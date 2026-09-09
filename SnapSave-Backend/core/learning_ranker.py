from core.user_preference_store import get_preferences


def apply_learning_rank(category, products):

    prefs = get_preferences(category)

    for p in products:
        name = p["name"].lower()
        score = 0
        for brand, weight in prefs.items():
            if brand in name:
                score += weight
        p["brand_weight"] = score

    # Tiered sort: primary match_score (descending), secondary brand_weight (descending)
    ranked = sorted(
        products,
        key=lambda x: (x.get("match_score", 0), x.get("brand_weight", 0)),
        reverse=True
    )

    return ranked