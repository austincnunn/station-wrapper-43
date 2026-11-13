"""Tests for firstrun.py: the test station on a new install. Run: python3 test_firstrun.py"""
import contextlib
import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import urllib.error

import build_channels as bc
import firstrun


class FakeConsole:
    stations_now = {}
    log = []
    unreachable = False

    def __init__(self, base):
        pass

    def stations(self):
        if FakeConsole.unreachable:
            raise urllib.error.URLError("refused")
        return dict(FakeConsole.stations_now)

    def ensure_station(self, conf, existing):
        FakeConsole.log.append(("save", conf))
        FakeConsole.stations_now[conf["network_name"]] = conf
        return "station created"

    def rebuild_catalog(self, name):
        FakeConsole.log.append(("rebuild", name))

    def add_day(self, name):
        FakeConsole.log.append(("day", name))


class FirstRunTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.config = os.path.join(self.root, "config")
        self.catalog = os.path.join(self.root, "catalog")
        os.makedirs(self.config)
        os.makedirs(self.catalog)
        FakeConsole.stations_now, FakeConsole.log, FakeConsole.unreachable = {}, [], False
        self.saved = (bc.Console, bc.add_first_day, bc.CONTAINER_CATALOG, firstrun.FLAG, firstrun.make_clip,
                      firstrun.WAIT_SECONDS, os.environ.get("FIRSTRUN_TEST_STATION"))
        self.real_weather, self.real_there = firstrun.add_weather_source, firstrun.weather_there
        self.weather_calls = []
        self.weather_there = True                           # is the ws4channels container beside us?
        firstrun.add_weather_source = lambda: (self.weather_calls.append(1), self.weather_there)[1]
        firstrun.weather_there = lambda: self.weather_there or bool(print("no 'ws4channels' container: COMPOSE_PROFILES=weather"))
        self.real_flag, firstrun.WEATHER_FLAG = firstrun.WEATHER_FLAG, os.path.join(self.config, ".weather-channel-done")
        os.environ.pop("WEATHER_CHANNEL", None)
        bc.Console = FakeConsole
        bc.CONTAINER_CATALOG = self.catalog
        firstrun.FLAG = os.path.join(self.config, ".test-station-done")
        self.clips = []
        firstrun.make_clip = lambda path: (self.clips.append(path), open(path, "w").write("clip"))
        firstrun.WAIT_SECONDS = 0
        os.environ.pop("FIRSTRUN_TEST_STATION", None)

    def tearDown(self):
        (bc.Console, bc.add_first_day, bc.CONTAINER_CATALOG, firstrun.FLAG, firstrun.make_clip,
         firstrun.WAIT_SECONDS, env) = self.saved
        firstrun.add_weather_source, firstrun.weather_there, firstrun.WEATHER_FLAG = self.real_weather, self.real_there, self.real_flag
        os.environ.pop("WEATHER_CHANNEL", None)
        if env is None:
            os.environ.pop("FIRSTRUN_TEST_STATION", None)
        else:
            os.environ["FIRSTRUN_TEST_STATION"] = env
        shutil.rmtree(self.root)

    def run_it(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            return firstrun.main(), buf.getvalue()

    def test_a_new_install_gets_channel_0_playing_a_test_card(self):
        code, out = self.run_it()
        self.assertEqual(code, 0)
        (op, conf), rebuild = FakeConsole.log[0], FakeConsole.log[1]
        self.assertEqual((op, conf["network_name"], conf["channel_number"]), ("save", "Test Pattern", 2))
        self.assertEqual(conf["network_type"], "loop")                           # one clip, repeated all day
        self.assertEqual(conf["content_dir"], "catalog/by-genre/Test Pattern")   # just the folder holding the clip
        self.assertNotIn("day_templates", conf)                                  # no slots, bumps or commercials to fit
        self.assertEqual(rebuild, ("rebuild", "Test Pattern"))
        # the days are added THROUGH the console (so its own pages show the schedule), several so it lasts a while
        self.assertEqual([e for e in FakeConsole.log if e[0] == "day"], [("day", "Test Pattern")] * firstrun.DAYS)
        self.assertGreaterEqual(firstrun.DAYS, 7)
        self.assertEqual(self.clips, [os.path.join(self.catalog, "by-genre", "Test Pattern", "test-pattern.mp4")])
        self.assertTrue(os.path.exists(firstrun.FLAG))
        self.assertIn("channel 2 (Test Pattern)", out)
        guide = FakeConsole.stations_now["Channel Guide"]                        # and the guide, with its default settings
        self.assertEqual((guide["channel_number"], guide["network_type"], guide["play_sound"]), (1, "guide", False))
        self.assertEqual(guide["wrapper_guide"], {"title": "Channel Guide", "hours": 3, "theme": "modern-blue", "music": ""})
        self.assertNotIn(("rebuild", "Channel Guide"), FakeConsole.log)          # drawn live: nothing to build
        self.assertIn("channel 1 (Channel Guide)", out)

    def test_each_first_start_station_has_its_own_switch(self):
        os.environ["FIRSTRUN_GUIDE_STATION"] = "0"
        try:
            self.run_it()
            self.assertEqual(list(FakeConsole.stations_now), ["Test Pattern"])
            FakeConsole.stations_now.clear()
            os.remove(firstrun.FLAG)
            os.environ["FIRSTRUN_GUIDE_STATION"] = "1"
            os.environ["FIRSTRUN_TEST_STATION"] = "0"
            self.run_it()
            self.assertEqual(list(FakeConsole.stations_now), ["Channel Guide"])
            self.assertEqual(self.clips, [os.path.join(self.catalog, "by-genre", "Test Pattern", "test-pattern.mp4")])    # only the first run made the clip
        finally:
            os.environ.pop("FIRSTRUN_GUIDE_STATION", None)

    def test_a_retry_after_a_half_made_start_still_finishes(self):
        FakeConsole.stations_now = {"Test Pattern": {"network_name": "Test Pattern", "channel_number": 0}}
        code, _ = self.run_it()
        self.assertEqual(code, 0)
        self.assertIn("Channel Guide", FakeConsole.stations_now)

    def test_it_runs_once_and_a_deleted_station_stays_deleted(self):
        self.run_it()
        FakeConsole.stations_now.clear()                    # the user deletes it in the console
        FakeConsole.log.clear()
        code, _ = self.run_it()
        self.assertEqual((code, FakeConsole.log), (0, []))

    def test_an_install_that_already_has_stations_is_left_alone(self):
        FakeConsole.stations_now = {"Mine": {"network_name": "Mine", "channel_number": 5}}
        code, out = self.run_it()
        self.assertEqual((code, FakeConsole.log, self.clips), (0, [], []))
        self.assertIn("already has 1 station", out)
        self.assertTrue(os.path.exists(firstrun.FLAG))      # and it never asks again, even if they delete theirs

    def test_the_weather_channel_is_off_unless_asked_for(self):
        code, out = self.run_it()
        self.assertEqual((code, self.weather_calls), (0, []))
        self.assertNotIn("eather", out)
        self.assertIn("Test Pattern", FakeConsole.stations_now)

    def test_switching_the_weather_channel_on_adds_it_once_on_a_new_install_or_an_old_one(self):
        os.environ["WEATHER_CHANNEL"] = "1"
        self.run_it()                                       # a new install: the two stations, then the weather channel
        self.assertEqual(len(self.weather_calls), 1)
        self.assertTrue(os.path.exists(firstrun.WEATHER_FLAG))
        self.run_it()
        self.assertEqual(len(self.weather_calls), 1)        # once: deleted on the Sources page, it stays deleted
        os.remove(firstrun.WEATHER_FLAG)
        FakeConsole.stations_now = {"Mine": {"network_name": "Mine", "channel_number": 5}}
        self.run_it()                                       # years later, with their own stations: asking for it is enough
        self.assertEqual(len(self.weather_calls), 2)
        os.environ["FIRSTRUN_TEST_STATION"] = "0"
        os.environ["FIRSTRUN_GUIDE_STATION"] = "0"
        os.remove(firstrun.WEATHER_FLAG)
        try:
            self.run_it()                                   # and it does not need the first-start stations switched on
        finally:
            os.environ.pop("FIRSTRUN_GUIDE_STATION", None)
        self.assertEqual(len(self.weather_calls), 3)

    def test_a_weather_channel_whose_containers_have_gone_says_how_to_start_them(self):
        os.environ["WEATHER_CHANNEL"] = "1"                 # a .env from before the profile, with the newer compose file
        self.run_it()
        self.assertNotIn("COMPOSE_PROFILES", self.run_it()[1])
        self.weather_there = False
        self.assertIn("COMPOSE_PROFILES=weather", self.run_it()[1])
        self.assertEqual(len(self.weather_calls), 1)        # and it is not added a second time

    def test_an_empty_switch_is_off(self):
        os.environ["WEATHER_CHANNEL"] = ""                  # what the compose file passes when no profile is on
        self.assertEqual((self.run_it()[0], self.weather_calls), (0, []))

    def test_with_no_weather_container_yet_it_tries_again_next_start(self):
        os.environ["WEATHER_CHANNEL"] = "1"                 # set in the wrapper's environment but not where compose reads it
        self.weather_there = False
        self.run_it()
        self.assertFalse(os.path.exists(firstrun.WEATHER_FLAG))
        self.weather_there = True
        self.run_it()
        self.assertEqual(len(self.weather_calls), 2)
        self.assertTrue(os.path.exists(firstrun.WEATHER_FLAG))

    def test_the_weather_source_is_added_once_and_only_beside_its_container(self):
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "fs42-tuner"))
        import iptv
        saved = (iptv.PATH, firstrun.WEATHER_STREAM, bc.restart_tuner, os.environ.get("FS42_TUNER_DIR"))
        restarts = []
        iptv.PATH = os.path.join(self.config, "sources.json")
        bc.restart_tuner = lambda container: restarts.append(container)
        os.environ["FS42_TUNER_DIR"] = os.path.dirname(iptv.__file__)
        firstrun.weather_there = self.real_there                # the real check, of a name that is not there
        try:
            firstrun.WEATHER_STREAM = "http://no-such-container.invalid:9798/stream/stream.m3u8"
            with contextlib.redirect_stdout(io.StringIO()) as out:
                self.assertFalse(self.real_weather())                   # a compose file without it: no dead channel
            self.assertIn("COMPOSE_PROFILES=weather", out.getvalue())       # it says how to start the container
            self.assertFalse(os.path.exists(iptv.PATH))
            firstrun.WEATHER_STREAM = "http://localhost:9798/stream/stream.m3u8"
            with contextlib.redirect_stdout(io.StringIO()) as out:
                self.assertTrue(self.real_weather())
            self.assertIn("Settings page", out.getvalue())
            [src] = iptv.Sources().all()
            self.assertEqual((src["type"], src["name"], src["base"], src["mode"], [c["url"] for c in src["channels"]]),
                             ("stream", "Weather", 3, "convert", [firstrun.WEATHER_STREAM]))
            self.assertEqual([c["number"] for c in iptv.Sources().plan(taken=("1", "2"))[0]], ["3"])
            self.assertEqual(restarts, [None])                          # the tuner is told to read its sources again
            self.assertTrue(self.real_weather())                        # already there: fine, and never a second copy
            self.assertEqual(len(iptv.Sources().all()), 1)
        finally:
            iptv.PATH, firstrun.WEATHER_STREAM, bc.restart_tuner, tuner_dir = saved
            if tuner_dir is None:
                os.environ.pop("FS42_TUNER_DIR", None)
            else:
                os.environ["FS42_TUNER_DIR"] = tuner_dir

    def test_it_can_be_switched_off(self):
        os.environ["FIRSTRUN_TEST_STATION"] = "0"
        os.environ["FIRSTRUN_GUIDE_STATION"] = "0"
        try:
            code, out = self.run_it()
        finally:
            os.environ.pop("FIRSTRUN_GUIDE_STATION", None)
        self.assertEqual((code, FakeConsole.log), (0, []))
        self.assertFalse(os.path.exists(firstrun.FLAG))     # switching it back on later still works

    def test_a_console_that_is_not_up_yet_is_retried_not_given_up_on(self):
        FakeConsole.unreachable = True
        code, out = self.run_it()
        self.assertEqual(code, 1)
        self.assertFalse(os.path.exists(firstrun.FLAG))
        self.assertIn("try again", out)

    def test_a_failure_is_reported_and_does_not_leave_the_flag_so_it_can_be_fixed(self):
        def boom(path):
            raise RuntimeError("ffmpeg could not make the test card")
        firstrun.make_clip = boom
        code, out = self.run_it()
        self.assertEqual(code, 78)
        self.assertIn("could not set up the first-start stations", out)
        self.assertFalse(os.path.exists(firstrun.FLAG))
        self.assertEqual(FakeConsole.log, [])                # no half-made station

    def test_an_existing_clip_is_kept_not_made_again(self):
        d = os.path.join(self.catalog, "by-genre", "Test Pattern")
        os.makedirs(d)
        open(os.path.join(d, "test-pattern.mp4"), "w").write("mine")
        self.run_it()
        self.assertEqual(self.clips, [])


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "needs ffmpeg")
class RealClipTest(unittest.TestCase):
    def test_the_pre_rendered_clip_in_the_image_is_used_when_it_is_there(self):
        d = tempfile.mkdtemp()
        asset = os.path.join(d, "asset.mp4")
        open(asset, "wb").write(b"PRERENDERED")
        saved, firstrun.ASSET = firstrun.ASSET, asset
        try:
            out = os.path.join(d, "t.mp4")
            firstrun.make_clip(out)
            self.assertEqual(open(out, "rb").read(), b"PRERENDERED")                       # copied, nothing rendered
        finally:
            firstrun.ASSET = saved
            shutil.rmtree(d)

    def test_the_clip_is_a_real_playable_video_with_sound(self):
        d = tempfile.mkdtemp()
        saved, firstrun.CLIP_SECONDS = firstrun.CLIP_SECONDS, 2
        try:
            path = os.path.join(d, "t.mp4")
            firstrun.make_clip(path)
            out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_name,width,height:format=duration",
                                  "-of", "default=nw=1", path], capture_output=True, text=True).stdout
            self.assertIn("codec_name=h264", out)
            self.assertIn("codec_name=aac", out)
            self.assertIn("width=640", out)
            self.assertAlmostEqual(float(out.split("duration=")[1].split()[0]), 2.0, delta=0.3)
            self.assertEqual(os.listdir(d), ["t.mp4"])         # no temp file left behind
        finally:
            firstrun.CLIP_SECONDS = saved
            shutil.rmtree(d)


if __name__ == "__main__":
    unittest.main()
