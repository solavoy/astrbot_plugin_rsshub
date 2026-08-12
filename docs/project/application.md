# 应用层入口与行为边界

本文记录应用层入口、聊天命令、AI tools、订阅配置与推送历史的稳定语义。它面向需要修改 `src/application/`、`src/interfaces/` 或入口编排的维护者。

> [!IMPORTANT]
> 应用层只描述入口语义和用例边界。领域值细节看 [`domain-model.md`](./domain-model.md)，平台发送差异看 [`platforms.md`](./platforms.md)。

## 聊天命令边界

以下命令需要保持完整参数签名，兼容 `GreedyStr` 风格参数。

| 命令 | 当前行为 | 不要回退 |
| --- | --- | --- |
| `/sub` | 支持多个 URL 批量订阅。 | 不要退回单 URL 语义。 |
| `/unsub` | 支持 ID 和 URL 混合批量取消。 | 不要只支持单 ID。 |
| `/sub_list` | 只展示当前会话订阅，支持分页。 | 不恢复 `all` 范围。 |
| `/sub_export [all]` | 保留管理员校验。 | 不绕过 admin guard。 |
| `/sub_import` | 支持 TOML 路径和上传等待流程。 | 不要移除上传等待监听。 |
| `/sub_test <ID\|URL>` | 真实推送最新条目，不是预览；聊天命令不接受额外范围参数。 | 不要恢复“测试推送未进入正式链路”的泛化误判。 |
| `/sub_status` | 展示当前会话运行中或排队中的推送任务。 | 不把全局队列无筛选暴露给普通用户。 |
| `/sub_stop [job_id\|feed_id\|all]` | 支持精确停止和批量停止；无参数时停止当前运行任务。 | 不让停止语义绕过审计。 |
| `/rsshelp` | 发送预生成帮助图；按 AstrBot `timezone` 选择日间/夜间主题，读不到或时区非法时回退系统本地时间。 | 不把帮助图生成放到运行时热路径。 |

命令解析细节见 [`commands.md`](./commands.md)。

## AI tools 边界

| Tool / 能力 | 输入边界 | 输出 / 副作用 | 备注 |
| --- | --- | --- | --- |
| `rss_subscribe` | 只暴露 `targets: string[]` | 批量订阅目标 | `targets` 中每项可以是完整 Feed URL、RSSHub path 或 route path。 |
| `rss_push_xml_entry` | 只暴露安全格式化参数，如 `send_mode`、显示选项、`length_limit` | 立即推送 XML/HTML 条目并写入 `push_history` | 不读取订阅配置。 |
| XML payload 校验 | 拒绝 malformed、超大、DOCTYPE 输入 | 失败时不进入发送链路 | 保护 XML 解析。 |
| agent push 去重 | `(source_type, source_key, user_id, target_session, entry_guid)` | 只看成功态 | 不依赖公开 `sub_id`。 |
| agent retry | 复用历史记录中的 target 和 media 上下文 | 直接重发 | 保留审计连续性。 |

`src/application/llmtools/` 按订阅、配置、历史和 XML 直推拆分工具实现；公开入口仍是 `build_llm_tools` 与 `LLM_TOOL_NAMES`。这次拆分只改变代码组织和工具说明，不改变公开参数 schema。

## 订阅、用户与历史语义

| 主题 | 当前语义 | 备注 |
| --- | --- | --- |
| 配置继承 | 订阅继承用户，用户继承全局默认；继承值只认 `-100` | 不恢复 `use_sub_config` / `use_user_config`。 |
| 旧翻译字段 | `translate`、`translate_target_lang` 保持移除 | 翻译不再是应用层内置入口。 |
| `minimal_interval` | 写入阶段硬下限 | 不要降级成运行时临时 clamp。 |
| 用户事实表 | 写入订阅或推送历史前必须确保非空 `user_id` 有用户记录 | 启动自愈会从订阅和历史补齐缺失用户。 |
| 删除用户 | 默认删除用户和该用户全部订阅 | 推送历史默认保留，显式 `delete_push_history=true` 才删除。 |

## 推送历史与重试

