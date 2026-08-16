import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { PageHeader } from "@/components/Layout";
import {
  Delta, Empty, ErrorState, EvidenceRow, Loading, MetricCard, Panel, ScorePill, SeverityBadge, TierBadge,
} from "@/components/ui-kit";
import { fmt, get } from "@/lib/api";

const SELECT = "num border border-[#262626] bg-[#141414] px-2.5 py-1.5 text-xs outline-none transition-colors duration-150 focus:border-[#007AFF]";
const INTENT_COLOUR = {
  transactional: "text-[#34C759]",
  commercial: "text-[#007AFF]",
  informational: "text-[#FFCC00]",
  navigational: "text-[#a3a3a3]",
};

function KeywordDrawer({ target, onClose }) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["keyword-detail", target?.query, target?.market],
    queryFn: () => get("/keywords/detail", { query: target.query, market: target.market }),
    enabled: Boolean(target),
  });

  return (
    <Sheet open={Boolean(target)} onOpenChange={(o) => !o && onClose()}>
      <SheetContent side="right" className="w-full overflow-y-auto border-l border-[#262626] bg-[#141414] sm:max-w-xl" data-testid="keyword-drawer">
        {!data && (
          <SheetHeader>
            <SheetTitle className="sr-only">Keyword detail</SheetTitle>
          </SheetHeader>
        )}
        {isLoading && <Loading label="Loading query intelligence" />}
        {error && <ErrorState error={error} />}
        {data && (
          <>
            <SheetHeader>
              <SheetTitle className="text-left text-lg break-words">{data.keyword.query}</SheetTitle>
            </SheetHeader>
            <p className="mt-1 flex flex-wrap items-center gap-2 text-xs text-[#a3a3a3]">
              <span className="label-caps">{data.keyword.market}</span>
              <span className={INTENT_COLOUR[data.keyword.intent]}>{data.keyword.intent}</span>
              <span className="num">conf {fmt.dec((data.keyword.intent_confidence || 0) * 100, 0)}%</span>
              <span className="num text-[#525252]">{data.keyword.intent_method}</span>
            </p>

            <div className="mt-5 space-y-5">
              {data.opportunity && (
                <section className="flex items-center gap-3 border border-[#262626] bg-[#0a0a0a] p-3">
                  <ScorePill score={data.opportunity.score} />
                  <TierBadge tier={data.opportunity.tier} />
                  <span className="text-xs text-[#a3a3a3]">{data.opportunity.recommended_action}</span>
                </section>
              )}

              <section>
                <h4 className="label-caps mb-1">Query facts</h4>
                <EvidenceRow label="impressions 30d" value={fmt.int(data.keyword.impressions_30d)} />
                <EvidenceRow label="avg position" value={fmt.dec(data.keyword.avg_position)} />
                <EvidenceRow label="preferred landing page" value={fmt.path(data.keyword.preferred_url)} />
                <EvidenceRow label="preferred page type" value={data.keyword.preferred_page_type} />
                <EvidenceRow label="cluster" value={data.keyword.cluster} />
                <EvidenceRow label="source" value={data.keyword.source} />
                {data.keyword.intent_reasoning && (
                  <EvidenceRow label="intent reasoning" value={data.keyword.intent_reasoning} mono={false} />
                )}
              </section>

              <section>
                <h4 className="label-caps mb-2">Pages ranking for this query</h4>
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b border-[#262626] text-left">
                      {["URL", "Impr", "Clicks", "CTR", "Pos"].map((h) => (
                        <th key={h} className="label-caps py-1.5">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {data.pages.map((p) => (
                      <tr key={p.url} className="border-b border-[#262626]">
                        <td className="num max-w-[210px] truncate py-1.5">{fmt.path(p.url)}</td>
                        <td className="num py-1.5">{fmt.int(p.impressions)}</td>
                        <td className="num py-1.5">{fmt.int(p.clicks)}</td>
                        <td className="num py-1.5">{fmt.pct(p.ctr, 2)}</td>
                        <td className="num py-1.5">{fmt.dec(p.position)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </section>

              <section>
                <h4 className="label-caps mb-2">Device split</h4>
                <ul className="space-y-1">
                  {data.devices.map((d, i) => (
                    <li key={i} className="flex items-center justify-between border-b border-[#262626] py-1.5 text-xs">
                      <span>{d.device}</span>
                      <span className="num text-[#a3a3a3]">
                        {fmt.int(d.impressions)} impr · {fmt.int(d.clicks)} clk · p{fmt.dec(d.position)}
                      </span>
                    </li>
                  ))}
                </ul>
              </section>

              {data.cannibalization ? (
                <section className="border border-[#FF3B30]/40 bg-[#FF3B30]/5 p-3" data-testid="drawer-cannibalization">
                  <div className="flex items-center gap-2">
                    <SeverityBadge severity={data.cannibalization.severity} />
                    <span className="num text-[11px]">{data.cannibalization.verdict}</span>
                    <span className="text-[10px] text-[#737373]">{data.cannibalization.resolution_method}</span>
                  </div>
                  <p className="num mt-2 text-[11px] text-[#a3a3a3]">
                    Preferred: {fmt.path(data.cannibalization.recommended_preferred_url)} (p
                    {fmt.dec(data.cannibalization.primary_position)})
                  </p>
                  {data.cannibalization.competing_urls.map((c) => (
                    <p key={c.url} className="num mt-1 text-[11px] text-[#FF6B62]">
                      Competing: {fmt.path(c.url)} · p{fmt.dec(c.position)} · {fmt.int(c.impressions)} impr
                    </p>
                  ))}
                  <p className="mt-2 text-[10px] text-[#737373]">Rule: {data.cannibalization.evidence.rule}</p>
                </section>
              ) : (
                <Empty label="No cannibalization detected for this query" testId="drawer-no-cannibalization" />
              )}
            </div>
          </>
        )}
      </SheetContent>
    </Sheet>
  );
}

export default function Keywords() {
  const [params] = useSearchParams();
  const [target, setTarget] = useState(null);
  const [filters, setFilters] = useState({
    market: params.get("market") || "",
    intent: "",
    search: params.get("search") || "",
    cannibalized_only: params.get("cannibalized") === "1",
    sort: "impressions_30d",
    offset: 0,
  });
  const set = (k, v) => setFilters((f) => ({ ...f, [k]: v, offset: k === "offset" ? v : 0 }));

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ["keywords", filters],
    queryFn: () => get("/keywords", { ...filters, limit: 50 }),
  });
  const { data: cann } = useQuery({ queryKey: ["cannibalization-count"], queryFn: () => get("/cannibalization", { limit: 1 }) });

  return (
    <div>
      <PageHeader
        title="Keywords / GSC"
        testId="keywords-title"
        description="Query × page × market intelligence sourced from Search Console. Intent is deterministic-first and escalates to the LLM router only for low-confidence, high-value queries."
      />

      <div className="space-y-4 p-4 sm:p-6">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <MetricCard label="Queries tracked" value={fmt.int(data?.total)} sub="matching filters" testId="kw-metric-total" />
          <MetricCard label="Transactional" value={fmt.int(data?.intent_facets?.transactional)} sub="intent class" testId="kw-metric-transactional" />
          <MetricCard label="Commercial" value={fmt.int(data?.intent_facets?.commercial)} sub="intent class" testId="kw-metric-commercial" />
          <MetricCard label="Cannibalised queries" value={fmt.int(cann?.total)} sub="deterministic detection"
            onClick={() => set("cannibalized_only", true)} testId="kw-metric-cannibalized" />
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <input placeholder="Search query…" value={filters.search} onChange={(e) => set("search", e.target.value)}
            data-testid="keyword-search" className={`${SELECT} min-w-[180px] flex-1`} />
          <select value={filters.market} onChange={(e) => set("market", e.target.value)} className={SELECT} data-testid="kw-filter-market">
            <option value="">All markets</option><option value="AU">AU</option><option value="NZ">NZ</option>
          </select>
          <select value={filters.intent} onChange={(e) => set("intent", e.target.value)} className={SELECT} data-testid="kw-filter-intent">
            <option value="">All intents</option>
            {["transactional", "commercial", "informational", "navigational"].map((i) => <option key={i} value={i}>{i}</option>)}
          </select>
          <label className="flex items-center gap-2 border border-[#262626] px-2.5 py-1.5 text-xs">
            <input type="checkbox" checked={filters.cannibalized_only} data-testid="kw-filter-cannibalized"
              onChange={(e) => set("cannibalized_only", e.target.checked)} className="accent-[#007AFF]" />
            Cannibalised only
          </label>
        </div>

        <Panel testId="keywords-panel">
          {isLoading ? <Loading /> : error ? <ErrorState error={error} onRetry={refetch} /> :
            data.rows.length === 0 ? <Empty /> : (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[840px] text-sm">
                  <thead>
                    <tr className="border-b border-[#262626] text-left">
                      {["Query", "Mkt", "Intent", "Impr 30d", "Avg pos", "Preferred landing page", "Cluster", "Cannib."].map((h) => (
                        <th key={h} className="label-caps whitespace-nowrap px-3 py-2">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {data.rows.map((k) => (
                      <tr key={k.id} onClick={() => setTarget(k)} data-testid={`keyword-row-${k.id}`}
                        className="row-hover cursor-pointer border-b border-[#262626] last:border-0">
                        <td className="max-w-[230px] truncate px-3 py-2 text-xs">{k.query}</td>
                        <td className="label-caps px-3 py-2">{k.market}</td>
                        <td className={`px-3 py-2 text-xs ${INTENT_COLOUR[k.intent]}`}>{k.intent}</td>
                        <td className="num px-3 py-2 text-xs">{fmt.int(k.impressions_30d)}</td>
                        <td className="num px-3 py-2 text-xs">{fmt.dec(k.avg_position)}</td>
                        <td className="num max-w-[220px] truncate px-3 py-2 text-[11px] text-[#a3a3a3]">{fmt.path(k.preferred_url)}</td>
                        <td className="px-3 py-2 text-[11px] text-[#a3a3a3]">{k.cluster}</td>
                        <td className="px-3 py-2">
                          {k.cannibalization ? <SeverityBadge severity={k.cannibalization.severity} /> :
                            <span className="text-[11px] text-[#525252]">—</span>}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          {data && data.total > 50 && (
            <div className="flex items-center justify-between border-t border-[#262626] px-4 py-2">
              <span className="num text-xs text-[#a3a3a3]">
                {filters.offset + 1}–{Math.min(filters.offset + 50, data.total)} of {fmt.int(data.total)}
              </span>
              <span className="flex gap-2">
                <button disabled={filters.offset === 0} data-testid="kw-page-prev"
                  onClick={() => setFilters((f) => ({ ...f, offset: Math.max(0, f.offset - 50) }))}
                  className="border border-[#262626] px-2.5 py-1 text-xs transition-colors duration-150 hover:bg-[#262626] disabled:opacity-40">Prev</button>
                <button disabled={filters.offset + 50 >= data.total} data-testid="kw-page-next"
                  onClick={() => setFilters((f) => ({ ...f, offset: f.offset + 50 }))}
                  className="border border-[#262626] px-2.5 py-1 text-xs transition-colors duration-150 hover:bg-[#262626] disabled:opacity-40">Next</button>
              </span>
            </div>
          )}
        </Panel>
      </div>

      <KeywordDrawer target={target} onClose={() => setTarget(null)} />
    </div>
  );
}
