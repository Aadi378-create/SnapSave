from time_utils import utcnow
import os

import uuid
import re
from datetime import datetime, timedelta
from typing import Optional, List
from fastapi import FastAPI, Depends, Header, HTTPException, status, Request, Query
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import func, or_, case
from sqlalchemy.orm import Session, selectinload, joinedload
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
import time
import jwt
import requests
import threading
import json
import hashlib
import logging
from contextlib import asynccontextmanager
from decimal import Decimal
from zoneinfo import ZoneInfo
from sqlalchemy.exc import IntegrityError
from settings import BASE_DIR, dev_auth_enabled, research_enabled, ACTIVE_STATUSES, STORES
from migrations import migrate
from core.order_policy import staff_access, read_access, require_state, change_order, message as order_message
from pricing.quotes import money, quote_items, totals as preview_totals, final_amount, store_id
from api.guardrails import RequestLimits

# Import database core
from database import engine, Base, get_db
import models

# Import existing core functions
from core.cart_builder import build_cart_from_text
from stores.price_parallel import get_prices_parallel
from pricing.pricing_engine import run_pricing_engine
from api.ai_concierge import AI_CONCIERGE_PROVIDER
from pricing.store_availability import check_store_availability
from pricing.pivot_layer import convert_to_legacy_prices, resolve_best_candidate

# Initialize Firebase Admin
import firebase_admin
from firebase_admin import credentials, auth

firebase_initialized = False
cred_path = os.getenv("FIREBASE_CREDENTIALS", str(BASE_DIR / "admin/firebase-service-account.json"))
if not os.path.isabs(cred_path):
    cred_path=str(BASE_DIR/cred_path)

# Try initializing with service account credentials first
if os.path.exists(cred_path):
    try:
        cred = credentials.Certificate(cred_path)
        firebase_admin.initialize_app(cred)
        firebase_initialized = True
        print("Firebase Admin SDK initialized with Service Account.")
    except Exception as e:
        print(f"Firebase Admin credentials could not be loaded ({type(e).__name__}).")
        firebase_initialized = False

# Fallback: Initialize with Project ID for public certificate verification
if not firebase_initialized:
    try:
        firebase_admin.initialize_app(options={"projectId": os.getenv("FIREBASE_PROJECT_ID","snapsave-501c7")})
        firebase_initialized = True
        print("[OK] Firebase Admin SDK initialized with Project ID fallback.")
    except Exception as e:
        print(f"Warning: Failed to initialize Firebase Admin SDK: {e}")

@asynccontextmanager
async def lifespan(app):
    startup_event()
    try:
        yield
    finally:
        stop_workers()

app = FastAPI(title="SnapSave API", lifespan=lifespan)

@app.exception_handler(IntegrityError)
async def integrity_conflict(request, exc):
    from fastapi.responses import JSONResponse
    return JSONResponse({"detail":"This change conflicts with an existing record. Reload before retrying."},status_code=409)

