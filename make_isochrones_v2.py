"""
Convert anam_rays.json (from fetch_anam_isochrones.py) → transit_anam.geojson.

Output schema: each feature has properties.total_commute_min so the JS can
render contours by total commute time (transit time from 안암역 + 10 min walk).

  30-min transit from 안암역  →  40-min total commute
  50-min transit              →  60-min total commute
  70-min transit              →  80-min total commute

If no ray data exists, falls back to approximate circular contours so the map
shows something while you're collecting real data.

Usage:
    python make_isochrones_v2.py
"""
import json, math, os

ANAM = {"lat": 37.5862, "lon": 127.0301}

# Mapping: transit-time-from-안암역 → total commute time (transit + 10 walk)
LEVEL_TO_TOTAL = {30: 40, 50: 60, 70: 80}

# Fallback radii (km) when no ray data — rough transit-speed estimate.
FALLBACK_RADII_KM = {30: 7.0, 50: 13.0, 70: 19.0}

M_PER_DEG_LAT = 111320.0
M_PER_DEG_LON = 111320.0 * math.cos(math.radians(ANAM["lat"]))


def offset(angle_rad, dist_km):
    """Return (lon, lat) in GeoJSON order."""
    dx = dist_km * 1000 * math.cos(angle_rad)
    dy = dist_km * 1000 * math.sin(angle_rad)
    return (ANAM["lon"] + dx / M_PER_DEG_LON,
            ANAM["lat"] + dy / M_PER_DEG_LAT)


def make_fallback_ring(radius_km, n_points=72):
    """Approximate circular ring with slight organic noise."""
    ring = []
    for i in range(n_points):
        a = 2 * math.pi * i / n_points
        wobble = 1.0 + 0.04 * math.sin(3 * a) + 0.025 * math.sin(7 * a + 1)
        ring.append([round(c, 6) for c in offset(a, radius_km * wobble)])
    ring.append(ring[0])
    return ring


def make_ring_from_traced(points):
    """
    points: list of [lat, lon] from fetcher (already ordered CCW from angle 0).
    Returns GeoJSON ring [[lon, lat], ..., closed].
    """
    ring = [[round(lon, 6), round(lat, 6)] for lat, lon in points]
    ring.append(ring[0])
    return ring


def main():
    rays_path = "data/anam_rays.json"
    have_real = os.path.exists(rays_path)
    contours  = {}

    if have_real:
        with open(rays_path, encoding="utf-8") as f:
            payload = json.load(f)
        contours = payload.get("contours", {})
        print(f"Loaded contours from {rays_path}: {list(contours.keys())} min")
    else:
        print("No anam_rays.json found - using FALLBACK circular contours.")
        print("Run fetch_anam_isochrones.py to replace with real transit data.\n")

    features = []
    # Order largest-first for the JS (rendering order doesn't matter with no fill,
    # but keeps the data legible)
    for level in sorted(LEVEL_TO_TOTAL.keys(), reverse=True):
        traced = contours.get(str(level))
        if traced and len(traced) >= 8:
            ring = make_ring_from_traced(traced)
            source = "tmap-traced"
        else:
            ring = make_fallback_ring(FALLBACK_RADII_KM[level])
            source = "fallback-circle"

        features.append({
            "type": "Feature",
            "properties": {
                "transit_min_from_anam": level,
                "total_commute_min":     LEVEL_TO_TOTAL[level],
                "source":                source,
            },
            "geometry": {"type": "Polygon", "coordinates": [ring]},
        })

    os.makedirs("data/isochrones", exist_ok=True)
    out_path = "data/isochrones/transit_anam.geojson"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "features": features}, f)

    print(f"Wrote {out_path} with {len(features)} features.")
    for feat in features:
        p = feat["properties"]
        print(f"  total {p['total_commute_min']:>2} min  "
              f"({p['transit_min_from_anam']} min transit + 10 walk)  "
              f"[{p['source']}]")


if __name__ == "__main__":
    main()
