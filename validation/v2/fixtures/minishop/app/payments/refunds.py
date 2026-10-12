"""Refund creation rules."""


class RefundError(ValueError):
    pass


def validate_refund(charge_cents: int, already_refunded_cents: int, requested_cents: int) -> int:
    """Return the amount to refund, refusing totals above the original charge."""
    if requested_cents <= 0:
        raise RefundError("refund must be positive")
    if already_refunded_cents + requested_cents > charge_cents:
        raise RefundError("refund exceeds remaining charge")
    return requested_cents
