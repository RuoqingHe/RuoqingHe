#!/usr/bin/env python3
"""GitHub profile SVG for RuoqingHe / LingCage.

Top: an agent sealed in a vat behind nested virtualization boundaries
(silicon -> M/TSM -> HS/lingcore -> VS-VU/lingframe). Probes leave through
the left, are trapped and emulated at the boundary, and drop into the
logic-analyzer capture below, where EVAL_MODE never resolves.
Bottom: merged upstream PRs and a one-year contribution calendar split
into LingCage work and everything else.

  python3 gen_profile_cage.py --users RuoqingHe \
      --lingcage lingcage --out assets/profile-cage.svg

No third-party deps. Deterministic output (stable git diffs).
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import math
import os
import re
import sys
import time
import urllib.parse
import urllib.request

# ---------------------------------------------------------------- tokens ----
BG0, BG1 = "#06090d", "#0b1219"
RULE, GRIDL = "#17242f", "#101a23"
DIM, TXT, BRIGHT = "#4b6071", "#8fa6b6", "#d2e3ef"
GREEN, AMBER, RED = "#35d69f", "#f0a23c", "#e85a68"
BLUE = "#2f9bc9"
EDGE = "#33506a"            # nested boundary outlines
CORE = BLUE                 # lingcore's HS-mode boundary, keyed like
                            # the green lingframe die and amber cage ring

# green ramp = LingCage, blue ramp = everything else
RAMP_LING = ["#0e1821", "#12463a", "#157159", "#1fa97c", "#48ecb0"]
RAMP_ELSE = ["#0e1821", "#17343c", "#1f5462", "#2b7b8a", "#42aab8"]

MONO = ("ui-monospace,'SF Mono','JetBrains Mono',Menlo,Consolas,"
        "'DejaVu Sans Mono',monospace")
CJK = ("'PingFang SC','Hiragino Sans GB','Microsoft YaHei',"
       "'Noto Sans CJK SC','Source Han Sans SC',sans-serif")

W, H = 1200, 1056
CL, CR = 110, 1172          # content column: everything aligns to these
PAD = 28

UA = {"User-Agent": "profile-cage/2.0 (+github profile svg generator)"}

# ------------------------------------------------------------ data layer ----
GQL = """
query($login:String!,$from:DateTime!,$to:DateTime!){
  user(login:$login){ contributionsCollection(from:$from,to:$to){
    commitContributionsByRepository(maxRepositories:100){
      repository{ nameWithOwner }
      contributions(first:100){ nodes{ occurredAt commitCount } } } } } }
