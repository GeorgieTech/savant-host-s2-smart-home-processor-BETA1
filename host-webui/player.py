#!/usr/bin/env python3
"""TOSLINK playback on the SHR-S2: ffmpeg stereo WAV piped to paplay/Pulse."""
import json
import os
import shlex
import signal
import subprocess
import threading
import time

MUSIC_DIR = os.environ.get("MUSIC_DIR", "/data/music")
PULSE_SINK = os.environ.get("PULSE_SINK", "@DEFAULT_SINK@")
FFMPEG_LOG = os.environ.get("FFMPEG_LOG", "/tmp/crypt-ffmpeg.log")
CLOCK_FILE = os.environ.get("CLOCK_FILE", "/data/crypt/clock.json")
# DualLite is happier at 48 kHz; Pulse resamples onto the 96 kHz S/PDIF sink.
RATE = os.environ.get("CRYPT_RATE", "48000")
# paplay WAV-on-stdin prebuffers seconds; raw PCM + this latency is the pause window.
try:
    LATENCY_MS = str(max(40, min(250, int(os.environ.get("CRYPT_LATENCY_MS", "90")))))
except ValueError:
    LATENCY_MS = "90"
# imx-spdif ALSA buffer is ~200 ms; paplay's 90 ms request is only the stream target.
try:
    CLOCK_PAD_MS = max(0, min(400, int(os.environ.get("CRYPT_CLOCK_PAD_MS", "270"))))
except ValueError:
    CLOCK_PAD_MS = 270
EQ_Q = 1.1
EQ_BANDS = (
    ("lowshelf", 32, "32"),
    ("peaking", 64, "64"),
    ("peaking", 125, "125"),
    ("peaking", 250, "250"),
    ("peaking", 500, "500"),
    ("peaking", 1000, "1k"),
    ("peaking", 2000, "2k"),
    ("peaking", 4000, "4k"),
    ("peaking", 8000, "8k"),
    ("highshelf", 16000, "16k"),
)


def clamp_eq(values):
    out = [0.0] * len(EQ_BANDS)
    if not isinstance(values, (list, tuple)):
        return out
    for i in range(min(len(EQ_BANDS), len(values))):
        try:
            out[i] = max(-12.0, min(12.0, float(values[i])))
        except (TypeError, ValueError):
            out[i] = 0.0
    return out


def ffmpeg_eq_filter(gains):
    """Match BETA2: Q 1.1, lowshelf / peaking / highshelf on TOSLINK."""
    gains = clamp_eq(gains)
    parts = []
    for (kind, freq, _label), gain in zip(EQ_BANDS, gains):
        if abs(gain) < 0.05:
            continue
        if kind == "lowshelf":
            parts.append("lowshelf=f=%s:t=q:w=%s:g=%.2f" % (freq, EQ_Q, gain))
        elif kind == "highshelf":
            parts.append("highshelf=f=%s:t=q:w=%s:g=%.2f" % (freq, EQ_Q, gain))
        else:
            parts.append("equalizer=f=%s:t=q:w=%s:g=%.2f" % (freq, EQ_Q, gain))
    return ",".join(parts)


def _cmd(args):
    try:
        return subprocess.check_output(args, stderr=subprocess.DEVNULL, text=True).strip()
    except Exception:
        return ""


def _paplay_ms():
    try:
        return int(LATENCY_MS)
    except (TypeError, ValueError):
        return 90


def _usec_field(line, prefix):
    if not line.startswith(prefix):
        return None
    parts = line.split()
    for i, part in enumerate(parts):
        if part.isdigit() and i + 1 < len(parts) and parts[i + 1].startswith("usec"):
            try:
                return int(part)
            except ValueError:
                return None
    return None


