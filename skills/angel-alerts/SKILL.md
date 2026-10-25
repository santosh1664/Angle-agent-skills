---
name: angel-alerts
description: >-
  Price Alerts for NSE stocks. Rings when a price, a stop, a target, a time
  or the opening bell hits: above / below levels, a percent move from
  yesterday's close, any time of day, the 09:00 pre-open and 09:15 open, and
  in one go the plan's stop, target and flat-by time. Each alert rings once.
  Knows NSE hours, the 2026 holidays and the Diwali Muhurat session, works
  in IST, uses Angel One quotes when logged in (with circuit limits) or
  delayed Yahoo prices, and writes angel-trader/prices.json. Use when the
  user says "alert me when", "tell me if RELIANCE hits", "watch my stop",
  "watch my trade", "remind me to close by 3", "is the market open", "when
  does the market open", "is tomorrow a holiday", "get me a price", or right
  after angel-exit writes a plan.
argument-hint: "[SYMBOL above|below|pct LEVEL] | from-plan | clock | check"
---

# angel-alerts

Watches the numbers so the user does not have to stare at a chart. An alert
is information, never an order: when a stop alert rings, nothing is sold by
this skill. In paper or live trading the stop is handled by angel-broker
`manage` (and, live, by the SL-M order at Angel One).

```bash
python3 "${CLAUDE_SKILL_DIR}/alerts.py" clock                      # NSE open/closed, next open, holidays
python3 "${CLAUDE_SKILL_DIR}/alerts.py" add RELIANCE above 2950
python3 "${CLAUDE_SKILL_DIR}/alerts.py" add TCS below 4100
python3 "${CLAUDE_SKILL_DIR}/alerts.py" add INFY pct -2            # 2% below yesterday's close
python3 "${CLAUDE_SKILL_DIR}/alerts.py" add time 14:55 "close the trade"
python3 "${CLAUDE_SKILL_DIR}/alerts.py" add bell                   # 09:00 pre-open + 09:15 open
python3 "${CLAUDE_SKILL_DIR}/alerts.py" from-plan                  # stop, target, flat-by
python3 "${CLAUDE_SKILL_DIR}/alerts.py" list | remove 3 | clear
python3 "${CLAUDE_SKILL_DIR}/alerts.py" check                      # ring what hit, once
python3 "${CLAUDE_SKILL_DIR}/alerts.py" watch --every 20           # loop until done or 15:30
```

`${CLAUDE_SKILL_DIR}` is this skill's folder.

## Ringing

`check` looks once. To keep watching, either run `watch` in the background
for the session, or, if the user wants checks while they are away, offer a
scheduled task that runs `check` every few minutes in market hours and
reports only what rang. Without an Angel One login, prices are Yahoo's,
delayed about 15 minutes: say so with every ring.

## The calendar

NSE cash market: pre-open 09:00-09:08 (order collection), continuous
09:15-15:30 IST, Monday-Friday except exchange holidays. 2026 holidays are
built in (16 weekday closures including 20 Oct Dussehra, 10 Nov Diwali
Balipratipada, 24 Nov Guru Nanak Jayanti, 25 Dec Christmas). Muhurat
trading is Sunday 8 Nov 2026 with timings set by NSE circular. 2027 dates are
not published yet: add them to `extra_holidays` in config.json when NSE
announces them. Angel One squares off equity intraday positions at 15:15.

Not investment advice.
