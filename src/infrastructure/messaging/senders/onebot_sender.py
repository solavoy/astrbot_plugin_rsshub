"""QQ OneBot 消息发送器

针对 QQ OneBot 协议的特定优化。
支持合并转发节点（Nodes）。
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from astrbot.api.message_components import Node, Nodes, Plain

from ...utils import get_logger
from ..napcat_stream import upload_file_stream
from .base_sender import DefaultMessageSender
from .types import MessageContext, SendRequest, SendResult, get_bot_self_id

if TYPE_CHECKING:
    from ...pipeline import MessageComponent
    from .types import PreparedMedia

logger = get_logger()


class OneBotMessageSender(DefaultMessageSender):
    """QQ OneBot 平台消息发送器

    复用统一发送骨架，平台差异经钩子表达：合并转发始终走 `_maybe_route_alternate_channel`
    （Nodes：文字 + 图片/视频/音频/文件各自一个节点；经典合并转发失败时回退为纯文本
    Nodes；NapCat 流式上传 always/fallback 两种模式），URL-only/超限媒体经
    `_apply_first_send_candidates` 候选改写降级为链接。
    """

    @staticmethod
    def _strategy_value(strategy, key: str, default=None):
        if strategy is None:
            return default
        if isinstance(strategy, dict):
            return strategy.get(key, default)
        return getattr(strategy, key, default)

    @classmethod
    def _napcat_stream_mode(cls, context: MessageContext | None) -> str:
        """获取 NapCat stream 模式配置

        Returns:
            "disabled", "fallback", 或 "always"
        """
        strategy = getattr(context, "sender_strategy", None) if context else None
        value = cls._strategy_value(strategy, "napcat_stream_mode", None)
        if value is None:
            return cls._get_onebot_napcat_stream_mode_default()
        return str(value)

    @classmethod
    def _get_onebot_napcat_stream_mode_default(cls) -> str:
        """获取 OneBot NapCat stream 模式的默认值"""
        from ....shared.constants import ONEBOT_NAPCAT_STREAM_MODE_DEFAULT

        return str(
            getattr(
                cls,
                "_onebot_napcat_stream_mode_default",
                ONEBOT_NAPCAT_STREAM_MODE_DEFAULT,
            )
        )

    @classmethod
    def _resolve_bot_client(cls, context: MessageContext | None) -> Any | None:
        """解析可用于 NapCat stream 的 bot 客户端

        优先使用消息事件携带的 bot（命令响应场景），
        否则通过全局 provider 按平台名解析（主动推送场景）。
        """
        event = getattr(context, "event", None) if context else None
        if event is not None:
            bot = getattr(event, "bot", None) or getattr(event, "_bot", None)
            if bot is not None:
                return bot

        from .types import get_bot_client

        platform_name = getattr(context, "platform_name", "") if context else ""
        return get_bot_client(platform_name or "")

    @classmethod
    def _resolve_bot_self_id(cls, context: MessageContext | None) -> str:
        """解析 bot 的 self_id（QQ 号），用于合并转发节点的 user_id。

        解析顺序：
        1. 命令响应场景：从事件消息对象的 ``self_id`` 读取（最可靠）。
        2. 主动推送场景：通过全局 provider 按 platform_name 解析（由
           bootstrap 注册，读取 CQHttp 的 ``_wsr_api_clients``）。
        3. 无法确认时返回空串。调用方保留 AstrBot SDK 的默认 ``uin="0"``，
           由兼容该缺省值的 OneBot 实现自行处理，避免伪造其他 QQ 号。
        """
        if context is not None:
            event = getattr(context, "event", None)
            if event is not None:
                msg_obj = getattr(event, "message_obj", None)
                if msg_obj is not None:
                    self_id = getattr(msg_obj, "self_id", None)
                    if self_id and str(self_id) != "0":
                        return str(self_id)
            platform_name = getattr(context, "platform_name", "") or ""
            if platform_name:
                self_id = get_bot_self_id(platform_name)
                if self_id and str(self_id) != "0":
                    return str(self_id)
        return ""

    @staticmethod
    def _build_forward_node(content: list, nickname: str, bot_self_id: str) -> Node:
        """构建合并转发节点，仅在已确认 bot QQ 号时显式设置 uin。"""
        if bot_self_id:
            return Node(content=content, name=nickname, uin=bot_self_id)
        return Node(content=content, name=nickname)

    async def _maybe_route_alternate_channel(
        self,
        request: SendRequest,
        context: MessageContext | None,
        prepared_media: list[PreparedMedia] | None,
        components: list[MessageComponent],
        *,
        use_markdown: bool | None,
    ) -> SendResult | None:
        session_id = request.session_id
        napcat_mode = self._napcat_stream_mode(context)
        bot_client = self._resolve_bot_client(context)
        bot_self_id = self._resolve_bot_self_id(context)
        nickname = (
            context.channel.title if context and context.channel.title else "RSSHub"
        )

        from astrbot.api.message_components import File, Image, Record, Video

        nodes: list[Node] = []
        for component in components:
            node_content: list | None = None
            if component.kind == "text":
                node_content = [Plain(component.text or "RSS update")]
            elif component.kind == "media":
                match component.media_type:
                    case "image":
                        node_content = [Image(file=component.file)]
                    case "video":
                        node_content = [Video(file=component.file)]
            elif component.kind == "tail":
                match component.media_type:
                    case "audio":
                        node_content = [Record(file=component.file, text="audio")]
                    case "file":
                        node_content = [
                            File(
                                name=component.name or "attachment",
                                file=component.file,
                                url=component.original_url,
                            )
                        ]
            if node_content:
                nodes.append(
                    self._build_forward_node(node_content, nickname, bot_self_id)
                )

        if not nodes and request.message:
            nodes.append(
                self._build_forward_node(
                    [Plain(request.message)], nickname, bot_self_id
                )
            )
        if not nodes:
            return SendResult(ok=False, detail="empty_message")

        if napcat_mode == "always" and bot_client is not None:
            nodes = await self._stream_upload_nodes(bot_client, nodes)
        result = await self._send_chain(session_id, [Nodes(nodes)])

        if (
            not result.ok
            and napcat_mode == "fallback"
            and bot_client is not None
            and self._has_local_video_nodes(nodes)
        ):
            logger.warning(
                "OneBot send failed, trying NapCat stream fallback: session=%s",
                session_id,
            )
            streamed_nodes = await self._stream_upload_nodes(bot_client, nodes)
            result = await self._send_chain(session_id, [Nodes(streamed_nodes)])

        if not result.ok:
            logger.warning(
                "OneBot merged-forward send failed, fallback to text-only: "
                "session=%s, detail=%s",
                session_id,
                result.detail,
            )
            from ...pipeline.markdown_plain import markdown_to_plain

            failed_urls = self._formatter.collect_original_urls(prepared_media or [])
            fallback_message = (
                self._message_with_all_generated_fallbacks(request) or "RSS update"
            )
            fallback_message = markdown_to_plain(fallback_message)
            fallback_text = self._append_failed_links(fallback_message, failed_urls)
            fallback_nodes = [
                self._build_forward_node(
                    [Plain(fallback_text or "RSS update")], nickname, bot_self_id
                )
            ]
            return await self._send_chain(session_id, [Nodes(fallback_nodes)])
        return result

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

    async def _stream_upload_nodes(
        self, bot_client: Any, nodes: list[Node]
    ) -> list[Node]:
        """通过 NapCat Stream 上传节点中的本地视频文件

        Args:
            bot_client: 支持 call_action 的 bot 客户端
            nodes: 原始节点列表

        Returns:
            处理后的节点列表（本地视频文件路径替换为上传后的路径）
        """
        from astrbot.api.message_components import Video

        streamed_nodes: list[Node] = []
        for node in nodes:
            if not node.content:
                streamed_nodes.append(node)
                continue

            streamed_content = []
            for comp in node.content:
                if not isinstance(comp, Video):
                    streamed_content.append(comp)
                    continue

                local_path = self._extract_local_video_path(comp)
                if not local_path:
                    streamed_content.append(comp)
                    continue

                uploaded_path = await upload_file_stream(bot_client, local_path)
                if uploaded_path:
                    logger.info(
                        "[napcat_stream] 视频上传成功: local=%s, remote=%s",
                        local_path,
                        uploaded_path,
                    )
                    streamed_content.append(Video(file=uploaded_path))
                else:
                    logger.warning(
                        "[napcat_stream] 视频上传失败，保留原路径: local=%s",
                        local_path,
                    )
                    streamed_content.append(comp)

            streamed_nodes.append(
                Node(content=streamed_content, name=node.name, uin=node.uin)
            )

        return streamed_nodes

    def _has_local_video_nodes(self, nodes: list[Node]) -> bool:
        """检查节点列表中是否包含本地视频文件"""
        from astrbot.api.message_components import Video

        for node in nodes:
            if not node.content:
                continue
            for comp in node.content:
                if isinstance(comp, Video) and self._extract_local_video_path(comp):
                    return True
        return False

    @staticmethod
    def _extract_local_video_path(video_comp) -> Path | None:
        """从 Video 组件中提取本地文件路径

        Args:
            video_comp: Video 组件

        Returns:
            本地文件路径，如果不是本地文件则返回 None
        """
        file_value = getattr(video_comp, "file", None)
        if not isinstance(file_value, str) or not file_value:
            return None

        # 处理 file:/// 协议
        if file_value.startswith("file:///"):
            path = Path(file_value[8:])
        elif file_value.startswith("http://") or file_value.startswith("https://"):
            # 跳过 HTTP URL
            return None
        else:
            path = Path(file_value)

        return path if path.exists() and path.is_file() else None
