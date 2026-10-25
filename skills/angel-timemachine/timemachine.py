#!/usr/bin/env python3
"""Time Machine: replay a trade 10,000 times before you risk a rupee.

  timemachine.py run                    # plan.json: 10,000 replays + every past session
  timemachine.py run --sims 20000 --seed 7 --days 60
  timemachine.py run --json             # every run also writes angel-trader/timemachine.json

How it works. From the stock's own 5-minute bars over the last ~60 sessions, each
time slot of the day (09:15, 09:20, ...) gets a pool of real bars, expressed as
moves relative to the previous close. A replay starts at your entry and draws one
bar per slot from that slot's pool until the stop, the target or the flat-by time.
If one bar touches both the stop and the target, the stop is counted (pessimistic).
The history check re-runs the same opening-range rule on every past session.

A simulation from 60 days of bars, not a prediction: results, news, a circuit,
a halt or a market-wide move can do what those 60 days never did.
"""
import argparse
import datetime as dt
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402


def slot(b):
    return C.bar_time(b).strftime("%H:%M")


def pools(sessions):
    """{HH:MM: [(ret, hi, lo), ...]} relative to the previous bar's close."""
    out = {}
    for bars in sessions:
        for prev, b in zip(bars, bars[1:]):
            pc = prev["c"]
            if pc <= 0:
                continue
            out.setdefault(slot(b), []).append((b["c"] / pc - 1, b["h"] / pc - 1, b["l"] / pc - 1))
    return out


def simulate(plan, pool, start_slot, flat_by, sims=10000, seed=19):
    rng = random.Random(seed)
    entry, stop, target = plan["entry"], plan["stop"], plan["target"]
    risk = entry - stop
    slots = sorted(s for s in pool if start_slot <= s < flat_by and pool[s])
    res = {"target": 0, "stop": 0, "neither": 0}
    rs, closes = [], []
    for _ in range(sims):
        p = entry
        out = None
        for s in slots:
            r, h, l = rng.choice(pool[s])
            hi, lo, p = p * (1 + h), p * (1 + l), p * (1 + r)
            if lo <= stop:
                out = ("stop", stop)
                break
            if hi >= target:
                out = ("target", target)
                break
        if out is None:
            out = ("neither", p)
        res[out[0]] += 1
        rs.append((out[1] - entry) / risk)
        closes.append(out[1] if out[0] == "neither" else None)
    neither = sorted(c for c in closes if c is not None)

    def pct(q):
        return round(neither[int(q * (len(neither) - 1))], 2) if neither else None

    return {"sims": sims, "seed": seed, "slots": len(slots),
            "p_target": round(100.0 * res["target"] / sims, 1), "p_stop": round(100.0 * res["stop"] / sims, 1),
            "p_neither": round(100.0 * res["neither"] / sims, 1), "avg_r": round(sum(rs) / sims, 3),
            "neither_close": {"p5": pct(0.05), "p25": pct(0.25), "p50": pct(0.5), "p75": pct(0.75), "p95": pct(0.95)}}


def history(plan, sessions, cfg, or_minutes=15):
    """Re-run the opening-range breakout rule on each past session with the plan's stop/target logic."""
    stop_mode, target_mode = plan.get("stop_mode", "or-mid"), plan.get("target_mode", "2R")
    pct_stop = (plan["entry"] - plan["stop"]) / plan["entry"]
    mult = float(target_mode[:-1]) if target_mode.upper().endswith("R") else \
        (plan["target"] - plan["entry"]) / (plan["entry"] - plan["stop"])
    win_end = cfg["entry_window"][1]
    rows = []
    for bars in sessions:
        rng = C.opening_range(bars, or_minutes)
        if not rng:
            continue
        trig = None
        for i, b in enumerate(bars):
            if slot(b) < rng["end"]:
                continue
            if slot(b) > win_end:
                break
            if b["c"] > rng["high"]:
                trig = i
                break
        if trig is None:
            continue
        e = bars[trig]["c"]
        if stop_mode == "or-mid":
            s = rng["mid"]
        elif stop_mode == "or-low":
            s = rng["low"]
        else:
            s = e * (1 - pct_stop)
        if s >= e:
            continue
        t = e + mult * (e - s)
        outcome, px = "neither", None
        for b in bars[trig + 1:]:
            if slot(b) >= plan["flat_by"]:
                px = b["o"]
                break
            if b["l"] <= s:
                outcome, px = "stop", s
                break
            if b["h"] >= t:
                outcome, px = "target", t
                break
            px = b["c"]
        if px is None:
            px = e
        rows.append({"date": C.bar_time(bars[0]).date().isoformat(), "entry": round(e, 2), "stop": round(s, 2),
                     "target": round(t, 2), "outcome": outcome, "r": round((px - e) / (e - s), 2)})
    n = len(rows)
    agg = {k: sum(1 for r in rows if r["outcome"] == k) for k in ("target", "stop", "neither")}
    return {"sessions": len(sessions), "fired": n, "counts": agg,
            "avg_r": round(sum(r["r"] for r in rows) / n, 3) if n else None, "rows": rows}


