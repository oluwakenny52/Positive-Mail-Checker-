"""breach.py - breach exposure and combo freshness.  v13.84

NO API KEY. Three keyless sources, in order of how much they prove:

    passwords  api.pwnedpasswords.com/range/<5-hex> - k-anonymity, no key, no
               challenge. Returns how many times the password appears in every
               breach HIBP has ever loaded. THIS is the freshness signal for a
               combo: 0 means the password is private, 40,000 means it is an old
               bridge that has been circulating for years.
    address    haveibeenpwned.com/unifiedsearch/<email> - the endpoint the site's
               own search box uses. Plain HTTP first; a real browser only when
               Cloudflare answers with the interstitial.
    catalogue  /api/v3/breaches - one fetch, matched LOCALLY by domain. Kept as
               a fallback for when the address tiers are blocked.

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

Plain module, NOT frame-gated - like runstate.py and sentinel.py. No Streamlit.
Nothing here renders. EVERY public function swallows: a breach lookup must never
be the reason a page dies.

THE BROWSER BINARY  (v13.84)
----------------------------
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
The cache resolves through auth.user_file(), so it is one file per user. The
browser pool is per process (one Chromium) but its pages are shared round-robin,
and every result is keyed by address in the caller's own dict. The binary is
process-wide on purpose: it is the same bytes for everybody.

USAGE
    import breach
    breach.configure(pages=4)
    breach.ensure_browser()                  # non-blocking, idempotent
    breach.browser_state()                   # for the page to show
    breach.available()                       # False -> HTTP only, no browser
    rec = breach.check("a@b.com", password="hunter2")
    all = breach.check_many(pairs, workers=8, progress=cb, cancel=ev)
    breach.score(all.values())               # old/new breakdown
    breach.parse_addresses(text)             # -> [(email, password)]

    python breach.py --selftest
    python breach.py --probe someone@example.com:hunter2
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

BREACH_VERSION = "v13.84"

# MUST be set before anything imports playwright. setdefault, not assignment, so
# an operator who exports their own path keeps it.
_HERE = os.path.dirname(os.path.abspath(__file__))
_PW_DIR = os.path.join(_HERE, ".pw-browsers")
_PW_SENTINEL = os.path.join(_PW_DIR, ".installed")
os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", _PW_DIR)

HIBP_BASE = "https://haveibeenpwned.com"
UNIFIED = HIBP_BASE + "/unifiedsearch/%s"
CATALOGUE_URL = HIBP_BASE + "/api/v3/breaches"
PW_RANGE = "https://api.pwnedpasswords.com/range/%s"

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

_cfg = {"pages": PAGES_DEFAULT, "timeout": 60.0}
_lock = threading.Lock()
_pool = None
_pw_missing = ""
_last = {"ts": 0.0, "email": "", "verdict": "", "via": "", "ms": 0, "error": ""}

_pw_lock = threading.Lock()
_pw_thread = None
_pw_state = {"state": "unknown", "error": "", "started": 0.0, "finished": 0.0}

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")


# ---------------------------------------------------------------------------
# config
# ---------------------------------------------------------------------------
def configure(pages=None, timeout=None):
    """Pool size and per-address budget. Never raises."""
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


def _pages() -> int:
    with _lock:
        return int(_cfg["pages"])


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
            return
        with open(_PW_SENTINEL, "w", encoding="utf-8") as fh:
            fh.write("ok\n")
        with _pw_lock:
            _pw_state = {"state": "ready", "error": "", "started": _pw_state["started"],
                         "finished": time.time()}
    except Exception as exc:
        with _pw_lock:
            _pw_state = {"state": "failed", "error": "%s: %s"
                         % (type(exc).__name__, exc),
                         "started": _pw_state.get("started", 0.0),
                         "finished": time.time()}


def ensure_browser(force=False) -> str:
    """Start the one-time install if it is needed. NEVER blocks. Returns state.

    Idempotent: a sentinel means done, a live thread means already running, and a
    previous failure is not retried unless `force` is set. A failed install is a
    real answer - re-running it on every page load would be a 900s download on
    every load.
    """
    global _pw_thread
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


def is_email(addr) -> bool:
    return bool(_EMAIL_RE.match(_norm(addr)))


def domain_of(addr) -> str:
    a = _norm(addr)
    return a.split("@", 1)[1] if "@" in a else ""


def parse_addresses(text):
    """A pasted list -> [(email, password)]. Password may be empty.

    A line is cut at the FIRST '|' then the FIRST ':', and only the left part is
    kept as the address. A line with no password yields ("", password) so an
    address-only list still works.
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
        s = _norm(s)
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
    return {"email": _norm(addr), "password_len": len(pw or ""), "verdict": "",
            "bucket": "", "reason": "", "breaches": [], "pastes": [],
            "pw_count": None, "corpora": 0, "sites": 0, "sensitive": 0,
            "newest_days": None, "count": None, "via": "",
            "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "error": ""}


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
        return entry.get("n")

    try:
        import requests
    except Exception:
        return None
    n = None
    try:
        r = requests.get(PW_RANGE % prefix, timeout=HTTP_TIMEOUT,
                         headers={"User-Agent": UA, "Add-Padding": "true"})
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
    except Exception:
        return entry.get("n") if entry else None

    cache.setdefault("pw", {})[full] = {"ts": time.time(), "n": n}
    _save(cache)
    return n


# ---------------------------------------------------------------------------
# tier 2 - address exposure
# ---------------------------------------------------------------------------
def _looks_like_challenge(status, body) -> bool:
    if status in (403, 429, 503):
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
    started = time.time()
    req = urllib.request.Request(
        UNIFIED % urllib.parse.quote(_norm(addr)),
        headers={"Accept": "application/json", "Accept-Language": "en-GB,en;q=0.9",
                 "User-Agent": UA, "Referer": HIBP_BASE + "/"})
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            body = resp.read().decode("utf-8", "replace")
            status = resp.status
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read().decode("utf-8", "replace")
        except Exception:
            body = ""
        status = exc.code
    except Exception as exc:
        rec = _blank(addr, pw)
        rec["via"] = "http"
        rec["error"] = "%s: %s" % (type(exc).__name__, exc)
        return rec

    if status == 404:
        rec = _blank(addr, pw)
        rec["via"] = "http"
        rec["count"] = 0
        return rec
    if _looks_like_challenge(status, body):
        rec = _blank(addr, pw)
        rec["via"] = "http"
        rec["error"] = "challenge (http %d)" % status
        return rec
    try:
        return _parse_payload(addr, json.loads(body or "{}"), "http", started, pw)
    except Exception as exc:
        rec = _blank(addr, pw)
        rec["via"] = "http"
        rec["error"] = "unparsable: %s" % exc
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
        except Exception as exc:
            self._boot_err = "%s: %s" % (type(exc).__name__, exc)
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
                started = time.time()
                status, body = self._search(page, addr)
                if status == 404:
                    rec = _blank(addr, pw_s)
                    rec["via"] = "browser"
                    rec["count"] = 0
                elif _looks_like_challenge(status, body):
                    rec = _blank(addr, pw_s)
                    rec["via"] = "browser"
                    rec["error"] = "challenge survived (http %d)" % status
                else:
                    try:
                        rec = _parse_payload(addr, json.loads(body or "{}"),
                                             "browser", started, pw_s)
                    except Exception as exc:
                        rec = _blank(addr, pw_s)
                        rec["via"] = "browser"
                        rec["error"] = "unparsable: %s" % exc
                if not fut.done():
                    fut.set_result(rec)
            except Exception as exc:
                if not fut.done():
                    rec = _blank(addr, pw_s)
                    rec["via"] = "browser"
                    rec["error"] = "%s: %s" % (type(exc).__name__, exc)
                    fut.set_result(rec)
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
        page.goto(HIBP_BASE + "/", wait_until="domcontentloaded", timeout=NAV_TIMEOUT)
        deadline = time.time() + CHALLENGE_WAIT
        while time.time() < deadline:
            try:
                title = (page.title() or "").lower()
            except Exception:
                title = ""
            if "pwned" in title and "moment" not in title:
                return True
            page.wait_for_timeout(1500 if any(m in title for m in CHALLENGE_MARKS) else 1200)
        return True

    def _search(self, page, addr):
        """Fetch from inside the page so the clearance cookie is carried."""
        status, body = 0, ""
        for attempt in (0, 1):
            if "haveibeenpwned.com" not in (page.url or ""):
                self._clear(page)
            try:
                out = page.evaluate(
                    """async (email) => {
                        const r = await fetch('/unifiedsearch/' +
                            encodeURIComponent(email),
                            {headers: {'Accept': 'application/json'}});
                        return {status: r.status, body: await r.text()};
                    }""", _norm(addr))
                status, body = int(out.get("status") or 0), out.get("body") or ""
            except Exception:
                status, body = 0, ""
            if status and not _looks_like_challenge(status, body):
                return status, body
            if attempt == 0:
                self._clear(page)
        return status, body

    def submit(self, addr, pw):
        fut = _cf.Future()
        self._q.put((_norm(addr), pw, fut))
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
def check(addr, password="", force=False, allow_browser=True) -> dict:
    """One address. Pwned Passwords, then address exposure. Never raises."""
    addr = _norm(addr)
    if not is_email(addr):
        rec = _blank(addr, password)
        rec["verdict"] = rec["bucket"] = "UNKNOWN"
        rec["reason"] = rec["error"] = "not an email address"
        return rec

    cache = _load()
    entry = (cache.get("address") or {}).get(addr)
    if not force and _fresh(entry, CACHE_TTL):
        got = dict(entry.get("report") or {})
        if got:
            return got

    rec = _blank(addr, password)
    rec["pw_count"] = pwned_count(password, force=force)

    addr_rec = _http_search(addr, password)
    if addr_rec.get("error", "").startswith("challenge"):
        if allow_browser and available():
            try:
                pool = _get_pool()
                addr_rec = pool.submit(addr, password).result(timeout=_cfg["timeout"])
            except Exception as exc:
                rec["error"] = "browser failed: %s: %s" % (type(exc).__name__, exc)
        else:
            # Kick the install so the NEXT press has a browser, and say which of
            # the two reasons it was: a missing binary is not a blocked site.
            if allow_browser and not available():
                ensure_browser()
            addr_rec["error"] += " | no browser (%s)" % browser_note()

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

    rec["bucket"] = _combine(_pw_bucket(rec["pw_count"]), _addr_bucket(addr_rec))
    rec["verdict"] = rec["bucket"]
    rec["reason"] = _REASON.get(rec["bucket"], "")
    if rec["bucket"] == "UNKNOWN" and not rec["error"]:
        rec["error"] = "no readable answer"

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


def check_many(pairs, workers=4, progress=None, cancel=None, force=False) -> dict:
    """Check every (email, password) pair. Returns {email: record}."""
    uniq, seen = [], set()
    for item in pairs or []:
        if isinstance(item, (tuple, list)) and item:
            em, pw = item[0], (item[1] if len(item) > 1 else "")
        else:
            em, pw = item, ""
        em = _norm(em)
        if em and em not in seen:
            seen.add(em)
            uniq.append((em, str(pw or "")))
    out, guard, done = {}, threading.Lock(), [0]
    total = len(uniq)

    def one(item):
        em, pw = item
        if cancel is not None and cancel.is_set():
            rec = _blank(em, pw)
            rec["verdict"] = rec["bucket"] = "UNKNOWN"
            rec["error"] = "cancelled"
        else:
            rec = check(em, pw, force=force)
        with guard:
            out[em] = rec
            done[0] += 1
            n = done[0]
        if progress is not None:
            try:
                progress(n, total, em, rec.get("verdict", ""))
            except Exception:
                pass

    try:
        with _cf.ThreadPoolExecutor(max_workers=max(1, min(16, int(workers or 1)))) as ex:
            list(ex.map(one, uniq))
    except Exception:
        for item in uniq:
            out.setdefault(item[0], check(item[0], item[1], force=force))
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
            "browser_error": browser_note(), "pages": _pages(),
            "pool": _pool is not None, "last": dict(_last)}


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
    add("challenge_html", _looks_like_challenge(200, "<title>Just a moment...</title>"))
    add("challenge_json", not _looks_like_challenge(200, '{"Breaches":[]}'))
    add("pw_hash", len(_pw_hash("abc")) == 40)
    add("report_shape", isinstance(report().get("browser"), bool))
    add("state_shape", "state" in browser_state())
    add("note_is_str", isinstance(browser_note(), str))
    add("env_set", os.environ.get("PLAYWRIGHT_BROWSERS_PATH") == _PW_DIR)

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
            print("usage: breach.py --probe someone@example.com[:password]")
            return 2
        pairs = parse_addresses(target) or [(target, "")]
        print("browser available:", available(), browser_note())
        res = check(pairs[0][0], pairs[0][1], force=True)
        print(json.dumps({k: res.get(k) for k in ("email", "verdict", "pw_count",
                                                  "count", "via", "error")}, indent=2))
        return 0 if res.get("verdict") else 1
    selftest(verbose=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
