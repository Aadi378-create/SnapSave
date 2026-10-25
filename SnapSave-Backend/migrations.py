"""Additive, versioned migrations; no customer records are discarded."""
from sqlalchemy import inspect, text
import models

def migrate(engine):
    inspector = inspect(engine)
    tables = inspector.get_table_names()
    old_items = "order_items" in tables and "line_total" not in {c["name"] for c in inspector.get_columns("order_items")}
    old_assignment = "orders" in tables and "assigned_moderator_id" not in {c["name"] for c in inspector.get_columns("orders")}
    defaults = {"order_revision":"0","revision": "0", "service_fee": "0", "mode": "'HUMAN'", "assigned_worker_type": "'HUMAN'", "is_ai_priced": "false", "coordinates_verified": "false", "payment_status": "'unpaid'", "kind": "'text'", "is_blacklisted": "false", "maintenance_mode": "false"}
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY)"))
        for table in models.Base.metadata.sorted_tables:
            if table.name not in tables:
                continue
            present = {c["name"] for c in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in present:
                    continue
                sql_type = column.type.compile(dialect=engine.dialect)
                default = defaults.get(column.name)
                suffix = f" DEFAULT {default}" if default is not None else ""
                if default is not None and not column.nullable:
                    suffix += " NOT NULL"
                if column.foreign_keys:
                    foreign = next(iter(column.foreign_keys))
                    parent, field = foreign.target_fullname.rsplit(".", 1)
                    suffix += f' REFERENCES "{parent}"("{field}")'
                    if foreign.ondelete:
                        suffix += f" ON DELETE {foreign.ondelete}"
                conn.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {sql_type}{suffix}'))
        if old_items:
            # The old human editor stored line totals in the unit_price column.
            conn.execute(text("UPDATE order_items SET line_total = unit_price WHERE order_id IN (SELECT id FROM orders WHERE is_ai_priced = false)"))
            conn.execute(text("UPDATE order_items SET line_total = unit_price * quantity WHERE order_id IN (SELECT id FROM orders WHERE is_ai_priced = true)"))
            conn.execute(text("UPDATE order_items SET unit_price = line_total * 1.0 / quantity WHERE line_total IS NOT NULL AND quantity > 0"))
        if old_assignment:
            conn.execute(text("UPDATE orders SET assigned_moderator_id = (SELECT assigned_moderator_id FROM users WHERE users.id = orders.user_id) WHERE status IN ('reviewing', 'awaiting_customer', 'awaiting_payment', 'placed')"))
        if engine.dialect.name == "postgresql":
            for table, column in [("orders", "manual_prices"), ("messages", "message"), ("help_messages", "message"), ("system_settings", "value")]:
                if table in tables:
                    conn.execute(text(f'ALTER TABLE "{table}" ALTER COLUMN "{column}" TYPE TEXT'))
        conn.execute(text("INSERT INTO schema_migrations(version) SELECT 1 WHERE NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version=1)"))
        if not conn.execute(text("SELECT version FROM schema_migrations WHERE version=2")).first():
            # Existing records lack bank-verification evidence. Flag them for
            # review instead of treating legacy fulfilled orders as unpaid.
            conn.execute(text("""UPDATE orders SET payment_status='reconciliation_required'
                WHERE COALESCE(payment_status,'unpaid')='unpaid' AND (
                    status IN ('placed','delivered','completed') OR
                    (status='cancelled' AND (COALESCE(customer_paid,0)>0 OR confirmed_at IS NOT NULL)))"""))
            conn.execute(text("INSERT INTO schema_migrations(version) VALUES (2)"))
        conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_order_request_idx ON orders(user_id, request_key)"))
        payment_duplicates=conn.execute(text("SELECT payment_reference FROM orders WHERE payment_reference IS NOT NULL GROUP BY payment_reference HAVING COUNT(*) > 1 LIMIT 1")).first()
        if not payment_duplicates:
            conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_order_payment_reference_idx ON orders(payment_reference)"))
        # Legacy duplicate feedback is preserved. Application transactions prevent
        # further duplicates; a uniqueness index is added when existing data allows it.
        duplicates = conn.execute(text("SELECT order_id FROM feedbacks GROUP BY order_id HAVING COUNT(*) > 1 LIMIT 1")).first()
        if not duplicates:
            conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_feedback_order_idx ON feedbacks(order_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_message_thread ON messages(user_id, order_id, created_at, id)"))

        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_order_history_cursor ON orders(user_id,created_at,id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_order_queue_cursor ON orders(status,created_at,id)"))
