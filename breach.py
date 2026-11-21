"""breach.py - breach exposure and combo freshness.  v13.86

CLEARANCE IS A COOKIE, NOT A GUESS  (this pass)
-----------------------------------------------
A log showed the fetch being declared "wall cleared, retrying" SIX MILLISECONDS
after a 401:

    04:51:58.605  attempt 1 -> http 401
    04:51:58.611  wall cleared, retrying
    04:51:58.627  attempt 2 -> http 401

The root page had only been open 4.2s. _solve_wall() asked _wall(), which reads
the title and body - and a page still loading has neither interstitial mark, so
"no wall" was returned and the retry fired before the challenge had even
appeared. Every fetch then 401'd and the visual fallback walked into the wall.

cf_clearance is the arbiter now. No cookie -> solve first, and again between
attempts; "cleared" means the cookie EXISTS, or the wall has been absent twice
running. A slot also warms up at boot, so the cookie is on disk before address 1.

THE TURNSTILE CLICK  (this pass)
--------------------------------
frame_locator() on a shadow-hosted cross-origin iframe returned False on every
attempt - there was no "clicked the challenge widget" line in any run. The frames
are iterated directly now (page.frames, URL match) and clicked inside, with a
mouse click on the iframe's own geometry as a fallback.

BOTH HALVES ARE SHOWN  (this pass)
----------------------------------
With a password supplied, PARTIAL came from 1,902 password hits while the address
half was never read, and the card never said which half produced the verdict - so
a clean address looked like a breach. Every record now carries `addr_verdict` and
`pw_band`, the card prints both, and the header badge shows the ADDRESS verdict
when no password was supplied, because then the address IS the verdict.

THE FAST PATH
-------------
The site's own XHR succeeds while the visual page is a wall - a trace showed
`settled: wall` and `10 breach(es)` in the same breath. So the browser tier calls
the endpoint from INSIDE the page (same cookies, same origin, no CORS) and only
scrapes the DOM when the fetch is refused.

THE REST
--------
Three sources in order of proof: Pwned Passwords (k-anonymity, keyless), the
address, the catalogue. A combo is only as good as its worse half. Bands are about
freshness, not count:

    NEW       password unseen, or address in a corpus < 365d
    PARTIAL   password seen 1-9999 times, or address in a breach < 730d
    OLD       password seen 10000+ times, or address only in breaches > 730d
    CLEAN     password unseen AND address in no source
    UNKNOWN   nothing readable - the only honest answer when every tier failed

count 0 and count None are different facts and `read` says which. Screenshots are
JPEG files on disk, referenced by path, so no base64 sits in session state.

One thread per page, reused tab, persistent profile. Jobs go to the least busy
slot. Stop is honoured inside the browser wait. _lock is an RLock, the page count
is read outside it, and the config is snapshotted per run. Cache, trace, state and
shots resolve through the pinned owner; the binary, the pool and its profiles are
process-wide on purpose.

Plain module, NOT frame-gated. No Streamlit. EVERY public function swallows.
"""

import concurrent.futures as _cf
import json
import os
import queue
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
_PROFILE_DIR = os.path.join(_HERE, ".pw-profile")
os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", _PW_DIR)

HIBP_BASE = "https://haveibeenpwned.com"
UNIFIED = HIBP_BASE + "/unifiedsearch/%s"
ACCOUNT = HIBP_BASE + "/account/%s"
CATALOGUE_URL = HIBP_BASE + "/api/v3/breaches"
PW_RANGE = "https://api.pwnedpasswords.com/range/%s"

ACCOUNT_API = HIBP_BASE + "/api/v3/breachedaccount/%s?truncateResponse=false"
PASTE_API = HIBP_BASE + "/api/v3/pasteaccount/%s"
KEY_ENV = "HIBP_API_KEY"

UI_SEARCH_SELECTORS = (
    "input#searchInput",
    "form input[type='email']",
    "form input[type='search']",
    "form input[type='text']",
    "input[type='search']",
    "input[type='email']",
    "input[type='text']",
)
TURNSTILE_SELECTORS = (
    "iframe[src*='challenges.cloudflare.com']",
    "div#challenge-stage iframe",
    "iframe[title*='challenge' i]",
    "iframe[title*='turnstile' i]",
)

NAV_POLL = 8.0
NAV_STEP = 250
RESULT_WAIT = 15.0
CHALLENGE_WAIT = 20.0
FETCH_TRIES = 3
WARM_SETTLE = 1500
INTERSTITIAL_MARKS = ("just a moment", "checking your browser", "verify you are human",
                      "performing security verification", "attention required",
                      "cf-challenge", "verifying...", "security service to protect")

JS_FETCH = """async (u) => {
  try {
    const r = await fetch(u, {credentials: 'include',
                              headers: {'Accept': 'application/json'}});
    let t = '';
    try { t = await r.text(); } catch (e) { t = ''; }
    return {status: r.status, body: t};
  } catch (e) { return {status: 0, body: String(e)}; }
}"""

JS_READ = """() => {
  const seen = new Set();
  const links = [];
  const push = (el, href) => {
    if (!el) return;
    const t = (el.textContent || '').trim();
    if (!t || seen.has(t)) return;
    seen.add(t);
    links.push({t: t, h: href || ''});
  };
  Array.from(document.querySelectorAll("a[href*='/breach/']"))
    .forEach(a => push(a, a.getAttribute('href') || ''));
  if (!links.length) {
    Array.from(document.querySelectorAll("[class*='pwned'], [class*='breach']"))
      .forEach(el => {
        if (el.querySelector("[class*='pwned'], [class*='breach']")) return;
        const a = el.querySelector('a[href]');
        push(el, a ? (a.getAttribute('href') || '') : '');
      });
  }
  const body = document.body;
  return {links: links,
          text: body ? (body.innerText || '') : '',
          html: document.documentElement ? document.documentElement.outerHTML : ''};
}"""

STEALTH_JS = ("Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
              "Object.defineProperty(navigator,'languages',"
              "{get:()=>['en-GB','en']});"
              "Object.defineProperty(navigator,'plugins',{get:()=>[1,2,3,4,5]});"
              "window.chrome={runtime:{}};")

PAGE_HTML_MAX = 60000
PAGE_TEXT_MAX = 20000
PAGE_SHOT_MAX = 1500000
PAGE_TIMEOUT = 12.0

