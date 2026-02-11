from __future__ import annotations

from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import get_settings


class Base(DeclarativeBase):
    pass


@lru_cache(maxsize=1)
def get_engine():
    settings = get_settings()
    connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
    return create_engine(settings.database_url, connect_args=connect_args)


@lru_cache(maxsize=1)
def get_session_maker():
    return sessionmaker(autocommit=False, autoflush=False, bind=get_engine())


def init_db() -> None:
    from app.models import domain  # noqa: F401

    Base.metadata.create_all(bind=get_engine())


def get_db_session():
    session_maker = get_session_maker()
    db = session_maker()
    try:
        yield db
    finally:
        db.close()


def reset_db_cache() -> None:
    get_session_maker.cache_clear()
    get_engine.cache_clear()
