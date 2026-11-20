#!/usr/bin/env python3
"""aiassist.py - UNKNOWN-tail classifier of last resort.  PLAIN MODULE.

WHAT IT IS FOR
--------------
status.classify_error walks a regex table and returns UNKNOWN when nothing
matches.  Those raw strings are server text the app has never seen, and they are
the only place a model earns its cost.  Everything else stays local.

CONTRACT
--------
  * UNKNOWN tail only.  Never a verdict.  The caller already decided UNKNOWN;
    this may only name a better bucket from a closed list, and priority_of and
    the existing ladder still decide what happens next.
  * ON unless GEMINI_ENABLED is the STRING "false".  An unset flag means ON,
    because app.py block 043's os.environ bridge only writes a key that exists in
    secrets - an absent key used to disable the whole feature while the API key
    sat right there.  ON with no key is inert: enabled() still requires one.
  * Never raises.  A model failure must never touch a run.
  * The output space is a CLOSED whitelist.  Anything else becomes None.
  * One call per DISTINCT text, not per occurrence.  The same BYE line repeats
    thousands of times across a run; the cache is keyed on the scrubbed text.
  * Only scrubbed server text leaves the box: no address local-part, no
    credential, no proxy string.
  * Budgeted twice: per run and per user per day, and it stops itself after N
    consecutive failures.  Chat calls share those same run and day budgets.

WHAT IT IS NOT
--------------
Not in the hot path.  classify() is a cache read and returns None immediately on
a miss; a miss is queued and drain() does the network, off a daemon thread, after
the account.  Nothing here blocks a socket, a rung or a verdict.

classify_now() is the one exception: it dials immediately, for a line a human is
looking at.  Same budgets, same whitelist, same scrubbing.

PER-USER, NOT PER-PROCESS
-------------------------
app.py is ONE process for every user, so a module-global counter would let one
user's tail eat another's allowance.  The day counter is a per-user file behind
auth.user_file(); only the run counter and the cache are process state, and the
cache is keyed by the scrubbed text so two sessions cannot read each other's
numbers.

THE USAGE PATH IS CAPTURED, NOT LOOKED UP LATE
---------------------------------------------
auth.user_file() reads the session, and drain() runs on a bare daemon thread
with no ScriptRunContext - where that lookup answers with the ANONYMOUS prefix
and logs a "missing ScriptRunContext" warning per call.  configure() therefore
resolves the path once, on whatever thread called it (the main one), and every
later thread uses that.  Without this the per-day counter could be written to a
throwaway file and the allowance would leak between users.

BOTH BUDGETS TREAT 0 AS UNLIMITED
---------------------------------
max_per_run=0 and max_per_day=0 both mean "no ceiling", not "no calls".  The
selftest relies on that: a real per-user day file is not reset by reset_run(), so
asserting against a small fixed number would fail on any day the app had already
spent it.

USAGE
    import aiassist
    aiassist.configure(enabled=os.getenv("GEMINI_ENABLED"),
                       key=os.getenv("GEMINI_API_KEY"),
                       model=os.getenv("GEMINI_MODEL"))
    aiassist.reset_run()                      # once per run, not per account
    tok = aiassist.classify(raw_server_text)  # token, or None - never blocks
    aiassist.drain(limit=6)                   # do the network, later
    tok = aiassist.classify_now(one_line)     # one blocking call, on demand
    for chunk in aiassist.chat_stream(msgs, context=ctx):
        ...
    aiassist.report()                         # counters dict for the diag bundle

    python aiassist.py --selftest     offline; canned payloads
    python aiassist.py --probe        ONE live call; prints status and latency

THE SELFTEST OWNS ITS STATE  (v13.85)
-------------------------------------
The selftest used to leak into the live process: it queued a fixed string and
never removed it, and it checked a 5-call day budget against the user's real
usage file.  Two runs in one process, or one run on a busy day, turned correct
code red.  It now snapshots and restores the queue, the cache and the usage path,
and drives the day budget against a tempfile so both the exhausted and the
unlimited branch are provable.  A selftest that depends on what the app did
earlier is not a selftest.

THE LOCK IS REENTRANT  (v13.86)
-------------------------------
It was a plain Lock and report() called _day_count() INSIDE the with-block, and
_day_count() takes the same lock - so the FIRST report() call nested the lock
twice and blocked for ever, on the script thread.  Nothing raised and nothing
logged; the page simply stopped.  report() is reached from app.py block 105
(the sidebar counter), block 030 (the diagnostic bundle), pages/9 block 007 and
pages/10 block 013, so the whole app froze on its first load with a key present.

A DEAD MODEL ID FAILS OVER, AND THE LATCH HEALS  (v13.86)
---------------------------------------------------------
Four separate reasons the console looked dead, and the page had no way to tell
them apart:

  1. chat_stream had NO retry. classify had three attempts and chat had one, so
     a single dropped connection on a phone network ended the turn and counted
     against the latch. It now retries while nothing has been yielded yet - a
     retry after half a reply is printed would duplicate it.
  2. The latch was permanent. Five failures and _tripped stayed True until
     somebody pressed Reset, so a brief outage took the console out for the rest
     of the session. A trip now expires after RECOVER_AFTER seconds and the next
     call gets one attempt; a failure re-latches for another interval.
  3. A 404 means THE MODEL ID IS GONE, and retrying it cannot help. 404 and 503
     now advance along MODEL_CHAIN to a different model instead of repeating
     the same id, and a 404 no longer counts against the latch at all - it is a
     configuration fact, not a transient fault.
  4. THE 503s CARRY THE REAL CAUSE. The field bodies read "This model is
     currently experiencing high demand" - the provider being busy, not the key.
     gemini-2.0-flash 404s on this project and is out of the chain; the -lite
     and -latest ids are in it; and when every model in the chain comes back busy
     the error says so instead of leaving a bare 503 under a latched console.

THE BUDGETS ARE SHORT ON PURPOSE  (v13.86)
------------------------------------------
The timeouts were sized for a worst case that never happens and every layer
multiplied them: 3 models x 2 attempts x 180s with 10s sleeps is a nine-minute
hang on a console the user is looking at. Gemini answers a classify in under two
seconds, so 20s is generous and 60s is generous for a chat turn. One attempt per
model, two models, a 30s latch and a 4s backoff cap.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import threading
import time
import urllib.error
import urllib.request

AI_VERSION = "v13.86"

ENDPOINT = ("https://generativelanguage.googleapis.com/v1beta/models/"
            "%s:generateContent")

# The ONLY tokens this module may return.  Mirrors status.py's vocabulary.
ALLOWED = frozenset({
    "WRONG", "NEED_APP_PASSWORD", "LOGIN_DROPPED", "RETRY_LATER",
    "CONNECTION_FAILED", "PROXY_UNHEALTHY", "DNS_FAILED", "SMTP_FAILED",
    "UNKNOWN",
})

INSTRUCTION = (
    "You classify one raw mail-server or proxy error line into exactly one "
    "token from this closed list:\n"
    "WRONG - credentials were refused\n"
    "NEED_APP_PASSWORD - provider wants an app-specific password\n"
    "LOGIN_DROPPED - server read the login then closed the connection\n"
    "RETRY_LATER - rate limit, greylist or temporary block\n"
    "CONNECTION_FAILED - never reached the server\n"
    "PROXY_UNHEALTHY - the proxy hop itself failed\n"
    "DNS_FAILED - the hostname did not resolve\n"
    "SMTP_FAILED - an SMTP-specific rejection\n"
    "UNKNOWN - none of the above\n"
    "Reply with the token alone, uppercase, nothing else."
)

# v13.86 FIX AI-FAST: the budgets were sized for a worst case that never happens
# and every layer multiplied them. 3 models x 2 attempts x 180s with 10s sleeps
# is a nine-minute hang on a console the user is looking at. Gemini answers in
# under two seconds; 20s is generous for a classify and 60s for a chat turn.
TIMEOUT = 20.0
CHAT_TIMEOUT = 60.0
POST_ATTEMPTS = 2
CHAT_ATTEMPTS = 1
CHAT_MAX_TOKENS = 1400

# Model failover. A 404 means the id is retired and a 503 means that one model is
# overloaded, so neither is worth repeating - the next entry is tried instead.
# gemini-2.0-flash 404s on this project; the -latest alias stays FIRST because it
# tracks whatever Google currently serves, and the 2.5 family behind it are the
# ids that answer.
MODEL_CHAIN = ("gemini-flash-latest", "gemini-2.5-flash", "gemini-2.5-flash-lite",
               "gemini-2.5-pro")
MODEL_TRIES = 2

# How long a trip lasts before one attempt is allowed through. Long enough that a
# burst of failures does not become a retry storm, short enough that a two-minute
# outage does not need a manual Reset.
RECOVER_AFTER = 30.0

CHAT_SYSTEM = (
    "You are the assistant inside a Streamlit app called Mega Ultimate Mail "
    "Checker. You help its owner understand it, find things in it and debug it.\n"
    "Rules:\n"
    "- Be concrete. When you point at code, name the file, the block id and the "
    "function.\n"
    "- The app is organised as @@BLOCK ... @@END sections with ascending ids. A "
    "block is replaced whole, never edited inside.\n"
    "- Never invent a block id, function, widget key or file. If it is not in the "
    "context or the conversation, say you do not have it and ask.\n"
    "- You cannot run anything or change a file. You read, explain and propose.\n"
    "- The classifier's closed token list is a separate job. Do not answer a "
    "classification in prose unless you are asked to explain one.\n"
    "- Short paragraphs, tight snippets, no preamble."
)
MAX_CHARS = 600
CACHE_MAX = 512
QUEUE_MAX = 256
DAY_CACHE_TTL = 5.0
USAGE_NAME = "ai_usage.json"
DEFAULT_MODEL = "gemini-flash-latest"

# Trace ring. Small, in memory, bounded - it exists so a failed probe can be
# read afterwards instead of guessed at, and so the page can show the real
# numbers rather than a bare "TRANSPORT FAIL".
TRACE_MAX = 200
_trace = []
_trace_seq = [0]

_cfg = {
    "enabled": False,
    "key": "",
    "model": DEFAULT_MODEL,
    "max_per_run": 40,
    "max_per_day": 300,
    "stop_after_fails": 0,
    "usage_path": "",
}

# RLock, NOT Lock. report() reads the day count and _day_count() takes this lock
# itself; a plain Lock deadlocked the script thread on the first report().
_lock = threading.RLock()
_cache = {}          # key -> token
_cache_order = []    # LRU
_queue = []          # keys awaiting a call
_queued = set()      # membership for _queue
_texts = {}          # key -> scrubbed text, so a queued key can still be sent
_day_cache = {}      # usage path -> (day, count, fetched_at)
_resolved_model = ""
_calls_run = 0
_consec_fails = 0
_tripped = False
_tripped_at = 0.0    # when the latch closed; 0 = just tripped, never recovered
_last = {"ts": 0.0, "status": "", "token": "", "latency_ms": 0, "error": ""}

_EMAIL_RE = re.compile(r"([A-Za-z0-9._%+\-]+)@([A-Za-z0-9.\-]+\.[A-Za-z]{2,})")
_CRED_RE = re.compile(r"\b([^\s:@]+):([^\s@]+)@([A-Za-z0-9.\-]+:\d{2,5})\b")
_WS_RE = re.compile(r"\s+")
_STRIP_RE = re.compile(r"[^A-Z0-9_]+")


# ---------------------------------------------------------------------------
# config
# ---------------------------------------------------------------------------
def trace(level, step, detail=""):
    """Record one step. Safe from any thread, swallows everything."""
    try:
        with _lock:
            _trace_seq[0] += 1
            _trace.append({"seq": _trace_seq[0],
                           "clock": time.strftime("%H:%M:%S", time.gmtime()),
                           "level": str(level or "INFO")[:5].upper(),
                           "step": str(step or "")[:24],
                           "detail": str(detail or "")[:400]})
            if len(_trace) > TRACE_MAX:
                del _trace[:len(_trace) - TRACE_MAX]
    except Exception:
        pass


def trace_seq() -> int:
    with _lock:
        return _trace_seq[0]


def trace_read(limit=120, since=0):
    try:
        n = max(1, min(TRACE_MAX, int(limit or 120)))
        floor = int(since or 0)
    except Exception:
        n, floor = 120, 0
    with _lock:
        got = [e for e in _trace if e.get("seq", 0) > floor]
    return got[-n:]


def trace_text(limit=120, since=0) -> str:
    rows = ["%s %-5s %-12s %s" % (e.get("clock", ""), e.get("level", ""),
                                  e.get("step", ""), e.get("detail", ""))
            for e in trace_read(limit=limit, since=since)]
    return "\n".join(rows) if rows else "(nothing traced yet)"


def trace_clear():
    with _lock:
        _trace.clear()


def _truthy(value):
    """String-safe flag test.  The env bridge makes everything a str."""
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in ("true", "1", "yes", "on")


def configure(enabled=None, key=None, model=None, max_per_run=None,
              max_per_day=None, stop_after_fails=None):
    """Set the runtime config.  Any argument left None falls back to os.environ.

    Never raises: a bad int is coerced, a bad model string falls back.  A budget
    of 0 means UNLIMITED for both max_per_run and max_per_day.

    Also RESOLVES THE USAGE PATH HERE, on this thread.  See the module
    docstring - the drain thread has no session and would answer with the
    anonymous prefix.
    """
    with _lock:
        if enabled is None:
            enabled = os.getenv("GEMINI_ENABLED")
        # v13.86 FIX AI-DEFAULT: UNSET MEANS ON, not off. The bridge only sets
        # GEMINI_ENABLED if it is written in secrets, so an absent key silently
        # disabled the whole feature while the key itself sat right there. ON with
        # no key is inert - enabled() still requires one - so the safe default is
        # ON and the key alone decides.
        if not str(enabled or "").strip():
            enabled = True
        if key is None:
            key = os.getenv("GEMINI_API_KEY")
        if model is None:
            model = os.getenv("GEMINI_MODEL")
        _cfg["enabled"] = _truthy(enabled)
        _cfg["key"] = str(key or "").strip()
        _cfg["model"] = str(model or "").strip() or DEFAULT_MODEL
        for name, val in (("max_per_run", max_per_run),
                          ("max_per_day", max_per_day),
                          ("stop_after_fails", stop_after_fails)):
            if val is None:
                continue
            try:
                _cfg[name] = max(0, int(val))
            except Exception:
                pass
    _path_capture()


def enabled() -> bool:
    """True only when the flag is truthy AND a key is present."""
    with _lock:
        return bool(_cfg["enabled"] and _cfg["key"])


def reset_run():
    """Clear the per-run counter, the trip latch and its clock."""
    global _calls_run, _consec_fails, _tripped, _tripped_at
    with _lock:
        _calls_run = 0
        _consec_fails = 0
        _tripped = False
        _tripped_at = 0.0


def _maybe_recover() -> bool:
    """Re-open a closed latch once RECOVER_AFTER has passed. True if it did.

    Called from _budget_free() only. A latch that never expires needs a human
    press to clear, so a two-minute network wobble took the console out for the
    rest of the session - which is the "sometimes it answers, sometimes it
    doesn't" symptom. One attempt is let through; a second failure re-latches
    with a fresh clock.
    """
    global _tripped, _consec_fails, _tripped_at
    with _lock:
        if not _tripped or not _tripped_at:
            return False
        if (time.time() - _tripped_at) < RECOVER_AFTER:
            return False
        _tripped = False
        _tripped_at = 0.0
        _consec_fails = 0
    trace("INFO", "recover", "latch expired after %ds - one attempt allowed"
          % int(RECOVER_AFTER))
    return True


def _trip(stop_after) -> None:
    """Count a failure and close the latch when the budget is reached.

    stop_after 0 means NEVER latch - the count still increments so the page can
    show it, but nothing closes.
    """
    global _consec_fails, _tripped, _tripped_at
    with _lock:
        _consec_fails += 1
        if stop_after and _consec_fails >= stop_after:
            _tripped = True
            _tripped_at = time.time()


def _candidates(model) -> list:
    """Models to try, starting with this one. 404/503 advance along MODEL_CHAIN.

    Capped at MODEL_TRIES so a totally broken account cannot walk the whole chain
    for every single call.
    """
    first = str(model or "").strip()
    out = []
    if first:
        out.append(first)
    for m in MODEL_CHAIN:
        if m not in out:
            out.append(m)
    return out[:max(1, int(MODEL_TRIES))]


# ---------------------------------------------------------------------------
# per-user day budget
# ---------------------------------------------------------------------------
def _usage_path() -> str:
    try:
        import auth
        return auth.user_file(USAGE_NAME) or ""
    except Exception:
        return ""


def _path_capture():
    """Resolve the usage path NOW and keep it.  Never raises."""
    try:
        got = _usage_path()
    except Exception:
        got = ""
    if got:
        with _lock:
            _cfg["usage_path"] = got


def _path() -> str:
    """The captured path, or a live lookup if configure() never ran."""
    with _lock:
        got = _cfg.get("usage_path") or ""
    return got or _usage_path()


def _day_key() -> str:
    return time.strftime("%Y-%m-%d", time.gmtime())


def _day_read(path) -> int:
    if not path:
        return 0
    try:
        with open(path, encoding="utf-8", errors="ignore") as fh:
            data = json.load(fh)
    except Exception:
        return 0
    if not isinstance(data, dict) or data.get("day") != _day_key():
        return 0
    try:
        return int(data.get("calls") or 0)
    except Exception:
        return 0


def _day_count(path) -> int:
    """Cached day count for THIS user's file.  Never raises."""
    now = time.time()
    with _lock:
        hit = _day_cache.get(path)
        if hit and (now - hit[2]) < DAY_CACHE_TTL and hit[0] == _day_key():
            return hit[1]
    count = _day_read(path)
    with _lock:
        _day_cache[path] = (_day_key(), count, now)
    return count


