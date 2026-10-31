# @@FILE status.py blocks=13 version=v13.47
# ===========================================================================
# status.py - canonical mail-verdict taxonomy, classifier and presentation.
#
# Invariants
#   * Import-clean: stdlib only. No Streamlit, no network, no side effects.
#   * classify_error(text, domain="", default=UNKNOWN) - `domain` is the
#     SECOND POSITIONAL parameter, so app.py block 067's
#     st_classify(err_str, domain) binds the domain to `domain` instead of
#     silently overwriting the default.
#   * Precedence is MOST DECISIVE FIRST. _RETRY_HARD owns
#     "too many" / "limit" / "temporar*" / "simultaneous", so
#     "* BYE Too many simultaneous connections" resolves to RETRY_LATER and
#     never LOGIN_DROPPED. _RETRY deliberately excludes
#     backend/upstream/downstream so those transient-server words fall through
#     to RETRY_LATER as well.
#   * Short aliases (VALID, WRONG, ...) live in block 011 ALIASES. Block 012
#     APP_COMPAT adds the STATUS_* and function spellings app.py and the pages
#     still reach for. Both exist for app.py block 004's `from status import`.
# ===========================================================================


# @@BLOCK 000 HEADER
"""Canonical verdict taxonomy for the mail checker.

Single source of truth for every verdict token the app uses. app.py imports
the short aliases from here; if that import ever fails the app falls back to
an inline copy of the same tables, so the two must stay in lockstep.
"""

import re

STATUS_VERSION = "v13.42"
STATUS_MODULE = "status"
STATUS_BLOCKS = 13
# @@END 000 HEADER


# @@BLOCK 001 CONSTANTS
STATUS_VALID = "VALID"
STATUS_WRONG = "WRONG"
STATUS_WRONG_PASSWORD = "WRONG_PASSWORD"
STATUS_APP = "APP"
STATUS_NEED_APP_PASSWORD = "NEED_APP_PASSWORD"
STATUS_FAILED = "FAILED"
STATUS_CONNECTION_FAILED = "CONNECTION_FAILED"
STATUS_PROXY_UNHEALTHY = "PROXY_UNHEALTHY"
STATUS_SKIP = "SKIP"
STATUS_SKIPPED_COOLDOWN = "SKIPPED_COOLDOWN"
STATUS_UNKNOWN = "UNKNOWN"
STATUS_RETRY = "RETRY"
STATUS_RETRY_LATER = "RETRY_LATER"
STATUS_RBL = "RBL"
STATUS_RBL_BLOCKED = "RBL_BLOCKED"
STATUS_SMTP_FAILED = "SMTP_FAILED"
STATUS_DNS_FAILED = "DNS_FAILED"
STATUS_LOGIN_DROPPED = "LOGIN_DROPPED"
# @@END 001 CONSTANTS


# @@BLOCK 002 GROUPS
STATUS_ALL_STATUSES = (
    STATUS_VALID,
    STATUS_WRONG,
    STATUS_WRONG_PASSWORD,
    STATUS_APP,
    STATUS_NEED_APP_PASSWORD,
    STATUS_FAILED,
    STATUS_CONNECTION_FAILED,
    STATUS_PROXY_UNHEALTHY,
    STATUS_SKIP,
    STATUS_SKIPPED_COOLDOWN,
    STATUS_UNKNOWN,
    STATUS_RETRY,
    STATUS_RETRY_LATER,
    STATUS_RBL,
    STATUS_RBL_BLOCKED,
    STATUS_SMTP_FAILED,
    STATUS_DNS_FAILED,
    STATUS_LOGIN_DROPPED,
)

WRONG_STATUSES = frozenset({STATUS_WRONG, STATUS_WRONG_PASSWORD})
APP_STATUSES = frozenset({STATUS_APP, STATUS_NEED_APP_PASSWORD})
VALID_STATUSES = frozenset({STATUS_VALID})
RBL_STATUSES = frozenset({STATUS_RBL, STATUS_RBL_BLOCKED})

# Transient: worth another rung or another pass.
RETRY_STATUSES = frozenset(
    {
        STATUS_UNKNOWN,
        STATUS_RETRY,
        STATUS_RETRY_LATER,
        STATUS_SKIPPED_COOLDOWN,
        STATUS_LOGIN_DROPPED,
    }
)

