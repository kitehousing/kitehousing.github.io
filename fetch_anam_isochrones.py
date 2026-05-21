"""
Contour-tracing isochrone fetcher for KU commute map.

Origin: 안암역 (Anam Station). For each target time level, we trace the contour
by rotating counter-clockwise around the origin, warm-starting each angular step
from the previous step's radius. This guarantees EVERY angular sample produces
a valid point (no more "ray returned None" gaps), and uses far fewer API calls
than per-ray binary search because the contour is locally smooth.

Algorithm per contour:
  1. Find an initial valid radius at angle 0 via standard binary search (~7 calls)
  2. Rotate CCW in `num_steps` increments. At each angle:
     a. Probe the previous radius (1 call)
     b. If close to target: accept (~typical case, 1 call/step)
     c. Otherwise: expand bracket if needed, then ≤4 binary-search iterations
     d. Save the radius for the next angular step

Estimated calls per contour: ~72 × 3 average = ~220
For 3 contours (30, 50, 70 min): ~660 calls × 0.55원 ≈ ~360원

Usage:
    pip install requests
    python fetch_anam_isochrones.py --key YOUR_TMAP_KEY
    python fetch_anam_isochrones.py --key YOUR_TMAP_KEY --steps 90    # finer resolution
"""
import argparse, json, math, os, time
import requests

# ── Constants ─────────────────────────────────────────────────────────────────
ANAM_STATION = {"lat": 37.5862, "lon": 127.0301}

# Transit-time contour levels (minutes) FROM 안암역.
# +10 min walking to building → total 40 / 60 / 80 min commute.
CONTOUR_LEVELS = [30, 50, 70]

DEFAULT_STEPS         = 72        # 5° angular resolution
TOLERANCE_MIN         = 2.0       # ±2 min around target → accept
MAX_ITERATIONS        = 4         # per-step binary search cap
INITIAL_BOUNDS_KM     = (0.4, 22) # bracket for the very first angle
EXPAND_FACTOR         = 1.8       # bracket expansion when target is outside guess
MAX_RADIUS_KM         = 28        # absolute hard ceiling on radius
MIN_RADIUS_KM         = 0.25      # absolute floor
SEARCH_DATETIME       = "202506231900"  # weekday morning departure (YYYYMMDDHHMI)
REQUEST_PAUSE_SEC     = 0.25
NULL_FALLBACK_PROBES  = [0.85, 1.15, 0.6, 1.5]  # radius multipliers on null

# Tmap "대중교통 요약정보" endpoint — 0.55 KRW / call
TMAP_URL = "https://apis.openapi.sk.com/transit/routes/sub"

M_PER_DEG_LAT = 111320.0
M_PER_DEG_LON = 111320.0 * math.cos(math.radians(ANAM_STATION["lat"]))


def offset(angle_rad, distance_km):
    """Move from 안암역 by distance_km in direction angle_rad. Returns (lat, lon)."""
    dx_m = distance_km * 1000 * math.cos(angle_rad)
    dy_m = distance_km * 1000 * math.sin(angle_rad)
    return (ANAM_STATION["lat"] + dy_m / M_PER_DEG_LAT,
            ANAM_STATION["lon"] + dx_m / M_PER_DEG_LON)


class TmapClient:
    def __init__(self, api_key):
        self.api_key = api_key
        self.calls   = 0
        self.errors  = 0

    def query_minutes(self, lat, lon):
        """Total transit time in MINUTES from (lat, lon) → 안암역. None on failure."""
        body = {
            "startX":     str(lon),
            "startY":     str(lat),
            "endX":       str(ANAM_STATION["lon"]),
            "endY":       str(ANAM_STATION["lat"]),
            "count":      1,
            "searchDttm": SEARCH_DATETIME,
        }
        headers = {"appKey": self.api_key, "Content-Type": "application/json"}
        try:
            resp = requests.post(TMAP_URL, headers=headers, json=body, timeout=15)
            self.calls += 1
            time.sleep(REQUEST_PAUSE_SEC)
            if resp.status_code != 200:
                self.errors += 1
                return None
            itins = resp.json().get("metaData", {}).get("plan", {}).get("itineraries", [])
            if not itins:
                return None
            return itins[0]["totalTime"] / 60.0
        except Exception:
            self.errors += 1
            return None

    def query_at(self, angle_rad, distance_km):
        lat, lon = offset(angle_rad, distance_km)
        return self.query_minutes(lat, lon)


# ── Contour-tracing primitives ────────────────────────────────────────────────

def find_initial_radius(client, target, angle_rad=0.0):
    """Standard binary search at one starting angle. Returns radius_km or None."""
    r_lo, r_hi = INITIAL_BOUNDS_KM
    t_lo = client.query_at(angle_rad, r_lo)
    t_hi = client.query_at(angle_rad, r_hi)
    if t_lo is None or t_hi is None:
        return None
    if t_lo > target:
        return r_lo
    if t_hi < target:
        return r_hi
    for _ in range(7):
        r_mid = (r_lo + r_hi) / 2
        t_mid = client.query_at(angle_rad, r_mid)
        if t_mid is None or t_mid > target:
            r_hi = r_mid
        else:
            r_lo = r_mid
    return (r_lo + r_hi) / 2