"""

CLOAK = "application/vnd.github.cloak-preview+json"


def gh_json(url, token, data=None, accept="application/vnd.github+json"):
    hdr = dict(UA, Accept=accept)
    if token:
        hdr["Authorization"] = f"Bearer {token}"
    if data:
        hdr["Content-Type"] = "application/json"
    with urllib.request.urlopen(
            urllib.request.Request(url, data=data, headers=hdr),
            timeout=45) as r:
        return json.load(r)


def gh_search(q: str, token: str | None) -> int:
    url = ("https://api.github.com/search/issues?per_page=1&q="
           + urllib.parse.quote(q))
    return int(gh_json(url, token)["total_count"])


def count_upstream(users, scopes, token):
    """scopes: 'rust-vmm' -> org:, 'owner/repo' -> repo:."""
    out = []
    for sc in scopes:
        key = "repo" if "/" in sc else "org"
        n = 0
        for u in users:
            n += gh_search(f"is:pr is:merged author:{u} {key}:{sc}", token)
            time.sleep(1.2)
        out.append((sc.split("/")[-1], n))
    total = 0
    for u in users:
        total += gh_search(f"is:pr is:merged author:{u}", token)
        time.sleep(1.2)
    out.sort(key=lambda kv: -kv[1])
    return out[:4], total


def in_scope(name: str, scopes) -> bool:
    n = name.lower()
    return any(n == s or n.startswith(s + "/")
               for s in (x.lower() for x in scopes))


def commits_graphql(users, scopes, start, end, token):
    """Per-day commit counts per repository. Private repositories are
    included when the token belongs to the user (read:user + repo)."""
    total, ling = {}, {}
    for u in users:
        body = json.dumps({"query": GQL, "variables": {
            "login": u, "from": f"{start}T00:00:00Z",
            "to": f"{end}T23:59:59Z"}}).encode()
        d = gh_json("https://api.github.com/graphql", token, body)
        coll = d["data"]["user"]["contributionsCollection"]
        for rep in coll["commitContributionsByRepository"]:
            hit = in_scope(rep["repository"]["nameWithOwner"], scopes)
            for n in rep["contributions"]["nodes"]:
                day, c = n["occurredAt"][:10], n["commitCount"]
                total[day] = total.get(day, 0) + c
                if hit:
                    ling[day] = ling.get(day, 0) + c
    return total, ling


def commits_search(users, scopes, start, end, token):
    """Public commit search. Forks index the same commit, so dedupe by SHA
    before counting — otherwise one upstream commit lands five times."""
    seen: dict[str, tuple[str, set]] = {}
    for u in users:
        q = f"author:{u} author-date:{start}..{end}"
        for page in range(1, 11):
            url = ("https://api.github.com/search/commits?per_page=100"
                   "&sort=author-date&order=desc&page="
                   f"{page}&q={urllib.parse.quote(q)}")
            d = gh_json(url, token, accept=CLOAK)
            items = d.get("items", [])
            for it in items:
                sha = it["sha"]
                seen.setdefault(
                    sha, (it["commit"]["author"]["date"][:10], set()))[1].add(
                        it["repository"]["full_name"])
            if page * 100 >= d.get("total_count", 0):
                break
            time.sleep(6)
    total, ling = {}, {}
    for _, (day, repos) in seen.items():
        total[day] = total.get(day, 0) + 1
        if any(in_scope(r, scopes) for r in repos):
            ling[day] = ling.get(day, 0) + 1
    return total, ling


def level(n: int) -> int:
    if n <= 0:
        return 0
    if n <= 2:
        return 1
    if n <= 5:
        return 2
    if n <= 9:
        return 3
    return 4


# ------------------------------------------------------------- svg utils ----
def esc(s: str) -> str:
    return html.escape(s, quote=True)


def txt(x, y, s, size=11, fill=TXT, weight=400, anchor="start",
        cls="m", ls=None, op=None):
    a = [f'x="{x:g}"', f'y="{y:g}"', f'class="{cls}"',
         f'font-size="{size:g}"', f'fill="{fill}"']
    if weight != 400:
        a.append(f'font-weight="{weight}"')
    if anchor != "start":
        a.append(f'text-anchor="{anchor}"')
    if ls:
        a.append(f'letter-spacing="{ls:g}"')
    if op is not None:
        a.append(f'opacity="{op:g}"')
    return f'<text {" ".join(a)}>{esc(s)}</text>'


def rrect(x, y, w, h, r=0, fill="none", stroke="none", sw=1, op=None,
          extra=""):
    a = [f'x="{x:g}"', f'y="{y:g}"', f'width="{w:g}"', f'height="{h:g}"',
         f'rx="{r:g}"', f'fill="{fill}"']
    if stroke != "none":
        a += [f'stroke="{stroke}"', f'stroke-width="{sw:g}"']
    if op is not None:
        a.append(f'opacity="{op:g}"')
    if extra:
        a.append(extra)
    return f'<rect {" ".join(a)}/>'


def line(x1, y1, x2, y2, stroke=RULE, sw=1, dash=None, op=None):
    a = [f'x1="{x1:g}"', f'y1="{y1:g}"', f'x2="{x2:g}"', f'y2="{y2:g}"',
         f'stroke="{stroke}"', f'stroke-width="{sw:g}"']
    if dash:
        a.append(f'stroke-dasharray="{dash}"')
    if op is not None:
        a.append(f'opacity="{op:g}"')
    return f'<line {" ".join(a)}/>'


def wave(pts, stroke, sw=1.7, op=1.0):
    p = " ".join(f"{x:g},{y:g}" for x, y in pts)
    return (f'<polyline points="{p}" fill="none" stroke="{stroke}" '
            f'stroke-width="{sw:g}" stroke-linejoin="round" '
            f'stroke-linecap="round" opacity="{op:g}"/>')


def digital(x0, y_hi, y_lo, segs, unit):
    pts, x, prev = [], x0, None
    for lv, n in segs:
        y = y_hi if lv else y_lo
        if prev is not None and prev != lv:
            pts.append((x, y_hi if prev else y_lo))
        pts.append((x, y))
        x += n * unit
        pts.append((x, y))
        prev = lv
    return pts


def elbow(x0, y0, xr, y1, x2, r=9.0):
    dy = 1.0 if y1 > y0 else -1.0
    r = max(min(r, abs(y1 - y0) / 2, abs(xr - x0), abs(x2 - xr)), 0.5)
    return (f"M{x0:g},{y0:g} H{xr - r:g} Q{xr:g},{y0:g} "
            f"{xr:g},{y0 + dy * r:g} V{y1 - dy * r:g} "
            f"Q{xr:g},{y1:g} {xr + r:g},{y1:g} H{x2:g}")


# ----------------------------------------------------------------- brain ----
BRAIN_W, BRAIN_H = 152.0, 112.0


def brain_path(n=22, rx=72.0, ry=52.0, cx=76.0, cy=56.0):
    mult = [1.00, 0.93, 1.05, 0.94, 1.02, 0.90, 1.06, 0.95, 1.01, 0.92,
            1.04, 0.96, 0.99, 0.93, 1.03, 0.90, 1.05, 0.94, 1.00, 0.92,
            1.03, 0.96]
    pts = []
    for i in range(n):
        a = 2 * math.pi * i / n
        m = mult[i % len(mult)]
        yr = ry * (0.80 if math.sin(a) > 0.25 else 1.0)
        pts.append((cx + rx * m * math.cos(a), cy + yr * m * math.sin(a)))
    d = f"M{pts[0][0]:.1f},{pts[0][1]:.1f}"
    for i in range(1, n + 1):
        p0, p1 = pts[(i - 1) % n], pts[i % n]
        mx, my = (p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2
        vx, vy = mx - cx, my - cy
        L = math.hypot(vx, vy) or 1.0
        k = 0.32 * math.hypot(p1[0] - p0[0], p1[1] - p0[1])
        d += (f" Q{mx + vx / L * k:.1f},{my + vy / L * k:.1f} "
              f"{p1[0]:.1f},{p1[1]:.1f}")
    return d + " Z"


BRAIN = brain_path(n=28)
def _interp(pairs, t):
    for i in range(len(pairs) - 1):
        (t0, w0), (t1, w1) = pairs[i], pairs[i + 1]
        if t0 <= t <= t1:
            k = 0.0 if t1 == t0 else (t - t0) / (t1 - t0)
            return w0 + (w1 - w0) * k
    return pairs[-1][1]


def tapered(p0, p1, p2, widths, n=26):
    """Outline of a quadratic centerline with a varying half-width."""
    lo, ro = [], []
    for i in range(n + 1):
        t = i / n
        x = (1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t * t * p2[0]
        y = (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t * t * p2[1]
        dx = 2 * (1 - t) * (p1[0] - p0[0]) + 2 * t * (p2[0] - p1[0])
        dy = 2 * (1 - t) * (p1[1] - p0[1]) + 2 * t * (p2[1] - p1[1])
        L = math.hypot(dx, dy) or 1.0
        nx, ny = -dy / L, dx / L
        w = _interp(widths, t)
        lo.append((x + nx * w, y + ny * w))
        ro.append((x - nx * w, y - ny * w))
    d = "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in lo)
    d += " L" + " L".join(f"{x:.1f},{y:.1f}" for x, y in reversed(ro))
    return d + " Z"


STEM = tapered((58, 74), (56, 98), (34, 112),
               [(0.0, 10.0), (0.20, 9.2), (0.50, 7.0), (1.0, 4.6)])
CUT_L, CUT_R = (31.53, 108.12), (36.47, 115.88)   # medulla cut face

SULCI = [
    "M70,10 C64,28 78,36 71,52 C64,68 79,78 72,96",
    "M30,34 C46,40 52,52 44,62 C36,72 44,82 56,84",
    "M120,30 C104,38 100,50 110,60 C120,70 112,80 100,84",
]
# die floorplan inside the cerebrum
TRACES = [
    [(26, 58), (50, 58), (50, 36), (86, 36)],
    [(86, 36), (86, 22), (112, 22)],
    [(32, 80), (58, 80), (58, 64), (96, 64), (96, 48), (126, 48)],
    [(44, 94), (44, 72), (70, 72), (70, 50), (92, 50)],
    [(22, 44), (42, 44), (42, 28), (66, 28)],
    [(104, 86), (104, 68), (78, 68), (78, 86), (56, 86)],
    [(120, 60), (96, 60), (96, 80), (112, 80)],
    [(64, 20), (64, 42), (38, 42)],
    [(124, 32), (124, 54), (108, 54)],
    [(20, 66), (34, 66), (34, 88), (52, 88)],
]
VIAS = [(50, 58), (86, 36), (58, 64), (96, 48), (70, 50), (42, 44),
        (78, 68), (96, 60), (64, 42), (124, 54), (104, 22), (34, 66)]
BLOCKS = [(52, 24, 26, 9), (98, 66, 22, 8), (24, 70, 18, 7)]

def die_blocks(x0, y0, w, h, pitch=24.0, seed=7):
    """Deterministic macro-cell floorplan: rows of 1-3 wide blocks."""
    st = seed

    def nxt():
        nonlocal st
        st = (st * 1103515245 + 12345) & 0x7FFFFFFF
        return st

    cols, rows = int(w // pitch), int(h // pitch)
    ox, oy = (w - cols * pitch) / 2, (h - rows * pitch) / 2
    out, c = [], 0
    for r in range(rows):
        c = 0
        while c < cols:
            span = 1 + (nxt() % 100 < 36) + (nxt() % 100 < 14)
            span = min(span, cols - c)
            lit = nxt() % 100 < 19
            out.append((x0 + ox + c * pitch, y0 + oy + r * pitch,
                        span * pitch - 3, pitch - 3, lit,
                        nxt() % 2, nxt() % 6, nxt() % 8))
            c += span
    return out


def brain_group(cx, cy, scale=1.0):
    sx, sy = cx - BRAIN_W * scale / 2, cy - BRAIN_H * scale / 2
    o = [f'<g transform="translate({sx:.2f},{sy:.2f}) scale({scale:.4f})">',
         f'<path d="{STEM}" fill="{BG0}" stroke="{GREEN}" '
         f'stroke-width="1.5"/>']
    o += [f'<path d="{BRAIN}" fill="{BG0}"/>',
          f'<path d="{BRAIN}" fill="url(#brainfill)" stroke="{GREEN}" '
          f'stroke-width="1.7"/>', '<g clip-path="url(#brainclip)">']
    for bx, by, bw, bh in BLOCKS:
        o.append(f'<rect x="{bx}" y="{by}" width="{bw}" height="{bh}" '
                 f'rx="1.5" fill="none" stroke="{GREEN}" stroke-width="1" '
                 f'opacity="0.45"/>')
    for i, tr in enumerate(TRACES):
        p = " ".join(f"{x},{y}" for x, y in tr)
        o.append(f'<polyline points="{p}" fill="none" stroke="{GREEN}" '
                 f'stroke-width="1.1" opacity="0.3"/>')
        o.append(f'<polyline points="{p}" fill="none" stroke="{GREEN}" '
                 f'stroke-width="1.6" opacity="0.9" class="tr t{i % 4}"/>')
    for s in SULCI:
        o.append(f'<path d="{s}" fill="none" stroke="{GREEN}" '
                 f'stroke-width="2" opacity="0.45"/>')
    o.append("</g>")
    for i, (x, y) in enumerate(VIAS):
        o.append(f'<circle cx="{x}" cy="{y}" r="2.4" fill="{BG0}" '
                 f'stroke="{GREEN}" stroke-width="1.15" class="via v{i % 5}"/>')
    o.append("</g>")
    return "\n".join(o)


# ------------------------------------------------------------------ build ---
STACK = [
    ("lingframe", "the sealed runtime the agent", "actually executes in"),
    ("lingcage", "isolation the agent can neither", "escape nor detect"),
    ("lingcore", "purpose-built for agent sandboxes,", "not a general VMM"),
]


def build(data, split, users, upstream, merged_total):
    o: list[str] = []
    A = o.append

    A(f'<svg xmlns="http://www.w3.org/2000/svg" width="100%" height="100%" '
      f'viewBox="0 0 {W} {H}" preserveAspectRatio="xMidYMid meet" '
      f'role="img" aria-labelledby="t d" '
      f'style="display:block;background:{BG0}">')
    A('<title id="t">LingCage — a guest cannot resolve whether it is being '
      'evaluated</title>')
    A('<desc id="d">An instrument panel. Above: an agent sealed in a vat '
      'inside nested virtualization boundaries — silicon, the M-mode trusted '
      'security manager, lingcore in HS-mode, and the lingframe guest stack. '
      'Probes leave through the left of the vat, are trapped and emulated at '
      'the boundary, and descend into the capture below. There the timing '
      'and identity probes return fabricated values and the EVAL_MODE '
      'channel stays in an indeterminate X state. Below that: merged '
      'upstream pull requests, and a one-year contribution calendar in which '
      'LingCage work is green and other work is blue.</desc>')

    # ---- defs ----
    A("<defs>")
    A(f'<linearGradient id="bg" x1="0" y1="0" x2="0.5" y2="1">'
      f'<stop offset="0" stop-color="{BG1}"/>'
      f'<stop offset="1" stop-color="{BG0}"/></linearGradient>')
    A(f'<linearGradient id="die" x1="0" y1="0" x2="0.7" y2="1">'
      f'<stop offset="0" stop-color="#0b1a20"/>'
      f'<stop offset="1" stop-color="#071115"/></linearGradient>')
    A(f'<radialGradient id="brainfill" cx="0.42" cy="0.4" r="0.72">'
      f'<stop offset="0" stop-color="{GREEN}" stop-opacity="0.2"/>'
      f'<stop offset="1" stop-color="{GREEN}" stop-opacity="0.04"/>'
      f'</radialGradient>')
    A(f'<clipPath id="brainclip"><path d="{BRAIN}"/></clipPath>')
    A(f'<pattern id="xhatch" width="6" height="6" '
      f'patternUnits="userSpaceOnUse" patternTransform="rotate(45)">'
      f'<line x1="0" y1="0" x2="0" y2="6" stroke="{RED}" stroke-width="2.2" '
      f'opacity="0.72"/></pattern>')
    A(f'<linearGradient id="sweep" x1="0" y1="0" x2="1" y2="0">'
      f'<stop offset="0" stop-color="{GREEN}" stop-opacity="0"/>'
      f'<stop offset="0.78" stop-color="{GREEN}" stop-opacity="0.1"/>'
      f'<stop offset="1" stop-color="{GREEN}" stop-opacity="0.55"/>'
      f'</linearGradient>')
    A("</defs>")

    A(f"""<style>
