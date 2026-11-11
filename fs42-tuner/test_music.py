"""Songs on a channel (music.py, tuner.music_cmd): tags, covers, the card, and a song played over it.
Run: python3 test_music.py (the last test needs ffmpeg and Pillow)"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

os.environ.setdefault("FS42_TUNER_CONF", os.path.join(tempfile.mkdtemp(), "c.json"))
os.environ.setdefault("FS42_ART_CACHE", tempfile.mkdtemp())
json.dump({"db_path": "none.db", "catalog_root": tempfile.mkdtemp(), "channels": {}, "media_root": "/tmp", "port": 5098,
           "advertise_url": "http://127.0.0.1:5098", "video": {"vcodec": "libx264", "width": 640, "height": 360, "fps": 10}},
          open(os.environ["FS42_TUNER_CONF"], "w"))
sys.argv = ["tuner.py"]
import music  # noqa: E402
import titles  # noqa: E402

try:
    from PIL import Image
except ImportError:
    Image = None


def album(root, artist="The Band", name="Second Album (1999)"):
    d = os.path.join(root, artist, name)
    os.makedirs(d)
    return d


class MusicTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        music._probe.cache_clear()

    def test_a_song_without_tags_is_named_from_where_it_is_kept(self):
        d = album(self.root)
        song = os.path.join(d, "03 Some Song.mp3")
        open(song, "wb").write(b"not really an mp3")
        link = os.path.join(self.root, "list.mp3")               # a list's link: the real file's folders count
        os.symlink(song, link)
        self.assertEqual(music.tags(link), {"artist": "The Band", "title": "Some Song", "album": "Second Album",
                                            "year": "1999", "genre": ""})
        self.assertEqual(music.line(link), "The Band - Some Song")
        self.assertEqual(titles.parts_for(link), ("The Band - Some Song", None))
        self.assertEqual(titles.details_for(link), {"plot": "From Second Album (1999)", "year": 1999})
        self.assertTrue(music.is_audio("x/Y.FLAC") and not music.is_audio("x/y.mkv"))
        self.assertEqual(music._clean("1-03 Stand Back (Live).flac"), "Stand Back (Live)")

    def test_the_safe_box_is_the_middle_4_3_less_overscan(self):
        self.assertEqual(music.safe_box(1280, 720), (208, 36, 1072, 684))         # 4:3 is x 160..1120, then 5% each side
        self.assertEqual(music.safe_box(960, 720), (48, 36, 912, 684))            # already 4:3: overscan only

    def test_the_cover_in_the_album_folder_is_found(self):
        d = album(self.root)
        song = os.path.join(d, "01 A.flac")
        open(song, "wb").write(b"x")
        open(os.path.join(d, "Folder.jpg"), "wb").write(b"jpeg")
        self.assertEqual(music.cover(song), os.path.join(d, "Folder.jpg"))

    @unittest.skipUnless(Image is not None and shutil.which("ffmpeg"), "needs Pillow and ffmpeg")
    def test_a_song_plays_over_its_card(self):
        d = album(self.root, "Test Artist", "Test Album")
        song = os.path.join(d, "01 Tone.flac")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=f=440:d=6", "-metadata", "title=A Tone",
                        "-metadata", "artist=Sine Wave", "-metadata", "date=2001", song], check=True)
        self.assertEqual(music.tags(song)["title"], "A Tone")
        self.assertAlmostEqual(music.duration(song), 6, delta=0.2)
        import tuner
        card = os.path.join(self.root, "card.png")
        info = music.card(card, song, "Tunes", 116, "Next Band - Next Song", (tuner.W, tuner.H))
        self.assertEqual(Image.open(card).size, (tuner.W, tuner.H))
        bx, by, bw, bh = info["bar"]
        left, top, right, bottom = music.safe_box(tuner.W, tuner.H)
        self.assertTrue(left <= bx and bx + bw <= right and top <= by and by + bh <= bottom)       # inside the 4:3 safe box
        self.assertGreaterEqual(info["clock"][0], left)
        out = subprocess.run(tuner.music_cmd(card, song, 2, 3, info), capture_output=True, timeout=120)
        self.assertEqual(out.returncode, 0, out.stderr.decode()[-600:])
        ts = os.path.join(self.root, "out.ts")
        open(ts, "wb").write(out.stdout)
        probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type:format=duration", "-of", "json", ts],
                               capture_output=True, text=True).stdout
        got = json.loads(probe)
        self.assertEqual(sorted(s["codec_type"] for s in got["streams"]), ["audio", "video"])
        self.assertAlmostEqual(float(got["format"]["duration"]), 3, delta=0.5)


if __name__ == "__main__":
    unittest.main()
