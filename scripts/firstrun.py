#!/usr/bin/env python3
"""First start: put two stations on air, so a new install shows something and proves the whole chain.

"Test Pattern" on channel 2 plays a test card with a quiet tone, from a clip made here (ffmpeg, nothing
downloaded) into catalog/by-genre/Test Pattern/. "Channel Guide" on channel 1 is the scrolling guide of every
channel (drawn by the tuner, see guide_channel.py) with its default settings and no music; it needs no schedule.
Both are made through the console, like any station you would add yourself, so you can edit or delete them there.

It runs once. It does nothing if the install already has stations of its own (an existing setup is never
touched), and once it has run (or declined to), /config/.test-station-done stops it ever running again, so a
station you delete stays deleted. FIRSTRUN_TEST_STATION=0 and FIRSTRUN_GUIDE_STATION=0 turn each off.

Separately, WEATHER_CHANNEL=1 (off by default; the compose file sets it when its "weather" profile is on) adds
"Weather" from channel 3: the stream of the ws4channels container that profile runs beside this one, as a source (the Sources page lists it; the place is set on the Settings
page). That too happens once (/config/.weather-channel-done), on a new install or an old one, and only when that
container is there.

Exit 0: done or not needed. 1: the console was not up in time (the supervisor tries again).
78: something is wrong that retrying will not fix (the message says what).
"""
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse

import build_channels as bc

NAME = "Test Pattern"
NUMBER = 2
GUIDE_NAME = "Channel Guide"
GUIDE_NUMBER = 1                 # not 0: Jellyfin and some other IPTV clients ignore channel 0
CLIP = "test-pattern.mp4"
CLIP_SECONDS = int(os.environ.get("FIRSTRUN_CLIP_SECONDS", "60"))     # how long the looped test card is
WEATHER_NAME = "Weather"
WEATHER_NUMBER = 3
WEATHER_STREAM = os.environ.get("WEATHER_STREAM_URL", "http://ws4channels:9798/stream/stream.m3u8")
FLAG = os.path.join(bc.CONTAINER_CONFIG, ".test-station-done")
WEATHER_FLAG = os.path.join(bc.CONTAINER_CONFIG, ".weather-channel-done")
WAIT_SECONDS = 180
DAYS = 7                    # a day of schedule is only what is left of today; nothing here extends it later


def say(msg):
    print(f"firstrun: {msg}", flush=True)


ASSET = os.environ.get("FIRSTRUN_ASSET", "/opt/assets/test-pattern.mp4")      # the pre-rendered test card shipped in the image


def make_clip(path):
    """The test card at `path`: the pre-rendered clip from the image when it is there, else one made with ffmpeg."""
    if os.path.isfile(ASSET):
        shutil.copyfile(ASSET, path + ".part.mp4")
        os.replace(path + ".part.mp4", path)
        return
    render_clip(path)


