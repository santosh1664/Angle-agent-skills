#!/usr/bin/env python3
"""Order Executor: paper ledger by default, Angel One SmartAPI when you turn live on.

  ticket.py login [--totp 123456]     # Angel One session (token kept in ~/.angel-one, 0600)
  ticket.py logout
  ticket.py status                    # mode, session, market, today's numbers, funds
  ticket.py show                      # tickets from orders.json: READY / BLOCKED / NOT CHECKED
  ticket.py approve 1 --said "yes, buy 12 RELIANCE"   # record the user's yes, word for word
  ticket.py place 1                   # paper fill (default)
  ticket.py place 1 --live            # real order (needs paper=false AND live_enabled=true)
  ticket.py manage [--watch 30]       # stops, targets, flat-by; places the stop after a live fill
  ticket.py flatten RELIANCE --said "get me out"     # exits are never blocked by day limits
  ticket.py flatten --all --said "flatten everything"
  ticket.py positions | journal | orders
  ticket.py cancel ORDERID --said "cancel it"

Three gates for every entry: angel-risk PASSED this exact order (fingerprint) in the
last 15 minutes, the user's yes was recorded for this exact order in the last 10
minutes, and (live only) both config switches are on and --live is passed.
"""
import argparse
import datetime as dt
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402

APPROVAL_TTL = 10 * 60
RISK_TTL = 15 * 60
API_FIELDS = ("variety", "tradingsymbol", "symboltoken", "transactiontype", "exchange", "ordertype",
              "producttype", "duration", "price", "triggerprice", "squareoff", "stoploss", "quantity")


# ---------------------------------------------------------------- ledger ---

def ledger():
    led = C.load_json("ledger.json", {}) or {}
    led.setdefault("positions", [])
    led.setdefault("closed", [])
    led.setdefault("day_log", {})
    return led


def save_ledger(led):
    C.save_json("ledger.json", led)


def day(led, date):
    return led["day_log"].setdefault(date, {"trades": 0, "realised": 0.0, "fingerprints": []})


def close_position(led, p, price, reason, cfg, when=None):
    when = when or C.now_ist()
    p["exit_price"] = round(price, 2)
    p["exit_reason"] = reason
    p["closed"] = when.isoformat()
    gross = (price - p["entry"]) * p["qty"]
    fees = C.charges("BUY", p["qty"], p["entry"], cfg) + C.charges("SELL", p["qty"], price, cfg)
    p["pnl_gross"] = round(gross, 2)
    p["charges"] = round(fees, 2)
    p["pnl_net"] = round(gross - fees, 2)
    p["r_multiple"] = round((price - p["entry"]) / (p["entry"] - p["stop"]), 2) if p["entry"] > p["stop"] else None
    p["status"] = "closed"
    d = day(led, p["opened"][:10])
    d["realised"] = round(d["realised"] + p["pnl_net"], 2)
    led["positions"] = [x for x in led["positions"] if x["id"] != p["id"]]
    led["closed"].append(p)
    print("CLOSED %s %s x%d: %s at %.2f, net %s (%s R)" % (
        p["mode"], p["symbol"], p["qty"], reason, price, C.inr(p["pnl_net"]), p["r_multiple"]))


# ---------------------------------------------------------------- gates ----

def latest_risk(fp, today):
    log = (C.load_json("risk-log.json", {}) or {}).get(today, [])
    hits = [r for r in log if r.get("fingerprint") == fp]
    return hits[-1] if hits else None


def latest_approval(fp, today):
    ap = (C.load_json("approvals.json", {}) or {}).get(today, [])
    hits = [r for r in ap if r.get("fingerprint") == fp]
    return hits[-1] if hits else None


def age(iso, now):
    return (now - dt.datetime.fromisoformat(iso)).total_seconds()


def ticket_text(o):
    lim = ("LIMIT %s" % o["price"]) if o["ordertype"] == "LIMIT" else "MARKET"
    return ("BUY %s x %s on %s, %s, %s intraday. Stop %.2f (sell stop-loss market), target %.2f, "
            "flat by %s. Max loss at the stop about %s incl. charges; value %s." % (
                o["quantity"], o["tradingsymbol"], o["exchange"], lim, o["producttype"],
                o["stop"], o["target"], o["flat_by"], C.inr(o["max_loss"]), C.inr(o["value"])))


