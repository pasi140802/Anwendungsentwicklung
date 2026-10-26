"""Demo-Daten laden (TS-03).

TC Isartal mit Tennis- und Padelplätzen, 20 Mitgliedern, Buchungen der letzten und
kommenden Woche, einer Beitrittsanfrage und einer offenen Einladung. Dazu der TC
Seeblick, in dem Lena ebenfalls Mitglied ist (mehrere Vereine, Mandantentrennung).

Aufruf:  python -m scripts.seed           (bringt das Schema auf Stand, legt Daten nur
                                           an, wenn die Datenbank leer ist)
         python -m scripts.seed --reset   (löscht alles und legt neu an)
"""

import random
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import select

from app.config import TZ
from app.db import SessionLocal
from app.models import (
    Block,
    Booking,
    Club,
    ClubKind,
    Court,
    Invitation,
    Membership,
    MembershipStatus,
    OpeningHours,
    RentalItem,
    Role,
    Season,
    Sport,
    User,
)
from app.security import hash_password
from app.services.booking import (
    court_in_season,
    court_price,
    day_bounds,
    durations_of,
    hours_for,
)

DEMO_PASSWORD = "demo-courtslot"
ALEMBIC_INI = Path(__file__).resolve().parent.parent / "alembic.ini"

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


def migrate(reset: bool) -> None:
    cfg = Config(str(ALEMBIC_INI))
    if reset:
        command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")


def hours(weekday: tuple[int, int], weekend: tuple[int, int]) -> list[OpeningHours]:
    result = []
    for d in range(7):
        opens, closes = weekend if d >= 5 else weekday
        result.append(OpeningHours(weekday=d, opens=opens * 60, closes=closes * 60))
    return result


def fill_bookings(db, club: Club, courts: list[Court], members: list[User], keep_free: User,
                  now: datetime, rng: random.Random) -> None:
    """Belegt vergangene und kommende Zeiten, abends dichter. Höchstens 2 aktive je Person."""
    active = {m.id: 0 for m in members}
    for offset in range(-7, 8):
        day = now.date() + timedelta(days=offset)
        hours = hours_for(club, day)
        if hours is None:
            continue
        day_open, day_close = day_bounds(day, hours)
        for court in courts:
            if not court.is_active or not court_in_season(club, court, day):
                continue
            t = day_open
            while t + timedelta(minutes=durations_of(court)[0]) <= day_close:
                evening = t.hour >= 17
                if rng.random() > (0.55 if evening else 0.2):
                    t += timedelta(minutes=30 if rng.random() < 0.5 else 60)
                    continue
                fitting = [d for d in durations_of(court)
                           if t + timedelta(minutes=d) <= day_close]
                minutes = rng.choice(fitting)
                future = t > now
                candidates = [m for m in members
                              if not future or (active[m.id] < 2 and m is not keep_free)]
                if not candidates:
                    break
                member = rng.choice(candidates)
                if future:
                    active[member.id] += 1
                cents = court_price(club, court, t, minutes)
                db.add(Booking(club_id=club.id, court_id=court.id, user_id=member.id,
                               start_at=t, end_at=t + timedelta(minutes=minutes),
                               court_price_cents=cents, price_cents=cents))
                t += timedelta(minutes=minutes)


def rental_items(club: Club) -> list[RentalItem]:
    return [
        RentalItem(club_id=club.id, name="Padelschläger", sport=Sport.PADEL, price_cents=400,
                   max_per_booking=4),
        RentalItem(club_id=club.id, name="Dose Padelbälle", sport=Sport.PADEL, price_cents=700,
                   max_per_booking=2),
        RentalItem(club_id=club.id, name="Tennisschläger", sport=Sport.TENNIS, price_cents=500,
                   max_per_booking=4),
        RentalItem(club_id=club.id, name="Dose Tennisbälle", sport=Sport.TENNIS,
                   price_cents=600, max_per_booking=2),
    ]


