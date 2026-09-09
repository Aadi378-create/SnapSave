from concurrent.futures import ThreadPoolExecutor, as_completed

from stores.zepto import get_zepto_price
from stores.bigbasket import get_bigbasket_price
from stores.blinkit import get_blinkit_price
from stores.instamart import get_instamart_price
from stores.jiomart import get_jiomart_price
from stores.amazon import get_amazon_price
from stores.flipkart import get_flipkart_price


STORE_FUNCTIONS = {
    "zepto": get_zepto_price,
    "bigbasket": get_bigbasket_price,
    "blinkit": get_blinkit_price,
    "instamart": get_instamart_price,
    "jiomart": get_jiomart_price,
    "amazon": get_amazon_price,
    "flipkart": get_flipkart_price
}


def get_prices_parallel(product, quantity=1, city=None):
    # Deactivated for Human Concierge MVP phase to prevent any automatic Playwright/scraper execution.
    # Return "not_available" for all configured stores.
    return {store: "not_available" for store in STORE_FUNCTIONS.keys()}