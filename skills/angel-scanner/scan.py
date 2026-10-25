#!/usr/bin/env python3
"""Chart Scanner: scan hundreds of NSE charts for setups.

  scan.py universe [--list nifty500]   # nifty50|nifty100|nifty200|nifty500|all -> universe.json
  scan.py daily [--limit 200]          # pre-market: 20-day closing-high breakout, bull flag,
                                       #   reclaimed 20-day average, oversold, oversold bounce
  scan.py orb [--at 09:45] [--or 15]   # opening-range breakouts on 5-minute bars so far
  scan.py add TCS INFY                 # put symbols on the watchlist by hand
  scan.py show                         # the current watchlist

Liquidity filter: average 20-day traded value >= --min-turnover crore (default 10).
Writes angel-trader/watchlist.json for angel-news and angel-entry. A scan is a list of
charts that match a rule, not a list of stocks to buy.
"""
import argparse
import csv
import datetime as dt
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402


def load_universe(name, refresh=False):
    cur = C.load_json("universe.json")
    today = C.now_ist().date().isoformat()
    if cur and cur.get("list") == name and cur.get("date") == today and not refresh:
        return cur["symbols"]
    fx = C.fixture("universe-" + name)
    if fx is not None:
        syms = fx
    else:
        try:
            raw = C.http(C.NSE_INDEX_LISTS[name], headers={"Referer": "https://www.nseindia.com/"}).decode("utf-8", "replace")
            rows = list(csv.DictReader(io.StringIO(raw)))
            syms = []
            for r in rows:
                r = {k.strip().upper(): (v or "").strip() for k, v in r.items() if k}
                if r.get("SERIES", "EQ") == "EQ" and r.get("SYMBOL"):
                    syms.append(r["SYMBOL"])
        except C.NetError as e:
            print("warning: NSE list unavailable (%s); using Angel One's EQ instruments" % e)
            syms = sorted(s for s, v in C.instruments().items() if v.get("series") == "EQ")
    C.save_json("universe.json", {"list": name, "date": today, "symbols": syms})
    return syms


def daily_setups(bs):
    closes = [b["c"] for b in bs]
    if len(closes) < 30:
        return []
    out = []
    last = closes[-1]
    if last > max(closes[-21:-1]):
        out.append(("breakout20", "closed at a 20-day closing high %.2f (prior high %.2f)" % (last, max(closes[-21:-1]))))
    pole = closes[-6] / closes[-16] - 1 if closes[-16] else 0
    flag = closes[-5:]
    if pole >= 0.10 and (max(flag) - min(flag)) / max(flag) <= 0.05 and last >= 0.97 * max(closes[-20:]):
        out.append(("bullflag", "%.0f%% run in 10 days, then 5 days within %.1f%%" % (
            100 * pole, 100 * (max(flag) - min(flag)) / max(flag))))
    s_now, s_prev = C.sma(closes, 20), C.sma(closes[:-1], 20)
    if s_now and s_prev and closes[-2] < s_prev and last > s_now:
        out.append(("reclaim20", "closed back above the 20-day average %.2f" % s_now))
    r = C.rsi(closes, 14)
    if r is not None and r < 30:
        out.append(("oversold", "RSI(14) %.1f" % r))
    recent = [C.rsi(closes[:i], 14) for i in range(len(closes) - 4, len(closes))]
    if any(x is not None and x < 30 for x in recent) and last > bs[-2]["h"]:
        out.append(("bounce", "was oversold in the last 4 days, closed above yesterday's high %.2f" % bs[-2]["h"]))
    return out


def turnover_cr(bs):
    tail = bs[-20:]
    return sum(b["c"] * b["v"] for b in tail) / len(tail) / 1e7 if tail else 0


