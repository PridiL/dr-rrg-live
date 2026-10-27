"""Build the country RRG: each DR market's main index against MSCI World.

One point per market that has DRs on SET, drawn as a relative rotation graph
with a TAIL-session tail (the combined page, combine_rrg.py, renders it). The
European countries (France, Germany, Italy, Netherlands, Denmark) are one Europe
point against STOXX 600; the US is two, Nasdaq 100 and S&P 500, split by where
the DR's underlying is listed, as in the stock table. Each local index is converted to USD
before it is compared, because MSCI World is a USD index: relative strength in
a common currency is what a DR holder actually gets (the THB leg cancels out
of the ratio). MSCI World comes from MSCI's own end-of-day service, which only
carries finished sessions; Yahoo's ^990100-USD-STRD matches it to 1e-5 but adds
a live bar for the current day.

    python build_country_rrg.py   # then combine_rrg.py
"""
import datetime as dt
import html
import json
import os
import sys
import time
import urllib.request

import pandas as pd

from build_rrg import DASHBOARD, STATE, ROOT, WINDOW, ROC, TAIL, rrg_points, quadrant, yahoo_closes, log
from build_rrg_table import CSS, group_of, vnindex_closes

OUT_DATA = os.path.join(ROOT, "country_rrg_data.json")
MSCI_API = ("https://app2.msci.com/products/service/index/indexmaster/getLevelDataForGraph"
            "?currency_symbol=USD&index_variant=STRD&start_date={0}&end_date={1}"
            "&data_frequency=DAILY&index_codes=990100")

# key -> (display name, flag, index label, index source, FX ticker = local per USD)
# The US is two markets, as in the stock table: Nasdaq-listed DRs vs the Nasdaq 100,
# NYSE / NYSE Arca DRs vs the S&P 500 (user rule 2026-10-26).
COUNTRIES = [
    ("US-NASDAQ",     "US · Nasdaq",   "🇺🇸", "Nasdaq 100 (NDX)",     "^NDX",       None),
    ("US-NYSE",       "US · S&P 500",  "🇺🇸", "S&P 500 (SPX)",        "^GSPC",      None),
    ("CHINA",         "China",         "🇨🇳", "SSE Composite",        "000001.SS",  "CNY=X"),
    ("HONG KONG",     "Hong Kong",     "🇭🇰", "Hang Seng (HSI)",      "^HSI",       "HKD=X"),
    ("JAPAN",         "Japan",         "🇯🇵", "Nikkei 225 (NKY)",     "^N225",      "JPY=X"),
    ("TAIWAN",        "Taiwan",        "🇹🇼", "TAIEX",                "^TWII",      "TWD=X"),
    ("SINGAPORE",     "Singapore",     "🇸🇬", "Straits Times (STI)",  "^STI",       "SGD=X"),
    ("VIETNAM",       "Vietnam",       "🇻🇳", "VN-Index",             "VNINDEX",    "VND=X"),
    ("EUROPE",        "Europe",        "🇪🇺", "STOXX Europe 600 (SXXP)", "^STOXX",  "EUR=X"),
]
QUADS = ("Leading", "Weakening", "Lagging", "Improving")
RANK = {"Leading": 0, "Weakening": 1, "Improving": 2, "Lagging": 3}


def msci_world():
    end = dt.date.today()
    url = MSCI_API.format((end - dt.timedelta(days=600)).strftime("%Y%m%d"), end.strftime("%Y%m%d"))
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    for attempt in range(3):
        try:
            d = json.load(urllib.request.urlopen(req, timeout=30))
            break
        except Exception:
            if attempt == 2:
                raise
            time.sleep(3)
    lv = d["indexes"]["INDEX_LEVELS"]
    s = pd.Series({dt.datetime.strptime(str(x["calc_date"]), "%Y%m%d").date(): x["level_eod"]
                   for x in lv}).sort_index()
    stale = (dt.date.today() - s.index[-1]).days
    if stale > 5:
        raise SystemExit(f"MSCI World last level {s.index[-1]} is {stale} days old")
    return s


