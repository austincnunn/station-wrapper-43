"""Client mode against a real /sync/ feed over HTTP. Run: python3 test_client.py"""
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
os.environ["FS42_APP"] = APP = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(HERE, "..", "fs42-tuner"))
import client  # noqa: E402
import playerconfs  # noqa: E402
from syncfeed import Feed  # noqa: E402

SRV = tempfile.mkdtemp()
CALLS = []


def server_tree():
    db = os.path.join(SRV, "fs42_fluid.db")
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE liquid_blocks (station TEXT, title TEXT, start_time TEXT, end_time TEXT, plan_json TEXT)")
    now = datetime.now()
    con.execute("INSERT INTO liquid_blocks VALUES (?, ?, ?, ?, ?)", ("Prime Country", "x", (now - timedelta(hours=1)).isoformat(),
                (now + timedelta(hours=2)).isoformat(), json.dumps([{"path": "catalog/by-genre/Prime/song.mp4", "content_type": "feature"}])))
    con.commit()
    con.close()
    os.makedirs(os.path.join(SRV, "confs"))
    json.dump({"station_conf": {"network_name": "Prime", "channel_number": 110, "network_type": "standard"}},
              open(os.path.join(SRV, "confs", "prime.json"), "w"))
    json.dump({"station_conf": {"network_name": "Guide", "channel_number": 4, "network_type": "guide", "wrapper_guide": {"aspect": "4:3"}}},
              open(os.path.join(SRV, "confs", "guide.json"), "w"))
    cat = os.path.join(SRV, "catalog", "by-genre", "Prime")
    os.makedirs(cat)
    os.makedirs(os.path.join(SRV, "media"))
    open(os.path.join(SRV, "media", "song.mp4"), "w").write("video")
    open(os.path.join(SRV, "media", "other.mp4"), "w").write("video")
    os.symlink(os.path.join(SRV, "media", "song.mp4"), os.path.join(cat, "song.mp4"))
    os.symlink(os.path.join(SRV, "media", "other.mp4"), os.path.join(cat, "gone.mp4"))
    open(os.path.join(cat, "song.nfo"), "w").write("<musicvideo/>")
    json.dump([{"id": "s1", "type": "m3u", "enabled": True, "numbers": {"yt": "107"},
                "channels": [{"key": "yt", "name": "YouTube", "url": "http://mtx/youtube.m3u8"}]}],
              open(os.path.join(SRV, "sources.json"), "w"))
    return Feed("tok", db, os.path.join(SRV, "confs"), os.path.join(SRV, "catalog"), os.path.join(SRV, "sources.json"),
                versions=client.my_versions())


FEED = server_tree()


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _go(self, method):
        u = urlparse(self.path)
        body = self.rfile.read(int(self.headers.get("Content-Length", "0") or 0)) if method == "POST" else b""
        CALLS.append(u.path)
        code, headers, data = FEED.handle(method, u.path, parse_qs(u.query), self.headers, body, "127.0.0.1")
        self.send_response(code)
        for k, v in headers:
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self._go("GET")

    def do_POST(self):
        self._go("POST")


HTTPD = ThreadingHTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=HTTPD.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{HTTPD.server_port}"


