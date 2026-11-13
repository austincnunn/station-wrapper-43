"""The Settings page's environment settings (envsettings.py). Run: python3 test_envsettings.py"""
import json
import os
import tempfile
import unittest

import envsettings as es
import settings


class EnvSettingsTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.old = settings.PATH
        settings.PATH = os.path.join(self.dir.name, "settings.json")

    def tearDown(self):
        settings.PATH = self.old
        self.dir.cleanup()

    def test_saved_beats_compose_beats_default_and_clearing_goes_back(self):
        compose = {"SYNC_INTERVAL_MINUTES": "60"}
        es.save({"SYNC_INTERVAL_MINUTES": 30, "FARM_ENABLED": False})
        rows = {r["key"]: r for r in es.describe("server", es.overlay("server"), compose)}
        self.assertEqual((rows["SYNC_INTERVAL_MINUTES"]["value"], rows["SYNC_INTERVAL_MINUTES"]["source"]), ("30", "saved"))
        self.assertEqual((rows["FARM_ENABLED"]["value"], rows["FARM_ENABLED"]["source"]), ("0", "saved"))
        self.assertEqual((rows["KEEPER_TOPUP_HOUR"]["value"], rows["KEEPER_TOPUP_HOUR"]["source"]), ("4", "default"))
        es.save({"SYNC_INTERVAL_MINUTES": ""})
        rows = {r["key"]: r for r in es.describe("server", es.overlay("server"), compose)}
        self.assertEqual((rows["SYNC_INTERVAL_MINUTES"]["value"], rows["SYNC_INTERVAL_MINUTES"]["source"]), ("60", "env"))
        self.assertEqual(es.overlay("server"), {"FARM_ENABLED": "0"})

    def test_bad_values_are_refused_and_nothing_is_saved(self):
        for bad in ({"SYNC_INTERVAL_MINUTES": 0}, {"SYNC_INTERVAL_MINUTES": "x"}, {"SYNC_REBUILD_HOUR": 24},
                    {"FARM_ENABLED": "maybe"}, {"PREFETCH_MAX_MB": True}, {"MEDIA_SERVER_URL": "ftp://x"},
                    {"MEDIA_SERVER_MEDIA_ROOT": "media"}, {"SYNC_INCLUDE": "a\nb"},
                    {"DASHBOARD_LOGIN": "0"}, {"MEDIA_SERVER_API_KEY": "k"}, {"FS42_GAMMA": 10}, {"PATH": "/x"}):
            with self.assertRaises(es.SettingsError, msg=bad):
                es.save(bad)
        self.assertFalse(os.path.exists(settings.PATH))

    def test_the_weather_place_is_a_zip_or_a_town_and_never_markup(self):
        for ok in ("20001", "Orlando, FL", "Coeur d'Alene, ID", "St. Louis, MO", "Winston-Salem, NC"):
            self.assertEqual(es.clean("WEATHER_LOCATION", ok), ok)
        self.assertIsNone(es.clean("WEATHER_LOCATION", "  "))        # empty: the channel asks for a place
        for bad in ('x"><script>', "a&kiosk=false", "http://evil.example/", "x" * 81, "line\nbreak"):
            with self.assertRaises(es.SettingsError):
                es.clean("WEATHER_LOCATION", bad)
        self.assertEqual(es.BY_KEY["WEATHER_LOCATION"]["restarts"], [])    # read live: saving restarts nothing

    def test_a_player_has_its_own_settings_and_checks_them(self):
        es.save_player("crt", {"FS42_SCREEN": "crt", "FS42_GAMMA": "12", "FS42_PANSCAN": 0.5})
        self.assertEqual(es.player_overlay("crt"), {"FS42_SCREEN": "crt", "FS42_GAMMA": "12", "FS42_PANSCAN": "0.5"})
        self.assertEqual(es.player_overlay("den"), {})
        for bad in ({"FS42_SCREEN": "tv"}, {"FS42_GAMMA": 101}, {"FS42_DRM_MODE": "big"}, {"FS42_DRM_CONNECTOR": "a b"},
                    {"FS42_SERVER": "http://x"}, {"SYNC_ENABLED": True}):
            with self.assertRaises(es.SettingsError, msg=bad):
                es.save_player("crt", bad)
        es.save_player("crt", {"FS42_SCREEN": None, "FS42_GAMMA": None, "FS42_PANSCAN": ""})
        self.assertEqual(settings.load()["players"], {})                 # an emptied player is dropped

    def test_a_hand_edited_file_is_cleaned_not_trusted(self):
        with open(settings.PATH, "w") as f:
            json.dump({"env": {"SYNC_INTERVAL_MINUTES": "abc", "FARM_INTERVAL_MINUTES": 10, "PATH": "/evil",
                               "FS42_GAMMA": "5"}}, f)
        self.assertEqual(es.overlay("server"), {"FARM_INTERVAL_MINUTES": "10"})
        player = os.path.join(self.dir.name, "player.json")
        with open(player, "w") as f:
            json.dump({"FS42_GAMMA": "5", "SYNC_ENABLED": "1", "FS42_SCREEN": "tv"}, f)
        self.assertEqual(es.overlay("client", player), {"FS42_GAMMA": "5"})
        self.assertEqual(es.overlay("client", os.path.join(self.dir.name, "none.json")), {})

    def test_the_compose_values_travel_with_the_environment(self):
        env = es.effective({"SYNC_INTERVAL_MINUTES": "60", "HOME": "/root"}, {"SYNC_INTERVAL_MINUTES": "5"}, "server")
        self.assertEqual(env["SYNC_INTERVAL_MINUTES"], "5")
        self.assertEqual(es.compose_env(env), {"SYNC_INTERVAL_MINUTES": "60"})
        self.assertEqual(es.compose_env({"FS42_GAMMA": "3"}), {"FS42_GAMMA": "3"})      # no overlay applied: env as is

    def test_secrets_are_never_described_only_whether_they_are_set(self):
        rows = es.describe("server", {}, {"MEDIA_SERVER_API_KEY": "s3cret"})
        self.assertNotIn("s3cret", json.dumps(rows))
        m = es.machine({"MEDIA_SERVER_API_KEY": "s3cret", "FS42_ROLE": "server", "DASHBOARD_EDIT": "0"})
        self.assertNotIn("s3cret", json.dumps(m))
        self.assertEqual(m["secrets"], {"DASHBOARD_PASSWORD": False, "MEDIA_SERVER_API_KEY": True, "FS42_SYNC_TOKEN": False})
        self.assertFalse(m["edit"])
        self.assertTrue(all(k not in es.BY_KEY for k in es.SECRETS))

    def test_the_time_zone_is_named_with_its_offset(self):
        import os, tempfile
        self.assertEqual(es.machine({"FS42_ROLE": "Client "})["role"], "client")
        self.assertRegex(es.time_zone({"TZ": "America/Chicago"}), r"^America/Chicago \(C[SD]T, UTC-0[56]:00\)$")
        self.assertEqual(es.time_zone({"TZ": "UTC"}), "UTC (UTC+00:00)")                       # the name is not said twice
        d = tempfile.mkdtemp()
        try:                                                    # no TZ: the zone /etc/localtime points at
            os.makedirs(os.path.join(d, "zoneinfo", "Europe"))
            open(os.path.join(d, "zoneinfo", "Europe", "London"), "w").close()
            os.symlink(os.path.join(d, "zoneinfo", "Europe", "London"), os.path.join(d, "localtime"))
            self.assertTrue(es.time_zone({}, localtime=os.path.join(d, "localtime")).startswith("Europe/London ("))
            with open(os.path.join(d, "timezone"), "w") as f:   # ... or the one /etc/timezone names
                f.write("Asia/Tokyo\n")
            self.assertTrue(es.time_zone({}, localtime=os.path.join(d, "nothing"), zonefile=os.path.join(d, "timezone")).startswith("Asia/Tokyo ("))
            nameless = es.time_zone({}, localtime=os.path.join(d, "nothing"), zonefile=os.path.join(d, "nothing"))
            self.assertRegex(nameless, r"UTC[+-]\d\d:\d\d\)$")                                 # never empty, never "(the container's)"
        finally:
            import shutil
            shutil.rmtree(d)

    def test_the_version_is_the_build_the_image_was_stamped_with(self):
        stamp = lambda ref, sha, built: es.build_stamp({"FS42_WRAPPER_REF": ref, "FS42_WRAPPER_SHA": sha, "FS42_WRAPPER_BUILT": built})
        self.assertEqual(stamp("dev-28e6a47", "28e6a47", "2026-11-13T04:31:02Z"), "dev build 28e6a47, 13 Nov 2026")
        self.assertEqual(stamp("main-28e6a47", "28e6a47" + "0" * 33, "unknown"), "main build 28e6a47")            # a full commit id is cut to 7
        self.assertEqual(stamp("v0.8.0", "28e6a47", "2026-12-01T00:00:00Z"), "v0.8.0 (28e6a47), 1 Dec 2026")       # a release
        self.assertIn("not stamped", stamp("dev", "unknown", "unknown"))                                         # an image built by hand
        self.assertIn("not stamped", es.build_stamp({}))
        self.assertEqual(es.machine({"FS42_WRAPPER_REF": "dev-abc1234", "FS42_WRAPPER_SHA": "abc1234"})["version"], "dev build abc1234")


if __name__ == "__main__":
    unittest.main()
