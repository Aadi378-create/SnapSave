import requests
from bs4 import BeautifulSoup


def search_bigbasket(product):

    url = f"https://www.bigbasket.com/ps/?q={product}"

    headers = {
        "User-Agent": "Mozilla/5.0"
    }

    r = requests.get(url, headers=headers)

    soup = BeautifulSoup(r.text, "html.parser")

    items = soup.find_all("div", class_="product")

    results = []

    for item in items[:5]:

        name = item.find("a", class_="product-title")

        price = item.find("span", class_="discnt-price")

        if name and price:

            results.append({
                "store": "BigBasket",
                "name": name.text.strip(),
                "price": price.text.strip()
            })

    return results