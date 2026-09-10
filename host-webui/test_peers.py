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
        self.assertEqual(beacon["igmp_iface"], "")
        self.assertFalse(beacon["igmp_rejoined"])
        self.assertEqual(beacon["error"], "")

    def _patch_start(self, fake, join, lan_ip="192.168.1.179", leave=None):
        orig = (
            peers.socket.socket,
            peers.crypt_wire.join_group,
            peers.crypt_wire.leave_group,
            peers._lan_ip,
        )
        peers.socket.socket = lambda *a, **k: fake
        peers.crypt_wire.join_group = join
        if leave is not None:
            peers.crypt_wire.leave_group = leave
        if callable(lan_ip):
            peers._lan_ip = lan_ip
        else:
            peers._lan_ip = lambda: lan_ip
        return orig

    def _unpatch_start(self, orig):
        (
            peers.socket.socket,
            peers.crypt_wire.join_group,
            peers.crypt_wire.leave_group,
            peers._lan_ip,
        ) = orig
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
            self.assertEqual(beacon["igmp_iface"], "192.168.1.179")
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
            self.assertEqual(beacon["igmp_iface"], "192.168.1.179")
            self.assertFalse(beacon["igmp_rejoined"])
        finally:
            idx.stop()
            self._unpatch_start(orig)

    def _assert_leave_both(self, leaves, ip):
        self.assertEqual(set(leaves), {"0.0.0.0", ip})
        self.assertEqual(len(leaves), 2)

    def test_empty_lan_ip_then_ip_appears_rejoins_once(self):
        idx = self._index()
        fake = _FakeBeaconSock()
        box = [""]
        joins = []
        leaves = []

        def join(sock, group=None, iface="0.0.0.0"):
            joins.append(iface)

        def leave(sock, group=None, iface="0.0.0.0"):
            leaves.append(iface)

        orig = self._patch_start(fake, join, lan_ip=lambda: box[0], leave=leave)
        try:
            idx.start()
            self.assertEqual(joins, ["0.0.0.0"])
            self.assertTrue(idx.igmp_ok)
            self.assertTrue(idx._igmp_pending_rejoin)
            box[0] = "192.168.1.179"
            deadline = time.time() + 2.5
            while len(joins) < 2 and time.time() < deadline:
                time.sleep(0.02)
            self.assertEqual(joins, ["0.0.0.0", "192.168.1.179"])
            self._assert_leave_both(leaves, "192.168.1.179")
            self.assertTrue(idx.igmp_ok)
            self.assertEqual(idx.igmp_error, "")
            self.assertFalse(idx._igmp_pending_rejoin)
            self.assertTrue(idx._igmp_rejoined)
            time.sleep(2.2)
            self.assertEqual(joins, ["0.0.0.0", "192.168.1.179"])
            self._assert_leave_both(leaves, "192.168.1.179")
            beacon = idx.fleet()["beacon"]
            self.assertTrue(beacon["igmp_ok"])
            self.assertEqual(beacon["igmp_error"], "")
            self.assertEqual(beacon["igmp_iface"], "192.168.1.179")
            self.assertTrue(beacon["igmp_rejoined"])
        finally:
            idx.stop()
            self._unpatch_start(orig)

    def test_successful_first_join_does_not_rejoin(self):
        idx = self._index()
        fake = _FakeBeaconSock()
        joins = []
        leaves = []

        def join(sock, group=None, iface="0.0.0.0"):
            joins.append(iface)

        def leave(sock, group=None, iface="0.0.0.0"):
            leaves.append(iface)

        orig = self._patch_start(fake, join, lan_ip="192.168.1.179", leave=leave)
        try:
            idx.start()
            self.assertEqual(joins, ["192.168.1.179"])
            self.assertTrue(idx.igmp_ok)
            self.assertFalse(idx._igmp_pending_rejoin)
            deadline = time.time() + 2.5
            while not idx.beacon_ok and time.time() < deadline:
                time.sleep(0.02)
            self.assertTrue(idx.beacon_ok)
            time.sleep(2.2)
            self.assertEqual(joins, ["192.168.1.179"])
            self.assertEqual(leaves, [])
            beacon = idx.fleet()["beacon"]
            self.assertTrue(beacon["igmp_ok"])
            self.assertEqual(beacon["igmp_error"], "")
            self.assertEqual(beacon["igmp_iface"], "192.168.1.179")
            self.assertFalse(beacon["igmp_rejoined"])
        finally:
            idx.stop()
            self._unpatch_start(orig)

    def test_failed_empty_join_then_ip_updates_sticky(self):
        idx = self._index()
        fake = _FakeBeaconSock()
        box = [""]
        joins = []
        leaves = []

        def join(sock, group=None, iface="0.0.0.0"):
            joins.append(iface)
            if iface == "0.0.0.0":
                raise OSError("No such device")

        def leave(sock, group=None, iface="0.0.0.0"):
            leaves.append(iface)

        orig = self._patch_start(fake, join, lan_ip=lambda: box[0], leave=leave)
        try:
            idx.start()
            self.assertEqual(joins, ["0.0.0.0"])
            self.assertFalse(idx.igmp_ok)
            self.assertIn("No such device", idx.igmp_error)
            deadline = time.time() + 2.5
            while not idx.beacon_ok and time.time() < deadline:
                time.sleep(0.02)
            self.assertTrue(idx.beacon_ok)
            self.assertFalse(idx.igmp_ok)
            self.assertIn("No such device", idx.igmp_error)
            box[0] = "192.168.1.179"
            deadline = time.time() + 2.5
            while len(joins) < 2 and time.time() < deadline:
                time.sleep(0.02)
            self.assertEqual(joins, ["0.0.0.0", "192.168.1.179"])
            self._assert_leave_both(leaves, "192.168.1.179")
            self.assertTrue(idx.igmp_ok)
            self.assertEqual(idx.igmp_error, "")
            beacon = idx.fleet()["beacon"]
            self.assertTrue(beacon["listening"])
            self.assertTrue(beacon["igmp_ok"])
            self.assertEqual(beacon["igmp_error"], "")
            self.assertEqual(beacon["igmp_iface"], "192.168.1.179")
            self.assertTrue(beacon["igmp_rejoined"])
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
