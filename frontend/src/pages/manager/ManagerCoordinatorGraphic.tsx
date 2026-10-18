import React from "react";

interface NodeDef {
  id: string;
  label: string;
  subLabel?: string;
  angleDeg: number;
  radius: number;
  color: string;
  bgColor: string;
  icon: React.ReactNode;
}

const NODES: NodeDef[] = [
  {
    id: "campaign_strategist",
    label: "Campaign",
    subLabel: "Strategist",
    angleDeg: -115,
    radius: 172,
    color: "#e05a36",
    bgColor: "#ffebe5",
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <circle cx="12" cy="12" r="9" />
        <circle cx="12" cy="12" r="5" />
        <circle cx="12" cy="12" r="1.5" fill="currentColor" />
      </svg>
    ),
  },
  {
    id: "discovery",
    label: "Discovery",
    angleDeg: -80,
    radius: 172,
    color: "#00897b",
    bgColor: "#e0f2f1",
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <circle cx="12" cy="12" r="9" />
        <polygon points="16.24 7.76 14.12 14.12 7.76 16.24 9.88 9.88 16.24 7.76" fill="currentColor" fillOpacity="0.3" />
      </svg>
    ),
  },
  {
    id: "customer_intelligence",
    label: "Customer",
    subLabel: "Intelligence",
    angleDeg: -45,
    radius: 172,
    color: "#d97706",
    bgColor: "#fef3c7",
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" />
        <circle cx="9" cy="7" r="4" />
        <path d="M23 21v-2a4 4 0 0 0-3-3.87" />
        <path d="M16 3.13a4 4 0 0 1 0 7.75" />
      </svg>
    ),
  },
  {
    id: "revenue_optimization",
    label: "Revenue",
    subLabel: "Optimization",
    angleDeg: -10,
    radius: 172,
    color: "#16a34a",
    bgColor: "#dcfce7",
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <line x1="18" y1="20" x2="18" y2="10" />
        <line x1="12" y1="20" x2="12" y2="4" />
        <line x1="6" y1="20" x2="6" y2="14" />
      </svg>
    ),
  },
  {
    id: "payment_recovery",
    label: "Payment",
    subLabel: "Recovery",
    angleDeg: 25,
    radius: 172,
    color: "#9333ea",
    bgColor: "#f3e8ff",
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <rect x="2" y="5" width="20" height="14" rx="2" />
        <line x1="2" y1="10" x2="22" y2="10" />
      </svg>
    ),
  },
  {
    id: "experiment",
    label: "Experiment",
    angleDeg: 60,
    radius: 172,
    color: "#2563eb",
    bgColor: "#dbeafe",
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <path d="M10 2v7.527a2 2 0 0 1-.211.896L4.72 20.55a1 1 0 0 0 .9 1.45h12.76a1 1 0 0 0 .9-1.45l-5.069-10.127A2 2 0 0 1 14 9.527V2" />
        <line x1="8.5" y1="2" x2="15.5" y2="2" />
      </svg>
    ),
  },
  {
    id: "personalization",
    label: "Personalization",
    angleDeg: 95,
    radius: 172,
    color: "#059669",
    bgColor: "#d1fae5",
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <circle cx="12" cy="7" r="4" />
        <path d="M5.5 21a8.5 8.5 0 0 1 13 0" />
      </svg>
    ),
  },
  {
    id: "opportunity_prioritization",
    label: "Opportunity",
    subLabel: "Prioritization",
    angleDeg: 130,
    radius: 172,
    color: "#d97706",
    bgColor: "#fef3c7",
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <path d="M6 9H4.5a2.5 2.5 0 0 1 0-5H6" />
        <path d="M18 9h1.5a2.5 2.5 0 0 0 0-5H18" />
        <path d="M4 22h16" />
        <path d="M10 14.66V17c0 .55-.45 1-1 1H8c-.55 0-1 .45-1 1v1h10v-1c0-.55-.45-1-1-1h-1c-.55 0-1-.45-1-1v-2.34" />
        <path d="M6 4h12v6a6 6 0 0 1-12 0V4z" />
      </svg>
    ),
  },
  {
    id: "memory",
    label: "Memory",
    angleDeg: 165,
    radius: 172,
    color: "#0284c7",
    bgColor: "#e0f2fe",
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <ellipse cx="12" cy="5" rx="9" ry="3" />
        <path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3" />
        <path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5" />
      </svg>
    ),
  },
  {
    id: "software",
    label: "Software",
    angleDeg: 200,
    radius: 172,
    color: "#0d9488",
    bgColor: "#ccfbf1",
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <polyline points="16 18 22 12 16 6" />
        <polyline points="8 6 2 12 8 18" />
      </svg>
    ),
  },
  {
    id: "designer",
    label: "Designer",
    angleDeg: 235,
    radius: 172,
    color: "#7c3aed",
    bgColor: "#ede9fe",
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10c1.38 0 2.5-1.12 2.5-2.5 0-.61-.23-1.21-.64-1.67-.4-.46-.64-1.06-.64-1.67 0-1.38 1.12-2.5 2.5-2.5H18c2.21 0 4-1.79 4-4 0-5.52-4.48-9.66-10-9.66z" />
        <circle cx="6.5" cy="11.5" r="1.5" fill="currentColor" />
        <circle cx="9.5" cy="7.5" r="1.5" fill="currentColor" />
        <circle cx="14.5" cy="7.5" r="1.5" fill="currentColor" />
      </svg>
    ),
  },
  {
    id: "product",
    label: "Product",
    angleDeg: 270,
    radius: 172,
    color: "#ea580c",
    bgColor: "#ffedd5",
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z" />
        <polyline points="3.27 6.96 12 12.01 20.73 6.96" />
        <line x1="12" y1="22.08" x2="12" y2="12" />
      </svg>
    ),
  },
  {
    id: "marketing",
    label: "Marketing",
    angleDeg: -145,
    radius: 172,
    color: "#dc2626",
    bgColor: "#fee2e2",
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <path d="m3 11 18-5v12L3 13v-2z" />
        <path d="M11.6 16.8a3 3 0 1 1-5.8-1.6" />
      </svg>
    ),
  },
];

