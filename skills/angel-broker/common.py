"""Shared helpers for the Angel One trader skills.

Standard library only (Python 3.8+). Every skill folder carries an identical
copy of this file, so each skill runs on its own.

Data sources:
  * Angel One SmartAPI (real time, needs your login)  -> apiconnect.angelone.in
  * Yahoo Finance chart / spark / RSS (free, delayed)  -> query1/2.finance.yahoo.com
  * NSE public JSON (announcements, results, PIT)      -> www.nseindia.com/api
  * NSE archives (symbol lists)                        -> nsearchives.nseindia.com

Credentials are read from environment variables or ~/.angel-one/credentials.json
and the session token lives in ~/.angel-one/session.json (chmod 600), never in
the project folder and never printed.
"""

import base64
import datetime as _dt
import gzip
import hashlib
import hmac
from http import cookiejar
import json
import math
import os
import struct
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

VERSION = "1.0.0"

# --------------------------------------------------------------------------
# time and the NSE calendar
# --------------------------------------------------------------------------

IST = _dt.timezone(_dt.timedelta(hours=5, minutes=30), "IST")

# NSE equity segment trading holidays (weekdays). Source: NSE circular for
# 2026 (15 holidays + Maharashtra municipal election day, 15 Jan 2026).
# 2027 is not published yet: add dates to "extra_holidays" in config.json.
NSE_HOLIDAYS = {
    "2026-01-15": "Municipal Corporation Election - Maharashtra",
    "2026-01-26": "Republic Day",
    "2026-03-03": "Holi",
    "2026-03-26": "Shri Ram Navami",
    "2026-03-31": "Shri Mahavir Jayanti",
    "2026-04-03": "Good Friday",
    "2026-04-14": "Dr. Baba Saheb Ambedkar Jayanti",
    "2026-05-01": "Maharashtra Day",
    "2026-05-28": "Bakri Id",
    "2026-06-26": "Muharram",
    "2026-09-14": "Ganesh Chaturthi",
    "2026-10-02": "Mahatma Gandhi Jayanti",
    "2026-10-20": "Dussehra",
    "2026-11-10": "Diwali Balipratipada",
    "2026-11-24": "Prakash Gurpurb Sri Guru Nanak Dev",
    "2026-12-25": "Christmas",
}
# Weekend days with a special session. Timings are announced by NSE circular;
# set them in config.json "special_sessions" once known.
SPECIAL_SESSIONS = {"2026-11-08": "Diwali Muhurat Trading (timings by NSE circular)"}

PRE_OPEN = _dt.time(9, 0)
OPEN = _dt.time(9, 15)
CLOSE = _dt.time(15, 30)


def now_ist():
    """Current time in IST. ANGEL_NOW="YYYY-MM-DD HH:MM" pins it (replays, tests)."""
    fixed = os.environ.get("ANGEL_NOW")
    if fixed:
        return parse_ist(fixed)
    return _dt.datetime.now(IST)


def parse_ist(text):
    text = text.strip().replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return _dt.datetime.strptime(text[:19], fmt).replace(tzinfo=IST)
        except ValueError:
            pass
    raise ValueError("cannot read time %r (use YYYY-MM-DD HH:MM, IST)" % text)


def hhmm(text):
    h, m = text.split(":")
    return _dt.time(int(h), int(m))


def at(day, t):
    return _dt.datetime.combine(day, t).replace(tzinfo=IST)


def holidays(cfg=None):
    h = dict(NSE_HOLIDAYS)
    for d in (cfg or {}).get("extra_holidays", []):
        h[d] = "holiday (config)"
    return h


def is_trading_day(day, cfg=None):
    key = day.isoformat()
    if key in holidays(cfg):
        return False
    if day.weekday() >= 5:
        return False
    return True


def next_trading_day(day, cfg=None, include=False):
    d = day if include else day + _dt.timedelta(days=1)
    for _ in range(30):
        if is_trading_day(d, cfg):
            return d
        d += _dt.timedelta(days=1)
    return d


def prev_trading_day(day, cfg=None):
    d = day - _dt.timedelta(days=1)
    for _ in range(30):
        if is_trading_day(d, cfg):
            return d
        d -= _dt.timedelta(days=1)
    return d


