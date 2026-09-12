#!/usr/bin/env python3
"""Peer shelf catalog tests. No live hosts."""
import json
import os
import shutil
import socket
import tempfile
import time
import unittest

import peers
import unison


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


class ParseContentRangeTests(unittest.TestCase):
    def test_partial_and_unsatisfied(self):
        self.assertEqual(peers._parse_content_range("bytes 4-7/8"), (4, 7, 8))
        self.assertEqual(peers._parse_content_range("bytes */8"), (None, None, 8))
        self.assertEqual(peers._parse_content_range(""), (None, None, None))
        self.assertEqual(peers._parse_content_range("bytes=10-99/200"), (10, 99, 200))


class _FakeHeaders(dict):
    def get(self, key, default=None):
        for name, val in dict.items(self):
            if str(name).lower() == str(key).lower():
                return val
        return default


class _FakeFH(object):
    def __init__(self, body, code=200, headers=None, hiccup_after=None):
        self._body = body
        self._off = 0
        self._code = code
        self.headers = _FakeHeaders(headers or {})
        self._hiccup_after = hiccup_after
        self._reads = 0

    def getcode(self):
        return self._code

    def read(self, n=-1):
        if self._hiccup_after is not None and self._off >= self._hiccup_after:
            raise socket.timeout("timed out")
        if self._off >= len(self._body):
            return b""
        end = len(self._body)
        if self._hiccup_after is not None:
            end = min(end, self._hiccup_after)
        if n is None or n < 0:
            take = end - self._off
        else:
            take = min(n, end - self._off)
        chunk = self._body[self._off:self._off + take]
        self._off += len(chunk)
        self._reads += 1
        return chunk

    def close(self):
        pass


class EnsureTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="crypt-music-")
        self._old_music = peers.MUSIC_DIR
        peers.MUSIC_DIR = self.folder
        self._orig_urlopen = peers.urlopen
        self.calls = []

    def tearDown(self):
        peers.urlopen = self._orig_urlopen
        peers.MUSIC_DIR = self._old_music
        shutil.rmtree(self.folder, ignore_errors=True)

    def _index(self, tracks=None):
        tracks = tracks if tracks is not None else [{"name": "Glow.wav", "size": 8}]
        def fake_http(url, timeout=20):
            return {"ok": True, "tracks": tracks}
        idx = peers.PeerIndex(
            path="/no/such.json",
            http=fake_http,
            hot_path=os.path.join(self.folder, "hot.json"),
        )
        idx._cfg = {"id": "v", "shelves": [{"id": "s", "url": "http://192.168.1.179"}]}
        return idx

    def _install_open(self, handler):
        def fake_open(req, timeout=30):
            rng = req.get_header("Range") if hasattr(req, "get_header") else None
            url = req.get_full_url() if hasattr(req, "get_full_url") else str(req)
            self.calls.append({"url": url, "range": rng, "timeout": timeout})
            return handler(req, rng)
        peers.urlopen = fake_open

    def test_ensure_writes_file(self):
        idx = self._index(tracks=[{"name": "Glow.wav"}])
        self._install_open(lambda req, rng: _FakeFH(b"RIFFTEST"))
        ok = idx.ensure("Glow.wav", owner="s")
        self.assertTrue(ok)
        dest = os.path.join(self.folder, "Glow.wav")
        self.assertTrue(os.path.isfile(dest))
        self.assertTrue(idx.is_hot("Glow.wav"))
        with open(dest, "rb") as fh:
            self.assertEqual(fh.read(), b"RIFFTEST")

    def test_ensure_resumes_part_with_range_206(self):
        idx = self._index()
        part = os.path.join(self.folder, "Glow.wav.part")
        with open(part, "wb") as fh:
            fh.write(b"RIFF")

        def handler(req, rng):
            self.assertEqual(rng, "bytes=4-")
            return _FakeFH(
                b"TEST",
                code=206,
                headers={
                    "Content-Length": "4",
                    "Content-Range": "bytes 4-7/8",
                },
            )

        self._install_open(handler)
        ok = idx.ensure("Glow.wav", owner="s")
        self.assertTrue(ok)
        dest = os.path.join(self.folder, "Glow.wav")
        with open(dest, "rb") as fh:
            self.assertEqual(fh.read(), b"RIFFTEST")
        self.assertFalse(os.path.isfile(part))
        self.assertEqual(self.calls[0]["range"], "bytes=4-")

    def test_ensure_full_200_restarts_part(self):
        idx = self._index()
        part = os.path.join(self.folder, "Glow.wav.part")
        with open(part, "wb") as fh:
            fh.write(b"RIFF")

        def handler(req, rng):
            self.assertEqual(rng, "bytes=4-")
            return _FakeFH(
                b"RIFFTEST",
                code=200,
                headers={"Content-Length": "8"},
            )

        self._install_open(handler)
        ok = idx.ensure("Glow.wav", owner="s")
        self.assertTrue(ok)
        with open(os.path.join(self.folder, "Glow.wav"), "rb") as fh:
            self.assertEqual(fh.read(), b"RIFFTEST")

    def test_ensure_keeps_part_on_hiccup(self):
        idx = self._index()
        self._install_open(lambda req, rng: _FakeFH(
            b"RIFFTEST",
            headers={"Content-Length": "8"},
            hiccup_after=4,
        ))
        ok = idx.ensure("Glow.wav", owner="s")
        self.assertFalse(ok)
        dest = os.path.join(self.folder, "Glow.wav")
        part = os.path.join(self.folder, "Glow.wav.part")
        self.assertFalse(os.path.isfile(dest))
        self.assertTrue(os.path.isfile(part))
        with open(part, "rb") as fh:
            self.assertEqual(fh.read(), b"RIFF")

    def test_ensure_resumes_after_hiccup(self):
        idx = self._index()
        bodies = [
            _FakeFH(b"RIFFTEST", headers={"Content-Length": "8"}, hiccup_after=4),
            _FakeFH(
                b"TEST",
                code=206,
                headers={"Content-Length": "4", "Content-Range": "bytes 4-7/8"},
            ),
        ]

        def handler(req, rng):
            return bodies.pop(0)

        self._install_open(handler)
        self.assertFalse(idx.ensure("Glow.wav", owner="s"))
        part = os.path.join(self.folder, "Glow.wav.part")
        self.assertTrue(os.path.isfile(part))
        self.assertTrue(idx.ensure("Glow.wav", owner="s"))
        dest = os.path.join(self.folder, "Glow.wav")
        with open(dest, "rb") as fh:
            self.assertEqual(fh.read(), b"RIFFTEST")
        self.assertFalse(os.path.isfile(part))
        self.assertEqual(self.calls[0]["range"], None)
        self.assertEqual(self.calls[1]["range"], "bytes=4-")

    def test_ensure_rejects_size_mismatch(self):
        idx = self._index(tracks=[{"name": "Glow.wav", "size": 99}])
        self._install_open(lambda req, rng: _FakeFH(
            b"RIFFTEST",
            headers={"Content-Length": "8"},
        ))
        ok = idx.ensure("Glow.wav", owner="s")
        self.assertFalse(ok)
        self.assertFalse(os.path.isfile(os.path.join(self.folder, "Glow.wav")))
        self.assertFalse(os.path.isfile(os.path.join(self.folder, "Glow.wav.part")))

    def test_ensure_skips_dest_when_size_matches(self):
        idx = self._index()
        dest = os.path.join(self.folder, "Glow.wav")
        with open(dest, "wb") as fh:
            fh.write(b"RIFFTEST")
        self._install_open(lambda req, rng: (_ for _ in ()).throw(AssertionError("should not fetch")))
        ok = idx.ensure("Glow.wav", owner="s")
        self.assertTrue(ok)
        self.assertEqual(self.calls, [])

    def test_ensure_recopies_dest_when_size_mismatches(self):
        idx = self._index()
        dest = os.path.join(self.folder, "Glow.wav")
        with open(dest, "wb") as fh:
            fh.write(b"NO")
        self._install_open(lambda req, rng: _FakeFH(
            b"RIFFTEST",
            headers={"Content-Length": "8"},
        ))
        ok = idx.ensure("Glow.wav", owner="s")
        self.assertTrue(ok)
        with open(dest, "rb") as fh:
            self.assertEqual(fh.read(), b"RIFFTEST")
        self.assertTrue(self.calls)

    def test_ensure_promotes_complete_part_without_fetch(self):
        idx = self._index()
        part = os.path.join(self.folder, "Glow.wav.part")
        with open(part, "wb") as fh:
            fh.write(b"RIFFTEST")
        self._install_open(lambda req, rng: (_ for _ in ()).throw(AssertionError("should not fetch")))
        ok = idx.ensure("Glow.wav", owner="s")
        self.assertTrue(ok)
        dest = os.path.join(self.folder, "Glow.wav")
        with open(dest, "rb") as fh:
            self.assertEqual(fh.read(), b"RIFFTEST")
        self.assertFalse(os.path.isfile(part))
        self.assertEqual(self.calls, [])

    def test_ensure_416_complete_part_promotes(self):
        idx = self._index()
        # Catalog size unknown so we cannot short-circuit; server says we already have all bytes.
        idx = self._index(tracks=[{"name": "Glow.wav"}])
        part = os.path.join(self.folder, "Glow.wav.part")
        with open(part, "wb") as fh:
            fh.write(b"RIFFTEST")

        def handler(req, rng):
            hdrs = _FakeHeaders({"Content-Range": "bytes */8"})
            raise peers.HTTPError(
                req.get_full_url(), 416, "Range Not Satisfiable", hdrs, None,
            )

        self._install_open(handler)
        ok = idx.ensure("Glow.wav", owner="s")
        self.assertTrue(ok)
        with open(os.path.join(self.folder, "Glow.wav"), "rb") as fh:
            self.assertEqual(fh.read(), b"RIFFTEST")


