"""
Signal Provider Adapters.

Each adapter wraps a data source and exposes it as a signal.
For the hackathon, these generate realistic simulated data.
In production, the whale_alert adapter connects to your Solana alpha engine.
"""

from __future__ import annotations

import random
import time
import hashlib
from dataclasses import dataclass
from typing import Optional


@dataclass
class Signal:
    """Standard signal envelope returned by all providers."""
    provider: str
    category: str
    timestamp: int
    data: dict
    confidence: float  # 0.0 — 1.0
    signal_id: str


# ── Whale Alert Provider ───────────────────────────────────────────
# In production: connects to your Solana alpha engine (Helius API + PostgreSQL)

WHALE_WALLETS = [
    "5ZWj7a1f8tWkjBESHKgrLmXGcK...abc",
    "DRpbCBMxVnDK7maPM5tGv6MvB...xyz",
    "9WzDXwBbmkg8ZTbNMqUxvQRAy...def",
    "HN7cABqLq46Es1jh92dQQisAq...ghi",
]

TOKENS_LIST = ["SOL", "ETH", "BTC", "USDC", "BONK", "JUP", "WIF"]


def generate_whale_alert() -> Signal:
    """Generate a realistic whale movement alert."""
    wallet = random.choice(WHALE_WALLETS)
    token = random.choice(TOKENS_LIST)
    amount_usd = random.uniform(500_000, 50_000_000)
    direction = random.choice(["transfer_in", "transfer_out", "swap", "stake", "unstake"])

    # Higher amounts = higher confidence
    confidence = min(0.95, 0.5 + (amount_usd / 100_000_000))

    return Signal(
        provider="whale_tracker_alpha",
        category="whale_alert",
        timestamp=int(time.time()),
        data={
            "wallet": wallet[:12] + "..." + wallet[-4:],
            "token": token,
            "amount_usd": round(amount_usd, 2),
            "direction": direction,
            "chain": random.choice(["solana", "ethereum", "arc"]),
            "tx_hash": hashlib.sha256(f"{wallet}{time.time()}".encode()).hexdigest()[:16],
            "historical_pnl": round(random.uniform(-20, 200), 1),
            "whale_score": round(random.uniform(60, 99), 1),
        },
        confidence=round(confidence, 3),
        signal_id=hashlib.sha256(f"whale:{wallet}:{time.time()}".encode()).hexdigest()[:12],
    )


# ── Price Oracle Provider ──────────────────────────────────────────

PRICE_FEEDS = {
    "BTC": (65000, 70000),
    "ETH": (3200, 3800),
    "SOL": (140, 180),
    "ARC": (0.95, 1.05),
}


def generate_price_signal(token: Optional[str] = None) -> Signal:
    """Generate a price feed signal with OHLCV-style data."""
    if token is None:
        token = random.choice(list(PRICE_FEEDS.keys()))

    low, high = PRICE_FEEDS.get(token, (100, 200))
    price = random.uniform(low, high)
    change_pct = random.uniform(-5, 5)

    return Signal(
        provider="arc_price_oracle",
        category="price_oracle",
        timestamp=int(time.time()),
        data={
            "token": token,
            "price_usd": round(price, 2),
            "change_24h_pct": round(change_pct, 2),
            "volume_24h_usd": round(random.uniform(1e6, 1e9), 0),
            "high_24h": round(price * (1 + abs(change_pct) / 100), 2),
            "low_24h": round(price * (1 - abs(change_pct) / 100), 2),
            "source": random.choice(["binance", "coinbase", "aggregated"]),
        },
        confidence=round(random.uniform(0.85, 0.99), 3),
        signal_id=hashlib.sha256(f"price:{token}:{time.time()}".encode()).hexdigest()[:12],
    )


# ── Wallet Score Provider ──────────────────────────────────────────

def generate_wallet_score(wallet_address: Optional[str] = None) -> Signal:
    """Score a wallet's alpha/risk profile."""
    if wallet_address is None:
        wallet_address = random.choice(WHALE_WALLETS)

    return Signal(
        provider="wallet_scorer_v1",
        category="wallet_score",
        timestamp=int(time.time()),
        data={
            "wallet": wallet_address[:12] + "..." + wallet_address[-4:],
            "alpha_score": round(random.uniform(20, 95), 1),
            "risk_score": round(random.uniform(10, 80), 1),
            "trade_count_30d": random.randint(5, 500),
            "win_rate_30d": round(random.uniform(0.3, 0.8), 2),
            "avg_holding_hours": round(random.uniform(0.5, 720), 1),
            "total_pnl_30d_usd": round(random.uniform(-50000, 500000), 2),
            "is_whale": random.random() > 0.7,
            "labels": random.sample(
                ["dex_trader", "nft_flipper", "yield_farmer", "mev_bot", "diamond_hands", "paper_hands"],
                k=random.randint(1, 3),
            ),
        },
        confidence=round(random.uniform(0.7, 0.95), 3),
        signal_id=hashlib.sha256(f"score:{wallet_address}:{time.time()}".encode()).hexdigest()[:12],
    )


# ── Sentiment Provider ─────────────────────────────────────────────

def generate_sentiment(token: Optional[str] = None) -> Signal:
    """Social/news sentiment for a token."""
    if token is None:
        token = random.choice(["BTC", "ETH", "SOL", "ARC"])

    sentiment_score = random.uniform(-1, 1)

    return Signal(
        provider="sentiment_engine",
        category="sentiment",
        timestamp=int(time.time()),
        data={
            "token": token,
            "sentiment_score": round(sentiment_score, 3),
            "sentiment_label": "bullish" if sentiment_score > 0.2 else "bearish" if sentiment_score < -0.2 else "neutral",
            "mention_count_1h": random.randint(10, 5000),
            "top_source": random.choice(["twitter", "reddit", "telegram", "news"]),
            "trending_topics": random.sample(
                ["breakout", "accumulation", "dump", "partnership", "listing", "hack", "upgrade"],
                k=random.randint(1, 3),
            ),
        },
        confidence=round(random.uniform(0.5, 0.9), 3),
        signal_id=hashlib.sha256(f"sent:{token}:{time.time()}".encode()).hexdigest()[:12],
    )


# ── Provider Factory ───────────────────────────────────────────────

PROVIDERS = {
    "whale_alert": generate_whale_alert,
    "price_oracle": generate_price_signal,
    "wallet_score": generate_wallet_score,
    "sentiment": generate_sentiment,
}


def get_signal(category: str, **kwargs) -> Signal:
    """Get a signal from the specified provider category."""
    generator = PROVIDERS.get(category)
    if generator is None:
        raise ValueError(f"Unknown provider category: {category}")
    return generator(**kwargs)
