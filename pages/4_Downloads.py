# @@FILE pages/4_Downloads.py blocks=16 version=v13.55
# @@BLOCK 000 FILE_HEADER deps=-
"""
pages/4_Downloads.py — Bobito Export Studio  (v13.55)
=====================================================
Pick WHAT to download, pick HOW it is written, preview it, take it.

Pure reader: no mailbox connection, no proxy credit. Sources are the result
files the checker already wrote, plus the live session buckets.

v13.44 fix on this page
-----------------------
* PER-USER PRESETS: the preset store resolves through user_file() at call time.
  It used to be built at import time in block 002, which runs BEFORE the gate,
  so the path never carried the unlocked hash and every user on the deployment
  shared one preset store.

v13.47 fixes on this page
-------------------------
* DISPLAY FIT PANEL: auth.fit_panel() is called in block 005. auth.fit() injects
  the CSS only, so without this call the Display Fit control was missing here.
  The expander stays collapsed until it is tapped.
* LAST-ACCOUNT FILE: "last_account" is an IGNORE_TOKEN now.
* EX_TPL DEFAULT: value= is gone; the key is seeded by the preset branch.

v13.55 fixes on this page
-------------------------
* DEDUPE KEPT THE WRONG ROW. "first wins" ran before any ordering, so the row
  that survived was whichever file happened to be read first - a VALID address
  could be thrown away in favour of the FAILED copy of the same email. Dedupe
  is now rank-aware: the strongest status wins, order-independent.
* EVERY FILE WAS RE-READ ON EVERY RERUN just to print its line count. The count
  is cached against (mtime, size), so the Sources box no longer touches the disk
  on a rerun.
* RETIRED SOURCES ARE VISIBLE NOW. Each source shows its age, and a Hide-older-
  than control defaults to 7 days so a file from an old pool cannot silently pad
  an export. The count that was hidden is stated.
* {status} in the file name was taken from picked[0], so a mixed export was
  named after whichever source sorted first. It now reflects the strongest
  status actually exported.
* _delim_map[delim] raised KeyError on any preset carrying an unknown separator.
* A 200k row cap with a visible note keeps a runaway export off the phone.
"""

import os
import re
import io
import csv
import json
import glob
import time
import zipfile
from datetime import datetime

import streamlit as st
# @@END 000 FILE_HEADER


# @@BLOCK 001 PAGE_CONFIG deps=000
st.set_page_config(
    page_title="Export Studio · Downloads",
    page_icon="📦",
    layout="wide",
    initial_sidebar_state="collapsed",
)
# @@END 001 PAGE_CONFIG


# @@BLOCK 002 APP_PATHS deps=000
APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _preset_file() -> str:
    """v13.44: per-user export presets.

    PRESET_FILE was built at import time in block 002, which runs BEFORE the
    gate, so the path never carried the unlocked hash and every user on the
    deployment shared one preset store.
    """
    return user_file("download_presets.json")
# @@END 002 APP_PATHS