class IdentityTests(unittest.TestCase):
    def test_uid_from_hostname(self):
        self.assertEqual(peers._uid_from("crypt-001aae10e4090000"), "001AAE10E4090000")
        self.assertEqual(peers._uid_from("sav-001aae0739db0000"), "001AAE0739DB0000")
        self.assertEqual(peers._uid_from("192.168.1.111"), "")
        self.assertEqual(peers._uid_from("001AAE10E4090000"), "001AAE10E4090000")
        self.assertEqual(peers.stamp("crypt-001aae10e4090000"), "E409")
        self.assertEqual(peers.stamp("001AAE10E4090000"), "E409")
        self.assertEqual(peers.stamp("001AAE0739DB0000"), "39DB")


class RosterTests(unittest.TestCase):
    def test_three_hosts_stay_unique_by_uid(self):
        folder = tempfile.mkdtemp(prefix="crypt-peers-")
        try:
            path = os.path.join(folder, "peers.json")
            seen = os.path.join(folder, "seen.json")
            with open(path, "w") as fh:
                json.dump({
                    "id": "crypt-viewer",
                    "shelves": [{"id": "crypt-001aae10e4090000", "url": "http://192.168.1.179"}],
                }, fh)
            idx = peers.PeerIndex(path=path, http=lambda url: (_ for _ in ()).throw(RuntimeError("offline")), seen_path=seen)
            idx._cfg = load_cfg()
            idx.note_beacon({
                "crypt": 1,
                "id": "crypt-001aae10e4090000",
                "uid": "001AAE10E4090000",
                "host": "crypt-001aae10e4090000",
                "model": "SHR-S2-00",
                "v": "1.1.9",
            }, "192.168.1.179")
            idx.note_beacon({
                "crypt": 1,
                "id": "crypt-001aae00abc00000",
                "uid": "001AAE00ABC00000",
                "host": "crypt-001aae00abc00000",
                "model": "SHC-S2-00",
                "v": "1.1.9",
            }, "192.168.1.150")
            rows = idx.roster(probe=False)
            uids = [r.get("uid") for r in rows if r.get("uid")]
            self.assertEqual(len(uids), len(set(uids)))
            by_uid = dict((r["uid"], r) for r in rows if r.get("uid"))
            shelf = by_uid["001AAE10E4090000"]
            self.assertTrue(shelf["linked"])
            self.assertTrue(shelf["online"])
            third = by_uid["001AAE00ABC00000"]
            self.assertFalse(third["linked"])
            self.assertTrue(third["online"])
            self.assertFalse(third["self"])
        finally:
            shutil.rmtree(folder, ignore_errors=True)

    def test_beacon_and_shelf_fold_into_one_blade(self):
        idx = peers.PeerIndex(path="/no/such/peers.json", http=lambda url: {}, seen_path="/no/such/seen.json")
        idx._cfg = {
            "id": "crypt-viewer",
            "shelves": [{"id": "crypt-001aae10e4090000", "url": "http://192.168.1.179", "uid": "001AAE10E4090000"}],
        }
        idx.note_beacon({
            "crypt": 1,
            "id": "crypt-001aae10e4090000",
            "uid": "001AAE10E4090000",
            "host": "crypt-001aae10e4090000",
        }, "192.168.1.179")
        rows = [r for r in idx.roster(probe=False) if not r.get("self")]
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["linked"])
        self.assertTrue(rows[0]["online"])
        self.assertEqual(rows[0]["ip"], "192.168.1.179")

    def test_blocked_beacon_is_ignored(self):
        idx = peers.PeerIndex(path="/no/such.json", http=lambda url: {}, seen_path="/no/such/seen.json")
        self.assertIsNone(idx.note_beacon({"crypt": 1, "id": "nope", "uid": "X"}, "192.168.1.40"))
        self.assertIsNone(idx.note_beacon({"crypt": 1, "id": "nope", "uid": "X"}, "192.168.1.178"))
        self.assertEqual(idx.roster(probe=False)[0]["self"], True)
        self.assertEqual(len(idx.roster(probe=False)), 1)


    def test_http_client_without_hello_is_not_a_chassis(self):
        idx = peers.PeerIndex(path="/no/such.json", http=lambda url: (_ for _ in ()).throw(RuntimeError("nope")), seen_path="/no/such/seen.json")
        idx.note_client("192.168.1.111", "CRYPT/1.1.9 (peer)")
        rows = [r for r in idx.roster(probe=False) if not r.get("self")]
        self.assertEqual(rows, [])