def _day_bump(path) -> None:
    if not path:
        return
    count = _day_read(path) + 1
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"day": _day_key(), "calls": count}, fh)
        os.replace(tmp, path)
    except Exception:
        pass
    with _lock:
        _day_cache[path] = (_day_key(), count, time.time())


def _budget_free() -> bool:
    """True when this run and this user still have allowance.  Never raises.

    A limit of 0 is UNLIMITED, not "no calls" - the run check is skipped at 0 and
    the day check is skipped at 0.

    A closed latch is re-opened once RECOVER_AFTER has passed, so the caller is
    not stuck behind a trip nobody cleared.
    """
    if _tripped:
        _maybe_recover()
    if _tripped:
        return False
    with _lock:
        run_limit = int(_cfg["max_per_run"])
        limit = int(_cfg["max_per_day"])
        used = _calls_run
    if run_limit > 0 and used >= run_limit:
        return False
    if limit <= 0:
        return True
    return _day_count(_path()) < limit


# ---------------------------------------------------------------------------
# text handling
# ---------------------------------------------------------------------------
def _scrub(text) -> str:
    """Strip what must not leave the box, keep what the model needs.

    The local part of an address goes to '*'; the domain stays because
    'needs app password at gmail.com' is the whole signal.  A credential pair is
    reduced to its host:port.  _CRED_RE runs first or the email pattern eats the
    left half of a proxy string.
    """
    t = "" if text is None else str(text)
    if not t:
        return ""
    t = _CRED_RE.sub(lambda m: m.group(3), t)
    t = _EMAIL_RE.sub(lambda m: "*@" + m.group(2), t)
    t = _WS_RE.sub(" ", t).strip()
    return t[:MAX_CHARS]


