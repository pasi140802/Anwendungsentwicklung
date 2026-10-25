"""Zentrale Konfiguration aus Umgebungsvariablen (siehe .env.example)."""

import os
from zoneinfo import ZoneInfo

DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql+psycopg://courtslot:courtslot@localhost:5432/courtslot"
)
DEV_SECRET_KEY = "dev-only-change-me"
SECRET_KEY = os.getenv("SECRET_KEY", DEV_SECRET_KEY)
# Im Zielbetrieb laufen Cookies nur über HTTPS (NFA-04).
SECURE_COOKIES = os.getenv("SECURE_COOKIES", "false").lower() == "true"

if SECURE_COOKIES and (SECRET_KEY == DEV_SECRET_KEY or len(SECRET_KEY) < 32):
    # Produktion (HTTPS) startet nur mit einem eigenen, langen Schlüssel.
    raise RuntimeError("SECRET_KEY muss im Zielbetrieb gesetzt sein (mind. 32 Zeichen).")

# Öffentliche Adresse für Links in E-Mails
BASE_URL = os.getenv("BASE_URL", "http://localhost:8000").rstrip("/")

# Mailversand. Ohne SMTP_HOST werden Mails nur protokolliert (Entwicklung, Tests).
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_STARTTLS = os.getenv("SMTP_STARTTLS", "true").lower() == "true"
MAIL_FROM = os.getenv("MAIL_FROM", "CourtSlot <noreply@courtslot.local>")

# Angaben für Impressum und Datenschutzerklärung
OPERATOR_NAME = os.getenv("OPERATOR_NAME", "[Name des Betreibers]")
OPERATOR_ADDRESS = os.getenv("OPERATOR_ADDRESS", "[Straße, PLZ Ort]")
OPERATOR_EMAIL = os.getenv("OPERATOR_EMAIL", "[kontakt@example.de]")

TZ = ZoneInfo("Europe/Berlin")
PASSWORD_MIN_LENGTH = 10
