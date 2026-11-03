#!/usr/bin/env python3
"""The profile card: a terminal window running `htop`, rendered as an animated SVG.

build_card(mode, ...) takes already-fetched data and returns the SVG text for "dark" or "light".
Animation is CSS only. Every animated element ends in its final state, so a renderer that ignores
CSS animation (or an animation frozen at its end) shows the complete card.
"""

import datetime
import html

import public_repos
from card_art import ART

W = 800
FS = 12
CW = FS * 0.6  # 7.2 px per char at 12px
MONO = "ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Consolas, 'Liberation Mono', monospace"

ART_SIZE = 9.2
ART_LH = 9.6
ART_W = max(len(line) for line in ART)

FKEYS = [("F1", "Help?"), ("F2", "Prompt"), ("F3", "Google"), ("F4", "Vibes"), ("F5", "Retry"),
         ("F6", "Blame"), ("F7", "Humble"), ("F8", "Ship"), ("F9", "rm -rf"), ("F10", "Nap")]

SYSTEM = [("location", "Silicon Alley"), ("shell", "living tissue over metal endoskeleton"),
          ("languages", "english, bad english, help files"), ("focus", "AI/ML, Developer Tools, waning")]

AREA51 = [
    ("Nexus", "Enterprise API platform connecting", " systems at scale"),
    ("Origami", "AI-powered", " app, concept to launch"),
    ("Foundry", "AI app builder for rapid", " prototyping"),
    ("Beacon", "Intelligence platform surfacing", " insights"),
    ("Meridian", "Client relationship dashboard for", ""),
    ("Exodus", "Large-scale", " migration across platforms"),
    ("Oracle", "Company-wide AI assistant for", " teams"),
    ("Relay", "Internal", " tracking & approvals platform"),
    ("Tempo", "AI timesheet automation syncing", " via Slack"),
    ("Atlas", "AI-assisted knowledge base for", ""),
]

LANG_SCOPE_NOTE = "all repos"

CSS = """
.r{}
@keyframes show{from{opacity:0}to{opacity:1}}
.type{}
@keyframes type{from{width:0}to{width:var(--w)}}
.mv{opacity:0;animation:mv var(--dur) steps(var(--n),end) forwards, vis calc(var(--dur) + .25s) steps(1) forwards;animation-delay:var(--d),var(--d)}
@keyframes mv{from{transform:translateX(0)}to{transform:translateX(var(--w))}}
@keyframes vis{0%,99%{opacity:1}100%{opacity:0}}
.blink{animation:blink 1.05s steps(1) infinite}
@keyframes blink{0%,49%{opacity:1}50%,100%{opacity:0}}
.eq{transform-box:fill-box;transform-origin:50% 100%;animation:eq 1.1s ease-in-out infinite alternate}
@keyframes eq{from{transform:scaleY(.25)}to{transform:scaleY(1)}}
"""

STAR_PATH = '<path d="M8 1.8l1.9 4 4.3.5-3.2 3 .9 4.3L8 11.4l-3.9 2.2.9-4.3-3.2-3 4.3-.5z"/>'


def esc(s):
    return html.escape(str(s), quote=False)


def fmt(n):
    n = float(n)
    for lim, suf in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if n >= lim:
            return f"{n / lim:.1f}{suf}"
    return str(int(n))


def palette(mode):
    if mode == "dark":
        return dict(bg="#0d1117", panel="#161b22", panel2="#1c2230", line="#30363d", ink="#e6edf3", gray="#8b949e",
                    dim="#6e7681", cyan="#39c5cf", magenta="#e879f9", green="#a3e635", red="#f87171",
                    orange="#fb923c", yellow="#fbbf24", blue="#58a6ff", redact="#c9d1d9",
                    heat=["#1c2230", "#0e4429", "#006d32", "#26a641", "#56d364"])
    return dict(bg="#f6f8fa", panel="#ffffff", panel2="#eaeef2", line="#d0d7de", ink="#1f2328", gray="#57606a",
                dim="#8c959f", cyan="#0e7490", magenta="#a21caf", green="#4d7c0f", red="#dc2626",
                orange="#c2410c", yellow="#b45309", blue="#0969da", redact="#1f2328",
                heat=["#e6eaee", "#aceebb", "#4ac26b", "#2da44e", "#116329"])


