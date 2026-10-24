# @@FILE status.py blocks=12 version=v13.40
# @@BLOCK 000 FILE_HEADER deps=-
"""
status.py - status vocabulary, classifier and label/colour metadata for the
Mega Ultimate Mail Checker.

SINGLE SOURCE OF TRUTH for turning a raw server/proxy string into a verdict.
app.py imports this module; if the import fails it falls back to the inline
classifier in app.py block 004 (STATUS_IMPORT_FALLBACK).

P0-3 ORDERING CONTRACT - DO NOT REORDER _ORDER:
    WRONG_STRONG  is evaluated BEFORE APP_PASSWORD and BEFORE RETRY_HARD.
    backend / upstream / downstream live in RETRY_HARD, NOT in RETRY.
    So 'NO [AUTHENTICATIONFAILED] ... OAUTH' resolves WRONG, not
    NEED_APP_PASSWORD, and auth rejections no longer resolve RETRY_LATER.

Every table is a tuple of lowercase substrings matched against normalise().
"""

from __future__ import annotations

import re

STATUS_VERSION = "v13.40"
STATUS_BUILD = 1340
# @@END 000


# @@BLOCK 001 STATUSES deps=000
STATUS_VALID = "VALID"
STATUS_WRONG = "WRONG"
STATUS_NEED_APP_PASSWORD = "NEED_APP_PASSWORD"
STATUS_RETRY_LATER = "RETRY_LATER"
STATUS_TIMEOUT = "TIMEOUT"
STATUS_SERVER_DROP = "SERVER_DROP"
STATUS_LOGIN_DROPPED = "LOGIN_DROPPED"
STATUS_PROXY_UNHEALTHY = "PROXY_UNHEALTHY"
STATUS_PROXY_BLOCKED = "PROXY_BLOCKED"
STATUS_CONNECTION_FAILED = "CONNECTION_FAILED"
STATUS_DNS_FAIL = "DNS_FAIL"
STATUS_RBL_BLOCKED = "RBL_BLOCKED"
STATUS_DISABLED = "DISABLED"
STATUS_LOCKED = "LOCKED"
STATUS_EXPIRED = "EXPIRED"
STATUS_ERROR = "ERROR"
STATUS_UNKNOWN = "UNKNOWN"

STATUSES = (
    STATUS_VALID,
    STATUS_WRONG,
    STATUS_NEED_APP_PASSWORD,
    STATUS_DISABLED,
    STATUS_LOCKED,
    STATUS_EXPIRED,
    STATUS_RETRY_LATER,
    STATUS_TIMEOUT,
    STATUS_LOGIN_DROPPED,
    STATUS_SERVER_DROP,
    STATUS_PROXY_UNHEALTHY,
    STATUS_PROXY_BLOCKED,
    STATUS_CONNECTION_FAILED,
    STATUS_DNS_FAIL,
    STATUS_RBL_BLOCKED,
    STATUS_ERROR,
    STATUS_UNKNOWN,
)

BUCKET_VALID = "valid"
BUCKET_WRONG = "wrong"
BUCKET_RETRY = "retry"
BUCKET_DROPPED = "dropped"
BUCKET_BLOCKED = "blocked"
BUCKET_DEAD = "dead"
BUCKET_UNKNOWN = "unknown"

BUCKETS = (
    BUCKET_VALID,
    BUCKET_WRONG,
    BUCKET_RETRY,
    BUCKET_DROPPED,
    BUCKET_BLOCKED,
    BUCKET_DEAD,
    BUCKET_UNKNOWN,
)

STATUS_BUCKET = {
    STATUS_VALID: BUCKET_VALID,
    STATUS_WRONG: BUCKET_WRONG,
    STATUS_NEED_APP_PASSWORD: BUCKET_WRONG,
    STATUS_DISABLED: BUCKET_WRONG,
    STATUS_LOCKED: BUCKET_WRONG,
    STATUS_EXPIRED: BUCKET_WRONG,
    STATUS_RETRY_LATER: BUCKET_RETRY,
    STATUS_TIMEOUT: BUCKET_RETRY,
    STATUS_LOGIN_DROPPED: BUCKET_DROPPED,
    STATUS_SERVER_DROP: BUCKET_DROPPED,
    STATUS_PROXY_UNHEALTHY: BUCKET_BLOCKED,
    STATUS_PROXY_BLOCKED: BUCKET_BLOCKED,
    STATUS_RBL_BLOCKED: BUCKET_BLOCKED,
    STATUS_CONNECTION_FAILED: BUCKET_DEAD,
    STATUS_DNS_FAIL: BUCKET_DEAD,
    STATUS_ERROR: BUCKET_UNKNOWN,
    STATUS_UNKNOWN: BUCKET_UNKNOWN,
}