def market_status(now=None, cfg=None):
    """Return dict(state, detail, next_open) for NSE cash market."""
    now = now or now_ist()
    day = now.date()
    t = now.time()
    if not is_trading_day(day, cfg):
        why = holidays(cfg).get(day.isoformat()) or ("weekend" if day.weekday() >= 5 else "closed")
        if day.isoformat() in SPECIAL_SESSIONS:
            why += "; special session: " + SPECIAL_SESSIONS[day.isoformat()]
        nxt = next_trading_day(day, cfg)
        return {"state": "closed", "detail": why, "next_open": at(nxt, OPEN)}
    if t < PRE_OPEN:
        return {"state": "closed", "detail": "before pre-open", "next_open": at(day, OPEN)}
    if t < OPEN:
        return {"state": "pre-open", "detail": "pre-open order collection 9:00-9:08, opens 9:15",
                "next_open": at(day, OPEN)}
    if t < CLOSE:
        return {"state": "open", "detail": "continuous trading until 15:30", "next_open": None}
    nxt = next_trading_day(day, cfg)
    return {"state": "closed", "detail": "after the close", "next_open": at(nxt, OPEN)}


# --------------------------------------------------------------------------
# files and config
# --------------------------------------------------------------------------

def data_dir():
    d = os.environ.get("ANGEL_TRADER_DIR") or os.path.join(os.getcwd(), "angel-trader")
    os.makedirs(d, exist_ok=True)
    return d


def path(*parts):
    p = os.path.join(data_dir(), *parts)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    return p


def load_json(name, default=None):
    p = name if os.path.isabs(name) else path(name)
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default
    except json.JSONDecodeError as e:
        die("%s is not valid JSON: %s" % (p, e))


def save_json(name, obj):
    p = name if os.path.isabs(name) else path(name)
    os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False, default=str)
        f.write("\n")
    os.replace(tmp, p)
    return p


DEFAULT_CONFIG = {
    "capital": 100000,              # INR you are willing to trade with
    "max_loss_per_trade": 500,      # INR lost if the stop fills at its price
    "daily_loss_limit": 1500,       # INR: sum of today's risk + realised losses
    "max_trades_per_day": 3,
    "max_position_pct": 50,         # one position <= this % of capital (exposure)
    "max_order_value": 100000,      # INR, hard cap on any single order
    "cash_buffer_pct": 10,          # keep this % of capital unused
    "min_reward_risk": 1.5,
    "mis_leverage": 1,              # intraday leverage you allow yourself (1 = none)
    "entry_window": ["09:30", "14:30"],
    "flat_by": "15:00",             # Angel One auto square-off for equity MIS is 15:15
    "exchange": "NSE",
    "product": "INTRADAY",
    "paper": True,                  # paper ledger; live needs paper=false AND live_enabled=true
    "live_enabled": False,
    "target_at_broker": False,      # see angel-broker SKILL.md before turning on
    "allow_short": False,
    "allow_fno": False,
    "blocked": [],
    "data_source": "auto",          # auto | smartapi | yahoo
    "slippage_pct": 0.05,           # paper fills: market orders slip this % against you
    "extra_holidays": [],
    "universe": "nifty500",         # nifty50 | nifty100 | nifty200 | nifty500 | all
    "watchlist": [],
    "charges": {                    # estimates, check your contract notes
        "brokerage_flat": 20.0, "brokerage_pct": 0.1, "brokerage_min": 5.0,
        "stt_sell_pct": 0.025, "exchange_txn_pct": 0.00297, "sebi_per_crore": 10.0,
        "stamp_buy_pct": 0.003, "gst_pct": 18.0,
    },
}


def load_config():
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    user = load_json("config.json", {}) or {}
    for k, v in user.items():
        if isinstance(v, dict) and isinstance(cfg.get(k), dict):
            cfg[k].update(v)
        else:
            cfg[k] = v
    return cfg


def die(msg, code=2):
    sys.stderr.write("error: %s\n" % msg)
    sys.exit(code)


# --------------------------------------------------------------------------
# money and prices
# --------------------------------------------------------------------------

