"""Erzeugt das Abgabe-ZIP mit allem selbst geschriebenen Material.

Enthalten sind alle Dateien, die im Git-Repository versioniert sind (Code, Tests,
Migrationen, Diagramme, Doku), unter dem Ordner CourtSlot/. Nicht enthalten sind
lokale Dateien wie .venv, .env, Caches und die Git-Historie.

Aufruf:  python -m scripts.abgabe_zip [Zielordner]   (Standard: abgabe/)
Weitere Abgabedateien (Ausarbeitung, Folien) legt man in den Zielordner dazu.
"""

import subprocess
import sys
import zipfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def tracked_files() -> list[str]:
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, check=True, capture_output=True,
                         text=True).stdout
    return sorted(line for line in out.splitlines() if line)


def main() -> None:
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "abgabe"
    target.mkdir(parents=True, exist_ok=True)
    zip_path = target / f"CourtSlot_Quellcode_{date.today():%Y-%m-%d}.zip"
    files = tracked_files()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in files:
            zf.write(ROOT / name, f"CourtSlot/{name}")
    size = zip_path.stat().st_size / 1024 / 1024
    print(f"{zip_path} geschrieben: {len(files)} Dateien, {size:.1f} MB")


if __name__ == "__main__":
    main()
