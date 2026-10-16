from pathlib import Path
import re

def load_categories():

    categories = []

    with open(Path(__file__).resolve().parents[1]/"data/categories.txt", "r", encoding="utf-8") as f:
        for line in f:
            c = line.strip().lower()
            if c:
                categories.append(c)

    return categories


CATEGORIES = load_categories()


def detect_category(query):

    q = query.lower()

    for category in CATEGORIES:
        if re.search(r"\b"+re.escape(category)+r"\b",q):
            return category

    return None
