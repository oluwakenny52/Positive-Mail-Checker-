"""breach.py - breach exposure and combo freshness.  v13.86

THE BROWSER IS THE ADDRESS PATH
-------------------------------
The keyless endpoint answers with a Cloudflare 401 to a plain urllib request, so
the address half is a real Chromium page from Playwright, driven through the
app's OWN proxy pool. The JSON endpoint is navigated to directly and its body
read from the response - no DOM scraping, no screenshot, no persistent profile
to go stale. `page.goto` answers 200 with the payload, 404 for "not in any
breach", and anything else means the challenge has to be earned.

THE WARM PAGE IS WHAT EARNS IT
------------------------------
A challenge cannot be solved on the JSON endpoint, because Chromium renders a
401 body as a bare block of JSON - there is no interstitial, no Turnstile
widget and no cookie to win. That is what made the first edition report
"challenge (http 401)" and then a re-fetch 115 ms later, on every proxy and on
DIRECT alike.

So when the endpoint refuses, the slot navigates the HTML page at the origin,
which DOES carry the widget, waits there for the wall to clear, and only then
re-fetches the endpoint from inside the same page - same origin, same cookies,
now including the clearance the solve produced. A slot records that it holds
clearance and goes straight to the endpoint next time, so a warmed proxy pays
the warm navigation once rather than once per item; clearance is dropped again
the moment a re-fetch still fails.

PAGES ARE TIED TO WORKERS
-------------------------
There is no page-count control. A run of N workers keeps at most N pages, one
per worker slot, and each slot is REUSED: the same context and page serve item
after item, reset to about:blank with its cookies cleared between them. The
Chromium process behind a slot is launched once per worker for the whole batch,
so a 500-item run pays for N browsers, not 500.

A slot recycles itself on its own terms - after SLOT_USES_MAX uses, or after
SLOT_FAILS_MAX consecutive failed attempts, or when the next attempt wants a
different proxy (the proxy is bound to the context, so a swap is a new context
on the same browser). Recycling is local: the item that was in flight is
already recorded, so a stuck or challenged page can never lose a finished
result and can never hold the queue.

THE DRAW IS RANDOM
------------------
Drawing `pool_lines()[:3]` gave every key the same first three nodes, so one
node carried the entire run. Each attempt now draws a RANDOM node from the whole
tier-ordered pool, never one already tried for that item, and a node that fails
twice hard is skipped for the rest of the run. The `rotate` switch turns the
draw off and walks the tier order instead, which is what you want when the pool
is tiny and a deterministic sweep is easier to read in the trace. DIRECT is the
last attempt in both modes, never the first.

THE PASSWORD HALF
-----------------
Pwned Passwords k-anonymity, unchanged and keyless: the SHA-1 is computed
locally, 5 of its 40 characters leave the box, and the 35 kept characters are
matched locally against the padded range response. It never touches the address
path and it never sees a proxy.

WHAT AN INPUT LINE CAN BE
-------------------------
    email:password   both halves
    email            the address half only
    password         the password half only (a line with no '@')

parse_lines() decides that per line, so one paste can carry all three shapes.

THE BANDS ARE ABOUT FRESHNESS, NOT COUNT
----------------------------------------
    NEW       password unseen, or exposure inside 365 days, or a stealer log
    PARTIAL   password seen 1-9999 times, or exposure inside 730 days
    OLD       password seen 10000+ times, or only old breaches
    CLEAN     password unseen and the address in no readable source
    UNKNOWN   nothing readable - the only honest answer when every attempt failed

count 0 and count None are different facts and `read` says which.

HTML IS WRITTEN AS \x3c ESCAPES
-------------------------------
Every angle bracket in a string literal is written \x3c / \x3e and every entity
is built from chr(38). A paste that strips tags out of literals - which eats a
raw tag down to a bare newline and turns a raw entity into a no-op - cannot
break either form.

Isolation: cache, trace and state resolve through the pinned owner, which is the
unlocked hash, so each is one file per user. The proxy pool is the owner's own
proxies.txt. Plain module, NOT frame-gated, no Streamlit. EVERY public function
swallows.
"""

import concurrent.futures as _cf
import hashlib
import json
import os
import random
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

BREACH_VERSION = "v13.86"

_HERE = os.path.dirname(os.path.abspath(__file__))
_PW_DIR = os.path.join(_HERE, ".pw-browsers")
_PW_SENTINEL = os.path.join(_PW_DIR, ".installed")
os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", _PW_DIR)

HIBP_BASE = "https://haveibeenpwned.com"
UNIFIED = HIBP_BASE + "/unifiedsearch/%s"
ACCOUNT = HIBP_BASE + "/account/%s"
CATALOGUE_URL = HIBP_BASE + "/api/v3/breaches"
PW_RANGE = "https://api.pwnedpasswords.com/range/%s"
KEY_ENV = "HIBP_API_KEY"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": HIBP_BASE + "/",
    "Origin": HIBP_BASE,
    "sec-ch-ua": '"Chromium";v="131", "Not_A Brand";v="24"',
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
}

# "challenge" alone is in here because the refused endpoint answers with a short
# JSON body and that word is in it; the rest are the interstitial's own wording.
CHALLENGE_MARKS = (
    "just a moment", "performing security verification", "checking your browser",
    "cf-challenge", "attention required", "verify you are human",
    "security service to protect", "verifying...", "challenge",
)
CLEAN_MARKS = ("no pwnage", "good news", "not been pwned", "no breaches found")

TURNSTILE_SELECTORS = (
    "iframe[src*='challenges.cloudflare.com']",
    "div#challenge-stage iframe",
    "iframe[title*='challenge' i]",
    "iframe[title*='turnstile' i]",
)

JS_FETCH = """async (u) => {
  try {
    const r = await fetch(u, {credentials: 'include',
                              headers: {'Accept': 'application/json'}});
    let t = '';
    try { t = await r.text(); } catch (e) { t = ''; }
    return {status: r.status, body: t};
  } catch (e) { return {status: 0, body: String(e)}; }
}"""

STEALTH_JS = ("Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
              "Object.defineProperty(navigator,'languages',{get:()=>['en-US','en']});"
              "Object.defineProperty(navigator,'plugins',{get:()=>[1,2,3,4,5]});"
              "window.chrome={runtime:{}};")

CHROME_ARGS = ["--no-sandbox", "--no-zygote", "--disable-dev-shm-usage",
               "--disable-gpu", "--disable-blink-features=AutomationControlled",
               "--disable-extensions", "--disable-background-networking",
               "--disable-sync", "--mute-audio", "--no-first-run",
               "--no-default-browser-check"]

NAV_TIMEOUT = 25000
CHALLENGE_WAIT = 15.0
HTTP_TIMEOUT = 15.0
TRIES = 4

# A page slot's own terms. Uses bounds the memory a long run can build up on one
# context; fails bounds how long a page that keeps timing out is kept.
SLOT_USES_MAX = 25
SLOT_FAILS_MAX = 2

# A node skipped for the rest of the run after this many hard fails, so a 500
# item batch does not keep drawing a node the provider has already dropped.
BAD_AFTER = 2

# Markers only - read by the page's stale-module guard, not by the flow.
RESULT_WAIT = 15.0

CACHE_NAME = "breach_cache.json"
CACHE_TTL = 6 * 3600.0
CACHE_MAX = 4000

TRACE_MAX = 1500
TRACE_NAME = "breach_trace.jsonl"
TRACE_FILE_MAX = 4000
TRACE_DUMP_MAX = 500

DESC_MAX = 1200
PAGE_HTML_MAX = 60000
PAGE_TEXT_MAX = 20000

DELAY_DEFAULT = 0.0
DELAY_MAX = 20.0

PW_NEW_MAX = 0
PW_PARTIAL_MAX = 9999
CORPUS_NEW_DAYS = 365
BREACH_PARTIAL_DAYS = 730

RANK = {"NEW": 0, "PARTIAL": 1, "OLD": 2}
WEIGHTS = {"NEW": 1.0, "PARTIAL": 0.5, "OLD": 0.15}

CORPORA = frozenset({
    "stealer logs", "synthient stealer log", "synthient credential stuffing",
    "alien txtbase", "combolists posted to telegram", "naz.api", "collection #1",
    "anti public", "exploit.in", "onliner spambot", "big combolist", "cit0day",
    "emotet", "qakbot", "redline", "raccoon", "vidar", "lumma",
})

_cfg = {"timeout": 240.0, "delay": DELAY_DEFAULT, "rotate": True,
        "workers": 3, "pool": None}
_lock = threading.RLock()
_pool_cache = {"ts": 0.0, "lines": []}
_pool_ttl = 30.0
_cursor = [0]
_bad = {}
_slots = {}

_tls = threading.local()
_lasts = {}

_pw_lock = threading.Lock()
_pw_thread = None
_pw_state = {"state": "unknown", "error": "", "started": 0.0, "finished": 0.0}
_pw_missing = ""

_trace_lock = threading.Lock()
_trace_file_lock = threading.Lock()
_trace = []
_trace_seq = [0]
_trace_writes = [0]

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")
_MAILTO_RE = re.compile(r"^mailto:\s*", re.IGNORECASE)
_TAG_RE = re.compile("\x3c[^\x3e]+\x3e")
_ISO_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
           "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}
_D_MONTH_Y = re.compile(r"\b(\d{1,2})\s+([A-Za-z]{3,9})\.?\s+(\d{4})\b")

# Entities, built so no "&" sequence exists in the source to be decoded.
_AMP = chr(38) + "amp;"
_LT = chr(38) + "lt;"
_GT = chr(38) + "gt;"
_QUOT = chr(38) + "quot;"

