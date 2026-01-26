from sqlalchemy import (
    Column,
    Integer,
    String,
    TIMESTAMP,
    ForeignKey,
    Enum,
    text as sql_text,
)
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

from app.db import Base


class Question(Base):
    __tablename__ = "questions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    text = Column(String(500), nullable=False)

    # VECTOR type is DB-specific; we won't map it as JSON anymore.
    # We'll write it via raw SQL: embedding = VEC_FromText(:emb_json)
    embedding = Column("embedding", nullable=True)

    tags = Column(String(255), nullable=True)
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp(), nullable=False)

    answers = relationship("Answer", back_populates="question", cascade="all, delete-orphan")


class Answer(Base):
    __tablename__ = "answers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    question_id = Column(Integer, ForeignKey("questions.id", ondelete="CASCADE"), nullable=False)
    text = Column(String(2000), nullable=False)

    # visual_path stores list of ints (media ids) in JSON column in MySQL
    # Keep JSON in answers, as before.
    from sqlalchemy.dialects.mysql import JSON as MYSQL_JSON
    visual_path = Column(MYSQL_JSON, nullable=True)

    created_at = Column(TIMESTAMP, server_default=func.current_timestamp(), nullable=False)

    question = relationship("Question", back_populates="answers")


class Admin(Base):
    __tablename__ = "admins"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(50), nullable=False, unique=True)
    password_hash = Column(String(255), nullable=False)
    role = Column(Enum("admin", "operator"), default="admin", nullable=False)
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp(), nullable=False)