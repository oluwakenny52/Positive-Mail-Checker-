"""breach.py - breach exposure and combo freshness.  v13.86

THE FLOW IS THE COLAB FLOW, WITH A SECOND SOURCE BEHIND IT
----------------------------------------------------------
Per item: build the unifiedsearch URL, then up to PROXY_TRIES (3) attempts, each
one a random live node from the owner's own pool in a real headless Chromium
with the proxy on the context.

    200 + JSON     parse it, remember the node as via_proxy, stop
    404            the site's own "not in any breach", stop
    401 / 403      the endpoint refusing the CALLER - next node, then DIRECT
    anything else  next node

A 200 that is NOT JSON is the only case that gets a same-origin fetch() from
inside the page: there is a document to fetch from and the shell may carry what
the plain navigation lacked. A 401 does NOT get one - it is the same 401 from the
same address and it only costs a request.

THE WALL IS ABOUT THE CALLER, NOT THE NODE
------------------------------------------
`{"message": "You're probably a bot, try the official API instead"}` with a
`cf-ray` header is HIBP's own answer, produced by Cloudflare's bot score. A node
that produces it is ALIVE: the tunnel opened, TLS completed, the edge answered,
and the egress IP in the line is the node's own. Only a transport failure is a
dead node. So the flight keeps any node the target ANSWERED (200, 401, 403, 404,
429) and counts the 200s separately, and the reader does not need a 200 either,
because a walled address has a second source.

THE SECOND SOURCE IS PER-ADDRESS AND OUTSIDE THE WALL
-----------------------------------------------------
XposedOrNot (`/v1/breach-analytics`) is keyless, is not behind the HIBP wall, and
answers the EXACT address with breach names, domains, years, record counts, data
classes and descriptions. The HIBP catalogue then names the same breaches, so the
row is filled with the real date and record count instead of a bare name. It is
tried only when the HIBP half was walled, and the record says so: `via` is
`xposedornot`, `read` is True and `partial_read` is False, because the address
half WAS read - just not by HIBP. A miss there is a readable zero and is labelled
as an index miss; an unreachable XposedOrNot falls through to the catalogue.

WHAT A ZERO IS
--------------
A 404 is the site's own "not in any breach" - an answer about the ADDRESS. A 401
is the endpoint refusing the CALLER, which says nothing about the mailbox, so it
is retried (three nodes, then DIRECT) and then handed to the second source
instead of being reported as clean. A zero is only ever reported from a source
that actually answered.

THE FREE SOURCES FILL THE WALL
------------------------------
Pwned Passwords and the public catalogue are both keyless and neither is behind
the wall. When the address half is walled and nothing readable came back, the
exact address goes to XposedOrNot first; only if that fails too is the domain
looked up in the catalogue and filled as a DOMAIN match, flagged `partial_read`.
A domain answer is worth more than an empty card, and it is labelled for what it
is. When the domain has nothing either, the address half stays UNREAD - a wall is
never a zero.

A COMBO IS GRADED ON BOTH HALVES
--------------------------------
`_combine()` takes the worse half. A password-only band is only a valid VERDICT
when the password is all that was asked for - a line with no '@'. When the line is
a combo and the address half could not be read, the combo is UNKNOWN: the password
band is still shown beside it, but it no longer decides the grade.

THE TEST FLIGHT IS ONE NAVIGATION PER NODE
------------------------------------------
The Colab fired ONE page.goto per candidate and 32 of 141 came back 200. Our
build was firing about five requests per node - the navigation, an in-page
re-fetch, a homepage warm-up, a retry, then the whole dressed context again - at
eleven shared exit IPs. The homepage still answers 200 while /unifiedsearch/
answers 401 on every node, so the browser and the proxy are both fine: the wall
had simply been fed too much. The flight is now the Colab call and nothing more.

    candidates   the owner's own proxies.txt FIRST, minus everything
                 proxy_meta.json marks dead / auth / timeout; proxies_secret.txt
                 and proxies_custom.txt next; the Webshare and Oxylabs APIs only
                 when all of that is empty
    dedupe       BY FULL LINE. `u:p@1.2.3.4:8080` and `v:q@1.2.3.4:8080` are two
                 candidates: the gateway judges the CREDENTIAL, so a dead sub-user
                 must not hide a live one behind the same IP. FLIGHT_MAX (200) is
                 above the 140 lines a full Webshare import produces.
    step 1       ipify, 8 s, dead nodes dropped with the REAL reason
    step 2       headless Chromium, TWO at a time, one context per node, ONE
                 navigation, with a short random jitter before it so two lanes
                 never land on the same exit IP in the same instant
    carry        the target ANSWERED the node: 200, 404, 401, 403 or 429
    read         200 AND a JSON body - counted separately, and the early stop
                 waits for FLIGHT_READ_WANT of them, never for the first few
    log          "    ✅ 200 -> host:port | country | city | egress IP"
                 "    keep  -> host:port | carried (401) | country | city | egress"
                 "    skip  -> host:port | test flight failed (reason) | egress IP"
    save         every carried node, one per line, to proxies_breach.txt
    summary      "[*] Passed test flight (✅ 200) : N", the carried count and the
                 file name

LOW BURST PRESSURE IS THE POINT
-------------------------------
FLIGHT_WORKERS is 2 and every node waits a random 0-0.7 s first. Eleven shared
exit IPs cannot absorb five lanes firing back to back; they can absorb two that
are staggered. Slower is faster here. The pool is then kept for an hour
(POOL_TTL), because a flight is itself a burn: the same exits flown every half
hour arrive already scored.

THE DIAGNOSTIC FLIGHT
---------------------
`diagnose=True` (the "Diagnostic flight" switch on the page) turns the flight
into a transcript instead of a verdict: the node, whether it carries auth, the
exact target, the ipify answer with the real exception when it fails, then the
status, content-type, byte count, the response headers that matter (server,
cf-ray, www-authenticate, via, x-cache) and the first 200 characters of the body.
Credentials are never printed - only host:port and auth=yes/no.

It closes with a count per outcome and a legend for every code it can emit, so a
wall of 401s says WHAT a 401 is here instead of just being one. It does not stop
at FLIGHT_WANT, so every node is reported.

WHY THE EGRESS IP IS LOGGED
---------------------------
ipify in step 1 goes through `requests`, which does use the proxy. The browser
does not necessarily - and if `proxy` is not carried on the context, every node
answers from Streamlit's own address instead of the proxy's, which looks exactly
like "all 401". So each node reads api.ipify.org FROM INSIDE ITS OWN CONTEXT
first and the answer is printed beside the verdict. ipify is a different host, so
it costs the target nothing. If every line shows the same IP, the proxy is not
being applied and that is the bug, not the endpoint.

THE READ IS INFORMATIONAL AND NEVER DROPS A NODE
------------------------------------------------
A Playwright Response exposes text() as a METHOD, not the `.text` property of a
requests Response, so an `_ip_of()` written for requests read nothing - and the
early return then threw every node away as no_egress before the target was ever
requested, while ipify through `requests` had just returned 200 on the same
nodes. `_body_of()` accepts both shapes, the target is always requested, and
`no_egress` survives only as the label for "no egress IP AND no status either".

THE TARGET TAB STARTS AT THE TARGET
-----------------------------------
The egress read happens in its OWN tab of the same context, and that tab is
closed before the target is touched, so the target page is the FIRST page in the
context and its only navigation is the unified URL, with an empty history and no
cross-site Referer.

A GATEWAY THAT FAILS AUTH IS DEAD, NOT LATE
--------------------------------------------
`Tunnel connection failed: 407 Unauthorized` means the gateway rejected the
credentials before a tunnel existed. A browser will not fare better, so an
oxylabs.io gateway that fails ipify on a 407 is skipped at step 1 instead of
burning two 35 s timeouts. Any other ipify failure still pushes it through.

proxies_breach.txt is the ONLY file the flight writes, so the mail checker's own
proxies.txt is never touched; the reader prefers the flight pool while it is
under POOL_TTL old and falls back to proxies.txt otherwise.

THE FLIGHT'S LOG HAS TO BE VISIBLE
----------------------------------
`owner()` is thread-local, so a worker thread that does not pin it traces with an
empty owner and trace_read() filters its lines away - the whole per-node log of a
flight vanished that way. Every flight worker pins the owner first, and a failure
keeps the exception TEXT, not just its class name. The flight also refuses to
start when Chromium is not ready instead of throwing 200 instant failures away.

THE CATALOGUE FILLS THE ZERO
----------------------------
The public catalogue (`/api/v3/breaches`) is keyless, unchallenged and indexed by
domain, so a 404 zero - and now a wall - gets the domain looked up, and if it has
breaches they fill the record with real names, dates, data classes and record
counts. That sets `partial_read`, because it is a DOMAIN match and not an
individual confirmation, and it is never cached as exact. The catalogue is also
indexed by NAME here, so the XposedOrNot path above can name its breaches with
the real date, record count and data classes instead of a bare string.

PAGES ARE TIED TO WORKERS
-------------------------
No page-count control. N workers keep at most N pages, one per worker slot, and
each slot is REUSED: the same context and page serve item after item, reset to
about:blank with its cookies cleared between them. The Chromium process behind a
slot is launched once per worker for the whole batch, so a 500-item run pays for
N browsers, not 500.

A slot recycles itself after SLOT_USES_MAX uses, after SLOT_FAILS_MAX failed
attempts in a row, or when the next attempt wants a different proxy. Recycling is
local: the item in flight is already recorded, so a wedged page can never lose a
finished result and can never hold the queue.

THE DRAW IS RANDOM
------------------
Each attempt draws a RANDOM node from the whole tier-ordered pool, never one
already tried for that item, and a node that fails twice in transport is skipped
for the rest of the run. The `rotate` switch walks the tier order instead.

THE PASSWORD HALF
-----------------
Pwned Passwords k-anonymity: the SHA-1 is computed locally, 5 of its 40 characters
leave the box, and the 35 kept characters are matched locally against the padded
range response. It never touches the address path and it never sees a proxy. The
plaintext is kept on the record so the page can show the combo it came from.

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
    UNKNOWN   nothing readable, or a combo whose address half was never read

count 0 and count None are different facts and `read` says which.

HTML IS WRITTEN AS \x3c ESCAPES
-------------------------------
Every angle bracket in a string literal is written \x3c / \x3e and every entity
is built from chr(38). A paste that strips tags out of literals - which eats a
raw tag down to a bare newline and turns a raw entity into a no-op - cannot
break either form.

Isolation: cache, trace, flight, pool cache, bad-node list, cursor, slots and
state resolve through the pinned owner, which is the unlocked hash, so each is
one file/bucket per user. Plain module, NOT frame-gated, no Streamlit. EVERY
public function swallows.
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

# The second source. Keyless, per-address, and NOT behind the HIBP wall.
XPOSED_BASE = "https://api.xposedornot.com/v1"
XPOSED_ANALYTICS = XPOSED_BASE + "/breach-analytics?email=%s"
XPOSED_TIMEOUT = 20.0
XPOSED_ROWS_MAX = 200

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

# Container necessities only. Colab passes NO launch args at all; these two are
# the ones Streamlit Cloud cannot do without, because it is a container.
CONTAINER_ARGS = ["--no-sandbox", "--disable-dev-shm-usage"]

# The context shape that flies. PROFILE_VANILLA is Colab Cell 3/4 exactly - UA,
# locale, viewport, proxy - and it is what the 32 passes came from. The dressed
# shape is kept intact behind this one constant because every extra option is a
# difference from a setup that works; set it to PROFILE_DRESSED to try again.
PROFILE_VANILLA = "vanilla"
PROFILE_DRESSED = "dressed"
_ACTIVE_PROFILE = PROFILE_VANILLA

# Dressed only. A bare navigation sends none of these; whether that helps is what
# the constant above decides.
CTX_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": HIBP_BASE + "/",
    "Origin": HIBP_BASE,
    "sec-ch-ua": '"Chromium";v="131", "Not_A Brand";v="24", '
                 '"Google Chrome";v="131"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
}

# Dressed only. Read-only getters on the prototypes, values consistent with the
# UA: Windows, a 1080p screen, an Intel GPU, no touch, en-US.
STEALTH_JS = r"""
(() => {
  const put = (obj, prop, value) => {
    try { Object.defineProperty(obj, prop, {get: () => value, configurable: true}); }
    catch (e) {}
  };
  const nav = Navigator.prototype;
  put(nav, 'webdriver', false);
  put(nav, 'platform', 'Win32');
  put(nav, 'vendor', 'Google Inc.');
  put(nav, 'vendorSub', '');
  put(nav, 'productSub', '20030107');
  put(nav, 'languages', ['en-US', 'en']);
  put(nav, 'hardwareConcurrency', 8);
  put(nav, 'deviceMemory', 8);
  put(nav, 'maxTouchPoints', 0);

  const rows = [
    ['PDF Viewer', 'Portable Document Format', 'internal-pdf-viewer'],
    ['Chrome PDF Viewer', 'Portable Document Format', 'internal-pdf-viewer'],
    ['Chromium PDF Viewer', 'Portable Document Format', 'internal-pdf-viewer'],
    ['Microsoft Edge PDF Viewer', 'Portable Document Format', 'internal-pdf-viewer'],
    ['WebKit built-in PDF', 'Portable Document Format', 'internal-pdf-viewer']
  ];
  const plugins = [];
  for (const row of rows) {
    const p = Object.create(Plugin.prototype);
    put(p, 'name', row[0]);
    put(p, 'description', row[1]);
    put(p, 'filename', row[2]);
    put(p, 'length', 1);
    plugins.push(p);
  }
  plugins.item = (i) => plugins[i] || null;
  plugins.namedItem = (n) => Array.prototype.find.call(plugins, (p) => p.name === n) || null;
  put(plugins, 'length', rows.length);

  const mimes = [
    ['application/pdf', 'pdf', 'Portable Document Format', plugins[0]],
    ['text/pdf', 'pdf', 'Portable Document Format', plugins[0]]
  ].map((row) => {
    const m = Object.create(MimeType.prototype);
    put(m, 'type', row[0]);
    put(m, 'suffixes', row[1]);
    put(m, 'description', row[2]);
    put(m, 'enabledPlugin', row[3]);
    return m;
  });
  mimes.item = (i) => mimes[i] || null;
  mimes.namedItem = (n) => Array.prototype.find.call(mimes, (m) => m.type === n) || null;
  put(mimes, 'length', 2);

  const scr = Screen.prototype;
  put(scr, 'width', 1920);
  put(scr, 'height', 1080);
  put(scr, 'availWidth', 1920);
  put(scr, 'availHeight', 1040);
  put(scr, 'colorDepth', 24);
  put(scr, 'pixelDepth', 24);

  const gl = (proto) => {
    if (!proto) return;
    const real = proto.getParameter;
    proto.getParameter = function (p) {
      if (p === 37445) return 'Intel Inc.';
      if (p === 37446) {
        return 'ANGLE (Intel, Intel(R) UHD Graphics 630 Direct3D11 vs_5_0 ps_5_0, D3D11)';
      }
      return real.call(this, p);
    };
  };
  gl(window.WebGLRenderingContext && WebGLRenderingContext.prototype);
  gl(window.WebGL2RenderingContext && WebGL2RenderingContext.prototype);

  if (!window.chrome) put(window, 'chrome', {});
  put(window.chrome, 'runtime', {});
  put(window.chrome, 'app', {
    isInstalled: false,
    InstallState: {INSTALLED: 'installed', MISSING: 'missing', DISABLED: 'disabled'},
    RunningState: {RUNNING: 'running', CANNOT_RUN: 'cannot_run',
                   READY_TO_RUN: 'ready_to_run'}
  });
  put(window.chrome, 'csi', () => ({onloadT: Date.now(), startE: Date.now(),
                                    pageT: 0, tran: 15}));
  put(window.chrome, 'loadTimes', () => ({requestTime: 0, startLoadTime: 0,
                                          commitLoadTime: 0,
                                          finishDocumentLoadTime: 0,
                                          finishLoadTime: 0, firstPaintTime: 0,
                                          navigationType: 'Other'}));

  if (window.Notification) put(Notification, 'permission', 'default');

  try { Object.setPrototypeOf(plugins, PluginArray.prototype); } catch (e) {}
  try { Object.setPrototypeOf(mimes, MimeTypeArray.prototype); } catch (e) {}
  put(nav, 'plugins', plugins);
  put(nav, 'mimeTypes', mimes);
})();
"""

# Same-origin fetch helper for NON-JSON 200 responses only.
FETCH_JS = ("async (u) => {try {const r = await fetch(u, {headers: "
            "{'accept': 'application/json'}, credentials: 'include', "
            "cache: 'no-store'}); const t = await r.text(); "
            "return {status: r.status, body: t};} catch (e) "
            "{return {status: 0, body: ''};}}")

NAV_TIMEOUT = 25000
HTTP_TIMEOUT = 15.0

# The retry set. The reader moves to the next node on these; the flight does not
# re-ask at all.
RETRY_STATUS = frozenset({401, 403, 408, 425, 429, 500, 502, 503, 504})

# A node CARRIED the request when the target ANSWERED it at all. 401/403 are the
# WAF judging the caller, 404 is the site's own zero, 429 is "slow down" - all of
# them mean the tunnel, the TLS and the edge worked, so none of them drops a node.
CARRY_STATUS = frozenset({200, 401, 403, 404, 429})

# The wall. A refusal about the CALLER says nothing about the mailbox.
WALL_STATUS = frozenset({401, 403, 429})

# The Colab limit. Three nodes, then DIRECT if no 404 arrived.
PROXY_TRIES = 3

# A page slot's own terms.
SLOT_USES_MAX = 25
SLOT_FAILS_MAX = 2

# A node skipped for the rest of the run after this many transport fails.
BAD_AFTER = 2

# The catalogue is one request per window for the whole process, not per item.
CATALOGUE_TTL = 6 * 3600.0
CAT_ROWS_MAX = 60

# ---- the test flight -------------------------------------------------------
FLIGHT_NAME = "breach_flight.json"
FLIGHT_POOL = "proxies_breach.txt"
FLIGHT_PROBE = "eddiemurphy@gmail.com"
FLIGHT_MAX = 200
FLIGHT_WANT = 12
FLIGHT_READ_WANT = 12
FLIGHT_WORKERS = 2
FLIGHT_JITTER = 0.7
FLIGHT_BUDGET = 300.0
FLIGHT_TIMEOUT = 35000
FLIGHT_GEO_URL = "http://ip-api.com/json/"
FLIGHT_GEO_TIMEOUT = 8.0
FLIGHT_LOG_MAX = 900
FLIGHT_SNIPPET = 200
IPIFY_WORKERS = 12
IPIFY_TIMEOUT = 8.0
IPIFY_URL = "https://api.ipify.org?format=json"
POOL_TTL = 3600.0
WS_PAGES = 20
WS_PAGE_SIZE = 100
READ_JITTER = 0.25

# Header names worth printing in a diagnostic line. Nothing else is echoed.
DIAG_HEADERS = ("server", "cf-ray", "www-authenticate", "proxy-authenticate",
                "via", "x-cache", "retry-after")

# Every outcome the diagnostic summary can print, in report order.
OUTCOMES = (
    ("200", "read - JSON body accepted, node KEPT"),
    ("404", "endpoint answered not-found - a readable zero for that address, KEPT"),
    ("401", "the WAF refused the CALLER - nothing readable, but the node is alive "
            "and is KEPT"),
    ("403", "forbidden by the WAF - node alive, KEPT"),
    ("429", "rate limited - the node is alive, KEPT, and must slow down"),
    ("5xx", "target-side error - node alive, retried on the next one"),
    ("0", "transport failure - timeout, TLS, reset or proxy dropped"),
    ("no_egress", "no egress IP and no status - the proxy was probably not carried"),
    ("other", "any other status"),
    ("ipify_fail", "the node could not reach ipify at all"),
)

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


def _corpus_key(name) -> str:
    """A breach name reduced to letters and digits, for matching a corpus.

    The catalogue says `Collection #1`, XposedOrNot says `Collection-1`; both
    reduce to `collection1`, so one table matches either spelling.
    """
    try:
        return re.sub(r"[^a-z0-9]+", "", str(name or "").lower())
    except Exception:
        return ""


_CORPUS_KEYS = frozenset(_corpus_key(n) for n in CORPORA)

_cfg = {"timeout": 240.0, "delay": DELAY_DEFAULT, "rotate": True,
        "workers": 3, "pool": None, "flight": True}
_lock = threading.RLock()
_pool_caches = {}
_pool_ttl = 30.0
_cursors = {}
_bads = {}
_slots = {}

_cat_lock = threading.Lock()
_cat = {"ts": 0.0, "by_domain": {}, "by_name": {}, "busy": False, "error": ""}

_flights = {}

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


def _zero_rule(seen) -> bool:
    """A 404 is the site's own 'not in any breach' - a readable zero."""
    try:
        return 404 in seen
    except Exception:
        return False


