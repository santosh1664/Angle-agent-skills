---
name: angel-analyst
description: >-
  Results Analyst for NSE-listed companies. Reads the quarterly results the
  company filed with NSE (SEBI LODR Reg. 33) and lines up the last ~5
  quarters: revenue, EBITDA and margin, profit before tax, net profit and
  margin, EPS, each against the same quarter a year earlier and the quarter
  before, in ₹ crore with Indian fiscal quarters (Q1 = Apr-Jun). Also says
  whether a results board meeting is coming up. Reads an earnings call
  transcript or investor presentation when the user pastes or attaches one.
  Use when the user says "how were TCS's results", "analyse the results",
  "what changed this quarter", "is revenue growing", "compare margins",
  "Q2 numbers", "sum up the concall", "when are results", "does it report
  this week", or before trading a stock around its results.
argument-hint: "[SYMBOLS] [--next]"
---

# angel-analyst

Results move Indian stocks more than anything else on the calendar, and the
press release leads with the best number. This reads the figures the company
actually filed with the exchange, lines them up quarter by quarter and says
plainly what changed. For a day trader it answers two questions: what did the
last results say, and do the next ones fall inside this trade?

```bash
python3 "${CLAUDE_SKILL_DIR}/facts.py" TCS
python3 "${CLAUDE_SKILL_DIR}/facts.py" HDFCBANK INFY --json
python3 "${CLAUDE_SKILL_DIR}/facts.py" RELIANCE --next          # just the next results date
```

`${CLAUDE_SKILL_DIR}` is this skill's folder.

## Reading the numbers

- Source: NSE's results comparison for the symbol (about the last 5
  quarters). NSE reports in ₹ lakh; the script shows ₹ crore.
- EBITDA here = profit before tax + finance cost + depreciation - other
  income. It is a derived figure; say "approximately".
- YoY needs the same quarter last year in NSE's list; QoQ uses the quarter
  before. Indian fiscal year: Q1 Apr-Jun, Q2 Jul-Sep, Q3 Oct-Dec, Q4 Jan-Mar
  (FY27 = Apr 2026-Mar 2027).
- A/U = audited / unaudited.
- Banks and NBFCs report a different format: revenue is interest earned and
  EBITDA is not meaningful. Say so.
- NSE's line-up can be standalone or consolidated depending on the company.
  For anything that matters, open the results PDF from NSE (angel-news shows
  the filing link) and check which statement the numbers are from.

## Reporting

Lead with what changed: revenue and profit growth YoY and QoQ, the margin
trend, EPS. Then the table. Then the next results date and whether it falls
inside the planned trade. If the user pastes a concall transcript or
attaches an investor presentation, read it and add: guidance, demand
commentary, margin drivers, and anything management avoided answering,
quoting sparingly.

Not investment advice.
