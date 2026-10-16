from stores.price_parallel import get_prices_parallel

def get_all_store_prices(product, location=None):
    # Use the same disabled-by-default adapter contract as the main API.
    return [{"store":s,"product":product,"candidates":v if isinstance(v,list) else [],"available":bool(isinstance(v,list) and v)} for s,v in get_prices_parallel(product,1,location).items()]
