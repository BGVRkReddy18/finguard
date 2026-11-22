"use client";

import Link from "next/link";

import { AreaTimeChart, ColumnChart, RankedBars } from "@/components/charts";
import { Card, ChartCard, Empty, ErrorNote, PageHeader, RiskBadge, ScoreBar, StatTile, cx } from "@/components/ui";
import { api } from "@/lib/api";
import { formatINR, formatINRCompact, formatNumber, formatPct, formatTime } from "@/lib/format";
import { useLive, useLiveRefresh } from "@/lib/session";
import type { RiskLevel, Stats, Timeseries } from "@/lib/types";
import { useFetch } from "@/lib/useFetch";

const hhmm = (iso: string | number) =>
  new Date(iso).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" });

export default function OverviewPage() {
  const stats = useFetch(() => api<Stats>("core", "/api/transactions/stats/?hours=24"), [], 15_000);
  const series = useFetch(() => api<Timeseries>("core", "/api/transactions/timeseries/?hours=6&bucket=10"), [], 30_000);
  const { recent, tps, status } = useLive();
  useLiveRefresh(["case_opened"], stats.reload, 3000);

  const s = stats.data;
  const openCases = (s?.cases_by_status.OPEN ?? 0) + (s?.cases_by_status.INVESTIGATING ?? 0);
  // Drop the current, still-filling bucket — it would falsely show a dip at the end of every chart
  const points = (series.data?.points ?? []).slice(0, -1);
  const riskTotal = Object.values(s?.by_risk_level ?? {}).reduce((a, b) => a + (b ?? 0), 0);
  const riskRows = (["HIGH", "MEDIUM", "LOW"] as RiskLevel[]).map((r) => ({ level: r, n: s?.by_risk_level[r] ?? 0 }));

  return (
    <>
      <PageHeader title="Overview" subtitle={s?.background_traffic
        ? "Last 24 hours · simulated payments, scored around the clock · cases are created while the demo is open"
        : "Last 24 hours · card transactions scored in real time"} />
      {stats.error && <div className="mb-4"><ErrorNote message={stats.error} /></div>}

      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        <StatTile label="Transactions" value={formatNumber(s?.total)} hint={`${formatINRCompact(s?.volume)} volume`} />
        <StatTile label="Alert rate" value={formatPct(s?.flag_rate, 2)} hint={`${formatNumber(s?.flagged)} flagged`} />
        <StatTile label="Cases needing action" value={formatNumber(openCases)}
          hint={<Link href="/cases" className="hover:text-ink">Open queue →</Link>} />
        <StatTile label="Value at risk flagged" value={formatINRCompact(s?.flagged_volume)} hint="sum of alerted amounts" />
        <StatTile label="Scoring latency" value={s?.avg_latency_ms != null ? `${s.avg_latency_ms.toFixed(1)} ms` : "—"} hint="avg, feature store + model" />
        <StatTile label="Live throughput" value={status === "live" ? `${tps.toFixed(1)}/s` : "—"} hint={s?.model_version ?? ""} />
      </div>

      <div className="mt-3 grid gap-3 lg:grid-cols-3">
        <ChartCard className="lg:col-span-2" title="Transactions" subtitle="per 10 min · last 6 h"
          table={{ columns: ["Time", "Transactions"], rows: points.map((p) => [hhmm(p.t), p.total]) }}>
          {points.length ? <AreaTimeChart data={points} x="t" y="total" name="Transactions" xFormat={hhmm} yFormat={(v) => formatNumber(v)} />
            : <Empty>No data yet</Empty>}
        </ChartCard>
        {/* ~98% of traffic is low risk, so bars would hide High/Medium entirely — numbers read better */}
        <Card title="Risk mix" action={<span className="text-xs text-ink-3">last 24 h</span>}>
          <dl className="divide-y divide-line">
            {riskRows.map((r) => (
              <div key={r.level} className="flex items-center justify-between py-3">
                <dt><RiskBadge level={r.level} /></dt>
                <dd className="text-right">
                  <span className="text-lg font-semibold tabular-nums text-ink">{formatNumber(r.n)}</span>
                  <span className="ml-2 text-xs tabular-nums text-ink-3">{riskTotal ? formatPct(r.n / riskTotal, 2) : "—"}</span>
                </dd>
              </div>
            ))}
          </dl>
          <p className="mt-2 text-xs text-ink-3">Medium and High risk open cases for analysts.</p>
        </Card>
      </div>

      <div className="mt-3 grid gap-3 lg:grid-cols-2">
        <ChartCard title="Alerts" subtitle="flagged per 10 min"
          table={{ columns: ["Time", "Alerts"], rows: points.map((p) => [hhmm(p.t), p.flagged]) }}>
          {points.length ? <ColumnChart data={points} x="t" y="flagged" name="Alerts" xFormat={hhmm} /> : <Empty>No data yet</Empty>}
        </ChartCard>
        <ChartCard title="Top cities by alerts" subtitle="last 24 h"
          table={{ columns: ["City", "Alerts"], rows: (s?.top_flagged_cities ?? []).map((c) => [c.city, c.n]) }}>
          {s?.top_flagged_cities.length ? <RankedBars data={s.top_flagged_cities} label="city" value="n" name="Alerts" />
            : <Empty>No alerts yet</Empty>}
        </ChartCard>
      </div>

      <Card className="mt-3" title="Live transactions"
        action={<span className="text-xs text-ink-3">{recent.length ? `latest ${recent.length}` : "waiting for events…"}</span>}>
        <div className="max-h-[440px] overflow-auto">
          <table className="w-full min-w-[720px] text-sm">
            <thead className="sticky top-0 bg-surface">
              <tr className="text-left text-xs text-ink-3">
                <th className="pb-2 font-medium">Time</th><th className="pb-2 font-medium">Customer</th>
                <th className="pb-2 font-medium">Merchant</th><th className="pb-2 font-medium">City</th>
                <th className="pb-2 font-medium">Channel</th><th className="pb-2 text-right font-medium">Amount</th>
                <th className="pb-2 pl-4 font-medium">Score</th><th className="pb-2 font-medium">Risk</th>
              </tr>
            </thead>
            <tbody>
              {recent.map((t) => (
                <tr key={t.txn_id} className={cx("row-in border-t border-line", t.is_flagged && "bg-surface-2")}>
                  <td className="py-1.5 tabular-nums text-ink-3">{formatTime(t.timestamp)}</td>
                  <td className="py-1.5 font-mono text-xs text-ink-2">{t.customer_id}</td>
                  <td className="py-1.5 text-ink">{t.merchant}<span className="ml-1.5 text-xs text-ink-3">{t.merchant_category.replace("_", " ")}</span></td>
                  <td className="py-1.5 text-ink-2">{t.city}</td>
                  <td className="py-1.5 text-ink-2">{t.channel}</td>
                  <td className="py-1.5 text-right tabular-nums text-ink">{formatINR(t.amount)}</td>
                  <td className="py-1.5 pl-4"><ScoreBar score={t.fraud_score} /></td>
                  <td className="py-1.5" title={t.reasons.join(" · ")}><RiskBadge level={t.risk_level} /></td>
                </tr>
              ))}
            </tbody>
          </table>
          {!recent.length && <Empty>Connecting to the live stream…</Empty>}
        </div>
      </Card>
    </>
  );
}
