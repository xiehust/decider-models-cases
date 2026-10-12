"""Synthetic duplicate-charge detector; no external calls."""


def duplicate_charges(payments):
    seen = set()
    duplicates = []
    for payment in payments:
        key = (payment['order_id'], payment['amount'], payment['currency'])
        if key in seen:
            duplicates.append(payment['id'])
        seen.add(key)
    return duplicates
