def build_order_summary(best_store):

    if not best_store:
        return None

    cart_total = best_store["cart_total"]
    delivery = best_store["delivery_fee"]
    store_discount = best_store["store_discount"]
    snapsave_discount = best_store["snapsave_discount"]
    final_price = best_store["final_price"]

    summary = {
        "store": best_store["store"],
        "cart_total": cart_total,
        "delivery_fee": delivery,
        "store_discount": store_discount,
        "snapsave_discount": snapsave_discount,
        "final_price": final_price,
        "message": (
            f"Order will be placed on {best_store['store'].title()}.\n"
            f"Cart Total: ₹{cart_total}\n"
            f"Delivery: ₹{delivery}\n"
            f"Store Discount: ₹{store_discount}\n"
            f"SnapSave Discount: ₹{snapsave_discount}\n"
            f"Final Price: ₹{final_price}"
        )
    }

    return summary