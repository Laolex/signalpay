// API base URL resolution:
// 1. `VITE_API_BASE` env var (if set at build time)
// 2. Cloudflare tunnel URL in production
// 3. Empty string in dev → Vite proxies through the dev server
const envBase = import.meta.env.VITE_API_BASE as string | undefined;
const isProd = import.meta.env.PROD;

const TUNNEL_URL = "https://strips-extraction-final-frequency.trycloudflare.com";

export const API_BASE =
  envBase?.trim() ||
  (isProd ? TUNNEL_URL : "");
