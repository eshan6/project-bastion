/**
 * MapView (Wk8) — MapLibre canvas driven by scenario world-state.
 *
 * Wk8 additions over Wk7:
 *  - Post markers color by status (ok/watch/critical/imminent).
 *  - Closed strategic-axis routes render as red dashed polylines.
 *  - Click a post -> calls onSelectPost; the App then renders the detail panel.
 *
 * Tactical edges (post-feeders) deliberately don't render as polylines yet —
 * their geometry would have to be synthesized from post lon-lat (no
 * intermediate points in the data). Wk13 design pass adds those.
 */
import { useEffect, useRef } from "react";
import maplibregl, { LngLatLike, Map as MaplibreMap } from "maplibre-gl";
import type { Depot, Post, PostsFile, RoutesData, RouteSegment } from "@/types";
import type { ScenarioWorldState } from "@/lib/scenarioEngine";
import { STATUS_HEX } from "./StatusPill";

interface MapViewProps {
  posts: PostsFile;
  routes: RoutesData;
  worldState: ScenarioWorldState;
  selectedPostId: string | null;
  onSelectPost: (postId: string | null) => void;
}

const BASEMAP_STYLE = "https://demotiles.maplibre.org/style.json";
const ROUTE_LAYER_ID = "fsp-routes";
const ROUTE_SOURCE_ID = "fsp-routes-source";

export function MapView({
  posts,
  routes,
  worldState,
  selectedPostId,
  onSelectPost,
}: MapViewProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MaplibreMap | null>(null);
  const markersRef = useRef<Map<string, maplibregl.Marker>>(new Map());

  // -- Initialize map once on mount -----------------------------------
  useEffect(() => {
    if (!containerRef.current) return;
    if (mapRef.current) return;

    const [west, south, east, north] = posts._meta.aoi_bbox;
    const center: LngLatLike = [(west + east) / 2, (south + north) / 2];

    const map = new maplibregl.Map({
      container: containerRef.current,
      style: BASEMAP_STYLE,
      center,
      zoom: 6.5,
      maxZoom: 12,
      minZoom: 4,
      attributionControl: { compact: true },
    });

    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    map.addControl(new maplibregl.ScaleControl({ unit: "metric" }), "bottom-left");

    map.on("load", () => {
      map.fitBounds(
        [
          [west, south],
          [east, north],
        ],
        { padding: 40, duration: 0 },
      );

      // Initialize an empty route layer; updated on each worldState change.
      map.addSource(ROUTE_SOURCE_ID, {
        type: "geojson",
        data: { type: "FeatureCollection", features: [] },
      });
      map.addLayer({
        id: ROUTE_LAYER_ID,
        type: "line",
        source: ROUTE_SOURCE_ID,
        paint: {
          "line-color": ["get", "color"],
          "line-width": 3,
          "line-dasharray": [2, 1.5],
          "line-opacity": 0.8,
        },
      });
    });

    // Background click clears selection.
    map.on("click", (ev) => {
      // Only deselect if the click wasn't on a marker (markers stop propagation).
      if ((ev.originalEvent.target as HTMLElement)?.closest(".fsp-post-marker")) {
        return;
      }
      onSelectPost(null);
    });

    mapRef.current = map;

    return () => {
      map.remove();
      mapRef.current = null;
      markersRef.current.clear();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []); // mount once; later effects update state via map APIs

  // -- Render depot markers (static) ----------------------------------
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    const ms: maplibregl.Marker[] = [];
    const onLoad = () => {
      posts.depots.forEach((d) => {
        const m = renderDepotMarker(d).setLngLat(d.coords).addTo(map);
        ms.push(m);
      });
    };
    if (map.isStyleLoaded()) onLoad();
    else map.once("load", onLoad);

    return () => {
      ms.forEach((m) => m.remove());
    };
  }, [posts.depots]);

  // -- Render post markers; refresh fill color on world-state change --
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    const onLoad = () => {
      // Remove old markers
      markersRef.current.forEach((m) => m.remove());
      markersRef.current.clear();

      // Render fresh markers with current status color
      posts.posts.forEach((p) => {
        const snap = worldState.post_states.get(p.post_id);
        const status = snap?.status ?? "ok";
        const color = STATUS_HEX[status];
        const isSelected = p.post_id === selectedPostId;

        const el = buildPostMarkerElement(p, color, isSelected);
        el.addEventListener("click", (ev) => {
          ev.stopPropagation();
          onSelectPost(p.post_id);
        });

        const marker = new maplibregl.Marker({ element: el }).setLngLat(p.coords).addTo(map);
        markersRef.current.set(p.post_id, marker);
      });
    };

    if (map.isStyleLoaded()) onLoad();
    else map.once("load", onLoad);
  }, [posts.posts, worldState, selectedPostId, onSelectPost]);

  // -- Render closed-route polylines ----------------------------------
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    const update = () => {
      const features = buildClosedRouteFeatures(routes, worldState.closed_edge_ids);
      const source = map.getSource(ROUTE_SOURCE_ID) as maplibregl.GeoJSONSource | undefined;
      if (source) {
        source.setData({ type: "FeatureCollection", features });
      }
    };

    if (map.isStyleLoaded()) update();
    else map.once("load", update);
  }, [routes, worldState.closed_edge_ids]);

  return <div ref={containerRef} className="h-full w-full" />;
}

