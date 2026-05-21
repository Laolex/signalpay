"""
SignalPay API Server — Signal provider endpoints gated by x402 nanopayments.

Routes:
  GET  /                        → Health + server info
  GET  /discovery/providers     → List registered signal providers
  GET  /discovery/categories    → Available signal categories
  GET  /stats                   → Provider revenue stats

  # x402 gated — require nanopayment
  GET  /signals/whale-alert     → Latest whale movement alert
  GET  /signals/price/{token}   → Price feed for a token
  GET  /signals/wallet-score    → Wallet alpha/risk score
  GET  /signals/sentiment/{token} → Social sentiment signal

Usage:
  uvicorn app.server:app --host 0.0.0.0 --port 8000 --reload
"""

from __future__ import annotations

import asyncio
import json as _json
import os
import time
from dataclasses import asdict

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.config import ARC, DEFAULT_PRICES
from app.x402 import X402PaymentMiddleware, ledger
from app.governance import GovernancePolicy, daily_spent, daily_remaining
from providers.signals import (
    generate_whale_alert,
    generate_price_signal,
    generate_wallet_score,
    generate_sentiment,
    generate_trade_signal,
    generate_yield_intel,
    PROVIDERS,
)

# ── App Setup ───────────────────────────────────────────────────────

app = FastAPI(
    title="SignalPay",
    description="AI Agent Alpha Marketplace — signal feeds gated by x402 nanopayments on Arc",
    version="0.1.0",
)

_default_origins = "http://localhost:5173,http://localhost:3000"
_cors_origins = [
    o.strip() for o in os.getenv("CORS_ALLOW_ORIGINS", _default_origins).split(",") if o.strip()
]
_allow_credentials = os.getenv("CORS_ALLOW_CREDENTIALS", "false").lower() == "true"

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
    allow_credentials=_allow_credentials,
    expose_headers=["X-Payment-Required", "X-Payment-Confirmed", "X-Payment-Amount"],
)

PROVIDER_WALLET = os.getenv("PROVIDER_WALLET", "0x0000000000000000000000000000000000000000")

app.add_middleware(
    X402PaymentMiddleware,
    provider_wallet=PROVIDER_WALLET,
    default_price=2000,
)


# ── Public Routes (no payment required) ─────────────────────────────

@app.get("/")
async def health():
    return {
        "service": "SignalPay",
        "status": "operational",
        "network": "Arc Testnet",
        "chain_id": ARC.chain_id,
        "x402_enabled": True,
        "timestamp": int(time.time()),
    }


@app.get("/compliance/check/{address}")
async def compliance_check(address: str):
    """Compliance screening for a wallet address — risk tier, sanctions, flags."""
    from app.compliance import check_wallet
    try:
        result = check_wallet(address)
        return result.to_dict()
    except Exception as e:
        return {"address": address, "allowed": True, "risk_tier": "unknown", "error": str(e)}


@app.get("/discovery/providers")
async def list_providers():
    """List available signal providers and their pricing."""
    return {
        "providers": [
            {
                "id": category,
                "name": category.replace("_", " ").title(),
                "price_usdc": price / 1_000_000,
                "price_raw": price,
                "endpoint": {
                    "price_oracle":  "/signals/price/{token}",
                    "sentiment":     "/signals/sentiment/{token}",
                    "trade_signal":  "/signals/trade-signal/{token}",
                    "yield_intel":   "/signals/yield-intel",
                }.get(category, f"/signals/{category.replace('_', '-')}"),
                "x402": True,
            }
            for category, price in DEFAULT_PRICES.items()
        ]
    }


@app.get("/discovery/categories")
async def list_categories():
    """List available signal categories."""
    return {"categories": list(PROVIDERS.keys())}


@app.get("/stats")
async def provider_stats():
    """Provider revenue and call statistics."""
    return ledger.stats()


@app.get("/reputation")
async def all_reputation():
    """Multi-dimensional accuracy metrics for all providers (GAP 3)."""
    from app.reputation_store import get_all_metrics
    try:
        metrics = get_all_metrics()
        return {"providers": [m.to_dict() for m in metrics]}
    except Exception as e:
        return {"providers": [], "error": str(e)}


@app.get("/reputation/{provider_id}")
async def provider_reputation(provider_id: str):
    """Accuracy metrics for a specific provider — hit rate, Sharpe, composite."""
    from app.reputation_store import get_metrics
    try:
        return get_metrics(provider_id).to_dict()
    except Exception as e:
        return {"provider_id": provider_id, "error": str(e)}


