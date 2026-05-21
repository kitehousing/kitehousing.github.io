"""
Contour-tracing isochrone fetcher for KU commute map (v4).

Origin: 안암역. Traces 4 contours by CCW rotation:
  - 20 min  (WALKING via Tmap Pedestrian endpoint)
  - 30 min  (TRANSIT via Tmap 대중교통 요약 endpoint)
  - 50 min  (TRANSIT)
  - 70 min  (TRANSIT)

After adding +10 min walk to building: total 20 / 40 / 60 / 80 min commute.

KEY MECHANISMS in this revision:

1. DUAL-MODE QUERIES
   The 20-min contour uses Tmap pedestrian routing (more realistic — within
   20 min transit overhead defeats subway). The 30/50/70 contours use Tmap
   transit summary. Both share the same cache, keyed by (mode, lat, lon).

2. GLOBAL QUERY CACHE
   (mode, lat_rounded, lon_rounded) -> minutes. Cache persists across runs.

3. INNER-CONTOUR PRIORS
   Contours processed ASCENDING (20 -> 30 -> 50 -> 70). Each one's per-angle
   radii are passed to the next as STRICT LOWER BOUNDS + warm-start hints.

4. THREE LAYERS OF GAP HANDLING
   a) In-flight: when all probes at an angle fail, use a weighted average
      of recent successful radii as the fallback (instead of just previous).
   b) Angular-neighbour smoothing: linearly interpolate failed angles from
      nearest successful neighbours on each side (closer neighbour weighs more).
   c) Cross-contour refinement (POST-PASS, after all contours traced):
      for any still-failed angle of a MIDDLE contour, interpolate from the
      same angle of the inner and outer contours by time:
          r_target = r_inner + (target - inner) / (outer - inner) * (r_outer - r_inner)
      Example: r_30=3km, r_70=5km, target=50 -> r_50=4km.

5. ACCURACY KNOBS
   Tolerance +-1 min, 90 angular steps default, 6 binary iterations.

6. VERBOSE OUTPUT
   Per-angle status line, contour banners, elapsed-time stats,
   cross-contour refinement summary.

Usage:
    pip install requests
    python fetch_anam_isochrones.py --key YOUR_TMAP_KEY
    python fetch_anam_isochrones.py --key YOUR_TMAP_KEY --steps 120 --verbose
    python fetch_anam_isochrones.py --key YOUR_TMAP_KEY --levels 30,50,70   (skip walking)
"""
import argparse, json, math, os, time
import requests

# ── Constants ─────────────────────────────────────────────────────────────────
ANAM_STATION = {"lat": 37.5862, "lon": 127.0301}

# Each level has a mode: walking or transit.
LEVEL_MODE = {
    20: "walking",
    30: "transit",
    50: "transit",
    70: "transit",
}

DEFAULT_LEVELS_ASCENDING = [20, 30, 50, 70]
DEFAULT_STEPS         = 90
TOLERANCE_MIN         = 1.0
MAX_ITERATIONS        = 6
EXPAND_FACTOR         = 1.6
SEARCH_DATETIME       = "202506231900"
REQUEST_PAUSE_SEC     = 0.20
NULL_FALLBACK_PROBES  = [0.9, 1.1, 0.7, 1.4, 0.55, 1.8]
CACHE_PRECISION       = 5

# Per-mode upper / lower radius bounds (km)
MODE_BOUNDS = {
    "walking": {"lower": 0.05, "upper": 3.5,  "init_lo": 0.20, "init_hi": 2.5},
    "transit": {"lower": 0.25, "upper": 30.0, "init_lo": 0.40, "init_hi": 22.0},
}

TMAP_TRANSIT_URL    = "https://apis.openapi.sk.com/transit/routes/sub"
TMAP_PEDESTRIAN_URL = "https://apis.openapi.sk.com/tmap/routes/pedestrian"

M_PER_DEG_LAT = 111320.0
M_PER_DEG_LON = 111320.0 * math.cos(math.radians(ANAM_STATION["lat"]))


def offset(angle_rad, distance_km):
    dx_m = distance_km * 1000 * math.cos(angle_rad)
    dy_m = distance_km * 1000 * math.sin(angle_rad)
    return (ANAM_STATION["lat"] + dy_m / M_PER_DEG_LAT,
            ANAM_STATION["lon"] + dx_m / M_PER_DEG_LON)


def fmt_elapsed(start_ts):
    s = int(time.time() - start_ts)
    return f"{s // 60}m{s % 60:02d}s"


# ── Dual-mode Tmap client with cache ──────────────────────────────────────────

