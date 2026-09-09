import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.aggregator import run_full_analysis

if __name__ == "__main__":
    items = [
        "2 packet maggi",
        "1kg basmati rice",
        "amul milk"
    ]

    result = run_full_analysis(items)
    print(result)