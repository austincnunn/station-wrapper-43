#!/usr/bin/env python3
"""Client mode: covers the wait on a channel change with snow or a rolling picture, drawn by mpv itself.

On a channel change FieldStation42 puts a moment of noise on the old picture, then mpv loads the new channel, and the
screen stays black until its first frame comes (a second or two from the share, more from Emby). This fills that gap
the way an old TV would: from the moment FieldStation42's runtime/play_status.socket names the new channel until mpv
shows the new channel's first frame (its playback-restart event), it lays a full-screen picture over everything,
changed 15 times a second, through the player's mpv control socket (runtime/mpv.socket). FieldStation42's own noise
then fades from the new picture as before.

  FS42_CHANGE_COVER   off (default) | snow: an empty channel's snow | roll: the last picture rolling, as a TV that has
                      lost its vertical hold, with the black bar between frames going by

How it draws: mpv's overlay-add, a bitmap the size of the screen read from a file in /dev/shm (RAM). One file each:
snow is a field of noise a little bigger than the screen, shown from a different place each time; roll is the last
picture twice, one above the other with the black bar between, shown a little further down each time, so it goes round.
The last picture is a screenshot mpv takes of the video every half second while nothing is being covered.
"""
import json
import os
import random
import socket
import sys
import time

APP = os.environ.get("FS42_APP", "/app")
STATUS = os.path.join(APP, "runtime", "play_status.socket")
MPV = os.path.join(APP, "runtime", "mpv.socket")
SHM = os.environ.get("FS42_COVER_DIR", "/dev/shm")  # nosec B108: the player container's own RAM disk, not shared with the host
SNOW, ROLL, SNAP = (os.path.join(SHM, f"fs42-cover-{n}") for n in ("snow.bgra", "roll.bgra", "last.jpg"))
OVERLAY = 7                       # the cover's slot among mpv's overlay-add bitmaps (0-63)
FPS = 15
LONGEST = 10.0                    # never covers for longer than this, whatever mpv says
SNAP_EVERY = 0.5
ROLL_SECONDS = 1.0                # one whole turn of the rolling picture


def _bgra(grey=None, rgb=None):
    """BGRA pixels (alpha 255) from grey bytes, or from RGB bytes."""
    n = len(grey) if grey is not None else len(rgb) // 3
    px = bytearray(n * 4)
    if grey is not None:
        px[0::4] = px[1::4] = px[2::4] = grey
    else:
        px[0::4], px[1::4], px[2::4] = rgb[2::3], rgb[1::3], rgb[0::3]
    px[3::4] = b"\xff" * n
    return px


