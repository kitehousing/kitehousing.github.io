"""
Smart radial isochrone fetcher for KU commute map.

Origin: 안암역 (Anam Station). Casts N rays at evenly-spaced angles, samples coarsely
then binary-searches each contour level along each ray. Results saved as JSON ray
data and turned into GeoJSON polygons by make_isochrones_v2.py.

Usage:
    python fetch_anam_isochrones.py --key YOUR_TMAP_KEY
    python fetch_anam_isochrones.py --key YOUR_TMAP_KEY --rays 72   # finer angular resolution

Approximate cost (default 36 rays, 4 contours):
    ~ 36 × (7 + 4×5) = ~975 API calls × 0.55원 = ~540원
"""
import argparse, json, math, os, time, requests

# ── Constants ─────────────────────────────────────────────────────────────────
ANAM_STATION = {"lat": 37.5862, "lon": 127.0301}

# Contour levels in MINUTES FROM 안암역. Adding +10 min walk to building gives
# 20 / 40 / 60 / 80 min total commute. (10 min is also fetched for diagnostics.)
CONTOUR_LEVELS = [10, 30, 50, 70]

DEFAULT_NUM_RAYS  = 36           # 10° spacing
MAX_DIST_KM       = 15           # outer limit of the search
COARSE_SAMPLES_KM = [1.0, 2.5, 4.0, 6.0, 9.0, 12.0, 15.0]
BINARY_ITERATIONS = 5            # ~150m precision at 15km / 2^5
SEARCH_DATETIME   = "202506231900"  # weekday morning departure (YYYYMMDDHHMI)

M_PER_DEG_LAT = 111320.0
M_PER_DEG_LON = 111320.0 * math.cos(math.radians(ANAM_STATION["lat"]))

# ── Tmap "대중교통 요약정보" endpoint (summary only — 0.55 KRW / call) ──────────
TMAP_URL = "https://apis.openapi.sk.com/transit/routes/sub"


def offset_point(lat, lon, angle_rad, distance_km):
    """Move (lat, lon) by distance_km in direction angle_rad (0 = east, π/2 = north)."""
    dx_m = distance_km * 1000 * math.cos(angle_rad)
    dy_m = distance_km * 1000 * math.sin(angle_rad)
    return (lat + dy_m / M_PER_DEG_LAT, lon + dx_m / M_PER_DEG_LON)


def query_tmap_minutes(api_key, origin_lat, origin_lon):
    """Return transit time in MINUTES from (origin_lat, origin_lon) → 안암역, or None."""
    body = {
        "startX":     str(origin_lon),
        "startY":     str(origin_lat),
        "endX":       str(ANAM_STATION["lon"]),
        "endY":       str(ANAM_STATION["lat"]),
        "count":      1,
        "searchDttm": SEARCH_DATETIME,
    }
    headers = {"appKey": api_key, "Content-Type": "application/json"}
    try:
        resp = requests.post(TMAP_URL, headers=headers, json=body, timeout=15)
        if resp.status_code != 200:
            return None
        itins = resp.json().get("metaData", {}).get("plan", {}).get("itineraries", [])
        if not itins:
            return None
        return itins[0]["totalTime"] / 60.0    # seconds → minutes
    except Exception:
        return None


def find_outermost_crossing(samples, level):
    """
    Given sorted samples [(dist_km, minutes), ...], return (d_lo, d_hi) bracketing
    the OUTERMOST distance where the time function crosses `level` (from below→above).
    Returns None if no crossing is found.
    """
    bracket = None
    valid = [(d, t) for d, t in samples if t is not None]
    valid.sort()
    for i in range(len(valid) - 1):
        d1, t1 = valid[i]
        d2, t2 = valid[i + 1]
        # Looking for upward crossing (t1 < level <= t2)
        if t1 < level <= t2:
            bracket = (d1, d2)        # keep updating → ends as outermost
    return bracket


