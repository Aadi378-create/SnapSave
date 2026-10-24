"""Read-only research diagnostic. Does not import the API or application database."""
import argparse
import json
from pathlib import Path
import settings  # Load the backend's explicit .env; no API/database initialization.
from core.catalog_research import research_catalog


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--query',required=True)
    parser.add_argument('--postal-code',required=True)
    parser.add_argument('--live',action='store_true',help='Permit bounded public HTTP requests')
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    if not args.live:
        parser.error('--live is required for public retailer requests')
    result=research_catalog([{'item_id':'diagnostic','name':args.query,'quantity':1}],args.postal_code)
    body=json.dumps(result,indent=2,ensure_ascii=False)
    if args.output:
        args.output.write_text(body,encoding='utf-8')
    else:
        print(body)
    return result


if __name__=='__main__':
    main()
