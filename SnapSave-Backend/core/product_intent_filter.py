def apply_intent_filters(intent, products):

    filtered = products

    # filter by price
    if intent["max_price"]:

        filtered = [
            p for p in filtered
            if p["price"] <= intent["max_price"]
        ]

    # filter by volume
    if intent["volume"]:

        vol = intent["volume"]

        filtered = [
            p for p in filtered
            if vol in p["name"].lower()
        ]

    return filtered