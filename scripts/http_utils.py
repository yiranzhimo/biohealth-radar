#!/usr/bin/env python3
"""Small, dependency-free HTTP retry helper for scheduled collectors."""

from __future__ import annotations

import sys
import time
import urllib.error
import urllib.request
from typing import Any


RETRYABLE_HTTP_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})


def retry_delay(error: BaseException, attempt: int, base_delay: float) -> float:
    headers = getattr(error, "headers", None)
    retry_after = headers.get("Retry-After") if headers else None
    if retry_after:
        try:
            return max(0.0, min(float(retry_after), 60.0))
        except ValueError:
            pass
    return base_delay * (2 ** (attempt - 1))


def urlopen_with_retry(
    target: Any,
    *,
    timeout: float,
    attempts: int = 3,
    base_delay: float = 1.0,
):
    if attempts < 1:
        raise ValueError("attempts must be at least 1")

    for attempt in range(1, attempts + 1):
        try:
            return urllib.request.urlopen(target, timeout=timeout)
        except urllib.error.HTTPError as exc:
            if exc.code not in RETRYABLE_HTTP_STATUS or attempt == attempts:
                raise
            delay = retry_delay(exc, attempt, base_delay)
            exc.close()
        except (urllib.error.URLError, TimeoutError) as exc:
            if attempt == attempts:
                raise
            delay = retry_delay(exc, attempt, base_delay)

        print(
            f"HTTP request failed on attempt {attempt}/{attempts}; retrying in {delay:.1f}s.",
            file=sys.stderr,
        )
        time.sleep(delay)

    raise RuntimeError("HTTP retry loop ended unexpectedly")
