"""A channel of music videos is listed in half-hour blocks, not one 3-minute programme per song. Run: python3 test_guide_blocks.py"""
import unittest
from datetime import datetime, timedelta

from guide import _blocks

T0 = datetime(2026, 11, 9, 12, 0)


def vids(start, *minutes, title="Song"):
    out, t = [], start
    for i, m in enumerate(minutes):
        out.append({"title": f"{title} {i}", "subtitle": "Live", "start": t, "end": t + timedelta(minutes=m), "path": f"/v/{i}"})
        t += timedelta(minutes=m)
    return out


class Blocks(unittest.TestCase):
    def test_a_normal_channel_is_untouched(self):
        shows = vids(T0, 22, 22, 45, 3)
        self.assertIs(_blocks(shows, "Laugh Track"), shows)

    def test_songs_become_half_hour_blocks_named_after_the_channel(self):
        out = _blocks(vids(T0, *[4] * 30), "Prime Country")              # two hours of 4-minute songs
        self.assertEqual({b["title"] for b in out}, {"Prime Country"})
        self.assertEqual(len(out), 4)
        for a, b in zip(out, out[1:]):
            self.assertEqual(a["end"], b["start"])                         # no gaps, no overlaps
        self.assertTrue(all(timedelta(minutes=28) <= b["end"] - b["start"] <= timedelta(minutes=36) for b in out[:-1]))
        self.assertIn("12:04 Song 1 - Live", out[0]["desc"])
        self.assertNotIn("path", out[0])

    def test_a_concert_film_keeps_its_own_entry_and_no_crumbs_are_left(self):
        L = vids(T0, 4, 4, 4, 4, 4, 4, 4, 3) + vids(T0 + timedelta(minutes=31), 131, title="Film") + vids(T0 + timedelta(minutes=162), 4, 4, 4, 4, 4, 4, 4, 4)
        out = _blocks(L, "All Rush")
        self.assertEqual([b["title"] for b in out], ["All Rush", "Film 0", "All Rush", "All Rush"])
        self.assertEqual(out[0]["end"], out[1]["start"])                   # the 3-minute song before the film joins the block before it
        self.assertEqual([b["start"].strftime("%H:%M") for b in out[2:]], ["14:42", "15:02"])
        self.assertTrue(all(b["end"] - b["start"] >= timedelta(minutes=10) for b in out))


if __name__ == "__main__":
    unittest.main()
