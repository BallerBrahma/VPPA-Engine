// Mirrors the pydantic response models in src/vppa/api/models.py.

export type Term = { start: string; end: string };

export type ProjectSpec = {
  lat: number;
  lon: number;
  dc_capacity_mw: number;
  tilt_deg: number;
  azimuth_deg: number;
  losses_pct: number;
  tracking: "fixed" | "single_axis" | "single_axis_backtracked";
  county: string | null;
  state: string | null;
  eia_plant_id: number | null;
  commercial_operation: string | null;
};

export type StorageSpec = {
  power_mw: number;
  duration_hours: number;
  round_trip_efficiency: number;
};

export type Contract = {
  name: string;
  display_name: string | null;
  counterparty_view: "buyer" | "seller";
  strike_usd_mwh: number;
  contract_mw: number;
  term: Term;
  settlement_index: "hub" | "node";
  hub: string;
  node: string;
  negative_price_floor: number | null;
  escalation_pct_yr: number;
  project: ProjectSpec;
  storage: StorageSpec | null;
};

export type ContractSummary = {
  file: string;
  contract: Contract;
  label: string;
  location: string | null;
  zone: string | null;
  contract_mw: number;
  tracking: ProjectSpec["tracking"];
  has_storage: boolean;
  storage_mw: number | null;
  term_start: string;
  term_end: string;
  settles_at: "hub" | "node";
  settlement_point: string;
  commercial_operation: string | null;
};

/** Whether one control can be used, and why not when it cannot. `cached` only
 *  means "already on disk, so instant" — an uncached option is slower, never
 *  unavailable. */
export type OptionAvailability = {
  available: boolean;
  cached: boolean;
  reason: string | null;
};

export type YearAvailabilityRow = {
  year: number;
  in_term: boolean;
  analysis: OptionAvailability;
  actual_weather: OptionAvailability;
  node_settlement: OptionAvailability;
};

export type AvailabilityResponse = {
  contract_name: string;
  default_year: number | null;
  storage: OptionAvailability;
  years: YearAvailabilityRow[];
};

export type AnalysisRequest = {
  contract: Contract;
  year: number;
  settle_at_node?: boolean;
  weather?: "tmy" | "actual";
};

export type MonthRow = {
  month: string;
  generation_mwh: number;
  realized_price_usd_mwh: number | null;
  avg_market_price_usd_mwh: number;
  cash_to_buyer_usd: number;
};

export type SettlementResponse = {
  contract_name: string;
  year: number;
  settlement_point: string;
  counterparty: string;
  strike_usd_mwh: number;
  base_strike_usd_mwh: number;
  capture_rate: number;
  breakeven_strike_usd_mwh: number;
  generation_mwh: number;
  cash_to_counterparty_usd: number;
  hours: number;
  in_term: boolean;
  notes: string[];
  monthly: MonthRow[];
};

export type BasisResponse = {
  cost_of_basis_usd_mwh: number;
  mean_basis_usd_mwh: number;
  negative_basis_hours: number;
  negative_basis_share: number;
  hours: number;
  monthly: { month: string; mean_basis_usd_mwh: number }[];
};

export type ScenarioRow = {
  scenario: string;
  label: string;
  generation_mwh: number;
  capture_rate: number;
  breakeven_strike_usd_mwh: number;
  cash_to_buyer_usd: number;
};

export type ScenariosResponse = { scenarios: ScenarioRow[] };

export type StorageResponse = {
  power_mw: number;
  energy_capacity_mwh: number;
  round_trip_efficiency: number;
  capture_rate_base: number;
  capture_rate_with_storage: number;
  uplift_points: number;
  revenue_uplift_usd: number;
  round_trip_loss_mwh: number;
  cycles: number;
  average_day: { hour: number; generation_mwh: number; delivered_mwh: number }[];
};
