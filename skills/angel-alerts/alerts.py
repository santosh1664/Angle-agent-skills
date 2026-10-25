#!/usr/bin/env python3
"""Price Alerts: ring when a price, a stop, a target, a time or the opening bell hits.

  alerts.py clock                          # NSE open or closed, next open, holidays ahead
  alerts.py add RELIANCE above 2950
  alerts.py add TCS below 4100
  alerts.py add INFY pct -2                # 2% below yesterday's close (pct 3 = 3% above)
  alerts.py add time 14:55 "close the trade"
  alerts.py add bell                       # 09:15 opening bell (and 09:00 pre-open)
  alerts.py from-plan                      # stop, target and flat-by from plan.json
  alerts.py list | remove ID | clear
  alerts.py check                          # rings what hit, once each; writes prices.json
  alerts.py watch --every 20               # loop check until nothing is left or 15:30

An alert is information only: it never sells anything.
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402


def load():
    return C.load_json("alerts.json", {"next_id": 1, "alerts": []}) or {"next_id": 1, "alerts": []}


def add(doc, **kw):
    kw["id"] = doc["next_id"]
    kw["created"] = C.now_ist().isoformat()
    kw["rung"] = None
    doc["next_id"] += 1
    doc["alerts"].append(kw)
    return kw


def describe(al):
    k = al["kind"]
    if k in ("above", "below"):
        return "%s %s %.2f%s" % (al["symbol"], k, al["level"], (" (%s)" % al["note"]) if al.get("note") else "")
    if k == "pct":
        return "%s moves %+.2f%% from yesterday's close" % (al["symbol"], al["level"])
    if k == "time":
        return "time %s: %s" % (al["at"], al.get("note", ""))
    if k == "bell":
        return "NSE bell %s (%s)" % (al["at"], al.get("note", ""))
    return str(al)


def check(doc, cfg, now):
    live = [a for a in doc["alerts"] if not a["rung"]]
    syms = sorted({a["symbol"] for a in live if a.get("symbol")})
    q = {}
    if syms:
        try:
            q = C.quotes(syms, cfg)
        except (C.NetError, C.AngelError) as e:
            print("warning: no prices (%s)" % e)
        prices = C.load_json("prices.json", {}) or {}
        prices.update(q)
        C.save_json("prices.json", prices)
    rang = []
    tradeday = C.is_trading_day(now.date(), cfg)
    for a in live:
        hit = False
        if a["kind"] in ("above", "below", "pct"):
            s = q.get(a["symbol"]) or {}
            ltp = s.get("ltp")
            if ltp is None:
                continue
            ltp = float(ltp)
            if a["kind"] == "above":
                hit = ltp >= a["level"]
            elif a["kind"] == "below":
                hit = ltp <= a["level"]
            else:
                pc = s.get("prev_close")
                if pc:
                    move = 100 * (ltp - float(pc)) / float(pc)
                    hit = move >= a["level"] if a["level"] > 0 else move <= a["level"]
            if hit:
                a["price"] = ltp
                a["source"] = s.get("source")
        elif a["kind"] in ("time", "bell"):
            hit = tradeday and now.strftime("%H:%M") >= a["at"] and (
                a.get("date") in (None, now.date().isoformat()))
        if hit:
            a["rung"] = now.isoformat()
            rang.append(a)
    for a in rang:
        extra = (" at %.2f (%s)" % (a["price"], a.get("source"))) if "price" in a else ""
        print("RING #%d %s%s" % (a["id"], describe(a), extra))
    return rang


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("clock")
    p = sub.add_parser("add")
    p.add_argument("what", nargs="+")
    sub.add_parser("from-plan")
    sub.add_parser("list")
    p = sub.add_parser("remove")
    p.add_argument("id", type=int)
    sub.add_parser("clear")
    sub.add_parser("check")
    p = sub.add_parser("watch")
    p.add_argument("--every", type=int, default=20)
    a = ap.parse_args()
    cfg = C.load_config()
    now = C.now_ist()
    doc = load()

    if a.cmd == "clock":
        st = C.market_status(now, cfg)
        print("%s IST: NSE %s (%s)" % (now.strftime("%a %Y-%m-%d %H:%M"), st["state"], st["detail"]))
        if st["next_open"]:
            print("next open: %s" % st["next_open"].strftime("%a %Y-%m-%d %H:%M IST"))
        ahead = sorted((d, n) for d, n in C.holidays(cfg).items() if d >= now.date().isoformat())[:4]
        if ahead:
            print("holidays ahead: " + "; ".join("%s %s" % x for x in ahead))
        sp = {d: n for d, n in C.SPECIAL_SESSIONS.items() if d >= now.date().isoformat()}
        for d, n in sp.items():
            print("special session: %s %s" % (d, n))
        print("Angel One squares off equity intraday at 15:15; your flat-by is %s" % cfg["flat_by"])
        return
    if a.cmd == "add":
        w = a.what
        if w[0] == "bell":
            add(doc, kind="bell", at="09:00", note="pre-open order collection")
            add(doc, kind="bell", at="09:15", note="market open")
        elif w[0] == "time":
            add(doc, kind="time", at=w[1], note=" ".join(w[2:]), date=now.date().isoformat())
        elif len(w) >= 3 and w[1] in ("above", "below", "pct", "stop", "target"):
            kind = {"stop": "below", "target": "above"}.get(w[1], w[1])
            add(doc, kind=kind, symbol=C.clean_symbol(w[0]), level=float(w[2]),
                note=w[1] if w[1] in ("stop", "target") else " ".join(w[3:]))
        else:
            C.die("could not read %r; see --help" % " ".join(w))
        C.save_json("alerts.json", doc)
        print("added #%d %s" % (doc["alerts"][-1]["id"], describe(doc["alerts"][-1])))
        return
    if a.cmd == "from-plan":
        pl = C.load_json("plan.json")
        if not pl:
            C.die("no plan.json: run angel-exit first")
        made = [add(doc, kind="below", symbol=pl["symbol"], level=pl["stop"], note="stop"),
                add(doc, kind="above", symbol=pl["symbol"], level=pl["target"], note="target"),
                add(doc, kind="time", at=pl["flat_by"], note="flat by: close %s" % pl["symbol"],
                    date=now.date().isoformat())]
        C.save_json("alerts.json", doc)
        for m in made:
            print("added #%d %s" % (m["id"], describe(m)))
        return
    if a.cmd == "list":
        for al in doc["alerts"]:
            print("#%d %s%s" % (al["id"], describe(al), ("  [rang %s]" % al["rung"][11:16]) if al["rung"] else ""))
        if not doc["alerts"]:
            print("no alerts")
        return
    if a.cmd == "remove":
        doc["alerts"] = [x for x in doc["alerts"] if x["id"] != a.id]
        C.save_json("alerts.json", doc)
        print("removed #%d" % a.id)
        return
    if a.cmd == "clear":
        C.save_json("alerts.json", {"next_id": doc["next_id"], "alerts": []})
        print("cleared")
        return
    if a.cmd == "check":
        r = check(doc, cfg, now)
        C.save_json("alerts.json", doc)
        if not r:
            print("nothing rang (%d waiting)" % sum(1 for x in doc["alerts"] if not x["rung"]))
        return
    while True:
        now = C.now_ist()
        doc = load()
        check(doc, cfg, now)
        C.save_json("alerts.json", doc)
        if not [x for x in doc["alerts"] if not x["rung"]] or now.time() >= C.CLOSE:
            return
        sys.stdout.flush()
        time.sleep(a.every)


if __name__ == "__main__":
    main()
