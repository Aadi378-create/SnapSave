import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.match_pipeline import run_match_pipeline

tests = [
    "2 packet maggi",
    "1kg basmati rice",
    "lays 20rs",
    "amul milk",
    "2kg aloo",
    "1kg dudh"
]

if __name__ == "__main__":
    for t in tests:
        print(run_match_pipeline(t))