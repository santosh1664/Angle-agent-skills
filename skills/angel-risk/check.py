#!/usr/bin/env python3
"""Risk Manager: PASS or BLOCK every order before it can reach the broker.

  check.py                       # angel-trader/orders.json
  check.py path/to/orders.json
  check.py --no-quote            # skip the fresh-price check (offline)
  check.py today                 # today's trades, risk used, limits left

Verdicts are written to angel-trader/risk-log.json by order fingerprint;
angel-broker only places an order whose exact fingerprint PASSED today.
Exits (role "exit") are never blocked by day limits.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402


def day_state(cfg, today):
    led = C.load_json("ledger.json", {}) or {}
    log = (led.get("day_log") or {}).get(today, {})
    open_pos = [p for p in led.get("positions", []) if p.get("status") == "open"]
    open_risk = sum(max(p["entry"] - p["stop"], 0) * p["qty"] for p in open_pos)
    return {"trades": log.get("trades", 0), "realised": log.get("realised", 0.0),
            "open_risk": round(open_risk, 2), "open_symbols": [p["symbol"] for p in open_pos],
            "exposure": sum(p["qty"] * p["entry"] for p in open_pos),
            "placed": log.get("fingerprints", [])}


def check(o, cfg, now, quote=None, inst=None):
    reasons, notes = [], []
    today = now.date().isoformat()
    role = o.get("role", "entry")
    ds = day_state(cfg, today)
    sym = o.get("symbol") or C.clean_symbol(o.get("tradingsymbol", ""))
    try:
        qty = int(str(o.get("quantity")))
    except ValueError:
        qty = 0
    if qty <= 0:
        reasons.append("quantity must be a whole number above 0")
    if o.get("exchange") not in ("NSE", "BSE"):
        reasons.append("exchange %s: only NSE/BSE cash equity is allowed" % o.get("exchange"))
    if o.get("producttype") not in ("INTRADAY", "DELIVERY"):
        reasons.append("product %s is not allowed (INTRADAY or DELIVERY only; no MTF/F&O)" % o.get("producttype"))
    if not cfg.get("allow_fno") and not str(o.get("tradingsymbol", "")).endswith(("-EQ", "-BE", "-BZ")):
        reasons.append("%s is not a cash-equity symbol" % o.get("tradingsymbol"))
    if sym in [b.upper() for b in cfg.get("blocked", [])]:
        reasons.append("%s is on your blocked list" % sym)
    if inst and inst.get("series") != "EQ" and o.get("producttype") == "INTRADAY":
        reasons.append("%s trades in the %s series (trade-to-trade): no intraday allowed" % (sym, inst.get("series")))
    if role == "exit":
        if o.get("transactiontype") != "SELL":
            reasons.append("an exit must be a SELL")
        if sym not in ds["open_symbols"]:
            notes.append("no open %s position in the ledger" % sym)
        return ("BLOCK" if reasons else "PASS"), reasons, notes

    if o.get("transactiontype") != "BUY" and not cfg.get("allow_short"):
        reasons.append("short selling is off (allow_short=false)")
    stop, target = o.get("stop"), o.get("target")
    price = float(o.get("price") or 0) or float(o.get("worst_entry") or o.get("plan_entry") or 0)
    ltp = (quote or {}).get("ltp")
    if o.get("ordertype") == "LIMIT" and float(o.get("price") or 0) > 0:
        ref = float(o["price"])            # a buy limit never fills above its price
        if ltp and float(ltp) > ref:
            notes.append("price %.2f is above your limit %.2f: the order may not fill" % (ltp, ref))
    else:
        ref = max(price, float(ltp or 0))  # market order: the worse of plan and fresh price
    if ltp:
        notes.append("fresh price %.2f (%s)" % (ltp, quote.get("source")))
    if stop is None:
        reasons.append("no stop: every trade needs one")
    elif stop >= ref:
        reasons.append("stop %.2f is not below the price %.2f" % (stop, ref))
    else:
        fees = C.charges("BUY", qty, ref, cfg) + C.charges("SELL", qty, stop, cfg)
        loss = qty * (ref - stop) + fees
        if loss > cfg["max_loss_per_trade"] + 0.005:
            reasons.append("loss at the stop %s (from %.2f, incl. charges) is over your max %s" % (
                C.inr(loss), ref, C.inr(cfg["max_loss_per_trade"])))
        if target is None or target <= ref:
            reasons.append("target must be above the entry")
        else:
            rr = (target - ref) / (ref - stop)
            if rr + 1e-9 < cfg["min_reward_risk"]:
                reasons.append("reward:risk %.2f is under your minimum %.2f" % (rr, cfg["min_reward_risk"]))
        used = ds["open_risk"] + max(-ds["realised"], 0)
        if used + loss > cfg["daily_loss_limit"] + 0.005:
            reasons.append("day risk would be %s (open %s + losses %s + this %s) > daily limit %s" % (
                C.inr(used + loss), C.inr(ds["open_risk"]), C.inr(max(-ds["realised"], 0)),
                C.inr(loss), C.inr(cfg["daily_loss_limit"])))
    if ds["trades"] >= cfg["max_trades_per_day"]:
        reasons.append("already %d trades today (max %d)" % (ds["trades"], cfg["max_trades_per_day"]))
    st = C.market_status(now, cfg)
    if st["state"] != "open":
        reasons.append("market is %s (%s)" % (st["state"], st["detail"]))
    else:
        w0, w1 = cfg["entry_window"]
        t = now.strftime("%H:%M")
        if not (w0 <= t <= w1):
            reasons.append("%s is outside your entry window %s-%s" % (t, w0, w1))
        if t >= o.get("flat_by", cfg["flat_by"]):
            reasons.append("past the flat-by time %s" % o.get("flat_by", cfg["flat_by"]))
    if str(o.get("flat_by", "")) > "15:10":
        reasons.append("flat-by %s is after 15:10 (Angel One squares off at 15:15)" % o.get("flat_by"))
    value = qty * ref
    if value > cfg["max_order_value"] + 0.005:
        reasons.append("order value %s > max order %s" % (C.inr(value), C.inr(cfg["max_order_value"])))
    lev = max(1.0, float(cfg.get("mis_leverage", 1)))
    cap_pos = cfg["capital"] * cfg["max_position_pct"] / 100.0 * lev
    if value > cap_pos + 0.005:
        reasons.append("position %s > position cap %s" % (C.inr(value), C.inr(cap_pos)))
    room = cfg["capital"] * (1 - cfg["cash_buffer_pct"] / 100.0) * lev - ds["exposure"]
    if value > room + 0.005:
        reasons.append("needs %s but only %s is free after your %d%% cash buffer" % (
            C.inr(value), C.inr(max(room, 0)), cfg["cash_buffer_pct"]))
    if sym in ds["open_symbols"]:
        reasons.append("already holding %s today" % sym)
    if o.get("fingerprint") in ds["placed"]:
        reasons.append("this exact order was already placed today")
    if quote:
        uc, lc = quote.get("upper_circuit"), quote.get("lower_circuit")
        if uc and ref >= float(uc) * 0.99:
            reasons.append("price is within 1%% of the upper circuit %.2f: you may not be able to buy, "
                           "or get out" % float(uc))
        if lc and stop is not None and stop <= float(lc):
            reasons.append("stop %.2f is at/below the lower circuit %.2f: it may never fill" % (stop, float(lc)))
    return ("BLOCK" if reasons else "PASS"), reasons, notes


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("target", nargs="?", default="orders.json")
    ap.add_argument("--no-quote", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    cfg = C.load_config()
    now = C.now_ist()
    today = now.date().isoformat()
    if a.target == "today":
        ds = day_state(cfg, today)
        used = ds["open_risk"] + max(-ds["realised"], 0)
        print("today %s: %d of %d trades, realised %s, open risk %s" % (
            today, ds["trades"], cfg["max_trades_per_day"], C.inr(ds["realised"]), C.inr(ds["open_risk"])))
        print("daily loss limit %s, room left %s" % (C.inr(cfg["daily_loss_limit"]),
                                                    C.inr(cfg["daily_loss_limit"] - used)))
        return
    doc = C.load_json(a.target)
    if not doc:
        C.die("no orders at %s: run angel-budget first" % a.target)
    orders = doc.get("orders", doc if isinstance(doc, list) else [])
    log = C.load_json("risk-log.json", {}) or {}
    out = []
    for o in orders:
        sym = o.get("symbol") or C.clean_symbol(o.get("tradingsymbol", ""))
        q = None
        if not a.no_quote:
            try:
                q = C.quotes([sym], cfg).get(sym)
            except (C.NetError, C.AngelError) as e:
                print("warning: no fresh price for %s (%s); checking against the order price" % (sym, e))
        inst = C.resolve(sym, required=False)
        verdict, reasons, notes = check(o, cfg, now, q, inst)
        rec = {"fingerprint": o.get("fingerprint"), "n": o.get("n"), "symbol": sym, "verdict": verdict,
               "reasons": reasons, "notes": notes, "time": now.isoformat(), "role": o.get("role", "entry")}
        log.setdefault(today, []).append(rec)
        out.append(rec)
        if not a.json:
            print("#%s %s %s %s x %s: %s" % (o.get("n"), o.get("transactiontype"), sym, o.get("quantity"),
                                           o.get("ordertype"), verdict))
            for r in reasons:
                print("   BLOCK: " + r)
            for n in notes:
                print("   note: " + n)
    C.save_json("risk-log.json", log)
    if a.json:
        C.emit_json(out)
    elif all(r["verdict"] == "PASS" for r in out):
        print("-> recorded. Next: angel-broker shows the ticket and asks for your yes.")
    else:
        print("-> a BLOCK is final for that order. Change the plan or the rules; do not route around it.")


if __name__ == "__main__":
    main()
