/**
 * useFspData — single hook that loads all five FSP demo content files
 * from /data/*.json (served by Vite from app/public/data/, which is
 * synced from data/fsp/ at build time).
 *
 * Why one hook for all five: the demo always renders against the full
 * data set; partial loads would show inconsistent state. Better to
 * block on a single Promise.all and render once.
 *
 * Routes.json contains string-comment entries (header dividers like
 *   "//============================================================"
 * interleaved with route objects for human readability. We filter
 * those out here so component code only sees objects.
 */
import { useEffect, useState } from "react";
import type {
  PostsFile,
  RoutesFile,
  RoutesData,
  RouteEdge,
  RouteSegment,
  SkusFile,
  VehiclesFile,
  ScenariosFile,
} from "@/types";

export interface FspData {
  posts: PostsFile;
  routes: RoutesData;
  skus: SkusFile;
  vehicles: VehiclesFile;
  scenarios: ScenariosFile;
}

export type FspDataState =
  | { status: "loading" }
  | { status: "ready"; data: FspData }
  | { status: "error"; error: string };

const FILES = {
  posts: "/data/posts.json",
  routes: "/data/routes.json",
  skus: "/data/skus.json",
  vehicles: "/data/vehicles.json",
  scenarios: "/data/scenarios.json",
} as const;

async function fetchJson<T>(url: string): Promise<T> {
  const res = await fetch(url, { cache: "no-cache" });
  if (!res.ok) {
    throw new Error(`fetch ${url} failed: HTTP ${res.status} ${res.statusText}`);
  }
  return (await res.json()) as T;
}

/**
 * routes.json mixes objects with string section-header comments inside
 * its `route_segments` and `route_edges` arrays. Strip the strings.
 */
function cleanRoutes(raw: RoutesFile): RoutesData {
  const segments = raw.route_segments.filter(
    (entry): entry is RouteSegment =>
      typeof entry === "object" && entry !== null && "segment_id" in entry,
  );
  const edges = raw.route_edges.filter(
    (entry): entry is RouteEdge =>
      typeof entry === "object" && entry !== null && "edge_id" in entry,
  );
  return {
    _meta: raw._meta,
    route_segments: segments,
    route_edges: edges,
    alternates_summary: raw.alternates_summary,
  };
}

export function useFspData(): FspDataState {
  const [state, setState] = useState<FspDataState>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;

    (async () => {
      try {
        const [posts, routesRaw, skus, vehicles, scenarios] = await Promise.all([
          fetchJson<PostsFile>(FILES.posts),
          fetchJson<RoutesFile>(FILES.routes),
          fetchJson<SkusFile>(FILES.skus),
          fetchJson<VehiclesFile>(FILES.vehicles),
          fetchJson<ScenariosFile>(FILES.scenarios),
        ]);

        const routes = cleanRoutes(routesRaw);

        // Sanity check the demo's locked invariants. If any of these fail,
        // a data file has been edited in a way that breaks downstream code.
        // Better to fail loud at boot than render wrong numbers.
        const errors: string[] = [];
        if (posts.posts.length !== 15) {
          errors.push(`posts: expected 15, got ${posts.posts.length}`);
        }
        if (posts.depots.length !== 4) {
          errors.push(`depots: expected 4, got ${posts.depots.length}`);
        }
        if (posts.loc_axes.length !== 3) {
          errors.push(`loc_axes: expected 3, got ${posts.loc_axes.length}`);
        }
        if (skus.skus.length !== 30) {
          errors.push(`skus: expected 30, got ${skus.skus.length}`);
        }
        if (vehicles.vehicle_classes.length !== 9) {
          errors.push(`vehicles: expected 9, got ${vehicles.vehicle_classes.length}`);
        }
        if (scenarios.scenarios.length !== 3) {
          errors.push(`scenarios: expected 3, got ${scenarios.scenarios.length}`);
        }
        if (errors.length > 0) {
          throw new Error(`Locked-data invariant violations:\n  - ${errors.join("\n  - ")}`);
        }

        if (!cancelled) {
          setState({
            status: "ready",
            data: { posts, routes, skus, vehicles, scenarios },
          });
        }
      } catch (e) {
        if (!cancelled) {
          setState({
            status: "error",
            error: e instanceof Error ? e.message : String(e),
          });
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, []);

  return state;
}
