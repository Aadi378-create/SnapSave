import re

def parse_query(query):

    query = query.lower()

    multiplier = None
    volume = None
    unit = None
    price = None

    # ---------- price detection ----------
    price_match = re.search(r"(\d+)\s?rs", query)
    if price_match:
        price = int(price_match.group(1))

    # ---------- multiplier detection (e.g. 2x, 2 *, 3 pcs, 2 packet) ----------
    mult_match = re.search(r"(\d+)\s*(?:x|\*|pcs|pieces|packet|pack|pkt|bottle|can|box)\b", query)
    if mult_match:
        multiplier = int(mult_match.group(1))

    # Also check if it starts with a number like "2 milk" (but not "2l milk")
    start_match = re.match(r"^(\d+)\s+([a-zA-Z]+)", query)
    if start_match and multiplier is None:
        # ensure the text after isn't a known volume unit
        if start_match.group(2) not in ["kg", "g", "gm", "ml", "l"]:
            multiplier = int(start_match.group(1))

    # ---------- volume + unit together (1kg, 500ml, 2l etc) ----------
    combo_match = re.search(r"(\d+)\s?(kg|g|gm|ml|l)\b", query)
    if combo_match:
        volume = int(combo_match.group(1))
        unit = combo_match.group(2)

    return {
        "query": query,
        "quantity": multiplier,
        "volume": volume,
        "unit": unit,
        "price_hint": price
    }