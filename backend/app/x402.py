"""
x402 Payment Middleware for SignalPay.

Implements the seller side of the x402 protocol:
1. Client requests a signal endpoint
2. Server responds HTTP 402 with payment requirements
3. Client signs EIP-3009 TransferWithAuthorization, resubmits with X-Payment header
4. Server verifies the EIP-712 signature locally, then settles via the x402 facilitator
5. Server releases signal data only after a settled receipt comes back

Security invariants:
- Never fabricate a receipt. If the facilitator is unreachable, return 402.
- Locally verify the EIP-712 signature with `eth_account` before paying the facilitator.
- Reject replayed nonces, expired authorizations, and amount/recipient mismatches.
- A dev-only simulation mode is gated behind `X402_DEV_MODE=1` and is never the default.
"""

from __future__ import annotations

import json
import time
import hashlib
from typing import Optional
from dataclasses import dataclass, field

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from app.config import (
    NANOPAYMENTS_API_URL,
    X402_FACILITATOR_URL,
    X402_SETTLE_PATH,
    TOKENS,
    ARC,
    CIRCLE_API_KEY,
    GATEWAY_WALLET_BATCHED,
    X402_DEV_MODE,
)


@dataclass
class PaymentRequirement:
    """x402 payment requirement sent in 402 response."""
    price_usdc: int          # 6 decimals — 2000 = $0.002
    recipient: str           # Provider's Gateway wallet
    description: str
    network: str = "arc-testnet"
    token: str = TOKENS.USDC


@dataclass
class PaymentReceipt:
    """Validated payment receipt from the x402 facilitator."""
    payment_id: str
    amount: int
    payer: str
    recipient: str
    timestamp: int
    valid: bool


# ── In-memory payment ledger (hackathon scope) ─────────────────────

@dataclass
class PaymentLedger:
    """Tracks validated payments. In production → database."""
    receipts: list[PaymentReceipt] = field(default_factory=list)
    total_revenue: int = 0  # USDC 6 decimals
    total_calls: int = 0

    def record(self, receipt: PaymentReceipt):
        self.receipts.append(receipt)
        self.total_revenue += receipt.amount
        self.total_calls += 1

    def stats(self) -> dict:
        return {
            "total_revenue_usdc": self.total_revenue / 1_000_000,
            "total_calls": self.total_calls,
            "recent": [
                {"payer": r.payer, "amount": r.amount, "ts": r.timestamp}
                for r in self.receipts[-10:]
            ],
        }


ledger = PaymentLedger()

# An authorization can only settle once. Keyed by (from, nonce) — per-payer scope.
# Hackathon scope is in-memory; production would back this with a DB/Redis + TTL.
_used_nonces: set[tuple[str, str]] = set()


# ── x402 Response Builder ──────────────────────────────────────────

def build_402_response(requirement: PaymentRequirement) -> JSONResponse:
    """Build an HTTP 402 Payment Required response per x402 spec."""
    return JSONResponse(
        status_code=402,
        content={
            "x402": {
                "version": "2",
                "accepts": [{
                    "scheme": "exact",
                    "network": f"eip155:{ARC.chain_id}",
                    "asset": requirement.token,
                    "amount": str(requirement.price_usdc),
                    "payTo": requirement.recipient,
                    "maxTimeoutSeconds": 432000,  # 5 days — Circle requires > 3 days
                    "extra": {
                        "name": "GatewayWalletBatched",
                        "version": "1",
                        "verifyingContract": GATEWAY_WALLET_BATCHED,
                    },
                    "description": requirement.description,
                }],
            }
        },
        headers={
            "X-Payment-Required": "true",
            "X-Payment-Network": requirement.network,
            "X-Payment-Token": requirement.token,
            "X-Payment-Amount": str(requirement.price_usdc),
            "X-Payment-Recipient": requirement.recipient,
        },
    )


# ── EIP-712 signature verification ─────────────────────────────────

