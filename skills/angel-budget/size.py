#!/usr/bin/env python3
"""Budget Manager: size the trade to your budget and your max loss per trade.

  size.py                         # plan.json + config.json -> angel-trader/orders.json
  size.py --capital 100000 --max-loss 500
  size.py --order-type market     # default: LIMIT at entry + 0.05% buffer
  size.py --funds-from-angel      # cap by Angel One available cash (needs login)
  size.py config                  # print the rules in force
  size.py set max_loss_per_trade=750 capital=200000

Whole shares only. A stop too far away for your max loss is a refusal, not a
smaller order. Nothing is placed.
"""
import argparse
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402


def open_exposure(cfg):
    led = C.load_json("ledger.json", {}) or {}
    return sum(p["qty"] * p["entry"] for p in led.get("positions", []) if p.get("status") == "open")


def size(plan, cfg, ordertype="LIMIT", buffer_pct=0.05, funds=None):
    tick = plan.get("tick", 0.05)
    entry = plan["entry"]
    limit = C.tick_ceil(entry * (1 + buffer_pct / 100.0), tick) if ordertype == "LIMIT" else None
    worst = limit or entry
    risk_ps = worst - plan["stop"]
    if risk_ps <= 0:
        raise ValueError("stop is not below the entry")
    cap = cfg["capital"]
    lev = max(1.0, float(cfg.get("mis_leverage", 1)))
    buying_power = cap * (1 - cfg["cash_buffer_pct"] / 100.0) * lev - open_exposure(cfg)
    if funds is not None:
        buying_power = min(buying_power, funds * lev)
    limits = {
        "max loss per trade": math.floor(cfg["max_loss_per_trade"] / risk_ps),
        "position cap": math.floor(cap * cfg["max_position_pct"] / 100.0 * lev / worst),
        "max order value": math.floor(cfg["max_order_value"] / worst),
        "cash after buffer": math.floor(max(buying_power, 0) / worst),
    }
    qty = min(limits.values())
    decided = min(limits, key=lambda k: limits[k])
    if limits["max loss per trade"] < 1:
        raise ValueError("one share risks %s, more than your max loss of %s: the stop is too far "
                         "for this budget" % (C.inr(risk_ps), C.inr(cfg["max_loss_per_trade"])))
    # trim for charges so loss-at-stop INCLUDING charges stays inside the max loss
    while qty > 0:
        fees = C.charges("BUY", qty, worst, cfg) + C.charges("SELL", qty, plan["stop"], cfg)
        if qty * risk_ps + fees <= cfg["max_loss_per_trade"]:
            break
        qty -= 1
        decided = "max loss per trade (incl. charges)"
    if qty < 1:
        raise ValueError("nothing fits: %s" % ", ".join("%s %d" % kv for kv in limits.items()))
    fees_stop = C.charges("BUY", qty, worst, cfg) + C.charges("SELL", qty, plan["stop"], cfg)
    fees_tgt = C.charges("BUY", qty, worst, cfg) + C.charges("SELL", qty, plan["target"], cfg)
    order = {
        "n": 1, "role": "entry", "date": C.now_ist().date().isoformat(),
        "symbol": plan["symbol"],
        # SmartAPI placeOrder fields
        "variety": "NORMAL", "tradingsymbol": plan["tradingsymbol"], "symboltoken": plan.get("token"),
        "transactiontype": "BUY", "exchange": cfg.get("exchange", "NSE"), "ordertype": ordertype,
        "producttype": cfg.get("product", "INTRADAY"), "duration": "DAY",
        "price": "%.2f" % limit if limit else "0", "triggerprice": "0",
        "squareoff": "0", "stoploss": "0", "quantity": str(qty),
        # the exits that go with it
        "stop": plan["stop"], "target": plan["target"], "flat_by": plan["flat_by"],
        "plan_entry": entry, "worst_entry": worst,
        "value": round(qty * worst, 2), "max_loss": round(qty * risk_ps + fees_stop, 2),
        "gain_at_target": round(qty * (plan["target"] - worst) - fees_tgt, 2),
        "est_charges_round_trip": round(fees_stop, 2), "limits": limits, "decided_by": decided,
    }
    order["fingerprint"] = C.fingerprint(order)
    return order


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", nargs="?", default="size", choices=["size", "config", "set"])
    ap.add_argument("pairs", nargs="*")
    ap.add_argument("--capital", type=float)
    ap.add_argument("--max-loss", type=float)
    ap.add_argument("--order-type", choices=["limit", "market"], default="limit")
    ap.add_argument("--buffer-pct", type=float, default=0.05)
    ap.add_argument("--funds-from-angel", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    if a.cmd == "set":
        user = C.load_json("config.json", {}) or {}
        for kv in a.pairs:
            k, _, v = kv.partition("=")
            if k not in C.DEFAULT_CONFIG:
                C.die("unknown setting %r" % k)
            d = C.DEFAULT_CONFIG[k]
            if isinstance(d, bool):
                v = v.lower() in ("1", "true", "yes", "on")
            elif isinstance(d, (int, float)):
                v = float(v)
            elif isinstance(d, list):
                v = [x.strip() for x in v.split(",") if x.strip()]
            if k in ("paper", "live_enabled", "target_at_broker") and kv:
                print("note: %s changes how orders are routed; read angel-broker SKILL.md" % k)
            user[k] = v
        C.save_json("config.json", user)
        print("saved angel-trader/config.json")
        return
    cfg = C.load_config()
    if a.capital:
        cfg["capital"] = a.capital
    if a.max_loss:
        cfg["max_loss_per_trade"] = a.max_loss
    if a.cmd == "config":
        for k in sorted(cfg):
            print("%-20s %s" % (k, cfg[k]))
        return
    plan = C.load_json("plan.json")
    if not plan:
        C.die("no plan: run angel-exit first")
    if plan.get("date") != C.now_ist().date().isoformat():
        print("warning: plan.json is from %s, not today" % plan.get("date"))
    funds = None
    if a.funds_from_angel:
        api = C.SmartAPI()
        api.ensure()
        rms = api.call("rms") or {}
        funds = float(rms.get("availablecash") or 0)
        print("Angel One available cash: %s" % C.inr(funds))
    try:
        o = size(plan, cfg, a.order_type.upper(), a.buffer_pct, funds)
    except ValueError as e:
        C.die("refused: %s" % e)
    C.save_json("orders.json", {"created": C.now_ist().isoformat(), "plan": plan, "orders": [o]})
    if a.json:
        C.emit_json(o)
        return
    print("BUY %s x %s %s (%s, %s)" % (o["quantity"], o["tradingsymbol"],
                                       ("LIMIT %s" % o["price"]) if o["ordertype"] == "LIMIT" else "MARKET",
                                       o["producttype"], o["exchange"]))
    print("  value %s  | stop %.2f  target %.2f  flat by %s" % (C.inr(o["value"]), o["stop"], o["target"], o["flat_by"]))
    print("  max loss at the stop %s (incl. ~%s charges)  | gain at target %s after charges" % (
        C.inr(o["max_loss"]), C.inr(o["est_charges_round_trip"]), C.inr(o["gain_at_target"])))
    print("  size decided by: %s  (%s)" % (o["decided_by"], ", ".join("%s %d" % kv for kv in o["limits"].items())))
    print("  -> angel-trader/orders.json (next: angel-risk)")


if __name__ == "__main__":
    main()
