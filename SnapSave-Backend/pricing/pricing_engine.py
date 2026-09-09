from pricing.cart_optimizer import optimize_cart
from pricing.deal_detector import detect_deals
from pricing.voucher_engine import apply_vouchers
from pricing.savings_summary import calculate_savings
from pricing.recommendation_engine import recommend_products
from pricing.store_availability import check_store_availability


def run_pricing_engine(scraped_results, location):

    # -------------------------------
    # 1 Check which stores are available
    # -------------------------------

    available_stores = check_store_availability(location)

    # -------------------------------
    # 2 Filter products by store availability
    # -------------------------------

    filtered_results = {}

    for item, products in scraped_results.items():

        valid_products = [
            p for p in products if p["store"] in available_stores
        ]

        if valid_products:
            filtered_results[item] = valid_products

    # If nothing is available
    if not filtered_results:
        return {
            "cart": {},
            "savings": 0,
            "deals": [],
            "recommendations": [],
            "message": "No products available for this location"
        }

    # -------------------------------
    # 3 Optimize cart
    # -------------------------------

    optimized_cart = optimize_cart(filtered_results)

    # -------------------------------
    # 4 Detect deals
    # -------------------------------

    deals = detect_deals(optimized_cart)

    # -------------------------------
    # 5 Apply vouchers / coupons
    # -------------------------------

    cart_with_vouchers = apply_vouchers(optimized_cart)

    # -------------------------------
    # 6 Calculate savings
    # -------------------------------

    savings = calculate_savings(cart_with_vouchers)

    # -------------------------------
    # 7 Generate recommendations
    # -------------------------------

    recommendations = recommend_products(cart_with_vouchers)

    # -------------------------------
    # Final response
    # -------------------------------

    return {
        "cart": cart_with_vouchers,
        "savings": savings,
        "deals": deals,
        "recommendations": recommendations
    }