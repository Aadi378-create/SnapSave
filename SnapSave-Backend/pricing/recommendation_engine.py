def generate_recommendation(final_results):

    best = final_results["best_store"]
    all_results = final_results["all_results"]

    if not best:
        return {
            "message": "No store has this product"
        }

    best_price = best["final_price"]

    differences = []

    for r in all_results:

        if r["store"] == best["store"]:
            continue

        diff = r["final_price"] - best_price

        differences.append({
            "store": r["store"],
            "difference": diff
        })

    differences.sort(key=lambda x: x["difference"])

    reasons = []

    for d in differences[:2]:

        reasons.append(
            f"₹{d['difference']} cheaper than {d['store']}"
        )

    return {
        "recommended_store": best["store"],
        "final_price": best_price,
        "reasons": reasons
    }


def recommend_products(cart_with_vouchers):
    """
    Adapter for pricing_engine.py. Generates store recommendations.
    """
    if not cart_with_vouchers:
        return []
    rec = generate_recommendation({
        "best_store": cart_with_vouchers.get("best_store"),
        "all_results": cart_with_vouchers.get("all_store_results", [])
    })
    return [rec] if rec else []