# @@FILE pages/8_Breach.py blocks=12 version=v13.86
# @@FILE pages/8_Breach.py blocks=12 version=v13.86
# @@BLOCK 000 FILE_HEADER deps=-
"""
pages/8_Breach.py - breach exposure and combo freshness  (v13.86)
=================================================================
What a list of combos has actually been in, with the verdict about FRESHNESS
rather than count.

WHAT CHANGED IN THIS PASS
-------------------------
Four defects, all reported from real runs:

  1. A 401 was being reported as a CLEAN address. The endpoint answers a real
     Chromium navigation with 200 on the same nodes the app was getting 401
     from, so the header set that was being forced onto the NAVIGATION is gone,
     and a refused attempt is now re-asked once from INSIDE the page with a
     same-origin fetch() - the call the site itself makes. Only a 404 is a
     readable zero any more.
  2. A combo was graded on its password alone. When the address half could not
     be read the combo read as PARTIAL off the password and said "no breach
     record - the source was read and lists none", which was not true. A combo
     whose address half is UNREAD is now UNKNOWN; the password band is still
     shown beside it but no longer decides the grade. Password-only lines are
     unaffected - there, the password IS the question.
  3. Nothing ever proved the pool against this endpoint. The Colab's second cell
     did, and that is now here: a test flight fetches Webshare and Oxylabs, drops
     the dead nodes on ipify, proves the rest in Chromium against the unified
     endpoint, and keeps only the survivors. It runs by itself when the flight
     pool is missing or stale, and can be run by hand.
  4. The record never carried its password, so the card could only show an
     address. It does now, so the card, the CSV and the rotate export show the
     combo that was actually checked.

THE ADDRESS HALF IS A REAL PAGE
-------------------------------
Through the app's OWN proxy pool - no key, no persistent profile to go stale.
Password-only and address-only lines are first class.

PAGES FOLLOW WORKERS
--------------------
There is no page-count control and no fixed number. If Workers is N the run keeps
at most N pages, one per worker slot, and REUSES them: a slot serves item after
item, blanked and with its cookies dropped between them, and it is only rebuilt
after 25 uses or 2 failed attempts in a row. The browser behind a slot is
launched once per worker for the whole batch, so 500 items cost N browsers, not
500. Recycling is local, so a stuck or challenged page can never lose a record
that is already written and can never hold the queue.

THE DRAW IS RANDOM
------------------
Each attempt draws a RANDOM node from the whole pool, never one already tried for
that item, and skips a node that has failed twice. `Random proxy per attempt`
turns that off and walks the tier order instead. DIRECT is the last attempt in
both modes, never the first.

HTML IS WRITTEN AS \x3c ESCAPES
------------------------------
Every angle bracket in a string literal is \x3c / \x3e and every entity is built
from chr(38). A paste that strips tags out of literals leaves both forms alone,
so the page view and the hero survive a paste that would otherwise turn a raw tag
into a bare newline.

WHAT EACH INPUT LINE IS
-----------------------
  email:password   both halves
  email            the address half only
  password         the password half only (a line with no '@')

WHAT EACH SOURCE IS
-------------------
  passwords  Pwned Passwords k-anonymity. Keyless, un-challenged, and the real
             signal - it says how public this exact password already is.
  address    the site's own unified search endpoint, fetched by a real Chromium
             page through the proxy pool, DIRECT as the last attempt.

WHAT LEAVES THE BOX
-------------------
Only the ADDRESS. A pasted `email:password` is cut at the colon before the URL
is built, so the password never reaches haveibeenpwned.com - which would not use
it anyway. The password goes to exactly one place: the SHA-1 hash for Pwned
Passwords, where 5 of the 40 characters leave and 35 are matched locally. The
plaintext is kept LOCALLY on the record so the card can show the combo.

THE BANDS
---------
  NEW       password unseen, or exposure inside 365 days, or a stealer log
  PARTIAL   password already circulating, or exposure inside 730 days
  OLD       password public for years, or only old breaches
  CLEAN     password unseen and the address in no readable source
  UNKNOWN   nothing readable, or a combo whose address half was never read

THE RUN DOES NOT RUN IN THE SCRIPT
----------------------------------
Streamlit holds the delta stream while a script run blocks, so the run is a
THREAD, its counters live in a session job dict, and this page polls them with
st.rerun(). The bar and the live trace move per item, Stop works, and a refresh
does not lose the run.

READ, VERSUS ZERO
-----------------
A card that said "0 breaches" could mean the page was read and lists none, or
that every attempt failed and nothing was read. Every record carries `read`; an
unread address half is flagged on the card, marked "-" in History, marked `no`
in the CSV and counted in the run summary.

ISOLATION
---------
The cache, the history, the trace and the flight all resolve through the pinned
owner, which is the unlocked hash, so each is one file per user. The proxy pool
is the owner's own proxies.txt, and the flight writes its survivors to the
owner's own proxies_breach.txt.

Read-only except Run / Stop / Prepare browser / Test flight / Clear cache /
Clear history / Clear trace / downloads.
"""

