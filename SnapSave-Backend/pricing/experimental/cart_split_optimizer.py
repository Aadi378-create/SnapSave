def find_cheapest_per_item(price_map):

    split_cart = {}
    total_price = 0

    for product, store_prices in price_map.items():

        cheapest_store = None
        cheapest_price = None

        for store, price in store_prices.items():

            if price is None:
                continue

            if cheapest_price is None or price < cheapest_price:
                cheapest_price = price
                cheapest_store = store

        if cheapest_store:
            split_cart[product] = {
                "store": cheapest_store,
                "price": cheapest_price
            }

            total_price += cheapest_price

    return split_cart, total_price


def find_single_store_best(price_map):

    store_totals = {}

    for product, store_prices in price_map.items():

        for store, price in store_prices.items():

            if price is None:
                continue

            store_totals.setdefault(store, 0)
            store_totals[store] += price

    best_store = min(store_totals, key=store_totals.get)

    return best_store, store_totals[best_store]


def choose_best_cart(price_map):

    split_cart, split_total = find_cheapest_per_item(price_map)

    best_store, single_total = find_single_store_best(price_map)

    if split_total < single_total:

        return {
            "type": "split_cart",
            "total": split_total,
            "cart": split_cart
        }

    return {
        "type": "single_store",
        "store": best_store,
        "total": single_total
    }