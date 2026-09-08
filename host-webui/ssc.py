#!/usr/bin/env python3
"""SSC telnet clients. Python 3.8 stdlib only.

Whitelist is show + relay on/off. Never sends ip/mac/reset/gpio/etc.
"""
from __future__ import print_function

import os
import re
import socket
import threading
import time

IAC, DONT, DO, WONT, WILL, SB, SE = 255, 254, 253, 252, 251, 250, 240

DEFAULT_DEVICES = (
    {
        "id": "ssc14",
        "model": "SSC-0014",
        "title": "SmartControl 14",
        "host": os.environ.get("SSC14_HOST", os.environ.get("SSC_HOST", "192.168.1.136")),
        "port": int(os.environ.get("SSC14_PORT", os.environ.get("SSC_PORT", "23"))),
        "relays": 7,
        "uid": "001AAE01C4D20021",
    },
)

_ALLOWED = re.compile(r"^(show|relay on [0-9]|relay off [0-9])$")
_RE_FW = re.compile(r"FW:\s*([0-9.:]+),\s*BL:\s*([0-9.:]+)")
_RE_UID = re.compile(r"UID:\s*([0-9A-Fa-f]+),\s*S/N:\s*([0-9A-Za-z]+),\s*P/N:\s*([0-9A-Za-z._-]+)")
_RE_NET = re.compile(r"Network is UP:\s*([0-9.]+)\s*\(([^)]+)\)")
_RE_UP = re.compile(r"MCU Uptime:\s*([^\r\n]+?)(?:\s{2,}|\s+\d+\s+total)")
_RE_RELAY = re.compile(r"Relay Status:\s*([0-9 ]+)")
_RE_COUNTS = re.compile(r"Counts:\s*([0-9 ]+)")
_RE_MODEL = re.compile(r"SSC-00[0-9]{2}")
_RE_UPLINK = re.compile(r"Uplinked\s+([0-9.]+):(\d+)")
_RE_NOT_UPLINK = re.compile(r"Not uplinked:\s*(\d+)")
_RE_GPIO0 = re.compile(r"GPIO0\s+\S+\(([^)]+)\)")

AVD_PROBE = bytes.fromhex("025004")
AVD_UPLINK_ON = bytes.fromhex("03500401")
AVD_DISCOVERY_PORT = 12004
AVD_DEVICE_PORT = 12005


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


def _ints(blob, n):
    vals = []
    for tok in (blob or "").split():
        try:
            vals.append(int(tok))
        except ValueError:
            continue
    if n is None:
        return vals
    while len(vals) < n:
        vals.append(0)
    return vals[:n]


def parse_show(text, relay_count=None, default_model="SSC"):
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
    status = []
    m = _RE_RELAY.search(text)
    if m:
        status = _ints(m.group(1), None)
    counts = []
    m = _RE_COUNTS.search(text)
    if m:
        counts = _ints(m.group(1), None)
    n = relay_count if relay_count else (len(status) or 0)
    if not n:
        n = 0
    status = _ints(" ".join(str(x) for x in status), n)
    counts = _ints(" ".join(str(x) for x in counts), n)
    relays = []
    for port in range(n):
        relays.append({
            "relay": port + 1,
            "port": port,
            "on": bool(status[port]),
            "count": counts[port],
        })
    model = default_model
    m = _RE_MODEL.search(text)
    if m:
        model = m.group(0)
    up_ip, up_port = "", 0
    m = _RE_UPLINK.search(text)
    if m:
        up_ip, up_port = m.group(1), int(m.group(2))
    not_up = 0
    m = _RE_NOT_UPLINK.search(text)
    if m:
        not_up = int(m.group(1))
    gpio_host = False
    m = _RE_GPIO0.search(text)
    if m:
        gpio_host = m.group(1).strip().lower() == "host"
    return {
        "model": model,
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
        "uplinked_ip": up_ip,
        "uplinked_port": up_port,
        "uplinked": bool(up_ip and up_ip != "0.0.0.0"),
        "not_uplinked": not_up,
        "gpio_host": gpio_host,
    }


