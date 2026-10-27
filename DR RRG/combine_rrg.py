"""Combine the country and stock RRG tables into one dashboard page.

Reads the data the two builders already wrote (country_rrg_data.json,
rrg_table_data.json) -- it fetches nothing -- and writes dr_rrg_combined.html:
countries vs MSCI World on top, then every underlying stock vs its home market.

    python build_country_rrg.py && python build_rrg_table.py && python combine_rrg.py
"""
import html
import json
import os
import sys

import build_country_rrg as country
import build_rrg_table as stock
from build_rrg import ROOT, log

OUT_HTML = os.path.join(ROOT, "dr_rrg_combined.html")

# The stock table's filter/sort script, reused as written there (it is stored
# inside a .format() template, so its braces are doubled).
_t = stock.TEMPLATE
STOCK_JS = _t[_t.index("<script>"):_t.index("</script>") + 9].replace("{{", "{").replace("}}", "}")

CSS_EXTRA = """
.wrap{max-width:1000px}
.sec{margin-top:34px; scroll-margin-top:12px}
.sec h2{font-size:18px; margin:0 0 2px}
.sec .meta{margin-bottom:10px}
.toc{display:flex; flex-wrap:wrap; gap:6px; margin:16px 0 14px}
.toc a{padding:5px 12px; border-radius:4px; border:1px solid var(--line); background:var(--chip-bg);
  color:var(--ink); text-decoration:none; font-size:12.5px}
.toc a:hover{border-color:var(--head1)}
.foot h3{font-size:13px; margin:14px 0 4px}
.tools{display:flex; gap:6px; margin-left:auto}
.tbtn{font:inherit; font-size:12.5px; font-weight:600; padding:5px 12px; border-radius:4px; cursor:pointer;
  border:1px solid var(--head1); background:linear-gradient(var(--head1),var(--head2)); color:#fff}
.tbtn:hover{filter:brightness(1.12)} .tbtn:disabled{opacity:.6; cursor:progress}
.tbtn:focus-visible,.toc a:focus-visible{outline:2px solid var(--imp); outline-offset:2px}
@media (max-width:640px){ .tools{margin-left:0} }
@media print{
  @page{size:A4 portrait; margin:12mm}
  *{-webkit-print-color-adjust:exact; print-color-adjust:exact}
  .wrap{max-width:none; padding:0}
  .noexport,.controls,.jumps{display:none !important}
  .chart{overflow:visible; break-inside:avoid}
  svg.rrg{min-width:0}
  .tw{overflow:visible}
  thead{display:table-header-group}
  .ghead{break-after:avoid}
  #stocks{break-before:page}
}
"""

TEMPLATE = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>DR RRG Dashboard</title>
<style>{css}</style></head>
<body><div class="wrap">
<header>
  <h1>SET DR · Relative Rotation (RRG) Dashboard</h1>
  <p class="meta">MSCI World to {world} · home-market closes to {trading} · built {generated}</p>
  <p class="note">Where each DR market stands against the world, then where each underlying stock stands against its own market.</p>
</header>
<nav class="toc noexport"><a href="#countries">Countries vs MSCI World</a><a href="#stocks">Stocks vs home market</a>
  <span class="tools"><button type="button" class="tbtn" id="btn-pdf">Save as PDF</button></span></nav>
<div class="legend">
  <span><i class="dot q-lead"></i>Leading: outperforming and still gaining</span>
  <span><i class="dot q-weak"></i>Weakening: outperforming but losing momentum</span>
  <span><i class="dot q-lagg"></i>Lagging: underperforming and still losing</span>
  <span><i class="dot q-impr"></i>Improving: underperforming but gaining momentum</span>
</div>

<section class="sec" id="countries">
  <h2>Countries vs MSCI World</h2>
  <p class="meta">{ncountry} markets with DRs on SET · each main index in US dollars against the MSCI World Index · {csummary}</p>
  <div class="chart" id="country-graph">{cgraph}</div>
  <p class="note" style="margin-top:6px">Large dot = latest close ({world}); the line runs back through the previous {tail} sessions. Hover a dot for its values.</p>
  <div class="keys">{ckeys}</div>
