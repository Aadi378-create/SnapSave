from core.basket_engine import process_basket
from pricing.cart_optimizer import find_best_store
from pricing.reward_engine import get_next_reward, generate_reward_message
import math


def build_store_totals(basket_results):
    """
    Convert basket item prices into per-store totals.
    """
    store_totals = {}
    coverage={}

    for item in basket_results:
        prices = item.get("prices", {})

        for store, price in prices.items():
            if price is None or price == "not_available":
                continue

            if isinstance(price,list):
                from pricing.pivot_layer import resolve_best_candidate
                offer=resolve_best_candidate(item.get("query",item.get("product","")),store,price)
                price=offer["price"] if offer else None
            try:
                numeric_price = float(price)
            except (ValueError, TypeError):
                continue
            if not math.isfinite(numeric_price) or numeric_price<0:
                continue

            store_totals.setdefault(store, 0.0)
            store_totals[store] += numeric_price
            coverage[store]=coverage.get(store,0)+1

    return {s:v for s,v in store_totals.items() if coverage[s]==len(basket_results)}


def run_full_analysis(user_items):
    """
    Main SnapSave engine:
    1. Process basket
    2. Compute store totals
    3. Run cart optimizer
    4. Generate reward suggestion
    """

    # Step 1: process all basket items
    basket = process_basket(user_items)

    # Step 2: compute totals per store
    store_totals = build_store_totals(basket)

    # Step 3: find best store
    best_store, all_results = find_best_store(store_totals)

    # Step 4: reward suggestion
    if best_store:
        reward_data = get_next_reward(best_store["store"], best_store["cart_total"])
        reward_message = generate_reward_message(reward_data)
    else:
        reward_message = "No store prices available for this basket."

    return {
        "basket": basket,
        "store_totals": store_totals,
        "best_option": best_store,
        "reward_tip": reward_message
    }
