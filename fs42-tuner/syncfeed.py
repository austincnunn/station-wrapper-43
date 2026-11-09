"""What a player PC in client mode (FS42_ROLE=client) copies from this server, under /sync/ on the tuner's port.

The server builds every schedule; a client only plays it. A client asks /sync/state about once a minute. That answer
carries one hash per part, and the client fetches only the parts whose hash changed:

  GET  /sync/state     the hashes, the versions this server runs, its time zone     (ETag: 304 when nothing changed)
  GET  /sync/db        the schedule database: a consistent sqlite copy, gzipped
  GET  /sync/confs     the station configs: {file name: text}
  GET  /sync/catalog   the catalog: {"links": {path: target}, "files": {path: [size, mtime]}, "dirs": [path]}, gzipped
  GET  /sync/file?path=one real file of the catalog (a bump card, an .nfo)
  GET  /sync/sources   the Sources page list
  POST /sync/hello     the client says who it is, what it runs and what is wrong; the Status page lists it

Off unless FS42_SYNC_TOKEN is set. Every call needs "Authorization: Bearer <that token>". It only reads.
"""
import gzip
import hashlib
import hmac
import json
import os
import sqlite3
import tempfile
import threading
import time

SKIP_DIRS = {".prefetch", ".tmdb_cache"}      # caches the server makes for itself
CACHE_SECONDS = 30                            # how long a computed part is reused: a minute's polls by many clients cost one walk
STALE_SECONDS = 300                           # a player not heard from for this long is reported as gone
FORGET_SECONDS = 24 * 3600                    # ...and after this long it is dropped from the list


def _h(data):
    return hashlib.sha1(data, usedforsecurity=False).hexdigest()      # a change detector, not security


class Feed:
    def __init__(self, token, db_path, confs_dir, catalog_dir, sources_path, versions=None, clock=time.time):
        self.token = (token or "").strip()
        self.db_path, self.confs_dir, self.catalog_dir, self.sources_path = db_path, confs_dir, catalog_dir, sources_path
        self.versions = versions or {}                 # {"wrapper": sha, "fieldstation42": commit}
        self.clock = clock
        self._lock = threading.Lock()
        self._cache = {}                               # part -> (computed at, signature, body bytes, hash)
        self._players = {}                             # name -> report

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
        links, files, dirs = {}, {}, []
        root = self.catalog_dir
        for d, subdirs, names in os.walk(root):
            rel_d = os.path.relpath(d, root)
            if rel_d != ".":
                dirs.append(rel_d)
            keep = []
            for s in subdirs:
                p = os.path.join(d, s)
                if s in SKIP_DIRS:
                    continue
                if os.path.islink(p):                  # a linked folder is a link, not somewhere to walk into
                    links[os.path.relpath(p, root)] = os.readlink(p)
                else:
                    keep.append(s)
            subdirs[:] = keep
            for n in names:
                p = os.path.join(d, n)
                rel = os.path.relpath(p, root)
                if os.path.islink(p):
                    links[rel] = os.readlink(p)
                else:
                    try:
                        st = os.stat(p)
                    except OSError:
                        continue
                    files[rel] = [st.st_size, st.st_mtime_ns // 1_000_000_000]
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
        keep = {k: report.get(k) for k in ("versions", "channel", "last_sync", "errors", "screen", "tz")}
        with self._lock:
            self._players[name] = dict(keep, name=name, addr=addr, seen=self.clock())

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
            return 404, [], b"client sync is off on this server (set FS42_SYNC_TOKEN)"
        got = (headers.get("Authorization") or "").removeprefix("Bearer ").strip()
        if not hmac.compare_digest(got.encode(), self.token.encode()):
            return 403, [], b"wrong or missing sync token"
        try:
            if method == "POST" and path == "/sync/hello":
                self.hello(json.loads(body or b"{}"), addr)
                return 204, [], b""
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
