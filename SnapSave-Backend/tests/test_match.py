import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rapidfuzz import process
from core.product_matcher import VOCAB

queries = [
    "amul milk",
    "ashirwad atta",
    "kurkure",
    "lays chips",
    "tamato ketchup"
]

if __name__ == "__main__":
    for q in queries:
        result = process.extractOne(q, VOCAB)

        if result:
            product, score, _ = result
            print(q, "->", product, "| confidence:", round(score))