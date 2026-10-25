"""Einfache Begrenzung von Anmelde- und Registrierungsversuchen.

Gezählt wird je Prozess im Arbeitsspeicher (gleitendes Zeitfenster). Das schützt
vor automatisiertem Passwortraten; im Zielbetrieb begrenzt zusätzlich der
Reverse Proxy die Anfragen pro IP-Adresse.
"""

import time
from collections import defaultdict, deque
from threading import Lock


class RateLimiter:
    def __init__(self, limit: int, window_seconds: int):
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def hit(self, key: str) -> bool:
        """Zählt einen Versuch. False, wenn das Limit überschritten ist."""
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and q[0] <= now - self.window:
                q.popleft()
            if len(q) >= self.limit:
                return False
            q.append(now)
            return True

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


# 10 Anmeldeversuche je E-Mail-Adresse und 30 je IP-Adresse in 15 Minuten
login_by_email = RateLimiter(10, 15 * 60)
login_by_ip = RateLimiter(30, 15 * 60)
# 5 Mails (Registrierung, Passwort vergessen, erneut senden) je IP in 15 Minuten
mail_by_ip = RateLimiter(5, 15 * 60)

ALL = (login_by_email, login_by_ip, mail_by_ip)


def client_ip(request) -> str:
    return request.client.host if request.client else "unbekannt"
