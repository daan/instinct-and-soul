// Tracer — D3 timeline with lanes (events / tokens / sizes), chat below, click-sync between them.
// Sim runs also get a transport (continuous playhead) and a small dancer/device/sound inset.

import { createSkeleton } from "/viewers/lib/skeleton-mini.js";
import { createDevice, volumeAt } from "/viewers/lib/device.js";

const KIND_META = {
  "instinct-msg": { label: "instinct", color: "#4a7", radius: 3 },
  "operator":     { label: "operator", color: "#2a9", radius: 3 },
  "intent":       { label: "soul",     color: "#74a", radius: 6 },
  "failed":       { label: "failed",   color: "#c33", radius: 6 },
  "crash":        { label: "crash",    color: "#911", radius: 6 },
  "mem":          { label: "mem",      color: "#999", radius: 3 },
};

const traceParam = new URLSearchParams(window.location.search).get("trace");
const traceUrl = traceParam ? `/${traceParam}/trace.json` : "./sample-trace.json";

async function loadTrace(url) {
  // A re-bake may be in flight (a missing file → 404, or — before atomic
  // writes — a truncated one → JSON parse error). Retry briefly, and on real
  // failure paint a message instead of leaving the page silently blank.
  let lastErr;
  for (let attempt = 0; attempt < 6; attempt++) {
    try {
      const r = await fetch(url, { cache: "no-store" });
      if (!r.ok) throw new Error(`${url} → ${r.status}`);
      return await r.json();        // throws on a partial / invalid file
    } catch (e) {
      lastErr = e;
      await new Promise(res => setTimeout(res, 500));
    }
  }
  throw lastErr;
}

let trace;
try {
  trace = await loadTrace(traceUrl);
} catch (e) {
  document.body.innerHTML =
    `<div style="padding:2rem;font-family:monospace;color:#c33">` +
    `couldn't load trace: ${e.message}<br>` +
    `the run may still be baking — refresh in a moment, or re-bake.</div>`;
  throw e;
}

// Grow the timeline (CSS) before we measure the SVG, when there's an IMU lane.
if (trace.stage && trace.stage.imu) document.body.classList.add("has-imu");

const t0 = trace.session_start;
const events = trace.events.map(e => ({ ...e, t: e.t - t0, t_unix: e.t }));
const versions = trace.versions || { instinct: [], experience: [] };
versions.instinct.forEach(v => { v.t = v.ts - t0; });
versions.experience.forEach(v => { v.t = v.ts - t0; });

const stageDurSec = trace.stage ? (trace.stage.duration_ms || 0) / 1000 : 0;
const eventsDurSec = events.length ? Math.max(...events.map(e => e.t)) + 2 : 0;
const sessionDuration = Math.max(eventsDurSec, stageDurSec) || 60;

// ---------- Header + legend ----------
document.getElementById("session-title").textContent =
  `${trace.session_id} · ${events.length} events · ${sessionDuration.toFixed(0)}s`;

const legendEl = document.getElementById("legend");
const presentKinds = new Set(events.map(e => e.kind));
for (const [kind, meta] of Object.entries(KIND_META)) {
  if (!presentKinds.has(kind)) continue;
  const item = document.createElement("div");
  item.className = "legend-item";
  const sw = document.createElement("span");
  sw.className = "legend-swatch";
  sw.style.background = meta.color;
  item.appendChild(sw);
  const count = events.filter(e => e.kind === kind).length;
  item.appendChild(document.createTextNode(`${meta.label} (${count})`));
  legendEl.appendChild(item);
}

// ---------- State ----------
const state = {
  timeScale: null,
  playheadTime: null,
  selectedEventId: null,
};
const subscribers = [];
function setState(updates) {
  Object.assign(state, updates);
  subscribers.forEach(fn => fn(state));
}
function subscribe(fn) { subscribers.push(fn); fn(state); }

// ---------- SVG layout ----------
const svg = d3.select("#timeline");
const { width, height } = svg.node().getBoundingClientRect();
svg.attr("viewBox", `0 0 ${width} ${height}`);
svg.append("rect").attr("class", "zoom-surface").attr("width", width).attr("height", height);

