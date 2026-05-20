import { useState } from "react";

const theme = {
  bg: "#0a0c10",
  surface: "#0f1318",
  border: "#1e2530",
  borderAccent: "#2a3540",
  arc: "#00d4ff",
  arcDim: "#00d4ff22",
  circle: "#4f8ef7",
  circleDim: "#4f8ef722",
  agent: "#a78bfa",
  agentDim: "#a78bfa22",
  seller: "#34d399",
  sellerDim: "#34d39922",
  text: "#e2e8f0",
  textMuted: "#64748b",
  textDim: "#94a3b8",
  warn: "#f59e0b",
};

const styles = `
  @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=IBM+Plex+Sans:wght@300;400;500;600&display=swap');

  * { box-sizing: border-box; margin: 0; padding: 0; }

  body {
    background: ${theme.bg};
    color: ${theme.text};
    font-family: 'IBM Plex Sans', sans-serif;
  }

  .root {
    min-height: 100vh;
    background: ${theme.bg};
    padding: 32px 24px;
    position: relative;
    overflow: hidden;
  }

  .root::before {
    content: '';
    position: fixed;
    top: -40%;
    left: -20%;
    width: 600px;
    height: 600px;
    background: radial-gradient(circle, ${theme.arcDim} 0%, transparent 70%);
    pointer-events: none;
    z-index: 0;
  }

  .root::after {
    content: '';
    position: fixed;
    bottom: -20%;
    right: -10%;
    width: 500px;
    height: 500px;
    background: radial-gradient(circle, ${theme.agentDim} 0%, transparent 70%);
    pointer-events: none;
    z-index: 0;
  }

  .content { position: relative; z-index: 1; max-width: 1100px; margin: 0 auto; }

  .header { margin-bottom: 36px; }

  .badge {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    background: ${theme.arcDim};
    border: 1px solid ${theme.arc}44;
    color: ${theme.arc};
    font-family: 'IBM Plex Mono', monospace;
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 0.15em;
    padding: 4px 10px;
    border-radius: 2px;
    text-transform: uppercase;
    margin-bottom: 16px;
  }

  .badge-dot {
    width: 6px; height: 6px;
    background: ${theme.arc};
    border-radius: 50%;
    animation: pulse 2s infinite;
  }

  @keyframes pulse {
    0%, 100% { opacity: 1; transform: scale(1); }
    50% { opacity: 0.4; transform: scale(0.7); }
  }

  .title {
    font-size: 28px;
    font-weight: 600;
    color: ${theme.text};
    letter-spacing: -0.02em;
    margin-bottom: 6px;
  }

  .title span { color: ${theme.arc}; }

  .subtitle {
    font-size: 13px;
    color: ${theme.textMuted};
    font-family: 'IBM Plex Mono', monospace;
  }

  /* LAYER SECTIONS */
  .layer {
    margin-bottom: 12px;
    border: 1px solid ${theme.border};
    border-radius: 6px;
    overflow: hidden;
    background: ${theme.surface};
  }

  .layer-header {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 10px 16px;
    border-bottom: 1px solid ${theme.border};
    cursor: pointer;
    user-select: none;
    transition: background 0.15s;
  }

  .layer-header:hover { background: #ffffff06; }

  .layer-label {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 0.12em;
    text-transform: uppercase;
  }

  .layer-desc {
    font-size: 11px;
    color: ${theme.textMuted};
    margin-left: auto;
    font-family: 'IBM Plex Mono', monospace;
  }

  .layer-chevron {
    margin-left: 8px;
    color: ${theme.textMuted};
    font-size: 10px;
    transition: transform 0.2s;
  }

  .layer-body {
    padding: 16px;
    display: grid;
    gap: 10px;
  }

  /* NODE CARDS */
  .nodes-row {
    display: flex;
    gap: 10px;
    flex-wrap: wrap;
  }

  .node {
    flex: 1;
    min-width: 160px;
    border-radius: 4px;
    padding: 12px 14px;
    border: 1px solid;
    position: relative;
    overflow: hidden;
    cursor: default;
    transition: transform 0.15s, box-shadow 0.15s;
  }

  .node:hover {
    transform: translateY(-1px);
    box-shadow: 0 4px 20px #00000040;
  }

  .node-icon { font-size: 18px; margin-bottom: 6px; }

  .node-name {
    font-size: 12px;
    font-weight: 600;
    margin-bottom: 3px;
  }

  .node-detail {
    font-size: 10px;
    font-family: 'IBM Plex Mono', monospace;
    color: ${theme.textMuted};
    line-height: 1.5;
  }

  .node-tag {
    display: inline-block;
    font-size: 9px;
    font-family: 'IBM Plex Mono', monospace;
    padding: 2px 5px;
    border-radius: 2px;
    margin-top: 6px;
    font-weight: 600;
    letter-spacing: 0.05em;
    text-transform: uppercase;
  }

  /* COLOR VARIANTS */
  .node-arc {
    background: ${theme.arcDim};
    border-color: ${theme.arc}44;
  }
  .node-arc .node-name { color: ${theme.arc}; }
  .node-arc .node-tag { background: ${theme.arc}22; color: ${theme.arc}; }

  .node-circle {
    background: ${theme.circleDim};
    border-color: ${theme.circle}44;
  }
  .node-circle .node-name { color: ${theme.circle}; }
  .node-circle .node-tag { background: ${theme.circle}22; color: ${theme.circle}; }

  .node-agent {
    background: ${theme.agentDim};
    border-color: ${theme.agent}44;
  }
  .node-agent .node-name { color: ${theme.agent}; }
  .node-agent .node-tag { background: ${theme.agent}22; color: ${theme.agent}; }

  .node-seller {
    background: ${theme.sellerDim};
    border-color: ${theme.seller}44;
  }
  .node-seller .node-name { color: ${theme.seller}; }
  .node-seller .node-tag { background: ${theme.seller}22; color: ${theme.seller}; }

  .node-neutral {
    background: #ffffff06;
    border-color: ${theme.border};
  }
  .node-neutral .node-name { color: ${theme.textDim}; }
  .node-neutral .node-tag { background: #ffffff0a; color: ${theme.textMuted}; }

  /* FLOW ARROWS */
  .flow-section {
    margin-bottom: 12px;
  }

  .flow-title {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 10px;
    color: ${theme.textMuted};
    letter-spacing: 0.1em;
    text-transform: uppercase;
    margin-bottom: 10px;
    padding-left: 4px;
    border-left: 2px solid ${theme.border};
    padding-left: 8px;
  }

  .flow-steps {
    display: flex;
    align-items: stretch;
    gap: 0;
    overflow-x: auto;
    padding-bottom: 4px;
  }

  .flow-step {
    display: flex;
    flex-direction: column;
    align-items: center;
    min-width: 110px;
  }

  .flow-box {
    border: 1px solid;
    border-radius: 4px;
    padding: 8px 10px;
    text-align: center;
    width: 100%;
  }

  .flow-num {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 9px;
    margin-bottom: 2px;
    font-weight: 600;
  }

  .flow-label {
    font-size: 10px;
    font-weight: 500;
    line-height: 1.3;
  }

  .flow-sub {
    font-size: 9px;
    font-family: 'IBM Plex Mono', monospace;
    color: ${theme.textMuted};
    margin-top: 2px;
  }

  .flow-arrow {
    display: flex;
    align-items: center;
    padding: 0 4px;
    margin-top: -20px;
  }

  .arrow-line {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 14px;
  }

  /* LEGEND */
  .legend {
    display: flex;
    gap: 20px;
    flex-wrap: wrap;
    padding: 12px 16px;
    background: ${theme.surface};
    border: 1px solid ${theme.border};
    border-radius: 4px;
    margin-top: 20px;
  }

  .legend-item {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 11px;
    color: ${theme.textDim};
  }

  .legend-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    flex-shrink: 0;
  }

  /* FOOTER */
  .footer {
    margin-top: 24px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    flex-wrap: gap;
    gap: 8px;
  }

  .footer-left {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 10px;
    color: ${theme.textMuted};
  }

  .footer-right {
    display: flex;
    gap: 12px;
  }

  .chip {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 9px;
    padding: 3px 8px;
    border-radius: 2px;
    font-weight: 600;
    letter-spacing: 0.08em;
    text-transform: uppercase;
  }

  .chip-arc { background: ${theme.arcDim}; color: ${theme.arc}; border: 1px solid ${theme.arc}33; }
  .chip-track { background: ${theme.agentDim}; color: ${theme.agent}; border: 1px solid ${theme.agent}33; }
  .chip-prize { background: ${theme.sellerDim}; color: ${theme.seller}; border: 1px solid ${theme.seller}33; }

  .divider {
    height: 1px;
    background: linear-gradient(90deg, transparent, ${theme.border}, transparent);
    margin: 8px 0;
  }

  .connector {
    display: flex;
    justify-content: center;
    align-items: center;
    height: 28px;
    position: relative;
  }

  .connector::before {
    content: '';
    position: absolute;
    left: 50%;
    top: 0;
    bottom: 0;
    width: 1px;
    background: linear-gradient(180deg, ${theme.border}, ${theme.borderAccent});
  }

  .connector-label {
    background: ${theme.surface};
    border: 1px solid ${theme.border};
    border-radius: 20px;
    padding: 2px 10px;
    font-size: 9px;
    font-family: 'IBM Plex Mono', monospace;
    color: ${theme.textMuted};
    position: relative;
    z-index: 1;
  }
`;