# ---------------------------------------------------------------------------
# owner
# ---------------------------------------------------------------------------
def set_owner(prefix="") -> str:
    _tls.owner = str(prefix or "")
    return _tls.owner


def owner() -> str:
    return str(getattr(_tls, "owner", "") or "")


def _owner_key() -> str:
    """The bucket name for every per-user table in this module.

    `owner()` first, because it is the only one that survives a worker thread.
    auth.user_key_hash() reads st.session_state, which a bare thread cannot do,
    so it is a fallback and "anonlocal" is the last resort - never a mix.
    """
    p = owner()
    if p:
        return p
    try:
        import auth
        return str(auth.user_key_hash() or auth._anon_id())
    except Exception:
        return "anonlocal"


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


def _read_lines(path):
    """Non-empty, non-comment lines of a file. [] when it is absent."""
    try:
        if not path or not os.path.exists(path):
            return []
        with open(path, encoding="utf-8", errors="ignore") as fh:
            return [l.strip() for l in fh
                    if l.strip() and not l.strip().startswith("#")]
    except Exception:
        return []


def _write_lines(path, lines):
    """Atomic write. True on success."""
    if not path:
        return False
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + ("\n" if lines else ""))
        os.replace(tmp, path)
        return True
    except Exception:
        return False


def _invalidate_pool_cache(who=None):
    k = _owner_key() if who is None else str(who)
    with _lock:
        _pool_caches.pop(k, None)


# ---------------------------------------------------------------------------
# config
# ---------------------------------------------------------------------------
def configure(timeout=None, delay=None, rotate=None, workers=None, pool=None,
              flight=None):
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
        if flight is not None:
            _cfg["flight"] = bool(flight)
        if pool is not None:
            try:
                _cfg["pool"] = [str(p).strip() for p in pool if str(p).strip()]
            except Exception:
                _cfg["pool"] = None
            _invalidate_pool_cache()


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
                "pool": _cfg.get("pool"), "flight": bool(_cfg.get("flight", True))}


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
    return True


def key_present() -> bool:
    try:
        return bool(str(os.environ.get("HIBP_API_KEY") or "").strip())
    except Exception:
        return False


def key_hint() -> str:
    return "keyless - browser, XposedOrNot, catalogue and Pwned Passwords"


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
    return (str(v if v is not None else "").replace(chr(38), _AMP)
            .replace(chr(60), _LT).replace(chr(62), _GT).replace(chr(34), _QUOT))


def _plain(s) -> str:
    import html as _html
    return _html.unescape(_TAG_RE.sub("", str(s or ""))).strip()


def _json_of(body):
    """A JSON OBJECT body, or None. The reader needs a dict."""
    try:
        got = json.loads(str(body or "").strip())
    except Exception:
        return None
    return got if isinstance(got, dict) else None


def _json_any(body):
    """A JSON object OR array body, or None. The flight only needs "it parsed"."""
    try:
        got = json.loads(str(body or "").strip())
    except Exception:
        return None
    return got if isinstance(got, (dict, list)) else None


def _snippet(body, n=None):
    """First `n` characters, whitespace collapsed, for a diagnostic line."""
    try:
        txt = " ".join(str(body or "").split())
    except Exception:
        return ""
    return txt[:int(n or FLIGHT_SNIPPET)]


def _safe_headers(resp):
    """Only the interesting response headers, as `k=v`, or '-'."""
    try:
        items = []
        for k, v in (resp.headers or {}).items():
            if str(k).lower() in DIAG_HEADERS:
                items.append("%s=%s" % (str(k).lower(), str(v)[:60]))
        return " ".join(items) if items else "-"
    except Exception:
        return "-"


