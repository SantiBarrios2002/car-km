# car-km — household car kilometre tracker (Pi service, car device firmware, hardware)

## What this is
Three parts:
- **Pi service** (`app/`): one Python process (FastAPI + SQLite) that serves
  - a phone-first web app at `/` for the family (log rides manually, claim unassigned rides, monthly totals, CSV export), and
  - the device API under `/api/` that the car device uses.
- **Car device hardware** (`hardware/`): a Waveshare ESP32-S3-Touch-LCD-2.8 on a custom carrier PCB, a PN532 NFC reader over I²C for the fob, and a Vgate iCar Pro BLE OBD-II dongle for distance.
- **Car device firmware** (`firmware/`, not started): PlatformIO + ESP-IDF.

Rides are logged automatically; the fob tap only sets *who* drove. Untapped rides are uploaded as unassigned and claimed in the web app.

`README.md` is the overview for people; `hardware/README.md` is the hardware design document. The original design discussion lives in a private doc outside the repo ("Car km tracker – build spec"). Everything needed to work on the project is in this repo.

## Status and next step
- Pi service: in use with real family data.
- Carrier PCB: the schematic is done and ERC clean; the first-pass board is placed, autorouted and DRC clean. **Next step: the four pre-order checks in `hardware/README.md` → "Next step: pre-order checks"** (review in KiCad, 3D fit, re-run ERC/DRC, export and inspect Gerbers). None has been done yet. Nothing is ordered.
- Firmware: not started.

## Layout
```
app/main.py            all routes; web app + device API in one file, sections marked with # ----
app/db.py              schema (idempotent CREATE IF NOT EXISTS), connect() context manager, settings helpers
app/static/index.html  the whole web app: single file, vanilla JS, no build step, es/en strings in I18N
app/static/manifest.webmanifest, icon.svg   PWA bits
install.sh             venv + systemd unit + nightly backup cron; safe to re-run
car-km.service         systemd template; install.sh substitutes __DIR__ and __USER__
data/                  runtime state, not committed: carkm.db, device_token, firmware/, backups/
hardware/README.md     hardware design doc: status + pre-order checks, module facts, carrier design, nets, connectors, PCB layout, firmware hooks
hardware/bom-rev2.csv  bill of materials
hardware/carrier/      KiCad 10 project: carrier.kicad_sch (source of truth for nets), carrier.kicad_pcb, carrier.kicad_pro (net classes, rules)
hardware/vendor/       Waveshare schematic + 2D drawing PDFs (STEP not committed, 20 MB)
```

## Running
- Production: `sudo systemctl {status,restart} car-km`, logs `journalctl -u car-km -f`, port 8080, bound 0.0.0.0 (LAN + Tailscale).
- Dev: `.venv/bin/uvicorn app.main:app --reload --port 8081` (a different port, so the live service keeps running).
- Env vars (set by the unit): `CARKM_DB`, `CARKM_TOKEN_FILE`, `CARKM_FIRMWARE`. Defaults are relative to CWD, so always run from the repo root.
- Interactive API docs: `/api/docs`.

## Conventions (Pi service)
- Python 3.11+, type hints, no ORM: plain `sqlite3` with `db.connect()` and the `rows()/one()` helpers. Every request opens its own connection.
- Timestamps are unix seconds (int) everywhere. Month filters use `_month_bounds("YYYY-MM")` in local time.
- `km` is what was measured or entered; `km_corrected` is `km * obd_factor` for OBD rides only; summaries always use `COALESCE(km_corrected, km)` (`km_final` in `_ride_select()`).
- Device rides are idempotent on `(device_id, start_ts)` via a partial unique index that excludes `device_id='manual'`. Don't make it a plain UNIQUE again: two manual entries in the same second broke that.
- Device routes depend on `require_device` (bearer token from `data/device_token`). `/api/fobs` is open because the web app uses it too. Web-app routes have no auth on purpose: reachability is LAN + Tailscale only. Don't add logins unless asked.
- Schema changes: add to `SCHEMA` in `db.py` as `CREATE ... IF NOT EXISTS`, or as `ALTER TABLE` guarded by a `PRAGMA table_info` check. There is no migration framework and the DB holds real family data; back it up (`sqlite3 data/carkm.db ".backup x.db"`) before anything destructive.
- Frontend: keep it one file, no framework, no bundler. New user-facing strings go in both `I18N.es` and `I18N.en`. The default language is Spanish. Test at 390 px wide.
- Keep `README.md` in step when routes or install steps change.

