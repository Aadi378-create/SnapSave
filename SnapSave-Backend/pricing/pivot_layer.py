from typing import List, Dict, Any, Optional
from core.match_pipeline import run_match_pipeline

def resolve_best_candidate(query: str, store: str, candidates: list) -> Optional[dict]:
    """
    Takes raw candidates list from a store and resolves it using the match pipeline.
    Attaches confidence and match_score to the structured candidate object.
    """
    if not candidates or not isinstance(candidates, list):
        return None
    
    # Run candidates through match pipeline
    result = run_match_pipeline(query, scraped_products=candidates)
    options = result.get("product_options")
    
    if not options:
        return None
    
    best = options[0]
    
    # Return structured candidate object
    return {
        "selected_product": best.get("name", ""),
        "price": best.get("price", 0),
        "store": store,
        "confidence": result.get("confidence", 0.90),
        "match_score": best.get("match_score", 0)
    }

def convert_to_legacy_prices(store_raw_results: Dict[str, Any], query: str) -> Dict[str, Any]:
    """
    Converts structured candidate results to legacy {store: price_int} structure
    for backwards-compatibility with /deal and server endpoints.
    """
    legacy_prices = {}
    for store, candidates in store_raw_results.items():
        if candidates in (None, "not_available"):
            legacy_prices[store] = "not_available"
        else:
            resolved = resolve_best_candidate(query, store, candidates)
            legacy_prices[store] = resolved["price"] if resolved else "not_available"
    return legacy_prices
