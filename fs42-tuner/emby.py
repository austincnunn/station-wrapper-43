"""Emby servers as a place to get videos from: sign in with Emby Connect, pick servers and libraries, use their shows and
movies on channels like your own media.

FieldStation42 only schedules files it can look at. So each chosen library is MIRRORED into the media pool, under
Emby/<server>/<library>/..., with one tiny black placeholder video per item (about 1 KB, as long as the real one, with
its chapters) and a .nfo beside it. The folders look like any media folder (Show/Season 01/Show - S01E02 - Name.mkv,
Movie (1999)/Movie (1999).mkv), so the Files page, lists, followed folders, shows in order, breaks and the guide work on
them unchanged. When a channel plays a placeholder, the tuner asks lookup() which Emby item it stands for and input_for()
how to read the real one from that server, starting at the right second. Nothing is read from Emby while nobody watches.

The Connect password is used once to sign in and is never kept: config/tuner/emby.json (readable by its owner only)
holds the tokens the sign-in gives.

    connect.emby.media/service/user/authenticate   nameOrEmail + rawpw          -> Connect token and user id
    connect.emby.media/service/servers?userId=     X-Connect-UserToken           -> the account's servers and access keys
    <server>/emby/Connect/Exchange?ConnectUserId=  X-Emby-Token: the access key  -> that server's own user id and token

A server reached on its LAN address plays the original file (no work for Emby). One reached only on its internet
address is asked to make H.264 at its cap_kbps instead (that server's CPU; 0 = the original file there too).

A server can also be added by its address with a user name and password of its own (add_server): any Jellyfin server,
and an Emby server that isn't on Connect (or is, but should be reached on an address of your choosing). The password is
passed on once for a token. It then sits in the same list ("direct": true; "kind": "jellyfin" or "emby") and is mirrored
and played the same way. An Emby server already on the Connect list keeps its entry (its choices and folder) and is
reached on the given address from then on. Jellyfin has no /emby prefix and wants the token in the Authorization header.
A server added by address always honours its cap_kbps (0, the start, reads the original file) because nothing says
whether its address is on the LAN.

Libraries don't have to be chosen by hand. A server new to the list is "auto": its libraries of shows, movies and music
videos are chosen the first time they are looked up. One added by its address is on at once; an Emby Connect account's
servers start off, and the page asks which of them to use before anything is read. A read then hands each library's
folder, once, to on_sync (tuner.py makes a list of it: "Server - Library"); "listed" remembers which, so a list you
delete stays deleted.
"""
import contextlib
import hashlib
import json
import os
import re
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

import iptv
import schedlock

CONNECT ="https://connect.emby.media/service"
MIRROR_DIR = "Emby"                         # the mirror's folder in the media pool (client mode streams what plays from it)
APP = "StationWrapper43/1.0"
TYPES = "Movie,Episode,Video,MusicVideo"         # MusicVideo: all a "Music Videos" library holds
PAGE = 500
REMOTE_CAP_KBPS = 6000                      # the starting cap for a server reached over the internet
MAX_ITEMS = 50000                           # per library
AUTO_KINDS = {"tvshows", "movies", "musicvideos", "mixed"}    # the libraries chosen for a server new to the list
BAD = re.compile(r'[\x00-\x1f/\\:*?"<>|]+')
CTRL = re.compile(r"[\x00-\x1f\x7f]+")       # what must never reach a request header (a token from a server)


class EmbyError(Exception):
    """Something the person can fix: the message is safe to show."""


class Busy(EmbyError):
    """A scan of the servers is already running. Not a fault: whoever asked for another has nothing to do or to report."""


def _safe_server_url(url):
    if not isinstance(url, str) or not url.lower().startswith(("http://", "https://")):
        return False
    if any(c.isspace() or ord(c) < 32 for c in url):
        return False
    return not iptv.forbidden(urllib.parse.urlsplit(url))      # the one rule for every outside address (iptv.py)


def clean_name(text, fallback="Untitled"):
    """A file or folder name from an Emby name: no slashes or other characters a share can't hold, not hidden."""
    text = BAD.sub(" ", str(text or "")).strip().lstrip(".").strip()
    return re.sub(r"\s+", " ", text)[:120] or fallback


