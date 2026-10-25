---
name: angel-entry
description: >-
  Entry Timer for NSE stocks. Watches a setup bar by bar (Angel One real-time
  candles when logged in, else free delayed Yahoo bars) and calls the entry
  on the first completed 5-minute (or 1-minute) bar that CLOSES above the
  opening range high (first 15 minutes from 09:15 IST by default) or above a
  level the user gives, with an optional volume check. Says not open,
  building range, waiting and how far, triggered with the time and price, or
  expired, and writes angel-trader/entry.json for angel-exit. Long side only;
  never places an order. Use when the user says "tell me when to get in",
  "watch RELIANCE", "has it broken out", "did it break the opening range",
  "entry signal", "time my entry", "check my watchlist", or after
  angel-scanner and angel-news, before angel-exit.
argument-hint: "[SYMBOL] [--setup orb|level] [--interval 5m|1m]"
---

# angel-entry

Turns a setup into one moment: the bar that confirms it. A price that pokes
above the level in the middle of a bar is not an entry; a bar that CLOSES
above it is. Then it records the time and price for the Exit Planner and
stops. It never buys anything.

```bash
python3 "${CLAUDE_SKILL_DIR}/entry.py" check RELIANCE                  # 15-min range, 5-min bars
python3 "${CLAUDE_SKILL_DIR}/entry.py" check RELIANCE --or 30 --interval 1m
python3 "${CLAUDE_SKILL_DIR}/entry.py" check TCS --setup level --level 4210.5
python3 "${CLAUDE_SKILL_DIR}/entry.py" check INFY --vol-mult 1.5       # trigger bar volume >= 1.5x OR average
python3 "${CLAUDE_SKILL_DIR}/entry.py" watch RELIANCE --every 30       # loop until triggered or expired
python3 "${CLAUDE_SKILL_DIR}/entry.py" scan                            # every symbol on the watchlist
```

`${CLAUDE_SKILL_DIR}` is this skill's folder. Symbols are NSE symbols
(RELIANCE, TCS, HDFCBANK); `.NS` or `-EQ` suffixes are stripped.

## States

- **not open**: weekend, NSE holiday or before 09:15 IST.
- **building range**: the opening range is not complete (09:15-09:30 for 15
  minutes).
- **waiting**: shows the last price, the level, and how far away it is.
- **triggered**: the first completed bar after the range that closed above
  the level, inside the entry window. Writes `angel-trader/entry.json`
  (symbol, opening range, trigger bar, entry price = that close, time).
- **expired**: no close above the level before the entry window ended
  (default 14:30).

## Notes to pass on

- Without an Angel One login the bars come from Yahoo and are delayed about
  15 minutes. Say so when reporting a trigger: by the time it shows, the
  price may already be well past it. Real-time needs angel-broker `login`.
- A trigger after a big move away from the range means a wide stop and fewer
  shares; angel-exit and angel-budget will show that.
- `watch` runs in the foreground; for a long wait, check every few minutes
  with `check` instead, or set an angel-alerts level.
- Next step after a trigger: angel-exit `plan`, then angel-timemachine.

Not investment advice. A clean signal does not change the fact that most
intraday traders lose money.
