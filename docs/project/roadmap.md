# 路线图与现状

## 当前阶段

项目已经完成 v2.0.0 后的核心收口，并清除了知识库与内容处理器等不再需要的子系统。已完成的重点包括：

- 命令语义回归收口
- `link_preview` 全量移除
- 类型化配置模型与运行态设置统一到 `src/infrastructure/config/models/`，其中 `src/infrastructure/config/datamodels.py` 仅作为兼容导出
- Markdown 排版推送与 `markdown_platforms` 渠道勾选配置
- RSSHub Routes 知识库功能移除（`/rsshub_kb_*` 命令、同步服务、Dashboard 页面、配置）
- 内容处理器功能移除（`ContentHandlerRuntime`、handler registry、`ai_filter`/`ai_transform`、LLM handler 工具、数据库 handlers 三列）
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
