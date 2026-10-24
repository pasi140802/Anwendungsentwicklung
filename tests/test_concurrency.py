"""Nebenläufigkeit (FA-06, NFA-02): parallele Buchungsversuche über echte DB-Verbindungen."""

from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import func, select

from app.db import SessionLocal
from app.models import Booking, BookingStatus, User
from app.services.booking import BookingError, book_slot
from tests.conftest import NOW, slot


def _attempt(user_id: int, court_id: int, start) -> bool:
    session = SessionLocal()
    try:
        user = session.get(User, user_id)
        book_slot(session, user, court_id, start, now=NOW)
        return True
    except BookingError:
        return False
    finally:
        session.close()


def test_100_parallel_attempts_same_slot_one_wins(db, pw_hash, world):
    """100 Mitglieder versuchen denselben Slot zu buchen, je 25 gleichzeitig."""
    users = [User(club_id=world["club"].id, name=f"M{i}", email=f"m{i}@a.de",
                  password_hash=pw_hash) for i in range(100)]
    db.add_all(users)
    db.commit()
    court_id, start = world["court1"].id, slot(1, 18)
    with ThreadPoolExecutor(max_workers=25) as pool:
        results = list(pool.map(lambda u: _attempt(u.id, court_id, start), users))
    assert sum(results) == 1
    count = db.scalar(select(func.count(Booking.id)).where(
        Booking.court_id == court_id, Booking.start_at == start,
        Booking.status == BookingStatus.CONFIRMED))
    assert count == 1


def test_same_member_parallel_respects_max_active(db, world):
    """Ein Mitglied bucht 6 verschiedene Slots gleichzeitig: nur 2 dürfen gelingen."""
    lena = world["lena"]
    starts = [slot(day, 18) for day in range(1, 7)]
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda s: _attempt(lena.id, world["court1"].id, s), starts))
    assert sum(results) == 2
