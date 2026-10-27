'use strict';

// ---------- server state ----------
// Everything persistent comes from server.py: the plan, runs and logs from the vault, and
// sessions/settings from data/*.json. A few view-only conveniences stay in localStorage.
let S = null;
// On the public site (sebastiaandenboer.org/groundwork) the state is a read-only export and
// GROUNDWORK_STATE_URL points at it; per-device choices (location, voice…) then live in localStorage.
const LOCAL_KEY = 'groundwork.local';
const readLocal = () => { try { return JSON.parse(localStorage.getItem(LOCAL_KEY)) || {}; } catch { return {}; } };
async function refreshState() {
  // Local server (read-write) answers api/state next to the app; the public site serves a read-only
  // export at /api/groundwork/state.
  let r = await fetch(window.GROUNDWORK_STATE_URL || 'api/state', { cache: 'no-store' });
  if (!r.ok && !window.GROUNDWORK_STATE_URL) r = await fetch('/api/groundwork/state', { cache: 'no-store' });
  S = await r.json();
  S.settings = S.settings || {};
  if (S.readonly) Object.assign(S.settings, readLocal());
  S.settings.prefs = S.settings.prefs || {};
  S.settings.locations = S.settings.locations && S.settings.locations.length ? S.settings.locations : clone(DEFAULT_LOCATIONS);
}
const putJSON = (path, data) => fetch(path, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) });
let settingsTimer = null;
function saveSettings() {
  clearTimeout(settingsTimer);
  settingsTimer = setTimeout(() => {
    if (S.readonly) { try { localStorage.setItem(LOCAL_KEY, JSON.stringify({ prefs: S.settings.prefs, locations: S.settings.locations })); } catch { /* private mode */ } }
    else putJSON('api/settings', S.settings);
  }, 300);
}
const prefs = () => Object.assign({ week: 'auto', voice: true, beeps: true, ticks: false, location: 'home', demo: 'video', figureStyle: 'studio' }, S.settings.prefs);
const setPref = (k, v) => { S.settings.prefs[k] = v; saveSettings(); };

