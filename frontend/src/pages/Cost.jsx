import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Cell, Pie, PieChart, ResponsiveContainer } from "recharts";
import { toast } from "sonner";
import { PageHeader } from "@/components/Layout";
import { Empty, ErrorState, Loading, MetricCard, Panel } from "@/components/ui-kit";
import { fmt, get, post } from "@/lib/api";

const THRESHOLD_COLOUR = (pct) =>
  pct >= 100 ? "#FF3B30" : pct >= 90 ? "#FF3B30" : pct >= 75 ? "#FFCC00" : pct >= 50 ? "#007AFF" : "#34C759";

function Gauge({ pct }) {
  const capped = Math.min(100, pct);
  const data = [{ value: capped }, { value: 100 - capped }];
  return (
    <div className="relative h-[150px] min-h-[150px]">
      <ResponsiveContainer width="100%" height="100%" minHeight={130}>
        <PieChart>
          <Pie data={data} dataKey="value" startAngle={180} endAngle={0} innerRadius={62} outerRadius={86}
            cx="50%" cy="92%" stroke="none">
            <Cell fill={THRESHOLD_COLOUR(pct)} />
            <Cell fill="#262626" />
          </Pie>
        </PieChart>
      </ResponsiveContainer>
      <div className="absolute inset-x-0 bottom-2 text-center">
        <p className="num text-3xl">{fmt.pct(pct)}</p>
        <p className="label-caps">of monthly cap</p>
      </div>
    </div>
  );
}

