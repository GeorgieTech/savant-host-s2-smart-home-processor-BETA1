#!/usr/bin/env python3
"""CRYPT web UI for the SHR-S2. Python 3.8 stdlib only. Binds :80."""
from __future__ import print_function

import cgi
import json
import os
import re
import shutil
import socket
import sys
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

from player import HostPlayer, MUSIC_DIR, EQ_BANDS, clamp_eq
from library import CATALOG, PLAYLISTS, GENRES
from wave import WAVES

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = int(os.environ.get("WEBUI_PORT", "80"))
EQ_FILE = os.environ.get("EQ_FILE", "/data/crypt/eq.json")
EQ_PRESETS = (
    {
        "id": "flat",
        "name": "Flat",
        "blurb": "No boost or cut. A level starting point.",
        "gains": [0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    },
    {
        "id": "harman",
        "name": "Harman",
        "blurb": "Harman loudspeaker target (Olive 2013 in-room preference): bass shelf below ~100 Hz, then a gentle downward tilt through the treble. 10-band fit, 1 kHz at 0 dB.",
        "gains": [6.5, 6.0, 4.0, 1.5, 0.5, 0, -0.5, -2.5, -4.0, -6.0],
    },
    {
        "id": "bk1974",
        "name": "B&K 1974",
        "blurb": "Brüel & Kjær 1974 hi-fi room curve: fairly level bass into the lower mids, then a slow roll-off toward the top. 10-band fit, 1 kHz at 0 dB.",
        "gains": [2.0, 2.0, 1.8, 1.0, 0.5, 0, -0.8, -1.6, -2.5, -4.0],
    },
    {
        "id": "hifi",
        "name": "Optimum HiFi",
        "blurb": "Classic “optimum hi-fi” house curve: mild bass lift, a presence dip around 2–4 kHz, and easier treble. 10-band fit, 1 kHz at 0 dB.",
        "gains": [3.0, 2.5, 1.5, 0.5, 0.2, 0, -1.5, -2.0, -1.0, -2.5],
    },
    {
        "id": "nad",
        "name": "NAD / Bluesound",
        "blurb": "NAD / Bluesound house target: punch around 30–60 Hz, less deep rumble than a full bass shelf, warmer and steeper highs than Harman. 10-band fit, 1 kHz at 0 dB.",
        "gains": [5.5, 4.0, 2.5, 1.0, 0.3, 0, -1.2, -3.0, -5.0, -7.5],
    },
)


def _eq_bands():
    return [
        {"type": kind, "freq": freq, "label": label}
        for kind, freq, label in EQ_BANDS
    ]


def _match_preset(gains):
    gains = clamp_eq(gains)
    for preset in EQ_PRESETS:
        ok = True
        for i in range(len(EQ_BANDS)):
            if abs(gains[i] - float(preset["gains"][i])) > 0.35:
                ok = False
                break
        if ok:
            return preset["id"]
    return ""


def _preset_gains(pid):
    pid = str(pid or "").strip().lower()
    for preset in EQ_PRESETS:
        if preset["id"] == pid:
            return clamp_eq(preset["gains"])
    return None


def _load_eq():
    try:
        with open(EQ_FILE, "r") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            return clamp_eq(data.get("eq"))
        return clamp_eq(data)
    except (OSError, ValueError, TypeError):
        return clamp_eq(None)


def _save_eq(gains):
    gains = clamp_eq(gains)
    folder = os.path.dirname(EQ_FILE)
    try:
        os.makedirs(folder, exist_ok=True)
        tmp = EQ_FILE + ".tmp"
        with open(tmp, "w") as fh:
            json.dump({"eq": gains}, fh)
        os.replace(tmp, EQ_FILE)
    except OSError:
        pass
    return gains
MAX_UPLOAD = int(os.environ.get("MAX_UPLOAD", str(400 * 1024 * 1024)))
AUDIO_EXT = (".mp3", ".flac", ".opus", ".ogg", ".wav", ".m4a", ".aac")
SAFE_NAME = re.compile(r"[^A-Za-z0-9._+\- ()\[\]]+")
MIME = {
    ".mp3": "audio/mpeg",
    ".flac": "audio/flac",
    ".opus": "audio/ogg",
    ".ogg": "audio/ogg",
    ".wav": "audio/wav",
    ".m4a": "audio/mp4",
    ".aac": "audio/aac",
}

PAGES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/library": ("library.html", "text/html; charset=utf-8"),
    "/library.html": ("library.html", "text/html; charset=utf-8"),
    "/eq": ("eq.html", "text/html; charset=utf-8"),
    "/eq.html": ("eq.html", "text/html; charset=utf-8"),
    "/crypt.css": ("crypt.css", "text/css; charset=utf-8"),
    "/manifest.webmanifest": ("manifest.webmanifest", "application/manifest+json"),
    "/favicon.svg": ("favicon.svg", "image/svg+xml"),
    "/icon.png": ("icon.png", "image/png"),
    "/apple-touch-icon.png": ("apple-touch-icon.png", "image/png"),
}


