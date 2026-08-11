# List 持久化批次后端 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用 SQLite 持久化 List、待发送队列、批次与批次分片，实现「条数阈值 + 最长等待」触发、启动恢复、部分分片重试和删除联动，并在入队可靠接管后推进 Feed 水位。

**Architecture:** 新增领域实体与仓储协议；`V5` 迁移建表并给 `rsshub_sub` 增加 `list_id`/`include_keywords`/`exclude_keywords`；`NotificationDispatcher` 在每个订阅循环处委托 `SubscriptionFilterService` 与 `ListQueueService`（未入 List 走原即时发送，入 List 走持久化入队）；`ListBatchCoordinator` 由调度器每分钟驱动，claim 后用 `SessionPushQueue` 串行发送已渲染分片。渲染结果（批次分片）持久化，重试只发未成功分片。AI 总结通过端口注入，具体 Provider 实现在 Pages/AI 计划中落地。

**Tech Stack:** Python 3.10+、SQLAlchemy/SQLModel + aiosqlite、asyncio、pytest。

## Global Constraints

- 一个订阅最多属于一个 List；List 绑定单一 `user_id`、`target_session`、`platform_name`。
- 加入 List 的订阅停止即时推送，改由 List 批量发送；移出后后续新条目恢复即时推送。
- 批次触发：达到 `batch_size` 立即生成；最早条目等待达到 `max_wait_minutes` 生成；一次 25 条阈值 10 生成 10/10/5。
- 入队是「可靠接管」：pending push_history + 队列项同事务写入；入队失败不推进 Feed 水位。
- 水位推进：规则性 `skipped` 和 `durably_queued` 可推进；`pending`/`failed`/异常不推进。
- 被过滤条目写 `status=skipped` 并推进水位；不重复判断。
- 队列项唯一约束 `(list_id, sub_id, entry_key)`；`entry_key` 优先 GUID，缺失用轮询稳定指纹。
- 批次分片持久化；重试只发未成功分片；AI 总结失败不阻塞正文。
- List 停用：不新入队，新条目按规则性 skipped 推进水位；已有队列保留。
- 订阅/Feed/用户删除：清理未发送队列项并把相关 history 标为 `skipped`；已发送审计保留。
- 不要增大 `notification_dispatcher.py`（1546 行）的责任；List 逻辑收敛到独立服务。

---

### Task 1: List 领域实体与关键词规则

**Files:**
- Create: `src/domain/entities/list_entities.py`
- Modify: `src/domain/__init__.py`
- Test: `tests/unit/domain/test_list_entities.py`

**Interfaces:**
- Consumes: `INHERIT_VALUE`（现有常量）、`datetime`。
- Produces: `ListEntity`、`ListQueueItem`、`ListBatch`、`ListBatchPart`、`ListBatchPartItem`，以及纯函数 `normalize_keywords` / `build_entry_key`。

- [ ] **Step 1: 写失败测试——实体与关键词归一化**

`tests/unit/domain/test_list_entities.py`：

