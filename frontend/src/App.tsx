import { useState, useEffect, useRef, useCallback } from "react";
import { ConnectButton } from "@rainbow-me/rainbowkit";
import { useAccount, useChainId } from "wagmi";
import { useRegistryStats, useAllProviders } from "./useRegistry";
import { SIGNAL_REGISTRY_ADDRESS } from "./wagmi";

// ── Simulated Data ──────────────────────────────────────────────
const PROVIDERS = [
  { id: 0, name: "Whale Tracker Alpha", category: "WHALE_ALERT", price: 0.002, reputation: 94, calls: 12847, endpoint: "/signals/whale-alert", status: "live" },
  { id: 1, name: "Arc Price Oracle", category: "PRICE_ORACLE", price: 0.001, reputation: 97, calls: 45210, endpoint: "/signals/price/{token}", status: "live" },
  { id: 2, name: "Wallet Scorer v1", category: "WALLET_SCORE", price: 0.005, reputation: 88, calls: 3291, endpoint: "/signals/wallet-score", status: "live" },
  { id: 3, name: "Sentiment Engine", category: "SENTIMENT", price: 0.003, reputation: 91, calls: 8734, endpoint: "/signals/sentiment/{token}", status: "live" },
];

const TOKENS = ["BTC", "ETH", "SOL", "ARC"];
const DIRECTIONS = ["transfer_in", "transfer_out", "swap", "stake", "unstake"];

function randomBetween(a: number, b: number) { return Math.random() * (b - a) + a; }
function randomInt(a: number, b: number) { return Math.floor(randomBetween(a, b)); }
function shortHash() { return "0x" + Array.from({ length: 8 }, () => Math.floor(Math.random() * 16).toString(16)).join(""); }
function timeAgo(ms: number) { const s = Math.floor(ms / 1000); if (s < 60) return `${s}s ago`; return `${Math.floor(s / 60)}m ago`; }

function generateSignal(category: string) {
  const now = Date.now();
  if (category === "WHALE_ALERT") {
    const token = TOKENS[randomInt(0, 4)];
    const amount = randomBetween(500000, 25000000);
    return { category, timestamp: now, token, data: { amount_usd: amount, direction: DIRECTIONS[randomInt(0, 5)], whale_score: randomBetween(60, 99).toFixed(1), chain: ["solana", "ethereum", "arc"][randomInt(0, 3)] }, confidence: randomBetween(0.65, 0.97) };
  }
  if (category === "PRICE_ORACLE") {
    const token = TOKENS[randomInt(0, 4)];
    const prices: Record<string, [number, number]> = { BTC: [64000, 71000], ETH: [3100, 3900], SOL: [135, 185], ARC: [0.94, 1.06] };
    const [lo, hi] = prices[token];
    return { category, timestamp: now, token, data: { price_usd: randomBetween(lo, hi), change_24h: randomBetween(-5, 5) }, confidence: randomBetween(0.88, 0.99) };
  }
  if (category === "WALLET_SCORE") {
    return { category, timestamp: now, token: "—", data: { alpha_score: randomBetween(20, 95).toFixed(1), risk_score: randomBetween(10, 80).toFixed(1), win_rate: randomBetween(0.3, 0.8).toFixed(2), wallet: shortHash() + "..." }, confidence: randomBetween(0.7, 0.95) };
  }
  const token = TOKENS[randomInt(0, 4)];
  const score = randomBetween(-1, 1);
  return { category: "SENTIMENT", timestamp: now, token, data: { sentiment_score: score, label: score > 0.2 ? "bullish" : score < -0.2 ? "bearish" : "neutral", mentions_1h: randomInt(50, 5000) }, confidence: randomBetween(0.5, 0.92) };
}


// ── Category Colors ─────────────────────────────────────────────
const CAT_COLORS: Record<string, string> = {
  WHALE_ALERT: "#00e5ff",
  PRICE_ORACLE: "#76ff03",
  WALLET_SCORE: "#ffab00",
  SENTIMENT: "#ea80fc",
};

const CAT_ICONS: Record<string, string> = {
  WHALE_ALERT: "🐋",
  PRICE_ORACLE: "📊",
  WALLET_SCORE: "🔍",
  SENTIMENT: "💬",
};