def _x(text):
    return (str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")) if text is not None else ""


def item_rel(item, library_dir):
    """The placeholder's path inside the library's folder, for one Emby item."""
    name = clean_name(item.get("Name"))
    if item.get("Type") == "Episode":
        show = clean_name(item.get("SeriesName"), "Unknown show")
        season, ep = item.get("ParentIndexNumber"), item.get("IndexNumber")
        season = season if isinstance(season, int) else 1
        stem = f"{show} - S{season:02d}E{ep:02d} - {name}" if isinstance(ep, int) else f"{show} - {name}"
        return f"{library_dir}/{show}/Season {season:02d}/{clean_name(stem)}.mkv"
    if item.get("Type") == "Movie":
        year = item.get("ProductionYear")
        stem = clean_name(f"{name} ({year})" if year else name)
        return f"{library_dir}/{stem}/{stem}.mkv"
    if item.get("Type") == "MusicVideo" and _artist(item):
        return f"{library_dir}/{clean_name(_artist(item))}/{name}.mkv"
    return f"{library_dir}/{name}.mkv"


def _artist(item):
    """A music video's artist(s), "" when the server names none."""
    return ", ".join(str(a) for a in (item.get("Artists") or [])[:3] if a)


def nfo(item):
    """A Kodi .nfo for the guide (titles.py reads these)."""
    genres = "".join(f"<genre>{_x(g)}</genre>" for g in (item.get("Genres") or [])[:6])
    aired = (item.get("PremiereDate") or "")[:10]
    if item.get("Type") == "Episode":
        return ("<episodedetails>"
                f"<title>{_x(item.get('Name'))}</title><showtitle>{_x(item.get('SeriesName'))}</showtitle>"
                + (f"<season>{item['ParentIndexNumber']}</season>" if isinstance(item.get("ParentIndexNumber"), int) else "")
                + (f"<episode>{item['IndexNumber']}</episode>" if isinstance(item.get("IndexNumber"), int) else "")
                + f"<plot>{_x(item.get('Overview'))}</plot>" + (f"<aired>{aired}</aired>" if aired else "")
                + genres + "</episodedetails>\n")
    if item.get("Type") == "MusicVideo":          # titles.py shows a music video by its <title>: artist and song
        name, artist = str(item.get("Name") or ""), _artist(item)
        title = f"{artist} - {name}" if artist and artist.lower() not in name.lower() else name
        return (f"<musicvideo><title>{_x(title)}</title><artist>{_x(artist)}</artist>"
                + (f"<album>{_x(item['Album'])}</album>" if item.get("Album") else "")
                + (f"<year>{item['ProductionYear']}</year>" if item.get("ProductionYear") else "")
                + f"<plot>{_x(item.get('Overview'))}</plot>" + genres + "</musicvideo>\n")
    return ("<movie>"
            f"<title>{_x(item.get('Name'))}</title>"
            + (f"<year>{item['ProductionYear']}</year>" if item.get("ProductionYear") else "")
            + f"<plot>{_x(item.get('Overview'))}</plot>" + (f"<premiered>{aired}</premiered>" if aired else "")
            + genres + "</movie>\n")


def item_key(item):
    """What a placeholder was made from: a different one means it is made again."""
    chapters = [round((c.get("StartPositionTicks") or 0) / 1e7, 1) for c in item.get("Chapters") or []]
    meta = [item.get("RunTimeTicks"), chapters, item.get("Name"), item.get("Overview"), item.get("SeriesName")]
    return hashlib.sha1(json.dumps(meta).encode(), usedforsecurity=False).hexdigest()[:16]


def make_placeholder(path, seconds, chapters=(), ffmpeg="ffmpeg"):
    """A black 16x16 video `seconds` long (two frames: one at the start, one a second before the end), with `chapters`
    (start seconds). About 1 KB. FieldStation42 reads its length and chapters as if it were the real video."""
    seconds = max(float(seconds), 2.0)
    marks = sorted({c for c in chapters if 0 <= c < seconds})
    if not marks or marks[0] != 0:
        marks = [0.0] + marks
    meta = ";FFMETADATA1\n" + "".join(
        f"[CHAPTER]\nTIMEBASE=1/1000\nSTART={int(a * 1000)}\nEND={int(b * 1000)}\n"
        for a, b in zip(marks, marks[1:] + [seconds]))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(suffix=".mkv", dir=os.path.dirname(path), prefix=".part-")
    os.close(fd)
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as m:
        m.write(meta)
    try:
        subprocess.run([ffmpeg, "-v", "error", "-y", "-f", "lavfi",
                        "-i", f"color=black:s=16x16:r=1,trim=end_frame=2,setpts=N*{seconds - 1:.3f}/TB",
                        "-i", m.name, "-map", "0:v", "-map_metadata", "1", "-map_chapters", "1", "-fps_mode", "vfr",
                        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", tmp],
                       check=True, stdin=subprocess.DEVNULL, capture_output=True, timeout=60)
        os.replace(tmp, path)
    finally:
        for p in (tmp, m.name):
            try:
                os.remove(p)
            except OSError:
                pass


def parse(body, ctype=""):
    """JSON when the body is JSON, whatever the server labels it (Emby Connect doesn't always say json); else the bytes."""
    if body and ("json" in ctype or body.lstrip()[:1] in (b"{", b"[")):
        try:
            return json.loads(body)
        except ValueError:
            pass
    return body


def _http(method, url, headers=None, data=None, timeout=20):
    """(status, parsed JSON or raw bytes). Raises EmbyError for network trouble, with the address's host only."""
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"User-Agent": APP, "Accept": "application/json", **(headers or {})})
    try:
        with iptv.OPENER.open(req, timeout=timeout) as r:  # nosec B310 - http(s) only, checked by callers and on every redirect
            return r.status, parse(r.read(64 * 1024 * 1024), r.headers.get("Content-Type", ""))
    except urllib.error.HTTPError as e:
        return e.code, None
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise EmbyError(f"could not reach {urllib.parse.urlsplit(url).hostname}: {getattr(e, 'reason', e)}")