@app.get("/economics")
async def economics_summary():
    """Lifetime spend analytics — totals, per-provider breakdown, daily history."""
    from app.economic_memory import get_spend_summary, get_provider_economics
    try:
        summary = get_spend_summary()
        summary["by_provider"] = get_provider_economics()
        return summary
    except Exception as e:
        return {"error": str(e)}


@app.get("/economics/sessions")
async def economics_sessions(user: str = Query(default="", description="Filter by wallet address"), limit: int = Query(default=20, ge=1, le=100)):
    """Session history with economic summary, newest first."""
    from app.economic_memory import get_session_history
    try:
        sessions = get_session_history(user_address=user or None, limit=limit)
        return {"sessions": sessions, "count": len(sessions)}
    except Exception as e:
        return {"sessions": [], "error": str(e)}


@app.get("/positions")
async def open_positions():
    """Open simulated positions with unrealized P&L (GAP 7)."""
    from app.trade_store import get_open_positions
    try:
        return {"positions": get_open_positions()}
    except Exception as e:
        return {"positions": [], "error": str(e)}


@app.get("/positions/history")
async def position_history(limit: int = Query(default=20, ge=1, le=100)):
    """Closed position history with realized P&L."""
    from app.trade_store import get_position_history
    try:
        return {"positions": get_position_history(limit=limit)}
    except Exception as e:
        return {"positions": [], "error": str(e)}


@app.get("/positions/performance")
async def position_performance():
    """Trade performance summary — win rate, total P&L, Sharpe."""
    from app.trade_store import get_performance_summary
    try:
        return get_performance_summary()
    except Exception as e:
        return {"error": str(e)}


@app.get("/chains")
async def chain_list():
    """Supported chains + bridge costs from Arc (GAP 6)."""
    from app.chain_registry import get_chain_summary
    return {"chains": get_chain_summary()}


@app.get("/chains/providers")
async def provider_chain_map():
    """Which chain each provider is registered on, with bridge cost info (GAP 6)."""
    from app.chain_registry import get_all_provider_chains, CHAIN_DEFS, ARC_CHAIN_ID
    chain_map = get_all_provider_chains()
    return {
        "providers": {
            pid: {
                "chain_id":         cid,
                "chain_name":       CHAIN_DEFS.get(cid, {}).get("name", "Unknown"),
                "symbol":           CHAIN_DEFS.get(cid, {}).get("symbol", "?"),
                "bridge_cost_usdc": CHAIN_DEFS.get(cid, {}).get("bridge_cost", 0.0),
                "native":           cid == ARC_CHAIN_ID,
                "penalty_pct":      round(min(CHAIN_DEFS.get(cid, {}).get("bridge_cost", 0.0) / 0.01, 0.20) * 100, 1),
            }
            for pid, cid in chain_map.items()
        }
    }


class ChainRegisterRequest(BaseModel):
    provider_id: str
    chain_id: int


@app.post("/chains/register")
async def register_provider_chain(body: ChainRegisterRequest):
    """Assign a provider to a settlement chain — affects routing penalty (GAP 6)."""
    from app.chain_registry import (
        register_provider_chain as _register,
        CHAIN_DEFS, get_bridge_cost, ARC_CHAIN_ID,
    )
    from fastapi.responses import JSONResponse as _JSONResponse
    try:
        _register(body.provider_id, body.chain_id)
    except ValueError as e:
        return _JSONResponse(status_code=400, content={"error": str(e)})
    chain = CHAIN_DEFS.get(body.chain_id, {})
    bridge = get_bridge_cost(ARC_CHAIN_ID, body.chain_id)
    return {
        "provider_id":      body.provider_id,
        "chain_id":         body.chain_id,
        "chain_name":       chain.get("name", "Unknown"),
        "bridge_cost_usdc": bridge,
        "penalty_pct":      round(min(bridge / 0.01, 0.20) * 100, 1),
        "native":           body.chain_id == ARC_CHAIN_ID,
    }


class BidRequest(BaseModel):
    provider_id: str
    bid_premium_pct: float   # 1.0 – 50.0
    duration_s: int = 300    # TTL seconds (60 – 3600)


