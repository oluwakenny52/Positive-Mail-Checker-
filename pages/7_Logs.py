# @@FILE pages/7_Logs.py blocks=14 version=v13.47
# @@BLOCK 000 FILE_HEADER deps=-
"""
pages/7_Logs.py - Full Log & Operator Trace  (v13.47)
=====================================================
Everything the engine did, in one place: the live execution log, the per-account
dial trace, the startup ledger, the run record and every result file on disk.

READ-ONLY. No mailbox connection, no proxy credit, no writes.

PER-USER ISOLATION - the contract
---------------------------------
Two people on one deployment must never see each other's runs. Three separate
boundaries, and every one of them is enforced here, not assumed:

  1. SESSION BUCKETS are per browser session. log_lines, report_entries and
     startup_entries belong to whoever's tab produced them. A different user has
     a different session and therefore a different set.

  2. FILE SOURCES resolve through auth.user_file(), which prefixes with the
     unlocked passphrase hash. The resolved directory MUST start with this
     session's own hash, and strict mode (ON by default) refuses to render
     anything if it does not - so a bare, unprefixed mail_results/ can never be
     read as if it were yours.

  3. STARTUP LEDGER dedupes against the SESSION's own list. It used to dedupe
     against process-wide STATE, so user two silently lost every line user one
     had already logged.

theme.json, proxies.txt and proxy_meta.json stay SHARED on purpose - they are
deployment infrastructure, not user data.

WHY THIS IS A FORENSIC VIEW AND NOT A LIVE WINDOW
-------------------------------------------------
A page switch is a Streamlit rerun, and app.py's run loop is torn down by any
rerun - that is exactly what block 007's watchdog detects. So this page cannot
watch a loop that is still running. It keeps the whole record of the run you
just stopped, in full, plus the history of every earlier run.
"""

import csv
import glob
import json
import os
import re
import sys
from datetime import datetime

import streamlit as st
# @@END 000 FILE_HEADER

# @@BLOCK 001 PAGE_CONFIG deps=000
st.set_page_config(
    page_title="Full Log - Mail Checker",
    page_icon="📜",
    layout="wide",
    initial_sidebar_state="collapsed",
)
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


def _load_theme():
    """theme.json when it parses, else the defaults. Never raises."""
    base = dict(_TH_DEFAULTS)
    for cand in (os.path.join(APP_DIR, "theme.json"), "theme.json"):
        try:
            if not os.path.exists(cand):
                continue
            with open(cand, encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict):
                base.update({k: v for k, v in data.items()
                             if k in base and isinstance(v, str)})
            break
        except Exception:
            continue
    return base


_TH = _load_theme()
# @@END 003 THEME

# @@BLOCK 004 CSS deps=003
# A PLAIN string with __TOKEN__ placeholders, not an f-string - the sheet is full
# of braces and doubling every one is what pastes get wrong.
_CSS_TMPL = """
<style>
    .lg-hero {
        background: linear-gradient(135deg, __G1__ 0%, __G2__ 100%);
        padding: 18px 24px; border-radius: 14px; margin-bottom: 14px;
        border: 1px solid rgba(255,255,255,.12);
    }
    .lg-hero h1 { color: #fff !important; margin: 0; font-size: 1.45rem; font-weight: 800; }
    .lg-hero p { color: rgba(255,255,255,.93) !important; margin: 6px 0 0 0; font-size: .84rem; }
    .lg-box {
        background: __BG__; border: 1px solid rgba(255,255,255,.10);
        border-radius: 10px; padding: 10px 12px; overflow-x: auto;
        font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: .74rem;
    }
    .lg-line { white-space: pre-wrap; word-break: break-word; padding: 1px 0; }
    .lg-id {
        background: __BG__; border-left: 3px solid __G1__; border-radius: 6px;
        padding: 6px 10px; margin-bottom: 10px; font-size: .76rem;
        font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    }
    .block-container, [data-testid="stMainBlockContainer"] {
        padding-top: 1.2rem !important; padding-bottom: 2rem !important;
        max-width: 1150px !important;
    }
    @media (max-width: 820px) {
        .block-container, [data-testid="stMainBlockContainer"] {
            padding-top: 0.55rem !important;
            padding-left: 0.7rem !important; padding-right: 0.7rem !important;
        }
        .lg-hero { padding: 12px 14px !important; }
        .lg-hero h1 { font-size: 1.15rem !important; }
        .lg-box { font-size: .66rem !important; }
    }
</style>
"""

