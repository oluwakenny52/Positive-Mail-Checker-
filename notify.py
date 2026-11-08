"""notify.py - per-user, bounded, file-backed notifications.  v13.71

WHY A FILE AND NOT session_state
--------------------------------
session_state is what was killing the container. A notification ring is
append-heavy and read rarely, so it lives on disk and nothing of it is held in
memory between reads. The bell and the Notifications page read the SAME source,
so they can never disagree.

WHERE IT LIVES
--------------
auth.user_dir() -> data/<unlocked hash>/notifications.jsonl. Per user, and
`data/` is already in .gitignore. Headless (a selftest, no Streamlit) falls back
to data/anonlocal, so nothing is ever written bare into the repo root.

BOUNDS
------
MAX_LINES rows, trimmed to that once TRIM_AT is passed, written to .tmp and
os.replace()d. A 300-row file is ~90 KB and cannot grow.

v13.71: THE DEDUPE MAP IS NOW PRUNED.  It held one pair per (scope, key) for the
life of the process and was never emptied, so every condition that had ever fired
for every user who had ever visited stayed resident. Past DEDUPE_MAX entries the
expired pairs are dropped; the same pass trims the per-scope throttle map.

DEDUPE - AND WHY IT IS PER USER
-------------------------------
`key` plus a window, keyed on (scope, key). A condition that is still true bumps
a counter instead of adding a row, so a ten-minute RAM squeeze is one
notification. The SCOPE is in the key because the throttle and the dedupe are
process values: without it user A's low-RAM alert would mute user B's.

THREADS
-------
Every writer can run on the alive-pool daemon, the first-probe thread or the run
heartbeat, so there is one RLock and no session_state in this module.

FAILURE MODE
------------
Every public function swallows: a missing /proc, an unwritable directory or a
stale cached module degrades to "no notification", never to a raised exception on
the script thread.
"""

from __future__ import annotations

import json
import os
import threading
import time

MAX_LINES = 300
TRIM_AT = 450
LOG_NAME = "notifications.jsonl"
SEEN_NAME = "notify_seen.json"
# v13.71: prune the dedupe map once it passes this many pairs.
DEDUPE_MAX = 400

LEVELS = ("info", "warn", "critical")
LEVEL_COLOR = {"info": "#38bdf8", "warn": "#facc15", "critical": "#ef4444"}
LEVEL_ICON = {"info": "\u2139\ufe0f", "warn": "\u26a0\ufe0f", "critical": "\U0001f6a8"}

SYS_MIN_SECONDS = 30.0
SYS_REPEAT_SECONDS = 600.0
RAM_WARN = 0.72
RAM_CRIT = 0.86
DISK_WARN_B = 250 * 1024 * 1024
DISK_CRIT_B = 60 * 1024 * 1024
SESS_WARN_B = 25 * 1024 * 1024

_lock = threading.RLock()
_dedupe = {}
_last_sys = {}
_seq = 0


# ---------------------------------------------------------------------------
# identity and storage
# ---------------------------------------------------------------------------
def _scope():
    """The unlocked prefix, so dedupe and throttling are per user."""
    try:
        import auth
        return os.path.basename(auth.user_file("")) or "anon"
    except Exception:
        return "anon"


def _dir():
    """This user's own directory under data/. Created on demand."""
    try:
        import auth
        return auth.user_dir()
    except Exception:
        d = os.path.join("data", "anonlocal")
        try:
            os.makedirs(d, exist_ok=True)
        except Exception:
            pass
        return d


def _path(name):
    return os.path.join(_dir(), name)


def _log_path():
    return _path(LOG_NAME)


def _read_rows():
    rows = []
    try:
        p = _log_path()
        if not os.path.exists(p):
            return rows
        with open(p, encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                if isinstance(rec, dict) and rec.get("id"):
                    rows.append(rec)
    except Exception:
        pass
    return rows


def _write_rows(rows):
    p = _log_path()
    tmp = p + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            for rec in rows:
                fh.write(json.dumps(rec, separators=(",", ":")) + "\n")
        os.replace(tmp, p)
        return True
    except Exception:
        return False


def _seen_id():
    try:
        p = _path(SEEN_NAME)
        if not os.path.exists(p):
            return ""
        with open(p, encoding="utf-8") as fh:
            return str((json.load(fh) or {}).get("last") or "")
    except Exception:
        return ""


def _write_seen(last):
    p = _path(SEEN_NAME)
    tmp = p + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"last": str(last or "")}, fh)
        os.replace(tmp, p)
    except Exception:
        pass


