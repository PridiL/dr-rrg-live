"""After a build, check every market reached the previous trading day.

User rule (2026-10-27): a run on day T uses the closing prices of the previous
trading day -- T-1, or Friday when T is a Monday. The builders already pick that
day (they drop anything dated today, Bangkok), but nothing checked that each
market actually GOT it. On 2026-10-27 five benchmark indices lacked Monday on
Yahoo at 07:30 and the dashboard quietly showed Friday for them.

For every market, in both sections of the page (countries graph, stocks section):
  - on the expected day                 -> ok
  - behind, and the market did not trade on the missing day(s)
    (no hourly bars on Yahoo)           -> holiday, fine (Taiwan 10-23/10-26)
  - behind, but the market DID trade    -> GAP: printed as a WARNING
MSCI World is reported too: the countries graph cannot be newer than it.

VN-Index comes from VNDirect, not Yahoo, so a Vietnam delay is reported as
"behind - holiday or gap, cannot tell" rather than guessed at.

Exit 0 = every market on the expected day or on a holiday; 4 = at least one gap.
Reads the data files only; changes nothing.

    python check_sessions.py
"""
import datetime as dt
import json
import os
import sys
import warnings

warnings.filterwarnings("ignore")
ROOT = os.path.dirname(os.path.abspath(__file__))


def expected_session(today: dt.date) -> dt.date:
    d = today - dt.timedelta(days=1)
    while d.weekday() >= 5:          # Saturday / Sunday
        d -= dt.timedelta(days=1)
    return d


def traded_between(ticker: str, after: dt.date, upto: dt.date):
    """Sessions Yahoo's hourly data shows in (after, upto]; None if it can't be checked."""
    try:
        import yfinance as yf
        h = yf.Ticker(ticker).history(period="1mo", interval="60m")
        if h.empty:
            return None
        return sorted({d for d in h.index.date if after < d <= upto})
    except Exception:
        return None


def main() -> int:
    today = dt.date.today()
    want = expected_session(today)
    country = json.load(open(os.path.join(ROOT, "country_rrg_data.json"), encoding="utf-8"))
    table = json.load(open(os.path.join(ROOT, "rrg_table_data.json"), encoding="utf-8"))

    sys.path.insert(0, ROOT)
    from build_country_rrg import COUNTRIES
    from build_rrg_table import GROUPS
    ticker = {c[0]: c[4] for c in COUNTRIES} | {g[0]: g[4] for g in GROUPS}
    name = {c[0]: c[1] for c in COUNTRIES} | {g[0]: g[1] for g in GROUPS}

    world = dt.date.fromisoformat(country["meta"]["world_last"])
    print(f"session check: run {today} -> expected previous trading day {want}")
    print(f"  MSCI World: {world}" + ("" if world >= want else
          "  (behind: the countries graph cannot be newer than this)"))

    # (section, market key, date the page shows for it)
    shown = [("countries", r["key"], dt.date.fromisoformat(r["last"])) for r in country["rows"]]
    shown += [("stocks", g["key"], dt.date.fromisoformat(g["asof"])) for g in table["groups"]]

    gaps, cache = 0, {}
    for section, key, d in shown:
        label = f"{name.get(key, key)} [{section}]"
        if d >= want:
            print(f"  ok       {label:42} {d}")
            continue
        # A countries row is capped by MSCI World; that is reported above, not here.
        if section == "countries" and d == world and world < want:
            print(f"  MSCI     {label:42} {d}  (held back by MSCI World)")
            continue
        tk = ticker.get(key)
        if tk == "VNINDEX":
            print(f"  behind   {label:42} {d}  holiday or gap - cannot tell (VNDirect source)")
            continue
        if tk not in cache:
            cache[tk] = traded_between(tk, d, want)
        missed = cache[tk]
        if missed is None:
            print(f"  behind   {label:42} {d}  could not check Yahoo hourly data for {tk}")
        elif not missed:
            print(f"  holiday  {label:42} {d}  {tk} did not trade after {d} (market closed)")
        else:
            gaps += 1
            print(f"  WARNING  {label:42} {d}  GAP: {tk} traded on {', '.join(map(str, missed))} "
                  f"but the dashboard did not get it")
    print(f"session check: {'OK' if not gaps else f'{gaps} GAP(S) - see WARNING lines'}")
    return 4 if gaps else 0


if __name__ == "__main__":
    sys.exit(main())
