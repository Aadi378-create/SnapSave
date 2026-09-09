from core.categories_parser import detect_category


def filter_products(query, products):

    q_words = query.lower().split()

    category = detect_category(query)

    filtered = []

    for p in products:

        name = p["name"].lower()

        # must contain category
        if category and category not in name:
            continue

        # must contain at least one query word
        if any(w in name for w in q_words):
            filtered.append(p)

    if filtered:
        return filtered[:4]

    return products[:4]