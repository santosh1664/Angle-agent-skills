#!/usr/bin/env python3
"""News Monitor: what is new on every stock you watch, and how far each has moved.

  news.py                              # watchlist + plan + open positions
  news.py --tickers RELIANCE TCS --hours 12
  news.py --all                        # include items already shown
  news.py --no-nse | --no-yahoo        # skip a feed
  news.py --json

Feeds: NSE corporate announcements (exchange filings under SEBI LODR Reg. 30),
NSE board-meeting intimations (results dates ahead), Yahoo Finance headlines.
Shows only what is new since the last check, newest first, in IST, tagged.
"""
import argparse
import datetime as dt
import email.utils
import os
import re
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402

TAGS = [
    ("results", r"financial result|quarterly result|\bresults?\b|earnings|profit|revenue|q[1-4]\s?fy|ebitda"),
    ("dividend", r"dividend|record date"),
    ("bonus/split", r"\bbonus\b|split|sub-division"),
    ("buyback", r"buy-?back"),
    ("order/contract", r"order win|bags? .*order|letter of award|\bLoA\b|contract|order (received|inflow)"),
    ("deal", r"acqui|merger|amalgamation|demerger|stake|joint venture|\bJV\b|scheme of arrangement"),
    ("fund-raise", r"\bQIP\b|preferential|rights issue|fund rais|allotment|NCD|debenture"),
    ("management", r"resign|appoint|\bCEO\b|\bCFO\b|managing director|key managerial|cessation"),
    ("regulatory", r"\bSEBI\b|penalty|show cause|tax demand|GST|income tax|enforcement|\bED\b|CBI|order of"),
    ("legal", r"litigation|court|tribunal|NCLT|arbitration|insolvency"),
    ("rating", r"credit rating|\bCRISIL\b|\bICRA\b|\bCARE\b|India Ratings|downgrade|upgrade"),
    ("analyst", r"target price|brokerage|buy rating|sell rating|overweight|underweight|initiates coverage"),
    ("pledge", r"pledge|encumbrance"),
    ("insider", r"\bSAST\b|insider|promoter (buy|sell|purchase)|regulation 29|regulation 7"),
    ("halt", r"suspen|trading halt|circuit|surveillance|\bASM\b|\bGSM\b"),
    ("macro", r"\bRBI\b|repo rate|inflation|\bCPI\b|budget|\bGDP\b|monsoon|crude"),
]


def tag(text):
    t = text or ""
    return [name for name, rx in TAGS if re.search(rx, t, re.I)] or ["general"]


def nse_announcements(sym, start, end):
    js = C.nse_get("corporate-announcements",
                   {"index": "equities", "symbol": sym, "from_date": start.strftime("%d-%m-%Y"),
                    "to_date": end.strftime("%d-%m-%Y")}, fixture_name="nse-ann-" + sym)
    rows = js if isinstance(js, list) else (js.get("data") or [])
    out = []
    for r in rows:
        when = None
        for k, fmt in (("sort_date", "%Y-%m-%d %H:%M:%S"), ("an_dt", "%d-%b-%Y %H:%M:%S")):
            try:
                when = dt.datetime.strptime(r.get(k) or "", fmt).replace(tzinfo=C.IST)
                break
            except ValueError:
                pass
        title = (r.get("desc") or "").strip()
        body = (r.get("attchmntText") or "").strip()
        out.append({"id": "nse:%s" % (r.get("seq_id") or r.get("attchmntFile") or title + str(when)),
                    "symbol": sym, "source": "NSE filing", "time": when, "title": title or body[:90],
                    "text": body, "link": r.get("attchmntFile"), "tags": tag(title + " " + body)})
    return out


def nse_board_meetings(sym, today):
    js = C.nse_get("corporate-board-meetings", {"index": "equities", "symbol": sym},
                   fixture_name="nse-bm-" + sym)
    rows = js if isinstance(js, list) else (js.get("data") or [])
    ahead = []
    for r in rows:
        try:
            d = dt.datetime.strptime(r.get("bm_date", ""), "%d-%b-%Y").date()
        except ValueError:
            continue
        if today <= d <= today + dt.timedelta(days=14):
            ahead.append({"date": d.isoformat(), "purpose": (r.get("bm_purpose") or "").strip(),
                          "results": bool(re.search(r"result", r.get("bm_purpose") or "", re.I))})
    return sorted(ahead, key=lambda x: x["date"])


