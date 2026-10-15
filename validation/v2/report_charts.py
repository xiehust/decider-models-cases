"""Inline SVG chart primitives for the light report theme. No external libraries."""
from html import escape

INK, MUTED, GRID = '#1e293b', '#64748b', '#e2e8f0'
BLUE, TEAL, AMBER, RED, VIOLET, SLATE = '#2563eb', '#0d9488', '#d97706', '#dc2626', '#7c3aed', '#94a3b8'
PALETTE = [BLUE, TEAL, AMBER, VIOLET, '#db2777', '#0891b2', '#65a30d', SLATE]
FONT = "font-family=\"'Inter','Noto Sans CJK SC','PingFang SC','Microsoft YaHei',sans-serif\""


def esc(text):
    return escape(str(text), quote=True)


def svg(width, height, body, label, max_width=None):
    style = f' style="max-width:{max_width}px;margin:0 auto"' if max_width else ''
    return (f'<svg class="chart" viewBox="0 0 {width} {height}" role="img" aria-label="{esc(label)}"{style} '
            f'xmlns="http://www.w3.org/2000/svg" {FONT}>{body}</svg>')


def text(x, y, content, size=12, color=INK, anchor='start', weight=400):
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" fill="{color}" text-anchor="{anchor}" '
            f'font-weight="{weight}">{esc(content)}</text>')


def skill_bars(rows, width=760):
    """rows: [(label, passed, total, review)] -> horizontal pass-rate bars with review ticks."""
    left, bar_w, row_h = 150, width - 150 - 110, 30
    height = 34 + row_h * len(rows)
    body = [text(left, 16, '符合标准答案的判断占比', 11, MUTED), text(width - 4, 16, '通过 / 总数 · 复核', 11, MUTED, 'end')]
    for i, (label, passed, total, review) in enumerate(rows):
        y = 28 + i * row_h
        rate = passed / total if total else 0
        color = TEAL if rate == 1 else AMBER if rate >= 0.8 else RED
        body.append(text(left - 10, y + 15, label, 12.5, INK, 'end', 500))
        body.append(f'<rect x="{left}" y="{y + 4}" width="{bar_w}" height="16" rx="8" fill="#f1f5f9"/>')
        body.append(f'<rect x="{left}" y="{y + 4}" width="{bar_w * rate:.1f}" height="16" rx="8" fill="{color}"/>')
        body.append(text(left + bar_w * rate - 6 if rate > .15 else left + 6, y + 16, f'{rate:.0%}', 10.5,
                         '#fff' if rate > .15 else INK, 'end' if rate > .15 else 'start', 600))
        body.append(text(width - 4, y + 16, f'{passed}/{total} · {review}', 12, MUTED, 'end'))
    return svg(width, height, ''.join(body), '各技能通过率')


def prob_bar(probs, chosen=None, gold=None, width=520, label_w=150):
    """One stacked distribution, largest first; marks chosen and gold labels."""
    items = sorted(probs.items(), key=lambda kv: -kv[1])
    bar_w, height = width - label_w - 50, 22 * len(items) + 6
    body = []
    for i, (name, p) in enumerate(items):
        y = 4 + i * 22
        color = TEAL if name == gold else (AMBER if name == chosen else SLATE)
        mark = (' ✓' if name == gold else '') + (' ◀' if name == chosen and name != gold else '')
        body.append(text(label_w - 8, y + 13, f'{name}{mark}', 11.5, INK if name in (gold, chosen) else MUTED, 'end',
                         600 if name in (gold, chosen) else 400))
        body.append(f'<rect x="{label_w}" y="{y + 3}" width="{bar_w}" height="12" rx="6" fill="#f1f5f9"/>')
        body.append(f'<rect x="{label_w}" y="{y + 3}" width="{max(bar_w * p, 1.5 if p else 0):.1f}" height="12" rx="6" fill="{color}"/>')
        body.append(text(label_w + bar_w + 8, y + 13, f'{p:.2f}', 11, MUTED))
    return svg(width, height, ''.join(body), '概率分布', max_width=int(width * 1.2))


