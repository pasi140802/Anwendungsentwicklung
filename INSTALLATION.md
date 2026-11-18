# CourtSlot – Installationsanleitung

CourtSlot läuft lokal unter Windows, macOS und Linux. Es gibt zwei Wege:

| Weg | Was wird installiert | Aufwand |
| --- | --- | --- |
| **A: mit Docker** (empfohlen) | nur Docker | ein Befehl, erster Start 2–4 Minuten |
| **B: ohne Docker** | Python 3.12 oder 3.13 und PostgreSQL 16 | etwa 10 Minuten |

Danach: [Anmelden](#anmelden), [Selbsttest](#selbsttest), [Ausprobieren](#vorschlag-zum-ausprobieren), [Probleme](#häufige-probleme).

Ein Terminal im Ordner `CourtSlot` öffnen (nach dem Entpacken des ZIP):

- **Windows:** Ordner im Explorer öffnen, Rechtsklick in den leeren Bereich, „Im Terminal öffnen“. Alle Befehle unten sind für PowerShell.
- **macOS:** Rechtsklick auf den Ordner im Finder, „Dienste“, „Neues Terminal beim Ordner“.
- **Linux:** Terminal öffnen und mit `cd` in den Ordner wechseln.

---

## Weg A: mit Docker

1. Docker installieren:
   - **Windows:** Docker Desktop von <https://www.docker.com/products/docker-desktop/> installieren. Der Installer richtet WSL 2 ein, danach einmal neu starten.
   - **macOS:** Docker Desktop von derselben Seite installieren (Variante „Apple Silicon“ oder „Intel“, je nach Mac).
   - **Linux:** Docker Engine mit Compose-Plugin nach <https://docs.docker.com/engine/install/> installieren, danach `sudo usermod -aG docker $USER` und einmal ab- und wieder anmelden.
2. Docker Desktop starten und warten, bis unten links „Engine running“ steht (unter Linux entfällt das).
3. Im Terminal im Ordner `CourtSlot`:
   ```
   docker compose up --build
   ```
   Fertig ist es, wenn im Terminal `Application startup complete` erscheint.
4. Im Browser <http://localhost:8000> öffnen.
5. Mails (z. B. Bestätigungslinks bei der Registrierung) erscheinen unter <http://localhost:8025>.
6. Beenden mit `Strg+C`. Zurücksetzen auf die Demo-Daten: `docker compose down -v`, dann wieder Schritt 3.

---

## Weg B: ohne Docker

Das Passwort für die Datenbank bitte ohne Sonderzeichen wie `@ : / ?` wählen, sonst muss es in der Verbindungsadresse umgeschrieben werden.

### Windows (PowerShell)

1. Python 3.13 von <https://www.python.org/downloads/windows/> installieren („Windows installer (64-bit)“). Im ersten Fenster den Haken **„Add python.exe to PATH“** setzen.
2. PostgreSQL 16 von <https://www.postgresql.org/download/windows/> installieren (Installer von EDB). Standardwerte übernehmen, Port 5432, ein Passwort für den Benutzer `postgres` festlegen. Den Stack Builder am Ende nicht starten.
3. Datenbank anlegen (fragt nach dem Passwort aus Schritt 2):
   ```
   & "C:\Program Files\PostgreSQL\16\bin\psql.exe" -U postgres -c "CREATE DATABASE courtslot"
   ```
4. Im Ordner `CourtSlot` die Umgebung anlegen und die Pakete installieren:
   ```
   py -3.13 -m venv .venv
   .venv\Scripts\python -m pip install -r requirements.txt
   ```
5. Verbindung zur Datenbank setzen (`PASSWORT` durch das Passwort aus Schritt 2 ersetzen):
   ```
   $env:DATABASE_URL = "postgresql+psycopg://postgres:PASSWORT@localhost:5432/courtslot"
   ```
6. Datenbankschema und Demo-Daten anlegen:
   ```
   .venv\Scripts\python -m scripts.seed
   ```
7. Anwendung starten:
   ```
   .venv\Scripts\python -m uvicorn app.main:app --port 8000
   ```
8. Im Browser <http://localhost:8000> öffnen. Mails erscheinen in diesem Fenster, den Bestätigungslink von dort kopieren.

Später erneut starten: neues PowerShell-Fenster im Ordner, Schritt 5 und 7.

### macOS (Terminal)

1. Homebrew installieren, falls noch nicht vorhanden: Befehl von <https://brew.sh> ins Terminal kopieren und ausführen.
2. Python und PostgreSQL installieren und die Datenbank starten:
   ```
   brew install python@3.13 postgresql@16
   brew services start postgresql@16
   ```
3. Datenbank anlegen:
   ```
   "$(brew --prefix postgresql@16)/bin/createdb" courtslot
   ```
4. Im Ordner `CourtSlot` die Umgebung anlegen und die Pakete installieren:
   ```
   python3.13 -m venv .venv
   .venv/bin/python -m pip install -r requirements.txt
   ```
5. Verbindung zur Datenbank setzen (Homebrew legt einen Benutzer mit dem Mac-Benutzernamen an, ohne Passwort):
   ```
   export DATABASE_URL="postgresql+psycopg://$(whoami)@localhost:5432/courtslot"
   ```
6. Datenbankschema und Demo-Daten anlegen:
   ```
   .venv/bin/python -m scripts.seed
   ```
7. Anwendung starten:
   ```
   .venv/bin/python -m uvicorn app.main:app --port 8000
   ```
8. Im Browser <http://localhost:8000> öffnen. Mails erscheinen in diesem Terminal, den Bestätigungslink von dort kopieren.

Später erneut starten: neues Terminal im Ordner, Schritt 5 und 7.

### Linux (Ubuntu 24.04 oder neuer)

1. Python und PostgreSQL installieren (Ubuntu 24.04 bringt Python 3.12 und PostgreSQL 16 mit):
   ```
   sudo apt update
   sudo apt install -y python3 python3-venv postgresql
   ```
2. Datenbankbenutzer und Datenbank anlegen:
   ```
   sudo -u postgres psql -c "CREATE USER courtslot WITH PASSWORD 'courtslot'"
   sudo -u postgres createdb -O courtslot courtslot
   ```
3. Im Ordner `CourtSlot` die Umgebung anlegen und die Pakete installieren:
   ```
   python3 -m venv .venv
   .venv/bin/python -m pip install -r requirements.txt
   ```
4. Verbindung zur Datenbank setzen:
   ```
   export DATABASE_URL="postgresql+psycopg://courtslot:courtslot@localhost:5432/courtslot"
   ```
5. Datenbankschema und Demo-Daten anlegen:
   ```
   .venv/bin/python -m scripts.seed
   ```
6. Anwendung starten:
   ```
   .venv/bin/python -m uvicorn app.main:app --port 8000
   ```
7. Im Browser <http://localhost:8000> öffnen. Mails erscheinen in diesem Terminal.

Andere Distributionen: Python ab 3.12 und PostgreSQL 16 aus den Paketquellen oder von <https://www.postgresql.org/download/linux/> installieren, dann ab Schritt 2.

---

## Anmelden

| Rolle | E-Mail | Passwort |
| --- | --- | --- |
| Verwaltung TC Isartal | admin@tc-isartal.de | demo-courtslot |
| Mitglied (in zwei Vereinen) | lena.hofmann@tc-isartal.de | demo-courtslot |
| Verwaltung TC Seeblick | admin@tc-seeblick.de | demo-courtslot |

Beitrittscode für ein selbst registriertes Konto: `ISAR2026` (Freigabe danach als Verwaltung unter „Mitglieder“).

## Selbsttest

Prüft in einigen Sekunden, ob alles läuft: Anmeldung, Kalender, Buchungsdialog, Buchung und Stornierung. Die Anwendung muss dafür laufen; in einem zweiten Terminal im Ordner `CourtSlot`:

| Weg | Befehl |
| --- | --- |
| A (Docker) | `docker compose exec app python -m scripts.selbsttest` |
| B unter Windows | `.venv\Scripts\python -m scripts.selbsttest` |
| B unter macOS und Linux | `.venv/bin/python -m scripts.selbsttest` |

Am Ende steht `Selbsttest bestanden`, sonst eine Meldung, woran es hakt.

## Vorschlag zum Ausprobieren

1. Als Lena anmelden, im Kalender einen Tag wählen, eine Padel-Startzeit ab 17 Uhr anklicken, 90 Minuten und einen Schläger wählen, buchen.
2. Zwei weitere Buchungen versuchen: Die Regel „höchstens 2 aktive Buchungen“ greift.
3. Als Verwaltung unter „Sperren“ eine gebuchte Zeit sperren: Die betroffene Buchung wird angezeigt und erst nach Bestätigung storniert.
4. Unter „Verwaltung“ Plätze, Preise, Leihartikel, Öffnungszeiten und Auslastung ansehen.
5. Abmelden, „Jetzt registrieren“, Bestätigungslink öffnen (Weg A: <http://localhost:8025>, Weg B: im Terminal), mit dem Beitrittscode beitreten.

## Häufige Probleme

| Meldung oder Verhalten | Lösung |
| --- | --- |
| `port is already allocated` oder `address already in use` bei Port 8000 | Ein anderes Programm nutzt den Port. Weg A: in `docker-compose.yml` bei `app` die Zeile `"8000:8000"` in `"8001:8000"` ändern. Weg B: `--port 8001` verwenden. Dann <http://localhost:8001> öffnen. |
| Docker: `Cannot connect to the Docker daemon` | Docker Desktop ist nicht gestartet. Starten und warten, bis „Engine running“ erscheint. |
| `py` oder `python3.13` wird nicht gefunden | Python neu installieren; unter Windows den Haken „Add python.exe to PATH“ setzen und ein neues PowerShell-Fenster öffnen. |
| `password authentication failed` | Benutzer oder Passwort in `DATABASE_URL` stimmen nicht mit der Datenbank überein. |
| `connection refused` zur Datenbank | PostgreSQL läuft nicht. Windows: Dienst „postgresql-x64-16“ starten; macOS: `brew services start postgresql@16`; Linux: `sudo systemctl start postgresql`. |
| `database "courtslot" does not exist` | Schritt „Datenbank anlegen“ wurde ausgelassen. |
| Anmeldung schlägt fehl | Demo-Daten fehlen: Schritt mit `scripts.seed` ausführen. |

## Getestet

Die Schritte für Weg B laufen bei jeder Änderung automatisch auf frischen Rechnern unter Windows, macOS und Ubuntu 24.04, Weg A unter Ubuntu mit Docker. Getestet wird jeweils aus dem entpackten Abgabe-ZIP, am Ende läuft der Selbsttest (Workflow `.github/workflows/installation.yml`).

## Tests (optional)

Für die 100 automatisierten Tests eine zweite Datenbank `courtslot_test` anlegen (wie oben, nur mit diesem Namen), dann:

1. `pip install -r requirements-dev.txt` in der Umgebung aus Weg B (`.venv\Scripts\python -m pip …` bzw. `.venv/bin/python -m pip …`)
2. `DATABASE_URL` auf die Datenbank `courtslot_test` setzen. Die Tests löschen deren Inhalt und laufen nur gegen einen Namen, der auf `_test` endet.
3. `python -m pytest` in der Umgebung ausführen
