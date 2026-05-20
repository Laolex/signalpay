"""
Auction store for SignalPay GAP 5: provider auction/bidding.

Providers bid a premium above their base price to boost routing priority.
A higher premium signals confidence and earns a composite-score bonus,
so the buyer agent preferentially routes to the highest active bidder.

Mechanics
---------
bid_premium_pct (1–50)  how much above base price the provider charges
                         when selected via auction
priority_boost           bid_premium_pct / 100, normalised 0–0.50
ProviderScore.composite  gains min(bid_premium * 0.15, 0.15) from the
                         auction_boost term already in the formula
dynamic_price            base_price * (1 + bid_premium_pct / 100)
                         — what the buyer actually pays for a bid-winner
TTL                      bids expire after duration_s (default 300 s)
Exclusivity              only one active bid per provider at a time;
                         placing a new bid deactivates the previous one

DB: $AUCTION_DB_PATH or backend/data/auction.db
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
import threading
import time
from dataclasses import dataclass
from typing import Optional

_DB_PATH = os.getenv(
    "AUCTION_DB_PATH",
    os.path.join(os.path.dirname(__file__), "..", "data", "auction.db"),
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
            CREATE TABLE IF NOT EXISTS bids (
                id              TEXT PRIMARY KEY,
                provider_id     TEXT NOT NULL,
                bid_premium_pct REAL NOT NULL,
                priority_boost  REAL NOT NULL,
                placed_at       INTEGER NOT NULL,
                expires_at      INTEGER NOT NULL,
                active          INTEGER NOT NULL DEFAULT 1
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_bids_provider ON bids(provider_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_bids_active ON bids(active, expires_at)")


_init_db()


@dataclass
class BidRecord:
    bid_id: str
    provider_id: str
    bid_premium_pct: float
    priority_boost: float
    placed_at: int
    expires_at: int
    active: bool

    @property
    def seconds_remaining(self) -> int:
        return max(0, self.expires_at - int(time.time()))

    def to_dict(self) -> dict:
        return {
            "bid_id":          self.bid_id,
            "provider_id":     self.provider_id,
            "bid_premium_pct": self.bid_premium_pct,
            "priority_boost":  self.priority_boost,
            "placed_at":       self.placed_at,
            "expires_at":      self.expires_at,
            "seconds_remaining": self.seconds_remaining,
            "score_impact":    round(min(self.priority_boost * 0.15, 0.15), 4),
        }


def place_bid(
    provider_id: str,
    bid_premium_pct: float,
    duration_s: int = 300,
) -> str:
    """Submit a bid for a provider. Deactivates any prior active bid."""
    now = int(time.time())
    bid_id = hashlib.sha256(
        f"{provider_id}:{now}:{bid_premium_pct}".encode()
    ).hexdigest()[:20]
    priority_boost = round(min(bid_premium_pct / 100.0, 0.50), 4)
    expires_at = now + duration_s

    with _lock:
        with _conn() as c:
            # Deactivate previous bids for this provider
            c.execute(
                "UPDATE bids SET active=0 WHERE provider_id=? AND active=1",
                (provider_id,),
            )
            c.execute("""
                INSERT INTO bids
                (id, provider_id, bid_premium_pct, priority_boost, placed_at, expires_at, active)
                VALUES (?,?,?,?,?,?,1)
            """, (bid_id, provider_id, bid_premium_pct, priority_boost, now, expires_at))

    return bid_id


def expire_old_bids():
    """Mark all past-TTL bids as inactive. Call once per scoring pass."""
    now = int(time.time())
    with _lock:
        with _conn() as c:
            c.execute(
                "UPDATE bids SET active=0 WHERE active=1 AND expires_at <= ?",
                (now,),
            )


def get_active_bids() -> list[BidRecord]:
    """Return all currently active (non-expired) bids, highest premium first."""
    now = int(time.time())
    with _conn() as c:
        rows = c.execute("""
            SELECT * FROM bids
            WHERE active=1 AND expires_at > ?
            ORDER BY bid_premium_pct DESC
        """, (now,)).fetchall()
    return [_row_to_bid(r) for r in rows]


def get_bid_for_provider(provider_id: str) -> Optional[BidRecord]:
    """Return the active bid for a specific provider, or None."""
    now = int(time.time())
    with _conn() as c:
        row = c.execute("""
            SELECT * FROM bids
            WHERE provider_id=? AND active=1 AND expires_at > ?
            ORDER BY bid_premium_pct DESC
            LIMIT 1
        """, (provider_id, now)).fetchone()
    return _row_to_bid(row) if row else None


def get_bid_history(limit: int = 20) -> list[dict]:
    """Recent bids (active + expired), newest first."""
    with _conn() as c:
        rows = c.execute("""
            SELECT * FROM bids ORDER BY placed_at DESC LIMIT ?
        """, (limit,)).fetchall()
    return [_row_to_bid(r).to_dict() | {"active": bool(r["active"])} for r in rows]


def _row_to_bid(row: sqlite3.Row) -> BidRecord:
    return BidRecord(
        bid_id=row["id"],
        provider_id=row["provider_id"],
        bid_premium_pct=float(row["bid_premium_pct"]),
        priority_boost=float(row["priority_boost"]),
        placed_at=int(row["placed_at"]),
        expires_at=int(row["expires_at"]),
        active=bool(row["active"]),
    )
