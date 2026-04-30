/**
 * Types for data/fsp/scenarios.json.
 *
 * Three scripted scenarios drive the demo timeline. Each has:
 * - disruption_events fired on specific days
 * - focal_post_projection or focal_cluster_projection with key_projection_days
 * - resupply_options at the day a critical-state alert pops
 *
 * The Wk8 scenario engine reads this file to determine world-state per (scenario, day).
 */

export type ScenarioId =
  | "SCEN-01-NORMAL_OPS"
  | "SCEN-02-ZOJI_LA_CASCADE"
  | "SCEN-03-VEHICLE_DEADLINE_CASCADE";

export type PostStatus = "ok" | "watch" | "critical" | "imminent";

export type DisruptionType =
  | "vehicle_reliability_signal"
  | "weather_minor"
  | "demand_uplift"
  | "weather_severe"
  | "demand_recognition"
  | "secondary_disruption"
  | "vehicle_deadline";

export interface RouteImpact {
  [edgeId: string]: string; // e.g. "EDGE-ZOJI-LEH": "closed"
}

export interface DisruptionEvent {
  day: number;
  type: DisruptionType;
  description: string;
  data_source?: string;
  operator_visibility_without_bastion?: string;
  route_impacts?: RouteImpact & { implication?: string };
  fleet_impact?: string;
  horizon_impact?: string;
  non_obvious_insight?: string;
}

export interface ProjectionDay {
  kerosene_stock_L?: number;
  cluster_stock_L?: number;
  kerosene_stock_L_if_full_convoy?: number;
  kerosene_stock_L_actual?: number;
  actual_stock_calc?: string;
  days_to_stockout_at_current_burn?: number;
  days_to_stockout?: number;
  days_to_stockout_summer_burn?: number;
  days_to_stockout_winter_burn?: number;
  days_to_winter_stockout_actual?: number;
  winter_target_60kL_gap_L?: number;
  status: PostStatus | "critical_for_winter_readiness";
  note?: string;
}

export interface FocalPostProjection {
  post_id: string;
  post_name: string;
  headcount: number;
  terrain_class: string;
  season: string;

  kerosene_daily_burn_L?: number;
  kerosene_burn_calc?: string;
  kerosene_burn_phases?: Record<string, { daily_burn_L: number; calc: string }>;

  focal_skus?: string[];

  key_projection_days: Record<string, ProjectionDay>;
}

export interface FocalClusterProjection {
  cluster_name: string;
  cluster_posts: string[];
  cluster_total_headcount: number;
  focal_sku: string;
  winter_uplift_factor: number;
  daily_burn_L_by_post: Record<
    string,
    { hc: number; burn_L_per_day: number; calc: string }
  >;
  cluster_burn_total_L_per_day: number;
  key_projection_days: Record<string, ProjectionDay>;
}

export interface ResupplyOption {
  option_id: string;
  name: string;
  plan: string;
  tonnes_delivered: number;
  tonnes_breakdown?: string;
  cost_INR_lakhs: number;
  cost_breakdown?: string;
  cost_note?: string;
  time_days: number;
  risk_P_complete: number;
  risk_drivers: string;
  why_recommended: string;
}

export interface ResupplyOptionsCard {
  context: string;
  options: ResupplyOption[];
  tradeoff_summary: string;
}

export interface SystemRecommendation {
  trigger: string;
  non_obvious_insight: string;
  recommended_action: string;
  operator_value: string;
}

export interface Scenario {
  scenario_id: ScenarioId;
  title: string;
  narrative_one_liner: string;
  season_start: string;
  duration_days: number;
  weather_assumption: string;

  starting_state: {
    all_routes_open: boolean;
    open_routes?: string[];
    closed_routes?: string[];
    closed_routes_reason?: string;
    all_passes_open?: boolean;
    vehicle_fleet_full_strength?: boolean;
    starting_inventory_focal_posts: Record<string, Record<string, number | string>>;
    planned_dbo_surge_convoy?: Record<string, unknown>;
  };

  disruption_events: DisruptionEvent[];
  focal_post_projection?: FocalPostProjection;
  focal_cluster_projection?: FocalClusterProjection;

  system_recommendation_at_day_18?: SystemRecommendation;
  resupply_options_at_day_12_alert?: ResupplyOptionsCard;
  resupply_options_at_day_10_alert?: ResupplyOptionsCard;
}

export interface ScenariosFile {
  _meta: {
    artifact: string;
    version: string;
    depends_on: string[];
    design_notes: string[];
    headcount_assumptions: {
      rationale: string;
      values: Record<string, number>;
    };
    demo_starting_inventory_assumptions: {
      rationale: string;
      approach: string;
    };
    math_methodology: Record<string, string>;
    demo_narrative_use: string;
  };
  scenarios: Scenario[];
  cross_scenario_demo_value: string[];
}