def adaptive_step(client, angle_rad, target, guess_km):
    """
    Find the contour radius at `angle_rad` for `target` minutes,
    warm-starting from `guess_km`. Always returns a usable radius (never None).
    """
    # Probe at guess
    t = client.query_at(angle_rad, guess_km)
    if t is None:
        for mult in NULL_FALLBACK_PROBES:
            r = max(MIN_RADIUS_KM, min(MAX_RADIUS_KM, guess_km * mult))
            t = client.query_at(angle_rad, r)
            if t is not None:
                guess_km = r
                break
        if t is None:
            return guess_km  # give up gracefully, use previous radius

    if abs(t - target) <= TOLERANCE_MIN:
        return guess_km

    # Establish bracket
    if t > target:
        r_hi, r_lo = guess_km, guess_km / EXPAND_FACTOR
        while r_lo > MIN_RADIUS_KM:
            t_lo = client.query_at(angle_rad, r_lo)
            if t_lo is not None and t_lo < target:
                break
            r_lo /= EXPAND_FACTOR
        else:
            return MIN_RADIUS_KM
    else:
        r_lo, r_hi = guess_km, guess_km * EXPAND_FACTOR
        while r_hi < MAX_RADIUS_KM:
            t_hi = client.query_at(angle_rad, r_hi)
            if t_hi is not None and t_hi > target:
                break
            r_hi *= EXPAND_FACTOR
        else:
            return MAX_RADIUS_KM

    # Binary search inside bracket
    for _ in range(MAX_ITERATIONS):
        r_mid = (r_lo + r_hi) / 2
        t_mid = client.query_at(angle_rad, r_mid)
        if t_mid is None:
            break
        if abs(t_mid - target) <= TOLERANCE_MIN:
            return r_mid
        if t_mid > target:
            r_hi = r_mid
        else:
            r_lo = r_mid

    return (r_lo + r_hi) / 2


def trace_contour(client, target_minutes, num_steps):
    """
    Trace a single contour by rotating CCW from angle 0.
    Returns a list of (lat, lon) points — always `num_steps` long.
    """
    print(f"\n── Tracing {target_minutes}-min contour ──")
    initial = find_initial_radius(client, target_minutes)
    if initial is None:
        print(f"  ! Could not find initial radius. Skipping.")
        return None
    print(f"  initial radius @ angle 0°: {initial:.2f} km")

    points = []
    radius = initial
    step_delta = 2 * math.pi / num_steps

    for step in range(num_steps):
        angle = step * step_delta
        radius = adaptive_step(client, angle, target_minutes, radius)
        radius = max(MIN_RADIUS_KM, min(MAX_RADIUS_KM, radius))
        lat, lon = offset(angle, radius)
        points.append((lat, lon))
        if (step + 1) % 12 == 0:
            print(f"  step {step + 1:>3}/{num_steps}  "
                  f"r={radius:5.2f}km  calls so far={client.calls}")

    return points


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--key",   required=True, help="Tmap API key")
    parser.add_argument("--steps", type=int, default=DEFAULT_STEPS,
                        help=f"Number of angular samples per contour (default {DEFAULT_STEPS})")
    parser.add_argument("--out",   default="data/anam_rays.json",
                        help="Output JSON file")
    parser.add_argument("--levels", default=",".join(map(str, CONTOUR_LEVELS)),
                        help="Comma-separated minute levels (default 30,50,70)")
    args = parser.parse_args()

    levels = [int(x) for x in args.levels.split(",")]
    client = TmapClient(args.key)

    # Resume if checkpoint exists
    existing = {}
    if os.path.exists(args.out):
        with open(args.out, encoding="utf-8") as f:
            existing = json.load(f)
    contours = existing.get("contours", {})

    print(f"Origin    : 안암역 ({ANAM_STATION['lat']}, {ANAM_STATION['lon']})")
    print(f"Levels    : {levels} min")
    print(f"Steps     : {args.steps} per contour ({360/args.steps:.1f}° spacing)")

    for level in levels:
        key = str(level)
        if key in contours:
            print(f"\n{level}-min contour already in {args.out}, skipping.")
            continue

        pts = trace_contour(client, level, args.steps)
        if pts is None:
            continue
        contours[key] = pts

        # Checkpoint after each contour
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump({
                "origin":    ANAM_STATION,
                "levels":    levels,
                "num_steps": args.steps,
                "contours":  contours,
                "stats":     {"total_calls": client.calls,
                              "errors":      client.errors},
            }, f, ensure_ascii=False)

    print(f"\nDone. Total Tmap calls: {client.calls}  (errors: {client.errors})")
    print(f"Saved to {args.out}")
    print(f"Cost estimate: {client.calls} x 0.55 = {client.calls * 0.55:.0f} KRW")


if __name__ == "__main__":
    main()
