"""What a player PC in client mode (FS42_ROLE=client) copies from this server, under /sync/ on the tuner's port.

The server builds every schedule; a client only plays it. A client asks /sync/state about once a minute. That answer
carries one hash per part, and the client fetches only the parts whose hash changed:

  GET  /sync/state     the hashes, the versions this server runs, its time zone     (ETag: 304 when nothing changed)
  GET  /sync/db        the schedule database: a consistent sqlite copy, gzipped
  GET  /sync/confs     the station configs: {file name: text}
  GET  /sync/catalog   the catalog: {"links": {path: target}, "files": {path: [size, mtime]}, "dirs": [path]}, gzipped
  GET  /sync/file?path=one real file of the catalog (a bump card, an .nfo)
  GET  /sync/sources   the Sources page list
  POST /sync/hello     the client says who it is, what it runs and what is wrong; the Status page lists it. The answer
                       is its settings from the Settings page: {"settings": {KEY: "value"}}

Every call needs "Authorization: Bearer <the token>": FS42_SYNC_TOKEN when it is set, else one this server makes once
and keeps beside the tuner's config (load_token); the Settings page shows it for copying into a player's .env. It only reads.
"""
import gzip
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import tempfile
import threading
import time

SKIP_DIRS = {".prefetch", ".tmdb_cache"}      # caches the server makes for itself
SKIP_PATHS = {"media-links/Emby"}             # Emby placeholders (emby.py): a player streams those channels from the tuner
CACHE_SECONDS = 30                            # how long a computed part is reused: a minute's polls by many clients cost one walk
STALE_SECONDS = 300                           # a player not heard from for this long is reported as gone
FORGET_SECONDS = 24 * 3600                    # ...and after this long it is dropped from the list


def load_token(given, path):
    """(token, "env" | "made") a player must send: FS42_SYNC_TOKEN when it is set, else one made here once and kept in
    `path` (readable by its owner only). ("", None) when it can be neither read nor made: client sync is then off."""
    if (given or "").strip():
        return given.strip(), "env"
    try:
        with open(path) as f:
            token = f.read().strip()
    except FileNotFoundError:
        token = ""
    except OSError:
        return "", None
    if token:
        return token, "made"
    token = secrets.token_urlsafe(24)
    try:
        with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as f:
            f.write(token + "\n")
    except OSError:
        return "", None
    return token, "made"


def _h(data):
    return hashlib.sha1(data, usedforsecurity=False).hexdigest()      # a change detector, not security


