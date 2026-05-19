"""
Live integration test: signs a real EIP-3009 authorization and sends it
to the Circle testnet facilitator. Run with:

    PYTHONPATH=backend .venv/bin/python -m pytest backend/tests/test_live_facilitator.py -v -s

Requires .env to be sourced with PRIVATE_KEY and PROVIDER_WALLET set.
The signing wallet needs Arc testnet USDC for actual settlement to succeed
(insufficient_balance is still a valid facilitator response — it means the
endpoint is reachable and the signature was accepted).
"""

from __future__ import annotations

import os
import secrets
import time

import httpx
import pytest
from eth_account import Account
from eth_account.messages import encode_typed_data

from dotenv import load_dotenv
load_dotenv()

from app.config import (
    ARC,
    TOKENS,
    NANOPAYMENTS_API_URL,
    X402_SETTLE_PATH,
    GATEWAY_WALLET_BATCHED,
)

PRIVATE_KEY = os.getenv("PRIVATE_KEY", "")
PROVIDER_WALLET = os.getenv("PROVIDER_WALLET", "")
SETTLE_URL = NANOPAYMENTS_API_URL.rstrip("/") + X402_SETTLE_PATH


def _build_signed_payment(private_key: str, recipient: str, amount: int = 1000) -> dict:
    acct = Account.from_key(private_key)
    nonce = "0x" + secrets.token_hex(32)
    valid_before = int(time.time()) + 5 * 24 * 3600  # 5 days

    authorization = {
        "from": acct.address,
        "to": recipient,
        "value": amount,
        "validAfter": 0,
        "validBefore": valid_before,
        "nonce": nonce,
    }

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
            "chainId": ARC.chain_id,
            "verifyingContract": GATEWAY_WALLET_BATCHED,
        },
        "message": {
            **authorization,
            "value": amount,
        },
    }

    encoded = encode_typed_data(full_message=typed_data)
    signed = acct.sign_message(encoded)
    signature = signed.signature.hex()
    if not signature.startswith("0x"):
        signature = "0x" + signature

    # Circle requires these as strings
    str_authorization = {
        **authorization,
        "value": str(amount),
        "validAfter": str(0),
        "validBefore": str(valid_before),
    }
    return {
        "authorization": str_authorization,
        "signature": signature,
        "verifyingContract": GATEWAY_WALLET_BATCHED,
    }


def _build_settle_body(payment: dict, recipient: str, amount: int) -> dict:
    req = {
        "scheme": "exact",
        "network": f"eip155:{ARC.chain_id}",
        "asset": TOKENS.USDC,
        "amount": str(amount),
        "payTo": recipient,
        "maxTimeoutSeconds": 432000,
        "extra": {
            "name": "GatewayWalletBatched",
            "version": "1",
            "verifyingContract": GATEWAY_WALLET_BATCHED,
        },
    }
    return {
        "paymentPayload": {
            "x402Version": 2,
            "resource": {
                "url": "https://signalpay-production.up.railway.app/signals/price-oracle",
                "description": "Signal access: price-oracle",
                "mimeType": "application/json",
            },
            "accepted": req,
            "payload": {
                "authorization": payment["authorization"],
                "signature": payment["signature"],
            },
        },
        "paymentRequirements": req,
    }


@pytest.mark.skipif(not PRIVATE_KEY, reason="PRIVATE_KEY not set")
def test_facilitator_reachable():
    """Facilitator endpoint must exist and return a JSON response (not 404/503)."""
    resp = httpx.post(SETTLE_URL, json={"paymentPayload": {}, "paymentRequirements": {}}, timeout=15)
    assert resp.status_code != 404, f"Facilitator not found at {SETTLE_URL}"
    assert resp.status_code != 503, "Facilitator is down"
    # 400 is expected for empty payload — endpoint is alive
    print(f"\nFacilitator status: {resp.status_code} — {resp.text[:200]}")


@pytest.mark.skipif(not PRIVATE_KEY or not PROVIDER_WALLET, reason="PRIVATE_KEY or PROVIDER_WALLET not set")
def test_signed_payment_accepted_by_facilitator():
    """
    Signs a real EIP-3009 authorization and POSTs to the Circle facilitator.
    Acceptable outcomes:
      - 200 success=true  → payment settled (wallet has USDC)
      - 200 success=false, errorReason=insufficient_balance → sig valid, no funds
      - 200 success=false, errorReason=wallet_not_found → wallet not registered
    Unacceptable: invalid_signature, nonce_already_used, address_mismatch, 400/404/503
    """
    payment = _build_signed_payment(PRIVATE_KEY, PROVIDER_WALLET, amount=1000)
    body = _build_settle_body(payment, PROVIDER_WALLET, amount=1000)

    resp = httpx.post(SETTLE_URL, json=body, timeout=15)
    print(f"\nFacilitator response: {resp.status_code}")
    print(f"Body: {resp.text[:500]}")

    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"

    result = resp.json()
    assert "success" in result, f"Missing 'success' in response: {result}"

    if result["success"]:
        print(f"Payment SETTLED — tx: {result.get('transaction')}")
    else:
        reason = result.get("errorReason", "unknown")
        # These mean the sig was good — just no balance or wallet not provisioned
        acceptable = {"insufficient_balance", "wallet_not_found", "self_transfer"}
        assert reason in acceptable, (
            f"Unexpected failure: {reason}. "
            f"If 'invalid_signature', check EIP-712 domain or key format."
        )
        print(f"Payment rejected (expected in testnet): {reason}")
