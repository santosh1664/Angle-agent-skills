---
name: angel-budget
description: >-
  Budget Manager for Angel One intraday trades. Sizes the position from the
  trade plan (entry, stop, target) to whole shares that fit the user's max
  loss per trade INCLUDING estimated charges, their position cap, max order
  value and cash after a buffer (optionally capped by Angel One available
  cash), says which limit decided the size, and writes one order in Angel
  One SmartAPI placeOrder format with its stop, target and flat-by to
  angel-trader/orders.json. A stop too far for the max loss is a refusal,
  not a smaller order. Also where the user sets their rules. Use when the
  user says "how many shares", "size this trade", "how much should I buy",
  "I have ₹50,000", "I only want to risk ₹500 a trade", "set my rules",
  "keep 10% in cash", "change my daily limit", or after angel-exit and
  angel-timemachine.
argument-hint: "[--capital N] [--max-loss N] | set key=value"
---

# angel-budget

Turns a plan ("buy RELIANCE at 3325.48, stop 3310.40") into an exact order
("buy 15 shares, limit 3327.15"). The stop decides the size: the further the
stop, the fewer shares. It writes a proposal only; angel-risk checks it and
angel-broker asks the user.

```bash
python3 "${CLAUDE_SKILL_DIR}/size.py"                        # plan.json + config -> orders.json
python3 "${CLAUDE_SKILL_DIR}/size.py" --capital 50000 --max-loss 300   # this run only
python3 "${CLAUDE_SKILL_DIR}/size.py" --order-type market
python3 "${CLAUDE_SKILL_DIR}/size.py" --funds-from-angel     # cap by Angel One available cash
python3 "${CLAUDE_SKILL_DIR}/size.py" config                 # the rules in force
python3 "${CLAUDE_SKILL_DIR}/size.py" set capital=200000 max_loss_per_trade=1000 daily_loss_limit=3000
```

`${CLAUDE_SKILL_DIR}` is this skill's folder. `config.example.json` here
lists every setting.

## How the size is found

- Entry is a LIMIT buy at the plan entry + 0.05%, rounded up to the tick, so
  a fast bar does not leave the order behind. `--buffer-pct` changes it;
  `--order-type market` sends a market order instead (risk then uses the
  worse of plan and fresh price).
- Shares = the smallest of: max loss / (limit - stop); position cap; max
  order value; cash after the buffer (all x `mis_leverage`, default 1 = no
  leverage), minus what is already in open positions.
- Then it trims shares until loss at the stop **plus estimated round-trip
  charges** fits the max loss. On small trades, charges matter: ₹20 or 0.1%
  brokerage per order (minimum ₹5), STT 0.025% on the sell, exchange, SEBI,
  stamp and GST.
- If even one share risks more than the max loss, it refuses and says so.

Report: shares, limit, value, stop, target, flat-by, max loss at the stop
(with charges), gain at the target after charges, and which limit decided.

## Setting rules

Ask the user for their numbers; do not invent them. Keys: `capital`,
`max_loss_per_trade`, `daily_loss_limit`, `max_trades_per_day`,
`max_position_pct`, `max_order_value`, `cash_buffer_pct`, `min_reward_risk`,
`mis_leverage`, `entry_window` (e.g. `09:30,14:30`), `flat_by`, `blocked`
(comma list), `watchlist`, `universe`, `data_source` (auto|smartapi|yahoo).
`paper`, `live_enabled` and `target_at_broker` change how orders are routed:
only set them when the user explicitly tells you to, after reading
angel-broker's "Going live".

A common rule of thumb is to risk no more than 0.5-1% of capital on one
trade; it is the user's call. Intraday leverage (MIS) magnifies losses the
same as gains; 1 means none.

Not investment advice.
