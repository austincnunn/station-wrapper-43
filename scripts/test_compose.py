"""The compose files: ONE service, and they must say, and enforce, where things may live.

The catalog and the pool are folders of symlinks, so they must be on local disk and not an
SMB/CIFS share. These tests render the real compose files (skipped when `docker compose`
isn't available) and check the explicit statement is still there.

Run: python3 scripts/test_compose.py
"""
import json
import os
import subprocess
import unittest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
COMPOSE = os.path.join(ROOT, "docker-compose.yml")


def read(path):
    with open(path) as f:
        return f.read()


def render(file=COMPOSE, extra_files=(), **env):
    """docker compose config as JSON, ignoring the repo's own .env. Returns (config, error text)."""
    full = {k: v for k, v in os.environ.items() if not k.startswith("FS42_")}
    full.update({k: v for k, v in env.items() if v is not None})
    flags = [x for f in (file, *extra_files) for x in ("-f", f)]
    out = subprocess.run(["docker", "compose", "--env-file", "/dev/null", *flags, "config", "--format", "json"],
                         capture_output=True, text=True, env=full, cwd=ROOT)
    if out.returncode != 0:
        return None, out.stderr
    return json.loads(out.stdout), ""


def have_compose():
    try:
        return subprocess.run(["docker", "compose", "version"], capture_output=True).returncode == 0
    except OSError:
        return False


def mounts(cfg, svc="station-wrapper-43"):
    """{container path: (host path, read_only)} for a service."""
    return {v["target"]: (v["source"], bool(v.get("read_only"))) for v in cfg["services"][svc]["volumes"]}


class ComposeTextTest(unittest.TestCase):
    """The statements themselves, which need no Docker."""

    def test_the_header_says_the_catalog_is_not_for_smb(self):
        head = read(COMPOSE).split("name: station-wrapper-43")[0]
        self.assertIn("NOT an SMB/CIFS share", head)
        self.assertIn("LOCAL DISK", head)
        self.assertIn("SYMLINKS", head)
        self.assertIn("FS42_ALLOW_NETWORK_CATALOG", head)

    def test_the_header_says_it_is_one_image_one_container_three_volumes(self):
        head = read(COMPOSE).split("name: station-wrapper-43")[0]
        self.assertIn("ONE image, ONE container, THREE volumes", head)

    def test_the_header_describes_each_volume_and_what_is_in_it(self):
        head = read(COMPOSE).split("name: station-wrapper-43")[0]
        for needle in ("CONFIG", "CATALOG", "MEDIA", "runtime/", "confs/", "tuner/", "groups.toml", "by-genre/",
                       "media-links/", "FS42_LOCAL_ROOT", "recursive", "ONLY SOME FOLDERS"):
            self.assertIn(needle, head + read(COMPOSE))

    def test_the_catalog_volume_repeats_it(self):
        text = read(COMPOSE)
        volume = text[text.index("    volumes:"):text.index(":/app/catalog")]
        self.assertIn("MUST NOT be an SMB/CIFS share", volume)

    def test_the_container_refuses_rather_than_runs_broken(self):
        entry = read(os.path.join(ROOT, "fieldstation42", "entrypoint.sh"))
        self.assertIn("REFUSING TO START", entry)
        self.assertIn("exit 78", entry)



