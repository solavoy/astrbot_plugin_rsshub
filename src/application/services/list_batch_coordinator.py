"""List 批次协调器。

每分钟由调度器驱动一次 tick：对每个活跃 List，按「条数阈值 + 最长等待」
触发批次 claim，渲染分片并持久化，再经 SessionPushQueue 串行发送。
启动时 recover() 把中断批次标为 failed、claimed 队列项回退 queued，
使失败批次可被页面或下轮重试。AI 总结通过 summary_provider 端口注入。
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

from ...domain.entities.list_entities import ListBatch, ListEntity, ListQueueItem
from ...infrastructure.utils import get_logger
from .notification_dispatcher import SendTarget
from .session_push_queue import SessionPushQueue

logger = get_logger()


class ListBatchCoordinator:
    """List 批次协调器。"""

    def __init__(
        self,
        *,
        list_repo: Any,
        queue_repo: Any,
        batch_repo: Any,
        renderer: Any,
        session_push_queue: SessionPushQueue | None = None,
        summary_provider: Any | None = None,
        dispatcher: Any | None = None,
        push_history_repo: Any | None = None,
    ) -> None:
        self._list_repo = list_repo
        self._queue_repo = queue_repo
        self._batch_repo = batch_repo
        self._renderer = renderer
        self._session_push_queue = session_push_queue
        self._summary_provider = summary_provider
        self._dispatcher = dispatcher
        self._push_history_repo = push_history_repo
        self._locks: dict[int, asyncio.Lock] = {}

    def _lock_for(self, list_id: int) -> asyncio.Lock:
        if list_id not in self._locks:
            self._locks[list_id] = asyncio.Lock()
        return self._locks[list_id]

    async def tick(self) -> None:
        """对每个活跃 List 触发达标/超时批次。"""
        lists = await self._list_repo.get_active_lists()
        now = datetime.now(timezone.utc)
        for list_entity in lists:
            list_id = int(list_entity.id or 0)
            if list_id <= 0:
                continue
            async with self._lock_for(list_id):
                while True:
                    count = await self._queue_repo.count_queued(list_id)
                    if count >= list_entity.batch_size:
                        await self._create_batch(
                            list_entity, claim_limit=list_entity.batch_size
                        )
                        continue
                    oldest = await self._queue_repo.oldest_queued_at(list_id)
                    if oldest is not None and count > 0:
                        if oldest.tzinfo is None:
                            oldest = oldest.replace(tzinfo=timezone.utc)
                        deadline = oldest + timedelta(
                            minutes=list_entity.max_wait_minutes
                        )
                        if deadline <= now:
                            await self._create_batch(list_entity, claim_limit=count)
                            continue
                    break

    async def recover(self) -> None:
        """启动恢复：中断批次标为 failed，claimed 队列项回退 queued。"""
        batches = await self._batch_repo.list_incomplete_batches()
        for batch in batches:
            batch.state = "failed"
            batch.fail_reason = "recovered after restart"
            await self._batch_repo.update_batch(batch)
            await self._queue_repo.requeue_batch_items(batch.id)
            logger.info(
                "启动恢复: 批次 %s 标记为 failed 并回退队列项", batch.id
            )

    async def _create_batch(
        self, list_entity: ListEntity, claim_limit: int
    ) -> None:
        """claim 队列项、渲染分片、持久化并排队发送。"""
        list_id = int(list_entity.id or 0)
        batch = await self._batch_repo.create_batch(
            ListBatch(list_id=list_id, state="preparing", item_count=0)
        )
        claimed = await self._queue_repo.claim_items_for_batch(
            list_id, batch.id, limit=claim_limit
        )
        if claimed == 0:
            batch.state = "failed"
            batch.fail_reason = "no items claimed"
            await self._batch_repo.update_batch(batch)
            return
        items = await self._queue_repo.get_batch_items(batch.id)
        parts = self._renderer.render(list_entity, items)
        for part in parts:
            part.batch_id = batch.id
        await self._batch_repo.insert_parts(parts)
        await self._batch_repo.insert_part_items(
            self._build_part_item_pairs(parts, items)
        )
        batch.item_count = claimed
        batch.state = "ready"
        await self._batch_repo.update_batch(batch)
        await self._enqueue_send(list_entity, batch.id)

    @staticmethod
    def _build_part_item_pairs(
        parts: list[Any], items: list[ListQueueItem]
    ) -> list[tuple[int, int]]:
        pairs: list[tuple[int, int]] = []
        if len(parts) == 1 and parts[0].kind == "aggregate":
            for item in items:
                pairs.append((parts[0].id, item.id))
        else:
            entry_parts = [p for p in parts if p.kind == "entry"]
            for part, item in zip(entry_parts, items):
                if part.id is not None and item.id is not None:
                    pairs.append((part.id, item.id))
        return pairs

    async def _enqueue_send(self, list_entity: ListEntity, batch_id: int) -> None:
        if self._session_push_queue is None:
            return
        await self._session_push_queue.enqueue(
            list_entity.target_session,
            work=lambda job: self._send_batch(list_entity, batch_id),
            description=f"list={list_entity.id}, batch={batch_id}",
        )

    async def _send_batch(self, list_entity: ListEntity, batch_id: int) -> None:
        """逐分片发送；成功/失败更新分片状态，全部成功才确认队列项。"""
        if self._dispatcher is None:
            return
        batch = await self._batch_repo.get_batch(batch_id)
        if batch is None:
            return
        now = datetime.now(timezone.utc)
        batch.state = "sending"
        batch.started_at = now
        await self._batch_repo.update_batch(batch)

        try:
            await self._send_batch_parts(list_entity, batch)
        except asyncio.CancelledError:
            # 批次发送被 /sub_stop 等取消：标记 failed 并回退队列项，
            # 供启动恢复或页面重试继续；随后向上传播取消。
            try:
                batch.state = "failed"
                batch.fail_reason = "send cancelled"
                batch.completed_at = datetime.now(timezone.utc)
                await self._batch_repo.update_batch(batch)
                await self._queue_repo.requeue_batch_items(batch_id)
            except Exception as exc:
                logger.warning("取消批次 %s 清理失败: %s", batch_id, exc)
            raise

    async def _send_batch_parts(
        self, list_entity: ListEntity, batch: Any
    ) -> None:
        batch_id = batch.id
        parts = await self._batch_repo.get_parts(batch_id)
        success_all = True
        target = SendTarget(
            user_id=list_entity.user_id,
            platform_name=list_entity.platform_name,
            target_session=list_entity.target_session,
        )
        for part in parts:
            if part.state == "success":
                continue
            try:
                # 批次 job 已在会话队列内，直接发送避免 SessionPushQueue 重入死锁。
                result = await self._dispatcher.send_to_session_now(
                    target=target,
                    content=part.markdown_content,
                    media_urls=[url for _t, url in part.media_items] or None,
                    media_items=list(part.media_items) or None,
                    job_description=(
                        f"list={list_entity.id}, batch={batch_id}, part={part.id}"
                    ),
                )
                if result.get("ok"):
                    part.state = "success"
                    part.sent_at = datetime.now(timezone.utc)
                    part.fail_reason = ""
                else:
                    part.state = "failed"
                    part.fail_reason = str(result.get("error") or "send failed")
                    success_all = False
            except Exception as exc:
                part.state = "failed"
                part.fail_reason = str(exc)
                success_all = False
            await self._batch_repo.update_part(part)
            await self._mark_part_history(
                part, success=(part.state == "success")
            )

        if success_all:
            await self._queue_repo.mark_batch_items_sent(batch_id)
            batch.state = "success"
            batch.fail_reason = ""
            batch.completed_at = datetime.now(timezone.utc)
            await self._batch_repo.update_batch(batch)
            await self._maybe_generate_summary(list_entity, batch)
        else:
            await self._queue_repo.mark_batch_items_failed(
                batch_id, "some parts failed"
            )
            batch.state = "failed"
            batch.fail_reason = "some parts failed"
            batch.completed_at = datetime.now(timezone.utc)
            await self._batch_repo.update_batch(batch)

    async def _mark_part_history(self, part: Any, *, success: bool) -> None:
        """把分片关联队列项的 push_history 标记为 success / failed。

        失败 reason 复用分片 fail_reason；缺 push_history_repo 时静默跳过。
        """
        if self._push_history_repo is None:
            return
        try:
            item_ids = await self._batch_repo.get_part_item_ids(part.id)
        except Exception as exc:
            logger.warning("读取分片 %s 队列项失败: %s", part.id, exc)
            return
        for item_id in item_ids:
            try:
                item = await self._batch_repo.get_queue_item(item_id)
            except Exception:
                item = None
            if item is None or not item.push_history_id:
                continue
            try:
                history = await self._push_history_repo.get_by_id(
                    item.push_history_id
                )
                if history is None:
                    continue
                if success:
                    history.mark_success()
                else:
                    history.mark_failed(part.fail_reason or "batch part failed")
                await self._push_history_repo.save(history)
            except Exception as exc:
                logger.warning(
                    "标记 push_history %s 失败: %s", item.push_history_id, exc
                )

    async def _maybe_generate_summary(
        self, list_entity: ListEntity, batch: ListBatch
    ) -> None:
        """正文全部成功后生成 AI 总结；失败不阻塞批次 success。"""
        if not list_entity.ai_summary_enabled:
            return
        if batch.summary_status == "success":
            return
        if self._summary_provider is None:
            return
        parts = await self._batch_repo.get_parts(batch.id)
        items: list[ListQueueItem] = await self._batch_repo.get_batch_items(
            batch.id
        )
        title_links = [
            f"- [{item.entry_title or item.entry_key}]({item.entry_link})"
            for item in items
        ]
        try:
            summary_text = await self._summary_provider.summarize_batch(
                list_entity=list_entity,
                items_title_link=title_links,
                prompt=list_entity.ai_summary_prompt,
            )
            batch.summary_markdown = summary_text
            summary_part = self._renderer.make_summary_part(
                batch.id, len(parts), summary_text
            )
            await self._batch_repo.insert_parts([summary_part])
            # 发送总结分片：失败只影响总结，正文批次保持 success（fail-open）。
            summary_ok = await self._send_summary_part(list_entity, summary_part)
            batch.summary_status = "success" if summary_ok else "failed"
            if not summary_ok and summary_part.fail_reason:
                batch.fail_reason = summary_part.fail_reason[:500]
            await self._batch_repo.update_batch(batch)
        except Exception as exc:
            logger.warning(
                "List 批次 %s AI 总结失败（正文已成功）: %s", batch.id, exc
            )
            batch.summary_status = "failed"
            batch.fail_reason = str(exc)[:500]
            await self._batch_repo.update_batch(batch)

    async def _send_summary_part(
        self, list_entity: ListEntity, part: Any
    ) -> bool:
        """发送单个 AI 总结分片，返回是否成功。"""
        if self._dispatcher is None:
            return False
        try:
            result = await self._dispatcher.send_to_session_now(
                target=SendTarget(
                    user_id=list_entity.user_id,
                    platform_name=list_entity.platform_name,
                    target_session=list_entity.target_session,
                ),
                content=part.markdown_content,
                media_urls=None,
                media_items=list(part.media_items) or None,
                job_description=f"list={list_entity.id}, batch={part.batch_id}, summary",
            )
            if result.get("ok"):
                part.state = "success"
                part.sent_at = datetime.now(timezone.utc)
                part.fail_reason = ""
                await self._batch_repo.update_part(part)
                return True
            part.state = "failed"
            part.fail_reason = str(result.get("error") or "summary send failed")
            await self._batch_repo.update_part(part)
            return False
        except Exception as exc:
            logger.warning("List 批次 %s AI 总结分片发送失败: %s", part.batch_id, exc)
            part.state = "failed"
            part.fail_reason = str(exc)[:500]
            await self._batch_repo.update_part(part)
            return False

    async def flush_list(self, list_id: int) -> int:
        """立即把当前排队项 claim 为一个批次并发送（Plugin Pages 手动触发）。"""
        list_entity = await self._list_repo.get_list(list_id)
        if list_entity is None:
            return 0
        async with self._lock_for(list_id):
            # 锁内重查 count：并发 flush 或 tick 已 claim 后，这里读到 0 直接返回，
            # 避免第二个调用创建 0 条 claim 的幽灵失败批次。
            count = await self._queue_repo.count_queued(list_id)
            if count <= 0:
                return 0
            await self._create_batch(list_entity, claim_limit=count)
            return count

    async def retry_batch(self, batch_id: int) -> None:
        """重发 failed 批次中未成功的分片。"""
        batch = await self._batch_repo.get_batch(batch_id)
        if batch is None or batch.state != "failed":
            return
        list_entity = await self._list_repo.get_list(batch.list_id)
        if list_entity is None:
            return
        parts = await self._batch_repo.get_parts(batch_id)
        if not parts:
            return
        # 已失败分片重新排队发送；成功分片保持 success 不重发。
        batch.state = "sending"
        await self._batch_repo.update_batch(batch)
        await self._enqueue_send(list_entity, batch_id)
