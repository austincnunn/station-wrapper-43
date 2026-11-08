"""Names, synopses and posters from Emby or Jellyfin (mediaserver.py), and where titles.py uses them. Run: python3 test_mediaserver.py"""
import os
import shutil
import tempfile
import unittest

import mediaserver
import titles

EPISODE = {"Type": "Episode", "Id": "e1", "Name": "Fraudcast News", "SeriesName": "The Simpsons", "SeriesId": "s1",
           "SeriesPrimaryImageTag": "t", "ParentIndexNumber": 15, "IndexNumber": 22, "Overview": "Burns buys  the media.",
           "PremiereDate": "2004-05-23T00:00:00.0000000Z", "ProductionYear": 2004, "Genres": ["Animation", "Comedy"],
           "Path": "/media/tv/The Simpsons (1989)/Season 15/the.simpsons.s15e22.mkv"}
MOVIE = {"Type": "Movie", "Id": "m1", "Name": "Twister", "ProductionYear": 1996, "ImageTags": {"Primary": "x"},
         "Path": "/media/movies/Twister (1996)/Twister.1996.mkv"}


def server(items, product=None, page=None, fail=False):
    """A fake Emby (product None) or Jellyfin: answers /System/Info/Public and /Items, a page at a time."""
    calls = []

    def fetch(path, params=None):
        calls.append((path, params))
        if fail:
            raise OSError("connection refused")
        if path == "/System/Info/Public":
            return {"ServerName": "x", **({"ProductName": product} if product else {})}
        start, limit = int(params["StartIndex"]), page or int(params["Limit"])
        return {"Items": items[start:start + limit], "TotalRecordCount": len(items)}
    fetch.calls = calls
    return fetch


class LibraryTest(unittest.TestCase):
    def setUp(self):
        self.root = os.path.realpath(tempfile.mkdtemp())
        self.media = os.path.join(self.root, "media")
        self.logged = []

    def tearDown(self):
        shutil.rmtree(self.root)

    def lib(self, fetch, cache=None):
        return mediaserver.Library("http://srv:8096", "k", "/media", cache=cache, fetch=fetch,
                                   log=lambda *a, **k: self.logged.append(a[0]))

    def video(self, rel):
        p = os.path.join(self.media, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, "w").close()
        return p

    def test_emby_and_jellyfin_are_both_read_and_told_apart(self):
        for product, kind in ((None, "Emby"), ("Jellyfin Server", "Jellyfin")):
            lib = self.lib(server([EPISODE, MOVIE], product))
            self.assertTrue(lib.refresh())
            self.assertEqual(lib.kind, kind)
            got = lib.lookup(self.video("tv/The Simpsons (1989)/Season 15/the.simpsons.s15e22.mkv"), self.media)
            self.assertEqual((got["title"], got["episode_name"], got["season"], got["episode"]), ("The Simpsons", "Fraudcast News", 15, 22))
            self.assertEqual(got["plot"], "Burns buys the media.")
            self.assertEqual((got["aired"], got["genres"]), ("2004-05-23", ["Animation", "Comedy"]))
            self.assertEqual(got["image"], "http://srv:8096/Items/s1/Images/Primary?maxWidth=640")          # the series' poster
            movie = lib.lookup(self.video("movies/Twister (1996)/Twister.1996.mkv"), self.media)
            self.assertEqual((movie["title"], movie["episode_name"], movie["year"], movie["genres"]), ("Twister", None, 1996, ["Movie"]))
            self.assertEqual(movie["image"], "http://srv:8096/Items/m1/Images/Primary?maxWidth=640")

    def test_the_key_is_sent_both_ways_the_two_servers_take_it(self):
        lib = mediaserver.Library("http://srv:8096", "secret", "/media")
        seen = {}

        class Answer:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self, *a):
                return b"{}"

        def urlopen(req, timeout):
            seen.update(req.headers)
            return Answer()
        saved, mediaserver.urllib.request.urlopen = mediaserver.urllib.request.urlopen, urlopen
        try:
            lib._get("/System/Info/Public")
        finally:
            mediaserver.urllib.request.urlopen = saved
        self.assertEqual(seen["X-emby-token"], "secret")                                              # Emby
        self.assertEqual(seen["Authorization"], 'MediaBrowser Token="secret"')                       # Jellyfin

    def test_every_page_is_read_and_a_link_finds_its_real_file(self):
        items = [dict(EPISODE, Id=f"e{i}", IndexNumber=i, Path=f"/media/tv/S/e{i}.mkv") for i in range(5)]
        fetch = server(items, page=2)
        lib = self.lib(fetch)
        lib.refresh()
        self.assertEqual(len(lib.by_path), 5)
        self.assertEqual(sum(1 for p, _ in fetch.calls if p == "/Items"), 3)
        real = self.video("tv/S/e4.mkv")
        link = os.path.join(self.root, "list.mkv")
        os.symlink(real, link)
        self.assertEqual(lib.lookup(link, self.media)["episode"], 4)
        self.assertIsNone(lib.lookup(self.video("tv/S/other.mkv"), self.media))

    def test_an_unreachable_server_keeps_the_last_answer_and_the_answer_survives_a_restart(self):
        cache = os.path.join(self.root, "ms.json")
        lib = self.lib(server([EPISODE]), cache)
        lib.refresh()
        lib.fetch = server([], fail=True)
        self.assertFalse(lib.refresh())
        self.assertEqual(len(lib.by_path), 1)
        self.assertIn("connection refused", lib.error)
        again = self.lib(server([], fail=True), cache)                                  # a restart: names at once, from disk
        self.assertEqual(len(again.by_path), 1)
        moved = mediaserver.Library("http://other:8096", "k", "/media", cache=cache)     # another server: not its answer
        self.assertEqual(moved.by_path, {})

    def test_media_the_server_sees_elsewhere_is_said_to_be_so(self):
        lib = self.lib(server([dict(EPISODE, Path="/data/tv/x.mkv")]))
        lib.refresh()
        self.assertEqual(lib.by_path, {})
        self.assertTrue(any("MEDIA_SERVER_MEDIA_ROOT" in line for line in self.logged))

    def test_off_without_an_address_and_a_key(self):
        self.assertFalse(mediaserver.Library("", "k").enabled)
        self.assertFalse(mediaserver.Library("http://srv", "").enabled)
        self.assertFalse(mediaserver.Library("", "").refresh())