def search_ray(api_key, angle_rad, levels, call_counter):
    """
    Search one ray for all contour level crossings.
    Returns dict {level: (lat, lon) of crossing point on this ray, or None if not crossed}.
    """
    # Step 1 — coarse sweep along the ray
    samples = []  # (dist_km, minutes)
    for d in COARSE_SAMPLES_KM:
        lat, lon = offset_point(ANAM_STATION["lat"], ANAM_STATION["lon"], angle_rad, d)
        t = query_tmap_minutes(api_key, lat, lon)
        call_counter[0] += 1
        samples.append((d, t))
        time.sleep(0.3)  # small pause to be polite to the API

    # Step 2 — binary search per contour, from outermost (longest) inward
    results = {}
    sorted_levels = sorted(levels, reverse=True)
    upper_bound_km = MAX_DIST_KM

    for level in sorted_levels:
        bracket = find_outermost_crossing(samples, level)
        if bracket is None:
            # Whole ray either below level (very close) or above (very far)
            results[level] = None
            continue

        d_lo, d_hi = bracket
        # Tighten with previous (smaller-distance) results — not needed since we
        # already pick the outermost crossing per level.

        for _ in range(BINARY_ITERATIONS):
            d_mid = (d_lo + d_hi) / 2
            lat, lon = offset_point(ANAM_STATION["lat"], ANAM_STATION["lon"],
                                    angle_rad, d_mid)
            t_mid = query_tmap_minutes(api_key, lat, lon)
            call_counter[0] += 1
            samples.append((d_mid, t_mid))
            samples.sort()
            time.sleep(0.3)

            if t_mid is None or t_mid > level:
                d_hi = d_mid
            else:
                d_lo = d_mid

        d_final = (d_lo + d_hi) / 2
        results[level] = offset_point(ANAM_STATION["lat"], ANAM_STATION["lon"],
                                       angle_rad, d_final)

    return results, samples


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--key",  required=True, help="Tmap API key")
    parser.add_argument("--rays", type=int, default=DEFAULT_NUM_RAYS,
                        help=f"Number of rays (default {DEFAULT_NUM_RAYS})")
    parser.add_argument("--out",  default="data/anam_rays.json",
                        help="Output JSON file")
    args = parser.parse_args()

    # Resume from checkpoint if present
    checkpoint = {}
    if os.path.exists(args.out):
        with open(args.out, encoding="utf-8") as f:
            checkpoint = json.load(f)

    rays_data = checkpoint.get("rays", {})
    call_counter = [checkpoint.get("api_calls", 0)]

    print(f"Origin     : 안암역 ({ANAM_STATION['lat']}, {ANAM_STATION['lon']})")
    print(f"Levels     : {CONTOUR_LEVELS} min from station")
    print(f"Rays       : {args.rays}")
    print(f"Resuming   : {len(rays_data)} rays already done\n")

    for i in range(args.rays):
        ray_key = str(i)
        if ray_key in rays_data:
            continue

        angle_deg = i * (360 / args.rays)
        angle_rad = math.radians(angle_deg)
        print(f"[Ray {i+1:>3}/{args.rays}]  angle={angle_deg:5.1f}°  "
              f"calls so far={call_counter[0]}", flush=True)

        crossings, samples = search_ray(args.key, angle_rad, CONTOUR_LEVELS,
                                         call_counter)
        rays_data[ray_key] = {
            "angle_deg": angle_deg,
            "crossings": {str(k): list(v) if v else None
                          for k, v in crossings.items()},
            "samples":   [(d, t) for d, t in samples]
        }

        # Save checkpoint every ray
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump({
                "anam":      ANAM_STATION,
                "levels":    CONTOUR_LEVELS,
                "num_rays":  args.rays,
                "rays":      rays_data,
                "api_calls": call_counter[0]
            }, f, ensure_ascii=False)

    print(f"\nDone. Total API calls: {call_counter[0]}")
    print(f"Saved to {args.out}")


if __name__ == "__main__":
    main()
