#!/usr/bin/env python3
"""Client mode: the channel bar along the bottom of the screen after each channel change, drawn by mpv itself.

It is the FS42 TV apps' bar (and the guide channel's "Cable box" style): bevelled grey boxes with the channel's number
and name, a green clock, and what is on now in a lavender box with blue type, in monospace type.

There is no X on a client (mpv draws straight to the screen), so FieldStation42's Qt on-screen display can't run. This
watches FieldStation42's runtime/play_status.socket and, when the channel changes, asks the server's /channels.json what
is on (the same now-playing the dashboard and the apps read; the server and this player play the same schedule), then
asks the player's mpv (through its own control socket, runtime/mpv.socket) to draw the bar as an OSD overlay, and to
take it away again after FS42_BANNER_SECONDS. With the server out of reach the bar still has the number and name.

  FS42_BANNER_SECONDS   how long it stays (default 8)
  FS42_BANNER=off       no bar
"""
import json
import os
import socket
import sys
import time
import urllib.request
from datetime import datetime

APP = os.environ.get("FS42_APP", "/app")
STATUS = os.path.join(APP, "runtime", "play_status.socket")
MPV = os.path.join(APP, "runtime", "mpv.socket")
OVERLAY = 42                      # the bar's id among mpv's OSD overlays

# the Cable box colours (fs42-tuner/guide_channel.py, THEMES["cable-box"]), as RGB
GREY, EDGE, LIGHT, PANEL = (201, 201, 201), (58, 58, 58), (242, 242, 242), (43, 43, 43)
LAVENDER, BLUE, BLUE_DIM = (180, 176, 242), (30, 30, 200), (60, 56, 140)
INK, CLOCK, CLOCK_FACE = (42, 42, 42), (80, 255, 80), (20, 20, 20)
FONT = "DejaVu Sans Mono"
CHAR = 0.6                        # a monospace character is about this many times the font size wide (a little over, to be safe)
H = 720                           # mpv's OSD is drawn 720 high; its width follows the screen's shape


def _c(rgb):
    """An ASS colour (&HBBGGRR&) from RGB."""
    return "&H%02X%02X%02X&" % (rgb[2], rgb[1], rgb[0])


def _rect(x, y, w, h, rgb):
    return f"{{\\an7\\pos({x},{y})\\bord0\\shad0\\1c{_c(rgb)}\\p1}}m 0 0 l {w} 0 {w} {h} 0 {h}{{\\p0}}"


def _box(x, y, w, h, face):
    """A raised box, as the guide's Cable box cells: dark bottom and right edge, light top and left edge, the face inside."""
    e = 3
    return [_rect(x, y, w, h, EDGE), _rect(x, y, w - e, h - e, LIGHT), _rect(x + e, y + e, w - 2 * e, h - 2 * e, face)]


def _text(x, y, an, size, rgb, s):
    s = " ".join(str(s).split()).replace("\\", "/").replace("{", "(").replace("}", ")")   # nothing ASS would read as a tag
    return f"{{\\an{an}\\pos({x},{y})\\fn{FONT}\\fs{size}\\bord0\\shad0\\1c{_c(rgb)}}}{s}"


def fit(s, width, size):
    """`s` cut off with … to what fits in `width` at font size `size` (monospace: every character is as wide)."""
    s = " ".join(str(s or "").split())
    room = int(width / (size * CHAR))
    return s if len(s) <= room else (s[:max(room - 1, 0)].rstrip() + "…" if room > 0 else "")


