from concurrent.futures import ThreadPoolExecutor, as_completed

from core.match_pipeline import run_match_pipeline
from stores.price_parallel import get_prices_parallel


def process_basket(user_items, city=None):

    basket_results = []

    # Cache to avoid duplicate store queries
    product_price_cache = {}

    futures = {}

    with ThreadPoolExecutor(max_workers=len(user_items)) as executor:

        for item in user_items:

            future = executor.submit(run_match_pipeline, item)
            futures[future] = item

        for future in as_completed(futures):

            item = futures[future]

            try:

                match_data = future.result()

                product = match_data["matched_product"]
                quantity = match_data["quantity"]
                unit = match_data["unit"]
                confidence = match_data["confidence"]

                if product is None:

                    basket_results.append({
                        "query": item,
                        "error": "product_not_found"
                    })

                    continue

                # Default quantity
                if quantity is None:
                    quantity = 1

                cache_key = (product, quantity, city)

                if cache_key in product_price_cache:

                    prices = product_price_cache[cache_key]

                else:

                    prices = get_prices_parallel(product, quantity, city)

                    product_price_cache[cache_key] = prices

                basket_results.append({
                    "query": item,
                    "product": product,
                    "quantity": quantity,
                    "unit": unit,
                    "confidence": confidence,
                    "prices": prices
                })

            except Exception:

                basket_results.append({
                    "query": item,
                    "error": "processing_failed"
                })

    return basket_results