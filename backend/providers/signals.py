"""
Signal Provider Adapters — live data only.

Price:     Pyth Hermes REST (oracle-grade, ~400ms latency) → CoinGecko fallback
Sentiment: Alternative.me Fear & Greed + CoinGecko community votes
Whale:     Arc testnet USDC Transfer events via web3 eth_getLogs
Wallet:    Arc RPC — real USDC balance + nonce (tx count proxy)
Yield:     DefiLlama /pools — USDC stablecoin yield opportunities across DeFi
"""

from __future__ import annotations

import hashlib
import os
import time
from dataclasses import dataclass
from typing import Optional

import httpx
from web3 import Web3

from app.config import ARC, TOKENS


@dataclass
class Signal:
    provider: str
    category: str
    timestamp: int
    data: dict
    confidence: float   # 0.0–1.0
    signal_id: str


# ── TTL Cache ──────────────────────────────────────────────────────
_cache: dict[str, tuple[float, object]] = {}


def _cached(key: str, fn, ttl: float = 60.0):
    now = time.time()
    if key in _cache and now - _cache[key][0] < ttl:
        return _cache[key][1]
    result = fn()
    _cache[key] = (now, result)
    return result


# ── Arc RPC ────────────────────────────────────────────────────────
def _w3() -> Web3:
    return Web3(Web3.HTTPProvider(ARC.rpc, request_kwargs={"timeout": 10}))


# ERC-20 Transfer(address indexed from, address indexed to, uint256 value)
_TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"