@app.post("/auction/bid")
async def place_auction_bid(body: BidRequest):
    """Submit a routing-priority bid for a provider (GAP 5)."""
    from app.auction_store import place_bid as _place_bid
    from fastapi.responses import JSONResponse as _JSONResponse
    if not (1.0 <= body.bid_premium_pct <= 50.0):
        return _JSONResponse(status_code=400, content={"error": "bid_premium_pct must be 1–50"})
    if not (60 <= body.duration_s <= 3600):
        return _JSONResponse(status_code=400, content={"error": "duration_s must be 60–3600"})
    bid_id = _place_bid(body.provider_id, body.bid_premium_pct, body.duration_s)
    priority_boost = round(min(body.bid_premium_pct / 100, 0.50), 4)
    score_impact   = round(min(priority_boost * 0.15, 0.15), 4)
    return {
        "bid_id":          bid_id,
        "provider_id":     body.provider_id,
        "bid_premium_pct": body.bid_premium_pct,
        "priority_boost":  priority_boost,
        "score_impact":    score_impact,
        "duration_s":      body.duration_s,
        "dynamic_price_usdc": round(
            DEFAULT_PRICES.get(body.provider_id, 1000) / 1_000_000
            * (1 + body.bid_premium_pct / 100), 6
        ),
    }


@app.get("/auction/bids")
async def active_auction_bids():
    """List all currently active provider bids (GAP 5)."""
    from app.auction_store import get_active_bids, expire_old_bids
    expire_old_bids()
    bids = get_active_bids()
    return {"bids": [b.to_dict() for b in bids], "count": len(bids)}


@app.get("/auction/history")
async def auction_history(limit: int = Query(default=20, ge=1, le=100)):
    """Recent bid history — active and expired."""
    from app.auction_store import get_bid_history
    return {"history": get_bid_history(limit=limit)}


@app.get("/treasury")
async def treasury_summary():
    """Unified treasury: revenue, spend, net P&L, 14-day cashflow, governance state."""
    from app.economic_memory import get_treasury_summary
    from app.trade_store import get_performance_summary
    try:
        data = get_treasury_summary()
        try:
            data["trade_performance"] = get_performance_summary()
        except Exception:
            data["trade_performance"] = {}
        policy = GovernancePolicy.from_env()
        spent = daily_spent()
        data["governance"] = {
            "policy": policy.as_display(),
            "today_spent_usdc":     spent / 1_000_000,
            "today_remaining_usdc": daily_remaining(policy) / 1_000_000,
        }
        data["provider_wallet"] = PROVIDER_WALLET
        return data
    except Exception as e:
        return {"error": str(e)}


class StakeDepositRequest(BaseModel):
    provider_id: str
    amount_usdc: float


class StakeSlashRequest(BaseModel):
    provider_id: str
    reason: str = ""
    slash_amount: float = 0.0


@app.post("/stake/deposit")
async def stake_deposit(body: StakeDepositRequest):
    """Deposit USDC stake for a provider — activates stake_boost in routing (GAP 10)."""
    from app.stake_store import deposit_stake as _deposit
    from fastapi.responses import JSONResponse as _JSONResponse
    if body.amount_usdc <= 0:
        return _JSONResponse(status_code=400, content={"error": "amount_usdc must be > 0"})
    record = _deposit(body.provider_id, body.amount_usdc)
    return record.to_dict()


@app.post("/stake/slash")
async def stake_slash(body: StakeSlashRequest):
    """Record a slash event against a provider — activates slash_penalty in routing (GAP 10)."""
    from app.stake_store import slash_provider as _slash
    record = _slash(body.provider_id, body.reason, body.slash_amount)
    return record.to_dict()


@app.get("/stake/providers")
async def stake_providers():
    """Stake leaderboard + recent slash events (GAP 10)."""
    from app.stake_store import get_all_stakes, get_slash_history
    stakes = get_all_stakes()
    return {
        "stakes": [s.to_dict() for s in stakes],
        "slash_history": get_slash_history(limit=15),
        "count": len(stakes),
    }


@app.get("/governance/policy")
async def governance_policy():
    """Active spend governance policy."""
    policy = GovernancePolicy.from_env()
    spent = daily_spent()
    return {
        "policy": policy.as_display(),
        "today": {
            "spent_usdc": spent / 1_000_000,
            "remaining_usdc": daily_remaining(policy) / 1_000_000,
            "budget_usdc": policy.daily_budget / 1_000_000,
            "pct_used": round(spent / policy.daily_budget * 100, 1) if policy.daily_budget else 0,
        },
    }


