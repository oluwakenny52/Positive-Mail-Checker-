# @@FILE pages/9_AI.py blocks=14 version=v13.85
# @@BLOCK 000 FILE_HEADER deps=-
"""
pages/9_AI.py - the UNKNOWN-tail classifier, with its controls in front of you.
===============================================================================
The AI feature had no page, so the only evidence it existed was a sidebar count
and an occasional token. Nothing could be switched on, watched, tested or
cleared without a terminal. This is that page.

WHAT THE FEATURE ACTUALLY DOES
------------------------------
status.classify_error walks a regex table and answers UNKNOWN when nothing
matches. Those strings are server text the app has never seen, so they are the
one place a model earns its cost. aiassist offers a bucket from a CLOSED list for
one such line. It never sets a verdict - the ladder still decides what happens -
it only names a better bucket than UNKNOWN. Everything else stays local.

WHERE IT HOOKS IN
-----------------
  classify()      cache read on the hot path, never blocks, queues a miss
  drain()         the network, off a daemon thread, after the account
  classify_now()  one blocking call for a line you are looking at - THIS page

WHY IT CAN BE OFF AND STILL BE FINE
-----------------------------------
Off unless GEMINI_ENABLED is the string "true" and a key is present. Off, every
classify() returns None, the caller keeps its UNKNOWN, and nothing else changes.
A model failure can never touch a run.

WHAT LEAVES THE BOX
-------------------
Only the scrubbed line: address local-parts become *@domain, a credential pair
becomes host:port, and the text is capped. The scrub is shown under the box so
you can see it before you press anything.

BUDGETS
-------
Per run and per user per day, plus a latch after N consecutive failures. 0 means
UNLIMITED for both. The day counter is a per-user file; the run counter and the
cache are process state. The cache is keyed on the scrubbed text, so two sessions
cannot read each other's numbers.

Read-only except the controls, which only ever touch aiassist's own state.
"""

import importlib
import json
import os
import sys
from datetime import datetime

import streamlit as st
# @@END 000 FILE_HEADER

# @@BLOCK 001 PAGE_CONFIG deps=000
st.set_page_config(page_title="AI Console - Mail Checker",
                   page_icon="\U0001f9e0", layout="wide",
                   initial_sidebar_state="collapsed")
# @@END 001 PAGE_CONFIG

# @@BLOCK 002 SYSPATH deps=000
THIS_DIR = os.path.dirname(os.path.abspath(__file__))
APP_DIR = os.path.dirname(THIS_DIR)
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)
# @@END 002 SYSPATH

# @@BLOCK 003 THEME deps=002
_TH_DEFAULTS = {
    "bg": "#0b1020", "panel": "#141b30", "text": "#e6ebff",
    "accent": "#8b5cf6", "accent2": "#22d3ee", "g1": "#667eea", "g2": "#764ba2",
}


def _theme():
    """The owner's theme when it parses, else the defaults. Never raises."""
    base = dict(_TH_DEFAULTS)
    try:
        import auth
        p = auth.user_file("theme.json")
        if os.path.exists(p):
            with open(p, encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict):
                base.update({k: v for k, v in data.items()
                             if k in base and isinstance(v, str)})
    except Exception:
        pass
    return base


_TH = _theme()
# @@END 003 THEME

# @@BLOCK 004 CSS deps=003
_CSS_TMPL = """
<style>
    .ai-hero {
        background: linear-gradient(135deg, __G1__ 0%, __G2__ 100%);
        padding: 18px 24px; border-radius: 14px; margin-bottom: 14px;
        border: 1px solid rgba(255,255,255,.12);
    }
    .ai-hero h1 { color: #fff !important; margin: 0; font-size: 1.45rem; font-weight: 800; }
    .ai-hero p { color: rgba(255,255,255,.93) !important; margin: 6px 0 0 0; font-size: .84rem; }
    .ai-tok { display:inline-block; padding:2px 9px; border-radius:999px;
              font-size:.72rem; font-weight:800; letter-spacing:.03em; }
    .ai-good { background:#22c55e33; color:#86efac; border:1px solid #22c55e66; }
    .ai-none { background:#64748b33; color:#cbd5e1; border:1px solid #64748b66; }
    .ai-bad  { background:#ef444433; color:#fca5a5; border:1px solid #ef444466; }
    .block-container, [data-testid="stMainBlockContainer"] {
        padding-top: 1.2rem !important; padding-bottom: 2rem !important;
        max-width: 1100px !important;
    }
    @media (max-width: 820px) {
        .block-container, [data-testid="stMainBlockContainer"] {
            padding-top: .55rem !important; padding-left: .7rem !important;
            padding-right: .7rem !important;
        }
        .ai-hero h1 { font-size: 1.15rem !important; }
    }
</style>
"""


