---
name: angel-scanner
description: >-
  Chart Scanner for NSE stocks. Builds the universe from NSE's index lists
  (NIFTY 50/100/200/500 or every EQ-series stock), runs a pre-market scan of
  daily bars (20-day closing-high breakout, bull flag, reclaimed 20-day
  average, oversold RSI, oversold bounce) and an intraday opening-range
  breakout scan on 5-minute bars, filters out thinly traded names by average
  turnover in crore, and writes angel-trader/watchlist.json for angel-news and
  angel-entry. Uses Angel One candles when logged in, else free Yahoo data.
  Use when the user says "scan the market", "find me setups", "what is
  breaking out", "opening range breakouts", "scan Nifty 500", "bull flags",
  "oversold stocks", "pre-market scan", "build my watchlist", "what should I
  look at today", or at the start of a trading day.
argument-hint: "[universe | daily | orb] [--list nifty500] [--at HH:MM]"
---

# angel-scanner

The first step of a day trade: read hundreds of charts and list the ones that
match a rule. A scan is a list of charts that match a rule, not a list of
stocks to buy, and a setup is not a prediction.

```bash
python3 "${CLAUDE_SKILL_DIR}/scan.py" universe --list nifty500     # -> angel-trader/universe.json
python3 "${CLAUDE_SKILL_DIR}/scan.py" daily                        # before 09:15 or after the close
python3 "${CLAUDE_SKILL_DIR}/scan.py" daily --only breakout20,bullflag --limit 200
python3 "${CLAUDE_SKILL_DIR}/scan.py" orb                          # after 09:30: breakouts so far
python3 "${CLAUDE_SKILL_DIR}/scan.py" orb --at 10:15 --or 15 --list nifty200
python3 "${CLAUDE_SKILL_DIR}/scan.py" add HDFCBANK ICICIBANK       # by hand
python3 "${CLAUDE_SKILL_DIR}/scan.py" show
```

`${CLAUDE_SKILL_DIR}` is this skill's folder. Default universe is
`nifty500` (set `universe` in config). `all` is every EQ-series NSE stock
(~2,000+) and is slow.

## Setups

| setup | rule (daily bars) |
| --- | --- |
| breakout20 | last close above the highest close of the prior 20 sessions |
| bullflag | +10% or more over 10 sessions, then 5 sessions within 5%, close near the 20-day high |
| reclaim20 | closed back above the 20-day average after closing below it |
| oversold | RSI(14) under 30 |
| bounce | RSI(14) under 30 in the last 4 sessions, then a close above the prior day's high |
| orb | (5-minute bars today) a close above the first 15 minutes' high |

Liquidity: average daily traded value over 20 sessions >= `--min-turnover`
crore (default ₹10 cr). For `orb` the same bar is pro-rated to the time of
day.

## Speed and data

One request per stock. With an Angel One login the candles are real time but
rate-limited (about 3 requests a second), so NIFTY 500 takes several minutes.
Without a login it uses Yahoo (delayed ~15 minutes), similar speed. Use
`--limit` or a smaller list for a quick look; run long scans in the
background and report when done.

## Reporting

Show the table, the count matched, and the data date. For `orb`, it sorts the
closest-to-the-range first: a stock already far above its range needs a
wider stop. Next: angel-news on the list, then angel-entry on the picks.

Not investment advice.
