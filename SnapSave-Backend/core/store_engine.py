from concurrent.futures import ThreadPoolExecutor, as_completed

from stores.zepto import search_product as zepto_search
from stores.blinkit import search_product as blinkit_search
from stores.instamart import search_product as instamart_search
from stores.amazon import search_product as amazon_search
from stores.flipkart import search_product as flipkart_search
from stores.jiomart import search_product as jiomart_search
from stores.bigbasket import search_product as bigbasket_search


STORE_FUNCTIONS = [
    zepto_search,
    blinkit_search,
    instamart_search,
    amazon_search,
    flipkart_search,
    jiomart_search,
    bigbasket_search
]


def get_all_store_prices(product, location=None):

    results = []

    with ThreadPoolExecutor(max_workers=len(STORE_FUNCTIONS)) as executor:

        futures = [
            executor.submit(store_func, product, location)
            for store_func in STORE_FUNCTIONS
        ]

        for future in as_completed(futures):
            try:
                results.append(future.result())
            except Exception as e:
                results.append({
                    "product": product,
                    "store": "unknown",
                    "price": None,
                    "available": False,
                    "error": str(e)
                })

    return results