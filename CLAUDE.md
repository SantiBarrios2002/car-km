# car-km — household car kilometre tracker (Pi service, car device firmware, hardware)

## What this is
Three parts:
- **Pi service** (`app/`): one Python process (FastAPI + SQLite) that serves
  - a phone-first web app at `/` for the family (log rides manually, claim unassigned rides, monthly totals, CSV export), and
  - the device API under `/api/` that the car device uses.
- **Car device firmware** (`firmware/`, not yet written): PlatformIO + ESP-IDF.
- **Hardware design** (`hardware/`): a Waveshare ESP32-S3-Touch-LCD-2.8 on a custom carrier PCB, a PN532 NFC reader over I²C for the fob, and a Vgate iCar Pro BLE OBD-II dongle for distance.

Rides are logged automatically; the fob tap only sets *who* drove; untapped rides are uploaded as unassigned and claimed in the web app.

The design spec lives outside this repo (Claude doc "Car km tracker – build spec"; hardware in tab "Rev 2: Waveshare + carrier PCB").

## Layout
```
app/main.py            all routes; web app + device API in one file, sections marked with # ----
app/db.py              schema (idempotent CREATE IF NOT EXISTS), connect() context manager, settings helpers
app/static/index.html  the whole web app: single file, vanilla JS, no build step, es/en strings in I18N
app/static/manifest.webmanifest, icon.svg   PWA bits
install.sh             venv + systemd unit + nightly backup cron; safe to re-run
car-km.service         systemd template; install.sh substitutes __DIR__ and __USER__
data/                  runtime state, not committed: carkm.db, device_token, firmware/, backups/
hardware/README.md     Rev 2 design: module facts, power design, carrier nets, connectors, layout, bench checks
hardware/bom-rev2.csv  bill of materials
hardware/carrier-netlist.net   hand-written KiCad netlist for the carrier PCB (the schematic spec)
hardware/vendor/       Waveshare schematic + 2D drawing PDFs (STEP not committed, 20 MB)
firmware/              planned: PlatformIO + ESP-IDF project for the car device (not created yet)
```

## Running
- Production: `sudo systemctl {status,restart} car-km`, logs `journalctl -u car-km -f`, port 8080, bound 0.0.0.0 (LAN + Tailscale).
- Dev: `.venv/bin/uvicorn app.main:app --reload --port 8081` (different port so the live service keeps running).
- Env vars (set by the unit): `CARKM_DB`, `CARKM_TOKEN_FILE`, `CARKM_FIRMWARE`. Defaults are relative to CWD, so always run from the repo root.
- Interactive API docs: `/api/docs`.

## Conventions
- Python 3.11+, type hints, no ORM: plain `sqlite3` with `db.connect()` and the `rows()/one()` helpers. Every request opens its own connection.
- Timestamps are unix seconds (int) everywhere. Month filters use `_month_bounds("YYYY-MM")` in local time.
- `km` is what was measured/entered; `km_corrected` is `km * obd_factor` for OBD rides only; summaries always use `COALESCE(km_corrected, km)` (`km_final` in `_ride_select()`).
- Rides from the device are idempotent on `(device_id, start_ts)` via a partial unique index that excludes `device_id='manual'`. Don't make it a plain UNIQUE again; two manual entries in the same second broke that.
- Device routes depend on `require_device` (bearer token from `data/device_token`). Web-app routes have no auth on purpose: reachability is LAN + Tailscale only. Do not add logins unless asked.
- Schema changes: add to `SCHEMA` in `db.py` as `CREATE ... IF NOT EXISTS` / `ALTER TABLE` guarded by a `PRAGMA table_info` check. There is no migration framework and the DB has real family data; back it up (`sqlite3 data/carkm.db ".backup x.db"`) before anything destructive.
- Frontend: keep it one file, no framework, no bundler. New user-facing strings go in both `I18N.es` and `I18N.en`. Default language is Spanish. Test at 390 px wide.
- Keep `README.md` in step when routes or install steps change.