# grey 24-224: snow without the full white that over-modulates an RF modulator (see the CRT's picture settings)
_SNOW_LEVELS = bytes(24 + v * 200 // 255 for v in range(256))


def snow(w, h):
    """Noise in 2x2 blocks (an old TV's snow is coarse), as BGRA rows `w` wide and h + h//2 + 1 high: the screen's worth
    shown from any row pair and any pixel pair (snow_offset) looks like new snow."""
    rows = (h + h // 2 + 2) // 2
    out = bytearray()
    for _ in range(rows):
        half = random.randbytes(w // 2 + 1).translate(_SNOW_LEVELS)
        line = bytearray(len(half) * 2)
        line[0::2] = line[1::2] = half
        out += _bgra(grey=bytes(line[:w])) * 2          # each row twice: blocks two rows high
    return bytes(out)


def snow_offset(w, h, rng=random):
    """A byte offset into snow()'s field that leaves a whole screen after it, on a block boundary."""
    return rng.randrange(0, (h // 2) // 2) * 2 * w * 4 + rng.randrange(0, w // 2) * 8


def roll(w, h, snapshot=None):
    """The last picture (filling the screen, cropped to its shape, a little darker) twice, one above the other, with a
    black bar where they meet: BGRA rows `w` wide and 2h high. A window h rows high from row y shows the picture rolled."""
    try:
        from PIL import Image, ImageOps
        img = ImageOps.fit(Image.open(snapshot).convert("RGB"), (w, h)) if snapshot and os.path.isfile(snapshot) else None
    except (ImportError, OSError, ValueError):
        img = None
    rgb = img.point(lambda v: v * 4 // 5).tobytes() if img is not None else bytes(w * h * 3)
    both = _bgra(rgb=rgb) * 2
    row, half = w * 4, max(2, h // 24)            # the black bar: a twelfth of the screen high, across the join
    black = bytes(_bgra(grey=bytes(w)))
    for r in range(h - half, h + half):
        both[r * row:(r + 1) * row] = black
    return bytes(both)


def roll_offset(w, h, frame):
    """Where the screen's window starts in roll()'s two pictures for frame number `frame`: a whole turn every ROLL_SECONDS."""
    step = max(1, round(h / (FPS * ROLL_SECONDS)))
    return (frame * step) % h * w * 4


def current():
    """The channel number playing now, from FieldStation42's status file (None while it has none)."""
    try:
        with open(STATUS) as f:
            return json.load(f).get("channel_number")
    except (OSError, ValueError):
        return None


class Mpv:
    """One connection to the player's mpv for as long as it runs: mpv takes a client's overlays away when it
    disconnects. Only the playback-restart event (a new picture's first frame) is asked for."""

    def __init__(self, path=MPV):
        self.s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.s.settimeout(2)
        try:
            self.s.connect(path)
        except OSError:
            self.s.close()
            raise
        self.buf, self.req, self.restarted = b"", 0, False
        self.send("disable_event", "all")
        self.send("enable_event", "playback-restart")

    def send(self, *cmd):
        self.s.settimeout(2)                     # _read may have left the socket non-blocking
        self.req += 1
        self.s.sendall((json.dumps({"command": list(cmd), "request_id": self.req}) + "\n").encode())
        return self.req

    def _read(self, wait):
        self.s.settimeout(wait)
        try:
            chunk = self.s.recv(65536)
        except (socket.timeout, BlockingIOError):
            return []
        if not chunk:
            raise OSError("mpv closed the connection")
        self.buf += chunk
        *done, self.buf = self.buf.split(b"\n")
        out = [json.loads(x) for x in done if x.strip()]
        self.restarted |= any(m.get("event") == "playback-restart" for m in out)
        return out

    def get(self, prop):
        rid = self.send("get_property", prop)
        end = time.monotonic() + 2
        while time.monotonic() < end:
            for m in self._read(0.2):
                if m.get("request_id") == rid:
                    return m.get("data")
        raise OSError(f"mpv did not answer for {prop}")

    def first_frame(self):
        """Has a first frame been shown since the last time this was asked?"""
        self._read(0)
        seen, self.restarted = self.restarted, False
        return seen

    def close(self):
        self.s.close()


class Cover:
    """What the service does each 1/FPS second, apart from sleeping: watch for a channel change, cover until mpv shows
    the new channel, take the last picture now and then for `roll`."""

    def __init__(self, mode, mpv_path=MPV):
        self.mode, self.mpv_path = mode, mpv_path
        self.mpv = None
        self.size = None
        self.last = current()
        self.since = None                # when the cover went up (monotonic), or None
        self.frame = 0
        self.next_snap = 0.0

    def _connect(self):
        self.mpv = Mpv(self.mpv_path)
        dims = self.mpv.get("osd-dimensions") or {}
        size = (int(dims.get("w") or 0), int(dims.get("h") or 0))
        if min(size) <= 0:
            raise OSError("mpv has no screen yet")
        if size != self.size and self.mode == "snow":
            _write(SNOW, snow(*size))
        self.size = size

    def _show(self):
        w, h = self.size
        if self.mode == "snow":
            path, off = SNOW, snow_offset(w, h)
        else:
            path, off = ROLL, roll_offset(w, h, self.frame)
        self.mpv.send("overlay-add", OVERLAY, 0, 0, path, off, "bgra", w, h, w * 4)
        self.frame += 1

    def step(self):
        try:
            if self.mpv is None:
                self._connect()
            now = current()
            shown = self.mpv.first_frame()
            if now is not None and now != self.last:
                if self.mode == "roll":
                    _write(ROLL, roll(*self.size, SNAP))
                self.last, self.since, self.frame = now, time.monotonic(), 0
                shown = False                    # a first frame from before the change was the old channel's
            elif now is None:
                self.last = None
            if self.since is not None:
                if shown or time.monotonic() - self.since > LONGEST:
                    self.mpv.send("overlay-remove", OVERLAY)
                    self.since = None
                else:
                    self._show()
            elif self.mode == "roll" and time.monotonic() >= self.next_snap:
                self.mpv.send("screenshot-to-file", SNAP, "video")   # fails quietly with no picture: the last one stays
                self.next_snap = time.monotonic() + SNAP_EVERY
        except (OSError, ValueError):
            if self.mpv is not None:
                self.mpv.close()
            self.mpv, self.since = None, None    # the player restarted: its overlays went with it


def _write(path, data):
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)


def main():
    mode = os.environ.get("FS42_CHANGE_COVER", "off").strip().lower()
    if mode not in ("snow", "roll"):
        sys.exit(0)
    cover = Cover(mode)
    while True:
        cover.step()
        time.sleep(1 / FPS)


if __name__ == "__main__":
    main()
