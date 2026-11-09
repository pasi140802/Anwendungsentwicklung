# CourtSlot – Installationsanleitung

Zwei Wege für Windows, macOS und Linux. Variante A ist der kürzere.

## Variante A: mit Docker (empfohlen)

1. Docker Desktop installieren und starten: <https://www.docker.com/products/docker-desktop/>
2. ZIP entpacken, im Terminal in den Ordner `CourtSlot` wechseln.
3. `docker compose up --build` ausführen. Der erste Start lädt Abhängigkeiten und dauert 2–4 Minuten.
4. Browser öffnen: <http://localhost:8000>
5. Mails (z. B. Bestätigungslinks bei der Registrierung) erscheinen unter <http://localhost:8025>.
6. Beenden: `Strg+C`, Datenbank zurücksetzen: `docker compose down -v`

## Variante B: ohne Docker

1. Python 3.12 oder 3.13 installieren: <https://www.python.org/downloads/> (Windows: Haken bei „Add python.exe to PATH“ setzen).
2. PostgreSQL 16 installieren: <https://www.postgresql.org/download/> (Windows: Installer von EDB; das Passwort für den Benutzer `postgres` merken).
3. Datenbank anlegen:
   `psql -U postgres -c "CREATE DATABASE courtslot"`
   (Windows: `psql` liegt unter `C:\Program Files\PostgreSQL\16\bin\`)
4. ZIP entpacken, im Terminal in den Ordner `CourtSlot` wechseln.
5. Virtuelle Umgebung anlegen und Pakete installieren:
   - macOS/Linux: `python3 -m venv .venv` und `source .venv/bin/activate`
   - Windows (PowerShell): `py -m venv .venv` und `.venv\Scripts\Activate.ps1`
   - danach: `pip install -r requirements.txt`
6. Verbindung zur Datenbank setzen (`PASSWORT` ersetzen):
   - macOS/Linux: `export DATABASE_URL=postgresql+psycopg://postgres:PASSWORT@localhost:5432/courtslot`
   - Windows (PowerShell): `$env:DATABASE_URL="postgresql+psycopg://postgres:PASSWORT@localhost:5432/courtslot"`
7. Datenbankschema und Demo-Daten anlegen: `python -m scripts.seed`
8. Anwendung starten: `python -m uvicorn app.main:app --port 8000`
9. Browser öffnen: <http://localhost:8000>
10. Mails werden ohne Mailserver im Terminal ausgegeben (Bestätigungslink von dort kopieren).

## Anmelden

| Rolle | E-Mail | Passwort |
| --- | --- | --- |
| Verwaltung TC Isartal | admin@tc-isartal.de | demo-courtslot |
| Mitglied (in zwei Vereinen) | lena.hofmann@tc-isartal.de | demo-courtslot |
| Verwaltung TC Seeblick | admin@tc-seeblick.de | demo-courtslot |

Beitrittscode für ein selbst registriertes Konto: `ISAR2026` (Freigabe danach als Verwaltung unter „Mitglieder“).

## Vorschlag zum Ausprobieren

1. Als Lena anmelden, im Kalender eine Padel-Startzeit ab 17 Uhr anklicken, 90 Minuten und Schläger wählen, buchen.
2. Zwei weitere Buchungen versuchen: Die Regel „höchstens 2 aktive Buchungen“ greift.
3. Als Verwaltung unter „Sperren“ eine gebuchte Zeit sperren: Die betroffene Buchung wird angezeigt und erst nach Bestätigung storniert.
4. Unter „Verwaltung“ Plätze, Preise, Leihartikel, Öffnungszeiten und Auslastung ansehen.
5. Abmelden, „Jetzt registrieren“, Bestätigungslink öffnen, mit dem Beitrittscode beitreten.

## Tests (optional, Variante B)

1. Zweite Datenbank anlegen: `psql -U postgres -c "CREATE DATABASE courtslot_test"`
2. `pip install -r requirements-dev.txt`
3. `DATABASE_URL` auf `.../courtslot_test` setzen (die Tests löschen den Inhalt dieser Datenbank und laufen nur gegen einen Namen mit Endung `_test`).
4. `pytest`
