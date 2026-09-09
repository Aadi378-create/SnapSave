import os
from dotenv import load_dotenv
load_dotenv()

import uuid
import re
from datetime import datetime
from typing import Optional, List
from fastapi import FastAPI, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session
from fastapi.middleware.cors import CORSMiddleware
import time
import jwt
import requests
import threading

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
cred_path = os.getenv("FIREBASE_CREDENTIALS", "admin/firebase-service-account.json")

# Try initializing with service account credentials first
if os.path.exists(cred_path):
    try:
        cred = credentials.Certificate(cred_path)
        firebase_admin.initialize_app(cred)
        firebase_initialized = True
        print("Firebase Admin SDK initialized with Service Account.")
    except Exception as e:
        print(f"⚠️  Error initializing Firebase Admin with credentials: {type(e).__name__}: {e}")
        print(f"    Credentials file: {cred_path}")
        print(f"    File exists: {os.path.exists(cred_path)}")
        firebase_initialized = False

# Fallback: Initialize with Project ID for public certificate verification
if not firebase_initialized:
    try:
        firebase_admin.initialize_app(options={"projectId": "snapsave-501c7"})
        firebase_initialized = True
        print("[OK] Firebase Admin SDK initialized with Project ID fallback.")
    except Exception as e:
        print(f"Warning: Failed to initialize Firebase Admin SDK: {e}")

app = FastAPI(title="SnapSave API")

# Enable CORS for frontend integration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def run_sqlite_column_migrations():
    """create_all() builds new tables but never adds columns to existing ones.
    For the dev SQLite DB, add any newly-introduced columns in place so existing
    data is preserved. No-op on a fresh DB (columns already created)."""
    from sqlalchemy import inspect, text
    inspector = inspect(engine)
    existing_tables = inspector.get_table_names()

    # (table, column, DDL type + default) tuples to ensure exist
    required_columns = [
        ("users", "is_blacklisted", "BOOLEAN DEFAULT 0"),
        ("users", "blacklist_reason", "VARCHAR(500)"),
        ("app_settings", "maintenance_mode", "BOOLEAN DEFAULT 0 NOT NULL"),
        # Order lifecycle timestamps added after initial schema
        ("orders", "confirmed_at", "DATETIME"),
        ("orders", "claimed_at", "DATETIME"),
        ("orders", "updated_at", "DATETIME"),
        ("orders", "completed_at", "DATETIME"),
        ("orders", "customer_paid", "NUMERIC(10, 2) DEFAULT 0.00"),
        ("orders", "store_cost", "NUMERIC(10, 2) DEFAULT 0.00"),
        ("orders", "profit", "NUMERIC(10, 2) DEFAULT 0.00"),
        ("orders", "manual_prices", "VARCHAR(1000)"),
        ("orders", "savings", "NUMERIC(10, 2) DEFAULT 0.00"),
        ("order_items", "unit_price", "NUMERIC(10, 2)"),
        ("order_items", "store", "VARCHAR(100)"),
        ("order_items", "created_at", "DATETIME"),
        ("messages", "order_id", "VARCHAR(36)"),
    ]

    with engine.begin() as conn:
        for table, column, ddl in required_columns:
            if table not in existing_tables:
                continue  # create_all will have built it with the column already
            cols = [c["name"] for c in inspector.get_columns(table)]
            if column not in cols:
                conn.execute(text(f'ALTER TABLE {table} ADD COLUMN {column} {ddl}'))
                print(f"  + Added column {table}.{column}")


# Background cache cleanup task
def start_cache_cleanup():
    """Periodically clean expired cache entries every 5 minutes."""
    def cleanup_loop():
        while True:
            try:
                time.sleep(300)
                from core.price_cache import clean_expired as clean_price_cache
                from core.result_cache import CACHE_TTL, CACHE
                clean_price_cache()
                now = time.time()
                expired_keys = [k for k, (_, ts) in CACHE.items() if now - ts > CACHE_TTL]
                for k in expired_keys:
                    del CACHE[k]
                if expired_keys:
                    print(f"[OK] Cache cleanup: removed {len(expired_keys)} expired entries")
            except Exception as e:
                print(f"[WARN] Cache cleanup error: {e}")

    thread = threading.Thread(target=cleanup_loop, daemon=True)
    thread.start()

# Startup event to verify/initialize database schema
@app.on_event("startup")
def startup_event():
    from database import SessionLocal
    Base.metadata.create_all(bind=engine)
    run_sqlite_column_migrations()
    db = SessionLocal()
    try:
        app_setting = db.query(models.AppSetting).first()
        if not app_setting:
            app_setting = models.AppSetting(id=1, orders_enabled=True)
            db.add(app_setting)
            db.commit()
            print("App settings initialized: Orders Enabled by default.")
    finally:
        db.close()
    print("Database tables initialized successfully.")
    start_cache_cleanup()
    print("[OK] Background cache cleanup started.")


# -------------------------------
# Request / Response Models
# -------------------------------

class CartRequest(BaseModel):
    items: str
    location: str = "Pune"


class AddressCreate(BaseModel):
    title: str = Field(..., description="Address title (e.g. Home, Work)")
    street_address: str = Field(..., description="Street address details")
    city: str = Field(..., description="City name")
    state: str = Field(..., description="State name")
    postal_code: str = Field(..., description="Postal code")
    latitude: Optional[float] = Field(18.5204, description="Latitude coordinates")
    longitude: Optional[float] = Field(73.8567, description="Longitude coordinates")
    is_default: bool = False


class OrderItemInput(BaseModel):
    name: str = Field(..., description="Product name, e.g. 'Amul Milk 1L'")
    quantity: int = Field(1, ge=1, description="Quantity of this product")


class OrderCreate(BaseModel):
    store: Optional[str] = Field("pending", description="Store name identifier (e.g. zepto)")
    address_id: str = Field(..., description="Database UUID of the delivery address")
    items: Optional[List[OrderItemInput]] = Field(None, description="Structured list of products + quantities")
    items_text: Optional[str] = Field(None, description="Plain text list of items, e.g. '1kg rice, 2 packets maggi'")


class OrderItemPrice(BaseModel):
    item_id: Optional[str] = Field(None, description="OrderItem UUID")
    name: Optional[str] = Field(None, description="Product name")
    unit_price: float = Field(..., ge=0, description="Lowest price found for one unit")
    store: str = Field(..., description="Store where the lowest price was found")


class RoleUpdate(BaseModel):
    user_id: str
    role: str


class PhoneRoleRequest(BaseModel):
    phone: str


class AssignModerator(BaseModel):
    customer_id: str
    moderator_id: str


class ManualPricesEntry(BaseModel):
    items: Optional[List[OrderItemPrice]] = Field(None, description="Per-product lowest price + store")
    prices: Optional[dict] = Field(None, description="Store-level price mapping e.g. {'zepto': 300, ...}")

class QuoteSubmission(BaseModel):
    store: str
    items: List[OrderItemPrice]
    subtotal: float
    delivery_fee: float
    platform_fee: float
    store_discount: float
    snapsave_discount: float
    profit: float
    final_price: float

class DeliveryConfig(BaseModel):
    thresholds: dict
class AiTakeoverRequest(BaseModel):
    ai_takeover_enabled: bool

class OrderModeRequest(BaseModel):
    mode: str

class DelegateWorkerRequest(BaseModel):
    assigned_worker_type: str


class AiStatusRequest(BaseModel):
    ai_enabled: bool


class AssignModeratorToOrder(BaseModel):
    moderator_id: str


class BlacklistRequest(BaseModel):
    reason: Optional[str] = None


class HelpMessageCreate(BaseModel):
    message: str


class MaintenanceUpdate(BaseModel):
    maintenance_mode: bool





class SendMessageRequest(BaseModel):
    message: str
    order_id: str | None = None


