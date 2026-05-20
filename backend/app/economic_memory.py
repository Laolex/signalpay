"""
Persistent economic memory for SignalPay.

Tracks spend, sessions, and provider cost basis across all agent runs.
Persists to SQLite — survives restarts, queryable by the analytics API.

DB: $ECONOMIC_DB_PATH or backend/data/economic.db

Schema
------
sessions   — one row per agent run (budget, spend, action, signal count)
spend_log  — one row per signal purchase (provider, cost, confidence, payment id)

Analytics
---------
get_spend_summary()       — lifetime totals + per-provider breakdown
get_session_history()     — paginated session list with economic summary
get_provider_economics()  — per-provider: total spend, avg cost, call count, ROI proxy
get_cost_basis(provider)  — rolling average cost per signal for routing decisions
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

# ── DB setup ─────────────────────────────────────────────────────────

_DB_PATH = os.getenv(
    "ECONOMIC_DB_PATH",
    os.path.join(os.path.dirname(__file__), "..", "data", "economic.db"),
)
os.makedirs(os.path.dirname(_DB_PATH), exist_ok=True)

_lock = threading.Lock()


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(_DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def _init_db():
    with _conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id              TEXT PRIMARY KEY,
                user_address    TEXT NOT NULL DEFAULT '',
                started_at      INTEGER NOT NULL,
                ended_at        INTEGER,
                budget_usdc     REAL NOT NULL DEFAULT 0,
                spent_usdc      REAL NOT NULL DEFAULT 0,
                signals_count   INTEGER NOT NULL DEFAULT 0,
                action_taken    TEXT,
                providers_used  TEXT    -- comma-separated provider ids
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS spend_log (
                id              TEXT PRIMARY KEY,
                session_id      TEXT NOT NULL,
                user_address    TEXT NOT NULL DEFAULT '',
                provider_id     TEXT NOT NULL,
                category        TEXT NOT NULL,
                cost_usdc       REAL NOT NULL,
                confidence      REAL NOT NULL DEFAULT 0.5,
                purchased_at    INTEGER NOT NULL,
                payment_id      TEXT
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_spend_session ON spend_log(session_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_spend_provider ON spend_log(provider_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_address)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_sessions_started ON sessions(started_at)")
        c.execute("""
            CREATE TABLE IF NOT EXISTS revenue_log (
                id          TEXT PRIMARY KEY,
                payer       TEXT NOT NULL DEFAULT '',
                amount_usdc REAL NOT NULL,
                payment_id  TEXT NOT NULL DEFAULT '',
                endpoint    TEXT NOT NULL DEFAULT '',
                received_at INTEGER NOT NULL
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_revenue_day ON revenue_log(received_at)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_revenue_endpoint ON revenue_log(endpoint)")


_init_db()


# ── Session lifecycle ─────────────────────────────────────────────────

def start_session(user_address: str, budget_usdc: float) -> str:
    """Open a new agent session. Returns the session_id."""
    now = int(time.time())
    session_id = hashlib.sha256(
        f"{user_address.lower()}:{now}".encode()
    ).hexdigest()[:20]

    with _lock:
        with _conn() as c:
            c.execute("""
                INSERT OR IGNORE INTO sessions (id, user_address, started_at, budget_usdc)
                VALUES (?, ?, ?, ?)
            """, (session_id, user_address.lower(), now, budget_usdc))

    return session_id


def end_session(
    session_id: str,
    spent_usdc: float,
    signals_count: int,
    action_taken: Optional[str] = None,
    providers_used: Optional[list[str]] = None,
):
    """Close a session with final economics."""
    now = int(time.time())
    prov_str = ",".join(sorted(set(providers_used or [])))

    with _lock:
        with _conn() as c:
            c.execute("""
                UPDATE sessions
                SET ended_at=?, spent_usdc=?, signals_count=?,
                    action_taken=?, providers_used=?
                WHERE id=?
            """, (now, spent_usdc, signals_count, action_taken, prov_str, session_id))


def record_spend(
    session_id: str,
    user_address: str,
    provider_id: str,
    category: str,
    cost_usdc: float,
    confidence: float = 0.5,
    payment_id: Optional[str] = None,
):
    """Record a single signal purchase in the spend log."""
    now = int(time.time())
    entry_id = hashlib.sha256(
        f"{session_id}:{provider_id}:{now}".encode()
    ).hexdigest()[:20]

    with _lock:
        with _conn() as c:
            c.execute("""
                INSERT OR IGNORE INTO spend_log
                (id, session_id, user_address, provider_id, category,
                 cost_usdc, confidence, purchased_at, payment_id)
                VALUES (?,?,?,?,?,?,?,?,?)
            """, (
                entry_id, session_id, user_address.lower(),
                provider_id, category, cost_usdc, confidence, now, payment_id,
            ))


# ── Analytics ─────────────────────────────────────────────────────────

def get_cost_basis(provider_id: str, window: int = 50) -> float:
    """
    Rolling average cost per signal for a provider (last `window` purchases).
    Returns 0.0 if no history.
    """
    with _conn() as c:
        row = c.execute("""
            SELECT AVG(cost_usdc) FROM (
                SELECT cost_usdc FROM spend_log
                WHERE provider_id = ?
                ORDER BY purchased_at DESC
                LIMIT ?
            )
        """, (provider_id, window)).fetchone()
    return float(row[0] or 0.0)


def get_spend_summary() -> dict:
    """Lifetime totals and per-provider breakdown."""
    with _conn() as c:
        totals = c.execute("""
            SELECT
                COUNT(DISTINCT session_id) as session_count,
                COUNT(*) as total_calls,
                SUM(cost_usdc) as total_spend,
                AVG(cost_usdc) as avg_cost,
                AVG(confidence) as avg_confidence
            FROM spend_log
        """).fetchone()

        by_provider = c.execute("""
            SELECT
                provider_id,
                category,
                COUNT(*) as calls,
                SUM(cost_usdc) as total_spend,
                AVG(cost_usdc) as avg_cost,
                AVG(confidence) as avg_confidence,
                MAX(purchased_at) as last_seen
            FROM spend_log
            GROUP BY provider_id
            ORDER BY total_spend DESC
        """).fetchall()

        daily = c.execute("""
            SELECT
                date(purchased_at, 'unixepoch') as day,
                SUM(cost_usdc) as spend,
                COUNT(*) as calls
            FROM spend_log
            GROUP BY day
            ORDER BY day DESC
            LIMIT 14
        """).fetchall()

    return {
        "lifetime": {
            "session_count":  int(totals["session_count"] or 0),
            "total_calls":    int(totals["total_calls"] or 0),
            "total_spend":    round(float(totals["total_spend"] or 0), 6),
            "avg_cost":       round(float(totals["avg_cost"] or 0), 6),
            "avg_confidence": round(float(totals["avg_confidence"] or 0.5), 4),
        },
        "by_provider": [
            {
                "provider_id":    r["provider_id"],
                "category":       r["category"],
                "calls":          int(r["calls"]),
                "total_spend":    round(float(r["total_spend"]), 6),
                "avg_cost":       round(float(r["avg_cost"]), 6),
                "avg_confidence": round(float(r["avg_confidence"]), 4),
                "last_seen":      int(r["last_seen"]),
                "spend_share":    0.0,  # filled below
            }
            for r in by_provider
        ],
        "daily_spend": [
            {"day": r["day"], "spend": round(float(r["spend"]), 6), "calls": int(r["calls"])}
            for r in daily
        ],
    }


def get_session_history(user_address: Optional[str] = None, limit: int = 20) -> list[dict]:
    """Recent sessions with economic summary, newest first."""
    with _conn() as c:
        if user_address:
            rows = c.execute("""
                SELECT s.*, COUNT(sl.id) as actual_calls, SUM(sl.cost_usdc) as actual_spend
                FROM sessions s
                LEFT JOIN spend_log sl ON sl.session_id = s.id
                WHERE s.user_address = ?
                GROUP BY s.id
                ORDER BY s.started_at DESC
                LIMIT ?
            """, (user_address.lower(), limit)).fetchall()
        else:
            rows = c.execute("""
                SELECT s.*, COUNT(sl.id) as actual_calls, SUM(sl.cost_usdc) as actual_spend
                FROM sessions s
                LEFT JOIN spend_log sl ON sl.session_id = s.id
                GROUP BY s.id
                ORDER BY s.started_at DESC
                LIMIT ?
            """, (limit,)).fetchall()

    return [
        {
            "session_id":    r["id"],
            "user_address":  r["user_address"],
            "started_at":    r["started_at"],
            "ended_at":      r["ended_at"],
            "duration_s":    (r["ended_at"] - r["started_at"]) if r["ended_at"] else None,
            "budget_usdc":   round(float(r["budget_usdc"] or 0), 6),
            "spent_usdc":    round(float(r["spent_usdc"] or 0), 6),
            "signals_count": int(r["signals_count"] or 0),
            "action_taken":  r["action_taken"],
            "providers_used": r["providers_used"] or "",
            "budget_used_pct": round(
                float(r["spent_usdc"] or 0) / float(r["budget_usdc"] or 1) * 100, 1
            ) if r["budget_usdc"] else 0,
        }
        for r in rows
    ]


def record_revenue(
    payer: str,
    amount_usdc: float,
    payment_id: str,
    endpoint: str,
):
    """Record a confirmed x402 settlement as treasury revenue."""
    now = int(time.time())
    entry_id = hashlib.sha256(
        f"{payment_id}:{now}".encode()
    ).hexdigest()[:20]

    with _lock:
        with _conn() as c:
            c.execute("""
                INSERT OR IGNORE INTO revenue_log
                (id, payer, amount_usdc, payment_id, endpoint, received_at)
                VALUES (?,?,?,?,?,?)
            """, (entry_id, payer.lower(), amount_usdc, payment_id, endpoint, now))


def get_treasury_summary() -> dict:
    """Unified treasury view: revenue + spend + net + 14-day cashflow + by-endpoint breakdown."""
    with _conn() as c:
        rev = c.execute("""
            SELECT COUNT(*) as calls, SUM(amount_usdc) as total
            FROM revenue_log
        """).fetchone()

        spd = c.execute("""
            SELECT COUNT(*) as calls, SUM(cost_usdc) as total
            FROM spend_log
        """).fetchone()

        daily_rev = c.execute("""
            SELECT date(received_at, 'unixepoch') as day,
                   SUM(amount_usdc) as revenue, COUNT(*) as calls
            FROM revenue_log
            GROUP BY day ORDER BY day DESC LIMIT 14
        """).fetchall()

        daily_spd = c.execute("""
            SELECT date(purchased_at, 'unixepoch') as day,
                   SUM(cost_usdc) as spend, COUNT(*) as calls
            FROM spend_log
            GROUP BY day ORDER BY day DESC LIMIT 14
        """).fetchall()

        by_endpoint = c.execute("""
            SELECT endpoint, COUNT(*) as calls,
                   SUM(amount_usdc) as total_revenue,
                   AVG(amount_usdc) as avg_revenue
            FROM revenue_log
            GROUP BY endpoint ORDER BY total_revenue DESC
        """).fetchall()

    total_revenue = float(rev["total"] or 0)
    total_spend   = float(spd["total"] or 0)

    rev_by_day   = {r["day"]: {"revenue": float(r["revenue"]), "rc": int(r["calls"])} for r in daily_rev}
    spend_by_day = {r["day"]: {"spend":   float(r["spend"]),   "sc": int(r["calls"])} for r in daily_spd}
    all_days = sorted(set(list(rev_by_day) + list(spend_by_day)), reverse=True)[:14]

    daily_flow = []
    for day in all_days:
        rv = rev_by_day.get(day,   {"revenue": 0.0, "rc": 0})
        sp = spend_by_day.get(day, {"spend":   0.0, "sc": 0})
        daily_flow.append({
            "day":         day,
            "revenue":     round(rv["revenue"], 6),
            "spend":       round(sp["spend"],   6),
            "net":         round(rv["revenue"] - sp["spend"], 6),
            "rev_calls":   rv["rc"],
            "spend_calls": sp["sc"],
        })

    return {
        "revenue":     {"total": round(total_revenue, 6), "calls": int(rev["calls"] or 0)},
        "spend":       {"total": round(total_spend,   6), "calls": int(spd["calls"] or 0)},
        "net":          round(total_revenue - total_spend, 6),
        "daily_flow":   daily_flow,
        "by_endpoint":  [
            {
                "endpoint":      r["endpoint"],
                "calls":         int(r["calls"]),
                "total_revenue": round(float(r["total_revenue"]), 6),
                "avg_revenue":   round(float(r["avg_revenue"]),   6),
            }
            for r in by_endpoint
        ],
    }


def get_provider_economics() -> list[dict]:
    """
    Per-provider economics: spend, cost basis, call count, avg confidence.
    Sorted by lifetime spend descending.
    """
    summary = get_spend_summary()
    total_spend = summary["lifetime"]["total_spend"] or 1.0

    providers = summary["by_provider"]
    for p in providers:
        p["spend_share"] = round(p["total_spend"] / total_spend * 100, 1)

    return providers