# ---------------------------------------------------------------------------
# input parsing - three shapes, decided per line
# ---------------------------------------------------------------------------
def parse_lines(text):
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
    if _corpus_key(name) in _CORPUS_KEYS:
        return True
    if any(k in name for k in ("stealer", "combolist", "credential stuff",
                               "txtbase", "naz.api")):
        return True
    return bool(breach.get("IsSpamList")) and not breach.get("Domain")


def _blank(item, pw="") -> dict:
    email = _email_only(item.get("email") or "") if isinstance(item, dict) else ""
    return {"email": email, "kind": (item.get("kind") if isinstance(item, dict) else ""),
            "password": str(pw or ""),
            "password_len": len(pw or ""), "verdict": "", "bucket": "", "reason": "",
            "breaches": [], "pastes": [], "pw_count": None, "corpora": 0, "sites": 0,
            "sensitive": 0, "stealer": 0, "newest_days": None, "count": None,
            "via": "", "via_proxy": "", "read": False, "partial_read": False,
            "pwned": False, "addr_verdict": "UNREAD", "pw_band": "none",
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
    with _cat_lock:
        _cat["ts"] = 0.0
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
# the public catalogue - keyless, and the one source that is not challenged
# ---------------------------------------------------------------------------
def _cat_fetch():
    try:
        import requests
    except Exception:
        return None
    try:
        trace("INFO", "catalogue", "GET %s" % CATALOGUE_URL)
        r = requests.get(CATALOGUE_URL, timeout=max(20.0, HTTP_TIMEOUT),
                         headers={"User-Agent": UA,
                                  "Accept": "application/json"})
        trace("INFO", "catalogue", "http %d, %d byte(s)"
              % (r.status_code, len(r.content or b"")))
        if r.status_code != 200:
            return None
        data = r.json()
    except Exception as exc:
        trace("ERR", "catalogue", "%s: %s" % (type(exc).__name__, str(exc)[:160]))
        return None
    return data if isinstance(data, list) else None


def catalogue(force=False):
    now = time.time()
    with _cat_lock:
        if not force and _cat["by_domain"] and (now - _cat["ts"]) < CATALOGUE_TTL:
            return _cat["by_domain"]
        if _cat["busy"]:
            return _cat["by_domain"] or None
        _cat["busy"] = True
    rows = None
    try:
        rows = _cat_fetch()
    finally:
        with _cat_lock:
            _cat["busy"] = False
    if rows is None:
        with _cat_lock:
            _cat["error"] = "fetch failed"
        return _cat["by_domain"] or None
    index, names = {}, {}
    for b in rows:
        if not isinstance(b, dict):
            continue
        d = str(b.get("Domain") or "").strip().lower().strip(".")
        if d:
            index.setdefault(d, []).append(b)
        n = _corpus_key(b.get("Name"))
        if n and n not in names:
            names[n] = b
    with _cat_lock:
        _cat["by_domain"] = index
        _cat["by_name"] = names
        _cat["ts"] = time.time()
        _cat["error"] = ""
    trace("INFO", "catalogue", "%d breach(es) indexed over %d domain(s) and %d name(s)"
          % (len(rows), len(index), len(names)))
    return index


def _cat_rows(email):
    cat = catalogue()
    if cat is None:
        return None
    dom = str(email or "").rsplit("@", 1)[-1].strip().lower().strip(".")
    if not dom:
        return []
    for cand in (dom, ".".join(dom.split(".")[-2:])):
        got = cat.get(cand)
        if got:
            got = sorted(got, key=lambda b: str(b.get("BreachDate") or ""),
                         reverse=True)
            return got[:CAT_ROWS_MAX]
    return []


def _cat_row_by_name(name):
    """The catalogue row for a breach NAME, or None. Read-only, cached."""
    cat = catalogue()
    if not cat:
        return None
    key = _corpus_key(name)
    if not key:
        return None
    with _cat_lock:
        return (_cat.get("by_name") or {}).get(key)


def catalogue_state() -> dict:
    with _cat_lock:
        return {"domains": len(_cat["by_domain"]), "age": int(time.time() - _cat["ts"])
                if _cat["ts"] else -1, "error": _cat["error"]}


# ---------------------------------------------------------------------------
# the second source - keyless, per-address, and outside the wall
# ---------------------------------------------------------------------------
def _xposed_fetch(email):
    """(status, data) from XposedOrNot. Never raises; 0 on transport."""
    try:
        import requests
    except Exception:
        return 0, None
    url = XPOSED_ANALYTICS % urllib.parse.quote(_email_only(email))
    try:
        trace("INFO", "xposed", "GET %s" % url, email)
        r = requests.get(url, timeout=XPOSED_TIMEOUT,
                         headers={"User-Agent": UA, "Accept": "application/json"})
    except Exception as exc:
        trace("ERR", "xposed", "%s: %s" % (type(exc).__name__, str(exc)[:160]), email)
        return 0, None
    trace("INFO", "xposed", "http %d, %d byte(s)"
          % (r.status_code, len(r.content or b"")), email)
    if r.status_code != 200:
        return r.status_code, None
    try:
        return 200, r.json()
    except Exception:
        return 200, None


def _xposed_rows(data):
    """The breach list of an XposedOrNot answer, HIBP-shaped and catalogue-filled.

    -> a list (possibly empty) when the answer was readable, else None. A row is
    filled from the catalogue by NAME wherever the catalogue knows the breach, so
    the date, record count and data classes are HIBP's own and not a bare year.
    """
    if not isinstance(data, dict):
        return None
    blk = data.get("ExposedBreaches")
    det = blk.get("breaches_details") if isinstance(blk, dict) else None
    if not isinstance(det, list):
        summ = data.get("BreachesSummary")
        site = summ.get("site") if isinstance(summ, dict) else ""
        names = [s.strip() for s in str(site or "").split(";") if s.strip()]
        if not names:
            return None
        det = [{"breach": n} for n in names]
    rows = []
    for d in det[:XPOSED_ROWS_MAX]:
        if not isinstance(d, dict):
            continue
        name = str(d.get("breach") or "").strip()
        if not name:
            continue
        cat = _cat_row_by_name(name) or {}
        date = str(cat.get("BreachDate") or "")[:10]
        if not date:
            year = str(d.get("xposed_date") or "").strip()[:4]
            if year.isdigit():
                date = "%s-01-01" % year
        classes = [c.strip() for c in str(d.get("xposed_data") or "").split(";")
                   if c.strip()]
        if not classes:
            classes = [str(c) for c in (cat.get("DataClasses") or [])]
        rows.append({
            "Name": name,
            "Title": str(cat.get("Title") or name)[:160],
            "Domain": str(cat.get("Domain") or d.get("domain") or ""),
            "BreachDate": date,
            "AddedDate": str(cat.get("AddedDate") or d.get("added") or "")[:24],
            "PwnCount": int(cat.get("PwnCount") or d.get("xposed_records") or 0),
            "Description": str(cat.get("Description") or d.get("details") or ""),
            "DataClasses": classes[:12],
            "IsVerified": str(d.get("verified") or "").strip().lower() == "yes",
            "IsSensitive": False,
            "IsStealerLog": "stealer" in name.lower(),
            "IsSpamList": _corpus_key(name) in _CORPUS_KEYS,
        })
    return rows


def _xposed_lookup(email):
    """('hit'|'miss'|'fail', payload, note) for one address. Never raises.

    'hit'  a readable answer that lists breaches - payload is HIBP-shaped
    'miss' a readable answer that lists none - a zero from a source that answered
    'fail' nothing readable - the caller falls through to the catalogue
    """
    try:
        status, data = _xposed_fetch(email)
    except Exception as exc:
        return "fail", None, "%s: %s" % (type(exc).__name__, str(exc)[:120])
    if status == 404:
        return "miss", None, "xposedornot: not indexed"
    if status != 200:
        return "fail", None, "xposedornot: %s" % (status or "transport")
    if not isinstance(data, dict):
        return "fail", None, "xposedornot: body was not JSON"
    if str(data.get("Error") or "").strip():
        return "miss", None, "xposedornot: %s" % str(data["Error"])[:60]
    rows = _xposed_rows(data)
    if rows is None:
        return "fail", None, "xposedornot: no breach list in the answer"
    if not rows:
        return "miss", None, "xposedornot: lists no breach"
    return "hit", {"Breaches": rows}, "xposedornot: %d breach(es)" % len(rows)


# ---------------------------------------------------------------------------
# the test flight - the Colab's second cell, in the app, for the breach only
# ---------------------------------------------------------------------------
def _flight_path() -> str:
    p = _user_file(FLIGHT_NAME)
    try:
        os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
    except Exception:
        pass
    return p


def _flight_pool_path() -> str:
    return _user_file(FLIGHT_POOL)


def _secret_text(name) -> str:
    try:
        got = os.environ.get(name)
        if got:
            return str(got)
    except Exception:
        pass
    try:
        import streamlit as st
        got = st.secrets.get(name)
        if got:
            return str(got)
    except Exception:
        pass
    return ""


def _webshare_keys():
    raw = _secret_text("WEBSHARE_KEYS") or _secret_text("WEBSHARE_API_KEYS")
    return [l.strip() for l in str(raw or "").splitlines() if l.strip()]


def _oxylabs_lines():
    raw = (_secret_text("OXYLABS_BASE") or _secret_text("OXYLABS_PROXIES"))
    return [l.strip() for l in str(raw or "").splitlines() if l.strip()]


def _say(log, msg):
    try:
        if log is not None:
            log.append(str(msg))
    except Exception:
        pass
    try:
        trace("INFO", "flight", str(msg))
    except Exception:
        pass


def _bump(codes, key, lock):
    try:
        with lock:
            codes[key] = codes.get(key, 0) + 1
    except Exception:
        pass


def _bucket(status, reason="") -> str:
    """One outcome label for the diagnostic summary. Never raises."""
    try:
        r = str(reason or "")
        if r.startswith("no egress"):
            return "no_egress"
        if status == 200:
            return "200"
        if status in (401, 403, 404, 429):
            return str(status)
        if 500 <= int(status or 0) < 600:
            return "5xx"
        if not status:
            return "0"
    except Exception:
        return "other"
    return "other"


def _gateway_dead(note) -> bool:
    """A gateway that failed AUTH fails auth in a browser too - skip it at step 1.

    `Tunnel connection failed: 407 Unauthorized` means the credential was refused
    before a tunnel existed, so pushing it into Chromium only buys two 35 s
    timeouts. Any other ipify failure still earns the browser.
    """
    n = str(note or "")
    return ("407" in n) or ("Unauthorized" in n) or ("unauthorized" in n)


def _webshare_fetch(keys, log=None):
    try:
        import requests
    except Exception:
        return []
    out = []
    for idx, key in enumerate(keys, 1):
        mine = 0
        page = 1
        while page <= WS_PAGES:
            try:
                r = requests.get(
                    "https://proxy.webshare.io/api/v2/proxy/list/?mode=direct"
                    "&page=%d&page_size=%d" % (page, WS_PAGE_SIZE),
                    headers={"Authorization": "Token %s" % key}, timeout=20)
            except Exception as exc:
                _say(log, "[!] Webshare key #%d failed: %s"
                     % (idx, type(exc).__name__))
                break
            if r.status_code == 401:
                _say(log, "[!] Webshare API key #%d invalid" % idx)
                break
            if r.status_code != 200:
                _say(log, "[!] Webshare API error %d on key #%d"
                     % (r.status_code, idx))
                break
            try:
                data = r.json()
            except Exception:
                break
            items = data.get("results") or []
            if not items:
                break
            for it in items:
                try:
                    out.append("%s:%s@%s:%s" % (it["username"], it["password"],
                                                it["proxy_address"], it["port"]))
                    mine += 1
                except Exception:
                    continue
            if not data.get("next"):
                break
            page += 1
        _say(log, "[*] Webshare [Key #%d] fetched : %d" % (idx, mine))
    return out


def _hostport(line) -> str:
    info = parse_proxy_line(line)
    return "%s:%d" % (info["host"], info["port"]) if info else ""


def _candidates(log=None):
    """The owner's own probed pool first, the APIs only when it is empty.

    proxies.txt is what the main page already probed, and proxy_meta.json says
    why each node failed - tier 3 is dead / auth / auth_dest / timeout /
    transport / tcp, and those are skipped rather than re-litigated. The flight
    is not the place to rediscover a node the probe already buried.

    Dedupe is by FULL LINE: `u:p@1.2.3.4:8080` and `v:q@1.2.3.4:8080` are two
    candidates, because the gateway judges the CREDENTIAL, so a dead sub-user must
    not hide a live one behind the same IP. Only an exact duplicate line is
    skipped, and FLIGHT_MAX sits above the 140 lines a full import produces.
    """
    tiers = _meta_tiers()
    own, buried = [], 0
    for line in _read_lines(_user_file("proxies.txt")):
        line = str(line or "").strip()
        if not line or not parse_proxy_line(line):
            continue
        if tiers.get(line) == 3:
            buried += 1
            continue
        own.append(line)
    if own:
        _say(log, "[*] From proxies.txt        : %d" % len(own))
        if buried:
            _say(log, "[*] Skipped as dead/auth    : %d (per proxy_meta.json)" % buried)
        raw = own
    else:
        _say(log, "[!] proxies.txt holds nothing usable - trying your imports")
        raw = []
        for name in ("proxies_secret.txt", "proxies_custom.txt"):
            extra = _read_lines(_user_file(name))
            if extra:
                _say(log, "[*] From %s : %d" % (name, len(extra)))
                raw.extend(extra)
        if not raw:
            oxy = _oxylabs_lines()
            if oxy:
                _say(log, "[*] Oxylabs line(s)       : %d" % len(oxy))
                raw.extend(oxy)
            keys = _webshare_keys()
            if keys:
                raw.extend(_webshare_fetch(keys, log))
            else:
                _say(log, "[!] No WEBSHARE_KEYS in secrets or env")
    seen, out = set(), []
    for line in raw:
        line = str(line or "").strip()
        if not line or line in seen or not parse_proxy_line(line):
            continue
        seen.add(line)
        out.append(line)
    _say(log, "[*] Unique credential lines: %d" % len(out))
    return out[:FLIGHT_MAX]


def _proxy_url(line):
    info = parse_proxy_line(line)
    if not info:
        return ""
    auth = ""
    if info.get("user"):
        auth = "%s:%s@" % (urllib.parse.quote(info["user"], safe=""),
                           urllib.parse.quote(info.get("pass") or "", safe=""))
    return "http://%s%s:%d" % (auth, info["host"], info["port"])


def _body_of(resp) -> str:
    """Response body text from EITHER response shape, or "".

    `requests` exposes .text as a PROPERTY. A Playwright Response exposes text()
    as a METHOD. Reading the Playwright one as a property yields the bound method,
    not the body, so every egress read came back "-" - and the caller then dropped
    the node before the target was ever requested. Callable first, value second.
    """
    try:
        got = getattr(resp, "text", "")
        txt = got() if callable(got) else got
        return str(txt or "")
    except Exception:
        return ""


def _ip_of(resp):
    try:
        return str((_json_of(_body_of(resp)) or {}).get("ip") or "-")
    except Exception:
        return "-"


def _ctx_kw(proxy_line=None, profile=None) -> dict:
    """Context kwargs for a profile, plus the proxy when there is one.

    VANILLA is the Colab context and nothing more: UA, locale, viewport. DRESSED
    adds the header set and the desktop emulation. `_ACTIVE_PROFILE` decides which
    one flies; the other stays reachable through the argument.
    """
    profile = profile or _ACTIVE_PROFILE
    kw = {"user_agent": UA, "locale": "en-US",
          "viewport": {"width": 1440, "height": 900}}
    if profile == PROFILE_DRESSED:
        kw["timezone_id"] = "America/New_York"
        kw["screen"] = {"width": 1920, "height": 1080}
        kw["device_scale_factor"] = 1
        kw["is_mobile"] = False
        kw["has_touch"] = False
        kw["color_scheme"] = "light"
        kw["extra_http_headers"] = dict(CTX_HEADERS)
    cfg = _proxy_cfg(proxy_line) if proxy_line else None
    if cfg:
        kw["proxy"] = cfg
    return kw


def _new_context(b, proxy_line=None):
    """A context in the active profile. STEALTH_JS only in the dressed one."""
    ctx = b.new_context(**_ctx_kw(proxy_line))
    if _ACTIVE_PROFILE == PROFILE_DRESSED:
        try:
            ctx.add_init_script(STEALTH_JS)
        except Exception:
            pass
    return ctx


def _proxy_ok(line, diag=False, log=None):
    """Does this node carry a request at all? -> (ok, note).

    `note` is the real reason on failure - the HTTP status or the exception text,
    never a generic "dead". It is kept to 220 characters, whitespace collapsed, so
    a ProxyError keeps its reason (407, tunnel failed, port or credential) on one
    line instead of being cut at the word that mattered.
    """
    url = _proxy_url(line)
    if not url:
        return False, "no usable proxy url"
    try:
        import requests
        r = requests.get(IPIFY_URL, proxies={"http": url, "https": url},
                         timeout=IPIFY_TIMEOUT)
        if diag:
            _say(log, "      <- ipify %d | egress %s" % (r.status_code, _ip_of(r)))
        if r.status_code == 200:
            return True, "ok"
        return False, "ipify http %d" % r.status_code
    except Exception as exc:
        note = _snippet("%s: %s" % (type(exc).__name__, exc), 220)
        if diag:
            _say(log, "      <- ipify fail | %s" % note)
        return False, note


def _flight_geo(line):
    url = _proxy_url(line)
    if not url:
        return "-", "-"
    try:
        import requests
        r = requests.get(FLIGHT_GEO_URL, proxies={"http": url, "https": url},
                         timeout=FLIGHT_GEO_TIMEOUT)
        data = r.json()
        return (str(data.get("country") or "-"), str(data.get("city") or "-"))
    except Exception:
        return "-", "-"


def _inpage_fetch(page, addr):
    try:
        if HIBP_BASE not in str(page.url or ""):
            page.goto(HIBP_BASE + "/", wait_until="domcontentloaded",
                      timeout=NAV_TIMEOUT)
        got = page.evaluate(FETCH_JS, unified_url(addr))
    except Exception as exc:
        trace("ERR", "fetch", "in-page fetch raised %s: %s"
              % (type(exc).__name__, str(exc)[:120]), addr)
        return 0, None
    if not isinstance(got, dict):
        return 0, None
    try:
        status = int(got.get("status") or 0)
    except Exception:
        status = 0
    payload = _json_of(got.get("body")) if status == 200 else None
    trace("INFO", "fetch", "in-page %s (%d byte(s))"
          % (status or "?", len(str(got.get("body") or ""))), addr)
    return status, payload


def _flight_one(line, diag=False, log=None):
    """One node, one context, ONE navigation - the Colab Cell 2 call.

    -> dict(ok, carried, reason, bucket, ip, status, ctype, size, headers, snippet).
    `ok` is a 200 that parsed as JSON. `carried` is "the target ANSWERED this node
    at all", which includes the 401/403 the WAF hands the caller and the 404 that
    is the site's own zero - those are alive nodes and they are kept.

    The target page is the FIRST page in the context and its only navigation is
    the unified URL: the egress read lives in a second tab that is closed first,
    and that tab talks to ipify, not to the target.

    Nothing re-asks on a 401. The wall is a verdict, not a hiccup: five requests
    per node is what cooked eleven shared exit IPs, so a refused node is simply
    recorded and kept. The only in-page fetch left is the one for a 200 that is
    not JSON, because there a document exists and the answer may still be behind
    it.

    The egress IP is INFORMATIONAL: a failed read never drops the node.
    Credentials are never printed, only host:port and auth=yes/no.
    """
    ctx = None
    out = {"ok": False, "carried": False, "reason": "", "bucket": "other", "ip": "-",
           "status": 0, "ctype": "-", "size": 0, "headers": "-", "snippet": ""}
    short = line.rsplit("@", 1)[-1]
    try:
        b = _browser()
        ctx = _new_context(b, line)
        page = ctx.new_page()
        page.set_default_timeout(FLIGHT_TIMEOUT)
        if diag:
            _say(log, "    send -> %s | auth=%s | target %s"
                 % (short, "yes" if "@" in line else "no",
                    unified_url(FLIGHT_PROBE)))
        # Egress read in its OWN tab, so the target page stays a clean first
        # navigation. ipify is a different host and costs the target nothing.
        try:
            probe_tab = ctx.new_page()
            try:
                probe = probe_tab.goto(IPIFY_URL, wait_until="domcontentloaded",
                                       timeout=FLIGHT_TIMEOUT)
                if probe is not None and probe.status == 200:
                    out["ip"] = _ip_of(probe)
            finally:
                probe_tab.close()
        except Exception as exc:
            if diag:
                _say(log, "      <- egress probe raised %s: %s"
                     % (type(exc).__name__, _snippet(str(exc), 160)))
        if out["ip"] in ("", "-") and diag:
            _say(log, "      <- egress unread, target is tried anyway")
        try:
            resp = page.goto(unified_url(FLIGHT_PROBE),
                             wait_until="domcontentloaded",
                             timeout=FLIGHT_TIMEOUT)
        except Exception as exc:
            out["reason"] = "%s: %s" % (type(exc).__name__, _snippet(str(exc), 160))
            if out["ip"] in ("", "-"):
                out["reason"] = "no egress ip and no status - " + out["reason"]
            out["bucket"] = _bucket(0, out["reason"])
            if diag:
                _say(log, "      <- transport raised %s | egress %s"
                     % (out["reason"], out["ip"]))
            return out
        out["status"] = resp.status if resp is not None else 0
        out["carried"] = out["status"] in CARRY_STATUS
        body = _body_of(resp)
        out["size"] = len(body or "")
        out["ctype"] = str((resp.headers or {}).get("content-type")
                           if resp is not None else "-")[:60] or "-"
        out["headers"] = _safe_headers(resp)
        out["snippet"] = _snippet(body)
        if diag:
            _say(log, "      <- %s | content-type: %s | %d byte(s) | %s | egress %s"
                 % (out["status"] or "?", out["ctype"], out["size"],
                    out["headers"], out["ip"]))
            if out["snippet"]:
                _say(log, "        body: %s" % out["snippet"])
        if out["status"] == 200:
            # Colab's own test: the body starts with { or [ and json.loads.
            if _json_any(body) is not None:
                out["ok"] = True
                out["reason"] = "200"
                out["bucket"] = "200"
                return out
            page.wait_for_timeout(500)
            got, payload = _inpage_fetch(page, FLIGHT_PROBE)
            if isinstance(payload, dict):
                out["ok"] = True
                out["reason"] = "200"
                out["bucket"] = "200"
                return out
            out["reason"] = "in-page %s" % (got or "200 non-JSON body")
            out["bucket"] = _bucket(got, out["reason"])
            if diag:
                _say(log, "      <- in-page %s after a non-JSON 200" % (got or "?"))
            return out
        if not out["status"] and out["ip"] in ("", "-"):
            out["reason"] = "no egress ip and no status - proxy not carried"
        else:
            out["reason"] = "status %s" % (out["status"] or "?")
        out["bucket"] = _bucket(out["status"], out["reason"])
        return out
    except Exception as exc:
        out["reason"] = "%s: %s" % (type(exc).__name__, _snippet(str(exc), 160))
        out["bucket"] = _bucket(0, out["reason"])
        if diag:
            _say(log, "      <- raised %s" % out["reason"])
        return out
    finally:
        try:
            if ctx is not None:
                ctx.close()
        except Exception:
            pass


def _flight_ipify(cand, cancel=None, log=None, pin="", diag=False, codes=None,
                  lock=None):
    out, own = [], threading.Lock()
    lock = lock or own

    def one(line):
        set_owner(pin)
        if _is_cancelled(cancel):
            return
        short = line.rsplit("@", 1)[-1]
        if diag:
            _say(log, "    probe -> %s | auth=%s"
                 % (short, "yes" if "@" in line else "no"))
        ok, note = _proxy_ok(line, diag, log)
        if ok:
            with own:
                out.append(line)
            return
        if codes is not None:
            _bump(codes, "ipify_fail", lock)
        # An Oxylabs rotating gateway can answer ipify badly and still be fine in
        # a real browser, which is how Colab Cell 2 used it - unless the failure
        # is auth, which a browser cannot fix. That one is skipped like any dead
        # node instead of burning two 35 s timeouts.
        gateway = "oxylabs.io" in line and not _gateway_dead(note)
        _say(log, "    %s -> %s | ipify_fail (%s)%s"
             % ("keep" if gateway else "skip", short, note,
                " - pushed to step 2 anyway" if gateway else ""))
        if gateway:
            with own:
                out.append(line)

    width = max(1, min(IPIFY_WORKERS, len(cand) or 1))
    with _cf.ThreadPoolExecutor(max_workers=width) as ex:
        list(ex.map(one, cand))
    return out


def _flight_browser(alive, cancel=None, log=None, pin="", diag=False, codes=None,
                    lock=None):
    """-> (carried lines, number of them that READ with 200 + JSON).

    A node is kept when the target ANSWERED it (CARRY_STATUS). The early stop is
    on the READ count, not the kept count: on a walled day every node is 401, so
    stopping at FLIGHT_WANT kept nodes would stop after twelve and leave a pool of
    twelve - which is exactly what a walled day needs most of.
    """
    kept, reads = [], [0]
    own = threading.Lock()
    lock = lock or own
    deadline = time.time() + FLIGHT_BUDGET
    width = max(1, min(FLIGHT_WORKERS, len(alive) or 1))
    lanes = [alive[i::width] for i in range(width)]

    def one(line):
        short = line.rsplit("@", 1)[-1]
        if _is_cancelled(cancel) or time.time() > deadline:
            return
        with own:
            if not diag and reads[0] >= FLIGHT_READ_WANT:
                return
        # Stagger the lanes: two workers landing on the same shared exit IP in
        # the same instant is the burst that got these IPs refused.
        try:
            time.sleep(random.uniform(0.0, FLIGHT_JITTER))
        except Exception:
            pass
        res = _flight_one(line, diag, log)
        if codes is not None:
            _bump(codes, res.get("bucket") or "other", lock)
        if not res.get("carried"):
            _say(log, "    skip  -> %-22s | test flight failed (%s) | egress %s"
                 % (short, res.get("reason") or "?", res.get("ip")))
            return
        country, city = _flight_geo(line)
        tag = " [OXYLABS CURRENT]" if "oxylabs.io" in line else ""
        with own:
            kept.append(line)
            if res.get("ok"):
                reads[0] += 1
        if res.get("ok"):
            _say(log, "    ✅ 200 -> %-22s | %-16s | %s%s | egress %s"
                 % (short, country, city, tag, res.get("ip")))
        else:
            _say(log, "    keep  -> %-22s | carried (%s) | %-16s | %s%s | egress %s"
                 % (short, res.get("status") or "?", country, city, tag,
                    res.get("ip")))

    def lane(chunk):
        """One lane owns one browser for its whole chunk, and closes it itself.

        A teardown task submitted after the map finishes lands on whichever
        thread is free, not the thread that owns the browser, so a browser per
        worker was left running until the process died.
        """
        set_owner(pin)
        try:
            for line in chunk:
                one(line)
        finally:
            _close_thread_browser()

    with _cf.ThreadPoolExecutor(max_workers=width) as ex:
        list(ex.map(lane, lanes))
    return kept, reads[0]


def _flight_load() -> dict:
    p = _flight_path()
    if not p or not os.path.exists(p):
        return {}
    try:
        with open(p, encoding="utf-8", errors="ignore") as fh:
            got = json.load(fh)
    except Exception:
        return {}
    return got if isinstance(got, dict) else {}


def _flight_save(st) -> None:
    p = _flight_path()
    if not p:
        return
    tmp = p + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(st, fh, ensure_ascii=False)
        os.replace(tmp, p)
    except Exception:
        pass


def _flight_fresh() -> bool:
    p = _flight_pool_path()
    try:
        if not p or not os.path.exists(p):
            return False
        if (time.time() - os.path.getmtime(p)) > POOL_TTL:
            return False
    except Exception:
        return False
    return bool(_read_lines(p))


def _summary_lines(log, codes, kept, diag, candidates, alive, reads=0):
    """The closing block: counts per outcome, then the legend for each code."""
    _say(log, "")
    _say(log, "=" * 62)
    _say(log, "[*] Passed test flight (✅ 200) : %d" % reads)
    _say(log, "[*] Carried - alive, KEPT      : %d" % len(kept))
    _say(log, "[*] File                         : %s" % FLIGHT_POOL)
    _say(log, "=" * 62)
    if diag:
        _say(log, "")
        _say(log, "[*] Summary by outcome (candidates %d, alive %d)"
             % (candidates, alive))
        total = 0
        for key, _meaning in OUTCOMES:
            n = int((codes or {}).get(key) or 0)
            if not n:
                continue
            total += n
            _say(log, "      %-11s : %d" % (key, n))
        if not total:
            _say(log, "      (nothing recorded)")
        _say(log, "[*] What each code means here")
        for key, meaning in OUTCOMES:
            _say(log, "      %-11s %s" % (key, meaning))
        if kept:
            _say(log, "[*] Kept: %s" % ", ".join(k.rsplit("@", 1)[-1] for k in kept))


def flight(force=False, cancel=None, diagnose=False) -> dict:
    started = time.time()
    pin = owner()
    who = _owner_key()
    diag = bool(diagnose)
    with _lock:
        cur_f = _flights.get(who) or {"busy": False, "last": {}}
        if cur_f["busy"] and not force:
            return dict(cur_f["last"])
        cur_f["busy"] = True
        _flights[who] = cur_f
    st = {"ran": True, "ts": time.time(), "candidates": 0, "alive": 0, "kept": 0,
          "reads": 0, "error": "", "seconds": 0.0, "diagnose": diag, "codes": {},
          "log": []}
    log = st["log"]
    codes, clock = {}, threading.Lock()
    try:
        _say(log, "=" * 62)
        _say(log, "   AUTO LIVE PROXIES + PLAYWRIGHT TEST FLIGHT%s"
             % ("  [DIAGNOSTIC]" if diag else ""))
        _say(log, "   Test email: %s" % FLIGHT_PROBE)
        _say(log, "   One navigation per node, %d at a time, staggered. A node the "
                  "target ANSWERS is kept." % FLIGHT_WORKERS)
        _say(log, "=" * 62)
        if not available():
            st["error"] = "browser not ready - %s" % browser_note()
            _say(log, "[!] " + st["error"])
            ensure_browser()
            return st
        cand = _candidates(log)
        st["candidates"] = len(cand)
        _say(log, "[*] Total candidates       : %d" % len(cand))
        if not cand:
            st["error"] = ("no candidate proxies - import a proxies.txt on the "
                           "checker page, or add WEBSHARE_KEYS to secrets")
            _say(log, "[!] " + st["error"])
            return st
        _say(log, "[*] Step 1: Checking basic ipify connectivity...")
        _say(log, "")
        alive = _flight_ipify(cand, cancel, log, pin, diag, codes, clock)
        st["alive"] = len(alive)
        _say(log, "")
        _say(log, "[*] Step 2: Running Chromium test flight on %d proxies..."
             % len(alive))
        _say(log, "")
        if not alive:
            st["error"] = "no candidate carried a request (all dead on ipify)"
            _say(log, "[!] " + st["error"])
            _summary_lines(log, codes, [], diag, len(cand), 0, 0)
            return st
        kept, reads = _flight_browser(alive, cancel, log, pin, diag, codes, clock)
        st["kept"] = len(kept)
        st["reads"] = reads
        if kept:
            _write_lines(_flight_pool_path(), kept)
            _invalidate_pool_cache(who)
            if not reads:
                _say(log, "[*] No node could READ the endpoint - every carried node "
                          "is behind the wall. They are kept anyway: the tunnel, the "
                          "TLS and the edge all worked, and a walled address is read "
                          "from the second source instead.")
        else:
            st["error"] = "no candidate carried the request (all dead in transport)"
            _say(log, "[!] " + st["error"])
            _say(log, "[*] Nothing was kept, so %s was left as it was - the reader "
                      "keeps using proxies.txt." % FLIGHT_POOL)
        _summary_lines(log, codes, kept, diag, len(cand), len(alive), reads)
        return st
    except Exception as exc:
        st["error"] = "%s: %s" % (type(exc).__name__, exc)
        _say(log, "[!] %s" % st["error"])
        return st
    finally:
        st["seconds"] = round(time.time() - started, 1)
        st["codes"] = dict(codes)
        if len(st["log"]) > FLIGHT_LOG_MAX:
            del st["log"][:len(st["log"]) - FLIGHT_LOG_MAX]
        with _lock:
            _flights[who] = {"busy": False, "last": dict(st)}
        _flight_save(st)


def flight_state() -> dict:
    who = _owner_key()
    with _lock:
        cur_f = _flights.get(who) or {}
        st = dict(cur_f.get("last") or {})
        busy = bool(cur_f.get("busy"))
    if not st:
        st = _flight_load()
    st["busy"] = busy
    st["pool"] = len(_read_lines(_flight_pool_path()))
    if not isinstance(st.get("log"), list):
        st["log"] = []
    if not isinstance(st.get("codes"), dict):
        st["codes"] = {}
    try:
        st["reads"] = int(st.get("reads") or 0)
    except Exception:
        st["reads"] = 0
    try:
        st["age"] = int(time.time() - float(st.get("ts") or 0)) if st.get("ts") else -1
    except Exception:
        st["age"] = -1
    return st


def flight_log_text(limit=400) -> str:
    try:
        rows = list(flight_state().get("log") or [])
    except Exception:
        rows = []
    if not rows:
        return "(no test flight yet)"
    try:
        n = max(1, int(limit or 400))
    except Exception:
        n = 400
    return "\n".join(rows[-n:])


def flight_clear() -> None:
    who = _owner_key()
    try:
        p = _flight_pool_path()
        if p and os.path.exists(p):
            os.remove(p)
    except Exception:
        pass
    _invalidate_pool_cache(who)
    with _lock:
        _flights[who] = {"busy": False, "last": {}}
    _flight_save({})
    trace("CLICK", "flight", "pool cleared by the page")


# ---------------------------------------------------------------------------
# the app's proxy pool
# ---------------------------------------------------------------------------
def parse_proxy_line(line):
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
    with _lock:
        given = _cfg.get("pool")
    if given:
        return list(dict.fromkeys(given))
    who = _owner_key()
    now = time.time()
    with _lock:
        cached = _pool_caches.get(who)
        if (not force and cached and cached.get("lines")
                and (now - float(cached.get("ts") or 0)) < _pool_ttl):
            return list(cached["lines"])
    path = _flight_pool_path() if _flight_fresh() else _user_file("proxies.txt")
    raw = [l for l in dict.fromkeys(_read_lines(path)) if parse_proxy_line(l)]
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
        _pool_caches[who] = {"ts": now, "lines": list(out)}
    return out


def _mark_bad(line):
    if not line:
        return
    who = _owner_key()
    with _lock:
        user_bad = _bads.setdefault(who, {})
        user_bad[line] = min(9, user_bad.get(line, 0) + 1)


def _pick_proxy(used):
    pool = pool_lines()
    if not pool:
        return None
    who = _owner_key()
    with _lock:
        user_bad = _bads.get(who) or {}
        live = [l for l in pool if user_bad.get(l, 0) < BAD_AFTER] or pool
        if not _cfg_get("rotate", True):
            n = len(live)
            cur = _cursors.setdefault(who, [0])
            for _ in range(n):
                line = live[cur[0] % n]
                cur[0] += 1
                if line not in used:
                    return line
            return None
    left = [l for l in live if l not in used]
    if not left:
        return None
    return random.choice(left)


def pool_status() -> dict:
    lines = pool_lines()
    return {"count": len(lines), "sample": lines[:3], "flight": _flight_fresh()}


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
# the address half - one reused page per worker, headless Chromium, the pool
# ---------------------------------------------------------------------------
def _browser():
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
    # Plain launch, no channel: Colab calls chromium.launch(headless=True) with no
    # channel, so the headless shell is the build that produced the 200s.
    b = pw.chromium.launch(headless=True, args=CONTAINER_ARGS)
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
    __slots__ = ("ctx", "page", "proxy", "uses", "fails")

    def __init__(self):
        self.ctx = None
        self.page = None
        self.proxy = ""
        self.uses = 0
        self.fails = 0

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

    def open_ctx(self, proxy_line):
        self.close_ctx()
        b = _browser()
        ctx = _new_context(b, proxy_line)
        ctx.set_default_timeout(NAV_TIMEOUT)
        self.ctx = ctx
        self.page = ctx.new_page()
        self.proxy = proxy_line or ""

    def reset(self):
        if self.page is not None and not self.page.is_closed():
            self.page.goto("about:blank", wait_until="commit", timeout=8000)
        try:
            if self.ctx is not None:
                self.ctx.clear_cookies()
        except Exception:
            pass

    def get(self, proxy_line):
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
        self.uses += 1
        self.fails += 1
        if self.fails >= SLOT_FAILS_MAX:
            self.close_ctx()


def _slot():
    s = getattr(_tls, "slot", None)
    if s is None:
        s = _Slot()
        _tls.slot = s
        who = _owner_key()
        with _lock:
            _slots.setdefault(who, {})[threading.get_ident()] = s
    return s


def _close_all_slots():
    who = _owner_key()
    with _lock:
        user_slots = _slots.pop(who, {})
        got = list(user_slots.values())
    for s in got:
        s.close_ctx()


def _attempt(addr, proxy_line):
    label = (proxy_line.rsplit("@", 1)[-1] if proxy_line else "DIRECT")
    url = unified_url(addr)
    slot = _slot()
    try:
        page = slot.get(proxy_line)
    except Exception as exc:
        trace("ERR", "fetch", "no page via %s: %s" % (label, type(exc).__name__), addr)
        return 0, None
    try:
        # A small stagger so the workers do not land together on one exit IP.
        try:
            time.sleep(random.uniform(0.0, READ_JITTER))
        except Exception:
            pass
        resp = page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT)
        status = resp.status if resp is not None else 0
        body = ""
        try:
            body = resp.text() if resp is not None else ""
        except Exception:
            body = ""
        trace("INFO", "fetch", "%s via %s (%d byte(s))"
              % (status or "?", label, len(body)), addr)
        if status == 200:
            payload = _json_of(body)
            if isinstance(payload, dict):
                slot.ok()
                return 200, payload
            page.wait_for_timeout(700)
            got, payload = _inpage_fetch(page, addr)
            if isinstance(payload, dict):
                slot.ok()
                return 200, payload
            if got == 404:
                slot.ok()
                return 404, None
            slot.ok()
            return got or 200, None
        if status == 404:
            slot.ok()
            return 404, None
        # A 401 is a dead end for the browser: no in-page re-ask, just the next
        # node, and the caller has the second source for when they all refuse.
        slot.ok()
        return status, None
    except Exception as exc:
        trace("ERR", "fetch", "err via %s (%s)" % (label, type(exc).__name__), addr)
        slot.bad()
        return 0, None


