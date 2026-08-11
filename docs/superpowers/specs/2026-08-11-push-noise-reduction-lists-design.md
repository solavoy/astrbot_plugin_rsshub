# 推送降噪、List 聚合与统一 Markdown 发送设计

## 1. 背景与目标

高频 Feed（例如 `https://rsshub.app/v2ex/topics/latest`）会在短时间内产生大量逐条推送。现有系统能识别增量、避免重复推送并在首次订阅时跳过历史条目，但缺少内容筛选和跨 Feed 聚合能力。结果是有用与无用内容混杂，用户短暂离开后可能积累几十条消息。

本设计引入四项相互配合的能力：

1. 订阅和 List 两级关键词过滤，先以低成本规则降噪。
2. List 将多个订阅聚合到持久化批次，按“条数阈值 + 最长等待”发送。
3. 可选 AI 总结，放在每个 List 批次末尾。
4. 重构全平台发送链路，以规范 Markdown 作为唯一正文格式并集中发送媒体，修复飞书多图时正文重复的问题。

同时移除已经没有独立实现价值的 `style` 排版配置，以及需要用户手动选择渠道的 `markdown_platforms` 配置。

## 2. 非目标

首版不包含：

- 正则表达式过滤或复杂布尔规则语言。
- 基于 AI 的逐条过滤；AI 只用于批次总结。
- Redis、Kafka 或其他外部消息队列。
- List 聊天命令或 List LLM tools；List 仅通过 Plugin Pages 管理。
- 按条目原文链接推断分类；Feed 分类只看订阅 URL 的 hostname。
- 恢复已移除的内容处理器、AI transform/filter 或人格配置。

## 3. 已确认的产品语义

### 3.1 List 归属

- 一个订阅最多属于一个 List。
- 未加入 List 的订阅在过滤通过后保持即时推送。
- 加入 List 的订阅停止独立即时推送，改由 List 批量发送。
- 从 List 移除后，后续新条目恢复即时推送。
- 一个 List 绑定单一 `user_id`、`target_session` 和 `platform_name`。
- 只允许加入同一用户、同一目标会话、同一平台的订阅。
- 同一个 Feed URL 被不同用户或会话订阅时，仍是不同订阅，可分别加入各自的 List。

### 3.2 批次触发

每个 List 配置 `batch_size` 与 `max_wait_minutes`：

1. 第一条待推送内容入队后开始计时。
2. 待发条目达到 `batch_size` 时立即生成并发送批次。
3. 未达到阈值但最早条目等待达到 `max_wait_minutes` 时，发送当前已有内容。
4. 批次成功后开始下一批。
5. 一次出现 25 条且阈值为 10 时，形成 10、10 两个完整批次，剩余 5 条进入下一批并从该批最早条目重新计时。

### 3.3 内容模式

List 提供：

- `title_link`：标题 + 原文链接，整批合并为 Markdown，不发送媒体组件。
- `full` + `split`：逐篇发送完整 Markdown 正文和该篇媒体；全部条目完成后发送 AI 总结。
- `full` + `aggregate`：全文合并成 Markdown，条目间用 `---` 分隔；媒体仅保留为 Markdown 链接，不下载或发送媒体组件。

AI 总结始终位于批次最后。

### 3.4 Feed 域名分类

- 分类严格使用订阅 URL 的 hostname，例如 `rsshub.app`、`rss.gurify.com`。
- hostname 统一转小写并忽略端口。
- 不解析 RSSHub 路由，不追踪条目原文链接。
- 无法解析的 URL 归入“未知域名”。
- 分类是 Plugin Pages 的只读派生视图，不新增分类持久化表。

## 4. 总体架构

```text
FeedPollingService
  -> SubscriptionFilterService
       -> 普通订阅: NotificationDispatcher
       -> List 订阅: ListQueueService（持久化入队）

ListBatchCoordinator
  -> batch_size 达标时立即 claim
  -> oldest queued item 达到 max_wait 时 claim
  -> 启动恢复未完成批次
  -> ListBatchRenderer
  -> SessionPushQueue
  -> UnifiedMessageDispatcher

UnifiedMessageDispatcher
  -> CanonicalMessage(markdown_body, media[])
  -> 平台 Sender 渲染 / 降级 / 上传 / 拆分
```

### 4.1 组件职责

#### `SubscriptionFilterService`

输入条目的标题、清洗后的完整正文、订阅规则和可选 List 规则，返回明确的允许/拒绝结果与审计原因。它不操作数据库或 sender。

#### `ListQueueService`

