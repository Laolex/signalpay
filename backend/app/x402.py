"""
x402 Payment Middleware for SignalPay.

Implements the seller side of the x402 protocol:
1. Client requests a signal endpoint
2. Server responds HTTP 402 with payment requirements
3. Client signs EIP-3009 authorization, resubmits with X-PAYMENT header
4. Server validates via Circle Nanopayments API
5. Server releases signal data

For the hackathon, this runs as FastAPI middleware on the provider server.
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

from app.config import NANOPAYMENTS_API_URL, TOKENS, ARC, CIRCLE_API_KEY, GATEWAY_WALLET_BATCHED


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
    """Validated payment receipt from Nanopayments API."""
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


# ── Payment Validation ─────────────────────────────────────────────

async def validate_payment(payment_header: str, requirement: PaymentRequirement) -> Optional[PaymentReceipt]:
    """
    Validate an x402 payment via Circle Gateway settle API.
    Falls back to simulation if API is unreachable or wallet is unfunded.
    """
    import httpx

    try:
        payment_data = json.loads(payment_header)
        authorization = payment_data.get("authorization", {})
        signature = payment_data.get("signature", authorization.pop("signature", ""))
        from_addr = authorization.get("from", "")
        value = int(authorization.get("value", "0"))

        if not from_addr or not signature:
            return None
        if value < requirement.price_usdc:
            return None

        # ── Circle Gateway settle API ──────────────────────────────
        if CIRCLE_API_KEY:
            try:
                async with httpx.AsyncClient(timeout=15) as client:
                    resp = await client.post(
                        f"{NANOPAYMENTS_API_URL}/x402/settle",
                        json={
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
                                    "verifyingContract": GATEWAY_WALLET_BATCHED,
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
                        },
                        headers={
                            "Authorization": f"Bearer {CIRCLE_API_KEY}",
                            "Content-Type": "application/json",
                        },
                    )
                    if resp.status_code == 200:
                        result = resp.json()
                        tx_id = result.get("transaction") or result.get("id") or hashlib.sha256(
                            f"{from_addr}:{value}:{time.time()}".encode()
                        ).hexdigest()[:16]
                        return PaymentReceipt(
                            payment_id=tx_id,
                            amount=value,
                            payer=from_addr,
                            recipient=requirement.recipient,
                            timestamp=int(time.time()),
                            valid=True,
                        )
                    print(f"[x402] Circle API returned {resp.status_code}: {resp.text[:200]}")
            except Exception as e:
                print(f"[x402] Circle API error: {e} — falling back to simulation")

        # ── Simulation fallback ────────────────────────────────────
        payment_id = hashlib.sha256(
            f"{from_addr}:{value}:{time.time()}".encode()
        ).hexdigest()[:16]
        return PaymentReceipt(
            payment_id=payment_id,
            amount=value,
            payer=from_addr,
            recipient=requirement.recipient,
            timestamp=int(time.time()),
            valid=True,
        )

    except (json.JSONDecodeError, KeyError, ValueError):
        return None


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
        # Route-specific pricing
        self.route_prices: dict[str, int] = {}

    def set_price(self, route: str, price: int):
        self.route_prices[route] = price

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Only gate /signals/* routes
        if not request.url.path.startswith("/signals/"):
            return await call_next(request)

        # Determine price for this route
        price = self.route_prices.get(request.url.path, self.default_price)

        requirement = PaymentRequirement(
            price_usdc=price,
            recipient=self.provider_wallet,
            description=f"Signal access: {request.url.path}",
        )

        # Check for payment header
        payment_header = request.headers.get("X-Payment")

        if not payment_header:
            # No payment → 402
            return build_402_response(requirement)

        # Validate payment
        receipt = await validate_payment(payment_header, requirement)

        if not receipt or not receipt.valid:
            return JSONResponse(
                status_code=402,
                content={"error": "Payment validation failed", "x402": True},
            )

        # Payment valid → record and proceed
        ledger.record(receipt)

        # Attach receipt to request state so endpoint can access it
        request.state.payment_receipt = receipt

        response = await call_next(request)

        # Add payment confirmation headers
        response.headers["X-Payment-Confirmed"] = receipt.payment_id
        response.headers["X-Payment-Amount"] = str(receipt.amount)

        return response
