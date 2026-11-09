#!/bin/bash
# ytcast: Xvfb + PulseAudio null sink + Firefox kiosk on youtube.com/tv, ffmpeg -> MediaMTX.
# Exits when Firefox or the ffmpeg loop dies; Docker's restart policy brings it back.
set -u
SCREEN=${SCREEN:-1280x720}       # what Firefox renders at (16:9; a 4:3 TV player can crop the sides)
OUT_SIZE=${OUT_SIZE:-854:480}    # what gets streamed (480 lines, plenty for an old TV)
FPS=${FPS:-60}                   # 60: one new picture per field on a CRT; 30 judders there
VIDEO_KBPS=${VIDEO_KBPS:-2500}
PUBLISH_URL=${PUBLISH_URL:?set PUBLISH_URL, e.g. rtsp://mediamtx:8554/youtube}
VAAPI_DEVICE=${VAAPI_DEVICE:-}   # e.g. /dev/dri/renderD128: encode on that Intel GPU; empty = x264 on the CPU
PROFILE=/profile

# The container starts as root only to fix the profile folder's owner (Docker creates a missing
# bind-mount folder as root, and Firefox can't use it then: "Firefox is already running"), and
# then runs everything else as user tv, in the GPU's group when VAAPI_DEVICE is set.
if [ "$(id -u)" = 0 ]; then
  chown tv:tv "$PROFILE"
  if [ -n "$VAAPI_DEVICE" ]; then groups=(--groups "$(stat -c %g "$VAAPI_DEVICE")"); else groups=(--clear-groups); fi
  HOME=/home/tv USER=tv exec setpriv --reuid=tv --regid=tv "${groups[@]}" "$0" "$@"
fi

if [ -n "$VAAPI_DEVICE" ]; then
  HW=(-vaapi_device "$VAAPI_DEVICE")
  VIDEO=(-vf "format=bgr0,hwupload,scale_vaapi=w=${OUT_SIZE%:*}:h=${OUT_SIZE#*:}:format=nv12" -c:v h264_vaapi)
else
  HW=()
  VIDEO=(-vf "scale=$OUT_SIZE:flags=bicubic,format=yuv420p" -c:v libx264 -preset veryfast)
fi

export DISPLAY=:99
rm -f /tmp/.X99-lock
Xvfb :99 -screen 0 "${SCREEN}x24" -nolisten tcp &
for _ in $(seq 50); do xdpyinfo >/dev/null 2>&1 && break; sleep 0.2; done 2>/dev/null

# A container restart (not recreate) keeps /tmp: the old run's pid file can name a PID that Xvfb or
# Firefox now has, and PulseAudio then refuses to start ("already running"), leaving ffmpeg no audio input.
rm -rf /tmp/pulse-* "$HOME"/.config/pulse/*-runtime
pulseaudio -n -D --exit-idle-time=-1 \
  --load=module-native-protocol-unix --load="module-null-sink sink_name=tv rate=48000"
for _ in $(seq 50); do pactl info >/dev/null 2>&1 && break; sleep 0.2; done
pactl set-default-sink tv

# Profile lives on a volume so the phone pairing (YouTube's localStorage) survives restarts.
mkdir -p "$PROFILE/extensions"
cp /opt/youtube-tv.xpi "$PROFILE/extensions/{01912552-4c6b-78cd-89b7-24736bd98539}.xpi"
cat > "$PROFILE/user.js" <<'EOF'
user_pref("xpinstall.signatures.required", false);
user_pref("extensions.autoDisableScopes", 0);
user_pref("extensions.enabledScopes", 15);
user_pref("extensions.update.enabled", false);
user_pref("media.autoplay.default", 0);
user_pref("media.autoplay.blocking_policy", 0);
user_pref("browser.shell.checkDefaultBrowser", false);
user_pref("browser.sessionstore.resume_from_crash", false);
user_pref("browser.startup.homepage_override.mstone", "ignore");
user_pref("browser.aboutwelcome.enabled", false);
user_pref("datareporting.policy.dataSubmissionEnabled", false);
user_pref("toolkit.telemetry.reportingpolicy.firstRun", false);
user_pref("app.update.enabled", false);
user_pref("full-screen-api.warning.timeout", 0);
user_pref("browser.eme.ui.enabled", false);   // hide "enable DRM" bar; normal videos need none
user_pref("media.av1.enabled", false);        // YouTube then serves VP9, cheaper to decode in software
EOF
# sessionstore files make Firefox show an "Open previous tabs?" bar after a restart
rm -rf "$PROFILE/lock" "$PROFILE/.parentlock" "$PROFILE"/sessionstore*

# No window manager, so --kiosk alone leaves a 921x691 window: size it to the screen.
firefox-esr --kiosk --no-remote --profile "$PROFILE" --width "${SCREEN%x*}" --height "${SCREEN#*x}" "https://www.youtube.com/tv" &

(
  sleep 5
  while true; do
    # -progress: live counters (dup_frames, fps) in /tmp/ffmpeg-progress for troubleshooting.
    # -copyts: both inputs are stamped with the wall clock, so keep them on that one clock. Without it
    # ffmpeg zeroes each input at its own first packet; Pulse's first packet comes ~0.9 s after the
    # first screen grab, so video looked 0.9 s ahead of audio forever and ffmpeg's scheduler kept
    # pausing the grab to let audio catch up: ~10 real frames/s, the rest duplicated (choppy).
    # -output_ts_offset brings the epoch timestamps back to near zero for the output.
    ffmpeg -hide_banner -loglevel warning -progress /tmp/ffmpeg-progress -stats_period 10 -copyts "${HW[@]}" \
      -thread_queue_size 1024 -f x11grab -draw_mouse 0 -framerate "$FPS" -video_size "$SCREEN" -i :99 \
      -thread_queue_size 1024 -f pulse -use_wallclock_as_timestamps 1 -i tv.monitor \
      "${VIDEO[@]}" -r "$FPS" \
      -b:v "${VIDEO_KBPS}k" -maxrate "${VIDEO_KBPS}k" -bufsize "$((VIDEO_KBPS * 2))k" -g "$((FPS * 2))" \
      -af aresample=async=1 -c:a aac -b:a 160k -ar 48000 -ac 2 \
      -output_ts_offset "-$(date +%s)" -f rtsp -rtsp_transport tcp "$PUBLISH_URL"
    echo "ffmpeg exited ($?), retrying in 5 s" >&2
    sleep 5
  done
) &

wait -n
echo "a process died, exiting" >&2
exit 1