// ── Components ──────────────────────────────────────────────────
function TabBar({ active, onSelect, tabs }: { active: string; onSelect: (id: string) => void; tabs: { id: string; label: string; icon?: string }[] }) {
  return (
    <div style={{ display: "flex", gap: 0, borderBottom: "1px solid #1a2332" }}>
      {tabs.map((t) => (
        <button key={t.id} onClick={() => onSelect(t.id)} style={{
          background: active === t.id ? "#0d1821" : "transparent",
          color: active === t.id ? "#00e5ff" : "#4a6274",
          border: "none", borderBottom: active === t.id ? "2px solid #00e5ff" : "2px solid transparent",
          padding: "10px 18px", cursor: "pointer", fontFamily: "'IBM Plex Mono', monospace",
          fontSize: "11px", letterSpacing: "0.08em", textTransform: "uppercase", fontWeight: 600,
          transition: "all 0.2s",
        }}>
          {t.icon && <span style={{ marginRight: 6 }}>{t.icon}</span>}
          {t.label}
        </button>
      ))}
    </div>
  );
}

function SignalCard({ signal, delay = 0 }: { signal: ReturnType<typeof generateSignal>; delay?: number }) {
  const color = CAT_COLORS[signal.category] || "#fff";
  const icon = CAT_ICONS[signal.category] || "•";
  const conf = (signal.confidence * 100).toFixed(0);

  return (
    <div style={{
      background: "linear-gradient(135deg, #0a1018 0%, #0d1520 100%)",
      border: `1px solid ${color}22`, borderLeft: `3px solid ${color}`,
      borderRadius: 6, padding: "12px 14px", marginBottom: 8,
      animation: `fadeSlideIn 0.4s ease ${delay}ms both`,
    }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
        <span style={{ color, fontSize: 11, fontWeight: 700, letterSpacing: "0.06em", fontFamily: "'IBM Plex Mono', monospace" }}>
          {icon} {signal.category.replace("_", " ")}
        </span>
        <span style={{ color: "#3a5060", fontSize: 10, fontFamily: "'IBM Plex Mono', monospace" }}>
          {timeAgo(Date.now() - signal.timestamp)}
        </span>
      </div>
      {signal.category === "WHALE_ALERT" && (
        <div style={{ fontSize: 13, color: "#c8d6e5" }}>
          <span style={{ color: (signal.data as any).direction.includes("in") || (signal.data as any).direction === "stake" ? "#76ff03" : "#ff5252" }}>
            {(signal.data as any).direction.toUpperCase()}
          </span>
          {" "}${Number((signal.data as any).amount_usd).toLocaleString(undefined, { maximumFractionDigits: 0 })} <span style={{ color }}>{signal.token}</span>
          <span style={{ color: "#4a6274", fontSize: 11 }}> on {(signal.data as any).chain}</span>
          <div style={{ color: "#4a6274", fontSize: 10, marginTop: 4 }}>whale score: {(signal.data as any).whale_score}</div>
        </div>
      )}
      {signal.category === "PRICE_ORACLE" && (
        <div style={{ fontSize: 13, color: "#c8d6e5" }}>
          <span style={{ color }}>{signal.token}</span> ${Number((signal.data as any).price_usd).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
          <span style={{ color: (signal.data as any).change_24h >= 0 ? "#76ff03" : "#ff5252", marginLeft: 8 }}>
            {(signal.data as any).change_24h >= 0 ? "+" : ""}{(signal.data as any).change_24h.toFixed(2)}%
          </span>
        </div>
      )}
      {signal.category === "WALLET_SCORE" && (
        <div style={{ fontSize: 13, color: "#c8d6e5" }}>
          {(signal.data as any).wallet} <span style={{ color: "#4a6274" }}>→</span> Alpha: <span style={{ color }}>{(signal.data as any).alpha_score}</span> Risk: <span style={{ color: "#ffab00" }}>{(signal.data as any).risk_score}</span> WR: {(signal.data as any).win_rate}
        </div>
      )}
      {signal.category === "SENTIMENT" && (
        <div style={{ fontSize: 13, color: "#c8d6e5" }}>
          <span style={{ color }}>{signal.token}</span>{" "}
          <span style={{
            color: (signal.data as any).label === "bullish" ? "#76ff03" : (signal.data as any).label === "bearish" ? "#ff5252" : "#ffab00",
            fontWeight: 700,
          }}>{(signal.data as any).label.toUpperCase()}</span>
          <span style={{ color: "#4a6274", fontSize: 11 }}> ({(signal.data as any).sentiment_score.toFixed(2)}) — {(signal.data as any).mentions_1h} mentions/hr</span>
        </div>
      )}
      <div style={{ marginTop: 6, display: "flex", alignItems: "center", gap: 8 }}>
        <div style={{ flex: 1, height: 3, background: "#1a2332", borderRadius: 2, overflow: "hidden" }}>
          <div style={{ width: `${conf}%`, height: "100%", background: color, borderRadius: 2, transition: "width 0.5s" }} />
        </div>
        <span style={{ color: "#4a6274", fontSize: 10, fontFamily: "'IBM Plex Mono', monospace", minWidth: 36, textAlign: "right" }}>{conf}%</span>
      </div>
    </div>
  );
}

const ACTION_COLORS: Record<string, string> = { INIT: "#4a6274", DISCOVER: "#00e5ff", SELECT: "#76ff03", PAY: "#ffab00", RECEIVE: "#ea80fc", REPUTATION: "#4a6274", ANALYZE: "#00e5ff", SUMMARY: "#76ff03" };

function normalizeSignal(raw: any) {
  if (!raw) return null;
  const cat = (raw.category || "").toUpperCase().replace(/-/g, "_");
  const d = raw.data || {};
  // Remap backend field names → frontend SignalCard field names
  const data = {
    ...d,
    change_24h: d.change_24h ?? d.change_24h_pct ?? 0,
    wallet: d.wallet ?? d.wallet_address ?? "0x???",
    label: d.label ?? d.sentiment_label ?? "neutral",
    mentions_1h: d.mentions_1h ?? d.sources_analyzed ?? 0,
  };
  return { category: cat, timestamp: (raw.timestamp || 0) * 1000, token: data.token || raw.token || "?", data, confidence: raw.confidence || 0 };
}

function AgentConsole({ signals, onSignal }: { signals: ReturnType<typeof generateSignal>[]; onSignal: (s: any) => void }) {
  const [logs, setLogs] = useState<{ action: string; msg: string; color: string; ts: number }[]>([]);
  const [running, setRunning] = useState(false);
  const [budget, setBudget] = useState(0.1);
  const [spent, setSpent] = useState(0);
  const [signalCount, setSignalCount] = useState(0);
  const scrollRef = useRef<HTMLDivElement>(null);

  const addLog = useCallback((action: string, msg: string) => {
    setLogs((prev) => [...prev, { action, msg, color: ACTION_COLORS[action] || "#8a9aaa", ts: Date.now() }]);
  }, []);

  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [logs]);

  const runAgent = useCallback(async () => {
    if (running) return;
    setRunning(true);
    setLogs([]);
    setBudget(0.1);
    setSpent(0);
    setSignalCount(0);

    try {
      const resp = await fetch("http://localhost:8000/agent/run", { method: "POST" });
      const reader = resp.body!.getReader();
      const decoder = new TextDecoder();
      let buf = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const lines = buf.split("\n");
        buf = lines.pop() || "";
        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          try {
            const event = JSON.parse(line.slice(6));
            if (event.action === "DONE") { setRunning(false); return; }
            addLog(event.action, event.msg || "");
            if (event.budget !== undefined) setBudget(event.budget);
            if (event.spent !== undefined) setSpent(event.spent);
            if (event.signals !== undefined) setSignalCount(event.signals);
            if (event.signal) {
              const norm = normalizeSignal(event.signal);
              if (norm) onSignal(norm);
            }
          } catch { /* malformed event */ }
        }
      }
    } catch (err) {
      addLog("ERROR", `Failed to connect to backend: ${err}`);
    }
    setRunning(false);
  }, [running, addLog, onSignal]);

  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 300px", gap: 16, height: "100%" }}>
      <div style={{ display: "flex", flexDirection: "column" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <div style={{ width: 8, height: 8, borderRadius: "50%", background: running ? "#76ff03" : "#4a6274", boxShadow: running ? "0 0 8px #76ff03" : "none", animation: running ? "pulse 1s infinite" : "none" }} />
            <span style={{ color: running ? "#76ff03" : "#4a6274", fontSize: 11, fontFamily: "'IBM Plex Mono', monospace", letterSpacing: "0.08em" }}>
              {running ? "AGENT RUNNING" : "AGENT IDLE"}
            </span>
          </div>
          <button onClick={runAgent} disabled={running} style={{
            background: running ? "#1a2332" : "linear-gradient(135deg, #00e5ff 0%, #00b0ff 100%)",
            color: running ? "#4a6274" : "#000", border: "none", borderRadius: 4,
            padding: "6px 16px", cursor: running ? "default" : "pointer",
            fontFamily: "'IBM Plex Mono', monospace", fontSize: 11, fontWeight: 700,
            letterSpacing: "0.06em", transition: "all 0.3s",
          }}>
            {running ? "RUNNING..." : "▶ RUN AGENT"}
          </button>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 8, marginBottom: 12 }}>
          {[
            { label: "BUDGET", value: `$${budget.toFixed(6)}`, color: "#00e5ff" },
            { label: "SPENT", value: `$${spent.toFixed(6)}`, color: "#ffab00" },
            { label: "SIGNALS", value: signalCount, color: "#76ff03" },
          ].map((s) => (
            <div key={s.label} style={{ background: "#0a1018", border: "1px solid #1a2332", borderRadius: 4, padding: "8px 10px", textAlign: "center" }}>
              <div style={{ color: "#3a5060", fontSize: 9, letterSpacing: "0.1em", fontFamily: "'IBM Plex Mono', monospace", marginBottom: 2 }}>{s.label}</div>
              <div style={{ color: s.color, fontSize: 16, fontWeight: 700, fontFamily: "'IBM Plex Mono', monospace" }}>{s.value}</div>
            </div>
          ))}
        </div>

        <div ref={scrollRef} style={{
          flex: 1, background: "#060a0f", border: "1px solid #1a2332", borderRadius: 6,
          padding: 12, overflowY: "auto", fontFamily: "'IBM Plex Mono', monospace", fontSize: 11,
          minHeight: 300,
        }}>
          {logs.length === 0 && (
            <div style={{ color: "#2a3a4a", textAlign: "center", paddingTop: 60 }}>
              Press RUN AGENT to start a trading session
            </div>
          )}
          {logs.map((l, i) => (
            <div key={i} style={{ marginBottom: 4, animation: "fadeSlideIn 0.3s ease both", display: "flex", gap: 8 }}>
              <span style={{ color: "#2a3a4a", minWidth: 60, flexShrink: 0 }}>{new Date(l.ts).toLocaleTimeString("en", { hour12: false })}</span>
              <span style={{ color: l.color || "#4a6274" }}>[{l.action}]</span>
              <span style={{ color: "#8a9aaa" }}>{l.msg}</span>
            </div>
          ))}
          {running && <div style={{ color: "#00e5ff", animation: "blink 1s infinite" }}>▊</div>}
        </div>
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <div style={{ color: "#3a5060", fontSize: 10, letterSpacing: "0.1em", fontFamily: "'IBM Plex Mono', monospace", marginBottom: 4 }}>LIVE SIGNAL FEED</div>
        <div style={{ flex: 1, overflowY: "auto" }}>
          {signals.slice(0, 8).map((s, i) => <SignalCard key={i} signal={s} delay={i * 50} />)}
          {signals.length === 0 && <div style={{ color: "#2a3a4a", textAlign: "center", paddingTop: 40, fontSize: 11 }}>Signals appear as agent purchases them</div>}
        </div>
      </div>
    </div>
  );
}