def _qparam(qs, key):
    return (parse_qs(qs, keep_blank_values=True).get(key) or [""])[0]


def _media_path(name):
    rel = (name or "").replace("\\", "/").lstrip("/")
    if not rel or ".." in rel.split("/"):
        return None
    base = os.path.realpath(MUSIC_DIR)
    full = os.path.realpath(os.path.join(base, rel))
    if full == base or not full.startswith(base + os.sep):
        return None
    if not os.path.isfile(full):
        return None
    if os.path.splitext(full)[1].lower() not in AUDIO_EXT:
        return None
    return full


def _send_media(handler, full, head=False):
    try:
        size = os.path.getsize(full)
    except OSError:
        handler._send(404, {"ok": False, "error": "not found"})
        return
    ext = os.path.splitext(full)[1].lower()
    mime = MIME.get(ext, "application/octet-stream")
    start = 0
    end = size - 1
    code = 200
    rng = handler.headers.get("Range") or ""
    if rng.startswith("bytes=") and size > 0:
        spec = rng.split("=", 1)[1].split("-")
        try:
            if spec[0]:
                start = int(spec[0])
            if len(spec) > 1 and spec[1]:
                end = int(spec[1])
        except ValueError:
            handler._send(400, {"ok": False, "error": "bad range"})
            return
        end = min(end, size - 1)
        if start < 0 or start > end:
            handler.send_response(416)
            handler.send_header("Content-Range", "bytes */%s" % size)
            handler.send_header("Content-Length", "0")
            handler.end_headers()
            return
        code = 206
    length = end - start + 1
    handler.send_response(code)
    handler.send_header("Content-Type", mime)
    handler.send_header("Content-Length", str(length))
    handler.send_header("Accept-Ranges", "bytes")
    handler.send_header("Cache-Control", "private, max-age=120")
    if code == 206:
        handler.send_header("Content-Range", "bytes %s-%s/%s" % (start, end, size))
    handler.end_headers()
    if head:
        return
    try:
        with open(full, "rb") as fh:
            fh.seek(start)
            left = length
            while left > 0:
                chunk = fh.read(min(65536, left))
                if not chunk:
                    break
                handler.wfile.write(chunk)
                left -= len(chunk)
    except (BrokenPipeError, ConnectionResetError, OSError):
        return


def _safe_filename(name):
    name = os.path.basename((name or "track").replace("\\", "/"))
    name = SAFE_NAME.sub("_", name).strip(" ._")
    if not name:
        name = "track"
    return name[:180]


def _library():
    return CATALOG.tracks()


def _library_payload():
    tracks = _library()
    return {
        "ok": True,
        "tracks": tracks,
        "disk": _disk(),
        "scanning": bool(CATALOG.scanning),
        "playlists": PLAYLISTS.list([t["name"] for t in tracks]),
        "genres": list(GENRES),
    }


def _disk():
    try:
        usage = shutil.disk_usage(MUSIC_DIR if os.path.isdir(MUSIC_DIR) else "/data")
        return {
            "total": usage.total,
            "used": usage.used,
            "free": usage.free,
        }
    except OSError:
        return {"total": 0, "used": 0, "free": 0}


