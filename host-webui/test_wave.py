#!/usr/bin/env python3
"""Waveform analyzer tests. Needs ffmpeg; no Pulse."""
import math
import os
import shutil
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wave as cryptwave


def _tone_wav(path, chunks):
    rate = 44100
    samples = []
    for freq, seconds, amp in chunks:
        n = int(rate * seconds)
        for i in range(n):
            x = amp * math.sin(2 * math.pi * freq * (i / float(rate)))
            samples.append(int(max(-32767, min(32767, x * 32767))))
    data = struct.pack("<%dh" % len(samples), *samples)
    with open(path, "wb") as fh:
        fh.write(b"RIFF")
        fh.write(struct.pack("<I", 36 + len(data)))
        fh.write(b"WAVEfmt ")
        fh.write(struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16))
        fh.write(b"data")
        fh.write(struct.pack("<I", len(data)))
        fh.write(data)


class ScaleBandTests(unittest.TestCase):
    def test_old_high_settings_killed_texture(self):
        vals = [0.02] * 80 + [1.0]
        old = cryptwave._scale_band(vals, 0.995, 0.92, 0.34, 0.16)
        self.assertEqual(old[0], 0)

    def test_dense_hats_stay_visible(self):
        vals = [0.35] * 50 + [0.55] * 30 + [1.0]
        out = cryptwave._scale_band(vals, *cryptwave.SCALE_HIGH)
        self.assertGreater(out[0], 25)

    def test_sparse_floor_is_not_full_scale(self):
        vals = [0.05] * 80 + [1.0]
        out = cryptwave._scale_band(vals, *cryptwave.SCALE_HIGH)
        self.assertLess(out[0], 90)
        self.assertGreater(out[-1], 180)


class AnalyzeBandsTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg required")
    def test_three_tones_land_in_the_right_band(self):
        fd, path = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        try:
            _tone_wav(
                path,
                ((80, 1.0, 0.6), (1000, 1.0, 0.6), (8000, 1.0, 0.6)),
            )
            data = cryptwave._analyze(path)
            self.assertIsNotNone(data)
            self.assertEqual(data["v"], cryptwave.WAVE_VER)
            n = data["n"]
            a, b = n // 3, 2 * n // 3

            def mean(arr, lo, hi):
                part = arr[lo:hi]
                return sum(part) / float(len(part) or 1)

            l80, m80, h80 = mean(data["l"], 0, a), mean(data["m"], 0, a), mean(data["h"], 0, a)
            l1k, m1k, h1k = mean(data["l"], a, b), mean(data["m"], a, b), mean(data["h"], a, b)
            l8k, m8k, h8k = mean(data["l"], b, n), mean(data["m"], b, n), mean(data["h"], b, n)
            self.assertGreater(l80, m80)
            self.assertGreater(l80, h80)
            self.assertGreater(m1k, l1k)
            self.assertGreater(m1k, h1k)
            self.assertGreater(h8k, l8k)
            self.assertGreater(h8k, m8k)
            self.assertGreater(h8k, 80)
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
