import json
import os

# ======================================================
# Store prediction engine for SnapSave
# ======================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.path.join(BASE_DIR, "store_model.json")


# Default model if file doesn't exist
DEFAULT_MODEL = {
    "milk": ["blinkit", "zepto", "instamart"],
    "bread": ["zepto", "blinkit", "instamart"],
    "maggi": ["zepto", "instamart", "blinkit"],
    "rice": ["bigbasket", "zepto", "blinkit"]
}


# ======================================================
# Load model safely
# ======================================================

def load_model():

    if not os.path.exists(MODEL_PATH):
        return DEFAULT_MODEL.copy()

    try:
        with open(MODEL_PATH, "r", encoding="utf8") as f:
            return json.load(f)
    except Exception:
        # if model file corrupt
        return DEFAULT_MODEL.copy()


MODEL = load_model()


# ======================================================
# Predict store order
# ======================================================

def predict_store_order(product):

    product = product.lower()

    # match using product words
    words = product.split()

    for key in MODEL:
        if key in words or key in product:
            return MODEL[key]

    # fallback order if product unknown
    return [
        "zepto",
        "blinkit",
        "instamart",
        "bigbasket",
        "jiomart",
        "amazon",
        "flipkart"
    ]


# ======================================================
# Update model from observed prices
# ======================================================

def update_model(product, price_map):

    product = product.lower()

    # normalize product key
    words = product.split()
    product_key = words[-1] if words else product

    # sort stores by cheapest price
    ranking = sorted(
        [s for s in price_map if price_map[s] not in (None, "not_available")],
        key=lambda s: price_map[s]
    )

    if not ranking:
        return

    MODEL[product_key] = ranking

    try:
        with open(MODEL_PATH, "w", encoding="utf8") as f:
            json.dump(MODEL, f, indent=2)
    except Exception:
        pass


# ======================================================
# Utility: learn from basket results
# ======================================================

def learn_from_prices(product, price_map):

    try:
        update_model(product, price_map)
    except Exception:
        pass