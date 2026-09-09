from core.store_scrapper_engine import run_scraper


def get_flipkart_price(product, quantity=1, city=None):

    products = run_scraper(
        search_url="https://www.flipkart.com",
        search_selector='input[type="text"]',
        card_selector="div",
        name_selector="a",
        price_selector="text=₹",
        product=product
    )

    if not products:
        return None

    for p in products:
        p["price"] *= quantity

    return products