def _css():
    return (_CSS_TMPL.replace("__G1__", _TH["g1"])
            .replace("__G2__", _TH["g2"]))


st.markdown(_css(), unsafe_allow_html=True)
# @@END 004 CSS

# @@BLOCK 005 HERO_GATE deps=004
st.markdown(
    '<div class="ai-hero"><h1>\U0001f9e0 AI Console</h1>'
    '<p>The UNKNOWN-tail classifier: what it is on, what it has spent, and one '
    'line you can test on demand. It never sets a verdict - it only offers a '
    'better bucket than UNKNOWN.</p></div>', unsafe_allow_html=True)

import auth

if not hasattr(auth, "fit_panel"):
    auth = importlib.reload(auth)

import audit_log as _audit

if not (hasattr(_audit, "page") and hasattr(_audit, "install")):
    try:
        _audit = importlib.reload(_audit)
    except Exception:
        pass
audit_log = _audit

if hasattr(audit_log, "page"):
    audit_log.page("pages/9_AI.py")

# INSTALL BEFORE require(), exactly as app.py block 007 and every other page do.
if hasattr(audit_log, "install"):
    audit_log.install(st, "pages/9_AI.py")

auth.require(st, "Unlock AI Console")
auth.fit(st)                        # CSS only, before the first widget

auth.fit_panel(st)                  # the controls; collapsed until tapped

# The first theme read ran before the gate, on the anonymous prefix.
_TH = _theme()
st.markdown(_css(), unsafe_allow_html=True)
# @@END 005 HERO_GATE

# @@BLOCK 006 MODULE_STATE deps=005
import aiassist

if not (hasattr(aiassist, "classify_now") and hasattr(aiassist, "report")):
    aiassist = importlib.reload(aiassist)

from auth import user_file

_OWNER_KEY = "_ai_owner"
_LEDGER_KEY = "_ai_ledger"
_SEED_KEY = "_ai_seeded"
_CFG_KEY = "_ai_configured"
_LEDGER_MAX = 200


def _owner():
    try:
        return os.path.basename(user_file("")) or ""
    except Exception:
        return ""


def _clip(value, n=140):
    s = " ".join(str(value if value is not None else "").split())
    return s[:n] + (" ..." if len(s) > n else "")


def _ledger_add(action, line, token, ms, note=""):
    """One row in the session ledger. Never raises."""
    try:
        rows = st.session_state.get(_LEDGER_KEY)
        if not isinstance(rows, list):
            rows = []
        rows.append({"at": datetime.now().strftime("%H:%M:%S"),
                     "action": action, "line": _clip(line), "token": token or "",
                     "ms": int(ms or 0), "note": _clip(note)})
        st.session_state[_LEDGER_KEY] = rows[-_LEDGER_MAX:]
    except Exception:
        pass


def _ledger_rows():
    rows = st.session_state.get(_LEDGER_KEY)
    return rows if isinstance(rows, list) else []


def _ledger_text():
    out = ["at       action   token       ms   line / note"]
    for r in _ledger_rows():
        out.append("%-8s %-8s %-11s %-4s %s%s" % (
            r.get("at"), r.get("action"), r.get("token") or "-", r.get("ms"),
            r.get("line"), ("  [" + r["note"] + "]") if r.get("note") else ""))
    return "\n".join(out) + "\n"


_owner = _owner()
if st.session_state.get(_OWNER_KEY) != _owner:
    st.session_state[_OWNER_KEY] = _owner
    for _k in (_LEDGER_KEY, _SEED_KEY, _CFG_KEY):
        st.session_state.pop(_k, None)

