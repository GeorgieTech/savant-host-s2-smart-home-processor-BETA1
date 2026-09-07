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

## SSC-0012 telnet note

Port 23 is open but currently **tcpwrapped** (accept then close) from both this Mac and the S2. Firmware still contains the same `relay on` / `relay off` CLI. If the Relays page shows the 12 offline, power-cycle the expander (do not hold reset 5 seconds — that clears network settings) and reload the page.