@app.get("/feed")
async def live_feed():
    """Latest signal from a random provider — public, for dashboard feed."""
    import random
    # wallet_score requires an RPC call — keep it out of the fast public feed
    # trade_signal reuses cached price+sentiment — no extra API calls
    tokens = ["BTC", "ETH", "SOL"]
    generators = [
        ("whale_alert", generate_whale_alert, {}),
        ("price_oracle", generate_price_signal, {"token": random.choice(tokens)}),
        ("sentiment", generate_sentiment, {"token": random.choice(tokens)}),
        ("trade_signal", generate_trade_signal, {"token": random.choice(tokens)}),
        ("yield_intel", generate_yield_intel, {}),
    ]
    category, fn, kwargs = random.choice(generators)
    signal = fn(**kwargs)
    return {"signal": asdict(signal), "category": category}


# ── x402 Gated Signal Routes ───────────────────────────────────────
# These require a valid nanopayment via X-Payment header.
# Without payment → HTTP 402 with payment requirements.

@app.get("/signals/whale-alert")
async def whale_alert():
    """Get latest whale movement alert. Costs $0.002 USDC."""
    signal = generate_whale_alert()
    return {
        "signal": asdict(signal),
        "payment": "confirmed",
        "price_usdc": DEFAULT_PRICES["whale_alert"] / 1_000_000,
    }


@app.get("/signals/price/{token}")
async def price_feed(token: str):
    """Get price feed for a token. Costs $0.001 USDC."""
    signal = generate_price_signal(token=token.upper())
    return {
        "signal": asdict(signal),
        "payment": "confirmed",
        "price_usdc": DEFAULT_PRICES["price_oracle"] / 1_000_000,
    }


@app.get("/signals/wallet-score")
async def wallet_score(wallet: str = Query(default=None, description="Wallet address to score")):
    """Score a wallet's alpha/risk profile. Costs $0.005 USDC."""
    signal = generate_wallet_score(wallet_address=wallet)
    return {
        "signal": asdict(signal),
        "payment": "confirmed",
        "price_usdc": DEFAULT_PRICES["wallet_score"] / 1_000_000,
    }


@app.get("/signals/sentiment/{token}")
async def sentiment(token: str):
    """Get social sentiment for a token. Costs $0.003 USDC."""
    signal = generate_sentiment(token=token.upper())
    return {
        "signal": asdict(signal),
        "payment": "confirmed",
        "price_usdc": DEFAULT_PRICES["sentiment"] / 1_000_000,
    }


@app.get("/signals/trade-signal/{token}")
async def trade_signal(token: str):
    """
    Composite trade signal: price momentum + Fear & Greed + sentiment.
    Returns BUY / ACCUMULATE / HOLD / REDUCE / SELL with confidence. Costs $0.01 USDC.
    """
    signal = generate_trade_signal(token=token.upper())
    return {
        "signal": asdict(signal),
        "payment": "confirmed",
        "price_usdc": DEFAULT_PRICES["trade_signal"] / 1_000_000,
    }


@app.get("/signals/trade-signal")
async def trade_signal_default():
    """Composite trade signal for BTC (default). Costs $0.01 USDC."""
    signal = generate_trade_signal(token="BTC")
    return {
        "signal": asdict(signal),
        "payment": "confirmed",
        "price_usdc": DEFAULT_PRICES["trade_signal"] / 1_000_000,
    }


@app.get("/signals/yield-intel")
async def yield_intel():
    """Top USDC yield opportunities across DeFi — DefiLlama. Costs $0.003 USDC."""
    signal = generate_yield_intel()
    return {
        "signal": asdict(signal),
        "payment": "confirmed",
        "price_usdc": DEFAULT_PRICES["yield_intel"] / 1_000_000,
    }


# ── Subscription Tier (GAP 13) ───────────────────────────────────────

class SubscribeRequest(BaseModel):
    address: str
    tier: str = "basic"   # basic | pro | unlimited


@app.post("/subscribe")
async def subscribe(body: SubscribeRequest, request: Request):
    """
    Pay flat USDC fee to activate a signal subscription.
    Subscription bypasses per-call x402 payments via X-Subscriber-Address header.
    """
    from app.subscription_store import TIERS, activate_subscription
    tier_cfg = TIERS.get(body.tier)
    if not tier_cfg:
        return JSONResponse(status_code=400, content={"error": f"Unknown tier: {body.tier}. Valid: {list(TIERS)}"})

    payment_resp = await check_payment(request, "subscription", tier_cfg["price_micro"])
    if payment_resp:
        return payment_resp

    sub = activate_subscription(body.address, body.tier)
    return {
        "subscribed":      True,
        "subscription":    sub.to_dict(),
        "message": (
            f"Subscription active — {sub.calls_remaining} calls available "
            f"for {sub.seconds_remaining // 3600}h. "
            f"Include X-Subscriber-Address: {body.address} header to bypass per-call payments."
        ),
    }


