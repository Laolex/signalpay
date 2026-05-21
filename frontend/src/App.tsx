import { useState, useEffect, useRef, useCallback } from "react";
import { API_BASE } from "./api";
import SignalPayDiagram from "./SignalPayDiagram";
import { ConnectButton } from "@rainbow-me/rainbowkit";
import { useAccount, useChainId, useWriteContract, useWaitForTransactionReceipt } from "wagmi";
import { useRegistryStats, useAllProviders } from "./useRegistry";
import { SIGNAL_REGISTRY_ADDRESS } from "./wagmi";

// ── Design tokens ────────────────────────────────────────────────
const C = {
  bg:      "#0a0a0a",
  panel:   "#111111",
  row:     "#161616",
  border:  "#222222",
  border2: "#2a2a2a",
  text:    "#e8e8e8",
  dim:     "#666666",
  muted:   "#444444",
  orange:  "#ff8c00",
  green:   "#00cc88",
  red:     "#ff4455",
  blue:    "#4a9eff",
  yellow:  "#ffcc00",
  cyan:    "#00ccdd",
  purple:  "#aa88ff",
};

const MONO = "'IBM Plex Mono', 'Courier New', monospace";

// ── Provider catalog ────────────────────────────────────────────
const PROVIDERS_STATIC = [
  { id: 0, key: "PRICE_ORACLE",  name: "Price Oracle",           price: 0.001, endpoint: "/signals/price/{token}" },
  { id: 1, key: "SENTIMENT",     name: "Sentiment Engine",       price: 0.003, endpoint: "/signals/sentiment/{token}" },
  { id: 2, key: "TRADE_SIGNAL",  name: "Trade Signal",           price: 0.010, endpoint: "/signals/trade-signal/{token}" },
  { id: 3, key: "WHALE_ALERT",   name: "Whale Alert",            price: 0.002, endpoint: "/signals/whale-alert" },
  { id: 4, key: "WALLET_SCORE",  name: "Wallet Score",           price: 0.005, endpoint: "/signals/wallet-score" },
  { id: 5, key: "YIELD_INTEL",   name: "Yield Intelligence",     price: 0.003, endpoint: "/signals/yield-intel" },
];

const CAT_COLOR: Record<string, string> = {
  PRICE_ORACLE:     C.green,
  SENTIMENT:        C.purple,
  TRADE_SIGNAL:     C.orange,
  WHALE_ALERT:      C.cyan,
  WALLET_SCORE:     C.yellow,
  YIELD_INTEL:      C.blue,
  COMPOSITE_SIGNAL: "#e040fb",
};

const CAT_TAG: Record<string, string> = {
  PRICE_ORACLE:     "PX",
  SENTIMENT:        "SNT",
  TRADE_SIGNAL:     "TRD",
  WHALE_ALERT:      "WHL",
  WALLET_SCORE:     "WSC",
  YIELD_INTEL:      "YLD",
  COMPOSITE_SIGNAL: "CMP",
};

const ACTION_COLOR: Record<string, string> = {
  INIT:       C.dim,
  DISCOVER:   C.cyan,
  SELECT:     C.blue,
  PAY:        C.yellow,
  RECEIVE:    C.green,
  REPUTATION: C.dim,
  ANALYZE:    C.cyan,
  EXECUTE:    C.orange,
  SUMMARY:    C.green,
  ERROR:      C.red,
};

function timeAgo(ms: number) {
  const s = Math.floor(ms / 1000);
  if (s < 60) return `${s}s`;
  return `${Math.floor(s / 60)}m`;
}

function fmt(n: number, dec = 2) { return n.toLocaleString("en", { minimumFractionDigits: dec, maximumFractionDigits: dec }); }

function _inferToken(cat: string, d: any): string {
  switch (cat) {
    case "WHALE_ALERT":
      return d.chain ? d.chain.split("-")[0].toUpperCase() : "WALLET";
    case "WALLET_SCORE":
      return "SCORE";
    case "YIELD_INTEL": {
      const proto = d.best_protocol || (d.opportunities?.[0]?.protocol) || "";
      const chain = d.best_chain || (d.opportunities?.[0]?.chain) || "";
      if (proto) return proto.toUpperCase().slice(0, 6);
      if (chain) return chain.toUpperCase().slice(0, 6);
      return "YIELD";
    }
    case "COMPOSITE_SIGNAL":
      return d.token || "SYNTH";
    default:
      return "—";
  }
}

// ── normalizeSignal ──────────────────────────────────────────────
function normalizeSignal(raw: any) {
  if (!raw) return null;
  const cat = (raw.category || "").toUpperCase().replace(/-/g, "_");
  const d = raw.data || {};
  return {
    category: cat,
    timestamp: (raw.timestamp || 0) * 1000,
    token: d.token || raw.token || _inferToken(cat, d),
    confidence: raw.confidence || 0,
    data: {
      ...d,
      price_usd:              d.price_usd ?? 0,
      change_24h:             d.change_24h ?? d.change_24h_pct ?? 0,
      amount_usd:             d.amount_usd ?? d.amount_usdc ?? 0,
      direction:              d.direction ?? "transfer",
      chain:                  d.chain ?? "arc-testnet",
      wallet:                 d.wallet ?? d.from_wallet ?? "0x???",
      usdc_balance:           d.usdc_balance ?? null,
      tx_count:               d.tx_count ?? null,
      composite_score:        d.composite_score ?? null,
      label:                  d.label ?? d.sentiment_label ?? "neutral",
      sentiment_score:        d.sentiment_score ?? 0,
      community_votes_up_pct: d.community_votes_up_pct ?? d.mentions_1h ?? null,
      fear_greed_index:       d.fear_greed_index ?? null,
      fear_greed_label:       d.fear_greed_label ?? null,
      action:                 d.action ?? null,
      rationale:              d.rationale ?? null,
      total_transfers_in_window: d.total_transfers_in_window ?? null,
      block:                  d.block ?? null,
      best_protocol:          d.best_protocol ?? null,
      best_chain:             d.best_chain ?? null,
      best_apy:               d.best_apy ?? null,
      avg_top5_apy:           d.avg_top5_apy ?? null,
      opportunities:          d.opportunities ?? null,
    },
  };
}
type Sig = NonNullable<ReturnType<typeof normalizeSignal>>;

// ── Shared primitives ────────────────────────────────────────────

function Panel({ children, style }: { children: React.ReactNode; style?: React.CSSProperties }) {
  return (
    <div style={{ background: C.panel, border: `1px solid ${C.border}`, ...style }}>
      {children}
    </div>
  );
}

function Label({ children, style }: { children: React.ReactNode; style?: React.CSSProperties }) {
  return (
    <span style={{
      fontSize: 9, letterSpacing: "0.12em", color: C.dim,
      fontFamily: MONO, textTransform: "uppercase" as const, ...style,
    }}>
      {children}
    </span>
  );
}

function StatCell({ label, value, color = C.text, sub }: { label: string; value: string | number; color?: string; sub?: string }) {
  return (
    <div style={{ padding: "10px 14px", borderRight: `1px solid ${C.border}` }}>
      <Label>{label}</Label>
      <div style={{ fontSize: 18, fontWeight: 700, fontFamily: MONO, color, marginTop: 2, lineHeight: 1 }}>{value}</div>
      {sub && <div style={{ fontSize: 9, color: C.dim, fontFamily: MONO, marginTop: 2 }}>{sub}</div>}
    </div>
  );
}

function Tab({ id, label, active, onClick }: { id: string; label: string; active: boolean; onClick: () => void }) {
  return (
    <button onClick={onClick} style={{
      background: "none", border: "none",
      borderBottom: active ? `2px solid ${C.orange}` : "2px solid transparent",
      color: active ? C.orange : C.dim, padding: "10px 16px", cursor: "pointer",
      fontFamily: MONO, fontSize: 10, letterSpacing: "0.1em", textTransform: "uppercase" as const,
      fontWeight: active ? 700 : 400, transition: "color 0.15s",
    }}>
      {label}
    </button>
  );
}

// ── Governance bar ───────────────────────────────────────────────
function GovernanceBar() {
  const [policy, setPolicy] = useState<any>(null);

  useEffect(() => {
    const load = () => fetch(`${API_BASE}/governance/policy`).then(r => r.json()).then(setPolicy).catch(() => {});
    load();
    const id = setInterval(load, 5000);
    return () => clearInterval(id);
  }, []);

  const p = policy?.policy;
  const today = policy?.today;
  const pct = today?.pct_used ?? 0;
  const barColor = pct > 80 ? C.red : pct > 50 ? C.yellow : C.green;

  return (
    <div style={{
      display: "flex", alignItems: "stretch", borderBottom: `1px solid ${C.border}`,
      background: C.bg, fontSize: 10, fontFamily: MONO,
    }}>
      <div style={{ padding: "6px 14px", borderRight: `1px solid ${C.border}`, display: "flex", alignItems: "center", gap: 8 }}>
        <Label>GOVERNANCE</Label>
      </div>
      {p && [
        { k: "MAX/CALL",   v: `$${p.max_per_call_usdc?.toFixed(3)}`,          c: C.text },
        { k: "DAILY CAP",  v: `$${p.daily_budget_usdc?.toFixed(2)}`,           c: C.text },
        { k: "HUMAN GATE", v: `>$${p.require_human_above_usdc?.toFixed(3)}`,   c: C.yellow },
        { k: "WHITELIST",  v: p.whitelist?.[0] === "*" ? "OPEN" : `${p.whitelist?.length} addr`, c: C.green },
      ].map(({ k, v, c }) => (
        <div key={k} style={{ padding: "6px 14px", borderRight: `1px solid ${C.border}`, display: "flex", gap: 6, alignItems: "center" }}>
          <Label>{k}</Label>
          <span style={{ color: c, fontSize: 10 }}>{v}</span>
        </div>
      ))}
      {today && (
        <div style={{ padding: "6px 14px", borderRight: `1px solid ${C.border}`, display: "flex", alignItems: "center", gap: 8, minWidth: 240 }}>
          <Label>TODAY</Label>
          <div style={{ flex: 1, height: 4, background: C.border2, position: "relative" }}>
            <div style={{ position: "absolute", left: 0, top: 0, height: "100%", width: `${Math.min(100, pct)}%`, background: barColor, transition: "width 0.5s" }} />
          </div>
          <span style={{ color: barColor, fontSize: 10, whiteSpace: "nowrap" as const }}>
            ${today.spent_usdc?.toFixed(4)} / ${today.budget_usdc?.toFixed(2)}
          </span>
        </div>
      )}
      <div style={{ flex: 1 }} />
    </div>
  );
}

// ── Signal row (table format) ────────────────────────────────────
function SignalRow({ sig, index }: { sig: Sig; index: number }) {
  const color = CAT_COLOR[sig.category] ?? C.text;
  const tag = CAT_TAG[sig.category] ?? "SIG";
  const d = sig.data;
  const conf = Math.round(sig.confidence * 100);

  let mainVal = "";
  let subVal = "";
  let dirColor = C.text;

  if (sig.category === "PRICE_ORACLE") {
    const chg = Number(d.change_24h);
    mainVal = `$${fmt(d.price_usd)}`;
    subVal = `${chg >= 0 ? "+" : ""}${fmt(chg, 2)}% 24h`;
    dirColor = chg >= 0 ? C.green : C.red;
  } else if (sig.category === "WHALE_ALERT") {
    mainVal = d.amount_usd > 0 ? `$${fmt(d.amount_usd, 4)} USDC` : "QUIET";
    subVal = d.total_transfers_in_window ? `${d.total_transfers_in_window} txs` : "arc-testnet";
    dirColor = C.cyan;
  } else if (sig.category === "SENTIMENT") {
    const fng = d.fear_greed_index;
    const label = (d.label ?? "neutral") as string;
    mainVal = fng != null ? `F&G ${fng}` : label.toUpperCase();
    subVal = d.fear_greed_label ?? label;
    dirColor = label === "bullish" ? C.green : label === "bearish" ? C.red : C.yellow;
  } else if (sig.category === "WALLET_SCORE") {
    mainVal = d.usdc_balance != null ? `$${fmt(Number(d.usdc_balance), 2)}` : "—";
    subVal = d.tx_count != null ? `${d.tx_count} txs` : "arc";
    dirColor = C.yellow;
  } else if (sig.category === "TRADE_SIGNAL") {
    const act = (d.action ?? "HOLD") as string;
    mainVal = act;
    subVal = d.composite_score != null ? `score ${Number(d.composite_score) >= 0 ? "+" : ""}${Number(d.composite_score).toFixed(2)}` : "";
    dirColor = act === "BUY" || act === "ACCUMULATE" ? C.green : act === "SELL" || act === "REDUCE" ? C.red : C.yellow;
  } else if (sig.category === "YIELD_INTEL") {
    mainVal = d.best_apy != null ? `${Number(d.best_apy).toFixed(2)}% APY` : "—";
    subVal = d.best_protocol ? `${d.best_protocol} · ${d.best_chain}` : "defillama";
    dirColor = C.blue;
  } else if (sig.category === "COMPOSITE_SIGNAL") {
    const act = (d.action ?? "HOLD") as string;
    mainVal = act.split("—")[0].trim().split(" ").slice(0, 2).join(" ");
    subVal = `${d.signal_count ?? "?"} signals · $${(d.spend_usdc ?? 0).toFixed(3)} cost`;
    dirColor = act.startsWith("ACCUMULATE") || act.startsWith("BUY") ? C.green : act.startsWith("SELL") || act.startsWith("REDUCE") ? C.red : C.yellow;
  }

  return (
    <div style={{
      display: "grid",
      gridTemplateColumns: "36px 60px 70px 1fr 120px 48px 40px",
      alignItems: "center",
      borderBottom: `1px solid ${C.border}`,
      background: index % 2 === 0 ? C.panel : C.row,
      fontSize: 11, fontFamily: MONO,
      padding: "5px 0",
    }}>
      <div style={{ padding: "0 8px", color: C.muted, fontSize: 9 }}>{timeAgo(Date.now() - sig.timestamp)}</div>
      <div style={{ padding: "0 4px" }}>
        <span style={{
          background: color + "22", color, fontSize: 9, fontWeight: 700,
          padding: "2px 5px", letterSpacing: "0.06em",
        }}>{tag}</span>
      </div>
      <div style={{ color: C.dim, fontSize: 10 }}>{sig.token}</div>
      <div style={{ color: dirColor, fontWeight: 600 }}>{mainVal}</div>
      <div style={{ color: C.dim, fontSize: 10 }}>{subVal}</div>
      <div style={{ color: C.dim, fontSize: 9 }}>
        <span style={{ color: conf >= 80 ? C.green : conf >= 60 ? C.yellow : C.dim }}>{conf}%</span>
      </div>
      <div style={{ padding: "0 8px" }}>
        <div style={{ width: "100%", height: 3, background: C.border2 }}>
          <div style={{ width: `${conf}%`, height: "100%", background: color }} />
        </div>
      </div>
    </div>
  );
}

