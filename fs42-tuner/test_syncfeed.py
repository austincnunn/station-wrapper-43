"""What a player PC in client mode copies from the server (/sync/). Run: python3 test_syncfeed.py"""
import gzip
import json
import os
import sqlite3
import tempfile
import unittest

from syncfeed import Feed

AUTH = {"Authorization": "Bearer s3cret"}


def make_tree():
    d = tempfile.mkdtemp()
    db = os.path.join(d, "fs42_fluid.db")
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE liquid_blocks (station TEXT, title TEXT)")
    con.execute("INSERT INTO liquid_blocks VALUES ('Prime Country', 'a song')")
    con.commit()
    con.close()
    confs = os.path.join(d, "confs")
    os.makedirs(confs)
    open(os.path.join(confs, "prime.json"), "w").write('{"station_conf": {}}')
    open(os.path.join(confs, "prime.json.bak"), "w").write("old")
    open(os.path.join(confs, "main_config.json"), "w").write("{}")
    cat = os.path.join(d, "catalog")
    os.makedirs(os.path.join(cat, "by-genre", "Prime Country"))
    os.makedirs(os.path.join(cat, ".prefetch"))
    os.makedirs(os.path.join(cat, "by-genre", "empty"))
    os.symlink("/mnt/media/song.mp4", os.path.join(cat, "by-genre", "Prime Country", "song.mp4"))
    os.symlink("/mnt/media/show/", os.path.join(cat, "by-genre", "show"))
    open(os.path.join(cat, "by-genre", "Prime Country", "song.nfo"), "w").write("<musicvideo/>")
    open(os.path.join(cat, ".prefetch", "x"), "w").write("cache")
    src = os.path.join(d, "sources.json")
    open(src, "w").write('[{"id": "a"}]')
    return Feed("s3cret", db, confs, cat, src, versions={"wrapper": "abc", "fieldstation42": "def"}), d


class SyncFeed(unittest.TestCase):
    def setUp(self):
        self.feed, self.dir = make_tree()

    def get(self, path, query=None, headers=AUTH):
        return self.feed.handle("GET", path, query or {}, headers, b"", "10.0.0.5")

    def test_off_without_a_token_and_refused_with_a_wrong_one(self):
        self.assertEqual(Feed("", "x", "x", "x", "x").handle("GET", "/sync/state", {}, AUTH, b"", "a")[0], 404)
        self.assertEqual(self.get("/sync/state", headers={})[0], 403)
        self.assertEqual(self.get("/sync/state", headers={"Authorization": "Bearer nope"})[0], 403)

    def test_state_carries_the_versions_and_answers_304_when_nothing_changed(self):
        code, headers, body = self.get("/sync/state")
        self.assertEqual(code, 200)
        st = json.loads(body)
        self.assertEqual(sorted(st["parts"]), ["catalog", "confs", "db", "sources"])
        self.assertEqual(st["versions"], {"wrapper": "abc", "fieldstation42": "def"})
        tag = dict(headers)["ETag"]
        self.assertEqual(self.get("/sync/state", headers=dict(AUTH, **{"If-None-Match": tag}))[0], 304)

    def test_the_db_is_a_working_copy(self):
        code, _, body = self.get("/sync/db")
        path = os.path.join(self.dir, "copy.db")
        open(path, "wb").write(gzip.decompress(body))
        self.assertEqual(sqlite3.connect(path).execute("SELECT title FROM liquid_blocks").fetchall(), [("a song",)])

    def test_confs_leave_out_backups_and_the_servers_own_main_config(self):
        self.assertEqual(sorted(json.loads(self.get("/sync/confs")[2])), ["prime.json"])

    def test_the_catalog_lists_links_files_and_folders_but_not_caches(self):
        m = json.loads(gzip.decompress(self.get("/sync/catalog")[2]))
        self.assertEqual(m["links"], {"by-genre/Prime Country/song.mp4": "/mnt/media/song.mp4", "by-genre/show": "/mnt/media/show/"})
        self.assertEqual(list(m["files"]), ["by-genre/Prime Country/song.nfo"])
        self.assertIn("by-genre/empty", m["dirs"])
        self.assertFalse(any(".prefetch" in p for p in list(m["files"]) + m["dirs"]))

    def test_a_file_is_served_only_from_inside_the_catalog_and_never_through_a_link(self):
        self.assertEqual(self.get("/sync/file", {"path": ["by-genre/Prime Country/song.nfo"]})[2], b"<musicvideo/>")
        self.assertEqual(self.get("/sync/file", {"path": ["../sources.json"]})[0], 404)
        self.assertEqual(self.get("/sync/file", {"path": ["by-genre/Prime Country/song.mp4"]})[0], 404)

    def test_a_player_saying_hello_is_listed_with_its_problems(self):
        hello = json.dumps({"name": "crt", "versions": {"wrapper": "old", "fieldstation42": "def"}, "errors": ["no media"]}).encode()
        self.assertEqual(self.feed.handle("POST", "/sync/hello", {}, AUTH, hello, "10.0.0.5")[0], 204)
        [p] = self.feed.players()
        self.assertEqual((p["name"], p["addr"], p["mismatch"], p["gone"], p["errors"]), ("crt", "10.0.0.5", True, False, ["no media"]))
        self.feed.clock = lambda: p["seen"] + 600
        self.assertTrue(self.feed.players()[0]["gone"])
        self.feed.clock = lambda: p["seen"] + 2 * 24 * 3600
        self.assertEqual(self.feed.players(), [])


if __name__ == "__main__":
    unittest.main()