def _search_address(addr, cancel=None):
    seen = []
    errors = []
    used = set()
    for _ in range(PROXY_TRIES):
        if _is_cancelled(cancel):
            return None, "", "cancelled", seen
        line = _pick_proxy(used)
        if line is None:
            break
        used.add(line)
        status, payload = _attempt(addr, line)
        label = line.rsplit("@", 1)[-1]
        seen.append(status)
        if payload is not None:
            return payload, label, "", seen
        if status == 404:
            return {}, "", "", seen
        errors.append("%s: %s" % (label, status or "err"))
        if status == 0:
            _mark_bad(line)

    if _is_cancelled(cancel):
        return None, "", "cancelled", seen
    if _zero_rule(seen):
        return {}, "", "", seen

    status, payload = _attempt(addr, None)
    seen.append(status)
    if payload is not None:
        return payload, "DIRECT", "", seen
    if status == 404:
        return {}, "", "", seen
    errors.append("DIRECT: %s" % (status or "err"))
    return None, "", "; ".join(errors[-4:]), seen


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
            "Title": _plain(b.get("Title") or b.get("Name") or "Unnamed")[:160],
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
            "title": _plain(b.get("Title") or b.get("Name") or "Unnamed")[:160],
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
        rec["pastes"].append({"Title": _plain(p.get("Title") or "Untitled")[:200],
                              "Source": str(p.get("Source") or "")[:120],
                              "Date": str(p.get("Date") or "")[:10],
                              "title": _plain(p.get("Title") or "Untitled")[:200],
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
    if rec.get("via") == "xposedornot":
        basis = "XposedOrNot index - the exact HIBP search was walled"
    elif rec.get("partial_read"):
        basis = "domain match - the exact search was walled"
    elif not rec.get("read"):
        basis = "nothing readable - proxy, in-page fetch and direct all failed"
    elif rec.get("count"):
        basis = "exact search"
    else:
        basis = "exact search - 404, the address is in no breach"
    lines = ["kind: %s" % kind,
             "entry: %s" % (("%s:%s" % (rec.get("email") or "-",
                                        rec.get("password") or ""))
                            if rec.get("password") else (rec.get("email") or "-")),
             "address: %s" % (rec.get("email") or "-"),
             "checked: %s" % (rec.get("checked_at") or ""),
             "verdict: %s - %s" % (rec.get("verdict") or "?", rec.get("reason") or ""),
             "address half: %s" % (rec.get("addr_verdict") or "UNREAD"),
             "password half: %s" % (rec.get("pw_band") or "none"),
             "password appearances: %s" % (_pw if _pw is not None
                                           else "no password supplied"),
             "source: %s" % (rec.get("via") or "-"),
             "basis: %s" % basis,
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
         _esc(_pw if _pw is not None else "-"), "\x3cbr\x3esource: ",
         _esc(rec.get("via") or "-"), "\x3cbr\x3ebasis: ", _esc(basis),
         "\x3cbr\x3echecked: ", _esc(rec.get("checked_at") or ""), "\x3c/p\x3e"]
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
                    if not rec.get("read") else
                    "No breach record - the source was read and lists none."))
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
    "UNKNOWN": "no readable answer - proxy, in-page fetch and direct all failed",
    "UNREAD": "address half was not read - a combo is not graded on its password",
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
    if item["password"]:
        return "combo:%s:%s" % (item["email"].lower(), _pw_hash(item["password"])[:12])
    return "email:%s" % item["email"].lower()


