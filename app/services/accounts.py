"""Konten: Registrierung, E-Mail-Bestätigung, Passwort, Datenexport, Löschung.

Dazu Vereine: neu registrieren, per Code beitreten, Einladung annehmen, verlassen.
Fehler werden als AccountError mit verständlicher Meldung ausgelöst.
"""

import re
import secrets
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app import tokens
from app.models import (
    Booking,
    BookingStatus,
    Club,
    ClubKind,
    Invitation,
    Membership,
    MembershipStatus,
    Role,
    User,
)
from app.security import hash_password, password_problem, verify_password
from app.services.admin import cancel_future_bookings, default_hours, new_join_code
from app.services.booking import now_local

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class AccountError(Exception):
    pass


def normalize_email(email: str) -> str:
    email = (email or "").strip().lower()
    if not EMAIL_RE.match(email) or len(email) > 254:
        raise AccountError("Bitte eine gültige E-Mail-Adresse angeben.")
    return email


def find_user(db: Session, email: str) -> User | None:
    return db.scalars(select(User).where(User.email == email)).first()


# --- Registrierung und Bestätigung ------------------------------------------------

def register(db: Session, name: str, email: str, password: str,
             verified: bool = False) -> tuple[User | None, User | None]:
    """Legt ein unbestätigtes Konto an.

    Rückgabe (neues_konto, bestehendes_konto): Ist die Adresse schon vergeben,
    wird kein Fehler angezeigt (sonst ließen sich Adressen ausspähen); stattdessen
    bekommt die Adresse eine Hinweis-Mail.
    """
    name = (name or "").strip()
    if not 2 <= len(name) <= 120:
        raise AccountError("Bitte deinen Namen angeben.")
    email = normalize_email(email)
    problem = password_problem(password, email, name)
    if problem:
        raise AccountError(problem)
    existing = find_user(db, email)
    if existing is not None:
        return None, existing
    user = User(name=name, email=email, password_hash=hash_password(password),
                email_verified_at=now_local() if verified else None)
    db.add(user)
    try:
        db.commit()
    except IntegrityError:  # gleichzeitige Registrierung derselben Adresse
        db.rollback()
        return None, find_user(db, email)
    return user, None


def verify_token(user: User) -> str:
    return tokens.make("verify-email", {"uid": user.id, "email": user.email})


def confirm_email(db: Session, token: str) -> User:
    try:
        data = tokens.read("verify-email", token, tokens.VERIFY_MAX_AGE)
    except tokens.TokenError as exc:
        raise AccountError("Der Bestätigungslink ist abgelaufen. Fordere einfach einen neuen an."
                           if exc.expired else "Der Bestätigungslink ist ungültig.") from None
    user = db.get(User, data.get("uid"))
    if user is None or user.is_deleted or user.email != data.get("email"):
        raise AccountError("Der Bestätigungslink ist ungültig.")
    if user.email_verified_at is None:
        user.email_verified_at = now_local()
        db.commit()
    return user


# --- Anmeldung ----------------------------------------------------------------------

DUMMY_HASH = hash_password("kein-benutzer-vorhanden")


def authenticate(db: Session, email: str, password: str) -> User | None:
    """Gleiche Rechenzeit für unbekannte und bekannte Adressen (kein Ausspähen)."""
    user = find_user(db, (email or "").strip().lower())
    ok = verify_password(user.password_hash if user else DUMMY_HASH, password)
    if user is None or not ok or not user.is_active or user.is_deleted:
        return None
    return user


# --- Passwort ----------------------------------------------------------------------

def reset_token(user: User) -> str:
    return tokens.make("reset-password",
                       {"uid": user.id, "fp": tokens.password_fingerprint(user.password_hash)})


def user_for_reset(db: Session, token: str) -> User:
    try:
        data = tokens.read("reset-password", token, tokens.RESET_MAX_AGE)
    except tokens.TokenError as exc:
        raise AccountError("Der Link ist abgelaufen. Fordere bitte einen neuen an."
                           if exc.expired else "Der Link ist ungültig.") from None
    user = db.get(User, data.get("uid"))
    if (user is None or user.is_deleted
            or tokens.password_fingerprint(user.password_hash) != data.get("fp")):
        raise AccountError("Der Link wurde bereits benutzt oder ist ungültig.")
    return user


