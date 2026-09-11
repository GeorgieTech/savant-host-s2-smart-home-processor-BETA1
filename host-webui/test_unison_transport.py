#!/usr/bin/env python3
"""Unison follower transport. Stdlib only — no Pulse, no ffmpeg, no LAN."""
from __future__ import print_function

import os
import shutil
import tempfile
import unittest

_ROOT = tempfile.mkdtemp(prefix="crypt-unison-test-")
os.environ["MUSIC_DIR"] = os.path.join(_ROOT, "music")
os.environ["CRYPT_SYNC"] = os.path.join(_ROOT, "sync.json")
os.environ["CRYPT_STATE"] = os.path.join(_ROOT, "crypt")
os.environ["CRYPT_PEERS"] = os.path.join(_ROOT, "peers.json")
os.environ["CRYPT_SEEN"] = os.path.join(_ROOT, "seen.json")
os.environ["CRYPT_HOT"] = os.path.join(_ROOT, "hot.json")
os.environ["CRYPT_WAVES"] = os.path.join(_ROOT, "waves")
os.environ["CRYPT_LYRICS"] = os.path.join(_ROOT, "lyrics")
os.environ["CRYPT_REPORTS"] = os.path.join(_ROOT, "reports")
os.environ["CLOCK_FILE"] = os.path.join(_ROOT, "clock.json")
os.environ["EQ_FILE"] = os.path.join(_ROOT, "eq.json")
os.makedirs(os.environ["MUSIC_DIR"], exist_ok=True)
os.makedirs(os.environ["CRYPT_STATE"], exist_ok=True)

import server
import wave as wave_mod


CONDUCTOR = "http://192.168.1.142"
CONDUCTOR_UID = "001AAE0739DB0000"


class FollowerTransportTests(unittest.TestCase):
    def setUp(self):
        self.app = server.APP
        self.uni = server.UNISON
        self._on = self.uni._on
        self._follow_url = self.uni._follow_url
        self._follow_uid = self.uni._follow_uid
        self._post = self.uni.post
        self._get = self.uni.get
        self._broadcast = self.uni.broadcast
        self._play = self.app.player.play
        self._refresh = self.app.refresh
        self._ensure = self.app._ensure_local
        self._waves = wave_mod.WAVES.ensure
        self._index = self.app.index
        self._order = list(self.app.order)
        self._tracks = list(self.app.tracks)
        self.broadcasts = []
        self.played = []
        self.uni.post = lambda url, body, timeout=4: {"ok": True}
        self.uni.get = lambda url, timeout=2: {}
        self.uni.broadcast = self._capture_broadcast
        wave_mod.WAVES.ensure = lambda *a, **k: None
        self.app.refresh = lambda: None
        self.app._ensure_local = lambda name: True
        self.app.player.play = self._capture_play
        self.app.order = ["Glow.flac", "Fade Away.flac"]
        self.app.tracks = [{"name": "Glow.flac"}, {"name": "Fade Away.flac"}]
        self.app.index = 0
        with self.uni.lock:
            self.uni._on = True
            self.uni._follow_url = ""
            self.uni._follow_uid = ""

    def tearDown(self):
        self.uni.post = self._post
        self.uni.get = self._get
        self.uni.broadcast = self._broadcast
        self.app.player.play = self._play
        self.app.refresh = self._refresh
        self.app._ensure_local = self._ensure
        wave_mod.WAVES.ensure = self._waves
        self.app.index = self._index
        self.app.order = self._order
        self.app.tracks = self._tracks
        with self.uni.lock:
            self.uni._on = self._on
            self.uni._follow_url = self._follow_url
            self.uni._follow_uid = self._follow_uid
            self.uni._drift_ms = None

    def _capture_broadcast(self, path, body):
        self.broadcasts.append((path, dict(body or {})))

    def _capture_play(self, name, start=0.0):
        self.played.append(name)
        return True

    def _follow_peer(self):
        self.uni.follow(CONDUCTOR, CONDUCTOR_UID)
        snap = self.uni.snapshot()
        self.assertTrue(snap["following"])
        self.assertEqual(snap["conductor"], CONDUCTOR_UID)

    def _follow_posts(self):
        return [item for item in self.broadcasts if item[0] == "/api/unison/follow"]

    def test_follower_next_does_not_dual_follow(self):
        self._follow_peer()
        ok = self.app.next_track()
        self.assertFalse(ok)
        self.assertEqual(self.played, [])
        self.assertEqual(self._follow_posts(), [])
        snap = self.uni.snapshot()
        self.assertTrue(snap["following"])
        self.assertEqual(snap["conductor"], CONDUCTOR_UID)
        self.assertTrue(self.uni._follow_url)
        self.assertEqual(self.app.player.error, server.FOLLOWER_TRANSPORT)
        self.assertEqual(self.app.index, 0)

    def test_follower_prev_stop_and_play_are_rejected(self):
        self._follow_peer()
        self.assertFalse(self.app.prev_track())
        self.assertFalse(self.app.stop())
        self.assertFalse(self.app.play_name("Glow.flac"))
        self.assertFalse(self.app._start_name("Fade Away.flac"))
        self.assertEqual(self.played, [])
        self.assertEqual(self.broadcasts, [])
        self.assertTrue(self.uni.snapshot()["following"])
        self.assertTrue(self.uni._follow_url)

    def test_start_name_and_play_name_share_follow_policy(self):
        self._follow_peer()
        self.assertFalse(self.app._apply_unison_role(False))
        self.assertTrue(self.uni.snapshot()["following"])
        self.assertFalse(self.app.play_name("Glow.flac", follow=False))
        self.assertFalse(self.app._start_name("Glow.flac", follow=False))
        self.assertTrue(self.app._apply_unison_role(True, CONDUCTOR, CONDUCTOR_UID))
        self.assertTrue(self.uni.snapshot()["following"])

        with self.uni.lock:
            self.uni._follow_url = ""
            self.uni._follow_uid = ""
        self.assertTrue(self.app._apply_unison_role(False))
        self.assertFalse(self.uni.snapshot()["following"])
        self.assertFalse(self.uni._follow_url)

    def test_conductor_next_still_fans_follow(self):
        ok = self.app.next_track()
        self.assertTrue(ok)
        self.assertEqual(self.played, ["Fade Away.flac"])
        posts = self._follow_posts()
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0][1].get("name"), "Fade Away.flac")
        self.assertEqual(posts[0][1].get("order"), ["Glow.flac", "Fade Away.flac"])
        self.assertFalse(self.uni.snapshot()["following"])
        self.assertFalse(self.uni._follow_url)

    def test_follow_command_still_sets_follower(self):
        ok = self.app.play_name(
            "Glow.flac",
            follow=True,
            conductor=CONDUCTOR,
            conductor_uid=CONDUCTOR_UID,
        )
        self.assertTrue(ok)
        self.assertEqual(self.played, ["Glow.flac"])
        self.assertEqual(self.broadcasts, [])
        snap = self.uni.snapshot()
        self.assertTrue(snap["following"])
        self.assertEqual(snap["conductor"], CONDUCTOR_UID)


if __name__ == "__main__":
    try:
        unittest.main()
    finally:
        shutil.rmtree(_ROOT, ignore_errors=True)
