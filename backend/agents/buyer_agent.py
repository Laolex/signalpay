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
from dataclasses import dataclass, field

from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages


# ── Provider Scoring Engine ─────────────────────────────────────────
#
# Single source of truth for how the agent ranks providers.
# All GAP extension points are stubbed here — populating a field
# activates it in the composite score automatically.
#
# GAP 1  (active)  — alpha_quality, cost_efficiency, reputation, latency (measured)
# GAP 5  (active)  — bid_premium, dynamic_price  → auction/dynamic pricing
# GAP 6  (active)  — chain_id, bridge_cost_usdc  → crosschain routing
# GAP 10 (active)  — stake_amount_usdc, slash_count → staking/slashing

@dataclass
class ProviderScore:
    provider_id: str
    name: str
    price_usdc: float

    # ── GAP 1: Core quality signals (active) ──────────────────────
    alpha_quality: float = 0.5      # signal confidence from last known call, 0–1
    cost_efficiency: float = 0.5    # 1 - (price / category_ceiling), 0–1
    reputation: float = 0.5         # ERC-8004 on-chain score / 100, 0–1
    latency: float = 0.8            # 1 - (response_ms / 5000), clamped 0–1

    # ── GAP 5: Auction / dynamic pricing (stub) ───────────────────
    # Providers submit bids when a signal is requested.
    # bid_premium > 0 means provider paid for routing priority.
    # dynamic_price overrides price_usdc when set by the auction layer.
    bid_premium: float = 0.0
    dynamic_price: float = 0.0

    # ── GAP 6: Crosschain routing (stub) ──────────────────────────
    # Agent will score settlement chains (Arc, Base, Solana) and route
    # to the one offering best cost + latency + liquidity depth.
    # bridge_cost_usdc penalises cross-chain providers.
    chain_id: int = 5042002         # Arc testnet default
    bridge_cost_usdc: float = 0.0
    chain_latency_ms: float = 0.0

    # ── GAP 10: Staking / slashing (active) ──────────────────────────
    # Providers bond USDC collateral. Stake boosts routing priority.
    # Each slash event decays the score permanently (5% per event).
    stake_amount_usdc: float = 0.0
    slash_count: int = 0

    @property
    def composite(self) -> float:
        """
        Weighted composite score, 0–1. Higher = preferred routing target.

        Weights (GAP 1, active):
          alpha_quality   45% — does this provider deliver useful signal?
          cost_efficiency 25% — how cheap relative to category peers?
          latency         20% — how fast is it?
          reputation      10% — on-chain ERC-8004 track record

        Modifiers (stubbed, activate by populating fields):
          GAP 5: +bid_premium bonus (max +15%)
          GAP 6: -bridge_cost penalty (max -20%)
          GAP 10: +stake_bonus (max +10%), -slash_penalty (5% per slash)
        """
        base = (
            self.alpha_quality   * 0.45 +
            self.cost_efficiency * 0.25 +
            self.latency         * 0.20 +
            self.reputation      * 0.10
        )
        # GAP 5
        auction_boost  = min(self.bid_premium * 0.15, 0.15)
        # GAP 6
        chain_penalty  = min(self.bridge_cost_usdc / 0.01, 0.20)
        # GAP 10
        stake_boost    = min(self.stake_amount_usdc / 100.0, 0.10)
        slash_penalty  = min(self.slash_count * 0.05, 0.25)

        return max(0.0, min(1.0,
            base + auction_boost - chain_penalty + stake_boost - slash_penalty
        ))

    def explain(self) -> str:
        return (
            f"score={self.composite:.3f} "
            f"[α={self.alpha_quality:.2f} cost={self.cost_efficiency:.2f} "
            f"rep={self.reputation:.2f} lat={self.latency:.2f}]"
        )


