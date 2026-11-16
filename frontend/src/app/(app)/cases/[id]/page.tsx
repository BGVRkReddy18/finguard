"use client";

import Link from "next/link";
import { use, useState } from "react";

import { Badge, Button, Card, ErrorNote, RecommendationBadge, RiskBadge, ScoreBar, Spinner, StatusBadge, cx } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { formatDateTime, formatINR, formatNumber, timeAgo } from "@/lib/format";
import { useLiveRefresh, useSession } from "@/lib/session";
import type { AuditEntry, FraudCase, InvestigationResponse, Paginated, User } from "@/lib/types";
import { useFetch } from "@/lib/useFetch";

const FEATURE_LABELS: [string, string, (v: number) => string][] = [
  ["history_count", "Prior transactions", (v) => formatNumber(v)],
  ["amount_ratio", "Amount vs. customer average", (v) => `${v.toFixed(1)}×`],
  ["km_from_home", "Distance from usual location", (v) => `${formatNumber(Math.round(v))} km`],
  ["km_from_last", "Distance from previous txn", (v) => `${formatNumber(Math.round(v))} km`],
  ["minutes_since_last", "Minutes since previous txn", (v) => formatNumber(Math.round(v))],
  ["speed_kmh", "Implied travel speed", (v) => `${formatNumber(Math.round(v))} km/h`],
  ["txn_count_10m", "Transactions in 10 min", (v) => formatNumber(v)],
  ["hour", "Local hour (IST)", (v) => `${String(v).padStart(2, "0")}:00`],
];

const AGENT_STEPS = ["Reading the case and model explanation", "Checking the customer's spending profile",
  "Reviewing recent transactions", "Looking for past cases", "Writing the report"];