def find_order(n):
    doc = C.load_json("orders.json")
    if not doc:
        C.die("no orders.json: run angel-budget and angel-risk first")
    for o in doc.get("orders", []):
        if str(o.get("n")) == str(n):
            return o
    C.die("no order #%s in orders.json" % n)


# ---------------------------------------------------------------- live -----

def api_ready():
    api = C.SmartAPI()
    try:
        api.ensure()
    except C.AngelError as e:
        C.die(str(e))
    return api


def live_place(api, params):
    body = {k: str(params[k]) for k in API_FIELDS if k in params and params[k] is not None}
    data = api.call("place", body) or {}
    oid = data.get("orderid") if isinstance(data, dict) else data
    if not oid:
        raise C.AngelError("no order id returned: %s" % data)
    return str(oid)


def order_book(api):
    rows = api.call("orderbook") or []
    return {str(r.get("orderid")): r for r in rows}


# ---------------------------------------------------------------- paper ----

def paper_fill_price(side, ltp, cfg):
    slip = cfg.get("slippage_pct", 0.05) / 100.0
    return round(ltp * (1 + slip) if side == "BUY" else ltp * (1 - slip), 2)


def walk_paper(led, p, cfg, now):
    """Replay bars since the last check for one paper position."""
    try:
        bs, _ = C.bars(p["symbol"], "1m" if cfg.get("paper_bars") == "1m" else "5m", days=2, cfg=cfg, end=now)
    except (C.NetError, C.AngelError) as e:
        print("warning: no bars for %s (%s)" % (p["symbol"], e))
        return
    since = p.get("checked_until") or p["opened"]
    step = dt.timedelta(minutes=C.bar_minutes(bs) if len(bs) > 1 else 5)
    new = [b for b in bs if b["t"] >= since[:19] and C.bar_time(b) + step <= now
           and C.bar_time(b).date() == now.date()]
    flat = C.at(now.date(), C.hhmm(p["flat_by"]))
    for b in new:
        t = C.bar_time(b)
        if p["status"] == "pending":
            if b["l"] <= p["limit"]:
                p["entry"] = round(min(p["limit"], b["o"]), 2)
                p["status"] = "open"
                p["filled"] = t.isoformat()
                print("FILLED paper %s x%d at %.2f (%s bar)" % (p["symbol"], p["qty"], p["entry"], t.strftime("%H:%M")))
            elif t.strftime("%H:%M") >= cfg["entry_window"][1]:
                p["status"] = "cancelled"
                led["positions"] = [x for x in led["positions"] if x["id"] != p["id"]]
                print("CANCELLED paper %s: limit %.2f never filled in the entry window" % (p["symbol"], p["limit"]))
                return
            continue
        if t >= flat:
            close_position(led, p, paper_fill_price("SELL", b["o"], cfg), "flat-by %s" % p["flat_by"], cfg, t)
            return
        if b["l"] <= p["stop"]:
            px = min(b["o"], p["stop"])          # a gap through the stop fills worse
            close_position(led, p, paper_fill_price("SELL", px, cfg), "stop", cfg, t)
            return
        if b["h"] >= p["target"]:
            close_position(led, p, max(b["o"], p["target"]), "target", cfg, t)
            return
        p["checked_until"] = (t + step).isoformat()
    if p["status"] == "open" and now >= flat:
        q = C.quotes([p["symbol"]], cfg).get(p["symbol"]) or {}
        if q.get("ltp"):
            close_position(led, p, paper_fill_price("SELL", float(q["ltp"]), cfg), "flat-by %s" % p["flat_by"], cfg, now)


# ---------------------------------------------------------------- commands -