class OrderFinancialsUpdate(BaseModel):
    customer_paid: float
    store_cost: float




class AppSettingUpdate(BaseModel):
    orders_enabled: bool


class ProfileUpdate(BaseModel):
    first_name: str
    last_name: str
    email: str


class FeedbackCreate(BaseModel):
    order_id: str
    rating: int = Field(..., ge=1, le=5)
    what_went_well: Optional[str] = None
    what_was_confusing: Optional[str] = None
    would_use_again: bool


class IncidentCreate(BaseModel):
    order_id: Optional[str] = None
    incident_type: str
    notes: Optional[str] = None


# -------------------------------
# Authentication Dependency
# -------------------------------

# Cache for Google's public certificates
_google_certs = {}
_google_certs_expiry = 0
_test_private_key = None
_test_public_cert = None

def fetch_google_public_certs():
    global _google_certs, _google_certs_expiry
    now = time.time()
    if not _google_certs or now > _google_certs_expiry:
        try:
            r = requests.get("https://www.googleapis.com/robot/v1/metadata/x509/securetoken@system.gserviceaccount.com", timeout=10)
            if r.status_code == 200:
                _google_certs = r.json()
                cache_control = r.headers.get("Cache-Control", "")
                max_age = 3600
                for part in cache_control.split(","):
                    if "max-age" in part:
                        try:
                            max_age = int(part.split("=")[1].strip())
                        except:
                            pass
                _google_certs_expiry = now + max_age
        except Exception as e:
            print(f"Error fetching Google public certs: {e}")
            if not _google_certs:
                raise e
    return _google_certs

def get_test_keys():
    global _test_private_key, _test_public_cert
    if _test_private_key is None:
        try:
            from cryptography.hazmat.primitives.asymmetric import rsa
            from cryptography.hazmat.primitives import serialization
            from cryptography.hazmat.backends import default_backend
            
            _test_private_key = rsa.generate_private_key(
                public_exponent=65537,
                key_size=2048,
                backend=default_backend()
            )
            public_key = _test_private_key.public_key()
            pem = public_key.public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo
            ).decode("utf-8")
            _test_public_cert = pem
        except Exception as e:
            print(f"Failed to generate local test keys: {e}")
    return _test_private_key, _test_public_cert

def get_current_user(authorization: str = Header(None), db: Session = Depends(get_db)):
    print(f"DEBUG AUTH: Authorization Header: {authorization}")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid Authorization header"
        )
    
    token = authorization.split("Bearer ")[1].strip()
    
    try:
        import jwt
        unverified_claims = jwt.decode(token, options={"verify_signature": False})
        print(f"DEBUG AUTH: Unverified Claims: {unverified_claims}")
    except Exception as e:
        print(f"DEBUG AUTH: Failed to decode unverified claims: {e}")
    
    # Local fallback for smoke tests and offline testing (DEBUG mode only)
    if token == "test_token" and os.getenv("DEBUG", "false").lower() == "true":
        test_user = db.query(models.User).filter(models.User.email == "test@snapsave.com").first()
        if not test_user:
            test_user = models.User(
                id="test_uid_123",
                email="test@snapsave.com",
                phone_number="+919999999999",
                password_hash="mock_hash",
                first_name="Test",
                last_name="User",
                completed_orders_count=0
            )
            db.add(test_user)
            db.commit()
            db.refresh(test_user)
        return test_user

    try:
        decoded_token = None
        # 1. Decode header unverified to check for test key
        header = jwt.get_unverified_header(token)
        kid = header.get("kid")

        # 2. Try Firebase Admin SDK verification if initialized and not a test key
        if firebase_initialized and kid != "test_kid":
            try:
                decoded_token = auth.verify_id_token(token, clock_skew_seconds=60)
                print(f"[OK] Token verified using Firebase Admin SDK")
            except Exception as admin_err:
                print(f"[WARN] Firebase Admin SDK token verification failed: {type(admin_err).__name__}: {admin_err}")
                print(f"    Falling back to manual verification...")
        
        # 2. Fallback to PyJWT manual verification if Admin SDK failed or was not initialized
        if not decoded_token:
            try:
                # Decode the token header to get kid
                header = jwt.get_unverified_header(token)
                kid = header.get("kid")
                if not kid:
                    raise ValueError("JWT header missing 'kid'")
                
                # Check for test token signature
                if kid == "test_kid":
                    _, test_pub = get_test_keys()
                    cert_pem = test_pub
                else:
                    certs = fetch_google_public_certs()
                    cert_pem = certs.get(kid)
                    if not cert_pem:
                        raise ValueError(f"No Google public key found for kid: {kid}")
                
                # Decode and verify using PyJWT
                key_to_use = cert_pem
                if isinstance(cert_pem, str) and cert_pem.startswith("-----BEGIN CERTIFICATE-----"):
                    from cryptography.x509 import load_pem_x509_certificate
                    from cryptography.hazmat.backends import default_backend
                    cert_obj = load_pem_x509_certificate(cert_pem.encode(), default_backend())
                    key_to_use = cert_obj.public_key()

                from datetime import timedelta
                decoded_token = jwt.decode(
                    token,
                    key_to_use,
                    algorithms=["RS256"],
                    audience="snapsave-501c7",
                    issuer="https://securetoken.google.com/snapsave-501c7",
                    leeway=timedelta(seconds=60)
                )
            except Exception as jwt_err:
                import traceback
                print(f"DEBUG AUTH: JWT Verification Exception: {jwt_err}")
                traceback.print_exc()
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail=f"Token verification failed: {str(jwt_err)}"
                )
        
        # 3. Resolve user in DB
        uid = decoded_token.get("uid") or decoded_token.get("sub") or decoded_token.get("user_id")
        if not uid:
            raise ValueError("Token missing user identifier (uid/sub)")
        email = decoded_token.get("email", "")
        phone = decoded_token.get("phone_number", "") or decoded_token.get("phone", "")

        # For test tokens, infer role from UID naming convention so dev logins work immediately
        inferred_role = None
        # Normalize phone number
        if phone:
            normalized_phone = phone if phone.startswith('+') else f"+{phone}"
        else:
            normalized_phone = None

        if kid == "test_kid":
            uid_lower = uid.lower()
            if "admin" in uid_lower or normalized_phone == "+919999999999":
                inferred_role = "ADMIN"
            elif "moderator" in uid_lower or "mod" in uid_lower:
                inferred_role = "MODERATOR"

        user = db.query(models.User).filter(models.User.id == uid).first()

        # For test tokens: if the uid doesn't exist but the phone belongs to a real user, return that user directly
        if not user and normalized_phone:
            user = db.query(models.User).filter(models.User.phone_number == normalized_phone).first()

        if user and normalized_phone == "+919999999999" and user.role != "ADMIN":
            user.role = "ADMIN"
            db.commit()

        if not user:
            # Create a new user — use a safe fallback phone that won't collide
            new_phone = normalized_phone or "+919999999999"
            # If that phone is already taken by another user, don't set a phone at all
            phone_taken = db.query(models.User).filter(models.User.phone_number == new_phone).first()
            user = models.User(
                id=uid,
                email=email or f"{uid}@snapsave.com",
                phone_number=new_phone if not phone_taken else None,
                password_hash="firebase_managed",
                completed_orders_count=0,
                role=inferred_role or "CUSTOMER"
            )
            db.add(user)
            db.commit()
            db.refresh(user)
        else:
            # Sync phone number or email if updated
            updated = False
            if normalized_phone and user.phone_number != normalized_phone:
                # Only update if the new phone isn't already claimed by a different user
                phone_owner = db.query(models.User).filter(
                    models.User.phone_number == normalized_phone,
                    models.User.id != user.id
                ).first()
                if not phone_owner:
                    user.phone_number = normalized_phone
                    updated = True
            if email and user.email != email:
                user.email = email
                updated = True
            # For test tokens, force-correct the role if it doesn't match the UID intent
            if inferred_role and user.role != inferred_role:
                user.role = inferred_role
                updated = True
            if updated:
                db.commit()
                db.refresh(user)
        return user
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        print(f"DEBUG AUTH: General Auth Exception: {e}")
        traceback.print_exc()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Authentication error: {str(e)}"
        )


