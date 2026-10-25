"""Mehrere Vereine: anlegen, per Code beitreten, einladen, wechseln, verlassen (Mandanten)."""

from sqlalchemy import select

from app import mail
from app.models import Club, Membership, MembershipStatus, Role
from tests.conftest import csrf_of, future_slot, last_mail, login, path_of
from tests.test_accounts import NEW_PW, register


def test_create_club_makes_creator_admin(client, world, db):
    token = login(client, "jonas@a.de")
    r = client.post("/verein/neu", data={"name": "Padel Arena Süd", "kind": "facility",
                                         "city": "Augsburg", "csrf_token": token},
                    follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/admin/plaetze"
    club = db.scalars(select(Club).where(Club.name == "Padel Arena Süd")).one()
    assert len(club.hours) == 7 and len(club.join_code) == 8
    page = client.get("/admin/plaetze")
    assert page.status_code == 200 and "Leg deinen ersten Platz an" in page.text
    # Der bisherige Verein bleibt erreichbar
    client.post("/verein/wechseln", data={"club_id": world["club"].id, "csrf_token": token})
    assert "TC A" in client.get("/kalender").text


def test_join_with_code_needs_approval(client, world, db):
    register(client, email="neu@example.de")
    client.get(path_of(mail.link_in(last_mail("neu@example.de"))))
    token = csrf_of(client, "/start")
    r = client.post("/beitreten", data={"code": "codea aaa", "csrf_token": token},
                    follow_redirects=False)
    assert r.status_code == 303
    assert "Warten auf Freigabe" in client.get("/start").text
    assert client.get("/kalender", follow_redirects=False).headers["location"] == "/start"

    admin = client.__class__(client.app)
    admin_token = login(admin, "admin@a.de")
    page = admin.get("/admin/mitglieder").text
    assert "Beitrittsanfragen" in page and "neu@example.de" in page
    m = db.scalars(select(Membership).where(Membership.status == MembershipStatus.PENDING)).one()
    admin.post(f"/admin/mitglieder/{m.id}/anfrage", data={"accept": "true",
                                                          "csrf_token": admin_token})
    assert "Willkommen" in last_mail("neu@example.de")["Subject"]
    assert client.get("/kalender").status_code == 200


def test_wrong_code(client, world):
    token = login(client, "lena@a.de")
    r = client.post("/beitreten", data={"code": "FALSCH12", "csrf_token": token})
    assert r.status_code == 400 and "keinen Verein" in r.text


def test_invitation_for_new_user(client, world, db):
    admin_token = login(client, "admin@a.de")
    client.post("/admin/einladungen", data={"email": "clara@example.de", "role": "member",
                                            "csrf_token": admin_token})
    link = path_of(mail.link_in(last_mail("clara@example.de")))
    client.cookies.clear()

    page = client.get(link)
    assert page.status_code == 200 and "TC A" in page.text and "Konto erstellen" in page.text
    invite = link.rsplit("/", 1)[1]
    r = register(client, email="clara@example.de", name="Clara", invite=invite)
    assert r.status_code == 303 and r.headers["location"] == link  # sofort bestätigt
    token = csrf_of(client, link)
    r = client.post(link, data={"csrf_token": token}, follow_redirects=False)
    assert r.headers["location"] == "/kalender"
    assert "TC A" in client.get("/kalender").text
    # Ein zweites Mal lässt sich die Einladung nicht verwenden
    assert client.get(link).status_code == 400


def test_invitation_for_other_email_rejected(client, world):
    admin_token = login(client, "admin@a.de")
    client.post("/admin/einladungen", data={"email": "clara@example.de", "role": "admin",
                                            "csrf_token": admin_token})
    link = path_of(mail.link_in(last_mail("clara@example.de")))
    client.cookies.clear()
    token = login(client, "jonas@a.de")
    assert "gilt für clara@example.de" in client.get(link).text
    r = client.post(link, data={"csrf_token": token})
    assert r.status_code == 400


def test_invitation_existing_user_joins_second_club(client, world, db):
    bea_admin = login(client, "bea@b.de")
    client.post("/admin/einladungen", data={"email": "lena@a.de", "csrf_token": bea_admin})
    link = path_of(mail.link_in(last_mail("lena@a.de")))
    client.cookies.clear()
    token = login(client, "lena@a.de")
    client.post(link, data={"csrf_token": token})
    page = client.get("/kalender").text
    assert "Platz B" in page and "Verein wechseln" in page
    client.post("/verein/wechseln", data={"club_id": world["club"].id, "csrf_token": token})
    assert "Platz 1" in client.get("/kalender").text
    # Meine Buchungen zeigt Spiele aus beiden Vereinen
    client.post("/buchungen", data={"court_id": world["court1"].id,
                                    "start": future_slot().isoformat(), "csrf_token": token})
    client.post("/verein/wechseln", data={"club_id": world["club_b"].id, "csrf_token": token})
    client.post("/buchungen", data={"court_id": world["court_b"].id,
                                    "start": future_slot().isoformat(), "csrf_token": token})
    mine = client.get("/meine-buchungen").text
    assert "Platz 1" in mine and "Platz B" in mine and "TC B" in mine


def test_switch_to_foreign_club_is_ignored(client, world):
    token = login(client, "lena@a.de")
    client.post("/verein/wechseln", data={"club_id": world["club_b"].id, "csrf_token": token})
    page = client.get("/kalender").text
    assert "TC A" in page and "Platz B" not in page


def test_leave_club_cancels_bookings(client, world, db):
    token = login(client, "lena@a.de")
    client.post("/buchungen", data={"court_id": world["court1"].id,
                                    "start": future_slot().isoformat(), "csrf_token": token})
    client.post(f"/konto/verein/{world['club'].id}/verlassen", data={"csrf_token": token})
    assert client.get("/kalender", follow_redirects=False).headers["location"] == "/start"


def test_admin_cannot_manage_other_club(client, world):
    token = login(client, "admin@a.de")
    r = client.post(f"/admin/mitglieder/{world['m_bea'].id}/sperren", data={"csrf_token": token})
    assert r.status_code == 404
    r = client.post(f"/admin/plaetze/{world['court_b'].id}/aktiv",
                    data={"active": "false", "csrf_token": token})
    assert r.status_code == 404


def test_role_change_and_last_admin_guard(client, world, db):
    token = login(client, "admin@a.de")
    r = client.post(f"/admin/mitglieder/{world['m_admin'].id}/rolle",
                    data={"role": "member", "csrf_token": token})
    assert "mindestens eine Person" in r.text
    client.post(f"/admin/mitglieder/{world['m_lena'].id}/rolle",
                data={"role": "admin", "csrf_token": token})
    db.expire_all()
    assert db.get(Membership, world["m_lena"].id).role == Role.ADMIN


def test_registration_with_new_password_logs_in_after_verify(client):
    register(client, email="x@example.de", password=NEW_PW)
    client.get(path_of(mail.link_in(last_mail("x@example.de"))))
    assert client.get("/konto").status_code == 200
