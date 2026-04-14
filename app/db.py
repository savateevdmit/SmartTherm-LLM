import logging
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from app.config import settings

log = logging.getLogger("kb_admin")


class Base(DeclarativeBase):
    pass


def make_engine():
    url = (
        f"mysql+pymysql://{settings.db_user}:{settings.db_password}"
        f"@{settings.db_host}:{settings.db_port}/{settings.db_name}"
        f"?charset=utf8mb4"
    )
    return create_engine(
        url,
        pool_pre_ping=True,
        pool_recycle=1800,
        pool_size=10,
        max_overflow=20,
        connect_args={"connect_timeout": 10},
    )


engine = None
SessionLocal = None


def init_db():
    global engine, SessionLocal
    try:
        engine = make_engine()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
        log.info("Database connection pool established.")
    except Exception as e:
        log.error("Failed to connect to database: %s", e)
        raise


def get_db():
    if SessionLocal is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()