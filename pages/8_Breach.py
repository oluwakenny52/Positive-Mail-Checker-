# @@FILE pages/8_Breach.py blocks=12 version=v13.84
# @@BLOCK 000 FILE_HEADER deps=-
"""
pages/8_Breach.py - breach exposure and combo freshness  (v13.84)
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

THE BANDS
---------
  NEW       password unseen, or exposure inside 365 days
  PARTIAL   password already circulating, or exposure inside 730 days
  OLD       password public for years, or only old breaches
  CLEAN     password unseen and address in no readable source
  UNKNOWN   nothing readable - the only honest answer when every tier failed

THE BROWSER (v13.84)
--------------------
The package comes from requirements.txt; the ~150 MB Chromium binary does not.
The browser row in section 1 installs it once, on a background thread, and shows
the state. A failed install prints its own error rather than pretending the site
was blocked. Passwords work with no browser at all - the browser only rescues an
address the site challenges.

ISOLATION
---------
The cache and the history resolve through auth.user_file(), so both are one
file per user. Nothing on this page reads another user's data.

Read-only except Run / Prepare browser / Clear history / downloads.
"""

import importlib
import json
import os
import re
import sys
import threading
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

auth.fit_panel(st)                  # the controls; collapsed until tapped

# The first theme read ran before the gate, on the anonymous prefix. Now that
# the passphrase is unlocked the owner's real file exists - re-read and repaint.
_TH = _theme()
st.markdown(_css(), unsafe_allow_html=True)
# @@END 005 HERO_GATE

# @@BLOCK 006 SOURCES deps=005
import breach

if not (hasattr(breach, "ensure_browser") and hasattr(breach, "check_many")):
    breach = importlib.reload(breach)

from auth import user_file

_HIST_NAME = "breach_history.jsonl"
_HIST_MAX = 2000
_OWNER_KEY = "_breach_owner"
_RUN_KEY = "_breach_run"
_RES_KEY = "_breach_results"
_QUAL_KEY = "_breach_quality"
_MSG_KEY = "_breach_msg"

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


def _csv(rows):
    """CSV, first five columns unchanged so anything downstream still reads."""
    head = ("verdict,email,breaches,pastes,pw_count,bucket,pw_hits,corpora,"
            "sites,sensitive,newest_breach_days,breach_names,data_classes,"
            "paste_titles,via,reason,error,checked_at")
    out = [head]
    for r in rows:
        bs = r.get("breaches") or []
        ps = r.get("pastes") or []
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
            str(r.get("newest_days") if r.get("newest_days") is not None else ""),
            '"%s"' % "; ".join(b.get("title") or "" for b in bs[:12]).replace('"', "'"),
            '"%s"' % "; ".join(sorted({c for b in bs
                                       for c in (b.get("classes") or [])})).replace('"', "'"),
            '"%s"' % "; ".join(p.get("title") or "" for p in ps[:12]).replace('"', "'"),
            str(r.get("via") or ""),
            '"%s"' % str(r.get("reason") or "").replace('"', "'"),
            '"%s"' % str(r.get("error") or "").replace('"', "'"),
            str(r.get("checked_at") or ""),
        ]))
    return "\n".join(out) + "\n"


# ---- owner gate: a second unlock in this tab must not inherit the last run ----
_owner = os.path.basename(user_file("")) or ""
if st.session_state.get(_OWNER_KEY) != _owner:
    for k in (_RES_KEY, _RUN_KEY, _QUAL_KEY, _MSG_KEY, "_breach_text"):
        st.session_state.pop(k, None)
    st.session_state[_OWNER_KEY] = _owner
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
        height=200, key="_breach_text",
        placeholder="someone@example.com:hunter2")
with _t2:
    up = st.file_uploader("Upload a .txt list", type=["txt"], key="_breach_up")
    if up is not None:
        try:
            _text = up.getvalue().decode("utf-8", errors="ignore")
        except Exception as e:
            st.error("Could not read that file: %s" % e)

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

# ---- the browser, and its state ------------------------------------------------
# Kicked on load so the first press already has one. Non-blocking and idempotent:
# a sentinel means done, a live thread means running, a previous failure stays
# failed until the button is pressed. The install is ~150 MB, so it is never
# retried on its own.
_bst = breach.browser_state()
if _bst.get("state") == "unknown":
    breach.ensure_browser()
    _bst = breach.browser_state()

_bst1, _bst2 = st.columns([0.72, 0.28])
with _bst1:
    if _bst.get("state") == "ready":
        st.caption("\u2705 Browser ready - a challenged address is resolved in place.")
    elif _bst.get("state") == "installing":
        st.caption("\u23f3 Browser installing (%ss). Passwords are checked either way; "
                   "a challenged address comes back UNKNOWN until it finishes."
                   % _bst.get("seconds", 0))
    elif _bst.get("state") == "failed":
        st.caption("\u26a0 Browser install FAILED. Passwords still work; a challenged "
                   "address comes back UNKNOWN. Error: `%s`"
                   % (_bst.get("error") or "unknown")[:300])
    else:
        st.caption("Browser not installed. Passwords are checked either way; a "
                   "challenged address comes back UNKNOWN without one.")
with _bst2:
    if _bst.get("state") != "ready" and _bst.get("state") != "installing":
        if st.button("\u2b07 Prepare browser", width="stretch",
                     help="Downloads Chromium once, into this repo, and keeps it. "
                          "About 150 MB - do it on wifi."):
            breach.ensure_browser(force=True)
            st.rerun()

