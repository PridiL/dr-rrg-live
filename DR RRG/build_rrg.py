"""Build the DR Relative Rotation dashboard.

Universe: every DR in the DR Dashboard whose underlying is a STOCK (ETFs are
excluded), deduplicated to one point per underlying -- AAPL01/03/19/80 collapse
to a single AAPL, because they are the same company on the same exchange and
would otherwise stack four identical marks.

Rotation is computed on the UNDERLYING listings in their own currency, never on
the THB DR price. That is not a shortcut: each DR's THB price is
underlying x FX / ratio, and both FX and ratio are constants common to the
whole country panel, so they cancel out of relative strength exactly. Measuring
in local currency against a local benchmark is the same rotation with less noise.

Each country is measured against its own market index:

    UNITED STATES  S&P 500          ^GSPC
    HONG KONG      Hang Seng        ^HSI
    JAPAN          TOPIX            TSE:TOPIX     (TradingView - no Yahoo symbol)
    CHINA          SSE Composite    000001.SS
    VIETNAM        VN-Index         HOSE:VNINDEX  (TradingView - no Yahoo symbol)
    SINGAPORE      Straits Times    ^STI
    EUROPE         STOXX Europe 600 ^STOXX

Taiwan is omitted (its DRs are all ETFs, so nothing survives the stock filter).

    python build_rrg.py            # rebuild from cached index history
    python build_rrg.py --refresh  # re-pull TOPIX/VN-Index first (needs TradingView + CDP)
"""
import json, math, os, subprocess, sys, time, warnings
import pandas as pd
import yfinance as yf

warnings.filterwarnings("ignore")

ROOT = os.path.dirname(os.path.abspath(__file__))
DASHBOARD = os.path.join(os.path.dirname(ROOT), "DR Dashboard", "dashboard_data.json")
STATE = os.path.join(os.path.dirname(ROOT), "DR Dashboard", "dr_watchlist_state.json")
TV_CACHE = os.path.join(ROOT, "tv_index_cache.json")
FETCHER = os.path.join(ROOT, "fetch_tv_index.mjs")
OUT_HTML = os.path.join(ROOT, "dr_rrg_dashboard.html")
OUT_DATA = os.path.join(ROOT, "rrg_data.json")
NODE = r"C:\Program Files\nodejs\node.exe"

WINDOW = 60      # z-score lookback, in trading days
ROC = 10         # rate-of-change span for momentum
TAIL = 2         # trailing sessions behind the head, per the brief

EUROPE = {"FRANCE", "GERMANY", "DENMARK", "ITALY", "NETHERLANDS"}

# panel key -> (display title, benchmark label, yahoo ticker or None, TV symbol or None)
PANELS = [
    ("UNITED STATES", "United States", "S&P 500 (SPX)",        "^GSPC",     None),
    ("HONG KONG",     "Hong Kong",     "Hang Seng (HSI)",      "^HSI",      None),
    ("JAPAN",         "Japan",         "TOPIX",                None,        "TSE:TOPIX"),
    ("CHINA",         "China",         "SSE Composite",        "000001.SS", None),
    ("VIETNAM",       "Vietnam",       "VN-Index",             None,        "HOSE:VNINDEX"),
    ("SINGAPORE",     "Singapore",     "Straits Times (STI)",  "^STI",      None),
    ("EUROPE",        "Europe",        "STOXX Europe 600 (SXXP)", "^STOXX", None),
]
THIN = 10        # panels below this many holdings get a sparse-sample warning


def log(m):
    print(m, flush=True)


# ------------------------------------------------------------------ universe

