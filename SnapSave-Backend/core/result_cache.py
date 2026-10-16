import time
import threading
from collections import OrderedDict
from copy import deepcopy
CACHE=OrderedDict()
CACHE_TTL=300
MAX_ENTRIES=1000
_lock=threading.RLock()

def clean_expired():
    with _lock:
        now=time.monotonic()
        for key in list(CACHE):
            if now-CACHE[key][1]>=CACHE_TTL:CACHE.pop(key,None)

def get_cache(key):
    with _lock:
        entry=CACHE.get(key)
        if not entry:return None
        if time.monotonic()-entry[1]>=CACHE_TTL:
            CACHE.pop(key,None);return None
        CACHE.move_to_end(key)
        return deepcopy(entry[0])

def save_cache(key,data):
    with _lock:
        clean_expired();CACHE[key]=(deepcopy(data),time.monotonic());CACHE.move_to_end(key)
        while len(CACHE)>MAX_ENTRIES:CACHE.popitem(last=False)
