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

from app.config import ARC, DEFAULT_PRICES
from app.x402 import X402PaymentMiddleware, ledger
from providers.signals import (
    generate_whale_alert,
    generate_price_signal,
    generate_wallet_score,
    generate_sentiment,
    PROVIDERS,
)

# ── App Setup ───────────────────────────────────────────────────────

app = FastAPI(
    title="SignalPay",
    description="AI Agent Alpha Marketplace — signal feeds gated by x402 nanopayments on Arc",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
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
                    "price_oracle": "/signals/price/{token}",
                    "sentiment": "/signals/sentiment/{token}",
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


@app.get("/feed")
async def live_feed():
    """Latest signal from a random provider — public, for dashboard feed."""
    import random
    generators = [
        ("whale_alert", generate_whale_alert, {}),
        ("price_oracle", generate_price_signal, {"token": random.choice(["BTC", "ETH", "SOL", "ARC"])}),
        ("wallet_score", generate_wallet_score, {}),
        ("sentiment", generate_sentiment, {"token": random.choice(["BTC", "ETH", "SOL"])}),
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


# ── Agent Runner (SSE) ──────────────────────────────────────────────

@app.post("/agent/run")
async def run_agent_sse():
    """Run the buyer agent and stream log events via SSE."""
    from agents.buyer_agent import build_agent_graph, AgentConfig, AgentState

    async def event_stream():
        def emit(action: str, msg: str, state: dict | None = None, signal: dict | None = None) -> str:
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
            return f"data: {_json.dumps(event)}\n\n"

        config = AgentConfig()
        graph = build_agent_graph()
        initial_state: AgentState = {
            "messages": [{"role": "system", "content": "You are a SignalPay buyer agent."}],
            "budget_remaining": config.session_budget,
            "total_spent": 0.0,
            "providers": [],
            "selected_provider": None,
            "signal_data": None,
            "signals_collected": [],
            "action_plan": None,
            "reputation_feedback": [],
            "iteration": 0,
            "max_iterations": config.max_iterations,
            "_config": config,
        }

        yield emit("INIT", f"Agent session started. Budget: ${config.session_budget:.3f} USDC", initial_state)

        async for node_output in graph.astream(initial_state):
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
                    yield emit("SELECT", f"Evaluating: {provider.get('name','?')} — ${provider.get('price_usdc',0):.3f}/call — Rep: N/A", state)

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
                    score = feedback[-1].get("score", 0)
                    yield emit("REPUTATION", f"Reputation: scored {provider.get('name','provider')} → {score}/100", state)

            elif node_name == "analyze":
                action_plan = state.get("action_plan", "")
                yield emit("ANALYZE", "Analyzing signals for convergence...", state)
                await asyncio.sleep(0.6)
                if action_plan:
                    yield emit("ANALYZE", f"Decision: {action_plan}", state)

            elif node_name == "summarize":
                n = len(state.get("signals_collected", []))
                spent = state.get("total_spent", 0)
                remaining = state.get("budget_remaining", 0)
                yield emit("SUMMARY", f"═══ Session Complete: {n} signals | ${spent:.6f} spent | ${remaining:.6f} remaining ═══", state)

        yield f"data: {_json.dumps({'action': 'DONE'})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Startup ─────────────────────────────────────────────────────────

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
