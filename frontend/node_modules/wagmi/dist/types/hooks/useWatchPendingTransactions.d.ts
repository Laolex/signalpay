import { type Config, type ResolvedRegister, type WatchPendingTransactionsParameters } from '@wagmi/core';
import type { ConfigParameter, EnabledParameter, UnionCompute, UnionExactPartial } from '@wagmi/core/internal';
export type UseWatchPendingTransactionsParameters<config extends Config = Config, chainId extends config['chains'][number]['id'] = config['chains'][number]['id']> = UnionCompute<UnionExactPartial<WatchPendingTransactionsParameters<config, chainId>> & ConfigParameter<config> & EnabledParameter>;
export type UseWatchPendingTransactionsReturnType = void;
/** https://wagmi.sh/react/api/hooks/useWatchPendingTransactions */
export declare function useWatchPendingTransactions<config extends Config = ResolvedRegister['config'], chainId extends config['chains'][number]['id'] = config['chains'][number]['id']>(parameters?: UseWatchPendingTransactionsParameters<config, chainId>): UseWatchPendingTransactionsReturnType;
//# sourceMappingURL=useWatchPendingTransactions.d.ts.map