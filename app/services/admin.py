"""Vereinsverwaltung: Mitglieder, Einladungen, Plätze, Sperren, Einstellungen, Auslastung."""

import secrets
from datetime import date, datetime, time, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.config import TZ
from app.models import (
    Block,
    Booking,
    BookingStatus,
    Club,
    ClubKind,
    Court,
    Invitation,
    Membership,
    MembershipStatus,
    OpeningHours,
    Role,
    Season,
    Sport,
    User,
)
from app.services.booking import (
    BookingError,
    NotFoundError,
    cancel,
    get_court_in_club,
    now_local,
    slot_end,
    slot_starts,
)

JOIN_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # ohne 0/O und 1/I


def new_join_code() -> str:
    return "".join(secrets.choice(JOIN_CODE_ALPHABET) for _ in range(8))


# --- Mitglieder (FA-03) -----------------------------------------------------------

def list_members(db: Session, club_id: int, status: MembershipStatus | None = None):
    query = (
        select(Membership)
        .join(User, Membership.user_id == User.id)
        .where(Membership.club_id == club_id, User.is_deleted.is_(False))
        .options(selectinload(Membership.user))
        .order_by(User.name)
    )
    if status is None:
        query = query.where(Membership.status != MembershipStatus.PENDING)
    else:
        query = query.where(Membership.status == status)
    return db.scalars(query).all()


def get_membership(db: Session, club_id: int, membership_id: int) -> Membership:
    m = db.get(Membership, membership_id)
    if m is None or m.club_id != club_id:
        raise NotFoundError("Mitglied nicht gefunden")
    return m


def _admin_count(db: Session, club_id: int) -> int:
    return db.scalar(select(func.count(Membership.id)).where(
        Membership.club_id == club_id, Membership.role == Role.ADMIN,
        Membership.status == MembershipStatus.ACTIVE)) or 0


def _guard_last_admin(db: Session, m: Membership) -> None:
    if m.is_admin and _admin_count(db, m.club_id) <= 1:
        raise BookingError("Der Verein braucht mindestens eine Person in der Verwaltung.")


def cancel_future_bookings(db: Session, user_id: int, club_id: int, actor_user_id: int,
                           now: datetime) -> int:
    future = db.scalars(select(Booking).where(
        Booking.user_id == user_id, Booking.club_id == club_id,
        Booking.status == BookingStatus.CONFIRMED, Booking.start_at > now)).all()
    for booking in future:
        cancel(booking, actor_user_id, now)
    return len(future)


def set_member_locked(db: Session, actor: Membership, membership_id: int, locked: bool,
                      now: datetime | None = None) -> int:
    """Sperren storniert künftige Buchungen in diesem Verein (US-02)."""
    now = now or now_local()
    m = get_membership(db, actor.club_id, membership_id)
    if m.id == actor.id:
        raise BookingError("Du kannst dich nicht selbst sperren.")
    if m.status == MembershipStatus.PENDING:
        raise BookingError("Offene Anfragen bitte annehmen oder ablehnen.")
    if locked:
        _guard_last_admin(db, m)
    m.status = MembershipStatus.LOCKED if locked else MembershipStatus.ACTIVE
    cancelled = 0
    if locked:
        cancelled = cancel_future_bookings(db, m.user_id, m.club_id, actor.user_id, now)
    db.commit()
    return cancelled


def remove_member(db: Session, actor: Membership, membership_id: int,
                  now: datetime | None = None) -> int:
    """Entfernt die Mitgliedschaft und storniert künftige Buchungen im Verein."""
    now = now or now_local()
    m = get_membership(db, actor.club_id, membership_id)
    if m.id == actor.id:
        raise BookingError("Du kannst dich nicht selbst entfernen.")
    _guard_last_admin(db, m)
    cancelled = cancel_future_bookings(db, m.user_id, m.club_id, actor.user_id, now)
    db.delete(m)
    db.commit()
    return cancelled


def set_role(db: Session, actor: Membership, membership_id: int, role: Role) -> Membership:
    m = get_membership(db, actor.club_id, membership_id)
    if role != Role.ADMIN:
        _guard_last_admin(db, m)
    m.role = role
    db.commit()
    return m


