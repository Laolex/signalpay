"""
SignalPay Buyer Agent — LangGraph-orchestrated AI agent that:

1. Discovers signal providers from the SignalRegistry (on-chain) or API discovery
2. Evaluates providers by reputation (ERC-8004) and price
3. Pays for signals via x402 nanopayments (EIP-3009 signed authorizations)
4. Processes received signals and decides next actions
5. Records provider reputation feedback on-chain

This is the demo centerpiece — shows an autonomous agent spending sub-cent
USDC to acquire alpha data, with zero gas per payment.

Usage:
  python -m agents.buyer_agent
"""

from __future__ import annotations

import json
import os
import secrets
import time
import hashlib
from typing import TypedDict, Annotated, Literal
from dataclasses import dataclass

from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages


# ── Agent State ─────────────────────────────────────────────────────

class AgentState(TypedDict):
    """State flowing through the LangGraph graph."""
    messages: Annotated[list, add_messages]
    budget_remaining: float          # USDC budget for this session
    total_spent: float               # Running spend total
    providers: list[dict]            # Discovered providers
    selected_provider: dict | None   # Currently selected provider
    signal_data: dict | None         # Last received signal
    signals_collected: list[dict]    # All signals this session
    action_plan: str | None          # What the agent decided to do
    reputation_feedback: list[dict]  # Feedback to record on-chain
    iteration: int                   # Current loop iteration
    max_iterations: int              # Stop after this many


# ── Agent Configuration ─────────────────────────────────────────────

@dataclass
class AgentConfig:
    signalpay_api_url: str = os.getenv("SIGNALPAY_API_URL", "http://localhost:8000")
    gateway_wallet: str = ""          # Circle Gateway wallet address
    private_key: str = ""             # For signing EIP-3009 authorizations
    session_budget: float = 0.10      # $0.10 budget per session
    max_iterations: int = 5


# ── Node Functions ──────────────────────────────────────────────────

def discover_providers(state: AgentState) -> AgentState:
    """
    Query the SignalPay API discovery endpoint (or on-chain SignalRegistry)
    to find available signal providers with pricing.
    """
    import httpx

    config = state.get("_config", AgentConfig())
    url = f"{config.signalpay_api_url}/discovery/providers"

    try:
        resp = httpx.get(url, timeout=10)
        providers = resp.json().get("providers", [])
    except Exception:
        providers = []

    # Sort by price (cheapest first)
    providers.sort(key=lambda p: p.get("price_raw", float("inf")))

    return {
        **state,
        "providers": providers,
        "messages": state["messages"] + [
            {"role": "assistant", "content": f"Discovered {len(providers)} signal providers."}
        ],
    }


def select_provider(state: AgentState) -> AgentState:
    """
    Select the best provider based on category need, price, and reputation.

    Strategy:
    - First iteration: whale alerts (most actionable)
    - Second: price oracle (context)
    - Third: sentiment (confirmation)
    - Subsequent: cheapest available
    """
    providers = state["providers"]
    iteration = state["iteration"]
    budget = state["budget_remaining"]

    category_priority = ["whale_alert", "price_oracle", "sentiment", "wallet_score"]
    target_category = category_priority[iteration % len(category_priority)]

    selected = None
    for p in providers:
        if target_category.replace("_", "-") in p.get("endpoint", ""):
            if p.get("price_usdc", 1) <= budget:
                selected = p
                break

    # Fallback: cheapest provider within budget
    if not selected:
        for p in providers:
            if p.get("price_usdc", 1) <= budget:
                selected = p
                break

    if not selected:
        return {
            **state,
            "selected_provider": None,
            "messages": state["messages"] + [
                {"role": "assistant", "content": f"No affordable providers. Budget: ${budget:.6f}"}
            ],
        }

    return {
        **state,
        "selected_provider": selected,
        "messages": state["messages"] + [
            {"role": "assistant", "content": (
                f"Selected: {selected['name']} | "
                f"${selected['price_usdc']:.4f}/call | "
                f"Endpoint: {selected['endpoint']}"
            )}
        ],
    }


