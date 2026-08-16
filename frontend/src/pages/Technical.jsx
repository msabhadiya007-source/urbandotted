import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { PageHeader } from "@/components/Layout";
import {
  Empty, ErrorState, EvidenceRow, Loading, MetricCard, Panel, SeverityBadge,
} from "@/components/ui-kit";
import { fmt, get } from "@/lib/api";

const SELECT = "num border border-[#262626] bg-[#141414] px-2.5 py-1.5 text-xs outline-none transition-colors duration-150 focus:border-[#007AFF]";

function IssueDrawer({ id, onClose }) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["issue", id],
    queryFn: () => get(`/technical/issues/${id}`),
    enabled: Boolean(id),
  });

  return (
    <Sheet open={Boolean(id)} onOpenChange={(o) => !o && onClose()}>
      <SheetContent side="right" className="w-full overflow-y-auto border-l border-[#262626] bg-[#141414] sm:max-w-xl" data-testid="issue-drawer">
        {!data && (
          <SheetHeader>
            <SheetTitle className="sr-only">Technical issue detail</SheetTitle>
          </SheetHeader>
        )}
        {isLoading && <Loading label="Loading issue evidence" />}
        {error && <ErrorState error={error} />}
        {data && (
          <>
            <SheetHeader>
              <SheetTitle className="flex items-center gap-3 text-left text-lg">
                <SeverityBadge severity={data.issue.severity} />
                <span className="num break-words">{data.issue.issue_type}</span>
              </SheetTitle>
            </SheetHeader>
            <p className="mt-1 text-xs text-[#a3a3a3]">{data.issue.description}</p>

            <div className="mt-5 space-y-5">
              <section>
                <h4 className="label-caps mb-1">Affected URL</h4>
                <p className="num break-all text-xs text-[#007AFF]">{data.issue.url}</p>
              </section>

              <section>
                <h4 className="label-caps mb-1">Crawl evidence</h4>
                {Object.entries(data.issue.evidence || {}).map(([k, v]) => (
                  <EvidenceRow key={k} label={k.replace(/_/g, " ")} value={String(v)} />
                ))}
                <EvidenceRow label="market" value={data.issue.market} />
                <EvidenceRow label="page type" value={data.issue.page_type} />
                <EvidenceRow label="first detected" value={fmt.time(data.issue.first_detected_at)} />
                <EvidenceRow label="last seen" value={fmt.time(data.issue.last_seen_at)} />
                <EvidenceRow label="detected by" value={data.detected_by_role?.name || data.issue.detected_by} />
              </section>

              {data.page && (
                <section>
                  <h4 className="label-caps mb-1">Page state at last crawl</h4>
                  <EvidenceRow label="indexable" value={String(data.page.indexable)} />
                  <EvidenceRow label="canonical" value={fmt.path(data.page.canonical_url)} />
                  <EvidenceRow label="hreflang complete" value={String(data.page.hreflang_complete)} />
                  <EvidenceRow label="in sitemap" value={String(data.page.in_sitemap)} />
                  <EvidenceRow label="LCP" value={`${fmt.int(data.page.lcp_ms)} ms`} />
                  <EvidenceRow label="CLS" value={fmt.dec(data.page.cls, 3)} />
                  <EvidenceRow label="INP" value={`${fmt.int(data.page.inp_ms)} ms`} />
                </section>
              )}

              <section>
                <h4 className="label-caps mb-2">Organic exposure at risk</h4>
                {data.gsc_rows.length === 0 ? <Empty label="No GSC rows for this URL" /> : (
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="border-b border-[#262626] text-left">
                        {["Query", "Impr", "Clicks", "Pos"].map((h) => <th key={h} className="label-caps py-1.5">{h}</th>)}
                      </tr>
                    </thead>
                    <tbody>
                      {data.gsc_rows.map((g, i) => (
                        <tr key={i} className="border-b border-[#262626]">
                          <td className="max-w-[200px] truncate py-1.5">{g.query}</td>
                          <td className="num py-1.5">{fmt.int(g.impressions)}</td>
                          <td className="num py-1.5">{fmt.int(g.clicks)}</td>
                          <td className="num py-1.5">{fmt.dec(g.position)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </section>
            </div>
          </>
        )}
      </SheetContent>
    </Sheet>
  );
}

export default function Technical() {
  const [params] = useSearchParams();
  const [focus, setFocus] = useState(null);
  const [filters, setFilters] = useState({
    market: "", severity: params.get("severity") || "", group: params.get("group") || "",
    status: "open", search: "", offset: 0,
  });
  const set = (k, v) => setFilters((f) => ({ ...f, [k]: v, offset: k === "offset" ? v : 0 }));

  const summary = useQuery({ queryKey: ["technical-summary"], queryFn: () => get("/technical/summary") });
  const issues = useQuery({
    queryKey: ["technical-issues", filters],
    queryFn: () => get("/technical/issues", { ...filters, limit: 50 }),
  });

  return (
    <div>
      <PageHeader
        title="Technical SEO"
        testId="technical-title"
        description="Indexability, canonicals, hreflang, robots, sitemaps, redirects, broken links, structured data and Core Web Vitals. Every issue drills down to the crawl evidence and the organic exposure at risk."
      />

      <div className="space-y-4 p-4 sm:p-6">
        {summary.isLoading ? <Loading /> : summary.error ? <ErrorState error={summary.error} onRetry={summary.refetch} /> : (
          <>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
              <MetricCard label="Open issues" value={fmt.int(summary.data.open_total)} testId="tech-metric-open" />
              <MetricCard label="Resolved" value={fmt.int(summary.data.resolved_total)} testId="tech-metric-resolved" />
              <MetricCard label="Crawled URLs" value={fmt.int(summary.data.crawl_by_market.reduce((a, m) => a + m.urls, 0))}
                sub="incremental crawler" testId="tech-metric-crawled" />
              <MetricCard label="Indexable" value={fmt.int(summary.data.crawl_by_market.reduce((a, m) => a + m.indexable, 0))}
                sub="of crawled URLs" testId="tech-metric-indexable" />
            </div>

            <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1.2fr_1fr]">
              <Panel title="Issues by group" testId="issues-by-group">
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[460px] text-sm">
                    <thead>
                      <tr className="border-b border-[#262626] text-left">
                        {["Group", "Total", "Critical", "High", "Medium", "Low"].map((h) => (
                          <th key={h} className="label-caps px-3 py-2">{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {summary.data.by_group.map((g) => (
                        <tr key={g.group} onClick={() => set("group", g.group)} data-testid={`group-row-${g.group}`}
                          className="row-hover cursor-pointer border-b border-[#262626] last:border-0">
                          <td className="px-3 py-2 text-xs">{g.group}</td>
                          <td className="num px-3 py-2 text-xs">{fmt.int(g.total)}</td>
                          <td className="num px-3 py-2 text-xs text-[#FF3B30]">{g.critical || "—"}</td>
                          <td className="num px-3 py-2 text-xs text-[#FF6B62]">{g.high || "—"}</td>
                          <td className="num px-3 py-2 text-xs text-[#FFCC00]">{g.medium || "—"}</td>
                          <td className="num px-3 py-2 text-xs text-[#a3a3a3]">{g.low || "—"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </Panel>

              <Panel title="Crawl + Core Web Vitals by market" testId="crawl-by-market">
                <div className="grid gap-px bg-[#262626] sm:grid-cols-2">
                  {summary.data.crawl_by_market.map((m) => (
                    <div key={m.market} className="bg-[#141414] p-4">
                      <span className="label-caps">{m.market}</span>
                      <dl className="mt-2 space-y-1.5 text-xs">
                        {[
                          ["URLs crawled", fmt.int(m.urls)],
                          ["Indexable", `${fmt.int(m.indexable)} (${fmt.pct((m.indexable / m.urls) * 100)})`],
                          ["In sitemap", fmt.int(m.in_sitemap)],
                          ["hreflang complete", fmt.int(m.hreflang_complete)],
                          ["Avg LCP", `${fmt.int(m.avg_lcp_ms)} ms`],
                          ["Avg CLS", fmt.dec(m.avg_cls, 3)],
                          ["Avg INP", `${fmt.int(m.avg_inp_ms)} ms`],
                        ].map(([k, v]) => (
                          <div key={k} className="flex justify-between border-b border-[#262626] pb-1">
                            <dt className="text-[#a3a3a3]">{k}</dt>
                            <dd className="num">{v}</dd>
                          </div>
                        ))}
                      </dl>
                    </div>
                  ))}
                </div>
              </Panel>
            </div>
          </>
        )}

        <div className="flex flex-wrap items-center gap-2">
          <input placeholder="Search URL…" value={filters.search} onChange={(e) => set("search", e.target.value)}
            data-testid="issue-search" className={`${SELECT} min-w-[180px] flex-1`} />
          <select value={filters.severity} onChange={(e) => set("severity", e.target.value)} className={SELECT} data-testid="tech-filter-severity">
            <option value="">All severities</option>
            {["critical", "high", "medium", "low"].map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
          <select value={filters.group} onChange={(e) => set("group", e.target.value)} className={SELECT} data-testid="tech-filter-group">
            <option value="">All groups</option>
            {(summary.data?.by_group || []).map((g) => <option key={g.group} value={g.group}>{g.group}</option>)}
          </select>
          <select value={filters.market} onChange={(e) => set("market", e.target.value)} className={SELECT} data-testid="tech-filter-market">
            <option value="">All markets</option><option value="AU">AU</option><option value="NZ">NZ</option>
          </select>
          <select value={filters.status} onChange={(e) => set("status", e.target.value)} className={SELECT} data-testid="tech-filter-status">
            <option value="open">Open</option><option value="resolved">Resolved</option>
          </select>
        </div>

        <Panel testId="issues-panel">
          {issues.isLoading ? <Loading /> : issues.error ? <ErrorState error={issues.error} onRetry={issues.refetch} /> :
            issues.data.rows.length === 0 ? <Empty label="No issues match these filters" /> : (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[760px] text-sm">
                  <thead>
                    <tr className="border-b border-[#262626] text-left">
                      {["Severity", "Issue", "Group", "URL", "Mkt", "Type", "Detected by", "Last seen"].map((h) => (
                        <th key={h} className="label-caps whitespace-nowrap px-3 py-2">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {issues.data.rows.map((r) => (
                      <tr key={r.id} onClick={() => setFocus(r.id)} data-testid={`issue-row-${r.id}`}
                        className="row-hover cursor-pointer border-b border-[#262626] last:border-0">
                        <td className="px-3 py-2"><SeverityBadge severity={r.severity} /></td>
                        <td className="num px-3 py-2 text-xs">{r.issue_type}</td>
                        <td className="px-3 py-2 text-xs text-[#a3a3a3]">{r.group}</td>
                        <td className="num max-w-[240px] truncate px-3 py-2 text-[11px] text-[#007AFF]">{fmt.path(r.url)}</td>
                        <td className="label-caps px-3 py-2">{r.market}</td>
                        <td className="px-3 py-2 text-xs text-[#a3a3a3]">{r.page_type}</td>
                        <td className="px-3 py-2 text-[11px] text-[#a3a3a3]">{r.detected_by}</td>
                        <td className="num px-3 py-2 text-[11px] text-[#737373]">{fmt.ago(r.last_seen_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          {issues.data && issues.data.total > 50 && (
            <div className="flex items-center justify-between border-t border-[#262626] px-4 py-2">
              <span className="num text-xs text-[#a3a3a3]">
                {filters.offset + 1}–{Math.min(filters.offset + 50, issues.data.total)} of {fmt.int(issues.data.total)}
              </span>
              <span className="flex gap-2">
                <button disabled={filters.offset === 0} data-testid="tech-page-prev"
                  onClick={() => setFilters((f) => ({ ...f, offset: Math.max(0, f.offset - 50) }))}
                  className="border border-[#262626] px-2.5 py-1 text-xs transition-colors duration-150 hover:bg-[#262626] disabled:opacity-40">Prev</button>
                <button disabled={filters.offset + 50 >= issues.data.total} data-testid="tech-page-next"
                  onClick={() => setFilters((f) => ({ ...f, offset: f.offset + 50 }))}
                  className="border border-[#262626] px-2.5 py-1 text-xs transition-colors duration-150 hover:bg-[#262626] disabled:opacity-40">Next</button>
              </span>
            </div>
          )}
        </Panel>
      </div>

      <IssueDrawer id={focus} onClose={() => setFocus(null)} />
    </div>
  );
}
