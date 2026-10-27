"""Build the DR RRG table: one row per DR showing DR, market and RRG position.

Like the rotation graphs in build_rrg.py, the table covers underlying STOCKS
only (no ETFs), one row per underlying with its DR symbols listed under it --
AAPL01/03/19/80 are one Apple row (user rule 2026-10-26). It uses the
benchmarks the user set on 2026-10-26:

    CHINA          SSE Composite     000001.SS
    HONG KONG      Hang Seng         ^HSI
    VIETNAM        VN-Index          VNINDEX   (VNDirect dchart API - not on Yahoo)
    JAPAN          Nikkei 225        ^N225
    SINGAPORE      Straits Times     ^STI
    EUROPE         STOXX Europe 600  ^STOXX
    US, Nasdaq     Nasdaq 100        ^NDX
    US, NYSE/Arca  S&P 500           ^GSPC

Taiwan is skipped (3 DRs only, all ETFs). Exchange comes from the resolved TradingView
symbol in dr_watchlist_state.json. Maths (RS-Ratio / RS-Momentum, window,
tail) is shared with build_rrg.py so the two pages agree wherever the
benchmark is the same.

    python build_rrg_table.py
"""
import datetime as dt
import html
import json
import os
import sys
import time
import urllib.request

import pandas as pd

from build_rrg import (DASHBOARD, STATE, ROOT, WINDOW, ROC, TAIL,
                       rrg_points, quadrant, yahoo_closes, log)

OUT_HTML = os.path.join(ROOT, "dr_rrg_table.html")
OUT_DATA = os.path.join(ROOT, "rrg_table_data.json")

EUROPE = {"FRANCE", "GERMANY", "DENMARK", "ITALY", "NETHERLANDS"}
SKIP = {"TAIWAN"}
VN_API = ("https://dchart-api.vndirect.com.vn/dchart/history"
          "?resolution=D&symbol=VNINDEX&from={0}&to={1}")

# group key -> (title, flag, benchmark label, benchmark source)
GROUPS = [
    ("CHINA",     "China",                 "🇨🇳", "SSE Composite",          "000001.SS"),
    ("HONG KONG", "Hong Kong",             "🇭🇰", "Hang Seng (HSI)",        "^HSI"),
    ("VIETNAM",   "Vietnam",               "🇻🇳", "VN-Index",               "VNINDEX"),
    ("JAPAN",     "Japan",                 "🇯🇵", "Nikkei 225 (NKY)",       "^N225"),
    ("SINGAPORE", "Singapore",             "🇸🇬", "Straits Times (STI)",    "^STI"),
    ("EUROPE",    "Europe",                "🇪🇺", "STOXX Europe 600 (SXXP)", "^STOXX"),
    ("US-NASDAQ", "United States · Nasdaq", "🇺🇸", "Nasdaq 100 (NDX)",       "^NDX"),
    ("US-NYSE",   "United States · NYSE",   "🇺🇸", "S&P 500 (SPX)",          "^GSPC"),
]

# TradingView exchange prefix -> market shown in the table
MARKETS = {
    "SSE": "Shanghai (SSE)", "SZSE": "Shenzhen (SZSE)", "HKEX": "Hong Kong (HKEX)",
    "HOSE": "Ho Chi Minh (HOSE)", "TSE": "Tokyo (TSE)", "SGX": "Singapore (SGX)",
    "NASDAQ": "Nasdaq", "NYSE": "NYSE", "AMEX": "NYSE Arca",
    "MIL": "Borsa Italiana", "OMXCOP": "Nasdaq Copenhagen", "XETR": "Xetra (Frankfurt)",
}
EURONEXT = {"FRANCE": "Euronext Paris", "NETHERLANDS": "Euronext Amsterdam"}

QUADS = ("Leading", "Weakening", "Lagging", "Improving")


def group_of(country, exch):
    if country in EUROPE:
        return "EUROPE"
    if country == "UNITED STATES":
        return "US-NASDAQ" if exch == "NASDAQ" else "US-NYSE"
    return country


def market_of(country, exch):
    if exch == "EURONEXT":
        return EURONEXT.get(country, "Euronext")
    return MARKETS.get(exch, exch)


