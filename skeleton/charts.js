import * as d3 from 'd3';
import { state, bus, setFrame, setPlaying } from './state.js';

const { data, N, FPS } = state;
const L_WRIST = data.joint_names.indexOf('l_wrist');
const R_WRIST = data.joint_names.indexOf('r_wrist');
const DT = 1 / FPS;

const COLORS = {
  L: '#f4a261',
  R: '#2a9d8f',
  X: '#e76f51',
  Y: '#3ecf8e',
  Z: '#4ea8ff',
};

// ---- Derived signals: speed, |accel|, |jerk| for both wrists ---------------
function extractPos(jointIdx) {
  const out = new Float32Array(N * 3);
  for (let t = 0; t < N; t++) {
    const p = data.frames[t].p[jointIdx];
    out[t * 3]     = p[0];
    out[t * 3 + 1] = p[1];
    out[t * 3 + 2] = p[2];
  }
  return out;
}

function diff3(arr) {
  const out = new Float32Array(arr.length);
  const n = arr.length / 3;
  const inv2dt = 1 / (2 * DT);
  for (let t = 1; t < n - 1; t++) {
    out[t * 3]     = (arr[(t + 1) * 3]     - arr[(t - 1) * 3])     * inv2dt;
    out[t * 3 + 1] = (arr[(t + 1) * 3 + 1] - arr[(t - 1) * 3 + 1]) * inv2dt;
    out[t * 3 + 2] = (arr[(t + 1) * 3 + 2] - arr[(t - 1) * 3 + 2]) * inv2dt;
  }
  for (let k = 0; k < 3; k++) {
    out[k] = out[3 + k];
    out[(n - 1) * 3 + k] = out[(n - 2) * 3 + k];
  }
  return out;
}

function magnitude(arr) {
  const n = arr.length / 3;
  const out = new Float32Array(n);
  for (let t = 0; t < n; t++) {
    out[t] = Math.hypot(arr[t * 3], arr[t * 3 + 1], arr[t * 3 + 2]);
  }
  return out;
}

function kinematicDerived(jointIdx) {
  const pos = extractPos(jointIdx);
  const vel = diff3(pos);
  const acc = diff3(vel);
  const jerk = diff3(acc);
  return { speed: magnitude(vel), accel: magnitude(acc), jerk: magnitude(jerk) };
}

function unpackXYZ(xyzArr) {
  const n = xyzArr.length;
  const x = new Float32Array(n);
  const y = new Float32Array(n);
  const z = new Float32Array(n);
  for (let i = 0; i < n; i++) {
    x[i] = xyzArr[i][0];
    y[i] = xyzArr[i][1];
    z[i] = xyzArr[i][2];
  }
  return { x, y, z };
}

const Lkin = kinematicDerived(L_WRIST);
const Rkin = kinematicDerived(R_WRIST);
const LaccImu  = unpackXYZ(data.imu.left.acc);
const LgyroImu = unpackXYZ(data.imu.left.gyro);
const RaccImu  = unpackXYZ(data.imu.right.acc);
const RgyroImu = unpackXYZ(data.imu.right.gyro);

// ---- View definitions ------------------------------------------------------
const VIEWS = {
  kinematics: [
    { label: 'speed (m/s)',    yKind: 'abs',
      lines: [{ stroke: COLORS.L, data: Lkin.speed }, { stroke: COLORS.R, data: Rkin.speed }] },
    { label: '|accel| (m/s²)', yKind: 'abs',
      lines: [{ stroke: COLORS.L, data: Lkin.accel }, { stroke: COLORS.R, data: Rkin.accel }] },
    { label: '|jerk| (m/s³)',  yKind: 'abs',
      lines: [{ stroke: COLORS.L, data: Lkin.jerk },  { stroke: COLORS.R, data: Rkin.jerk  }] },
  ],
  imu: [
    { label: 'L wrist accel (g)', yKind: 'sym',
      lines: [
        { stroke: COLORS.X, data: LaccImu.x },
        { stroke: COLORS.Y, data: LaccImu.y },
        { stroke: COLORS.Z, data: LaccImu.z },
      ] },
    { label: 'R wrist accel (g)', yKind: 'sym',
      lines: [
        { stroke: COLORS.X, data: RaccImu.x },
        { stroke: COLORS.Y, data: RaccImu.y },
        { stroke: COLORS.Z, data: RaccImu.z },
      ] },
    { label: 'L wrist gyro (deg/s)', yKind: 'sym',
      lines: [
        { stroke: COLORS.X, data: LgyroImu.x },
        { stroke: COLORS.Y, data: LgyroImu.y },
        { stroke: COLORS.Z, data: LgyroImu.z },
      ] },
    { label: 'R wrist gyro (deg/s)', yKind: 'sym',
      lines: [
        { stroke: COLORS.X, data: RgyroImu.x },
        { stroke: COLORS.Y, data: RgyroImu.y },
        { stroke: COLORS.Z, data: RgyroImu.z },
      ] },
  ],
};

