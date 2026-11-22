export type Role = "ANALYST" | "MANAGER" | "ADMIN";
export type RiskLevel = "LOW" | "MEDIUM" | "HIGH";
export type CaseStatus = "OPEN" | "INVESTIGATING" | "CONFIRMED_FRAUD" | "FALSE_POSITIVE";
export type Recommendation = "BLOCK" | "VERIFY" | "APPROVE";

export interface User {
  id: number;
  username: string;
  first_name: string;
  last_name: string;
  email: string;
  role: Role;
}

export interface Paginated<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}

export interface Transaction {
  id: number;
  txn_id: string;
  customer_id: string;
  amount: string;
  currency: string;
  merchant: string;
  merchant_category: string;
  city: string;
  lat: number;
  lon: number;
  channel: "POS" | "ONLINE" | "ATM";
  timestamp: string;
  fraud_score: number;
  risk_level: RiskLevel;
  is_flagged: boolean;
  reasons: string[];
  features: Record<string, number>;
  model_version: string;
  scoring_latency_ms: number | null;
  case_id: number | null;
}

export interface FraudCase {
  id: number;
  transaction: Transaction;
  assigned_to: User | null;
  status: CaseStatus;
  priority: "MEDIUM" | "HIGH";
  resolution_note: string;
  ai_summary: string;
  ai_recommendation: Recommendation | "";
  ai_confidence: number | null;
  ai_evidence: string[];
  ai_next_steps: string[];
  ai_model: string;
  ai_generated_at: string | null;
  created_at: string;
  updated_at: string;
  resolved_at: string | null;
}

export interface Stats {
  window_hours: number;
  total: number;
  flagged: number;
  volume: number | null;
  flagged_volume: number | null;
  avg_score: number | null;
  avg_latency_ms: number | null;
  flag_rate: number;
  by_risk_level: Partial<Record<RiskLevel, number>>;
  top_flagged_cities: { city: string; n: number }[];
  cases_by_status: Partial<Record<CaseStatus, number>>;
  model_version: string | null;
  background_traffic?: boolean; // Cloud Lite: totals include traffic that was not saved
}

export interface Timeseries {
  bucket_minutes: number;
  points: { t: string; total: number; flagged: number }[];
}

export interface AuditEntry {
  id: number;
  actor: string;
  action: string;
  entity_type: string;
  entity_id: string;
  details: Record<string, unknown>;
  created_at: string;
}

export interface EvalResult {
  name: string;
  threshold: number;
  roc_auc: number;
  pr_auc: number;
  precision: number;
  recall: number;
  f1: number;
  fraud_amount_caught: number;
  false_alerts_per_1k: number;
  recall_by_pattern: Record<string, number>;
}

export interface ModelInfo {
  version: string;
  flag_threshold: number;
  trained_at: string | null;
  rows: Record<string, number> | null;
  test_metrics: { xgboost: EvalResult; "rules-v1": EvalResult } | null;
  shap_importance: Record<string, number> | null;
}

export interface InvestigationReport {
  recommendation: Recommendation;
  confidence: number;
  summary: string;
  key_evidence: string[];
  next_steps: string[];
  model: string;
}

export interface InvestigationResponse {
  case_id: number;
  report: InvestigationReport;
  tool_calls: { tool: string; arguments: string }[];
}

export interface AskResponse {
  question: string;
  sql: string;
  chart: "bar" | "line" | "table" | "number";
  title: string;
  columns: string[];
  rows: Record<string, string | number | boolean | null>[];
  answer: string;
  model: string;
}

/** Events pushed over the WebSocket. */
export type LiveEvent =
  | {
      type: "txn";
      txn_id: string;
      customer_id: string;
      amount: number;
      merchant: string;
      merchant_category: string;
      city: string;
      channel: string;
      timestamp: string;
      fraud_score: number;
      risk_level: RiskLevel;
      is_flagged: boolean;
      reasons: string[];
    }
  | { type: "case_opened"; case_id: number; priority: string; fraud_score: number; customer_id: string }
  | { type: "ai_report"; case_id: number; recommendation: Recommendation; confidence: number; model: string };