def _verify_eip712_authorization(
    authorization: dict,
    signature: str,
    verifying_contract: str,
) -> Optional[str]:
    """
    Recover the signer address from an EIP-3009 TransferWithAuthorization signature.
    Returns the recovered address on success, or None on any failure. The caller
    compares this against `authorization["from"]`.
    """
    from eth_account import Account
    from eth_account.messages import encode_typed_data

    try:
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
                "verifyingContract": verifying_contract,
            },
            "message": {
                "from": authorization["from"],
                "to": authorization["to"],
                "value": int(authorization["value"]),
                "validAfter": int(authorization.get("validAfter", 0)),
                "validBefore": int(authorization["validBefore"]),
                "nonce": authorization["nonce"],
            },
        }
        encoded = encode_typed_data(full_message=typed_data)
        return Account.recover_message(encoded, signature=signature)
    except Exception as e:
        print(f"[x402] EIP-712 recover failed: {e}")
        return None


# ── Payment Validation ─────────────────────────────────────────────

async def validate_payment(
    payment_header: str,
    requirement: PaymentRequirement,
) -> Optional[PaymentReceipt]:
    """
    Validate an x402 payment.

    Order of operations:
      1. Parse & structurally validate the X-Payment header.
      2. Enforce recipient, amount, and time bounds.
      3. Reject replayed nonces.
      4. Locally recover the EIP-712 signer and compare to `authorization.from`.
      5. POST to the x402 facilitator `/settle` endpoint.
      6. Only on a 2xx facilitator response do we mint a receipt.

    Any failure returns None so the caller responds 402. No fabricated receipts
    unless `X402_DEV_MODE=1` is explicitly set — and that path logs loudly.
    """
    try:
        payment_data = json.loads(payment_header)
    except (json.JSONDecodeError, ValueError):
        return None

    authorization = payment_data.get("authorization") or {}
    signature = payment_data.get("signature") or authorization.pop("signature", "")
    from_addr = authorization.get("from", "")
    to_addr = authorization.get("to", "")
    try:
        value = int(authorization.get("value", "0"))
        valid_after = int(authorization.get("validAfter", 0))
        valid_before = int(authorization.get("validBefore", 0))
    except (TypeError, ValueError):
        return None
    nonce = authorization.get("nonce", "")
    verifying_contract = (
        payment_data.get("verifyingContract")
        or (payment_data.get("extra") or {}).get("verifyingContract")
        or GATEWAY_WALLET_BATCHED
    )

    # ── 1. Structural checks ───────────────────────────────────────
    if not (from_addr and to_addr and signature and nonce):
        return None
    if value < requirement.price_usdc:
        return None
    if to_addr.lower() != requirement.recipient.lower():
        return None

    now = int(time.time())
    if valid_before and now >= valid_before:
        return None
    if valid_after and now < valid_after:
        return None

    # ── 2. Replay protection ───────────────────────────────────────
    key = (from_addr.lower(), nonce.lower())
    if key in _used_nonces:
        return None

    # ── 3. Local signature verification ────────────────────────────
    recovered = _verify_eip712_authorization(authorization, signature, verifying_contract)
    if recovered is None or recovered.lower() != from_addr.lower():
        return None

    # ── 4. Facilitator settle ──────────────────────────────────────
    receipt = await _settle_with_facilitator(
        authorization=authorization,
        signature=signature,
        requirement=requirement,
        verifying_contract=verifying_contract,
    )

    if receipt is None and X402_DEV_MODE:
        # DEV-ONLY: mark receipt as valid without a facilitator confirmation so
        # local demos can run end-to-end. Loud on purpose — cannot ship silently.
        print(
            "[x402] ⚠ DEV MODE: issuing simulated receipt because the facilitator "
            "was unreachable. Do NOT run in production."
        )
        payment_id = hashlib.sha256(
            f"{from_addr}:{value}:{nonce}".encode()
        ).hexdigest()[:16]
        receipt = PaymentReceipt(
            payment_id=payment_id,
            amount=value,
            payer=from_addr,
            recipient=requirement.recipient,
            timestamp=now,
            valid=True,
        )

    if receipt is not None and receipt.valid:
        _used_nonces.add(key)
        return receipt

    return None


