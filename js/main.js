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

/* ── Map ── */
const KU_CENTER = [37.5895, 127.0317];

const buildingData = {
  engineering: {
    name: 'College of Engineering (공과대학)',
    coords: [37.5893, 127.0334],
    color: '#1565C0'
  },
  humanities: {
    name: 'College of Liberal Arts (인문대학)',
    coords: [37.5903, 127.0287],
    color: '#6A1B9A'
  },
  business: {
    name: 'Business School (경영대학)',
    coords: [37.5877, 127.0283],
    color: '#00695C'
  },
  law: {
    name: 'School of Law (법학전문대학원)',
    coords: [37.5883, 127.0272],
    color: '#E65100'
  },
  education: {
    name: 'College of Education (사범대학)',
    coords: [37.5912, 127.0268],
    color: '#558B2F'
  },
  medicine: {
    name: 'College of Medicine (의과대학)',
    coords: [37.5944, 127.0365],
    color: '#B71C1C'
  }
};

const ISOCHRONE_COLORS = [
  { minutes: 10, color: '#2E7D32', opacity: 0.35 },
  { minutes: 20, color: '#F9A825', opacity: 0.30 },
  { minutes: 30, color: '#E64A19', opacity: 0.25 }
];

const map = L.map('map-container', {
  center: KU_CENTER,
  zoom: 15,
  zoomControl: true
});

L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
  attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
  maxZoom: 18
}).addTo(map);

/* KU Main Gate marker */
const gateIcon = L.divIcon({
  className: '',
  html: '<div style="background:#8B1A2B;color:#fff;padding:3px 7px;border-radius:4px;font-size:11px;font-family:sans-serif;white-space:nowrap;box-shadow:0 2px 6px rgba(0,0,0,0.3);font-weight:700;">KU Main Gate</div>',
  iconAnchor: [40, 12]
});
L.marker([37.5877, 127.0296], { icon: gateIcon }).addTo(map);

/* Subway station markers */
const stations = [
  { name: '고려대역\nLine 6', coords: [37.5900, 127.0259] },
  { name: '안암역\nLine 6',   coords: [37.5855, 127.0301] },
  { name: '월곡역\nLine 6',   coords: [37.5991, 127.0278] }
];
stations.forEach(s => {
  const icon = L.divIcon({
    className: '',
    html: `<div style="background:#fff;border:2px solid #1a56a4;color:#1a56a4;padding:2px 6px;border-radius:4px;font-size:10px;font-family:sans-serif;white-space:pre;box-shadow:0 1px 4px rgba(0,0,0,0.2);line-height:1.3;text-align:center;">🚇 ${s.name}</div>`,
    iconAnchor: [32, 12]
  });
  L.marker(s.coords, { icon }).addTo(map);
});

/* Neighborhood layer */
let neighborhoodLayer = null;
let isochroneLayer = null;
let buildingMarker = null;

function rentColor(monthly) {
  if (monthly <= 45) return '#43a047';
  if (monthly <= 60) return '#fbc02d';
  if (monthly <= 80) return '#ef6c00';
  return '#c62828';
}

function loadNeighborhoods() {
  fetch('data/neighborhoods.geojson')
    .then(r => r.json())
    .then(data => {
      neighborhoodLayer = L.geoJSON(data, {
        style: feature => {
          const p = feature.properties;
          return {
            fillColor: rentColor(p.monthly_mid),
            fillOpacity: 0.25,
            color: '#666',
            weight: 1.2
          };
        },
        onEachFeature: (feature, layer) => {
          const p = feature.properties;
          layer.bindPopup(`
            <div style="font-family:'Noto Sans KR',sans-serif;min-width:200px;">
              <strong style="font-size:1.05rem;">${p.name_en}</strong>
              <div style="color:#666;font-size:0.8rem;margin-bottom:0.5rem;">${p.name_kr}</div>
              <table style="width:100%;font-size:0.85rem;border-collapse:collapse;">
                <tr><td style="padding:3px 0;color:#888;">Avg. Deposit</td><td style="padding:3px 0;font-weight:700;">${p.deposit}</td></tr>
                <tr><td style="padding:3px 0;color:#888;">Monthly Rent</td><td style="padding:3px 0;font-weight:700;">${p.monthly}</td></tr>
              </table>
              <div style="margin-top:0.5rem;font-size:0.82rem;color:#555;">${p.notes}</div>
            </div>
          `);
        }
      }).addTo(map);
    })
    .catch(() => console.warn('neighborhoods.geojson not found'));
}

function loadIsochrone(buildingId) {
  if (isochroneLayer) { map.removeLayer(isochroneLayer); isochroneLayer = null; }
  if (buildingMarker) { map.removeLayer(buildingMarker); buildingMarker = null; }
  if (!buildingId) return;

  const b = buildingData[buildingId];

  /* Building marker */
  const bIcon = L.divIcon({
    className: '',
    html: `<div style="background:${b.color};color:#fff;padding:4px 9px;border-radius:5px;font-size:11px;font-family:sans-serif;white-space:nowrap;box-shadow:0 2px 8px rgba(0,0,0,0.35);font-weight:700;max-width:200px;text-align:center;">${b.name}</div>`,
    iconAnchor: [70, 12]
  });
  buildingMarker = L.marker(b.coords, { icon: bIcon }).addTo(map);

  /* Load pre-computed isochrone */
  fetch(`data/isochrones/${buildingId}.geojson`)
    .then(r => {
      if (!r.ok) throw new Error('not found');
      return r.json();
    })
    .then(data => {
      /* ORS returns features ordered largest→smallest; render largest first */
      const features = data.features || [];
      const sorted = [...features].sort((a, b) =>
        (b.properties.value || 0) - (a.properties.value || 0)
      );
      isochroneLayer = L.featureGroup();
      sorted.forEach((feat, i) => {
        const cfg = ISOCHRONE_COLORS[i] || ISOCHRONE_COLORS[ISOCHRONE_COLORS.length - 1];
        L.geoJSON(feat, {
          style: {
            fillColor: cfg.color,
            fillOpacity: cfg.opacity,
            color: cfg.color,
            weight: 1.5,
            dashArray: '4 3'
          }
        }).addTo(isochroneLayer);
      });
      isochroneLayer.addTo(map);
      map.fitBounds(isochroneLayer.getBounds(), { padding: [30, 30] });
    })
    .catch(() => {
      /* Fallback: draw approximate circles */
      isochroneLayer = L.featureGroup();
      [[10, 750, ISOCHRONE_COLORS[0]], [20, 1500, ISOCHRONE_COLORS[1]], [30, 2200, ISOCHRONE_COLORS[2]]]
        .reverse()
        .forEach(([min, r, cfg]) => {
          L.circle(b.coords, {
            radius: r,
            fillColor: cfg.color,
            fillOpacity: cfg.opacity,
            color: cfg.color,
            weight: 1.5,
            dashArray: '4 3'
          }).bindTooltip(`~${min} min walk`, { permanent: false })
            .addTo(isochroneLayer);
        });
      isochroneLayer.addTo(map);
      map.fitBounds(isochroneLayer.getBounds(), { padding: [30, 30] });
    });
}

/* Wire up dropdown */
document.getElementById('building-select').addEventListener('change', e => {
  loadIsochrone(e.target.value);
});

/* Initialize */
loadNeighborhoods();
