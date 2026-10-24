"""Order ownership and optimistic writes shared by every workflow."""
from time_utils import utcnow
from datetime import datetime
from fastapi import HTTPException
import models
import json

def has_human_prices(order):
    if not order.manual_prices or order.is_ai_priced:
        return False
    try:
        draft = json.loads(order.manual_prices)
    except (ValueError, TypeError):
        return True  # Preserve malformed legacy drafts for manual review.
    evidence = draft.get('research_draft') if isinstance(draft, dict) else None
    evidence_only = (isinstance(draft, dict) and set(draft) == {'research_draft'}
                     and isinstance(evidence, dict) and evidence.get('verified') is False
                     and evidence.get('requires_human_review') is True)
    return not evidence_only

def staff_access(order, user):
    if user.is_blacklisted:
        raise HTTPException(403, 'Staff access is restricted')
    if user.role == "ADMIN":
        return
    if user.role != "MODERATOR" or order.assigned_moderator_id != user.id:
        raise HTTPException(403, "You are not assigned to this order")

def read_access(order, user):
    if order.user_id == user.id:
        return
    if user.role == "CUSTOMER":
        if order.user_id != user.id:
            raise HTTPException(403, "Not authorized to view this order")
    else:
        staff_access(order, user)

def require_state(order, allowed):
    if order.status not in allowed:
        raise HTTPException(409, "This action is not available in the current order state")

def change_order(db, order, **values):
    revision = order.revision
    values.update(revision=revision + 1, updated_at=utcnow())
    count = db.query(models.Order).filter(models.Order.id == order.id, models.Order.revision == revision).update(values, synchronize_session=False)
    if count != 1:
        db.rollback()
        raise HTTPException(409, "Order changed. Reload it before retrying")
    db.expire(order)

def message(db, order, text, role="SYSTEM", sender="system", kind="text"):
    db.add(models.Message(user_id=order.user_id, order_id=order.id, sender_id=sender, sender_role=role, message=text, kind=kind))
