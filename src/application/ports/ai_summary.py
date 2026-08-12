"""AI 总结端口。

定义 List 批次 AI 总结提供方的协议。具体实现（AstrBot Provider）在
ai_summary_service 中，可被测试替换。
"""

from __future__ import annotations

from typing import Any, Protocol


class AiSummaryProvider(Protocol):
    """List 批次 AI 总结提供方。"""

    async def summarize_batch(
        self,
        *,
        list_entity: Any,
        items_title_link: list[str],
        prompt: str,
    ) -> str:
        """返回规范化后的 Markdown 总结文本；异常向上抛，由调用方降级。"""
        ...