class SscClient(object):
    def __init__(self, spec):
        self.id = spec["id"]
        self.model = spec.get("model") or "SSC"
        self.title = spec.get("title") or self.model
        self.host = spec["host"]
        self.port = int(spec.get("port") or 23)
        self.relay_count = int(spec.get("relays") or 0)
        self.timeout = float(spec.get("timeout") or 4.0)
        self.expect_uid = (spec.get("uid") or "").upper()
        self.lock = threading.Lock()
        self._sock = None
        self._iac = b""
        self.last_error = None
        self._cache = None
        self._cache_at = 0.0
        self._cli_fail_at = 0.0

    def close(self):
        with self.lock:
            self._close()

    def _offline(self, err):
        self.last_error = err
        return {
            "ok": False,
            "online": False,
            "id": self.id,
            "title": self.title,
            "host": self.host,
            "port": self.port,
            "model": self.model,
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
                for i in range(self.relay_count)
            ],
            "error": err,
            "cli": False,
            "seen": False,
            "uplinked": False,
            "uplinked_ip": "",
            "uplinked_port": 0,
            "gpio_host": False,
            "uid": self.expect_uid,
        }

    def snapshot(self, force=False):
        with self.lock:
            now = time.time()
            if not force and self._cache and (now - self._cache_at) < 0.8:
                return dict(self._cache)
            if not force and self._cli_fail_at and (now - self._cli_fail_at) < 20:
                return self._offline(self.last_error or "ssc closed the socket")
            try:
                text = self._cmd("show", wait=6.0)
                if "PASS" not in text:
                    raise IOError("show did not PASS")
                info = parse_show(text, self.relay_count, self.model)
                snap = {
                    "ok": True,
                    "online": True,
                    "cli": True,
                    "seen": True,
                    "id": self.id,
                    "title": self.title,
                    "host": self.host,
                    "port": self.port,
                    "error": None,
                }
                snap.update(info)
                if not snap.get("model"):
                    snap["model"] = self.model
                self._cache = snap
                self._cache_at = time.time()
                self.last_error = None
                self._cli_fail_at = 0.0
                return dict(snap)
            except Exception as exc:
                self._close()
                self._cli_fail_at = time.time()
                return self._offline(str(exc))

    def set_relay(self, port, on):
        port = int(port)
        if port < 0 or port >= self.relay_count:
            raise ValueError("relay port must be 0-%d" % (self.relay_count - 1))
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
            for port in range(self.relay_count):
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
        try:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except Exception:
            pass
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
        if line.startswith("relay "):
            port = int(line.rsplit(" ", 1)[1])
            if port < 0 or port >= self.relay_count:
                raise ValueError("relay port out of range")
        try:
            self._ensure()
            self._send((line + "\r\n").encode("ascii"))
            return self._read(max_wait=wait, idle=0.28, need_prompt=True)
        except Exception:
            self._close()
            self._ensure()
            self._send((line + "\r\n").encode("ascii"))
            return self._read(max_wait=wait, idle=0.28, need_prompt=True)


def _crypt_uid():
    env = (os.environ.get("CRYPT_UID") or "").strip().upper()
    if len(env) >= 12:
        return env[:16].ljust(16, "0")
    try:
        hn = socket.gethostname()
    except Exception:
        hn = ""
    m = re.search(r"([0-9A-Fa-f]{16})", hn)
    if m:
        return m.group(1).upper()
    return "001AAE10E4090000"


