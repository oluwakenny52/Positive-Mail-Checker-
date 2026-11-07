# @@FILE pages/1_Notifications.py blocks=11 version=v13.48
# @@BLOCK 000 FILE_HEADER deps=-
"""
pages/1_Notifications.py - Notifications & Resource Health  (v13.70)
=====================================================================
Everything the app has raised for THIS user, newest first, with the system
notifications that matter on a 1 GB deployment: RAM headroom, disk headroom and
this session's own payload - each with the suggestion that actually fixes it.

WHY A PAGE AND NOT ONLY THE DROPDOWN
------------------------------------
The bell in app.py block 057 is the indicator; it is capped at 25 rows because a
popover is a glance, not a reading surface. This page is the reading surface: the
full ring, filters, the accurate storage panel and an export.

ISOLATION
---------
notify.py stores per user under data/<unlocked hash>/, so the list here is yours
alone. The badge comes from the same file, so the bell and this page can never
disagree. The page writes nothing outside that directory except the seen marker.

ACCURACY OF THE NUMBERS - stated, because they are easy to misread
-----------------------------------------------------------------
  * RAM belongs to the CONTAINER, not to a person: every session on this
    deployment shares one process and one cgroup. The percentage uses the
    cgroup's own usage (cache included), because that is the figure the OOM
    killer reads. Process RSS is shown beside it as the part this process can
    give back.
  * DISK: "free" is measured on the filesystem the app writes to and is the
    number an ENOSPC turns on. "Total" is that filesystem's size, which on an
    overlay is the HOST disk - shown as context, never as a quota.
  * "My files" is the only disk figure that is yours, and the only one the delete
    buttons can move.

Read-only except Mark read / Clear / Dismiss.
"""

import importlib
import json
import os
import sys
from datetime import datetime

import streamlit as st
# @@END 000 FILE_HEADER