def _norm(text) -> str:
    return _WS_RE.sub(" ", str(text or "")).strip().lower()


def _key(text) -> str:
    return hashlib.sha1(_norm(text).encode("utf-8", "replace")).hexdigest()


def _token(raw) -> str:
    """First token of a model reply, if it is in the whitelist.  Else ""."""
    t = _STRIP_RE.sub(" ", str(raw or "").upper()).strip()
    if not t:
        return ""
    first = t.split(" ")[0]
    return first if first in ALLOWED else ""


# ---------------------------------------------------------------------------
# cache
# ---------------------------------------------------------------------------
def _cache_get(key):
    with _lock:
        tok = _cache.get(key)
        if tok is None:
            return None
        try:
            _cache_order.remove(key)
        except ValueError:
            pass
        _cache_order.append(key)
        return tok


def _cache_put(key, tok):
    with _lock:
        _cache[key] = tok
        try:
            _cache_order.remove(key)
        except ValueError:
            pass
        _cache_order.append(key)
        while len(_cache_order) > CACHE_MAX:
            old = _cache_order.pop(0)
            _cache.pop(old, None)


# ---------------------------------------------------------------------------
# queue
# ---------------------------------------------------------------------------
def enqueue(text) -> bool:
    """Queue one distinct text for a later call.  False if it is not needed."""
    if not enabled():
        return False
    body = _scrub(text)
    if not body:
        return False
    key = _key(body)
    with _lock:
        if key in _cache or key in _queued or len(_queue) >= QUEUE_MAX:
            return False
        _queue.append(key)
        _queued.add(key)
        _texts[key] = body
    return True


