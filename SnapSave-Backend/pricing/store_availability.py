# Feature flags to control active stores for comparison and recommendation
STORE_FEATURE_FLAGS = {
    "zepto": True,
    "blinkit": True,
    "instamart": True,
    "bigbasket": True,
    "jiomart": True,
    "amazon": False,    # Disabled behind feature flag
    "flipkart": False   # Disabled behind feature flag
}


def calculate_store_availability(basket_results):

    availability = {}

    total_items = len(basket_results)

    for item in basket_results:

        prices = item.get("prices", {})

        for store, price in prices.items():

            availability.setdefault(store, 0)

            if price not in (None, "not_available"):
                availability[store] += 1

    result = {}

    for store, count in availability.items():

        result[store] = {
            "available_items": count,
            "total_items": total_items,
            "ratio": f"{count}/{total_items}"
        }

    return result


def check_store_availability(location):
    """
    Returns list of stores available for a given location.
    Filters out stores that are disabled behind feature flags.
    """
    all_stores = ["zepto", "blinkit", "instamart", "bigbasket", "amazon", "flipkart", "jiomart"]
    return [store for store in all_stores if STORE_FEATURE_FLAGS.get(store, True)]