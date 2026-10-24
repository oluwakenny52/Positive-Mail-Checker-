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
