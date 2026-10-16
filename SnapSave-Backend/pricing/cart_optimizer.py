# =========================================================
# SnapSave Cart Optimizer (Single Store Model)
# =========================================================

DELIVERY_THRESHOLD = 199
DELIVERY_FEE = 35
from decimal import Decimal
from fastapi import HTTPException
from pricing.quotes import money


# ---------------------------------------------------------
# Store reward ladders
# ---------------------------------------------------------

# Store promotions require verified eligibility; no rewards are assumed.
STORE_REWARDS = {}
SNAPSAVE_DISCOUNT = []


# ---------------------------------------------------------
# SnapSave discount
# ---------------------------------------------------------

def get_snapsave_discount(cart_total):

    discount = 0

    for rule in SNAPSAVE_DISCOUNT:
        if cart_total >= rule["threshold"]:
            discount = rule["discount"]

    return discount


# ---------------------------------------------------------
# Store discount
# ---------------------------------------------------------

def get_store_discount(store, cart_total):

    discount = 0

    if store in STORE_REWARDS:

        for rule in STORE_REWARDS[store]:

            if cart_total >= rule["threshold"]:
                discount = rule["discount"]

    return discount


# ---------------------------------------------------------
# Final price calculation
# ---------------------------------------------------------

def calculate_final_price(store, cart_total, completed_orders_count=0):

    try:
        cart_total=money(cart_total)
    except HTTPException:
        return None

    delivery_fee = 0

    if cart_total < DELIVERY_THRESHOLD:
        delivery_fee = DELIVERY_FEE

    # Keep the flat platform fee consistent with manual quote previews.
    platform_fee = 5

    store_discount = get_store_discount(store, cart_total)
    snapsave_discount = get_snapsave_discount(cart_total)

    # Personal wallet/card benefits require verified eligibility.
    zepto_cash = 0
    hsbc_discount = 0

    # Calculate raw final price
    final_price = cart_total + delivery_fee + platform_fee - store_discount - snapsave_discount - zepto_cash - hsbc_discount
    if final_price<0:
        return None

    return {
        "store": store,
        "cart_total": float(cart_total),
        "delivery_fee": delivery_fee,
        "platform_fee": platform_fee,
        "store_discount": store_discount,
        "snapsave_discount": snapsave_discount,
        "zepto_cash": zepto_cash,
        "hsbc_discount": hsbc_discount,
        "final_price": float(final_price)
    }


# ---------------------------------------------------------
# Compute totals from scraped results
# ---------------------------------------------------------

def compute_store_totals(scraped_results):
    if not scraped_results: return {}
    coverage={}
    totals={}
    for product,offers in scraped_results.items():
        per_store={}
        for offer in offers:
            price=offer.get("price")
            try:
                price=money(price)
            except HTTPException:
                continue
            store=offer["store"]
            per_store[store]=min(price,per_store.get(store,price))
        for store,price in per_store.items():
            totals[store]=totals.get(store,Decimal(0))+price
            coverage[store]=coverage.get(store,0)+1
    return {s:v for s,v in totals.items() if coverage[s]==len(scraped_results)}


# ---------------------------------------------------------
# Main optimizer
# ---------------------------------------------------------

def optimize_cart(scraped_results):

    store_totals = compute_store_totals(scraped_results)

    results = []

    for store, total in store_totals.items():

        price_data = calculate_final_price(store, total)

        if price_data:
            results.append(price_data)

    if not results:
        return None

    best_store = min(results, key=lambda x: x["final_price"])

    return {
        "best_store": best_store,
        "all_store_results": results
    }


def find_best_store(store_totals, completed_orders_count=0):
    results = []
    for store, total in store_totals.items():
        if total is None or total == "not_available":
            continue
        try:
            total_val = float(total)
        except (ValueError, TypeError):
            continue
        price_data = calculate_final_price(store, total_val, completed_orders_count)
        if price_data:
            results.append(price_data)

    if not results:
        return None, []

    best_store = min(results, key=lambda x: x["final_price"])
    return best_store, results
