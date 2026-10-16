import re
from core.categories_parser import detect_category
from pricing.quotes import money
from fastapi import HTTPException

def score_product(query, product_name):

    ignored={"x","l","ltr","litre","liter","litres","liters","kg","g","gm","ml","of","and","a","the","under","below","less","than","rs","rupees","packet","packets","pack","packs","pcs","pieces"}
    q_words = set(re.findall(r"\b[a-z]+\b",query.lower()))-ignored
    p_words = set(re.findall(r"\b[a-z]+\b",product_name.lower()))-ignored
    category=detect_category(query)
    if category and category not in product_name.lower():
        return 0

    # count matching words
    matches = q_words.intersection(p_words)

    return len(matches) if q_words and matches==q_words else 0

def rank_products(query, products):

    scored = []

    for p in products:
        if not isinstance(p,dict) or not isinstance(p.get("name"),str):
            continue
        p=dict(p)
        try:
            p["price"]=float(money(p.get("price")))
        except HTTPException:
            continue

        score = score_product(query, p["name"])
        p["match_score"] = score

        scored.append((score, p))

    # sort by highest score
    scored.sort(reverse=True, key=lambda x: x[0])

    ranked_products = [p for score, p in scored if score > 0]

    if ranked_products:
        return ranked_products[:4]

    # fallback
    return []
