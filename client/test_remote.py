#!/usr/bin/env python3
"""Which input devices the remote takes. Run: python3 test_remote.py"""
import unittest

import remote


class TestRemote(unittest.TestCase):
    def test_keyboards_and_remotes_are_taken(self):
        self.assertTrue(remote.is_keyboard({1: [1, 2, 28, 30, 103, 105, 106, 108]}))     # a keyboard: Esc, 1, Enter, A, arrows
        self.assertTrue(remote.is_keyboard({0: [0], 1: [28, 103, 108, 102], 4: [4]}))    # a Flirc: Enter, up, down, Home

    def test_the_pcs_own_buttons_are_left_alone(self):
        self.assertFalse(remote.is_keyboard({0: [0], 1: [116]}))                        # Power Button
        self.assertFalse(remote.is_keyboard({0: [0], 1: [142]}))                        # Sleep Button
        self.assertFalse(remote.is_keyboard({0: [0], 1: [224, 225, 227, 241]}))         # Video Bus: brightness keys
        self.assertFalse(remote.is_keyboard({0: [0], 5: [2]}))                          # a headphone jack: a switch, no keys
        self.assertFalse(remote.is_keyboard({}))


if __name__ == "__main__":
    unittest.main()
