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

/* ── Kakao Map ── */
if (typeof kakao === 'undefined') {
  document.getElementById('map-container').innerHTML =
    '<p style="padding:2rem;color:#c62828;">Kakao Maps failed to load. Check your network connection and that this domain is registered in Kakao Developers.</p>';
} else {
  const KU_CENTER = new kakao.maps.LatLng(37.5895, 127.0317);

  const map = new kakao.maps.Map(document.getElementById('map-container'), {
    center: KU_CENTER,
    level: 7
  });

  /* Zoom controls */
  map.addControl(new kakao.maps.ZoomControl(), kakao.maps.ControlPosition.RIGHT);

  /* ── Building data ── */
  const buildingData = {
    engineering: { name: 'College of Engineering (공과대학)', lat: 37.5893, lon: 127.0334 },
    humanities:  { name: 'College of Liberal Arts (인문대학)',  lat: 37.5903, lon: 127.0287 },
    business:    { name: 'Business School (경영대학)',           lat: 37.5877, lon: 127.0283 },
    law:         { name: 'School of Law (법학전문대학원)',        lat: 37.5883, lon: 127.0272 },
    education:   { name: 'College of Education (사범대학)',      lat: 37.5912, lon: 127.0268 },
    medicine:    { name: 'College of Medicine (의과대학)',        lat: 37.5944, lon: 127.0365 }
  };

  /* ── 5-level commute zones (largest rendered first = bottom layer) ── */
  const ISO_LEVELS = [
    { label: '80+ min',   color: '#B71C1C', fillOpacity: 0.22, strokeOpacity: 0.5 },
    { label: '60–80 min', color: '#EF6C00', fillOpacity: 0.26, strokeOpacity: 0.5 },
    { label: '40–60 min', color: '#FDD835', fillOpacity: 0.28, strokeOpacity: 0.5 },
    { label: '20–40 min', color: '#66BB6A', fillOpacity: 0.30, strokeOpacity: 0.5 },
    { label: '≤ 20 min',  color: '#1B5E20', fillOpacity: 0.35, strokeOpacity: 0.6 }
  ];

  /* ── Shared overlay for neighborhood popups ── */
  let activeOverlay = null;
  function closeOverlay() {
    if (activeOverlay) { activeOverlay.setMap(null); activeOverlay = null; }
  }
  kakao.maps.event.addListener(map, 'click', closeOverlay);

  /* ── Fixed markers (gate + subway) ── */
  function makeLabel(html, lat, lon) {
    new kakao.maps.CustomOverlay({
      map,
      position: new kakao.maps.LatLng(lat, lon),
      content: html,
      yAnchor: 1
    });
  }

  makeLabel(
    '<div style="background:#8B1A2B;color:#fff;padding:3px 8px;border-radius:4px;font:700 11px/1.5 sans-serif;white-space:nowrap;box-shadow:0 2px 6px rgba(0,0,0,.3);">KU Main Gate</div>',
    37.5877, 127.0296
  );

  [
    { name: '고려대역\nLine 6', lat: 37.5900, lon: 127.0259 },
    { name: '안암역\nLine 6',   lat: 37.5855, lon: 127.0301 },
    { name: '월곡역\nLine 6',   lat: 37.5991, lon: 127.0278 }
  ].forEach(s => makeLabel(
    `<div style="background:#fff;border:2px solid #1a56a4;color:#1a56a4;padding:2px 6px;border-radius:4px;font:600 10px/1.4 sans-serif;white-space:pre;box-shadow:0 1px 4px rgba(0,0,0,.2);text-align:center;">🚇 ${s.name}</div>`,
    s.lat, s.lon
  ));

  /* ── Neighbourhood layer ── */
  function geoToPath(ring) {
    return ring.map(([lon, lat]) => new kakao.maps.LatLng(lat, lon));
  }

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
        const poly = new kakao.maps.Polygon({
          map,
          path,
          strokeWeight: 1.5,
          strokeColor: '#666',
          strokeOpacity: 0.6,
          fillColor: rentColor(p.monthly_mid),
          fillOpacity: 0.22
        });

        kakao.maps.event.addListener(poly, 'click', e => {
          closeOverlay();
          const content = `
            <div style="font:400 13px/1.6 'Noto Sans KR',sans-serif;background:#fff;border:1.5px solid #ddd;border-radius:8px;padding:12px 14px;min-width:200px;box-shadow:0 4px 12px rgba(0,0,0,.15);position:relative;">
              <div style="font-weight:700;font-size:14px;margin-bottom:2px;">${p.name_en}</div>
              <div style="color:#888;font-size:11px;margin-bottom:8px;">${p.name_kr}</div>
              <div style="display:flex;justify-content:space-between;padding:3px 0;border-bottom:1px solid #eee;"><span style="color:#888;">Avg. Deposit</span><strong>${p.deposit}</strong></div>
              <div style="display:flex;justify-content:space-between;padding:3px 0;border-bottom:1px solid #eee;"><span style="color:#888;">Monthly Rent</span><strong>${p.monthly}</strong></div>
              <div style="font-size:11px;color:#555;margin-top:8px;">${p.notes}</div>
              <button onclick="this.parentElement._close()" style="position:absolute;top:6px;right:8px;background:none;border:none;font-size:16px;cursor:pointer;color:#999;line-height:1;">×</button>
            </div>`;
          const overlay = new kakao.maps.CustomOverlay({
            position: e.latLng,
            content,
            yAnchor: 1.1
          });
          overlay.getContent()._close = () => { overlay.setMap(null); activeOverlay = null; };
          overlay.setMap(map);
          activeOverlay = overlay;
        });
      });
    })
    .catch(() => {});

  /* ── Isochrone layer ── */
  let isoPolygons = [];
  let buildingOverlay = null;

  function clearIsochrone() {
    isoPolygons.forEach(p => p.setMap(null));
    isoPolygons = [];
    if (buildingOverlay) { buildingOverlay.setMap(null); buildingOverlay = null; }
  }

  function loadIsochrone(buildingId) {
    clearIsochrone();
    if (!buildingId) return;

    const b = buildingData[buildingId];

    /* Building label */
    buildingOverlay = new kakao.maps.CustomOverlay({
      map,
      position: new kakao.maps.LatLng(b.lat, b.lon),
      content: `<div style="background:#8B1A2B;color:#fff;padding:4px 10px;border-radius:5px;font:700 11px/1.5 sans-serif;white-space:nowrap;box-shadow:0 2px 8px rgba(0,0,0,.3);">${b.name}</div>`,
      yAnchor: 1
    });

    fetch(`data/isochrones/${buildingId}.geojson`)
      .then(r => { if (!r.ok) throw new Error(); return r.json(); })
      .then(({ features }) => {
        /* Features are stored largest→smallest; render in that order */
        features.forEach((feat, i) => {
          const cfg  = ISO_LEVELS[i] || ISO_LEVELS[ISO_LEVELS.length - 1];
          const path = geoToPath(feat.geometry.coordinates[0]);
          const poly = new kakao.maps.Polygon({
            map,
            path,
            strokeWeight: 1.5,
            strokeColor: cfg.color,
            strokeOpacity: cfg.strokeOpacity,
            strokeStyle: 'shortdash',
            fillColor: cfg.color,
            fillOpacity: cfg.fillOpacity
          });
          isoPolygons.push(poly);
        });

        /* Fit map to outermost polygon */
        if (isoPolygons.length) {
          const outer = isoPolygons[0];
          const bounds = new kakao.maps.LatLngBounds();
          outer.getPath().forEach(latlng => bounds.extend(latlng));
          map.setBounds(bounds, 40);
        }
      })
      .catch(() => {
        /* Fallback: circles */
        const pos = new kakao.maps.LatLng(b.lat, b.lon);
        [[9500, 0], [7000, 1], [5000, 2], [3000, 3], [1500, 4]]
          .forEach(([r, i]) => {
            const cfg = ISO_LEVELS[i];
            const circle = new kakao.maps.Circle({
              map,
              center: pos,
              radius: r,
              strokeWeight: 1.5,
              strokeColor: cfg.color,
              strokeOpacity: cfg.strokeOpacity,
              strokeStyle: 'shortdash',
              fillColor: cfg.color,
              fillOpacity: cfg.fillOpacity
            });
            isoPolygons.push(circle);
          });
        const bounds = new kakao.maps.LatLngBounds();
        isoPolygons[0].getBounds && isoPolygons[0].getBounds().getNorthEast && (() => {
          bounds.extend(isoPolygons[0].getBounds().getNorthEast());
          bounds.extend(isoPolygons[0].getBounds().getSouthWest());
          map.setBounds(bounds, 40);
        })();
      });
  }

  document.getElementById('building-select').addEventListener('change', e => {
    loadIsochrone(e.target.value);
  });
}
