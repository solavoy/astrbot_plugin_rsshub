# 统一 Markdown 发送链路 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将所有普通推送收敛为「规范 Markdown 唯一正文 + 集中媒体」，修复飞书多图时正文重复，并移除 `style` 与 `markdown_platforms`。

**Architecture:** 在现有 `MessageChainFormatter` / `MessageComponentSorter` 与平台 sender 之上做最小收敛：默认发送顺序固定为 正文→图片→视频→音频→文件；移除 sender 中所有 `original` layout 分支；`EntryTextFormatter` 统一输出规范 Markdown，sender 在边界做平台渲染或纯文本降级；从配置模型、schema、常量、bootstrap 装配、导入导出和 AI/XML 直推工具中删除 `style` 与 `markdown_platforms`。

**Tech Stack:** Python 3.10+、SQLAlchemy/SQLModel（迁移）、Pydantic（配置模型）、AstrBot `MessageChain` 组件、pytest。

## Global Constraints

- 一条逻辑消息只能有一个正文组件；sender 不得按媒体数量复制正文。
- 自动顺序固定为：`正文 → 图片 → 视频 → 音频 → 文件`。
- 内部规范 Markdown 不提前硬编码 Telegram MarkdownV2 转义；平台渲染/降级在 sender 边界完成。
- `push_history.content` 保存规范 Markdown，保证重试与审计一致。
- 飞书（默认 sender）多图必须表现为「正文一次、图片连续」。
- 彻底移除 `style` 与 `markdown_platforms`：从配置模型、`_conf_schema.json`、`runtime_settings`、`settings_builder`、`constants`、`bootstrap` 装配、`_conf_schema.json` 自愈、导入导出和 AI tool 参数中全部删除。
- QQ Official 的 `markdown_mode` 属平台发送能力控制，保留用于 sender 渲染/降级决策；不删除。
- 迁移 `V4_*` 删除订阅/用户表的 `style` 列；迁移可重复执行并兼容列已不存在。
- 旧 TOML 导入中的 `style` 明确报告为「字段已移除并忽略」；新导出不含该字段。
- 旧 AI/XML 直推工具调用传入 `style` 时由参数校验明确拒绝。

---

### Task 1: Markdown 规范化与消息组件单一正文不变量

**Files:**
- Modify: `src/infrastructure/pipeline/entry_formatter.py`
- Modify: `src/infrastructure/pipeline/components.py`
- Modify: `src/infrastructure/pipeline/formatter.py`
- Test: `tests/unit/infrastructure/test_message_formatter.py`

**Interfaces:**
- Consumes: `EffectivePushOptions`, `EntryFormatInput`, `EntryOutputFormat`, `MessageComponent`, `MessageComponentSorter`, `MessageChainFormatter` (现有)。
- Produces: `EntryTextFormatter.format_entry(..., output_format=EntryOutputFormat.MARKDOWN)` 始终输出规范 Markdown 正文；`MessageComponentSorter.build_components` 保证媒体组件去重后仅追加一个 `text` 组件；`MessageChainFormatter._components_to_chain` 保证平台无关链只有一个 `Plain`。

- [ ] **Step 1: 写失败测试——飞书多图正文唯一**

在 `tests/unit/infrastructure/test_message_formatter.py` 末尾新增：

```python
def test_multiple_images_never_duplicate_body_text():
    formatter = MessageFormatter()
    components = formatter.build_components(
        prepared_media=[
            PreparedMedia(media_type="image", original_url="https://example.com/a.jpg", local_path="/tmp/a.jpg"),
            PreparedMedia(media_type="image", original_url="https://example.com/b.jpg", local_path="/tmp/b.jpg"),
            PreparedMedia(media_type="image", original_url="https://example.com/c.jpg", local_path="/tmp/c.jpg"),
        ],
        text="正文",
        failed_urls=[],
        platform="",  # 默认 sender（飞书等）
    )
    texts = [c.text for c in components if c.kind == "text"]
    images = [c for c in components if c.kind == "media" and c.media_type == "image"]
    assert len(texts) == 1 and texts[0] == "正文"
    assert len(images) == 3
    # 顺序固定：正文在最前，图片依次连续
    assert components[0].kind == "text"
    assert [c.media_type for c in components[1:]] == ["image", "image", "image"]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `./tests/run_tests.sh --category unit`（或 `python -m pytest tests/unit/infrastructure/test_message_formatter.py::test_multiple_images_never_duplicate_body_text -v`）
Expected: FAIL（当前 `sort_components` 把 text 排在 media 之后，且组件顺序为 media 先、text 后）。

- [ ] **Step 3: 实现单一正文 + 集中媒体顺序**

在 `src/infrastructure/pipeline/components.py` 的 `MessageComponentSorter.sort_components` 中，把所有平台的 text 排序键改为固定最小优先：

```python
def order(component: MessageComponent) -> tuple[int, int]:
    if component.kind == "text":
        return (0, 0)
    if component.kind == "media":
        return (media_order.get(component.media_type, 99), 0)
    if component.kind == "tail":
        return (media_order.get(component.media_type, 99) + 200, 0)
    return (300, 0)