def _json_body(handler):
    n = int(handler.headers.get("Content-Length") or 0)
    if n <= 0:
        return {}
    raw = handler.rfile.read(n)
    try:
        return json.loads(raw.decode("utf-8"))
    except Exception:
        return {}


def _playlist_action(body):
    action = str(body.get("action") or "").strip().lower()
    pid = str(body.get("id") or "").strip()
    names = CATALOG.names()
    if action == "create":
        pl = PLAYLISTS.create(body.get("name"))
        return {"ok": True, "playlist": pl, "playlists": PLAYLISTS.list(names)}
    if action == "rename":
        pl = PLAYLISTS.rename(pid, body.get("name"))
        return {"ok": True, "playlist": pl, "playlists": PLAYLISTS.list(names)}
    if action == "delete":
        PLAYLISTS.delete(pid)
        return {"ok": True, "playlists": PLAYLISTS.list(names)}
    if action == "add":
        name = (body.get("name") or "").strip()
        if name not in set(names):
            raise ValueError("track not in library")
        pl = PLAYLISTS.add(pid, name)
        return {"ok": True, "playlist": pl, "playlists": PLAYLISTS.list(names)}
    if action == "remove":
        pl = PLAYLISTS.remove_track(pid, body.get("name"))
        return {"ok": True, "playlist": pl, "playlists": PLAYLISTS.list(names)}
    raise ValueError("need action create/rename/delete/add/remove")


