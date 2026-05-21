"""
Step 2: Convert travel-time JSON files into isochrone GeoJSON polygons.
Reads data/times_{building_id}.json, interpolates a smooth time surface,
extracts contour lines at [20, 40, 60, 80] minutes, and writes
data/isochrones/{building_id}.geojson ready for the Kakao Maps layer.

Run after fetch_times.py has completed for the buildings you want:
    python make_isochrones.py
    python make_isochrones.py --buildings engineering humanities
"""
import argparse, json, math, os
import numpy as np
from scipy.interpolate import griddata
from scipy.ndimage import gaussian_filter
import matplotlib
matplotlib.use("Agg")           # no GUI needed
import matplotlib.pyplot as plt

BUILDINGS = ["engineering", "humanities", "business", "law", "education", "medicine"]

CENTER_LAT = 37.5895
CENTER_LON = 127.0317
RADIUS_KM  = 15

M_PER_DEG_LAT = 111320.0
M_PER_DEG_LON = 111320.0 * math.cos(math.radians(CENTER_LAT))

# Contour boundaries in minutes. Produces 5 visual zones:
#   ≤20 | 20-40 | 40-60 | 60-80 | 80+
BOUNDARIES = [20, 40, 60, 80]

# GeoJSON feature order: largest zone first (rendered bottom → top in Kakao Maps).
# features[0] = 80-min boundary polygon  →  ISO_LEVELS[0] color (red)  visible as 60-80 min ring
# features[1] = 60-min boundary polygon  →  ISO_LEVELS[1] color (orange)
# features[2] = 40-min boundary polygon  →  ISO_LEVELS[2] color (yellow)
# features[3] = 20-min boundary polygon  →  ISO_LEVELS[3] color (green)
# Background beyond features[0] = 80+ min zone (uncoloured map background)
FEATURE_META = [
    {"value": 4800, "label": "80"},
    {"value": 3600, "label": "60"},
    {"value": 2400, "label": "40"},
    {"value":  600, "label": "20"},
]

GRID_RES = 400   # interpolation grid resolution (higher = smoother, slower)
SMOOTH   = 3     # gaussian smoothing sigma (in grid cells)

def load_points(building_id):
    path = f"data/times_{building_id}.json"
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    lats, lons, times = [], [], []
    for key, val in raw.items():
        if val is None:
            continue
        la, lo = map(float, key.split(","))
        lats.append(la)
        lons.append(lo)
        times.append(val / 60.0)   # seconds → minutes
    return np.array(lats), np.array(lons), np.array(times)

def build_grid(lats, lons, times):
    lat_min = CENTER_LAT - (RADIUS_KM * 1000) / M_PER_DEG_LAT
    lat_max = CENTER_LAT + (RADIUS_KM * 1000) / M_PER_DEG_LAT
    lon_min = CENTER_LON - (RADIUS_KM * 1000) / M_PER_DEG_LON
    lon_max = CENTER_LON + (RADIUS_KM * 1000) / M_PER_DEG_LON

    grid_lats = np.linspace(lat_min, lat_max, GRID_RES)
    grid_lons = np.linspace(lon_min, lon_max, GRID_RES)
    GL, GX = np.meshgrid(grid_lats, grid_lons, indexing="ij")

    Z = griddata(
        np.column_stack([lats, lons]),
        times,
        (GL, GX),
        method="linear"
    )
    # Fill NaN edges with a high value (unreachable / very far)
    Z = np.where(np.isnan(Z), 200.0, Z)
    Z = gaussian_filter(Z, sigma=SMOOTH)
    return grid_lats, grid_lons, Z

def extract_contour(grid_lats, grid_lons, Z, level_minutes):
    """Return a list of closed rings (each ring = [[lon,lat],...]) at the given level."""
    fig, ax = plt.subplots(figsize=(6, 6))
    cs = ax.contour(grid_lons, grid_lats, Z, levels=[level_minutes])
    rings = []
    for collection in cs.collections:
        for path in collection.get_paths():
            verts = path.vertices          # shape (N, 2): columns = [lon, lat]
            if len(verts) < 4:
                continue
            coords = [[round(float(v[0]), 6), round(float(v[1]), 6)] for v in verts]
            coords.append(coords[0])       # close the ring
            rings.append(coords)
    plt.close(fig)
    return rings

def largest_ring(rings):
    """Pick the ring with the largest bounding area (main island, ignore tiny fragments)."""
    if not rings:
        return None
    def bbox_area(ring):
        lons = [c[0] for c in ring]
        lats = [c[1] for c in ring]
        return (max(lons) - min(lons)) * (max(lats) - min(lats))
    return max(rings, key=bbox_area)

def process_building(building_id):
    data = load_points(building_id)
    if data is None:
        print(f"  [{building_id}] No data file found — skipping")
        return False

    lats, lons, times = data
    print(f"  [{building_id}] {len(lats)} points, "
          f"time range {times.min():.0f}–{times.max():.0f} min")

    grid_lats, grid_lons, Z = build_grid(lats, lons, times)

    features = []
    for meta, boundary_min in zip(FEATURE_META, BOUNDARIES):
        rings = extract_contour(grid_lats, grid_lons, Z, boundary_min)
        ring  = largest_ring(rings)
        if ring is None:
            print(f"    Warning: no contour found at {boundary_min} min — using approximate circle")
            # Fallback: draw a circle at walking speed for this time
            walk_m = boundary_min * 75       # ~75m/min average including transit
            ring = _circle_ring(CENTER_LAT, CENTER_LON, walk_m, 32)

        features.append({
            "type": "Feature",
            "properties": {"value": meta["value"], "label": meta["label"]},
            "geometry": {"type": "Polygon", "coordinates": [ring]}
        })

    out_path = f"data/isochrones/{building_id}.geojson"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "features": features}, f)
    print(f"    → wrote {out_path} ({len(features)} zones)")
    return True

def _circle_ring(lat, lon, radius_m, n=32):
    coords = []
    for i in range(n):
        angle = 2 * math.pi * i / n
        dlon = (radius_m * math.cos(angle)) / M_PER_DEG_LON
        dlat = (radius_m * math.sin(angle)) / M_PER_DEG_LAT
        coords.append([round(lon + dlon, 6), round(lat + dlat, 6)])
    coords.append(coords[0])
    return coords

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--buildings", nargs="+", default=BUILDINGS,
                        help="Which buildings to process (default: all with data files)")
    args = parser.parse_args()

    print("Building isochrone GeoJSON files...\n")
    ok = 0
    for b in args.buildings:
        if process_building(b):
            ok += 1
    print(f"\nDone — {ok}/{len(args.buildings)} buildings updated.")

if __name__ == "__main__":
    main()