def save_watch(kind, items, extra=None):
    doc = {"scan": kind, "created": C.now_ist().isoformat(), "items": items}
    doc.update(extra or {})
    C.save_json("watchlist.json", doc)
    print("-> angel-trader/watchlist.json (%d symbols; next: angel-news, then angel-entry)" % len(items))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("universe")
    p.add_argument("--list", choices=sorted(C.NSE_INDEX_LISTS))
    p.add_argument("--refresh", action="store_true")
    for name in ("daily", "orb"):
        p = sub.add_parser(name)
        p.add_argument("--list", choices=sorted(C.NSE_INDEX_LISTS))
        p.add_argument("--limit", type=int)
        p.add_argument("--min-turnover", type=float, default=10.0, help="crore INR per day")
        p.add_argument("--only", help="comma list of setups to keep (daily)")
        if name == "orb":
            p.add_argument("--at", help="HH:MM IST; default now")
            p.add_argument("--or", dest="or_minutes", type=int, default=15)
    p = sub.add_parser("add")
    p.add_argument("symbols", nargs="+")
    sub.add_parser("show")
    a = ap.parse_args()
    cfg = C.load_config()

    if a.cmd == "show":
        wl = C.load_json("watchlist.json") or {}
        for it in wl.get("items", []):
            print("%-12s %s" % (it["symbol"], "; ".join(it.get("why", []))))
        if not wl.get("items"):
            print("watchlist is empty")
        return
    if a.cmd == "add":
        wl = C.load_json("watchlist.json") or {"scan": "manual", "items": []}
        have = {i["symbol"] for i in wl["items"]}
        for s in a.symbols:
            s = C.clean_symbol(s)
            if s not in have:
                wl["items"].append({"symbol": s, "why": ["added by hand"]})
        C.save_json("watchlist.json", wl)
        print("watchlist: " + ", ".join(i["symbol"] for i in wl["items"]))
        return
    name = a.list or cfg.get("universe", "nifty500")
    syms = load_universe(name, getattr(a, "refresh", False))
    if a.cmd == "universe":
        print("%s: %d symbols -> angel-trader/universe.json" % (name, len(syms)))
        return
    if a.limit:
        syms = syms[: a.limit]
    print("scanning %d %s charts..." % (len(syms), name), file=sys.stderr)
    hits, errors, thin = [], 0, 0
    if a.cmd == "daily":
        keep = set(a.only.split(",")) if a.only else None
        for i, s in enumerate(syms):
            try:
                bs, src = C.bars(s, "1d", days=120, cfg=cfg)
            except (C.NetError, C.AngelError):
                errors += 1
                continue
            if turnover_cr(bs) < a.min_turnover:
                thin += 1
                continue
            found = [x for x in daily_setups(bs) if not keep or x[0] in keep]
            if found:
                hits.append({"symbol": s, "setups": [x[0] for x in found], "why": [x[1] for x in found],
                             "close": bs[-1]["c"], "date": bs[-1]["t"][:10],
                             "turnover_cr": round(turnover_cr(bs), 1), "level": round(max(b["h"] for b in bs[-20:]), 2)})
            if (i + 1) % 50 == 0:
                print("  %d/%d" % (i + 1, len(syms)), file=sys.stderr)
        hits.sort(key=lambda h: (-len(h["setups"]), -h["turnover_cr"]))
        rows = [[h["symbol"], ",".join(h["setups"]), "%.2f" % h["close"], h["turnover_cr"], h["why"][0]] for h in hits]
        print(C.table(rows, ["symbol", "setups", "close", "Rs cr/day", "why"]) if rows else "no setups matched")
        print("\n%d of %d charts matched (%d too thin, %d errors). Data: daily bars to %s." % (
            len(hits), len(syms), thin, errors, hits[0]["date"] if hits else "-"))
        save_watch("daily", hits, {"universe": name})
        return

    now = C.parse_ist(C.now_ist().date().isoformat() + " " + a.at) if a.at else C.now_ist()
    if not C.is_trading_day(now.date(), cfg):
        C.die("NSE is closed on %s" % now.date())
    for i, s in enumerate(syms):
        try:
            bs, src = C.bars(s, "5m", days=1, cfg=cfg, end=now)
        except (C.NetError, C.AngelError):
            errors += 1
            continue
        day = [b for b in C.session(bs, now.date())
               if C.bar_time(b) + dt.timedelta(minutes=5) <= now]
        rng = C.opening_range(day, a.or_minutes)
        if not rng:
            continue
        val = sum(b["c"] * b["v"] for b in day) / 1e7
        after = [b for b in day if C.bar_time(b).strftime("%H:%M") >= rng["end"]]
        first = next((b for b in after if b["c"] > rng["high"]), None)
        if first and val >= a.min_turnover * len(day) / 75.0:
            or_vol = sum(b["v"] for b in day if C.bar_time(b).strftime("%H:%M") < rng["end"]) / max(rng["bars"], 1)
            hits.append({"symbol": s, "setups": ["orb"], "or_high": rng["high"], "or_low": rng["low"],
                         "or_mid": rng["mid"], "first_close_above": first["c"],
                         "first_time": C.bar_time(first).strftime("%H:%M"), "last": day[-1]["c"],
                         "pct_over": round(100 * (day[-1]["c"] / rng["high"] - 1), 2),
                         "rel_vol": round(first["v"] / or_vol, 2) if or_vol else None,
                         "why": ["5-min close %.2f above the %d-min range high %.2f at %s" % (
                             first["c"], a.or_minutes, rng["high"], C.bar_time(first).strftime("%H:%M"))]})
        if (i + 1) % 50 == 0:
            print("  %d/%d" % (i + 1, len(syms)), file=sys.stderr)
    hits.sort(key=lambda h: h["pct_over"])
    rows = [[h["symbol"], "%.2f-%.2f" % (h["or_low"], h["or_high"]), "%.2f" % h["first_close_above"],
             h["first_time"], "%.2f" % h["last"], "%+.2f%%" % h["pct_over"], h["rel_vol"]] for h in hits]
    print(C.table(rows, ["symbol", "range", "first close", "at", "last", "vs high", "rel vol"])
          if rows else "no opening-range breakouts yet")
    print("\n%d of %d charts broke out by %s (%d errors). Closest to the range first: a stock already far "
          "above it has a wider stop." % (len(hits), len(syms), now.strftime("%H:%M"), errors))
    save_watch("orb", hits, {"universe": name, "at": now.strftime("%H:%M")})


if __name__ == "__main__":
    main()
