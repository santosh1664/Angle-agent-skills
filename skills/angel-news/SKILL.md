---
name: angel-news
description: >-
  News Monitor for NSE stocks. For every stock on the watchlist, plan or open
  positions, reads NSE corporate announcements (exchange filings: results,
  order wins, management changes, SEBI actions, ratings, pledges, deals),
  NSE board-meeting intimations (results dates in the next 14 days) and
  Yahoo Finance headlines, plus how far each stock is from yesterday's
  close. Shows only what is new since the last check, newest first, in IST,
  tagged, never repeating an item. Use when the user says "any news on
  RELIANCE", "why is this moving", "what's the news on my watchlist",
  "morning briefing", "pre-market news", "any announcements", "did anything
  break", "when are results", or after angel-scanner finds setups.
argument-hint: "[--tickers SYM ...] [--hours N]"
---

# angel-news

A chart can look perfect and still be about to gap on results, an SEBI order
or a promoter pledge. Before a setup becomes a trade, this reads the feeds
that carry those first and shows only what is new.

```bash
python3 "${CLAUDE_SKILL_DIR}/news.py"                               # watchlist + plan + positions
python3 "${CLAUDE_SKILL_DIR}/news.py" --tickers RELIANCE TCS --hours 12
python3 "${CLAUDE_SKILL_DIR}/news.py" --all                         # repeat items already shown
python3 "${CLAUDE_SKILL_DIR}/news.py" --no-yahoo --json
```

`${CLAUDE_SKILL_DIR}` is this skill's folder. Seen items are remembered in
`angel-trader/news-seen.json`.

## Reporting

- Lead with anything that changes the trade: a **results board meeting**
  today or before the trade ends, an SEBI/regulatory or legal item, a halt
  or surveillance (ASM/GSM) note, a big order or deal.
- Then the price move vs yesterday's close for each stock, then the items:
  time (IST), source, title, one line of text, link. Read the filing PDF
  (the link) before summarising anything that matters; the NSE text line is
  short.
- Tags are keyword guesses (results, dividend, order/contract, deal,
  fund-raise, management, regulatory, legal, rating, analyst, pledge,
  insider, halt, macro). Say they are approximate.
- A results day is the classic gap risk. A day trade that is flat by 15:00
  avoids the overnight gap but not a results announcement during market
  hours.

## When a feed fails

NSE's site blocks scripted access at times (it needs a browser-like session;
the script handles cookies and backs off). If NSE fails, say so, report the
rest, and suggest trying again in a minute or checking nseindia.com
"Corporate Announcements" directly. Yahoo headlines for Indian stocks are
thinner than for US stocks.

Not investment advice.
