#!/usr/bin/env python3
"""Client mode (FS42_ROLE=client): this container plays what a Station Wrapper 43 server schedules, on the screen it is
plugged into. The server builds every schedule; this only copies and plays it.

  client.py --setup   once, from the entrypoint: mpv's settings and FieldStation42's main_config.json for this screen
  client.py           the sync loop, under the supervisor: every FS42_SYNC_SECONDS it asks the server's /sync/state and
                      copies only the parts that changed (schedule database, station configs, catalog links, Sources list)
  client.py --display before each start of the player (player.sh): "x11" when a station needs a browser (pay-per-view),
                      else "drm"; writes mpv's settings for that way of drawing
  client.py --fit     with X up: the web stations' windows are made the size of the screen (there is no window manager)

How it draws: mpv straight to the screen (DRM), with nothing else. A pay-per-view station is a web page drawn by
FieldStation42's own browser (Qt WebEngine), which needs X: while the server has one, player.sh starts a bare X server in
this container and mpv draws in it instead. That needs /dev/tty0 and /dev/tty7 in the container's devices.

Settings (environment):
  FS42_SERVER         the server's tuner address, e.g. http://192.168.1.20:5004            (required)
  FS42_SYNC_TOKEN     the same token the server has
  FS42_SCREEN         crt | hd: sets the defaults below (see PROFILES)
  FS42_PANSCAN, FS42_DRM_MODE, FS42_MPV_PROFILE, FS42_STREAM_KBPS   override one default each
  FS42_DRM_CONNECTOR  the output to draw on (VGA-1, HDMI-A-1, ...; default: the first one connected)
  FS42_GAMMA          mpv's gamma, -100..100 (a CRT often wants a little, like 10)
  FS42_PLAYER_NAME    the name the server's Status page shows (default: the host name)
  FS42_SYNC_SECONDS   how often to look for changes (default 60)

The videos are never copied: they are read from /mnt/media, which must be the same share at the same path as on the server.
"""
import gzip
import json
import os
import random
import re
import signal
import socket
import sqlite3
import subprocess  # nosec B404: fixed commands only (xrandr)
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import playerconfs  # noqa: E402

APP = os.environ.get("FS42_APP", "/app")
RUNTIME, CONFS, CATALOG = (os.path.join(APP, d) for d in ("runtime", "confs", "catalog"))
STATE = os.path.join(RUNTIME, "client_state.json")       # the hashes of what was last copied
READY = os.path.join(RUNTIME, "client_ready")             # the player waits for this (player.sh)
KEEP_CONFS = ("main_config.json",)                        # this player's own; never replaced by the server's

PROFILES = {
    "crt": {"panscan": 1.0, "drm_mode": "preferred", "mpv_profile": "fast", "kbps": 1500},
    "hd": {"panscan": 0.0, "drm_mode": "preferred", "mpv_profile": "high-quality", "kbps": 4000},
}
MIN_KBPS, MAX_KBPS = 500, 4000


def screen(env=None):
    """This player's screen settings: FS42_SCREEN's profile, with any single setting overridden."""
    env = os.environ if env is None else env
    name = env.get("FS42_SCREEN", "hd").strip().lower()
    out = dict(PROFILES.get(name, PROFILES["hd"]), screen=name if name in PROFILES else "hd")
    if env.get("FS42_PANSCAN"):
        out["panscan"] = max(0.0, min(1.0, float(env["FS42_PANSCAN"])))
    if env.get("FS42_DRM_MODE"):
        out["drm_mode"] = env["FS42_DRM_MODE"]
    if env.get("FS42_MPV_PROFILE"):
        out["mpv_profile"] = env["FS42_MPV_PROFILE"]
    if env.get("FS42_STREAM_KBPS"):
        out["kbps"] = int(env["FS42_STREAM_KBPS"])
    out["kbps"] = max(MIN_KBPS, min(MAX_KBPS, int(out["kbps"])))
    return out


def mpv_conf(scr, env=None, x11=False):
    """mpv's settings: drawing straight to the screen, or (x11) full screen in the X server player.sh started."""
    env = os.environ if env is None else env
    common = [f"profile={scr['mpv_profile']}", "hwdec=auto-safe", "sid=no", "sub-auto=no", "cursor-autohide=always",
              f"gamma={int(env.get('FS42_GAMMA', '0') or 0)}"]
    if x11:
        return "\n".join(["vo=gpu", "gpu-context=x11egl", "fullscreen=yes"] + common) + "\n"
    lines = ["vo=gpu", "gpu-context=drm", f"drm-mode={scr['drm_mode']}"] + common
    if env.get("FS42_DRM_CONNECTOR"):
        lines.insert(2, f"drm-connector={env['FS42_DRM_CONNECTOR']}")
    return "\n".join(lines) + "\n"