def bucket_of(status):
    """Map any status token to its display bucket. Never raises."""
    return STATUS_BUCKET.get(status, BUCKET_UNKNOWN)
# @@END 001


# @@BLOCK 002 PRIORITY_LABELS_COLORS deps=001
PRIORITY_ORDER = (
    STATUS_VALID,
    STATUS_WRONG,
    STATUS_DISABLED,
    STATUS_LOCKED,
    STATUS_EXPIRED,
    STATUS_NEED_APP_PASSWORD,
    STATUS_RETRY_LATER,
    STATUS_TIMEOUT,
    STATUS_LOGIN_DROPPED,
    STATUS_SERVER_DROP,
    STATUS_PROXY_UNHEALTHY,
    STATUS_PROXY_BLOCKED,
    STATUS_RBL_BLOCKED,
    STATUS_CONNECTION_FAILED,
    STATUS_DNS_FAIL,
    STATUS_ERROR,
    STATUS_UNKNOWN,
)
PRIORITY = {s: i for i, s in enumerate(PRIORITY_ORDER)}

LABELS = {
    STATUS_VALID: "Valid",
    STATUS_WRONG: "Wrong password",
    STATUS_NEED_APP_PASSWORD: "Needs app password",
    STATUS_RETRY_LATER: "Retry later",
    STATUS_TIMEOUT: "Timeout",
    STATUS_SERVER_DROP: "Server dropped",
    STATUS_LOGIN_DROPPED: "Login dropped",
    STATUS_PROXY_UNHEALTHY: "Proxy unhealthy",
    STATUS_PROXY_BLOCKED: "Proxy blocked (407)",
    STATUS_CONNECTION_FAILED: "Connection failed",
    STATUS_DNS_FAIL: "DNS failure",
    STATUS_RBL_BLOCKED: "RBL blocked",
    STATUS_DISABLED: "Disabled",
    STATUS_LOCKED: "Locked",
    STATUS_EXPIRED: "Expired",
    STATUS_ERROR: "Error",
    STATUS_UNKNOWN: "Unknown",
}
DEFAULT_LABEL = "Unknown"

COLORS = {
    STATUS_VALID: "#22c55e",
    STATUS_WRONG: "#ef4444",
    STATUS_NEED_APP_PASSWORD: "#f59e0b",
    STATUS_RETRY_LATER: "#38bdf8",
    STATUS_TIMEOUT: "#0ea5e9",
    STATUS_SERVER_DROP: "#a855f7",
    STATUS_LOGIN_DROPPED: "#c084fc",
    STATUS_PROXY_UNHEALTHY: "#fb923c",
    STATUS_PROXY_BLOCKED: "#f97316",
    STATUS_CONNECTION_FAILED: "#64748b",
    STATUS_DNS_FAIL: "#94a3b8",
    STATUS_RBL_BLOCKED: "#eab308",
    STATUS_DISABLED: "#dc2626",
    STATUS_LOCKED: "#b91c1c",
    STATUS_EXPIRED: "#ea580c",
    STATUS_ERROR: "#6b7280",
    STATUS_UNKNOWN: "#8b93a7",
}
DEFAULT_COLOR = "#8b93a7"

# Bucket display metadata, kept here so pages never hardcode colours.
BUCKET_LABELS = {
    BUCKET_VALID: "Valid",
    BUCKET_WRONG: "Wrong",
    BUCKET_RETRY: "Retry",
    BUCKET_DROPPED: "Dropped",
    BUCKET_BLOCKED: "Blocked",
    BUCKET_DEAD: "Dead",
    BUCKET_UNKNOWN: "Unknown",
}
BUCKET_COLORS = {
    BUCKET_VALID: "#22c55e",
    BUCKET_WRONG: "#ef4444",
    BUCKET_RETRY: "#38bdf8",
    BUCKET_DROPPED: "#a855f7",
    BUCKET_BLOCKED: "#fb923c",
    BUCKET_DEAD: "#64748b",
    BUCKET_UNKNOWN: "#8b93a7",
}
# @@END 002