# Transport-level: the rung never got a protocol answer.
CONN_STATUSES = frozenset(
    {
        STATUS_FAILED,
        STATUS_CONNECTION_FAILED,
        STATUS_SMTP_FAILED,
        STATUS_DNS_FAILED,
        STATUS_PROXY_UNHEALTHY,
    }
)

# The proxy itself is the suspect, not the target host.
PROXY_LEVEL_STATUSES = frozenset(
    {
        STATUS_PROXY_UNHEALTHY,
        STATUS_CONNECTION_FAILED,
        STATUS_DNS_FAILED,
    }
)

# Answer is final; do not spend another rung on it.
TERMINAL_STATUSES = frozenset(
    {
        STATUS_VALID,
        STATUS_WRONG,
        STATUS_WRONG_PASSWORD,
        STATUS_APP,
        STATUS_RBL,
        STATUS_RBL_BLOCKED,
    }
)

DECISIVE_STATUSES = frozenset(
    set(WRONG_STATUSES) | set(APP_STATUSES) | set(RBL_STATUSES) | set(VALID_STATUSES)
)
# @@END 002 GROUPS


# @@BLOCK 003 LABELS
LABELS = {
    STATUS_VALID: "Valid",
    STATUS_WRONG: "Wrong",
    STATUS_WRONG_PASSWORD: "Wrong password",
    STATUS_APP: "App password / OAuth",
    STATUS_NEED_APP_PASSWORD: "Needs app password",
    STATUS_FAILED: "Failed",
    STATUS_CONNECTION_FAILED: "Connection failed",
    STATUS_PROXY_UNHEALTHY: "Proxy unhealthy",
    STATUS_SKIP: "Skip",
    STATUS_SKIPPED_COOLDOWN: "Skipped (cooldown)",
    STATUS_UNKNOWN: "Unknown",
    STATUS_RETRY: "Retry",
    STATUS_RETRY_LATER: "Retry later",
    STATUS_RBL: "RBL listed",
    STATUS_RBL_BLOCKED: "RBL blocked",
    STATUS_SMTP_FAILED: "SMTP failed",
    STATUS_DNS_FAILED: "DNS failed",
    STATUS_LOGIN_DROPPED: "Login dropped",
}
# @@END 003 LABELS


# @@BLOCK 004 COLORS
COLORS = {
    STATUS_VALID: "#22c55e",
    STATUS_WRONG: "#ef4444",
    STATUS_WRONG_PASSWORD: "#f97316",
    STATUS_APP: "#eab308",
    STATUS_NEED_APP_PASSWORD: "#f59e0b",
    STATUS_FAILED: "#ef4444",
    STATUS_CONNECTION_FAILED: "#64748b",
    STATUS_PROXY_UNHEALTHY: "#8b5cf6",
    STATUS_SKIP: "#94a3b8",
    STATUS_SKIPPED_COOLDOWN: "#94a3b8",
    STATUS_UNKNOWN: "#94a3b8",
    STATUS_RETRY: "#38bdf8",
    STATUS_RETRY_LATER: "#0ea5e9",
    STATUS_RBL: "#a855f7",
    STATUS_RBL_BLOCKED: "#7c3aed",
    STATUS_SMTP_FAILED: "#f43f5e",
    STATUS_DNS_FAILED: "#06b6d4",
    STATUS_LOGIN_DROPPED: "#fb923c",
}

ICONS = {
    STATUS_VALID: "OK",
    STATUS_WRONG: "X",
    STATUS_WRONG_PASSWORD: "X",
    STATUS_APP: "A",
    STATUS_NEED_APP_PASSWORD: "A",
    STATUS_FAILED: "!",
    STATUS_CONNECTION_FAILED: "!",
    STATUS_PROXY_UNHEALTHY: "P",
    STATUS_SKIP: "-",
    STATUS_SKIPPED_COOLDOWN: "-",
    STATUS_UNKNOWN: "?",
    STATUS_RETRY: "R",
    STATUS_RETRY_LATER: "R",
    STATUS_RBL: "B",
    STATUS_RBL_BLOCKED: "B",
    STATUS_SMTP_FAILED: "S",
    STATUS_DNS_FAILED: "D",
    STATUS_LOGIN_DROPPED: "D",
}
# @@END 004 COLORS