def set_password(db: Session, user: User, password: str) -> None:
    problem = password_problem(password, user.email, user.name)
    if problem:
        raise AccountError(problem)
    user.password_hash = hash_password(password)
    user.session_version += 1  # alle Sitzungen beenden
    if user.email_verified_at is None:  # Link kam per Mail an diese Adresse
        user.email_verified_at = now_local()
    db.commit()


def change_password(db: Session, user: User, current: str, new: str) -> None:
    if not verify_password(user.password_hash, current):
        raise AccountError("Das aktuelle Passwort ist falsch.")
    set_password(db, user, new)


def rename(db: Session, user: User, name: str) -> None:
    name = (name or "").strip()
    if not 2 <= len(name) <= 120:
        raise AccountError("Bitte deinen Namen angeben.")
    user.name = name
    db.commit()


# --- Datenschutz: Export und Löschung (DSGVO Art. 17 und 20) ---------------------

def export_data(db: Session, user: User) -> dict:
    memberships = db.scalars(select(Membership).where(Membership.user_id == user.id)
                             .options(selectinload(Membership.club))).all()
    bookings = db.scalars(select(Booking).where(Booking.user_id == user.id)
                          .options(selectinload(Booking.court), selectinload(Booking.items))
                          .order_by(Booking.start_at)).all()
    return {
        "exportiert_am": now_local().isoformat(),
        "konto": {"name": user.name, "email": user.email,
                  "erstellt_am": user.created_at.isoformat() if user.created_at else None,
                  "email_bestaetigt_am": user.email_verified_at.isoformat()
                  if user.email_verified_at else None},
        "mitgliedschaften": [{"verein": m.club.name, "rolle": m.role.value,
                              "status": m.status.value} for m in memberships],
        "buchungen": [{"verein_id": b.club_id, "platz": b.court.name,
                       "beginn": b.start_at.isoformat(), "ende": b.end_at.isoformat(),
                       "status": b.status.value, "preis_cent": b.price_cents,
                       "leihe": [{"artikel": i.name, "anzahl": i.quantity,
                                  "preis_cent": i.price_cents} for i in b.items]}
                      for b in bookings],
    }


def delete_account(db: Session, user: User, password: str, now: datetime | None = None) -> None:
    """Löscht das Konto: Mitgliedschaften weg, kommende Buchungen storniert,
    personenbezogene Daten überschrieben. Vergangene Buchungen bleiben anonym
    für die Auslastungsstatistik erhalten."""
    now = now or now_local()
    if not verify_password(user.password_hash, password):
        raise AccountError("Das Passwort ist falsch.")
    for m in db.scalars(select(Membership).where(Membership.user_id == user.id)).all():
        if m.is_admin:
            admins = db.scalar(select(func.count(Membership.id)).where(
                Membership.club_id == m.club_id, Membership.role == Role.ADMIN,
                Membership.status == MembershipStatus.ACTIVE))
            members = db.scalar(select(func.count(Membership.id)).where(
                Membership.club_id == m.club_id))
            if admins <= 1 and members > 1:
                raise AccountError(f"Du bist die einzige Person in der Verwaltung von "
                                   f"„{m.club.name}“. Übertrage die Rolle zuerst an "
                                   "jemand anderen.")
    for m in db.scalars(select(Membership).where(Membership.user_id == user.id)).all():
        cancel_future_bookings(db, user.id, m.club_id, user.id, now)
        db.delete(m)
    user.name = "Gelöschtes Konto"
    user.email = f"geloescht-{user.id}-{secrets.token_hex(4)}@invalid.local"
    user.password_hash = hash_password(secrets.token_urlsafe(32))
    user.is_active = False
    user.is_deleted = True
    user.session_version += 1
    db.commit()


# --- Vereine: registrieren, beitreten, verlassen ----------------------------------

def create_club(db: Session, user: User, form: dict) -> Club:
    name = (form.get("name") or "").strip()
    if not 3 <= len(name) <= 120:
        raise AccountError("Bitte den Namen des Vereins oder der Anlage angeben.")
    try:
        kind = ClubKind(form.get("kind", "club"))
    except ValueError:
        raise AccountError("Bitte die Art auswählen.") from None
    city = (form.get("city") or "").strip()
    if not city:
        raise AccountError("Bitte den Ort angeben.")
    club = Club(name=name, kind=kind, street=(form.get("street") or "").strip()[:120],
                zip_code=(form.get("zip_code") or "").strip()[:10], city=city[:80],
                contact_email=user.email, join_code=new_join_code())
    club.hours = default_hours()
    db.add(club)
    db.flush()
    db.add(Membership(user_id=user.id, club_id=club.id, role=Role.ADMIN,
                      status=MembershipStatus.ACTIVE))
    db.commit()
    return club