def score_bar(probs, levels, value, band=None, width=520):
    """Score distribution per level plus the probability-weighted value and accepted band."""
    n = len(levels)
    left, right, top = 20, width - 20, 30
    span = right - left
    body = [f'<line x1="{left}" y1="{top + 40}" x2="{right}" y2="{top + 40}" stroke="{GRID}" stroke-width="2"/>']
    if band:
        x0, x1 = left + span * band[0] / (n - 1), left + span * band[1] / (n - 1)
        body.append(f'<rect x="{x0:.1f}" y="{top - 6}" width="{x1 - x0:.1f}" height="52" rx="6" fill="#ccfbf1" opacity=".7"/>')
        body.append(text((x0 + x1) / 2, top - 10, f'可接受区间 [{band[0]}, {band[1]}]', 10.5, TEAL, 'middle', 600))
    for i in range(n):
        x = left + span * i / (n - 1)
        p = probs.get(str(i), 0)
        h = 36 * p
        body.append(f'<rect x="{x - 14:.1f}" y="{top + 40 - h:.1f}" width="28" height="{h:.1f}" rx="3" fill="{BLUE}" opacity=".8"/>')
        body.append(text(x, top + 56, f'等级 {i}', 10.5, MUTED, 'middle'))
        body.append(text(x, top + 36 - h, f'{p:.2f}', 10, INK, 'middle'))
    vx = left + span * value / (n - 1)
    inside = band is None or band[0] <= value <= band[1]
    color = TEAL if inside else RED
    body.append(f'<line x1="{vx:.1f}" y1="{top - 2}" x2="{vx:.1f}" y2="{top + 44}" stroke="{color}" stroke-width="2.5" stroke-dasharray="4 3"/>')
    body.append(f'<circle cx="{vx:.1f}" cy="{top + 40}" r="5" fill="{color}"/>')
    body.append(text(vx, top + 72, f'加权分 {value:g}', 11, color, 'middle', 700))
    return svg(width, top + 80, ''.join(body), '评分分布')


def calibration_chart(bins, width=520, height=250):
    left, bottom, top, right = 50, height - 40, 20, width - 20
    body = [f'<line x1="{left}" y1="{bottom}" x2="{right}" y2="{bottom}" stroke="{GRID}"/>',
            f'<line x1="{left}" y1="{top}" x2="{left}" y2="{bottom}" stroke="{GRID}"/>']
    for t in (0, .5, 1):
        y = bottom - (bottom - top) * t
        body.append(f'<line x1="{left}" y1="{y}" x2="{right}" y2="{y}" stroke="{GRID}" stroke-dasharray="3 3"/>')
        body.append(text(left - 8, y + 4, f'{t:.0%}', 10.5, MUTED, 'end'))
    slot = (right - left) / len(bins)
    for i, b in enumerate(bins):
        x = left + slot * i + slot * .2
        w = slot * .6
        lo, hi = b['range']
        body.append(text(x + w / 2, bottom + 16, f'{lo:.2f}–{hi:.2f}', 10.5, MUTED, 'middle'))
        body.append(text(x + w / 2, bottom + 30, f'n={b["n"]}', 10, MUTED, 'middle'))
        if b['rate'] is None:
            body.append(text(x + w / 2, bottom - 8, '无样本', 10, SLATE, 'middle'))
            continue
        h = (bottom - top) * b['rate']
        body.append(f'<rect x="{x:.1f}" y="{bottom - h:.1f}" width="{w:.1f}" height="{h:.1f}" rx="4" '
                    f'fill="{TEAL if b["rate"] >= .9 else AMBER if b["rate"] >= .6 else RED}"/>')
        body.append(text(x + w / 2, bottom - h - 6, f'{b["agree"]}/{b["n"]}', 11, INK, 'middle', 600))
    return svg(width, height, ''.join(body), '概率分段与标准答案的一致率')


