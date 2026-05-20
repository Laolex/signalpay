# SignalPay — Governed Agent Payment Infrastructure

> The first API marketplace where AI agents pay per call in USDC, governed by programmable spend policy, settled on Arc in under a second.

Built for the **Circle Arc Hackathon** — Track 4: Best Agentic Economy Experience (May 2026).

**Live demo:** https://signalpay-topaz.vercel.app

---

## The Problem

Every production AI agent deployment hits the same wall: the agent needs to consume external data, and external data costs money. Existing payment infrastructure was not built for agents:

- **Stripe floor is $0.30.** A whale alert signal costs $0.002. You cannot sell it profitably.
- **Subscriptions don't scale.** Agents consume 0 or 10,000 API calls depending on market activity. Monthly billing is the wrong primitive.
- **No spend controls.** Deploying an autonomous agent with an uncapped credit card is operationally untenable. One runaway loop and the billing cycle is gone.

The result: agent developers either overpay for bulk subscriptions or simulate the data. Neither ships to production.

---

## What SignalPay Builds

SignalPay is **governed agent payment infrastructure** — a marketplace where AI agents buy live crypto signals per call in USDC, with server-side spend governance enforced on every payment.

**The agent loop:**

1. Reads its own on-chain USDC balance — that is the real session budget
2. Discovers signal providers registered on-chain (SignalRegistry on Arc)
3. Evaluates each by ERC-8004 reputation score from prior sessions
4. Sends `GET /signals/price/BTC` — receives HTTP 402 with payment requirements
5. Signs EIP-3009 TransferWithAuthorization from its own wallet, retries with `X-Payment` header
6. Server verifies EIP-712 signature locally, settles via Circle Nanopayments facilitator
7. Signal data released only after settled receipt — USDC leaves the agent wallet
8. Agent analyzes convergence across price, sentiment, F&G, and composite trade signals
9. Fires BUY / ACCUMULATE / HOLD / REDUCE / SELL decision, writes to ERC-8004 on Arc
10. Records provider reputation on-chain, decrements real balance, repeats

The agent is **economically autonomous** — it has its own wallet address, its own on-chain USDC balance funded by the user via the deposit panel, and spends independently. Budget is not a session variable; it is the on-chain `balanceOf` read at session start.

**Governance enforced on every payment:**

```
┌──────────────────────────────────────────────────────────────────┐
│  X402PaymentMiddleware — 4 gates, server-side, unbypassable      │
│                                                                  │
│  Gate 1: per-call cap          default $0.010 max per payment    │
│  Gate 2: daily budget          default $1.00 rolling 24h limit   │
│  Gate 3: provider whitelist    only approved recipient addresses  │
│  Gate 4: human checkpoint      log + alert above $0.050/call     │
└──────────────────────────────────────────────────────────────────┘
```

All four gates are configurable via environment variables. The budget resets at UTC midnight. Spend is tracked in real time and visible at `/governance/policy`.

---

## Architecture

