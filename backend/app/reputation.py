"""
ERC-8004 Reputation client.

Wraps the ReputationRegistry deployed at `ERC_8004.reputation_registry` on Arc
Testnet. Submits feedback via `giveFeedback(...)` — the real spec function.
Previously the buyer agent only appended to an in-memory list.

Config:
  - BUYER_PRIVATE_KEY   — separate key for the agent (falls back to PRIVATE_KEY)
  - ARC_TESTNET_RPC_URL — RPC endpoint (falls back to ARC.rpc)

If no key is set, `give_feedback` is a no-op that logs intent. That makes the
module safe to import in environments without secrets (CI, local dev without
a funded wallet) without silently claiming success.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Optional

from app.config import ARC, ERC_8004


# ── Function fragment — ERC-8004 ReputationRegistry.giveFeedback ──
# Source: https://github.com/erc-8004/erc-8004-contracts (abis/ReputationRegistry.json)
GIVE_FEEDBACK_ABI = [{
    "inputs": [
        {"internalType": "uint256", "name": "agentId", "type": "uint256"},
        {"internalType": "int128",  "name": "value", "type": "int128"},
        {"internalType": "uint8",   "name": "valueDecimals", "type": "uint8"},
        {"internalType": "string",  "name": "tag1", "type": "string"},
        {"internalType": "string",  "name": "tag2", "type": "string"},
        {"internalType": "string",  "name": "endpoint", "type": "string"},
        {"internalType": "string",  "name": "feedbackURI", "type": "string"},
        {"internalType": "bytes32", "name": "feedbackHash", "type": "bytes32"},
    ],
    "name": "giveFeedback",
    "outputs": [],
    "stateMutability": "nonpayable",
    "type": "function",
}]


@dataclass
class FeedbackResult:
    submitted: bool
    tx_hash: Optional[str]
    reason: Optional[str] = None


def _rpc_url() -> str:
    return os.getenv("ARC_TESTNET_RPC_URL", ARC.rpc)


def _buyer_key() -> str:
    return os.getenv("BUYER_PRIVATE_KEY") or os.getenv("PRIVATE_KEY") or ""


def give_feedback(
    agent_id: int,
    score_0_100: int,
    tag1: str = "",
    tag2: str = "",
    endpoint: str = "",
    feedback_uri: str = "",
    feedback_hash: bytes = b"\x00" * 32,
) -> FeedbackResult:
    """
    Submit on-chain feedback to the ERC-8004 ReputationRegistry.

    The registry expects a signed int128 score with a decimal exponent. We
    encode `score_0_100` as value=score_0_100, decimals=2 — i.e. a percentage.
    Out-of-range values clamp to [-100, 100] to stay within a reasonable band.
    """
    key = _buyer_key()
    if not key:
        return FeedbackResult(False, None, "no buyer key configured")

    # Clamp and encode
    clamped = max(-100, min(100, int(score_0_100)))

    try:
        from web3 import Web3
        from eth_account import Account
    except ImportError as e:
        return FeedbackResult(False, None, f"web3 import error: {e}")

    try:
        w3 = Web3(Web3.HTTPProvider(_rpc_url(), request_kwargs={"timeout": 15}))
        if not w3.is_connected():
            return FeedbackResult(False, None, "RPC unreachable")
    except Exception as e:
        return FeedbackResult(False, None, f"RPC error: {e}")

    try:
        acct = Account.from_key(key)
        contract = w3.eth.contract(
            address=Web3.to_checksum_address(ERC_8004.reputation_registry),
            abi=GIVE_FEEDBACK_ABI,
        )

        tx = contract.functions.giveFeedback(
            int(agent_id),
            int(clamped),
            2,  # valueDecimals — score is a percentage
            tag1,
            tag2,
            endpoint,
            feedback_uri,
            feedback_hash if isinstance(feedback_hash, bytes) else bytes.fromhex(
                feedback_hash[2:] if feedback_hash.startswith("0x") else feedback_hash
            ),
        ).build_transaction({
            "from": acct.address,
            "nonce": w3.eth.get_transaction_count(acct.address),
            "chainId": ARC.chain_id,
            "gas": 200_000,
            "gasPrice": w3.eth.gas_price,
        })

        signed = acct.sign_transaction(tx)
        tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
        return FeedbackResult(True, tx_hash.hex(), None)

    except Exception as e:
        return FeedbackResult(False, None, f"tx send failed: {e}")
