import { AlertTriangle, ChevronRight, Loader2 } from "lucide-react";
import { fmt } from "@/lib/api";

export const Panel = ({ title, action, children, className = "", testId }) => (
  <section className={`panel ${className}`} data-testid={testId}>
    {(title || action) && (
      <header className="flex items-center justify-between border-b border-[#262626] px-4 py-2.5">
        <h3 className="label-caps">{title}</h3>
        {action}
      </header>
    )}
    {children}
  </section>
);

export const MetricCard = ({ label, value, unit, delta, deltaInverted, sub, onClick, testId }) => {
  const good = deltaInverted ? delta < 0 : delta > 0;
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={!onClick}
      data-testid={testId}
      className={`panel group flex w-full flex-col items-start gap-2 p-4 text-left transition-colors duration-150 ${
        onClick ? "hover:bg-[#1a1a1a] cursor-pointer" : "cursor-default"
      }`}
    >
      <div className="flex w-full items-center justify-between">
        <span className="label-caps">{label}</span>
        {onClick && (
          <ChevronRight className="h-3.5 w-3.5 text-[#525252] transition-transform duration-150 group-hover:translate-x-0.5 group-hover:text-white" />
        )}
      </div>
      <div className="flex items-baseline gap-1.5">
        <span className="num text-2xl font-medium tracking-tight">{value}</span>
        {unit && <span className="num text-xs text-[#a3a3a3]">{unit}</span>}
      </div>
      <div className="flex items-center gap-2">
        {delta !== null && delta !== undefined && (
          <span className={`num text-xs ${good ? "text-[#34C759]" : "text-[#FF3B30]"}`}>
            {fmt.delta(delta)}
          </span>
        )}
        {sub && <span className="text-xs text-[#a3a3a3]">{sub}</span>}
      </div>
    </button>
  );
};

const SCORE_COLOUR = (s) =>
  s >= 80 ? "border-[#34C759] text-[#34C759]" : s >= 50 ? "border-[#FFCC00] text-[#FFCC00]" : "border-[#FF3B30] text-[#FF3B30]";

export const ScorePill = ({ score, testId }) => (
  <span
    data-testid={testId}
    className={`num inline-flex min-w-[42px] justify-center border px-1.5 py-0.5 text-xs font-medium ${SCORE_COLOUR(score)}`}
  >
    {Number(score).toFixed(0)}
  </span>
);

const TIER_STYLE = {
  A: "bg-white text-black",
  B: "bg-[#007AFF] text-white",
  C: "bg-[#262626] text-[#d4d4d4]",
  D: "bg-transparent text-[#737373] border border-[#262626]",
};

export const TierBadge = ({ tier }) => (
  <span className={`num inline-flex h-5 w-5 items-center justify-center text-[11px] font-semibold ${TIER_STYLE[tier] || TIER_STYLE.D}`}>
    {tier}
  </span>
);

const SEV_STYLE = {
  critical: "bg-[#FF3B30] text-white",
  high: "bg-[#FF3B30]/15 text-[#FF6B62] border border-[#FF3B30]/40",
  medium: "bg-[#FFCC00]/15 text-[#FFCC00] border border-[#FFCC00]/40",
  low: "bg-[#262626] text-[#a3a3a3]",
};

export const SeverityBadge = ({ severity }) => (
  <span className={`px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider ${SEV_STYLE[severity] || SEV_STYLE.low}`}>
    {severity}
  </span>
);

export const Delta = ({ value, suffix = "%", inverted = false, decimals = 1 }) => {
  if (value === null || value === undefined) return <span className="text-[#525252]">—</span>;
  const good = inverted ? value < 0 : value > 0;
  return (
    <span className={`num text-xs ${value === 0 ? "text-[#a3a3a3]" : good ? "text-[#34C759]" : "text-[#FF3B30]"}`}>
      {value > 0 ? "+" : ""}
      {Number(value).toFixed(decimals)}
      {suffix}
    </span>
  );
};

export const Loading = ({ label = "Loading intelligence" }) => (
  <div className="flex items-center gap-2 p-8 text-sm text-[#a3a3a3]" data-testid="loading-state">
    <Loader2 className="h-4 w-4 animate-spin" />
    {label}…
  </div>
);

export const ErrorState = ({ error, onRetry }) => (
  <div className="panel flex flex-col items-start gap-3 p-6" data-testid="error-state">
    <div className="flex items-center gap-2 text-[#FF3B30]">
      <AlertTriangle className="h-4 w-4" />
      <span className="text-sm font-medium">Could not load this view</span>
    </div>
    <p className="text-xs text-[#a3a3a3]">{String(error?.message || error)}</p>
    {onRetry && (
      <button
        onClick={onRetry}
        data-testid="retry-button"
        className="border border-[#262626] px-3 py-1.5 text-xs transition-colors duration-150 hover:bg-[#262626]"
      >
        Retry
      </button>
    )}
  </div>
);

export const Empty = ({ label = "No records match the current filters", testId = "empty-state" }) => (
  <div className="p-8 text-sm text-[#737373]" data-testid={testId}>
    {label}
  </div>
);

export const DemoTag = ({ mode }) =>
  mode === "DEMO" ? (
    <span className="border border-[#FFCC00] px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-[#FFCC00]">
      demo
    </span>
  ) : null;

export const EvidenceRow = ({ label, value, mono = true }) => (
  <div className="flex items-start justify-between gap-4 border-b border-[#262626] py-2">
    <span className="label-caps pt-0.5">{label}</span>
    <span className={`${mono ? "num" : ""} max-w-[62%] break-words text-right text-xs text-[#f5f5f5]`}>
      {value ?? "—"}
    </span>
  </div>
);

export const ScoreBars = ({ components, weights }) => (
  <div className="space-y-2">
    {Object.entries(components || {}).map(([k, v]) => (
      <div key={k} className="space-y-1">
        <div className="flex items-center justify-between">
          <span className="text-xs capitalize text-[#a3a3a3]">
            {k.replace("_", " ")}
            <span className="num ml-1.5 text-[10px] text-[#525252]">
              w{weights?.[k] !== undefined ? Number(weights[k]).toFixed(2) : ""}
            </span>
          </span>
          <span className="num text-xs">{Number(v).toFixed(1)}</span>
        </div>
        <div className="h-1 w-full bg-[#262626]">
          <div className="h-1 bg-[#007AFF] transition-all duration-300" style={{ width: `${Math.min(100, v)}%` }} />
        </div>
      </div>
    ))}
  </div>
);
