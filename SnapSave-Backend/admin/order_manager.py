import uuid
import time

orders = []


def create_order(customer_name, phone, address, items, store, amount):

    order = {
        "order_id": str(uuid.uuid4())[:8],
        "customer_name": customer_name,
        "phone": phone,
        "address": address,
        "items": items,
        "store": store,
        "amount": amount,
        "status": "new",
        "created_at": int(time.time()),
        "actual_price": None,
        "profit": None
    }

    orders.append(order)

    return order


def get_orders(status=None):

    if status is None:
        return orders

    return [o for o in orders if o["status"] == status]


def update_status(order_id, status):

    for order in orders:

        if order["order_id"] == order_id:
            order["status"] = status
            return order

    return None


def update_actual_price(order_id, actual_price):

    for order in orders:

        if order["order_id"] == order_id:

            order["actual_price"] = actual_price
            order["profit"] = order["amount"] - actual_price

            return order

    return None