class ClientSync(unittest.TestCase):
    """One player's life, in order."""

    def test_sync(self):
        os.makedirs(client.RUNTIME, exist_ok=True)
        os.makedirs(client.CONFS, exist_ok=True)
        json.dump({"mine": True}, open(os.path.join(client.CONFS, "main_config.json"), "w"))
        srv, scr, state = client.Server(BASE, "tok"), client.screen({"FS42_SCREEN": "crt"}), {}

        # the first sync copies everything
        client.sync_once(srv, scr, state)
        self.assertEqual(sqlite3.connect(os.path.join(client.RUNTIME, "fs42_fluid.db")).execute("SELECT station FROM liquid_blocks").fetchall(),
                         [("Prime Country",)])
        link = os.path.join(client.CATALOG, "by-genre", "Prime", "song.mp4")
        self.assertEqual(os.readlink(link), os.path.join(SRV, "media", "song.mp4"))
        self.assertEqual(open(os.path.join(client.CATALOG, "by-genre", "Prime", "song.nfo")).read(), "<musicvideo/>")
        confs = sorted(os.listdir(client.CONFS))
        self.assertEqual(confs, ["guide.json", "main_config.json", "prime.json", "stream-s1-yt.json"])
        self.assertEqual(json.load(open(os.path.join(client.CONFS, "main_config.json"))), {"mine": True})       # this player's own
        guide = json.load(open(os.path.join(client.CONFS, "guide.json")))["station_conf"]
        self.assertEqual((guide["network_type"], guide["streams"][0]["url"], guide["panscan"]), ("streaming", f"{BASE}/auto/v4?kbps=1500", 1.0))
        self.assertEqual(json.load(open(os.path.join(client.CONFS, "prime.json")))["station_conf"]["panscan"], 1.0)
        self.assertEqual(json.load(open(os.path.join(client.CONFS, "stream-s1-yt.json")))["station_conf"]["channel_number"], 107)
        self.assertIsNone(client.media_problem(os.path.join(client.RUNTIME, "fs42_fluid.db")))

        # nothing changed: one cheap question, nothing fetched
        CALLS.clear()
        self.assertFalse(client.sync_once(srv, scr, state))
        self.assertEqual(CALLS, ["/sync/state"])

        # the server repoints a link, drops one, and changes a station: the player follows, and must restart
        os.remove(os.path.join(SRV, "catalog", "by-genre", "Prime", "gone.mp4"))
        os.remove(os.path.join(SRV, "catalog", "by-genre", "Prime", "song.mp4"))
        os.symlink(os.path.join(SRV, "media", "other.mp4"), os.path.join(SRV, "catalog", "by-genre", "Prime", "song.mp4"))
        json.dump({"station_conf": {"network_name": "Prime", "channel_number": 111, "network_type": "standard"}},
                  open(os.path.join(SRV, "confs", "prime.json"), "w"))
        FEED._cache.clear()
        self.assertTrue(client.sync_once(srv, scr, state))
        self.assertEqual(os.readlink(link), os.path.join(SRV, "media", "other.mp4"))
        self.assertFalse(os.path.lexists(os.path.join(client.CATALOG, "by-genre", "Prime", "gone.mp4")))

        # the share goes away: the player is told why
        shutil.move(os.path.join(SRV, "media"), os.path.join(SRV, "media-away"))
        try:
            self.assertIn("is the media share mounted", client.media_problem(os.path.join(client.RUNTIME, "fs42_fluid.db")))
        finally:
            shutil.move(os.path.join(SRV, "media-away"), os.path.join(SRV, "media"))

    def test_settings_from_the_server_are_kept_and_new_screen_settings_remake_the_streams(self):
        path = os.path.join(APP, "player-settings.json")
        FEED.player_settings = lambda name: {"FS42_GAMMA": "12"} if name == "crt" else {}
        srv = client.Server(BASE, "tok")
        self.assertTrue(client.keep_settings(srv.post("/sync/hello", {"name": "crt"}), path))
        self.assertEqual(json.load(open(path)), {"FS42_GAMMA": "12"})
        self.assertFalse(client.keep_settings(srv.post("/sync/hello", {"name": "crt"}), path))      # unchanged: not written
        self.assertFalse(client.keep_settings(None, path))                                           # an older server: kept
        self.assertTrue(client.keep_settings(srv.post("/sync/hello", {"name": "den"}), path))       # none: back to compose
        self.assertEqual(json.load(open(path)), {})
        os.makedirs(client.RUNTIME, exist_ok=True)
        os.makedirs(client.CONFS, exist_ok=True)
        state = {}
        client.sync_once(srv, client.screen({"FS42_SCREEN": "crt"}), state)
        CALLS.clear()
        client.sync_once(srv, client.screen({"FS42_SCREEN": "hd"}), state)
        self.assertIn("/sync/confs", CALLS)
        self.assertEqual(json.load(open(os.path.join(client.CONFS, "guide.json")))["station_conf"]["panscan"], 0.0)

    def test_a_wrong_token_is_refused(self):
        with self.assertRaises(Exception) as e:
            client.sync_once(client.Server(BASE, "wrong"), client.screen({}), {})
        self.assertEqual(getattr(e.exception, "code", None), 403)


