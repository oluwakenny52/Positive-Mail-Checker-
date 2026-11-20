"""breach.py - breach exposure and combo freshness.  v13.86

Three sources, in order of how much they prove:

    passwords  api.pwnedpasswords.com/range/<5-hex> - k-anonymity, no key, no
               challenge. Returns how many times the password appears in every
               breach HIBP has ever loaded. THIS is the freshness signal for a
               combo: 0 means the password is private, 40,000 means it is an old
               bridge that has been circulating for years.
    address    the SITE, DRIVEN LIKE A PERSON. A real Chromium lands on
               haveibeenpwned.com, finds the search box, types the bare address
               into it, presses Enter, waits for the account page, and reads the
               rendered DOM - the breach names, their dates, the data classes and
               the accounts figure - plus the page text and HTML from that same
               read. The JSON the page fires on its own is caught and preferred
               when it arrives, because it is exact; nothing depends on it.
    catalogue  /api/v3/breaches - one fetch, matched LOCALLY by domain. Kept as
               a fallback for when the address tiers are blocked.

WHY THE UI, AND NOT AN ENDPOINT  (v13.86)
-----------------------------------------
haveibeenpwned.com/unifiedsearch/ answers 401 to an anonymous urllib call, and a
401 is not a Cloudflare interstitial, so the old code fell through to
json.loads("") and reported an EMPTY payload - the site listed ten breaches for
the same address while this module said none. Two things were wrong. The status
list did not contain 401, so the browser was never sent at the wall; and the
browser tier's own fetch was an in-page fetch of that same endpoint, so it hit the
same wall. Both are fixed: 401 is a wall like 403, and the browser tier now drives
the UI and scrapes what renders. No key, no quota, no bill - the page is the API.

THE DEADLOCK THAT FROZE EVERY RUN  (v13.86)
-------------------------------------------
_lock was a plain threading.Lock, and _get_pool() called _pages() INSIDE a
with-block on it:

    with _lock:
        if _pool is None:
            _pool = _BrowserPool(_pages())   # _pages() takes _lock again

A non-reentrant lock taken twice by the same thread blocks for ever. The first
worker to reach the browser tier froze, the other workers froze behind it on the
same lock, nothing ever returned, and the page sat on "0 / 3" with no further
trace. It only appeared without a key, because that is the only path that ever
reaches _get_pool(). The lock is an RLock now AND the page count is read before
the lock is taken, so either fix alone would have held.

THE BOOT PATH, SECOND PASS  (v13.86)
------------------------------------
Clearing the deadlock was not enough, because the boot path had three faults of
its own:

  1. start() did `with _lock:` and then waited up to 90s on the launch, and every
     worker's _http_search takes _lock to record the URL - so one worker's launch
     stalled the other three for its whole duration. The wait is outside the lock:
     the thread is spawned under it, the event is waited on after it.
  2. A failed boot left _pool non-None with a DEAD thread, so start() returned at
     once on every later call and re-raised the stale error for the life of the
     process. start() respawns when the thread is dead, clears the old error
     first, and keeps the message in _pool_boot_err so the page can print the
     real reason.
  3. available() answered True whenever _pool was non-None - including during a
     boot-failure cooldown - so check() took the browser branch and paid a
     certain failure instead of the honest "no browser" branch. It is False for
     the cooldown now, and browser_note() names the launch failure rather than
     saying "not installed".

A FOURTH FAULT: THE REASON WAS THROWN AWAY
------------------------------------------
check() wrote `rec["error"] = "browser failed: ..."` inside its except and then
overwrote it three lines later with `rec["error"] = addr_rec.get("error", "")`,
which still held the plain "challenge (http 403)". The page therefore never said
why the browser had failed - it said the site had challenged, which is the one
thing already known. The failure is folded into addr_rec's error now, so it
survives to the record.

The per-address budget is 180s, not 45 and not 90. One navigation (20s) + a root
interstitial (10s) + the box scan + a render ceiling (12s) + an interstitial
ceiling (25s) does not fit in 90, and the budget also covers a spell in the queue
behind the other workers. A cut call is indistinguishable from a broken site, and
the old code answered it by re-queueing the same address and paying the whole
thing twice.

THE PAGE VIEW THAT NEVER EXISTED  (v13.86, this pass)
-----------------------------------------------------
_page_from_record() builds the Text and HTML view when a live page could not be
read. It formatted its head with `%` while the head contained the CSS rule
`width:100%`, and `%` followed by `;` is not a conversion - so EVERY call raised
ValueError, the call site swallowed it, and every record came back with an empty
page_text and page_html. The card then said "no page captured" and drew no
Text/HTML toggle, which read as a capture-policy fault and was nothing of the
kind. The CSS is a constant now, appended unformatted, and the selftest asserts a
`100%` survives the round trip.

READ, VERSUS ZERO  (v13.86, this pass)
--------------------------------------
count 0 and count None used to look identical: "0 breaches" whether the page had
been read and listed none, or every tier had failed and nothing was read at all.
Every record now carries `read` (the address half answered) and `partial_read`
(only the password half answered). A record with read False is UNREAD, not clean,
and the page, the history and the CSV all say so.

PER-USER ISOLATION, AND THE FOUR PLACES IT BROKE  (v13.86, this pass)
---------------------------------------------------------------------
The cache and the trace file were already per-user - auth.user_file() prefixes
them with the unlocked hash - but the RESOLUTION of that identity was not
isolated, and three pieces of shared state leaked or interfered:

  1. _anon_id() reads st.session_state, and the run executes on a worker thread.
     Off the script thread that falls back to the process-wide context, so with
     two users running at once a cache or trace write could land in the other
     one's prefix. FIXED by pinning the prefix per THREAD: set_owner() is called
     once by the page and once per worker, and _user_file() builds from it. The
     auth fallback is only for a thread nobody pinned (CLI, selftest).
  2. _cfg was process-wide, and check() re-read the page mode per address, so a
     second user pressing Run with capture Off silently turned capture off for
     the first user's in-flight run. FIXED by a per-run snapshot: check_many()
     pins it on the thread and every reader goes through _cfg_get().
  3. The trace RING and _last were process-wide, so the page DISPLAYED other
     people's addresses in section 4 and in the "Last URL" caption. FIXED: every
     event carries an owner and trace_read() filters; _lasts is keyed by owner.
  4. trace_clear() wiped the whole ring, and pool-thread lines had no owner at
     all. FIXED: clear is per owner, and the pool thread pins the owner of the
     job it is working on.

What stays process-wide ON PURPOSE: the Chromium binary and its install state
(same bytes for everybody), the browser pool and its shared context (one launch,
round-robin pages, results keyed per call), the boot-failure cooldown, and the
optional API key. The pool QUEUE is shared too, so a large run delays a second
user - interference, not a leak.

WHY AN OPTIONAL KEY STILL EXISTS
--------------------------------
If HIBP_API_KEY is set, /api/v3/breachedaccount is tried first because it is
faster and returns exact dates. It is never required: absent, the keyed tier is
simply skipped, and the key row on the page says so. Nothing pretends.

WHAT IS ACTUALLY SENT  (v13.85)
-------------------------------
The address, and only the address. A pasted combo arrives as "a@b.co:hunter2" or
"a@b.co | OLD" or "mailto:a@b.co", and every one of those tails has to come off
before the request is built - a colon is legal inside a path segment, so
"unifiedsearch/a@b.co:hunter2" is a DIFFERENT search, not an error you would
notice. _email_only() is the single funnel: check(), _http_search(), _blank(),
parse_addresses() and the browser pool all pass through it, and the selftest
asserts the transmitted URL equals the bare address. The password reaches exactly
one place, the SHA-1 hash that is split for k-anonymity, and only 5 hex characters
of it leave the box.

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
    CLEAN     password unseen AND address in no source
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
trace_dump() is what it downloads. The ring is bounded, the file is capped, and
both are filtered to one owner.

Pacing is separate from worker count on purpose. Workers bound concurrency;
configure(delay=...) bounds the RATE at which new addresses are started, which is
the thing a WAF counts. The default is 3 seconds between starts, because the
address tier is a full page load per address.

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

A boot that fails is remembered for BOOT_RETRY_AFTER seconds, so a run of ten
addresses does not pay ten separate 90-second waits for the same broken binary.

WITHOUT A BROWSER THERE IS NO ADDRESS TIER. With no key and no binary, every
address comes back UNKNOWN, and browser_note() says exactly that.

ISOLATION
---------
The cache and the trace file resolve through the PINNED owner (see above), which
is the unlocked hash, so both are one file per user and a worker thread cannot
pick up somebody else's session. The browser pool is per process (one Chromium)
but its pages are shared round-robin, and every result is keyed by address in the
caller's own dict. The binary is process-wide on purpose: it is the same bytes for
everybody.

USAGE
    import breach
    breach.configure(pages=2, delay=3.0)
    breach.set_owner(auth.user_file(""))     # pin the per-user prefix
    breach.ensure_browser()                  # non-blocking, idempotent
    breach.browser_state()                   # for the page to show
    breach.available()                       # False -> HTTP only, no browser
    rec = breach.check("a@b.com", password="hunter2")
    all = breach.check_many(pairs, workers=2, progress=cb, cancel=ev)
    breach.score(all.values())               # old/new breakdown
    breach.parse_addresses(text)             # -> [(email, password)]
    breach.trace_read(limit=100)             # what a page renders
    breach.trace_dump()                      # what a page downloads
    breach.record_view(rec)                  # -> (text, html) of a record

    python breach.py --probe someone@example.com:hunter2
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

# The OPTIONAL keyed tier. Faster and exact, never required.
ACCOUNT_API = HIBP_BASE + "/api/v3/breachedaccount/%s?truncateResponse=false"
PASTE_API = HIBP_BASE + "/api/v3/pasteaccount/%s"
KEY_ENV = "HIBP_API_KEY"

# The UI tier. The site's own search box, tried in this order because the id has
# moved before and a form layout has no id at all. If none is found the tier
# navigates straight to the account page instead - the page renders the same
# result, it just skips the typing.
UI_SEARCH_SELECTORS = (
    "input#searchInput",
    "form input[type='email']",
    "form input[type='search']",
    "form input[type='text']",
    "input[type='search']",
    "input[type='email']",
    "input[type='text']",
)
# v13.86 FIX PARSE-1: the render wait is a CEILING now, not a fixed sleep, and
# there is a second ceiling for the interstitial. A fresh __cf_chl_rt_tk is
# minted per URL, so an account page can land challenged even though the root
# page cleared - 8s of a flat loop cannot cover that, and the old code returned 0
# either way.
RENDER_WAIT = 12.0
CHALLENGE_EXTRA = 25.0
INTERSTITIAL_MARKS = ("just a moment", "checking your browser", "verify you are human",
                      "performing security verification", "attention required",
                      "cf-challenge")

# Read the rendered page ONCE: the breach anchors, the visible text and the
# markup. innerText, not textContent - innerText is what is actually laid out, so
# a collapsed or hidden block cannot pad the scrape with template text.
# v13.86 FIX PARSE-2: the anchors alone were the only selector and nothing forced
# a lazy tile into the DOM. The anchors are still first because they are exact;
# the class fallback only runs when they yield nothing, and the caller scrolls
# before reading so a mounted-on-scroll tile is present.
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

PAGE_HTML_MAX = 90000
PAGE_TEXT_MAX = 30000
PAGE_TIMEOUT = 12.0

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

# The stylesheet of a GENERATED page. It is a constant, appended to the head
# WITHOUT %-formatting, because it contains `width:100%` and `%` followed by `;`
# is not a conversion - the whole of _page_from_record() raised ValueError for as
# long as the CSS sat inside the formatted string, and every record came back
# with no page at all.
_PAGE_CSS = ("<style>body{font-family:system-ui,sans-serif;background:#0b1020;"
             "color:#e6ebff;padding:16px}h1{font-size:1.05rem}h2{font-size:.9rem}"
             "table{border-collapse:collapse;width:100%;font-size:.8rem}"
             "td,th{border:1px solid #2a3350;padding:5px;text-align:left;"
             "vertical-align:top}th{background:#141b30}.c{color:#fcd34d}</style>")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36")

HTTP_TIMEOUT = 8.0
NAV_TIMEOUT = 20000
CHALLENGE_WAIT = 25.0
# The root clear only has to re-establish a cookie the context already holds, so
# it gets a short ceiling. The full CHALLENGE_WAIT is still spent where it
# matters: on the account page itself, in _await_render.
ROOT_SETTLE = 10.0
BOOT_WAIT = 90.0
BOOT_RETRY_AFTER = 60.0
PAGES_DEFAULT = 2
PAGES_MAX = 8
DESC_MAX = 1200
CACHE_NAME = "breach_cache.json"
CACHE_TTL = 6 * 3600.0
CATALOGUE_TTL = 6 * 3600.0
INSTALL_TIMEOUT = 900

# Pacing. One new address may START every DELAY_DEFAULT seconds; workers bound
# concurrency, delay bounds the rate. 0 = flood as fast as the pool allows. The
# address tier is a whole page load, so the defaults are deliberately small.
DELAY_DEFAULT = 3.0
DELAY_MAX = 20.0
BROWSER_SETTLE = 500      # ms to sit on a page before reading it
BROWSER_JITTER = 400      # extra random ms, so two pages never fire together

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

# What a rendered account page says when there is nothing to show. Checked on the
# TEXT of the page, which is why the site's own wording is in here and not a CSS
# class that a redesign would break.
CLEAN_MARKS = ("no pwnage", "good news", "not been pwned", "no breaches found",
               "hasn't been pwned", "has not been pwned")

RANK = {"NEW": 0, "PARTIAL": 1, "OLD": 2}

# Trace ring. Bounded in memory AND on disk - a page left open for a week must
# not grow either one without limit.
TRACE_MAX = 600
TRACE_NAME = "breach_trace.jsonl"
TRACE_FILE_MAX = 4000
TRACE_DUMP_MAX = 500

# 180s, not 45 and not 90. A navigation (20s) plus a root interstitial (10s) plus
# the box scan plus a render ceiling (12s) plus an interstitial ceiling (25s)
# does not fit in 90 - and the budget also has to cover time spent in the queue
# behind the other workers, because the timeout is armed at submit, not at page
# take. A cut call is indistinguishable from a broken site, and it used to be
# answered by re-queueing the same address and paying the whole thing twice.
_cfg = {"pages": PAGES_DEFAULT, "timeout": 180.0, "delay": DELAY_DEFAULT,
        "http_only": False, "page_mode": PAGE_MODE_FAST,
        "page_on": tuple(PAGE_ON_DEFAULT)}
# RLock, NOT Lock. _get_pool() builds the pool while holding this and the builder
# reads the page count through _pages(), which takes it again - a plain Lock
# blocked for ever on the first address that reached the browser tier, and took
# every worker with it.
_lock = threading.RLock()
_pool = None
_pool_boot_failed = 0.0
_pool_boot_err = ""
_pw_missing = ""

# PER-THREAD state. _cfg above is the process DEFAULT; this holds what the
# current thread is actually running with, so a second user's configure() cannot
# retune a run already in flight. `owner` is the unlocked-hash prefix the cache
# and trace paths are built from - resolved here rather than from
# st.session_state, because st.session_state off the script thread falls back to
# the process-wide context and can answer for somebody else's session.
_tls = threading.local()

# Last address per OWNER. One shared dict used to mean the page's "Last URL"
# caption showed whichever user touched last.
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


# ---------------------------------------------------------------------------
# owner - the per-user prefix, pinned per THREAD
# ---------------------------------------------------------------------------
def set_owner(prefix="") -> str:
    """Pin the per-user prefix for the CALLING THREAD and return it.

    Call it once from the page (script thread) and once per worker. It is what
    makes the cache and trace paths safe from a background thread, where
    st.session_state cannot be trusted to belong to this session.
    """
    _tls.owner = str(prefix or "")
    return _tls.owner


def owner() -> str:
    """The prefix pinned for this thread, or "" when nobody pinned one."""
    return str(getattr(_tls, "owner", "") or "")


def _user_file(name) -> str:
    """Per-user filename from the PINNED owner, else from auth.

    The auth fallback is for a thread nobody pinned: the CLI, the selftest, and
    the module-level import. auth.user_file() returns "<hash>_<name>", which is
    the exact shape built here, so both agree.
    """
    p = owner()
    if p:
        return "%s_%s" % (p, name) if name else p
    try:
        import auth
        return auth.user_file(name)
    except Exception:
        return name


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

    This writes the PROCESS DEFAULT. A run that is already going keeps the
    snapshot it pinned (see _snapshot_cfg), so another user cannot retune it.
    """
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
    """This thread's snapshot value, else the process default. Never raises."""
    snap = getattr(_tls, "cfg", None)
    if isinstance(snap, dict) and key in snap:
        return snap[key]
    with _lock:
        return _cfg.get(key, default)


