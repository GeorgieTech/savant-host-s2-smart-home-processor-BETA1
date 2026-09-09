#!/usr/bin/env python3
"""CRYPT host-to-host library shelf.

A viewer host lists another host's catalog over HTTP. Files stay on the
shelf. Play copies the track onto this box first (no NAS, no ffmpeg HTTP).
Python 3.8 stdlib only.
"""
from __future__ import print_function

import json
import os
import socket
import threading
import time

try:
    from urllib.parse import quote, urlparse
    from urllib.request import Request, urlopen
except ImportError:
    from urllib import quote
    from urlparse import urlparse
    from urllib2 import Request, urlopen

from player import MUSIC_DIR

PEERS_FILE = os.environ.get("CRYPT_PEERS", "/data/crypt/peers.json")
CLIENT = "CRYPT/1.1.8 (peer)"
BLOCKED = ("192.168.1.40", "192.168.1.178", "192.168.1.180")
AUDIO_EXT = (".mp3", ".flac", ".opus", ".ogg", ".wav", ".m4a", ".aac")
MAX_COPY = int(os.environ.get("MAX_UPLOAD", str(400 * 1024 * 1024)))


def _self_id():
    return os.environ.get("CRYPT_ID") or socket.gethostname() or "crypt"


def _blocked(host):
    host = (host or "").split("%")[0].strip().lower()
    if host in ("127.0.0.1", "localhost", "::1"):
        return True
    for bad in BLOCKED:
        if host == bad or host.endswith(bad):
            return True
    if host.startswith("192.168.1."):
        return False
    return True


def _clean_url(url):
    url = str(url or "").strip().rstrip("/")
    if not url:
        return ""
    if "://" not in url:
        url = "http://" + url
    parsed = urlparse(url)
    if parsed.scheme != "http":
        return ""
    host = parsed.hostname or ""
    if _blocked(host):
        return ""
    port = parsed.port or 80
    if port != 80:
        return "http://%s:%s" % (host, port)
    return "http://%s" % host


def load_config(path=None):
    path = path or PEERS_FILE
    data = {}
    try:
        with open(path, "r") as fh:
            raw = json.load(fh)
        if isinstance(raw, dict):
            data = raw
    except (OSError, ValueError, TypeError):
        data = {}
    shelves = []
    seen = set()
    extra = os.environ.get("CRYPT_SHELVES") or ""
    listed = list(data.get("shelves") or [])
    if extra:
        listed.extend([{"url": bit} for bit in extra.split(",") if bit.strip()])
    for item in listed:
        if isinstance(item, str):
            item = {"url": item}
        if not isinstance(item, dict):
            continue
        url = _clean_url(item.get("url"))
        if not url or url in seen:
            continue
        seen.add(url)
        sid = str(item.get("id") or urlparse(url).hostname or url)
        shelves.append({"id": sid, "url": url})
    return {
        "id": str(data.get("id") or _self_id()),
        "shelves": shelves,
    }


def _http_json(url, timeout=4):
    req = Request(url, headers={"User-Agent": CLIENT, "Accept": "application/json"})
    fh = urlopen(req, timeout=timeout)
    try:
        raw = fh.read(2 * 1024 * 1024)
    finally:
        fh.close()
    return json.loads(raw.decode("utf-8"))


def _safe_rel(name):
    rel = (name or "").replace("\\", "/").lstrip("/")
    if not rel or ".." in rel.split("/"):
        return ""
    ext = os.path.splitext(rel)[1].lower()
    if ext not in AUDIO_EXT:
        return ""
    return rel


