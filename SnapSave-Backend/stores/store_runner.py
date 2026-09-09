from playwright.sync_api import sync_playwright


def run_store_session(products, search_fn):

    results = {}

    with sync_playwright() as p:

        browser = p.chromium.launch(headless=False)

        context = browser.new_context()

        page = context.new_page()

        for product in products:

            try:
                price = search_fn(page, product)
                results[product] = price
            except:
                results[product] = None

        browser.close()

    return results