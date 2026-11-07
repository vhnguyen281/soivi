// Shapes returned by the Soivi API (api/schemas.py). Money is integer VND; rates
// are decimal strings ("5.900"); times are ISO 8601 UTC.

export type Provenance = {
  source_url: string | null;
  checked_at: string | null;
  effective_from: string | null;
  approved_at?: string | null;
  extraction_method?: string | null;
  snapshot_sha256?: string | null;
  methodology_version: string;
  evidence?: Record<string, Evidence> | null;
};

export type Evidence = {
  page: number;
  quote: string;
  value: string;
  ocr?: boolean;
  also?: { page: number; quote: string; value: string }[];
};

export type InstitutionRef = { short_name: string; legal_name_vi: string };

export type Institution = {
  id: number;
  short_name: string;
  legal_name_vi: string;
  type: string;
  website: string | null;
  deposit_insurance: boolean;
  verification: "verified" | "unverified" | "no_sources";
  unverified: boolean;
  provenance: Provenance;
};

export type SavingsRate = {
  id: number;
  institution: InstitutionRef;
  product_name: string;
  channel: "counter" | "online" | "app";
  region: string;
  term_months: number;
  term_days: number;
  min_amount_vnd: number;
  interest_payment: "end" | "monthly" | "quarterly" | "upfront";
  rate_pct: string;
  conditions_text: string | null;
  is_cd: boolean;
  unverified: boolean;
  provenance: Provenance;
};

export type SavingsRankItem = {
  rank: number;
  rate: SavingsRate;
  equivalent_interest_vnd: number;
  cash_interest_vnd: number;
  equivalent_rate_pct: string;
  maturity_value_vnd: number;
  flags: Record<string, boolean | null>;
};

export type SavingsRank = {
  methodology_version: string;
  query: { amount_vnd: number; term_months: number; channel: string; region: string | null };
  results: SavingsRankItem[];
  excluded_min_amount: number;
};

export type HistoryPoint = {
  version_id: number;
  rate_pct: string;
  valid_from: string | null;
  valid_to: string | null;
  provenance: Provenance;
};

export type HistorySeries = {
  product_name: string;
  channel: string;
  region: string;
  term_months: number;
  term_days: number;
  min_amount_vnd: number;
  interest_payment: string;
  points: HistoryPoint[];
};

export type History = { institution: InstitutionRef; series: HistorySeries[] };

export type Valued = {
  version_id: number;
  values: Record<string, string | number | boolean | null>;
  provenance: Provenance;
};

export type CardSummary = {
  id: number;
  institution: InstitutionRef;
  name: string;
  network: string;
  card_type: string;
  tier: string | null;
  unverified: boolean;
  terms: Valued | null;
  rewards_count: number;
};

export type CardDetail = CardSummary & {
  rewards: Valued[];
  perks: Valued | null;
  interest?: Valued | null;
};

export type CardRankItem = {
  rank: number;
  card: CardSummary;
  annual_value_vnd: number;
  breakdown: {
    rewards_vnd: number;
    perks_vnd: number;
    annual_fee_vnd: number;
    fee_waived: boolean;
    fx_cost_vnd: number;
    interest_cost_vnd: number;
  };
  flags: Record<string, boolean>;
  provenance: Provenance[];
};

export type CardRank = {
  methodology_version: string;
  persona: string | null;
  profile: Record<string, unknown>;
  results: CardRankItem[];
  not_ranked: { card: CardSummary; reasons: string[] }[];
};

export type Persona = {
  key: string;
  name_vi: string;
  name_en: string;
  profile: {
    monthly_spend_vnd: Record<string, number>;
    foreign_monthly_vnd: number;
    revolving_balance_vnd: number;
    lounge_visits_wanted: number;
    lounge_visit_value_vnd: number;
    travel_insurance_value_vnd: number;
    monthly_income_vnd: number | null;
  };
};

export type Change = {
  table: "savings_rate" | "card_terms" | "card_reward" | "card_perk" | "card_interest";
  version_id: number;
  kind: "new" | "changed";
  institution: InstitutionRef;
  label: string;
  approved_at: string;
  changes: { field: string; old: unknown; new: unknown }[];
  provenance: Provenance;
};

// VNCMA (GET /vncma/latest): rates are decimal strings, percent per year.
export type VncmaClass = {
  id: string;
  name: string;
  expected_return: string;
  model_return: string;
  adjustment_pp: string;
  adjustment_reason: string | null;
  arithmetic_return: string | null;
  volatility: string | null;
  band_80: [string, string] | null;
  range: [string, string] | null;
  scenarios: { adverse: string; base: string; favourable: string };
  grade: "A" | "B" | "C";
  optimizer_default: boolean;
  formula: string;
};

export type Vncma = {
  version: string;
  status: string;
  methodology_version: string;
  as_of: string;
  horizon_years: number;
  approved_by: string | null;
  approved_at: string | null;
  classes: VncmaClass[];
  correlation: { classes: string[]; matrix: number[][] };
  macro: Record<string, { value: string; name: string; derivation: string }>;
  checks: string[];
  disclaimer: { vi: string; en: string };
  methodology_url: string;
  downloads: Record<"xlsx" | "json" | "md", string>;
};

// GET /vncma/latest/portfolios: asset-class model portfolios (approved), percents are integers.
export type ModelPortfolio = {
  id: string;
  name: string;
  name_en: string;
  target_volatility: string;
  weights: { asset_class: string; name: string; percent: number }[];
  expected_return: string;
  expected_return_arithmetic: string;
  volatility: string;
};

export type ModelPortfolios = {
  release: string;
  as_of: string;
  approved_by: string;
  approved_at: string;
  portfolios: ModelPortfolio[];
  disclaimer: { vi: string; en: string };
};

// GET /funds/stats: approved fund statistics by group (percent per year; null = not enough data).
export type FundSummary = { n: number; min: number; p25: number; p50: number; p75: number; max: number };
export type FundHorizon = { stats: FundSummary | null; benchmark: number | null; beat: number | null };
export type FundGroup = {
  count: number;
  benchmark: "eq_large" | "cash_vnd" | "balanced";
  horizons: Record<string, FundHorizon>;
  volatility: FundSummary | null;
  max_drawdown: FundSummary | null;
};
export type FundStats = {
  as_of: string;
  horizons: number[];
  groups: Record<"equity_fund" | "bond_fund" | "balanced_fund" | "etf", FundGroup>;
  benchmarks: Record<string, Record<string, number | null>>;
  approved_by: string;
  approved_at: string;
  payload_sha256: string;
  method: string;
  disclaimer: { vi: string; en: string };
};
