"""A player asking /auto/v<n>?kbps=N gets a shared lower-rate copy of the channel, never above the tuner's own rate.
Run: python3 test_variants.py"""
import json
import os
import sys
import tempfile
import unittest

os.environ.setdefault("FS42_TUNER_CONF", os.path.join(tempfile.mkdtemp(), "c.json"))
json.dump({"db_path": "none.db", "catalog_root": tempfile.mkdtemp(), "channels": {"110": "Prime"}, "media_root": "/tmp", "port": 5098,
           "advertise_url": "http://127.0.0.1:5098"}, open(os.environ["FS42_TUNER_CONF"], "w"))
sys.argv = ["tuner.py"]
import tuner  # noqa: E402


def arg(cmd, flag):
    return cmd[cmd.index(flag) + 1]


class Variants(unittest.TestCase):
    def test_the_rate_asked_for_is_held_between_500_and_the_tuners_own(self):
        self.assertEqual(tuner.stream_kbps({"kbps": ["1500"]}), 1500)
        self.assertEqual(tuner.stream_kbps({"kbps": ["100"]}), 500)
        self.assertIsNone(tuner.stream_kbps({"kbps": ["9000"]}))      # at or over the tuner's 4000: the channel as it is
        self.assertIsNone(tuner.stream_kbps({}))
        self.assertIsNone(tuner.stream_kbps({"kbps": ["fast"]}))

    def test_a_low_rate_is_480p_and_a_high_one_keeps_the_tuners_size(self):
        low, high = tuner.variant_args(1500), tuner.variant_args(3000)
        self.assertEqual((arg(low, "-b:v"), arg(low, "-maxrate")), ("1500k", "1500k"))
        self.assertTrue(arg(low, "-vf").startswith("scale=854:480"))
        self.assertTrue(arg(high, "-vf").startswith(f"scale={tuner.W}:{tuner.H}"))
        self.assertEqual(arg(tuner.NORMALIZE, "-b:v"), "4000k")          # the channel's own encoder is untouched

    def test_a_vaapi_encoder_uploads_after_every_cpu_filter(self):
        hw = tuner.encode_args({"vcodec": "h264_vaapi", "vaapi_device": "/dev/dri/renderD129"}, 1280, 720, 30)
        self.assertEqual(arg(hw, "-vaapi_device"), "/dev/dri/renderD129")
        self.assertEqual(arg(hw, "-c:v"), "h264_vaapi")
        self.assertNotIn("-preset", hw)                                  # x264-only
        self.assertNotIn("-sc_threshold", hw)
        self.assertTrue(arg(hw, "-vf").endswith("format=yuv420p,format=nv12,hwupload"))
        self.assertTrue(tuner.with_subtitles(hw, "subtitles=x.srt")[hw.index("-vf") + 1]
                        .endswith("format=yuv420p,subtitles=x.srt,format=nv12,hwupload"))
        sw = tuner.encode_args({}, 1280, 720, 30)
        self.assertNotIn("-vaapi_device", sw)
        self.assertEqual(arg(sw, "-preset"), "veryfast")
        self.assertTrue(tuner.vf_add(arg(sw, "-vf"), "drawtext=x").endswith("format=yuv420p,drawtext=x"))

    def test_everyone_asking_the_same_rate_shares_one_copy(self):
        ch = tuner.CHANS["110"]
        a, b, c = tuner.variant(ch, 1500), tuner.variant(ch, 1500), tuner.variant(ch, 2500)
        self.assertIs(a, b)
        self.assertIsNot(a, c)
        self.assertEqual((a.number, a.source), ("110@1500", ch))


if __name__ == "__main__":
    unittest.main()