# Minimal ERC-20 ABI — only what we need
_ERC20_ABI = [
    {
        "inputs": [{"name": "account", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
]


# ── Price Oracle (Pyth primary, CoinGecko fallback) ────────────────

_CG_IDS = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
    "USDC": "usd-coin",
    "ARC": None,
}

_CG_BASE = "https://api.coingecko.com/api/v3"

# Pyth Hermes price feed IDs (mainnet feeds — used for price only, not settlement)
_PYTH_IDS = {
    "BTC":  "0xe62df6c8b4a85fe1a67db44dc12de5db330f7ac66b72dc658afedf0f4a415b43",
    "ETH":  "0xff61491a931112ddf1bd8147cd1b641375f79f5825126d665480874634fd0ace",
    "SOL":  "0xef0d8b6fda2ceba41da15d4095d1da392a0d2f8ed0c6c7bc0f4cfac8c280b56d",
    "USDC": "0xeaa020c61cc479712813461ce153894a96a6c00b21ed0cfc2798d1f9a9e9c94a",
}
_PYTH_BASE = "https://hermes.pyth.network/v2/updates/price/latest"


def _fetch_pyth_prices() -> dict:
    """Fetch all tracked prices from Pyth Hermes in a single batched request."""
    ids_qs = "&".join(f"ids[]={v}" for v in _PYTH_IDS.values())
    resp = httpx.get(f"{_PYTH_BASE}?{ids_qs}", timeout=8, follow_redirects=True)
    resp.raise_for_status()
    parsed = resp.json().get("parsed", [])
    result: dict[str, dict] = {}
    # Invert _PYTH_IDS for lookup
    id_to_sym = {v.lower().lstrip("0x"): k for k, v in _PYTH_IDS.items()}
    for feed in parsed:
        sym = id_to_sym.get(feed["id"].lower().lstrip("0x"))
        if not sym:
            continue
        p = feed["price"]
        expo = int(p["expo"])
        price_usd = int(p["price"]) * (10 ** expo)
        # EMA price for 24h change approximation
        ema = feed.get("ema_price", {})
        ema_usd = int(ema.get("price", p["price"])) * (10 ** int(ema.get("expo", expo)))
        change_pct = ((price_usd - ema_usd) / ema_usd * 100) if ema_usd else 0.0
        result[sym] = {
            "price_usd": round(price_usd, 2),
            "change_24h_pct": round(change_pct, 4),
            "publish_time": int(p.get("publish_time", time.time())),
        }
    return result


def _fetch_cg_prices() -> dict:
    ids = ",".join(v for v in _CG_IDS.values() if v is not None)
    url = (
        f"{_CG_BASE}/simple/price"
        f"?ids={ids}&vs_currencies=usd"
        f"&include_24hr_change=true&include_24hr_vol=true"
        f"&include_24hr_high_low=true"
    )
    resp = httpx.get(url, timeout=10, follow_redirects=True)
    resp.raise_for_status()
    return resp.json()


def generate_price_signal(token: Optional[str] = None) -> Signal:
    token = (token or "ETH").upper()

    if token == "ARC":
        return Signal(
            provider="arc_price_oracle",
            category="price_oracle",
            timestamp=int(time.time()),
            data={"token": token, "price_usd": 1.0, "change_24h_pct": 0.0,
                  "volume_24h_usd": 0.0, "high_24h": 1.0, "low_24h": 1.0, "source": "usdc-peg"},
            confidence=1.0,
            signal_id=hashlib.sha256(f"price:{token}:{time.time()}".encode()).hexdigest()[:12],
        )

    # Try Pyth first (oracle-grade, ~400ms)
    source = "coingecko"
    price = change_24h = vol_24h = high = low = 0.0
    confidence = 0.92

    try:
        pyth = _cached("pyth_prices", _fetch_pyth_prices, ttl=15)
        tok_data = pyth.get(token)
        if tok_data:
            price      = tok_data["price_usd"]
            change_24h = tok_data["change_24h_pct"]
            # Pyth doesn't give 24h vol/high/low — estimate from price
            high = round(price * 1.008, 2)
            low  = round(price * 0.992, 2)
            vol_24h = 0.0
            source = "pyth"
            confidence = 0.99
    except Exception as exc:
        print(f"[signals] pyth fetch failed, falling back to coingecko: {exc}")

    if source == "coingecko" or price == 0.0:
        try:
            cg_id = _CG_IDS.get(token, "bitcoin")
            prices = _cached("cg_prices", _fetch_cg_prices, ttl=30)
            coin = prices.get(cg_id, {})
            price      = float(coin.get("usd", 0.0))
            change_24h = float(coin.get("usd_24h_change", 0.0))
            vol_24h    = float(coin.get("usd_24h_vol", 0.0))
            high       = float(coin.get("usd_24h_high", price * 1.01))
            low        = float(coin.get("usd_24h_low",  price * 0.99))
            source = "coingecko"
            confidence = 0.92
        except Exception as exc:
            print(f"[signals] coingecko also failed: {exc}")
            raise RuntimeError(f"Price feed unavailable: {exc}") from exc

    return Signal(
        provider="arc_price_oracle",
        category="price_oracle",
        timestamp=int(time.time()),
        data={
            "token": token,
            "price_usd": round(float(price), 2),
            "change_24h_pct": round(float(change_24h), 4),
            "volume_24h_usd": round(float(vol_24h), 2),
            "high_24h": round(float(high), 2),
            "low_24h": round(float(low), 2),
            "source": source,
        },
        confidence=confidence,
        signal_id=hashlib.sha256(f"price:{token}:{time.time()}".encode()).hexdigest()[:12],
    )


# ── Sentiment ──────────────────────────────────────────────────────

_FNG_URL = "https://api.alternative.me/fng/?limit=1"


def _fetch_fng() -> dict:
    resp = httpx.get(_FNG_URL, timeout=10, follow_redirects=True)
    resp.raise_for_status()
    return resp.json()


def _fetch_cg_community(cg_id: str) -> dict:
    url = f"{_CG_BASE}/coins/{cg_id}?localization=false&tickers=false&market_data=false&community_data=true&developer_data=false"
    resp = httpx.get(url, timeout=10, follow_redirects=True)
    resp.raise_for_status()
    return resp.json()


def generate_sentiment(token: Optional[str] = None) -> Signal:
    token = (token or "BTC").upper()
    cg_id = _CG_IDS.get(token, "bitcoin")

    try:
        fng = _cached("fng", _fetch_fng, ttl=300)
        fng_data = fng.get("data", [{}])[0]
        fng_value = int(fng_data.get("value", 50))
        fng_label = fng_data.get("value_classification", "Neutral")
    except Exception as exc:
        print(f"[signals] fng fetch failed: {exc}")
        raise RuntimeError(f"Sentiment feed unavailable: {exc}") from exc

    # Community votes from CoinGecko (token-specific)
    votes_up_pct = 50.0
    try:
        community = _cached(f"cg_community_{cg_id}", lambda: _fetch_cg_community(cg_id), ttl=120)
        cd = community.get("community_data") or {}
        sentiment_up = cd.get("sentiment_votes_up_percentage") or 50.0
        votes_up_pct = float(sentiment_up)
    except Exception:
        pass  # use default

    # Normalize F&G [0,100] → sentiment_score [-1, 1]
    sentiment_score = (fng_value - 50) / 50.0

    # Blend with community votes
    community_score = (votes_up_pct - 50) / 50.0
    blended = (sentiment_score * 0.6) + (community_score * 0.4)

    if blended > 0.2:
        label = "bullish"
    elif blended < -0.2:
        label = "bearish"
    else:
        label = "neutral"

    # Confidence is higher when signals agree
    agreement = 1.0 - abs(sentiment_score - community_score) / 2.0
    confidence = round(0.5 + agreement * 0.4, 3)

    return Signal(
        provider="sentiment_engine",
        category="sentiment",
        timestamp=int(time.time()),
        data={
            "token": token,
            "sentiment_score": round(blended, 4),
            "sentiment_label": label,
            "fear_greed_index": fng_value,
            "fear_greed_label": fng_label,
            "community_votes_up_pct": round(votes_up_pct, 1),
            "source": "alternative.me + coingecko",
        },
        confidence=confidence,
        signal_id=hashlib.sha256(f"sent:{token}:{time.time()}".encode()).hexdigest()[:12],
    )


# ── Whale Alert ────────────────────────────────────────────────────

def _fetch_arc_transfers(lookback_blocks: int = 300) -> list[dict]:
    w3 = _w3()
    latest = w3.eth.block_number
    from_block = max(0, latest - lookback_blocks)

    logs = w3.eth.get_logs({
        "fromBlock": from_block,
        "toBlock": "latest",
        "address": Web3.to_checksum_address(TOKENS.USDC),
        "topics": [_TRANSFER_TOPIC],
    })

    transfers = []
    for log in logs:
        topics = log["topics"]
        if len(topics) < 3:
            continue
        from_addr = "0x" + topics[1].hex()[-40:]
        to_addr = "0x" + topics[2].hex()[-40:]
        value = int(log["data"].hex(), 16) if log["data"] else 0
        transfers.append({
            "from": Web3.to_checksum_address(from_addr),
            "to": Web3.to_checksum_address(to_addr),
            "value_usdc": value / 1_000_000,
            "tx_hash": log["transactionHash"].hex(),
            "block": log["blockNumber"],
        })

    return sorted(transfers, key=lambda t: t["value_usdc"], reverse=True)


def generate_whale_alert() -> Signal:
    try:
        transfers = _cached("arc_transfers", _fetch_arc_transfers, ttl=20)
    except Exception as exc:
        print(f"[signals] whale fetch failed: {exc}")
        raise RuntimeError(f"Whale alert feed unavailable: {exc}") from exc

    if not transfers:
        # No USDC activity in the last 300 blocks — report that honestly
        return Signal(
            provider="whale_tracker_alpha",
            category="whale_alert",
            timestamp=int(time.time()),
            data={
                "status": "quiet",
                "message": "No USDC transfers on Arc in last 300 blocks",
                "chain": "arc-testnet",
                "monitored_contract": TOKENS.USDC,
            },
            confidence=0.5,
            signal_id=hashlib.sha256(f"whale:quiet:{time.time()}".encode()).hexdigest()[:12],
        )

    top = transfers[0]
    amount_usd = top["value_usdc"]

    # Confidence scales with transfer size: $0.001+ = 0.5, $1+ = 0.7, $10+ = 0.9
    if amount_usd >= 10:
        confidence = 0.92
    elif amount_usd >= 1:
        confidence = 0.75
    elif amount_usd >= 0.001:
        confidence = 0.60
    else:
        confidence = 0.50

    return Signal(
        provider="whale_tracker_alpha",
        category="whale_alert",
        timestamp=int(time.time()),
        data={
            "from_wallet": top["from"][:10] + "..." + top["from"][-6:],
            "to_wallet": top["to"][:10] + "..." + top["to"][-6:],
            "amount_usdc": round(amount_usd, 6),
            "tx_hash": top["tx_hash"][:18] + "...",
            "block": top["block"],
            "chain": "arc-testnet",
            "total_transfers_in_window": len(transfers),
            "direction": "transfer",
        },
        confidence=round(confidence, 3),
        signal_id=hashlib.sha256(f"whale:{top['tx_hash']}".encode()).hexdigest()[:12],
    )


# ── Wallet Score ───────────────────────────────────────────────────

def generate_wallet_score(wallet_address: Optional[str] = None) -> Signal:
    if not wallet_address:
        wallet_address = os.getenv("BUYER_WALLET") or os.getenv("PROVIDER_WALLET", "")

    if not wallet_address:
        raise RuntimeError("No wallet address to score — set BUYER_WALLET in .env")

    try:
        wallet_address = Web3.to_checksum_address(wallet_address)
    except Exception:
        raise RuntimeError(f"Invalid wallet address: {wallet_address}")

    cache_key = f"wallet_score:{wallet_address}"

    def _fetch():
        w3 = _w3()
        usdc_contract = w3.eth.contract(
            address=Web3.to_checksum_address(TOKENS.USDC),
            abi=_ERC20_ABI,
        )
        eth_balance = w3.eth.get_balance(wallet_address)
        usdc_balance = usdc_contract.functions.balanceOf(wallet_address).call()
        nonce = w3.eth.get_transaction_count(wallet_address)
        return {
            "eth_wei": eth_balance,
            "usdc_raw": usdc_balance,
            "tx_count": nonce,
        }

    try:
        on_chain = _cached(cache_key, _fetch, ttl=30)
    except Exception as exc:
        print(f"[signals] wallet score fetch failed: {exc}")
        raise RuntimeError(f"Wallet score feed unavailable: {exc}") from exc

    usdc_bal = on_chain["usdc_raw"] / 1_000_000
    # Arc native token is USDC-pegged, 18-decimal in get_balance (like ETH wei)
    native_bal = on_chain["eth_wei"] / 1e18
    tx_count = on_chain["tx_count"]

    # Simple composite score
    balance_score = min(50, usdc_bal * 10)          # $5 USDC → 50 pts
    activity_score = min(30, tx_count * 3)           # 10 txs → 30 pts
    native_score = min(20, native_bal * 10)          # $2 native → 20 pts
    composite = round(balance_score + activity_score + native_score, 1)

    confidence = round(min(0.95, 0.5 + tx_count * 0.02), 3)

    return Signal(
        provider="wallet_scorer_v1",
        category="wallet_score",
        timestamp=int(time.time()),
        data={
            "wallet": wallet_address[:10] + "..." + wallet_address[-6:],
            "usdc_balance": round(usdc_bal, 6),
            "native_balance": round(native_bal, 6),
            "tx_count": tx_count,
            "composite_score": composite,
            "chain": "arc-testnet",
            "source": "arc-rpc",
        },
        confidence=confidence,
        signal_id=hashlib.sha256(f"score:{wallet_address}:{time.time()}".encode()).hexdigest()[:12],
    )


# ── Trade Signal (composite) ───────────────────────────────────────

def generate_trade_signal(token: Optional[str] = None) -> Signal:
    """
    Composite signal: price momentum + Fear & Greed + community sentiment.
    Pulls from cache — no extra API calls if price/sentiment were recently fetched.
    Returns BUY / ACCUMULATE / HOLD / REDUCE / SELL with a confidence score.
    """
    token = (token or "BTC").upper()
    cg_id = _CG_IDS.get(token, "bitcoin")

    # ── Gather components ──────────────────────────────────────────
    price_sig = generate_price_signal(token)
    sentiment_sig = generate_sentiment(token)

    p = price_sig.data
    s = sentiment_sig.data

    change_24h: float = p.get("change_24h_pct", 0.0) or 0.0
    price_usd: float = p.get("price_usd", 0.0) or 0.0
    fng: int = int(s.get("fear_greed_index", 50))
    fng_label: str = s.get("fear_greed_label", "Neutral")
    community_up: float = float(s.get("community_votes_up_pct", 50.0) or 50.0)
    blended_sentiment: float = float(s.get("sentiment_score", 0.0) or 0.0)

    # ── Signals ────────────────────────────────────────────────────
    # Normalise momentum: ±10% move → ±1.0
    momentum = max(-1.0, min(1.0, change_24h / 10.0))

    # Fear & Greed: 0–100 → -1.0 (extreme fear) to +1.0 (extreme greed)
    fng_score = (fng - 50) / 50.0

    # Community divergence relative to F&G (positive = bullish divergence)
    community_score = (community_up - 50.0) / 50.0
    divergence = community_score - fng_score  # +ve = market more bullish than fear suggests

    # ── Weighted composite [-1, 1] ─────────────────────────────────
    composite = (
        momentum       * 0.35
        + fng_score    * 0.35
        + blended_sentiment * 0.20
        + divergence   * 0.10
    )
    composite = round(max(-1.0, min(1.0, composite)), 4)

    # ── Decision thresholds ────────────────────────────────────────
    extreme_fear  = fng < 25
    fear          = 25 <= fng < 40
    extreme_greed = fng > 80
    greed         = 65 < fng <= 80
    strong_bull   = community_up >= 65
    strong_bear   = community_up <= 35
    dip           = change_24h <= -3.0
    pump          = change_24h >= 3.0

    if extreme_fear and (strong_bull or dip):
        action = "BUY"
        rationale = f"Extreme Fear (F&G={fng}) + {'bullish community divergence' if strong_bull else f'{change_24h:.1f}% dip'} → high-conviction contrarian entry"
    elif extreme_fear:
        action = "ACCUMULATE"
        rationale = f"Extreme Fear (F&G={fng}) — historically strong contrarian zone; scale in"
    elif fear and strong_bull and not dip:
        action = "ACCUMULATE"
        rationale = f"Fear (F&G={fng}) with {community_up:.0f}% bullish community votes → fear/sentiment divergence"
    elif extreme_greed and (strong_bear or pump):
        action = "SELL"
        rationale = f"Extreme Greed (F&G={fng}) + {'bearish community' if strong_bear else f'+{change_24h:.1f}% pump'} → take profit"
    elif extreme_greed:
        action = "REDUCE"
        rationale = f"Extreme Greed (F&G={fng}) — trim exposure; keep core position"
    elif greed and strong_bear:
        action = "REDUCE"
        rationale = f"Greed (F&G={fng}) with bearish community divergence → risk-off"
    elif composite >= 0.3:
        action = "ACCUMULATE"
        rationale = f"Composite score {composite:+.2f} leans bullish across price/sentiment/momentum"
    elif composite <= -0.3:
        action = "REDUCE"
        rationale = f"Composite score {composite:+.2f} leans bearish across price/sentiment/momentum"
    else:
        action = "HOLD"
        rationale = f"Mixed signals (composite={composite:+.2f}, F&G={fng}) — no high-conviction edge"

    # Confidence: how strongly all signals agree
    signal_agreement = (
        abs(composite)                           # strong composite = high confidence
        * (1.0 - abs(divergence) * 0.3)         # penalise divergence
        * (1.0 if action != "HOLD" else 0.6)    # HOLD is inherently lower-confidence
    )
    confidence = round(min(0.97, 0.45 + signal_agreement * 0.5), 3)

    return Signal(
        provider="trade_signal_composite",
        category="trade_signal",
        timestamp=int(time.time()),
        data={
            "token": token,
            "action": action,
            "rationale": rationale,
            "composite_score": composite,
            "price_usd": price_usd,
            "change_24h_pct": round(change_24h, 4),
            "fear_greed_index": fng,
            "fear_greed_label": fng_label,
            "community_votes_up_pct": round(community_up, 1),
            "momentum": round(momentum, 4),
            "source": "coingecko + alternative.me",
        },
        confidence=confidence,
        signal_id=hashlib.sha256(f"trade:{token}:{time.time()}".encode()).hexdigest()[:12],
    )


# ── Yield Intelligence (DefiLlama) ────────────────────────────────

_DEFILLAMA_POOLS_URL = "https://yields.llama.fi/pools"


def _fetch_defi_pools() -> list:
    resp = httpx.get(_DEFILLAMA_POOLS_URL, timeout=12, follow_redirects=True)
    resp.raise_for_status()
    return resp.json().get("data", [])


def generate_yield_intel() -> Signal:
    """
    Top USDC yield opportunities across DeFi protocols.
    Filters for stablecoin pools, caps at 50% APY to exclude incentive farms,
    requires $5M+ TVL for protocol viability.
    """
    try:
        pools = _cached("defillama_pools", _fetch_defi_pools, ttl=300)
        usdc_pools = [
            p for p in pools
            if p.get("stablecoin")
            and "USDC" in p.get("symbol", "")
            and 0.1 < p.get("apy", 0) < 50
            and p.get("tvlUsd", 0) > 5_000_000
            and p.get("ilRisk", "yes") == "no"
        ]
        top = sorted(usdc_pools, key=lambda x: x.get("apy", 0), reverse=True)[:5]
    except Exception as exc:
        print(f"[signals] defillama fetch failed: {exc}")
        raise RuntimeError(f"Yield data unavailable: {exc}") from exc

    if not top:
        raise RuntimeError("No qualifying USDC yield pools found")

    best = top[0]
    avg_apy = round(sum(p["apy"] for p in top) / len(top), 2)

    opportunities = [
        {
            "protocol": p.get("project", "?"),
            "chain": p.get("chain", "?"),
            "symbol": p.get("symbol", "USDC"),
            "apy": round(p.get("apy", 0), 2),
            "apy_base": round(p.get("apyBase") or 0, 2),
            "apy_reward": round(p.get("apyReward") or 0, 2),
            "tvl_usd": round(p.get("tvlUsd", 0)),
        }
        for p in top
    ]

    confidence = min(0.95, 0.70 + (len(top) / 10))

    return Signal(
        provider="defillama_yield",
        category="yield_intel",
        timestamp=int(time.time()),
        data={
            "best_protocol": best.get("project", "?"),
            "best_chain": best.get("chain", "?"),
            "best_apy": round(best.get("apy", 0), 2),
            "avg_top5_apy": avg_apy,
            "opportunities": opportunities,
            "pool_count_scanned": len(usdc_pools),
            "source": "defillama",
        },
        confidence=confidence,
        signal_id=hashlib.sha256(f"yield:{time.time()}".encode()).hexdigest()[:12],
    )


# ── Provider Factory ───────────────────────────────────────────────

PROVIDERS = {
    "whale_alert": generate_whale_alert,
    "price_oracle": generate_price_signal,
    "wallet_score": generate_wallet_score,
    "sentiment": generate_sentiment,
    "trade_signal": generate_trade_signal,
    "yield_intel": generate_yield_intel,
}


def get_signal(category: str, **kwargs) -> Signal:
    generator = PROVIDERS.get(category)
    if generator is None:
        raise ValueError(f"Unknown provider category: {category}")
    return generator(**kwargs)
