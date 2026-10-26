"""Nebenläufigkeit (FA-06, NFA-02): parallele Buchungsversuche über echte DB-Verbindungen."""

from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import func, select

from app.db import SessionLocal
from app.models import Booking, BookingStatus, Membership
from app.services.booking import BookingError, book_slot
from tests.conftest import NOW, make_member, make_user, slot


def _attempt(membership_id: int, court_id: int, start, minutes: int | None = None) -> bool:
    session = SessionLocal()
    try:
        member = session.get(Membership, membership_id)
        book_slot(session, member, court_id, start, minutes, now=NOW)
        return True
    except BookingError:
        return False
    finally:
        session.close()


def _confirmed_overlapping(db, court_id, start, end) -> int:
    return db.scalar(select(func.count(Booking.id)).where(
        Booking.court_id == court_id, Booking.start_at < end, Booking.end_at > start,
        Booking.status == BookingStatus.CONFIRMED))


def test_100_parallel_attempts_same_slot_one_wins(db, pw_hash, world):
    """100 Mitglieder versuchen denselben Slot zu buchen, je 25 gleichzeitig."""
    members = [make_member(db, make_user(db, pw_hash, f"M{i}", f"m{i}@a.de"), world["club"])
               for i in range(100)]
    db.commit()
    court_id, start = world["court1"].id, slot(1, 18)
    with ThreadPoolExecutor(max_workers=25) as pool:
        results = list(pool.map(lambda m: _attempt(m.id, court_id, start), members))
    assert sum(results) == 1
    assert _confirmed_overlapping(db, court_id, start, slot(1, 19)) == 1


def test_parallel_padel_attempts_one_wins(db, pw_hash, world):
    members = [make_member(db, make_user(db, pw_hash, f"P{i}", f"p{i}@a.de"), world["club"])
               for i in range(30)]
    db.commit()
    court_id, start = world["padel"].id, slot(1, 17)
    with ThreadPoolExecutor(max_workers=15) as pool:
        results = list(pool.map(lambda m: _attempt(m.id, court_id, start, 90), members))
    assert sum(results) == 1
    assert _confirmed_overlapping(db, court_id, start, slot(1, 18, 30)) == 1


def test_same_member_parallel_respects_max_active(db, world):
    """Ein Mitglied bucht 6 verschiedene Slots gleichzeitig: nur 2 dürfen gelingen."""
    m = world["m_lena"]
    starts = [slot(day, 18) for day in range(1, 7)]
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda s: _attempt(m.id, world["court1"].id, s), starts))
    assert sum(results) == 2