def vnindex_closes():
    """VN-Index daily closes. Yahoo has no VN-Index; VNDirect's chart API does."""
    now = int(time.time())
    url = VN_API.format(now - 600 * 86400, now)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    for attempt in range(3):
        try:
            d = json.load(urllib.request.urlopen(req, timeout=30))
            break
        except Exception:
            if attempt == 2:
                raise
            time.sleep(3)
    if d.get("s") != "ok" or not d.get("t"):
        raise SystemExit(f"VN-Index fetch returned no data: {str(d)[:200]}")
    s = pd.Series({dt.datetime.fromtimestamp(t, dt.timezone.utc).date(): c
                   for t, c in zip(d["t"], d["c"])}).sort_index()
    stale = (dt.date.today() - s.index[-1]).days
    if stale > 5:
        raise SystemExit(f"VN-Index last bar {s.index[-1]} is {stale} days old")
    return s


def build():
    data = json.load(open(DASHBOARD, encoding="utf-8"))
    resolved = json.load(open(STATE, encoding="utf-8"))["resolved"]

    picks, unresolved = {}, []
    for r in data["rows"]:
        if r["country"] in SKIP or r["is_etf"]:
            continue
        tv = resolved.get(r["symbol"])
        if not tv:
            unresolved.append(r["symbol"])
            continue
        exch = tv.split(":")[0]
        picks.setdefault(tv, {"id": tv, "name": r["underlying"],
                              "yahoo": r["yahoo"], "ticker": tv.split(":")[-1],
                              "group": group_of(r["country"], exch),
                              "market": market_of(r["country"], exch),
                              "drs": []})["drs"].append(r["symbol"])
    rows = list(picks.values())
    for m in rows:
        m["drs"].sort()
    log(f"universe : {len(rows)} underlying stocks from {sum(len(m['drs']) for m in rows)} "
        f"DRs (ETFs and Taiwan skipped)")
    if unresolved:
        log(f"  no exchange mapping, skipped: {', '.join(unresolved)}")

    need = sorted({r["yahoo"] for r in rows} | {g[4] for g in GROUPS if g[4] != "VNINDEX"})
    log(f"prices   : {len(need)} Yahoo tickers")
    closes = yahoo_closes(need)
    # Yahoo's daily index history can lag a session behind its stocks (2026-10-27:
    # ^HSI ^N225 ^STOXX ^STI lacked Monday while every stock had it), which holds a
    # whole market back a day. Fill that one gap for the benchmarks only.
    from yahoo_patch import fill_missing_last_session
    fill_missing_last_session(closes, [g[4] for g in GROUPS if g[4] != "VNINDEX"], log)
    closes["VNINDEX"] = vnindex_closes()
    # Finished sessions only: a run during the day would otherwise score a live,
    # half-day bar for whichever markets are still open (Europe, Singapore).
    closes = {k: v[v.index < dt.date.today()] for k, v in closes.items()}
    log(f"           {len(closes)} series incl. VN-Index (last {closes['VNINDEX'].index[-1]})")

    groups, cache = [], {}
    for key, title, flag, blabel, bsym in GROUPS:
        bench = closes.get(bsym)
        members = [r for r in rows if r["group"] == key]
        if not members:
            continue
        if bench is None or not len(bench):
            raise SystemExit(f"no benchmark data for {title} ({bsym})")
        out = []
        for m in sorted(members, key=lambda m: m["name"].lower()):
            ck = (m["yahoo"], bsym)
            if ck not in cache:
                px = closes.get(m["yahoo"])
                cache[ck] = (None, "no price data") if px is None else \
                    (rrg_points(px, bench), "under 75 sessions of history")
            pts, why = cache[ck]
            row = {k: m[k] for k in ("id", "name", "drs", "market", "ticker")}
            if pts:
                hx, hy = pts[-1]
                row.update(x=hx, y=hy, q=quadrant(hx, hy), tail=pts)
            else:
                row["why"] = why
            out.append(row)
        counts = {q: sum(1 for r in out if r.get("q") == q) for q in QUADS}
        groups.append({"key": key, "title": title, "flag": flag, "bench": blabel,
                       "asof": str(bench.index[-1]), "counts": counts, "rows": out})
        log(f"  {title:<24} {len(out):>3} stocks vs {blabel:<24} "
            + "  ".join(f"{q[:4]} {n}" for q, n in counts.items())
            + f"  blank {sum(1 for r in out if 'q' not in r)}")

    meta = {"generated": time.strftime("%Y-%m-%d %H:%M"),
            "trading_date": data["tradingDate"],
            "window": WINDOW, "roc": ROC, "tail": TAIL,
            "stocks": sum(len(g["rows"]) for g in groups),
            "drs": sum(len(r["drs"]) for g in groups for r in g["rows"]),
            "scored": sum(1 for g in groups for r in g["rows"] if "q" in r)}
    return meta, groups


