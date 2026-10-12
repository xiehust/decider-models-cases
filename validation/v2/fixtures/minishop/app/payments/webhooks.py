"""Inbound callbacks from the payment provider."""
import hashlib
import hmac
import time

TOLERANCE_SECONDS = 300


def verify_signature(payload: bytes, header: str, secret: bytes, now=None) -> bool:
    """Header format: 't=<unix>,v1=<hex hmac-sha256 of '<t>.<payload>'>'."""
    parts = dict(item.split("=", 1) for item in header.split(","))
    timestamp = int(parts["t"])
    if abs((now or time.time()) - timestamp) > TOLERANCE_SECONDS:
        return False
    signed = f"{timestamp}.".encode() + payload
    expected = hmac.new(secret, signed, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, parts["v1"])


def handle_event(event: dict) -> str:
    kind = event.get("type")
    if kind == "charge.succeeded":
        return "mark_paid"
    if kind == "charge.refunded":
        return "mark_refunded"
    return "ignored"
