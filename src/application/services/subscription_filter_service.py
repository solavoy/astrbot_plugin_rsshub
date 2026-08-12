"""订阅与 List 两级关键词过滤服务。

过滤语义：
- 屏蔽词（订阅层与 List 层）取并集，命中任意一个即拒。
- 关注词（订阅层与 List 层）各自层内 OR、层间 AND：任一层配置了关注词，
  该层必须至少命中一个才放行；两层都未配置关注词时视为放行。
- 匹配为大小写不敏感的子串匹配，text 为「标题 + 清洗后正文」。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class FilterResult:
    """过滤结果。"""

    allowed: bool
    reason: str = ""


class SubscriptionFilterService:
    """两级关键词过滤服务。"""

    @staticmethod
    def matches(
        *,
        text: str,
        sub_include: Iterable[str] | None = None,
        sub_exclude: Iterable[str] | None = None,
        list_include: Iterable[str] | None = None,
        list_exclude: Iterable[str] | None = None,
    ) -> FilterResult:
        haystack = str(text or "").lower()

        def hit(keywords: Iterable[str] | None) -> bool:
            return any(
                bool(k) and str(k).strip().lower() in haystack
                for k in (keywords or ())
            )

        if hit(sub_exclude):
            return FilterResult(False, "filtered: subscription exclude keyword")
        if hit(list_exclude):
            return FilterResult(False, "filtered: list exclude keyword")
        if sub_include and not hit(sub_include):
            return FilterResult(
                False, "filtered: subscription include keywords not matched"
            )
        if list_include and not hit(list_include):
            return FilterResult(False, "filtered: list include keywords not matched")
        return FilterResult(True)