# @@BLOCK 003 THEME deps=002
# --------------------------------------------------------------------------
# theme mirror
# --------------------------------------------------------------------------
def _load_theme():
    base = {"bg": "#0b1020", "panel": "#141b30", "text": "#e6ebff",
            "accent": "#8b5cf6", "accent2": "#22d3ee", "g1": "#667eea", "g2": "#764ba2"}
    for cand in (os.path.join(APP_DIR, "theme.json"), "theme.json"):
        try:
            if os.path.exists(cand):
                with open(cand, encoding="utf-8") as f:
                    data = json.load(f)
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
    .ex-hero {
        background: linear-gradient(135deg, __G1__ 0%, __G2__ 100%);
        padding: 18px 24px; border-radius: 14px; margin-bottom: 14px;
        border: 1px solid rgba(255,255,255,.12);
    }
    .ex-hero h1 { color: #fff !important; margin: 0; font-size: 1.45rem; font-weight: 800; }
    .ex-hero p { color: rgba(255,255,255,.93) !important; margin: 6px 0 0 0; font-size: .84rem; }
    [data-testid="stSidebar"] p, [data-testid="stSidebar"] label,
    [data-testid="stSidebar"] .stMarkdown span { color: __TEXT__; }
    .ex-box {
        background: __BG__; border: 1px solid rgba(255,255,255,.10);
        border-radius: 10px; padding: 10px 12px; overflow-x: auto;
        font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: .74rem;
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
        .ex-hero { padding: 12px 14px !important; }
        .ex-hero h1 { font-size: 1.15rem !important; }
        .ex-box { font-size: .66rem !important; }
    }
</style>
"""

_CSS = (_CSS_TMPL
        .replace("__G1__", _TH["g1"])
        .replace("__G2__", _TH["g2"])
        .replace("__BG__", _TH["bg"])
        .replace("__TEXT__", _TH["text"]))

st.markdown(_CSS, unsafe_allow_html=True)
# @@END 004 CSS


# @@BLOCK 005 HERO deps=002,004
st.markdown(
    '<div class="ex-hero"><h1>📦 Export Studio</h1>'
    '<p>Choose what to download, choose the exact format, preview it, take it. '
    'No mailbox connection, no proxy credit spent.</p></div>',
    unsafe_allow_html=True,
)

import sys as _sys

if APP_DIR not in _sys.path:
    _sys.path.insert(0, APP_DIR)

import importlib

import auth

if not hasattr(auth, "fit_panel"):
    auth = importlib.reload(auth)

from auth import user_file         # AFTER the reload, so it binds to the live module

import audit_log as _audit

if not (hasattr(_audit, "page") and hasattr(_audit, "install")):
    try:
        _audit = importlib.reload(_audit)
    except Exception:
        pass
audit_log = _audit

if hasattr(audit_log, "page"):
    audit_log.page("pages/4_Downloads.py")

auth.require(st, "Unlock Export Studio")
auth.fit(st)                        # CSS only, before the first widget

if hasattr(audit_log, "install"):
    audit_log.install(st, "pages/4_Downloads.py")

auth.fit_panel(st)                  # the controls; collapsed until tapped
# @@END 005 HERO


# @@BLOCK 006 SOURCE_TABLES deps=002
# --------------------------------------------------------------------------
# sources
# --------------------------------------------------------------------------
def _results_dir():
    """v13.45: the SAME per-user prefix app.py writes with."""
    return user_file("mail_results")


# v13.48: PER-USER OWNERSHIP of a source file. The root glob reaches every
# user's <hash>_*.txt. The prefix is DERIVED from user_file(""), the same
# function that names the files, so no second identity source can drift.
_HASH_RX = re.compile(r"^(?:anon)?[0-9a-f]{16}_")


def _prefix() -> str:
    try:
        return os.path.basename(user_file("")) or ""
    except Exception:
        return ""


def _own(path) -> bool:
    """False only for a file that is prefixed to somebody else."""
    base = os.path.basename(path)
    if not _HASH_RX.match(base):
        return True
    pfx = _prefix()
    return bool(pfx) and base.startswith(pfx)


IGNORE = {
    "last_account.txt", "proxies.txt", "proxies_all.txt", "disposable_domains.txt",
    "clean_proxies.txt", "proxy_pool.txt", "download_presets.json",
}
# v13.63: paste_accounts.txt and inspect_cat.txt are app.py's own input and
# viewer state. They are .txt in the same directory, so without these two tokens
# they were offered as exportable sources with a MIXED status.
IGNORE_TOKENS = ("resume", "unfinished", "remaining", "input", "proxies", "config",
                 "last_account", "paste_accounts", "inspect_cat")

# v13.55: STRONGEST STATUS WINS on dedupe. Without a rank the survivor of a
# duplicate email was whichever file was read first, so a VALID address could be
# exported as its FAILED copy. Higher number = stronger, and VALID must beat
# everything or the export can only ever be pessimistic.
_STATUS_RANK = {
    "VALID": 90, "WRONG_PASSWORD": 80, "NEED_APP_PASSWORD": 78, "RBL_BLOCKED": 70,
    "LOGIN_DROPPED": 60, "APP_PASSWORD": 58, "SMTP_FAILED": 50, "DNS_FAILED": 45,
    "PROXY_UNHEALTHY": 40, "CONNECTION_FAILED": 35, "RETRY_LATER": 30,
    "SKIPPED": 20, "UNKNOWN": 10, "MIXED": 5,
}

_COUNT_CACHE = {}


def _status_of(path):
    n = os.path.basename(path).lower()
    if "clean_valid" in n or "manual_valid" in n or "valid_accounts" in n:
        return "VALID"
    # FIX DL-3: most-specific token first.
    for tag, word in (("LOGIN_DROPPED", "login_dropped"), ("NEED_APP_PASSWORD", "need_app"),
                      ("PROXY_UNHEALTHY", "proxy_unhealthy"), ("RETRY_LATER", "retry_later"),
                      ("RBL_BLOCKED", "rbl_blocked"), ("SMTP_FAILED", "smtp_failed"),
                      ("DNS_FAILED", "dns_failed"), ("SKIPPED", "skipped"),
                      ("UNKNOWN", "unclassified"), ("CONNECTION_FAILED", "failed"),
                      ("WRONG_PASSWORD", "wrong"), ("VALID", "valid")):
        if word in n:
            return tag
    return "MIXED"


def _count_lines(path):
    """v13.55: cached against (mtime, size).

    This used to open and read every source file on EVERY rerun - with a hundred
    result files on a phone that is a hundred disk reads per keystroke.
    """
    try:
        s = os.stat(path)
    except Exception:
        return 0
    sig = (s.st_mtime, s.st_size)
    hit = _COUNT_CACHE.get(path)
    if hit and hit[0] == sig:
        return hit[1]
    n = 0
    try:
        with open(path, encoding="utf-8", errors="ignore") as _fh:
            n = sum(1 for l in _fh if l.strip() and not l.startswith("#"))
    except Exception:
        n = 0
    _COUNT_CACHE[path] = (sig, n)
    return n


def _age_txt(path):
    try:
        d = max(0, int(time.time() - os.path.getmtime(path)))
    except Exception:
        return "?"
    if d < 90:
        return f"{d}s old"
    if d < 5400:
        return f"{d // 60}m old"
    if d < 172800:
        return f"{d // 3600}h old"
    return f"{d // 86400}d old"


def _sources():
    """PATH -> LABEL.  The PATH is the option key because it is STABLE.

    v13.63 - WHY "SELECTING ONE SOURCE SELECTED THEM ALL".  _age_txt() was
    interpolated INTO the label and the label WAS the option string, so every
    option changed on almost every rerun ("3m old" -> "4m old"). st.multiselect
    had no key= either, so its widget identity was derived from its parameters
    and changed with the options - and it fell back to default=_def_labels,
    which is every source. A selection could never survive one rerun.

    The path is the key now, the label is only what format_func draws, and the
    widget carries key="ex_sources" of its own.
    """
    out = {}
    for pat in (os.path.join(_results_dir(), "*.txt"), "*.txt"):
        for p in glob.glob(os.path.join(APP_DIR, pat)):
            b = os.path.basename(p)
            if b in IGNORE or any(t in b.lower() for t in IGNORE_TOKENS):
                continue
            if not _own(p):
                continue
            n = _count_lines(p)
            if n:
                # v13.55: the age stays in the LABEL, so a retired file is
                # visible as retired instead of looking like current output.
                out[p] = (f"{os.path.basename(os.path.dirname(p))}/{b}  ({n})  ·  "
                          f"{_age_txt(p)}")
    return dict(sorted(out.items(), key=lambda kv: kv[1]))


SESSION_BUCKETS = [
    ("Session · valid_results", "valid_results", "VALID"),
    ("Session · wrong_results", "wrong_results", "WRONG_PASSWORD"),
    ("Session · need_app_results", "need_app_results", "NEED_APP_PASSWORD"),
    ("Session · login_drop_results", "login_drop_results", "LOGIN_DROPPED"),
    ("Session · conn_results", "conn_results", "CONNECTION_FAILED"),
    ("Session · proxy_results", "proxy_results", "PROXY_UNHEALTHY"),
    ("Session · retry_results", "retry_results", "RETRY_LATER"),
    ("Session · rbl_results", "rbl_results", "RBL_BLOCKED"),
    ("Session · skip_results", "skip_results", "SKIPPED"),
    ("Session · unknown_results", "unknown_results", "UNKNOWN"),
]
_BUCKET_TAG = {key: tag for _label, key, tag in SESSION_BUCKETS}


def _session_sources():
    """BUCKET KEY -> LABEL.  Same stability reason as _sources()."""
    out = {}
    for label, key, _tag in SESSION_BUCKETS:
        items = st.session_state.get(key) or []
        if items:
            out[key] = f"{label}  ({len(items)})"
    return out


FIELDS = ["email", "password", "domain", "local", "status", "host", "port",
          "detail", "time", "n", "source"]

FORMAT_PRESETS = {
    "email:password": "{email}:{password}",
    "email|password": "{email}|{password}",
    "email;password": "{email};{password}",
    "email,password (csv row)": "{email},{password}",
    "user:pass@host:port": "{email}:{password}@{host}:{port}",
    "host:port:user:pass": "{host}:{port}:{email}:{password}",
    "email:password:host:port": "{email}:{password}:{host}:{port}",
    "email only": "{email}",
    "email|password|status": "{email}|{password}|{status}",
    "full annotated": "{n} | {email}:{password} | {status} | {host}:{port} | {detail}",
    "CUSTOM": "",
}
# @@END 006 SOURCE_TABLES


# @@BLOCK 007 PARSERS deps=006
def _parse(line, source, status_hint):
    raw = line.rstrip("\n")
    if not raw.strip() or raw.startswith("#"):
        return None
    if " | " in raw:
        combo, _, rest = raw.partition(" | ")
    elif "|" in raw:
        _colon = raw.find(":")
        _cut = raw.find("|", _colon + 1) if _colon != -1 else -1
        combo, rest = (raw[:_cut], raw[_cut + 1:]) if _cut != -1 else (raw, "")
    else:
        combo, rest = raw, ""
    combo = combo.strip().strip('"\'')
    if ":" not in combo:
        return None
    email, _, pw = combo.partition(":")
    email = email.strip()
    if "@" not in email:
        return None
    local, _, dom = email.partition("@")
    detail = rest.strip()
    host = port = ""
    m = re.search(r"([a-z0-9][a-z0-9.\-]*\.[a-z]{2,}):(\d{2,5})", detail, re.I)
    if m:
        host, port = m.group(1), m.group(2)
    st_tag = status_hint
    tm = re.search(r"\b([A-Z_]{4,})\b", detail)
    if status_hint == "MIXED" and tm:
        st_tag = tm.group(1)
    return {
        "email": email, "password": pw.strip(), "domain": dom.lower(),
        "local": local, "status": st_tag, "host": host, "port": port,
        "detail": detail, "time": "", "n": 0, "source": source,
        "line": raw,
    }


def _load(selection):
    """v13.63: `selection` holds KEYS - a result-file path or a bucket key."""
    rows = []
    srcs = _sources()
    sess = _session_sources()
    for key in selection:
        if key in sess:
            tag = _BUCKET_TAG.get(key, "MIXED")
            for ln in st.session_state.get(key) or []:
                r = _parse(str(ln), sess[key], tag)
                if r:
                    rows.append(r)
        elif key in srcs:
            tag = _status_of(key)
            try:
                with open(key, encoding="utf-8", errors="ignore") as fh:
                    for ln in fh:
                        r = _parse(ln, os.path.basename(key), tag)
                        if r:
                            rows.append(r)
            except Exception as ex:
                st.warning(f"{srcs.get(key, key)}: {ex}")
    return rows
# @@END 007 PARSERS


# @@BLOCK 008 FORMATTERS deps=007
MAX_ROWS = 200_000


def _fmt(rows, template, delim, crlf, header, prefix, suffix,
         sort_key, dedupe, lower, regex_inc, regex_exc, host_filter):
    sel = rows
    if regex_inc:
        try:
            rx = re.compile(regex_inc)
            sel = [r for r in sel if rx.search(r["line"])]
        except re.error as e:
            st.warning(f"include regex: {e}")
    if regex_exc:
        try:
            rx = re.compile(regex_exc)
            sel = [r for r in sel if not rx.search(r["line"])]
        except re.error as e:
            st.warning(f"exclude regex: {e}")
    if host_filter.strip():
        want = {h.strip().lower() for h in host_filter.split(",") if h.strip()}
        sel = [r for r in sel if r["host"].lower() in want]

    # v13.55: DEDUPE BY RANK, not by file order. The first row of a duplicate
    # email used to win, so reading failed_ before valid_ exported the failure.
    # The strongest status now wins regardless of which file it came from, and
    # on a tie the earliest row is kept so the output stays deterministic.
    if dedupe:
        best = {}
        for r in sel:
            cur = best.get(r["email"])
            if cur is None or _STATUS_RANK.get(r["status"], 0) > \
                    _STATUS_RANK.get(cur["status"], 0):
                best[r["email"]] = r
        sel = list(best.values())

    if sort_key == "email":
        sel = sorted(sel, key=lambda r: r["email"])
    elif sort_key == "domain":
        sel = sorted(sel, key=lambda r: (r["domain"], r["email"]))
    elif sort_key == "status":
        sel = sorted(sel, key=lambda r: (-_STATUS_RANK.get(r["status"], 0), r["email"]))

    _truncated = 0
    if len(sel) > MAX_ROWS:
        _truncated = len(sel) - MAX_ROWS
        sel = sel[:MAX_ROWS]

    out = []
    for i, r in enumerate(sel, 1):
        r["n"] = i
        e = r["email"].lower() if lower else r["email"]
        d = dict(r)
        d["email"] = e
        try:
            line = template.format(**d)
        except KeyError as ke:
            line = r["line"]
            st.session_state["_fmt_bad"] = str(ke)
        if delim != " " and " " not in template:
            line = line.replace(" ", delim)
        out.append(line)

    text = ("\n" if not crlf else "\r\n").join(out)
    if header.strip():
        text = header + ("\n" if not crlf else "\r\n") + text
    if prefix.strip():
        text = prefix + ("\n" if not crlf else "\r\n") + text
    if suffix.strip():
        text = text + ("\n" if not crlf else "\r\n") + suffix
    st.session_state["_fmt_truncated"] = _truncated
    return sel, text


def _csv_of(rows, sep):
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=sep, lineterminator="\n")
    w.writerow(["email", "password", "domain", "status", "host", "port", "detail"])
    for r in rows:
        w.writerow([r["email"], r["password"], r["domain"], r["status"],
                    r["host"], r["port"], r["detail"]])
    return buf.getvalue()


def _json_of(rows, lines=True):
    if lines:
        return "\n".join(json.dumps({k: r[k] for k in
                                     ("email", "password", "domain", "status", "host", "port", "detail")})
                         for r in rows)
    return json.dumps([{k: r[k] for k in
                        ("email", "password", "domain", "status", "host", "port", "detail")}
                       for r in rows], indent=2)
# @@END 008 FORMATTERS


# @@BLOCK 009 PRESETS_IO deps=002
def _presets():
    try:
        if os.path.exists(_preset_file()):
            with open(_preset_file(), encoding="utf-8") as f:
                return json.load(f) or {}
    except Exception:
        pass
    return {}


def _save_presets(d):
    try:
        with open(_preset_file(), "w", encoding="utf-8") as f:
            json.dump(d, f, indent=2)
    except Exception:
        pass
# @@END 009 PRESETS_IO


# @@BLOCK 010 SIDEBAR deps=006
# --------------------------------------------------------------------------
# sidebar — source + format
# --------------------------------------------------------------------------
srcs = _sources()
sess = _session_sources()

_pending_preset = st.session_state.pop("_ex_apply", None)
if _pending_preset:
    _pp = _presets().get(_pending_preset) or {}
    if _pp:
        st.session_state["ex_tpl"] = _pp.get("template", "{email}:{password}")
        st.session_state["ex_delim"] = _pp.get("delim", "none")
        st.session_state["ex_eol"] = _pp.get("eol", "LF (unix)")
        st.session_state["ex_header"] = _pp.get("header", "")
        st.session_state["ex_prefix"] = _pp.get("prefix", "")
        st.session_state["ex_suffix"] = _pp.get("suffix", "")
        st.session_state["ex_sort"] = _pp.get("sort", "none")
        st.session_state["ex_dedupe"] = bool(_pp.get("dedupe", True))
        st.session_state["ex_lower"] = bool(_pp.get("lower", True))
        st.session_state["ex_name"] = _pp.get("name_pat", "export_{status}_{count}_{stamp}")
        # v13.63: the preset carries the SOURCES too. It used to reach a local in
        # block 011 only, so the box on screen kept the old selection while the
        # export used the preset's. Legal here: no widget exists yet this run.
        _avail_now = set(sess) | set(srcs)
        st.session_state["ex_sources"] = [s for s in (_pp.get("sources") or [])
                                          if s in _avail_now]
        st.session_state["_ex_active"] = _pending_preset

_EX_DEFAULTS = {
    "ex_tpl": "",
    "ex_delim": "none",
    "ex_eol": "LF (unix)",
    "ex_header": "",
    "ex_prefix": "",
    "ex_suffix": "",
    "ex_sort": "none",
    "ex_dedupe": True,
    "ex_lower": True,
    "ex_name": "export_{status}_{count}_{stamp}",
    "ex_inc": "",
    "ex_exc": "",
    "ex_hosts": "",
    "ex_pname": "",
    "ex_age": "7 days",
}
for _k, _v in _EX_DEFAULTS.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v

with st.sidebar:
    st.markdown("### 1. What to download")
    labels = list(sess.keys()) + list(srcs.keys())
    _label_of = dict(sess)
    _label_of.update(srcs)
    if not labels:
        st.info("No result files yet. Run the checker, or validate a batch in the Reader.")
        st.stop()

    # v13.55: RETIRED FILES ARE HIDEABLE. Every result file from every past run
    # used to be preselected, so an export silently padded itself with accounts
    # measured against a dead pool. Age is a filter now and the hidden count is
    # stated; session buckets are always kept because they ARE this run.
    age_win = st.selectbox("File age", ["24 hours", "7 days", "30 days", "all"],
                           key="ex_age",
                           help="Session buckets are always included - they are the "
                                "live run. This only limits the FILES on disk.")
    _age_cut = {"24 hours": 86400, "7 days": 604800,
                "30 days": 2592000, "all": None}[age_win]
    _fresh, _old = [], 0
    for _lab in srcs:
        try:
            _ok_age = (_age_cut is None
                       or (time.time() - os.path.getmtime(_lab)) <= _age_cut)
        except Exception:
            _ok_age = True
        if _ok_age:
            _fresh.append(_lab)
        else:
            _old += 1
    _def_labels = list(sess.keys()) + _fresh

    # v13.63: two one-click helpers, on_click so no widget key is written after
    # its widget exists.
    st.session_state["_ex_all_opts"] = list(labels)

    def _ex_pick_all():
        st.session_state["ex_sources"] = list(st.session_state.get("_ex_all_opts") or [])

    def _ex_pick_none():
        st.session_state["ex_sources"] = []

    _sel_a, _sel_b = st.columns(2)
    with _sel_a:
        st.button("Select all", width="stretch", on_click=_ex_pick_all)
    with _sel_b:
        st.button("Clear selection", width="stretch", on_click=_ex_pick_none)

    # v13.63: THE SELECTION IS SEEDED, NOT DEFAULTED. default= plus key= raises
    # the "created with a default value but also had its value set via the
    # Session State API" warning, so the seed is written here and the widget
    # passes key= only. A remembered value is filtered against the CURRENT
    # options so a retired file cannot linger; an empty remembered value stays
    # empty, and only a value whose every entry retired falls back to the
    # age-filtered default.
    _stored_pick = st.session_state.get("ex_sources")
    if _stored_pick is None:
        _seed_pick = [k for k in _def_labels if k in labels]
    else:
        _seed_pick = [k for k in _stored_pick if k in labels]
        if not _seed_pick and _stored_pick:
            _seed_pick = [k for k in _def_labels if k in labels]
    st.session_state["ex_sources"] = _seed_pick

    picked = st.multiselect(
        "Sources", labels, key="ex_sources",
        format_func=lambda k: _label_of.get(k, str(k)),
        help="Multi-select. Add ANY session bucket or any mail_results file. The "
             "selection survives a rerun and a refresh now, and the age shown in "
             "a label can no longer reset it.")
    st.caption(f"{len(labels)} source(s) available · {len(_def_labels)} preselected "
               f"by the age filter · {_old} file(s) older than {age_win} hidden.")

    st.markdown("---")
    st.markdown("### 2. How to write it")
    fmt_name = st.selectbox("Format", list(FORMAT_PRESETS.keys()), index=0)
    default_tpl = FORMAT_PRESETS[fmt_name]
    if st.session_state.get("_ex_fmt_seen") != fmt_name:
        st.session_state["_ex_fmt_seen"] = fmt_name
        if default_tpl and not st.session_state.get("_ex_active"):
            st.session_state["ex_tpl"] = default_tpl
    template = st.text_input(
        "Template ({email} {password} {domain} {local} {status} {host} {port} {detail} {n})",
        key="ex_tpl",
    )
    if fmt_name == "CUSTOM" and not template.strip():
        template = "{email}:{password}"

    delim = st.selectbox("Separator inside a line", ["none", "tab", "comma", "semicolon", "pipe"],
                         key="ex_delim",
                         help="'none' keeps the template exactly as written.")
    st.caption("Only affects templates that contain spaces — the default template has none, so this control does nothing for it.")
    _delim_map = {"none": " ", "tab": "\t", "comma": ",", "semicolon": ";", "pipe": "|"}
    delim_ch = _delim_map.get(delim, " ")

    eol = st.radio("Line ending", ["LF (unix)", "CRLF (windows)"], horizontal=True, key="ex_eol")
    crlf = eol.startswith("CRLF")

    header = st.text_input("Header line (optional)", key="ex_header")
    prefix = st.text_input("Prefix line (optional)", key="ex_prefix")
    suffix = st.text_input("Suffix line (optional)", key="ex_suffix")

    st.markdown("---")
    st.markdown("### 3. Filter and order")
    sort_key = st.selectbox("Sort by", ["none", "email", "domain", "status"], key="ex_sort")
    dedupe = st.toggle("Dedupe by email (strongest status wins)", key="ex_dedupe")
    lower = st.toggle("Lowercase email", key="ex_lower")
    regex_inc = st.text_input("Include regex", key="ex_inc")
    regex_exc = st.text_input("Exclude regex", key="ex_exc")
    host_filter = st.text_input("Only these hosts (comma)", key="ex_hosts")

    st.markdown("---")
    st.markdown("### 4. File name")
    name_pat = st.text_input("Name pattern",
                             key="ex_name",
                             help="{status} {count} {stamp} {sources} are substituted.")

    st.markdown("---")
    st.markdown("### 5. Presets")
    _ps = _presets()
    pname = st.text_input("Preset name", key="ex_pname")
    c1, c2 = st.columns(2)
    with c1:
        if st.button("Save preset", width="stretch") and pname.strip():
            _ps[pname.strip()] = {"template": template, "delim": delim, "eol": eol,
                                  "header": header, "prefix": prefix, "suffix": suffix,
                                  "sort": sort_key, "dedupe": dedupe, "lower": lower,
                                  "sources": picked, "name_pat": name_pat}
            _save_presets(_ps)
            st.success(f"Saved '{pname.strip()}'")
    with c2:
        if _ps:
            p_use = st.selectbox("Load preset", ["--"] + sorted(_ps.keys()))
            if p_use != "--" and st.button("Apply", width="stretch"):
                st.session_state["_ex_apply"] = p_use
                st.rerun()
# @@END 010 SIDEBAR


# @@BLOCK 011 PRESET_APPLY deps=010
# Block 010 already seeded every preset-backed widget key BEFORE those widgets
# were created - the only point where writing a widget key is legal.
_p = _presets().get(st.session_state.pop("_ex_active", None) or "") or {}
if _p:
    template = _p.get("template", template)
    delim = _p.get("delim", delim)
    # v13.55: .get, not []. A preset saved before a separator was renamed raised
    # KeyError here and the whole page died on load.
    delim_ch = _delim_map.get(delim, " ")
    crlf = str(_p.get("eol", eol)).startswith("CRLF")
    header = _p.get("header", header)
    prefix = _p.get("prefix", prefix)
    suffix = _p.get("suffix", suffix)
    sort_key = _p.get("sort", sort_key)
    dedupe = _p.get("dedupe", dedupe)
    lower = _p.get("lower", lower)
    name_pat = _p.get("name_pat", name_pat)
    picked = [s for s in _p.get("sources", picked) if s in labels] or picked
# @@END 011 PRESET_APPLY


# @@BLOCK 012 BUILD deps=011
# --------------------------------------------------------------------------
# build
# --------------------------------------------------------------------------
rows = _load(picked)
sel, text = _fmt(rows, template, delim_ch, crlf, header, prefix, suffix,
                 sort_key, dedupe, lower, regex_inc, regex_exc, host_filter)

# v13.63: a built ZIP is discarded the moment any input that fed it changes, so
# it can never be downloaded against a different row set than the one on screen.
# The signature is built from the INPUTS, not from fname - fname carries a
# seconds-resolution {stamp} and would invalidate it every second.
_zip_sig = (tuple(picked), template, delim, crlf, header, prefix, suffix, sort_key,
            dedupe, lower, regex_inc, regex_exc, host_filter)
if st.session_state.get("_ex_zip_sig") != _zip_sig:
    st.session_state["_ex_zip_sig"] = _zip_sig
    st.session_state.pop("_ex_zip", None)

# v13.55: {status} came from picked[0], so a mixed export was named after
# whichever source happened to sort first. It now reflects what is IN the file,
# and only when every exported row agrees.
_statuses = {r["status"] for r in sel}
if len(_statuses) == 1:
    _status_tag = _statuses.pop().lower()
else:
    _status_tag = "mixed"

stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
fname = (name_pat.replace("{stamp}", stamp)
         .replace("{count}", str(len(sel)))
         .replace("{status}", _status_tag)
         .replace("{sources}", str(len(picked))))
if "." not in os.path.basename(fname):
    fname += ".txt"

m1, m2, m3, m4 = st.columns(4)
m1.metric("Sources picked", len(picked))
m2.metric("Rows read", len(rows))
m3.metric("Rows exported", len(sel))
m4.metric("Bytes", f"{len(text.encode('utf-8')):,}")

if st.session_state.get("_fmt_bad"):
    st.warning(f"Unknown placeholder in the template: {st.session_state.pop('_fmt_bad')} "
               f"- valid ones are {', '.join('{'+f+'}' for f in FIELDS)}")

_tr = int(st.session_state.get("_fmt_truncated") or 0)
if _tr:
    st.warning(f"Row cap reached: {MAX_ROWS:,} exported, {_tr:,} dropped. Narrow the "
               f"sources or a filter to take the rest.")

if not sel:
    st.info("Nothing matched. Widen the sources or clear a filter.")
    st.stop()

st.markdown("#### Preview (first 60 lines)")
st.code("\n".join(text.splitlines()[:60]) or "(empty)", language="text")

st.download_button(
    f"⬇️ Download {fname}",
    data=text.encode("utf-8"),
    file_name=fname,
    mime="text/plain",
    type="primary",
    width="stretch",
)
# @@END 012 BUILD


# @@BLOCK 013 TABS deps=012
tab_txt, tab_csv, tab_json, tab_zip, tab_break = st.tabs(
    ["Text / template", "CSV", "JSON", "ZIP (all formats)", "Per-status split"]
)

with tab_txt:
    st.caption("Exactly what the download button produces. The copy icon is top-right. "
               "The box scrolls - the page does not grow to 200k lines.")
    with st.container(height=420):
        st.code(text, language="text")

with tab_csv:
    sep_choice = st.radio("CSV separator", ["comma", "semicolon", "tab"], horizontal=True,
                          key="ex_csv_sep")
    _sep = {"comma": ",", "semicolon": ";", "tab": "\t"}[sep_choice]
    ctext = _csv_of(sel, _sep)
    st.download_button("⬇️ Download CSV", data=ctext.encode("utf-8"),
                       file_name=fname.rsplit(".", 1)[0] + ".csv",
                       mime="text/csv", width="stretch")
    st.code("\n".join(ctext.splitlines()[:30]), language="text")

with tab_json:
    jl = st.toggle("JSON Lines (one object per row)", value=True, key="ex_jsonl")
    jtext = _json_of(sel, lines=jl)
    st.download_button("⬇️ Download JSON", data=jtext.encode("utf-8"),
                       file_name=fname.rsplit(".", 1)[0] + (".jsonl" if jl else ".json"),
                       mime="application/json", width="stretch")
    st.code("\n".join(jtext.splitlines()[:30]), language="text")

with tab_zip:
    st.caption("One archive containing the template file, CSV, JSON and a per-status split.")
    # v13.63: THE ZIP DOWNLOAD BUTTON WAS DEAD. Clicking a download_button fires
    # a rerun; on that rerun st.button("Build ZIP") is False, the body was
    # skipped, the download_button was never rendered, and the click resolved
    # against nothing. The bytes are held in session_state now and the button is
    # drawn unconditionally while they exist; block 012 drops them when any
    # input changes.
    if st.button("Build ZIP", type="primary"):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr(fname, text)
            z.writestr(fname.rsplit(".", 1)[0] + ".csv", _csv_of(sel, ","))
            z.writestr(fname.rsplit(".", 1)[0] + ".json", _json_of(sel, lines=False))
            by = {}
            for r in sel:
                by.setdefault(r["status"], []).append(r)
            for tag, group in by.items():
                z.writestr(f"{tag}_{len(group)}.txt",
                           "\n".join(g["line"] for g in group))
        st.session_state["_ex_zip"] = (buf.getvalue(), fname.rsplit(".", 1)[0] + ".zip")
    _z = st.session_state.get("_ex_zip")
    if _z:
        st.download_button("⬇️ Download ZIP", data=_z[0], file_name=_z[1],
                           mime="application/zip", width="stretch")
        st.caption(f"{len(_z[0]):,} bytes ready - built from the rows currently on screen.")
    else:
        st.caption("Press Build ZIP. It stays built until you change a setting.")

with tab_break:
    by = {}
    for r in sel:
        by.setdefault(r["status"], []).append(r)
    # v13.55: strongest bucket first, so VALID is at the top instead of sorting
    # alphabetically under CONNECTION_FAILED.
    for tag in sorted(by, key=lambda t: -_STATUS_RANK.get(t, 0)):
        with st.expander(f"{tag} — {len(by[tag])} row(s)"):
            body = "\n".join(r["line"] for r in by[tag])
            st.download_button(f"⬇️ {tag}.txt", data=body.encode("utf-8"),
                               file_name=f"{tag}_{len(by[tag])}.txt",
                               mime="text/plain", key=f"dl_{tag}")
            with st.container(height=320):
                st.code(body, language="text")
# @@END 013 TABS


# @@BLOCK 014 FOOTER deps=013
st.markdown("---")
try:
    st.page_link("app.py", label="← Back to the Mail Checker")
except Exception:
    st.caption("The main checker lives at app.py")
# @@END 014 FOOTER


# @@BLOCK 015 TRAILING deps=014
# (reserved tail - keeps the file closed after the last block)
# @@END 015 TRAILING
# @@EOF
