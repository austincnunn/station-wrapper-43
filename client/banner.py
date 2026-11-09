#!/usr/bin/env python3
"""Client mode: the channel number in the top left corner after each channel change, drawn by mpv itself.

There is no X on a client (mpv draws straight to the screen), so FieldStation42's Qt on-screen display can't run. This
watches FieldStation42's runtime/play_status.socket and, when the channel changes, asks the player's mpv (through its own
control socket, runtime/mpv.socket) to show the number.

  FS42_BANNER_SECONDS   how long it stays (default 8)
  FS42_BANNER=off       no banner
"""
import json
import os
import socket
import sys
import time

APP = os.environ.get("FS42_APP", "/app")
STATUS = os.path.join(APP, "runtime", "play_status.socket")
MPV = os.path.join(APP, "runtime", "mpv.socket")


def text(number):
    # ASS: top left, big, green with a dark outline (the CRT's old banner colour)
    return "${osd-ass-cc/0}{\\an7\\pos(60,40)\\fs46\\bord3\\shad0\\1c&H50FF50&\\3c&H000000&}" + str(number)


def show(number, seconds):
    msg = json.dumps({"command": ["expand-properties", "show-text", text(number), int(seconds * 1000)]}) + "\n"
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.settimeout(2)
        s.connect(MPV)
        s.sendall(msg.encode())


def current():
    try:
        with open(STATUS) as f:
            st = json.load(f)
        return st.get("channel_number")
    except (OSError, ValueError):
        return None


def main():
    seconds = float(os.environ.get("FS42_BANNER_SECONDS", "8"))
    last = current()
    while True:
        time.sleep(0.3)
        now = current()
        if now is not None and now != last:
            try:
                show(now, seconds)
                last = now
            except OSError:
                pass                     # the player is starting: try again on the next look
        elif now is None:
            last = None


if __name__ == "__main__":
    if os.environ.get("FS42_BANNER", "").lower() in ("off", "0", "no", "false"):
        sys.exit(0)
    main()