export default function Cost() {
  const qc = useQueryClient();
  const [reason, setReason] = useState("");
  const [cap, setCap] = useState("");
  const { data, isLoading, error, refetch } = useQuery({ queryKey: ["cost"], queryFn: () => get("/cost/summary") });
  const ledger = useQuery({ queryKey: ["cost-ledger"], queryFn: () => get("/cost/ledger", { limit: 25 }) });

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["cost"] });
    qc.invalidateQueries({ queryKey: ["cost-ledger"] });
  };

  const exhaust = useMutation({
    mutationFn: () => post("/cost/simulate-exhaustion"),
    onSuccess: (r) => {
      toast.success(
        `Paid calls blocked: ${r.paid_calls_blocked} · free pipelines continue: ${r.free_pipelines_continue}`
      );
      invalidate();
    },
    onError: () => toast.error("Simulation failed"),
  });

  const reset = useMutation({
    mutationFn: () => post("/cost/reset-test-charges"),
    onSuccess: (r) => {
      toast.success(`Removed ${r.removed} test charges`);
      invalidate();
    },
  });

  const override = useMutation({
    mutationFn: () => post("/cost/override", { reason, global_cap_usd: cap ? Number(cap) : null }),
    onSuccess: () => {
      toast.success("Override applied and written to the audit log");
      setReason("");
      setCap("");
      invalidate();
    },
    onError: (e) => toast.error(e.response?.data?.detail || "Override rejected"),
  });

  if (isLoading) return <Loading label="Reading cost ledger" />;
  if (error) return <div className="p-6"><ErrorState error={error} onRetry={refetch} /></div>;

  return (
    <div>
      <PageHeader
        title="Cost"
        testId="cost-title"
        description="Every paid call is intercepted by the CostLedger. Per-provider caps sit under a global monthly ceiling. At 100% non-critical paid calls fail closed while the free pipelines (Shopify, GSC, crawler) keep running."
        right={
          <div className="flex flex-wrap gap-2">
            <button onClick={() => exhaust.mutate()} disabled={exhaust.isPending} data-testid="simulate-exhaustion-button"
              className="border border-[#FF3B30]/50 px-3 py-1.5 text-xs text-[#FF6B62] transition-colors duration-150 hover:bg-[#FF3B30]/10 disabled:opacity-50">
              Force budget to 100%
            </button>
            <button onClick={() => reset.mutate()} disabled={reset.isPending} data-testid="reset-charges-button"
              className="border border-[#262626] px-3 py-1.5 text-xs transition-colors duration-150 hover:bg-[#262626] disabled:opacity-50">
              Clear test charges
            </button>
          </div>
        }
      />

      <div className="space-y-4 p-4 sm:p-6">
        {data.halted && (
          <div className="border border-[#FF3B30] bg-[#FF3B30]/10 px-4 py-2.5 text-xs text-[#FF6B62]" data-testid="budget-halted-banner">
            BUDGET EXHAUSTED — non-critical paid calls are failing closed. Free pipelines (Shopify sync, GSC
            ingest, crawler) continue to run.
          </div>
        )}

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <MetricCard label="Spend this month" value={fmt.usd(data.spend_usd)} sub={`cap ${fmt.usd(data.global_cap_usd, 0)}`} testId="cost-metric-spend" />
          <MetricCard label="Forecast month end" value={fmt.usd(data.forecast_month_end_usd)}
            sub={data.forecast_month_end_usd > data.global_cap_usd ? "over cap trajectory" : "within cap"} testId="cost-metric-forecast" />
          <MetricCard label="Saved by cache" value={fmt.usd(data.saved_by_cache_usd, 4)} sub="deduped provider calls" testId="cost-metric-cache" />
          <MetricCard label="Budget-blocked calls" value={fmt.int(data.blocked_calls)} sub="failed closed" testId="cost-metric-blocked" />
        </div>

        <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1fr_1.3fr]">
          <Panel title="Global budget" testId="budget-gauge">
            <Gauge pct={data.pct_used} />
            <div className="grid grid-cols-4 gap-px border-t border-[#262626] bg-[#262626]">
              {data.thresholds.map((t) => (
                <div key={t} className={`bg-[#141414] p-2.5 text-center ${data.pct_used >= t ? "text-[#FFCC00]" : "text-[#525252]"}`}>
                  <p className="num text-sm">{t}%</p>
                  <p className="text-[10px]">{data.pct_used >= t ? "fired" : "armed"}</p>
                </div>
              ))}
            </div>
            <p className="px-4 py-2.5 text-[11px] text-[#a3a3a3]">
              Alert level {data.alert_level}% · remaining {fmt.usd(data.remaining_usd)}
            </p>
          </Panel>

          <Panel title="Spend by provider" testId="spend-by-provider">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-[#262626] text-left">
                  {["Provider", "Calls", "Spend", "Cap", "Used"].map((h) => (
                    <th key={h} className="label-caps px-4 py-2">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.by_provider.map((p) => {
                  const used = p.cap_usd ? (p.spend_usd / p.cap_usd) * 100 : 0;
                  return (
                    <tr key={p.provider} className="row-hover border-b border-[#262626] last:border-0" data-testid={`provider-row-${p.provider}`}>
                      <td className="px-4 py-2 text-xs">{p.provider}</td>
                      <td className="num px-4 py-2 text-xs">{fmt.int(p.calls)}</td>
                      <td className="num px-4 py-2 text-xs">{fmt.usd(p.spend_usd, 4)}</td>
                      <td className="num px-4 py-2 text-xs text-[#a3a3a3]">{fmt.usd(p.cap_usd, 0)}</td>
                      <td className="px-4 py-2">
                        <div className="h-1 w-20 bg-[#262626]">
                          <div className="h-1" style={{ width: `${Math.min(100, used)}%`, background: THRESHOLD_COLOUR(used) }} />
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </Panel>
        </div>

        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <Panel title="Spend by agent role" testId="spend-by-agent">
            {data.by_agent.length === 0 ? <Empty /> : (
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-[#262626] text-left">
                    {["Agent role", "Calls", "Tokens in", "Tokens out", "Spend"].map((h) => (
                      <th key={h} className="label-caps px-4 py-2">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {data.by_agent.map((a) => (
                    <tr key={a.agent_role} className="row-hover border-b border-[#262626] last:border-0">
                      <td className="px-4 py-2 text-xs">{a.agent_role}</td>
                      <td className="num px-4 py-2 text-xs">{fmt.int(a.calls)}</td>
                      <td className="num px-4 py-2 text-xs">{fmt.int(a.tokens_in)}</td>
                      <td className="num px-4 py-2 text-xs">{fmt.int(a.tokens_out)}</td>
                      <td className="num px-4 py-2 text-xs">{fmt.usd(a.spend_usd, 4)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Panel>

          <Panel title="Manual override (reason is logged)" testId="override-panel">
            <div className="space-y-3 p-4">
              <div>
                <label className="label-caps">New global cap (USD)</label>
                <input value={cap} onChange={(e) => setCap(e.target.value)} placeholder={String(data.global_cap_usd)}
                  data-testid="override-cap-input"
                  className="num mt-1.5 w-full border border-[#262626] bg-[#0a0a0a] px-3 py-2 text-xs outline-none focus:border-[#007AFF]" />
              </div>
              <div>
                <label className="label-caps">Reason (required)</label>
                <textarea value={reason} onChange={(e) => setReason(e.target.value)} rows={2}
                  data-testid="override-reason-input"
                  className="mt-1.5 w-full border border-[#262626] bg-[#0a0a0a] px-3 py-2 text-xs outline-none focus:border-[#007AFF]" />
              </div>
              <button onClick={() => override.mutate()} disabled={!reason.trim() || override.isPending}
                data-testid="override-submit-button"
                className="w-full bg-white px-3 py-2 text-xs font-medium text-black transition-colors duration-150 hover:bg-[#d4d4d4] disabled:opacity-40">
                Apply override
              </button>
              {data.overrides?.length > 0 && (
                <ul className="space-y-1.5 border-t border-[#262626] pt-3">
                  {data.overrides.slice(-4).reverse().map((o, i) => (
                    <li key={i} className="text-[11px] text-[#a3a3a3]">
                      <span className="num text-[#f5f5f5]">{fmt.time(o.at)}</span> · {o.actor} ·{" "}
                      {o.new_global_cap ? `cap → ${fmt.usd(o.new_global_cap, 0)}` : "caps unchanged"} · {o.reason}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </Panel>
        </div>

        <Panel title="Ledger entries (this month)" testId="ledger-panel">
          {ledger.isLoading ? <Loading /> : ledger.data?.rows?.length === 0 ? <Empty /> : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[640px] text-sm">
                <thead>
                  <tr className="border-b border-[#262626] text-left">
                    {["When", "Provider", "Operation", "Agent", "Status", "Cost"].map((h) => (
                      <th key={h} className="label-caps whitespace-nowrap px-3 py-2">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {ledger.data?.rows?.map((r) => (
                    <tr key={r.id} className="row-hover border-b border-[#262626] last:border-0">
                      <td className="num px-3 py-2 text-[11px] text-[#737373]">{fmt.ago(r.created_at)}</td>
                      <td className="px-3 py-2 text-xs">{r.provider}</td>
                      <td className="num px-3 py-2 text-[11px]">{r.operation}</td>
                      <td className="px-3 py-2 text-[11px] text-[#a3a3a3]">{r.agent_role || "—"}</td>
                      <td className="px-3 py-2">
                        <span className={`text-[10px] font-semibold uppercase ${
                          r.status === "blocked" ? "text-[#FF3B30]" : r.status === "cache_hit" ? "text-[#34C759]" : "text-[#a3a3a3]"
                        }`}>{r.status}</span>
                      </td>
                      <td className="num px-3 py-2 text-xs">{fmt.usd(r.cost_usd, 5)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Panel>
      </div>
    </div>
  );
}
