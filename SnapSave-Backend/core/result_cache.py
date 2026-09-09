import time

CACHE = {}

CACHE_TTL = 300


def get_cache(key):

    if key in CACHE:

        data, timestamp = CACHE[key]

        if time.time() - timestamp < CACHE_TTL:
            return data

    return None


def save_cache(key, data):

    CACHE[key] = (data, time.time())