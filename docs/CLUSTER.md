# Future plan — four SHC-2000 CRYPT engines

Status: **plan only**. Not built. Live CRYPT V1.1.7 stays on the DualLite SHR-S2 at **192.168.1.179**.

Goal: three SHC-2000 hosts run the full CRYPT web UI as **worker engines**. A fourth SHC-2000 is the **main TOSLINK playback** engine. A **separate application** (not this DualLite UI) sits in front, fans jobs out, and consumes the JSON those four hosts produce — reports, essays, lyrics, waveforms, clock, library — at higher throughput than one box can give.

This is a job farm on the lab LAN. It is not Kubernetes, not Savant clustering, not one shared TOSLINK, and not NAS/DLNA.

Do **not** use **192.168.1.40** (Carrillos Resident), **192.168.1.178** (Gigawatt), or **192.168.1.180** (Giggwatt Beta1). Do not spoof Carrillos UID `001AAE1C6F5F0000`.

## Picture

```
Separate app we build  (phone / Mac / future CRYPT console)
        │  HTTP JSON
        ▼
┌─────────────────────────────────────────────────────────┐
│  Playback SHC-2000  — TOSLINK, Playing, EQ, Time Clock  │
│  Source of truth for “what is audible right now”        │
└─────────────────────────────────────────────────────────┘
        ▲
        │  jobs / results (same CRYPT APIs)
        │
┌───────────────┬───────────────┬───────────────┐
│ Worker A      │ Worker B      │ Worker C      │
│ SHC-2000      │ SHC-2000      │ SHC-2000      │
│ Report/essay  │ Wave/beat     │ Lyrics +     │
│ research      │ analyze       │ overflow     │
│ (full CRYPT)  │ (full CRYPT)  │ (full CRYPT) │
└───────────────┴───────────────┴───────────────┘
```

Each of the four hosts runs **the same** CRYPT web UI (`/data/www`, port 80, Python 3.8 stdlib). They do not share `/data`, Pulse, or RAM. The new app is the only piece that knows the fleet.

## Hardware

| Role | Chassis | Why |
|---|---|---|
| Playback | SHC-2000 / SHC-S2 Quad (2 GB, 4 cores) | TOSLINK to the room. Keep Research off this box while music is up. |
| Worker A / B / C | Same SHC-2000 class | Quad + 2 GB is the engine. DualLite 1 GB is the current lab mule, not the farm. |

The live host at `.179` is an **SHR-S2-00 DualLite**. Do **not** `dd` that image onto an SHC-2000 (`/data` partition layout differs: DualLite `mmcblk0p2` vs Quad `p3`). Convert each SHC-2000 the same way we converted `.179`, then install CRYPT from this repo.

Assign lab IPs later. Until then use names: `crypt-play`, `crypt-work-a`, `crypt-work-b`, `crypt-work-c`. Keep them on `192.168.1.0/24` with this project’s existing “never .40 / .178 / .180” rule.

## What the separate app consumes

The funnel app does not re-implement ffmpeg, Pulse, Wikipedia, or EQ. It calls the APIs we already ship:

| Need | API | Prefer host |
|---|---|---|
| What TOSLINK is emitting | `GET /api/status`, `GET /api/clock` | **Playback** |
| Transport | `POST /api/play` `{name,start}`, pause / resume / next / seek / volume / EQ | **Playback** |
| Library identity (artist, title, album) | `GET /api/library` | Playback (canonical library) |
| Track report + meaning essay | `POST /api/report` `{name, fetch:true}` | **Worker A** (overflow B/C) |
| Lyrics / karaoke | `GET` or `POST /api/lyrics` | **Worker C** |
| 3-band waveform + beat grid | `GET /api/wave?name=` | **Worker B** |
| EQ curve | `GET` / `POST /api/eq` | **Playback** (it is in the TOSLINK chain) |

Research does **not** need the FLAC on the worker if the app sends artist / title / album. Waveforms and TOSLINK **do** need the file on that host.

## Data movement (no NAS)

Hard rule: no AirPlay, Spotify, DLNA, or NAS. Libraries stay on local eMMC.

1. **Canonical music** lives on **playback** `/data/music`.
2. Workers that must decode (wave analyze) get a **copy** of the track (scp / `POST /api/upload`), not a network mount.
3. Workers that only research get `{artist, title, album, year, genre}` from the app, plus optional sidecar `.lrc` bytes if we add a small upload later.
4. Caches stay **per host** and **attached to the track name**, same as V1.1.3–V1.1.7:
   - `/data/crypt/waves`
   - `/data/crypt/lyrics`
   - `/data/crypt/reports`
   Deleting a track on playback must tell the app to drop the same `name` on workers (`POST /api/delete` or a future `/api/drop-cache`). No dead JSON left behind.