## Hardware facts (verified from Waveshare files, 2026-10-06)
- Module J8 = JST SH 1.0 mm 12-pin: 1 GND, 2 USB_5V, 3 D−/IO19, 4 D+/IO20, 5 GND, 6 3V3, 7 SCL/IO10, 8 SDA/IO11, 9 TXD/IO43, 10 RXD/IO44, 11 GPIO18, 12 GPIO15.
- Power path: USB_5V → D3 Schottky → VCC → ME6217 3.3 V LDO. Battery → Q1 (on only when IO7 BAT_Control is high) → Q2 (on only when USB_5V absent) → VCC. Charger ETA6098, 2 A, 4.2 V CV; battery connector J1 PH1.25.
- Supercap bank 2 × 5 F / 2.7 V in series lives on the module's battery connector; the module charges it. Hold-up ≈ 5–7 s with backlight off (charger only tops up after a 160 mV drop, so the bank can sit at ~4.04 V).
- GPIO: IO7 BAT_Control (output, HIGH at boot, never low); IO8 BAT_ADC (Vbat = 3 × Vadc); IO15 PWR_SENSE (input, falling edge = car power lost; needs the carrier supervisor fix: the module's R30 10 k pull-up to 3V3 keeps IO15 high through the current 100 k / 47 k divider, car on or off); IO18 NFC_IRQ; IO5 LCD backlight; I²C IO10 SCL / IO11 SDA shared by PN532 0x24, PCF85063 RTC 0x51, QMI8658 IMU 0x6B. IO6 Key_BAT unused.
- Mechanical: module PCB 69.00 × 49.90 mm, holes Ø2.7 on a 60.00 × 41.00 grid 4.50 mm from the edges, 6 mm of parts on the back, antenna top-left. Carrier copies the outline and holes; 8 mm standoffs.
- Full net list, connectors and the fallback power configuration: `hardware/README.md`.

## Firmware conventions (for when firmware/ is created)
- PlatformIO env with `framework = espidf`, board `esp32-s3-devkitc-1` overridden to 16 MB flash + OPI PSRAM, custom `partitions.csv` with two OTA slots.
- BLE: NimBLE, central only.
- Components: `obd`, `rfid` (PN532/I²C), `clock` (PCF85063 + SNTP), `store` (NVS `ride/live` checkpoint + LittleFS queue), `sync` (WiFi + HTTP to the Pi), `ui` (LVGL 9, Waveshare BSP for ST7789 + CST328), `power` (IO15 ISR).
- Hard rules:
  - First line of `app_main` sets IO7 high.
  - Brownout handler order: backlight off → stop BLE → write ride → halt. In the halt loop, if IO15 goes high again (ignition back while the caps still hold the board, so no power-on reset), call `esp_restart()`.
  - Distance = sum of speed (PID 0x0D) / 3600 at 1 Hz; drop reads > 200 km/h or after a 5 s gap.
  - Checkpoint `ride/live` every 10 s.
  - Device posts to `POST /api/rides/batch` with the bearer token from `data/device_token`; idempotent on `(device_id, start_ts)`.
- Device-facing API shapes in `app/main.py` must not change without updating this section.

## Testing
No test suite yet. Smoke-test by starting the dev server on :8081 and hitting the routes with curl (users → manual ride → odometer ride → device batch with and without token → summary → export). Add `tests/` with pytest + `httpx.AsyncClient` if the backend grows.

## Things not to do
- Don't commit `data/` or `.venv/`.
- Don't change the device API shapes (`/api/rides/batch` body, `/api/fobs` ETag behaviour, `/api/firmware` `X-Version` header) without flagging it: the firmware will be written against them.
- Don't expose port 8080 to the internet; if remote access beyond Tailscale is ever wanted, use Tailscale Serve or a reverse proxy with auth.
- Don't connect a LiPo to the module: supercaps only (car interior temperatures).
- Don't populate R3/D2 on the carrier unless the fallback power configuration is chosen.
- Don't change the J8 pin mapping assumptions without re-reading `hardware/vendor/ESP32-S3-Touch-LCD-2.8_schematic.pdf`.