import hashlib
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
# The tags are \x3c / \x3e so a tag-stripping paste cannot empty the sheet.
_CSS_TMPL = """
\x3cstyle\x3e
    .br-hero {
        background: linear-gradient(135deg, __G1__ 0%, __G2__ 100%);
        padding: 18px 24px; border-radius: 14px; margin-bottom: 14px;
        border: 1px solid rgba(255,255,255,.12);
    }
    .br-hero h1 { color: #fff !important; margin: 0; font-size: 1.45rem;
                  font-weight: 800; }
    .br-hero p { color: rgba(255,255,255,.93) !important; margin: 6px 0 0 0;
                 font-size: .84rem; }
    .br-band { display:inline-block; padding:2px 9px; border-radius:999px;
               font-size:.7rem; font-weight:800; letter-spacing:.03em; }
    .br-new      { background:#22c55e33; color:#86efac; border:1px solid #22c55e66; }
    .br-partial  { background:#f59e0b33; color:#fcd34d; border:1px solid #f59e0b66; }
    .br-old      { background:#ef444433; color:#fca5a5; border:1px solid #ef444466; }
    .br-clean    { background:#64748b33; color:#cbd5e1; border:1px solid #64748b66; }
    .br-unknown  { background:#a78bfa33; color:#ddd6fe; border:1px solid #a78bfa66; }
    .br-mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
               font-size: .8rem; word-break: break-all; }
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
\x3c/style\x3e
"""


def _css():
    return (_CSS_TMPL.replace("__G1__", _TH["g1"])
            .replace("__G2__", _TH["g2"]))


st.markdown(_css(), unsafe_allow_html=True)
# @@END 004 CSS

# @@BLOCK 005 HERO_GATE deps=004
st.markdown(
    "\x3cdiv class='br-hero'\x3e\x3ch1\x3e\U0001f6e1 Breach Exposure\x3c/h1\x3e"
    "\x3cp\x3ePoint this at a list of combos, addresses or passwords. The address "
    "half is read by a real browser through your own proxy pool; the password half "
    "is a local SHA-1 and a k-anonymity lookup. The verdict is about how RECENT the "
    "exposure is.\x3c/p\x3e\x3c/div\x3e",
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

# INSTALL BEFORE require(), exactly as app.py block 007 does.
if hasattr(audit_log, "install"):
    audit_log.install(st, "pages/8_Breach.py")

auth.require(st, "Unlock Breach Exposure")
auth.fit(st)

_TH = _theme()
st.markdown(_css(), unsafe_allow_html=True)
# @@END 005 HERO_GATE

# @@BLOCK 006 SOURCES deps=005
import breach

# ---- stale-module guard -------------------------------------------------------
# Every marker is a capability this page calls. A module missing one predates it
# and is replaced before anything touches it. `_zero_rule`, PROXY_TRIES and the
# flight markers belong to the 401 fix and the test flight: a module without them
# still reported a 401 as CLEAN and still ran an unproven pool, so it has to go.
if not (hasattr(breach, "parse_lines") and hasattr(breach, "pool_lines")
        and hasattr(breach, "check_item") and hasattr(breach, "clear_cache")
        and hasattr(breach, "cache_stats") and hasattr(breach, "record_view")
        and hasattr(breach, "set_owner") and hasattr(breach, "_Slot")
        and hasattr(breach, "rotating") and hasattr(breach, "_zero_rule")
        and hasattr(breach, "PROXY_TRIES") and hasattr(breach, "catalogue")
        and hasattr(breach, "_cat_rows") and hasattr(breach, "catalogue_state")
        and hasattr(breach, "flight") and hasattr(breach, "flight_state")
        and hasattr(breach, "RETRY_STATUS") and hasattr(breach, "POOL_TTL")):
    breach = importlib.reload(breach)
    try:
        breach.trace("INFO", "page", "stale breach module replaced by reload")
    except Exception:
        pass

from auth import user_file

_HIST_NAME = "breach_history.jsonl"
_STATE_NAME = "breach_state.json"
_HIST_MAX = 2000
_OWNER_KEY = "_breach_owner"
_BOOT_KEY = "_breach_booted"
_RUN_KEY = "_breach_run"
_JOB_KEY = "_breach_job"
_RES_KEY = "_breach_results"
_QUAL_KEY = "_breach_quality"
_MSG_KEY = "_breach_msg"
_TRACE_SHOWN = "_breach_trace_shown"

_BAND_CSS = {"NEW": "br-new", "PARTIAL": "br-partial", "OLD": "br-old",
             "CLEAN": "br-clean", "UNKNOWN": "br-unknown"}

_AMP = chr(38) + "amp;"
_LT = chr(38) + "lt;"
_GT = chr(38) + "gt;"
_QUOT = chr(38) + "quot;"

_OWNER = os.path.basename(user_file("")) or ""
_pin_owner = getattr(breach, "set_owner", None)
if callable(_pin_owner):
    _pin_owner(_OWNER)


def _state_path():
    if _OWNER:
        return "%s_%s" % (_OWNER, _STATE_NAME)
    try:
        return user_file(_STATE_NAME)
    except Exception:
        return _STATE_NAME


def _state_load():
    """This user's last settings and results. {} when there are none."""
    p = _state_path()
    if not p or not os.path.exists(p):
        return {}
    try:
        with open(p, encoding="utf-8", errors="ignore") as fh:
            data = json.load(fh)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _state_save(rows, quality, stamp):
    """Persist settings + results + quality so a reload keeps them.

    The HTML is dropped and the text trimmed, so the file stays small.
    """
    p = _state_path()
    if not p:
        return
    try:
        slim = []
        for r in rows[-50:]:
            d = dict(r)
            d.pop("page_html", None)
            d["page_text"] = str(d.get("page_text") or "")[:4000]
            slim.append(d)
        data = {"settings": {
                    "workers": int(st.session_state.get("_breach_workers", 3)),
                    "delay": float(st.session_state.get("_breach_delay", 0.0)),
                    "rotate": bool(st.session_state.get("_breach_rotate", True)),
                    "view": st.session_state.get("_breach_view", "All")},
                "results": slim, "quality": quality or {}, "run_at": stamp}
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False)
        os.replace(tmp, p)
    except Exception:
        pass