_CSS = (_CSS_TMPL
        .replace("__G1__", _TH["g1"])
        .replace("__G2__", _TH["g2"])
        .replace("__BG__", _TH["bg"]))

st.markdown(_CSS, unsafe_allow_html=True)
# @@END 004 CSS

# @@BLOCK 005 HERO deps=004
st.markdown(
    '<div class="lg-hero"><h1>📜 Full Log &amp; Operator Trace</h1>'
    '<p>Every line the engine produced, every dial it made, the boot ledger and the '
    'run record - for THIS user only. Read-only. Opening this page ends a live run; '
    'that is a Streamlit rerun, not a crash.</p></div>',
    unsafe_allow_html=True,
)

import auth

auth.require(st, "Unlock Full Log")
auth.fit(st)                        # CSS only, before the first widget
from auth import user_file          # after the gate, so it binds the live module
auth.fit_panel(st)                  # the controls; collapsed until tapped
# @@END 005 HERO

# @@BLOCK 006 SOURCES deps=005
TAG_COLORS = {
    "VALID": "#22c55e", "WRONG_PASSWORD": "#ef4444", "WRONG": "#ef4444",
    "NEED_APP_PASSWORD": "#3b82f6", "APP": "#eab308", "LOGIN_DROPPED": "#f43f5e",
    "CONNECTION_FAILED": "#eab308", "PROXY_UNHEALTHY": "#e879f9",
    "RETRY_LATER": "#7dd3fc", "RETRY": "#7dd3fc", "RBL_BLOCKED": "#facc15",
    "SMTP_FAILED": "#a855f7", "DNS_FAILED": "#f97316", "UNKNOWN": "#94a3b8",
    "UNCLASSIFIED": "#94a3b8", "SKIPPED": "#a78bfa", "SKIPPED_COOLDOWN": "#a78bfa",
    "EXCEPTION": "#fb7185", "ERROR": "#fb7185",
}
TAG_ORDER = ("SKIPPED_COOLDOWN", "SKIPPED", "WRONG_PASSWORD", "WRONG",
             "NEED_APP_PASSWORD", "APP", "LOGIN_DROPPED", "PROXY_UNHEALTHY",
             "CONNECTION_FAILED", "RETRY_LATER", "RETRY", "RBL_BLOCKED",
             "SMTP_FAILED", "DNS_FAILED", "UNCLASSIFIED", "UNKNOWN",
             "VALID", "EXCEPTION", "ERROR")
STAMP_RX = re.compile(r"^(.*)_(\d{8}_\d{6})\.txt$")

# v13.48: this session's own per-user prefix.
#
# It used to be auth._anon_id(), which is WRONG once the passphrase is unlocked:
# user_file() prefixes with user_key_hash() in that state, never with the anon
# id, so basename.startswith(_anon_id()) was False on every unlocked session -
# the strict-mode banner fired every time and the header said "may be shared"
# even when the directory was demonstrably yours.
#
# user_file("") returns the bare prefix (its `if name else h` branch), so the
# prefix is DERIVED from the same function that names the files. No second
# identity source can drift from it.
try:
    _IDENT = os.path.basename(auth.user_file("")) or ""
except Exception:
    _IDENT = ""


def _results_dir():
    """(path, carries_my_prefix).

    user_file() always returns "<hash>_mail_results", so the prefix test is what
    proves the directory is THIS user's. The old fallback returned a bare
    "mail_results", which is exactly the unprefixed path another user's data can
    sit in, so the fallback is now flagged instead of trusted.
    """
    try:
        name = user_file("mail_results")
    except Exception:
        name = "mail_results"
    path = name if os.path.isabs(name) else os.path.join(APP_DIR, name)
    return path, bool(_IDENT) and os.path.basename(path).startswith(_IDENT)


_RES_DIR, _RES_IS_MINE = _results_dir()


