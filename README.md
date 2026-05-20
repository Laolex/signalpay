# SignalPay — Governed Agent Payment Infrastructure

> An API marketplace where AI agents pay per call in USDC, governed by programmable spend policy, settled on Arc in under a second.

**Live:** https://signalpay-topaz.vercel.app

---

## The Problem

Every production AI agent deployment hits the same wall: the agent needs to consume external data, and external data costs money. Existing payment infrastructure was not built for agents:

- **Stripe floor is $0.30.** A whale alert signal costs $0.002. You cannot sell it profitably.
- **Subscriptions don't scale.** Agents consume 0 or 10,000 API calls depending on market conditions. Monthly billing is the wrong primitive.
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

The agent is **economically autonomous** — each user gets a unique derived wallet address funded by their own USDC deposit. Budget is not a session variable; it is the on-chain `balanceOf` read at session start.

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
  User (connected wallet: 0xABC...)
         │
         │  HMAC-SHA256(userAddress, masterSeed)
         │  → unique derived agent wallet: 0xDEF...
         │
         │  USDC transfer → deposits to derived agent wallet
         ▼
┌─────────────────────────────────────────────────────────────────┐
│                    React Dashboard (Vite)                        │
│                                                                  │
│  Ticker · Agent Terminal · Signal Table · Governance Bar         │
│  Agent Wallet Panel — per-user address, live on-chain balance    │
└──────────┬──────────────────────────────────────────────────────┘
           │ SSE + REST  (Cloudflare Tunnel → Vercel CORS)
┌──────────▼──────────────────────────────────────────────────────┐
│               FastAPI Signal Provider Server                     │
│                                                                  │
│  PUBLIC                                                          │
│    /discovery/providers    provider catalog + pricing            │
│    /governance/policy      live spend policy + budget tracker    │
│    /feed                   random live signal (free preview)     │
│    /agent/wallet?user=0x…  derived address + on-chain balance    │
│                                                                  │
│  x402 GATED  (HTTP 402 → EIP-3009 sign → retry → settle)        │
│    /signals/price/{token}       $0.001  Pyth Hermes (conf 0.99)  │
│    /signals/whale-alert         $0.002  Arc eth_getLogs           │
│    /signals/sentiment/{token}   $0.003  Alt.me F&G + community   │
│    /signals/wallet-score        $0.005  Arc balanceOf + nonce     │
│    /signals/trade-signal/{t}    $0.010  Composite BUY/SELL/HOLD  │
│    /signals/yield-intel         $0.003  DefiLlama stablecoin APY │
│                                                                  │
│  X402PaymentMiddleware — 4 governance gates on every payment     │
│    Gate 1: per-call cap   Gate 2: daily budget                   │
│    Gate 3: whitelist      Gate 4: human checkpoint               │
│                                                                  │
│  /agent/run  POST { wallet_address } → SSE agent session stream  │
└──────┬──────────────────────┬───────────────────────────────────┘
       │                      │
       ▼                      ▼
 External Data          LangGraph Buyer Agent (8 nodes)
   Pyth Hermes REST       │
   DefiLlama yields       ├── discover          /discovery/providers
   Alternative.me F&G     ├── select_provider   ERC-8004 rep scoring
   Arc eth_getLogs        ├── pay_and_fetch     x402 client
                          │     Derived wallet ──► signs EIP-3009
                          │     (unique per user, real on-chain balance)
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


  Money flow (per user):
  User wallet (0xABC)
    │ HMAC-SHA256 derivation
    ▼
  Agent wallet (0xDEF) ── USDC deposit ──► on-chain balance
    │ x402 per signal call (EIP-3009 signed from 0xDEF)
    ▼
  Provider wallet ── earns per call
```

---

## Signal Providers — Live Data

No mock data. Every endpoint hits real APIs.

| Signal | Endpoint | Price | Data Source |
|---|---|---|---|
| **Price Oracle** | `/signals/price/{token}` | $0.001 | Pyth Hermes REST — BTC/ETH/SOL/USDC, conf=0.99, 15s TTL. Falls back to CoinGecko. |
| **Whale Alert** | `/signals/whale-alert` | $0.002 | Arc RPC `eth_getLogs` on USDC contract |
| **Sentiment** | `/signals/sentiment/{token}` | $0.003 | Alternative.me Fear & Greed + community votes |
| **Wallet Score** | `/signals/wallet-score` | $0.005 | Arc RPC `balanceOf` + nonce (tx count proxy) |
| **Trade Signal** | `/signals/trade-signal/{token}` | $0.010 | Composite: price momentum + F&G + sentiment → BUY/SELL/HOLD |
| **Yield Intel** | `/signals/yield-intel` | $0.003 | DefiLlama — USDC stablecoin pools, APY 0.1–50%, TVL >$5M, top 5 by yield |

The **Trade Signal** is the highest-value endpoint — a derived composite weighting price momentum (35%), Fear & Greed (35%), blended sentiment (20%), and community divergence (10%) into a single actionable decision with confidence score.

---

## Per-User Wallet Architecture

Each connected wallet address gets a unique, deterministic agent wallet:

```python
# Backend key derivation (never exposed to client)
import hmac, hashlib
raw = hmac.new(AGENT_MASTER_SEED.encode(), user_address.lower().encode(), hashlib.sha256).digest()
agent_account = Account.from_key(raw)
```

- Same user address always derives the same agent wallet
- Different users get completely separate wallets — no shared pool
- The derived private key lives server-side only, used exclusively for EIP-3009 signing
- User deposits USDC to their agent wallet via the frontend deposit panel
- `POST /agent/run { wallet_address }` → backend derives the key, injects into LangGraph state

---

## Open Marketplace

Signal endpoints are open to any agent — not just the built-in LangGraph buyer. Any agent with Arc testnet USDC and a private key can participate:

```bash
# 1. Discover providers
curl https://<backend>/discovery/providers

