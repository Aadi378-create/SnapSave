"""Read-only research diagnostic. Does not import the API or application database."""
import argparse
import json
from pathlib import Path
import settings  # Load the backend's explicit .env; no API/database initialization.
from core.catalog_research import research_catalog, BrowserCaptureClient, PublicCatalogClient


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--query',required=True)
    parser.add_argument('--postal-code',required=True)
    parser.add_argument('--live',action='store_true',help='Permit bounded public HTTP requests')
    parser.add_argument('--browser-capture',type=Path,help='Parse a fresh public DOM capture JSON instead of making network requests')
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    if args.live==bool(args.browser_capture):
        parser.error('Choose exactly one of --live or --browser-capture')
    client=None
    try:
        if args.browser_capture:
            if args.browser_capture.stat().st_size>8_000_000:parser.error('Capture file exceeds 8 MB')
            client=BrowserCaptureClient(json.loads(args.browser_capture.read_text(encoding='utf-8')))
        else:
            client=PublicCatalogClient()
        result=research_catalog([{'item_id':'diagnostic','name':args.query,'quantity':1}],args.postal_code,client=client)
    except (OSError,ValueError) as exc:
        parser.error(str(exc))
    finally:
        if client is not None:client.close()
    body=json.dumps(result,indent=2,ensure_ascii=False)
    if args.output:
        args.output.write_text(body,encoding='utf-8')
    else:
        print(body)
    return result


if __name__=='__main__':
    main()
