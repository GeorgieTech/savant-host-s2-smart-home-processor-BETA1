# SmartControl expanders

The CRYPT host at **192.168.1.179** drives these expanders over the LAN. They are not the S2’s internal Atmel MCU.

| | SSC-0014 |
|---|---|
| UI id | `ssc14` |
| IP | 192.168.1.136 |
| CLI | telnet `:23`, prompt `SSC>` |
| Relays | 7 (ports 0–6) |
| UID | `001AAE01C4D20021` |
| Firmware family | ATMEL SAMD21 101.1.9.51 |

V1.1 does not drive the SSC-0012 at `192.168.1.138`. Its telnet CLI is tcpwrapped (accept then close), so relays cannot be toggled.

## Commands the host is allowed to send

- `show` — identity + `Relay Status:` + cycle counts
- `relay on N` / `relay off N` — `N` is 0–6

The client will refuse anything else (`ip`, `mac`, `reset`, `gpio`, `bl`, …). A bare `ip` with no argument clears the stored address in EEPROM.

## Web API (on the S2)

| Method | Path | Body |
|---|---|---|
| GET | `/api/ssc` | `?fresh=1` to skip the short cache; returns `{devices:[…]}` |
| GET | `/api/ssc/ssc14` | one expander |
| POST | `/api/ssc/ssc14/relay` | `{"relay":1,"on":true}` or `{"port":0,"action":"off"}` |
| POST | `/api/ssc/ssc14/relays` | `{"on":false}` — all relays on that box |

UI: [http://192.168.1.179/controls](http://192.168.1.179/controls)

## Discovery / fake host uplink

CRYPT binds **UDP 12004** and sends the Savant host probe `02 50 04` (same 3-byte packet a real host uses). Expanders announce themselves with a 29-byte `1c 50 04` + UID beacon from port 12005.

After a beacon from a configured expander, CRYPT unicasts probe + `03 50 04 01` (uplink-on) to that IP. That is a minimal AVD fake, not full PeripheralDeviceManager. Unknown beacons (including the 0012) are ignored.
