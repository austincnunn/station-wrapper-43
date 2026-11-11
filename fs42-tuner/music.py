"""Songs on a channel, like Music Choice: an audio file (mp3, flac...) in a list plays with a card drawn for it.

FieldStation42 schedules audio files like videos (its catalog takes mp3, flac, m4a...); a picture is what they lack. For
each song the tuner draws one card with Pillow (the album cover, the artist, the song, the album and its year, what is up
next) and ffmpeg plays the song over it, filling a bar along the bottom and counting the time as it goes.

    is_audio(path)            is this a song
    tags(path)                {"artist", "title", "album", "year", "genre"}: the file's tags, else its folders and name
    cover(path)               the album's picture: a cover file in its folder, else the one inside the file (art.py), or None
    card(out, path, ...)      draw the card for a song into `out` (PNG); returns where the bar and the clock go

Nothing is written beside your music: covers taken from inside a file are kept in art.py's cache.
"""
import functools
import json
import os
import re
import subprocess

try:
    from PIL import Image, ImageDraw, ImageFilter, ImageFont
except ImportError:                      # the image has it; a bare checkout may not
    Image = ImageDraw = ImageFilter = ImageFont = None

AUDIO_EXT = {".mp3", ".flac", ".m4a", ".aac", ".ogg", ".oga", ".opus", ".wav", ".wma"}
COVER_NAMES = ("cover", "folder", "front", "album", "albumart")
FONT_REGULAR = ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "DejaVuSans.ttf"]
FONT_BOLD = ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "DejaVuSans-Bold.ttf"]
BG_TOP, BG_BOTTOM = (18, 28, 64), (4, 6, 16)        # deep blue to near black
ACCENT = (255, 196, 0)                              # the channel name, "UP NEXT" and the bar
TEXT, DIM, TRACK = (255, 255, 255), (170, 180, 205), (60, 66, 92)


def is_audio(path):
    return os.path.splitext(str(path))[1].lower() in AUDIO_EXT


def _clean(name):
    """A file or folder name as words: "01 Second Hand News" -> "Second Hand News", "1-03 Stand Back" -> "Stand Back"."""
    name = re.sub(r"^\s*(\d+[-.]\s*)?\d+\s*[-.]?\s+", "", os.path.splitext(name)[0])
    return re.sub(r"\s+", " ", name.replace("_", " ")).strip()


@functools.lru_cache(maxsize=4096)
def _probe(real):
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration:format_tags", "-of", "json", real],
                             capture_output=True, text=True, timeout=30).stdout
        fmt = json.loads(out or "{}").get("format") or {}
    except (OSError, ValueError, subprocess.SubprocessError):
        fmt = {}
    return {k.lower(): str(v).strip() for k, v in (fmt.get("tags") or {}).items()}, float(fmt.get("duration") or 0)


def tags(path):
    """What this song is. A tag the file lacks comes from where it is kept: Artist/Album (Year)/NN Song.ext."""
    real = os.path.realpath(path)
    t, _dur = _probe(real)
    album_dir = os.path.basename(os.path.dirname(real))
    artist_dir = os.path.basename(os.path.dirname(os.path.dirname(real)))
    year = re.search(r"\b(1[89]\d\d|20\d\d)\b", t.get("date") or t.get("year") or t.get("originaldate") or album_dir)
    return {"artist": t.get("artist") or t.get("album_artist") or t.get("albumartist") or _clean(artist_dir),
            "title": t.get("title") or _clean(os.path.basename(real)),
            "album": t.get("album") or re.sub(r"\s*[(\[]\s*(1[89]|20)\d\d\s*[)\]]\s*$", "", album_dir),
            "year": year.group(1) if year else "",
            "genre": (t.get("genre") or "").split(";")[0].split("/")[0].strip()}


def duration(path):
    return _probe(os.path.realpath(path))[1]


def line(path):
    """One line for a guide or an "up next": "Artist - Song"."""
    t = tags(path)
    return f"{t['artist']} - {t['title']}" if t["artist"] else t["title"]


def cover(path):
    """The album's picture: cover.jpg / folder.jpg / front... in the song's own folder, else the one inside the file."""
    real = os.path.realpath(path)
    folder = os.path.dirname(real)
    try:
        names = sorted(os.listdir(folder), key=str.lower)
    except OSError:
        names = []
    for n in names:
        stem, ext = os.path.splitext(n.lower())
        if ext in (".jpg", ".jpeg", ".png") and stem in COVER_NAMES:
            return os.path.join(folder, n)
    import art                                       # here: art.py asks this module about songs
    return art.make(real, art._key("a", folder))     # one per album, kept in art.py's cache


