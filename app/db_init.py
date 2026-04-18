import logging
from sqlalchemy import text as sql_text
from sqlalchemy.exc import SQLAlchemyError

from app.config import settings

log = logging.getLogger("kb_admin")

REQUIRED_TABLES = ("admins", "questions", "answers")


def _get_existing_columns(conn, db_name: str, table_name: str) -> set:
    rows = conn.execute(
        sql_text("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = :db AND table_name = :tbl
        """),
        {"db": db_name, "tbl": table_name},
    ).fetchall()
    return {r[0] for r in rows}


def _table_exists(conn, db_name: str, table_name: str) -> bool:
    rows = conn.execute(
        sql_text("""
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = :db AND table_name = :tbl
        """),
        {"db": db_name, "tbl": table_name},
    ).fetchall()
    return len(rows) > 0


def _ensure_questions_columns(conn, db_name: str):
    existing = _get_existing_columns(conn, db_name, "questions")

    if "embedding" in existing:
        rows = conn.execute(
            sql_text("""
                SELECT is_nullable
                FROM information_schema.columns
                WHERE table_schema = :db AND table_name = 'questions' AND column_name = 'embedding'
            """),
            {"db": db_name},
        ).fetchall()
        if rows and rows[0][0].upper() == "NO":
            try:
                conn.execute(sql_text(
                    "ALTER TABLE questions MODIFY COLUMN embedding BLOB NULL"
                ))
                log.info("Made questions.embedding nullable")
            except Exception:
                pass

    if "is_verified" not in existing:
        conn.execute(sql_text(
            "ALTER TABLE questions ADD COLUMN is_verified TINYINT(1) NOT NULL DEFAULT 1"
        ))
        log.info("Added column questions.is_verified")

    if "created_by_id" not in existing:
        conn.execute(sql_text(
            "ALTER TABLE questions ADD COLUMN created_by_id INT NULL"
        ))
        log.info("Added column questions.created_by_id")

    if "reviewed_by_id" not in existing:
        conn.execute(sql_text(
            "ALTER TABLE questions ADD COLUMN reviewed_by_id INT NULL"
        ))
        log.info("Added column questions.reviewed_by_id")

    if "review_status" not in existing:
        conn.execute(sql_text(
            "ALTER TABLE questions ADD COLUMN review_status ENUM('pending','accepted','rejected') NULL"
        ))
        log.info("Added column questions.review_status")


def _ensure_admin_role_enum(conn, db_name: str):
    rows = conn.execute(
        sql_text("""
            SELECT column_type
            FROM information_schema.columns
            WHERE table_schema = :db AND table_name = 'admins' AND column_name = 'role'
        """),
        {"db": db_name},
    ).fetchall()
    if rows:
        col_type = rows[0][0].lower()
        if "volunteer" not in col_type:
            conn.execute(sql_text(
                "ALTER TABLE admins MODIFY COLUMN role ENUM('admin','operator','volunteer') NOT NULL DEFAULT 'admin'"
            ))
            log.info("Updated admins.role enum to include 'volunteer'")


def _ensure_volunteer_notifications(conn, db_name: str):
    if not _table_exists(conn, db_name, "volunteer_notifications"):
        conn.execute(sql_text("""
            CREATE TABLE volunteer_notifications (
                id INT AUTO_INCREMENT PRIMARY KEY,
                volunteer_id INT NOT NULL,
                question_id INT NULL,
                question_text VARCHAR(500) NOT NULL,
                verdict ENUM('accepted','rejected') NOT NULL,
                is_read TINYINT(1) NOT NULL DEFAULT 0,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (volunteer_id) REFERENCES admins(id) ON DELETE CASCADE,
                FOREIGN KEY (question_id) REFERENCES questions(id) ON DELETE SET NULL
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """))
        log.info("Created table volunteer_notifications")
        return

    existing = _get_existing_columns(conn, db_name, "volunteer_notifications")

    if "pending_question_id" in existing and "question_id" not in existing:
        try:
            conn.execute(sql_text(
                "ALTER TABLE volunteer_notifications ADD COLUMN question_id INT NULL AFTER volunteer_id"
            ))
            try:
                conn.execute(sql_text(
                    "ALTER TABLE volunteer_notifications ADD FOREIGN KEY (question_id) "
                    "REFERENCES questions(id) ON DELETE SET NULL"
                ))
            except Exception:
                pass
            conn.execute(sql_text(
                "UPDATE volunteer_notifications SET question_id = pending_question_id"
            ))
            log.info("Migrated volunteer_notifications.pending_question_id -> question_id")
        except Exception:
            pass

    if "question_id" not in existing:
        conn.execute(sql_text(
            "ALTER TABLE volunteer_notifications ADD COLUMN question_id INT NULL AFTER volunteer_id"
        ))
        try:
            conn.execute(sql_text(
                "ALTER TABLE volunteer_notifications ADD FOREIGN KEY (question_id) "
                "REFERENCES questions(id) ON DELETE SET NULL"
            ))
        except Exception:
            pass
        log.info("Added column volunteer_notifications.question_id")

    if "question_text_preview" in existing and "question_text" not in existing:
        conn.execute(sql_text(
            "ALTER TABLE volunteer_notifications ADD COLUMN question_text VARCHAR(500) NOT NULL DEFAULT '' AFTER question_id"
        ))
        conn.execute(sql_text(
            "UPDATE volunteer_notifications SET question_text = question_text_preview"
        ))
        log.info("Migrated volunteer_notifications.question_text_preview -> question_text")

    if "question_text" not in existing and "question_text_preview" not in existing:
        conn.execute(sql_text(
            "ALTER TABLE volunteer_notifications ADD COLUMN question_text VARCHAR(500) NOT NULL DEFAULT ''"
        ))
        log.info("Added column volunteer_notifications.question_text")

    if "verdict" not in existing:
        conn.execute(sql_text(
            "ALTER TABLE volunteer_notifications ADD COLUMN verdict ENUM('accepted','rejected') NOT NULL DEFAULT 'accepted'"
        ))
        log.info("Added column volunteer_notifications.verdict")

    if "dismissed" in existing and "is_read" not in existing:
        conn.execute(sql_text(
            "ALTER TABLE volunteer_notifications ADD COLUMN is_read TINYINT(1) NOT NULL DEFAULT 0"
        ))
        conn.execute(sql_text(
            "UPDATE volunteer_notifications SET is_read = dismissed"
        ))
        log.info("Migrated volunteer_notifications.dismissed -> is_read")

    if "is_read" not in existing and "dismissed" not in existing:
        conn.execute(sql_text(
            "ALTER TABLE volunteer_notifications ADD COLUMN is_read TINYINT(1) NOT NULL DEFAULT 0"
        ))
        log.info("Added column volunteer_notifications.is_read")

    if "created_at" not in existing:
        conn.execute(sql_text(
            "ALTER TABLE volunteer_notifications ADD COLUMN created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP"
        ))
        log.info("Added column volunteer_notifications.created_at")


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

            _ensure_questions_columns(conn, db_name)
            _ensure_admin_role_enum(conn, db_name)
            _ensure_volunteer_notifications(conn, db_name)

            conn.commit()

            log.info("DB schema OK in '%s' (%s)", db_name, ", ".join(REQUIRED_TABLES))

    except SQLAlchemyError as e:
        log.exception("DB schema check failed")
        raise RuntimeError(f"DB schema check failed: {e}") from e