const isProd = import.meta.env.PROD;
export const API_BASE = isProd
  ? "https://signalpay-production.up.railway.app"
  : "";
