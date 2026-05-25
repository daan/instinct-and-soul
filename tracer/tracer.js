// Tracer — D3 timeline on top, chat scroll below, click-sync between them.

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
const trace = await fetch(traceUrl).then(r => {
  if (!r.ok) throw new Error(`fetch ${traceUrl} → ${r.status}`);
  return r.json();
});

// ts → seconds-from-session-start, keep unix for hover/export
const t0 = trace.session_start;
const events = trace.events.map(e => ({ ...e, t: e.t - t0, t_unix: e.t }));
const sessionDuration = events.length
  ? Math.max(...events.map(e => e.t)) + 2
  : 60;

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

// ---------- Timeline SVG ----------
const svg = d3.select("#timeline");
const { width, height } = svg.node().getBoundingClientRect();
svg.attr("viewBox", `0 0 ${width} ${height}`);
svg.append("rect").attr("class", "zoom-surface").attr("width", width).attr("height", height);

const axisGroup     = svg.append("g").attr("class", "axis").attr("transform", "translate(0, 30)");
const eventsGroup   = svg.append("g").attr("class", "events").attr("transform", `translate(0, ${height / 2 + 10})`);
const playheadGroup = svg.append("g").attr("class", "playhead-group");

// Two lanes inside eventsGroup: instinct/operator/crash/mem above, soul below.
const INSTINCT_Y = -22;
const SOUL_Y     = 22;
function laneY(kind) {
  return (kind === "intent" || kind === "failed") ? SOUL_Y : INSTINCT_Y;
}

// Static lane labels — drawn once.
svg.append("text")
  .attr("class", "lane-label")
  .attr("x", 6).attr("y", height / 2 + 10 + INSTINCT_Y + 3)
  .text("instinct");
svg.append("text")
  .attr("class", "lane-label")
  .attr("x", 6).attr("y", height / 2 + 10 + SOUL_Y + 3)
  .text("soul");

const margin = { left: 40, right: 30 };
const baseTimeScale = d3.scaleLinear()
  .domain([0, sessionDuration])
  .range([margin.left, width - margin.right]);
setState({ timeScale: baseTimeScale });

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

function renderEvents(state) {
  eventsGroup.selectAll("*").remove();
  const [tMin, tMax] = state.timeScale.domain();
  const visible = events.filter(e => e.t >= tMin && e.t <= tMax);

  // ---- Group visible events by ref_seq into batches ----
  const batches = new Map();
  visible.forEach(e => {
    const ref = e.payload?.ref_seq;
    if (ref == null) return;
    if (!batches.has(ref)) batches.set(ref, { msgs: [], intent: null });
    const b = batches.get(ref);
    if (e.kind === "intent" || e.kind === "failed") b.intent = e;
    else b.msgs.push(e);
  });
  batches.forEach(b => b.msgs.sort((a, b) => a.t - b.t));

  // ---- Batch polylines (rendered behind dots) ----
  const linesG = eventsGroup.append("g").attr("class", "batch-lines");
  batches.forEach(b => {
    const pts = [];
    b.msgs.forEach(m => pts.push([state.timeScale(m.t), INSTINCT_Y]));
    if (b.intent) pts.push([state.timeScale(b.intent.t), SOUL_Y]);
    if (pts.length < 2) return;
    const d = "M" + pts.map(p => `${p[0]},${p[1]}`).join(" L");
    linesG.append("path")
      .attr("class", "batch-line" + (b.intent?.kind === "failed" ? " failed" : ""))
      .attr("d", d);
  });

  // ---- Event dots ----
  const groups = eventsGroup.selectAll("g.event")
    .data(visible, d => d.id)
    .enter()
    .append("g")
    .attr("class", d => {
      const cls = ["event", d.kind];
      if (d.kind === "intent" &&
          (d.payload.instinct_changed || d.payload.experience_changed)) {
        cls.push("changed");
      }
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

function renderPlayhead(state) {
  playheadGroup.selectAll("*").remove();
  if (state.playheadTime == null) return;
  const x = state.timeScale(state.playheadTime);
  const [xMin, xMax] = state.timeScale.range();
  if (x < xMin - 5 || x > xMax + 5) return;
  playheadGroup.append("line")
    .attr("class", "playhead")
    .attr("x1", x).attr("x2", x)
    .attr("y1", 20).attr("y2", height - 10);
}

const zoom = d3.zoom()
  .scaleExtent([1, 500])
  .translateExtent([[0, 0], [width, height]])
  .extent([[0, 0], [width, height]])
  .on("zoom", (event) => {
    setState({ timeScale: event.transform.rescaleX(baseTimeScale) });
  });
svg.call(zoom);

// ---------- Chat ----------
const chatEl = document.getElementById("chat");
const chatRows = new Map();  // event id → row element

// Muted 4-color cycle keyed by ref_seq. Adjacent reflections never share a
// color, so the boundary between batches is visible at a glance — including
// the messages that arrived during a reflection (they get the *next* color).
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
    row.className = `chat-row ${ev.kind}`;
    row.dataset.id = ev.id;
    const c = refColor(ev.payload?.ref_seq);
    if (c) row.style.setProperty("--ref-color", c);

    const ts = document.createElement("div");
    ts.className = "chat-ts";
    ts.textContent = ev.t.toFixed(2) + "s";
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
    });

    chatEl.appendChild(row);
    chatRows.set(ev.id, row);

    // divider after each reflection beat (intent or failed)
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
      // Only scroll into view if not already visible (avoids re-scrolling on chat-click)
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
subscribe(renderPlayhead);
subscribe(syncChatSelection);