export default function CaseDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { user, isManager } = useSession();
  const kase = useFetch(() => api<FraudCase>("core", `/api/cases/${id}/`), [id]);
  const audit = useFetch(
    () => (isManager ? api<Paginated<AuditEntry>>("core", `/api/audit-logs/?entity_type=cases.FraudCase&entity_id=${id}`) : Promise.resolve(null)),
    [id, isManager],
  );
  const users = useFetch(() => (isManager ? api<User[] | Paginated<User>>("core", "/api/auth/users/") : Promise.resolve(null)), [isManager]);

  const [busy, setBusy] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const [trace, setTrace] = useState<InvestigationResponse["tool_calls"] | null>(null);
  const [step, setStep] = useState(0);

  const refresh = () => { kase.reload(); audit.reload(); };
  useLiveRefresh(["ai_report"], refresh, 500);

  const c = kase.data;
  if (kase.error) return <ErrorNote message={kase.error} />;
  if (!c) return <div className="py-20 text-center text-ink-3"><Spinner /></div>;
  const t = c.transaction;
  const mineOrManager = isManager || c.assigned_to?.id === user?.id;
  const userList = Array.isArray(users.data) ? users.data : users.data?.results ?? [];

  const run = async (label: string, fn: () => Promise<unknown>) => {
    setBusy(label);
    setActionError(null);
    try {
      await fn();
      refresh();
    } catch (e) {
      setActionError(e instanceof ApiError || e instanceof Error ? e.message : "Action failed");
    } finally {
      setBusy(null);
    }
  };

  const investigate = () => run("ai", async () => {
    setTrace(null);
    setStep(0);
    const ticker = setInterval(() => setStep((s) => Math.min(s + 1, AGENT_STEPS.length - 1)), 1600);
    try {
      const res = await api<InvestigationResponse>("ai", `/investigate/${c.id}`, { method: "POST" });
      setTrace(res.tool_calls);
    } finally {
      clearInterval(ticker);
    }
  });
  const assign = (userId?: number) => run("assign", () => api("core", `/api/cases/${c.id}/assign/`, { method: "POST", json: userId ? { user_id: userId } : {} }));
  const resolve = (status: "CONFIRMED_FRAUD" | "FALSE_POSITIVE") =>
    run(status, () => api("core", `/api/cases/${c.id}/resolve/`, { method: "POST", json: { status, note } }));

  return (
    <>
      <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
        <div>
          <Link href="/cases" className="text-xs text-ink-3 hover:text-ink">← Case queue</Link>
          <h1 className="mt-1 flex flex-wrap items-center gap-2 text-xl font-semibold tracking-tight text-ink">
            Case #{c.id}
            <StatusBadge status={c.status} />
            <Badge tone={c.priority === "HIGH" ? "critical" : "warning"}>{c.priority === "HIGH" ? "High" : "Medium"} priority</Badge>
          </h1>
          <p className="mt-0.5 text-sm text-ink-3">Opened {timeAgo(c.created_at)} · {c.assigned_to ? `assigned to ${c.assigned_to.username}` : "unassigned"}</p>
        </div>
        {!["CONFIRMED_FRAUD", "FALSE_POSITIVE"].includes(c.status) && (
          <div className="flex flex-wrap items-center gap-2">
            {c.assigned_to?.id !== user?.id && <Button onClick={() => assign()} loading={busy === "assign"}>Assign to me</Button>}
            {isManager && userList.length > 0 && (
              <select aria-label="Assign to" defaultValue="" onChange={(e) => e.target.value && assign(Number(e.target.value))}
                className="rounded-lg border border-line bg-surface px-2 py-1.5 text-sm text-ink">
                <option value="">Assign to…</option>
                {userList.map((u) => <option key={u.id} value={u.id}>{u.username} ({u.role.toLowerCase()})</option>)}
              </select>
            )}
          </div>
        )}
      </div>
      {actionError && <div className="mb-3"><ErrorNote message={actionError} /></div>}

      <div className="grid gap-3 lg:grid-cols-3">
        <div className="space-y-3 lg:col-span-2">
          <Card title="Transaction">
            <div className="flex flex-wrap items-end justify-between gap-4">
              <div>
                <div className="text-3xl font-semibold tracking-tight text-ink">{formatINR(t.amount)}</div>
                <div className="mt-1 text-sm text-ink-2">{t.merchant} · {t.merchant_category.replace("_", " ")} · {t.city} · {t.channel}</div>
                <div className="mt-0.5 text-xs text-ink-3">{formatDateTime(t.timestamp)} · customer <span className="font-mono">{t.customer_id}</span></div>
              </div>
              <div className="text-right">
                <div className="text-xs text-ink-3">Fraud score</div>
                <div className="flex items-center gap-2"><ScoreBar score={t.fraud_score} /><RiskBadge level={t.risk_level} /></div>
                <div className="mt-1 text-[11px] text-ink-3">{t.model_version} · {t.scoring_latency_ms?.toFixed(1)} ms</div>
              </div>
            </div>
          </Card>

          <Card title="Why the model flagged it" action={<span className="text-xs text-ink-3">top SHAP contributions</span>}>
            {t.reasons.length ? (
              <ol className="space-y-2">
                {t.reasons.map((r, i) => (
                  <li key={r} className="flex gap-3 text-sm text-ink">
                    <span className="grid h-5 w-5 shrink-0 place-items-center rounded-full bg-surface-2 text-[11px] font-medium text-ink-2">{i + 1}</span>
                    {r}
                  </li>
                ))}
              </ol>
            ) : <p className="text-sm text-ink-3">No single feature dominated the score.</p>}
            <dl className="mt-4 grid grid-cols-2 gap-x-6 gap-y-2 border-t border-line pt-4 sm:grid-cols-4">
              {FEATURE_LABELS.filter(([k]) => t.features[k] != null).map(([k, label, fmt]) => (
                <div key={k}>
                  <dt className="text-[11px] text-ink-3">{label}</dt>
                  <dd className="text-sm font-medium tabular-nums text-ink">{fmt(t.features[k])}</dd>
                </div>
              ))}
            </dl>
          </Card>

          {mineOrManager && !["CONFIRMED_FRAUD", "FALSE_POSITIVE"].includes(c.status) && (
            <Card title="Resolve case">
              <textarea value={note} onChange={(e) => setNote(e.target.value)} rows={2} placeholder="Resolution note (e.g. customer confirmed by phone)"
                className="w-full rounded-lg border border-line bg-bg px-3 py-2 text-sm text-ink outline-none focus:border-accent" />
              <div className="mt-2 flex flex-wrap gap-2">
                <Button variant="danger" onClick={() => resolve("CONFIRMED_FRAUD")} loading={busy === "CONFIRMED_FRAUD"}>Confirm fraud</Button>
                <Button onClick={() => resolve("FALSE_POSITIVE")} loading={busy === "FALSE_POSITIVE"}>Mark false positive</Button>
              </div>
            </Card>
          )}
          {c.resolved_at && (
            <Card title="Resolution">
              <div className="flex items-center gap-2"><StatusBadge status={c.status} /><span className="text-xs text-ink-3">{formatDateTime(c.resolved_at)}</span></div>
              {c.resolution_note && <p className="mt-2 text-sm text-ink-2">{c.resolution_note}</p>}
            </Card>
          )}
        </div>

        <div className="space-y-3">
          <Card title="AI risk analyst" action={c.ai_model && <span className="text-[11px] text-ink-3">{c.ai_model}</span>}>
            {busy === "ai" ? (
              <ul className="space-y-2" aria-live="polite">
                {AGENT_STEPS.map((s, i) => (
                  <li key={s} className={cx("flex items-center gap-2 text-sm", i < step ? "text-ink-2" : i === step ? "text-ink" : "text-ink-3")}>
                    {i < step ? <span aria-hidden className="text-good">✓</span> : i === step ? <Spinner /> : <span aria-hidden>·</span>}
                    {s}
                  </li>
                ))}
              </ul>
            ) : c.ai_recommendation ? (
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <RecommendationBadge rec={c.ai_recommendation} />
                  <span className="text-xs text-ink-3">{c.ai_confidence != null && `${Math.round(c.ai_confidence * 100)}% confident`}</span>
                </div>
                <p className="text-sm leading-relaxed text-ink">{c.ai_summary}</p>
                {c.ai_evidence.length > 0 && (
                  <div>
                    <div className="mb-1 text-xs font-medium text-ink-3">Evidence</div>
                    <ul className="space-y-1 text-sm text-ink-2">{c.ai_evidence.map((e) => <li key={e}>• {e}</li>)}</ul>
                  </div>
                )}
                {c.ai_next_steps.length > 0 && (
                  <div>
                    <div className="mb-1 text-xs font-medium text-ink-3">Suggested next steps</div>
                    <ol className="list-inside list-decimal space-y-1 text-sm text-ink-2">{c.ai_next_steps.map((s) => <li key={s}>{s}</li>)}</ol>
                  </div>
                )}
                {trace && (
                  <div className="flex flex-wrap gap-1.5 border-t border-line pt-3">
                    <span className="text-[11px] text-ink-3">Tools used:</span>
                    {trace.map((tc, i) => <span key={i} className="rounded bg-surface-2 px-1.5 py-0.5 font-mono text-[11px] text-ink-2">{tc.tool}</span>)}
                  </div>
                )}
                <div className="flex items-center justify-between border-t border-line pt-3">
                  <span className="text-[11px] text-ink-3">{formatDateTime(c.ai_generated_at)} · advisory only</span>
                  <Button variant="ghost" onClick={investigate}>Re-run</Button>
                </div>
              </div>
            ) : (
              <div className="space-y-3">
                <p className="text-sm text-ink-2">The agent reviews the customer&apos;s history and past cases, then recommends Block, Verify or Approve with evidence.</p>
                <Button variant="primary" onClick={investigate} className="w-full">Investigate with AI</Button>
              </div>
            )}
          </Card>

          {isManager && (
            <Card title="Audit trail">
              {audit.data?.results.length ? (
                <ol className="space-y-2">
                  {audit.data.results.map((a) => (
                    <li key={a.id} className="text-sm">
                      <span className="font-medium text-ink">{a.action.replace("case.", "").replace("_", " ")}</span>
                      <span className="text-ink-3"> · {a.actor} · {timeAgo(a.created_at)}</span>
                    </li>
                  ))}
                </ol>
              ) : <p className="text-sm text-ink-3">No entries.</p>}
            </Card>
          )}
        </div>
      </div>
    </>
  );
}
