# @@FILE pages/8_Breach.py blocks=12 version=v13.76
# @@BLOCK 000 FILE_HEADER deps=-
"""
pages/8_Breach.py - breach exposure  (v13.76)
=============================================
What a list of addresses has actually been in, from free keyless sources, with
the verdict about FRESHNESS rather than count.

WHY A PAGE AND NOT A RUN STEP
-----------------------------
A breach lookup is slow and rate-limited, and its answer never changes a mail
verdict. Putting it in the checker would spend ladder time on it. Here it is a
separate queue you point at a list when you want it.

WHAT EACH SOURCE IS, AND WHAT IT COSTS
--------------------------------------
  catalogue  /api/v3/breaches - ONE fetch for the whole page, then matched
             locally by domain. 500 addresses make one request, not 500.
  account    the HIBP account page, scraped ONLY when the local match is empty,
             at one request every 2 seconds because HIBP throttles HTML.
  pastes     psbdmp.ws per address, 1 hour cached.

THE BANDS
---------
  ACT       a breach added inside 90 days, or a paste from the last year
  REVIEW    a breach added inside a year
  HISTORIC  only old breaches or old pastes - rotate anyway
  CLEAN     not in the catalogue
  UNKNOWN   no readable answer

ISOLATION
---------
The cache and the history resolve through auth.user_file(), so both are one
file per user. Nothing on this page reads another user's data.

Read-only except Run / Clear history / downloads.
"""

