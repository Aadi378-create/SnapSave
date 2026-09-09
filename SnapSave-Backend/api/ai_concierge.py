import json
from datetime import datetime
from sqlalchemy.orm import Session
import models

class AI_CONCIERGE_PROVIDER:
    @staticmethod
    def process_ticket(order_id: str, db: Session):
        """
        Simulates an AI researching and finding prices.
        """
        order = db.query(models.Order).filter(models.Order.id == order_id).first()
        if not order:
            return
            
        # Check if AI is allowed globally
        setting = db.query(models.SystemSetting).filter(models.SystemSetting.key == "ai_enabled").first()
        is_enabled = setting.value.lower() == "true" if setting else True
        if not is_enabled:
            return

        # Pre-flight check: Is AI mode allowed for this order?
        if order.mode == "HUMAN" or order.assigned_worker_type != "AI":
            return
            
        # Pre-flight check: Do not override human prices
        if order.manual_prices and not order.is_ai_priced:
            return

        # Start AI action
        order.ai_started_at = datetime.utcnow()
        db.commit()

        # Simulate generating prices for items
        mock_prices = {
            "store": "zepto",
            "items": [],
            "subtotal": 0,
            "delivery_fee": 20.0,
            "platform_fee": 15.0,
            "store_discount": 0.0,
            "snapsave_discount": 0.0,
            "profit": 35.0,
            "final_price": 0
        }
        
        for idx, item in enumerate(order.items):
            # Mock price: 50.0 per unit
            mock_price = 50.0 * item.quantity
            mock_prices["items"].append({
                "item_id": item.id,
                "name": item.name,
                "unit_price": 50.0,
                "store": "zepto"
            })
            mock_prices["subtotal"] += mock_price

        mock_prices["final_price"] = mock_prices["subtotal"] + mock_prices["delivery_fee"] + mock_prices["platform_fee"] - mock_prices["store_discount"] - mock_prices["snapsave_discount"]
        
        order.manual_prices = json.dumps(mock_prices)
        order.is_ai_priced = True
        
        # Stop AI action
        order.ai_stopped_at = datetime.utcnow()
        
        # In HYBRID mode, just prepare the quote. In AI mode, also submit it to the customer.
        if order.mode == "AI":
            order.status = "awaiting_customer"
            order.store = "zepto"
            order.subtotal = mock_prices["subtotal"]
            order.delivery_fee = mock_prices["delivery_fee"]
            order.platform_fee = mock_prices["platform_fee"]
            order.store_discount = mock_prices["store_discount"]
            order.snapsave_discount = mock_prices["snapsave_discount"]
            order.final_price = mock_prices["final_price"]
            order.profit = mock_prices["profit"]
            order.savings = 0.0
            order.updated_at = datetime.utcnow()
            
            # Send quote message
            # Fetch the customer
            customer = db.query(models.User).filter(models.User.id == order.user_id).first()
            if customer:
                message = models.Message(
                    order_id=order.id,
                    user_id=customer.id,
                    sender_id="system_ai",
                    sender_role="AI",
                    message="I have found the best prices for your order. Tap Confirm Order to proceed."
                )
                db.add(message)
                
        db.commit()
