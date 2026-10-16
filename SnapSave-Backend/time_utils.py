"""Naive UTC timestamps match the existing database schema."""
from datetime import datetime,timezone

def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)
