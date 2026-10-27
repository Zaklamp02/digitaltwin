// The home view's sky: layered hills under a sky that follows the real day over Utrecht.
// The sun and moon sit where they actually are (low-precision astronomy, good to ~1°), the moon
// shows its real phase, stars come out after dusk, and clouds/rain/snow/fog follow the live weather
// from Open-Meteo (free, no key; the scene just stays clear if it's unreachable).
// Ridges are seeded per day; clicking the picture reseeds them. Motion (drifting clouds, twinkling
// stars, breathing mist, falling rain) is CSS on the classes below and stops for reduced motion.

const SKY_PLACE = { lat: 52.09, lon: 5.12 }; // Utrecht
const RAD = Math.PI / 180;

// ---------- astronomy ----------
function skyDays(date) { return (date.getTime() - Date.UTC(2000, 0, 1, 12)) / 864e5; }
function eclipticToHorizon(lambda, beta, date, { lat, lon }) {
  const d = skyDays(date);
  const e = 23.439 - 0.00000036 * d;
  const ra = Math.atan2(Math.sin(lambda * RAD) * Math.cos(e * RAD) - Math.tan(beta * RAD) * Math.sin(e * RAD), Math.cos(lambda * RAD)) / RAD;
  const dec = Math.asin(Math.sin(beta * RAD) * Math.cos(e * RAD) + Math.cos(beta * RAD) * Math.sin(e * RAD) * Math.sin(lambda * RAD)) / RAD;
  const gmst = (280.46061837 + 360.98564736629 * d) % 360;
  const H = ((((gmst + lon - ra) % 360) + 540) % 360) - 180;
  const alt = Math.asin(Math.sin(lat * RAD) * Math.sin(dec * RAD) + Math.cos(lat * RAD) * Math.cos(dec * RAD) * Math.cos(H * RAD)) / RAD;
  const az = (Math.atan2(Math.sin(H * RAD), Math.cos(H * RAD) * Math.sin(lat * RAD) - Math.tan(dec * RAD) * Math.cos(lat * RAD)) / RAD + 180 + 360) % 360;
  return { alt, az };
}
function sunEcliptic(date) {
  const d = skyDays(date);
  const g = (357.529 + 0.98560028 * d) % 360;
  const q = (280.459 + 0.98564736 * d) % 360;
  return (q + 1.915 * Math.sin(g * RAD) + 0.02 * Math.sin(2 * g * RAD) + 360) % 360;
}
function moonEcliptic(date) {
  const d = skyDays(date);
  const L = 218.316 + 13.176396 * d;
  const M = 134.963 + 13.064993 * d;
  const F = 93.272 + 13.22935 * d;
  return { lambda: ((L + 6.289 * Math.sin(M * RAD)) % 360 + 360) % 360, beta: 5.128 * Math.sin(F * RAD) };
}
function skyBodies(date, place = SKY_PLACE) {
  const ls = sunEcliptic(date);
  const m = moonEcliptic(date);
  const elong = ((m.lambda - ls) % 360 + 360) % 360;
  return {
    sun: eclipticToHorizon(ls, 0, date, place),
    moon: { ...eclipticToHorizon(m.lambda, m.beta, date, place), lit: (1 - Math.cos(elong * RAD)) / 2, waxing: elong < 180 },
  };
}

// ---------- colour ----------
const hexRGB = (c) => [1, 3, 5].map((i) => parseInt(c.slice(i, i + 2), 16));
const toHex = (a) => '#' + a.map((v) => Math.round(Math.max(0, Math.min(255, v))).toString(16).padStart(2, '0')).join('');
const mix = (a, b, t) => toHex(hexRGB(a).map((v, i) => v + (hexRGB(b)[i] - v) * t));

const SKY_KEYS = [
  { alt: -12, sky: ['#141a27', '#283043'], ridges: ['#2f3748', '#262d3c', '#1d2330', '#151a24', '#0e1118'], body: '#e9e4d2' },
  { alt: -4, sky: ['#3b3a58', '#9a7f93'], ridges: ['#6d6683', '#575069', '#423c52', '#2e2a3b', '#1c1a25'], body: '#efc4a0' },
  { alt: 3, sky: ['#d9c3d6', '#f2d9c4'], ridges: ['#cdb5c4', '#a68ea6', '#7a6782', '#4f4560', '#2c2838'], body: '#efa77a' },
  { alt: 16, sky: ['#cfdde3', '#eef1ec'], ridges: ['#c5d3d2', '#a3b8b1', '#7f978c', '#5b7266', '#36463e'], body: '#fbf2d5' },
];
function skyPalette(alt) {
  if (alt <= SKY_KEYS[0].alt) return SKY_KEYS[0];
  for (let i = 1; i < SKY_KEYS.length; i++) {
    const a = SKY_KEYS[i - 1];
    const b = SKY_KEYS[i];
    if (alt <= b.alt) {
      const t = (alt - a.alt) / (b.alt - a.alt);
      return { sky: a.sky.map((c, k) => mix(c, b.sky[k], t)), ridges: a.ridges.map((c, k) => mix(c, b.ridges[k], t)), body: mix(a.body, b.body, t) };
    }
  }
  return SKY_KEYS[SKY_KEYS.length - 1];
}
// 'night' | 'dusk' | 'day': lets the page pick a stronger fade behind text on dark skies.
function skyMood(date = new Date()) {
  const a = skyBodies(date).sun.alt;
  return a < -4 ? 'night' : a < 8 ? 'dusk' : 'day';
}