def inr(x, decimals=2):
    """Indian digit grouping: 1234567.5 -> Rs 12,34,567.50."""
    if x is None:
        return "-"
    neg = x < 0
    x = abs(x)
    s = ("%." + str(decimals) + "f") % x
    whole, _, frac = s.partition(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join(groups + [tail])
    out = "₹" + whole + ("." + frac if frac else "")
    return "-" + out if neg else out


def tick_floor(p, tick=0.05):
    return round(math.floor(round(p / tick, 6)) * tick, 2)


def tick_ceil(p, tick=0.05):
    return round(math.ceil(round(p / tick, 6)) * tick, 2)


def tick_round(p, tick=0.05):
    return round(round(p / tick) * tick, 2)


def charges(side, qty, price, cfg):
    """Estimated statutory + brokerage charges (INR) for one executed equity intraday order."""
    c = cfg["charges"]
    turnover = qty * price
    brokerage = max(min(c["brokerage_flat"], turnover * c["brokerage_pct"] / 100.0), c["brokerage_min"])
    txn = turnover * c["exchange_txn_pct"] / 100.0
    sebi = turnover * c["sebi_per_crore"] / 1e7
    stt = turnover * c["stt_sell_pct"] / 100.0 if side == "SELL" else 0.0
    stamp = turnover * c["stamp_buy_pct"] / 100.0 if side == "BUY" else 0.0
    gst = (brokerage + txn + sebi) * c["gst_pct"] / 100.0
    return round(brokerage + txn + sebi + stt + stamp + gst, 2)


def fingerprint(order):
    keys = ("tradingsymbol", "transactiontype", "ordertype", "quantity", "price",
            "triggerprice", "producttype", "exchange", "date")
    blob = json.dumps({k: str(order.get(k, "")) for k in keys}, sort_keys=True)
    return hashlib.sha1(blob.encode()).hexdigest()[:12]


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------

BROWSER_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0"
_last_call = {}


def throttle(key, per_second):
    gap = 1.0 / per_second
    last = _last_call.get(key, 0)
    wait = last + gap - time.time()
    if wait > 0:
        time.sleep(wait)
    _last_call[key] = time.time()


def _read(resp):
    raw = resp.read()
    if resp.headers.get("Content-Encoding") == "gzip" or raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    return raw


def http(url, method="GET", headers=None, body=None, params=None, timeout=20,
         retries=2, opener=None):
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    data = None
    if body is not None:
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
    h = {"User-Agent": BROWSER_UA, "Accept": "*/*", "Accept-Encoding": "gzip"}
    h.update(headers or {})
    last = None
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, data=data, headers=h, method=method)
        try:
            with (opener.open(req, timeout=timeout) if opener else
                  urllib.request.urlopen(req, timeout=timeout)) as r:
                return _read(r)
        except urllib.error.HTTPError as e:
            last = e
            if e.code in (429, 500, 502, 503, 504) and attempt < retries:
                time.sleep(1.5 * (attempt + 1))
                continue
            try:
                detail = _read(e)[:300].decode("utf-8", "replace")
            except Exception:
                detail = ""
            raise NetError("HTTP %s from %s %s" % (e.code, url.split("?")[0], detail.strip()))
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
            last = e
            if attempt < retries:
                time.sleep(1.0 * (attempt + 1))
                continue
    raise NetError("cannot reach %s (%s)" % (url.split("?")[0], last))


class NetError(Exception):
    pass


def http_json(url, **kw):
    raw = http(url, **kw)
    try:
        return json.loads(raw.decode("utf-8"))
    except ValueError:
        raise NetError("not JSON from %s: %r" % (url.split("?")[0], raw[:120]))


# --------------------------------------------------------------------------
# test fixtures (ANGEL_FIXTURES=dir) -- offline replays and the unit tests
# --------------------------------------------------------------------------

def fixture(name):
    """Load <ANGEL_FIXTURES>/<name>.json(.gz) or <name>.xml/.txt if present."""
    d = os.environ.get("ANGEL_FIXTURES")
    if not d:
        return None
    for ext in (".json", ".json.gz", ".xml", ".txt"):
        p = os.path.join(d, name + ext)
        if os.path.exists(p):
            opener = gzip.open if p.endswith(".gz") else open
            with opener(p, "rt", encoding="utf-8") as f:
                return json.load(f) if ".json" in ext else f.read()
    return None


def offline():
    return bool(os.environ.get("ANGEL_FIXTURES"))


# --------------------------------------------------------------------------
# Angel One SmartAPI
# --------------------------------------------------------------------------