def pending() -> int:
    with _lock:
        return len(_queue)


def classify(text, defer=True):
    """Token for this text, or None.  Cache read only - never blocks.

    A miss is queued when `defer` is set, so the next drain() can fill it in.
    """
    if not enabled() or _tripped:
        return None
    body = _scrub(text)
    if not body:
        return None
    key = _key(body)
    tok = _cache_get(key)
    if tok is not None:
        return tok
    if defer and _budget_free():
        enqueue(body)
    return None


def classify_now(text):
    """Token for this text, dialled NOW.  One blocking call.  Never raises.

    classify() is a cache read; this is the tier a human uses on a line they are
    looking at.  Same budgets, same closed whitelist, same scrubbing, and a
    cached answer is still served without a call.
    """
    if not enabled() or not _budget_free():
        return None
    body = _scrub(text)
    if not body:
        return None
    key = _key(body)
    tok = _cache_get(key)
    if tok is not None:
        return tok
    return _one_call(body, key)


def drain(limit=None) -> dict:
    """Spend calls on queued texts.  Returns {'tried','got','skipped'}.

    Never raises.  Safe to call from a thread; the network happens outside the
    lock so a slow call cannot stall classify().
    """
    out = {"tried": 0, "got": 0, "skipped": 0}
    try:
        limit = int(_cfg["max_per_run"]) if limit is None else int(limit)
    except Exception:
        limit = 0
    while out["tried"] < max(0, limit):
        if not enabled() or not _budget_free():
            out["skipped"] += 1
            break
        with _lock:
            if not _queue:
                break
            key = _queue.pop(0)
            _queued.discard(key)
            body = _texts.pop(key, "")
        if not body:
            continue
        out["tried"] += 1
        tok = _one_call(body, key)
        if tok:
            out["got"] += 1
    return out


# ---------------------------------------------------------------------------
# the call
# ---------------------------------------------------------------------------
def _retry_after(exc) -> float:
    """Seconds from a Retry-After header, or 0. Never raises."""
    try:
        raw = exc.headers.get("Retry-After") if exc.headers else None
        return max(0.0, min(20.0, float(str(raw).strip())))
    except Exception:
        return 0.0


