import re

def parse_query(query):
    q=query.lower().strip()
    number=r"(?:\d+(?:\.\d+)?)"
    price_match=re.search(r"(\d+(?:\.\d+)?)\s*(?:rs|rupees|₹)",q)
    mult=re.match(r"^(\d+)\s*(?:x\b|\*|×|pcs\b|pieces?\b|packets?\b|packs?\b|pkts?\b|bottles?\b|cans?\b|boxes?\b)",q)
    if not mult:
        mult=re.match(r"^(\d+)\s+(?!(?:kg|g|gm|ml|l|ltr|litres?|liters?)\b)[a-z]",q)
    volume_match=re.search(r"("+number+r")\s*(kg|gm|g|ml|litres?|liters?|ltr|l)\b",q)
    unit=volume_match.group(2) if volume_match else None
    if unit in {"litre","litres","liter","liters","ltr"}: unit="l"
    if unit=="gm": unit="g"
    return {"query":q,"quantity":int(mult.group(1)) if mult else None,"volume":float(volume_match.group(1)) if volume_match else None,"unit":unit,"price_hint":float(price_match.group(1)) if price_match else None}
