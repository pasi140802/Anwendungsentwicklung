"""Buchungslogik: Slotraster, Regeln, Doppelbuchungsschutz, Stornierung, Wochenansicht.

Das Slotraster ergibt sich je Platz aus Öffnungszeiten des Vereins, Saison des
Platzes und Slotlänge (z. B. Tennis 60, Padel 90 Minuten). Alle Funktionen
erhalten den aktuellen Zeitpunkt als Parameter `now`, damit die Regeln in Tests
mit festen Zeitpunkten geprüft werden können.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.config import TZ
from app.models import (
    Block,
    Booking,
    BookingStatus,
    Club,
    Court,
    Membership,
    OpeningHours,
    Season,
    User,
)


class BookingError(Exception):
    """Fachlicher Fehler, der mit Grund angezeigt wird (FA-07)."""


class NotFoundError(Exception):
    """Objekt existiert nicht oder gehört zu einem anderen Verein (FA-14)."""


class ForbiddenError(Exception):
    """Aktion ist für diese Rolle nicht erlaubt."""


def now_local() -> datetime:
    return datetime.now(TZ)


def week_start_for(day: date) -> date:
    return day - timedelta(days=day.weekday())


def get_court_in_club(db: Session, club_id: int, court_id: int) -> Court:
    court = db.get(Court, court_id)
    if court is None or court.club_id != club_id:
        raise NotFoundError("Platz nicht gefunden")
    return court


# --- Slotraster ------------------------------------------------------------------

def in_summer(club: Club, day: date) -> bool:
    start = (club.summer_start.month, club.summer_start.day)
    end = (club.summer_end.month, club.summer_end.day)
    current = (day.month, day.day)
    if start <= end:
        return start <= current <= end
    return current >= start or current <= end  # Saison über den Jahreswechsel


def court_in_season(club: Club, court: Court, day: date) -> bool:
    if court.season == Season.ALL:
        return True
    summer = in_summer(club, day)
    return summer if court.season == Season.SUMMER else not summer


def hours_for(club: Club, day: date) -> OpeningHours | None:
    entry = next((h for h in club.hours if h.weekday == day.weekday()), None)
    if entry is None or entry.is_closed:
        return None
    return entry


def slot_starts(club: Club, court: Court, day: date) -> list[datetime]:
    """Alle Startzeiten eines Platzes an einem Tag."""
    hours = hours_for(club, day)
    if hours is None or not court.is_active or not court_in_season(club, court, day):
        return []
    midnight = datetime.combine(day, time(0), TZ)
    starts = []
    minute = hours.opens
    while minute + court.slot_minutes <= hours.closes:
        starts.append(midnight + timedelta(minutes=minute))
        minute += court.slot_minutes
    return starts


def slot_end(court: Court, start: datetime) -> datetime:
    return start + timedelta(minutes=court.slot_minutes)


def slot_price(club: Club, court: Court, start: datetime) -> int:
    """Preis in Cent; in der Hauptzeit gilt der Hauptzeitpreis, falls gesetzt."""
    if club.prime_from is not None and court.prime_price_cents is not None:
        local = start.astimezone(TZ)
        minute = local.hour * 60 + local.minute
        if club.prime_from <= minute < club.prime_to:
            return court.prime_price_cents
    return court.price_cents


def _check_slot_rules(club: Club, court: Court, start: datetime, now: datetime) -> None:
    if start.tzinfo is None:
        raise ValueError("start muss eine Zeitzone haben")
    if not court.is_active:
        raise BookingError("Dieser Platz ist derzeit nicht buchbar.")
    local_day = start.astimezone(TZ).date()
    if not court_in_season(club, court, local_day):
        raise BookingError("Dieser Platz ist in dieser Saison geschlossen.")
    if start not in slot_starts(club, court, local_day):
        raise BookingError("Zu dieser Zeit ist der Platz nicht buchbar "
                           "(außerhalb der Öffnungszeiten oder nicht im Slotraster).")
    if start <= now:
        raise BookingError("Slots in der Vergangenheit können nicht gebucht werden.")
    last_day = now.astimezone(TZ).date() + timedelta(days=club.max_days_ahead)
    if local_day > last_day:
        raise BookingError(
            f"Buchungen sind höchstens {club.max_days_ahead} Tage im Voraus möglich."
        )


def active_booking_count(db: Session, user_id: int, club_id: int, now: datetime) -> int:
    return db.scalar(
        select(func.count(Booking.id)).where(
            Booking.user_id == user_id,
            Booking.club_id == club_id,
            Booking.status == BookingStatus.CONFIRMED,
            Booking.start_at > now,
        )
    ) or 0


def find_block(db: Session, court_id: int, start: datetime, end: datetime) -> Block | None:
    return db.scalars(
        select(Block).where(Block.court_id == court_id, Block.start_at < end, Block.end_at > start)
    ).first()


def book_slot(db: Session, member: Membership, court_id: int, start: datetime,
              now: datetime | None = None) -> Booking:
    """Bucht einen Slot und setzt alle Regeln durch (FA-05 bis FA-07).

    Nebenläufigkeit:
    - Zwei Mitglieder, überlappende Zeit auf einem Platz: Der Ausschluss-Constraint
      lässt nur eine bestätigte Buchung zu, die zweite endet in einem IntegrityError.
    - Ein Mitglied, mehrere Slots gleichzeitig: Die Mitgliedschaft wird gesperrt
      (SELECT ... FOR UPDATE), damit die Höchstzahl nicht überschritten wird.
    """
    now = now or now_local()
    club = db.get(Club, member.club_id)
    court = get_court_in_club(db, club.id, court_id)
    _check_slot_rules(club, court, start, now)
    end = slot_end(court, start)

    try:
        db.execute(select(Membership.id).where(Membership.id == member.id).with_for_update())
        count = active_booking_count(db, member.user_id, club.id, now)
        if count >= club.max_active_bookings:
            raise BookingError(
                f"Du hast bereits {count} aktive Buchungen "
                f"(Maximum im Verein: {club.max_active_bookings})."
            )
        block = find_block(db, court.id, start, end)
        if block is not None:
            raise BookingError(f"Der Platz ist gesperrt: {block.reason}.")
        booking = Booking(club_id=club.id, court_id=court.id, user_id=member.user_id,
                          start_at=start, end_at=end, price_cents=slot_price(club, court, start))
        db.add(booking)
        db.flush()
        db.commit()
    except IntegrityError:
        db.rollback()
        raise BookingError("Dieser Slot wurde gerade von jemand anderem gebucht.") from None
    except BookingError:
        db.rollback()
        raise
    return booking


def cancel_deadline(club: Club, booking: Booking) -> datetime:
    return booking.start_at - timedelta(hours=club.cancel_hours)


def cancel_booking(db: Session, member: Membership, booking_id: int,
                   now: datetime | None = None) -> Booking:
    """Storniert eine Buchung (FA-09). Mitglieder bis zur Stornofrist, Admins bis Beginn."""
    now = now or now_local()
    booking = db.get(Booking, booking_id)
    if booking is None or booking.club_id != member.club_id:
        raise NotFoundError("Buchung nicht gefunden")
    if booking.user_id != member.user_id and not member.is_admin:
        raise ForbiddenError("Nur eigene Buchungen können storniert werden.")
    if booking.status != BookingStatus.CONFIRMED:
        raise BookingError("Diese Buchung ist bereits storniert.")
    if booking.start_at <= now:
        raise BookingError("Buchungen können nur bis zum Spielbeginn storniert werden.")
    club = db.get(Club, member.club_id)
    if not member.is_admin and club.cancel_hours and now > cancel_deadline(club, booking):
        raise BookingError(
            f"Stornieren ist bis {club.cancel_hours} Stunden vor Spielbeginn möglich. "
            "Wende dich bitte an die Vereinsverwaltung."
        )
    cancel(booking, member.user_id, now)
    db.commit()
    return booking


def cancel(booking: Booking, actor_user_id: int, now: datetime) -> None:
    booking.status = BookingStatus.CANCELLED
    booking.cancelled_at = now
    booking.cancelled_by_id = actor_user_id


def my_bookings(db: Session, user: User, now: datetime | None = None):
    """Kommende und vergangene eigene Buchungen über alle Vereine (FA-10)."""
    now = now or now_local()
    rows = db.scalars(
        select(Booking)
        .where(Booking.user_id == user.id, Booking.status == BookingStatus.CONFIRMED)
        .options(selectinload(Booking.court))
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
    end: datetime
    state: str  # free | own | booked | blocked | past | later
    label: str = ""
    booking_id: int | None = None
    is_past: bool = False
    price_cents: int = 0


@dataclass
class Column:
    court: Court
    cells: list[Cell]
    note: str = ""


@dataclass
class DayView:
    day: date
    columns: list[Column] = field(default_factory=list)
    closed: bool = False
    opens: int = 0  # Minuten ab Mitternacht, bestimmt die Zeitachse der Tagesansicht
    closes: int = 0

    @property
    def free_count(self) -> int:
        return sum(1 for col in self.columns for c in col.cells if c.state == "free")


def build_week(db: Session, member: Membership, monday: date, now: datetime | None = None):
    now = now or now_local()
    club = db.get(Club, member.club_id)
    courts = db.scalars(
        select(Court)
        .where(Court.club_id == club.id, Court.is_active.is_(True))
        .order_by(Court.name)
    ).all()
    start = datetime.combine(monday, time(0), TZ)
    end = start + timedelta(days=7)
    query = select(Booking).where(
        Booking.club_id == club.id,
        Booking.status == BookingStatus.CONFIRMED,
        Booking.start_at < end,
        Booking.end_at > start,
    )
    if member.is_admin:  # Admins sehen Namen: Benutzer in einer Abfrage mitladen (kein N+1)
        query = query.options(selectinload(Booking.user))
    bookings_by_court: dict[int, list[Booking]] = {}
    for b in db.scalars(query):
        bookings_by_court.setdefault(b.court_id, []).append(b)
    blocks_by_court: dict[int, list[Block]] = {}
    for block in db.scalars(
        select(Block).where(Block.club_id == club.id, Block.start_at < end, Block.end_at > start)
    ):
        blocks_by_court.setdefault(block.court_id, []).append(block)
    last_day = now.astimezone(TZ).date() + timedelta(days=club.max_days_ahead)

    days = []
    for offset in range(7):
        day = monday + timedelta(days=offset)
        hours = hours_for(club, day)
        view = DayView(day=day, closed=hours is None,
                       opens=hours.opens if hours else 0, closes=hours.closes if hours else 0)
        for court in courts:
            starts = slot_starts(club, court, day)
            note = ""
            if not starts:
                note = "geschlossen" if view.closed else "außerhalb der Saison"
            cells = [
                _cell(club, court, s, now, last_day, bookings_by_court.get(court.id, ()),
                      blocks_by_court.get(court.id, ()), member)
                for s in starts
            ]
            view.columns.append(Column(court, cells, note))
        days.append(view)
    return club, courts, days


def _cell(club, court, start, now, last_day, bookings, blocks, member) -> Cell:
    end = slot_end(court, start)
    is_past = start <= now
    price = slot_price(club, court, start)
    for b in bookings:
        if b.start_at < end and b.end_at > start:
            if b.user_id == member.user_id:
                return Cell(court, start, end, "own", "Deine Buchung", b.id, is_past, price)
            label = b.user.name if member.is_admin else "Belegt"
            return Cell(court, start, end, "booked", label, b.id, is_past, price)
    for block in blocks:
        if block.start_at < end and block.end_at > start:
            return Cell(court, start, end, "blocked", block.reason, is_past=is_past)
    if is_past:
        return Cell(court, start, end, "past", is_past=True)
    if start.date() > last_day:
        return Cell(court, start, end, "later", price_cents=price)
    return Cell(court, start, end, "free", "Frei", price_cents=price)