def _prune(now, window=SYS_REPEAT_SECONDS):
    """Drop dedupe pairs whose window has expired. Called under _lock.

    v13.71: without this the map only ever grew. The longest window in the module
    is SYS_REPEAT_SECONDS, so a pair older than that can never suppress anything
    again and is safe to forget.
    """
    try:
        if len(_dedupe) > DEDUPE_MAX:
            cutoff = float(now) - float(window)
            for k in [k for k, v in _dedupe.items() if float(v[0]) < cutoff]:
                _dedupe.pop(k, None)
        if len(_last_sys) > DEDUPE_MAX:
            cutoff = float(now) - SYS_MIN_SECONDS
            for k in [k for k, v in _last_sys.items() if float(v) < cutoff]:
                _last_sys.pop(k, None)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# write
# ---------------------------------------------------------------------------
def add(level, kind, text, suggestion="", key="", dedupe=SYS_REPEAT_SECONDS):
    """Record one notification. Returns its id, or None when deduped."""
    global _seq
    level = level if level in LEVELS else "info"
    text = str(text or "").strip()
    if not text:
        return None
    now = time.time()
    try:
        with _lock:
            if key:
                dkey = (_scope(), key)
                prev = _dedupe.get(dkey)
                if prev is not None and (now - prev[0]) < float(dedupe):
                    prev[1] += 1
                    return None
                _dedupe[dkey] = [now, 1]
                _prune(now, dedupe)
            rows = _read_rows()
            _seq = (_seq + 1) % 1000
            rec = {
                "id": "%d%03d" % (int(now * 1000), _seq),
                "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
                "epoch": round(now, 1),
                "level": level,
                "kind": str(kind or "")[:40],
                "text": text[:1200],
                "suggestion": str(suggestion or "")[:600],
            }
            rows.append(rec)
            if len(rows) > TRIM_AT:
                rows = rows[-MAX_LINES:]
            _write_rows(rows)
            return rec["id"]
    except Exception:
        return None


def entries(limit=80, level=None):
    """Newest first. `level` filters to one level."""
    try:
        rows = _read_rows()
        if level:
            rows = [r for r in rows if r.get("level") == level]
        return list(reversed(rows[-int(limit or 80):]))
    except Exception:
        return []


def counts():
    """{total, unseen, crit, crit_unseen} - the badge reads this."""
    try:
        rows = _read_rows()
        last = _seen_id()
        unseen = [r for r in rows if str(r.get("id") or "") > last] if last else rows
        return {
            "total": len(rows),
            "unseen": len(unseen),
            "crit": sum(1 for r in rows if r.get("level") == "critical"),
            "crit_unseen": sum(1 for r in unseen if r.get("level") == "critical"),
        }
    except Exception:
        return {"total": 0, "unseen": 0, "crit": 0, "crit_unseen": 0}


def mark_seen():
    try:
        with _lock:
            rows = _read_rows()
            if rows:
                _write_seen(rows[-1].get("id"))
    except Exception:
        pass


def clear():
    try:
        with _lock:
            _write_rows([])
            _write_seen("")
    except Exception:
        pass


def dismiss(nid):
    try:
        with _lock:
            rows = [r for r in _read_rows() if str(r.get("id")) != str(nid)]
            _write_rows(rows)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# system sampling
# ---------------------------------------------------------------------------
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


