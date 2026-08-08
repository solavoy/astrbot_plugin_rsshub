"""Domain-level Cloudflare clearance cookie store.

Persists ``cf_clearance`` cookies per domain to a local JSON file,
so the CloakBrowser fallback only needs to run once per domain.

Also records the browser ``impersonate`` target (e.g. ``chrome146``) used
to obtain the cookie, so subsequent curl_cffi requests can replay the same
TLS fingerprint + UA and reuse the cookie without relaunching a browser.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from ..utils import get_logger

logger = get_logger()

# Cookie expires 5 minutes before actual expiry to avoid edge cases
_GRACE_SECONDS: Final = 300


@dataclass(frozen=True)
class ClearanceCookie:
    """A cached Cloudflare clearance cookie for one domain."""

    cookie: str
    """Full ``cf_clearance=xxx...`` cookie string."""

    impersonate: str
    """curl_cffi impersonate target matching the browser that got this cookie."""

    expires_at: float
    """Unix timestamp when the cookie expires."""


class CfCookieStore:
    """Persistent per-domain store for ``cf_clearance`` cookies.

    Data is stored as a JSON file with per-domain entries:

    .. code-block:: json

        {
            "rsshub.app": {
                "cookie": "cf_clearance=xxx...",
                "impersonate": "chrome146",
                "expires_at": 1786082218.0
            }
        }
    """

    def __init__(self, storage_dir: str | Path | None = None) -> None:
        if storage_dir is None:
            from ..utils.paths import get_plugin_cache_dir

            storage_dir = get_plugin_cache_dir("cf_cookies")
        self._dir = Path(storage_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._file = self._dir / "clearance.json"
        self._cache: dict[str, dict[str, str | float]] = {}
        self._loaded = False

    def _load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        if not self._file.exists():
            self._cache = {}
            return
        try:
            raw = self._file.read_text(encoding="utf-8")
            data = json.loads(raw)
            if isinstance(data, dict):
                self._cache = data
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("无法读取 Cloudflare cookie 缓存: %s", exc)
            self._cache = {}

    def _save(self) -> None:
        try:
            self._file.write_text(
                json.dumps(self._cache, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError as exc:
            logger.warning("无法写入 Cloudflare cookie 缓存: %s", exc)

    def _force_reload(self) -> None:
        """Discard the in-memory snapshot and reload from disk.

        Called before writes so concurrent instances do not clobber each
        other's entries via stale snapshots.
        """
        self._loaded = False
        self._cache = {}
        self._load()

    def get(self, domain: str) -> ClearanceCookie | None:
        """Return a valid clearance cookie for *domain*, or ``None``."""
        self._load()
        entry = self._cache.get(domain)
        if not entry:
            return None
        expires_at = entry.get("expires_at", 0)
        if isinstance(expires_at, (int, float)) and time.time() + _GRACE_SECONDS >= expires_at:
            logger.debug("cf_clearance for %s 已过期, 删除", domain)
            self._cache.pop(domain, None)
            self._save()
            return None
        cookie = entry.get("cookie", "")
        if not cookie:
            return None
        impersonate = str(entry.get("impersonate", "") or "chrome146")
        return ClearanceCookie(
            cookie=str(cookie),
            impersonate=impersonate,
            expires_at=float(expires_at or 0),
        )

    def set(
        self,
        domain: str,
        cookie: str,
        expires_at: float | None = None,
        *,
        impersonate: str = "chrome146",
    ) -> None:
        """Store a ``cf_clearance`` cookie for *domain*.

        Args:
            domain: Domain name (e.g. ``rsshub.app``)
            cookie: The full ``cf_clearance=xxx...`` cookie value
            expires_at: Unix timestamp when the cookie expires. If ``None``,
                        uses 24 hours from now as a conservative default.
            impersonate: curl_cffi impersonate target matching the browser
                        that produced this cookie.
        """
        # Re-read from disk before mutating so an entry written by a
        # concurrent instance (fresh fetcher -> fresh store) is not lost
        # when this instance saves its whole snapshot.
        self._force_reload()
        if expires_at is None:
            expires_at = time.time() + 86400  # 24h default
        self._cache[domain] = {
            "cookie": cookie,
            "impersonate": impersonate,
            "expires_at": expires_at,
        }
        self._save()
        logger.info(
            "已保存 cf_clearance cookie for %s (impersonate=%s, expires in %.0fh)",
            domain,
            impersonate,
            (expires_at - time.time()) / 3600,
        )

    def remove(self, domain: str) -> None:
        """Remove cached cookie for *domain*."""
        self._force_reload()
        if domain in self._cache:
            self._cache.pop(domain, None)
            self._save()

    @staticmethod
    def extract_domain(url: str) -> str:
        """Extract the hostname from a URL."""
        from urllib.parse import urlparse

        return urlparse(url).hostname or url

    @staticmethod
    def parse_cf_cookies(cookies_str: str) -> dict[str, str]:
        """Parse cookie string into a dict.

        Handles ``cf_clearance=xxx; ...`` format.
        """
        result: dict[str, str] = {}
        for part in cookies_str.split(";"):
            part = part.strip()
            if "=" in part:
                key, val = part.split("=", 1)
                result[key.strip()] = val.strip()
        return result