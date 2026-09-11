# Deploy notes — CRYPT V1.1.13

Targets: **192.168.1.179** (DualLite S2) and **192.168.1.142** (SHC-S2-00 Quad). Never 192.168.1.40 / .178 / .180.

Do not `dd` the S2 eMMC onto an SHC-2000. Install CRYPT files the same way on both; `/data` is `mmcblk0p2` on DualLite and `mmcblk0p3` on Quad.

SSH user: `RPM`. Do not commit the password. `scp -O` from modern macOS.

## First-time unit

1. Mask `savant-startup-manager.service` and `nginx.service`.
2. Stop them. Set default target to `multi-user.target`.
3. Stop leftover Pulse (`pulseaudio`) if Savant left one running.
4. Install files in `/data/www`, music dir `/data/music`.
5. Enable `crypt-hostname`, `crypt-pulse`, `crypt-web`.

Savant images on the eMMC are not deleted.

From the repo root. Peer/Unison wire: [PEER-PROTOCOL.md](PEER-PROTOCOL.md). LAN / IGMP for that wire: **LAN for CRYPT/1 and Unison** below.

```sh
scp -O host-webui/index.html host-webui/library.html host-webui/eq.html host-webui/karaoke.html host-webui/report.html host-webui/settings.html host-webui/crypt.css \
  host-webui/server.py host-webui/player.py host-webui/library.py host-webui/wave.py host-webui/lyrics.py host-webui/research.py host-webui/report.py host-webui/essay.py host-webui/peers.py host-webui/unison.py host-webui/crypt_wire.py \
  host-webui/manifest.webmanifest host-webui/favicon.svg \
  host-webui/icon.png host-webui/apple-touch-icon.png \
  host-webui/pin-hostname.sh \
  host-webui/crypt-web.service host-webui/crypt-pulse.service \
  host-webui/crypt-hostname.service \
  RPM@192.168.1.179:/tmp/
```

Then on the host, as root via `sudo env bash`:

```sh
mkdir -p /data/www /data/music
chown RPM:RPM /data/www /data/music
cp /tmp/index.html /tmp/library.html /tmp/eq.html /tmp/karaoke.html /tmp/report.html /tmp/settings.html /tmp/crypt.css \
  /tmp/server.py /tmp/player.py /tmp/library.py /tmp/wave.py /tmp/lyrics.py /tmp/research.py /tmp/report.py /tmp/essay.py /tmp/peers.py /tmp/unison.py /tmp/crypt_wire.py /tmp/pin-hostname.sh \
  /tmp/manifest.webmanifest /tmp/favicon.svg /tmp/icon.png /tmp/apple-touch-icon.png \
  /data/www/
chmod +x /data/www/pin-hostname.sh /data/www/server.py
cp /tmp/crypt-web.service /tmp/crypt-pulse.service /tmp/crypt-hostname.service /etc/systemd/system/
systemctl mask savant-startup-manager.service nginx.service
systemctl stop savant-startup-manager.service nginx.service
systemctl stop pulseaudio.service 2>/dev/null || true
systemctl set-default multi-user.target
systemctl daemon-reload
systemctl enable crypt-hostname.service crypt-pulse.service crypt-web.service
systemctl restart crypt-hostname.service crypt-pulse.service crypt-web.service
```

Open http://192.168.1.179/

## LAN for CRYPT/1 and Unison (#6, #7)

Discovery and Unison CLOCK use multicast **`239.18.20.1:41880`** with **TTL 1** and IGMP join on **`eth0`**. Chassis that must hear each other share **one L2** on **`192.168.1.0/24`**. A router hop expires the datagram even if HTTP still works. Peer URLs are hard-prefixed `192.168.1.` (`LAN_PREFIX` in `peers.py`); a different subnet is rejected unless that product constant is changed on purpose.

Private-link / dual-NIC (second prefix, USB-Ethernet, `eth1`) is **deferred** until hardware and product support exist. These chassis are **eth0-only** (`wlan*` is skipped). Unicast CLOCK to a linked peer IP is a later idea in [PEER-PROTOCOL.md](PEER-PROTOCOL.md); it is **not** a substitute for IGMP on the group.

JSON directed broadcast (`192.168.1.255`) stays as dual-stack fallback. **Issue #8 drop remains HOLD** until sustained Unison earshot ([#9](https://github.com/GeorgieTech/savant-host-s2-smart-home-processor-BETA1/issues/9)). Do not drop broadcast in this docs pass. Path A wire is proven; that is **not** Unison earshot PASS.

### IGMP snooping + exactly one querier

`239/8` (RFC 2365 administratively scoped) does **not** constrain L2 flooding by itself. The switch must run **IGMP snooping**, and there must be **exactly one IGMP querier** on that LAN/VLAN.

RFC 4541 (IGMP/MLD snooping switches): without a querier (or a multicast router sending queries), snooping membership **ages out**. Then CLOCK/BEACON go silent while JSON broadcast can still make Settings look **Live**. Live is not membership.

Do **not** use aggressive multicast storm-control on CRYPT access ports as an IGMP substitute. CLOCK is ~20 Hz; storm-control will drop it.

### Lab verify (Path A wire)

On **both** DualLite `.179` and Quad `.142` (as `RPM`):

1. Join-group recv of `CRPT` on `239.18.20.1:41880` (snippet in [PEER-PROTOCOL.md](PEER-PROTOCOL.md)). Send-to-group is not membership (`IP_MULTICAST_LOOP` is 0).
2. After [#41](https://github.com/GeorgieTech/savant-host-s2-smart-home-processor-BETA1/pull/41): Settings / fleet `beacon.igmp_ok` true (or `igmp_error` if join failed). **Live ≠ membership.**
3. Unison snapshot `via=udp` means CLOCK datagrams are arriving. That is not issue #9 earshot PASS.

Lab Path A (this house, not a generic cookbook): group `239.18.20.1:41880`, TTL 1, L2 multicast MAC `01:00:5e:12:14:01`. Peer `CRPT` recv **PASS** both ways; `igmp_ok` true after #41; Unison `via=udp`.

### This lab’s GS752TPP model (web UI only)

NETGEAR GS752TPP Fully Managed — **web UI**, not CLI. Menu paths from user manual **202-12021-06**: **Switching → Multicast → IGMP Snooping** and **Switching → Multicast → IGMP Snooping Querier**.

This lab:

| Switch | IP | Role |
|---|---|---|
| Core GS752TPP | 192.168.1.10 | **IGMP querier** on VLAN 1 |
| Secondary GS752TPP | 192.168.1.11 | **IGMP snooping**; DualLite `.179` and Quad `.142` live here |

Do not invent CLI for these Fully Managed switches. Other sites need snooping + exactly one querier on the VLAN that carries CRYPT; they do not need this pair of management IPs. Port-level Path A notes already in [CLUSTER.md](CLUSTER.md).

## Constraints

- No `apt`. Yocto image.
- Python 3.8 stdlib only.
- DualLite / 1 GB — keep V1.1.7 to library + TOSLINK. No extra daemons. No SSC expanders.
- Optional meaning essay: put `XAI_API_KEY=...` in `/data/crypt/xai.env` (not in git). The unit already reads that file. Without it, Research still writes a sourced essay from Wikipedia and local lyrics.