def pay_and_fetch(state: AgentState) -> AgentState:
    """
    Pay for signal via x402 nanopayment and fetch the data.

    Flow:
    1. Send GET to signal endpoint (no payment header)
    2. Receive 402 with payment requirements
    3. Sign EIP-3009 authorization
    4. Resubmit with X-Payment header
    5. Receive signal data
    """
    import httpx

    provider = state["selected_provider"]
    if not provider:
        return {**state, "signal_data": None}

    config = state.get("_config", AgentConfig())
    endpoint = provider["endpoint"]
    url = f"{config.signalpay_api_url}{endpoint}"

    # Handle parameterized routes
    if "{token}" in url or "/price/" in endpoint:
        url = url.replace("{token}", "BTC")
    if "/sentiment/" in endpoint:
        url = f"{config.signalpay_api_url}/signals/sentiment/SOL"

    try:
        # Step 1: Request without payment → 402
        resp = httpx.get(url, timeout=10)

        if resp.status_code == 402:
            # Step 2: Parse payment requirements (x402 v2 format)
            x402 = resp.json().get("x402", {})
            accepts = x402.get("accepts", [{}])
            payment_req = accepts[0] if accepts else {}
            amount = int(payment_req.get("amount", "0"))
            recipient = payment_req.get("payTo", payment_req.get("recipient", ""))
            verifying_contract = payment_req.get("extra", {}).get(
                "verifyingContract", "0x0077777d7EBA4688BDeF3E311b846F25870A19B9"
            )

            # Step 3: Sign EIP-712 TransferWithAuthorization.
            # Prefer a buyer-specific key so the provider wallet's key isn't
            # reused on the buyer side.
            private_key = os.getenv("BUYER_PRIVATE_KEY") or os.getenv("PRIVATE_KEY", "")
            nonce = "0x" + secrets.token_hex(32)
            valid_before = int(time.time()) + 5 * 24 * 3600  # 5 days (Circle requires > 3 days)

            try:
                from eth_account import Account
                from eth_account.messages import encode_typed_data

                agent_address = Account.from_key(private_key).address if private_key else (config.gateway_wallet or "0xAgentWallet")

                typed_data = {
                    "types": {
                        "EIP712Domain": [
                            {"name": "name", "type": "string"},
                            {"name": "version", "type": "string"},
                            {"name": "chainId", "type": "uint256"},
                            {"name": "verifyingContract", "type": "address"},
                        ],
                        "TransferWithAuthorization": [
                            {"name": "from", "type": "address"},
                            {"name": "to", "type": "address"},
                            {"name": "value", "type": "uint256"},
                            {"name": "validAfter", "type": "uint256"},
                            {"name": "validBefore", "type": "uint256"},
                            {"name": "nonce", "type": "bytes32"},
                        ],
                    },
                    "primaryType": "TransferWithAuthorization",
                    "domain": {
                        "name": "GatewayWalletBatched",
                        "version": "1",
                        "chainId": 5042002,
                        "verifyingContract": verifying_contract,
                    },
                    "message": {
                        "from": agent_address,
                        "to": recipient,
                        "value": amount,
                        "validAfter": 0,
                        "validBefore": valid_before,
                        "nonce": nonce,
                    },
                }

                msg = encode_typed_data(full_message=typed_data)
                signed = Account.sign_message(msg, private_key=private_key)
                signature = signed.signature.hex()
                if not signature.startswith("0x"):
                    signature = "0x" + signature
            except Exception as e:
                # Without a real signature, the server's validator will reject
                # the request. We surface the failure instead of sending a
                # bogus signature that used to succeed under the old simulator.
                return {
                    **state,
                    "signal_data": None,
                    "messages": state["messages"] + [
                        {"role": "assistant", "content": (
                            f"✗ Cannot sign x402 authorization: {e}. "
                            f"Set BUYER_PRIVATE_KEY to enable real payments."
                        )}
                    ],
                }

            authorization = {
                "from": agent_address,
                "to": recipient,
                "value": str(amount),
                "validAfter": "0",
                "validBefore": str(valid_before),
                "nonce": nonce,
            }

            payment_header = json.dumps({"authorization": authorization, "signature": signature})

            # Step 4: Resubmit with payment
            resp = httpx.get(
                url,
                headers={"X-Payment": payment_header},
                timeout=10,
            )

        if resp.status_code == 200:
            data = resp.json()
            signal = data.get("signal", {})
            price = provider.get("price_usdc", 0)

            return {
                **state,
                "signal_data": signal,
                "signals_collected": state["signals_collected"] + [signal],
                "budget_remaining": state["budget_remaining"] - price,
                "total_spent": state["total_spent"] + price,
                "messages": state["messages"] + [
                    {"role": "assistant", "content": (
                        f"✓ Paid ${price:.4f} → Received {signal.get('category', '?')} signal "
                        f"(confidence: {signal.get('confidence', '?')})"
                    )}
                ],
            }

    except Exception:
        pass

    return {
        **state,
        "signal_data": None,
        "messages": state["messages"] + [
            {"role": "assistant", "content": f"✗ Failed to fetch signal from {endpoint}"}
        ],
    }