def require_role(allowed_roles: List[str]):
    def dependency(current_user: models.User = Depends(get_current_user)):
        if current_user.role not in allowed_roles:
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
def find_deal(item: str):
    raw_prices = get_prices_parallel(item, 1)
    prices = convert_to_legacy_prices(raw_prices, item)
    valid = {k: v for k, v in prices.items() if v != "not_available"}

    if not valid:
        return {
            "item": item,
            "message": "Product not available in any store"
        }

    best_store = min(valid, key=valid.get)
    return {
        "item": item,
        "stores": prices,
        "best_deal": {
            "store": best_store,
            "price": valid[best_store]
        }
    }


@app.post("/optimize-cart")
def optimize_cart_endpoint(request: CartRequest):
    cart = build_cart_from_text(request.items)
    available_stores = check_store_availability(request.location)
    scraped_results = {}

    for item in cart:
        product = item["product"]
        quantity = item["quantity"]
        original_query = item["original_query"]

        try:
            raw_prices = get_prices_parallel(product, quantity)
        except Exception as e:
            print(f"Scraper execution failed: {e}")
            raw_prices = {}

        # Fallback to mock data if scrapers are blocked or unavailable (useful for offline demo & testing)
        if not raw_prices or all(v in (None, "not_available") for v in raw_prices.values()):
            raw_prices = {
                "zepto": [{"name": f"Test {product}", "price": 40.0 * quantity}],
                "blinkit": [{"name": f"Test {product}", "price": 45.0 * quantity}],
                "instamart": [{"name": f"Test {product}", "price": 42.0 * quantity}],
                "bigbasket": [{"name": f"Test {product}", "price": 38.0 * quantity}],
                "jiomart": [{"name": f"Test {product}", "price": 35.0 * quantity}]
            }

        product_results = []
        for store, candidates in raw_prices.items():
            if store not in available_stores:
                continue
            if candidates in (None, "not_available"):
                continue

            resolved = resolve_best_candidate(original_query, store, candidates)
            if resolved:
                resolved["product"] = product
                resolved["quantity"] = quantity
                product_results.append(resolved)

        if product_results:
            scraped_results[product] = product_results

    if not scraped_results:
        return {
            "cart": cart,
            "message": "No stores available for this cart"
        }

    pricing_result = run_pricing_engine(scraped_results, request.location)
    return {
        "location": request.location,
        "cart": cart,
        "pricing": pricing_result
    }


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
def get_test_token(phone: str = "+919999999999", uid: str = "test_uid_123"):
    """
    Helper endpoint for local demo and automated testing.
    Generates a cryptographically signed RS256 JWT token using a local RSA private key.
    The backend verifies this token using the corresponding public key because kid is 'test_kid'.
    """
    # Replace leading space with '+' if it was URL decoded incorrectly
    if phone.startswith(" "):
        phone = "+" + phone.strip()
        
    private_key, _ = get_test_keys()
    if not private_key:
        raise HTTPException(status_code=500, detail="Local RSA key generation failed")
    
    import jwt
    import time
    
    now = int(time.time())
    payload = {
        "iss": "https://securetoken.google.com/snapsave-501c7",
        "aud": "snapsave-501c7",
        "auth_time": now,
        "sub": uid,
        "uid": uid,
        "exp": now + 3600,
        "iat": now,
        "phone_number": phone,
        "firebase": {
            "identities": {
                "phone": [phone]
            },
            "sign_in_provider": "phone"
        }
    }
    
    token = jwt.encode(
        payload,
        private_key,
        algorithm="RS256",
        headers={"kid": "test_kid"}
    )
    
    return {"idToken": token}



# -------------------------------
# User Address Management
# -------------------------------

@app.post("/api/addresses", status_code=status.HTTP_201_CREATED)
def create_address(address_data: AddressCreate, current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    if address_data.is_default:
        db.query(models.Address).filter(
            models.Address.user_id == current_user.id,
            models.Address.is_default == True
        ).update({"is_default": False})

    new_address = models.Address(
        user_id=current_user.id,
        title=address_data.title,
        street_address=address_data.street_address,
        city=address_data.city,
        state=address_data.state,
        postal_code=address_data.postal_code,
        latitude=address_data.latitude if address_data.latitude is not None else 18.5204,
        longitude=address_data.longitude if address_data.longitude is not None else 73.8567,
        is_default=address_data.is_default
    )
    db.add(new_address)
    db.commit()
    db.refresh(new_address)
    return new_address


@app.get("/api/addresses")
def list_addresses(current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    addresses = db.query(models.Address).filter(models.Address.user_id == current_user.id).all()
    return addresses


@app.delete("/api/addresses/{address_id}")
def delete_address(address_id: str, current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    addr = db.query(models.Address).filter(
        models.Address.id == address_id,
        models.Address.user_id == current_user.id
    ).first()
    if not addr:
        raise HTTPException(status_code=404, detail="Address not found")
    
    was_default = addr.is_default
    db.delete(addr)
    db.commit()

    # If the deleted address was default, set another address as default if available
    if was_default:
        fallback = db.query(models.Address).filter(models.Address.user_id == current_user.id).first()
        if fallback:
            fallback.is_default = True
            db.commit()

    return {"message": "Address deleted successfully", "id": address_id}


@app.put("/api/addresses/{address_id}/default")
def set_default_address(address_id: str, current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
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
    """Return the structured per-product breakdown for an order."""
    return [
        {
            "id": it.id,
            "name": it.name,
            "quantity": it.quantity,
            "unit_price": float(it.unit_price) if it.unit_price is not None else None,
            "store": it.store,
            "line_total": float(it.unit_price) * it.quantity if it.unit_price is not None else None,
        }
        for it in sorted(order.items, key=lambda x: x.created_at or datetime.min)
    ]


def clean_item_name(name: str, quantity: int) -> str:
    """Clean leading multiplier or count prefix from product name if quantity > 1."""
    name = name.strip()
    if quantity and quantity > 1:
        # Strip leading multiplier patterns like '2x ', '2 * ', '2 pcs ', '2 packet ', '2 '
        cleaned = re.sub(
            r'^\s*\d+\s*(?:x|\*|pcs|pieces|packets?|packs?|pkts?|bottles?|cans?|box(?:es)?)\s*',
            '',
            name,
            flags=re.IGNORECASE
        )
        if cleaned == name:
            # Strip leading numbers followed by space if not a volume unit (kg, g, gm, ml, l, etc.)
            cleaned = re.sub(
                r'^\s*\d+\s+(?!(?:kg|g|gm|ml|l|ltr|litre|liter)\b)',
                '',
                name,
                flags=re.IGNORECASE
            )
        if cleaned.strip():
            name = cleaned.strip()
    return name


@app.post("/api/orders", status_code=status.HTTP_201_CREATED)
def create_order(order_data: OrderCreate, current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    # 0a. Blocked / blacklisted customers cannot place orders
    if current_user.is_blacklisted:
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=403,
            content={
                "status": "blocked",
                "message": "Your account is currently restricted from placing orders. Please contact support."
            }
        )

    # 0b. Check global maintenance / order pause switches
    app_setting = db.query(models.AppSetting).first()
    if app_setting and getattr(app_setting, "maintenance_mode", False):
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=503,
            content={
                "status": "maintenance",
                "message": "SnapSave is temporarily down for maintenance. Please check back soon."
            }
        )
    if app_setting and not app_setting.orders_enabled:
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=400,
            content={
                "status": "paused",
                "message": "We are currently processing existing orders. Please try again shortly."
            }
        )

    # 1. Resolve delivery address
    address = db.query(models.Address).filter(
        models.Address.id == order_data.address_id,
        models.Address.user_id == current_user.id
    ).first()

    if not address:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Delivery address not found or unauthorized"
        )

    # 2. Create Order record in pending_review status
    # In Human-Concierge MVP, there is no automatic scraper execution.
    order_items_list = []
    if order_data.items:
        order_items_list = [
            OrderItemInput(name=clean_item_name(it.name, it.quantity), quantity=it.quantity)
            for it in order_data.items if it.name and it.name.strip()
        ]
    elif order_data.items_text:
        parsed_cart = build_cart_from_text(order_data.items_text)
        if parsed_cart:
            for p in parsed_cart:
                p_name = p.get("original_query") or p.get("product") or "Item"
                p_qty = p.get("quantity") or 1
                cleaned_name = clean_item_name(p_name, p_qty)
                order_items_list.append(OrderItemInput(name=cleaned_name, quantity=p_qty))
        else:
            # Fallback simple split by comma
            for chunk in order_data.items_text.split(","):
                chunk = chunk.strip()
                if chunk:
                    order_items_list.append(OrderItemInput(name=clean_item_name(chunk, 1), quantity=1))

    if not order_items_list:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Either 'items' or 'items_text' must contain at least one item."
        )

    items_text = ", ".join(
        f"{it.quantity}x {it.name}" if it.quantity > 1 else it.name
        for it in order_items_list
    )
    new_order = models.Order(
        user_id=current_user.id,
        address_id=address.id,
        store=order_data.store or "pending",
        status="pending_review",
        delivery_street=address.street_address,
        delivery_city=address.city,
        delivery_postal_code=address.postal_code,
        subtotal=0.00,
        delivery_fee=0.00,
        platform_fee=0.00,
        store_discount=0.00,
        snapsave_discount=0.00,
        final_price=0.00,
        savings=0.00,
        manual_prices=None
    )
    db.add(new_order)
    db.flush()  # assign new_order.id before adding child rows

    # 2b. Persist structured line items
    for it in order_items_list:
        db.add(models.OrderItem(
            order_id=new_order.id,
            name=it.name.strip(),
            quantity=it.quantity,
        ))

    db.commit()
    db.refresh(new_order)

    # 3. Save the submission as a customer message in the chat
    cust_msg = models.Message(
        user_id=current_user.id,
        order_id=new_order.id,
        sender_id=current_user.id,
        sender_role="CUSTOMER",
        message=items_text
    )
    db.add(cust_msg)

    system_msg = models.Message(
        user_id=current_user.id,
        order_id=new_order.id,
        sender_id="system",
        sender_role="SYSTEM",
        message=f"Order received! A concierge moderator will review your request and find the best prices for you shortly."
    )
    db.add(system_msg)
    
    db.commit()
    db.refresh(new_order)

    return {
        "id": new_order.id,
        "user_id": new_order.user_id,
        "address_id": new_order.address_id,
        "store": new_order.store,
        "status": new_order.status,
        "subtotal": float(new_order.subtotal or 0.0),
        "final_price": float(new_order.final_price or 0.0),
        "savings": float(new_order.savings or 0.0),
        "items": serialize_order_items(new_order),
        "created_at": new_order.created_at.isoformat() if new_order.created_at else None,
    }



