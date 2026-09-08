# Future plan — four SHC-2000 CRYPT engines

Status: **plan only**. Not built. Live CRYPT V1.1.7 stays on the DualLite SHR-S2 at **192.168.1.179**.

Goal: three SHC-2000 hosts are **library + job workers**. A fourth SHC-2000 is the **TOSLINK playback cache** — it lists the whole fleet library, but only keeps a few files on its own eMMC while they are about to play, playing, or just played. A **separate application** (not this DualLite UI) sits in front, owns the fleet catalog, copies bytes when needed, fans research jobs out, and consumes the JSON those four hosts produce.

This is a job farm plus a sharded disk on the lab LAN. It is not Kubernetes, not Savant clustering, not one shared TOSLINK, not streaming, and not NAS/DLNA.

Do **not** use **192.168.1.40** (Carrillos Resident), **192.168.1.178** (Gigawatt), or **192.168.1.180** (Giggwatt Beta1). Do not spoof Carrillos UID `001AAE1C6F5F0000`.

## Picture

```
Separate app we build  (phone / Mac / future CRYPT console)
        │  fleet catalog + HTTP JSON
        ▼
┌────────────────────────────────────────────────────────┐
│  Playback SHC-2000  — TOSLINK, Playing, EQ, Time Clock     │
│  Hot cache only: now + next + last in /data/music          │
│  Source of truth for “what is audible right now”           │
└────────────────────────────────────────────────────────┘
        ▲
        │  copy-then-play  (never stream into ffmpeg / Pulse)
        │  jobs / results  (same CRYPT APIs)
        │
┌────────────────┬────────────────┬────────────────┐
│ Worker A      │ Worker B      │ Worker C      │
│ SHC-2000      │ SHC-2000      │ SHC-2000      │
│ shard of      │ shard of      │ shard of      │
│ /data/music   │ /data/music   │ /data/music   │
│ Report/essay  │ Wave/beat     │ Lyrics +      │
│ research      │ analyze       │ overflow      │
│ (full CRYPT)  │ (full CRYPT)  │ (full CRYPT)  │
└────────────────┴────────────────┴────────────────┘
```

Each of the four hosts runs **the same** CRYPT web UI (`/data/www`, port 80, Python 3.8 stdlib). They do not share `/data`, Pulse, or RAM. The new app is the only piece that knows the fleet.

## Why playback cannot just “play a file on worker B”

`HostPlayer.play()` only opens a real file under **this** host’s `/data/music`, then runs local `ffmpeg` → `paplay` → Pulse → `imx-spdif`. There is no URL/stream path.

Streaming a worker file into playback ffmpeg is rejected:

- Extra daemon / protocol on a Yocto image (stdlib only, no apt).
- LAN jitter would fight Host Time Clock (PLL already locks to **this** box’s paplay/Pulse latency).
- The room hears **playback’s** optical jack only. Playing on worker B’s TOSLINK is the wrong DAC.

Workaround: **copy, then play**. Worker B keeps the home copy. Playback gets a temporary local copy, plays that, then evicts it from the hot cache.

## Hardware

| Role | Chassis | Why |
|---|---|---|
| Playback | SHC-2000 / SHC-S2 Quad (2 GB, 4 cores) | TOSLINK to the room. Hot cache only. Keep Research off this box while music is up. |
| Worker A / B / C | Same SHC-2000 class | Quad + 2 GB is the engine **and** the shelf. DualLite 1 GB is the current lab mule, not the farm. |

The live host at `.179` is an **SHR-S2-00 DualLite**. Do **not** `dd` that image onto an SHC-2000 (`/data` partition layout differs: DualLite `mmcblk0p2` vs Quad `p3`). Convert each SHC-2000 the same way we converted `.179`, then install CRYPT from this repo.

Assign lab IPs later. Until then use names: `crypt-play`, `crypt-work-a`, `crypt-work-b`, `crypt-work-c`. Keep them on `192.168.1.0/24` with this project’s existing “never .40 / .178 / .180” rule.

## Library model — shard on workers, cache on playback

Canonical audio files live on the **workers**, sharded so each `name` has **one owner**. That is how three eMMC shelves become more space than one box. Do **not** copy the whole library onto every worker; that spends three disks on one collection.

Playback `/data/music` is **not** the archive. It is a hot cache of at most:

- **now** — the file ffmpeg is decoding
- **next** (and optionally **next+1**) — already copied before the current track ends
- **last** — so Prev / play-again does not re-copy

Playback’s Library page lists the **fleet catalog** (union of all workers), not a scan of its own `/data/music`. A row can be in the library and still absent from playback disk until play is requested.

### Fleet catalog row