| 行为 | 当前语义 | 备注 |
| --- | --- | --- |
| `PushHistory.fail_reason` | 必须保持在模型和数据库限制内，当前上限为 512 字符 | 仓储读取历史脏数据时要能截断过长失败原因。 |
| `failed_queue_capacity=0` | 只关闭自动失败队列捞取 | 不影响失败历史写入和保留。 |
| `failed_queue_max_retries` | 只控制自动重试次数上限 | 不代表可以删除失败历史。 |
| Plugin Pages 手动重试 | 复用同一条 `push_history`，更新结果和最近活动时间 | 不新增历史行，不消耗自动重试次数。 |
| `deduplicate_multi_bot` | 只在同一 `target_session` 且最终 payload 等价时去重 | 被压制的发送必须写入 `status=skipped`。 |
| 规则性跳过 | handler deny、通知关闭、成功去重 guard、多 BOT 去重都写入 `status=skipped` | 这类 skipped 是可审计 ack；不能伪装成 success。 |
| Feed 水位确认 | 只有 `success` 或明确规则性 `skipped` 会确认本轮新 entry | `pending`、`failed` 或分发异常不能推进 `entry_hashes` / 条件请求水位，避免漏推。 |

## List 聚合语义

| 行为 | 当前语义 | 备注 |
| --- | --- | --- |
| 归属 | List 绑定单一 `user_id`、`target_session`、`platform_name`；一个订阅最多属于一个 List | 订阅移出 List 后，已入队内容仍归原批次，后续新条目恢复即时推送。 |
| 批次触发 | 达到 `batch_size` 立即生成；最早条目等待达到 `max_wait_minutes` 生成；成功后开始下一批 | 一次 25 条阈值 10 生成 10/10/5。 |
| 可靠入队 | pending push_history + 队列项同事务写入；入队失败不推进 Feed 水位 | 水位推进：规则性 `skipped` 和 `durably_queued` 可推进；`pending`/`failed`/异常不推进。 |
| 队列项幂等 | 唯一约束 `(list_id, sub_id, entry_key)`；`entry_key` 优先 GUID，缺失用轮询稳定指纹 | 重复入队返回失败，不产生第二条。 |
| 两级过滤 | 订阅层关注词/屏蔽词 + List 层关注词/屏蔽词；屏蔽词并集命中即拒，关注词层内 OR、层间 AND | 被过滤条目写 `status=skipped` 并推进水位。 |
| 停用语义 | List 停用后不新入队，新条目按规则性 `skipped` 推进水位；已有队列保留 | Dispatcher 对停用 List 写 `skipped`，不入队也不即时发送。 |
| 分片持久化 | 渲染结果（批次分片）持久化；重试只发未成功分片 | 拆分一次生成，重试不重切。 |
| 删除联动 | 删除订阅/Feed/用户时清理未发送队列项，把相关 `pending` 历史标为 `skipped` | 已发送审计保留。 |

## List AI 总结边界

| 行为 | 当前语义 | 备注 |
| --- | --- | --- |
| Provider 选择 | `ai_summary.ai_provider_id` 配置优先；为空回退 List `target_session` 当前 Provider | 走 `Context.llm_generate(chat_provider_id=..., prompt=...)` 读 `response.completion_text`。 |
| 输入边界 | 只总结通过过滤并进入当前批次的条目；系统模板明确 Feed 内容为不可信数据 | 禁止执行条目中的指令。 |
| 结果规范 | 规范化 Markdown，移除 `[CQ:`、`sendMessage`、`tool_use` 等注入标记 | 禁止注入消息组件、会话目标或工具调用。 |
| 失败降级 | Provider 不可用或异常时正文照常发送，`summary_status=failed`，`fail_reason` 受长度限制 | 首次结果持久化，重试不重复调用模型。 |

## 已移除的应用能力

| 能力 | 当前状态 | 替代路径 |
| --- | --- | --- |
| route-search / route-build LLM tools | 不恢复 | 路由检索走 AstrBot KB；订阅走 `rss_subscribe(targets=[...])`。 |
| 旧翻译管道入口 | 不恢复 | 后续内容加工归 handler / AI transform / 扩展运行时。 |
| 旧 AI enrich / summarize 配置入口 | 不恢复 | 统一收敛到 handler chain。 |
| Plugin Pages 新建订阅、TOML 导入、TOML 导出 | 不恢复 | 用户归属流程保留在聊天命令或 AI tools。 |