def _station_confs():
    for f in sorted(os.listdir(CONFS)) if os.path.isdir(CONFS) else []:
        if f.endswith(".json") and f not in KEEP_CONFS:
            try:
                with open(os.path.join(CONFS, f)) as fh:
                    data = json.load(fh)
            except (OSError, ValueError):
                continue
            if isinstance(data, dict) and isinstance(data.get("station_conf"), dict):
                yield os.path.join(CONFS, f), data


def web_needed():
    """Does a station need FieldStation42's browser (a pay-per-view or other web station)?"""
    return any(d["station_conf"].get("network_type") == "web" for _, d in _station_confs())


def vaapi_driver(probe=None):
    """The VA-API driver that works on this GPU (i965, iHD, ...), or "". Drawing straight to the screen, libva finds it
    itself; in X it asks the X server, which can name one that does not work (an old Intel chip then decodes on the CPU)."""
    if os.environ.get("LIBVA_DRIVER_NAME"):
        return os.environ["LIBVA_DRIVER_NAME"]
    if probe is None:
        if not os.path.exists("/dev/dri/renderD128"):
            return ""
        try:
            probe = subprocess.run(["ffmpeg", "-v", "verbose", "-hide_banner", "-init_hw_device", "vaapi=va:/dev/dri/renderD128",  # nosec B603 B607
                                    "-f", "lavfi", "-i", "nullsrc=s=64x64:d=0.1", "-f", "null", "-"],
                                   capture_output=True, text=True, timeout=30).stderr
        except (OSError, subprocess.SubprocessError):
            return ""
    tried = ""
    for line in probe.splitlines():
        m = re.search(r"Trying to open .*/(\w+)_drv_video\.so", line)
        if m:
            tried = m[1]
        elif "va_openDriver() returns 0" in line and tried:
            return tried
    return ""


def display():
    """How the player draws from now on: writes mpv's settings and returns "x11 <vaapi driver>" or "drm"."""
    x11 = web_needed()
    d = os.path.expanduser("~/.config/mpv")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "mpv.conf"), "w") as f:
        f.write(mpv_conf(screen(), x11=x11))
    return f"x11 {vaapi_driver()}".strip() if x11 else "drm"


def fit(width, height):
    """Make each web station's window the whole screen. FieldStation42 asks for full screen, which only a window manager
    can grant; given a size it places the window itself. Returns how many configs were changed."""
    n = 0
    for path, data in _station_confs():
        c = data["station_conf"]
        if c.get("network_type") == "web" and (c.get("width"), c.get("height"), c.get("x"), c.get("y")) != (width, height, 0, 0):
            c.update(width=width, height=height, x=0, y=0)
            _atomic(path, json.dumps(data).encode())
            n += 1
    return n


def screen_size(xrandr_out):
    """(width, height) of the X screen, from `xrandr`'s first line ("Screen 0: minimum 320 x 200, current 1024 x 768, ...")."""
    m = re.search(r"current (\d+) x (\d+)", xrandr_out)
    return (int(m[1]), int(m[2])) if m else None


def setup():
    """mpv's settings for this screen, and FieldStation42's main_config.json (its Qt info overlay hidden: there is no X)."""
    scr = screen()
    d = os.path.expanduser("~/.config/mpv")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "mpv.conf"), "w") as f:
        f.write(mpv_conf(scr))
    os.makedirs(CONFS, exist_ok=True)
    with open(os.path.join(CONFS, "main_config.json"), "w") as f:
        json.dump({"overlay_conf": {"overlay_text_color": [0, 0, 0, 0], "overlay_shadow_color": [0, 0, 0, 0]}}, f)
    print(f"client: {scr['screen']} screen: panscan {scr['panscan']}, mode {scr['drm_mode']}, mpv profile {scr['mpv_profile']}, "
          f"server streams at {scr['kbps']} kbps", flush=True)


# -- talking to the server ---------------------------------------------------
class Server:
    def __init__(self, base, token, timeout=60):
        if not base.startswith(("http://", "https://")):
            raise ValueError(f"FS42_SERVER must start with http:// or https://, not {base!r}")
        self.base, self.token, self.timeout = base.rstrip("/"), token or "", timeout

    def get(self, path, etag=None):
        """(status, headers, body). 304 when `etag` still matches."""
        req = urllib.request.Request(self.base + path, headers={"Authorization": f"Bearer {self.token}"})
        if etag:
            req.add_header("If-None-Match", etag)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:   # nosec B310 - http(s) only, checked above
                return r.status, r.headers, r.read()
        except urllib.error.HTTPError as e:
            if e.code == 304:
                return 304, e.headers, b""
            raise

    def post(self, path, obj):
        req = urllib.request.Request(self.base + path, data=json.dumps(obj).encode(), method="POST",
                                     headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10):   # nosec B310 - http(s) only, checked in __init__
            pass


