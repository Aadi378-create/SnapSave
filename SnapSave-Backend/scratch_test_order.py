import sys
import os
sys.path.append("C:\\Users\\LENOVO\\Desktop\\SnapSave-Backend")
from database import SessionLocal
import models
db = SessionLocal()
order = db.query(models.Order).first()
print("Order from DB:", order)
if order:
    print("Order ID:", order.id)
    print("Order status:", order.status)
    print("Order store:", order.store)
else:
    print("No orders found!")