# @@BLOCK 003 MATCH_TABLES_APP_DNS deps=001
# Greedy app-password / modern-auth table. NOW EVALUATED AFTER WRONG_STRONG.
_APP_PASSWORD = (
    "application-specific password",
    "application specific password",
    "app-specific password",
    "app specific password",
    "app password",
    "application password",
    "oauth",
    "oauth2",
    "xoauth2",
    "sasl",
    "tenant",
    "consent",
    "admin approval",
    "mfa",
    "2fa",
    "two-factor",
    "two factor",
    "multi-factor",
    "multi factor",
    "modern authentication",
    "basic authentication is disabled",
    "basic auth is disabled",
    "less secure",
    "less-secure",
    "enable imap",
    "imap access",
    "web login required",
    "log in via your web browser",
    "unsupported authentication",
    "no supported authentication",
    "authmechanism",
)

_DNS = (
    "name or service not known",
    "nodename nor servname",
    "getaddrinfo failed",
    "temporary failure in name resolution",
    "no address associated with hostname",
    "name resolution",
    "socket.gaierror",
    "gaierror",
    "nxdomain",
    "servfail",
    "no such host",
    "dns lookup",
    "dns resolution",
    "dns error",
)
# @@END 003


# @@BLOCK 004 MATCH_TABLES_RETRY_SERVERDROP deps=001
# RETRY_HARD owns backend / upstream / downstream. These were pulled OUT of
# RETRY in v13.40 because they were swallowing real auth rejections.
_RETRY_HARD = (
    "backend",
    "upstream",
    "downstream",
    "try again later",
    "please try again",
    "temporarily",
    "temporary failure",
    "unavailable",
    "server busy",
    "server is busy",
    "too many",
    "rate limit",
    "ratelimit",
    "throttl",
    "overload",
    "congestion",
    "system error",
    "internal error",
    "service error",
    "maintenance",
)

# Soft / transport-level retry. Deliberately does NOT contain
# backend, upstream or downstream.
_RETRY = (
    "timeout",
    "timed out",
    "time out",
    "deadline exceeded",
    "deadline",
    "retry",
    "try again",
    "connection reset",
    "reset by peer",
    "broken pipe",
    "connection aborted",
    "premature",
    "incomplete",
    "bad greeting",
    "no greeting",
    "greeting",
    "handshake",
    "tls",
    "ssl",
)

# A post-LOGIN '* BYE' is the Windstream / mediacombb.net signature.
_SERVER_DROP = (
    "* bye",
    "bye",
    "server dropped",
    "dropped connection",
    "connection dropped",
    "server closed",
)

_SERVER_DROP_HARD = (
    "eof while reading",
    "eof occurred",
    "socket error: eof",
    "unexpected eof",
    "connection closed by remote",
    "remote host closed",
    "peer closed",
)
# @@END 004


# @@BLOCK 005 MATCH_TABLES_CONN_RBL_WRONG deps=001
_CONN = (
    "connection refused",
    "connect refused",
    "no route to host",
    "network is unreachable",
    "connect failed",
    "cannot connect",
    "failed to connect",
    "connection error",
    "unreachable",
    "host is down",
    "connection attempt failed",
    "oserror",
    "errno 111",
    "errno 113",
    "errno 101",
    "errno 110",
)

_RBL = (
    "blacklist",
    "blacklisted",
    "blocklist",
    "block list",
    "dnsbl",
    "rbl",
    "spamhaus",
    "spamcop",
    "barracuda",
    "sorbs",
    "spamrl",
    "listed at",
    "blocked by",
    "your ip",
    "ip blocked",
)

# Lower-confidence WRONG. Evaluated right after WRONG_STRONG so that
# 'mailbox unavailable' does not fall through to RETRY_HARD.
_WRONG_SOFT = (
    "no such user",
    "user unknown",
    "unknown user",
    "unknown username",
    "account not found",
    "mailbox not found",
    "mailbox unavailable",
    "user not found",
    "does not exist",
)

# THE definitive auth-rejection table. MUST be first in _ORDER.
_WRONG_STRONG = (
    "aadsts50126",
    "aadsts7000218",
    "aadsts50034",
    "aadsts50076",
    "authenticationfailed",
    "authentication failed",
    "authenticationfailure",
    "invalid credentials",
    "invalid credential",
    "invalid login",
    "invalid password",
    "invalid username or password",
    "username and password not accepted",
    "logon failure",
    "logon failed",
    "login incorrect",
    "login failed",
    "bad credentials",
    "wrong password",
    "password incorrect",
    "auth failed",
    "authorization failed",
    "not authenticated",
    "account is disabled",
    "account disabled",
    "user is locked",
    "account is locked",
    "account locked",
    "password expired",
    "5.7.8",
    "5.7.1",
    "535 ",
    "535-",
    "590 ",
)
# @@END 005