@app.get("/subscribe/status")
async def subscription_status(address: str):
    """Check active subscription for an address."""
    from app.subscription_store import get_active_subscription
    sub = get_active_subscription(address.lower())
    if not sub:
        return {"active": False, "address": address.lower()}
    return {"active": True, **sub.to_dict()}


@app.get("/subscribe/tiers")
async def subscription_tiers():
    """Available subscription tiers and pricing."""
    from app.subscription_store import TIERS
    return {"tiers": TIERS}


@app.get("/subscribe/revenue")
async def subscription_revenue():
    """Subscription revenue summary and active subscribers."""
    from app.subscription_store import get_revenue_summary, get_all_active_subscriptions
    return {
        **get_revenue_summary(),
        "active_subscriptions": get_all_active_subscriptions(),
    }


# ── Composite Signal (GAP 11: Agent-as-Provider) ─────────────────────
# NOTE: specific routes (/earnings, /publish) must come before /{token}

@app.get("/signals/composite/earnings")
async def composite_earnings():
    """Provider earnings summary for the agent composite signal."""
    from app.composite_store import get_earnings_summary, get_composite_history
    return {
        **get_earnings_summary(),
        "history": get_composite_history(limit=10),
    }


class CompositePublishRequest(BaseModel):
    session_id:   str
    token:        str
    action:       str
    confidence:   float
    rationale:    str
    signal_count: int
    spend_usdc:   float
    raw_signals:  list = []


@app.post("/signals/composite/publish")
async def publish_composite_signal(body: CompositePublishRequest):
    """Internal: agent publishes its synthesized composite after a session."""
    from app.composite_store import publish_composite
    comp = publish_composite(
        session_id=body.session_id,
        token=body.token,
        action=body.action,
        confidence=body.confidence,
        rationale=body.rationale,
        signal_count=body.signal_count,
        spend_usdc=body.spend_usdc,
        raw_signals=body.raw_signals,
    )
    if comp:
        return {"published": True, "composite_id": comp.id, "token": comp.token}
    return {"published": False}


@app.get("/signals/composite/{token}")
async def composite_signal(token: str, request: Request):
    """Agent-synthesized composite signal. Costs $0.025 USDC."""
    from app.composite_store import get_latest_composite, record_composite_sale
    payment_resp = await check_payment(request, "composite_signal", DEFAULT_PRICES["composite_signal"])
    if payment_resp:
        return payment_resp
    comp = get_latest_composite(token) or get_latest_composite()
    if not comp:
        return {"signal": None, "message": "No composite signal published yet — run the agent first"}
    buyer = request.headers.get("X-Agent-Id", "anonymous")
    record_composite_sale(buyer, token)
    from dataclasses import asdict as _asdict
    sig = generate_composite_signal(token)
    return {
        "signal":    _asdict(sig),
        "payment":   "confirmed",
        "price_usdc": DEFAULT_PRICES["composite_signal"] / 1_000_000,
    }


@app.get("/signals/composite")
async def composite_signal_latest(request: Request):
    """Latest composite signal regardless of token. Costs $0.025 USDC."""
    return await composite_signal("BTC", request)


# ── Agent Wallet ─────────────────────────────────────────────────────

def _read_usdc_balance(address: str) -> tuple[float, int]:
    """Return (balance_usdc, balance_raw) for an address on Arc Testnet."""
    try:
        from web3 import Web3
        w3 = Web3(Web3.HTTPProvider(ARC.rpc, request_kwargs={"timeout": 10}))
        usdc = w3.eth.contract(
            address=Web3.to_checksum_address("0x3600000000000000000000000000000000000000"),
            abi=[{"inputs": [{"name": "account", "type": "address"}], "name": "balanceOf",
                  "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"}],
        )
        raw = usdc.functions.balanceOf(Web3.to_checksum_address(address)).call()
        return round(raw / 1_000_000, 6), raw
    except Exception:
        return 0.0, 0