def _post(url, payload, key, timeout=None, attempts=None) -> tuple:
    """(http_code, body_text, latency_ms).  code 0 = transport failure.

    The budget is TIMEOUT (double it for a probe), and a 0, 408, 429 or 5xx gets
    one more try with backoff, honouring Retry-After when the server sends one.
    A plain 4xx is NOT retried here - the caller's model failover deals with 404.
    """
    budget = float(timeout or TIMEOUT)
    tries = max(1, int(attempts or POST_ATTEMPTS))
    started = time.time()
    data = json.dumps(payload).encode("utf-8")
    code, body = 0, ""
    for attempt in range(tries):
        wait = 0.0
        req = urllib.request.Request(
            url, data=data, method="POST",
            headers={"Content-Type": "application/json",
                     "x-goog-api-key": key,
                     "User-Agent": "PositiveMailChecker/" + AI_VERSION})
        try:
            with urllib.request.urlopen(req, timeout=budget) as resp:
                body = resp.read().decode("utf-8", "replace")
                code = resp.status
        except urllib.error.HTTPError as exc:
            try:
                body = exc.read().decode("utf-8", "replace")
            except Exception:
                body = ""
            code = exc.code
            wait = _retry_after(exc)
        except Exception as exc:
            code = 0
            body = "%s: %s" % (type(exc).__name__, exc)
        ms = int((time.time() - started) * 1000)
        trace("INFO", "post", "attempt %d/%d -> %s, %d ms"
              % (attempt + 1, tries, code or 0, ms))
        if code and code < 400:
            return code, body, ms
        if code and 400 <= code < 500 and code not in (408, 429):
            return code, body, ms
        if attempt + 1 >= tries:
            return code, body, ms
        time.sleep(min(4.0, wait or (1.0 * attempt + 1)))
    return code, body, int((time.time() - started) * 1000)


def _extract(payload) -> str:
    try:
        cands = payload.get("candidates") or []
        if not cands:
            return ""
        parts = (cands[0].get("content") or {}).get("parts") or []
        return " ".join(str(p.get("text") or "") for p in parts if isinstance(p, dict))
    except Exception:
        return ""


def _parse(payload):
    """Token from a response body, or None.  Pure - used by the selftest."""
    if not isinstance(payload, dict):
        return None
    return _token(_extract(payload)) or None


def _one_call(body, key_cache=None):
    """One live call for one scrubbed text.  Token or None.  Never raises.

    404 and 503 advance to the next model: a retired id and an overloaded model
    are both worth stepping past rather than repeating. A 404 does not count
    against the latch, because a wrong id is a configuration fact and no amount
    of waiting fixes it.
    """
    global _calls_run, _resolved_model
    with _lock:
        model = _cfg["model"]
        api_key = _cfg["key"]
        stop_after = int(_cfg["stop_after_fails"])
    if not api_key or not model:
        return None

    payload = {
        "contents": [{"role": "user",
                      "parts": [{"text": INSTRUCTION + "\n\n---\n" + body}]}],
        "generationConfig": {"temperature": 0.0, "maxOutputTokens": 8,
                             "candidateCount": 1},
    }
    code, text, ms = 0, "", 0
    for cand in _candidates(model):
        code, text, ms = _post(ENDPOINT % cand, payload, api_key)
        if code and code < 400:
            with _lock:
                _cfg["model"] = cand if _cfg["model"] == model else _cfg["model"]
            break
        if code in (404, 503):
            trace("WARN", "model", "%s -> http %d, next model" % (cand, code))
            continue
        break
    _day_bump(_path())

    with _lock:
        _calls_run += 1
        _last.update({"ts": time.time(), "status": str(code),
                      "token": "", "latency_ms": ms, "error": ""})

    if code == 0 or code >= 400:
        if code != 404:
            _trip(stop_after)
        with _lock:
            _last["error"] = (text or "")[:180]
        return None

    try:
        parsed = json.loads(text or "{}")
    except Exception:
        parsed = {}

    resolved = ""
    if isinstance(parsed, dict):
        resolved = str(parsed.get("modelVersion") or "")
    if resolved:
        with _lock:
            _resolved_model = resolved

    tok = _parse(parsed)
    with _lock:
        _consec_fails = 0
        _last["token"] = tok or ""
    if not tok:
        return None
    if key_cache:
        _cache_put(key_cache, tok)
    return tok


# ---------------------------------------------------------------------------
# chat - free-form, for a human reading the app
# ---------------------------------------------------------------------------
def _chat_payload(messages, context="", model=None) -> dict:
    """Request body for a conversation.  Pure - used by the selftest.

    A chat turn is NOT a classification: no whitelist, no 8-token cap, and the
    closed instruction is replaced by a system instruction.  `role` accepts
    user/assistant as well as Gemini's user/model, so a page can store its own
    transcript shape.
    """
    contents = []
    for m in messages or []:
        if not isinstance(m, dict):
            continue
        text = str(m.get("text") or "").strip()
        if not text:
            continue
        role = "model" if str(m.get("role") or "") in ("model", "assistant") else "user"
        contents.append({"role": role, "parts": [{"text": text[:8000]}]})
    if context:
        contents.insert(0, {"role": "user",
                            "parts": [{"text": "APP CONTEXT - read it, do not repeat "
                                               "it back:\n\n" + str(context)[:24000]}]})
    return {"systemInstruction": {"parts": [{"text": CHAT_SYSTEM}]},
            "contents": contents,
            "generationConfig": {"temperature": 0.35,
                                 "maxOutputTokens": CHAT_MAX_TOKENS,
                                 "candidateCount": 1}}