# --------------------------------------------------------------------- render

def gid(g):
    return "g-" + g["key"].lower().replace(" ", "-")


def render(meta, groups):
    e = html.escape
    return TEMPLATE.format(
        css=CSS, **stock_parts(groups),
        generated=e(meta["generated"]), trading=e(meta["trading_date"]),
        stocks=meta["stocks"], drs=meta["drs"], scored=meta["scored"],
        window=meta["window"], roc=meta["roc"])


def stock_parts(groups):
    """The pieces of the stock table, shared with the combined page (combine_rrg.py)."""
    e = html.escape
    total = {q: sum(g["counts"][q] for g in groups) for q in QUADS}
    body = []
    for g in groups:
        n = len(g["rows"])
        cs = " · ".join(f'<span class="q-{q[:4].lower()}-t">{q} {g["counts"][q]}</span>' for q in QUADS)
        body.append(
            f'<tbody class="grp" id="{gid(g)}"><tr class="ghead"><th colspan="3">'
            f'<span class="fl">{g["flag"]}</span> {e(g["title"])} '
            f'<span class="gn">{n} stocks</span>'
            f'<span class="gb">vs {e(g["bench"])} · {cs}</span></th></tr>')
        for r in g["rows"]:
            if "q" in r:
                q = r["q"]
                cell = f'<span class="qp q-{q[:4].lower()}">{q}</span>'
                attrs = f'data-q="{q}" data-x="{r["x"]}" data-y="{r["y"]}"'
            else:
                q = ""
                cell = f'<span class="na">– {e(r["why"])}</span>'
                attrs = 'data-q="" data-x="-1" data-y="-1"'
            search = e(f'{" ".join(r["drs"])} {r["name"]} {r["ticker"]} {r["market"]}'.lower())
            body.append(
                f'<tr class="dr" {attrs} data-s="{search}">'
                f'<td class="c-dr"><b>{e(r["name"])}</b><div class="nm">DR {e(", ".join(r["drs"]))}</div></td>'
                f'<td class="c-mk">{e(r["market"])}<div class="nm">{e(r["ticker"])}</div></td>'
                f'<td class="c-rrg"><div class="rr">{cell}</div></td></tr>')
        body.append("</tbody>")

    chips = "".join(
        f'<button class="chip qf" data-q="{q}" aria-pressed="true"><i class="dot q-{q[:4].lower()}"></i>{q}'
        f'<span class="n">{total[q]}</span></button>' for q in QUADS)
    jumps = "".join(f'<a class="chip" href="#{gid(g)}">{g["flag"]} {e(g["title"])}</a>' for g in groups)
    benches = "".join(f'<li><b>{g["flag"]} {e(g["title"])}</b> vs {e(g["bench"])} '
                      f'(last close {g["asof"]})</li>' for g in groups)

    return {"chips": chips, "jumps": jumps, "benches": benches, "body": "\n".join(body)}


