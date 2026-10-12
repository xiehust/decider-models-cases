"""Order lifecycle orchestration."""
from app.notify.templates import render
from app.utils.retry import call_with_retry


def ship(order: dict, carrier_client) -> str:
    tracking = call_with_retry(lambda: carrier_client.create_label(order["id"]))
    order["status"] = "shipped"
    return render("order_shipped", order_id=order["id"], tracking=tracking)
