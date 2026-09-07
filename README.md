# CRYPT — S2 Smart Home Processor BETA1

Repo: `savant-host-s2-smart-home-processor-BETA1`

A local TOSLINK music player on a recycled **Savant SHR-S2-00** rack host. Same job as [Gigawatt Beta2](https://github.com/GeorgieTech/savant-host-linux-media-player-BETA2) (library on disk, web UI, optical out), built from scratch for this DualLite chassis.

This project is **not affiliated with Savant Systems**.

Target: **192.168.1.179** only. Do not use 192.168.1.40 (live Carrillos Resident), 192.168.1.178 (Gigawatt), or 192.168.1.180 (Giggwatt Beta1).

## What BETA1 does

- Spooky web UI on port 80
- Upload MP3 / FLAC / Opus / OGG / WAV / M4A / AAC to `/data/music`
- Play through the SHR-S2 **TOSLINK** jack (`ffmpeg` → `paplay` → Pulse → `imx-spdif`)
- Play / pause / seek / next / prev / volume / delete

No AirPlay, Spotify, DLNA, or NAS in BETA1. DualLite + 1 GB RAM.

Live UI: [http://192.168.1.179/](http://192.168.1.179/)

| Piece | Path |
|---|---|
| Code | `/data/www` |
| Library | `/data/music` |
| Pulse | `crypt-pulse.service` using `/etc/pulse/savant-vcd.pa` |

## Host

- Hardware: [docs/HOST.md](docs/HOST.md)
- Deploy: [docs/DEPLOY.md](docs/DEPLOY.md)

## License

[MIT](LICENSE) © 2026 George Carrillo.
