# 发送、适配器与媒体指纹

## 负责什么

这一章覆盖三个紧密相关的部分：

- `NotificationServiceImpl`
- sender adapter / provider
- media fingerprint

## 为什么要单独写这一层

“发消息”看起来是一个动作，但其实分成三件事：

1. 生成平台无关的发送请求
2. 适配具体平台 sender
3. 处理媒体、失败和幂等

如果把这些揉成一团，OneBot、Telegram、QQ Official 的差异会很快把主链路拖乱。

## NotificationService

`NotificationServiceImpl` 是 scheduler/legacy 入口到应用 dispatcher 的桥接层。

### 正常流程

1. 接收 feed 更新
2. 遍历 entries
3. 组装正文、媒体、raw_xml
4. 调用 `NotificationDispatcher.dispatch_to_feed_subscribers()`

### 错误通知

如果 feed 抓取失败，会直接对相关订阅发送错误通知，而不是走普通条目链。

## Sender Provider / Adapter

### `InfrastructureMessageSenderProvider`

它根据平台名返回一个适配后的 sender：

- Telegram
- OneBot / aiocqhttp
- QQ Official
- Weixin OC

### 平台策略

provider 会同时解析 sender strategy：

- `telegram` -> Telegram 策略
- `aiocqhttp` / `onebot` -> OneBot 策略
- `qq_official` / `qqofficial` / `qq` -> QQ Official 策略

### Adapter 作用

`InfrastructureMessageSenderAdapter` 把应用层 `SendRequest` 转成基础设施层 sender 能懂的结构。

这样做是为了：

- 保持应用层不依赖具体平台实现
- 统一 sender 返回值
- 统一错误与重绑语义

### 统一发送模型

所有内容统一为规范 Markdown 正文 + 有序媒体集合；发送顺序固定为正文 → 图片 → 视频 → 音频 → 文件。`style` 排版策略与 `original` 布局发送已移除。

### QQ Official / Weixin OC 顺序发送

`qq_official` 与 `weixin_oc` 已并入统一发送骨架（`DefaultMessageSender.send_to_user`），与其他平台一样把全部正文与媒体合成「正文 → 媒体 → 尾」一条 chain 发送，不再有媒体优先、文本最后拆发的旧链路。平台差异改为在统一骨架上通过钩子表达：

- QQ Official 仍是唯一自带媒体数量阈值降级的平台：当媒体组件数超过 `qq_official_media_threshold` 时，`_maybe_degrade_before_send` 按策略走文件/链接降级，降级成功视为已送达（返回 `ok=True`）；`markdown_mode` 运行时开关保留在该 sender 的 `_resolve_use_markdown` 钩子。
- Weixin OC 无额外钩子，直接继承 `DefaultMessageSender` 全部行为。

统一骨架单链发送失败时默认仍返回 `SendResult.ok=False`，`transient` / `needs_rebind` 由失败结果聚合，`detail` 带有失败阶段语义。下载失败的媒体 URL 由统一组件过滤器折入正文：`MessageComponentSorter.append_failed_links` 只追加失败媒体的原始链接、不追加成功媒体链接。

QQ Official 是例外：当媒体在**发送时刻**被平台拒绝（整条 chain 发送 `ok=False`，而非阈值预判路径）时，该 sender 的 `_maybe_retry_after_failed_send` 后置发送降级钩子会把失败媒体逐项尝试 `_send_component_fallback_candidates`（文件候选 → 原文链接文本），并重新送出正文（含失败链接）；任一降级送达成功即返回 `ok=True`。"降级送达视为成功"避免轮询把已送达内容当失败反复补推——该语义等价于已删除的 `_counts_degraded_media_delivery_as_success`，现在经该后置钩子在 QQ 官方实现，仅作用于发送时刻失败，与阈值预判路径（`_maybe_degrade_before_send`）相互独立。

### Markdown 文本发送

RSS 文本格式化层统一输出规范 Markdown：标题加粗、可点击 via 链接、`---` 归属分隔线，转义按 MarkdownV2 全集合处理。

