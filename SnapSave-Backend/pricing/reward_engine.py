# SnapSave Reward Engine


STORE_REWARDS = {
    "zepto": [
        {"threshold": 599, "discount": 50},
        {"threshold": 1199, "discount": 100},
        {"threshold": 1799, "discount": 150}
    ]
}


SNAPSAVE_REWARDS = [
    {"threshold": 1000, "discount": 20},
    {"threshold": 1500, "discount": 40},
    {"threshold": 2000, "discount": 70}
]


def get_store_discount(store, cart_total):

    discount = 0

    if store in STORE_REWARDS:
        for rule in STORE_REWARDS[store]:
            if cart_total >= rule["threshold"]:
                discount = rule["discount"]

    return discount


def get_snapsave_discount(cart_total):

    discount = 0

    for rule in SNAPSAVE_REWARDS:
        if cart_total >= rule["threshold"]:
            discount = rule["discount"]

    return discount


def apply_rewards(store_prices):

    results = []

    for store, cart_total in store_prices.items():

        if cart_total == "not_available":
            continue

        store_discount = get_store_discount(store, cart_total)
        snapsave_discount = get_snapsave_discount(cart_total)

        final_price = cart_total - store_discount - snapsave_discount

        results.append({
            "store": store,
            "cart_total": cart_total,
            "store_discount": store_discount,
            "snapsave_discount": snapsave_discount,
            "final_price": final_price
        })

    # If product not available anywhere
    if not results:
        return {
            "best_store": None,
            "all_results": [],
            "message": "Product not available in any store"
        }

    best = min(results, key=lambda x: x["final_price"])

    return {
        "best_store": best,
        "all_results": results
    }


def get_next_reward(store, cart_total):
    if cart_total is None:
        return None
    next_rewards = []
    if store in STORE_REWARDS:
        for rule in STORE_REWARDS[store]:
            if rule["threshold"] > cart_total:
                next_rewards.append({
                    "type": "store",
                    "store": store,
                    "add_more": rule["threshold"] - cart_total,
                    "reward": rule["discount"],
                    "threshold": rule["threshold"]
                })
                break

    for rule in SNAPSAVE_REWARDS:
        if rule["threshold"] > cart_total:
            next_rewards.append({
                "type": "snapsave",
                "add_more": rule["threshold"] - cart_total,
                "reward": rule["discount"],
                "threshold": rule["threshold"]
            })
            break

    if not next_rewards:
        return None

    return min(next_rewards, key=lambda x: x["add_more"])


def generate_reward_message(reward_data):
    if not reward_data:
        return "You're getting the best savings on this order!"
    return f"Add ₹{reward_data['add_more']:.0f} more to unlock ₹{reward_data['reward']} discount!"