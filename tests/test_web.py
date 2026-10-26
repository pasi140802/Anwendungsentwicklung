"""Oberfläche, Anmeldung, Rechte, CSRF und Sicherheits-Header über HTTP (NFA-04 bis NFA-06)."""

from sqlalchemy import select

from app.models import Block, Booking, BookingStatus, Sport
from app.services.booking import book_slot
from tests.conftest import PASSWORD, csrf_of, future_slot, last_mail, login


def test_login_required_redirects(client, world):
    r = client.get("/kalender", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login"
    r = client.get("/meine-buchungen", follow_redirects=False)
    assert r.headers["location"] == "/login?next=/meine-buchungen"


def test_login_follows_safe_next_only(client, world):
    token = csrf_of(client)
    r = client.post("/login", data={"email": "lena@a.de", "password": PASSWORD,
                                    "next": "//boese.example", "csrf_token": token},
                    follow_redirects=False)
    assert r.headers["location"] == "/kalender"


def test_login_error_is_generic(client, world):
    token = csrf_of(client)
    wrong_pw = client.post("/login", data={"email": "lena@a.de", "password": "falsch",
                                           "csrf_token": token})
    unknown = client.post("/login", data={"email": "nie@a.de", "password": "falsch",
                                          "csrf_token": token})
    assert wrong_pw.status_code == unknown.status_code == 400
    assert "E-Mail-Adresse oder Passwort ist falsch." in wrong_pw.text
    assert "E-Mail-Adresse oder Passwort ist falsch." in unknown.text


def test_session_cookie_flags(client, world):
    token = csrf_of(client)
    r = client.post("/login", data={"email": "lena@a.de", "password": PASSWORD,
                                    "csrf_token": token}, follow_redirects=False)
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie


def test_security_headers(client):
    r = client.get("/login")
    csp = r.headers["content-security-policy"]
    assert "script-src 'self'" in csp and "frame-ancestors 'none'" in csp
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["referrer-policy"] == "same-origin"


def test_post_without_csrf_is_rejected(client, world):
    login(client, "lena@a.de")
    r = client.post("/buchungen", data={"court_id": world["court1"].id,
                                        "start": future_slot().isoformat()})
    assert r.status_code == 403


def test_member_books_via_calendar(client, world):
    token = login(client, "lena@a.de")
    page = client.get("/kalender")
    assert page.status_code == 200 and "Platz 1" in page.text and "Platz B" not in page.text
    assert "Padel, ab 36\u00a0€/Std." in page.text
    r = client.post("/buchungen", data={"court_id": world["court1"].id,
                                        "start": future_slot().isoformat(), "csrf_token": token},
                    headers={"HX-Request": "true"})
    assert r.status_code == 200 and "Gebucht: Platz 1" in r.text and 'id="week"' in r.text
    msg = last_mail("lena@a.de")
    assert msg["Subject"].startswith("Gebucht: Platz 1")
    mine = client.get("/meine-buchungen").text
    assert "Platz 1" in mine and "Stornieren" in mine


def test_padel_booking_with_duration_and_rentals(client, world, db):
    from app.models import RentalItem

    rackets = RentalItem(club_id=world["club"].id, name="Padelschläger", sport=Sport.PADEL,
                         price_cents=400, max_per_booking=4)
    db.add(rackets)
    db.commit()
    token = login(client, "lena@a.de")
    start = future_slot(1, 17)
    page = client.get(f"/kalender?tag={start.date().isoformat()}").text
    assert "44\u00a0€" in page and "36\u00a0€" in page
    dialog = client.get("/buchen", params={"court_id": world["padel"].id,
                                           "start": start.isoformat()},
                        headers={"HX-Request": "true"})
    assert "<html" not in dialog.text and "66\u00a0€" in dialog.text
    client.post("/buchungen", data={"court_id": world["padel"].id, "start": start.isoformat(),
                                    "duration": "90", f"item_{rackets.id}": "2",
                                    "csrf_token": token})
    booking = db.scalars(select(Booking)).one()
    assert booking.minutes == 90 and booking.price_cents == 6600 + 800
    mine = client.get("/meine-buchungen").text
    assert "74\u00a0€" in mine and "2× Padelschläger" in mine
    body = last_mail("lena@a.de").get_body(("plain",)).get_content()
    assert "90 Minuten" in body and "2× Padelschläger" in body and "74\u00a0€" in body


def test_rule_violation_message_shown(client, world):
    token = login(client, "lena@a.de")
    for day in (1, 2, 3):
        r = client.post("/buchungen", data={"court_id": world["court1"].id,
                                            "start": future_slot(day).isoformat(),
                                            "csrf_token": token})
    assert r.status_code == 200 and "bereits 2 aktive Buchungen" in r.text


def test_cancel_via_form(client, world, db):
    token = login(client, "lena@a.de")
    client.post("/buchungen", data={"court_id": world["court1"].id,
                                    "start": future_slot().isoformat(), "csrf_token": token})
    booking = db.scalars(select(Booking)).one()
    r = client.post(f"/buchungen/{booking.id}/storno",
                    data={"csrf_token": token, "back": "/meine-buchungen"})
    assert "Storniert: Platz 1" in r.text


def test_cancel_deadline_shown_in_my_bookings(client, world, db):
    world["club"].cancel_hours = 6
    db.commit()
    token = login(client, "lena@a.de")
    client.post("/buchungen", data={"court_id": world["court1"].id,
                                    "start": future_slot(2).isoformat(), "csrf_token": token})
    assert "Kostenlos stornierbar bis" in client.get("/meine-buchungen").text


def test_admin_cancels_member_booking_in_calendar(client, world, db):
    booking = book_slot(db, world["m_lena"], world["court1"].id, future_slot())
    token = login(client, "admin@a.de")
    page = client.get(f"/kalender?tag={future_slot().date().isoformat()}").text
    assert f'hx-post="/buchungen/{booking.id}/storno"' in page and "Lena Hofmann" in page
    r = client.post(f"/buchungen/{booking.id}/storno",
                    data={"csrf_token": token, "back": "/kalender"},
                    headers={"HX-Request": "true"})
    assert "Storniert: Platz 1" in r.text
    db.expire_all()
    assert db.get(Booking, booking.id).status == BookingStatus.CANCELLED
    assert "storniert" in last_mail("lena@a.de")["Subject"]


def test_block_reason_visible_in_calendar(client, world, db):
    start = future_slot(1, 10)
    db.add(Block(club_id=world["club"].id, court_id=world["court1"].id, start_at=start,
                 end_at=future_slot(1, 12), reason="Medenspiel", created_by_id=world["admin"].id))
    db.commit()
    login(client, "lena@a.de")
    page = client.get(f"/kalender?tag={start.date().isoformat()}").text
    assert 'title="Gesperrt: Medenspiel">Medenspiel</span>' in page


def test_tenant_isolation_over_http(client, world):
    token = login(client, "bea@b.de")
    r = client.post("/buchungen", data={"court_id": world["court1"].id,
                                        "start": future_slot().isoformat(), "csrf_token": token})
    assert "Platz nicht gefunden" in r.text or r.status_code == 404


def test_invalid_start_is_handled(client, world):
    token = login(client, "lena@a.de")
    r = client.post("/buchungen", data={"court_id": world["court1"].id, "start": "kaputt",
                                        "csrf_token": token})
    assert r.status_code == 200 and "Ungültige Startzeit." in r.text


def test_user_without_club_goes_to_start(client, world, db):
    from app.models import Membership

    db.delete(db.get(Membership, world["m_jonas"].id))
    db.commit()
    login(client, "jonas@a.de")
    r = client.get("/kalender", follow_redirects=False)
    assert r.headers["location"] == "/start"


def test_legal_pages_and_health(client):
    assert "Impressum" in client.get("/impressum").text
    assert "Datenschutzerklärung" in client.get("/datenschutz").text
    assert client.get("/health").json() == {"status": "ok"}


def test_old_rules_url_redirects(client, world):
    login(client, "admin@a.de")
    r = client.get("/admin/regeln", follow_redirects=False)
    assert r.headers["location"] == "/admin/verein"
