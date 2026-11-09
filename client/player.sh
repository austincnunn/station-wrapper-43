#!/bin/sh
# Client mode: FieldStation42's player, drawing with mpv straight to the screen (see client.py for the settings).
# It waits until client.py says the schedule is here and the videos can be found, and starts again when it stops
# (client.py stops it when the stations change, or the media share goes away).
cd "${FS42_APP:-/app}"
while true; do
  while [ ! -e runtime/client_ready ]; do sleep 2; done
  python3 field_player.py
  sleep 1
done