# -- applying what came ----------------------------------------------------------
def _atomic(path, data):
    tmp = path + ".part"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)


def apply_confs(confs):
    """Replace the server's station configs with `confs` ({file: text}); this player's own files are kept."""
    os.makedirs(CONFS, exist_ok=True)
    for f in os.listdir(CONFS):
        if f.endswith(".json") and f not in confs and f not in KEEP_CONFS and not f.startswith("stream-"):
            os.remove(os.path.join(CONFS, f))
    for f, text in confs.items():
        if f in KEEP_CONFS or "/" in f:
            continue
        _atomic(os.path.join(CONFS, f), text.encode())


def apply_catalog(manifest, fetch):
    """Make the local catalog match the server's: links made, repointed or removed; real files fetched when they changed."""
    links, files, dirs = manifest.get("links", {}), manifest.get("files", {}), manifest.get("dirs", [])
    root = CATALOG
    os.makedirs(root, exist_ok=True)
    for d in dirs:
        p = os.path.join(root, d)
        if os.path.islink(p):
            os.remove(p)
        os.makedirs(p, exist_ok=True)
    made = 0
    for rel, target in links.items():
        p = os.path.join(root, rel)
        if os.path.islink(p) and os.readlink(p) == target:
            continue
        if os.path.lexists(p):
            os.remove(p) if not os.path.isdir(p) or os.path.islink(p) else os.rmdir(p)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        os.symlink(target, p)
        made += 1
    got = 0
    for rel, (size, mtime) in files.items():
        p = os.path.join(root, rel)
        try:
            st = os.lstat(p)
            if not os.path.islink(p) and st.st_size == size and int(st.st_mtime) == mtime:
                continue
        except OSError:
            pass
        if os.path.lexists(p):
            os.remove(p)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        _atomic(p, fetch(rel))
        os.utime(p, (mtime, mtime))
        got += 1
    gone = 0
    want_dirs = set(dirs)
    for d, subdirs, names in os.walk(root, topdown=False):
        for n in names + [s for s in subdirs if os.path.islink(os.path.join(d, s))]:
            p = os.path.join(d, n)
            rel = os.path.relpath(p, root)
            if rel not in links and rel not in files:
                os.remove(p)
                gone += 1
        rel_d = os.path.relpath(d, root)
        if rel_d != "." and rel_d not in want_dirs and not os.listdir(d):
            os.rmdir(d)
    return made, got, gone


def _hash_confs():
    import hashlib
    h = hashlib.sha1(usedforsecurity=False)
    for f in sorted(os.listdir(CONFS)) if os.path.isdir(CONFS) else []:
        if f.endswith(".json"):
            h.update(f.encode())
            with open(os.path.join(CONFS, f), "rb") as fh:
                h.update(fh.read())
    return h.hexdigest()


# -- checks -----------------------------------------------------------------
def media_problem(db_path, hours=6, sample=20):
    """None, or why the videos the schedule plays in the next hours can't be found here (the share is not mounted?)."""
    try:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        later = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() + hours * 3600))
        rows = con.execute("SELECT plan_json FROM liquid_blocks WHERE julianday(end_time) > julianday(?) AND julianday(start_time) < julianday(?)", (now, later)).fetchall()
        con.close()
    except sqlite3.Error as e:
        return f"the schedule database can't be read: {e}"
    paths = set()
    for (plan,) in rows:
        try:
            for e in json.loads(plan):
                if isinstance(e, dict) and e.get("path") and not e.get("is_stream") and e.get("content_type") == "feature":
                    paths.add(e["path"])
        except (ValueError, TypeError):
            continue
    if not paths:
        return None
    pick = random.sample(sorted(paths), min(sample, len(paths)))
    missing = [p for p in pick if not os.path.exists(p if os.path.isabs(p) else os.path.join(APP, p))]
    if len(missing) * 2 > len(pick):
        return (f"{len(missing)} of {len(pick)} videos in the coming schedule are missing here (like {missing[0]}): "
                "is the media share mounted at /mnt/media, the same as on the server?")
    return None


def my_versions():
    try:
        with open("/opt/FS42_REF") as f:
            ref = f.read().split()[0]
    except (OSError, IndexError):
        ref = ""
    return {"wrapper": os.environ.get("FS42_WRAPPER_SHA") or "", "fieldstation42": ref}


def stop_player():
    """Stop FieldStation42's player (player.sh starts it again). The image has no pkill: look through /proc."""
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as f:
                if f.read().startswith(b"python3\0field_player.py"):
                    os.kill(int(pid), signal.SIGTERM)
        except (OSError, ValueError):
            continue


def now_on():
    try:
        with open(os.path.join(RUNTIME, "play_status.socket")) as f:
            st = json.load(f)
        return f"{st.get('channel_number')} {st.get('network_name')}".strip()
    except (OSError, ValueError):
        return None