def _snapshot_cfg(http_only=None) -> dict:
    """Freeze the current settings for ONE run.

    A run used to read _cfg live per address, so a second user pressing Run with
    capture Off turned capture off halfway through the first user's run and their
    later records came back as skipped pages. The snapshot is pinned on the
    thread by check_many() and never re-read from the process dict.
    """
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
    """The per-address budget for THIS run, never the process default."""
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

    Read lazily and cached once found. The key is OPTIONAL: empty means the keyed
    tier is skipped entirely and the browser does the work.
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
    p = _user_file(TRACE_NAME)
    if not p:
        return ""
    try:
        os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
    except Exception:
        pass
    return p


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

    The event is stamped with the caller's pinned owner. Without that the RING is
    shared and a page renders every session's addresses; the FILE was already
    per-user, but the ring was not, so section 4 leaked the other user's work.
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


def trace_read(limit=200, since=0):
    """Events newer than `since`, oldest first, for THIS owner. Never raises.

    An unpinned thread (CLI, selftest) gets every owner, because there is nobody
    to filter by and the ring is the only record.
    """
    try:
        n = max(1, min(TRACE_MAX, int(limit or 200)))
        floor = int(since or 0)
    except Exception:
        n, floor = 200, 0
    want = owner()
    with _trace_lock:
        got = [e for e in _trace
               if e.get("seq", 0) > floor and (not want or e.get("owner") == want)]
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
    """Clear THIS owner's file and ring entries. Other users keep theirs."""
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

    A pool whose last boot FAILED is not available: the cooldown would otherwise
    be invisible and every address would pay a 90s launch attempt that is certain
    to raise. False here sends check() down the "no browser" branch, which is the
    truthful answer and costs nothing.
    """
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
    """Why the browser tier is unavailable, in words the page can print."""
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
    """The bare address, with every pasted tail cut off. THE only thing HIBP sees.

    A combo can arrive as "a@b.co:pw", "a@b.co | OLD", "mailto:a@b.co",
    "<a@b.co>", "\"a@b.co\":pw", or a re-pasted bucket line. Each tail is legal
    inside a URL path segment, so leaving one on does not raise - it silently
    searches a different string. Everything funnels through here.

    Order matters: the tails come off FIRST, then the wrapping quotes and angle
    brackets, because "a@b.co":pw ends in the password, not in a quote, and a
    strip before the split would leave the quote attached to the address.

    In the UI tier this is also what gets TYPED into the box, so the guarantee is
    the same one the URL carried: the address and nothing else.
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


