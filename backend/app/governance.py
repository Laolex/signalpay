"""
Programmable spend governance for x402 payments.

Enforced server-side in X402PaymentMiddleware — every payment clears four gates:
  1. per-call cap       — hard max per individual payment
  2. daily budget       — rolling 24h spend limit across all providers
  3. provider whitelist — only approved recipient addresses may receive
  4. human gate         — payments above threshold emit an approval checkpoint log

Config via .env (all amounts in USDC 6-decimal raw units):
  GOVERNANCE_MAX_PER_CALL       default 10_000  ($0.010)
  GOVERNANCE_DAILY_BUDGET       default 1_000_000 ($1.00)
  GOVERNANCE_REQUIRE_HUMAN_ABOVE default 50_000 ($0.050)
  GOVERNANCE_WHITELIST          comma-separated checksummed addresses (empty = allow all)
"""

from __future__ import annotations

import os
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class GovernancePolicy:
    max_per_call: int = 10_000          # USDC raw — hard cap per payment
    daily_budget: int = 1_000_000       # USDC raw — rolling 24h limit
    require_human_above: int = 50_000   # USDC raw — log approval checkpoint
    whitelist: list[str] = field(default_factory=list)  # empty = allow all

    @classmethod
    def from_env(cls) -> "GovernancePolicy":
        whitelist_raw = os.getenv("GOVERNANCE_WHITELIST", "")
        whitelist = [a.strip().lower() for a in whitelist_raw.split(",") if a.strip()]
        return cls(
            max_per_call=int(os.getenv("GOVERNANCE_MAX_PER_CALL", "10000")),
            daily_budget=int(os.getenv("GOVERNANCE_DAILY_BUDGET", "1000000")),
            require_human_above=int(os.getenv("GOVERNANCE_REQUIRE_HUMAN_ABOVE", "50000")),
            whitelist=whitelist,
        )

    def as_display(self) -> dict:
        return {
            "max_per_call_usdc": self.max_per_call / 1_000_000,
            "daily_budget_usdc": self.daily_budget / 1_000_000,
            "require_human_above_usdc": self.require_human_above / 1_000_000,
            "whitelist": self.whitelist or ["*"],
        }


@dataclass
class GovernanceResult:
    allowed: bool
    gate: Optional[str] = None      # which gate blocked it
    reason: Optional[str] = None
    human_checkpoint: bool = False  # True when payment cleared but exceeds human gate


# ── In-memory daily spend tracker ─────────────────────────────────
# Keyed by ISO date string → total raw USDC spent that day.
_daily_spend: dict[str, int] = defaultdict(int)


def _today() -> str:
    return time.strftime("%Y-%m-%d", time.gmtime())


def record_spend(amount: int) -> None:
    _daily_spend[_today()] += amount


def daily_spent() -> int:
    return _daily_spend[_today()]


def daily_remaining(policy: GovernancePolicy) -> int:
    return max(0, policy.daily_budget - daily_spent())


# ── Gate enforcement ───────────────────────────────────────────────

def check(amount: int, recipient: str, policy: GovernancePolicy) -> GovernanceResult:
    """
    Run all four governance gates. Returns GovernanceResult.
    Call `record_spend(amount)` after a successful payment settles.
    """
    # Gate 1 — per-call cap
    if amount > policy.max_per_call:
        return GovernanceResult(
            allowed=False,
            gate="per_call_cap",
            reason=f"${amount/1e6:.4f} exceeds per-call limit of ${policy.max_per_call/1e6:.4f}",
        )

    # Gate 2 — daily budget
    if daily_spent() + amount > policy.daily_budget:
        return GovernanceResult(
            allowed=False,
            gate="daily_budget",
            reason=(
                f"Daily budget exhausted — spent ${daily_spent()/1e6:.4f} of "
                f"${policy.daily_budget/1e6:.4f} today"
            ),
        )

    # Gate 3 — whitelist
    if policy.whitelist and recipient.lower() not in policy.whitelist:
        return GovernanceResult(
            allowed=False,
            gate="whitelist",
            reason=f"Recipient {recipient[:10]}… not in provider whitelist",
        )

    # Gate 4 — human checkpoint (non-blocking — logs intent)
    human_checkpoint = amount >= policy.require_human_above

    return GovernanceResult(
        allowed=True,
        human_checkpoint=human_checkpoint,
    )
