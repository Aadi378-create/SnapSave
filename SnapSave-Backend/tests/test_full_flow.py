import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.match_pipeline import run_match_pipeline
from stores.price_parallel import get_prices_parallel
from pricing.reward_engine import apply_rewards



def test_item(item):

    print("\nUSER QUERY:", item)

    match = run_match_pipeline(item)

    print("MATCHED PRODUCT:", match["matched_product"])

    prices = get_prices_parallel(
        match["matched_product"],
        match["quantity"]
    )

    print("STORE PRICES:", prices)

    final = apply_rewards(prices)

    print("FINAL RESULTS:", final)


if __name__ == "__main__":

    items = [
        "2 packet maggi",
        "1kg basmati rice",
        "amul milk"
    ]

    for i in items:
        test_item(i)