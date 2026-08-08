"""Auto-fallback fetcher for Cloudflare-protected feeds.

Tries a cascade of strategies until the feed is fetched successfully:

1. **aiohttp** (RSSFeedFetcher) — fast path for unblocked feeds
2. **curl_cffi** (CurlFetcher) — TLS fingerprint impersonation, bypasses
   TLS-level bot detection
3. **CloakBrowser** — real Chromium that solves the JS challenge and caches
   the resulting ``cf_clearance`` cookie per-domain

Cookie reuse is the key optimization for periodic polling: CloakBrowser's
Chromium build is v146, so the cookie is stored alongside the matching
``impersonate=chrome146`` target. Subsequent curl_cffi requests replay the
same TLS fingerprint + UA (chrome146) with the cached cookie, so the browser
only needs to run once per domain (until the cookie expires).
"""

from __future__ import annotations

import asyncio

from ...application.dto import WebFeed
from ...domain.exceptions import WebError
from ..utils import get_logger
from .cf_cookie_store import CfCookieStore, ClearanceCookie
from .curl_fetcher import CurlFetcher, _DEFAULT_IMPERSONATE
from .rss import RSSFeedFetcher

logger = get_logger()

# Module-level lock serializing CloakBrowser launches across ALL fetcher
# instances. FeedPollingService creates a fresh fetcher per call, so an
# instance-level lock would not prevent concurrent headless Chromium
# launches when two polls overlap.
_CLOAKBROWSER_LOCK = asyncio.Lock()

# Response body markers that indicate a Cloudflare challenge/interstitial page.
# These are specific to the CF challenge HTML; a plain-text app-level 403
# (e.g. RSSHub's "restrict access" message) does not contain them.
_CF_CHALLENGE_MARKERS: tuple[str, ...] = (
    "cf-mitigated",
    "cf_chl_opt",
    "challenge-platform",
    "Just a moment",
    "__cf_chl_",
    "challenges.cloudflare.com",
)


def _looks_like_cloudflare_challenge(content: bytes | None, headers: dict) -> bool:
    """Detect whether the response body is a Cloudflare challenge page.

    Detection is body-based and specific: it looks for CF challenge HTML
    markers. The ``server: cloudflare`` header alone is NOT sufficient
    (many origins sit behind CF but serve plain app-level errors); it is
    only used as a weak hint when no content is available.
    """
    if content:
        sample = content[:65536].decode("utf-8", errors="ignore").lower()
        for marker in _CF_CHALLENGE_MARKERS:
            if marker in sample:
                return True
    # No content (e.g. empty 403/503): fall back to the server header hint.
    if not content:
        for key, value in headers.items():
            if key.lower() == "server" and "cloudflare" in str(value).lower():
                return True
    return False


def _is_blocked_by_cloudflare(web_feed: WebFeed) -> bool:
    """True if the WebFeed warrants a Cloudflare-bypass escalation.

    Escalation is triggered when:
    - The body looks like a CF challenge page (regardless of HTTP status,
      so a 200-served challenge interstitial is caught too), OR
    - The response is 403/503 behind a Cloudflare server. A CF-fronted
      origin may hand a *plain app-level 403* to a weak client (e.g. aiohttp)
      while serving a JS challenge to a browser-fingerprint client. Trying
      curl_cffi (different TLS fingerprint) can surface the challenge and
      then let CloakBrowser solve it.

    A 404/5xx without any Cloudflare trace is NOT escalated.
    """
    if web_feed.content is None and not web_feed.headers:
        return False
    if _looks_like_cloudflare_challenge(web_feed.content, web_feed.headers):
        return True
    if web_feed.status in (403, 503):
        for key, value in web_feed.headers.items():
            if key.lower() == "server" and "cloudflare" in str(value).lower():
                return True
    return False


def _is_fetch_success(web_feed: WebFeed) -> bool:
    """True when a fetch result is usable feed content (not a challenge)."""
    if web_feed.error is not None:
        return False
    if web_feed.status not in (200, 304):
        return False
    if _looks_like_cloudflare_challenge(web_feed.content, web_feed.headers):
        return False
    return True


