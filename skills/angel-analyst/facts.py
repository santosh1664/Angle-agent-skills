#!/usr/bin/env python3
"""Results Analyst: a company's reported quarterly numbers from NSE filings, lined up.

  facts.py TCS                  # last ~5 quarters: revenue, EBITDA, PBT, profit, margins, EPS
  facts.py TCS INFY --json
  facts.py RELIANCE --next      # only: is a results board meeting coming up?

Source: NSE results comparison (the figures companies file with the exchange under
SEBI LODR Reg. 33). NSE reports amounts in Rs lakh; shown here in Rs crore.
Which statement (standalone or consolidated) NSE lines up can vary by company:
check the filing PDF before relying on one number.
"""
import argparse
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402


def num(r, *keys):
    for k in keys:
        v = r.get(k)
        if v not in (None, "", "-"):
            try:
                return float(str(v).replace(",", ""))
            except ValueError:
                pass
    return None


def quarters(js):
    rows = js.get("resCmpData") or []
    bank = (js.get("bankNonBnking") or "N").upper() == "Y"
    out = []
    for r in rows:
        try:
            end = dt.datetime.strptime(r.get("re_to_dt", ""), "%d-%b-%Y").date()
        except ValueError:
            continue
        lakh = lambda *k: (lambda v: None if v is None else v / 100.0)(num(r, *k))  # noqa: E731 lakh -> crore
        rev = lakh("re_net_sale", "re_int_earned", "re_total_inc", "re_tot_inc")
        pbt = lakh("re_pro_loss_bef_tax", "re_pro_loss_bef_tax_sum")
        interest = lakh("re_int_new", "re_int_expd") or 0.0
        dep = lakh("re_depr_und_exp") or 0.0
        oth = lakh("re_oth_inc_new", "re_oth_inc") or 0.0
        np_ = lakh("re_net_profit", "re_con_pro_loss", "re_proloss_ord_act")
        ebitda = (pbt + interest + dep - oth) if (pbt is not None and not bank) else None
        out.append({
            "quarter_end": end.isoformat(), "label": "Q%d FY%02d" % (((end.month - 4) % 12) // 3 + 1,
                                                                     (end.year + (1 if end.month > 3 else 0)) % 100),
            "audited": r.get("re_res_type") == "A", "revenue_cr": rev, "total_income_cr": lakh("re_total_inc", "re_tot_inc"),
            "ebitda_cr": ebitda, "pbt_cr": pbt, "net_profit_cr": np_,
            "eps": num(r, "re_basic_eps_for_cont_dic_opr", "re_basic_eps", "re_bsc_eps_bfr_exi"),
            "ebitda_margin": round(100 * ebitda / rev, 1) if ebitda is not None and rev else None,
            "net_margin": round(100 * np_ / rev, 1) if np_ is not None and rev else None,
            "bank": bank,
        })
    out.sort(key=lambda q: q["quarter_end"])
    by_end = {q["quarter_end"]: q for q in out}
    for i, q in enumerate(out):
        prev = out[i - 1] if i else None
        e = dt.date.fromisoformat(q["quarter_end"])
        ly = by_end.get(e.replace(year=e.year - 1).isoformat()) if not (e.month == 2 and e.day == 29) else None
        for key in ("revenue_cr", "net_profit_cr", "eps"):
            q[key + "_qoq"] = pct(q[key], prev[key]) if prev else None
            q[key + "_yoy"] = pct(q[key], ly[key]) if ly else None
    return out


def pct(a, b):
    if a is None or b in (None, 0):
        return None
    return round(100 * (a - b) / abs(b), 1)


def f(x, d=0):
    return "-" if x is None else ("{:,.%df}" % d).format(x)


def g(x):
    return "" if x is None else " (%+.1f%%)" % x


def upcoming(sym, today):
    try:
        js = C.nse_get("corporate-board-meetings", {"index": "equities", "symbol": sym}, fixture_name="nse-bm-" + sym)
    except C.NetError as e:
        return None, str(e)
    rows = js if isinstance(js, list) else (js.get("data") or [])
    hits = []
    for r in rows:
        try:
            d = dt.datetime.strptime(r.get("bm_date", ""), "%d-%b-%Y").date()
        except ValueError:
            continue
        if d >= today and "result" in (r.get("bm_purpose") or "").lower():
            hits.append({"date": d.isoformat(), "purpose": r.get("bm_purpose", "")})
    return sorted(hits, key=lambda h: h["date"]), None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("symbols", nargs="+")
    ap.add_argument("--next", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    today = C.now_ist().date()
    out = {}
    for s in [C.clean_symbol(x) for x in a.symbols]:
        nxt, err = upcoming(s, today)
        rec = {"symbol": s, "next_results": nxt, "warning": err}
        if not a.next:
            try:
                js = C.nse_get("results-comparision", {"symbol": s}, fixture_name="nse-results-" + s)
                rec["quarters"] = quarters(js)
            except C.NetError as e:
                rec["error"] = str(e)
        out[s] = rec
        if a.json:
            continue
        print("\n%s" % s)
        if nxt:
            for h in nxt:
                days = (dt.date.fromisoformat(h["date"]) - today).days
                print("  NEXT RESULTS: board meeting %s (in %d days): %s" % (h["date"], days, h["purpose"][:120]))
        elif nxt == []:
            print("  no results board meeting announced on NSE yet")
        if err:
            print("  (board meetings unavailable: %s)" % err)
        if rec.get("error"):
            print("  results unavailable: %s" % rec["error"])
            continue
        qs = rec.get("quarters") or []
        if not qs:
            continue
        rows = [[q["label"], q["quarter_end"], "A" if q["audited"] else "U", f(q["revenue_cr"]) + g(q["revenue_cr_yoy"]),
                 f(q["ebitda_cr"]), "-" if q["ebitda_margin"] is None else "%.1f%%" % q["ebitda_margin"],
                 f(q["net_profit_cr"]) + g(q["net_profit_cr_yoy"]),
                 "-" if q["net_margin"] is None else "%.1f%%" % q["net_margin"], f(q["eps"], 2) + g(q["eps_yoy"])]
                for q in qs]
        print(C.table(rows, ["quarter", "ended", "A/U", "revenue Rs cr (YoY)", "EBITDA", "margin",
                             "net profit (YoY)", "net margin", "EPS (YoY)"]))
        last, prev = qs[-1], (qs[-2] if len(qs) > 1 else None)
        lines = []
        if last["revenue_cr_yoy"] is not None:
            lines.append("revenue %+.1f%% YoY" % last["revenue_cr_yoy"])
        if last["revenue_cr_qoq"] is not None:
            lines.append("%+.1f%% QoQ" % last["revenue_cr_qoq"])
        if last["net_profit_cr_yoy"] is not None:
            lines.append("net profit %+.1f%% YoY" % last["net_profit_cr_yoy"])
        if prev and last["ebitda_margin"] is not None and prev["ebitda_margin"] is not None:
            lines.append("EBITDA margin %.1f%% vs %.1f%% last quarter" % (last["ebitda_margin"], prev["ebitda_margin"]))
        if lines:
            print("  latest (%s): %s" % (last["label"], ", ".join(lines)))
        if last["bank"]:
            print("  bank/NBFC format: revenue is interest earned; EBITDA is not meaningful")
    if a.json:
        C.emit_json(out)


if __name__ == "__main__":
    main()
