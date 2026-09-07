# SSC-0014 — SmartControl 14

The CRYPT host at **192.168.1.179** drives this expander over the LAN. It is not the S2’s internal Atmel MCU.

| Field | Value |
|---|---|
| IP | 192.168.1.136 |
| CLI | telnet `:23`, prompt `SSC>`, no password |
| UID | `001AAE01C4D20021` |
| Serial | `41037014` |
| Part number | `068-0443-10` |
| Firmware | `1.5:1` (bootloader `1.1:1`) |
| Relays | 7 dry contacts, CLI ports **0–6** (UI relays **1–7**) |

## Commands the host is allowed to send

- `show` — identity + `Relay Status:` + cycle counts
- `relay on N` / `relay off N` — `N` is 0–6

The client will refuse anything else (`ip`, `mac`, `reset`, `gpio`, `bl`, …). A bare `ip` with no argument clears the stored address in EEPROM.

## Web API (on the S2)

| Method | Path | Body |
|---|---|---|
| GET | `/api/ssc` | `?fresh=1` to skip the short cache |
| POST | `/api/ssc/relay` | `{"relay":1,"on":true}` or `{"port":0,"action":"off"}` |
| POST | `/api/ssc/relays` | `{"on":false}` — all seven in order |

UI: [http://192.168.1.179/controls](http://192.168.1.179/controls)
