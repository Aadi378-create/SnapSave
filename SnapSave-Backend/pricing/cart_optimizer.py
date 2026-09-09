# =========================================================
# SnapSave Cart Optimizer (Single Store Model)
# =========================================================

DELIVERY_THRESHOLD = 199
DELIVERY_FEE = 35


# ---------------------------------------------------------
# Store reward ladders
# ---------------------------------------------------------

STORE_REWARDS = {
    "zepto": [
        {"threshold": 599, "discount": 50},
        {"threshold": 1199, "discount": 100},
        {"threshold": 1799, "discount": 150}
    ]
}


# ---------------------------------------------------------
# SnapSave discount ladder
# ---------------------------------------------------------

SNAPSAVE_DISCOUNT = [
    {"threshold": 1000, "discount": 20},
    {"threshold": 1500, "discount": 40},
    {"threshold": 2000, "discount": 70}
]


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

    if cart_total is None:
        return None

    delivery_fee = 0

    if cart_total < DELIVERY_THRESHOLD:
        delivery_fee = DELIVERY_FEE

    # 1. Platform Fee: first 10 orders free, Rs. 5 after
    platform_fee = 5 if completed_orders_count >= 10 else 0

    store_discount = get_store_discount(store, cart_total)
    snapsave_discount = get_snapsave_discount(cart_total)

    # 2. Zepto Cash discount logic (5% of cart total, capped at Rs. 50 if store is zepto)
    zepto_cash = 0
    if store == "zepto":
        zepto_cash = min(cart_total * 0.05, 50.0)

    # 3. HSBC discount logic: Rs. 100 discount for orders >= Rs. 1000
    hsbc_discount = 100 if cart_total >= 1000 else 0

    # Calculate raw final price
    final_price = cart_total + delivery_fee + platform_fee - store_discount - snapsave_discount - zepto_cash - hsbc_discount

    # 4. No negative profit scenario: final customer price cannot be less than expected store cost
    expected_store_cost = cart_total - store_discount
    if final_price < expected_store_cost:
        final_price = expected_store_cost

    final_price = max(final_price, 0)

    return {
        "store": store,
        "cart_total": cart_total,
        "delivery_fee": delivery_fee,
        "platform_fee": platform_fee,
        "store_discount": store_discount,
        "snapsave_discount": snapsave_discount,
        "zepto_cash": zepto_cash,
        "hsbc_discount": hsbc_discount,
        "final_price": final_price
    }


# ---------------------------------------------------------
# Compute totals from scraped results
# ---------------------------------------------------------

def compute_store_totals(scraped_results):

    store_totals = {}

    for product, offers in scraped_results.items():

        for offer in offers:

            store = offer["store"]
            price = offer["price"]

            store_totals.setdefault(store, 0)
            store_totals[store] += price

    return store_totals


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