def star_icon(x, y, size, col):
    s = size / 16
    return (f'<g transform="translate({x:g},{y:g}) scale({s:.3f})" fill="{col}" stroke="{col}" stroke-width="1.2" '
            f'stroke-linecap="round" stroke-linejoin="round">{STAR_PATH}</g>')


class Scene:
    def __init__(self, mode):
        self.c = palette(mode)
        self.mode = mode
        self.o = []
        self.t = 0.4  # running animation clock, seconds
        self.k = 0
        self.defs = []

    # ---- text / timing ---------------------------------------------------------------------
    def T(self, x, y, s, fill, size=FS, anchor="start", weight="normal", extra=""):
        if s == "":
            return ""
        return (f'<text x="{x:g}" y="{y:g}" font-size="{size}" fill="{fill}" text-anchor="{anchor}" '
                f'font-weight="{weight}" {extra}>{esc(s)}</text>')

    def add(self, s):
        self.o.append(s)

    def R(self, inner, step=0.1):
        """reveal a group at the running clock"""
        self.o.append(f'<g class="r" style="animation-delay:{self.t:.2f}s">{inner}</g>')
        self.t += step

    def uid(self, p="k"):
        self.k += 1
        return f"{p}{self.k}"

    def type_cmd(self, x, y, cmd, speed=0.05):
        c = self.c
        n = len(cmd)
        dur = n * speed
        d = self.t
        k = self.uid("cp")
        self.add(f'<text x="{x}" y="{y}" font-size="{FS}" fill="{c["green"]}" font-weight="bold" class="r" style="animation-delay:{d:.2f}s">$</text>')
        self.add(f'<clipPath id="{k}"><rect class="type" x="{x + 2 * CW:g}" y="{y - 14}" width="{n * CW + 2:g}" height="20" '
                 f'style="--w:{n * CW + 2:.1f}px;--n:{n};--dur:{dur:.2f}s;animation-delay:{d:.2f}s"/></clipPath>')
        self.add(f'<g clip-path="url(#{k})">{self.T(x + 2 * CW, y, cmd, c["ink"], FS)}</g>')
        self.add(f'<g class="mv" style="--w:{n * CW:.1f}px;--n:{n};--dur:{dur:.2f}s;--d:{d:.2f}s">'
                 f'<rect class="blink" x="{x + 2 * CW:g}" y="{y - 11}" width="{CW}" height="15" fill="{c["ink"]}"/></g>')
        self.t = d + dur + 0.3

    def sweep(self, inner, x, y, w, h, n, dur, delay=None):
        """reveal `inner` with a stepped left-to-right wipe"""
        k = self.uid("sw")
        d = self.t if delay is None else delay
        self.add(f'<clipPath id="{k}"><rect class="type" x="{x:g}" y="{y:g}" width="{w:g}" height="{h:g}" '
                 f'style="--w:{w:g}px;--n:{n};--dur:{dur:.2f}s;animation-delay:{d:.2f}s"/></clipPath>'
                 f'<g clip-path="url(#{k})">{inner}</g>')
        if delay is None:
            self.t += dur * 0.6

    # ---- pieces ----------------------------------------------------------------------------------
    def eq(self, x, ybase, n=4, bw=2.6, gap=2, hmax=12, color=None, seed=0, hmin=4):
        """small rounded equalizer bars; static height is the pattern, animation scales between .25 and 1"""
        color = color or self.c["cyan"]
        out = []
        for i in range(n):
            h = hmin + ((i * 5 + seed * 3) % 7) / 6 * (hmax - hmin)
            dur = 0.7 + ((i + seed) % 5) * 0.17
            out.append(f'<rect class="eq" x="{x + i * (bw + gap):.1f}" y="{ybase - h:.1f}" width="{bw}" height="{h:.1f}" rx="{bw / 2:.1f}" fill="{color}" '
                       f'style="animation-delay:{((i * 0.13 + seed * 0.07) % 1.1):.2f}s;animation-duration:{dur:.2f}s"/>')
        return "".join(out)

    def chrome(self, title, h=36):
        c = self.c
        s = f'<rect width="{W}" height="{h}" fill="{c["panel"]}"/><rect y="{h}" width="{W}" height="1" fill="{c["line"]}"/>'
        for i, col in enumerate(("#ff5f57", "#febc2e", "#28c840")):
            s += f'<circle cx="{22 + i * 20}" cy="{h / 2}" r="6" fill="{col}"/>'
        s += self.T(W / 2, 23, title, c["gray"], 12, "middle")
        px = W - 90
        s += f'<circle cx="{px}" cy="{h / 2}" r="3.5" fill="{c["green"]}"/>'
        s += self.T(px + 10, 22, "online", c["green"], 11)
        s += self.eq(W - 148, h / 2 + 7, 5, 3, 2, 14, c["cyan"], 0, 7)
        self.add(s)

    @staticmethod
    def heat_levels(weeks):
        flat = sorted(v for w in weeks for v in w if v > 0)
        if not flat:
            return lambda v: 0
        q = [flat[int(len(flat) * f)] for f in (.25, .5, .75)]
        return lambda v: 0 if v == 0 else 1 if v <= q[0] else 2 if v <= q[1] else 3 if v <= q[2] else 4

    def heatmap(self, cal, x, y, pitch, cell):
        c = self.c
        weeks, dates = cal["weeks"], cal["dates"]
        lv = self.heat_levels(weeks)
        paths = [[] for _ in range(5)]
        s = ""
        last = None
        for wi, w in enumerate(weeks):
            m = datetime.date.fromisoformat(dates[wi]).strftime("%b")
            if m != last and wi < len(weeks) - 2:
                s += self.T(x + wi * pitch, y - 7, m, c["dim"], 9)
            last = m
            for di, v in enumerate(w):
                paths[lv(v)].append(f"M{x + wi * pitch + 1:.1f} {y + di * pitch + 1:.1f}h{cell - 2:.1f}v{cell - 2:.1f}h-{cell - 2:.1f}z")
        for i, p in enumerate(paths):
            if p:
                s += f'<path d="{"".join(p)}" fill="{c["heat"][i]}" stroke="{c["heat"][i]}" stroke-width="2" stroke-linejoin="round"/>'
        for di, lab in ((1, "Mon"), (3, "Wed"), (5, "Fri")):
            s += self.T(x - 4, y + di * pitch + cell - 2, lab, c["dim"], 9, "end")
        return s

    def lang_items(self, langs):
        """top six languages plus Other, as (name, bytes, colour); drops Other when there is none"""
        top = langs[:6]
        tot = sum(l["bytes"] for l in langs)
        other = tot - sum(l["bytes"] for l in top)
        fix = {"GDScript": "#5f8db3" if self.mode == "dark" else "#355570"}
        items = [(l["name"], l["bytes"], fix.get(l["name"], l["color"])) for l in top]
        if other > 0:
            items.append(("Other", other, self.c["dim"]))
        return items, tot

    def segbar(self, x, y, w, h, segs, minw=4.0, gap=2.0):
        """solid rounded segmented bar; segs = [(fraction, colour)]; every segment is at least minw wide"""
        if not segs:
            return ""
        k = self.uid("sb")
        out = f'<clipPath id="{k}"><rect x="{x}" y="{y}" width="{w}" height="{h}" rx="3"/></clipPath><g clip-path="url(#{k})">'
        widths = [max(minw, f * w) for f, _ in segs]
        scale = (w - gap * (len(segs) - 1)) / sum(widths)
        xx = x
        for wd, (f, col) in zip(widths, segs):
            ww = wd * scale
            out += f'<rect x="{xx:.1f}" y="{y}" width="{ww:.1f}" height="{h}" fill="{col}"/>'
            xx += ww + gap
        return out + "</g>"

    # ---- portrait --------------------------------------------------------------------------------
    @staticmethod
    def portrait_size():
        return ART_W * ART_SIZE * 0.6, 8 + len(ART) * ART_LH + 14 + 16 + 28

    def portrait(self, x, y):
        """gradient ASCII portrait, tagline, 8-colour swatch row (bright + dim)"""
        c = self.c
        aw, th = self.portrait_size()
        ah = len(ART) * ART_LH
        y0 = y + 8
        g = self.uid("pg")
        self.defs.append(f'<linearGradient id="{g}" gradientUnits="userSpaceOnUse" x1="0" y1="{y0}" x2="0" y2="{y0 + ah}">'
                         f'<stop offset="0" stop-color="{c["cyan"]}"/><stop offset=".55" stop-color="{c["blue"]}"/><stop offset="1" stop-color="{c["magenta"]}"/></linearGradient>')
        art = "\n".join(f'<text x="{x}" y="{y0 + i * ART_LH:.2f}" font-size="{ART_SIZE}" fill="url(#{g})" xml:space="preserve">{esc(line)}</text>'
                        for i, line in enumerate(ART))
        self.sweep(art, x - 2, y0 - 10, aw + 6, ah + 12, len(ART), 1.5)
        ty = y0 + ah + 14
        self.R(self.T(x + aw / 2, ty, "ai developer  ·  prompt whisperer", c["gray"], 12, "middle"), 0.1)
        sy = ty + 16
        cols = [c["red"], c["orange"], c["yellow"], c["green"], c["cyan"], c["blue"], c["magenta"], c["ink"]]
        bw = aw / 8
        sw = ""
        for i, col in enumerate(cols):
            sw += (f'<rect x="{x + i * bw:.1f}" y="{sy}" width="{bw:.1f}" height="14" fill="{col}"/>'
                   f'<rect x="{x + i * bw:.1f}" y="{sy + 14}" width="{bw:.1f}" height="14" fill="{col}" opacity=".55"/>')
        self.sweep(sw, x, sy, aw, 28, 8, 0.6)
        return th

    # ---- public grid -----------------------------------------------------------------------------
    def public_grid(self, x, y, w, stars, gap=12, row_h=34):
        """DOCKER / AGENTS + AI / MACOS columns, name + stars, short description underneath"""
        c = self.c
        cw_ = (w - 2 * gap) / 3
        cols = public_repos.grid_columns(stars)
        for ci, ((_, label), items) in enumerate(zip(public_repos.CATEGORIES, cols)):
            cx = x + ci * (cw_ + gap)
            self.R(self.T(cx, y, label, c["gray"], 10.5, weight="bold", extra='letter-spacing="1.2"')
                   + f'<rect x="{cx:.1f}" y="{y + 6}" width="{cw_:.1f}" height="1" fill="{c["line"]}"/>', 0.08)
            for ri, (name, n, desc) in enumerate(items):
                ry = y + 26 + ri * row_h
                s = self.T(cx, ry, name, c["cyan"], 12, weight="bold")
                if n is not None:
                    s += self.T(cx + cw_ - 18, ry, str(n), c["yellow"], 12, "end", weight="bold") + star_icon(cx + cw_ - 14, ry - 10.5, 11, c["yellow"])
                s += self.T(cx, ry + 14, desc, c["gray"], 10.5)
                self.R(s, 0.07)
        return 26 + 3 * row_h

    def finish(self, H):
        c = self.c
        head = (f'<?xml version="1.0" encoding="UTF-8"?>\n<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">\n'
                f'<style>\ntext{{font-family:{MONO};white-space:pre;}}\n{CSS}\n</style>\n')
        head += "<defs>" + "".join(self.defs) + "</defs>"
        head += f'<clipPath id="win"><rect width="{W}" height="{H}" rx="12"/></clipPath><g clip-path="url(#win)">\n'
        head += f'<rect width="{W}" height="{H}" fill="{c["bg"]}"/>\n'
        return head + "\n".join(self.o) + f'\n</g>\n<rect x=".5" y=".5" width="{W - 1}" height="{H - 1}" rx="12" fill="none" stroke="{c["line"]}"/>\n</svg>\n'


