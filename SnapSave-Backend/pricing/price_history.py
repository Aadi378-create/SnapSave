from pathlib import Path
import threading
import time
from core.json_store import read_json,write_json
from pricing.quotes import money

DB_PATH=Path(__file__).resolve().parents[1]/"data/price_history.json"
MAX_OBSERVATIONS=1000
_lock=threading.RLock()

def load_db():
    with _lock:
        return read_json(DB_PATH)

def save_db(data):
    with _lock:
        write_json(DB_PATH,data)

def record_price(product,store,price):
    amount=float(money(price))
    with _lock:
        data=load_db()
        observations=data.setdefault(product,{}).setdefault(store,[])
        observations.append({"price":amount,"timestamp":int(time.time())})
        del observations[:-MAX_OBSERVATIONS]
        save_db(data)

def average_price(product,store):
    observations=load_db().get(product,{}).get(store,[])
    return sum(p["price"] for p in observations)/len(observations) if observations else None
