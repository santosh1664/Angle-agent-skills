#!/usr/bin/env python3
"""Insider Tracker: promoter and director trades disclosed under SEBI (PIT) Regulations.

  pit.py scan                         # last 7 days, all companies, market buys/sells
  pit.py scan --days 30 --symbol TCS
  pit.py scan --who promoters --mode buy --min-value 1      # >= Rs 1 crore promoter market buys
  pit.py new                          # only filings not seen before (alert once each)
  pit.py scan --json

Source: NSE corporate filings, Insider Trading (SEBI PIT Reg. 7(2)). Insiders
disclose to the company within 2 trading days and the company to the exchange
within 2 trading days, so these are days old by the time anyone reads them.
Public filings, not inside information. Flags companies on your watchlist or in
your positions.
"""
import argparse
import datetime as dt
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402

WHO = {
    "promoters": r"promoter",
    "directors": r"director|key managerial|\bkmp\b",
    "employees": r"employee|designated",
    "all": r".",
}


def parse_date(s):
    for fmt in ("%d-%b-%Y %H:%M", "%d-%b-%Y %H:%M:%S", "%d-%b-%Y", "%d-%m-%Y"):
        try:
            return dt.datetime.strptime((s or "").strip(), fmt)
        except ValueError:
            pass
    return None


def fetch(days, symbol=None):
    end = C.now_ist().date()
    start = end - dt.timedelta(days=days)
    params = {"index": "equities", "from_date": start.strftime("%d-%m-%Y"), "to_date": end.strftime("%d-%m-%Y")}
    if symbol:
        params["symbol"] = symbol
    js = C.nse_get("corporates-pit", params, fixture_name="nse-pit" + ("-" + symbol if symbol else ""))
    return js.get("data", []) if isinstance(js, dict) else js


def normalise(r):
    qty = C_float(r.get("secAcq"))
    val = C_float(r.get("secVal"))
    to = parse_date(r.get("acqtoDt"))
    filed = parse_date(r.get("date")) or parse_date(r.get("intimDt"))
    mode = (r.get("acqMode") or "").strip()
    typ = (r.get("tdpTransactionType") or "").strip()
    side = "buy" if re.search(r"buy|purchase|acqui", typ + " " + mode, re.I) else \
        "sell" if re.search(r"sell|sale|dispos", typ + " " + mode, re.I) else typ.lower() or "other"
    return {
        "id": "%s|%s|%s|%s|%s" % (r.get("symbol"), r.get("acqName"), r.get("acqtoDt"), qty, r.get("date")),
        "symbol": (r.get("symbol") or "").strip(), "company": (r.get("company") or "").strip(),
        "person": (r.get("acqName") or "").strip(), "category": (r.get("personCategory") or "").strip(),
        "security": (r.get("secType") or "").strip(), "side": side, "type": typ, "mode": mode,
        "qty": qty, "value_cr": round(val / 1e7, 3) if val else None,
        "avg_price": round(val / qty, 2) if val and qty else None,
        "after_pct": r.get("afterAcqSharesPer"), "trade_from": r.get("acqfromDt"), "trade_to": r.get("acqtoDt"),
        "filed": filed.strftime("%Y-%m-%d %H:%M") if filed else r.get("date"),
        "lag_days": (filed.date() - to.date()).days if filed and to else None,
        "xbrl": r.get("xbrl"),
    }


def C_float(x):
    try:
        return float(str(x).replace(",", ""))
    except (TypeError, ValueError):
        return 0.0


def mine():
    s = set()
    wl = C.load_json("watchlist.json") or {}
    s |= {i["symbol"] for i in wl.get("items", [])}
    led = C.load_json("ledger.json") or {}
    s |= {p["symbol"] for p in led.get("positions", [])}
    s |= {C.clean_symbol(x) for x in C.load_config().get("watchlist", [])}
    return s


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["scan", "new"])
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--symbol")
    ap.add_argument("--who", choices=sorted(WHO), default="all")
    ap.add_argument("--mode", choices=["buy", "sell", "any"], default="any")
    ap.add_argument("--include-all", action="store_true",
                    help="by default only Market Purchase / Market Sale; this adds pledges, ESOPs, gifts, "
                         "inter-se transfers")
    ap.add_argument("--min-value", type=float, default=0.0, help="crore INR")
    ap.add_argument("--limit", type=int, default=40)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    sym = C.clean_symbol(a.symbol) if a.symbol else None
    try:
        rows = [normalise(r) for r in fetch(a.days, sym)]
    except C.NetError as e:
        C.die("NSE insider-trading data unavailable: %s" % e)
    rx = re.compile(WHO[a.who], re.I)
    keep = []
    for r in rows:
        if not rx.search(r["category"]):
            continue
        if not a.include_all and not re.search(r"market (purchase|sale)", r["mode"], re.I):
            continue
        if a.mode != "any" and r["side"] != a.mode:
            continue
        if (r["value_cr"] or 0) < a.min_value:
            continue
        keep.append(r)
    keep.sort(key=lambda r: r["filed"] or "", reverse=True)
    seen = C.load_json("pit-seen.json", {}) or {}
    if a.cmd == "new":
        keep = [r for r in keep if r["id"] not in seen]
    for r in keep:
        seen.setdefault(r["id"], C.now_ist().isoformat())
    C.save_json("pit-seen.json", seen)
    flagged = mine()
    if a.json:
        C.emit_json([dict(r, yours=r["symbol"] in flagged) for r in keep[: a.limit]])
        return
    if not keep:
        print("no matching insider filings%s" % (" since the last check" if a.cmd == "new" else ""))
        return
    rows = [[("* " if r["symbol"] in flagged else "") + r["symbol"], r["person"][:28], r["category"][:22],
             r["side"].upper(), "{:,.0f}".format(r["qty"]), "-" if r["value_cr"] is None else "%.2f" % r["value_cr"],
             "-" if r["avg_price"] is None else "%.2f" % r["avg_price"], r["trade_to"] or "-", r["filed"] or "-",
             "-" if r["lag_days"] is None else r["lag_days"]] for r in keep[: a.limit]]
    print(C.table(rows, ["symbol", "who", "category", "side", "shares", "Rs cr", "avg px", "traded to",
                         "filed", "lag d"]))
    buys = sum(r["value_cr"] or 0 for r in keep if r["side"] == "buy")
    sells = sum(r["value_cr"] or 0 for r in keep if r["side"] == "sell")
    print("\n%d filings (%s shown); market buys Rs %.1f cr, sells Rs %.1f cr. * = on your watchlist or in a position." % (
        len(keep), min(len(keep), a.limit), buys, sells))
    print("Public disclosures under SEBI PIT, days after the trade. Insiders sell for many reasons; a buy with "
          "their own money is the rarer signal, and still not a reason on its own.")


if __name__ == "__main__":
    main()