class TmapClient:
    def __init__(self, api_key, cache=None, verbose=False):
        self.api_key       = api_key
        self.cache         = dict(cache) if cache else {}
        self.api_calls     = 0
        self.cache_hits    = 0
        self.errors        = 0
        self.verbose       = verbose
        # Track by mode for reporting
        self.calls_by_mode = {"walking": 0, "transit": 0}

    def _key(self, mode, lat, lon):
        return f"{mode}|{round(lat, CACHE_PRECISION)},{round(lon, CACHE_PRECISION)}"

    def _query_transit(self, lat, lon):
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
            resp = requests.post(TMAP_TRANSIT_URL, headers=headers, json=body, timeout=15)
            self.api_calls += 1
            self.calls_by_mode["transit"] += 1
            time.sleep(REQUEST_PAUSE_SEC)
            if resp.status_code != 200:
                self.errors += 1
                return None
            itins = resp.json().get("metaData", {}).get("plan", {}).get("itineraries", [])
            return itins[0]["totalTime"] / 60.0 if itins else None
        except Exception:
            self.errors += 1
            return None

    def _query_walking(self, lat, lon):
        body = {
            "startX":        str(lon),
            "startY":        str(lat),
            "endX":          str(ANAM_STATION["lon"]),
            "endY":          str(ANAM_STATION["lat"]),
            "reqCoordType":  "WGS84GEO",
            "resCoordType":  "WGS84GEO",
            "startName":     "출발",
            "endName":       "안암역",
        }
        headers = {"appKey": self.api_key, "Content-Type": "application/json"}
        try:
            resp = requests.post(TMAP_PEDESTRIAN_URL, headers=headers, json=body, timeout=15)
            self.api_calls += 1
            self.calls_by_mode["walking"] += 1
            time.sleep(REQUEST_PAUSE_SEC)
            if resp.status_code != 200:
                self.errors += 1
                return None
            data = resp.json()
            for feat in data.get("features", []):
                props = feat.get("properties", {})
                if "totalTime" in props:
                    return props["totalTime"] / 60.0
            return None
        except Exception:
            self.errors += 1
            return None

    def query(self, mode, lat, lon):
        """Return minutes (mode='walking' or 'transit'). Cached."""
        k = self._key(mode, lat, lon)
        if k in self.cache:
            self.cache_hits += 1
            return self.cache[k]
        result = self._query_walking(lat, lon) if mode == "walking" else self._query_transit(lat, lon)
        if result is not None:
            self.cache[k] = result
        return result

    def query_at(self, mode, angle_rad, distance_km):
        lat, lon = offset(angle_rad, distance_km)
        return self.query(mode, lat, lon)


# ── Contour-tracing primitives ────────────────────────────────────────────────

def find_initial_radius(client, mode, target, angle_rad=0.0,
                        lower=None, upper=None):
    """Binary search along one ray. Returns radius_km or None."""
    b = MODE_BOUNDS[mode]
    r_lo = max(lower if lower is not None else b["lower"], b["init_lo"])
    r_hi = min(upper if upper is not None else b["upper"], b["init_hi"])
    if r_lo >= r_hi:
        return r_lo

    t_lo = client.query_at(mode, angle_rad, r_lo)
    if t_lo is None:
        for mult in [1.2, 0.85, 1.5, 0.7]:
            cand = max(b["lower"], r_lo * mult)
            if cand >= r_hi: continue
            t_lo = client.query_at(mode, angle_rad, cand)
            if t_lo is not None:
                r_lo = cand; break
        if t_lo is None: return None

    t_hi = client.query_at(mode, angle_rad, r_hi)
    if t_hi is None:
        for mult in [0.85, 1.15, 0.7]:
            cand = min(b["upper"], r_hi * mult)
            if cand <= r_lo: continue
            t_hi = client.query_at(mode, angle_rad, cand)
            if t_hi is not None:
                r_hi = cand; break
        if t_hi is None: return None

    if t_lo > target: return r_lo
    if t_hi < target: return r_hi
    for _ in range(8):
        r_mid = (r_lo + r_hi) / 2
        t_mid = client.query_at(mode, angle_rad, r_mid)
        if t_mid is None or t_mid > target:
            r_hi = r_mid
        else:
            r_lo = r_mid
    return (r_lo + r_hi) / 2


def find_initial_radius_robust(client, mode, target, lower=None, upper=None, fallback=None):
    for angle_deg in [0, 45, 90, 135, 180, 225, 270, 315]:
        r = find_initial_radius(client, mode, target,
                                 math.radians(angle_deg), lower, upper)
        if r is not None:
            return math.radians(angle_deg), r
    return 0.0, fallback