def histogram(values, width=520, height=220, bins=8, unit='s'):
    lo, hi = min(values), max(values)
    step = (hi - lo) / bins or 1
    counts = [0] * bins
    for v in values:
        counts[min(int((v - lo) / step), bins - 1)] += 1
    left, bottom, top, right = 36, height - 34, 16, width - 12
    peak = max(counts)
    slot = (right - left) / bins
    body = [f'<line x1="{left}" y1="{bottom}" x2="{right}" y2="{bottom}" stroke="{GRID}"/>']
    for i, c in enumerate(counts):
        h = (bottom - top) * c / peak
        x = left + slot * i
        body.append(f'<rect x="{x + 2:.1f}" y="{bottom - h:.1f}" width="{slot - 4:.1f}" height="{h:.1f}" rx="3" fill="{BLUE}" opacity=".85"/>')
        if c:
            body.append(text(x + slot / 2, bottom - h - 4, c, 10, INK, 'middle'))
        body.append(text(x + slot / 2, bottom + 14, f'{lo + step * i:.2f}', 9.5, MUTED, 'middle'))
    body.append(text(right, bottom + 28, f'单次调用耗时（{unit}，区间下界）', 10, MUTED, 'end'))
    return svg(width, height, ''.join(body), '耗时分布')


def flow(steps, width=760, accent=BLUE):
    """steps: [(title, subtitle, kind)] kind in host/jev/check -> left-to-right boxes with arrows."""
    n = len(steps)
    gap = 26
    box_w = (width - gap * (n - 1) - 4) / n
    colors = {'host': ('#eff6ff', BLUE), 'jev': ('#f5f3ff', VIOLET), 'decision': ('#f5f3ff', VIOLET),
              'check': ('#f0fdfa', TEAL), 'stop': ('#fff7ed', AMBER)}
    body = []
    for i, (title, sub, kind) in enumerate(steps):
        x = 2 + i * (box_w + gap)
        fill, stroke = colors.get(kind, colors['host'])
        body.append(f'<rect x="{x:.1f}" y="8" width="{box_w:.1f}" height="74" rx="12" fill="{fill}" stroke="{stroke}" stroke-width="1.4"/>')
        body.append(text(x + box_w / 2, 36, title, 13, INK, 'middle', 650))
        for k, line in enumerate(sub.split('\n')[:2]):
            body.append(text(x + box_w / 2, 56 + k * 15, line, 10.5, MUTED, 'middle'))
        if i < n - 1:
            ax = x + box_w + 3
            body.append(f'<path d="M{ax:.1f},45 L{ax + gap - 8:.1f},45" stroke="{SLATE}" stroke-width="1.6"/>'
                        f'<path d="M{ax + gap - 8:.1f},40 L{ax + gap - 2:.1f},45 L{ax + gap - 8:.1f},50 Z" fill="{SLATE}"/>')
    legend = [('调用方（Agent 或代码）', BLUE), ('Decider 类型化判断', VIOLET), ('确定性校验', TEAL), ('停止/上报', AMBER)]
    lx = 2
    for name, color in legend:
        body.append(f'<rect x="{lx}" y="96" width="10" height="10" rx="2" fill="{color}"/>')
        body.append(text(lx + 15, 105, name, 10.5, MUTED))
        lx += 26 + 11.5 * len(name)
    return svg(width, 112, ''.join(body), '流程图')


