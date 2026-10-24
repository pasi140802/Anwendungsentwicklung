"""Zentrale Konfiguration aus Umgebungsvariablen."""

import os
from zoneinfo import ZoneInfo

DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql+psycopg://courtslot:courtslot@localhost:5432/courtslot"
)
SECRET_KEY = os.getenv("SECRET_KEY", "dev-only-change-me")
# Im Zielbetrieb laufen Cookies nur über HTTPS (NFA-04).
SECURE_COOKIES = os.getenv("SECURE_COOKIES", "false").lower() == "true"

TZ = ZoneInfo("Europe/Berlin")
SLOT_MINUTES = 60
