"""List 持久化入队服务。

对加入 List 的订阅，把「过滤 → 写 pending push_history + 队列项」放在同一个
事务里完成，保证入队成功即视为可靠接管（可推进 Feed 水位）；任一步失败整体
回滚，不推进水位。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ...domain.entities.list_entities import ListEntity
from sqlalchemy.exc import IntegrityError

from ...infrastructure.persistence.database import get_database
from ...infrastructure.persistence.models import ListQueueItemORM, PushHistoryORM
from ...infrastructure.utils import get_logger
from .subscription_filter_service import FilterResult, SubscriptionFilterService

logger = get_logger()


@dataclass(frozen=True)
class EnqueueResult:
    """持久化入队结果。"""

    durably_queued: bool
    history_id: int | None = None
    error: str = ""
    already_queued: bool = False


class ListQueueService:
    """List 队列服务。"""

    def __init__(
        self,
        *,
        list_repo: Any,
        push_history_repo: Any | None = None,
        filter_service: SubscriptionFilterService | None = None,
    ) -> None:
        self._list_repo = list_repo
        self._push_history_repo = push_history_repo
        self._filter_service = filter_service or SubscriptionFilterService()

    async def load_list(self, list_id: int) -> ListEntity | None:
        """按 ID 加载 List。"""
        return await self._list_repo.get_list(list_id)

    def filter_for_list(
        self,
        sub: Any,
        list_entity: ListEntity,
        *,
        effective_content: str,
        title: str,
    ) -> FilterResult:
        """两级关键词过滤：订阅层 + List 层。"""
        text = f"{title}\n{effective_content}"
        return self._filter_service.matches(
            text=text,
            sub_include=getattr(sub, "include_keywords", None) or None,
            sub_exclude=getattr(sub, "exclude_keywords", None) or None,
            list_include=list_entity.include_keywords or None,
            list_exclude=list_entity.exclude_keywords or None,
        )

    async def enqueue_durable(
        self,
        *,
        list_id: int,
        sub_id: int,
        feed_id: int,
        entry_key: str,
        entry_title: str,
        entry_link: str,
        feed_title: str,
        feed_link: str,
        markdown_content: str,
        media_items: list[tuple[str, str]],
        user_id: str,
        target_session: str,
        platform_name: str,
        entry_guid: str | None = None,
        raw_xml: str | None = None,
    ) -> EnqueueResult:
        """把条目可靠写入 pending history + 队列项（同一事务）。

        返回 durably_queued=True 才可推进 Feed 水位；target_session 为空、
        队列项唯一约束冲突或任何异常都返回失败且不推进水位。
        """
        if not str(target_session or "").strip():
            return EnqueueResult(False, error="no target session")

        # 防御性检查：List 已停用时不入队（Dispatcher 已按规则性 skipped 处理，
        # 这里兜底避免绕过路由直接调用时误入队）。
        list_entity = await self._list_repo.get_list(list_id)
        if list_entity is None:
            return EnqueueResult(False, error="list not found")
        if not list_entity.is_active():
            return EnqueueResult(False, error="list disabled")

        db = get_database()
        try:
            async with db.get_session() as session:
                history_orm = PushHistoryORM(
                    sub_id=sub_id,
                    user_id=user_id,
                    feed_id=feed_id,
                    source_type="feed",
                    source_key=f"feed:{feed_id}:sub:{sub_id}",
                    content=markdown_content,
                    raw_xml=(raw_xml or "").strip() or None,
                    media_urls=[url for _type, url in media_items] or None,
                    entry_title=entry_title or "",
                    entry_link=entry_link or "",
                    entry_guid=(entry_guid or "").strip() or None,
                    feed_title=feed_title or "",
                    feed_link=feed_link or "",
                    platform_name=platform_name,
                    target_session=target_session,
                    status="pending",
                    retry_count=0,
                    max_retries=0,
                )
                session.add(history_orm)
                await session.flush()
                item_orm = ListQueueItemORM(
                    list_id=list_id,
                    sub_id=sub_id,
                    feed_id=feed_id,
                    push_history_id=int(history_orm.id or 0),
                    entry_key=entry_key,
                    entry_title=entry_title or "",
                    entry_link=entry_link or "",
                    feed_title=feed_title or "",
                    feed_link=feed_link or "",
                    markdown_content=markdown_content or "",
                    media_items=[list(m) for m in media_items] or None,
                    state="queued",
                )
                session.add(item_orm)
                await session.commit()
                return EnqueueResult(
                    durably_queued=True, history_id=int(history_orm.id or 0)
                )
        except IntegrityError:
            # 唯一索引冲突：(list_id, sub_id, entry_key) 已存在，说明该条目已入队。
            # 视为规则性幂等（already_queued），由 Dispatcher 计为 skipped 推进水位，
            # 避免把重复条目算成硬失败导致 Feed 条件请求回滚卡住。
            logger.debug(
                "List 条目已入队（幂等）: list=%s sub=%s key=%s", list_id, sub_id, entry_key
            )
            return EnqueueResult(False, error="already queued", already_queued=True)
        except Exception as exc:
            logger.warning(
                "List 入队失败: list=%s sub=%s key=%s err=%s",
                list_id,
                sub_id,
                entry_key,
                exc,
            )
            return EnqueueResult(False, error=str(exc))

    async def cleanup_subscription(self, sub_id: int) -> int:
        """删除订阅：清理未发送队列项，并把 pending 历史标为 skipped。"""
        deleted = await self._list_repo.delete_by_sub(sub_id)
        await self._mark_pending_history_skipped(
            [sub_id], reason="subscription removed"
        )
        return deleted

    async def cleanup_feed(self, feed_id: int) -> int:
        """删除 Feed：清理未发送队列项。"""
        return await self._list_repo.delete_by_feed(feed_id)

    async def clear_queue(self, list_id: int) -> int:
        """清空 List 队列：把 queued/claimed 置为 skipped。"""
        return await self._list_repo.mark_items_skipped(list_id, reason="cleared by user")

    async def deactivate_list(self, list_id: int) -> None:
        """停用 List：后续新条目按规则性 skipped，已有队列保留。"""
        lst = await self._list_repo.get_list(list_id)
        if lst is None:
            return
        lst.state = 0
        await self._list_repo.save_list(lst)

    async def cleanup_user(self, user_id: str) -> int:
        """删除用户：级联删除该用户 Lists + 队列项，pending 历史标 skipped。

        推送历史默认保留，仅把 pending 队列对应历史标为 skipped。
        """
        lists = await self._list_repo.get_lists_by_user(user_id)
        list_ids = [int(lst.id or 0) for lst in lists if lst.id]
        total = 0
        for list_id in list_ids:
            total += await self._list_repo.delete_by_list(list_id)
            await self._list_repo.delete_list(list_id)
        return total

    async def _mark_pending_history_skipped(
        self, sub_ids: list[int], reason: str
    ) -> None:
        if self._push_history_repo is None:
            return
        for sub_id in sub_ids:
            try:
                pending = await self._push_history_repo.get_by_sub(
                    sub_id, status="pending"
                )
                for history in pending:
                    history.mark_skipped(reason)
                    await self._push_history_repo.save(history)
            except Exception as exc:
                logger.warning(
                    "标记 pending 历史为 skipped 失败: sub=%s err=%s", sub_id, exc
                )
