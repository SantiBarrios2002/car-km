"""Car km tracker — Pi service.

Serves the household web app and the ESP32 API from one process.
Run:  uvicorn app.main:app --host 0.0.0.0 --port 8080
"""
import csv
import io
import os
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Response
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import db

APP_DIR = Path(__file__).parent
STATIC_DIR = APP_DIR / "static"
FIRMWARE_DIR = Path(os.environ.get("CARKM_FIRMWARE", "data/firmware"))
TOKEN_FILE = Path(os.environ.get("CARKM_TOKEN_FILE", "data/device_token"))

app = FastAPI(title="Car km tracker", version="0.1.0", docs_url="/api/docs", redoc_url=None)


# ----------------------------------------------------------------------------- startup
@app.on_event("startup")
def _startup() -> None:
    db.init()
    FIRMWARE_DIR.mkdir(parents=True, exist_ok=True)
    if not TOKEN_FILE.exists():
        TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        TOKEN_FILE.write_text(secrets.token_urlsafe(24))
        TOKEN_FILE.chmod(0o600)


def device_token() -> str:
    return TOKEN_FILE.read_text().strip()


def require_device(authorization: Optional[str] = Header(default=None)) -> None:
    """Bearer-token check for the ESP32 endpoints. The web app never calls these."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "missing bearer token")
    if not secrets.compare_digest(authorization[7:].strip(), device_token()):
        raise HTTPException(403, "bad token")


def now() -> int:
    return int(time.time())


# ----------------------------------------------------------------------------- models
class UserIn(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    colour: str = Field(default="#4f7cff", pattern=r"^#[0-9a-fA-F]{6}$")
    active: bool = True


class FobIn(BaseModel):
    uid: str = Field(min_length=4, max_length=32, pattern=r"^[0-9a-fA-F]+$")
    user_id: Optional[int] = None
    label: Optional[str] = None
    active: bool = True


class ManualRide(BaseModel):
    """What the web app posts. Either km, or an odometer reading (km derived from the last one)."""
    user_id: Optional[int] = None
    start_ts: Optional[int] = None  # defaults to now - 30 min
    end_ts: Optional[int] = None    # defaults to now
    km: Optional[float] = Field(default=None, ge=0, le=5000)
    odometer_end: Optional[float] = Field(default=None, ge=0, le=5_000_000)
    note: Optional[str] = Field(default=None, max_length=200)


class RidePatch(BaseModel):
    user_id: Optional[int] = None
    km: Optional[float] = Field(default=None, ge=0, le=5000)
    start_ts: Optional[int] = None
    end_ts: Optional[int] = None
    note: Optional[str] = Field(default=None, max_length=200)


class ClaimIn(BaseModel):
    user_id: int


class SplitIn(BaseModel):
    user_id_a: int
    user_id_b: int
    share_a: float = Field(default=0.5, gt=0, lt=1)


class DeviceRide(BaseModel):
    """One queued ride as the ESP32 stores it."""
    device_id: str = Field(max_length=32)
    start_ts: int
    end_ts: int
    km: Optional[float] = None
    fob_uid: Optional[str] = None
    source: str = Field(pattern=r"^(obd|no_obd)$")
    fw: Optional[str] = None
    end_reason: Optional[str] = None


class OdometerIn(BaseModel):
    reading_km: float = Field(ge=0, le=5_000_000)
    user_id: Optional[int] = None
    ts: Optional[int] = None


class SettingsIn(BaseModel):
    rate_eur_km: Optional[float] = Field(default=None, ge=0, le=10)
    lang: Optional[str] = Field(default=None, pattern=r"^(es|en)$")
    car_name: Optional[str] = Field(default=None, max_length=40)
    obd_factor: Optional[float] = Field(default=None, gt=0.5, lt=1.5)


# ----------------------------------------------------------------------------- helpers
def _ride_select() -> str:
    return """
    SELECT r.*, u.name AS user_name, u.colour AS user_colour,
           COALESCE(r.km_corrected, r.km) AS km_final
    FROM rides r LEFT JOIN users u ON u.id = r.user_id
    """


def _month_bounds(month: str) -> tuple[int, int]:
    """'2026-10' -> (first second of month, first second of next month), local time."""
    try:
        y, m = (int(x) for x in month.split("-"))
        start = datetime(y, m, 1).astimezone()
        end = datetime(y + (m == 12), m % 12 + 1, 1).astimezone()
    except Exception:
        raise HTTPException(400, "month must be YYYY-MM")
    return int(start.timestamp()), int(end.timestamp())


def _resolve_fob(con, uid: Optional[str]) -> Optional[int]:
    if not uid:
        return None
    r = con.execute("SELECT user_id FROM fobs WHERE uid=? AND active=1", (uid.upper(),)).fetchone()
    return r["user_id"] if r else None


# ----------------------------------------------------------------------------- users
@app.get("/api/users")
def list_users(include_inactive: bool = False):
    with db.connect() as con:
        q = "SELECT * FROM users" + ("" if include_inactive else " WHERE active=1") + " ORDER BY name"
        return db.rows(con.execute(q))


@app.post("/api/users", status_code=201)
def create_user(u: UserIn):
    with db.connect() as con:
        try:
            cur = con.execute("INSERT INTO users(name, colour, active) VALUES (?,?,?)",
                              (u.name.strip(), u.colour, int(u.active)))
        except Exception:
            raise HTTPException(409, "name already exists")
        return db.one(con.execute("SELECT * FROM users WHERE id=?", (cur.lastrowid,)))


@app.patch("/api/users/{uid}")
def update_user(uid: int, u: UserIn):
    with db.connect() as con:
        con.execute("UPDATE users SET name=?, colour=?, active=? WHERE id=?",
                    (u.name.strip(), u.colour, int(u.active), uid))
        r = db.one(con.execute("SELECT * FROM users WHERE id=?", (uid,)))
        if not r:
            raise HTTPException(404)
        return r


# ----------------------------------------------------------------------------- fobs
@app.get("/api/fobs")
def list_fobs(response: Response, if_none_match: Optional[str] = Header(default=None)):
    """Used by both the web app and the ESP32 (which sends If-None-Match to skip unchanged tables)."""
    with db.connect() as con:
        fobs = db.rows(con.execute(
            "SELECT f.*, u.name AS user_name FROM fobs f LEFT JOIN users u ON u.id=f.user_id ORDER BY f.uid"))
    import hashlib
    sig = ";".join(f'{f["uid"]}:{f["user_id"]}:{f["active"]}' for f in fobs)
    etag = '"%s"' % hashlib.sha1(sig.encode()).hexdigest()[:16]
    if if_none_match == etag:
        return Response(status_code=304)
    response.headers["ETag"] = etag
    return fobs


@app.post("/api/fobs", status_code=201)
def upsert_fob(f: FobIn):
    with db.connect() as con:
        con.execute(
            "INSERT INTO fobs(uid, user_id, label, active) VALUES (?,?,?,?) "
            "ON CONFLICT(uid) DO UPDATE SET user_id=excluded.user_id, label=excluded.label, active=excluded.active",
            (f.uid.upper(), f.user_id, f.label, int(f.active)))
        return db.one(con.execute("SELECT * FROM fobs WHERE uid=?", (f.uid.upper(),)))


@app.delete("/api/fobs/{uid}", status_code=204)
def delete_fob(uid: str):
    with db.connect() as con:
        con.execute("DELETE FROM fobs WHERE uid=?", (uid.upper(),))


# ----------------------------------------------------------------------------- rides
@app.get("/api/rides")
def list_rides(month: Optional[str] = None, user: Optional[int] = None,
               unassigned: bool = False, limit: int = Query(default=200, le=1000)):
    where, args = [], []
    if month:
        a, b = _month_bounds(month)
        where.append("r.start_ts >= ? AND r.start_ts < ?"); args += [a, b]
    if user is not None:
        where.append("r.user_id = ?"); args.append(user)
    if unassigned:
        where.append("r.user_id IS NULL")
    q = _ride_select() + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY r.start_ts DESC LIMIT ?"
    args.append(limit)
    with db.connect() as con:
        return db.rows(con.execute(q, args))


@app.post("/api/rides", status_code=201)
def create_manual_ride(m: ManualRide):
    """Manual entry from the web app: km directly, or an odometer reading (km = delta from the last reading)."""
    end_ts = m.end_ts or now()
    start_ts = m.start_ts or end_ts - 1800
    with db.connect() as con:
        km = m.km
        if km is None:
            if m.odometer_end is None:
                raise HTTPException(400, "give km or odometer_end")
            last = db.one(con.execute(
                "SELECT ts, reading_km FROM odometer_log WHERE ts < ? ORDER BY ts DESC LIMIT 1", (end_ts,)))
            if not last:
                raise HTTPException(400, "no previous odometer reading; log one first in Settings")
            km = round(m.odometer_end - last["reading_km"], 1)
            if km < 0:
                raise HTTPException(400, f"odometer went backwards (last {last['reading_km']})")
            if m.start_ts is None:
                start_ts = max(last["ts"], end_ts - 12 * 3600)  # the delta covers since the last reading
        if start_ts >= end_ts:
            start_ts = end_ts - 60
        if m.odometer_end is not None:
            con.execute("INSERT OR REPLACE INTO odometer_log(ts, reading_km, user_id) VALUES (?,?,?)",
                        (end_ts, m.odometer_end, m.user_id))
        cur = con.execute(
            "INSERT INTO rides(device_id, start_ts, end_ts, km, odometer_end, user_id, source, "
            "claimed_by, claimed_at, note, created_at) VALUES ('manual',?,?,?,?,?,'manual',?,?,?,?)",
            (start_ts, end_ts, km, m.odometer_end, m.user_id, m.user_id,
             now() if m.user_id else None, m.note, now()))
        return db.one(con.execute(_ride_select() + " WHERE r.id=?", (cur.lastrowid,)))


@app.patch("/api/rides/{rid}")
def patch_ride(rid: int, p: RidePatch):
    fields = {k: v for k, v in p.model_dump().items() if v is not None}
    if not fields:
        raise HTTPException(400, "nothing to change")
    with db.connect() as con:
        sets = ", ".join(f"{k}=?" for k in fields)
        con.execute(f"UPDATE rides SET {sets} WHERE id=?", (*fields.values(), rid))
        r = db.one(con.execute(_ride_select() + " WHERE r.id=?", (rid,)))
        if not r:
            raise HTTPException(404)
        return r


@app.delete("/api/rides/{rid}", status_code=204)
def delete_ride(rid: int):
    with db.connect() as con:
        con.execute("DELETE FROM rides WHERE id=?", (rid,))


@app.post("/api/rides/{rid}/claim")
def claim_ride(rid: int, c: ClaimIn):
    with db.connect() as con:
        con.execute("UPDATE rides SET user_id=?, claimed_by=?, claimed_at=? WHERE id=?",
                    (c.user_id, c.user_id, now(), rid))
        r = db.one(con.execute(_ride_select() + " WHERE r.id=?", (rid,)))
        if not r:
            raise HTTPException(404)
        return r


@app.post("/api/rides/{rid}/split")
def split_ride(rid: int, s: SplitIn):
    """Turn one ride into two with the km shared; useful when two people drove."""
    with db.connect() as con:
        r = db.one(con.execute("SELECT * FROM rides WHERE id=?", (rid,)))
        if not r or r["km"] is None:
            raise HTTPException(404, "ride not found or has no km")
        km_a = round(r["km"] * s.share_a, 1)
        km_b = round(r["km"] - km_a, 1)
        mid = r["start_ts"] + int((r["end_ts"] - r["start_ts"]) * s.share_a)
        con.execute("UPDATE rides SET km=?, km_corrected=NULL, end_ts=?, user_id=?, claimed_by=?, claimed_at=?, "
                    "note=COALESCE(note,'') || ' [split 1/2]' WHERE id=?",
                    (km_a, mid, s.user_id_a, s.user_id_a, now(), rid))
        con.execute(
            "INSERT INTO rides(device_id, start_ts, end_ts, km, fob_uid, user_id, source, end_reason, "
            "claimed_by, claimed_at, note, fw, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (r["device_id"], mid + 1, r["end_ts"], km_b, r["fob_uid"], s.user_id_b, r["source"],
             r["end_reason"], s.user_id_b, now(), (r["note"] or "") + " [split 2/2]", r["fw"], now()))
        return db.rows(con.execute(_ride_select() + " WHERE r.id=? OR r.start_ts=? ORDER BY r.start_ts",
                                   (rid, mid + 1)))


# ----------------------------------------------------------------------------- device API
@app.post("/api/rides/batch", dependencies=[Depends(require_device)])
def rides_batch(rides: list[DeviceRide]):
    """ESP32 uploads its queue. Idempotent on (device_id, start_ts); returns which start_ts were accepted."""
    accepted, duplicate = [], []
    with db.connect() as con:
        factor = float(db.get_setting(con, "obd_factor", "1.0"))
        for r in rides:
            user_id = _resolve_fob(con, r.fob_uid)
            km_corr = round(r.km * factor, 2) if (r.km is not None and r.source == "obd") else None
            cur = con.execute(
                "INSERT OR IGNORE INTO rides(device_id, start_ts, end_ts, km, km_corrected, fob_uid, user_id, "
                "source, end_reason, fw, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (r.device_id, r.start_ts, r.end_ts, r.km, km_corr, (r.fob_uid or None) and r.fob_uid.upper(),
                 user_id, r.source, r.end_reason, r.fw, now()))
            (accepted if cur.rowcount else duplicate).append(r.start_ts)
    return {"accepted": accepted, "duplicate": duplicate, "server_time": now()}


@app.get("/api/time", dependencies=[Depends(require_device)])
def server_time():
    return {"ts": now()}


@app.get("/api/firmware", dependencies=[Depends(require_device)])
def firmware(response: Response, x_version: Optional[str] = Header(default=None)):
    """Latest firmware.bin; version comes from data/firmware/version.txt. 304 if the device already has it."""
    bin_path, ver_path = FIRMWARE_DIR / "firmware.bin", FIRMWARE_DIR / "version.txt"
    if not bin_path.exists() or not ver_path.exists():
        raise HTTPException(404, "no firmware published")
    version = ver_path.read_text().strip()
    if x_version == version:
        return Response(status_code=304)
    response.headers["X-Version"] = version
    return FileResponse(bin_path, media_type="application/octet-stream",
                        headers={"X-Version": version})


# ----------------------------------------------------------------------------- odometer & calibration
@app.get("/api/odometer")
def odometer_log(limit: int = 20):
    with db.connect() as con:
        return db.rows(con.execute(
            "SELECT o.*, u.name AS user_name FROM odometer_log o LEFT JOIN users u ON u.id=o.user_id "
            "ORDER BY ts DESC LIMIT ?", (limit,)))


@app.post("/api/odometer", status_code=201)
def log_odometer(o: OdometerIn):
    """Log a real dashboard reading. If there is a previous one, recompute obd_factor from the OBD rides between."""
    ts = o.ts or now()
    with db.connect() as con:
        prev = db.one(con.execute("SELECT * FROM odometer_log WHERE ts < ? ORDER BY ts DESC LIMIT 1", (ts,)))
        con.execute("INSERT OR REPLACE INTO odometer_log(ts, reading_km, user_id) VALUES (?,?,?)",
                    (ts, o.reading_km, o.user_id))
        result = {"ts": ts, "reading_km": o.reading_km, "factor": None, "obd_km_between": None}
        if prev:
            obd = db.one(con.execute(
                "SELECT SUM(km) AS s FROM rides WHERE source='obd' AND start_ts >= ? AND end_ts <= ?",
                (prev["ts"], ts)))
            if obd and obd["s"] and obd["s"] > 20:   # need a meaningful distance for a factor
                real = o.reading_km - prev["reading_km"]
                factor = real / obd["s"]
                if 0.8 < factor < 1.2:
                    db.set_setting(con, "obd_factor", f"{factor:.4f}")
                    con.execute("UPDATE rides SET km_corrected = ROUND(km * ?, 2) WHERE source='obd' AND start_ts >= ?",
                                (factor, prev["ts"]))
                    result.update(factor=round(factor, 4), obd_km_between=round(obd["s"], 1))
        return result


# ----------------------------------------------------------------------------- summary, export, settings
@app.get("/api/summary")
def summary(month: str):
    a, b = _month_bounds(month)
    with db.connect() as con:
        rate = float(db.get_setting(con, "rate_eur_km", "0"))
        per_user = db.rows(con.execute("""
            SELECT u.id, u.name, u.colour,
                   COUNT(r.id) AS rides,
                   ROUND(COALESCE(SUM(COALESCE(r.km_corrected, r.km)), 0), 1) AS km
            FROM users u LEFT JOIN rides r ON r.user_id = u.id AND r.start_ts >= ? AND r.start_ts < ?
            WHERE u.active = 1
            GROUP BY u.id ORDER BY km DESC, u.name""", (a, b)))
        unassigned = db.one(con.execute(
            "SELECT COUNT(*) AS rides, ROUND(COALESCE(SUM(COALESCE(km_corrected, km)),0),1) AS km "
            "FROM rides WHERE user_id IS NULL AND start_ts >= ? AND start_ts < ?", (a, b)))
    total = round(sum(u["km"] for u in per_user) + unassigned["km"], 1)
    for u in per_user:
        u["eur"] = round(u["km"] * rate, 2)
        u["share"] = round(u["km"] / total, 3) if total else 0
    return {"month": month, "rate_eur_km": rate, "total_km": total,
            "per_user": per_user, "unassigned": unassigned}


@app.get("/api/export.csv")
def export_csv(month: Optional[str] = None):
    where, args = "", []
    if month:
        a, b = _month_bounds(month)
        where, args = " WHERE r.start_ts >= ? AND r.start_ts < ?", [a, b]
    with db.connect() as con:
        rides = db.rows(con.execute(_ride_select() + where + " ORDER BY r.start_ts", args))
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id", "start", "end", "user", "km", "source", "note"])
    for r in rides:
        w.writerow([r["id"],
                    datetime.fromtimestamp(r["start_ts"]).isoformat(timespec="minutes"),
                    datetime.fromtimestamp(r["end_ts"]).isoformat(timespec="minutes"),
                    r["user_name"] or "", r["km_final"] if r["km_final"] is not None else "",
                    r["source"], r["note"] or ""])
    name = f"rides-{month or 'all'}.csv"
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="{name}"'})


@app.get("/api/settings")
def get_settings():
    with db.connect() as con:
        s = {r["key"]: r["value"] for r in con.execute("SELECT * FROM settings")}
    s["rate_eur_km"] = float(s.get("rate_eur_km", 0))
    s["obd_factor"] = float(s.get("obd_factor", 1))
    return s


@app.patch("/api/settings")
def patch_settings(s: SettingsIn):
    with db.connect() as con:
        for k, v in s.model_dump().items():
            if v is not None:
                db.set_setting(con, k, str(v))
    return get_settings()


@app.get("/api/device-token")
def show_device_token():
    """Shown once in Settings so you can paste it into the ESP32 build. LAN/Tailscale only, like the rest."""
    return {"token": device_token()}


# ----------------------------------------------------------------------------- static web app
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