def grid_map(grid, paths, cell=46, title=''):
    """grid rows of chars; paths: [(points, color, label)] drawn as polylines with visit counts."""
    rows, cols = len(grid), len(grid[0])
    pad = 26
    width, height = cols * cell + pad * 2, rows * cell + pad * 2 + 22
    body = []
    for y, row in enumerate(grid):
        for x, ch in enumerate(row):
            fill = '#334155' if ch == '#' else '#ffffff'
            body.append(f'<rect x="{pad + x * cell}" y="{pad + y * cell}" width="{cell}" height="{cell}" fill="{fill}" stroke="{GRID}"/>')
            if ch in 'SPD':
                name = {'S': '起点', 'P': '包裹', 'D': '投递点'}[ch]
                body.append(text(pad + x * cell + cell / 2, pad + y * cell + 14, name, 10, MUTED, 'middle'))
        body.append(text(pad - 8, pad + y * cell + cell / 2 + 4, y, 10, MUTED, 'end'))
    for x in range(cols):
        body.append(text(pad + x * cell + cell / 2, pad - 8, x, 10, MUTED, 'middle'))
    for k, (points, color, label) in enumerate(paths):
        off = (k - (len(paths) - 1) / 2) * 5
        coords = ' '.join(f'{pad + px * cell + cell / 2 + off:.1f},{pad + py * cell + cell / 2 + off:.1f}' for px, py in points)
        body.append(f'<polyline points="{coords}" fill="none" stroke="{color}" stroke-width="3.2" stroke-linejoin="round" '
                    f'stroke-linecap="round" opacity=".9"/>')
        visits = {}
        for p in points:
            visits[tuple(p)] = visits.get(tuple(p), 0) + 1
        for (px, py), c in visits.items():
            if c > 2:
                cx, cy = pad + px * cell + cell / 2 + off + 13, pad + py * cell + cell / 2 + off + 13
                body.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="12" fill="{color}" stroke="#fff" stroke-width="1.5"/>')
                body.append(text(cx, cy + 3.5, f'×{c}', 9.5, '#fff', 'middle', 700))
    if title:
        body.append(text(width / 2, height - 6, title, 11.5, INK, 'middle', 600))
    else:
        height -= 22
    return svg(width, height, ''.join(body), title or '网格地图', max_width=int(width * 1.15))


def hbars(rows, width=760, label_w=190, fmt=lambda v: f'{v}', unit=''):
    """rows: [(label, value, color, note)] -> linear horizontal bars, value printed at bar end."""
    top = max(v for _, v, _, _ in rows) or 1
    bar_w, row_h = width - label_w - 170, 34
    body = []
    for i, (label, v, color, note) in enumerate(rows):
        y = 6 + i * row_h
        w = max(bar_w * v / top, 2.5)
        body.append(text(label_w - 10, y + 17, label, 12.5, INK, 'end', 600))
        body.append(f'<rect x="{label_w}" y="{y + 5}" width="{bar_w}" height="18" rx="9" fill="#f1f5f9"/>')
        body.append(f'<rect x="{label_w}" y="{y + 5}" width="{w:.1f}" height="18" rx="9" fill="{color}"/>')
        body.append(text(label_w + w + 8, y + 18, fmt(v) + unit, 12, INK, 'start', 700))
        if note:
            body.append(text(label_w + w + 8 + 7.2 * len(fmt(v) + unit), y + 18, note, 11, MUTED))
    return svg(width, 12 + row_h * len(rows), ''.join(body), '横向条形图', max_width=int(width * 1.2))


def stacked(rows, width=760, label_w=190):
    """rows: [(label, [(part_name, value, color)])] -> 100% stacked composition bars."""
    bar_w, row_h = width - label_w - 20, 34
    body = []
    for i, (label, parts) in enumerate(rows):
        y = 6 + i * row_h
        total = sum(v for _, v, _ in parts) or 1
        x = label_w
        body.append(text(label_w - 10, y + 17, label, 12.5, INK, 'end', 600))
        for name, v, color in parts:
            w = bar_w * v / total
            body.append(f'<rect x="{x:.1f}" y="{y + 5}" width="{w:.1f}" height="18" fill="{color}"/>')
            if w > 70:
                body.append(text(x + 8, y + 18, f'{name} {v / total:.0%}', 11, '#fff', 'start', 600))
            x += w
    return svg(width, 12 + row_h * len(rows), ''.join(body), '构成条形图', max_width=int(width * 1.2))


def donut(parts, size=180, label=''):
    """parts: [(name, value, color)]"""
    import math
    total = sum(v for _, v, _ in parts) or 1
    r, cx, cy, w = 64, size / 2, size / 2, 22
    angle, body = -math.pi / 2, []
    for name, v, color in parts:
        a2 = angle + 2 * math.pi * v / total
        large = 1 if a2 - angle > math.pi else 0
        x1, y1 = cx + r * math.cos(angle), cy + r * math.sin(angle)
        x2, y2 = cx + r * math.cos(a2 - 1e-6), cy + r * math.sin(a2 - 1e-6)
        body.append(f'<path d="M{x1:.2f},{y1:.2f} A{r},{r} 0 {large} 1 {x2:.2f},{y2:.2f}" fill="none" stroke="{color}" stroke-width="{w}"/>')
        angle = a2
    body.append(text(cx, cy + 2, total, 24, INK, 'middle', 700))
    body.append(text(cx, cy + 20, label, 10.5, MUTED, 'middle'))
    return svg(size, size, ''.join(body), label)


