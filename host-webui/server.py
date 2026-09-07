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

from player import HostPlayer, MUSIC_DIR

HERE = os.path.dirname(os.path.abspath(__file__))
INDEX = os.path.join(HERE, "index.html")
PORT = int(os.environ.get("WEBUI_PORT", "80"))
MAX_UPLOAD = int(os.environ.get("MAX_UPLOAD", str(400 * 1024 * 1024)))
AUDIO_EXT = (".mp3", ".flac", ".opus", ".ogg", ".wav", ".m4a", ".aac")
SAFE_NAME = re.compile(r"[^A-Za-z0-9._+\- ()\[\]]+")


def _safe_filename(name):
    name = os.path.basename((name or "track").replace("\\", "/"))
    name = SAFE_NAME.sub("_", name).strip(" ._")
    if not name:
        name = "track"
    return name[:180]


def _library():
    base = os.path.realpath(MUSIC_DIR)
    out = []
    if not os.path.isdir(base):
        return out
    for dirpath, _dirs, files in os.walk(base):
        for fn in files:
            if os.path.splitext(fn)[1].lower() not in AUDIO_EXT:
                continue
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, base).replace("\\", "/")
            try:
                size = os.path.getsize(full)
            except OSError:
                size = 0
            out.append({"name": rel, "size": size})
    out.sort(key=lambda x: x["name"].lower())
    return out


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


class CryptApp(object):
    def __init__(self):
        os.makedirs(MUSIC_DIR, exist_ok=True)
        self.lock = threading.Lock()
        self.index = -1
        self.tracks = []
        self.player = HostPlayer(on_end=self._on_end)
        self.refresh()

    def refresh(self):
        with self.lock:
            self.tracks = _library()
            names = [t["name"] for t in self.tracks]
            cur = self.player.snapshot().get("name") or ""
            if cur in names:
                self.index = names.index(cur)
            elif self.index >= len(self.tracks):
                self.index = len(self.tracks) - 1 if self.tracks else -1

    def status(self):
        self.refresh()
        snap = self.player.snapshot()
        with self.lock:
            tracks = list(self.tracks)
            idx = self.index
        return {
            "host": socket.gethostname(),
            "model": "SHR-S2-00",
            "player": snap,
            "volume": self.player.volume(),
            "index": idx,
            "count": len(tracks),
            "disk": _disk(),
        }

    def play_name(self, name, start=0.0):
        self.refresh()
        with self.lock:
            names = [t["name"] for t in self.tracks]
            if name not in names:
                return False
            self.index = names.index(name)
        return self.player.play(name, start=start)

    def play_index(self, idx):
        self.refresh()
        with self.lock:
            if not self.tracks:
                return False
            idx = idx % len(self.tracks)
            self.index = idx
            name = self.tracks[idx]["name"]
        return self.player.play(name, start=0.0)

    def next_track(self):
        self.refresh()
        with self.lock:
            if not self.tracks:
                return False
            self.index = 0 if self.index < 0 else (self.index + 1) % len(self.tracks)
            name = self.tracks[self.index]["name"]
        return self.player.play(name)

    def prev_track(self):
        self.refresh()
        with self.lock:
            if not self.tracks:
                return False
            self.index = 0 if self.index < 0 else (self.index - 1) % len(self.tracks)
            name = self.tracks[self.index]["name"]
        return self.player.play(name)

    def _on_end(self):
        self.next_track()

    def delete_name(self, name):
        base = os.path.realpath(MUSIC_DIR)
        full = os.path.realpath(os.path.join(base, name.replace("\\", "/").lstrip("/")))
        if full != base and not full.startswith(base + os.sep):
            return False
        if not os.path.isfile(full):
            return False
        snap = self.player.snapshot()
        if snap.get("name") == name.replace("\\", "/"):
            self.player.stop()
        try:
            os.remove(full)
        except OSError:
            return False
        self.refresh()
        return True


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
        path = self.path.split("?", 1)[0]
        try:
            if path in ("/", "/index.html"):
                with open(INDEX, "rb") as fh:
                    data = fh.read()
                self._send(200, data, "text/html; charset=utf-8")
                return
            if path == "/api/status":
                self._send(200, APP.status())
                return
            if path == "/api/library":
                APP.refresh()
                self._send(200, {"tracks": _library(), "disk": _disk()})
                return
            self._send(404, {"error": "not found"})
        except Exception:
            traceback.print_exc()
            self._send(500, {"error": "server"})

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        try:
            if path == "/api/upload":
                self._upload()
                return
            body = _json_body(self)
            if path == "/api/play":
                name = (body.get("name") or "").strip()
                ok = APP.play_name(name, start=body.get("start") or 0)
                self._send(200 if ok else 400, {"ok": ok, "error": APP.player.error})
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
            if path == "/api/delete":
                name = (body.get("name") or "").strip()
                ok = APP.delete_name(name)
                self._send(200 if ok else 400, {"ok": ok})
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
