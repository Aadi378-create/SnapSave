from itertools import product
from decimal import Decimal
from pricing.quotes import money
from fastapi import HTTPException

def valid_offers(prices):
    if not isinstance(prices,dict):
        return {}
    result={}
    for store,value in prices.items():
        if not isinstance(store,str) or not store.strip() or isinstance(value,bool):
            continue
        try:
            result[store]=money(value)
        except HTTPException:
            continue
    return result

def choose_best_cart(price_map, delivery_thresholds=None, delivery_fees=None):
    if not price_map: return {"type":"unavailable","message":"Basket is empty"}
    thresholds=delivery_thresholds or {}
    fees=delivery_fees or {}
    keys=list(price_map)
    if len(keys)>12: return {"type":"unavailable","message":"Split optimization requires human review for large baskets"}
    choices=[]
    for item in keys:
        offers=list(valid_offers(price_map[item]).items())
        if not offers: return {"type":"unavailable","message":"A requested item is unavailable"}
        choices.append(offers)
    combinations=1
    for choice in choices: combinations*=len(choice)
    if combinations>50000: return {"type":"unavailable","message":"Split optimization requires human review"}
    best=None
    for allocation in product(*choices):
        buckets={}
        cart={}
        for item,(store,price) in zip(keys,allocation):
            buckets[store]=buckets.get(store,Decimal(0))+price
            cart[item]={"store":store,"price":float(price)}
        shipping=sum((money(fees.get(s,35)) if value<money(thresholds.get(s,199)) else Decimal(0) for s,value in buckets.items()),Decimal(0))
        total=sum(buckets.values(),Decimal(0))+shipping
        if best is None or total<best[0]: best=(total,shipping,cart,buckets)
    total,shipping,cart,buckets=best
    return {"type":"single_store" if len(buckets)==1 else "split_cart","store":next(iter(buckets)) if len(buckets)==1 else None,"total":float(total),"delivery_fee":float(shipping),"cart":cart}

def find_cheapest_per_item(price_map):
    cart={}
    total=Decimal(0)
    for item,prices in price_map.items():
        offers=valid_offers(prices)
        if not offers:
            return {},0
        store=min(offers,key=offers.get)
        cart[item]={"store":store,"price":float(offers[store])}
        total+=offers[store]
    return cart,float(total)

def find_single_store_best(price_map):
    if not price_map: return None,None
    offers=[valid_offers(prices) for prices in price_map.values()]
    stores=set.intersection(*(set(prices) for prices in offers))
    if not stores: return None,None
    totals={s:sum((prices[s] for prices in offers),Decimal(0)) for s in stores}
    store=min(totals,key=totals.get)
    return store,float(totals[store])