class CryptApp(object):
    def __init__(self):
        os.makedirs(MUSIC_DIR, exist_ok=True)
        self.lock = threading.Lock()
        self.index = -1
        self.tracks = []
        self.order = []
        self.player = HostPlayer(on_end=self._on_end)
        self.player.set_eq(_load_eq())
        self.refresh()

    def refresh(self):
        with self.lock:
            self.tracks = _library()
            names = [t["name"] for t in self.tracks]
            name_set = set(names)
            self.order = [n for n in self.order if n in name_set]
            if not self.order:
                self.order = list(names)
            cur = self.player.snapshot().get("name") or ""
            if cur in self.order:
                self.index = self.order.index(cur)
            elif self.index >= len(self.order):
                self.index = len(self.order) - 1 if self.order else -1

    def _upcoming(self, order, tracks, idx, limit=5):
        by_name = dict((t["name"], t) for t in tracks)
        n = len(order)
        if n == 0:
            return [], 0
        if idx < 0 or idx >= n:
            items = []
            for name in order[:limit]:
                t = by_name.get(name) or {"name": name, "size": 0}
                items.append({"name": t["name"], "size": t.get("size") or 0, "title": t.get("title") or ""})
            return items, n
        if n == 1:
            return [], 0
        items = []
        for i in range(1, n):
            name = order[(idx + i) % n]
            t = by_name.get(name) or {"name": name, "size": 0}
            items.append({"name": t["name"], "size": t.get("size") or 0, "title": t.get("title") or ""})
            if len(items) >= limit:
                break
        return items, n - 1

    def status(self):
        self.refresh()
        snap = self.player.snapshot()
        with self.lock:
            tracks = list(self.tracks)
            order = list(self.order)
            idx = self.index
        queue, queue_total = self._upcoming(order, tracks, idx, 5)
        eq = clamp_eq(snap.get("eq"))
        return {
            "host": socket.gethostname(),
            "model": "SHR-S2-00",
            "player": snap,
            "volume": self.player.volume(),
            "index": idx,
            "count": len(tracks),
            "queue": queue,
            "queue_total": queue_total,
            "eq": eq,
            "eq_preset": _match_preset(eq),
            "disk": _disk(),
        }

    def clock(self):
        snap = self.player.snapshot()
        return {
            "ok": True,
            "player": {
                "playing": snap.get("playing"),
                "paused": snap.get("paused"),
                "name": snap.get("name") or "",
                "position": snap.get("position"),
                "playback": snap.get("playback"),
                "duration": snap.get("duration"),
                "clock": snap.get("clock") or {},
            },
            "volume": self.player.volume(),
        }

    def eq_state(self):
        eq = clamp_eq(self.player.snapshot().get("eq"))
        return {
            "ok": True,
            "eq": eq,
            "preset": _match_preset(eq),
            "bands": _eq_bands(),
            "presets": [dict(p) for p in EQ_PRESETS],
        }

    def set_eq(self, gains=None, preset=None):
        if preset:
            found = _preset_gains(preset)
            if found is None:
                raise ValueError("unknown preset")
            gains = found
        elif gains is None:
            raise ValueError("need eq or preset")
        eq = _save_eq(gains)
        self.player.set_eq(eq)
        return self.eq_state()

    def play_name(self, name, start=0.0, order=None):
        self.refresh()
        with self.lock:
            names = [t["name"] for t in self.tracks]
            name_set = set(names)
            if order:
                cleaned = []
                seen = set()
                for item in order:
                    item = str(item or "").strip()
                    if item in name_set and item not in seen:
                        cleaned.append(item)
                        seen.add(item)
                    if len(cleaned) >= 300:
                        break
                if cleaned:
                    self.order = cleaned
            if not self.order:
                self.order = list(names)
            if name not in name_set:
                return False
            if name not in self.order:
                self.order = list(names)
            if name not in self.order:
                return False
            self.index = self.order.index(name)
            nxt = self.order[self.index + 1] if self.index + 1 < len(self.order) else ""
        ok = self.player.play(name, start=start)
        if ok:
            WAVES.ensure(name, front=True)
            if nxt:
                WAVES.ensure(nxt)
        return ok

    def play_playlist(self, pid):
        pl = PLAYLISTS.get(pid)
        if not pl or not pl.get("tracks"):
            return False
        return self.play_name(pl["tracks"][0], order=pl["tracks"])

    def _start_name(self, name, start=0.0, nxt=""):
        ok = self.player.play(name, start=start)
        if ok:
            WAVES.ensure(name, front=True)
            if nxt:
                WAVES.ensure(nxt)
        return ok

    def play_index(self, idx):
        self.refresh()
        with self.lock:
            if not self.order:
                return False
            idx = idx % len(self.order)
            self.index = idx
            name = self.order[idx]
            nxt = self.order[self.index + 1] if self.index + 1 < len(self.order) else ""
        return self._start_name(name, 0.0, nxt)

    def next_track(self):
        self.refresh()
        with self.lock:
            if not self.order:
                return False
            self.index = 0 if self.index < 0 else (self.index + 1) % len(self.order)
            name = self.order[self.index]
            nxt = self.order[self.index + 1] if self.index + 1 < len(self.order) else ""
        return self._start_name(name, 0.0, nxt)

    def prev_track(self):
        self.refresh()
        with self.lock:
            if not self.order:
                return False
            self.index = 0 if self.index < 0 else (self.index - 1) % len(self.order)
            name = self.order[self.index]
            nxt = self.order[self.index + 1] if self.index + 1 < len(self.order) else ""
        return self._start_name(name, 0.0, nxt)

    def _on_end(self):
        self.next_track()

    def delete_name(self, name, refresh=True):
        base = os.path.realpath(MUSIC_DIR)
        full = os.path.realpath(os.path.join(base, name.replace("\\", "/").lstrip("/")))
        if full != base and not full.startswith(base + os.sep):
            return False
        if not os.path.isfile(full):
            return False
        snap = self.player.snapshot()
        rel = name.replace("\\", "/").lstrip("/")
        if snap.get("name") == rel:
            self.player.stop()
        WAVES.drop_name(rel)
        try:
            os.remove(full)
        except OSError:
            return False
        CATALOG.drop_name(rel)
        PLAYLISTS.remove_everywhere(rel)
        if refresh:
            self.refresh()
        return True

    def delete_names(self, names):
        if not isinstance(names, list):
            raise ValueError("delete must be a list of names")
        cleaned = []
        seen = set()
        for item in names:
            name = str(item or "").replace("\\", "/").lstrip("/")
            if not name or name in seen:
                continue
            seen.add(name)
            cleaned.append(name)
            if len(cleaned) >= 200:
                break
        deleted = 0
        for name in cleaned:
            if self.delete_name(name, refresh=False):
                deleted += 1
        if deleted:
            self.refresh()
        return deleted

    def manage_library(self, body):
        deleted = 0
        edited = 0
        if body.get("delete"):
            deleted = self.delete_names(body.get("delete"))
        edits = body.get("edits")
        if edits:
            edited = CATALOG.apply_edits(edits)
            self.refresh()
        payload = _library_payload()
        payload["deleted"] = deleted
        payload["edited"] = edited
        return payload