Optional later: a `CRYPT_PEERS` list so playback can fan `drop_name` itself. Not required for v1 of the funnel app.

## Speed: what three workers buy

| Work | One DualLite today | Four SHC-2000s + app |
|---|---|---|
| Instagram reports for a **batch** of tracks | One Research at a time (~8–20 s) | Up to three reports in flight |
| Waveform analyze | One ffmpeg job | Dedicated Quad, or three jobs at once |
| Wikipedia / essay HTTP | Sequential on the playback CPU | Off the TOSLINK box |
| **One** MusicBrainz lookup | ~1 req/s | Still ~1 req/s if all four share the home WAN IP |
| TOSLINK audio | One optical jack | Still one jack **on playback**. Workers do not make the DAC faster. |

MusicBrainz wants about one request per second **per public IP**. Three workers on one router do not triple that. They **do** triple Wikipedia, local tags, waveform work, and “research three different tracks at once.”

The coordinator should own a **global MusicBrainz token bucket** (1/s) so workers do not 503 the API. Wikipedia can run in parallel. Essay (SpaceXAI) is one HTTPS call per track; put `XAI_API_KEY` only on the research worker(s) in `/data/crypt/xai.env` (never git).

## Fleet rules

- Same CRYPT build on all four (`/data/www` from this repo). Pin a release tag when the farm goes live.
- Stdlib only. No `apt`. No extra daemons beyond `crypt-web`, `crypt-pulse`, `crypt-hostname`.
- Pulse/TOSLINK **enabled** on playback. Pulse can stay installed but unused on workers (or run, but nothing listens to their optical jacks for the main room).
- Playback is the only host the listening room cares about. Workers may still bind :80 for the app and for lab debug.
- Do not merge Savant UIDs. Each chassis keeps its own `001AAE…` hostname pin.
- The funnel app is a **new** codebase (Mac or one more small service). It is not stuffed into DualLite `server.py`.

## Phases

### 0 — Lab mule (now)

CRYPT V1.1.7 on DualLite `.179`. Prove APIs: status, clock, report, lyrics, wave, delete-with-cache. This box is **not** one of the four SHC-2000s.

### 1 — Convert three SHC-2000 workers

Image each Quad correctly (do not clone DualLite eMMC). Install CRYPT. Give each a name and a lab IP. Confirm `GET /api/status` from a laptop. No TOSLINK required on workers.

### 2 — Convert the fourth as playback

Canonical `/data/music`. TOSLINK into the room. EQ and Time Clock live here only. Confirm Playing / EQ while workers are idle.

### 3 — Funnel app v1

- Config: four base URLs.
- Input: now-playing from playback, or a list of `name`s from library.
- Dispatch: report → worker A (round-robin A/B/C if busy); wave → worker B; lyrics → worker C.
- Timeout: report 60 s, wave 150 s (existing DualLite analyze deadline), lyrics 15 s.
- UI: one packet per track (identity, essay, caption, waveform handle, clock).
- Copy caption / copy report as we already do on `/report`.

### 4 — Copy-on-demand for analyze

When worker B lacks the file, the app scp or uploads from playback, then `GET /api/wave`. Delete the temp copy when the job ends if the worker is not a library mirror.

### 5 — Batch Instagram queue

Playlist or folder in → N reports out, three at a time. Persist results in the app (not on DualLite). Playback is never blocked by the queue.

## Success

- Room hears **only** playback TOSLINK. Workers do not glitch paplay when Research runs.
- Three reports in flight return faster than three serial reports on `.179`.
- Delete on playback can be followed by cache drops on workers so no dead `/data/crypt/*` JSON.
- WAN MusicBrainz stays ≤ 1 req/s fleet-wide.
- `.40` / `.178` / `.180` never appear in the fleet list.

## Out of scope

- Shared mounts, SMB, NFS, DLNA, AirPlay, Spotify.
- SSC expanders / Relays (removed in V1.1.2).
- Treating three optical jacks as one DAC.
- Running the funnel app **on** the DualLite S2.

## Open choices (decide when hardware is on the bench)

- Exact lab IPs and hostnames for the four SHC-2000s.
- Whether workers mirror the whole library or only fetch the current/queued tracks.
- Whether playback itself may run Report when idle, or never.
- Whether the funnel app is a local Mac tool first, or another rack host later.

Until those four chassis exist, keep shipping CRYPT on `.179` and treat this file as the target architecture.
