# SnapSave Platform Documentation

## Overview
SnapSave is a full-stack, real-time grocery concierge and price optimization platform. It bridges the gap between consumers looking for the best deals and multiple delivery services (like Zepto, Blinkit, Instamart, BigBasket, and JioMart) without requiring the user to app-hop. 

Instead of traditional cart building, SnapSave uses a chat-based concierge interface (with both AI and human-in-the-loop workflows) where customers can simply text their grocery list. A moderator (or AI) calculates the optimal cart split across stores, negotiates the best final price including delivery fees and platform discounts, and presents a final quote. Once the customer confirms, they make a single payment, and SnapSave handles the fulfillment.

## Architecture

SnapSave is built using a modern, decoupled architecture:

### 1. Frontend (`SnapSave-FRONTEND`)
- **Technology:** Vanilla JavaScript, HTML5, CSS3, with FontAwesome for iconography.
- **Architecture:** Single-Page Application (SPA) utilizing ES Modules (for the customer app) and IIFE scoping (for the admin app).
- **Communication:** RESTful API polling and bidirectional AJAX for chat.
- **Key Files:**
  - `index.html`: The customer-facing concierge interface. Includes the chat stream, order tracking stepper, grocery list builder, and order history sidebar.
  - `admin.html`: The secure, feature-rich operations console for Moderators and Admins. Includes ticket queue management, live chat monitoring, dynamic pricing entry, role management, and analytics dashboards.
  - `serve.py`: A lightweight Python HTTP server for local development, configured to disable caching for rapid iteration.

### 2. Backend (`SnapSave-Backend`)
- **Technology:** Python 3, FastAPI, SQLAlchemy, SQLite (Development).
- **Authentication:** Dual-layer authentication supporting Firebase Admin SDK for production and local PyJWT RS256 for local development and smoke tests.
- **Key Modules:**
  - `api/server.py`: The core FastAPI application containing 38 route endpoints for authentication, order management, chat processing, analytics, and admin controls.
  - `models.py`: Declarative SQLAlchemy models defining 10 database tables (`users`, `addresses`, `orders`, `order_items`, `messages`, etc.).
  - `database.py`: Database connection lifecycle and session management.

## Key Features & Standouts

### 1. Hybrid Chat-Based Ordering
The core customer experience mimics talking to a helpful store clerk. Customers can either build a structured list via a modal or simply type "I need 2 liters of milk and some eggs" into the chat. The system tracks the active order contextually.

### 2. Concierge Moderation Workflow
Instead of relying solely on error-prone scraping, SnapSave implements a robust human-in-the-loop moderation queue:
1. **Pending Review:** New orders enter the global queue.
2. **Reviewing (Claimed):** A moderator claims the ticket. They can chat with the customer to clarify requirements.
3. **Pricing Entry:** The moderator enters the lowest prices found for each item, selecting the optimal store. The system automatically calculates subtotal, platform fees, and savings.
4. **Awaiting Customer:** A detailed, itemized quote is sent to the customer for approval.
5. **Awaiting Payment:** Upon customer confirmation, an automated payment QR code is displayed.
6. **Placement & Delivery:** The moderator confirms payment receipt, inputs a delivery ETA, and marks the order as delivered once fulfilled.

### 3. "ChatGPT-style" Order History
SnapSave treats each order as a separate session. The customer interface features a sidebar where past orders are archived. Clicking a past order loads its historical chat log and final receipt in a read-only view, while a "+ New Order" button instantly provisions a fresh session.

### 4. Real-time Analytics & Moderation Dashboard
The admin panel includes comprehensive metrics:
- **Operational Dashboard:** Tracks today's revenue, profit margins, active tickets, average response times, and total customer savings.
- **Beta Metrics:** Tracks long-term KPIs like average time to first response and average profit per order.

### 5. Multi-Role RBAC (Role-Based Access Control)
The backend enforces strict security across three tiers:
- **CUSTOMER:** Can only view their own orders and chat.
- **MODERATOR:** Can view the queue, claim tickets, submit quotes, and chat with assigned customers.
- **ADMIN:** Has full access, including role promotion, user blacklisting, delivery fee configuration, global AI status toggles, and financial overrides.

### 6. Resilient Authentication Fallbacks
To ensure the platform can be developed and demoed offline or without active Firebase credentials, the backend dynamically falls back to generating and verifying its own cryptographically secure RS256 JWTs (`kid="test_kid"`).

## Setup & Execution

### Prerequisites
- Python 3.9+
- Node.js (Optional, for tooling)

### Running the Backend
```bash
cd SnapSave-Backend
pip install fastapi uvicorn sqlalchemy pyjwt cryptography firebase-admin python-dotenv requests
python -m uvicorn api.server:app --reload --port 8000
```

### Running the Frontend
```bash
cd SnapSave-FRONTEND
python -u serve.py
```
- Customer App: `http://localhost:3000/`
- Admin App: `http://localhost:3000/admin.html`

### Demo Credentials
- **Admin Phone:** `9999999999` (Automatically granted `ADMIN` privileges upon login)
- **Customer Phone:** Any valid 10-digit number (e.g., `9876543210`)

## Future Enhancements
- Re-integration of the fully autonomous AI scraper (currently toggled off in favor of the human-concierge MVP).
- Webhook integrations for automated store checkout.
- Razorpay/Stripe integration replacing static QR codes.