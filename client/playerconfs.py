"""The station configs as a player PC needs them, made from the server's (client mode; was extras/remote-player/fs42-streams).

1. Every live channel on the server's Sources page (a weather channel, a camera, an IPTV playlist) becomes a FieldStation42
   streaming station here (confs/stream-*.json), with the same number and name it has in Emby/Jellyfin. A source removed on
   the server is removed here too.
2. Guide stations play the server's own guide channel (show names and posters) from the server's tuner. A guide drawn 4:3
   is cropped to fill the screen when this player crops (panscan); otherwise it is shown whole.
3. Stations that play videos from an Emby server (`from_server`: their files are placeholders here) play the server's
   tuner instead, like the guide.
4. Every other station gets this player's panscan, unless its own config sets one.
"""
import glob
import json
import os
import re


def guide_stream(sc, tuner, panscan, kbps=None):
    num, name = sc["channel_number"], sc["network_name"]
    four_three = (sc.get("wrapper_guide") or {}).get("aspect") == "4:3"     # drawn 4:3 in the middle of a 16:9 picture
    url = f"{tuner}/auto/v{num}" + (f"?kbps={kbps}" if kbps else "")
    return {"network_name": name, "network_type": "streaming", "channel_number": num,
            "panscan": panscan if four_three else 0.0,
            "streams": [{"url": url, "duration": 3600, "title": name}]}


def plan(sources, taken_numbers, taken_names, panscan):
    """{file name: station conf} for the sources' live channels, numbered as the wrapper numbers them (iptv.Sources.plan)."""
    out = {}
    for s in sources:
        if not s.get("enabled", True) or s.get("mode") == "guide":
            continue
        for c in s.get("channels", []):
            ov = s.get("overrides", {}).get(c["key"], {})
            if ov.get("enabled") is False:
                continue
            num = ov.get("number") or (c.get("number") if s.get("type") == "hdhomerun" else None) or s.get("numbers", {}).get(c["key"])
            name = ov.get("name") or c["name"]
            if not num or not re.fullmatch(r"\d+", str(num)) or int(num) in taken_numbers or name in taken_names:
                print(f"skipped stream {name!r}: channel {num!r} is not a whole number free on this player", flush=True)
                continue
            taken_numbers.add(int(num))
            taken_names.add(name)
            fname = "stream-" + re.sub(r"[^A-Za-z0-9_-]+", "_", f"{s['id']}-{c['key']}") + ".json"
            out[fname] = {"station_conf": {"network_name": name, "network_type": "streaming", "channel_number": int(num),
                                           "panscan": panscan, "streams": [{"url": c["url"], "duration": 3600, "title": name}]}}
    return out


def write(root, sources, tuner, panscan, kbps=None, from_server=()):
    """Rewrite root/confs for this player. `sources` is the server's Sources page list; `from_server` the names of the
    stations to stream from the server's tuner. ponytail: such a station stays streamed until the server's confs change."""
    confs = os.path.join(root, "confs")
    numbers, names = set(), set()
    for f in glob.glob(os.path.join(confs, "*.json")):
        if os.path.basename(f).startswith("stream-") or os.path.basename(f) == "main_config.json":
            continue
        try:
            with open(f) as fh:
                conf = json.load(fh)
            sc = conf["station_conf"]
            numbers.add(int(sc["channel_number"]))
            names.add(sc["network_name"])
        except (OSError, ValueError, KeyError, TypeError):
            continue
        changed = False
        if sc.get("network_type") == "guide":
            conf["station_conf"] = sc = guide_stream(sc, tuner, panscan, kbps)
            changed = True
        elif sc["network_name"] in from_server and sc.get("network_type") != "streaming":
            conf["station_conf"] = sc = {**guide_stream(sc, tuner, panscan, kbps), "panscan": panscan}
            changed = True
        if "panscan" not in sc:
            sc["panscan"], changed = panscan, True
        if changed:
            with open(f, "w") as out:
                json.dump(conf, out, indent=2)
    want = plan(sources, numbers, names, panscan)
    for f in glob.glob(os.path.join(confs, "stream-*.json")):
        if os.path.basename(f) not in want:
            os.remove(f)
    for fname, conf in want.items():
        path, text = os.path.join(confs, fname), json.dumps(conf, indent=1) + "\n"
        try:
            with open(path) as f:
                same = f.read() == text
        except OSError:
            same = False
        if not same:
            with open(path, "w") as f:
                f.write(text)