# @@BLOCK 005 PRIORITY
# Decisiveness, high wins. Used by pick_verdict() / merge_result() when two
# rungs disagree: a hard WRONG outranks a VALID, a VALID outranks anything
# transient.
PRIORITY = {
    STATUS_SKIP: 5,
    STATUS_SKIPPED_COOLDOWN: 5,
    STATUS_UNKNOWN: 10,
    STATUS_RETRY: 20,
    STATUS_RETRY_LATER: 30,
    STATUS_PROXY_UNHEALTHY: 35,
    STATUS_FAILED: 40,
    STATUS_CONNECTION_FAILED: 45,
    STATUS_SMTP_FAILED: 50,
    STATUS_DNS_FAILED: 55,
    STATUS_LOGIN_DROPPED: 60,
    STATUS_VALID: 70,
    STATUS_NEED_APP_PASSWORD: 75,
    STATUS_RBL: 80,
    STATUS_APP: 85,
    STATUS_WRONG_PASSWORD: 90,
    STATUS_RBL_BLOCKED: 95,
    STATUS_WRONG: 100,
}

# Where several statuses are pooled into one bucket label.
BUCKET_OF = {
    STATUS_VALID: "valid",
    STATUS_WRONG: "wrong",
    STATUS_WRONG_PASSWORD: "wrong",
    STATUS_APP: "app",
    STATUS_NEED_APP_PASSWORD: "app",
    STATUS_RBL: "rbl",
    STATUS_RBL_BLOCKED: "rbl",
    STATUS_FAILED: "conn",
    STATUS_CONNECTION_FAILED: "conn",
    STATUS_SMTP_FAILED: "conn",
    STATUS_DNS_FAILED: "conn",
    STATUS_PROXY_UNHEALTHY: "conn",
    STATUS_LOGIN_DROPPED: "retry",
    STATUS_RETRY: "retry",
    STATUS_RETRY_LATER: "retry",
    STATUS_UNKNOWN: "retry",
    STATUS_SKIP: "skip",
    STATUS_SKIPPED_COOLDOWN: "skip",
}
# @@END 005 PRIORITY


# @@BLOCK 006 PATTERNS
# Order matters: classify_error() walks these top to bottom.
_WRONG_STRONG = re.compile(
    r"authenticationfailed|authentication failed|invalid credentials|"
    r"invalid username or password|invalid user name or password|invalid login|"
    r"invalid login or password|bad credentials|loginfailed|login failed|"
    r"auth(?:entication)? failed|authenticate error|realmless(?: login)? not allowed|"
    r"login incorrect|wrong password|password incorrect|incorrect password|"
    r"credentials invalid",
    re.I,
)
_WRONG_USER = re.compile(
    r"user unknown|no such user|unknown user|invalid user|user not found|"
    r"mailbox not found|no such mailbox|does not exist|account not found|"
    r"no mailbox|recipient address rejected|unknown account",
    re.I,
)
_APP = re.compile(
    r"application[- ]specific password|app[- ]specific password|app password|"
    r"needs app password|application password|xoauth2|ms_oauth|oauth|"
    r"basic authentication (?:is )?disabled|"
    r"log in via your web browser|web browser to log in",
    re.I,
)
# v13.50: rbl is BOUNDED. As a bare substring it fired inside unrelated words,
# and abusix / ip blocked (both in the app.py fallback table) were missing, so a
# real RBL answer fell through to UNKNOWN.
_RBL = re.compile(
    r"blacklist|blacklisted|blocklist|blocklisted|spamhaus|spam block|"
    r"blocked by|dnsbl|abusix|\brbl\b|listed at|listed in|reputation|ip blocked",
    re.I,
)
# v13.50: dns is BOUNDED and gaierror / does not resolve / failed to resolve /
# could not resolve / unable to resolve are added - every one of them exists in
# the app.py block 004 fallback table, and the two are required to stay in
# lockstep. A bare `resolution` made "high resolution image" a DNS failure.
_DNS = re.compile(
    r"name or service not known|nodename nor servname|no address associated|"
    r"temporary failure in name resolution|getaddrinfo|gaierror|"
    r"no such host|host not found|servfail|nxdomain|"
    r"\bdns\b|dnsbl|dns lookup|dns resolution|dns query|"
    r"does not resolve|failed to resolve|could not resolve|unable to resolve|"
    r"name resolution (?:failed|error)|resolution failed|resolution error",
    re.I,
)
_RETRY_HARD = re.compile(
    r"too many|rate ?limit|throttl|limit exceeded|quota exceeded|over quota|"
    r"try again later|temporar|service unavailable|server busy|too busy|"
    r"maintenance|simultaneous|resource temporarily unavailable",
    re.I,
)
_LOGIN_DROP = re.compile(
    r"\bbye\b|connection closed|closed by server|server disconnected|"
    r"terminating connection|server terminating|imap server terminating|"
    r"auth process broken|dropped connection|imap4rev1 server dropping",
    re.I,
)
_CONN_STRONG = re.compile(
    r"connection refused|timed out|timeout|no route to host|"
    r"network is unreachable|connection error|ssl|certificate|tls|handshake|"
    r"wrong version number|hostname mismatch",
    re.I,
)
# Transient-server words. backend/upstream/downstream are INCLUDED: with them
# excluded, a bare "backend error" matched nothing and fell through to UNKNOWN.
_RETRY = re.compile(
    r"unavailable|server error|internal error|greeting|busy|try again|"
    r"not ready|come back later|backend|upstream|downstream",
    re.I,
)
_CONN = re.compile(
    r"connect|socket|network|reset|eof|pipe|timeout|refused|unreachable|"
    r"proxy",
    re.I,
)