class StopPlayer(unittest.TestCase):
    @unittest.skipUnless(os.path.isdir("/proc/self"), "needs /proc (Linux)")
    def test_the_player_is_stopped_without_pkill(self):
        import subprocess
        d = tempfile.mkdtemp()
        open(os.path.join(d, "field_player.py"), "w").write("import time\ntime.sleep(60)\n")
        proc = subprocess.Popen(["python3", "field_player.py"], cwd=d)
        time.sleep(0.5)
        client.stop_player()
        self.assertIsNotNone(proc.wait(timeout=5))


class Screen(unittest.TestCase):
    def test_profiles_and_overrides(self):
        crt, hd = client.screen({"FS42_SCREEN": "crt"}), client.screen({"FS42_SCREEN": "hd"})
        self.assertEqual((crt["panscan"], crt["kbps"], crt["mpv_profile"]), (1.0, 1500, "fast"))
        self.assertEqual((hd["panscan"], hd["kbps"], hd["mpv_profile"]), (0.0, 4000, "high-quality"))
        self.assertEqual(client.screen({"FS42_SCREEN": "crt", "FS42_PANSCAN": "0.5"})["panscan"], 0.5)
        self.assertEqual(client.screen({"FS42_STREAM_KBPS": "9000"})["kbps"], 4000)
        self.assertEqual(client.screen({"FS42_STREAM_KBPS": "100"})["kbps"], 500)
        self.assertEqual(client.screen({"FS42_SCREEN": "plasma"})["screen"], "hd")

    def test_mpv_draws_straight_to_the_screen(self):
        conf = client.mpv_conf(client.screen({"FS42_SCREEN": "crt"}), {"FS42_DRM_CONNECTOR": "VGA-1", "FS42_GAMMA": "10"})
        for line in ("vo=gpu", "gpu-context=drm", "drm-connector=VGA-1", "profile=fast", "gamma=10", "sid=no"):
            self.assertIn(line + "\n", conf)


class WebStations(unittest.TestCase):
    """A pay-per-view station needs X and a window the size of the screen."""

    def setUp(self):
        shutil.rmtree(client.CONFS, ignore_errors=True)
        os.makedirs(client.CONFS)
        json.dump({"station_conf": {"network_name": "News", "channel_number": 3, "network_type": "standard"}},
                  open(os.path.join(client.CONFS, "news.json"), "w"))

    def test_drm_until_a_web_station_comes(self):
        self.assertFalse(client.web_needed())
        json.dump({"station_conf": {"network_name": "PPV", "channel_number": 115, "network_type": "web", "web_url": "http://x"}},
                  open(os.path.join(client.CONFS, "ppv.json"), "w"))
        self.assertTrue(client.web_needed())
        self.assertEqual(client.fit(1024, 768), 1)
        self.assertEqual(client.fit(1024, 768), 0)                     # already that size: the file is left alone
        c = json.load(open(os.path.join(client.CONFS, "ppv.json")))["station_conf"]
        self.assertEqual((c["width"], c["height"], c["x"], c["y"], c["web_url"]), (1024, 768, 0, 0, "http://x"))
        self.assertNotIn("width", json.load(open(os.path.join(client.CONFS, "news.json")))["station_conf"])

    def test_mpv_in_x(self):
        conf = client.mpv_conf(client.screen({"FS42_SCREEN": "crt"}), {"FS42_DRM_CONNECTOR": "VGA-1", "FS42_GAMMA": "10"}, x11=True)
        for line in ("gpu-context=x11egl", "fullscreen=yes", "profile=fast", "gamma=10"):
            self.assertIn(line + "\n", conf)
        self.assertNotIn("drm", conf)

    def test_screen_size_and_vaapi_driver(self):
        self.assertEqual(client.screen_size("Screen 0: minimum 320 x 200, current 1024 x 768, maximum 8192 x 8192"), (1024, 768))
        probe = ("libva: Trying to open /usr/lib/x86_64-linux-gnu/dri/iHD_drv_video.so\nlibva: va_openDriver() returns 1\n"
                 "libva: Trying to open /usr/lib/x86_64-linux-gnu/dri/i965_drv_video.so\nlibva: va_openDriver() returns 0\n")
        old = os.environ.pop("LIBVA_DRIVER_NAME", None)
        try:
            self.assertEqual(client.vaapi_driver(probe), "i965")
            self.assertEqual(client.vaapi_driver("no gpu here"), "")
        finally:
            if old is not None:
                os.environ["LIBVA_DRIVER_NAME"] = old


