def score_product(query, product_name):

    q_words = set(query.lower().split())
    p_words = set(product_name.lower().split())

    # count matching words
    matches = q_words.intersection(p_words)

    return len(matches)

def rank_products(query, products):

    scored = []

    for p in products:

        score = score_product(query, p["name"])
        p["match_score"] = score

        scored.append((score, p))

    # sort by highest score
    scored.sort(reverse=True, key=lambda x: x[0])

    ranked_products = [p for score, p in scored if score > 0]

    if ranked_products:
        return ranked_products[:4]

    # fallback
    return products[:4]