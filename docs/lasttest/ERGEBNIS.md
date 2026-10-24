# Lasttest NFA-01 – Ergebnis vom 24.10.2026

Umgebung: Entwicklungsrechner mit 2 vCPU, Anwendung mit 2 Uvicorn-Workern, PostgreSQL 16 lokal, Lastgenerator auf demselben Rechner. Demo-Daten „TC Isartal“ (4 Plätze, rund 140 Buchungen je Woche). Gemessen wird der Aufruf des Wochenkalenders durch angemeldete Nutzer (halb Admin, halb Mitglied).

| Szenario | Anfragen/s | Median | p95 | Fehler | NFA-01 (p95 < 500 ms) |
| --- | --- | --- | --- | --- | --- |
| 50 Nutzer, 1 s Denkzeit zwischen Seitenaufrufen | 48 | 26 ms | 210 ms | 0 | erfüllt |
| 50 Nutzer ohne Denkzeit (Stresstest) | 97 | 512 ms | 758 ms | 0 | nicht erfüllt |

Verlauf der Optimierung im Stresstest (ohne Denkzeit):

| Stand | Anfragen/s | p95 |
| --- | --- | --- |
| 1 Worker, Benutzernamen je Buchung einzeln geladen (N+1) | 48 | 1.737 ms |
| 2 Worker, Benutzer per `selectinload` in einer Abfrage | 93 | 892 ms |
| zusätzlich schlankeres HTML für freie Slots | 97 | 758 ms |

Bewertung: Unter realistischer Nutzung ist NFA-01 erfüllt. Im Stresstest begrenzen die 2 vCPU des Testrechners den Durchsatz auf rund 100 Anfragen/s (rund 18 ms Rechenzeit je Anfrage, Lastgenerator auf derselben Maschine). Im Zielbetrieb skaliert die zustandslose Anwendung horizontal über mehrere Pods; mit 3 Pods à 2 Workern liegt die rechnerische Kapazität beim Dreifachen.

Wiederholen: `python docs/lasttest/lasttest.py http://localhost:8000 20 1` (Denkzeit 1 s) bzw. `… 20 0` (Stresstest).
