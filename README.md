# SignalPay — AI Agent Alpha Marketplace

> AI agents buy and sell crypto alpha signals via nanopayments on Arc. Sub-cent payments, zero gas, real-time settlement.

Built for the **Nano Payments on Arc** hackathon (May 11–19, 2026).

## What It Does

SignalPay is a marketplace where autonomous AI agents pay for data feeds — whale alerts, price oracles, wallet scores, sentiment analysis — using Circle Nanopayments on Arc. Every API call costs a fraction of a cent in USDC, with zero gas per transaction.

**The core loop:**
1. Buyer agent discovers signal providers on-chain (SignalRegistry on Arc)
2. Evaluates providers by ERC-8004 reputation scores
3. Sends HTTP request to provider's x402 endpoint
4. Receives HTTP 402 → signs EIP-3009 payment authorization
5. Pays via Circle Nanopayments ($0.001–$0.01 per call, zero gas)
6. Receives signal data instantly
7. Records provider reputation on-chain (ERC-8004)
8. Repeats — spending $0.10 total across dozens of signal purchases

## Architecture

```
LangGraph Buyer Agent
    │
    ├── Discover providers (SignalRegistry on Arc)
    ├── Check reputation (ERC-8004 ReputationRegistry)
    ├── Pay via x402 nanopayment (EIP-3009 → Circle API)
    ├── Receive signal data
    ├── Analyze & decide
    └── Record reputation feedback (ERC-8004)
         │
         ▼
SignalPay API Server (FastAPI)
    │
    ├── x402 Payment Middleware
    │   └── HTTP 402 → payment required → validate → release data
    │
    ├── Signal Providers
    │   ├── Whale Alert (Solana alpha engine)
    │   ├── Price Oracle (aggregated feeds)
    │   ├── Wallet Scorer (alpha/risk profiling)
    │   └── Sentiment Engine (social signals)
    │
    └── Circle Nanopayments API
        └── Off-chain aggregation → batched Arc settlement
```

## Circle Products Used

| Product | How We Use It |
|---|---|
| **Nanopayments** | Zero-gas sub-cent payments for every API call |
| **x402 Protocol** | HTTP-native payment flow (402 → sign → pay → access) |
| **Gateway Wallets** | Agent deposits USDC once, pays thousands of times |
| **Dev-Controlled Wallets** | Manage agent wallet keys via API |
| **ERC-8004** | On-chain agent identity + reputation scoring |
| **Arc Settlement** | Batched nanopayment settlement on Arc L1 |

## Smart Contracts

| Contract | Address | Status |
|---|---|---|
| **SignalRegistry** | `TBD` (deploy with Foundry) | Custom — provider catalog + pricing |
| ERC-8004 IdentityRegistry | `0x8004A818BFB912233c491871b3d84c89A494BD9e` | Already deployed |
| ERC-8004 ReputationRegistry | `0x8004B663056A597Dffe9eCcC1965A193B7388713` | Already deployed |
| ERC-8004 ValidationRegistry | `0x8004Cb1BF31DAf7788923b405b754f57acEB4272` | Already deployed |

## Quick Start

### 1. Deploy SignalRegistry

```bash
cd contracts
forge install foundry-rs/forge-std
forge test -vv

# Deploy to Arc Testnet
cp ../.env.example ../.env && source ../.env
forge script script/Deploy.s.sol:DeploySignalRegistry \
  --rpc-url $ARC_TESTNET_RPC_URL \
  --private-key $PRIVATE_KEY \
  --broadcast
```

### 2. Run the Signal Provider API

```bash
cd backend
pip install -r requirements.txt
uvicorn app.server:app --host 0.0.0.0 --port 8000 --reload
```

Test discovery (no payment required):
```bash
curl http://localhost:8000/discovery/providers
```

Test a gated endpoint (returns 402):
```bash
curl -v http://localhost:8000/signals/whale-alert
# → HTTP 402 with x402 payment requirements
```

### 3. Run the Buyer Agent

```bash
cd backend
python -m agents.buyer_agent
```

### 4. Run the Frontend

```bash
cd frontend
npm install
npm run dev
# → http://localhost:5173
```

## Project Structure

```
signalpay/
├── contracts/
│   ├── src/SignalRegistry.sol        # Provider catalog + pricing
│   ├── test/SignalRegistry.t.sol     # 12 Forge tests
│   ├── script/Deploy.s.sol           # Arc Testnet deploy
│   └── foundry.toml
├── backend/
│   ├── app/
│   │   ├── config.py                 # Arc constants, contract addresses
│   │   ├── server.py                 # FastAPI with x402-gated endpoints
│   │   └── x402.py                   # x402 payment middleware
│   ├── providers/
│   │   └── signals.py                # Signal adapters (whale, price, score, sentiment)
│   ├── agents/
│   │   └── buyer_agent.py            # LangGraph buyer agent
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── App.tsx                   # React dashboard (4 tabs)
│   │   └── main.tsx
│   ├── index.html
│   ├── package.json
│   ├── vite.config.ts
│   └── tsconfig.json
├── .env.example
└── README.md
```

## Signal Pricing

| Signal | Price per Call | Category |
|---|---|---|
| Whale Alert | $0.002 | Real-time large wallet movements |
| Price Oracle | $0.001 | Token price feeds with OHLCV |
| Wallet Score | $0.005 | Alpha/risk profiling for any wallet |
| Sentiment | $0.003 | Social/news sentiment scoring |

## Why This Matters

Traditional API monetization uses monthly subscriptions or per-request billing with credit cards — minimum viable transaction is ~$0.30 (Stripe's floor). With Nanopayments on Arc, the floor drops to $0.000001. This unlocks:

- **Per-call pricing** for AI agents consuming thousands of API calls/minute
- **Zero gas overhead** — Circle batches settlement, agents pay nothing per tx
- **Reputation-driven markets** — agents score providers on-chain, bad data = low scores = fewer customers
- **Autonomous commerce** — no accounts, no credit cards, just signed USDC authorizations

## License

MIT