import importlib
import json
import os
import re
import sys
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
    .br-act      { background:#ef444433; color:#fca5a5; border:1px solid #ef444466; }
    .br-review   { background:#f59e0b33; color:#fcd34d; border:1px solid #f59e0b66; }
    .br-historic { background:#64748b33; color:#cbd5e1; border:1px solid #64748b66; }
    .br-clean    { background:#22c55e33; color:#86efac; border:1px solid #22c55e66; }
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
    '<p>Point this at a list of addresses. Free sources only - no API key, no '
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

if not (hasattr(breach, "check") and hasattr(breach, "catalogue")):
    breach = importlib.reload(breach)

import sentinel

if not (hasattr(sentinel, "expect") and hasattr(sentinel, "satisfy")):
    sentinel = importlib.reload(sentinel)

from auth import user_file

_HIST_NAME = "breach_history.jsonl"
_HIST_MAX = 2000
_OWNER_KEY = "_breach_owner"
_RUN_KEY = "_breach_run"
_RES_KEY = "_breach_results"

_BAND_CSS = {"ACT": "br-act", "REVIEW": "br-review", "HISTORIC": "br-historic",
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


def _parse_queue(text):
    """Dedupe, validate, and keep the order. Returns (good, rejected)."""
    good, bad, seen = [], [], set()
    for raw in str(text or "").splitlines():
        a = raw.strip().lstrip("\ufeff").strip("\"'").strip()
        if "|" in a:
            a = a.split("|", 1)[0].strip()
        if ":" in a and "@" in a:
            a = a.split(":", 1)[0].strip()
        a = a.lower()
        if not a or a in seen:
            continue
        seen.add(a)
        (good if breach.is_email(a) else bad).append(a)
    return good, bad


def _band_counts(rows):
    c = {"ACT": 0, "REVIEW": 0, "HISTORIC": 0, "CLEAN": 0, "UNKNOWN": 0}
    for r in rows:
        v = str(r.get("verdict") or "UNKNOWN")
        c[v] = c.get(v, 0) + 1
    return c


def _csv(rows):
    head = ("verdict,email,domain,breach_count,newest_breach_days,breaches,"
            "pastes,reason,checked_at")
    out = [head]
    for r in rows:
        bs = r.get("breaches") or []
        newest = bs[0].get("added_days", -1) if bs else -1
        names = " ".join(sorted({str(b.get("title") or b.get("name") or "")
                                 for b in bs}))[:400]
        out.append(",".join([
            str(r.get("verdict") or ""),
            str(r.get("email") or ""),
            str(r.get("domain") or ""),
            str(r.get("count") if r.get("count") is not None else ""),
            str(newest),
            '"%s"' % names.replace('"', "'"),
            str(len(r.get("pastes") or [])),
            '"%s"' % str(r.get("reason") or "").replace('"', "'"),
            str(r.get("checked_at") or ""),
        ]))
    return "\n".join(out) + "\n"


# ---- owner gate: a second unlock in this tab must not inherit the last run ----
_owner = os.path.basename(user_file("")) or ""
if st.session_state.get(_OWNER_KEY) != _owner:
    for k in (_RES_KEY, _RUN_KEY, "_breach_text"):
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
        "cut down to the address.",
        height=200, key="_breach_text",
        placeholder="someone@example.com")
with _t2:
    up = st.file_uploader("Upload a .txt list", type=["txt"], key="_breach_up")
    if up is not None:
        try:
            _text = up.getvalue().decode("utf-8", errors="ignore")
        except Exception as e:
            st.error("Could not read that file: %s" % e)

_good, _bad = _parse_queue(_text)
if _good:
    st.caption("**%d** address(es) ready, **%d** line(s) not an address."
               % (len(_good), len(_bad)))
elif _bad:
    st.caption("No usable address yet - **%d** line(s) rejected." % len(_bad))
else:
    st.caption("Nothing queued.")

_c1, _c2, _c3 = st.columns(3)
with _c1:
    _workers = st.slider("Workers", 1, 8, 3,
                         help="The account page is throttled to one request every "
                              "2 seconds process-wide, so more than 4 rarely helps.")
with _c2:
    _only_bad = st.checkbox("Skip the account-page check", value=False,
                            help="Catalogue match only. Fastest, and no per-address "
                                 "request at all - but a personal domain will read "
                                 "CLEAN when the breach list would have known it.")
with _c3:
    _run = st.button("\U0001f6e1 Check exposure", type="primary",
                     disabled=not _good)
# @@END 007 INPUT

# @@BLOCK 008 RUN deps=007
if _run and _good:
    _bar = st.progress(0.0, text="Fetching the breach catalogue...")
    _rows = []
    try:
        _cat = breach.catalogue()
        if not _cat:
            st.warning("The breach catalogue did not load. Results below are from the "
                       "account page only, which is slower and thinner.")
        sentinel.expect("breach", "catalogue", "the catalogue fetched or answered empty")
        if _cat:
            sentinel.satisfy("breach")

        _n = len(_good)
        _done = 0
        for a in _good:
            _done += 1
            r = breach.check(a)
            if _only_bad and r.get("verdict") == "CLEAN":
                r["breaches"] = []
            _rows.append(r)
            _bar.progress(_done / max(1, _n),
                          text="%d/%d - %s" % (_done, _n, a))
        _bar.progress(1.0, text="Done - %d address(es)." % _n)
        _hist_add(_rows)
        sentinel.expect("breach", "results", "one result per queued address")
        if len(_rows) == _n:
            sentinel.satisfy("breach")
    except Exception as e:
        st.error("Run failed: %s: %s" % (type(e).__name__, e))
    st.session_state[_RES_KEY] = _rows
    st.session_state[_RUN_KEY] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
# @@END 008 RUN

# @@BLOCK 009 DASHBOARD deps=008
_rows = st.session_state.get(_RES_KEY) or []

if _rows:
    _b = _band_counts(_rows)
    _stamp = st.session_state.get(_RUN_KEY) or ""

    st.markdown("### 2. Result")
    st.caption("Checked %s. **%d** address(es)." % (_stamp, len(_rows)))

    _m = st.columns(5)
    _m[0].metric("\U0001f525 ACT", _b.get("ACT", 0),
                 help="A breach added inside 90 days, or a paste from the last year.")
    _m[1].metric("\u26a0 REVIEW", _b.get("REVIEW", 0),
                 help="A breach added inside a year.")
    _m[2].metric("\U0001f5c4 HISTORIC", _b.get("HISTORIC", 0),
                 help="Only old exposure. Rotate anyway, but nothing is urgent.")
    _m[3].metric("\u2705 CLEAN", _b.get("CLEAN", 0))
    _m[4].metric("\u2753 UNKNOWN", _b.get("UNKNOWN", 0))

    if _b.get("ACT"):
        st.error("**%d address(es) need action now.** The password is in an exposure "
                 "added recently - rotate it and anything reused from it."
                 % _b["ACT"])
    elif _b.get("REVIEW"):
        st.warning("**%d address(es) worth reviewing.** Nothing from the last 90 days, "
                   "but the exposure is under a year old." % _b["REVIEW"])

    _view = st.radio("Show", ["ACT", "REVIEW", "HISTORIC", "UNKNOWN", "CLEAN", "All"],
                     horizontal=True, key="_breach_view")
    _show = _rows if _view == "All" else [r for r in _rows
                                          if r.get("verdict") == _view]

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
                if r.get("error"):
                    st.caption("error: %s" % r["error"])
                if _bs:
                    st.markdown("**Breaches on this domain**")
                    for b in _bs[:25]:
                        _d = b.get("added_days", -1)
                        _age = "%d day(s) ago" % _d if _d >= 0 else "date unknown"
                        st.markdown("- **%s** - added %s, %s record(s), classes: %s"
                                    % (b.get("title") or b.get("name") or "?",
                                       _age, "{:,}".format(int(b.get("pwn") or 0)),
                                       ", ".join(b.get("classes") or []) or "-"))
                        if b.get("description"):
                            st.caption(b["description"][:300])
                else:
                    st.caption("No breach on this domain in the catalogue.")
                if _ps:
                    st.markdown("**Pastes quoting the address:** %d" % len(_ps))
                    for p in _ps[:10]:
                        st.caption("%s  %s" % (p.get("id") or "?", p.get("time") or ""))
                st.caption("checked %s" % (r.get("checked_at") or ""))

    st.markdown("### 3. Export")
    _d1, _d2 = st.columns(2)
    with _d1:
        st.download_button("\u2b07 Download CSV (all bands)",
                           data=_csv(_rows).encode("utf-8"),
                           file_name="breach_%s.csv"
                                     % datetime.now().strftime("%Y%m%d_%H%M%S"),
                           mime="text/csv", use_container_width=True)
    with _d2:
        _act = [r for r in _rows if r.get("verdict") == "ACT"]
        st.download_button("\u2b07 Download ACT addresses only",
                           data="\n".join(r.get("email") or "" for r in _act).encode(),
                           file_name="breach_act_%d.txt" % len(_act),
                           mime="text/plain", use_container_width=True,
                           disabled=not _act)
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
    st.caption("ACT %d · REVIEW %d · HISTORIC %d · CLEAN %d · UNKNOWN %d"
               % (_hc.get("ACT", 0), _hc.get("REVIEW", 0), _hc.get("HISTORIC", 0),
                  _hc.get("CLEAN", 0), _hc.get("UNKNOWN", 0)))
    st.dataframe(
        [{"checked": h.get("checked_at"), "verdict": h.get("verdict"),
          "email": h.get("email"), "breaches": len(h.get("breaches") or []),
          "pastes": len(h.get("pastes") or [])} for h in reversed(_hist[-100:])],
        use_container_width=True, height=260)
    if st.button("Clear my history"):
        _hist_clear()
        st.rerun()
# @@END 010 HISTORY

# @@BLOCK 011 FOOTER deps=010
st.markdown("---")
_n1, _n2, _n3 = st.columns(3)
with _n1:
    try:
        st.page_link("app.py", label="\u26a1 Checker", use_container_width=True)
    except Exception:
        st.caption("Checker lives at app.py")
with _n2:
    try:
        st.page_link("pages/3_Mailbox_Reader.py", label="\U0001f4e5 Reader",
                     use_container_width=True)
    except Exception:
        st.caption("Reader lives at pages/3_Mailbox_Reader.py")
with _n3:
    try:
        st.page_link("pages/4_Downloads.py", label="\U0001f4e6 Export Studio",
                     use_container_width=True)
    except Exception:
        st.caption("Export Studio lives at pages/4_Downloads.py")

st.caption("Sources: the free HIBP catalogue, the HIBP account page and psbdmp.ws. "
           "No API key, no per-address charge. A CLEAN verdict means not in those "
           "sources - not that the address was never exposed anywhere.")
# @@END 011 FOOTER