_PAGE_CSS = ("\x3cstyle\x3e"
             "body{font-family:system-ui,sans-serif;background:#0b1020;"
             "color:#e6ebff;padding:16px}h1{font-size:1.05rem}"
             "h2{font-size:.9rem}table{border-collapse:collapse;width:100%;"
             "font-size:.8rem}td,th{border:1px solid #2a3350;padding:5px;"
             "text-align:left;vertical-align:top}th{background:#141b30}"
             ".c{color:#fcd34d}\x3c/style\x3e")


def _is_cancelled(cancel):
    try:
        return bool(cancel is not None and cancel.is_set())
    except Exception:
        return False


def _await(cancel, budget):
    """Marker kept for the page guard: a bounded wait helper."""
    end = time.time() + max(5.0, float(budget))
    while time.time() < end:
        if _is_cancelled(cancel):
            return None, True
        time.sleep(0.05)
    return None, False


# ---------------------------------------------------------------------------
# owner
# ---------------------------------------------------------------------------
def set_owner(prefix="") -> str:
    _tls.owner = str(prefix or "")
    return _tls.owner


def owner() -> str:
    return str(getattr(_tls, "owner", "") or "")


def _user_file(name) -> str:
    p = owner()
    if p:
        return "%s_%s" % (p, name) if name else p
    try:
        import auth
        return auth.user_file(name)
    except Exception:
        return name


def _dir_for(prefix, name) -> str:
    d = os.path.join("data", prefix, name)
    try:
        os.makedirs(d, exist_ok=True)
    except Exception:
        pass
    return d


def _user_dir(name) -> str:
    p = owner()
    if p:
        return _dir_for(p, name)
    try:
        import auth
        return auth.user_dir(name)
    except Exception:
        return _dir_for("anon", name)


# ---------------------------------------------------------------------------
# config
# ---------------------------------------------------------------------------
def configure(timeout=None, delay=None, rotate=None, workers=None, pool=None):
    with _lock:
        if timeout is not None:
            try:
                _cfg["timeout"] = max(60.0, float(timeout))
            except Exception:
                pass
        if delay is not None:
            try:
                _cfg["delay"] = max(0.0, min(DELAY_MAX, float(delay)))
            except Exception:
                pass
        if workers is not None:
            try:
                _cfg["workers"] = max(1, min(16, int(workers)))
            except Exception:
                pass
        if rotate is not None:
            _cfg["rotate"] = bool(rotate)
        if pool is not None:
            try:
                _cfg["pool"] = [str(p).strip() for p in pool if str(p).strip()]
            except Exception:
                _cfg["pool"] = None
            _pool_cache["ts"] = 0.0


def _cfg_get(key, default=None):
    snap = getattr(_tls, "cfg", None)
    if isinstance(snap, dict) and key in snap:
        return snap[key]
    with _lock:
        return _cfg.get(key, default)


def _snapshot_cfg() -> dict:
    with _lock:
        return {"timeout": float(_cfg["timeout"]), "delay": float(_cfg["delay"]),
                "rotate": bool(_cfg["rotate"]), "workers": int(_cfg["workers"]),
                "pool": _cfg.get("pool")}


def _pin_cfg(snap) -> None:
    _tls.cfg = snap if isinstance(snap, dict) else None


def _delay() -> float:
    try:
        return max(0.0, float(_cfg_get("delay", DELAY_DEFAULT)))
    except Exception:
        return DELAY_DEFAULT


def rotating() -> bool:
    return bool(_cfg_get("rotate", True))


def page_wanted(kind) -> bool:
    """Kept for the page's stale-module guard. Pages are always built now."""
    return True


def _api_key() -> str:
    try:
        return str(os.environ.get(KEY_ENV) or "").strip()
    except Exception:
        return ""


def key_present() -> bool:
    return bool(_api_key())


def key_hint() -> str:
    k = _api_key()
    if not k:
        return "no key needed - keyless browser + Pwned Passwords"
    return "key present (optional, %d chars)" % len(k)


# ---------------------------------------------------------------------------
# tracing
# ---------------------------------------------------------------------------
def _trace_path() -> str:
    p = _user_file(TRACE_NAME)
    if not p:
        return ""
    try:
        os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
    except Exception:
        pass
    return p


def _trace_to_file(ev):
    p = _trace_path()
    if not p:
        return
    try:
        with _trace_file_lock:
            with open(p, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(ev, ensure_ascii=False) + "\n")
            _trace_writes[0] += 1
            if _trace_writes[0] % 250:
                return
            with open(p, encoding="utf-8", errors="ignore") as fh:
                lines = fh.readlines()
            if len(lines) > TRACE_FILE_MAX:
                with open(p, "w", encoding="utf-8") as fh:
                    fh.writelines(lines[-TRACE_FILE_MAX:])
    except Exception:
        pass


def trace(level, step, detail="", email=""):
    try:
        now = time.time()
        with _trace_lock:
            _trace_seq[0] += 1
            ev = {"seq": _trace_seq[0], "ts": round(now, 3),
                  "clock": datetime.fromtimestamp(now).strftime("%H:%M:%S.%f")[:-3],
                  "level": str(level or "INFO")[:8].upper(),
                  "step": str(step or "")[:40],
                  "email": str(email or "")[:120],
                  "owner": owner(),
                  "detail": str(detail or "")[:600]}
            _trace.append(ev)
            if len(_trace) > TRACE_MAX:
                del _trace[:len(_trace) - TRACE_MAX]
        _trace_to_file(ev)
        return ev
    except Exception:
        return None


def trace_seq() -> int:
    with _trace_lock:
        return _trace_seq[0]


def trace_read(limit=200, since=0, skip=None):
    try:
        n = max(1, min(TRACE_MAX, int(limit or 200)))
        floor = int(since or 0)
    except Exception:
        n, floor = 200, 0
    want = owner()
    drop = tuple(skip or ())
    with _trace_lock:
        got = [e for e in _trace
               if e.get("seq", 0) > floor
               and (not want or e.get("owner") == want)
               and e.get("step") not in drop]
    return got[-n:]


def trace_text(limit=200, since=0, skip=None) -> str:
    rows = []
    for e in trace_read(limit=limit, since=since, skip=skip):
        rows.append("%s %-5s %-12s %-32s %s" % (
            e.get("clock", ""), e.get("level", ""), e.get("step", ""),
            e.get("email", "") or "-", e.get("detail", "")))
    return "\n".join(rows) if rows else "(nothing traced yet)"


def trace_dump() -> str:
    p = _trace_path()
    try:
        if p and os.path.exists(p):
            with open(p, encoding="utf-8", errors="ignore") as fh:
                lines = fh.readlines()
            return "".join(lines[-TRACE_DUMP_MAX:])
    except Exception:
        pass
    return trace_text(limit=TRACE_MAX) + "\n"


def trace_clear():
    p = _trace_path()
    try:
        if p and os.path.exists(p):
            os.remove(p)
    except Exception:
        pass
    want = owner()
    with _trace_lock:
        if want:
            _trace[:] = [e for e in _trace if e.get("owner") != want]
        else:
            _trace.clear()
        _trace_writes[0] = 0


# ---------------------------------------------------------------------------
# the binary
# ---------------------------------------------------------------------------
def _installed() -> bool:
    try:
        if not os.path.exists(_PW_SENTINEL):
            return False
        for entry in os.listdir(_PW_DIR):
            if entry.startswith("chromium"):
                return True
    except Exception:
        return False
    return False


def _install_now():
    global _pw_state
    with _pw_lock:
        _pw_state = {"state": "installing", "error": "", "started": time.time(),
                     "finished": 0.0}
    trace("INFO", "browser", "install started into %s" % _PW_DIR)
    try:
        os.makedirs(_PW_DIR, exist_ok=True)
        env = dict(os.environ)
        env["PLAYWRIGHT_BROWSERS_PATH"] = _PW_DIR
        proc = subprocess.run([sys.executable, "-m", "playwright", "install",
                               "chromium"], capture_output=True, text=True,
                              timeout=900, env=env)
        if proc.returncode != 0:
            _tail = ((proc.stderr or "") + (proc.stdout or "")).strip()[-500:]
            with _pw_lock:
                _pw_state = {"state": "failed", "error": _tail or "install failed",
                             "started": _pw_state["started"], "finished": time.time()}
            trace("ERR", "browser", "install failed: %s" % _tail[:300])
            return
        with open(_PW_SENTINEL, "w", encoding="utf-8") as fh:
            fh.write("ok\n")
        with _pw_lock:
            _pw_state = {"state": "ready", "error": "", "started": _pw_state["started"],
                         "finished": time.time()}
        trace("INFO", "browser", "install finished")
    except Exception as exc:
        with _pw_lock:
            _pw_state = {"state": "failed", "error": "%s: %s" % (type(exc).__name__, exc),
                         "started": _pw_state.get("started", 0.0),
                         "finished": time.time()}
        trace("ERR", "browser", "install raised %s" % type(exc).__name__)


def ensure_browser(force=False) -> str:
    global _pw_thread, _pw_state
    if _installed():
        with _pw_lock:
            if _pw_state["state"] != "ready":
                _pw_state = {"state": "ready", "error": "",
                             "started": _pw_state.get("started", 0.0),
                             "finished": time.time()}
        return "ready"
    with _pw_lock:
        if _pw_thread is not None and _pw_thread.is_alive():
            return _pw_state["state"]
        if _pw_state["state"] == "failed" and not force:
            return "failed"
        _pw_thread = threading.Thread(target=_install_now, name="breach-install",
                                      daemon=True)
        _pw_thread.start()
    return "installing"