def _derive_user_wallet(user_address: str):
    """
    Derive a deterministic per-user agent wallet.
    Uses HMAC-SHA256(user_address.lower(), AGENT_MASTER_SEED) as the private key.
    Falls back to BUYER_PRIVATE_KEY if AGENT_MASTER_SEED is not configured.
    """
    import hmac
    import hashlib
    from eth_account import Account
    from app.config import AGENT_MASTER_SEED

    if not user_address or user_address == "0x0":
        # No user address — fall back to shared key
        key = os.getenv("BUYER_PRIVATE_KEY") or os.getenv("PRIVATE_KEY") or ""
        return Account.from_key(key) if key else None

    if AGENT_MASTER_SEED:
        raw = hmac.new(
            AGENT_MASTER_SEED.encode(),
            user_address.lower().encode(),
            hashlib.sha256,
        ).digest()
        return Account.from_key(raw)

    # No seed configured — fall back to shared key
    key = os.getenv("BUYER_PRIVATE_KEY") or os.getenv("PRIVATE_KEY") or ""
    return Account.from_key(key) if key else None


@app.get("/agent/wallet")
async def agent_wallet(user: str = Query(default="", description="Connected wallet address")):
    """Per-user agent wallet address and live USDC balance on Arc Testnet."""
    try:
        acct = _derive_user_wallet(user)
        if not acct:
            return {"address": None, "balance_usdc": 0.0, "balance_raw": 0, "funded": False}
        balance_usdc, balance_raw = _read_usdc_balance(acct.address)
        return {
            "address": acct.address,
            "balance_usdc": balance_usdc,
            "balance_raw": balance_raw,
            "funded": balance_raw > 0,
        }
    except Exception as e:
        return {"address": None, "balance_usdc": 0.0, "balance_raw": 0, "funded": False, "error": str(e)}


# ── Agent Runner (SSE) ──────────────────────────────────────────────

class AgentRunRequest(dict):
    pass


class AgentRunBody(BaseModel):
    wallet_address: str = ""


