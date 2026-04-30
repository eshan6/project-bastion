/**
 * Types for data/fsp/routes.json.
 *
 * Important: the JSON file contains string-comment entries like
 *   "//============================================================"
 *   "// STRATEGIC AXIS: ..."
 * interleaved among the route_segments and route_edges arrays for human
 * readability. The useFspData() hook filters these out at parse time so
 * downstream code only sees objects.
 */

import type { LonLat, ProvenanceGrade } from "./posts";

export type SurfaceType =
  | "road_paved"
  | "road_unpaved"
  | "track"
  | "foot"
  | "air_corridor";

export type SegmentOwner = string; // BRO_Beacon, BRO_Vijayak, BRO_Himank, BRO_Deepak, IAF_Western_Air_Command, unit_maintained, ...

export interface RouteSegment {
  segment_id: string;
  loc_axis?: string;
  name: string;
  from_lon_lat?: LonLat;
  to_lon_lat?: LonLat;
  from_node?: string;
  to_node?: string;
  from_icao?: string;
  to_icao?: string;
  length_km?: number;
  great_circle_km?: number;
  surface_type: SurfaceType;
  key_chokepoint: string | null;
  chokepoint_altitude_m: number | null;
  seasonal_availability_baseline: string[];
  closure_drivers: string[];
  owner: SegmentOwner;
  aircraft_typical?: string[];
  lift_capacity_tonnes_per_sortie_typical?: number;
  provenance_grade: ProvenanceGrade;
  notes?: string;
}

export type EdgeType =
  | "strategic_road"
  | "trunk_road"
  | "tactical_road"
  | "tactical_track"
  | "tactical_foot"
  | "air";

export interface RouteEdge {
  edge_id: string;
  name: string;
  type: EdgeType;
  from_node: string;
  to_node: string;
  segment_ids: string[];
  transit_time_hrs_baseline: number;
  max_convoy_size_typical: number;
  cost_per_tonne_baseline: number;
  is_primary_for: string[];
  is_alternate_for: string[];
  provenance_grade: ProvenanceGrade;
  notes?: string;
}

export interface AlternateSummary {
  primary_edge: string;
  alternates_in_priority_order: string[];
  operational_note: string;
}

export interface RoutesFile {
  _meta: {
    artifact: string;
    version: string;
    depends_on: string;
    model_type: string;
    design_notes: string[];
    cost_units: string;
    transit_time_units: string;
    altitude_unit: string;
    provenance_notes: Record<string, string>;
  };
  // The raw arrays in the JSON contain interleaved string comments;
  // useFspData filters these. Downstream consumers see only objects.
  route_segments: (RouteSegment | string)[];
  route_edges: (RouteEdge | string)[];
  alternates_summary: AlternateSummary[];
}

// Cleaned shape after parse-time filtering (what app code actually consumes)
export interface RoutesData {
  _meta: RoutesFile["_meta"];
  route_segments: RouteSegment[];
  route_edges: RouteEdge[];
  alternates_summary: AlternateSummary[];
}
