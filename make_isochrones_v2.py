"""
Convert anam_rays.json (from fetch_anam_isochrones.py) into:
  data/isochrones/transit_anam.geojson    ← 4 features (shared across all buildings):
                                              [0] huge "80+ min" background polygon
                                              [1] 70-min contour from 안암역 (= 80 total)
                                              [2] 50-min contour                (= 60 total)
                                              [3] 30-min contour                (= 40 total)

The walking circles for the ≤20 min zone are drawn by the JS directly (no GeoJSON).

If no ray data exists, this script falls back to APPROXIMATE circular contours so
the map shows something while you're collecting real data.

Usage:
    python make_isochrones_v2.py             # writes transit_anam.geojson
"""
import json, math, os

ANAM = {"lat": 37.5862, "lon": 127.0301}

# Contour distance (km) FALLBACKS — used only when no real ray data is available.
# Rough estimate: transit at ~25 km/h average → 10/30/50/70 min = ~4 / 12 / 20 / 28 km.
# We cap at the map's display zoom to keep polygons reasonable.
FALLBACK_RADII_KM = {10: 3.0, 30: 8.0, 50: 13.0, 70: 18.0}

# GeoJSON feature order: largest → smallest
#   [0] background polygon (everything in view), label "80+"
#   [1] 70-min contour      (everything ≤ 70 min)   label "60-80"
#   [2] 50-min contour                              label "40-60"
#   [3] 30-min contour                              label "20-40"
FEATURE_ORDER = [
    {"key": "background", "label": "80+"},
    {"key": "70",         "label": "60-80"},
    {"key": "50",         "label": "40-60"},
    {"key": "30",         "label": "20-40"},
]

M_PER_DEG_LAT = 111320.0
M_PER_DEG_LON = 111320.0 * math.cos(math.radians(ANAM["lat"]))


def offset(lat, lon, angle_rad, dist_km):
    dx = dist_km * 1000 * math.cos(angle_rad)
    dy = dist_km * 1000 * math.sin(angle_rad)
    return (lon + dx / M_PER_DEG_LON,
            lat + dy / M_PER_DEG_LAT)


def make_background_ring(half_km=25):
    """Return a big box around 안암역 in [lon, lat] GeoJSON order."""
    dlat = (half_km * 1000) / M_PER_DEG_LAT
    dlon = (half_km * 1000) / M_PER_DEG_LON
    lat0, lon0 = ANAM["lat"], ANAM["lon"]
    return [
        [round(lon0 - dlon, 6), round(lat0 - dlat, 6)],
        [round(lon0 + dlon, 6), round(lat0 - dlat, 6)],
        [round(lon0 + dlon, 6), round(lat0 + dlat, 6)],
        [round(lon0 - dlon, 6), round(lat0 + dlat, 6)],
        [round(lon0 - dlon, 6), round(lat0 - dlat, 6)],
    ]


def make_fallback_ring(radius_km, n_points=48):
    """Approximate circular ring as GeoJSON coords (lon, lat)."""
    ring = []
    for i in range(n_points):
        a = 2 * math.pi * i / n_points
        # add a touch of organic noise so it doesn't look perfectly circular
        wobble = 1.0 + 0.05 * math.sin(3 * a)
        ring.append(list(offset(ANAM["lat"], ANAM["lon"], a, radius_km * wobble)))
    ring.append(ring[0])
    return [[round(x, 6), round(y, 6)] for x, y in ring]


def make_real_ring(rays_data, level):
    """
    Build a closed ring from per-ray contour crossings.
    rays_data: dict {ray_idx: {angle_deg, crossings: {str(level): [lat, lon] or None}}}
    Returns ring in GeoJSON order [lon, lat] or None if too few crossings.
    """
    pts = []
    for ray_key in sorted(rays_data.keys(), key=int):
        r   = rays_data[ray_key]
        ll  = r["crossings"].get(str(level))
        if ll is None:
            continue
        pts.append((r["angle_deg"], ll[0], ll[1]))     # (angle, lat, lon)
    if len(pts) < 8:
        return None
    pts.sort(key=lambda p: p[0])
    ring = [[round(lon, 6), round(lat, 6)] for _, lat, lon in pts]
    ring.append(ring[0])
    return ring


def main():
    rays_path = "data/anam_rays.json"
    have_real = os.path.exists(rays_path)
    rays_data = {}

    if have_real:
        with open(rays_path, encoding="utf-8") as f:
            payload = json.load(f)
        rays_data = payload.get("rays", {})
        print(f"Loaded {len(rays_data)} rays from {rays_path}")
    else:
        print("No anam_rays.json found - using FALLBACK circular contours.")
        print("Run fetch_anam_isochrones.py to replace with real transit data.\n")

    features = []
    for meta in FEATURE_ORDER:
        if meta["key"] == "background":
            ring = make_background_ring(half_km=25)
        else:
            level = int(meta["key"])
            ring = None
            if have_real:
                ring = make_real_ring(rays_data, level)
            if ring is None:
                ring = make_fallback_ring(FALLBACK_RADII_KM[level])

        features.append({
            "type": "Feature",
            "properties": {"label": meta["label"], "source": meta["key"]},
            "geometry": {"type": "Polygon", "coordinates": [ring]},
        })

    os.makedirs("data/isochrones", exist_ok=True)
    out_path = "data/isochrones/transit_anam.geojson"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "features": features}, f)

    print(f"Wrote {out_path} with {len(features)} features.")
    print("  (Walking circles for the <=20-min zone are drawn by the JS at runtime.)")


if __name__ == "__main__":
    main()