# "blocked by" is claimed by _RBL, so a proxy refusal was filed as RBL. This
# runs before _RBL and owns only the proxy spelling.
# v13.50: a proxy-side DNS/lookup failure is also the PROXY hop, not the
# mailbox, so it belongs here rather than in _DNS.
_PROXY_BLOCKED = re.compile(
    r"blocked by (?:the )?proxy|proxy (?:is )?blocked|proxy denied|"
    r"proxy (?:dns|lookup|resolve)",
    re.I,
)

# Rate-limit guard for the LOGIN_DROPPED decision.
_RATE_LIMIT = re.compile(r"too many|rate ?limit|throttl|simultaneous|limit", re.I)

# Domains that habitually answer "needs an app password".
_APP_HINT_DOMAINS = frozenset(
    {
        "outlook.com",
        "hotmail.com",
        "hotmail.co.uk",
        "live.com",
        "live.co.uk",
        "msn.com",
        "gmail.com",
        "googlemail.com",
        "yahoo.com",
        "aol.com",
        "icloud.com",
        "me.com",
        "mac.com",
    }
)
# @@END 006 PATTERNS


# @@BLOCK 007 CLASSIFY
def classify_error(text, domain="", default=STATUS_UNKNOWN):
    """Map raw server/proxy text onto a canonical status token.

    `domain` is positional (2nd) so app.py's st_classify(err, domain) binds it
    correctly. `default` is returned when nothing matches.
    """
    t = "" if text is None else str(text).strip()
    if not t:
        return default

    low = t.lower()

    if _WRONG_STRONG.search(low):
        return STATUS_WRONG_PASSWORD
    if _WRONG_USER.search(low):
        return STATUS_WRONG
    if _APP.search(low):
        d = (domain or "").split("@")[-1].strip().lower()
        if d in _APP_HINT_DOMAINS or "app" in low:
            return STATUS_NEED_APP_PASSWORD
        return STATUS_APP
    if _PROXY_BLOCKED.search(low):
        return STATUS_CONNECTION_FAILED
    if _RBL.search(low):
        if "blocked" in low:
            return STATUS_RBL_BLOCKED
        return STATUS_RBL
    if _DNS.search(low):
        return STATUS_DNS_FAILED
    if _RETRY_HARD.search(low):
        return STATUS_RETRY_LATER
    if _LOGIN_DROP.search(low):
        if _RATE_LIMIT.search(low):
            return STATUS_RETRY_LATER
        return STATUS_LOGIN_DROPPED
    if _CONN_STRONG.search(low):
        return STATUS_CONNECTION_FAILED
    if _RETRY.search(low):
        return STATUS_RETRY_LATER
    if _CONN.search(low):
        return STATUS_CONNECTION_FAILED
    return default


