"""List 批次渲染器。

根据 List 的内容模式把一组队列项渲染为持久化分片：
- title_link：按 Feed 分组输出标题 + 链接。
- full_split：每条队列项一个 entry 分片。
- full_aggregate：全部条目合并为一个 aggregate 分片。

分片在 claim 后一次性生成并持久化；重试只发未成功分片，不重新拆分。
"""

from __future__ import annotations

from ...domain.entities.list_entities import (
    LIST_CONTENT_MODE_FULL,
    LIST_CONTENT_MODE_TITLE_LINK,
    LIST_FULL_DELIVERY_AGGREGATE,
    LIST_FULL_DELIVERY_SPLIT,
    ListBatchPart,
    ListEntity,
    ListQueueItem,
)


class ListBatchRenderer:
    """把队列项渲染为批次分片。"""

    def render_title_link(
        self, list_entity: ListEntity, items: list[ListQueueItem]
    ) -> list[ListBatchPart]:
        """标题 + 链接模式：按 Feed 分组聚合为一个分片。"""
        lines = [f"# {list_entity.name}"]
        grouped: dict[str, list[ListQueueItem]] = {}
        order: list[str] = []
        for item in items:
            feed = item.feed_title or "未命名 Feed"
            if feed not in grouped:
                grouped[feed] = []
                order.append(feed)
            grouped[feed].append(item)
        for feed in order:
            lines.append(f"## {feed}")
            for item in grouped[feed]:
                link = item.entry_link or item.entry_link
                lines.append(f"- [{item.entry_title or item.entry_key}]({link})")
        return [
            ListBatchPart(
                batch_id=0,
                sequence=0,
                kind="aggregate",
                markdown_content="\n".join(lines),
            )
        ]

    def render_full_split(
        self, list_entity: ListEntity, items: list[ListQueueItem]
    ) -> list[ListBatchPart]:
        """全文拆分模式：每条队列项一个 entry 分片。"""
        parts: list[ListBatchPart] = []
        for index, item in enumerate(items):
            parts.append(
                ListBatchPart(
                    batch_id=0,
                    sequence=index,
                    kind="entry",
                    markdown_content=item.markdown_content or "",
                    media_items=item.media_items,
                )
            )
        return parts

    def render_full_aggregate(
        self, list_entity: ListEntity, items: list[ListQueueItem]
    ) -> list[ListBatchPart]:
        """全文聚合模式：所有条目合并为一个分片。"""
        lines = [f"# {list_entity.name}"]
        for index, item in enumerate(items):
            if index > 0:
                lines.append("---")
            lines.append(f"## {item.entry_title or item.entry_key}")
            if item.markdown_content:
                lines.append(item.markdown_content)
            if item.entry_link:
                lines.append(f"原文：[查看原文]({item.entry_link})")
        return [
            ListBatchPart(
                batch_id=0,
                sequence=0,
                kind="aggregate",
                markdown_content="\n\n".join(lines),
            )
        ]

    def make_summary_part(
        self, batch_id: int, sequence: int, summary_text: str
    ) -> ListBatchPart:
        """构造 AI 总结分片（在总结完成后追加）。"""
        return ListBatchPart(
            batch_id=batch_id,
            sequence=sequence,
            kind="summary",
            markdown_content=summary_text,
        )

    def render(
        self, list_entity: ListEntity, items: list[ListQueueItem]
    ) -> list[ListBatchPart]:
        """按 List 内容模式分发渲染。"""
        mode = list_entity.content_mode
        if mode == LIST_CONTENT_MODE_TITLE_LINK:
            return self.render_title_link(list_entity, items)
        if mode == LIST_CONTENT_MODE_FULL:
            if list_entity.full_delivery_mode == LIST_FULL_DELIVERY_AGGREGATE:
                return self.render_full_aggregate(list_entity, items)
            if list_entity.full_delivery_mode == LIST_FULL_DELIVERY_SPLIT:
                return self.render_full_split(list_entity, items)
            return self.render_full_split(list_entity, items)
        return self.render_title_link(list_entity, items)