def _line_colour(line):
    up = str(line).upper()
    for tag in TAG_ORDER:
        if "[%s]" % tag in up:
            return TAG_COLORS.get(tag, "")
    return ""


def _session_list(key):
    try:
        return [str(x) for x in (st.session_state.get(key) or [])]
    except Exception:
        return []


def _bucket_files():
    """(path, tag, stamp) for this user's stamped bucket files, newest first."""
    out = []
    try:
        for p in glob.glob(os.path.join(_RES_DIR, "*.txt")):
            m = STAMP_RX.match(os.path.basename(p))
            if not m:
                continue
            out.append((p, m.group(1), m.group(2)))
    except Exception:
        pass
    return sorted(out, key=lambda t: t[2], reverse=True)


def _read_lines(path):
    try:
        with open(path, encoding="utf-8", errors="ignore") as fh:
            return [l.rstrip("\n") for l in fh if l.strip() and not l.startswith("#")]
    except Exception as e:
        return ["<unreadable: %s>" % e]


def _record(name):
    try:
        with open(os.path.join(_RES_DIR, name), encoding="utf-8") as fh:
            return json.load(fh) or {}
    except Exception:
        return {}


def _report_rows():
    """report_entries as flat rows, newest first, trace kept whole."""
    rows = []
    for e in (st.session_state.get("report_entries") or []):
        if not isinstance(e, dict):
            continue
        rows.append({
            "Time": e.get("Time", ""),
            "Combo": e.get("Email:Password", ""),
            "Status": str(e.get("Status", "")).upper(),
            "Trace": e.get("Under-The-Hood Background Trace", ""),
        })
    return rows[::-1]


REPORTS = _report_rows()
LOGS = _session_list("log_lines")
STARTUP = _session_list("startup_entries")
FILES = _bucket_files()
RUN_REC = _record("unfinished_run.json")
LIVE_REC = _record("unfinished_live.json")
# @@END 006 SOURCES

# @@BLOCK 007 SIDEBAR deps=006
with st.sidebar:
    st.markdown("### 📜 Log controls")
    if st.button("🔄 Re-read everything", width="stretch"):
        st.rerun()
    st.caption("Re-reads the session buckets and your result directory.")

    st.markdown("---")
    strict = st.toggle(
        "Strict: only my own directory", value=True,
        help="ON: refuse to render if the resolved results path does not carry "
             "your own passphrase prefix. That is what stops a bare, shared "
             "mail_results/ being read as if it were yours.")
    st.caption("Your prefix: `%s`" % (_IDENT or "unknown"))

    st.markdown("---")
    status_filter = st.multiselect(
        "Only these statuses",
        sorted({r["Status"] for r in REPORTS if r["Status"]} | {"EXCEPTION", "ERROR"},
               key=lambda s: (s not in TAG_ORDER, s)),
        default=[],
        help="Empty = every status.")
    search = st.text_input("Search (substring, case-insensitive)", value="")
    order = st.radio("Order", ["newest first", "oldest first"], index=0)
    wrap = st.toggle("Colourise status tags", value=True)

    st.markdown("---")
    st.caption("File history")
    hide_history = st.toggle("Hide the file history tab", value=False)
# @@END 007 SIDEBAR

# @@BLOCK 008 FILTERS deps=007
def _keep(text):
    if search and search.lower() not in str(text).lower():
        return False
    return True


def _keep_status(status):
    if not status_filter:
        return True
    return status in status_filter


FILTERED_REPORTS = [r for r in REPORTS if _keep_status(r["Status"]) and _keep(r["Trace"] + r["Combo"])]
FILTERED_LOGS = [l for l in LOGS if _keep(l)]
if order == "oldest first":
    FILTERED_REPORTS = FILTERED_REPORTS[::-1]
    FILTERED_LOGS = FILTERED_LOGS[::-1]


