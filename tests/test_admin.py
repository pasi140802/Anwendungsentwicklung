"""Betreiberbereich: Plätze, Sperren, Mitglieder, Vereinseinstellungen, Auslastung."""

from datetime import date

import pytest
from sqlalchemy import select

from app.models import Booking, BookingStatus, Court, MembershipStatus, Season, Sport
from app.services import admin as svc
from app.services.booking import BookingError, book_slot, week_start_for
from tests.conftest import NOW, future_slot, last_mail, login, slot


def test_save_court_with_all_fields(client, world, db):
    token = login(client, "admin@a.de")
    client.post("/admin/plaetze", data={
        "name": "Padel 2", "sport": "padel", "surface": "Kunstrasen", "durations": ["60", "90"],
        "season": "winter", "price": "18,50", "prime_price": "26", "is_indoor": "on",
        "csrf_token": token})
    court = db.scalars(select(Court).where(Court.name == "Padel 2")).one()
    assert court.sport == Sport.PADEL and court.durations == [60, 90]
    assert court.season == Season.WINTER and court.is_indoor and not court.has_floodlight
    assert court.hourly_price_cents == 1850 and court.prime_hourly_price_cents == 2600
    page = client.get("/admin/plaetze").text
    assert "18,50\u00a0€/Std." in page and "Hauptzeit 26\u00a0€/Std." in page


@pytest.mark.parametrize("data, message", [
    ({"name": "", "durations": ["60"]}, "Namen"),
    ({"name": "X", "durations": ["45"]}, "Spieldauer"),
    ({"name": "X", "durations": []}, "Spieldauer"),
    ({"name": "X", "durations": ["60"], "price": "zwölf"}, "Betrag"),
])
def test_save_court_validation(db, world, data, message):
    with pytest.raises(BookingError, match=message):
        svc.save_court(db, world["club"].id, data)


def test_rental_items_managed_and_offered(client, world, db):
    from app.models import RentalItem

    token = login(client, "admin@a.de")
    client.post("/admin/leihartikel", data={"name": "Padelschläger", "sport": "padel",
                                            "price": "4", "max_per_booking": "4",
                                            "csrf_token": token})
    item = db.scalars(select(RentalItem)).one()
    assert item.price_cents == 400 and item.sport == Sport.PADEL
    assert "Padelschläger" in client.get("/admin/plaetze").text
    client.cookies.clear()
    login(client, "lena@a.de")
    start = future_slot(1, 18).isoformat()
    form = client.get("/buchen", params={"court_id": world["padel"].id, "start": start})
    assert "Padelschläger" in form.text and "90 Min." in form.text
    tennis = client.get("/buchen", params={"court_id": world["court1"].id, "start": start})
    assert "Padelschläger" not in tennis.text  # nur für Padel
    client.cookies.clear()
    token = login(client, "admin@a.de")
    client.post(f"/admin/leihartikel/{item.id}/aktiv", data={"active": "false",
                                                             "csrf_token": token})
    db.expire_all()
    assert not db.get(RentalItem, item.id).is_active


def test_block_with_bookings_needs_confirmation(client, world, db):
    start = future_slot(2, 18)
    book_slot(db, world["m_lena"], world["court1"].id, start)
    token = login(client, "admin@a.de")
    form = {"court_id": world["court1"].id, "start": start.strftime("%Y-%m-%dT%H:%M"),
            "end": start.replace(hour=20).strftime("%Y-%m-%dT%H:%M"),
            "reason": "Medenspiel", "csrf_token": token}
    r = client.post("/admin/sperren", data=form)
    assert "Sperre bestätigen" in r.text and "Lena Hofmann" in r.text
    r = client.post("/admin/sperren", data={**form, "confirm": "true"})
    assert "1 Buchung storniert" in r.text
    msg = last_mail("lena@a.de")
    assert "storniert" in msg["Subject"] and "Medenspiel" in msg.get_body(("plain",)).get_content()
    db.expire_all()
    assert db.scalars(select(Booking)).one().status == BookingStatus.CANCELLED


def test_lock_member_cancels_future_bookings(client, world, db):
    book_slot(db, world["m_lena"], world["court1"].id, future_slot())
    token = login(client, "admin@a.de")
    client.post(f"/admin/mitglieder/{world['m_lena'].id}/sperren", data={"csrf_token": token})
    db.expire_all()
    assert db.scalars(select(Booking)).one().status == BookingStatus.CANCELLED
    from fastapi.testclient import TestClient

    from app.main import app
    with TestClient(app) as lena:
        login(lena, "lena@a.de")
        assert lena.get("/kalender", follow_redirects=False).headers["location"] == "/start"
    client.post(f"/admin/mitglieder/{world['m_lena'].id}/entsperren", data={"csrf_token": token})
    db.expire_all()
    assert world["m_lena"].status == MembershipStatus.ACTIVE


def test_update_club_settings(client, world, db):
    token = login(client, "admin@a.de")
    data = {"name": "TC A neu", "kind": "club", "city": "München", "max_active": "3",
            "max_days": "14", "cancel_hours": "6", "summer_start": "01.05.",
            "summer_end": "30.09.", "prime_from": "18:00", "prime_to": "22:00",
            "csrf_token": token}
    for d in range(7):
        data[f"opens_{d}"], data[f"closes_{d}"] = "07:00", "23:00"
    data["closed_6"] = "on"
    client.post("/admin/verein", data=data)
    db.expire_all()
    club = db.get(type(world["club"]), world["club"].id)
    assert club.name == "TC A neu" and club.max_days_ahead == 14 and club.cancel_hours == 6
    assert club.summer_start == date(2000, 5, 1) and club.prime_from == 18 * 60
    hours = {h.weekday: h for h in club.hours}
    assert hours[0].opens == 7 * 60 and hours[0].closes == 23 * 60 and hours[6].is_closed


@pytest.mark.parametrize("field, value, message", [
    ("opens_0", "23:00", "Öffnung vor dem Schluss"),
    ("opens_0", "8 Uhr", "Uhrzeit"),
    ("opens_0", "08:10", "Viertelstunden"),
    ("summer_start", "31.02.", "Datum"),
    ("max_days", "0", "Vorlauf"),
])
def test_update_club_validation(db, world, field, value, message):
    form = {"name": "TC A", "max_active": "2", "max_days": "7", "cancel_hours": "0",
            "summer_start": "15.04.", "summer_end": "15.10.", field: value}
    with pytest.raises(BookingError, match=message):
        svc.update_club(db, world["club"].id, form)


def test_utilization_in_hours(db, world):
    book_slot(db, world["m_lena"], world["padel"].id, slot(1, 17), 90, now=NOW)
    rows = {court.name: (booked, offered, share)
            for court, booked, offered, share in svc.utilization(
                db, world["club"].id, week_start_for(NOW.date()))}
    booked, offered, share = rows["Padel 1"]
    assert booked == 1.5 and offered == 7 * 14
    assert share == pytest.approx(1.5 / offered * 100)
    assert rows["Platz 1"][1] == 7 * 14


def test_new_join_code_replaces_old(client, world, db):
    token = login(client, "admin@a.de")
    client.post("/admin/beitrittscode", data={"csrf_token": token})
    db.expire_all()
    assert db.get(type(world["club"]), world["club"].id).join_code != "CODEAAAA"


def test_member_has_no_admin_access(client, world):
    login(client, "lena@a.de")
    for path in ("/admin/plaetze", "/admin/mitglieder", "/admin/verein", "/admin/auslastung"):
        r = client.get(path)
        assert r.status_code == 403 and "Nur für die Vereinsverwaltung" in r.text
