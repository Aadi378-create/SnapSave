import re


def detect_intent(query):

    q = query.lower()

    intent = {
        "max_price": None,
        "volume": None,
        "keywords": []
    }

    # detect price constraint
    price_match = re.search(r"(under|below|less than)\s*(\d+)", q)
    if price_match:
        intent["max_price"] = int(price_match.group(2))

    # detect volume
    volume_match = re.search(r"(\d+)\s*(ml|l|kg|g)", q)
    if volume_match:
        intent["volume"] = volume_match.group(0)

    # remaining keywords
    words = q.split()

    ignore = ["under", "below", "less", "than"]

    intent["keywords"] = [w for w in words if w not in ignore]

    return intent