def decide_request(db: Session, actor: Membership, membership_id: int, accept: bool) -> Membership:
    m = get_membership(db, actor.club_id, membership_id)
    if m.status != MembershipStatus.PENDING:
        raise BookingError("Diese Anfrage ist bereits bearbeitet.")
    if accept:
        m.status = MembershipStatus.ACTIVE
    else:
        db.delete(m)
    db.commit()
    return m


def invite(db: Session, actor: Membership, email: str, role: Role) -> Invitation:
    email = email.strip().lower()
    if "@" not in email or len(email) > 254:
        raise BookingError("Bitte eine gültige E-Mail-Adresse angeben.")
    existing = db.scalars(select(Membership).join(User).where(
        Membership.club_id == actor.club_id, User.email == email)).first()
    if existing is not None:
        raise BookingError("Diese Person ist bereits Mitglied oder hat eine Anfrage gestellt.")
    inv = Invitation(club_id=actor.club_id, email=email, role=role, invited_by_id=actor.user_id)
    db.add(inv)
    db.commit()
    return inv


def open_invitations(db: Session, club_id: int) -> list[Invitation]:
    return db.scalars(select(Invitation).where(
        Invitation.club_id == club_id, Invitation.accepted_at.is_(None),
        Invitation.revoked.is_(False)).order_by(Invitation.created_at.desc())).all()


def revoke_invitation(db: Session, club_id: int, invitation_id: int) -> None:
    inv = db.get(Invitation, invitation_id)
    if inv is None or inv.club_id != club_id:
        raise NotFoundError("Einladung nicht gefunden")
    inv.revoked = True
    db.commit()


def regenerate_join_code(db: Session, club_id: int) -> str:
    club = db.get(Club, club_id)
    club.join_code = new_join_code()
    db.commit()
    return club.join_code


# --- Plätze (FA-11) --------------------------------------------------------------

def list_courts(db: Session, club_id: int) -> list[Court]:
    return db.scalars(select(Court).where(Court.club_id == club_id).order_by(Court.name)).all()


def _euro_to_cents(value: str | None, label: str, required: bool = True) -> int | None:
    value = (value or "").strip().replace("€", "").replace(",", ".")
    if not value:
        if required:
            return 0
        return None
    try:
        cents = round(float(value) * 100)
    except ValueError:
        raise BookingError(f"{label}: bitte einen Betrag wie 12,50 angeben.") from None
    if cents < 0 or cents > 100_000:
        raise BookingError(f"{label}: bitte einen Betrag zwischen 0 und 1.000 € angeben.")
    return cents


def save_court(db: Session, club_id: int, data: dict, court_id: int | None = None) -> Court:
    name = (data.get("name") or "").strip()
    if not name:
        raise BookingError("Bitte einen Namen für den Platz angeben.")
    try:
        sport = Sport(data.get("sport", "tennis"))
        season = Season(data.get("season", "all"))
        slot_minutes = int(data.get("slot_minutes", 60))
    except ValueError:
        raise BookingError("Ungültige Angabe bei Sportart, Saison oder Slotlänge.") from None
    if slot_minutes not in (30, 60, 90, 120):
        raise BookingError("Die Slotlänge muss 30, 60, 90 oder 120 Minuten betragen.")
    court = get_court_in_club(db, club_id, court_id) if court_id else Court(club_id=club_id)
    if court_id and slot_minutes != court.slot_minutes:
        future = db.scalar(select(func.count(Booking.id)).where(
            Booking.court_id == court.id, Booking.status == BookingStatus.CONFIRMED,
            Booking.start_at > now_local()))
        if future:
            raise BookingError("Die Slotlänge lässt sich erst ändern, wenn der Platz "
                               "keine kommenden Buchungen mehr hat.")
    court.name = name[:60]
    court.sport = sport
    court.surface = (data.get("surface") or "").strip()[:60]
    court.is_indoor = data.get("is_indoor") in ("on", "true", True)
    court.has_floodlight = data.get("has_floodlight") in ("on", "true", True)
    court.season = season
    court.slot_minutes = slot_minutes
    court.price_cents = _euro_to_cents(data.get("price"), "Preis")
    court.prime_price_cents = _euro_to_cents(data.get("prime_price"), "Hauptzeitpreis",
                                             required=False)
    db.add(court)
    db.commit()
    return court


