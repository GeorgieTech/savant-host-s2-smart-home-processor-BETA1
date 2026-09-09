#!/usr/bin/env python3
"""Time Clock PLL tests. Stdlib only — no Pulse, no ffmpeg."""
import os
import tempfile
import unittest

import player


class LatencyPllTests(unittest.TestCase):
    def test_capture_then_lock(self):
        st = player.new_pll_state(360.0, 90.0, 270.0)
        for _ in range(8):
            player.discipline_latency(st, {"buffer_ms": 92.0, "sink_ms": 268.0, "latency_ms": 360.0})
        self.assertTrue(st["locked"])
        self.assertGreaterEqual(st["n"], 6)
        self.assertLess(st["jitter_ms"], 8.0)
        self.assertAlmostEqual(st["lat_ms"], 360.0, delta=2.0)

    def test_hold_rejects_pulse_spike(self):
        st = player.new_pll_state(360.0, 90.0, 270.0)
        st["locked"] = True
        st["n"] = 12
        st["jitter_ms"] = 1.2
        player.discipline_latency(st, {"buffer_ms": 90.0, "sink_ms": 270.0, "latency_ms": 430.0})
        self.assertFalse(st["accepted"])
        self.assertAlmostEqual(st["lat_ms"], 360.0, delta=0.01)

    def test_hold_moves_slower_than_old_ema(self):
        st = player.new_pll_state(360.0, 90.0, 270.0)
        st["locked"] = True
        st["n"] = 12
        st["jitter_ms"] = 2.0
        player.discipline_latency(st, {"buffer_ms": 94.0, "sink_ms": 272.0, "latency_ms": 366.0})
        moved = abs(st["lat_ms"] - 360.0)
        old_ema = abs((360.0 * 0.62 + 366.0 * 0.38) - 360.0)
        self.assertLess(moved, old_ema)
        self.assertLess(moved, 0.5)

    def test_ignores_priming_buffer(self):
        st = player.new_pll_state(360.0)
        player.discipline_latency(st, {"buffer_ms": 5.0, "sink_ms": 4.0, "latency_ms": 9.0})
        self.assertFalse(st["accepted"])
        self.assertEqual(st["lat_ms"], 360.0)


class FollowPlanTests(unittest.TestCase):
    def test_hold_when_close(self):
        plan, err = player.follow_plan(10.000, 10.008)
        self.assertEqual(plan, "hold")
        self.assertAlmostEqual(err, 0.008, places=4)

    def test_behind_smear_does_not_seek(self):
        plan, err = player.follow_plan(10.0, 10.04)
        self.assertEqual(plan, "hold")
        self.assertAlmostEqual(err, 0.04, places=4)

    def test_ahead_slews_instead_of_restart(self):
        plan, err = player.follow_plan(10.04, 10.0)
        self.assertEqual(plan, "slew")
        self.assertAlmostEqual(err, -0.04, places=4)

    def test_catch_up_when_far_and_cool(self):
        plan, err = player.follow_plan(10.0, 10.2, last_seek_age=9.0, good_age=9.0)
        self.assertEqual(plan, "seek")
        self.assertAlmostEqual(err, 0.2, places=4)

    def test_no_catch_up_right_after_a_lock(self):
        plan, err = player.follow_plan(10.0, 10.2, last_seek_age=9.0, good_age=1.0)
        self.assertEqual(plan, "hold")
        self.assertAlmostEqual(err, 0.2, places=4)

    def test_path_delay_during_warmup_is_hold(self):
        plan, err = player.follow_plan(10.407, 10.0, warming=True)
        self.assertEqual(plan, "hold")
        self.assertAlmostEqual(err, -0.407, places=3)

    def test_no_second_seek_while_pll_relocks(self):
        plan, err = player.follow_plan(10.0, 10.37, last_seek_age=1.5)
        self.assertEqual(plan, "hold")
        self.assertAlmostEqual(err, 0.37, places=3)

    def test_jump_on_discontinuity(self):
        plan, err = player.follow_plan(10.0, 12.0, last_seek_age=2.0)
        self.assertEqual(plan, "seek")


class DecoderSteerTests(unittest.TestCase):
    def test_small_error_is_filtered(self):
        corr = player.discipline_decoder(0.0, 10.0, 10.02, alpha=0.12)
        self.assertAlmostEqual(corr, 0.0024, places=5)

    def test_seek_snaps(self):
        corr = player.discipline_decoder(0.0, 10.0, 12.0)
        self.assertAlmostEqual(corr, 2.0, places=6)

    def test_missing_ref_keeps_corr(self):
        self.assertEqual(player.discipline_decoder(0.07, 1.0, None), 0.07)


class ProgressAndSamplesTests(unittest.TestCase):
    def test_samples_at_48k(self):
        self.assertEqual(player._samples(1.0, 48000), 48000)
        self.assertEqual(player._samples(0.020833, 48000), 1000)

    def test_progress_prefers_last_out_time_us(self):
        fd, path = tempfile.mkstemp(prefix="crypt-ff-")
        os.close(fd)
        try:
            with open(path, "w") as fh:
                fh.write("out_time_us=1000\nprogress=continue\n")
                fh.write("out_time_us=2500000\nprogress=continue\n")
            self.assertAlmostEqual(player._read_out_time_s(path), 2.5, places=6)
        finally:
            os.unlink(path)

    def test_progress_falls_back_to_ms(self):
        fd, path = tempfile.mkstemp(prefix="crypt-ff-")
        os.close(fd)
        try:
            with open(path, "w") as fh:
                fh.write("out_time_ms=1234\nprogress=continue\n")
            self.assertAlmostEqual(player._read_out_time_s(path), 1.234, places=6)
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
