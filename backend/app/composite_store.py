"""
Composite signal store — GAP 11: Agent-as-provider.

The buyer agent synthesizes raw signals into a composite and publishes it here.
Other agents can discover and purchase the composite via x402, generating
revenue for the agent operator.

Price: $0.025/call (markup over ~$0.021 raw signal cost per session)
Revenue is credited to COMPOSITE_PROVIDER_ID in the earnings ledger.
"""

from __future__ import annotations

import os
import sqlite3
import threading
import time
from dataclasses import dataclass

_DB_PATH = os.getenv(
    "COMPOSITE_DB_PATH",
    os.path.join(os.path.dirname(__file__), "..", "data", "composite.db"),
)
os.makedirs(os.path.dirname(_DB_PATH), exist_ok=True)

COMPOSITE_PROVIDER_ID = "signalpay_agent_composite"
COMPOSITE_PRICE_USDC  = 0.025   # $0.025 per call
COMPOSITE_PRICE_MICRO = 25000   # in USDC micro-units (6 decimals)

_lock = threading.Lock()


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(_DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def _init_db():
    with _conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS composites (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id   TEXT NOT NULL,
                token        TEXT NOT NULL,
                action       TEXT NOT NULL,
                confidence   REAL NOT NULL DEFAULT 0.0,
                rationale    TEXT NOT NULL DEFAULT '',
                signal_count INTEGER NOT NULL DEFAULT 0,
                spend_usdc   REAL NOT NULL DEFAULT 0.0,
                raw_signals  TEXT NOT NULL DEFAULT '[]',
                published_at INTEGER NOT NULL
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS composite_earnings (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                buyer_agent  TEXT NOT NULL DEFAULT 'anonymous',
                earned_usdc  REAL NOT NULL,
                token        TEXT NOT NULL,
                earned_at    INTEGER NOT NULL
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_comp_token ON composites(token)")


_init_db()


@dataclass
class CompositeSignal:
    id: int
    session_id: str
    token: str
    action: str
    confidence: float
    rationale: str
    signal_count: int
    spend_usdc: float
    raw_signals: list
    published_at: int

    def to_signal_dict(self) -> dict:
        return {
            "category": "composite_signal",
            "provider":  COMPOSITE_PROVIDER_ID,
            "token":     self.token,
            "confidence": self.confidence,
            "timestamp": self.published_at,
            "data": {
                "token":        self.token,
                "action":       self.action,
                "confidence":   self.confidence,
                "rationale":    self.rationale,
                "signal_count": self.signal_count,
                "spend_usdc":   self.spend_usdc,
                "margin_usdc":  round(COMPOSITE_PRICE_USDC - self.spend_usdc, 6),
                "raw_signals":  self.raw_signals,
                "published_at": self.published_at,
            },
        }


def publish_composite(
    session_id: str,
    token: str,
    action: str,
    confidence: float,
    rationale: str,
    signal_count: int,
    spend_usdc: float,
    raw_signals: list,
) -> CompositeSignal:
    import json
    now = int(time.time())
    with _lock:
        with _conn() as c:
            cur = c.execute(
                """INSERT INTO composites
                   (session_id, token, action, confidence, rationale,
                    signal_count, spend_usdc, raw_signals, published_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (session_id, token, action, round(confidence, 4), rationale,
                 signal_count, round(spend_usdc, 6), json.dumps(raw_signals), now),
            )
            row_id = cur.lastrowid
    return get_latest_composite(token)  # type: ignore


def record_composite_sale(buyer_agent: str, token: str) -> float:
    """Called when a composite signal is purchased. Returns earnings credited."""
    now = int(time.time())
    with _lock:
        with _conn() as c:
            c.execute(
                "INSERT INTO composite_earnings (buyer_agent, earned_usdc, token, earned_at) VALUES (?,?,?,?)",
                (buyer_agent, COMPOSITE_PRICE_USDC, token, now),
            )
    return COMPOSITE_PRICE_USDC


def get_latest_composite(token: str | None = None) -> CompositeSignal | None:
    import json
    with _conn() as c:
        if token:
            row = c.execute(
                "SELECT * FROM composites WHERE token=? ORDER BY published_at DESC LIMIT 1",
                (token,),
            ).fetchone()
        else:
            row = c.execute(
                "SELECT * FROM composites ORDER BY published_at DESC LIMIT 1"
            ).fetchone()
    if not row:
        return None
    return CompositeSignal(
        id=row["id"],
        session_id=row["session_id"],
        token=row["token"],
        action=row["action"],
        confidence=float(row["confidence"]),
        rationale=row["rationale"],
        signal_count=int(row["signal_count"]),
        spend_usdc=float(row["spend_usdc"]),
        raw_signals=json.loads(row["raw_signals"]),
        published_at=int(row["published_at"]),
    )


def get_earnings_summary() -> dict:
    with _conn() as c:
        total = c.execute(
            "SELECT COALESCE(SUM(earned_usdc),0) as total, COUNT(*) as sales FROM composite_earnings"
        ).fetchone()
        recent = c.execute(
            "SELECT * FROM composite_earnings ORDER BY earned_at DESC LIMIT 10"
        ).fetchall()
    return {
        "provider_id":   COMPOSITE_PROVIDER_ID,
        "price_usdc":    COMPOSITE_PRICE_USDC,
        "total_earned":  round(float(total["total"]), 6),
        "total_sales":   int(total["sales"]),
        "recent_sales":  [
            {"buyer": r["buyer_agent"], "token": r["token"],
             "earned_usdc": float(r["earned_usdc"]), "at": int(r["earned_at"])}
            for r in recent
        ],
    }


def get_composite_history(token: str | None = None, limit: int = 20) -> list[dict]:
    with _conn() as c:
        if token:
            rows = c.execute(
                "SELECT * FROM composites WHERE token=? ORDER BY published_at DESC LIMIT ?",
                (token, limit),
            ).fetchall()
        else:
            rows = c.execute(
                "SELECT * FROM composites ORDER BY published_at DESC LIMIT ?", (limit,)
            ).fetchall()
    import json
    return [
        {
            "id": r["id"], "session_id": r["session_id"], "token": r["token"],
            "action": r["action"], "confidence": float(r["confidence"]),
            "signal_count": int(r["signal_count"]), "spend_usdc": float(r["spend_usdc"]),
            "published_at": int(r["published_at"]),
        }
        for r in rows
    ]
