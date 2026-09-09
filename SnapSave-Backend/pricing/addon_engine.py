def suggest_addon(cart_total, reward_data, cheap_items=None):
    """
    Suggest cheap items to reach next reward threshold.
    Also provide an option to continue without adding anything.
    """

    if not reward_data:
        return {
            "suggestion": None,
            "continue_option": True
        }

    gap = reward_data.get("gap", 0)

    if gap <= 0:
        return {
            "suggestion": None,
            "continue_option": True
        }

    if not cheap_items:
        cheap_items = [
            {"name": "banana", "price": 40},
            {"name": "bread", "price": 45},
            {"name": "biscuit", "price": 30},
            {"name": "maggi", "price": 14}
        ]

    candidates = []

    for item in cheap_items:

        price = item["price"]

        # item should help close the gap reasonably
        if price <= gap * 1.5:
            candidates.append({
                "item": item["name"],
                "price": price
            })

    if not candidates:
        return {
            "suggestion": None,
            "continue_option": True
        }

    best = min(candidates, key=lambda x: x["price"])

    return {
        "suggestion": {
            "item": best["item"],
            "price": best["price"],
            "gap": gap,
            "message": f"Add {best['item']} (₹{best['price']}) to unlock the next reward."
        },
        "continue_option": True
    }