CSS = """
:root{
  --head1:#1E4E9E; --head2:#163C7E; --ink:#1C2635; --ink-soft:#5B6B82; --ink-faint:#8A97A8;
  --bg:#F4F6FA; --surface:#FFFFFF; --line:#DCE3EE; --group-bg:#EAF0F9; --group-ink:#1B3A6B;
  --hover:#F2F6FC; --chip-bg:#FFFFFF;
  --lead:#1A7F4B; --weak:#B7791F; --lag:#B3392E; --imp:#1A56C4;
  --lead-bg:rgba(26,127,75,.10); --weak-bg:rgba(183,121,31,.12); --lag-bg:rgba(179,57,46,.10); --imp-bg:rgba(26,86,196,.10);
  --ax:#B9C3D3; --tail:#8A97A8;
}
@media (prefers-color-scheme: dark){ :root:not([data-theme="light"]){
  --head1:#1D3E7C; --head2:#142B58; --ink:#E4EAF4; --ink-soft:#9DABC0; --ink-faint:#6B7A90;
  --bg:#0E1420; --surface:#161D2B; --line:#2A3548; --group-bg:#1B2536; --group-ink:#A9C4EF;
  --hover:#1C2637; --chip-bg:#161D2B;
  --lead:#4CBF84; --weak:#E3B04B; --lag:#E07B6F; --imp:#8FB6F5;
  --lead-bg:rgba(76,191,132,.13); --weak-bg:rgba(227,176,75,.13); --lag-bg:rgba(224,123,111,.13); --imp-bg:rgba(143,182,245,.13);
  --ax:#3A4760; --tail:#6B7A90;
}}
:root[data-theme="dark"]{
  --head1:#1D3E7C; --head2:#142B58; --ink:#E4EAF4; --ink-soft:#9DABC0; --ink-faint:#6B7A90;
  --bg:#0E1420; --surface:#161D2B; --line:#2A3548; --group-bg:#1B2536; --group-ink:#A9C4EF;
  --hover:#1C2637; --chip-bg:#161D2B;
  --lead:#4CBF84; --weak:#E3B04B; --lag:#E07B6F; --imp:#8FB6F5;
  --lead-bg:rgba(76,191,132,.13); --weak-bg:rgba(227,176,75,.13); --lag-bg:rgba(224,123,111,.13); --imp-bg:rgba(143,182,245,.13);
  --ax:#3A4760; --tail:#6B7A90;
}
*{box-sizing:border-box}
body{margin:0; background:var(--bg); color:var(--ink); font:14px/1.45 "Segoe UI",Arial,"Helvetica Neue",sans-serif}
.wrap{max-width:1000px; margin:0 auto; padding:28px 16px 64px}
h1{font-size:22px; margin:0 0 4px}
.pages{display:flex; flex-wrap:wrap; gap:6px; margin:0 0 16px; font-size:12.5px}
.pages a,.pages .cur{padding:4px 12px; border-radius:4px; border:1px solid var(--line); text-decoration:none; color:var(--ink)}
.pages .cur{background:linear-gradient(var(--head1),var(--head2)); color:#fff; border-color:var(--head1)}
.pages a:hover{border-color:var(--head1)}
.meta{color:var(--ink-soft); font-size:12.5px; margin:0 0 4px}
.note{color:var(--ink-faint); font-size:11.5px; margin:0}
.controls{display:flex; flex-wrap:wrap; gap:8px; align-items:center; margin:18px 0 10px}
.chip{display:inline-flex; align-items:center; gap:6px; background:var(--chip-bg); border:1px solid var(--line);
  border-radius:4px; color:var(--ink); text-decoration:none; font:inherit; font-size:12px; padding:4px 10px; white-space:nowrap; cursor:pointer}
.chip:hover{border-color:var(--head1)}
.chip .n{color:var(--ink-faint); font-variant-numeric:tabular-nums}
.qf[aria-pressed="false"]{opacity:.38}
.dot{display:inline-block; width:9px; height:9px; border-radius:50%}
#q{margin-left:auto; min-width:200px; padding:6px 10px; font:inherit; font-size:13px; border:1px solid var(--line);
  border-radius:4px; background:var(--surface); color:var(--ink)}
.jumps{display:flex; flex-wrap:wrap; gap:6px; margin:0 0 14px}
.tw{background:var(--surface); border:1px solid var(--line); border-radius:6px; overflow-x:auto}
table{width:100%; border-collapse:collapse; font-size:14px}
thead th{background:linear-gradient(var(--head1),var(--head2)); color:#fff; text-align:left; font-weight:600;
  padding:9px 12px; position:sticky; top:0; z-index:2; cursor:pointer; user-select:none; white-space:nowrap}
thead th .ar{opacity:.6; font-size:11px; margin-left:4px}
.ghead th{background:var(--group-bg); color:var(--group-ink); text-align:left; padding:8px 12px; font-size:14px;
  border-top:1px solid var(--line); scroll-margin-top:44px}
.ghead .fl{font-size:15px}
.gn{font-weight:400; color:var(--ink-soft); font-size:12px; margin-left:6px}
.gb{display:block; font-weight:400; font-size:12px; color:var(--ink-soft); margin-top:2px}
td{padding:6px 12px; border-top:1px solid var(--line); vertical-align:middle}
tr.dr:hover td{background:var(--hover)}
.c-dr{width:38%} .c-mk{width:22%}
.nm{color:var(--ink-faint); font-size:11.5px; line-height:1.3; max-width:360px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap}
.etf{font-size:9.5px; font-weight:600; color:var(--ink-soft); border:1px solid var(--line); border-radius:3px; padding:0 4px; margin-left:4px; vertical-align:1px}
.rr{display:flex; align-items:center; gap:12px}
.mini{width:92px; height:60px; flex:none; border:1px solid var(--line); border-radius:3px; background:var(--surface)}
.b-lead{fill:var(--lead-bg)} .b-weak{fill:var(--weak-bg)} .b-lag{fill:var(--lag-bg)} .b-imp{fill:var(--imp-bg)}
.ax{stroke:var(--ax); stroke-width:1}
.tl{fill:none; stroke:var(--tail); stroke-width:1.4; stroke-linejoin:round}
.hd{stroke:var(--surface); stroke-width:1.2}
.q-lead{fill:var(--lead); background:var(--lead)} .q-weak{fill:var(--weak); background:var(--weak)}
.q-lagg{fill:var(--lag); background:var(--lag)} .q-impr{fill:var(--imp); background:var(--imp)}
.q-lead-t{color:var(--lead)} .q-weak-t{color:var(--weak)} .q-lagg-t{color:var(--lag)} .q-impr-t{color:var(--imp)}
.rv{display:flex; flex-direction:column; gap:3px}
.qp{color:#fff; font-size:11.5px; font-weight:600; border-radius:3px; padding:1px 8px; width:fit-content}
:root[data-theme="dark"] .qp{color:#0E1420}
@media (prefers-color-scheme: dark){ :root:not([data-theme="light"]) .qp{color:#0E1420} }
.num{font-size:11.5px; color:var(--ink-soft); font-variant-numeric:tabular-nums; line-height:1.3}
.na{color:var(--ink-faint); font-size:12px}
.foot{color:var(--ink-soft); font-size:12px; margin-top:18px}
.foot ul{margin:6px 0 10px; padding-left:18px}
.foot li{margin:2px 0}
.legend{display:flex; flex-wrap:wrap; gap:14px; font-size:12px; color:var(--ink-soft); margin:0 0 10px}
.legend span{display:inline-flex; align-items:center; gap:5px}
@media (max-width:640px){
  .wrap{padding:20px 16px 48px}
  #q{margin-left:0; min-width:0; width:100%}
  table{font-size:13px}
  .nm{max-width:130px; white-space:normal}
  td,thead th{padding:6px 8px}
  .rr{flex-direction:column; align-items:flex-start; gap:4px} .mini{width:78px; height:51px}
  .num{font-size:10.5px}
  .c-dr{width:auto} .c-mk{width:auto}
}
@media print{ .controls,.jumps{display:none} thead th{position:static} tr.dr{break-inside:avoid} }
"""

