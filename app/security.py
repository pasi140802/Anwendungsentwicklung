"""Passwörter, Sitzung, CSRF-Schutz und Rechteprüfung (NFA-04 bis NFA-06)."""

import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def generate_start_password() -> str:
    """Startpasswort für neue Mitglieder (US-02)."""
    return secrets.token_urlsafe(9)


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


# --- Anmeldung und Rollen ----------------------------------------------------

class LoginRequired(Exception):
    """Wird in eine Weiterleitung zur Anmeldeseite übersetzt."""


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    user_id = request.session.get("user_id")
    if user_id is None:
        raise LoginRequired
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        request.session.clear()
        raise LoginRequired
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Nur für Admins")
    return user