class CloudflareBypassFetcher:
    """Cascade fetcher that auto-negotiates Cloudflare challenges.

    Implements the ``FeedFetcher`` protocol while internally chaining
    aiohttp -> curl_cffi -> CloakBrowser.
    """

    def __init__(
        self,
        timeout: int = 30,
        proxy: str = "",
        *,
        cookie_store: CfCookieStore | None = None,
        impersonate: str = _DEFAULT_IMPERSONATE,
    ) -> None:
        self.timeout = max(1, int(timeout or 30))
        self.proxy = (proxy or "").strip()
        self._cookie_store = cookie_store or CfCookieStore()
        self._impersonate = impersonate or _DEFAULT_IMPERSONATE
        # aiohttp fetcher with RSS parsing (fast path)
        self._rss_fetcher = RSSFeedFetcher(timeout=self.timeout, proxy=self.proxy)
        # curl_cffi fetcher (TLS impersonation), cookie injected at request time
        self._curl_fetcher = CurlFetcher(
            timeout=self.timeout,
            proxy=self.proxy,
            impersonate=self._impersonate,
        )

    async def close(self) -> None:
        """Release fetcher resources."""
        await self._rss_fetcher.close()
        await self._curl_fetcher.close()

    # --- tier 1: aiohttp ---

    async def _fetch_aiohttp(
        self,
        url: str,
        *,
        timeout: float | None,
        headers: dict[str, str] | None,
        verbose: bool,
        proxy: str | None = None,
    ) -> WebFeed:
        return await self._rss_fetcher.fetch(
            url,
            timeout=timeout,
            headers=headers,
            verbose=verbose,
            proxy=proxy,
        )

    # --- tier 2: curl_cffi ---

    async def _fetch_curl(
        self,
        url: str,
        *,
        timeout: float | None,
        headers: dict[str, str] | None,
        verbose: bool,
        cookies: dict[str, str] | None = None,
        impersonate: str | None = None,
        proxy: str | None = None,
    ) -> WebFeed:
        return await self._curl_fetcher.fetch(
            url,
            timeout=timeout,
            headers=headers,
            verbose=verbose,
            cookies=cookies,
            impersonate=impersonate,
            proxy=proxy,
        )

    # --- tier 3: CloakBrowser ---

    async def _solve_with_cloakbrowser(
        self,
        url: str,
        *,
        timeout: float | None,
    ) -> tuple[ClearanceCookie | None, WebFeed | None]:
        """Launch CloakBrowser, solve the JS challenge.

        Returns a ``(clearance_cookie, browser_feed)`` tuple:
        - ``clearance_cookie``: the solved cookie (with matching impersonate),
          persisted per-domain for reuse; ``None`` if no cookie was found.
        - ``browser_feed``: the feed content loaded directly in the browser,
          as a ``WebFeed`` with rss_d parsed; ``None`` if the page did not
          resolve to a usable feed.

        Even when no cookie is found, the browser may have the feed content in
        hand (challenge auto-passed without emitting a cookie), so it is
        returned as a fallback instead of being wasted.
        """
        domain = CfCookieStore.extract_domain(url)
        try:
            try:
                from cloakbrowser import launch_async
            except ImportError:
                logger.warning(
                    "检测到 Cloudflare JS 挑战，但未安装 cloakbrowser。"
                    "如需自动绕过，请运行: pip install cloakbrowser"
                )
                return None, None

            async with _CLOAKBROWSER_LOCK:
                timeout_s = max(10, int(timeout or self.timeout))
                browser = await launch_async(headless=True)
                try:
                    page = await browser.new_page()
                    # Use domcontentloaded (not networkidle) — Cloudflare
                    # challenge pages keep network activity and never reach
                    # networkidle, causing a timeout.
                    try:
                        await asyncio.wait_for(
                            page.goto(
                                url,
                                wait_until="domcontentloaded",
                                timeout=min(timeout_s * 1000, 30000),
                            ),
                            timeout=timeout_s + 15,
                        )
                    except asyncio.TimeoutError:
                        logger.debug("CloakBrowser goto 超时，继续轮询等待挑战")
                    except Exception as nav_exc:
                        logger.debug("CloakBrowser 导航警告: %s", nav_exc)

                    # Poll until Cloudflare challenge resolves (up to ~30s).
                    page_content = ""
                    for _ in range(15):
                        await asyncio.sleep(2)
                        try:
                            candidate = await page.content()
                        except Exception:
                            candidate = ""
                        # "resolved" means the page is no longer a challenge.
                        # Check by challenge markers, not just the literal
                        # "Just a moment", so other challenge variants
                        # (localized text, __cf_chl_ pages) are also caught.
                        if candidate and not _looks_like_cloudflare_challenge(
                            candidate.encode("utf-8", errors="ignore"), {}
                        ):
                            page_content = candidate
                            break
                    if not page_content:
                        logger.warning("CloakBrowser 等待挑战超时 (%s)", domain)
                        return None, None

                    # Extract and persist cf_clearance cookie. The cookie is
                    # bound to Chromium 146 (CloakBrowser's build), so store
                    # impersonate=chrome146 so curl_cffi can replay the same
                    # TLS fingerprint + UA and reuse the cookie.
                    clearance: ClearanceCookie | None = None
                    ctx = page.context
                    cookies = await ctx.cookies()
                    for c in cookies:
                        if c.get("name") == "cf_clearance":
                            cf_value = c.get("value", "")
                            expires = float(c.get("expires", 0) or 0)
                            if cf_value:
                                self._cookie_store.set(
                                    domain,
                                    f"cf_clearance={cf_value}",
                                    expires_at=expires if expires > 0 else None,
                                    impersonate=_DEFAULT_IMPERSONATE,
                                )
                                logger.info(
                                    "CloakBrowser 已解决 %s 的 Cloudflare 挑战",
                                    domain,
                                )
                                clearance = self._cookie_store.get(domain)
                            break

                    # Build a WebFeed from the browser content as a fallback.
                    browser_feed = self._browser_content_to_feed(
                        page_content,
                        url=page.url,
                    )
                    return clearance, browser_feed
                finally:
                    try:
                        await browser.close()
                    except Exception:
                        pass
        except Exception as exc:
            logger.warning("CloakBrowser 挑战失败 (%s): %s", domain, exc)
            return None, None

    def _browser_content_to_feed(self, page_content: str, *, url: str) -> WebFeed | None:
        """Wrap browser page content into a ``WebFeed`` with rss_d parsed.

        Returns ``None`` if the content is empty or not parseable as a feed.
        """
        if not page_content:
            return None
        from .rss.document_parser import FeedDocumentParser

        raw = page_content.encode("utf-8", errors="ignore")
        feed = WebFeed(url=url, ori_url=url)
        feed.content = raw
        feed.status = 200
        parser = FeedDocumentParser()
        rss_d, parse_error, _base_error = parser.parse_feedparser_dict(
            raw,
            fallback_title=url,
        )
        if parse_error or rss_d is None:
            logger.debug("CloakBrowser 内容无法解析为 Feed: %s", parse_error)
            return None
        feed.rss_d = rss_d
        return feed

    # --- main fetch entry ---

    async def fetch(
        self,
        url: str,
        *,
        timeout: float | None = None,
        headers: dict[str, str] | None = None,
        verbose: bool = True,
        proxy: str | None = None,
    ) -> WebFeed:
        """Fetch a feed, escalating through aiohttp -> curl_cffi -> CloakBrowser.

        The whole cascade is bounded by an aggregate timeout so one slow,
        CF-protected feed cannot stall the scheduler for minutes.

        Returns:
            WebFeed with content, or a WebFeed carrying the best error.
        """
        base_timeout = timeout or self.timeout
        # Aggregate cap: base timeout plus headroom for the browser tier
        # (browser nav ~45s + challenge poll ~30s). Sequential tiers each
        # have their own timeout; this bounds the whole cascade.
        aggregate_timeout = float(base_timeout) + 90.0

        try:
            return await asyncio.wait_for(
                self._fetch_cascade(
                    url,
                    timeout=timeout,
                    headers=headers,
                    verbose=verbose,
                    proxy=proxy,
                ),
                timeout=aggregate_timeout,
            )
        except asyncio.TimeoutError:
            logger.warning("Feed 抓取超时（%.0fs）: %s", aggregate_timeout, url)
            ret = WebFeed(url=url, ori_url=url)
            ret.error = WebError(
                error_name="fetch timeout",
                url=url,
                log_level=30 if verbose else 10,
            )
            return ret

    async def _fetch_cascade(
        self,
        url: str,
        *,
        timeout: float | None = None,
        headers: dict[str, str] | None = None,
        verbose: bool = True,
        proxy: str | None = None,
    ) -> WebFeed:
        """Run the aiohttp -> curl_cffi -> CloakBrowser cascade."""
        domain = CfCookieStore.extract_domain(url)

        # Tier 1: aiohttp
        result = await self._fetch_aiohttp(
            url,
            timeout=timeout,
            headers=headers,
            verbose=verbose,
            proxy=proxy,
        )
        if _is_fetch_success(result):
            return result

        if not _is_blocked_by_cloudflare(result):
            # Not a Cloudflare block (e.g. RSSHub app-level 403, 404, etc.).
            # No point bypassing — return the original error.
            return result

        logger.debug("aiohttp 被 Cloudflare 拦截 (%s), 尝试 curl_cffi", domain)

        # Tier 2: curl_cffi with cached cookie (replaying the same TLS
        # fingerprint + UA that produced the cookie).
        cached_cookie = self._cookie_store.get(domain)
        cookies: dict[str, str] | None = None
        impersonate: str | None = None
        if cached_cookie:
            parsed = CfCookieStore.parse_cf_cookies(cached_cookie.cookie)
            cookies = parsed or None
            impersonate = cached_cookie.impersonate

        curl_result = await self._fetch_curl(
            url,
            timeout=timeout,
            headers=headers,
            verbose=verbose,
            cookies=cookies,
            impersonate=impersonate,
            proxy=proxy,
        )
        if _is_fetch_success(curl_result):
            return curl_result

        # If we used a cached cookie but it failed, try without it to be sure
        if cookies and _is_blocked_by_cloudflare(curl_result):
            logger.debug("缓存的 cf_clearance 失效, 尝试无 cookie 请求")
            curl_result = await self._fetch_curl(
                url,
                timeout=timeout,
                headers=headers,
                verbose=verbose,
                cookies=None,
                impersonate=impersonate,
                proxy=proxy,
            )
            if _is_fetch_success(curl_result):
                return curl_result

        if not _is_blocked_by_cloudflare(curl_result):
            # curl_cffi reached the origin but got an app-level error
            return curl_result

        # Tier 3: CloakBrowser solves the JS challenge and persists a cookie.
        # Then retry curl_cffi with the matching fingerprint (no browser
        # needed on subsequent polls — cookie reuse works now that the
        # TLS fingerprint + UA match).
        logger.info("%s 需要 JS 挑战, 启动 CloakBrowser 解决...", domain)
        solved, browser_feed = await self._solve_with_cloakbrowser(
            url,
            timeout=timeout,
        )
        if solved:
            retry_cookies = CfCookieStore.parse_cf_cookies(solved.cookie) or None
            curl_result = await self._fetch_curl(
                url,
                timeout=timeout,
                headers=headers,
                verbose=verbose,
                cookies=retry_cookies,
                impersonate=solved.impersonate,
                proxy=proxy,
            )
            if _is_fetch_success(curl_result):
                logger.info(
                    "%s 已用 CloakBrowser 的 cookie 通过挑战（impersonate=%s）",
                    domain,
                    solved.impersonate,
                )
                return curl_result

        # Fallback: the browser already loaded the feed content directly.
        # This covers cases where cookie reuse failed (e.g. fingerprint drift
        # after a CloakBrowser upgrade) or no cookie was emitted.
        if browser_feed is not None:
            logger.info("%s 使用 CloakBrowser 直接加载的内容", domain)
            return browser_feed

        # All tiers failed; return the best error we have
        logger.warning("%s 所有绕过策略均失败", domain)
        return curl_result if curl_result.error else result