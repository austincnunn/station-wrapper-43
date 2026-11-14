"""The web viewer, end to end: viewer.py as it runs in its container, in front of a stand-in for the server; and the
dashboard's side of it (accounts and the switch) against the real server. Run: python3 test_viewers_http.py"""
import http.client
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import auth
import viewer
from test_auth_http import Client
from test_files_api import Server, free_port
from viewers import Viewers

ADMIN = "correct horse"                       # the dashboard's password: who may add viewers
# test values by name, not written beside a "password" key: the secret scan reads those as real ones
LONG, MUM, KID, WRONG = "long enough", "grown up tv", "cartoons please", "wrong words"
HERE = os.path.dirname(os.path.abspath(__file__))
GUIDE = """<?xml version="1.0"?><tv>
<channel id="a"><display-name>one</display-name><display-name>101</display-name><icon src="http://10.0.0.5:5004/logo/101.png" /></channel>
<channel id="b"><display-name>two</display-name><display-name>102</display-name><icon src="http://10.0.0.5:5004/logo/102.png" /></channel>
<programme channel="a" start="20260101000000 +0000" stop="20260101010000 +0000"><title>Grown up film</title></programme>
<programme channel="b" start="20260101000000 +0000" stop="20260101010000 +0000"><title>Cartoon</title></programme>
</tv>""".encode()
CHUNK = b"G" + b"\x00" * 187


class FakeServer(BaseHTTPRequestHandler):
    """What the viewer asks the real server for. Streams count themselves, so a test can see one being let go."""
    protocol_version = "HTTP/1.1"
    streams, agents = 0, []

    def log_message(self, *a):
        pass

    def _send(self, body, ctype="application/json", code=200):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        p = self.path
        if p == "/lineup.json":
            return self._send(json.dumps([{"GuideNumber": n, "GuideName": name, "URL": f"http://10.0.0.5:5004/auto/v{n}"}
                                          for n, name in (("101", "one"), ("102", "two"))]).encode())
        if p == "/xmltv.xml":
            return self._send(GUIDE, "application/xml")
        if p == "/system.json":
            return self._send(json.dumps({"video_kbps": 4000, "cpu": {"count": 8}, "memory": {"total": 1}}).encode())
        if p in ("/captions/101.json", "/captions/102.json"):
            return self._send(json.dumps({"eid": None, "tracks": []}).encode())
        if p.split("?")[0] == "/auto/v102":
            FakeServer.agents.append((p, self.headers.get("User-Agent")))
            FakeServer.streams += 1
            self.send_response(200)
            self.send_header("Content-Type", "video/mp2t")
            self.send_header("Connection", "close")
            self.end_headers()
            try:
                while True:
                    self.wfile.write(CHUNK * 20)
                    time.sleep(0.02)
            except OSError:
                pass
            finally:
                FakeServer.streams -= 1
                self.close_connection = True
            return
        self._send(b"no", "text/plain", 404)


class ViewerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.saved, auth.ITERATIONS = auth.ITERATIONS, 1000      # fast hashes: the count is stored with each hash
        cls.dir = tempfile.mkdtemp()
        cls.users = Viewers(os.path.join(cls.dir, "viewers.json"))
        cls.users.save("mum", MUM)
        cls.users.save("kid", KID, ["102"])
        cls.fake = ThreadingHTTPServer(("127.0.0.1", 0), FakeServer)
        cls.fake.daemon_threads = True
        threading.Thread(target=cls.fake.serve_forever, daemon=True).start()
        cls.port = free_port()
        cls.proc = subprocess.Popen(
            [sys.executable, "viewer.py"], cwd=HERE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            env={**os.environ, "FS42_SERVER": f"http://127.0.0.1:{cls.fake.server_address[1]}", "VIEWER_DIR": cls.dir,
                 "VIEWER_PORT": str(cls.port), "VIEWER_TRUSTED_PROXIES": "127.0.0.1", "VIEWER_MAX_STREAMS": "2",
                 "VIEWER_IDLE_SECONDS": "2", "VIEWER_RECHECK_SECONDS": "0.3"})
        for _ in range(150):
            try:
                socket.create_connection(("127.0.0.1", cls.port), timeout=0.2).close()
                return
            except OSError:
                time.sleep(0.2)
        raise RuntimeError("the viewer did not start")

    @classmethod
    def tearDownClass(cls):
        auth.ITERATIONS = cls.saved
        cls.proc.terminate()
        cls.proc.wait(timeout=5)
        cls.fake.shutdown()
        shutil.rmtree(cls.dir)

    def request(self, method, path, body=None, headers=None, raw=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        c.request(method, path, body=data, headers={"Content-Type": "application/json", **(headers or {})})
        r = c.getresponse()
        text = r.read().decode(errors="replace")
        c.close()
        try:
            return r.status, r, json.loads(text), text
        except ValueError:
            return r.status, r, None, text

    def login(self, user, password, **headers):
        code, resp, body, _ = self.request("POST", "/api/auth/login", {"user": user, "password": password}, headers)
        self.assertEqual(code, 200, body)
        cookie = (resp.getheader("Set-Cookie") or "").split(";")[0]
        self.assertTrue(cookie.startswith("sw43_viewer="), cookie)
        return {"Cookie": cookie}

    def get(self, path, who=None):
        return self.request("GET", path, headers=who)

    def stream(self, who, path="/auto/v102"):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        c.request("GET", path, headers=who)
        return c, c.getresponse()

    def settled(self, want):
        for _ in range(100):
            if FakeServer.streams == want:
                return True
            time.sleep(0.05)
        return False

    def test_without_a_session_only_the_login_page_answers(self):
        code, resp, _, _ = self.get("/")
        self.assertEqual((code, resp.getheader("Location")), (302, "/login.html"))
        for path in ("/login.html", "/login.js", "/app.css"):
            code, resp, _, _ = self.get(path)
            self.assertEqual(code, 200, path)
            self.assertEqual((resp.getheader("X-Content-Type-Options"), resp.getheader("X-Frame-Options"), resp.getheader("Referrer-Policy")),
                             ("nosniff", "DENY", "no-referrer"))
        self.assertEqual(self.get("/api/auth/status")[2], {"login": True, "viewer": True, "has_password": True, "setup_needed": False,
                                                           "authenticated": False, "user": None})
        for path in ("/lineup.json", "/xmltv.xml", "/auto/v102", "/captions/102.json", "/system.json", "/app.js", "/settings.html", "/api/settings"):
            self.assertEqual(self.get(path)[0], 401, path)
        self.assertEqual(self.request("HEAD", "/auto/v102")[0], 501)             # no stream address answers without a login
        self.assertEqual(self.get("/vendor/../viewer.py")[0], 404)
        self.assertEqual(self.get("/vendor/../../viewers.py")[0], 404)

    def test_wrong_names_and_passwords_do_not_get_in_and_a_post_must_be_small_json(self):
        for n, (user, pw) in enumerate((("kid", WRONG), ("nobody", KID), ("kid", ADMIN), (None, None))):
            code, _, body, _ = self.request("POST", "/api/auth/login", {"user": user, "password": pw}, {"X-Forwarded-For": f"9.9.9.{n}"})
            self.assertEqual((code, body), (401, {"error": "that name or password is not right"}))
        self.assertEqual(self.request("POST", "/api/auth/login", raw=b"user=kid", headers={"Content-Type": "application/x-www-form-urlencoded"})[0], 415)
        self.assertEqual(self.request("POST", "/api/auth/login", raw=b"{" + b" " * 20_000 + b"}")[0], 413)
        self.assertEqual(self.request("POST", "/api/auth/login", raw=b"[1]")[0], 400)
        self.assertEqual(self.get("/lineup.json", {"Cookie": "sw43_viewer=1.2.kid.3"})[0], 401)
        self.assertIn("; Secure", self.request("POST", "/api/auth/login", {"user": "kid", "password": KID},
                                               {"X-Forwarded-Proto": "https"})[1].getheader("Set-Cookie"))

    def test_wrong_passwords_are_counted_for_the_visitor_the_proxy_names(self):
        for _ in range(auth.FAIL_LIMIT):
            self.assertEqual(self.request("POST", "/api/auth/login", {"user": "kid", "password": WRONG}, {"X-Forwarded-For": "1.1.1.1"})[0], 401)
        code, _, body, _ = self.request("POST", "/api/auth/login", {"user": "kid", "password": KID}, {"X-Forwarded-For": "1.1.1.1"})
        self.assertEqual(code, 401)
        self.assertIn("wait", body["error"])
        self.login("kid", KID, **{"X-Forwarded-For": "8.8.8.8, 2.2.2.2"})        # another visitor is not held up

    def test_only_a_proxy_we_trust_is_believed_about_who_is_calling(self):
        class Asked:
            def __init__(self, peer, forwarded):
                self.client_address, self.headers = (peer, 1), {"X-Forwarded-For": forwarded}
        saved, viewer.TRUSTED = viewer.TRUSTED, [viewer.ipaddress.ip_network("10.0.0.0/24")]
        try:
            who = lambda peer, fwd: viewer.Handler._who(Asked(peer, fwd))
            self.assertEqual(who("203.0.113.9", "1.2.3.4"), "203.0.113.9")       # not our proxy: its header is its own story
            self.assertEqual(who("10.0.0.2", "1.2.3.4"), "1.2.3.4")
            self.assertEqual(who("10.0.0.2", "6.6.6.6, 1.2.3.4, 10.0.0.7"), "1.2.3.4")   # the last hop that is not ours
            self.assertEqual(who("10.0.0.2", ""), "10.0.0.2")
            self.assertEqual(who("10.0.0.2", "not an address"), "10.0.0.2")
        finally:
            viewer.TRUSTED = saved

    def test_a_viewer_gets_the_player_and_only_their_channels(self):
        kid = self.login("Kid", KID)
        code, resp, _, page = self.get("/", kid)
        self.assertEqual(code, 200)
        self.assertIn('data-page="" data-viewer="kid"', page)                  # no dashboard bar, and a Log out for them
        self.assertEqual(self.get("/lineup.json", kid)[2], [{"GuideNumber": "102", "GuideName": "two"}])   # and no private address
        code, resp, _, guide = self.get("/xmltv.xml", kid)
        self.assertEqual((code, resp.getheader("Cache-Control")), (200, "no-store"))
        self.assertIn("Cartoon", guide)
        for private in ("Grown up film", ">101<", "<icon", "10.0.0.5"):
            self.assertNotIn(private, guide)
        for path in ("/auto/v101", "/auto/v101?kbps=1000", "/captions/101.json", "/captions/101/x/0.vtt"):
            self.assertEqual(self.get(path, kid)[0], 403, path)
        self.assertEqual(self.get("/captions/102.json", kid)[2], {"eid": None, "tracks": []})
        self.assertEqual(self.get("/system.json", kid)[2], {"video_kbps": 4000})
        self.assertEqual(self.get("/api/auth/status", kid)[2]["user"], "kid")

        mum = self.login("mum", MUM)
        self.assertEqual([r["GuideNumber"] for r in self.get("/lineup.json", mum)[2]], ["101", "102"])
        guide = self.get("/xmltv.xml", mum)[3]
        self.assertIn("Grown up film", guide)
        self.assertNotIn("10.0.0.5", guide)
        self.assertEqual(self.get("/captions/101.json", mum)[0], 200)
        self.assertEqual(self.get("/auto/v999", mum)[0], 404)                  # the server has no such channel

    def test_nothing_else_answers_here(self):
        mum = self.login("mum", MUM)
        for path in ("/settings.html", "/stations.html", "/index.html", "/status.json", "/channels.json", "/library.json", "/discover.json",
                     "/api/settings", "/api/viewers", "/sync/hello", "/lineup.m3u", "/settings.js", "/viewers.js", "/viewer.py",
                     "/auto/v102/../../api/settings", "/captions/..%2f..%2fapi%2fsettings", "/auto/v"):
            self.assertEqual(self.get(path, mum)[0], 404, path)
        for path in ("/api/viewers/save", "/api/viewers/switch", "/api/auth/setup", "/api/auth/password", "/lineup.post"):
            self.assertEqual(self.request("POST", path, {"name": "x", "on": True}, mum)[0], 404, path)

    def test_a_stream_is_passed_on_capped_for_each_viewer_and_let_go_when_they_leave(self):
        self.assertTrue(self.settled(0))
        kid = self.login("kid", KID)
        c1, r1 = self.stream(kid, "/auto/v102?kbps=1500")
        self.assertEqual((r1.status, r1.getheader("Content-Type")), (200, "video/mp2t"))
        self.assertEqual(r1.read(188 * 3), CHUNK * 3)
        self.assertEqual(FakeServer.agents[-1], ("/auto/v102?kbps=1500", "sw43-web-viewer (kid)"))
        self.assertEqual(self.users.status()["watching"], [{"user": "kid", "channel": "102"}])     # told to the dashboard at once
        c2, r2 = self.stream(kid)
        self.assertEqual(r2.status, 200)
        code, _, body, _ = self.get("/auto/v102", kid)                         # the third: over this viewer's cap
        self.assertEqual(code, 429, body)
        mum = self.login("mum", MUM)
        c3, r3 = self.stream(mum)                                              # someone else's are their own
        self.assertEqual(r3.status, 200)
        self.assertTrue(self.settled(3))
        for r, c in ((r1, c1), (r2, c2), (r3, c3)):
            r.close()                                                          # the response holds the socket open too
            c.close()
        self.assertTrue(self.settled(0))                                       # the server's side was closed too
        for _ in range(60):
            if not self.users.status()["watching"]:
                break
            time.sleep(0.05)
        self.assertEqual(self.users.status()["watching"], [])
        self.assertGreater(self.users.status()["started"], time.time() - 600)
        c4, r4 = self.stream(kid)
        self.assertEqual(r4.status, 200)
        r4.close()
        c4.close()
        self.assertTrue(self.settled(0))

    def test_an_open_stream_ends_when_its_viewer_may_no_longer_watch(self):
        self.users.save("tmp", LONG, ["102"])
        tmp = self.login("tmp", LONG)
        c, r = self.stream(tmp)
        self.assertEqual(r.read(188), CHUNK)
        self.users.save("tmp", channels=["101"])                               # the channel is taken away
        ended = time.time() + 5
        while r.read(188 * 20) and time.time() < ended:
            pass
        self.assertLess(time.time(), ended)
        r.close()
        c.close()
        self.users.remove("tmp")
        self.assertEqual(self.get("/lineup.json", tmp)[0], 401)

    def test_log_out_ends_the_session_and_only_the_viewer_wrote_it_down(self):
        with open(self.users.path) as f:
            before = f.read()
        mum = self.login("mum", MUM)
        code, resp, _, _ = self.request("POST", "/api/auth/logout", {}, mum)
        self.assertEqual(code, 200)
        self.assertIn("Max-Age=0", resp.getheader("Set-Cookie"))
        self.assertEqual(self.get("/lineup.json", mum)[0], 401)
        with open(self.users.path) as f:
            self.assertEqual(f.read(), before)
        self.assertTrue(os.path.exists(os.path.join(self.dir, "sessions.json")))

    def test_switched_off_on_the_dashboard_it_tells_everyone_so_at_once(self):
        mum = self.login("mum", MUM)
        self.users.switch(False)
        try:
            for path, who in (("/login.html", None), ("/", mum), ("/lineup.json", mum), ("/api/auth/status", None)):
                code, _, _, text = self.get(path, who)
                self.assertEqual(code, 503, path)
                self.assertIn("switched off", text)
            self.assertEqual(self.request("POST", "/api/auth/login", {"user": "mum", "password": MUM})[0], 503)
        finally:
            self.users.switch(True)
        self.assertEqual(self.get("/lineup.json", mum)[0], 200)                # the session is still good

    def test_it_says_it_is_running_and_drops_a_connection_that_says_nothing(self):
        self.assertTrue(self.users.running())
        s = socket.create_connection(("127.0.0.1", self.port), timeout=10)
        began = time.time()
        self.assertEqual(s.recv(100), b"")                                     # closed by the viewer, not by us
        self.assertLess(time.time() - began, 6)
        s.close()


class DashboardTest(unittest.TestCase):
    """The server's side: the accounts and the switch, behind the dashboard's login. It runs no viewer itself."""

    @classmethod
    def setUpClass(cls):
        cls.root = tempfile.mkdtemp()
        os.makedirs(os.path.join(cls.root, "catalog", "by-genre"))
        cls.srv = Server(cls.root, extra={"channels": {"101": "one", "102": "two"}},
                         env={"DASHBOARD_LOGIN": "1", "FS42_SETTINGS": os.path.join(cls.root, "settings.json")})
        cls.dash = Client(cls.srv)
        code, resp, body, _ = cls.dash.request("POST", "/api/auth/setup", {"password": ADMIN})
        assert code == 200, body
        cls.admin = Client.session(resp)

    @classmethod
    def tearDownClass(cls):
        cls.srv.stop()
        shutil.rmtree(cls.root)

    def post(self, path, body):
        code, _, answer, _ = self.dash.request("POST", path, body, cookie=self.admin)
        return code, answer

    def test_viewers_and_the_switch_are_kept_in_the_folder_the_viewer_shares(self):
        for path, body in (("/api/viewers/save", {"name": "x", "password": LONG}), ("/api/viewers/switch", {"on": False})):
            self.assertEqual(self.dash.request("POST", path, body)[0], 401)
        self.assertEqual(self.dash.request("GET", "/api/viewers")[0], 401)
        self.assertEqual(self.post("/api/viewers/save", {"name": "mum", "password": MUM, "channels": None})[0], 200)
        self.assertEqual(self.post("/api/viewers/save", {"name": "kid", "password": KID, "channels": ["102"]})[0], 200)
        self.assertEqual(self.post("/api/viewers/save", {"name": "no good", "password": LONG})[0], 400)
        code, _, body, text = self.dash.request("GET", "/api/viewers", cookie=self.admin)
        self.assertEqual(code, 200)
        self.assertEqual((body["on"], body["running"]), (True, False))          # switched on, but no viewer container here
        self.assertEqual(body["users"], [{"name": "kid", "channels": ["102"]}, {"name": "mum", "channels": None}])
        self.assertEqual([c["number"] for c in body["channels"]], ["101", "102"])
        self.assertNotIn("pbkdf2", text)

        shared = Viewers(os.path.join(self.root, "viewers", "viewers.json"))    # what the viewer's container reads
        self.assertEqual(shared.user(shared.login("kid", KID)), "kid")
        self.assertEqual(self.post("/api/viewers/switch", {"on": "no"})[0], 400)
        self.assertEqual(self.post("/api/viewers/switch", {"on": False}), (200, {**body, "on": False}))
        self.assertFalse(shared.is_on())
        shared.beat()                                                          # the viewer's container shows up
        code, answer = self.post("/api/viewers/switch", {"on": True})
        self.assertEqual((answer["on"], answer["running"]), (True, True))
        shared.beat({"started": 1_700_000_000, "watching": [{"user": "kid", "channel": "102"}]})
        status = self.dash.request("GET", "/api/system/status", cookie=self.admin)[2]       # the Status tab's data
        self.assertEqual(status["web_viewer"], {"on": True, "running": True, "accounts": 2, "started": 1_700_000_000,
                                                "watching": [{"user": "kid", "channel": "102"}]})
        self.assertFalse([c for c in status["checks"] if "web viewer" in c["text"]])
        code, answer = self.post("/api/viewers/remove", {"name": "mum"})
        self.assertEqual((code, [u["name"] for u in answer["users"]]), (200, ["kid"]))

    def test_the_server_has_no_viewer_of_its_own_any_more(self):
        rows = [s["key"] for s in self.dash.request("GET", "/api/settings", cookie=self.admin)[2]["settings"]]
        self.assertIn("SYNC_ENABLED", rows)
        self.assertEqual([k for k in rows if k.startswith("VIEWER")], [])
        self.assertEqual(self.dash.request("GET", "/watch.html")[0], 200)       # the dashboard's own player is as it was


if __name__ == "__main__":
    unittest.main()