class HomeMergeTests(unittest.TestCase):
    def test_hot_copy_keeps_shelf_as_home(self):
        def fake(url):
            return {"ok": True, "tracks": [
                {"name": "Glow.flac", "title": "Glow", "size": 12, "home": True, "owner": "crypt-001aae10e4090000", "owner_uid": "001AAE10E4090000"},
            ]}
        idx = peers.PeerIndex(path="/no/such.json", http=fake, seen_path="/no/such/seen.json", hot_path="/no/such/hot.json")
        idx._cfg = {
            "id": "crypt-001aae0739db0000",
            "shelves": [{"id": "crypt-001aae10e4090000", "url": "http://192.168.1.179", "uid": "001AAE10E4090000"}],
        }
        idx._hot.add("Glow.flac")
        out = idx.merge([{"name": "Glow.flac", "title": "Glow", "size": 12, "home": False}])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["owner"], "crypt-001aae10e4090000")
        self.assertTrue(out[0]["local"])
        self.assertFalse(out[0]["here"])
        self.assertEqual(out[0]["home_stamp"], "E409")

    def test_home_host_does_not_lose_owner_to_a_copy(self):
        def fake(url):
            return {"ok": True, "tracks": [
                {"name": "Glow.flac", "size": 12, "home": False},
            ]}
        idx = peers.PeerIndex(path="/no/such.json", http=fake, seen_path="/no/such/seen.json", hot_path="/no/such/hot.json")
        idx._cfg = {
            "id": "crypt-001aae10e4090000",
            "shelves": [{"id": "crypt-001aae0739db0000", "url": "http://192.168.1.142", "uid": "001AAE0739DB0000"}],
        }
        out = idx.merge([{"name": "Glow.flac", "size": 12, "home": True}])
        self.assertEqual(out[0]["owner"], "crypt-001aae10e4090000")
        self.assertTrue(out[0]["here"])
        self.assertTrue(out[0]["home"])
        self.assertEqual(out[0]["home_stamp"], "E409")


