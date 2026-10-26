"""Buchungsregeln auf Service-Ebene mit festem Zeitpunkt NOW (FA-05 bis FA-09)."""

from datetime import date, datetime, timedelta

import pytest
from sqlalchemy.exc import IntegrityError

from app.config import TZ
from app.models import Block, Booking, BookingStatus, RentalItem, Season, Sport
from app.services import booking as svc
from app.services.booking import BookingError, ForbiddenError, NotFoundError
from tests.conftest import NOW, slot


def book(db, world, who="m_lena", court="court1", start=None, minutes=None, items=None):
    return svc.book_slot(db, world[who], world[court].id, start or slot(1, 18), minutes, items,
                         now=NOW)


def test_book_free_slot(db, world):
    b = book(db, world)
    assert b.status == BookingStatus.CONFIRMED
    assert b.end_at - b.start_at == timedelta(minutes=60)
    assert b.price_cents == 0


def test_padel_60_or_90_minutes_with_hourly_prices(db, world):
    early = book(db, world, court="padel", start=slot(1, 15, 30), minutes=90)
    prime = book(db, world, who="m_jonas", court="padel", start=slot(1, 17), minutes=90)
    assert early.end_at == slot(1, 17) and early.price_cents == 5400  # 1,5 × 36 €
    assert prime.end_at == slot(1, 18, 30) and prime.price_cents == 6600  # 1,5 × 44 €
    assert book(db, world, court="padel", start=slot(2, 10)).minutes == 60  # kürzeste Dauer


def test_price_across_prime_start(world):
    # 16:30–17:30: halbe Stunde normal (18 €) + halbe Stunde Hauptzeit (22 €)
    assert svc.court_price(world["club"], world["padel"], slot(1, 16, 30), 60) == 4000


def test_duration_must_be_offered(db, world):
    with pytest.raises(BookingError, match="60 Minuten"):
        book(db, world, minutes=90)  # Platz 1 bietet nur 60 Minuten an


def test_duration_must_end_before_closing(db, world):
    with pytest.raises(BookingError, match="bis zum Schluss"):
        book(db, world, court="padel", start=slot(1, 21), minutes=90)
    assert book(db, world, court="padel", start=slot(1, 21), minutes=60).end_at == slot(1, 22)


def test_start_must_be_on_half_hour_grid(db, world):
    with pytest.raises(BookingError, match="Öffnungszeiten"):
        book(db, world, court="padel", start=slot(1, 18, 15))


def test_overlap_with_longer_booking_rejected(db, world):
    book(db, world, court="padel", start=slot(1, 17), minutes=90)
    with pytest.raises(BookingError, match="gerade"):
        book(db, world, who="m_jonas", court="padel", start=slot(1, 18))


def _items(db, world):
    club = world["club"]
    rackets = RentalItem(club_id=club.id, name="Padelschläger", sport=Sport.PADEL,
                         price_cents=400, max_per_booking=4)
    balls = RentalItem(club_id=club.id, name="Tennisbälle", sport=Sport.TENNIS,
                       price_cents=600, max_per_booking=2)
    db.add_all([rackets, balls])
    db.commit()
    return rackets, balls


def test_rental_items_added_to_price(db, world):
    rackets, _ = _items(db, world)
    b = book(db, world, court="padel", start=slot(1, 17), minutes=90, items={rackets.id: 2})
    assert b.court_price_cents == 6600 and b.price_cents == 6600 + 800
    assert [(i.name, i.quantity, i.price_cents) for i in b.items] == [("Padelschläger", 2, 400)]
    rackets.price_cents = 500  # spätere Preisänderung ändert die Buchung nicht
    db.commit()
    db.refresh(b)
    assert b.items[0].price_cents == 400


def test_rental_items_validated(db, world):
    rackets, balls = _items(db, world)
    with pytest.raises(BookingError, match="nicht verfügbar"):
        book(db, world, court="padel", start=slot(1, 17), items={balls.id: 1})  # Tennisbälle
    with pytest.raises(BookingError, match="höchstens 4"):
        book(db, world, court="padel", start=slot(1, 17), items={rackets.id: 5})
    rackets.is_active = False
    db.commit()
    with pytest.raises(BookingError, match="nicht verfügbar"):
        book(db, world, court="padel", start=slot(1, 17), items={rackets.id: 1})


