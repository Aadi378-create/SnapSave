import os
import re
from rapidfuzz import process, fuzz


# ---------- Load vocabulary ----------

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
VOCAB_PATH = os.path.join(BASE_DIR, "final_products.txt")


def load_vocab():
    with open(VOCAB_PATH, encoding="utf8") as f:
        return [line.strip().lower() for line in f if line.strip()]


VOCAB = load_vocab()


# ---------- Query cleaner ----------

def clean_query(text):

    text = text.lower()

    # remove quantities
    text = re.sub(r"\b\d+\s?(kg|g|gm|ml|l|packet|pack|pkt)\b", "", text)

    # remove price hints
    text = re.sub(r"\b\d+\s?rs\b", "", text)

    # remove standalone numbers
    text = re.sub(r"\b\d+\b", "", text)

    return text.strip()


# ---------- Product matcher ----------

def match_product(query):

    query = clean_query(query)

    # words we should avoid when possible
    BAD_WORDS = [
        "chocolate",
        "strawberry",
        "mango",
        "vanilla",
        "flavour",
        "shake",
        "drink",
        "bites"
    ]

    candidates = []

    for product in VOCAB:

        if query in product:

            # avoid flavour variants unless user typed them
            if any(bad in product for bad in BAD_WORDS) and not any(bad in query for bad in BAD_WORDS):
                continue

            candidates.append(product)

    # ---------- Exact substring match ----------

    if candidates:

        best = min(candidates, key=len)

        return {
            "product": best,
            "confidence": 0.95,
            "method": "substring"
        }

    # ---------- Fuzzy fallback ----------

    result = process.extractOne(query, VOCAB, scorer=fuzz.token_set_ratio)

    if result:

        match, score, _ = result

        confidence = score / 100

        return {
            "product": match,
            "confidence": confidence,
            "method": "fuzzy"
        }

    # ---------- No match ----------

    return {
        "product": None,
        "confidence": 0,
        "method": "none"
    }