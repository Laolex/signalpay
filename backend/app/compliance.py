"""
SignalPay Compliance Engine — programmable financial policy layer.

Runs before every x402 settlement and agent session start.
Checks are layered: sanctions → jurisdiction → on-chain risk signals → composite tier.

Extension points (stub → real):
  SANCTIONS   — local blocklist now; TRM Labs / Chainalysis API later
  JURISDICTION — unknown/inferred now; geo-IP clustering or on-chain graph later
  VELOCITY    — single-call check now; sliding-window rate monitor later
  KYB/KYC     — risk tier output now; KYB provider webhook later

Risk tiers:
  low      0.00–0.30  — allow, no action
  medium   0.30–0.60  — allow, log for audit trail
  high     0.60–0.85  — allow, emit human checkpoint alert
  blocked  0.85–1.00  — deny, return None from validate_payment
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Optional


# ── Sanctions Blocklist ────────────────────────────────────────────
# Illustrative subset matching OFAC SDN and Treasury-designated mixer
# contracts. Real deployment should pull from TRM Labs or Chainalysis
# sanctions screening API on every settlement request.
_SANCTIONS_BLOCKLIST: set[str] = {s.lower() for s in {
    "0x7f268357a8c2552623316e2562d90e642bb538e5",  # Hydra darknet
    "0xd882cfc20f52f2599d84b8e8d58c7fb62cfe344b",  # Tornado Cash (proxy)
    "0x722122df12d4e14e13ac3b6895a86e84145b6967",  # Tornado Cash Router
    "0x8589427373D6D84E98730D7795D8f6f8731FDA16",  # Blender.io mixer
    "0x1da5821544e25c636c1417ba96ade4cf6d2f9b5a",  # Sanctioned entity
}}

# Jurisdictions blocked by default (ISO 3166-1 alpha-2).
# Override via COMPLIANCE_BLOCKED_JURISDICTIONS env var (comma-separated).
_DEFAULT_BLOCKED = "KP,IR,SY,CU"
_BLOCKED_JURISDICTIONS: set[str] = set(
    os.getenv("COMPLIANCE_BLOCKED_JURISDICTIONS", _DEFAULT_BLOCKED).split(",")
)

# Risk score thresholds
_TIER_THRESHOLDS = [
    ("blocked", 0.85),
    ("high",    0.60),
    ("medium",  0.30),
    ("low",     0.00),
]

# 5-minute compliance result cache per address.
# Real deployment: Redis with TTL, invalidated on sanctions list update.
_cache: dict[str, tuple["ComplianceResult", float]] = {}
_CACHE_TTL = 300


# ── Result Dataclass ───────────────────────────────────────────────

@dataclass
class ComplianceResult:
    address: str
    allowed: bool
    risk_tier: str             # "low" | "medium" | "high" | "blocked"
    risk_score: float          # 0.0–1.0 composite
    sanctions_hit: bool
    jurisdiction: str          # ISO code or "UNKNOWN"
    jurisdiction_allowed: bool
    flags: list[str]
    checked_at: int = field(default_factory=lambda: int(time.time()))

    def to_dict(self) -> dict:
        return {
            "address": self.address,
            "allowed": self.allowed,
            "risk_tier": self.risk_tier,
            "risk_score": self.risk_score,
            "sanctions_hit": self.sanctions_hit,
            "jurisdiction": self.jurisdiction,
            "jurisdiction_allowed": self.jurisdiction_allowed,
            "flags": self.flags,
            "checked_at": self.checked_at,
        }


# ── On-chain Signal Fetcher ────────────────────────────────────────

def _get_onchain_signals(address: str) -> tuple[int, float]:
    """
    Returns (tx_count, balance_usdc) from Arc RPC.
    tx_count proxied via eth_getTransactionCount (nonce).
    Returns (0, 0.0) on any RPC failure — fail-open for liveness.
    """
    try:
        from web3 import Web3
        from app.config import ARC, TOKENS
        w3 = Web3(Web3.HTTPProvider(ARC.rpc, request_kwargs={"timeout": 5}))
        addr = Web3.to_checksum_address(address)
        tx_count = w3.eth.get_transaction_count(addr)
        usdc = w3.eth.contract(
            address=Web3.to_checksum_address(TOKENS.USDC),
            abi=[{"inputs": [{"name": "account", "type": "address"}],
                  "name": "balanceOf",
                  "outputs": [{"name": "", "type": "uint256"}],
                  "stateMutability": "view", "type": "function"}],
        )
        balance_raw = usdc.functions.balanceOf(addr).call()
        return tx_count, round(balance_raw / 1_000_000, 6)
    except Exception:
        return 0, 0.0


# ── Jurisdiction Inference ─────────────────────────────────────────

def _infer_jurisdiction(address: str, tx_count: int) -> str:
    """
    Jurisdiction inference stub.

    Real implementation options:
      - On-chain graph clustering: associate address with known exchange
        deposit wallets whose domicile is public (Coinbase → US, Binance → various)
      - Geo-IP on the HTTP request origin (not available to settlement layer)
      - TRM Labs jurisdiction risk API

    Current logic: return UNKNOWN (allowed by default).
    Blocked jurisdictions require explicit configuration + a real signal source.
    """
    # GAP 6 extension point — crosschain jurisdiction awareness plugs in here.
    # When chain_id != 5042002 (Arc), check bridge origin chain + address cluster.
    return "UNKNOWN"


# ── Velocity Monitor ───────────────────────────────────────────────
# GAP future: sliding-window counter per address, reset every 60s.
# Triggers "high" risk if >50 payments/minute from one address.
_velocity: dict[str, list[float]] = {}

def _check_velocity(address: str) -> tuple[float, list[str]]:
    """
    Single-window velocity check. Flags addresses with >20 calls/60s.
    Extension: replace with Redis sorted-set sliding window.
    """
    now = time.time()
    window = 60.0
    calls = _velocity.get(address, [])
    calls = [t for t in calls if now - t < window]
    calls.append(now)
    _velocity[address] = calls
    count = len(calls)
    if count > 50:
        return 0.40, [f"VELOCITY_CRITICAL:{count}/min"]
    if count > 20:
        return 0.20, [f"VELOCITY_HIGH:{count}/min"]
    return 0.0, []


# ── Core Compliance Check ──────────────────────────────────────────

def check_wallet(address: str, bypass_cache: bool = False) -> ComplianceResult:
    """
    Run full compliance stack against a wallet address.
    Results are cached for CACHE_TTL seconds.

    Called from:
      - x402.validate_payment() — between sig verify and facilitator settle
      - /agent/run — before starting a session
      - /compliance/check/{address} — frontend badge endpoint
    """
    addr = address.lower()

    if not bypass_cache and addr in _cache:
        result, ts = _cache[addr]
        if time.time() - ts < _CACHE_TTL:
            return result

    flags: list[str] = []
    risk_score: float = 0.0

    # ── 1. Sanctions screening ─────────────────────────────────────
    sanctions_hit = addr in _SANCTIONS_BLOCKLIST
    if sanctions_hit:
        flags.append("OFAC_SANCTIONS_HIT")
        risk_score = 1.0  # hard block — skip remaining checks

    if not sanctions_hit:
        # ── 2. On-chain signals ────────────────────────────────────
        tx_count, balance_usdc = _get_onchain_signals(address)

        if tx_count == 0:
            flags.append("NO_ONCHAIN_HISTORY")
            risk_score += 0.15
        elif tx_count < 3:
            flags.append("THIN_HISTORY")
            risk_score += 0.05

        if balance_usdc > 500_000:
            flags.append("WHALE_THRESHOLD")
            risk_score += 0.10
        elif balance_usdc > 100_000:
            flags.append("HIGH_VALUE_WALLET")
            risk_score += 0.05

        # ── 3. Jurisdiction ────────────────────────────────────────
        jurisdiction = _infer_jurisdiction(address, tx_count)
        jurisdiction_allowed = jurisdiction not in _BLOCKED_JURISDICTIONS
        if not jurisdiction_allowed:
            flags.append(f"BLOCKED_JURISDICTION:{jurisdiction}")
            risk_score += 0.50

        # ── 4. Velocity ────────────────────────────────────────────
        vel_score, vel_flags = _check_velocity(addr)
        risk_score += vel_score
        flags.extend(vel_flags)

    else:
        jurisdiction = "UNKNOWN"
        jurisdiction_allowed = False

    risk_score = min(1.0, round(risk_score, 3))

    # ── Tier assignment ────────────────────────────────────────────
    tier = "low"
    for t, threshold in _TIER_THRESHOLDS:
        if risk_score >= threshold:
            tier = t
            break

    allowed = tier != "blocked"

    result = ComplianceResult(
        address=address,
        allowed=allowed,
        risk_tier=tier,
        risk_score=risk_score,
        sanctions_hit=sanctions_hit,
        jurisdiction=jurisdiction,
        jurisdiction_allowed=jurisdiction_allowed,
        flags=flags,
    )

    _cache[addr] = (result, time.time())
    print(f"[compliance] {address[:10]}… tier={tier} score={risk_score} flags={flags}")
    return result


def clear_cache(address: Optional[str] = None):
    """Invalidate cache — call when sanctions list is updated."""
    if address:
        _cache.pop(address.lower(), None)
    else:
        _cache.clear()
