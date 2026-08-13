"""条目分发发布器。

收敛「HTML 单次解析 → 纯文本 → 媒体提取 → format_entry → dispatch」的公共链路，
供 Feed 轮询、测试推送共用。核心收益：每个条目只解析一次 HTML，消除三重解析。
"""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

from ...domain.entities.content_types import AudioContent, EntryContentContext, VideoContent
from ...infrastructure.pipeline import media_items_from_parsed, remove_media_placeholders
from ...infrastructure.utils import get_logger
from .html_parser import HTMLParser

logger = get_logger()

_DEFAULT_TRACKING_QUERY_PARAMS = frozenset(
    {
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_term",
        "utm_content",
        "utm_id",
        "gclid",
        "fbclid",
        "mc_cid",
        "mc_eid",
        "spm",
        "ref",
        "ref_src",
    }
)


class EntryDispatchPublisher:
    """把单个 RSS 条目解析、格式化并分发给订阅。"""

    def __init__(
        self,
        *,
        dispatcher: Any,
        media_fingerprint_service: Any = None,
        tracking_query_params: Any = None,
    ) -> None:
        self._dispatcher = dispatcher
        self._media_fingerprint_service = media_fingerprint_service
        self._tracking_query_params = (
            tracking_query_params or _DEFAULT_TRACKING_QUERY_PARAMS
        )

    async def publish(
        self,
        *,
        feed: Any,
        entry: Any,
        feed_url: str,
        subscription_ids: list[int] | None = None,
        include_inactive: bool = False,
        bypass_dedup: bool = False,
        event: Any = None,
        include_error_detail: bool = False,
    ) -> dict[str, Any]:
        """解析并分发一个条目，返回 dispatcher 统计（success/failed/pending/skipped/durably_queued）。"""
        title = str(getattr(entry, "title", "") or "")
        link = self._resolve_entry_link(entry, feed_url)
        guid = self._entry_identity(entry)
        author = str(getattr(entry, "author", "") or "").strip()
        raw_content = str(
            getattr(entry, "content", "")
            or getattr(entry, "summary", "")
            or title
        )
        feed_link = str(getattr(feed, "link", "") or feed_url or "").strip()

        # 单次 HTML 解析：同时获得 html_tree（纯文本）与 media 列表。
        parsed = await HTMLParser(raw_content, feed_link=feed_link).parse()
        plain_content = parsed.html_tree.get_plain().strip()
        if any(isinstance(m, (AudioContent, VideoContent)) for m in parsed.media):
            plain_content = remove_media_placeholders(plain_content)
        media_items = media_items_from_parsed(parsed.media)
        media_urls = [url for _t, url in media_items]
        for enclosure in getattr(entry, "enclosures", None) or []:
            enclosure_url = str(getattr(enclosure, "url", "") or "").strip()
            if enclosure_url:
                media_urls.append(enclosure_url)
        media_urls = list(dict.fromkeys(media_urls))
        tags = tuple(getattr(entry, "tags", []) or ())

        content = await self._format_content(
            title=title,
            body=plain_content,
            link=link,
            feed_title=str(getattr(feed, "title", "") or ""),
            feed_link=feed_link,
            author=author,
            tags=tags,
        )

        if self._media_fingerprint_service is not None and media_urls:
            try:
                media_hashes = await self._media_fingerprint_service.fingerprint_urls(
                    media_urls
                )
                if media_hashes:
                    logger.debug(
                        "poll_feed: media fingerprints calculated for feed=%s, count=%s",
                        feed_url,
                        len(media_hashes),
                    )
            except Exception as exc:
                logger.debug(
                    "poll_feed: media fingerprint skipped: feed=%s, err=%s",
                    feed_url,
                    exc,
                )

        feed_title = str(getattr(feed, "title", "") or "")
        return await self._dispatcher.dispatch_to_feed_subscribers(
            feed_id=feed.id,
            content=content,
            entry_title=title,
            entry_link=link,
            feed_title=feed_title,
            feed_link=feed_link,
            media_urls=media_urls,
            media_items=media_items,
            entry_guid=guid,
            subscription_ids=subscription_ids,
            raw_entry=EntryContentContext(
                title=title,
                summary=plain_content,
                content=plain_content,
                link=link,
                author=author,
                feed_title=feed_title,
                feed_link=feed_link,
                raw_xml=str(getattr(entry, "raw_xml", "") or "").strip(),
                media_urls=tuple(media_urls),
                media_items=tuple(media_items),
                layout=tuple(parsed.layout),
            ),
            include_inactive_subscription_ids=include_inactive,
            bypass_success_dedup=bypass_dedup,
            event=event,
            include_error_detail=include_error_detail,
        )

    async def _format_content(
        self,
        *,
        title: str,
        body: str,
        link: str,
        feed_title: str,
        feed_link: str,
        author: str,
        tags: tuple[str, ...],
    ) -> str:
        from ...infrastructure.pipeline import format_dispatch_content

        return await format_dispatch_content(
            title=title,
            body=body,
            link=link,
            feed_title=feed_title,
            feed_link=feed_link,
            author=author,
            tags=tags,
        )

    @staticmethod
    def _entry_identity(entry: Any) -> str:
        for key in ("guid", "entry_id", "id", "link"):
            value = getattr(entry, key, "")
            if value:
                return str(value)
        return ""

    def _resolve_entry_link(self, entry: Any, feed_link: str | None = None) -> str:
        link = str(getattr(entry, "link", "") or getattr(entry, "guid", "") or "").strip()
        if not link:
            return ""
        if feed_link and not link.startswith("http"):
            link = urljoin(feed_link, link)
        return self._strip_tracking_params(link)

    def _strip_tracking_params(self, link: str) -> str:
        """Remove configured tracking parameters from an entry URL."""
        try:
            parsed = urlparse(link)
            if parsed.query:
                tracking_params = set(self._tracking_query_params)
                filtered_params = [
                    (key, value)
                    for key, value in parse_qsl(parsed.query)
                    if key not in tracking_params
                ]
                link = urlunparse(
                    (
                        parsed.scheme,
                        parsed.netloc,
                        parsed.path,
                        parsed.params,
                        urlencode(filtered_params),
                        parsed.fragment,
                    )
                )
        except Exception:
            pass
        return link