def seed(reset: bool = False) -> None:
    migrate(reset)
    db = SessionLocal()
    if db.scalar(select(Club.id)) is not None:
        print("Datenbank enthält bereits Daten, nichts geändert (--reset zum Neuanlegen).")
        return

    pw = hash_password(DEMO_PASSWORD)
    now = datetime.now(TZ)
    rng = random.Random(42)

    def user(name: str, email: str) -> User:
        return User(name=name, email=email, password_hash=pw, email_verified_at=now)

    # --- TC Isartal --------------------------------------------------------------
    club = Club(name="TC Isartal", kind=ClubKind.CLUB, street="Isarauen 12", zip_code="81547",
                city="München", contact_email="vorstand@tc-isartal.de", join_code="ISAR2026",
                max_active_bookings=2, max_days_ahead=7, cancel_hours=2,
                summer_start=date(2000, 4, 15), summer_end=date(2000, 10, 15),
                prime_from=17 * 60, prime_to=21 * 60)
    club.hours = hours(weekday=(7, 22), weekend=(8, 21))
    db.add(club)
    db.flush()
    courts = [
        # Sandplätze im Sommer im Mitgliedsbeitrag enthalten
        Court(club_id=club.id, name="Platz 1", sport=Sport.TENNIS, surface="Sand",
              has_floodlight=True, season=Season.SUMMER, durations=[60, 90]),
        Court(club_id=club.id, name="Platz 2", sport=Sport.TENNIS, surface="Sand",
              season=Season.SUMMER, durations=[60, 90]),
        # Preise pro Stunde; Padel in der Hauptzeit: 90 Minuten = 66 €
        Court(club_id=club.id, name="Halle", sport=Sport.TENNIS, surface="Teppich",
              is_indoor=True, durations=[60, 90], hourly_price_cents=2600,
              prime_hourly_price_cents=3200),
        Court(club_id=club.id, name="Padel 1", sport=Sport.PADEL, surface="Kunstrasen",
              has_floodlight=True, durations=[60, 90], hourly_price_cents=3600,
              prime_hourly_price_cents=4400),
        Court(club_id=club.id, name="Padel 2", sport=Sport.PADEL, surface="Kunstrasen",
              is_indoor=True, durations=[60, 90], hourly_price_cents=3600,
              prime_hourly_price_cents=4400),
    ]
    admin = user("Werner Brandl", "admin@tc-isartal.de")
    members = [user(n, email_for(n, "tc-isartal.de")) for n in MEMBERS]
    applicant = user("Niklas Vogt", "niklas.vogt@example.de")
    db.add_all(courts + [admin, applicant] + members)
    db.flush()
    db.add(Membership(user_id=admin.id, club_id=club.id, role=Role.ADMIN,
                      status=MembershipStatus.ACTIVE))
    db.add_all(Membership(user_id=m.id, club_id=club.id, role=Role.MEMBER,
                          status=MembershipStatus.ACTIVE) for m in members)
    db.add(Membership(user_id=applicant.id, club_id=club.id, role=Role.MEMBER,
                      status=MembershipStatus.PENDING))
    db.add(Invitation(club_id=club.id, email="clara.neumann@example.de", role=Role.MEMBER,
                      invited_by_id=admin.id))
    db.add_all(rental_items(club))

    # Medenspiel am nächsten Samstag in der Halle, 10 bis 14 Uhr
    saturday = now.date() + timedelta(days=(5 - now.weekday()) % 7 or 7)
    block_start = datetime(saturday.year, saturday.month, saturday.day, 10, tzinfo=TZ)
    block = Block(club_id=club.id, court_id=courts[2].id, start_at=block_start,
                  end_at=block_start + timedelta(hours=4), reason="Medenspiel Herren 40",
                  created_by_id=admin.id)
    db.add(block)
    db.flush()
    fill_bookings(db, club, courts, members, keep_free=members[0], now=now, rng=rng)
    for b in list(db.new):  # keine Buchungen in der Sperre
        if isinstance(b, Booking) and b.court_id == block.court_id and \
                b.start_at < block.end_at and b.end_at > block.start_at:
            db.expunge(b)

    # --- TC Seeblick: zweiter Verein, Lena ist auch dort Mitglied --------------------
    other = Club(name="TC Seeblick", kind=ClubKind.CLUB, street="Uferweg 3", zip_code="82319",
                 city="Starnberg", contact_email="info@tc-seeblick.de", join_code="SEEBLICK",
                 summer_start=date(2000, 4, 15), summer_end=date(2000, 10, 15))
    other.hours = hours(weekday=(8, 22), weekend=(8, 20))
    db.add(other)
    db.flush()
    other_courts = [
        Court(club_id=other.id, name="Center Court", sport=Sport.TENNIS, surface="Hartplatz",
              is_indoor=True, durations=[60, 90], hourly_price_cents=2800),
        Court(club_id=other.id, name="Traglufthalle", sport=Sport.TENNIS, surface="Granulat",
              is_indoor=True, durations=[60, 90], hourly_price_cents=2400),
    ]
    other_admin = user("Admin Seeblick", "admin@tc-seeblick.de")
    other_members = [user(n, email_for(n, "tc-seeblick.de"))
                     for n in ("Moritz Graf", "Elena Roth", "Jan Kaiser", "Nina Vogel")]
    db.add_all(other_courts + [other_admin] + other_members)
    db.flush()
    db.add(Membership(user_id=other_admin.id, club_id=other.id, role=Role.ADMIN,
                      status=MembershipStatus.ACTIVE))
    db.add_all(Membership(user_id=u.id, club_id=other.id, role=Role.MEMBER,
                          status=MembershipStatus.ACTIVE) for u in other_members + [members[0]])
    fill_bookings(db, other, other_courts, other_members, keep_free=members[0], now=now, rng=rng)

    db.commit()
    print("Demo-Daten angelegt. Anmeldung mit admin@tc-isartal.de oder "
          f"lena.hofmann@tc-isartal.de, Passwort {DEMO_PASSWORD}")


if __name__ == "__main__":
    seed(reset="--reset" in sys.argv)
