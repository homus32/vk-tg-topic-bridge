"""Declarative base shared by all ORM models and by Alembic's target metadata."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base class for the bridge ORM; `Base.metadata` is the single schema source."""
