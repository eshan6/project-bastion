"""
Project Bastion — Stage 2 Generator: World Builder

Deterministically constructs the static world from a seed:
  - Posts (loaded from config; 35 total in Tangtse Brigade AOR)
  - Routes (computed from post graph; depot ↔ post pairs with realistic distances)
  - Vehicle fleet (250 vehicles, distributed by class share)
  - SKU catalogue (loaded from config; 30 SKUs across 6 stock heads)

All outputs are pandas DataFrames matching the Stage 1 ontology schema.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Tuple

import numpy as np
import pandas as pd

from config import (
    POSTS, SKUS, VEHICLE_CLASSES, TOTAL_VEHICLES, ALTITUDE_BANDS,
)


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two points, km."""
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def road_distance_km(lat1: float, lon1: float, lat2: float, lon2: float,
                     elev1: float, elev2: float) -> float:
    """
    Approximate road distance: great-circle inflated by a terrain factor.
    Eastern Ladakh roads have a typical sinuosity of ~1.6-1.9x straight-line
    (BRO highway alignments cross multiple watersheds). High-altitude
    crossings add more.
    """
    gc = haversine_km(lat1, lon1, lat2, lon2)
    # Base sinuosity 1.65; elevation difference adds switchback penalty.
    elev_penalty = 1.0 + abs(elev2 - elev1) / 1000.0 * 0.15
    return gc * 1.65 * elev_penalty


# ---------------------------------------------------------------------------
# Posts
# ---------------------------------------------------------------------------

def build_posts() -> pd.DataFrame:
    """Materialise the post catalogue from config."""
    df = pd.DataFrame(POSTS)
    # Derive serving depot for each post: the closest depot on the same axis
    # (or any depot if axis is Rear). This drives resupply routing.
    depots = df[df["is_depot"]].copy()

    def find_serving_depot(row):
        if row["is_depot"]:
            return row["id"]
        # Prefer same-axis depot
        candidates = depots[depots["axis"] == row["axis"]]
        if candidates.empty:
            # Fall back: any depot, by road distance
            candidates = depots
        # Pick closest
        dists = candidates.apply(
            lambda d: road_distance_km(row["lat"], row["lon"], d["lat"], d["lon"],
                                       row["elev_m"], d["elev_m"]),
            axis=1,
        )
        return candidates.iloc[int(dists.values.argmin())]["id"]

    df["serving_depot_id"] = df.apply(find_serving_depot, axis=1)
    return df


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

def build_routes(posts_df: pd.DataFrame) -> pd.DataFrame:
    """
    Build the route graph. Each non-depot post gets at least one route
    from its serving depot. Additionally we add:
      - Inter-depot routes (rear-area logistics network)
      - A few cross-axis routes for forward posts (operational flexibility)
    """
    routes = []
    rid = 0

    depots = posts_df[posts_df["is_depot"]]
    non_depots = posts_df[~posts_df["is_depot"]]

    # 1. Depot → forward/mid route for each non-depot post
    for _, post in non_depots.iterrows():
        depot = depots[depots["id"] == post["serving_depot_id"]].iloc[0]
        dist = road_distance_km(depot["lat"], depot["lon"], post["lat"], post["lon"],
                                depot["elev_m"], post["elev_m"])
        # Crossed passes derived from post's served_by list
        # (a route uses all the passes the destination requires)
        passes_crossed = post["served_by"]
        routes.append({
            "route_id": f"R{rid:04d}",
            "origin_id": depot["id"],
            "destination_id": post["id"],
            "distance_km": round(dist, 1),
            "passes_crossed": passes_crossed,
            "elev_max_m": max(depot["elev_m"], post["elev_m"]),
            "route_type": "primary",
            "axis": post["axis"],
        })
        rid += 1

    # 2. Inter-depot routes (Leh ↔ Karu, Karu ↔ Tangtse, Tangtse ↔ Durbuk,
    #    Durbuk ↔ Chushul base) — rear logistics network
    depot_pairs = [
        ("P001", "P002"),  # Leh → Karu
        ("P002", "P003"),  # Karu → Tangtse
        ("P003", "P004"),  # Tangtse → Durbuk
        ("P004", "P005"),  # Durbuk → Chushul base
    ]
    for o, d in depot_pairs:
        o_post = posts_df[posts_df["id"] == o].iloc[0]
        d_post = posts_df[posts_df["id"] == d].iloc[0]
        dist = road_distance_km(o_post["lat"], o_post["lon"], d_post["lat"], d_post["lon"],
                                o_post["elev_m"], d_post["elev_m"])
        # Inter-depot routes inherit the union of pass dependencies
        passes_crossed = sorted(set(o_post["served_by"]) | set(d_post["served_by"]))
        routes.append({
            "route_id": f"R{rid:04d}",
            "origin_id": o,
            "destination_id": d,
            "distance_km": round(dist, 1),
            "passes_crossed": passes_crossed,
            "elev_max_m": max(o_post["elev_m"], d_post["elev_m"]),
            "route_type": "inter_depot",
            "axis": "Rear",
        })
        rid += 1

    return pd.DataFrame(routes)


