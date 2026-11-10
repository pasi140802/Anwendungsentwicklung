"""Erzeugt das Abgabe-ZIP mit allem selbst geschriebenen Material.

Enthalten sind alle Dateien, die im Git-Repository versioniert sind (Code, Tests,
Migrationen, Diagramme, Doku), unter dem Ordner CourtSlot/. Nicht enthalten sind
lokale Dateien wie .venv, .env, Caches und die Git-Historie.

Aufruf:  python -m scripts.abgabe_zip [--ziel ORDNER] [--dazu DATEI ...]
  --ziel  Zielordner für das ZIP (Standard: abgabe/)
  --dazu  weitere Abgabedateien, z. B. Ausarbeitung und Folien als PDF; sie
          landen im ZIP unter CourtSlot/Ausarbeitung_und_Folien/
"""

import argparse
import subprocess
import zipfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def tracked_files() -> list[str]:
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, check=True, capture_output=True,
                         text=True).stdout
    return sorted(line for line in out.splitlines() if line)


def main() -> None:
    parser = argparse.ArgumentParser(description="Abgabe-ZIP erzeugen")
    parser.add_argument("--ziel", type=Path, default=ROOT / "abgabe")
    parser.add_argument("--dazu", type=Path, nargs="*", default=[])
    args = parser.parse_args()
    missing = [str(p) for p in args.dazu if not p.is_file()]
    if missing:
        parser.error("nicht gefunden: " + ", ".join(missing))
    args.ziel.mkdir(parents=True, exist_ok=True)
    zip_path = args.ziel / f"CourtSlot_Abgabe_{date.today():%Y-%m-%d}.zip"
    files = tracked_files()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in files:
            zf.write(ROOT / name, f"CourtSlot/{name}")
        for extra in args.dazu:
            zf.write(extra, f"CourtSlot/Ausarbeitung_und_Folien/{extra.name}")
    size = zip_path.stat().st_size / 1024 / 1024
    print(f"{zip_path} geschrieben: {len(files)} Dateien aus dem Repository, "
          f"{len(args.dazu)} weitere, {size:.1f} MB")


if __name__ == "__main__":
    main()