SMART_ROOT = "https://apiconnect.angelone.in"
ROUTES = {
    "login": ("POST", "/rest/auth/angelbroking/user/v1/loginByPassword"),
    "logout": ("POST", "/rest/secure/angelbroking/user/v1/logout"),
    "token": ("POST", "/rest/auth/angelbroking/jwt/v1/generateTokens"),
    "profile": ("GET", "/rest/secure/angelbroking/user/v1/getProfile"),
    "rms": ("GET", "/rest/secure/angelbroking/user/v1/getRMS"),
    "place": ("POST", "/rest/secure/angelbroking/order/v1/placeOrder"),
    "modify": ("POST", "/rest/secure/angelbroking/order/v1/modifyOrder"),
    "cancel": ("POST", "/rest/secure/angelbroking/order/v1/cancelOrder"),
    "orderbook": ("GET", "/rest/secure/angelbroking/order/v1/getOrderBook"),
    "tradebook": ("GET", "/rest/secure/angelbroking/order/v1/getTradeBook"),
    "positions": ("GET", "/rest/secure/angelbroking/order/v1/getPosition"),
    "ltp": ("POST", "/rest/secure/angelbroking/order/v1/getLtpData"),
    "quote": ("POST", "/rest/secure/angelbroking/market/v1/quote/"),
    "candles": ("POST", "/rest/secure/angelbroking/historical/v1/getCandleData"),
    "search": ("POST", "/rest/secure/angelbroking/order/v1/searchScrip"),
}
# requests per second (Angel One's published limits, kept a little under)
RATE = {"candles": 2.5, "quote": 8, "ltp": 8, "place": 8, "cancel": 8, "modify": 8,
        "orderbook": 0.9, "positions": 0.9, "tradebook": 0.9, "rms": 1.8, "search": 0.9,
        "login": 0.9, "profile": 2, "token": 0.9, "logout": 0.9}
SCRIP_MASTER = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
INTERVALS = {"1m": "ONE_MINUTE", "3m": "THREE_MINUTE", "5m": "FIVE_MINUTE", "10m": "TEN_MINUTE",
             "15m": "FIFTEEN_MINUTE", "30m": "THIRTY_MINUTE", "1h": "ONE_HOUR", "1d": "ONE_DAY"}
# Angel One returns at most ~500 candles per request; size chunks to fit.
CHUNK_DAYS = {"1m": 1, "3m": 3, "5m": 6, "10m": 12, "15m": 19, "30m": 38, "1h": 70, "1d": 450}


def secrets_dir():
    d = os.environ.get("ANGEL_HOME") or os.path.join(os.path.expanduser("~"), ".angel-one")
    os.makedirs(d, exist_ok=True)
    try:
        os.chmod(d, 0o700)
    except OSError:
        pass
    return d


def credentials():
    c = {
        "api_key": os.environ.get("ANGEL_API_KEY"),
        "client_code": os.environ.get("ANGEL_CLIENT_CODE"),
        "pin": os.environ.get("ANGEL_PIN"),
        "totp_secret": os.environ.get("ANGEL_TOTP_SECRET"),
    }
    p = os.path.join(secrets_dir(), "credentials.json")
    if os.path.exists(p):
        try:
            with open(p) as f:
                filed = json.load(f)
            for k in c:
                c[k] = c[k] or filed.get(k)
        except (OSError, ValueError):
            pass
    return c