def universe():
    """Non-ETF DRs, collapsed to one row per underlying."""
    data = json.load(open(DASHBOARD, encoding="utf-8"))
    resolved = json.load(open(STATE, encoding="utf-8"))["resolved"]

    picks = {}
    for r in data["rows"]:
        if r["is_etf"]:
            continue
        tv = resolved.get(r["symbol"])
        if not tv:
            continue
        panel = "EUROPE" if r["country"] in EUROPE else r["country"]
        key = (panel, tv)
        picks.setdefault(key, {
            "panel": panel, "tv": tv, "ticker": tv.split(":")[-1],
            "yahoo": r["yahoo"], "name": r["underlying"],
            "country": r["country"], "drs": [],
        })["drs"].append(r["symbol"])

    for v in picks.values():
        v["drs"].sort()
    return data, sorted(picks.values(), key=lambda v: (v["panel"], v["ticker"]))


# -------------------------------------------------------------------- prices

def yahoo_closes(tickers, period="400d"):
    """Daily adjusted closes as {ticker: Series indexed by date}."""
    out, chunk = {}, 40
    for i in range(0, len(tickers), chunk):
        part = tickers[i:i + chunk]
        for attempt in range(3):
            try:
                df = yf.download(part, period=period, interval="1d", auto_adjust=True,
                                 progress=False, threads=True, group_by="ticker")
                break
            except Exception:
                if attempt == 2:
                    df = None
                time.sleep(3)
        if df is None:
            continue
        for t in part:
            try:
                s = df[t]["Close"] if len(part) > 1 else df["Close"]
            except Exception:
                continue
            s = s.dropna()
            if len(s):
                s.index = [d.date() for d in s.index]
                out[t] = s
        log(f"  fetched {min(i+chunk, len(tickers))}/{len(tickers)}")
        time.sleep(0.4)
    return out


def tv_closes(refresh):
    """Daily closes for the indices Yahoo does not carry."""
    syms = [tv for _, _, _, y, tv in PANELS if tv]
    if refresh or not os.path.exists(TV_CACHE):
        log(f"pulling {len(syms)} index histories from TradingView")
        p = subprocess.run([NODE, FETCHER, TV_CACHE] + syms,
                           capture_output=True, text=True, timeout=300)
        for line in (p.stdout or "").splitlines():
            log("  " + line)
        if p.returncode != 0:
            raise SystemExit("index fetch failed:\n" + (p.stderr or "")[:600])

    raw = json.load(open(TV_CACHE, encoding="utf-8"))
    out = {}
    for sym, bars in raw.items():
        s = pd.Series({pd.Timestamp(t, unit="s").date(): c for t, c in bars})
        out[sym] = s.sort_index()

    # A stale cache is worse than a missing one: the Japan and Vietnam panels
    # would silently score today's stock prices against a benchmark that stopped
    # days ago, which shifts every point in those panels. Refuse rather than
    # quietly publish that.
    missing = [sym for sym, tv in ((s, v) for s, v in out.items()) if not len(tv)]
    if missing:
        raise SystemExit(f"index cache empty for {missing}; rerun with --refresh")
    stale = pd.Timestamp.today().date() - min(s.index[-1] for s in out.values())
    if stale.days > 5:
        raise SystemExit(
            f"index cache is {stale.days} days old (last bar "
            f"{min(s.index[-1] for s in out.values())}).\n"
            f"Rerun with --refresh, which needs TradingView Desktop up with CDP on 9222.")
    if stale.days > 2:
        log(f"  NOTE: index cache last bar is {stale.days} days old")
    return out


# ----------------------------------------------------------------- RRG maths

def rrg_points(px, bench):
    """JdK-style RS-Ratio / RS-Momentum, z-score replication.

    Returns the last TAIL+1 (x, y) points, oldest first, or None if there is
    not enough overlapping history.
    """
    df = pd.concat({"p": px, "b": bench}, axis=1).dropna()
    if len(df) < WINDOW + ROC + TAIL + 5:
        return None

    rs = 100.0 * df["p"] / df["b"]
    ratio = 100 + (rs - rs.rolling(WINDOW).mean()) / rs.rolling(WINDOW).std()
    mom_raw = ratio.diff(ROC)
    mom = 100 + (mom_raw - mom_raw.rolling(WINDOW).mean()) / mom_raw.rolling(WINDOW).std()

    pts = pd.concat({"x": ratio, "y": mom}, axis=1).dropna()
    if len(pts) < TAIL + 1:
        return None
    tail = pts.iloc[-(TAIL + 1):]
    if not all(map(math.isfinite, tail.to_numpy().ravel())):
        return None
    return [[round(float(a), 3), round(float(b), 3)] for a, b in tail.to_numpy()]