def analyze_signals(state: AgentState) -> AgentState:
    """
    Analyze collected signals and decide next action.

    In production: this calls an LLM (Claude) to reason about the signals.
    For the hackathon demo: rule-based analysis.
    """
    signals = state["signals_collected"]
    if not signals:
        return {
            **state,
            "action_plan": "No signals collected. Waiting.",
            "messages": state["messages"] + [
                {"role": "assistant", "content": "No signals to analyze yet."}
            ],
        }

    whale_alerts = [s for s in signals if s.get("category") == "whale_alert"]
    price_signals = [s for s in signals if s.get("category") == "price_oracle"]
    sentiments = [s for s in signals if s.get("category") == "sentiment"]

    analysis_parts = []

    if whale_alerts:
        latest = whale_alerts[-1]
        data = latest.get("data", {})
        analysis_parts.append(
            f"Whale alert: {data.get('direction', '?')} ${data.get('amount_usd', 0):,.0f} "
            f"{data.get('token', '?')} (whale score: {data.get('whale_score', '?')})"
        )

    if price_signals:
        latest = price_signals[-1]
        data = latest.get("data", {})
        analysis_parts.append(
            f"Price: {data.get('token', '?')} @ ${data.get('price_usd', 0):,.2f} "
            f"({data.get('change_24h_pct', 0):+.1f}%)"
        )

    if sentiments:
        latest = sentiments[-1]
        data = latest.get("data", {})
        analysis_parts.append(
            f"Sentiment: {data.get('token', '?')} → {data.get('sentiment_label', '?')} "
            f"(score: {data.get('sentiment_score', 0):.2f})"
        )

    action = "HOLD — insufficient signal convergence"
    if whale_alerts and any(
        s.get("data", {}).get("direction") in ("transfer_in", "stake")
        and s.get("confidence", 0) > 0.7
        for s in whale_alerts
    ):
        if sentiments and any(
            s.get("data", {}).get("sentiment_label") == "bullish"
            for s in sentiments
        ):
            action = "SIGNAL: Bullish convergence — whale accumulation + positive sentiment"
        else:
            action = "WATCH: Whale activity detected, awaiting sentiment confirmation"

    analysis = " | ".join(analysis_parts)

    return {
        **state,
        "action_plan": action,
        "messages": state["messages"] + [
            {"role": "assistant", "content": f"Analysis: {analysis}"},
            {"role": "assistant", "content": f"Decision: {action}"},
        ],
    }


def record_reputation(state: AgentState) -> AgentState:
    """
    Record provider reputation feedback on-chain via ERC-8004.

    Calls `ReputationRegistry.giveFeedback(...)` on Arc Testnet. If no buyer key
    is configured (or RPC is unreachable), we log the feedback locally and mark
    `tx_hash=None` so downstream tooling can tell real on-chain feedback from
    best-effort intent.

    Scoring: `confidence` in [0, 1] → score in [0, 100], clamped on-chain.
    """
    from app.reputation import give_feedback

    signal = state.get("signal_data")
    provider = state.get("selected_provider")

    if not signal or not provider:
        return state

    confidence = float(signal.get("confidence", 0.5))
    score = int(max(0.0, min(1.0, confidence)) * 100)
    category = signal.get("category", "unknown")

    # ERC-8004 agent IDs must be uint256. Provider dicts coming from the
    # discovery API expose a string-ish id — prefer an explicit `agent_id`,
    # fall back to a stable hash of the provider name so demos still run.
    agent_id = provider.get("agent_id")
    if agent_id is None:
        agent_id = int(
            hashlib.sha256(str(provider.get("name", "?")).encode()).hexdigest()[:12],
            16,
        )

    result = give_feedback(
        agent_id=int(agent_id),
        score_0_100=score,
        tag1="signal_quality",
        tag2=category,
        endpoint=provider.get("endpoint", ""),
    )

    feedback = {
        "provider_id": provider.get("id", "unknown"),
        "agent_id": int(agent_id),
        "score": score,
        "tag": f"signal_quality_{category}",
        "timestamp": int(time.time()),
        "tx_hash": result.tx_hash,
        "on_chain": result.submitted,
        "error": result.reason,
    }

    if result.submitted:
        msg = (
            f"Reputation ✓ on-chain: {provider.get('name', '?')} → {score}/100 "
            f"(tx {result.tx_hash[:10]}…)"
        )
    else:
        msg = (
            f"Reputation (off-chain): {provider.get('name', '?')} → {score}/100 "
            f"[{result.reason or 'not submitted'}]"
        )

    return {
        **state,
        "reputation_feedback": state["reputation_feedback"] + [feedback],
        "messages": state["messages"] + [
            {"role": "assistant", "content": msg}
        ],
    }