def browser_state() -> dict:
    if _installed():
        return {"state": "ready", "error": "", "path": _PW_DIR, "seconds": 0}
    with _pw_lock:
        snap = dict(_pw_state)
    snap["seconds"] = (int(time.time() - snap["started"])
                       if snap.get("state") == "installing" and snap.get("started") else 0)
    snap["path"] = _PW_DIR
    return snap


def available() -> bool:
    global _pw_missing
    if not _installed():
        return False
    if _pw_missing:
        return False
    try:
        import playwright.sync_api  # noqa: F401
        return True
    except Exception as exc:
        _pw_missing = "%s: %s" % (type(exc).__name__, exc)
        return False


def browser_note() -> str:
    if _installed() and _pw_missing:
        return _pw_missing
    st = browser_state()
    if st["state"] == "failed":
        return st.get("error") or "install failed"
    if st["state"] == "installing":
        return "installing (%ss)" % st.get("seconds", 0)
    return "not installed"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _norm(addr) -> str:
    return str(addr or "").strip().strip("<>").strip().lower()


def _email_only(addr) -> str:
    s = str(addr or "").strip().lstrip("\ufeff").strip()
    s = _MAILTO_RE.sub("", s).strip()
    if "|" in s:
        s = s.split("|", 1)[0]
    if ":" in s:
        s = s.split(":", 1)[0]
    return _norm(s.strip().strip("\"'").strip().strip("<>").strip())


def is_email(addr) -> bool:
    return bool(_EMAIL_RE.match(_email_only(addr)))


def unified_url(addr) -> str:
    return UNIFIED % urllib.parse.quote(_email_only(addr))


def account_url(addr) -> str:
    return ACCOUNT % urllib.parse.quote(_email_only(addr))


def _esc(v) -> str:
    return (str(v or "").replace(chr(38), _AMP).replace(chr(60), _LT)
            .replace(chr(62), _GT).replace(chr(34), _QUOT))


def _plain(s) -> str:
    import html as _html
    return _html.unescape(_TAG_RE.sub("", str(s or ""))).strip()


# ---------------------------------------------------------------------------
# input parsing - three shapes, decided per line
# ---------------------------------------------------------------------------
def parse_lines(text):
    """One line -> {'kind': combo|email|password, 'email':.., 'password':..}."""
    out, seen = [], set()
    for raw in str(text or "").splitlines():
        s = raw.strip().lstrip("\ufeff").strip("\"'").strip()
        if not s or s.startswith("#"):
            continue
        if "|" in s:
            s = s.split("|", 1)[0].strip()
        if not s:
            continue
        kind, email, pw = "", "", ""
        if "@" in s and ":" in s:
            head, tail = s.split(":", 1)
            if is_email(head):
                kind, email, pw = "combo", _email_only(head), tail.strip()
        elif "@" in s:
            if is_email(s):
                kind, email = "email", _email_only(s)
        else:
            kind, pw = "password", s
        if not kind:
            continue
        key = (kind, email.lower() if email else "", pw)
        if kind == "email":
            key = (kind, email.lower(), "")
        if key in seen:
            continue
        seen.add(key)
        out.append({"kind": kind, "email": email, "password": pw,
                    "raw": s[:200]})
    return out


def parse_addresses(text):
    """(email, password) for address rows - compatibility wrapper."""
    return [(i["email"], i["password"]) for i in parse_lines(text)
            if i["kind"] in ("email", "combo")]


def _days(date_str):
    if not date_str:
        return None
    txt = str(date_str)[:10]
    try:
        y, m, d = (int(p) for p in txt.split("-"))
        stamp = time.mktime((y, m, d, 0, 0, 0, 0, 0, -1))
        return max(0, int((time.time() - stamp) / 86400))
    except Exception:
        return None


def _any_date(text):
    txt = str(text or "")
    m = _ISO_RE.search(txt)
    if m:
        return "%s-%s-%s" % m.groups()
    m = _D_MONTH_Y.search(txt)
    if m:
        mon = _MONTHS.get(m.group(2).strip().lower()[:3])
        if mon:
            return "%04d-%02d-%02d" % (int(m.group(3)), mon, int(m.group(1)))
    return ""


def _is_corpus(breach) -> bool:
    name = str(breach.get("Name") or breach.get("Title") or "").strip().lower()
    if name in CORPORA:
        return True
    if any(k in name for k in ("stealer", "combolist", "credential stuff",
                               "txtbase", "naz.api")):
        return True
    return bool(breach.get("IsSpamList")) and not breach.get("Domain")


def _blank(item, pw="") -> dict:
    email = _email_only(item.get("email") or "") if isinstance(item, dict) else ""
    return {"email": email, "kind": (item.get("kind") if isinstance(item, dict) else ""),
            "password_len": len(pw or ""), "verdict": "", "bucket": "", "reason": "",
            "breaches": [], "pastes": [], "pw_count": None, "corpora": 0, "sites": 0,
            "sensitive": 0, "stealer": 0, "newest_days": None, "count": None,
            "via": "", "via_proxy": "", "read": False, "partial_read": False,
            "addr_verdict": "UNREAD", "pw_band": "none",
            "page_text": "", "page_html": "", "page_via": "",
            "password_check": None, "earliest_breach": None, "latest_breach": None,
            "total_records_exposed": 0, "password_breaches": [], "summary_note": "",
            "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "error": ""}


# ---------------------------------------------------------------------------
# cache
# ---------------------------------------------------------------------------
def _cache_path() -> str:
    p = _user_file(CACHE_NAME)
    if not p:
        return ""
    try:
        os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
    except Exception:
        pass
    return p


def _load() -> dict:
    p = _cache_path()
    if not p or not os.path.exists(p):
        return {}
    try:
        with open(p, encoding="utf-8", errors="ignore") as f:
            data = json.load(f)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _save(data: dict) -> None:
    p = _cache_path()
    if not p:
        return
    tmp = p + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, separators=(",", ":"))
        os.replace(tmp, p)
    except Exception:
        pass


def _fresh(entry, ttl) -> bool:
    try:
        return bool(entry) and (time.time() - float(entry.get("ts") or 0)) < ttl
    except Exception:
        return False


def clear_cache() -> None:
    _save({})
    trace("CLICK", "cache", "cleared by the page")


def cache_stats() -> dict:
    data = _load()
    try:
        size = os.path.getsize(_cache_path())
    except Exception:
        size = 0
    return {"entries": len(data.get("item") or {}) + len(data.get("pw") or {}),
            "bytes": size, "path": os.path.basename(_cache_path())}


# ---------------------------------------------------------------------------
# the app's proxy pool
# ---------------------------------------------------------------------------
def parse_proxy_line(line):
    """`user:pass@host:port` / `host:port` -> dict, or None."""
    t = str(line or "").strip()
    for sch in ("socks5://", "socks4://", "http://", "https://", "socks5:", "http:"):
        if t.lower().startswith(sch):
            t = t[len(sch):].strip()
            break
    if not t:
        return None
    user = pwd = None
    hostpart = t
    if "@" in t:
        cred, hostpart = t.rsplit("@", 1)
        if ":" in cred:
            user, pwd = cred.split(":", 1)
        else:
            user = cred
    parts = hostpart.split(":")
    if len(parts) == 2:
        host, port_s = parts
    elif len(parts) >= 3:
        host, port_s, user = parts[0], parts[1], (user or parts[2])
        if len(parts) >= 4:
            pwd = pwd or ":".join(parts[3:])
    else:
        return None
    try:
        port = int(port_s)
    except Exception:
        return None
    if not host or "." not in host or not (0 < port < 65536):
        return None
    return {"host": host.strip(), "port": port,
            "user": (user or "").strip() or None,
            "pass": (pwd or "").strip() or None}


def _proxy_cfg(line):
    info = parse_proxy_line(line)
    if not info:
        return None
    cfg = {"server": "http://%s:%d" % (info["host"], info["port"])}
    if info.get("user"):
        cfg["username"] = info["user"]
        cfg["password"] = info.get("pass") or ""
    return cfg


def _meta_tiers():
    """line -> tier from the app's proxy_meta.json. 0 best, 3 untested."""
    tiers = {}
    p = _user_file("proxy_meta.json")
    if not p or not os.path.exists(p):
        return tiers
    try:
        with open(p, encoding="utf-8", errors="ignore") as f:
            data = json.load(f)
    except Exception:
        return tiers
    probe = (data or {}).get("probe") if isinstance(data, dict) else {}
    meta = (data or {}).get("meta") if isinstance(data, dict) else {}
    for line in set(list((probe or {}).keys()) + list((meta or {}).keys())):
        reason = str(((probe or {}).get(line) or {}).get("reason") or "")
        if reason == "ok":
            tiers[line] = 0
        elif reason == "plan":
            tiers[line] = 2
        elif reason in ("auth", "auth_dest", "timeout", "transport", "tcp", "dead"):
            tiers[line] = 3
        else:
            tiers[line] = 1
    return tiers


def pool_lines(force=False):
    """The owner's own pool, best tier first, shuffled inside each tier."""
    with _lock:
        given = _cfg.get("pool")
    if given:
        return list(dict.fromkeys(given))
    now = time.time()
    if not force and _pool_cache["lines"] and (now - _pool_cache["ts"]) < _pool_ttl:
        return list(_pool_cache["lines"])
    path = _user_file("proxies.txt")
    raw = []
    try:
        if path and os.path.exists(path):
            with open(path, encoding="utf-8", errors="ignore") as f:
                raw = [l.strip() for l in f
                       if l.strip() and not l.strip().startswith("#")]
    except Exception:
        raw = []
    raw = [l for l in dict.fromkeys(raw) if parse_proxy_line(l)]
    tiers = _meta_tiers()
    buckets = {0: [], 1: [], 2: [], 3: []}
    for line in raw:
        buckets[tiers.get(line, 1)].append(line)
    out = []
    for key in (0, 1, 2, 3):
        part = buckets[key]
        random.shuffle(part)
        out.extend(part)
    with _lock:
        _pool_cache["ts"] = now
        _pool_cache["lines"] = list(out)
    return out


