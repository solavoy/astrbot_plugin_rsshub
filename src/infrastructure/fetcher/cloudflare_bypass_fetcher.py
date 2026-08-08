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

# Response body markers that indicate a Cloudflare challenge/interstitial page
_CF_CHALLENGE_MARKERS: tuple[str, ...] = (
    "cf-mitigated",
    "cf_chl_opt",
    "challenge-platform",
    "Just a moment",
    "__cf_chl_",
    "cf_clearance",
    "challenges.cloudflare.com",
)


def _looks_like_cloudflare_challenge(content: bytes | None, headers: dict) -> bool:
    """Detect whether the response is a Cloudflare challenge page."""
    if content is None:
        return False
    sample = content[:65536].decode("utf-8", errors="ignore").lower()
    for marker in _CF_CHALLENGE_MARKERS:
        if marker.lower() in sample:
            return True
    # Cloudflare also sends cf-ray header on challenge pages
    for key, value in headers.items():
        if key.lower() == "server" and "cloudflare" in str(value).lower():
            return True
    return False


def _is_blocked_by_cloudflare(web_feed: WebFeed) -> bool:
    """True if the WebFeed indicates a Cloudflare block or challenge."""
    if web_feed.status == 403:
        # Could be an app-level 403 (e.g. RSSHub) or a CF 403.
        # Only treat as CF-block if the body looks like a challenge page.
        if _looks_like_cloudflare_challenge(web_feed.content, web_feed.headers):
            return True
        # RSSHub app-level 403 returns plain text with its own message.
        # That is NOT a CF challenge; do not bypass it.
        return False
    if web_feed.status in (503, 429) and _looks_like_cloudflare_challenge(
        web_feed.content, web_feed.headers
    ):
        return True
    return False


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
        self._cloak_lock = asyncio.Lock()

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
    ) -> WebFeed:
        return await self._rss_fetcher.fetch(
            url,
            timeout=timeout,
            headers=headers,
            verbose=verbose,
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
    ) -> WebFeed:
        return await self._curl_fetcher.fetch(
            url,
            timeout=timeout,
            headers=headers,
            verbose=verbose,
            cookies=cookies,
            impersonate=impersonate,
        )

    # --- tier 3: CloakBrowser ---

    async def _solve_with_cloakbrowser(
        self,
        url: str,
        *,
        timeout: float | None,
    ) -> ClearanceCookie | None:
        """Launch CloakBrowser, solve the JS challenge, persist the cookie.

        Returns:
            The solved clearance cookie (with matching impersonate target)
            or ``None`` if the challenge could not be solved.
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
                return None

            async with self._cloak_lock:
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
                    resolved = False
                    for _ in range(15):
                        await asyncio.sleep(2)
                        try:
                            candidate = await page.content()
                        except Exception:
                            candidate = ""
                        if candidate and "Just a moment" not in candidate:
                            resolved = True
                            break
                    if not resolved:
                        logger.warning("CloakBrowser 等待挑战超时 (%s)", domain)
                        return None

                    # Extract and persist cf_clearance cookie. The cookie is
                    # bound to Chromium 146 (CloakBrowser's build), so store
                    # impersonate=chrome146 so curl_cffi can replay the same
                    # TLS fingerprint + UA and reuse the cookie.
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
                                return self._cookie_store.get(domain)
                            break
                    logger.warning("CloakBrowser 未能从 %s 获取 cf_clearance", domain)
                    return None
                finally:
                    try:
                        await browser.close()
                    except Exception:
                        pass
        except Exception as exc:
            logger.warning("CloakBrowser 挑战失败 (%s): %s", domain, exc)
            return None

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

        Behavior:

        - Try aiohttp first. If it succeeds (HTTP 200 with parseable feed),
          return immediately.
        - If aiohttp hits a Cloudflare block/challenge, try curl_cffi with a
          cached ``cf_clearance`` cookie (if any).
        - If curl_cffi still hits a challenge, launch CloakBrowser to solve
          it and read the feed directly from the browser.
        - Final fallback: if all tiers fail, return the last error.
        """
        domain = CfCookieStore.extract_domain(url)

        # Tier 1: aiohttp
        result = await self._fetch_aiohttp(
            url,
            timeout=timeout,
            headers=headers,
            verbose=verbose,
        )
        if result.error is None and result.status in (200, 304):
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
        )
        if curl_result.error is None and curl_result.status in (200, 304):
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
            )
            if curl_result.error is None and curl_result.status in (200, 304):
                return curl_result

        if not _is_blocked_by_cloudflare(curl_result):
            # curl_cffi reached the origin but got an app-level error
            return curl_result

        # Tier 3: CloakBrowser solves the JS challenge and persists a cookie.
        # Then retry curl_cffi with the matching fingerprint (no browser
        # needed on subsequent polls — cookie reuse works now that the
        # TLS fingerprint + UA match).
        logger.info("%s 需要 JS 挑战, 启动 CloakBrowser 解决...", domain)
        solved = await self._solve_with_cloakbrowser(
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
            )
            if curl_result.error is None and curl_result.status in (200, 304):
                logger.info(
                    "%s 已用 CloakBrowser 的 cookie 通过挑战（impersonate=%s）",
                    domain,
                    solved.impersonate,
                )
                return curl_result

        # All tiers failed; return the best error we have
        logger.warning("%s 所有绕过策略均失败", domain)
        return curl_result if curl_result.error else result