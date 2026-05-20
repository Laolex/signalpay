"""
Chain registry for SignalPay GAP 6: crosschain provider routing.

Providers can be registered on any supported chain. The buyer agent
penalises providers on foreign chains via bridge_cost_usdc in the
composite routing score:

    chain_penalty = min(bridge_cost_usdc / 0.01, 0.20)   # up to -20%

Providers default to Arc Testnet (chain 5042002) — no bridge cost.
Assigning a provider to a foreign chain adds a realistic penalty that
the composite score subtracts from routing priority.

Supported chains (bridge cost = estimated USDC round-trip from Arc):
  5042002  Arc Testnet    native — $0.000
  8453     Base           ~$0.002
  42161    Arbitrum One   ~$0.003
  10       Optimism       ~$0.003
  137      Polygon        ~$0.002
  1        Ethereum       ~$0.008

DB: $CHAIN_DB_PATH or backend/data/chain.db
"""

from __future__ import annotations

import os
import sqlite3
import threading
import time

_DB_PATH = os.getenv(
    "CHAIN_DB_PATH",
    os.path.join(os.path.dirname(__file__), "..", "data", "chain.db"),
)
os.makedirs(os.path.dirname(_DB_PATH), exist_ok=True)

_lock = threading.Lock()

ARC_CHAIN_ID = 5042002

CHAIN_DEFS: dict[int, dict] = {
    5042002: {"name": "Arc Testnet",  "symbol": "ARC",   "color": "#00ccdd", "bridge_cost": 0.000},
    8453:    {"name": "Base",         "symbol": "BASE",  "color": "#4a9eff", "bridge_cost": 0.002},
    42161:   {"name": "Arbitrum One", "symbol": "ARB",   "color": "#00cc88", "bridge_cost": 0.003},
    10:      {"name": "Optimism",     "symbol": "OP",    "color": "#ff4455", "bridge_cost": 0.003},
    137:     {"name": "Polygon",      "symbol": "MATIC", "color": "#aa88ff", "bridge_cost": 0.002},
    1:       {"name": "Ethereum",     "symbol": "ETH",   "color": "#8888ff", "bridge_cost": 0.008},
}


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(_DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def _init_db():
    with _conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS provider_chains (
                provider_id   TEXT PRIMARY KEY,
                chain_id      INTEGER NOT NULL DEFAULT 5042002,
                registered_at INTEGER NOT NULL
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_pc_chain ON provider_chains(chain_id)")


_init_db()


def register_provider_chain(provider_id: str, chain_id: int):
    """Assign a provider to a chain. Upserts on conflict."""
    if chain_id not in CHAIN_DEFS:
        raise ValueError(f"Unsupported chain_id {chain_id}. Supported: {list(CHAIN_DEFS)}")
    now = int(time.time())
    with _lock:
        with _conn() as c:
            c.execute("""
                INSERT INTO provider_chains (provider_id, chain_id, registered_at)
                VALUES (?, ?, ?)
                ON CONFLICT(provider_id) DO UPDATE
                SET chain_id=excluded.chain_id, registered_at=excluded.registered_at
            """, (provider_id, chain_id, now))


def get_provider_chain(provider_id: str) -> int:
    """Return chain_id for a provider. Defaults to Arc if not registered."""
    with _conn() as c:
        row = c.execute(
            "SELECT chain_id FROM provider_chains WHERE provider_id=?",
            (provider_id,),
        ).fetchone()
    return int(row["chain_id"]) if row else ARC_CHAIN_ID


def get_all_provider_chains() -> dict[str, int]:
    """Map of provider_id → chain_id for all explicitly registered providers."""
    with _conn() as c:
        rows = c.execute(
            "SELECT provider_id, chain_id FROM provider_chains"
        ).fetchall()
    return {r["provider_id"]: int(r["chain_id"]) for r in rows}


def get_bridge_cost(from_chain: int, to_chain: int) -> float:
    """Estimated USDC bridge cost between chains. 0 if same chain."""
    if from_chain == to_chain:
        return 0.0
    return CHAIN_DEFS.get(to_chain, {}).get("bridge_cost", 0.005)


def get_chain_summary(chain_map: dict[str, int] | None = None) -> list[dict]:
    """All supported chains with bridge cost, routing penalty, and provider count."""
    if chain_map is None:
        chain_map = get_all_provider_chains()
    counts: dict[int, int] = {}
    for cid in chain_map.values():
        counts[cid] = counts.get(cid, 0) + 1

    result = []
    for chain_id, info in CHAIN_DEFS.items():
        bridge = info["bridge_cost"]
        result.append({
            "chain_id":         chain_id,
            "name":             info["name"],
            "symbol":           info["symbol"],
            "color":            info["color"],
            "bridge_cost_usdc": bridge,
            "penalty_pct":      round(min(bridge / 0.01, 0.20) * 100, 1),
            "native":           chain_id == ARC_CHAIN_ID,
            "provider_count":   counts.get(chain_id, 0),
        })
    return result
