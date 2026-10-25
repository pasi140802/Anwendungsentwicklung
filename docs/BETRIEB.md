# Betriebshandbuch CourtSlot

Wie CourtSlot im Internet betrieben wird. Die Wahl des Hosters ist noch offen; alles hier läuft auf jedem Linux-Server mit Docker (Stufe 1 der Analyse „Produktivbetrieb“: ein Server mit 2 bis 4 vCPU und 4 bis 8 GB RAM, z. B. Hetzner CPX22 oder vergleichbar, rund 25 bis 35 € im Monat einschließlich Mail und Backup-Speicher).

## Bausteine

| Dienst | Aufgabe |
| --- | --- |
| `caddy` | HTTPS mit automatischem Let's-Encrypt-Zertifikat, Weiterleitung von HTTP, Kompression |
| `app` | CourtSlot (FastAPI, 2 Worker), nur im internen Netz erreichbar |
| `migrate` | bringt das Datenbankschema bei jedem Start per Alembic auf Stand |
| `db` | PostgreSQL 16, Daten im Volume `pgdata` |
| `backup` | nächtliche Sicherung mit `pg_dump`, 14 Tage aufbewahrt |
| `maintenance` | löscht täglich unbestätigte Konten (7 Tage) und Buchungen älter als 12 Monate |

Die Anwendung selbst ist hosting-unabhängig: Konfiguration nur über Umgebungsvariablen, Zustand nur in PostgreSQL, Mails über beliebigen SMTP-Anbieter.

## Erstinstallation

1. Server mit Ubuntu 24.04 anlegen, SSH-Schlüssel hinterlegen, Firewall nur für 22, 80 und 443 öffnen.
2. Docker installieren: `curl -fsSL https://get.docker.com | sh`
3. DNS: A-Record (und AAAA) der Domain auf die Server-IP setzen.
4. Mailanbieter einrichten (SMTP-Zugang, Absenderdomain mit SPF, DKIM und DMARC verifizieren, Vertrag zur Auftragsverarbeitung abschließen).
5. Code holen und konfigurieren:
   ```bash
   git clone https://github.com/pasi140802/Anwendungsentwicklung.git courtslot && cd courtslot
   cp .env.example .env
   python3 -c "import secrets; print(secrets.token_urlsafe(48))"   # für SECRET_KEY
   python3 -c "import secrets; print(secrets.token_urlsafe(24))"   # für POSTGRES_PASSWORD
   nano .env
   ```
6. Starten: `docker compose -f docker-compose.prod.yml up -d --build`
7. Prüfen: `https://<domain>/health` liefert `{"status": "ok"}`; Registrierung mit eigener Adresse testen (Mail muss ankommen).
8. Impressum und Datenschutzerklärung mit echten Betreiberangaben prüfen (Texte sind Vorlagen und vor dem Start rechtlich zu prüfen).

## Update einspielen

```bash
git pull
docker compose -f docker-compose.prod.yml up -d --build
```

`migrate` läuft vor der App und wendet neue Migrationen an. Neue Migration in der Entwicklung erzeugen: `alembic revision --autogenerate -m "beschreibung"`, prüfen, committen. Der Test `test_models_match_migrations` schlägt fehl, wenn eine Modelländerung ohne Migration eingecheckt wird.

## Sicherung und Wiederherstellung

- Sicherungen liegen im Volume `backups` (`/backups/courtslot_<datum>.dump`).
- Eine Kopie außer Haus ist Pflicht, z. B. täglich per `rclone` oder `restic` auf einen Speicher bei einem anderen Anbieter (Hetzner Storage Box, S3-kompatibler Speicher).
- Wiederherstellung testen, mindestens einmal pro Quartal:
  ```bash
  docker compose -f docker-compose.prod.yml exec backup sh -c \
    "pg_restore -h db -U courtslot -d courtslot --clean --if-exists /backups/<datei>"
  ```

## Überwachung

- Uptime-Prüfung von außen auf `/health` (z. B. UptimeRobot oder Better Stack, kostenlos), Alarm per Mail.
- Logs: `docker compose -f docker-compose.prod.yml logs -f app caddy`. Log-Dateien sind auf 5 × 10 MB je Dienst begrenzt.
- Fehlgeschlagene Mails erscheinen im App-Log als „Mailversand an … fehlgeschlagen“.

## Sicherheit

- HTTPS erzwungen, HSTS gesetzt, Cookies nur über HTTPS (`SECURE_COOKIES=true`), App startet nur mit eigenem `SECRET_KEY`.
- Content-Security-Policy ohne Inline-Skripte, Schutz vor Einbettung in fremde Seiten.
- Anmeldung begrenzt auf 10 Versuche je Adresse und 30 je IP in 15 Minuten, Mail-Versand auf 5 je IP. Die Zähler gelten je Worker-Prozess; wer mehrere Server betreibt, verschiebt sie nach Redis oder in den Proxy.
- Datenbank ist nicht von außen erreichbar, Container laufen ohne Root-Rechte.
- Server-Updates: `unattended-upgrades` aktivieren, Docker-Images monatlich neu bauen.

## Wachstum (Stufe 2)

Ab etwa 50 aktiven Vereinen oder wenn Ausfallzeiten vertraglich zugesagt werden: Datenbank als Managed PostgreSQL mit Point-in-Time-Recovery, zwei App-Server hinter einem Load Balancer, Rate Limiting in Redis. Kostenrahmen laut Analyse rund 250 € im Monat.
