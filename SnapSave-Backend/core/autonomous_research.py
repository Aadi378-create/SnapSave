"""Order-triggered public requests; blocked/unverified results explicitly need takeover."""
import time
from threading import Lock
from core.catalog_research import PublicCatalogClient, ResearchUnavailable
from core.order_research import research_basket

_blocked={}
_lock=Lock()

class AutonomousCatalogClient(PublicCatalogClient):
    def fetch(self,url,store):
        with _lock:
            previous=_blocked.get((store,url))
        if previous and time.monotonic()<previous[0]:
            raise ResearchUnavailable('Retailer temporarily unavailable; retry cooldown: '+previous[1])
        try:
            return super().fetch(url,store)
        except ResearchUnavailable as error:
            reason=str(error)
            if any(marker in reason for marker in ('HTTP 202','HTTP 403','HTTP 429','disallows')):
                with _lock:
                    if len(_blocked)>=256:_blocked.clear()
                    _blocked[(store,url)]=(time.monotonic()+90,reason)
            raise


def research(items,postal_code):
    # One client shares request/time budgets and page cache across all 100 items.
    client=AutonomousCatalogClient(timeout=30,max_requests=12)
    try:
        draft=research_basket(items,postal_code,client)
    finally:
        client.close()
    # Repeated failed URLs affect many basket items; one source diagnostic suffices.
    unique={}
    for diagnostic in draft['diagnostics']:
        unique.setdefault((diagnostic.get('store'),diagnostic.get('url'),diagnostic.get('status')),diagnostic)
    draft['diagnostics']=list(unique.values())
    found=sum(bool(item['candidates']) for item in draft['items'])
    draft.update(autonomous_attempt=True, handover_reason=(
        'Automatic retailer requests returned no matching product evidence. See retailer diagnostics.' if not found else
        'Public prices found, but delivery postcode, stock, exact packs and checkout fees could not all be verified automatically.'
    ))
    return draft