def should_continue(state: AgentState) -> Literal["select_provider", "end"]:
    """Decide whether to buy another signal or stop."""
    if state["iteration"] >= state["max_iterations"]:
        return "end"
    if state["budget_remaining"] <= 0.0005:
        return "end"
    if not state["providers"]:
        return "end"
    return "select_provider"


def increment_iteration(state: AgentState) -> AgentState:
    """Bump the iteration counter."""
    return {**state, "iteration": state["iteration"] + 1}


def summarize(state: AgentState) -> AgentState:
    """Final summary of the agent's session."""
    summary = (
        f"\n{'═' * 50}\n"
        f"  SignalPay Agent Session Summary\n"
        f"{'═' * 50}\n"
        f"  Signals purchased: {len(state['signals_collected'])}\n"
        f"  Total spent:       ${state['total_spent']:.6f} USDC\n"
        f"  Budget remaining:  ${state['budget_remaining']:.6f} USDC\n"
        f"  Action plan:       {state.get('action_plan', 'None')}\n"
        f"  Reputation scores: {len(state['reputation_feedback'])} recorded\n"
        f"{'═' * 50}"
    )

    return {
        **state,
        "messages": state["messages"] + [
            {"role": "assistant", "content": summary}
        ],
    }


# ── Graph Construction ──────────────────────────────────────────────

def build_agent_graph() -> StateGraph:
    """Build the LangGraph buyer agent graph."""
    builder = StateGraph(AgentState)

    builder.add_node("discover", discover_providers)
    builder.add_node("select_provider", select_provider)
    builder.add_node("pay_and_fetch", pay_and_fetch)
    builder.add_node("analyze", analyze_signals)
    builder.add_node("record_reputation", record_reputation)
    builder.add_node("increment", increment_iteration)
    builder.add_node("summarize", summarize)

    builder.set_entry_point("discover")
    builder.add_edge("discover", "select_provider")
    builder.add_edge("select_provider", "pay_and_fetch")
    builder.add_edge("pay_and_fetch", "record_reputation")
    builder.add_edge("record_reputation", "analyze")
    builder.add_edge("analyze", "increment")
    builder.add_conditional_edges("increment", should_continue, {
        "select_provider": "select_provider",
        "end": "summarize",
    })
    builder.add_edge("summarize", END)

    return builder.compile()


# ── Runner ──────────────────────────────────────────────────────────

async def run_agent(config: AgentConfig | None = None):
    """Run the SignalPay buyer agent."""
    if config is None:
        config = AgentConfig()

    graph = build_agent_graph()

    initial_state: AgentState = {
        "messages": [
            {"role": "system", "content": "You are a SignalPay buyer agent. Acquire alpha signals via nanopayments."}
        ],
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

    print("\n══════════════════════════════════════════════")
    print("  SignalPay Buyer Agent — Starting Session")
    print(f"  Budget: ${config.session_budget:.4f} USDC")
    print(f"  Max iterations: {config.max_iterations}")
    print("══════════════════════════════════════════════\n")

    result = await graph.ainvoke(initial_state)

    for msg in result["messages"]:
        role = getattr(msg, "type", None) or (msg.get("role", "?") if isinstance(msg, dict) else "?")
        content = getattr(msg, "content", None) or (msg.get("content", "") if isinstance(msg, dict) else "")
        if role in ("assistant", "ai"):
            print(f"  {content}")

    return result


# ── CLI Entry ───────────────────────────────────────────────────────

if __name__ == "__main__":
    import asyncio
    asyncio.run(run_agent())
