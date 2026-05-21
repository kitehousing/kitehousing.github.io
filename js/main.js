/* ── Nav toggle ── */
const toggle = document.querySelector('.nav-toggle');
const navLinks = document.querySelector('.nav-links');
toggle.addEventListener('click', () => navLinks.classList.toggle('open'));
document.querySelectorAll('.nav-links a').forEach(a =>
  a.addEventListener('click', () => navLinks.classList.remove('open'))
);

/* ── Expandable (Jeonse detail) ── */
document.querySelectorAll('.expand-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    const body = btn.nextElementSibling;
    const open = body.classList.toggle('open');
    btn.setAttribute('aria-expanded', open);
    btn.textContent = btn.textContent.replace(open ? '▾' : '▴', open ? '▴' : '▾');
  });
});

/* ── Checklist (localStorage) ── */
document.querySelectorAll('.check-item input[type=checkbox]').forEach(cb => {
  const key = 'kite_' + cb.dataset.key;
  cb.checked = localStorage.getItem(key) === '1';
  if (cb.checked) cb.closest('.check-item').classList.add('done');
  cb.addEventListener('change', () => {
    localStorage.setItem(key, cb.checked ? '1' : '0');
    cb.closest('.check-item').classList.toggle('done', cb.checked);
  });
});

/* ── Naver Map ── */
if (typeof naver === 'undefined' || !naver.maps) {
  document.getElementById('map-container').innerHTML =
    '<p style="padding:2rem;color:#c62828;">Naver Maps failed to load. Check your network connection and that this domain is registered in Naver Cloud Platform.</p>';
} else {
  const KU_CENTER = new naver.maps.LatLng(37.5895, 127.0317);

  const map = new naver.maps.Map('map-container', {
    center: KU_CENTER,
    zoom: 13,
    mapTypeControl: false
  });

  /* ── Campus buildings (used for the walking-circle inner zone) ── */
  const buildingData = {
    engineering: { name: 'College of Engineering (공과대학)',     lat: 37.5893, lon: 127.0334 },
    humanities:  { name: 'College of Liberal Arts (인문대학)',     lat: 37.5903, lon: 127.0287 },
    business:    { name: 'Business School (경영대학)',             lat: 37.5877, lon: 127.0283 },
    law:         { name: 'School of Law (법학전문대학원)',          lat: 37.5883, lon: 127.0272 },
    education:   { name: 'College of Education (사범대학)',        lat: 37.5912, lon: 127.0268 },
    medicine:    { name: 'College of Medicine (의과대학)',          lat: 37.5944, lon: 127.0365 }
  };

  /* ── 5-level commute zones (rendered largest-first = bottom→top) ── */
  const ISO_LEVELS = [
    { label: '80+ min',   color: '#B71C1C', fillOpacity: 0.20, strokeOpacity: 0.0 },
    { label: '60–80 min', color: '#EF6C00', fillOpacity: 0.30, strokeOpacity: 0.5 },
    { label: '40–60 min', color: '#FDD835', fillOpacity: 0.34, strokeOpacity: 0.5 },
    { label: '20–40 min', color: '#66BB6A', fillOpacity: 0.38, strokeOpacity: 0.5 },
    { label: '≤ 20 min',  color: '#1B5E20', fillOpacity: 0.42, strokeOpacity: 0.6 }
  ];

  /* ── Helper: convert GeoJSON ring [[lon,lat], …] → Naver LatLng array ── */
  function geoToPath(ring) {
    return ring.map(([lon, lat]) => new naver.maps.LatLng(lat, lon));
  }

  /* ── Shared overlay for popups ── */
  let activeInfo = null;
  function closeInfo() {
    if (activeInfo) { activeInfo.close(); activeInfo = null; }
  }
  naver.maps.Event.addListener(map, 'click', closeInfo);

  /* ── Commute zones: shared transit (anam) + per-building walking circle ── */
  let transitPolygons = [];
  let walkingPolygon  = null;
  let buildingMarker  = null;
  let cachedTransit   = null;     // GeoJSON cache so we don't refetch

  function clearCommute() {
    transitPolygons.forEach(p => p.setMap(null));
    transitPolygons = [];
    if (walkingPolygon) { walkingPolygon.setMap(null); walkingPolygon = null; }
    if (buildingMarker) { buildingMarker.setMap(null); buildingMarker = null; }
  }

  function renderTransit(features) {
    /* features ordered largest → smallest (background, 70, 50, 30 min) */
    features.forEach((feat, i) => {
      const cfg = ISO_LEVELS[i];
      const path = geoToPath(feat.geometry.coordinates[0]);
      const poly = new naver.maps.Polygon({
        map,
        paths: [path],
        strokeWeight: cfg.strokeOpacity > 0 ? 1.5 : 0,
        strokeColor: cfg.color,
        strokeOpacity: cfg.strokeOpacity,
        strokeStyle: 'shortdash',
        fillColor: cfg.color,
        fillOpacity: cfg.fillOpacity,
        zIndex: 10 + i
      });
      transitPolygons.push(poly);
    });
  }

  function renderWalkingCircle(building) {
    /* ≤20 min walking circle: ~1500 m radius. Uses ISO_LEVELS[4] (dark green) */
    const cfg = ISO_LEVELS[4];
    walkingPolygon = new naver.maps.Circle({
      map,
      center: new naver.maps.LatLng(building.lat, building.lon),
      radius: 1500,
      strokeWeight: 1.5,
      strokeColor: cfg.color,
      strokeOpacity: cfg.strokeOpacity,
      strokeStyle: 'shortdash',
      fillColor: cfg.color,
      fillOpacity: cfg.fillOpacity,
      zIndex: 20
    });
  }

  async function loadCommute(buildingId) {
    clearCommute();
    if (!buildingId) return;

    const b = buildingData[buildingId];

    /* Building label — wrapper div uses CSS transform so the marker self-centers
       on (lat, lon) without needing precise anchor pixel math */
    buildingMarker = new naver.maps.Marker({
      map,
      position: new naver.maps.LatLng(b.lat, b.lon),
      icon: {
        content:
          `<div style="position:relative;transform:translate(-50%,-50%);background:#8B1A2B;color:#fff;` +
          `padding:4px 10px;border-radius:5px;font:700 11px/1.5 sans-serif;white-space:nowrap;` +
          `box-shadow:0 2px 8px rgba(0,0,0,.35);">${b.name}</div>`,
        anchor: new naver.maps.Point(0, 0)
      },
      zIndex: 200
    });

    /* Load shared transit polygons (cache after first fetch) */
    try {
      if (!cachedTransit) {
        const r = await fetch('data/isochrones/transit_anam.geojson');
        if (!r.ok) throw new Error();
        cachedTransit = await r.json();
      }
      renderTransit(cachedTransit.features);
    } catch {
      /* Transit data missing → skip silently, walking circle still renders */
    }

    /* Per-building walking circle */
    renderWalkingCircle(b);
  }

  document.getElementById('building-select').addEventListener('change', e => {
    loadCommute(e.target.value);
  });
}
