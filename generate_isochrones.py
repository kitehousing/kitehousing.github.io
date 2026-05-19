"""
Generates approximate commute-time isochrone polygons for KU campus buildings.
5 levels: ≤20 / 20-40 / 40-60 / 60-80 / 80+ min.
Features are ordered largest→smallest so they render correctly (bottom→top).
Replace these GeoJSON files with accurate transit-time polygons when available.
"""
import json, math, random

BUILDINGS = {
    "engineering": {"lon": 127.0334, "lat": 37.5893},
    "humanities":  {"lon": 127.0287, "lat": 37.5903},
    "business":    {"lon": 127.0283, "lat": 37.5877},
    "law":         {"lon": 127.0272, "lat": 37.5883},
    "education":   {"lon": 127.0268, "lat": 37.5912},
    "medicine":    {"lon": 127.0365, "lat": 37.5944},
}

# Approximate radii (metres) for each commute level.
# Walking ~75m/min; outer zones account for subway reach.
CONTOURS = [
    {"label": "80+",   "value": 4800, "radius_m": 9500},  # rendered first (bottom)
    {"label": "60-80", "value": 3600, "radius_m": 7000},
    {"label": "40-60", "value": 2400, "radius_m": 5000},
    {"label": "20-40", "value": 1200, "radius_m": 3000},
    {"label": "0-20",  "value":  600, "radius_m": 1500},  # rendered last (top)
]

M_PER_DEG_LAT = 111320
M_PER_DEG_LON = 111320 * math.cos(math.radians(37.59))
N_POINTS = 36

def make_polygon(lon, lat, radius_m, seed):
    rng = random.Random(seed)
    coords = []
    for i in range(N_POINTS):
        angle = 2 * math.pi * i / N_POINTS
        variation = (1.0
                     + 0.18 * math.sin(3 * angle + rng.uniform(0, 2))
                     + 0.10 * math.sin(5 * angle + rng.uniform(0, 3))
                     + 0.06 * rng.gauss(0, 1))
        variation = max(0.70, min(1.30, variation))
        r = radius_m * variation
        dlat = (r * math.sin(angle)) / M_PER_DEG_LAT
        dlon = (r * math.cos(angle)) / M_PER_DEG_LON
        coords.append([round(lon + dlon, 6), round(lat + dlat, 6)])
    coords.append(coords[0])
    return coords

for building_id, pos in BUILDINGS.items():
    features = []
    for i, c in enumerate(CONTOURS):
        coords = make_polygon(pos["lon"], pos["lat"], c["radius_m"],
                              seed=hash(building_id) + i * 997)
        features.append({
            "type": "Feature",
            "properties": {
                "value": c["value"],
                "label": c["label"]
            },
            "geometry": {
                "type": "Polygon",
                "coordinates": [coords]
            }
        })
    geojson = {"type": "FeatureCollection", "features": features}
    path = f"data/isochrones/{building_id}.geojson"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(geojson, f)
    print(f"  wrote {path}")

print("Done.")
