"""QQ 官方 Bot 消息发送器

针对 QQ 官方 Bot 的特定优化。
组件排序由 MessageFormatter 统一处理，此处只负责发送。
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from ....shared.constants import (
    QQ_OFFICIAL_DEGRADE_STRATEGY_FAIL,
    QQ_OFFICIAL_DEGRADE_STRATEGY_FILE_THEN_LINK,
    QQ_OFFICIAL_DEGRADE_STRATEGY_LINK_ONLY,
)
from ...pipeline import MessageComponent
from .base_sender import DefaultMessageSender
from .types import MessageContext, SendRequest, SendResult

if TYPE_CHECKING:
    from .types import PreparedMedia


class QQOfficialMessageSender(DefaultMessageSender):
    """QQ 官方 Bot 消息发送器

    特性：
    - 主动推送临时统一纯文本
    - 组件排序由 MessageFormatter 统一
    - 复用统一发送骨架，平台差异经钩子表达：候选改写、阈值降级、Markdown 解析
    """

    def _apply_first_send_candidates(
        self,
        components: list[MessageComponent],
        prepared_media_by_url: dict[str, PreparedMedia] | None,
        *,
        platform: str,
    ) -> list[MessageComponent]:
        return self._apply_media_send_candidates(
            components, prepared_media_by_url, platform=platform
        )

    def _resolve_use_markdown(
        self, context: MessageContext | None, platform: str
    ) -> bool:
        return bool(self._use_markdown_for_context(context))

    async def _maybe_degrade_before_send(
        self,
        request: SendRequest,
        components: list[MessageComponent],
        *,
        use_markdown: bool | None,
        platform: str,
    ) -> SendResult | None:
        # 阈值降级路径成功送达时返回 ok=True，即"QQ 官方降级送达视为成功，
        # 不应触发轮询补推"——等价于已删除的
        # DefaultMessageSender._counts_degraded_media_delivery_as_success 语义。
        return await self._maybe_send_threshold_degrade(
            request, components, use_markdown=use_markdown
        )

    async def _maybe_retry_after_failed_send(
        self,
        request: SendRequest,
        failed_result: SendResult,
        components: list[MessageComponent],
        prepared_media_by_url: dict[str, PreparedMedia] | None,
        *,
        use_markdown: bool | None,
    ) -> SendResult:
        """统一骨架单链发送失败后的 QQ 官方降级重试。

        统一骨架把全部正文与媒体合成一条 chain 发送；若平台在发送时刻拒绝某个媒体，
        整条 chain 大概率整体未送达。旧实现（已删除的 _send_components_media_first /
        _counts_degraded_media_delivery_as_success）会在这种发送时刻失败时为每个媒体
        尝试 _send_component_fallback_candidates（文件候选 → 原文链接文本），丢失的
        媒体 URL 折入（重发的）正文文本。此处经新钩子恢复该语义。

        判定口径：只有"正文被某种形式真实送达"（生成媒体纯文本回退 / 重发正文文本）
        才返回 ok=True——避免正文根本没到用户手里却被标记为成功，导致轮询不再补推。
        仅某媒体降级为文件送达不构成"消息已送达"。

        注意：这是"发送时刻失败"的降级，与 _maybe_degrade_before_send 的阈值预判降级
        相互独立（默认阈值 0 不触发预判，但发送失败仍走这里）。
        """
        strategy = self._get_qq_official_degrade_strategy()
        if strategy == QQ_OFFICIAL_DEGRADE_STRATEGY_FAIL:
            return await self._retry_text_with_generated_fallbacks(
                request,
                failed_result,
                use_markdown=use_markdown,
            )

        media_components = [
            component for component in components if self._is_media_component(component)
        ]
        if not media_components:
            # 纯文本失败：不静默重发正文，保持旧的“单一阶段失败”语义，交给轮询补推。
            return failed_result

        failures: list[SendResult] = [failed_result]
        failed_urls: list[str] = []
        # 正文是否已真实送达（生成回退成功 / 正文（含链接）重发成功）。
        text_delivered = False

        # 先生成媒体纯文本回退（只作用于 layout 中带 fallback_text 的生成媒体）；命中即
        # 视为正文已送出，仍要继续处理失败的非生成媒体，避免静默丢失其链接。
        generated = await self._retry_text_with_generated_fallbacks(
            request,
            failed_result,
            use_markdown=use_markdown,
        )
        if generated is not failed_result:
            text_delivered = True

        try_file_fallback = strategy == QQ_OFFICIAL_DEGRADE_STRATEGY_FILE_THEN_LINK
        for component in media_components:
            # 生成占位媒体已由上面纯文本回退连同正文送出，不再重复降级。
            if text_delivered and component.fallback_text:
                continue
            if try_file_fallback and self._media_has_remaining_fallback(
                component, prepared_media_by_url
            ):
                fallback = await self._send_component_fallback_candidates(
                    request.session_id,
                    component,
                    prepared_media_by_url=prepared_media_by_url,
                    platform="qq_official",
                    skip_first_file=component.file,
                    use_markdown=use_markdown,
                )
                failures.extend(fallback.failures)
                if fallback.ok:
                    continue
            # 无法（或未）降级为文件候选的媒体：URL 折入待发文本
            self._record_failed_url(failed_urls, component)

        if failed_urls:
            if text_delivered:
                # 正文已由上一步送出，只补发失败媒体链接清单，避免重复正文。
                text_result = await self._send_failed_links_only(
                    request,
                    failed_urls,
                    use_markdown=use_markdown,
                )
            else:
                text_result = await self._send_failed_media_links_text(
                    request,
                    components,
                    failed_urls,
                    use_markdown=use_markdown,
                )
            if text_result.ok:
                text_delivered = True
            else:
                failures.append(self._result_with_stage(text_result, "degrade_text"))
        elif not text_delivered:
            # 媒体全部降级送达但正文始终没送出：必须把正文文本补发出去。
            text_result = await self._send_failed_media_links_text(
                request,
                components,
                [],
                use_markdown=use_markdown,
            )
            if text_result.ok:
                text_delivered = True
            else:
                failures.append(self._result_with_stage(text_result, "degrade_text"))

        if text_delivered:
            return SendResult(ok=True)
        return self._partial_send_result(failures)

    def _media_has_remaining_fallback(
        self,
        component: MessageComponent,
        prepared_media_by_url: dict[str, PreparedMedia] | None,
    ) -> bool:
        """该媒体在已发送的首候选之外是否还有可尝试的兜底候选。"""
        from ..media_send_planner import MediaSendPlanner

        prepared = (
            prepared_media_by_url.get(component.original_url)
            if prepared_media_by_url and component.original_url
            else None
        )
        if prepared is not None:
            candidates = MediaSendPlanner.candidates_for(
                prepared,
                platform="qq_official",
            )
        else:
            candidates = [self._component_to_file_candidate(component)]
        return any(
            candidate.action != "link"
            and not self._should_skip_fallback_candidate(
                candidate,
                component,
                skip_first_file=component.file,
            )
            for candidate in candidates
        )

    def _should_degrade_for_media_count(
        self,
        components: list[MessageComponent],
    ) -> bool:
        threshold = self._get_qq_official_media_threshold()
        if threshold <= 0:
            return False
        media_count = sum(1 for item in components if self._is_media_component(item))
        return media_count > threshold

    async def _maybe_send_threshold_degrade(
        self,
        request: SendRequest,
        components: list[MessageComponent],
        *,
        use_markdown: bool | None = None,
    ) -> SendResult | None:
        if not self._should_degrade_for_media_count(components):
            return None

        strategy = self._get_qq_official_degrade_strategy()
        if strategy == QQ_OFFICIAL_DEGRADE_STRATEGY_FAIL:
            return SendResult(
                ok=False,
                transient=False,
                detail=self._stage_error_detail(
                    "degrade_threshold",
                    "qq_official_media_threshold_exceeded",
                ),
            )
        if strategy == QQ_OFFICIAL_DEGRADE_STRATEGY_LINK_ONLY:
            return await self._send_link_only_degrade(
                request,
                components,
                use_markdown=use_markdown,
            )
        if strategy == QQ_OFFICIAL_DEGRADE_STRATEGY_FILE_THEN_LINK:
            if not self._can_degrade_media_as_files(components):
                return None
            return await self._send_file_then_link_degrade(
                request,
                components,
                use_markdown=use_markdown,
            )
        return None

    async def _send_link_only_degrade(
        self,
        request: SendRequest,
        components: list[MessageComponent],
        *,
        use_markdown: bool | None = None,
    ) -> SendResult:
        failed_urls = [
            item.original_url for item in components if self._is_media_component(item)
        ]
        return await self._send_failed_media_links_text(
            request,
            components,
            failed_urls,
            use_markdown=use_markdown,
        )

    async def _send_file_then_link_degrade(
        self,
        request: SendRequest,
        components: list[MessageComponent],
        *,
        use_markdown: bool | None = None,
    ) -> SendResult:
        media_components = [
            item for item in components if self._is_media_component(item)
        ]
        failures: list[SendResult] = []
        failed_urls: list[str] = []

        for component in media_components:
            fallback = await self._send_component_fallback_candidates(
                request.session_id,
                component,
                prepared_media_by_url=None,
                platform="qq_official",
            )
            if not fallback.ok:
                self._record_failed_url(failed_urls, component)
            failures.extend(fallback.failures)

        text_result = await self._send_failed_media_links_text(
            request,
            components,
            failed_urls,
            use_markdown=use_markdown,
        )
        if not text_result.ok:
            failures.append(self._result_with_stage(text_result, "degrade_text"))
            return self._partial_send_result(failures)
        return SendResult(ok=True)

    @staticmethod
    def _can_degrade_media_as_files(components: list[MessageComponent]) -> bool:
        media_components = [
            item
            for item in components
            if item.kind in {"media", "tail"} and item.original_url
        ]
        if not media_components:
            return False
        return all(item.file and "://" not in item.file for item in media_components)

    async def _send_failed_media_links_text(
        self,
        request: SendRequest,
        components: list[MessageComponent],
        failed_urls: list[str],
        *,
        use_markdown: bool | None = None,
    ) -> SendResult:
        text = "\n".join(
            item.text for item in components if item.kind == "text" and item.text
        ).strip()
        text = self._append_failed_links(text or request.message, failed_urls)
        if not text:
            return SendResult(ok=False, detail="empty_message")

        from astrbot.api.message_components import Plain

        return await self._send_chain(
            request.session_id,
            [Plain(text)],
            use_markdown=use_markdown,
        )

    async def _send_failed_links_only(
        self,
        request: SendRequest,
        failed_urls: list[str],
        *,
        use_markdown: bool | None = None,
    ) -> SendResult:
        """正文已送出时，只补发失败媒体链接清单，避免重复正文。"""
        text = self._append_failed_links("", failed_urls)
        if not text:
            return SendResult(ok=False, detail="empty_message")

        from astrbot.api.message_components import Plain

        return await self._send_chain(
            request.session_id,
            [Plain(text)],
            use_markdown=use_markdown,
        )

    @classmethod
    def _use_markdown_for_context(
        cls,
        context: MessageContext | None,
    ) -> bool | None:
        # Temporary compatibility guard: QQ Official active pushes stay plain text
        # until AstrBot core no longer leaks Markdown syntax in normal payloads.
        return False

    async def _send_media_as_file(
        self,
        session_id: str,
        component: MessageComponent,
    ) -> SendResult:
        file_path = str(component.file or "").strip()
        if not file_path or "://" in file_path:
            return SendResult(
                ok=False,
                detail=self._stage_error_detail(
                    "degrade_file",
                    "degrade_file_unavailable",
                ),
            )

        from astrbot.api.message_components import File

        name = component.name or Path(file_path).name or "attachment"
        return await self._send_chain(
            session_id,
            [
                File(
                    name=name,
                    file=file_path,
                    url=component.original_url,
                )
            ],
        )
