import { http } from "wagmi";
import { defineChain } from "viem";
import { getDefaultConfig } from "@rainbow-me/rainbowkit";

export const arcTestnet = defineChain({
  id: 5042002,
  name: "Arc Testnet",
  nativeCurrency: { name: "USDC", symbol: "USDC", decimals: 6 },
  rpcUrls: { default: { http: ["https://rpc.testnet.arc.network"] } },
  blockExplorers: { default: { name: "ArcScan", url: "https://testnet.arcscan.app" } },
  testnet: true,
});

// Override via `VITE_SIGNAL_REGISTRY_ADDRESS` in .env; the fallback keeps the
// current Arc Testnet deployment usable for local dev without extra setup.
export const SIGNAL_REGISTRY_ADDRESS = (
  import.meta.env.VITE_SIGNAL_REGISTRY_ADDRESS ??
  "0x0ac5a3d3b0787bc97f101a75854bbec62ee97cc6"
) as `0x${string}`;

export const SIGNAL_REGISTRY_ABI = [
  { inputs: [], name: "totalProviders", outputs: [{ internalType: "uint256", name: "", type: "uint256" }], stateMutability: "view", type: "function" },
  { inputs: [{ internalType: "uint256", name: "providerId", type: "uint256" }], name: "getProvider", outputs: [{ internalType: "uint256", name: "agentId", type: "uint256" }, { internalType: "address", name: "providerWallet", type: "address" }, { internalType: "string", name: "endpoint", type: "string" }, { internalType: "string", name: "name", type: "string" }, { internalType: "string", name: "description", type: "string" }, { internalType: "uint8", name: "category", type: "uint8" }, { internalType: "uint256", name: "pricePerCall", type: "uint256" }, { internalType: "uint256", name: "totalCalls", type: "uint256" }, { internalType: "uint256", name: "registeredAt", type: "uint256" }, { internalType: "bool", name: "active", type: "bool" }], stateMutability: "view", type: "function" },
  { inputs: [{ internalType: "uint8", name: "category", type: "uint8" }], name: "getActiveProvidersByCategory", outputs: [{ internalType: "uint256[]", name: "", type: "uint256[]" }], stateMutability: "view", type: "function" },
  { inputs: [{ internalType: "uint8", name: "category", type: "uint8" }], name: "getCheapestProvider", outputs: [{ internalType: "uint256", name: "providerId", type: "uint256" }, { internalType: "uint256", name: "price", type: "uint256" }], stateMutability: "view", type: "function" }
] as const;

export const CATEGORY_NAMES = ["WHALE_ALERT","PRICE_ORACLE","SENTIMENT","WALLET_SCORE","TRADE_SIGNAL","ON_CHAIN_ANALYTICS"] as const;

export const wagmiConfig = getDefaultConfig({
  appName: "SignalPay",
  projectId: "signalpay-arc-hackathon",
  chains: [arcTestnet],
  transports: { [arcTestnet.id]: http("https://rpc.testnet.arc.network") },
});
