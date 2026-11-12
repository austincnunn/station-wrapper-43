"""Emby servers mirrored as placeholders (emby.py). Run: python3 test_emby.py"""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
import urllib.parse

import emby

EP = {"Type": "Episode", "Id": "e1", "Name": "Kamp Krusty", "SeriesName": "The Simpsons", "SeriesId": "s1",
      "ParentIndexNumber": 4, "IndexNumber": 1, "RunTimeTicks": 1325 * 10**7, "Overview": "Bart & Lisa go to camp.",
      "Chapters": [{"StartPositionTicks": 0}, {"StartPositionTicks": 600 * 10**7}]}
MOVIE = {"Type": "Movie", "Id": "m1", "Name": "Twister", "ProductionYear": 1996, "RunTimeTicks": 6780 * 10**7}


class FakeEmby:
    """Emby Connect plus one server (LAN address dead, internet address alive unless lan=True)."""
    def __init__(self, items, lan=True):
        self.items, self.lan, self.calls = items, lan, []

    def __call__(self, method, url, headers=None, data=None, timeout=20):
        self.calls.append((method, url, headers, data))
        u = urllib.parse.urlsplit(url)
        q = dict(urllib.parse.parse_qsl(u.query))
        if u.path.endswith("/user/authenticate"):
            form = dict(urllib.parse.parse_qsl(data.decode()))
            if form["rawpw"] != "secret":
                return 401, None
            return 200, {"AccessToken": "ctok", "User": {"Id": "cu1", "Name": "austin"}}
        if u.path.endswith("/servers"):
            assert headers["X-Connect-UserToken"] == "ctok"
            return 200, [{"SystemId": "sys1", "Name": "Friend's Emby", "Url": "https://far.example:8920",
                          "LocalAddress": "http://192.168.9.9:8096", "AccessKey": "akey"}]
        if u.hostname == "192.168.9.9" and not self.lan:
            raise emby.EmbyError("could not reach 192.168.9.9: timed out")
        if u.path.endswith("/Connect/Exchange"):
            assert headers["X-Emby-Token"] == "akey" and q["ConnectUserId"] == "cu1"
            return 200, {"LocalUserId": "lu1", "AccessToken": "stok"}
        assert headers["X-Emby-Token"] == "stok"
        if u.path.endswith("/Views"):
            return 200, {"Items": [{"Id": "lib1", "Name": "TV & Films", "CollectionType": "mixed"}]}
        if u.path.endswith("/Items"):
            start = int(q["StartIndex"])
            return 200, {"Items": self.items[start:start + int(q["Limit"])], "TotalRecordCount": len(self.items)}
        if "/Images/" in u.path:
            return 200, b"\xff\xd8poster"
        return 404, None