class LinkTests(unittest.TestCase):
    def test_link_saves_shelf_and_unlink_drops_it(self):
        folder = tempfile.mkdtemp(prefix="crypt-link-")
        try:
            path = os.path.join(folder, "peers.json")
            seen = os.path.join(folder, "seen.json")
            with open(path, "w") as fh:
                json.dump({"id": "crypt-viewer", "shelves": []}, fh)

            def fake(url):
                self.assertTrue(url.endswith("/api/hello"))
                return {
                    "ok": True,
                    "crypt": 1,
                    "id": "crypt-001aae10e4090000",
                    "uid": "001AAE10E4090000",
                    "host": "crypt-001aae10e4090000",
                    "ip": "192.168.1.179",
                    "model": "SHR-S2-00",
                    "version": "1.1.9",
                    "shelves": [],
                    "seen": [],
                    "tracks": 71,
                }

            idx = peers.PeerIndex(path=path, http=fake, seen_path=seen, hot_path=os.path.join(folder, "hot.json"))
            ok, err = idx.link("http://192.168.1.179", notify=False)
            self.assertTrue(ok, err)
            cfg = peers.load_config(path)
            self.assertEqual(len(cfg["shelves"]), 1)
            self.assertEqual(cfg["shelves"][0]["url"], "http://192.168.1.179")
            self.assertEqual(cfg["shelves"][0]["uid"], "001AAE10E4090000")
            ok, err = idx.unlink("001AAE10E4090000", notify=False)
            self.assertTrue(ok, err)
            self.assertEqual(peers.load_config(path)["shelves"], [])
        finally:
            shutil.rmtree(folder, ignore_errors=True)

    def test_fetch_shelf_skips_http_when_libver_matches(self):
        calls = []
        tracks = [{"name": "Glow.flac", "size": 12, "mtime": 8}]
        def fake(url, timeout=20):
            calls.append(url)
            return {"ok": True, "tracks": tracks}
        idx = peers.PeerIndex(path="/no/such.json", http=fake)
        idx._cfg = {"id": "v", "shelves": [{"id": "s", "url": "http://192.168.1.179"}]}
        idx.note_beacon({
            "crypt": 1,
            "uid": "001AAE10E4090000",
            "id": "crypt-001aae10e4090000",
            "host": "crypt-001aae10e4090000",
            "libver": __import__("crypt_wire").libver(tracks),
            "tracks": 1,
        }, "192.168.1.179")
        a, err = idx.fetch_shelf({"url": "http://192.168.1.179"})
        self.assertEqual(err, "")
        self.assertEqual(len(a), 1)
        b, err = idx.fetch_shelf({"url": "http://192.168.1.179"})
        self.assertEqual(err, "")
        self.assertEqual(len(calls), 1)

    def test_fetch_shelf_refetches_when_libver_changes(self):
        calls = []
        catalogs = [
            [{"name": "Glow.flac", "size": 12, "mtime": 8}],
            [{"name": "Glow.flac", "size": 12, "mtime": 9}, {"name": "New.flac", "size": 4, "mtime": 1}],
        ]
        def fake(url, timeout=20):
            calls.append(url)
            return {"ok": True, "tracks": catalogs[min(len(calls) - 1, 1)]}
        idx = peers.PeerIndex(path="/no/such.json", http=fake)
        idx._cfg = {"id": "v", "shelves": [{"id": "s", "url": "http://192.168.1.179"}]}
        crypt_wire = __import__("crypt_wire")
        idx.note_beacon({
            "crypt": 1,
            "uid": "001AAE10E4090000",
            "id": "crypt-001aae10e4090000",
            "host": "crypt-001aae10e4090000",
            "libver": crypt_wire.libver(catalogs[0]),
            "tracks": 1,
        }, "192.168.1.179")
        a, err = idx.fetch_shelf({"url": "http://192.168.1.179"})
        self.assertEqual(err, "")
        self.assertEqual(len(a), 1)
        idx.note_beacon({
            "crypt": 1,
            "uid": "001AAE10E4090000",
            "id": "crypt-001aae10e4090000",
            "host": "crypt-001aae10e4090000",
            "libver": crypt_wire.libver(catalogs[1]),
            "tracks": 2,
        }, "192.168.1.179")
        b, err = idx.fetch_shelf({"url": "http://192.168.1.179"})
        self.assertEqual(err, "")
        self.assertEqual(len(calls), 2)
        self.assertEqual(len(b), 2)
        self.assertEqual([t["name"] for t in b], ["Glow.flac", "New.flac"])

    def test_beacon_bin_sets_playing_and_unison_flags(self):
        idx = peers.PeerIndex(path="/no/such.json", http=lambda url: {}, seen_path="/no/such/seen.json")
        idx._local_play_flags = lambda: (True, True)
        pkt = idx._beacon_bin(7)
        out = __import__("crypt_wire").decode(pkt)
        self.assertTrue(out["playing"])
        self.assertTrue(out["unison"])
        payload = idx._beacon_payload()
        raw = json.loads(payload.decode("utf-8"))
        self.assertTrue(raw["playing"])
        self.assertTrue(raw["unison"])

    def test_note_beacon_stores_playing_and_unison(self):
        idx = peers.PeerIndex(path="/no/such.json", http=lambda url: {}, seen_path="/no/such/seen.json")
        idx.note_beacon({
            "crypt": 1,
            "uid": "001AAE10E4090000",
            "id": "crypt-001aae10e4090000",
            "host": "crypt-001aae10e4090000",
            "playing": True,
            "unison": True,
            "tracks": 3,
        }, "192.168.1.179")
        rows = [r for r in idx.roster(probe=False) if r.get("uid") == "001AAE10E4090000"]
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["playing"])
        self.assertTrue(rows[0]["unison"])
        idx.note_beacon({
            "crypt": 1,
            "uid": "001AAE10E4090000",
            "id": "crypt-001aae10e4090000",
            "host": "crypt-001aae10e4090000",
            "playing": False,
            "unison": False,
            "tracks": 3,
        }, "192.168.1.179")
        rows = [r for r in idx.roster(probe=False) if r.get("uid") == "001AAE10E4090000"]
        self.assertFalse(rows[0]["playing"])
        self.assertFalse(rows[0]["unison"])

    def test_link_rejects_forbidden_hosts(self):
        idx = peers.PeerIndex(path="/no/such.json", http=lambda url: {}, seen_path="/no/such/seen.json")
        ok, err = idx.link("http://192.168.1.40")
        self.assertFalse(ok)
        self.assertTrue(err)


