"""Every test uses a disposable database, never the configured application DB."""
import os
import sys
import tempfile
from pathlib import Path
import pytest

BACKEND=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(BACKEND))
os.environ["APP_ENV"]="test"
os.environ["ENABLE_DEV_AUTH"]="true"
os.environ["ENABLE_LIVE_RESEARCH"]="false"
os.environ["UPI_ID"]="audit@upi"
TEMP=tempfile.TemporaryDirectory(prefix="snapsave-tests-")
os.environ["DATABASE_URL"]="sqlite:///"+str(Path(TEMP.name)/"tests.db").replace("\\","/")

from api.server import app
from database import Base,engine,SessionLocal
import models
from fastapi.testclient import TestClient

@pytest.fixture(autouse=True)
def isolated_db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    stack=app.middleware_stack
    while stack:
        if hasattr(stack,"requests"):
            stack.requests.clear()
        stack=getattr(stack,"app",None)
    yield
    app.dependency_overrides.clear()

@pytest.fixture
def db():
    with SessionLocal() as session:
        yield session

@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c

@pytest.fixture
def actors(client,db):
    result={}
    for index,role in enumerate(["CUSTOMER","CUSTOMER","MODERATOR","MODERATOR","ADMIN"],1):
        uid=f"fixture_{index}"
        phone=f"+91123456780{index}"
        token=client.get("/api/auth/test-token",params={"phone":phone,"uid":uid}).json()["idToken"]
        headers={"Authorization":"Bearer "+token}
        me=client.get("/api/auth/me",headers=headers).json()
        user=db.get(models.User,uid)
        user.role=role
        db.commit()
        result[{1:"customer",2:"other",3:"moderator",4:"unassigned",5:"admin"}[index]]={"id":me["id"],"headers":headers,"phone":phone}
    return result

@pytest.fixture
def order(client,actors):
    customer=actors["customer"]
    address=client.post("/api/addresses",headers=customer["headers"],json={"title":"Home","street_address":"Example street","city":"Delhi","state":"Delhi","postal_code":"110001"}).json()
    created=client.post("/api/orders",headers=customer["headers"],json={"address_id":address["id"],"items":[{"name":"Amul milk 1L","quantity":2},{"name":"Bread","quantity":1}]}).json()
    created["address_id"]=address["id"]
    return created

@pytest.fixture
def quoted(client,actors,order):
    headers=actors["moderator"]["headers"]
    client.put(f"/api/moderator/orders/{order['id']}/claim",headers=headers)
    rows=[{"item_id":i["id"],"line_total":100,"store":"zepto"} for i in order["items"]]
    preview=client.post(f"/api/moderator/orders/{order['id']}/preview-quote",headers=headers,json={"items":rows}).json()
    response=client.post(f"/api/moderator/orders/{order['id']}/price",headers=headers,json=preview)
    assert response.status_code==200,response.text
    return response.json()

def pytest_sessionfinish(session,exitstatus):
    engine.dispose()
    TEMP.cleanup()
