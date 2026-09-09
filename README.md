# CRYPT — S2 Smart Home Processor V1.1.7

Repo: `savant-host-s2-smart-home-processor-BETA1`

A local TOSLINK music player on a recycled **Savant SHR-S2-00** rack host. Same job as [Gigawatt Beta2](https://github.com/GeorgieTech/savant-host-linux-media-player-BETA2) (library on disk, web UI, optical out), built from scratch for this DualLite chassis.

**Current release: [V1.1.7](https://github.com/GeorgieTech/savant-host-s2-smart-home-processor-BETA1/releases/tag/v1.1.7)** (`v1.1.7`). Previous: [V1.1.6](https://github.com/GeorgieTech/savant-host-s2-smart-home-processor-BETA1/releases/tag/v1.1.6) · [V1.1.5](https://github.com/GeorgieTech/savant-host-s2-smart-home-processor-BETA1/releases/tag/v1.1.5) · [V1.1.4](https://github.com/GeorgieTech/savant-host-s2-smart-home-processor-BETA1/releases/tag/v1.1.4) · [V1.1.3](https://github.com/GeorgieTech/savant-host-s2-smart-home-processor-BETA1/releases/tag/v1.1.3) · [V1.1.2](https://github.com/GeorgieTech/savant-host-s2-smart-home-processor-BETA1/releases/tag/v1.1.2) · [V1.1.1](https://github.com/GeorgieTech/savant-host-s2-smart-home-processor-BETA1/releases/tag/v1.1.1) · [V1.1](https://github.com/GeorgieTech/savant-host-s2-smart-home-processor-BETA1/releases/tag/v1.1.0) · [V1.0](https://github.com/GeorgieTech/savant-host-s2-smart-home-processor-BETA1/releases/tag/v1.0.0).

This project is **not affiliated with Savant Systems**.

Targets: **192.168.1.179** (DualLite S2 mule) and **192.168.1.142** (first SHC-2000, same CRYPT UI). Do not use 192.168.1.40 (live Carrillos Resident), 192.168.1.178 (Gigawatt), or 192.168.1.180 (Giggwatt Beta1).

## What V1.1.7 does

- Spooky web UI on port 80
- **Playing** page: now playing, FFT visualizer, Rekordbox-style 3-band waveform with beat grid, Time Clock vs decoder timing, transport, and the next 5 tracks in queue
- **Library** page: upload with progress, browse by artist / album / track, playlists, and Manage for bulk delete (with progress) plus artist/album/genre edits
- **Karaoke** page: MusicBee-style sidecar `.lrc` / tags / optional LRCLIB fetch, timed to Host Time Clock
- **Report** page: artist / song / album report for later Instagram posts. Research pulls MusicBrainz + Wikipedia, then writes a full meaning-and-life essay (SpaceXAI when `XAI_API_KEY` is set, otherwise a sourced essay from the pages we found)
- **EQ** page: 31-band 1/3-octave TOSLINK graphic equalizer (ISO 266, Q 4.32) with the same HiFi presets expanded onto that grid
- Play through the SHR-S2 **TOSLINK** jack (`ffmpeg` → `paplay` → Pulse → `imx-spdif`)
- Play / pause / seek / next / prev / volume / delete
- Host Time Clock so the waveform, FFT, and karaoke lines follow audible TOSLINK time, not decoder time
- Deleting a track also deletes its waveform cache, lyrics sidecar/cache, and report cache
- Dark mobile-style web app (Add to Home Screen)

No AirPlay, Spotify, DLNA, NAS, or SSC expanders. DualLite + 1 GB RAM.

Live UI (S2): [http://192.168.1.179/](http://192.168.1.179/) · SHC-2000: [http://192.168.1.142/](http://192.168.1.142/)

On a phone: open the UI in Safari/Chrome, then **Add to Home Screen**.

| Piece | Path |
|---|---|
| Code | `/data/www` |
| Library | `/data/music` |
| Pulse | `crypt-pulse.service` using `/etc/pulse/savant-vcd.pa` |

## Host

- Hardware (DualLite S2): [docs/HOST.md](docs/HOST.md)
- Hardware (first SHC-2000): [docs/HOST-142.md](docs/HOST-142.md)
- Deploy: [docs/DEPLOY.md](docs/DEPLOY.md)
- Fleet plan: [docs/CLUSTER.md](docs/CLUSTER.md) — three SHC-2000 workers + one SHC-2000 TOSLINK playback, feeding a separate app. First Quad is at 192.168.1.142.

## License

[MIT](LICENSE) © 2026 George Carrillo.
