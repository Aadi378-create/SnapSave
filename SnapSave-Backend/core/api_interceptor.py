def extract_products_from_json(data):

    products = []

    if "products" not in data:
        return products

    for item in data["products"]:

        try:
            name = item["name"]
            price = item["price"]

            products.append({
                "name": name,
                "price": price
            })

        except:
            continue

    return products