"""Buchungslogik: Regeln, Doppelbuchungsschutz, Stornierung und Wochenansicht.

Alle Funktionen erhalten den aktuellen Zeitpunkt als Parameter `now`,
damit die Regeln in Tests mit festen Zeitpunkten geprüft werden können.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.config import SLOT_MINUTES, TZ
from app.models import Block, Booking, BookingStatus, Club, Court, User


class BookingError(Exception):
    """Fachlicher Fehler, der dem Mitglied mit Grund angezeigt wird (FA-07)."""


class NotFoundError(Exception):
    """Objekt existiert nicht oder gehört zu einem anderen Verein (FA-14)."""


class ForbiddenError(Exception):
    """Aktion ist für diese Rolle nicht erlaubt."""


def now_local() -> datetime:
    return datetime.now(TZ)


def slot_end(start: datetime) -> datetime:
    return start + timedelta(minutes=SLOT_MINUTES)


def get_court_in_club(db: Session, club_id: int, court_id: int) -> Court:
    court = db.get(Court, court_id)
    if court is None or court.club_id != club_id:
        raise NotFoundError("Platz nicht gefunden")
    return court


def _check_slot_rules(club: Club, court: Court, start: datetime, now: datetime) -> None:
    if start.tzinfo is None:
        raise ValueError("start muss eine Zeitzone haben")
    local = start.astimezone(TZ)
    if local.minute != 0 or local.second != 0 or local.microsecond != 0:
        raise BookingError("Buchungen beginnen immer zur vollen Stunde.")
    if not (club.open_hour <= local.hour < club.close_hour):
        raise BookingError(
            f"Gebucht werden kann zwischen {club.open_hour} und {club.close_hour} Uhr."
        )
    if not court.is_active:
        raise BookingError("Dieser Platz ist derzeit nicht buchbar.")
    if start <= now:
        raise BookingError("Slots in der Vergangenheit können nicht gebucht werden.")
    last_day = now.astimezone(TZ).date() + timedelta(days=club.max_days_ahead)
    if local.date() > last_day:
        raise BookingError(
            f"Buchungen sind höchstens {club.max_days_ahead} Tage im Voraus möglich."
        )


def active_booking_count(db: Session, user_id: int, now: datetime) -> int:
    return db.scalar(
        select(func.count(Booking.id)).where(
            Booking.user_id == user_id,
            Booking.status == BookingStatus.CONFIRMED,
            Booking.start_at > now,
        )
    ) or 0


def find_block(db: Session, court_id: int, start: datetime, end: datetime) -> Block | None:
    return db.scalars(
        select(Block).where(
            Block.court_id == court_id, Block.start_at < end, Block.end_at > start
        )
    ).first()


def book_slot(
    db: Session, user: User, court_id: int, start: datetime, now: datetime | None = None
) -> Booking:
    """Bucht einen Slot und setzt alle Regeln durch (FA-05 bis FA-07).

    Nebenläufigkeit:
    - Zwei Mitglieder, gleicher Slot: Der partielle Unique-Index lässt nur
      eine bestätigte Buchung zu, die zweite endet in einem IntegrityError.
    - Ein Mitglied, mehrere Slots gleichzeitig: Die Zeile des Mitglieds wird
      gesperrt (SELECT ... FOR UPDATE), damit die Höchstzahl aktiver
      Buchungen nicht durch parallele Anfragen überschritten wird.
    """
    now = now or now_local()
    court = get_court_in_club(db, user.club_id, court_id)
    club = db.get(Club, user.club_id)
    _check_slot_rules(club, court, start, now)
    end = slot_end(start)

    try:
        db.execute(select(User.id).where(User.id == user.id).with_for_update())
        count = active_booking_count(db, user.id, now)
        if count >= club.max_active_bookings:
            raise BookingError(
                f"Du hast bereits {count} aktive Buchungen "
                f"(Maximum im Verein: {club.max_active_bookings})."
            )
        block = find_block(db, court.id, start, end)
        if block is not None:
            raise BookingError(f"Der Platz ist gesperrt: {block.reason}.")
        booking = Booking(
            club_id=club.id, court_id=court.id, user_id=user.id, start_at=start, end_at=end
        )
        db.add(booking)
        db.flush()
        db.commit()
    except IntegrityError:
        db.rollback()
        raise BookingError(
            "Dieser Slot wurde gerade von jemand anderem gebucht."
        ) from None
    except BookingError:
        db.rollback()
        raise
    return booking


def cancel_booking(
    db: Session, actor: User, booking_id: int, now: datetime | None = None
) -> Booking:
    """Storniert eine Buchung bis zum Slotbeginn (FA-09)."""
    now = now or now_local()
    booking = db.get(Booking, booking_id)
    if booking is None or booking.club_id != actor.club_id:
        raise NotFoundError("Buchung nicht gefunden")
    if booking.user_id != actor.id and not actor.is_admin:
        raise ForbiddenError("Nur eigene Buchungen können storniert werden.")
    if booking.status != BookingStatus.CONFIRMED:
        raise BookingError("Diese Buchung ist bereits storniert.")
    if booking.start_at <= now:
        raise BookingError("Buchungen können nur bis zum Slotbeginn storniert werden.")
    _cancel(booking, actor, now)
    db.commit()
    return booking


def _cancel(booking: Booking, actor: User, now: datetime) -> None:
    booking.status = BookingStatus.CANCELLED
    booking.cancelled_at = now
    booking.cancelled_by_id = actor.id


def my_bookings(db: Session, user: User, now: datetime | None = None):
    """Kommende und vergangene eigene Buchungen getrennt (FA-10)."""
    now = now or now_local()
    rows = db.scalars(
        select(Booking)
        .where(Booking.user_id == user.id, Booking.status == BookingStatus.CONFIRMED)
        .order_by(Booking.start_at)
    ).all()
    upcoming = [b for b in rows if b.start_at > now]
    past = [b for b in rows if b.start_at <= now][::-1]
    return upcoming, past


# --- Wochenansicht (FA-04) -------------------------------------------------------

@dataclass
class Cell:
    court: Court
    start: datetime
    state: str  # free | own | booked | blocked | past | later
    label: str = ""
    booking_id: int | None = None
    is_past: bool = False


@dataclass
class DayView:
    day: date
    rows: list[tuple[int, list[Cell]]] = field(default_factory=list)


def week_start_for(day: date) -> date:
    return day - timedelta(days=day.weekday())


def build_week(db: Session, user: User, monday: date, now: datetime | None = None):
    now = now or now_local()
    club = db.get(Club, user.club_id)
    courts = db.scalars(
        select(Court)
        .where(Court.club_id == user.club_id, Court.is_active.is_(True))
        .order_by(Court.name)
    ).all()
    start = datetime.combine(monday, datetime.min.time(), TZ)
    end = start + timedelta(days=7)
    query = select(Booking).where(
        Booking.club_id == user.club_id,
        Booking.status == BookingStatus.CONFIRMED,
        Booking.start_at >= start,
        Booking.start_at < end,
    )
    if user.is_admin:  # Admins sehen Namen: Benutzer in einer Abfrage mitladen (kein N+1)
        query = query.options(selectinload(Booking.user))
    bookings = db.scalars(query).all()
    by_slot = {(b.court_id, b.start_at.astimezone(TZ)): b for b in bookings}
    blocks_by_court: dict[int, list[Block]] = {}
    for block in db.scalars(
        select(Block).where(
            Block.club_id == user.club_id, Block.start_at < end, Block.end_at > start
        )
    ):
        blocks_by_court.setdefault(block.court_id, []).append(block)
    last_day = now.astimezone(TZ).date() + timedelta(days=club.max_days_ahead)

    days = []
    for offset in range(7):
        day = monday + timedelta(days=offset)
        view = DayView(day=day)
        for hour in range(club.open_hour, club.close_hour):
            slot = datetime(day.year, day.month, day.day, hour, tzinfo=TZ)
            cells = []
            for court in courts:
                cells.append(_cell(court, slot, now, last_day, by_slot,
                                   blocks_by_court.get(court.id, ()), user))
            view.rows.append((hour, cells))
        days.append(view)
    return courts, days


def _cell(court, slot, now, last_day, by_slot, blocks, user) -> Cell:
    booking = by_slot.get((court.id, slot))
    is_past = slot <= now
    if booking is not None:
        if booking.user_id == user.id:
            return Cell(court, slot, "own", "Deine Buchung", booking.id, is_past)
        label = booking.user.name if user.is_admin else "Belegt"
        return Cell(court, slot, "booked", label, booking.id, is_past)
    for block in blocks:
        if block.start_at < slot_end(slot) and block.end_at > slot:
            return Cell(court, slot, "blocked", block.reason, is_past=is_past)
    if is_past:
        return Cell(court, slot, "past", is_past=True)
    if slot.date() > last_day:
        return Cell(court, slot, "later")
    return Cell(court, slot, "free", "Frei")