def _state_apply():
    """Seed the widget keys BEFORE the widgets exist. Never overwrites a live one."""
    st_ = _state_load()
    setts = st_.get("settings") or {}
    pairs = (("_breach_workers", setts.get("workers")),
             ("_breach_delay", setts.get("delay")),
             ("_breach_rotate", setts.get("rotate")),
             ("_breach_view", setts.get("view")))
    for key, val in pairs:
        if val is None:
            continue
        if key not in st.session_state:
            st.session_state[key] = val
    if not st.session_state.get(_RES_KEY) and st_.get("results"):
        st.session_state[_RES_KEY] = st_["results"]
        st.session_state[_QUAL_KEY] = st_.get("quality") or {}
        st.session_state[_RUN_KEY] = st_.get("run_at") or ""


def _hist_path():
    if _OWNER:
        return "%s_%s" % (_OWNER, _HIST_NAME)
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
                d = dict(r)
                d.pop("page_html", None)
                d["page_text"] = str(d.get("page_text") or "")[:2000]
                fh.write(json.dumps(d, ensure_ascii=False) + "\n")
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


def _hist_count():
    p = _hist_path()
    if not p or not os.path.exists(p):
        return 0, 0
    try:
        with open(p, encoding="utf-8", errors="ignore") as fh:
            n = sum(1 for l in fh if l.strip())
        return n, os.path.getsize(p)
    except Exception:
        return 0, 0


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
    """A stable, unique widget key. The password is part of it, or two combos on
    one address would share every widget key on the page."""
    seed = r.get("email") or r.get("password_check", {}).get("sha1") or "row"
    if r.get("password"):
        seed = "%s|%s" % (seed, r.get("password"))
    base = re.sub(r"[^a-z0-9]+", "_", str(seed).lower()).strip("_")[:40] or "row"
    tail = hashlib.sha1(str(seed).encode("utf-8")).hexdigest()[:8]
    return "%s_%s" % (base, tail)


def _h_esc(v):
    return (str(v if v is not None else "").replace(chr(38), _AMP)
            .replace(chr(60), _LT).replace(chr(62), _GT).replace(chr(34), _QUOT))


def _label(r):
    """What the card is about: the combo exactly as it was checked."""
    if r.get("kind") == "password":
        return "password only"
    em = str(r.get("email") or "?")
    pw = str(r.get("password") or "")
    return "%s:%s" % (em, pw) if pw else em


def _combo_line(r):
    """One pasteable line for the rotate export."""
    if r.get("kind") == "password":
        return "pw:%s" % (r.get("password") or "")
    em = str(r.get("email") or "")
    pw = str(r.get("password") or "")
    return "%s:%s" % (em, pw) if pw else em