验证 List 归属，在同一事务中创建 `pending` 推送历史与持久化队列项，保证轮询水位可以在可靠接管后推进。

#### `ListBatchCoordinator`

负责原子 claim、阈值触发、超时触发、恢复和重试。它不负责 Markdown 细节或平台发送差异。

#### `ListBatchRenderer`

根据 List 内容模式产生稳定的批次分片与可选 AI 总结。渲染结果持久化，使重试不依赖重新抓取 Feed 或重新调用 AI。

#### `UnifiedMessageDispatcher`

只接受规范消息对象：一个 Markdown 正文和一个有序、去重的媒体集合。它保证正文只出现一次，再委托 sender 处理平台能力。

#### 平台 sender

只负责：

- 渲染规范 Markdown，或降级为可读纯文本；
- 按平台长度限制安全拆分文本；
- 上传媒体并执行平台候选降级；
- 在媒体最终失败时补充原始链接；
- 不复制、重新生成或按媒体数量重组正文。

## 5. 数据模型

### 5.1 `rsshub_lists`

字段：

- `id`
- `name`
- `user_id`
- `target_session`
- `platform_name`
- `state`
- `batch_size`
- `max_wait_minutes`
- `content_mode`: `title_link | full`
- `full_delivery_mode`: `split | aggregate`
- `ai_summary_enabled`
- `ai_summary_prompt`
- `include_keywords`
- `exclude_keywords`
- `created_at`
- `updated_at`

约束：

- `(user_id, target_session, name)` 唯一。
- `batch_size > 0`。
- `max_wait_minutes > 0`。
- `full_delivery_mode` 仅在 `content_mode=full` 时生效。

用户和目标会话创建后不可直接修改。需要更换目标时，新建 List 并原子移动兼容订阅，避免待发内容归属变化。

### 5.2 `rsshub_sub` 新字段

- `list_id`: 可空外键，一个订阅最多属于一个 List。
- `include_keywords`: JSON 字符串数组。
- `exclude_keywords`: JSON 字符串数组。

加入或移动 List 时，服务端验证：

```text
subscription.user_id == list.user_id
subscription.target_session == list.target_session
subscription.platform_name == list.platform_name
```

### 5.3 `rsshub_list_queue_items`

字段：

- `id`
- `list_id`
- `sub_id`
- `feed_id`
- `push_history_id`
- `entry_guid`
- `entry_key`: 非空稳定幂等键；优先使用 `entry_guid`，缺失时使用轮询层稳定 entry 指纹
- `entry_title`
- `entry_link`
- `feed_title`
- `feed_link`
- `markdown_content`
- `media_items`
- `queued_at`
- `batch_id`: 可空
- `state`: `queued | claimed | sent | failed | skipped`

唯一约束：

```text
(list_id, sub_id, entry_key)
```

`entry_key` 必须非空，优先使用上游 GUID；GUID 缺失时复用 `FeedPollingService` 已生成的稳定身份指纹。该约束防止轮询重入导致同一条目重复入队。

### 5.4 `rsshub_list_batches`

字段：

- `id`
- `list_id`
- `state`: `preparing | ready | sending | success | failed`
- `item_count`
- `summary_markdown`
- `summary_status`: `disabled | pending | success | failed`
- `fail_reason`
- `created_at`
- `started_at`
- `completed_at`

### 5.5 `rsshub_list_batch_parts`

字段：

- `id`
- `batch_id`
- `sequence`
- `kind`: `entry | aggregate | summary`
- `markdown_content`
- `media_items`
- `state`: `pending | sending | success | failed`
- `fail_reason`
- `sent_at`

唯一约束：

```text
(batch_id, sequence)
```

批次分片持久化后，重试只发送未成功分片，不重复发送已经成功的正文、条目或总结。

### 5.6 `rsshub_list_batch_part_items`

聚合分片可能覆盖多个队列项，因此使用映射表保存分片与原条目的确认关系：

- `batch_part_id`
- `queue_item_id`

唯一约束：

```text
(batch_part_id, queue_item_id)
```

只有覆盖某个队列项的全部必需分片成功后，才把该队列项及其 `push_history` 更新为 `success`。标题链接和全文聚合模式因此不会因“一片对应多条目”而丢失逐条审计。

## 6. 过滤规则

### 6.1 匹配材料

匹配文本为：

```text
标题 + "\n" + 清洗后的完整正文
```

首版采用 Unicode 大小写不敏感的字面子串匹配。关键词写入时去首尾空白、移除空项，并按大小写不敏感方式去重。不支持正则表达式，避免表达式错误和 ReDoS 风险。

### 6.2 判断顺序