</section>

<section class="sec" id="stocks">
  <h2>Stocks vs home market</h2>
  <p class="meta">{stocks} underlying stocks ({drs} DRs) · {scored} with a reading · each against its home-market index in local currency</p>
  <div class="controls">{chips}<input id="q" type="search" placeholder="Search company, DR, market…" aria-label="Search stocks"></div>
  <div class="jumps">{jumps}</div>
  <div class="tw"><table id="t">
  <thead><tr><th data-k="dr">Underlying stock<span class="ar"></span></th><th data-k="mk">Market<span class="ar"></span></th><th data-k="rrg">RRG<span class="ar"></span></th></tr></thead>
{sbody}
  </table></div>
</section>

<div class="foot">
  <h3>Method</h3>
  Daily closes. RS = price ÷ benchmark. RS-Ratio = 100 + z-score of RS over {window} sessions; RS-Momentum = 100 + z-score
  of the {roc}-session change in RS-Ratio. Leading = both at or above 100; Weakening = RS-Ratio at or above 100,
  RS-Momentum below; Lagging = both below 100; Improving = RS-Ratio below 100, RS-Momentum at or above.
  <h3>Countries</h3>
  Each local index is converted to US dollars with that day's exchange rate, so currency moves count, as they do for a DR
  holder, and compared with the MSCI World Index (USD). The US is two markets: the Nasdaq 100 for DRs on Nasdaq-listed
  stocks and the S&amp;P 500 for DRs on NYSE-listed ones. Europe is one point for the DRs on French, German, Italian, Dutch
  and Danish stocks, measured by the STOXX Europe 600.
  <h3>Stocks</h3>
  Each underlying stock is measured in its own currency against its home-market index; THB and the DR conversion ratio
  cancel out of relative strength, so the reading is the same as for each DR's own price. ETFs and Taiwan are not included.
  Each row covers every DR on that stock. A blank means the stock listed too recently for a reading. Click a column
  heading to sort; RRG sorts Leading, Weakening, Improving, Lagging, strongest first.
  <ul>{benches}</ul>
  Sources: MSCI (MSCI World), Yahoo Finance (stocks, indices, FX), VNDirect (VN-Index).
</div>
</div>
{js}
<script>
(function(){{
  // The PDF always uses the light palette (it prints better), then the viewer's theme comes back.
  var root = document.documentElement, saved = null;
  window.addEventListener("beforeprint", function(){{ saved = root.getAttribute("data-theme"); root.setAttribute("data-theme", "light"); }});
  window.addEventListener("afterprint", function(){{ if (saved === null) root.removeAttribute("data-theme"); else root.setAttribute("data-theme", saved); }});
  document.getElementById("btn-pdf").addEventListener("click", function(){{ window.print(); }});
}})();
</script>
</body></html>
"""


def main():
    c = json.load(open(country.OUT_DATA, encoding="utf-8"))
    s = json.load(open(stock.OUT_DATA, encoding="utf-8"))
    cgraph, csummary = country.country_graph(c["rows"])
    sp = stock.stock_parts(s["groups"])
    e = html.escape
    page = TEMPLATE.format(
        css=stock.CSS + country.GRAPH_CSS + CSS_EXTRA, js=STOCK_JS,
        world=e(c["meta"]["world_last"]), trading=e(max(g["asof"] for g in s["groups"])),
        generated=e(max(c["meta"]["generated"], s["meta"]["generated"])),
        ncountry=len(c["rows"]), csummary=csummary, cgraph=cgraph,
        ckeys=country.country_keys(c["rows"]), tail=c["meta"]["tail"],
        stocks=s["meta"]["stocks"], drs=s["meta"]["drs"], scored=s["meta"]["scored"],
        chips=sp["chips"], jumps=sp["jumps"], sbody=sp["body"], benches=sp["benches"],
        window=s["meta"]["window"], roc=s["meta"]["roc"])
    open(OUT_HTML, "w", encoding="utf-8").write(page)
    log(f"wrote {OUT_HTML}  ({len(page):,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