TEMPLATE = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>DR RRG Table</title>
<style>{css}</style></head>
<body><div class="wrap">
<nav class="pages"><span class="cur">Stocks vs home market</span><a href="country.html">Countries vs MSCI World</a></nav>
<header>
  <h1>SET DR · Relative Rotation (RRG) Table</h1>
  <p class="meta">{stocks} underlying stocks ({drs} DRs) · {scored} with an RRG reading · underlying closes to {trading} · built {generated}</p>
  <p class="note">Each underlying stock is measured in local currency against its home-market benchmark. ETFs and Taiwan are not included.</p>
</header>
<div class="controls">{chips}<input id="q" type="search" placeholder="Search DR, company, market…" aria-label="Search"></div>
<div class="jumps">{jumps}</div>
<div class="legend">
  <span><i class="dot q-lead"></i>Leading: strong and still gaining</span>
  <span><i class="dot q-weak"></i>Weakening: strong but losing momentum</span>
  <span><i class="dot q-lagg"></i>Lagging: weak and still losing</span>
  <span><i class="dot q-impr"></i>Improving: weak but gaining momentum</span>
</div>
<div class="tw"><table id="t">
<thead><tr><th data-k="dr">Underlying stock<span class="ar"></span></th><th data-k="mk">Market<span class="ar"></span></th><th data-k="rrg">RRG<span class="ar"></span></th></tr></thead>
{body}
</table></div>
<div class="foot">
  <b>Benchmarks</b>
  <ul>{benches}</ul>
  <b>Method.</b> Daily closes. RS = underlying ÷ benchmark. RS-Ratio = 100 + z-score of RS over {window} sessions;
  RS-Momentum = 100 + z-score of the {roc}-session change in RS-Ratio. Leading = both at or above 100;
  Weakening = RS-Ratio at or above 100, RS-Momentum below; Lagging = both below 100; Improving = RS-Ratio below 100,
  RS-Momentum at or above. Each row covers every DR on that stock. A blank means the underlying has too little
  history (new listings) or no price data. THB and the conversion ratio do not change relative strength, so the reading is
  the same as for the DR's own price.
  Sort by clicking a column header: <b>RRG</b> sorts Leading → Weakening → Improving → Lagging, by RS-Ratio within each.
