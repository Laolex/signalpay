"""
SignalPay configuration — Arc Testnet constants, contract addresses, nanopayments config.
"""

from dataclasses import dataclass
import os


@dataclass(frozen=True)
class ArcConfig:
    chain_id: int = 5042002
    rpc: str = "https://rpc.testnet.arc.network"
    ws: str = "wss://rpc.testnet.arc.network"
    explorer: str = "https://testnet.arcscan.app"
    faucet: str = "https://faucet.circle.com"
    cctp_domain: int = 26


@dataclass(frozen=True)
class Tokens:
    USDC: str = "0x3600000000000000000000000000000000000000"
    EURC: str = "0x89B50855Aa3bE2F677cD6303Cec089B5F319D72a"


@dataclass(frozen=True)
class ERC8004:
    identity_registry: str = "0x8004A818BFB912233c491871b3d84c89A494BD9e"
    reputation_registry: str = "0x8004B663056A597Dffe9eCcC1965A193B7388713"
    validation_registry: str = "0x8004Cb1BF31DAf7788923b405b754f57acEB4272"


ARC = ArcConfig()
TOKENS = Tokens()
ERC_8004 = ERC8004()

# Populated after deployment
SIGNAL_REGISTRY_ADDRESS = os.getenv("SIGNAL_REGISTRY_ADDRESS", "")

# Circle credentials
CIRCLE_API_KEY = os.getenv("CIRCLE_API_KEY", "")
CIRCLE_ENTITY_SECRET = os.getenv("CIRCLE_ENTITY_SECRET", "")

# Circle Gateway
GATEWAY_WALLET_BATCHED = "0x0077777d7EBA4688BDeF3E311b846F25870A19B9"
NANOPAYMENTS_API_URL = os.getenv(
    "NANOPAYMENTS_API_URL",
    "https://gateway-api-testnet.circle.com/gateway/v1",
)

# Provider pricing (USDC 6 decimals)
DEFAULT_PRICES = {
    "whale_alert": 2000,        # $0.002 per call
    "price_oracle": 1000,       # $0.001 per call
    "wallet_score": 5000,       # $0.005 per call
    "sentiment": 3000,          # $0.003 per call
    "trade_signal": 10000,      # $0.01 per call
}
