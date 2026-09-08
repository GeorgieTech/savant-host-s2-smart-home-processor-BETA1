# SmartControl expanders

The CRYPT host at **192.168.1.179** drives these expanders over the LAN. They are not the S2’s internal Atmel MCU.

| | SSC-0014 | SSC-0012 |
|---|---|---|
| UI id | `ssc14` | `ssc12` |
| IP | 192.168.1.136 | 192.168.1.138 |
| CLI | telnet `:23`, prompt `SSC>` | same CLI in firmware (`Relay Status: %d %d`) |
| Relays | 7 (ports 0–6) | 2 (ports 0–1) |
| UID (0014) | `001AAE01C4D20021` | MAC `00:1A:AE:13:DF:60` |
| Firmware family | ATMEL SAMD21 101.1.9.51 | ATMEL SAMD21 100.1.9.50 |

## Commands the host is allowed to send

- `show` — identity + `Relay Status:` + cycle counts
- `relay on N` / `relay off N` — `N` is 0–6 on the 14, 0–1 on the 12

The client will refuse anything else (`ip`, `mac`, `reset`, `gpio`, `bl`, …). A bare `ip` with no argument clears the stored address in EEPROM.

## Web API (on the S2)

| Method | Path | Body |
|---|---|---|
| GET | `/api/ssc` | `?fresh=1` to skip the short cache; returns `{devices:[…]}` |
| GET | `/api/ssc/ssc14` | one expander |
| POST | `/api/ssc/ssc14/relay` | `{"relay":1,"on":true}` or `{"port":0,"action":"off"}` |
| POST | `/api/ssc/ssc12/relays` | `{"on":false}` — all relays on that box |

UI: [http://192.168.1.179/controls](http://192.168.1.179/controls)

## Discovery / fake host uplink

CRYPT binds **UDP 12004** and sends the Savant host probe `02 50 04` (same 3-byte packet a real host uses). Expanders announce themselves with a 29-byte `1c 50 04` + UID beacon from port 12005.

After a beacon, CRYPT unicasts probe + `03 50 04 01` (uplink-on) to the expander. That is a minimal AVD fake, not full PeripheralDeviceManager.

## SSC-0012 telnet note

Port 23 is open but currently **tcpwrapped** (accept then close). Relays on the 12 stay disabled until CLI comes up. UDP beacons still mark it **Seen**. A power cycle (not a 5-second reset) is the first fix to try for CLI.
