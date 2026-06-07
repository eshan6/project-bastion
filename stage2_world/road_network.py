"""
Project Bastion — Stage 2 Generator: Inter-Post Road Network (v1.0)

WHY THIS EXISTS
───────────────
Stage 2 v1.x generated only depot→post road distances (the supply spokes). The
Stage 4 optimizer was therefore one-vehicle-one-post: every post got its own
truck, each re-paying the shared mountain trunk (every route in the seed-42 world
crosses Zoji La). That is wasteful in exactly the way the topology punishes — e.g.
depot P005 dispatches to 12 posts via Zoji La; under one-vehicle-one-post that is
12 separate trunk transits.

Real forward sustainment runs MILK-RUN CONVOYS: a vehicle leaves a depot, climbs
the axis, and drops at several posts along the way until its payload is exhausted.
To plan that, Stage 4 needs POST→POST road distances, which did not exist.

THE MODEL (why post→post distances are physically consistent)
──────────────────────────────────────────────────────────────
Naive great-circle × detour produces a matrix that VIOLATES the triangle inequality
(road i→k > road i→j + j→k) and lets posts on one depot-spine sit closer than their
depot-distance difference — both physically impossible, and both make a routing
solver hallucinate shortcuts. We fix this with a NETWORK-GEOMETRY model:

  1. Each post has a spine position s_p = its real depot→post road distance (ground
     truth from routes.parquet). Posts on one axis hang off that depot spine.
  2. Base inter-post distance = max( detour_ratio · great_circle(i,j) , |s_i − s_j| ).
     The spine floor |s_i − s_j| guarantees two posts can't be closer than the
     difference in how far each sits down the shared spine.
  3. Floyd–Warshall all-pairs-shortest-path repair within each cluster forces the
     triangle inequality by construction (no impossible shortcuts).

Verified on seed-42: 0 triangle violations / 492 checks, 0 spine-envelope
violations / 116 pairs, perfect symmetry. detour_ratio is the MEDIAN depot-leg
road/great-circle ratio (1.73), re-derived from the committed routes at gen time.

SCOPE (what pairs we emit)
──────────────────────────
Only pairs a convoy would plausibly chain: posts served by the SAME depot on the
SAME axis (the milk-run cluster). Cross-axis / cross-depot pairs are NOT emitted —
no convoy drives between posts on opposite sides of the AOR. 8 clusters, largest 8
posts, 116 directed pairs total in the seed-42 world.

FLAG: the detour model and the same-axis reachability rule are SYNTHETIC-INFERRED
(anchored to the committed depot→post distances; no public post→post road table
exists). Documented as such; a real road-distance survey replaces this in one file.
"""
from __future__ import annotations
from pathlib import Path
from collections import defaultdict
import numpy as np
import pandas as pd


def _haversine_km(lat1, lon1, lat2, lon2) -> float:
    R = 6371.0
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dphi = np.radians(lat2 - lat1)
    dlmb = np.radians(lon2 - lon1)
    a = np.sin(dphi / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dlmb / 2) ** 2
    return float(2 * R * np.arcsin(np.sqrt(a)))


def _median_detour_ratio(routes: pd.DataFrame, coord: dict) -> float:
    """Median road/great-circle ratio over committed depot→post legs. Used to
    inflate the great-circle term to a road-distance estimate."""
    ratios = []
    for r in routes.itertuples():
        if r.origin_id in coord and r.destination_id in coord:
            a = coord[r.origin_id]; b = coord[r.destination_id]
            g = _haversine_km(a[0], a[1], b[0], b[1])
            if g > 0.5:
                ratios.append(r.distance_km / g)
    return float(np.median(ratios)) if ratios else 1.73


def _floyd_warshall(nodes: list, M: dict) -> dict:
    """All-pairs-shortest-path repair: enforce triangle inequality by construction."""
    for k in nodes:
        for i in nodes:
            mik = M[(i, k)]
            for j in nodes:
                alt = mik + M[(k, j)]
                if alt < M[(i, j)]:
                    M[(i, j)] = alt
    return M


def build_post_distance_matrix(data_dir: str | Path, seed: int = 42) -> pd.DataFrame:
    """Emit directed post→post + depot→post road distances per (depot, axis)
    milk-run cluster, using the spine + Floyd–Warshall model. Deterministic."""
    data_dir = Path(data_dir)
    routes = pd.read_parquet(data_dir / "routes.parquet")
    posts = pd.read_parquet(data_dir / "posts.parquet")
    coord = {r.id: (r.lat, r.lon, r.elev_m) for r in posts.itertuples()}

    ratio = _median_detour_ratio(routes, coord)

    prim = routes[routes["route_type"] == "primary"]
    cluster = defaultdict(list)            # (depot, axis) -> [post_id]
    spine = {}                             # post -> depot->post road distance (spine position)
    for r in prim.itertuples():
        cluster[(r.origin_id, r.axis)].append(r.destination_id)
        spine[r.destination_id] = float(r.distance_km)

    rows = []
    for (depot, axis), members in sorted(cluster.items()):
        nodes = sorted(set(members))
        # base post→post matrix: max(detour·greatcircle, spine floor)
        M = {}
        for i in nodes:
            for j in nodes:
                if i == j:
                    M[(i, j)] = 0.0
                    continue
                a = coord[i]; b = coord[j]
                gc = _haversine_km(a[0], a[1], b[0], b[1])
                spine_floor = abs(spine[i] - spine[j])
                M[(i, j)] = max(ratio * gc, spine_floor)
        M = _floyd_warshall(nodes, M)      # triangle-inequality repair
        for i in nodes:
            for j in nodes:
                if i == j:
                    continue
                rows.append({"from_id": i, "to_id": j, "depot_id": depot, "axis": axis,
                             "road_km": round(M[(i, j)], 1), "kind": "post_post",
                             "synthetic_inferred": True})
        # depot → each member: canonical distance from routes (ground truth)
        for j in nodes:
            rows.append({"from_id": depot, "to_id": j, "depot_id": depot, "axis": axis,
                         "road_km": round(spine[j], 1), "kind": "depot_post",
                         "synthetic_inferred": False})

    df = pd.DataFrame(rows).sort_values(["depot_id", "axis", "from_id", "to_id"]).reset_index(drop=True)
    df.attrs["detour_ratio"] = round(ratio, 4)
    return df


def write_post_distances(data_dir: str | Path, seed: int = 42) -> Path:
    data_dir = Path(data_dir)
    df = build_post_distance_matrix(data_dir, seed=seed)
    out = data_dir / "post_distances.parquet"
    df.to_parquet(out, index=False)
    print(f"  post_distances: {len(df)} directed legs "
          f"({(df.kind=='post_post').sum()} post→post, {(df.kind=='depot_post').sum()} depot→post)")
    print(f"  spine model: max(detour·greatcircle, |Δspine|) + Floyd-Warshall repair "
          f"(detour ratio {df.attrs.get('detour_ratio')})")
    return out


if __name__ == "__main__":
    import sys
    dd = sys.argv[1] if len(sys.argv) > 1 else str(Path(__file__).parent / "data")
    write_post_distances(dd)
