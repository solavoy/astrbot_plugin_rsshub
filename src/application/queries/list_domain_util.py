"""List 域名分类纯函数。

只按订阅 URL hostname 分类（小写、忽略端口），不解析条目原文链接。
"""

from __future__ import annotations

from urllib.parse import urlparse


def feed_hostname(feed_link: str | None) -> str:
    """返回 Feed URL 的小写 hostname；无效输入返回「未知域名」。"""
    raw = str(feed_link or "").strip()
    if not raw:
        return "未知域名"
    try:
        parsed = urlparse(raw)
    except ValueError:
        return "未知域名"
    hostname = (parsed.hostname or "").strip().lower()
    if not hostname:
        return "未知域名"
    return hostname