def _build_provider_scores(
    providers: list[dict],
    reputation_feedback: list[dict],
    budget: float,
    latency_map: dict[str, float] | None = None,
) -> list[ProviderScore]:
    """
    Build a ProviderScore for every affordable provider.

    alpha_quality comes from the reputation_store composite_accuracy (GAP 3 —
    measured hit rate + Sharpe), falling back to ERC-8004 feedback score, then 0.5.
    Category ceiling is the max price in that category (for cost_efficiency).
    latency_map carries measured response scores (0–1) from prior pay_and_fetch calls.
    """
    if not providers:
        return []

    # Category price ceilings for cost_efficiency normalisation
    cat_ceilings: dict[str, float] = {}
    for p in providers:
        cat = p.get("id", "")
        price = p.get("price_usdc", 0.001)
        cat_ceilings[cat] = max(cat_ceilings.get(cat, price), price)

    # Latest ERC-8004 reputation score per provider id (fallback)
    rep_map: dict[str, float] = {}
    for fb in reputation_feedback:
        pid = fb.get("provider_id", "")
        if pid:
            rep_map[pid] = fb.get("score", 50) / 100.0

    # GAP 3: multi-dimensional accuracy from reputation_store
    accuracy_map: dict[str, float] = {}
    try:
        from app.reputation_store import get_all_metrics
        for m in get_all_metrics():
            accuracy_map[m.provider_id] = m.composite_accuracy
    except Exception:
        pass  # fail-open — fall back to rep_map

    # GAP 5: load active auction bids once for this scoring pass
    bid_map: dict[str, any] = {}
    try:
        from app.auction_store import get_active_bids, expire_old_bids
        expire_old_bids()
        for b in get_active_bids():
            bid_map[b.provider_id] = b
    except Exception:
        pass  # fail-open — no auction data means no boost

    # GAP 6: load provider chain assignments once for this scoring pass
    _ARC = 5042002
    chain_map: dict[str, int] = {}
    try:
        from app.chain_registry import get_all_provider_chains, get_bridge_cost
        chain_map = get_all_provider_chains()
    except Exception:
        pass  # fail-open — unregistered providers default to Arc (zero penalty)

    # GAP 10: load provider stakes once for this scoring pass
    stake_map: dict[str, any] = {}
    try:
        from app.stake_store import get_stake_map
        stake_map = get_stake_map()
    except Exception:
        pass  # fail-open — no stake data means no boost/penalty

    scores: list[ProviderScore] = []
    for p in providers:
        price = p.get("price_usdc", 0.001)
        if price > budget:
            continue
        pid = p.get("id", "")
        ceiling = cat_ceilings.get(pid, price) or price
        cost_eff = 1.0 - (price / ceiling) if ceiling > 0 else 0.5

        # alpha_quality: measured accuracy > ERC-8004 feedback > default
        alpha = accuracy_map.get(pid) or rep_map.get(pid, 0.5)

        # GAP 1: measured latency score from prior calls; default 0.8 until observed
        latency_score = (latency_map or {}).get(pid, 0.8)

        # GAP 5: auction bid → priority_boost + dynamic_price
        bid = bid_map.get(pid)
        bid_premium   = bid.priority_boost if bid else 0.0
        dynamic_price = round(price * (1 + bid.bid_premium_pct / 100), 6) if bid else 0.0

        # GAP 6: crosschain bridge cost penalty
        provider_chain = chain_map.get(pid, _ARC)
        bridge_cost = 0.0
        if provider_chain != _ARC:
            try:
                bridge_cost = get_bridge_cost(_ARC, provider_chain)
            except Exception:
                pass

        # GAP 10: stake boost + slash penalty
        stake = stake_map.get(pid)
        stake_amount = stake.amount_usdc if stake else 0.0
        slash_count  = stake.slash_count  if stake else 0

        scores.append(ProviderScore(
            provider_id=pid,
            name=p.get("name", pid),
            price_usdc=price,
            alpha_quality=alpha,
            cost_efficiency=cost_eff,
            reputation=rep_map.get(pid, 0.5),
            latency=latency_score,
            bid_premium=bid_premium,
            dynamic_price=dynamic_price,
            chain_id=provider_chain,
            bridge_cost_usdc=bridge_cost,
            stake_amount_usdc=stake_amount,
            slash_count=slash_count,
        ))

    scores.sort(key=lambda s: s.composite, reverse=True)
    return scores


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
    signalpay_api_url: str           # API base URL (carried in state so LangGraph preserves it)
    last_executed_action: str        # Prevents re-executing the same decision on subsequent iterations
    exec_fired: bool                 # True only when execute_action actually ran this iteration
    session_private_key: str         # Per-user derived key for EIP-3009 signing
    session_id: str                  # GAP 4: economic memory session id
    user_address: str                # GAP 4: connected wallet (for per-user history)
    provider_latencies: dict         # GAP 1: pid → latency_score (0–1) from measured calls


# ── Agent Configuration ─────────────────────────────────────────────

@dataclass
class AgentConfig:
    signalpay_api_url: str = os.getenv("SIGNALPAY_API_URL", "http://localhost:8001")
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

    api_url = state.get("signalpay_api_url") or os.getenv("SIGNALPAY_API_URL", "http://localhost:8001")
    url = f"{api_url}/discovery/providers"

    try:
        resp = httpx.get(url, timeout=10)
        providers = resp.json().get("providers", [])
    except Exception as e:
        print(f"[agent] discover failed: {e}")
        providers = []

    # Sort by price (cheapest first)
    providers.sort(key=lambda p: p.get("price_raw", float("inf")))

    return {
        **state,
        "signalpay_api_url": api_url,
        "providers": providers,
        "messages": state["messages"] + [
            {"role": "assistant", "content": f"Discovered {len(providers)} signal providers."}
        ],
    }


def select_provider(state: AgentState) -> AgentState:
    """
    Score-driven provider selection.

    Phase 1 (iterations 0-4): warm-start — prefer the category that builds
    the best analytical context in sequence (price → sentiment → trade →
    whale → wallet). Within the preferred category, the highest composite
    score wins. If the preferred category is over budget or already scored,
    fall through to score-ranked open selection.

    Phase 2 (iteration 5+): pure score routing — highest ProviderScore.composite
    wins regardless of category. GAP 5 auction bids, GAP 6 chain costs, and
    GAP 10 stake bonuses all feed in here automatically once populated.
    """
    providers = state["providers"]
    iteration  = state["iteration"]
    budget     = state["budget_remaining"]
    rep        = state.get("reputation_feedback", [])

    WARM_START_SEQ = ["price_oracle", "sentiment", "trade_signal", "whale_alert", "wallet_score"]

    scored = _build_provider_scores(providers, rep, budget, latency_map=state.get("provider_latencies", {}))
    if not scored:
        return {
            **state,
            "selected_provider": None,
            "messages": state["messages"] + [
                {"role": "assistant", "content": f"No affordable providers. Budget: ${budget:.6f}"}
            ],
        }

    selected_score: ProviderScore | None = None

    if iteration < len(WARM_START_SEQ):
        target_id = WARM_START_SEQ[iteration]
        # Best-scored provider in the preferred category
        preferred = [s for s in scored if s.provider_id == target_id]
        if preferred:
            selected_score = preferred[0]

    # Phase 2 or fallback: top composite score across all categories
    if not selected_score:
        selected_score = scored[0]

    # Map back to the raw provider dict (agent loop expects a dict)
    selected = next(
        (p for p in providers if p.get("id") == selected_score.provider_id), None
    )
    if not selected:
        selected = providers[0]

    return {
        **state,
        "selected_provider": selected,
        "messages": state["messages"] + [
            {"role": "assistant", "content": (
                f"Selected: {selected_score.name} | "
                f"${selected_score.price_usdc:.4f}/call | "
                f"{selected_score.explain()}"
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

    api_url = state.get("signalpay_api_url") or os.getenv("SIGNALPAY_API_URL", "http://localhost:8001")
    endpoint = provider["endpoint"]
    url = f"{api_url}{endpoint}"

    # Handle parameterized routes — pick tokens by category
    category = provider.get("id", "")
    if "{token}" in url:
        token_map = {"price_oracle": "BTC", "sentiment": "BTC", "trade_signal": "BTC"}
        url = url.replace("{token}", token_map.get(category, "BTC"))

    pid = provider.get("id", "")
    _t0 = time.time()

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
            # Use per-user derived key from state (injected by /agent/run), then env fallback.
            private_key = (
                state.get("session_private_key")
                or os.getenv("BUYER_PRIVATE_KEY")
                or os.getenv("PRIVATE_KEY", "")
            )
            nonce = "0x" + secrets.token_hex(32)
            valid_before = int(time.time()) + 10 * 24 * 3600  # 10 days (must exceed maxTimeoutSeconds=432000)

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

        # GAP 1: compute latency score from total round-trip time
        elapsed_ms = (time.time() - _t0) * 1000
        latency_score = max(0.0, min(1.0, 1.0 - elapsed_ms / 5000.0))
        updated_latencies = {**state.get("provider_latencies", {}), pid: round(latency_score, 3)}

        if resp.status_code == 200:
            data = resp.json()
            signal = data.get("signal", {})
            price = provider.get("price_usdc", 0)

            # GAP 3: record prediction for outcome tracking (15-min resolution)
            try:
                from app.reputation_store import record_prediction
                record_prediction(provider.get("id", "unknown"), signal)
            except Exception:
                pass  # fail-open — never block signal delivery

            # GAP 4: record spend in persistent economic memory
            try:
                from app.economic_memory import record_spend
                receipt = getattr(state.get("payment_receipt", None), "payment_id", None)
                record_spend(
                    session_id=state.get("session_id", ""),
                    user_address=state.get("user_address", ""),
                    provider_id=provider.get("id", "unknown"),
                    category=signal.get("category", "unknown"),
                    cost_usdc=price,
                    confidence=float(signal.get("confidence", 0.5)),
                    payment_id=receipt,
                )
            except Exception:
                pass  # fail-open — never block signal delivery

            return {
                **state,
                "signal_data": signal,
                "signals_collected": state["signals_collected"] + [signal],
                "budget_remaining": state["budget_remaining"] - price,
                "total_spent": state["total_spent"] + price,
                "provider_latencies": updated_latencies,
                "messages": state["messages"] + [
                    {"role": "assistant", "content": (
                        f"✓ Paid ${price:.4f} → Received {signal.get('category', '?')} signal "
                        f"(confidence: {signal.get('confidence', '?')}, latency: {latency_score:.2f})"
                    )}
                ],
            }

    except Exception as e:
        print(f"[agent] pay_and_fetch error: {e}")

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

    # ── Real decision logic using live signal data ──────────────────
    action = "HOLD"
    reason_parts = []

    # Check if we have a trade_signal (composite — highest-value, use directly)
    trade_signals = [s for s in signals if s.get("category") == "trade_signal"]

    # Extract latest values from individual signals
    fng = None
    sentiment_label = None
    sentiment_score = 0.0
    price_change = 0.0
    token = "BTC"

    if sentiments:
        latest_sent = sentiments[-1].get("data", {})
        fng = latest_sent.get("fear_greed_index")
        sentiment_label = latest_sent.get("sentiment_label", "neutral")
        sentiment_score = latest_sent.get("sentiment_score", 0.0)
        token = latest_sent.get("token", "BTC")
        reason_parts.append(
            f"F&G={fng} ({latest_sent.get('fear_greed_label', '?')}) | "
            f"Community={latest_sent.get('community_votes_up_pct', '?')}% bullish"
        )

    if price_signals:
        latest_price = price_signals[-1].get("data", {})
        price_change = latest_price.get("change_24h_pct", 0.0)
        token = latest_price.get("token", token)
        reason_parts.append(
            f"{token} @ ${latest_price.get('price_usd', 0):,.2f} ({price_change:+.2f}% 24h)"
        )

    if whale_alerts:
        latest_whale = whale_alerts[-1].get("data", {})
        whale_amount = latest_whale.get("amount_usdc", 0)
        whale_status = latest_whale.get("status", "")
        if whale_status != "quiet" and whale_amount > 0:
            reason_parts.append(
                f"Whale: {whale_amount:.4f} USDC on Arc ({latest_whale.get('total_transfers_in_window', 0)} txs)"
            )

    # Trade signal composite — trust directly, it's already the synthesis
    if trade_signals:
        ts = trade_signals[-1].get("data", {})
        ts_action = ts.get("action", "HOLD")
        ts_rationale = ts.get("rationale", "")
        ts_token = ts.get("token", token)
        ts_fng = ts.get("fear_greed_index", fng)
        ts_composite = ts.get("composite_score", 0)
        reason_parts.append(
            f"TradeSignal: {ts_action} (composite={ts_composite:+.2f}, F&G={ts_fng})"
        )
        action = f"{ts_action} — {ts_rationale}" if ts_rationale else ts_action

    elif fng is not None:
        # Fall back to manual rules if no trade_signal yet
        extreme_fear = fng < 30
        extreme_greed = fng > 75
        moderate_fear = 30 <= fng < 45
        strong_bull_sentiment = sentiment_label == "bullish" and sentiment_score > 0.3
        strong_bear_sentiment = sentiment_label == "bearish" and sentiment_score < -0.3
        price_dumped = price_change < -5.0
        price_pumped = price_change > 5.0

        if extreme_fear and strong_bull_sentiment:
            action = f"BUY — extreme fear (F&G={fng}) with bullish community divergence — strong contrarian entry on {token}"
        elif extreme_fear and price_dumped:
            action = f"ACCUMULATE — extreme fear (F&G={fng}) on {price_change:.1f}% dip — high-conviction contrarian signal on {token}"
        elif extreme_fear:
            action = f"ACCUMULATE — extreme fear (F&G={fng}) — historically strong contrarian entry for {token}"
        elif extreme_greed and strong_bear_sentiment:
            action = f"SELL — extreme greed (F&G={fng}) + bearish community — distribution zone on {token}"
        elif extreme_greed:
            action = f"REDUCE — extreme greed (F&G={fng}) — trim exposure on {token}, rotate to cash"
        elif moderate_fear and strong_bull_sentiment:
            action = f"ACCUMULATE — fear (F&G={fng}) with bullish divergence — selective entry on {token}"
        elif strong_bull_sentiment and price_pumped:
            action = f"WATCH — bullish momentum on {token} but {price_change:.1f}% already moved — wait for pullback"
        elif 45 <= fng <= 55:
            action = f"HOLD — neutral market (F&G={fng}), no strong edge"
        else:
            action = f"HOLD — mixed signals (F&G={fng}, sentiment={sentiment_label}, {token} {price_change:+.1f}%)"

    else:
        action = f"HOLD — accumulating signals ({len(signals)} so far)"

    analysis = " | ".join(reason_parts) if reason_parts else "Insufficient data"

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

    # GAP 3: blend measured composite_accuracy with signal confidence for the
    # ERC-8004 score. When we have resolved history, weight it 60/40 over
    # self-reported confidence. Falls back to confidence-only if no data yet.
    confidence = float(signal.get("confidence", 0.5))
    category = signal.get("category", "unknown")

    accuracy_weight = confidence  # default
    try:
        from app.reputation_store import get_metrics
        metrics = get_metrics(provider.get("id", "unknown"))
        if metrics.resolved_count >= 5:
            accuracy_weight = (metrics.composite_accuracy * 0.6 + confidence * 0.4)
    except Exception:
        pass

    score = int(max(0.0, min(1.0, accuracy_weight)) * 100)

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


def execute_action(state: AgentState) -> AgentState:
    """
    Execute the trading decision.

    For BUY/ACCUMULATE: records the intent on-chain via ERC-8004, then opens a
    $10 simulated long position in trade_store (GAP 7).
    For SELL/REDUCE: logs exit signal, closes open positions for the token.
    For HOLD/WATCH: no-op.
    """
    from app.reputation import give_feedback

    action = state.get("action_plan", "HOLD") or "HOLD"
    signals = state.get("signals_collected", [])
    last_executed = state.get("last_executed_action", "")

    # Skip: HOLD/WATCH/empty, anything that looks like "No signals...", or already executed
    _skip_prefixes = ("HOLD", "WATCH", "No signals", "Mixed signals", "Accumulating")
    if any(action.startswith(p) for p in _skip_prefixes) or not action:
        return {**state, "exec_fired": False}
    if action == last_executed:
        return {**state, "exec_fired": False}

    # Determine direction
    is_buy = any(k in action for k in ("BUY", "ACCUMULATE"))
    is_sell = any(k in action for k in ("SELL", "REDUCE"))

    # ── Token + price from collected signals ───────────────────────
    token = "BTC"
    entry_price = 0.0
    conviction  = 0.5
    signal_ids: list[str] = []

    for preferred_cat in ("price_oracle", "trade_signal", "sentiment"):
        match = next((s for s in signals if s.get("category") == preferred_cat), None)
        if match:
            tok = match.get("data", {}).get("token")
            if tok:
                token = tok
            break

    for s in reversed(signals):
        if s.get("category") == "price_oracle":
            entry_price = float(s.get("data", {}).get("price_usd", 0.0) or 0.0)
            break

    for s in reversed(signals):
        if s.get("category") == "trade_signal":
            conviction = float(s.get("confidence", 0.5) or 0.5)
            break

    signal_ids = [s.get("signal_id", "") for s in signals if s.get("signal_id")]

    # Fallback: fetch price from Pyth if no price signal was purchased
    if entry_price <= 0:
        try:
            from providers.signals import generate_price_signal
            ps = generate_price_signal(token)
            entry_price = float(ps.data.get("price_usd", 0.0) or 0.0)
        except Exception:
            pass

    # ── Stable agent_id for ERC-8004 market-decision records ──────
    decision_agent_id = int(
        hashlib.sha256(b"signalpay_market_decision_v1").hexdigest()[:12], 16
    )
    score = 85 if is_buy else 20 if is_sell else 50
    tag2 = "accumulate" if is_buy else "reduce" if is_sell else "neutral"

    # Write decision on-chain via ERC-8004
    result = give_feedback(
        agent_id=decision_agent_id,
        score_0_100=score,
        tag1="market_decision",
        tag2=tag2,
        endpoint="arc_market",
    )

    # ── GAP 7: open / close simulated position ─────────────────────
    trade_msg = ""
    try:
        from app.trade_store import (
            open_position,
            close_open_positions_for_token,
            POSITION_SIZE_USDC,
        )
        session_id   = state.get("session_id", "")
        user_address = state.get("user_address", "")

        if is_buy and entry_price > 0:
            pos_id = open_position(
                session_id=session_id,
                user_address=user_address,
                token=token,
                direction="long",
                entry_price=entry_price,
                action_taken=action.split("—")[0].strip().split()[0],
                conviction=conviction,
                driving_signals=signal_ids,
            )
            trade_msg = (
                f" | POSITION OPEN: long {token} @ ${entry_price:,.2f} "
                f"(${POSITION_SIZE_USDC:.0f} simulated, conviction={conviction:.0%})"
            )

        elif is_sell and entry_price > 0:
            closed = close_open_positions_for_token(token, entry_price, session_id)
            if closed:
                pnl = sum(c["pnl_usdc"] for c in closed)
                pnl_pct = sum(c["pnl_pct"] for c in closed) / len(closed)
                sign = "+" if pnl >= 0 else ""
                trade_msg = (
                    f" | POSITION CLOSED: {token} @ ${entry_price:,.2f} "
                    f"P&L {sign}${pnl:.4f} ({sign}{pnl_pct:.2f}%)"
                )
            else:
                trade_msg = f" | No open {token} position to close"

    except Exception as e:
        trade_msg = f" | [trade_store error: {e}]"

    # Build the execution log line
    signals_summary = f"{len(signals)} signals purchased" if signals else "no signals"
    if is_buy:
        exec_msg = (
            f"EXECUTE: {action} | "
            f"Basis: {signals_summary} | "
            f"Settlement: Circle USDC on Arc"
        )
    else:
        exec_msg = f"EXECUTE: {action} | Basis: {signals_summary}"

    if result.submitted:
        exec_msg += f" | Decision recorded on Arc (tx {result.tx_hash[:10]}…)"
    else:
        exec_msg += f" | Decision logged [{result.reason or 'off-chain'}]"

    exec_msg += trade_msg

    return {
        **state,
        "last_executed_action": action,
        "exec_fired": True,
        "messages": state["messages"] + [
            {"role": "assistant", "content": exec_msg}
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
    """Bump the iteration counter and reset per-iteration flags."""
    return {**state, "iteration": state["iteration"] + 1, "exec_fired": False}


def summarize(state: AgentState) -> AgentState:
    """Final summary of the agent's session."""
    # GAP 4: close the session record with final economics
    try:
        from app.economic_memory import end_session
        providers_used = [
            s.get("category", "") for s in state.get("signals_collected", [])
        ]
        end_session(
            session_id=state.get("session_id", ""),
            spent_usdc=state["total_spent"],
            signals_count=len(state["signals_collected"]),
            action_taken=state.get("action_plan"),
            providers_used=providers_used,
        )
    except Exception:
        pass  # fail-open

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
    builder.add_node("execute_action", execute_action)
    builder.add_node("record_reputation", record_reputation)
    builder.add_node("increment", increment_iteration)
    builder.add_node("summarize", summarize)

    builder.set_entry_point("discover")
    builder.add_edge("discover", "select_provider")
    builder.add_edge("select_provider", "pay_and_fetch")
    builder.add_edge("pay_and_fetch", "record_reputation")
    builder.add_edge("record_reputation", "analyze")
    builder.add_edge("analyze", "execute_action")
    builder.add_edge("execute_action", "increment")
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
        "signalpay_api_url": config.signalpay_api_url,
        "last_executed_action": "",
        "exec_fired": False,
        "session_private_key": "",
        "session_id": "",
        "user_address": "",
        "provider_latencies": {},
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

    # ── GAP 11: publish composite signal so other agents can buy it ──
    _publish_composite(result, config)

    return result


def _publish_composite(state: dict, config: "AgentConfig"):
    """After session, synthesize collected signals and publish as a purchasable composite."""
    import requests as _req
    signals = state.get("signals_collected", [])
    if not signals:
        return
    action = state.get("last_executed_action", "HOLD")
    total_spent = state.get("total_spent", 0.0)
    session_id = state.get("session_id", "")

    # Derive token and confidence from the signal set
    token = "BTC"
    confidences = []
    raw_signal_summaries = []
    for s in signals:
        cat = s.get("category", "")
        d = s.get("data", {})
        tok = d.get("token")
        if tok and cat in ("price_oracle", "trade_signal"):
            token = tok
        conf = s.get("confidence", 0.0)
        if conf:
            confidences.append(conf)
        raw_signal_summaries.append({"category": cat, "confidence": conf})

    composite_confidence = round(sum(confidences) / len(confidences), 4) if confidences else 0.5
    rationale = (
        f"Synthesized from {len(signals)} signals costing ${total_spent:.4f} USDC. "
        f"Action: {action.split('—')[0].strip() if '—' in action else action}."
    )

    try:
        _req.post(
            f"{config.signalpay_api_url}/signals/composite/publish",
            json={
                "session_id":   session_id or "cli",
                "token":        token,
                "action":       action,
                "confidence":   composite_confidence,
                "rationale":    rationale,
                "signal_count": len(signals),
                "spend_usdc":   total_spent,
                "raw_signals":  raw_signal_summaries,
            },
            timeout=5,
        )
    except Exception:
        pass  # non-blocking — never crash the agent on publish failure


# ── CLI Entry ───────────────────────────────────────────────────────

if __name__ == "__main__":
    import asyncio
    asyncio.run(run_agent())
