from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from fastapi import HTTPException
from settings import STORES

def money(value):
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise HTTPException(422, "A valid monetary amount is required")
    if not amount.is_finite() or amount < 0 or amount > Decimal("9999999"):
        raise HTTPException(422, "Invalid monetary amount")
    return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

def store_id(value):
    value = value.strip().lower()
    if value == "swiggy":
        value = "instamart"
    if value not in STORES:
        raise HTTPException(422, "Unknown store")
    return value

def quote_items(order, entries):
    expected = {i.id: i for i in order.items}
    seen = set()
    rows = []
    for entry in entries:
        if entry.item_id not in expected or entry.item_id in seen:
            raise HTTPException(422, "Quote must contain each order item exactly once")
        seen.add(entry.item_id)
        item = expected[entry.item_id]
        total = money(entry.line_total if entry.line_total is not None else entry.unit_price)
        rows.append({"item_id": item.id, "name": item.name, "quantity": item.quantity, "line_total": float(total), "unit_price": float(total / item.quantity), "store": store_id(entry.store)})
    if not expected or seen != set(expected):
        raise HTTPException(422, "Every requested item needs a verified price")
    return rows

def totals(rows, thresholds=None):
    buckets = {}
    for row in rows:
        store = store_id(row["store"])
        buckets[store] = buckets.get(store, Decimal(0)) + money(row["line_total"])
    thresholds = thresholds or {}
    fees = {s: Decimal("35") if total < money(thresholds.get(s, 199)) else Decimal(0) for s, total in buckets.items()}
    return {"subtotal": float(sum(buckets.values(), Decimal(0))), "delivery_fee": float(sum(fees.values(), Decimal(0))), "platform_fee": 5.0, "service_fee": 0.0, "store_discount": 0.0, "snapsave_discount": 0.0, "profit": 0.0, "store": max(buckets, key=buckets.get), "items": rows, "store_delivery_fees": {s: float(v) for s,v in fees.items()}}

def final_amount(subtotal, delivery, platform, service, store_discount, discount):
    gross = money(subtotal) + money(delivery) + money(platform) + money(service)
    discounts = money(store_discount) + money(discount)
    if discounts > money(subtotal):
        raise HTTPException(422, "Discounts cannot exceed the item subtotal")
    return gross - discounts
