"""breach.py - breach exposure and combo freshness.  v13.86

No API key NEEDED, and three sources in order of how much they prove:

    passwords  api.pwnedpasswords.com/range/<5-hex> - k-anonymity, no key, no
               challenge. Returns how many times the password appears in every
               breach HIBP has ever loaded. THIS is the freshness signal for a
               combo: 0 means the password is private, 40,000 means it is an old
               bridge that has been circulating for years.
    address    the HIBP address lookup, keyed when a key is present:
               /api/v3/breachedaccount and /api/v3/pasteaccount with the
               hibp-api-key header, which return BreachDate, DataClasses and
               PwnCount per record. Without a key it falls back to the site's own
               search endpoint, plain HTTP first and a real browser only when
               Cloudflare challenges it.
    catalogue  /api/v3/breaches - one fetch, matched LOCALLY by domain. Kept as
               a fallback for when the address tiers are blocked.

WHY THE KEYED TIER EXISTS  (v13.86)
-----------------------------------
haveibeenpwned.com/unifiedsearch/ now answers 401 to an anonymous urllib call.
A 401 is not a Cloudflare interstitial, so the old code fell straight through to
json.loads("") and reported an EMPTY payload - the site listed ten breaches for
the same address while this module said none. Two things fix it: 401 is now a
wall like 403 and 429, so the browser tier can be sent at it, and the keyed API
answers the same question without any of the ambiguity. The key is read from
HIBP_API_KEY in the environment or in the app secrets and is only ever sent to
haveibeenpwned.com.

WHAT IS ACTUALLY SENT  (v13.85)
-------------------------------
The address endpoint takes an EMAIL and nothing else. A pasted combo arrives as
"a@b.co:hunter2" or "a@b.co | OLD" or "mailto:a@b.co", and every one of those
tails has to come off before the URL is built - a colon is legal inside a path
segment, so "unifiedsearch/a@b.co:hunter2" is a DIFFERENT search, not an error
you would notice. _email_only() is the single funnel: check(), _http_search(),
_blank(), parse_addresses() and the browser pool all pass through it, and the
selftest asserts the transmitted URL equals the bare address. The password
reaches exactly one place, the SHA-1 hash that is split for k-anonymity, and only
5 hex characters of it leave the box.

WHY THE CATALOGUE ALONE COULD NEVER WORK
----------------------------------------
It matches by DOMAIN, and six of the seven breaches on a real address are
stealer-log corpora that HIBP stores with an EMPTY domain - they are keyed by the
site the password was typed into, not by a breach of one site. A domain match can
never fire for them. The catalogue is a fallback now, not the method.

THE BANDS ARE ABOUT FRESHNESS, NOT COUNT
----------------------------------------
"In 40 breaches from 2009" is noise. "Password appeared 3 times, ever" is the
thing you act on. Nothing here scores on PwnCount.

    NEW       password unseen in Pwned Passwords, or address in a corpus < 365d
    PARTIAL   password seen 1-9999 times, or address in a breach < 730d
    OLD       password seen 10000+ times, or address only in breaches > 730d
    CLEAN     password unseen AND address not in any source
    UNKNOWN   nothing readable - the only honest answer when every tier failed

A combo is only as good as its worse half, so the worse of the two halves wins.
A unique password on a burned address is still burned.

TRACING AND PACING  (v13.85)
----------------------------
HIBP is rate limited and the failure modes are quiet - a 403 that looks like an
empty answer, a challenge page that parses as zero breaches, a browser that never
launched. So every step is recorded: what was normalised, whether the cache
answered, the exact URL put on the wire, the status, whether a challenge was
detected, which tier took over, the band, the error. trace() is safe to call from
any thread and swallows everything; trace_read() is what a page renders and
trace_dump() is what it downloads. The ring is bounded and the file is capped.

Pacing is separate from worker count on purpose. Workers bound concurrency;
configure(delay=...) bounds the RATE at which new addresses are started, which is
the thing a WAF counts. The default is 2 seconds between starts.

THE TIER SWITCH  (v13.86)
-------------------------
Both address tiers are worth choosing deliberately, so the tier is configuration,
not an accident: configure(http_only=True) or check(..., allow_browser=False)
runs the address half over plain HTTP and never launches, installs or hands off
to a browser. A challenged address then comes back UNKNOWN with the reason
"http only - browser not tried", which is a different answer from "no browser
installed" and must stay different: one is a choice, the other is a fault.
Passwords are unaffected - Pwned Passwords is a plain HTTP API on a different
host and is checked either way.

check(allow_browser=...) defaults to the CONFIGURED tier. It used to default to
True, and since no caller ever passed False the only way to run HTTP-only did
not exist.

Plain module, NOT frame-gated - like runstate.py and sentinel.py. No Streamlit.
Nothing here renders. EVERY public function swallows: a breach lookup must never
be the reason a page dies.

THE BROWSER BINARY
------------------
The Playwright PACKAGE comes from requirements.txt, but the CHROMIUM BINARY does
not - it is a ~150 MB download and no wheel carries it. ensure_browser() fetches
it once, into <app>/.pw-browsers, guarded by a sentinel and a lock and run on a
daemon thread so the page never blocks on it. PLAYWRIGHT_BROWSERS_PATH is set at
IMPORT, before anything can import playwright, because the driver reads it at
launch time and a late assignment is simply ignored.

The apt libraries Chromium links against come from packages.txt at build time.
If they are missing, launch fails with a missing .so and browser_state() shows
the text - which is why the state is a value on the page and not a log line.

ISOLATION
---------
The cache and the trace file resolve through auth.user_file(), so both are one
file per user. The browser pool is per process (one Chromium) but its pages are
shared round-robin, and every result is keyed by address in the caller's own
dict. The binary is process-wide on purpose: it is the same bytes for everybody.

USAGE
    import breach
    breach.configure(pages=4, delay=2.0)
    breach.ensure_browser()                  # non-blocking, idempotent
    breach.browser_state()                   # for the page to show
    breach.available()                       # False -> HTTP only, no browser
    rec = breach.check("a@b.com", password="hunter2")
    all = breach.check_many(pairs, workers=8, progress=cb, cancel=ev)
    breach.score(all.values())               # old/new breakdown
    breach.parse_addresses(text)             # -> [(email, password)]
    breach.trace_read(limit=100)             # what a page renders
    breach.trace_dump()                      # what a page downloads

    HIBP_API_KEY=xxxx python breach.py --probe someone@example.com:hunter2
    python breach.py --selftest
"""

import concurrent.futures as _cf
import json
import os
import queue
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

# MUST be set before anything imports playwright. setdefault, not assignment, so
# an operator who exports their own path keeps it.
_HERE = os.path.dirname(os.path.abspath(__file__))
_PW_DIR = os.path.join(_HERE, ".pw-browsers")
_PW_SENTINEL = os.path.join(_PW_DIR, ".installed")
os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", _PW_DIR)

HIBP_BASE = "https://haveibeenpwned.com"
UNIFIED = HIBP_BASE + "/unifiedsearch/%s"
ACCOUNT = HIBP_BASE + "/account/%s"
CATALOGUE_URL = HIBP_BASE + "/api/v3/breaches"
PW_RANGE = "https://api.pwnedpasswords.com/range/%s"

# The keyed tier. Same evidence as unifiedsearch, without the interstitial and
# with the fields the site's own JSON drops.
ACCOUNT_API = HIBP_BASE + "/api/v3/breachedaccount/%s?truncateResponse=false"
PASTE_API = HIBP_BASE + "/api/v3/pasteaccount/%s"
KEY_ENV = "HIBP_API_KEY"

PAGE_HTML_MAX = 90000
PAGE_TEXT_MAX = 30000
PAGE_TIMEOUT = 20.0

# WHEN a page is captured. Two modes, because a page costs a second request per
# address and 500 addresses is twice the run.
#   fast  capture only the outcomes named in page_on - "clean" and/or "error"
#   full  capture every address that is checked, records or not
#   off   capture nothing
# page_on is a set of kinds, and "records" is always skipped in fast mode because
# the JSON already carries those titles, dates and data classes.
PAGE_MODE_FAST = "fast"
PAGE_MODE_FULL = "full"
PAGE_MODE_OFF = "off"
PAGE_MODES = (PAGE_MODE_FAST, PAGE_MODE_FULL, PAGE_MODE_OFF)
PAGE_KINDS = ("clean", "error")
PAGE_ON_DEFAULT = ("clean", "error")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36")