1. 命中订阅或 List 任一屏蔽词：拒绝。
2. 订阅配置了关注词但未命中任何一个：拒绝。
3. List 配置了关注词但未命中任何一个：拒绝。
4. 其他情况允许。

因此：

- 屏蔽词取两层并集，优先级最高。
- 各层关注词采用层内 OR、层间 AND。
- 订阅规则对普通即时推送和 List 推送都生效。

### 6.3 审计与水位

被过滤条目创建 `push_history(status=skipped)`，原因示例：

```text
filtered: subscription exclude keyword="二手"
filtered: list include keywords not matched
```

审计原因不存储完整匹配正文。规则性跳过允许推进 Feed 水位，避免下轮重复判断和积压。

## 7. 持久化入队与 Feed 水位

List 条目只有在数据库可靠接管后才确认轮询：

```text
新条目
  -> 过滤通过
  -> 在事务中写 pending push_history + queue item
  -> 返回 durably_queued
  -> FeedPollingService 推进 entry_hashes
```

语义：

- 入队后 `push_history` 保持 `pending`，不能伪装成成功。
- 批次相关分片全部发送成功后，队列项和对应历史更新为 `success`。
- 入队事务失败时不推进 Feed 水位，下轮仍可重新处理。
- 批次失败依赖持久化恢复，不依赖重新抓取 Feed。

## 8. 批次并发、调度与恢复

- 每个 List 使用进程内异步锁，减少同进程重复竞争。
- 数据库 claim 使用原子状态更新；正确性不依赖异步锁。
- 每次入队后检查 `batch_size`，达到阈值即触发 coordinator。
- scheduler 每分钟检查最早 `queued_at` 是否达到 `max_wait_minutes`，并检查失败批次。
- 启动时把遗留 `preparing/sending` 批次归一化为可恢复状态。
- 同一 `target_session` 的批次通过现有 `SessionPushQueue` 串行发送。
- List 停用后不接受新条目进入聚合队列；其订阅在停用期间按 `notify disabled` 记为规则性 `skipped` 并推进水位，避免停用后一次性补推全部旧内容。已有队列保留，Plugin Pages 提供恢复、立即推送、清空为 `skipped` 三种操作。
- 订阅移出 List 后，已入队内容继续属于原 List；只有后续新条目恢复即时推送。

## 9. 批次渲染

### 9.1 标题 + 原文链接

按 Feed 分组、组内按入队时间排序：

```markdown
# 技术动态

## V2EX

- [帖子标题 A](https://...)
- [帖子标题 B](https://...)

## GitHub

- [项目标题 C](https://...)

---

## AI 总结

……
```

此模式不下载或发送媒体组件。

### 9.2 全文 + 分批发送

发送顺序：

```text
条目 1 Markdown 正文
条目 1 所有媒体
条目 2 Markdown 正文
条目 2 所有媒体
...
AI 总结
```

每篇条目是独立持久化分片，复用统一单条发送链路。媒体失败不能导致正文重发。

### 9.3 全文 + 聚合发送

```markdown
# List 名称

## 条目 1 标题

正文……

原文：[查看原文](https://...)

---

## 条目 2 标题

正文……

原文：[查看原文](https://...)

---

## AI 总结

……
```

此模式不下载或发送媒体组件；原媒体仅保留为 Markdown 链接。

### 9.4 文本拆分

- 先按条目边界拆分。
- 单个条目仍超限时，按段落边界拆分。
- 单个段落仍超限时，使用 Markdown 感知拆分器，不能切断链接、代码围栏或转义序列。
- 分片内容和顺序在第一次生成时持久化，重试不得重新切分。
- 平台长度阈值属于 sender 能力，不写进领域实体。

## 10. AI 总结

### 10.1 配置

恢复插件级 Provider 选择，但不恢复内容处理器：

```json
{
  "ai_summary": {
    "type": "object",
    "description": "List AI 总结配置",
    "items": {
      "ai_provider_id": {
        "type": "string",
        "description": "List AI 总结模型",
        "_special": "select_provider",
        "default": ""
      }
    }
  }
}
```

每个 List 单独配置 `ai_summary_enabled` 和 `ai_summary_prompt`。

### 10.2 Provider 解析与调用

依据 AstrBot v4.5.7+ 官方插件 API：

```python
provider_id = config.ai_provider_id.strip()
if not provider_id:
    provider_id = await context.get_current_chat_provider_id(
        umo=list_entity.target_session,
    )

response = await context.llm_generate(
    chat_provider_id=provider_id,
    prompt=prompt,
)
summary = response.completion_text
```