def classify_exception(exc, domain="", default=STATUS_UNKNOWN):
    """classify_error() over an exception, using class name when useful."""
    if exc is None:
        return default
    parts = []
    name = type(exc).__name__
    if name and name != "Exception":
        parts.append(name)
    try:
        parts.append(str(exc))
    except Exception:
        pass
    return classify_error(" ".join(p for p in parts if p), domain=domain, default=default)
# @@END 007 CLASSIFY


# @@BLOCK 008 HELPERS
def normalise(value):
    """Coerce anything (legacy token, STATUS_* spelling, case variant) to a
    canonical status. Unknown input becomes STATUS_UNKNOWN."""
    if value is None:
        return STATUS_UNKNOWN
    v = str(value).strip().upper().replace("-", "_").replace(" ", "_")
    if v in PRIORITY:
        return v
    if v.startswith("STATUS_") and v[7:] in PRIORITY:
        return v[7:]
    legacy = {
        "OK": STATUS_VALID,
        "PASS": STATUS_VALID,
        "GOOD": STATUS_VALID,
        "BAD": STATUS_WRONG,
        "WRONGPASSWORD": STATUS_WRONG_PASSWORD,
        "WRONG_PASS": STATUS_WRONG_PASSWORD,
        "APPPASSWORD": STATUS_APP,
        "APP_PASSWORD": STATUS_APP,
        "NEEDSAPPPASSWORD": STATUS_NEED_APP_PASSWORD,
        "CONNFAILED": STATUS_CONNECTION_FAILED,
        "CONNECT_FAILED": STATUS_CONNECTION_FAILED,
        "PROXYFAIL": STATUS_PROXY_UNHEALTHY,
        "PROXY_FAILED": STATUS_PROXY_UNHEALTHY,
        "COOLDOWN": STATUS_SKIPPED_COOLDOWN,
        "RETRYABLE": STATUS_RETRY,
        "DNSFAILED": STATUS_DNS_FAILED,
        "RBLBLOCKED": STATUS_RBL_BLOCKED,
        "SMTPFAILED": STATUS_SMTP_FAILED,
        "LOGINDROPPED": STATUS_LOGIN_DROPPED,
    }
    return legacy.get(v, STATUS_UNKNOWN)


def display(code, default=None):
    """Human label for a status."""
    c = normalise(code)
    if c == STATUS_UNKNOWN and default is not None:
        return default
    return LABELS.get(c, str(code))


def color(code, default="#94a3b8"):
    """Hex colour for a status."""
    return COLORS.get(normalise(code), default)


def icon(code, default="-"):
    return ICONS.get(normalise(code), default)


def priority_of(code):
    return PRIORITY.get(normalise(code), 10)


def worse_of(*codes):
    """Return the most decisive status among `codes`.

    Starts from None, not UNKNOWN: SKIP ranks 5 and UNKNOWN 10, so seeding with
    UNKNOWN made worse_of([SKIP]) answer UNKNOWN.
    """
    best = None
    for c in codes:
        if c is None:
            continue
        n = normalise(c)
        if best is None or PRIORITY.get(n, 0) > PRIORITY.get(best, 0):
            best = n
    return best if best is not None else STATUS_UNKNOWN


def better_of(*codes):
    return worse_of(*codes)


def is_valid(code):
    return normalise(code) in VALID_STATUSES


def is_wrong(code):
    return normalise(code) in WRONG_STATUSES


def is_app(code):
    return normalise(code) in APP_STATUSES


def is_rbl(code):
    return normalise(code) in RBL_STATUSES


def is_retryable(code):
    return normalise(code) in RETRY_STATUSES


def is_terminal(code):
    return normalise(code) in TERMINAL_STATUSES


def is_proxy_level_error(code):
    """True when the proxy/transport is the suspect, not the target host."""
    if code is None:
        return False
    if isinstance(code, BaseException):
        return classify_exception(code) in PROXY_LEVEL_STATUSES
    return normalise(code) in PROXY_LEVEL_STATUSES


def bucket_of(code):
    return BUCKET_OF.get(normalise(code), "other")
# @@END 008 HELPERS


# @@BLOCK 009 SUMMARY
def tally(results):
    """Count an iterable of statuses (or objects with .status) per bucket."""
    out = {
        "valid": 0,
        "wrong": 0,
        "app": 0,
        "rbl": 0,
        "conn": 0,
        "retry": 0,
        "skip": 0,
        "other": 0,
        "total": 0,
    }
    for item in results or ():
        st = getattr(item, "status", item)
        out[bucket_of(st)] += 1
        out["total"] += 1
    return out