const LAYOUT = {
  axisY: 30,
  events:   { top:  50, bottom: 115, instinctY:  70, soulY: 100 },
  tokens:   { top: 130, bottom: 170 },
  latency:  { top: 185, bottom: 225 },
  sizes:    { top: 240, bottom: 300 },
  accel:    { top: 318, bottom: 360 },
  gyro:     { top: 378, bottom: 420 },
};
const hasImu = !!(trace.stage && trace.stage.imu);
const TIMELINE_BOTTOM = hasImu ? LAYOUT.gyro.bottom : LAYOUT.sizes.bottom;
const margin = { left: 70, right: 30 };  // left wider for lane labels

// Faint dividers between lanes
const dividers = [LAYOUT.events.bottom + 5, LAYOUT.tokens.bottom + 5, LAYOUT.latency.bottom + 5];
if (hasImu) dividers.push(LAYOUT.sizes.bottom + 5, LAYOUT.accel.bottom + 9);
dividers.forEach(y => {
  svg.append("line").attr("class", "lane-divider")
    .attr("x1", 0).attr("x2", width).attr("y1", y).attr("y2", y);
});

// Clip lane plots to the plot area so zoomed-in lines don't spill over labels.
svg.append("defs").append("clipPath").attr("id", "plot-clip")
  .append("rect")
  .attr("x", margin.left).attr("y", 0)
  .attr("width", width - margin.right - margin.left).attr("height", height);

// Lane labels (static, left side)
function addLabel(x, y, text) {
  svg.append("text").attr("class", "lane-label").attr("x", x).attr("y", y).text(text);
}
addLabel(6, LAYOUT.events.instinctY + 3, "instinct");
addLabel(6, LAYOUT.events.soulY + 3,     "soul");
addLabel(6, LAYOUT.tokens.top + 12,      "tokens");
addLabel(6, LAYOUT.latency.top + 12,     "latency");
addLabel(6, LAYOUT.sizes.top + 12,       "lines");
if (hasImu) {
  addLabel(6, (LAYOUT.accel.top + LAYOUT.accel.bottom) / 2, "accel");
  addLabel(6, (LAYOUT.gyro.top + LAYOUT.gyro.bottom) / 2,   "gyro");
}

// Lane groups
const axisGroup     = svg.append("g").attr("class", "axis").attr("transform", `translate(0, ${LAYOUT.axisY})`);
const linesG        = svg.append("g").attr("class", "batch-lines");
const eventsG       = svg.append("g").attr("class", "events");
const tokensG       = svg.append("g").attr("class", "tokens-lane");
const latencyG      = svg.append("g").attr("class", "latency-lane");
const sizesG        = svg.append("g").attr("class", "sizes-lane");
const accelG        = svg.append("g").attr("class", "imu-lane accel-lane");
const gyroG         = svg.append("g").attr("class", "imu-lane gyro-lane");
const playheadGroup = svg.append("g").attr("class", "playhead-group");

const baseTimeScale = d3.scaleLinear()
  .domain([0, sessionDuration])
  .range([margin.left, width - margin.right]);
setState({ timeScale: baseTimeScale });

// ---------- Axis ----------
function formatSeconds(s) {
  const minutes = Math.floor(s / 60);
  const seconds = s - minutes * 60;
  const ticks = state.timeScale.ticks(10);
  const gap = ticks.length > 1 ? ticks[1] - ticks[0] : 1;
  if (gap < 1)  return `${minutes}:${seconds.toFixed(2).padStart(5, "0")}`;
  if (gap < 60) return `${minutes}:${Math.round(seconds).toString().padStart(2, "0")}`;
  return `${minutes}:00`;
}
function renderAxis(state) {
  axisGroup.call(d3.axisBottom(state.timeScale).ticks(10).tickFormat(formatSeconds));
}

// ---------- Events lane ----------
function laneY(kind) {
  return (kind === "intent" || kind === "failed") ? LAYOUT.events.soulY : LAYOUT.events.instinctY;
}

