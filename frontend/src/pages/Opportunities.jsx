import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { PageHeader, StageNotice } from "@/components/Layout";
import {
  Empty, ErrorState, EvidenceRow, Loading, Panel, ScoreBars, ScorePill, SeverityBadge, TierBadge,
} from "@/components/ui-kit";
import { fmt, get } from "@/lib/api";

const SELECT = "num border border-[#262626] bg-[#141414] px-2.5 py-1.5 text-xs outline-none transition-colors duration-150 focus:border-[#007AFF]";

function EvidenceDrawer({ id, onClose }) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["opportunity-evidence", id],
    queryFn: () => get(`/opportunities/${id}/evidence`),
    enabled: Boolean(id),
  });

  return (
    <Sheet open={Boolean(id)} onOpenChange={(o) => !o && onClose()}>
      <SheetContent side="right" className="w-full overflow-y-auto border-l border-[#262626] bg-[#141414] sm:max-w-xl" data-testid="evidence-drawer">
        {!data && (
          <SheetHeader>
            <SheetTitle className="sr-only">Opportunity evidence</SheetTitle>
          </SheetHeader>
        )}
        {isLoading && <Loading label="Loading evidence trail" />}
        {error && <ErrorState error={error} />}
        {data && (
          <>
            <SheetHeader>
              <SheetTitle className="flex items-center gap-3 text-left text-lg">
                <ScorePill score={data.opportunity.score} testId="drawer-score" />
                <TierBadge tier={data.opportunity.tier} />
                <span className="min-w-0 break-words">{data.opportunity.entity_label}</span>
              </SheetTitle>
            </SheetHeader>

            <p className="mt-1 text-xs text-[#a3a3a3]">
              {data.opportunity.entity_type} · {data.opportunity.market} · rank #{data.opportunity.rank} of market
              queue · confidence {fmt.dec(data.opportunity.confidence * 100, 0)}%
            </p>

            <div className="mt-5 space-y-5">
              <section>
                <h4 className="label-caps mb-2">Score components</h4>
                <ScoreBars components={data.opportunity.components} weights={data.opportunity.weights} />
              </section>

              <section>
                <h4 className="label-caps mb-1">Evidence used</h4>
                {Object.entries(data.opportunity.evidence || {}).map(([k, v]) => (
                  <EvidenceRow key={k} label={k.replace(/_/g, " ")}
                    value={typeof v === "number" ? fmt.int(v) : String(v)} />
                ))}
              </section>

              <section className="border border-[#262626] bg-[#0a0a0a] p-3">
                <h4 className="label-caps mb-1">Recommended action</h4>
                <p className="text-xs text-[#f5f5f5]">{data.opportunity.recommended_action}</p>
                <p className="mt-2 text-[11px] text-[#737373]">
                  Policy: {data.policy.risk_class} · decision {data.policy.decision} · approver required{" "}
                  {String(data.policy.approver_required)}. Stage 1 never executes.
                </p>
              </section>

              <section>
                <h4 className="label-caps mb-2">GSC rows behind this score ({data.gsc_rows.length})</h4>
                {data.gsc_rows.length === 0 ? <Empty label="No GSC rows joined" /> : (
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="border-b border-[#262626] text-left">
                        {["URL / query", "Dev", "Impr", "Clk", "Pos"].map((h) => (
                          <th key={h} className="label-caps py-1.5">{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {data.gsc_rows.slice(0, 10).map((g, i) => (
                        <tr key={i} className="border-b border-[#262626]">
                          <td className="num max-w-[220px] truncate py-1.5">{fmt.path(g.url)}</td>
                          <td className="py-1.5 text-[10px] text-[#a3a3a3]">{g.device[0]}</td>
                          <td className="num py-1.5">{fmt.int(g.impressions)}</td>
                          <td className="num py-1.5">{fmt.int(g.clicks)}</td>
                          <td className="num py-1.5">{fmt.dec(g.position)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </section>

              {data.cannibalization?.length > 0 && (
                <section>
                  <h4 className="label-caps mb-2">Cannibalization</h4>
                  {data.cannibalization.map((c, i) => (
                    <div key={i} className="border border-[#262626] p-3">
                      <div className="flex items-center gap-2">
                        <SeverityBadge severity={c.severity} />
                        <span className="num text-[11px]">{c.verdict}</span>
                        <span className="text-[10px] text-[#737373]">{c.resolution_method}</span>
                      </div>
                      <p className="num mt-2 text-[11px] text-[#a3a3a3]">
                        preferred: {fmt.path(c.recommended_preferred_url)}
                      </p>
                      <p className="num mt-1 text-[11px] text-[#a3a3a3]">
                        rival share {fmt.pct(c.rival_impression_share * 100)} across {c.competing_urls.length + 1} URLs
                      </p>
                    </div>
                  ))}
                </section>
              )}

              {data.technical_issues.length > 0 && (
                <section>
                  <h4 className="label-caps mb-2">Technical issues on the landing page</h4>
                  <ul className="space-y-1.5">
                    {data.technical_issues.map((t) => (
                      <li key={t.id} className="flex items-center gap-2 border border-[#262626] px-2.5 py-1.5">
                        <SeverityBadge severity={t.severity} />
                        <span className="num truncate text-[11px]">{t.issue_type}</span>
                      </li>
                    ))}
                  </ul>
                </section>
              )}

              <section>
                <h4 className="label-caps mb-2">Memory records informing this recommendation</h4>
                <ul className="space-y-2">
                  {data.memory_records.map((m) => (
                    <li key={m.id} className="border border-[#262626] p-3" data-testid={`drawer-memory-${m.id}`}>
                      <div className="flex items-center justify-between gap-2">
                        <span className="label-caps">{m.memory_type}</span>
                        <span className="num text-[10px] text-[#34C759]">
                          conf {fmt.dec(m.confidence * 100, 0)}% · n={m.sample_size}
                        </span>
                      </div>
                      <p className="mt-1 text-xs font-medium">{m.title}</p>
                      <p className="mt-1 text-[11px] leading-relaxed text-[#a3a3a3]">{m.content}</p>
                    </li>
                  ))}
                </ul>
              </section>

              {data.serp_snapshot && (
                <section>
                  <h4 className="label-caps mb-2">SERP snapshot ({fmt.time(data.serp_snapshot.captured_at)})</h4>
                  <ul className="space-y-1">
                    {data.serp_snapshot.results.map((r) => (
                      <li key={r.position} className={`flex items-center gap-2 px-2 py-1 text-[11px] ${r.is_us ? "bg-[#007AFF]/15 text-white" : "text-[#a3a3a3]"}`}>
                        <span className="num w-4">{r.position}</span>
                        <span className="num truncate">{r.domain}</span>
                        {r.is_us && <span className="label-caps ml-auto text-[#007AFF]">us</span>}
                      </li>
                    ))}
                  </ul>
                </section>
              )}
            </div>
          </>
        )}
      </SheetContent>
    </Sheet>
  );
}

export default function Opportunities() {
  const [params, setParams] = useSearchParams();
  const [focus, setFocus] = useState(params.get("focus"));
  const [filters, setFilters] = useState({
    market: params.get("market") || "",
    entity_type: params.get("entity_type") || "",
    tier: params.get("tier") || "",
    search: "",
    min_score: 0,
    sort: "score",
    offset: 0,
  });

  useEffect(() => {
    const next = new URLSearchParams();
    Object.entries(filters).forEach(([k, v]) => v && k !== "offset" && next.set(k, v));
    if (focus) next.set("focus", focus);
    setParams(next, { replace: true });
  }, [filters, focus, setParams]);

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ["opportunities", filters],
    queryFn: () => get("/opportunities", { ...filters, limit: 50 }),
  });

  const set = (k, v) => setFilters((f) => ({ ...f, [k]: v, offset: k === "offset" ? v : 0 }));

  return (
    <div>
      <PageHeader
        title="Opportunities"
        testId="opportunities-title"
        description="Every scored entity across keywords, products and collections. Score = 0.30 demand + 0.25 position gap + 0.20 CTR gap + 0.15 intent value + 0.10 technical health. Click any row for the full evidence trail."
        right={
          data && (
            <div className="panel px-4 py-2">
              <span className="label-caps">In queue</span>
              <p className="num text-xl">{fmt.int(data.total)}</p>
            </div>
          )
        }
      />

      <div className="space-y-4 p-4 sm:p-6">
        <StageNotice />

        <div className="flex flex-wrap items-center gap-2">
          <input placeholder="Search entity…" value={filters.search} data-testid="opportunity-search"
            onChange={(e) => set("search", e.target.value)}
            className={`${SELECT} min-w-[180px] flex-1`} />
          <select value={filters.market} onChange={(e) => set("market", e.target.value)} className={SELECT} data-testid="filter-market">
            <option value="">All markets</option>
            <option value="AU">AU</option>
            <option value="NZ">NZ</option>
          </select>
          <select value={filters.entity_type} onChange={(e) => set("entity_type", e.target.value)} className={SELECT} data-testid="filter-entity-type">
            <option value="">All types</option>
            <option value="keyword">Keyword</option>
            <option value="product">Product</option>
            <option value="collection">Collection</option>
          </select>
          <select value={filters.tier} onChange={(e) => set("tier", e.target.value)} className={SELECT} data-testid="filter-tier">
            <option value="">All tiers</option>
            {["A", "B", "C", "D"].map((t) => <option key={t} value={t}>Tier {t}</option>)}
          </select>
          <select value={filters.min_score} onChange={(e) => set("min_score", Number(e.target.value))} className={SELECT} data-testid="filter-min-score">
            {[0, 40, 50, 60, 70, 80].map((s) => <option key={s} value={s}>Score ≥ {s}</option>)}
          </select>
          <select value={filters.sort} onChange={(e) => set("sort", e.target.value)} className={SELECT} data-testid="filter-sort">
            <option value="score">Sort: score</option>
            <option value="rank">Sort: rank</option>
          </select>
        </div>

        <Panel testId="opportunities-panel">
          {isLoading ? <Loading /> : error ? <ErrorState error={error} onRetry={refetch} /> :
            data.rows.length === 0 ? <Empty /> : (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[860px] text-sm">
                  <thead>
                    <tr className="border-b border-[#262626] text-left">
                      {["Score", "Tier", "Entity", "Type", "Mkt", "Intent", "Impr 30d", "Clicks", "Pos", "CTR", "Recommended action"].map((h) => (
                        <th key={h} className="label-caps whitespace-nowrap px-3 py-2">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {data.rows.map((o) => (
                      <tr key={o.id} onClick={() => setFocus(o.id)} data-testid={`opportunity-row-${o.id}`}
                        className="row-hover cursor-pointer border-b border-[#262626] last:border-0">
                        <td className="px-3 py-2"><ScorePill score={o.score} /></td>
                        <td className="px-3 py-2"><TierBadge tier={o.tier} /></td>
                        <td className="max-w-[220px] truncate px-3 py-2 text-xs">{o.entity_label}</td>
                        <td className="px-3 py-2 text-xs text-[#a3a3a3]">{o.entity_type}</td>
                        <td className="label-caps px-3 py-2">{o.market}</td>
                        <td className="px-3 py-2 text-xs text-[#a3a3a3]">{o.intent}</td>
                        <td className="num px-3 py-2 text-xs">{fmt.int(o.evidence?.impressions_30d)}</td>
                        <td className="num px-3 py-2 text-xs">{fmt.int(o.evidence?.clicks_30d)}</td>
                        <td className="num px-3 py-2 text-xs">{fmt.dec(o.evidence?.avg_position)}</td>
                        <td className="num px-3 py-2 text-xs">{fmt.pct((o.evidence?.ctr || 0) * 100, 2)}</td>
                        <td className="max-w-[240px] truncate px-3 py-2 text-xs text-[#a3a3a3]">{o.recommended_action}</td>
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
                <button disabled={filters.offset === 0} onClick={() => setFilters((f) => ({ ...f, offset: Math.max(0, f.offset - 50) }))}
                  data-testid="page-prev"
                  className="border border-[#262626] px-2.5 py-1 text-xs transition-colors duration-150 hover:bg-[#262626] disabled:opacity-40">Prev</button>
                <button disabled={filters.offset + 50 >= data.total} onClick={() => setFilters((f) => ({ ...f, offset: f.offset + 50 }))}
                  data-testid="page-next"
                  className="border border-[#262626] px-2.5 py-1 text-xs transition-colors duration-150 hover:bg-[#262626] disabled:opacity-40">Next</button>
              </span>
            </div>
          )}
        </Panel>
      </div>

      <EvidenceDrawer id={focus} onClose={() => setFocus(null)} />
    </div>
  );
}
