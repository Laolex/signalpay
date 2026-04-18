// API base URL resolution:
// 1. `VITE_API_BASE` env var (if set at build time)
// 2. Empty string in dev → Vite proxies `/discovery/...` etc. through the dev server
// 3. Railway production URL as final fallback so the deployed dashboard still loads
const envBase = import.meta.env.VITE_API_BASE as string | undefined;
const isProd = import.meta.env.PROD;

export const API_BASE =
  envBase?.trim() ||
  (isProd ? "https://signalpay-production.up.railway.app" : "");