function renderEvents(state) {
  linesG.selectAll("*").remove();
  eventsG.selectAll("*").remove();
  const [tMin, tMax] = state.timeScale.domain();
  const visible = events.filter(e => e.t >= tMin && e.t <= tMax);

  // batches keyed by ref_seq — dropped messages don't belong to any batch
  // (they were never consumed by a reflection) so we skip them here.
  const batches = new Map();
  visible.forEach(e => {
    if (e.payload?.dropped) return;
    const ref = e.payload?.ref_seq;
    if (ref == null) return;
    if (!batches.has(ref)) batches.set(ref, { msgs: [], intent: null });
    const b = batches.get(ref);
    if (e.kind === "intent" || e.kind === "failed") b.intent = e;
    else b.msgs.push(e);
  });
  batches.forEach(b => b.msgs.sort((a, b) => a.t - b.t));

  // polylines per batch (under dots)
  batches.forEach(b => {
    const pts = [];
    b.msgs.forEach(m => pts.push([state.timeScale(m.t), LAYOUT.events.instinctY]));
    if (b.intent) pts.push([state.timeScale(b.intent.t), LAYOUT.events.soulY]);
    if (pts.length < 2) return;
    const d = "M" + pts.map(p => `${p[0]},${p[1]}`).join(" L");
    linesG.append("path")
      .attr("class", "batch-line" + (b.intent?.kind === "failed" ? " failed" : ""))
      .attr("d", d);
  });

  // dots
  const groups = eventsG.selectAll("g.event")
    .data(visible, d => d.id)
    .enter()
    .append("g")
    .attr("class", d => {
      const cls = ["event", d.kind];
      if (d.kind === "intent" &&
          (d.payload.instinct_changed || d.payload.experience_changed)) {
        cls.push("changed");
      }
      if (d.payload?.dropped) cls.push("dropped");
      if (d.id === state.selectedEventId) cls.push("selected");
      return cls.join(" ");
    })
    .attr("transform", d => `translate(${state.timeScale(d.t)}, ${laneY(d.kind)})`)
    .on("click", (event, d) => {
      setState({ selectedEventId: d.id, playheadTime: d.t });
    });

  groups.each(function(d) {
    const sel = d3.select(this);
    const meta = KIND_META[d.kind];
    if (d.kind === "crash") {
      const r = meta.radius;
      sel.append("path").attr("d", `M0,${-r} L${r},0 L0,${r} L${-r},0 Z`);
    } else {
      sel.append("circle").attr("r", meta.radius);
    }
  });
}

// ---------- Tokens lane ----------
function totalTokens(u) {
  return (u.input_tokens || 0)
       + (u.cache_read_input_tokens || 0)
       + (u.cache_creation_input_tokens || 0)
       + (u.output_tokens || 0);
}
const intentsWithUsage = events.filter(e => e.kind === "intent" && e.payload.usage);
const maxTokens = intentsWithUsage.length
  ? Math.max(...intentsWithUsage.map(e => totalTokens(e.payload.usage)))
  : 0;
const tokenYScale = d3.scaleLinear()
  .domain([0, Math.max(maxTokens, 1)])
  .range([LAYOUT.tokens.bottom, LAYOUT.tokens.top]);

function renderTokens(state) {
  tokensG.selectAll("*").remove();
  if (intentsWithUsage.length === 0) {
    tokensG.append("text").attr("class", "empty-lane-note")
      .attr("x", margin.left).attr("y", (LAYOUT.tokens.top + LAYOUT.tokens.bottom) / 2 + 4)
      .text("(this session has no usage data)");
    return;
  }
  const [tMin, tMax] = state.timeScale.domain();
  const visible = intentsWithUsage.filter(e => e.t >= tMin && e.t <= tMax);
  tokensG.selectAll("rect")
    .data(visible)
    .enter()
    .append("rect")
    .attr("class", "token-bar")
    .attr("x", d => state.timeScale(d.t) - 2)
    .attr("width", 4)
    .attr("y", d => tokenYScale(totalTokens(d.payload.usage)))
    .attr("height", d => LAYOUT.tokens.bottom - tokenYScale(totalTokens(d.payload.usage)));
}

// ---------- Latency lane ----------
const reflectionsWithLatency = events.filter(e =>
  (e.kind === "intent" || e.kind === "failed") && e.payload.latency_s != null);
const maxLatency = reflectionsWithLatency.length
  ? Math.max(...reflectionsWithLatency.map(e => e.payload.latency_s))
  : 0;
const latencyYScale = d3.scaleLinear()
  .domain([0, Math.max(maxLatency, 1)])
  .range([LAYOUT.latency.bottom, LAYOUT.latency.top]);

