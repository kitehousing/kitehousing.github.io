"""
Smart-grid sample collector for KU commute map (v5 — grid approach).

Origin: 안암역. Collects transit-time samples (mode='transit', via Tmap summary
endpoint) at strategically chosen lat/lon points so that the resulting cache
can be interpolated into smooth, accurate contour polygons by
make_contours_from_grid.py.

STRATEGY:
  Layer 1 — Uniform coverage
      Sparse polar grid (12 angles × 6 radii). Ensures the entire
      0–14 km region around 안암역 has at least one nearby sample,
      so cubic interpolation doesn't extrapolate wildly.

  Layer 2 — 30-min contour band
      Dense polar grid (36 angles × 4 radii) in 3.5–7.5 km range,
      where the 30-min transit contour is typically located.

  Layer 3 — 50-min contour band
      Dense polar grid (36 angles × 4 radii) in 8.5–13 km range.

  Subway-aware boost (Layer 4)
      Extra samples along Seoul Subway Line 6 (passes through 안암역),
      Line 1 (downtown corridor), Line 4 (northern corridor), and
      Line 2 (circle line). Captures the anisotropic stretching of
      contours along high-speed transit corridors.

ALL previously-cached queries are RE-USED — only new points hit the API.

Usage:
    pip install requests
    python fetch_smart_grid.py --key YOUR_TMAP_KEY
    python fetch_smart_grid.py --key YOUR_TMAP_KEY --max-new 500
"""
import argparse, json, math, os, time
import requests

# ── Constants ─────────────────────────────────────────────────────────────────
ANAM_STATION = {"lat": 37.5862, "lon": 127.0301}
TMAP_TRANSIT_URL  = "https://apis.openapi.sk.com/transit/routes/sub"
SEARCH_DATETIME   = "202506231900"
REQUEST_PAUSE_SEC = 0.20
CACHE_PRECISION   = 5
SAVE_EVERY        = 10

M_PER_DEG_LAT = 111320.0
M_PER_DEG_LON = 111320.0 * math.cos(math.radians(ANAM_STATION["lat"]))


def offset(angle_rad, distance_km):
    dx = distance_km * 1000 * math.cos(angle_rad)
    dy = distance_km * 1000 * math.sin(angle_rad)
    return (ANAM_STATION["lat"] + dy / M_PER_DEG_LAT,
            ANAM_STATION["lon"] + dx / M_PER_DEG_LON)


def cache_key(lat, lon):
    return f"transit|{round(lat, CACHE_PRECISION)},{round(lon, CACHE_PRECISION)}"


# ── Sample-point generation ───────────────────────────────────────────────────

def generate_layer_uniform():
    """Sparse blanket coverage."""
    radii_km = [0.8, 2.5, 4.5, 7.0, 10.5, 14.0]
    n_ang    = 12
    points   = []
    for r in radii_km:
        for i in range(n_ang):
            points.append(("uniform", r, i * (2 * math.pi / n_ang)))
    return points


def generate_layer_band(name, radii_km, n_ang=36):
    return [(name, r, i * (2 * math.pi / n_ang))
            for r in radii_km for i in range(n_ang)]


def generate_layer_subway():
    """
    Extra samples along Seoul subway corridors (approximate compass directions
    from 안암역). Each direction gets ~6 samples between 4–18 km.
    Line 6: roughly W and NE from 안암역
    Line 1: SW (toward city centre) and N (toward 의정부)
    Line 4: due N (toward Suyu) and S (toward Sadang)
    Line 2: roughly SE (toward Wangsimni-Konkuk)
    """
    directions_deg = [
        # (label, bearing_deg)
        ("L6-W",    265),  ("L6-E",     85),
        ("L1-SW",  220),  ("L1-N",    345),
        ("L4-N",     0),  ("L4-S",    180),
        ("L2-SE",  140),  ("L2-NW",   320),
    ]
    radii_km = [4.0, 6.5, 9.0, 11.5, 14.0, 16.5]
    points = []
    for label, deg in directions_deg:
        ang = math.radians(deg)
        for r in radii_km:
            points.append((f"subway-{label}", r, ang))
    return points


def plan_samples():
    layers = []
    layers += generate_layer_uniform()
    layers += generate_layer_band("30min-band", [3.5, 5.0, 6.0, 7.5], n_ang=36)
    layers += generate_layer_band("50min-band", [8.5, 10.0, 11.5, 13.0], n_ang=36)
    layers += generate_layer_subway()
    return layers