APP = CryptApp()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        if isinstance(body, dict) or isinstance(body, list):
            raw = json.dumps(body).encode("utf-8")
        elif isinstance(body, str):
            raw = body.encode("utf-8")
        else:
            raw = body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        raw_path = self.path.split("?", 1)[0]
        qs = self.path.split("?", 1)[1] if "?" in self.path else ""
        try:
            if raw_path in PAGES:
                name, ctype = PAGES[raw_path]
                path = os.path.realpath(os.path.join(HERE, name))
                if not path.startswith(os.path.realpath(HERE) + os.sep):
                    self._send(404, {"error": "not found"})
                    return
                with open(path, "rb") as fh:
                    data = fh.read()
                self._send(200, data, ctype)
                return
            if raw_path == "/api/status":
                self._send(200, APP.status())
                return
            if raw_path == "/api/clock":
                self._send(200, APP.clock())
                return
            if raw_path == "/api/library":
                APP.refresh()
                self._send(200, _library_payload())
                return
            if raw_path == "/api/playlists":
                tracks = _library()
                self._send(200, {"playlists": PLAYLISTS.list([t["name"] for t in tracks])})
                return
            if raw_path == "/api/eq":
                self._send(200, APP.eq_state())
                return
            if raw_path == "/api/wave":
                name = _qparam(qs, "name")
                data = WAVES.get(name)
                code = 200
                if data.get("analyzing"):
                    code = 202
                elif not data.get("ok"):
                    code = 404 if data.get("error") == "not found" else 200
                self._send(code, data)
                return
            if raw_path == "/api/media":
                full = _media_path(_qparam(qs, "name"))
                if not full:
                    self._send(404, {"ok": False, "error": "not found"})
                    return
                _send_media(self, full, head=False)
                return
            self._send(404, {"error": "not found"})
        except Exception:
            traceback.print_exc()
            self._send(500, {"error": "server"})

    def do_HEAD(self):
        raw_path = self.path.split("?", 1)[0]
        qs = self.path.split("?", 1)[1] if "?" in self.path else ""
        try:
            if raw_path == "/api/media":
                full = _media_path(_qparam(qs, "name"))
                if not full:
                    self._send(404, {"ok": False, "error": "not found"})
                    return
                _send_media(self, full, head=True)
                return
            if raw_path in PAGES:
                name, ctype = PAGES[raw_path]
                path = os.path.realpath(os.path.join(HERE, name))
                if not path.startswith(os.path.realpath(HERE) + os.sep):
                    self.send_response(404)
                    self.end_headers()
                    return
                size = os.path.getsize(path)
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(size))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                return
            self.send_response(404)
            self.end_headers()
        except Exception:
            traceback.print_exc()
            self.send_response(500)
            self.end_headers()

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        try:
            if path == "/api/upload":
                self._upload()
                return
            body = _json_body(self)
            if path == "/api/play":
                if body.get("playlist"):
                    ok = APP.play_playlist(body.get("playlist"))
                    self._send(200 if ok else 400, {"ok": ok, "error": APP.player.error})
                    return
                name = (body.get("name") or "").strip()
                order = body.get("order") if isinstance(body.get("order"), list) else None
                ok = APP.play_name(name, start=body.get("start") or 0, order=order)
                self._send(200 if ok else 400, {"ok": ok, "error": APP.player.error})
                return
            if path == "/api/playlists":
                try:
                    payload = _playlist_action(body)
                except KeyError as exc:
                    self._send(404, {"ok": False, "error": str(exc)})
                    return
                except ValueError as exc:
                    self._send(400, {"ok": False, "error": str(exc)})
                    return
                self._send(200, payload)
                return
            if path == "/api/pause":
                ok = APP.player.pause()
                self._send(200 if ok else 400, {"ok": ok, "error": APP.player.error})
                return
            if path == "/api/resume":
                ok = APP.player.resume()
                self._send(200 if ok else 400, {"ok": ok, "error": APP.player.error})
                return
            if path == "/api/stop":
                self._send(200, {"ok": APP.player.stop()})
                return
            if path == "/api/next":
                ok = APP.next_track()
                self._send(200 if ok else 400, {"ok": ok, "error": APP.player.error})
                return
            if path == "/api/prev":
                ok = APP.prev_track()
                self._send(200 if ok else 400, {"ok": ok, "error": APP.player.error})
                return
            if path == "/api/seek":
                ok = APP.player.seek(body.get("seconds"))
                self._send(200 if ok else 400, {"ok": ok, "error": APP.player.error})
                return
            if path == "/api/volume":
                ok = APP.player.set_volume(body.get("n"))
                self._send(200 if ok else 400, {"ok": ok})
                return
            if path == "/api/eq":
                try:
                    st = APP.set_eq(gains=body.get("eq"), preset=body.get("preset"))
                except ValueError as exc:
                    self._send(400, {"ok": False, "error": str(exc)})
                    return
                self._send(200, st)
                return
            if path == "/api/delete":
                name = (body.get("name") or "").strip()
                refresh = True if body.get("refresh") is None else bool(body.get("refresh"))
                ok = APP.delete_name(name, refresh=refresh)
                self._send(200 if ok else 400, {"ok": ok, "name": name})
                return
            if path == "/api/library/manage":
                try:
                    payload = APP.manage_library(body)
                except ValueError as exc:
                    self._send(400, {"ok": False, "error": str(exc)})
                    return
                self._send(200, payload)
                return
            self._send(404, {"error": "not found"})
        except Exception:
            traceback.print_exc()
            self._send(500, {"error": "server"})

    def _upload(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            self._send(400, {"ok": False, "error": "empty"})
            return
        if length > MAX_UPLOAD + 4096:
            self._send(413, {"ok": False, "error": "too large"})
            return
        env = {
            "REQUEST_METHOD": "POST",
            "CONTENT_TYPE": self.headers.get("Content-Type", ""),
            "CONTENT_LENGTH": str(length),
        }
        form = cgi.FieldStorage(fp=self.rfile, headers=self.headers, environ=env)
        item = form["file"] if "file" in form else None
        if item is None or not getattr(item, "filename", None):
            self._send(400, {"ok": False, "error": "no file"})
            return
        name = _safe_filename(item.filename)
        ext = os.path.splitext(name)[1].lower()
        if ext not in AUDIO_EXT:
            self._send(400, {"ok": False, "error": "unsupported type"})
            return
        dest = os.path.join(MUSIC_DIR, name)
        os.makedirs(MUSIC_DIR, exist_ok=True)
        # FieldStorage may already have a temp file; copy in chunks.
        src = item.file
        written = 0
        tmp = dest + ".part"
        try:
            with open(tmp, "wb") as out:
                while True:
                    chunk = src.read(1024 * 256)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > MAX_UPLOAD:
                        raise IOError("too large")
                    out.write(chunk)
            os.replace(tmp, dest)
            os.chmod(dest, 0o644)
        except Exception as exc:
            try:
                os.remove(tmp)
            except OSError:
                pass
            self._send(400, {"ok": False, "error": str(exc)})
            return
        APP.refresh()
        self._send(200, {"ok": True, "name": name, "size": written})


def main():
    os.makedirs(MUSIC_DIR, exist_ok=True)
    httpd = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print("CRYPT listening on :%s music=%s" % (PORT, MUSIC_DIR), flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    httpd.server_close()


if __name__ == "__main__":
    main()