def _ago(sec):
    """Seconds -> a short age. Never raises, never negative."""
    try:
        s = int(sec if sec is not None else -1)
    except Exception:
        s = -1
    if s < 0:
        return "never"
    if s < 90:
        return "%d s" % s
    if s < 5400:
        return "%d min" % (s // 60)
    return "%d h" % (s // 3600)


def _record_page(r):
    """(text, html) of a record, built here when nothing was generated."""
    _fn = getattr(breach, "record_view", None)
    if callable(_fn):
        try:
            _t, _h = _fn(r)
            if _t or _h:
                return _t, _h
        except Exception:
            pass
    _text = ("kind: %s\naddress: %s\nverdict: %s\n"
             % (r.get("kind") or "?", _label(r), r.get("verdict") or "?"))
    return _text, ("\x3chtml\x3e\x3cbody\x3e\x3cpre\x3e" + _h_esc(_text)
                   + "\x3c/pre\x3e\x3c/body\x3e\x3c/html\x3e")


def _csv(rows):
    head = ("verdict,kind,email,password,pwned,breaches,pastes,pw_count,pw_hits,"
            "corpora,sites,stealer,sensitive,earliest_breach,latest_breach,"
            "total_exposed,breach_names,data_classes,paste_titles,via,via_proxy,"
            "reason,error,checked_at,read,partial")
    out = [head]
    for r in rows:
        bs = r.get("breaches") or []
        ps = r.get("pastes") or []
        out.append(",".join([
            str(r.get("verdict") or ""),
            str(r.get("kind") or ""),
            str(r.get("email") or ""),
            '"%s"' % str(r.get("password") or "").replace('"', "'"),
            "yes" if r.get("pwned") else "no",
            str(len(bs)),
            str(len(ps)),
            str(r.get("pw_count") if r.get("pw_count") is not None else ""),
            str(r.get("pw_count") if r.get("pw_count") is not None else ""),
            str(r.get("corpora", 0)),
            str(r.get("sites", 0)),
            str(r.get("stealer", 0)),
            str(r.get("sensitive", 0)),
            str(r.get("earliest_breach") or ""),
            str(r.get("latest_breach") or ""),
            str(r.get("total_records_exposed") or 0),
            '"%s"' % "; ".join(b.get("Name") or b.get("title") or ""
                               for b in bs[:12]).replace('"', "'"),
            '"%s"' % "; ".join(sorted({c for b in bs
                                       for c in (b.get("DataClasses")
                                                 or b.get("classes") or [])})).replace('"', "'"),
            '"%s"' % "; ".join(p.get("Title") or p.get("title") or ""
                               for p in ps[:12]).replace('"', "'"),
            str(r.get("via") or ""),
            str(r.get("via_proxy") or ""),
            '"%s"' % str(r.get("reason") or "").replace('"', "'"),
            '"%s"' % str(r.get("error") or "").replace('"', "'"),
            str(r.get("checked_at") or ""),
            "yes" if r.get("read") else "no",
            "yes" if r.get("partial_read") else "no",
        ]))
    return "\n".join(out) + "\n"


def _watch(key, label):
    def cb():
        try:
            breach.trace("CLICK", "control", "%s -> %r"
                         % (label, st.session_state.get(key)))
        except Exception:
            pass
    return cb


def _trace_code(limit=200, since=0, skip=None):
    return breach.trace_text(limit=limit, since=since, skip=skip)


def _trace_read(limit=250, skip=None):
    fn = getattr(breach, "trace_read", None)
    if not callable(fn):
        return []
    try:
        return list(fn(limit=limit, skip=skip))
    except TypeError:
        try:
            return list(fn(limit=limit))
        except Exception:
            return []
    except Exception:
        return []


# ---- owner gate ----
if st.session_state.get(_OWNER_KEY) != _OWNER:
    for k in (_RES_KEY, _RUN_KEY, _JOB_KEY, _QUAL_KEY, _MSG_KEY, "_breach_text",
              _TRACE_SHOWN):
        st.session_state.pop(k, None)
    st.session_state[_OWNER_KEY] = _OWNER
    st.session_state.pop(_BOOT_KEY, None)

# ---- a FRESH SESSION wipes the trace ----
if not st.session_state.get(_BOOT_KEY):
    st.session_state[_BOOT_KEY] = True
    try:
        breach.trace_clear()
    except Exception:
        pass

# ---- settings and results survive a reload ----
_state_apply()

breach.trace("INFO", "page", "loaded")
# @@END 006 SOURCES

# @@BLOCK 007 INPUT deps=006
st.markdown("### 1. Input")

_t1, _t2 = st.tabs(["\U0001f4dd Paste", "\U0001f4c1 Upload"])

_text = ""
with _t1:
    _text = st.text_area(
        "One entry per line. `email:pass` checks both halves, an address on its own "
        "checks only its breaches, and a line with no `@` is treated as a PASSWORD and "
        "checked against Pwned Passwords only.",
        height=200, key="_breach_text", on_change=_watch("_breach_text", "text"),
        placeholder="someone@example.com:hunter2\nsomeone@example.com\nhunter2")
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

_items = breach.parse_lines(_text)
_n_combo = sum(1 for i in _items if i["kind"] == "combo")
_n_mail = sum(1 for i in _items if i["kind"] == "email")
_n_pw = sum(1 for i in _items if i["kind"] == "password")
if _items:
    st.caption("**%d** item(s) ready - **%d** combo(s), **%d** address only, "
               "**%d** password only." % (len(_items), _n_combo, _n_mail, _n_pw))
else:
    st.caption("Nothing queued.")

st.caption("Only the address is sent to haveibeenpwned.com - a pasted `email:password` "
           "is cut at the colon before the request is built. The password only ever "
           "goes to the Pwned Passwords hash check, and 5 of its 40 hash characters "
           "leave the box. The plaintext stays on the record so the card can show the "
           "combo it came from.")

# ---- the browser, and its state ------------------------------------------------
_bst = breach.browser_state()
if _bst.get("state") == "unknown":
    breach.ensure_browser()
    _bst = breach.browser_state()

_bst1, _bst2 = st.columns([0.72, 0.28])
with _bst1:
    if _bst.get("state") == "ready":
        st.caption("\u2705 Browser ready - the address half is a real page, through "
                   "your proxy pool. One page per worker, reused for the whole run.")
    elif _bst.get("state") == "installing":
        st.caption("\u23f3 Browser installing (%ss). Passwords work either way; "
                   "addresses come back UNREAD until it finishes."
                   % _bst.get("seconds", 0))
    elif _bst.get("state") == "failed":
        st.caption("\u26a0 Browser install FAILED. Passwords still work; addresses "
                   "come back UNREAD. Error: `%s`"
                   % (_bst.get("error") or "unknown")[:300])
    else:
        st.caption("Browser not installed. Passwords are checked either way; addresses "
                   "come back UNREAD without one.")
with _bst2:
    if _bst.get("state") not in ("ready", "installing"):
        if st.button("\u2b07 Prepare browser", width="stretch",
                     help="Downloads Chromium once, into this repo, and keeps it. "
                          "About 150 MB - do it on wifi."):
            breach.trace("CLICK", "browser", "Prepare browser pressed")
            breach.ensure_browser(force=True)
            st.rerun()

# ---- the pool, and the test flight that proves it ------------------------------
_fst = breach.flight_state()
_pstat = breach.pool_status()
if _pstat["count"]:
    st.caption("\U0001f310 **%d** proxy node(s) loaded%s - probed nodes first, DIRECT "
               "as the last attempt. Sample: `%s`"
               % (_pstat["count"],
                  " from your test flight" if _pstat.get("flight") else " from your pool",
                  ", ".join(p.rsplit("@", 1)[-1] for p in _pstat["sample"])))
else:
    st.warning("\U0001f310 **Your proxy pool is empty.** The address half will try "
               "DIRECT only. Run the test flight, or import a list on the checker page.")

_f1, _f2 = st.columns([0.72, 0.28])
with _f1:
    if _fst.get("busy"):
        st.caption("\u2708 **Test flight running** - fetching candidates and proving "
                   "each one in Chromium. The run waits for it.")
    elif _fst.get("ts"):
        st.caption("\u2708 Last test flight %s ago: **%d** candidate(s), **%d** kept. "
                   "Only kept nodes are drawn."
                   % (_ago(_fst.get("age")), int(_fst.get("candidates") or 0),
                      int(_fst.get("kept") or 0))
                   + ((" Error: `%s`" % _fst["error"]) if _fst.get("error") else ""))
    else:
        st.caption("\u2708 No test flight yet. One runs by itself before a run whenever "
                   "the flight pool is missing or older than **%d minutes** - so the "
                   "run never draws from a pool nobody has proved."
                   % max(1, int(breach.POOL_TTL // 60)))
with _f2:
    if st.button("\u2708 Run test flight", width="stretch",
                 disabled=bool(_fst.get("busy")),
                 help="Fetches Webshare + Oxylabs, drops the dead nodes on ipify, then "
                      "proves the rest in Chromium against this exact endpoint. Only "
                      "the survivors are written and used."):
        breach.trace("CLICK", "flight", "pressed by the page")
        breach.flight(force=True)
        st.rerun()

# ---- workers, pacing, the draw -------------------------------------------------
_c1, _c2, _c3 = st.columns(3)
with _c1:
    _workers = st.slider("Workers", 1, 12, 3, key="_breach_workers",
                         on_change=_watch("_breach_workers", "workers"),
                         help="How many items are worked on at the same time. This is "
                              "also the page count: N workers keep at most N pages, "
                              "reused for every item after the first.")
with _c2:
    _delay = st.slider("Delay (s)", 0.0, 5.0, 0.0, 0.5, key="_breach_delay",
                       on_change=_watch("_breach_delay", "delay"),
                       help="Seconds between STARTING items. 0 is fine for a probed "
                            "pool.")
with _c3:
    _rotate = st.checkbox("\U0001f3b2 Random proxy per attempt", value=True,
                          key="_breach_rotate",
                          on_change=_watch("_breach_rotate", "rotate"),
                          help="ON: every attempt draws a different random node from "
                               "the whole pool, so one node never carries the run. "
                               "OFF: walk the probed order instead, same spread, "
                               "easier to read in the trace.")

st.caption("**%d** worker(s), so at most **%d** page(s), each reused and reset "
           "between items and recycled after a challenge. **%d** proxy node(s), drawn "
           "at random per attempt with DIRECT as the last attempt."
           % (int(_workers), int(_workers), _pstat["count"]))

# ---- cache and history, monitored and clearable --------------------------------
st.markdown("##### Cache and history")
_cstat = breach.cache_stats()
_h_n, _h_b = _hist_count()
_m1, _m2, _m3 = st.columns(3)
_m1.metric("Cache entries", _cstat.get("entries", 0),
           help="Answered items kept for 6 hours in `%s`. "
                "A cached answer sends no request." % _cstat.get("path", "-"))
_m2.metric("History rows", _h_n, help="Appended by every run, capped at %d." % _HIST_MAX)
_m3.metric("History size", "%d KB" % max(0, _h_b // 1024))
_b1, _b2, _b3 = st.columns(3)
with _b1:
    if st.button("Clear cache", width="stretch",
                 help="Forgets every cached answer for this user."):
        breach.clear_cache()
        breach.trace("CLICK", "cache", "cleared")
        st.rerun()
with _b2:
    if st.button("Clear history", width="stretch",
                 help="Deletes your breach_history.jsonl and the saved result state."):
        breach.trace("CLICK", "history", "cleared")
        _hist_clear()
        st.session_state.pop(_RES_KEY, None)
        st.session_state.pop(_QUAL_KEY, None)
        st.session_state.pop(_RUN_KEY, None)
        try:
            if os.path.exists(_state_path()):
                os.remove(_state_path())
        except Exception:
            pass
        st.rerun()
with _b3:
    if st.button("Clear cache + history", width="stretch"):
        breach.clear_cache()
        breach.trace("CLICK", "cache", "cleared with history")
        _hist_clear()
        st.session_state.pop(_RES_KEY, None)
        st.session_state.pop(_QUAL_KEY, None)
        st.session_state.pop(_RUN_KEY, None)
        try:
            if os.path.exists(_state_path()):
                os.remove(_state_path())
        except Exception:
            pass
        st.rerun()
# @@END 007 INPUT

# @@BLOCK 008 RUN deps=007
_job = st.session_state.get(_JOB_KEY)
if isinstance(_job, dict) and not _job.get("done"):
    try:
        if time.time() - float(_job.get("started") or 0) > 3600.0:
            _job["error"] = _job.get("error") or "watchdog: the run stopped reporting"
            _job["done"] = True
    except Exception:
        pass
_running = bool(isinstance(_job, dict) and not _job.get("done"))

_bc1, _bc2 = st.columns([0.72, 0.28])
with _bc1:
    _run = st.button("\U0001f6e1 Check exposure", type="primary",
                     disabled=(not _items or _running), width="stretch")
with _bc2:
    _stop = st.button("\u23f9 Stop", width="stretch", disabled=not _running,
                      help="Cancels the run. Workers stop mid-item and queued items "
                           "are dropped; finished records are kept.")


def _job_start():
    """Start the run on a THREAD. The cancel event travels into check_many."""
    job = {"rows": {}, "done": False, "n": 0, "total": len(_items), "last": "",
           "error": "", "cancel": threading.Event(), "started": time.time(),
           "since0": breach.trace_seq(), "owner": _OWNER}
    st.session_state[_JOB_KEY] = job

    def _tick(n, total, label, verdict):
        try:
            job["n"] = int(n or 0)
            job["last"] = ("%s %s" % (label or "", (verdict or "").lower())).strip()
        except Exception:
            pass

    def _body():
        try:
            job["rows"] = breach.check_many(
                _items, workers=int(_workers), progress=_tick,
                cancel=job["cancel"], delay=float(_delay),
                rotate=bool(_rotate), owner_prefix=_OWNER)
        except Exception as e:
            job["error"] = "%s: %s" % (type(e).__name__, e)
            breach.trace("ERR", "run", "raised %s: %s" % (type(e).__name__, e))
        finally:
            job["done"] = True

    threading.Thread(target=_body, name="breach-run", daemon=True).start()
    return job


if _run and _items and not _running:
    breach.trace("CLICK", "run", "pressed: %d item(s), workers=%d, delay=%s, pool=%d, "
                 "rotate=%s" % (len(_items), int(_workers), _delay, _pstat["count"],
                                "on" if _rotate else "off"))
    breach.configure(workers=int(_workers), delay=float(_delay),
                     rotate=bool(_rotate))
    _job = _job_start()
    _running = True

if isinstance(_job, dict):
    _total = max(1, int(_job.get("total") or 0))
    _n = int(_job.get("n") or 0)
    _cancelling = bool(_job.get("cancel") is not None and _job["cancel"].is_set())
    st.progress(min(1.0, _n / _total),
                text="%d / %d%s%s" % (_n, _total,
                                      " - stopping" if _cancelling else "",
                                      (" - " + _job["last"]) if _job.get("last") else ""))
    _live = st.empty()
    try:
        _live.code(_trace_code(limit=12, since=int(_job.get("since0") or 0),
                               skip=("page",)), language="text")
    except Exception:
        pass

    if _running:
        if _stop:
            try:
                _job["cancel"].set()
            except Exception:
                pass
            breach.trace("CLICK", "run", "stop requested")
        time.sleep(1.0)
        st.rerun()
    else:
        st.session_state.pop(_JOB_KEY, None)
        _rows = list((_job.get("rows") or {}).values())
        if _job.get("error"):
            st.session_state[_MSG_KEY] = ("error", "Run failed: %s" % _job["error"])
        elif not _rows:
            st.session_state[_MSG_KEY] = ("warning", "Nothing was checked.")
        else:
            _rows.sort(key=lambda r: ({"OLD": 0, "PARTIAL": 1, "NEW": 2,
                                       "UNKNOWN": 3, "CLEAN": 4}.get(
                                           r.get("verdict") or "UNKNOWN", 5),
                                      r.get("email") or r.get("kind") or ""))
            _hist_add(_rows)
            _quality = breach.score(_rows)
            _stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            st.session_state[_RES_KEY] = _rows
            st.session_state[_QUAL_KEY] = _quality
            st.session_state[_RUN_KEY] = _stamp
            _state_save(_rows, _quality, _stamp)
            _b = _band_counts(_rows)
            _unread = sum(1 for r in _rows
                          if not r.get("read") and r.get("kind") != "password")
            _cancel_n = sum(1 for r in _rows if "cancel" in str(r.get("error") or ""))
            _msg = ("Checked %d. %d old, %d partially new, %d new, %d clean, "
                    "%d unresolved. %d unread. %d cancelled."
                    % (len(_rows), _b["OLD"], _b["PARTIAL"], _b["NEW"],
                       _b["CLEAN"], _b["UNKNOWN"], _unread, _cancel_n))
            breach.trace("INFO", "run", "summary: " + _msg)
            _tips = []
            if _unread:
                _tips.append("%d address half(s) are UNREAD, not zero." % _unread)
            if _b["UNKNOWN"]:
                _tips.append("Re-run the unresolved ones - a fresh random proxy is "
                             "drawn for each attempt, so a second pass usually lands.")
            _lvl = "warning" if (_unread or _b["UNKNOWN"]) else "success"
            st.session_state[_MSG_KEY] = (
                _lvl, _msg + ((" " + " ".join(_tips)) if _tips else ""))

if st.session_state.get(_MSG_KEY):
    _lvl, _msg = st.session_state.pop(_MSG_KEY)
    getattr(st, _lvl, st.info)(_msg)
# @@END 008 RUN

# @@BLOCK 009 DASHBOARD deps=008
_rows = st.session_state.get(_RES_KEY) or []
# A 500-item run cannot draw 500 expanders on a phone in one go.
_CARD_MAX = 150


def _iframe(html, height=520):
    """st.iframe when the runtime has it, else the legacy component.

    st.iframe takes an HTML string directly and auto-detects it as markup. The
    legacy call is only reached on a Streamlit old enough not to have it, and
    `components.v1.html` prints a deprecation line on every single call.
    """
    fn = getattr(st, "iframe", None)
    if callable(fn):
        fn(html, height=height)
        return
    import streamlit.components.v1 as components
    components.html(html, height=height, scrolling=True)


if _rows:
    _b = _band_counts(_rows)
    _q = st.session_state.get(_QUAL_KEY) or {}
    _stamp = st.session_state.get(_RUN_KEY) or ""

    st.markdown("### 2. Combo quality")
    st.caption("Checked %s. **%d** item(s)." % (_stamp, len(_rows)))

    _qc1, _qc2, _qc3, _qc4 = st.columns(4)
    _qc1.metric("Quality", "%s%%" % _q.get("quality", 0), _q.get("grade", "-"),
                delta_color="off",
                help="(NEW x1.0 + PARTIAL x0.5 + OLD x0.15) / scored.")
    _qc2.metric("Old", "%s%%" % _q.get("pct", {}).get("OLD", 0))
    _qc3.metric("Partially new", "%s%%" % _q.get("pct", {}).get("PARTIAL", 0))
    _qc4.metric("New", "%s%%" % _q.get("pct", {}).get("NEW", 0))

    st.caption(
        "%s%% of this set is OLD - rotate that password everywhere it was reused. "
        "%s%% is partially new. %s%% is new. %s%% unresolved and excluded."
        % (_q.get("pct", {}).get("OLD", 0), _q.get("pct", {}).get("PARTIAL", 0),
           _q.get("pct", {}).get("NEW", 0), _q.get("pct", {}).get("UNKNOWN", 0)))

    _unread_rows = [r for r in _rows
                    if not r.get("read") and r.get("kind") != "password"]
    if _unread_rows:
        st.caption("\u26a0 **%d of %d address half(s) were never read.** Every attempt "
                   "on them was refused, so they are UNKNOWN - a password alone does "
                   "not grade a combo. Re-run them; a fresh node is drawn each time."
                   % (len(_unread_rows), len(_rows)))
    _dom_rows = [r for r in _rows if r.get("partial_read")]
    if _dom_rows:
        st.caption("\U0001f4da **%d of %d were matched by DOMAIN**, not by the exact "
                   "address - the exact search was refused and the catalogue answered "
                   "instead. The breach list is real for the domain; this mailbox is "
                   "not individually confirmed."
                   % (len(_dom_rows), len(_rows)))
    st.bar_chart({"Band": list(_q.get("buckets", {}).keys()),
                  "Count": list(_q.get("buckets", {}).values())},
                 x="Band", y="Count", height=160)

    _m = st.columns(5)
    _m[0].metric("\U0001f525 OLD", _b["OLD"])
    _m[1].metric("\u26a0 PARTIAL", _b["PARTIAL"])
    _m[2].metric("\u2705 NEW", _b["NEW"])
    _m[3].metric("\U0001f5c4 CLEAN", _b["CLEAN"])
    _m[4].metric("\u2753 UNKNOWN", _b["UNKNOWN"])

    if _b["OLD"]:
        st.error("**%d combo(s) are old bridges.** Rotate and change them everywhere."
                 % _b["OLD"])
    elif _b["PARTIAL"]:
        st.warning("**%d combo(s) are partially new.** The password already circulates."
                   % _b["PARTIAL"])

    _view = st.radio("Show",
                     ["OLD", "PARTIAL", "NEW", "UNKNOWN", "CLEAN", "All"],
                     horizontal=True, key="_breach_view",
                     on_change=_watch("_breach_view", "band filter"))
    _show = _rows if _view == "All" else [r for r in _rows if r.get("verdict") == _view]

    if not _show:
        st.info("Nothing in that band.")
    else:
        if len(_show) > _CARD_MAX:
            st.caption("Showing the first **%d** of **%d**. Use the band filter to "
                       "narrow it, or the CSV export for the rest."
                       % (_CARD_MAX, len(_show)))
        for r in _show[:_CARD_MAX]:
            _v = str(r.get("verdict") or "UNKNOWN")
            _bs = r.get("breaches") or []
            _ps = r.get("pastes") or []
            _read = bool(r.get("read"))
            _dom = bool(r.get("partial_read"))
            _head_v = (_v if r.get("pw_band") != "none"
                       else str(r.get("addr_verdict") or _v))
            _key = _row_key(r)
            with st.expander("%s %s%s" % ("\u26a0" if not _read else "\u2022",
                                          _label(r), "  " + _head_v),
                             expanded=False):
                _av = str(r.get("addr_verdict") or "UNREAD")
                _pb = str(r.get("pw_band") or "none")
                st.markdown(
                    "\x3cspan class='br-band %s'\x3eaddress %s\x3c/span\x3e\u00a0 "
                    "\x3cspan class='br-band %s'\x3epassword %s\x3c/span\x3e\u00a0 %s"
                    % (_BAND_CSS.get(_av, "br-unknown"), _av,
                       _BAND_CSS.get(_pb, "br-unknown"), _pb,
                       _h_esc(r.get("reason") or "")), unsafe_allow_html=True)
                if _v == "UNKNOWN" and _av == "UNREAD" and _pb != "none":
                    st.caption("Combo verdict **UNKNOWN** - the address half was not "
                               "read, so the password half does not grade the combo. "
                               "Address half: **%s**. Password half: **%s**."
                               % (_av, _pb))
                else:
                    st.caption("Combo verdict **%s** - the worse of the two halves. "
                               "Address half: **%s**. Password half: **%s**."
                               % (_v, _av, _pb))
                if r.get("pw_count") is not None:
                    st.caption("Password appears **%s** time(s) in Pwned Passwords."
                               % "{:,}".format(int(r["pw_count"])))
                else:
                    st.caption("Password not supplied - the address half IS the "
                               "verdict.")
                if r.get("error"):
                    st.caption("error: %s" % r["error"])
                if _dom:
                    st.caption("\U0001f4da **Matched by domain** (`%s`) from the "
                               "catalogue - the exact search was refused, so this "
                               "mailbox is not individually confirmed."
                               % (str(r.get("email") or "").rsplit("@", 1)[-1] or "?"))
                elif not _read and r.get("kind") != "password":
                    st.caption("\u26a0 **The address half was not read.** Every attempt "
                               "was refused; the counts are unread, not zero.")
                if _bs:
                    st.markdown("**Breaches on this address** - %d" % len(_bs))
                    for b in _bs[:25]:
                        _d = b.get("days")
                        _when = (b.get("BreachDate") or b.get("date")
                                 or ("%d day(s) ago" % _d if _d is not None
                                     else "date unknown"))
                        st.markdown("- **%s**%s - %s, %s record(s), classes: %s"
                                    % (b.get("Title") or b.get("title") or "?",
                                       " _(stealer log)_" if (b.get("IsStealerLog")
                                                              or b.get("corpus")) else "",
                                       _when,
                                       "{:,}".format(int(b.get("PwnCount")
                                                         or b.get("pwn_count") or 0)),
                                       ", ".join(b.get("DataClasses")
                                                 or b.get("classes") or []) or "-"))
                        if b.get("Description") or b.get("description"):
                            st.caption(str(b.get("Description")
                                           or b.get("description"))[:300])
                elif _read:
                    st.caption("No breach record - the source was read and lists none.")
                elif r.get("error"):
                    st.caption("No breach record could be read - see the error above.")
                if _ps:
                    st.markdown("**Pastes quoting the address:** %d" % len(_ps))
                    for p in _ps[:10]:
                        st.caption("%s  %s" % (p.get("Title") or p.get("title") or "?",
                                               p.get("Date") or p.get("date") or ""))

                _pg_t, _pg_h = _record_page(r)
                st.caption("Page view - built from the answer, not a captured page.")
                _pv = st.radio("Page view", ["Text", "HTML"], horizontal=True, index=0,
                               key="_pv_%s" % _key)
                if _pv == "Text":
                    st.code(_pg_t[:30000] or "(empty page)", language="text")
                    st.download_button(
                        "\u2b07 Download this page as text",
                        data=_pg_t.encode("utf-8"),
                        file_name="page_%s.txt" % _key,
                        mime="text/plain", width="stretch",
                        key="_pvt_%s" % _key)
                else:
                    _iframe(_pg_h or "\x3cp\x3e(empty page)\x3c/p\x3e", height=520)
                    st.download_button(
                        "\u2b07 Download this page as HTML",
                        data=_pg_h.encode("utf-8"),
                        file_name="page_%s.html" % _key,
                        mime="text/html", width="stretch",
                        key="_pvh_%s" % _key)

                st.caption("via %s \u00b7 checked %s"
                           % (r.get("via_proxy") or r.get("via") or "-",
                              r.get("checked_at") or ""))

    st.markdown("### 3. Export")
    _d1, _d2, _d3 = st.columns(3)
    with _d1:
        st.download_button("\u2b07 Download CSV (all bands)",
                           data=_csv(_rows).encode("utf-8"),
                           file_name="breach_%s.csv"
                                     % datetime.now().strftime("%Y%m%d_%H%M%S"),
                           mime="text/csv", width="stretch")
    with _d2:
        st.download_button("\u2b07 Download JSON (full records)",
                           data=json.dumps(_rows, indent=2,
                                           ensure_ascii=False).encode("utf-8"),
                           file_name="breach_%s.json"
                                     % datetime.now().strftime("%Y%m%d_%H%M%S"),
                           mime="application/json", width="stretch")
    with _d3:
        _bad = [r for r in _rows if r.get("verdict") in ("OLD", "PARTIAL")]
        st.download_button("\u2b07 Download OLD + PARTIAL combos",
                           data="\n".join(_combo_line(r) for r in _bad).encode(),
                           file_name="breach_rotate_%d.txt" % len(_bad),
                           mime="text/plain", width="stretch", disabled=not _bad)
# @@END 009 DASHBOARD

# @@BLOCK 010 HISTORY deps=009
st.markdown("---")
st.markdown("### 4. Trace")
st.caption("Everything that happened, newest last: each control moved, each item "
           "started, the node drawn, the status, whether a challenge appeared, the "
           "band and every error. `%s` carries only the address - the password is "
           "never in it."
           % (breach.last_url()
              or "https://haveibeenpwned.com/unifiedsearch/\x3caddress\x3e"))

_tevents = _trace_read(limit=250, skip=("page",))
if not _tevents:
    st.caption("Nothing traced yet.")
else:
    st.code(breach.trace_text(limit=250, skip=("page",)), language="text")

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
                       "kind": h.get("kind"),
                       "email": h.get("email") or "-",
                       "read": "yes" if _hr else ("no" if _hr is False else "?"),
                       "breaches": (len(h.get("breaches") or []) if _hr else "-"),
                       "pastes": (len(h.get("pastes") or []) if _hr else "-"),
                       "pw_hits": (h.get("pw_count")
                                   if h.get("pw_count") is not None else "-")})
    st.dataframe(_hrows, width="stretch", height=260)
    st.caption("`read` is whether the address half answered. A dash means it did not, "
               "so the count beside it is unread - not zero. Rows written before this "
               "column existed show `?`.")
    if st.button("Clear my history"):
        breach.trace("CLICK", "history", "cleared")
        _hist_clear()
        st.session_state.pop(_RES_KEY, None)
        st.session_state.pop(_QUAL_KEY, None)
        st.session_state.pop(_RUN_KEY, None)
        try:
            if os.path.exists(_state_path()):
                os.remove(_state_path())
        except Exception:
            pass
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
           "box) and the site's unified search read by a real browser through your "
           "proxy pool, DIRECT as the last attempt. Only the address is transmitted; "
           "a pasted password is never. A CLEAN verdict means not in those sources, "
           "not that the address was never exposed - and an address half that could "
           "not be read is flagged UNREAD rather than reported as zero.")
# @@END 011 FOOTER
# @@EOF
