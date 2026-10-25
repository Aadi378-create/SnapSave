"""Order-aware browser research planning, coverage and fresh evidence merging.

Planning never contacts a retailer or supplies a price. Capture import performs
the authenticated order/location checks before calling these pure helpers.
"""
from copy import deepcopy
from datetime import datetime, timezone

from core.catalog_research import ResearchUnavailable, research_catalog


def validate_basket(items):
    if not isinstance(items,list) or not 1<=len(items)<=100:
        raise ResearchUnavailable('Research supports between 1 and 100 grocery items')
    seen=set()
    for item in items:
        if (not isinstance(item,dict) or not isinstance(item.get('item_id'),str)
            or item['item_id'] in seen or not isinstance(item.get('name'),str)
            or not 1<=len(item['name'].strip())<=500 or type(item.get('quantity')) is not int
            or not 1<=item['quantity']<=10000):
            raise ResearchUnavailable('Each research item needs a unique ID, name and positive quantity')
        seen.add(item['item_id'])


def prepare_research(items,postal_code):
    """Configured AI provider for staff-assisted browser research, without HTTP."""
    from core.catalog_research import location_plan
    validate_basket(items)
    location_plan('planning',0,postal_code)  # Shared postcode validation.
    return {'verified':False,'requires_human_review':True,'postal_code':str(postal_code),
        'research_contexts':[],'source':'Order research plan; retailer captures required',
        'transport':'browser_pending','observed_at':datetime.now(timezone.utc).isoformat(),
        'items':[{'item_id':i['item_id'],'query':i['name'].strip(),'quantity':i['quantity'],'candidates':[]} for i in items],
        'diagnostics':[],'warnings':['Select the order delivery area and capture the relevant products on each retailer. Missing evidence is not a price or an out-of-stock claim.']}


def fresh(candidate):
    try:
        observed=datetime.fromisoformat(candidate['observed_at'])
        return observed.tzinfo is not None and 0<=(datetime.now(timezone.utc)-observed).total_seconds()<=900
    except (KeyError,TypeError,ValueError):return False


def research_summary(draft):
    items=draft.get('items',[]) if isinstance(draft,dict) else []
    matched=sum(any(fresh(c) for c in item.get('candidates',[])) for item in items)
    stale=any(item.get('candidates') for item in items) and not matched
    return {'state':'needs_refresh' if stale else 'ready_for_review' if items and matched==len(items) else 'partial' if matched else 'awaiting_capture',
        'matched_items':matched,'total_items':len(items),'missing_items':len(items)-matched,
        'requires_human_review':True}


def research_basket(items,postal_code,client):
    """Use the same capture client for up to five bounded 20-item batches."""
    validate_basket(items)
    combined=None
    for offset in range(0,len(items),20):
        draft=research_catalog(items[offset:offset+20],postal_code,client)
        if combined is None:combined=draft
        else:
            combined['items'].extend(draft['items'])
            combined['diagnostics'].extend(draft['diagnostics'])
    combined['diagnostics']=combined['diagnostics'][:100]
    return combined


def merge_browser_evidence(previous,incoming):
    """Retain fresh evidence from other sources, replacing recaptured sources."""
    result=deepcopy(incoming)
    if not isinstance(previous,dict) or previous.get('postal_code')!=incoming['postal_code']:
        return result
    replaced={(d['store'],d['url']) for d in incoming.get('diagnostics',[]) if d.get('store') and d.get('url')}
    old_items={i.get('item_id'):i for i in previous.get('items',[]) if isinstance(i,dict)}
    for item in result['items']:
        old=old_items.get(item['item_id'],{})
        candidates=list(item['candidates'])
        for c in old.get('candidates',[]):
            location=c.get('location_context',{})
            if (not fresh(c) or location.get('requested_postal_code')!=incoming['postal_code']
                or location.get('status') not in {'staff_attested','postcode_observed'}):continue
            if (c.get('store'),c.get('capture_url')) in replaced:continue
            if not c.get('capture_url') and any(store==c.get('store') for store,_ in replaced):continue
            candidates.append(c)
        unique={}
        for c in candidates:
            key=(c['store'],c.get('sku') or c['name'],c['source_url'])
            unique.setdefault(key,c)
        item['candidates']=sorted(unique.values(),key=lambda c:c['price'])[:6]
    return result
