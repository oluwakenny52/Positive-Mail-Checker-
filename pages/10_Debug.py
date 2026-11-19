# @@FILE pages/10_Debug.py blocks=15 version=v13.86
# @@BLOCK 000 FILE_HEADER deps=-
"""
pages/10_Debug.py - one screen that answers "what state is this actually in".
==============================================================================
Every fault this project has shipped was diagnosed from logs and screenshots
after the fact. The information needed was always spread across five files, the
session, the filesystem and the frame. This page puts it on one screen so a
report can be read instead of reconstructed.

WHAT IS ON IT
-------------
  identity    which per-user prefix is live, and whether it is the real one
  versions    every module's own version string, beside the app's
  imports     each module imported, or the exact exception that stopped it
  frame       target against found, per file, with faults quoted by line
  contract    audit_frame's verifier-conformance check
  session     the live session-state keys, with anything secret masked
  gates       the eighteen commands, in order, ready to copy
  bundle      all of the above as one JSON download

WHAT IT DOES NOT DO
-------------------
It renders and it reads. It never edits a file, never runs a gate, and never
touches another user's data - every path shown comes from auth.user_file().

app.py IS READ, NOT IMPORTED
----------------------------
Importing app.py executes the whole shell, so every widget in the app would
render a second time inside this page and the load would double. The version is
taken from line 1 of the file instead, which is the only authority anyway.

WHY THE IDENTITY PANEL MATTERS
------------------------------
auth._anon_id() is the pre-unlock placeholder and it is NOT the identity. A page
that probed with it reported a directory as possibly shared on every unlocked
session. The owner below is derived from auth.user_file(""), which is the same
source every per-user write uses, so if the two ever disagree the panel says so.

Read-only.
"""

import importlib
import json
import os
import platform
import sys
from datetime import datetime

import streamlit as st
# @@END 000 FILE_HEADER