const layers = [
  {
    id: "consumer",
    label: "Consumer Layer",
    desc: "User + Autonomous Agent",
    color: theme.agent,
    nodes: [
      {
        type: "neutral",
        icon: "🖥️",
        name: "React Dashboard",
        detail: "Bloomberg terminal UI\nSSE agent log stream\nSignal explorer + governance",
        tag: "React + Vite + wagmi v2",
      },
      {
        type: "agent",
        icon: "💰",
        name: "User Wallet (MetaMask)",
        detail: "Connects via RainbowKit\nAny Arc testnet address\nDeposits USDC to their agent wallet",
        tag: "EIP-1193 / wagmi",
      },
      {
        type: "arc",
        icon: "🔑",
        name: "Per-User Key Derivation",
        detail: "HMAC-SHA256(userAddr, masterSeed)\nDeterministic — same user, same key\nBackend-side · never exposed",
        tag: "AGENT_MASTER_SEED",
      },
      {
        type: "agent",
        icon: "🤖",
        name: "Agent Wallet (per-user EOA)",
        detail: "Unique address per connected wallet\nHolds user's USDC budget on Arc\nSigns all EIP-3009 authorizations",
        tag: "Derived EOA",
      },
      {
        type: "agent",
        icon: "🧠",
        name: "LangGraph Buyer Agent",
        detail: "8-node graph\nDiscover → Select → Pay → Reputation\n→ Analyze → Execute → Loop",
        tag: "Python / LangGraph",
      },
    ],
  },
  {
    id: "payment",
    label: "Payment Layer",
    desc: "HTTP 402 → EIP-3009 → Circle settle",
    color: theme.arc,
    nodes: [
      {
        type: "arc",
        icon: "🔗",
        name: "HTTP 402 Gate",
        detail: "Every signal endpoint gated\nReturns 402 + X-Payment-Info header\nSignal locked until payment confirmed",
        tag: "x402 Protocol",
      },
      {
        type: "arc",
        icon: "✍️",
        name: "EIP-3009 Signing",
        detail: "TransferWithAuthorization\nEIP-712 typed data signature\nNonce: keccak256(uuid)",
        tag: "EIP-3009 / EIP-712",
      },
      {
        type: "circle",
        icon: "⚡",
        name: "Circle Facilitator",
        detail: "Verifies EIP-3009 signature\nSettles USDC on Arc\nReturns X-Payment-Response",
        tag: "Circle Gateway",
      },
    ],
  },
  {
    id: "backend",
    label: "Backend Layer",
    desc: "FastAPI + Arc + ERC-8004",
    color: theme.circle,
    nodes: [
      {
        type: "circle",
        icon: "🚀",
        name: "FastAPI Backend",
        detail: "Signal registry endpoints\nPayment verification\nSSE agent loop streaming",
        tag: "FastAPI / Python",
      },
      {
        type: "arc",
        icon: "📋",
        name: "ERC-8004 Registry",
        detail: "Identity / Reputation / Validation\nOn-chain provider reputation writes\nArc tx hash per signal call",
        tag: "Arc Smart Contracts",
      },
      {
        type: "arc",
        icon: "💎",
        name: "USDC on Arc",
        detail: "0x3600...0000\nSub-second finality\nChain ID 5042002",
        tag: "Arc L1 / USDC",
      },
    ],
  },
  {
    id: "signals",
    label: "Signal Provider Layer",
    desc: "6 live data sources",
    color: theme.seller,
    nodes: [
      {
        type: "seller",
        icon: "📡",
        name: "Whale Alert + Sentiment",
        detail: "Large on-chain transfers\nFear & Greed index\n$0.002 · $0.003 per call",
        tag: "Simulated / Live",
      },
      {
        type: "arc",
        icon: "🔮",
        name: "Price Oracle (Pyth)",
        detail: "BTC · ETH · SOL · USDC\nPyth Hermes REST API\nconf=0.99 · 15s TTL cache",
        tag: "Pyth Network",
      },
      {
        type: "seller",
        icon: "🎯",
        name: "Trade Signal + Wallet Score",
        detail: "Composite RSI/MACD signal\nOn-chain wallet risk tier\n$0.010 · $0.005 per call",
        tag: "Simulated / Live",
      },
      {
        type: "seller",
        icon: "🌾",
        name: "Yield Intel (DefiLlama)",
        detail: "USDC stablecoin pools\nAPY 0.1–50% · TVL > $5M\nTop 5 by yield · 300s cache",
        tag: "DefiLlama API",
      },
    ],
  },
];

