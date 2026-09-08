#!/usr/bin/env python3
"""Precompute Rekordbox-style 3-band waveforms (low / mid / high)."""
from __future__ import print_function

import hashlib
import json
import os
import struct
import subprocess
import threading
import time

from player import MUSIC_DIR

WAVE_DIR = os.environ.get("CRYPT_WAVES", "/data/crypt/waves")
RATE = 40
MAX_FRAMES = 12000
AUDIO_EXT = (".mp3", ".flac", ".opus", ".ogg", ".wav", ".m4a", ".aac")

def _lower_nice():
    try:
        os.nice(8)
    except Exception:
        pass


_FILTER = (
    "[0:a]aformat=channel_layouts=mono:sample_fmts=flt,asplit=3[l0][m0][h0];"
    "[l0]lowpass=f=250,lowpass=f=250,aresample=40,aformat=sample_fmts=flt:channel_layouts=mono[l];"
    "[m0]highpass=f=250,lowpass=f=4000,aresample=40,aformat=sample_fmts=flt:channel_layouts=mono[m];"
    "[h0]highpass=f=4000,highpass=f=4000,aresample=40,aformat=sample_fmts=flt:channel_layouts=mono[h];"
    "[l][m][h]join=inputs=3:channel_layout=3.0[a]"
)


def _full_path(rel):
    rel = (rel or "").replace("\\", "/").lstrip("/")
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


def _stat(full):
    try:
        st = os.stat(full)
        return int(st.st_size), int(st.st_mtime)
    except OSError:
        return 0, 0


def _cache_path(rel, size, mtime):
    key = "%s|%s|%s" % (rel, size, mtime)
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:20]
    return os.path.join(WAVE_DIR, digest + ".json")


def _scale_band(vals):
    if not vals:
        return []
    ordered = sorted(vals)
    idx = int(len(ordered) * 0.97)
    if idx >= len(ordered):
        idx = len(ordered) - 1
    peak = ordered[idx] or 0.000001
    out = []
    for v in vals:
        x = v / peak
        if x > 1.0:
            x = 1.0
        if x < 0.0:
            x = 0.0
        out.append(int(round((x ** 0.62) * 255.0)))
    return out


def _analyze(full):
    cmd = [
        "ffmpeg",
        "-nostdin",
        "-hide_banner",
        "-nostats",
        "-loglevel",
        "error",
        "-threads",
        "1",
        "-i",
        full,
        "-filter_complex",
        _FILTER,
        "-map",
        "[a]",
        "-f",
        "f32le",
        "pipe:1",
    ]
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        preexec_fn=_lower_nice,
    )
    try:
        raw, _err = proc.communicate(timeout=90)
    except subprocess.TimeoutExpired:
        try:
            proc.kill()
        except Exception:
            pass
        try:
            proc.communicate()
        except Exception:
            pass
        return None
    if not raw:
        return None
    frame = 12
    n = len(raw) // frame
    if n < 8:
        return None
    if n > MAX_FRAMES:
        step = int((n + MAX_FRAMES - 1) / MAX_FRAMES)
    else:
        step = 1
    lows, mids, highs = [], [], []
    i = 0
    while i < n:
        off = i * frame
        l, m, h = struct.unpack_from("<fff", raw, off)
        lows.append(abs(l))
        mids.append(abs(m))
        highs.append(abs(h))
        i += step
    return {
        "v": 1,
        "rate": RATE / float(step),
        "n": len(lows),
        "l": _scale_band(lows),
        "m": _scale_band(mids),
        "h": _scale_band(highs),
    }


class WaveIndex(object):
    def __init__(self):
        self.lock = threading.Lock()
        self.mem = {}
        self.busy = set()
        self.queue = []
        self.error = {}
        t = threading.Thread(target=self._loop, name="wave-scan", daemon=True)
        t.start()

    def get(self, rel):
        rel = (rel or "").replace("\\", "/").lstrip("/")
        full = _full_path(rel)
        if not full:
            return {"ok": False, "error": "not found"}
        size, mtime = _stat(full)
        path = _cache_path(rel, size, mtime)
        with self.lock:
            cached = self.mem.get(path)
        if cached:
            data = dict(cached)
            data["ok"] = True
            data["name"] = rel
            data["analyzing"] = False
            return data
        try:
            with open(path, "r") as fh:
                data = json.load(fh)
            if isinstance(data, dict) and data.get("l") and data.get("m") and data.get("h"):
                with self.lock:
                    self.mem[path] = data
                out = dict(data)
                out["ok"] = True
                out["name"] = rel
                out["analyzing"] = False
                return out
        except (OSError, ValueError, TypeError):
            pass
        self.ensure(rel, front=True)
        with self.lock:
            err = self.error.get(rel)
            analyzing = rel in self.busy or rel in self.queue
        if err:
            return {"ok": False, "name": rel, "analyzing": False, "error": err}
        return {"ok": False, "name": rel, "analyzing": True}

    def ensure(self, rel, front=False):
        rel = (rel or "").replace("\\", "/").lstrip("/")
        if not rel or not _full_path(rel):
            return
        with self.lock:
            if rel in self.busy or rel in self.queue:
                if front and rel in self.queue:
                    self.queue.remove(rel)
                    self.queue.insert(0, rel)
                return
            if front:
                self.queue.insert(0, rel)
            else:
                self.queue.append(rel)

    def _loop(self):
        while True:
            with self.lock:
                rel = self.queue.pop(0) if self.queue else None
                if rel:
                    self.busy.add(rel)
            if not rel:
                time.sleep(0.4)
                continue
            try:
                self._build(rel)
            except Exception as exc:
                with self.lock:
                    self.error[rel] = str(exc)[:160]
            finally:
                with self.lock:
                    self.busy.discard(rel)

    def _build(self, rel):
        full = _full_path(rel)
        if not full:
            with self.lock:
                self.error[rel] = "not found"
            return
        size, mtime = _stat(full)
        path = _cache_path(rel, size, mtime)
        if os.path.isfile(path):
            try:
                with open(path, "r") as fh:
                    data = json.load(fh)
                if isinstance(data, dict) and data.get("n"):
                    with self.lock:
                        self.mem[path] = data
                        self.error.pop(rel, None)
                    return
            except (OSError, ValueError):
                pass
        data = _analyze(full)
        if not data:
            with self.lock:
                self.error[rel] = "analyze failed"
            return
        data["name"] = rel
        try:
            os.makedirs(WAVE_DIR, exist_ok=True)
            tmp = path + ".tmp"
            with open(tmp, "w") as fh:
                json.dump(data, fh, separators=(",", ":"))
            os.replace(tmp, path)
        except OSError:
            pass
        with self.lock:
            self.mem[path] = data
            self.error.pop(rel, None)


WAVES = WaveIndex()
