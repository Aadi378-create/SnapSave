def price_confidence(source_type):
    
    confidence_map = {
        "api":0.95,
        "scrape":0.75,
        "estimate":0.50
    }

    return confidence_map.get(source_type, 0.6)