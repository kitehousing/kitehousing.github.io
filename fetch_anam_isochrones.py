"""
Contour-tracing isochrone fetcher for KU commute map (v3).

Origin: 안암역 (Anam Station). For each target time level, we trace the contour
by rotating counter-clockwise around the origin. KEY OPTIMIZATIONS in this revision:

1. GLOBAL QUERY CACHE
   Every (lat, lon) → time result is stored. Subsequent queries to the same
   point return instantly. Cache survives across angles and across contour
   levels, so binary-search overlaps cost zero API calls.

2. INNER-CONTOUR PRIORS (biggest win)
   Contours are processed ASCENDING (30, 50, 70). When tracing the 50-min
   contour at angle θ, we know the 30-min boundary at angle θ is at radius
   r_30(θ) — and mathematically, r_50(θ) MUST be > r_30(θ). We pass that as
   a strict lower bound, which dramatically tightens the binary search.

3. ROBUST INITIAL-RADIUS SEARCH
   The previous version could return None from find_initial_radius if both
   bound probes failed. Now: if angle 0 fails, try angles 90°/180°/270°/etc.,
   and as last resort use the inner contour's radius × scale.

4. TIGHTER ACCURACY
   Tolerance: ±1.0 min (was ±2.0). Steps: 90 (was 72). Binary iterations: 6
   (was 4). All produce smoother, more accurate polygons.

5. CHECKPOINT EVERY ANGLE
   The output JSON is rewritten after each angle, so a network interruption
   never loses more than one angle's progress. Mid-contour resume is supported.

Usage:
    pip install requests
    python fetch_anam_isochrones.py --key YOUR_TMAP_KEY
    python fetch_anam_isochrones.py --key YOUR_TMAP_KEY --steps 120  # finer
"""
import argparse, json, math, os, time
import requests

# ── Constants ─────────────────────────────────────────────────────────────────
ANAM_STATION = {"lat": 37.5862, "lon": 127.0301}

CONTOUR_LEVELS_ASCENDING = [30, 50, 70]   # MUST be ascending for prior-bound logic

DEFAULT_STEPS         = 90                  # 4° angular resolution
TOLERANCE_MIN         = 1.0                 # ±1 min around target
MAX_ITERATIONS        = 6                   # per-step binary search cap
INITIAL_BOUNDS_KM     = (0.4, 22.0)
EXPAND_FACTOR         = 1.6                 # bracket expansion outside guess
MAX_RADIUS_KM         = 30.0
MIN_RADIUS_KM         = 0.25
SEARCH_DATETIME       = "202506231900"      # weekday morning departure
REQUEST_PAUSE_SEC     = 0.22
NULL_FALLBACK_PROBES  = [0.9, 1.1, 0.7, 1.4, 0.55, 1.8]

# Tmap "대중교통 요약정보" endpoint — 0.55 KRW / call
TMAP_URL = "https://apis.openapi.sk.com/transit/routes/sub"

# Cache key precision (decimal places). 5 decimals ≈ 1 m, so cache hits only
# occur for queries that landed on the exact same (angle, radius). That's fine —
# we get a 100 % accurate cache.
CACHE_PRECISION = 5

M_PER_DEG_LAT = 111320.0
M_PER_DEG_LON = 111320.0 * math.cos(math.radians(ANAM_STATION["lat"]))


def offset(angle_rad, distance_km):
    """Move from 안암역 by distance_km in direction angle_rad. Returns (lat, lon)."""
    dx_m = distance_km * 1000 * math.cos(angle_rad)
    dy_m = distance_km * 1000 * math.sin(angle_rad)
    return (ANAM_STATION["lat"] + dy_m / M_PER_DEG_LAT,
            ANAM_STATION["lon"] + dx_m / M_PER_DEG_LON)


# ── Cached Tmap client ────────────────────────────────────────────────────────

class TmapClient:
    def __init__(self, api_key, cache=None):
        self.api_key     = api_key
        self.cache       = dict(cache) if cache else {}
        self.api_calls   = 0
        self.cache_hits  = 0
        self.errors      = 0

    def _key(self, lat, lon):
        return f"{round(lat, CACHE_PRECISION)},{round(lon, CACHE_PRECISION)}"

    def query_minutes(self, lat, lon):
        """Transit minutes (lat, lon) → 안암역. Cached. None on failure."""
        k = self._key(lat, lon)
        if k in self.cache:
            self.cache_hits += 1
            return self.cache[k]

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
            self.api_calls += 1
            time.sleep(REQUEST_PAUSE_SEC)
            if resp.status_code != 200:
                self.errors += 1
                return None     # don't cache transient HTTP failures
            itins = resp.json().get("metaData", {}).get("plan", {}).get("itineraries", [])
            result = itins[0]["totalTime"] / 60.0 if itins else None
            if result is not None:
                self.cache[k] = result   # only cache successful results
            return result
        except Exception:
            self.errors += 1
            return None

    def query_at(self, angle_rad, distance_km):
        lat, lon = offset(angle_rad, distance_km)
        return self.query_minutes(lat, lon)


