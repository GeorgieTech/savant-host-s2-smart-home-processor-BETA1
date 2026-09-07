# Deploy notes — CRYPT BETA1

Target: **192.168.1.179**. Never 192.168.1.40 / .178 / .180.

SSH user: `RPM`. Do not commit the password. `scp -O` from modern macOS.

## First-time unit

1. Mask `savant-startup-manager.service` and `nginx.service`.
2. Stop them. Set default target to `multi-user.target`.
3. Stop leftover Pulse (`pulseaudio`) if Savant left one running.
4. Install files in `/data/www`, music dir `/data/music`.
5. Enable `crypt-hostname`, `crypt-pulse`, `crypt-web`.

Savant images on the eMMC are not deleted.

From the repo root:

```sh
scp -O host-webui/index.html host-webui/controls.html host-webui/crypt.css \
  host-webui/server.py host-webui/player.py host-webui/ssc.py \
  host-webui/pin-hostname.sh \
  host-webui/crypt-web.service host-webui/crypt-pulse.service \
  host-webui/crypt-hostname.service \
  RPM@192.168.1.179:/tmp/
```

Then on the host, as root via `sudo env bash`:

```sh
mkdir -p /data/www /data/music
chown RPM:RPM /data/www /data/music
cp /tmp/index.html /tmp/controls.html /tmp/crypt.css \
  /tmp/server.py /tmp/player.py /tmp/ssc.py /tmp/pin-hostname.sh /data/www/
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

## Constraints

- No `apt`. Yocto image.
- Python 3.8 stdlib only.
- DualLite / 1 GB — keep BETA1 to library + TOSLINK + one SSC telnet client. No extra daemons.
- SSC-0014 is reached from the host at `192.168.1.136:23`. See [SSC.md](SSC.md).
