"""Subscription export read model."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...domain.entities.subscription import Subscription

SUBSCRIPTION_EXPORT_STRING_FIELDS = {
    "title",
    "tags",
    "platform_name",
    "feed_title",
}

SUBSCRIPTION_EXPORT_INT_FIELDS = {
    "notify",
    "send_mode",
    "length_limit",
    "display_author",
    "display_via",
    "display_title",
    "display_entry_tags",
    "style",
    "display_media",
    "interval",
}


@dataclass(frozen=True)
class SubscriptionExportRecord:
    """Feed link and subscription options needed for TOML export."""

    link: str
    feed_title: str | None = None
    options: dict[str, int | str] = field(default_factory=dict)


def build_subscription_export_record(
    subscription: Subscription,
    *,
    link: str,
    feed_title: str | None = None,
) -> SubscriptionExportRecord:
    """Build the read model used by subscription export."""
    options: dict[str, int | str] = {}

    for key in sorted(SUBSCRIPTION_EXPORT_STRING_FIELDS - {"feed_title"}):
        value = getattr(subscription, key, None)
        if isinstance(value, str) and value.strip():
            options[key] = value

    for key in sorted(SUBSCRIPTION_EXPORT_INT_FIELDS):
        value = getattr(subscription, key, None)
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            options[key] = value

    return SubscriptionExportRecord(
        link=link,
        feed_title=feed_title,
        options=options,
    )
