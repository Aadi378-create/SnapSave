import json
import os


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PATTERN_PATH = os.path.join(BASE_DIR, "..", "data", "basket_patterns.json")


def load_patterns():

    if not os.path.exists(PATTERN_PATH):
        return {}

    with open(PATTERN_PATH, encoding="utf8") as f:
        return json.load(f)


PATTERNS = load_patterns()


def suggest_items(cart_items):

    suggestions = set()

    for item in cart_items:

        key = item.lower()

        if key in PATTERNS:

            for s in PATTERNS[key]:
                suggestions.add(s)

    # remove items already in cart
    suggestions = [s for s in suggestions if s not in cart_items]

    return suggestions[:4]