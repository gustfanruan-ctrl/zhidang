from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from .config import settings

engine_kwargs = {
    "future": True,
    "pool_pre_ping": True,
}

# Keep SQLite dev mode lightweight while giving PostgreSQL a larger explicit
# pool for the single-worker production runtime.
if not settings.database_url.startswith("sqlite"):
    engine_kwargs.update(
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_pool_max_overflow,
        pool_timeout=settings.db_pool_timeout,
        pool_recycle=settings.db_pool_recycle,
    )

engine = create_engine(settings.database_url, **engine_kwargs)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