def _log_ticks(lo, hi):
    import math
    return [10 ** k for k in range(math.floor(math.log10(lo)), math.ceil(math.log10(hi)) + 1)]


def tradeoff_scatter(points, y_label, y_range, width=560, height=380, title=''):
    """Cost (log x) vs accuracy (y). points: dicts with keys
    name, cost, acc, total, lat, color, filled, group, note. Bubble area encodes median latency.
    Same-group points are joined; the Pareto frontier (cheaper or more accurate) is dashed.
    The right-hand secondary axis shows the same accuracy as a percentage of `total`."""
    import math
    left, right, top, bottom = 64, width - 58, 34, height - 50
    total = points[0]['total']
    lo = min(p['cost'] for p in points) / 1.8
    hi = max(p['cost'] for p in points) * 1.6
    ticks = _log_ticks(lo, hi)
    lo, hi = min(lo, ticks[0]), max(hi, ticks[-1])
    y0, y1 = y_range

    def X(v):
        return left + (math.log10(v) - math.log10(lo)) / (math.log10(hi) - math.log10(lo)) * (right - left)

    def Y(v):
        return bottom - (v - y0) / (y1 - y0) * (bottom - top)

    def R(lat):
        return 5 + 9 * math.sqrt(lat / max(p['lat'] for p in points))

    body = [text(left, 18, title, 12.5, INK, 'start', 700)] if title else []
    for t in ticks:
        x = X(t)
        body.append(f'<line x1="{x:.1f}" y1="{top}" x2="{x:.1f}" y2="{bottom}" stroke="{GRID}" stroke-dasharray="3 3"/>')
        body.append(text(x, bottom + 16, f'${t:g}', 10.5, MUTED, 'middle'))
    step = 5 if (y1 - y0) > 30 else 2
    for v in range(int(math.ceil(y0 / step) * step), int(y1) + 1, step):
        y = Y(v)
        body.append(f'<line x1="{left}" y1="{y:.1f}" x2="{right}" y2="{y:.1f}" stroke="{GRID}"/>')
        body.append(text(left - 8, y + 4, v, 10.5, MUTED, 'end'))
    body.append(text((left + right) / 2, height - 10, '本次总费用（美元，对数刻度）', 11, MUTED, 'middle'))
    body.append(f'<text transform="translate(16,{(top + bottom) / 2}) rotate(-90)" font-size="11" fill="{MUTED}" text-anchor="middle">{esc(y_label)}</text>')
    # Secondary axis: the same scale expressed as a percentage of total.
    body.append(f'<line x1="{right}" y1="{top}" x2="{right}" y2="{bottom}" stroke="{SLATE}" stroke-width="1"/>')
    pct_lo, pct_hi = y0 / total * 100, y1 / total * 100
    pstep = next(s for s in (1, 2, 5, 10, 20) if (pct_hi - pct_lo) / s <= 8)
    pct = math.ceil(pct_lo / pstep) * pstep
    while pct <= pct_hi + 1e-9:
        y = Y(pct / 100 * total)
        body.append(f'<line x1="{right}" y1="{y:.1f}" x2="{right + 4}" y2="{y:.1f}" stroke="{SLATE}"/>')
        body.append(text(right + 7, y + 4, f'{pct:g}%', 10.5, MUTED, 'start'))
        pct += pstep
    body.append(f'<text transform="translate({width - 6},{(top + bottom) / 2}) rotate(90)" font-size="11" fill="{MUTED}" '
                f'text-anchor="middle">准确率（%，共 {total} 题）</text>')
    # Pareto frontier: sort by cost; keep points that raise the best accuracy so far.
    front, best = [], -1
    for p in sorted(points, key=lambda p: (p['cost'], -p['acc'])):
        if p['acc'] > best:
            front.append(p)
            best = p['acc']
    if len(front) > 1:
        coords = ' '.join(f'{X(p["cost"]):.1f},{Y(p["acc"]):.1f}' for p in front)
        body.append(f'<polyline points="{coords}" fill="none" stroke="{TEAL}" stroke-width="1.6" stroke-dasharray="6 4" opacity=".8"/>')
    groups = {}
    for p in points:
        groups.setdefault(p['group'], []).append(p)
    for members in groups.values():
        if len(members) == 2:
            a, b = members
            body.append(f'<line x1="{X(a["cost"]):.1f}" y1="{Y(a["acc"]):.1f}" x2="{X(b["cost"]):.1f}" y2="{Y(b["acc"]):.1f}" '
                        f'stroke="{a["color"]}" stroke-width="2" opacity=".55"/>')
    for p in sorted(points, key=lambda p: -p['lat']):
        x, y, r = X(p['cost']), Y(p['acc']), R(p['lat'])
        fill = p['color'] if p['filled'] else '#ffffff'
        tip = (f'{p["name"]}：费用 ${p["cost"]:.6f}，答对 {p["acc"]}/{p["total"]}（{p["acc"] / p["total"]:.1%}），'
               f'中位耗时 {p["lat"]:.2f}s' + (f'，{p["note"]}' if p.get('note') else ''))
        body.append(f'<g><title>{esc(tip)}</title><circle cx="{x:.1f}" cy="{y:.1f}" r="{r:.1f}" fill="{fill}" '
                    f'fill-opacity="{.85 if p["filled"] else 1}" stroke="{p["color"]}" stroke-width="2.2"/></g>')
        if p.get('label'):
            if x + r + 8 + 7 * len(p['label']) > right:  # near the right edge: label above the bubble
                body.append(text(x, y - r - 7, p['label'], 11, INK, 'end' if x > right - 40 else 'middle', 650))
            else:
                body.append(text(x + r + 6, y + 4, p['label'], 11, INK, 'start', 650))
    return svg(width, height, ''.join(body), title or '成本与准确率')


