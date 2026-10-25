"""Tägliche Wartung (läuft im Zielbetrieb als eigener Dienst, siehe docker-compose.prod.yml).

- Löscht Konten, deren E-Mail-Adresse nach 7 Tagen nicht bestätigt wurde.
- Löscht Buchungen 12 Monate nach dem Spieltermin (NFA-07, Datensparsamkeit).

Beides ist so in der Datenschutzerklärung zugesagt.

Aufruf:  python -m scripts.maintenance
"""

from datetime import timedelta

from sqlalchemy import delete, select

from app.db import SessionLocal
from app.models import Booking, Membership, User
from app.services.booking import now_local

UNVERIFIED_DAYS = 7
BOOKING_RETENTION_DAYS = 365


def purge_unverified(db, now=None) -> int:
    now = now or now_local()
    cutoff = now - timedelta(days=UNVERIFIED_DAYS)
    ids = db.scalars(select(User.id).where(
        User.email_verified_at.is_(None), User.created_at < cutoff)).all()
    if ids:
        db.execute(delete(Membership).where(Membership.user_id.in_(ids)))
        db.execute(delete(User).where(User.id.in_(ids)))
        db.commit()
    return len(ids)


def purge_old_bookings(db, now=None) -> int:
    now = now or now_local()
    cutoff = now - timedelta(days=BOOKING_RETENTION_DAYS)
    result = db.execute(delete(Booking).where(Booking.end_at < cutoff))
    db.commit()
    return result.rowcount


def main() -> None:
    with SessionLocal() as db:
        print(f"Unbestätigte Konten gelöscht: {purge_unverified(db)}")
        print(f"Buchungen älter als 12 Monate gelöscht: {purge_old_bookings(db)}")


if __name__ == "__main__":
    main()
