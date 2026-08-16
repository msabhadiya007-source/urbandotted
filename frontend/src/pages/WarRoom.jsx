import { useQuery } from "@tanstack/react-query";
import { useParams, useNavigate } from "react-router-dom";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { PageHeader } from "@/components/Layout";
import {
  Delta, Empty, ErrorState, Loading, MetricCard, Panel, ScorePill, TierBadge,
} from "@/components/ui-kit";
import { fmt, get } from "@/lib/api";

const axis = { stroke: "#525252", fontSize: 10, fontFamily: "JetBrains Mono" };
const LABELS = { top_3: "1–3", "4_10": "4–10", "11_20": "11–20", "21_50": "21–50", "50_plus": "50+" };

export default function WarRoom() {
  const { market } = useParams();
  const navigate = useNavigate();
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ["warroom", market],
    queryFn: () => get(`/markets/${market}/warroom`),
  });

  if (isLoading) return <Loading label={`Loading ${market} war room`} />;
  if (error) return <div className="p-6"><ErrorState error={error} onRetry={refetch} /></div>;

  const t = data.totals;
  const dist = Object.entries(data.position_distribution).map(([k, v]) => ({ bucket: LABELS[k] || k, queries: v }));
  const top3Share = (data.position_distribution.top_3 /
    Object.values(data.position_distribution).reduce((a, b) => a + b, 0)) * 100;

  return (
    <div>
      <PageHeader
        title={`${market} War Room`}
        testId="warroom-title"
        description={`Independent ${market} visibility intelligence: query coverage, winners and losers, device and category performance, competitors and the highest-impact opportunities for this market only.`}
        right={
          <div className="flex gap-4">
            <div className="panel px-4 py-2">
              <span className="label-caps">Top 3 share</span>
              <p className="num text-xl">{fmt.pct(top3Share)}</p>
            </div>
            <div className="panel px-4 py-2">
              <span className="label-caps">Open issues</span>
              <p className="num text-xl">{fmt.int(data.open_issues)}</p>
            </div>
          </div>
        }
      />

      <div className="space-y-6 p-4 sm:p-6">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-5">
          <MetricCard label="Clicks 30d" value={fmt.int(t.clicks)} delta={t.clicks_delta_pct}
            onClick={() => navigate(`/keywords?market=${market}`)} testId="warroom-metric-clicks" />
          <MetricCard label="Impressions 30d" value={fmt.int(t.impressions)} delta={t.impressions_delta_pct}
            onClick={() => navigate(`/keywords?market=${market}`)} testId="warroom-metric-impressions" />
          <MetricCard label="CTR" value={fmt.pct(t.ctr, 2)} sub="market blended" testId="warroom-metric-ctr" />
          <MetricCard label="Avg position" value={fmt.dec(t.avg_position)} sub={`Δ ${fmt.dec(t.position_delta)} vs prior`}
            testId="warroom-metric-position" />
          <MetricCard label="Cannibalised queries" value={fmt.int(data.cannibalization)}
            onClick={() => navigate(`/keywords?market=${market}&cannibalized=1`)} testId="warroom-metric-cannibalization" />
        </div>

        <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1fr_1fr]">
          <Panel title="Position distribution (queries)" testId="position-distribution">
            <div className="h-[220px] min-h-[220px] p-3">
              <ResponsiveContainer width="100%" height="100%" minHeight={190}>
                <BarChart data={dist}>
                  <CartesianGrid stroke="#262626" vertical={false} />
                  <XAxis dataKey="bucket" {...axis} tickLine={false} />
                  <YAxis {...axis} tickLine={false} width={40} />
                  <Tooltip contentStyle={{ background: "#141414", border: "1px solid #262626", fontSize: 11 }} />
                  <Bar dataKey="queries" fill="#007AFF" />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </Panel>

          <Panel title="Device performance" testId="device-performance">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-[#262626] text-left">
                  {["Device", "Clicks", "Impr", "CTR", "Pos"].map((h) => (
                    <th key={h} className="label-caps px-4 py-2">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.devices.map((d) => (
                  <tr key={d.device} className="row-hover border-b border-[#262626] last:border-0" data-testid={`device-row-${d.device}`}>
                    <td className="px-4 py-2 text-xs">{d.device}</td>
                    <td className="num px-4 py-2 text-xs">{fmt.int(d.clicks)}</td>
                    <td className="num px-4 py-2 text-xs">{fmt.int(d.impressions)}</td>
                    <td className="num px-4 py-2 text-xs">{fmt.pct(d.ctr, 2)}</td>
                    <td className="num px-4 py-2 text-xs">{fmt.dec(d.avg_position)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Panel>
        </div>

        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <Panel title="Winners (clicks vs prior period)" testId="winners-panel">
            {data.winners.length === 0 ? <Empty label="No queries gained clicks in this window" /> : (
              <ul>
                {data.winners.map((w) => (
                  <li key={w.query} className="row-hover flex items-center justify-between gap-3 border-b border-[#262626] px-4 py-2 last:border-0">
                    <span className="truncate text-xs">{w.query}</span>
                    <span className="flex shrink-0 items-center gap-3">
                      <span className="num text-xs">{fmt.int(w.clicks)}</span>
                      <Delta value={w.clicks_delta_pct} />
                      <span className="num w-10 text-right text-[11px] text-[#a3a3a3]">p{fmt.dec(w.position)}</span>
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </Panel>

          <Panel title="Losers (clicks vs prior period)" testId="losers-panel">
            {data.losers.length === 0 ? <Empty label="No significant losses detected" /> : (
              <ul>
                {data.losers.map((w) => (
                  <li key={w.query} className="row-hover flex items-center justify-between gap-3 border-b border-[#262626] px-4 py-2 last:border-0">
                    <span className="truncate text-xs">{w.query}</span>
                    <span className="flex shrink-0 items-center gap-3">
                      <span className="num text-xs">{fmt.int(w.clicks)}</span>
                      <Delta value={w.clicks_delta_pct} />
                      <span className="num w-10 text-right text-[11px] text-[#a3a3a3]">p{fmt.dec(w.position)}</span>
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </Panel>
        </div>

        <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1.3fr_1fr]">
          <Panel title="Category coverage" testId="category-coverage">
            <div className="overflow-x-auto">
              <table className="w-full min-w-[420px] text-sm">
                <thead>
                  <tr className="border-b border-[#262626] text-left">
                    {["Category", "Queries", "Impressions", "Avg pos"].map((h) => (
                      <th key={h} className="label-caps px-4 py-2">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {data.categories.map((c) => (
                    <tr key={c.category} className="row-hover cursor-pointer border-b border-[#262626] last:border-0"
                      onClick={() => navigate(`/keywords?market=${market}&search=${encodeURIComponent(c.category.split(" ")[0].toLowerCase())}`)}
                      data-testid={`category-row-${c.category}`}>
                      <td className="px-4 py-2 text-xs">{c.category}</td>
                      <td className="num px-4 py-2 text-xs">{fmt.int(c.queries)}</td>
                      <td className="num px-4 py-2 text-xs">{fmt.int(c.impressions)}</td>
                      <td className="num px-4 py-2 text-xs">{fmt.dec(c.avg_position)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>

          <Panel title={`${market} competitors`} testId="warroom-competitors">
            <ul>
              {data.competitors.map((c) => (
                <li key={c.domain} className="row-hover border-b border-[#262626] px-4 py-2.5 last:border-0">
                  <div className="flex items-center justify-between">
                    <span className="num truncate text-xs">{c.domain}</span>
                    <Delta value={c.share_delta_30d} />
                  </div>
                  <div className="mt-1.5 flex items-center gap-2">
                    <div className="h-1 flex-1 bg-[#262626]">
                      <div className="h-1 bg-white" style={{ width: `${Math.min(100, c.visibility_share * 3.5)}%` }} />
                    </div>
                    <span className="num text-[11px] text-[#a3a3a3]">{fmt.pct(c.visibility_share)}</span>
                  </div>
                  <p className="num mt-1 text-[10px] text-[#525252]">
                    {fmt.int(c.queries_overlapping)} overlapping queries · avg p{fmt.dec(c.avg_position)}
                  </p>
                </li>
              ))}
            </ul>
          </Panel>
        </div>

        <Panel title={`Highest-impact ${market} opportunities`} testId="warroom-opportunities"
          action={
            <button onClick={() => navigate(`/opportunities?market=${market}`)} data-testid="warroom-open-opportunities"
              className="text-xs text-[#007AFF] transition-colors duration-150 hover:text-white">Full queue</button>
          }>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[720px] text-sm">
              <thead>
                <tr className="border-b border-[#262626] text-left">
                  {["Score", "Tier", "Entity", "Type", "Impr", "Pos", "CTR gap", "Recommended action"].map((h) => (
                    <th key={h} className="label-caps whitespace-nowrap px-3 py-2">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.top_opportunities.map((o) => (
                  <tr key={o.id} className="row-hover cursor-pointer border-b border-[#262626] last:border-0"
                    onClick={() => navigate(`/opportunities?focus=${o.id}`)} data-testid={`warroom-opportunity-${o.id}`}>
                    <td className="px-3 py-2"><ScorePill score={o.score} /></td>
                    <td className="px-3 py-2"><TierBadge tier={o.tier} /></td>
                    <td className="max-w-[220px] truncate px-3 py-2 text-xs">{o.entity_label}</td>
                    <td className="px-3 py-2 text-xs text-[#a3a3a3]">{o.entity_type}</td>
                    <td className="num px-3 py-2 text-xs">{fmt.int(o.evidence?.impressions_30d)}</td>
                    <td className="num px-3 py-2 text-xs">{fmt.dec(o.evidence?.avg_position)}</td>
                    <td className="num px-3 py-2 text-xs">{fmt.dec(o.components?.ctr_gap)}</td>
                    <td className="max-w-[260px] truncate px-3 py-2 text-xs text-[#a3a3a3]">{o.recommended_action}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      </div>
    </div>
  );
}
