"""Konto: Registrierung mit E-Mail-Bestätigung, Passwort, Datenexport, Löschung."""

import json

from sqlalchemy import select

from app import mail
from app.models import Booking, BookingStatus, Membership, User
from tests.conftest import PASSWORD, csrf_of, future_slot, last_mail, login, path_of

NEW_PW = "Netzroller-77"


def register(client, email="neu@example.de", name="Nora Neu", password=NEW_PW, **extra):
    token = csrf_of(client, "/registrieren")
    data = {"name": name, "email": email, "password": password, "password2": password,
            "consent": "on", "csrf_token": token, **extra}
    return client.post("/registrieren", data=data, follow_redirects=False)


def test_register_verify_and_login(client, db):
    r = register(client)
    assert r.status_code == 200 and "neu@example.de" in r.text
    user = db.scalars(select(User).where(User.email == "neu@example.de")).one()
    assert user.email_verified_at is None

    # Vor der Bestätigung ist keine Anmeldung möglich
    token = csrf_of(client)
    r = client.post("/login", data={"email": "neu@example.de", "password": NEW_PW,
                                    "csrf_token": token})
    assert r.status_code == 400 and "bestätige zuerst" in r.text

    link = mail.link_in(last_mail("neu@example.de"))
    r = client.get(path_of(link), follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/start"
    page = client.get("/start")
    assert "Beitrittscode" in page.text and "Verein anlegen" in page.text
    db.refresh(user)
    assert user.email_verified_at is not None


def test_register_validation(client):
    r = register(client, password="kurz")
    assert r.status_code == 400 and "mindestens 10 Zeichen" in r.text
    token = csrf_of(client, "/registrieren")
    r = client.post("/registrieren", data={"name": "Nora", "email": "n@example.de",
                                           "password": NEW_PW, "password2": NEW_PW,
                                           "csrf_token": token})
    assert r.status_code == 400 and "Datenschutzerklärung" in r.text
    r = register(client, email="keine-adresse")
    assert r.status_code == 400 and "gültige E-Mail-Adresse" in r.text


def test_register_existing_email_does_not_leak(client, world, db):
    r = register(client, email="lena@a.de", name="Fremd")
    assert r.status_code == 200  # gleiche Antwort wie bei neuer Adresse
    msg = last_mail("lena@a.de")
    assert "bereits" in msg["Subject"]
    assert db.scalars(select(User).where(User.email == "lena@a.de")).one().name == "Lena Hofmann"


def test_verification_link_tampered(client):
    register(client)
    link = mail.link_in(last_mail("neu@example.de"))
    r = client.get(path_of(link) + "x")
    assert r.status_code == 400 and "ungültig" in r.text


def test_password_reset_once(client, world):
    token = csrf_of(client, "/passwort-vergessen")
    r = client.post("/passwort-vergessen", data={"email": "lena@a.de", "csrf_token": token})
    assert r.status_code == 200
    unknown = client.post("/passwort-vergessen", data={"email": "nie@a.de", "csrf_token": token})
    assert unknown.status_code == 200 and len(mail.OUTBOX) == 1  # keine Mail, gleiche Antwort

    path = path_of(mail.link_in(last_mail("lena@a.de")))
    token = csrf_of(client, path)
    r = client.post(path, data={"password": NEW_PW, "password2": NEW_PW, "csrf_token": token},
                    follow_redirects=False)
    assert r.status_code == 303
    # Zweite Verwendung desselben Links schlägt fehl
    assert client.get(path).status_code == 400
    client.cookies.clear()
    login(client, "lena@a.de", NEW_PW)


def test_change_password_logs_out_other_sessions(world):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as phone, TestClient(app) as laptop:
        login(phone, "lena@a.de")
        token = login(laptop, "lena@a.de")
        r = laptop.post("/konto/passwort", data={"current": PASSWORD, "password": NEW_PW,
                                                 "password2": NEW_PW, "csrf_token": token},
                        follow_redirects=False)
        assert r.status_code == 303
        assert laptop.get("/kalender", follow_redirects=False).status_code == 200
        assert phone.get("/kalender", follow_redirects=False).status_code == 303
        assert "geändert" in last_mail("lena@a.de")["Subject"]


def test_change_password_needs_current(client, world):
    token = login(client, "lena@a.de")
    r = client.post("/konto/passwort", data={"current": "falsch", "password": NEW_PW,
                                             "password2": NEW_PW, "csrf_token": token})
    assert "aktuelle Passwort ist falsch" in r.text


def test_export_contains_own_data(client, world, db):
    token = login(client, "lena@a.de")
    client.post("/buchungen", data={"court_id": world["court1"].id,
                                    "start": future_slot().isoformat(), "csrf_token": token})
    r = client.get("/konto/export")
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    data = json.loads(r.text)
    assert data["konto"]["email"] == "lena@a.de"
    assert data["mitgliedschaften"][0]["verein"] == "TC A"
    assert len(data["buchungen"]) == 1
    assert "jonas" not in r.text


def test_delete_account_anonymizes(client, world, db):
    token = login(client, "lena@a.de")
    client.post("/buchungen", data={"court_id": world["court1"].id,
                                    "start": future_slot().isoformat(), "csrf_token": token})
    r = client.post("/konto/loeschen", data={"password": "falsch", "csrf_token": token},
                    follow_redirects=False)
    assert r.status_code == 303
    r = client.post("/konto/loeschen", data={"password": PASSWORD, "csrf_token": token})
    assert r.status_code == 200 and "gelöscht" in r.text
    db.expire_all()
    user = db.get(User, world["lena"].id)
    assert user.is_deleted and user.name == "Gelöschtes Konto" and "lena" not in user.email
    assert db.scalars(select(Membership).where(Membership.user_id == user.id)).all() == []
    booking = db.scalars(select(Booking).where(Booking.user_id == user.id)).one()
    assert booking.status == BookingStatus.CANCELLED
    token = csrf_of(client)
    r = client.post("/login", data={"email": "lena@a.de", "password": PASSWORD,
                                    "csrf_token": token})
    assert r.status_code == 400


def test_last_admin_cannot_delete_account(client, world):
    token = login(client, "admin@a.de")
    r = client.post("/konto/loeschen", data={"password": PASSWORD, "csrf_token": token})
    assert "einzige Person in der Verwaltung" in r.text


def test_login_rate_limit(client, world):
    token = csrf_of(client)
    codes = [client.post("/login", data={"email": "lena@a.de", "password": "falsch",
                                         "csrf_token": token}).status_code for _ in range(11)]
    assert codes[:10] == [400] * 10 and codes[10] == 429
    # Auch mit richtigem Passwort bleibt die Adresse vorerst gesperrt
    r = client.post("/login", data={"email": "lena@a.de", "password": PASSWORD,
                                    "csrf_token": token})
    assert r.status_code == 429


def test_logout_invalidates_copied_cookie(client, world):
    token = login(client, "lena@a.de")
    copied = dict(client.cookies)
    client.post("/logout", data={"csrf_token": token})
    client.cookies.clear()
    client.cookies.update(copied)
    assert client.get("/kalender", follow_redirects=False).status_code == 303


def test_maintenance_purges_old_unverified_accounts(client, db):
    from datetime import timedelta

    from scripts.maintenance import purge_unverified

    register(client, email="alt@example.de")
    register(client, email="frisch@example.de")
    old = db.scalars(select(User).where(User.email == "alt@example.de")).one()
    old.created_at = old.created_at - timedelta(days=8)
    db.commit()
    assert purge_unverified(db) == 1
    emails = set(db.scalars(select(User.email)).all())
    assert emails == {"frisch@example.de"}


def test_maintenance_purges_bookings_after_12_months(db, world):
    from datetime import timedelta

    from scripts.maintenance import purge_old_bookings
    from tests.conftest import NOW, slot

    court = world["court1"]
    for days in (400, 10):
        db.add(Booking(club_id=court.club_id, court_id=court.id, user_id=world["lena"].id,
                       start_at=slot(-days, 18), end_at=slot(-days, 19)))
    db.commit()
    assert purge_old_bookings(db, now=NOW) == 1
    remaining = db.scalars(select(Booking)).one()
    assert NOW - remaining.end_at < timedelta(days=30)