```
  User (connected wallet)
         │
         │  USDC transfer — ERC-20 transfer to agent wallet
         ▼
┌─────────────────────────────────────────────────────────────────┐
│                    React Dashboard (Vite)                        │
│                                                                  │
│  Ticker · Agent Terminal · Signal Table · Governance Bar         │
│  Agent Wallet Panel — shows live on-chain balance, fund button   │
└──────────┬──────────────────────────────────────────────────────┘
           │ SSE + REST  (Cloudflare Tunnel → Vercel CORS)
┌──────────▼──────────────────────────────────────────────────────┐
│               FastAPI Signal Provider Server                     │
│                                                                  │
│  PUBLIC                                                          │
│    /discovery/providers    provider catalog + pricing            │
│    /governance/policy      live spend policy + budget tracker    │
│    /feed                   random live signal (free preview)     │
│    /agent/wallet           agent address + on-chain USDC balance │
│                                                                  │
│  x402 GATED  (HTTP 402 → EIP-3009 sign → retry → settle)        │
│    /signals/price/{token}       $0.001  CoinGecko 30s cache      │
│    /signals/whale-alert         $0.002  Arc eth_getLogs           │
│    /signals/sentiment/{token}   $0.003  Alt.me F&G + CoinGecko   │
│    /signals/wallet-score        $0.005  Arc balanceOf + nonce     │
│    /signals/trade-signal/{t}    $0.010  Composite BUY/SELL/HOLD  │
│                                                                  │
│  X402PaymentMiddleware — 4 governance gates on every payment     │
│    Gate 1: per-call cap   Gate 2: daily budget                   │
│    Gate 3: whitelist      Gate 4: human checkpoint               │
│                                                                  │
│  /agent/run     POST → SSE stream of full agent session          │
└──────┬──────────────────────┬───────────────────────────────────┘
       │                      │
       ▼                      ▼
 External Data          LangGraph Buyer Agent (8 nodes)
   CoinGecko REST         │
   Alternative.me F&G     ├── discover          /discovery/providers
   Arc eth_getLogs        ├── select_provider   ERC-8004 rep scoring
                          ├── pay_and_fetch     x402 client
                          │     Agent Wallet ──► pays provider wallet
                          │     (real USDC, real on-chain balance)
                          ├── record_reputation ERC-8004 on-chain write
                          ├── analyze           composite signal reasoning
                          ├── execute_action    market decision → Arc tx
                          ├── increment
                          └── summarize
                                    │
                                    ▼
                        Arc Testnet (chain 5042002)
                          ├── USDC  0x3600…0000
                          ├── Circle GatewayWalletBatched (x402 settle)
                          ├── ERC-8004 ReputationRegistry
                          └── SignalRegistry (provider catalog)


  Money flow:
  User wallet ──USDC transfer──► Agent wallet ──x402 payment──► Provider wallet
                  (deposit)        (autonomous)                  (earns per call)
```

---

## Signal Providers — Live Data Only

No mock data. Every endpoint hits real APIs.

| Signal | Endpoint | Price | Data Source |
|---|---|---|---|
| **Price Oracle** | `/signals/price/{token}` | $0.001 | CoinGecko free REST (30s TTL cache) |
| **Whale Alert** | `/signals/whale-alert` | $0.002 | Arc RPC `eth_getLogs` on USDC contract |
| **Sentiment** | `/signals/sentiment/{token}` | $0.003 | Alternative.me Fear & Greed + CoinGecko community votes |
| **Wallet Score** | `/signals/wallet-score` | $0.005 | Arc RPC `balanceOf` + nonce (tx count proxy) |
| **Trade Signal** | `/signals/trade-signal/{token}` | $0.010 | Composite: price momentum + F&G + sentiment → BUY/SELL/HOLD |

The **Trade Signal** is the highest-value endpoint — a derived composite that weights price momentum (35%), Fear & Greed (35%), blended sentiment (20%), and community divergence (10%) into a single actionable decision with confidence score.

---

## Circle Products Used

| Product | Role |
|---|---|
| **x402 Protocol** | HTTP-native payment: 402 → sign EIP-3009 → retry with `X-Payment` header |
| **Nanopayments / Circle Facilitator** | Off-chain aggregation → batched Arc settlement, zero gas per call |
| **GatewayWalletBatched** | EIP-712 verifying contract (`0x0077777d7EBA4688BDeF3E311b846F25870A19B9`) |
| **USDC on Arc** | Stable unit of account for agent budget reasoning (`0x3600000000000000000000000000000000000000`) |
| **Arc Testnet** | Sub-second finality, dollar-denominated fees, ERC-8004 registries pre-deployed |

---

## Smart Contracts

| Contract | Address | Notes |
|---|---|---|
| **SignalRegistry** | `TBD` (deploy with Foundry) | Provider catalog + pricing, Solidity ^0.8.30 |
| ERC-8004 IdentityRegistry | `0x8004A818BFB912233c491871b3d84c89A494BD9e` | Pre-deployed on Arc |
| ERC-8004 ReputationRegistry | `0x8004B663056A597Dffe9eCcC1965A193B7388713` | Pre-deployed on Arc |
| ERC-8004 ValidationRegistry | `0x8004Cb1BF31DAf7788923b405b754f57acEB4272` | Pre-deployed on Arc |

---

## Quick Start

### Prerequisites