@unittest.skipUnless(have_compose(), "docker compose is not available")
class ComposeRenderTest(unittest.TestCase):
    BASE = dict(FS42_LOCAL_ROOT="/local", FS42_MEDIA_ROOT="/media")

    def cfg(self, **env):
        config, err = render(**{**self.BASE, **env})
        self.assertIsNotNone(config, err)
        return config

    def test_it_is_one_service_with_one_image(self):
        config = self.cfg()
        self.assertEqual(sorted(config["services"]), ["station-wrapper-43"])     # the two weather ones are behind a profile
        svc = config["services"]["station-wrapper-43"]
        self.assertEqual(svc["image"], "ghcr.io/austincnunn/station-wrapper-43:latest")
        self.assertEqual(svc["container_name"], "station-wrapper-43")
        self.assertNotIn("build", svc)      # a lone compose file must start: with build: a missing image is BUILT, not pulled

    def test_the_weather_channel_is_two_unpublished_containers_off_until_asked_for(self):
        off, on = self.cfg()["services"], self.cfg(COMPOSE_PROFILES="weather")["services"]
        for name in ("ws4kp", "ws4channels"):
            # Off, they are not in the project at all: at scale 0 Compose still downloaded their images, and an ARM
            # machine can't run ws4channels.
            self.assertNotIn(name, off)
            self.assertNotIn("ports", on[name])                     # only the wrapper talks to them
            self.assertNotIn("build", on[name])
            self.assertEqual(on[name]["profiles"], ["weather"])
        self.assertEqual(on["ws4channels"]["environment"]["PERMALINK_URL"], "http://station-wrapper-43:5004/weather")
        env = off["station-wrapper-43"]["environment"]
        self.assertEqual((env["WEATHER_CHANNEL"], env["WEATHER_LOCATION"]), ("", ""))        # "" is off (firstrun, supervisor)
        self.assertEqual(on["station-wrapper-43"]["environment"]["WEATHER_CHANNEL"], "1")    # so firstrun adds the channel
        # The switch's old name still tells the container, for a .env from before the profile.
        self.assertEqual(self.cfg(WEATHER_CHANNEL="1")["services"]["station-wrapper-43"]["environment"]["WEATHER_CHANNEL"], "1")

    def test_both_the_console_and_the_dashboard_are_published(self):
        ports = {int(p["target"]): p for p in self.cfg()["services"]["station-wrapper-43"]["ports"]}
        self.assertEqual(sorted((t, p["published"]) for t, p in ports.items()), [(4242, "4242"), (5004, "5004")])
        self.assertEqual(ports[4242].get("host_ip"), "127.0.0.1")
        lan = {int(p["target"]): p for p in self.cfg(FS42_CONSOLE_BIND="0.0.0.0")["services"]["station-wrapper-43"]["ports"]}
        self.assertEqual(lan[4242].get("host_ip"), "0.0.0.0")

    def test_config_and_catalog_are_local_folders_under_the_one_root(self):
        m = mounts(self.cfg())
        self.assertEqual(m["/config"][0], "/local/config")
        self.assertEqual(m["/app/catalog"][0], "/local/catalog")
        self.assertEqual(set(m), {"/config", "/app/catalog", "/mnt/media", "/etc/localtime"})   # three volumes, not six

    def test_the_media_is_the_only_thing_on_the_share_and_it_is_read_only(self):
        m = mounts(self.cfg())
        self.assertEqual(m["/mnt/media"], ("/media", True))
        for target, (_dev, read_only) in m.items():
            if target not in ("/mnt/media", "/etc/localtime"):
                self.assertFalse(read_only, f"{target} must be writable: the container writes there")

    def test_every_volume_is_a_plain_bind_so_docker_makes_a_missing_folder(self):
        # a bind-style NAMED volume fails on a missing folder (which is what setup-dirs.sh was for); a plain bind
        # is also recursive, so shares mounted inside the media folder show up
        config = self.cfg()
        self.assertFalse(config.get("volumes"))
        self.assertEqual({v["type"] for v in config["services"]["station-wrapper-43"]["volumes"]}, {"bind"})

    def test_the_catalog_and_the_config_can_each_be_moved_to_another_local_path(self):
        m = mounts(self.cfg(FS42_CATALOG_ROOT="/elsewhere", FS42_CONFIG_ROOT="/cfg"))
        self.assertEqual(m["/app/catalog"][0], "/elsewhere")
        self.assertEqual(m["/config"][0], "/cfg")

    def test_with_nothing_set_it_starts_from_folders_beside_the_compose_file(self):
        config, err = render()                                                    # no .env, no variables at all
        self.assertIsNotNone(config, err)
        here = os.path.realpath(ROOT)
        m = {t: (os.path.realpath(src), ro) for t, (src, ro) in mounts(config).items()}
        self.assertEqual(m["/config"], (os.path.join(here, "data", "config"), False))
        self.assertEqual(m["/app/catalog"], (os.path.join(here, "data", "catalog"), False))
        self.assertEqual(m["/mnt/media"], (os.path.join(here, "media"), True))
        self.assertEqual(config["services"]["station-wrapper-43"]["image"], "ghcr.io/austincnunn/station-wrapper-43:latest")

    def test_the_optional_parts_are_off_unless_switched_on(self):
        env = self.cfg()["services"]["station-wrapper-43"]["environment"]
        self.assertEqual(env["SYNC_ENABLED"], "")
        on = self.cfg(SYNC_ENABLED="1")["services"]["station-wrapper-43"]["environment"]
        self.assertEqual(on["SYNC_ENABLED"], "1")

    def test_the_nightly_catalog_update_is_left_to_the_sync_default_which_is_on(self):
        env = self.cfg()["services"]["station-wrapper-43"]["environment"]
        self.assertEqual(env["SYNC_REBUILD"], "")
        self.assertEqual((env["SYNC_INTERVAL_MINUTES"], env["SYNC_REBUILD_HOUR"], env["SYNC_PRUNE"]),
                         ("60", "4", ""))
        on = self.cfg(SYNC_REBUILD="1", SYNC_REBUILD_HOUR="3", SYNC_INCLUDE="movies,tvseries")["services"]["station-wrapper-43"]["environment"]
        self.assertEqual((on["SYNC_REBUILD"], on["SYNC_REBUILD_HOUR"], on["SYNC_INCLUDE"]), ("1", "3", "movies,tvseries"))

    def test_the_override_is_passed_through_and_the_label_states_the_rule(self):
        svc = self.cfg()["services"]["station-wrapper-43"]
        self.assertEqual(svc["environment"]["FS42_ALLOW_NETWORK_CATALOG"], "")            # off unless set
        self.assertIn("LOCAL disk", svc["labels"]["fs42.requires"])
        self.assertEqual(self.cfg(FS42_ALLOW_NETWORK_CATALOG="1")["services"]["station-wrapper-43"]["environment"]
                         ["FS42_ALLOW_NETWORK_CATALOG"], "1")


if __name__ == "__main__":
    unittest.main()