@app.post("/agent/run")
async def run_agent_sse(body: AgentRunBody = None):
    """Run the buyer agent and stream log events via SSE."""
    from agents.buyer_agent import build_agent_graph, AgentConfig, AgentState

    user_address = (body.wallet_address if body else "") or ""

    async def event_stream():
        def emit(action: str, msg: str, state: dict | None = None, signal: dict | None = None, tx_hash: str | None = None) -> str:
            s = state or {}
            event = {
                "action": action,
                "msg": msg,
                "budget": s.get("budget_remaining", 0.10),
                "spent": s.get("total_spent", 0.0),
                "signals": len(s.get("signals_collected", [])),
            }
            if signal:
                event["signal"] = signal
            if tx_hash:
                event["tx_hash"] = tx_hash
            return f"data: {_json.dumps(event)}\n\n"

        config = AgentConfig()

        # GAP 4: open persistent session record
        from app.economic_memory import start_session as _start_session
        econ_session_id = _start_session(user_address or "", config.session_budget)

        # Compliance pre-check on user wallet before starting session
        if user_address:
            try:
                from app.compliance import check_wallet
                compliance = check_wallet(user_address)
                if not compliance.allowed:
                    yield f"data: {_json.dumps({'action': 'ERROR', 'msg': f'Session blocked: compliance tier={compliance.risk_tier} flags={compliance.flags}'})}\n\n"
                    yield f"data: {_json.dumps({'action': 'DONE'})}\n\n"
                    return
                if compliance.risk_tier in ("medium", "high"):
                    yield emit("INIT", f"Compliance: {compliance.risk_tier.upper()} risk wallet — monitoring active", None)
            except Exception:
                pass  # fail-open

        # Derive per-user agent wallet and read real on-chain balance
        agent_budget = config.session_budget
        session_key = ""
        try:
            acct = _derive_user_wallet(user_address)
            if acct:
                session_key = acct.key.hex() if hasattr(acct, "key") else ""
                balance_usdc, balance_raw = _read_usdc_balance(acct.address)
                if balance_raw > 0:
                    agent_budget = balance_usdc
        except Exception:
            pass

        graph = build_agent_graph()
        initial_state: AgentState = {
            "messages": [{"role": "system", "content": "You are a SignalPay buyer agent."}],
            "budget_remaining": agent_budget,
            "total_spent": 0.0,
            "providers": [],
            "selected_provider": None,
            "signal_data": None,
            "signals_collected": [],
            "action_plan": None,
            "reputation_feedback": [],
            "iteration": 0,
            "max_iterations": config.max_iterations,
            "signalpay_api_url": config.signalpay_api_url,
            "last_executed_action": "",
            "exec_fired": False,
            "session_private_key": session_key,
            "session_id": econ_session_id,     # GAP 4
            "user_address": user_address or "", # GAP 4
            "provider_latencies": {},           # GAP 1
        }

        yield emit("INIT", f"Agent session started. Budget: ${agent_budget:.6f} USDC", initial_state)

        try:
          stream = graph.astream(initial_state)
        except Exception as e:
          yield f"data: {_json.dumps({'action': 'ERROR', 'msg': str(e)})}\n\n"
          yield f"data: {_json.dumps({'action': 'DONE'})}\n\n"
          return

        async for node_output in stream:
          try:
            node_name = next(iter(node_output))
            state = node_output[node_name]

            if node_name == "discover":
                providers = state.get("providers", [])
                yield emit("DISCOVER", "Querying SignalRegistry on Arc...", state)
                await asyncio.sleep(0.4)
                yield emit("DISCOVER", f"Found {len(providers)} providers across {len(set(p.get('id','') for p in providers))} categories", state)

            elif node_name == "select_provider":
                provider = state.get("selected_provider")
                if provider:
                    # Pull score breakdown from agent messages (buyer_agent embeds it)
                    msgs = state.get("messages", [])
                    score_line = next(
                        (m.get("content","") if isinstance(m,dict) else getattr(m,"content","")
                         for m in reversed(msgs)
                         if "score=" in (m.get("content","") if isinstance(m,dict) else getattr(m,"content",""))),
                        None
                    )
                    score_str = f" | {score_line.split('|')[-1].strip()}" if score_line else ""
                    yield emit("SELECT", f"Evaluating: {provider.get('name','?')} — ${provider.get('price_usdc',0):.3f}/call{score_str}", state)

            elif node_name == "pay_and_fetch":
                provider = state.get("selected_provider") or {}
                endpoint = provider.get("endpoint", "/signals/?")
                price = provider.get("price_usdc", 0)
                signal = state.get("signal_data")

                yield emit("PAY", f"→ HTTP GET {endpoint}", state)
                await asyncio.sleep(0.3)
                yield emit("PAY", f"← HTTP 402 Payment Required — ${price:.3f} USDC", state)
                await asyncio.sleep(0.3)
                yield emit("PAY", "Signing EIP-3009 authorization...", state)
                await asyncio.sleep(0.3)
                yield emit("PAY", "→ Resubmitting with X-Payment header", state)
                await asyncio.sleep(0.3)

                if signal:
                    conf = signal.get("confidence", 0)
                    cat = signal.get("category", "?").upper()
                    yield emit("RECEIVE", f"✓ Paid ${price:.4f} → {cat} signal (conf: {int(conf*100)}%)", state, signal=signal)
                else:
                    yield emit("RECEIVE", f"✗ Failed to fetch signal from {endpoint}", state)

            elif node_name == "record_reputation":
                feedback = state.get("reputation_feedback", [])
                provider = state.get("selected_provider") or {}
                if feedback:
                    latest_fb = feedback[-1]
                    score = latest_fb.get("score", 0)
                    name = provider.get("name", "provider")
                    tx = latest_fb.get("tx_hash")
                    on_chain = latest_fb.get("on_chain", False)
                    yield emit("REPUTATION", f"Scored {name} → {score}/100", state)
                    if on_chain and tx:
                        yield emit("REPUTATION", f"On-chain write confirmed", state, tx_hash=tx)
                    elif not on_chain:
                        reason = latest_fb.get("error") or "no key configured"
                        yield emit("REPUTATION", f"Off-chain: {reason}", state)

            elif node_name == "analyze":
                action_plan = state.get("action_plan", "")
                yield emit("ANALYZE", "Analyzing signals for convergence...", state)
                await asyncio.sleep(0.6)
                if action_plan:
                    yield emit("ANALYZE", f"Decision: {action_plan}", state)

            elif node_name == "execute_action":
                if state.get("exec_fired"):
                    msgs = state.get("messages", [])
                    exec_content = next(
                        (m.get("content", "") if isinstance(m, dict) else getattr(m, "content", "")
                         for m in reversed(msgs)
                         if "EXECUTE" in (m.get("content", "") if isinstance(m, dict) else getattr(m, "content", ""))),
                        state.get("action_plan", "")
                    )
                    yield emit("EXECUTE", exec_content, state)

            elif node_name == "summarize":
                n = len(state.get("signals_collected", []))
                spent = state.get("total_spent", 0)
                remaining = state.get("budget_remaining", 0)
                yield emit("SUMMARY", f"═══ Session Complete: {n} signals | ${spent:.6f} spent | ${remaining:.6f} remaining ═══", state)

          except Exception as node_err:
            print(f"[sse] node error: {node_err}")
            yield f"data: {_json.dumps({'action': 'ERROR', 'msg': str(node_err)})}\n\n"

        yield f"data: {_json.dumps({'action': 'DONE'})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Startup ─────────────────────────────────────────────────────────

