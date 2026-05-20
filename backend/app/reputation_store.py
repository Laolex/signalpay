"""
Multi-dimensional provider reputation store.

Tracks prediction accuracy over time:
  - Stores each signal's directional prediction at fetch time
  - 15 minutes later, checks Pyth for actual price movement
  - Computes hit rate, confidence calibration, Sharpe ratio per provider
  - composite_accuracy (0–1) feeds back into ProviderScore.alpha_quality

Backed by SQLite (no extra deps, persistent across restarts).
DB path: $REPUTATION_DB_PATH or backend/data/reputation.db

Sharpe definition used here:
  return_i = confidence_i * sign  (sign = +1 if hit, -0.5 if miss)
  sharpe   = mean(returns) / (std(returns) + 0.01)   — rolling last 20 resolved
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
    "REPUTATION_DB_PATH",
    os.path.join(os.path.dirname(__file__), "..", "data", "reputation.db"),
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
            CREATE TABLE IF NOT EXISTS predictions (
                id              TEXT PRIMARY KEY,
                provider_id     TEXT NOT NULL,
                category        TEXT NOT NULL,
                token           TEXT NOT NULL DEFAULT 'BTC',
                direction       TEXT,           -- 'up', 'down', 'neutral'
                predicted_price REAL,
                confidence      REAL NOT NULL,
                predicted_at    INTEGER NOT NULL,
                resolve_after   INTEGER NOT NULL,
                actual_price    REAL,
                resolved_at     INTEGER,
                hit             INTEGER,        -- 1=correct 0=wrong NULL=pending
                return_val      REAL            -- confidence-weighted return
            )
        """)
        c.execute("""
            CREATE INDEX IF NOT EXISTS idx_pred_provider ON predictions(provider_id)
        """)
        c.execute("""
            CREATE INDEX IF NOT EXISTS idx_pred_resolve ON predictions(resolve_after, resolved_at)
        """)


_init_db()


# ── Direction extraction ─────────────────────────────────────────────

def _extract_direction(signal: dict) -> tuple[str, str, float]:
    """
    Returns (direction, token, predicted_price) from a signal dict.
    direction: 'up' | 'down' | 'neutral'
    Only price_oracle, trade_signal, and sentiment carry measurable direction.
    """
    cat  = signal.get("category", "")
    data = signal.get("data", {})

    if cat == "trade_signal":
        token  = data.get("token", "BTC")
        price  = float(data.get("price_usd", 0.0) or 0.0)
        action = data.get("action", "HOLD")
        if action in ("BUY", "ACCUMULATE"):
            return "up", token, price
        if action in ("SELL", "REDUCE"):
            return "down", token, price
        return "neutral", token, price

    if cat == "price_oracle":
        token  = data.get("token", "BTC")
        price  = float(data.get("price_usd", 0.0) or 0.0)
        chg    = float(data.get("change_24h_pct", 0.0) or 0.0)
        if chg > 0.5:
            return "up", token, price
        if chg < -0.5:
            return "down", token, price
        return "neutral", token, price

    if cat == "sentiment":
        token = data.get("token", "BTC")
        label = data.get("sentiment_label", "neutral")
        if label == "bullish":
            return "up", token, 0.0
        if label == "bearish":
            return "down", token, 0.0
        return "neutral", token, 0.0

    return "neutral", "BTC", 0.0


# ── Prediction recording ─────────────────────────────────────────────

def record_prediction(provider_id: str, signal: dict, resolve_window: int = 900) -> str:
    """
    Store a new prediction. Returns the prediction id.
    resolve_window: seconds until outcome is checked (default 15 min).
    """
    direction, token, price = _extract_direction(signal)
    confidence = float(signal.get("confidence", 0.5) or 0.5)
    now = int(time.time())

    pred_id = hashlib.sha256(
        f"{provider_id}:{signal.get('signal_id', '')}:{now}".encode()
    ).hexdigest()[:20]

    with _lock:
        with _conn() as c:
            c.execute("""
                INSERT OR IGNORE INTO predictions
                (id, provider_id, category, token, direction, predicted_price,
                 confidence, predicted_at, resolve_after)
                VALUES (?,?,?,?,?,?,?,?,?)
            """, (
                pred_id,
                provider_id,
                signal.get("category", "unknown"),
                token,
                direction,
                price if price > 0 else None,
                confidence,
                now,
                now + resolve_window,
            ))

    return pred_id


