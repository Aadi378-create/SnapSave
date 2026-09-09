import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.basket_engine import process_basket

if __name__ == "__main__":
    items = [
        "2 packet maggi",
        "1kg basmati rice",
        "amul milk"
    ]

    result = process_basket(items)
    print(result)