def adaptive_step(client, mode, angle_rad, target, guess_km,
                  lower, upper, fallback_radius=None):
    """Returns (radius, success)."""
    guess_km = max(lower, min(upper, guess_km))
    t = client.query_at(mode, angle_rad, guess_km)
    if t is None:
        for mult in NULL_FALLBACK_PROBES:
            r = max(lower, min(upper, guess_km * mult))
            t = client.query_at(mode, angle_rad, r)
            if t is not None:
                guess_km = r; break
        if t is None:
            result = fallback_radius if fallback_radius is not None else guess_km
            return max(lower, min(upper, result)), False

    if abs(t - target) <= TOLERANCE_MIN:
        return guess_km, True

    if t > target:
        r_hi = guess_km
        r_lo = max(lower, guess_km / EXPAND_FACTOR)
        for _ in range(6):
            if r_lo <= lower: break
            t_lo = client.query_at(mode, angle_rad, r_lo)
            if t_lo is not None and t_lo < target: break
            r_lo = max(lower, r_lo / EXPAND_FACTOR)
        else:
            if r_lo <= lower: return lower, True
    else:
        r_lo = guess_km
        r_hi = min(upper, guess_km * EXPAND_FACTOR)
        for _ in range(6):
            if r_hi >= upper: break
            t_hi = client.query_at(mode, angle_rad, r_hi)
            if t_hi is not None and t_hi > target: break
            r_hi = min(upper, r_hi * EXPAND_FACTOR)
        else:
            if r_hi >= upper: return upper, True

    for _ in range(MAX_ITERATIONS):
        r_mid = (r_lo + r_hi) / 2
        t_mid = client.query_at(mode, angle_rad, r_mid)
        if t_mid is None: break
        if abs(t_mid - target) <= TOLERANCE_MIN: return r_mid, True
        if t_mid > target: r_hi = r_mid
        else:              r_lo = r_mid
    return (r_lo + r_hi) / 2, True


def smooth_failed_angles(radii, success_flags, inner_radii=None, inner_pad=1.02):
    """Bilateral interpolation of failed angles from successful neighbours."""
    n = len(radii)
    n_failed = sum(1 for s in success_flags if not s)
    if n_failed == 0 or all(not s for s in success_flags):
        return list(radii), 0

    result = list(radii)
    for i in range(n):
        if success_flags[i]: continue
        ccw_idx = ccw_dist = cw_idx = cw_dist = None
        for k in range(1, n):
            if ccw_idx is None:
                c = (i + k) % n
                if success_flags[c]: ccw_idx, ccw_dist = c, k
            if cw_idx is None:
                c = (i - k) % n
                if success_flags[c]: cw_idx, cw_dist = c, k
            if ccw_idx is not None and cw_idx is not None: break

        if ccw_idx is not None and cw_idx is not None:
            tot = ccw_dist + cw_dist
            value = (cw_dist * radii[ccw_idx] + ccw_dist * radii[cw_idx]) / tot
        elif ccw_idx is not None:  value = radii[ccw_idx]
        else:                      value = radii[cw_idx]

        if inner_radii is not None:
            value = max(value, inner_radii[i] * inner_pad)
        result[i] = value
    return result, n_failed


def cross_contour_refine(contour_data, all_levels):
    """
    Post-pass refinement. For each MIDDLE contour (has both inner and outer),
    refine any angles that were originally failed using linear-by-time
    interpolation between inner and outer at the same angle.

    contour_data: { level_int: {"radii": [...], "success": [...]} }
    all_levels:   ascending list of level integers.
    Returns: dict { level: n_refined }
    """
    refinements = {}
    for idx in range(1, len(all_levels) - 1):
        inner_lvl  = all_levels[idx - 1]
        target_lvl = all_levels[idx]
        outer_lvl  = all_levels[idx + 1]

        inner = contour_data[inner_lvl]["radii"]
        outer = contour_data[outer_lvl]["radii"]
        target_radii   = contour_data[target_lvl]["radii"]
        target_success = contour_data[target_lvl]["success"]

        t = (target_lvl - inner_lvl) / (outer_lvl - inner_lvl)
        n = 0
        for i in range(len(target_radii)):
            if target_success[i]:
                continue
            r_in, r_out = inner[i], outer[i]
            if r_in >= r_out:
                continue  # contours crossed somewhere — skip
            interp = r_in + t * (r_out - r_in)
            # Sanity guards
            if not (r_in < interp < r_out):
                continue
            target_radii[i] = interp
            n += 1
        refinements[target_lvl] = n
    return refinements


