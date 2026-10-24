"""Domänenmodell von CourtSlot.

Jede fachliche Tabelle trägt eine club_id (Mandantentrennung, FA-14).
Der Doppelbuchungsschutz (FA-06) liegt als partieller Unique-Index in der
Datenbank: pro Platz und Startzeit darf es nur eine bestätigte Buchung geben.
"""

import enum
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Role(enum.StrEnum):
    MEMBER = "member"
    ADMIN = "admin"


class Sport(enum.StrEnum):
    TENNIS = "tennis"
    PADEL = "padel"


class BookingStatus(enum.StrEnum):
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"


def _values(enum_cls) -> list[str]:
    """Speichert die Werte (z. B. 'confirmed') statt der Namen in der Datenbank."""
    return [m.value for m in enum_cls]


class Club(Base):
    __tablename__ = "clubs"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    max_active_bookings: Mapped[int] = mapped_column(Integer, default=2)
    max_days_ahead: Mapped[int] = mapped_column(Integer, default=7)
    open_hour: Mapped[int] = mapped_column(Integer, default=8)
    close_hour: Mapped[int] = mapped_column(Integer, default=22)

    __table_args__ = (
        CheckConstraint("max_active_bookings BETWEEN 1 AND 20", name="ck_club_max_active"),
        CheckConstraint("max_days_ahead BETWEEN 1 AND 60", name="ck_club_days_ahead"),
        CheckConstraint("open_hour >= 0 AND close_hour <= 24 AND open_hour < close_hour",
                        name="ck_club_hours"),
    )


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    club_id: Mapped[int] = mapped_column(ForeignKey("clubs.id"), index=True)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[Role] = mapped_column(
        Enum(Role, name="role", values_callable=_values), default=Role.MEMBER
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_removed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    club: Mapped[Club] = relationship()

    @property
    def is_admin(self) -> bool:
        return self.role == Role.ADMIN


class Court(Base):
    __tablename__ = "courts"

    id: Mapped[int] = mapped_column(primary_key=True)
    club_id: Mapped[int] = mapped_column(ForeignKey("clubs.id"), index=True)
    name: Mapped[str] = mapped_column(String(60))
    sport: Mapped[Sport] = mapped_column(Enum(Sport, name="sport", values_callable=_values))
    surface: Mapped[str] = mapped_column(String(60), default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Booking(Base):
    __tablename__ = "bookings"

    id: Mapped[int] = mapped_column(primary_key=True)
    club_id: Mapped[int] = mapped_column(ForeignKey("clubs.id"), index=True)
    court_id: Mapped[int] = mapped_column(ForeignKey("courts.id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[BookingStatus] = mapped_column(
        Enum(BookingStatus, name="booking_status", values_callable=_values),
        default=BookingStatus.CONFIRMED,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))

    court: Mapped[Court] = relationship()
    user: Mapped[User] = relationship(foreign_keys=[user_id])

    __table_args__ = (
        # FA-06 / NFA-02: höchstens eine bestätigte Buchung je Platz und Slot.
        Index(
            "uq_booking_court_slot_confirmed",
            "court_id",
            "start_at",
            unique=True,
            postgresql_where=text("status = 'confirmed'"),
        ),
        CheckConstraint("end_at > start_at", name="ck_booking_time"),
    )


class Block(Base):
    """Sperre eines Platzes für einen Zeitraum (FA-12)."""

    __tablename__ = "blocks"

    id: Mapped[int] = mapped_column(primary_key=True)
    club_id: Mapped[int] = mapped_column(ForeignKey("clubs.id"), index=True)
    court_id: Mapped[int] = mapped_column(ForeignKey("courts.id"))
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    reason: Mapped[str] = mapped_column(String(120))
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))

    court: Mapped[Court] = relationship()

    __table_args__ = (CheckConstraint("end_at > start_at", name="ck_block_time"),)