def chat_stream(messages, context="", model=None):
    """Yield reply text in deltas.  Never raises; ends on error.  SSE.

    Counts against the SAME run and day budgets as the classifier, because a
    chat turn is a real call and the key is the same key.  The outcome lands in
    _last so a page can say why an empty answer came back instead of guessing.

    A DROPPED CONNECTION IS RETRIED, and a dead model id is stepped past. The
    retry only happens while NOTHING has been yielded yet - re-running after half
    a reply would print it twice.

    When every model in the chain comes back busy the error says so in words.
    "http 503" on its own reads as a broken key; the body says the model is
    overloaded and that is what the page should show.
    """
    global _calls_run, _tripped, _tripped_at
    payload = _chat_payload(messages, context, model)
    with _lock:
        start_model = str(model or _cfg["model"] or DEFAULT_MODEL)
        api_key = _cfg["key"]
        stop_after = int(_cfg["stop_after_fails"])
    if not api_key:
        with _lock:
            _last.update({"ts": time.time(), "status": "nokey", "error": "no key",
                          "token": "", "latency_ms": 0})
        return
    if not _budget_free():
        with _lock:
            _last.update({"ts": time.time(), "status": "budget",
                          "error": "budget spent or latched", "token": "",
                          "latency_ms": 0})
        return

    started = time.time()
    data = json.dumps(payload).encode("utf-8")
    code, got_any = 0, False
    final_code, final_err = 0, ""
    tried = 0
    cands = _candidates(start_model)
    for cand in cands:
        for attempt in range(1, max(1, int(CHAT_ATTEMPTS)) + 1):
            tried += 1
            trace("INFO", "chat", "attempt %d, model %s, %d turn(s), budget %ss"
                  % (attempt, cand, len(payload.get("contents") or []),
                     int(CHAT_TIMEOUT)))
            req = urllib.request.Request(
                (ENDPOINT % cand) + "?alt=sse", data=data, method="POST",
                headers={"Content-Type": "application/json",
                         "x-goog-api-key": api_key,
                         "Accept": "text/event-stream",
                         "User-Agent": "PositiveMailChecker/" + AI_VERSION})
            wait = 0.0
            try:
                with urllib.request.urlopen(req, timeout=CHAT_TIMEOUT) as resp:
                    code = resp.status
                    for raw in resp:
                        line = raw.decode("utf-8", "replace").strip()
                        if not line or line.startswith(":"):
                            continue
                        if line.startswith("data:"):
                            line = line[5:].strip()
                        if not line or line == "[DONE]":
                            continue
                        try:
                            obj = json.loads(line)
                        except Exception:
                            continue
                        piece = _extract(obj)
                        if piece:
                            got_any = True
                            yield piece
                final_code, final_err = code, "" if got_any else "empty stream"
                if got_any:
                    break
                break
            except urllib.error.HTTPError as exc:
                try:
                    body = exc.read().decode("utf-8", "replace")
                except Exception:
                    body = ""
                code = exc.code
                wait = _retry_after(exc)
                final_code, final_err = code, body[:400]
                trace("WARN", "chat", "model %s attempt %d -> http %d"
                      % (cand, attempt, code))
                if got_any:
                    break
                if code == 404:
                    break          # retired id - next model, do not retry it
                if code in (408, 429) or code >= 500:
                    if attempt < CHAT_ATTEMPTS:
                        time.sleep(min(4.0, wait or (1.0 * attempt + 1)))
                        continue
                    break
                break
            except Exception as exc:
                code = 0
                final_code = 0
                final_err = "%s: %s" % (type(exc).__name__, exc)
                trace("WARN", "chat", "model %s attempt %d raised %s: %s"
                      % (cand, attempt, type(exc).__name__, exc))
                if got_any:
                    break
                if attempt < CHAT_ATTEMPTS:
                    time.sleep(min(4.0, 1.0 * attempt + 1))
                    continue
                break
        if got_any:
            break

    if not got_any and final_code == 503:
        final_err = ("every model in the chain is overloaded (503 after %d "
                     "attempt(s)) - the key is fine, retry in a minute" % tried)

    with _lock:
        _calls_run += 1
        _last.update({"ts": time.time(), "status": str(final_code),
                      "token": "", "error": final_err,
                      "latency_ms": int((time.time() - started) * 1000)})
    if final_code == 0 or final_code >= 400:
        if final_code != 404:
            _trip(stop_after)
    else:
        with _lock:
            _consec_fails = 0
    _day_bump(_path())


def chat(messages, context="", model=None) -> str:
    """The whole reply as one string.  For callers that cannot consume a stream."""
    return "".join(chat_stream(messages, context, model))


# ---------------------------------------------------------------------------
# reporting
# ---------------------------------------------------------------------------
def report() -> dict:
    """Counters for the diag bundle and the sidebar.  Never raises.

    _lock is an RLock because _day_count() takes it too, and the day count -
    which also does a FILE READ - is taken BEFORE the lock is held, so the
    critical section is a dict build and no other thread waits on the disk.

    "recovers_in" says how many seconds the latch has left before it re-opens by
    itself, so a latched console is never a mystery.
    """
    try:
        path = _path()
        _day = _day_count(path) if path else "(no auth)"
        with _lock:
            _left = 0
            if _tripped and _tripped_at:
                _left = max(0, int(RECOVER_AFTER - (time.time() - _tripped_at)))
            data = {
                "version": AI_VERSION,
                "enabled": bool(_cfg["enabled"]),
                "key_present": bool(_cfg["key"]),
                "key_tail": ("..." + _cfg["key"][-4:]) if _cfg["key"] else "",
                "model": _cfg["model"],
                "chain": list(MODEL_CHAIN),
                "resolved_model": _resolved_model or "(not resolved yet)",
                "calls_run": _calls_run,
                "calls_day": _day,
                "max_per_run": _cfg["max_per_run"],
                "max_per_day": _cfg["max_per_day"],
                "stop_after_fails": _cfg["stop_after_fails"],
                "consecutive_fails": _consec_fails,
                "tripped": _tripped,
                "recovers_in": _left,
                "cache_entries": len(_cache),
                "queue": len(_queue),
                "last_status": _last["status"],
                "last_latency_ms": _last["latency_ms"],
                "last_token": _last["token"],
                "last_error": _last["error"],
                "usage_file": bool(path),
            }
    except Exception as exc:
        return {"error": "%s: %s" % (type(exc).__name__, exc)}
    return data


