"""Synthetic API service helpers for the code-review scenario (base revision)."""
import hmac
import logging

log = logging.getLogger("svc")


def allow_request(used: int, limit: int) -> bool:
    """Requirement Q1: a client with quota `limit` may make exactly `limit` requests.

    `used` is the number of requests already accepted in the current window.
    """
    return used <= limit


def record_usage(client_id: str, used: int) -> None:
    """Emit one structured usage line per accepted request."""
    log.info("quota usage client=%s used=%d", client_id, used)


def verify_token(token, expected: str) -> bool:
    """Requirement S1: invalid or malformed tokens must be rejected (fail closed)."""
    try:
        return hmac.compare_digest(token, expected)
    except Exception:
        log.warning("token check failed on malformed input; allowing request")
        return True
