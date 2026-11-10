"""Environment settings you can change on the dashboard's Settings page.

Most of the container is set up with environment variables in the compose file. The ones people change (how often the
pool is synced, the farm, prefetch, the media server, and each player's screen) can also be set on the Settings page.
A value set there wins over the compose file's, which wins over the built-in default; clearing it goes back to the
compose file's.

The saved values are an overlay on the environment, applied by the supervisor: it starts every service with the
merged environment, and when a saved value changes it restarts only the services that read it (REGISTRY's
`restarts`). So no service reads this file: each keeps reading its environment variable as before.

  server   settings.json {"env": {KEY: "value"}}                        (written by the dashboard)
  players  settings.json {"players": {name: {KEY: "value"}}} on the server; each player gets its own in the
           answer to its /sync/hello and keeps it in PLAYER_PATH (client.py)

The supervisor also hands every service COMPOSE_ENV: the registry's variables as the compose file set them, so the
page can say where a value came from. Secrets (passwords, keys, tokens) are never in the registry: they stay in the
compose file or .env, and the page only says whether each is set.
"""
import json
import os
import re

import settings

PLAYER_PATH = os.environ.get("FS42_PLAYER_SETTINGS", "/config/player-settings.json")
COMPOSE_ENV = "FS42_COMPOSE_ENV"
OFF = ("0", "false", "no", "off")
SECRETS = ("DASHBOARD_PASSWORD", "MEDIA_SERVER_API_KEY", "FS42_SYNC_TOKEN")


def _s(key, group, label, kind, default, restarts, role="server", note=""):
    return {"key": key, "group": group, "label": label, "kind": kind, "default": default, "restarts": restarts,
            "role": role, "note": note}