```

同时在 `_build_media_components` 中做 URL 去重，避免同一媒体 URL 重复出现：

```python
seen_urls: set[str] = set()
for item in prepared_media:
    if item.download_failed or item.oversize:
        continue
    if not item.local_path and not item.original_url:
        continue
    if item.original_url in seen_urls:
        continue
    seen_urls.add(item.original_url)
    dispatch = MediaDispatchResolver.resolve_prepared(item)
    if not dispatch.media_type:
        continue
    ...
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/unit/infrastructure/test_message_formatter.py -v`
Expected: 新增测试 PASS，且既有顺序测试按新契约通过（见 Task 1 Step 5 的既有测试迁移说明）。

- [ ] **Step 5: 迁移既有顺序断言**

既有测试 `test_message_component_sorter_orders_media_before_text_for_onebot`、`test_message_formatter_build_components_keeps_default_media_text_tail_order`、`test_telegram_chain_keeps_failed_media_as_url_component`、`test_telegram_chain_does_not_truncate_caption_text` 需要按新契约更新：

- OneBot 用例期望由 `media → media → tail → text` 改为 `text → media → media → tail`。
- 默认顺序用例期望由 `media(image) → text → tail(audio)` 改为 `text → media(image) → tail(audio)`。
- Telegram 失败链接用例 `test_telegram_chain_keeps_failed_media_as_url_component` 期望不变（text 仍为唯一组件），但断言顺序需与排序一致。

Run: `python -m pytest tests/unit/infrastructure/test_message_formatter.py tests/unit/infrastructure/test_onebot_sender.py tests/unit/infrastructure/test_platform_sequence_senders.py -v`
Expected: 全绿。

- [ ] **Step 6: 提交**

```bash
git add src/infrastructure/pipeline/components.py src/infrastructure/pipeline/formatter.py tests/unit/infrastructure/test_message_formatter.py tests/unit/infrastructure/test_onebot_sender.py tests/unit/infrastructure/test_platform_sequence_senders.py
git commit -m "fix(sender): 统一正文唯一与集中媒体顺序，修复多图正文重复"
```

### Task 2: EntryTextFormatter 统一输出规范 Markdown

**Files:**
- Modify: `src/infrastructure/pipeline/entry_formatter.py`
- Modify: `src/application/services/feed_polling_service.py:44,791`
- Modify: `src/application/services/notification_dispatcher.py`（`_format_effective_entry_content`、`_format_dispatch_content_async`）
- Modify: `src/application/services/agent_xml_push_service.py`（格式化入口）
- Test: `tests/unit/infrastructure/test_message_formatter.py`、`tests/unit/application/test_notification_dispatcher.py`

**Interfaces:**
- Consumes: `EntryOutputFormat` 枚举。
- Produces: `EntryTextFormatter.resolve_output_format(platform)` 删除（不再按平台选择），`format_entry` 默认走 Markdown；`_format_markdown` 成为唯一输出路径。

- [ ] **Step 1: 写失败测试——format_entry 默认输出 Markdown**

```python
@pytest.mark.asyncio
async def test_format_entry_defaults_to_markdown():
    text = await EntryTextFormatter().format_entry(
        EntryFormatInput(title="T", content="Body", link="https://e.com/x", feed_title="F"),
        EffectivePushOptions(),
    )
    assert text.startswith("**T**")
    assert "\n\n---\n\n" in text
    assert "via [https://e\\.com/x](https://e\\.com/x) | F" in text
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/unit/infrastructure/test_message_formatter.py::test_format_entry_defaults_to_markdown -v`
Expected: FAIL（当前默认 `EntryOutputFormat.PLAIN`）。

- [ ] **Step 3: 实现默认 Markdown**

在 `EntryTextFormatter.format_entry` 中把默认 `output_format` 改为 `EntryOutputFormat.MARKDOWN`，并删除 `resolve_output_format` 及其对 `_markdown_platforms` 的依赖；保留 `configure_markdown_platforms` 的启动装配兼容（Task 4 会整体移除）。

```python
async def format_entry(
    self,
    entry: EntryFormatInput,
    options: EffectivePushOptions | None = None,
    output_format: EntryOutputFormat | str = EntryOutputFormat.MARKDOWN,
) -> str:
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/unit/infrastructure/test_message_formatter.py -v`
Expected: PASS。

- [ ] **Step 5: 更新调用方为 Markdown**

- `feed_polling_service._format_dispatch_content_async` 已调用 `format_entry`，默认即 Markdown；无需改动签名。
- `notification_dispatcher._format_effective_entry_content`（约 1267-1284 行）构造 `EntryFormatInput` 后调用 `format_entry`；保持默认即可。
- `agent_xml_push_service` 中调用 `format_entry` 的位置保持默认。

- [ ] **Step 6: 删除 `resolve_output_format` 并迁移测试**

删除 `EntryTextFormatter.resolve_output_format` 与 `configure_markdown_platforms` 的调用点（`test_resolve_output_format_*` 测试一并删除）；`test_entry_text_formatter_can_render_lightweight_markdown` 更新为直接调用默认路径。

- [ ] **Step 7: 提交**

```bash
git add src/infrastructure/pipeline/entry_formatter.py tests/unit/infrastructure/test_message_formatter.py
git commit -m "feat(format): 所有正文默认输出规范 Markdown"
```

### Task 3: 移除 original 排版与 layout 发送分支

**Files:**
- Modify: `src/infrastructure/messaging/senders/base_sender.py`
- Modify: `src/infrastructure/messaging/senders/onebot_sender.py:151-160`
- Modify: `src/infrastructure/messaging/senders/qq_official_sender.py:49-79`
- Modify: `src/infrastructure/messaging/senders/weixin_oc_sender.py:25-37`
- Modify: `src/application/services/notification_dispatcher.py`
- Test: `tests/unit/infrastructure/test_platform_sequence_senders.py`、`tests/unit/infrastructure/test_base_sender_ffmpeg.py`

**Interfaces:**
- Consumes: `SendRequest.layout`（将不再被 sender 消费）。
- Produces: 移除 `_is_original_style`、`_layout_to_components` 分支；`SendRequest.layout` 保留字段但 sender 不再读取。

- [ ] **Step 1: 写失败测试——默认 sender 不消费 layout**

```python
@pytest.mark.asyncio
async def test_default_sender_ignores_layout_and_keeps_single_body(monkeypatch):
    from astrbot_plugin_rsshub.src.domain.entities.content_types import LayoutFragment
    from astrbot_plugin_rsshub.src.infrastructure.messaging.senders.types import SendRequest
    sender = DefaultMessageSender()
    layout = [
        LayoutFragment(kind="text", text="片段1"),
        LayoutFragment(kind="image", media_type="image", url="https://e.com/a.jpg"),
        LayoutFragment(kind="text", text="片段2"),
        LayoutFragment(kind="image", media_type="image", url="https://e.com/b.jpg"),
    ]
    request = SendRequest(session_id="s", message="正文", layout=layout)
    # 断言不会走 _send_components_in_order 分支
    sent = []
    monkeypatch.setattr(sender, "_send_chain", lambda sid, chain, use_markdown=None: sent.append(chain) or SimpleNamespace(ok=True))
    result = await sender.send_to_user(request, context=MessageContext(platform_name="", style=0))
    assert result.ok
    texts = [str(p.args[0]) for p in sent if hasattr(p, "args")]
    assert sum("片段" in t for t in texts) == 0  # 不再按 layout 重复正文
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/unit/infrastructure/test_platform_sequence_senders.py -v`
Expected: FAIL（默认 sender 当前会走 `_layout_to_components` 产生多个 text）。

- [ ] **Step 3: 移除 original 分支**

- `base_sender.py`：删除 `_is_original_style`；`send_to_user` 中始终走 `_build_components` + `build_chain` 路径，不消费 `request.layout`。
- `onebot_sender.py` / `qq_official_sender.py` / `weixin_oc_sender.py`：删除 `if self._is_original_style(context) and request.layout:` 分支及其内 `_send_components_in_order` 调用；保留非 original 路径（OneBot 合并转发、QQ Official 媒体优先、Weixin 逐条）。
- `notification_dispatcher.py`：删除 `effective_layout` 的构造与 `_limit_original_layout_text` 调用，`SendRequest.layout` 不再传入；删除 `layouts_to_cleanup` 相关清理（保留 `cleanup_ephemeral_generated_media_paths` 对 `raw_entry.layout` 的清理）。

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/unit/infrastructure/test_platform_sequence_senders.py tests/unit/infrastructure/test_onebot_sender.py tests/unit/infrastructure/test_qq_official_sender.py tests/unit/infrastructure/test_weixin_oc_sender.py tests/unit/infrastructure/test_base_sender_ffmpeg.py tests/unit/application/test_notification_dispatcher.py -v`
Expected: 全绿。受影响的 original 断言测试需按新契约迁移（`test_qq_official_original_style_pairs_image_with_following_text` 等改为验证统一顺序）。