const LEGENDS = {
  kinematics: `<span class="sw" style="background:${COLORS.L}"></span>left&nbsp;&nbsp;<span class="sw" style="background:${COLORS.R}"></span>right`,
  imu:        `<span class="sw" style="background:${COLORS.X}"></span>x&nbsp;&nbsp;<span class="sw" style="background:${COLORS.Y}"></span>y&nbsp;&nbsp;<span class="sw" style="background:${COLORS.Z}"></span>z`,
};

// ---- Layout constants ------------------------------------------------------
const ROW_PAD_TOP = 14;
const ROW_PAD_BOTTOM = 4;
const AXIS_H = 22;
const LEFT_PAD = 64;
const RIGHT_PAD = 16;

const svg = d3.select('#charts');
const chartLegend = document.getElementById('chart-legend');

const xScaleBase = d3.scaleLinear().domain([0, (N - 1) / FPS]);
let xScaleView = xScaleBase.copy();
let currentTransform = d3.zoomIdentity;

// Per-view runtime objects (rebuilt on view switch).
let current = null; // { series, rowG, zoomGroups, lineEls, yScales, yAxesG, playheads, clipRects, overlay, xAxisG, layout }

function yScaleFor(s) {
  if (s.yKind === 'abs') {
    const tops = s.lines.map(l => d3.quantile(l.data, 0.995) ?? 1);
    return d3.scaleLinear().domain([0, Math.max(...tops, 1e-6) * 1.05]).nice();
  } else {
    // sym: symmetric around 0
    const tops = s.lines.map(l => d3.quantile(l.data, 0.995, Math.abs) ?? 1);
    const top = Math.max(...tops, 1e-6) * 1.1;
    return d3.scaleLinear().domain([-top, top]).nice();
  }
}

function buildLinePath(arr, yScale) {
  return d3.line()
    .x((_d, idx) => xScaleBase(idx / FPS))
    .y(d => yScale(d))(arr);
}

function buildView(viewName) {
  svg.selectAll('*').remove();
  chartLegend.innerHTML = LEGENDS[viewName];
  document.querySelectorAll('#chart-tabs button').forEach(b => {
    b.classList.toggle('active', b.dataset.view === viewName);
  });

  const series = VIEWS[viewName];
  const defs = svg.append('defs');
  const clipRects = series.map((_, i) =>
    defs.append('clipPath').attr('id', `chart-clip-${i}`).append('rect')
  );

  const rowG = series.map(s => svg.append('g').attr('class', `row`));
  const zoomGroups = rowG.map((r, i) =>
    r.append('g').attr('class', 'zoom-grp').attr('clip-path', `url(#chart-clip-${i})`)
  );
  const lineEls = series.map((s, i) =>
    s.lines.map(line =>
      zoomGroups[i].append('path').attr('fill', 'none').attr('stroke', line.stroke)
        .attr('stroke-width', 1).attr('vector-effect', 'non-scaling-stroke')
    )
  );
  rowG.forEach((r, i) => {
    r.append('text').attr('fill', '#aaa').attr('font-size', 11)
     .attr('x', 6).attr('y', 12).text(series[i].label);
  });
  const yAxesG = rowG.map(r => r.append('g').attr('class', 'y-axis'));
  const playheads = rowG.map(r =>
    r.append('line').attr('stroke', '#fff').attr('stroke-width', 1).attr('opacity', 0.7)
  );

  const xAxisG = svg.append('g').attr('class', 'x-axis');
  const overlay = svg.append('rect')
    .attr('fill', 'transparent').style('cursor', 'crosshair');

  const yScales = series.map(yScaleFor);

  current = { series, rowG, zoomGroups, lineEls, yScales, yAxesG, playheads, clipRects, overlay, xAxisG, layout: null };

  attachInteractions();
  relayout();
}

