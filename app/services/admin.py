"""Vereinsverwaltung: Mitglieder, Plätze, Sperren, Regeln, Auslastung."""

import secrets
from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import TZ
from app.models import Block, Booking, BookingStatus, Club, Court, Role, Sport, User
from app.security import generate_start_password, hash_password
from app.services.booking import (
    BookingError,
    NotFoundError,
    _cancel,
    get_court_in_club,
    now_local,
)

# --- Mitglieder (FA-03) -----------------------------------------------------------


def list_members(db: Session, club_id: int) -> list[User]:
    return db.scalars(
        select(User)
        .where(User.club_id == club_id, User.is_removed.is_(False))
        .order_by(User.name)
    ).all()


def get_member(db: Session, club_id: int, user_id: int) -> User:
    user = db.get(User, user_id)
    if user is None or user.club_id != club_id or user.is_removed:
        raise NotFoundError("Mitglied nicht gefunden")
    return user


def create_member(db: Session, club_id: int, name: str, email: str, role: Role) -> tuple[User, str]:
    name, email = name.strip(), email.strip().lower()
    if not name or "@" not in email:
        raise BookingError("Bitte Name und gültige E-Mail-Adresse angeben.")
    password = generate_start_password()
    user = User(club_id=club_id, name=name, email=email, role=role,
                password_hash=hash_password(password))
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise BookingError("Diese E-Mail-Adresse ist bereits vergeben.") from None
    return user, password


def cancel_future_bookings(db: Session, user: User, actor: User, now: datetime) -> int:
    future = db.scalars(
        select(Booking).where(
            Booking.user_id == user.id,
            Booking.status == BookingStatus.CONFIRMED,
            Booking.start_at > now,
        )
    ).all()
    for booking in future:
        _cancel(booking, actor, now)
    return len(future)


def set_member_active(db: Session, actor: User, user_id: int, active: bool,
                      now: datetime | None = None) -> int:
    """Sperren storniert künftige Buchungen (US-02)."""
    now = now or now_local()
    user = get_member(db, actor.club_id, user_id)
    if user.id == actor.id:
        raise BookingError("Du kannst dich nicht selbst sperren.")
    user.is_active = active
    cancelled = 0 if active else cancel_future_bookings(db, user, actor, now)
    db.commit()
    return cancelled


def remove_member(db: Session, actor: User, user_id: int, now: datetime | None = None) -> int:
    """Entfernen = sperren und personenbezogene Daten löschen (DSGVO, NFA-07).

    Die Buchungshistorie bleibt für die Auslastung erhalten, ist aber nicht
    mehr einer Person zuzuordnen.
    """
    now = now or now_local()
    user = get_member(db, actor.club_id, user_id)
    if user.id == actor.id:
        raise BookingError("Du kannst dich nicht selbst entfernen.")
    cancelled = cancel_future_bookings(db, user, actor, now)
    user.is_active = False
    user.is_removed = True
    user.name = "Entferntes Mitglied"
    user.email = f"entfernt-{user.id}@invalid.local"
    user.password_hash = hash_password(secrets.token_urlsafe(32))
    db.commit()
    return cancelled


# --- Plätze (FA-11) --------------------------------------------------------------


def list_courts(db: Session, club_id: int) -> list[Court]:
    return db.scalars(select(Court).where(Court.club_id == club_id).order_by(Court.name)).all()


def save_court(db: Session, club_id: int, name: str, sport: str, surface: str,
               court_id: int | None = None) -> Court:
    name = name.strip()
    if not name:
        raise BookingError("Bitte einen Namen für den Platz angeben.")
    try:
        sport_value = Sport(sport)
    except ValueError:
        raise BookingError("Unbekannte Sportart.") from None
    court = get_court_in_club(db, club_id, court_id) if court_id else Court(club_id=club_id)
    court.name, court.sport, court.surface = name, sport_value, surface.strip()
    db.add(court)
    db.commit()
    return court


def set_court_active(db: Session, club_id: int, court_id: int, active: bool,
                     now: datetime | None = None) -> Court:
    """Ein Platz mit künftigen Buchungen kann nicht deaktiviert werden (US-09)."""
    now = now or now_local()
    court = get_court_in_club(db, club_id, court_id)
    if not active:
        future = db.scalar(
            select(func.count(Booking.id)).where(
                Booking.court_id == court.id,
                Booking.status == BookingStatus.CONFIRMED,
                Booking.start_at > now,
            )
        )
        if future:
            raise BookingError(
                f"Der Platz hat noch {future} künftige Buchungen. "
                "Bitte zuerst eine Sperre anlegen oder die Buchungen stornieren."
            )
    court.is_active = active
    db.commit()
    return court


