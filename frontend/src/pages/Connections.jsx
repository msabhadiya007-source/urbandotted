import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { CheckCircle2, CircleDashed, Loader2, Lock, Play, ShieldCheck } from "lucide-react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { PageHeader } from "@/components/Layout";
import { Empty, ErrorState, EvidenceRow, Loading, MetricCard, Panel } from "@/components/ui-kit";
import { fmt, get, post } from "@/lib/api";
import { formatApiErrorDetail } from "@/lib/api";

const INPUT =
  "num mt-1.5 w-full border border-[#262626] bg-[#0a0a0a] px-3 py-2 text-xs outline-none transition-colors duration-150 focus:border-[#007AFF]";
const BTN =
  "flex items-center justify-center gap-2 bg-white px-3 py-2 text-xs font-medium text-black transition-colors duration-150 hover:bg-[#d4d4d4] disabled:opacity-40";
const GHOST =
  "flex items-center gap-2 border border-[#262626] px-3 py-1.5 text-xs transition-colors duration-150 hover:bg-[#262626] disabled:opacity-40";

const Status = ({ ok, label }) => (
  <span className={`flex items-center gap-1.5 text-xs ${ok ? "text-[#34C759]" : "text-[#737373]"}`}>
    {ok ? <CheckCircle2 className="h-3.5 w-3.5" /> : <CircleDashed className="h-3.5 w-3.5" />}
    {label}
  </span>
);

