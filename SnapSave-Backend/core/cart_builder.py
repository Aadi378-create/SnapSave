from core.match_pipeline import run_match_pipeline


def build_cart_from_text(user_text):

    # split items by comma or newline
    raw_items = user_text.replace("\n", ",").split(",")

    items = []

    for raw in raw_items:

        raw = raw.strip()

        if not raw:
            continue

        match = run_match_pipeline(raw)

        items.append({
            "original_query": raw,
            "product": match["matched_product"],
            "quantity": match["quantity"] or 1,
            "unit": match["unit"],
            "confidence": match["confidence"]
        })

    return items