HTTP_TIMEOUT = 12.0
NAV_TIMEOUT = 30000
CHALLENGE_WAIT = 30.0
PAGES_DEFAULT = 4
PAGES_MAX = 8
DESC_MAX = 1200
CACHE_NAME = "breach_cache.json"
CACHE_TTL = 6 * 3600.0
CATALOGUE_TTL = 6 * 3600.0
INSTALL_TIMEOUT = 900

# Pacing. One new address may START every DELAY_DEFAULT seconds; workers bound
# concurrency, delay bounds the rate. 0 = flood as fast as the pool allows.
DELAY_DEFAULT = 2.0
DELAY_MAX = 20.0
BROWSER_SETTLE = 700      # ms to sit on a page before the in-page fetch
BROWSER_JITTER = 500      # extra random ms, so two pages never fire together

# Band thresholds in days. Change here and nowhere else.
PW_NEW_MAX = 0          # 0 hits = unseen = NEW
PW_PARTIAL_MAX = 9999
CORPUS_NEW_DAYS = 365
BREACH_PARTIAL_DAYS = 730

CORPORA = frozenset({
    "stealer logs", "synthient stealer log", "synthient credential stuffing",
    "alien txtbase", "combolists posted to telegram", "naz.api", "collection #1",
    "anti public", "exploit.in", "onliner spambot", "big combolist", "cit0day",
    "emotet", "qakbot", "redline", "raccoon", "vidar", "lumma",
})

CHALLENGE_MARKS = (
    "just a moment", "performing security verification", "checking your browser",
    "cf-challenge", "attention required", "verify you are human",
)

RANK = {"NEW": 0, "PARTIAL": 1, "OLD": 2}

# Trace ring. Bounded in memory AND on disk - a page left open for a week must
# not grow either one without limit.
TRACE_MAX = 600
TRACE_NAME = "breach_trace.jsonl"
TRACE_FILE_MAX = 4000
TRACE_DUMP_MAX = 500

_cfg = {"pages": PAGES_DEFAULT, "timeout": 60.0, "delay": DELAY_DEFAULT,
        "http_only": False, "page_mode": PAGE_MODE_FAST,
        "page_on": tuple(PAGE_ON_DEFAULT)}
_lock = threading.Lock()
_pool = None
_pw_missing = ""
_last = {"ts": 0.0, "email": "", "verdict": "", "via": "", "ms": 0, "error": "",
         "url": ""}

_pw_lock = threading.Lock()
_pw_thread = None
_pw_state = {"state": "unknown", "error": "", "started": 0.0, "finished": 0.0}

_key_cache = [""]

_trace_lock = threading.Lock()
_trace_file_lock = threading.Lock()
_trace = []
_trace_seq = [0]
_trace_writes = [0]

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")
_MAILTO_RE = re.compile(r"^mailto:\s*", re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")


# ---------------------------------------------------------------------------
# config
# ---------------------------------------------------------------------------
def configure(pages=None, timeout=None, delay=None, http_only=None,
              page_mode=None, page_on=None):
    """Pool size, per-address budget, start pacing, the tier and the page mode.

    http_only=True disables the browser tier outright: no launch, no install, no
    hand-off. A challenged address comes back UNKNOWN and says why. Never raises.

    page_mode is fast / full / off and page_on names the fast-mode kinds
    ("clean", "error"). An unknown mode is ignored rather than coerced, so a
    typo leaves the previous setting alone instead of silently turning capture
    off.
    """
    with _lock:
        if pages is not None:
            try:
                _cfg["pages"] = max(1, min(PAGES_MAX, int(pages)))
            except Exception:
                pass
        if timeout is not None:
            try:
                _cfg["timeout"] = max(10.0, float(timeout))
            except Exception:
                pass
        if delay is not None:
            try:
                _cfg["delay"] = max(0.0, min(DELAY_MAX, float(delay)))
            except Exception:
                pass
        if http_only is not None:
            _cfg["http_only"] = bool(http_only)
        if page_mode is not None:
            _mode = str(page_mode or "").strip().lower()
            if _mode in PAGE_MODES:
                _cfg["page_mode"] = _mode
        if page_on is not None:
            try:
                _want = [str(x).strip().lower() for x in page_on]
                _cfg["page_on"] = tuple(k for k in PAGE_KINDS if k in _want)
            except Exception:
                pass


def _pages() -> int:
    with _lock:
        return int(_cfg["pages"])


def _delay() -> float:
    with _lock:
        return float(_cfg["delay"])


def _http_only() -> bool:
    with _lock:
        return bool(_cfg.get("http_only"))


def _page_mode() -> str:
    with _lock:
        return str(_cfg.get("page_mode") or PAGE_MODE_FAST)


def _page_on() -> tuple:
    with _lock:
        return tuple(_cfg.get("page_on") or ())


def page_wanted(kind) -> bool:
    """True when an outcome of this kind should be captured.

    kind is "clean", "error" or "records". Full captures everything, off
    captures nothing, and fast captures only what the page ticked. A fast run
    with nothing ticked therefore behaves like off, which is the honest reading
    of an empty selection.
    """
    mode = _page_mode()
    if mode == PAGE_MODE_OFF:
        return False
    if mode == PAGE_MODE_FULL:
        return True
    return str(kind or "") in _page_on()


def _api_key() -> str:
    """HIBP_API_KEY from the environment, else the app secrets. Never raises.

    Read lazily and cached once found, so a key added to secrets does not need
    the module reloaded twice - and a key never reaches the trace, only the URL.
    """
    try:
        k = str(os.environ.get(KEY_ENV) or "").strip()
    except Exception:
        k = ""
    if k:
        return k
    if _key_cache[0]:
        return _key_cache[0]
    try:
        import streamlit as st
        k = str(st.secrets.get(KEY_ENV) or "").strip()
    except Exception:
        k = ""
    if k:
        _key_cache[0] = k
    return k


def key_present() -> bool:
    return bool(_api_key())


# ---------------------------------------------------------------------------
# tracing
# ---------------------------------------------------------------------------
def _trace_path() -> str:
    try:
        import auth
        return auth.user_file(TRACE_NAME)
    except Exception:
        return ""


def _trace_to_file(ev):
    """Append one JSON line and trim the file now and then. Never raises."""
    p = _trace_path()
    if not p:
        return
    try:
        os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
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
    """Record one step. Safe from any thread, swallows everything.

    level is a short tag the page colours by - INFO / WARN / ERR / CLICK.
    """
    try:
        now = time.time()
        with _trace_lock:
            _trace_seq[0] += 1
            ev = {"seq": _trace_seq[0], "ts": round(now, 3),
                  "clock": datetime.fromtimestamp(now).strftime("%H:%M:%S.%f")[:-3],
                  "level": str(level or "INFO")[:8].upper(),
                  "step": str(step or "")[:40],
                  "email": str(email or "")[:120],
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


def trace_read(limit=200, since=0):
    """Events newer than `since`, oldest first. Never raises."""
    try:
        n = max(1, min(TRACE_MAX, int(limit or 200)))
        floor = int(since or 0)
    except Exception:
        n, floor = 200, 0
    with _trace_lock:
        got = [e for e in _trace if e.get("seq", 0) > floor]
    return got[-n:]


def trace_text(limit=200, since=0) -> str:
    """The trace as fixed-width text, for st.code and for a download."""
    rows = []
    for e in trace_read(limit=limit, since=since):
        rows.append("%s %-5s %-12s %-32s %s" % (
            e.get("clock", ""), e.get("level", ""), e.get("step", ""),
            e.get("email", "") or "-", e.get("detail", "")))
    return "\n".join(rows) if rows else "(nothing traced yet)"


def trace_dump() -> str:
    """The file, capped, else the ring. For a download button."""
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
    with _trace_lock:
        _trace.clear()
        _trace_writes[0] = 0


# ---------------------------------------------------------------------------
# the binary
# ---------------------------------------------------------------------------
def _installed() -> bool:
    """True when the sentinel is there and a chromium build is actually present."""
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
    """The blocking install. Runs on its own thread only. Never raises."""
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
                               "chromium"],
                              capture_output=True, text=True,
                              timeout=INSTALL_TIMEOUT, env=env)
        if proc.returncode != 0:
            _tail = ((proc.stderr or "") + (proc.stdout or "")).strip()[-500:]
            with _pw_lock:
                _pw_state = {"state": "failed", "error": _tail or "install exited %d"
                             % proc.returncode, "started": _pw_state["started"],
                             "finished": time.time()}
            trace("ERR", "browser", "install failed: %s" % _tail[:300])
            return
        with open(_PW_SENTINEL, "w", encoding="utf-8") as fh:
            fh.write("ok\n")
        with _pw_lock:
            _pw_state = {"state": "ready", "error": "", "started": _pw_state["started"],
                         "finished": time.time()}
        trace("INFO", "browser", "install finished in %ds"
              % int(time.time() - _pw_state["started"]))
    except Exception as exc:
        with _pw_lock:
            _pw_state = {"state": "failed", "error": "%s: %s"
                         % (type(exc).__name__, exc),
                         "started": _pw_state.get("started", 0.0),
                         "finished": time.time()}
        trace("ERR", "browser", "install raised %s: %s" % (type(exc).__name__, exc))