所有渠道统一按 Markdown 原文推送（`should_render_markdown` 恒为真，不再在发送边界把 Markdown 降级为纯文本）。各平台/适配器按其能力渲染：Telegram 走 MarkdownV2，Lark(飞书) 由适配器 post 富文本的 `md` 元素渲染，其余平台取决于各自适配器对 Markdown 的支持。`sender_strategies.markdown_platforms` 配置已移除。

QQ Official 的运行时开关在 `sender_strategies.platform_strategies` 的 `qq_official_strategy.markdown_mode`：

- `auto`：预留平台默认策略。
- `force`：预留强制 Markdown 策略。
- `plain`：纯文本策略。

QQ Official sender 必须通过 AstrBot `MessageChain.use_markdown` 控制 Markdown，不能绕过 core 手写 botpy payload。当前主动推送链路统一按 `should_render_markdown`（恒真）推送 Markdown 原文；QQ 的 `_use_markdown_for_context` 仍是兼容守卫（暂返回 False），若实测 QQ 渲染异常可据此单独调整。

Telegram 的 Markdown 走 MarkdownV2；插件只优化 Plain 文本文案，AstrBot Telegram adapter 会对 Plain 文本走 MarkdownV2 转换；媒体 caption Markdown 不是当前插件承诺面。

### OneBot 合并转发

OneBot 使用合并转发，节点名优先使用 feed title。合并转发失败后会回退为纯文本 Nodes。节点顺序遵循统一模型：文本节点在前，媒体节点依次在后。

### Telegram 大图片

Telegram Bot API 对 photo 有大小上限。发送前如果本地图片文件超过内置 photo 阈值，Telegram sender 会把它改为文件组件发送，避免平台把大图按 photo 拒绝。这个降级只改变发送组件类型，不改变原始媒体 URL 和失败历史记录。

### m3u8 / HLS 视频

媒体发送始终先预下载到本地成功缓存；下载失败不会写入失败缓存，下一次推送会重新尝试。m3u8/HLS 链接会交给 FFmpeg 合并为 MP4，并沿用标准化后的 `http_config.proxy` 作为 FFmpeg HTTP 代理参数；裸 `host:port` 会按 `http://host:port` 处理。`http_config.media_timeout` 控制媒体预下载和 FFmpeg 下载超时，上限 1800 秒。下载流程不只检查文件非空，还会用本地文件头/`filetype` 探测真实媒体类型与缓存后缀，再用 `media_integrity` 验证图片头/可选 Pillow 完整性，并用 ffprobe 校验视频流与时长；校验失败会删除坏缓存，并沿用媒体下载失败路径，让 sender 追加原始链接或按平台能力降级，而不是缓存坏文件。

OneBot 默认优先发送本地视频文件，避免 NapCat/OneBot 端自行拉取远程 m3u8 失败。QQ Official 由 `MediaSendPlanner` 按保守软阈值预先分流：可上传的图片/视频先按平台媒体组件发送，再按文件或链接降级；预计会被 QQ 官方网关拒绝的超限媒体不再撞上传 API，而是直接在正文中暴露原始链接。QQ Official 降级链路成功时视为已送达。平台限制和默认策略的常量归属见 [`domain-model.md`](./domain-model.md#常量归属)。

## 媒体 fingerprint

### `HttpMediaFingerprintService`

这个服务会下载媒体 URL 的小样本，然后算 `sha256`。

### 算法步骤

1. 限制 URL 数量
2. 只接受 http/https
3. 发起短超时请求
4. 逐块读取响应
5. 超过 `max_bytes` 就放弃
6. 对内容做 `sha256`

### 返回值形式

返回值统一加前缀：

- `media:<sha256>`

### 为什么不用直接拼 URL

因为很多媒体链接：

- 可能是临时签名 URL
- 可能会重定向
- 可能同内容不同地址

下载少量字节算内容 hash，更适合做“媒体是否相同”的判断。

## 失败与回退

- 非 http/https -> 直接忽略
- 响应非 200 -> 跳过
- 超过大小上限 -> 跳过
- 下载异常 -> debug 级别记录并跳过

也就是说，media fingerprint 是增强能力，不是发送门槛。

## 设计理由

这一层的原则是：

- sender 适配不能侵入业务规则
- sender adapter 可以处理平台专属发送次数与顺序
- fingerprint 不能阻断推送
- 失败要能回退到最小可发内容
