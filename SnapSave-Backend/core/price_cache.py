import time
import threading
from collections import OrderedDict
from copy import deepcopy
CACHE=OrderedDict()
CACHE_RULES={"zepto":600,"blinkit":600,"instamart":600,"amazon":900,"flipkart":900,"jiomart":900,"bigbasket":900}
DEFAULT_CACHE_TIME=600
MAX_ENTRIES=1000
_lock=threading.RLock()

def _make_key(product,store,city,quantity=1):
    return (product.lower().strip(),store.lower().strip(),(city or "").lower().strip(),quantity)

def get_cached_price(product,store,city=None,quantity=1):
    with _lock:
        key=_make_key(product,store,city,quantity);entry=CACHE.get(key)
        if not entry:return None
        if time.monotonic()-entry["timestamp"]>=CACHE_RULES.get(key[1],DEFAULT_CACHE_TIME):
            CACHE.pop(key,None);return None
        CACHE.move_to_end(key);return deepcopy(entry["price"])

def save_price(product,store,price,city=None,quantity=1):
    with _lock:
        key=_make_key(product,store,city,quantity)
        CACHE[key]={"price":deepcopy(price),"timestamp":time.monotonic()};CACHE.move_to_end(key)
        clean_expired()
        while len(CACHE)>MAX_ENTRIES:CACHE.popitem(last=False)

def clean_expired():
    with _lock:
        now=time.monotonic()
        for key in list(CACHE):
            if now-CACHE[key]["timestamp"]>=CACHE_RULES.get(key[1],DEFAULT_CACHE_TIME):CACHE.pop(key,None)

def clear_cache():
    with _lock:CACHE.clear()

def cache_stats():
    with _lock:
        clean_expired();stores={}
        for key in CACHE:stores[key[1]]=stores.get(key[1],0)+1
        return {"total_entries":len(CACHE),"stores":stores}