- [ ] **Step 5: 提交**

```bash
git add src/infrastructure/messaging/senders/ src/application/services/notification_dispatcher.py tests/unit/infrastructure/ tests/unit/application/test_notification_dispatcher.py
git commit -m "refactor(sender): 移除 original 排版与 layout 发送分支"
```

### Task 4: 配置层移除 markdown_platforms 并恢复 ai_summary.ai_provider_id

**Files:**
- Modify: `_conf_schema.json`
- Modify: `src/infrastructure/config/models/sender_strategy_models.py`
- Modify: `src/infrastructure/config/models/runtime_settings.py`
- Modify: `src/infrastructure/config/settings_builder.py`
- Modify: `src/infrastructure/config/schema_healer.py`
- Modify: `src/shared/constants.py`
- Modify: `bootstrap.py`
- Test: `tests/unit/test_conf_schema.py`、`tests/unit/application/test_settings.py`

**Interfaces:**
- Consumes: `SenderStrategySettings`（运行时）、`SenderStrategiesConfig`（持久化）。
- Produces: `markdown_platforms` 字段与常量、`_build_markdown_platforms` 全部删除；新增 `ai_summary` schema 段（含 `ai_provider_id`，`_special: select_provider`）；`bootstrap._configure_message_senders` 不再调用 `EntryTextFormatter.configure_markdown_platforms`。

