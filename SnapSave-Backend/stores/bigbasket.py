from core.store_scrapper_engine import run_scraper


def get_bigbasket_price(product, quantity=1, city=None):

    products = run_scraper(
        search_url=f"https://www.bigbasket.com/ps/?q={product}",
        search_selector='input[type="search"]',
        card_selector="div",
        name_selector="h3",
        price_selector="text=₹",
        product=product
    )

    if not products:
        return None

    for p in products:
        p["price"] *= quantity

    return products