# kind: "bool", ("int", lo, hi), ("float", lo, hi), ("choice", [...]), ("text", regex). Defaults are what the code uses
# when the variable is not set ("" means the code works it out, e.g. from the player's screen profile).
REGISTRY = [
    _s("SYNC_ENABLED", "Media pool", "Keep the pool of links to your media current", "bool", "0", []),
    _s("SYNC_INCLUDE", "Media pool", "Media folders in the pool (comma separated, empty = all)", ("text", r"[^\n\0]{0,500}"), "", ["sync"]),
    _s("SYNC_EXCLUDE", "Media pool", "Media folders left out (comma separated)", ("text", r"[^\n\0]{0,500}"), "", ["sync"]),
    _s("SYNC_INTERVAL_MINUTES", "Media pool", "Look for new videos every (minutes)", ("int", 1, 1440), "60", ["sync"]),
    _s("SYNC_FULL_EVERY_HOURS", "Media pool", "Full walk of the share every (hours)", ("int", 1, 720), "24", ["sync"]),
    _s("SYNC_REBUILD", "Media pool", "Add new videos to the stations' catalogs once a night", "bool", "1", ["sync"]),
    _s("SYNC_REBUILD_HOUR", "Media pool", "Nightly catalog update at (hour, 0-23)", ("int", 0, 23), "4", ["sync"]),
    _s("SYNC_REBUILD_WINDOW_HOURS", "Media pool", "Catalog update window (hours)", ("int", 1, 12), "2", ["sync"]),
    _s("FARM_ENABLED", "Farm", "Sort the media into genre lists (farm)", "bool", "1", []),
    _s("FARM_INTERVAL_MINUTES", "Farm", "Farm runs every (minutes)", ("int", 1, 1440), "30", ["farm"]),
    _s("FOLLOW_INTERVAL_MINUTES", "Lists", "Look in followed folders for new videos every (minutes)", ("int", 1, 1440), "30", ["tuner"]),
    _s("LIBRARY_SCAN_MINUTES", "Lists", "Rescan the Library card every (minutes)", ("int", 5, 1440), "60", ["tuner"]),
    _s("KEEPER_INTERVAL_MINUTES", "Schedule keeper", "Check the schedules every (minutes)", ("int", 5, 1440), "30", ["tuner"]),
    _s("KEEPER_TOPUP_HOUR", "Schedule keeper", "Add the next day at (hour, 0-23)", ("int", 0, 23), "4", ["tuner"]),
    _s("PREFETCH", "Prefetch", "Copy what plays next off the share ahead of time", "bool", "1", ["tuner"]),
    _s("PREFETCH_RAM", "Prefetch", "Only in RAM (the /cache RAM disk)", "bool", "1", ["tuner"]),
    _s("PREFETCH_MAX_MB", "Prefetch", "At most (MB)", ("int", 100, 1000000), "6144", ["tuner"]),
    _s("MEDIA_SERVER_URL", "Media server", "Emby or Jellyfin address (for guide pictures and descriptions)",
       ("text", r"(https?://[^\s\0]{1,200})?"), "", ["tuner"], note="Its API key stays in the compose file (.env)."),
    _s("MEDIA_SERVER_MEDIA_ROOT", "Media server", "Where the media server sees the media", ("text", r"(/[^\n\0]{0,200})?"), "/media", ["tuner"]),
    _s("MEDIA_SERVER_REFRESH_HOURS", "Media server", "Ask it again every (hours)", ("int", 1, 168), "6", ["tuner"]),
    # a player (client mode): set on the server, used by the player
    _s("FS42_SCREEN", "Screen", "Screen", ("choice", ["crt", "hd"]), "hd", ["client", "player"], "client",
       "crt: 4:3, widescreen cropped, lighter streams. hd: 16:9, the whole picture."),
    _s("FS42_PANSCAN", "Screen", "Crop widescreen (0 = whole picture with bars, 1 = fill a 4:3 screen)", ("float", 0, 1), "", ["client", "player"], "client"),
    _s("FS42_DRM_CONNECTOR", "Screen", "Output (VGA-1, HDMI-A-1, ...; empty = the first connected)", ("text", r"[A-Za-z0-9-]{0,32}"), "", ["player"], "client"),
    _s("FS42_DRM_MODE", "Screen", "Screen mode (preferred, highest, or e.g. 1024x768@60)",
       ("text", r"(preferred|highest|\d{2,5}x\d{2,5}(@\d{1,3}(\.\d{1,3})?)?)?"), "", ["player"], "client"),
    _s("FS42_MPV_PROFILE", "Screen", "Picture scaling", ("choice", ["", "fast", "high-quality"]), "", ["player"], "client"),
    _s("FS42_GAMMA", "Screen", "Gamma (-100 to 100; a CRT often wants a little, like 10)", ("int", -100, 100), "0", ["player"], "client"),
    _s("FS42_STREAM_KBPS", "Screen", "Rate of channels streamed from the server, the guide (kbps)", ("int", 500, 4000), "", ["client"], "client"),
    _s("FS42_BANNER", "Banner", "Show the channel number on a channel change", "bool", "1", [], "client"),
    _s("FS42_BANNER_SECONDS", "Banner", "For (seconds)", ("int", 1, 60), "8", ["banner"], "client"),
    _s("FS42_SYNC_SECONDS", "Sync", "Look for schedule changes every (seconds)", ("int", 15, 3600), "60", ["client"], "client"),
]
BY_KEY = {s["key"]: s for s in REGISTRY}


class SettingsError(ValueError):
    pass


def keys(role):
    return [s["key"] for s in REGISTRY if s["role"] == role]


def clean(key, value):
    """The value as the environment holds it, or SettingsError. None or "" means: not set here."""
    s = BY_KEY.get(key)
    if s is None:
        raise SettingsError(f"{key} can't be set here")
    if value is None or value == "":
        return None
    kind = s["kind"]
    if kind == "bool":
        if isinstance(value, bool):
            return "1" if value else "0"
        if isinstance(value, str) and value.strip().lower() in OFF + ("1", "true", "yes", "on"):
            return "0" if value.strip().lower() in OFF else "1"
        raise SettingsError(f"{s['label']}: must be on or off")
    if kind[0] in ("int", "float"):
        try:
            if isinstance(value, bool):
                raise ValueError
            n = int(str(value).strip()) if kind[0] == "int" else float(str(value).strip())
        except ValueError:
            raise SettingsError(f"{s['label']}: must be a number") from None
        if not kind[1] <= n <= kind[2]:
            raise SettingsError(f"{s['label']}: must be between {kind[1]} and {kind[2]}")
        return str(n)
    if not isinstance(value, str):
        raise SettingsError(f"{s['label']}: must be text")
    value = value.strip()
    if kind[0] == "choice":
        if value not in kind[1]:
            raise SettingsError(f"{s['label']}: must be one of {', '.join(c for c in kind[1] if c)}")
        return value or None
    if not re.fullmatch(kind[1], value):
        raise SettingsError(f"{s['label']}: not a valid value")
    return value or None


