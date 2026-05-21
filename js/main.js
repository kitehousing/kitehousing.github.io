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

  /* ── Contour stroke colours, keyed by total commute time in minutes ── */
  const STROKE_BY_TOTAL_MIN = {
    20: { color: '#1B5E20', weight: 3.0 },    // dark green   — walking 20 min
    40: { color: '#43A047', weight: 2.5 },    // green        — 30 min transit + 10 walk
    60: { color: '#F9A825', weight: 2.5 },    // amber        — 50 min transit + 10 walk
    80: { color: '#D32F2F', weight: 2.5 },    // red          — 70 min transit + 10 walk
  };

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

  /* ── Render contour rings (stroke only, no fill) ── */
  function renderContour(feat) {
    const total = feat.properties.total_commute_min;
    const cfg   = STROKE_BY_TOTAL_MIN[total];
    if (!cfg) return;
    const path = geoToPath(feat.geometry.coordinates[0]);
    new naver.maps.Polygon({
      map,
      paths: [path],
      strokeWeight:  cfg.weight,
      strokeColor:   cfg.color,
      strokeOpacity: 0.95,
      strokeStyle:   'solid',
      fillOpacity:   0,
      clickable:     false,
      zIndex:        10 + (80 - total)   /* draw smaller (shorter) contours on top */
    });
  }

  /* Load all contours once (fixed — never changes per college selection) */
  Promise.all([
    fetch('data/isochrones/walking_20min.geojson').then(r => r.json()).catch(() => null),
    fetch('data/isochrones/transit_anam.geojson').then(r => r.json()).catch(() => null)
  ]).then(([walking, transit]) => {
    if (walking) walking.features.forEach(renderContour);
    if (transit) transit.features.forEach(renderContour);
  });

  /* ── College dropdown: ONLY moves a simple pin, contours stay fixed ── */
  let buildingPin = null;
  function setPin(buildingId) {
    if (buildingPin) { buildingPin.setMap(null); buildingPin = null; }
    if (!buildingId) return;
    const b = buildingData[buildingId];
    buildingPin = new naver.maps.Marker({
      map,
      position: new naver.maps.LatLng(b.lat, b.lon),
      title:    b.name,
      zIndex:   200
    });
  }

  document.getElementById('building-select').addEventListener('change', e => {
    setPin(e.target.value);
  });
}
