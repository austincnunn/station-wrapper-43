"""What Emby or Jellyfin knows about a video: its show, episode title, synopsis, air date, genres and poster, for the guide.

A library that Emby or Jellyfin manages has its metadata in the server's database, not in .nfo files beside the videos. The
server has already matched every file to its show and episode, so one request for all its episodes and movies (with their file
paths) answers "what is this file" for every video the channels play, without matching names again.

Set MEDIA_SERVER_URL (http://192.168.1.3:8096) and MEDIA_SERVER_API_KEY (Emby: Dashboard > Advanced > API Keys; Jellyfin:
Dashboard > API Keys). Either server works: the two speak the same API, apart from how the key is sent, and both ways are sent.
The server sees the media at its own path (MEDIA_SERVER_MEDIA_ROOT, /media by default); a file is matched by its path below
that, against its path below this container's media root.

The answer is kept on disk and asked for again every MEDIA_SERVER_REFRESH_HOURS (6). A server that can't be reached is logged
and the last answer kept: the guide never waits on it, and without it names come from the .nfo files and file names as before.
"""
import json
import os
import tempfile
import threading
import time
import urllib.parse
import urllib.request

URL = os.environ.get("MEDIA_SERVER_URL", "").strip().rstrip("/")
KEY = os.environ.get("MEDIA_SERVER_API_KEY", "").strip()
SERVER_ROOT = os.environ.get("MEDIA_SERVER_MEDIA_ROOT", "/media").rstrip("/")
REFRESH_HOURS = float(os.environ.get("MEDIA_SERVER_REFRESH_HOURS", "6") or 6)
PAGE = 2000
TIMEOUT = 60
TYPES = "Episode,Movie,MusicVideo"
FIELDS = "Path,Overview,Genres,PremiereDate,ProductionYear,SeriesPrimaryImageTag"


def _rel(path, root):
    """`path` below `root` ("tv/Show/Season 1/x.mkv"), or None when it is not below it."""
    path, root = path.replace("\\", "/"), root.rstrip("/")
    return path[len(root) + 1:] if root and path.startswith(root + "/") else None


def record(item, url=""):
    """What the guide wants from one item of the server's answer, or None for an item that is neither an episode nor a movie."""
    kind = {"Episode": "episode", "Movie": "movie", "MusicVideo": "movie"}.get(item.get("Type"))
    if not kind or not item.get("Name"):
        return None
    rec = {"kind": kind, "title": (item.get("SeriesName") if kind == "episode" else None) or item["Name"],
           "episode_name": item["Name"] if kind == "episode" and item.get("SeriesName") else None}
    if kind == "episode":
        for key, field in (("season", "ParentIndexNumber"), ("episode", "IndexNumber")):
            if isinstance(item.get(field), int):
                rec[key] = item[field]
    if item.get("Overview"):
        rec["plot"] = " ".join(str(item["Overview"]).split())[:600]
    aired = str(item.get("PremiereDate") or "")[:10]
    if len(aired) == 10 and aired[4] == "-":
        rec["aired"] = aired
    if isinstance(item.get("ProductionYear"), int):
        rec["year"] = item["ProductionYear"]
    genres = [str(g)[:60] for g in item.get("Genres") or [] if g][:6]
    if kind == "movie" and not any(g.lower() in ("movie", "film") for g in genres):
        genres.insert(0, "Movie")
    if genres:
        rec["genres"] = genres
    # one picture per series, as the guide has always done (art.py); a movie's own
    if url and kind == "episode" and item.get("SeriesId") and item.get("SeriesPrimaryImageTag"):
        rec["image"] = f"{url}/Items/{item['SeriesId']}/Images/Primary?maxWidth=640"
    elif url and (item.get("ImageTags") or {}).get("Primary"):
        rec["image"] = f"{url}/Items/{item['Id']}/Images/Primary?maxWidth=640"
    return rec


