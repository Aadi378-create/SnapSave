import uuid
from datetime import datetime
from sqlalchemy import Column, String, Integer, ForeignKey, Boolean, DateTime, Numeric
from sqlalchemy.orm import relationship
from database import Base

class User(Base):
    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    email = Column(String(255), unique=True, nullable=False, index=True)
    phone_number = Column(String(20), unique=True, nullable=True, index=True)
    password_hash = Column(String(255), nullable=False)
    first_name = Column(String(100), nullable=True)
    last_name = Column(String(100), nullable=True)
    membership_tier = Column(String(50), default="standard")
    completed_orders_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Human-Concierge additions
    role = Column(String(50), default="CUSTOMER")  # "CUSTOMER", "MODERATOR", "ADMIN"
    assigned_moderator_id = Column(String(36), ForeignKey("users.id"), nullable=True)

    # Moderation / safety
    is_blacklisted = Column(Boolean, default=False)
    blacklist_reason = Column(String(500), nullable=True)

    # Relationships
    addresses = relationship("Address", back_populates="user", cascade="all, delete-orphan")
    orders = relationship("Order", foreign_keys="[Order.user_id]", back_populates="user")


class Address(Base):
    __tablename__ = "addresses"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(50), nullable=False)  # e.g., "Home", "Work"
    street_address = Column(String(500), nullable=False)
    city = Column(String(100), nullable=False)
    state = Column(String(100), nullable=False)
    postal_code = Column(String(20), nullable=False)
    latitude = Column(Numeric(9, 6), nullable=False)
    longitude = Column(Numeric(9, 6), nullable=False)
    is_default = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    user = relationship("User", back_populates="addresses")
    orders = relationship("Order", back_populates="address")


class Order(Base):
    __tablename__ = "orders"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    address_id = Column(String(36), ForeignKey("addresses.id", ondelete="SET NULL"), nullable=True, index=True)
    store = Column(String(100), nullable=False)
    status = Column(String(50), nullable=False, default="pending_review", index=True)  # "pending_review", "reviewing", etc.
    
    # Address Snapshot fields (frozen copy)
    delivery_street = Column(String(500), nullable=False)
    delivery_city = Column(String(100), nullable=False)
    delivery_postal_code = Column(String(20), nullable=False)

    # Financial metrics
    subtotal = Column(Numeric(10, 2), nullable=False)
    delivery_fee = Column(Numeric(10, 2), nullable=False)
    platform_fee = Column(Numeric(10, 2), nullable=False)
    store_discount = Column(Numeric(10, 2), default=0.00)
    snapsave_discount = Column(Numeric(10, 2), default=0.00)
    final_price = Column(Numeric(10, 2), nullable=False)
    savings = Column(Numeric(10, 2), default=0.00)
    
    # Human-Concierge additions
    manual_prices = Column(String(1000), nullable=True)  # JSON string representing manual prices
    customer_paid = Column(Numeric(10, 2), default=0.00)
    store_cost = Column(Numeric(10, 2), default=0.00)
    profit = Column(Numeric(10, 2), default=0.00)

    # AI Concierge Additions
    mode = Column(String(50), nullable=False, default="HUMAN")
    assigned_worker_type = Column(String(50), nullable=False, default="HUMAN")
    ai_started_at = Column(DateTime, nullable=True)
    ai_stopped_at = Column(DateTime, nullable=True)
    taken_over_at = Column(DateTime, nullable=True)
    taken_over_by = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    is_ai_priced = Column(Boolean, nullable=False, default=False)

    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    claimed_at = Column(DateTime, nullable=True)
    confirmed_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    user = relationship("User", foreign_keys=[user_id], back_populates="orders")
    taken_over_by_user = relationship("User", foreign_keys=[taken_over_by])
    address = relationship("Address", back_populates="orders")
    items = relationship("OrderItem", back_populates="order", cascade="all, delete-orphan")


class OrderItem(Base):
    __tablename__ = "order_items"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    order_id = Column(String(36), ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    quantity = Column(Integer, nullable=False, default=1)
    # Filled in by the moderator: the lowest price found and the store it was found at
    unit_price = Column(Numeric(10, 2), nullable=True)
    store = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    order = relationship("Order", back_populates="items")


class SystemSetting(Base):
    __tablename__ = "system_settings"

    key = Column(String(100), primary_key=True)
    value = Column(String(255), nullable=False)


class Message(Base):
    __tablename__ = "messages"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    order_id = Column(String(36), nullable=True, index=True)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    sender_id = Column(String(36), nullable=False)  # User ID or "system_ai"
    sender_role = Column(String(50), nullable=False)  # "CUSTOMER", "MODERATOR", "ADMIN", "AI"
    message = Column(String(1000), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class AppSetting(Base):
    __tablename__ = "app_settings"

    id = Column(Integer, primary_key=True, default=1)
    orders_enabled = Column(Boolean, default=True, nullable=False)
    maintenance_mode = Column(Boolean, default=False, nullable=False)


class HelpMessage(Base):
    """Customer <-> Admin support thread, independent of the order chat. Admin-only visibility."""
    __tablename__ = "help_messages"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    sender_role = Column(String(50), nullable=False)  # "CUSTOMER" or "ADMIN"
    message = Column(String(1000), nullable=False)
    is_resolved = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    user = relationship("User")


class Feedback(Base):
    __tablename__ = "feedbacks"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    order_id = Column(String(36), ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    rating = Column(Integer, nullable=False)
    what_went_well = Column(String(1000), nullable=True)
    what_was_confusing = Column(String(1000), nullable=True)
    would_use_again = Column(Boolean, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    order = relationship("Order")
    user = relationship("User")


class Incident(Base):
    __tablename__ = "incidents"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    order_id = Column(String(36), ForeignKey("orders.id", ondelete="SET NULL"), nullable=True, index=True)
    moderator_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    incident_type = Column(String(100), nullable=False)  # "Wrong price entered", "Customer confusion", etc.
    notes = Column(String(1000), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    order = relationship("Order")
    moderator = relationship("User")