# ── trace_contour with mode + verbose ─────────────────────────────────────────

def trace_contour(client, mode, target_min, num_steps,
                   inner_radii=None, scale_hint=1.4,
                   existing_radii=None, existing_success=None,
                   verbose=False, start_ts=None):
    bounds = MODE_BOUNDS[mode]
    lower_glb, upper_glb = bounds["lower"], bounds["upper"]

    radii         = list(existing_radii)   if existing_radii   else []
    success_flags = list(existing_success) if existing_success else [True] * len(radii)
    start_step    = len(radii)
    if start_step >= num_steps:
        return radii, success_flags, 0

    def lower_at(step):
        if inner_radii is None:
            return lower_glb
        return max(lower_glb, inner_radii[step] * 1.02)

    # Initial warm-start anchor
    if radii:
        current_radius = radii[-1]
    elif inner_radii is not None:
        _, current_radius = find_initial_radius_robust(
            client, mode, target_min,
            lower=lower_at(0), upper=upper_glb,
            fallback=inner_radii[0] * scale_hint)
    else:
        default_init = bounds["init_hi"] / 4
        _, current_radius = find_initial_radius_robust(
            client, mode, target_min,
            fallback=default_init)

    step_delta = 2 * math.pi / num_steps
    prev_r_for_delta = current_radius

    for step in range(start_step, num_steps):
        angle = step * step_delta
        lower = lower_at(step)
        guess = max(current_radius, lower)
        if inner_radii is not None:
            inner_guess = inner_radii[step] * scale_hint
            guess = max((current_radius + inner_guess) / 2, lower)

        # In-flight fallback: weighted avg of recent successful radii
        recent = [(r, w) for w, (r, ok) in enumerate(
                    zip(radii[-7:], success_flags[-7:]), start=1) if ok]
        if recent:
            fb = sum(w * r for r, w in recent) / sum(w for r, w in recent)
        else:
            fb = current_radius

        api_before, cache_before = client.api_calls, client.cache_hits
        new_radius, success = adaptive_step(
            client, mode, angle, target_min, guess,
            lower=lower, upper=upper_glb, fallback_radius=fb)
        radii.append(new_radius)
        success_flags.append(success)
        if success: current_radius = new_radius

        # Per-angle status line
        api_d   = client.api_calls  - api_before
        cache_d = client.cache_hits - cache_before
        delta_r = new_radius - prev_r_for_delta
        prev_r_for_delta = new_radius
        tag = "ok" if success else "FB"
        elapsed = fmt_elapsed(start_ts) if start_ts else ""
        bar = f"[{step+1:>3}/{num_steps}]"
        print(f"  {bar} a={math.degrees(angle):5.1f}°  r={new_radius:5.2f}km  "
              f"Δ={delta_r:+5.2f}  api+{api_d} cache+{cache_d}  {tag}  {elapsed}")

    radii, n_smoothed = smooth_failed_angles(radii, success_flags, inner_radii=inner_radii)
    if n_smoothed:
        print(f"  ↳ smoothed {n_smoothed} failed angle(s) via neighbour interpolation")
    return radii, success_flags, n_smoothed


# ── Main ──────────────────────────────────────────────────────────────────────

def banner(title):
    line = "═" * 62
    print(f"\n{line}\n  {title}\n{line}")