# configure() must run on THIS thread at least once: it is what resolves the
# per-user usage path, and a bare drain thread has no session to resolve it from.
if not st.session_state.get(_CFG_KEY):
    aiassist.configure()
    st.session_state[_CFG_KEY] = True
# @@END 006 MODULE_STATE

# @@BLOCK 007 CONFIG deps=006
try:
    _rep = aiassist.report()
except Exception as e:
    _rep = {"error": "%s: %s" % (type(e).__name__, e)}

if not st.session_state.get(_SEED_KEY):
    st.session_state["_ai_enabled"] = bool(_rep.get("enabled"))
    st.session_state["_ai_model"] = _rep.get("model") or "gemini-flash-latest"
    st.session_state["_ai_run"] = int(_rep.get("max_per_run") or 0)
    st.session_state["_ai_day"] = int(_rep.get("max_per_day") or 0)
    st.session_state["_ai_fails"] = 4
    st.session_state[_SEED_KEY] = True

st.markdown("### 1. Configuration")
st.caption("A budget of 0 means UNLIMITED, not zero calls. The key itself comes "
           "from the deployment secrets (`GEMINI_API_KEY`) and is never typed here.")

_g1, _g2 = st.columns([0.34, 0.66])
with _g1:
    st.checkbox("Enabled", key="_ai_enabled",
                help="Off means every classify() returns None and the caller keeps "
                     "its UNKNOWN. Nothing else changes.")
with _g2:
    st.text_input("Model", key="_ai_model",
                  help="The API model id. `gemini-flash-latest` is the default and "
                       "the cheapest thing that answers a one-word reply.")

_b1, _b2, _b3 = st.columns(3)
with _b1:
    st.number_input("Max per run", 0, 500, step=5, key="_ai_run",
                    help="0 = unlimited. Counts calls inside one run.")
with _b2:
    st.number_input("Max per day", 0, 5000, step=25, key="_ai_day",
                    help="0 = unlimited. This one is per USER, in your own file, "
                         "so another session cannot spend it.")
with _b3:
    st.number_input("Stop after fails", 0, 20, step=1, key="_ai_fails",
                    help="0 = never latch. Consecutive failures only; one success "
                         "clears the count.")

_a1, _a2, _a3 = st.columns(3)
with _a1:
    if st.button("Apply configuration", width="stretch"):
        try:
            aiassist.configure(enabled=bool(st.session_state["_ai_enabled"]),
                               model=st.session_state["_ai_model"],
                               max_per_run=int(st.session_state["_ai_run"]),
                               max_per_day=int(st.session_state["_ai_day"]),
                               stop_after_fails=int(st.session_state["_ai_fails"]))
            st.success("Applied. Key present: %s. Model: %s."
                       % (aiassist.report().get("key_present"),
                          aiassist.report().get("model")))
        except Exception as e:
            st.error("Apply failed: %s: %s" % (type(e).__name__, e))
with _a2:
    if st.button("Reset run counters", width="stretch",
                 help="Clears the per-run count, the consecutive-failure count and "
                      "the latch. The per-DAY count is not touched."):
        aiassist.reset_run()
        st.success("Run counters cleared. The day count is unchanged.")
with _a3:
    if st.button("Clear AI cache", width="stretch",
                 help="Forgets every cached token, so the next classify() misses "
                      "and queues. Does not clear the day count."):
        try:
            with aiassist._lock:
                aiassist._cache.clear()
                aiassist._cache_order.clear()
            st.success("Cache cleared.")
        except Exception as e:
            st.error("Could not clear the cache: %s: %s" % (type(e).__name__, e))
# @@END 007 CONFIG

# @@BLOCK 008 STATUS deps=007
st.markdown("### 2. Status")

if _rep.get("error"):
    st.error("report() failed: %s" % _rep["error"])
