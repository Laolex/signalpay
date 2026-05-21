"""
Capital pool store — GAP 14: pooled capital + performance fee.

Depositors contribute USDC to the agent pool. The agent trades on their
behalf. Profits above the high-water mark (HWM) accrue a 20% performance
fee to the operator. Withdrawals are pro-rata on current NAV.

Mechanics
---------
NAV         = total_deposited + realized_pnl - fees_accrued
HWM         = highest NAV the pool has reached
Perf fee    = 20% of (realized_pnl - HWM_shortfall) per close
              only charged when NAV > HWM

DB: $POOL_DB_PATH or backend/data/pool.db
"""

from __future__ import annotations

import os
import sqlite3
import threading
import time
from dataclasses import dataclass

_DB_PATH = os.getenv(
    "POOL_DB_PATH",
    os.path.join(os.path.dirname(__file__), "..", "data", "pool.db"),
)
os.makedirs(os.path.dirname(_DB_PATH), exist_ok=True)

PERFORMANCE_FEE_PCT = 0.20   # 20% of profits above HWM

_lock = threading.Lock()


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(_DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def _init_db():
    with _conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS pool_state (
                id              INTEGER PRIMARY KEY CHECK (id = 1),
                total_deposited REAL NOT NULL DEFAULT 0.0,
                realized_pnl    REAL NOT NULL DEFAULT 0.0,
                fees_accrued    REAL NOT NULL DEFAULT 0.0,
                hwm             REAL NOT NULL DEFAULT 0.0,
                updated_at      INTEGER NOT NULL DEFAULT 0
            )
        """)
        c.execute("""
            INSERT OR IGNORE INTO pool_state (id, total_deposited, realized_pnl, fees_accrued, hwm, updated_at)
            VALUES (1, 0.0, 0.0, 0.0, 0.0, ?)
        """, (int(time.time()),))
        c.execute("""
            CREATE TABLE IF NOT EXISTS pool_transactions (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                type        TEXT NOT NULL,  -- 'deposit' | 'withdraw' | 'pnl' | 'fee'
                address     TEXT NOT NULL DEFAULT 'operator',
                amount_usdc REAL NOT NULL,
                note        TEXT NOT NULL DEFAULT '',
                created_at  INTEGER NOT NULL
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS depositors (
                address     TEXT PRIMARY KEY,
                deposited   REAL NOT NULL DEFAULT 0.0,
                withdrawn   REAL NOT NULL DEFAULT 0.0,
                first_at    INTEGER NOT NULL,
                updated_at  INTEGER NOT NULL
            )
        """)


_init_db()


@dataclass
class PoolState:
    total_deposited: float
    realized_pnl: float
    fees_accrued: float
    hwm: float
    updated_at: int

    @property
    def nav(self) -> float:
        return round(self.total_deposited + self.realized_pnl - self.fees_accrued, 6)

    @property
    def nav_above_hwm(self) -> float:
        return round(max(0.0, self.nav - self.hwm), 6)

    def to_dict(self) -> dict:
        return {
            "nav":              self.nav,
            "total_deposited":  round(self.total_deposited, 6),
            "realized_pnl":     round(self.realized_pnl, 6),
            "fees_accrued":     round(self.fees_accrued, 6),
            "hwm":              round(self.hwm, 6),
            "nav_above_hwm":    self.nav_above_hwm,
            "performance_fee_pct": PERFORMANCE_FEE_PCT,
            "updated_at":       self.updated_at,
        }


def _get_state(c: sqlite3.Connection) -> PoolState:
    row = c.execute("SELECT * FROM pool_state WHERE id=1").fetchone()
    return PoolState(
        total_deposited=float(row["total_deposited"]),
        realized_pnl=float(row["realized_pnl"]),
        fees_accrued=float(row["fees_accrued"]),
        hwm=float(row["hwm"]),
        updated_at=int(row["updated_at"]),
    )


def _save_state(c: sqlite3.Connection, s: PoolState):
    c.execute("""
        UPDATE pool_state SET total_deposited=?, realized_pnl=?, fees_accrued=?, hwm=?, updated_at=?
        WHERE id=1
    """, (s.total_deposited, s.realized_pnl, s.fees_accrued, s.hwm, int(time.time())))


def deposit(address: str, amount_usdc: float) -> PoolState:
    """Record a deposit. Returns updated pool state."""
    now = int(time.time())
    with _lock:
        with _conn() as c:
            s = _get_state(c)
            s.total_deposited = round(s.total_deposited + amount_usdc, 6)
            # HWM rises with deposits
            if s.nav > s.hwm:
                s.hwm = s.nav
            _save_state(c, s)
            c.execute(
                "INSERT INTO pool_transactions (type, address, amount_usdc, note, created_at) VALUES (?,?,?,?,?)",
                ("deposit", address.lower(), amount_usdc, f"deposit from {address[:10]}", now),
            )
            c.execute("""
                INSERT INTO depositors (address, deposited, withdrawn, first_at, updated_at) VALUES (?,?,0,?,?)
                ON CONFLICT(address) DO UPDATE SET deposited=deposited+?, updated_at=?
            """, (address.lower(), amount_usdc, now, now, amount_usdc, now))
    return get_pool_state()


def withdraw(address: str, amount_usdc: float) -> tuple[PoolState, float]:
    """
    Withdraw up to amount_usdc from pool (pro-rata on NAV).
    Returns (updated_state, actual_withdrawn).
    """
    now = int(time.time())
    with _lock:
        with _conn() as c:
            s = _get_state(c)
            actual = min(amount_usdc, max(0.0, s.nav))
            if actual <= 0:
                return s, 0.0
            s.total_deposited = max(0.0, round(s.total_deposited - actual, 6))
            _save_state(c, s)
            c.execute(
                "INSERT INTO pool_transactions (type, address, amount_usdc, note, created_at) VALUES (?,?,?,?,?)",
                ("withdraw", address.lower(), actual, f"withdraw to {address[:10]}", now),
            )
            c.execute("""
                INSERT INTO depositors (address, deposited, withdrawn, first_at, updated_at) VALUES (?,0,?,?,?)
                ON CONFLICT(address) DO UPDATE SET withdrawn=withdrawn+?, updated_at=?
            """, (address.lower(), actual, now, now, actual, now))
    return get_pool_state(), actual


def record_trade_pnl(pnl_usdc: float, note: str = "") -> tuple[PoolState, float]:
    """
    Called by trade_store after closing a position.
    Credits PnL to pool, computes performance fee if NAV exceeds HWM.
    Returns (updated_state, fee_charged).
    """
    now = int(time.time())
    fee_charged = 0.0
    with _lock:
        with _conn() as c:
            s = _get_state(c)
            s.realized_pnl = round(s.realized_pnl + pnl_usdc, 6)

            # Charge performance fee on profit above HWM
            if s.nav > s.hwm and pnl_usdc > 0:
                profit_above_hwm = s.nav - s.hwm
                fee_charged = round(min(profit_above_hwm * PERFORMANCE_FEE_PCT, pnl_usdc * PERFORMANCE_FEE_PCT), 6)
                s.fees_accrued = round(s.fees_accrued + fee_charged, 6)

            # Update HWM
            if s.nav > s.hwm:
                s.hwm = round(s.nav, 6)

            _save_state(c, s)
            c.execute(
                "INSERT INTO pool_transactions (type, address, amount_usdc, note, created_at) VALUES (?,?,?,?,?)",
                ("pnl", "agent", round(pnl_usdc, 6), note or f"trade P&L", now),
            )
            if fee_charged > 0:
                c.execute(
                    "INSERT INTO pool_transactions (type, address, amount_usdc, note, created_at) VALUES (?,?,?,?,?)",
                    ("fee", "operator", fee_charged, f"20% perf fee on +${pnl_usdc:.4f} P&L", now),
                )
    return get_pool_state(), fee_charged


def get_pool_state() -> PoolState:
    with _conn() as c:
        return _get_state(c)


def get_transactions(limit: int = 20) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM pool_transactions ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [
        {"id": r["id"], "type": r["type"], "address": r["address"],
         "amount_usdc": float(r["amount_usdc"]), "note": r["note"], "created_at": int(r["created_at"])}
        for r in rows
    ]


def get_depositors() -> list[dict]:
    with _conn() as c:
        rows = c.execute("SELECT * FROM depositors ORDER BY deposited DESC").fetchall()
    return [
        {"address": r["address"], "deposited": float(r["deposited"]),
         "withdrawn": float(r["withdrawn"]), "net": round(float(r["deposited"]) - float(r["withdrawn"]), 6)}
        for r in rows
    ]