async def _reputation_resolver_loop():
    """Background task: resolve pending predictions every 15 minutes."""
    import asyncio
    from app.reputation_store import resolve_pending_predictions
    while True:
        await asyncio.sleep(900)
        try:
            resolved = await asyncio.to_thread(resolve_pending_predictions)
            if resolved:
                print(f"[reputation] resolved {resolved} pending predictions")
        except Exception as e:
            print(f"[reputation] resolver error: {e}")


_STOP_LOSS_PCT  = -5.0   # auto-close if unrealized P&L drops below -5%
_TAKE_PROFIT_PCT = 10.0  # auto-close if unrealized P&L rises above +10%


async def _position_tracker_loop():
    """Background: update unrealized P&L every 60s, auto-close on SL/TP breach."""
    import asyncio
    import httpx
    from app.trade_store import get_open_positions, update_unrealized_pnl, close_position

    _PYTH_IDS = {
        "BTC": "0xe62df6c8b4a85fe1a67db44dc12de5db330f7ac66b72dc658afedf0f4a415b43",
        "ETH": "0xff61491a931112ddf1bd8147cd1b641375f79f5825126d665480874634fd0ace",
        "SOL": "0xef0d8b6fda2ceba41da15d4095d1da392a0d2f8ed0c6c7bc0f4cfac8c280b56d",
    }

    while True:
        await asyncio.sleep(60)
        try:
            open_pos = get_open_positions()
            if not open_pos:
                continue

            tokens = set(p["token"] for p in open_pos if p["token"] in _PYTH_IDS)
            if not tokens:
                continue

            ids_qs = "&".join(f"ids[]={_PYTH_IDS[t]}" for t in tokens)
            async with httpx.AsyncClient(timeout=8) as client:
                resp = await client.get(
                    f"https://hermes.pyth.network/v2/updates/price/latest?{ids_qs}",
                    follow_redirects=True,
                )

            id_to_sym = {v.lower().lstrip("0x"): k for k, v in _PYTH_IDS.items()}
            prices: dict[str, float] = {}
            for feed in resp.json().get("parsed", []):
                sym = id_to_sym.get(feed["id"].lower().lstrip("0x"))
                if sym:
                    p = feed["price"]
                    prices[sym] = int(p["price"]) * (10 ** int(p["expo"]))

            if not prices:
                continue

            await asyncio.to_thread(update_unrealized_pnl, prices)

            # ── Auto-close: SL / TP ──────────────────────────────────
            for pos in open_pos:
                tok = pos["token"]
                current = prices.get(tok)
                if current is None:
                    continue
                entry = pos["entry_price"]
                if not entry:
                    continue
                if pos["direction"] == "long":
                    pnl_pct = (current - entry) / entry * 100
                else:
                    pnl_pct = (entry - current) / entry * 100

                if pnl_pct <= _STOP_LOSS_PCT:
                    reason = "SL_HIT"
                elif pnl_pct >= _TAKE_PROFIT_PCT:
                    reason = "TP_HIT"
                else:
                    continue

                closed = await asyncio.to_thread(close_position, pos["id"], current, reason)
                if closed:
                    sign = "+" if closed["pnl_usdc"] >= 0 else ""
                    print(
                        f"[positions] AUTO-CLOSE {reason} — {tok} @ ${current:,.2f} "
                        f"P&L {sign}${closed['pnl_usdc']:.4f} ({sign}{closed['pnl_pct']:.2f}%)"
                    )

            print(f"[positions] tick — {len(open_pos)} open, prices: {prices}")
        except Exception as e:
            print(f"[positions] tracker error: {e}")


@app.on_event("startup")
async def startup():
    print("\n══════════════════════════════════════════════")
    print("  SignalPay API — AI Agent Alpha Marketplace")
    print("══════════════════════════════════════════════")
    print(f"  Network:  Arc Testnet ({ARC.chain_id})")
    print(f"  Wallet:   {PROVIDER_WALLET}")
    print(f"  x402:     Enabled on /signals/*")
    print(f"  Signals:  {', '.join(PROVIDERS.keys())}")
    print("══════════════════════════════════════════════\n")

    import asyncio
    asyncio.create_task(_reputation_resolver_loop())
    print("[reputation] background resolver started (15-min cadence)")
    asyncio.create_task(_position_tracker_loop())
    print("[positions] background tracker started (5-min cadence)")
