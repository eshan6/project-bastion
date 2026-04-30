/**
 * MapView — MapLibre canvas centered on the XIV Corps AOI bbox.
 *
 * Wk7 scope:
 * - Render the basemap.
 * - Plot all 15 posts and 4 depots as circle markers.
 * - Click a marker -> popup with name, type, altitude, formation.
 *
 * Out of scope this week (slated for Wk8/Wk13):
 * - Status-colored markers driven by scenario state (Wk8).
 * - Hex-binned post boundaries (Wk13 design pass).
 * - Route segment polylines (Wk8 — needed for closure visualization).
 *
 * Basemap choice (TEMPORARY): MapLibre's hosted demo tiles. Free, no key.
 * Wk13 design pass should replace this with a self-hosted PMTiles file
 * clipped to the AOI bbox and styled in light gray to match the app chrome.
 * For Wk7 this is fine — the demo tiles are a reasonable light basemap and
 * unblock the rest of the build.
 */
import { useEffect, useRef } from "react";
import maplibregl, { LngLatLike, Map as MaplibreMap } from "maplibre-gl";
import type { Depot, Post, PostsFile } from "@/types";

interface MapViewProps {
  data: PostsFile;
}

// Light-gray basemap. MapLibre demo tiles are a sensible default for Wk7;
// swap for self-hosted PMTiles in Wk13.
const BASEMAP_STYLE = "https://demotiles.maplibre.org/style.json";

export function MapView({ data }: MapViewProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MaplibreMap | null>(null);

  // -- Initialize map once on mount ----------------------------------
  useEffect(() => {
    if (!containerRef.current) return;
    if (mapRef.current) return; // already initialized

    const [west, south, east, north] = data._meta.aoi_bbox;
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

    // Fit to AOI on load — tighter than a hardcoded zoom and adapts to viewport.
    map.on("load", () => {
      map.fitBounds(
        [
          [west, south],
          [east, north],
        ],
        { padding: 40, duration: 0 },
      );
    });

    mapRef.current = map;

    return () => {
      map.remove();
      mapRef.current = null;
    };
  }, [data._meta.aoi_bbox]);

  // -- Add post + depot markers --------------------------------------
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    const markers: maplibregl.Marker[] = [];
    const onLoad = () => {
      // Depots: square-ish (use a slightly larger circle for now), accent color.
      data.depots.forEach((d) => {
        const m = renderDepotMarker(d).setLngLat(d.coords).addTo(map);
        markers.push(m);
      });
      // Posts: smaller circles, neutral color (status colors come in Wk8).
      data.posts.forEach((p) => {
        const m = renderPostMarker(p).setLngLat(p.coords).addTo(map);
        markers.push(m);
      });
    };

    if (map.isStyleLoaded()) {
      onLoad();
    } else {
      map.once("load", onLoad);
    }

    return () => {
      markers.forEach((m) => m.remove());
    };
  }, [data]);

  return <div ref={containerRef} className="h-full w-full" />;
}

// ---- Marker renderers (plain DOM, kept small so they're easy to restyle) ----

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
    cursor: pointer;
  `;
  const popup = new maplibregl.Popup({ offset: 14, closeButton: false }).setHTML(`
    <div style="min-width: 200px;">
      <div style="font-size: 0.6875rem; color: #2563eb; font-weight: 600; letter-spacing: 0.04em; text-transform: uppercase;">
        Depot · ${escapeHtml(d.tier)}
      </div>
      <div style="font-size: 0.875rem; font-weight: 600; color: #0f172a; margin-top: 2px;">
        ${escapeHtml(d.name)}
      </div>
      <div style="font-size: 0.75rem; color: #475569; margin-top: 6px;">
        ${d.altitude_m.toLocaleString()} m · ${escapeHtml(d.altitude_band)}
      </div>
      ${d.notional_formation ? `<div style="font-size: 0.75rem; color: #475569;">${escapeHtml(d.notional_formation)}</div>` : ""}
      <div style="font-size: 0.6875rem; color: #94a3b8; margin-top: 6px;">
        Provenance: ${d.provenance_grade}
      </div>
    </div>
  `);
  return new maplibregl.Marker({ element: el }).setPopup(popup);
}

function renderPostMarker(p: Post): maplibregl.Marker {
  const el = document.createElement("div");
  el.className = "fsp-post-marker";
  // Wk8 will replace this fill color with status-derived color.
  el.style.cssText = `
    width: 10px;
    height: 10px;
    border-radius: 50%;
    background: #64748b;
    border: 2px solid #ffffff;
    box-shadow: 0 1px 2px 0 rgb(15 23 42 / 0.15);
    cursor: pointer;
  `;
  const popup = new maplibregl.Popup({ offset: 10, closeButton: false }).setHTML(`
    <div style="min-width: 200px;">
      <div style="font-size: 0.6875rem; color: #64748b; font-weight: 600; letter-spacing: 0.04em; text-transform: uppercase;">
        Post · ${escapeHtml(p.type.replace(/_/g, " "))}
      </div>
      <div style="font-size: 0.875rem; font-weight: 600; color: #0f172a; margin-top: 2px;">
        ${escapeHtml(p.name)}
      </div>
      <div style="font-size: 0.75rem; color: #475569; margin-top: 6px;">
        ${p.altitude_m.toLocaleString()} m · ${escapeHtml(p.altitude_band)}
      </div>
      <div style="font-size: 0.75rem; color: #475569;">
        ${escapeHtml(p.sub_sector.replace(/_/g, " "))} · ${escapeHtml(p.notional_formation)}
      </div>
      <div style="font-size: 0.6875rem; color: #94a3b8; margin-top: 6px;">
        Provenance: ${p.provenance_grade}
      </div>
    </div>
  `);
  return new maplibregl.Marker({ element: el }).setPopup(popup);
}

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}
