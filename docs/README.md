# Dokumentation

| Datei | Inhalt |
| --- | --- |
| `diagramme/use_cases.*` | Use-Case-Diagramm |
| `diagramme/klassen.*` | Klassendiagramm (Domänenmodell) |
| `diagramme/zustand_buchung.*` | Zustandsdiagramm einer Buchung |
| `diagramme/sequenz_buchen.*` | Sequenzdiagramm „Slot buchen“ inkl. Nebenläufigkeit |
| `diagramme/datenmodell.*` | Datenmodell (PostgreSQL) |
| `diagramme/c4_kontext.*` | Systemkontext (C4 Ebene 1) |
| `diagramme/c4_container.*` | Container (C4 Ebene 2) |
| `diagramme/zielbetrieb.*` | Verteilungssicht Zielbetrieb |
| `wirtschaftlichkeit/break_even.py` | Break-even-Rechnung und Kennzahlen |
| `lasttest/` | Lasttest-Skript und Ergebnis zu NFA-01 |

Die Quelltexte der Diagramme liegen in `uml/` (PlantUML). Neu erzeugen:
`java -jar plantuml.jar -charset UTF-8 -tpng -o ../diagramme docs/uml/*.puml`