function renderLatency(state) {
  latencyG.selectAll("*").remove();
  if (reflectionsWithLatency.length === 0) {
    latencyG.append("text").attr("class", "empty-lane-note")
      .attr("x", margin.left).attr("y", (LAYOUT.latency.top + LAYOUT.latency.bottom) / 2 + 4)
      .text("(no latency data — spine recorded started_at after May 26)");
    return;
  }
  const [tMin, tMax] = state.timeScale.domain();
  const visible = reflectionsWithLatency.filter(e => e.t >= tMin && e.t <= tMax);
  latencyG.selectAll("rect")
    .data(visible)
    .enter()
    .append("rect")
    .attr("class", d => "latency-bar" + (d.kind === "failed" ? " failed" : ""))
    .attr("x", d => state.timeScale(d.t) - 2)
    .attr("width", 4)
    .attr("y", d => latencyYScale(d.payload.latency_s))
    .attr("height", d => LAYOUT.latency.bottom - latencyYScale(d.payload.latency_s));
  latencyG.append("text").attr("class", "empty-lane-note")
    .attr("x", width - margin.right).attr("y", LAYOUT.latency.top - 2)
    .attr("text-anchor", "end")
    .text(`0–${maxLatency.toFixed(1)}s`);
}

// ---------- Sizes lane ----------
const allLines = [
  ...versions.instinct.map(v => v.lines),
  ...versions.experience.map(v => v.lines),
];
const maxLines = allLines.length ? Math.max(...allLines) : 1;
const sizeYScale = d3.scaleLinear()
  .domain([0, maxLines])
  .range([LAYOUT.sizes.bottom, LAYOUT.sizes.top]);

function renderSizes(state) {
  sizesG.selectAll("*").remove();
  function plotLine(vs, klass) {
    if (vs.length === 0) return;
    // extend the last segment to the session end so the step is visible
    const data = vs.map(v => ({ t: v.t, lines: v.lines }));
    data.push({ t: sessionDuration, lines: data[data.length - 1].lines });
    const line = d3.line()
      .x(d => state.timeScale(d.t))
      .y(d => sizeYScale(d.lines))
      .curve(d3.curveStepAfter);
    sizesG.append("path").attr("class", `size-line ${klass}`).attr("d", line(data));
  }
  plotLine(versions.instinct,   "instinct");
  plotLine(versions.experience, "experience");

  // tiny inline legend with current max for orientation
  sizesG.append("text").attr("class", "empty-lane-note")
    .attr("x", width - margin.right).attr("y", LAYOUT.sizes.top - 2)
    .attr("text-anchor", "end")
    .text(`0–${maxLines} lines`);
}

// ---------- IMU lanes (accel / gyro) ----------
const imu = hasImu ? trace.stage.imu : null;
const AX = ["x", "y", "z"];
let accelSeries = [], gyroSeries = [], accelYScale = null, gyroYScale = null;
if (imu) {
  const series = (arr, a) => imu.ms.map((m, i) => ({ t: m / 1000, v: arr[i][a] }));
  accelSeries = AX.map((_, a) => series(imu.acc, a));
  gyroSeries  = AX.map((_, a) => series(imu.gyro, a));
  const maxAbs = (rows) => Math.max(1e-6, ...rows.map(r => Math.max(Math.abs(r[0]), Math.abs(r[1]), Math.abs(r[2]))));
  accelYScale = d3.scaleLinear().domain([-maxAbs(imu.acc), maxAbs(imu.acc)]).range([LAYOUT.accel.bottom, LAYOUT.accel.top]);
  gyroYScale  = d3.scaleLinear().domain([-maxAbs(imu.gyro), maxAbs(imu.gyro)]).range([LAYOUT.gyro.bottom, LAYOUT.gyro.top]);
}
function drawBand(group, seriesByAxis, yScale, state) {
  group.selectAll("*").remove();
  group.append("line").attr("class", "imu-zero")
    .attr("x1", margin.left).attr("x2", width - margin.right)
    .attr("y1", yScale(0)).attr("y2", yScale(0));
  const line = d3.line().x(d => state.timeScale(d.t)).y(d => yScale(d.v));
  seriesByAxis.forEach((pts, a) => {
    group.append("path").attr("class", `imu-line ${AX[a]}`)
      .attr("clip-path", "url(#plot-clip)").attr("d", line(pts));
  });
}
function renderImu(state) {
  if (!imu) return;
  drawBand(accelG, accelSeries, accelYScale, state);
  drawBand(gyroG, gyroSeries, gyroYScale, state);
}

// ---------- Playhead ----------
function renderPlayhead(state) {
  playheadGroup.selectAll("*").remove();
  if (state.playheadTime == null) return;
  const x = state.timeScale(state.playheadTime);
  const [xMin, xMax] = state.timeScale.range();
  if (x < xMin - 5 || x > xMax + 5) return;
  playheadGroup.append("line")
    .attr("class", "playhead")
    .attr("x1", x).attr("x2", x)
    .attr("y1", LAYOUT.axisY + 5).attr("y2", TIMELINE_BOTTOM + 5);
}



