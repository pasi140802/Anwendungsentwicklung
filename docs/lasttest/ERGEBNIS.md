# Lasttest NFA-01 – Ergebnis

Umgebung: Entwicklungsrechner mit 2 vCPU, Anwendung mit 2 Uvicorn-Workern, PostgreSQL 16 lokal, Lastgenerator auf demselben Rechner. Demo-Daten „TC Isartal“ (Tennis und Padel, rund 140 Buchungen je Woche). Gemessen wird der Aufruf des Wochenkalenders durch angemeldete Nutzer (halb Verwaltung, halb Mitglied), je Szenario 30 Sekunden.

## Messung vom 10.11.2026 (aktueller Stand)

| Szenario | Anfragen/s | Median | p95 | Fehler | NFA-01 (p95 < 500 ms) |
| --- | --- | --- | --- | --- | --- |
| 50 Nutzer, Denkzeit im Mittel 1 s, versetzter Start (3 Läufe) | 47–48 | 38–49 ms | 152–224 ms | 0 | erfüllt |
| 50 Nutzer ohne Denkzeit (Stresstest) | 80 | 614 ms | 883 ms | 0 | nicht erfüllt |

Die erneute Messung nach Einführung der 30-Minuten-Startzeiten zeigte zunächst einen Rückschritt: Die Kalenderseite enthielt alle sieben Tage auf einmal (rund 215 KB HTML, rund 55 ms je Aufruf), der p95-Wert lag bei rund 2,5 s. Behoben durch:

| Änderung | Wirkung |
| --- | --- |
| Nur der gewählte Tag wird gerendert, weitere Tage werden beim Wechsel nachgeladen (`/kalender/tag`) | Seite 30 KB statt 215 KB, rund 20 ms je Aufruf |
| Buchungen und Sperren je Tag vorgefiltert, kein Preis für vergangene Startzeiten | Aufbau der Woche 8 statt 17 ms |
| Statuszeile fragt nur kommende Buchungen des Vereins ab statt aller eigenen Buchungen | eine schlankere Abfrage je Aufruf |

Zusätzlich wurde das Testskript korrigiert: Die Nutzer melden sich nicht mehr einzeln an (die Begrenzung der Anmeldeversuche hätte sonst gegriffen), starten versetzt und warten zufällig 0,5 bis 1,5 s. Ohne Versatz liefen alle 50 Nutzer im Gleichtakt und schickten jede Sekunde 50 Anfragen gleichzeitig; das ergab p95-Werte zwischen 260 und 660 ms je nach Lauf.

## Messung vom 24.10.2026 (erster Prototyp, Slots zur vollen Stunde)

| Szenario | Anfragen/s | Median | p95 | Fehler |
| --- | --- | --- | --- | --- |
| 50 Nutzer, 1 s Denkzeit (gleichzeitiger Start) | 48 | 26 ms | 210 ms | 0 |
| 50 Nutzer ohne Denkzeit (Stresstest) | 97 | 512 ms | 758 ms | 0 |

Verlauf der Optimierung im Stresstest damals:

| Stand | Anfragen/s | p95 |
| --- | --- | --- |
| 1 Worker, Benutzernamen je Buchung einzeln geladen (N+1) | 48 | 1.737 ms |
| 2 Worker, Benutzer per `selectinload` in einer Abfrage | 93 | 892 ms |
| zusätzlich schlankeres HTML für freie Slots | 97 | 758 ms |

## Bewertung

Unter realistischer Nutzung ist NFA-01 für den Kalenderaufruf erfüllt; die Buchung selbst wurde nicht unter Last gemessen. Im Stresstest begrenzen die 2 vCPU des Testrechners, die sich Anwendung, Datenbank und Lastgenerator teilen, den Durchsatz. Im Zielbetrieb skaliert die zustandslose Anwendung horizontal; geplant sind 4 Pods à 2 Worker.

Wiederholen (Anwendung mit Demo-Daten muss laufen): `python docs/lasttest/lasttest.py http://localhost:8000 30 1` (Denkzeit 1 s) bzw. `… 30 0` (Stresstest).
