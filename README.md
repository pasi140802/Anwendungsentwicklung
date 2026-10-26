# CourtSlot

Buchungsplattform für Tennis- und Padelvereine und gewerbliche Anlagen. Entstanden im Modul „Projekt: Anwendungsentwicklung“ (FOM, WiSe 2026/27).

Mitglieder legen ein Konto an, treten ihrem Verein per Einladung oder Beitrittscode bei und buchen Plätze selbst. Betreiber pflegen Plätze, Preise, Öffnungszeiten, Saison und Regeln online. Spieler wählen beim Buchen 60 oder 90 Minuten und leihen Schläger oder Bälle dazu. Doppelbuchungen sind technisch ausgeschlossen, auch bei gleichzeitigen Anfragen und unterschiedlich langen Buchungen.

## Starten

Voraussetzung: Docker mit Docker Compose.

```bash
docker compose up --build
```

- App: <http://localhost:8000>
- Mails: <http://localhost:8025> (Mailpit fängt alle Mails ab, z. B. Bestätigungs- und Einladungslinks)

Beim ersten Start wird das Schema per Migration angelegt und es werden Demo-Daten geladen: TC Isartal mit Tennis (zwei Sandplätze nur im Sommer, Halle 26 €/Std., Hauptzeit 32 €) und Padel (36 €/Std., Hauptzeit 44 €, also 66 € für 90 Minuten), Leihschläger und Bälle, 20 Mitglieder, eine Beitrittsanfrage, eine offene Einladung, sowie der TC Seeblick.

| Rolle | E-Mail | Passwort |
| --- | --- | --- |
| Verwaltung TC Isartal | admin@tc-isartal.de | demo-courtslot |
| Mitglied in zwei Vereinen | lena.hofmann@tc-isartal.de | demo-courtslot |
| Verwaltung TC Seeblick | admin@tc-seeblick.de | demo-courtslot |

Beitrittscode des TC Isartal: `ISAR2026`.

Demo-Daten neu laden: `docker compose run --rm migrate python -m scripts.seed --reset`

Nach einem Update mit Schemaänderung einmalig `docker compose down -v` ausführen (löscht die lokale Demo-Datenbank).

## Funktionen

**Konto**
- Registrierung mit Bestätigung der E-Mail-Adresse, Passwortregeln, Einwilligung zur Datenschutzerklärung
- Passwort vergessen (Link 1 Stunde gültig, nur einmal nutzbar), Passwort ändern meldet andere Geräte ab
- Daten herunterladen (JSON) und Konto löschen (DSGVO Art. 20 und 17)

**Vereine und Mitglieder**
- Verein oder gewerbliche Anlage selbst anlegen, Ersteller wird Verwaltung
- Beitritt per Einladungsmail (sofort Mitglied) oder Beitrittscode (Freigabe durch die Verwaltung)
- Ein Konto in mehreren Vereinen, Wechsel über das Benutzermenü
- Rollen Mitglied und Verwaltung, Sperren, Entfernen; der letzte Admin ist geschützt

**Plätze und Buchung**
- Plätze mit Sportart, Belag, Halle, Flutlicht, Saison (ganzjährig, Sommer, Winter), buchbare Spieldauer (60, 90, 120 Min.), Preis pro Stunde und Hauptzeitpreis
- Leihartikel wie Schläger und Bälle mit Preis und Höchstmenge je Buchung, je Sportart
- Öffnungszeiten je Wochentag, Sommersaison, Hauptzeit, Buchungsregeln (aktive Buchungen, Vorlauf, Stornofrist)
- Tagesansicht als Zeitachse mit Startzeiten im 30-Minuten-Raster und Preisen; Buchungsdialog mit Spieldauer, Leihartikeln und Gesamtpreis
- Doppelbuchungsschutz per Ausschluss-Constraint in PostgreSQL über Zeiträume (`tstzrange`)
- Sperren mit Grund; betroffene Buchungen werden nach Bestätigung storniert und per Mail informiert
- Bestätigungsmail nach jeder Buchung, Mail bei Stornierung durch die Verwaltung
- Auslastung je Platz und Woche in Stunden

**Betrieb**
- Schema über Alembic-Migrationen, Gesundheitsprüfung unter `/health`
- Impressum und Datenschutzerklärung mit Betreiberangaben aus der Konfiguration
- Produktions-Setup mit Caddy (HTTPS), Backups und Wartungsjob: siehe [docs/BETRIEB.md](docs/BETRIEB.md)

Nicht im Umfang: Online-Zahlung, Gastbuchung ohne Konto, Abonnements, native App.

## Aufbau

```
app/
  main.py            FastAPI-Anwendung, Sicherheits-Header, Fehlerseiten
  models.py          Domänenmodell (SQLAlchemy)
  security.py        Passwort-Hashing (Argon2), Sitzung, CSRF, Rollen
  tokens.py          signierte Links (Bestätigung, Passwort, Einladung)
  mail.py            Mailversand (SMTP), Vorlagen in templates/mail
  ratelimit.py       Begrenzung von Anmelde- und Mailversuchen
  services/
    booking.py       Startraster, Dauer, Preise, Leihe, Regeln, Doppelbuchungsschutz
    accounts.py      Konten, Vereine, Beitritt, Einladungen, DSGVO
    admin.py         Mitglieder, Plätze, Sperren, Einstellungen, Auslastung
  routes/            HTTP-Endpunkte
  templates/         Jinja2-Vorlagen, Interaktion per HTMX
migrations/          Alembic-Migrationen
scripts/             Demo-Daten, Wartung
deploy/              Caddyfile, Backup-Skript
tests/               99 automatisierte Tests (pytest)
docs/                UML- und Architekturdiagramme, Betriebshandbuch
```

Technik: Python 3.13, FastAPI, SQLAlchemy 2, Alembic, PostgreSQL 16, Jinja2, HTMX, Docker Compose, Caddy.

## Entwicklung und Tests

```bash
pip install -r requirements-dev.txt
export DATABASE_URL=postgresql+psycopg://courtslot:courtslot@localhost:5432/courtslot_test
pytest --cov=app
ruff check .
```

Die Tests bauen das Schema über die Migrationen auf und prüfen, dass Modelle und Migrationen übereinstimmen. Darunter: 100 gleichzeitige Buchungsversuche auf denselben Slot, überlappende 60- und 90-Minuten-Buchungen, Preise über die Hauptzeitgrenze, Leihartikel, Registrierung mit Bestätigungslink, Einladung, Beitritt mit Freigabe, Passwort-Reset, Löschung und Export.

Die CI-Pipeline (`.github/workflows/ci.yml`) führt bei jedem Push Linter und Tests gegen PostgreSQL aus und baut das Container-Image.

## Sicherheit

- Passwörter als Argon2-Hash; gleiche Meldung und Rechenzeit für unbekannte Adresse und falsches Passwort; Registrierung verrät nicht, ob eine Adresse existiert
- Signiertes Sitzungs-Cookie (HttpOnly, SameSite=Lax, im Zielbetrieb Secure); Abmelden, Passwortwechsel und Sperren beenden bestehende Sitzungen
- CSRF-Token für jede schreibende Anfrage, Rollen- und Vereinsprüfung serverseitig
- Content-Security-Policy ohne Inline-Skripte, HSTS im Zielbetrieb
- Rate Limiting für Anmeldung und Mailversand

## Screenshots

`docs/screenshots/` zeigt die Ansichten auf Desktop und Smartphone, u. a. Kalender, Registrierung, Konto und Betreiberbereich.