# ---------------------------------------------------------------------------
# Vehicles
# ---------------------------------------------------------------------------

def build_vehicles(rng: np.random.Generator, posts_df: pd.DataFrame) -> pd.DataFrame:
    """
    250 vehicles distributed across classes by fleet_share, assigned
    home-base depots in proportion to that depot's served troop strength.
    """
    depots = posts_df[posts_df["is_depot"]].copy()
    depot_share = depots["troops"] / depots["troops"].sum()

    vehicles = []
    vid = 0
    for cls_name, cls in VEHICLE_CLASSES.items():
        n = int(round(TOTAL_VEHICLES * cls["fleet_share"]))
        for _ in range(n):
            # Assign home base weighted by depot troop strength
            home_depot = rng.choice(depots["id"].values, p=depot_share.values)
            # Age in days at start of simulation: uniform 0-1825 (0-5 years)
            initial_age = int(rng.uniform(0, 1825))
            vehicles.append({
                "vehicle_id": f"V{vid:04d}",
                "vehicle_class": cls_name,
                "payload_tons": cls["payload_tons"],
                "home_depot_id": home_depot,
                "initial_age_days": initial_age,
                "weibull_shape": cls["weibull_shape"],
                "weibull_scale_days": cls["weibull_scale_days"],
            })
            vid += 1
    return pd.DataFrame(vehicles)


# ---------------------------------------------------------------------------
# SKUs
# ---------------------------------------------------------------------------

def build_skus() -> pd.DataFrame:
    """Materialise the SKU catalogue from config."""
    return pd.DataFrame(SKUS)


# ---------------------------------------------------------------------------
# Top-level build
# ---------------------------------------------------------------------------

@dataclass
class World:
    posts: pd.DataFrame
    routes: pd.DataFrame
    vehicles: pd.DataFrame
    skus: pd.DataFrame

    def summary(self) -> str:
        lines = [
            f"World summary:",
            f"  Posts:    {len(self.posts)} ({(self.posts['is_depot']).sum()} depots, "
            f"{((self.posts['band']=='mid')).sum()} mid, "
            f"{((self.posts['band']=='forward')).sum()} forward)",
            f"  Routes:   {len(self.routes)}",
            f"  Vehicles: {len(self.vehicles)} across {self.vehicles['vehicle_class'].nunique()} classes",
            f"  SKUs:     {len(self.skus)} across {self.skus['head'].nunique()} stock heads",
            f"  Elev range: {self.posts['elev_m'].min()} - {self.posts['elev_m'].max()} m",
            f"  Total troops: {self.posts['troops'].sum():,}",
        ]
        return "\n".join(lines)


def build_world(seed: int = 42) -> World:
    rng = np.random.default_rng(seed)
    posts = build_posts()
    routes = build_routes(posts)
    vehicles = build_vehicles(rng, posts)
    skus = build_skus()
    return World(posts=posts, routes=routes, vehicles=vehicles, skus=skus)


if __name__ == "__main__":
    w = build_world(seed=42)
    print(w.summary())
