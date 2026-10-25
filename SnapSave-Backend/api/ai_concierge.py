"""Verified research only. Every final write checks the current ticket generation."""
from time_utils import utcnow
import json
from datetime import datetime, timedelta
from decimal import Decimal
from sqlalchemy import exists, select
import models
from core.order_policy import message,change_order,has_human_prices
from pricing.quotes import money, final_amount
from settings import research_enabled, research_provider

class AI_CONCIERGE_PROVIDER:
    @staticmethod
    def research(items, location):
        provider = research_provider()
        return provider(items, location) if provider else None

    @staticmethod
    def process_ticket(order_id, db):
        order=db.get(models.Order,order_id)
        enabled=db.get(models.SystemSetting,"ai_enabled")
        if not order:
            return
        if order.status not in {"pending_review","reviewing"} or order.mode not in {"AI","HYBRID"} or order.assigned_worker_type!="AI" or has_human_prices(order):
            return
        if not research_enabled() or not enabled or enabled.value!="true":
            change_order(db,order,mode="HUMAN",assigned_worker_type="HUMAN",ai_stopped_at=utcnow(),ai_error="Live research is unavailable.")
            message(db,order,"Live research is unavailable. A human concierge will review this ticket.")
            db.commit()
            return
        version=order.revision
        global_enabled=exists(select(models.SystemSetting.key).where(models.SystemSetting.key=="ai_enabled",models.SystemSetting.value=="true"))
        count=db.query(models.Order).filter(models.Order.id==order_id,models.Order.revision==version,global_enabled).update({models.Order.ai_started_at:utcnow(),models.Order.revision:version+1},synchronize_session=False)
        if count!=1:
            db.rollback()
            return
        db.commit()
        version+=1
        db.expire_all()
        order=db.get(models.Order,order_id)
        items=[{"item_id":i.id,"name":i.name,"quantity":i.quantity} for i in order.items]
        location=order.delivery_postal_code
        previous_prices=order.manual_prices
        db.rollback() # Do not retain a transaction/connection while researching.
        draft=None;rows=None
        try:
            quote=AI_CONCIERGE_PROVIDER.research(items,location)
            if isinstance(quote,dict) and quote.get('transport')=='browser_pending':
                from core.order_research import merge_browser_evidence
                try:previous=json.loads(previous_prices or '{}').get('research_draft')
                except (ValueError,AttributeError):previous=None
                quote=merge_browser_evidence(previous,quote)
                if any(item['candidates'] for item in quote['items']):
                    quote['transport']='browser_capture'
                    quote['source']='Fresh order-bound browser evidence'
            if isinstance(quote,dict) and quote.get("requires_human_review") is True and quote.get("verified") is False:
                contexts=quote.get('research_contexts',[])
                if not isinstance(contexts,list) or any(not isinstance(context,dict) or context.get('order_id')!=order_id or context.get('revision')!=version or context.get('postal_code')!=location for context in contexts):
                    raise ValueError('Browser evidence belongs to a different order or research revision')
                if quote.get("postal_code")!=location or not isinstance(quote.get("items"),list):
                    raise ValueError("Research draft does not match the requested delivery context")
                expected={i["item_id"] for i in items}
                if len(quote["items"])!=len(expected) or {i.get("item_id") for i in quote["items"]}!=expected:
                    raise ValueError("Research draft must describe every requested item")
                encoded=json.dumps({"research_draft":quote})
                if len(encoded)>200000:
                    raise ValueError("Research evidence exceeds the supported size")
                draft=quote
                values={"manual_prices":encoded,"is_ai_priced":True,"ai_stopped_at":utcnow(),
                        "ai_error":None if quote.get('transport')=='browser_pending' else "Public catalogue research requires human verification of products, availability and checkout fees." if any(i.get("candidates") for i in quote["items"]) else "No usable public catalogue prices were available. Review the source diagnostics and price this ticket manually.",
                        "mode":"HUMAN" if quote.get("autonomous_attempt") else "HYBRID","assigned_worker_type":"HUMAN","revision":version+1,"updated_at":utcnow()}
                if quote.get("autonomous_attempt"):
                    values["ai_error"]=quote.get("handover_reason") or "Automatic research could not verify all products, delivery coverage and checkout fees."
            else:
                if not quote or quote.get("verified") is not True or quote.get("postal_code")!=location:
                    raise ValueError("Live inventory and pricing could not be verified. A human must price this ticket.")
                rows=quote["items"]
                expected={i["item_id"]:i for i in items}
                if len(rows)!=len(expected) or {i["item_id"] for i in rows}!=set(expected):
                    raise ValueError("Research did not cover the complete requested basket")
                from pricing.quotes import store_id
                for i in rows:
                    i["store"]=store_id(i["store"])
                    i["quantity"]=expected[i["item_id"]]["quantity"]
                    i["name"]=expected[i["item_id"]]["name"]
                    i["line_total"]=float(money(i["line_total"]))
                subtotal=sum((money(i["line_total"]) for i in rows),Decimal(0))
                fees={k:money(quote.get(k,0)) for k in ("delivery_fee","platform_fee","service_fee","store_discount","snapsave_discount")}
                final=final_amount(subtotal,*[fees[k] for k in ("delivery_fee","platform_fee","service_fee","store_discount","snapsave_discount")])
                values={"manual_prices":json.dumps({"items":rows,"source":quote.get("source"),"verified":True}),"is_ai_priced":True,"ai_stopped_at":utcnow(),"ai_error":None,"revision":version+1,"updated_at":utcnow()}
                if order.mode=="AI":
                    values.update(status="awaiting_customer",subtotal=subtotal,final_price=final,store=rows[0]["store"],quote_expires_at=utcnow()+timedelta(minutes=15),savings=fees["store_discount"]+fees["snapsave_discount"],**fees)
        except Exception as exc:
            values={"ai_error":str(exc)[:1000],"ai_stopped_at":utcnow(),"revision":version+1,"assigned_worker_type":"HUMAN","mode":"HUMAN"}
            rows=None;draft=None
        # This predicate is evaluated in the same UPDATE that writes the result.
        predicates=[models.Order.id==order_id,models.Order.revision==version,models.Order.assigned_worker_type=="AI",models.Order.mode.in_(["AI","HYBRID"]),models.Order.status.in_(["pending_review","reviewing"]),global_enabled]
        count=db.query(models.Order).filter(*predicates).update(values,synchronize_session=False)
        if count!=1:
            db.rollback()
            return
        db.expire_all()
        current=db.get(models.Order,order_id)
        if draft is not None:
            if draft.get('autonomous_attempt'):
                message(db,current,"Automatic store research needs assistance. A concierge will resolve the unavailable or unverified retailer data before a quote is sent.")
            elif draft.get('transport')=='browser_pending':
                message(db,current,"Your grocery list is ready for retailer research. Your concierge will check the requested products and delivery area before sending a quote.")
            else:
                message(db,current,"Catalogue research is ready for human review. Prices, delivery coverage and fees have not been confirmed." if any(i.get("candidates") for i in draft["items"]) else "Public sources did not provide usable product evidence. A concierge will price this order manually.")
        elif rows:
            by_id={i.id:i for i in current.items}
            for i in rows:
                by_id[i["item_id"]].line_total=money(i["line_total"])
                by_id[i["item_id"]].unit_price=money(i["line_total"])/i["quantity"]
                by_id[i["item_id"]].store=i["store"]
            if current.mode=="AI":
                from api.server import quote_text
                message(db,current,quote_text(current,rows),role="AI",sender="system_ai",kind="quote")
            else:
                message(db,current,"AI research draft is ready for human verification.")
        else:
            message(db,current,"Live research was unavailable. This ticket is now assigned to human review.")
        db.commit()
