#!/usr/bin/env python3
"""SSC-0014 telnet client. Python 3.8 stdlib only.

Talks to the SmartControl 14 CLI on port 23. Whitelist is show + relay
on/off for ports 0-6 (relays 1-7). Never sends ip/mac/reset/gpio/etc.
"""
from __future__ import print_function

import os
import re
import socket
import threading
import time

IAC, DONT, DO, WONT, WILL, SB, SE = 255, 254, 253, 252, 251, 250, 240

RELAY_COUNT = 7
DEFAULT_HOST = os.environ.get("SSC_HOST", "192.168.1.136")
DEFAULT_PORT = int(os.environ.get("SSC_PORT", "23"))

_ALLOWED = re.compile(r"^(show|relay on [0-6]|relay off [0-6])$")
_RE_FW = re.compile(r"FW:\s*([0-9.:]+),\s*BL:\s*([0-9.:]+)")
_RE_UID = re.compile(r"UID:\s*([0-9A-Fa-f]+),\s*S/N:\s*([0-9A-Za-z]+),\s*P/N:\s*([0-9A-Za-z._-]+)")
_RE_NET = re.compile(r"Network is UP:\s*([0-9.]+)\s*\(([^)]+)\)")
_RE_UP = re.compile(r"MCU Uptime:\s*([^\r\n]+?)(?:\s{2,}|\s+\d+\s+total)")
_RE_RELAY = re.compile(r"Relay Status:\s*([0-9 ]+)")
_RE_COUNTS = re.compile(r"Counts:\s*([0-9 ]+)")


def _process_iac(data, pending):
    buf = pending + data
    out = bytearray()
    replies = bytearray()
    i = 0
    n = len(buf)
    while i < n:
        if buf[i] != IAC:
            out.append(buf[i])
            i += 1
            continue
        if i + 1 >= n:
            break
        cmd = buf[i + 1]
        if cmd == IAC:
            out.append(IAC)
            i += 2
            continue
        if cmd in (DO, DONT, WILL, WONT):
            if i + 2 >= n:
                break
            opt = buf[i + 2]
            if cmd == DO:
                replies += bytes([IAC, WONT, opt])
            elif cmd == WILL:
                replies += bytes([IAC, DONT, opt])
            i += 3
            continue
        if cmd == SB:
            j = i + 2
            found = False
            while j + 1 < n:
                if buf[j] == IAC and buf[j + 1] == SE:
                    i = j + 2
                    found = True
                    break
                j += 1
            if not found:
                break
            continue
        i += 2
    return bytes(out), bytes(replies), buf[i:]


def _ints(blob, n=RELAY_COUNT):
    vals = []
    for tok in (blob or "").split():
        try:
            vals.append(int(tok))
        except ValueError:
            continue
    while len(vals) < n:
        vals.append(0)
    return vals[:n]


def parse_show(text):
    fw = bl = uid = sn = pn = ip = mode = uptime = ""
    m = _RE_FW.search(text)
    if m:
        fw, bl = m.group(1).rstrip("."), m.group(2).rstrip(".")
    m = _RE_UID.search(text)
    if m:
        uid, sn, pn = m.group(1).upper(), m.group(2), m.group(3)
    m = _RE_NET.search(text)
    if m:
        ip, mode = m.group(1), m.group(2)
    m = _RE_UP.search(text)
    if m:
        uptime = m.group(1).strip().rstrip(".")
    status = [0] * RELAY_COUNT
    m = _RE_RELAY.search(text)
    if m:
        status = _ints(m.group(1))
    counts = [0] * RELAY_COUNT
    m = _RE_COUNTS.search(text)
    if m:
        counts = _ints(m.group(1))
    relays = []
    for port in range(RELAY_COUNT):
        relays.append({
            "relay": port + 1,
            "port": port,
            "on": bool(status[port]),
            "count": counts[port],
        })
    return {
        "model": "SSC-0014",
        "fw": fw,
        "bl": bl,
        "uid": uid,
        "sn": sn,
        "pn": pn,
        "ip": ip,
        "dhcp": "DHCP" in (mode or "").upper(),
        "net_mode": mode,
        "uptime": uptime,
        "relays": relays,
    }