PAGE_MODE_FAST = "fast"
PAGE_MODE_FULL = "full"
PAGE_MODE_OFF = "off"
PAGE_MODES = (PAGE_MODE_FAST, PAGE_MODE_FULL, PAGE_MODE_OFF)
PAGE_KINDS = ("clean", "error")
PAGE_ON_DEFAULT = ("clean", "error")

_PAGE_CSS = ("<style>body{font-family:system-ui,sans-serif;background:#0b1020;"
             "color:#e6ebff;padding:16px}h1{font-size:1.05rem}h2{font-size:.9rem}"
             "table{border-collapse:collapse;width:100%;font-size:.8rem}"
             "td,th{border:1px solid #2a3350;padding:5px;text-align:left;"
             "vertical-align:top}th{background:#141b30}.c{color:#fcd34d}</style>")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36")

HTTP_TIMEOUT = 8.0
NAV_TIMEOUT = 20000
BOOT_WAIT = 90.0
BOOT_RETRY_AFTER = 60.0
PAGES_DEFAULT = 2
PAGES_MAX = 8
DESC_MAX = 1200
CACHE_NAME = "breach_cache.json"
CACHE_TTL = 6 * 3600.0
CATALOGUE_TTL = 6 * 3600.0
INSTALL_TIMEOUT = 900

DELAY_DEFAULT = 1.0
DELAY_MAX = 20.0

PW_NEW_MAX = 0
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

CLEAN_MARKS = ("no pwnage", "good news", "not been pwned", "no breaches found",
               "hasn't been pwned", "has not been pwned")

RANK = {"NEW": 0, "PARTIAL": 1, "OLD": 2}

TRACE_MAX = 1500
TRACE_NAME = "breach_trace.jsonl"
TRACE_FILE_MAX = 4000
TRACE_DUMP_MAX = 500

_cfg = {"pages": PAGES_DEFAULT, "timeout": 180.0, "delay": DELAY_DEFAULT,
        "http_only": False, "page_mode": PAGE_MODE_FAST,
        "page_on": tuple(PAGE_ON_DEFAULT)}
_lock = threading.RLock()
_pool = None
_pool_boot_failed = 0.0
_pool_boot_err = ""
_pw_missing = ""

_tls = threading.local()
_lasts = {}

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
_ISO_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_D_MONTH_Y = re.compile(r"\b(\d{1,2})\s+([A-Za-z]{3,9})\.?\s+(\d{4})\b")
_CLASSES_RE = re.compile(r"compromised data:?\s*([^\n]{0,200})", re.IGNORECASE)
_COUNT_RE = re.compile(r"([\d][\d,]{3,})\s+accounts", re.IGNORECASE)
_MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
           "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}


def _is_cancelled(cancel):
    try:
        return bool(cancel is not None and cancel.is_set())
    except Exception:
        return False


def _await_future(fut, cancel, budget):
    end = time.time() + max(5.0, float(budget))
    while time.time() < end:
        try:
            return fut.result(timeout=0.4), False
        except _cf.TimeoutError:
            pass
        if _is_cancelled(cancel):
            return None, True
    raise TimeoutError("budget expired")


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
def configure(pages=None, timeout=None, delay=None, http_only=None,
              page_mode=None, page_on=None):
    with _lock:
        if pages is not None:
            try:
                _cfg["pages"] = max(1, min(PAGES_MAX, int(pages)))
            except Exception:
                pass
        if timeout is not None:
            try:
                _cfg["timeout"] = max(30.0, float(timeout))
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


def _cfg_get(key, default=None):
    snap = getattr(_tls, "cfg", None)
    if isinstance(snap, dict) and key in snap:
        return snap[key]
    with _lock:
        return _cfg.get(key, default)


def _snapshot_cfg(http_only=None) -> dict:
    with _lock:
        snap = {"pages": int(_cfg["pages"]), "delay": float(_cfg["delay"]),
                "timeout": float(_cfg["timeout"]),
                "http_only": bool(_cfg.get("http_only")),
                "page_mode": str(_cfg.get("page_mode") or PAGE_MODE_FAST),
                "page_on": tuple(_cfg.get("page_on") or ())}
    if http_only is not None:
        snap["http_only"] = bool(http_only)
    return snap


def _pin_cfg(snap) -> None:
    _tls.cfg = snap if isinstance(snap, dict) else None


def _budget() -> float:
    try:
        return max(30.0, float(_cfg_get("timeout", 180.0)))
    except Exception:
        return 180.0


def _pages() -> int:
    try:
        return max(1, int(_cfg_get("pages", PAGES_DEFAULT)))
    except Exception:
        return PAGES_DEFAULT


def _delay() -> float:
    try:
        return max(0.0, float(_cfg_get("delay", DELAY_DEFAULT)))
    except Exception:
        return DELAY_DEFAULT


def _http_only() -> bool:
    return bool(_cfg_get("http_only", False))


def _page_mode() -> str:
    return str(_cfg_get("page_mode", PAGE_MODE_FAST) or PAGE_MODE_FAST)


def _page_on() -> tuple:
    got = _cfg_get("page_on", ())
    try:
        return tuple(got or ())
    except Exception:
        return ()


def page_wanted(kind) -> bool:
    mode = _page_mode()
    if mode == PAGE_MODE_OFF:
        return False
    if mode == PAGE_MODE_FULL:
        return True
    return str(kind or "") in _page_on()


def _api_key() -> str:
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
    if snap["state"] == "installing" and snap.get("started"):
        snap["seconds"] = int(time.time() - snap["started"])
    else:
        snap["seconds"] = 0
    snap["path"] = _PW_DIR
    return snap


def available() -> bool:
    global _pw_missing
    if _pool is not None and not _pool_boot_failed:
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
    if _pool_boot_failed:
        return ("chromium launch failed %ds ago (%s) - not retried yet"
                % (int(time.time() - _pool_boot_failed),
                   _pool_boot_err or "see trace"))
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
    s = s.strip().strip("\"'").strip().strip("<>").strip()
    return _norm(s)


def is_email(addr) -> bool:
    return bool(_EMAIL_RE.match(_email_only(addr)))


def domain_of(addr) -> str:
    a = _email_only(addr)
    return a.split("@", 1)[1] if "@" in a else ""


def unified_url(addr) -> str:
    return UNIFIED % urllib.parse.quote(_email_only(addr))


def account_url(addr) -> str:
    return ACCOUNT % urllib.parse.quote(_email_only(addr))


def _clean_url(url) -> str:
    u = str(url or "")
    return u.split("?", 1)[0] if "?" in u else u


