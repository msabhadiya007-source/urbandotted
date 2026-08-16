import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { ArrowUpRight } from "lucide-react";
import { PageHeader, ActivityDot, StageNotice } from "@/components/Layout";
import {
  Delta, Empty, ErrorState, Loading, MetricCard, Panel, ScorePill, TierBadge,
} from "@/components/ui-kit";
import { fmt, get } from "@/lib/api";

const chartAxis = { stroke: "#525252", fontSize: 10, fontFamily: "JetBrains Mono" };

export default function Overview() {
  const navigate = useNavigate();
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ["overview"],
    queryFn: () => get("/overview"),
  });

  if (isLoading) return <Loading label="Aggregating AU + NZ signals" />;
  if (error) return <div className="p-6"><ErrorState error={error} onRetry={refetch} /></div>;

  const au = data.markets.find((m) => m.market === "AU") || {};
  const nz = data.markets.find((m) => m.market === "NZ") || {};
  const combinedClicks = data.markets.reduce((a, m) => a + m.clicks, 0);
  const combinedImpr = data.markets.reduce((a, m) => a + m.impressions, 0);
  const marketChart = data.markets.map((m) => ({
    market: m.market, clicks: m.clicks, impressions: m.impressions,
  }));

  return (
    <div>
      <PageHeader
        title="Overview"
        testId="overview-title"
        description="Combined AU + NZ organic intelligence. Every figure below is computed from ingested GSC rows joined to the Shopify catalogue — no invented metrics."
        right={
          <div className="panel px-4 py-2">
            <span className="label-caps">SEO health</span>
            <p className="num text-2xl">{fmt.dec(data.seo_health_score)}<span className="text-xs text-[#a3a3a3]">/100</span></p>
          </div>
        }
      />

      <div className="space-y-6 p-4 sm:p-6">
        <StageNotice />

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <MetricCard label="Organic clicks (30d)" value={fmt.int(combinedClicks)} delta={au.clicks_delta_pct}
            sub="AU + NZ" onClick={() => navigate("/keywords")} testId="metric-clicks" />
          <MetricCard label="Impressions (30d)" value={fmt.int(combinedImpr)} delta={au.impressions_delta_pct}
            sub="AU + NZ" onClick={() => navigate("/keywords")} testId="metric-impressions" />
          <MetricCard label="Blended CTR" value={fmt.pct((combinedClicks / combinedImpr) * 100, 2)}
            sub="clicks ÷ impressions" onClick={() => navigate("/opportunities")} testId="metric-ctr" />
          <MetricCard label="Paid API spend" value={fmt.usd(data.cost.spend_usd)}
            sub={`of ${fmt.usd(data.cost.global_cap_usd, 0)} cap · ${fmt.pct(data.cost.pct_used)}`}
            onClick={() => navigate("/cost")} testId="metric-cost" />
        </div>

        <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
          {[au, nz].map((m) => (
            <Panel key={m.market} title={`${m.market} market`} testId={`market-panel-${m.market}`}
              action={
                <button onClick={() => navigate(`/war-room/${m.market}`)} data-testid={`open-warroom-${m.market}`}
                  className="flex items-center gap-1 text-xs text-[#007AFF] transition-colors duration-150 hover:text-white">
                  War Room <ArrowUpRight className="h-3 w-3" />
                </button>
              }>
              <dl className="grid grid-cols-2 gap-px bg-[#262626]">
                {[
                  ["Clicks", fmt.int(m.clicks), m.clicks_delta_pct, false],
                  ["Impressions", fmt.int(m.impressions), m.impressions_delta_pct, false],
                  ["CTR", fmt.pct(m.ctr, 2), null, false],
                  ["Avg position", fmt.dec(m.avg_position), m.position_delta, true],
                ].map(([k, v, d, inv]) => (
                  <div key={k} className="bg-[#141414] p-3.5">
                    <dt className="label-caps">{k}</dt>
                    <dd className="num mt-1 text-lg">{v}</dd>
                    {d !== null && <Delta value={d} suffix={inv ? "" : "%"} inverted={false} />}
                  </div>
                ))}
              </dl>
            </Panel>
          ))}

          <Panel title="Clicks by market" testId="market-chart">
            <div className="h-[196px] min-h-[196px] p-3">
              <ResponsiveContainer width="100%" height="100%" minHeight={170}>
                <LineChart data={marketChart}>
                  <CartesianGrid stroke="#262626" vertical={false} />
                  <XAxis dataKey="market" {...chartAxis} tickLine={false} />
                  <YAxis {...chartAxis} tickLine={false} width={46} />
                  <Tooltip contentStyle={{ background: "#141414", border: "1px solid #262626", fontSize: 11 }} />
                  <Line type="monotone" dataKey="clicks" stroke="#34C759" strokeWidth={2} dot />
                  <Line type="monotone" dataKey="impressions" stroke="#007AFF" strokeWidth={1} dot />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </Panel>
        </div>

        <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
          <Panel title="Dynamic tier distribution" testId="tier-distribution"
            action={<span className="text-[10px] text-[#525252]">recomputed by percentile rank</span>}>
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-[#262626] text-left">
                  {["Tier", "Total", "AU", "NZ"].map((h) => (
                    <th key={h} className="label-caps px-4 py-2 last:text-right">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.tier_distribution.map((t) => (
                  <tr key={t.tier} className="row-hover cursor-pointer border-b border-[#262626] last:border-0"
                    onClick={() => navigate(`/opportunities?tier=${t.tier}`)} data-testid={`tier-row-${t.tier}`}>
                    <td className="px-4 py-2"><TierBadge tier={t.tier} /></td>
                    <td className="num px-4 py-2">{fmt.int(t.total)}</td>
                    <td className="num px-4 py-2">{fmt.int(t.AU)}</td>
                    <td className="num px-4 py-2 text-right">{fmt.int(t.NZ)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Panel>

          <Panel title="Open technical issues" testId="issues-summary"
            action={
              <button onClick={() => navigate("/technical")} data-testid="open-technical"
                className="text-xs text-[#007AFF] transition-colors duration-150 hover:text-white">Drill down</button>
            }>
            <div className="grid grid-cols-2 gap-px bg-[#262626]">
              {["critical", "high", "medium", "low"].map((sev) => (
                <button key={sev} onClick={() => navigate(`/technical?severity=${sev}`)}
                  data-testid={`issue-severity-${sev}`}
                  className="bg-[#141414] p-3.5 text-left transition-colors duration-150 hover:bg-[#1d1d1d]">
                  <span className="label-caps">{sev}</span>
                  <p className={`num mt-1 text-xl ${sev === "critical" ? "text-[#FF3B30]" : sev === "high" ? "text-[#FF6B62]" : ""}`}>
                    {fmt.int(data.open_issues_by_severity[sev] || 0)}
                  </p>
                </button>
              ))}
            </div>
          </Panel>

          <Panel title="Competitor movement (30d share)" testId="competitor-movement">
            {data.competitor_movements.length === 0 ? <Empty /> : (
              <ul>
                {data.competitor_movements.map((c) => (
                  <li key={`${c.domain}${c.market}`} className="row-hover flex items-center justify-between border-b border-[#262626] px-4 py-2 last:border-0">
                    <span className="num truncate text-xs">{c.domain}</span>
                    <span className="flex shrink-0 items-center gap-3">
                      <span className="label-caps">{c.market}</span>
                      <span className="num text-xs">{fmt.pct(c.visibility_share)}</span>
                      <Delta value={c.share_delta_30d} />
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </Panel>
        </div>

        <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1.4fr_1fr]">
          <Panel title="Top opportunities" testId="top-opportunities"
            action={
              <button onClick={() => navigate("/opportunities")} data-testid="open-opportunities"
                className="text-xs text-[#007AFF] transition-colors duration-150 hover:text-white">Full queue</button>
            }>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[620px] text-sm">
                <thead>
                  <tr className="border-b border-[#262626] text-left">
                    {["Score", "Tier", "Entity", "Type", "Market", "Impr 30d", "Pos"].map((h) => (
                      <th key={h} className="label-caps whitespace-nowrap px-3 py-2">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {data.top_opportunities.map((o) => (
                    <tr key={o.id} className="row-hover cursor-pointer border-b border-[#262626] last:border-0"
                      onClick={() => navigate(`/opportunities?focus=${o.id}`)} data-testid={`overview-opportunity-${o.id}`}>
                      <td className="px-3 py-2"><ScorePill score={o.score} /></td>
                      <td className="px-3 py-2"><TierBadge tier={o.tier} /></td>
                      <td className="max-w-[240px] truncate px-3 py-2 text-xs">{o.entity_label}</td>
                      <td className="px-3 py-2 text-xs text-[#a3a3a3]">{o.entity_type}</td>
                      <td className="label-caps px-3 py-2">{o.market}</td>
                      <td className="num px-3 py-2 text-xs">{fmt.int(o.evidence?.impressions_30d)}</td>
                      <td className="num px-3 py-2 text-xs">{fmt.dec(o.evidence?.avg_position)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>

          <Panel title="Agent activity" testId="overview-activity"
            action={
              <button onClick={() => navigate("/ai-operations")} data-testid="open-ai-operations"
                className="text-xs text-[#007AFF] transition-colors duration-150 hover:text-white">
                {data.agent_roles.total} roles
              </button>
            }>
            <ul>
              {data.recent_activity.map((a) => (
                <li key={a.id} className="flex items-center justify-between gap-3 border-b border-[#262626] px-4 py-2 last:border-0">
                  <span className="flex min-w-0 items-center gap-2">
                    <ActivityDot status={a.status} />
                    <span className="num truncate text-xs">{a.job}</span>
                  </span>
                  <span className="shrink-0 text-[11px] text-[#737373]">{fmt.ago(a.started_at)}</span>
                </li>
              ))}
            </ul>
            <div className="grid grid-cols-3 gap-px border-t border-[#262626] bg-[#262626]">
              {[["Products", data.catalog.products], ["Keywords", data.catalog.keywords], ["GSC rows", data.catalog.gsc_rows]].map(([k, v]) => (
                <div key={k} className="bg-[#141414] p-3">
                  <span className="label-caps">{k}</span>
                  <p className="num mt-0.5 text-sm">{fmt.int(v)}</p>
                </div>
              ))}
            </div>
          </Panel>
        </div>
      </div>
    </div>
  );
}
