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

  /* ── Static labels (gate + subway stations) ── */
  function makeLabel(html, lat, lon, yAnchor = 1) {
    new naver.maps.Marker({
      map,
      position: new naver.maps.LatLng(lat, lon),
      icon: {
        content: html,
        anchor: new naver.maps.Point(html.length * 2, yAnchor * 14)
      }
    });
  }

  makeLabel(
    '<div style="background:#8B1A2B;color:#fff;padding:3px 8px;border-radius:4px;font:700 11px/1.5 sans-serif;white-space:nowrap;box-shadow:0 2px 6px rgba(0,0,0,.3);">KU Main Gate</div>',
    37.5877, 127.0296
  );
  makeLabel(
    '<div style="background:#fff;border:2px solid #1a56a4;color:#1a56a4;padding:2px 6px;border-radius:4px;font:700 10px/1.4 sans-serif;white-space:nowrap;box-shadow:0 1px 4px rgba(0,0,0,.2);">🚇 안암역 · Line 6</div>',
    37.5862, 127.0301
  );
  makeLabel(
    '<div style="background:#fff;border:2px solid #1a56a4;color:#1a56a4;padding:2px 6px;border-radius:4px;font:700 10px/1.4 sans-serif;white-space:nowrap;box-shadow:0 1px 4px rgba(0,0,0,.2);">🚇 고려대역 · Line 6</div>',
    37.5900, 127.0259
  );

  /* ── Neighborhood rent overlay ── */
  function rentColor(mid) {
    if (mid <= 45) return '#43a047';
    if (mid <= 60) return '#fbc02d';
    if (mid <= 80) return '#ef6c00';
    return '#c62828';
  }

  fetch('data/neighborhoods.geojson')
    .then(r => r.json())
    .then(({ features }) => {
      features.forEach(feat => {
        const p   = feat.properties;
        const path = geoToPath(feat.geometry.coordinates[0]);
        const poly = new naver.maps.Polygon({
          map,
          paths: [path],
          strokeWeight: 1.2,
          strokeColor: '#666',
          strokeOpacity: 0.6,
          fillColor: rentColor(p.monthly_mid),
          fillOpacity: 0.18,
          zIndex: 100
        });

        naver.maps.Event.addListener(poly, 'click', e => {
          closeInfo();
          const content = `
            <div style="font:400 13px/1.6 'Noto Sans KR',sans-serif;background:#fff;border:1.5px solid #ddd;border-radius:8px;padding:12px 14px;min-width:200px;box-shadow:0 4px 12px rgba(0,0,0,.15);">
              <div style="font-weight:700;font-size:14px;">${p.name_en}</div>
              <div style="color:#888;font-size:11px;margin-bottom:8px;">${p.name_kr}</div>
              <div style="display:flex;justify-content:space-between;padding:3px 0;border-bottom:1px solid #eee;"><span style="color:#888;">Avg. Deposit</span><strong>${p.deposit}</strong></div>
              <div style="display:flex;justify-content:space-between;padding:3px 0;border-bottom:1px solid #eee;"><span style="color:#888;">Monthly Rent</span><strong>${p.monthly}</strong></div>
              <div style="font-size:11px;color:#555;margin-top:8px;">${p.notes}</div>
            </div>`;
          activeInfo = new naver.maps.InfoWindow({
            content,
            borderWidth: 0,
            backgroundColor: 'transparent',
            disableAnchor: true,
            pixelOffset: new naver.maps.Point(0, -10)
          });
          activeInfo.open(map, e.coord);
        });
      });
    })
    .catch(() => {});

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

    /* Building label */
    buildingMarker = new naver.maps.Marker({
      map,
      position: new naver.maps.LatLng(b.lat, b.lon),
      icon: {
        content: `<div style="background:#8B1A2B;color:#fff;padding:4px 10px;border-radius:5px;font:700 11px/1.5 sans-serif;white-space:nowrap;box-shadow:0 2px 8px rgba(0,0,0,.35);">${b.name}</div>`,
        anchor: new naver.maps.Point(b.name.length * 3, 14)
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
