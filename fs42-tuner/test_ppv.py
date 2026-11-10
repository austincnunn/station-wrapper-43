"""A Pay-Per-View station: its form, its config, and the folder of movies made for it. Run: python3 test_ppv.py"""
import json
import os
import tempfile
import unittest
import xml.etree.ElementTree as ET

import ppv
import stationform as sf
import stations


def movies():
    """/media/movies/<Title (Year)>/<release name>.mkv, the way a media server's library is laid out."""
    media = tempfile.mkdtemp()
    root = os.path.join(media, "movies")
    for folder, f in (("Airplane! (1980)", "Airplane.1980.720p.BluRay.x264.mkv"), ("Heat (1995)", "Heat.1995.1080p.mp4"),
                      ("Interstellar (2014)", "Interstellar.2014.IMAX.mkv")):
        os.makedirs(os.path.join(root, folder))
        open(os.path.join(root, folder, f), "w").write("v")
    os.makedirs(os.path.join(root, "Interstellar (2014)", "Interstellar.2014.IMAX.trickplay"))
    open(os.path.join(root, "Interstellar (2014)", "Interstellar.2014.IMAX.trickplay", "x.mkv"), "w").write("not a movie")
    open(os.path.join(root, "Loose Video.webm"), "w").write("v")
    open(os.path.join(root, ".DS_Store"), "w").write("")
    return root


SERVER = {"Airplane.1980.720p.BluRay.x264.mkv": {"kind": "movie", "title": "Airplane!", "year": 1980,
                                                 "plot": "A pilot & a <stewardess>", "image": "http://emby/Items/1/Images/Primary"}}


def lookup(path):
    return SERVER.get(os.path.basename(path))


class Folder(unittest.TestCase):
    def setUp(self):
        self.src, self.cat = movies(), tempfile.mkdtemp()
        self.posters = []

    def poster(self, info, video):
        self.posters.append(info["title"])
        return b"jpg" if info.get("image") else None

    def build(self):
        return ppv.build(115, self.src, self.cat, lookup, self.poster, log=lambda *a, **k: None)

    def test_one_link_nfo_and_poster_per_movie(self):
        self.assertEqual(self.build(), 4)
        out = os.path.join(self.cat, "ppv", "115")
        self.assertEqual(sorted(os.listdir(out)), ["Airplane! (1980).jpg", "Airplane! (1980).mkv", "Airplane! (1980).nfo",
                                                   "Heat (1995).mp4", "Heat (1995).nfo", "Interstellar (2014).mkv",
                                                   "Interstellar (2014).nfo", "Loose Video.nfo", "Loose Video.webm"])
        self.assertEqual(os.readlink(os.path.join(out, "Heat (1995).mp4")), os.path.join(self.src, "Heat (1995)", "Heat.1995.1080p.mp4"))
        movie = ET.parse(os.path.join(out, "Airplane! (1980).nfo")).getroot()          # the server's words, escaped
        self.assertEqual((movie.tag, movie.findtext("title"), movie.findtext("year"), movie.findtext("plot")),
                         ("movie", "Airplane!", "1980", "A pilot & a <stewardess>"))
        self.assertEqual(ET.parse(os.path.join(out, "Heat (1995).nfo")).getroot().findtext("year"), "1995")   # from the folder

    def test_again_changes_nothing_and_a_poster_is_fetched_once(self):
        self.build()
        self.posters.clear()
        self.build()
        self.assertEqual(sorted(self.posters), ["Heat", "Interstellar", "Loose Video"])     # only the ones that have none yet

    def test_a_movie_that_is_gone_leaves_and_so_does_a_station(self):
        self.build()
        os.remove(os.path.join(self.src, "Heat (1995)", "Heat.1995.1080p.mp4"))
        self.build()
        self.assertFalse(any(e.startswith("Heat") for e in os.listdir(os.path.join(self.cat, "ppv", "115"))))
        ppv.build_all({"Other": {"network_type": "standard", "channel_number": 5}}, self.cat, log=lambda *a, **k: None)
        self.assertEqual(os.listdir(os.path.join(self.cat, "ppv")), [])

    def test_two_files_of_one_movie_both_stay(self):
        open(os.path.join(self.src, "Heat (1995)", "Heat.1995.Directors.Cut.mkv"), "w").write("v")
        self.assertEqual(self.build(), 5)
        self.assertIn("Heat (1995) 2.mkv", os.listdir(os.path.join(self.cat, "ppv", "115")))

    def test_build_all_makes_each_ppv_station_and_skips_a_missing_folder(self):
        confs = {"PPV": {"network_type": "web", "channel_number": 115, "wrapper_ppv": {"folder": self.src}},
                 "Away": {"network_type": "web", "channel_number": 116, "wrapper_ppv": {"folder": "/nope"}},
                 "Web": {"network_type": "web", "channel_number": 117, "web_url": "http://x"}}
        os.makedirs(os.path.join(self.cat, "ppv", "116"))
        open(os.path.join(self.cat, "ppv", "116", "Old (1990).nfo"), "w").write("x")       # the share is away: what was made stays
        ppv.build_all(confs, self.cat, lookup, self.poster, log=lambda *a, **k: None)
        self.assertEqual(sorted(os.listdir(os.path.join(self.cat, "ppv"))), ["115", "116"])
        self.assertEqual(os.listdir(os.path.join(self.cat, "ppv", "116")), ["Old (1990).nfo"])


class Form(unittest.TestCase):
    FORM = {"name": "Pay-Per-View", "number": 115, "kind": "ppv", "ppv": {"folder": "/mnt/media/movies/", "theme": "retro", "seconds": 15}}

    def test_round_trip(self):
        form = sf.validate(self.FORM)
        conf = sf.to_conf(form)
        self.assertEqual((conf["network_type"], conf["content_dir"]), ("web", "catalog/ppv/115"))
        self.assertEqual(conf["web_url"], "http://localhost:4242/static/ppv/ppv.html?channel=115&variation=retro&duration=15000")
        back, why = sf.parse(conf)
        self.assertIsNone(why)
        self.assertEqual(back["ppv"], {"folder": "/mnt/media/movies", "theme": "retro", "seconds": 15})

    def test_bad_ones(self):
        for p in ({"folder": "movies"}, {"folder": "/mnt/media/../etc"}, {"folder": "/m", "theme": "neon"}, {"folder": "/m", "seconds": 1}):
            with self.assertRaises(sf.FormError):
                sf.validate({**self.FORM, "ppv": p})

    def test_turning_it_into_a_loop_drops_the_web_keys(self):
        conf = sf.to_conf(sf.validate(self.FORM))
        loop = sf.to_conf(sf.validate({"name": "Pay-Per-View", "number": 115, "kind": "loop", "loop": {"list": "Movies"}}), conf)
        self.assertNotIn("web_url", loop)
        self.assertNotIn("wrapper_ppv", loop)

    def test_a_web_station_is_not_in_the_tuners_lineup(self):
        d = tempfile.mkdtemp()
        json.dump({"station_conf": sf.to_conf(sf.validate(self.FORM))}, open(os.path.join(d, "ppv.json"), "w"))
        json.dump({"station_conf": {"network_name": "News", "channel_number": 3}}, open(os.path.join(d, "news.json"), "w"))
        self.assertEqual(stations.discover(d), {"3": "News"})


if __name__ == "__main__":
    unittest.main()
