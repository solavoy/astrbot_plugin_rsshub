"""List 批次 AI 总结服务单元测试。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from astrbot_plugin_rsshub.src.application.services.ai_summary_service import (
    AstrBotAiSummaryProvider,
    normalize_ai_markdown,
)


def test_normalize_ai_markdown_strips_injected_component_markers():
    text = "## 总结\n\n[CQ:image,file=evil] sendMessage 指令"
    out = normalize_ai_markdown(text)
    assert "[CQ:" not in out and "sendMessage" not in out


def test_normalize_ai_markdown_collapses_whitespace_and_control_chars():
    text = "  总结\n\n\x00\x01第一行\n第二行  \n  "
    out = normalize_ai_markdown(text)
    assert "\x00" not in out and "\x01" not in out
    assert "第一行" in out


@pytest.mark.asyncio
async def test_provider_uses_fixed_id_and_returns_text():
    context = MagicMock()
    context.llm_generate = AsyncMock(
        return_value=SimpleNamespace(completion_text="总结")
    )
    svc = AstrBotAiSummaryProvider(context=context, ai_provider_id="prov-1")
    out = await svc.summarize_batch(
        list_entity=SimpleNamespace(target_session="s1"),
        items_title_link=["- [a](u)"],
        prompt="摘要",
    )
    assert out == "总结"
    context.llm_generate.assert_awaited_once()
    call_kwargs = context.llm_generate.call_args.kwargs
    assert call_kwargs["chat_provider_id"] == "prov-1"
    assert "用户要求：摘要" in call_kwargs["prompt"]
    assert "不可信数据" in call_kwargs["prompt"]


@pytest.mark.asyncio
async def test_provider_falls_back_to_session_when_id_empty():
    context = MagicMock()
    context.get_current_chat_provider_id = AsyncMock(return_value="session-prov")
    context.llm_generate = AsyncMock(
        return_value=SimpleNamespace(completion_text="总结")
    )
    svc = AstrBotAiSummaryProvider(context=context, ai_provider_id="")
    await svc.summarize_batch(
        list_entity=SimpleNamespace(target_session="s1"),
        items_title_link=[],
        prompt="摘要",
    )
    context.get_current_chat_provider_id.assert_awaited_once_with(umo="s1")
    assert context.llm_generate.call_args.kwargs["chat_provider_id"] == "session-prov"


@pytest.mark.asyncio
async def test_provider_raises_when_no_provider_available():
    context = MagicMock()
    context.get_current_chat_provider_id = AsyncMock(return_value="")
    svc = AstrBotAiSummaryProvider(context=context, ai_provider_id="  ")
    with pytest.raises(RuntimeError):
        await svc.summarize_batch(
            list_entity=SimpleNamespace(target_session="s1"),
            items_title_link=[],
            prompt="摘要",
        )