// ---------- Zoom ----------
const zoom = d3.zoom()
  .scaleExtent([1, 500])
  .translateExtent([[0, 0], [width, height]])
  .extent([[0, 0], [width, height]])
  .on("zoom", (event) => {
    setState({ timeScale: event.transform.rescaleX(baseTimeScale) });
  });
svg.call(zoom);

// Auto-pan the timeline (option B): only when the target time is outside
// the visible domain (with 5% margin). Pan only — never re-zoom.
function panToTimeIfNeeded(t) {
  const [tMin, tMax] = state.timeScale.domain();
  const m = (tMax - tMin) * 0.05;
  if (t >= tMin + m && t <= tMax - m) return;
  const transform = d3.zoomTransform(svg.node());
  const k = transform.k;
  const centerX = (margin.left + (width - margin.right)) / 2;
  const tx = centerX - k * baseTimeScale(t);
  const newTransform = d3.zoomIdentity.translate(tx, 0).scale(k);
  svg.transition().duration(250).call(zoom.transform, newTransform);
}

// ---------- Chat ----------
const chatEl = document.getElementById("chat");
const chatRows = new Map();

const REF_COLORS = ["#a8c0d8", "#bcd4a8", "#d8c4a4", "#c4a4d4"];
function refColor(seq) {
  if (seq == null) return null;
  return REF_COLORS[seq % REF_COLORS.length];
}

function renderChatOnce() {
  chatEl.innerHTML = "";
  chatRows.clear();
  events.forEach((ev, idx) => {
    const row = document.createElement("div");
    row.className = `chat-row ${ev.kind}` + (ev.payload?.dropped ? " dropped" : "");
    row.dataset.id = ev.id;
    const c = refColor(ev.payload?.ref_seq);
    if (c) row.style.setProperty("--ref-color", c);

    const ts = document.createElement("div");
    ts.className = "chat-ts";
    ts.textContent = ev.t.toFixed(2);
    ts.title = new Date(ev.t_unix * 1000).toISOString();
    row.appendChild(ts);

    const kind = document.createElement("div");
    kind.className = "chat-kind";
    kind.textContent = KIND_META[ev.kind]?.label ?? ev.kind;
    row.appendChild(kind);

    const content = document.createElement("div");
    content.className = "chat-content";
    if (ev.kind === "intent") {
      content.textContent = ev.payload.intent || "(no intent text)";
      if (ev.payload.instinct_changed || ev.payload.experience_changed) {
        const flags = document.createElement("div");
        flags.className = "chat-flags";
        if (ev.payload.instinct_changed) {
          const f = document.createElement("span");
          f.className = "chat-flag";
          f.textContent = `instinct → v${ev.payload.instinct_version_out ?? "?"}`;
          flags.appendChild(f);
        }
        if (ev.payload.experience_changed) {
          const f = document.createElement("span");
          f.className = "chat-flag";
          f.textContent = `experience → v${ev.payload.experience_version_out ?? "?"}`;
          flags.appendChild(f);
        }
        content.appendChild(flags);
      }
    } else if (ev.kind === "failed") {
      content.textContent = `error: ${ev.payload.error}`;
    } else {
      content.textContent = ev.payload.content ?? JSON.stringify(ev.payload);
    }
    row.appendChild(content);

    row.addEventListener("click", () => {
      setState({ selectedEventId: ev.id, playheadTime: ev.t });
      panToTimeIfNeeded(ev.t);
    });

    chatEl.appendChild(row);
    chatRows.set(ev.id, row);

    if ((ev.kind === "intent" || ev.kind === "failed") && idx < events.length - 1) {
      const hr = document.createElement("hr");
      hr.className = "chat-divider";
      chatEl.appendChild(hr);
    }
  });
}

let lastSelected = null;
function syncChatSelection(state) {
  if (lastSelected) {
    const prev = chatRows.get(lastSelected);
    if (prev) prev.classList.remove("selected");
  }
  if (state.selectedEventId) {
    const row = chatRows.get(state.selectedEventId);
    if (row) {
      row.classList.add("selected");
      const r = row.getBoundingClientRect();
      const parent = chatEl.getBoundingClientRect();
      if (r.top < parent.top || r.bottom > parent.bottom) {
        row.scrollIntoView({ block: "center", behavior: "smooth" });
      }
    }
  }
  lastSelected = state.selectedEventId;
}

