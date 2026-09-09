def calculate_voucher_discount(cart_total, voucher_cost):

    if voucher_cost >= cart_total:
        return {
            "user_discount": 0,
            "profit": 0,
            "final_price": cart_total
        }

    margin = cart_total - voucher_cost

    # Split margin between user and SnapSave
    user_discount = margin * 0.6
    profit = margin * 0.4

    final_price = cart_total - user_discount

    return {
        "user_discount": round(user_discount, 2),
        "profit": round(profit, 2),
        "final_price": round(final_price, 2)
    }


def apply_vouchers(optimized_cart):
    """
    Adapter for pricing_engine.py. Applies voucher discount calculations to each store result.
    """
    if not optimized_cart:
        return None
    for res in optimized_cart.get("all_store_results", []):
        # Default voucher_cost to final_price (no partner voucher discount) to prevent a free 60% discount bug
        discount_info = calculate_voucher_discount(res["final_price"], res["final_price"])
        res["voucher_discount"] = discount_info["user_discount"]
        res["final_price"] = discount_info["final_price"]
    if optimized_cart.get("all_store_results"):
        optimized_cart["best_store"] = min(optimized_cart["all_store_results"], key=lambda x: x["final_price"])
    return optimized_cart