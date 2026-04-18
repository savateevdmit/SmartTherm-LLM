from sqlalchemy import (
    Column,
    Integer,
    String,
    TIMESTAMP,
    ForeignKey,
    Enum,
    Boolean,
    text as sql_text,
)
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

from app.db import Base


class Question(Base):
    __tablename__ = "questions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    text = Column(String(500), nullable=False)
    embedding = Column("embedding", nullable=True)

    tags = Column(String(255), nullable=True)
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp(), nullable=False)

    is_verified = Column(Boolean, nullable=False, server_default=sql_text("1"))
    created_by_id = Column(Integer, ForeignKey("admins.id", ondelete="SET NULL"), nullable=True)
    reviewed_by_id = Column(Integer, ForeignKey("admins.id", ondelete="SET NULL"), nullable=True)
    review_status = Column(Enum("pending", "accepted", "rejected"), nullable=True)

    answers = relationship("Answer", back_populates="question", cascade="all, delete-orphan")
    created_by = relationship("Admin", foreign_keys=[created_by_id])
    reviewed_by = relationship("Admin", foreign_keys=[reviewed_by_id])


class Answer(Base):
    __tablename__ = "answers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    question_id = Column(Integer, ForeignKey("questions.id", ondelete="CASCADE"), nullable=False)
    text = Column(String(2000), nullable=False)

    from sqlalchemy.dialects.mysql import JSON as MYSQL_JSON
    visual_path = Column(MYSQL_JSON, nullable=True)

    created_at = Column(TIMESTAMP, server_default=func.current_timestamp(), nullable=False)

    question = relationship("Question", back_populates="answers")


class Admin(Base):
    __tablename__ = "admins"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(50), nullable=False, unique=True)
    password_hash = Column(String(255), nullable=False)
    role = Column(Enum("admin", "operator", "volunteer"), default="admin", nullable=False)
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp(), nullable=False)


class VolunteerNotification(Base):
    __tablename__ = "volunteer_notifications"

    id = Column(Integer, primary_key=True, autoincrement=True)
    volunteer_id = Column(Integer, ForeignKey("admins.id", ondelete="CASCADE"), nullable=False)
    question_id = Column(Integer, ForeignKey("questions.id", ondelete="SET NULL"), nullable=True)
    question_text = Column(String(500), nullable=False)
    verdict = Column(Enum("accepted", "rejected"), nullable=False)
    is_read = Column(Boolean, nullable=False, server_default=sql_text("0"))
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp(), nullable=False)

    volunteer = relationship("Admin", foreign_keys=[volunteer_id])
    question = relationship("Question", foreign_keys=[question_id])