def _ram():
    """(rss, cgroup_used, cgroup_limit). Zeros off Linux."""
    rss = 0
    try:
        with open("/proc/self/status", encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                if line.startswith("VmRSS:"):
                    rss = int(line.split()[1]) * 1024
                    break
    except Exception:
        pass
    return (rss,
            _cgroup(("/sys/fs/cgroup/memory.current",
                     "/sys/fs/cgroup/memory/memory.usage_in_bytes")),
            _cgroup(("/sys/fs/cgroup/memory.max",
                     "/sys/fs/cgroup/memory/memory.limit_in_bytes")))


def _disk_free():
    try:
        v = os.statvfs(os.getcwd())
        return int(v.f_bavail) * int(v.f_frsize)
    except Exception:
        return 0


def _mb(n):
    try:
        return "%.0f MB" % (float(n) / 1048576.0)
    except Exception:
        return "?"


def system_tick(force=False, session_bytes=0):
    """Raise RAM / disk / payload notifications. Throttled per user, deduped.

    The RAM fraction uses the CGROUP figure when a limit file exists, because
    that - cache included - is the number the OOM killer reads. RSS alone would
    understate it and let the kill arrive unannounced.
    """
    now = time.time()
    scope = _scope()
    if not force and (now - float(_last_sys.get(scope, 0.0))) < SYS_MIN_SECONDS:
        return 0
    _last_sys[scope] = now
    made = 0
    try:
        rss, cused, lim = _ram()
        killer = cused or rss
        if lim and killer:
            frac = float(killer) / float(lim)
            if frac >= RAM_CRIT:
                made += bool(add(
                    "critical", "ram",
                    "Container RAM is nearly exhausted: %s of %s used (%.0f%%). "
                    "Streamlit Cloud kills the app at the limit."
                    % (_mb(killer), _mb(lim), frac * 100),
                    "Press Free my RAM, set Workers Start to 10-20, shorten the "
                    "paste, then reboot the app. Nothing on disk is lost by any of it.",
                    key="ram-crit"))
            elif frac >= RAM_WARN:
                made += bool(add(
                    "warn", "ram",
                    "Container RAM is getting tight: %s of %s (%.0f%%)."
                    % (_mb(killer), _mb(lim), frac * 100),
                    "Trim the session payload and keep the paste short before "
                    "starting another run.", key="ram-warn"))
        free = _disk_free()
        if free:
            if free <= DISK_CRIT_B:
                made += bool(add(
                    "critical", "disk",
                    "Only %s of disk free - a result write can fail with ENOSPC."
                    % _mb(free),
                    "Export what you need, then Delete my cache files and Delete my "
                    "RESULT files, then reboot.", key="disk-crit"))
            elif free <= DISK_WARN_B:
                made += bool(add(
                    "warn", "disk",
                    "Low free disk space: %s left." % _mb(free),
                    "Clear cache and old result files before the next run.",
                    key="disk-warn"))
        try:
            sess = int(session_bytes or 0)
        except Exception:
            sess = 0
        if sess >= SESS_WARN_B:
            made += bool(add(
                "warn", "payload",
                "My session payload is %s - this is the part that causes the kills."
                % _mb(sess),
                "Press Free my RAM. Your files on disk are untouched by it.",
                key="payload"))
    except Exception:
        pass
    return made


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------
_BELL_CSS = """
<style>
[data-testid="stPopover"] button {
    border-radius: 999px !important;
    border: 1px solid rgba(255,255,255,.18) !important;
    padding: .18rem .55rem !important;
    font-weight: 700 !important;
    min-height: 2.1rem;
}
[data-testid="stPopover"] button:hover { border-color: #8b5cf6 !important; }
.nt-row { display:flex; gap:8px; align-items:flex-start; padding:5px 0;
          border-bottom:1px solid rgba(255,255,255,.07); }
.nt-ico { font-size:.9rem; line-height:1.2; }
.nt-txt { font-size:.76rem; line-height:1.35; flex:1; }
.nt-when { font-size:.63rem; opacity:.55; }
.nt-sug { font-size:.71rem; opacity:.82; margin-top:2px; }
.nt-kind { font-size:.6rem; opacity:.6; text-transform:uppercase; letter-spacing:.04em; }
</style>
"""


def _esc(text):
    return str(text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def render_bell(st):
    """The bell, the red count and the dropdown. Degrades to a caption."""
    try:
        c = counts()
    except Exception:
        c = {"unseen": 0, "crit_unseen": 0, "total": 0}
    n = int(c.get("unseen") or 0)
    label = "\U0001f514" if not n else "\U0001f514 :red[**%s**]" % ("99+" if n > 99 else n)
    try:
        st.markdown(_BELL_CSS, unsafe_allow_html=True)
        with st.popover(label, help="Notifications (%d unread)" % n):
            h1, h2 = st.columns([0.55, 0.45])
            with h1:
                st.markdown("**Notifications**")
            with h2:
                if n:
                    st.caption("%d unread" % n)
            if c.get("crit"):
                st.caption("%d critical in total" % c["crit"])

            rows = entries(limit=25)
            if not rows:
                st.caption("Nothing yet. Resource alerts and run events land here.")
            for rec in rows:
                lvl = rec.get("level") or "info"
                st.markdown(
                    '<div class="nt-row"><div class="nt-ico">%s</div>'
                    '<div class="nt-txt"><span style="color:%s">%s</span>'
                    ' <span class="nt-kind">%s</span>'
                    '<div class="nt-when">%s</div>%s</div></div>'
                    % (LEVEL_ICON.get(lvl, "\u2139\ufe0f"),
                       LEVEL_COLOR.get(lvl, "#e6ebff"),
                       _esc(rec.get("text")),
                       _esc(rec.get("kind")),
                       _esc(rec.get("ts")),
                       ('<div class="nt-sug">\u2192 %s</div>'
                        % _esc(rec.get("suggestion")))
                       if rec.get("suggestion") else ""),
                    unsafe_allow_html=True)

            st.markdown("---")
            b1, b2 = st.columns(2)
            with b1:
                st.button("Mark all read", key="nt_mark", on_click=mark_seen,
                          width="stretch")
            with b2:
                st.button("Clear all", key="nt_clear", on_click=clear,
                          width="stretch")
            try:
                st.page_link("pages/1_Notifications.py",
                             label="Open the notifications page", width="stretch")
            except Exception:
                st.caption("Full list: pages/1_Notifications.py")
    except Exception:
        try:
            st.caption("\U0001f514 %d" % n)
        except Exception:
            pass