</div>
</div>
<script>
(function(){{
  var on = {{Leading:1, Weakening:1, Lagging:1, Improving:1}}, term = "";
  var rows = Array.prototype.slice.call(document.querySelectorAll("tr.dr"));
  function apply(){{
    rows.forEach(function(r){{
      var q = r.getAttribute("data-q");
      var ok = (q === "" ? Object.keys(on).every(function(k){{return on[k];}}) : on[q]) &&
               (!term || r.getAttribute("data-s").indexOf(term) >= 0);
      r.style.display = ok ? "" : "none";
    }});
    document.querySelectorAll("tbody.grp").forEach(function(b){{
      var any = b.querySelector("tr.dr:not([style*='none'])");
      b.style.display = any ? "" : "none";
    }});
  }}
  document.querySelectorAll(".qf").forEach(function(b){{
    b.addEventListener("click", function(){{
      var q = b.getAttribute("data-q"); on[q] = on[q] ? 0 : 1;
      b.setAttribute("aria-pressed", on[q] ? "true" : "false"); apply();
    }});
  }});
  document.getElementById("q").addEventListener("input", function(e){{ term = e.target.value.trim().toLowerCase(); apply(); }});
  var rank = {{Leading:0, Weakening:1, Improving:2, Lagging:3, "":4}}, cur = null, dir = 1;
  function key(r, k){{
    if (k === "dr") return r.cells[0].querySelector("b").textContent;
    if (k === "mk") return r.cells[1].firstChild.textContent + " " + r.cells[0].querySelector("b").textContent;
    return [rank[r.getAttribute("data-q")], -parseFloat(r.getAttribute("data-x"))];
  }}
  function cmp(a, b){{
    if (Array.isArray(a)) return (a[0] - b[0]) || (a[1] - b[1]);
    return a < b ? -1 : a > b ? 1 : 0;
  }}
  document.querySelectorAll("#t thead th").forEach(function(th){{
    th.addEventListener("click", function(){{
      var k = th.getAttribute("data-k"); dir = (cur === k) ? -dir : 1; cur = k;
      document.querySelectorAll("#t thead .ar").forEach(function(a){{ a.textContent = ""; }});
      th.querySelector(".ar").textContent = dir > 0 ? "▲" : "▼";
      document.querySelectorAll("tbody.grp").forEach(function(b){{
        var rs = Array.prototype.slice.call(b.querySelectorAll("tr.dr"));
        rs.sort(function(x, y){{ return dir * cmp(key(x, k), key(y, k)); }});
        rs.forEach(function(r){{ b.appendChild(r); }});
      }});
    }});
  }});
}})();
</script>
</body></html>
"""


def main():
    meta, groups = build()
    json.dump({"meta": meta, "groups": groups}, open(OUT_DATA, "w", encoding="utf-8"),
              ensure_ascii=False)
    page = render(meta, groups)
    open(OUT_HTML, "w", encoding="utf-8").write(page)
    log(f"\nwrote {OUT_HTML}  ({len(page):,} bytes)")
    log(f"      {meta['scored']}/{meta['stocks']} stocks scored across {len(groups)} groups")
    return 0


if __name__ == "__main__":
    sys.exit(main())
