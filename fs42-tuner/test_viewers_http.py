"""The web viewer's port, end to end against the real server: viewers log in there and get only their channels,
and nothing else of the dashboard answers on it. Run: python3 test_viewers_http.py"""
import os
import shutil
import tempfile
import unittest

from test_auth_http import Client
from test_files_api import Server, free_port, touch

ADMIN = "correct horse"                       # the dashboard's password: who may add viewers
# test values by name, not written beside a "password" key: the secret scan reads those as real ones
LONG, FIRST, SECOND = "long enough", "first words", "second words"


class ViewerPortTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = tempfile.mkdtemp()
        touch(os.path.join(cls.root, "media", "m", "a.mp4"))
        os.makedirs(os.path.join(cls.root, "catalog", "by-genre"))
        cls.viewer_port = free_port()
        cls.srv = Server(cls.root, extra={"channels": {"101": "one", "102": "two"}},
                         env={"DASHBOARD_LOGIN": "1", "FS42_SETTINGS": os.path.join(cls.root, "settings.json"),
                              "VIEWER_PORT": str(cls.viewer_port)})
        cls.dash = Client(cls.srv)
        cls.view = Client(cls.srv)
        cls.view.port = cls.viewer_port
        code, resp, body, _ = cls.dash.request("POST", "/api/auth/setup", {"password": ADMIN})
        assert code == 200, body
        cls.admin = Client.session(resp)
        for name, pw, chans in (("mum", "grown up tv", None), ("kid", "cartoons please", ["102"])):
            code, _, body, _ = cls.dash.request("POST", "/api/viewers/save", {"name": name, "password": pw, "channels": chans}, cookie=cls.admin)
            assert code == 200, body

    @classmethod
    def tearDownClass(cls):
        cls.srv.stop()
        shutil.rmtree(cls.root)

    def login(self, user, password):
        code, resp, body, _ = self.view.request("POST", "/api/auth/login", {"user": user, "password": password})
        self.assertEqual(code, 200, body)
        cookie = (resp.getheader("Set-Cookie") or "").split(";")[0]
        self.assertTrue(cookie.startswith("sw43_viewer="), cookie)
        return {"Cookie": cookie}

    def get(self, path, who=None):
        return self.view.request("GET", path, headers=who)

    def test_the_dashboard_lists_and_changes_viewers_only_when_logged_in(self):
        self.assertEqual(self.dash.request("GET", "/api/viewers")[0], 401)
        self.assertEqual(self.dash.request("POST", "/api/viewers/save", {"name": "x", "password": LONG})[0], 401)
        code, _, body, text = self.dash.request("GET", "/api/viewers", cookie=self.admin)
        self.assertEqual(code, 200)
        self.assertEqual(body["port"], self.viewer_port)
        self.assertEqual(body["users"], [{"name": "kid", "channels": ["102"]}, {"name": "mum", "channels": None}])
        self.assertEqual([c["number"] for c in body["channels"]], ["101", "102"])
        self.assertNotIn("pbkdf2", text)
        code, _, body, _ = self.dash.request("POST", "/api/viewers/save", {"name": "no good", "password": LONG}, cookie=self.admin)
        self.assertEqual(code, 400, body)

    def test_without_a_session_only_the_login_page_answers(self):
        code, resp, _, _ = self.get("/")
        self.assertEqual((code, resp.getheader("Location")), (302, "/login.html"))
        for path in ("/login.html", "/login.js", "/app.css"):
            self.assertEqual(self.get(path)[0], 200, path)
        self.assertEqual(self.get("/api/auth/status")[2], {"login": True, "viewer": True, "has_password": True, "setup_needed": False,
                                                           "authenticated": False, "user": None})
        for path in ("/lineup.json", "/xmltv.xml", "/auto/v102", "/captions/102.json", "/system.json", "/app.js", "/settings.html", "/api/settings"):
            self.assertEqual(self.get(path)[0], 401, path)

    def test_wrong_names_and_passwords_and_the_dashboards_own_session_do_not_get_in(self):
        for user, pw in (("kid", "wrong password"), ("nobody", "cartoons please"), ("kid", ADMIN), (None, None)):
            self.assertEqual(self.view.request("POST", "/api/auth/login", {"user": user, "password": pw})[0], 401)
        for cookie in (f"sw43_viewer={self.admin}", f"sw43_session={self.admin}"):
            self.assertEqual(self.get("/lineup.json", {"Cookie": cookie})[0], 401)
        kid = self.login("kid", "cartoons please")["Cookie"].split("=", 1)[1]
        self.assertEqual(self.dash.request("GET", "/api/viewers", cookie=kid)[0], 401)       # nor a viewer's on the dashboard

    def test_a_viewer_gets_the_player_and_only_their_channels(self):
        kid = self.login("Kid", "cartoons please")
        code, _, _, page = self.get("/", kid)
        self.assertEqual(code, 200)
        self.assertIn('data-page="" data-viewer="kid"', page)                  # no dashboard bar, and a Log out for them
        self.assertEqual([r["GuideNumber"] for r in self.get("/lineup.json", kid)[2]], ["102"])
        code, _, _, guide = self.get("/xmltv.xml", kid)
        self.assertEqual(code, 200)
        self.assertIn(">102<", guide)
        self.assertNotIn(">101<", guide)
        self.assertEqual(self.get("/auto/v101", kid)[0], 403)
        self.assertEqual(self.get("/auto/v101?kbps=1000", kid)[0], 403)
        self.assertEqual(self.get("/captions/101.json", kid)[0], 403)
        self.assertEqual(self.get("/captions/101/x/0.vtt", kid)[0], 403)
        self.assertEqual(self.get("/captions/102.json", kid)[0], 200)
        self.assertEqual(list(self.get("/system.json", kid)[2]), ["video_kbps"])
        self.assertEqual(self.get("/api/auth/status", kid)[2]["user"], "kid")

        mum = self.login("mum", "grown up tv")
        self.assertEqual([r["GuideNumber"] for r in self.get("/lineup.json", mum)[2]], ["101", "102"])
        self.assertIn(">101<", self.get("/xmltv.xml", mum)[3])
        self.assertEqual(self.get("/captions/101.json", mum)[0], 200)

    def test_nothing_else_of_the_dashboard_answers_here(self):
        mum = self.login("mum", "grown up tv")
        for path in ("/settings.html", "/stations.html", "/index.html", "/status.json", "/channels.json", "/library.json", "/discover.json",
                     "/api/settings", "/api/viewers", "/api/system/status", "/sync/hello", "/lineup.m3u", "/settings.js", "/viewers.js"):
            self.assertEqual(self.get(path, mum)[0], 404, path)
        for path in ("/api/viewers/save", "/api/auth/setup", "/api/auth/password", "/api/settings", "/lineup.post"):
            self.assertEqual(self.view.request("POST", path, {"name": "x", "password": LONG}, headers=mum)[0], 404, path)
        self.assertEqual(self.dash.request("GET", "/api/viewers", cookie=self.admin)[2]["users"][0]["name"], "kid")     # nothing was added

    def test_log_out_and_a_new_password_end_the_session(self):
        mum = self.login("mum", "grown up tv")
        code, resp, _, _ = self.view.request("POST", "/api/auth/logout", {}, headers=mum)
        self.assertEqual(code, 200)
        self.assertIn("Max-Age=0", resp.getheader("Set-Cookie"))
        self.assertEqual(self.get("/lineup.json", mum)[0], 401)

        self.dash.request("POST", "/api/viewers/save", {"name": "tmp", "password": FIRST, "channels": []}, cookie=self.admin)
        tmp = self.login("tmp", FIRST)
        self.assertEqual(self.get("/lineup.json", tmp)[2], [])
        self.dash.request("POST", "/api/viewers/save", {"name": "tmp", "password": SECOND, "channels": []}, cookie=self.admin)
        self.assertEqual(self.get("/lineup.json", tmp)[0], 401)
        tmp = self.login("tmp", SECOND)
        code, _, body, _ = self.dash.request("POST", "/api/viewers/remove", {"name": "tmp"}, cookie=self.admin)
        self.assertEqual((code, [u["name"] for u in body["users"]]), (200, ["kid", "mum"]))
        self.assertEqual(self.get("/lineup.json", tmp)[0], 401)


if __name__ == "__main__":
    unittest.main()