def _pw_halves(rec, item, force):
    if not item["password"]:
        rec["pw_count"] = None
        rec["password_check"] = None
        return
    rec["pw_count"] = pwned_count(item["password"], force=force)
    rec["password_check"] = check_password(item["password"], force=force)


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
        rec["pwned"] = bool(rec["pw_count"])
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

    payload, via, err, seen = _search_address(email, cancel)
    if payload:
        rec = _parse_payload(item, payload, via or "browser", started, item["password"])
        _pw_halves(rec, item, force)
        rec["read"] = True
        rec["via_proxy"] = via or "browser"
    elif payload is not None:
        rows = _cat_rows(email)
        if rows:
            rec = _parse_payload(item, {"Breaches": rows}, "catalogue", started,
                                 item["password"])
            _pw_halves(rec, item, force)
            rec["read"] = True
            rec["partial_read"] = True
            rec["via"] = "catalogue"
            rec["via_proxy"] = ""
            rec["error"] = "; ".join("%s: %s" % ("proxies", s or "err") for s in seen)
            trace("INFO", "catalogue", "%d domain match(es) - 404 zero filled"
                  % len(rows), email)
        else:
            rec["via"] = "browser"
            rec["via_proxy"] = ""
            rec["read"] = True
            rec["count"] = 0
            rec["error"] = ""
            trace("INFO", "address", "404 - reported as no breach (statuses %s)"
                  % seen, email)
    else:
        # The address half was walled. Two keyless sources sit OUTSIDE the wall and
        # neither is a browser: XposedOrNot answers the EXACT address, the HIBP
        # catalogue answers the DOMAIN. Exact first - a domain answer for a gmail
        # mailbox is noise - and the catalogue only when the exact one failed too.
        xp_state, xp_payload, xp_note = "fail", None, ""
        if not _is_cancelled(cancel):
            xp_state, xp_payload, xp_note = _xposed_lookup(email)
            trace("INFO", "xposed", "%s%s" % (xp_state,
                                              (" - " + xp_note) if xp_note else ""),
                  email)
        if xp_state == "hit":
            rec = _parse_payload(item, xp_payload, "xposedornot", started,
                                 item["password"])
            _pw_halves(rec, item, force)
            rec["read"] = True
            rec["partial_read"] = False
            rec["via"] = "xposedornot"
            rec["via_proxy"] = ""
            rec["error"] = ("the exact HIBP search was walled - read from "
                            "XposedOrNot instead" + ((" (%s)" % err) if err else ""))
        elif xp_state == "miss":
            rec = _parse_payload(item, {"Breaches": [], "Pastes": []},
                                 "xposedornot", started, item["password"])
            _pw_halves(rec, item, force)
            rec["read"] = True
            rec["partial_read"] = False
            rec["via"] = "xposedornot"
            rec["via_proxy"] = ""
            rec["error"] = ("the exact HIBP search was walled - XposedOrNot lists no "
                            "breach for the address" + ((" (%s)" % err) if err else ""))
        else:
            rows = _cat_rows(email)
            if rows:
                rec = _parse_payload(item, {"Breaches": rows}, "catalogue", started,
                                     item["password"])
                _pw_halves(rec, item, force)
                rec["read"] = True
                rec["partial_read"] = True
                rec["via"] = "catalogue"
                rec["via_proxy"] = ""
                rec["error"] = ("the exact search was walled and the second source "
                                "failed - filled from the catalogue by DOMAIN"
                                + ((" (%s)" % err) if err else ""))
                trace("INFO", "catalogue", "%d domain match(es) - walled address filled"
                      % len(rows), email)
            else:
                rec["via"] = "browser"
                rec["via_proxy"] = ""
                rec["read"] = False
                rec["error"] = ("cancelled" if _is_cancelled(cancel) else
                                "connection/proxy error - unreachable on proxy, in-page "
                                "fetch and direct, and the second source failed"
                                + ((" (%s)" % err) if err else ""))

    rec["breach_count"] = len(rec.get("breaches") or [])
    rec["summary_note"] = _summary_note(rec)

    ab = _addr_bucket(rec)
    rec["addr_verdict"] = ab or ("UNREAD" if not rec["read"] else "UNKNOWN")
    rec["pw_band"] = _pw_bucket(rec.get("pw_count")) or "none"
    if ab is None and item["kind"] == "combo":
        rec["bucket"] = "UNKNOWN"
        rec["reason"] = _REASON["UNREAD"]
    else:
        rec["bucket"] = _combine(_pw_bucket(rec.get("pw_count")), ab)
        rec["reason"] = _REASON.get(rec["bucket"], "")
    rec["verdict"] = rec["bucket"]
    rec["pwned"] = bool(rec["breach_count"] or (rec.get("pw_count") or 0))
    if rec["bucket"] == "UNKNOWN" and not rec["error"]:
        rec["error"] = "no readable answer"
    rec.update(_page_from_record(rec))
    trace("INFO", "band", "%s (%s) - addr %s, pw %s, %d ms"
          % (rec["bucket"], rec["reason"] or "-", rec["addr_verdict"],
             rec["pw_band"], rec.get("elapsed_ms") or 0), email)

    if rec["bucket"] != "UNKNOWN" and not rec["partial_read"]:
        cache.setdefault("item", {})[key] = {"ts": time.time(), "report": rec}
        if len(cache.get("item") or {}) > CACHE_MAX:
            cut = list(cache["item"])[:len(cache["item"]) - CACHE_MAX]
            for k in cut:
                cache["item"].pop(k, None)
        _save(cache)
    _remember(rec)
    return rec


