#!/bin/sh
# Client mode: FieldStation42's player (see client.py for the settings). It waits until client.py says the schedule is here
# and the videos can be found, and starts again when it stops (client.py stops it when the stations change, or the media
# share goes away).
#
# mpv draws straight to the screen. While the server has a pay-per-view (web) station, FieldStation42's browser needs X: a
# bare X server is started here (no desktop, no window manager), mpv draws in it, and it is stopped again when there is no
# web station any more. X needs /dev/tty0 and /dev/tty7 in the container's devices.
cd "${FS42_APP:-/app}"
LOG=/tmp/Xorg.0.log

x_up() { DISPLAY=:0 xset q >/dev/null 2>&1; }

start_x() {
  if ! x_up; then
    rm -f /tmp/.X0-lock /tmp/.X11-unix/X0
    Xorg :0 vt7 -nolisten tcp -noreset -nocursor -logfile "$LOG" >/dev/null 2>&1 &
    i=0
    until x_up; do
      i=$((i + 1))
      if [ $i -gt 40 ]; then
        echo "player: X did not start, so the pay-per-view station can't be shown. Does the container have /dev/tty0 and /dev/tty7 in its devices? From $LOG:"
        grep '(EE)' "$LOG" | tail -3
        return 1
      fi
      sleep 0.5
    done
  fi
  export DISPLAY=:0
  # the output: FS42_DRM_CONNECTOR (X calls HDMI-A-1 "HDMI-1"), else the first one connected; every other one off
  out=$(xrandr | awk -v want="${FS42_DRM_CONNECTOR:-}" -v alt="$(echo "${FS42_DRM_CONNECTOR:-}" | sed 's/^HDMI-A-/HDMI-/')" \
        '/ connected/ { if (!first) first = $1; if ($1 == want || $1 == alt) got = $1 } END { print got ? got : first }')
  case "${FS42_DRM_MODE:-}" in
    *x*) set -- --mode "${FS42_DRM_MODE%@*}"; [ "${FS42_DRM_MODE#*@}" != "$FS42_DRM_MODE" ] && set -- "$@" --rate "${FS42_DRM_MODE#*@}" ;;
    *) set -- --auto ;;
  esac
  xrandr --output "$out" "$@" --primary
  for o in $(xrandr | awk '/ connected/ {print $1}'); do [ "$o" = "$out" ] || xrandr --output "$o" --off; done
  xset s off -dpms s noblank
}

stop_x() {
  [ -f /tmp/.X0-lock ] || return 0
  kill "$(tr -d ' ' < /tmp/.X0-lock)" 2>/dev/null
  sleep 1
}

while true; do
  while [ ! -e runtime/client_ready ]; do sleep 2; done
  set -- $(python3 /opt/client/client.py --display)
  if [ "$1" = x11 ]; then
    if ! start_x; then sleep 30; continue; fi
    python3 /opt/client/client.py --fit
    [ -n "${2:-}" ] && export LIBVA_DRIVER_NAME="$2"
    export QTWEBENGINE_DISABLE_SANDBOX=1      # Chromium's sandbox can't run as root in a container (the page is the station's own)
  else
    stop_x
    unset DISPLAY LIBVA_DRIVER_NAME
  fi
  # its own process group, so the browser and mpv it started go with it when it stops
  setsid python3 field_player.py &
  pid=$!
  wait $pid
  kill -TERM -- -$pid 2>/dev/null
  sleep 1
done
