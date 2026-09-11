#!/usr/bin/env python3
"""Unison follower HTTP-clock fallback. Stdlib only — no paplay, no LAN."""
import os
import tempfile
import time
import unittest

import unison


class FakePlayer(object):
    def __init__(self, playing=True):
        self.playing = bool(playing)
        self.paused = False
        self.pause_calls = 0
        self.stop_calls = 0
        self.follow_calls = []
        self.heard = 12.5

    def snapshot(self):
        return {
            "playing": bool(self.playing and not self.paused),
            "paused": bool(self.paused and self.playing),
            "clock": {"heard": self.heard, "warming": False},
        }

    def follow_heard(self, heard):
        self.follow_calls.append(heard)
        return True

    def pause(self):
        self.pause_calls += 1
        self.paused = True
        return True

    def stop(self):
        self.stop_calls += 1
        self.playing = False
        self.paused = False
        return True


class HttpClockFallbackTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="crypt-unison-")
        self.path = os.path.join(self.folder, "sync.json")
        self.gets = []
        self.get_error = None
        self.get_body = {
            "ok": True,
            "player": {
                "playing": True,
                "paused": False,
                "clock": {"heard": 12.5},
            },
        }
        self.u = unison.Unison(path=self.path, get=self._get, post=lambda *a, **k: None)
        self.u._alive = False
        if self.u._thread is not None:
            self.u._thread.join(timeout=2)
        self.player = FakePlayer()
        self.u.player = self.player
        self.u.set_on(True)
        self.u.follow("http://192.168.1.142", "001AAE0739DB0000")

    def tearDown(self):
        self.u._alive = False

    def _get(self, url, timeout=2):
        self.gets.append((url, timeout))
        if self.get_error is not None:
            raise self.get_error
        return self.get_body

    def test_silence_while_conductor_playing_does_not_pause(self):
        """CLOCK quiet is not pause: HTTP still says playing, local keeps paplay."""
        self.u._fallback_http_clock()
        self.assertEqual(self.player.pause_calls, 0)
        self.assertEqual(self.player.stop_calls, 0)
        self.assertTrue(self.player.snapshot()["playing"])
        self.assertEqual(self.player.follow_calls, [12.5])
        self.assertTrue(self.u.snapshot()["following"])

    def test_confirmed_playing_false_pauses_local(self):
        self.get_body = {
            "ok": True,
            "player": {"playing": False, "paused": True, "clock": {}},
        }
        self.u._fallback_http_clock()
        self.assertEqual(self.player.pause_calls, 1)
        self.assertEqual(self.player.stop_calls, 0)
        self.assertFalse(self.player.snapshot()["playing"])
        self.assertTrue(self.player.snapshot()["paused"])
        self.assertTrue(self.u.snapshot()["following"])
        self.assertIsNone(self.u.snapshot()["drift_ms"])

    def test_confirmed_stopped_stops_local(self):
        self.get_body = {
            "ok": True,
            "player": {"playing": False, "paused": False, "name": "", "clock": {}},
        }
        self.u._fallback_http_clock()
        self.assertEqual(self.player.stop_calls, 1)
        self.assertEqual(self.player.pause_calls, 0)
        self.assertFalse(self.player.snapshot()["playing"])
        self.assertFalse(self.u.snapshot()["following"])

    def test_unreachable_clock_holds(self):
        self.get_error = OSError("conductor unreachable")
        self.u._fallback_http_clock()
        self.assertEqual(self.player.pause_calls, 0)
        self.assertEqual(self.player.stop_calls, 0)
        self.assertTrue(self.player.snapshot()["playing"])
        self.assertTrue(self.u.snapshot()["following"])
        self.assertEqual(len(self.gets), 1)

    def test_note_clock_not_playing_does_not_pause(self):
        """UDP CLOCK with FLAG_PLAYING clear is not the pause path (HTTP confirm)."""
        self.u.note_clock({
            "kind": "clock",
            "uid": "001AAE0739DB0000",
            "playing": False,
            "heard": 12.5,
        })
        self.assertEqual(self.player.pause_calls, 0)
        self.assertEqual(self.player.stop_calls, 0)
        self.assertTrue(self.player.snapshot()["playing"])
        self.assertEqual(self.gets, [])


class GroupPlayTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="crypt-group-")
        self.path = os.path.join(self.folder, "sync.json")
        self.posts = []
        self.u = unison.Unison(path=self.path, get=lambda *a, **k: {}, post=self._post)
        self.u._alive = False
        if self.u._thread is not None:
            self.u._thread.join(timeout=2)

    def tearDown(self):
        self.u._alive = False
        import shutil
        shutil.rmtree(self.folder, ignore_errors=True)

    def _post(self, url, data=None, timeout=4):
        self.posts.append((url, data, timeout))
        return {"ok": True}

    def test_old_on_true_does_not_target_shelves(self):
        with open(self.path, "w") as fh:
            fh.write('{"on": true}')
        u = unison.Unison(path=self.path, get=lambda *a, **k: {}, post=self._post)
        u._alive = False
        if u._thread is not None:
            u._thread.join(timeout=2)
        self.assertEqual(u._targets(), [])
        self.assertFalse(u.snapshot()["grouped"])

    def test_add_room_is_the_only_target(self):
        self.u.add_room("http://192.168.1.142")
        self.assertEqual(self.u._targets(), ["http://192.168.1.142"])
        snap = self.u.snapshot()
        self.assertTrue(snap["grouped"])
        self.assertEqual(len(snap["rooms"]), 1)

    def test_broadcast_only_hits_group(self):
        self.u.add_room("http://192.168.1.142")
        self.u.broadcast("/api/unison/follow", {"name": "Glow.flac"})
        time.sleep(0.05)
        urls = [p[0] for p in self.posts]
        self.assertEqual(urls, ["http://192.168.1.142/api/unison/follow"])
        self.posts[:] = []
        self.u.set_rooms([])
        self.u.broadcast("/api/unison/follow", {"name": "Glow.flac"})
        time.sleep(0.05)
        self.assertEqual(self.posts, [])

    def test_follow_works_when_local_group_empty(self):
        """Conductor can add this jack even if Unison/group was off here."""
        self.assertEqual(self.u._targets(), [])
        self.u.follow("http://192.168.1.179", "001AAE10E4090000")
        snap = self.u.snapshot()
        self.assertTrue(snap["following"])
        self.assertEqual(snap["conductor_stamp"], "E409")

    def test_set_on_false_clears_rooms(self):
        self.u.add_room("http://192.168.1.142")
        self.u.set_on(False)
        self.assertEqual(self.u._targets(), [])
        self.assertFalse(self.u.snapshot()["grouped"])


if __name__ == "__main__":
    unittest.main()