renderChatOnce();

subscribe(renderAxis);
subscribe(renderEvents);
subscribe(renderTokens);
subscribe(renderLatency);
subscribe(renderSizes);
subscribe(renderImu);
subscribe(renderPlayhead);
subscribe(syncChatSelection);

// ---------- Transport + inset stage (sim runs) ----------
// The JS wall clock is the master; audio is slaved (it may be shorter than the
// run). Playhead ticks update only the playhead line + inset — never the heavy
// timeline subscribers — so playback stays smooth.
const transportEl = document.getElementById("transport");
const playBtn = document.getElementById("play");
const scrubEl = document.getElementById("scrub");
const timeEl = document.getElementById("time");
const audioEl = document.getElementById("stage-audio");

let stage = null;
let playing = false;
let ph = 0;                 // playhead, seconds
let startWall = 0, startHead = 0;
let userScrubbing = false;

function setPlayhead(sec) {
  ph = Math.max(0, Math.min(sessionDuration, sec));
  state.playheadTime = ph;
  renderPlayhead(state);
  if (!userScrubbing) scrubEl.value = sessionDuration > 0 ? Math.round(ph / sessionDuration * 1000) : 0;
  timeEl.textContent = `${ph.toFixed(1)} / ${sessionDuration.toFixed(1)} s`;
  if (stage) stage.render(ph);
}
function play() {
  if (playing) return;
  if (ph >= sessionDuration) ph = 0;
  playing = true;
  startWall = performance.now(); startHead = ph;
  playBtn.textContent = "❚❚";
  if (audioEl.src) { audioEl.currentTime = Math.min(ph, audioEl.duration || ph); audioEl.play().catch(() => {}); }
}
function pause() {
  playing = false;
  playBtn.textContent = "▶";
  if (audioEl.src) audioEl.pause();
}
function tick() {
  if (playing) {
    const t = startHead + (performance.now() - startWall) / 1000;
    if (t >= sessionDuration) { setPlayhead(sessionDuration); pause(); }
    else setPlayhead(t);
  }
  requestAnimationFrame(tick);
}
playBtn.addEventListener("click", () => (playing ? pause() : play()));
window.addEventListener("keydown", (e) => {
  if (e.code === "Space" && e.target.tagName !== "INPUT") { e.preventDefault(); playing ? pause() : play(); }
});
scrubEl.addEventListener("pointerdown", () => { userScrubbing = true; });
scrubEl.addEventListener("pointerup", () => { userScrubbing = false; });
scrubEl.addEventListener("input", () => {
  if (playing) pause();
  setPlayhead((scrubEl.value / 1000) * sessionDuration);
  if (audioEl.src) audioEl.currentTime = Math.min(ph, audioEl.duration || ph);
});

// Double-click anywhere on the timeline to drop the playhead at that time.
// (timeScale is the zoom-rescaled scale, so this is correct at any zoom.)
svg.on("dblclick.zoom", null);   // disable d3-zoom's default double-click zoom
svg.on("dblclick", (event) => {
  const [x] = d3.pointer(event, svg.node());
  if (playing) pause();
  setPlayhead(state.timeScale.invert(x));
  if (audioEl.src) audioEl.currentTime = Math.min(ph, audioEl.duration || ph);
});

async function initStage(s) {
  document.getElementById("stage").hidden = false;
  transportEl.hidden = false;
  const screenEl = document.getElementById("stage-screen");
  const dev = createDevice(screenEl, s.display_ops, s.screen);
  screenEl.style.width = `${Math.round(64 * s.screen.w / s.screen.h)}px`;  // portrait aspect
  let skel = null;
  if (s.mocap) {
    try { skel = await createSkeleton(document.getElementById("stage-3d"), `/${s.mocap}`); }
    catch (e) { console.warn("skeleton:", e.message); }
  }
  const volBar = document.getElementById("stage-vol-bar");
  document.getElementById("stage-wrist").textContent = s.wrist ? s.wrist[0].toUpperCase() : "";
  if (s.audio) audioEl.src = `/${s.audio}`;
  return {
    render(sec) {
      const ms = sec * 1000;
      dev.render(ms);
      if (skel) skel.setTime(sec);
      volBar.style.width = `${Math.round(volumeAt(s.audio_events, ms) * 100)}%`;
    },
  };
}

if (trace.stage) {
  stage = await initStage(trace.stage);
  setPlayhead(0);
}
requestAnimationFrame(tick);
