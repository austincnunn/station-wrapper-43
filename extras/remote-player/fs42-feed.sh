#!/bin/sh
# fs42-feed.sh: runs on the SERVER (the machine running station-wrapper-43).
#
# A remote player PC uses a dedicated SSH key to copy this server's schedule. That key is locked to this
# script in ~/.ssh/authorized_keys (command="/home/tv/fieldstation42/fs42-feed.sh",restrict ...), so the
# key can do exactly two things and nothing else:
#
#   snapshot   save a consistent copy of the schedule database, the FieldStation42 commit the wrapper runs,
#              and the Sources page list, into $DATA/crt/
#   (anything else)  a READ-ONLY rsync of $DATA, through rrsync (it comes with Ubuntu's rsync package)
#
# Setup guide: https://github.com/austincnunn/station-wrapper-43/wiki/Syncing-a-Remote-Player

# ---- settings ----------------------------------------------------------------------------------------------
DATA=/home/tv/fieldstation42/data       # the folder mounted as /config and /app/catalog (it holds config/ and catalog/)
CONTAINER=station-wrapper-43            # the wrapper container's name
# ------------------------------------------------------------------------------------------------------------

case "$SSH_ORIGINAL_COMMAND" in
  snapshot)
    # The schedule database is live sqlite, so copy it with sqlite's backup API, never as an open file.
    python3 -c "
import os, sqlite3, sys
d = sys.argv[1]; out = os.path.join(d, \"crt\"); os.makedirs(out, exist_ok=True)
tmp = os.path.join(out, \".fs42_fluid.db.tmp\")
src = sqlite3.connect(\"file:\" + d + \"/config/runtime/fs42_fluid.db?mode=ro\", uri=True)
dst = sqlite3.connect(tmp); src.backup(dst); dst.close(); src.close()
os.replace(tmp, os.path.join(out, \"fs42_fluid.db\"))
" "$DATA" || exit 1
    # The FieldStation42 commit inside the image, so the player can run the same version.
    docker exec "$CONTAINER" cat /opt/FS42_REF > "$DATA/crt/.FS42_REF" && mv "$DATA/crt/.FS42_REF" "$DATA/crt/FS42_REF"
    # The Sources page list. The wrapper saves it readable by root only, so read it through the container.
    docker exec "$CONTAINER" cat /config/tuner/sources.json > "$DATA/crt/.sources.json" &&
      mv "$DATA/crt/.sources.json" "$DATA/crt/sources.json"
    exit 0 ;;
  *) exec /usr/bin/rrsync -ro "$DATA" ;;
esac