## Conventions (hardware / KiCad)
- KiCad 10. `carrier.kicad_sch` is the source of truth for connectivity. Change nets in the schematic, then *Tools → Update PCB from Schematic*; never change pad nets on the board alone. Footprints are linked to their symbols.
- Net classes and design rules live in `carrier.kicad_pro`: Power 0.6 mm, GND 0.4 mm, Default 0.25 mm, 0.2 mm clearance, 0.15 mm minimum track. Local-label nets are named with a `/` prefix (`/USB_5V`), so net-class patterns must include it.
- Checks from the CLI (expected: ERC 0; DRC 0 errors, 0 unconnected, 0 parity; two accepted warnings for J1's silkscreen at the board edge):
  - `kicad-cli sch erc --severity-all -o /tmp/erc.rpt hardware/carrier/carrier.kicad_sch`
  - `kicad-cli pcb drc --schematic-parity --severity-all -o /tmp/drc.rpt hardware/carrier/carrier.kicad_pcb`
- All parts go on F.Cu (the outer face). The face toward the module has only ~2 mm of clearance.
- Keep the 25 × 12 mm antenna keep-out (top-left, both layers) free of copper; H1 inside it stays a bare NPTH.
- Keep `hardware/README.md` (nets, connectors, layout notes) and `bom-rev2.csv` in step with the schematic.
- Fab outputs go in `hardware/carrier/fab/` and are not committed.

## Hardware facts (verified from Waveshare files, 2026-10-06)
- Module J8 = JST SH 1.0 mm 12-pin: 1 GND, 2 USB_5V, 3 D−/IO19, 4 D+/IO20, 5 GND, 6 3V3, 7 SCL/IO10, 8 SDA/IO11, 9 TXD/IO43, 10 RXD/IO44, 11 GPIO18, 12 GPIO15.
- Power path:
  - USB_5V → D3 Schottky → VCC → ME6217 3.3 V LDO.
  - Battery → Q1 (on only when IO7 BAT_Control is high) → Q2 (on only when USB_5V is absent) → VCC.
  - Charger ETA6098: 2 A (RISET R7 82 k; plan is ≥ 200 k because J8 pin 2 is one ~1 A contact), 4.2 V CV.
  - Battery connector J1 "PH1.25" = MX1.25 / Molex PicoBlade, pin 1 = BAT.
- The supercap bank (2 × 5 F / 2.7 V in series) sits on the module's battery connector, and the module charges it. Hold-up ≈ 5–7 s with the backlight off; the charger only tops up after a 160 mV drop, so the bank can sit at ~4.04 V.
- GPIO:
  - IO7 BAT_Control: output, HIGH at boot, never low.
  - IO8 BAT_ADC: Vbat = 3 × Vadc.
  - IO15 PWR_SENSE: input; falling edge = car power lost. Driven by the carrier's U2 TPS3808G01 open-drain ~RESET (trip 3.99 V falling on VIN_FUSED, 20 ms release delay). The module's R30 10 k is the pull-up. IO15 is also the microSD D2 line, so no 4-bit SD.
  - IO18 NFC_IRQ; IO5 LCD backlight; IO6 Key_BAT unused.
  - I²C on IO10 SCL / IO11 SDA, shared by PN532 0x24, PCF85063 RTC 0x51 and QMI8658 IMU 0x6B.
- Mechanical: module PCB 69.00 × 49.90 mm; Ø2.7 holes on a 60.00 × 41.00 grid, 4.50 mm in from the edges; 6 mm of parts on the back; antenna top-left. The carrier copies the outline and holes and sits on 8 mm standoffs.
- Full net list, connectors and the fallback power configuration: `hardware/README.md`.

## Firmware conventions (for when firmware/ is created)
- PlatformIO env with `framework = espidf`; board `esp32-s3-devkitc-1` overridden to 16 MB flash + OPI PSRAM; custom `partitions.csv` with two OTA slots.
- BLE: NimBLE, central only.
- Components:
  - `obd`, `rfid` (PN532/I²C), `clock` (PCF85063 + SNTP);
  - `store` (NVS `ride/live` checkpoint + LittleFS queue);
  - `sync` (WiFi + HTTP to the Pi);
  - `ui` (LVGL 9, Waveshare BSP for ST7789 + CST328);
  - `power` (IO15 ISR).
- Hard rules:
  - The first line of `app_main` sets IO7 high.
  - Brownout handler order: backlight off → stop BLE → write ride → halt. In the halt loop, if IO15 goes high again (ignition back while the caps still hold the board, so no power-on reset), call `esp_restart()`.
  - Distance = sum of speed (PID 0x0D) / 3600 at 1 Hz; drop reads > 200 km/h or after a 5 s gap.
  - Checkpoint `ride/live` every 10 s.
  - The device posts to `POST /api/rides/batch` with the bearer token from `data/device_token`; idempotent on `(device_id, start_ts)`.
- Device-facing API shapes in `app/main.py` must not change without updating this section.

## Testing
- There is no test suite yet.
- Smoke-test by starting the dev server on :8081 and hitting the routes with curl, in this order: users → manual ride → odometer ride → device batch with and without the token → summary → export.
- Add `tests/` with pytest + `httpx.AsyncClient` if the backend grows.

## Things not to do
- Don't commit `data/`, `.venv/`, `hardware/carrier/fab/` or the Waveshare STEP.
- Don't change the device API shapes (`/api/rides/batch` body, `/api/fobs` ETag behaviour, `/api/firmware` `X-Version` header) without flagging it: the firmware will be written against them.
- Don't expose port 8080 to the internet; if remote access beyond Tailscale is ever wanted, use Tailscale Serve or a reverse proxy with auth.
- Don't connect a LiPo to the module: supercaps only (car interior temperatures).
- Don't populate R3/D2 on the carrier unless the fallback power configuration is chosen (then also cut JP1 and JP2).
- Don't change the J8 pin mapping assumptions without re-reading `hardware/vendor/ESP32-S3-Touch-LCD-2.8_schematic.pdf`.
- Don't put copper (tracks, vias, pours, plated holes) in the antenna keep-out.