# @@BLOCK 006 MATCH_TABLES_BARE_PROXYLEVEL deps=001
_PROXY_LEVEL = (
    "407",
    "proxy authentication",
    "proxy auth",
    "proxyerror",
    "proxy error",
    "tunnel connection failed",
    "connect tunnel",
    "cannot connect to proxy",
    "bad gateway",
    "502",
    "503",
    "504",
    "gateway timeout",
    "quota",
    "bandwidth",
    "subuser",
    "sub-user",
    "no available",
    "all nodes busy",
)

_BARE = (
    "error",
    "failed",
    "failure",
    "denied",
    "invalid",
    "bad",
    "closed",
    "aborted",
    "dropped",
)

# ---------------------------------------------------------------------------
# EVALUATION ORDER. Index 0 wins. WRONG_STRONG is deliberately first.
# ---------------------------------------------------------------------------
_ORDER = (
    ("WRONG_STRONG", _WRONG_STRONG, STATUS_WRONG),
    ("WRONG_SOFT", _WRONG_SOFT, STATUS_WRONG),
    ("SERVER_DROP", _SERVER_DROP, STATUS_LOGIN_DROPPED),
    ("SERVER_DROP_HARD", _SERVER_DROP_HARD, STATUS_SERVER_DROP),
    ("APP_PASSWORD", _APP_PASSWORD, STATUS_NEED_APP_PASSWORD),
    ("DNS", _DNS, STATUS_DNS_FAIL),
    ("RBL", _RBL, STATUS_RBL_BLOCKED),
    ("CONN", _CONN, STATUS_CONNECTION_FAILED),
    ("PROXY_LEVEL", _PROXY_LEVEL, STATUS_PROXY_UNHEALTHY),
    ("RETRY_HARD", _RETRY_HARD, STATUS_RETRY_LATER),
    ("RETRY", _RETRY, STATUS_RETRY_LATER),
    ("BARE", _BARE, STATUS_ERROR),
)

TABLES = {name: (table, status) for name, table, status in _ORDER}
TABLE_NAMES = tuple(name for name, _t, _s in _ORDER)
# @@END 006


# @@BLOCK 007 NORMALISE_HELPERS deps=006
_WS_RE = re.compile(r"\s+")


def normalise(text):
    """Lowercase, collapse whitespace, decode bytes. Never raises."""
    if text is None:
        return ""
    if isinstance(text, (bytes, bytearray)):
        try:
            text = bytes(text).decode("utf-8", "replace")
        except Exception:
            text = repr(text)
    try:
        s = str(text)
    except Exception:
        return ""
    s = s.replace("\r", " ").replace("\n", " ").replace("\t", " ")
    s = _WS_RE.sub(" ", s)
    return s.strip().lower()


def first_match(haystack, table):
    """First needle from table present in haystack, else None."""
    for needle in table:
        if needle in haystack:
            return needle
    return None


def hits(haystack, table):
    """Every needle from table present in haystack, in table order."""
    return [n for n in table if n in haystack]
# @@END 007


# @@BLOCK 008 CLASSIFIER deps=007
def classify_detail(text, default=STATUS_UNKNOWN):
    """Return (status, table_name, needle) for the first matching table."""
    s = normalise(text)
    if not s:
        return default, "EMPTY", None
    for name, table, status in _ORDER:
        needle = first_match(s, table)
        if needle is not None:
            return status, name, needle
    return default, "DEFAULT", None


def classify_error(text, default=STATUS_UNKNOWN):
    """Map a raw server/proxy/exception string to a status token."""
    return classify_detail(text, default)[0]


def explain(text, default=STATUS_UNKNOWN):
    """Human string describing why text classified the way it did."""
    status, table, needle = classify_detail(text, default)
    if needle is None:
        return "%s (no table matched, default)" % status
    return "%s (table=%s, needle=%r)" % (status, table, needle)
# @@END 008


# @@BLOCK 009 SIGNAL_HELPERS deps=008
def is_valid(status):
    return status == STATUS_VALID


def is_wrong(status):
    return bucket_of(status) == BUCKET_WRONG


def is_retry(status):
    return bucket_of(status) in (BUCKET_RETRY, BUCKET_DROPPED)


def is_drop(status):
    return bucket_of(status) == BUCKET_DROPPED


def is_blocked(status):
    return bucket_of(status) == BUCKET_BLOCKED


def is_dead(status):
    return bucket_of(status) == BUCKET_DEAD


