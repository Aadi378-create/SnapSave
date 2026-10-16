import os
from pathlib import Path
from sqlalchemy import create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import declarative_base, sessionmaker
from settings import BASE_DIR

def configured_database_url(value):
    url=make_url(value)
    name=url.database
    if url.get_backend_name()=="sqlite" and name and name!=":memory:" and not name.startswith("file:"):
        path=Path(name)
        if not path.is_absolute():
            url=url.set(database=(BASE_DIR/path).resolve().as_posix())
    return url

DATABASE_URL = configured_database_url(os.getenv("DATABASE_URL", "sqlite:///" + (BASE_DIR / "snapsave.db").as_posix()))
connect_args = {"check_same_thread": False, "timeout": 15} if DATABASE_URL.get_backend_name()=="sqlite" else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args, pool_pre_ping=True)
if engine.dialect.name == "sqlite":
    @event.listens_for(engine, "connect")
    def configure_sqlite(connection, record):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=15000")
        cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    with SessionLocal() as db:
        try:
            yield db
        except Exception:
            db.rollback()
            raise
