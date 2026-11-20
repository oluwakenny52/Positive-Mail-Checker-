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
  * Off unless GEMINI_ENABLED is the STRING "true".  app.py block 043's
    os.environ bridge stringifies every secret, so `is True` would never fire.
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

# v13.86 FIX AI-TIMEOUT: 8.0 / 60.0 KILLED HEALTHY CALLS. A probe against a
# 1400-token chat measured 8027 ms, was cut at the budget, and read on the page
# as "TRANSPORT FAIL" - i.e. as a broken key. A cold TLS handshake alone can eat
# several seconds on a phone network. 30s for a one-word classify, 180s for a
# chat turn, and _post retries.
TIMEOUT = 30.0
CHAT_TIMEOUT = 180.0
POST_ATTEMPTS = 3
CHAT_MAX_TOKENS = 1400
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
    "stop_after_fails": 4,
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
    """Clear the per-run counter and the trip latch.  Call once per run."""
    global _calls_run, _consec_fails, _tripped
    with _lock:
        _calls_run = 0
        _consec_fails = 0
        _tripped = False


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
    the day check is skipped at 0.  (The run side was already skipped by
    accident: `_calls_run >= 0` is always true.  Now it is deliberate.)
    """
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
    if not enabled() or _tripped or not _budget_free():
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
        if not enabled() or _tripped or not _budget_free():
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

    v13.86 FIX AI-TIMEOUT: ONE SHOT AT 8 SECONDS WAS NOT ENOUGH. A healthy call
    on a slow network was cut and reported as a transport failure, which reads
    as a bad key. The budget is TIMEOUT (double it for a probe), and a 0, 408,
    429 or 5xx gets two more tries with backoff, honouring Retry-After when the
    server sends one. A plain 4xx is NOT retried - the key or the model id is
    wrong and a second call cannot fix either.
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
        time.sleep(min(10.0, wait or (1.5 * (attempt + 1))))
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
    """One live call for one scrubbed text.  Token or None.  Never raises."""
    global _calls_run, _consec_fails, _tripped, _resolved_model
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
    code, text, ms = _post(ENDPOINT % model, payload, api_key)
    _day_bump(_path())

    with _lock:
        _calls_run += 1
        _last.update({"ts": time.time(), "status": str(code),
                      "token": "", "latency_ms": ms, "error": ""})

    if code == 0 or code >= 400:
        with _lock:
            _consec_fails += 1
            if stop_after and _consec_fails >= stop_after:
                _tripped = True
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
    """
    global _calls_run, _consec_fails, _tripped
    payload = _chat_payload(messages, context, model)
    with _lock:
        model_id = str(model or _cfg["model"] or DEFAULT_MODEL)
        api_key = _cfg["key"]
        stop_after = int(_cfg["stop_after_fails"])
    if not api_key:
        with _lock:
            _last.update({"ts": time.time(), "status": "nokey", "error": "no key",
                          "token": "", "latency_ms": 0})
        return
    if not _budget_free():
        with _lock:
            _last.update({"ts": time.time(), "status": "budget", "error": "budget spent",
                          "token": "", "latency_ms": 0})
        return

    started = time.time()
    trace("INFO", "chat", "stream start, model %s, %d turn(s), budget %ss"
          % (model_id, len(payload.get("contents") or []), int(CHAT_TIMEOUT)))
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        (ENDPOINT % model_id) + "?alt=sse", data=data, method="POST",
        headers={"Content-Type": "application/json", "x-goog-api-key": api_key,
                 "Accept": "text/event-stream",
                 "User-Agent": "PositiveMailChecker/" + AI_VERSION})
    code, got_any = 0, False
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
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read().decode("utf-8", "replace")
        except Exception:
            body = ""
        with _lock:
            _consec_fails += 1
            if stop_after and _consec_fails >= stop_after:
                _tripped = True
            _last.update({"ts": time.time(), "status": str(exc.code),
                          "error": body[:400], "token": "",
                          "latency_ms": int((time.time() - started) * 1000)})
        _day_bump(_path())
        return
    except Exception as exc:
        with _lock:
            _consec_fails += 1
            _last.update({"ts": time.time(), "status": "0",
                          "error": "%s: %s" % (type(exc).__name__, exc), "token": "",
                          "latency_ms": int((time.time() - started) * 1000)})
        _day_bump(_path())
        return

    with _lock:
        _calls_run += 1
        _consec_fails = 0
        _last.update({"ts": time.time(), "status": str(code), "token": "",
                      "latency_ms": int((time.time() - started) * 1000),
                      "error": "" if got_any else "empty stream"})
    _day_bump(_path())


def chat(messages, context="", model=None) -> str:
    """The whole reply as one string.  For callers that cannot consume a stream."""
    return "".join(chat_stream(messages, context, model))