- [ ] **Step 1: 写失败测试——schema 不再包含 markdown_platforms 且包含 ai_summary**

在 `tests/unit/test_conf_schema.py` 新增：

```python
def test_conf_schema_removes_markdown_platforms():
    schema = _load_conf_schema()
    assert "markdown_platforms" not in schema["sender_strategies"]["items"]
    assert "ai_summary" in schema
    ai_provider = schema["ai_summary"]["items"]["ai_provider_id"]
    assert ai_provider["_special"] == "select_provider"

def test_sender_strategies_config_roundtrip_without_markdown_platforms():
    cfg = SenderStrategiesConfig.from_config({"enabled_platforms": ["telegram"]})
    serialized = cfg.to_config_dict()
    assert "markdown_platforms" not in serialized
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/unit/test_conf_schema.py tests/unit/application/test_settings.py -v`
Expected: FAIL（当前 schema 含 `markdown_platforms`，且无 `ai_summary`）。

- [ ] **Step 3: 实现配置变更**

- `_conf_schema.json`：删除 `sender_strategies.items.markdown_platforms`；新增顶层 `ai_summary` 对象（`ai_provider_id` 为 string + `_special: select_provider`，default `""`）。
- `sender_strategy_models.py`：删除 `markdown_platforms` 字段、`_normalize_markdown_platforms`、`_MARKDOWN_PLATFORM_KEYS`；`to_config_dict` 不再输出 `markdown_platforms`。
- `runtime_settings.py`：删除 `SenderStrategySettings.markdown_platforms`；新增 `AiSummarySettings` dataclass（`ai_provider_id: str = ""`），加入 `ApplicationSettings`。
- `settings_builder.py`：删除 `_build_markdown_platforms`；`_build_sender_strategy_settings` 不再传递；新增 `_build_ai_summary_settings` 并从配置读取。
- `schema_healer.py`：`heal_astrbot_plugin_config` 自动删除 schema 外的 `markdown_platforms`；新增 `ai_summary` 段。
- `constants.py`：删除 `SENDER_MARKDOWN_PLATFORM_DEFAULT`、`SENDER_MARKDOWN_PLATFORM_OPTIONS`。
- `bootstrap.py`：`_configure_message_senders` 删除 `EntryTextFormatter.configure_markdown_platforms` 调用及日志字段。

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/unit/test_conf_schema.py tests/unit/application/test_settings.py tests/unit/test_bootstrap_runtime.py -v`
Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add _conf_schema.json src/infrastructure/config/ src/shared/constants.py bootstrap.py tests/unit/test_conf_schema.py tests/unit/application/test_settings.py tests/unit/test_bootstrap_runtime.py
git commit -m "feat(config): 移除 markdown_platforms，新增 ai_summary Provider 配置"
```

