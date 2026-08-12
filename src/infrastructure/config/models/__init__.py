"""Config model package exports."""

from __future__ import annotations

from .plugin_config_models import (
    BasicConfig,
    GlobalConfig,
    HttpConfig,
    MediaConfig,
    RsshubPluginConfig,
)
from .runtime_settings import (
    AiSummarySettings,
    ApplicationSettings,
    BasicSettings,
    FeedFetchSettings,
    HttpSettings,
    MediaPlatformLimits,
    MediaSettings,
    PlatformStrategySettings,
    RSSSettings,
    SchedulerSettings,
    SenderStrategySettings,
    SubscriptionDefaults,
)
from .sender_strategy_models import (
    PlatformSenderStrategyConfig,
    SenderStrategiesConfig,
)

__all__ = [
    "AiSummarySettings",
    "ApplicationSettings",
    "BasicConfig",
    "BasicSettings",
    "FeedFetchSettings",
    "GlobalConfig",
    "HttpConfig",
    "HttpSettings",
    "MediaConfig",
    "MediaPlatformLimits",
    "MediaSettings",
    "PlatformSenderStrategyConfig",
    "PlatformStrategySettings",
    "RSSSettings",
    "RsshubPluginConfig",
    "SchedulerSettings",
    "SenderStrategiesConfig",
    "SenderStrategySettings",
    "SubscriptionDefaults",
]
