"""
Step 1: Query Tmap Transit API for travel times from a grid of points to a campus building.
Saves results to data/times_{building_id}.json (checkpointed — safe to re-run).

Usage:
    python fetch_times.py --key YOUR_TMAP_KEY --building engineering
    python fetch_times.py --key YOUR_TMAP_KEY --building humanities
    ... (run once per building)

Buildings: engineering, humanities, business, law, education, medicine
"""
import argparse, json, math, os, time, requests

# ── Campus building destinations ─────────────────────────────────────────────
BUILDINGS = {
    "engineering": {"lat": 37.5893, "lon": 127.0334, "name": "College of Engineering"},
    "humanities":  {"lat": 37.5903, "lon": 127.0287, "name": "College of Liberal Arts"},
    "business":    {"lat": 37.5877, "lon": 127.0283, "name": "Business School"},
    "law":         {"lat": 37.5883, "lon": 127.0272, "name": "School of Law"},
    "education":   {"lat": 37.5912, "lon": 127.0268, "name": "College of Education"},
    "medicine":    {"lat": 37.5944, "lon": 127.0365, "name": "College of Medicine"},
}

# ── Grid settings ─────────────────────────────────────────────────────────────
CENTER_LAT  = 37.5895   # KU campus center
CENTER_LON  = 127.0317
RADIUS_KM   = 15        # max distance to sample (covers ~80 min transit zone)
STEP_KM     = 0.7       # grid spacing in km (reduce for higher density, more API calls)

M_PER_DEG_LAT = 111320.0
M_PER_DEG_LON = 111320.0 * math.cos(math.radians(CENTER_LAT))

# Weekday 9 AM departure — gives typical morning commute times
SEARCH_TIME = "202506231900"   # YYYYMMDDHHMI (adjust to a future weekday)

def generate_grid():
    dlat = (STEP_KM * 1000) / M_PER_DEG_LAT
    dlon = (STEP_KM * 1000) / M_PER_DEG_LON
    r_lat = (RADIUS_KM * 1000) / M_PER_DEG_LAT
    r_lon = (RADIUS_KM * 1000) / M_PER_DEG_LON

    points = []
    lat = CENTER_LAT - r_lat
    while lat <= CENTER_LAT + r_lat + dlat * 0.01:
        lon = CENTER_LON - r_lon
        while lon <= CENTER_LON + r_lon + dlon * 0.01:
            dist_km = math.sqrt(
                ((lat - CENTER_LAT) * M_PER_DEG_LAT / 1000) ** 2 +
                ((lon - CENTER_LON) * M_PER_DEG_LON / 1000) ** 2
            )
            if dist_km <= RADIUS_KM:
                points.append((round(lat, 6), round(lon, 6)))
            lon += dlon
        lat += dlat
    return points

def query_tmap(api_key, origin_lat, origin_lon, dest_lat, dest_lon):
    url = "https://apis.openapi.sk.com/transit/routes"
    headers = {"appKey": api_key, "Content-Type": "application/json"}
    body = {
        "startX":     str(origin_lon),
        "startY":     str(origin_lat),
        "endX":       str(dest_lon),
        "endY":       str(dest_lat),
        "count":      1,
        "searchDttm": SEARCH_TIME,
    }
    resp = requests.post(url, headers=headers, json=body, timeout=15)
    if resp.status_code != 200:
        return None
    try:
        itineraries = resp.json()["metaData"]["plan"]["itineraries"]
        if not itineraries:
            return None
        return itineraries[0]["totalTime"]   # seconds
    except (KeyError, IndexError, ValueError):
        return None

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--key",      required=True, help="Tmap API key")
    parser.add_argument("--building", required=True, choices=BUILDINGS.keys())
    parser.add_argument("--delay",    type=float, default=1.1,
                        help="Seconds between API calls (default 1.1)")
    args = parser.parse_args()

    b = BUILDINGS[args.building]
    out_path = f"data/times_{args.building}.json"

    # Load existing checkpoint
    results = {}
    if os.path.exists(out_path):
        with open(out_path, encoding="utf-8") as f:
            results = json.load(f)
        print(f"Loaded {len(results)} cached results from {out_path}")

    grid = generate_grid()
    total   = len(grid)
    pending = [(la, lo) for la, lo in grid if f"{la},{lo}" not in results]

    print(f"Building : {b['name']}")
    print(f"Grid pts : {total}  |  Pending: {len(pending)}  |  Delay: {args.delay}s")
    print(f"Est. time: {len(pending) * args.delay / 60:.1f} min")
    print()

    for i, (lat, lon) in enumerate(pending, 1):
        key = f"{lat},{lon}"
        secs = query_tmap(args.key, lat, lon, b["lat"], b["lon"])
        results[key] = secs   # None means no route found
        if i % 50 == 0 or i == len(pending):
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(results, f)
            done = sum(1 for v in results.values() if v is not None)
            print(f"  [{i}/{len(pending)}] saved — {done} valid routes")
        time.sleep(args.delay)

    print(f"\nDone. Results saved to {out_path}")

if __name__ == "__main__":
    main()