# -- one round ------------------------------------------------------------------
def sync_once(server, scr, state):
    """Copy what changed since `state` (the hashes last copied; updated in place). True when the player must restart."""
    code, headers, body = server.get("/sync/state", state.get("etag"))
    if code == 304:
        return False
    st = json.loads(body)
    want, have = st["parts"], state.setdefault("parts", {})
    before = _hash_confs()
    if want["db"] != have.get("db"):
        _atomic(os.path.join(RUNTIME, "fs42_fluid.db"), gzip.decompress(server.get("/sync/db")[2]))
        print("client: new schedule database", flush=True)
    if want["catalog"] != have.get("catalog"):
        manifest = json.loads(gzip.decompress(server.get("/sync/catalog")[2]))
        made, got, gone = apply_catalog(manifest, lambda rel: server.get("/sync/file?path=" + urllib.parse.quote(rel))[2])
        print(f"client: catalog: {made} links made, {got} files fetched, {gone} removed", flush=True)
    if want["sources"] != have.get("sources"):
        _atomic(os.path.join(RUNTIME, "server_sources.json"), server.get("/sync/sources")[2])
    if want["confs"] != have.get("confs"):
        apply_confs(json.loads(server.get("/sync/confs")[2]))
    if want["confs"] != have.get("confs") or want["sources"] != have.get("sources"):
        with open(os.path.join(RUNTIME, "server_sources.json")) as f:
            playerconfs.write(APP, json.load(f), server.base, scr["panscan"], scr["kbps"])
    state.update(parts=dict(want), etag=headers.get("ETag"), versions=st.get("versions"), tz=st.get("tz"))
    return _hash_confs() != before


def main():
    if "--setup" in sys.argv:
        return setup()
    if "--display" in sys.argv:
        print(display())
        return 0
    if "--fit" in sys.argv:
        size = screen_size(subprocess.run(["xrandr"], capture_output=True, text=True, timeout=10).stdout)  # nosec B603 B607: fixed command
        if not size:
            print("client: could not read the screen's size from xrandr", flush=True)
            return 1
        if fit(*size):
            print(f"client: web stations drawn at {size[0]}x{size[1]}", flush=True)
        return 0
    base = os.environ.get("FS42_SERVER", "").strip()
    if not base:
        print("client: FS42_SERVER is not set: it must be the server's address, like http://192.168.1.20:5004", flush=True)
        return 78
    try:
        server = Server(base, os.environ.get("FS42_SYNC_TOKEN"))
    except ValueError as e:
        print(f"client: {e}", flush=True)
        return 78
    scr, every = screen(), int(os.environ.get("FS42_SYNC_SECONDS", "60"))
    name = os.environ.get("FS42_PLAYER_NAME") or socket.gethostname()
    try:
        with open(STATE) as f:
            state = json.load(f)
    except (OSError, ValueError):
        state = {}
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    last_ok, said = None, None
    while True:
        errors = []
        try:
            if sync_once(server, scr, state):
                print("client: the stations changed: restarting the player", flush=True)
                stop_player()
            with open(STATE, "w") as f:
                json.dump(state, f)
            last_ok = time.time()
        except urllib.error.HTTPError as e:
            errors.append("the server refused the sync token (FS42_SYNC_TOKEN must match the server's)" if e.code == 403 else
                          "the server has client sync switched off (set FS42_SYNC_TOKEN there)" if e.code == 404 else
                          f"sync failed: HTTP {e.code}")
        except (urllib.error.URLError, OSError, ValueError, KeyError) as e:
            errors.append(f"sync failed: {e}")
        if os.path.exists(os.path.join(RUNTIME, "fs42_fluid.db")):
            problem = media_problem(os.path.join(RUNTIME, "fs42_fluid.db"))
            if problem:
                errors.append(problem)
                if os.path.exists(READY):
                    os.remove(READY)
                    stop_player()
            elif not os.path.exists(READY):
                open(READY, "w").close()
                print("client: ready: the player can start", flush=True)
        if state.get("versions") and state["versions"] != my_versions():
            errors.append("this player runs a different version than the server: run docker compose pull here (or on the server)")
        if state.get("tz") and state["tz"] != time.strftime("%Z %z"):
            errors.append(f"this player's time zone ({time.strftime('%Z %z')}) is not the server's ({state['tz']}): shows would play at the wrong time")
        if errors != said:
            for e in errors:
                print(f"client: ! {e}", flush=True)
            said = errors
        try:
            server.post("/sync/hello", {"name": name, "versions": my_versions(), "channel": now_on(), "last_sync": last_ok,
                                        "errors": errors, "screen": scr["screen"], "tz": time.strftime("%Z %z")})
        except (urllib.error.URLError, OSError):
            pass
        time.sleep(every)


if __name__ == "__main__":
    sys.exit(main() or 0)
