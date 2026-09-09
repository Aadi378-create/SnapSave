import time


# =========================================================
# SnapSave Price Cache System
# =========================================================


# In-memory cache
CACHE = {}


# Cache duration rules (seconds)
CACHE_RULES = {
    "zepto": 600,
    "blinkit": 600,
    "instamart": 600,

    "amazon": 900,
    "flipkart": 900,
    "jiomart": 900,
    "bigbasket": 900
}


# Default cache if store unknown
DEFAULT_CACHE_TIME = 600


# =========================================================
# Generate cache key
# =========================================================

def _make_key(product, store, city):

    product = product.lower().strip()
    store = store.lower().strip()

    if city:
        city = city.lower().strip()

    return (product, store, city)


# =========================================================
# Get cached price
# =========================================================

def get_cached_price(product, store, city=None):

    key = _make_key(product, store, city)

    if key not in CACHE:
        return None

    entry = CACHE[key]

    now = time.time()
    age = now - entry["timestamp"]

    cache_limit = CACHE_RULES.get(store, DEFAULT_CACHE_TIME)

    if age < cache_limit:
        return entry["price"]

    # Cache expired
    del CACHE[key]

    return None


# =========================================================
# Save price to cache
# =========================================================

def save_price(product, store, price, city=None):

    key = _make_key(product, store, city)

    CACHE[key] = {
        "price": price,
        "timestamp": time.time()
    }


# =========================================================
# Clear full cache (admin tool)
# =========================================================

def clear_cache():

    CACHE.clear()


# =========================================================
# Remove expired entries (optional maintenance)
# =========================================================

def clean_expired():

    now = time.time()

    expired_keys = []

    for key, entry in CACHE.items():

        store = key[1]

        cache_limit = CACHE_RULES.get(store, DEFAULT_CACHE_TIME)

        if now - entry["timestamp"] > cache_limit:
            expired_keys.append(key)

    for key in expired_keys:
        del CACHE[key]


# =========================================================
# Debug utility
# =========================================================

def cache_stats():

    stats = {
        "total_entries": len(CACHE),
        "stores": {}
    }

    for key in CACHE:

        store = key[1]

        stats["stores"].setdefault(store, 0)
        stats["stores"][store] += 1

    return stats