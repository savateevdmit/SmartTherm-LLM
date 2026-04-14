import logging
from sqlalchemy import text as sql_text
from sqlalchemy.exc import SQLAlchemyError

from app.config import settings

log = logging.getLogger("kb_admin")

REQUIRED_TABLES = ("admins", "questions", "answers")


def check_schema_or_raise() -> None:
    from app.db import engine

    if engine is None:
        raise RuntimeError(
            "DB engine not initialized. Call init_db() before check_schema_or_raise()."
        )

    try:
        log.info(
            "DB connect target: host=%s port=%s db=%s",
            settings.db_host,
            settings.db_port,
            settings.db_name,
        )

        db_name = (engine.url.database or settings.db_name or "").strip()
        if not db_name:
            raise RuntimeError("DB_NAME is empty (no database selected). Check env DB_NAME.")

        with engine.connect() as conn:
            conn.execute(sql_text("SELECT 1"))

            rows = conn.execute(
                sql_text("""
                    SELECT table_name
                    FROM information_schema.tables
                    WHERE table_schema = :db
                """),
                {"db": db_name},
            ).fetchall()

            existing = {r[0] for r in rows}
            missing = [t for t in REQUIRED_TABLES if t not in existing]

            if missing:
                raise RuntimeError(
                    f"Database schema is missing required tables in '{db_name}': "
                    + ", ".join(missing)
                    + ". Ensure the app points to the compose DB (DB_HOST=db, DB_PORT=3306) "
                      "and that db_restore restored a valid backup in ./backups."
                )

            log.info("DB schema OK in '%s' (%s)", db_name, ", ".join(REQUIRED_TABLES))

    except SQLAlchemyError as e:
        log.exception("DB schema check failed")
        raise RuntimeError(f"DB schema check failed: {e}") from e