class Library:
    """The server's episodes and movies by their path below the media root. lookup() never touches the network."""

    def __init__(self, url=URL, key=KEY, server_root=SERVER_ROOT, cache=None, log=print, fetch=None):
        self.url, self.key, self.server_root, self.log = url, key, server_root, log
        self.cache = cache
        self.fetch = fetch or self._get
        self.by_path = {}
        self.kind = None
        self.updated = None
        self.error = None
        self.on_change = None
        self._lock = threading.Lock()
        self._load()

    @property
    def enabled(self):
        return bool(self.url and self.key)

    # -- the server
    def _get(self, path, params=None):
        q = ("?" + urllib.parse.urlencode(params)) if params else ""
        req = urllib.request.Request(self.url + path + q, headers={
            "Accept": "application/json",
            "X-Emby-Token": self.key,                                   # Emby
            "Authorization": f'MediaBrowser Token="{self.key}"',        # Jellyfin (its X-Emby-Token is off by default now)
        })
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:  # nosec B310: the address is the owner's own setting
            return json.load(r)

    def image(self, url):
        """The bytes of a picture the server named (a record's "image"), or None when it is not the server's."""
        if not (self.enabled and url.startswith(self.url + "/")):
            return None
        req = urllib.request.Request(url, headers={"X-Emby-Token": self.key, "Authorization": f'MediaBrowser Token="{self.key}"'})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:  # nosec B310: the address is the owner's own setting
            return r.read(8 * 1024 * 1024)

    def refresh(self):
        """Ask the server for everything again. True when it answered."""
        if not self.enabled:
            return False
        try:
            info = self.fetch("/System/Info/Public")
            kind = "Jellyfin" if "jellyfin" in str(info.get("ProductName", "")).lower() else "Emby"
            found, start = {}, 0
            while True:
                page = self.fetch("/Items", {"Recursive": "true", "IncludeItemTypes": TYPES, "Fields": FIELDS,
                                             "EnableImageTypes": "Primary", "ImageTypeLimit": "1",
                                             "StartIndex": str(start), "Limit": str(PAGE)})
                items = page.get("Items") or []
                for item in items:
                    rel = _rel(str(item.get("Path") or ""), self.server_root)
                    rec = record(item, self.url) if rel else None
                    if rec:
                        found[rel] = rec
                start += len(items)
                if not items or start >= int(page.get("TotalRecordCount") or 0):
                    break
        except Exception as e:                         # unreachable, a wrong key, an answer we can't read: keep what we had
            self.error = f"{type(e).__name__}: {e}"[:300]
            self.log(f"[mediaserver] could not read {self.url}: {self.error}", flush=True)
            return False
        with self._lock:
            self.by_path, self.kind, self.updated, self.error = found, kind, time.time(), None
        self._save()
        self.log(f"[mediaserver] {kind} at {self.url}: {len(found)} episodes and movies", flush=True)
        if not found:
            self.log(f"[mediaserver] none of them is below {self.server_root}: set MEDIA_SERVER_MEDIA_ROOT to the folder "
                     "the server sees your media in", flush=True)
        if self.on_change:
            self.on_change()
        return True

    def run(self, stop=None):
        """Refresh now and every REFRESH_HOURS, until `stop` (an Event) is set. A failure is tried again in 10 minutes."""
        stop = stop or threading.Event()
        while not stop.is_set():
            ok = self.refresh()
            stop.wait(REFRESH_HOURS * 3600 if ok else 600)

    def start(self):
        if self.enabled:
            threading.Thread(target=self.run, daemon=True, name="mediaserver").start()

    # -- the answer, kept on disk so a restart has names at once
    def _load(self):
        if not self.cache:
            return
        try:
            with open(self.cache) as f:
                data = json.load(f)
            if data.get("url") == self.url and data.get("server_root") == self.server_root:
                self.by_path, self.kind, self.updated = data.get("items") or {}, data.get("kind"), data.get("updated")
        except (OSError, ValueError, AttributeError):
            pass

    def _save(self):
        if not self.cache:
            return
        try:
            folder = os.path.dirname(self.cache) or "."
            fd, tmp = tempfile.mkstemp(dir=folder, prefix=".mediaserver-")
            with os.fdopen(fd, "w") as f:
                json.dump({"url": self.url, "server_root": self.server_root, "kind": self.kind, "updated": self.updated,
                           "items": self.by_path}, f)
            os.replace(tmp, self.cache)
        except OSError as e:
            self.log(f"[mediaserver] could not keep the answer in {self.cache}: {e}", flush=True)

    # -- asking
    def lookup(self, video_path, media_root):
        """What the server knows about this video (a link is followed to the real file), or None."""
        if not self.by_path:
            return None
        rel = _rel(os.path.realpath(video_path), os.path.realpath(media_root))
        return self.by_path.get(rel) if rel else None

    def status(self):
        return {"enabled": self.enabled, "url": self.url, "kind": self.kind, "items": len(self.by_path),
                "updated": self.updated, "error": self.error}
