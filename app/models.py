"""Domänenmodell von CourtSlot.

Ein Benutzerkonto (User) ist vereinsübergreifend. Die Zugehörigkeit zu einem
Verein, die Rolle und der Freigabestatus stehen in der Mitgliedschaft
(Membership). Alle fachlichen Daten eines Vereins tragen eine club_id
(Mandantentrennung, FA-14).

Der Doppelbuchungsschutz (FA-06) liegt als Ausschluss-Constraint in der
Datenbank: Auf demselben Platz dürfen sich bestätigte Buchungen zeitlich nicht
überlappen. Das gilt auch für unterschiedliche Slotlängen (z. B. 60 und 90 Min.).
"""

import enum
from datetime import date, datetime

from sqlalchemy import (
    DDL,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    event,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, ExcludeConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Role(enum.StrEnum):
    MEMBER = "member"
    ADMIN = "admin"


class MembershipStatus(enum.StrEnum):
    PENDING = "pending"   # Beitritt per Code beantragt, wartet auf Freigabe
    ACTIVE = "active"
    LOCKED = "locked"     # vom Verein gesperrt


class Sport(enum.StrEnum):
    TENNIS = "tennis"
    PADEL = "padel"


class Season(enum.StrEnum):
    ALL = "all"           # ganzjährig
    SUMMER = "summer"     # nur in der Sommersaison (Freiplätze)
    WINTER = "winter"     # nur außerhalb der Sommersaison (Hallenplätze)


class ClubKind(enum.StrEnum):
    CLUB = "club"         # Verein
    FACILITY = "facility"  # gewerbliche Anlage


class BookingStatus(enum.StrEnum):
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"


def _values(enum_cls) -> list[str]:
    """Speichert die Werte (z. B. 'confirmed') statt der Namen in der Datenbank."""
    return [m.value for m in enum_cls]


def _enum(cls, name: str) -> Enum:
    return Enum(cls, name=name, values_callable=_values)


def _now_col():
    return mapped_column(DateTime(timezone=True), server_default=func.now())


class User(Base):
    """Vereinsübergreifendes Benutzerkonto."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(String(255))
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    # Wird beim Abmelden, Passwortwechsel und Löschen erhöht: alte Sitzungen werden ungültig.
    session_version: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = _now_col()

    memberships: Mapped[list["Membership"]] = relationship(back_populates="user")

    @property
    def is_verified(self) -> bool:
        return self.email_verified_at is not None


class Club(Base):
    """Verein oder Anlage, also der Mandant."""

    __tablename__ = "clubs"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[ClubKind] = mapped_column(_enum(ClubKind, "club_kind"), default=ClubKind.CLUB)
    street: Mapped[str] = mapped_column(String(120), default="")
    zip_code: Mapped[str] = mapped_column(String(10), default="")
    city: Mapped[str] = mapped_column(String(80), default="")
    contact_email: Mapped[str] = mapped_column(String(254), default="")
    join_code: Mapped[str] = mapped_column(String(12), unique=True)
    # Buchungsregeln (FA-08)
    max_active_bookings: Mapped[int] = mapped_column(Integer, default=2)
    max_days_ahead: Mapped[int] = mapped_column(Integer, default=7)
    cancel_hours: Mapped[int] = mapped_column(Integer, default=0)
    # Sommersaison für Freiplätze (Jahr wird ignoriert)
    summer_start: Mapped[date] = mapped_column(Date, default=date(2000, 4, 15))
    summer_end: Mapped[date] = mapped_column(Date, default=date(2000, 10, 15))
    # Hauptzeit mit eigenem Preis, Minuten ab Mitternacht (optional)
    prime_from: Mapped[int | None] = mapped_column(Integer)
    prime_to: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = _now_col()

    hours: Mapped[list["OpeningHours"]] = relationship(
        order_by="OpeningHours.weekday", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint("max_active_bookings BETWEEN 1 AND 20", name="ck_club_max_active"),
        CheckConstraint("max_days_ahead BETWEEN 1 AND 60", name="ck_club_days_ahead"),
        CheckConstraint("cancel_hours BETWEEN 0 AND 72", name="ck_club_cancel_hours"),
        CheckConstraint("prime_from IS NULL OR (prime_from >= 0 AND prime_to <= 1440 "
                        "AND prime_from < prime_to)", name="ck_club_prime"),
    )


class OpeningHours(Base):
    """Öffnungszeit je Wochentag (0 = Montag) in Minuten ab Mitternacht."""

    __tablename__ = "opening_hours"

    id: Mapped[int] = mapped_column(primary_key=True)
    club_id: Mapped[int] = mapped_column(ForeignKey("clubs.id", ondelete="CASCADE"), index=True)
    weekday: Mapped[int] = mapped_column(Integer)
    opens: Mapped[int] = mapped_column(Integer, default=8 * 60)
    closes: Mapped[int] = mapped_column(Integer, default=22 * 60)
    is_closed: Mapped[bool] = mapped_column(Boolean, default=False)

    __table_args__ = (
        UniqueConstraint("club_id", "weekday", name="uq_hours_club_weekday"),
        CheckConstraint("weekday BETWEEN 0 AND 6", name="ck_hours_weekday"),
        CheckConstraint("opens >= 0 AND closes <= 1440 AND opens < closes", name="ck_hours_range"),
    )


class Membership(Base):
    """Zugehörigkeit eines Kontos zu einem Verein mit Rolle und Status."""

    __tablename__ = "memberships"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    club_id: Mapped[int] = mapped_column(ForeignKey("clubs.id"), index=True)
    role: Mapped[Role] = mapped_column(_enum(Role, "role"), default=Role.MEMBER)
    status: Mapped[MembershipStatus] = mapped_column(
        _enum(MembershipStatus, "membership_status"), default=MembershipStatus.ACTIVE
    )
    created_at: Mapped[datetime] = _now_col()

    user: Mapped[User] = relationship(back_populates="memberships")
    club: Mapped[Club] = relationship()

    __table_args__ = (UniqueConstraint("user_id", "club_id", name="uq_membership"),)

    @property
    def is_admin(self) -> bool:
        return self.role == Role.ADMIN and self.status == MembershipStatus.ACTIVE

    @property
    def is_active(self) -> bool:
        return self.status == MembershipStatus.ACTIVE


class Invitation(Base):
    """Einladung per E-Mail. Der Link enthält die signierte ID der Einladung."""

    __tablename__ = "invitations"

    id: Mapped[int] = mapped_column(primary_key=True)
    club_id: Mapped[int] = mapped_column(ForeignKey("clubs.id"), index=True)
    email: Mapped[str] = mapped_column(String(254))
    role: Mapped[Role] = mapped_column(_enum(Role, "role"), default=Role.MEMBER)
    invited_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = _now_col()
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)

    club: Mapped[Club] = relationship()


class Court(Base):
    __tablename__ = "courts"

    id: Mapped[int] = mapped_column(primary_key=True)
    club_id: Mapped[int] = mapped_column(ForeignKey("clubs.id"), index=True)
    name: Mapped[str] = mapped_column(String(60))
    sport: Mapped[Sport] = mapped_column(_enum(Sport, "sport"))
    surface: Mapped[str] = mapped_column(String(60), default="")
    is_indoor: Mapped[bool] = mapped_column(Boolean, default=False)
    has_floodlight: Mapped[bool] = mapped_column(Boolean, default=False)
    season: Mapped[Season] = mapped_column(_enum(Season, "season"), default=Season.ALL)
    # Wählbare Spieldauern in Minuten; Startzeiten liegen im 30-Minuten-Raster
    durations: Mapped[list[int]] = mapped_column(ARRAY(Integer), default=lambda: [60, 90])
    # Preis pro Stunde in Cent (anteilig je halbe Stunde); 0 = im Beitrag enthalten
    hourly_price_cents: Mapped[int] = mapped_column(Integer, default=0)
    prime_hourly_price_cents: Mapped[int | None] = mapped_column(Integer)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    __table_args__ = (
        CheckConstraint("durations <@ ARRAY[60, 90, 120] AND cardinality(durations) >= 1",
                        name="ck_court_durations"),
        CheckConstraint(
            "hourly_price_cents >= 0 AND "
            "(prime_hourly_price_cents IS NULL OR prime_hourly_price_cents >= 0)",
            name="ck_court_price"),
    )


class RentalItem(Base):
    """Leihartikel einer Anlage, z. B. Padelschläger oder eine Dose Bälle."""

    __tablename__ = "rental_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    club_id: Mapped[int] = mapped_column(ForeignKey("clubs.id"), index=True)
    name: Mapped[str] = mapped_column(String(60))
    # None = für alle Sportarten
    sport: Mapped[Sport | None] = mapped_column(_enum(Sport, "sport"))
    price_cents: Mapped[int] = mapped_column(Integer, default=0)
    max_per_booking: Mapped[int] = mapped_column(Integer, default=4)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    __table_args__ = (
        CheckConstraint("price_cents >= 0", name="ck_rental_price"),
        CheckConstraint("max_per_booking BETWEEN 1 AND 10", name="ck_rental_max"),
    )


class Booking(Base):
    __tablename__ = "bookings"

    id: Mapped[int] = mapped_column(primary_key=True)
    club_id: Mapped[int] = mapped_column(ForeignKey("clubs.id"), index=True)
    court_id: Mapped[int] = mapped_column(ForeignKey("courts.id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Platzpreis und Gesamtpreis (Platz + Leihartikel) zum Zeitpunkt der Buchung
    court_price_cents: Mapped[int] = mapped_column(Integer, default=0)
    price_cents: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[BookingStatus] = mapped_column(
        _enum(BookingStatus, "booking_status"), default=BookingStatus.CONFIRMED
    )
    created_at: Mapped[datetime] = _now_col()
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))

    court: Mapped[Court] = relationship()
    user: Mapped[User] = relationship(foreign_keys=[user_id])
    items: Mapped[list["BookingItem"]] = relationship(
        back_populates="booking", cascade="all, delete-orphan", order_by="BookingItem.id")

    __table_args__ = (CheckConstraint("end_at > start_at", name="ck_booking_time"),)

    @property
    def minutes(self) -> int:
        return int((self.end_at - self.start_at).total_seconds() // 60)


class BookingItem(Base):
    """Ausgeliehener Artikel einer Buchung; Name und Preis werden festgehalten."""

    __tablename__ = "booking_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    booking_id: Mapped[int] = mapped_column(
        ForeignKey("bookings.id", ondelete="CASCADE"), index=True)
    rental_item_id: Mapped[int] = mapped_column(ForeignKey("rental_items.id"))
    name: Mapped[str] = mapped_column(String(60))
    quantity: Mapped[int] = mapped_column(Integer)
    price_cents: Mapped[int] = mapped_column(Integer)  # je Stück

    booking: Mapped[Booking] = relationship(back_populates="items")

    __table_args__ = (CheckConstraint("quantity BETWEEN 1 AND 10", name="ck_item_quantity"),)

    @property
    def total_cents(self) -> int:
        return self.quantity * self.price_cents


# FA-06 / NFA-02: keine zeitliche Überlappung bestätigter Buchungen auf einem Platz.
Booking.__table__.append_constraint(
    ExcludeConstraint(
        (Booking.court_id, "="),
        (func.tstzrange(Booking.start_at, Booking.end_at, "[)"), "&&"),
        name="ex_booking_no_overlap",
        using="gist",
        where=text("status = 'confirmed'"),
    )
)

# Für den Ausschluss-Constraint braucht PostgreSQL die Erweiterung btree_gist.
event.listen(
    Base.metadata, "before_create", DDL("CREATE EXTENSION IF NOT EXISTS btree_gist")
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
