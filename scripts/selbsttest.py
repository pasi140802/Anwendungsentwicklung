"""Kurzer Selbsttest einer laufenden CourtSlot-Installation.

Prüft gegen die Demo-Daten: Gesundheitsprüfung, Anmeldung als Lena, Kalender für
morgen, Buchungsdialog, Buchung und „Meine Buchungen“. Braucht nur die
Python-Standardbibliothek, läuft also auch ohne virtuelle Umgebung.

Aufruf:  python -m scripts.selbsttest [URL]      (Standard: http://localhost:8000)
Ende mit „Selbsttest bestanden“ und Exit-Code 0, sonst mit der Stelle, an der es hakt.
"""

import html
import http.cookiejar
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000").rstrip("/")
EMAIL, PASSWORD = "lena.hofmann@tc-isartal.de", "demo-courtslot"

jar = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))


def _open(req: urllib.request.Request) -> str:
    try:
        with opener.open(req, timeout=15) as resp:
            return resp.read().decode("utf-8")
    except urllib.error.HTTPError as err:  # Fehlerseiten (z. B. 400 bei falschem Passwort)
        return err.read().decode("utf-8", "replace")


def get(path: str, htmx: bool = False) -> str:
    headers = {"HX-Request": "true"} if htmx else {}
    return _open(urllib.request.Request(BASE + path, headers=headers))


def post(path: str, data: dict) -> str:
    return _open(urllib.request.Request(BASE + path, data=urllib.parse.urlencode(data).encode()))


def csrf(page: str) -> str:
    m = re.search(r'name="csrf_token" value="([^"]+)"', page)
    if not m:
        fail("kein CSRF-Token auf der Seite gefunden")
    return m.group(1)


def fail(reason: str) -> None:
    print(f"FEHLER: {reason}")
    sys.exit(1)


def ok(text: str) -> None:
    print(f"  ok  {text}")


def main() -> None:
    print(f"Selbsttest gegen {BASE}")
    for _ in range(30):  # Anwendung braucht nach dem Start ein paar Sekunden
        try:
            if get("/health"):
                break
        except (urllib.error.URLError, ConnectionError):
            time.sleep(2)
    else:
        fail("Anwendung antwortet nicht. Läuft sie, und stimmt die Adresse?")
    ok("Anwendung erreichbar (/health)")

    page = post("/login", {"email": EMAIL, "password": PASSWORD, "csrf_token": csrf(get("/login"))})
    if "Abmelden" not in page and "logout" not in page:
        fail("Anmeldung als Lena fehlgeschlagen. Wurden die Demo-Daten geladen (scripts.seed)?")
    ok("Anmeldung als Lena")

    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    day = get(f"/kalender/tag?tag={tomorrow}")
    slots = re.findall(r'hx-get="(/buchen\?[^"]+)"', day)
    if not slots:
        fail(f"keine freie Startzeit am {tomorrow} gefunden")
    ok(f"Kalender für {tomorrow}: {len(slots)} freie Startzeiten")

    form = get(html.unescape(slots[len(slots) // 2]), htmx=True)
    fields = {k: v for k, v in re.findall(r'type="hidden" name="([^"]+)" value="([^"]*)"', form)}
    durations = re.findall(r'name="duration" value="(\d+)"[^>]*checked', form)
    if not {"csrf_token", "court_id", "start"} <= fields.keys() or not durations:
        fail("Buchungsdialog unvollständig")
    ok(f"Buchungsdialog für {html.unescape(fields['start'])[:16]} mit {durations[0]} Minuten")

    storno = re.compile(r'action="/buchungen/(\d+)/storno"')
    before = set(storno.findall(get("/meine-buchungen")))
    result = post("/buchungen", {**fields, "duration": durations[0]})
    mine = get("/meine-buchungen")
    new = set(storno.findall(mine)) - before
    if not new:
        hint = re.search(r'class="toast[^"]*".*?<span>([^<]+)</span>', result, re.S)
        fail("Buchung nicht angelegt" + (f": {hint.group(1).strip()}" if hint else ""))
    ok("Buchung angelegt und unter „Meine Buchungen“ sichtbar")

    booking_id = new.pop()  # aufräumen, damit der Test beliebig oft laufen kann
    post(f"/buchungen/{booking_id}/storno", {"csrf_token": csrf(mine), "back": "/meine-buchungen"})
    if booking_id in storno.findall(get("/meine-buchungen")):
        fail("Stornierung der Testbuchung fehlgeschlagen")
    ok("Testbuchung wieder storniert")
    print("Selbsttest bestanden")


if __name__ == "__main__":
    main()