def _cleaned(saved, role):
    """A saved overlay with anything unknown or invalid dropped (a hand-edited file must not take a service down)."""
    out = {}
    for k, v in (saved or {}).items() if isinstance(saved, dict) else ():
        if k in BY_KEY and BY_KEY[k]["role"] == role:
            try:
                v = clean(k, v)
            except SettingsError:
                continue
            if v is not None:
                out[k] = v
    return out


def overlay(role, path=None):
    """What was set on the Settings page for this machine."""
    if role == "client":
        try:
            with open(path or PLAYER_PATH) as f:
                return _cleaned(json.load(f), role)
        except (OSError, ValueError):
            return {}
    return _cleaned(settings.load(path).get("env"), role)


def effective(env, saved, role):
    """The environment to run with: env, with the saved values on top, plus COMPOSE_ENV (env's own values)."""
    out = dict(env)
    out.update(saved)
    out[COMPOSE_ENV] = json.dumps({k: env[k] for k in keys(role) if k in env}, sort_keys=True)
    return out


def compose_env(env=None):
    """The registry's variables as the compose file set them (from COMPOSE_ENV; else env itself, before any overlay)."""
    env = os.environ if env is None else env
    try:
        got = json.loads(env.get(COMPOSE_ENV) or "null")
    except ValueError:
        got = None
    return got if isinstance(got, dict) else {k: env[k] for k in BY_KEY if k in env}


def describe(role, saved, compose):
    """Every setting of this role: its value in force and where that came from (saved, env or default)."""
    out = []
    for s in REGISTRY:
        if s["role"] != role:
            continue
        k = s["key"]
        source = "saved" if k in saved else "env" if compose.get(k, "") != "" else "default"
        value = saved.get(k) if source == "saved" else compose.get(k) if source == "env" else s["default"]
        kind = s["kind"] if isinstance(s["kind"], str) else list(s["kind"])
        out.append({"key": k, "group": s["group"], "label": s["label"], "note": s["note"], "kind": kind,
                    "value": value, "source": source, "env": compose.get(k), "default": s["default"],
                    "restarts": s["restarts"]})
    return out


def _save_section(update):
    data = settings.load()
    update(data)
    settings._save(settings.PATH, data)


def save(values):
    """Save this server's settings: {KEY: value}; "" or None clears one (back to the compose file's)."""
    if not isinstance(values, dict):
        raise SettingsError("expected {setting: value}")
    changes = {}
    for k, v in values.items():
        if BY_KEY.get(k, {}).get("role") != "server":
            raise SettingsError(f"{k} can't be set here")
        changes[k] = clean(k, v)

    def update(data):
        env = _cleaned(data.get("env"), "server")
        for k, v in changes.items():
            env.pop(k, None) if v is None else env.__setitem__(k, v)
        data["env"] = env
    _save_section(update)
    return overlay("server")


def player_overlay(name):
    """What was set on the server for the player called `name`."""
    players = settings.load().get("players")
    return _cleaned(players.get(name) if isinstance(players, dict) else None, "client")


def save_player(name, values):
    if not isinstance(name, str) or not name.strip() or len(name) > 64:
        raise SettingsError("which player?")
    if not isinstance(values, dict):
        raise SettingsError("expected {setting: value}")
    changes = {}
    for k, v in values.items():
        if BY_KEY.get(k, {}).get("role") != "client":
            raise SettingsError(f"{k} can't be set for a player")
        changes[k] = clean(k, v)

    def update(data):
        players = data.get("players") if isinstance(data.get("players"), dict) else {}
        mine = _cleaned(players.get(name), "client")
        for k, v in changes.items():
            mine.pop(k, None) if v is None else mine.__setitem__(k, v)
        players[name] = mine
        data["players"] = {n: p for n, p in players.items() if p}
    _save_section(update)
    return player_overlay(name)


def machine(env=None):
    """The read-only facts the page shows: role, clock, version, the login switches, and which secrets are set."""
    env = os.environ if env is None else env
    return {"role": (env.get("FS42_ROLE") or "server").strip().lower(), "tz": env.get("TZ", ""),
            "version": env.get("FS42_WRAPPER_SHA", "")[:7], "login": env.get("DASHBOARD_LOGIN", "1").lower() not in OFF,
            "edit": env.get("DASHBOARD_EDIT", "1").lower() not in OFF,
            "secrets": {k: bool(env.get(k, "").strip()) for k in SECRETS}}
