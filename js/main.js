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
    engineering:         { name: 'College of Engineering (공과대학)',                        lat: 37.58357730400124,  lon: 127.02533218035535 },
    liberal_arts:        { name: 'College of Liberal Arts (문과대학)',                        lat: 37.588690975580406, lon: 127.0316524428444  },
    business:            { name: 'Business School (경영대학)',                                lat: 37.59054196975258,  lon: 127.03506810895817 },
    life_sciences:       { name: 'College of Life Sciences & Biotechnology (생명과학대학)',   lat: 37.58557353604908,  lon: 127.02811925907832 },
    political_economics: { name: 'College of Political Science and Economics (정경대학)',     lat: 37.58711697261103,  lon: 127.03045850127637 },
    science:             { name: 'College of Science (이과대학)',                             lat: 37.58512085152415,  lon: 127.02537280665894 },
    education:           { name: 'College of Education (사범대학)',                           lat: 37.591605138264015, lon: 127.03446292035005 },
    international:       { name: 'College of International Studies (국제대학)',               lat: 37.588037211746524, lon: 127.03083755006668 },
    informatics:         { name: 'College of Informatics (정보대학)',                         lat: 37.58513552869056,  lon: 127.02859388682612 },
    media:               { name: 'College of Media & Communication (미디어대학)',             lat: 37.58674034554787,  lon: 127.03105298964363 },
    health:              { name: 'College of Health Science (보건과학대학)',                  lat: 37.58571602611504,  lon: 127.02467085701744 }
  };

  /* ── Contour stroke colours, keyed by total commute time in minutes ── */
  const STROKE_BY_TOTAL_MIN = {
    20: { color: '#1B5E20', weight: 3.0 },    // dark green — walking 20 min (manual)
    40: { color: '#F9A825', weight: 2.5 },    // amber      — 30 min transit + 10 walk
    60: { color: '#D32F2F', weight: 2.5 },    // red        — 50 min transit + 10 walk
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
      zIndex:        10 + (60 - total)   /* draw smaller (shorter) contours on top */
    });
  }

  /* Load all contours once (fixed — never changes per college selection).
     transit_anam.geojson now contains all four total-commute levels
     (20 / 40 / 60 / 80) — the 20-min ring is either the algorithm output
     (Tmap pedestrian) or a user-provided fallback. */
  fetch('data/isochrones/transit_anam.geojson')
    .then(r => r.json())
    .then(data => data.features.forEach(renderContour))
    .catch(() => {});

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
