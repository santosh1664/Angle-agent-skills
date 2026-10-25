---
name: angel-exit
description: >-
  Exit Planner for NSE intraday trades. Sets the stop and the target before
  the entry: stop at the opening-range midpoint by default (or the range low,
  a price, a percent, or a multiple of the 14-day ATR), rounded down to the
  ₹0.05 tick, target at 2R by default (or any R, or a price), and a flat-by
  time before Angel One's 15:15 auto square-off. Refuses a stop at or above
  the entry, a target at or below it, a stop too tight to survive the
  spread, or a flat-by after 15:10, and says why. Writes
  angel-trader/plan.json for the Time Machine, the Budget Manager and Price
  Alerts. Long side only. Use when the user says "where's my stop", "set my
  stop and target", "plan the exit", "when do I get out", "stop loss",
  "what's my R", "risk reward", or right after angel-entry triggers.
argument-hint: "[--stop or-mid|or-low|price:X|pct:X|atr:K] [--target 2R|1.5R|price:X]"
---

# angel-exit

Decides how a trade ends before it starts. The stop is where the setup has
failed; the target is where the user takes what they came for; the flat-by
time ends the day trade either way. All three are written down before the
entry so nothing has to be decided in a fast move.

```bash
python3 "${CLAUDE_SKILL_DIR}/exit.py" plan                                  # entry.json, or-mid stop, 2R
python3 "${CLAUDE_SKILL_DIR}/exit.py" plan --stop or-low --target 1.5R
python3 "${CLAUDE_SKILL_DIR}/exit.py" plan --symbol TCS --entry 4215 --stop price:4180 --target price:4290
python3 "${CLAUDE_SKILL_DIR}/exit.py" plan --stop pct:0.8
python3 "${CLAUDE_SKILL_DIR}/exit.py" plan --stop atr:0.5 --flat-by 14:45
python3 "${CLAUDE_SKILL_DIR}/exit.py" show
```

`${CLAUDE_SKILL_DIR}` is this skill's folder.

## Rules it applies

- Stop rounds **down** to the tick (₹0.05 for most NSE stocks; the tick comes
  from Angel One's instrument list), target rounds to the tick.
- R = entry - stop. Target nR = entry + n x R.
- Refused: stop at/above entry; stop closer than 3 ticks or 0.15% of price
  (noise and the spread would take it out); target at/below entry; flat-by
  after 15:10.
- Flat-by defaults to 15:00. Angel One squares off open equity intraday
  positions at 15:15 and NSE's closing auction changes the last minutes, so
  the plan is out before both.

Report entry, stop, target, risk and reward per share, reward:risk and the
flat-by time. Next: angel-timemachine (odds), then angel-budget (size).

A stop is a plan, not a guarantee: an SL-M order can fill well below its
trigger in a gap, a fast fall or at a lower circuit. Not investment advice.
