def detect_deal(results, threshold=20):
    """
    Detect whether the cheapest store is significantly cheaper
    than the second cheapest store.
    """

    if not results:
        return None

    # sort stores by final price
    sorted_results = sorted(results, key=lambda x: x["final_price"])

    cheapest = sorted_results[0]

    if len(sorted_results) < 2:
        return None

    second = sorted_results[1]

    price_diff = second["final_price"] - cheapest["final_price"]

    if price_diff >= threshold:

        return {
            "store": cheapest["store"],
            "saving": price_diff,
            "message": f"⚡ {cheapest['store'].title()} is ₹{price_diff} cheaper than other stores."
        }

    return None


def detect_deals(optimized_cart):
    """
    Adapter for pricing_engine.py. Wraps single detect_deal result in a list.
    """
    if not optimized_cart or "all_store_results" not in optimized_cart:
        return []
    deal = detect_deal(optimized_cart["all_store_results"])
    return [deal] if deal else []