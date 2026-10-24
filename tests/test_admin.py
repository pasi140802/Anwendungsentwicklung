"""Vereinsverwaltung (FA-03, FA-08, FA-11 bis FA-14)."""

from datetime import date

import pytest

from app.models import BookingStatus, Role, Sport
from app.security import verify_password
from app.services import admin as svc
from app.services.booking import BookingError, NotFoundError, book_slot
from tests.conftest import NOW, slot


def test_create_member_with_start_password(db, world):
    user, password = svc.create_member(db, world["club"].id, "Neu", "Neu@A.de", Role.MEMBER)
    assert user.email == "neu@a.de"
    assert user.password_hash.startswith("$argon2")  # NFA-04
    assert verify_password(user.password_hash, password)


def test_duplicate_email_rejected(db, world):
    with pytest.raises(BookingError, match="bereits vergeben"):
        svc.create_member(db, world["club"].id, "Lena 2", "lena@a.de", Role.MEMBER)


def test_lock_member_cancels_future_bookings(db, world):
    b = book_slot(db, world["lena"], world["court1"].id, slot(1, 18), now=NOW)
    n = svc.set_member_active(db, world["admin"], world["lena"].id, False, now=NOW)
    db.refresh(b)
    assert n == 1 and b.status == BookingStatus.CANCELLED
    assert world["lena"].is_active is False


def test_admin_cannot_lock_self(db, world):
    with pytest.raises(BookingError):
        svc.set_member_active(db, world["admin"], world["admin"].id, False, now=NOW)


def test_remove_member_anonymizes(db, world):
    book_slot(db, world["lena"], world["court1"].id, slot(1, 18), now=NOW)
    svc.remove_member(db, world["admin"], world["lena"].id, now=NOW)
    db.refresh(world["lena"])
    assert world["lena"].name == "Entferntes Mitglied"
    assert "lena" not in world["lena"].email
    assert world["lena"] not in svc.list_members(db, world["club"].id)


def test_member_of_other_club_not_found(db, world):
    with pytest.raises(NotFoundError):
        svc.set_member_active(db, world["admin"], world["other"].id, False, now=NOW)


def test_save_and_edit_court(db, world):
    court = svc.save_court(db, world["club"].id, "Platz 3", "tennis", "Sand")
    svc.save_court(db, world["club"].id, "Platz 3 (Halle)", "tennis", "Teppich", court.id)
    db.refresh(court)
    assert court.name == "Platz 3 (Halle)" and court.sport == Sport.TENNIS
    with pytest.raises(BookingError):
        svc.save_court(db, world["club"].id, "X", "squash", "")


def test_deactivate_court_with_future_bookings_rejected(db, world):
    book_slot(db, world["lena"], world["court1"].id, slot(1, 18), now=NOW)
    with pytest.raises(BookingError, match="künftige Buchungen"):
        svc.set_court_active(db, world["club"].id, world["court1"].id, False, now=NOW)
    svc.set_court_active(db, world["club"].id, world["court2"].id, False, now=NOW)


def test_block_needs_confirmation_and_cancels(db, world):
    b = book_slot(db, world["lena"], world["court1"].id, slot(1, 11), now=NOW)
    block, affected = svc.create_block(db, world["admin"], world["court1"].id, slot(1, 10),
                                       slot(1, 14), "Medenspiel", confirm=False, now=NOW)
    assert block is None and [x.id for x in affected] == [b.id]
    db.refresh(b)
    assert b.status == BookingStatus.CONFIRMED  # noch nichts storniert
    block, affected = svc.create_block(db, world["admin"], world["court1"].id, slot(1, 10),
                                       slot(1, 14), "Medenspiel", confirm=True, now=NOW)
    db.refresh(b)
    assert block is not None and b.status == BookingStatus.CANCELLED
    assert len(svc.list_blocks(db, world["club"].id, now=NOW)) == 1
    svc.delete_block(db, world["club"].id, block.id)
    assert svc.list_blocks(db, world["club"].id, now=NOW) == []


def test_block_validation(db, world):
    with pytest.raises(BookingError, match="nach dem Beginn"):
        svc.create_block(db, world["admin"], world["court1"].id, slot(1, 14), slot(1, 10),
                         "X", confirm=True, now=NOW)
    with pytest.raises(BookingError, match="Grund"):
        svc.create_block(db, world["admin"], world["court1"].id, slot(1, 10), slot(1, 14),
                         " ", confirm=True, now=NOW)


def test_update_rules_validation(db, world):
    svc.update_rules(db, world["club"].id, 3, 14)
    db.refresh(world["club"])
    assert world["club"].max_active_bookings == 3 and world["club"].max_days_ahead == 14
    with pytest.raises(BookingError):
        svc.update_rules(db, world["club"].id, 0, 14)
    with pytest.raises(BookingError):
        svc.update_rules(db, world["club"].id, 2, 90)


def test_utilization(db, world):
    book_slot(db, world["lena"], world["court1"].id, slot(1, 18), now=NOW)
    book_slot(db, world["jonas"], world["court1"].id, slot(1, 19), now=NOW)
    rows = svc.utilization(db, world["club"].id, date(2026, 11, 2))
    by_name = {court.name: (booked, offered, share) for court, booked, offered, share in rows}
    assert by_name["Platz 1"][0] == 2
    assert by_name["Platz 1"][1] == 7 * 14
    assert round(by_name["Platz 1"][2], 2) == round(2 / 98 * 100, 2)