def yahoo_headlines(sym):
    raw = C.fixture("yahoo-rss-" + sym)
    if raw is None:
        if C.offline():
            return []
        raw = C.http("https://feeds.finance.yahoo.com/rss/2.0/headline",
                     params={"s": C.ysym(sym), "region": "IN", "lang": "en-IN"}).decode("utf-8", "replace")
    out = []
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return out
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        link = (it.findtext("link") or "").strip()
        pub = it.findtext("pubDate")
        try:
            when = email.utils.parsedate_to_datetime(pub).astimezone(C.IST) if pub else None
        except (TypeError, ValueError):
            when = None
        out.append({"id": "yahoo:" + (link or title), "symbol": sym, "source": "Yahoo Finance", "time": when,
                    "title": title, "text": (it.findtext("description") or "").strip(), "link": link,
                    "tags": tag(title)})
    return out


def tickers_from_files(cfg):
    syms = []
    wl = C.load_json("watchlist.json") or {}
    syms += [i["symbol"] for i in wl.get("items", [])]
    pl = C.load_json("plan.json") or {}
    if pl.get("symbol"):
        syms.append(pl["symbol"])
    led = C.load_json("ledger.json") or {}
    syms += [p["symbol"] for p in led.get("positions", [])]
    syms += cfg.get("watchlist", [])
    seen, out = set(), []
    for s in syms:
        s = C.clean_symbol(s)
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tickers", nargs="*")
    ap.add_argument("--hours", type=float, default=24)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--no-nse", action="store_true")
    ap.add_argument("--no-yahoo", action="store_true")
    ap.add_argument("--max", type=int, default=25, help="watchlist symbols to check at most")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    cfg = C.load_config()
    now = C.now_ist()
    syms = [C.clean_symbol(s) for s in a.tickers] if a.tickers else tickers_from_files(cfg)[: a.max]
    if not syms:
        C.die("no tickers: pass --tickers or build a watchlist with angel-scanner")
    since = now - dt.timedelta(hours=a.hours)
    seen = C.load_json("news-seen.json", {}) or {}
    items, meetings, errors = [], {}, []
    for s in syms:
        if not a.no_nse:
            try:
                items += nse_announcements(s, since.date(), now.date())
                bm = nse_board_meetings(s, now.date())
                if bm:
                    meetings[s] = bm
            except C.NetError as e:
                errors.append("%s NSE: %s" % (s, e))
        if not a.no_yahoo:
            try:
                items += yahoo_headlines(s)
            except C.NetError as e:
                errors.append("%s Yahoo: %s" % (s, e))
    items = [i for i in items if i["time"] is None or i["time"] >= since]
    fresh = [i for i in items if a.all or i["id"] not in seen]
    fresh.sort(key=lambda i: i["time"] or now, reverse=True)
    try:
        moves = C.quotes(syms, cfg)
    except (C.NetError, C.AngelError) as e:
        moves = {}
        errors.append("prices: %s" % e)
    for i in fresh:
        seen[i["id"]] = now.isoformat()
    C.save_json("news-seen.json", seen)
    if a.json:
        C.emit_json({"items": fresh, "board_meetings": meetings, "moves": moves, "errors": errors})
        return
    print("News since %s IST for %s" % (since.strftime("%d %b %H:%M"), ", ".join(syms)))
    for s in syms:
        q = moves.get(s) or {}
        if q.get("ltp") and q.get("prev_close"):
            ch = 100 * (float(q["ltp"]) / float(q["prev_close"]) - 1)
            print("  %-12s %.2f  %+.2f%% vs yesterday's close  (%s)" % (s, float(q["ltp"]), ch, q.get("source")))
    for s, bm in meetings.items():
        for m in bm:
            flag = "RESULTS " if m["results"] else ""
            print("  !! %s board meeting %s %s: %s" % (s, m["date"], flag, m["purpose"][:140]))
    if not fresh:
        print("\nnothing new.")
    for i in fresh:
        when = i["time"].strftime("%d %b %H:%M") if i["time"] else "--"
        print("\n[%s] %s  %s  (%s; %s)" % (when, i["symbol"], i["title"][:150], i["source"], ", ".join(i["tags"])))
        if i["text"] and i["text"] != i["title"]:
            print("    " + i["text"][:240])
        if i["link"]:
            print("    " + i["link"])
    for e in errors:
        print("warning: " + e)
    if any(m["results"] for bm in meetings.values() for m in bm):
        print("\nA results date inside your holding period can gap the stock past any stop. A day trade is "
              "flat by %s, so only the results day itself matters." % cfg["flat_by"])


if __name__ == "__main__":
    main()