| Field | Why |
|---|---|
| `name` | Stable id. Same string on every host. |
| `owner` | `crypt-work-a` / `b` / `c` — home copy lives here |
| `size` + hash | Two different files must not share a `name` |
| tags | artist / title / album / year / genre — Library, Report, Lyrics without pulling bytes |
| `present_on_play` | Whether playback currently has a hot copy |
| `available` | Owner is up; otherwise show the row as unplayable, not a ghost |

Today `GET /api/library` is a local scan. The funnel app (or a later CRYPT endpoint) is the source of truth for the union view. Playback `play_name()` still requires the file to exist locally **after** the copy lands and the catalog refresh sees it.

### Copy-then-play

1. User picks a row owned by worker B.
2. If playback already has that `name` + matching size/hash in the hot cache, skip the copy.
3. Else **push or pull** B → playback: existing `GET` media on B, existing `POST` upload on playback (400 MB cap), or `scp`. No mount.
4. Refresh playback catalog. Only then `POST /api/play` `{name}` **on playback**.
5. While it plays, prefetch queue item +1 (and +2 if you want a safer gap).
6. On end: start the prefetched next file, **then** evict the previous file if the cache is full. Never unlink `self.media` while ffmpeg/paplay still has that path (EQ rebuild and seek re-open it).

Phone / laptop uploads land on the **least-full worker**, then the catalog row appears on playback. Do not park new FLACs on the TOSLINK box as the home copy.

Delete hits the **owner worker** first, then drops any hot copy on playback and caches on every host that has that `name` (`POST /api/delete` or a future `/api/drop-cache`). No dead `/data/crypt/*` JSON.

### Job files vs play files

| Work | Needs the audio file on that host? |
|---|---|
| TOSLINK play, seek, EQ rebuild | **Yes, on playback**, only while it is in the hot cache |
| Wave / beat analyze | **Yes, on worker B** (owner already has it; no extra copy if B owns the track) |
| Report / essay / MusicBrainz / Wikipedia | **No** — tags from the catalog are enough |
| Lyrics / karaoke timing | Sidecar / cache on C; audio file only if C must decode. Clock still comes from playback |

If wave runs on B and B is the owner, there is nothing to copy. If a non-owner must decode, copy onto that worker for the job, then delete the temp copy when the job ends.

## What the separate app consumes

The funnel app does not re-implement ffmpeg, Pulse, Wikipedia, or EQ. It calls the APIs we already ship:

| Need | API | Prefer host |
|---|---|---|
| What TOSLINK is emitting | `GET /api/status`, `GET /api/clock` | **Playback** |
| Transport | `POST /api/play` `{name,start}`, pause / resume / next / seek / volume / EQ | **Playback** (after the hot copy exists) |
| Fleet library | union of worker `GET /api/library` + catalog | **App** (not playback’s local scan) |
| Pull bytes for the cache | `GET` media / `POST` upload | Owner worker → playback |
| Track report + meaning essay | `POST /api/report` `{name, fetch:true}` | **Worker A** (overflow B/C) |
| Lyrics / karaoke | `GET` or `POST /api/lyrics` | **Worker C** |
| 3-band waveform + beat grid | `GET /api/wave?name=` | **Worker B** |
| EQ curve | `GET` / `POST /api/eq` | **Playback** (it is in the TOSLINK chain) |

## Data movement (no NAS, no stream)

Hard rule: no AirPlay, Spotify, DLNA, NAS, NFS, SMB, or ffmpeg HTTP input.

1. Home copy of each track lives on **exactly one worker** `/data/music`.
2. Playback receives a **copy** of now / next / last only.
3. Research workers get `{artist, title, album, year, genre}` from the app, plus optional sidecar `.lrc` bytes if we add a small upload later.
4. Caches stay **per host** and **attached to the track name**, same as V1.1.3–V1.1.7:
   - `/data/crypt/waves`
   - `/data/crypt/lyrics`
   - `/data/crypt/reports`
5. Waveform **JSON** may stay on B (or be copied to the app). Playback does not need to keep the FLAC after eviction in order to show a cached wave.

Optional later: a `CRYPT_PEERS` list so playback can fan `drop_name` itself. Not required for v1 of the funnel app.

## Speed: what three workers buy

| Work | One DualLite today | Four SHC-2000s + app |
|---|---|---|
| Library size | One DualLite eMMC | Up to three worker eMMCs (sharded, not mirrored) |
| Instagram reports for a **batch** of tracks | One Research at a time (~8–20 s) | Up to three reports in flight |
| Waveform analyze | One ffmpeg job | Dedicated Quad; owner already has the file |
| Wikipedia / essay HTTP | Sequential on the playback CPU | Off the TOSLINK box |
| First play of a cold track | Instant (file already local) | LAN copy, then play. Prefetch hides this for queue item +1 |
| **One** MusicBrainz lookup | ~1 req/s | Still ~1 req/s if all four share the home WAN IP |
| TOSLINK audio | One optical jack | Still one jack **on playback**. Workers do not make the DAC faster. |