### Task 5: 数据库迁移删除 style 列

**Files:**
- Create: `src/infrastructure/persistence/migrations/V4_drop_style_columns.py`
- Modify: `src/infrastructure/persistence/models.py`
- Modify: `src/domain/entities/subscription.py`
- Modify: `src/domain/entities/user.py`
- Modify: `src/infrastructure/persistence/migrations/V1_init.py`（建表 SQL 去 style）
- Test: `tests/unit/infrastructure/test_database_manager.py`、`tests/unit/application/test_settings.py`

**Interfaces:**
- Consumes: SQLAlchemy `AlterTable` / `column_exists` 辅助。
- Produces: `V4_drop_style_columns.upgrade(conn)` 删除 `rsshub_sub.style` 与 `rsshub_user.style`（列不存在则跳过）。

- [ ] **Step 1: 写失败测试——迁移幂等删除 style**

在 `tests/unit/infrastructure/test_database_manager.py` 新增：

```python
async def test_v4_migration_drops_style_columns_idempotently():
    conn = _build_memory_conn()
    # 构造包含 style 的旧表
    await conn.execute(text("CREATE TABLE rsshub_sub (id INTEGER PRIMARY KEY, style INTEGER)"))
    await conn.execute(text("CREATE TABLE rsshub_user (id TEXT PRIMARY KEY, style INTEGER)"))
    from astrbot_plugin_rsshub.src.infrastructure.persistence.migrations import V4_drop_style_columns
    await V4_drop_style_columns.upgrade(conn)
    cols = [row[1] for row in (await conn.execute(text("PRAGMA table_info(rsshub_sub)"))).all()]
    assert "style" not in cols
    # 幂等：再次执行不报错
    await V4_drop_style_columns.upgrade(conn)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/unit/infrastructure/test_database_manager.py -v`
Expected: FAIL（无 V4 迁移，import 失败）。

- [ ] **Step 3: 实现迁移**

`V4_drop_style_columns.py`：

```python
from sqlalchemy import text

async def upgrade(conn) -> None:
    for table in ("rsshub_sub", "rsshub_user"):
        cols = [row[1] for row in (await conn.execute(text(f"PRAGMA table_info({table})"))).all()]
        if "style" in cols:
            await conn.execute(text(f"ALTER TABLE {table} DROP COLUMN style"))
```

同步：`models.py` 删除 `SubORM.style` 与 `UserORM.style` 字段；`subscription.py` / `user.py` 删除 `style` 字段；`V1_init.py` 建表 SQL 不再包含 style。

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/unit/infrastructure/test_database_manager.py tests/unit/application/test_settings.py -v`
Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add src/infrastructure/persistence/ src/domain/entities/ tests/unit/infrastructure/test_database_manager.py tests/unit/application/test_settings.py
git commit -m "feat(db): V4 迁移删除 style 列"
```

### Task 6: 移除 style 与 markdown_platforms 的入口、导出、AI 工具

**Files:**
- Modify: `src/application/services/subscription_serializer.py`
- Modify: `src/application/llmtools/xml_push.py`
- Modify: `src/application/services/agent_xml_push_service.py`
- Modify: `src/infrastructure/config/models/plugin_config_models.py`
- Modify: `pages/dashboard/components/pages/settings.js`
- Modify: `pages/dashboard/components/overlays/user-panel.js`
- Modify: `pages/dashboard/components/overlays/main-panel.js`
- Test: `tests/unit/application/test_import_export.py`、`tests/unit/application/test_llmtools.py`、`tests/unit/application/test_agent_xml_push_service.py`

