"""Signierte, zeitlich begrenzte Links für E-Mail-Bestätigung, Passwort und Einladungen."""

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.config import SECRET_KEY

VERIFY_MAX_AGE = 24 * 3600
RESET_MAX_AGE = 3600
INVITE_MAX_AGE = 7 * 24 * 3600

_serializer = URLSafeTimedSerializer(SECRET_KEY)


class TokenError(Exception):
    def __init__(self, expired: bool):
        super().__init__("abgelaufen" if expired else "ungültig")
        self.expired = expired


def make(purpose: str, data: dict) -> str:
    return _serializer.dumps(data, salt=purpose)


def read(purpose: str, token: str, max_age: int) -> dict:
    try:
        return _serializer.loads(token, salt=purpose, max_age=max_age)
    except SignatureExpired:
        raise TokenError(expired=True) from None
    except BadSignature:
        raise TokenError(expired=False) from None


def password_fingerprint(password_hash: str) -> str:
    """Ändert sich mit jedem neuen Passwort: Reset-Links sind nur einmal nutzbar."""
    return password_hash[-16:]
