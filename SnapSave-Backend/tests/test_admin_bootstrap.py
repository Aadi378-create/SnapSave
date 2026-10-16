import pytest
import models
from bootstrap_admin import promote_admin
from database import configured_database_url
from settings import BASE_DIR

def test_relative_database_path_is_independent_of_launch_directory(tmp_path,monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert configured_database_url("sqlite:///./snapsave.db").database==(BASE_DIR/"snapsave.db").as_posix()
    assert configured_database_url("sqlite:///:memory:").database==":memory:"
    assert configured_database_url("sqlite:///file::memory:?cache=shared&uri=true").database=="file::memory:"
    absolute=(tmp_path/"explicit.db").as_posix()
    assert configured_database_url("sqlite:///"+absolute).database==absolute

def test_private_phone_promotion_preserves_existing_identity(client,actors,db):
    customer=actors["customer"]
    user=promote_admin(db,phone=customer["phone"])
    assert user.id==customer["id"] and user.role=="ADMIN"
    assert client.get("/api/auth/me",headers=customer["headers"]).json()["role"]=="ADMIN"
    assert promote_admin(db,phone=customer["phone"]).id==user.id

def test_bootstrap_rejects_unknown_or_ambiguous_identity(db):
    with pytest.raises(ValueError,match="No account"):
        promote_admin(db,phone="1234567890")
    db.add_all([models.User(id="a",email="a@example.com",password_hash="firebase",phone_number="+911234567890"),models.User(id="b",email="b@example.com",password_hash="firebase",phone_number="1234567890")])
    db.commit()
    with pytest.raises(ValueError,match="Multiple matching"):
        promote_admin(db,phone="1234567890")
    assert {u.role for u in db.query(models.User).all()}=={"CUSTOMER"}

def test_existing_email_bootstrap_remains_supported(db):
    db.add(models.User(id="email-user",email="admin@example.com",password_hash="firebase"));db.commit()
    assert promote_admin(db,email="ADMIN@EXAMPLE.COM").role=="ADMIN"