# Enable CORS for frontend integration
app.add_middleware(
    CORSMiddleware,
    allow_origins=[v.strip() for v in os.getenv("CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(",") if v.strip()],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
)


app.add_middleware(RequestLimits)
allowed_hosts=[host.strip() for host in os.getenv('ALLOWED_HOSTS','localhost,127.0.0.1').split(',') if host.strip()]
if not allowed_hosts or '*' in allowed_hosts:raise RuntimeError('ALLOWED_HOSTS must name explicit API hostnames')
if os.getenv('APP_ENV')=='test':allowed_hosts+=['testserver','snapsave.test']
app.add_middleware(TrustedHostMiddleware,allowed_hosts=allowed_hosts)

def run_sqlite_column_migrations():
    migrate(engine)


# Background cache cleanup task
def start_cache_cleanup():
    # Caches evict expired entries on access and are size-bounded.
    return

# Startup event to verify/initialize database schema
def startup_event():
    from database import SessionLocal
    global _ai_executor
    if _ai_executor is None:
        _ai_executor=ThreadPoolExecutor(max_workers=2,thread_name_prefix="concierge")
    Base.metadata.create_all(bind=engine)
    migrate(engine)
    if engine.dialect.name=="sqlite":
        with engine.connect() as connection:
            connection.exec_driver_sql("PRAGMA journal_mode=WAL")
    with SessionLocal() as db:
        if not db.get(models.AppSetting, 1):
            db.add(models.AppSetting(id=1, orders_enabled=True))
        if not db.get(models.SystemSetting, "ai_enabled"):
            db.add(models.SystemSetting(key="ai_enabled", value="false"))
        # A server restart invalidates unfinished in-process research jobs.
        for row in db.query(models.Order).filter(models.Order.assigned_worker_type=="AI",models.Order.status.in_(["pending_review","reviewing"])):
            change_order(db,row,mode="HUMAN",assigned_worker_type="HUMAN",ai_stopped_at=utcnow(),ai_error="Research was interrupted by a restart. Human review is required.")
            order_message(db,row,"Research was interrupted. A human concierge will review this ticket.")
        db.commit()


# -------------------------------
# Request / Response Models
# -------------------------------

class StrictRequest(BaseModel):
    model_config=ConfigDict(str_strip_whitespace=True)

class CartRequest(StrictRequest):
    items: str = Field(..., min_length=1, max_length=10000)
    location: str = Field(..., min_length=1, max_length=100)


class AddressCreate(StrictRequest):
    title: str = Field(..., min_length=1, max_length=50)
    street_address: str = Field(..., min_length=1, max_length=500)
    city: str = Field(..., min_length=1, max_length=100)
    state: str = Field(..., min_length=1, max_length=100)
    postal_code: str = Field(..., pattern=r"^[1-9][0-9]{5}$")
    latitude: Optional[float] = Field(None, ge=-90, le=90, allow_inf_nan=False)
    longitude: Optional[float] = Field(None, ge=-180, le=180, allow_inf_nan=False)
    is_default: bool = False


class OrderItemInput(StrictRequest):
    name: str = Field(..., min_length=1, max_length=255)
    quantity: int = Field(1, ge=1, le=1000)


class OrderCreate(StrictRequest):
    store: Optional[str] = "pending"
    address_id: str = Field(..., max_length=36)
    items: Optional[List[OrderItemInput]] = Field(None, max_length=100)
    items_text: Optional[str] = Field(None, max_length=10000)


class OrderItemPrice(StrictRequest):
    item_id: str = Field(..., max_length=36)
    name: Optional[str] = Field(None, max_length=255)
    line_total: Optional[float] = Field(None, ge=0, le=9999999, allow_inf_nan=False)
    unit_price: Optional[float] = Field(None, ge=0, le=9999999, allow_inf_nan=False, description="Legacy input: total line cost. Use line_total instead")
    store: str = Field(..., max_length=30)


class RoleUpdate(StrictRequest):
    user_id: str
    role: str


class PhoneRoleRequest(StrictRequest):
    phone: str


class AssignModerator(StrictRequest):
    customer_id: str
    moderator_id: str


class ManualPricesEntry(StrictRequest):
    items: Optional[List[OrderItemPrice]] = Field(None, description="Per-product lowest price + store")
    prices: Optional[dict] = Field(None, description="Store-level price mapping e.g. {'zepto': 300, ...}")

class QuoteSubmission(StrictRequest):
    revision: int = Field(..., ge=0)
    store: str = Field(..., max_length=30)
    items: List[OrderItemPrice] = Field(..., min_length=1, max_length=100)
    subtotal: float = Field(..., ge=0, le=9999999, allow_inf_nan=False)
    delivery_fee: float = Field(..., ge=0, le=9999999, allow_inf_nan=False)
    platform_fee: float = Field(..., ge=0, le=9999999, allow_inf_nan=False)
    service_fee: float = Field(0, ge=0, le=9999999, allow_inf_nan=False)
    store_discount: float = Field(0, ge=0, le=9999999, allow_inf_nan=False)
    snapsave_discount: float = Field(0, ge=0, le=9999999, allow_inf_nan=False)
    final_price: float = Field(..., ge=0, le=9999999, allow_inf_nan=False)

class QuoteConfirmation(StrictRequest):
    revision: int = Field(..., ge=0)

class ResearchCaptureSubmission(StrictRequest):
    revision: int = Field(..., ge=0)
    captures: List[dict] = Field(..., min_length=1, max_length=15)

class DeliveryConfig(StrictRequest):
    thresholds: dict[str,float]
class AiTakeoverRequest(StrictRequest):
    ai_takeover_enabled: bool

class OrderModeRequest(StrictRequest):
    mode: str

class DelegateWorkerRequest(StrictRequest):
    assigned_worker_type: str


class AiStatusRequest(StrictRequest):
    ai_enabled: bool


class AssignModeratorToOrder(StrictRequest):
    moderator_id: str


class BlacklistRequest(StrictRequest):
    reason: Optional[str] = Field(None,max_length=500)


class HelpMessageCreate(StrictRequest):
    message: str = Field(..., min_length=1, max_length=4000)


class MaintenanceUpdate(StrictRequest):
    maintenance_mode: bool





class SendMessageRequest(StrictRequest):
    message: str = Field(..., min_length=1, max_length=4000)
    order_id: Optional[str] = Field(None, max_length=36)
    request_id: Optional[uuid.UUID] = None


class OrderFinancialsUpdate(StrictRequest):
    customer_paid: float = Field(..., ge=0, le=9999999, allow_inf_nan=False)
    store_cost: float = Field(..., ge=0, le=9999999, allow_inf_nan=False)




class AppSettingUpdate(StrictRequest):
    orders_enabled: bool


class ProfileUpdate(StrictRequest):
    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str = Field(..., min_length=1, max_length=100)
    email: str = Field(..., pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$", max_length=255)


class FeedbackCreate(StrictRequest):
    order_id: str
    rating: int = Field(..., ge=1, le=5)
    what_went_well: Optional[str] = Field(None,max_length=2000)
    what_was_confusing: Optional[str] = Field(None,max_length=2000)
    would_use_again: bool


class IncidentCreate(StrictRequest):
    order_id: Optional[str] = None
    incident_type: str = Field(...,min_length=1,max_length=100)
    notes: Optional[str] = Field(None,max_length=4000)


# -------------------------------
# Authentication Dependency
# -------------------------------

_test_private_key = None
_test_public_cert = None
_key_lock = threading.Lock()

def get_test_keys():
    global _test_private_key, _test_public_cert
    if not dev_auth_enabled():
        raise HTTPException(404, "Development authentication is disabled")
    with _key_lock:
        if _test_private_key is None:
            from cryptography.hazmat.primitives.asymmetric import rsa
            from cryptography.hazmat.primitives import serialization
            _test_private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            _test_public_cert = _test_private_key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    return _test_private_key, _test_public_cert

def get_current_user(authorization: str = Header(None), db: Session = Depends(get_db)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing or invalid Authorization header")
    token = authorization[7:].strip()
    try:
        header = jwt.get_unverified_header(token)
        if header.get("kid") == "test_kid":
            if not dev_auth_enabled():
                raise HTTPException(401, "Development tokens are disabled")
            _, public = get_test_keys()
            decoded = jwt.decode(token, public, algorithms=["RS256"], audience="snapsave-dev", issuer="snapsave-dev", options={"require":["exp","iat","sub"]})
        else:
            if not firebase_initialized:
                raise HTTPException(503, "Authentication is unavailable")
            decoded = auth.verify_id_token(token, check_revoked=True, clock_skew_seconds=30)
        uid = decoded.get("sub") or decoded.get("uid")
        if not uid:
            raise ValueError("Missing identity")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(401, "Invalid or expired session")
    phone = decoded.get("phone_number") or None
    user = db.get(models.User, uid)
    if not user and phone:
        user = db.query(models.User).filter(models.User.phone_number == phone).first()
    if not user:
        user = models.User(id=uid, email=f"{uid}@snapsave.com", phone_number=phone, password_hash="firebase_managed", role="CUSTOMER", completed_orders_count=0)
        db.add(user)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            user = db.query(models.User).filter(models.User.phone_number == phone).first() if phone else db.get(models.User, uid)
            if not user:
                raise HTTPException(409, "Account identity conflict")
    # Roles are database-managed; neither UID names nor a phone constant grants access.
    return user


def require_role(allowed_roles: List[str]):
    def dependency(current_user: models.User = Depends(get_current_user)):
        if current_user.is_blacklisted or current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Operation not permitted for this user role"
            )
        return current_user
    return dependency


# -------------------------------
# Health Check & Legacy Endpoints
# -------------------------------

@app.get("/")
def home():
    return {"message": "SnapSave backend running"}


@app.get("/deal")
def find_deal(item: str = Query(...,min_length=1,max_length=255), location: str = Query(...,min_length=1,max_length=100), current_user: models.User = Depends(get_current_user)):
    if not research_enabled():
        raise HTTPException(503,"Live price research is unavailable")
    raw=get_prices_parallel(item,1,location)
    prices=convert_to_legacy_prices(raw,item)
    valid={k:v for k,v in prices.items() if isinstance(v,(int,float))}
    return {"item":item,"stores":prices,"best_deal":{"store":min(valid,key=valid.get),"price":min(valid.values())} if valid else None,"requires_human_verification":True}


@app.post("/optimize-cart")
def optimize_cart_endpoint(request: CartRequest, current_user: models.User = Depends(get_current_user)):
    if not research_enabled():
        raise HTTPException(503,"Live price research is unavailable; request a human concierge quote")
    cart=build_cart_from_text(request.items)
    scraped={}
    for item in cart:
        raw=get_prices_parallel(item["original_query"],item["quantity"],request.location)
        offers=[]
        for store,candidates in raw.items():
            resolved=resolve_best_candidate(item["original_query"],store,candidates)
            if resolved:
                offers.append(resolved)
        if not offers:
            raise HTTPException(409,"A requested item needs human availability verification")
        scraped[item["original_query"]]=offers
    return {"cart":cart,"pricing":run_pricing_engine(scraped,request.location),"source":"live_research","requires_human_verification":True}


# -------------------------------
# User Authentication / Profile
# -------------------------------

@app.get("/api/auth/me")
def get_me(current_user: models.User = Depends(get_current_user)):
    """
    Returns current authenticated user details.
    """
    return {
        "id": current_user.id,
        "email": current_user.email,
        "phone_number": current_user.phone_number,
        "first_name": current_user.first_name,
        "last_name": current_user.last_name,
        "role": current_user.role,
        "membership_tier": current_user.membership_tier,
        "completed_orders_count": current_user.completed_orders_count
    }


@app.get("/api/auth/test-token")
def get_test_token(request: Request, phone: str, uid: Optional[str] = None):
    if not dev_auth_enabled() or not request.client or request.client.host not in {"127.0.0.1", "::1", "localhost", "testclient"}:
        raise HTTPException(404, "Development authentication is disabled")
    if not re.fullmatch(r"\+[1-9]\d{7,14}", phone):
        raise HTTPException(422, "Use an international phone number")
    # Custom IDs are only permitted in isolated automated tests.
    if uid is not None and os.getenv("APP_ENV") != "test":
        raise HTTPException(422, "Custom development identities are disabled")
    identity = uid or "dev_" + hashlib.sha256(phone.encode()).hexdigest()[:28]
    private, _ = get_test_keys()
    now = int(time.time())
    return {"idToken": jwt.encode({"iss":"snapsave-dev", "aud":"snapsave-dev", "sub":identity, "iat":now, "exp":now+3600, "phone_number":phone}, private, algorithm="RS256", headers={"kid":"test_kid"})}



# -------------------------------
# User Address Management
# -------------------------------

def lock_address_owner(db,user_id):
    # Serialize address/default changes before reading the current default.
    # A no-op owner-row update acquires a write/row lock until commit.
    db.query(models.User).filter(models.User.id==user_id).update({models.User.updated_at:models.User.updated_at},synchronize_session=False)

@app.post("/api/addresses", status_code=status.HTTP_201_CREATED)
def create_address(address_data: AddressCreate, current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    if (address_data.latitude is None) != (address_data.longitude is None):
        raise HTTPException(422, "Provide both coordinates or neither")
    lock_address_owner(db,current_user.id)
    first = not db.query(models.Address.id).filter_by(user_id=current_user.id).first()
    if address_data.is_default or first:
        db.query(models.Address).filter_by(user_id=current_user.id).update({"is_default":False})
    row = models.Address(user_id=current_user.id, title=address_data.title.strip(), street_address=address_data.street_address.strip(), city=address_data.city.strip(), state=address_data.state.strip(), postal_code=address_data.postal_code, latitude=address_data.latitude or 0, longitude=address_data.longitude or 0, coordinates_verified=address_data.latitude is not None, is_default=address_data.is_default or first)
    db.add(row)
    db.commit()
    return serialize_address(row)


@app.get("/api/addresses")
def list_addresses(current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    return [serialize_address(a) for a in db.query(models.Address).filter_by(user_id=current_user.id).all()]


@app.delete("/api/addresses/{address_id}")
def delete_address(address_id: str, current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    lock_address_owner(db,current_user.id)
    addr = db.query(models.Address).filter(
        models.Address.id == address_id,
        models.Address.user_id == current_user.id
    ).first()
    if not addr:
        raise HTTPException(status_code=404, detail="Address not found")

    was_default = addr.is_default
    db.delete(addr)
    # Delete and fallback selection commit together.
    if was_default:
        fallback = db.query(models.Address).filter(models.Address.user_id == current_user.id,models.Address.id!=address_id).order_by(models.Address.created_at,models.Address.id).first()
        if fallback:
            fallback.is_default = True
    db.commit()

    return {"message": "Address deleted successfully", "id": address_id}


@app.put("/api/addresses/{address_id}/default")
def set_default_address(address_id: str, current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    lock_address_owner(db,current_user.id)
    addr = db.query(models.Address).filter(
        models.Address.id == address_id,
        models.Address.user_id == current_user.id
    ).first()
    if not addr:
        raise HTTPException(status_code=404, detail="Address not found")

    db.query(models.Address).filter(
        models.Address.user_id == current_user.id
    ).update({"is_default": False})

    addr.is_default = True
    db.commit()
    return {"message": "Default address updated", "id": address_id}



# -------------------------------
# User Order Management & History
# -------------------------------

def serialize_order_items(order: models.Order):
    return [{"id":i.id, "name":i.name, "quantity":i.quantity, "unit_price":float(i.unit_price) if i.unit_price is not None else None, "line_total":float(i.line_total) if i.line_total is not None else None, "store":i.store} for i in sorted(order.items, key=lambda x:(x.created_at or datetime.min,x.id))]


def clean_item_name(name: str, quantity: int) -> str:
    """Clean an explicit matching count prefix from a text-parsed item."""
    name = name.strip()
    if quantity and quantity >= 1:
        # Strip leading multiplier patterns like '2x ', '2 * ', '2 pcs ', '2 packet ', '2 '
        cleaned = re.sub(
            r'^\s*'+str(quantity)+r'\s*(?:x\b|×|\*|pcs\b|pieces?\b|packets?\b|packs?\b|pkts?\b|bottles?\b|cans?\b|box(?:es)?\b)\s*',
            '',
            name,
            flags=re.IGNORECASE
        )
        if cleaned == name:
            # Strip leading numbers followed by space if not a volume unit (kg, g, gm, ml, l, etc.)
            cleaned = re.sub(
                r'^\s*'+str(quantity)+r'\s+(?!(?:kg|g|gm|ml|l|ltr|litre|liter)\b)',
                '',
                name,
                flags=re.IGNORECASE
            )
        if cleaned.strip():
            name = cleaned.strip()
    return name


@app.post("/api/orders", status_code=status.HTTP_201_CREATED)
def create_order(order_data: OrderCreate, current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db), idempotency_key: Optional[str] = Header(None, max_length=128)):
    if current_user.is_blacklisted:
        raise HTTPException(403,"Your account is restricted. Contact support")
    request_hash=hashlib.sha256(json.dumps(order_data.model_dump(),sort_keys=True).encode()).hexdigest()
    if idempotency_key:
        existing = db.query(models.Order).options(selectinload(models.Order.items)).filter_by(user_id=current_user.id, request_key=idempotency_key).first()
        if existing:
            if existing.request_hash and existing.request_hash!=request_hash:
                raise HTTPException(409,"This retry key was already used for another grocery list")
            return serialize_order(existing,current_user)
    setting = db.get(models.AppSetting, 1)
    if setting and (setting.maintenance_mode or not setting.orders_enabled):
        raise HTTPException(503, "New orders are temporarily paused")
    address = db.query(models.Address).filter_by(id=order_data.address_id, user_id=current_user.id).first()
    if not address:
        raise HTTPException(404, "Delivery address not found")
    entries = order_data.items or []
    if not entries and order_data.items_text:
        for item in build_cart_from_text(order_data.items_text):
            entries.append(OrderItemInput(name=clean_item_name(item["original_query"],item["quantity"]), quantity=item["quantity"]))
    if not entries or len(entries)>100 or any(not i.name.strip() for i in entries):
        raise HTTPException(422, "Provide between 1 and 100 grocery items")
    worker=db.get(models.User,current_user.assigned_moderator_id) if current_user.assigned_moderator_id else None
    assigned=worker.id if worker and worker.role in {'MODERATOR','ADMIN'} and not worker.is_blacklisted else None
    row = models.Order(user_id=current_user.id, address_id=address.id, request_key=idempotency_key, request_hash=request_hash, assigned_moderator_id=assigned, store="pending", status="pending_review", delivery_street=address.street_address, delivery_city=address.city, delivery_postal_code=address.postal_code, subtotal=0, delivery_fee=0, platform_fee=0, final_price=0)
    db.add(row)
    db.flush()
    for item in entries:
        # Structured item names are already separate from their quantity;
        # stripping numeric prefixes here destroys brands such as "7 Up".
        db.add(models.OrderItem(order_id=row.id, name=item.name.strip(), quantity=item.quantity))
    order_message(db,row,", ".join(f"{i.quantity}× {i.name}" for i in entries),role="CUSTOMER",sender=current_user.id)
    order_message(db,row,"Order received. Your concierge will verify availability and prices.")
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.query(models.Order).filter_by(user_id=current_user.id, request_key=idempotency_key).first() if idempotency_key else None
        if not existing or existing.request_hash!=request_hash:
            raise HTTPException(409,"Order could not be saved; check the retry key")
        row = existing
    return serialize_order(row,current_user)



@app.get("/api/orders")
def get_order_history(current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db), limit: int = Query(50,ge=1,le=100), offset: int = Query(0,ge=0), active_only: bool = False):
    query = db.query(models.Order).filter_by(user_id=current_user.id).options(selectinload(models.Order.items))
    if active_only:
        query = query.filter(models.Order.status.in_(ACTIVE_STATUSES))
    rows = query.order_by(models.Order.created_at.desc(),models.Order.id.desc()).offset(offset).limit(limit).all()
    return [serialize_order(o,current_user) for o in rows]


@app.get("/api/orders/{order_id}")
def get_order_detail(order_id: str, current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = load_order(db,order_id)
    read_access(row,current_user)
    return serialize_order(row,current_user)


@app.post("/api/orders/{order_id}/complete")
def complete_order_endpoint(order_id: str, current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = load_order(db,order_id)
    read_access(row,current_user)
    if row.status != "completed":
        require_state(row,{"delivered"})
        change_order(db,row,status="completed",completed_at=utcnow())
        db.commit()
    return {"order_id":row.id,"status":row.status,"completed_at":row.completed_at}


# -------------------------------
# Human-Concierge MVP Endpoints
# -------------------------------

@app.put("/api/admin/roles")
def update_user_role(data: RoleUpdate, current_user: models.User = Depends(require_role(["ADMIN"])), db: Session = Depends(get_db)):
    # Serialize role changes on one persistent row; separate admin rows alone
    # allow concurrent demotions to each observe another administrator.
    db.query(models.AppSetting).filter(models.AppSetting.id==1).update({models.AppSetting.orders_enabled:models.AppSetting.orders_enabled},synchronize_session=False)
    db.refresh(current_user)
    if current_user.role!='ADMIN' or current_user.is_blacklisted:
        raise HTTPException(403,'Administrator access changed. Sign in again')
    user = db.get(models.User,data.user_id)
    if not user:
        raise HTTPException(404,"User not found")
    if data.role not in {"CUSTOMER","MODERATOR","ADMIN"}:
        raise HTTPException(422,"Invalid role")
    db.refresh(user)
    if user.role=="ADMIN" and not user.is_blacklisted and data.role!="ADMIN" and db.query(models.User).filter_by(role="ADMIN",is_blacklisted=False).count()<=1:
        raise HTTPException(409,"Cannot remove the last administrator")
    user.role=data.role
    db.commit()
    return {"user_id":user.id,"role":user.role}


@app.put("/api/admin/make-admin")
def make_admin_by_phone(data: PhoneRoleRequest, current_user: models.User = Depends(require_role(["ADMIN"])), db: Session = Depends(get_db)):
    user = db.query(models.User).filter_by(phone_number=data.phone).first()
    if not user:
        raise HTTPException(404,"User not found")
    return update_user_role(RoleUpdate(user_id=user.id,role="ADMIN"),current_user,db)


@app.put("/api/admin/make-moderator")
def make_moderator_by_phone(data: PhoneRoleRequest, current_user: models.User = Depends(require_role(["ADMIN"])), db: Session = Depends(get_db)):
    user = db.query(models.User).filter_by(phone_number=data.phone).first()
    if not user:
        raise HTTPException(404,"User not found")
    return update_user_role(RoleUpdate(user_id=user.id,role="MODERATOR"),current_user,db)


@app.post("/api/admin/assign-moderator")
def assign_moderator(data: AssignModerator, current_user: models.User = Depends(require_role(["ADMIN"])), db: Session = Depends(get_db)):
    customer = db.query(models.User).filter(models.User.id == data.customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")

    moderator = db.query(models.User).filter(models.User.id == data.moderator_id).first()
    if not moderator:
        raise HTTPException(status_code=404, detail="Moderator not found")
    if moderator.role not in ["MODERATOR", "ADMIN"] or moderator.is_blacklisted:
        raise HTTPException(status_code=400, detail="Target user is not a moderator or admin")

    customer.assigned_moderator_id = moderator.id
    db.commit()
    db.refresh(customer)
    return {"message": "Moderator assigned successfully", "customer_id": customer.id, "moderator_id": customer.assigned_moderator_id}


@app.get("/api/admin/moderators")
def list_moderators(current_user: models.User = Depends(require_role(["ADMIN", "MODERATOR"])), db: Session = Depends(get_db)):
    moderators = db.query(models.User).filter(models.User.role.in_(["MODERATOR", "ADMIN"])).all()
    return [{"id": m.id, "email": m.email, "phone_number": m.phone_number, "role": m.role} for m in moderators]


@app.get("/api/admin/customers")
def list_customers(current_user: models.User = Depends(require_role(["ADMIN"])), db: Session = Depends(get_db)):
    customers = db.query(models.User).filter(models.User.role == "CUSTOMER").limit(200).all()
    return [{
        "id": c.id, "email": c.email, "phone_number": c.phone_number,
        "assigned_moderator_id": c.assigned_moderator_id,
        "is_blacklisted": bool(c.is_blacklisted), "blacklist_reason": c.blacklist_reason
    } for c in customers]


@app.get("/api/admin/users")
def list_all_users(current_user: models.User = Depends(require_role(["ADMIN"])), db: Session = Depends(get_db)):
    """Full user list with roles — feeds the (hidden) role-management panel. ADMIN only."""
    users = db.query(models.User).order_by(models.User.created_at.asc()).limit(200).all()
    return [{
        "id": u.id,
        "phone_number": u.phone_number,
        "email": u.email,
        "role": u.role,
        "is_blacklisted": bool(u.is_blacklisted)
    } for u in users]


@app.put("/api/admin/customers/{user_id}/blacklist")
def blacklist_customer(user_id: str, data: BlacklistRequest, current_user: models.User = Depends(require_role(["ADMIN"])), db: Session = Depends(get_db)):
    target = db.query(models.User).filter(models.User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if target.role == "ADMIN":
        raise HTTPException(status_code=400, detail="Cannot blacklist an admin")
    target.is_blacklisted = True
    target.blacklist_reason = data.reason
    db.commit()
    return {"message": "Customer blacklisted", "user_id": target.id, "is_blacklisted": True}


@app.put("/api/admin/customers/{user_id}/unblacklist")
def unblacklist_customer(user_id: str, current_user: models.User = Depends(require_role(["ADMIN"])), db: Session = Depends(get_db)):
    target = db.query(models.User).filter(models.User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    target.is_blacklisted = False
    target.blacklist_reason = None
    db.commit()
    return {"message": "Customer reinstated", "user_id": target.id, "is_blacklisted": False}


# -------------------------------
# Help / Support channel (Customer <-> Admin only)
# -------------------------------

def _serialize_help(m: models.HelpMessage):
    return {
        "id": m.id,
        "user_id": m.user_id,
        "sender_role": m.sender_role,
        "message": m.message,
        "is_resolved": bool(m.is_resolved),
        "created_at": m.created_at.isoformat() if m.created_at else None,
    }


@app.post("/api/help")
def send_help_message(data: HelpMessageCreate, current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Customer raises / continues a support thread. Heard by admins only."""
    msg = models.HelpMessage(
        user_id=current_user.id,
        sender_role="CUSTOMER",
        message=data.message,
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return _serialize_help(msg)


@app.get("/api/help/messages")
def get_my_help_messages(current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Customer reads their own support thread (their messages + admin replies)."""
    msgs = db.query(models.HelpMessage).filter(
        models.HelpMessage.user_id == current_user.id
    ).order_by(models.HelpMessage.created_at.desc()).limit(100).all()
    return [_serialize_help(m) for m in reversed(msgs)]


@app.get("/api/admin/help")
def get_help_inbox(current_user: models.User = Depends(require_role(["ADMIN"])), db: Session = Depends(get_db), limit: int = Query(50,ge=1,le=100), offset: int = Query(0,ge=0)):
    aggregate=db.query(models.HelpMessage.user_id.label("uid"),func.max(models.HelpMessage.created_at).label("latest"),func.max(case(((models.HelpMessage.sender_role=="CUSTOMER") & (models.HelpMessage.is_resolved==False),1),else_=0)).label("open")).group_by(models.HelpMessage.user_id).subquery()
    ranked=db.query(models.HelpMessage.id.label("mid"),models.HelpMessage.user_id.label("uid"),func.row_number().over(partition_by=models.HelpMessage.user_id,order_by=(models.HelpMessage.created_at.desc(),models.HelpMessage.id.desc())).label("rn")).subquery()
    rows=db.query(models.HelpMessage,models.User,aggregate.c.open).join(ranked,(models.HelpMessage.id==ranked.c.mid)&(ranked.c.rn==1)).join(aggregate,aggregate.c.uid==models.HelpMessage.user_id).join(models.User,models.User.id==models.HelpMessage.user_id).order_by(aggregate.c.open.desc(),aggregate.c.latest.desc()).offset(offset).limit(limit).all()
    return [{"user_id":u.id,"messages":[_serialize_help(m)],"open":bool(opened),"customer_phone":u.phone_number,"customer_email":u.email} for m,u,opened in rows]


@app.get("/api/admin/help/summary")
def get_help_summary(current_user: models.User = Depends(require_role(["ADMIN"])), db: Session = Depends(get_db)):
    total=db.query(func.count(func.distinct(models.HelpMessage.user_id))).scalar() or 0
    opened=db.query(func.count(func.distinct(models.HelpMessage.user_id))).filter(models.HelpMessage.sender_role=="CUSTOMER",models.HelpMessage.is_resolved==False).scalar() or 0
    return {"total_threads":total,"open_threads":opened}


@app.post("/api/admin/help/{user_id}/reply")
def reply_help_message(user_id: str, data: HelpMessageCreate, current_user: models.User = Depends(require_role(["ADMIN"])), db: Session = Depends(get_db)):
    target = db.query(models.User).filter(models.User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="Customer not found")
    msg = models.HelpMessage(
        user_id=user_id,
        sender_role="ADMIN",
        message=data.message,
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return _serialize_help(msg)


@app.put("/api/admin/help/{user_id}/resolve")
def resolve_help_thread(user_id: str, current_user: models.User = Depends(require_role(["ADMIN"])), db: Session = Depends(get_db)):
    db.query(models.HelpMessage).filter(models.HelpMessage.user_id == user_id).update({"is_resolved": True})
    db.commit()
    return {"message": "Help thread marked resolved", "user_id": user_id}


# -------------------------------
# Maintenance mode (ADMIN) + public status
# -------------------------------

@app.get("/api/status")
def public_status(db: Session = Depends(get_db)):
    setting=db.get(models.AppSetting,1)
    return {"maintenance_mode":bool(setting and setting.maintenance_mode),"orders_enabled":setting.orders_enabled if setting else True,"dev_auth_enabled":dev_auth_enabled(),"research_available":research_enabled()}


@app.get("/api/admin/settings/maintenance")
def get_maintenance(current_user: models.User = Depends(require_role(["ADMIN"])), db: Session = Depends(get_db)):
    setting = db.query(models.AppSetting).first()
    return {"maintenance_mode": bool(getattr(setting, "maintenance_mode", False)) if setting else False}


@app.put("/api/admin/settings/maintenance")
def update_maintenance(data: MaintenanceUpdate, current_user: models.User = Depends(require_role(["ADMIN"])), db: Session = Depends(get_db)):
    setting = db.query(models.AppSetting).first()
    if not setting:
        setting = models.AppSetting(id=1, orders_enabled=True, maintenance_mode=data.maintenance_mode)
        db.add(setting)
    else:
        setting.maintenance_mode = data.maintenance_mode
    db.commit()
    return {"message": "Maintenance mode updated", "maintenance_mode": data.maintenance_mode}


@app.get("/api/moderator/queue")
def get_moderator_queue(status_filter: Optional[str] = None, current_user: models.User = Depends(require_role(["ADMIN","MODERATOR"])), db: Session = Depends(get_db), limit: int = Query(50,ge=1,le=100), offset: int = Query(0,ge=0)):
    query = db.query(models.Order).options(joinedload(models.Order.user),selectinload(models.Order.items))
    query = query.filter(models.Order.status == status_filter) if status_filter else query.filter(models.Order.status.in_(ACTIVE_STATUSES))
    if current_user.role=="MODERATOR":
        query=query.filter(or_(models.Order.assigned_moderator_id==None,models.Order.assigned_moderator_id==current_user.id))
    results=[]
    for o in query.order_by(models.Order.created_at.asc(),models.Order.id.asc()).offset(offset).limit(limit).all():
        needs_claim=current_user.role=='MODERATOR' and o.assigned_moderator_id is None and o.user_id!=current_user.id
        entry={**serialize_order(o,current_user),'order_id':o.id,'customer_id':o.user_id,
               'customer_name':(f"{o.user.first_name or ''} {o.user.last_name or ''}".strip() or 'Customer') if o.user else 'Unknown',
               'customer_phone':o.user.phone_number if o.user and not needs_claim else None,'requires_claim':needs_claim}
        if needs_claim:
            for key in ('delivery_street','delivery_city','delivery_postal_code','address_id','customer_paid','payment_reference','refund_reference','payment_uri'):
                entry.pop(key,None)
        results.append(entry)
    return results


@app.put("/api/moderator/orders/{order_id}/claim")
def claim_order(order_id: str, current_user: models.User = Depends(require_role(["ADMIN","MODERATOR"])), db: Session = Depends(get_db)):
    row=load_order(db,order_id)
    require_state(row,{"pending_review","reviewing"})
    if row.assigned_moderator_id and row.assigned_moderator_id!=current_user.id and current_user.role!="ADMIN":
        raise HTTPException(403,"Order is claimed by another moderator")
    if row.assigned_moderator_id==current_user.id and row.status=="reviewing":
        return serialize_order(row,current_user)
    change_order(db,row,assigned_moderator_id=current_user.id,status="reviewing",claimed_at=row.claimed_at or utcnow())
    order_message(db,row,"A concierge has claimed this order.")
    db.commit()
    return {**serialize_order(row,current_user),"order_id":row.id}


@app.post("/api/moderator/orders/{order_id}/preview-quote")
def preview_quote(order_id: str, data: ManualPricesEntry, current_user: models.User = Depends(require_role(["ADMIN","MODERATOR"])), db: Session = Depends(get_db)):
    row=load_order(db,order_id)
    staff_access(row,current_user)
    require_state(row,{"pending_review","reviewing","awaiting_customer"})
    items=quote_items(row,data.items or [])
    result=preview_totals(items,delivery_thresholds(db))
    return {**result,"revision":row.revision,"order_id":row.id,"final_price":float(final_amount(result["subtotal"],result["delivery_fee"],result["platform_fee"],0,0,0))}


@app.get("/api/moderator/orders/{order_id}/research-location")
def research_location_plan(order_id: str, current_user: models.User = Depends(require_role(["ADMIN","MODERATOR"])), db: Session = Depends(get_db)):
    from core.catalog_research import location_plan
    row=load_order(db,order_id);staff_access(row,current_user)
    require_state(row,{"pending_review","reviewing"})
    return location_plan(row.id,row.revision,row.delivery_postal_code)


@app.post("/api/moderator/orders/{order_id}/research-evidence")
def import_research_evidence(order_id: str, data: ResearchCaptureSubmission, current_user: models.User = Depends(require_role(["ADMIN","MODERATOR"])), db: Session = Depends(get_db)):
    from core.catalog_research import BrowserCaptureClient, research_catalog, ResearchUnavailable, capture_location
    row=load_order(db,order_id);staff_access(row,current_user)
    require_state(row,{"pending_review","reviewing"})
    if row.revision!=data.revision:raise HTTPException(409,'Order changed. Copy a new research context and recapture.')
    try:
        client=BrowserCaptureClient(data.captures)
        for context in client.contexts.values():
            if context.get('order_id')!=row.id or context.get('revision')!=row.revision or context.get('postal_code')!=row.delivery_postal_code:
                raise ResearchUnavailable('Evidence must be captured with this order ID, revision and postcode')
        if any(capture_location(context,row.delivery_postal_code)['status']=='needs_location' for context in client.locations.values()):
            raise ResearchUnavailable('Select the retailer location and confirm this customer postcode before importing')
        draft=research_catalog([{'item_id':i.id,'name':i.name,'quantity':i.quantity} for i in row.items],row.delivery_postal_code,client)
        if any(d.get('status')=='unavailable' for d in draft['diagnostics']):
            raise ResearchUnavailable('Capture has a location mismatch or unavailable source. Check the retailer location and recapture.')
    except (ValueError,TypeError) as exc:
        raise HTTPException(422,str(exc)) from exc
    try:existing=json.loads(row.manual_prices or '{}')
    except ValueError:raise HTTPException(409,'Existing pricing draft is invalid; review it before importing evidence')
    if not isinstance(existing,dict):raise HTTPException(409,'Existing pricing draft is invalid')
    existing['research_draft']=draft
    encoded=json.dumps(existing)
    if len(encoded.encode())>200000:raise HTTPException(422,'Research evidence exceeds the supported size')
    change_order(db,row,manual_prices=encoded,assigned_worker_type='HUMAN',ai_stopped_at=utcnow(),mode='HYBRID' if row.mode=='AI' else row.mode)
    db.commit()
    return serialize_order(row,current_user)


@app.post("/api/moderator/orders/{order_id}/price")
def enter_prices(order_id: str, data: QuoteSubmission, current_user: models.User = Depends(require_role(["ADMIN","MODERATOR"])), db: Session = Depends(get_db)):
    row=load_order(db,order_id)
    staff_access(row,current_user)
    require_state(row,{"pending_review","reviewing","awaiting_customer"})
    if data.revision!=row.revision:
        raise HTTPException(409,"Quote changed. Preview again")
    items=quote_items(row,data.items)
    subtotal=sum((money(i["line_total"]) for i in items),Decimal(0))
    if money(data.subtotal)!=subtotal:
        raise HTTPException(422,"Subtotal does not match the item prices")
    primary=preview_totals(items,delivery_thresholds(db))["store"]
    if store_id(data.store)!=primary:
        raise HTTPException(422,"Primary store does not match this basket")
    final=final_amount(subtotal,data.delivery_fee,data.platform_fee,data.service_fee,data.store_discount,data.snapsave_discount)
    if money(data.final_price)!=final:
        raise HTTPException(422,"Final price does not reconcile")
    # Store cost and actual profit are recorded only when payment/fulfillment are verified.
    change_order(db,row,store=primary,subtotal=subtotal,delivery_fee=money(data.delivery_fee),platform_fee=money(data.platform_fee),service_fee=money(data.service_fee),store_discount=money(data.store_discount),snapsave_discount=money(data.snapsave_discount),final_price=final,savings=money(data.store_discount)+money(data.snapsave_discount),profit=0,first_response_at=row.first_response_at or utcnow(),manual_prices=json.dumps({"items":items}),is_ai_priced=False,ai_stopped_at=utcnow(),status="awaiting_customer",quote_expires_at=utcnow()+timedelta(minutes=15))
    item_map={i.id:i for i in row.items}
    for entry in items:
        target=item_map[entry["item_id"]]
        target.line_total=money(entry["line_total"])
        target.unit_price=Decimal(str(entry["line_total"]))/target.quantity
        target.store=entry["store"]
    order_message(db,row,quote_text(row,items),kind="quote")
    db.commit()
    return {**serialize_order(row,current_user),"order_id":row.id}


@app.put("/api/customer/orders/{order_id}/confirm")
def confirm_order(order_id: str, data: QuoteConfirmation, current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    row=load_order(db,order_id)
    if row.user_id!=current_user.id:
        raise HTTPException(403,"Not your order")
    if row.status=="awaiting_payment" and data.revision==row.revision-1:
        return {**serialize_order(row,current_user),"order_id":row.id}
    require_state(row,{"awaiting_customer"})
    if data.revision!=row.revision or not row.quote_expires_at or row.quote_expires_at<utcnow():
        raise HTTPException(409,"Quote changed or expired. Ask your concierge for a fresh quote")
    if not os.getenv("UPI_ID"):
        raise HTTPException(503,"Payment details are not configured. Contact your concierge")
    change_order(db,row,status="awaiting_payment",confirmed_at=utcnow())
    order_message(db,row,"Quote accepted.",role="CUSTOMER",sender=current_user.id)
    order_message(db,row,"Pay the exact approved amount using the payment card. Send the bank transaction reference after paying.",kind="payment")
    db.commit()
    return {**serialize_order(row,current_user),"order_id":row.id}

class PlaceOrderRequest(StrictRequest):
    eta_mins: int = Field(..., ge=1, le=1440)
    payment_reference: str = Field(..., min_length=3, max_length=128)
    customer_paid: float = Field(..., ge=0, le=9999999, allow_inf_nan=False)
    store_cost: float = Field(..., ge=0, le=9999999, allow_inf_nan=False)

@app.post("/api/moderator/orders/{order_id}/place")
def place_order_with_eta(order_id: str, data: PlaceOrderRequest, current_user: models.User = Depends(require_role(["ADMIN","MODERATOR"])), db: Session = Depends(get_db)):
    row=load_order(db,order_id)
    staff_access(row,current_user)
    if row.status in {"placed","delivered","completed"}:
        if row.payment_reference==data.payment_reference and money(row.customer_paid)==money(data.customer_paid) and money(row.store_cost)==money(data.store_cost):
            return {**serialize_order(row,current_user),"order_id":row.id}
        raise HTTPException(409,"This order was already placed with different settlement details")
    require_state(row,{"awaiting_payment"})
    if db.query(models.Order.id).filter(models.Order.payment_reference==data.payment_reference,models.Order.id!=row.id).first():
        raise HTTPException(409,"That bank reference is already recorded on another order")
    paid,cost=money(data.customer_paid),money(data.store_cost)
    if paid!=money(row.final_price):
        raise HTTPException(422,"Payment amount must match the approved quote")
    now=utcnow()
    change_order(db,row,status="placed",placed_at=now,eta_at=now+timedelta(minutes=data.eta_mins),payment_status="verified",payment_reference=data.payment_reference.strip(),payment_verified_at=now,payment_verified_by=current_user.id,customer_paid=paid,store_cost=cost,profit=paid-cost)
    order_message(db,row,f"Payment verified. Your order is placed; estimated arrival in {data.eta_mins} minutes.")
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409,"That bank reference is already recorded on another order")
    return {**serialize_order(row,current_user),"order_id":row.id}


@app.put("/api/admin/orders/{order_id}/place")
def place_order(order_id: str, data: PlaceOrderRequest, current_user: models.User = Depends(require_role(["ADMIN"])), db: Session = Depends(get_db)):
    return place_order_with_eta(order_id,data,current_user,db)


@app.put("/api/admin/orders/{order_id}/deliver")
@app.put("/api/moderator/orders/{order_id}/deliver")
def deliver_order(order_id: str, current_user: models.User = Depends(require_role(["ADMIN","MODERATOR"])), db: Session = Depends(get_db)):
    row=load_order(db,order_id)
    staff_access(row,current_user)
    if row.status in {"delivered","completed"}:
        return {**serialize_order(row,current_user),"order_id":row.id}
    require_state(row,{"placed"})
    change_order(db,row,status="delivered",delivered_at=utcnow())
    db.query(models.User).filter_by(id=row.user_id).update({models.User.completed_orders_count:func.coalesce(models.User.completed_orders_count,0)+1},synchronize_session=False)
    order_message(db,row,"Your order has been delivered. You can now rate your experience.")
    db.commit()
    return {**serialize_order(row,current_user),"order_id":row.id}


@app.put("/api/admin/orders/{order_id}/assign")
def assign_order_to_moderator(order_id: str, data: AssignModeratorToOrder, current_user: models.User = Depends(require_role(["ADMIN"])), db: Session = Depends(get_db)):
    row=load_order(db,order_id)
    require_state(row,ACTIVE_STATUSES)
    worker=db.get(models.User,data.moderator_id)
    if not worker or worker.role not in {"MODERATOR","ADMIN"} or worker.is_blacklisted:
        raise HTTPException(422,"Invalid moderator")
    values={"assigned_moderator_id":worker.id}
    if row.status=="pending_review":
        values.update(status="reviewing",claimed_at=utcnow())
    change_order(db,row,**values)
    order_message(db,row,"This order was assigned to a concierge.")
    db.commit()
    return {**serialize_order(row,current_user),"order_id":row.id}


@app.put("/api/admin/orders/{order_id}/cancel")
def cancel_order(order_id: str, current_user: models.User = Depends(require_role(["ADMIN"])), db: Session = Depends(get_db)):
    row=load_order(db,order_id)
    require_state(row,ACTIVE_STATUSES)
    refund=row.payment_status=="verified"
    reconciliation=row.status=="awaiting_payment" or row.payment_status=="reconciliation_required" or money(row.customer_paid or 0)>0
    change_order(db,row,status="cancelled",assigned_worker_type="HUMAN",mode="HUMAN",ai_stopped_at=utcnow(),payment_status="refund_required" if refund else "reconciliation_required" if reconciliation else "unpaid")
    order_message(db,row,"Your order was cancelled." + (" A refund needs reconciliation; contact support." if refund else " Any payment receipt needs bank reconciliation; contact support if you paid." if reconciliation else ""))
    db.commit()
    return {**serialize_order(row,current_user),"order_id":row.id}


@app.get("/api/chat/{customer_id}/messages")
def get_chat_messages(customer_id: str, current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db), order_id: Optional[str] = None, after_id: Optional[str] = None, limit: int = Query(100,ge=1,le=200)):
    authorize_chat(db,customer_id,order_id,current_user)
    query=db.query(models.Message).filter_by(user_id=customer_id)
    query=query.filter(models.Message.order_id==order_id) if order_id else query.filter(models.Message.order_id==None)
    if after_id:
        cursor=db.query(models.Message).filter_by(id=after_id,user_id=customer_id,order_id=order_id).first()
        if not cursor:
            raise HTTPException(422,"Invalid message cursor")
        query=query.filter(or_(models.Message.created_at>cursor.created_at,(models.Message.created_at==cursor.created_at)&(models.Message.id>cursor.id)))
        rows=query.order_by(models.Message.created_at.asc(),models.Message.id.asc()).limit(limit).all()
    else:
        rows=list(reversed(query.order_by(models.Message.created_at.desc(),models.Message.id.desc()).limit(limit).all()))
    # Conversation participation is distinct from an account's management role.
    # Normalize historical own-thread messages without rewriting stored records.
    return [{"id":m.id,"sender_id":m.sender_id,"sender_role":"CUSTOMER" if m.sender_id==customer_id and m.sender_role in {"ADMIN","MODERATOR"} and m.kind=="text" else m.sender_role,"message":m.message,"order_id":m.order_id,"kind":m.kind,"created_at":m.created_at} for m in rows]


@app.put("/api/admin/orders/{order_id}/mode")
def set_order_mode(order_id: str, data: OrderModeRequest, current_user: models.User = Depends(require_role(["ADMIN"])), db: Session = Depends(get_db)):
    row=load_order(db,order_id)
    require_state(row,{"pending_review","reviewing","awaiting_customer"})
    if data.mode not in {"HUMAN","AI","HYBRID"}:
        raise HTTPException(422,"Invalid mode")
    if data.mode!="HUMAN" and not research_enabled():
        raise HTTPException(503,"Live AI research is unavailable. Use HUMAN mode")
    if data.mode!="HUMAN":
        require_state(row,{"pending_review","reviewing"})
        require_ai_enabled(db)
        if row.manual_prices and not row.is_ai_priced:
            raise HTTPException(409,"Human prices are already recorded. Keep this ticket in human review")
    change_order(db,row,mode=data.mode,assigned_worker_type="HUMAN" if data.mode=="HUMAN" else "AI",ai_stopped_at=utcnow() if data.mode=="HUMAN" else None,ai_error=None)
    order_message(db,row,f"Ticket mode changed to {data.mode} by an administrator.")
    db.commit()
    if data.mode!="HUMAN":
        submit_ai(row.id)
        db.refresh(row)
    return {**serialize_order(row,current_user),"order_id":row.id}

@app.put("/api/admin/orders/{order_id}/delegate")
def delegate_worker(order_id: str, data: DelegateWorkerRequest, current_user: models.User = Depends(require_role(["ADMIN"])), db: Session = Depends(get_db)):
    row=load_order(db,order_id)
    require_state(row,{"pending_review","reviewing","awaiting_customer"})
    if data.assigned_worker_type not in {"HUMAN","AI"}:
        raise HTTPException(422,"Invalid worker")
    if data.assigned_worker_type=="AI" and (row.mode=="HUMAN" or not research_enabled()):
        raise HTTPException(409,"Select an available AI/HYBRID mode before delegating")
    if data.assigned_worker_type=="AI":
        require_state(row,{"pending_review","reviewing"})
        require_ai_enabled(db)
        if row.manual_prices and not row.is_ai_priced:
            raise HTTPException(409,"Human prices are already recorded")
    change_order(db,row,assigned_worker_type=data.assigned_worker_type,ai_stopped_at=utcnow() if data.assigned_worker_type=="HUMAN" else None)
    order_message(db,row,f"Worker delegated to {data.assigned_worker_type}.")
    db.commit()
    if data.assigned_worker_type=="AI":
        submit_ai(row.id)
        db.refresh(row)
    return {**serialize_order(row,current_user),"order_id":row.id}

@app.put("/api/moderator/orders/{order_id}/takeover")
def takeover_order(order_id: str, current_user: models.User = Depends(require_role(["ADMIN","MODERATOR"])), db: Session = Depends(get_db)):
    row=load_order(db,order_id)
    staff_access(row,current_user)
    require_state(row,ACTIVE_STATUSES)
    now=utcnow()
    change_order(db,row,assigned_worker_type="HUMAN",mode="HUMAN",taken_over_at=now,taken_over_by=current_user.id,ai_stopped_at=now)
    order_message(db,row,"A human concierge took over this ticket. AI work is invalidated.")
    db.commit()
    return {**serialize_order(row,current_user),"order_id":row.id}


@app.get("/api/admin/settings/ai-status")
def get_global_ai_status(db: Session = Depends(get_db)):
    setting=db.get(models.SystemSetting,"ai_enabled")
    return {"ai_enabled":bool(setting and setting.value=="true"),"research_available":research_enabled()}


@app.put("/api/admin/settings/ai-status")
def set_global_ai_status(data: AiStatusRequest, current_user: models.User = Depends(require_role(["ADMIN"])), db: Session = Depends(get_db)):
    if data.ai_enabled and not research_enabled():
        raise HTTPException(503,"No verified live research provider is enabled")
    setting=db.get(models.SystemSetting,"ai_enabled")
    if not setting:
        setting=models.SystemSetting(key="ai_enabled",value="false")
        db.add(setting)
    setting.value=str(data.ai_enabled).lower()
    # Invalidate all in-flight generations, including disable-then-enable races.
    db.query(models.Order).filter(models.Order.assigned_worker_type=="AI").update({models.Order.revision:models.Order.revision+1},synchronize_session=False)
    if not data.ai_enabled:
        for row in db.query(models.Order).filter(models.Order.assigned_worker_type=="AI",models.Order.status.in_(["pending_review","reviewing"])):
            change_order(db,row,mode="HUMAN",assigned_worker_type="HUMAN",ai_stopped_at=utcnow())
            order_message(db,row,"AI was disabled. A human concierge will review this ticket.")
    db.commit()
    return get_global_ai_status(db)


@app.post("/api/chat/{customer_id}/send")
def send_chat_message(customer_id: str, data: SendMessageRequest, current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    row=authorize_chat(db,customer_id,data.order_id,current_user)
    def replay():
        existing=db.get(models.Message,str(data.request_id)) if data.request_id else None
        if existing:
            if (existing.user_id,existing.order_id,existing.sender_id,existing.message)!=(customer_id,data.order_id,current_user.id,data.message.strip()):
                raise HTTPException(409,"Message request already used for different content")
            return {"message":"Message sent","id":existing.id}
    previous=replay()
    if previous:
        return previous
    if row:
        require_state(row,ACTIVE_STATUSES)
    if not data.message.strip():
        raise HTTPException(422,"Message cannot be empty")
    if current_user.is_blacklisted:
        raise HTTPException(403,"Your account is restricted. Use Support")
    sender_role="CUSTOMER" if current_user.id==customer_id else current_user.role
    if row and sender_role in {"MODERATOR","ADMIN"} and not row.first_response_at:
        change_order(db,row,first_response_at=utcnow())
    msg=models.Message(user_id=customer_id,order_id=data.order_id,sender_id=current_user.id,sender_role=sender_role,message=data.message.strip(),kind="text")
    if data.request_id:
        msg.id=str(data.request_id)
    db.add(msg)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        previous=replay()
        if previous:
            return previous
        raise
    return {"message":"Message sent","id":msg.id}





@app.get("/api/admin/settings/orders")
def get_order_setting(current_user: models.User = Depends(require_role(["ADMIN"])), db: Session = Depends(get_db)):
    setting = db.query(models.AppSetting).first()
    enabled = setting.orders_enabled if setting else True
    return {"orders_enabled": enabled}


@app.put("/api/admin/settings/orders")
def update_order_setting(data: AppSettingUpdate, current_user: models.User = Depends(require_role(["ADMIN"])), db: Session = Depends(get_db)):
    setting = db.query(models.AppSetting).first()
    if not setting:
        setting = models.AppSetting(id=1, orders_enabled=data.orders_enabled)
        db.add(setting)
    else:
        setting.orders_enabled = data.orders_enabled
    db.commit()
    return {"message": "Global order switch updated successfully", "orders_enabled": setting.orders_enabled}


@app.get("/api/admin/delivery-config")
def get_delivery_config(current_user: models.User = Depends(require_role(["ADMIN"])), db: Session = Depends(get_db)):
    return delivery_thresholds(db)

@app.put("/api/admin/delivery-config")
def update_delivery_config(data: DeliveryConfig, current_user: models.User = Depends(require_role(["ADMIN"])), db: Session = Depends(get_db)):
    values={store_id(k):float(money(v)) for k,v in data.thresholds.items()}
    row=db.get(models.SystemSetting,"delivery_thresholds")
    if not row:
        row=models.SystemSetting(key="delivery_thresholds",value="{}")
        db.add(row)
    row.value=json.dumps(values)
    db.commit()
    return {"message":"Delivery thresholds saved"}


@app.get("/api/admin/dashboard/metrics")
def get_dashboard_metrics(current_user: models.User = Depends(require_role(["ADMIN", "MODERATOR"])), db: Session = Depends(get_db)):
    today_start = datetime.now(ZoneInfo("Asia/Kolkata")).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(ZoneInfo("UTC")).replace(tzinfo=None)

    orders_today = db.query(models.Order).filter(models.Order.created_at >= today_start).count()

    revenue_today = db.query(func.sum(models.Order.customer_paid)).filter(
        models.Order.status.in_(["placed", "delivered", "completed"]),
        models.Order.payment_verified_at >= today_start
    ).scalar() or 0.0

    profit_today = db.query(func.sum(models.Order.profit)).filter(
        models.Order.status.in_(["placed", "delivered", "completed"]),
        models.Order.payment_verified_at >= today_start
    ).scalar() or 0.0

    total_customers = db.query(models.User).filter(models.User.role == "CUSTOMER").count()

    total_savings = db.query(func.sum(models.Order.savings)).filter(models.Order.status.in_(["delivered","completed"])).scalar() or 0.0

    # Task 6: Operational Dashboard counts
    orders_pending_review = db.query(models.Order).filter(models.Order.status == "pending_review").count()
    orders_awaiting_customer = db.query(models.Order).filter(models.Order.status == "awaiting_customer").count()
    orders_confirmed = db.query(models.Order).filter(models.Order.status.in_(["confirmed", "awaiting_payment"])).count()
    orders_delivered = db.query(models.Order).filter(models.Order.status == "delivered").count()

    total_revenue = db.query(func.sum(models.Order.customer_paid)).filter(
        models.Order.status.in_(["placed", "delivered", "completed"])
    ).scalar() or 0.0

    total_profit = db.query(func.sum(models.Order.profit)).filter(
        models.Order.status.in_(["placed", "delivered", "completed"])
    ).scalar() or 0.0

    # Task 3: Moderator Dashboard metrics
    from sqlalchemy.orm import joinedload
    active_statuses = list(ACTIVE_STATUSES)
    active=db.query(models.Order).filter(models.Order.status.in_(active_statuses))
    if current_user.role=="MODERATOR":
        active=active.filter(or_(models.Order.assigned_moderator_id==None,models.Order.assigned_moderator_id==current_user.id))
    active_tickets=active.count()
    claimed_tickets=active.filter(models.Order.assigned_moderator_id!=None).count()
    pending_tickets=active_tickets-claimed_tickets

    avg_response_time = average_seconds(db,models.Order.first_response_at)

    return {
        "orders_today": int(orders_today),
        "orders_pending_review": int(orders_pending_review),
        "orders_awaiting_customer": int(orders_awaiting_customer),
        "orders_confirmed": int(orders_confirmed),
        "orders_delivered": int(orders_delivered),
        "revenue_today": float(revenue_today),
        "profit_today": float(profit_today),
        "revenue": float(total_revenue),
        "profit": float(total_profit),
        "total_customers": int(total_customers),
        "total_savings_delivered": float(total_savings),

        "active_tickets": int(active_tickets),
        "claimed_tickets": int(claimed_tickets),
        "pending_tickets": int(pending_tickets),
        "avg_response_time": float(avg_response_time)
    }


@app.put("/api/admin/orders/{order_id}/financials")
def update_order_financials(order_id: str, data: OrderFinancialsUpdate, current_user: models.User = Depends(require_role(["ADMIN"])), db: Session = Depends(get_db)):
    row=load_order(db,order_id)
    require_state(row,{"placed","delivered","completed"})
    if money(data.customer_paid)!=money(row.customer_paid):
        raise HTTPException(422,"Recorded payment cannot be altered through cost correction")
    change_order(db,row,store_cost=money(data.store_cost),profit=money(row.customer_paid)-money(data.store_cost))
    order_message(db,row,"An administrator corrected the recorded fulfillment cost.")
    db.commit()
    return serialize_order(row,current_user)


@app.put("/api/auth/profile")
def update_profile(data: ProfileUpdate, current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    email=data.email.strip().lower()
    if db.query(models.User.id).filter(models.User.email==email,models.User.id!=current_user.id).first():
        raise HTTPException(409,"Email is already associated with another account")
    current_user.first_name=data.first_name.strip()
    current_user.last_name=data.last_name.strip()
    current_user.email=email
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409,"Email is already associated with another account")
    return {"first_name":current_user.first_name,"last_name":current_user.last_name,"email":current_user.email}


@app.get("/api/admin/dashboard/beta-metrics")
def get_beta_metrics(current_user: models.User = Depends(require_role(["ADMIN", "MODERATOR"])), db: Session = Depends(get_db)):
    total_beta_users = db.query(models.User).filter(models.User.role == "CUSTOMER").count()
    orders_submitted = db.query(models.Order).count()
    orders_completed = db.query(models.Order).filter(models.Order.status.in_(["delivered", "completed"])).count()

    avg_first_response_time=average_seconds(db,models.Order.first_response_at)
    avg_confirm_time=average_seconds(db,models.Order.confirmed_at)

    # Completed/placed order aggregates using SQL
    completed_orders_count = db.query(models.Order).filter(models.Order.status.in_(["placed", "delivered", "completed"])).count()
    profit_sum = db.query(func.sum(models.Order.profit)).filter(
        models.Order.status.in_(["placed", "delivered", "completed"])
    ).scalar() or 0.0
    avg_profit = float(profit_sum) / completed_orders_count if completed_orders_count > 0 else 0.0

    savings_sum = db.query(func.sum(models.Order.savings)).filter(
        models.Order.status.in_(["delivered", "completed"])
    ).scalar() or 0.0
    avg_savings = float(savings_sum) / orders_completed if orders_completed > 0 else 0.0

    active_moderators = db.query(models.User).filter(models.User.role.in_(["MODERATOR", "ADMIN"])).count()

    return {
        "total_beta_users": total_beta_users,
        "orders_submitted": orders_submitted,
        "orders_completed": orders_completed,
        "avg_first_response_time": avg_first_response_time,
        "avg_confirm_time": avg_confirm_time,
        "avg_profit_per_order": avg_profit,
        "avg_savings_delivered": avg_savings,
        "active_moderators": active_moderators
    }


@app.post("/api/feedback", status_code=status.HTTP_201_CREATED)
def submit_feedback(data: FeedbackCreate, current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    row=load_order(db,data.order_id)
    if row.user_id!=current_user.id:
        raise HTTPException(403,"Not your order")
    require_state(row,{"delivered","completed"})
    if db.query(models.Feedback.id).filter_by(order_id=row.id).first():
        raise HTTPException(409,"This order already has feedback")
    change_order(db,row,status="completed",completed_at=row.completed_at or utcnow())
    feedback=models.Feedback(**data.model_dump(),user_id=current_user.id)
    db.add(feedback)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409,"This order already has feedback")
    return feedback


@app.get("/api/admin/feedback")
def get_all_feedback(current_user: models.User = Depends(require_role(["ADMIN"])), db: Session = Depends(get_db)):
    from sqlalchemy.orm import joinedload
    feedbacks = db.query(models.Feedback).options(joinedload(models.Feedback.user)).order_by(models.Feedback.created_at.desc()).limit(100).all()
    results = []
    for f in feedbacks:
        cust = f.user
        results.append({
            "id": f.id,
            "order_id": f.order_id,
            "customer_phone": cust.phone_number if cust else "Unknown",
            "rating": f.rating,
            "what_went_well": f.what_went_well,
            "what_was_confusing": f.what_was_confusing,
            "would_use_again": f.would_use_again,
            "created_at": f.created_at.isoformat() if f.created_at else None
        })
    return results


@app.post("/api/moderator/incidents", status_code=status.HTTP_201_CREATED)
def log_incident(data: IncidentCreate, current_user: models.User = Depends(require_role(["ADMIN", "MODERATOR"])), db: Session = Depends(get_db)):
    if data.order_id:
        order = db.query(models.Order).filter(models.Order.id == data.order_id).first()
        if not order:
            raise HTTPException(status_code=404, detail="Order not found")
        staff_access(order,current_user)

    incident = models.Incident(
        order_id=data.order_id,
        moderator_id=current_user.id,
        incident_type=data.incident_type,
        notes=data.notes
    )
    db.add(incident)
    db.commit()
    db.refresh(incident)
    return incident


@app.get("/api/admin/incidents")
def list_incidents(current_user: models.User = Depends(require_role(["ADMIN", "MODERATOR"])), db: Session = Depends(get_db)):
    from sqlalchemy.orm import joinedload
    query=db.query(models.Incident).options(joinedload(models.Incident.moderator))
    if current_user.role=="MODERATOR":
        query=query.filter_by(moderator_id=current_user.id)
    incidents = query.order_by(models.Incident.created_at.desc()).limit(100).all()
    results = []
    for inc in incidents:
        mod = inc.moderator
        results.append({
            "id": inc.id,
            "order_id": inc.order_id,
            "moderator_phone": mod.phone_number if mod else "Unknown",
            "incident_type": inc.incident_type,
            "notes": inc.notes,
            "created_at": inc.created_at.isoformat() if inc.created_at else None
        })
    return results
def load_order(db, order_id):
    row=db.query(models.Order).options(selectinload(models.Order.items)).filter_by(id=order_id).first()
    if not row:
        raise HTTPException(404,"Order not found")
    return row

def serialize_address(row):
    return {"id":row.id,"title":row.title,"street_address":row.street_address,"city":row.city,"state":row.state,"postal_code":row.postal_code,"is_default":row.is_default,"latitude":float(row.latitude) if row.coordinates_verified else None,"longitude":float(row.longitude) if row.coordinates_verified else None}

def serialize_order(row, viewer=None):
    result={k:getattr(row,k) for k in ("id","user_id","address_id","store","status","mode","assigned_worker_type","is_ai_priced","assigned_moderator_id","revision","payment_status","payment_reference","refund_reference","ai_error","manual_prices","delivery_street","delivery_city","delivery_postal_code")}
    for k in ("subtotal","delivery_fee","platform_fee","service_fee","store_discount","snapsave_discount","final_price","savings","customer_paid","store_cost","profit"):
        result[k]=float(getattr(row,k) or 0)
    for k in ("created_at","updated_at","claimed_at","confirmed_at","placed_at","delivered_at","completed_at","eta_at","quote_expires_at","refunded_at"):
        dt=getattr(row,k)
        result[k]=dt.isoformat()+"Z" if dt else None
    result["items"]=serialize_order_items(row)
    result["payment_uri"]=payment_uri(row) if row.status=="awaiting_payment" else None
    result['requires_claim']=bool(viewer and viewer.role=='MODERATOR' and row.assigned_moderator_id is None and row.user_id!=viewer.id)
    staff_view=viewer and not viewer.is_blacklisted and (viewer.role=='ADMIN' or (viewer.role=='MODERATOR' and row.assigned_moderator_id==viewer.id))
    if viewer and not staff_view:
        for key in ("store_cost","profit","ai_error","manual_prices"):
            result.pop(key,None)
    return result

def payment_uri(row):
    from urllib.parse import urlencode
    payee=os.getenv("UPI_ID")
    if not payee:
        return None
    return "upi://pay?"+urlencode({"pa":payee,"pn":os.getenv("UPI_PAYEE_NAME","SnapSave"),"am":f"{row.final_price:.2f}","cu":"INR","tn":f"SnapSave order {row.id}","tr":row.id})

def delivery_thresholds(db):
    row=db.get(models.SystemSetting,"delivery_thresholds")
    try:
        saved=json.loads(row.value) if row else {}
        return {s:float(money(saved.get(s,saved.get("swiggy",199) if s=="instamart" else 199))) for s in STORES}
    except (ValueError,TypeError):
        raise HTTPException(503,"Delivery settings need administrator review")

def quote_text(row,items):
    return "Your itemised quote is ready:\n"+"\n".join(f"- {i['quantity']}× {i['name']}: ₹{i['line_total']:.2f} ({i['store']})" for i in items)+f"\n\nSubtotal: ₹{row.subtotal:.2f}\nDelivery: ₹{row.delivery_fee:.2f}\nPlatform fee: ₹{row.platform_fee:.2f}\nService fee: ₹{row.service_fee:.2f}\nStore discount: -₹{row.store_discount:.2f}\nSnapSave discount: -₹{row.snapsave_discount:.2f}\nFinal price: ₹{row.final_price:.2f}\nQuote valid for 15 minutes."

def authorize_chat(db,customer_id,order_id,user):
    if user.is_blacklisted and user.id!=customer_id:
        raise HTTPException(403,'Staff access is restricted')
    if user.role=="CUSTOMER" and user.id!=customer_id:
        raise HTTPException(403,"Not your conversation")
    if not db.get(models.User,customer_id):
        raise HTTPException(404,"Customer not found")
    if order_id:
        row=load_order(db,order_id)
        if row.user_id!=customer_id:
            raise HTTPException(403,"Order does not belong to this conversation")
        read_access(row,user)
        return row
    if user.role!="ADMIN" and user.id!=customer_id:
        raise HTTPException(403,"Select an assigned order to chat")
    return None

from concurrent.futures import ThreadPoolExecutor
_ai_executor=ThreadPoolExecutor(max_workers=2,thread_name_prefix="concierge")
_ai_jobs=set()
_ai_jobs_lock=threading.Lock()

def require_ai_enabled(db):
    setting=db.get(models.SystemSetting,"ai_enabled")
    if not setting or setting.value!="true":
        raise HTTPException(409,"Enable the global AI switch before assigning research")

def ai_fallback(order_id, reason):
    from database import SessionLocal
    with SessionLocal() as db:
        row=db.get(models.Order,order_id)
        if row and row.assigned_worker_type=="AI" and row.status in {"pending_review","reviewing"}:
            change_order(db,row,mode="HUMAN",assigned_worker_type="HUMAN",ai_stopped_at=utcnow(),ai_error=reason)
            order_message(db,row,reason+" A human concierge will review this ticket.")
            db.commit()

def submit_ai(order_id):
    with _ai_jobs_lock:
        if order_id in _ai_jobs:
            return
        busy=len(_ai_jobs)>=20
        if not busy:
            _ai_jobs.add(order_id)
    if busy:
        ai_fallback(order_id,"Research capacity is full.")
        return
    def work():
        from database import SessionLocal
        try:
            with SessionLocal() as db:
                AI_CONCIERGE_PROVIDER.process_ticket(order_id,db)
        except Exception:
            logging.exception("Concierge worker failed for order %s",order_id)
            ai_fallback(order_id,"Research could not be completed.")
        finally:
            with _ai_jobs_lock:
                _ai_jobs.discard(order_id)
    if _ai_executor is None:
        with _ai_jobs_lock:
            _ai_jobs.discard(order_id)
        ai_fallback(order_id,"Research is shutting down.")
        return
    try:
        _ai_executor.submit(work)
    except RuntimeError:
        with _ai_jobs_lock:
            _ai_jobs.discard(order_id)
        ai_fallback(order_id,"Research is shutting down.")

def stop_workers():
    global _ai_executor
    if _ai_executor is not None:
        _ai_executor.shutdown(wait=True,cancel_futures=True)
        _ai_executor=None
    with _ai_jobs_lock:
        _ai_jobs.clear()

@app.get("/api/orders/{order_id}/payment-qr")
def payment_qr(order_id: str, current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    from io import BytesIO
    from fastapi.responses import Response
    row=load_order(db,order_id)
    read_access(row,current_user)
    require_state(row,{"awaiting_payment"})
    uri=payment_uri(row)
    if not uri:
        raise HTTPException(503,"Payment is not configured")
    import qrcode
    buffer=BytesIO()
    qrcode.make(uri).save(buffer,format="PNG")
    return Response(buffer.getvalue(),media_type="image/png",headers={"Cache-Control":"no-store"})

@app.get("/api/admin/help/{user_id}/messages")
def staff_help_messages(user_id: str, current_user: models.User = Depends(require_role(["ADMIN"])), db: Session = Depends(get_db), limit: int = Query(100,ge=1,le=200)):
    rows=db.query(models.HelpMessage).filter_by(user_id=user_id).order_by(models.HelpMessage.created_at.desc(),models.HelpMessage.id.desc()).limit(limit).all()
    return [_serialize_help(m) for m in reversed(rows)]

class RefundVerification(StrictRequest):
    reference: str = Field(...,min_length=3,max_length=128)
    amount: float = Field(...,ge=0,allow_inf_nan=False)

class OrderPaymentReconciliation(StrictRequest):
    received: bool
    reference: Optional[str] = Field(None,min_length=3,max_length=128)
    amount: Optional[float] = Field(None,gt=0,le=9999999,allow_inf_nan=False)

@app.post("/api/admin/orders/{order_id}/reconcile-payment")
def reconcile_order_payment(order_id: str, data: OrderPaymentReconciliation, current_user: models.User = Depends(require_role(["ADMIN"])), db: Session = Depends(get_db)):
    row=load_order(db,order_id)
    require_state(row,{"cancelled","placed","delivered","completed"})
    reconciled_status="refund_required" if row.status=="cancelled" else "verified"
    if data.received and row.payment_status==reconciled_status and row.payment_reference==data.reference and money(row.customer_paid)==money(data.amount):
        return serialize_order(row,current_user)
    if row.payment_status!="reconciliation_required" and not (row.payment_status=="unpaid" and row.confirmed_at):
        raise HTTPException(409,"This payment was already reconciled or the quote was never accepted")
    if data.received:
        if not data.reference or data.amount is None:
            raise HTTPException(422,"Enter the verified bank reference and actual received amount")
        if db.query(models.Order.id).filter(models.Order.payment_reference==data.reference,models.Order.id!=row.id).first():
            raise HTTPException(409,"That bank reference is already recorded on another order")
        amount=money(data.amount)
        change_order(db,row,payment_status=reconciled_status,payment_reference=data.reference,customer_paid=amount,payment_verified_at=utcnow(),payment_verified_by=current_user.id,profit=amount-money(row.store_cost or 0) if row.status!="cancelled" else 0)
        order_message(db,row,"A bank payment was verified for this order."+(" A refund is required." if row.status=="cancelled" else " The legacy settlement record was reconciled."))
    else:
        if data.reference is not None or data.amount is not None:
            raise HTTPException(422,"Payment details conflict with no payment received")
        previous_amount=money(row.customer_paid or 0)
        previous_reference=row.payment_reference or "none"
        change_order(db,row,payment_status="unpaid",customer_paid=0,payment_reference=None,payment_verified_at=None,payment_verified_by=None,profit=-money(row.store_cost or 0) if row.status!="cancelled" else 0)
        order_message(db,row,f"Bank reconciliation was completed; no payment receipt was found. Previously recorded amount: ₹{previous_amount:.2f}; reference: {previous_reference}.")
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409,"That bank reference is already recorded on another order")
    return serialize_order(row,current_user)

@app.post("/api/admin/orders/{order_id}/refund")
def record_refund(order_id: str, data: RefundVerification, current_user: models.User = Depends(require_role(["ADMIN"])), db: Session = Depends(get_db)):
    row=load_order(db,order_id)
    require_state(row,{"cancelled"})
    if row.payment_status!="refund_required":
        raise HTTPException(409,"This order does not need a refund")
    if money(data.amount)!=money(row.customer_paid):
        raise HTTPException(422,"Refund must match the recorded payment")
    change_order(db,row,payment_status="refunded",refund_reference=data.reference,refunded_at=utcnow())
    order_message(db,row,"Your refund was verified by an administrator. Reference: "+data.reference)
    db.commit()
    return serialize_order(row,current_user)

def average_seconds(db,column):
    if db.bind.dialect.name=="sqlite":
        delta=(func.julianday(column)-func.julianday(models.Order.created_at))*86400
    else:
        delta=func.extract("epoch",column-models.Order.created_at)
    return float(db.query(func.avg(delta)).filter(column!=None).scalar() or 0)
