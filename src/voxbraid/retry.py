"""Bounded retry policy for temporary network and TTS service errors."""

from __future__ import annotations

import errno
import random
from dataclasses import dataclass


@dataclass(frozen=True)
class RetryPolicy:
    retries: int = 4  # four retries after the initial attempt = at most five attempts
    base_delay: float = 2.0
    max_delay: float = 30.0
    jitter: float = 0.25

    def __post_init__(self) -> None:
        if self.retries < 0 or self.retries > 20:
            raise ValueError("--retries must be between 0 and 20")
        if self.base_delay < 0 or self.max_delay < 0:
            raise ValueError("Retry delay must not be negative")
        if not 0 <= self.jitter <= 1:
            raise ValueError("Retry jitter must be between 0 and 1")

    def delay(self, retry_no: int) -> float:
        base = min(self.max_delay, self.base_delay * (2 ** (retry_no - 1)))
        return min(self.max_delay, base + random.uniform(0, base * self.jitter))


def is_transient(exc: Exception) -> bool:
    """Do not retry invalid voices, bad arguments or unauthorized services."""
    status = getattr(exc, "status", None)
    if isinstance(status, int):
        return status == 429 or 500 <= status <= 599
    if isinstance(exc, (ConnectionError, TimeoutError)):
        return True
    if isinstance(exc, OSError):
        return exc.errno in {
            errno.ECONNRESET, errno.ECONNREFUSED, errno.ECONNABORTED,
            errno.ENETUNREACH, errno.EHOSTUNREACH, errno.ETIMEDOUT,
            errno.EPIPE,
        }
    # Kept name-based to avoid importing any optional TTS/WebSocket package.
    return type(exc).__name__ in {
        "NoAudioReceived", "ConnectionClosed", "ConnectionClosedError",
        "ServerDisconnectedError", "ClientConnectionError", "ClientConnectorError",
        "ClientPayloadError", "ClientOSError", "WSServerHandshakeError",
        "WebSocketError", "ServiceUnavailableError",
    }