def load_cfg():
    return {
        "id": "crypt-viewer",
        "shelves": [{"id": "crypt-001aae10e4090000", "url": "http://192.168.1.179", "uid": "001AAE10E4090000"}],
    }


class _FakeBeaconSock(object):
    """UDP stand-in so start() / _beacon_loop never touch a real port."""

    def __init__(self):
        self.sent = []

    def setsockopt(self, *args, **kwargs):
        return None

    def settimeout(self, value):
        return None

    def bind(self, addr):
        return None

    def sendto(self, data, dest):
        self.sent.append((data, dest))
        return len(data)

    def recvfrom(self, n):
        raise socket.timeout()

    def close(self):
        return None


class IgmpJoinTests(unittest.TestCase):
    def _index(self):
        return peers.PeerIndex(
            path="/no/such.json",
            http=lambda url: {},
            seen_path="/no/such/seen.json",
            hot_path="/no/such/hot.json",
        )

    def test_fleet_exposes_igmp_fields_before_start(self):
        idx = self._index()
        beacon = idx.fleet()["beacon"]
        self.assertFalse(beacon["listening"])
        self.assertFalse(beacon["igmp_ok"])
        self.assertEqual(beacon["igmp_error"], "")
        self.assertEqual(beacon["error"], "")

    def _patch_start(self, fake, join):
        orig = (peers.socket.socket, peers.crypt_wire.join_group, peers._lan_ip)
        peers.socket.socket = lambda *a, **k: fake
        peers.crypt_wire.join_group = join
        peers._lan_ip = lambda: "192.168.1.179"
        return orig

    def _unpatch_start(self, orig):
        peers.socket.socket, peers.crypt_wire.join_group, peers._lan_ip = orig
        peers._ident_cache["t"] = 0.0
        peers._ident_cache["row"] = None

    def test_join_failure_survives_successful_send(self):
        idx = self._index()
        fake = _FakeBeaconSock()

        def boom(*args, **kwargs):
            raise OSError("No such device")

        orig = self._patch_start(fake, boom)
        try:
            idx.start()
            self.assertFalse(idx.igmp_ok)
            self.assertIn("No such device", idx.igmp_error)
            deadline = time.time() + 2.5
            while not idx.beacon_ok and time.time() < deadline:
                time.sleep(0.02)
            self.assertTrue(idx.beacon_ok)
            self.assertTrue(fake.sent)
            self.assertFalse(idx.igmp_ok)
            self.assertIn("No such device", idx.igmp_error)
            beacon = idx.fleet()["beacon"]
            self.assertTrue(beacon["listening"])
            self.assertFalse(beacon["igmp_ok"])
            self.assertIn("No such device", beacon["igmp_error"])
        finally:
            idx.stop()
            self._unpatch_start(orig)

    def test_join_success_sets_igmp_ok(self):
        idx = self._index()
        fake = _FakeBeaconSock()
        orig = self._patch_start(fake, lambda *a, **k: None)
        try:
            idx.start()
            self.assertTrue(idx.igmp_ok)
            self.assertEqual(idx.igmp_error, "")
            deadline = time.time() + 2.5
            while not idx.beacon_ok and time.time() < deadline:
                time.sleep(0.02)
            self.assertTrue(idx.beacon_ok)
            self.assertTrue(idx.igmp_ok)
            self.assertEqual(idx.igmp_error, "")
            beacon = idx.fleet()["beacon"]
            self.assertTrue(beacon["igmp_ok"])
            self.assertEqual(beacon["igmp_error"], "")
        finally:
            idx.stop()
            self._unpatch_start(orig)


