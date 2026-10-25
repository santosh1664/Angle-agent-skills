#!/usr/bin/env python3
"""Entry Timer: watch a setup bar by bar and call the entry on a CLOSE above the level.

  entry.py check RELIANCE                       # 15-min opening range, 5-min bars
  entry.py check RELIANCE --interval 1m --or 30 # 30-min range, 1-min bars
  entry.py check TCS --setup level --level 4210.5
  entry.py check INFY --vol-mult 1.5            # trigger bar volume >= 1.5x average OR bar
  entry.py watch RELIANCE --every 30            # poll until triggered / expired
  entry.py scan                                 # every symbol in angel-trader/watchlist.json

Writes angel-trader/entry.json on a trigger. Long side only. Never places an order.
"""
import argparse
import datetime as dt
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402


def evaluate(sym, setup="orb", interval="5m", or_minutes=15, level=None, vol_mult=None, cfg=None, now=None):
    cfg = cfg or C.load_config()
    now = now or C.now_ist()
    sym = C.clean_symbol(sym)
    st = C.market_status(now, cfg)
    res = {"symbol": sym, "setup": setup, "interval": interval, "checked": now.isoformat()}
    if not C.is_trading_day(now.date(), cfg):
        res.update(state="not open", detail=st["detail"])
        return res
    if now.time() < C.OPEN:
        res.update(state="not open", detail="market opens 09:15 IST")
        return res
    bs, src = C.bars(sym, interval, days=3, cfg=cfg, end=now)
    res["source"] = src
    day = C.session(bs, now.date())
    step = dt.timedelta(minutes=C.bar_minutes(day) if len(day) > 1 else int(interval.rstrip("m")))
    done = [b for b in day if C.bar_time(b) + step <= now]          # completed bars only
    forming = [b for b in day if C.bar_time(b) + step > now]
    win_end = C.hhmm(cfg["entry_window"][1])
    rng = C.opening_range(done, or_minutes) if setup == "orb" else None
    if setup == "orb":
        if not rng:
            res.update(state="building range",
                       detail="opening range %d min not complete yet (ends %s)" % (
                           or_minutes, (dt.datetime.combine(now.date(), C.OPEN) +
                                        dt.timedelta(minutes=or_minutes)).strftime("%H:%M")))
            return res
        trigger_level = rng["high"]
        res["opening_range"] = rng
        after = [b for b in done if C.bar_time(b).strftime("%H:%M") >= rng["end"]]
        or_bars = [b for b in done if C.bar_time(b).strftime("%H:%M") < rng["end"]]
    else:
        if level is None:
            C.die("--level is required for --setup level")
        trigger_level = float(level)
        after = done
        or_bars = done[:3]
    res["level"] = trigger_level
    avg_vol = (sum(b["v"] for b in or_bars) / len(or_bars)) if or_bars else 0
    for b in after:
        if b["c"] > trigger_level:
            if vol_mult and avg_vol and b["v"] < vol_mult * avg_vol:
                continue
            t = C.bar_time(b)
            if t.time() > win_end:
                break
            res.update(state="triggered", trigger_bar=b, entry_price=b["c"],
                       time=(t + step).strftime("%H:%M"),
                       detail="first %s bar to CLOSE above %.2f: %s bar closed %.2f" % (
                           interval, trigger_level, t.strftime("%H:%M"), b["c"]))
            if setup == "orb" and t.date() == now.date():
                res["opening_range"] = rng
            return res
    if now.time() > win_end:
        res.update(state="expired", detail="no close above %.2f before the entry window ended (%s)" % (
            trigger_level, cfg["entry_window"][1]))
        return res
    last = (forming or done or [{"c": None}])[-1]["c"]
    if last is not None:
        gap = trigger_level - last
        res.update(state="waiting", last=last,
                   detail="last %.2f, needs a %s close above %.2f (%.2f away, %.2f%%)" % (
                       last, interval, trigger_level, gap, 100 * gap / trigger_level))
    else:
        res.update(state="waiting", detail="no bars yet")
    return res


def show(r):
    print("%s  %s  %s" % (r["symbol"], r["state"].upper(), r.get("detail", "")))
    if r.get("opening_range"):
        o = r["opening_range"]
        print("  opening range %s-%s: high %.2f  low %.2f  mid %.2f" % ("09:15", o["end"], o["high"], o["low"], o["mid"]))
    if r.get("source"):
        print("  data: %s" % r["source"])


def save(r):
    if r["state"] == "triggered":
        C.save_json("entry.json", r)
        print("  -> angel-trader/entry.json (next: angel-exit plan)")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("check", "watch"):
        p = sub.add_parser(name)
        p.add_argument("symbol")
        p.add_argument("--setup", choices=["orb", "level"], default="orb")
        p.add_argument("--level", type=float)
        p.add_argument("--interval", choices=["1m", "5m"], default="5m")
        p.add_argument("--or", dest="or_minutes", type=int, default=15)
        p.add_argument("--vol-mult", type=float)
        p.add_argument("--json", action="store_true")
        if name == "watch":
            p.add_argument("--every", type=int, default=30)
            p.add_argument("--max-minutes", type=int, default=240)
    sc = sub.add_parser("scan")
    sc.add_argument("--interval", choices=["1m", "5m"], default="5m")
    sc.add_argument("--or", dest="or_minutes", type=int, default=15)
    a = ap.parse_args()
    cfg = C.load_config()

    if a.cmd == "scan":
        wl = C.load_json("watchlist.json", {}) or {}
        syms = [x["symbol"] for x in wl.get("items", [])] or cfg.get("watchlist", [])
        if not syms:
            C.die("no watchlist: run angel-scanner first or add symbols to config.json watchlist")
        hits = []
        for s in syms:
            try:
                r = evaluate(s, "orb", a.interval, a.or_minutes, cfg=cfg)
            except (C.NetError, C.AngelError) as e:
                print("%s  ERROR  %s" % (s, e))
                continue
            show(r)
            if r["state"] == "triggered":
                hits.append(r)
        if len(hits) == 1:
            save(hits[0])
        elif hits:
            print("\n%d triggered; pick one and run `entry.py check SYMBOL` to write entry.json" % len(hits))
        return

    if a.cmd == "check":
        r = evaluate(a.symbol, a.setup, a.interval, a.or_minutes, a.level, a.vol_mult, cfg)
        C.emit_json(r) if a.json else show(r)
        save(r)
        return

    deadline = time.time() + a.max_minutes * 60
    while True:
        r = evaluate(a.symbol, a.setup, a.interval, a.or_minutes, a.level, a.vol_mult, cfg)
        print(C.now_ist().strftime("%H:%M:%S"), end="  ")
        show(r)
        sys.stdout.flush()
        if r["state"] in ("triggered", "expired") or time.time() > deadline:
            save(r)
            return
        if r["state"] == "not open" and C.now_ist().time() >= C.CLOSE:
            return
        time.sleep(a.every)


if __name__ == "__main__":
    main()
