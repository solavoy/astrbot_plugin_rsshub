"""Markdown → 纯文本降级器。

把规范 Markdown 还原为可读纯文本，供不支持 Markdown 的平台
（OneBot / QQ 官方 / 微信 / 默认 sender）在发送边界使用。

转换规则：
- 去除 `**粗体**`、`*斜体*`、`` `行内代码` `` 标记
- `[文本](url)` → `文本 (url)`；链接文本即 URL 时只保留一份（避免 `url (url)` 重复）
- `# 标题` → `标题`
- `---` 水平线 → `——`
- 引用块 `>`、代码围栏 ``` 还原为普通文本
- 反转义 `\\*` `\\_` 等 MarkdownV2 特殊字符转义
"""

from __future__ import annotations

import re

# 转义反转义必须在行内强调之前处理：`\*x\*` 应还原为 `*x*`，
# 而不是被斜体规则误判后残留反斜杠。
_ESCAPE = re.compile(r"\\([\\`*_{}\[\]()#+.!|=<>~-])")
# 代码围栏整体还原为内部文本。
_FENCE = re.compile(r"(?ms)^[ \t]*```.*?```[ \t]*$")
_INLINE_CODE = re.compile(r"`([^`]+?)`")
# 链接 URL 支持一层 balanced 括号（如 Wikipedia 的 Foo_(bar)），
# 避免 `([^)\s]+?)` 在第一个 `)` 处截断 URL。
_INLINE_LINK = re.compile(r"\[([^\]]+?)\]\(((?:[^()]|\([^)]*\))+)\)")
_INLINE_STRONG = re.compile(r"\*\*(.+?)\*\*")
_INLINE_EM = re.compile(r"(?<!\*)\*([^*]+?)\*(?!\*)")
_ATX_HEADING = re.compile(r"(?m)^(#{1,6})\s+(.+?)\s*#*\s*$")
_HR = re.compile(r"(?m)^[ \t]*-{3,}[ \t]*$")
_QUOTE_LINE = re.compile(r"(?m)^[ \t]*>[ \t]?(.*)$")
_MULTI_BLANK = re.compile(r"\n{3,}")


def _fence_repl(match: re.Match[str]) -> str:
    """把围栏块还原为内部文本。"""
    block = match.group(0)
    block = re.sub(r"(?m)^[ \t]*```[ \t]*$", "", block)
    return block.strip("\n")


def _normalize_link_text(value: str) -> str:
    """去掉 Markdown 强调标记与尾部斜杠，用于判断「链接文本是否即 URL」的去重。"""
    return re.sub(r"[*_`~]", "", value or "").strip().strip("/")


def _link_repl(match: re.Match[str]) -> str:
    """``[文本](url)`` → ``文本 (url)``；链接文本即 URL 时只保留一份。

    归一化后比较（忽略加粗/斜体标记、尾部斜杠），避免
    ``[**url**](url)`` / ``[url/](url)`` 仍复现 ``url (url)`` 重复。
    """
    text_part = match.group(1)
    url_part = match.group(2)
    if _normalize_link_text(text_part) == _normalize_link_text(url_part):
        return text_part
    return f"{text_part} ({url_part})"


def markdown_to_plain(value: str | None) -> str:
    """把规范 Markdown 文本降级为可读纯文本。"""
    text = str(value or "")
    if not text:
        return ""

    text = _ESCAPE.sub(r"\1", text)
    text = _FENCE.sub(_fence_repl, text)
    text = _INLINE_CODE.sub(r"\1", text)
    text = _INLINE_LINK.sub(_link_repl, text)
    text = _INLINE_STRONG.sub(r"\1", text)
    text = _INLINE_EM.sub(r"\1", text)
    text = _ATX_HEADING.sub(r"\2", text)
    text = _HR.sub("——", text)
    text = _QUOTE_LINE.sub(r"\1", text)
    text = _MULTI_BLANK.sub("\n\n", text)
    return text.strip()
