from core.query_parser import parse_query

def apply_intent_filters(intent, products):
    result=products
    if intent.get("max_price") is not None:
        result=[p for p in result if p["price"]<=intent["max_price"]]
    if intent.get("volume"):
        desired=parse_query(intent["volume"])
        def same(p):
            actual=parse_query(p["name"])
            if actual["volume"] is None: return False
            def canonical(value,unit):
                return (value*1000,"g") if unit=="kg" else (value*1000,"ml") if unit=="l" else (value,unit)
            return canonical(actual["volume"],actual["unit"])==canonical(desired["volume"],desired["unit"])
        result=[p for p in result if same(p)]
    return result