# --- Sperren (FA-12) --------------------------------------------------------------


def affected_bookings(db: Session, court_id: int, start: datetime, end: datetime) -> list[Booking]:
    return db.scalars(
        select(Booking)
        .where(
            Booking.court_id == court_id,
            Booking.status == BookingStatus.CONFIRMED,
            Booking.start_at < end,
            Booking.end_at > start,
        )
        .order_by(Booking.start_at)
    ).all()


def validate_block(db: Session, club_id: int, court_id: int, start: datetime,
                   end: datetime, reason: str) -> Court:
    court = get_court_in_club(db, club_id, court_id)
    if end <= start:
        raise BookingError("Das Ende der Sperre muss nach dem Beginn liegen.")
    if not reason.strip():
        raise BookingError("Bitte einen Grund für die Sperre angeben.")
    return court


def create_block(db: Session, actor: User, court_id: int, start: datetime, end: datetime,
                 reason: str, confirm: bool, now: datetime | None = None):
    """Legt eine Sperre an. Betroffene Buchungen werden erst nach Bestätigung storniert.

    Gibt (block, betroffene_buchungen) zurück; block ist None, solange noch eine
    Bestätigung fehlt.
    """
    now = now or now_local()
    court = validate_block(db, actor.club_id, court_id, start, end, reason)
    affected = affected_bookings(db, court.id, start, end)
    if affected and not confirm:
        return None, affected
    for booking in affected:
        _cancel(booking, actor, now)
    block = Block(club_id=actor.club_id, court_id=court.id, start_at=start, end_at=end,
                  reason=reason.strip(), created_by_id=actor.id)
    db.add(block)
    db.commit()
    return block, affected


def list_blocks(db: Session, club_id: int, now: datetime | None = None) -> list[Block]:
    now = now or now_local()
    return db.scalars(
        select(Block)
        .where(Block.club_id == club_id, Block.end_at > now)
        .order_by(Block.start_at)
    ).all()


def delete_block(db: Session, club_id: int, block_id: int) -> None:
    block = db.get(Block, block_id)
    if block is None or block.club_id != club_id:
        raise NotFoundError("Sperre nicht gefunden")
    db.delete(block)
    db.commit()


# --- Buchungsregeln (FA-08) -------------------------------------------------------


def update_rules(db: Session, club_id: int, max_active: int, max_days: int) -> Club:
    if not 1 <= max_active <= 20:
        raise BookingError("Die Höchstzahl aktiver Buchungen muss zwischen 1 und 20 liegen.")
    if not 1 <= max_days <= 60:
        raise BookingError("Der Vorlauf muss zwischen 1 und 60 Tagen liegen.")
    club = db.get(Club, club_id)
    club.max_active_bookings = max_active
    club.max_days_ahead = max_days
    db.commit()
    return club


# --- Auslastung (FA-13, Kennzahl Platzauslastung) ---------------------------------


def utilization(db: Session, club_id: int, monday: date) -> list[tuple[Court, int, int, float]]:
    """Auslastung je Platz und Woche: gebuchte Slots / angebotene Slots.

    Gesperrte Slots zählen nicht als angeboten.
    """
    club = db.get(Club, club_id)
    start = datetime.combine(monday, datetime.min.time(), TZ)
    end = start + timedelta(days=7)
    result = []
    for court in list_courts(db, club_id):
        if not court.is_active:
            continue
        booked = db.scalar(
            select(func.count(Booking.id)).where(
                Booking.court_id == court.id,
                Booking.status == BookingStatus.CONFIRMED,
                Booking.start_at >= start,
                Booking.start_at < end,
            )
        ) or 0
        offered = 0
        blocks = db.scalars(
            select(Block).where(Block.court_id == court.id, Block.start_at < end,
                                Block.end_at > start)
        ).all()
        for day in range(7):
            d = monday + timedelta(days=day)
            for hour in range(club.open_hour, club.close_hour):
                slot = datetime(d.year, d.month, d.day, hour, tzinfo=TZ)
                slot_end = slot + timedelta(hours=1)
                if not any(b.start_at < slot_end and b.end_at > slot for b in blocks):
                    offered += 1
        share = booked / offered * 100 if offered else 0.0
        result.append((court, booked, offered, share))
    return result