// ---------- weather ----------
async function skyWeather() {
  const KEY = 'groundwork.weather';
  try {
    const cached = JSON.parse(sessionStorage.getItem(KEY) || 'null');
    if (cached && Date.now() - cached.at < 30 * 60e3) return cached.w;
  } catch { /* no storage */ }
  try {
    const url = `https://api.open-meteo.com/v1/forecast?latitude=${SKY_PLACE.lat}&longitude=${SKY_PLACE.lon}&current=cloud_cover,precipitation,weather_code&timezone=auto`;
    const r = await fetch(url);
    const c = (await r.json()).current;
    const w = { cloud: c.cloud_cover ?? 0, precip: c.precipitation ?? 0, code: c.weather_code ?? 0 };
    try { sessionStorage.setItem(KEY, JSON.stringify({ at: Date.now(), w })); } catch { /* no storage */ }
    return w;
  } catch {
    return null;
  }
}

// ---------- scene ----------
function artRandom(seed) {
  let s = seed >>> 0 || 1;
  return () => { s = (s * 1664525 + 1013904223) >>> 0; return s / 4294967296; };
}

// Returns an SVG string (1200×520) for this moment, ridges seeded by `seed`.
function landscapeSVG(seed, date = new Date(), weather = null) {
  const W = 1200;
  const H = 520;
  const HORIZON = 300;
  const id = `a${seed}`;
  const rnd = artRandom(seed);
  const { sun, moon } = skyBodies(date);
  const pal = skyPalette(sun.alt);
  const cloud = weather ? weather.cloud / 100 : 0;
  const code = weather ? weather.code : 0;
  const fog = [45, 48].includes(code);
  const night = sun.alt < -4;
  // overcast washes the sky towards grey
  const grey = night ? '#242830' : '#c3c6c8';
  const sky = pal.sky.map((c) => mix(c, grey, cloud * 0.55));
  const x = (az) => ((az - 60) / 240) * W; // east on the left, west on the right (facing south)
  const y = (alt) => HORIZON - alt * 5.2;

  let out = `<defs><linearGradient id="${id}s" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${sky[0]}"/><stop offset="1" stop-color="${sky[1]}"/></linearGradient>` +
    `<radialGradient id="${id}g"><stop offset="0" stop-color="${pal.body}" stop-opacity=".55"/><stop offset="1" stop-color="${pal.body}" stop-opacity="0"/></radialGradient>` +
    `<linearGradient id="${id}m" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${sky[1]}" stop-opacity="0"/><stop offset=".5" stop-color="${sky[1]}" stop-opacity=".35"/><stop offset="1" stop-color="${sky[1]}" stop-opacity="0"/></linearGradient>` +
    `<filter id="${id}b" x="-20%" y="-50%" width="140%" height="200%"><feGaussianBlur stdDeviation="9"/></filter></defs>` +
    `<rect width="${W}" height="${H}" fill="url(#${id}s)"/>`;

  // stars: fade in as the sun drops, hidden by cloud
  const starVis = Math.max(0, Math.min(1, (-sun.alt - 4) / 8)) * (1 - cloud);
  if (starVis > 0.05) {
    const sr = artRandom(seed ^ 0x5bd1);
    for (let i = 0; i < 110; i++) {
      const tw = i % 3 === 0 ? ` class="twinkle" style="animation-duration:${(4 + sr() * 5).toFixed(1)}s;animation-delay:-${(sr() * 9).toFixed(1)}s"` : '';
      out += `<circle${tw} cx="${(sr() * W).toFixed(0)}" cy="${(sr() * 280).toFixed(0)}" r="${(sr() * 1.1 + 0.3).toFixed(1)}" fill="#fff" opacity="${(starVis * (sr() * 0.7 + 0.2)).toFixed(2)}"/>`;
    }
  }

  // sun (with glow) by day, moon with its real phase whenever it's up
  if (sun.alt > -3 && sun.az > 50 && sun.az < 310) {
    const sx = x(sun.az).toFixed(0);
    const sy = Math.max(70, y(sun.alt)).toFixed(0);
    out += `<g opacity="${(1 - cloud * 0.8).toFixed(2)}"><circle cx="${sx}" cy="${sy}" r="170" fill="url(#${id}g)"/><circle cx="${sx}" cy="${sy}" r="32" fill="${pal.body}"/></g>`;
  }
  if (moon.alt > -2 && moon.az > 50 && moon.az < 310) {
    const mx = Math.round(x(moon.az));
    const my = Math.round(Math.max(60, y(moon.alt)));
    const r = 22;
    const k = moon.lit; // 0 new … 1 full
    const rx = Math.abs(1 - 2 * k) * r;
    // lit limb on the right while waxing (northern hemisphere), terminator as a half-ellipse
    const sweepOuter = moon.waxing ? 1 : 0;
    const sweepInner = (k > 0.5) === moon.waxing ? 1 : 0;
    const lit = `M${mx},${my - r} A${r},${r} 0 0 ${sweepOuter} ${mx},${my + r} A${rx.toFixed(1)},${r} 0 0 ${sweepInner} ${mx},${my - r} Z`;
    const vis = Math.max(0.25, Math.min(1, (6 - sun.alt) / 10)) * (1 - cloud * 0.7);
    out += `<g opacity="${vis.toFixed(2)}"><circle cx="${mx}" cy="${my}" r="${r}" fill="${mix(sky[0], '#ffffff', 0.12)}" opacity=".35"/><path d="${lit}" fill="#efe9d6"/></g>`;
  }

  // clouds: soft blurred puffs, more of them as cover rises
  const nClouds = Math.round(cloud * 9);
  if (nClouds) {
    const cr = artRandom(seed ^ 0x9e37);
    const cc = night ? '#3a4152' : sun.alt < 8 ? mix(pal.sky[1], '#ffffff', 0.3) : '#ffffff';
    out += `<g filter="url(#${id}b)" opacity="${night ? 0.7 : 0.82}">`;
    for (let i = 0; i < nClouds; i++) {
      const cx = cr() * W;
      const cy = 50 + cr() * 190;
      const w = 110 + cr() * 180;
      out += `<g class="drift" style="animation-duration:${(140 + cr() * 120).toFixed(0)}s;animation-delay:-${(cr() * 200).toFixed(0)}s">`;
      for (let j = 0; j < 5; j++) {
        out += `<ellipse cx="${(cx + (j - 2) * w * 0.22 + cr() * 20).toFixed(0)}" cy="${(cy - cr() * 18).toFixed(0)}" rx="${(w * (0.22 + cr() * 0.12)).toFixed(0)}" ry="${(16 + cr() * 16).toFixed(0)}" fill="${cc}"/>`;
      }
      out += '</g>';
    }
    out += '</g>';
  }

  // hills, nearer ones darker, with mist bands (thicker in fog)
  for (let k = 0; k < pal.ridges.length; k++) {
    const base = 230 + k * 58 + rnd() * 20;
    const amp = 26 + k * 10 + rnd() * 28;
    const f = [0.002 + rnd() * 0.003, 0.006 + rnd() * 0.006, 0.017 + rnd() * 0.012];
    const ph = [rnd() * 6.3, rnd() * 6.3, rnd() * 6.3];
    let d = `M0,${H}`;
    for (let xx = 0; xx <= W; xx += 12) {
      const yy = base - amp * (Math.sin(xx * f[0] + ph[0]) * 0.62 + Math.sin(xx * f[1] + ph[1]) * 0.28 + Math.sin(xx * f[2] + ph[2]) * 0.1);
      d += ` L${xx},${yy.toFixed(1)}`;
    }
    out += `<path d="${d} L${W},${H} Z" fill="${mix(pal.ridges[k], grey, cloud * 0.25)}"/>`;
    if (k === 1 || k === 3 || (fog && k === 2)) out += `<rect y="${(base - amp * 0.4).toFixed(0)}" width="${W}" height="${fog ? 140 : 70}" fill="url(#${id}m)" class="breathe"/>`;
  }

  // precipitation over everything: rain streaks or snow dots
  const snow = [71, 73, 75, 77, 85, 86].includes(code);
  if (weather && (weather.precip > 0.05 || (code >= 51 && code <= 99))) {
    const pr = artRandom(seed ^ 0x2545);
    const col = night ? '#9aa3b5' : '#ffffff';
    out += `<g class="${snow ? 'snowfall' : 'rainfall'}">`;
    for (let i = 0; i < (snow ? 140 : 110); i++) {
      const px = pr() * W;
      const py = pr() * H;
      out += snow
        ? `<circle cx="${px.toFixed(0)}" cy="${py.toFixed(0)}" r="${(pr() * 1.6 + 0.8).toFixed(1)}" fill="${col}" opacity=".7"/>`
        : `<line x1="${px.toFixed(0)}" y1="${py.toFixed(0)}" x2="${(px - 6).toFixed(0)}" y2="${(py + 22).toFixed(0)}" stroke="${col}" stroke-width="1.2" opacity=".35" stroke-linecap="round"/>`;
    }
    out += '</g>';
  }

  // a faint winding trail on the nearest hill
  const ty = 470 + rnd() * 20;
  out += `<path d="M${(rnd() * 200).toFixed(0)},${H} C${(300 + rnd() * 200).toFixed(0)},${ty} ${(600 + rnd() * 200).toFixed(0)},${(ty + 20).toFixed(0)} ${(900 + rnd() * 250).toFixed(0)},${(ty - 30).toFixed(0)}" fill="none" stroke="${sky[1]}" stroke-width="2" stroke-dasharray="1 7" stroke-linecap="round" opacity=".5"/>`;
  return `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid slice" xmlns="http://www.w3.org/2000/svg">${out}</svg>`;
}
