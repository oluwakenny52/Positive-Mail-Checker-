# @@FILE pages/8_Breach.py blocks=12 version=v13.86
# @@BLOCK 000 FILE_HEADER deps=-
"""
pages/8_Breach.py - breach exposure and combo freshness  (v13.86)
=================================================================
What a list of combos has actually been in, from keyless sources, with the
verdict about FRESHNESS rather than count.

WHY A PAGE AND NOT A RUN STEP
-----------------------------
A breach lookup is slow and rate-limited, and its answer never changes a mail
verdict. Putting it in the checker would spend ladder time on it. Here it is a
separate queue you point at a list when you want it.

WHAT EACH SOURCE IS
-------------------
  passwords  Pwned Passwords k-anonymity. Keyless, un-challenged, and the real
             signal - it says how public this exact password already is.
  address    the HIBP site's own search endpoint. Plain HTTP first, a browser
             only when Cloudflare challenges it.
  catalogue  the free breach list, matched locally by domain, as a fallback.

WHAT LEAVES THE BOX  (v13.85)
-----------------------------
Only the ADDRESS. A pasted `email:password` is cut at the colon before the URL
is built, so the password never reaches haveibeenpwned.com - which would not use
it anyway. The password goes to exactly one place: the SHA-1 hash for Pwned
Passwords, where 5 of the 40 characters leave and 35 are matched locally.

THE BANDS
---------
  NEW       password unseen, or exposure inside 365 days
  PARTIAL   password already circulating, or exposure inside 730 days
  OLD       password public for years, or only old breaches
  CLEAN     password unseen and address in no readable source
  UNKNOWN   nothing readable - the only honest answer when every tier failed

THE RUN DOES NOT RUN IN THE SCRIPT  (v13.86, this pass)
-------------------------------------------------------
It used to. Streamlit holds the whole delta stream while a script run blocks, so
a three-minute run greyed the page out and left the bar on 0 / 4 until the first
address happened to finish, and the widget states were dead for the duration.
The run is a THREAD now, its counters live in a session job dict, and this page
polls them with st.rerun(). The bar and the live trace move per address, Stop
works, and a refresh or a tab switch does not lose the run.

READ, VERSUS ZERO  (v13.86, this pass)
--------------------------------------
A card that said "0 breaches" could mean the page was read and lists none, or
that every tier failed and nothing was read. Those are opposite facts. Every
record carries `read`; an unread address half is flagged on the card, marked "-"
in History, marked `no` in the CSV, and counted in the run summary.

TRACING AND PACING  (v13.85)
----------------------------
Section 4 is a trace of everything: each control you moved, each address started,
the literal URL sent, the status, whether a challenge appeared, which tier
took over, the band, and every error verbatim. It is shown live during a run,
kept in a per-user file, and downloadable - so a run that goes wrong can be read
afterwards instead of guessed at. The Delay control paces address starts; workers
only bound concurrency. Both exist because HIBP's failures are quiet ones.

THE BROWSER
-----------
The package comes from requirements.txt; the ~150 MB Chromium binary does not.
The browser row in section 1 installs it once, on a background thread, and shows
the state. A failed install prints its own error rather than pretending the site
was blocked. Passwords work with no browser at all - the browser only rescues an
address the site challenges.

ISOLATION
---------
The cache, the history and the trace resolve through auth.user_file(), so each is
one file per user. Nothing on this page reads another user's data.

Read-only except Run / Stop / Prepare browser / Clear history / Clear trace /
downloads.
"""

import importlib
import json
import os
import re
import sys
import threading
import time
from datetime import datetime

import streamlit as st
# @@END 000 FILE_HEADER