def worst_of(results):
    """Most decisive status in an iterable."""
    return worse_of(*[getattr(r, "status", r) for r in (results or ())])
# @@END 009 SUMMARY


# @@BLOCK 010 SELFTEST
def alias_selftest(verbose=False):
    """Assert the taxonomy is internally consistent. Returns True or raises."""
    checks = []

    for st in STATUS_ALL_STATUSES:
        checks.append((f"label:{st}", st in LABELS))
        checks.append((f"color:{st}", st in COLORS))
        checks.append((f"priority:{st}", st in PRIORITY))
        checks.append((f"bucket:{st}", st in BUCKET_OF))
        checks.append((f"normalise:{st}", normalise(st) == st))

    checks.append(("classify:wrong", classify_error("NO [AUTHENTICATIONFAILED] Invalid credentials") == STATUS_WRONG_PASSWORD))
    checks.append(("classify:wrong_user", classify_error("550 5.1.1 User unknown") == STATUS_WRONG))
    checks.append(("classify:ratelimit", classify_error("* BYE Too many simultaneous connections") == STATUS_RETRY_LATER))
    checks.append(("classify:transient", classify_error("upstream temporarily unavailable") == STATUS_RETRY_LATER))
    checks.append(("classify:backend", classify_error("backend error") == STATUS_RETRY_LATER))
    checks.append(("classify:upstream", classify_error("upstream error") == STATUS_RETRY_LATER))
    checks.append(("classify:proxy_blocked",
                   classify_error("Connection blocked by proxy") == STATUS_CONNECTION_FAILED))
    checks.append(("classify:spamhaus_still_rbl",
                   classify_error("blocked by Spamhaus") == STATUS_RBL_BLOCKED))
    checks.append(("classify:conn", classify_error("Connection refused") == STATUS_CONNECTION_FAILED))
    checks.append(("classify:dns", classify_error("Name or service not known") == STATUS_DNS_FAILED))
    checks.append(("classify:drop", classify_error("* BYE server dropping connection") == STATUS_LOGIN_DROPPED))
    checks.append(("classify:drop_terminating", classify_error("command: LOGIN => IMAP server terminating connection") == STATUS_LOGIN_DROPPED))
    checks.append(("classify:reset_is_conn", classify_error("connection reset by peer") == STATUS_CONNECTION_FAILED))
    checks.append(("classify:407_is_conn", classify_error("Socket error: 407: Proxy Authentication Required") == STATUS_CONNECTION_FAILED))
    checks.append(("classify:empty", classify_error("") == STATUS_UNKNOWN))
    checks.append(("classify:domain_bind", classify_error("needs app password", "gmail.com") == STATUS_NEED_APP_PASSWORD))
    # ---- v13.50: the five misclassifications the bounded tokens fix ----
    checks.append(("classify:realmless",
                   classify_error("realmless login not allowed") == STATUS_WRONG_PASSWORD))
    checks.append(("classify:gaierror",
                   classify_error("socket.gaierror: [Errno -2] Name or service not known")
                   == STATUS_DNS_FAILED))
    checks.append(("classify:proxy_dns",
                   classify_error("Proxy DNS lookup failed") == STATUS_CONNECTION_FAILED))
    checks.append(("classify:bare_resolution_is_not_dns",
                   classify_error("high resolution image attached") == STATUS_UNKNOWN))
    checks.append(("classify:ip_blocked_is_rbl",
                   classify_error("IP blocked by provider") == STATUS_RBL_BLOCKED))
    checks.append(("proxy_level", is_proxy_level_error(STATUS_DNS_FAILED) is True))
    checks.append(("priority_order", PRIORITY[STATUS_WRONG] > PRIORITY[STATUS_VALID] > PRIORITY[STATUS_RETRY_LATER]))
    checks.append(("worse_of:skip", worse_of(STATUS_SKIP) == STATUS_SKIP))
    checks.append(("worse_of", worse_of(STATUS_VALID, STATUS_WRONG) == STATUS_WRONG))
    checks.append(("tally", tally([STATUS_VALID, STATUS_WRONG])["total"] == 2))

    bad = [name for name, ok in checks if not ok]
    if bad:
        raise AssertionError("status alias_selftest failed: " + ", ".join(bad))
    if verbose:
        print("status.py alias_selftest: %d checks OK" % len(checks))
    return True
