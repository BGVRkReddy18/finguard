"use client";

import Link from "next/link";
import { useState } from "react";

import { Button, Card, Empty, ErrorNote, PageHeader, Spinner } from "@/components/ui";
import { api } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { useSession } from "@/lib/session";
import type { AuditEntry, Paginated } from "@/lib/types";
import { useFetch } from "@/lib/useFetch";

const ACTIONS = ["", "case.opened", "case.assigned", "case.resolved", "case.ai_report"];

export default function AuditPage() {
  const { isManager } = useSession();
  const [action, setAction] = useState("");
  const [page, setPage] = useState(1);
  const query = new URLSearchParams({ page: String(page), ...(action ? { action } : {}) }).toString();
  const log = useFetch(() => (isManager ? api<Paginated<AuditEntry>>("core", `/api/audit-logs/?${query}`) : Promise.resolve(null)), [query, isManager]);

  if (!isManager) return <ErrorNote message="The audit log is available to risk managers and administrators." />;
  const pages = log.data ? Math.max(1, Math.ceil(log.data.count / 25)) : 1;

  return (
    <>
      <PageHeader title="Audit log" subtitle="Append-only record of every case action — human and AI"
        action={
          <select value={action} onChange={(e) => { setAction(e.target.value); setPage(1); }} aria-label="Filter by action"
            className="rounded-lg border border-line bg-surface px-2 py-1.5 text-sm text-ink">
            {ACTIONS.map((a) => <option key={a} value={a}>{a || "All actions"}</option>)}
          </select>
        } />
      {log.error && <ErrorNote message={log.error} />}
      <Card>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[720px] text-sm">
            <thead><tr className="text-left text-xs text-ink-3">{["When", "Actor", "Action", "Case", "Details"].map((h) => <th key={h} className="pb-2 font-medium">{h}</th>)}</tr></thead>
            <tbody>
              {log.data?.results.map((a) => (
                <tr key={a.id} className="border-t border-line align-top">
                  <td className="py-2 whitespace-nowrap text-ink-3">{formatDateTime(a.created_at)}</td>
                  <td className="py-2 text-ink">{a.actor}</td>
                  <td className="py-2 font-mono text-xs text-ink-2">{a.action}</td>
                  <td className="py-2"><Link className="text-ink hover:underline" href={`/cases/${a.entity_id}`}>#{a.entity_id}</Link></td>
                  <td className="max-w-md truncate py-2 font-mono text-[11px] text-ink-3" title={JSON.stringify(a.details)}>{JSON.stringify(a.details)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {log.loading && !log.data && <div className="py-10 text-center text-ink-3"><Spinner /></div>}
          {log.data && !log.data.results.length && <Empty>No entries.</Empty>}
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