class UnisonClockViaTests(unittest.TestCase):
    def test_snapshot_via_http_clock_when_udp_quiet(self):
        folder = tempfile.mkdtemp(prefix="crypt-unison-")
        try:
            path = os.path.join(folder, "sync.json")
            u = unison.Unison(path=path, post=lambda *a, **k: {}, get=lambda *a, **k: {})
            try:
                with u.lock:
                    u._on = True
                    u._follow_url = "http://192.168.1.179"
                    u._follow_uid = "001AAE10E4090000"
                    u._clock_at = 0.0
                snap = u.snapshot()
                self.assertTrue(snap["following"])
                self.assertEqual(snap["via"], "http-clock")
                with u.lock:
                    u._clock_at = time.time()
                snap = u.snapshot()
                self.assertEqual(snap["via"], "udp")
            finally:
                u._alive = False
        finally:
            shutil.rmtree(folder, ignore_errors=True)

    def test_snapshot_via_empty_when_not_following(self):
        folder = tempfile.mkdtemp(prefix="crypt-unison-")
        try:
            path = os.path.join(folder, "sync.json")
            u = unison.Unison(path=path, post=lambda *a, **k: {}, get=lambda *a, **k: {})
            try:
                snap = u.snapshot()
                self.assertFalse(snap["following"])
                self.assertEqual(snap["via"], "")
            finally:
                u._alive = False
        finally:
            shutil.rmtree(folder, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