_c1, _c2, _c3, _c4 = st.columns(4)
with _c1:
    _workers = st.slider("Workers", 1, 8, 4,
                         help="Pwned Passwords is a different host and takes "
                              "concurrency well. 4 is right for a phone.")
with _c2:
    _pages = st.number_input("Browser pages", 1, 8, 4, 1,
                             help="Chromium pages for addresses Cloudflare "
                                  "challenges. Only used when the browser is ready.")
with _c3:
    _force = st.checkbox("Ignore cache", value=False,
                         help="A cached answer is served for 6 hours. Tick this to "
                              "re-check from the sources, which is what you want "
                              "straight after changing anything.")
with _c4:
    _http_only = st.checkbox("HTTP only", value=False,
                             help="No browser. Faster, but a challenged address "
                                  "comes back UNKNOWN instead of resolved.")
# @@END 007 INPUT

# @@BLOCK 008 RUN deps=007
_run = st.button("\U0001f6e1 Check exposure", type="primary",
                 disabled=not _pairs, width="stretch")

if _run and _pairs:
    breach.configure(pages=int(_pages))
    _bar = st.progress(0.0, text="0 / %d" % len(_pairs))
    _cancel = threading.Event()

    def _tick(n, total, email, verdict):
        try:
            _bar.progress(min(1.0, n / max(1, total)),
                          text="%d / %d - %s" % (n, total, (verdict or "checking").lower()))
        except Exception:
            pass

    try:
        _rows = list(breach.check_many(
            _pairs, workers=int(_workers), progress=_tick, cancel=_cancel,
            force=bool(_force)).values())
    except Exception as e:
        _rows = []
        st.session_state[_MSG_KEY] = ("error", "Run failed: %s: %s"
                                      % (type(e).__name__, e))
    _bar.empty()

    if _rows:
        _rows.sort(key=lambda r: ({"OLD": 0, "PARTIAL": 1, "NEW": 2,
                                   "UNKNOWN": 3, "CLEAN": 4}.get(
                                       r.get("verdict") or "UNKNOWN", 5),
                                  r.get("email") or ""))
        _hist_add(_rows)
        st.session_state[_RES_KEY] = _rows
        st.session_state[_QUAL_KEY] = breach.score(_rows)
        st.session_state[_RUN_KEY] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        _b = _band_counts(_rows)
        _msg = ("Checked %d. %d old, %d partially new, %d new, %d clean, "
                "%d unresolved." % (len(_rows), _b["OLD"], _b["PARTIAL"],
                                    _b["NEW"], _b["CLEAN"], _b["UNKNOWN"]))
        # A message widget is REQUIRED here. Without one the ledger closes the
        # press as "NO RESULT | finished without reporting", which is exactly what
        # the 00:36:57 entry recorded.
        if _b["UNKNOWN"]:
            st.session_state[_MSG_KEY] = (
                "warning", _msg + " The unresolved ones could not be read - turn the "
                                  "browser on, or untick HTTP only.")
        else:
            st.session_state[_MSG_KEY] = ("success", _msg)
    elif not st.session_state.get(_MSG_KEY):
        st.session_state[_MSG_KEY] = ("warning", "Nothing was checked.")

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
                     horizontal=True, key="_breach_view")
    _show = _rows if _view == "All" else [r for r in _rows if r.get("verdict") == _view]

    if not _show:
        st.info("Nothing in that band.")
    else:
        for r in _show:
            _v = str(r.get("verdict") or "UNKNOWN")
            _bs = r.get("breaches") or []
            _ps = r.get("pastes") or []
            with st.expander("%s  %s" % (r.get("email") or "?", _v), expanded=False):
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
                if _bs:
                    st.markdown("**Breaches on this address**")
                    for b in _bs[:25]:
                        _d = b.get("days")
                        _age = "%d day(s) ago" % _d if _d is not None else "date unknown"
                        st.markdown("- **%s**%s - %s, %s record(s), classes: %s"
                                    % (b.get("title") or "?",
                                       " _(stealer corpus)_" if b.get("corpus") else "",
                                       _age, "{:,}".format(int(b.get("pwn_count") or 0)),
                                       ", ".join(b.get("classes") or []) or "-"))
                        if b.get("description"):
                            st.caption(b["description"][:300])
                else:
                    st.caption("No breach record for this address.")
                if _ps:
                    st.markdown("**Pastes quoting the address:** %d" % len(_ps))
                    for p in _ps[:10]:
                        st.caption("%s  %s" % (p.get("title") or "?", p.get("date") or ""))
                st.caption("via %s · checked %s"
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
st.markdown("### History (yours, capped at %d)" % _HIST_MAX)

_hist = _hist_read()
if not _hist:
    st.caption("Nothing stored yet. Every run appends here.")
else:
    st.caption("%d stored report(s), newest last." % len(_hist))
    _hc = _band_counts(_hist)
    st.caption("OLD %d · PARTIAL %d · NEW %d · CLEAN %d · UNKNOWN %d"
               % (_hc["OLD"], _hc["PARTIAL"], _hc["NEW"], _hc["CLEAN"], _hc["UNKNOWN"]))
    st.dataframe(
        [{"checked": h.get("checked_at"), "verdict": h.get("verdict"),
          "email": h.get("email"), "breaches": len(h.get("breaches") or []),
          "pastes": len(h.get("pastes") or [])} for h in reversed(_hist[-100:])],
        width="stretch", height=260)
    if st.button("Clear my history"):
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

st.caption("Sources: Pwned Passwords (k-anonymity - only 5 hash characters leave the "
           "box), the HIBP address search and the free breach list. No API key. A CLEAN "
           "verdict means not in those sources, not that the address was never exposed.")
# @@END 011 FOOTER
# @@EOF