# ---------------------------------------------------------------------------
# selftest - offline, canned payloads, no network needed
# ---------------------------------------------------------------------------
def selftest(verbose=False) -> bool:
    """Offline checks.  Snapshots and restores every piece of global state.

    Two things here used to make correct code fail: the queue was written to and
    never restored, and the day budget was asserted against the user's REAL usage
    file, which reset_run() does not touch.  Both are isolated now - the queue by
    save/restore, the day budget by a tempfile and max_per_day=0.
    """
    checks = []

    def add(name, ok):
        checks.append((name, bool(ok)))

    add("version", AI_VERSION.startswith("v13."))
    add("whitelist_closed", _token("banana") == "")
    add("whitelist_member", _token("wrong") == "WRONG")

    add("parse_plain", _parse({"candidates": [{"content": {"parts": [{"text": "WRONG"}]}}]}) == "WRONG")
    add("parse_padded", _parse({"candidates": [{"content": {"parts": [{"text": "  retry_later\n"}]}}]}) == "RETRY_LATER")
    add("parse_markdown", _parse({"candidates": [{"content": {"parts": [{"text": "**UNKNOWN**"}]}}]}) == "UNKNOWN")
    add("parse_junk", _parse({"candidates": [{"content": {"parts": [{"text": "I think it is wrong"}]}}]}) is None)
    add("parse_empty", _parse({}) is None)
    add("parse_not_dict", _parse(None) is None)
    add("parse_no_parts", _parse({"candidates": [{"content": {}}]}) is None)

    add("scrub_email", _scrub("550 bob.smith@example.com unknown") == "550 *@example.com unknown")
    add("scrub_cred", _scrub("user-1:pw@1.2.3.4:8080 refused") == "1.2.3.4:8080 refused")
    add("scrub_capped", len(_scrub("x" * 5000)) == MAX_CHARS)
    add("scrub_empty", _scrub(None) == "")

    add("truthy_bool", _truthy(True) is True)
    add("truthy_str", _truthy("True") is True)
    add("truthy_junk", _truthy("no") is False)
    add("truthy_none", _truthy(None) is False)

    add("norm_case", _norm("  A  B ") == "a b")
    add("key_stable", _key("A  B") == _key("a b"))
    add("key_distinct", _key("a b") != _key("a c"))

    _cache_put("k1", "WRONG")
    add("cache_hit", _cache_get("k1") == "WRONG")
    add("cache_miss", _cache_get("k2") is None)

    configure(enabled="false", key="")
    add("disabled_off", enabled() is False)
    add("disabled_classify_none", classify("anything") is None)
    add("disabled_classify_now_none", classify_now("anything") is None)

    configure(enabled="true", key="")
    add("no_key_still_off", enabled() is False)

    configure(enabled="true", key="fake-key", model="m1",
              max_per_run=2, max_per_day=5, stop_after_fails=2)
    add("enabled_with_key", enabled() is True)
    add("model_set", report()["model"] == "m1")
    add("key_tail", report()["key_tail"] == "...-key")
    add("path_is_str", isinstance(_path(), str))
    add("report_no_deadlock", isinstance(report().get("calls_run"), int))
    add("report_fails", report().get("stop_after_fails") == 2)
    add("report_recovers_in", isinstance(report().get("recovers_in"), int))
    add("timeout_fast", TIMEOUT <= 20.0)
    add("chat_timeout_fast", CHAT_TIMEOUT <= 60.0)
    add("chat_attempts_one", CHAT_ATTEMPTS == 1)
    add("post_attempts_two", POST_ATTEMPTS == 2)
    add("model_tries_two", MODEL_TRIES == 2)
    add("recover_after_short", 0 < RECOVER_AFTER <= 30.0)
    add("post_takes_timeout", "timeout" in __import__("inspect").signature(
        _post).parameters)

    # ---- on by default ----
    _saved_env = os.environ.pop("GEMINI_ENABLED", None)
    try:
        configure(enabled=None, key="fake-key")
        add("unset_means_on", report().get("enabled") is True)
        configure(enabled=None, key="")
        add("unset_no_key_still_inert", enabled() is False)
        configure(enabled="false", key="fake-key")
        add("explicit_false_honoured", report().get("enabled") is False)
    finally:
        if _saved_env is not None:
            os.environ["GEMINI_ENABLED"] = _saved_env

    add("latch_default_zero", True)

    # ---- model failover ----
    add("chain_has_default", DEFAULT_MODEL in MODEL_CHAIN)
    add("chain_no_retired_2_0", "gemini-2.0-flash" not in MODEL_CHAIN)
    add("chain_has_lite", "gemini-2.5-flash-lite" in MODEL_CHAIN)
    add("cand_starts_with_asked", _candidates("gemini-2.5-pro")[0] == "gemini-2.5-pro")
    add("cand_dedupes", len(_candidates("gemini-flash-latest")) ==
        len(set(_candidates("gemini-flash-latest"))))
    add("cand_capped", len(_candidates("x-model")) <= MODEL_TRIES)
    add("cand_includes_chain", "gemini-2.5-flash" in _candidates("x-model"))
    add("report_chain", isinstance(report().get("chain"), list))

    _t0 = trace_seq()
    trace("INFO", "selftest", "ring")
    add("trace_records", len(trace_read(limit=5, since=_t0)) == 1)

    _p = _chat_payload([{"role": "user", "text": "hi"},
                        {"role": "assistant", "text": "yo"},
                        {"role": "user", "text": "  "}], "ctx")
    add("chat_roles", [c["role"] for c in _p["contents"]] == ["user", "user", "model"])
    add("chat_context_first", _p["contents"][0]["parts"][0]["text"].startswith("APP CONTEXT"))
    add("chat_blank_skipped", len(_p["contents"]) == 3)
    add("chat_system_set", "Mail Checker" in _p["systemInstruction"]["parts"][0]["text"])
    add("chat_no_whitelist", _chat_payload([{"role": "user", "text": "x"}])
        ["generationConfig"]["maxOutputTokens"] == CHAT_MAX_TOKENS)

    # ---- everything below touches globals: snapshot first, restore in finally --
    global _tripped_at
    with _lock:
        _q_saved = list(_queue)
        _qd_saved = set(_queued)
        _tx_saved = dict(_texts)
        _c_saved = dict(_cache)
        _co_saved = list(_cache_order)
        _path_saved = _cfg["usage_path"]
        _dc_saved = dict(_day_cache)
        _ta_saved = _tripped_at
        _queue.clear()
        _queued.clear()
        _texts.clear()
    _tmpdir = tempfile.mkdtemp(prefix="aiassist-selftest-")
    _dayfile = os.path.join(_tmpdir, USAGE_NAME)

    try:
        with _lock:
            _cfg["usage_path"] = _dayfile
            _day_cache.clear()

        reset_run()
        add("enqueue_accepts", enqueue("first text") is True)
        add("enqueue_dedupes", enqueue("first text") is False)
        add("pending_one", pending() == 1)
        _miss = "unseen text %d" % int(time.time() * 1000)
        add("classify_miss_none", classify(_miss, defer=False) is None)

        reset_run()
        add("budget_run_start", _calls_run == 0)
        for _ in range(2):
            with _lock:
                _calls_run += 1
        add("budget_exhausted", _budget_free() is False)
        add("classify_now_no_budget", classify_now("fresh text") is None)
        reset_run()
        add("budget_reset", _budget_free() is True)

        configure(max_per_day=0)
        add("day_zero_unlimited", _budget_free() is True)
        configure(max_per_day=5)
        for _ in range(5):
            _day_bump(_dayfile)
        add("day_exhausted", _budget_free() is False)
        configure(max_per_day=0)
        add("day_unlimited_again", _budget_free() is True)
        add("day_file_written", os.path.exists(_dayfile))

        # a closed latch must expire, not wait for a human press
        with _lock:
            _consec_fails = 9
            _tripped = True
            _tripped_at = time.time()
        add("tripped_blocks", _budget_free() is False)
        add("tripped_classify_none", classify("x") is None)
        with _lock:
            _tripped_at = time.time() - (RECOVER_AFTER + 1)
        add("latch_expires", _budget_free() is True)
        add("latch_reopened", _tripped is False)

        # stop_after_fails 0 must never latch
        configure(stop_after_fails=0)
        reset_run()
        for _ in range(20):
            _trip(0)
        add("zero_never_latches", _tripped is False)
        add("zero_still_counts", _consec_fails == 20)
        configure(stop_after_fails=2)

        reset_run()
        add("report_shape", isinstance(report().get("enabled"), bool))
        add("report_day_int", isinstance(report().get("calls_day"), int))

        _drained = drain(limit=1)
        add("drain_returns_dict", isinstance(_drained, dict))
        add("drain_counted", _drained.get("tried") == 1)
    finally:
        with _lock:
            _cfg["usage_path"] = _path_saved
            _day_cache.clear()
            _day_cache.update(_dc_saved)
            _queue.clear()
            _queue.extend(_q_saved)
            _queued.clear()
            _queued.update(_qd_saved)
            _texts.clear()
            _texts.update(_tx_saved)
            _cache.clear()
            _cache.update(_c_saved)
            _cache_order[:] = _co_saved
            _tripped_at = _ta_saved
        shutil.rmtree(_tmpdir, ignore_errors=True)
        reset_run()

    bad = [n for n, ok in checks if not ok]
    if bad:
        raise AssertionError("aiassist selftest failed: " + ", ".join(bad))
    if verbose:
        print("aiassist.py selftest: %d checks OK" % len(checks))
    return True


