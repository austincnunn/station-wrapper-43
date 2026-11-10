"""The folder a Pay-Per-View station shows: one link per movie, with its .nfo and poster beside it.

FieldStation42's PPV page (a "web" station, drawn by a player's own browser) lists the videos in its content_dir and shows each
one's title, year and plot from an .nfo of the same name, and a .jpg of the same name as its poster. A media server's library
keeps none of that beside the videos (it is in Emby's or Jellyfin's database), and the videos sit one per folder with release
names. So for each PPV station (stationform: wrapper_ppv.folder) this makes catalog/ppv/<channel number>/:

    Airplane! (1980).mkv  ->  /mnt/media/movies/Airplane! (1980)/Airplane.1980.720p.BluRay.x264.mkv
    Airplane! (1980).nfo      <movie><title>Airplane!</title><year>1980</year><plot>...</plot></movie>
    Airplane! (1980).jpg      the poster: Emby's/Jellyfin's, else a picture beside the movie or a frame of it (art.py)

Names, years and plots come from the media server when it knows the file, else from the folder's name ("Airplane! (1980)").
A player in client mode copies the folder with the rest of the catalog. Movies that are gone are removed, and folders of
stations that are gone too. Nothing is ever written to the media.
"""
import os
import re
import shutil
import xml.etree.ElementTree as ET

ROOT = "ppv"                                    # under the catalog
VIDEO_EXT = {".mp4", ".mov", ".webm", ".avi", ".mkv", ".m4v", ".wmv", ".flv"}   # what FieldStation42's PPV page lists
NAMED = re.compile(r"^(?P<title>.+?)\s*\((?P<year>\d{4})\)\s*$")


def content_dir(number):
    """A PPV station's folder, as its station config names it (relative to FieldStation42's /app)."""
    return f"catalog/{ROOT}/{number}"


def _videos(folder):
    for top, dirs, files in os.walk(folder, followlinks=True):
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and not d.endswith(".trickplay"))
        for f in sorted(files):
            if not f.startswith(".") and os.path.splitext(f)[1].lower() in VIDEO_EXT:
                yield os.path.join(top, f)


def describe(video, folder, lookup):
    """{title, year, plot} for one movie: the media server's, else read from its folder's (or file's) name."""
    rec = lookup(video) or {}
    if rec.get("kind") == "movie" and rec.get("title"):
        return {"title": rec["title"], "year": rec.get("year"), "plot": rec.get("plot") or "", "image": rec.get("image")}
    parent = os.path.basename(os.path.dirname(video))
    name = parent if os.path.dirname(video) != folder.rstrip("/") else os.path.splitext(os.path.basename(video))[0]
    m = NAMED.match(name)
    return {"title": m["title"] if m else name, "year": int(m["year"]) if m else None, "plot": "", "image": None}


def _safe(text):
    text = re.sub(r'[/\\\0:*?"<>|]', " ", text).strip().strip(".")
    return re.sub(r"\s+", " ", text)[:150] or "Movie"


def nfo(info):
    movie = ET.Element("movie")
    for key in ("title", "year", "plot"):
        ET.SubElement(movie, key).text = "" if info.get(key) is None else str(info[key])
    return ET.tostring(movie, encoding="unicode") + "\n"


def _write(path, data):
    mode = "wb" if isinstance(data, bytes) else "w"
    try:
        with open(path, "rb" if mode == "wb" else "r") as f:
            if f.read() == data:
                return False
    except (OSError, UnicodeDecodeError):
        pass
    tmp = path + ".tmp"
    with open(tmp, mode) as f:
        f.write(data)
    os.replace(tmp, path)
    return True


def build(number, folder, catalog, lookup=lambda p: None, poster=lambda info, video: None, log=print):
    """Make (or bring up to date) one station's folder. Returns how many movies it has.

    lookup(video path) -> the media server's record or None; poster(info, video) -> the poster's bytes or None."""
    out = os.path.join(catalog, ROOT, str(number))
    os.makedirs(out, exist_ok=True)
    keep, bases, made = set(), set(), 0
    for video in _videos(folder):
        info = describe(video, folder, lookup)
        first = base = _safe(f"{info['title']} ({info['year']})" if info.get("year") else info["title"])
        n = 2
        while base.casefold() in bases:                 # two files of one movie (or two remakes of one name)
            base, n = f"{first} {n}", n + 1
        bases.add(base.casefold())
        link = os.path.join(out, base + os.path.splitext(video)[1].lower())
        keep.add(os.path.basename(link))
        if not (os.path.islink(link) and os.readlink(link) == video):
            if os.path.lexists(link):
                os.unlink(link)
            os.symlink(video, link)
            made += 1
        keep.add(base + ".nfo")
        made += _write(os.path.join(out, base + ".nfo"), nfo(info))
        jpg = os.path.join(out, base + ".jpg")
        keep.add(base + ".jpg")
        if not os.path.isfile(jpg):
            try:
                data = poster(info, video)
            except Exception as e:                      # one poster that can't be had never stops the rest
                log(f"[ppv] no poster for {base}: {e}", flush=True)
                data = None
            if data:
                _write(jpg, data)
                made += 1
    gone = [e for e in os.listdir(out) if e not in keep]
    for e in gone:
        p = os.path.join(out, e)
        shutil.rmtree(p) if os.path.isdir(p) and not os.path.islink(p) else os.unlink(p)
    if made or gone:
        log(f"[ppv] channel {number}: {len(bases)} movies from {folder}"
            f" ({made} new or changed, {len(gone)} removed)", flush=True)
    return len(bases)


def build_all(stations, catalog, lookup=lambda p: None, poster=lambda info, video: None, log=print):
    """Every PPV station's folder, from {station name: station config}; folders of stations that are gone are removed."""
    keep = set()
    for name, conf in stations.items():
        ppv = conf.get("wrapper_ppv") if conf.get("network_type") == "web" else None
        if not isinstance(ppv, dict) or not isinstance(conf.get("channel_number"), int):
            continue
        keep.add(str(conf["channel_number"]))
        if not os.path.isdir(ppv.get("folder") or ""):
            log(f"[ppv] {name}: {ppv.get('folder')} is not there (is the media share mounted?); its movies are left as they are", flush=True)
            continue
        build(conf["channel_number"], ppv["folder"], catalog, lookup, poster, log)
    root = os.path.join(catalog, ROOT)
    if os.path.isdir(root):
        for e in os.listdir(root):
            if e not in keep:
                shutil.rmtree(os.path.join(root, e), ignore_errors=True)
                log(f"[ppv] removed {ROOT}/{e}: no PPV station has that number now", flush=True)
