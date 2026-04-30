/**
 * Types for data/fsp/posts.json.
 *
 * Source of truth: data/fsp/posts.json (wk6_v1_locked).
 * Provenance grades A/B/C are documented in the file's _meta.provenance_grades.
 */

export type ProvenanceGrade = "A" | "B" | "C";

export type AltitudeBand = "low" | "medium" | "high" | "extreme";

export type LonLat = [number, number];

export type DepotTier =
  | "corps_main"
  | "division_sub"
  | "brigade_main";

export type PostType =
  | "forward_base"
  | "subdepot_transit"
  | "forward_picket"
  | "patrol_post"
  | "garrison_subdepot"
  | "observation_post"
  | "border_picket"
  | "brigade_hq_main_depot";

export type SubSector =
  | "DBO_axis"
  | "Pangong_Chushul"
  | "Demchok_Hanle"
  | "Kargil_Drass";

export interface Depot {
  depot_id: string;
  name: string;
  tier: DepotTier;
  coords: LonLat;
  altitude_m: number;
  altitude_band: AltitudeBand;
  supports_subdepots?: string[];
  supports_posts?: string[];
  fed_by?: string[];
  fed_by_depot?: string;
  fed_by_loc_alternate?: string;
  notional_formation?: string;
  provenance_grade: ProvenanceGrade;
  provenance_note: string;
}

export interface Post {
  post_id: string;
  name: string;
  sub_sector: SubSector;
  type: PostType;
  coords: LonLat;
  altitude_m: number;
  altitude_band: AltitudeBand;
  primary_depot: string;
  primary_route_segments_outbound: string[];
  notional_formation: string;
  provenance_grade: ProvenanceGrade;
  provenance_note: string;
  consumption_profile_hint: string;
}

export type LoCType = "land_road" | "air";

export interface LoCAxis {
  loc_id: string;
  name: string;
  type: LoCType;
  approx_length_km?: number;
  key_chokepoint?: string;
  key_chokepoints?: string[];
  seasonal_pattern: string;
  feeds_depot: string;
  icao_dest?: string;
  aircraft_types_typical?: string[];
  cost_multiplier_vs_road?: string;
  provenance_grade: ProvenanceGrade;
  provenance_note: string;
}

export interface PostsFile {
  _meta: {
    artifact: string;
    version: string;
    aoi: string;
    aoi_bbox: [number, number, number, number]; // [west, south, east, north]
    crs: string;
    coord_order: string;
    altitude_unit: string;
    provenance_grades: Record<ProvenanceGrade, string>;
    formation_disclaimer: string;
    altitude_bands: Record<AltitudeBand, string>;
  };
  depots: Depot[];
  posts: Post[];
  loc_axes: LoCAxis[];
}