async def _settle_with_facilitator(
    authorization: dict,
    signature: str,
    requirement: PaymentRequirement,
    verifying_contract: str,
) -> Optional[PaymentReceipt]:
    """Call the x402 facilitator `/settle` endpoint. Never fabricates a receipt."""
    import httpx

    if not (X402_FACILITATOR_URL or NANOPAYMENTS_API_URL):
        return None

    # Prefer the explicit x402 facilitator URL; fall back to Circle Gateway root.
    base = (X402_FACILITATOR_URL or NANOPAYMENTS_API_URL).rstrip("/")
    settle_url = f"{base}{X402_SETTLE_PATH}"

    body = {
        "paymentRequirements": {
            "scheme": "exact",
            "network": f"eip155:{ARC.chain_id}",
            "asset": requirement.token,
            "amount": str(requirement.price_usdc),
            "payTo": requirement.recipient,
            "maxTimeoutSeconds": 432000,
            "extra": {
                "name": "GatewayWalletBatched",
                "version": "1",
                "verifyingContract": verifying_contract,
            },
        },
        "payment": {
            "x402Version": 2,
            "scheme": "exact",
            "network": f"eip155:{ARC.chain_id}",
            "payload": {
                "authorization": authorization,
                "signature": signature,
            },
        },
    }

    headers = {"Content-Type": "application/json"}
    if CIRCLE_API_KEY:
        headers["Authorization"] = f"Bearer {CIRCLE_API_KEY}"

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(settle_url, json=body, headers=headers)
    except httpx.HTTPError as e:
        print(f"[x402] facilitator transport error: {e}")
        return None

    if resp.status_code // 100 != 2:
        print(f"[x402] facilitator {resp.status_code}: {resp.text[:200]}")
        return None

    try:
        result = resp.json()
    except ValueError:
        print(f"[x402] facilitator returned non-JSON body")
        return None

    if result.get("success") is False:
        print(f"[x402] facilitator rejected settlement: {result}")
        return None

    tx_id = (
        result.get("transaction")
        or result.get("txHash")
        or result.get("id")
        or hashlib.sha256(
            f"{authorization.get('from')}:{authorization.get('nonce')}".encode()
        ).hexdigest()[:16]
    )

    return PaymentReceipt(
        payment_id=str(tx_id),
        amount=int(authorization["value"]),
        payer=authorization["from"],
        recipient=requirement.recipient,
        timestamp=int(time.time()),
        valid=True,
    )


# ── FastAPI Middleware ──────────────────────────────────────────────

class X402PaymentMiddleware(BaseHTTPMiddleware):
    """
    Middleware that gates signal endpoints behind x402 nanopayments.

    Routes matching /signals/* require payment.
    Other routes (health, discovery, etc.) pass through.
    """

    def __init__(self, app, provider_wallet: str, default_price: int = 2000):
        super().__init__(app)
        self.provider_wallet = provider_wallet
        self.default_price = default_price
        self.route_prices: dict[str, int] = {}

    def set_price(self, route: str, price: int):
        self.route_prices[route] = price

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if not request.url.path.startswith("/signals/"):
            return await call_next(request)

        price = self.route_prices.get(request.url.path, self.default_price)

        requirement = PaymentRequirement(
            price_usdc=price,
            recipient=self.provider_wallet,
            description=f"Signal access: {request.url.path}",
        )

        payment_header = request.headers.get("X-Payment")

        if not payment_header:
            return build_402_response(requirement)

        receipt = await validate_payment(payment_header, requirement)

        if not receipt or not receipt.valid:
            return JSONResponse(
                status_code=402,
                content={"error": "Payment validation failed", "x402": True},
            )

        ledger.record(receipt)
        request.state.payment_receipt = receipt

        response = await call_next(request)

        response.headers["X-Payment-Confirmed"] = receipt.payment_id
        response.headers["X-Payment-Amount"] = str(receipt.amount)

        return response
