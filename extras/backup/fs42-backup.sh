#!/bin/bash
# fs42-backup.sh: nightly backup of a Station Wrapper 43 install. Runs on the SERVER from your own crontab
# (no root needed, but your user must be able to run docker).
#
# Writes one fs42-YYYY-MM-DD.tar.gz per night into $DEST and keeps the newest $KEEP.
# It saves the compose file, .env, your scripts and data/ (station configs, the schedule, the catalog's
# symlinks), but skips things that rebuild themselves:
#   data/catalog/media-links   the "pool" of links to every video (the sync service makes it again)
#   data/crt                   a remote player's snapshot (fs42-feed.sh makes it again)
#
# Why tar and not rsync: a network share (SMB/CIFS) usually can't store symlinks or 0600 file modes.
# Inside the tar they are kept exactly.
# The schedule database is live sqlite, so it goes in from a sqlite backup-API copy, not the open file.
# Two files the wrapper keeps root-only (0600) are read through the container instead.
#
# Restore and cron setup: https://github.com/austincnunn/station-wrapper-43/wiki/Backups
set -euo pipefail

# ---- settings ----------------------------------------------------------------------------------------------
SRC=/home/tv/fieldstation42                 # the folder with docker-compose.yml and data/
DEST=/mnt/backups/fieldstation42            # where the backups go (a NAS share is fine)
KEEP=14                                     # how many nightly backups to keep
CONTAINER=station-wrapper-43                # the wrapper container's name
DEST_MOUNT=""                               # optional: a mount point that must be mounted first, e.g. /mnt/backups
# ------------------------------------------------------------------------------------------------------------

DB=data/config/runtime/fs42_fluid.db
if [ -n "$DEST_MOUNT" ]; then
  mountpoint -q "$DEST_MOUNT" || { echo "$DEST_MOUNT is not mounted" >&2; exit 1; }
fi
mkdir -p "$DEST"
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT

python3 - "$SRC/$DB" "$T/db" <<'PY'
import sqlite3, sys
s = sqlite3.connect("file:" + sys.argv[1] + "?mode=ro", uri=True); d = sqlite3.connect(sys.argv[2])
s.backup(d); d.close(); s.close()
PY

ROOTONLY="mediaserver.json sources.json"
# Stops here if the container isn't running. A file that doesn't exist yet (no Emby/Jellyfin, no sources) is saved empty.
for f in $ROOTONLY; do docker exec "$CONTAINER" sh -c "cat /config/tuner/$f 2>/dev/null || true" > "$T/$f"; done

OUT="$DEST/fs42-$(date +%F).tar.gz"
tar -czf "$OUT.part" -C "$SRC" \
  --exclude=./data/catalog/media-links --exclude=./data/crt --exclude="./$DB" \
  --exclude=channel.socket --exclude=./data/config/tuner/mediaserver.json --exclude=./data/config/tuner/sources.json . \
  -C "$T" --transform="s,^db\$,./$DB," --transform="s,^\(mediaserver\|sources\).json\$,./data/config/tuner/\1.json," \
  db $ROOTONLY
mv "$OUT.part" "$OUT"
gzip -t "$OUT"
ls -1t "$DEST"/fs42-*.tar.gz | tail -n +$((KEEP+1)) | xargs -r rm --
echo "$(date '+%F %T') ok $OUT $(du -h "$OUT" | cut -f1)"
