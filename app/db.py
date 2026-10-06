"""SQLite access for the car-km service. One connection per request, WAL mode, dict rows."""
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path(os.environ.get("CARKM_DB", "data/carkm.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id      INTEGER PRIMARY KEY,
  name    TEXT NOT NULL UNIQUE,
  colour  TEXT NOT NULL DEFAULT '#4f7cff',
  active  INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS fobs (
  uid      TEXT PRIMARY KEY,
  user_id  INTEGER REFERENCES users(id) ON DELETE SET NULL,
  label    TEXT,
  active   INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS rides (
  id            INTEGER PRIMARY KEY,
  device_id     TEXT NOT NULL,            -- 'manual' or the ESP32's id
  start_ts      INTEGER NOT NULL,
  end_ts        INTEGER NOT NULL,
  km            REAL,                     -- as measured / entered
  km_corrected  REAL,                     -- after odometer calibration, OBD rides only
  odometer_end  REAL,                     -- dashboard reading at the end, if the user gave one
  fob_uid       TEXT,
  user_id       INTEGER REFERENCES users(id) ON DELETE SET NULL,
  source        TEXT NOT NULL,            -- obd | no_obd | manual
  end_reason    TEXT,
  claimed_by    INTEGER REFERENCES users(id) ON DELETE SET NULL,
  claimed_at    INTEGER,
  note          TEXT,
  fw            TEXT,
  created_at    INTEGER NOT NULL
);
-- idempotency for device uploads only; manual rides may share a start second
CREATE UNIQUE INDEX IF NOT EXISTS rides_device_start ON rides(device_id, start_ts) WHERE device_id <> 'manual';
CREATE INDEX IF NOT EXISTS rides_start ON rides(start_ts);
CREATE INDEX IF NOT EXISTS rides_user  ON rides(user_id);

CREATE TABLE IF NOT EXISTS odometer_log (
  ts          INTEGER PRIMARY KEY,
  reading_km  REAL NOT NULL,
  user_id     INTEGER REFERENCES users(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS settings (
  key    TEXT PRIMARY KEY,
  value  TEXT NOT NULL
);
INSERT OR IGNORE INTO settings(key, value) VALUES ('rate_eur_km', '0');
INSERT OR IGNORE INTO settings(key, value) VALUES ('obd_factor', '1.0');
INSERT OR IGNORE INTO settings(key, value) VALUES ('lang', 'es');
INSERT OR IGNORE INTO settings(key, value) VALUES ('car_name', 'Meriva');
"""


def init() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with connect() as con:
        con.executescript(SCHEMA)


@contextmanager
def connect():
    con = sqlite3.connect(DB_PATH, timeout=10)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def rows(cur) -> list[dict]:
    return [dict(r) for r in cur.fetchall()]


def one(cur) -> dict | None:
    r = cur.fetchone()
    return dict(r) if r else None


def get_setting(con, key: str, default: str = "") -> str:
    r = con.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return r["value"] if r else default


def set_setting(con, key: str, value: str) -> None:
    con.execute(
        "INSERT INTO settings(key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )
