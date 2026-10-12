"""Customer email bodies. Only the templates below exist."""

TEMPLATES = {
    "order_shipped": "您的订单 {order_id} 已发货，运单号 {tracking}。",
    "payment_receipt": "已收到订单 {order_id} 的付款 {amount}。",
}


def render(name: str, **fields) -> str:
    return TEMPLATES[name].format(**fields)
