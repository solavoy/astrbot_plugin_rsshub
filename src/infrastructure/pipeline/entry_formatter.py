"""RSS entry text cleaning and formatting."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum

from ...application.services.html_parser import HTMLParser
from ...shared.constants import (
    PLATFORM_ALIASES,
    SENDER_MARKDOWN_PLATFORM_DEFAULT,
)
from ..rendering import cleanup_ephemeral_generated_media_paths
from ..utils import get_logger

logger = get_logger()


class EntryOutputFormat(str, Enum):
    """Output text format for platform-specific rendering."""

    PLAIN = "plain"
    MARKDOWN = "markdown"


# 平台别名 → 规范名，用于把订阅的 platform_name 归一化后匹配配置的勾选渠道。
_PLATFORM_ALIAS_TO_CANONICAL: dict[str, str] = {
    alias: canonical
    for canonical, aliases in PLATFORM_ALIASES.items()
    for alias in aliases
}


@dataclass(frozen=True)
class EffectivePushOptions:
    """Resolved push options for one subscription/user target."""

    notify: bool = True
    length_limit: int = 0
    display_author: int = 0
    display_via: int = 0
    display_title: int = 0
    display_entry_tags: bool = False
    style: int = 0
    display_media: bool = True


@dataclass(frozen=True)
class EntryFormatInput:
    """Normalized RSS entry data used by the text formatter."""

    title: str = ""
    content: str = ""
    summary: str = ""
    link: str = ""
    author: str = ""
    feed_title: str = ""
    feed_link: str = ""
    tags: tuple[str, ...] = field(default_factory=tuple)


class EntryTextFormatter:
    """Format cleaned entry text according to effective push options."""

    # 表格转图总开关（media.table_to_image）；关闭后表格统一回退纯文本。
    _table_to_image_enabled: bool = True

    # 使用 Markdown 排版的渠道（规范平台名），由 sender_strategies
    # 的 markdown_platforms 勾选配置驱动；默认仅 Telegram。
    _markdown_platforms: frozenset[str] = frozenset(SENDER_MARKDOWN_PLATFORM_DEFAULT)

    @classmethod
    def configure_table_to_image(cls, enabled: bool) -> None:
        """配置表格转图总开关（启动装配时调用）。"""
        cls._table_to_image_enabled = bool(enabled)

    @classmethod
    def configure_markdown_platforms(cls, platforms: list[str] | tuple[str, ...]) -> None:
        """配置使用 Markdown 排版的消息渠道（启动装配时调用）。

        传入勾选的规范平台名列表；空列表表示任何渠道都不使用 Markdown。
        """
        cls._markdown_platforms = frozenset(
            str(name).strip().lower() for name in platforms or []
        )

    async def format_entry(
        self,
        entry: EntryFormatInput,
        options: EffectivePushOptions | None = None,
        output_format: EntryOutputFormat | str = EntryOutputFormat.PLAIN,
    ) -> str:
        options = options or EffectivePushOptions()
        try:
            output_format = EntryOutputFormat(output_format)
        except (TypeError, ValueError):
            logger.warning(
                "Invalid entry output format %r, fallback to plain",
                output_format,
            )
            output_format = EntryOutputFormat.PLAIN
        body = await self.clean_text(
            entry.content or entry.summary or "",
            render_tables_as_images=(
                options.display_media and self._table_to_image_enabled
            ),
        )
        title = await self.clean_text(entry.title)
        author = await self.clean_text(entry.author)
        feed_title = await self.clean_text(entry.feed_title)
        feed_link = str(entry.feed_link or "").strip()
        link = str(entry.link or "").strip()

        if options.display_title != -1:
            body = self._remove_repeated_title(body, title)
        if options.length_limit > 0 and body:
            body = self._truncate(body, options.length_limit)

        lines: list[str] = []
        if options.display_title != -1 and title:
            lines.append(title)
        if body:
            lines.append(body)
        tags = ""
        if options.display_entry_tags and entry.tags:
            tags = " ".join(
                f"#{tag.strip().lstrip('#')}" for tag in entry.tags if tag.strip()
            )
            if tags:
                lines.append(tags)

        if output_format is EntryOutputFormat.MARKDOWN:
            return self._format_markdown(
                title=title,
                body=body,
                tags=tags,
                link=link,
                feed_title=feed_title,
                feed_link=feed_link,
                author=author,
                options=options,
            )

        content = "\n\n".join(part for part in lines if part)
        via_suffix = self._build_via_suffix(
            link=link,
            feed_title=feed_title,
            feed_link=feed_link,
            author=author,
            options=options,
        )
        if via_suffix:
            return f"{content}\n\n{via_suffix}" if content else via_suffix
        return content

    @classmethod
    def resolve_output_format(cls, platform: str | None) -> EntryOutputFormat:
        """按平台解析最终输出格式（由 markdown_platforms 勾选配置驱动）。

        命中勾选渠道（含别名，如 tg→telegram、onebot→aiocqhttp）输出
        Markdown 排版，其余平台保持纯文本，避免 ``**标题**``、``[链接](url)``
        等 Markdown 原文直接暴露给用户。
        """
        normalized = str(platform or "").strip().lower()
        canonical = _PLATFORM_ALIAS_TO_CANONICAL.get(normalized, normalized)
        if canonical in cls._markdown_platforms:
            return EntryOutputFormat.MARKDOWN
        return EntryOutputFormat.PLAIN

    @staticmethod
    async def clean_text(value: str, *, render_tables_as_images: bool = True) -> str:
        parsed = await HTMLParser(
            value or "",
            render_tables_as_images=render_tables_as_images,
        ).parse()
        try:
            text = parsed.html_tree.get_plain()
            text = remove_media_placeholders(text)
            return normalize_plain_text(text)
        finally:
            cleanup_ephemeral_generated_media_paths(parsed.layout)

    @staticmethod
    def _remove_repeated_title(body: str, title: str) -> str:
        if not body or not title:
            return body
        stripped = body.strip()
        normalized_title = title.strip()
        if stripped == normalized_title:
            return ""
        if normalize_plain_text(stripped).replace("\n", " ") == normalize_plain_text(
            normalized_title
        ).replace("\n", " "):
            return ""
        if stripped.startswith(normalized_title + "\n"):
            return stripped[len(normalized_title) :].strip()
        return body

    @staticmethod
    def _truncate(text: str, limit: int) -> str:
        if limit <= 0 or len(text) <= limit:
            return text
        if limit <= 3:
            return text[:limit]
        return text[: limit - 3].rstrip() + "..."

    @staticmethod
    def _build_via_suffix(
        *,
        link: str,
        feed_title: str,
        feed_link: str,
        author: str,
        options: EffectivePushOptions,
    ) -> str:
        if options.display_via == -2:
            return ""

        source = feed_title or feed_link
        if options.display_via == -1:
            source = ""

        parts: list[str] = []
        if link and source:
            parts.append(f"via {link} | {source}")
        elif link:
            parts.append(f"via {link}")
        elif source:
            parts.append(source)

        if options.display_author != -1 and author:
            if parts:
                parts[-1] += f" (author: {author})"
            else:
                parts.append(f"author: {author}")

        return " ".join(parts)

    @classmethod
    def _format_markdown(
        cls,
        *,
        title: str,
        body: str,
        tags: str,
        link: str,
        feed_title: str,
        feed_link: str,
        author: str,
        options: EffectivePushOptions,
    ) -> str:
        lines: list[str] = []
        if options.display_title != -1 and title:
            lines.append(f"**{cls._escape_markdown_text(title)}**")
        if body:
            lines.append(cls._escape_markdown_text(body))
        if tags:
            lines.append(cls._escape_markdown_text(tags))

        content = "\n\n".join(part for part in lines if part)
        via_suffix = cls._build_markdown_via_suffix(
            link=link,
            feed_title=feed_title,
            feed_link=feed_link,
            author=author,
            options=options,
        )
        if via_suffix:
            return f"{content}\n\n---\n\n{via_suffix}" if content else via_suffix
        return content

    @classmethod
    def _build_markdown_via_suffix(
        cls,
        *,
        link: str,
        feed_title: str,
        feed_link: str,
        author: str,
        options: EffectivePushOptions,
    ) -> str:
        if options.display_via == -2:
            return ""

        source = feed_title or feed_link
        if options.display_via == -1:
            source = ""

        parts: list[str] = []
        link_text = cls._escape_markdown_text(link)
        source_text = cls._escape_markdown_text(source)
        if link and source:
            parts.append(
                f"via [{link_text}]({cls._escape_markdown_url(link)}) | {source_text}"
            )
        elif link:
            parts.append(f"via [{link_text}]({cls._escape_markdown_url(link)})")
        elif source:
            parts.append(source_text)

        if options.display_author != -1 and author:
            author_text = cls._escape_markdown_text(author)
            if parts:
                parts[-1] += f" (author: {author_text})"
            else:
                parts.append(f"author: {author_text}")

        return " ".join(parts)

    # MarkdownV2 全部特殊字符（超集覆盖 classic Markdown）。Telegram adapter
    # 按 MarkdownV2 渲染 Plain 文本（docs/project/sender.md），未转义这些字符
    # 会导致解析 400（如 via 链接文本里的 ``.`` ``-``）。classic Markdown 下
    # 对任意字符 ``\x`` 也按字面输出，因此两套 parse mode 都安全。
    # ``-`` 放在末尾避免在字符类里被当作范围运算符。
    _MARKDOWNV2_SPECIAL: str = r"\\`*_{}\[\]()#+.!|=<>~-"

    @staticmethod
    def _escape_markdown_text(value: str) -> str:
        return re.sub(
            r"([" + EntryTextFormatter._MARKDOWNV2_SPECIAL + r"])",
            r"\\\1",
            value or "",
        )

    @staticmethod
    def _escape_markdown_url(value: str) -> str:
        url = (value or "").replace("\\", "\\\\")
        # MarkdownV2 中链接 URL 需要转义 ``)`` 与 ``.`` ``_`` 等特殊字符。
        return re.sub(
            r"([" + EntryTextFormatter._MARKDOWNV2_SPECIAL + r"])",
            r"\\\1",
            url,
        )


def normalize_plain_text(value: str) -> str:
    """Normalize whitespace without flattening meaningful line breaks."""
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t\f\v]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def remove_media_placeholders(value: str) -> str:
    text = re.sub(r"(?m)^\s*\[(视频|音频|表格已转为图片)\]\s*$\n?", "", value or "")
    text = re.sub(r"[ \t]*(\[视频\]|\[音频\]|\[表格已转为图片\])[ \t]*", " ", text)
    return text