def _esc(v) -> str:
    return (str(v or "").replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def _shot_path(addr) -> str:
    key = re.sub(r"[^a-z0-9]+", "_", _email_only(addr)).strip("_")[:60] or "row"
    return os.path.join(_user_dir("shots"), key + ".jpg")


def parse_addresses(text):
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


def _parse_rendered(text, links):
    txt = str(text or "")
    low = txt.lower()
    out, seen = [], set()
    for item in (links or [])[:80]:
        name = str((item or {}).get("t") or "").strip()
        if not name:
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        idx = low.find(key)
        window = txt[idx: idx + 600] if idx >= 0 else ""
        date = _any_date(window)
        cls = _CLASSES_RE.search(window)
        cnt = _COUNT_RE.search(window)
        classes = []
        if cls:
            classes = [c.strip() for c in cls.group(1).split(",") if c.strip()][:12]
        out.append({
            "name": name, "title": name[:160], "domain": "",
            "date": date,
            "pwn_count": int(cnt.group(1).replace(",", "")) if cnt else 0,
            "classes": classes, "sensitive": False,
            "corpus": _is_corpus({"Title": name}),
            "days": _days(date), "description": "",
        })
    clean = (not out) and any(m in low for m in CLEAN_MARKS)
    return out, clean


def _blank(addr, pw="") -> dict:
    return {"email": _email_only(addr), "password_len": len(pw or ""), "verdict": "",
            "bucket": "", "reason": "", "breaches": [], "pastes": [],
            "pw_count": None, "corpora": 0, "sites": 0, "sensitive": 0,
            "newest_days": None, "count": None, "via": "",
            "read": False, "partial_read": False,
            "addr_verdict": "UNREAD", "pw_band": "none",
            "page_url": "", "page_html": "", "page_text": "", "page_shot_file": "",
            "page_via": "", "page_error": "", "page_at": "",
            "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "error": ""}


def _page_skip(kind) -> dict:
    return {"page_html": "", "page_text": "", "page_via": "",
            "page_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "page_error": "not captured - %s mode, %s not selected"
                          % (_page_mode(), kind)}


def _page_http(addr, kind="records") -> dict:
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
        try:
            raw = exc.read().decode("utf-8", "replace")
            if raw:
                out["page_html"] = raw[:PAGE_HTML_MAX]
                out["page_text"] = _TAG_RE.sub(" ", raw)[:PAGE_TEXT_MAX]
        except Exception:
            pass
    except Exception as exc:
        out["page_error"] = "%s: %s" % (type(exc).__name__, exc)
    return out


def _page_from_record(rec, kind="records", force=False) -> dict:
    if not force and not page_wanted(kind):
        return _page_skip(kind)
    addr = _email_only(rec.get("email") or "")
    _pw = rec.get("pw_count")
    lines = ["address: %s" % addr,
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

    head = ("<html><head><meta charset='utf-8'><title>%s</title>%s</head>"
            "<body><h1>%s</h1><p class='c'>%s - %s</p>"
            "<p>address half: %s<br>password half: %s<br>password appearances: %s"
            "<br>source: %s<br>checked: %s</p>"
            % (_esc(addr), _PAGE_CSS, _esc(addr), _esc(rec.get("verdict") or "?"),
               _esc(rec.get("reason") or ""), _esc(rec.get("addr_verdict") or "UNREAD"),
               _esc(rec.get("pw_band") or "none"),
               _esc(_pw) if _pw is not None else "-", _esc(rec.get("via") or "-"),
               _esc(rec.get("checked_at") or "")))
    body = []
    if rec.get("error"):
        body.append("<p class='c'>error: %s</p>" % _esc(rec["error"]))
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
        body.append("<p>%s</p>"
                    % ("No breach record could be read - see the error above."
                       if rec.get("error") else "No breach record for this address."))
    if rec.get("pastes"):
        body.append("<h2>Pastes</h2><ul>")
        for p in (rec.get("pastes") or [])[:30]:
            body.append("<li>%s (%s) %s</li>"
                        % (_esc(p.get("title") or "?"), _esc(p.get("source") or "-"),
                           _esc(p.get("date") or "")))
        body.append("</ul>")
    body.append("<p><small>Generated from the answer, not a captured "
                "page.</small></p></body></html>")
    return {"page_url": account_url(addr),
            "page_html": (head + "".join(body))[:PAGE_HTML_MAX],
            "page_text": text, "page_via": "api", "page_error": "",
            "page_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}


def record_view(rec):
    try:
        page = _page_from_record(rec or {}, "records", force=True)
        return (str(page.get("page_text") or ""),
                str(page.get("page_html") or ""))
    except Exception:
        return "", ""


def _fill_page(page, got, addr, kind="records") -> dict:
    if not page_wanted(kind):
        return _page_skip(kind)
    if got is None:
        try:
            got = page.evaluate(JS_READ) or {}
        except Exception:
            got = {}
    return {"page_url": account_url(addr),
            "page_html": str(got.get("html") or "")[:PAGE_HTML_MAX],
            "page_text": str(got.get("text") or "")[:PAGE_TEXT_MAX],
            "page_via": "browser", "page_error": "",
            "page_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}


# ---------------------------------------------------------------------------
# cache
# ---------------------------------------------------------------------------
def _path() -> str:
    p = _user_file(CACHE_NAME)
    if not p:
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
# tier 1 - Pwned Passwords
# ---------------------------------------------------------------------------
def _pw_hash(password) -> str:
    import hashlib
    return hashlib.sha1(str(password or "").encode("utf-8", "replace")).hexdigest().upper()


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
    if status in (401, 403, 429, 503):
        return True
    low = (body or "")[:4000].lower()
    return any(m in low for m in CHALLENGE_MARKS)


def _parse_payload(addr, payload, via, started, pw) -> dict:
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
    _remember({"email": addr, "url": url})
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
# tier 2b - the OPTIONAL keyed API
# ---------------------------------------------------------------------------
def _keyed_search(addr, pw):
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
        _remember({"email": addr, "url": url})
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
# tier 3 - a SLOT per page
# ---------------------------------------------------------------------------
class _Slot:
    """One worker: own thread, own Playwright, own browser, one reused tab."""

    def __init__(self, index):
        self.index = index
        self.q = queue.Queue()
        self.thread = None
        self.pw = None
        self.context = None
        self.page = None
        self.started = threading.Event()
        self.boot_err = ""
        self.retired = False

    def spawn(self):
        with _lock:
            if self.thread is not None and self.thread.is_alive():
                return
            self.boot_err = ""
            self.started.clear()
            self.thread = threading.Thread(target=self._run, daemon=True,
                                           name="breach-slot-%d" % self.index)
            self.thread.start()

    def wait_ready(self):
        self.started.wait(BOOT_WAIT)
        if self.boot_err:
            raise RuntimeError(self.boot_err)

    def _boot(self):
        from playwright.sync_api import sync_playwright
        prof = os.path.join(_PROFILE_DIR, "slot%d" % self.index)
        os.makedirs(prof, exist_ok=True)
        self.pw = sync_playwright().start()
        args = ["--no-sandbox", "--no-zygote", "--disable-dev-shm-usage",
                "--disable-gpu", "--disable-blink-features=AutomationControlled",
                "--disable-extensions", "--disable-background-networking",
                "--disable-sync", "--mute-audio", "--no-first-run",
                "--no-default-browser-check"]
        opts = dict(user_data_dir=prof, headless=True, args=args, user_agent=UA,
                    viewport={"width": 1280, "height": 900}, locale="en-GB",
                    timezone_id="Europe/London")
        try:
            self.context = self.pw.chromium.launch_persistent_context(
                channel="chromium", **opts)
        except Exception:
            self.context = self.pw.chromium.launch_persistent_context(**opts)
        self.context.add_init_script(STEALTH_JS)
        self.context.set_default_timeout(NAV_TIMEOUT)
        self.page = (self.context.pages[0] if self.context.pages
                     else self.context.new_page())
        # WARM UP: land on the site and clear once, before any job. The cookie
        # then exists for address 1 instead of being paid for on it.
        try:
            if not self._has_clearance():
                trace("INFO", "browser", "slot %d warming up" % self.index)
                self.page.goto(HIBP_BASE + "/", wait_until="domcontentloaded",
                               timeout=NAV_TIMEOUT)
                self._sleep(self.page, WARM_SETTLE)
                self._solve_wall(self.page)
                if self._has_clearance():
                    trace("INFO", "browser", "slot %d holds clearance" % self.index)
                else:
                    trace("WARN", "browser", "slot %d has no clearance yet" % self.index)
        except Exception as exc:
            trace("WARN", "browser", "slot %d warm-up failed: %s"
                  % (self.index, type(exc).__name__))

    def _run(self):
        try:
            self._boot()
        except Exception as exc:
            self.boot_err = "%s: %s" % (type(exc).__name__, exc)
            trace("ERR", "browser", "slot %d launch failed: %s"
                  % (self.index, self.boot_err))
            self.started.set()
            return
        self.started.set()
        trace("INFO", "browser", "slot %d ready" % self.index)
        while True:
            try:
                job = self.q.get(timeout=1.0)
            except queue.Empty:
                if self.retired:
                    break
                continue
            if job is None:
                break
            self._handle(job)
            if self.retired and self.q.empty():
                break
        try:
            self.context.close()
        except Exception:
            pass
        try:
            self.pw.stop()
        except Exception:
            pass
        trace("INFO", "browser", "slot %d stopped" % self.index)

    def _page(self):
        try:
            if self.page is not None and not self.page.is_closed():
                return self.page
        except Exception:
            pass
        self.page = self.context.new_page()
        return self.page

    def _handle(self, job):
        addr, pw_s, fut, job_owner, cancel = job
        if _is_cancelled(cancel):
            rec = _blank(addr, pw_s)
            rec["via"] = "browser"
            rec["error"] = "cancelled before the page"
            if not fut.done():
                fut.set_result(rec)
            return
        set_owner(job_owner)
        try:
            page = self._page()
            trace("INFO", "browser", "page taken", addr)
            started = time.time()
            status, body, state = self._ask(page, addr, cancel)
            got = None
            if state == "cancelled":
                rec = _blank(addr, pw_s)
                rec["via"] = "browser"
                rec["error"] = "cancelled during the browser step"
            elif status == 200 and body:
                try:
                    rec = _parse_payload(addr, json.loads(body), "browser",
                                         started, pw_s)
                    trace("INFO", "browser", "answered by the page fetch: %s "
                          "breach(es)" % len(rec["breaches"]), addr)
                    got = self._read(page)
                except Exception as exc:
                    trace("WARN", "browser", "fetch body unparsable (%s) - scraping"
                          % type(exc).__name__, addr)
                    rec, got = self._dom_record(page, addr, pw_s)
            elif status == 404:
                rec = _blank(addr, pw_s)
                rec["via"] = "browser"
                rec["count"] = 0
                got = self._read(page)
            elif state == "records":
                rec, got = self._dom_record(page, addr, pw_s)
            elif state == "clean":
                rec = _blank(addr, pw_s)
                rec["via"] = "browser"
                rec["count"] = 0
                got = self._read(page)
            elif state == "wall":
                rec, got = self._dom_record(page, addr, pw_s)
                if rec.get("error"):
                    rec["error"] = "challenge wall (http %d) - %s" % (status,
                                                                     rec["error"])
                trace("WARN", "browser", "challenge wall, dom read: %s"
                      % ("empty" if rec.get("error") else "ok"), addr)
            else:
                rec, got = self._dom_record(page, addr, pw_s)

            if rec.get("error") or rec.get("count") is not None:
                kind = ("records" if rec.get("count") else
                        ("error" if rec.get("error") else "clean"))
                if page_wanted(kind):
                    _shot = self._shot(page, addr)
                    if _shot:
                        rec["page_shot_file"] = _shot
                rec.update(_fill_page(page, got, addr, kind))
            if not fut.done():
                fut.set_result(rec)
        except Exception as exc:
            if not fut.done():
                rec = _blank(addr, pw_s)
                rec["via"] = "browser"
                rec["error"] = "%s: %s" % (type(exc).__name__, exc)
                fut.set_result(rec)
            trace("ERR", "browser", "%s: %s" % (type(exc).__name__, exc), addr)

    def _read(self, page):
        try:
            return page.evaluate(JS_READ) or {}
        except Exception as exc:
            trace("WARN", "browser", "read failed: %s" % type(exc).__name__)
            return {}

    def _shot(self, page, addr):
        try:
            raw = page.screenshot(full_page=True, type="jpeg", quality=72)
        except Exception as exc:
            trace("WARN", "browser", "screenshot failed: %s" % type(exc).__name__)
            return ""
        if not raw or len(raw) > PAGE_SHOT_MAX:
            return ""
        try:
            p = _shot_path(addr)
            with open(p, "wb") as fh:
                fh.write(raw)
            return p
        except Exception:
            return ""

    def _sleep(self, page, ms):
        try:
            page.wait_for_timeout(ms)
        except Exception:
            time.sleep(ms / 1000.0)

    def _wall(self, page):
        try:
            title = (page.title() or "").lower()
        except Exception:
            title = ""
        if any(m in title for m in INTERSTITIAL_MARKS):
            return True
        try:
            low = (page.evaluate(
                "() => document.body ? (document.body.innerText || '').slice(0, 1500)"
                " : ''") or "").lower()
        except Exception:
            low = ""
        return any(m in low for m in INTERSTITIAL_MARKS)

    def _has_clearance(self):
        """True when the context actually holds cf_clearance for the site.

        THIS is the arbiter. The old code asked _wall() six milliseconds after a
        401, on a page that had not finished loading - no marks, "no wall",
        retry, 401, give up. A cookie cannot be faked by timing.
        """
        try:
            for c in self.context.cookies():
                if (c.get("name") == "cf_clearance"
                        and "haveibeenpwned.com" in str(c.get("domain") or "")):
                    return True
        except Exception:
            pass
        return False

    def _click_turnstile(self, page):
        """Click inside the Turnstile frame. Cross-origin frames are reachable by
        iterating page.frames; a frame_locator on a shadow-hosted iframe is not
        and returned False on every attempt in the log."""
        for fr in list(page.frames):
            try:
                if "challenges.cloudflare.com" not in (fr.url or ""):
                    continue
            except Exception:
                continue
            for sel in ("input[type='checkbox']", "#challenge-stage", "body"):
                try:
                    if sel == "body":
                        fr.click(sel, timeout=1200, position={"x": 20, "y": 20})
                    else:
                        fr.click(sel, timeout=1200)
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

    def _solve_wall(self, page, cancel=None):
        """Clear the interstitial. True only on evidence, never on a guess."""
        deadline = time.time() + CHALLENGE_WAIT
        last = 0.0
        clear_streak = 0
        while time.time() < deadline:
            if _is_cancelled(cancel):
                return False
            if self._has_clearance():
                return True
            if not self._wall(page):
                clear_streak += 1
                if clear_streak >= 2:
                    return True
            else:
                clear_streak = 0
                if time.time() - last > 3.0:
                    last = time.time()
                    if self._click_turnstile(page):
                        trace("INFO", "browser", "clicked the challenge widget")
            self._sleep(page, 700)
        return self._has_clearance() or not self._wall(page)

    def _fetch(self, page, addr):
        try:
            got = page.evaluate(JS_FETCH, unified_url(addr)) or {}
        except Exception as exc:
            trace("WARN", "browser", "fetch failed: %s" % type(exc).__name__, addr)
            return 0, ""
        return int(got.get("status") or 0), str(got.get("body") or "")

    def _ask(self, page, addr, cancel=None):
        """Fetch first, solve on refusal, fetch again, then fall back visually."""
        addr = _email_only(addr)
        try:
            if "haveibeenpwned.com" not in (page.url or ""):
                trace("INFO", "browser", "landing on %s/" % HIBP_BASE, addr)
                page.goto(HIBP_BASE + "/", wait_until="domcontentloaded",
                          timeout=NAV_TIMEOUT)
                self._sleep(page, WARM_SETTLE)
        except Exception:
            pass

        if not self._has_clearance():
            trace("INFO", "browser", "no clearance - solving before the fetch", addr)
            self._solve_wall(page, cancel)

        status, body = 0, ""
        for attempt in range(FETCH_TRIES):
            if _is_cancelled(cancel):
                return 0, "", "cancelled"
            status, body = self._fetch(page, addr)
            trace("INFO", "fetch", "attempt %d -> http %d (clearance %s)"
                  % (attempt + 1, status, "yes" if self._has_clearance() else "no"),
                  addr)
            if status in (200, 404):
                return status, body, ("records" if status == 200 else "clean")
            if attempt + 1 >= FETCH_TRIES:
                break
            if self._has_clearance():
                # Cookie present but the XHR was still refused: give the edge a beat.
                self._sleep(page, 900)
            elif not self._solve_wall(page, cancel):
                trace("WARN", "browser", "wall did not clear - fetch will fail", addr)
                break

        if _is_cancelled(cancel):
            return 0, "", "cancelled"
        try:
            trace("WARN", "ui", "fetch refused (http %d) - visual fallback" % status,
                  addr)
            page.goto(account_url(addr), wait_until="domcontentloaded",
                      timeout=NAV_TIMEOUT)
        except Exception as exc:
            trace("ERR", "ui", "%s: %s" % (type(exc).__name__, exc), addr)
            return status, body, "blank"
        trace("INFO", "ui", "landed on %s" % _clean_url(page.url or "-")[:140], addr)
        state, n = self._wait_result(page, cancel)
        trace("INFO", "ui", "settled: %s (%s breach link(s))" % (state, n), addr)
        return status, body, state

    def _wait_result(self, page, cancel=None):
        soft = time.time() + RESULT_WAIT
        while True:
            if _is_cancelled(cancel):
                return "cancelled", 0
            if self._wall(page):
                if not self._solve_wall(page, cancel):
                    return ("cancelled", 0) if _is_cancelled(cancel) else ("wall", 0)
                soft = time.time() + RESULT_WAIT
                continue
            try:
                n = page.evaluate(
                    "() => document.querySelectorAll(\"a[href*='/breach/']\").length")
            except Exception:
                n = 0
            if n:
                return "records", int(n)
            try:
                low = (page.evaluate(
                    "() => document.body ? (document.body.innerText || '') : ''"
                ) or "").lower()
            except Exception:
                low = ""
            if any(m in low for m in CLEAN_MARKS):
                return "clean", 0
            if time.time() >= soft:
                try:
                    page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
                except Exception:
                    pass
                self._sleep(page, 400)
                try:
                    n = page.evaluate(
                        "() => document.querySelectorAll(\"a[href*='/breach/']\").length")
                except Exception:
                    n = 0
                return ("records", int(n)) if n else ("blank", 0)
            self._sleep(page, 300)

    def _dom_record(self, page, addr, pw):
        rec = _blank(addr, pw)
        rec["via"] = "browser"
        try:
            page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(350)
            page.evaluate("() => window.scrollTo(0, 0)")
        except Exception:
            pass
        got = self._read(page)
        text = str(got.get("text") or "")
        url = page.url or ""
        if "/account/" not in url:
            rec["error"] = "did not reach the account page (%s)" % (url[:80] or "-")
            return rec, got
        breaches, clean = _parse_rendered(text, got.get("links"))
        if breaches:
            rec["breaches"] = breaches
            rec["count"] = len(breaches)
            for b in breaches:
                if b.get("corpus"):
                    rec["corpora"] += 1
                else:
                    rec["sites"] += 1
                d = b.get("days")
                if d is not None and (rec["newest_days"] is None
                                      or d < rec["newest_days"]):
                    rec["newest_days"] = d
            trace("INFO", "browser", "scraped %d breach(es) from the rendered page"
                  % len(breaches), addr)
            return rec, got
        if clean:
            rec["count"] = 0
            trace("INFO", "browser", "rendered page says no pwnage", addr)
            return rec, got
        rec["error"] = "page rendered but no breach block was readable"
        trace("WARN", "browser", rec["error"], addr)
        return rec, got


class _BrowserPool:
    def __init__(self, size):
        self._lock = threading.Lock()
        self._slots = []
        self._size = 0
        self.resize(size)

    def resize(self, n):
        try:
            n = max(1, min(PAGES_MAX, int(n)))
        except Exception:
            return
        with self._lock:
            while len(self._slots) < n:
                self._slots.append(_Slot(len(self._slots)))
            for s in self._slots[n:]:
                s.retired = True
            for s in self._slots[:n]:
                s.retired = False
            self._size = n

    def start(self):
        with self._lock:
            slots = list(self._slots)
        for s in slots:
            s.spawn()
        errs = []
        for s in slots:
            try:
                s.wait_ready()
            except Exception as exc:
                errs.append(str(exc))
        if errs and len(errs) == len(slots):
            raise RuntimeError(errs[0])
        if errs:
            trace("WARN", "browser", "%d of %d slot(s) failed: %s"
                  % (len(errs), len(slots), errs[0][:200]))

    def _pick(self):
        with self._lock:
            live = [s for s in self._slots if not s.retired] or list(self._slots)
        best, depth = None, None
        for s in live:
            d = s.q.qsize()
            if depth is None or d < depth:
                best, depth = s, d
                if d == 0:
                    break
        return best

    def submit(self, addr, pw, job_owner=None, cancel=None):
        addr = _email_only(addr)
        fut = _cf.Future()
        slot = self._pick()
        if slot is None:
            raise RuntimeError("no browser slot")
        slot.q.put((addr, pw, fut, owner() if job_owner is None else job_owner,
                    cancel))
        trace("INFO", "browser", "queued in slot %d" % slot.index, addr)
        return fut

    def stop(self):
        with self._lock:
            slots = list(self._slots)
        for s in slots:
            s.q.put(None)


def _get_pool():
    global _pool, _pool_boot_failed
    size = _pages()
    with _lock:
        if _pool is None:
            _pool = _BrowserPool(size)
        pool = _pool
    failed_ago = (time.time() - _pool_boot_failed) if _pool_boot_failed else 0.0
    if failed_ago and failed_ago < BOOT_RETRY_AFTER:
        raise RuntimeError("browser boot failed %ds ago - not retried yet"
                           % int(failed_ago))
    try:
        pool.start()
    except Exception:
        _pool_boot_failed = time.time()
        raise
    pool.resize(size)
    _pool_boot_failed = 0.0
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
def check(addr, password="", force=False, allow_browser=None, cancel=None) -> dict:
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
            trace("WARN", "api", "keyed tier did not answer - keyless next", addr)
    if addr_rec is None:
        addr_rec = _http_search(addr, password)
    if addr_rec.get("error", "").startswith("challenge") and not _is_cancelled(cancel):
        if allow_browser and available():
            try:
                pool = _get_pool()
                trace("INFO", "browser", "handing off to the browser tier (UI)", addr)
                _res, was_cancelled = _await_future(
                    pool.submit(addr, password, cancel=cancel), cancel, _budget())
                if was_cancelled:
                    addr_rec["error"] += " | cancelled during the browser step"
                    trace("WARN", "browser", "cancelled during the browser step", addr)
                else:
                    addr_rec = _res
                    _wall = "challenge wall" in str(addr_rec.get("error") or "")
                    _cut = "TimeoutError" in str(addr_rec.get("error") or "")
                    if (not addr_rec.get("breaches") and addr_rec.get("error")
                            and not _cut and not _wall
                            and not _is_cancelled(cancel)):
                        trace("WARN", "browser", "empty read - one retry", addr)
                        _again, _wc = _await_future(
                            pool.submit(addr, password, cancel=cancel), cancel,
                            _budget())
                        if not _wc and (_again.get("breaches")
                                        or not _again.get("error")):
                            addr_rec = _again
            except Exception as exc:
                addr_rec["error"] += (" | browser failed: %s: %s"
                                      % (type(exc).__name__, exc))
                trace("ERR", "browser", "browser failed: %s: %s"
                      % (type(exc).__name__, exc), addr)
        elif not allow_browser:
            addr_rec["error"] += " | http only - browser not tried"
            trace("WARN", "browser", "skipped by the tier switch (HTTP only)", addr)
        else:
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
    rec["read"] = bool(addr_rec.get("count") is not None
                       and not addr_rec.get("error"))
    rec["partial_read"] = bool(not rec["read"] and rec.get("pw_count") is not None)
    for _k in ("page_url", "page_html", "page_text", "page_shot_file", "page_via",
               "page_error", "page_at"):
        if _k in addr_rec:
            rec[_k] = addr_rec[_k]

    if not (rec.get("page_text") or rec.get("page_html")):
        try:
            _kind = ("records" if rec.get("count")
                     else ("error" if rec.get("error") else "clean"))
            _gen = _page_from_record(rec, _kind, force=True)
            for _k in ("page_url", "page_html", "page_text", "page_via",
                       "page_error", "page_at"):
                if _gen.get(_k):
                    rec[_k] = _gen[_k]
        except Exception:
            pass

    # BOTH HALVES, LABELLED. addr_verdict is what the ADDRESS said (or UNREAD);
    # pw_band is what the PASSWORD said. Without them a clean address wearing a
    # circulating password reads as a breached address.
    _ab = _addr_bucket(addr_rec)
    rec["addr_verdict"] = _ab or ("UNREAD" if not rec["read"] else "UNKNOWN")
    rec["pw_band"] = _pw_bucket(rec["pw_count"]) or "none"
    rec["bucket"] = _combine(_pw_bucket(rec["pw_count"]), _ab)
    rec["verdict"] = rec["bucket"]
    rec["reason"] = _REASON.get(rec["bucket"], "")
    if rec["bucket"] == "UNKNOWN" and not rec["error"]:
        rec["error"] = "no readable answer"
    trace("INFO", "band", "%s (%s) - addr %s, pw %s, %d ms"
          % (rec["bucket"], rec["reason"] or "-", rec["addr_verdict"],
             rec["pw_band"], rec["elapsed_ms"]), addr)

    if rec["bucket"] != "UNKNOWN":
        _slim = dict(rec)
        _slim.pop("page_html", None)
        cache.setdefault("address", {})[addr] = {"ts": time.time(), "report": _slim}
        _save(cache)
    _remember(rec)
    return rec


def _remember(rec):
    with _lock:
        who = owner()
        cur = _lasts.get(who) or {}
        cur.update({"ts": time.time(), "email": rec.get("email", ""),
                    "verdict": rec.get("verdict", ""), "via": rec.get("via", ""),
                    "ms": rec.get("elapsed_ms", 0), "error": rec.get("error", ""),
                    "url": rec.get("url") or cur.get("url", "")})
        _lasts[who] = cur


def last_url() -> str:
    with _lock:
        return (_lasts.get(owner()) or {}).get("url", "")


def check_many(pairs, workers=2, progress=None, cancel=None, force=False,
               delay=None, http_only=None, owner_prefix=None) -> dict:
    pin = owner() if owner_prefix is None else str(owner_prefix or "")
    set_owner(pin)
    snap = _snapshot_cfg(http_only)
    _pin_cfg(snap)
    ho = bool(snap.get("http_only"))
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
    pace = float(snap.get("delay") if delay is None else max(0.0, float(delay or 0.0)))
    trace("INFO", "run", "start: %d unique address(es), workers=%d, pace=%ss, tier=%s"
          % (total, max(1, int(workers or 1)), pace,
             "http-only" if ho else "http+browser"))
    if not total:
        return out

    def _tell(n, em, verdict):
        if progress is not None:
            try:
                progress(n, total, em, verdict)
            except Exception:
                pass

    def one(item, position):
        set_owner(pin)
        _pin_cfg(snap)
        em, pw = item
        rec = None
        if _is_cancelled(cancel):
            rec = _blank(em, pw)
            rec["verdict"] = rec["bucket"] = "UNKNOWN"
            rec["error"] = "cancelled"
            trace("WARN", "cancel", "cancelled before the check", em)
        else:
            trace("INFO", "start", "checking", em)
            _tell(position, em, "starting")
            try:
                rec = check(em, pw, force=force, allow_browser=not ho, cancel=cancel)
            except Exception as exc:
                rec = _blank(em, pw)
                rec["verdict"] = rec["bucket"] = "UNKNOWN"
                rec["error"] = "%s: %s" % (type(exc).__name__, exc)
                trace("ERR", "run", "%s: %s" % (type(exc).__name__, exc), em)
        with guard:
            out[em] = rec
            done[0] += 1
            n = done[0]
        _tell(n, em, rec.get("verdict", ""))

    width = max(1, min(16, int(workers or 1)))
    try:
        with _cf.ThreadPoolExecutor(max_workers=width) as ex:
            inflight = set()
            for position, item in enumerate(uniq, 1):
                inflight.add(ex.submit(one, item, position))
                step = 0.0 if _is_cancelled(cancel) else pace
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
        for position, item in enumerate(uniq, 1):
            out.setdefault(item[0], check(item[0], item[1], force=force,
                                          allow_browser=not ho, cancel=cancel))
            _tell(position, item[0], out[item[0]].get("verdict", ""))
    trace("INFO", "run", "finished: %d record(s)" % len(out))
    return out


# ---------------------------------------------------------------------------
# scoring
# ---------------------------------------------------------------------------
WEIGHTS = {"NEW": 1.0, "PARTIAL": 0.5, "OLD": 0.15}


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
    return {"version": BREACH_VERSION, "browser": available(),
            "browser_state": browser_state().get("state", ""),
            "browser_error": browser_note(), "pages": _pages(), "delay": _delay(),
            "http_only": _http_only(), "pool": _pool is not None,
            "slots": len(getattr(_pool, "_slots", [])) if _pool else 0,
            "key": bool(_api_key()), "tier": "ui", "owner": owner(),
            "boot_failed_ago": (int(time.time() - _pool_boot_failed)
                                if _pool_boot_failed else 0),
            "page_mode": _page_mode(), "page_on": list(_page_on()),
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
    add("only_pipe", _email_only("a@b.co | OLD") == "a@b.co")
    add("url_no_password", unified_url("a@b.co:hunter2") ==
        HIBP_BASE + "/unifiedsearch/a%40b.co")
    add("blank_read_false", _blank("a@b.co").get("read") is False)
    add("blank_addr_unread", _blank("a@b.co").get("addr_verdict") == "UNREAD")
    add("blank_pw_none", _blank("a@b.co").get("pw_band") == "none")
    add("blank_has_shot_file", "page_shot_file" in _blank("a@b.co"))
    add("clean_url_strips_token",
        _clean_url("https://x/account/a%40b.co?__cf_chl_rt_tk=z") ==
        "https://x/account/a%40b.co")

    # ---- clearance is the arbiter ----
    add("has_clearance", hasattr(_Slot, "_has_clearance"))
    add("clearance_reads_cookies", "cf_clearance" in
        inspect.getsource(_Slot._has_clearance))
    add("solve_checks_clearance", "self._has_clearance()" in
        inspect.getsource(_Slot._solve_wall))
    add("solve_needs_streak", "clear_streak" in inspect.getsource(_Slot._solve_wall))
    add("ask_gates_on_clearance", "no clearance - solving" in
        inspect.getsource(_Slot._ask))
    add("ask_logs_clearance", "clearance %s" in inspect.getsource(_Slot._ask))
    add("warm_up_at_boot", "warming up" in inspect.getsource(_Slot._boot))
    add("stealth_script", "plugins" in STEALTH_JS and "webdriver" in STEALTH_JS)
    add("stealth_applied", "STEALTH_JS" in inspect.getsource(_Slot._boot))
    add("turnstile_by_frames", "page.frames" in
        inspect.getsource(_Slot._click_turnstile))
    add("turnstile_fallback_geometry", "bounding_box" in
        inspect.getsource(_Slot._click_turnstile))
    add("fetch_tries_three", FETCH_TRIES >= 3)
    add("warm_settle_sane", 800 <= WARM_SETTLE <= 4000)

    # ---- both halves ----
    add("addr_verdict_set", "rec[\"addr_verdict\"]" in inspect.getsource(check))
    add("pw_band_set", "rec[\"pw_band\"]" in inspect.getsource(check))
    add("verdict_from_addr_when_no_pw", _combine(None, "CLEAN") == "CLEAN")
    add("unread_not_clean", _addr_bucket({"error": "challenge wall"}) is None)

    # ---- cancellation ----
    _ev = threading.Event()
    add("cancel_helper_false", not _is_cancelled(_ev))
    _ev.set()
    add("cancel_helper_true", _is_cancelled(_ev))
    _fut = _cf.Future()
    add("await_returns_on_cancel", _await_future(_fut, _ev, 30.0) == (None, True))
    add("check_takes_cancel", "cancel" in inspect.signature(check).parameters)
    add("submit_takes_cancel", "cancel" in inspect.signature(
        _BrowserPool.submit).parameters)

    # ---- pool ----
    add("pool_picks_by_depth", "qsize" in inspect.getsource(_BrowserPool._pick))
    add("report_slots", isinstance(report().get("slots"), int))

    # ---- trace ----
    add("trace_skip_param", "skip" in inspect.signature(trace_read).parameters)
    _seq_skip = trace_seq()
    trace("INFO", "page", "heartbeat")
    trace("INFO", "ui", "real")
    _got_skip = trace_text(limit=20, since=_seq_skip, skip=("page",))
    add("skip_drops_page", "heartbeat" not in _got_skip and "real" in _got_skip)

    # ---- isolation ----
    _was_owner = owner()
    set_owner("aaaa1111")
    add("user_file_prefixed", _user_file(CACHE_NAME) == "aaaa1111_" + CACHE_NAME)
    add("shot_path_is_jpg", _shot_path("a@b.co").endswith(".jpg"))
    add("shot_path_prefixed", "aaaa1111" in _shot_path("a@b.co"))
    set_owner("")
    add("owner_empty_falls_back", bool(_user_file(CACHE_NAME)))

    _saved_cfg = dict(_cfg)
    configure(page_mode=PAGE_MODE_FULL, delay=1.0)
    _pin_cfg(_snapshot_cfg(False))
    configure(page_mode=PAGE_MODE_OFF, delay=9.0)
    add("snapshot_keeps_mode", _page_mode() == PAGE_MODE_FULL)
    _pin_cfg(None)
    add("no_snapshot_reads_default", _page_mode() == PAGE_MODE_OFF)
    with _lock:
        _cfg.clear()
        _cfg.update(_saved_cfg)

    set_owner("aaaa1111")
    _seq_a = trace_seq()
    trace("INFO", "selftest", "mine a", "a@b.co")
    set_owner("bbbb2222")
    add("ring_other_owner_empty", trace_read(limit=50, since=_seq_a) == [])
    set_owner(_was_owner)

    configure(page_mode=PAGE_MODE_FAST, page_on=PAGE_KINDS)
    add("fast_captures_clean", page_wanted("clean"))
    add("fast_skips_records", not page_wanted("records"))
    configure(page_mode=PAGE_MODE_OFF)
    add("off_nothing", not page_wanted("records"))
    configure(page_mode=PAGE_MODE_FAST, page_on=PAGE_ON_DEFAULT)

    pairs = parse_addresses("a@b.co:pw\n- c@d.co:pw2 | VALID\njunk")
    add("parse_count", len(pairs) == 2)

    add("pw_new", _pw_bucket(0) == "NEW")
    add("pw_old", _pw_bucket(50000) == "OLD")
    add("combine_worst", _combine("NEW", "OLD") == "OLD")

    pwn = {"Breaches": [
        {"Name": "Stealer Logs", "Domain": "", "BreachDate": "2026-06-01",
         "DataClasses": ["Passwords"], "IsSpamList": True},
        {"Name": "X", "Domain": "x.com", "BreachDate": "2018-02-01",
         "DataClasses": ["Passwords"]}], "Pastes": [{"Title": "d", "Source": "P"}]}
    rec = _parse_payload("a@b.co", pwn, "browser", time.time(), "pw")
    add("corpus_split", rec["corpora"] == 1 and rec["sites"] == 1)
    add("count_total", rec["count"] == 3)
    clean = _parse_payload("a@b.co", {"Breaches": [], "Pastes": []}, "browser", None, "")
    add("addr_bucket_clean", _addr_bucket(clean) == "CLEAN")

    add("date_long", _any_date("Breach date: 4 October 2013") == "2013-10-04")
    _got_b, _ = _parse_rendered(
        "Adobe\nBreach date: 4 October 2013\nAccounts: 152,445,165\n",
        [{"t": "Adobe", "h": "/breach/Adobe"}])
    add("scrape_accounts", _got_b[0]["pwn_count"] == 152445165)
    add("scrape_clean", _parse_rendered("Good news - no pwnage found", [])[1] is True)

    add("challenge_401", _looks_like_challenge(401, ""))
    add("pw_hash", len(_pw_hash("abc")) == 40)
    add("report_tier", report().get("tier") == "ui")
    add("env_set", os.environ.get("PLAYWRIGHT_BROWSERS_PATH") == _PW_DIR)

    add("page_percent_css", "100%" in
        _page_from_record({"email": "a@b.co"}, "clean")["page_html"])
    add("gen_shows_halves", "password half" in
        _page_from_record({"email": "a@b.co"}, "clean")["page_text"])
    add("record_view_never_raises", record_view(None) == ("", ""))
    add("esc", _esc("<a&b>") == "&lt;a&amp;b&gt;")

    import inspect
    add("check_passes_cancel", "cancel=cancel" in inspect.getsource(check_many))
    add("check_keeps_reason", "addr_rec[\"error\"] +=" in inspect.getsource(check))
    add("cache_drops_html", "pop(\"page_html\"" in inspect.getsource(check))
    add("pool_resized_on_get", "pool.resize(size)" in inspect.getsource(_get_pool))

    before = trace_seq()
    trace("INFO", "selftest", "hello")
    add("trace_recorded", len(trace_read(limit=5, since=before)) == 1)

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
        res = check(pairs[0][0], pairs[0][1], force=True)
        print("url sent:", last_url())
        print(json.dumps({k: res.get(k) for k in ("email", "verdict", "addr_verdict",
                                                  "pw_band", "count", "read", "via",
                                                  "error")}, indent=2))
        print(trace_text(limit=40))
        return 0 if res.get("verdict") else 1
    selftest(verbose=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
