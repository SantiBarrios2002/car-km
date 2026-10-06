# Car km tracker — Pi service

Household car-kilometre log. One Python process on the Raspberry Pi serves a phone-friendly web app
(manual km entry, claiming rides, monthly totals, CSV export) and the API the ESP32 will use later.

## Install on the Pi

```bash
scp -r car-km pi@<pi>:~/           # or git clone
ssh pi@<pi>
cd ~/car-km && chmod +x install.sh && ./install.sh
```

The script creates a venv, installs a systemd unit (`car-km.service`, port 8080), a nightly SQLite backup
cron, and prints the Tailscale URL to share with the family. Logs: `journalctl -u car-km -f`.

## Using it

- Open `http://<pi-tailscale-name>:8080` on a phone with Tailscale. On iOS, Share → *Add to Home Screen* makes it feel like an app.
- First visit asks *¿Quién eres?* — the choice is remembered on that phone.
- **Ajustes** → add the people. Optionally log the real odometer reading once; then rides can be logged by typing the new odometer reading instead of km.
- **Apuntar** → km (or odometer) → Guardar. Rides can be back-dated.
- **Resumen** → month totals per person, unassigned rides highlighted with a *Fui yo* button; CSV button exports the month.
- Language es/en and €/km are in Ajustes.

## Layout

```
app/main.py          FastAPI routes (web app + device API)
app/db.py            SQLite schema and helpers
app/static/          index.html (the whole web app), manifest, icon
data/carkm.db        the database (created on first start)
data/device_token    bearer token the ESP32 must send (created on first start, shown in Ajustes)
data/firmware/       drop firmware.bin + version.txt here for OTA
data/backups/        nightly .backup copies, 60 days kept
```

## Device API (for the ESP32 later)

All device routes need `Authorization: Bearer <token>`.

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/api/rides/batch` | JSON array of rides; idempotent on `(device_id, start_ts)` |
| GET | `/api/fobs` | fob → user map; send `If-None-Match` with the last ETag to get 304 |
| GET | `/api/time` | server unix time, for setting the RTC |
| GET | `/api/firmware` | latest `firmware.bin`; send `X-Version` to get 304 when current |

Ride object:

```json
{"device_id":"meriva-1","start_ts":1759742400,"end_ts":1759744230,"km":23.4,
 "fob_uid":"04A1B2C3D4E580","source":"obd","fw":"0.3.1","end_reason":"brownout"}
```

Interactive docs at `/api/docs`.

## Dev

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --reload --port 8080
```

## Security model

No logins: the app is reachable only on the LAN and over Tailscale, and a household km log doesn't need more.
If you ever expose it beyond that, put it behind Tailscale Serve or a reverse proxy with auth.
