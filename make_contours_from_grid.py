"""
Build data/isochrones/transit_anam.geojson from the cached samples.

Reads:
  data/anam_query_cache.json         — (lat, lon) -> transit minutes from 안암역
  data/isochrones/walking_20min.geojson — user's hand-drawn 20-min walking polygon

Outputs:
  data/isochrones/transit_anam.geojson — FeatureCollection with 3 features:
    - 60-min total commute (= 50-min transit + 10 walk)
    - 40-min total commute (= 30-min transit + 10 walk)
    - 20-min total commute (= user's manual walking polygon)

PIPELINE:
  1. Load all transit samples from cache  →  scattered (lon, lat, minutes)
  2. Build a regular evaluation grid covering all samples (+ small margin)
  3. Interpolate f(lon, lat) ≈ minutes using scipy.griddata (cubic where
     possible, linear elsewhere). Cubic is smooth; linear is the safe
     fallback in regions outside the convex hull of samples.
  4. Use matplotlib's contour finder to extract the level sets at 30 and 50
     minutes. Pick the LARGEST connected polygon for each level (outermost
     ring of the isochrone — smaller closed loops are usually interpolation
     artefacts from outlier samples).
  5. Combine with the manual 20-min polygon, emit GeoJSON.

Buggy outlier handling:
  Outlier filtering is OPTIONAL (--filter-outliers). Default OFF since the
  user prefers to inspect/remove bad samples manually before re-running.
  When enabled, drops points whose minutes/distance ratio looks impossible
  (e.g. 3 min reported at a 12 km point).

Usage:
    pip install numpy scipy matplotlib
    python make_contours_from_grid.py
    python make_contours_from_grid.py --grid 300 --method linear
"""
import argparse, json, math, os
import numpy as np
from scipy.interpolate import griddata
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# ── Constants ─────────────────────────────────────────────────────────────────
ANAM = {"lat": 37.5862, "lon": 127.0301}
M_PER_DEG_LAT = 111320.0
M_PER_DEG_LON = 111320.0 * math.cos(math.radians(ANAM["lat"]))

CACHE_PATH        = "data/anam_query_cache.json"
WALKING_20_PATH   = "data/isochrones/walking_20min.geojson"
OUTPUT_PATH       = "data/isochrones/transit_anam.geojson"

# total_commute_min -> transit_min_from_anam (or None to use external file)
LEVEL_SPECS = [
    {"total": 60, "transit": 50, "source_file": None},
    {"total": 40, "transit": 30, "source_file": None},
    {"total": 20, "transit": None, "source_file": WALKING_20_PATH},
]


def banner(t):
    bar = "═" * 64
    print(f"\n{bar}\n  {t}\n{bar}")


# ── Sample loading & filtering ────────────────────────────────────────────────

def load_transit_samples(cache_path, filter_outliers=False):
    """Returns numpy arrays (pts [N,2] in (lon,lat), vals [N] in minutes)."""
    with open(cache_path, encoding="utf-8") as f:
        cache = json.load(f)

    samples = []
    for key, mins in cache.items():
        if not isinstance(key, str) or not key.startswith("transit|"):
            continue
        if mins is None or not isinstance(mins, (int, float)):
            continue
        try:
            coords = key.split("|", 1)[1]
            lat_s, lon_s = coords.split(",")
            samples.append((float(lon_s), float(lat_s), float(mins)))
        except (ValueError, IndexError):
            continue

    if not samples:
        raise SystemExit(f"No transit samples in {cache_path}.")

    pts  = np.array([(lon, lat) for lon, lat, _ in samples])
    vals = np.array([m for _, _, m in samples])

    if filter_outliers:
        # Distance from origin in km
        d_lon_m = (pts[:, 0] - ANAM["lon"]) * M_PER_DEG_LON
        d_lat_m = (pts[:, 1] - ANAM["lat"]) * M_PER_DEG_LAT
        dist_km = np.hypot(d_lat_m, d_lon_m) / 1000.0
        # Reject if reported minutes are implausibly small for the distance
        # (transit can do ~1 km / min at best; flag <0.4 km/min implied speed)
        speed = np.where(vals > 0, dist_km / (vals / 60.0), 0)  # km/h
        bad   = (vals < 4) & (dist_km > 3) | (speed > 80)
        n_bad = int(bad.sum())
        if n_bad:
            print(f"  filtered {n_bad} outlier sample(s) (impossible distance/time)")
            pts, vals = pts[~bad], vals[~bad]

    return pts, vals


# ── Contour extraction ────────────────────────────────────────────────────────