// ── USDC ABI (transfer + balanceOf) ─────────────────────────────
const USDC_ADDRESS = "0x3600000000000000000000000000000000000000" as const;
const USDC_ABI = [
  { name: "transfer", type: "function", inputs: [{ name: "to", type: "address" }, { name: "value", type: "uint256" }], outputs: [{ name: "", type: "bool" }], stateMutability: "nonpayable" },
] as const;

// ── Agent Wallet ─────────────────────────────────────────────────
const COMPLIANCE_COLORS: Record<string, string> = {
  low: "#34d399", medium: "#f59e0b", high: "#f97316", blocked: "#ef4444", unknown: "#64748b",
};

function AgentWallet() {
  const [info, setInfo] = useState<{ address: string | null; balance_usdc: number; funded: boolean } | null>(null);
  const [compliance, setCompliance] = useState<{ risk_tier: string; risk_score: number; flags: string[]; sanctions_hit: boolean } | null>(null);
  const [amount, setAmount] = useState("0.01");
  const [copied, setCopied] = useState(false);
  const { isConnected, address } = useAccount();

  const { writeContract, data: txHash, isPending, error: writeError } = useWriteContract();
  const { isLoading: isConfirming, isSuccess: isConfirmed } = useWaitForTransactionReceipt({ hash: txHash });

  const loadInfo = useCallback(() => {
    const userParam = address ? `?user=${address}` : "";
    fetch(`${API_BASE}/agent/wallet${userParam}`).then(r => r.json()).then(setInfo).catch(() => {});
  }, [address]);

  const loadCompliance = useCallback(() => {
    if (!address) return;
    fetch(`${API_BASE}/compliance/check/${address}`).then(r => r.json()).then(setCompliance).catch(() => {});
  }, [address]);

  useEffect(() => {
    loadCompliance();
  }, [loadCompliance]);

  useEffect(() => {
    loadInfo();
    const id = setInterval(loadInfo, 5000);
    return () => clearInterval(id);
  }, [loadInfo]);

  useEffect(() => { if (isConfirmed) loadInfo(); }, [isConfirmed, loadInfo]);

  const deposit = () => {
    if (!info?.address || !amount || isNaN(parseFloat(amount))) return;
    const raw = BigInt(Math.round(parseFloat(amount) * 1_000_000));
    writeContract({
      address: USDC_ADDRESS,
      abi: USDC_ABI,
      functionName: "transfer",
      args: [info.address as `0x${string}`, raw],
      chainId: 5042002,
    });
  };

  const copyAddr = () => {
    if (!info?.address) return;
    navigator.clipboard.writeText(info.address);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const txStatus = isConfirmed ? "FUNDED" : isConfirming ? "CONFIRMING..." : isPending ? "CONFIRM IN WALLET..." : writeError ? "TX FAILED" : null;
  const txColor  = isConfirmed ? C.green : isConfirming ? C.cyan : isPending ? C.yellow : C.red;

  return (
    <Panel style={{ borderLeft: "none", borderRight: "none", borderTop: "none" }}>
      <div style={{
        padding: "6px 12px", borderBottom: `1px solid ${C.border}`,
        display: "flex", alignItems: "center", justifyContent: "space-between",
      }}>
        <Label>AGENT WALLET</Label>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          {compliance && (
            <span style={{
              fontSize: 8, fontFamily: MONO, fontWeight: 700, letterSpacing: "0.1em",
              padding: "2px 6px", borderRadius: 2,
              background: COMPLIANCE_COLORS[compliance.risk_tier] + "22",
              color: COMPLIANCE_COLORS[compliance.risk_tier],
              border: `1px solid ${COMPLIANCE_COLORS[compliance.risk_tier]}44`,
            }}>
              {compliance.risk_tier.toUpperCase()} RISK
            </span>
          )}
          <span style={{ fontSize: 9, fontFamily: MONO, color: info?.funded ? C.green : C.yellow }}>
            {info ? (info.funded ? "FUNDED" : "UNFUNDED") : "..."}
          </span>
        </div>
      </div>

      <div style={{ padding: "8px 12px" }}>
        {/* Balance */}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 6 }}>
          <Label>USDC</Label>
          <span style={{ fontSize: 15, fontWeight: 700, fontFamily: MONO, color: info?.funded ? C.green : C.muted }}>
            ${(info?.balance_usdc ?? 0).toFixed(6)}
          </span>
        </div>

        {/* Address */}
        {info?.address ? (
          <div
            onClick={copyAddr}
            title={info.address}
            style={{
              display: "flex", justifyContent: "space-between", alignItems: "center",
              padding: "3px 7px", background: C.bg, border: `1px solid ${C.border2}`,
              cursor: "pointer", marginBottom: 7,
            }}
          >
            <span style={{ fontSize: 9, color: C.dim, fontFamily: MONO }}>
              {info.address.slice(0, 12)}…{info.address.slice(-6)}
            </span>
            <span style={{ fontSize: 9, color: copied ? C.green : C.muted, fontFamily: MONO }}>
              {copied ? "COPIED" : "COPY"}
            </span>
          </div>
        ) : (
          <div style={{ fontSize: 9, color: C.muted, fontFamily: MONO, marginBottom: 7 }}>
            NO KEY CONFIGURED
          </div>
        )}

        {/* Deposit */}
        {isConnected && info?.address ? (
          <div style={{ display: "flex", gap: 5 }}>
            <input
              value={amount}
              onChange={e => setAmount(e.target.value)}
              style={{
                flex: 1, background: C.bg, border: `1px solid ${C.border2}`,
                padding: "4px 7px", color: C.text, fontFamily: MONO, fontSize: 10, outline: "none",
              }}
              placeholder="0.01"
            />
            <span style={{ fontSize: 9, color: C.dim, fontFamily: MONO, alignSelf: "center" }}>USDC</span>
            <button
              onClick={deposit}
              disabled={isPending || isConfirming}
              style={{
                background: isPending || isConfirming ? C.border : C.orange,
                color: isPending || isConfirming ? C.dim : "#000",
                border: "none", padding: "4px 10px", cursor: isPending || isConfirming ? "default" : "pointer",
                fontFamily: MONO, fontSize: 9, fontWeight: 700, letterSpacing: "0.06em",
              }}
            >
              FUND
            </button>
          </div>
        ) : (
          <div style={{ fontSize: 9, color: C.muted, fontFamily: MONO }}>
            {info?.address ? "CONNECT WALLET TO FUND" : "SET BUYER_PRIVATE_KEY"}
          </div>
        )}

        {txStatus && (
          <div style={{ fontSize: 9, color: txColor, fontFamily: MONO, marginTop: 5, display: "flex", gap: 8 }}>
            <span>{txStatus}</span>
            {isConfirmed && txHash && (
              <a href={`https://testnet.arcscan.app/tx/${txHash}`} target="_blank" rel="noopener noreferrer"
                style={{ color: C.cyan, textDecoration: "none" }}>
                VIEW TX →
              </a>
            )}
          </div>
        )}
      </div>
    </Panel>
  );
}

// ── Agent Console ────────────────────────────────────────────────
function AgentConsole({ signals, onSignal }: { signals: Sig[]; onSignal: (s: Sig) => void }) {
  const [logs, setLogs] = useState<{ action: string; msg: string; ts: number; signal?: any; txHash?: string }[]>([]);
  const [running, setRunning] = useState(false);
  const [budget, setBudget] = useState(0.1);
  const [spent, setSpent] = useState(0);
  const [signalCount, setSignalCount] = useState(0);
  const scrollRef = useRef<HTMLDivElement>(null);
  const { address } = useAccount();
  const addLog = useCallback((action: string, msg: string, extra?: { signal?: any; txHash?: string }) => {
    setLogs(prev => [...prev, { action, msg, ts: Date.now(), ...extra }]);
  }, []);

  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [logs]);

  const runAgent = useCallback(async () => {
    if (running) return;
    setRunning(true); setLogs([]); setBudget(0.1); setSpent(0); setSignalCount(0);
    try {
      const resp = await fetch(`${API_BASE}/agent/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ wallet_address: address ?? "" }),
      });
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
            const ev = JSON.parse(line.slice(6));
            if (ev.action === "DONE") { setRunning(false); return; }
            addLog(ev.action, ev.msg || "", {
              signal: ev.signal || undefined,
              txHash: ev.tx_hash || undefined,
            });
            if (ev.budget !== undefined) setBudget(ev.budget);
            if (ev.spent !== undefined) setSpent(ev.spent);
            if (ev.signals !== undefined) setSignalCount(ev.signals);
            if (ev.signal) { const n = normalizeSignal(ev.signal); if (n) onSignal(n); }
          } catch {}
        }
      }
    } catch (err) { addLog("ERROR", `Connection failed: ${err}`); }
    setRunning(false);
  }, [running, addLog, onSignal]);

  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 320px", gap: 1, height: "calc(100vh - 148px)", background: C.border }}>

      {/* Left — terminal log */}
      <div style={{ background: C.bg, display: "flex", flexDirection: "column" }}>
        {/* Stat bar */}
        <div style={{ display: "flex", borderBottom: `1px solid ${C.border}` }}>
          <StatCell label="BUDGET"  value={`$${budget.toFixed(6)}`}  color={C.cyan}  sub="on-chain" />
          <StatCell label="SPENT"   value={`$${spent.toFixed(6)}`}   color={spent > 0 ? C.orange : C.dim} sub="this session" />
          <StatCell label="SIGNALS" value={signalCount}               color={C.green} sub="purchased" />
          <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "flex-end", padding: "0 14px", gap: 12 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <div style={{
                width: 7, height: 7, borderRadius: "50%",
                background: running ? C.green : C.muted,
                boxShadow: running ? `0 0 6px ${C.green}` : "none",
              }} />
              <Label style={{ color: running ? C.green : C.muted }}>
                {running ? "RUNNING" : "IDLE"}
              </Label>
            </div>
            <button onClick={runAgent} disabled={running} style={{
              background: running ? C.border : C.orange,
              color: running ? C.dim : "#000",
              border: "none", padding: "6px 14px", cursor: running ? "default" : "pointer",
              fontFamily: MONO, fontSize: 10, fontWeight: 700, letterSpacing: "0.08em",
              transition: "background 0.15s",
            }}>
              {running ? "RUNNING..." : "EXECUTE SESSION"}
            </button>
          </div>
        </div>

        {/* Log */}
        <div ref={scrollRef} style={{
          flex: 1, overflowY: "auto", background: C.bg, fontSize: 10, fontFamily: MONO,
          padding: "8px 0",
        }}>
          {logs.length === 0 && (
            <div style={{ color: C.muted, padding: "40px 16px", textAlign: "center" }}>
              AWAITING SESSION — PRESS EXECUTE SESSION TO START
            </div>
          )}
          {logs.map((l, i) => {
            const isExecute = l.action === "EXECUTE";
            const isPay     = l.action === "PAY";
            const isRep     = l.action === "REPUTATION";
            const isReceive = l.action === "RECEIVE";

            // PAY sub-step coloring
            let msgColor = isExecute ? C.orange : C.text;
            if (isPay) {
              if (l.msg.startsWith("← HTTP 402"))        msgColor = C.red;
              else if (l.msg.includes("EIP-3009"))        msgColor = C.yellow;
              else if (l.msg.startsWith("→ Resubmitting")) msgColor = C.cyan;
              else                                         msgColor = C.dim;
            }

            const tradeData = (isReceive && l.signal?.category === "trade_signal") ? l.signal.data : null;

            return (
              <div key={i} style={{
                borderLeft: isExecute ? `2px solid ${C.orange}` : "2px solid transparent",
                background: isExecute ? `${C.orange}0a` : "transparent",
              }}>
                <div style={{
                  display: "grid", gridTemplateColumns: "64px 90px 1fr",
                  padding: "2px 12px", gap: 8,
                }}>
                  <span style={{ color: C.muted }}>
                    {new Date(l.ts).toLocaleTimeString("en", { hour12: false })}
                  </span>
                  <span style={{
                    color: ACTION_COLOR[l.action] ?? C.dim,
                    fontWeight: isExecute ? 700 : 400,
                  }}>
                    [{l.action}]
                  </span>
                  <span style={{ color: msgColor }}>{l.msg}</span>
                </div>

                {tradeData && (
                  <div style={{
                    paddingLeft: 182, paddingRight: 12, paddingBottom: 4,
                    fontSize: 9, fontFamily: MONO, color: C.dim,
                  }}>
                    <span style={{ color: C.muted }}>momentum </span>
                    <span style={{ color: (tradeData.momentum ?? 0) >= 0 ? C.green : C.red }}>
                      {(tradeData.momentum ?? 0) >= 0 ? "+" : ""}{Number(tradeData.momentum ?? 0).toFixed(2)}
                    </span>
                    {" · "}
                    <span style={{ color: C.muted }}>F&G </span>
                    <span style={{ color: (tradeData.fear_greed_index ?? 50) < 30 ? C.green : (tradeData.fear_greed_index ?? 50) > 70 ? C.red : C.yellow }}>
                      {tradeData.fear_greed_index} ({tradeData.fear_greed_label})
                    </span>
                    {" · "}
                    <span style={{ color: C.muted }}>community </span>
                    <span style={{ color: C.cyan }}>{tradeData.community_votes_up_pct}% bullish</span>
                    {" · "}
                    <span style={{ color: C.muted }}>composite </span>
                    <span style={{ color: (tradeData.composite_score ?? 0) >= 0 ? C.green : C.red }}>
                      {(tradeData.composite_score ?? 0) >= 0 ? "+" : ""}{Number(tradeData.composite_score ?? 0).toFixed(3)}
                    </span>
                    {" → "}
                    <span style={{ color: C.orange, fontWeight: 700 }}>{tradeData.action}</span>
                  </div>
                )}

                {isRep && l.txHash && (
                  <div style={{ paddingLeft: 182, paddingRight: 12, paddingBottom: 4, fontSize: 9, fontFamily: MONO }}>
                    <a
                      href={`https://testnet.arcscan.app/tx/${l.txHash}`}
                      target="_blank"
                      rel="noopener noreferrer"
                      style={{ color: C.cyan, textDecoration: "none" }}
                    >
                      Arc tx {l.txHash.slice(0, 10)}…{l.txHash.slice(-6)} →
                    </a>
                  </div>
                )}
              </div>
            );
          })}
          {running && (
            <div style={{ padding: "2px 12px", color: C.orange, fontSize: 10 }}>▊</div>
          )}
        </div>
      </div>

      {/* Right — signals + governance */}
      <div style={{ background: C.bg, display: "flex", flexDirection: "column" }}>
        <Panel style={{ borderLeft: "none", borderRight: "none", borderTop: "none" }}>
          {/* Signal table header */}
          <div style={{
            display: "grid",
            gridTemplateColumns: "36px 60px 70px 1fr 120px 48px 40px",
            padding: "6px 0",
            borderBottom: `1px solid ${C.border2}`,
          }}>
            {["AGE", "TYPE", "TOKEN", "VALUE", "DETAIL", "CONF", ""].map(h => (
              <Label key={h} style={{ padding: "0 4px" }}>{h}</Label>
            ))}
          </div>
        </Panel>

        <div style={{ flex: 1, overflowY: "auto" }}>
          {signals.length === 0 && (
            <div style={{ color: C.muted, textAlign: "center", padding: "32px 12px", fontSize: 10, fontFamily: MONO }}>
              NO SIGNALS — START SESSION TO POPULATE
            </div>
          )}
          {signals.slice(0, 30).map((s, i) => <SignalRow key={i} sig={s} index={i} />)}
        </div>

        {/* Agent wallet + governance */}
        <AgentWallet />
        <GovernanceMini />
      </div>
    </div>
  );
}

