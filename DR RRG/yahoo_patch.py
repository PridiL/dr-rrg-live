"""Fill a benchmark index's missing latest session from Yahoo's quote.

Found 2026-10-27, when the DR RRG went daily: at 08:24 Bangkok, Yahoo's DAILY
history for ^HSI, ^N225, ^STOXX and ^STI had no bar for Monday 10-26 -- some even
showed Tuesday's live bar but skipped Monday -- while every stock in those markets
had Monday. Each stock is scored against its index on shared dates, so one missing
index bar silently held a whole market (both sections of the page) a day behind.

Yahoo did have Monday elsewhere:
  - the hourly series, complete, but its last price is not the official close
    (median 0.05-0.09% off, up to 0.4% on the Nikkei, whose closing auction moves it);
  - the quote, which carries the official close: regularMarketPrice for a market
    that has not reopened since, regularMarketPreviousClose for one trading today.
So the hourly series says WHICH sessions exist and the quote supplies the VALUE.

Rules, deliberately narrow:
  - only the most recent FINISHED session (dated before today, Bangkok) is
    considered, and only if the daily series lacks it -- never overwrites a bar;
  - only for the handful of benchmark indices (stocks did not show the gap, and
    one quote call per stock would cost ~300 slow requests);
  - nothing is written to disk: the next run refetches, and once Yahoo's daily bar
    appears it is used instead.
"""
from __future__ import annotations

import datetime as dt
import warnings
import zoneinfo

import pandas as pd

warnings.filterwarnings("ignore")


def _last_finished_session(ticker, today: dt.date):
    """(session date, hourly last price) of the newest hourly session before today."""
    import yfinance as yf
    h = yf.Ticker(ticker).history(period="10d", interval="60m", auto_adjust=True)
    if h.empty:
        return None, None
    by_day = h["Close"].groupby(h.index.date).last()
    done = by_day[[d < today for d in by_day.index]]
    if done.empty:
        return None, None
    return done.index[-1], float(done.iloc[-1])


def _official_close(ticker, session: dt.date):
    """Official close of `session` from the quote, or None if the quote can't vouch for it."""
    import yfinance as yf
    i = yf.Ticker(ticker).info
    tz, t = i.get("exchangeTimezoneName"), i.get("regularMarketTime")
    if not tz or not t:
        return None
    quoted = dt.datetime.fromtimestamp(t, zoneinfo.ZoneInfo(tz)).date()
    if quoted == session and i.get("regularMarketPrice"):
        return float(i["regularMarketPrice"]), "regularMarketPrice"
    if quoted > session and i.get("regularMarketPreviousClose"):
        # The market has traded since, so "previous close" is that of the session
        # before today -- `session`, which is the newest finished one by construction.
        return float(i["regularMarketPreviousClose"]), "regularMarketPreviousClose"
    return None


def fill_missing_last_session(closes: dict, tickers, log=print, today: dt.date | None = None) -> dict:
    """For each ticker in `tickers`, append its newest finished session if the daily
    series in `closes` lacks it. Returns {ticker: (date, value, source)} of what it filled."""
    today = today or dt.date.today()
    filled = {}
    for tk in tickers:
        s = closes.get(tk)
        if s is None or not len(s):
            continue
        try:
            session, hourly = _last_finished_session(tk, today)
            # Compare with FINISHED daily bars only: a market trading right now already
            # has today's live bar in the daily series (dropped later by the builders),
            # and testing against that skipped the Nikkei and STI on 2026-10-27.
            done = [d for d in s.index if d < today]
            if session is None or session in s.index or (done and session <= done[-1]):
                continue
            got = _official_close(tk, session)
            value, source = got if got else (hourly, "hourly last (quote unavailable)")
            closes[tk] = pd.concat([s, pd.Series([value], index=[session])]).sort_index()
            filled[tk] = (session, value, source)
            log(f"  patched {tk}: Yahoo daily lacks {session}; using {value:,.2f} from {source}")
        except Exception as e:          # a patch must never break the build
            log(f"  NOTE: could not check {tk} for a missing session ({type(e).__name__}: {e})")
    return filled