class Feed:
    def __init__(self, token, db_path, confs_dir, catalog_dir, sources_path, versions=None, clock=time.time,
                 player_settings=None):
        self.token = (token or "").strip()
        self.db_path, self.confs_dir, self.catalog_dir, self.sources_path = db_path, confs_dir, catalog_dir, sources_path
        self.versions = versions or {}                 # {"wrapper": sha, "fieldstation42": commit}
        self.clock = clock
        self._lock = threading.Lock()
        self._cache = {}                               # part -> (computed at, signature, body bytes, hash)
        self._players = {}                             # name -> report
        self.player_settings = player_settings or (lambda name: {})   # name -> {KEY: value} set on the Settings page

    @property
    def enabled(self):
        return bool(self.token)

    # -- the parts ---------------------------------------------------------
    def _part(self, name, make, sig=None):
        """(body, hash) of one part, made again only when its signature changed or it is older than CACHE_SECONDS."""
        now = self.clock()
        with self._lock:
            hit = self._cache.get(name)
            if hit and (hit[1] == sig if sig is not None else now - hit[0] < CACHE_SECONDS):
                return hit[2], hit[3]
        body = make()
        with self._lock:
            self._cache[name] = (now, sig, body, _h(body))
            return body, self._cache[name][3]

    def _db_sig(self):
        sig = []
        for p in (self.db_path, self.db_path + "-wal"):
            try:
                st = os.stat(p)
                sig.append((st.st_mtime_ns, st.st_size))
            except OSError:
                sig.append(None)
        return tuple(sig)

    def _db(self):
        """The schedule database, copied with sqlite's backup API (the file itself is live and may be half-written)."""
        fd, tmp = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            src = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
            dst = sqlite3.connect(tmp)
            with dst:
                src.backup(dst)
            dst.close()
            src.close()
            with open(tmp, "rb") as f:
                return gzip.compress(f.read(), 6, mtime=0)
        finally:
            os.unlink(tmp)

    def _confs(self):
        out = {}
        for f in sorted(os.listdir(self.confs_dir)):
            if f.endswith(".json") and f != "main_config.json":
                with open(os.path.join(self.confs_dir, f), encoding="utf-8") as fh:
                    out[f] = fh.read()
        return json.dumps(out, sort_keys=True).encode()

    def manifest(self):
        """Every link (and where it points), real file (size, mtime) and folder in the catalog. A link is never followed:
        the catalog is tens of thousands of links into the media share, and looking at what each points to (os.walk does,
        to tell folders from files) is a network round trip each, which made this take most of a minute."""
        links, files, dirs = {}, {}, []
        root = self.catalog_dir
        stack = [root]
        while stack:
            d = stack.pop()
            if d != root:
                dirs.append(os.path.relpath(d, root))
            try:
                entries = list(os.scandir(d))
            except OSError:
                continue
            for e in entries:
                rel = os.path.relpath(e.path, root)
                try:
                    if e.is_symlink():                  # a linked folder is a link too, not somewhere to walk into
                        links[rel] = os.readlink(e.path)
                    elif e.name in SKIP_DIRS or rel in SKIP_PATHS:
                        continue
                    elif e.is_dir(follow_symlinks=False):
                        stack.append(e.path)
                    else:
                        st = e.stat(follow_symlinks=False)
                        files[rel] = [st.st_size, st.st_mtime_ns // 1_000_000_000]
                except OSError:
                    continue
        return {"links": links, "files": files, "dirs": sorted(dirs)}

    def _catalog(self):
        return gzip.compress(json.dumps(self.manifest(), sort_keys=True).encode(), 6, mtime=0)

    def _sources(self):
        try:
            with open(self.sources_path, "rb") as f:
                return f.read()
        except FileNotFoundError:
            return b"[]"

    def parts(self):
        return {"db": self._part("db", self._db, self._db_sig()), "confs": self._part("confs", self._confs),
                "catalog": self._part("catalog", self._catalog), "sources": self._part("sources", self._sources)}

    def state(self):
        hashes = {k: h for k, (_, h) in self.parts().items()}
        tz = time.strftime("%Z %z")                   # what the clock says here: a player must say the same
        return {"parts": hashes, "versions": self.versions, "tz": tz}

    # -- players -------------------------------------------------------------
    def hello(self, report, addr):
        name = str(report.get("name") or addr)[:64]
        keep = {k: report.get(k) for k in ("versions", "channel", "last_sync", "errors", "screen", "tz", "env", "applied")}
        for k in ("env", "applied"):          # its settings from its compose file, and those it runs with: strings only
            v = keep[k]
            keep[k] = {str(a)[:64]: str(b)[:500] for a, b in v.items() if isinstance(b, str)} if isinstance(v, dict) else None
        with self._lock:
            self._players[name] = dict(keep, name=name, addr=addr, seen=self.clock())
        return {"settings": self.player_settings(name)}

    def players(self):
        now = self.clock()
        with self._lock:
            for name in [n for n, p in self._players.items() if now - p["seen"] > FORGET_SECONDS]:
                del self._players[name]                # a player gone for a day was retired, not broken
            out = []
            for p in sorted(self._players.values(), key=lambda p: p["name"]):
                p = dict(p, age=round(now - p["seen"]))
                p["gone"] = p["age"] > STALE_SECONDS
                p["mismatch"] = bool(self.versions) and (p.get("versions") or {}) != self.versions
                out.append(p)
            return out

    # -- HTTP ---------------------------------------------------------------
    def handle(self, method, path, query, headers, body, addr):
        """(status, [(header, value)], body bytes) for one /sync/ request."""
        if not self.enabled:
            return 404, [], b"client sync is off on this server (its token could not be made: set FS42_SYNC_TOKEN)"
        got = (headers.get("Authorization") or "").removeprefix("Bearer ").strip()
        if not hmac.compare_digest(got.encode(), self.token.encode()):
            return 403, [], b"wrong or missing sync token"
        try:
            if method == "POST" and path == "/sync/hello":
                got = self.hello(json.loads(body or b"{}"), addr)
                return 200, [("Content-Type", "application/json")], json.dumps(got).encode()
            if method != "GET":
                return 405, [], b""
            if path == "/sync/state":
                st = json.dumps(self.state(), sort_keys=True).encode()
                tag = '"' + _h(st) + '"'
                if headers.get("If-None-Match") == tag:
                    return 304, [("ETag", tag)], b""
                return 200, [("ETag", tag), ("Content-Type", "application/json")], st
            if path in ("/sync/db", "/sync/confs", "/sync/catalog", "/sync/sources"):
                data, h = self.parts()[path[len("/sync/"):]]
                ctype = "application/gzip" if path in ("/sync/db", "/sync/catalog") else "application/json"
                return 200, [("ETag", '"' + h + '"'), ("Content-Type", ctype)], data
            if path == "/sync/file":
                rel = (query.get("path") or [""])[0]
                root = os.path.realpath(self.catalog_dir)
                p = os.path.realpath(os.path.join(root, rel))
                if not rel or os.path.commonpath([root, p]) != root or not os.path.isfile(p):
                    return 404, [], b"no such file in the catalog"
                with open(p, "rb") as f:
                    return 200, [("Content-Type", "application/octet-stream")], f.read()
        except (OSError, sqlite3.Error, ValueError) as e:
            return 500, [], f"sync: {e}".encode()
        return 404, [], b""


# -- TV apps -----------------------------------------------------------------
APP_UA = re.compile(r"^FS42TV/([\w.-]{1,16}) \(([^;()]{1,32}); ([^()]{0,64})\)")


class AppPlayers:
    """The FS42 TV apps (Android TV, Apple TV) seen watching a channel. They are not client-mode players (they don't sync,
    they only stream /auto/v<n>), so they say who they are in their User-Agent instead:
        FS42TV/0.1 (Android TV; Living Room TV)
    The Status page lists them under Players with the client-mode boxes."""

    def __init__(self, clock=time.time):
        self.clock = clock
        self._lock = threading.Lock()
        self._apps = {}                                # (name, addr) -> {..., "streams": open streams}

    @staticmethod
    def parse(user_agent):
        """(version, platform, name) from an FS42 TV User-Agent, or None for anything else (Emby, a browser, VLC)."""
        m = APP_UA.match(user_agent or "")
        return (m.group(1), m.group(2).strip(), m.group(3).strip()) if m else None

    def joined(self, user_agent, addr, channel):
        """A stream started. The key to pass to left(), or None when it isn't one of the apps."""
        got = self.parse(user_agent)
        if got is None:
            return None
        version, platform, name = got
        key = (name or addr, addr)
        with self._lock:
            a = self._apps.setdefault(key, {"streams": 0})
            a.update(name=key[0], addr=addr, platform=platform, version=version, channel=str(channel), seen=self.clock(),
                     kind="app")
            a["streams"] += 1                          # the Apple TV app opens the next channel before closing the old one
        return key

    def left(self, key):
        if key is None:
            return
        with self._lock:
            a = self._apps.get(key)
            if a:
                a["streams"] = max(0, a["streams"] - 1)
                a["seen"] = self.clock()

    def players(self):
        now = self.clock()
        with self._lock:
            for k in [k for k, a in self._apps.items() if not a["streams"] and now - a["seen"] > FORGET_SECONDS]:
                del self._apps[k]
            out = []
            for a in sorted(self._apps.values(), key=lambda a: a["name"]):
                watching = a["streams"] > 0
                out.append({k: v for k, v in a.items() if k != "streams"} | {"watching": watching,
                           "age": 0 if watching else round(now - a["seen"])})
            return out