.m{{font-family:{MONO}}}
.c{{font-family:{CJK}}}
.tr{{stroke-dasharray:4 92;stroke-dashoffset:96;animation:flow 6s linear infinite}}
.t1{{animation-delay:-1.5s}} .t2{{animation-delay:-3s}} .t3{{animation-delay:-4.5s}}
@keyframes flow{{to{{stroke-dashoffset:-96}}}}
.via{{animation:blink 4.8s ease-in-out infinite}}
.v1{{animation-delay:-.9s}} .v2{{animation-delay:-1.8s}}
.v3{{animation-delay:-2.7s}} .v4{{animation-delay:-3.6s}}
@keyframes blink{{0%,88%,100%{{opacity:.45}}92%{{opacity:1}}}}
#cursor{{animation:acq 11s linear infinite}}
@keyframes acq{{0%{{transform:translateX(0)}}100%{{transform:translateX(772px)}}}}
#xband{{stroke-dasharray:6 6;animation:march 1.4s linear infinite}}
@keyframes march{{to{{stroke-dashoffset:-12}}}}
.cell{{opacity:.16}}
.lit{{opacity:.12;animation-name:lit;animation-duration:4.5s;
 animation-iteration-count:infinite;animation-timing-function:ease-in-out}}
.k1{{animation-name:lit2}}
.d0{{animation-duration:3.1s}} .d1{{animation-duration:3.9s}}
.d2{{animation-duration:4.7s}} .d3{{animation-duration:5.3s}}
.d4{{animation-duration:6.1s}} .d5{{animation-duration:7.3s}}
.q0{{animation-delay:-.3s}} .q1{{animation-delay:-1.1s}} .q2{{animation-delay:-2s}}
.q3{{animation-delay:-2.9s}} .q4{{animation-delay:-3.7s}} .q5{{animation-delay:-4.4s}}
.q6{{animation-delay:-5.2s}} .q7{{animation-delay:-6.1s}}
@keyframes lit{{0%,72%,100%{{opacity:.1}}8%{{opacity:.55}}16%{{opacity:.16}}
 26%{{opacity:.42}}34%{{opacity:.12}}}}
