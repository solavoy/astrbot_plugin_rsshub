"""HTML 解析器媒体抽取测试：非正文装饰图片（logo/头像/图标/二维码）不应进媒体列表。"""

from __future__ import annotations

import pytest

from astrbot_plugin_rsshub.src.application.services.html_parser import HTMLParser


async def _media_urls(html: str) -> list[str]:
    parser = HTMLParser(html, feed_link="https://example.com/post")
    result = await parser.parse()
    return [item.url for item in result.media]


@pytest.mark.asyncio
async def test_keeps_real_article_image():
    urls = await _media_urls(
        '<p>正文</p><img src="https://x.com/img/real-photo.jpg">'
    )
    assert urls == ["https://x.com/img/real-photo.jpg"]


@pytest.mark.asyncio
async def test_filters_logo_by_filename():
    urls = await _media_urls(
        '<p>正文</p><img src="https://x.com/static/logo.png">'
        '<img src="https://x.com/img/real-photo.jpg">'
    )
    assert "https://x.com/static/logo.png" not in urls
    assert "https://x.com/img/real-photo.jpg" in urls


@pytest.mark.asyncio
async def test_filters_avatar_and_icon_urls():
    urls = await _media_urls(
        '<p>正文</p>'
        '<img src="https://x.com/avatar/123.png">'
        '<img src="https://x.com/assets/icon-share.png">'
        '<img src="https://x.com/real.jpg">'
    )
    assert "https://x.com/avatar/123.png" not in urls
    assert "https://x.com/assets/icon-share.png" not in urls
    assert "https://x.com/real.jpg" in urls


@pytest.mark.asyncio
async def test_filters_small_icon_by_dimension():
    urls = await _media_urls(
        '<p>正文</p>'
        '<img width="32" height="32" src="https://x.com/i.png">'
        '<img src="https://x.com/real.png">'
    )
    assert "https://x.com/i.png" not in urls
    assert "https://x.com/real.png" in urls


@pytest.mark.asyncio
async def test_keeps_large_image():
    urls = await _media_urls(
        '<p>正文</p><img width="600" height="400" src="https://x.com/photo.jpg">'
    )
    assert "https://x.com/photo.jpg" in urls


@pytest.mark.asyncio
async def test_filters_image_by_element_class():
    urls = await _media_urls(
        '<p>正文</p>'
        '<img class="logo" src="https://x.com/a.png">'
        '<img src="https://x.com/b.png">'
    )
    assert "https://x.com/a.png" not in urls
    assert "https://x.com/b.png" in urls


@pytest.mark.asyncio
async def test_filters_image_inside_logo_ancestor():
    urls = await _media_urls(
        '<div class="site-header-logo">'
        '<img src="https://x.com/header.png">'
        "</div>"
        '<p>正文</p><img src="https://x.com/c.png">'
    )
    assert "https://x.com/header.png" not in urls
    assert "https://x.com/c.png" in urls


@pytest.mark.asyncio
async def test_video_not_filtered():
    urls = await _media_urls(
        '<p>正文</p><video><source src="https://x.com/v.mp4"></video>'
    )
    assert "https://x.com/v.mp4" in urls


@pytest.mark.asyncio
async def test_srcset_chooses_large_photo_not_logo():
    urls = await _media_urls(
        '<p>正文</p>'
        '<img srcset="https://x.com/logo-40.png 40w, '
        'https://x.com/photo-800.jpg 800w" src="https://x.com/photo-800.jpg">'
    )
    assert "https://x.com/photo-800.jpg" in urls
    assert "https://x.com/logo-40.png" not in urls