class TitlesUseIt(unittest.TestCase):
    def setUp(self):
        titles.forget()
        self.root = os.path.realpath(tempfile.mkdtemp())
        self.old = titles.MEDIA_ROOT, titles.SERVER
        titles.MEDIA_ROOT = self.root
        lib = mediaserver.Library("http://srv:8096", "k", "/media", fetch=server([EPISODE]), log=lambda *a, **k: None)
        lib.refresh()
        titles.SERVER = lambda p: lib.lookup(p, self.root)
        self.p = os.path.join(self.root, "tv/The Simpsons (1989)/Season 15/the.simpsons.s15e22.mkv")
        os.makedirs(os.path.dirname(self.p))
        open(self.p, "w").close()

    def tearDown(self):
        titles.MEDIA_ROOT, titles.SERVER = self.old
        shutil.rmtree(self.root)
        titles.forget()

    def test_the_server_names_a_video_with_no_nfo_before_its_file_name_does(self):
        self.assertEqual(titles.names_for(self.p), ("The Simpsons", "Fraudcast News"))
        d = titles.details_for(self.p)
        self.assertEqual((d["kind"], d["season"], d["episode"], d["plot"]), ("episode", 15, 22, "Burns buys the media."))

    def test_an_nfo_still_comes_first_and_without_the_server_the_file_name_is_used(self):
        with open(os.path.splitext(self.p)[0] + ".nfo", "w") as f:
            f.write("<episodedetails><title>Mine</title><showtitle>My Show</showtitle></episodedetails>")
        self.assertEqual(titles.names_for(self.p), ("My Show", "Mine"))
        os.remove(os.path.splitext(self.p)[0] + ".nfo")
        titles.forget()
        titles.SERVER = None
        self.assertEqual(titles.names_for(self.p), ("The Simpsons", None))          # from its folder and file name

    def test_a_broken_server_hook_never_breaks_a_name(self):
        def boom(p):
            raise RuntimeError("x")
        titles.SERVER = boom
        self.assertEqual(titles.names_for(self.p), ("The Simpsons", None))


if __name__ == "__main__":
    unittest.main()
