import os
import logging
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

logger = logging.getLogger(__name__)

class Base(DeclarativeBase):
    pass

def _db_path():
    d = os.path.dirname(__file__)
    p = os.path.join(d, "annotation2.db")
    return p

DATABASE_URL = "sqlite:///" + _db_path()
engine = create_engine(DATABASE_URL, future=True, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False, autocommit=False)

def init_db():
    from . import schema
    Base.metadata.create_all(bind=engine)
    return True

def get_session():
    return SessionLocal()