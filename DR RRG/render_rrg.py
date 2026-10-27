"""HTML renderer for the DR rotation dashboard.

Kept separate from build_rrg.py so the maths and the markup can be edited
independently. Palette and quadrant treatment follow the earlier single-panel
rrg.html: one mark colour throughout, because the Leading<->Lagging colour pair
fails colourblind separation and quadrant is already carried by position.
"""
import json

CSS = """
:root{
  --surface-1:#fcfcfb; --plane:#f9f9f7;
  --text-primary:#0b0b0b; --text-secondary:#52514e; --muted:#898781;
  --grid:#e1e0d9; --axis:#c3c2b7; --border:rgba(11,11,11,0.10);
  --mark:#2a78d6; --mark-tail:#86b6ef; --accent:#eb6834;
  --q-lead:rgba(12,163,12,0.07); --q-weak:rgba(250,178,25,0.09);
  --q-lag:rgba(208,59,59,0.07); --q-imp:rgba(42,120,214,0.07);
  --chip:#efeee9; --warn:#8a5a10; --warn-bg:rgba(250,178,25,0.13);
}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){
    --surface-1:#1a1a19; --plane:#0d0d0d;
    --text-primary:#fff; --text-secondary:#c3c2b7; --muted:#898781;
    --grid:#2c2c2a; --axis:#383835; --border:rgba(255,255,255,0.10);
    --mark:#3987e5; --mark-tail:#1c5cab; --accent:#d95926;
    --q-lead:rgba(12,163,12,0.075); --q-weak:rgba(250,178,25,0.065);
    --q-lag:rgba(208,59,59,0.075); --q-imp:rgba(57,135,229,0.08);
    --chip:#242422; --warn:#f0c266; --warn-bg:rgba(250,178,25,0.10);
  }
}
:root[data-theme="dark"]{
  --surface-1:#1a1a19; --plane:#0d0d0d;
  --text-primary:#fff; --text-secondary:#c3c2b7; --muted:#898781;
  --grid:#2c2c2a; --axis:#383835; --border:rgba(255,255,255,0.10);
  --mark:#3987e5; --mark-tail:#1c5cab; --accent:#d95926;
  --q-lead:rgba(12,163,12,0.075); --q-weak:rgba(250,178,25,0.065);
  --q-lag:rgba(208,59,59,0.075); --q-imp:rgba(57,135,229,0.08);
  --chip:#242422; --warn:#f0c266; --warn-bg:rgba(250,178,25,0.10);
}
*{box-sizing:border-box}
body{
  font-family:system-ui,-apple-system,"Segoe UI",sans-serif;
  color:var(--text-primary); background:var(--plane);
  max-width:1180px; margin:0 auto; padding:28px 20px 64px; line-height:1.5;
}
.eyebrow{font-size:.72rem; letter-spacing:.09em; text-transform:uppercase; color:var(--muted); margin:0 0 6px}
h1{font-size:1.75rem; margin:0 0 6px; letter-spacing:-0.02em}
.sub{color:var(--text-secondary); margin:0 0 4px; font-size:.95rem}
.meta{color:var(--muted); font-size:.8rem; margin:0 0 22px}
.card{background:var(--surface-1); border:1px solid var(--border); border-radius:12px; padding:16px}
.tabs{display:flex; gap:6px; flex-wrap:wrap; margin-bottom:16px}
.tab{
  font:inherit; font-size:.83rem; padding:7px 13px; border-radius:999px; cursor:pointer;
  background:var(--chip); color:var(--text-secondary); border:1px solid transparent;
}
.tab[aria-selected="true"]{background:var(--mark); color:#fff; border-color:var(--mark)}
.tab .n{opacity:.7; margin-left:6px; font-variant-numeric:tabular-nums}
.filters{display:flex; gap:8px; flex-wrap:wrap; align-items:center; margin-bottom:12px}
.chip{
  font:inherit; font-size:.78rem; padding:5px 11px; border-radius:999px; cursor:pointer;
  background:var(--chip); color:var(--text-secondary); border:1px solid transparent;
}
.chip[aria-pressed="false"]{opacity:.4}
.chip .n{opacity:.65; margin-left:5px; font-variant-numeric:tabular-nums}
input[type=search]{
  font:inherit; font-size:.8rem; padding:5px 10px; border-radius:8px;
  border:1px solid var(--border); background:var(--plane); color:var(--text-primary); width:150px;
}
.thin{
  background:var(--warn-bg); color:var(--warn); border-radius:8px; padding:8px 12px;
  font-size:.8rem; margin-bottom:12px;
}
.layout{display:grid; grid-template-columns:minmax(0,620px) minmax(0,1fr); gap:20px; align-items:start}
@media (max-width:900px){ .layout{grid-template-columns:1fr} }
.plotwrap{position:relative}
svg{width:100%; height:auto; display:block; overflow:visible}
.qlabel{font-size:11px; fill:var(--muted); letter-spacing:.05em; text-transform:uppercase}
.axlabel{font-size:10px; fill:var(--muted); font-variant-numeric:tabular-nums}
.axtitle{font-size:11px; fill:var(--text-secondary)}
.tip{
  position:absolute; pointer-events:none; opacity:0; transition:opacity .12s;
  background:var(--text-primary); color:var(--plane); font-size:.75rem;
  padding:6px 9px; border-radius:7px; white-space:nowrap; z-index:5;
}
.tablewrap{max-height:560px; overflow:auto}
table{width:100%; border-collapse:collapse; font-size:.8rem}
th,td{text-align:right; padding:6px 8px; border-bottom:1px solid var(--border); white-space:nowrap}
th:first-child,td:first-child,th:nth-child(2),td:nth-child(2){text-align:left}
th{position:sticky; top:0; background:var(--surface-1); cursor:pointer; font-weight:600; color:var(--text-secondary)}
td.num{font-variant-numeric:tabular-nums}
td.co{color:var(--text-secondary); max-width:190px; overflow:hidden; text-overflow:ellipsis}
.legend{display:flex; gap:16px; flex-wrap:wrap; font-size:.76rem; color:var(--text-secondary); margin-top:10px}
.legend i{display:inline-block; width:10px; height:10px; border-radius:50%; background:var(--mark); margin-right:5px; vertical-align:-1px}
.legend .tl{display:inline-block; width:16px; height:2px; background:var(--mark-tail); margin-right:5px; vertical-align:4px}
.note{font-size:.78rem; color:var(--text-secondary); margin-top:26px; line-height:1.65}
.note strong{color:var(--text-primary)}
"""

