"""The words in the bottom right corner that say why a test pattern is on screen. Run: python3 test_overlay.py (needs ffmpeg)"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

os.environ.setdefault("FS42_TUNER_CONF", os.path.join(tempfile.mkdtemp(), "c.json"))
import json
json.dump({"db_path": "none.db", "catalog_root": tempfile.mkdtemp(), "channels": {}, "media_root": "/tmp", "port": 5099,
           "advertise_url": "http://127.0.0.1:5099"}, open(os.environ["FS42_TUNER_CONF"], "w"))
sys.argv = ["tuner.py"]
import tuner  # noqa: E402


class OverlayTest(unittest.TestCase):
    def test_the_text_goes_in_the_picture_filter_of_the_command(self):
        cmd = tuner.filler_cmd(5, "BAD FILE: a.mp4")
        vf = cmd[cmd.index("-vf") + 1]
        self.assertIn("drawtext=text='BAD FILE\\: a.mp4'", vf)
        self.assertIn("x=w-tw-30:y=h-th-30", vf)                          # bottom right
        self.assertEqual(tuner.filler_cmd(5)[tuner.filler_cmd(5).index("-vf") + 1].count("drawtext"), 0)

    def test_nothing_in_the_name_can_break_the_filter(self):
        vf = tuner.with_text(["ffmpeg", "-vf", "scale=1:1"], "it's 100%: a\\b;c,d")[2]
        self.assertEqual(vf.count("drawtext"), 1)
        self.assertNotIn("\\b", vf.split("text=")[1].split(":font")[0].replace("\\\\", ""))

    @unittest.skipUnless(shutil.which("ffmpeg"), "needs ffmpeg")
    def test_ffmpeg_accepts_it_and_makes_a_stream(self):
        for cmd in (tuner.filler_cmd(1, "NO FILE: it's here.mp4"), tuner.filler_cmd(1, "QUEUEING")):
            out = subprocess.run(cmd, capture_output=True, timeout=60)
            self.assertEqual(out.returncode, 0, out.stderr.decode()[-300:])
            self.assertGreater(len(out.stdout), 4000)

    @unittest.skipUnless(shutil.which("ffmpeg"), "needs ffmpeg")
    def test_a_picture_is_held_on_screen_with_the_reason_over_it(self):
        d = tempfile.mkdtemp()
        png = os.path.join(d, "brb.png")
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=blue:s=320x180", "-frames:v", "1", png], check=True)
        out = subprocess.run(tuner.still_cmd(png, 2, "NO COMMERCIAL"), capture_output=True, timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr.decode()[-300:])
        self.assertGreater(len(out.stdout), 4000)
        shutil.rmtree(d)


class CaptionSafetyTest(unittest.TestCase):
    def test_a_failing_caption_injector_is_dropped_and_the_stream_goes_on(self):
        class Boom:
            def feed(self, chunk):
                raise IndexError("a stream it did not expect")

        out, inject = tuner.caption_feed(Boom(), b"\x47" * 188, 3)
        self.assertEqual(out, b"\x47" * 188)                 # the chunk goes out untouched
        self.assertIsNone(inject)                            # and captions are off for the rest of the programme
        self.assertEqual(tuner.caption_feed(None, b"abc"), (b"abc", None))


class OffAirReasonTest(unittest.TestCase):
    class Entry:
        def __init__(self, path, kind): self.path, self.content_type = path, kind

    def test_a_programme_has_no_reason_and_the_off_air_video_always_has_one(self):
        self.assertIsNone(tuner.offair_reason("S", self.Entry("/m/Show.mp4", "feature"), "Show"))
        for e, title in ((self.Entry("/opt/assets/test-pattern.mp4", "feature"), "Show"), (self.Entry("/x/y.mp4", "off_air"), "Show"),
                         (self.Entry("/x/y.mp4", "feature"), "Offair")):
            self.assertEqual(tuner.offair_reason("S", e, title), "OFF AIR: NOTHING SCHEDULED")

    def test_lists_the_calendar_left_out_for_having_no_videos_are_named(self):
        import schedules
        d = tempfile.mkdtemp()
        old = schedules.PATH
        schedules.PATH = os.path.join(d, "schedules.json")
        try:
            import json
            json.dump({"stations": {}, "skipped": {"S": ["Toons", "Anime", "More"]}}, open(schedules.PATH, "w"))
            got = tuner.offair_reason("S", self.Entry("/x/y.mp4", "off_air"), "x")
            self.assertEqual(got, "NO VIDEOS IN: Anime, More +1")
        finally:
            schedules.PATH = old


class ChannelSurvivesTest(unittest.TestCase):
    def test_an_error_while_playing_puts_the_reason_on_screen_and_the_channel_goes_on(self):
        import threading
        ch = tuner.Channel.__new__(tuner.Channel)
        ch.stop, ch.station, ch.number, ch.now_playing = threading.Event(), "X", 3, ""
        ch.lock, ch.subs = threading.Lock(), set()
        ch.thread = threading.current_thread()                 # _run is what the channel's encoder thread runs
        piped = []
        calls = []

        def step():
            calls.append(1)
            if len(calls) == 1:
                raise KeyError("no such block")
            ch.stop.set()
        ch._step = step
        ch._pipe = lambda cmd, **k: piped.append(cmd)
        ch._run()
        self.assertEqual(len(calls), 2)                          # it carried on after the error
        text = " ".join(piped[0])
        self.assertIn("CHANNEL ERROR", text)
        self.assertIn("KeyError", text)


class PrimeTest(unittest.TestCase):
    def test_a_viewer_joining_a_channel_of_tiny_chunks_is_not_dropped(self):
        import threading
        ch = tuner.Channel(9, "X", tuner.EncoderPool(4))
        ch.thread = object()                                  # an encoder is "running": attach only has to replay
        for _ in range(5000):                                 # what a quiet picture looks like: thousands of small writes
            ch.prime.append(b"\x47" * 1316)
        sub = ch.attach()
        self.assertIsNotNone(sub)
        self.assertFalse(sub.dead.is_set())
        got = 0
        while not sub.q.empty():
            got += len(sub.q.get_nowait())
        self.assertEqual(got, 5000 * 1316)                    # all of it, nothing lost

    def test_a_stopped_encoders_last_read_does_not_reach_the_next_viewer(self):
        """The last viewer left: the replay was cleared while the encoder was still reading. What it read must not be
        replayed to the next viewer, who would get the old stream's timestamps first (Emby: audio "starting" 25s in)."""
        import threading
        ch = tuner.Channel(9, "X", tuner.EncoderPool(4))
        ch.thread = threading.current_thread()
        ch._broadcast(b"\x47" * 188)
        self.assertEqual(ch.prime_bytes, 188)                 # the running encoder's output is kept
        ch.thread = None                                      # _shutdown: no encoder now
        ch.prime.clear()
        ch.prime_bytes = 0
        ch._broadcast(b"\x47" * 188)                          # the stopped one's last read
        self.assertEqual((len(ch.prime), ch.prime_bytes), (0, 0))

    def test_an_old_encoder_neither_feeds_nor_hangs_up_on_a_newer_one_s_viewers(self):
        import threading
        ch = tuner.Channel(9, "X", tuner.EncoderPool(4))
        ch.thread = object()                                  # a newer encoder has started
        sub = tuner.Subscriber()
        ch.subs.add(sub)
        ch._broadcast(b"\x47" * 188)
        ch._run()                                             # the old one, finishing: stops at once
        self.assertTrue(sub.q.empty())                        # nothing of the old stream, and no hang-up (None)
        self.assertIn(sub, ch.subs)