const flowSteps = [
  { num: "01", label: "Read on-chain balance", sub: "Arc balanceOf", color: theme.agent },
  { num: "02", label: "Discover providers", sub: "/discovery/providers", color: theme.agent },
  { num: "03", label: "Select signal", sub: "LangGraph node", color: theme.agent },
  { num: "04", label: "← HTTP 402", sub: "Payment required", color: theme.arc },
  { num: "05", label: "EIP-3009 signed", sub: "Agent wallet key", color: theme.circle },
  { num: "06", label: "→ Retry + X-Payment", sub: "Circle settle", color: theme.arc },
  { num: "07", label: "Signal unlocked", sub: "FastAPI delivers", color: theme.circle },
  { num: "08", label: "ERC-8004 reputation", sub: "Arc tx write", color: theme.arc },
  { num: "09", label: "Analyze + execute", sub: "Action decision", color: theme.agent },
  { num: "10", label: "Loop / summarize", sub: "Next signal", color: theme.seller },
];

export default function SignalPayDiagram() {
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});

  const toggle = (id: string) => setCollapsed((s) => ({ ...s, [id]: !s[id] }));

  return (
    <>
      <style>{styles}</style>
      <div className="root">
        <div className="content">
          {/* HEADER */}
          <div className="header">
            <div className="badge">
              <div className="badge-dot" />
              Ignyte Challenge · Track 4 · Agentic Economy on Arc
            </div>
            <div className="title">
              Signal<span>Pay</span> — Architecture Overview
            </div>
            <div className="subtitle">
              AI Alpha Marketplace · HTTP 402 → EIP-3009 · Nanopayments · Arc L1
            </div>
          </div>

          {/* PAYMENT FLOW */}
          <div className="flow-section">
            <div className="flow-title">// Payment Flow — end to end</div>
            <div className="flow-steps">
              {flowSteps.map((step, i) => (
                <div key={i} style={{ display: "flex", alignItems: "center" }}>
                  <div className="flow-step">
                    <div
                      className="flow-box"
                      style={{
                        borderColor: step.color + "55",
                        background: step.color + "11",
                      }}
                    >
                      <div className="flow-num" style={{ color: step.color }}>
                        {step.num}
                      </div>
                      <div className="flow-label" style={{ color: theme.text }}>
                        {step.label}
                      </div>
                      <div className="flow-sub">{step.sub}</div>
                    </div>
                  </div>
                  {i < flowSteps.length - 1 && (
                    <div className="flow-arrow">
                      <span className="arrow-line" style={{ color: theme.border }}>
                        →
                      </span>
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>

          <div className="divider" />

          {/* LAYER NODES */}
          {layers.map((layer, li) => (
            <div key={layer.id}>
              <div className="layer">
                <div
                  className="layer-header"
                  onClick={() => toggle(layer.id)}
                >
                  <div
                    style={{
                      width: 3,
                      height: 16,
                      background: layer.color,
                      borderRadius: 2,
                      flexShrink: 0,
                    }}
                  />
                  <span
                    className="layer-label"
                    style={{ color: layer.color }}
                  >
                    {layer.label}
                  </span>
                  <span className="layer-desc">{layer.desc}</span>
                  <span className="layer-chevron">
                    {collapsed[layer.id] ? "▶" : "▼"}
                  </span>
                </div>
                {!collapsed[layer.id] && (
                  <div className="layer-body">
                    <div className="nodes-row">
                      {layer.nodes.map((node, ni) => (
                        <div key={ni} className={`node node-${node.type}`}>
                          <div className="node-icon">{node.icon}</div>
                          <div className="node-name">{node.name}</div>
                          <div className="node-detail" style={{ whiteSpace: "pre-line" }}>
                            {node.detail}
                          </div>
                          <div className="node-tag">{node.tag}</div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
              {li < layers.length - 1 && (
                <div className="connector">
                  <span className="connector-label">↓ data + value flow</span>
                </div>
              )}
            </div>
          ))}

          {/* WALLET FLOW CALLOUT */}
          <div style={{
            margin: "12px 0",
            padding: "14px 16px",
            background: theme.surface,
            border: `1px solid ${theme.borderAccent}`,
            borderRadius: 4,
            fontFamily: "'IBM Plex Mono', monospace",
            fontSize: 11,
          }}>
            <div style={{ color: theme.textMuted, fontSize: 10, letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: 12 }}>// Per-User Wallet Flow</div>

            {/* Derivation row */}
            <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", marginBottom: 12 }}>
              {[
                { label: "User Wallet", sub: "0xABC... (MetaMask)", color: theme.agent },
                { arrow: "─ HMAC-SHA256 ─▶\n(+ masterSeed)" },
                { label: "Agent Wallet", sub: "0xDEF... (derived, unique)", color: theme.arc },
                { arrow: "─ USDC.transfer ─▶\n(user deposits)" },
                { label: "Agent Balance", sub: "on-chain · Arc USDC", color: theme.arc },
              ].map((item, i) =>
                "arrow" in item ? (
                  <span key={i} style={{ color: theme.textMuted, fontSize: 9, whiteSpace: "pre", lineHeight: 1.4 }}>{item.arrow}</span>
                ) : (
                  <div key={i} style={{ padding: "6px 10px", border: `1px solid ${item.color}44`, borderRadius: 4, background: item.color + "11" }}>
                    <div style={{ color: item.color, fontWeight: 600, fontSize: 11 }}>{item.label}</div>
                    <div style={{ color: theme.textMuted, fontSize: 9, marginTop: 2 }}>{item.sub}</div>
                  </div>
                )
              )}
            </div>

            {/* Spend row */}
            <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", marginBottom: 10 }}>
              {[
                { label: "Agent Wallet", sub: "signs EIP-3009", color: theme.arc },
                { arrow: "─ x402 per signal call ─▶" },
                { label: "Provider Wallet", sub: "SignalPay · receives USDC fees", color: theme.seller },
                { arrow: "─ open to ─▶" },
                { label: "Any External Agent", sub: "bring your own key + USDC", color: theme.textDim },
              ].map((item, i) =>
                "arrow" in item ? (
                  <span key={i} style={{ color: theme.textMuted, fontSize: 10 }}>{item.arrow}</span>
                ) : (
                  <div key={i} style={{ padding: "6px 10px", border: `1px solid ${(item as any).color}44`, borderRadius: 4, background: (item as any).color + "11" }}>
                    <div style={{ color: (item as any).color, fontWeight: 600, fontSize: 11 }}>{item.label}</div>
                    <div style={{ color: theme.textMuted, fontSize: 9, marginTop: 2 }}>{item.sub}</div>
                  </div>
                )
              )}
            </div>

            <div style={{ color: theme.textMuted, fontSize: 9, borderTop: `1px solid ${theme.border}`, paddingTop: 8 }}>
              Each connected wallet gets a unique derived agent wallet via HMAC-SHA256(userAddress, masterSeed). Signal endpoints are open — any agent with USDC can pay and call. No shared pool.
            </div>
          </div>

          {/* LEGEND */}
          <div className="legend">
            {[
              { color: theme.arc, label: "Arc L1 / Settlement" },
              { color: theme.circle, label: "Circle / x402" },
              { color: theme.agent, label: "AI Agent Layer" },
              { color: theme.seller, label: "Signal Providers" },
              { color: theme.textMuted, label: "Frontend / Neutral" },
            ].map((l, i) => (
              <div key={i} className="legend-item">
                <div className="legend-dot" style={{ background: l.color }} />
                {l.label}
              </div>
            ))}
          </div>

          {/* FOOTER */}
          <div className="footer">
            <div className="footer-left">
              SignalPay v1 · Arc Testnet · Chain ID 5042002 · USDC 0x3600...0000
            </div>
            <div className="footer-right">
              <span className="chip chip-arc">Arc L1</span>
              <span className="chip chip-track">Track 4</span>
              <span className="chip chip-prize">$4,000 + $2,000 USDC</span>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