export function ManagerCoordinatorGraphic() {
  const cx = 220;
  const cy = 220;

  return (
    <div className="manager-coordinator" aria-label="Manager Agent coordination diagram">
      <svg
        viewBox="0 0 440 440"
        className="manager-coordinator__svg"
        role="img"
        aria-hidden="true"
      >
        <defs>
          {/* Subtle warm halo behind coordinator */}
          <radialGradient id="mgrHalo" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor="#ff9a62" stopOpacity="0.4" />
            <stop offset="45%" stopColor="#f7c59f" stopOpacity="0.2" />
            <stop offset="100%" stopColor="#fff8ed" stopOpacity="0" />
          </radialGradient>
          {/* Radial glow for center button */}
          <radialGradient id="centerGlow" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor="#ffe8cc" />
            <stop offset="70%" stopColor="#ffd8a8" />
            <stop offset="100%" stopColor="#fbc286" />
          </radialGradient>
          {/* Crown gold gradient */}
          <linearGradient id="crownGold" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor="#fbbf24" />
            <stop offset="100%" stopColor="#f59e0b" />
          </linearGradient>
        </defs>

        {/* Outer radial ambient glow & backdrop to keep labels crisp over the illustrated world */}
        <circle cx={cx} cy={cy} r={218} fill="#fff9f0" fillOpacity="0.82" />
        <circle cx={cx} cy={cy} r={210} fill="url(#mgrHalo)" />

        {/* Concentric subtle guide rings */}
        <circle cx={cx} cy={cy} r={172} fill="none" stroke="#f0d5be" strokeWidth="1" strokeDasharray="3 3" opacity="0.6" />
        <circle cx={cx} cy={cy} r={110} fill="none" stroke="#f3d8c3" strokeWidth="1" opacity="0.4" />

        {/* Connecting lines from center to each node */}
        {NODES.map((node) => {
          const rad = (node.angleDeg * Math.PI) / 180;
          const nx = cx + node.radius * Math.cos(rad);
          const ny = cy + node.radius * Math.sin(rad);
          return (
            <line
              key={`line-${node.id}`}
              x1={cx}
              y1={cy}
              x2={nx}
              y2={ny}
              stroke="#e28743"
              strokeWidth="1.2"
              strokeOpacity="0.75"
            />
          );
        })}

        {/* Center Node: Manager Agent */}
        <g className="manager-center-node">
          {/* Orange pulsing ring */}
          <circle cx={cx} cy={cy} r={56} fill="#ffebd4" stroke="#e07a4a" strokeWidth="1.5" />
          <circle cx={cx} cy={cy} r={46} fill="url(#centerGlow)" stroke="#f7a06d" strokeWidth="2" />

          {/* Crown */}
          <path
            d={`M ${cx - 16} ${cy - 22} L ${cx - 10} ${cy - 34} L ${cx} ${cy - 26} L ${cx + 10} ${cy - 34} L ${cx + 16} ${cy - 22} Z`}
            fill="url(#crownGold)"
            stroke="#b45309"
            strokeWidth="1"
          />
          <circle cx={cx - 10} cy={cy - 34} r="2" fill="#d97706" />
          <circle cx={cx} cy={cy - 26} r="2" fill="#d97706" />
          <circle cx={cx + 10} cy={cy - 34} r="2" fill="#d97706" />

          {/* Robot Head */}
          <rect
            x={cx - 24}
            y={cy - 20}
            width="48"
            height="38"
            rx="12"
            fill="#2c1710"
            stroke="#e07a4a"
            strokeWidth="2"
          />
          {/* Robot Eyes (Warm glowing amber) */}
          <ellipse cx={cx - 10} cy={cy - 3} rx="4" ry="5" fill="#f59e0b" />
          <ellipse cx={cx + 10} cy={cy - 3} rx="4" ry="5" fill="#f59e0b" />
          {/* Eye reflections */}
          <circle cx={cx - 9} cy={cy - 5} r="1.5" fill="#fff" />
          <circle cx={cx + 11} cy={cy - 5} r="1.5" fill="#fff" />
          {/* Robot Mouth / Smile line */}
          <path d={`M ${cx - 8} ${cy + 7} Q ${cx} ${cy + 11} ${cx + 8} ${cy + 7}`} fill="none" stroke="#f59e0b" strokeWidth="1.8" strokeLinecap="round" />

          {/* Dark Pill Badge: Manager Agent */}
          <rect
            x={cx - 65}
            y={cy + 22}
            width="130"
            height="26"
            rx="13"
            fill="#1c110b"
            stroke="#e07a4a"
            strokeWidth="1.2"
          />
          <text
            x={cx}
            y={cy + 35}
            textAnchor="middle"
            fill="#fff9f0"
            fontFamily="'Archivo Variable', sans-serif"
            fontSize="10.5"
            fontWeight="700"
          >
            Manager Agent
          </text>
          <text
            x={cx}
            y={cy + 44}
            textAnchor="middle"
            fill="#f7be92"
            fontFamily="'IBM Plex Mono', monospace"
            fontSize="6.5"
            fontWeight="500"
            letterSpacing="0.3"
          >
            Orchestrates • Plans • Coordinates
          </text>
        </g>

        {/* 12 Specialist Agent Nodes */}
        {NODES.map((node) => {
          const rad = (node.angleDeg * Math.PI) / 180;
          const nx = cx + node.radius * Math.cos(rad);
          const ny = cy + node.radius * Math.sin(rad);

          // Calculate text label offset so it doesn't collide with the node circle
          const isTop = ny < cy;
          const textOffsetY = isTop ? -20 : 25;

          return (
            <g key={`node-${node.id}`} className="specialist-node-item">
              {/* Outer circle shadow / ring */}
              <circle cx={nx} cy={ny} r={17} fill="#fff9f0" stroke="#f29559" strokeWidth="1.5" />
              <circle cx={nx} cy={ny} r={14} fill={node.bgColor} />

              {/* Icon */}
              <foreignObject x={nx - 9} y={ny - 9} width="18" height="18">
                <div
                  style={{
                    width: 18,
                    height: 18,
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    color: node.color,
                  }}
                >
                  {node.icon}
                </div>
              </foreignObject>

              {/* Node Labels */}
              {node.subLabel ? (
                <>
                  <text
                    x={nx}
                    y={ny + (isTop ? -24 : 24)}
                    textAnchor="middle"
                    fill="#2a1810"
                    fontFamily="'Archivo Variable', sans-serif"
                    fontSize="9.5"
                    fontWeight="700"
                  >
                    {node.label}
                  </text>
                  <text
                    x={nx}
                    y={ny + (isTop ? -14 : 34)}
                    textAnchor="middle"
                    fill="#2a1810"
                    fontFamily="'Archivo Variable', sans-serif"
                    fontSize="9.5"
                    fontWeight="700"
                  >
                    {node.subLabel}
                  </text>
                </>
              ) : (
                <text
                  x={nx}
                  y={ny + textOffsetY}
                  textAnchor="middle"
                  fill="#2a1810"
                  fontFamily="'Archivo Variable', sans-serif"
                  fontSize="9.5"
                  fontWeight="700"
                >
                  {node.label}
                </text>
              )}
            </g>
          );
        })}
      </svg>
    </div>
  );
}