def test_duration_options(db, world):
    book(db, world, who="m_jonas", court="padel", start=slot(1, 18))  # 18:00–19:00
    options = svc.duration_options(db, world["club"], world["padel"], slot(1, 17))
    assert [(o.minutes, o.available, o.price_cents) for o in options] == [
        (60, True, 4400), (90, False, 6600)]


def test_outside_opening_hours(db, world):
    with pytest.raises(BookingError, match="Öffnungszeiten"):
        book(db, world, start=slot(1, 7))
    with pytest.raises(BookingError):
        book(db, world, start=slot(1, 21, 30))  # 60 Minuten passen nicht mehr bis 22 Uhr


def test_closed_weekday(db, world):
    tuesday = next(h for h in world["club"].hours if h.weekday == 1)
    tuesday.is_closed = True
    db.commit()
    with pytest.raises(BookingError):
        book(db, world, start=slot(1, 18))  # NOW ist Montag, +1 = Dienstag


def test_season_court_closed_in_winter(db, world):
    world["court1"].season = Season.SUMMER
    db.commit()
    with pytest.raises(BookingError, match="Saison"):
        book(db, world)


def test_season_over_new_year(world):
    club = world["club"]
    club.summer_start, club.summer_end = date(2000, 11, 1), date(2000, 2, 28)
    assert svc.in_summer(club, date(2026, 12, 24))
    assert svc.in_summer(club, date(2027, 1, 10))
    assert not svc.in_summer(club, date(2027, 6, 1))


def test_no_booking_in_past(db, world):
    with pytest.raises(BookingError, match="Vergangenheit"):
        book(db, world, start=slot(0, 9))


def test_max_days_ahead(db, world):
    book(db, world, start=slot(7, 18))
    with pytest.raises(BookingError, match="7 Tage"):
        book(db, world, who="m_jonas", start=slot(8, 18))


def test_max_active_bookings(db, world):
    book(db, world, start=slot(1, 18))
    book(db, world, start=slot(2, 18))
    with pytest.raises(BookingError, match="2 aktive"):
        book(db, world, start=slot(3, 18))


def test_double_booking_rejected(db, world):
    book(db, world)
    with pytest.raises(BookingError, match="gerade"):
        book(db, world, who="m_jonas")


def test_database_rejects_overlapping_bookings(db, world):
    """Ausschluss-Constraint: auch an der Anwendung vorbei keine Überlappung."""
    court = world["padel"]
    db.add(Booking(club_id=court.club_id, court_id=court.id, user_id=world["lena"].id,
                   start_at=slot(1, 17), end_at=slot(1, 18, 30)))
    db.commit()
    db.add(Booking(club_id=court.club_id, court_id=court.id, user_id=world["jonas"].id,
                   start_at=slot(1, 18), end_at=slot(1, 19, 30)))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
    # Direkt anschließend ([) = Ende exklusiv) ist erlaubt, ebenso nach Stornierung
    db.add(Booking(club_id=court.club_id, court_id=court.id, user_id=world["jonas"].id,
                   start_at=slot(1, 18, 30), end_at=slot(1, 20)))
    db.commit()


def test_cancelled_slot_can_be_booked_again(db, world):
    b = book(db, world)
    svc.cancel_booking(db, world["m_lena"], b.id, now=NOW)
    again = book(db, world, who="m_jonas")
    assert again.status == BookingStatus.CONFIRMED


def test_blocked_slot(db, world):
    db.add(Block(club_id=world["club"].id, court_id=world["court1"].id, start_at=slot(1, 17),
                 end_at=slot(1, 20), reason="Medenspiel", created_by_id=world["admin"].id))
    db.commit()
    with pytest.raises(BookingError, match="Medenspiel"):
        book(db, world)


def test_court_of_other_club_not_found(db, world):
    with pytest.raises(NotFoundError):
        book(db, world, court="court_b")


def test_inactive_court(db, world):
    world["court1"].is_active = False
    db.commit()
    with pytest.raises(BookingError):
        book(db, world)


def test_cancel_own_and_not_others(db, world):
    b = book(db, world)
    with pytest.raises(ForbiddenError):
        svc.cancel_booking(db, world["m_jonas"], b.id, now=NOW)
    svc.cancel_booking(db, world["m_lena"], b.id, now=NOW)
    assert b.status == BookingStatus.CANCELLED and b.cancelled_by_id == world["lena"].id


