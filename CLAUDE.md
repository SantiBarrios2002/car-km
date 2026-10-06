# car-km — household car kilometre tracker (Raspberry Pi service)

## What this is
One Python process (FastAPI + SQLite) that serves:
- a phone-first web app at `/` for the family (log rides manually, claim unassigned rides, monthly totals, CSV export), and
- the device API under `/api/` that an ESP32-S3 in the car will use later (RFID fob + OBD-II distance). The firmware does not exist yet.

The design spec lives outside this repo (Claude doc "Car km tracker – build spec"). Short version: the car device logs every ride automatically; an RFID tap only sets *who* drove; untapped rides arrive as unassigned and are claimed in the web app.

## Layout
```
app/main.py            all routes; web app + device API in one file, sections marked with # ----
app/db.py              schema (idempotent CREATE IF NOT EXISTS), connect() context manager, settings helpers
app/static/index.html  the whole web app: single file, vanilla JS, no build step, es/en strings in I18N
app/static/manifest.webmanifest, icon.svg   PWA bits
install.sh             venv + systemd unit + nightly backup cron; safe to re-run
car-km.service         systemd template; install.sh substitutes __DIR__ and __USER__
data/                  runtime state, not committed: carkm.db, device_token, firmware/, backups/
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

## Testing
No test suite yet. Smoke-test by starting the dev server on :8081 and hitting the routes with curl (users → manual ride → odometer ride → device batch with and without token → summary → export). Add `tests/` with pytest + `httpx.AsyncClient` if the backend grows.

## Things not to do
- Don't commit `data/` or `.venv/`.
- Don't change the device API shapes (`/api/rides/batch` body, `/api/fobs` ETag behaviour, `/api/firmware` `X-Version` header) without flagging it: the firmware will be written against them.
- Don't expose port 8080 to the internet; if remote access beyond Tailscale is ever wanted, use Tailscale Serve or a reverse proxy with auth.