function GovernanceMini() {
  const [policy, setPolicy] = useState<any>(null);
  useEffect(() => {
    const load = () => fetch(`${API_BASE}/governance/policy`).then(r => r.json()).then(setPolicy).catch(() => {});
    load();
    const id = setInterval(load, 5000);
    return () => clearInterval(id);
  }, []);

  const today = policy?.today;
  const pct = today?.pct_used ?? 0;
  const barColor = pct > 80 ? C.red : pct > 50 ? C.yellow : C.green;

  return (
    <Panel style={{ borderLeft: "none", borderRight: "none", borderBottom: "none" }}>
      <div style={{ padding: "8px 12px", borderBottom: `1px solid ${C.border}` }}>
        <Label>GOVERNANCE — DAILY BUDGET</Label>
      </div>
      <div style={{ padding: "8px 12px" }}>
        <div style={{ height: 4, background: C.border2, marginBottom: 6 }}>
          <div style={{ width: `${Math.min(100, pct)}%`, height: "100%", background: barColor, transition: "width 0.5s" }} />
        </div>
        <div style={{ display: "flex", justifyContent: "space-between", fontSize: 10, fontFamily: MONO }}>
          <span style={{ color: barColor }}>${today?.spent_usdc?.toFixed(4) ?? "0.0000"} spent</span>
          <span style={{ color: C.dim }}>${today?.remaining_usdc?.toFixed(4) ?? "1.0000"} left</span>
        </div>
      </div>
    </Panel>
  );
}