class AvdHost(object):
    """Minimal Savant AVD discovery: host probe 02 50 04 + uplink-on 03 50 04 01."""

    def __init__(self, clients):
        self.clients = list(clients)
        self.uid = _crypt_uid()
        self.lock = threading.Lock()
        self.beacons = {}
        self._sock = None
        self._stop = False
        self.last_error = None
        t = threading.Thread(target=self._run, name="avd-host")
        t.daemon = True
        t.start()

    def for_client(self, client):
        with self.lock:
            by_ip = self.beacons.get(client.host)
            if by_ip:
                return dict(by_ip)
            if client.expect_uid:
                for rec in self.beacons.values():
                    if rec.get("uid") == client.expect_uid:
                        return dict(rec)
        return None

    def _run(self):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.bind(("0.0.0.0", AVD_DISCOVERY_PORT))
            sock.settimeout(0.5)
            self._sock = sock
        except Exception as exc:
            self.last_error = str(exc)
            return
        last_probe = 0.0
        last_uplink = {}
        host29 = self._host_announce()
        while not self._stop:
            now = time.time()
            if now - last_probe >= 2.0:
                try:
                    sock.sendto(AVD_PROBE, ("192.168.1.255", AVD_DISCOVERY_PORT))
                    last_probe = now
                except Exception as exc:
                    self.last_error = str(exc)
            try:
                data, addr = sock.recvfrom(2048)
            except socket.timeout:
                continue
            except Exception as exc:
                self.last_error = str(exc)
                time.sleep(0.5)
                continue
            rec = self._parse_beacon(data, addr)
            if rec and rec.get("uid") == self.uid:
                rec = None
            known = set(c.host for c in self.clients)
            if rec and rec["ip"] not in known:
                rec = None
            if rec:
                with self.lock:
                    self.beacons[rec["ip"]] = rec
                key = rec["ip"]
                if now - last_uplink.get(key, 0) >= 5.0:
                    last_uplink[key] = now
                    try:
                        sock.sendto(AVD_PROBE, (rec["ip"], AVD_DEVICE_PORT))
                        sock.sendto(AVD_UPLINK_ON, (rec["ip"], AVD_DEVICE_PORT))
                        sock.sendto(host29, (rec["ip"], AVD_DEVICE_PORT))
                    except Exception:
                        pass

    def _local_ip(self):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("192.168.1.1", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "192.168.1.179"

    def _host_announce(self):
        ip = self._local_ip()
        parts = [int(x) for x in ip.split(".")]
        while len(parts) < 4:
            parts.append(0)
        tail = bytes([1, parts[0], parts[1], parts[2], parts[3], 0, 1, 0, 0, 0])
        body = bytes([0x50, 0x04]) + self.uid.encode("ascii")[:16].ljust(16, b"0") + tail
        return bytes([len(body)]) + body

    def _parse_beacon(self, data, addr):
        if not data or len(data) < 19:
            return None
        if data[0] != 0x1C or data[1] != 0x50:
            return None
        try:
            uid = data[3:19].decode("ascii").upper()
        except Exception:
            return None
        if not re.match(r"^[0-9A-F]{16}$", uid):
            return None
        return {
            "ip": addr[0],
            "port": addr[1],
            "uid": uid,
            "at": time.time(),
            "raw": data.hex(),
        }


class SscHub(object):
    def __init__(self, devices=None):
        self.clients = []
        self.by_id = {}
        for spec in devices or DEFAULT_DEVICES:
            client = SscClient(spec)
            self.clients.append(client)
            self.by_id[client.id] = client
        self.avd = AvdHost(self.clients)

    def get(self, devid):
        client = self.by_id.get(devid)
        if client is None:
            raise KeyError("unknown expander %s" % devid)
        return client

    def _merge_beacon(self, client, snap):
        rec = self.avd.for_client(client)
        now = time.time()
        if rec and (now - rec.get("at", 0)) < 30:
            snap["seen"] = True
            snap["seen_age"] = int(now - rec["at"])
            if rec.get("uid") and not snap.get("uid"):
                snap["uid"] = rec["uid"]
            snap["beacon_ip"] = rec.get("ip")
        else:
            snap["seen"] = bool(snap.get("cli"))
            snap["seen_age"] = None
        snap["cli"] = bool(snap.get("cli"))
        if snap.get("cli"):
            snap["online"] = True
            snap["ok"] = True
        elif snap.get("seen"):
            snap["online"] = True
            snap["ok"] = True
            err = snap.get("error") or ""
            if (not err) or "closed" in err or "timeout" in err:
                snap["error"] = "CLI down — heard on UDP 12004"
        return snap

    def snapshot_all(self, force=False):
        box = {}

        def run(client):
            box[client.id] = client.snapshot(force=force)

        threads = []
        for client in self.clients:
            t = threading.Thread(target=run, args=(client,))
            t.daemon = True
            t.start()
            threads.append((t, client))
        for t, client in threads:
            t.join(8.0)
            if t.is_alive() and client.id not in box:
                box[client.id] = client._offline("timeout")
        devices = []
        for client in self.clients:
            snap = box.get(client.id) or client._offline("no snapshot")
            devices.append(self._merge_beacon(client, snap))
        online = sum(1 for d in devices if d.get("online"))
        return {
            "ok": True,
            "online": online,
            "count": len(devices),
            "devices": devices,
            "avd_uid": self.avd.uid,
            "avd_error": self.avd.last_error,
        }
