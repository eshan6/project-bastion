/**
 * Types for data/fsp/vehicles.json.
 *
 * 9 vehicle classes: trucks, animal transport, porters, helicopters.
 * Altitude derate curves and reliability priors are central to the
 * Wk12 optimizer; the scenario engine in Wk8 will read these.
 */

import type { ProvenanceGrade } from "./posts";
import type { SurfaceType } from "./routes";

export type VehicleClass =
  | "medium_truck"
  | "heavy_truck"
  | "light_truck"
  | "light_tactical"
  | "animal_transport"
  | "human_porter"
  | "light_helicopter"
  | "medium_helicopter"
  | "heavy_helicopter";

export type SpeedBySurface = Partial<Record<SurfaceType, number | null>>;

/**
 * Reliability prior structure differs between ground vehicles (deadlines per
 * 1000 vkm) and animal/air assets (availability fractions). We type both.
 */
export type GroundReliabilityPrior = {
  summer_road_paved?: number;
  winter_road_paved?: number;
  summer_road_unpaved?: number;
  winter_road_unpaved?: number;
  summer_track?: number;
  winter_track?: number;
};

export type AvailabilityPrior = Partial<{
  summer_HA: number;
  summer_SHA: number;
  summer_ECC: number;
  winter_HA: number;
  winter_SHA: number;
  winter_ECC: number;
  summer_clear_weather: number;
  summer_marginal_weather: number;
  winter_clear_weather: number;
  winter_marginal_weather: number;
}>;

export interface VehicleClassEntry {
  vehicle_id: string;
  name: string;
  class: VehicleClass;
  manufacturer: string;
  owner: string;

  payload_capacity_kg?: number;
  payload_capacity_kg_sea_level?: number;
  payload_capacity_kg_at_3000m?: number;
  payload_capacity_kg_at_4000m?: number;
  payload_capacity_kg_at_5000m?: number;
  payload_capacity_kg_at_5500m?: number;
  payload_capacity_volume_l?: number;

  range_km_full_tank?: number;
  range_km_full_fuel?: number;
  range_km_per_day?: number;
  range_note?: string;

  fuel_type: string;
  fodder_kg_per_mule_per_day?: number;
  water_l_per_mule_per_day?: number;

  speed_kph_by_surface?: SpeedBySurface;
  speed_kph_cruise?: number;

  surface_compatibility: SurfaceType[];

  altitude_derate_payload?: Record<string, number>;
  altitude_derate_payload_curve?: Record<string, number | string>;

  reliability_prior_deadlines_per_1000_vkm?: GroundReliabilityPrior;
  reliability_prior_availability_fraction?: AvailabilityPrior;

  cold_start_below_minus_20C_failure_rate?: number;

  cost_per_tonne_km_baseline: number;
  fleet_count_typical_per_brigade: string;

  provenance_grade: ProvenanceGrade;
  provenance_note: string;
}

export interface VehicleRouteCompat {
  edge_id: string;
  surface_type_dominant: string;
  compatible_vehicles: string[];
  incompatible_vehicles: string[];
  winter_alternate?: string;
  operational_note: string;
}

export interface VehiclesFile {
  _meta: {
    artifact: string;
    version: string;
    depends_on: string[];
    design_notes: string[];
    surface_compatibility_legend: Record<string, string>;
    altitude_derate_principle: string;
    reliability_units: string;
    cost_units: string;
    provenance_grading: Record<ProvenanceGrade, string>;
  };
  vehicle_classes: VehicleClassEntry[];
  vehicle_to_route_compatibility_summary: VehicleRouteCompat[];
}