def ensure_browser(force=False) -> str:
    """Start the one-time install if it is needed. NEVER blocks. Returns state.

    Idempotent: a sentinel means done, a live thread means already running, and a
    previous failure is not retried unless `force` is set. A failed install is a
    real answer - re-running it on every page load would be a 900s download on
    every load.
    """
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
    """What the page needs to say about the browser. Never raises."""
    if _installed():
        return {"state": "ready", "error": "", "path": _PW_DIR,
                "seconds": 0}
    with _pw_lock:
        snap = dict(_pw_state)
    if snap["state"] == "installing" and snap.get("started"):
        snap["seconds"] = int(time.time() - snap["started"])
    else:
        snap["seconds"] = 0
    snap["path"] = _PW_DIR
    return snap


def available() -> bool:
    """True only when Playwright imports AND the binary is installed.

    Cached on the import side. The binary check is a listdir, so it is cached too
    once it succeeds - a pool that is already up cannot lose its browser.
    """
    global _pw_missing
    if _pool is not None:
        return True
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
    """Why the browser tier is unavailable, in words the page can print."""
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
    """The bare address, with every pasted tail cut off. THE only thing HIBP sees.

    A combo can arrive as "a@b.co:pw", "a@b.co | OLD", "mailto:a@b.co",
    "<a@b.co>", "\"a@b.co\":pw", or a re-pasted bucket line. Each tail is legal
    inside a URL path segment, so leaving one on does not raise - it silently
    searches a different string. Everything funnels through here.

    Order matters: the tails come off FIRST, then the wrapping quotes and angle
    brackets, because "a@b.co":pw ends in the password, not in a quote, and a
    strip before the split would leave the quote attached to the address.
    """
    s = str(addr or "").strip().lstrip("\ufeff").strip()
    s = _MAILTO_RE.sub("", s).strip()
    if "|" in s:
        s = s.split("|", 1)[0]
    if ":" in s:
        s = s.split(":", 1)[0]
    s = s.strip().strip("\"'").strip().strip("<>").strip()
    return _norm(s)


def is_email(addr) -> bool:
    return bool(_EMAIL_RE.match(_email_only(addr)))


def domain_of(addr) -> str:
    a = _email_only(addr)
    return a.split("@", 1)[1] if "@" in a else ""


def unified_url(addr) -> str:
    """The exact URL for an address. Quoted, and address-only by construction."""
    return UNIFIED % urllib.parse.quote(_email_only(addr))


def account_url(addr) -> str:
    return ACCOUNT % urllib.parse.quote(_email_only(addr))