def _mark_bad(line):
    if not line:
        return
    with _lock:
        _bad[line] = min(9, _bad.get(line, 0) + 1)


def _pick_proxy(used):
    """The next node for this item, or None when the pool cannot supply one.

    Random across the whole tier order so one node is never the only one the run
    ever touches, never a node this item has already tried, and never a node that
    has already failed BAD_AFTER times - until nothing else is left. `rotate`
    off walks the tier order from a shared cursor instead, which is a readable
    deterministic sweep for a small pool.
    """
    pool = pool_lines()
    if not pool:
        return None
    with _lock:
        live = [l for l in pool if _bad.get(l, 0) < BAD_AFTER] or pool
        if not _cfg_get("rotate", True):
            n = len(live)
            for _ in range(n):
                line = live[_cursor[0] % n]
                _cursor[0] += 1
                if line not in used:
                    return line
            return None
    left = [l for l in live if l not in used]
    if not left:
        return None
    return random.choice(left)


def pool_status() -> dict:
    lines = pool_lines()
    return {"count": len(lines), "sample": lines[:3]}


# ---------------------------------------------------------------------------
# password half - Pwned Passwords k-anonymity
# ---------------------------------------------------------------------------
def _pw_hash(password) -> str:
    return hashlib.sha1(str(password or "").encode("utf-8", "replace")).hexdigest().upper()


def _pw_message(n) -> str:
    if n > 0:
        return ("Oh no - pwned!\nThis password has been seen %d times before in data "
                "breaches!" % n)
    return ("0\nGood news - no pwnage found!\nThis password wasn't found in any of the "
            "Pwned Passwords loaded into Have I Been Pwned. That doesn't necessarily "
            "mean it's a good password, merely that it's not indexed on this site.")


def pwned_count(password, force=False):
    pw = str(password or "")
    if not pw:
        return None
    full = _pw_hash(pw)
    prefix, suffix = full[:5], full[5:]
    cache = _load()
    entry = (cache.get("pw") or {}).get(full)
    if not force and _fresh(entry, CACHE_TTL):
        trace("INFO", "pw", "cache hit, %s hit(s)" % entry.get("n"))
        return entry.get("n")
    try:
        import requests
    except Exception:
        trace("ERR", "pw", "requests not importable")
        return entry.get("n") if entry else None
    n = None
    try:
        trace("INFO", "pw", "GET %s (prefix %s, 35 chars kept local)"
              % (PW_RANGE % prefix, prefix))
        r = requests.get(PW_RANGE % prefix, timeout=HTTP_TIMEOUT,
                         headers={"User-Agent": UA, "Add-Padding": "true"})
        trace("INFO", "pw", "http %d, %d byte(s)" % (r.status_code, len(r.text or "")))
        if r.status_code == 200:
            for line in (r.text or "").splitlines():
                if ":" not in line:
                    continue
                got, _, cnt = line.partition(":")
                if got.strip().upper() == suffix:
                    try:
                        n = int(cnt.strip() or 0)
                    except Exception:
                        n = 1
                    break
            if n is None:
                n = 0
    except Exception as exc:
        trace("ERR", "pw", "%s: %s" % (type(exc).__name__, exc))
        return entry.get("n") if entry else None
    cache.setdefault("pw", {})[full] = {"ts": time.time(), "n": n}
    if len(cache.get("pw") or {}) > CACHE_MAX:
        cut = list(cache["pw"])[:len(cache["pw"]) - CACHE_MAX]
        for k in cut:
            cache["pw"].pop(k, None)
    _save(cache)
    return n


def check_password(password, force=False):
    if not password:
        return None
    n = pwned_count(password, force=force)
    if n is None:
        return None
    return {"sha1": _pw_hash(password), "times_pwned": int(n),
            "pwned": bool(n and n > 0), "message": _pw_message(int(n))}


# ---------------------------------------------------------------------------
# the address half - one reused page per worker, real Chromium, the pool
# ---------------------------------------------------------------------------
def _browser():
    """This thread's Chromium. Launched once per run, reused, replaced if it died."""
    b = getattr(_tls, "browser", None)
    try:
        if b is not None and b.is_connected():
            return b
    except Exception:
        pass
    from playwright.sync_api import sync_playwright
    pw = getattr(_tls, "pw", None)
    if pw is None:
        pw = sync_playwright().start()
        _tls.pw = pw
    b = pw.chromium.launch(headless=True, args=CHROME_ARGS)
    _tls.browser = b
    return b


def _close_thread_browser():
    b = getattr(_tls, "browser", None)
    pw = getattr(_tls, "pw", None)
    try:
        if b is not None:
            b.close()
    except Exception:
        pass
    try:
        if pw is not None:
            pw.stop()
    except Exception:
        pass
    _tls.browser = None
    _tls.pw = None


class _Slot:
    """One context and one page, owned by one worker and REUSED across items.

    The proxy is bound to the CONTEXT, so a different proxy means a new context -
    but always on the same browser, which is the expensive half. `get()` resets
    the page between items and recycles on its own terms, so a page that is
    challenged or wedged never costs more than the attempt it was in.

    `cf` records that this context has already earned clearance, so a warmed
    proxy goes straight to the endpoint instead of warming on every item.
    """

    __slots__ = ("ctx", "page", "proxy", "uses", "fails", "cf")

    def __init__(self):
        self.ctx = None
        self.page = None
        self.proxy = ""
        self.uses = 0
        self.fails = 0
        self.cf = False

    def close_ctx(self):
        try:
            if self.ctx is not None:
                self.ctx.close()
        except Exception:
            pass
        self.ctx = None
        self.page = None
        self.proxy = ""
        self.uses = 0
        self.fails = 0
        self.cf = False

    def open_ctx(self, proxy_line):
        self.close_ctx()
        b = _browser()
        kw = {"user_agent": UA, "locale": "en-US", "ignore_https_errors": True,
              "viewport": {"width": 1440, "height": 900},
              "extra_http_headers": HEADERS}
        cfg = _proxy_cfg(proxy_line) if proxy_line else None
        if cfg:
            kw["proxy"] = cfg
        ctx = b.new_context(**kw)
        ctx.add_init_script(STEALTH_JS)
        ctx.set_default_timeout(NAV_TIMEOUT)
        self.ctx = ctx
        self.page = ctx.new_page()
        self.proxy = proxy_line or ""

    def reset(self):
        """Blank the page and drop its cookies - state never carries over.

        The clearance cookie goes with them, so `cf` is cleared too; the next
        challenge warms again. A blank page is what keeps one item's render out
        of the next item's way.
        """
        if self.page is not None and not self.page.is_closed():
            self.page.goto("about:blank", wait_until="commit", timeout=8000)
        try:
            if self.ctx is not None:
                self.ctx.clear_cookies()
        except Exception:
            pass
        self.cf = False

    def get(self, proxy_line):
        """A page ready for this attempt. Reuses, resets, recycles as needed."""
        try:
            if self.ctx is None or self.page is None:
                self.open_ctx(proxy_line)
            elif self.uses >= SLOT_USES_MAX:
                trace("INFO", "slot", "recycling after %d use(s)" % self.uses)
                self.open_ctx(proxy_line)
            elif (proxy_line or "") != self.proxy:
                self.open_ctx(proxy_line)
            elif self.page.is_closed():
                self.open_ctx(proxy_line)
            else:
                self.reset()
        except Exception as exc:
            trace("WARN", "slot", "reopen after %s" % type(exc).__name__)
            self.close_ctx()
            self.open_ctx(proxy_line)
        return self.page

    def ok(self):
        self.uses += 1
        self.fails = 0

    def bad(self):
        """A failed attempt. Two in a row and the context is thrown away."""
        self.uses += 1
        self.fails += 1
        if self.fails >= SLOT_FAILS_MAX:
            self.close_ctx()


def _slot():
    """This worker's slot. One per thread, so one page per worker at most."""
    s = getattr(_tls, "slot", None)
    if s is None:
        s = _Slot()
        _tls.slot = s
        with _lock:
            _slots[threading.get_ident()] = s
    return s


def _close_all_slots():
    with _lock:
        got = list(_slots.values())
        _slots.clear()
    for s in got:
        s.close_ctx()


def _looks_challenge(status, body) -> bool:
    if status in (401, 403, 429, 503):
        return True
    low = str(body or "")[:4000].lower()
    return any(m in low for m in CHALLENGE_MARKS)


def _is_wall(page) -> bool:
    try:
        if any(m in (page.title() or "").lower() for m in CHALLENGE_MARKS):
            return True
    except Exception:
        pass
    try:
        low = (page.evaluate("() => document.body ? (document.body.innerText || '')"
                             ".slice(0, 1500) : ''") or "").lower()
    except Exception:
        low = ""
    return any(m in low for m in CHALLENGE_MARKS)


def _click_turnstile(page) -> bool:
    for fr in list(page.frames):
        try:
            if "challenges.cloudflare.com" not in (fr.url or ""):
                continue
        except Exception:
            continue
        for sel in ("input[type='checkbox']", "#challenge-stage", "body"):
            try:
                fr.click(sel, timeout=1200,
                         position={"x": 20, "y": 20} if sel == "body" else None)
                return True
            except Exception:
                continue
    for sel in TURNSTILE_SELECTORS:
        try:
            el = page.query_selector(sel)
            bb = el.bounding_box() if el is not None else None
            if bb:
                page.mouse.click(bb["x"] + 22, bb["y"] + bb["height"] / 2.0)
                return True
        except Exception:
            continue
    return False