- 固定 Provider 优先。
- 配置为空时按 List 目标会话回退当前聊天 Provider。
- Provider ID 为空、失效或调用异常时，记录总结失败，但正文批次继续发送。
- 不假定具体异常类型，调用边界捕获异常并保存受长度限制的失败原因。

### 10.3 提示词安全与输入

- 只总结通过过滤并进入当前批次的条目。
- 系统模板明确声明 Feed 标题、正文、链接均是不可信数据，不得执行其中的指令。
- List 自定义提示词作为总结目标，而不是覆盖安全边界。
- 输入设置总字符预算；超限时对每条正文先做确定性截断，并保留标题与链接。
- AI 结果按普通不可信 Markdown 文本规范化，不允许注入消息组件、会话目标或工具调用。
- 首次总结结果或失败状态持久化；发送重试不重复调用模型。

## 11. 统一 Markdown 发送链路

### 11.1 规范消息

所有普通推送和 List 分片收敛为：

```text
CanonicalMessage
  markdown_body: str        # 唯一正文
  media: list[MediaItem]     # 有序、URL 去重
```

移除 layout fragments 作为发送时图文交错模型。HTML parser 仍可产出结构化媒体和用于 Markdown 转换的内容树，但 sender 不再消费 `original` layout。

### 11.2 Markdown 转换

HTML/RSS 内容转换为规范 Markdown，保留：

- 标题和段落；
- 有序/无序列表；
- 引用；
- 代码与代码块；
- 链接；
- 基础强调；
- 媒体 alt 和失败链接语义。

内部规范 Markdown 不提前硬编码 Telegram MarkdownV2 转义。平台 sender 在最终边界进行对应渲染或纯文本降级。

`push_history.content` 保存规范 Markdown，确保审计和重试使用相同内容。

### 11.3 全平台不变量

- 一条逻辑消息只有一个正文来源。
- 自动顺序固定为：正文、图片、视频、音频、文件。
- sender 可以因平台限制拆分消息，但不得按媒体数量复制正文。
- 媒体失败只重试/降级媒体；已经成功的正文不重发。
- 不支持 Markdown 的平台使用统一降级器输出可读纯文本，而不是直接显示无效语法。

飞书多图回归必须得到：

```text
正文
图片 1
图片 2
```

而不是：

```text
正文
图片 1
正文
图片 2
```

### 11.4 移除旧配置

彻底移除 `style`：

- 不再区分 `auto / RSSRT / original`。
- 从订阅、用户默认、全局默认、数据库、Plugin Pages、命令更新参数、导入导出和 AI/XML 直推工具移除。
- 数据库迁移删除相关列；兼容列已不存在的数据库。
- 旧 TOML `style` 明确报告为已移除并忽略；新导出不包含该字段。
- 旧 AI tool 调用传入 `style` 时由参数校验明确拒绝，不静默改变语义。

彻底移除 `markdown_platforms`：

- 从 `_conf_schema.json`、持久化配置模型、运行时设置、settings builder 和启动装配移除。
- 配置自愈删除旧值。
- 所有内容默认进入规范 Markdown 链路，由 sender 自动适配平台能力。

QQ Official 的 `markdown_mode` 属平台发送能力控制，不等同于内容格式选择；保留用于 sender 最终渲染/降级决策。

## 12. Plugin Pages

新增独立 Lists 页面。

### 12.1 域名分类侧栏

- 按订阅 URL hostname 自动分组。
- 展示域名及可选订阅数。
- 用于筛选和折叠，不持久化分类。

### 12.2 List 列表

展示：

- 名称、用户、目标会话、平台；
- 订阅数、排队条数、最早等待时长；
- 内容模式、AI 总结状态；
- 最近批次结果。

支持启用、停用、编辑和删除。删除默认“仅解散 List，订阅恢复即时推送”；可显式选择同时删除其中订阅。

### 12.3 编辑面板

可编辑：

- `batch_size`
- `max_wait_minutes`
- 内容模式和全文发送方式
- AI 总结开关与提示词
- List 关注词和屏蔽词
- 所属订阅

订阅选择器按域名分组，只显示同用户、同目标会话、同平台且未加入其他 List 的订阅。允许在两个兼容 List 间原子移动订阅。

### 12.4 订阅面板

新增：

- 所属 List
- 关注词
- 屏蔽词
- 只读 `feed_hostname`

未加入 List 时提示“过滤通过后即时推送”。

## 13. Web API

新增：

```text
GET  /lists
POST /lists/create
POST /lists/update
POST /lists/delete
POST /lists/move-subscriptions
GET  /lists/eligible-subscriptions
GET  /lists/batches
POST /lists/batches/retry
POST /lists/flush
POST /lists/clear-queue
```