def _read_crypt_latency():
    """Pulse stream latency for the CRYPT paplay client, in milliseconds."""
    text = _cmd(["pactl", "list", "sink-inputs"])
    if not text:
        return None
    name = ""
    buf_usec = None
    sink_usec = None
    found = None
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("Sink Input #"):
            if name == "CRYPT" and buf_usec is not None:
                found = (buf_usec, sink_usec or 0)
            name = ""
            buf_usec = None
            sink_usec = None
            continue
        if line.startswith("application.name"):
            _, _, val = line.partition("=")
            name = val.strip().strip('"')
            continue
        usec = _usec_field(line, "Buffer Latency:")
        if usec is not None:
            buf_usec = usec
            continue
        usec = _usec_field(line, "Sink Latency:")
        if usec is not None:
            sink_usec = usec
    if name == "CRYPT" and buf_usec is not None:
        found = (buf_usec, sink_usec or 0)
    if not found:
        return None
    buf_ms = max(0, found[0] / 1000.0)
    sink_ms = max(0, found[1] / 1000.0)
    total = buf_ms + sink_ms
    # paplay still priming or tearing down reports 0 buffer; ignore those.
    if buf_ms < 40 or sink_ms < 10 or total < 60 or total > 1200:
        return None
    return {"buffer_ms": buf_ms, "sink_ms": sink_ms, "latency_ms": total}


def _load_clock_file():
    try:
        with open(CLOCK_FILE, "r") as fh:
            data = json.load(fh)
        lat = float(data.get("latency_ms") or 0)
        buf = float(data.get("buffer_ms") or 0)
        sink = float(data.get("sink_ms") or 0)
        if lat < 60 or lat > 1200 or buf < 40:
            return None
        return {"latency_ms": lat, "buffer_ms": buf, "sink_ms": sink}
    except Exception:
        return None


def _save_clock_file(data):
    try:
        folder = os.path.dirname(CLOCK_FILE)
        if folder:
            os.makedirs(folder, exist_ok=True)
        tmp = CLOCK_FILE + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(data, fh)
        os.replace(tmp, CLOCK_FILE)
    except OSError:
        pass