def check(addr, password="", force=False, cancel=None) -> dict:
    return check_item(_as_item(addr, password), force=force, cancel=cancel)


def _remember(rec):
    who = _owner_key()
    with _lock:
        cur = _lasts.get(who) or {}
        cur.update({"ts": time.time(), "email": rec.get("email", ""),
                    "verdict": rec.get("verdict", ""), "via": rec.get("via", ""),
                    "ms": rec.get("elapsed_ms", 0), "error": rec.get("error", "")})
        _lasts[who] = cur


def last_url() -> str:
    who = _owner_key()
    with _lock:
        cur = _lasts.get(who) or {}
    if cur.get("email"):
        return unified_url(cur["email"])
    return ""


def check_many(items, workers=3, progress=None, cancel=None, force=False,
               delay=None, rotate=None, owner_prefix=None, flight_first=None) -> dict:
    pin = owner() if owner_prefix is None else str(owner_prefix)
    set_owner(pin)
    who = _owner_key()
    snap = _snapshot_cfg()
    if rotate is not None:
        snap["rotate"] = bool(rotate)
    _pin_cfg(snap)
    with _lock:
        _bads[who] = {}
        _cursors[who] = [0]

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
    if not total:
        return out

    fly = snap.get("flight", True) if flight_first is None else bool(flight_first)
    if fly and any(i["kind"] != "password" for i in uniq) and not _flight_fresh():
        trace("INFO", "flight", "auto: pool missing or older than %d s" % int(POOL_TTL))
        flight(cancel=cancel)
        _close_thread_browser()
        _invalidate_pool_cache(who)

    trace("INFO", "run", "start: %d item(s), workers=%d, pages<=%d, pace=%ss, pool=%d, "
          "rotate=%s" % (total, width, width, pace, len(pool_lines()),
                         "on" if snap.get("rotate") else "off"))
    if any(i["kind"] != "password" for i in uniq):
        catalogue()

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
    who = _owner_key()
    with _lock:
        mine = dict(_lasts.get(who) or {})
        bad = len(_bads.get(who) or {})
    return {"version": BREACH_VERSION, "browser": available(),
            "browser_state": browser_state().get("state", ""),
            "browser_error": browser_note(), "delay": _delay(),
            "pool": len(pool_lines()), "rotate": rotating(), "skipped": bad,
            "catalogue": catalogue_state(), "tries": PROXY_TRIES,
            "flight": flight_state(), "key": key_present(), "owner": owner(),
            "cache": cache_stats(), "last": mine, "trace_seq": trace_seq()}