class Emby:
    def __init__(self, path, mirror_root, ffmpeg="ffmpeg", http=_http, log=print):
        self.path, self.mirror, self.ffmpeg, self.http, self.log = path, mirror_root, ffmpeg, http, log
        self.lock = threading.RLock()
        self.sync_lock = threading.Lock()
        self.status = {"syncing": False, "last": None, "error": None, "counts": {}}
        self.state = self._load()
        self._index, self._index_at = {}, None
        self.on_sync = None                        # called with "<server>/<library>" (inside the mirror) for a library read for the first time

    # ---- saved state (tokens only: never the password) ----
    def _load(self):
        try:
            with open(self.path) as f:
                state = json.load(f)
        except (OSError, ValueError):
            state = {}
        state.setdefault("device_id", uuid.uuid4().hex)
        state.setdefault("connect", None)
        state.setdefault("servers", {})
        return state

    def _save(self):
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(self.path) or ".", prefix=".emby-")
        with os.fdopen(fd, "w") as f:
            json.dump(self.state, f, indent=1)
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.path)

    def _auth_header(self):
        return (f'MediaBrowser Client="Station Wrapper 43", Device="FieldStation42 tuner", '
                f'DeviceId="{self.state["device_id"]}", Version="1.0"')

    def _headers(self, s, tok):
        """The request headers that carry a server's token."""
        if s.get("kind") == "jellyfin":
            return {"Authorization": f'{self._auth_header()}, Token="{tok}"'}
        return {"X-Emby-Token": tok, "X-Emby-Authorization": self._auth_header()}

    @staticmethod
    def _base(s):
        return s["reach"] + ("" if s.get("kind") == "jellyfin" else "/emby")

    @staticmethod
    def _direct(s):
        """Added by its address with a sign-in of its own (not through Emby Connect)."""
        return bool(s.get("direct")) or s.get("kind") == "jellyfin"

    # ---- a server by its address (any Jellyfin; an Emby without Connect): no Connect, one server at a time ----
    def add_server(self, kind, url, name, password):
        if kind not in ("emby", "jellyfin"):
            raise EmbyError("a server is Emby or Jellyfin")
        label = "Jellyfin" if kind == "jellyfin" else "Emby"
        prefix = "" if kind == "jellyfin" else "/emby"
        url = url.strip().rstrip("/") if isinstance(url, str) else ""
        if url and "://" not in url:
            url = "http://" + url
        if url.lower().endswith("/emby"):                   # an Emby address copied from its dashboard
            url = url[:-5]
        if not _safe_server_url(url):
            raise EmbyError(f"type the {label} server's address, like http://192.168.1.20:8096")
        if not name or not isinstance(name, str) or not isinstance(password, str):
            raise EmbyError(f"type a {label} user name and its password")
        auth = {"Authorization": self._auth_header()} if kind == "jellyfin" else {"X-Emby-Authorization": self._auth_header()}
        code, got = self.http("POST", f"{url}{prefix}/Users/AuthenticateByName", {**auth, "Content-Type": "application/json"},
                              json.dumps({"Username": name.strip(), "Pw": password}).encode())
        if code in (400, 401, 403):
            raise EmbyError(f"that {label} server did not accept the name and password")
        tok = CTRL.sub("", str(got.get("AccessToken") or "")) if isinstance(got, dict) else ""
        uid = (got.get("User") or {}).get("Id") if isinstance(got, dict) else None
        if code != 200 or not tok or not uid:
            raise EmbyError(f"{urllib.parse.urlsplit(url).hostname} answered {code}: is that a {label} server's address?")
        code, info = self.http("GET", f"{url}{prefix}/System/Info/Public", timeout=8)
        info = info if code == 200 and isinstance(info, dict) else {}
        raw = re.sub(r"[^A-Za-z0-9]", "", str(got.get("ServerId") or info.get("Id") or uuid.uuid4().hex))[:40]
        sid = "jf-" + raw if kind == "jellyfin" else raw    # an Emby server on the Connect list keeps its entry
        with self.lock:
            cur = self.state["servers"].setdefault(sid, {"on": True, "auto": True, "libraries": [], "cap_kbps": 0})
            if not self._direct(cur):
                cur["cap_kbps"] = 0                         # from now on the cap always counts: start with the original file
            cur.update({"kind": kind, "direct": True, "url": url, "reach": url, "remote": True, "user_id": str(uid),
                        "token": tok, "gone": False, "error": None})
            cur["name"] = cur.get("name") or info.get("ServerName") or urllib.parse.urlsplit(url).hostname
            self._save()
        return self.describe()

    def remove(self, sid):
        """Take a server added by its address off the list. Its placeholders go at the next sync."""
        with self.lock:
            if not self._direct(self.state["servers"].get(sid) or {}):
                raise EmbyError("no such server added by its address")
            del self.state["servers"][sid]
            self._save()
        return self.describe()

    # ---- Emby Connect ----
    def sign_in(self, name, password):
        if not name or not password or not isinstance(name, str) or not isinstance(password, str):
            raise EmbyError("type your Emby Connect name (or email) and password")
        body = urllib.parse.urlencode({"nameOrEmail": name.strip(), "rawpw": password}).encode()
        code, got = self.http("POST", f"{CONNECT}/user/authenticate", {"X-Application": APP,
                              "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"}, body)
        if code in (400, 401, 403, 404):                     # 404: no such user (Connect's own answer)
            raise EmbyError("Emby Connect did not accept that name and password")
        if not isinstance(got, dict):
            raise EmbyError(f"Emby Connect answered {code} with something that isn't JSON "
                            f"({len(got or b'')} bytes starting {bytes(got or b'')[:1]!r})")
        token = got.get("AccessToken") or got.get("ConnectAccessToken")
        user = got.get("User") or {}
        uid = user.get("Id") or got.get("ConnectUserId")
        if not token or not uid:
            raise EmbyError("Emby Connect's answer had no token in it")
        with self.lock:
            self.state["connect"] = {"user_id": str(uid), "token": token,
                                     "name": user.get("Name") or user.get("Email") or name.strip()}
            self._save()
        return self.refresh_servers()

    def sign_out(self):
        """Forget the account and every server's token. The mirror stays, so lists keep their videos if you sign in again."""
        with self.lock:
            self.state["connect"] = None
            for s in self.state["servers"].values():
                if not self._direct(s):                     # a server added by address has a sign-in of its own
                    s.pop("token", None)
                    s.pop("access_key", None)
            self._save()

    def refresh_servers(self):
        """The account's servers from Emby Connect. Choices made for a server (on, libraries, cap) are kept."""
        conn = self.state.get("connect")
        if not conn:
            raise EmbyError("sign in with Emby Connect first")
        code, got = self.http("GET", f"{CONNECT}/servers?userId={urllib.parse.quote(conn['user_id'])}",
                              {"X-Application": APP, "X-Connect-UserToken": conn["token"]})
        if code in (401, 403):
            raise EmbyError("Emby Connect signed this tuner out: sign in again")
        if code != 200 or not isinstance(got, list):
            raise EmbyError(f"Emby Connect answered {code} for the server list")
        with self.lock:
            servers = self.state["servers"]
            for s in got:
                sid = str(s.get("SystemId") or "")
                if not sid:
                    continue
                cur = servers.setdefault(sid, {"on": False, "auto": True, "libraries": [], "cap_kbps": REMOTE_CAP_KBPS})
                cur.update({"name": s.get("Name") or sid, "url": (s.get("Url") or "").rstrip("/"),
                            "local": (s.get("LocalAddress") or "").rstrip("/"), "access_key": s.get("AccessKey")})
                cur["gone"] = False
            for sid, cur in servers.items():
                if not self._direct(cur) and sid not in {str(s.get("SystemId")) for s in got}:
                    cur["gone"] = True                       # no longer on the account: kept (with its choices), not played
            self._save()
        return self.describe()

    def _reach(self, sid):
        """Exchange the access key for this server's own token, on the first address that answers (LAN first)."""
        s = self.state["servers"][sid]
        if self._direct(s):                                  # its password was never kept, so there is nothing to retry with
            with self.lock:
                s["error"] = "signed out: add this server again"
                self._save()
            raise EmbyError(f"{s.get('name', sid)}: add this server again (it no longer accepts the sign-in)")
        if not s.get("access_key") or not self.state.get("connect"):
            raise EmbyError(f"{s.get('name', sid)}: sign in with Emby Connect again")
        why = "no address"
        for base in [u for u in (s.get("local"), s.get("url")) if _safe_server_url(u)]:
            try:
                code, got = self.http("GET", f"{base}/emby/Connect/Exchange?format=json&ConnectUserId="
                                      + urllib.parse.quote(self.state["connect"]["user_id"]),
                                      {"X-Emby-Token": s["access_key"], "X-Emby-Authorization": self._auth_header()}, timeout=8)
            except EmbyError as e:
                why = str(e)
                continue
            if code == 200 and isinstance(got, dict) and got.get("AccessToken"):
                tok = CTRL.sub("", str(got["AccessToken"]))
                if not tok:
                    continue
                with self.lock:
                    s.update({"reach": base, "remote": base != s.get("local"), "user_id": got.get("LocalUserId"),
                              "token": tok, "error": None})
                    self._save()
                return s
            why = f"{base} answered {code}"
        with self.lock:
            s["error"] = why
            self._save()
        raise EmbyError(f"{s.get('name', sid)}: {why}")

    def _api(self, sid, path, params=None):
        s = self.state["servers"][sid]
        for attempt in (1, 2):
            if not s.get("token") or attempt == 2:            # none yet, or it went stale: exchange (again)
                s = self._reach(sid)
            url = f"{self._base(s)}{path}" + ("?" + urllib.parse.urlencode(params) if params else "")
            code, got = self.http("GET", url, self._headers(s, s["token"]))
            if code != 401:
                break
        if code != 200:
            raise EmbyError(f"{s.get('name', sid)} answered {code} for {path.split('?')[0]}")
        return got

    def libraries(self, sid):
        if sid not in self.state["servers"]:
            raise EmbyError("no such server")
        s = self.state["servers"][sid]
        if not s.get("user_id"):
            s = self._reach(sid)
        got = self._api(sid, f"/Users/{s['user_id']}/Views")
        found = [{"id": v["Id"], "name": v.get("Name") or v["Id"], "kind": v.get("CollectionType") or "mixed"}
                 for v in (got or {}).get("Items", []) if v.get("Id")]
        if s.get("auto"):                                    # new to the list: its video libraries are chosen for you, once
            with self.lock:
                s["libraries"] = [lib["id"] for lib in found if lib["kind"] in AUTO_KINDS][:50]
                s.pop("auto")
                self._save()
        return found

    def choose(self, sid, on=None, libraries=None, cap_kbps=None):
        with self.lock:
            s = self.state["servers"].get(sid)
            if s is None:
                raise EmbyError("no such server")
            if on is not None:
                s["on"] = bool(on)
            if libraries is not None:
                if not isinstance(libraries, list) or not all(isinstance(x, str) for x in libraries):
                    raise EmbyError("libraries must be a list of ids")
                s["libraries"] = libraries[:50]
                s.pop("auto", None)                          # chosen by hand before the first look
            if cap_kbps is not None:
                try:
                    cap = int(cap_kbps)
                except (TypeError, ValueError):
                    raise EmbyError("the cap is a whole number of kbps (0 = the original file)")
                if cap and not 500 <= cap <= 100000:
                    raise EmbyError("the cap is 0 (original file) or 500 to 100000 kbps")
                s["cap_kbps"] = cap
            self._save()
        return self.describe()

    def describe(self):
        """For the Sources page: no tokens or keys."""
        with self.lock:
            conn = self.state.get("connect")
            return {"signed_in": bool(conn), "account": conn and conn.get("name"), "status": dict(self.status),
                    "servers": [{"id": sid, "name": s.get("name"), "on": s.get("on", False), "libraries": s.get("libraries", []),
                                 "cap_kbps": s.get("cap_kbps"), "remote": s.get("remote"), "error": s.get("error"),
                                 "gone": s.get("gone", False), "folder": clean_name(s.get("name"), sid), "auto": bool(s.get("auto")),
                                 "kind": s.get("kind", "emby"), "direct": self._direct(s)}
                                for sid, s in sorted(self.state["servers"].items(), key=lambda kv: str(kv[1].get("name")).lower())]}

    # ---- the mirror ----
    def _index_path(self):
        return os.path.join(self.mirror, ".index.json")

    def _read_index(self):
        try:
            with open(self._index_path()) as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def sync(self):
        """Make the mirror match the chosen libraries: placeholders made for new or changed items, removed for gone ones.
        A server that can't be reached keeps its placeholders (they come back when it does). Returns the counts."""
        if not self.sync_lock.acquire(blocking=False):
            raise Busy("the servers are already being scanned")
        self.status.update(syncing=True, error=None, library="", read=0, total=0)
        counts = {"made": 0, "kept": 0, "removed": 0, "servers": 0, "lists": 0}
        errors, read = [], []                          # read: (server id, library id, its folder in the mirror)
        try:
            index = self._read_index()                 # {rel path: [server id, item id, key]}
            keep = set()
            for sid, s in list(self.state["servers"].items()):
                if not s.get("on") or s.get("gone") or not (s.get("libraries") or s.get("auto")):
                    continue
                folder = clean_name(s.get("name"), sid)
                try:
                    libs = {lib["id"]: lib["name"] for lib in self.libraries(sid)}
                    for lid in s["libraries"]:
                        if lid not in libs:
                            continue
                        read.append((sid, lid, f"{folder}/{clean_name(libs[lid])}"))
                        self.status.update(library=f"{s.get('name') or folder} - {libs[lid]}", read=0, total=0)   # for the page's bar
                        items = self._items(sid, lid)
                        self.status["total"] = len(items)
                        for n, item in enumerate(items):
                            self.status["read"] = n
                            rel = item_rel(item, read[-1][2])
                            if rel in keep:                          # two items with the same name: keep both
                                rel = rel[:-4] + f" [{item['Id']}].mkv"
                            if rel in keep:
                                continue
                            keep.add(rel)
                            key = item_key(item)
                            old = index.get(rel)
                            full = os.path.join(self.mirror, rel)
                            if old and old[1] == item["Id"] and old[2] == key and os.path.exists(full):
                                counts["kept"] += 1
                                continue
                            chapters = [(c.get("StartPositionTicks") or 0) / 1e7 for c in item.get("Chapters") or []]
                            make_placeholder(full, item["RunTimeTicks"] / 1e7, chapters, self.ffmpeg)
                            with open(full[:-4] + ".nfo", "w", encoding="utf-8") as f:
                                f.write(nfo(item))
                            self._poster(sid, item, full)
                            index[rel] = [sid, item["Id"], key]
                            counts["made"] += 1
                    counts["servers"] += 1
                except EmbyError as e:                       # unreachable: leave this server's placeholders as they are
                    errors.append(str(e))
                    keep |= {r for r, v in index.items() if v[0] == sid}
            gone = [r for r in index if r not in keep]
            try:
                # FieldStation42 stops a whole catalog build at a link whose video vanishes under it, so wait for a
                # running build to end (schedlock.py). The next build drops the dead links before it starts.
                waiting = f"[emby] mirror: waiting for a build to end before removing {len(gone)} video(s) that are gone"
                with schedlock.held(on_wait=lambda: self.log(waiting, flush=True)) if gone else contextlib.nullcontext():
                    for rel in gone:
                        for p in (rel, rel[:-4] + ".nfo"):
                            try:
                                os.remove(os.path.join(self.mirror, p))
                            except OSError:
                                pass
                        index.pop(rel)
                        counts["removed"] += 1
            except schedlock.LockTimeout:
                pass                                         # still building: they stay, and go at the next scan
            self._tidy()
            os.makedirs(self.mirror, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=self.mirror, prefix=".index-")
            with os.fdopen(fd, "w") as f:
                json.dump(index, f)
            os.replace(tmp, self._index_path())
            for sid, lid, rel in read if self.on_sync else ():     # a list for each library read for the first time
                s = self.state["servers"][sid]
                if lid in s.get("listed", ()) or not os.path.isdir(os.path.join(self.mirror, rel)):
                    continue                                 # (an empty library has no folder yet: asked again next time)
                try:
                    self.on_sync(rel)
                except Exception as e:
                    errors.append(f"no list made for {rel}: {e}")
                    continue
                with self.lock:
                    s.setdefault("listed", []).append(lid)
                    self._save()
                counts["lists"] += 1
            self.status.update(last=time.time(), counts=counts, error="; ".join(errors)[:500] or None)
            return counts
        finally:
            self.status["syncing"] = False
            self.sync_lock.release()

    def _items(self, sid, lib):
        uid = self.state["servers"][sid].get("user_id")
        start, out = 0, []
        while len(out) < MAX_ITEMS:
            got = self._api(sid, f"/Users/{uid}/Items", {
                "ParentId": lib, "Recursive": "true", "IncludeItemTypes": TYPES, "IsMissing": "false",
                "Fields": "Chapters,Overview,Genres,PremiereDate,ProductionYear,SeriesId,ImageTags",
                "SortBy": "SortName", "StartIndex": start, "Limit": PAGE}) or {}
            page = got.get("Items") or []
            out += [i for i in page if i.get("Id") and (i.get("RunTimeTicks") or 0) > 2e7 and i.get("LocationType") != "Virtual"]
            start += len(page)
            if len(page) < PAGE or start >= (got.get("TotalRecordCount") or 0):
                break
        return out

    def _poster(self, sid, item, full):
        """The show's or movie's poster beside it, once, so the guide has a picture (art.py looks for poster.jpg)."""
        if item.get("Type") == "Episode":
            target, owner = os.path.join(os.path.dirname(os.path.dirname(full)), "poster.jpg"), item.get("SeriesId")
        elif item.get("Type") == "Movie":
            target, owner = os.path.join(os.path.dirname(full), "poster.jpg"), item["Id"]
        else:
            return
        if not owner or os.path.exists(target):
            return
        s = self.state["servers"][sid]
        try:
            code, got = self.http("GET", f"{self._base(s)}/Items/{owner}/Images/Primary?maxWidth=400&format=jpg",
                                  self._headers(s, s["token"]))
        except EmbyError:
            return
        if code == 200 and isinstance(got, bytes) and got[:2] == b"\xff\xd8":
            with open(target, "wb") as f:
                f.write(got)

    def _tidy(self):
        """Remove the folders removals emptied: a folder with no placeholders and no folders left (a poster doesn't count)."""
        for root, dirs, files in os.walk(self.mirror, topdown=False):
            if root == self.mirror or any(os.path.isdir(os.path.join(root, d)) for d in dirs) \
                    or any(f.endswith(".mkv") for f in files):
                continue
            for f in files:
                os.remove(os.path.join(root, f))
            os.rmdir(root)

    def loop(self, hours=6, first_delay=90):
        time.sleep(first_delay)
        while True:
            if any(s.get("on") for s in self.state["servers"].values()):
                try:
                    c = self.sync()
                    self.log(f"[emby] mirror: {c['made']} made, {c['kept']} unchanged, {c['removed']} removed"
                             + (f"; {self.status['error']}" if self.status.get("error") else ""), flush=True)
                except Busy:                             # one you asked for is running: this turn is not needed
                    pass
                except Exception as e:
                    self.status["error"] = str(e)[:500]
                    self.log(f"[emby] mirror: {e}", flush=True)
            time.sleep(hours * 3600)

    # ---- playing ----
    def lookup(self, real_path):
        """(server id, item id) for a placeholder's real path, or None for anything else."""
        root = os.path.realpath(self.mirror).rstrip("/") + "/"
        if not real_path.startswith(root):
            return None
        try:
            stamp = os.stat(self._index_path()).st_mtime_ns
        except OSError:
            return None
        if stamp != self._index_at:
            self._index, self._index_at = self._read_index(), stamp
        hit = self._index.get(real_path[len(root):])
        return (hit[0], hit[1]) if hit else None

    def still(self, sid, item_id, width=320):
        """A small JPEG of an item for the dashboard's tile: its backdrop (a film), else its own picture (an episode's
        frame). None when the server has none or does not answer. A placeholder's own frames are black, and reading
        one real frame could start a transcode on somebody else's server, so this asks for a picture it already has."""
        s = self.state["servers"].get(sid)
        if s is None or not s.get("token"):
            return None
        safe_item = urllib.parse.quote(str(item_id), safe="")
        for kind in ("Backdrop", "Primary"):
            try:
                code, got = self.http("GET", f"{self._base(s)}/Items/{safe_item}/Images/{kind}?maxWidth={int(width)}&format=jpg",
                                      self._headers(s, s["token"]), timeout=8)
            except EmbyError:
                return None
            if code == 200 and isinstance(got, bytes) and got[:2] == b"\xff\xd8":
                return got
        return None

    def input_for(self, sid, item_id, seek):
        """{"opts": ffmpeg options before -i, "url", "seek": what to pass as -ss, "done": call when finished} to read an
        item from `seek` seconds. The token goes in a header, never in the address (which is logged)."""
        s = self.state["servers"].get(sid)
        if s is None:
            raise EmbyError("that server is not on the account any more")
        if not s.get("token"):
            s = self._reach(sid)
        tok = CTRL.sub("", str(s["token"]))
        headers = "".join(f"{k}: {v}\r\n" for k, v in self._headers(s, tok).items())
        opts = ["-headers", headers, "-reconnect", "1", "-reconnect_on_network_error", "1", "-reconnect_delay_max", "5",
                "-rw_timeout", "15000000"]
        base, dev = self._base(s), urllib.parse.quote(str(self.state["device_id"]), safe="")
        safe_item = urllib.parse.quote(str(item_id), safe="")
        cap = (s.get("cap_kbps") or 0) if s.get("remote") else 0      # on the LAN: always the original file
        if not cap:
            return {"opts": opts, "url": f"{base}/Videos/{safe_item}/stream?static=true&DeviceId={dev}", "seek": seek,
                    "done": lambda: None}
        session = uuid.uuid4().hex
        q = urllib.parse.urlencode({"VideoCodec": "h264", "AudioCodec": "aac", "VideoBitrate": cap * 1000,
                                    "AudioBitrate": 192000, "MaxAudioChannels": 2, "StartTimeTicks": int(seek * 1e7),
                                    "DeviceId": dev, "PlaySessionId": session})

        def done():                                  # tell the server to stop making it now, not when it notices
            try:
                self.http("DELETE", f"{base}/Videos/ActiveEncodings?DeviceId={dev}&PlaySessionId={session}",
                          self._headers(s, tok), timeout=5)
            except EmbyError:
                pass
        return {"opts": opts, "url": f"{base}/Videos/{safe_item}/stream.ts?{q}", "seek": 0.0, "done": done}
