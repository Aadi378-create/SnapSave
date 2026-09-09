import pytest
from fastapi.testclient import TestClient
import uuid

# Assume the main app and db is accessible via api.server
from api.server import app
from database import SessionLocal
import models

client = TestClient(app)

@pytest.fixture(scope="module")
def db():
    db = SessionLocal()
    yield db
    db.close()

@pytest.fixture
def test_admin(db):
    admin = db.query(models.User).filter(models.User.email == "test_ai_admin@snapsave.com").first()
    if not admin:
        admin = models.User(
            id=str(uuid.uuid4()),
            email="test_ai_admin@snapsave.com",
            phone_number="+910000000010",
            password_hash="fakehash",
            role="ADMIN"
        )
        db.add(admin)
        db.commit()
    return admin

@pytest.fixture
def test_moderator(db):
    mod = db.query(models.User).filter(models.User.email == "test_ai_mod@snapsave.com").first()
    if not mod:
        mod = models.User(
            id=str(uuid.uuid4()),
            email="test_ai_mod@snapsave.com",
            phone_number="+910000000011",
            password_hash="fakehash",
            role="MODERATOR"
        )
        db.add(mod)
        db.commit()
    return mod

@pytest.fixture
def test_customer(db):
    cust = db.query(models.User).filter(models.User.email == "test_ai_cust@snapsave.com").first()
    if not cust:
        cust = models.User(
            id=str(uuid.uuid4()),
            email="test_ai_cust@snapsave.com",
            phone_number="+910000000012",
            password_hash="fakehash",
            role="CUSTOMER"
        )
        db.add(cust)
        db.commit()
    return cust

def get_token(user_id, phone):
    # Generates a test token using the debug token endpoint or manually
    response = client.get(f"/api/auth/test-token?uid={user_id}&phone={phone}")
    return response.json()["idToken"]

def test_human_ticket_ai_cannot_act(db, test_admin, test_customer):
    order = models.Order(
        id=str(uuid.uuid4()),
        user_id=test_customer.id,
        store="any",
        delivery_street="123",
        delivery_city="City",
        delivery_postal_code="12345",
        subtotal=0, delivery_fee=0, platform_fee=0, final_price=0,
        mode="HUMAN",
        assigned_worker_type="HUMAN"
    )
    db.add(order)
    db.commit()

    from api.ai_concierge import AI_CONCIERGE_PROVIDER
    AI_CONCIERGE_PROVIDER.process_ticket(order.id, db)
    db.refresh(order)
    
    assert order.is_ai_priced == False
    assert order.manual_prices is None
    
def test_admin_assigns_ai_can_act(db, test_admin, test_customer):
    order = models.Order(
        id=str(uuid.uuid4()),
        user_id=test_customer.id,
        store="any",
        delivery_street="123",
        delivery_city="City",
        delivery_postal_code="12345",
        subtotal=0, delivery_fee=0, platform_fee=0, final_price=0,
        mode="AI",
        assigned_worker_type="AI"
    )
    db.add(order)
    db.commit()

    from api.ai_concierge import AI_CONCIERGE_PROVIDER
    AI_CONCIERGE_PROVIDER.process_ticket(order.id, db)
    db.refresh(order)
    
    assert order.is_ai_priced == True
    assert order.manual_prices is not None
    assert order.status == "awaiting_customer"

def test_moderator_takeover_halts_ai(db, test_admin, test_moderator, test_customer):
    order = models.Order(
        id=str(uuid.uuid4()),
        user_id=test_customer.id,
        store="any",
        delivery_street="123",
        delivery_city="City",
        delivery_postal_code="12345",
        subtotal=0, delivery_fee=0, platform_fee=0, final_price=0,
        mode="AI",
        assigned_worker_type="AI"
    )
    db.add(order)
    db.commit()

    token = get_token(test_moderator.id, test_moderator.phone_number)
    response = client.put(f"/api/moderator/orders/{order.id}/takeover", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    
    db.refresh(order)
    assert order.assigned_worker_type == "HUMAN"
    assert order.taken_over_by == test_moderator.id
    
    # AI should not act now
    from api.ai_concierge import AI_CONCIERGE_PROVIDER
    AI_CONCIERGE_PROVIDER.process_ticket(order.id, db)
    db.refresh(order)
    assert order.is_ai_priced == False

def test_human_edited_price_not_overwritten(db, test_admin, test_customer):
    order = models.Order(
        id=str(uuid.uuid4()),
        user_id=test_customer.id,
        store="any",
        delivery_street="123",
        delivery_city="City",
        delivery_postal_code="12345",
        subtotal=0, delivery_fee=0, platform_fee=0, final_price=0,
        mode="AI",
        assigned_worker_type="AI",
        manual_prices='[{"name": "human price", "unit_price": 100.0}]',
        is_ai_priced=False # Human edited!
    )
    db.add(order)
    db.commit()

    from api.ai_concierge import AI_CONCIERGE_PROVIDER
    AI_CONCIERGE_PROVIDER.process_ticket(order.id, db)
    db.refresh(order)
    
    # AI should not overwrite human price
    assert order.is_ai_priced == False
    assert "human price" in order.manual_prices