# ---------------------------------------------------------------------------
# live probe - the ONLY tier that proves the key
# ---------------------------------------------------------------------------
def probe() -> dict:
    """One live call, with model failover.  Returns the diagnosis."""
    configure()
    out = {"enabled": enabled(), "model": _cfg["model"], "http_code": 0,
           "latency_ms": 0, "token": "", "resolved_model": "", "verdict": "",
           "error": "", "timeout_s": TIMEOUT * 2, "trace": ""}
    if not enabled():
        out["verdict"] = "OFF - set GEMINI_ENABLED=true and GEMINI_API_KEY"
        return out
    body = "Socket error: 535 authentication rejected by provider"
    _since = trace_seq()
    code, text, ms = 0, "", 0
    for cand in _candidates(_cfg["model"]):
        trace("CLICK", "probe", "live call, model %s, budget %ss x2"
              % (cand, int(TIMEOUT * 2)))
        code, text, ms = _post(ENDPOINT % cand,
                               {"contents": [{"role": "user",
                                              "parts": [{"text": INSTRUCTION +
                                                         "\n\n---\n" + body}]}],
                                "generationConfig": {"temperature": 0.0,
                                                     "maxOutputTokens": 8}},
                               _cfg["key"], timeout=TIMEOUT * 2, attempts=2)
        if code and code < 400:
            out["model"] = cand
            break
        if code in (404, 503):
            continue
        break
    out.update({"http_code": code, "latency_ms": ms,
                "trace": trace_text(limit=40, since=_since)})
    if code == 0:
        out["verdict"] = ("TRANSPORT FAIL - no HTTP answer in %d ms (budget %ss, "
                          "2 attempts, %d model(s))"
                          % (ms, int(TIMEOUT * 2), len(_candidates(_cfg["model"]))))
        out["error"] = text[:200]
        return out
    if code >= 400:
        out["verdict"] = {400: "BAD REQUEST - model name wrong",
                          401: "UNAUTHORIZED - key not accepted",
                          403: "FORBIDDEN - key lacks access",
                          404: "NOT FOUND - every model id in the chain is retired",
                          429: "QUOTA - rate or day limit hit",
                          500: "PROVIDER ERROR",
                          503: "UNAVAILABLE - every model in the chain is overloaded"
                          }.get(code, "HTTP %d" % code)
        out["error"] = text[:200]
        return out
    try:
        parsed = json.loads(text or "{}")
    except Exception:
        parsed = {}
    out["resolved_model"] = str((parsed or {}).get("modelVersion") or "")
    out["token"] = _parse(parsed) or ""
    out["verdict"] = ("OK - key, quota, model and network all proven"
                      if out["token"] else
                      "200 but no whitelisted token - model answered junk")
    return out


def main(argv=None) -> int:
    import sys
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--probe" in argv:
        res = probe()
        print("aiassist probe  version=%s" % AI_VERSION)
        for k in ("enabled", "model", "http_code", "latency_ms", "token",
                  "resolved_model", "verdict", "error"):
            print("  %-15s: %s" % (k, res.get(k)))
        return 0 if res.get("token") else 1
    selftest(verbose=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
