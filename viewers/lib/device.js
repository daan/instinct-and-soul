// device — replay an M5 display_log onto a canvas at a given sim-ms.
// Lifted from viewers/playback/playback.js (the applyOp switch + frame
// reconstruction). The canvas buffer is the true panel size; CSS scales it small.

export function createDevice(canvas, ops, screen) {
  const W = screen.w, H = screen.h;
  canvas.width = W;
  canvas.height = H;
  const ctx = canvas.getContext('2d');
  ctx.imageSmoothingEnabled = false;

  const times = ops.map(o => o.t);
  const frameStarts = [];
  ops.forEach((o, i) => { if (o.kind === 'fillScreen') frameStarts.push(i); });
  const frameTimes = frameStarts.map(i => times[i]);

  const css = (n) => '#' + (n >>> 0).toString(16).padStart(6, '0').slice(-6);
  const deg2rad = (d) => (d * Math.PI) / 180;
  const ub = (arr, t) => {
    let lo = 0, hi = arr.length - 1, a = -1;
    while (lo <= hi) { const m = (lo + hi) >> 1; if (arr[m] <= t) { a = m; lo = m + 1; } else hi = m - 1; }
    return a;
  };

  function applyOp(o) {
    switch (o.kind) {
      case 'fillScreen': ctx.fillStyle = css(o.rgb); ctx.fillRect(0, 0, W, H); break;
      case 'fillRect': ctx.fillStyle = css(o.rgb); ctx.fillRect(o.x, o.y, o.w, o.h); break;
      case 'fillCircle':
        ctx.fillStyle = css(o.rgb); ctx.beginPath(); ctx.arc(o.cx, o.cy, o.r, 0, 2 * Math.PI); ctx.fill(); break;
      case 'fillTriangle':
        ctx.fillStyle = css(o.rgb); ctx.beginPath();
        ctx.moveTo(o.x1, o.y1); ctx.lineTo(o.x2, o.y2); ctx.lineTo(o.x3, o.y3); ctx.closePath(); ctx.fill(); break;
      case 'fillArc': {
        ctx.fillStyle = css(o.rgb);
        ctx.beginPath();
        ctx.arc(o.cx, o.cy, o.r1, deg2rad(o.a0), deg2rad(o.a1));
        ctx.arc(o.cx, o.cy, o.r0, deg2rad(o.a1), deg2rad(o.a0), true);
        ctx.closePath(); ctx.fill(); break;
      }
      case 'drawLine':
        ctx.strokeStyle = css(o.rgb); ctx.lineWidth = 1;
        ctx.beginPath(); ctx.moveTo(o.x1 + 0.5, o.y1 + 0.5); ctx.lineTo(o.x2 + 0.5, o.y2 + 0.5); ctx.stroke(); break;
    }
  }

  function render(ms) {
    const end = ub(times, ms);
    if (end < 0) { ctx.fillStyle = '#000'; ctx.fillRect(0, 0, W, H); return; }
    let start = ub(frameTimes, ms);
    if (start < 0) { ctx.fillStyle = '#000'; ctx.fillRect(0, 0, W, H); start = 0; }
    else start = frameStarts[start];
    for (let i = start; i <= end; i++) applyOp(ops[i]);
  }

  render(0);
  return { render };
}

// Peak tone volume (0..1) sounding at sim-ms `t`, from audio_events.
export function volumeAt(events, t) {
  let v = 0;
  for (const e of events) {
    if (e.kind === 'tone' && e.t <= t && t < e.t + e.ms) v = Math.max(v, (e.volume || 0) / 255);
  }
  return v;
}
