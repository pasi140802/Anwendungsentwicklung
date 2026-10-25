#!/bin/sh
# Sicherung der Datenbank im Custom-Format, ältere als BACKUP_KEEP_DAYS werden gelöscht.
# Wiederherstellen: pg_restore -h db -U courtslot -d courtslot --clean /backups/<datei>
set -eu
stamp=$(date +%Y-%m-%d_%H%M)
file="/backups/courtslot_${stamp}.dump"
pg_dump -h db -U courtslot -d courtslot -Fc -f "$file.tmp"
mv "$file.tmp" "$file"
find /backups -name 'courtslot_*.dump' -mtime +"${BACKUP_KEEP_DAYS:-14}" -delete
echo "Sicherung erstellt: $file ($(du -h "$file" | cut -f1))"
