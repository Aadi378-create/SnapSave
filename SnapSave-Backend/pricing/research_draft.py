"""Calculate item-price drafts from fresh, order-bound retailer observations.

No checkout fees, stock guarantees or customer quotes are produced here.
"""
import re
from decimal import Decimal
from fastapi import HTTPException
from core.catalog_research import safe_url
from core.order_research import fresh
from core.query_parser import parse_query
from core.product_ranker import score_product
from pricing.quotes import money


def pack_size(text):
    parsed=parse_query(text)
    if parsed['volume'] is not None:
        amount=Decimal(str(parsed['volume']));unit=parsed['unit']
        if amount<=0:return None
        return (amount*1000,'g') if unit=='kg' else (amount*1000,'ml') if unit=='l' else (amount,unit)
    count=re.search(r'\bpack\s+of\s+(\d+)\b|\b(\d+)\s*(?:pcs|pieces)\b',text,re.I)
    return (Decimal(count[1] or count[2]),'pieces') if count and int(count[1] or count[2])>0 else None


def price_proposal(items,draft,postal_code,selections=None):
    """A single supported match can fill a draft; ambiguous products need selection."""
    selections=selections or {}
    expected={i['item_id']:i for i in items}
    if set(selections)-expected.keys():raise ValueError('A selection refers to another order item')
    evidence={i['item_id']:i for i in draft.get('items',[]) if isinstance(i,dict) and i.get('item_id') in expected}
    rows=[];matched=Decimal(0)
    for identity,item in expected.items():
        candidates=evidence.get(identity,{}).get('candidates',[])
        requested=pack_size(item['name'])
        usable=[]
        for index,c in enumerate(candidates):
            if not isinstance(c,dict):continue
            if not isinstance(c.get('name'),str) or score_product(item['name'],c['name'])<=0:continue
            location=c.get('location_context',{})
            if (not fresh(c) or c.get('currency')!='INR' or c.get('availability')=='out_of_stock'
                or location.get('requested_postal_code')!=postal_code
                or location.get('status') not in {'staff_attested','postcode_observed'}):continue
            label=c.get('pack_size','')
            if not requested or requested!=pack_size(label) or re.search(r'\d\s*[x×]\s*\d|\bor\b',label,re.I):continue
            try:
                safe_url(c.get('source_url'),c.get('store'))
                unit=money(c.get('price'))
                if unit<=0:continue
                total=money(unit*item['quantity'])
            except (ValueError,TypeError,HTTPException):continue
            usable.append((index,c,unit,total))
        chosen=next((u for u in usable if u[0]==selections[identity]),None) if identity in selections else usable[0] if len(usable)==1 else None
        row={'item_id':identity,'name':item['name'],'quantity':item['quantity']}
        if chosen is None:
            row['state']='needs_pack' if requested is None else 'needs_selection' if len(usable)>1 else 'needs_fresh_evidence'
            if identity in selections:raise ValueError('Selected price is stale, mismatched or unsupported. Recapture before using it')
        else:
            index,c,unit,total=chosen
            row.update(state='priced',candidate_index=index,store=c['store'],pack_size=c['pack_size'],
                observed_pack_price=float(unit),line_total=float(total),source_url=c['source_url'],observed_at=c['observed_at'])
            matched+=total
        rows.append(row)
    complete=all(r['state']=='priced' for r in rows)
    return {'items':rows,'complete':complete,'matched_subtotal':float(matched),
        'subtotal':float(matched) if complete else None,'fees_verified':False,'payable_total':None,
        'requires_human_review':True}