**Interfaces:**
- Consumes: `SubscriptionDefaults.style`、`GlobalConfig.style`、LLM tool `style` 参数。
- Produces: 删除 `style` 从导入导出字段、AI tool schema、Agent XML 推送安全参数、前端表单。

- [ ] **Step 1: 写失败测试——导入含 style 报告忽略、AI tool 拒绝 style**

```python
def test_import_toml_with_style_reports_ignored():
    content = "[[subscriptions]]\nlink='https://example.com/rss'\nstyle=2\n"
    payload = parse_subscriptions_toml(content)
    assert any("style" in msg and "已移除" in msg for msg in payload.warnings or [])

def test_xml_push_tool_rejects_style_param():
    from astrbot_plugin_rsshub.src.application.llmtools.xml_push import build_xml_push_tool
    tool = build_xml_push_tool(...)
    assert "style" not in tool.schema()["properties"]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/unit/application/test_import_export.py tests/unit/application/test_llmtools.py tests/unit/application/test_agent_xml_push_service.py -v`
Expected: FAIL。

- [ ] **Step 3: 实现移除**

- `subscription_serializer.py`：导出的字段列表去掉 `style`；解析时遇到 `style` 写入 warning「字段已移除并忽略」。
- `xml_push.py`：`style` 从 `rss_push_xml_entry` 参数 schema 移除；`agent_xml_push_service.py` 的 `_normalize_style` 删除，传入 `style` 时返回明确错误。
- `plugin_config_models.py`：`GlobalConfig` 删除 `style` 字段与映射。
- 前端 `settings.js` / `user-panel.js` / `main-panel.js`：删除排版策略下拉与提交字段。

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/unit/application/test_import_export.py tests/unit/application/test_llmtools.py tests/unit/application/test_agent_xml_push_service.py tests/unit/test_conf_schema.py -v`
Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add src/application/services/subscription_serializer.py src/application/llmtools/xml_push.py src/application/services/agent_xml_push_service.py src/infrastructure/config/models/plugin_config_models.py pages/dashboard/components/pages/settings.js pages/dashboard/components/overlays/user-panel.js pages/dashboard/components/overlays/main-panel.js tests/unit/application/ tests/unit/test_conf_schema.py
git commit -m "feat: 全面移除 style 排版配置与 markdown_platforms"
```

### Task 7: 全量回归与文档

**Files:**
- Modify: `docs/project/formatting.md`
- Modify: `docs/project/sender.md`
- Modify: `docs/project/architecture.md`
- Modify: `docs/project/domain-model.md`
- Modify: `docs/project/platforms.md`
- Modify: `docs/usage/configuration.md`
- Modify: `docs/usage/commands.md`
- Modify: `docs/usage/ai-tools.md`
- Modify: `docs/project/roadmap.md`

**Interfaces:**
- Consumes: 全部已完成任务。
- Produces: 文档同步删除 `style`、`original`、`markdown_platforms` 描述，补充统一 Markdown 链路说明。

- [ ] **Step 1: 运行全量单测**

Run: `./tests/run_tests.sh --category unit`
Expected: 全绿。

- [ ] **Step 2: 运行 ruff**

Run: `cd .. && uv run ruff check data/plugins/astrbot_plugin_rsshub && uv run ruff format --check data/plugins/astrbot_plugin_rsshub`
Expected: 无错误。

- [ ] **Step 3: 更新文档**

- `formatting.md`：删除 `style` 枚举、`original layout` 语义，改为「唯一 Markdown 正文 + 集中媒体」。
- `sender.md`：删除 `markdown_platforms` 描述；补充各平台 sender 的 Markdown 渲染/纯文本降级。
- `architecture.md`：更新链路描述，删除 `original` 相关句。
- `domain-model.md`：删除 `style` 行与 `markdown_platforms` 相关。
- `platforms.md`：删除 `original` 平台行为行。
- `configuration.md`：删除 `markdown_platforms` 配置说明；补充 `ai_summary`。
- `commands.md` / `ai-tools.md`：删除 `style` 参数说明。
- `roadmap.md`：更新完成项。

- [ ] **Step 4: 提交**

```bash
git add docs/
git commit -m "docs: 同步统一 Markdown 发送与移除 style/markdown_platforms"
```
