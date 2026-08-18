"""消息格式化器

统一各平台消息组件（图片/文字/音频/文件）的排序规则。
senders 只管发送，排序逻辑全部集中在 Formatter 中。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...domain.entities.content_types import is_generated_media_url

if TYPE_CHECKING:
    from ..messaging.senders.types import PreparedMedia

from .components import MessageComponent, MessageComponentSorter


class MessageChainFormatter:
    """消息链格式化器

    根据平台特性将预处理后的媒体和文本组合为最终消息链。
    排序规则统一在此管理，senders 只调用 build_chain() 后发送。
    """

    _sorter: MessageComponentSorter = MessageComponentSorter()

    def build_components(
        self,
        prepared_media: list[PreparedMedia] | None,
        text: str,
        failed_urls: list[str],
        platform: str = "",
    ) -> list[MessageComponent]:
        """
        构建平台无关消息组件。
        """
        return self._sorter.build_components(
            prepared_media=prepared_media,
            text=text,
            failed_urls=failed_urls,
            platform=platform,
        )

    def build_chain_from_components(
        self,
        components: list[MessageComponent],
        platform: str = "",
    ) -> list:
        """把平台无关组件转为最终消息链。顺序统一为 正文 → 媒体 → 尾（sorter 已保证）。"""
        return self._components_to_chain(components)

    @staticmethod
    def collect_original_urls(
        prepared_media: list[PreparedMedia] | None,
    ) -> list[str]:
        """Collect all original media URLs in first-seen order."""
        if not prepared_media:
            return []
        urls: list[str] = []
        seen: set[str] = set()
        for item in prepared_media:
            url = str(item.original_url or "").strip()
            if is_generated_media_url(url):
                continue
            if url and url not in seen:
                urls.append(url)
                seen.add(url)
        return urls

    # ------------------------------------------------------------------
    # 通用顺序：images → Plain → tails
    # ------------------------------------------------------------------

    def _components_to_chain(self, components: list[MessageComponent]) -> list:
        """Convert platform-neutral components to AstrBot message components."""
        from astrbot.api.message_components import File, Image, Plain, Record, Video

        chain: list = []
        for component in components:
            if component.kind == "text" and component.text:
                chain.append(Plain(component.text))
            elif component.kind == "media":
                match component.media_type:
                    case "image":
                        chain.append(Image(file=component.file))
                    case "video":
                        chain.append(Video(file=component.file))
            elif component.kind == "tail":
                match component.media_type:
                    case "audio":
                        chain.append(Record(file=component.file, text="audio"))
                    case "file":
                        chain.append(
                            File(
                                name=component.name or "attachment",
                                file=component.file,
                                url=component.original_url,
                            )
                        )
        return chain

    # ------------------------------------------------------------------
    # 工具
    # ------------------------------------------------------------------

    @staticmethod
    def _append_failed_links(text: str, failed_urls: list[str]) -> str:
        """将下载失败的媒体链接追加到文本末尾"""
        return MessageComponentSorter.append_failed_links(text, failed_urls)
