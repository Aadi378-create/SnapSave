import json
import os
import time


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "..", "data", "price_history.json")


def load_db():

    if not os.path.exists(DB_PATH):
        return {}

    with open(DB_PATH, encoding="utf8") as f:
        return json.load(f)


def save_db(data):

    with open(DB_PATH, "w", encoding="utf8") as f:
        json.dump(data, f, indent=2)


def record_price(product, store, price):

    db = load_db()

    db.setdefault(product, {})
    db[product].setdefault(store, [])

    db[product][store].append({
        "price": price,
        "timestamp": int(time.time())
    })

    save_db(db)


def average_price(product, store):

    db = load_db()

    if product not in db:
        return None

    if store not in db[product]:
        return None

    prices = [p["price"] for p in db[product][store]]

    if not prices:
        return None

    return sum(prices) / len(prices)