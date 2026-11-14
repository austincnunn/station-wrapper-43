#!/usr/bin/env python3
"""The channel-change cover: its snow and rolling-picture bitmaps, and when it goes up and comes down.
Run: python3 test_cover.py"""
import json
import os
import random
import socket
import tempfile
import threading
import time
import unittest

import cover


class Pictures(unittest.TestCase):
    def test_snow_is_a_field_bigger_than_the_screen(self):
        w, h = 64, 48
        field = cover.snow(w, h)
        self.assertEqual(len(field) % (w * 4), 0)
        self.assertTrue(set(field[3::4]) == {255})                          # opaque
        self.assertTrue(min(field[0::4]) >= 24 and max(field[0::4]) <= 224)  # no full white for the RF modulator
        rng = random.Random(1)
        for _ in range(200):
            off = cover.snow_offset(w, h, rng)
            self.assertEqual(off % 8, 0)                                    # on a pixel pair: the blocks stay whole
            self.assertLessEqual(off + w * h * 4, len(field))               # a whole screen after it
        self.assertNotEqual(cover.snow(w, h)[:w * 4], field[:w * 4])        # new snow each time it is made

    def test_roll_is_the_picture_twice_with_a_black_bar_between(self):
        w, h = 64, 48
        both = cover.roll(w, h)                                             # no picture yet: black, with the bar
        self.assertEqual(len(both), w * h * 4 * 2)
        offs = [cover.roll_offset(w, h, f) for f in range(cover.FPS)]
        self.assertEqual(offs[0], 0)
        self.assertTrue(all(0 <= o <= w * h * 4 and o % (w * 4) == 0 for o in offs))
        self.assertEqual(offs, sorted(offs))                                # it goes one way, a little each frame
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("no Pillow here (the image has it)")
        snap = os.path.join(tempfile.mkdtemp(), "last.png")
        Image.new("RGB", (160, 90), (255, 255, 255)).save(snap)             # a 16:9 picture for a 4:3 screen
        both = cover.roll(w, h, snap)
        row = w * 4
        self.assertEqual(both[10 * row], 204)                               # the picture, a little darker
        self.assertEqual(both[(h - 1) * row: (h + 1) * row:4], bytes(2 * w))  # the bar where the two meet
        self.assertEqual(both[(h + 10) * row], 204)


class FakeMpv:
    """Answers mpv's requests (osd-dimensions 64x48) and keeps every command; events are sent with event()."""

    def __init__(self):
        self.path = os.path.join(tempfile.mkdtemp(), "mpv.socket")
        self.srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.srv.bind(self.path)
        self.srv.listen()
        self.got, self.conn = [], None
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        try:
            self.conn, _ = self.srv.accept()
        except OSError:
            return
        for line in self.conn.makefile("rb"):
            req = json.loads(line)
            self.got.append(req["command"])
            data = {"w": 64, "h": 48} if req["command"] == ["get_property", "osd-dimensions"] else None
            self.conn.sendall(json.dumps({"request_id": req["request_id"], "error": "success", "data": data}).encode() + b"\n")

    def event(self, name):
        self.conn.sendall(json.dumps({"event": name}).encode() + b"\n")
        time.sleep(0.05)

    def names(self):
        return [c[0] for c in self.got]


class Covering(unittest.TestCase):
    def setUp(self):
        d = tempfile.mkdtemp()
        cover.STATUS = os.path.join(d, "play_status.socket")
        cover.SNOW, cover.ROLL, cover.SNAP = (os.path.join(d, n) for n in ("snow.bgra", "roll.bgra", "last.jpg"))
        self.tune(101)
        self.mpv = FakeMpv()

    def tune(self, number):
        with open(cover.STATUS, "w") as f:
            json.dump({"channel_number": number, "network_name": "x"}, f)

    def step(self, c):
        c.step()
        time.sleep(0.05)

    def test_up_at_a_channel_change_and_down_at_the_first_frame(self):
        c = cover.Cover("snow", self.mpv.path)
        self.step(c)
        self.assertEqual(self.mpv.got[:2], [["disable_event", "all"], ["enable_event", "playback-restart"]])
        self.assertNotIn("overlay-add", self.mpv.names())                   # nothing changed: nothing covered
        self.assertTrue(os.path.getsize(cover.SNOW) >= 64 * 48 * 4)
        self.mpv.event("playback-restart")                                  # the old channel's, before the change
        self.tune(102)
        self.step(c)
        self.step(c)
        self.assertEqual(self.mpv.names().count("overlay-add"), 2)
        add = [x for x in self.mpv.got if x[0] == "overlay-add"][0]
        self.assertEqual(add[1:5] + add[6:], [cover.OVERLAY, 0, 0, cover.SNOW, "bgra", 64, 48, 256])
        self.mpv.event("playback-restart")                                  # the new channel's first frame
        self.step(c)
        self.step(c)
        self.assertEqual(self.mpv.names()[-1], "overlay-remove")
        self.assertEqual(self.mpv.names().count("overlay-add"), 2)          # and no more after it

    def test_roll_takes_the_last_picture_and_never_covers_for_ever(self):
        c = cover.Cover("roll", self.mpv.path)
        self.step(c)
        self.assertIn(["screenshot-to-file", cover.SNAP, "video"], self.mpv.got)
        self.tune(103)
        c.step()
        self.assertTrue(os.path.getsize(cover.ROLL) == 64 * 48 * 4 * 2)
        c.since -= cover.LONGEST + 1                                         # mpv never said the picture came
        self.step(c)
        self.assertEqual(self.mpv.names()[-1], "overlay-remove")


if __name__ == "__main__":
    unittest.main()