# ── Outcome resolution ───────────────────────────────────────────────

def resolve_pending_predictions() -> int:
    """
    Fetch current Pyth prices and resolve all pending predictions whose
    resolve_after has passed. Returns number of predictions resolved.
    """
    now = int(time.time())

    with _lock:
        with _conn() as c:
            rows = c.execute("""
                SELECT id, token, direction, predicted_price, confidence
                FROM predictions
                WHERE resolved_at IS NULL
                  AND resolve_after <= ?
                  AND direction != 'neutral'
            """, (now,)).fetchall()

    if not rows:
        return 0

    # Fetch current prices for needed tokens
    tokens_needed = set(r["token"] for r in rows if r["token"] in ("BTC", "ETH", "SOL"))
    prices: dict[str, float] = {}
    if tokens_needed:
        try:
            import httpx
            _PYTH_IDS = {
                "BTC":  "0xe62df6c8b4a85fe1a67db44dc12de5db330f7ac66b72dc658afedf0f4a415b43",
                "ETH":  "0xff61491a931112ddf1bd8147cd1b641375f79f5825126d665480874634fd0ace",
                "SOL":  "0xef0d8b6fda2ceba41da15d4095d1da392a0d2f8ed0c6c7bc0f4cfac8c280b56d",
            }
            ids_qs = "&".join(f"ids[]={_PYTH_IDS[t]}" for t in tokens_needed if t in _PYTH_IDS)
            resp = httpx.get(
                f"https://hermes.pyth.network/v2/updates/price/latest?{ids_qs}",
                timeout=8,
                follow_redirects=True,
            )
            resp.raise_for_status()
            parsed = resp.json().get("parsed", [])
            id_to_sym = {v.lower().lstrip("0x"): k for k, v in _PYTH_IDS.items()}
            for feed in parsed:
                sym = id_to_sym.get(feed["id"].lower().lstrip("0x"))
                if sym:
                    p = feed["price"]
                    prices[sym] = int(p["price"]) * (10 ** int(p["expo"]))
        except Exception as e:
            print(f"[reputation_store] pyth fetch failed: {e}")
            return 0

    resolved_count = 0
    with _lock:
        with _conn() as c:
            for row in rows:
                token     = row["token"]
                direction = row["direction"]
                pred_price = row["predicted_price"]
                confidence = row["confidence"]
                actual_price = prices.get(token)

                if actual_price is None or actual_price <= 0:
                    # Skip tokens we couldn't price (e.g. sentiment with no price)
                    if pred_price is None:
                        # Sentiment without a baseline price — can't resolve
                        # Mark as neutral outcome to clear the queue
                        c.execute("""
                            UPDATE predictions
                            SET resolved_at=?, actual_price=NULL, hit=NULL, return_val=0
                            WHERE id=?
                        """, (now, row["id"]))
                        resolved_count += 1
                    continue

                # Hit: price moved in predicted direction
                if direction == "up":
                    hit = 1 if (actual_price > (pred_price or actual_price - 1)) else 0
                elif direction == "down":
                    hit = 1 if (actual_price < (pred_price or actual_price + 1)) else 0
                else:
                    hit = None

                if hit is None:
                    return_val = 0.0
                elif hit == 1:
                    return_val = confidence
                else:
                    return_val = -confidence * 0.5  # Asymmetric: penalize wrong but less

                c.execute("""
                    UPDATE predictions
                    SET resolved_at=?, actual_price=?, hit=?, return_val=?
                    WHERE id=?
                """, (now, actual_price, hit, return_val, row["id"]))
                resolved_count += 1

    if resolved_count:
        print(f"[reputation_store] resolved {resolved_count} predictions")
    return resolved_count


# ── Metrics computation ──────────────────────────────────────────────