class SscClient(object):
    def __init__(self, host=DEFAULT_HOST, port=DEFAULT_PORT, timeout=4.0):
        self.host = host
        self.port = int(port)
        self.timeout = float(timeout)
        self.lock = threading.Lock()
        self._sock = None
        self._iac = b""
        self.last_error = None
        self._cache = None
        self._cache_at = 0.0

    def close(self):
        with self.lock:
            self._close()

    def snapshot(self, force=False):
        with self.lock:
            now = time.time()
            if not force and self._cache and (now - self._cache_at) < 0.8:
                return dict(self._cache)
            try:
                text = self._cmd("show", wait=6.0)
                if "PASS" not in text:
                    raise IOError("show did not PASS")
                info = parse_show(text)
                snap = {
                    "ok": True,
                    "online": True,
                    "host": self.host,
                    "port": self.port,
                    "error": None,
                }
                snap.update(info)
                self._cache = snap
                self._cache_at = time.time()
                self.last_error = None
                return dict(snap)
            except Exception as exc:
                self.last_error = str(exc)
                self._close()
                return {
                    "ok": False,
                    "online": False,
                    "host": self.host,
                    "port": self.port,
                    "model": "SSC-0014",
                    "fw": "",
                    "bl": "",
                    "uid": "",
                    "sn": "",
                    "pn": "",
                    "ip": "",
                    "dhcp": False,
                    "net_mode": "",
                    "uptime": "",
                    "relays": [
                        {"relay": i + 1, "port": i, "on": False, "count": 0}
                        for i in range(RELAY_COUNT)
                    ],
                    "error": self.last_error,
                }

    def set_relay(self, port, on):
        port = int(port)
        if port < 0 or port >= RELAY_COUNT:
            raise ValueError("relay port must be 0-6")
        verb = "on" if on else "off"
        with self.lock:
            text = self._cmd("relay %s %d" % (verb, port), wait=4.0)
            ok = "PASS" in text and "FAIL" not in text
            if not ok:
                raise IOError("relay %s %d: %s" % (verb, port, text.strip()[:180]))
            self._cache = None
        return self.snapshot(force=True)

    def set_all(self, on):
        verb = "on" if on else "off"
        with self.lock:
            last = ""
            for port in range(RELAY_COUNT):
                last = self._cmd("relay %s %d" % (verb, port), wait=4.0)
                if "PASS" not in last or "FAIL" in last:
                    raise IOError("relay %s %d failed" % (verb, port))
            self._cache = None
        return self.snapshot(force=True)

    def _close(self):
        sock = self._sock
        self._sock = None
        self._iac = b""
        if sock is not None:
            try:
                sock.close()
            except Exception:
                pass

    def _ensure(self):
        if self._sock is not None:
            return
        sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        sock.settimeout(0.25)
        self._sock = sock
        self._iac = b""
        self._read(max_wait=2.5, idle=0.4, need_prompt=False)
        self._send(b"\r\n")
        self._read(max_wait=2.0, idle=0.35, need_prompt=True)

    def _send(self, raw):
        self._sock.sendall(raw)

    def _read(self, max_wait, idle, need_prompt):
        data = b""
        start = time.time()
        last = time.time()
        saw = False
        while time.time() - start < max_wait:
            try:
                chunk = self._sock.recv(4096)
                if not chunk:
                    self._close()
                    raise IOError("ssc closed the socket")
                text, replies, self._iac = _process_iac(chunk, self._iac)
                if replies:
                    self._send(replies)
                if text:
                    data += text
                    last = time.time()
                    if b"SSC>" in data:
                        saw = True
            except socket.timeout:
                quiet = time.time() - last
                if need_prompt and saw and quiet >= idle:
                    break
                if (not need_prompt) and quiet >= idle:
                    break
                if data and quiet >= 1.2:
                    break
        return data.decode("latin1", "replace")

    def _cmd(self, line, wait=5.0):
        if not _ALLOWED.match(line):
            raise ValueError("refusing SSC command: %s" % line)
        try:
            self._ensure()
            self._send((line + "\r\n").encode("ascii"))
            return self._read(max_wait=wait, idle=0.28, need_prompt=True)
        except Exception:
            self._close()
            self._ensure()
            self._send((line + "\r\n").encode("ascii"))
            return self._read(max_wait=wait, idle=0.28, need_prompt=True)