else:
    if _rep.get("tripped"):
        st.error("**Latched.** %s consecutive failures. Reset the run counters or "
                 "check the key before spending more."
                 % _rep.get("consecutive_fails"))
    if not _rep.get("enabled"):
        st.warning("**Off.** Set `GEMINI_ENABLED` to the string `true` and add "
                   "`GEMINI_API_KEY` in the deployment secrets, then reload. Off is "
                   "a supported state - nothing else changes.")

    _s = st.columns(4)
    _s[0].metric("Calls this run", _rep.get("calls_run"))
    _s[1].metric("Calls today", _rep.get("calls_day"))
    _s[2].metric("Queued", _rep.get("queue"))
    _s[3].metric("Cached", _rep.get("cache_entries"))

    _t = st.columns(4)
    _t[0].metric("Budget/run", _rep.get("max_per_run"))
    _t[1].metric("Budget/day", _rep.get("max_per_day"))
    _t[2].metric("Consec. fails", _rep.get("consecutive_fails"))
    _t[3].metric("Tripped", "yes" if _rep.get("tripped") else "no")

    st.caption("Key: %s  |  model: `%s`  |  resolved: `%s`  |  last status: %s  |  "
               "last latency: %s ms  |  last token: %s"
               % ("present " + (_rep.get("key_tail") or "") if _rep.get("key_present")
                  else "MISSING", _rep.get("model"), _rep.get("resolved_model"),
                  _rep.get("last_status") or "-", _rep.get("last_latency_ms"),
                  _rep.get("last_token") or "-"))
    if _rep.get("last_error"):
        st.caption("last error: `%s`" % _clip(_rep.get("last_error"), 300))
# @@END 008 STATUS

# @@BLOCK 009 CLASSIFY_NOW deps=008
st.markdown("### 3. Classify one line now")
st.caption("This is the blocking tier: one call, right now, for a line you are "
           "looking at. A cached answer is served without a call.")

_line = st.text_area("Raw server or proxy line", height=120, key="_ai_line",
                     placeholder="550 5.7.1 bob@example.com rejected by policy")

_scrubbed = ""
try:
    _scrubbed = aiassist._scrub(_line)
except Exception:
    pass
if _line:
    st.caption("Leaves the box as: `%s`" % (_scrubbed or "(nothing)"))
    if _scrubbed != _line:
        st.caption("Changed before sending - address local-parts and credentials "
                   "are stripped, the domain is kept because it is the signal.")

_n1, _n2 = st.columns(2)
with _n1:
    _do_now = st.button("\U0001f9e0 Classify now", type="primary",
                        disabled=not (_line or "").strip(), width="stretch")
with _n2:
    _do_queue = st.button("\U0001f4e5 Queue it instead", width="stretch",
                          disabled=not (_line or "").strip(),
                          help="No call now. The next drain() picks it up.")

if _do_now:
    _started = datetime.now()
    try:
        _tok = aiassist.classify_now(_line)
    except Exception as e:
        _tok = None
        st.error("classify_now raised: %s: %s" % (type(e).__name__, e))
        _ledger_add("now", _line, "", 0, "raised %s" % type(e).__name__)
    _ms = int((datetime.now() - _started).total_seconds() * 1000)
    if _tok:
        st.markdown('<span class="ai-tok ai-good">%s</span>' % _tok,
                    unsafe_allow_html=True)
        _ledger_add("now", _line, _tok, _ms, "ok")
    else:
        st.markdown('<span class="ai-tok ai-none">None</span>', unsafe_allow_html=True)
        _why = []
        if not _rep.get("enabled"):
            _why.append("disabled or no key")
        if _rep.get("tripped"):
            _why.append("latched after failures")
        if _rep.get("last_error"):
            _why.append("last error: " + _clip(_rep.get("last_error"), 90))
        if not _why:
            _why.append("no budget left, empty line, or a reply outside the whitelist")
        st.caption("No token. " + "; ".join(_why) + ".")
        _ledger_add("now", _line, "", _ms, "; ".join(_why))

if _do_queue:
    try:
        _ok = aiassist.enqueue(_line)
        if _ok:
            st.success("Queued. Press Drain below, or leave it for the app's own "
                       "drain after a run.")
            _ledger_add("queue", _line, "", 0, "queued")
        else:
            st.info("Not queued - already cached, already queued, off, or the "
                    "queue is full.")
            _ledger_add("queue", _line, "", 0, "rejected")
    except Exception as e:
        st.error("enqueue raised: %s: %s" % (type(e).__name__, e))
# @@END 009 CLASSIFY_NOW

# @@BLOCK 010 QUEUE_DRAIN deps=009
st.markdown("### 4. Queue")
st.caption("The app fills this after each account and drains it off a thread. "
           "Here you can drain it by hand.")