def verdict(sim, hist):
    er = sim["avg_r"]
    words = ("leans your way in this sample" if er > 0.2 else
             "close to a coin flip" if er > -0.1 else "the odds lean against this plan")
    if hist and hist["fired"] >= 10 and hist["avg_r"] is not None:
        if (hist["avg_r"] > 0) != (er > 0):
            words += "; the real history disagrees with the replay, so trust neither much"
    elif hist is not None:
        words += "; the rule fired too rarely in history to say much"
    return words


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("run")
    p.add_argument("plan", nargs="?", default="plan.json")
    p.add_argument("--sims", type=int, default=10000)
    p.add_argument("--seed", type=int, default=19)
    p.add_argument("--days", type=int, default=60)
    p.add_argument("--or", dest="or_minutes", type=int, default=15)
    p.add_argument("--json", action="store_true")
    a = ap.parse_args()
    cfg = C.load_config()
    plan = C.load_json(a.plan)
    if not plan:
        C.die("no plan: run angel-exit first")
    today = dt.date.fromisoformat(plan["date"])
    end = C.at(today, C.CLOSE)
    bs, src = C.bars(plan["symbol"], "5m", days=a.days, cfg=cfg, end=end)
    days = C.split_sessions(bs)
    past = [C.session(days[d], dt.date.fromisoformat(d)) for d in sorted(days) if d < plan["date"]]
    past = [s for s in past if len(s) >= 60][-(a.days - 1):]
    if len(past) < 15:
        C.die("only %d full past sessions of 5-minute bars: not enough to replay" % len(past))
    start = plan.get("entry_time") or C.now_ist().strftime("%H:%M")
    h, m = map(int, start.split(":"))
    start = "%02d:%02d" % (h, m - m % 5)
    sim = simulate(plan, pools(past), start, plan["flat_by"], a.sims, a.seed)
    hist = history(plan, past, cfg, a.or_minutes) if plan.get("setup") == "orb" else None
    out = {"symbol": plan["symbol"], "plan": {k: plan[k] for k in ("entry", "stop", "target", "flat_by")},
           "from": start, "data": src, "past_sessions": len(past), "replay": sim, "history": hist,
           "verdict": verdict(sim, hist), "created": C.now_ist().isoformat()}
    C.save_json("timemachine.json", out)
    if a.json:
        C.emit_json(out)
        return
    rr = (plan["target"] - plan["entry"]) / (plan["entry"] - plan["stop"])
    print("%s from %s, entry %.2f, stop %.2f, target %.2f (%.2fR), flat by %s" % (
        plan["symbol"], start, plan["entry"], plan["stop"], plan["target"], rr, plan["flat_by"]))
    print("Replay: %d sessions of %s, each 5-min slot drawn from %d past sessions (seed %d)" % (
        sim["sims"], plan["symbol"], len(past), sim["seed"]))
    print("  target first %.1f%%   stop first %.1f%%   still open at flat-by %.1f%%" % (
        sim["p_target"], sim["p_stop"], sim["p_neither"]))
    print("  average outcome %+.2f R (before charges)" % sim["avg_r"])
    nc = sim["neither_close"]
    if nc["p50"] is not None:
        print("  when neither hits, price at flat-by: 5%% %.2f | 25%% %.2f | median %.2f | 75%% %.2f | 95%% %.2f" % (
            nc["p5"], nc["p25"], nc["p50"], nc["p75"], nc["p95"]))
    if hist:
        c = hist["counts"]
        print("History: the same opening-range rule fired on %d of %d past sessions: %d target, %d stop, %d neither; "
              "average %s R" % (hist["fired"], hist["sessions"], c["target"], c["stop"], c["neither"],
                                ("%+.2f" % hist["avg_r"]) if hist["avg_r"] is not None else "-"))
    print("Verdict: %s." % out["verdict"])
    print("A simulation from %s's last %d sessions, not a prediction. Charges and slippage make every R a "
          "little worse." % (plan["symbol"], len(past)))
    print("-> angel-trader/timemachine.json (next: angel-budget)")


if __name__ == "__main__":
    main()
