"""List 批次聚合领域实体。

List 是把多个订阅归为一组、按「条数阈值 + 最长等待」批量推送的逻辑集合。
这里只定义实体、状态常量与纯函数，不包含任何持久化逻辑。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

LIST_CONTENT_MODE_TITLE_LINK = "title_link"
LIST_CONTENT_MODE_FULL = "full"
LIST_FULL_DELIVERY_SPLIT = "split"
LIST_FULL_DELIVERY_AGGREGATE = "aggregate"

# 队列项状态：queued(排队) / claimed(已入批) / sent(已发送) / failed(失败) / skipped(跳过)
QUEUE_ITEM_STATES = ("queued", "claimed", "sent", "failed", "skipped")
# 批次状态
BATCH_STATES = ("preparing", "ready", "sending", "success", "failed")
# 批次分片状态
BATCH_PART_STATES = ("pending", "sending", "success", "failed")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def normalize_keywords(value: list[str] | tuple[str, ...] | None) -> list[str]:
    """去空白、去空项、大小写不敏感去重、统一小写、保序。"""
    seen: set[str] = set()
    result: list[str] = []
    for item in value or []:
        text = str(item or "").strip().lower()
        if not text:
            continue
        if text not in seen:
            seen.add(text)
            result.append(text)
    return result


def build_entry_key(entry_guid: str, stable_fingerprint: str) -> str:
    """返回非空稳定幂等键：优先 GUID，缺失用轮询层稳定指纹。"""
    return (entry_guid or stable_fingerprint or "").strip() or "unknown"


@dataclass
class ListEntity:
    """List 逻辑集合实体。"""

    name: str
    user_id: str
    target_session: str
    platform_name: str
    id: int | None = None
    state: int = 1
    batch_size: int = 10
    max_wait_minutes: int = 120
    content_mode: str = LIST_CONTENT_MODE_FULL
    full_delivery_mode: str = LIST_FULL_DELIVERY_SPLIT
    ai_summary_enabled: bool = False
    ai_summary_prompt: str = ""
    include_keywords: list[str] = field(default_factory=list)
    exclude_keywords: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)

    def is_active(self) -> bool:
        return self.state == 1


@dataclass
class ListQueueItem:
    """待发送队列项，随 push_history 同事务持久化。"""

    list_id: int
    sub_id: int
    feed_id: int
    push_history_id: int
    entry_key: str
    entry_title: str = ""
    entry_link: str = ""
    feed_title: str = ""
    feed_link: str = ""
    markdown_content: str = ""
    media_items: tuple[tuple[str, str], ...] = ()
    queued_at: datetime = field(default_factory=_now)
    batch_id: int | None = None
    state: str = "queued"
    id: int | None = None


@dataclass
class ListBatch:
    """一个待发送批次，对应一次 List 聚合推送。"""

    list_id: int
    state: str = "preparing"
    item_count: int = 0
    summary_markdown: str = ""
    summary_status: str = "disabled"
    fail_reason: str = ""
    created_at: datetime = field(default_factory=_now)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    id: int | None = None


@dataclass
class ListBatchPart:
    """批次分片，是实际发送单元（entry / aggregate / summary）。"""

    batch_id: int
    sequence: int
    kind: str  # entry | aggregate | summary
    markdown_content: str = ""
    media_items: tuple[tuple[str, str], ...] = ()
    state: str = "pending"
    fail_reason: str = ""
    sent_at: datetime | None = None
    id: int | None = None


@dataclass
class ListBatchPartItem:
    """分片与队列项的关联（供部分分片重试使用）。"""

    batch_part_id: int
    queue_item_id: int
    id: int | None = None
