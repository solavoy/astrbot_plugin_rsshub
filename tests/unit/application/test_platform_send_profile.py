"""平台发送画像测试：统一内联媒体为 markdown 链接，并验证配置驱动的接缝。"""

from __future__ import annotations

from astrbot_plugin_rsshub.src.application.services.platform_send_profile import (
    build_inline_media_markdown,
    profile_for_platform,
)


def test_build_inline_media_markdown_renders_image_and_links():
    out = build_inline_media_markdown(
        [
            ("image", "https://example.com/a.jpg"),
            ("video", "https://example.com/v.mp4"),
            ("file", "https://example.com/r.pdf"),
        ]
    )
    assert "![图片](https://example.com/a.jpg)" in out
    assert "[video](https://example.com/v.mp4)" in out
    assert "[file](https://example.com/r.pdf)" in out


def test_build_inline_media_markdown_skips_blank_urls():
    assert build_inline_media_markdown([("image", ""), ("file", "  ")]) == ""
    assert build_inline_media_markdown([]) == ""


def test_profile_defaults_to_inline_for_all_platforms():
    # 当前统一内联；后续按平台配置差异化——这里保证接缝可用。
    for platform in ("telegram", "lark", "onebot", "qq_official"):
        assert profile_for_platform(platform).inline_media_as_markdown is True
    assert profile_for_platform().inline_media_as_markdown is True