function SignalExplorer() {
  const [selected, setSelected] = useState<number | null>(null);
  const [providers, setProviders] = useState(PROVIDERS);
  const [stats, setStats] = useState<{ total_calls: number; total_revenue_usdc: number } | null>(null);

  useEffect(() => {
    fetch("/discovery/providers")
      .then((r) => r.json())
      .then((data) => {
        const raw = data.providers || [];
        setProviders(raw.map((p: any, i: number) => ({
          id: i,
          name: p.name || p.id,
          category: (p.id || "").toUpperCase(),
          price: p.price_usdc || 0,
          reputation: Math.floor(Math.random() * 10) + 88,
          calls: 0,
          endpoint: p.endpoint || "",
          status: "live",
        })));
      })
      .catch(() => {});
    fetch("/stats")
      .then((r) => r.json())
      .then(setStats)
      .catch(() => {});
  }, []);

  const totalCalls = stats?.total_calls ?? providers.reduce((s, p) => s + p.calls, 0);
  const avgPrice = providers.length ? (providers.reduce((s, p) => s + p.price, 0) / providers.length) : 0;

  return (
    <div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(2, 1fr)", gap: 12, marginBottom: 16 }}>
        {providers.map((p) => {
          const color = CAT_COLORS[p.category];
          const icon = CAT_ICONS[p.category];
          const isSelected = selected === p.id;
          return (
            <div key={p.id} onClick={() => setSelected(isSelected ? null : p.id)} style={{
              background: isSelected ? `${color}08` : "#0a1018",
              border: `1px solid ${isSelected ? color + "44" : "#1a2332"}`,
              borderRadius: 8, padding: 16, cursor: "pointer", transition: "all 0.3s",
            }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 10 }}>
                <div>
                  <span style={{ fontSize: 20, marginRight: 8 }}>{icon}</span>
                  <span style={{ color: "#e0e8f0", fontSize: 14, fontWeight: 600 }}>{p.name}</span>
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
                  <div style={{ width: 6, height: 6, borderRadius: "50%", background: "#76ff03" }} />
                  <span style={{ color: "#76ff03", fontSize: 9, fontFamily: "'IBM Plex Mono', monospace" }}>LIVE</span>
                </div>
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 8 }}>
                {[
                  { label: "PRICE", value: `$${p.price}`, color },
                  { label: "REPUTATION", value: `${p.reputation}/100`, color: p.reputation > 90 ? "#76ff03" : "#ffab00" },
                  { label: "CALLS", value: p.calls.toLocaleString(), color: "#4a6274" },
                ].map((s) => (
                  <div key={s.label}>
                    <div style={{ color: "#3a5060", fontSize: 8, letterSpacing: "0.1em", fontFamily: "'IBM Plex Mono', monospace" }}>{s.label}</div>
                    <div style={{ color: s.color, fontSize: 13, fontWeight: 600, fontFamily: "'IBM Plex Mono', monospace" }}>{s.value}</div>
                  </div>
                ))}
              </div>
              {isSelected && (
                <div style={{ marginTop: 12, paddingTop: 12, borderTop: `1px solid ${color}22` }}>
                  <div style={{ color: "#4a6274", fontSize: 10, fontFamily: "'IBM Plex Mono', monospace", marginBottom: 4 }}>ENDPOINT</div>
                  <div style={{ color, fontSize: 11, fontFamily: "'IBM Plex Mono', monospace", background: "#060a0f", padding: "6px 8px", borderRadius: 4 }}>
                    GET {p.endpoint}
                  </div>
                  <div style={{ color: "#4a6274", fontSize: 10, fontFamily: "'IBM Plex Mono', monospace", marginTop: 8, marginBottom: 4 }}>x402 PAYMENT FLOW</div>
                  <div style={{ fontSize: 10, color: "#6a7a8a", lineHeight: 1.6 }}>
                    1. Request → HTTP 402<br />
                    2. Sign EIP-3009 auth → ${p.price} USDC<br />
                    3. Resubmit with X-Payment header<br />
                    4. Receive signal data instantly
                  </div>
                  <div style={{ color: "#4a6274", fontSize: 10, fontFamily: "'IBM Plex Mono', monospace", marginTop: 8, marginBottom: 4 }}>ON-CHAIN IDENTITY</div>
                  <div style={{ fontSize: 10, color: "#6a7a8a" }}>
                    ERC-8004 Agent #{1000 + p.id} • Registered on Arc Testnet
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>
      <div style={{ background: "#0a1018", border: "1px solid #1a2332", borderRadius: 8, padding: 16 }}>
        <div style={{ color: "#3a5060", fontSize: 10, letterSpacing: "0.1em", fontFamily: "'IBM Plex Mono', monospace", marginBottom: 8 }}>MARKETPLACE STATS</div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 16 }}>
          {[
            { label: "PROVIDERS", value: String(providers.length), color: "#00e5ff" },
            { label: "TOTAL CALLS", value: totalCalls.toLocaleString(), color: "#76ff03" },
            { label: "AVG PRICE", value: `$${avgPrice.toFixed(5)}`, color: "#ffab00" },
            { label: "SETTLEMENT", value: "ARC L1", color: "#ea80fc" },
          ].map((s) => (
            <div key={s.label} style={{ textAlign: "center" }}>
              <div style={{ color: "#3a5060", fontSize: 8, letterSpacing: "0.1em", fontFamily: "'IBM Plex Mono', monospace", marginBottom: 2 }}>{s.label}</div>
              <div style={{ color: s.color, fontSize: 18, fontWeight: 700, fontFamily: "'IBM Plex Mono', monospace" }}>{s.value}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function ProviderDashboard() {
  const [earnings] = useState(() => Array.from({ length: 24 }, (_, i) => ({
    hour: i, usdc: randomBetween(0.5, 8).toFixed(2), calls: randomInt(50, 800),
  })));
  const maxEarning = Math.max(...earnings.map((e) => parseFloat(e.usdc)));
  const [stats, setStats] = useState<{ total_revenue_usdc: number; total_calls: number } | null>(null);

  // ── Live chain data ──────────────────────────────────────────
  const { data: totalOnChain } = useRegistryStats();
  const { providers: chainProviders, isLoading: loadingProviders } = useAllProviders(Number(totalOnChain ?? 0));

  // Merge chain providers with reputation scores (simulated until ERC-8004 reputation reads)
  const repProviders = chainProviders.length > 0
    ? chainProviders.map((p) => ({ ...p, reputation: 88 + Number(p.totalCalls % 10n) }))
    : PROVIDERS.map((p) => ({ ...p, categoryName: p.category, priceUSDC: p.price, reputation: p.reputation }));

  useEffect(() => {
    fetch("/stats").then((r) => r.json()).then(setStats).catch(() => {});
  }, []);

  const totalEarnings = stats?.total_revenue_usdc ?? 0;
  const totalCalls = stats?.total_calls ?? Number(chainProviders.reduce((s, p) => s + p.totalCalls, 0n));

  return (
    <div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 12, marginBottom: 16 }}>
        {[
          { label: "TOTAL EARNINGS", value: `$${totalEarnings.toFixed(6)}`, sub: "USDC", color: "#76ff03" },
          { label: "SESSION CALLS", value: totalCalls.toLocaleString(), sub: "validated", color: "#00e5ff" },
          { label: "TOTAL CALLS", value: totalCalls.toLocaleString(), sub: "lifetime", color: "#ffab00" },
          { label: "AVG REPUTATION", value: repProviders.length ? (repProviders.reduce((s, p) => s + p.reputation, 0) / repProviders.length).toFixed(1) : "—", sub: "/100", color: "#ea80fc" },
        ].map((s) => (
          <div key={s.label} style={{ background: "#0a1018", border: "1px solid #1a2332", borderRadius: 8, padding: 14 }}>
            <div style={{ color: "#3a5060", fontSize: 9, letterSpacing: "0.1em", fontFamily: "'IBM Plex Mono', monospace", marginBottom: 6 }}>{s.label}</div>
            <div style={{ color: s.color, fontSize: 22, fontWeight: 700, fontFamily: "'IBM Plex Mono', monospace" }}>{s.value}</div>
            <div style={{ color: "#3a5060", fontSize: 10 }}>{s.sub}</div>
          </div>
        ))}
      </div>

      <div style={{ background: "#0a1018", border: "1px solid #1a2332", borderRadius: 8, padding: 16, marginBottom: 16 }}>
        <div style={{ color: "#3a5060", fontSize: 10, letterSpacing: "0.1em", fontFamily: "'IBM Plex Mono', monospace", marginBottom: 12 }}>EARNINGS — LAST 24H (USDC)</div>
        <div style={{ display: "flex", alignItems: "flex-end", gap: 2, height: 120 }}>
          {earnings.map((e, i) => {
            const h = (parseFloat(e.usdc) / maxEarning) * 100;
            return (
              <div key={i} title={`${e.hour}:00 — $${e.usdc} USDC — ${e.calls} calls`} style={{
                flex: 1, height: `${h}%`, background: `linear-gradient(to top, #00e5ff33, #00e5ff${h > 70 ? "cc" : "66"})`,
                borderRadius: "2px 2px 0 0", minWidth: 0, cursor: "pointer", transition: "opacity 0.2s",
              }} />
            );
          })}
        </div>
        <div style={{ display: "flex", justifyContent: "space-between", marginTop: 4 }}>
          <span style={{ color: "#2a3a4a", fontSize: 9, fontFamily: "'IBM Plex Mono', monospace" }}>0:00</span>
          <span style={{ color: "#2a3a4a", fontSize: 9, fontFamily: "'IBM Plex Mono', monospace" }}>12:00</span>
          <span style={{ color: "#2a3a4a", fontSize: 9, fontFamily: "'IBM Plex Mono', monospace" }}>23:00</span>
        </div>
      </div>

      <div style={{ background: "#0a1018", border: "1px solid #1a2332", borderRadius: 8, padding: 16 }}>
        <div style={{ color: "#3a5060", fontSize: 10, letterSpacing: "0.1em", fontFamily: "'IBM Plex Mono', monospace", marginBottom: 12 }}>REPUTATION BREAKDOWN</div>
        {repProviders.map((p) => {
          const catKey = (p as any).categoryName ?? (p as any).category ?? "";
          const color = CAT_COLORS[catKey] ?? "#00e5ff";
          return (
            <div key={p.id} style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 10 }}>
              <span style={{ fontSize: 16 }}>{CAT_ICONS[catKey] ?? "📡"}</span>
              <span style={{ color: "#8a9aaa", fontSize: 12, flex: 1, minWidth: 140 }}>{p.name}</span>
              <div style={{ flex: 2, height: 6, background: "#1a2332", borderRadius: 3, overflow: "hidden" }}>
                <div style={{ width: `${p.reputation}%`, height: "100%", background: color, borderRadius: 3 }} />
              </div>
              <span style={{ color, fontSize: 12, fontWeight: 700, fontFamily: "'IBM Plex Mono', monospace", minWidth: 40, textAlign: "right" }}>{p.reputation}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function Faucet() {
  const [wallet, setWallet] = useState("");
  const [status, setStatus] = useState<{ type: string; msg: string } | null>(null);
  const [balance] = useState<number | null>(null);
  const [copied, setCopied] = useState(false);

  const requestFaucet = () => {
    if (!wallet || !wallet.startsWith("0x")) { setStatus({ type: "error", msg: "Enter a valid 0x address" }); return; }
    navigator.clipboard.writeText(wallet);
    setStatus({ type: "loading", msg: "Address copied — opening Circle faucet..." });
    setTimeout(() => {
      window.open(`https://faucet.circle.com`, "_blank", "noopener,noreferrer");
      setStatus({ type: "success", msg: `Address copied to clipboard — paste it in the faucet to receive testnet USDC` });
    }, 800);
  };

  const copyConfig = () => {
    const config = `Network: Arc Testnet\nRPC: https://rpc.testnet.arc.network\nChain ID: 5042002\nCurrency: USDC\nExplorer: https://testnet.arcscan.app`;
    navigator.clipboard.writeText(config);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div style={{ maxWidth: 560, margin: "0 auto" }}>
      <div style={{ textAlign: "center", marginBottom: 24 }}>
        <div style={{ fontSize: 40, marginBottom: 8 }}>💧</div>
        <div style={{ color: "#e0e8f0", fontSize: 18, fontWeight: 700, marginBottom: 4 }}>Arc Testnet Faucet</div>
        <div style={{ color: "#4a6274", fontSize: 12 }}>Get testnet USDC to fund your agent's Gateway Wallet</div>
      </div>

      <div style={{ background: "#0a1018", border: "1px solid #1a2332", borderRadius: 8, padding: 20, marginBottom: 16 }}>
        <div style={{ color: "#3a5060", fontSize: 10, letterSpacing: "0.1em", fontFamily: "'IBM Plex Mono', monospace", marginBottom: 8 }}>WALLET ADDRESS</div>
        <div style={{ display: "flex", gap: 8 }}>
          <input
            value={wallet} onChange={(e) => setWallet(e.target.value)}
            placeholder="0x..."
            style={{
              flex: 1, background: "#060a0f", border: "1px solid #1a2332", borderRadius: 4,
              padding: "10px 12px", color: "#e0e8f0", fontFamily: "'IBM Plex Mono', monospace",
              fontSize: 13, outline: "none",
            }}
          />
          <button onClick={requestFaucet} style={{
            background: "linear-gradient(135deg, #00e5ff, #00b0ff)", color: "#000",
            border: "none", borderRadius: 4, padding: "10px 20px", cursor: "pointer",
            fontFamily: "'IBM Plex Mono', monospace", fontSize: 11, fontWeight: 700, whiteSpace: "nowrap",
          }}>
            DRIP 10 USDC
          </button>
        </div>
        {status && (
          <div style={{
            marginTop: 10, padding: "8px 12px", borderRadius: 4, fontSize: 12,
            fontFamily: "'IBM Plex Mono', monospace",
            background: status.type === "success" ? "#76ff0311" : status.type === "error" ? "#ff525211" : "#00e5ff11",
            color: status.type === "success" ? "#76ff03" : status.type === "error" ? "#ff5252" : "#00e5ff",
            border: `1px solid ${status.type === "success" ? "#76ff0322" : status.type === "error" ? "#ff525222" : "#00e5ff22"}`,
          }}>
            {status.type === "loading" && "⏳ "}{status.type === "success" && "✓ "}{status.type === "error" && "✗ "}
            {status.msg}
          </div>
        )}
        {balance !== null && (
          <div style={{ marginTop: 10, color: "#76ff03", fontSize: 12, fontFamily: "'IBM Plex Mono', monospace" }}>
            Balance: {balance} USDC (testnet)
          </div>
        )}
      </div>

      <div style={{ background: "#0a1018", border: "1px solid #1a2332", borderRadius: 8, padding: 20, marginBottom: 16 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
          <div style={{ color: "#3a5060", fontSize: 10, letterSpacing: "0.1em", fontFamily: "'IBM Plex Mono', monospace" }}>ARC TESTNET CONFIG</div>
          <button onClick={copyConfig} style={{
            background: "transparent", border: "1px solid #1a2332", borderRadius: 4,
            padding: "4px 10px", color: copied ? "#76ff03" : "#4a6274", cursor: "pointer",
            fontFamily: "'IBM Plex Mono', monospace", fontSize: 10,
          }}>
            {copied ? "✓ COPIED" : "COPY"}
          </button>
        </div>
        <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 11, lineHeight: 1.8 }}>
          {[
            { label: "Network", value: "Arc Testnet" },
            { label: "RPC", value: "https://rpc.testnet.arc.network" },
            { label: "Chain ID", value: "5042002" },
            { label: "Currency", value: "USDC" },
            { label: "Gas", value: "~$0.01/tx (160 Gwei base)" },
            { label: "Explorer", value: "testnet.arcscan.app" },
          ].map((r) => (
            <div key={r.label} style={{ display: "flex" }}>
              <span style={{ color: "#4a6274", minWidth: 100 }}>{r.label}</span>
              <span style={{ color: "#00e5ff" }}>{r.value}</span>
            </div>
          ))}
        </div>
      </div>

      <a href="https://faucet.circle.com" target="_blank" rel="noopener noreferrer" style={{
        display: "block", textAlign: "center", background: "#0a1018", border: "1px solid #1a2332",
        borderRadius: 8, padding: 14, color: "#00e5ff", textDecoration: "none",
        fontFamily: "'IBM Plex Mono', monospace", fontSize: 12, transition: "all 0.3s",
      }}>
        ↗ Official Circle Faucet (faucet.circle.com)
      </a>
    </div>
  );
}

// ── Main App ────────────────────────────────────────────────────
export default function SignalPayApp() {
  const [tab, setTab] = useState("agent");
  const [signals, setSignals] = useState<ReturnType<typeof generateSignal>[]>([]);
  const { data: totalProviders } = useRegistryStats();
  const { address, isConnected } = useAccount();
  const chainId = useChainId();


  useEffect(() => {
    let cancelled = false;
    const poll = async () => {
      try {
        const resp = await fetch("/feed");
        if (!cancelled && resp.ok) {
          const data = await resp.json();
          const norm = normalizeSignal(data.signal);
          if (norm) setSignals((prev) => [norm, ...prev].slice(0, 50));
        }
      } catch { /* backend not ready yet */ }
      if (!cancelled) setTimeout(poll, 3000);
    };
    poll();
    return () => { cancelled = true; };
  }, []);

  const tabs = [
    { id: "agent", label: "Agent Console", icon: "⚡" },
    { id: "explore", label: "Signal Explorer", icon: "🔍" },
    { id: "provider", label: "Provider Stats", icon: "📊" },
    { id: "faucet", label: "Faucet", icon: "💧" },
  ];

  return (
    <div style={{
      minHeight: "100vh", background: "#080c12", color: "#c8d6e5",
      fontFamily: "'IBM Plex Mono', 'JetBrains Mono', monospace",
    }}>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600;700&display=swap');
        @keyframes fadeSlideIn { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: translateY(0); } }
        @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }
        @keyframes blink { 0%, 100% { opacity: 1; } 50% { opacity: 0; } }
        @keyframes glow { 0%, 100% { text-shadow: 0 0 8px #00e5ff44; } 50% { text-shadow: 0 0 16px #00e5ff88; } }
        * { box-sizing: border-box; scrollbar-width: thin; scrollbar-color: #1a2332 transparent; }
        ::-webkit-scrollbar { width: 4px; } ::-webkit-scrollbar-track { background: transparent; } ::-webkit-scrollbar-thumb { background: #1a2332; border-radius: 2px; }
        input::placeholder { color: #2a3a4a; }
      `}</style>

      <div style={{
        borderBottom: "1px solid #1a2332", padding: "12px 20px",
        display: "flex", justifyContent: "space-between", alignItems: "center",
        background: "linear-gradient(180deg, #0a1018 0%, #080c12 100%)",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <img src="/favicon.svg" width={32} height={32} alt="SignalPay" style={{ borderRadius: 8 }} />
          <div>
            <div style={{ fontSize: 14, fontWeight: 700, color: "#e0e8f0", letterSpacing: "0.04em", animation: "glow 3s infinite" }}>
              SIGNAL<span style={{ color: "#00e5ff" }}>PAY</span>
            </div>
            <div style={{ fontSize: 9, color: "#3a5060", letterSpacing: "0.08em" }}>AI AGENT ALPHA MARKETPLACE</div>
          </div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <div style={{ width: 6, height: 6, borderRadius: "50%", background: "#76ff03", boxShadow: "0 0 6px #76ff03" }} />
            <span style={{ color: "#76ff03", fontSize: 10, fontFamily: "'IBM Plex Mono', monospace" }}>ARC TESTNET</span>
          </div>
          <div style={{ color: "#3a5060", fontSize: 10, fontFamily: "'IBM Plex Mono', monospace" }}>
            x402 + NANOPAYMENTS
          </div>
          <ConnectButton
            accountStatus="address"
            chainStatus="icon"
            showBalance={false}
          />
        </div>
      </div>

      <TabBar active={tab} onSelect={setTab} tabs={tabs} />

      <div style={{ padding: 20, maxWidth: 1100, margin: "0 auto" }}>
        {tab === "agent" && <AgentConsole signals={signals} onSignal={(s) => setSignals((prev) => [s, ...prev].slice(0, 50))} />}
        {tab === "explore" && <SignalExplorer />}
        {tab === "provider" && <ProviderDashboard />}
        {tab === "faucet" && <Faucet />}
      </div>

      <div style={{
        borderTop: "1px solid #0d1520", padding: "10px 20px",
        display: "flex", justifyContent: "space-between",
        color: "#2a3a4a", fontSize: 9, fontFamily: "'IBM Plex Mono', monospace",
      }}>
        <span>SIGNALPAY v0.1.0 — NANO PAYMENTS ON ARC HACKATHON 2026</span>
        <span>SETTLEMENT: ARC L1 (5042002) — USDC NATIVE GAS — ZERO-GAS NANOPAYMENTS</span>
      </div>
    </div>
  );
}
