import requests
from bs4 import BeautifulSoup


def get_amazon_price(product, quantity=1):

    try:
        query = product.replace(" ", "+")
        url = f"https://www.amazon.in/s?k={query}"

        headers = {
            "User-Agent": "Mozilla/5.0",
            "Accept-Language": "en-IN,en;q=0.9"
        }

        r = requests.get(url, headers=headers, timeout=6)

        soup = BeautifulSoup(r.text, "html.parser")

        results = soup.select("div.s-result-item")

        for item in results:

            title_tag = item.select_one("h2")
            price_tag = item.select_one(".a-price-whole")

            if not title_tag or not price_tag:
                continue

            title = title_tag.get_text().lower()

            # only accept results that actually match the product
            if product.lower() in title:

                price = (
                    price_tag.get_text()
                    .replace(",", "")
                    .strip()
                )

                return [{"name": title, "price": int(price) * quantity}]

        return None

    except Exception:
        return None