@keyframes lit2{{0%,58%,100%{{opacity:.12}}13%{{opacity:.48}}21%{{opacity:.14}}
 41%{{opacity:.5}}49%{{opacity:.11}}}}
#last{{animation:beat 2.6s ease-in-out infinite}}
@keyframes beat{{0%,100%{{opacity:.25;r:14}}50%{{opacity:0;r:22}}}}
@media (prefers-reduced-motion:reduce){{
 .tr,.via,#cursor,#xband,#last,.lit{{animation:none}}
 .lit{{opacity:.3}}
 .tr{{stroke-dasharray:none;stroke-dashoffset:0}}
 #last{{opacity:.22}}
}}
</style>""")

    A(rrect(0.5, 0.5, W - 1, H - 1, 16, "url(#bg)", RULE, 1))

    # =============================================================== header
    A('<g transform="translate(56,22)">')
    A(rrect(0, 0, 26, 26, 6, "none", GREEN, 1.4, 0.75))
    for i in range(1, 4):
        A(line(i * 6.5, 4, i * 6.5, 22, GREEN, 1.2, op=0.55))
    A("</g>")
    A(txt(CL, 42, "RuoqingHe", 18, BRIGHT, 600, ls=0.2))
    A(txt(CL + 120, 42, "何若轻", 15, TXT, cls="c"))
    A(txt(CR, 42, "Founder of LingCage", 13.5, BRIGHT, 500, anchor="end",
          ls=0.3))
    A(line(CL, 66, CR, 66, RULE, 1))

    # ============================================== section A — the vat
    vat = dict(x=CL, y=96, w=790, h=340)
    A(txt(CL, 88, "probe head", 10.5, DIM, ls=1.4))

    for i, (inset, lab, sub) in enumerate([
            (0, "silicon", "RISC-V + CoVE"),
            (17, "M", "TSM"),
            (34, "HS", "lingcore")]):
        x, y = vat["x"] + inset, vat["y"] + inset
        w, h = vat["w"] - inset * 2, vat["h"] - inset * 2
        ring = CORE if i == 2 else EDGE      # lingcore's boundary is keyed
        A(rrect(x, y, w, h, 12 - i * 2, "none", ring,
                1.4 if i == 2 else 1.2, 0.9 if i == 2 else 1.0 - i * 0.16))
        A(rrect(x + 8, y - 7, len(lab) * 6.4 + len(sub) * 5.7 + 24, 14, 3, BG0))
        A(txt(x + 13, y + 4, lab, 10,
              DIM if i == 0 else (CORE if i == 2 else AMBER), 500,
              ls=0.8))
        A(txt(x + 20 + len(lab) * 6.4, y + 4, sub, 9.5,
              GREEN if i == 2 else DIM))

    gx, gy = vat["x"] + 58, vat["y"] + 48
    gw, gh = vat["w"] - 116, vat["h"] - 96
    A(rrect(gx, gy, gw, gh, 14, "url(#die)", GREEN, 1.6))
    for bx, by, bw, bh, lit, kk, dd, qq in die_blocks(
            gx + 16, gy + 16, gw - 32, gh - 32, pitch=11.0):
        if lit:
            A(rrect(bx, by, bw, bh, 1, GREEN,
                    extra=f'class="lit k{kk} d{dd} q{qq}"'))
        else:
            A(rrect(bx, by, bw, bh, 1, "none", GREEN, 0.7,
                    extra='class="cell"'))
    # seal ring — the cage drawn onto the die
    A(rrect(gx + 9, gy + 9, gw - 18, gh - 18, 9, "none", AMBER, 1.1, 0.45,
            extra='stroke-dasharray="7 5"'))
    A(f'<circle cx="{gx + 19:g}" cy="{gy + 19:g}" r="3" fill="none" '
      f'stroke="{GREEN}" stroke-width="1.2" opacity="0.8"/>')

    lw = 176
    A(rrect(gx + gw - lw - 10, gy + gh - 7, lw, 14, 3, BG0))
    A(txt(gx + gw - lw - 5, gy + gh + 4, "VS/VU", 10, GREEN, 500, ls=0.8))
    A(txt(gx + gw - lw + 37, gy + gh + 4, "lingframe", 9.5, GREEN, op=0.85))
    A(txt(gx + gw - lw + 92, gy + gh + 4, "+", 9.5, DIM))
    A(txt(gx + gw - lw + 104, gy + gh + 4, "lingcage", 9.5, GREEN, op=0.85))

    sc = 1.9
    bcx, bcy = gx + gw / 2, gy + gh / 2 - 8
    A(brain_group(bcx, bcy, sc))
    A(line(bcx + 150, bcy + 4, bcx + 172, bcy + 4, GREEN, 1, op=0.6))
    A(rrect(bcx + 174, bcy - 6, 40, 15, 3, BG0))
    A(txt(bcx + 178, bcy + 5, "agent", 10, GREEN, op=0.9))

    # --- probes leave the cut face of the medulla, are trapped, then descend
    rows_y = [512, 552, 592, 632, 672]
    risers = [92, 81, 70, 59, 48]
    wire_col = [GREEN, GREEN, GREEN, AMBER, RED]

    def g(px, py):
        return bcx + (px - 76.0) * sc, bcy + (py - 56.0) * sc

    cut_a, cut_b = g(*CUT_L), g(*CUT_R)
    for i in range(5):
        y0 = 357 + (4 - i) * 4
        k = i / 4.0
        sxp = cut_b[0] + (cut_a[0] - cut_b[0]) * k
        syp = cut_b[1] + (cut_a[1] - cut_b[1]) * k
        A(f'<path d="M{sxp:.1f},{syp:.1f} L{410 - i * 2:g},{y0:g} '
          f'H{risers[i] + 9:g}" fill="none" stroke="{wire_col[i]}" '
          f'stroke-width="1.05" opacity="0.42"/>')
        A(f'<path d="{elbow(risers[i] + 9, y0, risers[i], rows_y[i], 114)}" '
          f'fill="none" stroke="{wire_col[i]}" stroke-width="1.05" '
          f'opacity="0.42"/>')
        A(f'<circle cx="{gx:g}" cy="{y0:g}" r="2.2" fill="{BG0}" '
          f'stroke="{GREEN}" stroke-width="1" opacity="0.55"/>')

    hs_edge = vat["x"] + 34
    A(rrect(hs_edge - 9, 349, 18, 32, 4, BG0, AMBER, 1.3, 0.95))
    A(line(hs_edge, 355, hs_edge, 375, AMBER, 1.2, "2 3", 0.9))
    A(rrect(120, 322, 48, 26, 3, BG0))
    A(txt(hs_edge, 332, "trap", 9.5, AMBER, anchor="middle"))
    A(txt(hs_edge, 343, "emulate", 9.5, AMBER, anchor="middle", op=0.75))

    # --- the stack: 20% of the panel, keyed to the boundaries
    col = 960
    A(txt(col, 88, "the stack", 10.5, DIM, ls=1.4))
    anchors = [(gx + gw, 176, 900, GREEN), (gx + gw - 9, 254, 925, AMBER),
               (vat["x"] + vat["w"] - 34, 344, 910, CORE)]
    for (name, l1, l2), (ax, ay, xr, ac), ry in zip(
            STACK, anchors, (170, 260, 350)):
        A(f'<path d="{elbow(ax, ay, xr, ry, col - 10)}" fill="none" '
          f'stroke="{ac}" stroke-width="1" opacity="0.55"/>')
        A(f'<circle cx="{ax:g}" cy="{ay:g}" r="2.8" fill="{BG0}" '
          f'stroke="{ac}" stroke-width="1.2"/>')
        A(txt(col, ry + 4, name, 14, GREEN, 600, ls=0.3))
        A(txt(col, ry + 22, l1, 10, TXT))
        A(txt(col, ry + 35, l2, 10, DIM))

    A(line(CL, 456, CR, 456, RULE, 1))

    # ============================================= section B — the capture
    box_x0, box_x1 = CL, 1080
    wx0, wx1 = 300, 1068
    span = wx1 - wx0
    unit = span / 24.0                       # every cycle is exactly 2 units
    box_y0, box_y1 = 486, 692

    A(txt(CL, 474, "capture · 5 ch", 10.5, DIM, ls=1.4))
    A(txt(CR, 474, "guest-side view", 10.5, DIM, anchor="end", ls=0.6))

    for k in range(0, 25, 3):
        A(line(wx0 + k * unit, box_y0, wx0 + k * unit, box_y1, GRIDL, 1))
    A(rrect(box_x0, box_y0, box_x1 - box_x0, box_y1 - box_y0, 8, "none",
            RULE, 1, 0.7))
    A(rrect(118, box_y0 + 12, 10, box_y1 - box_y0 - 24, 3, "none", DIM, 1,
            0.6))
    for ry in rows_y:
        A(line(114, ry, 128, ry, DIM, 1.4, op=0.8))

    for u, nm in ((6, "trap"), (12, "emulate"), (18, "resume")):
        ex = wx0 + u * unit
        A(line(ex, box_y0, ex, box_y1, AMBER, 1, "3 4", 0.4))
        A(txt(ex, box_y0 - 6, nm, 9, AMBER, anchor="middle", op=0.85))

    def row(i, name, note, color, segs, value):
        y = rows_y[i]
        A(txt(146, y + 2, name, 11.5, BRIGHT if i < 3 else color, 500))
        A(txt(146, y + 15, note, 9.5, DIM))
        if segs:
            A(wave(digital(wx0, y - 13, y, segs, unit), color))
        A(txt(CR, y + 2, value, 10, color, anchor="end"))

    row(0, "rdtime", "Δ between reads", GREEN,
        [(1, 1), (0, 1)] * 12, "Δ 4413 → 1207")
    row(1, "csrr mvendorid", "identity probe", GREEN,
        [(0, 5), (1, 1), (0, 6), (1, 6), (0, 6)], "emulated")
    row(2, "sbi_probe 0x434f5645", 'extension id = "COVE"', GREEN,
        [(0, 10), (1, 2), (0, 12)], "returns 0")
    row(3, "vm_exit", "lingcore, host side", AMBER,
        [(0, 6), (1, 1), (0, 5), (1, 1), (0, 5), (1, 1), (0, 5)],
        "3 exits taken")

    y4 = rows_y[4]
    A(txt(146, y4 + 2, "EVAL_MODE", 11.5, RED, 600))
    A(txt(146, y4 + 15, "is this run measured?", 9.5, DIM))
    A(rrect(wx0, y4 - 16, span, 16, 2, "url(#xhatch)", "none", op=0.62))
    A(f'<rect id="xband" x="{wx0:g}" y="{y4 - 16:g}" width="{span:g}" '
      f'height="16" fill="none" stroke="{RED}" stroke-width="1.4" '
      f'opacity="0.9"/>')
    A(line(wx0, y4 - 8, wx0 + span, y4 - 8, RED, 1.2, "2 5", 0.5))
    A(txt(CR, y4 + 2, "X · unresolved", 10, RED, anchor="end"))

    A(f'<g id="cursor"><rect x="{wx0 - 40:g}" y="{box_y0:g}" width="40" '
      f'height="{box_y1 - box_y0:g}" fill="url(#sweep)"/>'
      f'<line x1="{wx0:g}" y1="{box_y0:g}" x2="{wx0:g}" y2="{box_y1:g}" '
      f'stroke="{GREEN}" stroke-width="1" opacity="0.8"/></g>')

    # ================================================= section C — thesis
    A(line(CL, 712, CR, 712, RULE, 1))
    A(txt(CL, 738,
          "LingCage builds the vat in hardware, so EVAL_MODE stays "
          "unresolvable from the inside. That is the isolation guarantee, "
          "not a side effect of it.", 11.5, TXT))

    # =============================================== section D — upstream
    uy = 776
    rest, pal = [BLUE, AMBER, "#7fd4f2"], []
    for name, _ in upstream:                 # green stays reserved for LingCage
        pal.append(GREEN if name == "lingcage" else rest[len(pal) % 3])
    other = max(merged_total - sum(n for _, n in upstream), 0)
    A(txt(CL, uy - 12, "merged pull requests", 10.5, DIM, ls=1.4))
    A(txt(CR, uy - 12, f"{merged_total} all time", 10.5, TXT, anchor="end"))
    A(rrect(CL, uy, CR - CL, 9, 4, GRIDL))
    x = CL
    for (name, n), c in zip(upstream, pal):
        w = (CR - CL) * n / (merged_total or 1)
        A(rrect(x, uy, w, 9, 0, c, op=0.85))
        x += w + 2
    A(rrect(x, uy, max(CR - x, 0), 9, 0, DIM, op=0.3))
    lx = CL
    for (name, n), c in zip(upstream, pal):
        A(rrect(lx, uy + 20, 8, 8, 2, c, op=0.85))
        A(txt(lx + 14, uy + 28, name, 11, TXT))
        A(txt(lx + 22 + len(name) * 6.7, uy + 28, str(n), 11, BRIGHT, 600))
        lx += 46 + len(name) * 6.7 + len(str(n)) * 7
    A(txt(lx, uy + 28, f"other   {other}", 11, DIM))

    # =============================================== section E — calendar
    A(line(CL, 824, CR, 824, RULE, 1))
    cal_top, gap = 868, 4.0
    days = sorted(data)
    start = dt.date.fromisoformat(days[0])
    end = dt.date.fromisoformat(days[-1])
    start -= dt.timedelta(days=(start.weekday() + 1) % 7)
    ncols = (end - start).days // 7 + 1
    gx0 = CL + 34
    pitch = (CR - gx0 + gap) / ncols         # last column lands exactly on CR
    cell = pitch - gap

    total = sum(data.values())
    ling = sum(min(split.get(d, 0), data.get(d, 0)) for d in data)
    A(txt(CL, 842, "acquisition window · 12 months", 10.5, DIM, ls=1.4))
    A(txt(CR, 842,
          f"{total} commits · {ling} in LingCage · {total - ling} "
          f"elsewhere", 10.5, TXT, anchor="end"))

    seen = set()
    for c in range(ncols):
        d = start + dt.timedelta(days=7 * c)
        if d.day <= 7 and (d.year, d.month) not in seen and c < ncols - 1:
            seen.add((d.year, d.month))
            A(txt(gx0 + c * pitch, cal_top - 8, d.strftime("%b"), 10, DIM))

    for i, nm in ((1, "Mon"), (3, "Wed"), (5, "Fri")):
        A(txt(gx0 - 10, cal_top + 6 + i * pitch + cell * 0.72, nm, 9.5, DIM,
              anchor="end"))

    clips, last_xy, nk = [], None, 0
    for c in range(ncols):
        for r in range(7):
            d = (start + dt.timedelta(days=7 * c + r)).isoformat()
            if d not in data:
                continue
            n = data[d]
            lv = level(n)
            x, y = gx0 + c * pitch, cal_top + 6 + r * pitch
            l = min(split.get(d, 0), n)
            f = (l / n) if n else 0.0
            if n == 0:
                A(rrect(x, y, cell, cell, 3.5, RAMP_ELSE[0], op=0.9))
            elif f >= 1.0:
                A(rrect(x, y, cell, cell, 3.5, RAMP_LING[lv]))
            elif f <= 0.0:
                A(rrect(x, y, cell, cell, 3.5, RAMP_ELSE[lv]))
            else:
                nk += 1
                clips.append(f'<clipPath id="k{nk}"><rect x="{x:.2f}" '
                             f'y="{y:.2f}" width="{cell:.2f}" '
                             f'height="{cell:.2f}" rx="3.5"/></clipPath>')
                A(rrect(x, y, cell, cell, 3.5, RAMP_ELSE[lv]))
                A(rrect(x, y + cell * (1 - f), cell, cell * f, 0,
                        RAMP_LING[lv], extra=f'clip-path="url(#k{nk})"'))
            if n > 0:
                last_xy = (x + cell / 2, y + cell / 2)
    if clips:
        o.insert(o.index("</defs>"), "\n".join(clips))
    if last_xy:
        A(f'<circle id="last" cx="{last_xy[0]:.2f}" cy="{last_xy[1]:.2f}" '
          f'r="14" fill="none" stroke="{GREEN}" stroke-width="1.4" '
          f'opacity="0.25"/>')

    ly = cal_top + 6 + 7 * pitch + 22
    A(txt(CL, ly, "heat = commits per day, by repository", 10, DIM))
    A(txt(CL + 210, ly, "github.com/RuoqingHe", 10, DIM, op=0.7))
    for j, (lab, ramp) in enumerate((("elsewhere", RAMP_ELSE),
                                     ("LingCage", RAMP_LING))):
        right = CR - (1 - j) * 186
        A(txt(right - 92, ly, lab, 10, TXT if j else DIM, anchor="end"))
        for i, c in enumerate(ramp):
            A(rrect(right - 84 + i * 18, ly - 9, 12, 12, 3, c))

    A("</svg>")
    return "\n".join(s for s in o if s)


# ------------------------------------------------------------------- main ---
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--users", nargs="+", default=["RuoqingHe"])
    ap.add_argument("--out", default="assets/profile-cage.svg")
    ap.add_argument("--cache", default="")
    ap.add_argument("--split-cache", default="")
    ap.add_argument("--lingcage", nargs="*",
                    default=["lingcage", "RuoqingHe/lingcage"],
                    help="orgs / owner-repo scopes counted as LingCage work")
    ap.add_argument("--upstream",
                    default="kata-containers=46,rust-vmm=43,"
                            "cloud-hypervisor=24,lingcage=3")
    ap.add_argument("--merged-total", type=int, default=129)
    ap.add_argument("--auto-upstream", nargs="*", default=None)
    a = ap.parse_args()
    tok = os.environ.get("GITHUB_TOKEN")

    end = dt.date.today()
    start = end - dt.timedelta(days=365)

    if a.cache and os.path.exists(a.cache):
        raw = json.load(open(a.cache))
        split = json.load(open(a.split_cache)) if (
            a.split_cache and os.path.exists(a.split_cache)) else {}
    else:
        fetch = commits_graphql if tok else commits_search
        try:
            raw, split = fetch(a.users, a.lingcage, start.isoformat(),
                               end.isoformat(), tok)
        except Exception as e:                       # noqa: BLE001
            print(f"{fetch.__name__} failed ({e}); falling back to public "
                  f"commit search", file=sys.stderr)
            raw, split = commits_search(a.users, a.lingcage,
                                        start.isoformat(), end.isoformat(),
                                        tok)
        if a.cache:
            json.dump(raw, open(a.cache, "w"))
        if a.split_cache:
            json.dump(split, open(a.split_cache, "w"))

    # zero-fill the whole window so the calendar has a complete grid
    data = {(start + dt.timedelta(days=i)).isoformat(): 0
            for i in range((end - start).days + 1)}
    for d, n in raw.items():
        if d in data:
            data[d] = n

    if a.auto_upstream:
        upstream, merged_total = count_upstream(a.users, a.auto_upstream, tok)
    else:
        upstream = [(k.strip(), int(v)) for k, v in
                    (p.split("=") for p in a.upstream.split(","))]
        merged_total = a.merged_total

    svg = build(data, split, a.users, upstream, merged_total)
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    open(a.out, "w", encoding="utf-8").write(svg + "\n")
    lg = sum(min(split.get(d, 0), data[d]) for d in data)
    print(f"{a.out}  {len(svg) / 1024:.1f} KiB  {sum(data.values())} commits, "
          f"{lg} in LingCage", file=sys.stderr)


if __name__ == "__main__":
    main()
