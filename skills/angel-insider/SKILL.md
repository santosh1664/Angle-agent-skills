---
name: angel-insider
description: >-
  Insider Tracker for NSE companies, the Indian answer to tracking
  politicians' trades. Reads the insider-trading disclosures companies file
  with NSE under SEBI's Prohibition of Insider Trading (PIT) Regulations:
  promoters, promoter group, directors, KMP and designated employees buying
  or selling. Turns them into clean rows (who, category, buy or sell,
  shares, ₹ crore, average price, trade dates, filing time, days to
  disclose), filters to open-market buys and sells by default, alerts once
  per new filing, and flags companies on the watchlist or in positions. Use
  when the user says "are promoters buying", "insider trading", "insider
  buys", "promoter selling", "did the promoter buy TCS", "track insider
  trades", "PIT disclosures", "alert me when insiders file", or
  "who's buying their own stock".
argument-hint: "[scan | new] [--symbol SYM] [--who promoters] [--mode buy]"
---

# angel-insider

Company insiders in India must disclose their trades: to the company within
2 trading days, and the company to the exchange within 2 trading days after
that (SEBI PIT Regulations, Reg. 7(2)). NSE publishes them. This reads those
filings fast and cleanly.

It is fast; it is not early. By the time anyone can read a filing the trade is
days old. These are public disclosures, not inside information. Say that
every time.

```bash
python3 "${CLAUDE_SKILL_DIR}/pit.py" scan                                   # last 7 days, all companies
python3 "${CLAUDE_SKILL_DIR}/pit.py" scan --days 30 --symbol TCS
python3 "${CLAUDE_SKILL_DIR}/pit.py" scan --who promoters --mode buy --min-value 1   # >= ₹1 cr
python3 "${CLAUDE_SKILL_DIR}/pit.py" scan --include-all                     # + pledges, ESOPs, gifts, inter-se
python3 "${CLAUDE_SKILL_DIR}/pit.py" new                                    # only filings not seen before
```

`${CLAUDE_SKILL_DIR}` is this skill's folder. Seen filings are remembered in
`angel-trader/pit-seen.json`. `--who`: promoters, directors (incl. KMP),
employees, all.

## Reading the rows

- Default is **open-market** purchases and sales only. Pledges, ESOP
  allotments, gifts and inter-se transfers between promoter entities move a
  lot of shares without telling you much; `--include-all` shows them.
- A promoter buying in the open market with their own money is the rarer and
  usually more meaningful signal. Insiders sell for many reasons (tax, a
  house, diversification).
- `lag d` = days from the last trade date to the exchange filing.
- `*` marks a company on the watchlist or in an open position: lead with
  those.

## Keeping watch

For "alert me when insiders file", offer a scheduled task that runs `new`
(optionally with `--who promoters --mode buy`) a few times a day and reports
only new rows. NSE sometimes blocks scripted access; if it fails, say so and
try later, or point to nseindia.com, Corporate Filings, Insider Trading.

Bulk and block deals and SAST (takeover-code) disclosures are separate NSE
filings and are not covered here.

Not investment advice.