def _solve_wall(page, cancel=None):
    """Bounded wait for a challenge to clear. True when the page looks clear."""
    deadline = time.time() + CHALLENGE_WAIT
    last = 0.0
    streak = 0
    while time.time() < deadline:
        if _is_cancelled(cancel):
            return False
        if not _is_wall(page):
            streak += 1
            if streak >= 2:
                return True
        else:
            streak = 0
            if time.time() - last > 3.0:
                last = time.time()
                if _click_turnstile(page):
                    trace("INFO", "browser", "clicked the challenge widget")
        try:
            page.wait_for_timeout(700)
        except Exception:
            time.sleep(0.7)
    return not _is_wall(page)


def _warm(page, label, addr):
    """Navigate the origin HTML so a challenge has a widget to solve.

    The endpoint renders a refused body as bare JSON - no interstitial, no
    Turnstile, no cookie. This is the page that can actually earn one. Returns
    the status it got, 0 when the navigation itself failed.
    """
    try:
        warm = page.goto(HIBP_BASE + "/", wait_until="domcontentloaded",
                         timeout=NAV_TIMEOUT)
        wstatus = warm.status if warm is not None else 0
        trace("INFO", "fetch", "warm page http %d via %s" % (wstatus, label), addr)
        return wstatus
    except Exception as exc:
        trace("WARN", "fetch", "warm page failed via %s: %s"
              % (label, type(exc).__name__), addr)
        return 0


def _attempt(addr, proxy_line, cancel=None):
    """One navigation through one proxy (or DIRECT). -> (status, payload|None).

    The page comes from this worker's slot and goes back to it. Nothing is closed
    here; the slot decides when to recycle, so the browser survives the batch.
    """
    label = (proxy_line.rsplit("@", 1)[-1] if proxy_line else "DIRECT")
    url = unified_url(addr)
    slot = _slot()
    try:
        page = slot.get(proxy_line)
    except Exception as exc:
        trace("ERR", "slot", "no page via %s: %s" % (label, type(exc).__name__), addr)
        return 0, None
    try:
        trace("INFO", "fetch", "goto via %s" % label, addr)
        resp = page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT)
        status = resp.status if resp is not None else 0
        body = ""
        try:
            body = resp.text() if resp is not None else ""
        except Exception:
            body = ""
        trace("INFO", "fetch", "http %d via %s (%d byte(s))"
              % (status, label, len(body)), addr)

        if status == 200 and body.strip():
            try:
                got = json.loads(body)
                if isinstance(got, dict):
                    slot.ok()
                    return 200, got
            except Exception:
                pass

        if _looks_challenge(status, body):
            trace("WARN", "fetch", "challenge (http %d) via %s" % (status, label), addr)
            wstatus = 0
            if not slot.cf:
                wstatus = _warm(page, label, addr)
            if _solve_wall(page, cancel):
                if wstatus == 200:
                    slot.cf = True
                try:
                    got = page.evaluate(JS_FETCH, url) or {}
                except Exception:
                    got = {}
                s2 = int(got.get("status") or 0)
                b2 = str(got.get("body") or "")
                trace("INFO", "fetch", "re-fetch from the page -> http %d" % s2, addr)
                if s2 == 200 and b2.strip():
                    try:
                        parsed = json.loads(b2)
                        if isinstance(parsed, dict):
                            slot.ok()
                            return 200, parsed
                    except Exception:
                        pass
                if s2 == 404:
                    slot.ok()
                    return 404, None
                slot.cf = False
                slot.bad()
                return s2 or status, None
            slot.cf = False
            slot.bad()
            return status, None

        if status == 404:
            slot.ok()
            return 404, None
        slot.bad()
        return status, None
    except Exception as exc:
        trace("ERR", "fetch", "%s via %s: %s" % (type(exc).__name__, label,
                                                 str(exc)[:160]), addr)
        slot.bad()
        return 0, None


def _search_address(addr, cancel=None):
    """Draw nodes, then DIRECT. -> (payload|None, via_label, error, tried)."""
    tries = max(1, min(8, int(TRIES)))
    order, used = [], set()
    for _ in range(tries - 1):
        line = _pick_proxy(used)
        if line is None:
            break
        used.add(line)
        order.append(line)
    order.append(None)
    errors = []
    last_status = 0
    for line in order:
        if _is_cancelled(cancel):
            return None, "", "cancelled", errors
        status, payload = _attempt(addr, line, cancel)
        last_status = status
        label = (line.rsplit("@", 1)[-1] if line else "DIRECT")
        if payload is not None:
            return payload, label, "", errors
        if status == 404:
            return {}, label, "", errors
        if status in (0, 401, 403, 429, 503):
            _mark_bad(line)
        errors.append("%s: http %s" % (label, status or "?"))
        if status == 200 and not payload:
            errors[-1] = "%s: http 200 but no JSON" % label
    return None, "", "; ".join(errors[-3:]) or ("http %s" % (last_status or "?")), errors


# ---------------------------------------------------------------------------
# payload -> record
# ---------------------------------------------------------------------------
def _parse_payload(item, payload, via, started, pw) -> dict:
    rec = _blank(item, pw)
    rec["via"] = via
    rec["via_proxy"] = via
    rec["elapsed_ms"] = int((time.time() - started) * 1000) if started else 0
    if not isinstance(payload, dict):
        rec["error"] = "payload not an object"
        return rec

    raw_b = payload.get("Breaches")
    raw_p = payload.get("Pastes")
    raw_b = raw_b if isinstance(raw_b, list) else []
    raw_p = raw_p if isinstance(raw_p, list) else []

    for b in raw_b:
        if not isinstance(b, dict):
            continue
        corpus = _is_corpus(b)
        days = _days(b.get("BreachDate") or b.get("AddedDate"))
        rec["breaches"].append({
            "Name": str(b.get("Name") or ""),
            "Title": str(b.get("Title") or b.get("Name") or "Unnamed")[:160],
            "Domain": str(b.get("Domain") or ""),
            "BreachDate": str(b.get("BreachDate") or "")[:10],
            "AddedDate": str(b.get("AddedDate") or "")[:24],
            "PwnCount": int(b.get("PwnCount") or 0),
            "Description": _plain(b.get("Description"))[:DESC_MAX],
            "DescriptionHtml": str(b.get("Description") or "")[:DESC_MAX],
            "DataClasses": [str(c) for c in (b.get("DataClasses") or [])][:12],
            "IsVerified": bool(b.get("IsVerified")),
            "IsSensitive": bool(b.get("IsSensitive")),
            "IsStealerLog": bool(b.get("IsStealerLog")),
            "IsSpamList": bool(b.get("IsSpamList")),
            "corpus": corpus, "days": days,
            "name": str(b.get("Name") or ""),
            "title": str(b.get("Title") or b.get("Name") or "Unnamed")[:160],
            "domain": str(b.get("Domain") or ""),
            "date": str(b.get("BreachDate") or "")[:10],
            "pwn_count": int(b.get("PwnCount") or 0),
            "classes": [str(c) for c in (b.get("DataClasses") or [])][:12],
            "sensitive": bool(b.get("IsSensitive")),
            "description": _plain(b.get("Description"))[:DESC_MAX],
        })
        if corpus:
            rec["corpora"] += 1
        else:
            rec["sites"] += 1
        if b.get("IsStealerLog"):
            rec["stealer"] += 1
        if b.get("IsSensitive"):
            rec["sensitive"] += 1
        if days is not None:
            if rec["newest_days"] is None or days < rec["newest_days"]:
                rec["newest_days"] = days

    for p in raw_p:
        if not isinstance(p, dict):
            continue
        rec["pastes"].append({"Title": str(p.get("Title") or "Untitled")[:200],
                              "Source": str(p.get("Source") or "")[:120],
                              "Date": str(p.get("Date") or "")[:10],
                              "title": str(p.get("Title") or "Untitled")[:200],
                              "source": str(p.get("Source") or "")[:120],
                              "date": str(p.get("Date") or "")[:10]})

    rec["count"] = len(rec["breaches"]) + len(rec["pastes"])
    dates = [b["BreachDate"] for b in rec["breaches"] if b.get("BreachDate")]
    rec["earliest_breach"] = min(dates) if dates else None
    rec["latest_breach"] = max(dates) if dates else None
    rec["total_records_exposed"] = sum(int(b.get("PwnCount") or 0) for b in rec["breaches"])
    rec["password_breaches"] = [b["Name"] for b in rec["breaches"]
                                if "Passwords" in (b.get("DataClasses") or [])]
    return rec


def _summary_note(rec) -> str:
    n = int(rec.get("breach_count") or 0)
    if n > 0:
        return ("%d\nData Breaches\nOh no - pwned! This email address has been found "
                "in multiple data breaches. Review the details below to see where your "
                "data was exposed." % n)
    return ("0\nData Breaches\nGood news - no pwnage found! This email address wasn't "
            "found in any of the data breaches loaded into Have I Been Pwned. That's "
            "great news!")


