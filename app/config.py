"""Zentrale Konfiguration aus Umgebungsvariablen."""

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

TZ = ZoneInfo("Europe/Berlin")
SLOT_MINUTES = 60
