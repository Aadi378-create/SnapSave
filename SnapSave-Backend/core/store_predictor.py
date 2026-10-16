import json
import os
import threading
from copy import deepcopy
from core.json_store import write_json

_lock=threading.RLock()

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
        return deepcopy(DEFAULT_MODEL)

    try:
        with open(MODEL_PATH, "r", encoding="utf8") as f:
            return json.load(f)
    except Exception:
        # if model file corrupt
        return deepcopy(DEFAULT_MODEL)


MODEL = load_model()


# ======================================================
# Predict store order
# ======================================================

def predict_store_order(product):

    product = product.lower()

    # match using product words
    words = product.split()

    with _lock:
        for key in MODEL:
            if key in words:
                return list(MODEL[key])

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

    with _lock:
        updated=deepcopy(MODEL)
        updated[product_key]=ranking
        write_json(MODEL_PATH,updated)
        MODEL.clear()
        MODEL.update(updated)


# ======================================================
# Utility: learn from basket results
# ======================================================

def learn_from_prices(product, price_map):

    try:
        update_model(product, price_map)
    except Exception:
        pass