def bar(number, name, title, until, clock, w):
    """The bar's ASS events (one per line) for a screen `w` wide and 720 high."""
    m = round(w * 0.06)                           # in from the edges, inside what an old TV's overscan hides
    pw, ph = w - 2 * m, 112
    y0, p, gap = H - 36 - ph, 8, 6
    num_w, clock_w, row1, row2 = 120, 170, 44, 46
    name_x = m + p + num_w + gap
    name_w = pw - 2 * p - num_w - clock_w - 2 * gap
    clock_x = name_x + name_w + gap
    y1, y2 = y0 + p, y0 + p + row1 + gap
    ev = [_rect(m, y0, pw, ph, PANEL)]
    ev += _box(m + p, y1, num_w, row1, GREY) + [_text(m + p + num_w // 2, y1 + row1 // 2, 5, 36, INK, fit(number, num_w - 12, 36))]
    ev += _box(name_x, y1, name_w, row1, GREY) + [_text(name_x + 12, y1 + row1 // 2, 4, 30, INK, fit(name, name_w - 24, 30))]
    ev += _box(clock_x, y1, clock_w, row1, CLOCK_FACE) + [_text(clock_x + clock_w // 2, y1 + row1 // 2, 5, 30, CLOCK, clock)]
    now_w = pw - 2 * p
    ev += _box(m + p, y2, now_w, row2, LAVENDER)
    tail = f"until {until}" if until else ""
    if tail:
        ev.append(_text(m + p + now_w - 12, y2 + row2 // 2, 6, 24, BLUE_DIM, tail))
    room = now_w - 24 - (int(len(tail) * 24 * CHAR) + 24 if tail else 0)
    ev.append(_text(m + p + 12, y2 + row2 // 2, 4, 30, BLUE, fit(title or "", room, 30)))
    return "\n".join(ev)


def _hm(t):
    return t.strftime("%I:%M %p").lstrip("0")


def now_on(rows, name, number):
    """(title, until) for the channel from the server's /channels.json rows: by station name, else by number."""
    row = next((r for r in rows if r.get("station") == name), None) or \
        next((r for r in rows if str(r.get("channel")) == str(number)), None)
    now = (row or {}).get("now") or {}
    try:
        until = _hm(datetime.fromisoformat(now["block_end"])) if now.get("block_end") else ""
    except (TypeError, ValueError):
        until = ""
    return now.get("title") or "", until


def fetch_rows():
    base = os.environ.get("FS42_SERVER", "").strip().rstrip("/")
    if not base.startswith(("http://", "https://")):
        return []
    try:
        with urllib.request.urlopen(base + "/channels.json", timeout=2) as r:  # nosec B310: the server's own address, http(s) only
            rows = json.load(r)
        return rows if isinstance(rows, list) else []
    except (OSError, ValueError):
        return []


def mpv(*commands):
    """Send commands to the player's mpv; the reply to each, in order (an event mpv sends meanwhile is skipped)."""
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.settimeout(2)
        s.connect(MPV)
        f = s.makefile("rb")
        out = []
        for i, cmd in enumerate(commands):
            s.sendall((json.dumps({"command": cmd, "request_id": i + 1}) + "\n").encode())
            while True:
                reply = json.loads(f.readline() or b"{}")
                if reply.get("request_id") == i + 1 or not reply:
                    out.append(reply)
                    break
        return out


def show(number, name):
    title, until = now_on(fetch_rows(), name, number)
    dims = mpv(["get_property", "osd-dimensions"])[0].get("data") or {}
    w = round(H * dims["w"] / dims["h"]) if dims.get("w") and dims.get("h") else 960     # unknown: 4:3, which fits any screen
    mpv({"name": "osd-overlay", "id": OVERLAY, "format": "ass-events", "res_x": w, "res_y": H,
         "data": bar(number, name, title, until, _hm(datetime.now()), w)})


def hide():
    mpv({"name": "osd-overlay", "id": OVERLAY, "format": "none", "data": ""})


def current():
    try:
        with open(STATUS) as f:
            st = json.load(f)
        return st.get("channel_number"), st.get("network_name") or ""
    except (OSError, ValueError):
        return None, ""


def main():
    seconds = float(os.environ.get("FS42_BANNER_SECONDS", "8"))
    last, _ = current()
    hide_at = None
    while True:
        time.sleep(0.3)
        now, name = current()
        if now is not None and now != last:
            try:
                show(now, name)
                last, hide_at = now, time.monotonic() + seconds
            except (OSError, ValueError):
                pass                     # the player is starting: try again on the next look
        elif now is None:
            last = None
        if hide_at is not None and time.monotonic() >= hide_at:
            try:
                hide()
            except (OSError, ValueError):
                pass                     # the player restarted: the bar went with it
            hide_at = None


if __name__ == "__main__":
    if os.environ.get("FS42_BANNER", "").lower() in ("off", "0", "no", "false"):
        sys.exit(0)
    main()
