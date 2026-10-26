import os
import re
from datetime import date, datetime, timedelta
from pathlib import Path

os.environ.setdefault(
    "DATABASE_URL", "postgresql+psycopg://courtslot@localhost:5433/courtslot_test"
)
# Die Tests löschen das komplette Schema: nur gegen eine Testdatenbank laufen lassen.
if not os.environ["DATABASE_URL"].rstrip("/").endswith("_test"):
    raise SystemExit("DATABASE_URL muss auf eine Datenbank mit Endung _test zeigen.")

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app import mail, ratelimit  # noqa: E402
from app.config import TZ  # noqa: E402
from app.db import Base, SessionLocal, engine  # noqa: E402
from app.models import (  # noqa: E402
    Club,
    Court,
    Membership,
    MembershipStatus,
    OpeningHours,
    Role,
    Sport,
    User,
)
from app.security import hash_password  # noqa: E402

PASSWORD = "Aufschlag-2026"
# Fester Zeitpunkt für Regeltests: Montag, 02.11.2026, 10:00 Uhr (Wintersaison).
NOW = datetime(2026, 11, 2, 10, 0, tzinfo=TZ)
ALEMBIC_INI = str(Path(__file__).resolve().parent.parent / "alembic.ini")


@pytest.fixture(scope="session", autouse=True)
def schema():
    """Schema einmal über die Migrationen aufbauen (prüft sie gleich mit)."""
    with engine.begin() as conn:  # leere Datenbank, auch nach älteren Testläufen
        conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public"))
    engine.dispose()
    command.upgrade(Config(ALEMBIC_INI), "head")
    engine.dispose()  # neue Enum-Typen: alte Verbindungen verwerfen
    yield


@pytest.fixture(autouse=True)
def clean_state():
    tables = ", ".join(t.name for t in Base.metadata.sorted_tables)
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    for limiter in ratelimit.ALL:
        limiter.reset()
    mail.OUTBOX.clear()
    yield


@pytest.fixture
def db():
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture(scope="session")
def pw_hash():
    return hash_password(PASSWORD)


def make_user(db, pw_hash, name: str, email: str) -> User:
    user = User(name=name, email=email, password_hash=pw_hash, email_verified_at=NOW)
    db.add(user)
    db.flush()
    return user


def make_member(db, user: User, club: Club, role: Role = Role.MEMBER,
                status: MembershipStatus = MembershipStatus.ACTIVE) -> Membership:
    m = Membership(user_id=user.id, club_id=club.id, role=role, status=status)
    db.add(m)
    db.flush()
    return m


def make_club(name: str, code: str, **kwargs) -> Club:
    club = Club(name=name, city="München", join_code=code,
                summer_start=date(2000, 4, 15), summer_end=date(2000, 10, 15), **kwargs)
    club.hours = [OpeningHours(weekday=d, opens=8 * 60, closes=22 * 60) for d in range(7)]
    return club


@pytest.fixture
def world(db, pw_hash):
    """Verein A (Tennis 60 Min. kostenlos; Padel 60/90 Min., 36 €/Std., Hauptzeit 44 €/Std.)
    und Verein B."""
    a = make_club("TC A", "CODEAAAA", max_active_bookings=2, max_days_ahead=7,
                  prime_from=17 * 60, prime_to=21 * 60)
    b = make_club("TC B", "CODEBBBB")
    db.add_all([a, b])
    db.flush()
    court1 = Court(club_id=a.id, name="Platz 1", sport=Sport.TENNIS, surface="Sand",
                   durations=[60])
    padel = Court(club_id=a.id, name="Padel 1", sport=Sport.PADEL, surface="Kunstrasen",
                  durations=[60, 90], hourly_price_cents=3600,
                  prime_hourly_price_cents=4400)
    court_b = Court(club_id=b.id, name="Platz B", sport=Sport.TENNIS, durations=[60])
    db.add_all([court1, padel, court_b])
    admin = make_user(db, pw_hash, "Admin A", "admin@a.de")
    lena = make_user(db, pw_hash, "Lena Hofmann", "lena@a.de")
    jonas = make_user(db, pw_hash, "Jonas Weber", "jonas@a.de")
    bea = make_user(db, pw_hash, "Bea Berg", "bea@b.de")
    m_admin = make_member(db, admin, a, Role.ADMIN)
    m_lena = make_member(db, lena, a)
    m_jonas = make_member(db, jonas, a)
    m_bea = make_member(db, bea, b, Role.ADMIN)
    db.commit()
    return dict(club=a, club_b=b, court1=court1, padel=padel, court_b=court_b,
                admin=admin, lena=lena, jonas=jonas, bea=bea,
                m_admin=m_admin, m_lena=m_lena, m_jonas=m_jonas, m_bea=m_bea)


def slot(day_offset: int, hour: int, minute: int = 0, base: datetime = NOW) -> datetime:
    d = base.date() + timedelta(days=day_offset)
    return datetime(d.year, d.month, d.day, hour, minute, tzinfo=TZ)


def future_slot(day_offset: int = 1, hour: int = 18) -> datetime:
    """Slot relativ zur echten Uhrzeit, für Tests über die Weboberfläche."""
    return slot(day_offset, hour, base=datetime.now(TZ))


@pytest.fixture
def client():
    from app.main import app

    with TestClient(app) as c:
        yield c


def csrf_of(client: TestClient, path: str = "/login") -> str:
    html = client.get(path).text
    return re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)


def login(client: TestClient, email: str, password: str = PASSWORD) -> str:
    token = csrf_of(client)
    r = client.post("/login", data={"email": email, "password": password, "csrf_token": token},
                    follow_redirects=False)
    assert r.status_code == 303, r.text
    return token


def last_mail(to: str):
    for msg in reversed(mail.OUTBOX):
        if msg["To"] == to:
            return msg
    raise AssertionError(f"keine Mail an {to}")


def path_of(link: str) -> str:
    return "/" + link.split("://", 1)[1].split("/", 1)[1]