function relayout() {
  if (!current) return;
  const W = svg.node().clientWidth;
  const H = svg.node().clientHeight;
  if (!W || !H) return;
  const { series, rowG, lineEls, yScales, yAxesG, playheads, clipRects, overlay } = current;

  const innerW = W - LEFT_PAD - RIGHT_PAD;
  const usableH = H - AXIS_H;
  const rowH = usableH / series.length;

  xScaleBase.range([LEFT_PAD, LEFT_PAD + innerW]);

  series.forEach((s, i) => {
    const top = i * rowH + ROW_PAD_TOP;
    const bot = (i + 1) * rowH - ROW_PAD_BOTTOM;
    yScales[i].range([bot, top]);

    rowG[i].select('.row-bg').remove();
    rowG[i].insert('rect', ':first-child')
      .attr('class', 'row-bg')
      .attr('x', LEFT_PAD).attr('y', top)
      .attr('width', innerW).attr('height', bot - top)
      .attr('fill', '#141414').attr('stroke', '#222')
      .style('pointer-events', 'none');

    clipRects[i]
      .attr('x', LEFT_PAD).attr('y', top)
      .attr('width', innerW).attr('height', bot - top);

    s.lines.forEach((line, li) => {
      lineEls[i][li].attr('d', buildLinePath(line.data, yScales[i]));
    });

    yAxesG[i]
      .attr('transform', `translate(${LEFT_PAD},0)`)
      .call(d3.axisLeft(yScales[i]).ticks(3).tickSize(-innerW))
      .call(g => g.selectAll('.tick line').attr('stroke', '#262626'))
      .call(g => g.selectAll('.tick text').attr('fill', '#666'))
      .call(g => g.select('.domain').remove());

    playheads[i].attr('y1', top).attr('y2', bot);
  });

  overlay
    .attr('x', LEFT_PAD).attr('y', 0)
    .attr('width', innerW).attr('height', usableH);

  current.layout = { W, H, innerW, usableH };

  zoom.extent([[LEFT_PAD, 0], [LEFT_PAD + innerW, usableH]])
      .translateExtent([[LEFT_PAD, 0], [LEFT_PAD + innerW, usableH]]);

  // Re-apply current transform (preserves zoom across resize / view switch).
  svg.call(zoom.transform, currentTransform);

  updateXAxis();
  updatePlayhead(state.frame);
}

function updateXAxis() {
  if (!current?.layout) return;
  current.xAxisG
    .attr('transform', `translate(0,${current.layout.usableH})`)
    .call(d3.axisBottom(xScaleView).ticks(Math.max(2, Math.floor(current.layout.innerW / 80))))
    .call(g => g.selectAll('.tick text').attr('fill', '#888'))
    .call(g => g.select('.domain').attr('stroke', '#444'));
}

function updatePlayhead(f) {
  if (!current) return;
  const x = xScaleView(f / FPS);
  const [xMin, xMax] = xScaleView.range();
  const visible = x >= xMin - 0.5 && x <= xMax + 0.5;
  for (const ph of current.playheads) {
    ph.attr('x1', x).attr('x2', x).attr('opacity', visible ? 0.7 : 0);
  }
}

// ---- Zoom (wheel / dblclick) and pan (shift+drag) -------------------------
const zoom = d3.zoom()
  .scaleExtent([1, 500])
  .filter(event => {
    if (event.type === 'wheel') return true;
    if (event.type === 'dblclick') return true;
    return event.shiftKey;
  })
  .on('zoom', (event) => {
    currentTransform = event.transform;
    xScaleView = event.transform.rescaleX(xScaleBase);
    const tx = event.transform.x;
    const k = event.transform.k;
    if (current) {
      for (const g of current.zoomGroups) {
        g.attr('transform', `translate(${tx},0) scale(${k},1)`);
      }
      updateXAxis();
      updatePlayhead(state.frame);
    }
  });

svg.call(zoom);

// ---- Scrub (plain drag) ---------------------------------------------------
function xToFrame(x) {
  return Math.round(xScaleView.invert(x) * FPS);
}

function attachInteractions() {
  const drag = d3.drag()
    .filter(event => !event.shiftKey)
    .on('start', (event) => {
      setPlaying(false);
      const [x] = d3.pointer(event, svg.node());
      setFrame(xToFrame(x));
    })
    .on('drag', (event) => {
      const [x] = d3.pointer(event, svg.node());
      setFrame(xToFrame(x));
    });
  current.overlay.call(drag);
}

// ---- Tabs -----------------------------------------------------------------
document.querySelectorAll('#chart-tabs button').forEach(btn => {
  btn.addEventListener('click', () => buildView(btn.dataset.view));
});

// ---- Reactive updates -----------------------------------------------------
bus.addEventListener('frame', (e) => updatePlayhead(e.detail));

const ro = new ResizeObserver(relayout);
ro.observe(svg.node());

buildView('kinematics');