class StreamConfs(unittest.TestCase):
    """What extras/remote-player/fs42-streams --test checked."""

    def test_plan(self):
        src = [{"id": "a1", "type": "m3u", "enabled": True, "mode": "convert", "numbers": {"ws": "47", "ws2": "48", "x": "2", "off": "49"},
                "overrides": {"ws2": {"name": "Weather Boston"}, "off": {"enabled": False}},
                "channels": [{"key": k, "name": k.upper(), "url": f"http://h/{k}.m3u8"} for k in ("ws", "ws2", "x", "off")]},
               {"id": "g", "mode": "guide", "channels": [{"key": "y", "name": "Y", "url": "u"}], "numbers": {"y": "60"}}]
        got = playerconfs.plan(src, {2}, set(), 0.0)
        self.assertEqual(sorted(c["station_conf"]["channel_number"] for c in got.values()), [47, 48])
        self.assertEqual(got["stream-a1-ws2.json"]["station_conf"]["network_name"], "Weather Boston")

    def test_a_16_9_guide_is_never_cropped_and_a_set_panscan_is_kept(self):
        g = playerconfs.guide_stream({"network_name": "G", "channel_number": 4}, "http://s:5004", 1.0)
        self.assertEqual((g["panscan"], g["streams"][0]["url"]), (0.0, "http://s:5004/auto/v4"))
        d = tempfile.mkdtemp()
        os.makedirs(os.path.join(d, "confs"))
        json.dump({"station_conf": {"network_name": "Mine", "channel_number": 9, "network_type": "standard", "panscan": 0.5}},
                  open(os.path.join(d, "confs", "mine.json"), "w"))
        playerconfs.write(d, [], "http://s", 1.0)
        self.assertEqual(json.load(open(os.path.join(d, "confs", "mine.json")))["station_conf"]["panscan"], 0.5)

    def test_a_station_playing_emby_videos_streams_from_the_server(self):
        d = tempfile.mkdtemp()
        db = os.path.join(d, "fs42_fluid.db")
        con = sqlite3.connect(db)
        con.execute("CREATE TABLE liquid_blocks (station TEXT, title TEXT, start_time TEXT, end_time TEXT, plan_json TEXT)")
        now = datetime.now()
        os.makedirs(os.path.join(d, "list"))
        os.symlink("/app/catalog/media-links/Emby/Srv/TV/Show/Season 01/Show - S01E01 - A.mkv", os.path.join(d, "list", "a.mkv"))
        for station, path in (("Friends", os.path.join(d, "list", "a.mkv")), ("Local", "/mnt/media/tv/x.mkv"),
                              ("Tunes", "/mnt/media/music/Band/Album/01 Song.FLAC")):        # a song: the server draws its card
            con.execute("INSERT INTO liquid_blocks VALUES (?, ?, ?, ?, ?)", (station, "x", now.isoformat(),
                        (now + timedelta(hours=1)).isoformat(), json.dumps([{"path": path, "content_type": "feature"}])))
        con.commit()
        con.close()
        self.assertEqual(client.server_stations(db), {"Friends", "Tunes"})
        os.makedirs(os.path.join(d, "confs"))
        for name, num in (("Friends", 120), ("Local", 121)):
            json.dump({"station_conf": {"network_name": name, "channel_number": num, "network_type": "standard"}},
                      open(os.path.join(d, "confs", f"{name}.json"), "w"))
        playerconfs.write(d, [], "http://s", 1.0, from_server={"Friends"})
        friends = json.load(open(os.path.join(d, "confs", "Friends.json")))["station_conf"]
        self.assertEqual((friends["network_type"], friends["streams"][0]["url"], friends["panscan"]), ("streaming", "http://s/auto/v120", 1.0))
        self.assertEqual(json.load(open(os.path.join(d, "confs", "Local.json")))["station_conf"]["network_type"], "standard")


if __name__ == "__main__":
    import warnings
    warnings.simplefilter("ignore", ResourceWarning)
    unittest.main()