# @@BLOCK 001 PAGE_CONFIG deps=000
st.set_page_config(page_title="Debugging - Mail Checker",
                   page_icon="\U0001f41e", layout="wide",
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
    .db-hero {
        background: linear-gradient(135deg, __G1__ 0%, __G2__ 100%);
        padding: 18px 24px; border-radius: 14px; margin-bottom: 14px;
        border: 1px solid rgba(255,255,255,.12);
    }
    .db-hero h1 { color: #fff !important; margin: 0; font-size: 1.45rem; font-weight: 800; }
    .db-hero p { color: rgba(255,255,255,.93) !important; margin: 6px 0 0 0; font-size: .84rem; }
    .block-container, [data-testid="stMainBlockContainer"] {
        padding-top: 1.2rem !important; padding-bottom: 2rem !important;
        max-width: 1150px !important;
    }
    @media (max-width: 820px) {
        .block-container, [data-testid="stMainBlockContainer"] {
            padding-top: .55rem !important; padding-left: .7rem !important;
            padding-right: .7rem !important;
        }
        .db-hero h1 { font-size: 1.15rem !important; }
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
    '<div class="db-hero"><h1>\U0001f41e Debugging</h1>'
    '<p>Identity, versions, imports, frame, session and gates on one screen. '
    'Read-only - it renders and reads, never edits.</p></div>', unsafe_allow_html=True)

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
    audit_log.page("pages/10_Debug.py")

# INSTALL BEFORE require(), exactly as app.py block 007 and every other page do.
if hasattr(audit_log, "install"):
    audit_log.install(st, "pages/10_Debug.py")

auth.require(st, "Unlock Debugging")
auth.fit(st)                        # CSS only, before the first widget

auth.fit_panel(st)                  # the controls; collapsed until tapped

# The first theme read ran before the gate, on the anonymous prefix.
_TH = _theme()
st.markdown(_css(), unsafe_allow_html=True)
# @@END 005 HERO_GATE

# @@BLOCK 006 IDENTITY deps=005
_SECRET_HINTS = ("key", "pass", "secret", "token", "cookie", "hash")


def _mask(name, value, n=90):
    """Clip a value, and blank it entirely when the name looks secret."""
    s = " ".join(str(value).split())
    low = str(name or "").lower()
    if any(h in low for h in _SECRET_HINTS) and len(s) > 12:
        return "<masked, %d chars>" % len(s)
    return s[:n] + (" ..." if len(s) > n else "")


def _owner():
    """The live per-user prefix, derived the same way every write derives it."""
    try:
        return os.path.basename(auth.user_file("")) or ""
    except Exception as e:
        return "UNRESOLVED (%s)" % type(e).__name__


st.markdown("### 1. Identity")
_owner_id = _owner()
_anon = ""
try:
    _anon = str(auth._anon_id()) if hasattr(auth, "_anon_id") else ""
except Exception:
    _anon = ""

_i1, _i2 = st.columns([0.5, 0.5])
_i1.metric("Owner prefix", _owner_id or "(empty)")
_i2.metric("Anon placeholder", _anon or "(none)")
if _anon and _owner_id and _anon == _owner_id:
    st.warning("The owner equals the anonymous placeholder. Either this session is "
               "not unlocked, or a page is probing with the wrong source.")
else:
    st.caption("The owner is derived from `auth.user_file(\"\")`, which is the same "
               "source every per-user write uses. The anonymous placeholder is only "
               "correct BEFORE an unlock.")

st.caption("Python %s  |  %s  |  streamlit %s"
           % (platform.python_version(), platform.system(),
              getattr(__import__("streamlit"), "__version__", "?")))
# @@END 006 IDENTITY

# @@BLOCK 007 VERSIONS deps=006
st.markdown("### 2. Versions")

# app.py is NOT in this tuple: importing it runs the whole shell. Its version is
# read from line 1 below instead, which is the only authority anyway.
_MODULES = ("auth", "engine", "status", "aiassist", "hosts", "ms_oauth",
            "audit_log", "notify", "mailsearch", "mailview", "mailsort",
            "runstate", "sentinel", "breach", "verify_blocks", "audit_frame",
            "verify_v1337", "fix_end_names")

_APP_TAG = ""
try:
    with open(os.path.join(APP_DIR, "app.py"), encoding="utf-8") as _fh:
        _first = _fh.readline().strip()
    if "version=" in _first:
        _APP_TAG = _first.split("version=", 1)[1].split()[0]
except Exception:
    pass

st.caption("app.py header: `%s`. A module version behind it is drift, not a "
           "failure - but it names a build that no longer exists."
           % (_APP_TAG or "unreadable"))

_v_rows = []
for _m in _MODULES:
    _v = ""
    _err = ""
    try:
        _mod = importlib.import_module(_m)
        _v = str(getattr(_mod, "__version__", "")
                 or getattr(_mod, "BREACH_VERSION", "")
                 or getattr(_mod, "AI_VERSION", "")
                 or getattr(_mod, "STATUS_VERSION", "") or "")
    except Exception as e:
        _err = "%s: %s" % (type(e).__name__, e)
    _v_rows.append({"module": _m, "version": _v or "-", "import_error": _err or ""})
st.dataframe(_v_rows, width="stretch", height=300)
# @@END 007 VERSIONS

# @@BLOCK 008 IMPORTS deps=007
st.markdown("### 3. Imports")
st.caption("Every module the app needs, imported here. A missing package shows the "
           "exact exception rather than a page that dies later.")

_bad = [r for r in _v_rows if r["import_error"]]
if not _bad:
    st.success("All %d modules import." % len(_v_rows))
else:
    st.error("**%d module(s) do not import.**" % len(_bad))
    for r in _bad:
        st.caption("`%s` - %s" % (r["module"], r["import_error"]))
# @@END 008 IMPORTS

# @@BLOCK 009 FRAME deps=008
st.markdown("### 4. Frame")
st.caption("Target is owned by `verify_blocks.py`; this page only reads it. A "
           "mismatch means a file was added or removed without moving the target.")

try:
    import verify_blocks as _vb
    if not hasattr(_vb, "audit_source"):
        _vb = importlib.reload(_vb)
except Exception as e:
    _vb = None
    st.error("verify_blocks will not import: %s: %s" % (type(e).__name__, e))

if _vb is not None:
    _reps = {}
    for _p in _vb.BLOCKED_FILES:
        try:
            _reps[_p] = _vb.audit_source(_p)
        except Exception as e:
            _reps[_p] = {"faults": 1, "blocks": [],
                         "fails": ["audit raised %s" % type(e).__name__],
                         "table": [], "exists": False}
    _files = sum(1 for r in _reps.values() if r.get("exists"))
    _blocks = sum(len(r.get("blocks") or []) for r in _reps.values())
    _faults = sum(int(r.get("faults") or 0) for r in _reps.values())
    _tgt_f = getattr(_vb, "TARGET_FILES", 0)
    _tgt_b = getattr(_vb, "TARGET_BLOCKS", 0)

    _f1, _f2, _f3, _f4 = st.columns(4)
    _f1.metric("Files", _files, "%+d" % (_files - _tgt_f), delta_color="off")
    _f2.metric("Blocks", _blocks, "%+d" % (_blocks - _tgt_b), delta_color="off")
    _f3.metric("Faults", _faults)
    _f4.metric("Target", "%d/%d" % (_tgt_f, _tgt_b))

    if _faults == 0 and _files == _tgt_f and _blocks == _tgt_b:
        st.success("Frame clean and on target.")
    else:
        st.error("Frame is NOT clean or NOT on target. Faults are quoted below "
                 "with their line numbers.")

    st.dataframe([{"file": p, "blocks": len(r.get("blocks") or []),
                   "faults": int(r.get("faults") or 0)}
                  for p, r in _reps.items()], width="stretch", height=320)

    for _p, _r in _reps.items():
        if _r.get("faults"):
            with st.expander("%s - %s fault(s)" % (_p, _r.get("faults"))):
                for _f in (_r.get("fails") or [])[:40]:
                    st.caption(_f)
# @@END 009 FRAME

# @@BLOCK 010 CONFORMANCE deps=009
st.markdown("### 5. Verifier contract")
st.caption("`audit_frame.api_conformance()` proves verify_blocks still satisfies its "
           "three callers. It is the gate that catches a verifier quietly disarmed.")

try:
    import audit_frame as _af
    if not hasattr(_af, "api_conformance"):
        _af = importlib.reload(_af)
    _prob = _af.api_conformance()
except Exception as e:
    _prob = ["audit_frame.api_conformance raised: %s: %s" % (type(e).__name__, e)]

if not _prob:
    st.success("All three callers satisfied.")
else:
    st.error("**%d problem(s).**" % len(_prob))
    for _p in _prob:
        st.caption(_p)
# @@END 010 CONFORMANCE

# @@BLOCK 011 SESSION deps=010
st.markdown("### 6. Session state")
st.caption("The live keys in THIS session, secrets masked. Nothing here is read "
           "from another user's session.")

_sess = []
for _k in sorted(st.session_state.keys(), key=lambda s: str(s)):
    try:
        _val = st.session_state[_k]
    except Exception:
        _val = "<unreadable>"
    _type = type(_val).__name__
    if isinstance(_val, (list, dict, set, tuple)):
        _shown = "<%s, %d item(s)>" % (_type, len(_val))
    else:
        _shown = _mask(_k, _val)
    _sess.append({"key": _k, "type": _type, "value": _shown})
st.dataframe(_sess, width="stretch", height=280)
# @@END 011 SESSION

# @@BLOCK 012 GATES deps=011
st.markdown("### 7. Gates")
st.caption("The eighteen, in order. All must be green before a commit, and the "
           "workflow step names in `.github/workflows/gates.yml` are the authority "
           "if a command here ever drifts.")

_GATES = """python fix_end_names.py --check
python verify_blocks.py
python audit_frame.py
python verify_v1337.py
python test_verdicts.py
python engine.py --selftest
python status.py --selftest
python auth.py --selftest
python -m compileall -q .
pip install -r requirements.txt
python pages/5_Blocks.py --fix-check
python runstate.py --selftest
python test_resume_io.py"""
st.code(_GATES, language="text")

st.caption("Five more run as shell steps in the workflow: the blocks=N header "
           "equals the @@BLOCK count, the @@END count equals the same N, app.py "
           "ends with @@EOF, `read_timeout` appears nowhere, and no conflict "
           "marker exists in any .py.")
# @@END 012 GATES

# @@BLOCK 013 BUNDLE deps=012
st.markdown("---")
st.markdown("### 8. Diag bundle")
st.caption("Everything above as one JSON file, for pasting into a report.")


def _bundle():
    """The bundle dict. Never raises - a failing section is recorded as text."""
    out = {"built_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
           "python": platform.python_version(), "platform": platform.system(),
           "owner": _owner_id, "anon": _anon, "app_header": _APP_TAG,
           "streamlit": getattr(__import__("streamlit"), "__version__", "?")}
    try:
        out["modules"] = _v_rows
    except Exception as e:
        out["modules"] = "error: %s" % e
    try:
        out["frame"] = {"files": _files, "blocks": _blocks, "faults": _faults,
                        "target_files": _tgt_f, "target_blocks": _tgt_b}
    except Exception as e:
        out["frame"] = "error: %s" % e
    try:
        out["conformance"] = _prob
    except Exception as e:
        out["conformance"] = "error: %s" % e
    try:
        out["session_keys"] = [r["key"] for r in _sess]
    except Exception as e:
        out["session_keys"] = "error: %s" % e
    try:
        import aiassist
        out["aiassist"] = aiassist.report()
    except Exception as e:
        out["aiassist"] = "error: %s: %s" % (type(e).__name__, e)
    try:
        import breach
        out["breach"] = breach.report()
    except Exception as e:
        out["breach"] = "error: %s: %s" % (type(e).__name__, e)
    return out


st.download_button("\u2b07 Download diag bundle",
                   data=json.dumps(_bundle(), indent=2, default=str).encode("utf-8"),
                   file_name="diag_%s.json" % datetime.now().strftime("%Y%m%d_%H%M%S"),
                   mime="application/json", width="stretch")
# @@END 013 BUNDLE

# @@BLOCK 014 FOOTER deps=013
st.markdown("---")
_g1, _g2, _g3 = st.columns(3)
with _g1:
    try:
        st.page_link("app.py", label="\u26a1 Checker", width="stretch")
    except Exception:
        st.caption("Checker lives at app.py")
with _g2:
    try:
        st.page_link("pages/9_AI.py", label="\U0001f9e0 AI Console", width="stretch")
    except Exception:
        st.caption("AI Console lives at pages/9_AI.py")
with _g3:
    try:
        st.page_link("pages/5_Blocks.py", label="\U0001f9f1 Blocks", width="stretch")
    except Exception:
        st.caption("Blocks lives at pages/5_Blocks.py")

st.caption("Read-only. Nothing here edits a file, runs a gate or writes to another "
           "user's store.")
# @@END 014 FOOTER
# @@EOF
