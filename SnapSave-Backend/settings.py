"""Explicit environment flags. Production behavior is the default."""
import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

def flag(name):
    return os.getenv(name, "false").lower() == "true"

def dev_auth_enabled():
    return os.getenv("APP_ENV", "production") in {"development", "test"} and flag("ENABLE_DEV_AUTH")

def research_enabled():
    return flag("ENABLE_LIVE_RESEARCH") and research_provider() is not None

def research_provider():
    """Providers are explicitly configured server code, never request parameters."""
    from importlib import import_module
    path = os.getenv("RESEARCH_PROVIDER", "")
    if ":" not in path:
        return None
    module, name = path.split(":", 1)
    try:
        provider = getattr(import_module(module), name)
        return provider if callable(provider) else None
    except (ImportError, AttributeError):
        return None

STORES = {"zepto", "blinkit", "instamart", "bigbasket", "jiomart"}
ACTIVE_STATUSES = {"pending_review", "reviewing", "awaiting_customer", "awaiting_payment", "placed"}
TERMINAL_STATUSES = {"delivered", "completed", "cancelled"}