# @@BLOCK 001 PAGE_CONFIG deps=000
st.set_page_config(page_title="Breach Exposure - Mail Checker",
                   page_icon="\U0001f6e1", layout="wide",
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
    .br-hero {
        background: linear-gradient(135deg, __G1__ 0%, __G2__ 100%);
        padding: 18px 24px; border-radius: 14px; margin-bottom: 14px;
        border: 1px solid rgba(255,255,255,.12);
    }
    .br-hero h1 { color: #fff !important; margin: 0; font-size: 1.45rem; font-weight: 800; }
    .br-hero p { color: rgba(255,255,255,.93) !important; margin: 6px 0 0 0; font-size: .84rem; }
    .br-band { display:inline-block; padding:2px 9px; border-radius:999px;
               font-size:.7rem; font-weight:800; letter-spacing:.03em; }
    .br-new      { background:#22c55e33; color:#86efac; border:1px solid #22c55e66; }
    .br-partial  { background:#f59e0b33; color:#fcd34d; border:1px solid #f59e0b66; }
    .br-old      { background:#ef444433; color:#fca5a5; border:1px solid #ef444466; }
    .br-clean    { background:#64748b33; color:#cbd5e1; border:1px solid #64748b66; }
    .br-unknown  { background:#a78bfa33; color:#ddd6fe; border:1px solid #a78bfa66; }
    .block-container, [data-testid="stMainBlockContainer"] {
        padding-top: 1.2rem !important; padding-bottom: 2rem !important;
        max-width: 1100px !important;
    }
    @media (max-width: 820px) {
        .block-container, [data-testid="stMainBlockContainer"] {
            padding-top: .55rem !important; padding-left: .7rem !important;
            padding-right: .7rem !important;
        }
        .br-hero h1 { font-size: 1.15rem !important; }
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
    '<div class="br-hero"><h1>\U0001f6e1 Breach Exposure</h1>'
    '<p>Point this at a list of combos. Keyless sources only - no API key, no '
    'per-address charge. The verdict is about how RECENT the exposure is.</p></div>',
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
    audit_log.page("pages/8_Breach.py")

# INSTALL BEFORE require(), exactly as app.py block 007 and every other page do.
# require() calls st.stop() while locked, so an install() after it never runs on
# a locked page and the Unlock box is never wrapped.
if hasattr(audit_log, "install"):
    audit_log.install(st, "pages/8_Breach.py")

auth.require(st, "Unlock Breach Exposure")
auth.fit(st)                        # CSS only, before the first widget

# The first theme read ran before the gate, on the anonymous prefix. Now that
# the passphrase is unlocked the owner's real file exists - re-read and repaint.
_TH = _theme()
st.markdown(_css(), unsafe_allow_html=True)
# @@END 005 HERO_GATE

# @@BLOCK 006 SOURCES deps=005
import breach
import streamlit.components.v1 as components

# ---- stale-module guard -------------------------------------------------------
# Streamlit Cloud keeps this process alive across 'Updated app!', so sys.modules
# keeps serving whichever copy was imported first. The old guard tested
# ensure_browser/check_many, which the OLD module already had, so it never fired
# and the page ran old code with no page_mode, no trace_read and no 401 handling.
# page_wanted, trace_read and trace_clear exist only in the current module, so
# testing those is a real version test and the reload actually happens.
# record_view is the newest marker: a module without it builds no page at all
# when the address tier fails, so it belongs in the same test.
if not (hasattr(breach, "page_wanted") and hasattr(breach, "trace_read")
        and hasattr(breach, "trace_clear") and hasattr(breach, "record_view")):
    breach = importlib.reload(breach)
    try:
        breach.trace("INFO", "page", "stale breach module replaced by reload")
    except Exception:
        pass

from auth import user_file

_HIST_NAME = "breach_history.jsonl"
_HIST_MAX = 2000
_OWNER_KEY = "_breach_owner"
_RUN_KEY = "_breach_run"
_JOB_KEY = "_breach_job"
_RES_KEY = "_breach_results"
_QUAL_KEY = "_breach_quality"
_MSG_KEY = "_breach_msg"
_TRACE_SHOWN = "_breach_trace_shown"
_CAP_VIEW_KEY = "_breach_cap_view"
_CAP_MODE_KEY = "_breach_page_mode"
_CAP_ON_KEY = "_breach_page_on"
_MODE_LABELS = {
    "Fast - only what I filter for": "fast",
    "Full - every address checked": "full",
    "Off - capture no pages": "off",
}

_BAND_CSS = {"NEW": "br-new", "PARTIAL": "br-partial", "OLD": "br-old",
             "CLEAN": "br-clean", "UNKNOWN": "br-unknown"}


def _hist_path():
    try:
        return user_file(_HIST_NAME)
    except Exception:
        return _HIST_NAME


def _hist_add(rows):
    """Append reports, then trim the file to _HIST_MAX. Never raises."""
    p = _hist_path()
    if not p:
        return
    try:
        with open(p, "a", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        with open(p, encoding="utf-8", errors="ignore") as fh:
            lines = fh.readlines()
        if len(lines) > _HIST_MAX:
            with open(p, "w", encoding="utf-8") as fh:
                fh.writelines(lines[-_HIST_MAX:])
    except Exception:
        pass


def _hist_read(limit=300):
    p = _hist_path()
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
                if isinstance(r, dict):
                    out.append(r)
    except Exception:
        return out
    return out[-limit:]


def _hist_clear():
    p = _hist_path()
    try:
        if p and os.path.exists(p):
            os.remove(p)
    except Exception:
        pass


def _band_counts(rows):
    c = {"NEW": 0, "PARTIAL": 0, "OLD": 0, "CLEAN": 0, "UNKNOWN": 0}
    for r in rows:
        v = str(r.get("verdict") or "UNKNOWN")
        c[v] = c.get(v, 0) + 1
    return c


def _row_key(r):
    """A stable widget-key stem from the address, not from hash().

    hash() is salted per process, so the same address got different keys on every
    run and the view choice never stuck. The address is unique in a run and
    survives a re-render, which is what a widget key needs.
    """
    return (re.sub(r"[^a-z0-9]+", "_", str(r.get("email") or "").lower()).strip("_")
            [:48] or "row")


def _h_esc(v):
    """Escape for the record view's HTML. Never raises on None."""
    return (str(v if v is not None else "").replace("&", "&amp;")
            .replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;"))


def _record_page(r):
    """(text, html) of a record, built here when no page was captured.

    The card must ALWAYS be able to offer a Text and an HTML view. When the
    address tier failed there is no captured page, and printing "no page
    captured" with no toggle hides the only artefact left to inspect. This is a
    view of the RECORD and says so in its own footer.
    """
    _read = bool(r.get("read"))
    _e = str(r.get("email") or "")
    _pw = r.get("pw_count")
    _lines = ["address: " + _e,
              "checked: " + str(r.get("checked_at") or ""),
              "verdict: %s - %s" % (r.get("verdict") or "?", r.get("reason") or ""),
              "address half: " + ("READ" if _read else "NOT READ"),
              "password appearances: " + ("no password supplied" if _pw is None
                                          else str(_pw)),
              "source: " + str(r.get("via") or "-"),
              "breaches: %d, pastes: %d" % (len(r.get("breaches") or []),
                                           len(r.get("pastes") or []))]
    if r.get("error"):
        _lines.append("error: " + str(r["error"]))
    _rows = []
    for b in (r.get("breaches") or [])[:60]:
        _rows.append(b)
        _lines.append("")
        _lines.append("- " + str(b.get("title") or "?"))
        if b.get("date"):
            _lines.append("  breach date: " + str(b["date"]))
        if b.get("days") is not None:
            _lines.append("  age: %d day(s)" % int(b["days"]))
        _lines.append("  accounts: " + "{:,}".format(int(b.get("pwn_count") or 0)))
        if b.get("classes"):
            _lines.append("  data: " + ", ".join(b["classes"]))
    for p in (r.get("pastes") or [])[:30]:
        _lines.append("")
        _lines.append("- paste: %s (%s) %s" % (p.get("title") or "?",
                                               p.get("source") or "-",
                                               p.get("date") or ""))
    _text = "\n".join(_lines)[:30000]

    _h = ["<!doctype html><html><head><meta charset='utf-8'><title>", _h_esc(_e),
          "</title><style>body{font-family:system-ui,sans-serif;background:#0b1020;"
          "color:#e6ebff;padding:16px}h1{font-size:1.05rem}"
          "table{border-collapse:collapse;width:100%;font-size:.8rem}"
          "td,th{border:1px solid #2a3350;padding:5px;text-align:left;"
          "vertical-align:top}th{background:#141b30}.c{color:#fcd34d}"
          "</style></head><body><h1>", _h_esc(_e), "</h1><p class='c'>",
          _h_esc(r.get("verdict") or "?"), " - ", _h_esc(r.get("reason") or ""),
          "</p><p>address half: " + ("READ" if _read else "NOT READ")
          + "<br>password appearances: " + ("-" if _pw is None else _h_esc(_pw))
          + "<br>source: " + _h_esc(r.get("via") or "-")
          + "<br>checked: " + _h_esc(r.get("checked_at") or "") + "</p>"]
    if r.get("error"):
        _h.append("<p class='c'>error: " + _h_esc(r["error"]) + "</p>")
    if _rows:
        _h.append("<table><tr><th>Breach</th><th>Date</th><th>Age</th><th>Accounts</th>"
                  "<th>Data classes</th></tr>")
        for b in _rows:
            _h.append("<tr><td>" + _h_esc(b.get("title") or "?") + "</td><td>"
                      + _h_esc(b.get("date") or "-") + "</td><td>"
                      + ("%d d" % int(b["days"]) if b.get("days") is not None else "-")
                      + "</td><td>" + "{:,}".format(int(b.get("pwn_count") or 0))
                      + "</td><td>" + _h_esc(", ".join(b.get("classes") or []) or "-")
                      + "</td></tr>")
        _h.append("</table>")
    else:
        _h.append("<p>" + ("No breach record could be read - see the error above."
                           if r.get("error") else "No breach record for this address.")
                  + "</p>")
    if r.get("pastes"):
        _h.append("<h2>Pastes</h2><ul>")
        for p in (r.get("pastes") or [])[:30]:
            _h.append("<li>" + _h_esc(p.get("title") or "?") + " ("
                      + _h_esc(p.get("source") or "-") + ") "
                      + _h_esc(p.get("date") or "") + "</li>")
        _h.append("</ul>")
    _h.append("<p><small>View built from the record, not a captured page.</small></p>"
              "</body></html>")
    return _text, "".join(_h)[:90000]


def _csv(rows):
    """CSV, first five columns unchanged so anything downstream still reads.

    `read` is appended LAST: yes means the address half answered (so the counts
    are real, including a real zero), no means nothing was read and the counts
    must not be taken as zero.
    """
    head = ("verdict,email,breaches,pastes,pw_count,bucket,pw_hits,corpora,"
            "sites,sensitive,newest_breach_days,breach_names,data_classes,"
            "paste_titles,via,reason,error,checked_at,read")
    out = [head]
    for r in rows:
        bs = r.get("breaches") or []
        ps = r.get("pastes") or []
        # The record key is newest_days - reading newest_breach_days left this
        # column blank on every row, whatever the run had actually found.
        _newest = r.get("newest_days")
        if _newest is None:
            _newest = r.get("newest_breach_days")
        out.append(",".join([
            str(r.get("verdict") or ""),
            str(r.get("email") or ""),
            str(len(bs)),
            str(len(ps)),
            str(r.get("pw_count") if r.get("pw_count") is not None else ""),
            str(r.get("bucket") or ""),
            str(r.get("pw_count") if r.get("pw_count") is not None else ""),
            str(r.get("corpora", 0)),
            str(r.get("sites", 0)),
            str(r.get("sensitive", 0)),
            str(_newest) if _newest is not None else "",
            '"%s"' % "; ".join(b.get("title") or "" for b in bs[:12]).replace('"', "'"),
            '"%s"' % "; ".join(sorted({c for b in bs
                                       for c in (b.get("classes") or [])})).replace('"', "'"),
            '"%s"' % "; ".join(p.get("title") or "" for p in ps[:12]).replace('"', "'"),
            str(r.get("via") or ""),
            '"%s"' % str(r.get("reason") or "").replace('"', "'"),
            '"%s"' % str(r.get("error") or "").replace('"', "'"),
            str(r.get("checked_at") or ""),
            "yes" if r.get("read") else "no",
        ]))
    return "\n".join(out) + "\n"


def _watch(key, label):
    """An on_change callback that traces the control. Never raises."""
    def cb():
        try:
            breach.trace("CLICK", "control", "%s -> %r"
                         % (label, st.session_state.get(key)))
        except Exception:
            pass
    return cb


def _trace_code(limit=200, since=0):
    return breach.trace_text(limit=limit, since=since)


def _trace_read(limit=250):
    """Structured events where the module has them, else a stand-in from text.

    Keeps section 4 working against a module that predates trace_read instead of
    dying on an AttributeError after a run has already been paid for.
    """
    fn = getattr(breach, "trace_read", None)
    if callable(fn):
        try:
            return list(fn(limit=limit))
        except Exception:
            return []
    try:
        return [1] if breach.trace_text(limit=limit) else []
    except Exception:
        return []


def _hibp_key():
    """True when HIBP_API_KEY is set. Read here only to say whether it is on."""
    k = os.environ.get("HIBP_API_KEY") or ""
    if not k:
        try:
            k = str(st.secrets.get("HIBP_API_KEY") or "")
        except Exception:
            k = ""
    return bool(k.strip())


# ---- owner gate: a second unlock in this tab must not inherit the last run ----
_owner = os.path.basename(user_file("")) or ""
if st.session_state.get(_OWNER_KEY) != _owner:
    for k in (_RES_KEY, _RUN_KEY, _JOB_KEY, _QUAL_KEY, _MSG_KEY, "_breach_text",
              _TRACE_SHOWN):
        st.session_state.pop(k, None)
    st.session_state[_OWNER_KEY] = _owner
    breach.trace("INFO", "page", "new owner in this tab, state cleared")

breach.trace("INFO", "page", "loaded")
# @@END 006 SOURCES

# @@BLOCK 007 INPUT deps=006
st.markdown("### 1. Addresses")

_t1, _t2 = st.tabs(["\U0001f4dd Paste", "\U0001f4c1 Upload"])

_text = ""
with _t1:
    _text = st.text_area(
        "One address per line. A pasted `email:pass` or `email | VERDICT` line is "
        "cut down to the address; the password is kept for the Pwned Passwords "
        "check, because how public the PASSWORD already is, is the real signal.",
        height=200, key="_breach_text", on_change=_watch("_breach_text", "text"),
        placeholder="someone@example.com:hunter2")
with _t2:
    up = st.file_uploader("Upload a .txt list", type=["txt"], key="_breach_up")
    if up is not None:
        try:
            _text = up.getvalue().decode("utf-8", errors="ignore")
            breach.trace("CLICK", "upload", "%s, %d byte(s)"
                         % (getattr(up, "name", "?"), len(_text)))
        except Exception as e:
            st.error("Could not read that file: %s" % e)
            breach.trace("ERR", "upload", str(e))

_pairs = breach.parse_addresses(_text)
_with_pw = sum(1 for _e, _p in _pairs if _p)
if _pairs:
    st.caption("**%d** address(es) ready, **%d** of them with a password."
               % (len(_pairs), _with_pw))
    if not _with_pw:
        st.caption("No passwords in the list - the verdict then rests on the address "
                   "alone, which is the weaker half.")
else:
    st.caption("Nothing queued.")

st.caption("Only the address is sent to haveibeenpwned.com. A pasted "
           "`email:password` is cut at the colon before the request is built - HIBP "
           "does not use the password. The password only ever goes to the Pwned "
           "Passwords hash check, and 5 of its 40 hash characters leave the box.")

# ---- the browser, and its state ------------------------------------------------
# This is not a rescue any more, it is the address tier: a real Chromium types the
# address into the site's own search box and reads the rendered page. No key, no
# quota, no bill. Without the binary there is no address half at all, which is why
# the install is kicked here and its state is a value on the page.
_bst = breach.browser_state()
if _bst.get("state") == "unknown":
    breach.ensure_browser()
    _bst = breach.browser_state()

_bst1, _bst2 = st.columns([0.72, 0.28])
with _bst1:
    if _bst.get("state") == "ready":
        st.caption("\u2705 Browser ready - addresses are typed into the site's search "
                   "box and the rendered page is read.")
    elif _bst.get("state") == "installing":
        st.caption("\u23f3 Browser installing (%ss). Passwords are checked either way; "
                   "addresses come back UNKNOWN until it finishes."
                   % _bst.get("seconds", 0))
    elif _bst.get("state") == "failed":
        st.caption("\u26a0 Browser install FAILED. Passwords still work; addresses "
                   "come back UNKNOWN. Error: `%s`"
                   % (_bst.get("error") or "unknown")[:300])
    else:
        st.caption("Browser not installed. Passwords are checked either way; "
                   "addresses come back UNKNOWN without one.")
with _bst2:
    if _bst.get("state") != "ready" and _bst.get("state") != "installing":
        if st.button("\u2b07 Prepare browser", width="stretch",
                     help="Downloads Chromium once, into this repo, and keeps it. "
                          "About 150 MB - do it on wifi. This is what reads the "
                          "address pages."):
            breach.trace("CLICK", "browser", "Prepare browser pressed")
            breach.ensure_browser(force=True)
            st.rerun()

# ---- the address tier: the UI, keyless ----------------------------------------
# No key is needed and none is faked. The page is the API: the address goes into
# the site's own search box, the result is scraped from what renders, and the page
# text and HTML are kept from that same read. A key only makes it faster.
if breach.key_present():
    st.caption("\U0001f511 HIBP_API_KEY is set - the keyed API is tried first because "
               "it is faster and exact. The browser is still the fallback.")
else:
    st.caption("\U0001f5b1 No API key, and none needed. The address is typed into the "
               "site's own search box and the rendered page is scraped for the breach "
               "names, dates and classes. Slower than an API call, and free.")

_c1, _c2, _c3, _c4, _c5 = st.columns(5)
with _c1:
    _workers = st.slider("Workers", 1, 8, 2, key="_breach_workers",
                         on_change=_watch("_breach_workers", "workers"),
                         help="How many addresses may be in flight at once. Each one "
                              "is a whole page load, so 2 is the honest default on a "
                              "small container - raise it only if runs feel slow.")
with _c2:
    _delay = st.slider("Delay (s)", 0.0, 10.0, 3.0, 0.5, key="_breach_delay",
                       on_change=_watch("_breach_delay", "delay"),
                       help="Seconds between STARTING addresses, regardless of "
                            "worker count. This is the knob for being gentle - 3s "
                            "trickles, 0 floods.")
with _c3:
    _pages = st.number_input("Browser pages", 1, 8, 2, 1, key="_breach_pages",
                             on_change=_watch("_breach_pages", "pages"),
                             help="Chromium tabs for addresses. Each is reused, and "
                                  "recreated if it dies.")
with _c4:
    _force = st.checkbox("Ignore cache", value=False, key="_breach_force",
                         on_change=_watch("_breach_force", "ignore cache"),
                         help="A cached answer is served for 6 hours. Tick this to "
                              "re-check from the sources, which is what you want "
                              "straight after changing anything.")
with _c5:
    _http_only = st.checkbox("HTTP only", value=False, key="_breach_http_only",
                             on_change=_watch("_breach_http_only", "http only"),
                             help="No browser. Faster, but a walled address comes "
                                  "back UNKNOWN instead of resolved.")

# ---- page capture, and how much of it ------------------------------------
# The page read and the search are the SAME visit now, so capture costs almost
# nothing - the text and HTML are already in hand. The mode decides which
# outcomes keep them.
st.markdown("##### Captured pages")
_cm1, _cm2 = st.columns([0.58, 0.42])
with _cm1:
    _mode_label = st.radio(
        "Capture", list(_MODE_LABELS.keys()), horizontal=False, key=_CAP_MODE_KEY,
        on_change=_watch(_CAP_MODE_KEY, "capture mode"),
        help="The page is what the site actually rendered for an address - titles, "
             "dates, data classes, or the 'no pwnage' copy. It is kept per address "
             "under your own prefix and can be wiped at the bottom of the page.")
_page_mode = _MODE_LABELS.get(_mode_label, "fast")
with _cm2:
    if _page_mode == "fast":
        _on_labels = st.multiselect(
            "Capture which outcomes", ["CLEAN", "Errored"],
            default=["CLEAN", "Errored"], key=_CAP_ON_KEY,
            on_change=_watch(_CAP_ON_KEY, "capture outcomes"),
            help="Only these are fetched. A breached address keeps its records and "
                 "gets no page - the scrape already has the titles and dates.")
        _page_on = [x.lower() for x in _on_labels]
    elif _page_mode == "full":
        st.caption("Every checked address keeps its page, records or not.")
        _page_on = ["clean", "error"]
    else:
        st.caption("No pages are kept. Records, verdicts and exports are "
                   "unaffected.")
        _page_on = []

if _page_mode == "fast" and not _page_on:
    st.caption("Fast mode with nothing ticked keeps nothing - the same as Off.")
# @@END 007 INPUT

# @@BLOCK 008 RUN deps=007
_job = st.session_state.get(_JOB_KEY)
if isinstance(_job, dict) and not _job.get("done"):
    try:
        # Watchdog: a thread that dies without its finally would otherwise leave
        # the page polling for ever.
        if time.time() - float(_job.get("started") or 0) > 1800.0:
            _job["error"] = _job.get("error") or "watchdog: the run stopped reporting"
            _job["done"] = True
    except Exception:
        pass
_running = bool(isinstance(_job, dict) and not _job.get("done"))

_bc1, _bc2 = st.columns([0.72, 0.28])
with _bc1:
    _run = st.button("\U0001f6e1 Check exposure", type="primary",
                     disabled=(not _pairs or _running), width="stretch")
with _bc2:
    _stop = st.button("\u23f9 Stop", width="stretch", disabled=not _running,
                      help="Asks the workers to stop at the next address. Records "
                           "already finished are kept.")


def _job_start(tier):
    """Start the run on a THREAD and hand back its job dict.

    The run used to execute inside the script run itself, and Streamlit holds the
    whole delta stream while a script run blocks: the page greyed out, the bar sat
    on 0 / 4 until the first address happened to finish, and the widget states
    were dead for the whole three minutes. The thread owns the work now, the job
    dict owns the counters, and the script polls it with st.rerun(). Stop works, a
    refresh or a tab switch does not lose the run, and the bar and the live trace
    move per address instead of per run.
    """
    job = {"rows": {}, "done": False, "n": 0, "total": len(_pairs), "last": "",
           "error": "", "cancel": threading.Event(), "started": time.time(),
           "since0": breach.trace_seq(), "tier": tier, "mode": _page_mode,
           "page_on": list(_page_on)}
    st.session_state[_JOB_KEY] = job

    def _tick(n, total, email, verdict):
        try:
            job["n"] = int(n or 0)
            job["last"] = ("%s %s" % (email or "", (verdict or "").lower())).strip()
        except Exception:
            pass

    def _body():
        try:
            try:
                job["rows"] = breach.check_many(
                    _pairs, workers=int(_workers), progress=_tick,
                    cancel=job["cancel"], force=bool(_force), delay=float(_delay),
                    http_only=bool(_http_only))
            except TypeError:
                breach.trace("WARN", "run", "check_many has no http_only argument - "
                                            "re-running without it")
                job["rows"] = breach.check_many(
                    _pairs, workers=int(_workers), progress=_tick,
                    cancel=job["cancel"], force=bool(_force), delay=float(_delay))
        except Exception as e:
            job["error"] = "%s: %s" % (type(e).__name__, e)
            breach.trace("ERR", "run", "raised %s: %s" % (type(e).__name__, e))
        finally:
            job["done"] = True

    threading.Thread(target=_body, name="breach-run", daemon=True).start()
    return job


if _run and _pairs and not _running:
    _tier = "http-only" if _http_only else "http+browser"
    breach.trace("CLICK", "run", "pressed: %d address(es), workers=%d, delay=%s, "
                 "tier=%s" % (len(_pairs), int(_workers), _delay, _tier))
    # THE TIER AND THE CAPTURE SWITCH ARE PASSED. Both calls take them; the
    # fallbacks are only for a breach.py that has not caught up, and they say so
    # in the trace rather than silently running the old way.
    try:
        breach.configure(pages=int(_pages), delay=float(_delay),
                         http_only=bool(_http_only),
                         page_mode=_page_mode, page_on=_page_on)
        breach.trace("INFO", "run", "configure: tier + capture switch accepted")
    except TypeError:
        try:
            breach.configure(pages=int(_pages), delay=float(_delay),
                             http_only=bool(_http_only))
        except TypeError:
            breach.configure(pages=int(_pages), delay=float(_delay))
            breach.trace("WARN", "run", "breach.configure has no http_only argument "
                                        "- the tier switch is NOT applied")
        breach.trace("WARN", "run", "breach.configure has no page_mode argument "
                                    "- the capture switch is NOT applied")
    breach.trace("INFO", "run", "pages: %s%s" % (
        _page_mode, (" (%s)" % ",".join(_page_on)) if _page_on else ""))
    _job = _job_start(_tier)
    _running = True

if isinstance(_job, dict):
    _total = max(1, int(_job.get("total") or 0))
    _n = int(_job.get("n") or 0)
    st.progress(min(1.0, _n / _total),
                text="%d / %d%s" % (_n, _total,
                                    (" - " + _job["last"]) if _job.get("last") else ""))
    _live = st.empty()
    try:
        _live.code(_trace_code(limit=14, since=int(_job.get("since0") or 0)),
                   language="text")
    except Exception:
        pass

    if _running:
        if _stop:
            try:
                _job["cancel"].set()
            except Exception:
                pass
            breach.trace("CLICK", "run", "stop requested - workers stop at the "
                                        "next address")
        time.sleep(0.6)
        st.rerun()
    else:
        st.session_state.pop(_JOB_KEY, None)
        _rows = list((_job.get("rows") or {}).values())
        _mode_used = str(_job.get("mode") or _page_mode)
        _on_used = list(_job.get("page_on") or [])
        _tier_used = str(_job.get("tier") or "-")
        if _job.get("error"):
            st.session_state[_MSG_KEY] = ("error", "Run failed: %s" % _job["error"])
        elif not _rows:
            st.session_state[_MSG_KEY] = ("warning", "Nothing was checked.")
        else:
            _rows.sort(key=lambda r: ({"OLD": 0, "PARTIAL": 1, "NEW": 2,
                                       "UNKNOWN": 3, "CLEAN": 4}.get(
                                           r.get("verdict") or "UNKNOWN", 5),
                                      r.get("email") or ""))
            _hist_add(_rows)
            st.session_state[_RES_KEY] = _rows
            st.session_state[_QUAL_KEY] = breach.score(_rows)
            st.session_state[_RUN_KEY] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            _b = _band_counts(_rows)
            _unread = sum(1 for r in _rows if not r.get("read"))
            # The tier is part of the summary, not a detail: UNKNOWN under HTTP
            # only means "walled, not tried", and under http+browser it means the
            # browser could not render it either. Those are different problems.
            # The unread count is separate again: it is the addresses whose page
            # nobody read, and their zeros are not zeros.
            _msg = ("Checked %d via %s. %d old, %d partially new, %d new, %d clean, "
                    "%d unresolved. %d address half(s) unread. Pages kept: %s."
                    % (len(_rows), _tier_used, _b["OLD"], _b["PARTIAL"], _b["NEW"],
                       _b["CLEAN"], _b["UNKNOWN"], _unread,
                       ("off" if _mode_used == "off" else
                        ("all" if _mode_used == "full"
                         else (",".join(_on_used) or "none")))))
            breach.trace("INFO", "run", "summary: " + _msg)
            _tips = []
            if _unread:
                _tips.append("%d address half(s) could not be read - those verdicts "
                             "rest on the password half alone and their breach and "
                             "paste counts are UNREAD, not zero. The trace names the "
                             "step that failed." % _unread)
            _bst_now = breach.browser_state().get("state")
            if _b["UNKNOWN"] and _http_only:
                _tips.append("Unresolved ones were walled and HTTP only was selected - "
                             "untick HTTP only so the browser can read them.")
            elif _b["UNKNOWN"] and _bst_now != "ready":
                _tips.append("The browser is %s, and the browser IS the address tier - "
                             "press Prepare browser, then re-run." % _bst_now)
            elif _b["UNKNOWN"]:
                _tips.append("The browser reached the page but nothing readable came "
                             "back - open the trace, it names the step that failed.")
            # A message widget is REQUIRED here. Without one the ledger closes the
            # press as "NO RESULT | finished without reporting", which is exactly
            # what the 00:36:57 entry recorded.
            _lvl = "warning" if (_unread or _b["UNKNOWN"]) else "success"
            st.session_state[_MSG_KEY] = (
                _lvl, _msg + ((" " + " ".join(_tips)) if _tips else ""))

if st.session_state.get(_MSG_KEY):
    _lvl, _msg = st.session_state.pop(_MSG_KEY)
    getattr(st, _lvl, st.info)(_msg)
# @@END 008 RUN

# @@BLOCK 009 DASHBOARD deps=008
_rows = st.session_state.get(_RES_KEY) or []

if _rows:
    _b = _band_counts(_rows)
    _q = st.session_state.get(_QUAL_KEY) or {}
    _stamp = st.session_state.get(_RUN_KEY) or ""

    st.markdown("### 2. Combo quality")
    st.caption("Checked %s. **%d** address(es)." % (_stamp, len(_rows)))

    _qc1, _qc2, _qc3, _qc4 = st.columns(4)
    _qc1.metric("Quality", "%s%%" % _q.get("quality", 0), _q.get("grade", "-"),
                delta_color="off",
                help="(NEW x1.0 + PARTIAL x0.5 + OLD x0.15) / scored. UNKNOWN and "
                     "CLEAN are outside the score.")
    _qc2.metric("Old", "%s%%" % _q.get("pct", {}).get("OLD", 0),
                help="The password has been public for years, or only old breaches.")
    _qc3.metric("Partially new", "%s%%" % _q.get("pct", {}).get("PARTIAL", 0),
                help="Already circulating, but nothing ancient.")
    _qc4.metric("New", "%s%%" % _q.get("pct", {}).get("NEW", 0),
                help="Password unseen in Pwned Passwords, or exposure inside a year.")

    st.caption(
        "%s%% of this set is OLD - that half of each combo is burned and the password "
        "should be rotated everywhere it was reused. %s%% is partially new. %s%% is new. "
        "%s%% unresolved and excluded from the score."
        % (_q.get("pct", {}).get("OLD", 0), _q.get("pct", {}).get("PARTIAL", 0),
           _q.get("pct", {}).get("NEW", 0), _q.get("pct", {}).get("UNKNOWN", 0)))

    _unread_rows = [r for r in _rows if not r.get("read")]
    if _unread_rows:
        st.caption("\u26a0 **%d of these %d address half(s) were never read.** Their "
                   "breach and paste counts are UNREAD, not zero, and their verdict "
                   "rests on the password half alone."
                   % (len(_unread_rows), len(_rows)))
    st.bar_chart({"Band": list(_q.get("buckets", {}).keys()),
                  "Count": list(_q.get("buckets", {}).values())},
                 x="Band", y="Count", height=180)

    _m = st.columns(5)
    _m[0].metric("\U0001f525 OLD", _b["OLD"])
    _m[1].metric("\u26a0 PARTIAL", _b["PARTIAL"])
    _m[2].metric("\u2705 NEW", _b["NEW"])
    _m[3].metric("\U0001f5c4 CLEAN", _b["CLEAN"])
    _m[4].metric("\u2753 UNKNOWN", _b["UNKNOWN"])

    if _b["OLD"]:
        st.error("**%d combo(s) are old bridges.** The password is in public corpora - "
                 "rotate it and everything it was reused on." % _b["OLD"])
    elif _b["PARTIAL"]:
        st.warning("**%d combo(s) are partially new.** Nothing ancient, but the "
                   "password already circulates." % _b["PARTIAL"])

    _view = st.radio("Show",
                     ["OLD", "PARTIAL", "NEW", "UNKNOWN", "CLEAN", "All"],
                     horizontal=True, key="_breach_view",
                     on_change=_watch("_breach_view", "band filter"))
    _show = _rows if _view == "All" else [r for r in _rows if r.get("verdict") == _view]

    if not _show:
        st.info("Nothing in that band.")
    else:
        for r in _show:
            _v = str(r.get("verdict") or "UNKNOWN")
            _bs = r.get("breaches") or []
            _ps = r.get("pastes") or []
            _read = bool(r.get("read"))
            _key = _row_key(r)
            with st.expander("%s %s%s" % ("\u26a0" if not _read else "\u2022",
                                          r.get("email") or "?", "  " + _v),
                             expanded=False):
                st.markdown('<span class="br-band %s">%s</span> &nbsp; %s'
                            % (_BAND_CSS.get(_v, "br-unknown"), _v,
                               r.get("reason") or ""), unsafe_allow_html=True)
                if r.get("pw_count") is not None:
                    st.caption("Password appears **%s** time(s) in Pwned Passwords."
                               % "{:,}".format(int(r["pw_count"])))
                else:
                    st.caption("Password not supplied - address evidence only.")
                if r.get("error"):
                    st.caption("error: %s" % r["error"])
                if not _read:
                    st.caption("\u26a0 **The address half was not read.** This verdict "
                               "rests on the password half alone, and the breach and "
                               "paste counts below are unread - they are not zeros.")
                if _bs:
                    st.markdown("**Breaches on this address** - %d" % len(_bs))
                    for b in _bs[:25]:
                        _d = b.get("days")
                        # Prefer the real date when the record carries one, and keep
                        # the age as the fallback for records that only have days.
                        _when = (b.get("date") or b.get("breach_date")
                                 or ("%d day(s) ago" % _d if _d is not None
                                     else "date unknown"))
                        st.markdown("- **%s**%s - %s, %s record(s), classes: %s"
                                    % (b.get("title") or "?",
                                       " _(stealer corpus)_" if b.get("corpus") else "",
                                       _when, "{:,}".format(int(b.get("pwn_count") or 0)),
                                       ", ".join(b.get("classes") or []) or "-"))
                        if b.get("description"):
                            st.caption(b["description"][:300])
                elif _read:
                    st.caption("No breach record - the page was read and lists none.")
                elif r.get("error"):
                    st.caption("No breach record could be read - see the error above.")
                else:
                    st.caption("No breach record for this address.")
                if _ps:
                    st.markdown("**Pastes quoting the address:** %d" % len(_ps))
                    for p in _ps[:10]:
                        st.caption("%s  %s" % (p.get("title") or "?", p.get("date") or ""))

                # ---- the page: text or HTML, and ALWAYS one of them ----
                # A missing captured page used to mean a missing toggle, so a
                # failed run left the one thing worth inspecting unavailable. The
                # view is built from the record when nothing was captured, and the
                # caption says which of the three it is.
                _pg_t = str(r.get("page_text") or "")
                _pg_h = str(r.get("page_html") or "")
                _pg_via = str(r.get("page_via") or "")
                if not (_pg_t or _pg_h):
                    _fn = getattr(breach, "record_view", None)
                    if callable(_fn):
                        try:
                            _pg_t, _pg_h = _fn(r)
                        except Exception:
                            _pg_t, _pg_h = "", ""
                    if not (_pg_t or _pg_h):
                        _pg_t, _pg_h = _record_page(r)
                    _src = "view built from the record - no page was captured"
                elif _pg_via == "browser":
                    _src = "page as the browser rendered it"
                elif _pg_via == "http":
                    _src = ("page as fetched over plain HTTP - not rendered, so it is "
                            "often the challenge body itself")
                else:
                    _src = "view built from the record"

                if _pg_t or _pg_h:
                    st.caption(_src)
                    _opts = (["Text", "HTML"] if (_pg_t and _pg_h)
                             else (["Text"] if _pg_t else ["HTML"]))
                    _pv = st.radio("Page view", _opts, horizontal=True, index=0,
                                   key="_pv_%s" % _key,
                                   help="What the source actually returned for this "
                                        "address, kept under your own prefix.")
                    if _pv == "Text":
                        st.code(_pg_t[:40000] or "(empty page)", language="text")
                        st.download_button(
                            "\u2b07 Download this page as text",
                            data=_pg_t.encode("utf-8"),
                            file_name="page_%s.txt" % _key,
                            mime="text/plain", width="stretch",
                            key="_pvt_%s" % _key)
                    else:
                        components.html(_pg_h, height=560, scrolling=True)
                        st.download_button(
                            "\u2b07 Download this page as HTML",
                            data=_pg_h.encode("utf-8"),
                            file_name="page_%s.html" % _key,
                            mime="text/html", width="stretch",
                            key="_pvh_%s" % _key)

                st.caption("via %s \u00b7 checked %s"
                           % (r.get("via") or "-", r.get("checked_at") or ""))

    st.markdown("### 3. Export")
    _d1, _d2 = st.columns(2)
    with _d1:
        st.download_button("\u2b07 Download CSV (all bands)",
                           data=_csv(_rows).encode("utf-8"),
                           file_name="breach_%s.csv"
                                     % datetime.now().strftime("%Y%m%d_%H%M%S"),
                           mime="text/csv", width="stretch")
    with _d2:
        _bad = [r for r in _rows if r.get("verdict") in ("OLD", "PARTIAL")]
        st.download_button("\u2b07 Download OLD + PARTIAL addresses",
                           data="\n".join(r.get("email") or "" for r in _bad).encode(),
                           file_name="breach_rotate_%d.txt" % len(_bad),
                           mime="text/plain", width="stretch", disabled=not _bad)
# @@END 009 DASHBOARD

# @@BLOCK 010 HISTORY deps=009
st.markdown("---")
st.markdown("### 4. Trace")
st.caption("Everything that happened, newest last: each control moved, each address "
           "started, the exact URL sent, the status, whether a challenge appeared, "
           "which tier took over, the band and every error. `%s` carries only the "
           "address - the password is never in it."
           % (breach.last_url() or "https://haveibeenpwned.com/unifiedsearch/<address>"))

_tevents = _trace_read(limit=250)
if not _tevents:
    st.caption("Nothing traced yet.")
else:
    st.code(breach.trace_text(limit=250), language="text")

_td1, _td2, _td3 = st.columns(3)
with _td1:
    st.download_button("\u2b07 Download trace log",
                       data=breach.trace_dump().encode("utf-8"),
                       file_name="breach_trace_%s.log"
                                 % datetime.now().strftime("%Y%m%d_%H%M%S"),
                       mime="text/plain", width="stretch")
with _td2:
    if st.button("Clear trace", width="stretch"):
        breach.trace_clear()
        breach.trace("CLICK", "trace", "cleared")
        st.rerun()
with _td3:
    st.caption("Last URL: `%s`" % (breach.last_url() or "-"))

st.markdown("---")
st.markdown("### History (yours, capped at %d)" % _HIST_MAX)

_hist = _hist_read()
if not _hist:
    st.caption("Nothing stored yet. Every run appends here.")
else:
    st.caption("%d stored report(s), newest last." % len(_hist))
    _hc = _band_counts(_hist)
    st.caption("OLD %d \u00b7 PARTIAL %d \u00b7 NEW %d \u00b7 CLEAN %d \u00b7 UNKNOWN %d"
               % (_hc["OLD"], _hc["PARTIAL"], _hc["NEW"], _hc["CLEAN"], _hc["UNKNOWN"]))
    _hrows = []
    for h in reversed(_hist[-100:]):
        _hr = h.get("read")
        _hrows.append({"checked": h.get("checked_at"), "verdict": h.get("verdict"),
                       "email": h.get("email"),
                       "read": "yes" if _hr else ("no" if _hr is False else "?"),
                       "breaches": (len(h.get("breaches") or []) if _hr else "-"),
                       "pastes": (len(h.get("pastes") or []) if _hr else "-")})
    st.dataframe(_hrows, width="stretch", height=260)
    st.caption("`read` is whether the address half answered. A dash means it did not, "
               "so the count beside it is unread - not zero. Rows written before this "
               "column existed show `?`.")
    if st.button("Clear my history"):
        breach.trace("CLICK", "history", "cleared")
        _hist_clear()
        st.rerun()
# @@END 010 HISTORY

# @@BLOCK 011 FOOTER deps=010
st.markdown("---")
_n1, _n2, _n3 = st.columns(3)
with _n1:
    try:
        st.page_link("app.py", label="\u26a1 Checker", width="stretch")
    except Exception:
        st.caption("Checker lives at app.py")
with _n2:
    try:
        st.page_link("pages/3_Mailbox_Reader.py", label="\U0001f4e5 Reader",
                     width="stretch")
    except Exception:
        st.caption("Reader lives at pages/3_Mailbox_Reader.py")
with _n3:
    try:
        st.page_link("pages/4_Downloads.py", label="\U0001f4e6 Export Studio",
                     width="stretch")
    except Exception:
        st.caption("Export Studio lives at pages/4_Downloads.py")

st.markdown("---")
auth.fit_panel(st)

st.caption("Sources: Pwned Passwords (k-anonymity - only 5 hash characters leave the "
           "box), the HIBP address search and the free breach list. No API key. Only "
           "the address is transmitted; a pasted password is never. A CLEAN verdict "
           "means not in those sources, not that the address was never exposed - and "
           "an address half that could not be read is flagged UNREAD rather than "
           "reported as zero.")
# @@END 011 FOOTER
# @@EOF
