import os
import re
from datetime import datetime, timedelta

os.environ.setdefault(
    "DATABASE_URL", "postgresql+psycopg://courtslot@localhost:5433/courtslot_test"
)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.config import TZ  # noqa: E402
from app.db import Base, SessionLocal, engine  # noqa: E402
from app.models import Club, Court, Role, Sport, User  # noqa: E402
from app.security import hash_password  # noqa: E402

PASSWORD = "geheim123"
# Fester Zeitpunkt für Regeltests: Montag, 02.11.2026, 10:00 Uhr.
NOW = datetime(2026, 11, 2, 10, 0, tzinfo=TZ)


@pytest.fixture(autouse=True)
def clean_db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    # Neu angelegte Enum-Typen bekommen neue OIDs; alte Verbindungen verwerfen.
    engine.dispose()
    yield


@pytest.fixture
def db():
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture(scope="session")
def pw_hash():
    return hash_password(PASSWORD)


@pytest.fixture
def world(db, pw_hash):
    """Zwei Vereine; Verein A mit zwei Plätzen, Admin und zwei Mitgliedern."""
    a = Club(name="TC A", max_active_bookings=2, max_days_ahead=7)
    b = Club(name="TC B")
    db.add_all([a, b])
    db.flush()
    court1 = Court(club_id=a.id, name="Platz 1", sport=Sport.TENNIS, surface="Sand")
    court2 = Court(club_id=a.id, name="Padel 1", sport=Sport.PADEL, surface="Kunstrasen")
    court_b = Court(club_id=b.id, name="Platz B", sport=Sport.TENNIS)
    admin = User(club_id=a.id, name="Admin A", email="admin@a.de", role=Role.ADMIN,
                 password_hash=pw_hash)
    lena = User(club_id=a.id, name="Lena", email="lena@a.de", password_hash=pw_hash)
    jonas = User(club_id=a.id, name="Jonas", email="jonas@a.de", password_hash=pw_hash)
    other = User(club_id=b.id, name="Bea", email="bea@b.de", password_hash=pw_hash)
    db.add_all([court1, court2, court_b, admin, lena, jonas, other])
    db.commit()
    return dict(club=a, club_b=b, court1=court1, court2=court2, court_b=court_b,
                admin=admin, lena=lena, jonas=jonas, other=other)


def slot(day_offset: int, hour: int, base: datetime = NOW) -> datetime:
    d = base.date() + timedelta(days=day_offset)
    return datetime(d.year, d.month, d.day, hour, tzinfo=TZ)


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