def extract_largest_polygon(grid_lon, grid_lat, grid_time, level):
    """
    Use matplotlib.contour to extract level set at `level`. Return the LARGEST
    closed polygon (by point count) as a list of [lon, lat] coordinates.
    Returns None if no contour found.
    """
    fig, ax = plt.subplots()
    cs = ax.contour(grid_lon, grid_lat, grid_time, levels=[level])
    plt.close(fig)

    if not cs.allsegs or not cs.allsegs[0]:
        return None

    segments = cs.allsegs[0]
    # Choose the longest segment (typically the outermost / dominant contour)
    longest = max(segments, key=len)
    if len(longest) < 6:
        return None

    ring = longest.tolist()
    if ring[0] != ring[-1]:
        ring.append(ring[0])
    # Round coordinates for cleaner GeoJSON
    return [[round(x, 6), round(y, 6)] for x, y in ring]


def load_manual_polygon(path):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    features = data.get("features", [])
    if not features:
        return None
    coords = features[0].get("geometry", {}).get("coordinates")
    if not coords:
        return None
    ring = list(coords[0])
    if ring[0] != ring[-1]:
        ring.append(ring[0])
    return ring


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--grid", type=int, default=300,
                        help="Grid resolution per side (default 300 = 90k cells)")
    parser.add_argument("--method", choices=["linear", "cubic"], default="cubic",
                        help="scipy.griddata interpolation method")
    parser.add_argument("--filter-outliers", action="store_true",
                        help="Drop samples with implausible time-vs-distance ratios")
    parser.add_argument("--margin", type=float, default=0.015,
                        help="Lat/lon margin (degrees) around sample bbox")
    args = parser.parse_args()

    banner("Grid-Based Contour Extractor  (origin: 안암역)")

    # ── 1. Load samples ──
    pts, vals = load_transit_samples(CACHE_PATH, args.filter_outliers)
    print(f"  Loaded {len(pts)} transit samples from {CACHE_PATH}")
    print(f"  Time range : {vals.min():.1f} – {vals.max():.1f} min")
    print(f"  Lon range  : {pts[:,0].min():.4f} – {pts[:,0].max():.4f}")
    print(f"  Lat range  : {pts[:,1].min():.4f} – {pts[:,1].max():.4f}")

    # ── 2. Build evaluation grid ──
    lon_min, lon_max = pts[:, 0].min() - args.margin, pts[:, 0].max() + args.margin
    lat_min, lat_max = pts[:, 1].min() - args.margin, pts[:, 1].max() + args.margin

    grid_lon, grid_lat = np.meshgrid(
        np.linspace(lon_min, lon_max, args.grid),
        np.linspace(lat_min, lat_max, args.grid),
    )

    # ── 3. Interpolate ──
    print(f"\n  Interpolating ({args.method}, grid={args.grid}×{args.grid}) ...")
    grid_time = griddata(pts, vals, (grid_lon, grid_lat), method=args.method)

    # Fill NaNs (cubic leaves holes outside convex hull) with linear fallback
    if args.method == "cubic":
        nan_mask = np.isnan(grid_time)
        if nan_mask.any():
            linear_fill = griddata(pts, vals, (grid_lon, grid_lat), method="linear")
            grid_time = np.where(nan_mask, linear_fill, grid_time)

    n_valid = int((~np.isnan(grid_time)).sum())
    print(f"  Valid grid cells: {n_valid}/{grid_time.size}")

    # ── 4. Extract contours, combine with manual 20-min ──
    banner("Extracting contour polygons")
    features = []

    for spec in LEVEL_SPECS:
        total = spec["total"]
        if spec["source_file"] is not None:
            ring = load_manual_polygon(spec["source_file"])
            if ring is None:
                print(f"  {total:>2} min  :  ✗ failed to load {spec['source_file']}")
                continue
            features.append({
                "type": "Feature",
                "properties": {"total_commute_min": total, "source": "user-manual"},
                "geometry": {"type": "Polygon", "coordinates": [ring]},
            })
            print(f"  {total:>2} min  :  ✓ user-manual polygon ({len(ring)} vertices)")
            continue

        transit = spec["transit"]
        ring = extract_largest_polygon(grid_lon, grid_lat, grid_time, transit)
        if ring is None:
            print(f"  {total:>2} min  :  ✗ no contour found at {transit} min")
            continue
        features.append({
            "type": "Feature",
            "properties": {
                "total_commute_min": total,
                "transit_min_from_anam": transit,
                "source": f"grid-{args.method}",
            },
            "geometry": {"type": "Polygon", "coordinates": [ring]},
        })
        print(f"  {total:>2} min  :  ✓ extracted ({transit}-min transit) "
              f"— {len(ring)} vertices")

    # ── 5. Save ──
    os.makedirs("data/isochrones", exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "features": features}, f)
    print(f"\n  Wrote {OUTPUT_PATH} with {len(features)} features.")


if __name__ == "__main__":
    main()
