"""Oberfläche, Anmeldung, Rechte und CSRF über HTTP (NFA-04 bis NFA-06)."""

import pytest

from tests.conftest import csrf_of, future_slot, login


def test_login_required_redirects(client, world):
    r = client.get("/kalender", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login"


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
    r = client.post("/login", data={"email": "lena@a.de", "password": "geheim123",
                                    "csrf_token": token}, follow_redirects=False)
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie


def test_post_without_csrf_is_rejected(client, world):
    login(client, "lena@a.de")
    start = future_slot()
    r = client.post("/buchungen", data={"court_id": world["court1"].id,
                                        "start": start.isoformat()})
    assert r.status_code == 403


def test_member_books_via_calendar(client, world):
    token = login(client, "lena@a.de")
    page = client.get("/kalender")
    assert page.status_code == 200 and "Platz 1" in page.text and "Platz B" not in page.text
    start = future_slot()
    r = client.post("/buchungen", data={"court_id": world["court1"].id,
                                        "start": start.isoformat(), "csrf_token": token},
                    headers={"HX-Request": "true"})
    assert r.status_code == 200
    assert "Gebucht: Platz 1" in r.text
    assert 'id="week"' in r.text
    mine = client.get("/meine-buchungen").text
    assert "Platz 1" in mine and "Stornieren" in mine


def test_rule_violation_message_shown(client, world):
    token = login(client, "lena@a.de")
    for day in (1, 2, 3):
        r = client.post("/buchungen", data={"court_id": world["court1"].id,
                                            "start": future_slot(day).isoformat(),
                                            "csrf_token": token})
    assert r.status_code == 200  # Weiterleitung auf den Kalender
    assert "bereits 2 aktive Buchungen" in r.text


def test_cancel_via_form(client, world, db):
    token = login(client, "lena@a.de")
    client.post("/buchungen", data={"court_id": world["court1"].id,
                                    "start": future_slot().isoformat(), "csrf_token": token})
    from app.models import Booking
    booking = db.query(Booking).one()
    r = client.post(f"/buchungen/{booking.id}/storno",
                    data={"csrf_token": token, "back": "/meine-buchungen"})
    assert "Storniert: Platz 1" in r.text


@pytest.mark.parametrize("path", ["/admin/mitglieder", "/admin/plaetze", "/admin/sperren",
                                  "/admin/regeln", "/admin/auslastung"])
def test_admin_pages_forbidden_for_members(client, world, path):
    login(client, "lena@a.de")
    assert client.get(path).status_code == 403


@pytest.mark.parametrize("path", ["/admin/mitglieder", "/admin/plaetze", "/admin/sperren",
                                  "/admin/regeln", "/admin/auslastung"])
def test_admin_pages_ok_for_admin(client, world, path):
    login(client, "admin@a.de")
    assert client.get(path).status_code == 200


def test_admin_post_forbidden_for_member(client, world):
    token = login(client, "lena@a.de")
    r = client.post("/admin/regeln", data={"max_active": 10, "max_days": 30,
                                           "csrf_token": token})
    assert r.status_code == 403


def test_admin_creates_member_and_block_flow(client, world):
    token = login(client, "admin@a.de")
    r = client.post("/admin/mitglieder", data={"name": "Neu", "email": "neu@a.de",
                                               "role": "member", "csrf_token": token})
    assert "Startpasswort" in r.text
    start = future_slot(1, 10)
    end = future_slot(1, 12)
    client.post("/buchungen", data={"court_id": world["court1"].id,
                                    "start": future_slot(1, 11).isoformat(), "csrf_token": token})
    form = {"court_id": world["court1"].id, "start": start.strftime("%Y-%m-%dT%H:%M"),
            "end": end.strftime("%Y-%m-%dT%H:%M"), "reason": "Wartung", "csrf_token": token}
    confirm = client.post("/admin/sperren", data=form)
    assert "Sperre bestätigen" in confirm.text
    done = client.post("/admin/sperren", data={**form, "confirm": "true"})
    assert "Sperre angelegt, 1 Buchungen storniert." in done.text


def test_tenant_isolation_over_http(client, world, db):
    token = login(client, "bea@b.de")
    r = client.post("/buchungen", data={"court_id": world["court1"].id,
                                        "start": future_slot().isoformat(), "csrf_token": token})
    assert r.status_code == 404


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}
