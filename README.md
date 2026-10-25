# CourtSlot

Buchungsplattform für Tennis- und Padelvereine – Prototyp im Modul „Projekt: Anwendungsentwicklung“ (FOM, WiSe 2026/27).

Mitglieder sehen die Belegung aller Plätze in einem Wochenkalender und buchen selbst. Der Verein legt Regeln fest, die das System automatisch durchsetzt. Doppelbuchungen sind technisch ausgeschlossen, auch bei gleichzeitigen Anfragen.

## Starten

Voraussetzung: Docker mit Docker Compose.

```bash
docker compose up --build
```

Danach im Browser <http://localhost:8000> öffnen. Beim ersten Start werden Demo-Daten geladen (Verein „TC Isartal“, 4 Plätze, 20 Mitglieder, vorbelegte Buchungen).

| Rolle | E-Mail | Passwort |
| --- | --- | --- |
| Admin (Platzwart) | admin@tc-isartal.de | demo1234 |
| Mitglied | lena.hofmann@tc-isartal.de | demo1234 |
| Admin eines zweiten Vereins (Mandantentrennung) | admin@tc-seeblick.de | demo1234 |

Demo-Daten neu laden: `docker compose run --rm seed python -m scripts.seed --reset`

## Funktionen

| Nr. | Funktion | Story |
| --- | --- | --- |
| P-01 | Anmeldung per E-Mail und Passwort, Rollen Mitglied und Admin | US-01 |
| P-02 | Wochenkalender aller Plätze, 60-Minuten-Slots von 8 bis 22 Uhr | US-03 |
| P-03 | Freien Slot buchen, sofortige Bestätigung | US-04 |
| P-04 | Doppelbuchungsschutz per Unique-Index in PostgreSQL | US-05 |
| P-05 | Buchungsregeln: max. aktive Buchungen, max. Vorlauf (einstellbar) | US-06 |
| P-06 | Stornieren bis Slotbeginn | US-07 |
| P-07 | Meine Buchungen (kommend und vergangen) | US-08 |
| P-08 | Platzverwaltung (anlegen, bearbeiten, deaktivieren) | US-09 |
| P-09 | Platzsperren mit Grund, betroffene Buchungen nach Bestätigung storniert | US-10 |
| P-10 | Mitgliederverwaltung (anlegen mit Startpasswort, sperren, entfernen) | US-02 |
| – | Auslastung je Platz und Woche (Should) | US-11 |
| – | Mandantentrennung über `club_id` in allen Daten und Abfragen (Should) | US-12 |

## Aufbau

```
app/
  main.py            FastAPI-Anwendung, Middleware, Fehlerseiten
  models.py          Domänenmodell (SQLAlchemy)
  security.py        Passwort-Hashing (Argon2), CSRF, Rollenprüfung
  services/
    booking.py       Buchungsregeln, Doppelbuchungsschutz, Wochenansicht
    admin.py         Mitglieder, Plätze, Sperren, Regeln, Auslastung
  routes/            HTTP-Endpunkte (Kalender, Anmeldung, Admin)
  templates/         Jinja2-Vorlagen, Interaktion per HTMX
scripts/seed.py      Demo-Daten
tests/               60 automatisierte Tests (pytest)
docs/                UML- und Architekturdiagramme
```

Technik: Python 3.13, FastAPI, SQLAlchemy 2, PostgreSQL 16, Jinja2, HTMX, Docker Compose.

## Entwicklung und Tests

```bash
pip install -r requirements-dev.txt
export DATABASE_URL=postgresql+psycopg://courtslot:courtslot@localhost:5432/courtslot_test
pytest --cov=app        # 60 Tests, Abdeckung 92 %, inkl. 100 Buchungsversuchen auf denselben Slot (je 25 gleichzeitig)
ruff check app tests scripts
```

Die CI-Pipeline (`.github/workflows/ci.yml`) führt bei jedem Push Linter und Tests gegen PostgreSQL aus und baut das Container-Image.

## Oberfläche

Eigenes Design in Hartplatzblau und Ballgelb mit der Schrift Archivo (lokal eingebunden, SIL Open Font License). Der Kalender zeigt eine Tagesleiste mit freien Slots je Tag; Buchen und Stornieren laufen über einen eigenen Bestätigungsdialog. Auf dem Smartphone gibt es eine Navigationsleiste am unteren Rand.

## Screenshots

`docs/screenshots/` zeigt alle Ansichten, u. a. den Kalender bei 360 px Breite und den Admin-Bereich. Sie ersetzen im Projekt die Wireframes, weil die Oberfläche direkt als Prototyp entworfen wurde.

## Sicherheit

- Passwörter als Argon2-Hash; Anmeldung mit gleicher Meldung und gleicher Rechenzeit für unbekannte E-Mail und falsches Passwort
- Signiertes Sitzungs-Cookie (HttpOnly, SameSite=Lax); Abmelden, Sperren und Entfernen machen bestehende Sitzungen ungültig
- CSRF-Token für jede schreibende Anfrage, Rollen- und Vereinsprüfung serverseitig
- `SECRET_KEY` per Umgebungsvariable; mit `SECURE_COOKIES=true` (Zielbetrieb, HTTPS) startet die Anwendung nur mit eigenem Schlüssel ab 32 Zeichen

## Bekannte Grenzen des Prototyps

- Tabellen werden beim Start angelegt; im Zielbetrieb übernehmen das Datenbankmigrationen.
- Kein Passwort-Zurücksetzen per E-Mail; Admins vergeben Startpasswörter.
- Löschen von Buchungen älter als 12 Monate (NFA-07) ist konzipiert, aber nicht als Job umgesetzt.
- Kein Rate Limiting beim Login; im Zielbetrieb übernimmt das der Ingress.
- Online-Zahlung, native App, Flutlichtsteuerung und Turnierverwaltung sind nicht im Umfang.