def build_card(mode, usage, github, calendar, langs, stars):
    """Return the card SVG for `mode` ("dark" or "light").

    usage: token_usage stats dict; github: github stats dict; calendar: card_data calendar dict;
    langs: aggregated language list; stars: {owner/repo: stars or None}.
    """
    sc = Scene(mode)
    c = sc.c
    T = sc.T
    sc.chrome("htop  —  scott@silicon-alley")
    sc.type_cmd(24, 62, "htop")
    y = 84
    aw, th = sc.portrait_size()
    sc.portrait(24, y)
    RX = 24 + aw + 26
    RW = W - 24 - RX

    # ---- identity + real meters ----
    ry = y + 20
    sc.R(T(RX, ry, "scott", c["cyan"], 13, weight="bold") + T(RX + 5 * 7.8, ry, "@", c["dim"], 13) + T(RX + 6 * 7.8, ry, "silicon-alley", c["ink"], 13, weight="bold"), 0.1)
    ry += 22
    for k, v in SYSTEM:
        sc.R(T(RX, ry, k, c["dim"], 11) + T(RX + 11 * 6.6, ry, v, c["ink"], 11), 0.06)
        ry += 16
    ry += 18

    def head(label, val):
        nonlocal ry
        sc.R(T(RX, ry, label, c["cyan"], 11, weight="bold", extra='letter-spacing="1.2"') + T(RX + RW, ry, val, c["ink"], 11.5, "end", "bold"), 0.06)
        ry += 9

    def legend(items, y_, fs=9.5):
        x = RX
        out = ""
        for name, val, col in items:
            out += f'<rect x="{x:.1f}" y="{y_ - 8}" width="8" height="8" rx="1.5" fill="{col}"/>' + T(x + 12, y_, f"{name} {val}", c["gray"], fs)
            x += 12 + len(f"{name} {val}") * fs * 0.6 + 12
        return out

    def bar(segs):
        nonlocal ry
        sc.sweep(sc.segbar(RX, ry, RW, 12, segs), RX - 2, ry - 2, RW + 4, 16, 30, 0.9)
        ry += 25

    tot = usage["total_tokens"] or 1
    head("TOKENS", fmt(usage["total_tokens"]))
    bar([(usage["input_tokens"] / tot, c["blue"]), (usage["output_tokens"] / tot, c["red"]),
         (usage["cache_creation"] / tot, c["yellow"]), (usage["cache_read"] / tot, c["green"])])
    sc.R(legend([("in", fmt(usage["input_tokens"]), c["blue"]), ("out", fmt(usage["output_tokens"]), c["red"]),
                 ("cache-new", fmt(usage["cache_creation"]), c["yellow"]), ("cache-read", fmt(usage["cache_read"]), c["green"])], ry), 0.06)
    ry += 25

    la, ld = github["loc_added"], github["loc_deleted"]
    head("LINES OF CODE", f"{github['loc_total']:,}")
    bar([(la / ((la + ld) or 1), c["green"]), (ld / ((la + ld) or 1), c["red"])])
    sc.R(T(RX, ry, f"+{la:,} added", c["green"], 10) + T(RX + RW, ry, f"-{ld:,} deleted", c["red"], 10, "end"), 0.06)
    ry += 25

    items, tl = sc.lang_items(langs)
    head("LANGUAGES", LANG_SCOPE_NOTE)
    bar([(b / tl, col) for _, b, col in items])
    for row in (items[:4], items[4:]):
        if row:
            sc.R(legend([(n, f"{100 * b / tl:.1f}%", col) for n, b, col in row], ry, 9.5), 0.05)
            ry += 14
    ry += 12

    cells = [("SESSIONS", fmt(usage["sessions"])), ("MESSAGES", fmt(usage["messages"])),
             ("API SAVED", f"${usage['cost_estimate']:,.0f}"), ("STARS", f"{github['stars']}"),
             ("REPOS", f"{github['repos']}"), ("CONTRIBUTED", f"{github['contributed_repos']}"),
             ("COMMITS", f"{github['commits']:,}"), ("PULL REQS", f"{github['prs']:,}")]
    cw2 = RW / 2
    rh = min(26, (y + th - ry) / 4)
    for i, (lab, val) in enumerate(cells):
        cx = RX + (i % 2) * (cw2 + 14)
        cy = ry + (i // 2) * rh + 14
        w_ = cw2 - 14
        s = T(cx, cy - 1, lab, c["gray"], 9, weight="bold", extra='letter-spacing=".8"') + T(cx + w_, cy + 1, val, c["ink"], 16, "end", "bold")
        s += f'<rect x="{cx:.1f}" y="{cy + 6:.1f}" width="{w_:.1f}" height="1" fill="{c["line"]}"/>'
        sc.R(s, 0.06)
    y += th + 26

    def band(yy, text, right=""):
        lab = text.upper()
        s = T(24, yy, lab, c["cyan"], 11, weight="bold", extra='letter-spacing="1.2"')
        x1 = 24 + len(lab) * 8.6 + 8
        x2 = W - 24 - (len(right) * 6.4 + 10 if right else 0)
        s += f'<rect x="{x1:.1f}" y="{yy - 4}" width="{x2 - x1:.1f}" height="1" fill="{c["line"]}"/>'
        if right:
            s += T(W - 24, yy, right, c["gray"], 10.5, "end")
        sc.R(s, 0.1)

    # ---- contributions ----
    band(y, "Contributions", f"{calendar['total']:,} in the last year")
    gy = y + 30
    pitch = 13.0
    sc.sweep(sc.heatmap(calendar, 24 + 40, gy, pitch, 10.4), 24 + 4, gy - 16, 36 + len(calendar["weeks"]) * pitch + 8, 110, 53, 1.5)
    y = gy + 7 * pitch + 18

    # ---- area 51 process table ----
    cx = {"pid": 24, "name": 24 + 6 * CW, "st": 24 + 17 * CW, "cmd": 24 + 29 * CW}
    s = "".join(T(cx[k], y, lab, c["cyan"], 11, weight="bold", extra='letter-spacing="1.2"')
                for k, lab in (("pid", "PID"), ("name", "NAME"), ("st", "STATUS"), ("cmd", "COMMAND")))
    s += T(W - 24, y, "just trust me", c["gray"], 10.5, "end", extra='font-style="italic"') + f'<rect x="24" y="{y + 6}" width="{W - 48}" height="1" fill="{c["line"]}"/>'
    sc.R(s, 0.1)
    ty = y + 26
    sel = 6
    for i, (name, pre, post) in enumerate(AREA51):
        ry = ty + i * 18
        if i == sel:
            sc.R(f'<rect x="12" y="{ry - 13}" width="{W - 24}" height="18" fill="{c["cyan"]}"/>', 0)
        fg = c["bg"] if i == sel else None
        s = T(cx["pid"], ry, f"{4100 + i * 37:04d}", fg or c["dim"], FS) + T(cx["name"], ry, name, fg or c["ink"], FS, weight="bold")
        s += T(cx["st"], ry, "classified", fg or c["red"], FS)
        s += T(cx["cmd"], ry, pre, fg or c["gray"], FS)
        xx = cx["cmd"] + (len(pre) + 1) * CW
        s += f'<rect x="{xx:.1f}" y="{ry - 10}" width="{8 * CW - 2:.1f}" height="13" rx="2" fill="{c["redact"] if fg is None else c["bg"]}"/>'
        if post:
            s += T(xx + 8 * CW, ry, post, fg or c["gray"], FS)
        sc.R(s, 0.06)
    y = ty + 10 * 18 + 16

    # ---- public ----
    band(y, "PUBLIC", "open source")
    y += 28
    y += sc.public_grid(24, y, W - 48, stars) + 6

    # ---- footer f-keys ----
    fy = y + 10
    s = ""
    slot = (W - 24) / 10
    for i, (k, lab) in enumerate(FKEYS):
        x = 12 + i * slot
        s += T(x + 2, fy + 3, k, c["ink"], 10.5, weight="bold")
        kw = len(k) * 6.4 + 4
        s += f'<rect x="{x + kw:.1f}" y="{fy - 11}" width="{slot - kw - 2:.1f}" height="19" fill="{c["cyan"]}"/>' + T(x + kw + 3, fy + 3, lab, c["bg"], 10.5)
    sc.R(s, 0.1)
    return sc.finish(int(fy + 22))
