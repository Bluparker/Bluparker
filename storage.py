"""SQLite-backed price history and alert deduplication."""

import os
import sqlite3
from datetime import datetime
from typing import Optional

DB_PATH = os.environ.get("DB_PATH", "flight_history.db")


def init_db() -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS price_snapshots (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                watch_name  TEXT    NOT NULL,
                origin      TEXT    NOT NULL,
                destination TEXT    NOT NULL,
                depart_date TEXT    NOT NULL,
                return_date TEXT    NOT NULL DEFAULT '',
                best_price  REAL    NOT NULL,
                currency    TEXT    NOT NULL,
                airline     TEXT,
                stops       INTEGER,
                checked_at  TEXT    NOT NULL
            );

            CREATE TABLE IF NOT EXISTS alert_log (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                watch_name    TEXT    NOT NULL,
                origin        TEXT    NOT NULL,
                destination   TEXT    NOT NULL,
                depart_date   TEXT    NOT NULL,
                return_date   TEXT    NOT NULL DEFAULT '',
                alerted_price REAL    NOT NULL,
                alert_type    TEXT    NOT NULL,
                alerted_at    TEXT    NOT NULL
            );
            """
        )


def save_snapshot(
    watch_name: str,
    origin: str,
    destination: str,
    depart_date: str,
    return_date: str,
    best_price: float,
    currency: str,
    airline: Optional[str],
    stops: int,
) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """INSERT INTO price_snapshots
               (watch_name, origin, destination, depart_date, return_date,
                best_price, currency, airline, stops, checked_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                watch_name, origin, destination, depart_date, return_date,
                best_price, currency, airline, stops,
                datetime.utcnow().isoformat(),
            ),
        )


def get_previous_best_price(
    watch_name: str,
    origin: str,
    destination: str,
    depart_date: str,
    return_date: str,
) -> Optional[float]:
    """Return the best_price from the second-most-recent snapshot, or None."""
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            """SELECT best_price FROM price_snapshots
               WHERE watch_name=? AND origin=? AND destination=?
               AND depart_date=? AND return_date=?
               ORDER BY checked_at DESC LIMIT 2""",
            (watch_name, origin, destination, depart_date, return_date),
        ).fetchall()
    return rows[1][0] if len(rows) >= 2 else None


def already_alerted(
    watch_name: str,
    origin: str,
    destination: str,
    depart_date: str,
    return_date: str,
    price: float,
) -> bool:
    """True if an alert for this exact price/route/dates was already sent."""
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            """SELECT 1 FROM alert_log
               WHERE watch_name=? AND origin=? AND destination=?
               AND depart_date=? AND return_date=? AND alerted_price=?
               LIMIT 1""",
            (watch_name, origin, destination, depart_date, return_date, price),
        ).fetchone()
    return row is not None


def log_alert(
    watch_name: str,
    origin: str,
    destination: str,
    depart_date: str,
    return_date: str,
    price: float,
    alert_type: str,
) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """INSERT INTO alert_log
               (watch_name, origin, destination, depart_date, return_date,
                alerted_price, alert_type, alerted_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (
                watch_name, origin, destination, depart_date, return_date,
                price, alert_type, datetime.utcnow().isoformat(),
            ),
        )