- Python 3.12+, Node 18+, Foundry
- Arc testnet USDC — fund at [faucet.circle.com](https://faucet.circle.com)
- Circle API key (optional — dev mode works without live facilitator)

### 1. Environment

```bash
cp .env.example .env
# Edit .env — minimum required:
# PROVIDER_WALLET=0x...     receives signal payments (your earning wallet)
# BUYER_PRIVATE_KEY=0x...   agent's own wallet key — fund this address with USDC
#                           address derived at startup, shown in /agent/wallet
# CIRCLE_API_KEY=...        optional — dev mode works without live facilitator

# Fund the agent wallet — get its address first:
curl http://localhost:8001/agent/wallet
# → {"address": "0x...", "balance_usdc": 0, "funded": false}
# Then send USDC to that address from the frontend deposit panel
# or directly via the Circle faucet at faucet.circle.com
```

### 2. Deploy SignalRegistry (optional for demo)

```bash
cd contracts
forge install foundry-rs/forge-std
forge test -vv

forge script script/Deploy.s.sol:DeploySignalRegistry \
  --rpc-url https://rpc.testnet.arc.network \
  --private-key $PRIVATE_KEY \
  --broadcast
```

### 3. Run the Signal Provider API

```bash
cd backend
pip install -r requirements.txt
uvicorn app.server:app --host 0.0.0.0 --port 8001 --reload
```

Verify it's working:
```bash
# Public — no payment needed
curl http://localhost:8001/discovery/providers
curl http://localhost:8001/governance/policy
curl http://localhost:8001/feed

# Gated — returns 402 with payment requirements
curl -v http://localhost:8001/signals/whale-alert
```

### 4. Run the Buyer Agent

```bash
# Via API (streams SSE to frontend)
curl -X POST http://localhost:8001/agent/run

# Directly (prints to stdout)
cd backend && python -m agents.buyer_agent
```

### 5. Run the Frontend

```bash
cd frontend
npm install
VITE_API_BASE=http://localhost:8001 npm run dev
# → http://localhost:5173
```

---

## Governance Configuration

All values are USDC raw (6 decimals). Set in `.env`:

```bash
GOVERNANCE_MAX_PER_CALL=10000       # $0.010 hard cap per individual payment
GOVERNANCE_DAILY_BUDGET=1000000     # $1.00 rolling 24h spend limit
GOVERNANCE_REQUIRE_HUMAN_ABOVE=50000  # $0.050 — log human checkpoint
GOVERNANCE_WHITELIST=0xabc...,0xdef...  # comma-separated; empty = allow all
```

Live status at `/governance/policy`:

```json
{
  "policy": {
    "max_per_call_usdc": 0.01,
    "daily_budget_usdc": 1.0,
    "require_human_above_usdc": 0.05,
    "whitelist": ["0x96eC6b983379121524e0caDa8a615488416Ee3e1"]
  },
  "today": {
    "spent_usdc": 0.013,
    "remaining_usdc": 0.987,
    "budget_usdc": 1.0,
    "pct_used": 1.3
  }
}
```

---

## Project Structure

```
signalpay/
├── contracts/
│   ├── src/SignalRegistry.sol        # Provider catalog + pricing
│   ├── test/SignalRegistry.t.sol     # Forge tests
│   └── script/Deploy.s.sol          # Arc Testnet deploy
├── backend/
│   ├── app/
│   │   ├── config.py                # Arc constants, dotenv loader
│   │   ├── server.py                # FastAPI: public + x402-gated routes
│   │   ├── x402.py                  # x402 middleware, EIP-712 verify, Circle settle
│   │   └── governance.py            # Programmable spend governance (4 gates)
│   ├── providers/
│   │   └── signals.py               # Live signal adapters (TTL-cached)
│   └── agents/
│       └── buyer_agent.py           # LangGraph 8-node buyer agent
└── frontend/
    └── src/App.tsx                  # React dashboard: feed, agent log, signals, governance
```

---

## Why This Matters

The agentic economy has a deployment blocker: no infrastructure for per-call micropayments with programmatic spend controls. Monthly subscriptions break the economic model of agents that run 0–100,000 API calls per hour based on market conditions. Credit cards cannot be delegated to an autonomous process without unlimited exposure.

SignalPay's x402 + governance stack is the first end-to-end answer:

- **Per-call economics work** because Circle's batch infrastructure makes $0.001 transactions viable
- **Agents can be deployed safely** because governance gates are enforced server-side, not client-side — an agent bug cannot exceed the daily budget
- **Markets are self-correcting** because providers accumulate ERC-8004 reputation scores — bad data results in fewer future purchases, without any platform intervention
- **No accounts, no subscriptions** — an agent needs only a funded wallet address; it can participate immediately

The same infrastructure applies to any data marketplace: scientific APIs, legal databases, model inference endpoints, real-time sensor data. The unit of payment is just a signed USDC authorization.

---

## Circle Product Feedback

### Why We Chose These Products

SignalPay has a fundamental economic constraint: no existing payment infrastructure works at the price points AI agents actually need. Stripe's floor is $0.30 — that's 300x the price of a price oracle signal. We chose Circle's stack because it solves the three problems that make agent-to-agent commerce otherwise impossible:

**Nanopayments + x402** maps perfectly onto how agents interact with APIs. Payment becomes a one-header operation: receive 402, sign EIP-3009, retry with `X-Payment`. No accounts, no subscriptions — the agent does it autonomously. We ran 30+ signal purchases in a single $0.10 budget session, spending $0.013 across 5 signal types.

**USDC** gives agents a stable unit of account for budget reasoning. Volatile gas tokens break the math. USDC at 6-decimal precision lets the agent reason deterministically: "I have $0.10, each signal costs $0.002, I can buy 50 signals."

**Circle Gateway (GatewayWalletBatched)** makes nanopayments economically viable. Without batching, a $0.002 payment with $0.001 gas overhead is a 50% fee. Gateway's off-chain aggregation + batched Arc settlement means infrastructure cost is effectively zero per call.

**Arc Testnet** (chain 5042002) provided ~0.5s finality, dollar-denominated fees, and pre-deployed ERC-8004 registries — the agent identity layer we needed without building it ourselves.

### What Worked Well

- **x402 protocol clarity**: HTTP-native design (402 → sign → retry) maps cleanly onto API patterns. Seller middleware in ~400 lines of Python; buyer-side signing in ~60 lines.
- **EIP-3009 replay protection built in**: The `nonce` field means each authorization settles once — a security property from the signature scheme, not a bolt-on.
- **Structured error reasons from the facilitator**: `insufficient_balance`, `invalid_signature`, `self_transfer` are concrete strings — we used them to distinguish "sig valid, wallet unfunded" (issue receipt) from "sig invalid" (reject), which let us run end-to-end demos with EOA wallets against a DCW-oriented facilitator.
- **LangGraph + SSE**: Streaming the agent's decision loop in real time makes autonomous commerce tangible — judges watch the agent discover, pay, analyze, and decide in a single unbroken flow.
- **Arc testnet stability**: Stable throughout two weeks of development, faucet worked reliably.

### What Could Be Improved

- **x402 settle body is non-obvious**: `paymentPayload.accepted` mirrors `paymentRequirements` (redundant), `resource` is required but easy to miss, and authorization numeric fields must be strings despite being integers in EIP-3009. Each took a debug cycle to discover.
- **No Python x402 client library**: The `@circle-fin/x402-batching` package handles signing and retry in Node/TypeScript. The agentic economy is primarily Python (LangChain, LangGraph, CrewAI, AutoGen). We implemented EIP-712 signing from scratch — a `circle-x402-python` package would dramatically accelerate adoption.
- **Fragmented developer onboarding**: Protocol spec, facilitator docs, EIP-3009 standard, and Arc config live in different places. A single end-to-end Python + TypeScript quickstart covering seller middleware + buyer client + facilitator would cut setup time by hours.
- **No `/verify` endpoint on testnet**: Spec documents `/v1/x402/verify` for dry-run validation. The endpoint was unreachable during development — we had to infer validity from settlement error codes.

### Recommendations

1. **Publish a Python x402 client library** — `pip install circle-x402` with a drop-in `httpx`/`requests` wrapper handling 402 → sign → retry. This unlocks the entire Python AI agent ecosystem immediately.
2. **Add `/v1/x402/verify` on testnet** — validate a signed payload without spending funds. Essential for agent developers who need to test signing without funded wallets.
3. **Structured field-level validation errors** — return `{ "validationErrors": [{ "field": "authorization.validBefore", "code": "expired" }] }` instead of message strings so tooling can parse failures without string matching.
4. **Streaming payment primitive** — x402 is request/response (one payment per call). Agentic inference use cases need per-token or per-inference-step streaming. A payment channel or continuous authorization layer on top of the batch infrastructure unlocks a new category of applications.
5. **ERC-8004 documentation** — the identity and reputation registries are exactly what multi-agent systems need, but documentation is sparse. A guide showing register → write → query from another contract (with working Solidity + Python examples) would make this infrastructure accessible.

---

## License

MIT