def join_with_code(db: Session, user: User, code: str) -> Membership:
    code = (code or "").strip().upper().replace(" ", "")
    club = db.scalars(select(Club).where(Club.join_code == code)).first()
    if club is None:
        raise AccountError("Zu diesem Code gibt es keinen Verein. Bitte prüfe die Schreibweise.")
    existing = db.scalars(select(Membership).where(
        Membership.user_id == user.id, Membership.club_id == club.id)).first()
    if existing is not None:
        if existing.status == MembershipStatus.LOCKED:
            raise AccountError("Deine Mitgliedschaft in diesem Verein ist gesperrt.")
        return existing
    m = Membership(user_id=user.id, club_id=club.id, role=Role.MEMBER,
                   status=MembershipStatus.PENDING)
    db.add(m)
    db.commit()
    return m


def invitation_token(inv: Invitation) -> str:
    return tokens.make("invite", {"iid": inv.id})


def invitation_from_token(db: Session, token: str) -> Invitation:
    try:
        data = tokens.read("invite", token, tokens.INVITE_MAX_AGE)
    except tokens.TokenError as exc:
        raise AccountError("Die Einladung ist abgelaufen. Bitte den Verein um eine neue."
                           if exc.expired else "Die Einladung ist ungültig.") from None
    inv = db.get(Invitation, data.get("iid"))
    if inv is None or inv.revoked or inv.accepted_at is not None:
        raise AccountError("Die Einladung wurde bereits verwendet oder zurückgezogen.")
    return inv


def accept_invitation(db: Session, user: User, inv: Invitation) -> Membership:
    """Nimmt die Einladung an. Die Mailadresse muss zum Konto passen."""
    if user.email != inv.email:
        raise AccountError(f"Diese Einladung gilt für {inv.email}. Melde dich mit dieser "
                           "Adresse an oder registriere dich damit.")
    m = db.scalars(select(Membership).where(
        Membership.user_id == user.id, Membership.club_id == inv.club_id)).first()
    if m is None:
        m = Membership(user_id=user.id, club_id=inv.club_id, role=inv.role,
                       status=MembershipStatus.ACTIVE)
        db.add(m)
    elif m.status == MembershipStatus.PENDING:
        m.status = MembershipStatus.ACTIVE
        m.role = inv.role
    inv.accepted_at = now_local()
    if user.email_verified_at is None:  # Link kam per Mail an diese Adresse
        user.email_verified_at = now_local()
    db.commit()
    return m


def leave_club(db: Session, user: User, club_id: int, now: datetime | None = None) -> None:
    now = now or now_local()
    m = db.scalars(select(Membership).where(
        Membership.user_id == user.id, Membership.club_id == club_id)).first()
    if m is None:
        raise AccountError("Du bist kein Mitglied dieses Vereins.")
    if m.is_admin:
        admins = db.scalar(select(func.count(Membership.id)).where(
            Membership.club_id == club_id, Membership.role == Role.ADMIN,
            Membership.status == MembershipStatus.ACTIVE))
        if admins <= 1:
            raise AccountError("Du bist die einzige Person in der Verwaltung. "
                               "Übertrage die Rolle zuerst an jemand anderen.")
    cancel_future_bookings(db, user.id, club_id, user.id, now)
    db.delete(m)
    db.commit()


def all_memberships(db: Session, user: User) -> list[Membership]:
    return db.scalars(select(Membership).where(Membership.user_id == user.id)
                      .options(selectinload(Membership.club))
                      .order_by(Membership.created_at)).all()


def upcoming_count(db: Session, user: User, now: datetime | None = None) -> int:
    now = now or now_local()
    return db.scalar(select(func.count(Booking.id)).where(
        Booking.user_id == user.id, Booking.status == BookingStatus.CONFIRMED,
        Booking.start_at > now)) or 0