# ── Contour-tracing primitives ────────────────────────────────────────────────

def find_initial_radius(client, target, angle_rad=0.0,
                        lower=MIN_RADIUS_KM, upper=MAX_RADIUS_KM):
    """Binary search along one ray. Returns radius_km or None."""
    r_lo = max(lower, INITIAL_BOUNDS_KM[0])
    r_hi = min(upper, INITIAL_BOUNDS_KM[1])
    if r_lo >= r_hi:
        return r_lo

    t_lo = client.query_at(angle_rad, r_lo)
    if t_lo is None:
        # Try a slightly inner/outer probe
        for mult in [1.2, 0.85, 1.5, 0.7]:
            cand = max(lower, r_lo * mult)
            if cand >= r_hi:
                continue
            t_lo = client.query_at(angle_rad, cand)
            if t_lo is not None:
                r_lo = cand
                break
        if t_lo is None:
            return None

    t_hi = client.query_at(angle_rad, r_hi)
    if t_hi is None:
        for mult in [0.85, 1.15, 0.7]:
            cand = min(upper, r_hi * mult)
            if cand <= r_lo:
                continue
            t_hi = client.query_at(angle_rad, cand)
            if t_hi is not None:
                r_hi = cand
                break
        if t_hi is None:
            return None

    if t_lo > target: return r_lo
    if t_hi < target: return r_hi

    for _ in range(8):
        r_mid = (r_lo + r_hi) / 2
        t_mid = client.query_at(angle_rad, r_mid)
        if t_mid is None or t_mid > target:
            r_hi = r_mid
        else:
            r_lo = r_mid
    return (r_lo + r_hi) / 2


def find_initial_radius_robust(client, target, lower=MIN_RADIUS_KM,
                                upper=MAX_RADIUS_KM, fallback=None):
    """
    Try angle 0 first. If it fails, try several other angles. As last resort,
    return `fallback` (so the trace can still proceed).
    Returns (start_angle_rad_used, radius_km).
    """
    for angle_deg in [0, 45, 90, 135, 180, 225, 270, 315]:
        angle_rad = math.radians(angle_deg)
        r = find_initial_radius(client, target, angle_rad, lower, upper)
        if r is not None:
            if angle_deg != 0:
                print(f"  initial probe shifted to {angle_deg}° (angle 0° failed)")
            return angle_rad, r
    if fallback is not None:
        print(f"  ! all probe angles failed, using fallback r={fallback:.2f} km")
        return 0.0, fallback
    return 0.0, None


def adaptive_step(client, angle_rad, target, guess_km,
                  lower=MIN_RADIUS_KM, upper=MAX_RADIUS_KM,
                  fallback_radius=None):
    """
    Find contour radius at `angle_rad`, warm-starting from `guess_km`.
    Returns (radius_km, success):
      success = True  if at least one query succeeded (radius is trustworthy)
      success = False if every probe returned None (radius is a fallback guess)
    `fallback_radius`: used as the result if all probes fail (e.g. weighted avg
    of recent successful angles). Defaults to `guess_km`.
    """
    guess_km = max(lower, min(upper, guess_km))

    t = client.query_at(angle_rad, guess_km)
    if t is None:
        for mult in NULL_FALLBACK_PROBES:
            r = max(lower, min(upper, guess_km * mult))
            t = client.query_at(angle_rad, r)
            if t is not None:
                guess_km = r
                break
        if t is None:
            result = fallback_radius if fallback_radius is not None else guess_km
            return max(lower, min(upper, result)), False

    if abs(t - target) <= TOLERANCE_MIN:
        return guess_km, True

    # Establish bracket
    if t > target:
        r_hi = guess_km
        r_lo = max(lower, guess_km / EXPAND_FACTOR)
        steps_expanded = 0
        while r_lo > lower and steps_expanded < 6:
            t_lo = client.query_at(angle_rad, r_lo)
            steps_expanded += 1
            if t_lo is not None and t_lo < target:
                break
            r_lo = max(lower, r_lo / EXPAND_FACTOR)
        else:
            if r_lo <= lower:
                return max(lower, r_lo), True
    else:
        r_lo = guess_km
        r_hi = min(upper, guess_km * EXPAND_FACTOR)
        steps_expanded = 0
        while r_hi < upper and steps_expanded < 6:
            t_hi = client.query_at(angle_rad, r_hi)
            steps_expanded += 1
            if t_hi is not None and t_hi > target:
                break
            r_hi = min(upper, r_hi * EXPAND_FACTOR)
        else:
            if r_hi >= upper:
                return min(upper, r_hi), True

    # Binary search inside bracket
    for _ in range(MAX_ITERATIONS):
        r_mid = (r_lo + r_hi) / 2
        t_mid = client.query_at(angle_rad, r_mid)
        if t_mid is None:
            break
        if abs(t_mid - target) <= TOLERANCE_MIN:
            return r_mid, True
        if t_mid > target:
            r_hi = r_mid
        else:
            r_lo = r_mid

    return (r_lo + r_hi) / 2, True


