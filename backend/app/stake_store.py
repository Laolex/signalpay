"""
Stake store for SignalPay GAP 10: provider staking/slashing.

Providers bond USDC collateral. Stake boosts routing priority.
Each slash event permanently decays the composite score.

Mechanics
---------
stake_amount_usdc  USDC bonded by a provider (0 = no stake)
stake_boost        min(stake_amount_usdc / 100.0, 0.10) — up to +10pts
slash_count        total slash events recorded against a provider
slash_penalty      min(slash_count * 0.05, 0.25) — 5% per slash, max −25pts

DB: $STAKE_DB_PATH or backend/data/stake.db
"""

from __future__ import annotations

import os
import sqlite3
import threading
import time
from dataclasses import dataclass

_DB_PATH = os.getenv(
    "STAKE_DB_PATH",
    os.path.join(os.path.dirname(__file__), "..", "data", "stake.db"),
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
            CREATE TABLE IF NOT EXISTS stakes (
                provider_id  TEXT PRIMARY KEY,
                amount_usdc  REAL NOT NULL DEFAULT 0.0,
                deposited_at INTEGER NOT NULL,
                updated_at   INTEGER NOT NULL
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS slash_events (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                provider_id  TEXT NOT NULL,
                reason       TEXT NOT NULL DEFAULT '',
                slash_amount REAL NOT NULL DEFAULT 0.0,
                slash_at     INTEGER NOT NULL
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_slash_provider ON slash_events(provider_id)")


_init_db()


@dataclass
class StakeRecord:
    provider_id: str
    amount_usdc: float
    deposited_at: int
    updated_at: int
    slash_count: int = 0

    @property
    def stake_boost(self) -> float:
        return round(min(self.amount_usdc / 100.0, 0.10), 4)

    @property
    def slash_penalty(self) -> float:
        return round(min(self.slash_count * 0.05, 0.25), 4)

    def to_dict(self) -> dict:
        return {
            "provider_id":    self.provider_id,
            "amount_usdc":    self.amount_usdc,
            "deposited_at":   self.deposited_at,
            "updated_at":     self.updated_at,
            "slash_count":    self.slash_count,
            "stake_boost":    self.stake_boost,
            "slash_penalty":  self.slash_penalty,
            "net_score_delta": round(self.stake_boost - self.slash_penalty, 4),
        }


def deposit_stake(provider_id: str, amount_usdc: float) -> StakeRecord:
    """Add stake for a provider (accumulates — does not replace)."""
    now = int(time.time())
    with _lock:
        with _conn() as c:
            row = c.execute(
                "SELECT amount_usdc FROM stakes WHERE provider_id=?", (provider_id,)
            ).fetchone()
            if row:
                new_amount = float(row["amount_usdc"]) + amount_usdc
                c.execute(
                    "UPDATE stakes SET amount_usdc=?, updated_at=? WHERE provider_id=?",
                    (new_amount, now, provider_id),
                )
            else:
                c.execute(
                    "INSERT INTO stakes (provider_id, amount_usdc, deposited_at, updated_at) VALUES (?,?,?,?)",
                    (provider_id, amount_usdc, now, now),
                )
    return get_stake(provider_id)


def slash_provider(provider_id: str, reason: str = "", slash_amount: float = 0.0) -> StakeRecord:
    """Record a slash event. Reduces stake by slash_amount (floor 0). Increments slash_count."""
    now = int(time.time())
    with _lock:
        with _conn() as c:
            c.execute(
                "INSERT INTO slash_events (provider_id, reason, slash_amount, slash_at) VALUES (?,?,?,?)",
                (provider_id, reason, slash_amount, now),
            )
            if slash_amount > 0:
                row = c.execute(
                    "SELECT amount_usdc FROM stakes WHERE provider_id=?", (provider_id,)
                ).fetchone()
                if row:
                    new_amount = max(0.0, float(row["amount_usdc"]) - slash_amount)
                    c.execute(
                        "UPDATE stakes SET amount_usdc=?, updated_at=? WHERE provider_id=?",
                        (new_amount, now, provider_id),
                    )
                else:
                    c.execute(
                        "INSERT INTO stakes (provider_id, amount_usdc, deposited_at, updated_at) VALUES (?,0.0,?,?)",
                        (provider_id, now, now),
                    )
    return get_stake(provider_id)


def get_stake(provider_id: str) -> StakeRecord:
    """Get stake record for a provider. Returns zeroed record if not found."""
    with _conn() as c:
        row = c.execute(
            "SELECT * FROM stakes WHERE provider_id=?", (provider_id,)
        ).fetchone()
        slash_count = c.execute(
            "SELECT COUNT(*) as cnt FROM slash_events WHERE provider_id=?", (provider_id,)
        ).fetchone()["cnt"]
    if row:
        return StakeRecord(
            provider_id=row["provider_id"],
            amount_usdc=float(row["amount_usdc"]),
            deposited_at=int(row["deposited_at"]),
            updated_at=int(row["updated_at"]),
            slash_count=slash_count,
        )
    return StakeRecord(
        provider_id=provider_id, amount_usdc=0.0,
        deposited_at=0, updated_at=0, slash_count=slash_count,
    )


def get_all_stakes() -> list[StakeRecord]:
    """All staked providers, sorted by stake amount descending."""
    with _conn() as c:
        rows = c.execute("SELECT * FROM stakes ORDER BY amount_usdc DESC").fetchall()
        result = []
        for row in rows:
            slash_count = c.execute(
                "SELECT COUNT(*) as cnt FROM slash_events WHERE provider_id=?",
                (row["provider_id"],)
            ).fetchone()["cnt"]
            result.append(StakeRecord(
                provider_id=row["provider_id"],
                amount_usdc=float(row["amount_usdc"]),
                deposited_at=int(row["deposited_at"]),
                updated_at=int(row["updated_at"]),
                slash_count=slash_count,
            ))
    return result


def get_stake_map() -> dict[str, StakeRecord]:
    """Provider ID → StakeRecord map. Consumed by buyer_agent scoring pass."""
    return {s.provider_id: s for s in get_all_stakes()}


def get_slash_history(provider_id: str | None = None, limit: int = 20) -> list[dict]:
    """Recent slash events, newest first."""
    with _conn() as c:
        if provider_id:
            rows = c.execute(
                "SELECT * FROM slash_events WHERE provider_id=? ORDER BY slash_at DESC LIMIT ?",
                (provider_id, limit),
            ).fetchall()
        else:
            rows = c.execute(
                "SELECT * FROM slash_events ORDER BY slash_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
    return [
        {
            "id":           row["id"],
            "provider_id":  row["provider_id"],
            "reason":       row["reason"],
            "slash_amount": float(row["slash_amount"]),
            "slash_at":     int(row["slash_at"]),
        }
        for row in rows
    ]
