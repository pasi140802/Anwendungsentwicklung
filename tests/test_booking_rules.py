"""Buchungsregeln (FA-05 bis FA-09) mit festem Zeitpunkt NOW."""

from datetime import timedelta

import pytest

from app.models import Block, BookingStatus
from app.services.booking import (
    BookingError,
    ForbiddenError,
    NotFoundError,
    book_slot,
    build_week,
    cancel_booking,
    my_bookings,
    week_start_for,
)
from tests.conftest import NOW, slot


def test_book_free_slot(db, world):
    b = book_slot(db, world["lena"], world["court1"].id, slot(1, 18), now=NOW)
    assert b.status == BookingStatus.CONFIRMED
    assert b.end_at - b.start_at == timedelta(hours=1)


def test_slot_in_past_rejected(db, world):
    with pytest.raises(BookingError, match="Vergangenheit"):
        book_slot(db, world["lena"], world["court1"].id, slot(0, 9), now=NOW)


def test_slot_beyond_horizon_rejected(db, world):
    book_slot(db, world["lena"], world["court1"].id, slot(7, 9), now=NOW)  # Tag 7: erlaubt
    with pytest.raises(BookingError, match="7 Tage"):
        book_slot(db, world["jonas"], world["court1"].id, slot(8, 9), now=NOW)


def test_outside_opening_hours_rejected(db, world):
    with pytest.raises(BookingError, match="zwischen 8 und 22"):
        book_slot(db, world["lena"], world["court1"].id, slot(1, 22), now=NOW)
    with pytest.raises(BookingError, match="zwischen 8 und 22"):
        book_slot(db, world["lena"], world["court1"].id, slot(1, 7), now=NOW)


def test_start_not_on_full_hour_rejected(db, world):
    with pytest.raises(BookingError, match="vollen Stunde"):
        book_slot(db, world["lena"], world["court1"].id, slot(1, 18) + timedelta(minutes=30),
                  now=NOW)


def test_max_active_bookings(db, world):
    lena, c1 = world["lena"], world["court1"].id
    book_slot(db, lena, c1, slot(1, 18), now=NOW)
    book_slot(db, lena, c1, slot(2, 18), now=NOW)
    with pytest.raises(BookingError, match="bereits 2 aktive"):
        book_slot(db, lena, c1, slot(3, 18), now=NOW)


def test_past_bookings_do_not_count_as_active(db, world):
    lena, c1 = world["lena"], world["court1"].id
    book_slot(db, lena, c1, slot(1, 18), now=NOW)
    book_slot(db, lena, c1, slot(1, 19), now=NOW)
    later = NOW + timedelta(days=2)  # beide Buchungen liegen jetzt in der Vergangenheit
    book_slot(db, lena, c1, slot(3, 18), now=later)


def test_rule_change_applies(db, world):
    world["club"].max_active_bookings = 1
    db.commit()
    book_slot(db, world["lena"], world["court1"].id, slot(1, 18), now=NOW)
    with pytest.raises(BookingError, match="Maximum im Verein: 1"):
        book_slot(db, world["lena"], world["court1"].id, slot(2, 18), now=NOW)


def test_slot_taken_rejected(db, world):
    book_slot(db, world["lena"], world["court1"].id, slot(1, 18), now=NOW)
    with pytest.raises(BookingError, match="gerade von jemand anderem"):
        book_slot(db, world["jonas"], world["court1"].id, slot(1, 18), now=NOW)
    # Anderer Platz zur gleichen Zeit ist frei.
    book_slot(db, world["jonas"], world["court2"].id, slot(1, 18), now=NOW)


def test_blocked_slot_rejected(db, world):
    db.add(Block(club_id=world["club"].id, court_id=world["court1"].id, start_at=slot(1, 10),
                 end_at=slot(1, 14), reason="Medenspiel", created_by_id=world["admin"].id))
    db.commit()
    with pytest.raises(BookingError, match="gesperrt: Medenspiel"):
        book_slot(db, world["lena"], world["court1"].id, slot(1, 13), now=NOW)
    book_slot(db, world["lena"], world["court1"].id, slot(1, 14), now=NOW)