def build():
    data = json.load(open(DASHBOARD, encoding="utf-8"))
    resolved = json.load(open(STATE, encoding="utf-8"))["resolved"]
    ndr = {}
    for r in data["rows"]:
        exch = (resolved.get(r["symbol"]) or ":").split(":")[0]
        key = group_of(r["country"], exch)       # one Europe, two US markets
        ndr[key] = ndr.get(key, 0) + 1

    world = msci_world()
    log(f"MSCI World : {len(world)} levels, last {world.index[-1]}")
    need = sorted({c[4] for c in COUNTRIES if c[4] != "VNINDEX"} | {c[5] for c in COUNTRIES if c[5]})
    closes = yahoo_closes(need, period="600d")
    closes["VNINDEX"] = vnindex_closes()
    # Yahoo's daily index history can lag a session behind its own stock data
    # (2026-10-27: ^HSI ^N225 ^STOXX ^STI all lacked Monday). Fill only that gap.
    from yahoo_patch import fill_missing_last_session
    fill_missing_last_session(closes, [c[4] for c in COUNTRIES if c[4] != "VNINDEX"], log)
    # Finished sessions only: a run during the day would otherwise score a live,
    # half-day bar for whichever markets are still open (Europe, Singapore).
    closes = {k: v[v.index < dt.date.today()] for k, v in closes.items()}

    rows = []
    for key, name, flag, ilabel, isym, fx in COUNTRIES:
        idx = closes.get(isym)
        if idx is None or not len(idx):
            raise SystemExit(f"no index data for {name} ({isym})")
        if fx:
            rate = closes.get(fx)
            if rate is None or not len(rate):
                raise SystemExit(f"no FX data for {name} ({fx})")
            j = pd.concat({"i": idx, "f": rate}, axis=1).sort_index()
            j["f"] = j["f"].ffill()      # FX trades on days some exchanges are shut
            usd = (j["i"] / j["f"]).dropna()
        else:
            usd = idx
        pts = rrg_points(usd, world)
        row = {"key": key, "country": name, "flag": flag, "index": ilabel,
               "drs": ndr.get(key, 0), "last": str(min(usd.index[-1], world.index[-1]))}
        if pts:
            x, y = pts[-1]
            row.update(x=x, y=y, q=quadrant(x, y), tail=pts)
        rows.append(row)
        log(f"  {name:<14} {ilabel:<22} {row.get('q', 'no reading'):<10} "
            f"{row.get('x', float('nan')):7.2f} {row.get('y', float('nan')):7.2f}")

    rows.sort(key=lambda r: (RANK.get(r.get("q"), 9), -r.get("x", 0)))
    meta = {"generated": time.strftime("%Y-%m-%d %H:%M"),
            "world_last": str(world.index[-1]), "window": WINDOW, "roc": ROC, "tail": TAIL}
    return meta, rows