# ── Tmap query ────────────────────────────────────────────────────────────────

def query_transit_minutes(api_key, lat, lon):
    body = {
        "startX":     str(lon),
        "startY":     str(lat),
        "endX":       str(ANAM_STATION["lon"]),
        "endY":       str(ANAM_STATION["lat"]),
        "count":      1,
        "searchDttm": SEARCH_DATETIME,
    }
    headers = {"appKey": api_key, "Content-Type": "application/json"}
    try:
        resp = requests.post(TMAP_TRANSIT_URL, headers=headers,
                              json=body, timeout=15)
        if resp.status_code != 200:
            return None
        itins = resp.json().get("metaData", {}).get("plan", {}).get("itineraries", [])
        return itins[0]["totalTime"] / 60.0 if itins else None
    except Exception:
        return None


# ── Main ──────────────────────────────────────────────────────────────────────

def banner(title):
    bar = "═" * 64
    print(f"\n{bar}\n  {title}\n{bar}")


def fmt_elapsed(start):
    s = int(time.time() - start)
    return f"{s // 60}m{s % 60:02d}s"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--key",      required=True)
    parser.add_argument("--cache",    default="data/anam_query_cache.json")
    parser.add_argument("--max-new",  type=int, default=600,
                        help="Cap on new API calls this run")
    args = parser.parse_args()

    # Load cache
    cache = {}
    if os.path.exists(args.cache):
        with open(args.cache, encoding="utf-8") as f:
            cache = json.load(f)

    banner(f"Smart Grid Sample Collector  (origin: 안암역)")
    print(f"  Existing cache : {len(cache)} entries")

    # Plan
    planned = plan_samples()
    print(f"\n  Planned sample layers:")
    layer_counts = {}
    for name, r, a in planned:
        key = name.split("-")[0] if "-" in name else name
        layer_counts[key] = layer_counts.get(key, 0) + 1
    for k, n in layer_counts.items():
        print(f"    {k:10s}: {n} target points")
    print(f"  Total planned  : {len(planned)} points")

    # De-duplicate against cache
    to_query = []   # list of (label, lat, lon, key)
    skipped  = 0
    for label, r, a in planned:
        lat, lon = offset(a, r)
        k = cache_key(lat, lon)
        if k in cache:
            skipped += 1
            continue
        to_query.append((label, r, math.degrees(a), lat, lon, k))

    print(f"  Already cached : {skipped}")
    print(f"  Need to query  : {len(to_query)}")

    if args.max_new < len(to_query):
        to_query = to_query[:args.max_new]
        print(f"  Capped to      : {args.max_new}")

    print(f"  Cost estimate  : ~{len(to_query) * 0.55:.0f} KRW\n")

    if not to_query:
        print("Nothing to do.")
        return

    # Query
    banner("Querying Tmap")
    start_ts = time.time()
    success = errors = 0
    for i, (label, r_km, ang_deg, lat, lon, k) in enumerate(to_query):
        result = query_transit_minutes(args.key, lat, lon)
        time.sleep(REQUEST_PAUSE_SEC)

        if result is not None:
            cache[k] = result
            success += 1
            tag = f"{result:5.1f} min"
        else:
            errors += 1
            tag = "  ERR    "

        if (i + 1) % SAVE_EVERY == 0 or i == len(to_query) - 1:
            with open(args.cache, "w", encoding="utf-8") as f:
                json.dump(cache, f, ensure_ascii=False)

        print(f"  [{i+1:>4}/{len(to_query)}]  "
              f"{label:14s}  r={r_km:5.2f}km  a={ang_deg:5.1f}°  "
              f"→  {tag}   "
              f"(ok={success} err={errors}  {fmt_elapsed(start_ts)})")

    banner("DONE")
    print(f"  New successful queries : {success}")
    print(f"  Errors                 : {errors}")
    print(f"  Cache now              : {len(cache)} entries")
    print(f"  Time elapsed           : {fmt_elapsed(start_ts)}")
    print(f"  Cost                   : ~{success * 0.55:.0f} KRW")
    print(f"\n  Next step: python make_contours_from_grid.py")


if __name__ == "__main__":
    main()