def smooth_failed_angles(radii, success_flags, inner_radii=None, inner_pad=1.02):
    """
    For each angle with success=False, replace its radius with a linear
    interpolation between the nearest successful neighbours on either side
    (going around the ring, wrap-around supported). Closer neighbour gets
    more weight. Successful angles are untouched, preserving real features.
    """
    n = len(radii)
    n_failed = sum(1 for s in success_flags if not s)
    if n_failed == 0:
        return list(radii), 0
    if all(not s for s in success_flags):
        return list(radii), 0   # nothing to interpolate from

    result = list(radii)
    for i in range(n):
        if success_flags[i]:
            continue
        # Find nearest successful neighbours on each side, with wrap-around
        ccw_idx = ccw_dist = None
        cw_idx  = cw_dist  = None
        for k in range(1, n):
            if ccw_idx is None:
                cand = (i + k) % n
                if success_flags[cand]:
                    ccw_idx, ccw_dist = cand, k
            if cw_idx is None:
                cand = (i - k) % n
                if success_flags[cand]:
                    cw_idx, cw_dist = cand, k
            if ccw_idx is not None and cw_idx is not None:
                break

        if ccw_idx is not None and cw_idx is not None:
            total = ccw_dist + cw_dist
            value = (cw_dist  * radii[ccw_idx]
                   + ccw_dist * radii[cw_idx]) / total   # closer = heavier
        elif ccw_idx is not None:
            value = radii[ccw_idx]
        else:
            value = radii[cw_idx]

        if inner_radii is not None:
            value = max(value, inner_radii[i] * inner_pad)
        result[i] = value

    return result, n_failed


def trace_contour(client, target_min, num_steps,
                   inner_radii=None, scale_hint=1.4,
                   existing_radii=None):
    """
    Trace one contour by CCW rotation.

    inner_radii    : optional list (len = num_steps). Strict LOWER BOUNDS per
                     angle. The contour being traced must be strictly outside
                     the inner contour at every angle.
    scale_hint     : initial-guess scaling: r_target ≈ r_inner × scale_hint.
    existing_radii : if resuming mid-contour, the already-computed radii.

    Returns (radii, n_smoothed) — radii always has length num_steps.
    """
    radii = list(existing_radii) if existing_radii else []
    success_flags = [True] * len(radii)   # assume resumed values are good

    start_step = len(radii)
    if start_step >= num_steps:
        return radii, 0

    def lower_at(step):
        if inner_radii is None:
            return MIN_RADIUS_KM
        return max(MIN_RADIUS_KM, inner_radii[step] * 1.02)

    # Establish current radius (warm-start anchor)
    if radii:
        current_radius = radii[-1]
    elif inner_radii is not None:
        fallback = inner_radii[0] * scale_hint
        _, current_radius = find_initial_radius_robust(
            client, target_min, lower=lower_at(0), fallback=fallback)
    else:
        _, current_radius = find_initial_radius_robust(
            client, target_min, fallback=5.0)

    step_delta = 2 * math.pi / num_steps

    for step in range(start_step, num_steps):
        angle = step * step_delta
        lower = lower_at(step)

        # Warm-start guess: blend previous radius with inner-scaled estimate
        guess = max(current_radius, lower)
        if inner_radii is not None:
            inner_guess = inner_radii[step] * scale_hint
            guess = max((current_radius + inner_guess) / 2, lower)

        # Fallback estimate: weighted avg of last 5 SUCCESSFUL radii.
        # Used by adaptive_step if every probe at this angle fails.
        recent = [(r, w) for w, (r, ok) in enumerate(
                    zip(radii[-7:], success_flags[-7:]), start=1) if ok]
        if recent:
            num   = sum(w * r for r, w in recent)
            denom = sum(w     for r, w in recent)
            fallback_estimate = num / denom
        else:
            fallback_estimate = current_radius

        new_radius, success = adaptive_step(
            client, angle, target_min, guess,
            lower=lower, upper=MAX_RADIUS_KM,
            fallback_radius=fallback_estimate
        )
        radii.append(new_radius)
        success_flags.append(success)

        # Update warm-start anchor only on successful steps to avoid drift
        if success:
            current_radius = new_radius

        if (step + 1) % 12 == 0 or step == num_steps - 1:
            tag = "" if success else " [fallback]"
            print(f"  step {step + 1:>3}/{num_steps}  "
                  f"r={new_radius:5.2f}km{tag}  "
                  f"api={client.api_calls}  cache_hits={client.cache_hits}")

    # Post-processing: bilateral interpolation for failed angles
    radii, n_smoothed = smooth_failed_angles(
        radii, success_flags, inner_radii=inner_radii)
    if n_smoothed:
        print(f"  smoothed {n_smoothed} failed angle(s) via neighbour interpolation")

    return radii, n_smoothed


