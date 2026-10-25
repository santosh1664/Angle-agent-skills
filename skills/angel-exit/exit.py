#!/usr/bin/env python3
"""Exit Planner: set the stop and the target before the entry.

  exit.py plan                                   # entry.json: stop at OR midpoint, target 2R
  exit.py plan --stop or-low --target 1.5R
  exit.py plan --symbol TCS --entry 4215 --stop price:4180 --target price:4290
  exit.py plan --stop pct:0.8 --target 2R
  exit.py plan --stop atr:0.5                    # 0.5 x 14-day ATR below entry
  exit.py show

Stops round DOWN and targets round to the 0.05 tick. Writes angel-trader/plan.json.
Long side only.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402


def make_plan(entry_info, stop_mode="or-mid", target_mode="2R", cfg=None, flat_by=None):
    cfg = cfg or C.load_config()
    sym = entry_info["symbol"]
    entry = float(entry_info["entry_price"])
    inst = C.resolve(sym, required=False) or {}
    tick = inst.get("tick", 0.05)
    rng = entry_info.get("opening_range") or {}
    m = stop_mode.split(":", 1)
    kind = m[0]
    if kind == "or-mid":
        if not rng:
            raise ValueError("or-mid needs an opening range (run angel-entry) or use price:/pct:/atr:")
        stop = rng["mid"]
    elif kind == "or-low":
        if not rng:
            raise ValueError("or-low needs an opening range")
        stop = rng["low"]
    elif kind == "price":
        stop = float(m[1])
    elif kind == "pct":
        stop = entry * (1 - float(m[1]) / 100)
    elif kind == "atr":
        daily, _ = C.bars(sym, "1d", days=40, cfg=cfg)
        a = C.atr(daily, 14)
        if not a:
            raise ValueError("not enough daily bars for ATR")
        stop = entry - float(m[1]) * a
    else:
        raise ValueError("unknown stop mode %r" % stop_mode)
    stop = C.tick_floor(stop, tick)
    if stop >= entry:
        raise ValueError("stop %.2f is at or above the entry %.2f: not a long trade" % (stop, entry))
    risk = round(entry - stop, 2)
    min_risk = max(3 * tick, entry * 0.0015)
    if risk < min_risk:
        raise ValueError("stop is only %.2f below entry (< %.2f, ~3 ticks or 0.15%%): too tight to "
                         "survive the spread and noise" % (risk, min_risk))
    if target_mode.upper().endswith("R"):
        mult = float(target_mode[:-1])
        target = C.tick_round(entry + mult * risk, tick)
    elif target_mode.startswith("price:"):
        target = C.tick_round(float(target_mode.split(":", 1)[1]), tick)
    else:
        raise ValueError("unknown target %r (use 2R, 1.5R or price:X)" % target_mode)
    if target <= entry:
        raise ValueError("target %.2f is at or below the entry %.2f" % (target, entry))
    flat = flat_by or cfg["flat_by"]
    if flat > "15:10":
        raise ValueError("flat-by %s is too late: Angel One squares off equity intraday at 15:15" % flat)
    return {
        "symbol": sym, "tradingsymbol": inst.get("symbol", sym + "-EQ"), "token": inst.get("token"),
        "tick": tick, "side": "BUY", "entry": entry, "stop": stop, "target": target,
        "risk_per_share": risk, "reward_per_share": round(target - entry, 2),
        "reward_risk": round((target - entry) / risk, 2), "stop_mode": stop_mode, "target_mode": target_mode,
        "flat_by": flat, "setup": entry_info.get("setup", "manual"), "interval": entry_info.get("interval", "5m"),
        "opening_range": rng or None, "entry_time": entry_info.get("time"),
        "date": C.now_ist().date().isoformat(), "created": C.now_ist().isoformat(),
    }


def show(p):
    print("%s long: entry %.2f  stop %.2f  target %.2f" % (p["symbol"], p["entry"], p["stop"], p["target"]))
    print("  risk %.2f/share, reward %.2f/share, reward:risk %.2f" % (
        p["risk_per_share"], p["reward_per_share"], p["reward_risk"]))
    print("  flat by %s IST either way (Angel One auto square-off is 15:15)" % p["flat_by"])
    print("  stop %s, target %s" % (p["stop_mode"], p["target_mode"]))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan")
    p.add_argument("--symbol")
    p.add_argument("--entry", type=float)
    p.add_argument("--stop", default="or-mid")
    p.add_argument("--target", default="2R")
    p.add_argument("--flat-by")
    p.add_argument("--json", action="store_true")
    sub.add_parser("show")
    a = ap.parse_args()
    cfg = C.load_config()
    if a.cmd == "show":
        pl = C.load_json("plan.json")
        if not pl:
            C.die("no plan yet: run `exit.py plan`")
        show(pl)
        return
    info = C.load_json("entry.json", {}) or {}
    if a.symbol:
        if C.clean_symbol(a.symbol) != info.get("symbol"):
            info = {"symbol": C.clean_symbol(a.symbol), "setup": "manual"}
    if a.entry is not None:
        info["entry_price"] = a.entry
    if not info.get("symbol") or info.get("entry_price") is None:
        C.die("no entry: run angel-entry first, or pass --symbol and --entry")
    try:
        pl = make_plan(info, a.stop, a.target, cfg, a.flat_by)
    except ValueError as e:
        C.die("refused: %s" % e)
    C.save_json("plan.json", pl)
    C.emit_json(pl) if a.json else show(pl)
    print("  -> angel-trader/plan.json (next: angel-timemachine, then angel-budget)")


if __name__ == "__main__":
    main()
