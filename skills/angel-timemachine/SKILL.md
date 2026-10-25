---
name: angel-timemachine
description: >-
  Time Machine for NSE intraday trades. Before any rupee is risked, replays
  the rest of the session 10,000 times from the stock's own 5-minute bars
  over the last ~60 sessions (each time slot drawn from that slot's real
  bars), and re-runs the same opening-range rule on every past session.
  Prints the odds of target first, stop first or neither by flat-by, the
  average R, where the price sits at flat-by, the real history and one
  honest verdict, then hands off to angel-budget. Use when the user says
  "run the time machine", "replay this trade", "what are the odds",
  "simulate this trade", "monte carlo", "backtest this setup", "how often
  does this hit the target", "is this a coin flip", or after angel-exit
  writes a plan.
argument-hint: "[path to plan.json]"
---

# angel-timemachine

Sits between the plan and the money. One question: if today plays out like
this stock's own last 60 sessions, how often does this plan hit the target
first, the stop first, or neither?

```bash
python3 "${CLAUDE_SKILL_DIR}/timemachine.py" run                     # angel-trader/plan.json
python3 "${CLAUDE_SKILL_DIR}/timemachine.py" run --sims 20000 --seed 7
python3 "${CLAUDE_SKILL_DIR}/timemachine.py" run --json
```

`${CLAUDE_SKILL_DIR}` is this skill's folder. Every run writes
`angel-trader/timemachine.json`. The default seed (19) makes a run
repeatable; say the seed when you report.

## Method (say it in one or two sentences when reporting)

- **Replay:** each 5-minute slot of the day (09:15, 09:20, ...) gets a pool of
  that slot's real bars from past sessions, as moves relative to the previous
  close. A replay starts at the entry and draws one bar per slot until the
  stop, the target or flat-by. A bar that touches both counts as the stop.
- **History:** the opening-range breakout rule (first 5-minute close above
  the 15-minute range, inside the entry window) re-run on every past session,
  with the plan's stop logic (range midpoint/low, or the same % distance) and
  the same R multiple for the target.
- Needs at least 15 full past sessions. Angel One serves 5-minute history in
  chunks (about 500 candles per request, ~3 requests a second); Yahoo serves
  up to 60 days.

## Reporting

Give: target first %, stop first %, neither %, average R, the history line
(fired N of M sessions: target / stop / neither, average R), and the verdict.
The verdict: above +0.2 R "leans your way in this sample", -0.1 to +0.2
"close to a coin flip", below -0.1 "the odds lean against this plan". When
the replay and the history disagree, say so.

Always add: this is a simulation built from about 60 sessions of the stock's
own bars, not a prediction. Results days, news, a circuit, a market-wide
move or a halt can do what those sessions never did. Charges and slippage
make every R slightly worse. Treat the odds as a reality check, never a
promise.
