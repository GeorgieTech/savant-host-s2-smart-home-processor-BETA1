#!/usr/bin/env python3
"""Grouped TOSLINK: play this jack, then add linked hosts (Sonos-style).

Default is local-only. Linked shelves are not overwritten until you add
them to the play-to group. Each added chassis copies the track, then
plays it on its own optical jack and rides CLOCK. No NAS, no ffmpeg HTTP.
Python 3.8 stdlib only.
"""
from __future__ import print_function

import json
import os
import threading
import time
import traceback

from peers import PEERS, _clean_url, _http_json, _http_post, identity, stamp
import crypt_wire

SYNC_FILE = os.environ.get("CRYPT_SYNC", "/data/crypt/sync.json")


def _load_rooms(path):
    """Old {on: true} without rooms means local-only — do not hijack shelves."""
    try:
        with open(path, "r") as fh:
            raw = json.load(fh)
        if not isinstance(raw, dict):
            return []
        rooms = raw.get("rooms")
        if not isinstance(rooms, list):
            return []
        out = []
        seen = set()
        for item in rooms:
            url = _clean_url(item if not isinstance(item, dict) else (item.get("url") or ""))
            if url and url not in seen:
                seen.add(url)
                out.append(url)
        return out
    except (OSError, ValueError, TypeError):
        return []


def _save_rooms(path, rooms):
    folder = os.path.dirname(path)
    if folder:
        try:
            os.makedirs(folder, exist_ok=True)
        except OSError:
            return
    tmp = path + ".tmp"
    payload = {"rooms": list(rooms or []), "on": bool(rooms)}
    try:
        with open(tmp, "w") as fh:
            json.dump(payload, fh)
        os.replace(tmp, path)
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass


class Unison(object):
    def __init__(self, path=None, post=None, get=None):
        self.path = path or SYNC_FILE
        self.post = post or _http_post
        self.get = get or _http_json
        self.player = None
        self.lock = threading.Lock()
        self._rooms = _load_rooms(self.path)
        self._on = bool(self._rooms)
        self._follow_url = ""
        self._follow_uid = ""
        self._drift_ms = None
        self._clock_pkt = None
        self._clock_at = 0.0
        self._seq = crypt_wire.now_seq()
        self._thread = None
        self._alive = True
        t = threading.Thread(target=self._loop, name="crypt-unison", daemon=True)
        self._thread = t
        t.start()

    def snapshot(self):
        shelves = PEERS.config().get("shelves") or []
        linked_hosts = []
        for shelf in shelves:
            url = _clean_url(shelf.get("url") or "")
            if not url:
                continue
            uid = shelf.get("uid") or ""
            linked_hosts.append({
                "url": url,
                "uid": uid,
                "id": shelf.get("id") or "",
                "stamp": stamp(uid or shelf.get("id") or url),
            })
        with self.lock:
            following = bool(self._follow_url)
            rooms = list(self._rooms)
            clock_age = time.time() - self._clock_at if self._clock_at else 999
            via = ""
            if following:
                via = "udp" if clock_age <= 0.25 else "http-clock"
            grouped = bool(rooms)
        room_rows = [h for h in linked_hosts if h.get("url") in rooms]
        extra = [u for u in rooms if u not in [h.get("url") for h in room_rows]]
        for url in extra:
            room_rows.append({"url": url, "uid": "", "id": "", "stamp": stamp(url)})
        return {
            "on": grouped or following,
            "grouped": grouped,
            "rooms": room_rows,
            "linked_hosts": linked_hosts,
            "linked": len(linked_hosts),
            "following": following,
            "conductor": self._follow_uid,
            "conductor_stamp": stamp(self._follow_uid) if self._follow_uid else "",
            "drift_ms": self._drift_ms,
            "via": via,
        }

    def set_on(self, on):
        """Legacy. on=false clears the play-to group. on=true does not add shelves."""
        if not on:
            dropped = self.set_rooms([])
            with self.lock:
                self._follow_url = ""
                self._follow_uid = ""
                self._drift_ms = None
            return self.snapshot()
        with self.lock:
            self._on = bool(self._rooms)
        return self.snapshot()

    def set_rooms(self, urls):
        seen = set()
        rooms = []
        for item in urls or []:
            url = _clean_url(item if not isinstance(item, dict) else (item.get("url") or ""))
            if url and url not in seen:
                seen.add(url)
                rooms.append(url)
        with self.lock:
            self._rooms = rooms
            self._on = bool(rooms)
        _save_rooms(self.path, rooms)
        return rooms

    def add_room(self, url):
        url = _clean_url(url)
        if not url:
            return False
        with self.lock:
            if url in self._rooms:
                rooms = list(self._rooms)
            else:
                rooms = list(self._rooms) + [url]
                self._rooms = rooms
                self._on = True
        _save_rooms(self.path, rooms)
        return True

    def remove_room(self, url):
        url = _clean_url(url)
        with self.lock:
            rooms = [u for u in self._rooms if u != url]
            self._rooms = rooms
            self._on = bool(rooms)
        _save_rooms(self.path, rooms)
        return url

    def follow(self, url, uid=""):
        url = _clean_url(url)
        with self.lock:
            self._follow_url = url
            self._follow_uid = str(uid or "")
            if url:
                self._on = True

    def unfollow(self):
        with self.lock:
            self._follow_url = ""
            self._follow_uid = ""
            self._drift_ms = None

    def _targets(self, urls=None):
        me = identity()
        mine = set(filter(None, [me.get("ip"), me.get("url"), urlparse_host(me.get("url"))]))
        src = urls if urls is not None else self._rooms
        out = []
        for item in src or []:
            url = _clean_url(item if not isinstance(item, dict) else (item.get("url") or ""))
            host = urlparse_host(url)
            if not url or host in mine or url in mine:
                continue
            if url not in out:
                out.append(url)
        return out

    def broadcast(self, path, body, urls=None):
        payload = dict(body or {})
        payload["follow"] = True
        me = identity()
        payload["conductor"] = me.get("url") or (("http://%s" % me["ip"]) if me.get("ip") else "")
        payload["conductor_uid"] = me.get("uid") or ""
        targets = list(self._targets(urls))
        if not targets:
            return

        def run():
            for url in targets:
                try:
                    self.post(url + path, payload, timeout=4)
                except Exception:
                    pass

        threading.Thread(target=run, daemon=True, name="unison-fan").start()

    def note_clock(self, payload, addr_ip=""):
        """Apply a CRYPT/1 CLOCK datagram from the conductor."""
        if not payload or payload.get("kind") != "clock":
            return
        me = identity()
        uid = str(payload.get("uid") or "")
        if uid and uid == (me.get("uid") or ""):
            return
        with self.lock:
            if not self._follow_url:
                return
            if self._follow_uid and uid and uid != self._follow_uid:
                return
            self._clock_pkt = dict(payload)
            self._clock_at = time.time()
        player = self.player
        heard = payload.get("heard")
        if player is None or heard is None:
            return
        local = player.snapshot()
        if not local.get("playing") or not payload.get("playing"):
            with self.lock:
                self._drift_ms = None
            return
        player.follow_heard(heard)
        local_snap = player.snapshot()
        local_heard = ((local_snap.get("clock") or {}).get("heard"))
        if local_heard is not None and not (local_snap.get("clock") or {}).get("warming"):
            with self.lock:
                self._drift_ms = int(round((float(heard) - float(local_heard)) * 1000.0))

    def _emit_clock(self):
        player = self.player
        if player is None:
            return
        snap = player.snapshot()
        clock = snap.get("clock") or {}
        me = identity()
        uid = me.get("uid") or ""
        if not uid:
            return
        state = 2 if clock.get("locked") else (1 if snap.get("playing") else 0)
        with self.lock:
            self._seq = (self._seq + 1) & 0xFFFFFFFF
            seq = self._seq
        pkt = crypt_wire.encode_clock(
            uid, seq,
            heard=clock.get("heard"),
            mono=time.monotonic(),
            path=(float(clock.get("latency_ms") or 0) / 1000.0),
            state=state,
            playing=bool(snap.get("playing")),
            unison=True,
        )
        PEERS.send_dgram(pkt)

    def _loop(self):
        while self._alive:
            with self.lock:
                url = self._follow_url
                rooms = list(self._rooms)
                player = self.player
                clock_age = time.time() - self._clock_at if self._clock_at else 999
            if not url:
                if rooms and player is not None and player.snapshot().get("playing"):
                    try:
                        self._emit_clock()
                    except Exception:
                        traceback.print_exc()
                    time.sleep(0.05)
                    continue
                time.sleep(0.35)
                continue
            if clock_age <= 0.25:
                time.sleep(0.05)
                continue
            # CLOCK quiet is not pause. HTTP confirm; unreachable holds.
            self._fallback_http_clock()
            time.sleep(0.35)

    def _fallback_http_clock(self):
        """GET /api/clock when UDP CLOCK is quiet. Silence is not pause; miss holds."""
        with self.lock:
            url = self._follow_url
            on = self._on
        if not url:
            return
        try:
            data = self.get(url + "/api/clock", timeout=2)
        except Exception:
            return
        self._apply_http_clock(data)

    def _apply_http_clock(self, data):
        player_snap = (data or {}).get("player")
        if not isinstance(player_snap, dict) or "playing" not in player_snap:
            return
        clock = player_snap.get("clock") or {}
        heard = clock.get("heard")
        playing = bool(player_snap.get("playing"))
        paused = bool(player_snap.get("paused"))
        player = self.player
        local = player.snapshot() if player is not None else {}
        with self.lock:
            following = bool(self._on and self._follow_url)
        if playing and heard is not None and local.get("playing"):
            player.follow_heard(heard)
            after = player.snapshot()
            local_heard = ((after.get("clock") or {}).get("heard"))
            if local_heard is not None and not (after.get("clock") or {}).get("warming"):
                with self.lock:
                    self._drift_ms = int(round((float(heard) - float(local_heard)) * 1000.0))
            return
        if playing:
            return
        with self.lock:
            self._drift_ms = None
        if not following or player is None or not local.get("playing"):
            return
        if paused:
            player.pause()
            return
        player.stop()
        self.unfollow()


def urlparse_host(url):
    try:
        from urllib.parse import urlparse
    except ImportError:
        from urlparse import urlparse
    return (urlparse(url or "").hostname or "")


UNISON = Unison()