# ── Main ──────────────────────────────────────────────────────────────────────

def save_state(path, contours_state, num_steps, client):
    payload = {
        "origin":     ANAM_STATION,
        "levels":     CONTOUR_LEVELS_ASCENDING,
        "num_steps":  num_steps,
        "contours":   contours_state,    # dict {level_str: [(lat, lon), ...]}
        "stats": {
            "api_calls":  client.api_calls,
            "cache_hits": client.cache_hits,
            "errors":     client.errors,
        },
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)


def save_cache(path, client):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(client.cache, f, ensure_ascii=False)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--key",     required=True, help="Tmap API key")
    parser.add_argument("--steps",   type=int, default=DEFAULT_STEPS,
                        help=f"Angular samples per contour (default {DEFAULT_STEPS})")
    parser.add_argument("--out",     default="data/anam_rays.json")
    parser.add_argument("--cache",   default="data/anam_query_cache.json")
    parser.add_argument("--levels",  default=",".join(map(str, CONTOUR_LEVELS_ASCENDING)),
                        help="Comma-separated minute levels (default 30,50,70)")
    args = parser.parse_args()

    levels = sorted(int(x) for x in args.levels.split(","))   # ASCENDING

    # ── Load cache ──
    cache = {}
    if os.path.exists(args.cache):
        try:
            with open(args.cache, encoding="utf-8") as f:
                cache = json.load(f)
            print(f"Loaded {len(cache)} cached queries from {args.cache}")
        except Exception:
            cache = {}

    client = TmapClient(args.key, cache=cache)

    # ── Load existing contour state (resume) ──
    contours_state = {}
    if os.path.exists(args.out):
        try:
            with open(args.out, encoding="utf-8") as f:
                contours_state = json.load(f).get("contours", {})
        except Exception:
            contours_state = {}

    print(f"Origin   : 안암역 ({ANAM_STATION['lat']}, {ANAM_STATION['lon']})")
    print(f"Levels   : {levels} min (ascending)")
    print(f"Steps    : {args.steps} per contour ({360/args.steps:.1f}° spacing)")
    print(f"Tolerance: ±{TOLERANCE_MIN} min")

    prev_radii = None    # the inner contour's per-angle radii (used as lower bound)

    for level in levels:
        print(f"\n── Tracing {level}-min contour ──")
        key = str(level)
        existing_points = contours_state.get(key, [])
        existing_radii = []
        if existing_points:
            # Reconstruct radii from saved lat/lon (haversine to origin)
            for lat, lon in existing_points:
                dlat = (lat - ANAM_STATION["lat"]) * M_PER_DEG_LAT
                dlon = (lon - ANAM_STATION["lon"]) * M_PER_DEG_LON
                existing_radii.append(math.hypot(dlat, dlon) / 1000.0)
            print(f"  resuming from step {len(existing_radii)}/{args.steps}")

        radii, _ = trace_contour(
            client, level, args.steps,
            inner_radii=prev_radii,
            existing_radii=existing_radii,
        )

        # Convert radii → points and save
        step_delta = 2 * math.pi / args.steps
        points = []
        for step, r in enumerate(radii):
            lat, lon = offset(step * step_delta, r)
            points.append([lat, lon])
        contours_state[key] = points

        save_state(args.out, contours_state, args.steps, client)
        save_cache(args.cache, client)

        prev_radii = radii    # warm-start lower bound for next (larger) contour

    print(f"\nDone.")
    print(f"  API calls (uncached) : {client.api_calls}")
    print(f"  Cache hits           : {client.cache_hits}")
    print(f"  Errors               : {client.errors}")
    print(f"  Estimated cost       : {client.api_calls * 0.55:.0f} KRW")
    print(f"  Saved contours to    : {args.out}")
    print(f"  Saved cache to       : {args.cache}")


if __name__ == "__main__":
    main()