class ClockTest(unittest.TestCase):
    """CONTINUOUS_TS: every piece of a channel carries on the timestamps, so time never goes backwards at a change."""
    def test_the_offset_goes_before_the_output_and_the_break_flag_goes(self):
        cmd = tuner.at_clock(tuner.filler_cmd(3), 125.5)
        i = cmd.index("-output_ts_offset")
        self.assertEqual(cmd[i + 1], "125.500")
        self.assertEqual(cmd[i + 2:i + 4], ["-f", "mpegts"])
        self.assertNotIn("+resend_headers+initial_discontinuity", cmd)
        self.assertEqual(tuner.at_clock(cmd, 9)[i + 1], "9.000")                  # once only

    @unittest.skipUnless(shutil.which("ffmpeg"), "needs ffmpeg")
    def test_two_pieces_in_a_row_only_go_forward(self):
        d = tempfile.mkdtemp()
        ts = os.path.join(d, "two.ts")
        with open(ts, "wb") as f:
            for offset in (0, 3.0 + tuner.TS_MARGIN):                             # the second starts where the clock got to
                f.write(subprocess.run(tuner.at_clock(tuner.filler_cmd(3), offset), capture_output=True, timeout=60).stdout)
        pts = [float(x.strip(",")) for x in subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                                                 "packet=pts_time", "-of", "csv=p=0", ts], capture_output=True, text=True).stdout.split()
               if x.strip(",") not in ("", "N/A")]
        self.assertGreater(len(pts), 20)
        self.assertGreater(pts[-1], 5)                                             # the second piece is later, not at 0
        self.assertTrue(all(b > a - 0.5 for a, b in zip(pts, pts[1:])), "time went backwards")      # B-frames aside


if __name__ == "__main__":
    unittest.main()
