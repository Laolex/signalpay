import { useReadContract, useReadContracts } from "wagmi";
import { SIGNAL_REGISTRY_ADDRESS, SIGNAL_REGISTRY_ABI, CATEGORY_NAMES } from "./wagmi";

export interface OnChainProvider {
  id: number;
  agentId: bigint;
  providerWallet: string;
  endpoint: string;
  name: string;
  description: string;
  category: number;
  categoryName: string;
  pricePerCall: bigint;
  priceUSDC: number;
  totalCalls: bigint;
  registeredAt: bigint;
  active: boolean;
}

export function useRegistryStats() {
  return useReadContract({
    address: SIGNAL_REGISTRY_ADDRESS,
    abi: SIGNAL_REGISTRY_ABI,
    functionName: "totalProviders",
  });
}

export function useProvider(providerId: number) {
  const { data, isLoading, error } = useReadContract({
    address: SIGNAL_REGISTRY_ADDRESS,
    abi: SIGNAL_REGISTRY_ABI,
    functionName: "getProvider",
    args: [BigInt(providerId)],
  });

  if (!data) return { provider: null, isLoading, error };

  const [agentId, providerWallet, endpoint, name, description, category, pricePerCall, totalCalls, registeredAt, active] = data;

  const provider: OnChainProvider = {
    id: providerId,
    agentId,
    providerWallet,
    endpoint,
    name,
    description,
    category: Number(category),
    categoryName: CATEGORY_NAMES[Number(category)] ?? "UNKNOWN",
    pricePerCall,
    priceUSDC: Number(pricePerCall) / 1_000_000,
    totalCalls,
    registeredAt,
    active,
  };

  return { provider, isLoading, error };
}

export function useAllProviders(total: number) {
  const contracts = Array.from({ length: total }, (_, i) => ({
    address: SIGNAL_REGISTRY_ADDRESS,
    abi: SIGNAL_REGISTRY_ABI,
    functionName: "getProvider" as const,
    args: [BigInt(i)] as const,
  }));

  const { data, isLoading } = useReadContracts({ contracts });

  const providers: OnChainProvider[] = [];

  data?.forEach((result, i) => {
    if (result.status === "success" && result.result) {
      const [agentId, providerWallet, endpoint, name, description, category, pricePerCall, totalCalls, registeredAt, active] = result.result;
      if (active) {
        providers.push({
          id: i,
          agentId,
          providerWallet,
          endpoint,
          name,
          description,
          category: Number(category),
          categoryName: CATEGORY_NAMES[Number(category)] ?? "UNKNOWN",
          pricePerCall,
          priceUSDC: Number(pricePerCall) / 1_000_000,
          totalCalls,
          registeredAt,
          active,
        });
      }
    }
  });

  return { providers, isLoading };
}