// ---- Marker element builders ------------------------------------------

function buildPostMarkerElement(
  p: Post,
  color: string,
  isSelected: boolean,
): HTMLDivElement {
  const el = document.createElement("div");
  el.className = "fsp-post-marker";
  const size = isSelected ? 14 : 10;
  const ring = isSelected ? "3px" : "2px";
  el.style.cssText = `
    width: ${size}px;
    height: ${size}px;
    border-radius: 50%;
    background: ${color};
    border: ${ring} solid #ffffff;
    box-shadow: 0 1px 2px 0 rgb(15 23 42 / 0.2)${isSelected ? ", 0 0 0 2px " + color : ""};
    cursor: pointer;
    transition: width 80ms, height 80ms, box-shadow 80ms;
  `;
  el.title = `${p.name} (${p.altitude_m}m)`;
  return el;
}

function renderDepotMarker(d: Depot): maplibregl.Marker {
  const el = document.createElement("div");
  el.className = "fsp-depot-marker";
  el.style.cssText = `
    width: 14px;
    height: 14px;
    border-radius: 3px;
    background: #2563eb;
    border: 2px solid #ffffff;
    box-shadow: 0 1px 2px 0 rgb(15 23 42 / 0.2);
    cursor: default;
  `;
  el.title = `${d.name} (${d.altitude_m}m)`;
  return new maplibregl.Marker({ element: el });
}

// ---- GeoJSON for closed-route polylines -------------------------------

/**
 * Build LineString features for any closed edge whose segments have
 * geometry in the data. Strategic-axis segments have from_lon_lat /
 * to_lon_lat; tactical edges don't (they reference post nodes), so
 * they're skipped here. Wk13 will synthesize tactical geometry.
 */
function buildClosedRouteFeatures(
  routes: RoutesData,
  closedEdgeIds: Set<string>,
): GeoJSON.Feature[] {
  if (closedEdgeIds.size === 0) return [];

  const segById: Map<string, RouteSegment> = new Map();
  for (const seg of routes.route_segments) {
    segById.set(seg.segment_id, seg);
  }

  const out: GeoJSON.Feature[] = [];
  for (const edge of routes.route_edges) {
    if (!closedEdgeIds.has(edge.edge_id)) continue;
    const coords: [number, number][] = [];
    for (const segId of edge.segment_ids) {
      const seg = segById.get(segId);
      if (!seg) continue;
      if (seg.from_lon_lat && seg.to_lon_lat) {
        // Append, deduping touching endpoints
        if (coords.length === 0) coords.push(seg.from_lon_lat);
        if (
          coords.length > 0 &&
          (coords[coords.length - 1][0] !== seg.from_lon_lat[0] ||
            coords[coords.length - 1][1] !== seg.from_lon_lat[1])
        ) {
          coords.push(seg.from_lon_lat);
        }
        coords.push(seg.to_lon_lat);
      }
    }
    if (coords.length < 2) continue;
    out.push({
      type: "Feature",
      geometry: { type: "LineString", coordinates: coords },
      properties: {
        edge_id: edge.edge_id,
        edge_name: edge.name,
        color: STATUS_HEX.critical,
      },
    });
  }
  return out;
}
