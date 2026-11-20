# @@FILE pages/9_AI.py blocks=16 version=v13.86
# @@BLOCK 000 FILE_HEADER deps=-
"""
pages/9_AI.py - ask about the app, and classify the UNKNOWN tail.
=================================================================
TWO JOBS, ONE KEY, DELIBERATELY SEPARATE
----------------------------------------
  chat          free-form. Ask about the app, paste a traceback, have a block
                drafted. It reads the block index, the page list and one
                attached file, and it points at the block it means.
  classify      the UNKNOWN tail only. status.classify_error runs a regex table
                first and only a miss reaches a model, which may name one bucket
                from a CLOSED list. Never a verdict - the ladder still decides.

WHERE THE CLASSIFIER HOOKS IN
-----------------------------
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
Chat: the prompt, the context you ticked, and the reply request.
Classify: the scrubbed line only.

With Scrub on (default) both go through the same two masks - an address
local-part becomes *@domain, a credential pair collapses to host:port. Chat
keeps its newlines, because a block index and a traceback are structure; the
classifier folds whitespace and caps at 600 characters, because it gets one
server line. The classified line is shown scrubbed under the box before you
press anything.

THE RECORD
----------
Every chat turn is appended to ai_chat.jsonl under the user's own prefix, capped
at 300 turns, downloadable and clearable. It survives a reload; the session copy
is only what renders.

BUDGETS
-------
Per run and per user per day, plus a latch after N consecutive failures. 0 means
UNLIMITED for both. Chat and classification SHARE both counters - a chat turn is
a real call on the same key. The day counter is a per-user file; the run counter
and the cache are process state. The cache is keyed on the scrubbed text, so two
sessions cannot read each other's numbers.

Read-only except the controls and the record file.
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
    '<p>Two jobs: ask anything about the app and keep the thread, or classify one '
    'raw line. It never sets a verdict - it names a better bucket than UNKNOWN, '
    'and the ladder still decides.</p></div>', unsafe_allow_html=True)

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

if not (hasattr(aiassist, "classify_now") and hasattr(aiassist, "report")
        and hasattr(aiassist, "chat_stream")):
    aiassist = importlib.reload(aiassist)

from auth import user_file

_OWNER_KEY = "_ai_owner"
_LEDGER_KEY = "_ai_ledger"
_SEED_KEY = "_ai_seeded"
_CFG_KEY = "_ai_configured"
_LEDGER_MAX = 200

_CHAT_NAME = "ai_chat.jsonl"
_CHAT_MAX = 300
_CHAT_KEY = "_ai_chat"
_CHAT_TURNS = 24          # turns replayed to the model; the file keeps all of them


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


# ---- the conversation record -------------------------------------------------
# A per-user JSONL file, like every other durable thing on this app. One object
# per line. It is a RECORD, not state: the session copy is what renders, the
# file is what survives a reload and what the download button exports.
def _chat_path():
    try:
        return user_file(_CHAT_NAME)
    except Exception:
        return _CHAT_NAME


def _chat_load():
    p = _chat_path()
    out = []
    if not p or not os.path.exists(p):
        return out
    try:
        with open(p, encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                if isinstance(r, dict) and r.get("text") and r.get("role") in (
                        "user", "assistant"):
                    out.append(r)
    except Exception:
        return out
    return out[-_CHAT_MAX:]


def _chat_append(role, text):
    """Append one turn and trim the file. Never raises."""
    p = _chat_path()
    if not p:
        return
    try:
        os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
        with open(p, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                 "role": role, "text": str(text)},
                                ensure_ascii=False) + "\n")
        with open(p, encoding="utf-8", errors="ignore") as fh:
            lines = fh.readlines()
        if len(lines) > _CHAT_MAX:
            with open(p, "w", encoding="utf-8") as fh:
                fh.writelines(lines[-_CHAT_MAX:])
    except Exception:
        pass


def _chat_clear():
    p = _chat_path()
    try:
        if p and os.path.exists(p):
            os.remove(p)
    except Exception:
        pass


def _chat_text():
    rows = st.session_state.get(_CHAT_KEY) or []
    out = []
    for r in rows:
        out.append("[%s] %s\n%s\n" % (r.get("at", ""),
                                      str(r.get("role", "")).upper(),
                                      r.get("text", "")))
    return "\n".join(out) or "(empty)\n"


# ---- context the model may be given -----------------------------------------
def _build_tag():
    try:
        with open(os.path.join(APP_DIR, "app.py"), encoding="utf-8",
                  errors="ignore") as fh:
            first = fh.readline()
        return first.split("version=")[-1].strip() or "v13.86"
    except Exception:
        return "v13.86"


def _block_index():
    """Every @@BLOCK id and name in app.py. One read, no exec, no import."""
    out = []
    try:
        with open(os.path.join(APP_DIR, "app.py"), encoding="utf-8",
                  errors="ignore") as fh:
            for line in fh:
                if line.startswith("# @@BLOCK"):
                    bits = line.split()
                    out.append("%s %s" % (bits[2], " ".join(bits[3:])))
    except Exception:
        pass
    return out


def _py_files():
    out = ["app.py"]
    try:
        for n in sorted(os.listdir(os.path.join(APP_DIR, "pages"))):
            if n.endswith(".py"):
                out.append("pages/" + n)
    except Exception:
        pass
    try:
        for n in sorted(os.listdir(APP_DIR)):
            if n.endswith(".py") and n not in out and n not in ("app.py",):
                out.append(n)
    except Exception:
        pass
    return out


def _file_text(rel, cap=14000):
    try:
        with open(os.path.join(APP_DIR, rel), encoding="utf-8", errors="ignore") as fh:
            return fh.read()[:cap]
    except Exception as e:
        return "(could not read %s: %s)" % (rel, e)


def _light_scrub(text, cap=24000):
    """Mask addresses and credentials but KEEP the whitespace.

    aiassist._scrub() collapses whitespace runs and caps at 600 characters -
    right for one server line, wrong for a block index or a pasted traceback,
    where the newlines are the signal. Same two patterns, no folding, own cap.
    """
    t = str(text or "")
    try:
        t = aiassist._CRED_RE.sub(lambda m: m.group(3), t)
        t = aiassist._EMAIL_RE.sub(lambda m: "*@" + m.group(2), t)
    except Exception:
        pass
    return t[:cap]


def _ctx_pack(blocks=True, pages=True, one_file="", counters=True):
    """Assemble the context string. Every part is optional. Never raises."""
    parts = ["build: %s" % _build_tag(), "app root: %s" % APP_DIR]
    if pages:
        parts.append("pages:\n" + "\n".join("  " + n for n in _py_files()))
    if blocks:
        parts.append("app.py blocks (id + name, in execution order):\n"
                     + "\n".join("  " + b for b in _block_index()))
    if counters:
        try:
            rep = aiassist.report()
            parts.append("ai counters: " + json.dumps(
                {k: rep.get(k) for k in ("enabled", "model", "calls_run", "calls_day",
                                         "max_per_run", "max_per_day", "tripped",
                                         "cache_entries", "queue")}))
        except Exception:
            pass
    if one_file:
        parts.append("FILE %s:\n%s" % (one_file, _file_text(one_file)))
    return "\n\n".join(parts)


_owner = _owner()
if st.session_state.get(_OWNER_KEY) != _owner:
    st.session_state[_OWNER_KEY] = _owner
    for _k in (_LEDGER_KEY, _SEED_KEY, _CFG_KEY, _CHAT_KEY, "_ai_chat_seeded",
               "_ai_model_applied", "_ai_prompt", "_ai_ctx_file", "_ai_send",
               "_ai_queued"):
        st.session_state.pop(_k, None)
    st.session_state[_CHAT_KEY] = _chat_load()

# configure() must run on THIS thread at least once: it is what resolves the
# per-user usage path, and a bare drain thread has no session to resolve it from.
if not st.session_state.get(_CFG_KEY):
    aiassist.configure()
    st.session_state[_CFG_KEY] = True
# @@END 006 MODULE_STATE

# @@BLOCK 007 DESCRIPTION deps=006
st.markdown("### 1. What this console can do, and how it works")

_d_open = bool(st.session_state.pop("_ai_desc_done", True))
st.session_state["_ai_desc_done"] = False
with st.expander("📖 Read this once - what the AI is for, how to use it, what it "
                 "costs, what leaves the box", expanded=_d_open):
    st.markdown(
        "**Two separate jobs, one key.**\n\n"
        "1. **Classify** a raw server or proxy line that the local regex table "
        "could not name. The app calls this automatically for its UNKNOWN tail; "
        "sections 5-7 let you drive it by hand.\n"
        "2. **Ask** about the app itself - section 2. This is a normal "
        "conversation: it can read the block index, the page list and any one "
        "file you attach, and it will point at the block it means.\n\n"
        "**How to use the chat**\n\n"
        "Type a question, pick a model, attach context if the answer needs it, "
        "press Ask. Follow-ups keep the thread. Every turn is written to "
        "`ai_chat.jsonl` under your own prefix, so it survives a reload and can "
        "be downloaded or cleared. Nothing is shared with another user.\n\n"
        "**What it can actually do for you**\n\n"
        "- name the block, file and function behind a symptom you describe\n"
        "- explain what a block does and what breaks if it is replaced\n"
        "- read a traceback or a log you paste and say which line raised\n"
        "- draft a whole replacement block, in this file's @@BLOCK frame\n"
        "- tell you where a setting lives, or that it does not exist\n\n"
        "**What it cannot do**\n\n"
        "- run anything, edit a file, or restart the app\n"
        "- see a file you have not attached, or a page you have not described\n"
        "- know anything about your mailbox, your results or another session\n"
        "- set a verdict - the classifier only ever names a bucket, and the "
        "ladder still decides\n\n"
        "**What leaves the box**\n\n"
        "Your prompt, the context you ticked, and the reply request. With "
        "*Scrub* on (default), address local-parts become `*@domain` and a "
        "credential pair collapses to `host:port` before anything is sent. "
        "Attached code is sent verbatim apart from that.\n\n"
        "**How the classifier half works**\n\n"
        "A closed whitelist of nine tokens; anything else becomes `None` and the "
        "caller keeps its UNKNOWN. Answers are cached on the scrubbed text, so "
        "the same BYE line costs one call and not thousands. Misses are queued "
        "and drained off a thread, never on the hot path. Two budgets - per run "
        "and per user per day, both `0 = unlimited` - and a latch after N "
        "consecutive failures. The lock is reentrant because `report()` reads the "
        "day count inside it.\n\n"
        "**Requirements.** `GEMINI_ENABLED=true` and `GEMINI_API_KEY` in the "
        "deployment secrets. Off is a supported state: every call returns `None` "
        "and nothing else changes. The key is never typed on this page."
    )
# @@END 007 DESCRIPTION

# @@BLOCK 008 CHAT deps=006,007
st.markdown("### 2. Ask the console")
st.caption("Ask about the app, paste a traceback, or have a block drafted. "
           "Follow-ups keep the thread. Every turn is recorded to your own file.")

_repc = aiassist.report()
if not st.session_state.get("_ai_chat_seeded"):
    st.session_state["_ai_chat_model"] = _repc.get("model") or "gemini-flash-latest"
    st.session_state["_ai_chat_seeded"] = True
if _CHAT_KEY not in st.session_state:
    st.session_state[_CHAT_KEY] = _chat_load()

_MODELS = ("gemini-flash-latest", "gemini-2.5-flash", "gemini-2.5-pro",
           "gemini-2.0-flash")

_cm1, _cm2 = st.columns([0.42, 0.58])
with _cm1:
    _model = st.selectbox("Model", options=[st.session_state["_ai_chat_model"]]
                          + [m for m in _MODELS
                             if m != st.session_state["_ai_chat_model"]],
                          key="_ai_chat_model")
with _cm2:
    st.caption("Budget: **%s** of %s today, **%s** of %s this run (0 = unlimited). "
               "Chat and classification share both."
               % (_repc.get("calls_day"), _repc.get("max_per_day") or "unlimited",
                  _repc.get("calls_run"), _repc.get("max_per_run") or "unlimited"))

# A model change is a configure() - and configure() resets any argument left
# None back to the environment, so every UI-owned value is passed with it.
if st.session_state.get("_ai_model_applied") != _model:
    aiassist.configure(enabled=st.session_state.get("_ai_enabled"),
                       model=_model,
                       max_per_run=st.session_state.get("_ai_run"),
                       max_per_day=st.session_state.get("_ai_day"),
                       stop_after_fails=st.session_state.get("_ai_fails"))
    st.session_state["_ai_model_applied"] = _model

with st.expander("Context to attach", expanded=False):
    st.caption("The model sees only what is ticked here plus the thread. Ticking "
               "nothing still works - it just has to ask you.")
    _ctx_blocks = st.checkbox("Block index of app.py", value=True, key="_ai_ctx_blocks")
    _ctx_pages = st.checkbox("Page and module list", value=True, key="_ai_ctx_pages")
    _ctx_counters = st.checkbox("AI counters", value=True, key="_ai_ctx_counters")
    _ctx_opts = ["(none)"] + _py_files()
    if st.session_state.get("_ai_ctx_file") not in _ctx_opts:
        st.session_state["_ai_ctx_file"] = "(none)"
    _ctx_file = st.selectbox("Attach one file in full", options=_ctx_opts,
                             key="_ai_ctx_file")
    _scrub_on = st.checkbox("Scrub addresses and credentials before sending",
                            value=True, key="_ai_scrub",
                            help="Address local-parts become *@domain and a "
                                 "credential pair becomes host:port. Turn it off if "
                                 "you need the model to see an exact string.")

_chat = st.session_state.get(_CHAT_KEY) or []
if not _chat:
    st.caption("No turns yet. Try: *which block renders the header, and in what "
               "order?* or paste a traceback and ask which line raised.")
else:
    st.caption("%d turn(s) recorded. Showing all of them." % len(_chat))
    for _t in _chat:
        with st.chat_message("user" if _t.get("role") == "user" else "assistant"):
            st.markdown(_t.get("text") or "")


def _ai_on_ask():
    """Ask. A callback runs BEFORE the widgets, so it may clear the key."""
    _q0 = (st.session_state.get("_ai_prompt") or "").strip()
    if not _q0:
        return
    st.session_state["_ai_queued"] = _q0
    st.session_state["_ai_prompt"] = ""
    st.session_state["_ai_send"] = True


def _ai_on_new():
    """New conversation - same reason the clear lives in a callback."""
    _chat_clear()
    st.session_state[_CHAT_KEY] = []
    st.session_state["_ai_prompt"] = ""
    st.session_state["_ai_send"] = False
    st.session_state["_ai_queued"] = ""


_prompt = st.text_area("Your question", key="_ai_prompt", height=110,
                       placeholder="Why does the Breach page crash at line 386?")
_q1, _q2, _q3 = st.columns([0.5, 0.25, 0.25])
with _q1:
    st.button("🧠 Ask", type="primary", width="stretch", on_click=_ai_on_ask,
              disabled=not (_prompt or "").strip())
with _q2:
    st.button("✚ New conversation", width="stretch", on_click=_ai_on_new,
              help="Clears this thread from the screen AND your record file.")
with _q3:
    st.download_button("⬇ Export thread", data=_chat_text().encode("utf-8"),
                       file_name="ai_chat_%s.txt"
                                 % datetime.now().strftime("%Y%m%d_%H%M%S"),
                       mime="text/plain", width="stretch", disabled=not _chat)

if st.session_state.pop("_ai_send", False):
    _q = st.session_state.pop("_ai_queued", "") or ""
    if _q:
        _ctx = _ctx_pack(blocks=_ctx_blocks, pages=_ctx_pages,
                         one_file="" if _ctx_file == "(none)" else _ctx_file,
                         counters=_ctx_counters)
        if _scrub_on:
            _ctx = _light_scrub(_ctx, 24000)
            _q = _light_scrub(_q, 8000)
        _now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        _chat = list(st.session_state.get(_CHAT_KEY) or [])
        _chat.append({"role": "user", "text": _q, "at": _now})
        st.session_state[_CHAT_KEY] = _chat
        _chat_append("user", _q)

        _buf = ""
        with st.chat_message("user"):
            st.markdown(_q)
        with st.chat_message("assistant"):
            _slot = st.empty()
            try:
                for _d in aiassist.chat_stream(_chat[-_CHAT_TURNS:], _ctx, model=_model):
                    _buf += _d
                    _slot.markdown(_buf + " ▌")
            except Exception as e:
                _buf = _buf or "_stream raised: %s: %s_" % (type(e).__name__, e)
            if _buf:
                _slot.markdown(_buf)
            else:
                _rep2 = aiassist.report()
                _why = _rep2.get("last_error") or "no answer"
                if not _rep2.get("key_present"):
                    _why = "no key - set GEMINI_ENABLED=true and GEMINI_API_KEY"
                elif not _rep2.get("enabled"):
                    _why = "the classifier is off - tick Enabled in section 3"
                elif _rep2.get("tripped"):
                    _why = "latched after %s consecutive failures" % _rep2.get(
                        "consecutive_fails")
                _slot.markdown("_no answer: %s_" % _why)
                _buf = "_no answer: %s_" % _why

        _chat.append({"role": "assistant", "text": _buf,
                      "at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
        st.session_state[_CHAT_KEY] = _chat
        _chat_append("assistant", _buf)
        _ledger_add("chat", _q, "", 0, "%d chars back, model %s" % (len(_buf), _model))
        st.rerun()
# @@END 008 CHAT

# @@BLOCK 009 CONFIG deps=008
try:
    _rep = aiassist.report()
except Exception as e:
    _rep = {"error": "%s: %s" % (type(e).__name__, e)}

if not st.session_state.get(_SEED_KEY):
    st.session_state["_ai_enabled"] = bool(_rep.get("enabled"))
    st.session_state["_ai_model"] = _rep.get("model") or "gemini-flash-latest"
    st.session_state["_ai_run"] = int(_rep.get("max_per_run") or 0)
    st.session_state["_ai_day"] = int(_rep.get("max_per_day") or 0)
    # v13.86 FIX AI-SEED: THIS WAS A HARDCODED 4. report() had no such key, so the
    # page always opened on 4 no matter what configure() had been given - and a
    # user who set 2 and reloaded saw 4 again, then saved 4 back over it. The key
    # exists in report() now and the seed is clamped to the widget's own range.
    try:
        _fails_seed = int(_rep.get("stop_after_fails") or 4)
    except Exception:
        _fails_seed = 4
    st.session_state["_ai_fails"] = max(0, min(20, _fails_seed))
    st.session_state[_SEED_KEY] = True

st.markdown("### 3. Configuration")
st.caption("A budget of 0 means UNLIMITED, not zero calls. The key itself comes "
           "from the deployment secrets (`GEMINI_API_KEY`) and is never typed here.")

_g1, _g2 = st.columns([0.34, 0.66])
with _g1:
    st.checkbox("Enabled", key="_ai_enabled",
                help="Off means every classify() returns None and the caller keeps "
                     "its UNKNOWN. Nothing else changes.")
    if not _rep.get("key_present"):
        st.caption("⬆ Ticked but inert: no `GEMINI_API_KEY` is set, so every call "
                   "still returns None.")
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
# @@END 009 CONFIG

# @@BLOCK 010 STATUS deps=009
st.markdown("### 4. Status")

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
# @@END 010 STATUS

# @@BLOCK 011 CLASSIFY_NOW deps=010
st.markdown("### 5. Classify one line now")
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
# @@END 011 CLASSIFY_NOW

# @@BLOCK 012 QUEUE_DRAIN deps=011
st.markdown("### 6. Queue")
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
# @@END 012 QUEUE_DRAIN

# @@BLOCK 013 PROBE deps=012
st.markdown("### 7. Live probe")
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
    if _p.get("trace"):
        with st.expander("Attempts for this probe", expanded=not _p.get("token")):
            st.code(_p["trace"], language="text")
# @@END 013 PROBE

# @@BLOCK 014 LEDGER deps=013
st.markdown("---")
st.markdown("### 8. Call trace")
st.caption("Every attempt, its status and its latency, newest last. Budget: **%ss** "
           "for a classify and a **%ss** probe, %d attempts with backoff. A 4xx is "
           "not retried. Cleared when the owner changes."
           % (int(aiassist.TIMEOUT), int(aiassist.TIMEOUT * 2),
              int(getattr(aiassist, "POST_ATTEMPTS", 3))))

if not st.session_state.get("_ai_trace_seeded"):
    aiassist.trace_clear()
    st.session_state["_ai_trace_seeded"] = True

_tev = aiassist.trace_read(limit=200)
if not _tev:
    st.caption("Nothing traced yet - press Probe in section 7, or Classify now in "
               "section 5.")
else:
    st.code(aiassist.trace_text(limit=200), language="text")

_tr1, _tr2 = st.columns(2)
with _tr1:
    st.download_button("\u2b07 Download trace",
                       data=(aiassist.trace_text(limit=200) + "\n").encode("utf-8"),
                       file_name="ai_trace_%s.log"
                                 % datetime.now().strftime("%Y%m%d_%H%M%S"),
                       mime="text/plain", width="stretch")
with _tr2:
    if st.button("Clear trace", width="stretch"):
        aiassist.trace_clear()
        st.rerun()

st.markdown("---")
st.markdown("### 9. Session ledger")
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
# @@END 014 LEDGER

# @@BLOCK 015 FOOTER deps=014
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
# @@END 015 FOOTER
# @@EOF