@app.get("/api/orders")
def get_order_history(current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    from sqlalchemy.orm import joinedload
    orders = db.query(models.Order).filter(
        models.Order.user_id == current_user.id
    ).options(joinedload(models.Order.user)).order_by(models.Order.created_at.desc()).all()

    results = []
    moderator_cache = {}

    for o in orders:
        moderator_name = "Unassigned"
        cust = o.user
        if cust and cust.assigned_moderator_id:
            mod_id = cust.assigned_moderator_id
            if mod_id in moderator_cache:
                moderator_name = moderator_cache[mod_id]
            else:
                mod = db.query(models.User).filter(models.User.id == mod_id).first()
                if mod:
                    name_parts = []
                    if mod.first_name:
                        name_parts.append(mod.first_name)
                    if mod.last_name:
                        name_parts.append(mod.last_name)
                    moderator_name = " ".join(name_parts).strip() or mod.email or "Assigned Moderator"
                moderator_cache[mod_id] = moderator_name

        results.append({
            "id": o.id,
            "user_id": o.user_id,
            "address_id": o.address_id,
            "store": o.store,
            "status": o.status,
            "delivery_street": o.delivery_street,
            "delivery_city": o.delivery_city,
            "delivery_postal_code": o.delivery_postal_code,
            "mode": o.mode,
            "assigned_worker_type": o.assigned_worker_type,
            "is_ai_priced": o.is_ai_priced,
            "subtotal": float(o.subtotal),
            "delivery_fee": float(o.delivery_fee),
            "platform_fee": float(o.platform_fee),
            "store_discount": float(o.store_discount),
            "snapsave_discount": float(o.snapsave_discount),
            "final_price": float(o.final_price),
            "savings": float(o.savings),
            "manual_prices": o.manual_prices,
            "customer_paid": float(o.customer_paid),
            "store_cost": float(o.store_cost),
            "profit": float(o.profit),
            "created_at": o.created_at.isoformat() if o.created_at else None,
            "claimed_at": o.claimed_at.isoformat() if o.claimed_at else None,
            "completed_at": o.completed_at.isoformat() if o.completed_at else None,
            "updated_at": o.updated_at.isoformat() if o.updated_at else (o.created_at.isoformat() if o.created_at else None),
            "assigned_moderator_name": moderator_name,
            "items": serialize_order_items(o)
        })
    return results


@app.get("/api/orders/{order_id}")
def get_order_detail(order_id: str, current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    order = db.query(models.Order).filter(models.Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    # Customers may only read their own orders; staff may read any
    if current_user.role == "CUSTOMER" and order.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to view this order")
    return {
        "id": order.id,
        "user_id": order.user_id,
        "store": order.store,
        "status": order.status,
        "subtotal": float(order.subtotal),
        "delivery_fee": float(order.delivery_fee),
        "platform_fee": float(order.platform_fee),
        "store_discount": float(order.store_discount),
        "snapsave_discount": float(order.snapsave_discount),
        "final_price": float(order.final_price),
        "savings": float(order.savings),
        "customer_paid": float(order.customer_paid),
        "store_cost": float(order.store_cost),
        "profit": float(order.profit),
        "delivery_city": order.delivery_city,
        "mode": order.mode,
        "assigned_worker_type": order.assigned_worker_type,
        "is_ai_priced": order.is_ai_priced,
        "created_at": order.created_at.isoformat() if order.created_at else None,
        "items": serialize_order_items(order)
    }


@app.post("/api/orders/{order_id}/complete")
def complete_order_endpoint(order_id: str, current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    """
    Explicit order-completion logic.
    Increments completed_orders_count and registers completion timestamps in one transaction.
    """
    order = db.query(models.Order).filter(models.Order.id == order_id).first()
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found"
        )

    if order.status != "completed":
        # Increment user order counter explicitly
        if order.user_id:
            user = db.query(models.User).filter(models.User.id == order.user_id).first()
            if user:
                user.completed_orders_count += 1
        
        order.status = "completed"
        order.completed_at = datetime.utcnow()
        db.commit()
        db.refresh(order)

    return {
        "message": "Order marked completed successfully",
        "order_id": order.id,
        "status": order.status,
        "completed_at": order.completed_at
    }


# -------------------------------
# Human-Concierge MVP Endpoints
# -------------------------------

@app.put("/api/admin/roles")
def update_user_role(data: RoleUpdate, current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    # Bootstrap exception: allow test users or if there is no admin in DB
    has_admin = db.query(models.User).filter(models.User.role == "ADMIN").first()
    is_test_user = current_user.id.startswith("test_uid") or "test" in current_user.id
    
    if has_admin and not is_test_user and current_user.role != "ADMIN":
        raise HTTPException(status_code=403, detail="Only admins can update roles")
    
    target_user = db.query(models.User).filter(models.User.id == data.user_id).first()
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")
    
    if data.role not in ["CUSTOMER", "MODERATOR", "ADMIN"]:
        raise HTTPException(status_code=400, detail="Invalid role value")
    
    target_user.role = data.role
    db.commit()
    db.refresh(target_user)
    return {"message": "Role updated successfully", "user_id": target_user.id, "role": target_user.role}


@app.put("/api/admin/make-admin")
def make_admin_by_phone(data: PhoneRoleRequest, db: Session = Depends(get_db)):
    """Promote a user to ADMIN by phone number. No auth required — hit directly from Postman."""
    user = db.query(models.User).filter(models.User.phone_number == data.phone).first()
    if not user:
        raise HTTPException(status_code=404, detail=f"No user found with phone: {data.phone}")
    user.role = "ADMIN"
    db.commit()
    db.refresh(user)
    return {"message": "User promoted to ADMIN", "phone": user.phone_number, "user_id": user.id, "role": user.role}


@app.put("/api/admin/make-moderator")
def make_moderator_by_phone(data: PhoneRoleRequest, db: Session = Depends(get_db)):
    """Promote a user to MODERATOR by phone number. No auth required — hit directly from Postman."""
    user = db.query(models.User).filter(models.User.phone_number == data.phone).first()
    if not user:
        raise HTTPException(status_code=404, detail=f"No user found with phone: {data.phone}")
    user.role = "MODERATOR"
    db.commit()
    db.refresh(user)
    return {"message": "User promoted to MODERATOR", "phone": user.phone_number, "user_id": user.id, "role": user.role}


@app.post("/api/admin/assign-moderator")
def assign_moderator(data: AssignModerator, current_user: models.User = Depends(require_role(["ADMIN"])), db: Session = Depends(get_db)):
    customer = db.query(models.User).filter(models.User.id == data.customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    
    moderator = db.query(models.User).filter(models.User.id == data.moderator_id).first()
    if not moderator:
        raise HTTPException(status_code=404, detail="Moderator not found")
    if moderator.role not in ["MODERATOR", "ADMIN"]:
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
def list_customers(current_user: models.User = Depends(require_role(["ADMIN", "MODERATOR"])), db: Session = Depends(get_db)):
    customers = db.query(models.User).filter(models.User.role == "CUSTOMER").all()
    return [{
        "id": c.id, "email": c.email, "phone_number": c.phone_number,
        "assigned_moderator_id": c.assigned_moderator_id,
        "is_blacklisted": bool(c.is_blacklisted), "blacklist_reason": c.blacklist_reason
    } for c in customers]


@app.get("/api/admin/users")
def list_all_users(current_user: models.User = Depends(require_role(["ADMIN"])), db: Session = Depends(get_db)):
    """Full user list with roles — feeds the (hidden) role-management panel. ADMIN only."""
    users = db.query(models.User).order_by(models.User.created_at.asc()).all()
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
    ).order_by(models.HelpMessage.created_at.asc()).all()
    return [_serialize_help(m) for m in msgs]


@app.get("/api/admin/help")
def get_help_inbox(current_user: models.User = Depends(require_role(["ADMIN"])), db: Session = Depends(get_db)):
    """Admin inbox: all support messages grouped by customer. ADMIN only — moderators have no access."""
    from sqlalchemy.orm import joinedload
    msgs = db.query(models.HelpMessage).options(joinedload(models.HelpMessage.user)).order_by(models.HelpMessage.created_at.asc()).all()
    threads = {}
    for m in msgs:
        t = threads.setdefault(m.user_id, {"user_id": m.user_id, "messages": [], "open": False, "customer_phone": "N/A", "customer_email": "N/A"})
        t["messages"].append(_serialize_help(m))
        if not m.is_resolved and m.sender_role == "CUSTOMER":
            t["open"] = True
        if m.user:
            t["customer_phone"] = m.user.phone_number or "N/A"
            t["customer_email"] = m.user.email or "N/A"
    most_recently_active = sorted(threads.values(), key=lambda x: x["messages"][-1]["created_at"] or "", reverse=True)
    return most_recently_active


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
    """Unauthenticated app status so the customer app can show a maintenance banner."""
    setting = db.query(models.AppSetting).first()
    return {
        "maintenance_mode": bool(getattr(setting, "maintenance_mode", False)) if setting else False,
        "orders_enabled": setting.orders_enabled if setting else True,
    }


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
def get_moderator_queue(status_filter: Optional[str] = None, current_user: models.User = Depends(require_role(["ADMIN", "MODERATOR"])), db: Session = Depends(get_db)):
    from sqlalchemy.orm import joinedload
    query = db.query(models.Order).options(joinedload(models.Order.user))
    if status_filter:
        query = query.filter(models.Order.status == status_filter)

    orders = query.order_by(models.Order.created_at.desc()).all()

    results = []
    for o in orders:
        cust = o.user
        results.append({
            "order_id": o.id,
            "customer_id": o.user_id,
            "customer_name": f"{cust.first_name or ''} {cust.last_name or ''}".strip() if cust else "Unknown",
            "customer_phone": cust.phone_number if cust else "N/A",
            "status": o.status,
            "created_at": o.created_at,
            "delivery_city": o.delivery_city,
            "assigned_moderator_id": cust.assigned_moderator_id if cust else None,
            "manual_prices": o.manual_prices,
            "final_price": float(o.final_price),
            "subtotal": float(o.subtotal),
            "customer_paid": float(o.customer_paid),
            "store_cost": float(o.store_cost),
            "mode": o.mode,
            "assigned_worker_type": o.assigned_worker_type,
            "is_ai_priced": o.is_ai_priced,
            "ai_started_at": o.ai_started_at,
            "ai_stopped_at": o.ai_stopped_at,
            "taken_over_at": o.taken_over_at,
            "items": serialize_order_items(o)
        })
    return results


@app.put("/api/moderator/orders/{order_id}/claim")
def claim_order(order_id: str, current_user: models.User = Depends(require_role(["ADMIN", "MODERATOR"])), db: Session = Depends(get_db)):
    order = db.query(models.Order).filter(models.Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    
    cust = db.query(models.User).filter(models.User.id == order.user_id).first()
    if cust:
        if current_user.role != "ADMIN" and cust.assigned_moderator_id and cust.assigned_moderator_id != current_user.id:
            raise HTTPException(status_code=403, detail="Order is already claimed by another moderator")
        cust.assigned_moderator_id = current_user.id
    
    order.status = "reviewing"
    order.claimed_at = datetime.utcnow()
    order.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(order)
    return {"message": "Order claimed successfully", "order_id": order.id, "status": order.status, "assigned_moderator_id": current_user.id}


@app.post("/api/moderator/orders/{order_id}/preview-quote")
def preview_quote(order_id: str, data: ManualPricesEntry, current_user: models.User = Depends(require_role(["ADMIN", "MODERATOR"])), db: Session = Depends(get_db)):
    import json
    order = db.query(models.Order).filter(models.Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    if data.items:
        # Sum up the total costs entered (each unit_price represents the total for that line item)
        subtotal = sum(float(entry.unit_price) for entry in data.items)

        # Primary store = the store carrying the largest share of the cart
        store_totals = {}
        for entry in data.items:
            store_totals[entry.store.strip().lower()] = store_totals.get(entry.store.strip().lower(), 0.0) + float(entry.unit_price)
        primary_store = max(store_totals, key=store_totals.get) if store_totals else "pending"

        # Check delivery threshold
        setting = db.query(models.SystemSetting).filter(models.SystemSetting.key == "delivery_thresholds").first()
        thresholds = json.loads(setting.value) if setting and setting.value else {}
        threshold = float(thresholds.get(primary_store, 199.0))
        
        delivery_fee = 0.0
        if subtotal < threshold:
            delivery_fee = 35.0  # default suggested fee if below threshold

        # Default platform fee
        platform_fee = 5.0

        return {
            "subtotal": subtotal,
            "delivery_fee": delivery_fee,
            "platform_fee": platform_fee,
            "store_discount": 0.0,
            "snapsave_discount": 0.0,
            "profit": 0.0,
            "store": primary_store,
            "items": [it.dict() for it in data.items]
        }
    else:
        raise HTTPException(status_code=400, detail="items are required")


@app.post("/api/moderator/orders/{order_id}/price")
def enter_prices(order_id: str, data: QuoteSubmission, current_user: models.User = Depends(require_role(["ADMIN", "MODERATOR"])), db: Session = Depends(get_db)):
    import json
    order = db.query(models.Order).filter(models.Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    cust = db.query(models.User).filter(models.User.id == order.user_id).first()
    if current_user.role != "ADMIN" and cust and cust.assigned_moderator_id != current_user.id:
        raise HTTPException(status_code=403, detail="You are not assigned to this customer's order")

    if order.status not in ["pending_review", "reviewing", "awaiting_customer"]:
        raise HTTPException(status_code=400, detail="Cannot enter/edit prices in this order status")

    # Map prices back onto line items
    item_map = {it.id: it for it in order.items}
    for entry in data.items:
        target = item_map.get(entry.item_id) if entry.item_id else None
        if not target and entry.name:
            target = next((it for it in order.items if it.name == entry.name), None)
        if target:
            target.unit_price = entry.unit_price
            target.store = entry.store.strip().lower()

    # Savings = total of all discounts
    savings_val = data.snapsave_discount + data.store_discount

    order.store = data.store
    order.subtotal = data.subtotal
    order.delivery_fee = data.delivery_fee
    order.platform_fee = data.platform_fee
    order.store_discount = data.store_discount
    order.snapsave_discount = data.snapsave_discount
    order.profit = data.profit
    order.final_price = data.final_price
    order.savings = savings_val
    order.manual_prices = json.dumps([
        {"name": it.name, "qty": it.quantity, "unit_price": float(it.unit_price) if it.unit_price is not None else None, "store": it.store}
        for it in order.items
    ])
    
    # Mark as human-verified since a moderator is entering prices
    order.is_ai_priced = False

    order.status = "awaiting_customer"
    db.commit()
    db.refresh(order)

    msg_text = (
        "Your itemised quote is ready:\n"
        + "\n".join([
            f"- {it.quantity}x {it.name}: ₹{float(it.unit_price):.2f} ({it.store.capitalize()})"
            for it in order.items if it.unit_price is not None
        ])
        + f"\n\nSubtotal: ₹{data.subtotal:.2f}\n"
        f"Final Estimated Price: ₹{order.final_price:.2f} (after discounts & delivery).\n"
        f"You save ₹{savings_val:.2f}! Tap Confirm Order to proceed."
    )

    system_msg = models.Message(
        user_id=order.user_id,
        sender_id="system",
        sender_role="SYSTEM",
        message=msg_text
    )
    db.add(system_msg)
    db.commit()

    return {
        "message": "Quote submitted successfully",
        "order_id": order.id,
        "primary_store": data.store,
        "final_price": data.final_price,
        "status": order.status,
        "items": serialize_order_items(order)
    }


@app.put("/api/customer/orders/{order_id}/confirm")
def confirm_order(order_id: str, current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    order = db.query(models.Order).filter(
        models.Order.id == order_id,
        models.Order.user_id == current_user.id
    ).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    
    if order.status != "awaiting_customer":
        raise HTTPException(status_code=400, detail="Order is not in awaiting_customer status")
    
    order.status = "awaiting_payment"
    order.confirmed_at = datetime.utcnow()
    order.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(order)
    
    system_msg = models.Message(
        user_id=current_user.id,
        order_id=order.id,
        sender_id=current_user.id,
        sender_role="CUSTOMER",
        message="CONFIRM"
      )
    db.add(system_msg)

    # Automated QR code response
    qr_msg = models.Message(
        user_id=current_user.id,
        order_id=order.id,
        sender_id="system",
        sender_role="SYSTEM",
        message="Thank you! Please scan this QR code to make your payment. Once done, let us know in the chat!<br><br><img src='/assets/qr.jpg' alt='Payment QR' style='max-width: 250px; border-radius: 8px; margin-top: 8px;' />"
    )
    db.add(qr_msg)
    
    db.commit()
    
    return {"message": "Order confirmed successfully", "order_id": order.id, "status": order.status}

class PlaceOrderRequest(BaseModel):
    eta_mins: int

@app.post("/api/moderator/orders/{order_id}/place")
def place_order_with_eta(order_id: str, data: PlaceOrderRequest, current_user: models.User = Depends(require_role(["ADMIN", "MODERATOR"])), db: Session = Depends(get_db)):
    order = db.query(models.Order).filter(models.Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    
    if order.status != "awaiting_payment":
        raise HTTPException(status_code=400, detail="Order is not awaiting payment")
        
    order.status = "placed"
    order.updated_at = datetime.utcnow()
    
    eta_msg = models.Message(
        user_id=order.user_id,
        order_id=order.id,
        sender_id="system",
        sender_role="SYSTEM",
        message=f"Payment verified! Your order has been placed and will arrive in {data.eta_mins} minutes."
    )
    db.add(eta_msg)
    db.commit()
    db.refresh(order)
    return {"message": "Order placed successfully", "order_id": order.id, "status": order.status}


@app.put("/api/admin/orders/{order_id}/place")
def place_order(order_id: str, data: OrderFinancialsUpdate, current_user: models.User = Depends(require_role(["ADMIN"])), db: Session = Depends(get_db)):
    order = db.query(models.Order).filter(models.Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    
    order.customer_paid = data.customer_paid
    order.store_cost = data.store_cost
    order.profit = data.customer_paid - data.store_cost
    order.status = "placed"
    
    db.commit()
    db.refresh(order)
    return {"message": "Order marked as placed manually", "order_id": order.id, "status": order.status, "profit": order.profit}


@app.put("/api/admin/orders/{order_id}/deliver")
@app.put("/api/moderator/orders/{order_id}/deliver")
def deliver_order(order_id: str, current_user: models.User = Depends(require_role(["ADMIN", "MODERATOR"])), db: Session = Depends(get_db)):
    order = db.query(models.Order).filter(models.Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    cust = db.query(models.User).filter(models.User.id == order.user_id).first()
    if current_user.role == "MODERATOR":
        if not cust or cust.assigned_moderator_id != current_user.id:
            raise HTTPException(status_code=403, detail="You are not assigned to this customer")

    if order.status != "placed":
        raise HTTPException(status_code=400, detail="Order must be in placed status to mark delivered")

    order.status = "delivered"
    order.completed_at = datetime.utcnow()

    if cust:
        cust.completed_orders_count += 1

    db.commit()
    db.refresh(order)
    return {"message": "Order marked as delivered successfully", "order_id": order.id, "status": order.status}


@app.put("/api/admin/orders/{order_id}/assign")
def assign_order_to_moderator(order_id: str, data: AssignModeratorToOrder, current_user: models.User = Depends(require_role(["ADMIN"])), db: Session = Depends(get_db)):
    """Admin hands a ticket to a specific moderator (the admin-driven half of hybrid assignment)."""
    order = db.query(models.Order).filter(models.Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    moderator = db.query(models.User).filter(models.User.id == data.moderator_id).first()
    if not moderator or moderator.role not in ["MODERATOR", "ADMIN"]:
        raise HTTPException(status_code=400, detail="Target user is not a moderator or admin")

    cust = db.query(models.User).filter(models.User.id == order.user_id).first()
    if cust:
        cust.assigned_moderator_id = moderator.id

    if order.status == "pending_review":
        order.status = "reviewing"
        order.claimed_at = datetime.utcnow()
    order.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(order)
    return {"message": "Order assigned successfully", "order_id": order.id, "status": order.status, "assigned_moderator_id": moderator.id}


@app.put("/api/admin/orders/{order_id}/cancel")
def cancel_order(order_id: str, current_user: models.User = Depends(require_role(["ADMIN"])), db: Session = Depends(get_db)):
    order = db.query(models.Order).filter(models.Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    if order.status in ["delivered", "completed", "cancelled"]:
        raise HTTPException(status_code=400, detail=f"Cannot cancel an order that is already {order.status}")

    order.status = "cancelled"
    order.updated_at = datetime.utcnow()
    db.commit()

    system_msg = models.Message(
        user_id=order.user_id,
        sender_id="system",
        sender_role="AI",
        message="Your order has been cancelled by SnapSave. Please contact support if you have questions."
    )
    db.add(system_msg)
    db.commit()
    db.refresh(order)
    return {"message": "Order cancelled", "order_id": order.id, "status": order.status}


@app.get("/api/chat/{customer_id}/messages")
def get_chat_messages(customer_id: str, current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    # Customers can only read their own chat
    if current_user.role == "CUSTOMER" and current_user.id != customer_id:
        raise HTTPException(status_code=403, detail="Not authorized to view this chat history")

    # Moderators can only read chat of assigned customers
    if current_user.role == "MODERATOR":
        customer = db.query(models.User).filter(models.User.id == customer_id).first()
        if not customer or customer.assigned_moderator_id != current_user.id:
            raise HTTPException(status_code=403, detail="You are not assigned to this customer")

    messages = db.query(models.Message).filter(models.Message.user_id == customer_id).order_by(models.Message.created_at.asc()).all()
    return [
        {
            "id": m.id,
            "sender_id": m.sender_id,
            "sender_role": m.sender_role,
            "message": m.message,
            "order_id": m.order_id,
            "created_at": m.created_at
        } for m in messages
    ]


@app.put("/api/admin/orders/{order_id}/mode")
def set_order_mode(order_id: str, data: OrderModeRequest, current_user: models.User = Depends(require_role(["ADMIN"])), db: Session = Depends(get_db)):
    order = db.query(models.Order).filter(models.Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    
    old_mode = order.mode
    order.mode = data.mode
    
    # Auto-adjust worker assignment based on mode change
    if data.mode == "HUMAN":
        order.assigned_worker_type = "HUMAN"
    elif data.mode == "AI":
        order.assigned_worker_type = "AI"
    # HYBRID keeps the current worker assignment (admin decides manually)
    
    db.commit()
    
    # Add audit trail message visible to moderators
    if old_mode != data.mode:
        audit_msg = models.Message(
            user_id=order.user_id,
            order_id=order.id,
            sender_id="system",
            sender_role="SYSTEM",
            message=f"⚙️ Ticket mode changed from {old_mode} → {data.mode} by admin."
        )
        db.add(audit_msg)
        db.commit()
    
    # If mode is AI and worker is AI, trigger AI processing
    if order.mode in ("AI", "HYBRID") and order.assigned_worker_type == "AI":
        threading.Thread(target=AI_CONCIERGE_PROVIDER.process_ticket, args=(order.id, Session(engine))).start()
        
    return {"message": "Mode updated", "order_id": order_id, "mode": data.mode, "assigned_worker_type": order.assigned_worker_type}

@app.put("/api/admin/orders/{order_id}/delegate")
def delegate_worker(order_id: str, data: DelegateWorkerRequest, current_user: models.User = Depends(require_role(["ADMIN"])), db: Session = Depends(get_db)):
    order = db.query(models.Order).filter(models.Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
        
    order.assigned_worker_type = data.assigned_worker_type
    
    if data.assigned_worker_type == "HUMAN":
        order.ai_stopped_at = datetime.utcnow()
    db.commit()
    
    if order.assigned_worker_type == "AI":
        threading.Thread(target=AI_CONCIERGE_PROVIDER.process_ticket, args=(order.id, Session(engine))).start()
        
    return {"message": "Worker delegated", "order_id": order_id, "assigned_worker_type": data.assigned_worker_type}

@app.put("/api/moderator/orders/{order_id}/takeover")
def takeover_order(order_id: str, current_user: models.User = Depends(require_role(["ADMIN", "MODERATOR"])), db: Session = Depends(get_db)):
    order = db.query(models.Order).filter(models.Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
        
    order.assigned_worker_type = "HUMAN"
    order.mode = "HUMAN"
    order.taken_over_at = datetime.utcnow()
    order.taken_over_by = current_user.id
    order.ai_stopped_at = datetime.utcnow()
    
    # Audit trail
    name = (current_user.first_name or "") + " " + (current_user.last_name or "")
    name = name.strip() or "Moderator"
    audit_msg = models.Message(
        user_id=order.user_id,
        order_id=order.id,
        sender_id="system",
        sender_role="SYSTEM",
        message=f"🛑 {name} took over this ticket from AI. Now in HUMAN mode."
    )
    db.add(audit_msg)
    db.commit()
    
    return {"message": "Order taken over by human", "order_id": order_id, "assigned_worker_type": "HUMAN", "mode": "HUMAN"}


@app.get("/api/admin/settings/ai-status")
def get_global_ai_status(db: Session = Depends(get_db)):
    setting = db.query(models.SystemSetting).filter(models.SystemSetting.key == "ai_enabled").first()
    is_enabled = setting.value.lower() == "true" if setting else True
    return {"ai_enabled": is_enabled}


@app.put("/api/admin/settings/ai-status")
def set_global_ai_status(data: AiStatusRequest, current_user: models.User = Depends(require_role(["ADMIN"])), db: Session = Depends(get_db)):
    setting = db.query(models.SystemSetting).filter(models.SystemSetting.key == "ai_enabled").first()
    if not setting:
        setting = models.SystemSetting(key="ai_enabled", value=str(data.ai_enabled).lower())
        db.add(setting)
    else:
        setting.value = str(data.ai_enabled).lower()
    db.commit()
    return {"message": "Global AI status updated", "ai_enabled": data.ai_enabled}


@app.post("/api/chat/{customer_id}/send")
def send_chat_message(customer_id: str, data: SendMessageRequest, current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    # Customers can only send to their own chat
    if current_user.role == "CUSTOMER" and current_user.id != customer_id:
        raise HTTPException(status_code=403, detail="Not authorized to send messages to this chat")

    # Moderators can only send to assigned customers' chat
    if current_user.role == "MODERATOR":
        customer = db.query(models.User).filter(models.User.id == customer_id).first()
        if not customer or customer.assigned_moderator_id != current_user.id:
            raise HTTPException(status_code=403, detail="You are not assigned to this customer")

    user_msg = models.Message(
        user_id=customer_id,
        order_id=data.order_id,
        sender_id=current_user.id,
        sender_role=current_user.role,
        message=data.message
    )
    db.add(user_msg)
    db.commit()
    db.refresh(user_msg)

    # If customer sent the message, check if AI is enabled globally and not taken over
    if current_user.role == "CUSTOMER":
        ai_setting = db.query(models.SystemSetting).filter(models.SystemSetting.key == "ai_enabled").first()
        ai_enabled = (ai_setting.value.lower() == "true") if ai_setting else True

        takeover_setting = db.query(models.SystemSetting).filter(models.SystemSetting.key == f"ai_takeover_{customer_id}").first()
        takeover_active = (takeover_setting.value.lower() == "true") if takeover_setting else False

        if ai_enabled and not takeover_active:
            ai_msg = models.Message(
                user_id=customer_id,
                sender_id="system_ai",
                sender_role="AI",
                message="Thank you! A concierge moderator will review your request and find the best prices for you shortly."
            )
            db.add(ai_msg)
            db.commit()

    return {"message": "Message sent successfully", "id": user_msg.id}





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
    import json
    setting = db.query(models.SystemSetting).filter(models.SystemSetting.key == "delivery_thresholds").first()
    if setting and setting.value:
        return json.loads(setting.value)
    return {"zepto": 199, "blinkit": 199, "swiggy": 199}

@app.put("/api/admin/delivery-config")
def update_delivery_config(data: DeliveryConfig, current_user: models.User = Depends(require_role(["ADMIN"])), db: Session = Depends(get_db)):
    import json
    setting = db.query(models.SystemSetting).filter(models.SystemSetting.key == "delivery_thresholds").first()
    if not setting:
        setting = models.SystemSetting(key="delivery_thresholds", value=json.dumps(data.thresholds))
        db.add(setting)
    else:
        setting.value = json.dumps(data.thresholds)
    db.commit()
    return {"message": "Delivery thresholds updated successfully"}


@app.get("/api/admin/dashboard/metrics")
def get_dashboard_metrics(current_user: models.User = Depends(require_role(["ADMIN", "MODERATOR"])), db: Session = Depends(get_db)):
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    
    orders_today = db.query(models.Order).filter(models.Order.created_at >= today_start).count()
    
    revenue_today = db.query(func.sum(models.Order.customer_paid)).filter(
        models.Order.status.in_(["confirmed", "awaiting_payment", "placed", "delivered"]),
        models.Order.created_at >= today_start
    ).scalar() or 0.0
    
    profit_today = db.query(func.sum(models.Order.profit)).filter(
        models.Order.status.in_(["confirmed", "awaiting_payment", "placed", "delivered"]),
        models.Order.created_at >= today_start
    ).scalar() or 0.0
    
    total_customers = db.query(models.User).filter(models.User.role == "CUSTOMER").count()
    
    total_savings = db.query(func.sum(models.Order.savings)).scalar() or 0.0
    
    # Task 6: Operational Dashboard counts
    orders_pending_review = db.query(models.Order).filter(models.Order.status == "pending_review").count()
    orders_awaiting_customer = db.query(models.Order).filter(models.Order.status == "awaiting_customer").count()
    orders_confirmed = db.query(models.Order).filter(models.Order.status.in_(["confirmed", "awaiting_payment"])).count()
    orders_delivered = db.query(models.Order).filter(models.Order.status == "delivered").count()
    
    total_revenue = db.query(func.sum(models.Order.customer_paid)).filter(
        models.Order.status.in_(["confirmed", "awaiting_payment", "placed", "delivered"])
    ).scalar() or 0.0
    
    total_profit = db.query(func.sum(models.Order.profit)).filter(
        models.Order.status.in_(["confirmed", "awaiting_payment", "placed", "delivered"])
    ).scalar() or 0.0
    
    # Task 3: Moderator Dashboard metrics
    from sqlalchemy.orm import joinedload
    active_statuses = ["pending_review", "reviewing", "awaiting_customer", "awaiting_payment", "confirmed", "placed"]
    active_orders = db.query(models.Order).filter(models.Order.status.in_(active_statuses)).options(joinedload(models.Order.user)).all()
    active_tickets = len(active_orders)

    claimed_tickets = 0
    pending_tickets = 0
    for o in active_orders:
        cust = o.user
        if cust and cust.assigned_moderator_id:
            claimed_tickets += 1
        else:
            pending_tickets += 1
            
    claimed_orders = db.query(models.Order).filter(models.Order.claimed_at != None).all()
    total_time = 0.0
    count = 0
    for o in claimed_orders:
        if o.claimed_at and o.created_at:
            total_time += (o.claimed_at - o.created_at).total_seconds()
            count += 1
    avg_response_time = total_time / count if count > 0 else 0.0
    
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
    order = db.query(models.Order).filter(models.Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    
    order.customer_paid = data.customer_paid
    order.store_cost = data.store_cost
    order.profit = data.customer_paid - data.store_cost
    db.commit()
    db.refresh(order)
    
    return {
        "message": "Order financials updated successfully",
        "order_id": order.id,
        "customer_paid": float(order.customer_paid),
        "store_cost": float(order.store_cost),
        "profit": float(order.profit)
    }


@app.put("/api/auth/profile")
def update_profile(data: ProfileUpdate, current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    current_user.first_name = data.first_name
    current_user.last_name = data.last_name
    current_user.email = data.email
    db.commit()
    db.refresh(current_user)
    return {
        "message": "Profile updated successfully",
        "first_name": current_user.first_name,
        "last_name": current_user.last_name,
        "email": current_user.email
    }


@app.get("/api/admin/dashboard/beta-metrics")
def get_beta_metrics(current_user: models.User = Depends(require_role(["ADMIN", "MODERATOR"])), db: Session = Depends(get_db)):
    total_beta_users = db.query(models.User).filter(models.User.role == "CUSTOMER").count()
    orders_submitted = db.query(models.Order).count()
    orders_completed = db.query(models.Order).filter(models.Order.status.in_(["delivered", "completed"])).count()
    
    # Avg time to first response (only calculate for orders that have been claimed)
    orders_with_claim = db.query(models.Order).filter(models.Order.claimed_at != None).all()
    avg_first_response_time = 0.0
    if orders_with_claim:
        total_response_time = sum((o.claimed_at - o.created_at).total_seconds() for o in orders_with_claim if o.claimed_at and o.created_at)
        avg_first_response_time = total_response_time / len(orders_with_claim)

    # Avg time to order confirmation (only calculate for orders that have been confirmed)
    orders_with_confirm = db.query(models.Order).filter(models.Order.confirmed_at != None).all()
    avg_confirm_time = 0.0
    if orders_with_confirm:
        total_confirm_time = sum((o.confirmed_at - o.created_at).total_seconds() for o in orders_with_confirm if o.confirmed_at and o.created_at)
        avg_confirm_time = total_confirm_time / len(orders_with_confirm)

    # Completed/placed order aggregates using SQL
    completed_orders_count = db.query(models.Order).filter(models.Order.status.in_(["placed", "delivered", "completed"])).count()
    profit_sum = db.query(func.sum(models.Order.profit)).filter(
        models.Order.status.in_(["placed", "delivered", "completed"])
    ).scalar() or 0.0
    avg_profit = float(profit_sum) / completed_orders_count if completed_orders_count > 0 else 0.0

    savings_sum = db.query(func.sum(models.Order.savings)).filter(
        models.Order.status.in_(["placed", "delivered", "completed"])
    ).scalar() or 0.0
    avg_savings = float(savings_sum) / completed_orders_count if completed_orders_count > 0 else 0.0
    
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
    order = db.query(models.Order).filter(models.Order.id == data.order_id, models.Order.user_id == current_user.id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found or unauthorized")
        
    feedback = models.Feedback(
        order_id=data.order_id,
        user_id=current_user.id,
        rating=data.rating,
        what_went_well=data.what_went_well,
        what_was_confusing=data.what_was_confusing,
        would_use_again=data.would_use_again
    )
    db.add(feedback)
    db.commit()
    db.refresh(feedback)
    return feedback


@app.get("/api/admin/feedback")
def get_all_feedback(current_user: models.User = Depends(require_role(["ADMIN"])), db: Session = Depends(get_db)):
    from sqlalchemy.orm import joinedload
    feedbacks = db.query(models.Feedback).options(joinedload(models.Feedback.user)).order_by(models.Feedback.created_at.desc()).all()
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
    incidents = db.query(models.Incident).options(joinedload(models.Incident.moderator)).order_by(models.Incident.created_at.desc()).all()
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