class HostPlayer(object):
    def __init__(self, on_end=None):
        self.on_end = on_end
        self.lock = threading.Lock()
        self.proc = None
        self.name = ""
        self.media = ""
        self.paused = False
        self.t0 = 0.0
        self.offset = 0.0
        self.hold = 0.0
        self.duration = 0.0
        self.error = ""
        self.generation = 0
        self.eq = [0.0] * len(EQ_BANDS)
        self._eq_timer = None
        self._vol_lock = threading.Lock()
        self._vol_cv = threading.Condition(self._vol_lock)
        self._vol = self._read_sink_volume()
        self._vol_target = self._vol
        self._muted = False
        self._clock_init()
        self._set_mute(False)
        threading.Thread(target=self._watch, daemon=True).start()
        threading.Thread(target=self._vol_loop, name="vol-fade", daemon=True).start()

    def snapshot(self):
        with self.lock:
            alive = self._alive_locked()
            playback = self._position_locked()
            clock = self._clock_locked(playback)
            return {
                "playing": bool(alive and not self.paused),
                "paused": bool(self.paused and alive),
                "name": self.name,
                "position": clock["heard"],
                "playback": clock["playback"],
                "duration": round(self.duration or 0.0, 3),
                "error": self.error,
                "eq": list(self.eq),
                "clock": clock,
            }

    def play(self, relname, start=0.0):
        base = os.path.realpath(MUSIC_DIR)
        full = os.path.realpath(os.path.join(base, relname.replace("\\", "/").lstrip("/")))
        if full != base and not full.startswith(base + os.sep):
            self.error = "not found"
            return False
        if not os.path.isfile(full):
            self.error = "not found"
            return False
        try:
            start = float(start or 0.0)
        except (TypeError, ValueError):
            start = 0.0
        if start < 0:
            start = 0.0
        with self.lock:
            self.name = os.path.relpath(full, base).replace("\\", "/")
            self.media = full
            self.duration = self._probe(full)
            if self.duration and start >= max(0.0, self.duration - 0.2):
                start = 0.0
            return self._play_locked(full, start)

    def pause(self):
        with self.lock:
            return self._pause_locked()

    def _pause_locked(self):
        if not self._alive_locked():
            self.error = "nothing playing"
            return False
        if self.paused:
            return True
        self.hold = self._position_locked()
        self._set_mute(True)
        try:
            os.killpg(os.getpgid(self.proc.pid), signal.SIGSTOP)
        except Exception as exc:
            self._set_mute(False)
            self.error = str(exc)
            return False
        self.paused = True
        self.error = ""
        return True

    def resume(self):
        with self.lock:
            if not self._alive_locked():
                self.error = "nothing playing"
                return False
            if not self.paused:
                return True
            try:
                os.killpg(os.getpgid(self.proc.pid), signal.SIGCONT)
            except Exception as exc:
                self.error = str(exc)
                return False
            self.t0 = time.monotonic() - (self.hold - self.offset)
            self.paused = False
            self.error = ""
            self._set_mute(False)
            return True

    def stop(self):
        with self.lock:
            self._stop_locked()
            self.name = ""
            self.media = ""
            self.duration = 0.0
            self.error = ""
            return True

    def seek(self, seconds):
        with self.lock:
            if not self.media:
                self.error = "nothing playing"
                return False
            try:
                pos = float(seconds)
            except (TypeError, ValueError):
                self.error = "bad seek"
                return False
            if pos < 0:
                pos = 0.0
            if self.duration > 0:
                pos = min(pos, max(0.0, self.duration - 0.15))
            return self._play_locked(self.media, pos)

    def set_eq(self, gains):
        next_eq = clamp_eq(gains)
        with self.lock:
            same = self.eq == next_eq
            self.eq = next_eq
            if self._eq_timer is not None:
                try:
                    self._eq_timer.cancel()
                except Exception:
                    pass
                self._eq_timer = None
            if same or not self.media:
                return True
            if not self._alive_locked() and not self.paused:
                return True
            timer = threading.Timer(0.4, self._apply_eq_now)
            timer.daemon = True
            self._eq_timer = timer
            timer.start()
        return True

    def _apply_eq_now(self):
        with self.lock:
            self._eq_timer = None
            if not self.media:
                return
            if not self._alive_locked() and not self.paused:
                return
            pos = self._position_locked()
            paused = self.paused
            ok = self._play_locked(self.media, pos)
            if ok and paused:
                self._pause_locked()

    def set_volume(self, n):
        try:
            n = int(round(float(n)))
        except (TypeError, ValueError):
            return False
        n = max(0, min(100, n))
        with self._vol_cv:
            self._vol_target = n
            self._vol_cv.notify()
        return True

    def volume(self):
        with self._vol_lock:
            return int(self._vol_target)

    def _read_sink_volume(self):
        out = _cmd(["pactl", "get-sink-volume", PULSE_SINK])
        for part in out.replace("/", " ").split():
            if part.endswith("%"):
                try:
                    return max(0, min(100, int(part[:-1])))
                except ValueError:
                    pass
        return 100

    def _apply_vol(self, n):
        _cmd(["pactl", "set-sink-volume", PULSE_SINK, "%s%%" % int(n)])

    def _set_mute(self, mute):
        _cmd(["pactl", "set-sink-mute", PULSE_SINK, "1" if mute else "0"])
        self._muted = bool(mute)

    def _vol_loop(self):
        while True:
            with self._vol_cv:
                while self._vol == self._vol_target:
                    self._vol_cv.wait(timeout=0.4)
                target = self._vol_target
                cur = self._vol
            if cur == target:
                continue
            delta = target - cur
            step = int(round(delta * 0.38))
            if step == 0:
                step = 1 if delta > 0 else -1
            nxt = cur + step
            if (delta > 0 and nxt > target) or (delta < 0 and nxt < target):
                nxt = target
            self._apply_vol(nxt)
            with self._vol_lock:
                self._vol = nxt
            time.sleep(0.018)

    def _alive_locked(self):
        return self.proc is not None and self.proc.poll() is None

    def _clock_init(self):
        saved = _load_clock_file()
        default = float(_paplay_ms() + CLOCK_PAD_MS)
        if saved:
            self._lat_ms = saved["latency_ms"]
            self._buf_ms = saved.get("buffer_ms") or 0.0
            self._sink_ms = saved.get("sink_ms") or 0.0
        else:
            self._lat_ms = default
            self._buf_ms = float(_paplay_ms())
            self._sink_ms = float(CLOCK_PAD_MS)
        self._clock_on = False
        self._clock_saved = 0.0

    def _clock_locked(self, playback):
        playback = max(0.0, playback or 0.0)
        lat_s = max(0.0, (self._lat_ms or 0.0) / 1000.0)
        heard = max(self.offset if self.media else 0.0, playback - lat_s)
        if self.duration > 0:
            heard = min(heard, self.duration)
            playback = min(playback, self.duration)
        heard = max(0.0, heard)
        offset_ms = max(0, int(round((playback - heard) * 1000.0)))
        try:
            rate = int(RATE)
        except (TypeError, ValueError):
            rate = 48000
        return {
            "heard": round(heard, 3),
            "playback": round(playback, 3),
            "offset_ms": offset_ms,
            "latency_ms": int(round(self._lat_ms or 0.0)),
            "buffer_ms": int(round(self._buf_ms or 0.0)),
            "sink_ms": int(round(self._sink_ms or 0.0)),
            "paplay_ms": _paplay_ms(),
            "drift_ms": int(round((self._lat_ms or 0.0) - float(_paplay_ms()))),
            "locked": bool(self._clock_on and self._alive_locked() and not self.paused),
            "rate": rate,
        }

    def _apply_latency_sample(self, sample):
        buf = float(sample.get("buffer_ms") or 0.0)
        sink = float(sample.get("sink_ms") or 0.0)
        total = float(sample.get("latency_ms") or (buf + sink))
        if total < 20 or total > 1200:
            return
        if not self._clock_on:
            self._lat_ms = total
        else:
            self._lat_ms = (self._lat_ms * 0.62) + (total * 0.38)
        self._buf_ms = buf
        self._sink_ms = sink
        self._clock_on = True
        now = time.monotonic()
        if self._buf_ms >= 40 and now - self._clock_saved >= 8.0:
            self._clock_saved = now
            _save_clock_file({
                "latency_ms": round(self._lat_ms, 1),
                "buffer_ms": round(self._buf_ms, 1),
                "sink_ms": round(self._sink_ms, 1),
            })

    def _position_locked(self):
        if self.paused or not self._alive_locked():
            pos = self.hold
        else:
            pos = self.offset + (time.monotonic() - self.t0)
        if self.duration > 0:
            pos = min(pos, self.duration)
        return round(max(0.0, pos), 3)

    def _probe(self, path):
        out = _cmd(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                path,
            ]
        )
        try:
            dur = float(out)
            return dur if dur > 0 else 0.0
        except (TypeError, ValueError):
            return 0.0

    def _stop_locked(self):
        proc = self.proc
        self.proc = None
        self.paused = False
        self.offset = 0.0
        self.hold = 0.0
        self.t0 = time.monotonic()
        self.generation += 1
        self._set_mute(False)
        if proc is None:
            return
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    def _play_locked(self, path, start):
        self._stop_locked()
        self.media = path
        ss = "-ss %.3f " % start if start > 0.04 else ""
        af = ffmpeg_eq_filter(self.eq)
        extra = ("-af %s " % shlex.quote(af)) if af else ""
        try:
            open(FFMPEG_LOG, "w").close()
        except OSError:
            pass
        cmd = (
            "ffmpeg -nostdin -hide_banner -nostats -loglevel error "
            "-fflags +nobuffer %s-i %s -ac 2 -ar %s %s-f s16le - 2>>%s "
            "| paplay --device=%s --raw --format=s16le --rate=%s --channels=2 "
            "--latency-msec=%s --process-time-msec=20 --client-name=CRYPT"
            % (
                ss,
                shlex.quote(path),
                shlex.quote(RATE),
                extra,
                shlex.quote(FFMPEG_LOG),
                shlex.quote(PULSE_SINK),
                shlex.quote(RATE),
                shlex.quote(str(int(LATENCY_MS))),
            )
        )
        try:
            self.proc = subprocess.Popen(
                cmd,
                shell=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                preexec_fn=os.setsid,
            )
        except Exception as exc:
            self.error = str(exc)
            self.proc = None
            return False
        self.offset = start
        self.hold = start
        self.t0 = time.monotonic()
        self.paused = False
        self._clock_on = False
        self.error = ""
        return True

    def _watch(self):
        last = -1
        while True:
            time.sleep(0.4)
            ended = False
            gen = 0
            playing = False
            with self.lock:
                if self.proc is not None and self.proc.poll() is not None and not self.paused:
                    if self.generation != last:
                        ended = True
                        gen = self.generation
                        self.proc = None
                        self.hold = self.duration or self._position_locked()
                        self._clock_on = False
                else:
                    playing = bool(self._alive_locked() and not self.paused)
            if ended:
                last = gen
                if self.on_end:
                    try:
                        self.on_end()
                    except Exception:
                        pass
                continue
            if not playing:
                continue
            sample = _read_crypt_latency()
            if not sample:
                continue
            with self.lock:
                if self._alive_locked() and not self.paused:
                    self._apply_latency_sample(sample)
