from playwright.sync_api import sync_playwright


def get_instamart_price(product, quantity=1):

    try:

        query = product.replace(" ", "%20")
        url = f"https://www.swiggy.com/instamart/search?query={query}"

        with sync_playwright() as p:

            browser = p.chromium.launch(headless=True)

            page = browser.new_page()

            page.goto(url)

            # allow JS to load products
            page.wait_for_timeout(4000)

            items = page.query_selector_all("div")

            for item in items:

                text = item.inner_text().lower()

                if product.lower() in text and "₹" in text:

                    parts = text.split("₹")

                    if len(parts) > 1:

                        price = parts[1].split()[0]

                        price = price.replace(",", "")

                        browser.close()

                        return [{"name": product, "price": int(price) * quantity}]

            browser.close()

        return None

    except Exception:
        return None