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
        self.srv = Server(self.root, env={"FS42_SETTINGS": self.path, "FS42_SYNC_TOKEN": "tok", "MEDIA_SERVER_API_KEY": "s3cret",
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

    def test_nothing_changes_when_editing_is_off(self):
        self.start(DASHBOARD_EDIT="0")
        self.assertFalse(self.srv.get("/api/settings")[1]["edit"])
        self.assertEqual(self.srv.post("/api/settings", {"values": {"SYNC_INTERVAL_MINUTES": "30"}})[0], 403)
        self.assertEqual(self.srv.post("/api/settings/player", {"name": "crt", "values": {"FS42_GAMMA": "1"}})[0], 403)
        self.assertFalse(os.path.exists(self.path))


if __name__ == "__main__":
    unittest.main()
