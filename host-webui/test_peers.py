#!/usr/bin/env python3
"""Peer shelf catalog tests. No live hosts."""
import json
import os
import shutil
import tempfile
import unittest

import peers


class UrlGuardTests(unittest.TestCase):
    def test_allows_lab_lan(self):
        self.assertEqual(peers._clean_url("http://192.168.1.179"), "http://192.168.1.179")
        self.assertEqual(peers._clean_url("192.168.1.142"), "http://192.168.1.142")

    def test_blocks_forbidden_and_off_lan(self):
        self.assertEqual(peers._clean_url("http://192.168.1.40"), "")
        self.assertEqual(peers._clean_url("http://192.168.1.178"), "")
        self.assertEqual(peers._clean_url("http://192.168.1.180"), "")
        self.assertEqual(peers._clean_url("https://192.168.1.179"), "")
        self.assertEqual(peers._clean_url("http://8.8.8.8"), "")


class MergeTests(unittest.TestCase):
    def test_viewer_lists_shelf_tracks(self):
        def fake(url):
            self.assertIn("local=1", url)
            self.assertTrue(url.startswith("http://192.168.1.179/"))
            return {"ok": True, "tracks": [
                {"name": "Glow.flac", "title": "Glow", "artist": "CRYPT Test", "album": "Lab", "size": 12},
            ]}
        idx = peers.PeerIndex(path="/no/such/peers.json", http=fake)
        idx._cfg = {
            "id": "crypt-viewer",
            "shelves": [{"id": "crypt-shelf", "url": "http://192.168.1.179"}],
        }
        out = idx.merge([])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["name"], "Glow.flac")
        self.assertEqual(out[0]["owner"], "crypt-shelf")
        self.assertFalse(out[0]["local"])
        self.assertTrue(out[0]["available"])

    def test_local_copy_is_still_owned_by_shelf(self):
        def fake(url):
            return {"ok": True, "tracks": [
                {"name": "Glow.flac", "title": "Glow", "artist": "X", "size": 9},
            ]}
        idx = peers.PeerIndex(path="/no/such/peers.json", http=fake)
        idx._cfg = {
            "id": "crypt-viewer",
            "shelves": [{"id": "crypt-shelf", "url": "http://192.168.1.179"}],
        }
        out = idx.merge([{"name": "Glow.flac", "title": "Glow", "size": 9}])
        self.assertEqual(len(out), 1)
        self.assertTrue(out[0]["local"])
        self.assertEqual(out[0]["owner"], "crypt-shelf")


class EnsureTests(unittest.TestCase):
    def test_ensure_writes_file(self):
        folder = tempfile.mkdtemp(prefix="crypt-music-")
        old = peers.MUSIC_DIR
        peers.MUSIC_DIR = folder
        try:
            calls = []
            def fake_http(url):
                return {"ok": True, "tracks": [{"name": "Glow.wav"}]}
            idx = peers.PeerIndex(path="/no/such.json", http=fake_http)
            idx._cfg = {"id": "v", "shelves": [{"id": "s", "url": "http://192.168.1.179"}]}
            orig_urlopen = peers.urlopen
            class FakeFH(object):
                def read(self, n=-1):
                    if getattr(self, "done", False):
                        return b""
                    self.done = True
                    return b"RIFFTEST"
                def close(self):
                    pass
            def fake_open(req, timeout=30):
                calls.append(req.get_full_url() if hasattr(req, "get_full_url") else str(req))
                return FakeFH()
            peers.urlopen = fake_open
            try:
                ok = idx.ensure("Glow.wav", owner="s")
            finally:
                peers.urlopen = orig_urlopen
            self.assertTrue(ok)
            dest = os.path.join(folder, "Glow.wav")
            self.assertTrue(os.path.isfile(dest))
            with open(dest, "rb") as fh:
                self.assertEqual(fh.read(), b"RIFFTEST")
        finally:
            peers.MUSIC_DIR = old
            shutil.rmtree(folder, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
