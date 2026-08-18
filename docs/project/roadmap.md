# 路线图与现状

## 当前阶段

项目已经完成 v2.0.0 后的核心收口，并清除了知识库与内容处理器等不再需要的子系统。已完成的重点包括：

- 命令语义回归收口
- `link_preview` 全量移除
- 类型化配置模型与运行态设置统一到 `src/infrastructure/config/models/`，其中 `src/infrastructure/config/datamodels.py` 仅作为兼容导出
- 统一 Markdown 发送链路：内容一律规范 Markdown，全部渠道按 Markdown 原文推送（不做纯文本降级），由各适配器按其能力渲染；移除 `style` 与 `markdown_platforms` 配置
- RSSHub Routes 知识库功能移除（`/rsshub_kb_*` 命令、同步服务、Dashboard 页面、配置）
- 内容处理器功能移除（`ContentHandlerRuntime`、handler registry、`ai_filter`/`ai_transform`、LLM handler 工具、数据库 handlers 三列）
- 推送降噪与 List 聚合：数据库持久化批次（V5 迁移）、条数阈值 + 最长等待触发、两级关键词过滤、订阅/Feed/用户删除联动、AstrBot Provider 驱动的批次 AI 总结、Plugin Pages Lists 页面与域名分类
- Plugin Pages 管理面板大幅扩展
- 推送历史、数据管理、跨标签筛选联动补全

## 当前未完成但已定方向

### 文档

- `project/` 与 `dev/` 已完成首轮收口
- `usage/` 仍待继续拆分

## 建议的文档维护策略

后续继续推进时，建议按下面的顺序维护文档：

1. 先更新 `project/overview.md` 中的边界与定位
2. 再更新 `project/architecture.md` 中的实际链路
3. 最后更新 `README.md` 的外部说明

不要只改 README，不改项目文档。否则很快会再次出现入口文档和实现脱节。
