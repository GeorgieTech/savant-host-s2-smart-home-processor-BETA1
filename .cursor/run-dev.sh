#!/usr/bin/env bash
# Dev launcher for the CRYPT S2 web UI inside a Cloud Agent VM.
#
# The production host (SHR-S2) serves on :80 out of /data with systemd + a
# system PulseAudio instance wired to the TOSLINK sink. A cloud VM has neither
# port-80 privileges, a /data partition, nor an audio device, so here we serve
# on a high port out of a writable state dir under $HOME. Everything except
# real TOSLINK audio output (which needs the physical S/PDIF sink) works.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE="${CRYPT_DEV_HOME:-$HOME/.crypt}"

mkdir -p "$STATE/music" "$STATE/state" "$STATE/waves"

export WEBUI_PORT="${WEBUI_PORT:-8080}"
export MUSIC_DIR="${MUSIC_DIR:-$STATE/music}"
export CRYPT_STATE="${CRYPT_STATE:-$STATE/state}"
export CRYPT_WAVES="${CRYPT_WAVES:-$STATE/waves}"
export EQ_FILE="${EQ_FILE:-$STATE/eq.json}"
export CLOCK_FILE="${CLOCK_FILE:-$STATE/clock.json}"
export PROGRESS_FILE="${PROGRESS_FILE:-$STATE/ff.progress}"

cd "$HERE/host-webui"
exec python3 server.py
