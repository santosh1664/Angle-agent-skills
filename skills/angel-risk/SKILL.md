---
name: angel-risk
description: >-
  Risk Manager for Angel One trades. Checks every order against the user's
  limits and BLOCKS anything over them before it can reach the broker: a
  stop is required, the loss at the stop including charges must fit the max
  loss per trade, reward:risk must meet the minimum, today's risk plus
  losses must fit the daily loss limit, no more than the allowed trades per
  day, entries only inside the entry window while NSE is open, no
  trade-to-trade (BE/BZ) stocks intraday, nothing near the upper circuit or
  with a stop under the lower circuit, plus order size, position cap, cash
  buffer, no shorts/F&O/MTF, no duplicates. Exits are never blocked by day
  limits. Use when the user says "check my order", "is this safe", "risk
  check", "does this break my rules", "can I take this trade", "how much
  have I risked today", and always before angel-broker.
argument-hint: "[orders.json | today]"
---

# angel-risk

The gate between a proposal and the broker. It prints PASS or BLOCK with
every reason and records the verdict by the order's fingerprint in
`angel-trader/risk-log.json`. angel-broker refuses any order whose exact
fingerprint did not PASS in the last 15 minutes.

**A BLOCK is final for that order.** Tell the user each reason in plain
words. Do not edit the order, the limits or the logs to turn it into a PASS.
The user may change their rules (angel-budget `set`) or the plan, then the
order is sized and checked again from the start. Loosening a limit to fit one
trade is a decision for the user to make knowingly, so name the limit and the
number if they ask.

```bash
python3 "${CLAUDE_SKILL_DIR}/check.py"              # angel-trader/orders.json
python3 "${CLAUDE_SKILL_DIR}/check.py" today        # trades, realised, open risk, room left
python3 "${CLAUDE_SKILL_DIR}/check.py" --no-quote   # skip the fresh price (offline)
```

`${CLAUDE_SKILL_DIR}` is this skill's folder.

## What it checks (entries)

| check | rule (config key) |
| --- | --- |
| stop | required, below the price |
| loss at the stop | qty x (price - stop) + estimated round-trip charges <= `max_loss_per_trade` |
| reward:risk | (target - price) / (price - stop) >= `min_reward_risk` |
| daily loss limit | open risk + today's realised losses + this trade <= `daily_loss_limit` |
| trades per day | < `max_trades_per_day` |
| time | NSE open, inside `entry_window` (default 09:30-14:30), before `flat_by` |
| flat-by | not after 15:10 (Angel One auto square-off 15:15) |
| size | value <= `max_order_value`, <= `max_position_pct` of capital (x `mis_leverage`), fits after `cash_buffer_pct` |
| instrument | NSE/BSE cash equity, EQ series for intraday (BE/BZ are trade-to-trade), not `blocked` |
| direction/product | BUY only unless `allow_short`; INTRADAY or DELIVERY; no F&O unless `allow_fno` |
| circuits | price not within 1% of the upper circuit; stop above the lower circuit (needs Angel One quotes) |
| duplicates | not already holding the symbol; the same order not placed today |

"Price" is the order's limit for a LIMIT buy (it cannot fill higher) and the
worse of the plan price and a fresh price for a MARKET buy. The fresh price
comes from Angel One when logged in, else Yahoo (delayed ~15 min; say so).

Exits (`role: exit`, SELL) only need to be valid: day limits never stop the
user getting out.

## Defaults

Capital ₹1,00,000, max loss ₹500 a trade, daily loss limit ₹1,500, 3 trades a
day, reward:risk 1.5, position cap 50%, max order ₹1,00,000, 10% cash buffer,
no leverage. They are starting points, not advice. The user sets their own
with angel-budget: `size.py set max_loss_per_trade=750 daily_loss_limit=2000`.

Not investment advice. These limits keep each loss and each day's losses
small; they do not make a trade win.
