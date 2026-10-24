"""Demo-Daten laden (TS-03): Verein „TC Isartal“ mit 4 Plätzen, 20 Mitgliedern
und vorbelegten Buchungen sowie ein zweiter Verein zum Zeigen der Mandantentrennung.

Aufruf:  python -m scripts.seed           (legt Daten nur an, wenn die DB leer ist)
         python -m scripts.seed --reset   (löscht alle Tabellen und legt neu an)
"""

import random
import sys
from datetime import datetime, timedelta

from sqlalchemy import select

from app.config import TZ
from app.db import Base, SessionLocal, engine
from app.models import Block, Booking, Club, Court, Role, Sport, User
from app.security import hash_password

DEMO_PASSWORD = "demo1234"

MEMBERS = [
    "Lena Hofmann", "Jonas Weber", "Sophie Bauer", "Maximilian Huber", "Anna Schmid",
    "Felix Wagner", "Laura Mayer", "Paul Fischer", "Marie Schneider", "Lukas Becker",
    "Julia Richter", "Tobias Wolf", "Lea Schäfer", "Simon Koch", "Hannah Zimmermann",
    "David Krüger", "Katharina Braun", "Michael Hartmann", "Sarah Lange",
]


def email_for(name: str, domain: str) -> str:
    base = name.lower().replace(" ", ".")
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        base = base.replace(a, b)
    return f"{base}@{domain}"


def seed(reset: bool = False) -> None:
    if reset:
        Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    db = SessionLocal()
    if db.scalar(select(Club.id)) is not None:
        print("Datenbank enthält bereits Daten – nichts geändert (--reset zum Neuanlegen).")
        return

    pw = hash_password(DEMO_PASSWORD)
    club = Club(name="TC Isartal", max_active_bookings=2, max_days_ahead=7)
    db.add(club)
    db.flush()
    courts = [
        Court(club_id=club.id, name="Platz 1", sport=Sport.TENNIS, surface="Sand"),
        Court(club_id=club.id, name="Platz 2", sport=Sport.TENNIS, surface="Sand"),
        Court(club_id=club.id, name="Padel 1", sport=Sport.PADEL, surface="Kunstrasen"),
        Court(club_id=club.id, name="Padel 2", sport=Sport.PADEL, surface="Kunstrasen"),
    ]
    admin = User(club_id=club.id, name="Werner Brandl", email="admin@tc-isartal.de",
                 role=Role.ADMIN, password_hash=pw)
    members = [User(club_id=club.id, name=n, email=email_for(n, "tc-isartal.de"),
                    password_hash=pw) for n in MEMBERS]
    db.add_all(courts + [admin] + members)
    db.flush()

    # Vorbelegte Buchungen: vergangene Woche und kommende Tage, abends dichter.
    rng = random.Random(42)
    now = datetime.now(TZ)
    today = now.date()
    used = set()
    active = {m.id: 0 for m in members}
    for offset in range(-7, 7):
        day = today + timedelta(days=offset)
        for hour in range(8, 22):
            for court in courts:
                chance = 0.55 if hour >= 17 else 0.2
                if rng.random() > chance:
                    continue
                start = datetime(day.year, day.month, day.day, hour, tzinfo=TZ)
                # Lena (Demo-Account) bleibt für die Live-Demo ohne künftige Buchungen.
                candidates = [m for m in members
                              if start <= now or (active[m.id] < 2 and m is not members[0])]
                if not candidates or (court.id, start) in used:
                    continue
                member = rng.choice(candidates)
                used.add((court.id, start))
                if start > now:
                    active[member.id] += 1
                db.add(Booking(club_id=club.id, court_id=court.id, user_id=member.id,
                               start_at=start, end_at=start + timedelta(hours=1)))

    # Medenspiel-Sperre am nächsten Samstag auf Platz 1, 10–14 Uhr.
    saturday = today + timedelta(days=(5 - today.weekday()) % 7 or 7)
    sat_start = datetime(saturday.year, saturday.month, saturday.day, 10, tzinfo=TZ)
    for b in list(db.new):
        if isinstance(b, Booking) and b.court_id == courts[0].id and \
                sat_start <= b.start_at < sat_start + timedelta(hours=4):
            db.expunge(b)
    db.add(Block(club_id=club.id, court_id=courts[0].id, start_at=sat_start,
                 end_at=sat_start + timedelta(hours=4), reason="Medenspiel Herren 40",
                 created_by_id=admin.id))

    # Zweiter Verein für die Mandantentrennung (FA-14).
    other = Club(name="TC Seeblick")
    db.add(other)
    db.flush()
    db.add_all([
        Court(club_id=other.id, name="Center Court", sport=Sport.TENNIS, surface="Hartplatz"),
        Court(club_id=other.id, name="Platz 2", sport=Sport.TENNIS, surface="Sand"),
        User(club_id=other.id, name="Admin Seeblick", email="admin@tc-seeblick.de",
             role=Role.ADMIN, password_hash=pw),
    ])
    db.commit()
    print("Demo-Daten angelegt. Anmeldung: admin@tc-isartal.de oder "
          f"lena.hofmann@tc-isartal.de, Passwort {DEMO_PASSWORD}")


if __name__ == "__main__":
    seed(reset="--reset" in sys.argv)