JS = r"""
const $ = s => document.querySelector(s);
const NS = 'http://www.w3.org/2000/svg';
const S = 620, M = {t:30, r:30, b:46, l:52};
const QS = ['Leading','Weakening','Lagging','Improving'];
const state = {p:0, q:new Set(QS), find:'', labels:false, sort:'t', dir:1};

const el = (n,a) => { const e = document.createElementNS(NS,n); for (const k in a) e.setAttribute(k,a[k]); return e; };
const panel = () => PANELS[state.p];
const visible = () => panel().pts.filter(r => state.q.has(r.q) &&
  (!state.find || r.t.toLowerCase().includes(state.find) || r.n.toLowerCase().includes(state.find)));

function domain(pts){
  let lo = 100, hi = 100;
  for (const r of pts) for (const [a,b] of r.tail){ lo = Math.min(lo,a,b); hi = Math.max(hi,a,b); }
  // Keep 100 exactly centred so the quadrants read as equal quarters.
  const half = Math.max(hi - 100, 100 - lo) * 1.08 || 2;
  return {lo: 100 - half, hi: 100 + half};
}

function draw(){
  const svg = $('#plot'); svg.textContent = '';
  const p = panel(), rows = visible(), D = domain(p.pts);
  const px = v => M.l + (v - D.lo)/(D.hi - D.lo)*(S - M.l - M.r);
  const py = v => S - M.b - (v - D.lo)/(D.hi - D.lo)*(S - M.t - M.b);
  const L = M.l, R = S - M.r, T = M.t, B = S - M.b, x0 = px(100), y0 = py(100);

  for (const [x,y,w,h,f] of [[x0,T,R-x0,y0-T,'--q-lead'],[x0,y0,R-x0,B-y0,'--q-weak'],
                             [L,y0,x0-L,B-y0,'--q-lag'],[L,T,x0-L,y0-T,'--q-imp']])
    svg.appendChild(el('rect',{x,y,width:Math.max(0,w),height:Math.max(0,h),fill:`var(${f})`}));

  for (const [tx,ty,an,tt] of [[R-6,T+14,'end','Leading'],[R-6,B-8,'end','Weakening'],
                               [L+6,B-8,'start','Lagging'],[L+6,T+14,'start','Improving']]){
    const t = el('text',{x:tx,y:ty,class:'qlabel','text-anchor':an}); t.textContent = tt; svg.appendChild(t);
  }

  const step = (D.hi - D.lo) > 12 ? 4 : ((D.hi - D.lo) > 6 ? 2 : 1);
  for (let v = Math.ceil(D.lo); v <= D.hi; v++){
    if (v % step) continue;
    svg.appendChild(el('line',{x1:px(v),y1:T,x2:px(v),y2:B,stroke:'var(--grid)','stroke-width':1}));
    svg.appendChild(el('line',{x1:L,y1:py(v),x2:R,y2:py(v),stroke:'var(--grid)','stroke-width':1}));
    const a = el('text',{x:px(v),y:B+16,class:'axlabel','text-anchor':'middle'}); a.textContent = v; svg.appendChild(a);
    const b = el('text',{x:L-8,y:py(v)+4,class:'axlabel','text-anchor':'end'}); b.textContent = v; svg.appendChild(b);
  }
  svg.appendChild(el('line',{x1:x0,y1:T,x2:x0,y2:B,stroke:'var(--axis)','stroke-width':1.5}));
  svg.appendChild(el('line',{x1:L,y1:y0,x2:R,y2:y0,stroke:'var(--axis)','stroke-width':1.5}));

  const xt = el('text',{x:(L+R)/2,y:S-10,class:'axtitle','text-anchor':'middle'});
  xt.textContent = 'RS-Ratio  (relative strength vs ' + p.bench + ')'; svg.appendChild(xt);
  const yt = el('text',{x:14,y:(T+B)/2,class:'axtitle','text-anchor':'middle',transform:`rotate(-90 14 ${(T+B)/2})`});
  yt.textContent = 'RS-Momentum'; svg.appendChild(yt);

  const tip = $('#tip');
  for (const r of rows){
    svg.appendChild(el('polyline',{points:r.tail.map(([a,b])=>`${px(a)},${py(b)}`).join(' '),
      fill:'none', stroke:'var(--mark-tail)', 'stroke-width':1.6, 'stroke-linecap':'round'}));
    const dot = el('circle',{cx:px(r.x), cy:py(r.y), r:4.5, fill:'var(--mark)'});
    dot.addEventListener('mouseenter', e => {
      tip.innerHTML = `<strong>${r.t}</strong> · ${r.q}<br>${r.n}<br>` +
        `RS-Ratio ${r.x.toFixed(2)} · Mom ${r.y.toFixed(2)}<br>` +
        `<span style="opacity:.7">DR: ${r.drs.join(', ')}</span>`;
      tip.style.opacity = 1;
      const w = svg.getBoundingClientRect();
      tip.style.left = (px(r.x)/S*w.width + 12) + 'px';
      tip.style.top  = (py(r.y)/S*w.height - 10) + 'px';
    });
    dot.addEventListener('mouseleave', () => tip.style.opacity = 0);
    svg.appendChild(dot);
    if (state.labels){
      const lb = el('text',{x:px(r.x)+8, y:py(r.y)-7, class:'axlabel','text-anchor':'start'});
      lb.textContent = r.t; svg.appendChild(lb);
    }
  }
}

function table(){
  const tb = $('#tbl tbody'); tb.textContent = '';
  const rows = visible().slice().sort((a,b) => {
    const k = state.sort, va = a[k], vb = b[k];
    return (typeof va === 'string' ? va.localeCompare(vb) : va - vb) * state.dir;
  });
  for (const r of rows){
    const tr = document.createElement('tr');
    tr.innerHTML = `<td><strong>${r.t}</strong></td><td class="co" title="${r.n}">${r.n}</td>` +
      `<td>${r.q}</td><td class="num">${r.x.toFixed(2)}</td><td class="num">${r.y.toFixed(2)}</td>` +
      `<td class="num">${r.dx > 0 ? '+' : ''}${r.dx.toFixed(2)}</td>` +
      `<td class="num">${r.dy > 0 ? '+' : ''}${r.dy.toFixed(2)}</td>`;
    tb.appendChild(tr);
  }
}

function chips(){
  const c = $('#chips'); c.textContent = '';
  for (const q of QS){
    const b = document.createElement('button');
    b.className = 'chip'; b.setAttribute('aria-pressed', state.q.has(q));
    b.innerHTML = `${q}<span class="n">${panel().counts[q]}</span>`;
    b.onclick = () => { state.q.has(q) ? state.q.delete(q) : state.q.add(q); chips(); draw(); table(); };
    c.appendChild(b);
  }
}

function head(){
  const p = panel();
  $('#pbench').textContent = `${p.n} underlying stocks vs ${p.bench}`;
  const w = $('#thin');
  w.style.display = p.thin ? 'block' : 'none';
  w.textContent = `Only ${p.n} holdings — too few for the cloud to describe a market. ` +
    `Read individual positions, not the overall rotation.`;
}

function render(){ head(); chips(); draw(); table(); }

function tabs(){
  const t = $('#tabs');
  PANELS.forEach((p, i) => {
    const b = document.createElement('button');
    b.className = 'tab'; b.setAttribute('aria-selected', i === state.p);
    b.innerHTML = `${p.title}<span class="n">${p.n}</span>`;
    b.onclick = () => {
      state.p = i; state.q = new Set(QS); state.find = ''; $('#q').value = '';
      [...t.children].forEach((c, j) => c.setAttribute('aria-selected', j === i));
      render();
    };
    t.appendChild(b);
  });
}

$('#q').addEventListener('input', e => { state.find = e.target.value.toLowerCase().trim(); draw(); table(); });
$('#lbl').addEventListener('click', e => {
  state.labels = !state.labels; e.target.setAttribute('aria-pressed', state.labels); draw();
});
document.querySelectorAll('#tbl th').forEach(th => th.addEventListener('click', () => {
  const k = th.dataset.k;
  state.dir = (state.sort === k) ? -state.dir : 1;
  state.sort = k; table();
}));

tabs(); render();
"""