class EmbyTest(unittest.TestCase):
    def setUp(self):
        self.root = os.path.realpath(tempfile.mkdtemp())
        self.mirror = os.path.join(self.root, "media-links", "Emby")
        self.conf = os.path.join(self.root, "tuner", "emby.json")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def make(self, items, lan=True):
        fake = FakeEmby(items, lan)
        e = emby.Emby(self.conf, self.mirror, http=fake, log=lambda *a, **k: None)
        e.sign_in("austin", "secret")
        e.choose("sys1", on=True, libraries=["lib1"])
        return e, fake

    def test_wrong_password_is_refused_and_password_never_saved(self):
        e = emby.Emby(self.conf, self.mirror, http=FakeEmby([]))
        with self.assertRaises(emby.EmbyError):
            e.sign_in("austin", "nope")
        e.sign_in("austin", "secret")
        with open(self.conf) as f:
            text = f.read()
        self.assertNotIn("secret", text)
        self.assertEqual(os.stat(self.conf).st_mode & 0o777, 0o600)
        self.assertNotIn("akey", json.dumps(e.describe()))         # no keys or tokens on the page

    def test_json_is_read_whatever_it_is_labelled(self):
        self.assertEqual(emby.parse(b'{"AccessToken": "t"}', "text/html"), {"AccessToken": "t"})
        self.assertEqual(emby.parse(b" [1]", ""), [1])
        self.assertEqual(emby.parse(b"\xff\xd8jpeg", "image/jpeg"), b"\xff\xd8jpeg")
        self.assertEqual(emby.parse(b"<xml/>", "application/xml"), b"<xml/>")

    def test_names(self):
        self.assertEqual(emby.item_rel(EP, "S/L"), "S/L/The Simpsons/Season 04/The Simpsons - S04E01 - Kamp Krusty.mkv")
        self.assertEqual(emby.item_rel(MOVIE, "S/L"), "S/L/Twister (1996)/Twister (1996).mkv")
        self.assertEqual(emby.clean_name("AC/DC: Live?"), "AC DC Live")
        self.assertEqual(emby.clean_name("..."), "Untitled")
        self.assertIn("<showtitle>The Simpsons</showtitle>", emby.nfo(EP))
        self.assertIn("Bart &amp; Lisa", emby.nfo(EP))

    @unittest.skipUnless(shutil.which("ffprobe"), "needs ffmpeg")
    def test_sync_makes_placeholders_that_look_like_the_real_thing(self):
        e, _ = self.make([EP, MOVIE])
        self.assertEqual(e.sync()["made"], 2)
        show = os.path.join(self.mirror, "Friend's Emby", "TV & Films", "The Simpsons")
        stub = os.path.join(show, "Season 04", "The Simpsons - S04E01 - Kamp Krusty.mkv")
        probe = json.loads(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                                    "-show_chapters", "-of", "json", stub]))
        self.assertAlmostEqual(float(probe["format"]["duration"]), 1325, delta=1)
        self.assertEqual([round(float(c["start_time"])) for c in probe["chapters"]], [0, 600])
        self.assertLess(os.path.getsize(stub), 10000)
        self.assertTrue(os.path.exists(stub[:-4] + ".nfo"))
        self.assertTrue(os.path.exists(os.path.join(show, "poster.jpg")))
        self.assertEqual(e.lookup(stub), ("sys1", "e1"))
        self.assertIsNone(e.lookup("/mnt/media/tv/x.mkv"))
        self.assertEqual(e.sync()["kept"], 2)                         # nothing changed: nothing made again

        e2, _ = self.make([MOVIE])                                    # the episode is gone from the server
        self.assertEqual(e2.sync()["removed"], 1)
        self.assertFalse(os.path.exists(show))                       # its emptied folders (and poster) too
        self.assertIsNone(e2.lookup(stub))

    def test_a_still_for_the_dashboard_tile(self):
        e, fake = self.make([EP])
        e.libraries("sys1")                                           # any call: the server's token is in hand
        self.assertEqual(e.still("sys1", "e1"), b"\xff\xd8poster")
        self.assertIn("/Items/e1/Images/Backdrop?maxWidth=320", fake.calls[-1][1])
        self.assertIsNone(e.still("gone", "e1"))

    @unittest.skipUnless(shutil.which("ffprobe"), "needs ffmpeg")
    def test_unreachable_server_keeps_its_placeholders(self):
        e, fake = self.make([MOVIE])
        e.sync()
        fake.lan = False
        e.state["servers"]["sys1"].update(token=None, reach=None)
        fake.items = []
        broken = lambda *a, **k: (_ for _ in ()).throw(emby.EmbyError("down"))
        e.http = broken
        counts = e.sync()
        self.assertEqual(counts["removed"], 0)
        self.assertIn("down", e.status["error"])

    def test_lan_plays_the_file_internet_asks_for_a_capped_transcode(self):
        e, _ = self.make([])
        e._reach("sys1")
        got = e.input_for("sys1", "e1", 125.5)
        self.assertIn("/emby/Videos/e1/stream?static=true", got["url"])
        self.assertEqual(got["seek"], 125.5)
        self.assertNotIn("stok", got["url"])                          # the token is in a header, not the logged address
        self.assertIn("X-Emby-Token: stok", got["opts"][got["opts"].index("-headers") + 1])
        self.assertFalse(emby._safe_server_url("http://169.254.169.254/emby"))
        self.assertFalse(emby._safe_server_url("http://127.0.0.1:4242"))

        far, fake = self.make([], lan=False)
        far._reach("sys1")
        self.assertTrue(far.state["servers"]["sys1"]["remote"])
        got = far.input_for("sys1", "e1", 125.5)
        self.assertIn("https://far.example:8920/emby/Videos/e1/stream.ts?", got["url"])
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(got["url"]).query))
        self.assertEqual((q["VideoBitrate"], q["StartTimeTicks"]), (str(emby.REMOTE_CAP_KBPS * 1000), "1255000000"))
        self.assertEqual(got["seek"], 0.0)
        got["done"]()
        self.assertEqual(fake.calls[-1][0], "DELETE")

    def test_a_jellyfin_server_is_added_by_address_and_survives_emby_connect(self):
        def jf(method, url, headers=None, data=None, timeout=20):
            u = urllib.parse.urlsplit(url)
            if u.hostname != "192.168.7.7":
                return FakeEmby([])(method, url, headers, data, timeout)
            self.assertNotIn("/emby/", u.path)                        # Jellyfin has no /emby prefix
            if u.path == "/Users/AuthenticateByName":
                if json.loads(data)["Pw"] != "jfpass":
                    return 401, None
                return 200, {"AccessToken": "jtok", "ServerId": "abc123", "User": {"Id": "ju1"}}
            if u.path == "/System/Info/Public":
                return 200, {"ServerName": "Den"}
            self.assertIn('Token="jtok"', headers["Authorization"])
            self.assertNotIn("X-Emby-Token", headers)
            if u.path == "/Users/ju1/Views":
                return 200, {"Items": [{"Id": "jl1", "Name": "Movies", "CollectionType": "movies"}]}
            return 401, None                                          # everything else: the token went stale

        e = emby.Emby(self.conf, self.mirror, http=jf)
        with self.assertRaises(emby.EmbyError):
            e.add_jellyfin("192.168.7.7:8096", "austin", "wrong")
        with self.assertRaises(emby.EmbyError):
            e.add_jellyfin("http://169.254.169.254", "austin", "jfpass")
        got = e.add_jellyfin("192.168.7.7:8096/", "austin", "jfpass")["servers"]
        self.assertEqual([(s["id"], s["name"], s["kind"], s["cap_kbps"]) for s in got], [("jf-abc123", "Den", "jellyfin", 0)])
        with open(self.conf) as f:
            self.assertNotIn("jfpass", f.read())
        self.assertNotIn("jtok", json.dumps(e.describe()))
        self.assertEqual(e.libraries("jf-abc123")[0]["name"], "Movies")

        play = e.input_for("jf-abc123", "m1", 30)                     # cap 0: the original file, token in a header
        self.assertEqual(play["url"].split("?")[0], "http://192.168.7.7:8096/Videos/m1/stream")
        self.assertIn('Token="jtok"', play["opts"][play["opts"].index("-headers") + 1])
        e.choose("jf-abc123", cap_kbps=4000)
        self.assertIn("/Videos/m1/stream.ts?", e.input_for("jf-abc123", "m1", 30)["url"])

        e.sign_in("austin", "secret")                                 # Emby Connect comes and goes: Jellyfin stays as it is
        e.sign_out()
        jelly = e.state["servers"]["jf-abc123"]
        self.assertEqual((jelly["token"], jelly.get("gone")), ("jtok", False))
        with self.assertRaises(emby.EmbyError) as stale:              # a refused token asks for the server to be added again
            e._api("jf-abc123", "/Users/ju1/Items")
        self.assertIn("add this Jellyfin server again", str(stale.exception))
        with self.assertRaises(emby.EmbyError):
            e.remove("sys1")                                          # only Jellyfin servers are removed by hand
        self.assertEqual([s["id"] for s in e.remove("jf-abc123")["servers"]], ["sys1"])

    def test_cap_checks(self):
        e, _ = self.make([])
        with self.assertRaises(emby.EmbyError):
            e.choose("sys1", cap_kbps=50)
        e.choose("sys1", cap_kbps=0)
        self.assertEqual(e.describe()["servers"][0]["cap_kbps"], 0)


if __name__ == "__main__":
    unittest.main()