def cmd_place(a, cfg):
    now = C.now_ist()
    today = now.date().isoformat()
    o = find_order(a.n)
    fp = o["fingerprint"]
    if C.fingerprint(o) != fp:
        C.die("order #%s was edited after sizing (fingerprint mismatch): re-run angel-budget" % a.n)
    r = latest_risk(fp, today)
    if not r or r["verdict"] != "PASS":
        C.die("angel-risk has not PASSED this exact order today%s" % (
            (": " + "; ".join(r["reasons"])) if r and r.get("reasons") else ""))
    if age(r["time"], now) > RISK_TTL:
        C.die("the risk check is %d min old: run angel-risk again" % (age(r["time"], now) // 60))
    ap = latest_approval(fp, today)
    if not ap:
        C.die("no recorded yes for this exact order: show the ticket, get the user's yes, then `approve`")
    if age(ap["time"], now) > APPROVAL_TTL:
        C.die("the yes is %d min old: show the ticket again and ask again" % (age(ap["time"], now) // 60))
    led = ledger()
    if fp in day(led, today)["fingerprints"]:
        C.die("this exact order was already placed today")
    live = bool(a.live)
    if live and (cfg.get("paper", True) or not cfg.get("live_enabled", False)):
        C.die("live is off: config.json needs \"paper\": false AND \"live_enabled\": true (the user sets these)")
    if not live and not cfg.get("paper", True):
        C.die("config says live but --live was not passed: refusing to guess. Pass --live, or set paper=true")
    qty = int(o["quantity"])
    pos = {"id": "%s-%s-%d" % (today, o["symbol"], len(led["closed"]) + len(led["positions"]) + 1),
           "mode": "live" if live else "paper", "symbol": o["symbol"], "tradingsymbol": o["tradingsymbol"],
           "token": o.get("symboltoken"), "qty": qty, "stop": o["stop"], "target": o["target"],
           "flat_by": o["flat_by"], "opened": now.isoformat(), "fingerprint": fp, "orders": {},
           "approval": ap["said"], "limit": float(o["price"]) if o["ordertype"] == "LIMIT" else None,
           "entry": o["worst_entry"]}
    if live:
        api = api_ready()
        try:
            oid = live_place(api, o)
        except (C.AngelError, C.NetError) as e:
            C.die("Angel One rejected the order: %s" % e)
        pos["orders"]["entry"] = oid
        pos["status"] = "pending"
        print("SENT live BUY %d %s, Angel One order id %s." % (qty, o["tradingsymbol"], oid))
        print("Run `ticket.py manage` now: it confirms the fill and places the protective stop-loss.")
    else:
        q = C.quotes([o["symbol"]], cfg).get(o["symbol"]) or {}
        ltp = q.get("ltp")
        if ltp is None:
            C.die("no price for %s to fill the paper order" % o["symbol"])
        ltp = float(ltp)
        if o["ordertype"] == "MARKET":
            pos["entry"] = paper_fill_price("BUY", ltp, cfg)
            pos["status"] = "open"
        elif ltp <= pos["limit"]:
            pos["entry"] = round(ltp, 2)
            pos["status"] = "open"
        else:
            pos["status"] = "pending"
        if pos["status"] == "open":
            pos["filled"] = now.isoformat()
            print("PAPER FILL: bought %d %s at %.2f (price %.2f, %s). Stop %.2f, target %.2f, flat by %s." % (
                qty, o["symbol"], pos["entry"], ltp, q.get("source"), pos["stop"], pos["target"], pos["flat_by"]))
        else:
            print("PAPER: limit %.2f resting (price %.2f). `manage` fills it if the price comes back." % (
                pos["limit"], ltp))
    pos["checked_until"] = now.isoformat()
    led["positions"].append(pos)
    d = day(led, today)
    d["trades"] += 1
    d["fingerprints"].append(fp)
    save_ledger(led)


def cmd_manage(a, cfg):
    while True:
        now = C.now_ist()
        led = ledger()
        live_pos = [p for p in led["positions"] if p["mode"] == "live"]
        api = api_ready() if live_pos else None
        book = order_book(api) if live_pos else {}
        for p in list(led["positions"]):
            if p["mode"] == "paper":
                walk_paper(led, p, cfg, now)
                continue
            manage_live(led, p, cfg, now, api, book)
        save_ledger(led)
        opn = [p for p in led["positions"] if p["status"] in ("open", "pending")]
        for p in opn:
            print("%s %s %s x%d entry %.2f stop %.2f target %.2f flat by %s" % (
                p["mode"], p["status"], p["symbol"], p["qty"], p["entry"], p["stop"], p["target"], p["flat_by"]))
        if not opn:
            print("no open positions")
        if not a.watch or not opn or now.time() >= C.CLOSE:
            return
        time.sleep(a.watch)


def manage_live(led, p, cfg, now, api, book):
    ent = book.get(p["orders"].get("entry", ""), {})
    st = (ent.get("orderstatus") or ent.get("status") or "").lower()
    if p["status"] == "pending":
        if st == "complete":
            p["entry"] = float(ent.get("averageprice") or p["entry"])
            p["status"] = "open"
            p["filled"] = now.isoformat()
            print("FILLED live %s x%d at %.2f" % (p["symbol"], p["qty"], p["entry"]))
        elif st in ("rejected", "cancelled"):
            print("ENTRY %s %s: %s" % (st.upper(), p["symbol"], ent.get("text", "")))
            p["status"] = st
            led["positions"] = [x for x in led["positions"] if x["id"] != p["id"]]
            return
        else:
            if now.strftime("%H:%M") > cfg["entry_window"][1]:
                try:
                    api.call("cancel", {"variety": "NORMAL", "orderid": p["orders"]["entry"]})
                    print("CANCELLED unfilled live entry %s (entry window over)" % p["symbol"])
                except C.AngelError as e:
                    print("could not cancel entry: %s" % e)
            return
    base = {"variety": "STOPLOSS", "tradingsymbol": p["tradingsymbol"], "symboltoken": p["token"],
            "transactiontype": "SELL", "exchange": cfg.get("exchange", "NSE"), "producttype": "INTRADAY",
            "duration": "DAY", "quantity": p["qty"], "squareoff": "0", "stoploss": "0"}
    if not p["orders"].get("stop"):
        params = dict(base, ordertype="STOPLOSS_MARKET", triggerprice="%.2f" % p["stop"], price="0")
        try:
            p["orders"]["stop"] = live_place(api, params)
            print("STOP-LOSS placed at Angel One: SL-M sell %d %s trigger %.2f (id %s)" % (
                p["qty"], p["symbol"], p["stop"], p["orders"]["stop"]))
        except (C.AngelError, C.NetError) as e:
            print("!! COULD NOT PLACE THE STOP: %s. Place it by hand in the Angel One app NOW." % e)
    if cfg.get("target_at_broker") and not p["orders"].get("target"):
        params = dict(base, variety="NORMAL", ordertype="LIMIT", price="%.2f" % p["target"], triggerprice="0")
        try:
            p["orders"]["target"] = live_place(api, params)
            print("TARGET placed at Angel One: LIMIT sell at %.2f (id %s). If the stop fills first, "
                  "`manage` must run to cancel this, or it becomes a short." % (p["target"], p["orders"]["target"]))
        except (C.AngelError, C.NetError) as e:
            print("could not place target: %s" % e)
    so = book.get(p["orders"].get("stop", ""), {})
    to = book.get(p["orders"].get("target", ""), {})
    if (so.get("orderstatus") or "").lower() == "complete":
        cancel_quiet(api, p["orders"].get("target"))
        close_position(led, p, float(so.get("averageprice") or p["stop"]), "stop", cfg, now)
        return
    if (to.get("orderstatus") or "").lower() == "complete":
        cancel_quiet(api, p["orders"].get("stop"), "STOPLOSS")
        close_position(led, p, float(to.get("averageprice") or p["target"]), "target", cfg, now)
        return
    q = C.quotes([p["symbol"]], cfg).get(p["symbol"]) or {}
    ltp = float(q.get("ltp") or 0)
    flat = now.strftime("%H:%M") >= p["flat_by"]
    hit_target = ltp and ltp >= p["target"] and not cfg.get("target_at_broker")
    if flat or hit_target:
        exit_live(led, p, cfg, now, api, "flat-by %s" % p["flat_by"] if flat else "target", ltp)


def cancel_quiet(api, oid, variety="NORMAL"):
    if not oid:
        return
    try:
        api.call("cancel", {"variety": variety, "orderid": oid})
    except (C.AngelError, C.NetError):
        pass


def exit_live(led, p, cfg, now, api, reason, ltp):
    cancel_quiet(api, p["orders"].get("stop"), "STOPLOSS")
    cancel_quiet(api, p["orders"].get("target"))
    params = {"variety": "NORMAL", "tradingsymbol": p["tradingsymbol"], "symboltoken": p["token"],
              "transactiontype": "SELL", "exchange": cfg.get("exchange", "NSE"), "ordertype": "MARKET",
              "producttype": "INTRADAY", "duration": "DAY", "price": "0", "triggerprice": "0",
              "quantity": p["qty"], "squareoff": "0", "stoploss": "0"}
    try:
        p["orders"]["exit"] = live_place(api, params)
    except (C.AngelError, C.NetError) as e:
        print("!! EXIT FAILED for %s: %s. Close it by hand in the Angel One app NOW." % (p["symbol"], e))
        return
    time.sleep(1.2)
    fill = order_book(api).get(p["orders"]["exit"], {})
    px = float(fill.get("averageprice") or ltp or p["entry"])
    close_position(led, p, px, reason, cfg, now)


def cmd_flatten(a, cfg):
    if not a.said:
        C.die("record the user's words: --said \"...\"")
    now = C.now_ist()
    led = ledger()
    targets = [p for p in led["positions"] if a.all or (a.symbol and p["symbol"] == C.clean_symbol(a.symbol))]
    if not targets:
        C.die("no matching open position")
    live = [p for p in targets if p["mode"] == "live"]
    api = api_ready() if live else None
    for p in targets:
        p["flatten_said"] = a.said
        if p["status"] == "pending":
            if p["mode"] == "live":
                cancel_quiet(api, p["orders"].get("entry"))
            led["positions"] = [x for x in led["positions"] if x["id"] != p["id"]]
            print("CANCELLED unfilled %s %s" % (p["mode"], p["symbol"]))
            continue
        q = C.quotes([p["symbol"]], cfg).get(p["symbol"]) or {}
        ltp = float(q.get("ltp") or p["entry"])
        if p["mode"] == "paper":
            close_position(led, p, paper_fill_price("SELL", ltp, cfg), "flattened by you", cfg, now)
        else:
            exit_live(led, p, cfg, now, api, "flattened by you", ltp)
    save_ledger(led)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("login")
    p.add_argument("--totp")
    sub.add_parser("logout")
    sub.add_parser("status")
    sub.add_parser("show")
    p = sub.add_parser("approve")
    p.add_argument("n")
    p.add_argument("--said", required=True)
    p = sub.add_parser("place")
    p.add_argument("n")
    p.add_argument("--live", action="store_true")
    p = sub.add_parser("manage")
    p.add_argument("--watch", type=int, default=0)
    p = sub.add_parser("flatten")
    p.add_argument("symbol", nargs="?")
    p.add_argument("--all", action="store_true")
    p.add_argument("--said")
    sub.add_parser("positions")
    sub.add_parser("journal")
    sub.add_parser("orders")
    p = sub.add_parser("cancel")
    p.add_argument("orderid")
    p.add_argument("--variety", default="NORMAL")
    p.add_argument("--said", required=True)
    a = ap.parse_args()
    cfg = C.load_config()
    now = C.now_ist()
    today = now.date().isoformat()

    if a.cmd == "login":
        api = C.SmartAPI()
        try:
            s = api.login(a.totp)
        except (C.AngelError, C.NetError) as e:
            C.die(str(e))
        print("logged in to Angel One as %s; session valid until %s IST" % (s["client_code"], s["expires"]))
    elif a.cmd == "logout":
        C.SmartAPI().logout()
        print("logged out; session file removed")
    elif a.cmd == "status":
        api = C.SmartAPI()
        st = C.market_status(now, cfg)
        mode = "PAPER" if cfg.get("paper", True) else ("LIVE" if cfg.get("live_enabled") else "LIVE (locked: live_enabled=false)")
        print("mode %s | NSE %s (%s) | %s IST" % (mode, st["state"], st["detail"], now.strftime("%Y-%m-%d %H:%M")))
        print("Angel One: %s" % ("logged in until %s" % api.session["expires"] if api.logged_in() else
                                 "not logged in" + ("" if api.configured() else " (credentials not set)")))
        print("data: %s" % ("Angel One real time" if api.logged_in() and cfg.get("data_source") != "yahoo"
                            else "Yahoo Finance, delayed ~15 min"))
        d = ledger()["day_log"].get(today, {})
        print("today: %d trades, realised %s" % (d.get("trades", 0), C.inr(d.get("realised", 0))))
        if api.logged_in():
            try:
                r = api.call("rms") or {}
                print("funds: available cash %s, net %s" % (C.inr(float(r.get("availablecash") or 0)),
                                                             C.inr(float(r.get("net") or 0))))
            except (C.AngelError, C.NetError) as e:
                print("funds: unavailable (%s)" % e)
    elif a.cmd == "show":
        doc = C.load_json("orders.json") or {}
        for o in doc.get("orders", []):
            r = latest_risk(o["fingerprint"], today)
            state = "NOT CHECKED" if not r else ("READY" if r["verdict"] == "PASS" else "BLOCKED")
            print("#%s [%s] %s" % (o["n"], state, ticket_text(o)))
            if r and r["verdict"] != "PASS":
                for x in r["reasons"]:
                    print("    - " + x)
            print("    mode: %s" % ("PAPER (simulated fill)" if cfg.get("paper", True) else "LIVE (real money)"))
        if not doc.get("orders"):
            print("no orders: run angel-budget")
    elif a.cmd == "approve":
        o = find_order(a.n)
        if not re.search(r"\b(yes|confirm(ed)?|go ahead|place it)\b", a.said, re.I) or \
                re.search(r"\b(no|don'?t|do not|wait|cancel)\b", a.said, re.I):
            C.die("that is not a yes; nothing recorded")
        log = C.load_json("approvals.json", {}) or {}
        log.setdefault(today, []).append({"n": o["n"], "fingerprint": o["fingerprint"], "said": a.said,
                                          "ticket": ticket_text(o), "time": now.isoformat()})
        C.save_json("approvals.json", log)
        print("recorded the yes for #%s (%s); valid 10 minutes" % (o["n"], o["fingerprint"]))
    elif a.cmd == "place":
        cmd_place(a, cfg)
    elif a.cmd == "manage":
        cmd_manage(a, cfg)
    elif a.cmd == "flatten":
        cmd_flatten(a, cfg)
    elif a.cmd == "positions":
        led = ledger()
        rows = [[p["mode"], p["status"], p["symbol"], p["qty"], "%.2f" % p["entry"], "%.2f" % p["stop"],
                 "%.2f" % p["target"], p["flat_by"]] for p in led["positions"]]
        print(C.table(rows, ["mode", "status", "symbol", "qty", "entry", "stop", "target", "flat by"])
              if rows else "no open positions")
    elif a.cmd == "journal":
        led = ledger()
        rows, tot = [], 0.0
        for p in led["closed"]:
            if p.get("status") != "closed":
                continue
            tot += p["pnl_net"]
            rows.append([p["opened"][:10], p["mode"], p["symbol"], p["qty"], "%.2f" % p["entry"],
                         "%.2f" % p["exit_price"], p["exit_reason"], C.inr(p["pnl_gross"]), C.inr(p["charges"]),
                         C.inr(p["pnl_net"]), p.get("r_multiple")])
        if not rows:
            print("no closed trades yet")
            return
        print(C.table(rows, ["date", "mode", "symbol", "qty", "entry", "exit", "why", "gross", "charges", "net", "R"]))
        wins = sum(1 for p in led["closed"] if p.get("pnl_net", 0) > 0)
        print("\n%d trades, %d winners, net %s after estimated charges" % (len(rows), wins, C.inr(tot)))
    elif a.cmd == "orders":
        api = api_ready()
        for oid, r in order_book(api).items():
            print("%s %s %s %s x%s %s @%s trig %s: %s %s" % (
                oid, r.get("updatetime", ""), r.get("transactiontype"), r.get("tradingsymbol"), r.get("quantity"),
                r.get("ordertype"), r.get("price"), r.get("triggerprice"), r.get("orderstatus"), r.get("text", "")))
    elif a.cmd == "cancel":
        api = api_ready()
        try:
            api.call("cancel", {"variety": a.variety, "orderid": a.orderid})
            print("cancel sent for %s" % a.orderid)
        except C.AngelError as e:
            C.die(str(e))


if __name__ == "__main__":
    main()