def quadrant(x, y):
    if x >= 100 and y >= 100:
        return "Leading"
    if x >= 100:
        return "Weakening"
    if y >= 100:
        return "Improving"
    return "Lagging"


# -------------------------------------------------------------------- build

def main():
    refresh = "--refresh" in sys.argv
    data, rows = universe()
    log(f"universe : {len(rows)} unique underlyings from "
        f"{sum(len(r['drs']) for r in rows)} non-ETF DRs")

    tv = tv_closes(refresh)

    need = sorted({r["yahoo"] for r in rows} |
                  {y for _, _, _, y, _ in PANELS if y})
    log(f"prices   : {len(need)} Yahoo tickers")
    closes = yahoo_closes(need)
    log(f"           {len(closes)} returned data")

    panels, dropped = [], []
    for key, title, blabel, ysym, tvsym in PANELS:
        members = [r for r in rows if r["panel"] == key]
        if not members:
            continue
        bench = closes.get(ysym) if ysym else tv.get(tvsym)
        if bench is None or not len(bench):
            log(f"  WARNING: no benchmark data for {title} ({blabel}); panel skipped")
            continue

        pts = []
        for m in members:
            px = closes.get(m["yahoo"])
            if px is None:
                dropped.append((title, m["ticker"], "no price data"))
                continue
            p = rrg_points(px, bench)
            if p is None:
                dropped.append((title, m["ticker"], "insufficient overlap"))
                continue
            hx, hy = p[-1]
            px0, py0 = p[0]
            pts.append({"t": m["ticker"], "n": m["name"][:44], "drs": m["drs"],
                        "x": hx, "y": hy, "q": quadrant(hx, hy),
                        "tail": p, "dx": round(hx - px0, 3), "dy": round(hy - py0, 3)})

        if not pts:
            log(f"  WARNING: {title} produced no plottable points; panel skipped")
            continue
        pts.sort(key=lambda d: d["t"])
        counts = {q: sum(1 for p in pts if p["q"] == q)
                  for q in ("Leading", "Weakening", "Lagging", "Improving")}
        panels.append({"key": key, "title": title, "bench": blabel,
                       "n": len(pts), "thin": len(pts) < THIN,
                       "counts": counts, "pts": pts})
        log(f"  {title:<14} {len(pts):>3} holdings vs {blabel}"
            + ("   [thin]" if len(pts) < THIN else ""))

    if dropped:
        log(f"dropped  : {len(dropped)}")
        for t, k, why in dropped[:25]:
            log(f"  {t:<14} {k:<10} {why}")

    meta = {"generated": time.strftime("%Y-%m-%d %H:%M"),
            "dashboard_generated": data["generated"],
            "trading_date": data["tradingDate"],
            "window": WINDOW, "roc": ROC, "tail": TAIL,
            "universe": sum(p["n"] for p in panels),
            "drs": sum(len(x["drs"]) for p in panels for x in p["pts"])}
    json.dump({"meta": meta, "panels": panels}, open(OUT_DATA, "w", encoding="utf-8"),
              ensure_ascii=False)

    from render_rrg import render
    html = render(meta, panels)
    open(OUT_HTML, "w", encoding="utf-8").write(html)
    log(f"\nwrote {OUT_HTML}  ({len(html):,} bytes)")
    log(f"      {meta['universe']} underlyings across {len(panels)} panels")
    return 0


if __name__ == "__main__":
    sys.exit(main())