def save_state(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--key",     required=True)
    parser.add_argument("--steps",   type=int, default=DEFAULT_STEPS)
    parser.add_argument("--out",     default="data/anam_rays.json")
    parser.add_argument("--cache",   default="data/anam_query_cache.json")
    parser.add_argument("--levels",  default=",".join(map(str, DEFAULT_LEVELS_ASCENDING)),
                        help="Comma-separated minute levels (default 20,30,50,70)")
    parser.add_argument("--verbose", action="store_true",
                        help="Extra detail per binary search iteration")
    args = parser.parse_args()

    levels = sorted(int(x) for x in args.levels.split(","))
    for lvl in levels:
        if lvl not in LEVEL_MODE:
            print(f"WARNING: level {lvl} not in LEVEL_MODE map. Defaulting to transit.")
            LEVEL_MODE[lvl] = "transit"

    start_ts = time.time()

    # ── Load cache ──
    cache = {}
    if os.path.exists(args.cache):
        try:
            with open(args.cache, encoding="utf-8") as f:
                cache = json.load(f)
        except Exception:
            cache = {}
    client = TmapClient(args.key, cache=cache, verbose=args.verbose)

    # ── Load existing state for resume ──
    contour_data = {}     # { level_int: {"radii": [...], "success": [...]} }
    if os.path.exists(args.out):
        try:
            with open(args.out, encoding="utf-8") as f:
                payload = json.load(f)
            for k, v in payload.get("contours", {}).items():
                if isinstance(v, dict) and "radii" in v:
                    contour_data[int(k)] = v
        except Exception:
            contour_data = {}

    banner(f"KU Commute Contour Fetcher v4   (origin: 안암역)")
    print(f"  Levels       : {levels}  (modes: " +
          ", ".join(f"{l}={LEVEL_MODE[l]}" for l in levels) + ")")
    print(f"  Steps        : {args.steps}   ({360/args.steps:.2f}° spacing)")
    print(f"  Tolerance    : ±{TOLERANCE_MIN} min")
    print(f"  Loaded cache : {len(cache)} entries")
    print(f"  Resuming     : " +
          ", ".join(f"{l}({len(contour_data[l]['radii'])}/{args.steps})"
                    for l in contour_data) if contour_data else "  Resuming     : none")

    prev_radii = None
    for level in levels:
        mode = LEVEL_MODE[level]
        banner(f"Tracing {level}-min {mode.upper()} contour   "
               f"[elapsed {fmt_elapsed(start_ts)}]")

        existing = contour_data.get(level)
        e_radii = existing["radii"]   if existing else None
        e_succ  = existing["success"] if existing else None
        if e_radii and len(e_radii) >= args.steps:
            print(f"  already complete ({len(e_radii)}/{args.steps}), skipping")
            prev_radii = e_radii
            continue
        if e_radii:
            print(f"  resuming from step {len(e_radii)}/{args.steps}")

        api_before = client.api_calls
        radii, success, n_smoothed = trace_contour(
            client, mode, level, args.steps,
            inner_radii=prev_radii,
            existing_radii=e_radii,
            existing_success=e_succ,
            verbose=args.verbose,
            start_ts=start_ts,
        )
        contour_data[level] = {"radii": radii, "success": success}

        # Persist
        payload = {
            "origin":      ANAM_STATION,
            "num_steps":   args.steps,
            "level_modes": {str(l): LEVEL_MODE[l] for l in levels},
            "contours":    {str(l): contour_data[l] for l in contour_data},
            "stats": {
                "api_calls":     client.api_calls,
                "cache_hits":    client.cache_hits,
                "errors":        client.errors,
                "calls_by_mode": client.calls_by_mode,
            },
        }
        save_state(args.out, payload)
        save_state(args.cache, client.cache)

        api_used = client.api_calls - api_before
        n_success = sum(1 for s in success if s)
        print(f"  ✓ {level}-min {mode} done: {n_success}/{args.steps} success, "
              f"{n_smoothed} smoothed, {api_used} new API calls")

        prev_radii = radii

    # ── Cross-contour refinement (post-pass) ──
    banner("Cross-contour refinement (post-pass)")
    refs = cross_contour_refine(contour_data, levels)
    if any(refs.values()):
        for lvl, n in refs.items():
            if n:
                print(f"  refined {n} angle(s) in {lvl}-min via inner/outer interpolation")
        # Save refined data
        payload = {
            "origin":      ANAM_STATION,
            "num_steps":   args.steps,
            "level_modes": {str(l): LEVEL_MODE[l] for l in levels},
            "contours":    {str(l): contour_data[l] for l in contour_data},
            "stats": {
                "api_calls":      client.api_calls,
                "cache_hits":     client.cache_hits,
                "errors":         client.errors,
                "calls_by_mode":  client.calls_by_mode,
                "cross_refined":  refs,
            },
        }
        save_state(args.out, payload)
    else:
        print("  nothing to refine (all middle-contour angles succeeded)")

    # ── Final summary ──
    banner("FINAL SUMMARY")
    print(f"  Time elapsed       : {fmt_elapsed(start_ts)}")
    print(f"  API calls (uncached): {client.api_calls}")
    print(f"    - walking         : {client.calls_by_mode['walking']}")
    print(f"    - transit         : {client.calls_by_mode['transit']}")
    print(f"  Cache hits         : {client.cache_hits}")
    print(f"  Errors             : {client.errors}")
    print(f"  Cost estimate      : ~{client.api_calls * 0.55:.0f} KRW")
    print(f"  Output             : {args.out}")
    print(f"  Cache              : {args.cache}")
    print(f"\n  Next step: python make_isochrones_v2.py")


if __name__ == "__main__":
    main()
