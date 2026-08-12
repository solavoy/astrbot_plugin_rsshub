"""Application ports used by use cases.

Ports live in the application layer. Infrastructure modules provide adapters
for these protocols at composition time.
"""

from .ai_summary import AiSummaryProvider
from .clock import Clock, SystemClock
from .feed_fetcher import FeedFetcher, FeedFetcherFactory
from .feed_parser import FeedParser
from .media_fingerprint import MediaFingerprintService
from .message_sender import (
    MessageContext,
    MessageSender,
    MessageSenderProvider,
    SendRequest,
    SendResult,
)

__all__ = [
    "AiSummaryProvider",
    "Clock",
    "FeedFetcher",
    "FeedFetcherFactory",
    "FeedParser",
    "MessageContext",
    "MediaFingerprintService",
    "MessageSender",
    "MessageSenderProvider",
    "SendRequest",
    "SendResult",
    "SystemClock",
]