def set_court_active(db: Session, club_id: int, court_id: int, active: bool,
                     now: datetime | None = None) -> Court:
    """Plätze werden nie gelöscht; mit kommenden Buchungen nicht deaktivierbar (US-09)."""
    now = now or now_local()
    court = get_court_in_club(db, club_id, court_id)
    if not active:
        future = db.scalar(select(func.count(Booking.id)).where(
            Booking.court_id == court.id, Booking.status == BookingStatus.CONFIRMED,
            Booking.start_at > now))
        if future:
            raise BookingError(
                f"Der Platz hat noch {future} kommende Buchungen. "
                "Bitte zuerst eine Sperre anlegen oder die Buchungen stornieren."
            )
    court.is_active = active
    db.commit()
    return court


# --- Sperren (FA-12) --------------------------------------------------------------

def affected_bookings(db: Session, court_id: int, start: datetime, end: datetime) -> list[Booking]:
    return db.scalars(select(Booking).where(
        Booking.court_id == court_id, Booking.status == BookingStatus.CONFIRMED,
        Booking.start_at < end, Booking.end_at > start)
        .options(selectinload(Booking.user)).order_by(Booking.start_at)).all()


def create_block(db: Session, actor: Membership, court_id: int, start: datetime, end: datetime,
                 reason: str, confirm: bool, now: datetime | None = None):
    """Legt eine Sperre an. Betroffene Buchungen werden erst nach Bestätigung storniert.

    Gibt (block, betroffene_buchungen) zurück; block ist None, solange die Bestätigung fehlt.
    """
    now = now or now_local()
    court = get_court_in_club(db, actor.club_id, court_id)
    if end <= start:
        raise BookingError("Das Ende der Sperre muss nach dem Beginn liegen.")
    if not reason.strip():
        raise BookingError("Bitte einen Grund für die Sperre angeben.")
    affected = affected_bookings(db, court.id, start, end)
    if affected and not confirm:
        return None, affected
    for booking in affected:
        cancel(booking, actor.user_id, now)
    block = Block(club_id=actor.club_id, court_id=court.id, start_at=start, end_at=end,
                  reason=reason.strip()[:120], created_by_id=actor.user_id)
    db.add(block)
    db.commit()
    return block, affected


def list_blocks(db: Session, club_id: int, now: datetime | None = None) -> list[Block]:
    now = now or now_local()
    return db.scalars(select(Block).where(Block.club_id == club_id, Block.end_at > now)
                      .order_by(Block.start_at)).all()


def delete_block(db: Session, club_id: int, block_id: int) -> None:
    block = db.get(Block, block_id)
    if block is None or block.club_id != club_id:
        raise NotFoundError("Sperre nicht gefunden")
    db.delete(block)
    db.commit()


# --- Vereinseinstellungen (FA-08, Öffnungszeiten, Saison, Preise) -----------------

def parse_time(value: str, label: str) -> int:
    try:
        hh, mm = value.strip().split(":")
        minutes = int(hh) * 60 + int(mm)
    except (ValueError, AttributeError):
        raise BookingError(f"{label}: bitte eine Uhrzeit wie 08:00 angeben.") from None
    if not 0 <= minutes <= 1440 or minutes % 15:
        raise BookingError(f"{label}: bitte eine Uhrzeit in Viertelstunden angeben, z. B. 08:00.")
    return minutes


def parse_day_month(value: str, label: str) -> date:
    try:
        day, month = value.strip().rstrip(".").split(".")[:2]
        return date(2000, int(month), int(day))
    except (ValueError, AttributeError):
        raise BookingError(f"{label}: bitte ein Datum wie 15.04. angeben.") from None


def default_hours() -> list[OpeningHours]:
    return [OpeningHours(weekday=d, opens=8 * 60, closes=22 * 60) for d in range(7)]


