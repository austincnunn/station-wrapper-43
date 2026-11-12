#!/usr/bin/env python3
"""The channel bar's text fitting, its now-playing lookup and its layout. Run: python3 test_banner.py"""
import re
import unittest

import banner


class TestBanner(unittest.TestCase):
    def test_fit(self):
        self.assertEqual(banner.fit("Friends", 300, 30), "Friends")
        cut = banner.fit("The One Where Everybody Finds Out", 180, 30)     # room for 10 characters
        self.assertEqual(cut, "The One W…")
        self.assertEqual(banner.fit("anything", 5, 30), "")

    def test_now_on(self):
        rows = [{"channel": "103", "station": "Cartoons", "now": {"title": "Looney Tunes", "block_end": "2026-11-12T20:30:00"}},
                {"channel": "107", "station": "iptv:107", "now": {"title": "Camera", "block_end": ""}},
                {"channel": "110", "station": "Off", "now": None}]
        self.assertEqual(banner.now_on(rows, "Cartoons", 3), ("Looney Tunes", "8:30 PM"))   # by name, whatever the number
        self.assertEqual(banner.now_on(rows, "Lobby cam", 107), ("Camera", ""))              # else by number
        self.assertEqual(banner.now_on(rows, "Off", 110), ("", ""))
        self.assertEqual(banner.now_on([], "Cartoons", 103), ("", ""))

    def test_bar_fits_the_screen(self):
        for w in (960, 1280):
            ev = banner.bar(103, "Cartoons {x}", "Looney Tunes", "8:30 PM", "8:05 PM", w).split("\n")
            for line in ev:
                self.assertNotIn("{x}", line)                              # the name can't open an ASS tag
                box = re.search(r"\\pos\((\d+),(\d+)\).*m 0 0 l (\d+) 0 \d+ (\d+)", line)
                if box:
                    x, y, bw, bh = map(int, box.groups())
                    self.assertTrue(0 <= x and x + bw <= w and y + bh <= banner.H - 30, line)
            text = "\n".join(ev)
            for part in ("103", "Cartoons", "Looney Tunes", "until 8:30 PM", "8:05 PM", banner._c(banner.LAVENDER)):
                self.assertIn(part, text)


if __name__ == "__main__":
    unittest.main()
