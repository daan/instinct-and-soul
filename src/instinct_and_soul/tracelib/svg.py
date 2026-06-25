"""Render a baked trace into a standalone, self-contained SVG (timeline + log).

Saving the live viewer's SVG drops the external stylesheet and omits the HTML
log. This emits one self-styled .svg fit for a paper figure: a time axis (m:ss),
the instinct/soul event lanes with deploy version labels (v4, v7, …), and the
reflection log as wrapped text below. All styling is inline, so the file stands
alone in Inkscape / LaTeX / a browser.
"""
import html
from collections import defaultdict

# kind -> (colour, radius, lane)   lane: "instinct" (upper) or "soul" (lower)
KIND = {
    "instinct-msg": ("#44aa77", 3, "instinct"),
    "operator":     ("#22aa99", 3, "instinct"),
    "mem":          ("#999999", 3, "instinct"),
    "intent":       ("#7744aa", 6, "soul"),
    "failed":       ("#cc3333", 6, "soul"),
    "crash":        ("#991111", 6, "instinct"),
}


def _mmss(s: float) -> str:
    m = int(s // 60)
    sec = int(round(s - m * 60))
    if sec == 60:
        m += 1
        sec = 0
    return f"{m}:{sec:02d}"


def _esc(t) -> str:
    return html.escape(str(t), quote=True)


def _nice_step(dur: float) -> int:
    raw = dur / 10.0
    for step in (5, 10, 15, 20, 30, 60, 120, 300, 600, 1200):
        if step >= raw:
            return step
    return 1800


def _wrap(text: str, width: int) -> list:
    lines, cur = [], ""
    for w in str(text).split():
        if cur and len(cur) + len(w) + 1 > width:
            lines.append(cur)
            cur = w
        else:
            cur = (cur + " " + w).strip()
    if cur:
        lines.append(cur)
    return lines or [""]


def render_svg(data: dict, width: int = 1100) -> str:
    t0 = data.get("session_start", 0) or 0
    events = sorted(data.get("events", []), key=lambda e: e.get("t", 0))
    for e in events:
        e["_t"] = e.get("t", 0) - t0
    dur = max((e["_t"] for e in events), default=58) + 2

    L, R = 70, 30
    plot_w = max(1, width - L - R)

    def X(s: float) -> float:
        return L + (s / dur) * plot_w

    y_inst, y_soul, axis_y = 92, 130, 154

    model = (data.get("meta", {}).get("llm") or {}).get("model", "")
    n_dep = sum(1 for e in events
                if e.get("payload", {}).get("instinct_changed"))

    body = []

    # ── header ──
    body.append(f'<text x="{L}" y="30" font-size="15" fill="#111" '
                f'font-weight="bold">{_esc(data.get("session_id", ""))}</text>')
    body.append(f'<text x="{L}" y="50" font-size="11" fill="#555">'
                f'{len(events)} events · {_mmss(dur)} · {_esc(model)} · '
                f'{n_dep} deploys</text>')

    # ── timeline: lane labels ──
    body.append(f'<text x="6" y="{y_inst + 3}" font-size="10" fill="#777">instinct</text>')
    body.append(f'<text x="6" y="{y_soul + 3}" font-size="10" fill="#777">soul</text>')

    # ── batch polylines (messages -> their intent) ──
    batches = defaultdict(lambda: {"msgs": [], "intent": None})
    for e in events:
        ref = e.get("payload", {}).get("ref_seq")
        if ref is None or e.get("payload", {}).get("dropped"):
            continue
        b = batches[str(ref)]
        if e["kind"] in ("intent", "failed"):
            b["intent"] = e
        else:
            b["msgs"].append(e)
    for b in batches.values():
        pts = [(X(m["_t"]), y_inst) for m in sorted(b["msgs"], key=lambda m: m["_t"])]
        if b["intent"]:
            pts.append((X(b["intent"]["_t"]), y_soul))
        if len(pts) >= 2:
            d = "M" + " L".join(f"{px:.1f},{py:.1f}" for px, py in pts)
            col = "#cc3333" if (b["intent"] and b["intent"]["kind"] == "failed") else "#cccccc"
            body.append(f'<path d="{d}" fill="none" stroke="{col}" '
                        f'stroke-width="1" opacity="0.6"/>')

    # ── event dots + deploy version labels ──
    for e in events:
        col, r, _ = KIND.get(e["kind"], ("#999999", 3, "instinct"))
        y = y_soul if e["kind"] in ("intent", "failed") else y_inst
        px = X(e["_t"])
        if e["kind"] == "crash":
            body.append(f'<path d="M{px:.1f},{y - r} L{px + r:.1f},{y} '
                        f'L{px:.1f},{y + r} L{px - r:.1f},{y} Z" fill="{col}"/>')
        else:
            body.append(f'<circle cx="{px:.1f}" cy="{y}" r="{r}" fill="{col}"/>')
        p = e.get("payload", {})
        if e["kind"] == "intent" and p.get("instinct_changed"):
            body.append(f'<text x="{px:.1f}" y="{y - r - 3}" text-anchor="middle" '
                        f'font-size="9" fill="{col}">v{p.get("instinct_version_out")}</text>')

    # ── time axis (m:ss) ──
    body.append(f'<line x1="{L}" y1="{axis_y}" x2="{width - R}" y2="{axis_y}" '
                f'stroke="#888" stroke-width="1"/>')
    step = _nice_step(dur)
    t = 0
    while t <= dur:
        px = X(t)
        body.append(f'<line x1="{px:.1f}" y1="{axis_y}" x2="{px:.1f}" '
                    f'y2="{axis_y + 4}" stroke="#888"/>')
        body.append(f'<text x="{px:.1f}" y="{axis_y + 16}" text-anchor="middle" '
                    f'font-size="10" fill="#555">{_mmss(t)}</text>')
        t += step

    # ── reflection log ──
    y = axis_y + 46
    body.append(f'<text x="{L}" y="{y}" font-size="12" fill="#222" '
                f'font-weight="bold">reflection log</text>')
    y += 20
    LINE_H = 14
    wrap_w = max(20, plot_w // 7)   # ~7px per monospace char at 11px
    for e in events:
        if e["kind"] not in ("intent", "failed"):
            continue
        p = e.get("payload", {})
        if e["kind"] == "failed":
            head, hcol = f'[{_mmss(e["_t"])}] FAILED', "#cc3333"
        else:
            tag = (f'→ v{p.get("instinct_version_out")}'
                   if p.get("instinct_changed") else '(no deploy)')
            head, hcol = f'[{_mmss(e["_t"])}] {tag}', "#7744aa"
        body.append(f'<text x="{L}" y="{y}" font-size="11" fill="{hcol}" '
                    f'font-weight="bold">{_esc(head)}</text>')
        y += LINE_H
        for ln in _wrap(p.get("intent") or p.get("error") or "", wrap_w):
            body.append(f'<text x="{L + 14}" y="{y}" font-size="11" '
                        f'fill="#333">{_esc(ln)}</text>')
            y += LINE_H
        y += 6

    height = int(y + 16)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
            f'height="{height}" viewBox="0 0 {width} {height}" '
            f'font-family="ui-monospace, Menlo, Consolas, monospace">'
            f'<rect width="{width}" height="{height}" fill="white"/>'
            + "".join(body) + '</svg>')