def render(meta, panels):
    payload = [{"title": p["title"], "bench": p["bench"], "n": p["n"],
                "thin": p["thin"], "counts": p["counts"], "pts": p["pts"]}
               for p in panels]

    names = ", ".join(f"{p['title']} ({p['n']})" for p in panels)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>DR Rotation</title>
<style>{CSS}</style>
</head>
<body>
<p class="eyebrow">Relative rotation · daily</p>
<h1>DR Rotation</h1>
<p class="sub">Relative Rotation Graphs for the <strong>DR Watchlist</strong> —
{meta['universe']} underlying stocks from {meta['drs']} depositary receipts,
each market against its own index.</p>
<p class="meta">Head + {meta['tail']} trailing sessions · daily bars ·
SET data {meta['trading_date']} · generated {meta['generated']}</p>

<div id="tabs" class="tabs" role="tablist"></div>

<div id="thin" class="thin" style="display:none"></div>

<div class="card">
  <p class="sub" id="pbench" style="margin-bottom:12px"></p>
  <div class="filters">
    <span id="chips" style="display:flex; gap:8px; flex-wrap:wrap"></span>
    <input type="search" id="q" placeholder="Find…" aria-label="Find stock">
    <button class="chip" id="lbl" aria-pressed="false">Labels</button>
  </div>
  <div class="layout">
    <div class="plotwrap">
      <svg id="plot" viewBox="0 0 620 620" role="img" aria-label="Relative rotation graph"></svg>
      <div class="tip" id="tip"></div>
    </div>
    <div class="tablewrap">
      <table id="tbl">
        <thead><tr>
          <th data-k="t">Ticker</th><th data-k="n">Company</th><th data-k="q">Quadrant</th>
          <th data-k="x">RS-Ratio</th><th data-k="y">RS-Mom</th>
          <th data-k="dx">Δ Ratio</th><th data-k="dy">Δ Mom</th>
        </tr></thead>
        <tbody></tbody>
      </table>
    </div>
  </div>
  <div class="legend">
    <span><i></i>Latest session (head)</span>
    <span><span class="tl"></span>Prior {meta['tail']} sessions — tail direction shows rotation</span>
  </div>