// ---------- helpers ----------
function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
    else if (k === 'class') el.className = v;
    else if (k === 'value') el.value = v;
    else if (k === 'checked') el.checked = !!v;
    else el.setAttribute(k, v === true ? '' : v);
  }
  for (const c of kids.flat(Infinity)) {
    if (c == null || c === false) continue;
    el.append(c instanceof Node ? c : String(c));
  }
  return el;
}
const svgEl = (cls) => { const s = document.createElementNS('http://www.w3.org/2000/svg', 'svg'); s.setAttribute('class', cls); return s; };
const clone = (o) => JSON.parse(JSON.stringify(o));
const isoDate = (d) => d.toLocaleDateString('sv-SE');
const todayISO = () => isoDate(new Date());
const fmtTime = (s) => { s = Math.max(0, Math.ceil(s)); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`; };
const fmtMin = (s) => `${Math.max(1, Math.round(s / 60))} min`;
const cap = (s) => s.charAt(0).toUpperCase() + s.slice(1);

function programWeek(iso) {
  const days = (new Date(iso + 'T12:00') - new Date(PROGRAM.firstMonday + 'T12:00')) / 864e5;
  return Math.min(Math.max(Math.floor(days / 7) + 1, 1), PROGRAM.weeks);
}
const currentWeek = () => { const w = prefs().week; return w === 'auto' ? programWeek(todayISO()) : +w; };
const wv = (v, week) => (Array.isArray(v) ? v[Math.min(week - 1, v.length - 1)] : v);

// ---------- locations & equipment ----------
const getLocations = () => S.settings.locations;
const saveLocations = () => saveSettings();
// prefs.location is the default (set in Settings); the top-bar picker overrides it until reload.
let sessionLoc = null;
function currentLocation() {
  const locs = getLocations();
  return locs.find((l) => l.id === sessionLoc) || locs.find((l) => l.id === prefs().location) || locs[0];
}
const eqName = (id) => (EQUIPMENT.find((e) => e.id === id) || { name: id }).name;
function canDo(exId, loc) {
  const ex = EXERCISES[exId];
  if (!ex || !ex.video) return false;
  return (ex.needs || []).every((g) => g.split('|').some((e) => loc.equipment.includes(e)));
}
function resolveEx(exId, loc) {
  if (canDo(exId, loc)) return exId;
  for (const s of EXERCISES[exId]?.subs || []) if (canDo(s, loc)) return s;
  return null;
}
function needsText(exId) {
  const n = EXERCISES[exId].needs || [];
  if (!n.length) return 'No equipment';
  return n.map((g) => g.split('|').map(eqName).join(' or ')).join(' + ');
}

// ---------- sessions ----------
const allWorkouts = () => S.sessions;
const getWorkout = (id) => S.sessions.find((w) => w.id === id);
function saveWorkout(w) {
  const i = S.sessions.findIndex((x) => x.id === w.id);
  if (i >= 0) S.sessions[i] = w; else S.sessions.push(w);
  return putJSON('api/sessions', { sessions: S.sessions });
}
function deleteWorkout(id) {
  S.sessions = S.sessions.filter((w) => w.id !== id);
  return putJSON('api/sessions', { sessions: S.sessions });
}

const itemMode = (it) => (it.holds != null ? 'holds' : it.reps != null ? 'reps' : 'time');
const exName = (id) => (EXERCISES[id] ? EXERCISES[id].name : id);

function amountText(s) {
  if (s.mode === 'time') return `${s.time} s`;
  if (s.mode === 'holds') return `${s.holds} × ${s.hold} s`;
  const n = typeof s.reps === 'number' ? `${s.reps} reps` : s.reps;
  return s.alt ? `${n} / side` : n;
}

// Flattens a workout into exercise and rest steps for a program week and location.
function buildSteps(w, week, loc) {
  const steps = [];
  steps.swaps = [];
  steps.dropped = [];
  let prevRest = 0;
  w.blocks.forEach((b) => {
    const items = [];
    for (const it of b.items) {
      if (!EXERCISES[it.ex] || (it.weeks && it.weeks.length && !it.weeks.includes(week))) continue;
      const ex = resolveEx(it.ex, loc);
      if (!ex) { steps.dropped.push(it.ex); continue; }
      if (ex !== it.ex && !steps.swaps.some((s) => s.from === it.ex)) steps.swaps.push({ from: it.ex, to: ex });
      items.push({ ...it, ex, from: ex !== it.ex ? it.ex : null });
    }
    if (!items.length) return;
    const rounds = +wv(b.rounds, week) || 1;
    const blockRest = +wv(b.rest, week) || 0;
    let firstInBlock = true;
    for (let r = 1; r <= rounds; r++) {
      items.forEach((it, ii) => {
        const sets = +wv(it.sets, week) || 1;
        const sides = it.sides === 'each' ? ['left', 'right'] : [null];
        const itemRest = it.rest != null ? +wv(it.rest, week) : blockRest;
        for (let s = 1; s <= sets; s++) {
          sides.forEach((side, si) => {
            const mode = itemMode(it);
            const step = {
              kind: 'ex', ex: it.ex, from: it.from, side, mode, set: s, sets, round: r, rounds, block: b.name || '',
              alt: it.sides === 'alt', note: it.note || '', target: wv(it.target, week) || '', pace: EXERCISES[it.ex].pace || null,
            };
            if (mode === 'reps') step.reps = wv(it.reps, week);
            if (mode === 'time') step.time = +wv(it.time, week) || 30;
            if (mode === 'holds') { step.holds = +wv(it.holds, week) || 1; step.hold = +wv(it.hold, week) || 10; step.relax = 3; }

            let gap = 0;
            let label = 'Rest';
            if (!steps.length) { gap = 6; label = 'Get ready'; }
            else if (si > 0) { gap = 5; label = 'Switch sides'; }
            else if (firstInBlock) { gap = Math.max(prevRest, 20); label = 'Rest'; }
            else if (ii === 0 && s === 1) { gap = +wv(b.roundRest, week) || 0; label = `Round ${r}`; }
            else gap = prevRest;
            if (gap < 5 && steps.length) { gap = 5; label = 'Get ready'; }
            steps.push({ kind: 'rest', time: gap, label, next: step });
            steps.push(step);
            firstInBlock = false;
            prevRest = itemRest;
          });
        }
      });
    }
  });
  return steps;
}

function stepSeconds(s) {
  if (s.kind === 'rest') return s.time;
  if (s.mode === 'time') return s.time;
  if (s.mode === 'holds') return s.holds * (s.hold + s.relax);
  const n = typeof s.reps === 'number' ? s.reps : 15;
  return Math.max(20, n * 3 * (s.alt ? 2 : 1));
}
const totalSeconds = (steps) => steps.reduce((a, s) => a + stepSeconds(s), 0);

// ---------- media ----------
let mediaStops = [];
function stopMedia() { mediaStops.forEach((f) => f()); mediaStops = []; }

const hasVideo = (exId) => !!EXERCISES[exId]?.video;

// Training uses video only. Animation experiments live on database.html.
function mediaEl(exId, { still = false, cls = '', hoverPlay = false } = {}) {
  const ex = EXERCISES[exId];
  if (!ex?.video) return h('div', { class: `media ${cls}` }, 'Video unavailable');
  const box = h('div', { class: `media is-video ${cls}` });
  if (still) {
    box.append(h('img', { src: ex.poster || '', alt: `${ex.name} demonstration`, loading: 'lazy' }));
    if (hoverPlay) {
      let v;
      box.addEventListener('mouseenter', () => {
        v = h('video', { src: ex.video, autoplay: true, loop: true, playsinline: true });
        v.muted = true; box.append(v); v.play().catch(() => {});
      });
      box.addEventListener('mouseleave', () => { if (v) { v.pause(); v.remove(); v = null; } });
    }
  } else {
    const v = h('video', { src: ex.video, poster: ex.poster || '', autoplay: true, loop: true, playsinline: true, preload: 'auto', 'aria-label': `${ex.name} video demonstration` });
    v.muted = true; box.append(v); v.play().catch(() => {});
  }
  return box;
}

// ---------- audio ----------
let actx = null;
function unlockAudio() {
  try {
    if (!actx) actx = new (window.AudioContext || window.webkitAudioContext)();
    if (actx.state === 'suspended') actx.resume();
  } catch { /* no audio */ }
}
function tone(freq = 660, dur = 0.12, vol = 0.18) {
  if (!actx) return;
  const o = actx.createOscillator();
  const g = actx.createGain();
  o.frequency.value = freq;
  o.type = 'sine';
  g.gain.setValueAtTime(0.0001, actx.currentTime);
  g.gain.exponentialRampToValueAtTime(vol, actx.currentTime + 0.01);
  g.gain.exponentialRampToValueAtTime(0.0001, actx.currentTime + dur);
  o.connect(g).connect(actx.destination);
  o.start();
  o.stop(actx.currentTime + dur + 0.02);
}
const beep = (f, d, v) => { if (prefs().beeps) tone(f, d, v); };
function say(text) {
  if (!prefs().voice || !window.speechSynthesis) return;
  speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(text.replace(/[~–—]/g, ' ').replace(/\//g, ' per '));
  u.lang = 'en-GB';
  u.rate = 0.98;
  speechSynthesis.speak(u);
}
document.addEventListener('click', unlockAudio);
document.addEventListener('keydown', unlockAudio);

// ---------- routing ----------
const app = () => document.getElementById('app');
let keyHandler = null;
function setView(node, keys = null) {
  stopMedia();
  document.body.classList.remove('snap');
  if (P) stopEngine();
  keyHandler = keys;
  app().replaceChildren(node);
  window.scrollTo(0, 0);
}
document.addEventListener('keydown', (e) => {
  if (!keyHandler) return;
  if (['INPUT', 'SELECT', 'TEXTAREA'].includes(document.activeElement.tagName)) return;
  keyHandler(e);
});
function route() {
  const [, view, id] = location.hash.split('/');
  if (view === 'library') return viewLibrary();
  if (view === 'settings') return viewSettings();
  if (view === 'sessions' || view === 'routines') return viewSessions();
  if (view === 'calendar') return viewCalendar();
  if (view === 'edit' && !S.readonly) return viewEditor(id ? decodeURIComponent(id) : null);
  if (view === 'play') return viewPrestart(decodeURIComponent(id || ''));
  return viewHome();
}
window.addEventListener('hashchange', route);

function topbar(active) {
  const link = (href, label, key) => h('a', { href, class: active === key ? 'on' : '' }, label);
  return h('header', { class: 'topbar' },
    h('a', { class: 'wordmark', href: '#/' }, 'Groundwork'),
    h('nav', {}, link('#/', 'Today', 'home'), link('#/calendar', 'Calendar', 'calendar'), link('#/routines', 'Routines', 'sessions'), link('#/library', 'Exercises', 'library'), link('#/settings', 'Settings', 'settings')));
}

// ---------- home ----------
// The plan says what's intended; the logs say what happened. Days show both.
const dayDate = (iso) => new Date(iso + 'T12:00');
const addDays = (iso, n) => isoDate(new Date(dayDate(iso).getTime() + n * 864e5));
const mondayOf = (iso) => addDays(iso, -((dayDate(iso).getDay() + 6) % 7));
const fmtDay = (iso, opts) => dayDate(iso).toLocaleDateString('en-GB', opts);
const planOn = (iso) => S.plan.find((p) => p.date === iso);
const runsOn = (iso) => S.runs.filter((r) => r.date === iso);
const sessionIdOf = (text) => { const m = /\(([^)]+)\)\s*$/.exec(text || ''); return m ? m[1] : null; };
const strengthDone = (iso, id) => S.strength.some((e) => e.date === iso && sessionIdOf(e.session) === id);
const daysUntil = (iso) => Math.round((dayDate(iso) - dayDate(todayISO())) / 864e5);
const inProgram = (iso) => iso >= PROGRAM.firstMonday && iso < addDays(PROGRAM.firstMonday, PROGRAM.weeks * 7);
const obsidianPlanLink = () => S.vault && `obsidian://open?vault=${encodeURIComponent(S.vault.name)}&file=${encodeURIComponent(S.vault.plan.replace(/\.md$/, ''))}`;
const kmText = (km) => `${(Math.round(km * 10) / 10).toFixed(1)} km`;

function runStatus(iso) {
  const runs = runsOn(iso);
  if (!runs.length) return null;
  const km = runs.reduce((a, r) => a + r.km, 0);
  const main = runs.reduce((a, r) => (r.km > a.km ? r : a));
  return h('span', { class: 'actual' }, `✓ ${kmText(km)}`, h('span', { class: 'muted' }, ` · ${main.pace}/km`));
}

// Routines show as one of two kinds: mobility (focus "mobility") or strength (everything else).
const focusOf = (id) => (getWorkout(id) || {}).focus || 'core';
const kindOfFocus = (f) => (f === 'mobility' ? 'mobility' : 'strength');
const kindOf = (id) => kindOfFocus(focusOf(id));

// Everything planned or done on a day, as uniform "activities": runs and routines look alike.
function activitiesOn(iso) {
  const p = planOn(iso);
  const runs = runsOn(iso);
  const out = [];
  if (p && !p.rest || runs.length) {
    const km = runs.reduce((a, r) => a + r.km, 0);
    const main = runs.length ? runs.reduce((a, r) => (r.km > a.km ? r : a)) : null;
    out.push({
      kind: 'run', icon: p && p.race ? 'race' : 'run', focus: 'run', done: !!runs.length,
      title: p && p.race ? p.race : p && !p.rest ? p.run : 'Run',
      meta: p && p.race ? 'Race' : 'Run',
      result: runs.length ? `${kmText(km)} · ${main.pace}/km` : p && p.runKm ? `${p.runKm} km planned` : '',
    });
  }
  for (const id of p ? p.strength : []) {
    const w = getWorkout(id);
    const f = kindOf(id);
    out.push({
      kind: 'routine', id, icon: f, focus: f, done: strengthDone(iso, id),
      title: w ? w.name : id,
      meta: [w ? w.tag : null, w ? fmtMin(totalSeconds(buildSteps(w, currentWeek(), currentLocation()))) : null].filter(Boolean).join('  ·  '),
    });
  }
  return out;
}

function activityCard(a) {
  const right = a.kind === 'routine'
    ? h('a', { class: 'act-go', href: `#/play/${encodeURIComponent(a.id)}` }, a.done ? 'Again →' : 'Begin →')
    : h('span', { class: `act-result ${a.done ? 'done' : ''}` }, a.done ? `✓ ${a.result}` : a.result);
  return h('div', { class: `act ${a.done ? 'is-done' : ''}` },
    icon(a.icon, `f-${a.focus} ${a.done ? 'filled' : ''}`),
    h('div', { class: 'act-text' }, h('div', { class: 'act-title' }, a.title), h('div', { class: 'act-meta' }, a.meta)),
    right);
}

let selectedDay = null;
// Month view of the plan, in round badges: runner for runs (with km), flag for races, and one badge per
// routine in its focus colour. Outlined = planned, filled = done.
function calendar() {
  const today = todayISO();
  const start = addDays(mondayOf(today), -7);
  const lastPlanned = S.plan.length ? S.plan[S.plan.length - 1].date : today;
  const end = addDays(mondayOf(lastPlanned > today ? lastPlanned : today), 6);
  const cells = [];
  for (let d = start; d <= end; d = addDays(d, 1)) {
    const p = planOn(d);
    const acts = activitiesOn(d);
    const run = acts.find((a) => a.kind === 'run');
    const ranKm = runsOn(d).reduce((a, r) => a + r.km, 0);
    const first = dayDate(d).getDate() === 1 || d === start;
    cells.push(h('button', {
      class: `cday ${d === today ? 'today' : ''} ${d < today ? 'past' : ''} ${d === selectedDay ? 'sel' : ''} ${p || ranKm ? '' : 'empty'}`,
      title: acts.map((a) => a.title).join(' · '),
      onclick: () => selectDay(d),
    },
      h('span', { class: 'c-n' }, first ? fmtDay(d, { day: 'numeric', month: 'short' }) : dayDate(d).getDate()),
      h('span', { class: 'c-icons' },
        run ? h('span', { class: 'c-item' }, icon(run.icon, `f-run ${run.done ? 'filled' : ''}`),
          h('span', { class: 'c-km' }, ranKm ? `${Math.round(ranKm * 10) / 10}` : p && p.runKm ? `${p.runKm}` : '')) : null,
        acts.filter((a) => a.kind === 'routine').map((a) => h('span', { class: 'c-item', title: a.title }, icon(a.icon, `f-${a.focus} ${a.done ? 'filled' : ''}`))),
        p && p.rest && !acts.length ? h('span', { class: 'c-item rest' }, icon('rest', 'f-rest')) : null)));
  }
  const legend = h('div', { class: 'legend' },
    h('span', {}, icon('run', 'f-run'), 'Run · km'),
    h('span', {}, icon('race', 'f-run'), 'Race'),
    h('span', {}, icon('strength', 'f-strength'), 'Strength'),
    h('span', {}, icon('mobility', 'f-mobility'), 'Mobility'),
    h('span', {}, icon('strength', 'f-strength filled'), 'Done'));
  return h('div', { class: 'calendar' }, h('div', { class: 'cal-dow' }, ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'].map((x) => h('span', {}, x))), h('div', { class: 'cal' }, cells), legend);
}

// Day by day from today to the end of the plan; a past day picked in the month view shows on top.
function agenda() {
  const today = todayISO();
  const lastPlanned = S.plan.length ? S.plan[S.plan.length - 1].date : today;
  const days = [];
  if (selectedDay && selectedDay < today) days.push(selectedDay);
  for (let d = today; d <= lastPlanned; d = addDays(d, 1)) days.push(d);
  return h('div', { class: 'agenda' }, days.map((d) => {
    const acts = activitiesOn(d);
    const p = planOn(d);
    return h('section', { class: `ag-day ${d === today ? 'today' : ''} ${d === selectedDay ? 'sel' : ''}`, id: `day-${d}` },
      h('div', { class: 'ag-head' },
        h('span', { class: 'ag-date' }, d === today ? 'Today' : fmtDay(d, { weekday: 'long' })),
        h('span', { class: 'muted' }, fmtDay(d, { day: 'numeric', month: 'long' }))),
      acts.length ? acts.map(activityCard) : h('div', { class: 'act rest' }, icon('rest', 'f-rest'), h('div', { class: 'act-text' }, h('div', { class: 'act-title' }, 'Rest'))),
      p && p.note ? h('p', { class: 'ag-note' }, p.note) : null);
  }));
}

function selectDay(d) {
  selectedDay = d;
  renderCalendarView();
  const el = document.getElementById(`day-${d}`);
  if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
}
function renderCalendarView() {
  const box = document.getElementById('calview');
  if (!box) return;
  box.replaceChildren(calendar(), h('h2', { class: 'agenda-title' }, 'Day by day'), agenda());
}

// Rotating lines for the home view.
const QUOTES = [
  ['Little by little, one travels far.', 'J.R.R. Tolkien'],
  ['It does not matter how slowly you go, as long as you do not stop.', 'Confucius'],
  ['The journey of a thousand miles begins with one step.', 'Lao Tzu'],
  ['Fall seven times, stand up eight.', 'Japanese proverb'],
  ['We are what we repeatedly do.', 'Will Durant'],
  ['Run the mile you are in.', 'Ryan Hall'],
  ['Slow is smooth, smooth is fast.', 'Old military saying'],
  ['Easy days easy, hard days hard.', 'Training maxim'],
  ['Consistency beats intensity.', 'Training maxim'],
  ['Motion is lotion.', 'Physio saying'],
  ['Rest is part of the training.', 'Training maxim'],
  ['You don’t have to go fast. You just have to go.', 'Runner’s saying'],
  ['Good form is free speed.', 'Coach’s saying'],
  ['Every expert was once a beginner.', 'Proverb'],
  ['Today’s work is tomorrow’s groundwork.', 'Groundwork'],
  ['Small steps, every day.', 'Groundwork'],
  ['Strength is built in the reps nobody sees.', 'Groundwork'],
  ['The best workout is the one you actually do.', 'Training maxim'],
];
function quoteRotator() {
  const box = h('div', { class: 'quote' });
  let i = Math.floor(Math.random() * QUOTES.length);
  const show = () => {
    const [q, who] = QUOTES[i % QUOTES.length];
    box.classList.add('out');
    setTimeout(() => { box.replaceChildren(h('span', { class: 'q' }, q), h('span', { class: 'q-who' }, who)); box.classList.remove('out'); }, 450);
    i++;
  };
  show();
  const t = setInterval(show, 11000);
  mediaStops.push(() => clearInterval(t));
  return box;
}

// Home: today's main routine with Begin, the rest of today as cards, over a live sky.
function todayPanel() {
  const today = todayISO();
  const acts = activitiesOn(today);
  const routines = acts.filter((a) => a.kind === 'routine');
  const main = routines.find((a) => !a.done) || routines[0];
  const p = planOn(today);
  const title = p && p.race ? p.race : main ? main.title : acts.length ? (p && p.runKm ? `${p.runKm} km run` : 'Run day') : 'Rest day';
  return h('section', { class: 'today-panel' },
    quoteRotator(),
    h('h1', { class: 'display' }, title),
    main ? h('div', { class: 'hero-actions' },
      h('a', { class: 'begin', href: `#/play/${encodeURIComponent(main.id)}` }, h('span', { class: 'begin-icon' }), main.done ? 'Again' : 'Begin'),
      h('span', { class: 'lede' }, main.meta)) : null,
    h('div', { class: 'today-acts' }, acts.filter((a) => a !== main).map(activityCard)));
}

let artSeed = null;
function viewHome() {
  const today = todayISO();
  if (artSeed == null) artSeed = Number(today.replace(/-/g, ''));
  const art = h('div', { class: 'art-full', title: 'The sky over Utrecht right now · weather: Open-Meteo · click for other hills' });
  const home = h('div', { class: `home-full mood-${skyMood()}` },
    art, h('div', { class: 'home-scrim' }),
    h('div', { class: 'home-content' },
      h('div', { class: 'page narrow' }, topbar('home')),
      h('div', { class: 'page narrow home-today' }, todayPanel())));
  let weather = null;
  const paint = () => {
    art.innerHTML = landscapeSVG(artSeed, new Date(), weather);
    home.className = `home-full mood-${skyMood()}`;
  };
  art.addEventListener('click', () => { artSeed += 7919; art.classList.add('fade'); setTimeout(() => { paint(); art.classList.remove('fade'); }, 250); });
  paint();
  setView(home);
  skyWeather().then((w) => { weather = w; if (document.body.contains(art)) paint(); });
  const t = setInterval(paint, 5 * 60e3);
  mediaStops.push(() => clearInterval(t));
}

function viewCalendar() {
  setView(h('div', { class: 'page narrow' }, topbar('calendar'),
    h('div', { class: 'page-head cal-head' }, h('h1', { class: 'display small' }, 'Calendar'),
      S.vault ? h('a', { class: 'quiet', href: obsidianPlanLink() }, 'Edit plan in Obsidian') : null),
    h('div', { id: 'calview' })));
  renderCalendarView();
}

// ---------- sessions ----------
function viewSessions() {
  const week = currentWeek();
  const loc = currentLocation();
  setView(h('div', { class: 'page narrow' }, topbar('sessions'),
    h('div', { class: 'page-head' }, h('h1', { class: 'display small' }, 'Routines'),
      h('p', { class: 'lede' }, `Ready-made routines. The plan picks one per day; start any of them here.`)),
    h('div', { class: 'rows' }, allWorkouts().map((w) => {
      const steps = buildSteps(w, week, loc);
      const nEx = new Set(steps.filter((s) => s.kind === 'ex').map((s) => s.ex)).size;
      return h('div', { class: 'row' },
        h('a', { class: 'row-main', href: `#/play/${encodeURIComponent(w.id)}` },
          icon(kindOfFocus(w.focus), `f-${kindOfFocus(w.focus)}`),
          h('span', { class: 'row-title' }, w.name),
          h('span', { class: 'row-meta' }, `${w.id}  ·  ${nEx} exercises  ·  ${fmtMin(totalSeconds(steps))}`),
          h('span', { class: 'row-go' }, '→')),
        S.readonly ? null : h('a', { class: 'row-edit', href: `#/edit/${encodeURIComponent(w.id)}` }, 'Edit'));
    })),
    S.readonly ? null : h('div', { class: 'btns', style: 'margin-top:28px' }, h('a', { class: 'btn', href: '#/edit' }, 'New routine'))));
}

// ---------- library ----------
const LIB = { filter: 'all', onlyHere: false, q: '', shown: 48 };
function viewLibrary() {
  const loc = currentLocation();
  const tags = ['all', 'program', 'back', 'core', 'arms', 'upper', 'legs', 'mobility', 'cardio'];
  const q = LIB.q.trim().toLowerCase();
  const ids = Object.keys(EXERCISES).filter((id) => {
    const ex = EXERCISES[id];
    if (!hasVideo(id)) return false;
    if (LIB.filter === 'program' && ex.lib) return false;
    if (!['all', 'program'].includes(LIB.filter) && !ex.tags.includes(LIB.filter)) return false;
    if (LIB.onlyHere && !canDo(id, loc)) return false;
    return !q || ex.name.toLowerCase().includes(q);
  });
  const practice = (id) => startPlayer({ id: `practice-${id}`, name: exName(id), blocks: [{ name: '', rounds: 1, rest: 0, roundRest: 0, items: [{ ex: id, time: 30 }] }] });
  const set = (k, v) => { LIB[k] = v; LIB.shown = 48; viewLibrary(); };
  const search = h('input', { class: 'search', type: 'search', placeholder: `Search ${Object.keys(EXERCISES).filter(hasVideo).length} exercises`, value: LIB.q });
  search.addEventListener('input', () => { LIB.q = search.value; LIB.shown = 48; clearTimeout(search._t); search._t = setTimeout(() => { viewLibrary(); const s = document.querySelector('.search'); s.focus(); s.setSelectionRange(s.value.length, s.value.length); }, 180); });
  setView(h('div', { class: 'page narrow' }, topbar('library'),
    h('div', { class: 'page-head' }, h('h1', { class: 'display small' }, 'Exercises'),
      h('p', { class: 'lede' }, `${Object.keys(EXERCISES).filter(hasVideo).length} movements with video. Find your form, one movement at a time.`)),
    h('div', { class: 'filters' }, search,
      tags.map((t) => h('button', { class: `pill ${t === LIB.filter ? 'on' : ''}`, onclick: () => set('filter', t) }, cap(t))),
      h('label', { class: 'switch' }, h('input', { type: 'checkbox', checked: LIB.onlyHere, onchange: (e) => set('onlyHere', e.target.checked) }), h('span', {}, `Only at ${loc.name}`))),
    h('p', { class: 'library-hint' }, 'Video demonstrations only. Hover a tile to preview, or choose Try 30 s. ', h('a', { href: 'http://localhost:8781/', target: '_blank', rel: 'noopener' }, 'Exercise database & animation studies ↗')),
    h('p', { class: 'muted small' }, `${ids.length} shown`),
    h('div', { class: 'lib' }, ids.slice(0, LIB.shown).map((id) => {
      const ex = EXERCISES[id];
      const ok = canDo(id, loc);
      const sub = ok ? null : resolveEx(id, loc);
      return h('article', { class: `tile ${ok ? '' : 'unavailable'}` },
        mediaEl(id, { still: true, hoverPlay: true, cls: 'tile-media' }),
        h('div', { class: 'tile-body' },
          h('div', { class: 'tile-head' }, h('h3', {}, ex.name), h('button', { class: 'quiet', onclick: () => practice(id) }, 'Try 30 s')),
          h('div', { class: 'tile-meta' }, [needsText(id), ex.lib ? null : 'program', ok ? null : sub ? `at ${loc.name}: ${exName(sub)}` : `not at ${loc.name}`].filter(Boolean).join('  ·  ')),
          h('ul', { class: 'cues' }, ex.cues.map((c) => h('li', {}, c)))));
    })),
    ids.length > LIB.shown ? h('div', { class: 'more' }, h('button', { class: 'btn', onclick: () => { LIB.shown += 96; viewLibrary(); } }, `Show more (${ids.length - LIB.shown})`)) : null));
}

// ---------- settings ----------
function viewSettings() {
  const p = prefs();
  const locs = getLocations();
  const save = () => saveLocations();
  const EQ_GROUPS = [['Free weights', ['barbell', 'ezbar', 'dumbbells', 'kettlebell']], ['Fixtures', ['bench', 'pullupbar', 'chair', 'table']], ['Extras', ['rope', 'band', 'ball', 'backpack', 'machines']]];
  const possible = (l) => Object.keys(EXERCISES).filter((id) => canDo(id, l)).length;
  const locCards = locs.map((l, i) => {
    const isDefault = l.id === p.location;
    const count = h('span', { class: 'muted small' });
    const recount = () => { count.textContent = `${l.equipment.length} items  ·  ${possible(l)} of ${Object.keys(EXERCISES).length} exercises possible`; };
    recount();
    return h('div', { class: `loc-card ${isDefault ? 'is-default' : ''}` },
      h('div', { class: 'loc-card-head' },
        h('input', { class: 'loc-name', value: l.name, 'aria-label': 'Location name', oninput: (e) => { l.name = e.target.value; save(); } }),
        isDefault ? h('span', { class: 'tag' }, 'Default') : h('button', { class: 'quiet', onclick: () => { setPref('location', l.id); sessionLoc = null; viewSettings(); } }, 'Make default'),
        h('span', { class: 'loc-actions' },
          h('button', { class: 'quiet', onclick: () => { locs.splice(i + 1, 0, { ...clone(l), id: `loc${Date.now()}`, name: `${l.name} copy` }); save(); viewSettings(); } }, 'Duplicate'),
          locs.length > 1 ? h('button', { class: 'quiet danger', onclick: () => { if (confirm(`Remove ${l.name}?`)) { locs.splice(i, 1); if (isDefault) setPref('location', locs[0].id); save(); viewSettings(); } } }, 'Remove') : null)),
      count,
      EQ_GROUPS.map(([g, ids]) => h('div', { class: 'eq-group' },
        h('span', { class: 'eq-group-name' }, g),
        h('div', { class: 'eq-chips' }, ids.map((eid) => h('button', {
          class: `eq-chip ${l.equipment.includes(eid) ? 'on' : ''}`,
          onclick: (ev) => {
            if (l.equipment.includes(eid)) l.equipment = l.equipment.filter((x) => x !== eid); else l.equipment.push(eid);
            ev.target.classList.toggle('on');
            recount();
            save();
          },
        }, eqName(eid)))))));
  });

  const toggle = (k, label, hint) => h('label', { class: 'check row-check' },
    h('input', { type: 'checkbox', checked: p[k], onchange: (e) => setPref(k, e.target.checked) }), h('span', {}, label, hint ? h('span', { class: 'muted small' }, `  ${hint}`) : null));
  const weekSel = h('select', { onchange: (e) => setPref('week', e.target.value) },
    h('option', { value: 'auto' }, `Automatic (now week ${programWeek(todayISO())})`),
    [1, 2, 3, 4, 5].map((n) => h('option', { value: n }, `Week ${n}`)));
  weekSel.value = String(p.week);

  setView(h('div', { class: 'page narrow' }, topbar('settings'),
    h('div', { class: 'page-head' }, h('h1', { class: 'display small' }, 'Settings')),
    h('section', { class: 'section' },
      h('div', { class: 'section-head' }, h('h2', {}, 'Locations'), h('button', { class: 'quiet', onclick: () => {
        locs.push({ id: `loc${Date.now()}`, name: 'New place', equipment: [] }); save(); viewSettings();
      } }, 'Add location')),
      h('p', { class: 'muted' }, "What's available where. Sessions swap exercises you can't do (bench press becomes push-ups when travelling). The default is where the app starts; switch for today in the top bar."),
      locCards),
    h('section', { class: 'section' },
      h('div', { class: 'section-head' }, h('h2', {}, 'Demonstrations')),
      h('p', { class: 'muted' }, 'Training uses video demonstrations only. Animation comparisons are kept in the separate exercise database.')),
    h('section', { class: 'section' },
      h('div', { class: 'section-head' }, h('h2', {}, 'During a session')),
      toggle('voice', 'Spoken cues', 'exercise names, sides, rest'),
      toggle('beeps', 'Countdown tones', 'last three seconds'),
      toggle('ticks', 'Tempo ticks', 'a soft click on every rep')),
    h('section', { class: 'section' },
      h('div', { class: 'section-head' }, h('h2', {}, 'Program week')),
      h('p', { class: 'muted' }, 'Some exercises progress by week (longer holds, harder variations).'), weekSel),
    h('section', { class: 'section' },
      h('div', { class: 'section-head' }, h('h2', {}, 'Where things live')),
      h('p', { class: 'muted' }, S.vault
        ? `Plan: ${S.vault.plan} in your vault (edit it there, or ask Claude). Logs: Strength Log and Running Log next to it. Routines and settings: Hobbies/Sports/Groundwork in the vault.`
        : `This is the read-only public version. The plan and logs come from the vault${S.exportedAt ? ` (exported ${S.exportedAt})` : ''}; your location and session settings are kept on this device.`))));
}

// ---------- editor ----------
const fmtVal = (v) => (Array.isArray(v) ? v.join(', ') : v ?? '');
const numOr = (x) => (/^\d+(\.\d+)?$/.test(x) ? +x : x);
function parseVal(s) {
  s = String(s).trim();
  if (!s) return undefined;
  if (s.includes(',')) return s.split(',').map((x) => numOr(x.trim())).filter((x) => x !== '');
  return numOr(s);
}
function parseWeeks(s) {
  s = s.trim();
  if (!s) return undefined;
  const out = new Set();
  for (const part of s.split(',')) {
    const m = part.trim().match(/^(\d+)\s*-\s*(\d+)$/);
    if (m) for (let i = +m[1]; i <= +m[2]; i++) out.add(i);
    else if (/^\d+$/.test(part.trim())) out.add(+part.trim());
  }
  return [...out].sort();
}
const fmtWeeks = (w) => (w && w.length ? w.join(',') : '');

function viewEditor(id) {
  const orig = id ? getWorkout(id) : null;
  const w = orig ? clone(orig) : { id: `S${String(Date.now()).slice(-5)}`, name: 'New session', tag: 'Custom', blocks: [{ name: 'Main', rounds: 1, rest: 15, roundRest: 60, items: [{ ex: 'pushup', time: 40 }] }] };
  const exOptions = Object.keys(EXERCISES).filter(hasVideo).sort((a, b) => exName(a).localeCompare(exName(b)));
  const estEl = h('span', { class: 'muted' });
  const updateEst = () => { estEl.textContent = `≈ ${fmtMin(totalSeconds(buildSteps(w, currentWeek(), currentLocation())))}`; };
  const move = (arr, i, d) => { const j = i + d; if (j < 0 || j >= arr.length) return; [arr[i], arr[j]] = [arr[j], arr[i]]; render(); };
  const field = (label, obj, key, attrs = {}) => h('label', { class: 'fld' }, h('span', {}, label),
    h('input', { value: fmtVal(obj[key]), ...attrs, oninput: (e) => { const v = parseVal(e.target.value); if (v === undefined) delete obj[key]; else obj[key] = v; updateEst(); } }));

  const body = h('div');
  function itemRow(b, it, ii) {
    const mode = itemMode(it);
    const amountKey = mode;
    return h('div', { class: 'erow' },
      h('div', { class: 'erow-main' },
        mediaEl(it.ex, { still: true, cls: 'erow-thumb' }),
        h('select', { class: 'ex-sel', onchange: (e) => { it.ex = e.target.value; render(); } },
          h('optgroup', { label: 'Program (video)' }, exOptions.filter((x) => !EXERCISES[x].lib).map((x) => h('option', { value: x, selected: x === it.ex }, exName(x)))),
          ['back', 'core', 'arms', 'upper', 'legs', 'cardio', 'other'].map((t) => h('optgroup', { label: `Library: ${t}` },
            exOptions.filter((x) => EXERCISES[x].lib && EXERCISES[x].tags[0] === t).map((x) => h('option', { value: x, selected: x === it.ex }, exName(x)))))),
        h('select', { onchange: (e) => {
          const amt = it[amountKey];
          delete it.reps; delete it.time; delete it.holds; delete it.hold;
          const m = e.target.value;
          if (m === 'holds') { it.holds = 5; it.hold = 10; } else it[m] = typeof amt === 'number' ? amt : m === 'time' ? 40 : 10;
          render();
        } }, [['time', 'Timed'], ['holds', 'Holds'], ['reps', 'Reps (press Done)']].map(([m, l]) => h('option', { value: m, selected: m === mode }, l))),
        h('span', { class: 'erow-btns' },
          h('button', { class: 'icon', title: 'Move up', onclick: () => move(b.items, ii, -1) }, '↑'),
          h('button', { class: 'icon', title: 'Move down', onclick: () => move(b.items, ii, 1) }, '↓'),
          h('button', { class: 'icon', title: 'Duplicate', onclick: () => { b.items.splice(ii + 1, 0, clone(it)); render(); } }, '+'),
          h('button', { class: 'icon', title: 'Remove', onclick: () => { b.items.splice(ii, 1); render(); } }, '×'))),
      h('div', { class: 'erow-fields' },
        field(mode === 'time' ? 'Seconds' : mode === 'holds' ? 'Holds' : 'Reps', it, amountKey),
        mode === 'holds' ? field('Hold (s)', it, 'hold') : null,
        field('Sets', it, 'sets', { placeholder: '1' }),
        h('label', { class: 'fld' }, h('span', {}, 'Sides'),
          h('select', { onchange: (e) => { if (e.target.value) it.sides = e.target.value; else delete it.sides; updateEst(); } },
            h('option', { value: '', selected: !it.sides }, '—'),
            h('option', { value: 'each', selected: it.sides === 'each' }, 'Left, then right'),
            h('option', { value: 'alt', selected: it.sides === 'alt' }, 'Alternating'))),
        field('Rest after (s)', it, 'rest', { placeholder: String(fmtVal(b.rest)) }),
        h('label', { class: 'fld' }, h('span', {}, 'Weeks'), h('input', { value: fmtWeeks(it.weeks), placeholder: 'all',
          oninput: (e) => { const v = parseWeeks(e.target.value); if (v && v.length) it.weeks = v; else delete it.weeks; updateEst(); } })),
        h('label', { class: 'fld wide' }, h('span', {}, 'Target'), h('input', { value: fmtVal(it.target), placeholder: '~10 slow reps',
          oninput: (e) => { if (e.target.value) it.target = e.target.value; else delete it.target; } })),
        h('label', { class: 'fld wide' }, h('span', {}, 'Note'), h('input', { value: it.note || '',
          oninput: (e) => { if (e.target.value) it.note = e.target.value; else delete it.note; } }))));
  }
  function render() {
    body.replaceChildren(
      ...w.blocks.map((b, bi) => h('section', { class: 'eblock' },
        h('div', { class: 'eblock-head' },
          h('input', { class: 'eblock-name', value: b.name || '', placeholder: 'Block name', oninput: (e) => { b.name = e.target.value; } }),
          field('Rounds', b, 'rounds'),
          field('Rest between (s)', b, 'rest'),
          field('Rest between rounds (s)', b, 'roundRest'),
          h('span', { class: 'erow-btns' },
            h('button', { class: 'icon', onclick: () => move(w.blocks, bi, -1) }, '↑'),
            h('button', { class: 'icon', onclick: () => move(w.blocks, bi, 1) }, '↓'),
            h('button', { class: 'icon', onclick: () => { w.blocks.splice(bi, 1); render(); } }, '×'))),
        b.items.map((it, ii) => itemRow(b, it, ii)),
        h('button', { class: 'quiet', onclick: () => { b.items.push({ ex: 'plank', time: 30 }); render(); } }, '+ Exercise'))),
      h('button', { class: 'quiet', onclick: () => { w.blocks.push({ name: '', rounds: 1, rest: 15, roundRest: 60, items: [] }); render(); } }, '+ Block'));
    updateEst();
  }
  render();

  setView(h('div', { class: 'page narrow' }, topbar(''),
    h('div', { class: 'page-head' },
      h('input', { class: 'display-input', value: w.name, oninput: (e) => { w.name = e.target.value; } }),
      h('p', { class: 'lede' }, estEl, h('span', { class: 'muted' }, '  ·  Numbers can change per program week: "15, 20, 25, 30". Weeks limits an exercise, e.g. "3-5".'))),
    body,
    h('div', { class: 'savebar' },
      h('button', { class: 'btn primary', onclick: () => saveWorkout(w).then(() => { location.hash = '#/'; }) }, 'Save'),
      h('button', { class: 'btn', onclick: () => saveWorkout(w).then(() => { location.hash = `#/play/${encodeURIComponent(w.id)}`; }) }, 'Save & begin'),
      h('a', { class: 'quiet', href: '#/' }, 'Cancel'),
      orig ? h('button', { class: 'quiet danger', onclick: () => { if (confirm(`Delete "${w.name}"? Plan days that use ${w.id} will show it as unknown.`)) deleteWorkout(w.id).then(() => { location.hash = '#/'; }); } }, 'Delete') : null)));
}

// ---------- player ----------
let P = null;
let wakeLock = null;

// Pre-session overview: totals, a timeline of work vs rest, then each block as a card listing its
// exercises with how long, how many sets/sides, and the rest that follows.
function viewPrestart(id) {
  const w = getWorkout(id);
  if (!w) { location.hash = '#/'; return; }
  const week = currentWeek();
  const loc = currentLocation();
  const steps = buildSteps(w, week, loc);
  const work = steps.filter((s) => s.kind === 'ex').reduce((a, s) => a + stepSeconds(s), 0);
  const rest = steps.filter((s) => s.kind === 'rest').reduce((a, s) => a + s.time, 0);
  const nEx = new Set(steps.filter((s) => s.kind === 'ex').map((s) => s.ex)).size;
  const total = work + rest;
  const go = () => startPlayer(w);

  const stat = (n, label) => h('div', { class: 'stat' }, h('span', { class: 'stat-n' }, n), h('span', { class: 'stat-l' }, label));
  const timeline = h('div', { class: 'timeline', title: 'Work (dark) and rest (light), to scale' },
    steps.map((s) => h('i', { class: s.kind === 'rest' ? 'tl-rest' : `tl-work f-${kindOfFocus(w.focus)}`, style: `flex:${stepSeconds(s)}`, title: s.kind === 'rest' ? `${s.label} ${s.time} s` : `${exName(s.ex)}${s.side ? ` (${s.side})` : ''} · ${amountText(s)}` })));

  const blocks = w.blocks.map((b) => {
    const items = b.items.filter((it) => EXERCISES[it.ex] && (!it.weeks || !it.weeks.length || it.weeks.includes(week)))
      .map((it) => ({ ...it, rx: resolveEx(it.ex, loc) })).filter((it) => it.rx);
    if (!items.length) return null;
    const rounds = +wv(b.rounds, week) || 1;
    const bRest = +wv(b.rest, week) || 0;
    const rRest = +wv(b.roundRest, week) || 0;
    return h('section', { class: 'ov-block' },
      h('div', { class: 'ov-block-head' },
        h('h3', {}, b.name || 'Block'),
        h('span', { class: 'muted' }, [rounds > 1 ? `${rounds} rounds` : null, bRest ? `${bRest} s rest between` : null, rounds > 1 && rRest ? `${rRest} s between rounds` : null].filter(Boolean).join('  ·  '))),
      items.map((it) => {
        const mode = itemMode(it);
        const sets = +wv(it.sets, week) || 1;
        const amount = mode === 'time' ? `${wv(it.time, week)} s` : mode === 'holds' ? `${wv(it.holds, week)} × ${wv(it.hold, week)} s` : `${wv(it.reps, week)}`;
        const restAfter = it.rest != null ? +wv(it.rest, week) : bRest;
        return h('div', { class: 'ov-item' },
          mediaEl(it.rx, { still: true, cls: 'ov-thumb' }),
          h('div', { class: 'ov-text' },
            h('div', { class: 'ov-title' }, exName(it.rx)),
            h('div', { class: 'ov-meta' }, [wv(it.target, week), it.rx !== it.ex ? `instead of ${exName(it.ex)}` : null, it.note].filter(Boolean).join('  ·  '))),
          h('div', { class: 'ov-amount' },
            h('span', { class: 'ov-big' }, amount),
            h('span', { class: 'ov-tags' }, [sets > 1 ? `${sets} sets` : null, it.sides === 'each' ? 'each side' : it.sides === 'alt' ? 'alternating' : null, mode === 'holds' ? 'holds' : null, restAfter ? `${restAfter} s rest` : null].filter(Boolean).join('  ·  '))));
      }));
  });

  setView(h('div', { class: 'page narrow' }, topbar(''),
    h('section', { class: 'pre-head' },
      h('div', { class: 'eyebrow pre-eyebrow' }, [w.tag, inProgram(todayISO()) ? `Week ${week}` : null].filter(Boolean).join('  ·  '),
        h('label', { class: 'loc-mini', title: 'Where are you training?' }, '  ·  at ',
          (() => {
            const sel = h('select', { onchange: (e) => { sessionLoc = e.target.value; viewPrestart(id); } }, getLocations().map((l) => h('option', { value: l.id }, l.name)));
            sel.value = loc.id;
            return sel;
          })())),
      h('h1', { class: 'display' }, w.name),
      h('div', { class: 'stats' }, stat(fmtMin(total).replace(' min', ''), 'minutes'), stat(nEx, 'exercises'), stat(fmtMin(work).replace(' min', ''), 'min work'), stat(fmtMin(rest).replace(' min', ''), 'min rest')),
      timeline,
      h('div', { class: 'hero-actions' }, h('button', { class: 'begin', onclick: go }, h('span', { class: 'begin-icon' }), 'Begin'),
        h('span', { class: 'muted small' }, 'Runs on its own  ·  Space pauses  ·  ← → skip  ·  Esc stops')),
      steps.swaps.length ? h('p', { class: 'swaps' }, `At ${loc.name}: `, steps.swaps.map((s, i) => [i ? ', ' : '', `${exName(s.from)} → ${exName(s.to)}`])) : null),
    blocks),
  (e) => { if (e.code === 'Space' || e.code === 'Enter') { e.preventDefault(); go(); } });
}

function startPlayer(w) {
  unlockAudio();
  const week = currentWeek();
  const steps = buildSteps(w, week, currentLocation());
  if (!steps.length) { alert('Nothing to do in this session at this location.'); return; }
  const shell = h('div', { class: 'player' });
  setView(shell, playerKeys);
  P = { w, week, steps, i: 0, paused: false, startedAt: Date.now(), log: [], shell, timer: null, last: performance.now(), idleT: null };
  P.timer = setInterval(tick, 100);
  shell.addEventListener('mousemove', wake);
  wake();
  try { navigator.wakeLock && navigator.wakeLock.request('screen').then((l) => { wakeLock = l; }).catch(() => {}); } catch { /* unsupported */ }
  enterStep(0);
}

function wake() {
  if (!P) return;
  P.shell.classList.remove('idle');
  clearTimeout(P.idleT);
  P.idleT = setTimeout(() => P && P.shell.classList.add('idle'), 2500);
}

function stopEngine() {
  if (!P) return;
  clearInterval(P.timer);
  clearTimeout(P.idleT);
  if (window.speechSynthesis) speechSynthesis.cancel();
  if (wakeLock) { wakeLock.release().catch(() => {}); wakeLock = null; }
  P = null;
}

function stepIntro(s) {
  if (s.kind === 'rest') {
    const n = s.next;
    if (s.label === 'Switch sides') return `Switch sides. ${cap(n.side)} side.`;
    const nm = `${exName(n.ex)}${n.side ? `, ${n.side} side` : ''}`;
    return s.label === 'Get ready' ? `Get ready. ${nm}.` : `Rest, ${s.time} seconds. Next: ${nm}.`;
  }
  const amt = s.mode === 'time' ? `${s.time} seconds` : s.mode === 'holds' ? `${s.holds} holds of ${s.hold} seconds` : typeof s.reps === 'number' ? `${s.reps} reps` : s.reps;
  return `${exName(s.ex)}${s.side ? `, ${s.side} side` : ''}. ${amt}. ${s.mode === 'holds' ? 'Hold.' : 'Go.'}`;
}

function enterStep(i) {
  P.i = i;
  const s = P.steps[i];
  P.elapsed = 0;
  P.remain = s.kind === 'rest' ? s.time : s.mode === 'time' ? s.time : s.mode === 'holds' ? s.hold : null;
  P.hold = 1;
  P.holdPhase = 'hold';
  P.repCount = 0;
  P.last = performance.now();
  if (s.kind === 'ex') beep(880, 0.35, 0.2);
  say(stepIntro(s));
  renderPlayer();
}

function advance(skipped = false) {
  const s = P.steps[P.i];
  if (s.kind === 'ex') P.log.push({ ex: s.ex, side: s.side, amount: amountText(s), secs: P.elapsed, skipped });
  if (P.i + 1 < P.steps.length) enterStep(P.i + 1);
  else finish();
}

function goBack() {
  const s = P.steps[P.i];
  if (s.kind === 'ex' && P.elapsed > 3) return enterStep(P.i);
  for (let j = P.i - 1; j >= 0; j--) {
    if (P.steps[j].kind === 'ex') { P.log.pop(); return enterStep(j > 0 && P.steps[j - 1].kind === 'rest' ? j - 1 : j); }
  }
}
function skip() {
  // skip rests straight to the exercise; skip exercises to the next rest
  advance(P.steps[P.i].kind === 'ex');
}
function togglePause() {
  P.paused = !P.paused;
  if (P.paused && window.speechSynthesis) speechSynthesis.cancel();
  P.shell.classList.toggle('paused', P.paused);
  const btn = P.shell.querySelector('#pausebtn');
  if (btn) btn.textContent = P.paused ? 'Resume' : 'Pause';
}

function tick() {
  if (!P) return;
  const now = performance.now();
  const dt = (now - P.last) / 1000;
  P.last = now;
  if (P.paused) return;
  P.elapsed += dt;
  const s = P.steps[P.i];
  if (s.kind === 'ex' && s.mode === 'time' && s.pace && prefs().ticks) {
    const reps = Math.floor(P.elapsed / s.pace);
    if (reps > P.repCount) { P.repCount = reps; tone(1400, 0.04, 0.06); }
  }
  if (P.remain != null) {
    const before = P.remain;
    P.remain -= dt;
    const countdown = !(s.kind === 'ex' && s.mode === 'holds' && P.holdPhase === 'relax');
    for (const n of [3, 2, 1]) if (countdown && before > n && P.remain <= n) beep(660, 0.12);
    if (P.remain <= 0) {
      if (s.kind === 'ex' && s.mode === 'holds') {
        if (P.holdPhase === 'hold' && P.hold < s.holds) { P.holdPhase = 'relax'; P.remain = s.relax; beep(520, 0.2); say('Relax'); }
        else if (P.holdPhase === 'relax') { P.hold++; P.holdPhase = 'hold'; P.remain = s.hold; beep(880, 0.2); say(`Hold ${P.hold}`); }
        else { beep(990, 0.4); advance(); return; }
      } else { if (s.kind === 'ex') beep(990, 0.4); advance(); return; }
    }
  }
  updateLive();
}

function playerKeys(e) {
  if (!P) return;
  const s = P.steps[P.i];
  wake();
  if (e.code === 'Space' || e.code === 'Enter') {
    e.preventDefault();
    if (s.kind === 'ex' && s.mode === 'reps' && !P.paused) { beep(990, 0.2); advance(); } else togglePause();
  } else if (e.code === 'ArrowRight') { e.preventDefault(); skip(); }
  else if (e.code === 'ArrowLeft') { e.preventDefault(); goBack(); }
  else if (e.code === 'Escape') exitPlayer();
}

function exitPlayer() {
  if (P && !confirm('Stop this session?')) return;
  stopEngine();
  if (location.hash === '#/') route();
  else location.hash = '#/';
}

function remainingSeconds() {
  let t = P.remain != null ? Math.max(0, P.remain) : 0;
  const s = P.steps[P.i];
  if (s.kind === 'ex' && s.mode === 'holds') t += (s.holds - P.hold) * (s.hold + s.relax) + (P.holdPhase === 'hold' ? s.relax : 0);
  if (s.kind === 'ex' && s.mode === 'reps') t += Math.max(0, stepSeconds(s) - P.elapsed);
  for (let j = P.i + 1; j < P.steps.length; j++) t += stepSeconds(P.steps[j]);
  return t;
}

const RING_R = 54;
const RING_C = 2 * Math.PI * RING_R;

function renderPlayer() {
  stopMedia();
  const s = P.steps[P.i];
  const isRest = s.kind === 'rest';
  const ex = isRest ? s.next : s;
  const def = EXERCISES[ex.ex];
  const exSteps = P.steps.filter((x) => x.kind === 'ex');
  const exIdx = exSteps.indexOf(ex) + 1;
  const nextEx = isRest ? null : P.steps.slice(P.i + 1).find((x) => x.kind === 'ex');
  const meta = [ex.rounds > 1 ? `Round ${ex.round} of ${ex.rounds}` : null, ex.sets > 1 ? `Set ${ex.set} of ${ex.sets}` : null].filter(Boolean).join('  ·  ');

  const ring = svgEl('ring');
  ring.setAttribute('viewBox', '0 0 120 120');
  ring.innerHTML = `<circle cx="60" cy="60" r="${RING_R}" class="ring-track"/><circle cx="60" cy="60" r="${RING_R}" class="ring-arc" id="arc" stroke-dasharray="${RING_C}" stroke-dashoffset="0" transform="rotate(-90 60 60)"/>`;

  P.shell.className = `player ${isRest ? 'is-rest' : 'is-work'}${P.paused ? ' paused' : ''}`;
  P.shell.replaceChildren(
    h('div', { class: 'p-progress' }, h('i', { id: 'pbar' })),
    h('header', { class: 'p-top' },
      h('span', { class: 'p-crumb' }, P.w.name, h('span', { class: 'muted' }, `  ·  ${exIdx} of ${exSteps.length}`)),
      h('span', { class: 'muted', id: 'premain' }),
      h('button', { class: 'p-close', title: 'Stop (Esc)', onclick: exitPlayer }, '×')),
    h('main', { class: 'p-stage' },
      h('div', { class: 'p-figure' }, mediaEl(ex.ex, { pace: ex.mode === 'time' ? ex.pace : null, cls: 'p-media' })),
      h('aside', { class: 'p-side' },
        h('div', { class: 'p-kicker' }, isRest ? (s.label.startsWith('Round') ? 'Round rest' : s.label === 'Rest' ? 'Recover' : 'Prepare') : meta || ex.block || ' '),
        isRest
          ? h('h1', { class: 'p-title p-rest-title' }, s.label.startsWith('Round') ? `Rest · ${s.label.toLowerCase()} next` : s.label)
          : h('h1', { class: 'p-title' }, def.name, ex.side ? h('em', {}, ` ${ex.side}`) : null),
        isRest
          ? h('div', { class: 'p-upnext' }, h('span', { class: 'muted' }, 'Up next  '), def.name, ex.side ? h('em', {}, ` ${ex.side}`) : null, h('span', { class: 'muted' }, `  ·  ${amountText(ex)}`))
          : h('div', { class: 'p-target' }, ex.target || ' '),
        h('div', { class: 'p-ring' }, ring, h('div', { class: 'p-num-wrap' }, h('div', { class: 'p-num', id: 'big' }), h('div', { class: 'p-sub', id: 'sub' }))),
        !isRest && s.mode === 'reps' ? h('button', { class: 'begin small', onclick: () => { beep(990, 0.2); advance(); } }, 'Done') : null,
        isRest ? null : h('ul', { class: 'p-cues' }, def.cues.map((c) => h('li', {}, c))),
        ex.note ? h('p', { class: 'p-note' }, ex.note) : null,
        ex.from ? h('p', { class: 'p-swap' }, `Instead of ${exName(ex.from)}`) : null)),
    h('footer', { class: 'p-foot' },
      h('div', { class: 'p-controls' },
        h('button', { onclick: goBack, title: 'Back (←)' }, '←'),
        h('button', { id: 'pausebtn', onclick: togglePause }, P.paused ? 'Resume' : 'Pause'),
        h('button', { onclick: skip, title: 'Skip (→)' }, '→')),
      nextEx ? h('div', { class: 'p-next' }, h('span', { class: 'muted' }, 'Next'), ` ${exName(nextEx.ex)}${nextEx.side ? ` · ${nextEx.side}` : ''}`) : h('div')));
  updateLive();
}

function updateLive() {
  if (!P) return;
  const s = P.steps[P.i];
  const big = document.getElementById('big');
  const sub = document.getElementById('sub');
  const arc = document.getElementById('arc');
  if (!big) return;
  let frac = 0;
  if (s.kind === 'ex' && s.mode === 'reps') {
    big.textContent = typeof s.reps === 'number' ? s.reps : '—';
    sub.textContent = typeof s.reps === 'number' ? (s.alt ? 'per side' : 'reps') : s.reps;
  } else if (s.kind === 'ex' && s.mode === 'holds') {
    const relax = P.holdPhase === 'relax';
    big.textContent = Math.ceil(Math.max(0, P.remain));
    sub.textContent = relax ? 'relax' : `hold ${P.hold} of ${s.holds}`;
    frac = 1 - Math.max(0, P.remain) / (relax ? s.relax : s.hold);
    P.shell.classList.toggle('is-relax', relax);
  } else {
    const long = P.remain >= 60;
    big.textContent = long ? fmtTime(P.remain) : Math.ceil(Math.max(0, P.remain));
    sub.textContent = s.kind === 'rest' ? 'rest' : long ? '' : 'seconds';
    frac = 1 - Math.max(0, P.remain) / (s.time || 1);
  }
  arc.setAttribute('stroke-dashoffset', String(RING_C * frac));
  document.getElementById('pbar').style.width = `${(100 * P.i) / P.steps.length}%`;
  document.getElementById('premain').textContent = `${fmtTime(remainingSeconds())} left`;
}

function finish() {
  const w = P.w;
  const secs = Math.round((Date.now() - P.startedAt) / 1000);
  const log = P.log;
  const week = P.week;
  const practice = w.id.startsWith('practice-');
  stopEngine();
  say('Done. Well done.');
  beep(990, 0.15); setTimeout(() => beep(1320, 0.35), 180);

  // "Side plank ×6, ✕ Bird dog": consecutive repeats collapse, skipped ones are marked
  const parts = [];
  for (const l of log) {
    const label = `${l.skipped ? '✕ ' : ''}${exName(l.ex)}`;
    const last = parts[parts.length - 1];
    if (last && last.label === label) last.n++; else parts.push({ label, n: 1 });
  }
  const done = parts.map((p) => (p.n > 1 ? `${p.label} ×${p.n}` : p.label)).join(', ');
  const entry = { date: todayISO(), session: `${w.name} (${w.id})`, minutes: Math.max(1, Math.round(secs / 60)), location: currentLocation().name, done, note: inProgram(todayISO()) ? `week ${week}` : '' };
  const shouldLog = !S.readonly && !practice && log.some((l) => !l.skipped);
  let saved = !shouldLog;
  const note = h('textarea', { class: 'note-input', rows: 2, placeholder: w.id === 'TEST' ? 'Results, e.g. push-ups 32, pull-ups 6, side plank 60/55 s, plank 95 s, bridge 15/14' : 'Anything worth noting? (optional)' });
  const status = h('span', { class: 'muted small' });

  // Garmin-style rating: perceived effort 1–10 and how you felt.
  const EFFORT = ['', 'Very light', 'Very light', 'Light', 'Light', 'Moderate', 'Moderate', 'Hard', 'Hard', 'Very hard', 'Maximum'];
  const FEEL = ['Very weak', 'Weak', 'Normal', 'Strong', 'Very strong'];
  const rating = { effort: null, feel: null };
  const effortLabel = h('span', { class: 'rate-label' }, 'How hard was it?');
  const effortRow = h('div', { class: 'rate-scale' }, [...Array(10)].map((_, i) => h('button', {
    class: 'rate-n', onclick: (ev) => {
      rating.effort = i + 1;
      effortLabel.textContent = `${i + 1}  ·  ${EFFORT[i + 1]}`;
      effortRow.querySelectorAll('.rate-n').forEach((b, k) => b.classList.toggle('on', k <= i));
    },
  }, i + 1)));
  const feelRow = h('div', { class: 'rate-feel' }, FEEL.map((f) => h('button', {
    class: 'pill', onclick: (ev) => { rating.feel = f; feelRow.querySelectorAll('.pill').forEach((b) => b.classList.toggle('on', b === ev.target)); },
  }, f)));
  const ratingBox = h('div', { class: 'rating' },
    h('div', { class: 'rate-row' }, h('div', { class: 'eyebrow' }, 'Effort'), effortRow, effortLabel),
    h('div', { class: 'rate-row' }, h('div', { class: 'eyebrow' }, 'How did you feel?'), feelRow));

  const save = (beacon = false) => {
    if (saved) return Promise.resolve();
    saved = true;
    const e = { ...entry, effort: rating.effort ? `${rating.effort}/10` : '', feel: rating.feel || '', note: [entry.note, note.value.trim()].filter(Boolean).join(' · ') };
    if (beacon) { navigator.sendBeacon('api/log', new Blob([JSON.stringify(e)], { type: 'application/json' })); return Promise.resolve(); }
    status.textContent = 'Saving…';
    return fetch('api/log', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(e) })
      .then(() => { status.textContent = 'Saved to Strength Log'; S.strength.unshift({ ...e }); });
  };
  const leave = () => save().then(() => { location.hash = '#/'; });
  window.addEventListener('pagehide', () => save(true), { once: true });
  window.addEventListener('hashchange', () => save(), { once: true });

  setView(h('div', { class: 'page narrow' }, topbar(''),
    h('section', { class: 'hero compact' },
      h('div', { class: 'eyebrow' }, practice ? 'Practice' : 'Session complete'),
      h('h1', { class: 'display' }, 'Well done.'),
      h('p', { class: 'lede' }, `${w.name}  ·  ${fmtMin(secs)}`),
      shouldLog ? ratingBox : null,
      shouldLog ? h('div', { class: 'finish-note' }, note) : null,
      h('div', { class: 'hero-actions' },
        h('button', { class: 'btn primary', onclick: leave }, shouldLog ? 'Save & back to today' : 'Back to today'),
        status)),
    h('div', { class: 'log' }, log.map((l) => h('div', { class: `log-row ${l.skipped ? 'skipped' : ''}` },
      h('span', {}, exName(l.ex), l.side ? h('span', { class: 'muted' }, ` · ${l.side}`) : null),
      h('span', { class: 'muted' }, l.skipped ? 'skipped' : fmtTime(l.secs)))))));
}

// ---------- boot ----------
Promise.all([
  refreshState(),
  fetch('library/exercises.json').then((r) => r.json()).then(loadLibrary).catch(() => {}),
]).then(route).catch((e) => {
  app().replaceChildren(h('div', { class: 'page narrow' }, h('section', { class: 'hero' },
    h('h1', { class: 'display small' }, 'Server not reachable'),
    h('p', { class: 'lede' }, 'Groundwork needs its local server (server.py). It normally starts at login; run ', h('code', {}, 'python3 ~/Practice/server.py'), ' to start it by hand.'),
    h('p', { class: 'muted small' }, String(e)))));
});
// Pick up plan/log edits made in the vault when coming back to the app.
window.addEventListener('focus', async () => {
  if (P || !S || !/^#?\/?$/.test(location.hash.replace('#/', ''))) return;
  await refreshState();
  route();
});