def test_admin_cancels_member_booking(db, world):
    b = book(db, world)
    svc.cancel_booking(db, world["m_admin"], b.id, now=NOW)
    assert b.cancelled_by_id == world["admin"].id


def test_admin_of_other_club_cannot_cancel(db, world):
    b = book(db, world)
    with pytest.raises(NotFoundError):
        svc.cancel_booking(db, world["m_bea"], b.id, now=NOW)


def test_cancel_deadline_for_members_only(db, world):
    world["club"].cancel_hours = 24
    db.commit()
    b = book(db, world, start=slot(1, 9))  # 23 Stunden nach NOW
    with pytest.raises(BookingError, match="24 Stunden"):
        svc.cancel_booking(db, world["m_lena"], b.id, now=NOW)
    svc.cancel_booking(db, world["m_admin"], b.id, now=NOW)


def test_cannot_cancel_started_booking(db, world):
    b = book(db, world, start=slot(1, 9))
    with pytest.raises(BookingError, match="Spielbeginn"):
        svc.cancel_booking(db, world["m_lena"], b.id, now=slot(1, 9, 30))


def test_week_view_states(db, world):
    book(db, world, start=slot(1, 18))
    book(db, world, who="m_jonas", court="padel", start=slot(1, 17), minutes=90)
    club, courts, days = svc.build_week(db, world["m_lena"], svc.week_start_for(NOW.date()),
                                        now=NOW)
    tuesday = days[1]
    assert tuesday.opens == 8 * 60 and tuesday.closes == 22 * 60
    tennis = next(c for c in tuesday.columns if c.court.id == world["court1"].id)
    padel = next(c for c in tuesday.columns if c.court.id == world["padel"].id)
    by_start = {c.start: c for c in tennis.cells}
    assert by_start[slot(1, 18)].state == "own" and by_start[slot(1, 18)].end == slot(1, 19)
    assert by_start[slot(1, 17, 30)].state == "short"  # 60 Minuten passen nicht vor 18 Uhr
    assert by_start[slot(1, 21)].state == "free" and by_start[slot(1, 21, 30)].state == "short"
    padel_by_start = {c.start: c for c in padel.cells}
    booked = padel_by_start[slot(1, 17)]
    assert booked.state == "booked" and booked.minutes == 90
    assert booked.label == "Belegt"  # Mitglieder sehen keine Namen
    assert padel_by_start[slot(1, 18, 30)].price_cents == 4400  # 60 Minuten Hauptzeit
    assert padel_by_start[slot(1, 10)].price_cents == 3600
    monday = next(c for c in days[0].columns if c.court.id == world["court1"].id)
    monday_past = {c.start: c for c in monday.cells}
    assert monday_past[slot(0, 9)].state == "past"


def test_week_view_admin_sees_names_and_season_note(db, world):
    book(db, world)
    world["padel"].season = Season.SUMMER
    db.commit()
    _, _, days = svc.build_week(db, world["m_admin"], svc.week_start_for(NOW.date()), now=NOW)
    tennis = next(c for c in days[1].columns if c.court.id == world["court1"].id)
    assert any(c.label == "Lena Hofmann" for c in tennis.cells)
    padel = next(c for c in days[1].columns if c.court.id == world["padel"].id)
    assert padel.cells == [] and padel.note == "außerhalb der Saison"


def test_week_view_beyond_horizon_is_later(db, world):
    _, _, days = svc.build_week(db, world["m_lena"],
                                svc.week_start_for(NOW.date() + timedelta(days=7)), now=NOW)
    last = days[-1]  # Sonntag in 13 Tagen
    states = {c.state for col in last.columns for c in col.cells}
    assert states == {"later", "short"}  # short: 21:30, 60 Minuten passen nicht mehr


def test_slot_times_respect_dst(world):
    """Zeitumstellung Ende Oktober: Slots bleiben auf lokaler Uhrzeit."""
    club, court = world["club"], world["court1"]
    starts = svc.slot_starts(club, court, date(2026, 10, 25))
    assert starts[0] == datetime(2026, 10, 25, 8, tzinfo=TZ)
    assert starts[0].utcoffset() == timedelta(hours=1)
