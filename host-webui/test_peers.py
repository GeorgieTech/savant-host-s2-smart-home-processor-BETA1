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
            idx = peers.PeerIndex(path="/no/such.json", http=fake_http, hot_path=os.path.join(folder, "hot.json"))
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
            self.assertTrue(idx.is_hot("Glow.wav"))
            with open(dest, "rb") as fh:
                self.assertEqual(fh.read(), b"RIFFTEST")
        finally:
            peers.MUSIC_DIR = old
            shutil.rmtree(folder, ignore_errors=True)


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


class HelloContractTests(unittest.TestCase):
    def test_hello_is_self_libver_linked_uids(self):
        idx = peers.PeerIndex(path="/no/such.json", http=lambda url: {}, seen_path="/no/such/seen.json")
        idx._cfg = {
            "id": "crypt-viewer",
            "shelves": [
                {"id": "crypt-001aae10e4090000", "url": "http://192.168.1.179", "uid": "001AAE10E4090000"},
                {"id": "crypt-001aae0739db0000", "url": "http://192.168.1.142", "uid": "001AAE0739DB0000"},
            ],
        }
        tracks = [{"name": "Glow.flac", "size": 12, "mtime": 8}]
        idx.note_local_catalog(tracks)
        idx.note_beacon({
            "crypt": 1,
            "id": "crypt-001aae00abc00000",
            "uid": "001AAE00ABC00000",
            "host": "crypt-001aae00abc00000",
        }, "192.168.1.150")
        payload = idx.hello({"tracks": 71, "playing": True, "now": "Glow.flac"})
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["crypt"], 1)
        self.assertEqual(payload["id"], "crypt-viewer")
        self.assertEqual(payload["version"], peers.VERSION)
        self.assertEqual(payload["libver"], __import__("crypt_wire").libver(tracks))
        self.assertEqual(payload["linked"], ["001AAE10E4090000", "001AAE0739DB0000"])
        self.assertEqual(payload["tracks"], 71)
        self.assertTrue(payload["playing"])
        self.assertEqual(payload["now"], "Glow.flac")
        self.assertNotIn("seen", payload)
        self.assertNotIn("shelves", payload)
        for key in ("uid", "host", "ip", "url", "model"):
            self.assertIn(key, payload)

    def test_hello_omits_seen_even_when_roster_is_full(self):
        idx = peers.PeerIndex(path="/no/such.json", http=lambda url: {}, seen_path="/no/such/seen.json")
        idx._cfg = {"id": "crypt-viewer", "shelves": []}
        for i, ip in enumerate(("192.168.1.150", "192.168.1.151", "192.168.1.152")):
            uid = "001AAE00ABC%05d" % i
            idx.note_beacon({
                "crypt": 1,
                "id": "crypt-%s" % uid.lower(),
                "uid": uid,
                "host": "crypt-%s" % uid.lower(),
            }, ip)
        payload = idx.hello()
        self.assertEqual(payload["linked"], [])
        self.assertNotIn("seen", payload)
        self.assertNotIn("shelves", payload)
        self.assertEqual(payload["libver"], 0)

    def test_probe_url_hellos_one_target_and_drops_gossip(self):
        calls = []

        def fake(url):
            calls.append(url)
            return {
                "ok": True,
                "crypt": 1,
                "id": "crypt-001aae10e4090000",
                "uid": "001AAE10E4090000",
                "host": "crypt-001aae10e4090000",
                "ip": "192.168.1.179",
                "model": "SHR-S2-00",
                "version": "1.1.12",
                "libver": 99,
                "linked": ["001AAE0739DB0000"],
                "tracks": 71,
                "playing": False,
                "shelves": [{"id": "crypt-third", "uid": "001AAE00ABC00000", "url": "http://192.168.1.150"}],
                "seen": [{
                    "id": "crypt-third",
                    "uid": "001AAE00ABC00000",
                    "ip": "192.168.1.150",
                    "url": "http://192.168.1.150",
                    "model": "SHC-S2-00",
                }],
            }

        idx = peers.PeerIndex(path="/no/such.json", http=fake, seen_path="/no/such/seen.json")
        idx._cfg = {"id": "crypt-viewer", "shelves": []}
        host, err = idx.probe_url("http://192.168.1.179")
        self.assertEqual(err, "")
        self.assertIsNotNone(host)
        self.assertEqual(host["uid"], "001AAE10E4090000")
        self.assertEqual(host["tracks"], 71)
        self.assertEqual(host.get("libver"), 99)
        self.assertEqual(calls, ["http://192.168.1.179/api/hello"])
        rows = idx.roster(probe=False)
        uids = [r.get("uid") for r in rows if r.get("uid")]
        self.assertIn("001AAE10E4090000", uids)
        self.assertNotIn("001AAE00ABC00000", uids)

    def test_roster_still_comes_from_beacons_without_hello(self):
        idx = peers.PeerIndex(
            path="/no/such.json",
            http=lambda url: (_ for _ in ()).throw(RuntimeError("hello must not run")),
            seen_path="/no/such/seen.json",
        )
        idx._cfg = {"id": "crypt-viewer", "shelves": []}
        idx.note_beacon({
            "crypt": 1,
            "id": "crypt-001aae10e4090000",
            "uid": "001AAE10E4090000",
            "host": "crypt-001aae10e4090000",
            "v": "1.1.12",
        }, "192.168.1.179")
        rows = [r for r in idx.roster(probe=False) if not r.get("self")]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["uid"], "001AAE10E4090000")
        self.assertTrue(rows[0]["online"])
        self.assertIn("beacon", rows[0].get("via") or [])

    def test_probe_lists_us_from_linked_uids(self):
        def fake(url):
            return {
                "ok": True,
                "crypt": 1,
                "id": "crypt-001aae10e4090000",
                "uid": "001AAE10E4090000",
                "host": "crypt-001aae10e4090000",
                "ip": "192.168.1.179",
                "libver": 1,
                "linked": ["001AAE0739DB0000"],
                "tracks": 4,
            }

        idx = peers.PeerIndex(path="/no/such.json", http=fake, seen_path="/no/such/seen.json")
        idx._cfg = {"id": "crypt-001aae0739db0000", "shelves": []}
        host, err = idx.probe_url("http://192.168.1.179")
        self.assertEqual(err, "")
        self.assertTrue(host["lists_us"])
        self.assertTrue(host["sees_us"])


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
                    "libver": 0,
                    "linked": [],
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


if __name__ == "__main__":
    unittest.main()