# ---------------------------------------------------------------------------
# the generated page view (text + html)
# ---------------------------------------------------------------------------
def _page_from_record(rec) -> dict:
    kind = str(rec.get("kind") or ("combo" if rec.get("email") else "password"))
    head_addr = rec.get("email") or "(password only)"
    _pw = rec.get("pw_count")
    pc = rec.get("password_check") or {}
    lines = ["kind: %s" % kind,
             "address: %s" % (rec.get("email") or "-"),
             "checked: %s" % (rec.get("checked_at") or ""),
             "verdict: %s - %s" % (rec.get("verdict") or "?", rec.get("reason") or ""),
             "address half: %s" % (rec.get("addr_verdict") or "UNREAD"),
             "password half: %s" % (rec.get("pw_band") or "none"),
             "password appearances: %s" % (_pw if _pw is not None
                                           else "no password supplied"),
             "source: %s" % (rec.get("via") or "-"),
             "breaches: %d, pastes: %d" % (len(rec.get("breaches") or []),
                                          len(rec.get("pastes") or []))]
    if rec.get("error"):
        lines.append("error: %s" % rec["error"])
    if pc:
        lines.append("")
        lines.append("password sha1: %s" % pc.get("sha1"))
        lines.append("times pwned: %s" % pc.get("times_pwned"))
    for b in (rec.get("breaches") or [])[:60]:
        lines.append("")
        lines.append("- %s%s" % (b.get("Title") or b.get("title") or "?",
                                 " [stealer log]" if (b.get("IsStealerLog")
                                                      or b.get("corpus")) else ""))
        if b.get("BreachDate") or b.get("date"):
            lines.append("  breach date: %s" % (b.get("BreachDate") or b.get("date")))
        if b.get("days") is not None:
            lines.append("  age: %d day(s)" % int(b["days"]))
        lines.append("  accounts: %s" % "{:,}".format(int(b.get("PwnCount")
                                                         or b.get("pwn_count") or 0)))
        cls = b.get("DataClasses") or b.get("classes")
        if cls:
            lines.append("  data: %s" % ", ".join(cls))
        if b.get("Description") or b.get("description"):
            lines.append("  %s" % str(b.get("Description") or b.get("description"))[:400])
    for p in (rec.get("pastes") or [])[:30]:
        lines.append("")
        lines.append("- paste: %s (%s) %s" % (p.get("Title") or p.get("title") or "?",
                                              p.get("Source") or p.get("source") or "-",
                                              p.get("Date") or p.get("date") or ""))
    text = "\n".join(lines)[:PAGE_TEXT_MAX]

    h = ["\x3chtml\x3e\x3chead\x3e\x3cmeta charset='utf-8'\x3e\x3ctitle\x3e",
         _esc(head_addr),
         "\x3c/title\x3e", _PAGE_CSS, "\x3c/head\x3e\x3cbody\x3e\x3ch1\x3e",
         _esc(head_addr),
         "\x3c/h1\x3e\x3cp class='c'\x3e", _esc(rec.get("verdict") or "?"), " - ",
         _esc(rec.get("reason") or ""), "\x3c/p\x3e\x3cp\x3eaddress half: ",
         _esc(rec.get("addr_verdict") or "UNREAD"), "\x3cbr\x3epassword half: ",
         _esc(rec.get("pw_band") or "none"), "\x3cbr\x3epassword appearances: ",
         (_esc(_pw) if _pw is not None else "-"), "\x3cbr\x3esource: ",
         _esc(rec.get("via") or "-"), "\x3cbr\x3echecked: ",
         _esc(rec.get("checked_at") or ""), "\x3c/p\x3e"]
    if rec.get("error"):
        h.append("\x3cp class='c'\x3eerror: %s\x3c/p\x3e" % _esc(rec["error"]))
    if pc:
        h.append("\x3cp\x3eSHA-1: %s\x3cbr\x3eseen: %s time(s)\x3c/p\x3e"
                 % (_esc(pc.get("sha1") or "-"), _esc(pc.get("times_pwned"))))
    rows = rec.get("breaches") or []
    if rows:
        h.append("\x3ctable\x3e\x3ctr\x3e\x3cth\x3eBreach\x3c/th\x3e\x3cth\x3eDate"
                 "\x3c/th\x3e\x3cth\x3eAge\x3c/th\x3e\x3cth\x3eAccounts\x3c/th\x3e"
                 "\x3cth\x3eData classes\x3c/th\x3e\x3c/tr\x3e")
        for b in rows:
            h.append("\x3ctr\x3e\x3ctd\x3e%s%s\x3c/td\x3e\x3ctd\x3e%s\x3c/td\x3e"
                     "\x3ctd\x3e%s\x3c/td\x3e\x3ctd\x3e%s\x3c/td\x3e\x3ctd\x3e%s"
                     "\x3c/td\x3e\x3c/tr\x3e"
                     % (_esc(b.get("Title") or b.get("title") or "?"),
                        " (stealer log)" if (b.get("IsStealerLog")
                                             or b.get("corpus")) else "",
                        _esc(b.get("BreachDate") or b.get("date") or "-"),
                        ("%d d" % int(b["days"])) if b.get("days") is not None else "-",
                        "{:,}".format(int(b.get("PwnCount") or b.get("pwn_count") or 0)),
                        _esc(", ".join(b.get("DataClasses") or b.get("classes") or [])
                             or "-")))
        h.append("\x3c/table\x3e")
    else:
        h.append("\x3cp\x3e%s\x3c/p\x3e"
                 % ("No breach record could be read - see the error above."
                    if rec.get("error") else "No breach record for this address."))
    if rec.get("pastes"):
        h.append("\x3ch2\x3ePastes\x3c/h2\x3e\x3cul\x3e")
        for p in (rec.get("pastes") or [])[:30]:
            h.append("\x3cli\x3e%s (%s) %s\x3c/li\x3e"
                     % (_esc(p.get("Title") or p.get("title") or "?"),
                        _esc(p.get("Source") or p.get("source") or "-"),
                        _esc(p.get("Date") or p.get("date") or "")))
        h.append("\x3c/ul\x3e")
    h.append("\x3cp\x3e\x3csmall\x3eGenerated from the answer, not a captured page."
             "\x3c/small\x3e\x3c/p\x3e\x3c/body\x3e\x3c/html\x3e")
    return {"page_text": text, "page_html": "".join(h)[:PAGE_HTML_MAX],
            "page_via": "record"}


def record_view(rec):
    try:
        page = _page_from_record(rec or {})
        return (str(page.get("page_text") or ""), str(page.get("page_html") or ""))
    except Exception:
        return "", ""


# ---------------------------------------------------------------------------
# banding
# ---------------------------------------------------------------------------
def _pw_bucket(n):
    if n is None:
        return None
    if n <= PW_NEW_MAX:
        return "NEW"
    if n <= PW_PARTIAL_MAX:
        return "PARTIAL"
    return "OLD"


def _addr_bucket(rec):
    if rec.get("error") and rec.get("count") is None:
        return None
    if not rec.get("count"):
        return "CLEAN"
    nd = rec.get("newest_days")
    if rec.get("stealer"):
        return "NEW" if (nd is not None and nd <= CORPUS_NEW_DAYS) else "PARTIAL"
    if rec.get("corpora"):
        if nd is not None and nd <= CORPUS_NEW_DAYS:
            return "NEW"
        return "PARTIAL"
    if nd is None:
        return "PARTIAL"
    return "PARTIAL" if nd <= BREACH_PARTIAL_DAYS else "OLD"


def _combine(pw_b, addr_b):
    known = [b for b in (pw_b, addr_b) if b in RANK]
    if known:
        return max(known, key=lambda b: RANK[b])
    if pw_b == "CLEAN" or addr_b == "CLEAN":
        return "CLEAN"
    return "UNKNOWN"


_REASON = {
    "NEW": "password unseen in Pwned Passwords, or exposure inside %d days"
           % CORPUS_NEW_DAYS,
    "PARTIAL": "password already circulating, or exposure inside %d days"
               % BREACH_PARTIAL_DAYS,
    "OLD": "password has been public for years, or only old breaches",
    "CLEAN": "password unseen and the address in no readable source",
    "UNKNOWN": "no readable answer - every attempt failed",
}


# ---------------------------------------------------------------------------
# the check
# ---------------------------------------------------------------------------
def _as_item(addr, password=""):
    if isinstance(addr, dict):
        return {"kind": addr.get("kind") or ("combo" if addr.get("password") else "email"),
                "email": addr.get("email") or "",
                "password": addr.get("password") or "",
                "raw": addr.get("raw") or ""}
    if isinstance(addr, (tuple, list)):
        em = addr[0] if addr else ""
        pw = addr[1] if len(addr) > 1 else ""
        return {"kind": "combo" if pw else "email", "email": em or "",
                "password": pw or "", "raw": ""}
    s = str(addr or "")
    if "@" not in s and password == "":
        return {"kind": "password", "email": "", "password": s, "raw": s}
    return {"kind": "combo" if password else "email", "email": s,
            "password": password or "", "raw": s}


def _cache_key(item) -> str:
    if item["kind"] == "password":
        return "pw:%s" % _pw_hash(item["password"])[:20]
    return "%s:%s" % (item["kind"], item["email"].lower())