```python
from astrbot_plugin_rsshub.src.domain.entities.list_entities import (
    ListEntity, ListQueueItem, ListBatch, ListBatchPart, ListBatchPartItem,
    normalize_keywords, build_entry_key,
)

def test_normalize_keywords_dedups_case_insensitive_and_strips():
    assert normalize_keywords(["  Python ", "python", " AI ", "", "  ai  "]) == ["python", "ai"]

def test_build_entry_key_falls_back_to_stable_fingerprint():
    assert build_entry_key(entry_guid="g-1", stable_fingerprint="sid:abc") == "g-1"
    assert build_entry_key(entry_guid="", stable_fingerprint="sid:abc") == "sid:abc"

def test_list_entity_defaults_and_mode_validation():
    lst = ListEntity(name="Tech", user_id="u1", target_session="s1", platform_name="telegram")
    assert lst.state == 1 and lst.batch_size == 10 and lst.max_wait_minutes == 120
    assert lst.content_mode == "full" and lst.full_delivery_mode == "split"

def test_queue_item_unique_key_is_entry_key_based():
    item = ListQueueItem(list_id=1, sub_id=2, entry_key="k")
    assert item.entry_key == "k"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `./tests/run_tests.sh --category unit`（或 `python -m pytest tests/unit/domain/test_list_entities.py -v`）
Expected: FAIL（模块不存在）。

- [ ] **Step 3: 实现领域实体**

`src/domain/entities/list_entities.py`：

```python
"""List 批次聚合领域实体。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

LIST_CONTENT_MODE_TITLE_LINK = "title_link"
LIST_CONTENT_MODE_FULL = "full"
LIST_FULL_DELIVERY_SPLIT = "split"
LIST_FULL_DELIVERY_AGGREGATE = "aggregate"

QUEUE_ITEM_STATES = ("queued", "claimed", "sent", "failed", "skipped")
BATCH_STATES = ("preparing", "ready", "sending", "success", "failed")
BATCH_PART_STATES = ("pending", "sending", "success", "failed")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def normalize_keywords(value: list[str] | tuple[str, ...] | None) -> list[str]:
    """去空白、去空项、大小写不敏感去重、保序。"""
    seen: set[str] = set()
    result: list[str] = []
    for item in value or []:
        text = str(item or "").strip()
        if not text:
            continue
        key = text.lower()
        if key not in seen:
            seen.add(key)
            result.append(text)
    return result


def build_entry_key(entry_guid: str, stable_fingerprint: str) -> str:
    """返回非空稳定幂等键：优先 GUID，缺失用轮询层稳定指纹。"""
    return (entry_guid or stable_fingerprint or "").strip() or "unknown"


@dataclass
class ListEntity:
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
    batch_part_id: int
    queue_item_id: int
    id: int | None = None
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/unit/domain/test_list_entities.py -v`
Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add src/domain/entities/list_entities.py src/domain/__init__.py tests/unit/domain/test_list_entities.py
git commit -m "feat(domain): List 批次领域实体与关键词归一化"
```

### Task 2: V5 迁移与 ORM 模型

**Files:**
- Create: `src/infrastructure/persistence/migrations/V5_create_list_batching.py`
- Modify: `src/infrastructure/persistence/models.py`
- Modify: `src/infrastructure/persistence/migrations/V1_init.py`
- Test: `tests/unit/infrastructure/test_database_manager.py`

**Interfaces:**
- Consumes: `RSSHubBaseModel`、SQLModel `Field`。
- Produces: 表 `rsshub_lists`、`rsshub_list_queue_items`、`rsshub_list_batches`、`rsshub_list_batch_parts`、`rsshub_list_batch_part_items`；`SubORM` 增加 `list_id`、`include_keywords`、`exclude_keywords`。

- [ ] **Step 1: 写失败测试——迁移建表与列**

```python
async def test_v5_migration_creates_list_tables_and_sub_columns():
    conn = _build_memory_conn()
    await conn.execute(text("CREATE TABLE rsshub_sub (id INTEGER PRIMARY KEY, user_id TEXT, feed_id INTEGER)"))
    from astrbot_plugin_rsshub.src.infrastructure.persistence.migrations import V5_create_list_batching
    await V5_create_list_batching.upgrade(conn)
    tables = [row[0] for row in (await conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))).all()]
    for t in ("rsshub_lists", "rsshub_list_queue_items", "rsshub_list_batches", "rsshub_list_batch_parts", "rsshub_list_batch_part_items"):
        assert t in tables
    cols = [row[1] for row in (await conn.execute(text("PRAGMA table_info(rsshub_sub)"))).all()]
    assert "list_id" in cols and "include_keywords" in cols and "exclude_keywords" in cols
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/unit/infrastructure/test_database_manager.py -v`
Expected: FAIL（V5 不存在）。

- [ ] **Step 3: 实现 ORM 模型与迁移**

在 `models.py` 增加：

```python
class ListORM(RSSHubBaseModel, table=True):
    __tablename__ = "rsshub_lists"
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(max_length=255)
    user_id: str = Field(foreign_key="rsshub_user.id", max_length=255)
    target_session: str = Field(max_length=255)
    platform_name: str = Field(default="", max_length=64)
    state: int = Field(default=1)
    batch_size: int = Field(default=10)
    max_wait_minutes: int = Field(default=120)
    content_mode: str = Field(default="full", max_length=16)
    full_delivery_mode: str = Field(default="split", max_length=16)
    ai_summary_enabled: bool = Field(default=False)
    ai_summary_prompt: str = Field(default="", max_length=4096)
    include_keywords: list[Any] | None = Field(default=None, sa_column=Column(JSON))
    exclude_keywords: list[Any] | None = Field(default=None, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class ListQueueItemORM(RSSHubBaseModel, table=True):
    __tablename__ = "rsshub_list_queue_items"
    id: int | None = Field(default=None, primary_key=True)
    list_id: int = Field(foreign_key="rsshub_lists.id", index=True)
    sub_id: int = Field(foreign_key="rsshub_sub.id", index=True)
    feed_id: int = Field(foreign_key="rsshub_feed.id", index=True)
    push_history_id: int = Field(index=True)
    entry_key: str = Field(max_length=1024)
    entry_title: str = Field(default="", max_length=1024)
    entry_link: str = Field(default="", max_length=4096)
    feed_title: str = Field(default="", max_length=1024)
    feed_link: str = Field(default="", max_length=4096)
    markdown_content: str = Field(default="")
    media_items: list[Any] | None = Field(default=None, sa_column=Column(JSON))
    queued_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), index=True)
    batch_id: int | None = Field(default=None, index=True)
    state: str = Field(default="queued", max_length=16)
    __table_args__ = (UniqueConstraint("list_id", "sub_id", "entry_key", name="uq_list_queue_item"),)

class ListBatchORM(RSSHubBaseModel, table=True):
    __tablename__ = "rsshub_list_batches"
    id: int | None = Field(default=None, primary_key=True)
    list_id: int = Field(foreign_key="rsshub_lists.id", index=True)
    state: str = Field(default="preparing", max_length=16)
    item_count: int = Field(default=0)
    summary_markdown: str = Field(default="")
    summary_status: str = Field(default="disabled", max_length=16)
    fail_reason: str = Field(default="")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: datetime | None = Field(default=None)
    completed_at: datetime | None = Field(default=None)

class ListBatchPartORM(RSSHubBaseModel, table=True):
    __tablename__ = "rsshub_list_batch_parts"
    id: int | None = Field(default=None, primary_key=True)
    batch_id: int = Field(foreign_key="rsshub_list_batches.id", index=True)
    sequence: int = Field(default=0)
    kind: str = Field(max_length=16)
    markdown_content: str = Field(default="")
    media_items: list[Any] | None = Field(default=None, sa_column=Column(JSON))
    state: str = Field(default="pending", max_length=16)
    fail_reason: str = Field(default="")
    sent_at: datetime | None = Field(default=None)
    __table_args__ = (UniqueConstraint("batch_id", "sequence", name="uq_batch_part_sequence"),)

class ListBatchPartItemORM(RSSHubBaseModel, table=True):
    __tablename__ = "rsshub_list_batch_part_items"
    id: int | None = Field(default=None, primary_key=True)
    batch_part_id: int = Field(foreign_key="rsshub_list_batch_parts.id", index=True)
    queue_item_id: int = Field(foreign_key="rsshub_list_queue_items.id", index=True)
    __table_args__ = (UniqueConstraint("batch_part_id", "queue_item_id", name="uq_batch_part_item"),)
```

`SubORM` 增加：

```python
    list_id: int | None = Field(default=None, foreign_key="rsshub_lists.id", index=True)
    include_keywords: list[Any] | None = Field(default=None, sa_column=Column(JSON))
    exclude_keywords: list[Any] | None = Field(default=None, sa_column=Column(JSON))
```

`V5_create_list_batching.py`：与上面 ORM 对应的 `CREATE TABLE IF NOT EXISTS` 语句，并在 `rsshub_sub` 上 `ALTER TABLE ADD COLUMN`（用 `PRAGMA table_info` 判断缺列才加，保持幂等）。

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/unit/infrastructure/test_database_manager.py -v`
Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add src/infrastructure/persistence/models.py src/infrastructure/persistence/migrations/V5_create_list_batching.py src/infrastructure/persistence/migrations/V1_init.py tests/unit/infrastructure/test_database_manager.py
git commit -m "feat(db): V5 迁移创建 List 批次表并扩展订阅列"
```

### Task 3: List 仓储协议与实现

**Files:**
- Create: `src/domain/repositories/list_repository.py`
- Create: `src/infrastructure/persistence/list_repository_impl.py`
- Modify: `src/infrastructure/persistence/__init__.py`
- Modify: `src/domain/__init__.py`
- Test: `tests/unit/infrastructure/test_list_repository_impl.py`

**Interfaces:**
- Consumes: 领域实体、ORM 模型。
- Produces: `ListRepository` Protocol 与 `ListRepositoryImpl`，方法见下。

`ListRepository` Protocol 方法签名（供后续任务消费）：

```python
class ListRepository(Protocol):
    # lists
    async def get_list(self, list_id: int) -> ListEntity | None
    async def get_lists_by_scope(self, user_id: str, target_session: str, platform_name: str) -> list[ListEntity]
    async def get_active_lists(self) -> list[ListEntity]
    async def save_list(self, entity: ListEntity) -> ListEntity
    async def delete_list(self, list_id: int) -> None
    # queue items
    async def enqueue_item(self, item: ListQueueItem) -> ListQueueItem  # unique(list_id,sub_id,entry_key)
    async def count_queued(self, list_id: int) -> int
    async def get_queued_items(self, list_id: int, limit: int | None = None) -> list[ListQueueItem]
    async def oldest_queued_at(self, list_id: int) -> datetime | None
    async def claim_items_for_batch(self, list_id: int, batch_id: int, limit: int) -> int  # queued -> claimed, return count
    async def mark_batch_items_sent(self, batch_id: int) -> int  # claimed -> sent
    async def mark_batch_items_failed(self, batch_id: int, reason: str) -> int
    async def mark_items_skipped(self, list_id: int, reason: str) -> int
    async def delete_by_sub(self, sub_id: int) -> int
    async def delete_by_feed(self, feed_id: int) -> int
    async def delete_by_list(self, list_id: int) -> int
    # batches
    async def create_batch(self, batch: ListBatch) -> ListBatch
    async def get_batch(self, batch_id: int) -> ListBatch | None
    async def update_batch(self, batch: ListBatch) -> None
    async def list_batches(self, list_id: int, limit: int = 20) -> list[ListBatch]
    # batch parts
    async def insert_parts(self, parts: list[ListBatchPart]) -> None
    async def get_parts(self, batch_id: int) -> list[ListBatchPart]
    async def update_part(self, part: ListBatchPart) -> None
    async def insert_part_items(self, pairs: list[tuple[int, int]]) -> None  # (part_id, queue_item_id)
    async def get_part_item_ids(self, batch_part_id: int) -> list[int]
```

- [ ] **Step 1: 写失败测试——仓储 CRUD 与 claim 语义**

`tests/unit/infrastructure/test_list_repository_impl.py` 使用 `temp_db_path` fixture：

```python
@pytest.mark.asyncio
async def test_enqueue_respects_unique_key_and_claim_transitions(temp_db_path):
    await get_database().init(str(temp_db_path))
    repo = ListRepositoryImpl()
    lst = await repo.save_list(ListEntity(name="Tech", user_id="u1", target_session="s1", platform_name="telegram"))
    item1 = await repo.enqueue_item(ListQueueItem(list_id=lst.id, sub_id=1, feed_id=1, push_history_id=11, entry_key="k"))
    assert item1.id is not None
    dup = await repo.enqueue_item(ListQueueItem(list_id=lst.id, sub_id=1, feed_id=1, push_history_id=12, entry_key="k"))
    assert dup.id is None or dup.id == item1.id  # 唯一约束，不产生第二条
    assert await repo.count_queued(lst.id) == 1
    batch = await repo.create_batch(ListBatch(list_id=lst.id, item_count=1))
    claimed = await repo.claim_items_for_batch(lst.id, batch.id, limit=10)
    assert claimed == 1
    sent = await repo.mark_batch_items_sent(batch.id)
    assert sent == 1
    assert await repo.count_queued(lst.id) == 0
    await get_database().close()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/unit/infrastructure/test_list_repository_impl.py -v`
Expected: FAIL（模块不存在）。

- [ ] **Step 3: 实现仓储**

`ListRepositoryImpl` 用 `get_database().get_session()` 打开会话，按实体↔ORM 映射完成上述方法。关键语义：

- `enqueue_item`：检查 `(list_id, sub_id, entry_key)` 是否已存在；存在则返回已存在项（幂等），不存在则插入。
- `claim_items_for_batch`：`UPDATE ... SET state='claimed', batch_id=:batch WHERE list_id=:list AND state='queued' ORDER BY queued_at, id LIMIT :limit`，返回受影响行数。
- `mark_batch_items_sent`：`UPDATE ... SET state='sent' WHERE batch_id=:batch AND state='claimed'`。
- `mark_items_skipped`：把 `list_id` 下 `queued`/`claimed` 置为 `skipped` 并清空 batch_id。
- `create_batch` 时若 `summary_status` 为 `pending` 则保持，否则默认 `disabled`。

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/unit/infrastructure/test_list_repository_impl.py -v`
Expected: PASS。

- [ ] **Step 5: 注册到包导出并提交**

```bash
git add src/domain/repositories/list_repository.py src/infrastructure/persistence/list_repository_impl.py src/domain/__init__.py src/infrastructure/persistence/__init__.py tests/unit/infrastructure/test_list_repository_impl.py
git commit -m "feat(persistence): List 批次仓储实现"
```

### Task 4: 订阅过滤服务

**Files:**
- Create: `src/application/services/subscription_filter_service.py`
- Modify: `src/application/services/__init__.py`
- Test: `tests/unit/application/test_subscription_filter_service.py`

**Interfaces:**
- Consumes: `normalize_keywords`。
- Produces:

```python
@dataclass(frozen=True)
class FilterResult:
    allowed: bool
    reason: str = ""

class SubscriptionFilterService:
    def matches(
        self, *,
        text: str,
        sub_include: list[str],
        sub_exclude: list[str],
        list_include: list[str] | None = None,
        list_exclude: list[str] | None = None,
    ) -> FilterResult
```

语义：屏蔽词取并集命中即拒；各层关注词层内 OR、层间 AND（任一层配置了关注词则必须命中）。`text` 为「标题 + 清洗后正文」，大小写不敏感子串匹配。

- [ ] **Step 1: 写失败测试——过滤矩阵**

```python
def test_exclude_wins_over_include():
    svc = SubscriptionFilterService()
    assert not svc.matches(text="Python 二手教程", sub_include=["python"], sub_exclude=["二手"]).allowed

def test_layer_include_or_and_across_layers():
    svc = SubscriptionFilterService()
    r = svc.matches(text="Python 教程", sub_include=["python"], list_include=["linux"])
    assert not r.allowed and "list include" in r.reason
    assert svc.matches(text="Python Linux 教程", sub_include=["python"], list_include=["linux"]).allowed

def test_no_include_is_pass_through_when_no_exclude():
    svc = SubscriptionFilterService()
    assert svc.matches(text="任何内容", sub_include=[], sub_exclude=[]).allowed

def test_case_insensitive_substring():
    svc = SubscriptionFilterService()
    assert svc.matches(text="PythoN 教程", sub_include=["python"]).allowed
    assert not svc.matches(text="Python 教程", sub_exclude=["PYTHON"]).allowed
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/unit/application/test_subscription_filter_service.py -v`
Expected: FAIL（模块不存在）。

- [ ] **Step 3: 实现**

```python
@dataclass(frozen=True)
class FilterResult:
    allowed: bool
    reason: str = ""

class SubscriptionFilterService:
    @staticmethod
    def matches(*, text, sub_include, sub_exclude, list_include=None, list_exclude=None) -> FilterResult:
        haystack = str(text or "").lower()
        def hit(keywords):
            return any(k and k.lower() in haystack for k in keywords or [])
        if hit(sub_exclude):
            return FilterResult(False, "filtered: subscription exclude keyword")
        if hit(list_exclude):
            return FilterResult(False, "filtered: list exclude keyword")
        if sub_include and not hit(sub_include):
            return FilterResult(False, "filtered: subscription include keywords not matched")
        if list_include and not hit(list_include):
            return FilterResult(False, "filtered: list include keywords not matched")
        return FilterResult(True)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/unit/application/test_subscription_filter_service.py -v`
Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add src/application/services/subscription_filter_service.py src/application/services/__init__.py tests/unit/application/test_subscription_filter_service.py
git commit -m "feat(filter): 订阅与 List 两级关键词过滤"
```

### Task 5: 持久化入队服务与 Dispatcher 路由

**Files:**
- Create: `src/application/services/list_queue_service.py`
- Modify: `src/application/services/notification_dispatcher.py`（在 per-sub 循环内最小分支）
- Modify: `src/application/services/feed_polling_service.py`（水位确认）
- Modify: `bootstrap.py`（装配 `ListQueueService` 到 Dispatcher）
- Test: `tests/unit/application/test_list_queue_service.py`、`tests/unit/application/test_notification_dispatcher.py`

**Interfaces:**
- Consumes: `SubscriptionFilterService`、`ListRepository`、`PushHistoryRepository`、`normalize_keywords`、`PushHistory`。
- Produces:

```python
class ListQueueService:
    async def enqueue_durable(self, *, list_id: int, sub_id: int, feed_id: int, entry_key: str,
        entry_title, entry_link, feed_title, feed_link, markdown_content, media_items,
        user_id, target_session, platform_name, raw_xml=None) -> EnqueueResult
```

`EnqueueResult` 为 `@dataclass(frozen=True)`：`durably_queued: bool`、`history_id: int | None`、`error: str = ""`。同事务写 `PushHistoryORM(status=pending)` 与 `ListQueueItemORM`；`target_session` 为空或 `push_history_id` 缺失视为失败且不推进水位。

`NotificationDispatcher` 路由（在 `dispatch_to_feed_subscribers` per-sub 循环、`_save_skipped_history` 之后、正常 send 之前）插入：

```python
list_id = int(getattr(sub, "list_id", 0) or 0)
if list_id:
    list_entity = await self._list_queue_service.load_list(list_id)
    if list_entity is not None and list_entity.is_active():
        filter_result = self._list_queue_service.filter_for_list(sub, list_entity, effective_content=effective_content, title=effective_title)
        if not filter_result.allowed:
            await self._save_skipped_history(..., reason=filter_result.reason)
            stats["skipped"] += 1
            continue
        enq = await self._list_queue_service.enqueue_durable(list_id=list_id, sub_id=sub.id, feed_id=feed_id, entry_key=entry_guid or stable_key, entry_title=effective_title, entry_link=effective_link, feed_title=feed_title, feed_link=feed_link, markdown_content=effective_content, media_items=normalized_media, user_id=sub.user_id, target_session=sub.target_session, platform_name=sub.platform_name)
        if enq.durably_queued:
            stats["durably_queued"] = stats.get("durably_queued", 0) + 1
        else:
            stats["failed"] += 1
            record_error_detail(enq.error)
        continue
```

`stable_key`：`FeedPollingService` 已为 entry 生成稳定身份指纹（`_hash_entry` 的 `sid:` 值）；Dispatcher 通过 `entry_guid` 参数传入，GUID 缺失时用 `entry_link` 兜底为 `build_entry_key` 输入。

- [ ] **Step 1: 写失败测试——入队事务与水位结果**

```python
@pytest.mark.asyncio
async def test_enqueue_durable_writes_history_and_queue_atomically(temp_db_path):
    await get_database().init(str(temp_db_path))
    repo = ListRepositoryImpl()
    lst = await repo.save_list(ListEntity(name="Tech", user_id="u1", target_session="s1", platform_name="telegram"))
    service = ListQueueService(list_repo=repo, push_history_repo=PushHistoryRepositoryImpl())
    result = await service.enqueue_durable(
        list_id=lst.id, sub_id=1, feed_id=1, entry_key="k",
        entry_title="T", entry_link="https://e.com/1", feed_title="F", feed_link="",
        markdown_content="正文", media_items=[], user_id="u1", target_session="s1", platform_name="telegram",
    )
    assert result.durably_queued is True and result.history_id is not None
    assert await repo.count_queued(lst.id) == 1
    await get_database().close()

@pytest.mark.asyncio
async def test_enqueue_durable_fails_without_target_session(temp_db_path):
    service = ListQueueService(list_repo=MagicMock(), push_history_repo=MagicMock())
    result = await service.enqueue_durable(
        list_id=1, sub_id=1, feed_id=1, entry_key="k", entry_title="", entry_link="",
        feed_title="", feed_link="", markdown_content="", media_items=[],
        user_id="u1", target_session="", platform_name="telegram",
    )
    assert result.durably_queued is False
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/unit/application/test_list_queue_service.py -v`
Expected: FAIL（模块不存在）。

- [ ] **Step 3: 实现 ListQueueService**

`enqueue_durable` 打开单会话，插入 `PushHistoryORM`（`status=pending`、`source_type=feed`、`source_key=f"feed:{feed_id}:sub:{sub_id}"`）与 `ListQueueItemORM`，`commit`，返回 `durably_queued=True`。异常回滚并返回 `error`。`filter_for_list` 复用 `SubscriptionFilterService.matches`，`text=title + "\n" + markdown_content`，keywords 来自 sub（`include_keywords`/`exclude_keywords`）与 list（归一化后）。

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/unit/application/test_list_queue_service.py tests/unit/application/test_notification_dispatcher.py -v`
Expected: PASS。

- [ ] **Step 5: Dispatcher 路由 + Feed 水位确认**

- 在 `notification_dispatcher.py` 的 `dispatch_to_feed_subscribers` 插入路由分支（如上）；构造 `stats["durably_queued"]`。
- `FeedPollingService` 中消费 `dispatch_to_feed_subscribers` 返回值处，把 `durably_queued` 与 `success` 一起视为「确认条目」（推进 `entry_hashes` / 条件请求水位）。找到对应确认逻辑位置（`_handle_dispatch_result` 或 `poll_feed_group` 内的 confirm 段），追加对 `durably_queued` 的确认。

- [ ] **Step 6: 运行回归**

Run: `python -m pytest tests/unit/application/test_feed_polling_service.py tests/unit/application/test_notification_dispatcher.py tests/unit/application/test_list_queue_service.py -v`
Expected: 全绿。

- [ ] **Step 7: 提交**

```bash
git add src/application/services/list_queue_service.py src/application/services/notification_dispatcher.py src/application/services/feed_polling_service.py bootstrap.py tests/unit/application/test_list_queue_service.py
git commit -m "feat(list): 持久化入队、Dispatcher 路由与 Feed 水位确认"
```

### Task 6: 批次协调器、渲染与部分分片重试

**Files:**
- Create: `src/application/services/list_batch_coordinator.py`
- Create: `src/application/services/list_batch_renderer.py`
- Modify: `bootstrap.py`
- Test: `tests/unit/application/test_list_batch_coordinator.py`

**Interfaces:**
- Consumes: `ListRepository`、`SubscriptionFilterService`、`ListQueueService`、`SessionPushQueue`、`NotificationDispatcher.send_to_session`（发送分片）、渲染端口。
- Produces:

```python
class ListBatchRenderer:
    def render_title_link(self, list_entity, items: list[ListQueueItem]) -> list[ListBatchPart]
    def render_full_split(self, list_entity, items) -> list[ListBatchPart]
    def render_full_aggregate(self, list_entity, items) -> list[ListBatchPart]

class ListBatchCoordinator:
    def __init__(self, *, list_repo, queue_repo, batch_repo, renderer, session_push_queue,
                 summary_provider=None) -> None
    async def tick(self) -> None          # 每分钟：触发达标/超时批次，恢复，重试失败批次
    async def recover(self) -> None       # 启动恢复 preparing/sending
```

渲染规则：
- `title_link`：按 `feed_title` 分组、组内按 `queued_at` 升序；`# List 名称` + `## feed` + `- [标题](链接)`；AI 总结为最后一个分片。
- `full_split`：每条 item 一个 `entry` 分片（`markdown_content` + `media_items`）；AI 总结最后一个分片。
- `full_aggregate`：`# List 名称` + 每 item `## 标题` + 正文 + `原文：[查看原文](链接)`，`---` 分隔；AI 总结最后。
- 分片 `markdown_content` 先按条目边界、再按段落边界、最后按 Markdown 感知拆分，不切断链接/代码围栏/转义；拆分结果一次生成并持久化，重试不重切。

Coordinator 语义：
- `tick` 对每个活跃 List：`count_queued >= batch_size` 或 `oldest_queued_at + max_wait <= now` 时 claim。
- claim 前用进程内 `asyncio.Lock`（key=`list:{id}`）避免并发重复。
- claim 后 `create_batch(state=preparing)` → `claim_items_for_batch` → 读取 items → `renderer` 生成分片 → `insert_parts` + `insert_part_items` → `update_batch(state=ready)` → 通过 `session_push_queue.enqueue(list.target_session, work=send_batch)` 串行发送。
- `send_batch` 内逐分片调用 `dispatcher.send_to_session(...)`；每个分片成功后 `update_part(state=success)`、失败 `update_part(state=failed, fail_reason=...)`；全部成功则 `mark_batch_items_sent` + `update_batch(state=success, completed_at)`；有失败则 `update_batch(state=failed, fail_reason)`。
- `recover`：把 `preparing/sending` 批次改为 `failed`（原因 `recovered after restart`），`claimed` 队列项回退为 `queued`，使失败批次可被页面或下轮重试。

- [ ] **Step 1: 写失败测试——达标触发与 10/10/5**

```python
@pytest.mark.asyncio
async def test_tick_creates_full_batches_for_25_items(temp_db_path):
    await get_database().init(str(temp_db_path))
    repo = ListRepositoryImpl()
    lst = await repo.save_list(ListEntity(name="Tech", user_id="u1", target_session="s1", platform_name="telegram", batch_size=10, content_mode="title_link"))
    for i in range(25):
        await repo.enqueue_item(ListQueueItem(list_id=lst.id, sub_id=1, feed_id=1, push_history_id=100 + i, entry_key=f"k{i}"))
    queue = SessionPushQueue()
    coordinator = ListBatchCoordinator(list_repo=repo, queue_repo=repo, batch_repo=repo, renderer=ListBatchRenderer(), session_push_queue=queue)
    await coordinator.tick()
    batches = await repo.list_batches(lst.id, limit=50)
    assert len(batches) == 2  # 10 + 10 完整批次，剩余 5 未入批
    assert batches[0].item_count == 10 and batches[1].item_count == 10
    assert await repo.count_queued(lst.id) == 5
    await get_database().close()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/unit/application/test_list_batch_coordinator.py -v`
Expected: FAIL（模块不存在）。

- [ ] **Step 3: 实现 Renderer 与 Coordinator**

按上面接口实现。`send_batch` 的发送用 `NotificationDispatcher.send_to_session`（`target=SendTarget(user_id, platform_name, target_session)`），并在 `session_push_queue.enqueue(session_id, work=..., description=f"list={list_id}, batch={batch_id}")` 中执行。

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/unit/application/test_list_batch_coordinator.py -v`
Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add src/application/services/list_batch_renderer.py src/application/services/list_batch_coordinator.py bootstrap.py tests/unit/application/test_list_batch_coordinator.py
git commit -m "feat(list): 批次协调、渲染与部分分片持久化"
```

### Task 7: 调度器接线与启动恢复

**Files:**
- Modify: `src/infrastructure/schedule/rss_scheduler.py`
- Modify: `bootstrap.py`
- Test: `tests/unit/application/test_list_batch_coordinator.py`（新增恢复用例）、`tests/unit/test_bootstrap_runtime.py`

**Interfaces:**
- Consumes: `ListBatchCoordinator`。
- Produces: `RSSScheduler(..., list_batch_coordinator=None)`；`run_periodic_task` 调用 `coordinator.tick()`；`start()` 调用 `coordinator.recover()`。

- [ ] **Step 1: 写失败测试——启动恢复 preparing 批次**

```python
@pytest.mark.asyncio
async def test_recover_marks_interrupted_batches_failed(temp_db_path):
    await get_database().init(str(temp_db_path))
    repo = ListRepositoryImpl()
    lst = await repo.save_list(ListEntity(name="Tech", user_id="u1", target_session="s1", platform_name="telegram"))
    batch = await repo.create_batch(ListBatch(list_id=lst.id, state="sending", item_count=2))
    coordinator = ListBatchCoordinator(list_repo=repo, queue_repo=repo, batch_repo=repo, renderer=ListBatchRenderer(), session_push_queue=SessionPushQueue())
    await coordinator.recover()
    recovered = await repo.get_batch(batch.id)
    assert recovered.state == "failed"
    assert "recovered" in recovered.fail_reason
    await get_database().close()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/unit/application/test_list_batch_coordinator.py -v`
Expected: FAIL（`recover` 不存在）。

- [ ] **Step 3: 实现调度接线**

- `RSSScheduler.__init__` 增加 `list_batch_coordinator: ListBatchCoordinator | None = None`；`start()` 内调用 `await self._list_batch_coordinator.recover()`（空值安全）；`run_periodic_task` 在 `_dispatch_pending_retries` 之后调用 `await self._list_batch_coordinator.tick()`。
- `bootstrap._start_scheduler` 把 `coordinator` 传入 `RSSScheduler`；在 `_build_dependencies` 装配 `ListRepositoryImpl`、`ListQueueService`、`ListBatchRenderer`、`ListBatchCoordinator`，并注入 `SessionPushQueue`。

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/unit/application/test_list_batch_coordinator.py tests/unit/test_bootstrap_runtime.py -v`
Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add src/infrastructure/schedule/rss_scheduler.py bootstrap.py tests/unit/application/test_list_batch_coordinator.py tests/unit/test_bootstrap_runtime.py
git commit -m "feat(scheduler): 调度器接线 List 批次协调与启动恢复"
```

### Task 8: List 感知的删除联动

**Files:**
- Modify: `src/application/commands/unsubscribe_feed_cmd.py`
- Modify: `src/application/commands/batch_unsubscribe_cmd.py`
- Modify: `src/application/commands/delete_user_cmd.py`（或对应删除用户入口）
- Modify: `src/interfaces/web_api.py`（Feed/订阅删除端点）
- Test: `tests/unit/application/test_list_queue_service.py`（删除联动）、`tests/unit/interfaces/test_web_api.py`

**Interfaces:**
- Consumes: `ListRepository.delete_by_sub` / `delete_by_feed` / `delete_by_list`。
- Produces: 删除订阅/Feed/用户时，清理未发送队列项并把对应 `push_history(status=pending)` 标为 `skipped`。

- [ ] **Step 1: 写失败测试——删除订阅清理队列并把历史标 skipped**

```python
@pytest.mark.asyncio
async def test_delete_by_sub_cleans_queue_and_marks_pending_history_skipped(temp_db_path):
    await get_database().init(str(temp_db_path))
    repo = ListRepositoryImpl()
    hist_repo = PushHistoryRepositoryImpl()
    lst = await repo.save_list(ListEntity(name="Tech", user_id="u1", target_session="s1", platform_name="telegram"))
    item = await repo.enqueue_item(ListQueueItem(list_id=lst.id, sub_id=1, feed_id=1, push_history_id=11, entry_key="k"))
    await repo.delete_by_sub(1)
    assert await repo.count_queued(lst.id) == 0
    # 订阅删除端点会把 push_history id=11 标为 skipped
    await get_database().close()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/unit/application/test_list_queue_service.py -v`
Expected: FAIL（`delete_by_sub` 不存在或行为不符）。

- [ ] **Step 3: 实现删除联动**

- `ListRepositoryImpl.delete_by_sub(sub_id)` 删除 `list_queue_items` 中该 sub 的未发送项，返回删除数。
- 删除订阅的 command（`unsubscribe_feed_cmd`、`batch_unsubscribe_cmd`）在删除后调用 `list_repo.delete_by_sub`，并把相关 `pending` push_history 标 `skipped`（reason `subscription removed`）。
- 删除 Feed 的端点调用 `delete_by_feed`；删除用户时级联删除该用户 Lists + 队列项（推送历史默认保留，仅把 `pending` 标 skipped）。
- 把这些新依赖通过构造器注入，保持 command 构造签名向后兼容（新增可选参数，默认 `None` 时跳过）。

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/unit/application/test_list_queue_service.py tests/unit/application/test_commands.py tests/unit/interfaces/test_web_api.py -v`
Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add src/application/commands/ src/interfaces/web_api.py tests/unit/application/test_list_queue_service.py tests/unit/application/test_commands.py tests/unit/interfaces/test_web_api.py
git commit -m "feat(list): 订阅/Feed/用户删除联动清理队列与历史"
```

### Task 9: 状态不变量与全量回归

**Files:**
- Test: `tests/unit/application/test_list_queue_service.py`、`tests/unit/application/test_list_batch_coordinator.py`、`tests/unit/infrastructure/test_list_repository_impl.py`

**Interfaces:**
- Consumes: 全部已完成组件。
- Produces: 覆盖水位移交、并发 claim 只执行一次、分片部分成功重试只发失败分片、停用语义。

- [ ] **Step 1: 写失败测试——并发入队只 claim 一次 + 部分分片重试只发失败分片**

```python
@pytest.mark.asyncio
async def test_concurrent_tick_only_claims_once(temp_db_path):
    await get_database().init(str(temp_db_path))
    repo = ListRepositoryImpl()
    lst = await repo.save_list(ListEntity(name="Tech", user_id="u1", target_session="s1", platform_name="telegram", batch_size=3, content_mode="title_link"))
    for i in range(3):
        await repo.enqueue_item(ListQueueItem(list_id=lst.id, sub_id=1, feed_id=1, push_history_id=200+i, entry_key=f"k{i}"))
    coordinator = ListBatchCoordinator(list_repo=repo, queue_repo=repo, batch_repo=repo, renderer=ListBatchRenderer(), session_push_queue=SessionPushQueue())
    await asyncio.gather(coordinator.tick(), coordinator.tick(), coordinator.tick())
    batches = await repo.list_batches(lst.id, limit=50)
    assert len(batches) == 1
    await get_database().close()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/unit/application/test_list_batch_coordinator.py -v`
Expected: 视实现结果，若出现重复批次则 FAIL；据此确认锁语义。

- [ ] **Step 3: 修复并发语义**

`ListBatchCoordinator.tick` 对每个 list 用 `asyncio.Lock` 串行化「检查+claim」，且 claim 条件在锁内重查（二次确认），确保并发 tick 不重复建批。

- [ ] **Step 4: 运行全量单测**

Run: `./tests/run_tests.sh --category unit`
Expected: 全绿。

- [ ] **Step 5: 运行 ruff**

Run: `cd .. && uv run ruff check data/plugins/astrbot_plugin_rsshub && uv run ruff format --check data/plugins/astrbot_plugin_rsshub`
Expected: 无错误。

- [ ] **Step 6: 提交**

```bash
git add tests/unit/application/test_list_queue_service.py tests/unit/application/test_list_batch_coordinator.py tests/unit/infrastructure/test_list_repository_impl.py src/application/services/list_batch_coordinator.py
git commit -m "test(list): 状态不变量与并发语义回归"
```