def totp_now(secret, when=None):
    """RFC 6238 TOTP (SHA1, 30 s, 6 digits) from the base32 secret Angel One shows at enable-TOTP."""
    key = base64.b32decode(secret.replace(" ", "").upper() + "=" * (-len(secret.replace(" ", "")) % 8))
    counter = int((when or time.time()) // 30)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    o = digest[-1] & 0x0F
    code = (struct.unpack(">I", digest[o:o + 4])[0] & 0x7FFFFFFF) % 1000000
    return "%06d" % code


class AngelError(Exception):
    def __init__(self, message, code=None):
        Exception.__init__(self, message)
        self.code = code


class SmartAPI:
    def __init__(self):
        self.creds = credentials()
        self.session_file = os.path.join(secrets_dir(), "session.json")
        self.session = None
        if os.path.exists(self.session_file):
            try:
                with open(self.session_file) as f:
                    self.session = json.load(f)
            except (OSError, ValueError):
                self.session = None

    # -- session -----------------------------------------------------------
    def configured(self):
        return bool(self.creds.get("api_key") and self.creds.get("client_code") and self.creds.get("pin"))

    def logged_in(self):
        s = self.session
        if not s or not s.get("jwt"):
            return False
        try:
            return parse_ist(s["expires"]) > now_ist()
        except (KeyError, ValueError):
            return False

    def headers(self, auth=True):
        h = {
            "Content-Type": "application/json", "Accept": "application/json",
            "X-UserType": "USER", "X-SourceID": "WEB",
            "X-ClientLocalIP": "127.0.0.1", "X-ClientPublicIP": "127.0.0.1",
            "X-MACAddress": "00:00:00:00:00:00",
            "X-PrivateKey": self.creds.get("api_key") or "",
        }
        if auth and self.session:
            h["Authorization"] = "Bearer " + self.session["jwt"]
        return h

    def login(self, totp=None):
        if not self.configured():
            raise AngelError("Angel One credentials missing: set ANGEL_API_KEY, ANGEL_CLIENT_CODE, "
                             "ANGEL_PIN (and ANGEL_TOTP_SECRET, or pass --totp) or fill "
                             "~/.angel-one/credentials.json")
        code = totp or (totp_now(self.creds["totp_secret"]) if self.creds.get("totp_secret") else None)
        if not code:
            raise AngelError("need a TOTP: pass --totp 123456 from your authenticator app, "
                             "or set ANGEL_TOTP_SECRET")
        throttle("login", RATE["login"])
        body = {"clientcode": self.creds["client_code"], "password": self.creds["pin"], "totp": code}
        r = http_json(SMART_ROOT + ROUTES["login"][1], method="POST", headers=self.headers(False), body=body)
        if not r.get("status"):
            raise AngelError("login failed: %s" % r.get("message"), r.get("errorcode"))
        d = r["data"]
        now = now_ist()
        # SmartAPI sessions end at the next 05:00 IST (Angel One resets tokens daily)
        exp = at(now.date() + _dt.timedelta(days=1 if now.time() >= _dt.time(5, 0) else 0), _dt.time(5, 0))
        self.session = {"jwt": d["jwtToken"].replace("Bearer ", ""), "refresh": d.get("refreshToken"),
                        "feed": d.get("feedToken"), "client_code": self.creds["client_code"],
                        "created": now.isoformat(), "expires": exp.strftime("%Y-%m-%d %H:%M")}
        with open(self.session_file, "w") as f:
            json.dump(self.session, f)
        try:
            os.chmod(self.session_file, 0o600)
        except OSError:
            pass
        return self.session

    def logout(self):
        if self.session:
            try:
                self.call("logout", {"clientcode": self.session.get("client_code")})
            except (AngelError, NetError):
                pass
        if os.path.exists(self.session_file):
            os.remove(self.session_file)
        self.session = None

    def ensure(self):
        if self.logged_in():
            return
        if self.configured() and self.creds.get("totp_secret"):
            self.login()
            return
        raise AngelError("not logged in to Angel One: run `ticket.py login` (angel-broker skill)")

    # -- calls -------------------------------------------------------------
    def call(self, route, body=None, _retry=True):
        method, p = ROUTES[route]
        throttle(route, RATE.get(route, 1))
        url = SMART_ROOT + p
        if method == "GET":
            r = http_json(url, headers=self.headers())
        else:
            r = http_json(url, method="POST", headers=self.headers(), body=body or {})
        if r.get("status") is False or (r.get("success") is False):
            code = r.get("errorcode") or r.get("errorCode")
            if _retry and code in ("AG8001", "AG8002", "AG8003", "AB1010") and self.creds.get("totp_secret"):
                self.login()
                return self.call(route, body, _retry=False)
            raise AngelError("%s: %s" % (route, r.get("message") or r), code)
        return r.get("data")

    def candles(self, token, interval, start, end, exchange="NSE"):
        out = []
        step = _dt.timedelta(days=CHUNK_DAYS[interval])
        cur = start
        while cur < end:
            stop = min(cur + step, end)
            data = self.call("candles", {"exchange": exchange, "symboltoken": str(token),
                                         "interval": INTERVALS[interval],
                                         "fromdate": cur.strftime("%Y-%m-%d %H:%M"),
                                         "todate": stop.strftime("%Y-%m-%d %H:%M")}) or []
            for row in data:
                ts = parse_ist(row[0][:19])
                out.append({"t": ts.isoformat(), "o": float(row[1]), "h": float(row[2]),
                            "l": float(row[3]), "c": float(row[4]), "v": float(row[5] or 0)})
            cur = stop
        seen, uniq = set(), []
        for b in sorted(out, key=lambda b: b["t"]):
            if b["t"] not in seen:
                seen.add(b["t"])
                uniq.append(b)
        return uniq

    def quote(self, tokens, exchange="NSE", mode="FULL"):
        rows = []
        tokens = [str(t) for t in tokens]
        for i in range(0, len(tokens), 50):
            d = self.call("quote", {"mode": mode, "exchangeTokens": {exchange: tokens[i:i + 50]}}) or {}
            rows.extend(d.get("fetched") or [])
        return rows


# --------------------------------------------------------------------------
# instruments (symbol -> Angel One token)
# --------------------------------------------------------------------------

def instruments(refresh=False):
    """NSE cash instruments from Angel One's scrip master, cached daily."""
    fx = fixture("instruments")
    if fx is not None:
        return fx
    cache = path("cache", "instruments-NSE.json")
    today = now_ist().date().isoformat()
    cur = load_json(cache)
    if cur and cur.get("date") == today and not refresh:
        return cur["symbols"]
    try:
        raw = json.loads(http(SCRIP_MASTER, timeout=90).decode("utf-8"))
    except NetError as e:
        if cur:
            sys.stderr.write("warning: using cached instrument list from %s (%s)\n" % (cur.get("date"), e))
            return cur["symbols"]
        raise
    syms = {}
    for r in raw:
        if r.get("exch_seg") != "NSE":
            continue
        s = r.get("symbol", "")
        if "-" not in s:
            continue
        base, series = s.rsplit("-", 1)
        if series not in ("EQ", "BE", "BZ", "SM", "ST"):
            continue
        tick = float(r.get("tick_size") or 5) / 100.0   # master lists tick in paise
        if base not in syms or series == "EQ":
            syms[base] = {"token": r["token"], "symbol": s, "name": r.get("name"), "series": series,
                          "tick": tick or 0.05, "lot": int(float(r.get("lotsize") or 1))}
    save_json(cache, {"date": today, "symbols": syms})
    return syms


def resolve(sym, required=True):
    sym = clean_symbol(sym)
    try:
        inst = instruments()
    except NetError as e:
        if required:
            die("cannot load the Angel One instrument list: %s" % e)
        return None
    hit = inst.get(sym)
    if not hit and required:
        die("%s is not an NSE cash-market symbol in Angel One's instrument list" % sym)
    return hit


def clean_symbol(sym):
    s = sym.strip().upper()
    for suf in (".NS", ".BO", "-EQ", "-BE"):
        if s.endswith(suf):
            s = s[: -len(suf)]
    return s.replace("NSE:", "")


# --------------------------------------------------------------------------
# Yahoo Finance (free, delayed ~15 min for NSE)
# --------------------------------------------------------------------------

def ysym(sym):
    s = clean_symbol(sym)
    return s if s.startswith("^") else s + ".NS"


YAHOO_INTERVAL = {"1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m", "1h": "60m", "1d": "1d"}


def _yahoo_bars(js):
    res = (js.get("chart") or {}).get("result") or []
    if not res:
        err = (js.get("chart") or {}).get("error")
        raise NetError("Yahoo: %s" % (err or "no data"))
    r = res[0]
    ts = r.get("timestamp") or []
    q = (r.get("indicators") or {}).get("quote", [{}])[0]
    bars = []
    for i, t in enumerate(ts):
        o, h, l, c = (q.get(k, [None] * len(ts))[i] for k in ("open", "high", "low", "close"))
        if None in (o, h, l, c):
            continue
        v = (q.get("volume") or [0] * len(ts))[i] or 0
        bars.append({"t": _dt.datetime.fromtimestamp(t, IST).isoformat(), "o": round(o, 2),
                     "h": round(h, 2), "l": round(l, 2), "c": round(c, 2), "v": float(v)})
    return bars, r.get("meta") or {}


def yahoo_chart(sym, interval="5m", days=5):
    rng = "%dd" % days if days <= 60 else ("1y" if days <= 365 else "2y")
    js = http_json("https://query2.finance.yahoo.com/v8/finance/chart/" + urllib.parse.quote(ysym(sym)),
                   params={"interval": YAHOO_INTERVAL[interval], "range": rng, "includePrePost": "false"})
    return _yahoo_bars(js)


def yahoo_spark(symbols, interval="5m", rng="1d"):
    """Batch close series for up to 20 symbols per call: {SYM: [(iso, close), ...]}."""
    out = {}
    syms = [ysym(s) for s in symbols]
    for i in range(0, len(syms), 20):
        throttle("yahoo", 4)
        js = http_json("https://query1.finance.yahoo.com/v7/finance/spark",
                       params={"symbols": ",".join(syms[i:i + 20]), "interval": interval, "range": rng})
        for r in (js.get("spark") or {}).get("result") or []:
            resp = (r.get("response") or [{}])[0]
            ts = resp.get("timestamp") or []
            closes = ((resp.get("indicators") or {}).get("quote") or [{}])[0].get("close") or []
            key = clean_symbol(r.get("symbol", ""))
            out[key] = [(_dt.datetime.fromtimestamp(t, IST).isoformat(), c) for t, c in zip(ts, closes)
                        if c is not None]
    return out


# --------------------------------------------------------------------------
# one data facade: SmartAPI when logged in, Yahoo otherwise
# --------------------------------------------------------------------------

def _source(cfg):
    want = cfg.get("data_source", "auto")
    if want == "yahoo":
        return "yahoo", None
    api = SmartAPI()
    if api.logged_in() or (want == "smartapi"):
        if want == "smartapi" and not api.logged_in():
            api.ensure()
        return "smartapi", api
    return "yahoo", None


def bars(sym, interval="5m", days=5, cfg=None, end=None):
    """Return (bars, source). Bars: dicts t(ISO IST), o,h,l,c,v oldest first."""
    sym = clean_symbol(sym)
    fx = fixture("bars-%s-%s" % (sym, interval))
    if fx is not None:
        b = fx["bars"] if isinstance(fx, dict) else fx
        if end:
            b = [x for x in b if x["t"] <= end.isoformat()]
        return b, "fixture"
    if offline():
        raise NetError("offline: no fixture bars-%s-%s" % (sym, interval))
    cfg = cfg or load_config()
    src, api = _source(cfg)
    if src == "smartapi":
        inst = resolve(sym)
        stop = end or now_ist()
        start = at((stop - _dt.timedelta(days=int(days * 1.6) + 3)).date(), _dt.time(9, 0))
        return api.candles(inst["token"], interval, start, stop), "angel-one"
    throttle("yahoo", 4)
    b, _ = yahoo_chart(sym, interval, days if interval != "1d" else max(days, 30))
    if end:
        b = [x for x in b if x["t"] <= end.isoformat()]
    return b, "yahoo (delayed)"


def quotes(symbols, cfg=None):
    """{SYM: {ltp, open, high, low, prev_close, upper_circuit, lower_circuit, volume, source}}."""
    fx = fixture("quotes")
    out = {}
    syms = [clean_symbol(s) for s in symbols]
    if fx is not None:
        return {s: fx[s] for s in syms if s in fx}
    cfg = cfg or load_config()
    src, api = _source(cfg)
    if src == "smartapi":
        inst = instruments()
        tok = {inst[s]["token"]: s for s in syms if s in inst}
        for r in api.quote(list(tok)):
            s = tok.get(str(r.get("symbolToken")))
            if not s:
                continue
            out[s] = {"ltp": r.get("ltp"), "open": r.get("open"), "high": r.get("high"), "low": r.get("low"),
                      "prev_close": r.get("close"), "upper_circuit": r.get("upperCircuit"),
                      "lower_circuit": r.get("lowerCircuit"), "volume": r.get("tradeVolume"),
                      "time": now_ist().isoformat(), "source": "angel-one"}
        return out
    for s in syms:
        try:
            throttle("yahoo", 4)
            b, meta = yahoo_chart(s, "1d", 5)
        except NetError as e:
            sys.stderr.write("warning: no quote for %s (%s)\n" % (s, e))
            continue
        last = b[-1] if b else {}
        out[s] = {"ltp": meta.get("regularMarketPrice") or last.get("c"),
                  "open": last.get("o"), "high": last.get("h"), "low": last.get("l"),
                  "prev_close": meta.get("chartPreviousClose") if len(b) < 2 else b[-2]["c"],
                  "upper_circuit": None, "lower_circuit": None, "volume": last.get("v"),
                  "time": now_ist().isoformat(), "source": "yahoo (delayed)"}
    return out


# --------------------------------------------------------------------------
# NSE public JSON (needs a browser-like session with cookies)
# --------------------------------------------------------------------------

_nse_opener = None


def nse_get(endpoint, params=None, fixture_name=None):
    fx = fixture(fixture_name) if fixture_name else None
    if fx is not None:
        return fx
    if offline():
        raise NetError("offline (ANGEL_FIXTURES set) and no fixture %s" % fixture_name)
    global _nse_opener
    hdr = {"User-Agent": BROWSER_UA, "Accept": "application/json, text/plain, */*",
           "Accept-Language": "en-US,en;q=0.9", "Referer": "https://www.nseindia.com/"}
    if _nse_opener is None:
        jar = cookiejar.CookieJar()
        _nse_opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        try:
            http("https://www.nseindia.com/", headers=hdr, opener=_nse_opener, retries=1)
        except NetError:
            pass
    throttle("nse", 2)
    raw = http("https://www.nseindia.com/api/" + endpoint, headers=hdr, params=params,
               opener=_nse_opener, retries=2)
    try:
        return json.loads(raw.decode("utf-8"))
    except ValueError:
        raise NetError("NSE returned a non-JSON page for %s (it may be blocking scripted access; "
                       "try again in a minute)" % endpoint)


NSE_INDEX_LISTS = {
    "nifty50": "https://nsearchives.nseindia.com/content/indices/ind_nifty50list.csv",
    "nifty100": "https://nsearchives.nseindia.com/content/indices/ind_nifty100list.csv",
    "nifty200": "https://nsearchives.nseindia.com/content/indices/ind_nifty200list.csv",
    "nifty500": "https://nsearchives.nseindia.com/content/indices/ind_nifty500list.csv",
    "all": "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv",
}


# --------------------------------------------------------------------------
# bar maths
# --------------------------------------------------------------------------

def bar_time(b):
    return _dt.datetime.fromisoformat(b["t"]).astimezone(IST)


def split_sessions(bs):
    days = {}
    for b in bs:
        days.setdefault(bar_time(b).date().isoformat(), []).append(b)
    return days


def session(bs, day):
    return [b for b in bs if bar_time(b).date() == day and OPEN <= bar_time(b).time() < CLOSE]


def bar_minutes(bs):
    if len(bs) < 2:
        return 5
    gaps = [(bar_time(bs[i + 1]) - bar_time(bs[i])).total_seconds() / 60 for i in range(min(len(bs) - 1, 20))]
    gaps = [g for g in gaps if g > 0]
    return int(min(gaps)) if gaps else 5


def opening_range(day_bars, minutes=15):
    """High/low of bars starting before 9:15 + minutes. None if incomplete."""
    end = (_dt.datetime.combine(_dt.date(2000, 1, 1), OPEN) + _dt.timedelta(minutes=minutes)).time()
    inside = [b for b in day_bars if OPEN <= bar_time(b).time() < end]
    if not inside:
        return None
    step = bar_minutes(day_bars)
    last_end = bar_time(inside[-1]) + _dt.timedelta(minutes=step)
    if last_end.time() < end:
        return None
    hi = max(b["h"] for b in inside)
    lo = min(b["l"] for b in inside)
    return {"high": hi, "low": lo, "mid": round((hi + lo) / 2, 2), "end": end.strftime("%H:%M"),
            "bars": len(inside)}


def sma(xs, n):
    return sum(xs[-n:]) / n if len(xs) >= n else None


def rsi(closes, n=14):
    if len(closes) < n + 1:
        return None
    gains = losses = 0.0
    for i in range(1, n + 1):
        d = closes[i] - closes[i - 1]
        gains += max(d, 0)
        losses += max(-d, 0)
    ag, al = gains / n, losses / n
    for i in range(n + 1, len(closes)):
        d = closes[i] - closes[i - 1]
        ag = (ag * (n - 1) + max(d, 0)) / n
        al = (al * (n - 1) + max(-d, 0)) / n
    if al == 0:
        return 100.0
    return 100 - 100 / (1 + ag / al)


def atr(bs, n=14):
    if len(bs) < n + 1:
        return None
    trs = []
    for i in range(1, len(bs)):
        h, l, pc = bs[i]["h"], bs[i]["l"], bs[i - 1]["c"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    a = sum(trs[:n]) / n
    for tr in trs[n:]:
        a = (a * (n - 1) + tr) / n
    return a


# --------------------------------------------------------------------------
# misc
# --------------------------------------------------------------------------

DISCLAIMER = ("Not investment advice. Most intraday traders in India lose money "
              "(SEBI study, FY23: 7 in 10 individual intraday traders made a loss).")


def table(rows, headers):
    cols = [[str(h)] + [str(r[i]) for r in rows] for i, h in enumerate(headers)]
    w = [max(len(x) for x in c) for c in cols]
    lines = ["  ".join(str(h).ljust(w[i]) for i, h in enumerate(headers)),
             "  ".join("-" * x for x in w)]
    for r in rows:
        lines.append("  ".join(str(v).ljust(w[i]) for i, v in enumerate(r)))
    return "\n".join(lines)


def emit_json(obj):
    sys.stdout.write(json.dumps(obj, indent=2, default=str, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    st = market_status(cfg=load_config())
    print("angel-trader common %s | NSE %s: %s" % (VERSION, st["state"], st["detail"]))
