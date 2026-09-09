import requests
from bs4 import BeautifulSoup


def scrape_store(product, quantity, url, title_selector, price_selector):

    try:

        headers = {
            "User-Agent": "Mozilla/5.0",
            "Accept-Language": "en-IN,en;q=0.9"
        }

        r = requests.get(url, headers=headers, timeout=6)

        soup = BeautifulSoup(r.text, "html.parser")

        items = soup.select(title_selector)

        prices = soup.select(price_selector)

        for title, price in zip(items, prices):

            title_text = title.get_text().lower()

            if product.lower() in title_text:

                value = (
                    price.get_text()
                    .replace("₹", "")
                    .replace(",", "")
                    .strip()
                )

                return int(value) * quantity

        return None

    except Exception:
        return None