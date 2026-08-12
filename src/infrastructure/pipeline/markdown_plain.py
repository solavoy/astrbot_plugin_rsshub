"""Markdown → 纯文本降级器。

把规范 Markdown 还原为可读纯文本，供不支持 Markdown 的平台
（OneBot / QQ 官方 / 微信 / 默认 sender）在发送边界使用。

转换规则：
- 去除 `**粗体**`、`*斜体*`、`` `行内代码` `` 标记
- `[文本](url)` → `文本 (url)`
- `# 标题` → `标题`
- `---` 水平线 → `——`
- 引用块 `>`、代码围栏 ``` 还原为普通文本
- 反转义 `\*` `\_` 等 MarkdownV2 特殊字符转义
"""

from __future__ import annotations

import re

# 转义反转义必须在行内强调之前处理：`\*x\*` 应还原为 `*x*`，
# 而不是被斜体规则误判后残留反斜杠。
_ESCAPE = re.compile(r"\\([\\`*_{}\[\]()#+.!|=<>~-])")
# 代码围栏整体还原为内部文本。
_FENCE = re.compile(r"(?ms)^[ \t]*```.*?```[ \t]*$")
_INLINE_CODE = re.compile(r"`([^`]+?)`")
_INLINE_LINK = re.compile(r"\[([^\]]+?)\]\(([^)\s]+?)\)")
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


def markdown_to_plain(value: str | None) -> str:
    """把规范 Markdown 文本降级为可读纯文本。"""
    text = str(value or "")
    if not text:
        return ""

    text = _ESCAPE.sub(r"\1", text)
    text = _FENCE.sub(_fence_repl, text)
    text = _INLINE_CODE.sub(r"\1", text)
    text = _INLINE_LINK.sub(lambda m: f"{m.group(1)} ({m.group(2)})", text)
    text = _INLINE_STRONG.sub(r"\1", text)
    text = _INLINE_EM.sub(r"\1", text)
    text = _ATX_HEADING.sub(r"\2", text)
    text = _HR.sub("——", text)
    text = _QUOTE_LINE.sub(r"\1", text)
    text = _MULTI_BLANK.sub("\n\n", text)
    return text.strip()