现有订阅 API 增加：

- `list_id`
- `include_keywords`
- `exclude_keywords`
- `feed_hostname`（只读派生）

所有写接口在服务端重新校验用户、目标会话、平台和当前归属，不信任前端筛选。参数错误返回明确 4xx；跨归属操作不能部分成功。

## 14. 失败处理与一致性

- 规则过滤：`skipped`，推进 Feed 水位。
- List 入队失败：不推进水位。
- AI 总结失败：正文继续发送，`summary_status=failed`。
- 分片部分成功：重试只发未成功分片。
- 媒体部分失败：正文不重发；按平台候选链降级，最终保留原始链接。
- List 停用：后续新条目按规则性 `skipped` 处理并推进水位，不进入队列；已有队列保留。
- 订阅移出 List：旧队列项仍归原批次，后续条目即时推送。
- 删除订阅或 Feed：清理未发送队列项并把相关 history 标为 `skipped`；成功审计历史保留。
- 删除 List 仅解散时：未成批队列项默认保留，要求用户在删除确认中选择“立即推送”或“清空为 skipped”，不能静默丢弃。
- 插件重启：恢复未完成批次与最长等待语义。

失败原因遵守现有 `PushHistory.fail_reason` 长度边界，不存储模型响应全文、密钥或不必要的 Feed 正文。

## 15. 数据库迁移与配置兼容

新迁移负责：

1. 创建 List、队列、批次和批次分片表。
2. 为订阅增加 `list_id`、`include_keywords`、`exclude_keywords`。
3. 删除订阅和用户中的 `style` 列；迁移可重复执行并兼容列已经不存在。
4. 保持现有 push history 成功/失败/skipped 语义。

配置自愈负责：

- 新增 `ai_summary.ai_provider_id`。
- 删除 `sender_strategies.markdown_platforms`。
- 删除全局默认中的 `style`。
- 不恢复 `content_handlers` 或 `ai_persona_id`。

## 16. 测试矩阵

### 16.1 过滤

- 订阅/List 关注词与屏蔽词组合。
- 屏蔽优先、层内 OR、层间 AND。
- 中文、英文大小写、Unicode、空项和重复词。
- 普通即时订阅同样应用订阅规则。
- 被过滤条目只处理一次并推进水位。

### 16.2 批次与恢复

- 达到条数立即创建批次。
- 最长等待到期创建批次。
- 25 条按 10/10/5 处理。
- 多 Feed 并发入队只 claim 一次。
- 入队事务失败不推进 Feed 水位。
- 启动恢复 `preparing/sending`。
- 部分分片成功后重试不重复成功分片。

### 16.3 内容渲染

- 标题链接、全文分批、全文聚合。
- 按 Feed 分组和稳定排序。
- AI 总结始终最后。
- 聚合模式不触发媒体下载。
- 长 Markdown 按条目、段落和语法安全拆分。
- AI 输入预算、提示注入边界和失败回退。

### 16.4 全平台发送

- 0、1、2 和多图片均只有一个正文来源。
- 飞书自动发送表现为正文一次、图片连续。
- Telegram、OneBot、QQ Official、微信及默认 sender 的 Markdown 渲染/纯文本降级。
- 媒体失败不会重发已成功正文。
- Markdown 链接、代码围栏、特殊字符不被拆坏。

### 16.5 迁移、配置与 API

- 新数据库和旧数据库升级。
- `style` 列存在/不存在两种迁移路径。
- 旧 `markdown_platforms` 配置自愈清理。
- Provider 固定选择与目标会话回退。
- 跨用户、跨会话、跨平台加入 List 被拒绝。
- List 删除、订阅移动、队列清空和立即 flush。
- Feed hostname 派生分类。

## 17. 验收标准

1. 高频订阅可通过关键词规则减少无关消息。
2. List 能跨多个 Feed 持久化聚合，并按条数阈值或最长等待可靠发送。
3. 插件重启、发送失败和部分成功都不丢失待发内容，也不重复已成功分片。
4. 三种 List 内容模式符合既定媒体语义，AI 总结始终最后且失败不阻塞正文。
5. 所有普通推送和 List 推送以规范 Markdown 为唯一正文格式。
6. 所有平台在多媒体发送中正文只出现一次；飞书多图重复正文回归被自动测试覆盖。
7. `style` 与 `markdown_platforms` 从配置、模型、页面和公开参数中完整移除。
8. Feed 分类只按订阅 URL hostname，结果稳定且不依赖条目原文链接。