def test_inactive_court_rejected(db, world):
    world["court1"].is_active = False
    db.commit()
    with pytest.raises(BookingError, match="nicht buchbar"):
        book_slot(db, world["lena"], world["court1"].id, slot(1, 18), now=NOW)


def test_court_of_other_club_not_found(db, world):
    with pytest.raises(NotFoundError):
        book_slot(db, world["lena"], world["court_b"].id, slot(1, 18), now=NOW)


def test_cancel_own_booking_frees_slot(db, world):
    b = book_slot(db, world["lena"], world["court1"].id, slot(1, 18), now=NOW)
    cancel_booking(db, world["lena"], b.id, now=NOW)
    assert b.status == BookingStatus.CANCELLED
    book_slot(db, world["jonas"], world["court1"].id, slot(1, 18), now=NOW)


def test_cannot_cancel_foreign_booking(db, world):
    b = book_slot(db, world["lena"], world["court1"].id, slot(1, 18), now=NOW)
    with pytest.raises(ForbiddenError):
        cancel_booking(db, world["jonas"], b.id, now=NOW)
    cancel_booking(db, world["admin"], b.id, now=NOW)  # Admin darf alle


def test_cancel_only_before_start(db, world):
    b = book_slot(db, world["lena"], world["court1"].id, slot(1, 18), now=NOW)
    with pytest.raises(BookingError, match="bis zum Slotbeginn"):
        cancel_booking(db, world["lena"], b.id, now=slot(1, 18))


def test_cancel_twice_rejected(db, world):
    b = book_slot(db, world["lena"], world["court1"].id, slot(1, 18), now=NOW)
    cancel_booking(db, world["lena"], b.id, now=NOW)
    with pytest.raises(BookingError, match="bereits storniert"):
        cancel_booking(db, world["lena"], b.id, now=NOW)


def test_cancel_other_club_not_found(db, world):
    b = book_slot(db, world["lena"], world["court1"].id, slot(1, 18), now=NOW)
    with pytest.raises(NotFoundError):
        cancel_booking(db, world["other"], b.id, now=NOW)


def test_my_bookings_split(db, world):
    book_slot(db, world["lena"], world["court1"].id, slot(1, 18), now=NOW)
    book_slot(db, world["lena"], world["court1"].id, slot(2, 18), now=NOW)
    upcoming, past = my_bookings(db, world["lena"], now=slot(1, 20))
    assert len(upcoming) == 1 and len(past) == 1


def test_week_view_states(db, world):
    lena, jonas = world["lena"], world["jonas"]
    book_slot(db, lena, world["court1"].id, slot(1, 18), now=NOW)
    book_slot(db, jonas, world["court2"].id, slot(1, 18), now=NOW)
    db.add(Block(club_id=world["club"].id, court_id=world["court1"].id, start_at=slot(2, 9),
                 end_at=slot(2, 10), reason="Wartung", created_by_id=world["admin"].id))
    db.commit()
    courts, days = build_week(db, lena, week_start_for(NOW.date()), now=NOW)
    assert [c.name for c in courts] == ["Padel 1", "Platz 1"]
    states = {(c.court.name, c.start): c.state for d in days for _, row in d.rows for c in row}
    assert states[("Platz 1", slot(1, 18))] == "own"
    assert states[("Padel 1", slot(1, 18))] == "booked"
    assert states[("Platz 1", slot(2, 9))] == "blocked"
    assert states[("Platz 1", slot(0, 9))] == "past"
    assert states[("Platz 1", slot(1, 9))] == "free"
    # Andere Vereine tauchen nicht auf (FA-14).
    assert all(c.club_id == world["club"].id for c in courts)
    # 7 Tage, 14 Stunden
    assert len(days) == 7 and all(len(d.rows) == 14 for d in days)
