"""
Security-focused tests for the x402 payment validator.

We test the invariants that make the middleware trustworthy:
- Bad signatures are rejected
- Replayed nonces are rejected
- Wrong recipient / amount / expired bounds are rejected
- A real EIP-3009 authorization verifies and (with no facilitator) is still
  rejected — unless X402_DEV_MODE is on.
"""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import time

import pytest

# Load config module first so we can toggle env before importing x402.
os.environ.setdefault("X402_DEV_MODE", "1")

import importlib

from app import config as _config  # noqa: E402
from app import x402 as _x402  # noqa: E402
from eth_account import Account
from eth_account.messages import encode_typed_data


RECIPIENT = "0x00000000000000000000000000000000000000Ab"
VERIFYING_CONTRACT = _config.GATEWAY_WALLET_BATCHED


def _sign_authorization(
    *,
    private_key: str,
    to: str = RECIPIENT,
    value: int = 2000,
    valid_after: int = 0,
    valid_before: int | None = None,
    nonce: str | None = None,
    verifying_contract: str = VERIFYING_CONTRACT,
) -> dict:
    acct = Account.from_key(private_key)
    valid_before = valid_before or int(time.time()) + 5 * 24 * 3600
    nonce = nonce or "0x" + secrets.token_hex(32)

    typed = {
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
            "chainId": _config.ARC.chain_id,
            "verifyingContract": verifying_contract,
        },
        "message": {
            "from": acct.address,
            "to": to,
            "value": value,
            "validAfter": valid_after,
            "validBefore": valid_before,
            "nonce": nonce,
        },
    }
    encoded = encode_typed_data(full_message=typed)
    signed = Account.sign_message(encoded, private_key=private_key)
    return {
        "authorization": {
            "from": acct.address,
            "to": to,
            "value": str(value),
            "validAfter": str(valid_after),
            "validBefore": str(valid_before),
            "nonce": nonce,
        },
        "signature": signed.signature.hex(),
        "private_key": private_key,
        "from": acct.address,
    }


def _make_requirement(price: int = 2000) -> _x402.PaymentRequirement:
    return _x402.PaymentRequirement(
        price_usdc=price,
        recipient=RECIPIENT,
        description="test",
    )


@pytest.fixture(autouse=True)
def _reset_nonces():
    _x402._used_nonces.clear()
    yield
    _x402._used_nonces.clear()


@pytest.fixture
def private_key():
    return "0x" + secrets.token_hex(32)


def test_recover_roundtrip(private_key):
    sig = _sign_authorization(private_key=private_key)
    recovered = _x402._verify_eip712_authorization(
        sig["authorization"], sig["signature"], VERIFYING_CONTRACT
    )
    assert recovered and recovered.lower() == sig["from"].lower()


def test_tampered_value_fails_recovery(private_key):
    sig = _sign_authorization(private_key=private_key, value=2000)
    sig["authorization"]["value"] = "99999999"
    recovered = _x402._verify_eip712_authorization(
        sig["authorization"], sig["signature"], VERIFYING_CONTRACT
    )
    # Recovery will succeed but produce a different address
    assert recovered is None or recovered.lower() != sig["from"].lower()


def test_validate_accepts_signed_authorization(private_key, monkeypatch):
    # In dev mode, with no facilitator reachable, this should still succeed.
    monkeypatch.setattr(_x402, "X402_DEV_MODE", True)
    monkeypatch.setattr(_x402, "X402_FACILITATOR_URL", "")
    monkeypatch.setattr(_x402, "NANOPAYMENTS_API_URL", "")

    sig = _sign_authorization(private_key=private_key)
    header = json.dumps({"authorization": sig["authorization"], "signature": sig["signature"]})
    receipt = asyncio.run(_x402.validate_payment(header, _make_requirement()))
    assert receipt is not None and receipt.valid
    assert receipt.payer.lower() == sig["from"].lower()


def test_validate_rejects_when_no_facilitator_and_prod_mode(private_key, monkeypatch):
    monkeypatch.setattr(_x402, "X402_DEV_MODE", False)
    monkeypatch.setattr(_x402, "X402_FACILITATOR_URL", "")
    monkeypatch.setattr(_x402, "NANOPAYMENTS_API_URL", "")

    sig = _sign_authorization(private_key=private_key)
    header = json.dumps({"authorization": sig["authorization"], "signature": sig["signature"]})
    receipt = asyncio.run(_x402.validate_payment(header, _make_requirement()))
    assert receipt is None


def test_replay_same_nonce_rejected(private_key, monkeypatch):
    monkeypatch.setattr(_x402, "X402_DEV_MODE", True)
    monkeypatch.setattr(_x402, "X402_FACILITATOR_URL", "")
    monkeypatch.setattr(_x402, "NANOPAYMENTS_API_URL", "")

    sig = _sign_authorization(private_key=private_key)
    header = json.dumps({"authorization": sig["authorization"], "signature": sig["signature"]})

    first = asyncio.run(_x402.validate_payment(header, _make_requirement()))
    second = asyncio.run(_x402.validate_payment(header, _make_requirement()))
    assert first is not None and first.valid
    assert second is None


def test_expired_authorization_rejected(private_key, monkeypatch):
    monkeypatch.setattr(_x402, "X402_DEV_MODE", True)

    sig = _sign_authorization(
        private_key=private_key,
        valid_before=int(time.time()) - 10,
    )
    header = json.dumps({"authorization": sig["authorization"], "signature": sig["signature"]})
    receipt = asyncio.run(_x402.validate_payment(header, _make_requirement()))
    assert receipt is None


def test_wrong_recipient_rejected(private_key, monkeypatch):
    monkeypatch.setattr(_x402, "X402_DEV_MODE", True)

    sig = _sign_authorization(
        private_key=private_key,
        to="0x1111111111111111111111111111111111111111",
    )
    header = json.dumps({"authorization": sig["authorization"], "signature": sig["signature"]})
    receipt = asyncio.run(_x402.validate_payment(header, _make_requirement()))
    assert receipt is None


def test_insufficient_value_rejected(private_key, monkeypatch):
    monkeypatch.setattr(_x402, "X402_DEV_MODE", True)

    sig = _sign_authorization(private_key=private_key, value=999)  # requirement is 2000
    header = json.dumps({"authorization": sig["authorization"], "signature": sig["signature"]})
    receipt = asyncio.run(_x402.validate_payment(header, _make_requirement()))
    assert receipt is None


def test_garbage_header_rejected(monkeypatch):
    monkeypatch.setattr(_x402, "X402_DEV_MODE", True)
    receipt = asyncio.run(_x402.validate_payment("not json", _make_requirement()))
    assert receipt is None


def test_unsigned_authorization_rejected(monkeypatch):
    """The original bug: sending any JSON used to fabricate a valid receipt."""
    monkeypatch.setattr(_x402, "X402_DEV_MODE", True)
    header = json.dumps({
        "authorization": {
            "from": "0x" + "ab" * 20,
            "to": RECIPIENT,
            "value": "999999",
            "validAfter": "0",
            "validBefore": str(int(time.time()) + 3600),
            "nonce": "0x" + "00" * 32,
        },
        "signature": "0x" + "ab" * 65,
    })
    receipt = asyncio.run(_x402.validate_payment(header, _make_requirement()))
    assert receipt is None