@dataclass
class ProviderMetrics:
    provider_id: str
    total_signals: int = 0
    resolved_count: int = 0
    pending_count: int = 0
    hit_rate: float = 0.5
    avg_confidence: float = 0.5
    sharpe_ratio: float = 0.0
    composite_accuracy: float = 0.5
    last_updated: int = field(default_factory=lambda: int(time.time()))

    def to_dict(self) -> dict:
        return {
            "provider_id": self.provider_id,
            "total_signals": self.total_signals,
            "resolved_count": self.resolved_count,
            "pending_count": self.pending_count,
            "hit_rate": round(self.hit_rate, 4),
            "avg_confidence": round(self.avg_confidence, 4),
            "sharpe_ratio": round(self.sharpe_ratio, 4),
            "composite_accuracy": round(self.composite_accuracy, 4),
            "last_updated": self.last_updated,
            "data_quality": (
                "high" if self.resolved_count >= 20 else
                "medium" if self.resolved_count >= 5 else
                "low"
            ),
        }


def get_metrics(provider_id: str) -> ProviderMetrics:
    """Compute rolling metrics for a provider from stored predictions."""
    with _conn() as c:
        total = c.execute(
            "SELECT COUNT(*) FROM predictions WHERE provider_id=?", (provider_id,)
        ).fetchone()[0]

        pending = c.execute(
            "SELECT COUNT(*) FROM predictions WHERE provider_id=? AND resolved_at IS NULL",
            (provider_id,),
        ).fetchone()[0]

        resolved_rows = c.execute("""
            SELECT hit, confidence, return_val
            FROM predictions
            WHERE provider_id=? AND hit IS NOT NULL
            ORDER BY resolved_at DESC
            LIMIT 30
        """, (provider_id,)).fetchall()

        avg_conf_row = c.execute(
            "SELECT AVG(confidence) FROM predictions WHERE provider_id=?", (provider_id,)
        ).fetchone()[0]

    resolved_count = len(resolved_rows)
    avg_confidence = float(avg_conf_row or 0.5)

    if resolved_count == 0:
        return ProviderMetrics(
            provider_id=provider_id,
            total_signals=total,
            resolved_count=0,
            pending_count=pending,
            avg_confidence=avg_confidence,
        )

    hits = [r["hit"] for r in resolved_rows if r["hit"] is not None]
    hit_rate = sum(hits) / len(hits) if hits else 0.5

    returns = [float(r["return_val"] or 0.0) for r in resolved_rows]

    # Sharpe: mean / (std + 0.01) — rolling last 30 resolved
    if len(returns) >= 2:
        mean_r = statistics.mean(returns)
        std_r  = statistics.stdev(returns) if len(returns) >= 2 else 0.01
        sharpe = mean_r / (std_r + 0.01)
    else:
        sharpe = 0.0

    # composite_accuracy: meaningful only when resolved_count >= 5
    if resolved_count >= 5:
        # Blend hit_rate (40%), Sharpe contribution (30%), confidence (30%)
        sharpe_contrib = min(max(sharpe, -1.0), 1.0) * 0.5  # maps [-1,1] → [-0.5,+0.5]
        composite = 0.40 * hit_rate + 0.30 * (0.5 + sharpe_contrib) + 0.30 * avg_confidence
    else:
        # Sparse data — trust confidence + small hit_rate signal
        composite = 0.6 * avg_confidence + 0.4 * hit_rate

    composite = round(min(0.95, max(0.10, composite)), 4)

    return ProviderMetrics(
        provider_id=provider_id,
        total_signals=total,
        resolved_count=resolved_count,
        pending_count=pending,
        hit_rate=round(hit_rate, 4),
        avg_confidence=round(avg_confidence, 4),
        sharpe_ratio=round(sharpe, 4),
        composite_accuracy=composite,
        last_updated=int(time.time()),
    )


def get_all_metrics() -> list[ProviderMetrics]:
    """Metrics for every provider that has at least one recorded prediction."""
    with _conn() as c:
        provider_ids = [
            r[0] for r in c.execute(
                "SELECT DISTINCT provider_id FROM predictions"
            ).fetchall()
        ]
    return [get_metrics(pid) for pid in provider_ids]