export default function Connections() {
  const qc = useQueryClient();
  const [shopify, setShopify] = useState({ shop_domain: "", admin_api_token: "", webhook_secret: "" });
  const [gsc, setGsc] = useState({ site_url: "", service_account_json: "" });
  const [bq, setBq] = useState({ project: "", dataset: "searchconsole", location: "" });
  const [crawl, setCrawl] = useState({ requests_per_sec: 3, workers: 3 });
  const [confirmPurge, setConfirmPurge] = useState(false);
  const [purgeText, setPurgeText] = useState("");

  const conn = useQuery({ queryKey: ["connections"], queryFn: () => get("/admin/connections") });
  const syncStatus = useQuery({ queryKey: ["sync-status"], queryFn: () => get("/admin/shopify/sync/status"), refetchInterval: 15000 });
  const gscStatus = useQuery({ queryKey: ["gsc-status"], queryFn: () => get("/admin/gsc/status"), refetchInterval: 20000 });
  const crawlStatus = useQuery({ queryKey: ["crawl-status"], queryFn: () => get("/admin/crawl/status"), refetchInterval: 10000 });
  const report = useQuery({ queryKey: ["acceptance"], queryFn: () => get("/admin/live-acceptance-report") });
  const recon = useQuery({ queryKey: ["url-recon"], queryFn: () => get("/admin/gsc/url-reconciliation", { limit: 20 }) });

  const refreshAll = () => ["connections", "sync-status", "gsc-status", "crawl-status", "acceptance", "url-recon"]
    .forEach((k) => qc.invalidateQueries({ queryKey: [k] }));

  const action = useMutation({
    mutationFn: ({ path, body }) => post(path, body),
    onSuccess: () => {
      toast.success("Request completed");
      refreshAll();
    },
    onError: (e) => {
      toast.error(formatApiErrorDetail(e.response?.data?.detail) || "Request failed");
      refreshAll();
    },
  });
  const run = (path, body) => action.mutate({ path, body });
  const lastPath = action.variables?.path;
  const resultFor = (path) => (lastPath === path && action.data ? action.data : null);

  const saveShopify = { mutate: () => run("/admin/connections/shopify", shopify), isPending: action.isPending, data: resultFor("/admin/connections/shopify") };
  const saveGsc = { mutate: () => run("/admin/connections/gsc", gsc), isPending: action.isPending, data: resultFor("/admin/connections/gsc") };
  const saveBq = { mutate: () => run("/admin/connections/bigquery", bq), isPending: action.isPending };
  const saveCrawl = { mutate: () => run("/admin/connections/crawl-settings", crawl), isPending: action.isPending };
  const activate = { mutate: () => run("/admin/connections/activate-live"), isPending: action.isPending };
  const registerHooks = { mutate: () => run("/admin/shopify/webhooks/register") };
  const runSync = { mutate: () => run("/admin/shopify/sync?background=true") };
  const runReconcile = { mutate: () => run("/admin/shopify/reconcile") };
  const runBootstrap = { mutate: () => run("/admin/gsc/bootstrap?background=true") };
  const runDaily = { mutate: () => run("/admin/gsc/daily?days=3") };
  const runRecon = { mutate: () => run("/admin/gsc/url-reconciliation/run") };
  const runRobots = { mutate: () => run("/admin/crawl/robots") };
  const runCrawlBatch = { mutate: () => run("/admin/crawl/batch?limit=25") };
  const runCrawlFull = { mutate: () => run("/admin/crawl/full?batch_size=200&max_batches=5") };
  const runRecompute = { mutate: () => run("/admin/intelligence/recompute") };
  const purge = { mutate: () => run("/admin/intelligence/purge-fixtures") };

  if (conn.isLoading) return <Loading label="Reading connection state" />;
  if (conn.error) return <div className="p-6"><ErrorState error={conn.error} onRetry={conn.refetch} /></div>;

  const c = conn.data;
  const rd = report.data?.readiness;

  return (
    <div>
      <PageHeader
        title="Connections & Live Data"
        testId="connections-title"
        description="Credentials are accepted over HTTPS, stored only in the backend environment with 0600 permissions, and never returned, logged or written to the database. Rotation is a re-submit of the same field."
        right={
          <div className="panel px-4 py-2">
            <span className="label-caps">Data mode</span>
            <p className={`num text-xl ${c.live_data_mode ? "text-[#34C759]" : "text-[#FFCC00]"}`}>
              {c.data_mode}
            </p>
          </div>
        }
      />

      <div className="space-y-4 p-4 sm:p-6">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <MetricCard label="Shopify" value={c.shopify.verified ? "Verified" : c.shopify.admin_token_configured ? "Unverified" : "Not set"}
            sub={c.shopify.shop_domain || "read-only scopes"} testId="conn-metric-shopify" />
          <MetricCard label="Search Console" value={c.gsc.verified ? "Verified" : c.gsc.service_account_configured ? "Unverified" : "Not set"}
            sub={c.gsc.site_url || "service account"} testId="conn-metric-gsc" />
          <MetricCard label="BigQuery export" value={c.bigquery.verified ? "Verified" : c.bigquery.configured ? "Unverified" : "Not set"}
            sub={c.bigquery.dataset || "preferred ongoing source"} testId="conn-metric-bq" />
          <MetricCard label="Crawl ceiling" value={`${c.crawl.requests_per_sec}/s`}
            sub={`${c.crawl.workers} workers · shared limiter`} testId="conn-metric-crawl" />
        </div>

        <Panel title="Stage 1 live-data readiness" testId="readiness-panel">
          {report.isLoading ? <Loading /> : !rd ? <Empty /> : (
            <div className="grid gap-px bg-[#262626] sm:grid-cols-2 lg:grid-cols-3">
              {Object.entries(rd.checks).map(([k, v]) => (
                <div key={k} className="bg-[#141414] p-3" data-testid={`readiness-${k}`}>
                  <Status ok={v} label={k.replace(/_/g, " ")} />
                </div>
              ))}
            </div>
          )}
        </Panel>

        <Tabs defaultValue="credentials">
          <TabsList className="border border-[#262626] bg-[#141414]">
            <TabsTrigger value="credentials" data-testid="tab-credentials">Credentials</TabsTrigger>
            <TabsTrigger value="shopify" data-testid="tab-shopify">Shopify sync</TabsTrigger>
            <TabsTrigger value="gsc" data-testid="tab-gsc">GSC ingest</TabsTrigger>
            <TabsTrigger value="crawl" data-testid="tab-crawl">Crawler</TabsTrigger>
            <TabsTrigger value="report" data-testid="tab-report">Acceptance report</TabsTrigger>
          </TabsList>

          {/* ---------------------------------------------------------------- credentials */}
          <TabsContent value="credentials" className="mt-4 grid gap-4 lg:grid-cols-2">
            <Panel title="Shopify — read-only custom app" testId="shopify-credentials">
              <div className="space-y-3 p-4">
                <p className="text-[11px] leading-relaxed text-[#a3a3a3]">
                  Required Admin API scopes: {c.shopify.required_read_scopes.join(", ")}. No write scope is
                  requested and no write route exists.
                </p>
                <div>
                  <label className="label-caps">Store domain</label>
                  <input value={shopify.shop_domain} placeholder="urbandotted.myshopify.com"
                    data-testid="shopify-domain-input" className={INPUT}
                    onChange={(e) => setShopify({ ...shopify, shop_domain: e.target.value })} />
                </div>
                <div>
                  <label className="label-caps flex items-center gap-1.5"><Lock className="h-3 w-3" /> Admin API access token</label>
                  <input type="password" value={shopify.admin_api_token} data-testid="shopify-token-input"
                    autoComplete="off" className={INPUT}
                    onChange={(e) => setShopify({ ...shopify, admin_api_token: e.target.value })} />
                </div>
                <div>
                  <label className="label-caps flex items-center gap-1.5"><Lock className="h-3 w-3" /> Webhook signing secret (optional)</label>
                  <input type="password" value={shopify.webhook_secret} data-testid="shopify-webhook-secret-input"
                    autoComplete="off" className={INPUT}
                    onChange={(e) => setShopify({ ...shopify, webhook_secret: e.target.value })} />
                </div>
                <button className={BTN} data-testid="shopify-save-button" disabled={saveShopify.isPending}
                  onClick={() => saveShopify.mutate()}>
                  {saveShopify.isPending && lastPath === "/admin/connections/shopify"
                    ? <><Loader2 className="h-3.5 w-3.5 animate-spin" /> Verifying with Shopify…</>
                    : <><ShieldCheck className="h-3.5 w-3.5" /> Save & verify (read-only call)</>}
                </button>
                {saveShopify.data?.shopify && (
                  <div className="border border-[#34C759]/40 bg-[#34C759]/5 p-3" data-testid="shopify-verified">
                    <EvidenceRow label="shop" value={saveShopify.data.shopify.shop_name} />
                    <EvidenceRow label="primary domain" value={saveShopify.data.shopify.primary_domain} />
                    {saveShopify.data.shopify.markets.map((m) => (
                      <EvidenceRow key={m.handle} label={`market ${m.handle}`}
                        value={`${m.countries?.join(",")} · ${m.root_urls?.[0] || "—"}`} />
                    ))}
                  </div>
                )}
              </div>
            </Panel>

            <Panel title="Search Console — service account" testId="gsc-credentials">
              <div className="space-y-3 p-4">
                <p className="text-[11px] leading-relaxed text-[#a3a3a3]">
                  Paste the service-account JSON here (this field is a secret input — the value is written
                  only to the backend environment and never echoed back). Add{" "}
                  {c.gsc.service_account_email || "the service account email"} to the property in Search
                  Console with the minimum permission that returns performance data.
                </p>
                <div>
                  <label className="label-caps">Property</label>
                  <input value={gsc.site_url} placeholder="sc-domain:urbandotted.com"
                    data-testid="gsc-site-input" className={INPUT}
                    onChange={(e) => setGsc({ ...gsc, site_url: e.target.value })} />
                </div>
                <div>
                  <label className="label-caps flex items-center gap-1.5"><Lock className="h-3 w-3" /> Service account JSON</label>
                  <textarea rows={5} value={gsc.service_account_json} data-testid="gsc-json-input"
                    spellCheck={false} className={INPUT}
                    onChange={(e) => setGsc({ ...gsc, service_account_json: e.target.value })} />
                </div>
                <button className={BTN} data-testid="gsc-save-button" disabled={saveGsc.isPending}
                  onClick={() => saveGsc.mutate()}>
                  {saveGsc.isPending && lastPath === "/admin/connections/gsc"
                    ? <><Loader2 className="h-3.5 w-3.5 animate-spin" /> Verifying property access…</>
                    : <><ShieldCheck className="h-3.5 w-3.5" /> Save & verify property access</>}
                </button>
                {saveGsc.data?.gsc && (
                  <div className="border border-[#34C759]/40 bg-[#34C759]/5 p-3" data-testid="gsc-verified">
                    <EvidenceRow label="property" value={saveGsc.data.gsc.site_url} />
                    <EvidenceRow label="permission" value={saveGsc.data.gsc.permission_level} />
                    <EvidenceRow label="days with data" value={saveGsc.data.gsc.available_range?.days_with_data} />
                    <EvidenceRow label="first date" value={saveGsc.data.gsc.available_range?.first_date} />
                    <EvidenceRow label="last date" value={saveGsc.data.gsc.available_range?.last_date} />
                  </div>
                )}
              </div>
            </Panel>

            <Panel title="BigQuery bulk export (preferred ongoing source)" testId="bq-credentials">
              <div className="space-y-3 p-4">
                <div className="grid gap-3 sm:grid-cols-3">
                  <div>
                    <label className="label-caps">Project</label>
                    <input value={bq.project} data-testid="bq-project-input" className={INPUT}
                      onChange={(e) => setBq({ ...bq, project: e.target.value })} />
                  </div>
                  <div>
                    <label className="label-caps">Dataset</label>
                    <input value={bq.dataset} data-testid="bq-dataset-input" className={INPUT}
                      onChange={(e) => setBq({ ...bq, dataset: e.target.value })} />
                  </div>
                  <div>
                    <label className="label-caps">Location</label>
                    <input value={bq.location} placeholder="US" data-testid="bq-location-input" className={INPUT}
                      onChange={(e) => setBq({ ...bq, location: e.target.value })} />
                  </div>
                </div>
                <button className={BTN} data-testid="bq-save-button" disabled={saveBq.isPending}
                  onClick={() => saveBq.mutate()}>Save & verify dataset</button>
              </div>
            </Panel>

            <Panel title="Crawl politeness + go live" testId="crawl-settings">
              <div className="space-y-3 p-4">
                <div className="grid gap-3 sm:grid-cols-2">
                  <div>
                    <label className="label-caps">Requests / sec (combined)</label>
                    <input type="number" step="0.5" min="0.2" max="10" value={crawl.requests_per_sec}
                      data-testid="crawl-rate-input" className={INPUT}
                      onChange={(e) => setCrawl({ ...crawl, requests_per_sec: Number(e.target.value) })} />
                  </div>
                  <div>
                    <label className="label-caps">Workers</label>
                    <input type="number" min="1" max="10" value={crawl.workers}
                      data-testid="crawl-workers-input" className={INPUT}
                      onChange={(e) => setCrawl({ ...crawl, workers: Number(e.target.value) })} />
                  </div>
                </div>
                <button className={GHOST} data-testid="crawl-save-button" disabled={saveCrawl.isPending}
                  onClick={() => saveCrawl.mutate()}>Save crawl ceiling</button>
                <div className="border-t border-[#262626] pt-3">
                  <p className="text-[11px] leading-relaxed text-[#a3a3a3]">
                    Activating LIVE mode requires both Shopify and Search Console to verify. Seeded fixtures
                    are then excluded from every read. DEMO mode is retained as an explicit development
                    adapter and can be switched back on.
                  </p>
                  <button className={`${BTN} mt-3`} data-testid="activate-live-button" disabled={activate.isPending}
                    onClick={() => activate.mutate()}>Activate LIVE data mode</button>
                </div>
              </div>
            </Panel>
          </TabsContent>

          {/* ---------------------------------------------------------------- shopify */}
          <TabsContent value="shopify" className="mt-4 space-y-4">
            <Panel title="Catalogue sync" testId="shopify-sync-panel"
              action={
                <div className="flex flex-wrap gap-2">
                  <button className={GHOST} data-testid="run-sync-button" onClick={() => runSync.mutate()}>
                    <Play className="h-3 w-3" /> Full sync
                  </button>
                  <button className={GHOST} data-testid="run-reconcile-button" onClick={() => runReconcile.mutate()}>
                    Nightly reconcile now
                  </button>
                  <button className={GHOST} data-testid="register-webhooks-button" onClick={() => registerHooks.mutate()}>
                    Register webhooks
                  </button>
                </div>
              }>
              <div className="grid gap-px bg-[#262626] sm:grid-cols-3 lg:grid-cols-5">
                {Object.entries(syncStatus.data?.catalogue || {}).map(([k, v]) => (
                  <div key={k} className="bg-[#141414] p-3">
                    <span className="label-caps">{k.replace(/_/g, " ")}</span>
                    <p className="num mt-0.5 text-lg">{fmt.int(v)}</p>
                  </div>
                ))}
              </div>
              {(syncStatus.data?.runs || []).length === 0 ? <Empty label="No sync run recorded yet" /> : (
                <ul className="divide-y divide-[#262626]">
                  {syncStatus.data.runs.map((r) => (
                    <li key={r.id} className="p-4" data-testid={`sync-run-${r.id}`}>
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="num text-xs">{r.kind}</span>
                        <span className={`text-[10px] font-semibold uppercase ${
                          r.status === "success" ? "text-[#34C759]" : r.status === "running" ? "text-[#007AFF]" : "text-[#FF3B30]"}`}>
                          {r.status}
                        </span>
                        <span className="label-caps">{r.data_mode}</span>
                        <span className="num ml-auto text-[10px] text-[#525252]">{fmt.ago(r.started_at)}</span>
                      </div>
                      {r.report && (
                        <div className="mt-2 grid gap-x-6 sm:grid-cols-2">
                          {Object.entries(r.report.counters || {}).map(([k, v]) => (
                            <EvidenceRow key={k} label={k} value={fmt.int(v)} />
                          ))}
                          <EvidenceRow label="duration (s)" value={r.report.duration_seconds} />
                          <EvidenceRow label="requests" value={r.report.requests} />
                          <EvidenceRow label="retries" value={r.report.retries} />
                          <EvidenceRow label="throttled" value={r.report.throttled} />
                          <EvidenceRow label="invalid records" value={r.report.invalid_count} />
                        </div>
                      )}
                      {r.market_mapping && (
                        <p className="num mt-2 text-[10px] text-[#737373]">
                          markets: {Object.entries(r.market_mapping).map(([m, v]) => `${m}→${v.root_url}`).join("  ")}
                        </p>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </Panel>

            <Panel title="Webhook ingestion" testId="webhooks-panel">
              <div className="grid gap-px bg-[#262626] sm:grid-cols-3">
                {[["Total events", c.webhooks?.total_events], ["Unverified rejected", c.webhooks?.unverified_rejected],
                  ["Subscribed topics", c.webhooks?.subscribed_topics?.length]].map(([k, v]) => (
                  <div key={k} className="bg-[#141414] p-3">
                    <span className="label-caps">{k}</span>
                    <p className="num mt-0.5 text-lg">{fmt.int(v)}</p>
                  </div>
                ))}
              </div>
              {(c.webhooks?.recent || []).length === 0
                ? <Empty label="No webhook deliveries received yet" />
                : (
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="border-b border-[#262626] text-left">
                        {["Topic", "Status", "HMAC", "Entity", "Attempts", "Received"].map((h) => (
                          <th key={h} className="label-caps px-3 py-2">{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {c.webhooks.recent.map((w, i) => (
                        <tr key={i} className="border-b border-[#262626]">
                          <td className="num px-3 py-1.5">{w.topic}</td>
                          <td className="px-3 py-1.5">{w.status}</td>
                          <td className={`px-3 py-1.5 ${w.hmac_verified ? "text-[#34C759]" : "text-[#FF3B30]"}`}>
                            {String(w.hmac_verified)}
                          </td>
                          <td className="num max-w-[200px] truncate px-3 py-1.5">{w.shopify_gid}</td>
                          <td className="num px-3 py-1.5">{w.attempts}</td>
                          <td className="num px-3 py-1.5 text-[#737373]">{fmt.ago(w.received_at)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
            </Panel>
          </TabsContent>

          {/* ---------------------------------------------------------------- gsc */}
          <TabsContent value="gsc" className="mt-4 space-y-4">
            <Panel title="Ingest" testId="gsc-ingest-panel"
              action={
                <div className="flex flex-wrap gap-2">
                  <button className={GHOST} data-testid="run-bootstrap-button" onClick={() => runBootstrap.mutate()}>
                    <Play className="h-3 w-3" /> Bootstrap {c.gsc_bootstrap_months}mo (API)
                  </button>
                  <button className={GHOST} data-testid="run-daily-button" onClick={() => runDaily.mutate()}>Daily ingest</button>
                  <button className={GHOST} data-testid="run-recon-button" onClick={() => runRecon.mutate()}>URL reconciliation</button>
                  <button className={GHOST} data-testid="run-recompute-button" onClick={() => runRecompute.mutate()}>Recompute intelligence</button>
                </div>
              }>
              {(gscStatus.data?.by_market_and_source || []).length === 0
                ? <Empty label="No live GSC rows ingested yet" />
                : (
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-[#262626] text-left">
                        {["Market", "Source", "Rows", "Impressions", "Clicks", "Date coverage"].map((h) => (
                          <th key={h} className="label-caps px-3 py-2">{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {gscStatus.data.by_market_and_source.map((r, i) => (
                        <tr key={i} className="border-b border-[#262626] last:border-0">
                          <td className="label-caps px-3 py-2">{r.market}</td>
                          <td className="num px-3 py-2 text-xs">{r.source}</td>
                          <td className="num px-3 py-2 text-xs">{fmt.int(r.rows)}</td>
                          <td className="num px-3 py-2 text-xs">{fmt.int(r.impressions)}</td>
                          <td className="num px-3 py-2 text-xs">{fmt.int(r.clicks)}</td>
                          <td className="num px-3 py-2 text-xs">{r.date_coverage?.join(" → ")}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
            </Panel>

            <Panel title="URL reconciliation (unmatched URLs are retained, never discarded)" testId="recon-panel">
              {recon.data?.report ? (
                <>
                  <div className="grid gap-px bg-[#262626] sm:grid-cols-3 lg:grid-cols-4">
                    <div className="bg-[#141414] p-3">
                      <span className="label-caps">Match rate</span>
                      <p className="num mt-0.5 text-lg">{fmt.pct(recon.data.report.match_rate_pct, 2)}</p>
                    </div>
                    <div className="bg-[#141414] p-3">
                      <span className="label-caps">Impression coverage</span>
                      <p className="num mt-0.5 text-lg">{fmt.pct(recon.data.report.impression_coverage_pct, 2)}</p>
                    </div>
                    {Object.entries(recon.data.report.buckets || {}).map(([k, v]) => (
                      <div key={k} className="bg-[#141414] p-3">
                        <span className="label-caps">{k.replace(/_/g, " ")}</span>
                        <p className="num mt-0.5 text-lg">{fmt.int(v)}</p>
                      </div>
                    ))}
                  </div>
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="border-b border-[#262626] text-left">
                        {["URL", "Market", "Category", "Impr", "Clicks"].map((h) => (
                          <th key={h} className="label-caps px-3 py-2">{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {(recon.data.rows || []).map((r) => (
                        <tr key={r.id} className="border-b border-[#262626]">
                          <td className="num max-w-[320px] truncate px-3 py-1.5 text-[#007AFF]">{r.url}</td>
                          <td className="label-caps px-3 py-1.5">{r.market}</td>
                          <td className="px-3 py-1.5">{r.category}</td>
                          <td className="num px-3 py-1.5">{fmt.int(r.impressions)}</td>
                          <td className="num px-3 py-1.5">{fmt.int(r.clicks)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </>
              ) : <Empty label="Run URL reconciliation after the first GSC ingest" />}
            </Panel>
          </TabsContent>

          {/* ---------------------------------------------------------------- crawler */}
          <TabsContent value="crawl" className="mt-4 space-y-4">
            <Panel title="Read-only crawler" testId="crawler-panel"
              action={
                <div className="flex flex-wrap gap-2">
                  <button className={GHOST} data-testid="run-robots-button" onClick={() => runRobots.mutate()}>
                    Fetch robots + sitemaps
                  </button>
                  <button className={GHOST} data-testid="run-crawl-batch-button" onClick={() => runCrawlBatch.mutate()}>
                    <Play className="h-3 w-3" /> Validation batch (25)
                  </button>
                  <button className={GHOST} data-testid="run-crawl-full-button" onClick={() => runCrawlFull.mutate()}>
                    Scale up
                  </button>
                </div>
              }>
              <div className="grid gap-px bg-[#262626] sm:grid-cols-3 lg:grid-cols-5">
                {[
                  ["URL inventory", fmt.int(crawlStatus.data?.url_inventory)],
                  ["Crawled", fmt.int(crawlStatus.data?.urls_with_crawl_data)],
                  ["Coverage", fmt.pct(crawlStatus.data?.coverage_pct, 2)],
                  ["Configured rate", `${crawlStatus.data?.configured?.requests_per_sec}/s`],
                  ["Effective rate", `${crawlStatus.data?.configured?.effective_rate_per_sec}/s`],
                ].map(([k, v]) => (
                  <div key={k} className="bg-[#141414] p-3">
                    <span className="label-caps">{k}</span>
                    <p className="num mt-0.5 text-lg">{v}</p>
                  </div>
                ))}
              </div>
              {(crawlStatus.data?.runs || []).length === 0 ? <Empty label="No crawl run recorded yet" /> : (
                <ul className="divide-y divide-[#262626]">
                  {crawlStatus.data.runs.map((r) => (
                    <li key={r.id} className="grid gap-x-6 p-4 sm:grid-cols-2" data-testid={`crawl-run-${r.id}`}>
                      <EvidenceRow label="urls crawled" value={fmt.int(r.urls_crawled)} />
                      <EvidenceRow label="throughput / s" value={r.throughput_urls_per_sec} />
                      <EvidenceRow label="failures" value={r.failures} />
                      <EvidenceRow label="retries / adjustments" value={r.retries} />
                      <EvidenceRow label="429s" value={r.throttled_429} />
                      <EvidenceRow label="5xx" value={r.server_errors_5xx} />
                      <EvidenceRow label="avg latency" value={`${fmt.int(r.avg_latency_ms)} ms`} />
                      <EvidenceRow label="p95 latency" value={`${fmt.int(r.p95_latency_ms)} ms`} />
                      <EvidenceRow label="issues written" value={r.issues_written} />
                      <EvidenceRow label="duration (s)" value={r.duration_seconds} />
                      <EvidenceRow label="status codes" value={JSON.stringify(r.status_code_distribution)} />
                      <EvidenceRow label="effective rate" value={`${r.effective_rate_per_sec}/s`} />
                    </li>
                  ))}
                </ul>
              )}
            </Panel>
          </TabsContent>

          {/* ---------------------------------------------------------------- report */}
          <TabsContent value="report" className="mt-4 space-y-4">
            <Panel title="LIVE DATA ACCEPTANCE REPORT" testId="acceptance-report"
              action={
                <button className={GHOST} data-testid="purge-fixtures-button"
                  onClick={() => setConfirmPurge(true)}>
                  Purge demo fixtures
                </button>
              }>
              {report.isLoading ? <Loading /> : report.error ? <ErrorState error={report.error} /> : (
                <div className="space-y-4 p-4">
                  {confirmPurge && (
                    <div className="border border-[#FF3B30] bg-[#FF3B30]/10 p-3" data-testid="purge-confirm">
                      <p className="text-xs text-[#FF6B62]">
                        This permanently deletes every seeded DEMO row (catalogue, GSC, scores, issues).
                        The audit log is untouched. Type PURGE to confirm.
                      </p>
                      <div className="mt-2 flex flex-wrap gap-2">
                        <input value={purgeText} onChange={(e) => setPurgeText(e.target.value)}
                          data-testid="purge-confirm-input" placeholder="PURGE"
                          className="num border border-[#262626] bg-[#0a0a0a] px-3 py-1.5 text-xs outline-none focus:border-[#FF3B30]" />
                        <button disabled={purgeText !== "PURGE"} data-testid="purge-confirm-button"
                          onClick={() => { purge.mutate(); setConfirmPurge(false); setPurgeText(""); }}
                          className="border border-[#FF3B30] px-3 py-1.5 text-xs text-[#FF6B62] transition-colors duration-150 hover:bg-[#FF3B30]/20 disabled:opacity-40">
                          Confirm purge
                        </button>
                        <button onClick={() => { setConfirmPurge(false); setPurgeText(""); }}
                          data-testid="purge-cancel-button" className={GHOST}>Cancel</button>
                      </div>
                    </div>
                  )}
                  <section>
                    <h4 className="label-caps mb-1">Provenance</h4>
                    {Object.entries(report.data.provenance).map(([k, v]) => (
                      <EvidenceRow key={k} label={k.replace(/_/g, " ")} value={v} />
                    ))}
                  </section>
                  <section>
                    <h4 className="label-caps mb-1">Catalogue</h4>
                    {Object.entries(report.data.catalogue).map(([k, v]) => (
                      <EvidenceRow key={k} label={k.replace(/_/g, " ")} value={fmt.int(v)} />
                    ))}
                  </section>
                  <section>
                    <h4 className="label-caps mb-1">Tier distribution (live)</h4>
                    {report.data.tier_distribution.length === 0 ? <Empty label="No live scores yet" /> :
                      report.data.tier_distribution.map((t) => (
                        <EvidenceRow key={t.tier} label={`tier ${t.tier}`}
                          value={`total ${t.total} · AU ${t.AU || 0} · NZ ${t.NZ || 0}`} />
                      ))}
                  </section>
                  <section>
                    <h4 className="label-caps mb-1">Failures and retries</h4>
                    {Object.entries(report.data.failures_and_retries).map(([k, v]) => (
                      <EvidenceRow key={k} label={k.replace(/_/g, " ")}
                        value={Array.isArray(v) ? (v.length ? v.join("; ") : "none") : String(v ?? "—")} />
                    ))}
                  </section>
                  <section>
                    <h4 className="label-caps mb-1">Stage 1 invariants</h4>
                    {Object.entries(report.data.stage1_invariants).map(([k, v]) => (
                      <EvidenceRow key={k} label={k.replace(/_/g, " ")}
                        value={Array.isArray(v) ? (v.length ? v.join(", ") : "none") : String(v)} />
                    ))}
                  </section>
                  <section>
                    <h4 className="label-caps mb-1">Paid API and LLM usage</h4>
                    <EvidenceRow label="spend" value={fmt.usd(report.data.paid_api_usage.spend_usd, 4)} />
                    <EvidenceRow label="cap" value={fmt.usd(report.data.paid_api_usage.global_cap_usd, 0)} />
                    <EvidenceRow label="used" value={fmt.pct(report.data.paid_api_usage.pct_used)} />
                    <EvidenceRow label="blocked calls" value={report.data.paid_api_usage.blocked_calls} />
                    {(report.data.paid_api_usage.by_provider || []).map((p) => (
                      <EvidenceRow key={p.provider} label={p.provider}
                        value={`${fmt.usd(p.spend_usd, 4)} · ${p.calls} calls`} />
                    ))}
                  </section>
                  {Object.entries(report.data.top_20_opportunities || {}).map(([market, rows]) => (
                    <section key={market}>
                      <h4 className="label-caps mb-2">Top 20 opportunities — {market}</h4>
                      {rows.length === 0 ? <Empty label={`No live ${market} opportunities yet`} /> : (
                        <table className="w-full text-xs">
                          <thead>
                            <tr className="border-b border-[#262626] text-left">
                              {["Score", "Tier", "Entity", "Impr", "Clicks", "Pos", "Evidence"].map((h) => (
                                <th key={h} className="label-caps py-1.5">{h}</th>
                              ))}
                            </tr>
                          </thead>
                          <tbody>
                            {rows.map((o) => (
                              <tr key={o.id} className="border-b border-[#262626]">
                                <td className="num py-1.5">{fmt.dec(o.score)}</td>
                                <td className="num py-1.5">{o.tier}</td>
                                <td className="max-w-[200px] truncate py-1.5">{o.entity_label}</td>
                                <td className="num py-1.5">{fmt.int(o.evidence?.impressions_30d)}</td>
                                <td className="num py-1.5">{fmt.int(o.evidence?.clicks_30d)}</td>
                                <td className="num py-1.5">{fmt.dec(o.evidence?.avg_position)}</td>
                                <td className="num max-w-[220px] truncate py-1.5 text-[#737373]">
                                  {JSON.stringify(o.evidence)}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      )}
                    </section>
                  ))}
                </div>
              )}
            </Panel>
          </TabsContent>
        </Tabs>
      </div>
    </div>
  );
}