def is_definitive(status):
    """True when no amount of retrying should change the verdict."""
    return status in (
        STATUS_VALID,
        STATUS_WRONG,
        STATUS_DISABLED,
        STATUS_LOCKED,
        STATUS_EXPIRED,
    )


def worst_of(statuses):
    """Lowest-priority-number status wins. Empty input -> UNKNOWN."""
    best = None
    best_rank = None
    for s in statuses:
        rank = PRIORITY.get(s)
        if rank is None:
            continue
        if best_rank is None or rank < best_rank:
            best, best_rank = s, rank
    return best or STATUS_UNKNOWN


def summarise(statuses):
    """Counter dict of status -> count, plus a 'total' key."""
    out = {}
    for s in statuses:
        out[s] = out.get(s, 0) + 1
    out["total"] = len(list(statuses))
    return out


def completion_status(statuses, ran=True):
    """Coarse run outcome used by the app footer."""
    seq = list(statuses)
    if not ran:
        return "not_run"
    if not seq:
        return "no_accounts"
    if any(is_valid(s) for s in seq):
        return "completed"
    if all(is_definitive(s) or is_dead(s) for s in seq):
        return "completed_no_valid"
    return "partial"
# @@END 009


# @@BLOCK 010 SMALL_HELPERS deps=002
def label_for(status):
    return LABELS.get(status, DEFAULT_LABEL)


def color_for(status):
    return COLORS.get(status, DEFAULT_COLOR)


def priority_for(status):
    return PRIORITY.get(status, len(PRIORITY_ORDER))


def bucket_label(bucket):
    return BUCKET_LABELS.get(bucket, str(bucket).title())


def bucket_color(bucket):
    return BUCKET_COLORS.get(bucket, DEFAULT_COLOR)


def badge(status):
    """Tiny HTML pill for a status token."""
    return (
        '<span style="display:inline-block;padding:1px 7px;border-radius:999px;'
        'font-size:11px;font-weight:600;color:#0b0f19;background:%s;">%s</span>'
        % (color_for(status), label_for(status))
    )
# @@END 010


# @@BLOCK 011 FOOTER deps=010
def selftest():
    """Ordering assertions. Returns list of (name, ok, detail)."""
    cases = (
        ("auth_plus_oauth_is_wrong",
         "NO [AUTHENTICATIONFAILED] Invalid credentials (Failure) OAUTH",
         STATUS_WRONG),
        ("aadsts_is_wrong",
         "AADSTS50126: Error validating credentials",
         STATUS_WRONG),
        ("backend_is_not_retry_for_auth",
         "NO [AUTHENTICATIONFAILED] backend said no",
         STATUS_WRONG),
        ("app_password_still_works",
         "Application-specific password required",
         STATUS_NEED_APP_PASSWORD),
        ("upstream_alone_is_retry",
         "upstream temporarily unavailable",
         STATUS_RETRY_LATER),
        ("bye_is_login_dropped",
         "* BYE Windstream closing connection",
         STATUS_LOGIN_DROPPED),
        ("eof_is_server_drop",
         "socket error: EOF while reading",
         STATUS_SERVER_DROP),
        ("dns_is_dns",
         "getaddrinfo failed for imap.example.net",
         STATUS_DNS_FAIL),
        ("407_is_proxy",
         "CONNECT tunnel failed: 407 Proxy Authentication Required",
         STATUS_PROXY_UNHEALTHY),
        ("rbl_is_rbl",
         "Your IP is blacklisted by Spamhaus",
         STATUS_RBL_BLOCKED),
        ("empty_is_default",
         "",
         STATUS_UNKNOWN),
    )
    out = []
    for name, text, want in cases:
        got = classify_error(text)
        out.append((name, got == want, "want=%s got=%s" % (want, got)))
    return out


__all__ = (
    "STATUS_VERSION",
    "STATUS_BUILD",
    "STATUSES",
    "BUCKETS",
    "STATUS_BUCKET",
    "PRIORITY",
    "LABELS",
    "COLORS",
    "BUCKET_LABELS",
    "BUCKET_COLORS",
    "TABLES",
    "TABLE_NAMES",
    "normalise",
    "classify_error",
    "classify_detail",
    "explain",
    "bucket_of",
    "is_valid",
    "is_wrong",
    "is_retry",
    "is_drop",
    "is_blocked",
    "is_dead",
    "is_definitive",
    "worst_of",
    "summarise",
    "completion_status",
    "label_for",
    "color_for",
    "priority_for",
    "bucket_label",
    "bucket_color",
    "badge",
    "selftest",
)
# @@END 011
