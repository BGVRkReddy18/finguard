"use client";

import { useState } from "react";

import { RankedBars, SimpleLine } from "@/components/charts";
import { Button, Card, ErrorNote, PageHeader } from "@/components/ui";
import { api } from "@/lib/api";
import type { AskResponse } from "@/lib/types";

const EXAMPLES = [
  "Which 5 cities had the most flagged transactions today?",
  "What is the average fraud score by channel?",
  "How many cases are open per priority?",
  "Flagged transactions per hour over the last 6 hours",
  "Which merchant categories have the highest alert rate?",
];

type Entry = { id: number; question: string; result?: AskResponse; error?: string };

function isNumeric(v: unknown) {
  return typeof v === "number" || (typeof v === "string" && v.trim() !== "" && !Number.isNaN(Number(v)));
}

function ResultView({ r }: { r: AskResponse }) {
  const [showSql, setShowSql] = useState(false);
  const [asTable, setAsTable] = useState(r.chart === "table");
  const labelCol = r.columns.find((c) => r.rows.some((row) => !isNumeric(row[c])));
  const valueCol = r.columns.find((c) => c !== labelCol && r.rows.every((row) => row[c] == null || isNumeric(row[c])));
  const chartRows = labelCol && valueCol
    ? r.rows.map((row) => ({ label: String(row[labelCol]), score: Number(row[valueCol]) }))
    : [];
  const canChart = chartRows.length > 0 && r.chart !== "table" && r.chart !== "number";
  const single = r.rows.length === 1 && r.columns.length === 1 ? r.rows[0][r.columns[0]] : null;

  return (
    <div className="space-y-3">
      <p className="text-sm leading-relaxed text-ink">{r.answer}</p>

      {single != null ? (
        <div className="text-4xl font-semibold tracking-tight text-ink">
          {isNumeric(single) ? Number(single).toLocaleString("en-IN", { maximumFractionDigits: 3 }) : String(single)}
          <div className="mt-1 text-xs font-normal text-ink-3">{r.title || r.columns[0]}</div>
        </div>
      ) : canChart && !asTable ? (
        <div>
          <div className="mb-1 text-xs font-medium text-ink-2">{r.title}</div>
          {r.chart === "line"
            ? <SimpleLine data={chartRows} x="label" y="score" name={valueCol!} />
            : <RankedBars data={chartRows.slice(0, 15)} label="label" value="score" name={valueCol!}
                valueFormat={(v) => v.toLocaleString("en-IN", { maximumFractionDigits: 3 })} />}
        </div>
      ) : (
        <div className="max-h-80 overflow-auto rounded-lg border border-line">
          <table className="w-full text-sm">
            <thead className="sticky top-0 bg-surface-2"><tr>{r.columns.map((c) => <th key={c} className="px-3 py-1.5 text-left text-xs font-medium text-ink-2">{c}</th>)}</tr></thead>
            <tbody>
              {r.rows.map((row, i) => (
                <tr key={i} className="border-t border-line">
                  {r.columns.map((c) => <td key={c} className="px-3 py-1.5 tabular-nums text-ink-2">{row[c] == null ? "—" : isNumeric(row[c]) ? Number(row[c]).toLocaleString("en-IN", { maximumFractionDigits: 3 }) : String(row[c])}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
          {!r.rows.length && <p className="p-3 text-sm text-ink-3">The query returned no rows.</p>}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-3 text-xs text-ink-3">
        {canChart && <button onClick={() => setAsTable((v) => !v)} className="hover:text-ink">{asTable ? "Show chart" : "Show table"}</button>}
        <button onClick={() => setShowSql((v) => !v)} className="hover:text-ink">{showSql ? "Hide SQL" : "Show SQL"}</button>
        <span>{r.rows.length} rows · {r.model} · read-only, validated query</span>
      </div>
      {showSql && <pre className="overflow-x-auto rounded-lg bg-surface-2 p-3 font-mono text-xs text-ink-2">{r.sql}</pre>}
    </div>
  );
}

export default function AskPage() {
  const [question, setQuestion] = useState("");
  const [entries, setEntries] = useState<Entry[]>([]);
  const [busy, setBusy] = useState(false);

  const ask = async (q: string) => {
    const text = q.trim();
    if (!text || busy) return;
    const id = Date.now();
    setEntries((prev) => [{ id, question: text }, ...prev]);
    setQuestion("");
    setBusy(true);
    try {
      const result = await api<AskResponse>("ai", "/ask", { method: "POST", json: { question: text } });
      setEntries((prev) => prev.map((e) => (e.id === id ? { ...e, result } : e)));
    } catch (err) {
      setEntries((prev) => prev.map((e) => (e.id === id ? { ...e, error: err instanceof Error ? err.message : "Failed" } : e)));
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <PageHeader title="Ask AI" subtitle="Questions about fraud data in plain English — answered with a validated, read-only SQL query" />
      <form onSubmit={(e) => { e.preventDefault(); ask(question); }} className="flex gap-2">
        <input value={question} onChange={(e) => setQuestion(e.target.value)} maxLength={500}
          placeholder="e.g. Which cities had the most alerts in the last hour?"
          className="flex-1 rounded-lg border border-line bg-surface px-3 py-2 text-sm text-ink outline-none focus:border-accent" />
        <Button type="submit" variant="primary" loading={busy} disabled={!question.trim()}>Ask</Button>
      </form>
      <div className="mt-3 flex flex-wrap gap-2">
        {EXAMPLES.map((q) => (
          <button key={q} onClick={() => ask(q)} disabled={busy}
            className="rounded-full border border-line bg-surface px-3 py-1 text-xs text-ink-2 hover:bg-surface-2 disabled:opacity-50">{q}</button>
        ))}
      </div>

      <div className="mt-5 space-y-3">
        {entries.map((e) => (
          <Card key={e.id} title={e.question}>
            {e.result ? <ResultView r={e.result} /> : e.error ? <ErrorNote message={e.error} /> : <p className="text-sm text-ink-3">Writing and running a query…</p>}
          </Card>
        ))}
      </div>
    </>
  );
}