</div>

<p class="note">
<strong>Panels.</strong> {names}. Taiwan is omitted: all three Taiwanese DRs track ETFs,
so nothing survives the stocks-only filter.
<br><br>
<strong>Method.</strong> RS = 100 × (price ÷ benchmark) on shared bar timestamps.
RS-Ratio = 100 + the z-score of RS over a {meta['window']}-day window;
RS-Momentum = 100 + the z-score of the {meta['roc']}-day rate of change of RS-Ratio, same window.
JdK's published RS-Ratio and RS-Momentum formulas are proprietary, so this is a standard
z-score replication — quadrant placement and rotation direction track the original closely,
absolute values will not match exactly. Treat anything within ~0.3 of a boundary as unclassified.
<br><br>
<strong>Currency.</strong> Computed on the underlying listings in their own currency, not on the
THB DR prices. Each DR's THB price is underlying × FX ÷ conversion ratio, and within a country
panel both FX and ratio are common constants, so they cancel out of relative strength exactly —
the local-currency result is the same rotation against a local benchmark, with less noise.
Rotation therefore does not reflect your FX exposure.
<br><br>
<strong>Deduplication.</strong> Multiple DRs on one company collapse to a single mark under the
underlying ticker — AAPL01/03/19/80 plot once as AAPL. Hover a mark to see which DRs it covers.
<br><br>
Marks share one colour by design: quadrant is carried by position and by the labelled regions,
because the Leading↔Lagging colour pair fails colourblind separation (ΔE 4.1 under deuteranopia).
</p>

<script>
const PANELS = {json.dumps(payload, ensure_ascii=False)};
{JS}
</script>
</body>
</html>
"""
