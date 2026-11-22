"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Badge, Button, Card, Empty, ErrorNote, PageHeader, RecommendationBadge, ScoreBar, Spinner, StatusBadge, cx } from "@/components/ui";
import { api } from "@/lib/api";
import { formatINR, timeAgo } from "@/lib/format";
import { useLiveRefresh, useSession } from "@/lib/session";
import type { CaseStatus, FraudCase, Paginated } from "@/lib/types";
import { useFetch } from "@/lib/useFetch";

const TABS: { label: string; status: CaseStatus | "" }[] = [
  { label: "Open", status: "OPEN" },
  { label: "Investigating", status: "INVESTIGATING" },
  { label: "Confirmed fraud", status: "CONFIRMED_FRAUD" },
  { label: "False positive", status: "FALSE_POSITIVE" },
  { label: "All", status: "" },
];

export default function CasesPage() {
  const { user } = useSession();
  const router = useRouter();
  const [status, setStatus] = useState<CaseStatus | "">("OPEN");
  const [priority, setPriority] = useState("");
  const [mine, setMine] = useState(false);
  const [page, setPage] = useState(1);

  const params = new URLSearchParams({ ordering: "-created_at", page: String(page) });
  if (status) params.set("status", status);
  if (priority) params.set("priority", priority);
  if (mine && user) params.set("assigned_to", String(user.id));
  const query = params.toString();

  const cases = useFetch(() => api<Paginated<FraudCase>>("core", `/api/cases/?${query}`), [query]);
  useLiveRefresh(["case_opened", "ai_report"], () => page === 1 && cases.reload(), 2000);

  const pages = cases.data ? Math.max(1, Math.ceil(cases.data.count / 25)) : 1;
  const select = (fn: () => void) => { fn(); setPage(1); };

  return (
    <>
      <PageHeader title="Case queue" subtitle="Transactions the model flagged for human review" />

      <div className="mb-3 flex flex-wrap items-center gap-2">
        <div className="flex flex-wrap gap-1 rounded-lg border border-line bg-surface p-1" role="tablist">
          {TABS.map((t) => (
            <button key={t.label} role="tab" aria-selected={status === t.status} onClick={() => select(() => setStatus(t.status))}
              className={cx("rounded-md px-3 py-1 text-sm", status === t.status ? "bg-surface-2 font-medium text-ink" : "text-ink-2 hover:text-ink")}>
              {t.label}
            </button>
          ))}
        </div>
        <select value={priority} onChange={(e) => select(() => setPriority(e.target.value))} aria-label="Priority"
          className="rounded-lg border border-line bg-surface px-2 py-1.5 text-sm text-ink">
          <option value="">Any priority</option>
          <option value="HIGH">High priority</option>
          <option value="MEDIUM">Medium priority</option>
        </select>
        <label className="flex items-center gap-2 text-sm text-ink-2">
          <input type="checkbox" checked={mine} onChange={(e) => select(() => setMine(e.target.checked))} />
          Assigned to me
        </label>
        <span className="ml-auto text-xs text-ink-3">{cases.data ? `${cases.data.count.toLocaleString("en-IN")} cases` : ""}</span>
      </div>

      {cases.error && <ErrorNote message={cases.error} />}
      <Card>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[900px] text-sm">
            <thead>
              <tr className="text-left text-xs text-ink-3">
                {["Case", "Opened", "Customer", "Transaction", "Amount", "Score", "Priority", "Status", "AI analyst", "Assignee"].map((h) => (
                  <th key={h} className={cx("pb-2 font-medium", h === "Amount" && "text-right")}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {cases.data?.results.map((c) => (
                <tr key={c.id} onClick={() => router.push(`/cases/${c.id}`)} className="cursor-pointer border-t border-line hover:bg-surface-2">
                  <td className="py-2"><Link href={`/cases/${c.id}`} className="font-medium text-ink hover:underline">#{c.id}</Link></td>
                  <td className="py-2 text-ink-3" title={c.created_at}>{timeAgo(c.created_at)}</td>
                  <td className="py-2 font-mono text-xs text-ink-2">{c.transaction.customer_id}</td>
                  <td className="py-2 text-ink">{c.transaction.merchant}<div className="text-xs text-ink-3">{c.transaction.city} · {c.transaction.channel}</div></td>
                  <td className="py-2 text-right tabular-nums text-ink">{formatINR(c.transaction.amount)}</td>
                  <td className="py-2"><ScoreBar score={c.transaction.fraud_score} level={c.transaction.risk_level} /></td>
                  <td className="py-2"><Badge tone={c.priority === "HIGH" ? "critical" : "warning"}>{c.priority === "HIGH" ? "High" : "Medium"}</Badge></td>
                  <td className="py-2"><StatusBadge status={c.status} /></td>
                  <td className="py-2"><RecommendationBadge rec={c.ai_recommendation} confidence={c.ai_confidence} /></td>
                  <td className="py-2 text-ink-2">{c.assigned_to?.username ?? <span className="text-ink-3">Unassigned</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {cases.loading && !cases.data && <div className="py-10 text-center text-ink-3"><Spinner /></div>}
          {cases.data && !cases.data.results.length && <Empty>No cases here. Nice.</Empty>}
        </div>
        {pages > 1 && (
          <div className="mt-3 flex items-center justify-end gap-2 text-sm text-ink-2">
            <Button variant="ghost" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>← Prev</Button>
            <span>Page {page} of {pages}</span>
            <Button variant="ghost" disabled={page >= pages} onClick={() => setPage((p) => p + 1)}>Next →</Button>
          </div>
        )}
      </Card>
    </>
  );
}
