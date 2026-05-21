"""
Build data/isochrones/transit_anam.geojson from data/anam_rays.json.

Output has FOUR features (one per total commute time):
   80 min total = 70 min transit + 10 walk
   60 min total = 50 min transit + 10 walk
   40 min total = 30 min transit + 10 walk
   20 min total = 20 min walking (algorithm) OR user's manual polygon

Order largest-first. Sources:
  - If anam_rays.json has the level as a {"radii":..., "success":...} dict
    (new format) OR as a list of [lat,lon] points (old format), use it.
  - For 20-min specifically: if the algorithm produced data, prefer it;
    otherwise fall back to data/isochrones/walking_20min.geojson;
    otherwise use a circular fallback.
  - For transit levels missing from anam_rays.json, fall back to circles.

Usage:
    python make_isochrones_v2.py
"""
import json, math, os

ANAM = {"lat": 37.5862, "lon": 127.0301}

# total_commute_min  ->  (source key in anam_rays.json, default radius km)
LEVEL_MAPPING = [
    {"total": 80, "rays_key": "70", "default_km": 19.0},
    {"total": 60, "rays_key": "50", "default_km": 13.0},
    {"total": 40, "rays_key": "30", "default_km": 7.0},
    {"total": 20, "rays_key": "20", "default_km": 1.5},
]

M_PER_DEG_LAT = 111320.0
M_PER_DEG_LON = 111320.0 * math.cos(math.radians(ANAM["lat"]))


def offset_lonlat(angle_rad, dist_km):
    dx = dist_km * 1000 * math.cos(angle_rad)
    dy = dist_km * 1000 * math.sin(angle_rad)
    return (ANAM["lon"] + dx / M_PER_DEG_LON,
            ANAM["lat"] + dy / M_PER_DEG_LAT)


def make_fallback_ring(radius_km, n_points=72):
    ring = []
    for i in range(n_points):
        a = 2 * math.pi * i / n_points
        wobble = 1.0 + 0.04 * math.sin(3 * a) + 0.025 * math.sin(7 * a + 1)
        ring.append([round(c, 6) for c in offset_lonlat(a, radius_km * wobble)])
    ring.append(ring[0])
    return ring


def ring_from_radii(radii):
    """Convert list of km radii (CCW from angle 0) -> closed GeoJSON ring."""
    n = len(radii)
    ring = []
    for step, r in enumerate(radii):
        a = 2 * math.pi * step / n
        ring.append([round(c, 6) for c in offset_lonlat(a, r)])
    ring.append(ring[0])
    return ring


def ring_from_points(points):
    """Old format: list of [lat, lon]. Returns closed [lon, lat] ring."""
    ring = [[round(lon, 6), round(lat, 6)] for lat, lon in points]
    if ring:
        ring.append(ring[0])
    return ring


def get_contour_ring(rays_payload, key):
    """Look up a contour by key in the loaded rays payload. Returns ring or None."""
    contours = rays_payload.get("contours", {}) if rays_payload else {}
    entry = contours.get(key)
    if entry is None:
        return None
    if isinstance(entry, dict) and "radii" in entry:
        # New format
        radii = entry["radii"]
        if len(radii) < 8:
            return None
        return ring_from_radii(radii)
    if isinstance(entry, list):
        if len(entry) < 8:
            return None
        return ring_from_points(entry)
    return None


def load_user_walking_20():
    """Read user-provided 20-min walking polygon (GeoJSON FeatureCollection)."""
    path = "data/isochrones/walking_20min.geojson"
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        features = data.get("features", [])
        if not features:
            return None
        coords = features[0].get("geometry", {}).get("coordinates")
        if not coords:
            return None
        ring = coords[0]
        if ring[0] != ring[-1]:
            ring = list(ring) + [ring[0]]
        return ring
    except Exception:
        return None


def main():
    rays_path = "data/anam_rays.json"
    rays_payload = None
    if os.path.exists(rays_path):
        with open(rays_path, encoding="utf-8") as f:
            rays_payload = json.load(f)
        contours = rays_payload.get("contours", {})
        print(f"Loaded {rays_path}: contours for {list(contours.keys())} min")
    else:
        print("No anam_rays.json found - using fallback / user-provided data.\n")

    features = []
    for spec in LEVEL_MAPPING:
        total      = spec["total"]
        rays_key   = spec["rays_key"]
        default_km = spec["default_km"]

        ring = get_contour_ring(rays_payload, rays_key)
        source = "algorithm" if ring else None

        if ring is None and total == 20:
            ring = load_user_walking_20()
            if ring:
                source = "user-manual"

        if ring is None:
            ring = make_fallback_ring(default_km)
            source = "fallback-circle"

        features.append({
            "type": "Feature",
            "properties": {
                "total_commute_min": total,
                "rays_key":          rays_key,
                "source":            source,
            },
            "geometry": {"type": "Polygon", "coordinates": [ring]},
        })

    os.makedirs("data/isochrones", exist_ok=True)
    out_path = "data/isochrones/transit_anam.geojson"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "features": features}, f)

    print(f"\nWrote {out_path} with {len(features)} features:")
    for feat in features:
        p = feat["properties"]
        print(f"  total {p['total_commute_min']:>2} min   [{p['source']}]")


if __name__ == "__main__":
    main()
