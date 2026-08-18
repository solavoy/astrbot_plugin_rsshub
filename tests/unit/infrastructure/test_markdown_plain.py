"""Markdown → 纯文本降级器测试。

降级器用于不支持 Markdown 的平台（OneBot / QQ 官方 / 微信 / 默认 sender），
在发送边界把规范 Markdown 还原为可读纯文本，避免把 `**粗体**`、`[链接](url)`
等原始语法直接暴露给用户。
"""

from __future__ import annotations

from astrbot_plugin_rsshub.src.infrastructure.pipeline.markdown_plain import (
    markdown_to_plain,
)


def test_strips_bold_and_italic_markers():
    text = "**粗体** 和 *斜体* 文本"
    assert markdown_to_plain(text) == "粗体 和 斜体 文本"


def test_converts_inline_link_to_text_and_url():
    text = "查看 [原文](https://example.com/post) 详情"
    assert markdown_to_plain(text) == "查看 原文 (https://example.com/post) 详情"


def test_plain_link_without_text_becomes_url():
    text = "链接：https://example.com/x"
    assert markdown_to_plain(text) == "链接：https://example.com/x"


def test_strips_atx_heading_markers():
    text = "# 一级标题\n## 二级标题\n### 三级标题"
    assert markdown_to_plain(text) == "一级标题\n二级标题\n三级标题"


def test_keeps_horizontal_rule_as_separator():
    text = "上文\n\n---\n\n下文"
    assert markdown_to_plain(text) == "上文\n\n——\n\n下文"


def test_converts_quote_and_code_blocks():
    text = "> 引用内容\n\n```\ncode block\n```"
    plain = markdown_to_plain(text)
    assert "引用内容" in plain
    assert "```" not in plain
    assert "code block" in plain


def test_unwraps_backtick_code_spans():
    text = "使用 `pip install` 安装"
    assert markdown_to_plain(text) == "使用 pip install 安装"


def test_unwraps_escaped_special_characters():
    # 反转义后强调标记仍按纯文本降级剥除；普通字符按字面保留。
    text = r"保留 \*星号\* 和 \_下划线\_ 以及 \# 井号"
    plain = markdown_to_plain(text)
    assert "*" not in plain and "_下划线_" in plain
    assert "井号" in plain


def test_returns_empty_string_for_empty_input():
    assert markdown_to_plain("") == ""
    assert markdown_to_plain(None) == ""


def test_keeps_plain_text_unchanged():
    text = "普通文本，没有 Markdown 语法。"
    assert markdown_to_plain(text) == text


def test_markdown_to_plain_keeps_paren_urls_intact():
    from astrbot_plugin_rsshub.src.infrastructure.pipeline.markdown_plain import (
        markdown_to_plain,
    )

    text = "via [t](https://en.wikipedia.org/wiki/Foo_(bar))"
    out = markdown_to_plain(text)
    assert "Foo_(bar))" in out  # 括号 URL 不被截断
    assert "https://en.wikipedia.org/wiki/Foo_(bar)" in out


def test_markdown_to_plain_plain_link_still_works():
    from astrbot_plugin_rsshub.src.infrastructure.pipeline.markdown_plain import (
        markdown_to_plain,
    )

    out = markdown_to_plain("[a](https://e.com)")
    assert out == "a (https://e.com)"


def test_markdown_to_plain_dedups_url_when_link_text_is_url():
    # 推送 footer 的 `via [url](url)` 降级后不应出现 `url (url)` 重复。
    # 链接文本与 URL 相等与否是动态比较，与具体地址无关（示例 URL 仅作 fixture）。
    text = "via [https://example.com/posts/42](https://example.com/posts/42)"
    assert markdown_to_plain(text) == "via https://example.com/posts/42"

    # 文本与 URL 不同时仍保留 `文本 (url)`，便于用户看到真实跳转地址。
    assert markdown_to_plain("[点击查看](https://example.com/a)") == (
        "点击查看 (https://example.com/a)"
    )


def test_markdown_to_plain_dedups_escaped_url_link_text():
    # MarkdownV2 转义（如 `.`）经反转义后文本仍等于 URL，同样去重。
    text = r"via [https://example\.com/posts/42](https://example\.com/posts/42)"
    assert markdown_to_plain(text) == "via https://example.com/posts/42"
