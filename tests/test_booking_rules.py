"""Buchungsregeln auf Service-Ebene mit festem Zeitpunkt NOW (FA-05 bis FA-09)."""

from datetime import date, datetime, timedelta

import pytest
from sqlalchemy.exc import IntegrityError

from app.config import TZ
from app.models import Block, Booking, BookingStatus, Season
from app.services import booking as svc
from app.services.booking import BookingError, ForbiddenError, NotFoundError
from tests.conftest import NOW, slot


def book(db, world, who="m_lena", court="court1", start=None):
    return svc.book_slot(db, world[who], world[court].id, start or slot(1, 18), now=NOW)


def test_book_free_slot(db, world):
    b = book(db, world)
    assert b.status == BookingStatus.CONFIRMED
    assert b.end_at - b.start_at == timedelta(minutes=60)
    assert b.price_cents == 0


def test_padel_slot_is_90_minutes_with_prime_price(db, world):
    # Padel-Raster ab 08:00 in 90 Minuten: 08:00, 09:30, … 15:30, 17:00, 18:30, 20:00
    early = book(db, world, court="padel", start=slot(1, 15, 30))
    prime = book(db, world, who="m_jonas", court="padel", start=slot(1, 17))
    assert early.end_at == slot(1, 17) and early.price_cents == 1600
    assert prime.price_cents == 2400


def test_start_must_be_on_slot_grid(db, world):
    with pytest.raises(BookingError, match="Slotraster"):
        book(db, world, court="padel", start=slot(1, 18))  # 18:00 liegt nicht im 90er-Raster


def test_outside_opening_hours(db, world):
    with pytest.raises(BookingError, match="Öffnungszeiten"):
        book(db, world, start=slot(1, 7))
    with pytest.raises(BookingError):
        book(db, world, start=slot(1, 22))  # Schluss um 22 Uhr


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
    book(db, world, who="m_jonas", court="padel", start=slot(1, 17))
    club, courts, days = svc.build_week(db, world["m_lena"], svc.week_start_for(NOW.date()),
                                        now=NOW)
    tuesday = days[1]
    assert tuesday.opens == 8 * 60 and tuesday.closes == 22 * 60
    tennis = next(c for c in tuesday.columns if c.court.id == world["court1"].id)
    padel = next(c for c in tuesday.columns if c.court.id == world["padel"].id)
    assert len(tennis.cells) == 14 and len(padel.cells) == 9
    by_start = {c.start: c for c in tennis.cells}
    assert by_start[slot(1, 18)].state == "own"
    padel_by_start = {c.start: c for c in padel.cells}
    assert padel_by_start[slot(1, 17)].state == "booked"
    assert padel_by_start[slot(1, 17)].label == "Belegt"  # Mitglieder sehen keine Namen
    assert padel_by_start[slot(1, 18, 30)].price_cents == 2400
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
    assert all(c.state == "later" for col in last.columns for c in col.cells)


def test_slot_times_respect_dst(world):
    """Zeitumstellung Ende Oktober: Slots bleiben auf lokaler Uhrzeit."""
    club, court = world["club"], world["court1"]
    starts = svc.slot_starts(club, court, date(2026, 10, 25))
    assert starts[0] == datetime(2026, 10, 25, 8, tzinfo=TZ)
    assert starts[0].utcoffset() == timedelta(hours=1)