# 2. Call a signal — receive 402
curl https://<backend>/signals/price/BTC
# → HTTP 402 + X-Payment-Info header with EIP-712 domain + amount

# 3. Sign EIP-3009 TransferWithAuthorization with your wallet key
# 4. Retry with X-Payment header → signal delivered
```

Any language, any framework. The payment is a single signed USDC authorization.

---

## Infrastructure

| Component | Stack |
|---|---|
| **x402 Protocol** | HTTP-native payment: 402 → sign EIP-3009 → retry with `X-Payment` header |
| **Circle Nanopayments / Facilitator** | Off-chain aggregation → batched Arc settlement |
| **GatewayWalletBatched** | EIP-712 verifying contract (`0x0077777d7EBA4688BDeF3E311b846F25870A19B9`) |
| **USDC on Arc** | `0x3600000000000000000000000000000000000000` |
| **Arc Testnet** | Chain ID 5042002, sub-second finality, ERC-8004 registries pre-deployed |
| **ERC-8004** | Identity / Reputation / Validation registries — provider scoring per session |

---

## Smart Contracts

| Contract | Address |
|---|---|
| **SignalRegistry** | `TBD` — deploy with Foundry |
| ERC-8004 IdentityRegistry | `0x8004A818BFB912233c491871b3d84c89A494BD9e` |
| ERC-8004 ReputationRegistry | `0x8004B663056A597Dffe9eCcC1965A193B7388713` |
| ERC-8004 ValidationRegistry | `0x8004Cb1BF31DAf7788923b405b754f57acEB4272` |

---

## Quick Start

### Prerequisites

- Python 3.12+, Node 18+, Foundry
- Arc testnet USDC — fund at [faucet.circle.com](https://faucet.circle.com)
- Circle API key (optional — dev mode works without live facilitator)

### 1. Environment

```bash
cp .env.example .env
# Minimum required:
# PROVIDER_WALLET=0x...       receives signal payments (your earning wallet)
# AGENT_MASTER_SEED=<hex32>   derive per-user agent wallets
#                             generate: python3 -c "import secrets; print(secrets.token_hex(32))"
# CIRCLE_API_KEY=...          optional — dev mode works without live facilitator

# Check a user's derived agent wallet:
curl "http://localhost:8001/agent/wallet?user=0xYOUR_WALLET_ADDRESS"
# → {"address": "0x...", "balance_usdc": 0, "funded": false}
# Then fund that address via the frontend deposit panel
```

### 2. Deploy SignalRegistry (optional)

```bash
cd contracts
forge install foundry-rs/forge-std
forge test -vv

forge script script/Deploy.s.sol:DeploySignalRegistry \
  --rpc-url https://rpc.testnet.arc.network \
  --private-key $PRIVATE_KEY \
  --broadcast
```

### 3. Run the Backend

```bash
cd backend
pip install -r requirements.txt
uvicorn app.server:app --host 0.0.0.0 --port 8001 --reload
```

```bash
# Public — no payment needed
curl http://localhost:8001/discovery/providers
curl http://localhost:8001/governance/policy
curl http://localhost:8001/feed

# Gated — returns 402 with payment requirements
curl -v http://localhost:8001/signals/whale-alert
```

### 4. Run the Frontend

```bash
cd frontend
npm install
VITE_API_BASE=http://localhost:8001 npm run dev
# → http://localhost:5173
```

### 5. Run the Buyer Agent

```bash
# Via API (streams SSE to frontend)
curl -X POST http://localhost:8001/agent/run \
  -H "Content-Type: application/json" \
  -d '{"wallet_address": "0xYOUR_WALLET_ADDRESS"}'

# Directly
cd backend && python -m agents.buyer_agent
```

---

## Governance Configuration

All values are USDC raw (6 decimals). Set in `.env`:

```bash
GOVERNANCE_MAX_PER_CALL=10000         # $0.010 hard cap per payment
GOVERNANCE_DAILY_BUDGET=1000000       # $1.00 rolling 24h limit
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
│   │   ├── config.py                # Arc constants, AGENT_MASTER_SEED, dotenv loader
│   │   ├── server.py                # FastAPI: public + x402-gated routes, wallet derivation
│   │   ├── x402.py                  # x402 middleware, EIP-712 verify, Circle settle
│   │   └── governance.py            # Programmable spend governance (4 gates)
│   ├── providers/
│   │   └── signals.py               # Live signal adapters (Pyth, DefiLlama, Arc RPC)
│   └── agents/
│       └── buyer_agent.py           # LangGraph 8-node buyer agent
└── frontend/
    └── src/
        ├── App.tsx                  # React dashboard: terminal, signals, governance, wallet
        └── SignalPayDiagram.tsx     # Interactive architecture diagram
```

---

## Why This Works

The agentic economy has a deployment blocker: no infrastructure for per-call micropayments with programmatic spend controls. Monthly subscriptions break the economic model of agents that run 0–100,000 API calls per hour based on market conditions.

SignalPay's x402 + governance stack is the answer:

- **Per-call economics work** because Circle's batch infrastructure makes $0.001 transactions viable
- **Agents deploy safely** because governance gates are server-side — an agent bug cannot exceed the daily budget
- **Markets self-correct** because providers accumulate ERC-8004 reputation scores — bad data means fewer future purchases, without platform intervention
- **No accounts, no subscriptions** — an agent needs only a funded wallet address

The same infrastructure applies to any data marketplace: scientific APIs, legal databases, model inference endpoints, real-time sensor data. The unit of payment is a signed USDC authorization.

---

## License

MIT