def metric_strip(rows, acc_total_full, acc_total_norm, width=980):
    """Three aligned panels per row: cost (log bar), median latency with P90 tick, accuracy dots.
    rows: dicts name, cost, lat, p90, acc_full, acc_norm, color, flag."""
    import math
    label_w, row_h, top = 210, 30, 40
    panel = (width - label_w - 30) / 3
    gap = 22
    pw = panel - gap
    xs = [label_w + i * panel for i in range(3)]
    height = top + row_h * len(rows) + 30
    lo = min(r['cost'] for r in rows) / 2
    hi = max(r['cost'] for r in rows) * 1.5
    ticks = _log_ticks(lo, hi)
    lo, hi = ticks[0], ticks[-1]
    lat_max = max(r['p90'] for r in rows) * 1.08
    a_lo = min(min(r['acc_full'] / acc_total_full, r['acc_norm'] / acc_total_norm) for r in rows)
    a_lo = math.floor(a_lo * 20) / 20

    def cx(v):
        return xs[0] + (math.log10(v) - math.log10(lo)) / (math.log10(hi) - math.log10(lo)) * pw

    def lx(v):
        return xs[1] + v / lat_max * pw

    def ax(v):
        return xs[2] + (v - a_lo) / (1 - a_lo) * pw

    body = []
    for x, head in zip(xs, ['本次总费用（对数刻度）', '中位耗时（细线为 P90）',
                            f'准确率（● 全部 {acc_total_full} 题 · ○ 不含对照组 {acc_total_norm} 题）']):
        body.append(text(x, 16, head, 11.5, INK, 'start', 700))
    base = top + row_h * len(rows)
    for t in ticks:
        body.append(f'<line x1="{cx(t):.1f}" y1="{top - 6}" x2="{cx(t):.1f}" y2="{base}" stroke="{GRID}" stroke-dasharray="3 3"/>')
        body.append(text(cx(t), base + 16, f'${t:g}', 10, MUTED, 'middle'))
    step = 1 if lat_max <= 6 else 2
    for t in range(0, int(lat_max) + 1, step):
        body.append(f'<line x1="{lx(t):.1f}" y1="{top - 6}" x2="{lx(t):.1f}" y2="{base}" stroke="{GRID}" stroke-dasharray="3 3"/>')
        body.append(text(lx(t), base + 16, f'{t}s', 10, MUTED, 'middle'))
    # A wider accuracy range needs fewer labels to keep percentages readable.
    acc_step = next(s for s in (0.05, 0.1, 0.2, 0.25, 0.5) if pw * s / (1 - a_lo) >= 34)
    k = round(math.ceil(a_lo / acc_step - 1e-9) * acc_step, 2)
    while k <= 1.0001:
        body.append(f'<line x1="{ax(k):.1f}" y1="{top - 6}" x2="{ax(k):.1f}" y2="{base}" stroke="{GRID}" stroke-dasharray="3 3"/>')
        body.append(text(ax(k), base + 16, f'{k:.0%}', 10, MUTED, 'middle'))
        k = round(k + acc_step, 2)
    for i, r in enumerate(rows):
        y = top + i * row_h
        if i % 2:
            body.append(f'<rect x="0" y="{y - 2}" width="{width}" height="{row_h}" fill="#f8fafc"/>')
        body.append(text(label_w - 10, y + 16, r['name'], 12, INK, 'end', 600))
        w = max(cx(r['cost']) - xs[0], 2)
        body.append(f'<g><title>{esc(r["name"])}：${r["cost"]:.6f}</title><rect x="{xs[0]}" y="{y + 5}" width="{w:.1f}" height="14" rx="7" fill="{r["color"]}"/></g>')
        if w > pw - 60:  # long bar: print the value inside so it never spills into the next panel
            body.append(text(xs[0] + w - 6, y + 16, f'${r["cost"]:.4f}', 10.5, '#fff', 'end', 700))
        else:
            body.append(text(xs[0] + w + 6, y + 16, f'${r["cost"]:.4f}', 10.5, INK, 'start', 600))
        w = max(lx(r['lat']) - xs[1], 2)
        body.append(f'<g><title>{esc(r["name"])}：中位 {r["lat"]:.2f}s，P90 {r["p90"]:.2f}s</title>'
                    f'<rect x="{xs[1]}" y="{y + 5}" width="{w:.1f}" height="14" rx="7" fill="{r["color"]}"/></g>')
        body.append(f'<line x1="{lx(r["p90"]):.1f}" y1="{y + 3}" x2="{lx(r["p90"]):.1f}" y2="{y + 21}" stroke="{INK}" stroke-width="1.5"/>')
        body.append(text(lx(r['p90']) + 5, y + 16, f'{r["lat"]:.2f}s', 10.5, INK, 'start', 600))
        f_full, f_norm = r['acc_full'] / acc_total_full, r['acc_norm'] / acc_total_norm
        body.append(f'<line x1="{ax(min(f_full, f_norm)):.1f}" y1="{y + 12}" x2="{ax(max(f_full, f_norm)):.1f}" y2="{y + 12}" stroke="{r["color"]}" stroke-width="2" opacity=".5"/>')
        body.append(f'<g><title>{esc(r["name"])}：全部 {r["acc_full"]}/{acc_total_full}（{f_full:.1%}），'
                    f'不含网格误用对照组 {r["acc_norm"]}/{acc_total_norm}（{f_norm:.1%}）</title>'
                    f'<circle cx="{ax(f_full):.1f}" cy="{y + 12}" r="6" fill="{r["color"]}"/>'
                    f'<circle cx="{ax(f_norm):.1f}" cy="{y + 12}" r="6" fill="#fff" stroke="{r["color"]}" stroke-width="2.2"/></g>')
        label = f'{r["acc_full"]} / {r["acc_norm"]}' + (' ⚠' if r.get('flag') else '')
        body.append(text(xs[2] + pw + 4, y + 16, label, 10.5, INK, 'start', 600))
    return svg(width + 70, height, ''.join(body), '成本、耗时与准确率三联图')
