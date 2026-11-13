"""Tests for viewers.py. Run: python3 test_viewers.py"""
import json
import os
import shutil
import stat
import tempfile
import unittest

import auth
from auth import AuthError
from viewers import Viewers


class Clock:
    def __init__(self):
        self.now = 1_000_000.0

    def __call__(self):
        return self.now


class ViewersTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "viewers.json")
        self.clock = Clock()
        self.v = Viewers(self.path, clock=self.clock)
        self.saved = auth.ITERATIONS
        auth.ITERATIONS = 1000                  # fast tests; the real value is 200,000

    def tearDown(self):
        auth.ITERATIONS = self.saved
        shutil.rmtree(self.dir)

    def test_no_file_until_the_first_user_and_then_it_is_private_and_holds_no_password(self):
        self.assertEqual(self.v.list(), [])
        self.assertFalse(os.path.exists(self.path))
        self.v.save("Kid", "cartoons please", ["102", "112"])
        self.assertEqual(stat.S_IMODE(os.stat(self.path).st_mode), 0o600)
        with open(self.path) as f:
            self.assertNotIn("cartoons please", f.read())
        self.assertEqual(self.v.list(), [{"name": "kid", "channels": ["102", "112"]}])

    def test_login_gives_a_session_that_names_the_user_whatever_the_case_typed(self):
        self.v.save("kid", "cartoons please", ["102"])
        self.assertEqual(self.v.user(self.v.login(" Kid ", "cartoons please")), "kid")
        for name, pw in (("kid", "wrong password"), ("nobody", "cartoons please"), (None, "cartoons please"), ("kid", None)):
            with self.assertRaises(AuthError):
                self.v.login(name, pw)

    def test_channels_none_means_every_channel(self):
        self.v.save("mum", "grown up tv")
        self.v.save("kid", "cartoons please", ["102", "102", "112"])
        self.assertIsNone(self.v.channels("mum"))
        self.assertEqual(self.v.channels("kid"), {"102", "112"})
        self.v.save("kid", channels=[])                              # no password given: it is kept
        self.assertEqual(self.v.channels("kid"), set())
        self.assertTrue(self.v.verify("kid", "cartoons please"))

    def test_bad_names_passwords_and_channel_lists_are_refused(self):
        for name in ("", "has space", "dot.dot", "x" * 33, None, 7):
            with self.assertRaises(AuthError, msg=name):
                self.v.save(name, "long enough")
        with self.assertRaises(AuthError):
            self.v.save("kid")                                       # a new user needs a password
        with self.assertRaises(AuthError):
            self.v.save("kid", "short")
        for chans in ("102", [102], [""], ["x" * 17]):
            with self.assertRaises(AuthError, msg=chans):
                self.v.save("kid", "long enough", chans)
        self.assertEqual(self.v.list(), [])

    def test_a_new_password_or_removal_ends_that_users_sessions_only(self):
        self.v.save("mum", "grown up tv")
        self.v.save("kid", "cartoons please")
        mum, kid = self.v.login("mum", "grown up tv"), self.v.login("kid", "cartoons please")
        self.v.save("kid", "a new password")
        self.assertIsNone(self.v.user(kid))
        self.assertEqual(self.v.user(mum), "mum")
        self.v.remove("mum")
        self.assertIsNone(self.v.user(mum))
        with self.assertRaises(AuthError):
            self.v.remove("mum")

    def test_sessions_expire_can_be_revoked_and_cannot_be_forged(self):
        self.v.save("mum", "grown up tv")
        self.v.save("kid", "cartoons please")
        token = self.v.login("kid", "cartoons please")
        expiry, nonce, name, sig = token.split(".")
        for forged in (f"{expiry}.{nonce}.mum.{sig}", f"{int(expiry) + 9}.{nonce}.kid.{sig}", f"{expiry}.{nonce}.kid.é",
                       "", "a.b.c", "x.y.kid.z", None, f"{expiry}.{nonce}.nobody.{sig}"):
            self.assertIsNone(self.v.user(forged), forged)
        other = self.v.login("kid", "cartoons please")
        self.v.revoke(token)
        self.assertIsNone(self.v.user(token))
        self.assertEqual(self.v.user(other), "kid")
        self.clock.now += auth.SESSION_SECONDS + 1
        self.assertIsNone(self.v.user(other))

    def test_the_dashboard_and_the_viewer_each_write_a_file_of_their_own(self):
        self.v.save("kid", "cartoons please")
        with open(self.path) as f:
            accounts = f.read()
        token = self.v.login("kid", "cartoons please")
        self.v.revoke(token)                                         # the viewer's side: a log out
        self.v.beat()
        with open(self.path) as f:
            self.assertEqual(f.read(), accounts)                     # the accounts file was not touched
        with open(os.path.join(self.dir, "sessions.json")) as f:
            self.assertEqual(list(json.load(f).values()), [int(token.split(".")[0])])
        self.assertEqual(stat.S_IMODE(os.stat(os.path.join(self.dir, "sessions.json")).st_mode), 0o600)

    def test_the_switch_is_on_until_switched_off_and_keeps_the_users(self):
        self.assertTrue(self.v.is_on())                              # no file yet
        self.v.save("kid", "cartoons please", ["102"])
        self.v.switch(False)
        self.assertFalse(self.v.is_on())
        self.assertEqual(self.v.list(), [{"name": "kid", "channels": ["102"]}])
        self.v.save("kid", channels=["103"])                         # saving a user leaves the switch alone
        self.assertFalse(self.v.is_on())
        self.v.switch(True)
        self.assertTrue(self.v.is_on())
        self.assertEqual(self.v.user(self.v.login("kid", "cartoons please")), "kid")

    def test_running_is_a_heartbeat_younger_than_a_minute_and_a_half(self):
        self.assertFalse(self.v.running())
        self.v.beat()
        self.assertTrue(self.v.running())
        self.clock.now += 89
        self.assertTrue(self.v.running())
        self.clock.now += 2
        self.assertFalse(self.v.running())
        self.v.beat()
        self.assertTrue(self.v.running())

    def test_too_many_wrong_guesses_must_wait(self):
        self.v.save("kid", "cartoons please")
        for _ in range(auth.FAIL_LIMIT):
            with self.assertRaises(AuthError):
                self.v.login("kid", "wrong password", "1.2.3.4")
        with self.assertRaisesRegex(AuthError, "wait"):
            self.v.login("kid", "cartoons please", "1.2.3.4")
        self.assertTrue(self.v.login("kid", "cartoons please", "5.6.7.8"))    # another address is not held up

    def test_a_damaged_file_is_no_users_not_a_crash(self):
        for text in ("not json", "[]", json.dumps({"users": []}), json.dumps({"users": {"kid": {}}, "secret": "s"})):
            with open(self.path, "w") as f:
                f.write(text)
            self.assertIsNone(self.v.user("1.2.kid.3"))
            with self.assertRaises(AuthError):
                self.v.login("kid", "cartoons please", text)


if __name__ == "__main__":
    unittest.main()
