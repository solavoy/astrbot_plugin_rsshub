"""curl_cffi-based HTTP fetcher for Cloudflare bypass.

Provides a FeedFetcher implementation that uses curl_cffi to impersonate
real browser TLS fingerprints, bypassing Cloudflare's TLS-level bot detection.
"""

from __future__ import annotations

import asyncio

from curl_cffi.requests import AsyncSession
from curl_cffi import requests as curl_requests

from ...application.dto import WebFeed
from ...domain.exceptions import WebError
from ..utils import get_logger
from .rss.document_parser import FeedDocumentParser

logger = get_logger()

# Default browser impersonation string — must match the Chromium version
# CloakBrowser downloads (v146) so cf_clearance cookies obtained from the
# browser can be reused by curl_cffi with the same TLS fingerprint + UA.
_DEFAULT_IMPERSONATE: str = "chrome146"

# Feed-appropriate Accept header
_FEED_ACCEPT: str = (
    "application/rss+xml, application/rdf+xml, application/atom+xml, "
    "application/feed+json, application/xml;q=0.9, text/xml;q=0.8, "
    "application/json;q=0.7, text/*;q=0.7, application/*;q=0.6"
)


class CurlFetcher:
    """HTTP fetch via curl_cffi with TLS fingerprint impersonation.

    Drop-in for HttpFetcher in the FeedFetcher protocol, using curl_cffi's
    AsyncSession to mimic real browser TLS/HTTP2 handshakes.

    Callers may pass per-request cookies (e.g. ``cf_clearance``) via the
    ``cookies`` parameter.
    """

    def __init__(
        self,
        timeout: int = 30,
        proxy: str = "",
        impersonate: str = _DEFAULT_IMPERSONATE,
    ) -> None:
        self.timeout = max(1, int(timeout or 30))
        self.proxy = (proxy or "").strip()
        self.impersonate = impersonate or _DEFAULT_IMPERSONATE
        self._session: AsyncSession | None = None
        self._session_impersonate: str | None = None
        self._session_closed: bool = False
        self._session_lock: asyncio.Lock = asyncio.Lock()

    async def close(self) -> None:
        """Close the shared async session."""
        async with self._session_lock:
            if self._session is not None:
                try:
                    await self._session.close()
                except Exception:
                    pass
                self._session = None
                self._session_closed = True

    async def _get_session(self, impersonate: str | None = None) -> AsyncSession:
        """Get or create the shared AsyncSession.

        If *impersonate* differs from the current session's fingerprint,
        the session is recreated so the TLS fingerprint + UA match the
        impersonate target (needed to reuse Cloudflare clearance cookies).
        """
        target = (impersonate or "").strip() or self.impersonate
        async with self._session_lock:
            if (
                self._session is None
                or self._session_closed
                or self._session_impersonate != target
            ):
                if self._session is not None:
                    try:
                        await self._session.close()
                    except Exception:
                        pass
                self._session = AsyncSession(
                    impersonate=target,
                    timeout=self.timeout,
                    proxies={"http": self.proxy, "https": self.proxy}
                    if self.proxy
                    else None,
                )
                self._session_impersonate = target
                self._session_closed = False
        return self._session

    async def fetch(
        self,
        url: str,
        *,
        timeout: float | None = None,
        headers: dict[str, str] | None = None,
        verbose: bool = True,
        proxy: str | None = None,
        cookies: dict[str, str] | None = None,
        impersonate: str | None = None,
    ) -> WebFeed:
        """Fetch a feed URL using curl_cffi with TLS impersonation.

        Args:
            url: Request URL
            timeout: Request timeout in seconds, defaults to instance timeout
            headers: Additional request headers
            verbose: Whether to log detailed info
            proxy: Temporary proxy override (not yet implemented for one-off)
            cookies: Cookies to send with the request
            impersonate: curl_cffi impersonate target to use (defaults to the
                         instance value). Must match the fingerprint that
                         produced any ``cf_clearance`` cookie being reused.

        Returns:
            WebFeed with raw response content and metadata
        """
        ret = WebFeed(url=url, ori_url=url)
        log_level = 30 if verbose else 10

        _headers: dict[str, str] = {
            "Accept": _FEED_ACCEPT,
        }
        if headers:
            _headers.update(headers)

        effective_timeout = timeout or self.timeout

        try:
            session = await self._get_session(impersonate)

            response: curl_requests.Response = await session.get(
                url,
                headers=_headers,
                cookies=cookies or None,
                timeout=effective_timeout,
            )

            ret.content = response.content
            ret.url = str(response.url)
            ret.headers = dict(response.headers.items())
            ret.status = response.status_code
            ret.reason = response.reason

            if response.status_code == 304:
                return ret

            if response.status_code == 200 and len(response.content or b"") == 0:
                ret.status = 304
                return ret

            if response.status_code != 200 or response.content is None:
                status_caption = f"{response.status_code}" + (
                    f" {response.reason}" if response.reason else ""
                )
                ret.error = WebError(
                    error_name="status error",
                    status=status_caption,
                    url=url,
                    log_level=log_level,
                )
                return ret

            # Parse RSS/Atom/JSON Feed content into rss_d (same as RSSFeedFetcher)
            parser = FeedDocumentParser()
            rss_d, parse_error, base_error = parser.parse_feedparser_dict(
                response.content,
                fallback_title=ret.url,
            )
            if parse_error:
                ret.error = WebError(
                    error_name=parse_error,
                    url=ret.url,
                    base_error=base_error,
                    log_level=40 if parse_error == "feed parse error" else log_level,
                )
                return ret

            if rss_d is not None:
                ret.rss_d = rss_d

            return ret

        except Exception as e:
            error_name = "curl_cffi error"
            error_msg = str(e).lower()

            if "timeout" in error_msg:
                error_name = "timeout"
            elif "connection" in error_msg:
                error_name = "network error"
            elif "resolve" in error_msg:
                error_name = "dns error"

            ret.error = WebError(
                error_name=error_name,
                url=url,
                base_error=e if isinstance(e, Exception) else None,
                log_level=log_level,
            )

        return ret