// ── Signal Explorer (table view) ─────────────────────────────────
function SignalExplorer() {
  const [selected, setSelected] = useState<number | null>(null);
  const [providers, setProviders] = useState(PROVIDERS_STATIC);
  const [stats, setStats] = useState<{ total_calls: number; total_revenue_usdc: number } | null>(null);

  useEffect(() => {
    fetch(`${API_BASE}/discovery/providers`)
      .then(r => r.json())
      .then(data => {
        const raw = data.providers || [];
        setProviders(raw.map((p: any, i: number) => ({
          id: i,
          key: (p.id || "").toUpperCase(),
          name: p.name || p.id,
          price: p.price_usdc || 0,
          endpoint: p.endpoint || "",
        })));
      }).catch(() => {});
    fetch(`${API_BASE}/stats`).then(r => r.json()).then(setStats).catch(() => {});
  }, []);

  return (
    <div style={{ fontFamily: MONO }}>
      {/* Stats bar */}
      <Panel style={{ display: "flex", marginBottom: 1 }}>
        <StatCell label="PROVIDERS"  value={providers.length}                                  color={C.cyan} />
        <StatCell label="TOTAL CALLS" value={(stats?.total_calls ?? 0).toLocaleString()}       color={C.green} sub="session" />
        <StatCell label="REVENUE"    value={`$${(stats?.total_revenue_usdc ?? 0).toFixed(6)}`} color={C.orange} sub="USDC" />
        <StatCell label="SETTLEMENT" value="ARC L1"                                             color={C.dim} sub="chain 5042002" />
        <div style={{ flex: 1 }} />
      </Panel>

      {/* Table header */}
      <Panel style={{ marginBottom: 1 }}>
        <div style={{
          display: "grid",
          gridTemplateColumns: "48px 1fr 120px 100px 100px 80px",
          padding: "6px 12px",
          borderBottom: `1px solid ${C.border}`,
        }}>
          {["TYPE", "PROVIDER", "ENDPOINT", "PRICE/CALL", "PROTOCOL", "STATUS"].map(h => (
            <Label key={h}>{h}</Label>
          ))}
        </div>

        {providers.map((p, i) => {
          const color = CAT_COLOR[p.key] ?? C.text;
          const tag = CAT_TAG[p.key] ?? "SIG";
          const isSelected = selected === p.id;
          return (
            <div key={p.id}>
              <div
                onClick={() => setSelected(isSelected ? null : p.id)}
                style={{
                  display: "grid",
                  gridTemplateColumns: "48px 1fr 120px 100px 100px 80px",
                  padding: "8px 12px",
                  borderBottom: `1px solid ${C.border}`,
                  cursor: "pointer",
                  background: isSelected ? `${color}0d` : i % 2 === 0 ? C.panel : C.row,
                  transition: "background 0.1s",
                }}
              >
                <span style={{ background: color + "22", color, fontSize: 9, fontWeight: 700, padding: "2px 5px", letterSpacing: "0.06em", alignSelf: "center" }}>
                  {tag}
                </span>
                <span style={{ color: C.text, fontSize: 11 }}>{p.name}</span>
                <span style={{ color: C.dim, fontSize: 10 }}>{p.endpoint.replace("{token}", ":token")}</span>
                <span style={{ color: C.orange, fontWeight: 700 }}>${p.price.toFixed(3)}</span>
                <span style={{ color: C.dim, fontSize: 10 }}>x402 / EIP-3009</span>
                <span style={{ display: "flex", alignItems: "center", gap: 5 }}>
                  <div style={{ width: 5, height: 5, borderRadius: "50%", background: C.green }} />
                  <span style={{ color: C.green, fontSize: 9 }}>LIVE</span>
                </span>
              </div>

              {isSelected && (
                <div style={{
                  padding: "14px 16px",
                  borderBottom: `1px solid ${C.border}`,
                  background: C.bg,
                  display: "grid",
                  gridTemplateColumns: "1fr 1fr",
                  gap: 16,
                  fontSize: 10,
                }}>
                  <div>
                    <Label style={{ display: "block", marginBottom: 6 }}>PAYMENT FLOW</Label>
                    {[
                      "GET " + p.endpoint.replace("{token}", "BTC"),
                      "← HTTP 402  { x402: { accepts: [...] } }",
                      "Sign EIP-3009 TransferWithAuthorization",
                      `→ Retry with X-Payment: { authorization, signature }`,
                      "200 OK — signal data released",
                    ].map((step, idx) => (
                      <div key={idx} style={{ color: idx === 4 ? C.green : C.dim, marginBottom: 3 }}>
                        <span style={{ color: C.muted, marginRight: 8 }}>{idx + 1}.</span>{step}
                      </div>
                    ))}
                  </div>
                  <div>
                    <Label style={{ display: "block", marginBottom: 6 }}>ON-CHAIN IDENTITY</Label>
                    <div style={{ color: C.dim, lineHeight: 1.8 }}>
                      <div>Registry: ERC-8004 ReputationRegistry</div>
                      <div>Network: Arc Testnet (5042002)</div>
                      <div>Settlement: Circle GatewayWalletBatched</div>
                      <div style={{ color: C.orange, marginTop: 6 }}>Price: ${p.price.toFixed(3)} USDC/call</div>
                    </div>
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </Panel>

      {/* x402 Protocol note */}
      <Panel style={{ padding: "10px 16px" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 16, fontSize: 10, color: C.dim }}>
          <Label style={{ color: C.orange }}>x402 PROTOCOL</Label>
          <span>HTTP 402 Payment Required → EIP-3009 signature → Circle Nanopayments settlement → Arc L1 batching</span>
          <span style={{ marginLeft: "auto", color: C.dim }}>Zero gas per payment · Sub-$0.01 per call · USDC native</span>
        </div>
      </Panel>
    </div>
  );
}

// ── Provider Stats ───────────────────────────────────────────────
// ── Accuracy colour helper ───────────────────────────────────────
function accColor(v: number | undefined) {
  if (v === undefined) return C.muted;
  if (v >= 0.70) return C.green;
  if (v >= 0.55) return C.yellow;
  if (v >= 0.40) return C.orange;
  return C.red;
}

function sharpeColor(s: number | undefined) {
  if (s === undefined) return C.muted;
  if (s >= 0.5) return C.green;
  if (s >= 0) return C.yellow;
  return C.red;
}

function ProviderDashboard() {
  const [stats, setStats] = useState<{ total_revenue_usdc: number; total_calls: number; recent: any[] } | null>(null);
  const [repMetrics, setRepMetrics] = useState<Record<string, any>>({});
  const [economics, setEconomics]   = useState<any>(null);
  const [sessions, setSessions]     = useState<any[]>([]);
  const [openPositions, setOpenPositions]   = useState<any[]>([]);
  const [closedPositions, setClosedPositions] = useState<any[]>([]);
  const [perfSummary, setPerfSummary]       = useState<any>(null);
  const { data: totalOnChain } = useRegistryStats();
  const { providers: chainProviders } = useAllProviders(Number(totalOnChain ?? 0));

  const providers = chainProviders.length > 0
    ? chainProviders.map(p => ({ ...p, reputation: 0 }))
    : PROVIDERS_STATIC.map(p => ({ ...p, reputation: 0, categoryName: p.key, priceUSDC: p.price }));

  const loadAll = useCallback(() => {
    fetch(`${API_BASE}/stats`).then(r => r.json()).then(setStats).catch(() => {});
    fetch(`${API_BASE}/reputation`).then(r => r.json()).then((d: any) => {
      const m: Record<string, any> = {};
      for (const p of (d.providers ?? [])) m[p.provider_id] = p;
      setRepMetrics(m);
    }).catch(() => {});
    fetch(`${API_BASE}/economics`).then(r => r.json()).then(setEconomics).catch(() => {});
    fetch(`${API_BASE}/economics/sessions?limit=10`).then(r => r.json()).then((d: any) => setSessions(d.sessions ?? [])).catch(() => {});
    fetch(`${API_BASE}/positions`).then(r => r.json()).then((d: any) => setOpenPositions(d.positions ?? [])).catch(() => {});
    fetch(`${API_BASE}/positions/history?limit=15`).then(r => r.json()).then((d: any) => setClosedPositions(d.positions ?? [])).catch(() => {});
    fetch(`${API_BASE}/positions/performance`).then(r => r.json()).then(setPerfSummary).catch(() => {});
  }, []);

  useEffect(() => {
    loadAll();
    const t = setInterval(loadAll, 120_000);  // refresh every 2 min
    return () => clearInterval(t);
  }, [loadAll]);

  const totalEarnings = stats?.total_revenue_usdc ?? 0;
  const totalCalls = stats?.total_calls ?? 0;
  const recent = stats?.recent ?? [];

  // Aggregate accuracy stats across all providers with data
  const metricsArr = Object.values(repMetrics);
  const trackedProviders = metricsArr.filter((m: any) => m.total_signals > 0);
  const resolvedTotal = trackedProviders.reduce((s: number, m: any) => s + (m.resolved_count ?? 0), 0);
  const avgHitRate = trackedProviders.length
    ? trackedProviders.reduce((s: number, m: any) => s + (m.hit_rate ?? 0.5), 0) / trackedProviders.length
    : null;

  // Map provider_id → rep metrics key (API uses snake_case provider ids)
  const repKey: Record<string, string> = {
    PRICE_ORACLE: "price_oracle",
    SENTIMENT:    "sentiment",
    TRADE_SIGNAL: "trade_signal",
    WHALE_ALERT:  "whale_alert",
    WALLET_SCORE: "wallet_score",
    YIELD_INTEL:  "yield_intel",
  };

  const eLife   = economics?.lifetime ?? {};
  const eByProv = economics?.by_provider ?? [];
  const eDaily  = economics?.daily_spend ?? [];
  const totalLifetimeSpend = eLife.total_spend ?? 0;
  const totalSessions      = eLife.session_count ?? 0;
  const avgSessionCost     = totalSessions > 0 ? (totalLifetimeSpend / totalSessions) : 0;
  const busiestProvider    = eByProv[0];

  return (
    <div style={{ fontFamily: MONO }}>
      <Panel style={{ display: "flex", marginBottom: 1 }}>
        <StatCell label="TOTAL REVENUE"  value={`$${totalEarnings.toFixed(6)}`} color={C.green}  sub="USDC session" />
        <StatCell label="VALIDATED CALLS" value={totalCalls.toLocaleString()}    color={C.cyan}  sub="x402 settled" />
        <StatCell label="LIFETIME SPEND" value={`$${totalLifetimeSpend.toFixed(4)}`} color={C.orange} sub={`${totalSessions} sessions`} />
        <StatCell label="AVG HIT RATE"
          value={avgHitRate !== null ? `${(avgHitRate * 100).toFixed(1)}%` : "—"}
          color={avgHitRate !== null ? accColor(avgHitRate) : C.muted}
          sub={resolvedTotal > 0 ? `${resolvedTotal} resolved` : "accumulating"} />
        <div style={{ flex: 1 }} />
      </Panel>

      {/* Economics overview */}
      <Panel style={{ marginBottom: 1 }}>
        <div style={{
          padding: "8px 12px", borderBottom: `1px solid ${C.border}`,
          display: "flex", alignItems: "center", justifyContent: "space-between",
        }}>
          <Label>ECONOMIC MEMORY — CROSS-SESSION SPEND ANALYTICS</Label>
          <span style={{ color: C.muted, fontSize: 9 }}>PERSISTED · SQLITE</span>
        </div>

        {/* Summary stats row */}
        <div style={{ display: "flex", borderBottom: `1px solid ${C.border}` }}>
          {[
            { label: "SESSIONS",       value: totalSessions.toString(),               color: C.cyan },
            { label: "LIFETIME CALLS", value: (eLife.total_calls ?? 0).toString(),    color: C.blue },
            { label: "LIFETIME SPEND", value: `$${totalLifetimeSpend.toFixed(6)}`,    color: C.orange },
            { label: "AVG SESSION",    value: `$${avgSessionCost.toFixed(6)}`,         color: C.yellow },
            { label: "TOP PROVIDER",   value: busiestProvider?.category?.toUpperCase().replace("_"," ") ?? "—", color: C.green },
          ].map(s => (
            <div key={s.label} style={{ flex: 1, padding: "10px 12px", borderRight: `1px solid ${C.border}` }}>
              <div style={{ fontSize: 8, color: C.muted, marginBottom: 4 }}>{s.label}</div>
              <div style={{ fontSize: 13, color: s.color, fontWeight: 700 }}>{s.value}</div>
            </div>
          ))}
        </div>

        {/* Per-provider spend breakdown */}
        {eByProv.length > 0 && (
          <>
            <div style={{
              display: "grid", gridTemplateColumns: "48px 1fr 80px 80px 80px 60px",
              padding: "5px 12px", borderBottom: `1px solid ${C.border2}`,
            }}>
              {["TYPE", "PROVIDER", "CALLS", "TOTAL $", "AVG $", "SHARE"].map(h => <Label key={h}>{h}</Label>)}
            </div>
            {eByProv.map((p: any, i: number) => {
              const catKey = p.provider_id.toUpperCase();
              const color  = CAT_COLOR[catKey] ?? C.text;
              const tag    = CAT_TAG[catKey] ?? "SIG";
              return (
                <div key={p.provider_id} style={{
                  display: "grid", gridTemplateColumns: "48px 1fr 80px 80px 80px 60px",
                  padding: "6px 12px", borderBottom: `1px solid ${C.border}`,
                  background: i % 2 === 0 ? C.panel : C.row, fontSize: 10,
                }}>
                  <span style={{ background: color + "22", color, fontSize: 9, fontWeight: 700, padding: "2px 5px" }}>{tag}</span>
                  <span style={{ color: C.text }}>{p.category.replace(/_/g, " ")}</span>
                  <span style={{ color: C.cyan }}>{p.calls}</span>
                  <span style={{ color: C.orange }}>${p.total_spend.toFixed(4)}</span>
                  <span style={{ color: C.dim }}>${p.avg_cost.toFixed(4)}</span>
                  <span style={{ color: C.muted }}>{p.spend_share}%</span>
                </div>
              );
            })}
          </>
        )}
        {eByProv.length === 0 && (
          <div style={{ padding: "20px 12px", color: C.muted, fontSize: 10 }}>
            No spend recorded yet — run the agent to populate economic memory
          </div>
        )}
      </Panel>

      {/* Session history */}
      <Panel style={{ marginBottom: 1 }}>
        <div style={{ padding: "8px 12px", borderBottom: `1px solid ${C.border}` }}>
          <Label>SESSION HISTORY</Label>
        </div>
        <div style={{
          display: "grid", gridTemplateColumns: "140px 1fr 70px 70px 50px 1fr",
          padding: "5px 12px", borderBottom: `1px solid ${C.border2}`,
        }}>
          {["TIMESTAMP", "WALLET", "BUDGET", "SPENT", "SIGS", "ACTION"].map(h => <Label key={h}>{h}</Label>)}
        </div>
        {sessions.length === 0 && (
          <div style={{ padding: "20px 12px", color: C.muted, fontSize: 10 }}>
            No sessions recorded yet
          </div>
        )}
        {sessions.map((s: any, i: number) => {
          const action = s.action_taken ?? "—";
          const actionShort = action.length > 40 ? action.slice(0, 40) + "…" : action;
          const actionKey = (action.match(/^(BUY|ACCUMULATE|HOLD|REDUCE|SELL|WATCH)/)?.[0] ?? "").toUpperCase();
          const ACTION_COLORS: Record<string, string> = { BUY: C.green, ACCUMULATE: C.green, HOLD: C.muted, REDUCE: C.yellow, SELL: C.red, WATCH: C.dim };
          const actionColor = ACTION_COLORS[actionKey] ?? C.dim;
          const wallet = s.user_address ? `${s.user_address.slice(0,8)}…${s.user_address.slice(-4)}` : "anonymous";
          return (
            <div key={s.session_id} style={{
              display: "grid", gridTemplateColumns: "140px 1fr 70px 70px 50px 1fr",
              padding: "6px 12px", borderBottom: `1px solid ${C.border}`,
              background: i % 2 === 0 ? C.panel : C.row, fontSize: 10,
            }}>
              <span style={{ color: C.muted }}>
                {s.started_at ? new Date(s.started_at * 1000).toLocaleString("en", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false }) : "—"}
              </span>
              <span style={{ color: C.dim }}>{wallet}</span>
              <span style={{ color: C.cyan }}>${s.budget_usdc?.toFixed(4)}</span>
              <span style={{ color: s.spent_usdc > 0 ? C.orange : C.muted }}>${s.spent_usdc?.toFixed(4)}</span>
              <span style={{ color: C.blue }}>{s.signals_count}</span>
              <span style={{ color: actionColor, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={action}>{actionShort}</span>
            </div>
          );
        })}
      </Panel>

      {/* Accuracy metrics panel */}
      <Panel style={{ marginBottom: 1 }}>
        <div style={{
          padding: "8px 12px",
          borderBottom: `1px solid ${C.border}`,
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
        }}>
          <Label>PREDICTION ACCURACY — MULTI-DIMENSIONAL REPUTATION</Label>
          <span style={{ color: C.muted, fontSize: 9 }}>15-MIN RESOLUTION · PYTH ORACLE</span>
        </div>
        <div style={{
          display: "grid", gridTemplateColumns: "48px 1fr 70px 70px 70px 70px 70px",
          padding: "5px 12px", borderBottom: `1px solid ${C.border2}`,
        }}>
          {["TYPE", "PROVIDER", "SIGNALS", "RESOLVED", "HIT RATE", "SHARPE", "ACCURACY"].map(h =>
            <Label key={h}>{h}</Label>
          )}
        </div>
        {PROVIDERS_STATIC.map((p, i) => {
          const key = p.key;
          const color = CAT_COLOR[key] ?? C.text;
          const tag = CAT_TAG[key] ?? "SIG";
          const rk = repKey[key];
          const m = rk ? repMetrics[rk] : undefined;
          const hasData = m && m.total_signals > 0;
          return (
            <div key={p.id} style={{
              display: "grid", gridTemplateColumns: "48px 1fr 70px 70px 70px 70px 70px",
              padding: "7px 12px", borderBottom: `1px solid ${C.border}`,
              background: i % 2 === 0 ? C.panel : C.row, fontSize: 10,
            }}>
              <span style={{ background: color + "22", color, fontSize: 9, fontWeight: 700, padding: "2px 5px" }}>{tag}</span>
              <span style={{ color: C.text }}>{p.name}</span>
              <span style={{ color: hasData ? C.cyan : C.muted }}>
                {hasData ? m.total_signals : "—"}
              </span>
              <span style={{ color: hasData && m.resolved_count > 0 ? C.dim : C.muted }}>
                {hasData && m.resolved_count > 0 ? m.resolved_count : (m?.pending_count > 0 ? `${m.pending_count}⏳` : "—")}
              </span>
              <span style={{ color: hasData && m.resolved_count > 0 ? accColor(m.hit_rate) : C.muted, fontWeight: m?.resolved_count >= 5 ? 700 : 400 }}>
                {hasData && m.resolved_count > 0 ? `${(m.hit_rate * 100).toFixed(1)}%` : "—"}
              </span>
              <span style={{ color: hasData && m.resolved_count > 0 ? sharpeColor(m.sharpe_ratio) : C.muted }}>
                {hasData && m.resolved_count > 0 ? (m.sharpe_ratio >= 0 ? `+${m.sharpe_ratio.toFixed(2)}` : m.sharpe_ratio.toFixed(2)) : "—"}
              </span>
              <span style={{ color: hasData ? accColor(m.composite_accuracy) : C.muted, fontWeight: 700 }}>
                {hasData ? `${(m.composite_accuracy * 100).toFixed(0)}` : "—"}
                {hasData ? <span style={{ color: C.muted, fontWeight: 400 }}>/100</span> : null}
              </span>
            </div>
          );
        })}
        <div style={{ padding: "6px 12px", fontSize: 9, color: C.muted }}>
          ACCURACY = 40% hit rate + 30% Sharpe contribution + 30% avg confidence · feeds into agent ProviderScore.alpha_quality
        </div>
      </Panel>

      {/* Trade execution — open positions */}
      <Panel style={{ marginBottom: 1 }}>
        <div style={{
          padding: "8px 12px", borderBottom: `1px solid ${C.border}`,
          display: "flex", alignItems: "center", justifyContent: "space-between",
        }}>
          <Label>OPEN POSITIONS — SIMULATED PAPER TRADING · $10/TRADE</Label>
          <div style={{ display: "flex", gap: 16, fontSize: 9, color: C.muted }}>
            {perfSummary && perfSummary.total_trades > 0 && <>
              <span>WIN RATE <span style={{ color: accColor(perfSummary.win_rate), fontWeight: 700 }}>{(perfSummary.win_rate * 100).toFixed(0)}%</span></span>
              <span>TOTAL P&amp;L <span style={{ color: (perfSummary.total_pnl_usdc ?? 0) >= 0 ? C.green : C.red, fontWeight: 700 }}>{(perfSummary.total_pnl_usdc ?? 0) >= 0 ? "+" : ""}${(perfSummary.total_pnl_usdc ?? 0).toFixed(4)}</span></span>
              <span>SHARPE <span style={{ color: sharpeColor(perfSummary.trade_sharpe), fontWeight: 700 }}>{(perfSummary.trade_sharpe ?? 0) >= 0 ? "+" : ""}{(perfSummary.trade_sharpe ?? 0).toFixed(2)}</span></span>
            </>}
          </div>
        </div>
        {openPositions.length > 0 && (
          <>
            <div style={{
              display: "grid", gridTemplateColumns: "60px 1fr 110px 110px 80px 80px 60px",
              padding: "5px 12px", borderBottom: `1px solid ${C.border2}`,
            }}>
              {["TOKEN", "DIRECTION", "ENTRY $", "CURRENT $", "P&L $", "P&L %", "HELD"].map(h => <Label key={h}>{h}</Label>)}
            </div>
            {openPositions.map((p: any, i: number) => {
              const pnlColor = (p.pnl_pct ?? 0) >= 0 ? C.green : C.red;
              const held = p.duration_s ?? 0;
              const heldStr = held < 60 ? `${held}s` : held < 3600 ? `${Math.floor(held/60)}m` : `${(held/3600).toFixed(1)}h`;
              return (
                <div key={p.id} style={{
                  display: "grid", gridTemplateColumns: "60px 1fr 110px 110px 80px 80px 60px",
                  padding: "7px 12px", borderBottom: `1px solid ${C.border}`,
                  background: i % 2 === 0 ? C.panel : C.row, fontSize: 10,
                }}>
                  <span style={{ color: C.cyan, fontWeight: 700 }}>{p.token}</span>
                  <span style={{ color: p.direction === "long" ? C.green : C.red }}>
                    {p.direction === "long" ? "▲ LONG" : "▼ SHORT"} · {p.action_taken}
                  </span>
                  <span style={{ color: C.dim }}>${(p.entry_price ?? 0).toLocaleString("en", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span>
                  <span style={{ color: C.text }}>${(p.exit_price ?? p.entry_price ?? 0).toLocaleString("en", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span>
                  <span style={{ color: pnlColor, fontWeight: 700 }}>{(p.pnl_usdc ?? 0) >= 0 ? "+" : ""}${(p.pnl_usdc ?? 0).toFixed(4)}</span>
                  <span style={{ color: pnlColor }}>{(p.pnl_pct ?? 0) >= 0 ? "+" : ""}{(p.pnl_pct ?? 0).toFixed(2)}%</span>
                  <span style={{ color: C.muted }}>{heldStr}</span>
                </div>
              );
            })}
          </>
        )}
        {openPositions.length === 0 && (
          <div style={{ padding: "20px 12px", color: C.muted, fontSize: 10 }}>
            No open positions — agent opens a position when it fires BUY or ACCUMULATE
          </div>
        )}
      </Panel>

      {/* Closed positions / P&L history */}
      {closedPositions.length > 0 && (
        <Panel style={{ marginBottom: 1 }}>
          <div style={{ padding: "8px 12px", borderBottom: `1px solid ${C.border}` }}>
            <Label>CLOSED POSITIONS — REALIZED P&amp;L</Label>
          </div>
          <div style={{
            display: "grid", gridTemplateColumns: "60px 1fr 100px 100px 80px 70px 80px",
            padding: "5px 12px", borderBottom: `1px solid ${C.border2}`,
          }}>
            {["TOKEN", "ACTION", "ENTRY $", "EXIT $", "P&L $", "P&L %", "HELD"].map(h => <Label key={h}>{h}</Label>)}
          </div>
          {closedPositions.map((p: any, i: number) => {
            const win = (p.pnl_usdc ?? 0) > 0;
            const pnlColor = win ? C.green : C.red;
            const held = p.duration_s ?? 0;
            const heldStr = held < 60 ? `${held}s` : held < 3600 ? `${Math.floor(held/60)}m` : `${(held/3600).toFixed(1)}h`;
            return (
              <div key={p.id} style={{
                display: "grid", gridTemplateColumns: "60px 1fr 100px 100px 80px 70px 80px",
                padding: "6px 12px", borderBottom: `1px solid ${C.border}`,
                background: i % 2 === 0 ? C.panel : C.row, fontSize: 10,
              }}>
                <span style={{ color: C.cyan, fontWeight: 700 }}>{p.token}</span>
                <span style={{ color: win ? C.green : C.red, fontSize: 9, fontWeight: 700 }}>
                  {win ? "✓ WIN" : "✗ LOSS"} · {p.action_taken}
                </span>
                <span style={{ color: C.dim }}>${(p.entry_price ?? 0).toLocaleString("en", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span>
                <span style={{ color: C.text }}>${(p.exit_price ?? 0).toLocaleString("en", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span>
                <span style={{ color: pnlColor, fontWeight: 700 }}>{(p.pnl_usdc ?? 0) >= 0 ? "+" : ""}${(p.pnl_usdc ?? 0).toFixed(4)}</span>
                <span style={{ color: pnlColor }}>{(p.pnl_pct ?? 0) >= 0 ? "+" : ""}{(p.pnl_pct ?? 0).toFixed(2)}%</span>
                <span style={{ color: C.muted }}>{heldStr}</span>
              </div>
            );
          })}
        </Panel>
      )}

      {/* Recent payments */}
      <Panel style={{ marginBottom: 1 }}>
        <div style={{ padding: "8px 12px", borderBottom: `1px solid ${C.border}` }}>
          <Label>RECENT VALIDATED PAYMENTS</Label>
        </div>
        <div style={{
          display: "grid",
          gridTemplateColumns: "1fr 120px 80px",
          padding: "5px 12px",
          borderBottom: `1px solid ${C.border2}`,
        }}>
          {["PAYER", "AMOUNT (USDC)", "TIMESTAMP"].map(h => <Label key={h}>{h}</Label>)}
        </div>
        {recent.length === 0 && (
          <div style={{ padding: "24px 12px", color: C.muted, fontSize: 10 }}>
            No payments yet this session — run the agent to populate
          </div>
        )}
        {recent.map((r, i) => (
          <div key={i} style={{
            display: "grid",
            gridTemplateColumns: "1fr 120px 80px",
            padding: "6px 12px",
            borderBottom: `1px solid ${C.border}`,
            background: i % 2 === 0 ? C.panel : C.row,
            fontSize: 10,
          }}>
            <span style={{ color: C.dim }}>{r.payer?.slice(0, 10)}…{r.payer?.slice(-6)}</span>
            <span style={{ color: C.green, fontWeight: 700 }}>${(r.amount / 1_000_000).toFixed(6)}</span>
            <span style={{ color: C.muted }}>{new Date(r.ts * 1000).toLocaleTimeString("en", { hour12: false })}</span>
          </div>
        ))}
      </Panel>

      {/* Provider table */}
      <Panel>
        <div style={{ padding: "8px 12px", borderBottom: `1px solid ${C.border}` }}>
          <Label>PROVIDER REGISTRY</Label>
        </div>
        <div style={{
          display: "grid", gridTemplateColumns: "48px 1fr 100px 70px 70px",
          padding: "5px 12px", borderBottom: `1px solid ${C.border2}`,
        }}>
          {["TYPE", "NAME", "PRICE", "REP", "ACC"].map(h => <Label key={h}>{h}</Label>)}
        </div>
        {providers.map((p: any, i: number) => {
          const key = p.categoryName ?? p.key ?? "";
          const color = CAT_COLOR[key] ?? C.text;
          const tag = CAT_TAG[key] ?? "SIG";
          const rep = p.reputation ?? 0;
          const repColor = rep >= 90 ? C.green : rep >= 70 ? C.yellow : rep > 0 ? C.red : C.muted;
          const rk = repKey[key];
          const m = rk ? repMetrics[rk] : undefined;
          return (
            <div key={p.id} style={{
              display: "grid", gridTemplateColumns: "48px 1fr 100px 70px 70px",
              padding: "7px 12px", borderBottom: `1px solid ${C.border}`,
              background: i % 2 === 0 ? C.panel : C.row, fontSize: 11,
            }}>
              <span style={{ background: color + "22", color, fontSize: 9, fontWeight: 700, padding: "2px 5px" }}>{tag}</span>
              <span style={{ color: C.text }}>{p.name}</span>
              <span style={{ color: C.orange }}>${(p.priceUSDC ?? p.price ?? 0).toFixed(3)}/call</span>
              <span style={{ color: repColor }}>{rep > 0 ? `${rep}/100` : "—"}</span>
              <span style={{ color: m ? accColor(m.composite_accuracy) : C.muted, fontWeight: 700 }}>
                {m ? `${(m.composite_accuracy * 100).toFixed(0)}` : "—"}
              </span>
            </div>
          );
        })}
      </Panel>
    </div>
  );
}

// ── Routing constants (GAP 5 + 6) ────────────────────────────────
const PROVIDER_IDS = ["price_oracle", "sentiment", "trade_signal", "whale_alert", "wallet_score", "yield_intel"];
const PROVIDER_LABELS: Record<string, string> = {
  price_oracle: "Price Oracle", sentiment: "Sentiment Engine",
  trade_signal: "Trade Signal", whale_alert: "Whale Alert",
  wallet_score: "Wallet Score", yield_intel: "Yield Intelligence",
};
const BASE_PRICES: Record<string, number> = {
  price_oracle: 0.001, sentiment: 0.003, trade_signal: 0.010,
  whale_alert: 0.002, wallet_score: 0.005, yield_intel: 0.003,
};

const CHAIN_INFO: Record<number, { name: string; symbol: string; color: string; bridge: number }> = {
  5042002: { name: "Arc Testnet",  symbol: "ARC",   color: C.cyan,   bridge: 0.000 },
  8453:    { name: "Base",         symbol: "BASE",  color: C.blue,   bridge: 0.002 },
  42161:   { name: "Arbitrum One", symbol: "ARB",   color: C.green,  bridge: 0.003 },
  10:      { name: "Optimism",     symbol: "OP",    color: C.red,    bridge: 0.003 },
  137:     { name: "Polygon",      symbol: "MATIC", color: C.purple, bridge: 0.002 },
  1:       { name: "Ethereum",     symbol: "ETH",   color: "#8888ff", bridge: 0.008 },
};
const ARC_CHAIN_ID = 5042002;

function timeLeft(expiresAt: number): string {
  const s = Math.max(0, expiresAt - Math.floor(Date.now() / 1000));
  if (s >= 60) return `${Math.floor(s / 60)}m ${s % 60}s`;
  return `${s}s`;
}

function AuctionDashboard() {
  const [bids, setBids]             = useState<any[]>([]);
  const [history, setHistory]       = useState<any[]>([]);
  const [chainProviders, setChainProviders] = useState<Record<string, any>>({});
  const [chains, setChains]         = useState<any[]>([]);
  const [stakes, setStakes]         = useState<any[]>([]);
  const [slashHistory, setSlashHistory] = useState<any[]>([]);
  const [form, setForm]             = useState({ provider_id: "trade_signal", bid_premium_pct: 20, duration_s: 300 });
  const [chainForm, setChainForm]   = useState({ provider_id: "trade_signal", chain_id: ARC_CHAIN_ID });
  const [stakeForm, setStakeForm]   = useState({ provider_id: "trade_signal", amount_usdc: 10 });
  const [slashForm, setSlashForm]   = useState({ provider_id: "trade_signal", reason: "", slash_amount: 5 });
  const [status, setStatus]         = useState<{ type: "ok" | "err" | "loading"; msg: string } | null>(null);
  const [chainStatus, setChainStatus] = useState<{ type: "ok" | "err" | "loading"; msg: string } | null>(null);
  const [stakeStatus, setStakeStatus] = useState<{ type: "ok" | "err" | "loading"; msg: string } | null>(null);
  const [tick, setTick]             = useState(0);
  const [compositeEarnings, setCompositeEarnings] = useState<any>(null);
  const [latestComposite, setLatestComposite]     = useState<any>(null);

  const loadData = useCallback(() => {
    fetch(`${API_BASE}/auction/bids`).then(r => r.json()).then((d: any) => setBids(d.bids ?? [])).catch(() => {});
    fetch(`${API_BASE}/auction/history?limit=15`).then(r => r.json()).then((d: any) => setHistory(d.history ?? [])).catch(() => {});
    fetch(`${API_BASE}/chains/providers`).then(r => r.json()).then((d: any) => setChainProviders(d.providers ?? {})).catch(() => {});
    fetch(`${API_BASE}/chains`).then(r => r.json()).then((d: any) => setChains(d.chains ?? [])).catch(() => {});
    fetch(`${API_BASE}/stake/providers`).then(r => r.json()).then((d: any) => { setStakes(d.stakes ?? []); setSlashHistory(d.slash_history ?? []); }).catch(() => {});
    fetch(`${API_BASE}/signals/composite/earnings`).then(r => r.json()).then(setCompositeEarnings).catch(() => {});
  }, []);

  useEffect(() => {
    loadData();
    const poll = setInterval(loadData, 10_000);
    const counter = setInterval(() => setTick(t => t + 1), 1000);
    return () => { clearInterval(poll); clearInterval(counter); };
  }, [loadData]);

  const submitBid = async () => {
    setStatus({ type: "loading", msg: "Submitting bid…" });
    try {
      const resp = await fetch(`${API_BASE}/auction/bid`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(form),
      });
      const data = await resp.json();
      if (!resp.ok) { setStatus({ type: "err", msg: data.error ?? "Failed" }); return; }
      setStatus({ type: "ok", msg: `Bid placed — ID ${data.bid_id} | +${(data.score_impact * 100).toFixed(1)}% routing score` });
      loadData();
    } catch (e) {
      setStatus({ type: "err", msg: String(e) });
    }
  };

  const submitChainRegister = async () => {
    setChainStatus({ type: "loading", msg: "Registering…" });
    try {
      const resp = await fetch(`${API_BASE}/chains/register`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(chainForm),
      });
      const data = await resp.json();
      if (!resp.ok) { setChainStatus({ type: "err", msg: data.error ?? "Failed" }); return; }
      const penalty = data.penalty_pct ?? 0;
      setChainStatus({ type: "ok", msg: `Registered on ${data.chain_name} — ${penalty > 0 ? `-${penalty}% routing penalty` : "native, no penalty"}` });
      loadData();
    } catch (e) {
      setChainStatus({ type: "err", msg: String(e) });
    }
  };

  const submitStakeDeposit = async () => {
    setStakeStatus({ type: "loading", msg: "Depositing stake…" });
    try {
      const resp = await fetch(`${API_BASE}/stake/deposit`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(stakeForm),
      });
      const data = await resp.json();
      if (!resp.ok) { setStakeStatus({ type: "err", msg: data.error ?? "Failed" }); return; }
      setStakeStatus({ type: "ok", msg: `Staked $${data.amount_usdc.toFixed(2)} → +${(data.stake_boost * 100).toFixed(1)}pts boost` });
      loadData();
    } catch (e) {
      setStakeStatus({ type: "err", msg: String(e) });
    }
  };

  const submitSlash = async () => {
    setStakeStatus({ type: "loading", msg: "Slashing provider…" });
    try {
      const resp = await fetch(`${API_BASE}/stake/slash`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(slashForm),
      });
      const data = await resp.json();
      if (!resp.ok) { setStakeStatus({ type: "err", msg: data.error ?? "Failed" }); return; }
      setStakeStatus({ type: "ok", msg: `Slashed — ${data.slash_count} total events | penalty: −${(data.slash_penalty * 100).toFixed(1)}pts` });
      loadData();
    } catch (e) {
      setStakeStatus({ type: "err", msg: String(e) });
    }
  };

  const activeBids   = bids.filter((b: any) => b.seconds_remaining > 0);
  const topBidder    = activeBids[0];
  const avgPremium   = activeBids.length
    ? activeBids.reduce((s: number, b: any) => s + b.bid_premium_pct, 0) / activeBids.length
    : 0;
  const totalHistory = history.length;

  // Build a quick map of provider_id → active bid for the provider table
  const bidByProvider: Record<string, any> = {};
  for (const b of activeBids) bidByProvider[b.provider_id] = b;

  return (
    <div style={{ fontFamily: MONO }}>
      {/* Header stats */}
      <Panel style={{ display: "flex", marginBottom: 1 }}>
        <StatCell label="ACTIVE BIDS"  value={activeBids.length}                              color={C.cyan} />
        <StatCell label="TOP BIDDER"   value={topBidder ? PROVIDER_LABELS[topBidder.provider_id] ?? topBidder.provider_id : "—"} color={C.orange} sub={topBidder ? `+${topBidder.bid_premium_pct}%` : "no bids"} />
        <StatCell label="AVG PREMIUM"  value={activeBids.length ? `+${avgPremium.toFixed(1)}%` : "—"} color={C.yellow} />
        <StatCell label="TOTAL PLACED" value={totalHistory}                                    color={C.dim} sub="all time" />
        <div style={{ flex: 1 }} />
      </Panel>

      {/* Provider × bid table */}
      <Panel style={{ marginBottom: 1 }}>
        <div style={{
          padding: "8px 12px", borderBottom: `1px solid ${C.border}`,
          display: "flex", alignItems: "center", justifyContent: "space-between",
        }}>
          <Label>ROUTING AUCTION — LIVE BID STATUS</Label>
          <span style={{ color: C.muted, fontSize: 9 }}>SCORE IMPACT = bid_premium × 15% · MAX +15pts</span>
        </div>
        <div style={{
          display: "grid", gridTemplateColumns: "44px 1fr 64px 68px 68px 64px 60px 64px",
          padding: "5px 12px", borderBottom: `1px solid ${C.border2}`,
        }}>
          {["TYPE", "PROVIDER", "BASE $", "PREM%", "DYN $", "BOOST", "CHAIN", "TTL"].map(h => <Label key={h}>{h}</Label>)}
        </div>
        {PROVIDER_IDS.map((pid, i) => {
          const catKey   = pid.toUpperCase();
          const color    = CAT_COLOR[catKey] ?? C.text;
          const tag      = CAT_TAG[catKey]   ?? "SIG";
          const base     = BASE_PRICES[pid] ?? 0.001;
          const bid      = bidByProvider[pid];
          const cpData   = chainProviders[pid];
          const chainId  = cpData?.chain_id ?? ARC_CHAIN_ID;
          const chainMeta = CHAIN_INFO[chainId] ?? CHAIN_INFO[ARC_CHAIN_ID];
          const isNative = chainId === ARC_CHAIN_ID;
          return (
            <div key={pid} style={{
              display: "grid", gridTemplateColumns: "44px 1fr 64px 68px 68px 64px 60px 64px",
              padding: "7px 12px", borderBottom: `1px solid ${C.border}`,
              background: bid ? `${C.orange}0a` : i % 2 === 0 ? C.panel : C.row,
              fontSize: 10,
            }}>
              <span style={{ background: color + "22", color, fontSize: 9, fontWeight: 700, padding: "2px 5px" }}>{tag}</span>
              <span style={{ color: C.text }}>{PROVIDER_LABELS[pid]}</span>
              <span style={{ color: C.dim }}>${base.toFixed(3)}</span>
              {bid ? (
                <>
                  <span style={{ color: C.orange, fontWeight: 700 }}>+{bid.bid_premium_pct}%</span>
                  <span style={{ color: C.yellow }}>${(base * (1 + bid.bid_premium_pct / 100)).toFixed(4)}</span>
                  <span style={{ color: C.green, fontWeight: 700 }}>+{(bid.score_impact * 100).toFixed(1)}pts</span>
                </>
              ) : (
                <>
                  <span style={{ color: C.muted }}>—</span>
                  <span style={{ color: C.muted }}>—</span>
                  <span style={{ color: C.muted }}>—</span>
                </>
              )}
              {/* CHAIN badge */}
              <span style={{
                background: chainMeta.color + "22", color: chainMeta.color,
                fontSize: 8, fontWeight: 700, padding: "2px 4px",
                alignSelf: "center",
                outline: isNative ? "none" : `1px solid ${chainMeta.color}44`,
              }}>
                {chainMeta.symbol}
                {!isNative && <span style={{ color: C.red, marginLeft: 3 }}>−{Math.round(Math.min(chainMeta.bridge / 0.01, 0.20) * 100)}%</span>}
              </span>
              {/* TTL */}
              {bid ? (
                <span style={{ color: bid.seconds_remaining < 60 ? C.red : C.dim, fontSize: 9 }}>
                  {tick >= 0 && timeLeft(bid.expires_at)}
                </span>
              ) : (
                <span style={{ color: C.muted, fontSize: 9 }}>no bid</span>
              )}
            </div>
          );
        })}
      </Panel>

      {/* Bid submission form */}
      <Panel style={{ marginBottom: 1 }}>
        <div style={{ padding: "8px 12px", borderBottom: `1px solid ${C.border}` }}>
          <Label>PLACE BID — BOOST ROUTING PRIORITY</Label>
        </div>
        <div style={{ padding: "14px 12px", display: "flex", gap: 12, alignItems: "flex-end", flexWrap: "wrap" as const }}>
          {/* Provider selector */}
          <div>
            <div style={{ fontSize: 8, color: C.muted, marginBottom: 4 }}>PROVIDER</div>
            <select
              value={form.provider_id}
              onChange={e => setForm(f => ({ ...f, provider_id: e.target.value }))}
              style={{
                background: C.row, color: C.text, border: `1px solid ${C.border2}`,
                fontFamily: MONO, fontSize: 10, padding: "6px 8px", outline: "none",
              }}
            >
              {PROVIDER_IDS.map(pid => (
                <option key={pid} value={pid}>{PROVIDER_LABELS[pid]}</option>
              ))}
            </select>
          </div>

          {/* Premium % input */}
          <div>
            <div style={{ fontSize: 8, color: C.muted, marginBottom: 4 }}>PREMIUM % (1–50)</div>
            <input
              type="number" min={1} max={50} step={1}
              value={form.bid_premium_pct}
              onChange={e => setForm(f => ({ ...f, bid_premium_pct: Number(e.target.value) }))}
              style={{
                background: C.row, color: C.orange, border: `1px solid ${C.border2}`,
                fontFamily: MONO, fontSize: 11, fontWeight: 700, padding: "6px 8px",
                outline: "none", width: 80,
              }}
            />
          </div>

          {/* Duration selector */}
          <div>
            <div style={{ fontSize: 8, color: C.muted, marginBottom: 4 }}>DURATION</div>
            <select
              value={form.duration_s}
              onChange={e => setForm(f => ({ ...f, duration_s: Number(e.target.value) }))}
              style={{
                background: C.row, color: C.text, border: `1px solid ${C.border2}`,
                fontFamily: MONO, fontSize: 10, padding: "6px 8px", outline: "none",
              }}
            >
              <option value={60}>1 min</option>
              <option value={300}>5 min</option>
              <option value={600}>10 min</option>
              <option value={1800}>30 min</option>
              <option value={3600}>1 hour</option>
            </select>
          </div>

          {/* Score preview */}
          <div style={{ padding: "6px 0" }}>
            <div style={{ fontSize: 8, color: C.muted, marginBottom: 4 }}>SCORE IMPACT</div>
            <div style={{ fontSize: 13, fontWeight: 700, color: C.green }}>
              +{(Math.min(form.bid_premium_pct / 100, 0.5) * 15).toFixed(1)}pts
            </div>
          </div>

          {/* Dynamic price preview */}
          <div style={{ padding: "6px 0" }}>
            <div style={{ fontSize: 8, color: C.muted, marginBottom: 4 }}>BUYER PAYS</div>
            <div style={{ fontSize: 13, fontWeight: 700, color: C.yellow }}>
              ${((BASE_PRICES[form.provider_id] ?? 0.001) * (1 + form.bid_premium_pct / 100)).toFixed(4)}
            </div>
          </div>

          <button
            onClick={submitBid}
            disabled={status?.type === "loading"}
            style={{
              background: status?.type === "loading" ? C.border : C.orange,
              color: status?.type === "loading" ? C.dim : "#000",
              border: "none", padding: "8px 18px", cursor: status?.type === "loading" ? "default" : "pointer",
              fontFamily: MONO, fontSize: 10, fontWeight: 700, letterSpacing: "0.08em",
              transition: "background 0.15s", alignSelf: "flex-end",
            }}
          >
            {status?.type === "loading" ? "PLACING…" : "PLACE BID"}
          </button>
        </div>

        {status && status.type !== "loading" && (
          <div style={{
            padding: "8px 12px", borderTop: `1px solid ${C.border}`,
            color: status.type === "ok" ? C.green : C.red, fontSize: 10,
          }}>
            {status.type === "ok" ? "✓ " : "✗ "}{status.msg}
          </div>
        )}
      </Panel>

      {/* Chain routing panel */}
      <Panel style={{ marginBottom: 1 }}>
        <div style={{
          padding: "8px 12px", borderBottom: `1px solid ${C.border}`,
          display: "flex", alignItems: "center", justifyContent: "space-between",
        }}>
          <Label>CROSSCHAIN ROUTING — SETTLEMENT CHAIN ASSIGNMENT</Label>
          <span style={{ color: C.muted, fontSize: 9 }}>BRIDGE PENALTY = min(cost / $0.01, 20%) · MAX −20pts</span>
        </div>

        {/* Chain summary */}
        <div style={{
          display: "grid", gridTemplateColumns: "60px 1fr 80px 80px 70px 60px",
          padding: "5px 12px", borderBottom: `1px solid ${C.border2}`,
        }}>
          {["CHAIN", "NAME", "BRIDGE $", "PENALTY", "PROVIDERS", "NATIVE"].map(h => <Label key={h}>{h}</Label>)}
        </div>
        {chains.map((ch: any, i: number) => {
          const meta = CHAIN_INFO[ch.chain_id] ?? { color: C.dim, symbol: "?" };
          return (
            <div key={ch.chain_id} style={{
              display: "grid", gridTemplateColumns: "60px 1fr 80px 80px 70px 60px",
              padding: "6px 12px", borderBottom: `1px solid ${C.border}`,
              background: ch.native ? `${C.cyan}08` : i % 2 === 0 ? C.panel : C.row,
              fontSize: 10,
            }}>
              <span style={{ background: meta.color + "22", color: meta.color, fontSize: 9, fontWeight: 700, padding: "2px 5px" }}>
                {ch.symbol}
              </span>
              <span style={{ color: C.text }}>{ch.name}</span>
              <span style={{ color: ch.bridge_cost_usdc > 0 ? C.red : C.green }}>
                {ch.bridge_cost_usdc > 0 ? `$${ch.bridge_cost_usdc.toFixed(3)}` : "free"}
              </span>
              <span style={{ color: ch.penalty_pct > 0 ? C.red : C.green, fontWeight: ch.penalty_pct > 0 ? 700 : 400 }}>
                {ch.penalty_pct > 0 ? `−${ch.penalty_pct}%` : "none"}
              </span>
              <span style={{ color: C.dim }}>{ch.provider_count}</span>
              <span style={{ color: ch.native ? C.green : C.muted, fontSize: 9 }}>{ch.native ? "YES" : "—"}</span>
            </div>
          );
        })}

        {/* Chain assignment form */}
        <div style={{ padding: "12px 12px 10px", borderTop: `1px solid ${C.border2}` }}>
          <div style={{ fontSize: 8, color: C.muted, marginBottom: 8 }}>ASSIGN PROVIDER TO CHAIN</div>
          <div style={{ display: "flex", gap: 10, alignItems: "flex-end", flexWrap: "wrap" as const }}>
            <div>
              <div style={{ fontSize: 8, color: C.muted, marginBottom: 4 }}>PROVIDER</div>
              <select
                value={chainForm.provider_id}
                onChange={e => setChainForm(f => ({ ...f, provider_id: e.target.value }))}
                style={{ background: C.row, color: C.text, border: `1px solid ${C.border2}`, fontFamily: MONO, fontSize: 10, padding: "6px 8px", outline: "none" }}
              >
                {PROVIDER_IDS.map(pid => <option key={pid} value={pid}>{PROVIDER_LABELS[pid]}</option>)}
              </select>
            </div>
            <div>
              <div style={{ fontSize: 8, color: C.muted, marginBottom: 4 }}>CHAIN</div>
              <select
                value={chainForm.chain_id}
                onChange={e => setChainForm(f => ({ ...f, chain_id: Number(e.target.value) }))}
                style={{ background: C.row, color: C.text, border: `1px solid ${C.border2}`, fontFamily: MONO, fontSize: 10, padding: "6px 8px", outline: "none" }}
              >
                {Object.entries(CHAIN_INFO).map(([cid, meta]) => (
                  <option key={cid} value={Number(cid)}>{meta.symbol} — {meta.name}</option>
                ))}
              </select>
            </div>
            {/* Penalty preview */}
            <div style={{ padding: "6px 0" }}>
              <div style={{ fontSize: 8, color: C.muted, marginBottom: 4 }}>ROUTING PENALTY</div>
              <div style={{ fontSize: 13, fontWeight: 700, color: chainForm.chain_id === ARC_CHAIN_ID ? C.green : C.red }}>
                {chainForm.chain_id === ARC_CHAIN_ID
                  ? "none"
                  : `−${Math.round(Math.min((CHAIN_INFO[chainForm.chain_id]?.bridge ?? 0) / 0.01, 0.20) * 100)}%`
                }
              </div>
            </div>
            <button
              onClick={submitChainRegister}
              disabled={chainStatus?.type === "loading"}
              style={{
                background: chainStatus?.type === "loading" ? C.border : C.cyan,
                color: chainStatus?.type === "loading" ? C.dim : "#000",
                border: "none", padding: "8px 16px", cursor: chainStatus?.type === "loading" ? "default" : "pointer",
                fontFamily: MONO, fontSize: 10, fontWeight: 700, letterSpacing: "0.08em",
                transition: "background 0.15s", alignSelf: "flex-end",
              }}
            >
              {chainStatus?.type === "loading" ? "SAVING…" : "REGISTER"}
            </button>
          </div>
          {chainStatus && chainStatus.type !== "loading" && (
            <div style={{ marginTop: 8, color: chainStatus.type === "ok" ? C.green : C.red, fontSize: 10 }}>
              {chainStatus.type === "ok" ? "✓ " : "✗ "}{chainStatus.msg}
            </div>
          )}
        </div>
      </Panel>

      {/* Staking leaderboard + slash */}
      <Panel style={{ marginBottom: 1 }}>
        <div style={{
          padding: "8px 12px", borderBottom: `1px solid ${C.border}`,
          display: "flex", alignItems: "center", justifyContent: "space-between",
        }}>
          <Label>STAKING / SLASHING — PROVIDER COLLATERAL (GAP 10)</Label>
          <span style={{ color: C.muted, fontSize: 9 }}>STAKE BOOST = min(stake/$100, +10pts) · SLASH = −5pts each · MAX −25pts</span>
        </div>

        {/* Leaderboard header */}
        <div style={{
          display: "grid", gridTemplateColumns: "44px 1fr 80px 60px 60px 60px 70px",
          padding: "5px 12px", borderBottom: `1px solid ${C.border2}`,
        }}>
          {["TYPE", "PROVIDER", "STAKED $", "BOOST", "SLASHES", "PENALTY", "NET Δ"].map(h => <Label key={h}>{h}</Label>)}
        </div>

        {PROVIDER_IDS.map((pid, i) => {
          const catKey = pid.toUpperCase();
          const color  = CAT_COLOR[catKey] ?? C.text;
          const tag    = CAT_TAG[catKey]   ?? "SIG";
          const stake  = stakes.find((s: any) => s.provider_id === pid);
          const amt    = stake?.amount_usdc ?? 0;
          const boost  = stake?.stake_boost ?? 0;
          const slashes = stake?.slash_count ?? 0;
          const penalty = stake?.slash_penalty ?? 0;
          const net     = stake?.net_score_delta ?? 0;
          return (
            <div key={pid} style={{
              display: "grid", gridTemplateColumns: "44px 1fr 80px 60px 60px 60px 70px",
              padding: "7px 12px", borderBottom: `1px solid ${C.border}`,
              background: amt > 0 ? `${C.purple}0a` : i % 2 === 0 ? C.panel : C.row,
              fontSize: 10,
            }}>
              <span style={{ background: color + "22", color, fontSize: 9, fontWeight: 700, padding: "2px 5px" }}>{tag}</span>
              <span style={{ color: C.text }}>{PROVIDER_LABELS[pid]}</span>
              <span style={{ color: amt > 0 ? C.purple : C.muted, fontWeight: amt > 0 ? 700 : 400 }}>
                {amt > 0 ? `$${amt.toFixed(2)}` : "—"}
              </span>
              <span style={{ color: boost > 0 ? C.green : C.muted }}>
                {boost > 0 ? `+${(boost * 100).toFixed(1)}pts` : "—"}
              </span>
              <span style={{ color: slashes > 0 ? C.red : C.muted }}>
                {slashes > 0 ? slashes : "—"}
              </span>
              <span style={{ color: penalty > 0 ? C.red : C.muted, fontWeight: penalty > 0 ? 700 : 400 }}>
                {penalty > 0 ? `−${(penalty * 100).toFixed(1)}pts` : "—"}
              </span>
              <span style={{ color: net > 0 ? C.green : net < 0 ? C.red : C.muted, fontWeight: Math.abs(net) > 0 ? 700 : 400 }}>
                {net !== 0 ? `${net > 0 ? "+" : ""}${(net * 100).toFixed(1)}pts` : "—"}
              </span>
            </div>
          );
        })}

        {/* Stake deposit + slash forms */}
        <div style={{ padding: "12px 12px 10px", borderTop: `1px solid ${C.border2}` }}>
          <div style={{ fontSize: 8, color: C.muted, marginBottom: 8 }}>DEPOSIT STAKE / SLASH PROVIDER</div>
          <div style={{ display: "flex", gap: 10, alignItems: "flex-end", flexWrap: "wrap" as const }}>
            {/* Provider */}
            <div>
              <div style={{ fontSize: 8, color: C.muted, marginBottom: 4 }}>PROVIDER</div>
              <select
                value={stakeForm.provider_id}
                onChange={e => { setStakeForm(f => ({ ...f, provider_id: e.target.value })); setSlashForm(f => ({ ...f, provider_id: e.target.value })); }}
                style={{ background: C.row, color: C.text, border: `1px solid ${C.border2}`, fontFamily: MONO, fontSize: 10, padding: "6px 8px", outline: "none" }}
              >
                {PROVIDER_IDS.map(pid => <option key={pid} value={pid}>{PROVIDER_LABELS[pid]}</option>)}
              </select>
            </div>
            {/* Stake amount */}
            <div>
              <div style={{ fontSize: 8, color: C.muted, marginBottom: 4 }}>STAKE USDC</div>
              <input
                type="number" min={0.01} step={1}
                value={stakeForm.amount_usdc}
                onChange={e => setStakeForm(f => ({ ...f, amount_usdc: Number(e.target.value) }))}
                style={{ background: C.row, color: C.purple, border: `1px solid ${C.border2}`, fontFamily: MONO, fontSize: 11, fontWeight: 700, padding: "6px 8px", outline: "none", width: 80 }}
              />
            </div>
            {/* Boost preview */}
            <div style={{ padding: "6px 0" }}>
              <div style={{ fontSize: 8, color: C.muted, marginBottom: 4 }}>BOOST PREVIEW</div>
              <div style={{ fontSize: 13, fontWeight: 700, color: C.green }}>
                +{(Math.min(stakeForm.amount_usdc / 100, 0.10) * 100).toFixed(1)}pts
              </div>
            </div>
            <button
              onClick={submitStakeDeposit}
              disabled={stakeStatus?.type === "loading"}
              style={{
                background: stakeStatus?.type === "loading" ? C.border : C.purple,
                color: stakeStatus?.type === "loading" ? C.dim : "#fff",
                border: "none", padding: "8px 14px", cursor: stakeStatus?.type === "loading" ? "default" : "pointer",
                fontFamily: MONO, fontSize: 10, fontWeight: 700, letterSpacing: "0.08em",
                transition: "background 0.15s", alignSelf: "flex-end",
              }}
            >
              {stakeStatus?.type === "loading" ? "STAKING…" : "DEPOSIT STAKE"}
            </button>

            <div style={{ width: 1, height: 32, background: C.border, alignSelf: "flex-end" }} />

            {/* Slash amount */}
            <div>
              <div style={{ fontSize: 8, color: C.muted, marginBottom: 4 }}>SLASH USDC</div>
              <input
                type="number" min={0} step={1}
                value={slashForm.slash_amount}
                onChange={e => setSlashForm(f => ({ ...f, slash_amount: Number(e.target.value) }))}
                style={{ background: C.row, color: C.red, border: `1px solid ${C.border2}`, fontFamily: MONO, fontSize: 11, fontWeight: 700, padding: "6px 8px", outline: "none", width: 80 }}
              />
            </div>
            {/* Reason */}
            <div>
              <div style={{ fontSize: 8, color: C.muted, marginBottom: 4 }}>REASON</div>
              <input
                type="text" placeholder="bad signal quality"
                value={slashForm.reason}
                onChange={e => setSlashForm(f => ({ ...f, reason: e.target.value }))}
                style={{ background: C.row, color: C.text, border: `1px solid ${C.border2}`, fontFamily: MONO, fontSize: 10, padding: "6px 8px", outline: "none", width: 160 }}
              />
            </div>
            <button
              onClick={submitSlash}
              disabled={stakeStatus?.type === "loading"}
              style={{
                background: stakeStatus?.type === "loading" ? C.border : C.red,
                color: "#fff", border: "none", padding: "8px 14px",
                cursor: stakeStatus?.type === "loading" ? "default" : "pointer",
                fontFamily: MONO, fontSize: 10, fontWeight: 700, letterSpacing: "0.08em",
                transition: "background 0.15s", alignSelf: "flex-end",
              }}
            >
              {stakeStatus?.type === "loading" ? "SLASHING…" : "SLASH"}
            </button>
          </div>
          {stakeStatus && stakeStatus.type !== "loading" && (
            <div style={{ marginTop: 8, color: stakeStatus.type === "ok" ? C.green : C.red, fontSize: 10 }}>
              {stakeStatus.type === "ok" ? "✓ " : "✗ "}{stakeStatus.msg}
            </div>
          )}
        </div>
      </Panel>

      {/* Slash history */}
      <Panel style={{ marginBottom: 1 }}>
        <div style={{ padding: "8px 12px", borderBottom: `1px solid ${C.border}` }}>
          <Label>SLASH HISTORY</Label>
        </div>
        <div style={{
          display: "grid", gridTemplateColumns: "44px 1fr 80px 90px 80px",
          padding: "5px 12px", borderBottom: `1px solid ${C.border2}`,
        }}>
          {["TYPE", "PROVIDER", "AMT SLASHED", "REASON", "TIME"].map(h => <Label key={h}>{h}</Label>)}
        </div>
        {slashHistory.length === 0 && (
          <div style={{ padding: "20px 12px", color: C.muted, fontSize: 10 }}>
            No slash events recorded yet
          </div>
        )}
        {slashHistory.map((ev: any, i: number) => {
          const catKey = (ev.provider_id ?? "").toUpperCase();
          const color  = CAT_COLOR[catKey] ?? C.text;
          const tag    = CAT_TAG[catKey]   ?? "SIG";
          return (
            <div key={ev.id} style={{
              display: "grid", gridTemplateColumns: "44px 1fr 80px 90px 80px",
              padding: "6px 12px", borderBottom: `1px solid ${C.border}`,
              background: i % 2 === 0 ? C.panel : C.row, fontSize: 10,
            }}>
              <span style={{ background: color + "22", color, fontSize: 9, fontWeight: 700, padding: "2px 5px" }}>{tag}</span>
              <span style={{ color: C.text }}>{PROVIDER_LABELS[ev.provider_id] ?? ev.provider_id}</span>
              <span style={{ color: C.red, fontWeight: 700 }}>
                {ev.slash_amount > 0 ? `-$${ev.slash_amount.toFixed(2)}` : "—"}
              </span>
              <span style={{ color: C.dim, fontSize: 9 }}>{ev.reason || "—"}</span>
              <span style={{ color: C.muted, fontSize: 9 }}>
                {ev.slash_at ? new Date(ev.slash_at * 1000).toLocaleTimeString("en", { hour12: false }) : "—"}
              </span>
            </div>
          );
        })}
      </Panel>

      {/* GAP 11: Composite Signal — Agent-as-Provider Earnings */}
      <Panel>
        <div style={{ padding: "8px 12px", borderBottom: `1px solid ${C.border}`, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div>
            <Label>COMPOSITE SIGNAL — AGENT-AS-PROVIDER (GAP 11)</Label>
            <span style={{ color: C.muted, fontSize: 9, marginLeft: 8 }}>
              Agent buys raw signals → synthesizes → re-sells at $0.025/call · markup over ~$0.021 cost
            </span>
          </div>
          {compositeEarnings && (
            <div style={{ display: "flex", gap: 16, fontSize: 10 }}>
              <span style={{ color: C.green, fontWeight: 700 }}>
                +${(compositeEarnings.total_earned ?? 0).toFixed(4)} earned
              </span>
              <span style={{ color: C.dim }}>{compositeEarnings.total_sales ?? 0} sales</span>
              <span style={{ color: C.muted }}>$0.025/call</span>
            </div>
          )}
        </div>

        {/* Latest composite */}
        {compositeEarnings?.history?.length > 0 ? (
          <div>
            <div style={{
              display: "grid", gridTemplateColumns: "60px 80px 1fr 70px 80px 70px",
              padding: "5px 12px", borderBottom: `1px solid ${C.border2}`,
              fontSize: 9, color: C.muted, fontWeight: 700, letterSpacing: "0.06em",
            }}>
              {["SESSION", "TOKEN", "ACTION", "SIGNALS", "SPENT", "PUBLISHED"].map(h => <span key={h}>{h}</span>)}
            </div>
            {compositeEarnings.history.map((h: any, i: number) => (
              <div key={h.id} style={{
                display: "grid", gridTemplateColumns: "60px 80px 1fr 70px 80px 70px",
                padding: "6px 12px", borderBottom: `1px solid ${C.border}`,
                background: i % 2 === 0 ? C.panel : C.row, fontSize: 10,
              }}>
                <span style={{ color: C.muted, fontSize: 9 }}>{(h.session_id ?? "").slice(0, 8)}</span>
                <span style={{ color: C.cyan, fontWeight: 700 }}>{h.token}</span>
                <span style={{ color: h.action?.startsWith("ACCUMULATE") || h.action?.startsWith("BUY") ? C.green : h.action?.startsWith("SELL") || h.action?.startsWith("REDUCE") ? C.red : C.yellow, fontWeight: 600 }}>
                  {(h.action ?? "").split("—")[0].trim().split(" ").slice(0, 3).join(" ")}
                </span>
                <span style={{ color: C.dim }}>{h.signal_count} signals</span>
                <span style={{ color: C.red }}>-${(h.spend_usdc ?? 0).toFixed(4)}</span>
                <span style={{ color: C.muted, fontSize: 9 }}>
                  {h.published_at ? new Date(h.published_at * 1000).toLocaleTimeString("en", { hour12: false }) : "—"}
                </span>
              </div>
            ))}
            <div style={{ padding: "8px 12px", borderTop: `1px solid ${C.border2}`, display: "flex", gap: 24, fontSize: 10 }}>
              <span style={{ color: C.green }}>Revenue: +${(compositeEarnings.total_earned ?? 0).toFixed(4)} USDC</span>
              <span style={{ color: C.red }}>Cost: -${(compositeEarnings.history.reduce((s: number, h: any) => s + (h.spend_usdc ?? 0), 0)).toFixed(4)} USDC</span>
              <span style={{ color: C.cyan, fontWeight: 700 }}>
                Net: ${((compositeEarnings.total_earned ?? 0) - compositeEarnings.history.reduce((s: number, h: any) => s + (h.spend_usdc ?? 0), 0)).toFixed(4)} USDC
              </span>
            </div>
          </div>
        ) : (
          <div style={{ padding: "20px 12px", color: C.muted, fontSize: 10 }}>
            No composite signals published yet — run the agent to generate the first composite
          </div>
        )}
      </Panel>

      {/* Bid history */}
      <Panel>
        <div style={{ padding: "8px 12px", borderBottom: `1px solid ${C.border}` }}>
          <Label>BID HISTORY</Label>
        </div>
        <div style={{
          display: "grid", gridTemplateColumns: "48px 1fr 80px 60px 80px 70px",
          padding: "5px 12px", borderBottom: `1px solid ${C.border2}`,
        }}>
          {["TYPE", "PROVIDER", "PREMIUM", "BOOST", "PLACED", "STATUS"].map(h => <Label key={h}>{h}</Label>)}
        </div>
        {history.length === 0 && (
          <div style={{ padding: "20px 12px", color: C.muted, fontSize: 10 }}>
            No bids placed yet — use the form above to place your first bid
          </div>
        )}
        {history.map((b: any, i: number) => {
          const catKey = (b.provider_id ?? "").toUpperCase();
          const color  = CAT_COLOR[catKey] ?? C.text;
          const tag    = CAT_TAG[catKey]   ?? "SIG";
          const isActive = b.active && b.seconds_remaining > 0;
          return (
            <div key={b.bid_id} style={{
              display: "grid", gridTemplateColumns: "48px 1fr 80px 60px 80px 70px",
              padding: "6px 12px", borderBottom: `1px solid ${C.border}`,
              background: i % 2 === 0 ? C.panel : C.row, fontSize: 10,
            }}>
              <span style={{ background: color + "22", color, fontSize: 9, fontWeight: 700, padding: "2px 5px" }}>{tag}</span>
              <span style={{ color: C.text }}>{PROVIDER_LABELS[b.provider_id] ?? b.provider_id}</span>
              <span style={{ color: C.orange, fontWeight: 700 }}>+{b.bid_premium_pct}%</span>
              <span style={{ color: C.green }}>+{((b.score_impact ?? 0) * 100).toFixed(1)}pts</span>
              <span style={{ color: C.muted }}>
                {b.placed_at ? new Date(b.placed_at * 1000).toLocaleTimeString("en", { hour12: false }) : "—"}
              </span>
              <span style={{ color: isActive ? C.green : C.muted, fontSize: 9 }}>
                {isActive ? "ACTIVE" : "EXPIRED"}
              </span>
            </div>
          );
        })}
      </Panel>
    </div>
  );
}

// ── Treasury Dashboard (GAP 8) ───────────────────────────────────
function TreasuryDashboard() {
  const [treasury, setTreasury] = useState<any>(null);

  const load = useCallback(() => {
    fetch(`${API_BASE}/treasury`).then(r => r.json()).then(setTreasury).catch(() => {});
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, 60_000);
    return () => clearInterval(t);
  }, [load]);

  if (!treasury) return (
    <div style={{ padding: 60, color: C.muted, fontFamily: MONO, fontSize: 11, textAlign: "center" }}>
      LOADING TREASURY DATA...
    </div>
  );

  const rev      = treasury.revenue ?? {};
  const spd      = treasury.spend ?? {};
  const net      = treasury.net ?? 0;
  const tradePnl = treasury.trade_performance?.total_pnl_usdc ?? 0;
  const dailyFlow    = treasury.daily_flow ?? [];
  const byEndpoint   = treasury.by_endpoint ?? [];
  const gov    = treasury.governance ?? {};
  const policy = gov.policy ?? {};

  const maxBar = Math.max(...dailyFlow.map((d: any) => Math.max(d.revenue, d.spend, 0.000001)));

  return (
    <div style={{ fontFamily: MONO }}>
      {/* 5-stat header */}
      <Panel style={{ display: "flex", marginBottom: 1 }}>
        <StatCell label="REVENUE"    value={`$${(rev.total ?? 0).toFixed(6)}`}   color={C.green}  sub={`${rev.calls ?? 0} settlements`} />
        <StatCell label="SPEND"      value={`$${(spd.total ?? 0).toFixed(6)}`}   color={C.orange} sub={`${spd.calls ?? 0} signals`} />
        <StatCell label="NET"        value={`${net >= 0 ? "+" : "−"}$${Math.abs(net).toFixed(6)}`} color={net >= 0 ? C.green : C.red} sub="revenue − spend" />
        <StatCell label="TRADE P&L"  value={`${tradePnl >= 0 ? "+" : "−"}$${Math.abs(tradePnl).toFixed(4)}`} color={tradePnl >= 0 ? C.green : C.red} sub="simulated" />
        <StatCell label="DAILY BURN" value={`$${(gov.today_spent_usdc ?? 0).toFixed(4)}`} color={C.yellow} sub={`$${(gov.today_remaining_usdc ?? 0).toFixed(2)} left`} />
        <div style={{ flex: 1 }} />
      </Panel>

      {/* 14-day cashflow chart */}
      <Panel style={{ marginBottom: 1 }}>
        <div style={{
          padding: "8px 12px", borderBottom: `1px solid ${C.border}`,
          display: "flex", alignItems: "center", justifyContent: "space-between",
        }}>
          <Label>14-DAY CASHFLOW — REVENUE vs SPEND</Label>
          <div style={{ display: "flex", gap: 14, alignItems: "center" }}>
            <span style={{ color: C.green,  fontSize: 9 }}>▓ REVENUE</span>
            <span style={{ color: C.orange, fontSize: 9 }}>▓ SPEND</span>
          </div>
        </div>
        {dailyFlow.length === 0 ? (
          <div style={{ padding: "24px 12px", color: C.muted, fontSize: 10 }}>
            No cashflow data yet — run the agent to populate
          </div>
        ) : (
          <div style={{ padding: "12px 12px 8px", overflowX: "auto" }}>
            <div style={{ display: "flex", alignItems: "flex-end", gap: 6, height: 96 }}>
              {[...dailyFlow].reverse().map((d: any) => (
                <div key={d.day} style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", minWidth: 28 }}>
                  <div style={{ display: "flex", gap: 2, alignItems: "flex-end", height: 76, width: "100%", justifyContent: "center" }}>
                    <div style={{
                      width: 8, background: C.green, opacity: 0.8,
                      height: `${Math.max(2, (d.revenue / maxBar) * 100)}%`,
                    }} />
                    <div style={{
                      width: 8, background: C.orange, opacity: 0.8,
                      height: `${Math.max(2, (d.spend / maxBar) * 100)}%`,
                    }} />
                  </div>
                  <div style={{ fontSize: 7, color: C.muted, marginTop: 3, whiteSpace: "nowrap" as const }}>
                    {d.day.slice(5)}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </Panel>

      {/* Revenue by endpoint */}
      {byEndpoint.length > 0 && (
        <Panel style={{ marginBottom: 1 }}>
          <div style={{ padding: "8px 12px", borderBottom: `1px solid ${C.border}` }}>
            <Label>REVENUE BY ENDPOINT</Label>
          </div>
          <div style={{
            display: "grid", gridTemplateColumns: "1fr 70px 110px 90px",
            padding: "5px 12px", borderBottom: `1px solid ${C.border2}`,
          }}>
            {["ENDPOINT", "CALLS", "TOTAL", "AVG"].map(h => <Label key={h}>{h}</Label>)}
          </div>
          {byEndpoint.map((e: any, i: number) => (
            <div key={e.endpoint} style={{
              display: "grid", gridTemplateColumns: "1fr 70px 110px 90px",
              padding: "6px 12px", borderBottom: `1px solid ${C.border}`,
              background: i % 2 === 0 ? C.panel : C.row, fontSize: 10,
            }}>
              <span style={{ color: C.cyan }}>{e.endpoint}</span>
              <span style={{ color: C.dim }}>{e.calls}</span>
              <span style={{ color: C.green, fontWeight: 700 }}>${e.total_revenue.toFixed(6)}</span>
              <span style={{ color: C.muted }}>${e.avg_revenue.toFixed(6)}</span>
            </div>
          ))}
        </Panel>
      )}

      {/* Governance policy card */}
      <Panel>
        <div style={{ padding: "8px 12px", borderBottom: `1px solid ${C.border}` }}>
          <Label>GOVERNANCE POLICY</Label>
        </div>
        <div style={{ display: "flex", flexWrap: "wrap" as const }}>
          {[
            { k: "MAX/CALL",    v: `$${policy.max_per_call_usdc?.toFixed(4) ?? "—"}`,          c: C.text },
            { k: "DAILY CAP",   v: `$${policy.daily_budget_usdc?.toFixed(2) ?? "—"}`,           c: C.text },
            { k: "HUMAN GATE",  v: `>$${policy.require_human_above_usdc?.toFixed(4) ?? "—"}`,   c: C.yellow },
            { k: "WHITELIST",   v: policy.whitelist?.[0] === "*" ? "OPEN" : `${policy.whitelist?.length ?? 0} addr`, c: C.green },
            { k: "TODAY USED",  v: `$${(gov.today_spent_usdc ?? 0).toFixed(4)}`,                c: C.orange },
            { k: "REMAINING",   v: `$${(gov.today_remaining_usdc ?? 0).toFixed(4)}`,            c: C.cyan },
            { k: "PROVIDER",    v: treasury.provider_wallet ? `${treasury.provider_wallet.slice(0, 8)}…` : "—", c: C.dim },
          ].map(({ k, v, c }) => (
            <div key={k} style={{
              padding: "10px 18px",
              borderRight: `1px solid ${C.border}`,
              borderBottom: `1px solid ${C.border}`,
            }}>
              <div style={{ fontSize: 8, color: C.muted, marginBottom: 4 }}>{k}</div>
              <div style={{ fontSize: 14, color: c, fontWeight: 700 }}>{v}</div>
            </div>
          ))}
        </div>
      </Panel>
    </div>
  );
}

// ── Network / Faucet ─────────────────────────────────────────────
function Network() {
  const [wallet, setWallet] = useState("");
  const [status, setStatus] = useState<{ type: string; msg: string } | null>(null);
  const [copied, setCopied] = useState(false);

  const requestFaucet = () => {
    if (!wallet || !wallet.startsWith("0x")) { setStatus({ type: "error", msg: "Invalid address — must start with 0x" }); return; }
    navigator.clipboard.writeText(wallet);
    setStatus({ type: "loading", msg: "Address copied — opening Circle faucet..." });
    setTimeout(() => {
      window.open("https://faucet.circle.com", "_blank", "noopener,noreferrer");
      setStatus({ type: "success", msg: "Address in clipboard — paste in faucet to receive testnet USDC" });
    }, 600);
  };

  const copyConfig = () => {
    navigator.clipboard.writeText(
      "Network: Arc Testnet\nRPC: https://rpc.testnet.arc.network\nChain ID: 5042002\nCurrency: USDC\nExplorer: https://testnet.arcscan.app"
    );
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const netRows = [
    { k: "NETWORK",     v: "Arc Testnet" },
    { k: "RPC",         v: "https://rpc.testnet.arc.network" },
    { k: "CHAIN ID",    v: "5042002" },
    { k: "USDC",        v: "0x3600000000000000000000000000000000000000" },
    { k: "EXPLORER",    v: "testnet.arcscan.app" },
    { k: "FAUCET",      v: "faucet.circle.com" },
    { k: "GatewayWallet", v: "0x0077777d7EBA4688BDeF3E311b846F25870A19B9" },
  ];

  return (
    <div style={{ maxWidth: 640, fontFamily: MONO }}>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 1, marginBottom: 1 }}>
        {/* Network config */}
        <Panel>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "8px 12px", borderBottom: `1px solid ${C.border}` }}>
            <Label>ARC TESTNET CONFIG</Label>
            <button onClick={copyConfig} style={{
              background: "none", border: `1px solid ${C.border2}`,
              color: copied ? C.green : C.dim, padding: "3px 10px",
              cursor: "pointer", fontFamily: MONO, fontSize: 9,
            }}>
              {copied ? "COPIED" : "COPY ALL"}
            </button>
          </div>
          {netRows.map(({ k, v }) => (
            <div key={k} style={{
              display: "grid", gridTemplateColumns: "130px 1fr",
              padding: "5px 12px", borderBottom: `1px solid ${C.border}`,
              fontSize: 10,
            }}>
              <Label>{k}</Label>
              <span style={{ color: C.text, wordBreak: "break-all" as const }}>{v}</span>
            </div>
          ))}
        </Panel>

        {/* Faucet */}
        <Panel>
          <div style={{ padding: "8px 12px", borderBottom: `1px solid ${C.border}` }}>
            <Label>GET TESTNET USDC</Label>
          </div>
          <div style={{ padding: 14 }}>
            <Label style={{ display: "block", marginBottom: 6 }}>WALLET ADDRESS</Label>
            <input
              value={wallet}
              onChange={e => setWallet(e.target.value)}
              placeholder="0x..."
              style={{
                width: "100%", background: C.bg, border: `1px solid ${C.border2}`,
                padding: "8px 10px", color: C.text, fontFamily: MONO, fontSize: 11,
                outline: "none", marginBottom: 8, boxSizing: "border-box" as const,
              }}
            />
            <button onClick={requestFaucet} style={{
              width: "100%", background: C.orange, color: "#000", border: "none",
              padding: "8px", cursor: "pointer", fontFamily: MONO, fontSize: 10,
              fontWeight: 700, letterSpacing: "0.08em",
            }}>
              COPY ADDRESS + OPEN FAUCET
            </button>
            {status && (
              <div style={{
                marginTop: 8, padding: "6px 10px", fontSize: 10,
                background: status.type === "success" ? `${C.green}11` : status.type === "error" ? `${C.red}11` : `${C.cyan}11`,
                color: status.type === "success" ? C.green : status.type === "error" ? C.red : C.cyan,
                border: `1px solid currentColor`,
              }}>
                {status.msg}
              </div>
            )}
          </div>
          <div style={{ padding: "10px 14px", borderTop: `1px solid ${C.border}` }}>
            <a href="https://faucet.circle.com" target="_blank" rel="noopener noreferrer" style={{
              color: C.orange, textDecoration: "none", fontSize: 10,
            }}>
              OPEN CIRCLE FAUCET DIRECTLY →
            </a>
          </div>
        </Panel>
      </div>

      {/* ERC-8004 registries */}
      <Panel>
        <div style={{ padding: "8px 12px", borderBottom: `1px solid ${C.border}` }}>
          <Label>ERC-8004 REGISTRIES — ARC TESTNET</Label>
        </div>
        {[
          { k: "IdentityRegistry",    v: "0x8004A818BFB912233c491871b3d84c89A494BD9e" },
          { k: "ReputationRegistry",  v: "0x8004B663056A597Dffe9eCcC1965A193B7388713" },
          { k: "ValidationRegistry",  v: "0x8004Cb1BF31DAf7788923b405b754f57acEB4272" },
        ].map(({ k, v }) => (
          <div key={k} style={{
            display: "grid", gridTemplateColumns: "180px 1fr",
            padding: "6px 12px", borderBottom: `1px solid ${C.border}`, fontSize: 10,
          }}>
            <Label>{k}</Label>
            <span style={{ color: C.cyan, wordBreak: "break-all" as const }}>{v}</span>
          </div>
        ))}
      </Panel>
    </div>
  );
}

// ── Top ticker strip ─────────────────────────────────────────────
function TickerStrip() {
  const [prices, setPrices] = useState<Record<string, { price: number; change: number }>>({});

  useEffect(() => {
    const load = async () => {
      try {
        const r = await fetch(`${API_BASE}/feed`);
        const d = await r.json();
        const sig = d.signal;
        if (sig?.category === "price_oracle") {
          const token = sig.data?.token;
          if (token) setPrices(prev => ({
            ...prev,
            [token]: { price: sig.data.price_usd, change: sig.data.change_24h_pct },
          }));
        }
      } catch {}
    };
    load();
    const id = setInterval(load, 5000);
    return () => clearInterval(id);
  }, []);

  const pairs = Object.entries(prices);

  return (
    <div style={{
      display: "flex", alignItems: "center", gap: 0,
      borderBottom: `1px solid ${C.border}`, background: C.bg,
      fontSize: 10, fontFamily: MONO, overflowX: "hidden" as const,
    }}>
      {pairs.length === 0 && ["BTC", "ETH", "SOL"].map(t => (
        <div key={t} style={{ padding: "4px 14px", borderRight: `1px solid ${C.border}`, color: C.muted }}>
          {t} <span style={{ color: C.muted }}>—</span>
        </div>
      ))}
      {pairs.map(([token, { price, change }]) => (
        <div key={token} style={{ padding: "4px 14px", borderRight: `1px solid ${C.border}`, display: "flex", gap: 8 }}>
          <span style={{ color: C.dim }}>{token}</span>
          <span style={{ color: C.text, fontWeight: 600 }}>${price.toLocaleString("en", { maximumFractionDigits: 2 })}</span>
          <span style={{ color: change >= 0 ? C.green : C.red }}>
            {change >= 0 ? "+" : ""}{change.toFixed(2)}%
          </span>
        </div>
      ))}
      <div style={{ flex: 1 }} />
      <div style={{ padding: "4px 14px", color: C.muted, fontSize: 9 }}>
        SRC: COINGECKO · ARC TESTNET · 30s
      </div>
    </div>
  );
}

// ── Main App ─────────────────────────────────────────────────────
export default function SignalPayApp() {
  const [tab, setTab] = useState("agent");
  const [signals, setSignals] = useState<Sig[]>([]);
  const { address, isConnected } = useAccount();
  const chainId = useChainId();

  useEffect(() => {
    let cancelled = false;
    const poll = async () => {
      try {
        const resp = await fetch(`${API_BASE}/feed`);
        if (!cancelled && resp.ok) {
          const data = await resp.json();
          const norm = normalizeSignal(data.signal);
          if (norm) setSignals(prev => [norm, ...prev].slice(0, 50));
        }
      } catch {}
      if (!cancelled) setTimeout(poll, 4000);
    };
    poll();
    return () => { cancelled = true; };
  }, []);

  const onSignal = useCallback((s: Sig) => setSignals(prev => [s, ...prev].slice(0, 50)), []);

  const TABS = [
    { id: "agent",    label: "TERMINAL" },
    { id: "explore",  label: "MARKET" },
    { id: "auction",  label: "AUCTION" },
    { id: "provider", label: "POSITIONS" },
    { id: "treasury", label: "TREASURY" },
    { id: "faucet",   label: "NETWORK" },
    { id: "arch",     label: "ARCHITECTURE" },
  ];

  return (
    <div style={{ minHeight: "100vh", background: C.bg, color: C.text, fontFamily: MONO }}>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600;700&display=swap');
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { background: ${C.bg}; }
        ::-webkit-scrollbar { width: 4px; height: 4px; }
        ::-webkit-scrollbar-track { background: transparent; }
        ::-webkit-scrollbar-thumb { background: ${C.border2}; }
        input::placeholder { color: ${C.muted}; }
        @keyframes blink { 0%,100% { opacity:1; } 50% { opacity:0; } }
        @keyframes fadeIn { from { opacity:0; transform:translateY(4px); } to { opacity:1; transform:none; } }
      `}</style>

      {/* Header */}
      <div style={{
        display: "flex", alignItems: "center", borderBottom: `1px solid ${C.border}`,
        background: C.panel, height: 44, padding: "0 16px", gap: 16,
      }}>
        <div style={{ display: "flex", alignItems: "baseline", gap: 6 }}>
          <span style={{ fontSize: 13, fontWeight: 700, color: C.text, letterSpacing: "0.06em" }}>SIGNAL</span>
          <span style={{ fontSize: 13, fontWeight: 700, color: C.orange, letterSpacing: "0.06em" }}>PAY</span>
          <span style={{ fontSize: 9, color: C.muted, marginLeft: 4 }}>GOVERNED AGENT PAYMENT INFRASTRUCTURE</span>
        </div>
        <div style={{ width: 1, height: 20, background: C.border }} />
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <div style={{ width: 5, height: 5, borderRadius: "50%", background: C.green }} />
          <Label style={{ color: C.green }}>ARC TESTNET</Label>
        </div>
        <div style={{ width: 1, height: 20, background: C.border }} />
        <Label>x402 · EIP-3009 · CIRCLE NANOPAYMENTS</Label>
        <div style={{ flex: 1 }} />
        <ConnectButton accountStatus="address" chainStatus="icon" showBalance={false} />
      </div>

      {/* Ticker */}
      <TickerStrip />

      {/* Governance bar */}
      <GovernanceBar />

      {/* Tab bar */}
      <div style={{
        display: "flex", borderBottom: `1px solid ${C.border}`,
        background: C.panel, padding: "0 4px",
      }}>
        {TABS.map(t => <Tab key={t.id} id={t.id} label={t.label} active={tab === t.id} onClick={() => setTab(t.id)} />)}
      </div>

      {/* Content */}
      <div style={tab === "agent" ? {} : { padding: tab === "arch" ? 0 : 16, maxWidth: tab === "arch" ? "none" : 1100, margin: "0 auto" }}>
        {tab === "agent"    && <AgentConsole signals={signals} onSignal={onSignal} />}
        {tab === "explore"  && <SignalExplorer />}
        {tab === "auction"  && <AuctionDashboard />}
        {tab === "provider" && <ProviderDashboard />}
        {tab === "treasury" && <TreasuryDashboard />}
        {tab === "faucet"   && <Network />}
        {tab === "arch"     && <SignalPayDiagram />}
      </div>

      {/* Footer */}
      <div style={{
        position: "fixed", bottom: 0, left: 0, right: 0,
        borderTop: `1px solid ${C.border}`, background: C.panel,
        display: "flex", justifyContent: "space-between", padding: "3px 14px",
        fontSize: 9, color: C.muted, fontFamily: MONO,
      }}>
        <span>SIGNALPAY v0.1.0 — CIRCLE ARC HACKATHON 2026 — TRACK 4: AGENTIC ECONOMY</span>
        <span>ARC L1 · CHAIN 5042002 · USDC NATIVE · ZERO-GAS NANOPAYMENTS</span>
      </div>
    </div>
  );
}
