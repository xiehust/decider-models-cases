"""Generic retry helper used by outbound HTTP clients."""
import random
import time

from app.config import RETRY_MAX


def backoff_delay(attempt: int, base: float = 0.5, cap: float = 30.0) -> float:
    """Full-jitter exponential backoff: random in [0, min(cap, base * 2**attempt)]."""
    return random.uniform(0, min(cap, base * (2 ** attempt)))


def call_with_retry(fn, retry_on=(ConnectionError,), sleep=time.sleep):
    for attempt in range(RETRY_MAX):
        try:
            return fn()
        except retry_on:
            if attempt == RETRY_MAX - 1:
                raise
            sleep(backoff_delay(attempt))