def render_clip(path):
    """A one minute test card (SMPTE-style colour bars) with a quiet 1 kHz tone. The station loops it.

    Sixty seconds, not five: the dashboard starts an ffmpeg for every schedule entry and the schedule keeps
    growing, so a 5 s loop meant 17,280 entries (~2.7 MB) per day and an ffmpeg every 5 s; 60 s is 1,440."""
    tmp = path + ".part.mp4"
    cmd = ["ffmpeg", "-nostdin", "-loglevel", "error", "-y",
           "-f", "lavfi", "-i", "smptebars=size=640x480:rate=15",
           "-f", "lavfi", "-i", "sine=frequency=1000:sample_rate=48000",
           "-af", "volume=0.12", "-t", str(CLIP_SECONDS),
           "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "64k", "-ac", "2", "-movflags", "+faststart", tmp]
    out = subprocess.run(cmd, capture_output=True, text=True)
    if out.returncode != 0:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise RuntimeError(f"ffmpeg could not make the test card: {out.stderr[-300:]}")
    os.replace(tmp, path)


def mark_done(flag=None, text="The test station was made, or the install already had stations. Delete this file to allow it again.\n"):
    flag = flag or FLAG
    try:
        with open(flag, "w") as f:
            f.write(text)
        if os.geteuid() == 0:           # the config folder is yours: give the file to whoever owns the folder
            ref = os.stat(bc.CONTAINER_CONFIG)
            os.chown(flag, ref.st_uid, ref.st_gid)
    except OSError as e:
        say(f"could not write {flag}: {e}")


def _on(var, default="1"):
    return (os.environ.get(var) or default).lower() not in ("0", "false", "no", "off")     # set but empty = not set


def guide_conf():
    """The guide station with its default settings (the same keys the station form writes, see stationform.py)."""
    return {"network_name": GUIDE_NAME, "channel_number": GUIDE_NUMBER, "network_type": "guide",
            "messages": ["Welcome to the Channel Guide"], "play_sound": False, "scroll_speed": 1.0,
            "wrapper_guide": {"title": "Channel Guide", "hours": 3, "theme": "modern-blue", "music": ""}}


def add_weather_source():
    """The weather channel as a source, from channel 3 up. True when the source is there afterwards (new or not),
    False when there is no ws4channels container to play."""
    if not weather_there():
        return False
    sys.path.insert(0, os.environ.get("FS42_TUNER_DIR", "/opt/tuner"))
    import iptv
    sources = iptv.Sources()
    if any(s.get("url") == WEATHER_STREAM for s in sources.all()):
        return True
    src = sources.save({"type": "stream", "url": WEATHER_STREAM, "name": WEATHER_NAME, "mode": "convert", "base": WEATHER_NUMBER})
    sources.set_channels(src["id"], iptv.fetch_channels(src), None)
    bc.restart_tuner(None)                                            # the tuner reads its sources when it starts
    say(f"the {WEATHER_NAME} channel is on air (channel {WEATHER_NUMBER}, or the next free number). Set its place on the "
        "Settings page; remove it on the Sources page.")
    return True


def weather_there():
    """Is the ws4channels container beside this one? Says how to start it when it is not."""
    host = urllib.parse.urlsplit(WEATHER_STREAM).hostname
    try:
        socket.getaddrinfo(host, None)
        return True
    except OSError:
        say(f"the weather channel is switched on, but there is no '{host}' container beside this one. "
            "COMPOSE_PROFILES=weather in .env (beside the compose file) starts it; that line was WEATHER_CHANNEL=1 "
            "until November 2026. Then: docker compose up -d")
        return False


def weather():
    """WEATHER_CHANNEL=1 adds the weather channel, once: on a new install or years later, whatever stations there are
    (switching it on is the asking). Its own flag, so a source deleted on the Sources page stays deleted."""
    if not _on("WEATHER_CHANNEL", "0"):
        return
    if os.path.exists(WEATHER_FLAG):
        weather_there()                 # added before: only say so if its containers have gone (the switch's old name)
        return
    try:
        if add_weather_source():
            mark_done(WEATHER_FLAG, "The weather channel was added. Delete this file to allow it again.\n")
    except Exception as e:
        say(f"could not add the weather channel: {e}")


def main(argv=None):
    code = stations()
    weather()               # after the stations: it restarts the tuner, which should find them made
    return code


def stations():
    test_on, guide_on = _on("FIRSTRUN_TEST_STATION"), _on("FIRSTRUN_GUIDE_STATION")
    if not test_on and not guide_on:
        if not _on("WEATHER_CHANNEL", "0"):
            say("the first-start stations are switched off (FIRSTRUN_TEST_STATION=0, FIRSTRUN_GUIDE_STATION=0)")
        return 0
    if os.path.exists(FLAG):
        return 0
    console = bc.Console("http://127.0.0.1:4242")
    deadline = time.time() + WAIT_SECONDS
    while True:
        try:
            existing = console.stations()
            break
        except (urllib.error.URLError, OSError):
            if time.time() > deadline:
                say("the console did not come up in time; will try again")
                return 1
            time.sleep(3)
    others = [n for n in existing if n not in (NAME, GUIDE_NAME)]       # ours, left by an attempt that stopped halfway, don't count
    if others:
        say(f"this install already has {len(others)} station(s), so no first-start stations are added")
        mark_done()
        return 0

    try:
        if test_on and NAME not in existing:
            make_test_station(console)
        if guide_on and GUIDE_NAME not in existing:
            console.ensure_station(guide_conf(), existing)            # drawn live: no catalog or schedule to build
    except Exception as e:      # whatever it was, retrying on every start would not fix it
        say(f"could not set up the first-start stations: {e}")
        return 78
    mark_done()
    if test_on:
        say(f"channel {NUMBER} ({NAME}) is on air. Edit or delete it in the console; it will not come back.")
    if guide_on:
        say(f"channel {GUIDE_NUMBER} ({GUIDE_NAME}) is on air. Change its style, messages and music on the Stations page.")
    return 0


def make_test_station(console):
    tag_dir = os.path.join(bc.CONTAINER_CATALOG, bc.FARM, NAME)
    clip = os.path.join(tag_dir, CLIP)
    if not os.path.exists(clip):
        os.makedirs(tag_dir, exist_ok=True)
        make_clip(clip)
    # A "loop" station repeats the one clip all day: no bump clips, commercials or time slots to fit.
    conf = {"network_name": NAME, "channel_number": NUMBER, "network_type": "loop", "shuffle_loop": False,
            "content_dir": f"catalog/{bc.FARM}/{NAME}"}
    console.ensure_station(conf, {})
    console.rebuild_catalog(NAME)
    for _ in range(DAYS):
        bc.add_first_day(None, NAME, console)
    bc.adopt_owner(os.path.join(bc.CONTAINER_CATALOG, bc.FARM), bc.CONTAINER_CATALOG)


if __name__ == "__main__":
    sys.exit(main())