def clock(seconds):
    s = max(0, int(seconds))
    return f"{s // 3600}:{s // 60 % 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"


# ---- drawing ------------------------------------------------------------------------------------------------
def _font(paths, size):
    for p in paths:
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _clip(draw, text, font, width):
    """text cut to fit `width` pixels, with an ellipsis."""
    if draw.textlength(text, font=font) <= width:
        return text
    while text and draw.textlength(text + "…", font=font) > width:
        text = text[:-1]
    return (text + "…") if text else ""


def _background(w, h):
    img = Image.new("RGB", (w, h))
    px = ImageDraw.Draw(img)
    for y in range(h):
        f = y / max(h - 1, 1)
        px.line([(0, y), (w, y)], fill=tuple(int(a + (b - a) * f) for a, b in zip(BG_TOP, BG_BOTTOM)))
    return img


def card(out, path, station="", number=None, up_next="", size=(1280, 720)):
    """Draw the card for the song at `path` into `out` (a PNG). Returns {"bar": (x, y, w, h), "clock": (x, y, font size),
    "total": seconds}: where the tuner fills the bar and writes the time gone, which change as the song plays."""
    w, h = size
    s = h / 720
    img = _background(w, h)
    d = ImageDraw.Draw(img)
    t = tags(path)
    total = duration(path)
    m = int(56 * s)                                          # the margin

    f_head = _font(FONT_BOLD, int(30 * s))
    d.text((m, int(34 * s)), _clip(d, (station or "Music").upper(), f_head, w * 0.6), font=f_head, fill=ACCENT)
    if number is not None:
        ch = f"CH {number}"
        d.text((w - m - d.textlength(ch, font=f_head), int(34 * s)), ch, font=f_head, fill=DIM)

    side = int(380 * s)                                      # the cover
    cx, cy = m, int(110 * s)
    pic = cover(path)
    try:
        art = Image.open(pic).convert("RGB") if pic else None
    except (OSError, ValueError):
        art = None
    shadow = Image.new("RGBA", (side + 24, side + 24), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rectangle([12, 12, side + 12, side + 12], fill=(0, 0, 0, 170))
    img.paste(shadow.filter(ImageFilter.GaussianBlur(10)), (cx - 6, cy - 2), shadow.filter(ImageFilter.GaussianBlur(10)))
    if art is not None:
        img.paste(art.resize((side, side)), (cx, cy))
    else:                                                    # no picture: a plain square with a note on it
        d.rectangle([cx, cy, cx + side, cy + side], fill=(36, 44, 84))
        f_note = _font(FONT_BOLD, int(side * 0.5))
        d.text((cx + side / 2, cy + side / 2), "♪", font=f_note, fill=DIM, anchor="mm")

    tx = cx + side + int(56 * s)                             # the words beside it
    tw = w - tx - m
    f_artist, f_title, f_album = _font(FONT_BOLD, int(54 * s)), _font(FONT_REGULAR, int(44 * s)), _font(FONT_REGULAR, int(30 * s))
    y = cy + int(40 * s)
    d.text((tx, y), _clip(d, (t["artist"] or "").upper(), f_artist, tw), font=f_artist, fill=TEXT)
    y += int(78 * s)
    d.text((tx, y), _clip(d, t["title"], f_title, tw), font=f_title, fill=TEXT)
    y += int(84 * s)
    album = t["album"] + (f"  ({t['year']})" if t["year"] else "")
    d.text((tx, y), _clip(d, album, f_album, tw), font=f_album, fill=DIM)
    if t["genre"]:
        d.text((tx, y + int(46 * s)), _clip(d, t["genre"], f_album, tw), font=f_album, fill=DIM)

    f_next = _font(FONT_BOLD, int(28 * s))
    ny = int(540 * s)
    if up_next:
        label = "UP NEXT  "
        d.text((m, ny), label, font=f_next, fill=ACCENT)
        lx = m + d.textlength(label, font=f_next)
        d.text((lx, ny), _clip(d, up_next, f_next, w - m - lx), font=f_next, fill=TEXT)

    bar = (m, int(640 * s), w - 2 * m, max(int(12 * s), 4))
    d.rectangle([bar[0], bar[1], bar[0] + bar[2], bar[1] + bar[3]], fill=TRACK)
    f_clock = int(26 * s)
    if total:
        tot = clock(total)
        fc = _font(FONT_REGULAR, f_clock)
        d.text((bar[0] + bar[2] - d.textlength(tot, font=fc), bar[1] - int(40 * s)), tot, font=fc, fill=DIM)
    img.save(out, "PNG")
    return {"bar": bar, "clock": (bar[0], bar[1] - int(40 * s), f_clock), "total": total}
