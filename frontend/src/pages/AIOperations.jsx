import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Play } from "lucide-react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { ActivityDot, PageHeader, StageNotice } from "@/components/Layout";
import { Empty, ErrorState, EvidenceRow, Loading, MetricCard, Panel } from "@/components/ui-kit";
import { fmt, get, post } from "@/lib/api";

const KIND_STYLE = {
  llm: "border-[#007AFF] text-[#007AFF]",
  service: "border-[#262626] text-[#a3a3a3]",
};

function ActivityDrawer({ row, onClose }) {
  return (
    <Sheet open={Boolean(row)} onOpenChange={(o) => !o && onClose()}>
      <SheetContent side="right" className="w-full overflow-y-auto border-l border-[#262626] bg-[#141414] sm:max-w-lg" data-testid="activity-drawer">
        {!row && (
          <SheetHeader>
            <SheetTitle className="sr-only">Agent run detail</SheetTitle>
          </SheetHeader>
        )}
        {row && (
          <>
            <SheetHeader>
              <SheetTitle className="flex items-center gap-2 text-left text-lg">
                <ActivityDot status={row.status} />
                <span className="num break-words">{row.job}</span>
              </SheetTitle>
            </SheetHeader>
            <p className="mt-1 text-xs text-[#a3a3a3]">
              {row.role?.name} · {row.role?.kind === "llm" ? "LLM agent" : "deterministic service"}
            </p>
            <div className="mt-5">
              <EvidenceRow label="status" value={row.status} />
              <EvidenceRow label="actor" value={row.actor} />
              <EvidenceRow label="queue backend" value={row.queue_backend} />
              <EvidenceRow label="started" value={fmt.time(row.started_at)} />
              <EvidenceRow label="finished" value={fmt.time(row.finished_at)} />
              <EvidenceRow label="duration" value={`${fmt.int(row.duration_ms)} ms`} />
              {row.error && <EvidenceRow label="error" value={row.error} mono={false} />}
              {row.result && Object.entries(row.result).map(([k, v]) => (
                <EvidenceRow key={k} label={`result · ${k}`} value={typeof v === "object" ? JSON.stringify(v) : String(v)} />
              ))}
            </div>
            <p className="mt-4 text-[11px] leading-relaxed text-[#737373]">{row.role?.description}</p>
          </>
        )}
      </SheetContent>
    </Sheet>
  );
}