def _esc(v) -> str:
    """Minimal HTML escape for the generated view."""
    return (str(v or "").replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def parse_addresses(text):
    """A pasted list -> [(email, password)]. Password may be empty.

    A line is cut at the FIRST '|' then the FIRST ':', and only the left part is
    kept as the address. A line with no password yields ("", password) so an
    address-only list still works. The address goes through _email_only(), not
    _norm(), so a quoted or bracketed line yields the same clean address the
    request will carry.
    """
    out, seen = [], set()
    for raw in str(text or "").splitlines():
        s = raw.strip().lstrip("\ufeff").strip("\"'").strip()
        if not s or s.startswith("#"):
            continue
        if "|" in s:
            s = s.split("|", 1)[0].strip()
        pw = ""
        if ":" in s:
            head, tail = s.split(":", 1)
            s = head.strip()
            pw = tail.strip()
        s = _email_only(s)
        if not s or s in seen or not is_email(s):
            continue
        seen.add(s)
        out.append((s, pw))
    return out


def _days(date_str):
    """Age in days of an ISO date, or None when unusable."""
    if not date_str:
        return None
    txt = str(date_str)[:10]
    try:
        y, m, d = (int(p) for p in txt.split("-"))
        stamp = time.mktime((y, m, d, 0, 0, 0, 0, 0, -1))
        return max(0, int((time.time() - stamp) / 86400))
    except Exception:
        return None


def _is_corpus(breach) -> bool:
    name = str(breach.get("Name") or breach.get("Title") or "").strip().lower()
    if name in CORPORA:
        return True
    if any(k in name for k in ("stealer", "combolist", "credential stuff",
                               "txtbase", "naz.api")):
        return True
    return bool(breach.get("IsSpamList")) and not breach.get("Domain")


def _blank(addr, pw="") -> dict:
    return {"email": _email_only(addr), "password_len": len(pw or ""), "verdict": "",
            "bucket": "", "reason": "", "breaches": [], "pastes": [],
            "pw_count": None, "corpora": 0, "sites": 0, "sensitive": 0,
            "newest_days": None, "count": None, "via": "",
            "page_url": "", "page_html": "", "page_text": "",
            "page_via": "", "page_error": "", "page_at": "",
            "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "error": ""}


def _page_skip(kind) -> dict:
    """The empty page fields for an address whose kind was not selected."""
    return {"page_html": "", "page_text": "", "page_via": "",
            "page_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "page_error": "not captured - %s mode, %s not selected"
                          % (_page_mode(), kind)}


def _page_http(addr, kind="records") -> dict:
    """Best-effort plain-HTTP capture of /account/<email>. Never raises.

    This is the page the site actually renders for an address - breach titles,
    dates, data classes and the "no pwnage found" copy - as opposed to the JSON
    the search box posts. Whether it is fetched at all is page_wanted()'s
    decision, taken from the OUTCOME (clean / error / records) rather than from
    the address, so fast mode can capture exactly the filtered half.

    The page answers 401 to anonymous callers like everything else does now, so
    an empty result here is normal and is why _page_from_record() exists.
    """
    if not page_wanted(kind):
        return _page_skip(kind)
    addr = _email_only(addr)
    url = account_url(addr)
    out = {"page_url": url, "page_html": "", "page_text": "", "page_via": "http",
           "page_error": "",
           "page_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    req = urllib.request.Request(
        url, headers={"Accept": "text/html,application/xhtml+xml",
                      "Accept-Language": "en-GB,en;q=0.9",
                      "User-Agent": UA, "Referer": HIBP_BASE + "/"})
    try:
        with urllib.request.urlopen(req, timeout=PAGE_TIMEOUT) as resp:
            raw = resp.read().decode("utf-8", "replace")
            out["page_html"] = raw[:PAGE_HTML_MAX]
            out["page_text"] = _TAG_RE.sub(" ", raw)[:PAGE_TEXT_MAX]
    except urllib.error.HTTPError as exc:
        out["page_error"] = "http %d" % exc.code
    except Exception as exc:
        out["page_error"] = "%s: %s" % (type(exc).__name__, exc)
    return out


def _page_from_record(rec, kind="records") -> dict:
    """A text and an HTML view BUILT FROM the record. Never raises.

    /account answers 401 to anonymous callers, so a keyed run frequently has no
    page to render. The records are the same evidence, so the view is generated
    from them and marked page_via "api" - it is a report of what the API said,
    not a captured page, and it says so at the foot of the HTML.
    """
    if not page_wanted(kind):
        return _page_skip(kind)
    addr = _email_only(rec.get("email") or "")
    _pw = rec.get("pw_count")
    lines = ["address: %s" % addr,
             "checked: %s" % (rec.get("checked_at") or ""),
             "verdict: %s - %s" % (rec.get("verdict") or "?", rec.get("reason") or ""),
             "password appearances: %s" % (_pw if _pw is not None
                                           else "no password supplied"),
             "source: %s" % (rec.get("via") or "-"),
             "breaches: %d, pastes: %d" % (len(rec.get("breaches") or []),
                                          len(rec.get("pastes") or []))]
    rows = []
    for b in (rec.get("breaches") or [])[:60]:
        lines.append("")
        lines.append("- %s%s" % (b.get("title") or "?",
                                 " [stealer corpus]" if b.get("corpus") else ""))
        if b.get("date"):
            lines.append("  breach date: %s" % b["date"])
        if b.get("days") is not None:
            lines.append("  age: %d day(s)" % int(b["days"]))
        lines.append("  accounts: %s" % "{:,}".format(int(b.get("pwn_count") or 0)))
        if b.get("classes"):
            lines.append("  data: %s" % ", ".join(b["classes"]))
        if b.get("description"):
            lines.append("  %s" % str(b["description"])[:400])
        rows.append(b)
    for p in (rec.get("pastes") or [])[:30]:
        lines.append("")
        lines.append("- paste: %s (%s) %s" % (p.get("title") or "?",
                                              p.get("source") or "-",
                                              p.get("date") or ""))
    text = "\n".join(lines)[:PAGE_TEXT_MAX]

    head = ("<html><head><meta charset='utf-8'><title>%s</title>"
            "<style>body{font-family:system-ui,sans-serif;background:#0b1020;"
            "color:#e6ebff;padding:16px}h1{font-size:1.05rem}h2{font-size:.9rem}"
            "table{border-collapse:collapse;width:100%;font-size:.8rem}"
            "td,th{border:1px solid #2a3350;padding:5px;text-align:left;"
            "vertical-align:top}th{background:#141b30}.c{color:#fcd34d}</style>"
            "</head><body><h1>%s</h1><p class='c'>%s - %s</p>"
            "<p>password appearances: %s<br>source: %s<br>checked: %s</p>"
            % (_esc(addr), _esc(addr), _esc(rec.get("verdict") or "?"),
               _esc(rec.get("reason") or ""),
               _esc(_pw) if _pw is not None else "-", _esc(rec.get("via") or "-"),
               _esc(rec.get("checked_at") or "")))
    body = []
    if rows:
        body.append("<table><tr><th>Breach</th><th>Date</th><th>Age</th>"
                    "<th>Accounts</th><th>Data classes</th></tr>")
        for b in rows:
            body.append(
                "<tr><td>%s%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>"
                % (_esc(b.get("title") or "?"),
                   " (stealer corpus)" if b.get("corpus") else "",
                   _esc(b.get("date") or "-"),
                   "%d d" % int(b["days"]) if b.get("days") is not None else "-",
                   "{:,}".format(int(b.get("pwn_count") or 0)),
                   _esc(", ".join(b.get("classes") or []) or "-")))
        body.append("</table>")
    else:
        body.append("<p>No breach record for this address.</p>")
    if rec.get("pastes"):
        body.append("<h2>Pastes</h2><ul>")
        for p in (rec.get("pastes") or [])[:30]:
            body.append("<li>%s (%s) %s</li>"
                        % (_esc(p.get("title") or "?"), _esc(p.get("source") or "-"),
                           _esc(p.get("date") or "")))
        body.append("</ul>")
    body.append("<p><small>Generated from the API answer, not a captured "
                "page.</small></p></body></html>")
    return {"page_url": account_url(addr),
            "page_html": (head + "".join(body))[:PAGE_HTML_MAX],
            "page_text": text, "page_via": "api", "page_error": "",
            "page_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}


# ---------------------------------------------------------------------------
# cache
# ---------------------------------------------------------------------------
def _path() -> str:
    try:
        import auth
        p = auth.user_file(CACHE_NAME)
    except Exception:
        return ""
    try:
        os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
    except Exception:
        pass
    return p


def _load() -> dict:
    p = _path()
    if not p or not os.path.exists(p):
        return {}
    try:
        with open(p, encoding="utf-8", errors="ignore") as f:
            data = json.load(f)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _save(data: dict) -> None:
    p = _path()
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


# ---------------------------------------------------------------------------
# tier 1 - Pwned Passwords (k-anonymity, keyless, unchallenged)
# ---------------------------------------------------------------------------
def _pw_hash(password) -> str:
    import hashlib
    return hashlib.sha1(str(password or "").encode("utf-8", "replace")).hexdigest().upper()


def pwned_count(password, force=False):
    """Times this password appears in Pwned Passwords, or None if unreadable.

    Only the first five hex characters of the SHA-1 leave the box; the remaining
    35 are matched locally. That is the whole point of k-anonymity and it means
    the password itself is never transmitted.
    """
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
        return None
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
                    n = int(cnt.strip() or 0)
                    break
            if n is None:
                n = 0
    except Exception as exc:
        trace("ERR", "pw", "%s: %s" % (type(exc).__name__, exc))
        return entry.get("n") if entry else None

    cache.setdefault("pw", {})[full] = {"ts": time.time(), "n": n}
    _save(cache)
    return n


# ---------------------------------------------------------------------------
# tier 2 - address exposure
# ---------------------------------------------------------------------------
def _looks_like_challenge(status, body) -> bool:
    """Is this response a wall rather than an answer?

    401 is in the list because the anonymous unifiedsearch endpoint now answers
    401. It used to fall through to json.loads("") and parse as an EMPTY payload,
    so an address with ten breaches was reported as having none - the quietest
    possible failure. A 401 must reach the browser tier like a 403 does.
    """
    if status in (401, 403, 429, 503):
        return True
    low = (body or "")[:4000].lower()
    return any(m in low for m in CHALLENGE_MARKS)


def _parse_payload(addr, payload, via, started, pw) -> dict:
    """Normalised record from a unifiedsearch payload. Pure - used by selftest."""
    rec = _blank(addr, pw)
    rec["via"] = via
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
            "name": str(b.get("Name") or ""),
            "title": str(b.get("Title") or b.get("Name") or "Unnamed")[:160],
            "domain": str(b.get("Domain") or ""),
            "date": str(b.get("BreachDate") or "")[:10],
            "pwn_count": int(b.get("PwnCount") or 0),
            "classes": [str(c) for c in (b.get("DataClasses") or [])][:12],
            "sensitive": bool(b.get("IsSensitive")),
            "corpus": corpus,
            "days": days,
            "description": str(b.get("Description") or "")[:DESC_MAX],
        })
        if corpus:
            rec["corpora"] += 1
        else:
            rec["sites"] += 1
        if b.get("IsSensitive"):
            rec["sensitive"] += 1
        if days is not None:
            if rec["newest_days"] is None or days < rec["newest_days"]:
                rec["newest_days"] = days

    for p in raw_p:
        if not isinstance(p, dict):
            continue
        rec["pastes"].append({
            "title": str(p.get("Title") or "Untitled")[:200],
            "source": str(p.get("Source") or "")[:120],
            "date": str(p.get("Date") or "")[:10],
        })
    rec["count"] = len(rec["breaches"]) + len(rec["pastes"])
    return rec


def _http_search(addr, pw) -> dict:
    addr = _email_only(addr)
    url = unified_url(addr)
    with _lock:
        _last["url"] = url
    started = time.time()
    trace("INFO", "http", "GET %s" % url, addr)
    req = urllib.request.Request(
        url, headers={"Accept": "application/json",
                      "Accept-Language": "en-GB,en;q=0.9",
                      "User-Agent": UA, "Referer": HIBP_BASE + "/"})
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            body = resp.read().decode("utf-8", "replace")
            status = resp.status
            trace("INFO", "http", "http %d (%d byte(s))" % (status, len(body)), addr)
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read().decode("utf-8", "replace")
        except Exception:
            body = ""
        status = exc.code
        trace("WARN", "http", "http %d (%d byte(s))" % (status, len(body)), addr)
    except Exception as exc:
        rec = _blank(addr, pw)
        rec["via"] = "http"
        rec["error"] = "%s: %s" % (type(exc).__name__, exc)
        trace("ERR", "http", "%s: %s" % (type(exc).__name__, exc), addr)
        return rec

    if status == 404:
        trace("INFO", "http", "404 - address in no source", addr)
        rec = _blank(addr, pw)
        rec["via"] = "http"
        rec["count"] = 0
        rec.update(_page_http(addr, "clean"))
        return rec
    if _looks_like_challenge(status, body):
        trace("WARN", "http", "challenge detected (http %d) - browser tier needed"
              % status, addr)
        rec = _blank(addr, pw)
        rec["via"] = "http"
        rec["error"] = "challenge (http %d)" % status
        # The challenged page is still worth keeping: it is the proof the wall
        # exists, and it is what the viewer shows when the tier switch is on.
        rec.update(_page_http(addr, "error"))
        return rec
    try:
        rec = _parse_payload(addr, json.loads(body or "{}"), "http", started, pw)
        trace("INFO", "http", "parsed %s breach(es), %s paste(s)"
              % (len(rec["breaches"]), len(rec["pastes"])), addr)
        rec.update(_page_http(addr, "records" if rec.get("count") else "clean"))
        return rec
    except Exception as exc:
        trace("ERR", "http", "unparsable: %s" % exc, addr)
        rec = _blank(addr, pw)
        rec["via"] = "http"
        rec["error"] = "unparsable: %s" % exc
        rec.update(_page_http(addr, "error"))
        return rec


# ---------------------------------------------------------------------------
# tier 2b - the keyed API (only when HIBP_API_KEY is set)
# ---------------------------------------------------------------------------
def _keyed_search(addr, pw):
    """The keyed API answer, or None to fall through to the keyless tier.

    None means "this tier could not answer": no key, a rejected key, a rate
    limit, an unreadable body or a transport error. The caller then does keyless
    HTTP and, if that is challenged, the browser. A 404 is an ANSWER (no record)
    and returns a normal record with count 0.

    Both endpoints are asked, breached then paste, because the paste list is a
    separate call in v3 and a combo whose address sits in a paste is not clean.
    The two lists are merged into the unifiedsearch shape so _parse_payload, the
    bands and the CSV need no knowledge of this tier at all.
    """
    key = _api_key()
    if not key:
        return None
    addr = _email_only(addr)
    started = time.time()
    hdrs = {"Accept": "application/json", "User-Agent": UA,
            "Accept-Language": "en-GB,en;q=0.9", "hibp-api-key": key}
    payload = {"Breaches": [], "Pastes": []}
    for url, field in ((ACCOUNT_API % urllib.parse.quote(addr), "Breaches"),
                       (PASTE_API % urllib.parse.quote(addr), "Pastes")):
        with _lock:
            _last["url"] = url
        trace("INFO", "api", "GET %s" % url, addr)
        req = urllib.request.Request(url, headers=hdrs)
        try:
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
                body = resp.read().decode("utf-8", "replace")
                status = resp.status
                trace("INFO", "api", "http %d (%d byte(s))"
                      % (status, len(body)), addr)
        except urllib.error.HTTPError as exc:
            status, body = exc.code, ""
            trace("WARN", "api", "http %d" % status, addr)
        except Exception as exc:
            trace("ERR", "api", "%s: %s - falling back"
                  % (type(exc).__name__, exc), addr)
            return None
        if status == 404:
            continue
        if status in (401, 403):
            trace("WARN", "api", "key rejected (http %d) - keyless next" % status, addr)
            return None
        if status == 429:
            trace("WARN", "api", "rate limited (429) - keyless next", addr)
            return None
        if status != 200:
            trace("WARN", "api", "http %d - keyless next" % status, addr)
            return None
        try:
            got = json.loads(body or "[]")
        except Exception as exc:
            trace("ERR", "api", "unparsable: %s" % exc, addr)
            return None
        if isinstance(got, list):
            payload[field] = got

    rec = _parse_payload(addr, payload, "api", started, pw)
    trace("INFO", "api", "keyed answer: %s breach(es), %s paste(s)"
          % (len(rec["breaches"]), len(rec["pastes"])), addr)
    kind = "records" if rec.get("count") else "clean"
    page = _page_http(addr, kind)
    if not (page.get("page_html") or page.get("page_text")):
        _gen = _page_from_record(rec, kind)
        if _gen.get("page_text") or _gen.get("page_html"):
            _gen["page_error"] = page.get("page_error") or ""
            page = _gen
    rec.update(page)
    return rec


# ---------------------------------------------------------------------------
# tier 3 - the browser pool (only reached on a challenge)
# ---------------------------------------------------------------------------
class _BrowserPool:
    """One thread owns Playwright, one browser, one context, N reused pages.

    Playwright's sync API is not thread safe, so the driver lives on its own
    thread and callers wait on a Future. The context is shared so the clearance
    cookie is too, which is the entire reason the tier works.
    """

    def __init__(self, size):
        self._size = max(1, size)
        self._q = queue.Queue()
        self._free = queue.Queue()
        self._thread = None
        self._started = threading.Event()
        self._boot_err = ""
        self._closed = False

    def start(self):
        with _lock:
            if self._thread is not None:
                return
            self._thread = threading.Thread(target=self._run, name="breach-browser",
                                            daemon=True)
            self._thread.start()
        self._started.wait(90)
        if self._boot_err:
            raise RuntimeError(self._boot_err)

    def _run(self):
        pw = browser = context = None
        try:
            from playwright.sync_api import sync_playwright
            trace("INFO", "browser", "launching chromium (%d page(s))" % self._size)
            pw = sync_playwright().start()
            browser = pw.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu",
                      "--disable-blink-features=AutomationControlled"])
            context = browser.new_context(
                user_agent=UA, viewport={"width": 1366, "height": 900},
                locale="en-GB", timezone_id="Europe/London")
            context.add_init_script(
                "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});")
            context.set_default_timeout(NAV_TIMEOUT)
            trace("INFO", "browser", "launched, context armed")
        except Exception as exc:
            self._boot_err = "%s: %s" % (type(exc).__name__, exc)
            trace("ERR", "browser", "launch failed: %s" % self._boot_err)
            self._started.set()
            return

        self._started.set()
        while not self._closed:
            try:
                job = self._q.get(timeout=1.0)
            except queue.Empty:
                continue
            if job is None:
                break
            addr, pw_s, fut = job
            page = None
            try:
                page = self._take(context)
                trace("INFO", "browser", "page taken", addr)
                started = time.time()
                status, body = self._search(page, addr)
                trace("INFO", "browser", "in-page fetch http %d (%d byte(s))"
                      % (status, len(body or "")), addr)
                if status == 404:
                    rec = _blank(addr, pw_s)
                    rec["via"] = "browser"
                    rec["count"] = 0
                elif _looks_like_challenge(status, body):
                    rec = _blank(addr, pw_s)
                    rec["via"] = "browser"
                    rec["error"] = "challenge survived (http %d)" % status
                    trace("WARN", "browser", "challenge survived", addr)
                else:
                    try:
                        rec = _parse_payload(addr, json.loads(body or "{}"),
                                             "browser", started, pw_s)
                        trace("INFO", "browser", "parsed %s breach(es)"
                              % len(rec["breaches"]), addr)
                    except Exception as exc:
                        rec = _blank(addr, pw_s)
                        rec["via"] = "browser"
                        rec["error"] = "unparsable: %s" % exc
                        trace("ERR", "browser", "unparsable: %s" % exc, addr)
                if not rec.get("error", "").startswith("unparsable"):
                    _kind = "records" if rec.get("count") else (
                        "error" if rec.get("error") else "clean")
                    rec.update(self._grab(page, addr, _kind))
                if not fut.done():
                    fut.set_result(rec)
            except Exception as exc:
                if not fut.done():
                    rec = _blank(addr, pw_s)
                    rec["via"] = "browser"
                    rec["error"] = "%s: %s" % (type(exc).__name__, exc)
                    fut.set_result(rec)
                trace("ERR", "browser", "%s: %s" % (type(exc).__name__, exc), addr)
            finally:
                if page is not None:
                    try:
                        if page.is_closed():
                            page = self._new_page(context)
                    except Exception:
                        page = self._new_page(context)
                    if page is not None:
                        self._free.put(page)

        for closer in (context, browser):
            try:
                closer.close()
            except Exception:
                pass
        try:
            pw.stop()
        except Exception:
            pass
        trace("INFO", "browser", "pool stopped")

    def _new_page(self, context):
        try:
            return context.new_page()
        except Exception:
            return None

    def _take(self, context):
        try:
            page = self._free.get_nowait()
            if not page.is_closed():
                return page
        except queue.Empty:
            pass
        page = self._new_page(context)
        if page is None:
            raise RuntimeError("could not open a page")
        return page

    def _clear(self, page):
        """Land on the site and sit out the interstitial."""
        trace("INFO", "browser", "landing on %s/ to clear" % HIBP_BASE)
        page.goto(HIBP_BASE + "/", wait_until="domcontentloaded", timeout=NAV_TIMEOUT)
        deadline = time.time() + CHALLENGE_WAIT
        while time.time() < deadline:
            try:
                title = (page.title() or "").lower()
            except Exception:
                title = ""
            if "pwned" in title and "moment" not in title:
                trace("INFO", "browser", "clearance title: %r" % title[:60])
                return True
            trace("INFO", "browser", "interstitial title: %r" % title[:60])
            page.wait_for_timeout(1500 if any(m in title for m in CHALLENGE_MARKS) else 1200)
        trace("WARN", "browser", "clearance wait expired")
        return True

    def _search(self, page, addr):
        """Fetch from inside the page so the clearance cookie is carried."""
        addr = _email_only(addr)
        status, body = 0, ""
        for attempt in (0, 1):
            if "haveibeenpwned.com" not in (page.url or ""):
                self._clear(page)
            # Settle, so consecutive pages do not fire in lockstep. This is the
            # "slow" part of the browser tier and it is deliberate.
            try:
                page.wait_for_timeout(BROWSER_SETTLE + random.randint(0, BROWSER_JITTER))
            except Exception:
                pass
            try:
                out = page.evaluate(
                    """async (email) => {
                        const r = await fetch('/unifiedsearch/' +
                            encodeURIComponent(email),
                            {headers: {'Accept': 'application/json'}});
                        return {status: r.status, body: await r.text()};
                    }""", addr)
                status, body = int(out.get("status") or 0), out.get("body") or ""
                trace("INFO", "browser", "attempt %d -> http %d" % (attempt + 1, status),
                      addr)
            except Exception as exc:
                status, body = 0, ""
                trace("WARN", "browser", "attempt %d raised %s"
                      % (attempt + 1, type(exc).__name__), addr)
            if status and not _looks_like_challenge(status, body):
                return status, body
            if attempt == 0:
                self._clear(page)
        return status, body

    def _grab(self, page, addr, kind="records"):
        """Navigate to the address's own page and keep the markup. Never raises.

        The clearance cookie is already on this context, so the navigation is
        the same tier as the fetch above it - and it is the only way to capture
        the page on an address Cloudflare challenges. The kind gate is applied
        before the navigation, so a skipped capture costs no round trip.
        """
        if not page_wanted(kind):
            return _page_skip(kind)
        addr = _email_only(addr)
        url = account_url(addr)
        out = {"page_url": url, "page_html": "", "page_text": "", "page_via": "browser",
               "page_error": "",
               "page_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
        try:
            page.goto(url, wait_until="domcontentloaded",
                      timeout=int(PAGE_TIMEOUT * 1000))
            markup = page.content() or ""
            out["page_html"] = markup[:PAGE_HTML_MAX]
            out["page_text"] = _TAG_RE.sub(" ", markup)[:PAGE_TEXT_MAX]
        except Exception as exc:
            out["page_error"] = "%s: %s" % (type(exc).__name__, exc)
        return out

    def submit(self, addr, pw):
        addr = _email_only(addr)
        fut = _cf.Future()
        self._q.put((addr, pw, fut))
        trace("INFO", "browser", "queued in pool", addr)
        return fut

    def stop(self):
        self._closed = True
        self._q.put(None)


def _get_pool():
    global _pool
    with _lock:
        if _pool is None:
            _pool = _BrowserPool(_pages())
        pool = _pool
    pool.start()
    return pool


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
    if rec.get("error"):
        return None
    if not rec.get("count"):
        return "CLEAN"
    if rec.get("corpora"):
        nd = rec.get("newest_days")
        if nd is not None and nd <= CORPUS_NEW_DAYS:
            return "NEW"
        return "PARTIAL"
    nd = rec.get("newest_days")
    if nd is None:
        return "PARTIAL"
    return "PARTIAL" if nd <= BREACH_PARTIAL_DAYS else "OLD"


def _combine(pw_b, addr_b):
    """The worse half wins. CLEAN only when every readable half is CLEAN."""
    known = [b for b in (pw_b, addr_b) if b in RANK]
    if known:
        return max(known, key=lambda b: RANK[b])
    if pw_b == "CLEAN" or addr_b == "CLEAN":
        return "CLEAN"
    return "UNKNOWN"


_REASON = {
    "NEW": "password unseen in Pwned Passwords, or exposure inside %d days" % CORPUS_NEW_DAYS,
    "PARTIAL": "password already circulating, or exposure inside %d days" % BREACH_PARTIAL_DAYS,
    "OLD": "password has been public for years, or only old breaches",
    "CLEAN": "password unseen and address in no readable source",
    "UNKNOWN": "no readable answer - every source failed",
}


# ---------------------------------------------------------------------------
# the check
# ---------------------------------------------------------------------------
def check(addr, password="", force=False, allow_browser=None) -> dict:
    """One address. Pwned Passwords, then address exposure. Never raises.

    v13.86: allow_browser DEFAULTS TO THE CONFIGURED TIER. It defaulted to True
    and no caller ever passed False, so configure(http_only=True) could not have
    worked even once the page had a switch.

    The address half is tried in order of how much it proves: the keyed API when
    a key is set, then the keyless endpoint, then the browser on a challenge. The
    first two are the same evidence; the key only removes the ambiguity.
    """
    if allow_browser is None:
        allow_browser = not _http_only()
    raw = addr
    addr = _email_only(addr)
    if not is_email(addr):
        rec = _blank(addr, password)
        rec["verdict"] = rec["bucket"] = "UNKNOWN"
        rec["reason"] = rec["error"] = "not an email address"
        trace("WARN", "address", "rejected %r - not an email" % str(raw)[:80])
        return rec
    trace("INFO", "address", "using %r, password %s, tier %s, pages %s"
          % (addr, "kept (hash only)" if password else "absent",
             "http+browser" if allow_browser else "http-only",
             _page_mode() if _page_mode() != PAGE_MODE_FAST
             else "fast(%s)" % (",".join(_page_on()) or "none")), addr)

    cache = _load()
    entry = (cache.get("address") or {}).get(addr)
    if not force and _fresh(entry, CACHE_TTL):
        got = dict(entry.get("report") or {})
        if got:
            trace("INFO", "cache", "hit, verdict %s - no request sent"
                  % got.get("verdict"), addr)
            return got

    rec = _blank(addr, password)
    rec["pw_count"] = pwned_count(password, force=force)
    trace("INFO", "pw", "result: %s" % ("no password" if rec["pw_count"] is None
                                        else "%d hit(s)" % rec["pw_count"]), addr)

    addr_rec = None
    if _api_key():
        addr_rec = _keyed_search(addr, password)
        if addr_rec is not None:
            trace("INFO", "api", "answered by the keyed tier", addr)
        else:
            trace("WARN", "api", "keyed tier did not answer - keyless HTTP next", addr)
    if addr_rec is None:
        addr_rec = _http_search(addr, password)
    if addr_rec.get("error", "").startswith("challenge"):
        if allow_browser and available():
            try:
                pool = _get_pool()
                trace("INFO", "browser", "handing off to the browser tier", addr)
                addr_rec = pool.submit(addr, password).result(timeout=_cfg["timeout"])
            except Exception as exc:
                rec["error"] = "browser failed: %s: %s" % (type(exc).__name__, exc)
                trace("ERR", "browser", rec["error"], addr)
        elif not allow_browser:
            # A CHOICE, not a fault - and it must not read like one, so the
            # marker is distinct from the missing-binary text below.
            addr_rec["error"] += " | http only - browser not tried"
            trace("WARN", "browser", "skipped by the tier switch (HTTP only)", addr)
        else:
            # Kick the install so the NEXT press has a browser, and say which of
            # the two reasons it was: a missing binary is not a blocked site.
            if not available():
                ensure_browser()
            addr_rec["error"] += " | no browser (%s)" % browser_note()
            trace("WARN", "browser", "not used: %s" % browser_note(), addr)

    rec["breaches"] = addr_rec.get("breaches") or []
    rec["pastes"] = addr_rec.get("pastes") or []
    rec["corpora"] = addr_rec.get("corpora", 0)
    rec["sites"] = addr_rec.get("sites", 0)
    rec["sensitive"] = addr_rec.get("sensitive", 0)
    rec["newest_days"] = addr_rec.get("newest_days")
    rec["count"] = addr_rec.get("count")
    rec["via"] = addr_rec.get("via", "")
    rec["error"] = addr_rec.get("error", "")
    rec["elapsed_ms"] = addr_rec.get("elapsed_ms", 0)
    for _k in ("page_url", "page_html", "page_text", "page_via", "page_error",
               "page_at"):
        if _k in addr_rec:
            rec[_k] = addr_rec[_k]

    rec["bucket"] = _combine(_pw_bucket(rec["pw_count"]), _addr_bucket(addr_rec))
    rec["verdict"] = rec["bucket"]
    rec["reason"] = _REASON.get(rec["bucket"], "")
    if rec["bucket"] == "UNKNOWN" and not rec["error"]:
        rec["error"] = "no readable answer"
    trace("INFO", "band", "%s (%s) - pw %s, addr %s, %d ms"
          % (rec["bucket"], rec["reason"] or "-", rec["pw_count"],
             addr_rec.get("via") or "-", rec["elapsed_ms"]), addr)

    if rec["bucket"] != "UNKNOWN":
        cache.setdefault("address", {})[addr] = {"ts": time.time(), "report": rec}
        _save(cache)
    _remember(rec)
    return rec


def _remember(rec):
    with _lock:
        _last.update({"ts": time.time(), "email": rec.get("email", ""),
                      "verdict": rec.get("verdict", ""), "via": rec.get("via", ""),
                      "ms": rec.get("elapsed_ms", 0), "error": rec.get("error", "")})


def last_url() -> str:
    """The exact address URL last put on the wire - the proof the tail was cut."""
    with _lock:
        return _last.get("url", "")


def check_many(pairs, workers=4, progress=None, cancel=None, force=False,
               delay=None, http_only=None) -> dict:
    """Check every (email, password) pair. Returns {email: record}.

    Paced on purpose: `workers` bounds concurrency, `delay` bounds the rate at
    which NEW addresses are started. A pool of 8 that starts 8 at once is what a
    WAF sees as a burst; a pool of 8 that starts one every two seconds is not.

    v13.86: `http_only` reaches check() as allow_browser=False, and the tier is
    written into the run line so a trace says how its rows were reached.
    """
    ho = _http_only() if http_only is None else bool(http_only)
    uniq, seen = [], set()
    for item in pairs or []:
        if isinstance(item, (tuple, list)) and item:
            em, pw = item[0], (item[1] if len(item) > 1 else "")
        else:
            em, pw = item, ""
        em = _email_only(em)
        if em and em not in seen:
            seen.add(em)
            uniq.append((em, str(pw or "")))
    out, guard, done = {}, threading.Lock(), [0]
    total = len(uniq)
    pace = _delay() if delay is None else max(0.0, float(delay or 0.0))
    trace("INFO", "run", "start: %d unique address(es), workers=%d, pace=%ss, tier=%s"
          % (total, max(1, int(workers or 1)), pace,
             "http-only" if ho else "http+browser"))
    if not total:
        return out

    def one(item):
        em, pw = item
        if cancel is not None and cancel.is_set():
            rec = _blank(em, pw)
            rec["verdict"] = rec["bucket"] = "UNKNOWN"
            rec["error"] = "cancelled"
            trace("WARN", "cancel", "cancelled before the check", em)
        else:
            trace("INFO", "start", "checking", em)
            rec = check(em, pw, force=force, allow_browser=not ho)
        with guard:
            out[em] = rec
            done[0] += 1
            n = done[0]
        if progress is not None:
            try:
                progress(n, total, em, rec.get("verdict", ""))
            except Exception:
                pass

    width = max(1, min(16, int(workers or 1)))
    try:
        with _cf.ThreadPoolExecutor(max_workers=width) as ex:
            inflight = set()
            for item in uniq:
                inflight.add(ex.submit(one, item))
                step = 0.0 if (cancel is not None and cancel.is_set()) else pace
                if step:
                    time.sleep(step)
                if len(inflight) >= width:
                    _done, inflight = _cf.wait(inflight,
                                               return_when=_cf.FIRST_COMPLETED)
            while inflight:
                _done, inflight = _cf.wait(inflight,
                                           return_when=_cf.FIRST_COMPLETED)
    except Exception as exc:
        trace("ERR", "run", "executor failed (%s), falling back to serial"
              % type(exc).__name__)
        for item in uniq:
            out.setdefault(item[0], check(item[0], item[1], force=force,
                                          allow_browser=not ho))
    trace("INFO", "run", "finished: %d record(s)" % len(out))
    return out


# ---------------------------------------------------------------------------
# scoring
# ---------------------------------------------------------------------------
WEIGHTS = {"NEW": 1.0, "PARTIAL": 0.5, "OLD": 0.15}


def score(records) -> dict:
    """Old/new breakdown and a quality figure for a set of records."""
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
    return {"version": BREACH_VERSION, "browser": available(),
            "browser_state": browser_state().get("state", ""),
            "browser_error": browser_note(), "pages": _pages(), "delay": _delay(),
            "http_only": _http_only(), "pool": _pool is not None,
            "key": bool(_api_key()),
            "page_mode": _page_mode(), "page_on": list(_page_on()),
            "last": dict(_last), "trace_seq": trace_seq()}


# ---------------------------------------------------------------------------
# selftest / probe
# ---------------------------------------------------------------------------
def selftest(verbose=False) -> bool:
    checks = []

    def add(n, ok):
        checks.append((n, bool(ok)))

    add("is_email", is_email("a.b@c.co"))
    add("not_email", not is_email("nope"))
    add("domain_of", domain_of("A@B.com") == "b.com")
    add("norm", _norm(" A@B.CO ") == "a@b.co")

    # ---- the address funnel: nothing but the address may survive it ----
    add("only_colon", _email_only("a@b.co:hunter2") == "a@b.co")
    add("only_pipe", _email_only("a@b.co | OLD") == "a@b.co")
    add("only_both", _email_only("a@b.co:hunter2 | OLD") == "a@b.co")
    add("only_mailto", _email_only("mailto:a@b.co") == "a@b.co")
    add("only_angle", _email_only("<a@b.co>") == "a@b.co")
    add("only_quoted", _email_only("\"a@b.co\":pw") == "a@b.co")
    add("only_bom", _email_only("\ufeffa@b.co") == "a@b.co")
    add("only_upper", _email_only(" A@B.CO:pw ") == "a@b.co")
    add("is_email_combo", is_email("a@b.co:hunter2"))
    add("url_no_password", unified_url("a@b.co:hunter2") ==
        HIBP_BASE + "/unifiedsearch/a%40b.co")
    add("url_quotes", unified_url("a+b@c.co") == HIBP_BASE + "/unifiedsearch/a%2Bb%40c.co")
    add("blank_email_only", _blank("a@b.co:pw")["email"] == "a@b.co")
    add("blank_has_page", "page_html" in _blank("a@b.co"))

    configure(page_mode=PAGE_MODE_FAST, page_on=PAGE_KINDS)
    add("fast_default_on", _page_mode() == PAGE_MODE_FAST)
    add("fast_captures_clean", page_wanted("clean"))
    add("fast_captures_error", page_wanted("error"))
    add("fast_skips_records", not page_wanted("records"))
    configure(page_on=("clean",))
    add("fast_clean_only", page_wanted("clean") and not page_wanted("error"))
    configure(page_on=())
    add("fast_nothing", not page_wanted("clean") and not page_wanted("error"))
    add("skip_is_note", "not captured" in _page_skip("clean")["page_error"])
    configure(page_mode=PAGE_MODE_FULL)
    add("full_everything", page_wanted("records") and page_wanted("clean"))
    configure(page_mode=PAGE_MODE_OFF)
    add("off_nothing", not page_wanted("records"))
    configure(page_mode="nonsense")
    add("mode_ignored", _page_mode() == PAGE_MODE_OFF)
    configure(page_mode=PAGE_MODE_FAST, page_on=PAGE_ON_DEFAULT)

    add("parse_no_pw_in_addr", parse_addresses("a@b.co:pw")[0][0] == "a@b.co")
    add("parse_quoted", parse_addresses("\"a@b.co\":pw")[0][0] == "a@b.co")

    pairs = parse_addresses("a@b.co:pw\n- c@d.co:pw2 | VALID\njunk\nA@B.co:x")
    add("parse_count", len(pairs) == 2)
    add("parse_keeps_pw", pairs[0][1] == "pw")
    add("parse_cuts_tail", pairs[1][1] == "pw2")
    add("parse_dedupes", pairs[0][0] == "a@b.co")

    add("pw_new", _pw_bucket(0) == "NEW")
    add("pw_partial", _pw_bucket(500) == "PARTIAL")
    add("pw_old", _pw_bucket(50000) == "OLD")
    add("pw_none", _pw_bucket(None) is None)

    add("combine_worst", _combine("NEW", "OLD") == "OLD")
    add("combine_clean", _combine("CLEAN", "CLEAN") == "CLEAN")
    add("combine_clean_old", _combine("CLEAN", "OLD") == "OLD")
    add("combine_unknown", _combine(None, None) == "UNKNOWN")
    add("combine_one_side", _combine("PARTIAL", None) == "PARTIAL")

    pwn = {"Breaches": [
        {"Name": "Stealer Logs", "Title": "Stealer Logs", "Domain": "",
         "BreachDate": "2026-06-01", "DataClasses": ["Passwords"],
         "IsSpamList": True, "Description": "d"},
        {"Name": "MyFitnessPal", "Title": "MyFitnessPal", "Domain": "myfitnesspal.com",
         "BreachDate": "2018-02-01", "DataClasses": ["Passwords"]}],
        "Pastes": [{"Title": "dump.txt", "Source": "Pastebin"}]}
    rec = _parse_payload("a@b.co", pwn, "http", time.time(), "pw")
    add("corpus_split", rec["corpora"] == 1 and rec["sites"] == 1)
    add("count_total", rec["count"] == 3)
    add("paste_kept", len(rec["pastes"]) == 1)
    add("addr_bucket_corpus_new", _addr_bucket(rec) == "NEW")

    old = _parse_payload("a@b.co", {"Breaches": [
        {"Name": "X", "Domain": "x.com", "BreachDate": "2015-01-01"}]}, "http", None, "")
    add("addr_bucket_old", _addr_bucket(old) == "OLD")

    clean = _parse_payload("a@b.co", {"Breaches": [], "Pastes": []}, "http", None, "")
    add("addr_bucket_clean", _addr_bucket(clean) == "CLEAN")

    bad = _blank("a@b.co")
    bad["error"] = "challenge (http 403)"
    add("addr_bucket_error_none", _addr_bucket(bad) is None)

    add("days_ok", _days("2020-01-01") is not None)
    add("days_bad", _days("") is None)

    sc = score([{"verdict": "OLD"}, {"verdict": "NEW"}, {"verdict": "UNKNOWN"}])
    add("score_total", sc["total"] == 3)
    add("score_pct", sc["pct"]["UNKNOWN"] == 33.3)
    add("score_grade", sc["grade"] in "ABCDF")

    add("challenge_403", _looks_like_challenge(403, ""))
    add("challenge_401", _looks_like_challenge(401, ""))
    add("challenge_401_json", _looks_like_challenge(401, '{"Breaches":[]}'))
    add("challenge_404_clear", not _looks_like_challenge(404, ""))
    add("challenge_html", _looks_like_challenge(200, "<title>Just a moment...</title>"))
    add("challenge_json", not _looks_like_challenge(200, '{"Breaches":[]}'))
    add("pw_hash", len(_pw_hash("abc")) == 40)
    add("report_shape", isinstance(report().get("browser"), bool))
    add("state_shape", "state" in browser_state())
    add("note_is_str", isinstance(browser_note(), str))
    add("env_set", os.environ.get("PLAYWRIGHT_BROWSERS_PATH") == _PW_DIR)

    # ---- the keyed tier ----
    add("key_shape", isinstance(_api_key(), str))
    add("keyed_account_url", "breachedaccount" in ACCOUNT_API and
        ACCOUNT_API.startswith(HIBP_BASE))
    add("keyed_paste_url", "pasteaccount" in PASTE_API)
    add("keyed_truncate", "truncateResponse=false" in ACCOUNT_API)
    add("keyed_header_name", KEY_ENV == "HIBP_API_KEY")
    _pr = {"email": "a@b.co", "verdict": "OLD", "reason": "r", "via": "api",
           "pw_count": 3, "breaches": [{"title": "X", "date": "2015-01-01",
                                        "days": 4000, "pwn_count": 12,
                                        "classes": ["Passwords"]}],
           "pastes": [], "checked_at": "2026-01-01 00:00:00"}
    _gen = _page_from_record(_pr, "clean")
    add("gen_text", "breaches: 1" in _gen["page_text"] and "X" in _gen["page_text"])
    add("gen_html", "<table" in _gen["page_html"] and "2015-01-01" in _gen["page_html"])
    add("gen_marked", _gen["page_via"] == "api")
    add("gen_skipped", _page_from_record(_pr, "records")["page_text"] == "")
    add("esc", _esc("<a&b>") == "&lt;a&amp;b&gt;")

    # ---- pacing and tracing ----
    configure(delay=3.5)
    add("delay_set", _delay() == 3.5)
    configure(delay=DELAY_DEFAULT)
    add("delay_clamped", 0.0 <= _delay() <= DELAY_MAX)
    add("delay_default_on", DELAY_DEFAULT > 0)

    import inspect
    add("configure_takes_http_only",
        "http_only" in inspect.signature(configure).parameters)
    add("configure_takes_page_mode",
        "page_mode" in inspect.signature(configure).parameters)
    add("configure_takes_page_on",
        "page_on" in inspect.signature(configure).parameters)
    add("check_many_takes_http_only",
        "http_only" in inspect.signature(check_many).parameters)
    add("ensure_browser_declares_pw_state",
        "_pw_state" in inspect.getsource(ensure_browser).split("\n")[1])
    configure(http_only=True)
    add("http_only_on", _http_only() is True)
    configure(http_only=False)
    add("http_only_off", _http_only() is False)
    configure(http_only=None)
    add("http_only_untouched", _http_only() is False)

    before = trace_seq()
    trace("INFO", "selftest", "hello")
    got = trace_read(limit=5, since=before)
    add("trace_recorded", len(got) == 1 and got[0]["step"] == "selftest")
    add("trace_text_shape", "selftest" in trace_text(limit=5, since=before))
    add("trace_dump_shape", isinstance(trace_dump(), str))

    bad_names = [n for n, ok in checks if not ok]
    if bad_names:
        raise AssertionError("breach selftest failed: " + ", ".join(bad_names))
    if verbose:
        print("breach.py selftest: %d checks OK" % len(checks))
    return True


def main(argv=None) -> int:
    import sys
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
            print("usage: breach.py --probe someone@example.com[:password] "
                  "[--http-only]")
            return 2
        only = "--http-only" in argv
        configure(http_only=only)
        pairs = parse_addresses(target) or [(target, "")]
        print("tier:", "http-only" if only else "http+browser")
        print("key:", "present" if _api_key() else "absent")
        print("browser available:", available(), browser_note())
        res = check(pairs[0][0], pairs[0][1], force=True)
        print("url sent:", last_url())
        print(json.dumps({k: res.get(k) for k in ("email", "verdict", "pw_count",
                                                  "count", "via", "error")}, indent=2))
        print(trace_text(limit=40))
        return 0 if res.get("verdict") else 1
    selftest(verbose=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
