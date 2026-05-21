"""
Subscription store — GAP 13: flat-rate USDC subscription tier.

Agents/users pay once per epoch to unlock N signal calls, bypassing
per-call x402 payments. The x402 middleware checks subscription status
before requiring payment — active subscribers get routed through free.

Tiers
-----
basic      $0.10 / 24h →  50 calls
pro        $0.50 / 24h → 300 calls
unlimited  $2.00 / 24h → unlimited (capped at 9999 for storage)

DB: $SUBSCRIPTION_DB_PATH or backend/data/subscription.db
"""

from __future__ import annotations

import os
import sqlite3
import threading
import time
from dataclasses import dataclass

_DB_PATH = os.getenv(
    "SUBSCRIPTION_DB_PATH",
    os.path.join(os.path.dirname(__file__), "..", "data", "subscription.db"),
)
os.makedirs(os.path.dirname(_DB_PATH), exist_ok=True)

_lock = threading.Lock()

TIERS: dict[str, dict] = {
    "basic": {
        "price_usdc":    0.10,
        "price_micro":   100_000,
        "calls":         50,
        "duration_s":    86_400,   # 24h
        "label":         "Basic",
    },
    "pro": {
        "price_usdc":    0.50,
        "price_micro":   500_000,
        "calls":         300,
        "duration_s":    86_400,
        "label":         "Pro",
    },
    "unlimited": {
        "price_usdc":    2.00,
        "price_micro":   2_000_000,
        "calls":         9_999,
        "duration_s":    86_400,
        "label":         "Unlimited",
    },
}


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(_DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def _init_db():
    with _conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS subscriptions (
                address      TEXT NOT NULL,
                tier         TEXT NOT NULL DEFAULT 'basic',
                calls_total  INTEGER NOT NULL DEFAULT 50,
                calls_used   INTEGER NOT NULL DEFAULT 0,
                activated_at INTEGER NOT NULL,
                expires_at   INTEGER NOT NULL,
                PRIMARY KEY (address, activated_at)
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_sub_addr ON subscriptions(address, expires_at)")
        c.execute("""
            CREATE TABLE IF NOT EXISTS subscription_revenue (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                address      TEXT NOT NULL,
                tier         TEXT NOT NULL,
                price_usdc   REAL NOT NULL,
                subscribed_at INTEGER NOT NULL
            )
        """)


_init_db()


@dataclass
class Subscription:
    address: str
    tier: str
    calls_total: int
    calls_used: int
    activated_at: int
    expires_at: int

    @property
    def calls_remaining(self) -> int:
        return max(0, self.calls_total - self.calls_used)

    @property
    def is_active(self) -> bool:
        return self.expires_at > int(time.time()) and self.calls_remaining > 0

    @property
    def seconds_remaining(self) -> int:
        return max(0, self.expires_at - int(time.time()))

    def to_dict(self) -> dict:
        tier_info = TIERS.get(self.tier, {})
        return {
            "address":          self.address,
            "tier":             self.tier,
            "tier_label":       tier_info.get("label", self.tier),
            "calls_total":      self.calls_total,
            "calls_used":       self.calls_used,
            "calls_remaining":  self.calls_remaining,
            "is_active":        self.is_active,
            "activated_at":     self.activated_at,
            "expires_at":       self.expires_at,
            "seconds_remaining": self.seconds_remaining,
            "price_usdc":       tier_info.get("price_usdc", 0),
        }


def activate_subscription(address: str, tier: str) -> Subscription:
    """Create or extend a subscription for an address."""
    address = address.lower()
    tier_cfg = TIERS.get(tier, TIERS["basic"])
    now = int(time.time())
    expires = now + tier_cfg["duration_s"]

    with _lock:
        with _conn() as c:
            c.execute("""
                INSERT INTO subscriptions (address, tier, calls_total, calls_used, activated_at, expires_at)
                VALUES (?,?,?,0,?,?)
            """, (address, tier, tier_cfg["calls"], now, expires))
            c.execute("""
                INSERT INTO subscription_revenue (address, tier, price_usdc, subscribed_at)
                VALUES (?,?,?,?)
            """, (address, tier, tier_cfg["price_usdc"], now))

    return get_active_subscription(address)  # type: ignore


def get_active_subscription(address: str) -> Subscription | None:
    """Return the active (non-expired, calls remaining) subscription for an address."""
    address = address.lower()
    now = int(time.time())
    with _conn() as c:
        row = c.execute("""
            SELECT * FROM subscriptions
            WHERE address=? AND expires_at > ? AND (calls_total - calls_used) > 0
            ORDER BY expires_at DESC LIMIT 1
        """, (address, now)).fetchone()
    if not row:
        return None
    return Subscription(
        address=row["address"],
        tier=row["tier"],
        calls_total=int(row["calls_total"]),
        calls_used=int(row["calls_used"]),
        activated_at=int(row["activated_at"]),
        expires_at=int(row["expires_at"]),
    )


def consume_call(address: str) -> bool:
    """Decrement calls_used for active subscription. Returns True if consumed."""
    address = address.lower()
    now = int(time.time())
    with _lock:
        with _conn() as c:
            row = c.execute("""
                SELECT rowid, calls_total, calls_used FROM subscriptions
                WHERE address=? AND expires_at > ? AND (calls_total - calls_used) > 0
                ORDER BY expires_at DESC LIMIT 1
            """, (address, now)).fetchone()
            if not row:
                return False
            c.execute(
                "UPDATE subscriptions SET calls_used=? WHERE rowid=?",
                (int(row["calls_used"]) + 1, row["rowid"]),
            )
    return True


def get_revenue_summary() -> dict:
    with _conn() as c:
        total = c.execute(
            "SELECT COALESCE(SUM(price_usdc),0) as rev, COUNT(*) as cnt FROM subscription_revenue"
        ).fetchone()
        by_tier = c.execute(
            "SELECT tier, COUNT(*) as cnt, SUM(price_usdc) as rev FROM subscription_revenue GROUP BY tier"
        ).fetchall()
    return {
        "total_revenue": round(float(total["rev"]), 6),
        "total_subscriptions": int(total["cnt"]),
        "by_tier": {r["tier"]: {"count": int(r["cnt"]), "revenue": round(float(r["rev"]), 6)} for r in by_tier},
    }


def get_all_active_subscriptions() -> list[dict]:
    now = int(time.time())
    with _conn() as c:
        rows = c.execute("""
            SELECT * FROM subscriptions
            WHERE expires_at > ? AND (calls_total - calls_used) > 0
            ORDER BY expires_at DESC
        """, (now,)).fetchall()
    return [Subscription(
        address=r["address"], tier=r["tier"],
        calls_total=int(r["calls_total"]), calls_used=int(r["calls_used"]),
        activated_at=int(r["activated_at"]), expires_at=int(r["expires_at"]),
    ).to_dict() for r in rows]
