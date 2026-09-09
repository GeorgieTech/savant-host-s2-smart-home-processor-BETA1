#!/usr/bin/env python3
"""Unison TOSLINK: optional synced play across linked CRYPT hosts.

Each chassis copies the track, then plays it on its own optical jack.
The follower steers its Time Clock toward the conductor's heard clock.
No NAS, no ffmpeg HTTP. Python 3.8 stdlib only.
"""
from __future__ import print_function

import json
import os
import threading
import time
import traceback

from peers import PEERS, _clean_url, _http_json, _http_post, identity, stamp

SYNC_FILE = os.environ.get("CRYPT_SYNC", "/data/crypt/sync.json")


def _load_on(path):
    try:
        with open(path, "r") as fh:
            raw = json.load(fh)
        if isinstance(raw, dict):
            return bool(raw.get("on"))
    except (OSError, ValueError, TypeError):
        pass
    return False


def _save_on(path, on):
    folder = os.path.dirname(path)
    if folder:
        try:
            os.makedirs(folder, exist_ok=True)
        except OSError:
            return
    tmp = path + ".tmp"
    try:
        with open(tmp, "w") as fh:
            json.dump({"on": bool(on)}, fh)
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
        self._on = _load_on(self.path)
        self._follow_url = ""
        self._follow_uid = ""
        self._drift_ms = None
        self._thread = None
        self._alive = True
        t = threading.Thread(target=self._loop, name="crypt-unison", daemon=True)
        self._thread = t
        t.start()

    def snapshot(self):
        linked = len((PEERS.config().get("shelves") or []))
        with self.lock:
            following = bool(self._follow_url)
            return {
                "on": bool(self._on),
                "linked": linked,
                "following": following,
                "conductor": self._follow_uid,
                "conductor_stamp": stamp(self._follow_uid) if self._follow_uid else "",
                "drift_ms": self._drift_ms,
            }

    def set_on(self, on):
        on = bool(on)
        with self.lock:
            self._on = on
            if not on:
                self._follow_url = ""
                self._follow_uid = ""
                self._drift_ms = None
        _save_on(self.path, on)
        return self.snapshot()

    def follow(self, url, uid=""):
        url = _clean_url(url)
        with self.lock:
            if not self._on:
                return
            self._follow_url = url
            self._follow_uid = str(uid or "")

    def unfollow(self):
        with self.lock:
            self._follow_url = ""
            self._follow_uid = ""
            self._drift_ms = None

    def _targets(self):
        me = identity()
        mine = set(filter(None, [me.get("ip"), me.get("url"), urlparse_host(me.get("url"))]))
        out = []
        for shelf in PEERS.config().get("shelves") or []:
            url = shelf.get("url") or ""
            host = urlparse_host(url)
            if not url or host in mine or url in mine:
                continue
            out.append(url)
        return out

    def broadcast(self, path, body):
        if not self._on:
            return
        payload = dict(body or {})
        payload["follow"] = True
        me = identity()
        payload["conductor"] = me.get("url") or (("http://%s" % me["ip"]) if me.get("ip") else "")
        payload["conductor_uid"] = me.get("uid") or ""
        urls = list(self._targets())
        if not urls:
            return

        def run():
            for url in urls:
                try:
                    self.post(url + path, payload, timeout=4)
                except Exception:
                    pass

        threading.Thread(target=run, daemon=True, name="unison-fan").start()

    def _loop(self):
        while self._alive:
            with self.lock:
                url = self._follow_url
                on = self._on
                player = self.player
            if not on or not url or player is None:
                time.sleep(0.35)
                continue
            try:
                data = self.get(url + "/api/clock", timeout=2)
                player_snap = (data or {}).get("player") or {}
                clock = player_snap.get("clock") or {}
                heard = clock.get("heard")
                playing = bool(player_snap.get("playing"))
                local = player.snapshot()
                if playing and heard is not None and local.get("playing"):
                    player.follow_heard(heard)
                    local_heard = ((player.snapshot().get("clock") or {}).get("heard"))
                    if local_heard is not None:
                        with self.lock:
                            self._drift_ms = int(round((float(heard) - float(local_heard)) * 1000.0))
                elif not playing:
                    with self.lock:
                        self._drift_ms = None
            except Exception:
                pass
            time.sleep(0.35)


def urlparse_host(url):
    try:
        from urllib.parse import urlparse
    except ImportError:
        from urlparse import urlparse
    return (urlparse(url or "").hostname or "")


UNISON = Unison()