def check_item(item, force=False, cancel=None) -> dict:
    item = _as_item(item)
    started = time.time()
    rec = _blank(item, item["password"])

    if item["kind"] == "password":
        rec["pw_count"] = pwned_count(item["password"], force=force)
        rec["password_check"] = check_password(item["password"], force=force)
        rec["read"] = rec["pw_count"] is not None
        rec["count"] = None
        rec["via"] = "pw"
        rec["addr_verdict"] = "none"
        rec["pw_band"] = _pw_bucket(rec["pw_count"]) or "none"
        rec["bucket"] = _combine(_pw_bucket(rec["pw_count"]), None)
        rec["verdict"] = rec["bucket"]
        rec["reason"] = _REASON.get(rec["bucket"], "")
        rec["summary_note"] = (rec["password_check"] or {}).get("message", "")
        if rec["pw_count"] is None:
            rec["error"] = "password check failed"
        rec.update(_page_from_record(rec))
        trace("INFO", "band", "%s (password only) - pw %s"
              % (rec["bucket"], rec["pw_band"]))
        return rec

    email = item["email"]
    if not is_email(email):
        rec["verdict"] = rec["bucket"] = "UNKNOWN"
        rec["reason"] = rec["error"] = "not an email address"
        trace("WARN", "address", "rejected %r" % email[:80])
        rec.update(_page_from_record(rec))
        return rec

    key = _cache_key(item)
    cache = _load()
    entry = (cache.get("item") or {}).get(key)
    if not force and _fresh(entry, CACHE_TTL) and entry.get("report"):
        got = dict(entry["report"])
        trace("INFO", "cache", "hit, verdict %s - no request sent"
              % got.get("verdict"), email)
        return got

    trace("INFO", "address", "checking %r, password %s, pool %d, rotate %s"
          % (email, "kept (hash only)" if item["password"] else "absent",
             len(pool_lines()), "on" if rotating() else "off"), email)
    if item["password"]:
        rec["pw_count"] = pwned_count(item["password"], force=force)
        rec["password_check"] = check_password(item["password"], force=force)
        trace("INFO", "pw", "result: %s" % ("no password" if rec["pw_count"] is None
                                            else "%d hit(s)" % rec["pw_count"]), email)

    payload, via, err, tried = _search_address(email, cancel)
    if payload is not None:
        rec = _parse_payload(item, payload, via or "browser", started, item["password"])
        rec["pw_count"] = (pwned_count(item["password"], force=force)
                           if item["password"] else None)
        if item["password"]:
            rec["password_check"] = check_password(item["password"], force=force)
        rec["read"] = True
    else:
        rec["via"] = "browser"
        rec["error"] = err or "no answer"
        rec["read"] = False
        if _is_cancelled(cancel):
            rec["error"] = "cancelled"
    rec["breach_count"] = len(rec.get("breaches") or [])
    rec["summary_note"] = _summary_note(rec)

    ab = _addr_bucket(rec)
    rec["addr_verdict"] = ab or ("UNREAD" if not rec["read"] else "UNKNOWN")
    rec["pw_band"] = _pw_bucket(rec.get("pw_count")) or "none"
    rec["bucket"] = _combine(_pw_bucket(rec.get("pw_count")), ab)
    rec["verdict"] = rec["bucket"]
    rec["reason"] = _REASON.get(rec["bucket"], "")
    if rec["bucket"] == "UNKNOWN" and not rec["error"]:
        rec["error"] = "no readable answer"
    rec.update(_page_from_record(rec))
    trace("INFO", "band", "%s (%s) - addr %s, pw %s, %d ms"
          % (rec["bucket"], rec["reason"] or "-", rec["addr_verdict"],
             rec["pw_band"], rec.get("elapsed_ms") or 0), email)

    if rec["bucket"] != "UNKNOWN":
        cache.setdefault("item", {})[key] = {"ts": time.time(), "report": rec}
        if len(cache.get("item") or {}) > CACHE_MAX:
            cut = list(cache["item"])[:len(cache["item"]) - CACHE_MAX]
            for k in cut:
                cache["item"].pop(k, None)
        _save(cache)
    _remember(rec)
    return rec


def check(addr, password="", force=False, cancel=None) -> dict:
    """One address or combo. Kept for callers that pass email + password."""
    return check_item(_as_item(addr, password), force=force, cancel=cancel)


def _remember(rec):
    with _lock:
        who = owner()
        cur = _lasts.get(who) or {}
        cur.update({"ts": time.time(), "email": rec.get("email", ""),
                    "verdict": rec.get("verdict", ""), "via": rec.get("via", ""),
                    "ms": rec.get("elapsed_ms", 0), "error": rec.get("error", "")})
        _lasts[who] = cur


def last_url() -> str:
    with _lock:
        cur = _lasts.get(owner()) or {}
    if cur.get("email"):
        return unified_url(cur["email"])
    return ""


def check_many(items, workers=3, progress=None, cancel=None, force=False,
               delay=None, rotate=None, owner_prefix=None) -> dict:
    """Run the list. One page slot per worker, reused and recycled, never more.

    The pool is drawn at most (tries - 1) times per item, so N workers hold at
    most N pages and the batch never opens one per check. Each worker's browser
    is launched on its first item and closed by a teardown task at the end, so a
    500-item run pays for N browsers and N pages, not 500.
    """
    pin = owner() if owner_prefix is None else str(owner_prefix or "")
    set_owner(pin)
    snap = _snapshot_cfg()
    if rotate is not None:
        snap["rotate"] = bool(rotate)
    _pin_cfg(snap)
    with _lock:
        _bad.clear()
        _cursor[0] = 0

    uniq, seen = [], set()
    for raw in items or []:
        item = _as_item(raw)
        if item["kind"] != "password" and not is_email(item["email"]):
            continue
        key = _cache_key(item)
        if key in seen:
            continue
        seen.add(key)
        uniq.append(item)

    out, guard, done = {}, threading.Lock(), [0]
    total = len(uniq)
    pace = float(snap.get("delay") if delay is None else max(0.0, float(delay or 0.0)))
    width = max(1, min(16, int(workers or 1)))
    trace("INFO", "run", "start: %d item(s), workers=%d, pages<=%d, pace=%ss, pool=%d, "
          "rotate=%s" % (total, width, width, pace, len(pool_lines()),
                         "on" if snap.get("rotate") else "off"))
    if not total:
        return out

    def _tell(n, label, verdict):
        if progress is not None:
            try:
                progress(n, total, label, verdict)
            except Exception:
                pass

    def one(item, position):
        set_owner(pin)
        _pin_cfg(snap)
        label = item["email"] or ("pw:%s" % ("*" * 8))
        rec = None
        if _is_cancelled(cancel):
            rec = _blank(item, item["password"])
            rec["verdict"] = rec["bucket"] = "UNKNOWN"
            rec["error"] = "cancelled"
            rec.update(_page_from_record(rec))
        else:
            trace("INFO", "start", "checking", label)
            _tell(position, label, "starting")
            try:
                rec = check_item(item, force=force, cancel=cancel)
            except Exception as exc:
                rec = _blank(item, item["password"])
                rec["verdict"] = rec["bucket"] = "UNKNOWN"
                rec["error"] = "%s: %s" % (type(exc).__name__, exc)
                rec.update(_page_from_record(rec))
                trace("ERR", "run", "%s: %s" % (type(exc).__name__, exc), label)
        with guard:
            out[_cache_key(item)] = rec
            done[0] += 1
            n = done[0]
        _tell(n, label, rec.get("verdict", ""))

    def _teardown():
        """Runs on a worker thread: close its page and its browser."""
        s = getattr(_tls, "slot", None)
        if s is not None:
            s.close_ctx()
        _close_thread_browser()

    try:
        with _cf.ThreadPoolExecutor(max_workers=width) as ex:
            inflight = set()
            for position, item in enumerate(uniq, 1):
                inflight.add(ex.submit(one, item, position))
                step = 0.0 if _is_cancelled(cancel) else pace
                if step:
                    time.sleep(step)
                if len(inflight) >= width:
                    _done, inflight = _cf.wait(inflight, return_when=_cf.FIRST_COMPLETED)
            while inflight:
                _done, inflight = _cf.wait(inflight, return_when=_cf.FIRST_COMPLETED)
            # One sentinel per worker thread, so every browser is closed from
            # inside the thread that owns it - Playwright objects are thread-bound.
            for _ in range(width):
                ex.submit(_teardown)
    except Exception as exc:
        trace("ERR", "run", "executor failed (%s), falling back to serial"
              % type(exc).__name__)
        for position, item in enumerate(uniq, 1):
            out.setdefault(_cache_key(item), check_item(item, force=force, cancel=cancel))
            _tell(position, item["email"], out[_cache_key(item)].get("verdict", ""))
        _teardown()
    finally:
        _close_all_slots()
    trace("INFO", "run", "finished: %d record(s)" % len(out))
    return out


# ---------------------------------------------------------------------------
# scoring
# ---------------------------------------------------------------------------
def score(records) -> dict:
    buckets = {"NEW": 0, "PARTIAL": 0, "OLD": 0, "CLEAN": 0, "UNKNOWN": 0}
    rows = []
    for rec in records or []:
        b = rec.get("verdict") or "UNKNOWN"
        buckets[b] = buckets.get(b, 0) + 1
        rows.append({"email": rec.get("email", ""), "bucket": b,
                     "pw_count": rec.get("pw_count"),
                     "breaches": len(rec.get("breaches") or [])})
    total = sum(buckets.values())
    scored = buckets["NEW"] + buckets["PARTIAL"] + buckets["OLD"]
    pct = {k: (round(100.0 * v / total, 1) if total else 0.0) for k, v in buckets.items()}
    quality = 0.0
    if scored:
        quality = 100.0 * sum(WEIGHTS[k] * buckets[k] for k in WEIGHTS) / scored
    grade = ("A" if quality >= 85 else "B" if quality >= 70 else
             "C" if quality >= 55 else "D" if quality >= 40 else "F")
    return {"total": total, "scored": scored, "buckets": buckets, "pct": pct,
            "quality": round(quality, 1), "grade": grade, "rows": rows}


def report() -> dict:
    with _lock:
        mine = dict(_lasts.get(owner()) or {})
        bad = len(_bad)
    return {"version": BREACH_VERSION, "browser": available(),
            "browser_state": browser_state().get("state", ""),
            "browser_error": browser_note(), "delay": _delay(),
            "pool": len(pool_lines()), "rotate": rotating(), "skipped": bad,
            "key": bool(_api_key()), "owner": owner(), "cache": cache_stats(),
            "last": mine, "trace_seq": trace_seq()}


