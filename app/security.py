"""Passwörter, Sitzung, CSRF-Schutz und Rechteprüfung (NFA-04 bis NFA-06)."""

import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.config import PASSWORD_MIN_LENGTH
from app.db import get_db
from app.models import Membership, MembershipStatus, User

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def password_problem(password: str, email: str = "", name: str = "") -> str | None:
    """Prüft die Passwortregeln; gibt eine Meldung zurück oder None."""
    if len(password) < PASSWORD_MIN_LENGTH:
        return f"Das Passwort muss mindestens {PASSWORD_MIN_LENGTH} Zeichen lang sein."
    lowered = password.lower()
    if email and lowered == email.lower():
        return "Das Passwort darf nicht deine E-Mail-Adresse sein."
    if name and lowered == name.lower():
        return "Das Passwort darf nicht dein Name sein."
    if len(set(password)) < 4:
        return "Das Passwort ist zu einfach."
    return None


# --- CSRF -------------------------------------------------------------------

def csrf_token(request: Request) -> str:
    token = request.session.get("csrf")
    if not token:
        token = secrets.token_urlsafe(32)
        request.session["csrf"] = token
    return token


async def verify_csrf(request: Request) -> None:
    """Jede schreibende Anfrage muss das Sitzungs-Token mitsenden."""
    expected = request.session.get("csrf")
    sent = request.headers.get("X-CSRF-Token")
    if sent is None:
        form = await request.form()
        sent = form.get("csrf_token")
    if not expected or not sent or not secrets.compare_digest(str(sent), expected):
        raise HTTPException(status_code=403, detail="Ungültiges Sicherheits-Token")


# --- Anmeldung, Mitgliedschaft und Rollen ----------------------------------------

class LoginRequired(Exception):
    """Wird in eine Weiterleitung zur Anmeldeseite übersetzt."""


class ClubRequired(Exception):
    """Konto ohne aktive Mitgliedschaft: Weiterleitung zum Einstieg."""


def start_session(request: Request, user: User, club_id: int | None = None) -> None:
    csrf = request.session.get("csrf")
    request.session.clear()
    request.session["user_id"] = user.id
    request.session["sv"] = user.session_version
    if club_id:
        request.session["club_id"] = club_id
    if csrf:
        request.session["csrf"] = csrf


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    user_id = request.session.get("user_id")
    if user_id is None:
        raise LoginRequired
    user = db.get(User, user_id)
    if (user is None or not user.is_active or user.is_deleted or not user.is_verified
            or request.session.get("sv") != user.session_version):
        request.session.clear()
        raise LoginRequired
    request.state.user = user
    return user


def active_memberships(db: Session, user: User) -> list[Membership]:
    return db.scalars(
        select(Membership)
        .where(Membership.user_id == user.id, Membership.status == MembershipStatus.ACTIVE)
        .options(selectinload(Membership.club))  # Vereinsname auch nach Sitzungsende lesbar
        .order_by(Membership.created_at)
    ).all()


def get_current_member(request: Request, db: Session = Depends(get_db),
                       user: User = Depends(get_current_user)) -> Membership:
    """Aktive Mitgliedschaft im gewählten Verein (Sitzung) oder die erste aktive."""
    memberships = active_memberships(db, user)
    request.state.memberships = memberships
    if not memberships:
        raise ClubRequired
    wanted = request.session.get("club_id")
    member = next((m for m in memberships if m.club_id == wanted), memberships[0])
    request.session["club_id"] = member.club_id
    request.state.member = member
    return member


def require_admin(request: Request, db: Session = Depends(get_db),
                  member: Membership = Depends(get_current_member)) -> Membership:
    if not member.is_admin:
        raise HTTPException(status_code=403, detail="Nur für die Vereinsverwaltung")
    # Offene Beitrittsanfragen als Zähler in der Verwaltungsnavigation
    request.state.pending_count = db.scalar(select(func.count(Membership.id)).where(
        Membership.club_id == member.club_id, Membership.status == MembershipStatus.PENDING)) or 0
    return member