# @@END 010 SELFTEST


# @@BLOCK 011 ALIASES
VALID = STATUS_VALID
WRONG = STATUS_WRONG
WRONG_PASSWORD = STATUS_WRONG_PASSWORD
APP = STATUS_APP
NEED_APP_PASSWORD = STATUS_NEED_APP_PASSWORD
FAILED = STATUS_FAILED
CONNECTION_FAILED = STATUS_CONNECTION_FAILED
PROXY_UNHEALTHY = STATUS_PROXY_UNHEALTHY
SKIP = STATUS_SKIP
SKIPPED_COOLDOWN = STATUS_SKIPPED_COOLDOWN
UNKNOWN = STATUS_UNKNOWN
RETRY = STATUS_RETRY
RETRY_LATER = STATUS_RETRY_LATER
RBL = STATUS_RBL
RBL_BLOCKED = STATUS_RBL_BLOCKED
SMTP_FAILED = STATUS_SMTP_FAILED
DNS_FAILED = STATUS_DNS_FAILED
LOGIN_DROPPED = STATUS_LOGIN_DROPPED

ALL_STATUSES = STATUS_ALL_STATUSES

# Convenience groups app.py uses for rung gating.
WRONG_SET = WRONG_STATUSES
APP_SET = APP_STATUSES
RETRY_SET = RETRY_STATUSES
CONN_SET = CONN_STATUSES
PROXY_LEVEL_SET = PROXY_LEVEL_STATUSES
TERMINAL_SET = TERMINAL_STATUSES
# @@END 011 ALIASES


# @@BLOCK 012 APP_COMPAT
# Names app.py and the pages reach for under older spellings. Every one is an
# identity alias onto the canonical constant, so `is` comparisons hold.
STATUS_OK = STATUS_VALID
STATUS_BAD = STATUS_WRONG
STATUS_WRONG_PASS = STATUS_WRONG_PASSWORD
STATUS_APP_PASSWORD = STATUS_APP
STATUS_NEEDS_APP_PASSWORD = STATUS_NEED_APP_PASSWORD
STATUS_CONN_FAILED = STATUS_CONNECTION_FAILED
STATUS_PROXY_FAILED = STATUS_PROXY_UNHEALTHY
STATUS_COOLDOWN = STATUS_SKIPPED_COOLDOWN
STATUS_SKIPPED = STATUS_SKIP
STATUS_RETRYABLE = STATUS_RETRY
STATUS_UNKNOWN_ERROR = STATUS_UNKNOWN

is_wrong_status = is_wrong
is_valid_status = is_valid
is_app_status = is_app
is_retry_status = is_retryable
is_proxy_error = is_proxy_level_error
label_of = display
color_of = color
priority = priority_of

ALIASES = {
    "VALID": VALID,
    "WRONG": WRONG,
    "WRONG_PASSWORD": WRONG_PASSWORD,
    "APP": APP,
    "NEED_APP_PASSWORD": NEED_APP_PASSWORD,
    "FAILED": FAILED,
    "CONNECTION_FAILED": CONNECTION_FAILED,
    "PROXY_UNHEALTHY": PROXY_UNHEALTHY,
    "SKIP": SKIP,
    "SKIPPED_COOLDOWN": SKIPPED_COOLDOWN,
    "UNKNOWN": UNKNOWN,
    "RETRY": RETRY,
    "RETRY_LATER": RETRY_LATER,
    "RBL": RBL,
    "RBL_BLOCKED": RBL_BLOCKED,
    "SMTP_FAILED": SMTP_FAILED,
    "DNS_FAILED": DNS_FAILED,
    "LOGIN_DROPPED": LOGIN_DROPPED,
}

assert len(ALIASES) == len(STATUS_ALL_STATUSES), "alias/constant count mismatch"
assert all(ALIASES[k] == v for k, v in zip(ALIASES, STATUS_ALL_STATUSES)), "alias drift"


if __name__ == "__main__":
    import sys as _sys

    if "--selftest" in _sys.argv:
        alias_selftest(verbose=True)
    _sys.exit(0)
# @@END 012 APP_COMPAT
# @@EOF