MusicBrainz wants about one request per second **per public IP**. Three workers on one router do not triple that. They **do** triple Wikipedia, local tags, waveform work, and “research three different tracks at once.” They also triple **shelf space** when files are sharded.

The coordinator should own a **global MusicBrainz token bucket** (1/s) so workers do not 503 the API. Wikipedia can run in parallel. Essay (SpaceXAI) is one HTTPS call per track; put `XAI_API_KEY` only on the research worker(s) in `/data/crypt/xai.env` (never git).

## Fleet rules

- Same CRYPT build on all four (`/data/www` from this repo). Pin a release tag when the farm goes live.
- Stdlib only. No `apt`. No extra daemons beyond `crypt-web`, `crypt-pulse`, `crypt-hostname`.
- Pulse/TOSLINK **enabled** on playback. Pulse can stay installed but unused on workers (or run, but nothing listens to their optical jacks for the main room).
- Playback is the only host the listening room cares about. Workers may still bind :80 for the app and for lab debug.
- Do not merge Savant UIDs. Each chassis keeps its own `001AAE…` hostname pin.
- The funnel app is a **new** codebase (Mac or one more small service). It is not stuffed into DualLite `server.py`.
- Never point playback ffmpeg at `http://crypt-work-b/…`. Copy first.

## Phases

### 0 — Lab mule (now)

CRYPT V1.1.7 on DualLite `.179`. Prove APIs: status, clock, report, lyrics, wave, upload, media GET, delete-with-cache. This box is **not** one of the four SHC-2000s.

### 1 — Convert three SHC-2000 workers

Image each Quad correctly (do not clone DualLite eMMC). Install CRYPT. Give each a name and a lab IP. Confirm `GET /api/status` from a laptop. No TOSLINK required on workers. Seed each worker with a **distinct** shard of test files.

### 2 — Convert the fourth as playback

Empty-ish `/data/music` (cache, not archive). TOSLINK into the room. EQ and Time Clock live here only. Confirm Playing / EQ with a file that was uploaded or copied onto this box first.

### 3 — Funnel app v1 (catalog + copy-then-play)

- Config: four base URLs.
- Build the fleet catalog from the three worker libraries.
- Play path: ensure hot copy on playback → `POST /api/play` → prefetch next.
- Evict last-minus-one when cache holds now + next + last.
- Dispatch: report → worker A (round-robin A/B/C if busy); wave → worker B (skip copy if B owns the file); lyrics → worker C.
- Timeout: report 60 s, wave 150 s (existing DualLite analyze deadline), lyrics 15 s, copy bounded by file size / LAN.
- UI: one packet per track (identity, owner, essay, caption, waveform handle, clock, `present_on_play`).
- If a worker is down, mark its rows unavailable.

### 4 — Placement and delete fan-out

New uploads → least-full worker. Deletes → owner + playback hot copy + caches on A/B/C. Optional `CRYPT_PEERS` later.

### 5 — Batch Instagram queue

Playlist or folder in → N reports out, three at a time. Persist results in the app (not on DualLite). Playback is never blocked by the queue. Research does not pull FLACs onto A.

## Success

- Room hears **only** playback TOSLINK. Workers do not glitch paplay when Research runs.
- Playback `/data/music` stays a small hot cache, not a third copy of the whole library.
- Library UI on the app shows every sharded track; a cold play copies from the owner, then TOSLINK starts.
- Queue advances without a hole: next file is on playback before `on_end`.
- Three reports in flight return faster than three serial reports on `.179`.
- Delete on the owner is followed by cache drops everywhere so no dead `/data/crypt/*` JSON.
- WAN MusicBrainz stays ≤ 1 req/s fleet-wide.
- `.40` / `.178` / `.180` never appear in the fleet list.

## Out of scope

- Shared mounts, SMB, NFS, DLNA, AirPlay, Spotify.
- ffmpeg / Pulse streaming from one host to another.
- SSC expanders / Relays (removed in V1.1.2).
- Treating three optical jacks as one DAC.
- Mirroring the full library onto every worker.
- Running the funnel app **on** the DualLite S2.

## Open choices (decide when hardware is on the bench)

- Exact lab IPs and hostnames for the four SHC-2000s.
- Shard rule (least-free space vs hash-mod-3 vs manual folders).
- Whether to keep a second replica of each file on another worker later (space vs a down owner).
- Whether playback itself may run Report when idle, or never.
- Whether the funnel app is a local Mac tool first, or another rack host later.

Until those four chassis exist, keep shipping CRYPT on `.179` and treat this file as the target architecture.