def update_club(db: Session, club_id: int, form: dict) -> Club:
    club = db.get(Club, club_id)
    name = (form.get("name") or "").strip()
    if not name:
        raise BookingError("Bitte einen Namen angeben.")
    try:
        club.kind = ClubKind(form.get("kind", club.kind))
        max_active = int(form.get("max_active", club.max_active_bookings))
        max_days = int(form.get("max_days", club.max_days_ahead))
        cancel_hours = int(form.get("cancel_hours", club.cancel_hours))
    except ValueError:
        raise BookingError("Bitte bei den Buchungsregeln ganze Zahlen angeben.") from None
    if not 1 <= max_active <= 20:
        raise BookingError("Aktive Buchungen pro Mitglied: zwischen 1 und 20.")
    if not 1 <= max_days <= 60:
        raise BookingError("Vorlauf: zwischen 1 und 60 Tagen.")
    if not 0 <= cancel_hours <= 72:
        raise BookingError("Stornofrist: zwischen 0 und 72 Stunden.")

    summer_start = parse_day_month(form.get("summer_start", "15.04."), "Saisonbeginn")
    summer_end = parse_day_month(form.get("summer_end", "15.10."), "Saisonende")
    prime_from = prime_to = None
    if form.get("prime_from") or form.get("prime_to"):
        prime_from = parse_time(form.get("prime_from", ""), "Hauptzeit von")
        prime_to = parse_time(form.get("prime_to", ""), "Hauptzeit bis")
        if prime_from >= prime_to:
            raise BookingError("Die Hauptzeit muss vor ihrem Ende beginnen.")

    hours = {h.weekday: h for h in club.hours}
    for d in range(7):
        h = hours.get(d) or OpeningHours(club_id=club.id, weekday=d)
        closed = form.get(f"closed_{d}") in ("on", "true")
        if not closed:
            opens = parse_time(form.get(f"opens_{d}", "08:00"), "Öffnet")
            closes = parse_time(form.get(f"closes_{d}", "22:00"), "Schließt")
            if opens >= closes:
                raise BookingError(
                    "Bei den Öffnungszeiten muss die Öffnung vor dem Schluss liegen.")
            h.opens, h.closes = opens, closes
        h.is_closed = closed
        if d not in hours:
            club.hours.append(h)

    club.name = name[:120]
    club.street = (form.get("street") or "").strip()[:120]
    club.zip_code = (form.get("zip_code") or "").strip()[:10]
    club.city = (form.get("city") or "").strip()[:80]
    club.contact_email = (form.get("contact_email") or "").strip()[:254]
    club.max_active_bookings, club.max_days_ahead = max_active, max_days
    club.cancel_hours = cancel_hours
    club.summer_start, club.summer_end = summer_start, summer_end
    club.prime_from, club.prime_to = prime_from, prime_to
    db.commit()
    return club


# --- Auslastung (FA-13, Kennzahl Platzauslastung) ---------------------------------

def utilization(db: Session, club_id: int, monday: date):
    """Auslastung je Platz und Woche in Stunden: gebuchte / buchbare Zeit.

    Gesperrte Zeiten zählen nicht als buchbar. Rückgabe: (Platz, gebucht_h, buchbar_h, Prozent).
    """
    club = db.get(Club, club_id)
    start = datetime.combine(monday, time(0), TZ)
    end = start + timedelta(days=7)
    result = []
    for court in list_courts(db, club_id):
        if not court.is_active:
            continue
        bookings = db.scalars(select(Booking).where(
            Booking.court_id == court.id, Booking.status == BookingStatus.CONFIRMED,
            Booking.start_at >= start, Booking.start_at < end)).all()
        blocks = db.scalars(select(Block).where(
            Block.court_id == court.id, Block.start_at < end, Block.end_at > start)).all()
        offered = 0
        for offset in range(7):
            for s in slot_starts(club, court, monday + timedelta(days=offset)):
                e = slot_end(court, s)
                if not any(b.start_at < e and b.end_at > s for b in blocks):
                    offered += court.slot_minutes
        booked = sum((b.end_at - b.start_at).total_seconds() / 60 for b in bookings)
        share = booked / offered * 100 if offered else 0.0
        result.append((court, booked / 60, offered / 60, share))
    return result
