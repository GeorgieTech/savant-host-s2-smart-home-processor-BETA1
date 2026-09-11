# CRYPT — S2 Smart Home Processor V1.1.16

Repo: `savant-host-s2-smart-home-processor-BETA1`

A local TOSLINK music player on a recycled **Savant SHR-S2-00** rack host. Same job as [Gigawatt Beta2](https://github.com/GeorgieTech/savant-host-linux-media-player-BETA2) (library on disk, web UI, optical out), built from scratch for this DualLite chassis.

**Current release: [V1.1.16](https://github.com/GeorgieTech/savant-host-s2-smart-home-processor-BETA1/releases/tag/v1.1.16)** (`v1.1.16`). Previous: [V1.1.15](https://github.com/GeorgieTech/savant-host-s2-smart-home-processor-BETA1/releases/tag/v1.1.15) · [V1.1.14](https://github.com/GeorgieTech/savant-host-s2-smart-home-processor-BETA1/releases/tag/v1.1.14) · [V1.1.13](https://github.com/GeorgieTech/savant-host-s2-smart-home-processor-BETA1/releases/tag/v1.1.13) · [V1.1.12](https://github.com/GeorgieTech/savant-host-s2-smart-home-processor-BETA1/releases/tag/v1.1.12) · [V1.1.11](https://github.com/GeorgieTech/savant-host-s2-smart-home-processor-BETA1/releases/tag/v1.1.11) · [V1.1.10](https://github.com/GeorgieTech/savant-host-s2-smart-home-processor-BETA1/releases/tag/v1.1.10) · [V1.1.9](https://github.com/GeorgieTech/savant-host-s2-smart-home-processor-BETA1/releases/tag/v1.1.9) · [V1.1.8](https://github.com/GeorgieTech/savant-host-s2-smart-home-processor-BETA1/releases/tag/v1.1.8) · [V1.1.7](https://github.com/GeorgieTech/savant-host-s2-smart-home-processor-BETA1/releases/tag/v1.1.7) · [V1.1.6](https://github.com/GeorgieTech/savant-host-s2-smart-home-processor-BETA1/releases/tag/v1.1.6) · [V1.1.5](https://github.com/GeorgieTech/savant-host-s2-smart-home-processor-BETA1/releases/tag/v1.1.5) · [V1.1.4](https://github.com/GeorgieTech/savant-host-s2-smart-home-processor-BETA1/releases/tag/v1.1.4) · [V1.1.3](https://github.com/GeorgieTech/savant-host-s2-smart-home-processor-BETA1/releases/tag/v1.1.3) · [V1.1.2](https://github.com/GeorgieTech/savant-host-s2-smart-home-processor-BETA1/releases/tag/v1.1.2) · [V1.1.1](https://github.com/GeorgieTech/savant-host-s2-smart-home-processor-BETA1/releases/tag/v1.1.1) · [V1.1](https://github.com/GeorgieTech/savant-host-s2-smart-home-processor-BETA1/releases/tag/v1.1.0) · [V1.0](https://github.com/GeorgieTech/savant-host-s2-smart-home-processor-BETA1/releases/tag/v1.0.0).

This project is **not affiliated with Savant Systems**.

Targets: **192.168.1.179** (DualLite S2 mule) and **192.168.1.142** (first SHC-2000, same CRYPT UI). Do not use 192.168.1.40 (live Carrillos Resident), 192.168.1.178 (Gigawatt), or 192.168.1.180 (Giggwatt Beta1).

## What V1.1.16 does

- Unison follower: hold a 18–50 ms Quad lead; short SIGSTOP (≤24 ms, 1.2 s cooldown) if further ahead; **never catch-seek when ahead** (that restart was the #56 ~400 ms hallway slap). Jump seek still ≥1.25 s. Catch-up seek remains behind-only.
- Library loads again when two hosts are linked: page boot `tick`, local catalog first, merge without holding the app lock across HTTP (1.1.14 #52 dropped the fetch; linked `refresh()` could deadlock)
- Dark YouTube Music–inspired **Playing** and **Library** (no light mode): FFT hero, white Play, Time Clock/Pro, Solo|Unison chip, tap-to-play browse. Follower transport looks disabled except Pause/Resume/Seek. Remote/away library rows are read-only until a local-owned row is checked
- Spooky web UI on port 80
- **Playing** page: now playing, FFT visualizer, Rekordbox-style 3-band waveform with beat grid, Time Clock vs decoder timing, transport, and the next 5 tracks in queue
- **Library** page: upload with progress, browse by artist / album / track, playlists, and Manage for bulk delete (with progress) plus artist/album/genre edits. After a link, both hosts show the same catalog; each row is stamped with the chassis that holds the file. Play copies here, then this TOSLINK
- **Karaoke** page: MusicBee-style sidecar `.lrc` / tags / optional LRCLIB fetch, timed to Host Time Clock
- **Report** page: artist / song / album report for later Instagram posts. Research pulls MusicBrainz + Wikipedia, then writes a full meaning-and-life essay (SpaceXAI when `XAI_API_KEY` is set, otherwise a sourced essay from the pages we found)
- **EQ** page: 31-band 1/3-octave TOSLINK graphic equalizer (ISO 266, Q 4.32) with the same HiFi presets expanded onto that grid
- **Settings** page: LAN discovery of other CRYPT chassis. Each host is unique by Savant UID, so a third box appears on its own. **Live** is heard on the wire; **Linked** merges libraries both ways. **Do not trust Live for IGMP** — `beacon.igmp_ok` / `igmp_error` stay sticky if `IP_ADD_MEMBERSHIP` failed even when JSON broadcast still works. **Unison TOSLINK** (optional) plays the same track on every linked optical jack. The follower rides CRYPT/1 CLOCK instead of seeking on the ~400 ms path delay (that seek was the two-zone echo). Pause/stop on the follower confirms over HTTP `/api/clock`; CLOCK silence is not pause. Discovery and clock use multicast `239.18.20.1:41880` with JSON broadcast as fallback. Library merge treats advertised **libver** as an ETag (refetch when it changes). BEACON flags include playing / unison.
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
