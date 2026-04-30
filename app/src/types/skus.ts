/**
 * Types for data/fsp/skus.json.
 *
 * SKUs span 6 stock heads (RATIONS, POL, AMMO, MEDICAL, CLOTHING, GENERAL)
 * with terrain-class consumption multipliers (Plains, HA, SHA, ECC).
 *
 * Note: consumption_baseline_per_* shape varies across SKUs (per-soldier-per-day,
 * per-vehicle-km, per-100-soldiers-per-month, etc.). We model the union of shapes
 * loosely; scenario engine code does the right thing per-SKU.
 */

import type { ProvenanceGrade } from "./posts";

export type StockHead =
  | "RATIONS"
  | "POL"
  | "AMMO"
  | "MEDICAL"
  | "CLOTHING"
  | "GENERAL";

export type CriticalityTier = "T1" | "T2" | "T3" | "T4";

export type TerrainClass =
  | "Plains"
  | "HA"
  | "SHA"
  | "ECC"
  | "HA_extreme_cold"
  | "HA_to_SHA_boundary"
  | "SHA_to_ECC";

/**
 * Per-soldier-per-day baseline consumption keyed by terrain class.
 * Used for rations, kerosene, ammunition (peacetime training scale), etc.
 */
export type PerSoldierPerDay = Partial<Record<"Plains" | "HA" | "SHA" | "ECC", number>>;

export interface SKU {
  sku_id: string;
  name: string;
  stock_head: StockHead;
  criticality_tier: CriticalityTier;
  unit: string;
  unit_weight_kg: number;
  unit_volume_l: number;
  shelf_life_months: number;
  shelf_life_note?: string;

  // One of these consumption shapes will be present; downstream code branches per SKU.
  consumption_baseline_per_soldier_per_day?: PerSoldierPerDay;
  consumption_baseline_per_vehicle_km?: Record<string, number>;
  consumption_baseline_per_generator_hour?: number;
  consumption_baseline_per_sortie?: Record<string, number>;
  consumption_baseline_per_vehicle_per_quarter?: Record<string, number>;
  consumption_baseline_per_100_soldiers_per_month?: PerSoldierPerDay;
  consumption_baseline_per_post_per_month?: Record<string, number>;
  consumption_baseline_per_post_per_quarter?: Record<string, number>;
  consumption_baseline_per_post_per_year?: Record<string, number>;
  consumption_baseline_per_subsector_per_quarter?: number;
  consumption_baseline_per_soldier_per_year?: PerSoldierPerDay;

  consumption_unit?: string;
  altitude_derate_per_1000m_above_3000m?: number;
  winter_uplift_factor: number;
  winter_uplift_note?: string;
  combat_uplift_note?: string;
  freeze_protection_required?: boolean;
  substitution_allowed_with: string[];
  provenance_grade: ProvenanceGrade;
  provenance_note?: string;
}

export interface StockHeadEntry {
  id: StockHead;
  name: string;
  owner: string;
  skus_count: number;
}

export interface SkusFile {
  _meta: {
    artifact: string;
    version: string;
    depends_on: string[];
    design_notes: string[];
    altitude_bands_to_terrain_class_mapping: Record<string, string>;
    post_to_terrain_class: Record<string, TerrainClass>;
    criticality_tiers: Record<CriticalityTier, string>;
    consumption_units: Record<string, string>;
    provenance_grading: Record<ProvenanceGrade, string>;
  };
  stock_heads: StockHeadEntry[];
  skus: SKU[];
}
