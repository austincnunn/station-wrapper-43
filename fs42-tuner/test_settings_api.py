"""The Settings page's API (/api/settings, /api/settings/player) on a real tuner. Run: python3 test_settings_api.py"""
import json
import os
import shutil
import tempfile
import unittest
import urllib.request

from test_files_api import Server


class SettingsApi(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.path = os.path.join(self.root, "settings.json")

    def tearDown(self):
        self.srv.stop()
        shutil.rmtree(self.root)

    def start(self, **env):
        self.srv = Server(self.root, env={"FS42_SETTINGS": self.path, "FS42_SYNC_TOKEN": "tok", "MEDIA_SERVER_API_KEY": "s3cret",  # pragma: allowlist secret
                                          "FS42_COMPOSE_ENV": json.dumps({"SYNC_INTERVAL_MINUTES": "60"}), **env})

    def test_save_a_server_and_a_player_setting_and_refuse_bad_ones(self):
        self.start()
        code, r = self.srv.get("/api/settings")
        self.assertEqual(code, 200)
        self.assertNotIn("s3cret", json.dumps(r))
        self.assertTrue(r["machine"]["secrets"]["MEDIA_SERVER_API_KEY"])
        rows = {s["key"]: s for s in r["settings"]}
        self.assertEqual((rows["SYNC_INTERVAL_MINUTES"]["value"], rows["SYNC_INTERVAL_MINUTES"]["source"]), ("60", "env"))

        code, r = self.srv.post("/api/settings", {"values": {"SYNC_INTERVAL_MINUTES": "30"}})
        self.assertEqual(code, 200)
        self.assertEqual({s["key"]: s["source"] for s in r["settings"]}["SYNC_INTERVAL_MINUTES"], "saved")
        self.assertEqual(json.load(open(self.path))["env"], {"SYNC_INTERVAL_MINUTES": "30"})
        self.assertEqual(self.srv.post("/api/settings", {"values": {"DASHBOARD_LOGIN": "0"}})[0], 400)
        self.assertEqual(self.srv.post("/api/settings", {"values": {"SYNC_INTERVAL_MINUTES": -1}})[0], 400)

        req = urllib.request.Request(self.srv.base + "/sync/hello", data=json.dumps({"name": "crt", "env": {"FS42_GAMMA": "10"}}).encode(),
                                     headers={"Authorization": "Bearer tok", "Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            self.assertEqual(json.load(resp), {"settings": {}})
        code, r = self.srv.post("/api/settings/player", {"name": "crt", "values": {"FS42_GAMMA": "12"}})
        self.assertEqual(code, 200)
        [p] = r["players"]
        gamma = {s["key"]: s for s in p["settings"]}["FS42_GAMMA"]
        self.assertEqual((gamma["value"], gamma["source"], gamma["env"]), ("12", "saved", "10"))
        with urllib.request.urlopen(req, timeout=10) as resp:
            self.assertEqual(json.load(resp), {"settings": {"FS42_GAMMA": "12"}})

    def test_the_number_of_encoders_can_be_set_without_the_config_file(self):
        self.start(MAX_ENCODERS="7")
        self.assertEqual(self.srv.get("/status.json")[1]["encoders"]["max"], 7)          # wins over the file's max_encoders
        row = {s["key"]: s for s in self.srv.get("/api/settings")[1]["settings"]}["MAX_ENCODERS"]
        self.assertEqual((row["restarts"], row["default"]), (["tuner"], ""))             # saved here, the supervisor restarts the tuner
        self.assertEqual(self.srv.post("/api/settings", {"values": {"MAX_ENCODERS": "9"}})[0], 200)
        self.assertEqual(json.load(open(self.path))["env"], {"MAX_ENCODERS": "9"})
        for bad in ("0", "65", "many"):
            self.assertEqual(self.srv.post("/api/settings", {"values": {"MAX_ENCODERS": bad}})[0], 400, bad)

    def test_without_it_the_config_file_decides_the_number_of_encoders(self):
        self.start()
        self.assertEqual(self.srv.get("/status.json")[1]["encoders"]["max"], 4)

    def test_the_weather_page_follows_the_place_saved_on_the_settings_page_without_a_restart(self):
        self.start()
        page = urllib.request.urlopen(self.srv.base + "/weather", timeout=10).read().decode()
        self.assertIn("No place is set yet", page)
        self.assertNotIn("<iframe", page)
        self.assertEqual(self.srv.get("/weather/where"), (200, {"url": ""}))
        self.assertEqual(self.srv.post("/api/settings", {"values": {"WEATHER_LOCATION": "Orlando, FL"}})[0], 200)
        want = "http://ws4kp:8080/?latLonQuery=Orlando%2C+FL&kiosk=true&viewMode=standard"
        self.assertEqual(self.srv.get("/weather/where"), (200, {"url": want}))
        page = urllib.request.urlopen(self.srv.base + "/weather", timeout=10).read().decode()
        self.assertIn(f'<iframe src="{want.replace("&", "&amp;")}"', page)
        self.assertIn("/weather/where", page)                                # the page looks again by itself
        self.assertEqual(self.srv.post("/api/settings", {"values": {"WEATHER_LOCATION": '"><script>'}})[0], 400)

    def test_the_weather_place_can_start_from_the_compose_file(self):
        self.start(FS42_COMPOSE_ENV=json.dumps({"WEATHER_LOCATION": "20001"}))
        self.assertIn("latLonQuery=20001&", self.srv.get("/weather/where")[1]["url"])

    def test_with_no_token_set_the_server_makes_one_and_shows_it_only_when_asked(self):
        self.start(FS42_SYNC_TOKEN="")
        code, r = self.srv.get("/api/settings")
        self.assertEqual((r["sync_on"], r["sync_token_from"], r["machine"]["secrets"]["FS42_SYNC_TOKEN"]), (True, "made", True))
        made = open(os.path.join(self.root, "sync-token")).read().strip()
        self.assertNotIn(made, json.dumps(r))
        code, t = self.srv.get("/api/settings/sync-token")
        self.assertEqual((code, t), (200, {"token": made, "from": "made"}))
        req = urllib.request.Request(self.srv.base + "/sync/hello", data=b'{"name": "crt"}', method="POST",
                                     headers={"Authorization": f"Bearer {made}", "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            self.assertEqual(resp.status, 200)

    def test_nothing_changes_when_editing_is_off(self):
        self.start(DASHBOARD_EDIT="0")
        self.assertFalse(self.srv.get("/api/settings")[1]["edit"])
        self.assertEqual(self.srv.post("/api/settings", {"values": {"SYNC_INTERVAL_MINUTES": "30"}})[0], 403)
        self.assertEqual(self.srv.post("/api/settings/player", {"name": "crt", "values": {"FS42_GAMMA": "1"}})[0], 403)
        self.assertEqual(self.srv.get("/api/settings/sync-token")[0], 403)
        self.assertFalse(os.path.exists(self.path))


if __name__ == "__main__":
    unittest.main()
