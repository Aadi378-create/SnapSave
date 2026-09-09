import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.query_parser import parse_query

tests = [
    "2 packet maggi",
    "1kg basmati rice",
    "lays 20rs",
    "amul milk"
]

if __name__ == "__main__":
    for t in tests:
        print(parse_query(t))