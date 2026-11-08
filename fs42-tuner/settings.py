"""Settings you change from the dashboard, kept in the config volume (settings.json): the names videos are shown
under, the caption language and the schedule keeper. Some have an environment variable as their starting value: a
setting saved from the dashboard wins over it. The dashboard (tuner.py) writes the file, so a change takes effect
without restarting the container.
"""
import json
import os
import re
import tempfile

PATH = os.environ.get("FS42_SETTINGS", "/config/settings.json")


class SettingsError(ValueError):
    pass


def load(path=None):
    """The saved settings, or {} when there are none or the file is unreadable. Never raises."""
    try:
        with open(path or PATH) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(path, data):
    """Write the settings file atomically, readable and editable from the host, owned like the config folder."""
    folder = os.path.dirname(path) or "."
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=folder, prefix=".settings-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
        os.chmod(tmp, 0o666)  # nosec B103 - a file in the config volume, editable from the host by whoever owns the folder            # the config volume is yours: you can read and edit it from the host
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    if os.geteuid() == 0:               # we run as root; hand the file to whoever owns the config folder
        try:
            ref = os.stat(folder)
            os.chown(path, ref.st_uid, ref.st_gid)
        except OSError:
            pass


# ---- the names videos are shown under (titles.py)
def get_titles(path=None):
    """{"episode_names": bool}: whether an episode is named "Show: Episode" (on, the default) or just "Show" (off)."""
    saved = load(path).get("titles")
    if isinstance(saved, dict) and isinstance(saved.get("episode_names"), bool):
        return {"episode_names": saved["episode_names"]}
    return {"episode_names": True}


def set_titles(values, path=None):
    path = path or PATH
    if "episode_names" in values and not isinstance(values["episode_names"], bool):
        raise SettingsError("episode names must be on or off")
    data = load(path)
    titles = data.get("titles") if isinstance(data.get("titles"), dict) else {}
    if "episode_names" in values:
        titles["episode_names"] = values["episode_names"]
    data["titles"] = titles
    _save(path, data)
    return get_titles(path)


# ---- captions: the one language the container uses for the captions it carries or draws (captions.py)
def get_captions(path=None):
    """{"language": "en"}: the language of the caption track a video is asked for, in the stream and drawn on the picture."""
    saved = load(path).get("captions")
    lang = saved.get("language") if isinstance(saved, dict) else None
    if isinstance(lang, str) and re.fullmatch(r"[a-z]{2,3}", lang):
        return {"language": lang}
    return {"language": "en"}


def set_captions(values, path=None):
    path = path or PATH
    lang = values.get("language")
    if not isinstance(lang, str) or not re.fullmatch(r"[A-Za-z]{2,3}", lang.strip()):
        raise SettingsError("the caption language is two or three letters, such as en or ja")
    data = load(path)
    data["captions"] = {"language": lang.strip().lower()}
    _save(path, data)
    return get_captions(path)


# ---- the schedule keeper: keeps every station's schedule running a few days ahead
DEFAULT_KEEPER = {"enabled": True, "days_ahead": 7}
DAYS_AHEAD_RANGE = (1, 30)
OFF = ("0", "false", "no", "off")


def get_keeper(env=None, path=None):
    """The keeper's settings in force, and where each came from (saved > environment > default)."""
    env = os.environ if env is None else env
    out, source = dict(DEFAULT_KEEPER), {k: "default" for k in DEFAULT_KEEPER}
    if env.get("SCHEDULE_KEEPER", "").strip():
        out["enabled"], source["enabled"] = env["SCHEDULE_KEEPER"].strip().lower() not in OFF, "env"
    try:
        if env.get("KEEPER_DAYS_AHEAD", "").strip():
            out["days_ahead"], source["days_ahead"] = int(env["KEEPER_DAYS_AHEAD"]), "env"
    except ValueError:
        pass
    saved = load(path).get("keeper")
    if isinstance(saved, dict):
        if isinstance(saved.get("enabled"), bool):
            out["enabled"], source["enabled"] = saved["enabled"], "saved"
        d = saved.get("days_ahead")
        if isinstance(d, int) and not isinstance(d, bool) and DAYS_AHEAD_RANGE[0] <= d <= DAYS_AHEAD_RANGE[1]:
            out["days_ahead"], source["days_ahead"] = d, "saved"
    lo, hi = DAYS_AHEAD_RANGE
    out["days_ahead"] = min(hi, max(lo, out["days_ahead"]))
    return {**out, "source": source}


def set_keeper(values, path=None):
    """Validate and save enabled / days_ahead. Returns the new settings."""
    path = path or PATH
    clean = {}
    if "enabled" in values:
        if not isinstance(values["enabled"], bool):
            raise SettingsError("enabled must be on or off")
        clean["enabled"] = values["enabled"]
    if "days_ahead" in values:
        d = values["days_ahead"]
        if isinstance(d, bool) or not isinstance(d, int) or not DAYS_AHEAD_RANGE[0] <= d <= DAYS_AHEAD_RANGE[1]:
            raise SettingsError(f"days ahead must be between {DAYS_AHEAD_RANGE[0]} and {DAYS_AHEAD_RANGE[1]}")
        clean["days_ahead"] = d
    data = load(path)
    keeper = data.get("keeper") if isinstance(data.get("keeper"), dict) else {}
    keeper.update(clean)
    data["keeper"] = keeper
    _save(path, data)
    return get_keeper(path=path)