# @@BLOCK 001 PAGE_CONFIG deps=000
st.set_page_config(page_title="Notifications - Mail Checker",
                   page_icon="\U0001f514", layout="wide",
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
    .nt-hero {
        background: linear-gradient(135deg, __G1__ 0%, __G2__ 100%);
        padding: 18px 24px; border-radius: 14px; margin-bottom: 14px;
        border: 1px solid rgba(255,255,255,.12);
    }
    .nt-hero h1 { color: #fff !important; margin: 0; font-size: 1.45rem; font-weight: 800; }
    .nt-hero p { color: rgba(255,255,255,.93) !important; margin: 6px 0 0 0; font-size: .84rem; }
    .nt-card {
        background: __PANEL__; border: 1px solid rgba(255,255,255,.10);
        border-left: 4px solid __G1__; border-radius: 10px;
        padding: 9px 12px; margin-bottom: 8px;
    }
    .nt-card .nt-t { font-size: .84rem; line-height: 1.4; }
    .nt-card .nt-s { font-size: .76rem; opacity: .85; margin-top: 3px; }
    .nt-card .nt-m { font-size: .64rem; opacity: .55; margin-top: 4px;
                     text-transform: uppercase; letter-spacing: .04em; }
    .block-container, [data-testid="stMainBlockContainer"] {
        padding-top: 1.2rem !important; padding-bottom: 2rem !important;
        max-width: 1000px !important;
    }
    @media (max-width: 820px) {
        .block-container, [data-testid="stMainBlockContainer"] {
            padding-top: .55rem !important; padding-left: .7rem !important;
            padding-right: .7rem !important;
        }
        .nt-hero h1 { font-size: 1.15rem !important; }
        .nt-card .nt-t { font-size: .78rem; }
    }
</style>
"""


def _css():
    return (_CSS_TMPL.replace("__G1__", _TH["g1"])
            .replace("__G2__", _TH["g2"])
            .replace("__PANEL__", _TH["panel"]))


st.markdown(_css(), unsafe_allow_html=True)
# @@END 004 CSS

# @@BLOCK 005 HERO_GATE deps=004
st.markdown(
    '<div class="nt-hero"><h1>\U0001f514 Notifications &amp; Resource Health</h1>'
    '<p>Everything raised for you - resource alerts with the fix beside each one, '
    'and the run events worth knowing about. Yours only.</p></div>',
    unsafe_allow_html=True)

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
    audit_log.page("pages/1_Notifications.py")

auth.require(st, "Unlock Notifications")
auth.fit(st)

if hasattr(audit_log, "install"):
    audit_log.install(st, "pages/1_Notifications.py")

auth.fit_panel(st)

# The first theme read ran before the gate and therefore used the anonymous
# prefix. Now that the passphrase is unlocked the owner's real file exists, so
# re-read it and repaint. A second identical <style> is harmless; the last wins.
_TH = _theme()
st.markdown(_css(), unsafe_allow_html=True)
# @@END 005 HERO_GATE

# @@BLOCK 006 SOURCES deps=005
import notify

if not (hasattr(notify, "entries") and hasattr(notify, "system_tick")):
    notify = importlib.reload(notify)

from auth import user_file


def _mb(n):
    try:
        n = float(n)
    except Exception:
        return "?"
    if n <= 0:
        return "0 B"
    if n < 1024:
        return "%d B" % int(n)
    if n < 1048576:
        return "%.0f KB" % (n / 1024.0)
    if n < 1073741824:
        return "%.1f MB" % (n / 1048576.0)
    return "%.2f GB" % (n / 1073741824.0)


def _cgroup(paths):
    for p in paths:
        try:
            with open(p, encoding="utf-8", errors="ignore") as fh:
                raw = fh.read().strip()
            if not raw:
                continue
            if raw == "max":
                return 0
            n = int(raw)
            if 0 < n < (1 << 62):
                return n
        except Exception:
            continue
    return 0


def _rss():
    try:
        with open("/proc/self/status", encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) * 1024
    except Exception:
        pass
    return 0


def _disk():
    try:
        v = os.statvfs(os.getcwd())
        return int(v.f_blocks) * int(v.f_frsize), int(v.f_bavail) * int(v.f_frsize)
    except Exception:
        return 0, 0


def _my_files():
    """(count, bytes) for files carrying this user's prefix, root and data/."""
    pfx = os.path.basename(user_file("")) or ""
    n = b = 0
    if not pfx:
        return 0, 0
    root = os.getcwd()

    def _sized(path):
        nonlocal n, b
        n += 1
        try:
            b += os.path.getsize(path)
        except Exception:
            pass

    try:
        for name in os.listdir(root):
            if not name.startswith(pfx + "_"):
                continue
            full = os.path.join(root, name)
            if os.path.isfile(full):
                _sized(full)
            elif os.path.isdir(full):
                for wr, _d, files in os.walk(full):
                    for fn in files:
                        _sized(os.path.join(wr, fn))
    except Exception:
        pass
    try:
        for wr, _d, files in os.walk(os.path.join(root, "data", pfx)):
            for fn in files:
                _sized(os.path.join(wr, fn))
    except Exception:
        pass
    return n, b


_SESS_KEYS = ("valid_results", "wrong_results", "need_app_results",
              "login_drop_results", "conn_results", "proxy_results",
              "retry_results", "rbl_results", "smtp_results", "dns_results",
              "skip_results", "unknown_results", "log_lines", "report_entries",
              "startup_entries")


def _session_bytes():
    """Rough payload size. Shallow - the trace strings are counted as a flat 80."""
    total = 0
    for k in _SESS_KEYS:
        v = st.session_state.get(k)
        if not v:
            continue
        try:
            if isinstance(v, dict):
                total += len(v) * 80
            elif isinstance(v, (list, tuple, set, str)):
                for item in v:
                    if isinstance(item, str):
                        total += len(item)
                    elif isinstance(item, dict):
                        total += 80
                    else:
                        total += 24
        except Exception:
            continue
    try:
        total += len(st.session_state.get("bb_raw_text") or "")
    except Exception:
        pass
    return total


RSS = _rss()
CUSED = _cgroup(("/sys/fs/cgroup/memory.current",
                 "/sys/fs/cgroup/memory/memory.usage_in_bytes"))
CLIM = _cgroup(("/sys/fs/cgroup/memory.max",
                "/sys/fs/cgroup/memory/memory.limit_in_bytes"))
D_TOTAL, D_FREE = _disk()
MY_N, MY_B = _my_files()
SESS_B = _session_bytes()

COUNT = notify.counts()
UNSEEN_BEFORE = int(COUNT.get("unseen") or 0)
notify.mark_seen()
notify.system_tick(force=True, session_bytes=SESS_B)
# @@END 006 SOURCES

# @@BLOCK 007 SIDEBAR deps=006
with st.sidebar:
    st.markdown("### \U0001f514 Notification controls")
    st.caption("This page marks everything read as it loads - that is what the bell "
               "count is for. Nothing is deleted by reading it.")
    if st.button("Clear all notifications", width="stretch",
                 help="Deletes YOUR notification file only."):
        notify.clear()
        st.rerun()
    st.markdown("---")
    level_pick = st.multiselect("Only these levels", list(notify.LEVELS), default=[])
    _kinds = sorted({str(r.get("kind") or "") for r in
                     notify.entries(limit=notify.MAX_LINES) if r.get("kind")})
    kind_pick = st.multiselect("Only these kinds", _kinds, default=[])
    st.markdown("---")
    show_system = st.toggle("Show the resource panel", value=True)
    st.caption("Reading this page costs no proxy credit and opens no mailbox.")
# @@END 007 SIDEBAR

# @@BLOCK 008 RESOURCE_PANEL deps=006,007
if show_system:
    st.markdown("### \U0001f9ee Live resources")
    st.caption("RAM belongs to the container and is shared by every session here. "
               "The percentage uses the cgroup's own usage - cache included - because "
               "that is what the OOM killer reads. RSS is the part this process can "
               "give back.")

    killer = CUSED or RSS
    r1, r2, r3 = st.columns(3)
    r1.metric("Process RSS", _mb(RSS))
    r2.metric("Container memory (incl. cache)", _mb(CUSED) if CUSED else "?")
    r3.metric("Container limit", _mb(CLIM) if CLIM else "no limit file")

    if CLIM and killer:
        pct = min(1.0, float(killer) / float(CLIM))
        st.progress(pct, text="%.0f%% of the limit - %s headroom"
                              % (pct * 100, _mb(max(0, CLIM - killer))))
        if pct >= 0.86:
            st.error("\U0001f6a8 Very little headroom. Free the payload, cut Workers "
                     "Start to 10-20 and reboot before another run.")
        elif pct >= 0.72:
            st.warning("\u26a0 Getting tight. Trim the payload and keep the paste short.")
    elif not CLIM:
        st.caption("No cgroup limit file (not Linux, or not containerised), so there "
                   "is no honest percentage to show. The RSS figure above is real.")

    d1, d2, d3, d4 = st.columns(4)
    d1.metric("My session payload", _mb(SESS_B))
    d2.metric("My files on disk", _mb(MY_B), help="%d file(s) carrying my prefix" % MY_N)
    d3.metric("Filesystem free", _mb(D_FREE),
              help="Free space where the app writes - what an out-of-disk error "
                   "turns on.")
    d4.metric("Filesystem total (shared host disk)", _mb(D_TOTAL))

    if D_TOTAL and D_FREE:
        fpct = min(1.0, float(max(0, D_TOTAL - D_FREE)) / float(D_TOTAL))
        st.progress(fpct, text="Filesystem %.1f%% used overall (%s free) - shared by "
                               "every app on the host, so it is context, not a quota"
                               % (fpct * 100, _mb(D_FREE)))
        if D_FREE <= notify.DISK_CRIT_B:
            st.error("\U0001f6a8 Under %s free. Export what you need, then clear cache "
                     "and result files from the app's resource panel."
                     % _mb(notify.DISK_CRIT_B))
        elif D_FREE <= notify.DISK_WARN_B:
            st.warning("\u26a0 Low free space (%s). Clear cache and old result files."
                       % _mb(D_FREE))

    if SESS_B >= notify.SESS_WARN_B:
        st.warning("\u26a0 My payload is %s - this is the part that causes the kills. "
                   "The app's Free my RAM button trims it and deletes nothing on disk."
                   % _mb(SESS_B))

    st.caption("Readings are taken once, when this page loads. The app's own panel "
               "refreshes at most every 3 seconds while it is open.")
    st.markdown("---")
# @@END 008 RESOURCE_PANEL

# @@BLOCK 009 LIST deps=006,007
_rows = notify.entries(limit=notify.MAX_LINES)
if level_pick:
    _rows = [r for r in _rows if r.get("level") in level_pick]
if kind_pick:
    _rows = [r for r in _rows if r.get("kind") in kind_pick]

m1, m2, m3, m4 = st.columns(4)
m1.metric("Shown", len(_rows))
m2.metric("Unread when opened", UNSEEN_BEFORE)
m3.metric("Critical", sum(1 for r in _rows if r.get("level") == "critical"))
m4.metric("Total stored", int(COUNT.get("total") or 0))

if not _rows:
    st.info("Nothing matches those filters." if (level_pick or kind_pick) else
            "No notifications yet. They raise themselves - low RAM, low disk, a "
            "failed fetch, an interrupted run - and each carries the fix.")
else:
    st.caption("Newest first. The ring keeps the last %d; the oldest is dropped."
               % notify.MAX_LINES)
    for rec in _rows:
        lvl = rec.get("level") or "info"
        col = notify.LEVEL_COLOR.get(lvl, "#e6ebff")
        ico = notify.LEVEL_ICON.get(lvl, "\u2139\ufe0f")
        c_body, c_btn = st.columns([0.88, 0.12])
        with c_body:
            st.markdown(
                '<div class="nt-card" style="border-left-color:%s">'
                '<div class="nt-t">%s %s</div>%s'
                '<div class="nt-m">%s &middot; %s</div></div>'
                % (col, ico, str(rec.get("text") or "").replace("<", "&lt;"),
                   ('<div class="nt-s">\u2192 %s</div>'
                    % str(rec.get("suggestion") or "").replace("<", "&lt;"))
                   if rec.get("suggestion") else "",
                   str(rec.get("kind") or "general"), str(rec.get("ts") or "")),
                unsafe_allow_html=True)
        with c_btn:
            st.button("\u2716", key="ntd_%s" % rec.get("id"),
                      on_click=notify.dismiss, args=(rec.get("id"),),
                      help="Dismiss this one")
# @@END 009 LIST

# @@BLOCK 010 EXPORT_FOOTER deps=009
st.markdown("---")
_all = notify.entries(limit=notify.MAX_LINES)
st.download_button(
    "\u2b07\ufe0f Download all notifications (.jsonl)",
    data="\n".join(json.dumps(r, ensure_ascii=False) for r in _all).encode("utf-8"),
    file_name="notifications_%s.jsonl" % datetime.now().strftime("%Y%m%d_%H%M%S"),
    mime="application/json", width="stretch")

c1, c2, c3, c4, c5 = st.columns(5)
with c1:
    try:
        st.page_link("app.py", label="\u26a1 Checker", width="stretch")
    except Exception:
        st.caption("app.py")
with c2:
    try:
        st.page_link("pages/3_Mailbox_Reader.py", label="\U0001f4e5 Reader",
                     width="stretch")
    except Exception:
        st.caption("pages/3_Mailbox_Reader.py")
with c3:
    try:
        st.page_link("pages/2_Diagnostics.py", label="\U0001f50d Diagnostics",
                     width="stretch")
    except Exception:
        st.caption("pages/2_Diagnostics.py")
with c4:
    try:
        st.page_link("pages/7_Logs.py", label="\U0001f4dc Logs", width="stretch")
    except Exception:
        st.caption("pages/7_Logs.py")
with c5:
    try:
        st.page_link("pages/6_User_Guide.py", label="\U0001f4d6 Guide", width="stretch")
    except Exception:
        st.caption("pages/6_User_Guide.py")

st.caption("Notification file: `data/%s/%s` - yours alone, capped at %d rows."
           % (os.path.basename(user_file("")) or "anon",
              notify.LOG_NAME, notify.MAX_LINES))
# @@END 010 EXPORT_FOOTER
# @@EOF
