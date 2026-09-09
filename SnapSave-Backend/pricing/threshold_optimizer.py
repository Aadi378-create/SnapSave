REWARD_THRESHOLDS = {
    "zepto": [
        {"threshold": 599, "reward": 50},
        {"threshold": 1199, "reward": 100},
        {"threshold": 1799, "reward": 150}
    ]
}

SUGGESTED_FILLER_ITEMS = [
    {"name": "biscuits", "price": 40},
    {"name": "chocolate", "price": 50},
    {"name": "chips", "price": 20},
    {"name": "bread", "price": 45}
]


def check_threshold_opportunity(store, cart_total):

    if store not in REWARD_THRESHOLDS:
        return None

    thresholds = REWARD_THRESHOLDS[store]

    for rule in thresholds:

        threshold = rule["threshold"]
        reward = rule["reward"]

        if cart_total < threshold:

            gap = threshold - cart_total

            for item in SUGGESTED_FILLER_ITEMS:

                if item["price"] >= gap:

                    net_gain = reward - item["price"]

                    if net_gain > 0:

                        return {
                            "store": store,
                            "add_item": item["name"],
                            "item_price": item["price"],
                            "unlock_reward": reward,
                            "net_savings": net_gain
                        }

    return None