def country_graph(rows):
    """Inline SVG relative rotation graph: each market's head plus its TAIL-session tail.

    Returns (svg, summary). Shared with the combined page (combine_rrg.py).
    """
    e = html.escape
    W, H, L, R, T, B = 620, 480, 52, 14, 14, 46
    pw, ph = W - L - R, H - T - B
    pts = [p for r in rows if r.get("tail") for p in r["tail"]]
    hx = max(1.2, max(abs(x - 100) for x, _ in pts) * 1.18)
    hy = max(1.2, max(abs(y - 100) for _, y in pts) * 1.18)
    sx = lambda v: L + (v - (100 - hx)) / (2 * hx) * pw
    sy = lambda v: T + ph - (v - (100 - hy)) / (2 * hy) * ph

    def ticks(h):
        step = next(s for s in (0.25, 0.5, 1, 2, 5, 10) if h / s <= 4)
        k = int(h // step)
        return [100 + i * step for i in range(-k, k + 1)]

    out = [f'<svg class="rrg" viewBox="0 0 {W} {H}" role="img" '
           f'aria-label="Relative rotation graph of DR markets against MSCI World">']
    cx, cy = sx(100), sy(100)
    for x0, y0, x1, y1, cls in ((cx, T, L + pw, cy, "b-lead"), (cx, cy, L + pw, T + ph, "b-weak"),
                                (L, cy, cx, T + ph, "b-lag"), (L, T, cx, cy, "b-imp")):
        out.append(f'<rect x="{x0:.1f}" y="{y0:.1f}" width="{x1 - x0:.1f}" height="{y1 - y0:.1f}" class="{cls}"/>')
    for v in ticks(hx):
        X = sx(v)
        out.append(f'<line x1="{X:.1f}" y1="{T}" x2="{X:.1f}" y2="{T + ph}" class="grid"/>'
                   f'<text x="{X:.1f}" y="{T + ph + 16}" class="tick" text-anchor="middle">{v:g}</text>')
    for v in ticks(hy):
        Y = sy(v)
        out.append(f'<line x1="{L}" y1="{Y:.1f}" x2="{L + pw}" y2="{Y:.1f}" class="grid"/>'
                   f'<text x="{L - 7}" y="{Y + 4:.1f}" class="tick" text-anchor="end">{v:g}</text>')
    out.append(f'<line x1="{cx:.1f}" y1="{T}" x2="{cx:.1f}" y2="{T + ph}" class="axis"/>'
               f'<line x1="{L}" y1="{cy:.1f}" x2="{L + pw}" y2="{cy:.1f}" class="axis"/>'
               f'<rect x="{L}" y="{T}" width="{pw}" height="{ph}" class="frame"/>')
    for txt, x, y, anc in (("LEADING", L + pw - 8, T + 18, "end"), ("WEAKENING", L + pw - 8, T + ph - 9, "end"),
                           ("LAGGING", L + 8, T + ph - 9, "start"), ("IMPROVING", L + 8, T + 18, "start")):
        out.append(f'<text x="{x}" y="{y}" class="qlab" text-anchor="{anc}">{txt}</text>')
    out.append(f'<text x="{L + pw / 2:.1f}" y="{H - 8}" class="axt" text-anchor="middle">'
               f'RS-Ratio: relative strength vs MSCI World →</text>'
               f'<text transform="translate(15 {T + ph / 2:.1f}) rotate(-90)" class="axt" '
               f'text-anchor="middle">RS-Momentum →</text>')

    # tails first so every head and label sits on top of them
    # one colour per market, fixed by its place in COUNTRIES so it never changes week to week
    order = [c[0] for c in COUNTRIES]
    heads = []
    for r in rows:
        if not r.get("tail"):
            continue
        q = "c" + str(order.index(r["key"]) + 1)
        xy = [(sx(x), sy(y)) for x, y in r["tail"]]
        out.append(f'<polyline points="{" ".join(f"{a:.1f},{b:.1f}" for a, b in xy)}" class="tl s-{q}"/>')
        for a, b in xy[:-1]:
            out.append(f'<circle cx="{a:.1f}" cy="{b:.1f}" r="2.6" class="td f-{q}"/>')
        heads.append((r, q, xy[-1]))

    # labels: first candidate spot that clears the plot edge, other labels and other heads
    boxes = [(a - 7, b - 7, a + 7, b + 7) for _, _, (a, b) in heads]
    hit = lambda u, v: not (u[2] < v[0] or v[2] < u[0] or u[3] < v[1] or v[3] < u[1])
    for r, q, (a, b) in heads:
        label = r["country"]
        w, h = 7.4 * len(label), 14
        spots = [(a + 10, b + 4, "start"), (a + 9, b - 8, "start"), (a - 10, b + 4, "end"),
                 (a - 9, b - 8, "end"), (a + 10, b + 14, "start"),
                 (a - 10, b + 14, "end"), (a + 10, b - 14, "start"), (a - 10, b - 14, "end"),
                 (a - w / 2, b - 12, "start"), (a - w / 2, b + 21, "start")]
        pick = spots[0]
        for x, y, anc in spots:
            x0 = x if anc == "start" else x - w
            box = (x0, y - h + 3, x0 + w, y + 3)
            if box[0] < L + 2 or box[2] > L + pw - 2 or box[1] < T + 2 or box[3] > T + ph - 2:
                continue
            if any(hit(box, o) for o in boxes if o != (a - 7, b - 7, a + 7, b + 7)):
                continue
            pick = (x, y, anc)
            boxes.append(box)
            break
        x, y, anc = pick
        tip = (f'{r["country"]} ({r["index"]}): {r["q"]} · RS-Ratio {r["x"]:.2f} · '
               f'RS-Momentum {r["y"]:.2f} · to {r["last"]}')
        out.append(f'<g><title>{e(tip)}</title>'
                   f'<circle cx="{a:.1f}" cy="{b:.1f}" r="6.5" class="hd f-{q}"/>'
                   f'<text x="{x:.1f}" y="{y:.1f}" class="lab f-{q}" text-anchor="{anc}">{e(label)}</text></g>')
    out.append("</svg>")

    counts = {q: sum(1 for r in rows if r.get("q") == q) for q in QUADS}
    summary = " · ".join(f'<span class="q-{q[:4].lower()}-t">{q} {counts[q]}</span>' for q in QUADS)
    return "".join(out), summary


GRAPH_CSS = """
.chart{background:var(--surface); border:1px solid var(--line); border-radius:6px; padding:8px; overflow-x:auto}
svg.rrg{display:block; width:100%; min-width:400px; height:auto}
svg.rrg .grid{stroke:var(--line); stroke-width:1}
svg.rrg .axis{stroke:var(--ax); stroke-width:1.4}
svg.rrg .frame{fill:none; stroke:var(--line)}
svg.rrg .tick{font-size:11px; fill:var(--ink-faint); font-variant-numeric:tabular-nums}
svg.rrg .axt{font-size:12px; fill:var(--ink-soft)}
svg.rrg .qlab{font-size:11px; letter-spacing:.08em; fill:var(--ink-faint); font-weight:600}
svg.rrg .tl{fill:none; stroke-width:2.2; stroke-linejoin:round; stroke-linecap:round; opacity:.6}
.chart,.keys{--c1:#2563EB; --c2:#7C3AED; --c3:#DC2626; --c4:#EA580C; --c5:#DB2777; --c6:#0D9488; --c7:#B45309; --c8:#16A34A; --c9:#475569}
@media (prefers-color-scheme: dark){ :root:not([data-theme="light"]) .chart, :root:not([data-theme="light"]) .keys{
  --c1:#60A5FA; --c2:#A78BFA; --c3:#F87171; --c4:#FB923C; --c5:#F472B6; --c6:#2DD4BF; --c7:#FBBF24; --c8:#4ADE80; --c9:#94A3B8}}
:root[data-theme="dark"] .chart, :root[data-theme="dark"] .keys{
  --c1:#60A5FA; --c2:#A78BFA; --c3:#F87171; --c4:#FB923C; --c5:#F472B6; --c6:#2DD4BF; --c7:#FBBF24; --c8:#4ADE80; --c9:#94A3B8}
svg.rrg .s-c1{stroke:var(--c1)} svg.rrg .f-c1{fill:var(--c1)}
svg.rrg .s-c2{stroke:var(--c2)} svg.rrg .f-c2{fill:var(--c2)}
svg.rrg .s-c3{stroke:var(--c3)} svg.rrg .f-c3{fill:var(--c3)}
svg.rrg .s-c4{stroke:var(--c4)} svg.rrg .f-c4{fill:var(--c4)}
svg.rrg .s-c5{stroke:var(--c5)} svg.rrg .f-c5{fill:var(--c5)}
svg.rrg .s-c6{stroke:var(--c6)} svg.rrg .f-c6{fill:var(--c6)}
svg.rrg .s-c7{stroke:var(--c7)} svg.rrg .f-c7{fill:var(--c7)}
svg.rrg .s-c8{stroke:var(--c8)} svg.rrg .f-c8{fill:var(--c8)}
svg.rrg .s-c9{stroke:var(--c9)} svg.rrg .f-c9{fill:var(--c9)}

svg.rrg .td{opacity:.75}
svg.rrg .hd{stroke:var(--surface); stroke-width:1.6}
svg.rrg .lab{font-size:13px; font-weight:700; paint-order:stroke;
  stroke:var(--surface); stroke-width:3.5px; stroke-linejoin:round}
.keys{display:grid; grid-template-columns:repeat(auto-fill,minmax(220px,1fr)); gap:4px 16px;
  font-size:12px; color:var(--ink-soft); margin:10px 0 0}
.keys b{color:var(--ink)}
"""


def country_keys(rows):
    """One line per market under the graph: what each label measures."""
    e = html.escape
    order = [c[0] for c in COUNTRIES]
    return "".join(
        f'<div><i class="dot" style="background:var(--c{order.index(r["key"]) + 1})"></i> '
        f'<b>{e(r["country"])}</b>: {e(r["index"])} · {r["drs"]} DR{"s" if r["drs"] != 1 else ""}'
        + (f' · <span class="q-{r["q"][:4].lower()}-t">{r["q"]}</span>' if r.get("q") else " · no reading")
        + '</div>' for r in rows)


def main():
    meta, rows = build()
    json.dump({"meta": meta, "rows": rows}, open(OUT_DATA, "w", encoding="utf-8"), ensure_ascii=False)
    log(f"\nwrote {OUT_DATA} - render with combine_rrg.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
