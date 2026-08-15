"""EntryDispatchPublisher 单测：单次解析链路的媒体占位符与正文正确性。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from astrbot_plugin_rsshub.src.application.services.entry_dispatch_publisher import (
    EntryDispatchPublisher,
)
from astrbot_plugin_rsshub.src.domain.entities.content_types import (
    build_generated_media_url,
)
from astrbot_plugin_rsshub.src.domain.entities.feed import Feed
from astrbot_plugin_rsshub.src.infrastructure.fetcher.rss.models import EntryParsed
from astrbot_plugin_rsshub.src.infrastructure.rendering import (
    TableImageRenderer,
    TableImageRenderResult,
)


def _mock_table_image(monkeypatch, tmp_path: Path, digest: str) -> str:
    """把表格渲染 mock 成已生成的图片，返回 source_id。"""
    source_id = build_generated_media_url("table", digest)
    table_png = tmp_path / "table_images" / f"table_{digest}.png"
    table_png.parent.mkdir(parents=True)
    table_png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 128)

    async def fake_font_ready():
        return tmp_path / "font.ttf"

    monkeypatch.setattr(
        "astrbot_plugin_rsshub.src.infrastructure.rendering."
        "table_image_renderer.get_plugin_cache_dir",
        lambda *parts: tmp_path.joinpath(*parts),
    )
    monkeypatch.setattr(
        "astrbot_plugin_rsshub.src.infrastructure.rendering.font_manager."
        "ensure_table_font_runtime",
        fake_font_ready,
    )
    monkeypatch.setattr(
        TableImageRenderer,
        "render_table",
        lambda self, table: TableImageRenderResult(
            source_id=source_id,
            path=table_png,
            digest=digest,
            reused=True,
        ),
    )
    return source_id


def _make_dispatcher() -> AsyncMock:
    dispatcher = AsyncMock()
    dispatcher.dispatch_to_feed_subscribers.return_value = {
        "success": 1,
        "failed": 0,
        "pending": 0,
        "skipped": 0,
    }
    return dispatcher


@pytest.mark.asyncio
async def test_publish_does_not_leak_table_image_placeholder(
    monkeypatch, tmp_path: Path
):
    """表格转图片后，正文中不应残留「[表格已转为图片]」占位符。"""
    _mock_table_image(monkeypatch, tmp_path, digest="a" * 64)

    dispatcher = _make_dispatcher()
    publisher = EntryDispatchPublisher(dispatcher=dispatcher)
    feed = Feed(id=1, link="https://example.com/rss.xml", title="Test Feed")
    entry = EntryParsed(
        title="Table entry",
        link="https://example.com/table",
        guid="table-1",
        content="<table><tr><td>A</td></tr></table>",
    )

    await publisher.publish(feed=feed, entry=entry, feed_url=feed.link)

    call_kwargs = dispatcher.dispatch_to_feed_subscribers.await_args.kwargs
    assert "[表格已转为图片]" not in call_kwargs["content"]
    assert "[表格已转为图片]" not in call_kwargs["raw_entry"].content
