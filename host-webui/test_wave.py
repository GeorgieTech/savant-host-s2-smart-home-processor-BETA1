#!/usr/bin/env python3
"""Waveform analyzer tests. Needs ffmpeg; no Pulse."""
import math
import os
import struct
import tempfile
import unittest

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

    def test_new_high_settings_keep_texture(self):
        vals = [0.12] * 80 + [1.0]
        new = cryptwave._scale_band(vals, 0.90, 0.55, 1.12, 0.02)
        self.assertGreater(new[0], 40)


class AnalyzeBandsTests(unittest.TestCase):
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


class BeatGridTests(unittest.TestCase):
    def test_impulse_train_is_120_bpm(self):
        rate = 80.0
        lows = []
        for i in range(int(rate * 12)):
            lows.append(1.0 if i % 40 == 4 else 0.04)
        grid = cryptwave.beat_grid(lows, rate)
        self.assertGreater(grid["bpm"], 116)
        self.assertLess(grid["bpm"], 124)
        self.assertEqual(grid["bar"], 4)
        self.assertLess(abs(grid["beat0"] - (4 / rate)), 0.04)

    def test_flat_envelope_has_no_grid(self):
        grid = cryptwave.beat_grid([0.2] * 400, 80)
        self.assertEqual(grid["bpm"], 0.0)

    def test_analyze_kicks_near_120(self):
        fd, path = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        try:
            chunks = []
            for _ in range(16):
                chunks.append((70, 0.06, 0.85))
                chunks.append((70, 0.44, 0.0))
            _tone_wav(path, chunks)
            data = cryptwave._analyze(path)
            self.assertIsNotNone(data)
            self.assertIn("grid", data)
            bpm = data["grid"]["bpm"]
            self.assertGreater(bpm, 112)
            self.assertLess(bpm, 128)
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