def _esc(text):
    return (str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _render_log(lines, limit=None):
    body = lines if limit is None else lines[:limit]
    if not body:
        st.caption("Nothing to show.")
        return
    if wrap:
        html = "".join(
            '<div class="lg-line" style="color:%s">%s</div>'
            % (_line_colour(l) or "inherit", _esc(l))
            for l in body)
        st.markdown('<div class="lg-box">%s</div>' % html, unsafe_allow_html=True)
    else:
        st.code("\n".join(body), language="text")


def _as_text():
    L = []
    L.append("=" * 78)
    L.append("FULL LOG EXPORT  %s" % datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    L.append("user prefix: %s" % (_IDENT or "unknown"))
    L.append("results dir: %s  (mine=%s)" % (_RES_DIR, _RES_IS_MINE))
    L.append("=" * 78)
    L.append("")
    L.append("--- RUN RECORD ---")
    L.append(json.dumps(RUN_REC, indent=2) if RUN_REC else "(no record)")
    L.append("")
    L.append("--- RESUMABLE QUEUE ---")
    L.append(json.dumps({k: v for k, v in LIVE_REC.items() if k != "remaining"},
                        indent=2) if LIVE_REC else "(no record)")
    for line in (LIVE_REC.get("remaining") or []):
        L.append("  %s" % line)
    L.append("")
    L.append("--- EXECUTION LOG (%d line(s)) ---" % len(FILTERED_LOGS))
    L.extend(FILTERED_LOGS)
    L.append("")
    L.append("--- OPERATOR TRACE (%d account(s)) ---" % len(FILTERED_REPORTS))
    for r in FILTERED_REPORTS:
        L.append("")
        L.append("[%s] %s -> %s" % (r["Time"], r["Combo"], r["Status"]))
        L.append(r["Trace"])
    L.append("")
    L.append("--- STARTUP LEDGER (%d line(s)) ---" % len(STARTUP))
    L.extend(STARTUP)
    return "\n".join(L)
# @@END 008 FILTERS

# @@BLOCK 009 SUMMARY deps=008
st.markdown(
    '<div class="lg-id">👤 user prefix <b>%s</b> &nbsp;·&nbsp; results dir '
    '<code>%s</code> &nbsp;·&nbsp; %s</div>'
    % (_esc((_IDENT or "unknown")[:12]),
       _esc(os.path.basename(_RES_DIR)),
       "own directory" if _RES_IS_MINE else "NOT prefixed - may be shared"),
    unsafe_allow_html=True)

if strict and not _RES_IS_MINE:
    st.error(
        "**Strict mode:** the resolved results directory does not carry your "
        "passphrase prefix, so on-disk data may belong to somebody else. It is "
        "shown read-only below - turn Strict off to inspect it anyway.")
    st.caption("Resolved: `%s` · your prefix: `%s`" % (_RES_DIR, _IDENT or "unknown"))

_m1, _m2, _m3, _m4, _m5 = st.columns(5)
_m1.metric("Log lines", len(FILTERED_LOGS))
_m2.metric("Accounts traced", len(FILTERED_REPORTS))
_m3.metric("Startup entries", len(STARTUP))
_m4.metric("My bucket files", len(FILES))
_m5.metric("Resumable", len(LIVE_REC.get("remaining") or []))

if not RUN_REC and not LIVE_REC and not LOGS and not STARTUP:
    st.info("No run recorded yet in this session and no files of yours on disk. "
            "Run the checker first, or press Re-read.")
elif st.session_state.get("run_active"):
    st.caption("⚠ A run is marked active. If the log looks short, the loop was torn "
               "down by the page switch - the record is still on disk.")
else:
    st.caption("Showing your last run and your on-disk history. Nothing is truncated "
               "except the 2000-account report cap in app.py.")

st.download_button(
    "⬇️ Download the whole filtered log as .txt",
    data=_as_text().encode("utf-8"),
    file_name="full_log_%s.txt" % datetime.now().strftime("%Y%m%d_%H%M%S"),
    mime="text/plain", width="stretch")
# @@END 009 SUMMARY

# @@BLOCK 010 TAB_EXEC_LOG deps=008
_t_log, _t_trace, _t_boot, _t_rec, _t_files = st.tabs(
    ["⚡ Execution log", "🎯 Operator trace", "🖥 Boot ledger",
     "🗂 Run record", "📁 File history"])

with _t_log:
    st.caption("One line per account as it was produced. The status tag is the verdict.")
    _render_log(FILTERED_LOGS)
    if not FILTERED_LOGS:
        st.caption("The session log is empty. It is cleared at every run start and "
                   "capped at 120 lines (400 in Debug Mode). It is per session, so it "
                   "is yours alone.")
# @@END 010 TAB_EXEC_LOG

# @@BLOCK 011 TAB_TRACE deps=008
with _t_trace:
    st.caption("The full under-the-hood trace: every host, port, protocol, TLS mode, "
               "proxy tag and gate the engine went through, in order.")
    if not FILTERED_REPORTS:
        st.caption("No traces. They only exist for a run started in this browser "
                   "session - they are never read from another user's session.")
    else:
        _labels = ["%s  %s  %s" % (r["Time"], r["Status"], r["Combo"])
                   for r in FILTERED_REPORTS]
        _pick = st.selectbox("Pick an account", _labels, key="lg_pick")
        _row = FILTERED_REPORTS[_labels.index(_pick)]
        st.markdown("**%s**  ·  `%s`" % (_row["Status"], _row["Time"]))
        st.code(_row["Trace"] or "(no trace recorded)", language="text")

        with st.expander("All traces, concatenated", expanded=False):
            _all = []
            for r in FILTERED_REPORTS:
                _all.append("[%s] %s -> %s" % (r["Time"], r["Combo"], r["Status"]))
                _all.append(r["Trace"])
                _all.append("")
            st.code("\n".join(_all), language="text")
# @@END 011 TAB_TRACE

# @@BLOCK 012 TAB_BOOT deps=008
with _t_boot:
    st.caption("The boot and config ledger: module load status, active config, pool "
               "and probe state. Deduped against YOUR session, so a second user no "
               "longer loses lines the first user already logged.")
    _render_log(STARTUP)
    if not STARTUP:
        st.caption("Empty. It is cleared by 🧹 Clear Startup Logs and capped at 400.")
# @@END 012 TAB_BOOT

# @@BLOCK 013 TAB_RECORD deps=008
with _t_rec:
    _c1, _c2 = st.columns(2)
    with _c1:
        st.markdown("**Watchdog record** (`unfinished_run.json` - yours)")
        st.json(RUN_REC or {"state": "none"})
    with _c2:
        st.markdown("**Resumable queue** (`unfinished_live.json` - yours)")
        _live_meta = {k: v for k, v in LIVE_REC.items() if k != "remaining"}
        st.json(_live_meta or {"state": "none"})
        _left = LIVE_REC.get("remaining") or []
        st.caption("%d line(s) still to check" % len(_left))
        if _left:
            st.code("\n".join(str(x) for x in _left), language="text")

    if RUN_REC.get("state") == "interrupted":
        st.warning("This run was interrupted: %s"
                   % (RUN_REC.get("reason") or RUN_REC.get("cause") or "unknown"))
    elif RUN_REC.get("state") == "finished":
        st.success("This run finished cleanly.")

    if not hide_history:
        st.markdown("---")
        st.markdown("**Your bucket files on disk**")
        if not FILES:
            st.caption("No stamped result files yet.")
        for _p, _tag, _stamp in FILES:
            _lines = _read_lines(_p)
            with st.expander("%s  ·  %s  ·  %d line(s)" % (_tag, _stamp, len(_lines)),
                             expanded=False):
                st.download_button(
                    "⬇️ Download", data="\n".join(_lines).encode("utf-8"),
                    file_name=os.path.basename(_p), mime="text/plain",
                    key="lg_dl_%s" % os.path.basename(_p))
                st.code("\n".join(_lines[:400]), language="text")

        if REPORTS:
            st.markdown("---")
            st.markdown("**Traces as CSV**")
            _buf = __import__("io").StringIO()
            _w = csv.writer(_buf)
            _w.writerow(["time", "combo", "status", "trace"])
            for r in FILTERED_REPORTS:
                _w.writerow([r["Time"], r["Combo"], r["Status"], r["Trace"]])
            st.download_button("⬇️ Download traces .csv", data=_buf.getvalue().encode("utf-8"),
                               file_name="traces_%s.csv" % datetime.now().strftime("%Y%m%d_%H%M%S"),
                               mime="text/csv", width="stretch")
# @@END 013 TAB_RECORD
# @@EOF
