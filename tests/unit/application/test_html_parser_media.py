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
async def test_filters_avatar_url_segment_but_keeps_icon_share_filename():
    # 「avatar」命中路径段 → 过滤；「icon-share」只是普通文件名不再误删（精确匹配优先）。
    urls = await _media_urls(
        '<p>正文</p>'
        '<img src="https://x.com/avatar/123.png">'
        '<img src="https://x.com/assets/icon-share.png">'
        '<img src="https://x.com/real.jpg">'
    )
    assert "https://x.com/avatar/123.png" not in urls
    assert "https://x.com/assets/icon-share.png" in urls
    assert "https://x.com/real.jpg" in urls


@pytest.mark.asyncio
async def test_filters_icon_size_by_dimension_but_keeps_32px():
    # 仅 <=24px 视为图标级；32px（如小头像/缩略图）不再误删。
    urls = await _media_urls(
        '<p>正文</p>'
        '<img width="16" height="16" src="https://x.com/i16.png">'
        '<img width="32" height="32" src="https://x.com/i32.png">'
    )
    assert "https://x.com/i16.png" not in urls
    assert "https://x.com/i32.png" in urls


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


@pytest.mark.asyncio
async def test_keeps_content_images_with_decorative_looking_words():
    # 精度回归：路径段"share"、内容类"article-icon"、文件名"icon-of-..."都不再误删。
    urls = await _media_urls(
        '<p>正文</p>'
        '<img src="https://img.cdn/share/cover-800.jpg">'
        '<img class="article-icon" src="https://x.com/a.png">'
        '<img src="https://x.com/news/icon-of-solar-cells.png">'
    )
    assert "https://img.cdn/share/cover-800.jpg" in urls
    assert "https://x.com/a.png" in urls
    assert "https://x.com/news/icon-of-solar-cells.png" in urls


@pytest.mark.asyncio
async def test_keeps_image_inside_share_buttons_container():
    # 祖先类只认强装饰标记（logo/avatar 等）；share-buttons 容器不再导致误删。
    urls = await _media_urls(
        '<div class="share-buttons">'
        '<img src="https://x.com/hero.jpg">'
        "</div>"
    )
    assert "https://x.com/hero.jpg" in urls
