"""Buchungslogik: Startraster, Spieldauer, Preise, Leihartikel, Regeln,
Doppelbuchungsschutz, Stornierung, Wochenansicht.

Startzeiten liegen im 30-Minuten-Raster ab Öffnung; gespielt wird so lange,
wie der Platz es anbietet (z. B. 60 oder 90 Minuten). Alle Funktionen
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
    BookingItem,
    BookingStatus,
    Club,
    Court,
    Membership,
    OpeningHours,
    RentalItem,
    Season,
    User,
)

GRID_MINUTES = 30  # Startzeiten liegen im 30-Minuten-Raster ab Öffnung


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


def durations_of(court: Court) -> list[int]:
    return sorted(court.durations or [60])


def day_bounds(day: date, hours: OpeningHours) -> tuple[datetime, datetime]:
    midnight = datetime.combine(day, time(0), TZ)
    return midnight + timedelta(minutes=hours.opens), midnight + timedelta(minutes=hours.closes)


def slot_starts(club: Club, court: Court, day: date) -> list[datetime]:
    """Alle möglichen Startzeiten eines Platzes an einem Tag (kürzeste Dauer passt)."""
    hours = hours_for(club, day)
    if hours is None or not court.is_active or not court_in_season(club, court, day):
        return []
    midnight = datetime.combine(day, time(0), TZ)
    shortest = durations_of(court)[0]
    return [midnight + timedelta(minutes=m)
            for m in range(hours.opens, hours.closes - shortest + 1, GRID_MINUTES)]


def _local_minute(dt: datetime) -> int:
    local = dt.astimezone(TZ)
    return local.hour * 60 + local.minute


def court_price(club: Club, court: Court, start: datetime, minutes: int) -> int:
    """Platzpreis in Cent: Stundenpreis anteilig je halbe Stunde, Hauptzeit zum Hauptzeitpreis."""
    total = 0
    for block in range(minutes // GRID_MINUTES):
        minute = _local_minute(start + timedelta(minutes=block * GRID_MINUTES))
        rate = court.hourly_price_cents
        if (club.prime_from is not None and court.prime_hourly_price_cents is not None
                and club.prime_from <= minute < club.prime_to):
            rate = court.prime_hourly_price_cents
        total += rate * GRID_MINUTES
    return round(total / 60)


def rental_items_for(db: Session, club_id: int, court: Court) -> list[RentalItem]:
    """Aktive Leihartikel, die zur Sportart des Platzes passen."""
    return db.scalars(
        select(RentalItem)
        .where(RentalItem.club_id == club_id, RentalItem.is_active.is_(True),
               (RentalItem.sport.is_(None)) | (RentalItem.sport == court.sport))
        .order_by(RentalItem.name)
    ).all()


def _overlapping(db: Session, court_id: int, start: datetime, end: datetime) -> bool:
    return db.scalar(select(func.count(Booking.id)).where(
        Booking.court_id == court_id, Booking.status == BookingStatus.CONFIRMED,
        Booking.start_at < end, Booking.end_at > start)) > 0


@dataclass
class DurationOption:
    minutes: int
    end: datetime
    price_cents: int
    available: bool
    reason: str = ""


def duration_options(db: Session, club: Club, court: Court,
                     start: datetime) -> list[DurationOption]:
    """Wählbare Spieldauern ab einer Startzeit, jeweils mit Preis und Verfügbarkeit."""
    hours = hours_for(club, start.astimezone(TZ).date())
    options = []
    for minutes in durations_of(court):
        end = start + timedelta(minutes=minutes)
        available, reason = True, ""
        if hours is None or end > day_bounds(start.astimezone(TZ).date(), hours)[1]:
            available, reason = False, "endet nach Schluss"
        elif _overlapping(db, court.id, start, end) or find_block(db, court.id, start, end):
            available, reason = False, "Anschluss belegt"
        options.append(DurationOption(minutes, end, court_price(club, court, start, minutes),
                                      available, reason))
    return options


def _check_slot_rules(club: Club, court: Court, start: datetime, minutes: int,
                      now: datetime) -> None:
    if start.tzinfo is None:
        raise ValueError("start muss eine Zeitzone haben")
    if not court.is_active:
        raise BookingError("Dieser Platz ist derzeit nicht buchbar.")
    if minutes not in durations_of(court):
        allowed = " oder ".join(str(d) for d in durations_of(court))
        raise BookingError(f"Dieser Platz ist für {allowed} Minuten buchbar.")
    local_day = start.astimezone(TZ).date()
    if not court_in_season(club, court, local_day):
        raise BookingError("Dieser Platz ist in dieser Saison geschlossen.")
    hours = hours_for(club, local_day)
    if start not in slot_starts(club, court, local_day) or hours is None:
        raise BookingError("Zu dieser Zeit ist der Platz nicht buchbar "
                           "(außerhalb der Öffnungszeiten).")
    if start + timedelta(minutes=minutes) > day_bounds(local_day, hours)[1]:
        raise BookingError(f"{minutes} Minuten passen nicht mehr bis zum Schluss.")
    if start <= now:
        raise BookingError("Slots in der Vergangenheit können nicht gebucht werden.")
    last_day = now.astimezone(TZ).date() + timedelta(days=club.max_days_ahead)
    if local_day > last_day:
        raise BookingError(
            f"Buchungen sind höchstens {club.max_days_ahead} Tage im Voraus möglich."
        )


def _rental_lines(db: Session, club_id: int, court: Court,
                  wanted: dict[int, int] | None) -> list[BookingItem]:
    """Prüft gewünschte Leihartikel und legt die Positionen mit festem Preis an."""
    if not wanted:
        return []
    allowed = {item.id: item for item in rental_items_for(db, club_id, court)}
    lines = []
    for item_id, quantity in wanted.items():
        if not quantity:
            continue
        item = allowed.get(item_id)
        if item is None:
            raise BookingError("Dieser Leihartikel ist für den Platz nicht verfügbar.")
        if not 1 <= quantity <= item.max_per_booking:
            raise BookingError(f"{item.name}: höchstens {item.max_per_booking} Stück.")
        lines.append(BookingItem(rental_item_id=item.id, name=item.name, quantity=quantity,
                                 price_cents=item.price_cents))
    return lines


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
              minutes: int | None = None, items: dict[int, int] | None = None,
              now: datetime | None = None) -> Booking:
    """Bucht einen Platz und setzt alle Regeln durch (FA-05 bis FA-07).

    Nebenläufigkeit:
    - Zwei Mitglieder, überlappende Zeit auf einem Platz: Der Ausschluss-Constraint
      lässt nur eine bestätigte Buchung zu, die zweite endet in einem IntegrityError.
    - Ein Mitglied, mehrere Slots gleichzeitig: Die Mitgliedschaft wird gesperrt
      (SELECT ... FOR UPDATE), damit die Höchstzahl nicht überschritten wird.
    """
    now = now or now_local()
    club = db.get(Club, member.club_id)
    court = get_court_in_club(db, club.id, court_id)
    minutes = minutes or durations_of(court)[0]
    _check_slot_rules(club, court, start, minutes, now)
    end = start + timedelta(minutes=minutes)
    lines = _rental_lines(db, club.id, court, items)

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
        court_cents = court_price(club, court, start, minutes)
        booking = Booking(club_id=club.id, court_id=court.id, user_id=member.user_id,
                          start_at=start, end_at=end, court_price_cents=court_cents,
                          price_cents=court_cents + sum(li.total_cents for li in lines),
                          items=lines)
        db.add(booking)
        db.flush()
        db.commit()
    except IntegrityError:
        db.rollback()
        raise BookingError("Diese Zeit wurde gerade von jemand anderem gebucht.") from None
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
        .options(selectinload(Booking.court), selectinload(Booking.items))
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
    state: str  # free | short | own | booked | blocked | past | later
    label: str = ""
    booking_id: int | None = None
    is_past: bool = False
    price_cents: int = 0  # bei freien Zeiten: Preis der kürzesten Dauer

    @property
    def minutes(self) -> int:
        return int((self.end - self.start).total_seconds() // 60)


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
            if hours is None or not court_in_season(club, court, day):
                note = "geschlossen" if hours is None else "außerhalb der Saison"
                view.columns.append(Column(court, [], note))
                continue
            cells = _day_cells(club, court, day, hours, now, last_day, member,
                               bookings_by_court.get(court.id, []),
                               blocks_by_court.get(court.id, []))
            view.columns.append(Column(court, cells))
        days.append(view)
    return club, courts, days


def _day_cells(club, court, day, hours, now, last_day, member, bookings, blocks) -> list[Cell]:
    """Belegung eines Platzes an einem Tag: Buchungen und Sperren in voller Länge,
    dazwischen freie Startzeiten im 30-Minuten-Raster."""
    day_open, day_close = day_bounds(day, hours)
    shortest = durations_of(court)[0]
    cells: list[Cell] = []
    t = day_open
    step = timedelta(minutes=GRID_MINUTES)
    while t < day_close:
        b = next((b for b in bookings if b.start_at < t + step and b.end_at > t), None)
        if b is not None:
            s, e = max(b.start_at, day_open), min(b.end_at, day_close)
            is_past = s <= now
            if b.user_id == member.user_id:
                cells.append(Cell(court, s, e, "own", "Deine Buchung", b.id, is_past))
            else:
                label = b.user.name if member.is_admin else "Belegt"
                cells.append(Cell(court, s, e, "booked", label, b.id, is_past))
            t = e
            continue
        blk = next((k for k in blocks if k.start_at < t + step and k.end_at > t), None)
        if blk is not None:
            s, e = max(blk.start_at, day_open), min(blk.end_at, day_close)
            cells.append(Cell(court, s, e, "blocked", blk.reason, is_past=s <= now))
            t = e
            continue
        price = court_price(club, court, t, shortest)
        fits = t + timedelta(minutes=shortest) <= day_close and not any(
            x.start_at < t + timedelta(minutes=shortest) and x.end_at > t
            for x in [*bookings, *blocks])
        if t <= now:
            cells.append(Cell(court, t, t + step, "past", is_past=True))
        elif not fits:
            cells.append(Cell(court, t, t + step, "short"))
        elif t.date() > last_day:
            cells.append(Cell(court, t, t + step, "later", price_cents=price))
        else:
            cells.append(Cell(court, t, t + step, "free", "Frei", price_cents=price))
        t = t + step
    return cells