# ---------------------------------------------------------------------------
# selftest
# ---------------------------------------------------------------------------
def selftest(verbose=False) -> bool:
    checks = []

    def add(n, ok):
        checks.append((n, bool(ok)))

    add("lock_reentrant", type(_lock).__name__ == "RLock")
    add("owner_key_nonempty", bool(_owner_key()))
    add("is_email", is_email("a.b@c.co"))
    add("not_email", not is_email("nope"))
    add("only_colon", _email_only("a@b.co:hunter2") == "a@b.co")
    add("url_no_password", unified_url("a@b.co:hunter2") ==
        HIBP_BASE + "/unifiedsearch/a%40b.co")
    add("flight_probe_url", unified_url(FLIGHT_PROBE) ==
        HIBP_BASE + "/unifiedsearch/eddiemurphy%40gmail.com")
    add("container_args", "--no-sandbox" in CONTAINER_ARGS)
    add("container_args_slim", len(CONTAINER_ARGS) == 2)
    add("hostport", _hostport("u:p@1.2.3.4:8080") == "1.2.3.4:8080")
    add("hostport_bad", _hostport("nope") == "")

    # ---- the diagnostic plumbing ----
    add("outcomes_have_200", "200" in [k for k, _m in OUTCOMES])
    add("outcomes_have_ipify_fail", "ipify_fail" in [k for k, _m in OUTCOMES])
    add("no_egress_is_informational", "no status" in dict(OUTCOMES)["no_egress"])
    add("legend_401_kept", "KEPT" in dict(OUTCOMES)["401"])
    add("legend_403_kept", "KEPT" in dict(OUTCOMES)["403"])
    add("legend_404_kept", "KEPT" in dict(OUTCOMES)["404"])
    add("bucket_200", _bucket(200) == "200")
    add("bucket_401", _bucket(401, "status 401") == "401")
    add("bucket_5xx", _bucket(503) == "5xx")
    add("bucket_zero", _bucket(0, "Timeout: x") == "0")
    add("bucket_no_egress", _bucket(0, "no egress ip - proxy not carried") == "no_egress")
    add("bucket_other", _bucket(302) == "other")
    add("snippet_cuts", len(_snippet("a b   c", 4)) == 4)
    add("snippet_collapses", _snippet("a\n\n b") == "a b")
    add("snippet_none", _snippet(None) == "")
    add("diag_headers_tuple", "cf-ray" in DIAG_HEADERS)
    add("bump_counts", (_c := {}, _bump(_c, "x", threading.Lock()), _c["x"] == 1)[2])

    # ---- the body/ip read: BOTH response shapes, and a raising one ----
    class _PwResp:          # requests shape - .text is a PROPERTY
        text = '{"ip": "9.9.9.9"}'

    class _PgResp:          # Playwright shape - .text() is a METHOD
        def text(self):
            return '{"ip": "8.8.8.8"}'

    class _Boom:            # reading .text raises
        @property
        def text(self):
            raise RuntimeError("boom")

    add("body_of_property", _body_of(_PwResp()) == '{"ip": "9.9.9.9"}')
    add("body_of_method", _body_of(_PgResp()) == '{"ip": "8.8.8.8"}')
    add("body_of_raises", _body_of(_Boom()) == "")
    add("body_of_none", _body_of(None) == "")
    add("ip_of_property", _ip_of(_PwResp()) == "9.9.9.9")
    add("ip_of_method", _ip_of(_PgResp()) == "8.8.8.8")
    add("ip_of_raises", _ip_of(_Boom()) == "-")
    add("ip_of_none", _ip_of(None) == "-")
    add("ip_of_non_json", _ip_of(type("R", (), {"text": "hello"})()) == "-")
    add("json_any_dict", _json_any('{"a": 1}') == {"a": 1})
    add("json_any_list", _json_any("[1, 2]") == [1, 2])
    add("json_any_junk", _json_any("hello") is None)
    add("json_of_list_is_none", _json_of("[1]") is None)

    # ---- the profiles: vanilla is active and Colab-exact, dressed stays valid ----
    add("active_profile_vanilla", _ACTIVE_PROFILE == PROFILE_VANILLA)
    add("ctx_vanilla_no_headers", "extra_http_headers" not in _ctx_kw(None))
    add("ctx_vanilla_no_tz", "timezone_id" not in _ctx_kw(None))
    add("ctx_vanilla_no_screen", "screen" not in _ctx_kw(None))
    add("ctx_vanilla_no_device", "is_mobile" not in _ctx_kw(None))
    add("ctx_vanilla_ua", _ctx_kw(None).get("user_agent") == UA)
    add("ctx_vanilla_locale", _ctx_kw(None).get("locale") == "en-US")
    add("ctx_vanilla_viewport", (_ctx_kw(None).get("viewport") or {}).get("width")
        == 1440)
    add("ctx_dressed_headers", "extra_http_headers" in _ctx_kw(None, PROFILE_DRESSED))
    add("ctx_dressed_tz", _ctx_kw(None, PROFILE_DRESSED).get("timezone_id")
        == "America/New_York")
    add("ctx_dressed_screen", (_ctx_kw(None, PROFILE_DRESSED).get("screen") or {})
        .get("width") == 1920)
    add("ctx_headers_referer", CTX_HEADERS.get("Referer") == HIBP_BASE + "/")
    add("ctx_headers_origin", CTX_HEADERS.get("Origin") == HIBP_BASE)
    add("ctx_kw_proxy", (_ctx_kw("u:p@1.2.3.4:8080").get("proxy") or {}).get("server")
        == "http://1.2.3.4:8080")
    add("ctx_kw_direct_no_proxy", "proxy" not in _ctx_kw(None))
    add("stealth_webdriver", "webdriver" in STEALTH_JS)
    add("stealth_platform", "'Win32'" in STEALTH_JS)
    add("stealth_no_angle", "\x3c" not in STEALTH_JS)
    add("new_context_callable", callable(_new_context))
    add("flight_one_callable", callable(_flight_one))
    add("gateway_dead_407", _gateway_dead("ProxyError: Tunnel connection failed: "
                                          "407 Unauthorized"))
    add("gateway_alive_503", not _gateway_dead("ipify http 503"))

    add("blank_read_false", _blank({"kind": "email", "email": "a@b.co"}).get("read") is False)
    add("blank_addr_unread", _blank({"kind": "email", "email": "a@b.co"}).get("addr_verdict")
        == "UNREAD")
    add("blank_not_pwned", _blank({"kind": "email", "email": "a@b.co"}).get("pwned") is False)
    add("blank_keeps_password", _blank({"kind": "combo", "email": "a@b.co"},
                                       "pw").get("password") == "pw")

    items = parse_lines("a@b.co:pw\nc@d.co\nhunter2\njunk line\n")
    add("parse_combo", items[0]["kind"] == "combo" and items[0]["password"] == "pw")
    add("parse_email", items[1]["kind"] == "email" and items[1]["password"] == "")
    add("parse_password", items[2]["kind"] == "password")
    add("parse_pairs", len(parse_addresses("a@b.co:pw\nc@d.co\n")) == 2)
    add("parse_skips_junk", all(i["kind"] for i in items))
    add("parse_dedupes", len(parse_lines("a@b.co:pw\na@b.co:pw\n")) == 1)
    add("parse_keeps_two_pws", len(parse_lines("a@b.co:one\na@b.co:two\n")) == 2)

    add("tries_is_three", PROXY_TRIES == 3)
    add("no_zero_on_401", not _zero_rule([401, 0, 0]))
    add("zero_on_404", _zero_rule([404]))
    add("no_zero_on_late_401", not _zero_rule([0, 403, 401]))
    add("no_zero_on_403", not _zero_rule([403, 0, 0]))
    add("no_zero_on_empty", not _zero_rule([]))
    add("retry_status_has_401", 401 in RETRY_STATUS)

    add("pw_hash", len(_pw_hash("abc")) == 40)
    add("pw_new", _pw_bucket(0) == "NEW")
    add("pw_old", _pw_bucket(50000) == "OLD")
    add("combine_worst", _combine("NEW", "OLD") == "OLD")
    add("combine_clean_pw_partial", _combine("PARTIAL", "CLEAN") == "PARTIAL")
    add("unread_not_clean", _addr_bucket({"error": "x", "count": None}) is None)
    add("clean_bucket", _addr_bucket({"count": 0}) == "CLEAN")
    add("stealer_is_new", _addr_bucket({"count": 1, "stealer": 1,
                                        "newest_days": 10}) == "NEW")
    add("old_breach_old", _addr_bucket({"count": 1, "newest_days": 3000}) == "OLD")
    add("reason_unread", "not graded on its password" in _REASON["UNREAD"])

    _k1 = _cache_key({"kind": "combo", "email": "a@b.co", "password": "one"})
    _k2 = _cache_key({"kind": "combo", "email": "a@b.co", "password": "two"})
    add("cache_key_by_password", _k1 != _k2)
    add("cache_key_email", _cache_key({"kind": "email", "email": "a@b.co",
                                       "password": ""}) == "email:a@b.co")

    pwn = {"Breaches": [
        {"Name": "June2026StealerLogs", "Title": "June 2026 Stealer Logs",
         "Domain": "", "BreachDate": "2026-06-15", "DataClasses": ["Passwords"],
         "IsStealerLog": True, "PwnCount": 1000},
        {"Name": "Wattpad", "Title": "\x3cb\x3eWattpad\x3c/b\x3e",
         "Domain": "wattpad.com", "BreachDate": "2020-06-29",
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
    add("title_stripped", rec["breaches"][1]["Title"] == "Wattpad")
    add("paste_title_stripped", rec["pastes"][0]["Title"] == "p")
    add("password_breaches", "Wattpad" in rec["password_breaches"])
    add("summary_note_counts", "2" in _summary_note({"breach_count": 2}))

    txt, htm = record_view(rec)
    add("view_has_breach", "Wattpad" in txt and "Wattpad" in htm)
    add("view_has_entry", "entry: a@b.co:pw" in txt)
    add("view_has_table", "\x3ctable\x3e" in htm)
    add("view_has_css", "\x3cstyle\x3e" in htm and "\x3c/style\x3e" in htm)
    add("view_never_raises", record_view(None) == ("", ""))
    add("view_password_only", "password only" in record_view(
        {"kind": "password", "pw_count": 3})[0])

    add("esc_zero", _esc(0) == "0")
    add("esc_false", _esc(False) == "False")
    _z = {"kind": "combo", "email": "a@b.co", "pw_count": 0, "verdict": "NEW",
          "addr_verdict": "CLEAN", "read": True}
    _zt, _zh = record_view(_z)
    add("html_keeps_zero", "password appearances: 0" in _zh)
    add("html_keeps_seen_zero", "seen: 0 time(s)" in _zh)
    add("text_keeps_zero", "password appearances: 0" in _zt)
    add("basis_partial", "domain match" in record_view(
        {"kind": "email", "email": "a@b.co", "read": True,
         "partial_read": True})[0])
    add("basis_refused", "404" in record_view(
        {"kind": "email", "email": "a@b.co", "read": True, "count": 0})[0])
    add("basis_unread", "nothing readable" in record_view(
        {"kind": "email", "email": "a@b.co", "read": False})[0])
    add("basis_xposed", "XposedOrNot" in record_view(
        {"kind": "email", "email": "a@b.co", "read": True, "count": 0,
         "via": "xposedornot"})[0])

    add("proxy_parse_auth", (parse_proxy_line("u:p@1.2.3.4:8080") or {}).get("user") == "u")
    add("proxy_parse_plain", (parse_proxy_line("1.2.3.4:8080") or {}).get("port") == 8080)
    add("proxy_reject", parse_proxy_line("nope") is None)
    add("proxy_cfg_server", (_proxy_cfg("1.2.3.4:8080") or {}).get("server")
        == "http://1.2.3.4:8080")
    add("proxy_url_quotes", "%2B" in _proxy_url("u:pa+ss@1.2.3.4:8080"))

    add("flight_callable", callable(flight) and callable(flight_state))
    add("flight_takes_diagnose", "diagnose" in inspect_sig(flight))
    add("flight_consts", FLIGHT_WANT >= 1 and FLIGHT_MAX >= FLIGHT_WANT
        and POOL_TTL > 0)
    add("flight_read_want", FLIGHT_READ_WANT >= 1)
    add("flight_carry_200", 200 in CARRY_STATUS)
    add("flight_carry_401", 401 in CARRY_STATUS)
    add("flight_carry_404", 404 in CARRY_STATUS)
    add("flight_carry_403", 403 in CARRY_STATUS)
    add("flight_wall_401", 401 in WALL_STATUS)
    add("flight_wall_403", 403 in WALL_STATUS)
    add("flight_not_carry_0", 0 not in CARRY_STATUS)
    add("pool_ttl_hour", POOL_TTL >= 3600.0)
    add("flight_workers_low", FLIGHT_WORKERS <= 3)
    add("flight_jitter", FLIGHT_JITTER > 0)
    add("read_jitter", READ_JITTER > 0)
    add("flight_timeout_35s", FLIGHT_TIMEOUT == 35000)
    add("flight_probe_is_email", is_email(FLIGHT_PROBE))
    add("flight_pool_only", FLIGHT_POOL == "proxies_breach.txt")
    add("flight_cap_above_140", FLIGHT_MAX >= 140)
    add("fetch_js", "fetch(" in FETCH_JS and "credentials" in FETCH_JS)
    add("flight_geo_helper", callable(_flight_geo))
    add("flight_log_helper", "no test flight" in flight_log_text())
    add("flight_state_keys", "kept" in flight_state() and "pool" in flight_state()
        and "log" in flight_state() and "codes" in flight_state()
        and "reads" in flight_state())
    add("flight_browser_returns_pair", callable(_flight_browser))
    add("pool_status_keys", set(pool_status()) == {"count", "sample", "flight"})
    _lgl = []
    _say(_lgl, "x")
    add("say_appends", _lgl == ["x"])

    # ---- candidates: proxies.txt first, full-line dedupe, dead nodes skipped ----
    _was_c = owner()
    set_owner("zzcand")
    _pf, _mf = _user_file("proxies.txt"), _user_file("proxy_meta.json")
    _old_pf = _old_mf = None
    try:
        for _p in (_pf, _mf):
            if os.path.exists(_p):
                with open(_p, encoding="utf-8") as _fh:
                    if _p == _pf:
                        _old_pf = _fh.read()
                    else:
                        _old_mf = _fh.read()
        with open(_mf, "w", encoding="utf-8") as _fh:
            json.dump({"probe": {"1.2.3.4:2": {"reason": "dead"}}}, _fh)
        with open(_pf, "w", encoding="utf-8") as _fh:
            _fh.write("u:p@1.1.1.1:1\nv:q@1.1.1.1:1\nu:p@1.1.1.1:1\n"
                      "1.2.3.4:2\n5.6.7.8:3\n")
        _got = _candidates()
        add("cand_full_line_dedupe", len(_got) == 3)
        add("cand_keeps_two_creds", _got.count("u:p@1.1.1.1:1") == 1
            and "v:q@1.1.1.1:1" in _got)
        add("cand_skips_dead", "1.2.3.4:2" not in _got)
        add("cand_keeps_unknown", "5.6.7.8:3" in _got)
    finally:
        for _p, _old in ((_pf, _old_pf), (_mf, _old_mf)):
            try:
                if _old is not None:
                    with open(_p, "w", encoding="utf-8") as _fh:
                        _fh.write(_old)
                elif os.path.exists(_p):
                    os.remove(_p)
            except Exception:
                pass
        set_owner(_was_c)

    add("cat_helpers", callable(catalogue) and callable(_cat_rows)
        and callable(catalogue_state) and callable(_cat_row_by_name))
    add("cat_ttl", CATALOGUE_TTL >= 3600.0)
    _keep_cat = dict(_cat)
    _cat["by_domain"] = {"b.co": [{"Name": "X", "Domain": "b.co",
                                   "BreachDate": "2024-01-01", "PwnCount": 5,
                                   "DataClasses": ["Passwords"]}],
                         "a.b.co": []}
    _cat["ts"] = time.time()
    _cat["busy"] = False
    add("cat_match", len(_cat_rows("me@b.co")) == 1)
    add("cat_miss", _cat_rows("me@z.co") == [])

    # ---- the second source: shape, spelling, and every miss/fail branch ----
    add("corpus_key", _corpus_key("Collection #1") == "collection1")
    add("corpus_key_same", _corpus_key("Collection-1") == _corpus_key("Collection #1"))
    add("corpus_by_key", _is_corpus({"Name": "ExploitIN"}))
    add("corpus_plain", not _is_corpus({"Name": "Wattpad", "Domain": "wattpad.com"}))
    add("xposed_consts", XPOSED_ANALYTICS.startswith("https://api.xposedornot.com/"))
    add("xposed_callable", callable(_xposed_lookup) and callable(_xposed_rows)
        and callable(_xposed_fetch))
    _xr = _xposed_rows({"ExposedBreaches": {"breaches_details": [
        {"breach": "Wattpad", "domain": "wattpad.com", "xposed_date": "2020",
         "xposed_records": 5, "xposed_data": "Email addresses;Passwords",
         "verified": "Yes", "details": "d"}]}})
    add("xposed_rows_shape", isinstance(_xr, list) and len(_xr) == 1)
    add("xposed_rows_year", _xr[0]["BreachDate"] == "2020-01-01")
    add("xposed_rows_classes", _xr[0]["DataClasses"] == ["Email addresses",
                                                         "Passwords"])
    add("xposed_rows_verified", _xr[0]["IsVerified"] is True)
    add("xposed_rows_records", _xr[0]["PwnCount"] == 5)
    add("xposed_rows_none", _xposed_rows({"Error": "Not found"}) is None)
    add("xposed_rows_empty", _xposed_rows(
        {"ExposedBreaches": {"breaches_details": []}}) == [])
    add("xposed_summary_fallback", len(_xposed_rows(
        {"BreachesSummary": {"site": "Tumblr;Wattpad"}}) or []) == 2)
    add("xposed_summary_corpus", (_xposed_rows(
        {"BreachesSummary": {"site": "Collection-1"}}) or [{}])[0]["IsSpamList"]
        is True)

    _cat["by_domain"] = {}
    _cat["ts"] = 0.0
    _cat["error"] = "fetch failed"
    add("cat_none_is_unread", _cat_rows("me@b.co") is None)
    add("cat_state_keys", set(catalogue_state()) == {"domains", "age", "error"})
    _cat.update(_keep_cat)

    add("rotate_default", _cfg.get("rotate") is True)
    add("slot_class", callable(_Slot))
    add("slot_reuse_reset", hasattr(_Slot, "reset") and hasattr(_Slot, "get")
        and hasattr(_Slot, "bad") and hasattr(_Slot, "ok"))
    add("slot_limits", SLOT_FAILS_MAX >= 1 and SLOT_USES_MAX >= 1)
    _s = _Slot()
    for _ in range(SLOT_FAILS_MAX):
        _s.bad()
    add("slot_bad_clears", _s.ctx is None and _s.page is None)
    _s2 = _Slot()
    _s2.bad()
    _s2.ok()
    add("slot_ok_resets_fails", _s2.fails == 0)

    _keep_pool, _keep_rot = _cfg.get("pool"), _cfg.get("rotate")
    _cfg["pool"] = ["1.1.1.1:1", "2.2.2.2:2", "3.3.3.3:3"]
    _cfg["rotate"] = False
    _who = _owner_key()
    _cursors[_who] = [0]
    _a, _b = _pick_proxy(set()), _pick_proxy(set())
    add("walk_differs", _a != _b and _a in _cfg["pool"] and _b in _cfg["pool"])
    _cfg["rotate"] = True
    add("random_spreads", len({_pick_proxy(set()) for _ in range(60)}) == 3)
    add("avoid_set", _pick_proxy({"1.1.1.1:1", "2.2.2.2:2"}) == "3.3.3.3:3")
    add("avoid_exhausted", _pick_proxy({"1.1.1.1:1", "2.2.2.2:2", "3.3.3.3:3"}) is None)
    _bads[_who] = {"1.1.1.1:1": BAD_AFTER}
    add("bad_node_skipped", _pick_proxy(set()) in ("2.2.2.2:2", "3.3.3.3:3"))
    _bads.pop(_who, None)
    _cfg["pool"], _cfg["rotate"] = _keep_pool, _keep_rot
    add("pick_empty_pool", _pick_proxy(set()) is not None or not pool_lines())

    add("configure_takes_workers", "workers" in inspect_sig(configure))
    add("configure_takes_rotate", "rotate" in inspect_sig(configure))
    add("configure_takes_flight", "flight" in inspect_sig(configure))
    add("check_many_takes_workers", "workers" in inspect_sig(check_many))
    add("check_many_takes_rotate", "rotate" in inspect_sig(check_many))
    add("check_many_takes_flight_first", "flight_first" in inspect_sig(check_many))
    add("check_takes_cancel", "cancel" in inspect_sig(check))
    add("search_takes_cancel", "cancel" in inspect_sig(_search_address))
    add("clear_cache_exists", callable(clear_cache))
    add("cache_stats_keys", set(cache_stats()) == {"entries", "bytes", "path"})
    add("page_wanted", page_wanted("records") is True)
    add("rotate_reported", "rotate" in report())
    add("cat_reported", "catalogue" in report())
    add("flight_reported", "flight" in report())
    add("tries_reported", report().get("tries") == 3)
    add("tag_regex", bool(_TAG_RE.search("\x3cb\x3ex\x3c/b\x3e")))

    _ev = threading.Event()
    add("cancel_false", not _is_cancelled(_ev))
    _ev.set()
    add("cancel_true", _is_cancelled(_ev))

    _was = owner()
    set_owner("aaaa1111")
    add("user_file_prefixed", _user_file(CACHE_NAME) == "aaaa1111_" + CACHE_NAME)
    add("flight_pool_prefixed", _flight_pool_path() == "aaaa1111_" + FLIGHT_POOL)
    add("owner_key_is_pin", _owner_key() == "aaaa1111")
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
    if "--catalogue" in argv:
        cat = catalogue(force=True)
        print("catalogue:", "unreadable" if cat is None else
              "%d domain(s)" % len(cat))
        return 0 if cat is not None else 1
    if "--xposed" in argv:
        try:
            target = argv[argv.index("--xposed") + 1]
        except Exception:
            print("usage: breach.py --xposed someone@example.com")
            return 2
        state, payload, note = _xposed_lookup(target)
        print("state:", state, "|", note)
        if payload:
            for b in payload.get("Breaches") or []:
                print("  %-32s %-10s %s" % (b.get("Title") or b.get("Name") or "?",
                                            b.get("BreachDate") or "-",
                                            ", ".join(b.get("DataClasses") or [])))
        return 0 if state != "fail" else 1
    if "--flight" in argv:
        got = flight(force=True, diagnose=("--diagnose" in argv))
        print("\n".join(got.get("log") or []))
        return 0 if got.get("kept") else 1
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
                                                  "pw_band", "count", "read",
                                                  "partial_read", "pwned", "via",
                                                  "error")}, indent=2))
        print(trace_text(limit=40))
        return 0 if res.get("verdict") else 1
    selftest(verbose=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
