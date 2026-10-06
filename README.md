# car-km — household car kilometre tracker

Logs every ride of the family car automatically and works out who drove how many kilometres each month.

A small device in the car reads distance from the OBD-II port over Bluetooth and records each ride. Tapping an NFC fob says who is driving. Rides are uploaded over WiFi to a Raspberry Pi at home, and the family uses a phone web app to see monthly totals, assign untapped rides ("that was me") and export CSV.

```
 car                                              home
┌──────────────────────────────────────┐        ┌───────────────────────────────┐
│ Vgate iCar Pro ─BLE─► ESP32-S3 module │  WiFi  │ Raspberry Pi                  │
│ (OBD-II speed)        + carrier PCB   │ ─────► │ FastAPI + SQLite (app/)       │
│ PN532 NFC ─I²C─►      (supercap hold- │  HTTP  │ web app at /, device API      │
│ (who drives)           up, 5 V input) │        │ at /api/  ◄── family phones   │
└──────────────────────────────────────┘        └───────────────────────────────┘
```

## Status

| Part | Where | State |
| --- | --- | --- |
| Pi service + web app | `app/` | **In use** on the family Pi. |
| Carrier PCB | `hardware/carrier/` | Schematic done (ERC clean); first-pass board placed, autorouted and passing DRC. **Not reviewed, not ordered.** |
| Car device firmware | `firmware/` | Not started. Conventions are already fixed in `CLAUDE.md`. |

### Next step: pre-order checks for the carrier PCB

None of these have been done yet. They come before anything is sent to a fab; details and commands are in [`hardware/README.md`](hardware/README.md#next-step-pre-order-checks).

1. **Review the board in KiCad**: placement, power trace widths, the autorouted tracks.
2. **Check the 3D fit** against Waveshare's STEP model (stack height, standoffs, cable paths).
3. **Re-run ERC and DRC** after any changes.
4. **Export the Gerber and drill files** and inspect them in a Gerber viewer.

## Repository layout

```
app/                  Pi service: FastAPI + SQLite, web app and device API
  main.py             all routes (web app + device API), sections marked with # ----
  db.py               schema and SQLite helpers
  static/index.html   the whole web app: one file, vanilla JS, Spanish/English
install.sh            Pi install: venv, systemd unit, nightly backup cron (safe to re-run)
car-km.service        systemd unit template used by install.sh
hardware/             car device hardware: Waveshare module + custom carrier PCB
  README.md           hardware design document: start here for the electronics
  carrier/            KiCad 10 project (schematic + PCB)
  bom-rev2.csv        bill of materials
  vendor/             Waveshare schematic and mechanical drawing (PDF)
CLAUDE.md             working notes for Claude Code and contributors: conventions, hard rules, hardware facts
```

`data/` (database, device token, firmware images, backups) is created at runtime and is not committed.

## Pi service

### Install on the Pi

```bash
git clone <this repo> ~/car-km
cd ~/car-km && chmod +x install.sh && ./install.sh
```

The script creates a venv, installs a systemd unit (`car-km.service`, port 8080) and a nightly SQLite backup cron, then prints the Tailscale URL to share with the family. Logs: `journalctl -u car-km -f`.

### Using it

- Open `http://<pi-tailscale-name>:8080` on a phone (see *Links*). On iOS, Share → *Add to Home Screen* makes it feel like an app.
- The first visit asks *¿Quién eres?*; the answer is remembered on that phone.
- **Ajustes**: add the people. Optionally log the real odometer reading once; after that a ride can be logged by typing the new odometer reading instead of km.
- **Apuntar**: km (or odometer) → Guardar. Rides can be back-dated.
- **Resumen**: monthly totals per person, with unassigned rides highlighted and a *Fui yo* button; the CSV button exports the month.
- Language (es/en) and €/km are set in Ajustes.

### Links (family setup)

| Where | URL |
| --- | --- |
| Anywhere, phone with Tailscale | http://iot-hub.tail8fe499.ts.net:8080 |
| Same, by Tailscale IP (if the name doesn't resolve) | http://100.102.81.29:8080 |
| Home WiFi, no Tailscale needed | http://192.168.1.140:8080 |
| API docs | http://iot-hub.tail8fe499.ts.net:8080/api/docs |

### Giving family members access (Tailscale)

At home the LAN link works for anyone on the WiFi. From outside, each person needs Tailscale. Prefer **sharing the Pi** over inviting people into the tailnet: someone you share with can reach only `iot-hub`, not your other devices.

1. In https://login.tailscale.com/admin/machines, open the **⋯** menu on `iot-hub` → **Share…** and copy the invite link.
2. Send it to the person. They install Tailscale (iOS/Android), sign in with their own Google/Apple/Microsoft account and open the link. They get their own free tailnet with `iot-hub` in it.
3. On their phone: Tailscale on → open the link above → Share / ⋮ → *Add to Home Screen*.
4. To revoke: admin console → **Machines** → `iot-hub` → **Share…** (or the **Sharing** tab) and remove them.

Alternatively, **Users → Invite users** makes them full tailnet members. That's simpler when they have many devices, but by default they can then reach every machine, so restrict them in **Access controls**.

### Device API (used by the car device)

| Method | Path | Auth | Purpose |
| --- | --- | --- | --- |
| POST | `/api/rides/batch` | bearer | JSON array of rides; idempotent on `(device_id, start_ts)` |
| GET | `/api/fobs` | none (also used by the web app) | fob → user map; send `If-None-Match` with the last ETag to get a 304 |
| GET | `/api/time` | bearer | server unix time, for setting the RTC |
| GET | `/api/firmware` | bearer | latest `firmware.bin`; send `X-Version` to get a 304 when current |

Bearer = `Authorization: Bearer <token>`. The token is in `data/device_token`, created on first start and shown in Ajustes. OTA images go in `data/firmware/` (`firmware.bin` + `version.txt`).

Ride object:

```json
{"device_id":"meriva-1","start_ts":1759742400,"end_ts":1759744230,"km":23.4,
 "fob_uid":"04A1B2C3D4E580","source":"obd","fw":"0.3.1","end_reason":"brownout"}
```

Interactive docs at `/api/docs`.

### Development

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --reload --port 8081
```

Port 8081 lets the dev server run alongside the live service on 8080. Run from the repo root: the default paths under `data/` are relative to the working directory.

### Security model

There are no logins: the app is reachable only on the home LAN and over Tailscale, and a household km log doesn't need more. The device API uses a bearer token. Don't expose port 8080 to the internet; if wider access is ever needed, put it behind Tailscale Serve or a reverse proxy with authentication.
