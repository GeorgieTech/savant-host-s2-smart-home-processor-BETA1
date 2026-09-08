# CRYPT — S2 Smart Home Processor V1.1.1

Repo: `savant-host-s2-smart-home-processor-BETA1`

A local TOSLINK music player on a recycled **Savant SHR-S2-00** rack host. Same job as [Gigawatt Beta2](https://github.com/GeorgieTech/savant-host-linux-media-player-BETA2) (library on disk, web UI, optical out), built from scratch for this DualLite chassis.

**Current release: [V1.1.1](https://github.com/GeorgieTech/savant-host-s2-smart-home-processor-BETA1/releases/tag/v1.1.1)** (`v1.1.1`). Previous: [V1.1](https://github.com/GeorgieTech/savant-host-s2-smart-home-processor-BETA1/releases/tag/v1.1.0) · [V1.0](https://github.com/GeorgieTech/savant-host-s2-smart-home-processor-BETA1/releases/tag/v1.0.0).

This project is **not affiliated with Savant Systems**.

Target: **192.168.1.179** only. Do not use 192.168.1.40 (live Carrillos Resident), 192.168.1.178 (Gigawatt), or 192.168.1.180 (Giggwatt Beta1).

## What V1.1.1 does

- Spooky web UI on port 80
- **Playing** page: now playing, FFT visualizer, Rekordbox-style 3-band waveform (V1.1.1 envelopes bands before downsample so hats stay visible), Time Clock vs decoder timing, transport, and the next 5 tracks in queue
- **Library** page: upload with progress, browse by artist / album / track, playlists, and Manage for bulk delete (with progress) plus artist/album/genre edits
- **EQ** page: 10-band TOSLINK equalizer (ffmpeg, same bands as Gigawatt Beta2)
- Play through the SHR-S2 **TOSLINK** jack (`ffmpeg` → `paplay` → Pulse → `imx-spdif`)
- Play / pause / seek / next / prev / volume / delete
- Host Time Clock so the waveform and FFT follow audible TOSLINK time, not decoder time. V1.1 holds path delay (AFC-style PLL) instead of chasing Pulse jitter, and exposes word-clock / jitter / ppm on Playing.
- **Relays** page drives **SSC-0014** (`192.168.1.136`, 7 relays)
- Dark mobile-style web app (Add to Home Screen)

No AirPlay, Spotify, DLNA, or NAS. DualLite + 1 GB RAM.

Live UI: [http://192.168.1.179/](http://192.168.1.179/) · Library: [http://192.168.1.179/library](http://192.168.1.179/library) · EQ: [http://192.168.1.179/eq](http://192.168.1.179/eq) · Relays: [http://192.168.1.179/controls](http://192.168.1.179/controls)

On a phone: open the UI in Safari/Chrome, then **Add to Home Screen**.

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
