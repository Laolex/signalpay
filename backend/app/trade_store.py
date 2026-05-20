"""
Trade execution store — paper-trading position tracker for SignalPay.

Every agent BUY/ACCUMULATE opens a simulated long at the current Pyth price.
Every SELL/REDUCE closes any open position on that token and records P&L.
Positions are $10 simulated USDC each — large enough to show meaningful P&L,
clearly labeled as paper trading throughout.

Closed positions feed back into reputation_store to close the signal→outcome loop:
  - profitable close → retrospective hit for the driving signals
  - loss            → retroactive miss

DB: $TRADE_DB_PATH or backend/data/trade.db

Schema: positions table
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
import statistics
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

# ── DB setup ─────────────────────────────────────────────────────────

_DB_PATH = os.getenv(
    "TRADE_DB_PATH",
    os.path.join(os.path.dirname(__file__), "..", "data", "trade.db"),
)
os.makedirs(os.path.dirname(_DB_PATH), exist_ok=True)

_lock = threading.Lock()

POSITION_SIZE_USDC = 10.0  # simulated allocation per trade


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(_DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def _init_db():
    with _conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS positions (
                id              TEXT PRIMARY KEY,
                session_id      TEXT NOT NULL DEFAULT '',
                user_address    TEXT NOT NULL DEFAULT '',
                token           TEXT NOT NULL,
                direction       TEXT NOT NULL,   -- 'long' | 'short'
                entry_price     REAL NOT NULL,
                size_usdc       REAL NOT NULL DEFAULT 10.0,
                entry_at        INTEGER NOT NULL,
                exit_price      REAL,
                exit_at         INTEGER,
                pnl_usdc        REAL,
                pnl_pct         REAL,
                status          TEXT NOT NULL DEFAULT 'open',  -- 'open' | 'closed'
                action_taken    TEXT,   -- 'BUY' | 'ACCUMULATE' | 'SELL' | 'REDUCE'
                conviction      REAL DEFAULT 0.5,
                driving_signals TEXT    -- comma-sep signal_ids
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_pos_status  ON positions(status)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_pos_token   ON positions(token, status)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_pos_session ON positions(session_id)")


_init_db()


# ── Position lifecycle ────────────────────────────────────────────────

def open_position(
    session_id: str,
    user_address: str,
    token: str,
    direction: str,
    entry_price: float,
    action_taken: str = "BUY",
    conviction: float = 0.5,
    driving_signals: Optional[list[str]] = None,
) -> str:
    """Open a new simulated position. Returns position_id."""
    now = int(time.time())
    pos_id = hashlib.sha256(
        f"{session_id}:{token}:{direction}:{now}".encode()
    ).hexdigest()[:20]

    with _lock:
        with _conn() as c:
            c.execute("""
                INSERT OR IGNORE INTO positions
                (id, session_id, user_address, token, direction,
                 entry_price, size_usdc, entry_at, action_taken,
                 conviction, driving_signals)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """, (
                pos_id,
                session_id,
                user_address.lower(),
                token.upper(),
                direction,
                entry_price,
                POSITION_SIZE_USDC,
                now,
                action_taken,
                conviction,
                ",".join(driving_signals or []),
            ))

    return pos_id


def close_position(position_id: str, exit_price: float) -> Optional[dict]:
    """
    Close a position and compute P&L.
    Returns the closed position dict or None if not found.
    """
    now = int(time.time())
    with _lock:
        with _conn() as c:
            row = c.execute(
                "SELECT * FROM positions WHERE id=? AND status='open'",
                (position_id,)
            ).fetchone()

            if not row:
                return None

            direction   = row["direction"]
            entry_price = row["entry_price"]
            size        = row["size_usdc"]

            if direction == "long":
                pnl_pct  = (exit_price - entry_price) / entry_price * 100 if entry_price else 0.0
            else:
                pnl_pct  = (entry_price - exit_price) / entry_price * 100 if entry_price else 0.0

            pnl_usdc = size * pnl_pct / 100.0

            c.execute("""
                UPDATE positions
                SET exit_price=?, exit_at=?, pnl_usdc=?, pnl_pct=?, status='closed'
                WHERE id=?
            """, (exit_price, now, round(pnl_usdc, 6), round(pnl_pct, 4), position_id))

            return {
                "position_id": position_id,
                "token":       row["token"],
                "direction":   direction,
                "entry_price": entry_price,
                "exit_price":  exit_price,
                "pnl_usdc":    round(pnl_usdc, 6),
                "pnl_pct":     round(pnl_pct, 4),
                "holding_s":   now - row["entry_at"],
            }


def close_open_positions_for_token(
    token: str,
    exit_price: float,
    session_id: str = "",
) -> list[dict]:
    """Close all open positions for a token. Returns list of closed position dicts."""
    with _conn() as c:
        open_ids = [
            r["id"] for r in c.execute(
                "SELECT id FROM positions WHERE token=? AND status='open'",
                (token.upper(),)
            ).fetchall()
        ]

    results = []
    for pos_id in open_ids:
        result = close_position(pos_id, exit_price)
        if result:
            results.append(result)

    return results


# ── Live price update (background task) ──────────────────────────────

def update_unrealized_pnl(prices: dict[str, float]):
    """
    Update unrealized P&L for all open positions.
    `prices` is a {token: current_price} dict from Pyth.
    """
    with _conn() as c:
        open_rows = c.execute(
            "SELECT id, token, direction, entry_price, size_usdc FROM positions WHERE status='open'"
        ).fetchall()

    with _lock:
        with _conn() as c:
            for row in open_rows:
                current = prices.get(row["token"])
                if current is None or current <= 0:
                    continue
                entry = row["entry_price"]
                if row["direction"] == "long":
                    pct = (current - entry) / entry * 100 if entry else 0.0
                else:
                    pct = (entry - current) / entry * 100 if entry else 0.0
                pnl = row["size_usdc"] * pct / 100.0
                c.execute(
                    "UPDATE positions SET exit_price=?, pnl_usdc=?, pnl_pct=? WHERE id=?",
                    (current, round(pnl, 6), round(pct, 4), row["id"]),
                )


# ── Queries ──────────────────────────────────────────────────────────

def get_open_positions() -> list[dict]:
    """All open positions with unrealized P&L."""
    with _conn() as c:
        rows = c.execute("""
            SELECT * FROM positions
            WHERE status = 'open'
            ORDER BY entry_at DESC
        """).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_position_history(limit: int = 20) -> list[dict]:
    """Closed positions newest first."""
    with _conn() as c:
        rows = c.execute("""
            SELECT * FROM positions
            WHERE status = 'closed'
            ORDER BY exit_at DESC
            LIMIT ?
        """, (limit,)).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_performance_summary() -> dict:
    """Win rate, total realized P&L, avg holding time, trade Sharpe."""
    with _conn() as c:
        closed = c.execute(
            "SELECT pnl_usdc, pnl_pct, entry_at, exit_at FROM positions WHERE status='closed'"
        ).fetchall()
        open_count = c.execute(
            "SELECT COUNT(*) FROM positions WHERE status='open'"
        ).fetchone()[0]

    total   = len(closed)
    wins    = sum(1 for r in closed if (r["pnl_usdc"] or 0) > 0)
    losses  = total - wins
    win_rate = wins / total if total else 0.0

    total_pnl = sum(float(r["pnl_usdc"] or 0) for r in closed)

    holding_times = [
        (r["exit_at"] - r["entry_at"])
        for r in closed if r["exit_at"] and r["entry_at"]
    ]
    avg_holding_s = sum(holding_times) / len(holding_times) if holding_times else 0

    # Trade Sharpe: mean(pnl_pct) / (std(pnl_pct) + 0.01)
    pnl_pcts = [float(r["pnl_pct"] or 0) for r in closed]
    if len(pnl_pcts) >= 2:
        sharpe = statistics.mean(pnl_pcts) / (statistics.stdev(pnl_pcts) + 0.01)
    else:
        sharpe = 0.0

    return {
        "total_trades":     total,
        "open_positions":   int(open_count),
        "wins":             wins,
        "losses":           losses,
        "win_rate":         round(win_rate, 4),
        "total_pnl_usdc":   round(total_pnl, 6),
        "avg_pnl_pct":      round(statistics.mean(pnl_pcts), 4) if pnl_pcts else 0.0,
        "avg_holding_s":    round(avg_holding_s),
        "trade_sharpe":     round(sharpe, 4),
    }


def _row_to_dict(r: sqlite3.Row) -> dict:
    d = dict(r)
    duration = None
    if d.get("exit_at") and d.get("entry_at"):
        duration = d["exit_at"] - d["entry_at"]
    elif d.get("entry_at"):
        duration = int(time.time()) - d["entry_at"]
    d["duration_s"] = duration
    return d