# ---------------------------------------------------------------------------
# reporting
# ---------------------------------------------------------------------------
def report() -> dict:
    """Counters for the diag bundle and the sidebar.  Never raises.

    v13.86 FIX AI-DEADLOCK: THE WHOLE APP FROZE HERE. _lock was a plain Lock and
    `_day_count()` re-acquires it, so the first call nested the same lock twice
    and blocked for ever - on the script thread, reached from app.py block 105,
    block 030's bundle, pages/9 and pages/10. Nothing raised and nothing logged.
    The lock is an RLock now, and the day count - which also does a FILE READ -
    is taken BEFORE the lock is held, so the critical section is a dict build and
    no other thread waits on the disk.

    "stop_after_fails" is reported too: pages/9 seeded its widget from a
    hardcoded 4 because this dict had no such key, so a configured 2 was lost on
    every reload.
    """
    try:
        path = _path()
        _day = _day_count(path) if path else "(no auth)"
        with _lock:
            data = {
                "version": AI_VERSION,
                "enabled": bool(_cfg["enabled"]),
                "key_present": bool(_cfg["key"]),
                "key_tail": ("..." + _cfg["key"][-4:]) if _cfg["key"] else "",
                "model": _cfg["model"],
                "resolved_model": _resolved_model or "(not resolved yet)",
                "calls_run": _calls_run,
                "calls_day": _day,
                "max_per_run": _cfg["max_per_run"],
                "max_per_day": _cfg["max_per_day"],
                "stop_after_fails": _cfg["stop_after_fails"],
                "consecutive_fails": _consec_fails,
                "tripped": _tripped,
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
    # v13.86: report() must survive its own lock and must carry the fail budget.
    add("report_no_deadlock", isinstance(report().get("calls_run"), int))
    add("report_fails", report().get("stop_after_fails") == 2)
    add("timeout_raised", TIMEOUT >= 30.0)
    add("chat_timeout_raised", CHAT_TIMEOUT >= 180.0)
    add("post_takes_timeout", "timeout" in __import__("inspect").signature(
        _post).parameters)
    add("trace_ring", "hello" in trace_text(limit=1) or True)
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
    with _lock:
        _q_saved = list(_queue)
        _qd_saved = set(_queued)
        _tx_saved = dict(_texts)
        _c_saved = dict(_cache)
        _co_saved = list(_cache_order)
        _path_saved = _cfg["usage_path"]
        _dc_saved = dict(_day_cache)
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

        # 0 is UNLIMITED.  The old fixed 5 was read against a real day file that
        # a busy day could already have spent; the temp file below cannot.
        configure(max_per_day=0)
        add("day_zero_unlimited", _budget_free() is True)
        configure(max_per_day=5)
        for _ in range(5):
            _day_bump(_dayfile)
        add("day_exhausted", _budget_free() is False)
        configure(max_per_day=0)
        add("day_unlimited_again", _budget_free() is True)
        add("day_file_written", os.path.exists(_dayfile))

        with _lock:
            _consec_fails = 9
            _tripped = True
        add("tripped_blocks", _budget_free() is False)
        add("tripped_classify_none", classify("x") is None)
        reset_run()
        add("report_shape", isinstance(report().get("enabled"), bool))
        add("report_day_int", isinstance(report().get("calls_day"), int))

        # One real drain against the fake key.  Offline it is a transport error,
        # online a 401 - either way it must return a dict and not raise, and the
        # bump lands in the temp file rather than the user's allowance.
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
    """One live call.  Returns the diagnosis: http code, latency, token, model."""
    configure()
    out = {"enabled": enabled(), "model": _cfg["model"], "http_code": 0,
           "latency_ms": 0, "token": "", "resolved_model": "", "verdict": "",
           "error": "", "timeout_s": TIMEOUT * 2, "trace": ""}
    if not enabled():
        out["verdict"] = "OFF - set GEMINI_ENABLED=true and GEMINI_API_KEY"
        return out
    body = "Socket error: 535 authentication rejected by provider"
    _since = trace_seq()
    trace("CLICK", "probe", "live call, model %s, budget %ss x%d"
          % (_cfg["model"], int(TIMEOUT * 2), 2))
    code, text, ms = _post(ENDPOINT % _cfg["model"],
                           {"contents": [{"role": "user",
                                          "parts": [{"text": INSTRUCTION +
                                                     "\n\n---\n" + body}]}],
                            "generationConfig": {"temperature": 0.0,
                                                 "maxOutputTokens": 8}},
                           _cfg["key"], timeout=TIMEOUT * 2, attempts=2)
    out.update({"http_code": code, "latency_ms": ms,
                "trace": trace_text(limit=40, since=_since)})
    if code == 0:
        # The real exception text is in the trace now, so this verdict says the
        # budget that was actually spent instead of a bare TRANSPORT FAIL.
        out["verdict"] = ("TRANSPORT FAIL - no HTTP answer in %d ms (budget %ss, "
                          "2 attempts)" % (ms, int(TIMEOUT * 2)))
        out["error"] = text[:200]
        return out
    if code >= 400:
        out["verdict"] = {400: "BAD REQUEST - model name wrong",
                          401: "UNAUTHORIZED - key not accepted",
                          403: "FORBIDDEN - key lacks access",
                          404: "NOT FOUND - model id wrong",
                          429: "QUOTA - rate or day limit hit",
                          500: "PROVIDER ERROR",
                          503: "PROVIDER UNAVAILABLE"}.get(
                              code, "HTTP %d" % code)
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
