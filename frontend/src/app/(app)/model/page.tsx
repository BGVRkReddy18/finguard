"use client";

import { CompareBars, RankedBars } from "@/components/charts";
import { Card, ChartCard, ErrorNote, PageHeader, Spinner, StatTile } from "@/components/ui";
import { api } from "@/lib/api";
import { formatDateTime, formatNumber, titleCase } from "@/lib/format";
import type { ModelInfo } from "@/lib/types";
import { useFetch } from "@/lib/useFetch";

const FEATURE_NAMES: Record<string, string> = {
  channel_online: "Online channel", amount_log: "Amount", km_from_home: "Distance from home",
  amount_ratio: "Amount vs. average", km_from_last: "Distance from last txn", hour: "Hour of day",
  minutes_since_last: "Time since last txn", history_count: "Customer history", gift_card: "Gift card",
  amount_zscore: "Amount z-score", speed_kmh_log: "Travel speed", txn_count_10m: "Velocity (10 min)",
  high_risk_category: "High-risk category", is_night: "Night time", channel_atm: "ATM",
};
const pct = (v: number) => `${Math.round(v * 100)}%`;

export default function ModelPage() {
  const info = useFetch(() => api<ModelInfo>("ml", "/model/info"), []);
  if (info.error) return <ErrorNote message={info.error} />;
  const m = info.data;
  if (!m) return <div className="py-20 text-center text-ink-3"><Spinner /></div>;
  const xgb = m.test_metrics?.xgboost;
  const rules = m.test_metrics?.["rules-v1"];

  const metrics = xgb && rules ? ([
    ["Precision", "precision"], ["Recall", "recall"], ["F1", "f1"], ["PR-AUC", "pr_auc"], ["Fraud ₹ caught", "fraud_amount_caught"],
  ] as const).map(([label, key]) => ({ label, rules: rules[key], model: xgb[key] })) : [];
  const patterns = xgb && rules ? Object.keys(xgb.recall_by_pattern).map((p) => ({
    label: titleCase(p), rules: rules.recall_by_pattern[p] ?? 0, model: xgb.recall_by_pattern[p],
  })) : [];
  const shap = Object.entries(m.shap_importance ?? {}).slice(0, 10).map(([k, v]) => ({ feature: FEATURE_NAMES[k] ?? k, score: v }));
  const testRows = m.rows?.test;

  return (
    <>
      <PageHeader title="Model performance" subtitle={`Serving ${m.version}${m.trained_at ? ` · trained ${formatDateTime(m.trained_at)}` : ""}`} />
      {!xgb || !rules ? (
        <Card><p className="text-sm text-ink-2">The rule-based scorer is serving. Train the model with <code className="rounded bg-surface-2 px-1">make ml-bootstrap</code> to see a model card.</p></Card>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <StatTile label="PR-AUC" value={xgb.pr_auc.toFixed(3)} hint={`rules: ${rules.pr_auc.toFixed(3)} (${(xgb.pr_auc / rules.pr_auc).toFixed(1)}×)`} />
            <StatTile label="Recall" value={pct(xgb.recall)} hint={`rules: ${pct(rules.recall)}`} />
            <StatTile label="False alerts / 1,000 genuine" value={xgb.false_alerts_per_1k.toFixed(1)} hint={`rules: ${rules.false_alerts_per_1k.toFixed(1)} — analyst workload`} />
            <StatTile label="Decision threshold" value={m.flag_threshold.toFixed(3)} hint="tuned for max F1 on validation" />
          </div>

          <div className="mt-3 grid gap-3 lg:grid-cols-2">
            <ChartCard title="Rules vs. XGBoost" subtitle={`held-out test set${testRows ? ` · ${formatNumber(testRows)} txns` : ""}`}
              table={{ columns: ["Metric", "Rules", "XGBoost"], rows: metrics.map((r) => [r.label, r.rules.toFixed(3), r.model.toFixed(3)]) }}>
              <CompareBars data={metrics} label="label" a={{ key: "rules", name: "Rules (rules-v1)" }} b={{ key: "model", name: "XGBoost" }} valueFormat={pct} />
            </ChartCard>
            <ChartCard title="Recall by fraud pattern" subtitle="share of each attack type caught"
              table={{ columns: ["Pattern", "Rules", "XGBoost"], rows: patterns.map((r) => [r.label, pct(r.rules), pct(r.model)]) }}>
              <CompareBars data={patterns} label="label" a={{ key: "rules", name: "Rules (rules-v1)" }} b={{ key: "model", name: "XGBoost" }} valueFormat={pct} />
            </ChartCard>
          </div>

          <div className="mt-3 grid gap-3 lg:grid-cols-3">
            <ChartCard className="lg:col-span-2" title="What drives the model" subtitle="mean |SHAP| on the test set"
              table={{ columns: ["Feature", "Mean |SHAP|"], rows: shap.map((s) => [s.feature, s.score.toFixed(3)]) }}>
              <RankedBars data={shap} label="feature" value="score" name="Mean |SHAP|" valueFormat={(v) => v.toFixed(2)} />
            </ChartCard>
            <Card title="How to read this">
              <ul className="space-y-2 text-sm text-ink-2">
                <li><b className="text-ink">Time-based split.</b> Trained on the first 70% of the timeline, tested on the last 15% — no peeking at the future.</li>
                <li><b className="text-ink">PR-AUC</b> is the headline metric: with ~2% fraud, accuracy and ROC-AUC look good even for weak models.</li>
                <li><b className="text-ink">Known gap:</b> card-not-present fraud mimics normal spend; catching it needs device and IP signals this data doesn&apos;t have.</li>
              </ul>
            </Card>
          </div>
        </>
      )}
    </>
  );
}
