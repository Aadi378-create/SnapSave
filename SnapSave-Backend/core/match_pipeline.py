from core.query_parser import parse_query
from core.normalize_query import normalize_query
from core.product_matcher import match_product
from core.product_ranker import rank_products
from core.intent_parser import detect_intent
from core.product_intent_filter import apply_intent_filters
from core.learning_ranker import apply_learning_rank


def run_match_pipeline(user_query, scraped_products=None):

    # Step 1 — parse quantity / unit / price
    parsed = parse_query(user_query)

    # Step 2 — normalize synonyms
    normalized_query = normalize_query(parsed["query"])

    # Step 3 — match base product category
    match = match_product(normalized_query)

    # Step 4 — detect user intent (price, volume etc)
    intent = detect_intent(normalized_query)

    ranked_products = None

    if scraped_products:

        # Step 5 — similarity ranking
        ranked = rank_products(normalized_query, scraped_products)

        # Step 6 — apply intent filters
        ranked = apply_intent_filters(intent, ranked)

        # Step 7 — apply learning rank (user preference)
        ranked = apply_learning_rank(match["product"], ranked)

        # Step 8 — keep top 4 options
        ranked_products = ranked[:4]

    return {
        "original_query": user_query,
        "normalized_query": normalized_query,
        "matched_product": match["product"],
        "confidence": match["confidence"],
        "match_method": match["method"],
        "quantity": parsed["quantity"],
        "unit": parsed["unit"],
        "price_hint": parsed["price_hint"],
        "intent": intent,
        "product_options": ranked_products
    }