def _any_date(text):
    """The first date in a string, as ISO, or "". Reads both forms the site uses.

    The account page prints a date as "4 October 2013"; the JSON carries
    "2013-10-04". A rendered scrape only ever has the first, so it is parsed here
    rather than being thrown away as unknown.
    """
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
    """Rendered page text + its /breach/ anchors -> (breaches, clean). PURE.

    The anchors are the breach names, because the site links every one of them to
    /breach/<Name>; nothing else on an account page points there. The dates, the
    data classes and the accounts figure are read from the text that FOLLOWS the
    name in the rendered layout, which is the order the site prints them in.

    `clean` is only true when there are no anchors at all and the page says so in
    words. A page that merely failed to render is not clean, and the caller can
    tell the difference by the link count.
    """
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

    The page answers 401 to anonymous callers, so an empty result here is normal
    and is why the browser tier reads the DOM instead, and why
    _page_from_record() exists as a last resort when a key is set.
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
        # The 401 body is 101 bytes and is still the only evidence of the wall,
        # so it is read rather than dropped - a card with the wall in it beats an
        # empty card that says the same thing as a clean address.
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
    """A text and an HTML view BUILT FROM the record. Never raises.

    Only used when a live page could not be read - a keyed run whose /account
    fetch was refused, or an address the browser could not render. Marked
    page_via "api": it is a report of what the source said, not a captured page,
    and it says so at the foot of the HTML.

    force=True ignores page_wanted(), so a caller that has already decided this
    record must carry a page can build one in fast mode where "records" is never
    a captured kind.

    THE CSS IS NOT IN THE FORMAT STRING. It contains `width:100%`, and `%`
    followed by `;` is not a conversion, so formatting a head that carried the
    stylesheet raised ValueError on EVERY call - the call site swallowed it and
    every record came back with no page at all. _PAGE_CSS is appended as a value.
    """
    if not force and not page_wanted(kind):
        return _page_skip(kind)
    addr = _email_only(rec.get("email") or "")
    _pw = rec.get("pw_count")
    lines = ["address: %s" % addr,
             "checked: %s" % (rec.get("checked_at") or ""),
             "verdict: %s - %s" % (rec.get("verdict") or "?", rec.get("reason") or ""),
             "address half: %s" % ("READ" if rec.get("read") else "NOT READ"),
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
            "<p>address half: %s<br>password appearances: %s<br>source: %s<br>"
            "checked: %s</p>"
            % (_esc(addr), _PAGE_CSS, _esc(addr), _esc(rec.get("verdict") or "?"),
               _esc(rec.get("reason") or ""),
               "READ" if rec.get("read") else "NOT READ",
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
    """(text, html) of a record, for a page that must always offer a view.

    Returns ("", "") rather than raising, so a caller can fall back to its own
    builder without a try of its own.
    """
    try:
        page = _page_from_record(rec or {}, "records", force=True)
        return (str(page.get("page_text") or ""),
                str(page.get("page_html") or ""))
    except Exception:
        return "", ""


def _fill_page(page, got, addr, kind="records") -> dict:
    """The captured page fields from what the browser already rendered.

    `got` is the JS_READ dict when the caller has one, else None and the page is
    read here. No navigation: by this point the account page is already loaded,
    so a second goto would double the round trips for the same markup.
    """
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
    """The per-user cache path for THIS thread's owner. Never bare."""
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

    401 is in the list because the anonymous unifiedsearch endpoint answers 401.
    It used to fall through to json.loads("") and parse as an EMPTY payload, so
    an address with ten breaches was reported as having none - the quietest
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
# tier 2b - the OPTIONAL keyed API (only when HIBP_API_KEY is set)
# ---------------------------------------------------------------------------
def _keyed_search(addr, pw):
    """The keyed API answer, or None to fall through to the keyless tiers.

    None means "this tier could not answer": no key, a rejected key, a rate
    limit, an unreadable body or a transport error. A 404 is an ANSWER (no
    record) and returns a normal record with count 0.
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
# tier 3 - the browser pool: THE UI, DRIVEN LIKE A PERSON
# ---------------------------------------------------------------------------
class _BrowserPool:
    """One thread owns Playwright, one browser, one context, N reused pages.

    Playwright's sync API is not thread safe, so the driver lives on its own
    thread and callers wait on a Future. The context is shared so the clearance
    cookie is too, which is the entire reason the tier works.

    Each job carries its OWNER, and the driver pins it before it touches a page,
    so a pool line lands in the right user's trace and the page a job takes can
    never be handed to another job while it is in use.
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
        """Spawn the driver thread and wait for the boot. Raises on boot failure.

        THE WAIT IS OUTSIDE _lock. Every worker's _http_search takes _lock to
        record the URL, so a wait held under it stalls the other workers for the
        whole launch - a slower version of the deadlock it replaced.

        A DEAD THREAD IS RESPAWNED. Previously _pool stayed non-None after a
        failed boot, so this method returned at once on every later call and
        re-raised the stale error for the life of the process: one bad launch
        took the address tier out until a redeploy. The error is cleared before
        the new thread starts, and kept in _pool_boot_err for the page.
        """
        global _pool_boot_err
        with _lock:
            alive = self._thread is not None and self._thread.is_alive()
            if not alive:
                self._boot_err = ""
                self._closed = False
                self._started.clear()
                self._thread = threading.Thread(target=self._run,
                                                name="breach-browser", daemon=True)
                self._thread.start()
            started = self._started
        started.wait(BOOT_WAIT)
        if self._boot_err:
            _pool_boot_err = self._boot_err
            raise RuntimeError(self._boot_err)

    def _run(self):
        global _pool_boot_err
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
            _pool_boot_err = self._boot_err
            trace("ERR", "browser", "launch failed: %s" % self._boot_err)
            self._started.set()
            return

        _pool_boot_err = ""
        self._started.set()
        while not self._closed:
            try:
                job = self._q.get(timeout=1.0)
            except queue.Empty:
                continue
            if job is None:
                break
            addr, pw_s, fut, job_owner = job
            # Pin the job's owner on THIS thread before any trace call, so a
            # pool line is written to the file of the user whose address it is.
            set_owner(job_owner)
            page = None
            try:
                page = self._take(context)
                trace("INFO", "browser", "page taken", addr)
                started = time.time()
                cap_status, cap_body = self._ui_search(page, addr)
                got = None
                if cap_status == 200 and cap_body:
                    try:
                        rec = _parse_payload(addr, json.loads(cap_body),
                                             "browser", started, pw_s)
                        trace("INFO", "browser", "json caught from the page: %s "
                              "breach(es)" % len(rec["breaches"]), addr)
                        got = self._read(page)
                    except Exception as exc:
                        trace("WARN", "browser", "caught json unparsable (%s) - "
                              "scraping the DOM" % type(exc).__name__, addr)
                        rec, got = self._dom_record(page, addr, pw_s)
                elif cap_status == 404:
                    rec = _blank(addr, pw_s)
                    rec["via"] = "browser"
                    rec["count"] = 0
                    got = self._read(page)
                elif cap_status in (401, 403, 429, 503):
                    # THE JSON FAILING DOES NOT MEAN THE PAGE FAILED. The in-page
                    # fetch hits the same wall the DOM already got past, so the
                    # rendered page is read FIRST and the 401 is only the reason
                    # when the DOM has nothing either. This is the branch that
                    # discarded sportmedizin's rendered page.
                    rec, got = self._dom_record(page, addr, pw_s)
                    if rec.get("error"):
                        rec["error"] = ("challenge survived (http %d) - %s"
                                        % (cap_status, rec["error"]))
                    trace("WARN", "browser",
                          "json challenged (http %d), dom read: %s"
                          % (cap_status, "empty" if rec.get("error") else "ok"), addr)
                else:
                    rec, got = self._dom_record(page, addr, pw_s)

                if rec.get("error") or rec.get("count") is not None:
                    kind = ("records" if rec.get("count") else
                            ("error" if rec.get("error") else "clean"))
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
        """Land on the site and sit out the interstitial.

        The budget is ROOT_SETTLE, not CHALLENGE_WAIT: the context already holds
        the clearance cookie, so the root normally loads first time and only a
        genuinely re-challenged session spends the full window. The long window
        is spent where it counts, on the account page in _await_render.
        """
        trace("INFO", "browser", "landing on %s/ to clear" % HIBP_BASE)
        page.goto(HIBP_BASE + "/", wait_until="domcontentloaded", timeout=NAV_TIMEOUT)
        self._settle(page, ROOT_SETTLE)

    def _settle(self, page, budget):
        """True once the page is not an interstitial. Never raises.

        Used on ANY url, not just the root: the challenge token is minted per
        navigation, so an account page can arrive walled. Returns False on expiry
        so the caller can decide, rather than pretending it cleared.
        """
        deadline = time.time() + budget
        while True:
            try:
                title = (page.title() or "").lower()
            except Exception:
                title = ""
            if not any(m in title for m in INTERSTITIAL_MARKS):
                return True
            if time.time() >= deadline:
                return False
            try:
                page.wait_for_timeout(900)
            except Exception:
                time.sleep(0.9)

    def _read(self, page):
        """The rendered page as {links, text, html}. Never raises."""
        try:
            return page.evaluate(JS_READ) or {}
        except Exception as exc:
            trace("WARN", "browser", "read failed: %s" % type(exc).__name__)
            return {}

    def _await_render(self, page):
        """Wait until the result is on the page. Returns the anchor count.

        A CHALLENGE ON THE ACCOUNT URL IS WAITED OUT, not counted as a failed
        render - the interstitial has no anchors and no "no pwnage" copy, so the
        flat 8s loop used to expire on a page that was still solving and report
        zero. The render ceiling only starts once the page is real.
        """
        hard = time.time() + RENDER_WAIT + CHALLENGE_EXTRA
        while time.time() < hard:
            try:
                title = (page.title() or "").lower()
            except Exception:
                title = ""
            if any(m in title for m in INTERSTITIAL_MARKS):
                try:
                    page.wait_for_timeout(900)
                except Exception:
                    time.sleep(0.9)
                continue
            try:
                n = page.evaluate(
                    "() => document.querySelectorAll(\"a[href*='/breach/']\").length")
            except Exception:
                n = 0
            if n:
                return int(n)
            try:
                low = (page.evaluate(
                    "() => document.body ? (document.body.innerText || '') : ''"
                ) or "").lower()
            except Exception:
                low = ""
            if any(m in low for m in CLEAN_MARKS):
                return 0
            try:
                page.wait_for_timeout(500)
            except Exception:
                time.sleep(0.5)
        return 0

    def _ui_search(self, page, addr):
        """Type the address into the site's own box and land on its page.

        Returns (status, body) for the JSON response the page fired on its own, if
        any was caught. status 0 means nothing was caught and the caller must read
        the DOM instead - which is the normal path when the endpoint is walled.

        The address typed is _email_only(), so the box receives the bare address
        and never a combo tail. If no box can be found, or the click is swallowed
        by a banner, it navigates straight to the account page: same page, same
        render, just no typing.
        """
        addr = _email_only(addr)
        cap = {}

        def _on_response(resp):
            try:
                if "/unifiedsearch/" in resp.url and "status" not in cap:
                    cap["status"] = resp.status
                    if resp.status == 200:
                        cap["body"] = resp.text()
            except Exception:
                pass

        try:
            page.on("response", _on_response)
        except Exception:
            pass
        try:
            # ALWAYS, not only off-site. The pool hands back a page still sitting
            # on the previous account URL, so the old guard skipped the clear and
            # the box lookup ran against the last address's DOM - which is the
            # 38 ms "no search box found" in every trace.
            self._clear(page)
            box = None
            used = ""
            for sel in UI_SEARCH_SELECTORS:
                try:
                    page.wait_for_selector(sel, timeout=1200)
                except Exception:
                    pass
                try:
                    box = page.query_selector(sel)
                except Exception:
                    box = None
                if box is not None:
                    used = sel
                    break
            if box is None:
                trace("WARN", "ui", "no search box found - navigating directly", addr)
                page.goto(account_url(addr), wait_until="domcontentloaded",
                          timeout=NAV_TIMEOUT)
            else:
                trace("INFO", "ui", "typing the address into %s" % used, addr)
                try:
                    try:
                        box.scroll_into_view_if_needed(timeout=4000)
                    except Exception:
                        pass
                    box.click(timeout=6000)
                    box.fill("")
                    box.type(addr, delay=20)
                    box.press("Enter")
                except Exception as exc:
                    trace("WARN", "ui", "box failed (%s) - navigating directly"
                          % type(exc).__name__, addr)
                    page.goto(account_url(addr), wait_until="domcontentloaded",
                              timeout=NAV_TIMEOUT)
                else:
                    try:
                        page.wait_for_url("**/account/**", timeout=NAV_TIMEOUT)
                    except Exception:
                        trace("WARN", "ui", "no navigation to an account page", addr)
                        if "/account/" not in (page.url or ""):
                            page.goto(account_url(addr),
                                      wait_until="domcontentloaded",
                                      timeout=NAV_TIMEOUT)
            trace("INFO", "ui", "landed on %s" % (page.url or "-")[:140], addr)
            n = self._await_render(page)
            trace("INFO", "ui", "rendered %s breach link(s)" % n, addr)
        except Exception as exc:
            trace("ERR", "ui", "%s: %s" % (type(exc).__name__, exc), addr)
        finally:
            try:
                page.remove_listener("response", _on_response)
            except Exception:
                pass
        return int(cap.get("status") or 0), str(cap.get("body") or "")

    def _dom_record(self, page, addr, pw):
        """Build the record from what actually rendered. Returns (rec, got).

        This is the path with no key and no caught JSON: the anchors are the
        breach names, the text beside them carries the date, the data classes and
        the accounts figure, and the same read supplies the text and HTML view.
        """
        rec = _blank(addr, pw)
        rec["via"] = "browser"
        try:
            page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(400)
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

    def submit(self, addr, pw, job_owner=None):
        addr = _email_only(addr)
        fut = _cf.Future()
        self._q.put((addr, pw, fut, owner() if job_owner is None else job_owner))
        trace("INFO", "browser", "queued in pool", addr)
        return fut

    def stop(self):
        self._closed = True
        self._q.put(None)


def _get_pool():
    """The process pool, started once.

    The page count is read BEFORE the lock: _pages() takes the same lock, so
    reading it inside the with-block on a non-reentrant lock would block for ever
    - which is exactly what froze every keyless run. _lock is an RLock as well,
    so either half of the fix holds on its own.

    The lock is RELEASED before start(), because start() waits for a chromium
    launch and the workers take _lock too.

    The pool is shared by every user on purpose - one Chromium, one clearance
    cookie - and pages are created on demand, so a second user's addresses are
    not capped by the first user's page count. They do share the QUEUE, so a
    large run delays a small one.
    """
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

    The address half is tried in order: the optional keyed API when a key exists,
    the keyless endpoint, then the browser - which drives the site's own search
    box and scrapes what renders. With no key the browser IS the method.

    The OWNER and the CONFIG are taken from the calling thread, which check_many
    pins before it dispatches. A direct call from an unpinned thread (CLI) falls
    back to auth and to the process default, which is the same answer.
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
            trace("WARN", "api", "keyed tier did not answer - keyless next", addr)
    if addr_rec is None:
        addr_rec = _http_search(addr, password)
    if addr_rec.get("error", "").startswith("challenge"):
        if allow_browser and available():
            try:
                pool = _get_pool()
                trace("INFO", "browser", "handing off to the browser tier (UI)", addr)
                addr_rec = pool.submit(addr, password).result(timeout=_budget())
                # ONE retry, and only for an EMPTY READ - a page that rendered and
                # held nothing. A TimeoutError already means the pool was slower
                # than the whole budget, so re-queueing it pays the same wait a
                # second time behind the addresses still queued; the page the
                # first job produced arrives later anyway.
                _cut = "TimeoutError" in str(addr_rec.get("error") or "")
                if (not addr_rec.get("breaches") and addr_rec.get("error")
                        and not _cut):
                    trace("WARN", "browser", "empty read - one retry", addr)
                    _again = pool.submit(addr, password).result(timeout=_budget())
                    if _again.get("breaches") or not _again.get("error"):
                        addr_rec = _again
            except Exception as exc:
                # FOLDED INTO addr_rec, not into rec. rec["error"] is overwritten
                # from addr_rec a few lines below, so writing it here used to throw
                # the reason away and leave only the bare "challenge (http NNN)" -
                # the page never said why the browser had failed.
                addr_rec["error"] += (" | browser failed: %s: %s"
                                      % (type(exc).__name__, exc))
                trace("ERR", "browser", "browser failed: %s: %s"
                      % (type(exc).__name__, exc), addr)
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
    # READ, VERSUS ZERO. count 0 with no error is a page that was read and lists
    # nothing; count None is a page nobody managed to read. They used to render
    # identically as "0 breaches". partial_read marks a verdict that rests on the
    # password half alone.
    rec["read"] = bool(addr_rec.get("count") is not None
                       and not addr_rec.get("error"))
    rec["partial_read"] = bool(not rec["read"] and rec.get("pw_count") is not None)
    for _k in ("page_url", "page_html", "page_text", "page_via", "page_error",
               "page_at"):
        if _k in addr_rec:
            rec[_k] = addr_rec[_k]

    # v13.86 FIX PAGE-1: A RECORD WITH NO PAGE NOW GETS ONE. In fast mode
    # "records" is not a captured kind, so a 10-breach address carried no page at
    # all and block 009 had nothing to draw a Text/HTML toggle from. The page is
    # built from the record itself - no extra request - and marked page_via "api"
    # so it is never passed off as a captured page. This also covers a failed
    # address tier, where the view is the only artefact left to inspect.
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
    """The last-address card, kept PER OWNER.

    One shared dict meant the page's "Last URL" caption showed whichever user
    touched the file last, which could be somebody else's address.
    """
    with _lock:
        who = owner()
        cur = _lasts.get(who) or {}
        cur.update({"ts": time.time(), "email": rec.get("email", ""),
                    "verdict": rec.get("verdict", ""), "via": rec.get("via", ""),
                    "ms": rec.get("elapsed_ms", 0), "error": rec.get("error", ""),
                    "url": rec.get("url") or cur.get("url", "")})
        _lasts[who] = cur


def last_url() -> str:
    """The exact address URL last put on the wire by THIS owner - the proof the
    tail was cut."""
    with _lock:
        return (_lasts.get(owner()) or {}).get("url", "")


def check_many(pairs, workers=2, progress=None, cancel=None, force=False,
               delay=None, http_only=None, owner_prefix=None) -> dict:
    """Check every (email, password) pair. Returns {email: record}.

    Paced on purpose: `workers` bounds concurrency, `delay` bounds the rate at
    which NEW addresses are started. Each address is a whole page load, so the
    defaults are 2 and 3s rather than 8 and 0.

    progress() is called on START as well as on finish, with the verdict "starting".
    Without the start call nothing on the page moves until the first address has
    finished, so a slow first address looks like a frozen app.

    THE RUN IS PINNED: owner_prefix (else this thread's owner) and a config
    snapshot are set on every worker before any address is dispatched, so a
    second user's configure() or another unlock cannot retune or re-prefix a run
    that is already going.
    """
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
        # Each worker is its own thread and ThreadPoolExecutor reuses threads
        # across runs, so the pin and the snapshot are re-applied per task.
        set_owner(pin)
        _pin_cfg(snap)
        em, pw = item
        rec = None
        if cancel is not None and cancel.is_set():
            rec = _blank(em, pw)
            rec["verdict"] = rec["bucket"] = "UNKNOWN"
            rec["error"] = "cancelled"
            trace("WARN", "cancel", "cancelled before the check", em)
        else:
            trace("INFO", "start", "checking", em)
            # STARTED, not finished: the bar and the live trace move on dispatch.
            _tell(position, em, "starting")
            try:
                rec = check(em, pw, force=force, allow_browser=not ho)
            except Exception as exc:
                # check() swallows everything itself, but nothing in this file
                # calls future.result(), so an escape here would leave the record
                # missing AND the counter stuck - the run would look hung at N.
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
        for position, item in enumerate(uniq, 1):
            out.setdefault(item[0], check(item[0], item[1], force=force,
                                          allow_browser=not ho))
            _tell(position, item[0], out[item[0]].get("verdict", ""))
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
    with _lock:
        mine = dict(_lasts.get(owner()) or {})
    return {"version": BREACH_VERSION, "browser": available(),
            "browser_state": browser_state().get("state", ""),
            "browser_error": browser_note(), "pages": _pages(), "delay": _delay(),
            "http_only": _http_only(), "pool": _pool is not None,
            "key": bool(_api_key()), "tier": "ui", "owner": owner(),
            "boot_failed_ago": (int(time.time() - _pool_boot_failed)
                                if _pool_boot_failed else 0),
            "page_mode": _page_mode(), "page_on": list(_page_on()),
            "last": mine, "trace_seq": trace_seq()}


# ---------------------------------------------------------------------------
# selftest / probe
# ---------------------------------------------------------------------------
def selftest(verbose=False) -> bool:
    checks = []

    def add(n, ok):
        checks.append((n, bool(ok)))

    # ---- the deadlock that froze every keyless run ----
    add("lock_reentrant", type(_lock).__name__ == "RLock")
    add("pages_under_lock", _pages() >= 1)

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
    # ---- READ, VERSUS ZERO ----
    add("blank_read_false", _blank("a@b.co").get("read") is False)
    add("blank_partial_false", _blank("a@b.co").get("partial_read") is False)

    # ---- ISOLATION: the owner pins the paths, and does not survive a thread --
    _was_owner = owner()
    set_owner("aaaa1111")
    add("owner_pins", owner() == "aaaa1111")
    add("user_file_prefixed", _user_file(CACHE_NAME) == "aaaa1111_" + CACHE_NAME)
    add("cache_path_prefixed", _path().endswith("aaaa1111_" + CACHE_NAME))
    add("trace_path_prefixed", _trace_path().endswith("aaaa1111_" + TRACE_NAME))
    set_owner("bbbb2222")
    add("owner_switches", _path().endswith("bbbb2222_" + CACHE_NAME))
    add("two_users_differ", _user_file("x") != "aaaa1111_x")
    set_owner("")
    add("owner_empty_falls_back", bool(_user_file(CACHE_NAME)))
    add("owner_empty_not_prefixed", not _user_file("x").startswith("bbbb2222_"))

    # ---- ISOLATION: a snapshot beats another user's configure() ----
    _saved_cfg = dict(_cfg)
    configure(page_mode=PAGE_MODE_FULL, page_on=("clean", "error"), delay=1.0)
    _mine = _snapshot_cfg(False)
    _pin_cfg(_mine)
    configure(page_mode=PAGE_MODE_OFF, page_on=(), delay=9.0)
    add("snapshot_keeps_mode", _page_mode() == PAGE_MODE_FULL)
    add("snapshot_keeps_on", _page_on() == ("clean", "error"))
    add("snapshot_keeps_delay", _delay() == 1.0)
    add("snapshot_still_wants", page_wanted("clean") and page_wanted("records"))
    _pin_cfg(None)
    add("no_snapshot_reads_default", _page_mode() == PAGE_MODE_OFF)
    with _lock:
        _cfg.clear()
        _cfg.update(_saved_cfg)

    # ---- ISOLATION: the ring and the last-address card are per owner ----
    set_owner("aaaa1111")
    _seq_a = trace_seq()
    trace("INFO", "selftest", "mine a", "a@b.co")
    _mine_a = [e for e in trace_read(limit=50, since=_seq_a)]
    set_owner("bbbb2222")
    add("ring_other_owner_empty", trace_read(limit=50, since=_seq_a) == [])
    _seq_b = trace_seq()
    trace("INFO", "selftest", "mine b", "b@b.co")
    add("ring_own_visible", len(trace_read(limit=50, since=_seq_b)) == 1)
    set_owner("aaaa1111")
    add("ring_a_still_there", len(_mine_a) == 1)
    add("ring_a_not_b", all(e.get("owner") == "aaaa1111" for e in _mine_a))

    set_owner("aaaa1111")
    _remember({"email": "a@b.co", "url": "u-a"})
    set_owner("bbbb2222")
    _remember({"email": "b@b.co", "url": "u-b"})
    add("last_url_own", last_url() == "u-b")
    set_owner("aaaa1111")
    add("last_url_other_kept", last_url() == "u-a")
    add("report_owner", report().get("owner") == "aaaa1111")

    # ---- clearing the ring must not wipe another owner ----
    set_owner("aaaa1111")
    _seq_c = trace_seq()
    trace("INFO", "selftest", "c", "c@b.co")
    set_owner("bbbb2222")
    _b_before = len(trace_read(limit=200, since=_seq_c - 1))
    set_owner("aaaa1111")
    trace_clear()
    set_owner("bbbb2222")
    add("clear_kept_other", len(trace_read(limit=200, since=_seq_c - 1)) == _b_before)
    set_owner(_was_owner)

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

    # ---- dates out of a rendered page ----
    add("date_iso", _any_date("2015-01-02") == "2015-01-02")
    add("date_long", _any_date("Breach date: 4 October 2013") == "2013-10-04")
    add("date_none", _any_date("nothing here") == "")

    # ---- scraping the rendered page ----
    _txt = ("Adobe\nBreach date: 4 October 2013\nAccounts: 152,445,165\n"
            "Compromised data: Email addresses, Passwords\n"
            "Stealer Logs\nBreach date: 1 June 2026\nAccounts: 4,000\n"
            "Compromised data: Passwords\n")
    _links = [{"t": "Adobe", "h": "/breach/Adobe"}, {"t": "Stealer Logs", "h": "/breach/X"}]
    _got_b, _got_clean = _parse_rendered(_txt, _links)
    add("scrape_count", len(_got_b) == 2)
    add("scrape_date", _got_b[0]["date"] == "2013-10-04")
    add("scrape_days", _got_b[0]["days"] is not None)
    add("scrape_classes", "Passwords" in _got_b[0]["classes"])
    add("scrape_accounts", _got_b[0]["pwn_count"] == 152445165)
    add("scrape_corpus", _got_b[1]["corpus"] is True)
    add("scrape_not_clean", _got_clean is False)
    add("scrape_clean", _parse_rendered("Good news - no pwnage found", [])[1] is True)
    add("scrape_empty", _parse_rendered("", []) == ([], False))

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
    add("report_tier", report().get("tier") == "ui")
    add("report_boot", isinstance(report().get("boot_failed_ago"), int))
    add("state_shape", "state" in browser_state())
    add("note_is_str", isinstance(browser_note(), str))
    add("env_set", os.environ.get("PLAYWRIGHT_BROWSERS_PATH") == _PW_DIR)

    # ---- the UI tier ----
    add("ui_selectors", bool(UI_SEARCH_SELECTORS))
    add("ui_selector_id_first", UI_SEARCH_SELECTORS[0] == "input#searchInput")
    add("js_read_links", "breach/" in JS_READ)
    add("js_read_innertext", "innerText" in JS_READ)
    add("js_read_dedupes", "seen" in JS_READ)
    add("js_read_fallback", "class*='pwned'" in JS_READ)
    add("render_ceiling_raised", RENDER_WAIT >= 12.0)
    add("challenge_ceiling", CHALLENGE_EXTRA > 0)
    add("root_settle_shorter", ROOT_SETTLE < CHALLENGE_WAIT)
    add("interstitial_marks", "just a moment" in INTERSTITIAL_MARKS)
    add("settle_exists", hasattr(_BrowserPool, "_settle"))
    add("clear_unconditional", "if \"haveibeenpwned.com\" not in"
        not in inspect.getsource(_BrowserPool._ui_search))
    add("ui_waits_for_box", "wait_for_selector" in
        inspect.getsource(_BrowserPool._ui_search))
    add("dom_record_scrolls", "scrollTo" in inspect.getsource(_BrowserPool._dom_record))
    add("dom_read_on_wall", "_dom_record(page, addr, pw_s)" in
        inspect.getsource(_BrowserPool._run))
    add("check_retries_once", "one retry" in inspect.getsource(check))
    add("gen_force_param", "force" in inspect.signature(_page_from_record).parameters)
    add("key_optional", isinstance(_api_key(), str))
    add("keyed_account_url", "breachedaccount" in ACCOUNT_API and
        ACCOUNT_API.startswith(HIBP_BASE))
    add("keyed_paste_url", "pasteaccount" in PASTE_API)
    add("keyed_truncate", "truncateResponse=false" in ACCOUNT_API)
    add("keyed_header_name", KEY_ENV == "HIBP_API_KEY")
    _pr = {"email": "a@b.co", "verdict": "OLD", "reason": "r", "via": "api",
           "read": True, "pw_count": 3,
           "breaches": [{"title": "X", "date": "2015-01-01",
                         "days": 4000, "pwn_count": 12,
                         "classes": ["Passwords"]}],
           "pastes": [], "checked_at": "2026-01-01 00:00:00"}
    _gen = _page_from_record(_pr, "clean")
    add("gen_text", "breaches: 1" in _gen["page_text"] and "X" in _gen["page_text"])
    add("gen_html", "<table" in _gen["page_html"] and "2015-01-01" in _gen["page_html"])
    add("gen_marked", _gen["page_via"] == "api")
    add("gen_skipped", _page_from_record(_pr, "records")["page_text"] == "")
    add("gen_forced", _page_from_record(_pr, "records", force=True)["page_text"] != "")
    # ---- the CSS survives %-formatting: the bug that emptied every page ----
    add("page_percent_css", "100%" in
        _page_from_record({"email": "a@b.co"}, "clean")["page_html"])
    add("page_on_error_text", "could be read" in
        _page_from_record({"email": "a@b.co", "error": "challenge (http 401)"},
                          "error", force=True)["page_text"])
    add("record_view_pair", record_view({"email": "a@b.co"})[0] != "")
    add("record_view_never_raises", record_view(None) == ("", ""))
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
    add("check_many_takes_owner",
        "owner_prefix" in inspect.signature(check_many).parameters)
    add("submit_takes_owner", "job_owner" in inspect.signature(
        _BrowserPool.submit).parameters)
    add("run_pins_owner", "set_owner(job_owner)" in
        inspect.getsource(_BrowserPool._run))
    add("ensure_browser_declares_pw_state",
        "_pw_state" in inspect.getsource(ensure_browser).split("\n")[1])
    configure(http_only=True)
    add("http_only_on", _http_only() is True)
    configure(http_only=False)
    add("http_only_off", _http_only() is False)
    configure(http_only=None)
    add("http_only_untouched", _http_only() is False)

    # ---- the boot path, second pass ----
    add("boot_waits_outside_lock", "started.wait" in inspect.getsource(_BrowserPool.start))
    add("boot_respawns_dead_thread", "is_alive" in inspect.getsource(_BrowserPool.start))
    add("boot_clears_error", "_boot_err = \"\"" in inspect.getsource(_BrowserPool.start))
    add("boot_releases_before_start",
        inspect.getsource(_get_pool).index("with _lock") <
        inspect.getsource(_get_pool).index("pool.start"))
    add("boot_error_kept", "_pool_boot_err" in inspect.getsource(_BrowserPool.start))
    add("note_reports_boot", "_pool_boot_err" in inspect.getsource(browser_note))
    add("available_checks_boot", "_pool_boot_failed" in inspect.getsource(available))
    add("check_keeps_reason", "addr_rec[\"error\"] +=" in inspect.getsource(check))
    add("timeout_default_roomy", _cfg["timeout"] >= 90.0)
    # ---- the budget covers a queue slot, not just one page ----
    add("budget_covers_queue", _cfg["timeout"] >= 180.0)
    add("budget_from_snapshot", "one retry" in inspect.getsource(check)
        and "_budget()" in inspect.getsource(check))
    add("retry_skips_cut_calls", "_cut" in inspect.getsource(check))
    add("check_many_guards_one", "rec = check(em, pw" in inspect.getsource(check_many))

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
        print("tier:", "http-only" if only else "http+browser (UI)")
        print("key:", "present" if _api_key() else "absent (browser does the work)")
        print("browser available:", available(), browser_note())
        res = check(pairs[0][0], pairs[0][1], force=True)
        print("url sent:", last_url())
        print(json.dumps({k: res.get(k) for k in ("email", "verdict", "pw_count",
                                                  "count", "read", "via", "error")},
                         indent=2))
        print(trace_text(limit=40))
        return 0 if res.get("verdict") else 1
    selftest(verbose=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