class PeerIndex(object):
    def __init__(self, path=None, http=None):
        self.path = path or PEERS_FILE
        self.http = http or _http_json
        self.lock = threading.Lock()
        self._cfg = load_config(self.path)
        self._remote = {}
        self.error = ""

    def reload(self):
        self._cfg = load_config(self.path)
        return self._cfg

    def config(self):
        return dict(self._cfg)

    def snapshot(self):
        cfg = self.config()
        rows = []
        for shelf in cfg.get("shelves") or []:
            rows.append({"id": shelf["id"], "url": shelf["url"]})
        return {"id": cfg.get("id"), "shelves": rows}

    def fetch_shelf(self, shelf):
        url = shelf.get("url") or ""
        if not url:
            return [], "no url"
        now = time.time()
        hit = self._remote.get(url)
        if hit and now - hit[0] < 8:
            return hit[1], hit[2]
        try:
            data = self.http(url + "/api/library?local=1")
            err = ""
            tracks = []
            if not isinstance(data, dict) or not data.get("ok"):
                err = "bad library"
            else:
                tracks = data.get("tracks") or []
                if not isinstance(tracks, list):
                    tracks, err = [], "bad tracks"
        except Exception as exc:
            tracks, err = [], str(exc)
        self._remote[url] = (now, tracks, err)
        return tracks, err

    def url_for_owner(self, owner):
        owner = str(owner or "")
        if not owner:
            return ""
        cfg = self.config()
        if owner == cfg.get("id"):
            return ""
        for shelf in cfg.get("shelves") or []:
            host = urlparse(shelf.get("url") or "").hostname or ""
            if owner in (shelf.get("id"), shelf.get("url"), host):
                return shelf.get("url")
        return ""

    def merge(self, local_tracks):
        cfg = self.config()
        self_id = cfg.get("id") or _self_id()
        by = {}
        for t in local_tracks or []:
            name = (t or {}).get("name")
            if not name:
                continue
            row = dict(t)
            row["owner"] = self_id
            row["local"] = True
            row["available"] = True
            by[name] = row
        errors = []
        for shelf in cfg.get("shelves") or []:
            tracks, err = self.fetch_shelf(shelf)
            if err:
                errors.append("%s: %s" % (shelf.get("id"), err))
                continue
            for t in tracks:
                name = (t or {}).get("name")
                if not name:
                    continue
                owner = shelf.get("id") or shelf.get("url")
                if name in by:
                    by[name]["owner"] = owner
                    by[name]["local"] = True
                    by[name]["available"] = True
                    if not by[name].get("title") and t.get("title"):
                        by[name]["title"] = t.get("title")
                    if not by[name].get("artist") and t.get("artist"):
                        by[name]["artist"] = t.get("artist")
                    if not by[name].get("album") and t.get("album"):
                        by[name]["album"] = t.get("album")
                    continue
                row = dict(t)
                row["owner"] = owner
                row["local"] = False
                row["available"] = True
                by[name] = row
        self.error = "; ".join(errors)
        out = list(by.values())
        out.sort(key=lambda t: (
            str(t.get("artist") or "").lower(),
            str(t.get("album") or "").lower(),
            t.get("track") or 9999,
            str(t.get("title") or "").lower(),
            str(t.get("name") or "").lower(),
        ))
        return out

    def owner_url(self, name, owner=None):
        url = self.url_for_owner(owner)
        if url:
            return url
        cfg = self.config()
        for shelf in cfg.get("shelves") or []:
            tracks, err = self.fetch_shelf(shelf)
            if err:
                continue
            for t in tracks:
                if (t or {}).get("name") == name:
                    return shelf.get("url")
        return ""

    def ensure(self, name, owner=None):
        """Copy a remote track into MUSIC_DIR if it is not already here."""
        rel = _safe_rel(name)
        if not rel:
            return False
        dest = os.path.join(MUSIC_DIR, rel)
        if os.path.isfile(dest):
            return True
        url = self.owner_url(rel, owner=owner)
        if not url:
            return False
        folder = os.path.dirname(dest)
        if folder:
            os.makedirs(folder, exist_ok=True)
        media = url + "/api/media?name=" + quote(rel)
        tmp = dest + ".part"
        try:
            req = Request(media, headers={"User-Agent": CLIENT})
            fh = urlopen(req, timeout=30)
            try:
                written = 0
                with open(tmp, "wb") as out:
                    while True:
                        chunk = fh.read(256 * 1024)
                        if not chunk:
                            break
                        written += len(chunk)
                        if written > MAX_COPY:
                            raise IOError("too large")
                        out.write(chunk)
            finally:
                fh.close()
            if written <= 0:
                raise IOError("empty")
            os.replace(tmp, dest)
            os.chmod(dest, 0o644)
            return True
        except Exception:
            try:
                os.remove(tmp)
            except OSError:
                pass
            return False


PEERS = PeerIndex()