_q1, _q2 = st.columns([0.4, 0.6])
with _q1:
    _limit = st.number_input("Drain up to", 1, 50, 5, 1, key="_ai_drain",
                             help="Calls spent by this press.")
with _q2:
    st.metric("Waiting", aiassist.pending())

if st.button("\u25b6 Drain now", disabled=not aiassist.pending(), width="stretch"):
    try:
        _res = aiassist.drain(limit=int(_limit))
        st.success("tried %s, got %s, skipped %s"
                   % (_res.get("tried"), _res.get("got"), _res.get("skipped")))
        _ledger_add("drain", "limit=%s" % _limit, "", 0,
                    "tried %s got %s" % (_res.get("tried"), _res.get("got")))
    except Exception as e:
        st.error("drain raised: %s: %s" % (type(e).__name__, e))
        _ledger_add("drain", "limit=%s" % _limit, "", 0, "raised %s" % type(e).__name__)
# @@END 010 QUEUE_DRAIN

# @@BLOCK 011 PROBE deps=010
st.markdown("### 5. Live probe")
st.caption("One fixed line, one real call. This is the only tier that proves the "
           "key, the quota and the model together - a 200 with no token means the "
           "model answered something outside the whitelist.")

if st.button("\U0001f50c Probe the endpoint", width="stretch"):
    try:
        _p = aiassist.probe()
    except Exception as e:
        _p = {"verdict": "probe raised: %s: %s" % (type(e).__name__, e)}
    _ledger_add("probe", "fixed line", _p.get("token") or "", _p.get("latency_ms"),
                _clip(_p.get("verdict"), 80))
    if _p.get("token"):
        st.success(_p.get("verdict"))
    else:
        st.warning(_p.get("verdict"))
    st.caption("http %s  |  latency %s ms  |  model `%s`  |  resolved `%s`"
               % (_p.get("http_code"), _p.get("latency_ms"), _p.get("model"),
                  _p.get("resolved_model") or "-"))
    if _p.get("error"):
        st.caption("error: `%s`" % _clip(_p.get("error"), 300))
# @@END 011 PROBE

# @@BLOCK 012 LEDGER deps=011
st.markdown("---")
st.markdown("### 6. Session ledger")
st.caption("Everything this page did in this session, newest last. Cleared when "
           "the owner changes.")

_rows = _ledger_rows()
if not _rows:
    st.caption("Nothing yet.")
else:
    st.dataframe([{"at": r.get("at"), "action": r.get("action"),
                   "token": r.get("token") or "-", "ms": r.get("ms"),
                   "line": r.get("line"), "note": r.get("note")}
                  for r in reversed(_rows)], width="stretch", height=240)
    _l1, _l2 = st.columns(2)
    with _l1:
        st.download_button("\u2b07 Download ledger",
                           data=_ledger_text().encode("utf-8"),
                           file_name="ai_ledger_%s.log"
                                     % datetime.now().strftime("%Y%m%d_%H%M%S"),
                           mime="text/plain", width="stretch")
    with _l2:
        if st.button("Clear ledger", width="stretch"):
            st.session_state[_LEDGER_KEY] = []
            st.rerun()
# @@END 012 LEDGER

# @@BLOCK 013 FOOTER deps=012
st.markdown("---")
_f1, _f2, _f3 = st.columns(3)
with _f1:
    try:
        st.page_link("app.py", label="\u26a1 Checker", width="stretch")
    except Exception:
        st.caption("Checker lives at app.py")
with _f2:
    try:
        st.page_link("pages/2_Diagnostics.py", label="\U0001f50d Diagnostics",
                     width="stretch")
    except Exception:
        st.caption("Diagnostics lives at pages/2_Diagnostics.py")
with _f3:
    try:
        st.page_link("pages/10_Debug.py", label="\U0001f41e Debugging",
                     width="stretch")
    except Exception:
        st.caption("Debugging lives at pages/10_Debug.py")

st.caption("The classifier never sets a verdict. It names a better bucket than "
           "UNKNOWN and the existing ladder still decides. Off by default; with no "
           "key every call returns None and nothing else changes.")
# @@END 013 FOOTER
# @@EOF