# ---------------------------------------------------------------------------
# selftest
# ---------------------------------------------------------------------------
def selftest(verbose=False) -> bool:
    checks = []

    def add(n, ok):
        checks.append((n, bool(ok)))

    add("lock_reentrant", type(_lock).__name__ == "RLock")
    add("is_email", is_email("a.b@c.co"))
    add("not_email", not is_email("nope"))
    add("only_colon", _email_only("a@b.co:hunter2") == "a@b.co")
    add("url_no_password", unified_url("a@b.co:hunter2") ==
        HIBP_BASE + "/unifiedsearch/a%40b.co")
    add("blank_read_false", _blank({"kind": "email", "email": "a@b.co"}).get("read") is False)
    add("blank_addr_unread", _blank({"kind": "email", "email": "a@b.co"}).get("addr_verdict")
        == "UNREAD")

    items = parse_lines("a@b.co:pw\nc@d.co\nhunter2\njunk line\n")
    add("parse_combo", items[0]["kind"] == "combo" and items[0]["password"] == "pw")
    add("parse_email", items[1]["kind"] == "email" and items[1]["password"] == "")
    add("parse_password", items[2]["kind"] == "password")
    add("parse_pairs", len(parse_addresses("a@b.co:pw\nc@d.co\n")) == 2)
    add("parse_skips_junk", all(i["kind"] for i in items))
    add("parse_dedupes", len(parse_lines("a@b.co:pw\na@b.co:pw\n")) == 1)

    add("pw_hash", len(_pw_hash("abc")) == 40)
    add("pw_new", _pw_bucket(0) == "NEW")
    add("pw_old", _pw_bucket(50000) == "OLD")
    add("combine_worst", _combine("NEW", "OLD") == "OLD")
    add("unread_not_clean", _addr_bucket({"error": "x", "count": None}) is None)
    add("clean_bucket", _addr_bucket({"count": 0}) == "CLEAN")
    add("stealer_is_new", _addr_bucket({"count": 1, "stealer": 1,
                                        "newest_days": 10}) == "NEW")
    add("old_breach_old", _addr_bucket({"count": 1, "newest_days": 3000}) == "OLD")

    pwn = {"Breaches": [
        {"Name": "June2026StealerLogs", "Title": "June 2026 Stealer Logs",
         "Domain": "", "BreachDate": "2026-06-15", "DataClasses": ["Passwords"],
         "IsStealerLog": True, "PwnCount": 1000},
        {"Name": "Wattpad", "Domain": "wattpad.com", "BreachDate": "2020-06-29",
         "DataClasses": ["Passwords"], "PwnCount": 2000,
         "Description": "\x3ca href='x'\x3elink\x3c/a\x3e text"}],
        "Pastes": [{"Title": "p", "Source": "P"}]}
    rec = _parse_payload({"kind": "combo", "email": "a@b.co", "password": "pw"},
                         pwn, "1.2.3.4:8080", time.time(), "pw")
    add("corpus_split", rec["corpora"] == 1 and rec["sites"] == 1)
    add("stealer_counted", rec["stealer"] == 1)
    add("count_total", rec["count"] == 3)
    add("earliest", rec["earliest_breach"] == "2020-06-29")
    add("latest", rec["latest_breach"] == "2026-06-15")
    add("exposed_sum", rec["total_records_exposed"] == 3000)
    add("html_stripped", "\x3ca" not in rec["breaches"][1]["Description"])
    add("html_kept", "\x3ca" in rec["breaches"][1]["DescriptionHtml"])
    add("password_breaches", "Wattpad" in rec["password_breaches"])
    add("summary_note_counts", "2" in _summary_note({"breach_count": 2}))

    txt, htm = record_view(rec)
    add("view_has_breach", "Wattpad" in txt and "Wattpad" in htm)
    add("view_has_table", "\x3ctable\x3e" in htm)
    add("view_has_css", "\x3cstyle\x3e" in htm and "\x3c/style\x3e" in htm)
    add("view_never_raises", record_view(None) == ("", ""))
    add("view_password_only", "password only" in record_view(
        {"kind": "password", "pw_count": 3})[0])

    add("proxy_parse_auth", (parse_proxy_line("u:p@1.2.3.4:8080") or {}).get("user") == "u")
    add("proxy_parse_plain", (parse_proxy_line("1.2.3.4:8080") or {}).get("port") == 8080)
    add("proxy_reject", parse_proxy_line("nope") is None)
    add("proxy_cfg_server", (_proxy_cfg("1.2.3.4:8080") or {}).get("server")
        == "http://1.2.3.4:8080")

    # ---- rotation and the slot ----
    add("rotate_default", _cfg.get("rotate") is True)
    add("slot_class", callable(_Slot))
    add("slot_reuse_reset", hasattr(_Slot, "reset") and hasattr(_Slot, "get")
        and hasattr(_Slot, "bad") and hasattr(_Slot, "ok"))
    add("slot_limits", SLOT_FAILS_MAX >= 1 and SLOT_USES_MAX >= 1)
    add("slot_has_cf", "cf" in _Slot.__slots__)
    add("warm_helper", callable(_warm))
    add("warm_is_origin", _warm.__doc__ is not None and HIBP_BASE.endswith(".com"))
    add("challenge_mark", "challenge" in CHALLENGE_MARKS)
    add("wait_is_bounded", CHALLENGE_WAIT >= 10.0)
    _s = _Slot()
    for _ in range(SLOT_FAILS_MAX):
        _s.bad()
    add("slot_bad_clears", _s.ctx is None and _s.page is None and _s.cf is False)
    _s2 = _Slot()
    _s2.bad()
    _s2.ok()
    add("slot_ok_resets_fails", _s2.fails == 0)

    _keep_pool, _keep_rot = _cfg.get("pool"), _cfg.get("rotate")
    _cfg["pool"] = ["1.1.1.1:1", "2.2.2.2:2", "3.3.3.3:3"]
    _cfg["rotate"] = False
    _cursor[0] = 0
    _a, _b = _pick_proxy(set()), _pick_proxy(set())
    add("walk_differs", _a != _b and _a in _cfg["pool"] and _b in _cfg["pool"])
    _cfg["rotate"] = True
    add("random_spreads", len({_pick_proxy(set()) for _ in range(60)}) == 3)
    add("avoid_set", _pick_proxy({"1.1.1.1:1", "2.2.2.2:2"}) == "3.3.3.3:3")
    add("avoid_exhausted", _pick_proxy({"1.1.1.1:1", "2.2.2.2:2", "3.3.3.3:3"}) is None)
    _bad["1.1.1.1:1"] = BAD_AFTER
    add("bad_node_skipped", _pick_proxy(set()) in ("2.2.2.2:2", "3.3.3.3:3"))
    _bad.clear()
    _cfg["pool"], _cfg["rotate"] = _keep_pool, _keep_rot
    add("pick_empty_pool", _pick_proxy(set()) is not None or not pool_lines())

    add("configure_takes_workers", "workers" in inspect_sig(configure))
    add("configure_takes_rotate", "rotate" in inspect_sig(configure))
    add("check_many_takes_workers", "workers" in inspect_sig(check_many))
    add("check_many_takes_rotate", "rotate" in inspect_sig(check_many))
    add("check_takes_cancel", "cancel" in inspect_sig(check))
    add("clear_cache_exists", callable(clear_cache))
    add("cache_stats_keys", set(cache_stats()) == {"entries", "bytes", "path"})
    add("page_wanted", page_wanted("records") is True)
    add("js_fetch", "fetch(" in JS_FETCH)
    add("rotate_reported", "rotate" in report())
    add("tag_regex", bool(_TAG_RE.search("\x3cb\x3ex\x3c/b\x3e")))

    _ev = threading.Event()
    add("cancel_false", not _is_cancelled(_ev))
    _ev.set()
    add("cancel_true", _is_cancelled(_ev))

    _was = owner()
    set_owner("aaaa1111")
    add("user_file_prefixed", _user_file(CACHE_NAME) == "aaaa1111_" + CACHE_NAME)
    set_owner("")
    add("owner_empty_falls_back", bool(_user_file(CACHE_NAME)))
    set_owner(_was)

    add("esc", _esc("\x3ca&b\x3e") == _LT + "a" + _AMP + "b" + _GT)
    add("esc_quote", _esc('"') == _QUOT)
    add("report_tier", isinstance(report().get("pool"), int))

    bad = [n for n, ok in checks if not ok]
    if bad:
        raise AssertionError("breach selftest failed: " + ", ".join(bad))
    if verbose:
        print("breach.py selftest: %d checks OK" % len(checks))
    return True


def inspect_sig(fn):
    import inspect
    return inspect.signature(fn).parameters


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--install-browser" in argv:
        ensure_browser(force=True)
        while browser_state()["state"] == "installing":
            time.sleep(2)
        st = browser_state()
        print("browser:", st["state"], st.get("error", ""))
        return 0 if st["state"] == "ready" else 1
    if "--probe" in argv:
        try:
            target = argv[argv.index("--probe") + 1]
        except Exception:
            print("usage: breach.py --probe someone@example.com[:password]")
            return 2
        items = parse_lines(target) or [{"kind": "password", "password": target}]
        res = check_item(items[0], force=True)
        print("pool:", len(pool_lines()), "rotate:", rotating())
        print(json.dumps({k: res.get(k) for k in ("email", "verdict", "addr_verdict",
                                                  "pw_band", "count", "read", "via",
                                                  "error")}, indent=2))
        print(trace_text(limit=40))
        return 0 if res.get("verdict") else 1
    selftest(verbose=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
