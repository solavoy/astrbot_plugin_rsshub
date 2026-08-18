"""Telegram 消息发送器

针对 Telegram 平台的特定优化。
组件排序由 MessageChainFormatter 统一处理，此处只负责发送。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...config import get_config_manager
from ...pipeline import MessageChainFormatter
from ...utils import get_logger
from .base_sender import DefaultMessageSender
from .telegraph_client import TelegraphClient
from .types import MessageContext, SendRequest, SendResult

if TYPE_CHECKING:
    from ...pipeline import MessageComponent
    from .types import PreparedMedia

logger = get_logger()


class TelegramMessageSender(DefaultMessageSender):
    """Telegram 平台消息发送器

    特性：
    - 正文在前、媒体在后（单条链，caption = 正文写在小链首，媒体随后）
    - 组件排序由 MessageChainFormatter 统一（platform="telegram"）
    """

    @staticmethod
    def _strategy_value(strategy, key: str, default=None):
        if strategy is None:
            return default
        if isinstance(strategy, dict):
            return strategy.get(key, default)
        return getattr(strategy, key, default)

    @staticmethod
    def _strategy_from_templates(sender_strategies, template_key: str):
        templates = (
            sender_strategies.get("platform_strategies")
            if isinstance(sender_strategies, dict)
            else getattr(sender_strategies, "platform_strategies", None)
        )
        if not isinstance(templates, list):
            return None
        return next(
            (
                item
                for item in templates
                if isinstance(item, dict) and item.get("__template_key") == template_key
            ),
            None,
        )

    @classmethod
    def _get_timeout_seconds(cls) -> int:
        """Telegram 可能需要更长的超时"""
        return max(1, int(getattr(cls, "_timeout_seconds", 60)))

    @staticmethod
    def _context_render_markdown(context: MessageContext | None) -> bool | None:
        """内容是否为 Markdown 排版（Telegram adapter 按 MarkdownV2 渲染）。

        返回 ``None`` 时不改动 MessageChain 的 markdown 标记（保持默认纯文本）。
        """
        render = bool(getattr(context, "render_markdown", False)) if context else False
        return True if render else None

    @classmethod
    def _should_use_telegraph(
        cls,
        context: MessageContext | None,
        prepared_media,
    ) -> tuple[bool, str, str]:
        if context is None or context.send_mode != 0:
            return False, "", ""

        strategy = getattr(context, "sender_strategy", None)
        if strategy is None:
            try:
                config = get_config_manager()
                sender_strategies = getattr(config, "sender_strategies", None)
                strategy = cls._strategy_from_templates(
                    sender_strategies, "telegram_strategy"
                )
                if strategy is None:
                    strategy = (
                        sender_strategies.get("telegram")
                        if isinstance(sender_strategies, dict)
                        else getattr(
                            sender_strategies,
                            "telegram_settings",
                            getattr(sender_strategies, "telegram", None),
                        )
                    )
            except Exception:
                strategy = None

        enabled = bool(cls._strategy_value(strategy, "enable_telegraph", False))
        token = str(cls._strategy_value(strategy, "telegraph_token", "") or "").strip()
        proxy = cls._normalize_telegraph_proxy(
            cls._strategy_value(strategy, "telegraph_proxy", "")
        )
        if not enabled or not token:
            return False, "", ""

        unique_urls = MessageChainFormatter.collect_original_urls(prepared_media)
        return len(unique_urls) > 1, token, proxy

    @staticmethod
    def _normalize_telegraph_proxy(value) -> str:
        """归一化 Telegraph 代理：裸 host:port 按 http:// 处理；留空即直连。

        策略可能来自原始配置模板（未归一化）或已解析的设置对象（已归一化），
        此规则幂等，重复应用安全。
        """
        proxy = str(value or "").strip()
        if not proxy:
            return ""
        if "://" not in proxy:
            return f"http://{proxy}"
        return proxy

    async def _send_via_telegraph(
        self,
        *,
        session_id: str,
        request: SendRequest,
        context: MessageContext | None,
        prepared_media,
        token: str,
        proxy: str = "",
    ) -> SendResult:
        media_urls = MessageChainFormatter.collect_original_urls(prepared_media)
        client = TelegraphClient(
            access_token=token,
            timeout_seconds=self._get_timeout_seconds(),
            proxy=proxy,
        )
        page_title = (
            str(getattr(context, "entry_title", "") or "").strip() if context else ""
        )
        if not page_title:
            page_title = (
                context.channel.title if context and context.channel.title else "RSSHub"
            )
        page_url = await client.create_media_page(
            title=page_title,
            content=request.message,
            media_urls=media_urls,
            channel=context.channel if context else None,
        )
        message = self._build_telegraph_message(
            request.message,
            page_url,
            context=context,
        )
        from astrbot.api.message_components import Plain

        return await self._send_chain(
            session_id,
            [Plain(message)],
            use_markdown=self._context_render_markdown(context),
        )

    @staticmethod
    def _build_telegraph_message(
        content: str,
        page_url: str,
        *,
        context: MessageContext | None,
    ) -> str:
        text = str(content or "").strip()
        if page_url and page_url not in text:
            text = f"{text}\n\n{page_url}" if text else page_url
        return text

    async def _maybe_route_alternate_channel(
        self,
        request: SendRequest,
        context: MessageContext | None,
        prepared_media: list[PreparedMedia] | None,
        components: list[MessageComponent],
        *,
        use_markdown: bool | None,
    ) -> SendResult | None:
        effective_prepared = prepared_media or []
        use_telegraph, token, proxy = self._should_use_telegraph(
            context, effective_prepared
        )
        if not use_telegraph:
            return None
        try:
            return await self._send_via_telegraph(
                session_id=request.session_id,
                request=request,
                context=context,
                prepared_media=effective_prepared,
                token=token,
                proxy=proxy,
            )
        except Exception as err:
            logger.warning(
                "Telegram Telegraph fallback to native send: session=%s, error=%s",
                request.session_id,
                err,
            )
            return None

    def _resolve_use_markdown(
        self, context: MessageContext | None, platform: str
    ) -> bool:
        return bool(self._context_render_markdown(context))

    def _apply_first_send_candidates(
        self,
        components: list[MessageComponent],
        prepared_media_by_url: dict[str, PreparedMedia] | None,
        *,
        platform: str,
    ) -> list[MessageComponent]:
        """发送前按平台策略把组件改写为第一个可发送候选。

        Telegram 也走 MediaSendPlanner 候选改写：超出 photo 上限的本地媒体
        会降级为 document/file 发送（原 Telegram 专属 `_normalize_planned_media` 行为）。
        """
        return self._apply_media_send_candidates(
            components, prepared_media_by_url, platform="telegram"
        )
