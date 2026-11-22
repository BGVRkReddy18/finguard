"use client";

import { useState } from "react";

import type { CaseStatus, Recommendation, RiskLevel } from "@/lib/types";

export function cx(...classes: (string | false | null | undefined)[]) {
  return classes.filter(Boolean).join(" ");
}

export function Card({ title, action, children, className }: {
  title?: React.ReactNode; action?: React.ReactNode; children: React.ReactNode; className?: string;
}) {
  return (
    <section className={cx("rounded-xl border border-line bg-surface", className)}>
      {(title || action) && (
        <header className="flex items-center justify-between gap-3 px-4 pt-4">
          {title && <h2 className="text-sm font-semibold text-ink">{title}</h2>}
          {action}
        </header>
      )}
      <div className="p-4">{children}</div>
    </section>
  );
}

export function StatTile({ label, value, hint }: { label: string; value: React.ReactNode; hint?: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-line bg-surface px-4 py-3">
      <div className="text-xs font-medium text-ink-3">{label}</div>
      <div className="mt-1 text-2xl font-semibold tracking-tight text-ink">{value}</div>
      {hint && <div className="mt-0.5 text-xs text-ink-3">{hint}</div>}
    </div>
  );
}

type Tone = "good" | "warning" | "serious" | "critical" | "neutral" | "accent";
const DOT: Record<Tone, string> = {
  good: "bg-good", warning: "bg-warning", serious: "bg-serious", critical: "bg-critical",
  neutral: "bg-ink-3", accent: "bg-accent",
};

/** Status chip: a coloured dot + a text label (state is never conveyed by colour alone). */
export function Badge({ tone, children, title }: { tone: Tone; children: React.ReactNode; title?: string }) {
  return (
    <span title={title}
      className="inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border border-line bg-surface-2 px-2 py-0.5 text-xs font-medium text-ink">
      <span aria-hidden className={cx("h-1.5 w-1.5 rounded-full", DOT[tone])} />
      {children}
    </span>
  );
}

const RISK_TONE: Record<RiskLevel, Tone> = { LOW: "good", MEDIUM: "warning", HIGH: "critical" };
export const RiskBadge = ({ level }: { level: RiskLevel }) => <Badge tone={RISK_TONE[level]}>{level[0] + level.slice(1).toLowerCase()} risk</Badge>;

const STATUS: Record<CaseStatus, [Tone, string]> = {
  OPEN: ["accent", "Open"],
  INVESTIGATING: ["warning", "Investigating"],
  CONFIRMED_FRAUD: ["critical", "Confirmed fraud"],
  FALSE_POSITIVE: ["good", "False positive"],
};
export const StatusBadge = ({ status }: { status: CaseStatus }) => <Badge tone={STATUS[status][0]}>{STATUS[status][1]}</Badge>;

const REC: Record<Recommendation, [Tone, string]> = {
  BLOCK: ["critical", "AI: Block"], VERIFY: ["warning", "AI: Verify"], APPROVE: ["good", "AI: Approve"],
};
export function RecommendationBadge({ rec, confidence }: { rec: Recommendation | ""; confidence?: number | null }) {
  if (!rec) return <span className="text-xs text-ink-3">—</span>;
  return (
    <Badge tone={REC[rec][0]}>
      {REC[rec][1]}
      {confidence != null && <span className="text-ink-3">{Math.round(confidence * 100)}%</span>}
    </Badge>
  );
}

export function Button({ variant = "secondary", loading, className, children, ...props }:
  React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" | "danger" | "ghost"; loading?: boolean }) {
  const styles = {
    primary: "bg-accent text-accent-ink hover:opacity-90 border-transparent",
    secondary: "bg-surface text-ink border-line hover:bg-surface-2",
    danger: "bg-critical text-white border-transparent hover:opacity-90",
    ghost: "bg-transparent text-ink-2 border-transparent hover:bg-surface-2",
  }[variant];
  return (
    <button {...props} disabled={props.disabled || loading}
      className={cx("inline-flex items-center justify-center gap-2 rounded-lg border px-3 py-1.5 text-sm font-medium transition disabled:cursor-not-allowed disabled:opacity-50", styles, className)}>
      {loading && <Spinner />}
      {children}
    </button>
  );
}

export function Spinner({ className }: { className?: string }) {
  return <span aria-hidden className={cx("inline-block h-3.5 w-3.5 animate-spin rounded-full border-2 border-current border-t-transparent", className)} />;
}

export function ErrorNote({ message }: { message: string }) {
  return <div role="alert" className="rounded-lg border border-line bg-surface-2 px-3 py-2 text-sm text-ink"><span className="mr-1.5 text-critical">●</span>{message}</div>;
}

export function Empty({ children }: { children: React.ReactNode }) {
  return <div className="py-10 text-center text-sm text-ink-3">{children}</div>;
}

export function PageHeader({ title, subtitle, action }: { title: string; subtitle?: string; action?: React.ReactNode }) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-xl font-semibold tracking-tight text-ink">{title}</h1>
        {subtitle && <p className="mt-0.5 text-sm text-ink-3">{subtitle}</p>}
      </div>
      {action}
    </div>
  );
}

/** Score as a thin meter + number. */
export function ScoreBar({ score, level }: { score: number; level: RiskLevel }) {
  const tone = level === "HIGH" ? "bg-critical" : level === "MEDIUM" ? "bg-warning" : "bg-ink-3";
  return (
    <div className="flex items-center gap-2">
      <div className="relative h-1.5 w-16 overflow-hidden rounded-full bg-surface-2" aria-hidden>
        <div className={cx("h-full rounded-full", tone)} style={{ width: `${Math.max(3, score * 100)}%` }} />
      </div>
      <span className="text-xs tabular-nums text-ink-2">{score.toFixed(3)}</span>
    </div>
  );
}

/** Wraps a chart with a chart/table toggle, so every chart has an accessible table view. */
export function ChartCard({ title, subtitle, table, children, className }: {
  title: string; subtitle?: string; className?: string;
  table: { columns: string[]; rows: (string | number)[][] };
  children: React.ReactNode;
}) {
  const [asTable, setAsTable] = useState(false);
  return (
    <Card className={className} title={<span>{title}{subtitle && <span className="ml-2 font-normal text-ink-3">{subtitle}</span>}</span>}
      action={<button onClick={() => setAsTable((v) => !v)} className="text-xs text-ink-3 hover:text-ink">{asTable ? "Chart" : "Table"}</button>}>
      {asTable ? (
        <div className="max-h-72 overflow-auto">
          <table className="w-full text-sm">
            <thead><tr>{table.columns.map((c) => <th key={c} className="py-1 text-left text-xs font-medium text-ink-3">{c}</th>)}</tr></thead>
            <tbody>{table.rows.map((r, i) => <tr key={i} className="border-t border-line">{r.map((v, j) => <td key={j} className="py-1 tabular-nums text-ink-2">{v}</td>)}</tr>)}</tbody>
          </table>
        </div>
      ) : children}
    </Card>
  );
}
