# Angle Agent Skills: Angel One Trader for Claude

11 Claude skills for intraday trading on the NSE through **Angel One SmartAPI**:
scan hundreds of charts, read the exchange filings, time the entry, plan the
exit, replay the trade 10,000 times, size it, risk-check it, and paper-trade it,
or, once you switch it on yourself, send it to Angel One with the stop-loss
placed at the broker.

Standard-library Python 3.8+. Nothing to pip install. **Paper trading by default.**

---

## Install

### Option 1: Claude Code plugin (recommended)

In Claude Code, run:

```
/plugin marketplace add santosh1664/Angle-agent-skills
/plugin install angel-one-trader@angle-agent-skills
```

Restart Claude Code if the skills do not show up. Plugin skills are namespaced, so
they appear as `/angel-one-trader:angel-scanner`, `/angel-one-trader:angel-broker`
and so on, and Claude also picks them up from plain requests ("scan Nifty 200
for breakouts").

Update later with `/plugin marketplace update angle-agent-skills`.

### Option 2: Plain skill folders (Claude Code)

Copy the folders if you want short names like `/angel-scanner`:

```bash
git clone https://github.com/santosh1664/Angle-agent-skills.git
cp -r Angle-agent-skills/skills/angel-* ~/.claude/skills/          # every project
# or, for one project only:
mkdir -p .claude/skills && cp -r Angle-agent-skills/skills/angel-* .claude/skills/
```

Keep each folder whole: every skill runs the `.py` script and `common.py` that
sit next to its `SKILL.md`.

### Option 3: Claude app (desktop / claude.ai)

Download [`dist/angel-one-trader.plugin`](dist/angel-one-trader.plugin), attach
it to a chat in the Claude desktop app and press **Install** on the preview card.

To add one skill at a time instead, zip a single skill folder (for example
`skills/angel-scanner/`, with its `SKILL.md` at the top of the zip) and upload it
in the Skills section of Claude's settings. The skills run Python, so they need
code execution enabled. Real-time data and live orders also need your Angel One
credentials on the machine running the code, which in practice means Claude Code
or the desktop app on your own computer.

### Check it works

Ask Claude: **"is the NSE market open?"** (runs `angel-alerts clock`), then
**"scan Nifty 50 for setups"**. Without an Angel One login everything runs on
free, ~15-minute-delayed Yahoo prices and paper fills.

---

## Connect Angel One (optional: real-time data and live orders)

1. Sign in to the SmartAPI developer portal at [smartapi.angelone.in](https://smartapi.angelone.in),
   create an app for trading APIs and copy its **API key**.
2. On the portal's **Enable TOTP** page, link an authenticator app. Keep the
   base32 secret only if you want unattended logins.
3. Put your details in environment variables **yourself**. Never paste them into a chat.

   ```bash
   export ANGEL_API_KEY="..."
   export ANGEL_CLIENT_CODE="..."      # your Angel One client ID
   export ANGEL_PIN="...."             # your 4-digit login PIN
   export ANGEL_TOTP_SECRET="..."      # optional
   ```

   or create `~/.angel-one/credentials.json` with `api_key`, `client_code`,
   `pin`, `totp_secret`, then run `chmod 600 ~/.angel-one/credentials.json`.
4. Ask Claude to **"log in to Angel One"**. Without a stored TOTP secret, give it
   the 6-digit code from your authenticator. The session token is saved in
   `~/.angel-one/session.json` (0600) and lasts until 05:00 IST.

---

## The eleven skills

| skill | job |
| --- | --- |
| `angel-scanner` | Scans NIFTY 50-500 for 20-day breakouts, bull flags, 20-DMA reclaims, oversold bounces and opening-range breakouts |
| `angel-news` | NSE corporate announcements, results board meetings ahead, Yahoo headlines, today's move |
| `angel-entry` | Watches a setup bar by bar and triggers on a 5-min close above the opening range or your level |
| `angel-exit` | Stop (range mid/low, %, price, ATR) and target (R or price), tick-rounded, flat by 15:00 |
| `angel-timemachine` | 10,000 replays from the stock's own 5-min bars, plus the same rule re-run on every past session |
| `angel-budget` | Whole shares inside your max loss *including charges*, position cap and cash buffer; your rules live here |
| `angel-risk` | PASS/BLOCK: stop, max loss, R:R, daily loss limit, trades/day, entry window, circuits, T2T stocks, duplicates |
| `angel-broker` | Angel One login, tickets, your recorded yes, paper ledger, live orders with SL-M at the broker, journal |
| `angel-alerts` | Price, % move, time and opening-bell alerts; NSE hours, 2026 holidays, Muhurat session |
| `angel-analyst` | Last ~5 quarters from NSE results filings: revenue, EBITDA, profit, margins, EPS, YoY/QoQ, next results date |
| `angel-insider` | Promoter/director buys and sells disclosed under SEBI PIT, alerting once per filing |

## One trade, start to finish

```
scanner -> news -> entry -> exit -> timemachine -> budget -> risk -> broker   (one trade)
alerts + broker manage: stop, target, flat by 15:00                            (while it is open)
news / analyst / insider                                                       (any time)
```

Talk to Claude in plain words: *"scan Nifty 200 for opening range breakouts"*,
*"any news on the list?"*, *"watch RELIANCE and tell me when to get in"*,
*"plan the exit"*, *"run the time machine"*, *"size it, I risk ₹500 a trade"*,
*"check it"*, *"place it"*. Everything is saved in an `angel-trader/` folder in
your project.

## Your rules

Defaults: capital ₹1,00,000, max loss ₹500 a trade, daily loss limit ₹1,500,
3 trades a day, reward:risk 1.5, position cap 50%, 10% cash buffer, entry window
09:30-14:30, flat by 15:00, no leverage, no shorts, no F&O. Change them in plain
words (*"set my max loss to ₹750 and capital to ₹2 lakh"*) or edit
`angel-trader/config.json`. Every setting is listed in
[`skills/angel-budget/config.example.json`](skills/angel-budget/config.example.json).

## Safety

- **Paper first.** Angel One has no paper account, so the built-in ledger is the
  practice account: fills on real prices, 0.05% slippage, estimated charges.
- **No trade without your yes.** An entry needs `angel-risk` to PASS that exact
  order in the last 15 minutes and your typed yes for that order in the last 10
  minutes.
- **Live is two switches you set:** `"paper": false` **and** `"live_enabled": true`
  in `angel-trader/config.json`.
- **Stop at the broker.** Live, an SL-M stop-loss is placed at Angel One right
  after the fill, so it works even if Claude is not running. The target and the
  flat-by exit are run by the broker's `manage` command, which must be running.
  Angel One's 15:15 auto square-off is the backstop.
- Credentials never go in the project folder or the chat.

## Data sources

| what | with Angel One login | without |
| --- | --- | --- |
| prices, candles | SmartAPI, real time | Yahoo Finance, ~15 min delayed |
| filings, results, insider trades | NSE public JSON | same |
| orders | SmartAPI (only when live is on) | paper ledger |

## Status

Built and tested offline: synthetic data, and a fake SmartAPI for the live order
path. The live Angel One, NSE and Yahoo endpoints were not reachable from the
build environment, so check the first real login, quote and paper trade before
relying on it. NSE and Yahoo endpoints are unofficial and can change or block
scripted access.

## Fine print

Not investment advice. SEBI's study of FY23 found about 7 in 10 individual
intraday traders in the equity cash segment lost money. The Time Machine is a
simulation from about 60 sessions, not a prediction. A stop is a plan, not a
guarantee: gaps and circuits can fill it far from its price. Charges are
estimates from Angel One's published rates; your contract note is the real
number. Intraday gains are taxed as speculative business income; this is not
tax advice.

MIT licence. Structure modelled on
[Jakeschincariol/day-trader-skill](https://github.com/Jakeschincariol/day-trader-skill)
(MIT), rewritten for NSE and Angel One.