export default function AIOperations() {
  const qc = useQueryClient();
  const [focus, setFocus] = useState(null);
  const [memoryType, setMemoryType] = useState("");

  const roles = useQuery({ queryKey: ["agent-roles"], queryFn: () => get("/agents/roles") });
  const activity = useQuery({ queryKey: ["agent-activity"], queryFn: () => get("/agents/activity", { limit: 40 }) });
  const memory = useQuery({ queryKey: ["memory", memoryType], queryFn: () => get("/memory", { memory_type: memoryType || undefined, limit: 40 }) });
  const pipelines = useQuery({ queryKey: ["pipelines"], queryFn: () => get("/pipelines") });
  const actions = useQuery({ queryKey: ["actions"], queryFn: () => get("/actions") });

  const run = useMutation({
    mutationFn: (job) => post(`/pipelines/${job}/run`),
    onSuccess: (r) => {
      if (r.status === "success") toast.success(`${r.job} completed: ${JSON.stringify(r.result)}`);
      else toast.error(`${r.job} failed: ${r.error}`);
      qc.invalidateQueries({ queryKey: ["agent-activity"] });
      qc.invalidateQueries({ queryKey: ["agent-roles"] });
      qc.invalidateQueries({ queryKey: ["pipelines"] });
    },
    onError: (e) => toast.error(e.response?.data?.detail || "Pipeline run failed"),
  });

  const llmCount = roles.data?.rows?.filter((r) => r.kind === "llm").length || 0;

  return (
    <div>
      <PageHeader
        title="AI Operations"
        testId="ai-operations-title"
        description="All 28 logical roles: 7 true LLM agents and 21 deterministic services. Deterministic work never burns tokens; the LLM router is used only where judgement is required."
      />

      <div className="space-y-4 p-4 sm:p-6">
        <StageNotice />

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <MetricCard label="Logical roles" value={fmt.int(roles.data?.total)} sub={`${llmCount} LLM · ${(roles.data?.total || 0) - llmCount} services`} testId="ai-metric-roles" />
          <MetricCard label="Runs recorded" value={fmt.int(activity.data?.total)} sub="agent activity timeline" testId="ai-metric-runs" />
          <MetricCard label="Memory records" value={fmt.int(memory.data?.total)} sub="evidence + confidence + sample size" testId="ai-metric-memory" />
          <MetricCard label="Proposed actions" value={fmt.int(actions.data?.rows?.length)} sub="all blocked in Stage 1" testId="ai-metric-actions" />
        </div>

        <Tabs defaultValue="activity">
          <TabsList className="border border-[#262626] bg-[#141414]">
            <TabsTrigger value="activity" data-testid="tab-activity">Agent activity</TabsTrigger>
            <TabsTrigger value="roles" data-testid="tab-roles">Roles</TabsTrigger>
            <TabsTrigger value="memory" data-testid="tab-memory">Memory</TabsTrigger>
            <TabsTrigger value="actions" data-testid="tab-actions">Proposed actions</TabsTrigger>
          </TabsList>

          <TabsContent value="activity" className="mt-4 space-y-4">
            <Panel title="Run a deterministic pipeline" testId="pipelines-panel">
              <div className="flex flex-wrap gap-2 p-4">
                {(pipelines.data?.rows || []).map((p) => (
                  <button key={p.job} onClick={() => run.mutate(p.job)} disabled={run.isPending}
                    data-testid={`run-pipeline-${p.job}`}
                    className="flex items-center gap-2 border border-[#262626] px-3 py-1.5 text-xs transition-colors duration-150 hover:bg-[#262626] disabled:opacity-50">
                    <Play className="h-3 w-3" />
                    <span className="num">{p.job}</span>
                    <span className="text-[10px] text-[#737373]">{fmt.ago(p.last_started)}</span>
                  </button>
                ))}
              </div>
            </Panel>

            <Panel title="Timeline" testId="activity-panel">
              {activity.isLoading ? <Loading /> : activity.error ? <ErrorState error={activity.error} /> :
                activity.data.rows.length === 0 ? <Empty /> : (
                  <div className="overflow-x-auto">
                    <table className="w-full min-w-[720px] text-sm">
                      <thead>
                        <tr className="border-b border-[#262626] text-left">
                          {["", "Job", "Role", "Kind", "Status", "Duration", "Started"].map((h, i) => (
                            <th key={i} className="label-caps whitespace-nowrap px-3 py-2">{h}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {activity.data.rows.map((r) => (
                          <tr key={r.id} onClick={() => setFocus(r)} data-testid={`activity-row-${r.id}`}
                            className="row-hover cursor-pointer border-b border-[#262626] last:border-0">
                            <td className="px-3 py-2"><ActivityDot status={r.status} /></td>
                            <td className="num px-3 py-2 text-xs">{r.job}</td>
                            <td className="px-3 py-2 text-xs text-[#a3a3a3]">{r.role?.name || r.agent_role}</td>
                            <td className="px-3 py-2">
                              <span className={`border px-1.5 py-0.5 text-[10px] uppercase ${KIND_STYLE[r.role?.kind] || KIND_STYLE.service}`}>
                                {r.role?.kind || "service"}
                              </span>
                            </td>
                            <td className="px-3 py-2 text-xs">{r.status}</td>
                            <td className="num px-3 py-2 text-xs">{r.duration_ms ? `${fmt.int(r.duration_ms)} ms` : "—"}</td>
                            <td className="num px-3 py-2 text-[11px] text-[#737373]">{fmt.ago(r.started_at)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
            </Panel>
          </TabsContent>

          <TabsContent value="roles" className="mt-4">
            <Panel title="28 logical roles" testId="roles-panel">
              {roles.isLoading ? <Loading /> : (
                <div className="grid gap-px bg-[#262626] sm:grid-cols-2 xl:grid-cols-3">
                  {roles.data.rows.map((r) => (
                    <div key={r.key} className="bg-[#141414] p-4" data-testid={`role-card-${r.key}`}>
                      <div className="flex items-start justify-between gap-2">
                        <span className="text-sm font-medium">{r.name}</span>
                        <span className={`shrink-0 border px-1.5 py-0.5 text-[10px] uppercase ${KIND_STYLE[r.kind]}`}>{r.kind}</span>
                      </div>
                      <p className="mt-1.5 text-[11px] leading-relaxed text-[#a3a3a3]">{r.description}</p>
                      <div className="mt-2.5 flex items-center gap-3 border-t border-[#262626] pt-2">
                        <ActivityDot status={r.status} />
                        <span className="num text-[10px] text-[#a3a3a3]">{r.runs} runs</span>
                        {r.failures > 0 && <span className="num text-[10px] text-[#FF3B30]">{r.failures} failed</span>}
                        <span className="num text-[10px] text-[#a3a3a3]">{fmt.usd(r.spend_usd, 4)}</span>
                        <span className="num ml-auto text-[10px] text-[#525252]">{fmt.ago(r.last_run_at)}</span>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </Panel>
          </TabsContent>

          <TabsContent value="memory" className="mt-4 space-y-4">
            <div className="flex flex-wrap gap-2">
              {["", "business", "seo_knowledge", "failure", "decision"].map((t) => (
                <button key={t || "all"} onClick={() => setMemoryType(t)} data-testid={`memory-filter-${t || "all"}`}
                  className={`border px-3 py-1.5 text-xs transition-colors duration-150 ${
                    memoryType === t ? "border-white bg-white text-black" : "border-[#262626] text-[#a3a3a3] hover:bg-[#262626]"
                  }`}>
                  {t ? t.replace("_", " ") : "all"}
                  {memory.data?.facets?.[t] ? ` (${memory.data.facets[t]})` : ""}
                </button>
              ))}
            </div>

            <Panel title="Memory records" testId="memory-panel">
              {memory.isLoading ? <Loading /> : memory.data.rows.length === 0 ? <Empty /> : (
                <ul className="divide-y divide-[#262626]">
                  {memory.data.rows.map((m) => (
                    <li key={m.id} className="p-4" data-testid={`memory-row-${m.id}`}>
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="label-caps">{m.memory_type}</span>
                        <span className="num text-[10px] text-[#34C759]">conf {fmt.dec((m.confidence || 0) * 100, 0)}%</span>
                        <span className="num text-[10px] text-[#a3a3a3]">n={m.sample_size}</span>
                        <span className="num text-[10px] text-[#525252]">{m.agent_role}</span>
                        <span className="num ml-auto text-[10px] text-[#525252]">recheck {fmt.time(m.recheck_at)}</span>
                      </div>
                      <p className="mt-1.5 text-sm font-medium">{m.title}</p>
                      <p className="mt-1 text-xs leading-relaxed text-[#a3a3a3]">{m.content}</p>
                      {m.evidence && (
                        <p className="num mt-2 border-l-2 border-[#007AFF] pl-2 text-[10px] text-[#737373]">
                          evidence: {JSON.stringify(m.evidence)}
                        </p>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </Panel>

            <Panel title="Decision records" testId="decisions-panel">
              <ul className="divide-y divide-[#262626]">
                {(memory.data?.decisions || []).map((d) => (
                  <li key={d.id} className="p-4">
                    <div className="flex items-center gap-2">
                      <span className="label-caps">{d.outcome}</span>
                      <span className="num text-[10px] text-[#525252]">{d.decided_by}</span>
                    </div>
                    <p className="mt-1 text-sm font-medium">{d.title}</p>
                    <p className="mt-1 text-xs text-[#a3a3a3]">{d.rationale}</p>
                  </li>
                ))}
              </ul>
            </Panel>
          </TabsContent>

          <TabsContent value="actions" className="mt-4">
            <Panel title="Proposed actions (Stage 1: never executed)" testId="actions-panel">
              {actions.isLoading ? <Loading /> : actions.data.rows.length === 0 ? <Empty label="No actions proposed yet" /> : (
                <ul className="divide-y divide-[#262626]">
                  {actions.data.rows.map((a) => (
                    <li key={a.id} className="p-4" data-testid={`action-row-${a.id}`}>
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="border border-[#FF3B30] px-1.5 py-0.5 text-[10px] font-semibold text-[#FF3B30]">
                          {a.risk_class} · {a.policy_decision}
                        </span>
                        <span className="num text-xs">{a.action_type}</span>
                        <span className="num text-[10px] text-[#525252]">{a.entity_type} · {a.entity_id}</span>
                      </div>
                      <div className="mt-2 grid gap-2 sm:grid-cols-2">
                        <div className="border border-[#262626] p-2">
                          <span className="label-caps">previous value</span>
                          <p className="num mt-1 text-[11px] text-[#a3a3a3]">{String(a.previous_value)}</p>
                        </div>
                        <div className="border border-[#262626] p-2">
                          <span className="label-caps">proposed value</span>
                          <p className="num mt-1 text-[11px] text-[#f5f5f5]">{String(a.proposed_value)}</p>
                        </div>
                      </div>
                      <p className="mt-2 text-xs text-[#a3a3a3]">{a.rationale}</p>
                      <p className="num mt-1.5 text-[10px] text-[#737373]">evidence: {JSON.stringify(a.evidence)}</p>
                      <p className="mt-1 text-[10px] text-[#FFCC00]">{a.execution_note}</p>
                    </li>
                  ))}
                </ul>
              )}
            </Panel>
          </TabsContent>
        </Tabs>
      </div>

      <ActivityDrawer row={focus} onClose={() => setFocus(null)} />
    </div>
  );
}
