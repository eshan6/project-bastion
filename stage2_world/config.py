"""
Project Bastion — Stage 2 Generator: Calibration Parameters

Every parameter in this file is either:
  (a) anchored to a named public source (citation in comment), or
  (b) flagged as SYNTHETIC-ARBITRARY where no public source exists.

This is the single source of truth for the synthetic world's physics.
Changes here propagate through all generators.

AOR: 3rd Infantry Division (Trishul) — Tangtse Brigade-equivalent slice
of Eastern Ladakh. Per XIV Corps Wikipedia entry, the Tangtse-based
brigade has historical responsibility for the Pangong/Chushul/Demchok
axis. We model ~35 posts within the box 32.5–35.5°N, 76–79.5°E.

History window: 3 years of daily history.
Seed: 42 (deterministic regeneration).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

# ---------------------------------------------------------------------------
# Global
# ---------------------------------------------------------------------------

DEFAULT_SEED = 42
SEED = 42   # canonical world seed
START_DATE = date(2022, 1, 1)
END_DATE = date(2024, 12, 31)   # 3 years inclusive
N_DAYS = (END_DATE - START_DATE).days + 1   # 1096

# AOR bounding box (Eastern Ladakh, Tangtse Brigade-equivalent)
AOR_LAT_MIN, AOR_LAT_MAX = 32.5, 35.5
AOR_LON_MIN, AOR_LON_MAX = 76.0, 79.5

# ---------------------------------------------------------------------------
# Weather: IMD-anchored climatology
# ---------------------------------------------------------------------------
# Three real anchor stations. We use Leh, Drass, and a Tangtse-equivalent
# (extrapolated from Leh + lapse rate, since no IMD station at Tangtse).
#
# Sources:
#   Leh: IMD-derived from "Variability of Precipitation regime in Ladakh
#        region of India from 1901-2000" (Romshoo et al.), and
#        climatestotravel.com aggregate of IMD normals.
#   Drass: en.wikipedia.org/wiki/Dras citing Köppen Dsb climate,
#        Municipal Committee Kargil official portal (mckargil.in/climate.html).
#   Tangtse: extrapolated (no IMD station). Marked accordingly.

# Anchor stations: (name, lat, lon, elev_m, monthly_T_max_C, monthly_T_min_C,
#                   monthly_precip_mm, monthly_snow_days)
# Index 0=Jan, 11=Dec. Temperatures are climatological monthly means of
# daily max / daily min.

ANCHOR_LEH = {
    "name": "Leh",
    "lat": 34.1526, "lon": 77.5770, "elev_m": 3500,
    # Source: Weather-Atlas + climatestotravel + IMD 100yr study (1901-2000).
    # Daily max / daily min monthly normals, °C.
    "t_max_c": [-2.8, 0.5, 6.9, 12.6, 17.4, 21.5, 24.7, 24.2, 21.0, 14.4,  7.7,  1.4],
    "t_min_c": [-14.0,-11.6,-6.4,-1.0,  3.6,  7.4, 10.7, 10.2,  6.0, -1.0, -7.0,-11.4],
    # Monthly precip mm. The IMD 100yr study (Romshoo et al., Leh 1901-2000)
    # reports annual total ~50-70mm with Jan 11.3mm, Feb 7.8mm, Dec 5.8mm,
    # Nov 2.3mm as winter; Jul 15.2mm and Aug 15.4mm as wettest.
    # Weather-Atlas reports much higher (439mm) — likely includes
    # snow-on-ground depth observations rather than water-equivalent.
    # We anchor to the IMD figures.
    "precip_mm": [11.3, 7.8, 6.0, 5.0, 5.0, 6.0, 15.2, 15.4, 6.0, 3.0, 2.3, 5.8],
    # Days with any snowfall per month (climatological).
    "snow_days":  [9, 8, 7, 5, 2, 0, 0, 0, 0, 1, 4, 7],
}

ANCHOR_DRASS = {
    "name": "Drass",
    "lat": 34.4244, "lon": 75.7558, "elev_m": 3300,
    # Source: Wikipedia (en.wikipedia.org/wiki/Dras) — winters avg low -20°C,
    # summers ~23°C; annual precip ~550mm concentrated Dec-May.
    # Weather-Atlas Drass monthly profile harmonised with Köppen Dsb.
    "t_max_c": [-7.0, -4.5,  1.5,  8.5, 14.0, 20.0, 23.0, 22.0, 18.0, 11.0,  4.0, -3.5],
    "t_min_c": [-21.0,-18.5,-12.0,-4.5,  0.5,  5.0,  8.0,  7.5,  3.5, -3.0, -9.5,-16.5],
    "precip_mm": [85.0, 75.0, 70.0, 60.0, 45.0, 25.0, 30.0, 25.0, 30.0, 35.0, 50.0, 70.0],
    "snow_days":  [11, 10, 9, 6, 2, 0, 0, 0, 0, 2, 6, 9],
}

# Tangtse extrapolation (no IMD station at Tangtse, ~3,950m elev).
# Built from Leh + lapse rate adjustment (Leh is 3,500m, Tangtse 3,950m,
# +450m → temperature shift -2.9°C using ELR 6.5°C/km).
# Marked SYNTHETIC-EXTRAPOLATED.
ANCHOR_TANGTSE = {
    "name": "Tangtse",
    "lat": 34.0228, "lon": 78.1764, "elev_m": 3950,
    "t_max_c": [-5.7, -2.4,  4.0,  9.7, 14.5, 18.6, 21.8, 21.3, 18.1, 11.5,  4.8, -1.5],
    "t_min_c": [-16.9,-14.5,-9.3, -3.9,  0.7,  4.5,  7.8,  7.3,  3.1, -3.9, -9.9,-14.3],
    # Tangtse precip: Leh-anchored × 1.15 for modest orographic uplift
    # (Pangong basin is slightly wetter than Leh proper but still arid).
    "precip_mm": [13.0, 9.0, 7.0, 5.8, 5.8, 7.0, 17.5, 17.7, 7.0, 3.5, 2.6, 6.7],
    "snow_days":  [10, 9, 8, 6, 2, 0, 0, 0, 0, 1, 5, 8],
}

ANCHOR_STATIONS = [ANCHOR_LEH, ANCHOR_DRASS, ANCHOR_TANGTSE]

# Environmental lapse rate (standard atmospheric): -6.5°C per 1000m.
# Used to derive per-post temperatures from nearest anchor.
LAPSE_RATE_C_PER_KM = 6.5

# Daily noise model: each day's actual temperature deviates from
# climatological mean by a Gaussian shock + persistence (AR(1) component).
# Calibrated against typical day-to-day variability at Leh: σ≈3-4°C in
# summer, σ≈4-6°C in winter (climatestotravel descriptive ranges).
DAILY_TEMP_NOISE_SIGMA = 3.5      # base σ°C
DAILY_TEMP_NOISE_WINTER_BOOST = 1.5  # added Nov-Mar
DAILY_TEMP_PERSISTENCE = 0.55     # AR(1) coefficient; 0.55 ≈ 2-3 day weather inertia

# Western Disturbance event model: episodic large precipitation events
# in winter (Dec-Mar), 4-8 events per winter season per location.
# Sources: Met Centre Leh advisories (x.com/metcentreleh) reference 4-6
# significant WDs per winter; the Tribune (Mar 2026 article) flags
# "very heavy snowfall" as recurring even in benign winters.
WD_EVENTS_PER_WINTER_LAMBDA = 6.0   # Poisson mean per winter Dec-Mar
WD_EVENT_DURATION_DAYS = (1, 4)      # uniform range
WD_EVENT_PRECIP_MULT = (1.8, 4.5)    # precip multiplier on affected days
WD_EVENT_TEMP_DROP_C = (4.0, 12.0)   # temp drop range during WD

# ---------------------------------------------------------------------------
# Strategic passes: closure model
# ---------------------------------------------------------------------------
# Five strategic passes within or adjacent to AOR. Calibration from
# BRO PIB releases, Tribune coverage, and Wikipedia.
#
# Two distinct closure regimes:
#   1. ZOJI LA-TYPE: long seasonal closure (Dec/Jan → Mar/Apr).
#      Modeled with a closure-start date drawn from a Gaussian
#      around historical mean, and reopening date similar.
#   2. KHARDUNG LA-TYPE: no permanent closure, stochastic short
#      closures (1-5 days) triggered by snowfall events.

PASSES = {
    "Zoji La": {
        "elev_m": 3528,  # 11,575 ft (BRO operational figure)
        # PIB 2022: avg historical closure 150 days, 2022 record 73 days.
        # Tribune Mar 2026: 2025-26 winter Zoji La open beyond Feb 28
        # (unprecedented). We model the MODERN regime (post-2020 BRO),
        # since that's the realistic operating environment now.
        "closure_regime": "seasonal",
        "closure_start_doy_mean": 357,  # ~Dec 23 average modern start
        "closure_start_doy_sigma": 14,
        "closure_duration_days_mean": 75,   # modern era (33-79 day range)
        "closure_duration_days_sigma": 18,
        "min_closure_days": 25,             # 2025 BRO record was 33
        "max_closure_days": 130,            # bad winters can still reach this
        # Probability of within-open-season interruption (avalanche, fresh storm)
        "interim_closure_prob_per_day": 0.008,  # ~3 days/year of interim closures
        "interim_closure_duration": (1, 3),
        "served_posts_classification": "rear_admin",  # closure isolates posts
        "notes": "Primary Srinagar-Leh axis. Closure forces dependence on Manali axis or airlift.",
    },
    "Khardung La": {
        "elev_m": 5359,
        # Wikipedia: "no permanent winter closure" — Army keeps it open
        # for Siachen/Nubra. Kashmir Monitor 25 Aug 2025: traffic
        # suspended after heavy snow. Pattern is stochastic short closures.
        "closure_regime": "stochastic",
        "winter_closure_prob_per_day": 0.04,   # ~Nov-Mar, ~5 closures/winter
        "summer_closure_prob_per_day": 0.003,  # rare monsoon-related
        "closure_duration": (1, 4),
        "served_posts_classification": "nubra_axis",
        "notes": "Permanent military priority. Short interruptions only.",
    },
    "Chang La": {
        "elev_m": 5360,
        # Same regime as Khardung La per Vargis Khan analysis.
        # Critical for Pangong/Chushul access.
        "closure_regime": "stochastic",
        "winter_closure_prob_per_day": 0.035,
        "summer_closure_prob_per_day": 0.002,
        "closure_duration": (1, 5),
        "served_posts_classification": "pangong_axis",
        "notes": "Gateway to Pangong sector. Short interruptions only.",
    },
    "Tsaka La": {
        "elev_m": 4724,
        # Internal AOR pass on Chushul-Dungti axis. Less documented;
        # treated as Chang La-equivalent.
        # SYNTHETIC-INFERRED from regional pattern.
        "closure_regime": "stochastic",
        "winter_closure_prob_per_day": 0.03,
        "summer_closure_prob_per_day": 0.002,
        "closure_duration": (1, 4),
        "served_posts_classification": "chushul_demchok",
        "notes": "Internal axis. SYNTHETIC-INFERRED priors.",
    },
    "Marsimik La": {
        "elev_m": 5582,
        # Very high pass NE of Chang La, road to Hot Springs area.
        # Higher elevation → more frequent closures.
        # SYNTHETIC-INFERRED.
        "closure_regime": "stochastic",
        "winter_closure_prob_per_day": 0.06,
        "summer_closure_prob_per_day": 0.004,
        "closure_duration": (1, 6),
        "served_posts_classification": "hot_springs_galwan",
        "notes": "Very high. SYNTHETIC-INFERRED priors, elevation-scaled.",
    },
}

# Snowfall-event-triggered closure boost: when a major snow event
# hits, multiply closure probability. Threshold is in water-equivalent
# precip; 4mm/day water-eq ≈ 40-50mm of fresh snow at <1°C, which is
# operationally significant for high passes.
SNOW_EVENT_CLOSURE_BOOST = 8.0
SNOW_EVENT_THRESHOLD_MM = 4.0

# ---------------------------------------------------------------------------
# Posts: brigade lay-down
# ---------------------------------------------------------------------------
# 35 posts total in the Tangtse Brigade AOR slice:
#   - 5 depot/base nodes (3000-3500m): Leh, Karu, Tangtse, Durbuk, Chushul-base
#   - 12 mid-altitude admin/transit (3500-4500m)
#   - 18 forward posts (4200-5400m) at the LAC
#
# Real toponyms used where publicly attested (Galwan, DBO, Chushul, Demchok,
# Hot Springs, Pangong sector "Finger" positions, Rezang La, Spanggur Gap,
# Tsaka La, Hanle, Nyoma, Loma, Dungti, Fukche, Chumur, Tangtse, Durbuk,
# Karu, Leh). For unattested forward posts we generate plausible
# "Post-N" labels with realistic coordinates.
#
# Each post has:
#   id, name, lat, lon, elev_m, altitude_band, troop_strength,
#   served_by_passes (which strategic passes must be open for ground resupply),
#   admin_axis (Pangong / Chushul / Demchok / DBO / Hot_Springs / Rear).

POSTS = [
    # === Rear / Depot tier (3000-3500m) ===
    # has_air_resupply: True for depots (Leh has IXL airport, others have
    # helipads), reducing the isolation-driven consumption multiplier.
    {"id": "P001", "name": "Leh Garrison",          "lat":34.1526,"lon":77.5770,"elev_m":3500,"band":"depot","troops":2000,"served_by":["Zoji La"],"axis":"Rear","is_depot":True,"has_air_resupply":True},
    {"id": "P002", "name": "Karu Logistics Base",   "lat":33.9219,"lon":77.7836,"elev_m":3460,"band":"depot","troops":1800,"served_by":["Zoji La"],"axis":"Rear","is_depot":True,"has_air_resupply":True},
    {"id": "P003", "name": "Tangtse Brigade HQ",    "lat":34.0228,"lon":78.1764,"elev_m":3950,"band":"depot","troops":1200,"served_by":["Zoji La","Chang La"],"axis":"Pangong","is_depot":True,"has_air_resupply":True},
    {"id": "P004", "name": "Durbuk Transit Camp",   "lat":34.0700,"lon":78.0500,"elev_m":3850,"band":"depot","troops":800, "served_by":["Zoji La","Chang La"],"axis":"Pangong","is_depot":True,"has_air_resupply":True},
    {"id": "P005", "name": "Chushul Base",          "lat":33.5736,"lon":78.6450,"elev_m":4350,"band":"depot","troops":900, "served_by":["Zoji La","Chang La","Tsaka La"],"axis":"Chushul","is_depot":True,"has_air_resupply":True},

    # === Mid-altitude admin / transit (3500-4500m) ===
    # Most mid-altitude posts have helipad access (Nyoma, Fukche airstrips per CDFD highway article)
    {"id": "P006", "name": "Sakti Admin Post",      "lat":34.0700,"lon":77.9100,"elev_m":3800,"band":"mid","troops":300,"served_by":["Zoji La"],"axis":"Pangong","is_depot":False,"has_air_resupply":True},
    {"id": "P007", "name": "Zingral Camp",          "lat":34.0900,"lon":78.0200,"elev_m":4100,"band":"mid","troops":250,"served_by":["Zoji La","Chang La"],"axis":"Pangong","is_depot":False,"has_air_resupply":False},
    {"id": "P008", "name": "Lukung Forward",        "lat":34.1200,"lon":78.2700,"elev_m":4250,"band":"mid","troops":400,"served_by":["Zoji La","Chang La"],"axis":"Pangong","is_depot":False,"has_air_resupply":False},
    {"id": "P009", "name": "Spangmik Outpost",      "lat":34.0900,"lon":78.4200,"elev_m":4280,"band":"mid","troops":200,"served_by":["Zoji La","Chang La"],"axis":"Pangong","is_depot":False,"has_air_resupply":False},
    {"id": "P010", "name": "Man-Merak Camp",        "lat":33.9500,"lon":78.5400,"elev_m":4300,"band":"mid","troops":280,"served_by":["Zoji La","Chang La"],"axis":"Pangong","is_depot":False,"has_air_resupply":False},
    {"id": "P011", "name": "Loma Admin Post",       "lat":33.2600,"lon":78.7500,"elev_m":4200,"band":"mid","troops":350,"served_by":["Zoji La","Chang La","Tsaka La"],"axis":"Demchok","is_depot":False,"has_air_resupply":True},
    {"id": "P012", "name": "Nyoma Camp",            "lat":33.1800,"lon":78.6500,"elev_m":4180,"band":"mid","troops":450,"served_by":["Zoji La","Chang La","Tsaka La"],"axis":"Demchok","is_depot":False,"has_air_resupply":True},
    {"id": "P013", "name": "Hanle Observatory Camp","lat":32.7800,"lon":78.9600,"elev_m":4500,"band":"mid","troops":220,"served_by":["Zoji La","Chang La","Tsaka La"],"axis":"Demchok","is_depot":False,"has_air_resupply":False},
    {"id": "P014", "name": "Dungti Forward",        "lat":33.0500,"lon":78.7200,"elev_m":4310,"band":"mid","troops":300,"served_by":["Zoji La","Chang La","Tsaka La"],"axis":"Demchok","is_depot":False,"has_air_resupply":False},
    {"id": "P015", "name": "Fukche Admin",          "lat":32.9000,"lon":79.2200,"elev_m":4180,"band":"mid","troops":320,"served_by":["Zoji La","Chang La","Tsaka La"],"axis":"Demchok","is_depot":False,"has_air_resupply":True},
    {"id": "P016", "name": "Tangste-North Transit", "lat":34.1100,"lon":78.1500,"elev_m":4000,"band":"mid","troops":180,"served_by":["Zoji La","Chang La"],"axis":"Pangong","is_depot":False,"has_air_resupply":False},
    {"id": "P017", "name": "Shyok Junction",        "lat":34.2500,"lon":78.0500,"elev_m":3700,"band":"mid","troops":260,"served_by":["Zoji La"],"axis":"DBO","is_depot":False,"has_air_resupply":False},

    # === Forward posts (4200-5400m) — LAC-facing ===
    # DBO Forward Base has a major ALG (C-130J landed there 2013, per news);
    # most others rely on Mi-17/Cheetah helicopters when weather permits.
    {"id": "P018", "name": "Finger-4 OP",           "lat":33.8500,"lon":78.7800,"elev_m":4400,"band":"forward","troops":120,"served_by":["Zoji La","Chang La"],"axis":"Pangong","is_depot":False,"has_air_resupply":False},
    {"id": "P019", "name": "Finger-8 Listening Post","lat":33.7800,"lon":78.9500,"elev_m":4380,"band":"forward","troops":90,"served_by":["Zoji La","Chang La"],"axis":"Pangong","is_depot":False,"has_air_resupply":False},
    {"id": "P020", "name": "Rezang La Memorial OP", "lat":33.4700,"lon":78.7100,"elev_m":4900,"band":"forward","troops":150,"served_by":["Zoji La","Chang La","Tsaka La"],"axis":"Chushul","is_depot":False,"has_air_resupply":False},
    {"id": "P021", "name": "Spanggur Gap OP",       "lat":33.4900,"lon":78.7900,"elev_m":4400,"band":"forward","troops":140,"served_by":["Zoji La","Chang La","Tsaka La"],"axis":"Chushul","is_depot":False,"has_air_resupply":False},
    {"id": "P022", "name": "Black Top OP",          "lat":33.5300,"lon":78.7400,"elev_m":5200,"band":"forward","troops":80,"served_by":["Zoji La","Chang La","Tsaka La"],"axis":"Chushul","is_depot":False,"has_air_resupply":False},
    {"id": "P023", "name": "Helmet Top OP",         "lat":33.5500,"lon":78.7200,"elev_m":5100,"band":"forward","troops":75,"served_by":["Zoji La","Chang La","Tsaka La"],"axis":"Chushul","is_depot":False,"has_air_resupply":False},
    {"id": "P024", "name": "Demchok Forward",       "lat":32.7000,"lon":79.4500,"elev_m":4350,"band":"forward","troops":110,"served_by":["Zoji La","Chang La","Tsaka La"],"axis":"Demchok","is_depot":False,"has_air_resupply":False},
    {"id": "P025", "name": "Chumur Forward",        "lat":32.6200,"lon":78.6800,"elev_m":4500,"band":"forward","troops":130,"served_by":["Zoji La","Chang La","Tsaka La"],"axis":"Demchok","is_depot":False,"has_air_resupply":False},
    {"id": "P026", "name": "Koyul OP",              "lat":33.0800,"lon":78.9500,"elev_m":4600,"band":"forward","troops":85,"served_by":["Zoji La","Chang La","Tsaka La"],"axis":"Demchok","is_depot":False,"has_air_resupply":False},
    {"id": "P027", "name": "Hot Springs PP-15",     "lat":34.3500,"lon":78.6500,"elev_m":4900,"band":"forward","troops":95,"served_by":["Zoji La","Chang La","Marsimik La"],"axis":"Hot_Springs","is_depot":False,"has_air_resupply":False},
    {"id": "P028", "name": "Kongka La OP",          "lat":34.3100,"lon":79.0000,"elev_m":5180,"band":"forward","troops":70,"served_by":["Zoji La","Chang La","Marsimik La"],"axis":"Hot_Springs","is_depot":False,"has_air_resupply":False},
    {"id": "P029", "name": "Gogra Post-17A",        "lat":34.4300,"lon":78.7800,"elev_m":4750,"band":"forward","troops":100,"served_by":["Zoji La","Chang La","Marsimik La"],"axis":"Hot_Springs","is_depot":False,"has_air_resupply":False},
    {"id": "P030", "name": "Galwan PP-14",          "lat":34.7800,"lon":78.9100,"elev_m":4300,"band":"forward","troops":140,"served_by":["Zoji La"],"axis":"DBO","is_depot":False,"has_air_resupply":False},
    {"id": "P031", "name": "Galwan Estuary OP",     "lat":34.8200,"lon":78.7200,"elev_m":4250,"band":"forward","troops":115,"served_by":["Zoji La"],"axis":"DBO","is_depot":False,"has_air_resupply":False},
    {"id": "P032", "name": "Depsang North OP",      "lat":35.2500,"lon":77.9500,"elev_m":5200,"band":"forward","troops":110,"served_by":["Zoji La"],"axis":"DBO","is_depot":False,"has_air_resupply":False},
    {"id": "P033", "name": "Burtsa Camp",           "lat":35.0500,"lon":78.0500,"elev_m":4800,"band":"forward","troops":95,"served_by":["Zoji La"],"axis":"DBO","is_depot":False,"has_air_resupply":False},
    {"id": "P034", "name": "DBO Forward Base",      "lat":35.3700,"lon":77.7400,"elev_m":5050,"band":"forward","troops":250,"served_by":["Zoji La"],"axis":"DBO","is_depot":False,"has_air_resupply":True},
    {"id": "P035", "name": "Karakoram Approach OP", "lat":35.4900,"lon":77.7800,"elev_m":5400,"band":"forward","troops":60,"served_by":["Zoji La"],"axis":"DBO","is_depot":False,"has_air_resupply":False},
]

# Altitude band definitions for consumption modulation.
# Sources for consumption-altitude coupling: CAG report on Siachen/Ladakh
# (special ration scales); Tribune (Jan 2025) "Providing logistics in
# Ladakh a test of mettle"; Swarajyamag (Oct 2020) Indian Army winter
# logistics piece.

ALTITUDE_BANDS = {
    "depot":   {"elev_min": 3000, "elev_max": 3700, "ration_mult": 1.0,  "kerosene_mult": 1.0,  "medical_mult": 1.0},
    "mid":     {"elev_min": 3700, "elev_max": 4500, "ration_mult": 1.15, "kerosene_mult": 1.8,  "medical_mult": 1.4},
    "forward": {"elev_min": 4500, "elev_max": 5400, "ration_mult": 1.35, "kerosene_mult": 3.2,  "medical_mult": 2.2},
}
# Rationale: CAG flagged calorie shortfall ~48-82% — special HA ration
# scales are ~1.3-1.5x normal. Kerosene multiplier is dominated by
# heating burden, which scales sharply with temperature drop and
# therefore with altitude. Medical scales with AMS/HAPE risk.

# ---------------------------------------------------------------------------
# SKU catalogue (30 SKUs across 6 stock heads)
# ---------------------------------------------------------------------------
# Sources for stock-head structure: Indian Army Ordnance Corps "stock heads"
# terminology, Tribune logistics piece (rations / engineering stores /
# weapons / clothing / medical / ammunition).

SKUS = [
    # === Rations (8 SKUs) ===
    # Base consumption rates are per-soldier-per-day at depot-tier baseline.
    # Sources: Standard Army ration scales (publicly referenced in CAG report);
    # high-altitude scale uplift factor applied via ALTITUDE_BANDS.
    {"sku": "RAT-001","head":"Rations","name":"Atta/Flour (kg)",         "base_per_soldier_day":0.50, "shelf_life_days":180, "tier":1, "weather_sensitivity":"low"},
    {"sku": "RAT-002","head":"Rations","name":"Rice (kg)",                "base_per_soldier_day":0.30, "shelf_life_days":365, "tier":1, "weather_sensitivity":"low"},
    {"sku": "RAT-003","head":"Rations","name":"Dal/Pulses (kg)",          "base_per_soldier_day":0.12, "shelf_life_days":270, "tier":1, "weather_sensitivity":"low"},
    {"sku": "RAT-004","head":"Rations","name":"Cooking Oil (L)",          "base_per_soldier_day":0.08, "shelf_life_days":365, "tier":1, "weather_sensitivity":"low"},
    {"sku": "RAT-005","head":"Rations","name":"Fresh Meat (kg)",          "base_per_soldier_day":0.18, "shelf_life_days":7,   "tier":1, "weather_sensitivity":"low"},
    {"sku": "RAT-006","head":"Rations","name":"Tinned Rations (units)",   "base_per_soldier_day":1.50, "shelf_life_days":730, "tier":1, "weather_sensitivity":"med"},  # winter spike
    {"sku": "RAT-007","head":"Rations","name":"Tea/Sugar (kg)",           "base_per_soldier_day":0.05, "shelf_life_days":365, "tier":2, "weather_sensitivity":"med"},
    {"sku": "RAT-008","head":"Rations","name":"Dry Fruits (g) HA-ration", "base_per_soldier_day":40.0, "shelf_life_days":270, "tier":1, "weather_sensitivity":"low"},  # CAG-cited HA-special

    # === POL (4 SKUs) ===
    # Tribune (Jan 2025): "Fuel requirements, including kerosene for heating,
    # are colossal." Swarajyamag: winter-grade kerosene/diesel unfreezing at -33°C.
    # Realistic baseline: ~0.3 L/soldier/day at depot autumn baseline,
    # rising to 0.8-1.2 L/soldier/day at forward posts in deep winter.
    # Stacking: 0.3 × 3.2 (forward altitude) × ~2.0 (deep cold) ≈ 1.9 L,
    # consistent with bukhari operational consumption rates.
    {"sku": "POL-001","head":"POL","name":"Kerosene (L) Winter-Grade",     "base_per_soldier_day":0.30,"shelf_life_days":730, "tier":1, "weather_sensitivity":"extreme"},
    {"sku": "POL-002","head":"POL","name":"Diesel HSD (L)",                "base_per_soldier_day":0.8, "shelf_life_days":365, "tier":1, "weather_sensitivity":"high"},
    {"sku": "POL-003","head":"POL","name":"Petrol MS (L)",                 "base_per_soldier_day":0.15,"shelf_life_days":180, "tier":2, "weather_sensitivity":"med"},
    {"sku": "POL-004","head":"POL","name":"Lubricants (L)",                "base_per_soldier_day":0.04,"shelf_life_days":540, "tier":2, "weather_sensitivity":"low"},

    # === Ammunition (5 SKUs) ===
    # Tempo-driven (convoy frequency proxy), not weather-driven.
    {"sku": "AMM-001","head":"Ammunition","name":"5.56mm Ball (rds)",      "base_per_soldier_day":0.4, "shelf_life_days":3650,"tier":2, "weather_sensitivity":"none"},
    {"sku": "AMM-002","head":"Ammunition","name":"7.62mm (rds)",           "base_per_soldier_day":0.25,"shelf_life_days":3650,"tier":2, "weather_sensitivity":"none"},
    {"sku": "AMM-003","head":"Ammunition","name":"40mm UBGL (rds)",        "base_per_soldier_day":0.01,"shelf_life_days":3650,"tier":3, "weather_sensitivity":"none"},
    {"sku": "AMM-004","head":"Ammunition","name":"81mm Mortar (rds)",      "base_per_soldier_day":0.005,"shelf_life_days":3650,"tier":3,"weather_sensitivity":"none"},
    {"sku": "AMM-005","head":"Ammunition","name":"Pyro/Illum (units)",     "base_per_soldier_day":0.02,"shelf_life_days":1825,"tier":2, "weather_sensitivity":"low"},

    # === Clothing/ECC&E (4 SKUs) ===
    # CAG-cited deficiency 24-100% in HQ reserves. ECC&E = Extreme Cold
    # Clothing & Equipment. Consumption is mostly replacement-driven,
    # not daily. Modeled as monthly per-soldier issue rates.
    {"sku": "CLO-001","head":"Clothing","name":"Multi-Purpose Boots (pair)","base_per_soldier_day":0.003,"shelf_life_days":1825,"tier":2, "weather_sensitivity":"high"},
    {"sku": "CLO-002","head":"Clothing","name":"ECC&E Jacket (unit)",       "base_per_soldier_day":0.002,"shelf_life_days":1825,"tier":2, "weather_sensitivity":"high"},
    {"sku": "CLO-003","head":"Clothing","name":"Snow Goggles (pair)",       "base_per_soldier_day":0.005,"shelf_life_days":1095,"tier":3, "weather_sensitivity":"med"},
    {"sku": "CLO-004","head":"Clothing","name":"Thermal Sleeping Bag (unit)","base_per_soldier_day":0.001,"shelf_life_days":2555,"tier":2, "weather_sensitivity":"high"},

    # === Medical (5 SKUs) ===
    # AMS/HAPE/HACE risk scales with altitude. Medical consumption
    # is weather-coupled (cold injuries) and altitude-coupled.
    {"sku": "MED-001","head":"Medical","name":"Diamox/Acetazolamide (tabs)","base_per_soldier_day":0.8, "shelf_life_days":730,"tier":1, "weather_sensitivity":"med"},
    {"sku": "MED-002","head":"Medical","name":"Dexamethasone (vial)",       "base_per_soldier_day":0.01,"shelf_life_days":545,"tier":1, "weather_sensitivity":"high"},
    {"sku": "MED-003","head":"Medical","name":"Oxygen Cylinder (refill)",   "base_per_soldier_day":0.003,"shelf_life_days":3650,"tier":1,"weather_sensitivity":"high"},
    {"sku": "MED-004","head":"Medical","name":"Frostbite Kit (unit)",       "base_per_soldier_day":0.001,"shelf_life_days":1095,"tier":2,"weather_sensitivity":"extreme"},
    {"sku": "MED-005","head":"Medical","name":"Antibiotics-General (course)","base_per_soldier_day":0.015,"shelf_life_days":730,"tier":2,"weather_sensitivity":"med"},

    # === Engineer Stores (4 SKUs) ===
    {"sku": "ENG-001","head":"Engineer","name":"Bukhari Stove (unit)",      "base_per_soldier_day":0.0008,"shelf_life_days":3650,"tier":2,"weather_sensitivity":"high"},
    {"sku": "ENG-002","head":"Engineer","name":"Prefab Shelter Panel (m2)", "base_per_soldier_day":0.002, "shelf_life_days":3650,"tier":3,"weather_sensitivity":"low"},
    {"sku": "ENG-003","head":"Engineer","name":"Sandbags (units)",          "base_per_soldier_day":0.4,   "shelf_life_days":730, "tier":3,"weather_sensitivity":"low"},
    {"sku": "ENG-004","head":"Engineer","name":"Concertina Wire (m)",       "base_per_soldier_day":0.05,  "shelf_life_days":1825,"tier":3,"weather_sensitivity":"none"},
]

# ---------------------------------------------------------------------------
# Consumption coupling
# ---------------------------------------------------------------------------
# Weather → kerosene coupling: PIECEWISE. Above 0°C: linear, small slope.
# Below 0°C: kink — burn rate roughly triples at -20°C vs reference.
# This matches the qualitative behaviour described in the Tribune logistics
# piece ("colossal") and in CAG's calorie-shortfall coupling (more
# fuel needed to cook in extreme cold). Calibration target: Jan/Jul
# forward-post ratio = 3-6x.
KEROSENE_TEMP_COUPLING = {
    "above_0_slope_per_C": -0.025,  # very slight rise as temp drops 0-25°C
    "below_0_kink_temp": 0.0,
    "below_0_slope_per_C": -0.12,   # ~+2.4x multiplier at -20°C from kink alone
    "ref_temp_C": 10.0,             # reference temp for base rate (depot autumn day)
}

# Tempo proxy: ammunition + petrol scale with "convoy frequency".
# We model tempo as a slow-varying state (monthly-ish) representing
# patrol/exercise intensity. Higher tempo → higher ammo, fuel, lower
# clothing-replacement (because units rotate less to depot).
TEMPO_LEVELS = ["low", "normal", "high", "crisis"]
TEMPO_TRANSITION_PROBS_DAILY = {
    # P(tempo on day t+1 | tempo on day t)
    "low":     {"low": 0.97,  "normal": 0.029, "high": 0.001,  "crisis": 0.0},
    "normal":  {"low": 0.005, "normal": 0.985, "high": 0.010,  "crisis": 0.0},
    "high":    {"low": 0.0,   "normal": 0.020, "high": 0.978,  "crisis": 0.002},
    "crisis":  {"low": 0.0,   "normal": 0.0,   "high": 0.015,  "crisis": 0.985},
}
TEMPO_AMMO_MULT = {"low": 0.6, "normal": 1.0, "high": 1.8, "crisis": 3.5}
TEMPO_POL_MULT  = {"low": 0.7, "normal": 1.0, "high": 1.4, "crisis": 2.2}

# Disruption isolation coupling: when a post's serving passes are all
# closed simultaneously, the post is "isolated" — bukhari/kerosene draw
# accelerates (no resupply, switch to cached stock, also units cluster
# for warmth). We model this as a multiplier on POL and rations.
ISOLATION_KEROSENE_BOOST = 1.30   # 30% more burn during isolation
ISOLATION_RATION_BOOST = 1.08     # marginal — caloric needs the same,
                                  # but waste/spoilage rises slightly
ISOLATION_MEDICAL_BOOST = 1.20    # cold-injury risk rises in isolation

# Lognormal consumption noise: real per-day consumption is lumpy.
CONSUMPTION_LOGNORMAL_SIGMA = 0.18   # ~20% per-day CV

# ---------------------------------------------------------------------------
# Vehicles
# ---------------------------------------------------------------------------
# Fleet composition: per the public sources, 6,000 trucks deployed by
# Army in Ladakh in 2020 (Swarajyamag). At Brigade scale (~12,000-15,000
# troops in our slice), we'd expect ~600-800 vehicles. We model 250
# vehicles assigned to this brigade's logistic units, which is roughly
# the share that would do active resupply runs.
#
# Classes: Stallion 4x4, Stallion 6x6, Tata LPTA, BharatBenz HD.

VEHICLE_CLASSES = {
    "Stallion-4x4": {
        # Ashok Leyland Stallion 4x4, payload 5t, ICBR-validated.
        "payload_tons": 5.0, "fuel_l_per_100km_lowland": 22, "fuel_l_per_100km_highalt": 38,
        "fleet_share": 0.45,
        # Survival prior: median time to first deadline event.
        # CAG audits flagged ECC&E and vehicle availability shortfalls;
        # we anchor "expected high-altitude useful life before major
        # deadline" at ~24 months median, with Weibull shape 1.4
        # (mild ageing acceleration). SYNTHETIC-INFERRED from CAG patterns.
        "weibull_shape": 1.4, "weibull_scale_days": 730,
    },
    "Stallion-6x6": {
        "payload_tons": 7.5, "fuel_l_per_100km_lowland": 28, "fuel_l_per_100km_highalt": 48,
        "fleet_share": 0.25,
        "weibull_shape": 1.4, "weibull_scale_days": 700,
    },
    "Tata-LPTA": {
        # Tata LPTA 713/715 light, payload 2.5t. Workhorse for last-mile.
        "payload_tons": 2.5, "fuel_l_per_100km_lowland": 16, "fuel_l_per_100km_highalt": 28,
        "fleet_share": 0.20,
        "weibull_shape": 1.3, "weibull_scale_days": 800,
    },
    "BharatBenz-HD": {
        # BharatBenz 3128 / similar heavy, payload 10t.
        "payload_tons": 10.0, "fuel_l_per_100km_lowland": 32, "fuel_l_per_100km_highalt": 56,
        "fleet_share": 0.10,
        "weibull_shape": 1.5, "weibull_scale_days": 650,  # newer, harsher use
    },
}
TOTAL_VEHICLES = 250

# Vehicle deadline hazard modifiers (multiplicative on Weibull hazard).
# Modeled as features that accelerate ageing.
VEHICLE_HAZARD_ALTITUDE_MULT = {
    # mission altitude band → hazard multiplier per mission day
    "depot":   1.0,
    "mid":     1.4,
    "forward": 2.1,    # Stryker high-altitude trial failure (Mar 2025) demonstrates real penalty
}
VEHICLE_HAZARD_WINTER_MULT = 1.6   # mission in Nov-Mar
VEHICLE_HAZARD_DISRUPTION_MULT = 2.4   # mission across closed/marginal pass

# Per-mission cycle assumption: average vehicle does ~12 missions/month
# in road-open season, ~5 missions/month in winter (axis dependent).
MISSIONS_PER_MONTH_OPEN = 12
MISSIONS_PER_MONTH_WINTER = 5

# Time to repair after deadline event (days).
REPAIR_TIME_DEPOT_DAYS = (3, 10)
REPAIR_TIME_FIELD_DAYS = (1, 4)
DEADLINE_REQUIRES_DEPOT_PROB = 0.35

# ---------------------------------------------------------------------------
# Holiday / religious calendar tempo modifiers
# ---------------------------------------------------------------------------
# Indian Army operational tempo dips on major civilian holidays only
# slightly (Republic Day, Independence Day, Army Day → ceremonial,
# logistics steady). Lossar (Ladakhi New Year, late Dec-early Jan)
# is locally observed.
KEY_DATES = {
    "republic_day": (1, 26),
    "army_day": (1, 15),
    "independence_day": (8, 15),
    "lossar": (12, 30),     # approximate, varies by lunar calendar
    "diwali_proxy_window_start": (10, 25),
    "diwali_proxy_window_end": (11, 15),
}

# Consumption seasonal modifiers (week-of-year-based).
# Aggregates the holiday/religious calendar plus seasonal tempo.

# ---------------------------------------------------------------------------
# Stock dynamics: AWS (Advance Winter Stocking), receipts, spoilage
# ---------------------------------------------------------------------------
# The stock layer runs a forward accounting identity per (post, SKU, day):
#   closing = opening + aws_receipt + routine_receipt - consumption - spoilage
#
# Sources for the AWS doctrine:
#   The Tribune (Jan 2025) "Providing logistics in Ladakh a test of mettle"
#     — describes the "Road open period" when ration, POL, ammunition,
#       clothing, medical stores are inducted in bulk before winter.
#   Swarajyamag (Oct 2020) — underground fuel dumps (400,000 L each),
#       winter-grade kerosene pre-positioned for the harsh winter.
#   CAG Report 2017-18 — shortfalls happen but are audit-flagged
#       exceptions, not the steady state; concentrated in specific
#       SKUs/posts.

# Road-open season: the window when bulk AWS induction happens.
# Tribune frames it as roughly the snow-free months; for Eastern Ladakh
# the forward axes are practically trafficable bulk-convoy-wise May-Sep.
AWS_SEASON_MONTHS = [5, 6, 7, 8, 9]

# AWS target sizing is TOPOLOGY-DRIVEN, not an abstract doctrine number.
# The target a post pre-positions is sized to outlast its own longest
# plausible isolation window (derived from the pass-status data), so a
# post that gets cut off for 120 days automatically stocks deeper than
# one cut off for 40 — no per-post hand-tuning.
#
#   planning_days = max(longest_isolation_run + margin, tier_floor)
#   aws_target_qty = planning_days * winter_rate_p80
#                    * tier_safety_mult * attainment_fraction

# Margin added to the longest observed isolation run — the post plans for
# a window somewhat longer than the worst it has actually seen.
AWS_ISOLATION_PLANNING_MARGIN_DAYS = 30

# Tier-dependent floor on planning days: even a never-isolated post holds
# a baseline buffer, because routine convoys can still be weather- or
# tempo-delayed. Tier 1 = life-critical (rations, kerosene, core medical).
AWS_TIER_MIN_PLANNING_DAYS = {1: 75, 2: 50, 3: 35}

# Tier safety multiplier: Tier-1 is stocked with the deepest margin —
# the post would rather over-stock kerosene than sandbags. This is the
# margin ON TOP of the planning-days horizon.
AWS_TIER_SAFETY_MULT = {1: 1.6, 2: 1.3, 3: 1.1}

# Per-winter planning variance. Without this, a post plans IDENTICALLY
# every winter (same longest-ever isolation run + same fixed margin), so
# the only thing that varies year to year is the attainment draw — and
# every forward post ends up failing in the same month in the same way,
# a deterministic wall rather than a signal.
#
# Real logistics staff plan off RECENT, IMPERFECT experience: last
# winter's isolation, an imperfect seasonal forecast, a margin that is
# itself a judgement call. So the planning horizon a post actually uses
# is a noisy estimate around its true isolation exposure — some winters
# it over-plans, some it under-plans, and THAT is what makes a stockout
# a function of (this winter's severity) vs (this winter's plan), which
# is the genuine, learnable signal.
AWS_PLANNING_HORIZON_NOISE_FRAC = 0.18   # lognormal-ish spread on planning days
AWS_PLANNING_MARGIN_NOISE_DAYS = 20      # +/- jitter on the isolation margin

# Ammunition is tempo-driven, and a brigade cannot perfectly forecast
# next winter's operational tempo when it plans AWS. Most winters the
# pre-positioned ammo is sized about right; occasionally the winter runs
# hot (a tense LAC season, more firing) and ammo sized off a normal-tempo
# forecast falls short. This is an EPISODIC ammo failure — a minority of
# post-winters — not an every-post-every-year wall.
AWS_AMMO_TEMPO_MISESTIMATE_HEADS = ["Ammunition"]
# Per-winter multiplier on the ammo planning rate: mostly ~1.0, with a
# left tail (under-planned: a hot winter the staff did not see coming).
# Beta(6, 2.2) -> mean ~0.73; rescaled so mean ~0.97, left tail reaches
# ~0.7 (planned for 70% of the tempo the winter actually brought).
AWS_AMMO_TEMPO_BETA_A = 6.0
AWS_AMMO_TEMPO_BETA_B = 2.2
AWS_AMMO_TEMPO_MISESTIMATE_MEAN = 0.97
AWS_AMMO_TEMPO_MISESTIMATE_MIN = 0.68
AWS_AMMO_TEMPO_MISESTIMATE_MAX = 1.20

# AWS execution is imperfect. Each post-SKU draws an "AWS attainment
# fraction" — the fraction of its coverage target it actually achieves.
# Centered just below 1.0, so MOST posts mostly succeed (per CAG framing:
# shortfalls are the exception), with a left tail of under-provisioned
# post-SKUs that will be the genuine stockout-risk signal.
#   Beta(8, 1.6) -> mean ~0.83, but we rescale to mean ~0.93 with a
#   floor and a small over-shoot allowance.
AWS_ATTAINMENT_BETA_A = 8.0
AWS_ATTAINMENT_BETA_B = 1.6
AWS_ATTAINMENT_MIN = 0.55          # worst-provisioned post-SKU floor
AWS_ATTAINMENT_MAX = 1.15          # some posts over-stock
AWS_ATTAINMENT_MEAN_TARGET = 0.93  # rescale Beta draw to this mean

# Which SKUs bear the brunt when AWS under-provisions. This is NOT
# imposed directly — it emerges because the attainment shortfall, applied
# to the SKUs with the steepest winter demand ramp (kerosene) and the
# shortest shelf life (perishables), produces the deepest relative gaps.
# We additionally apply an attainment penalty to POL to reflect that bulk
# fuel is the hardest thing to pre-position (volume) — consistent with
# the Tribune's "colossal" fuel framing.
#
# The POL drag is deliberately stronger than a token nudge: kerosene is
# the SKU the FSP most needs to be able to predict a stockout for (steep
# winter ramp, deep isolation lift), so a meaningful minority of forward
# post-winters must enter genuinely short on it. The drag + a POL-specific
# attainment floor below the global floor put a real left tail on POL
# provisioning. Combined with winter kerosene demand whose P90/P95
# (596/768 L/day at forward posts) runs well above the P80 the AWS target
# is sized against, a cold-and-long winter can outrun even an adequately
# provisioned post — the genuine, hard-to-predict signal.
AWS_HARD_TO_STOCK_HEADS = ["POL"]              # extra attainment drag
AWS_HARD_TO_STOCK_PENALTY = 0.83               # multiplies attainment for POL
AWS_POL_ATTAINMENT_MIN = 0.42                  # POL-specific floor, below global 0.55
AWS_PERISHABLE_SHELF_LIFE_CUTOFF_DAYS = 30     # SKUs below this can't be deep-stocked
AWS_PERISHABLE_MAX_COVERAGE_DAYS = 14          # perishables capped regardless of target

# Routine (non-AWS) receipts: convoys top posts up year-round, whenever
# the post is reachable. This is ANTICIPATORY, not emergency-triggered —
# every time a convoy CAN run to a post, it tops the post up toward its
# topology-sized planning horizon. A post bleeds down only while it is
# genuinely cut off; the moment it is reachable again, it is refilled.
ROUTINE_RECEIPT_REFILL_TO_COVERAGE_DAYS = 75   # fallback target if no planning_days
ROUTINE_RECEIPT_CONVOY_LATENCY_DAYS = (2, 6)   # dispatch-to-arrival lag, uniform
# Convoy cadence throttle: a post-SKU is not topped up every single day.
# A convoy is dispatched at most once per ROUTINE_CONVOY_MIN_GAP_DAYS,
# and only if cover sits below the planning horizon by a meaningful
# margin (otherwise small daily wobble would trigger constant convoys).
ROUTINE_CONVOY_MIN_GAP_DAYS = 10
ROUTINE_CONVOY_DISPATCH_GAP_DAYS = 20   # only dispatch if (planning_days - cover) > this
# Routine receipts only happen if the post is reachable (serving passes
# open) — uses the same pass_status the isolation logic uses.

# POL convoy throttle: bulk fuel cannot be trickled in as freely as
# boxed stores. A POL routine convoy carries a capped volume (it is a
# tanker run, not a general-stores top-up) and runs on a slower cadence.
# This means a forward post that enters winter short on kerosene cannot
# be fully rescued mid-season by routine convoys — the AWS shortfall and
# the late-winter demand ramp are allowed to bite.
POL_CONVOY_MIN_GAP_DAYS = 24            # slower cadence than general stores
POL_CONVOY_MAX_REFILL_COVERAGE_DAYS = 35  # one tanker run tops up ~35 days, not the full horizon

# Perishable demand substitution: a 7-day-shelf item (fresh meat) cannot
# survive a multi-week isolation, and a post does not keep drawing fresh
# meat it knows is not there — it switches to tinned/dried rations. So a
# perishable "stockout" is a SHORT depletion gap at the onset of an
# isolation run, after which the perishable's effective demand decays to
# a residual floor and the substitute SKU absorbs the displaced demand.
#
# This keeps the perishable gap REAL (it still happens, still labelled
# stockout) without it becoming 90% of the stockout signal as a wall of
# near-identical rows — and it creates a genuine cross-SKU substitution
# pattern (tinned-ration consumption spikes when fresh meat gaps) that a
# forecasting model can learn.
PERISHABLE_SUBSTITUTION_ENABLED = True
PERISHABLE_GAP_GRACE_DAYS = 3           # days at zero stock before demand starts decaying
PERISHABLE_DEMAND_DECAY_RATE = 0.45     # per-day multiplicative decay of effective demand
PERISHABLE_DEMAND_RESIDUAL_FLOOR = 0.08 # effective demand floors at 8% of nominal
# Map: perishable SKU -> substitute SKU that absorbs the displaced demand.
# Displaced demand is converted by the ratio of their per-soldier base
# rates so the substitution is calorie/quantity-sensible.
PERISHABLE_SUBSTITUTE_MAP = {
    "RAT-005": "RAT-006",   # Fresh Meat -> Tinned Rations
}

# Emergency perishable resupply: posts WITH air resupply (the
# has_air_resupply flag on the post) get an intermittent perishable
# trickle even while road-isolated — heli/air-drop of fresh rations.
# It is expensive and weather-gated, so it is neither continuous nor
# guaranteed: a per-isolated-day dispatch probability, blocked on
# severe-weather days. Posts without the flag get none — most forward
# posts genuinely cannot get fresh rations during a long cutoff.
EMERGENCY_PERISHABLE_RESUPPLY_ENABLED = True
EMERGENCY_PERISHABLE_DISPATCH_PROB = 0.12     # per isolated day, if post has air resupply
EMERGENCY_PERISHABLE_REFILL_COVERAGE_DAYS = 6 # an air-drop covers ~6 days of perishable demand
EMERGENCY_PERISHABLE_WEATHER_BLOCK_TMIN_C = -22.0  # too cold/stormy to fly below this

# Spoilage: perishable SKUs lose stock to spoilage. Non-perishables
# (kerosene, ammunition) effectively don't. Modeled as a daily fractional
# loss for SKUs whose shelf life is short, plus a hard expiry sweep.
SPOILAGE_DAILY_FRACTION_PERISHABLE = 0.04   # ~4%/day loss for very short shelf-life items
SPOILAGE_SHELF_LIFE_PERISHABLE_CUTOFF = 30  # SKUs at/below this are "perishable"

# Opening-balance policy: warm-up year. We generate a full extra year
# (2021) of weather/disruption/consumption/stock dynamics, then DISCARD
# it — so Jan 1 2022 opens at whatever level the sawtooth actually
# produced mid-winter, with no hand-seeded artifact.
WARMUP_YEAR = 2021
WARMUP_START_DATE = date(2021, 1, 1)
# At the very start of the warm-up year itself, posts are seeded near a
# full post-AWS level. The warm-up year then runs one complete AWS +
# drawdown cycle, so by the time it is discarded the series is at a
# genuine steady state and Jan 1 2022 inherits a realistic — not
# hand-tuned — opening balance. A richer seed here only means the
# *discarded* year starts clean; it does not touch the real horizon.
WARMUP_SEED_COVERAGE_FRACTION = 0.90

# Stockout definition: a (post, SKU, day) is in stockout if closing
# stock hits zero AND there was unmet consumption demand that day.
# "Rationing" is the softer state: stock positive but below the
# tier-specific critical threshold (the same thresholds the masterplan's
# Component 5 risk evaluator uses).
STOCKOUT_RATIONING_THRESHOLD_DAYS = {1: 14, 2: 7, 3: 3}  # days-of-cover

# ---------------------------------------------------------------------------
# Provenance metadata
# ---------------------------------------------------------------------------
PROVENANCE = {
    "config_version": "stage2_v1.1",
    "generated_at": "2026-05-14",
    "anchors": {
        "weather": ["IMD Leh (1901-2000 study)", "Wikipedia Dras", "Weather-Atlas Drass+Leh"],
        "passes": ["BRO PIB 1809806 (Zoji La 2022)", "Tribune Mar 2026 BRO record",
                   "Wikipedia Khardung La/Chang La", "Vargis Khan Ladakh winter roads"],
        "consumption": ["CAG Report 2017-18 Siachen/Ladakh",
                        "The Tribune 'Providing logistics in Ladakh' (Jan 2025)",
                        "Swarajyamag Oct 2020 Army winter prep"],
        "stock_dynamics": ["The Tribune 'Providing logistics in Ladakh' (Jan 2025) — "
                           "AWS road-open-period bulk induction doctrine",
                           "Swarajyamag Oct 2020 — underground fuel dumps, "
                           "pre-positioned winter-grade kerosene",
                           "CAG Report 2017-18 — shortfalls as audit-flagged "
                           "exceptions, not steady state"],
        "vehicles": ["Tata/Ashok Leyland mil-spec sheets",
                     "Swarajyamag 6000-trucks figure",
                     "IDRW Stryker high-altitude trial failure (Mar 2025)"],
        "orbat": ["Wikipedia XIV Corps", "SPS Land Forces 'Defending Eastern Ladakh' (Mar 2025)"],
    },
    "synthetic_arbitrary_flags": [
        "Tangtse anchor station (extrapolated from Leh + lapse rate)",
        "Tsaka La closure priors (regional-pattern inferred)",
        "Marsimik La closure priors (elevation-scaled inference)",
        "Vehicle Weibull shape/scale parameters (inferred from CAG deficiency patterns, no direct survival data)",
        "AWS coverage targets in days-of-consumption (no public per-post stocking figures; "
        "calibrated so ~85-90% of post-SKUs enter winter adequately provisioned)",
        "AWS attainment Beta distribution (shape inferred from CAG 'exception not norm' framing)",
        "Routine convoy latency and refill thresholds (operationally plausible, no public source)",
        "Spoilage daily fractions for perishables (order-of-magnitude estimate)",
    ],
}
