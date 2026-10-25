"""Database-backed, at-least-once research scheduling with expiring worker leases.

Research providers must be read-only. Order revision predicates remain the final
write fence; a resumed job cannot overwrite a human takeover or another generation.
"""
from datetime import timedelta
import uuid
from sqlalchemy import or_,exists,select
from sqlalchemy.exc import IntegrityError
import models
from database import SessionLocal
from time_utils import utcnow

LEASE_SECONDS=120
MAX_ATTEMPTS=3

def eligible(order):
    return bool(order and order.assigned_worker_type=='AI' and order.mode in {'AI','HYBRID'} and order.status in {'pending_review','reviewing'})

def enqueue(order_id,reset=True):
    with SessionLocal() as db:
        order=db.get(models.Order,order_id)
        if not eligible(order):return False
        job=db.get(models.ResearchJob,order_id)
        if job and (not reset or job.state=='queued' or (job.state=='running' and order.revision<=job.order_revision+1)):return True
        if job:
            job.state='queued';job.attempts=0;job.order_revision=order.revision;job.owner=None;job.lease_until=None;job.updated_at=utcnow()
        else:db.add(models.ResearchJob(order_id=order_id,state='queued',attempts=0,order_revision=order.revision))
        try:db.commit()
        except IntegrityError:db.rollback() # A competing scheduler already stored the intent.
        return True

def recover_intents():
    with SessionLocal() as db:
        ids=[row[0] for row in db.query(models.Order.id).outerjoin(models.ResearchJob,models.ResearchJob.order_id==models.Order.id).filter(models.ResearchJob.order_id==None,models.Order.assigned_worker_type=='AI',models.Order.mode.in_(['AI','HYBRID']),models.Order.status.in_(['pending_review','reviewing'])).limit(100).all()]
    for identity in ids:enqueue(identity,reset=False)

def pending(limit=20):
    with SessionLocal() as db:
        return [row[0] for row in db.query(models.ResearchJob.order_id).filter(or_(models.ResearchJob.state=='queued',(models.ResearchJob.state=='running')&(models.ResearchJob.lease_until<utcnow()))).order_by(models.ResearchJob.created_at,models.ResearchJob.order_id).limit(limit).all()]

def claim(order_id):
    owner=str(uuid.uuid4());now=utcnow()
    with SessionLocal() as db:
        active=exists(select(models.Order.id).where(models.Order.id==order_id,models.Order.assigned_worker_type=='AI',models.Order.mode.in_(['AI','HYBRID']),models.Order.status.in_(['pending_review','reviewing'])))
        if not eligible(db.get(models.Order,order_id)):
            db.query(models.ResearchJob).filter(models.ResearchJob.order_id==order_id,~active).update({'state':'cancelled','owner':None,'lease_until':None,'updated_at':now});db.commit();return None
        count=db.query(models.ResearchJob).filter(models.ResearchJob.order_id==order_id,active,or_(models.ResearchJob.state=='queued',(models.ResearchJob.state=='running')&(models.ResearchJob.lease_until<now))).update({'state':'running','owner':owner,'lease_until':now+timedelta(seconds=LEASE_SECONDS),'attempts':models.ResearchJob.attempts+1,'updated_at':now},synchronize_session=False)
        db.commit()
        if count!=1:return None
        job=db.get(models.ResearchJob,order_id)
        return owner,job.attempts

def renew(order_id,owner):
    with SessionLocal() as db:
        count=db.query(models.ResearchJob).filter_by(order_id=order_id,owner=owner,state='running').update({'lease_until':utcnow()+timedelta(seconds=LEASE_SECONDS),'updated_at':utcnow()});db.commit();return count==1

def finish(order_id,owner,state='done'):
    with SessionLocal() as db:
        db.query(models.ResearchJob).filter_by(order_id=order_id,owner=owner,state='running').update({'state':state,'owner':None,'lease_until':None,'updated_at':utcnow()});db.commit()
