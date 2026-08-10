# 配置说明

AstrBot 配置页只保留启动级基础设施配置、媒体配置和平台发送策略。订阅默认值请在 Plugin Pages 中维护。

插件启动时会按 `_conf_schema.json` 对实际配置做轻量自愈：补齐缺失字段、移除废弃字段、修正常见类型错误，并把下拉选项和滑块数值收敛到合法范围。只有检测到实际变化时才会写回配置文件。

## 基础配置 (`basic_config`)

| 配置项 | 说明 | 默认值 |
| --- | --- | --- |
| `rsshub_base_url` | 默认 RSSHub 域名，用于路由检索与订阅链接拼接。 | `https://rsshub.app` |
| `minimal_interval` | 最小监控间隔，保存订阅、用户默认值和会话默认值时都会强制检查。 | `1` |
| `hash_history_min` | 去重历史最小保留数量。 | `500` |
| `hash_history_multiplier` | 去重历史增长倍数。 | `2` |
| `hash_history_hard_limit` | 去重历史硬上限。 | `5000` |
| `tracking_query_params` | 链接去重时忽略的查询参数。 | 见 schema |
| `failed_queue_capacity` | 自动失败重试队列容量，`0` 表示禁用自动重试队列但仍保留失败历史。 | `50` |
| `failed_queue_max_retries` | 自动重试链路对单条失败历史的最大尝试次数。 | `3` |
| `deduplicate_multi_bot` | 同一会话多 BOT payload 等价时压重，并写入 `skipped` 审计记录。 | `true` |
| `bootstrap_skip_history` | 首轮是否只建立去重历史、不推送旧消息。 | `true` |
| `history_entry_limit` | 历史条目推送限制，`0` 表示不限制。 | `0` |

## HTTP 网络配置 (`http_config`)

| 配置项 | 说明 | 默认值 |
| --- | --- | --- |
| `proxy` | RSS 拉取、普通媒体预下载和 FFmpeg 下载使用的 HTTP/SOCKS 代理。裸 `host:port` 会按 `http://host:port` 处理。 | `""` |
| `timeout` | RSS 拉取和普通 HTTP 请求超时，单位秒。 | `30` |
| `media_timeout` | 媒体预下载、m3u8/HLS 合并与 FFmpeg 下载超时，单位秒。 | `300` |

## 媒体配置 (`media`)

| 配置项 | 说明 | 默认值 |
| --- | --- | --- |
| `telegraph_proxy` | Telegraph API 独立代理，留空直连且不继承 `http_config.proxy`。 | `""` |
| `image_relay_base_url` | 图片预下载反代地址，支持 `https://wsrv.nl/` 或 `https://wsrv.nl/?url=`。 | `""` |
| `media_relay_base_url` | 非图片媒体或未配置图片反代时使用的通用反代地址。 | `""` |
| `media_download_concurrency` | 同一条推送内远程媒体预下载并发数，`1` 表示串行。 | `1` |
| `cache_enabled` | 启用远程媒体、表格图片、GIF/压缩 GIF 和视频 MP4 转码结果缓存；关闭后使用本次临时文件并在发送后清理。 | `true` |
| `cache_ttl_seconds` | 媒体与转码缓存 TTL，单位秒；配置页面取值范围为 `60` 到 `604800`（7 天）。 | `900` |
| `table_to_image` | HTML 表格优先渲染为图片；关闭后使用文本表格 fallback。 | `true` |
| `video_transcode` | 视频发送前自动转码为兼容 MP4。 | `false` |
| `video_transcode_timeout` | 视频转码超时时间，单位秒。 | `120` |
| `gif_transcode` | 无声视频自动转 GIF。 | `false` |
| `gif_transcode_timeout` | GIF 转码超时时间，单位秒。 | `60` |

旧版 `ffmpeg` 配置会在启动自愈时迁移到 `media`，两者同时存在时以 `media` 已有字段为准。

## 发送策略 (`sender_strategies`)

`enabled_platforms` 是平台多选列表，默认启用 `telegram`、`aiocqhttp`、`qq_official`。未选中的平台回退到默认发送器。

`markdown_platforms` 是 Markdown 排版渠道勾选列表，默认仅 `telegram`，选项覆盖 `telegram`、`aiocqhttp`、`qq_official`、`weixin_oc`。勾选的渠道输出标题加粗、可点击 via 链接、`---` 分隔线的 Markdown；Telegram 会实际渲染，其余渠道显示 Markdown 语法（是否渲染取决于平台客户端能力）。未勾选的渠道推送纯文本。

平台策略写入 `platform_strategies` 模板列表。当前常用字段：

| 配置项 | 作用范围 | 说明 |
| --- | --- | --- |
| `enable_telegraph` | Telegram | 启用 Telegraph 自动分流。 |
| `telegraph_token` | Telegram | Telegraph access token；启用自动分流时必填。 |
| `telegraph_proxy` | Telegram | Telegraph createPage API 独立代理；留空直连且不继承 `http_config.proxy`，裸 `host:port` 按 `http://` 处理。 |
| `prefer_local_video` | OneBot | 覆盖默认视频来源策略；默认优先使用本地视频文件。 |
| `markdown_mode` | QQ Official | 预留 Markdown 三态配置；当前主动推送临时统一按纯文本发送。 |

Telegraph 不是显式 `send_mode`。它只在 Telegram 自动发送策略中触发：自动发送、Telegram 策略启用 Telegraph、token 有效，且去重后的媒体条目数大于 1。
