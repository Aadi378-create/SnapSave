def build_savings_summary(best_store, all_results):

    if not best_store or not all_results:
        return None

    cheapest_price = best_store["final_price"]

    # find next cheapest store
    others = [r for r in all_results if r["store"] != best_store["store"]]

    if not others:
        return None

    second_best = min(others, key=lambda x: x["final_price"])

    store_saving = second_best["final_price"] - cheapest_price

    snapsave_discount = best_store.get("snapsave_discount", 0)
    store_discount = best_store.get("store_discount", 0)

    total_saving = store_saving + snapsave_discount + store_discount

    return {
        "total_saving": total_saving,
        "store_saving": store_saving,
        "snapsave_discount": snapsave_discount,
        "store_discount": store_discount,
        "message": (
            f"You saved ₹{total_saving} with SnapSave "
            f"(₹{store_saving} better store price, "
            f"₹{snapsave_discount} SnapSave discount, "
            f"₹{store_discount} store reward)."
        )
    }


def calculate_savings(cart_with_vouchers):
    """
    Adapter for pricing_engine.py. Resolves total savings using build_savings_summary.
    """
    if not cart_with_vouchers or "best_store" not in cart_with_vouchers:
        return 0
    summary = build_savings_summary(
        cart_with_vouchers["best_store"], 
        cart_with_vouchers["all_store_results"]
    )
    return summary["total_saving"] if summary else 0