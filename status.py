"""
status.py — single source of truth for engine statuses and error classification.

Both naming conventions are exported (VALID + WRONG_PASSWORD, FAILED +
CONNECTION_FAILED, RBL + RBL_BLOCKED, ...) so `from status import (...)` can
never break.

Classification order is deliberate:
    APP -> WRONG_STRONG -> BARE_AUTH -> RBL -> DNS -> RETRY -> CONN -> WRONG -> UNKNOWN
CONN runs before WRONG so a proxy "Socket error: 407" is never read as an auth
failure by a generic token.

v13.18
------
* RBL / RBL_BLOCKED ARE NOW DEFINED.  app.py imports them, this file never
  exported them, so the whole `from status import (...)` block raised
  ImportError and the engine silently fell back to its inline classifier.
  The real classifier in this file is now live.
* Microsoft AADSTS codes added:
    AADSTS50126 / AADSTS50034           -> WRONG_PASSWORD
    AADSTS50076 / AADSTS50079 / 50074   -> NEED_APP_PASSWORD (MFA on)
  so an OAuth token refusal classifies instead of landing in UNKNOWN.
* ms_token_status() helper for the XOAUTH2 path.
* RBL is checked before CONN and before WRONG, so an IP-reputation block is
  never reported as a bare connection failure.
"""

# ---------------------------------------------------------------------------
# CANONICAL STATUSES  (every alias points at the same string)
# ---------------------------------------------------------------------------
VALID = "valid"
WRONG = WRONG_PASSWORD = "wrong_password"
APP = NEED_APP_PASSWORD = "need_app_password"
FAILED = CONNECTION_FAILED = "connection_failed"
SKIP = SKIPPED_COOLDOWN = "skipped_cooldown"
UNKNOWN = "unknown"
RETRY = RETRY_LATER = "retry_later"
RBL = RBL_BLOCKED = "rbl_blocked"
SMTP_FAILED = "smtp_failed"
DNS_FAILED = "dns_failed"
ERROR = "error"

ALL = [
    VALID,
    WRONG_PASSWORD,
    NEED_APP_PASSWORD,
    RETRY_LATER,
    RBL_BLOCKED,
    SMTP_FAILED,
    DNS_FAILED,
    CONNECTION_FAILED,
    UNKNOWN,
    SKIPPED_COOLDOWN,
]
ALL_STATUSES = ALL

TERMINAL = {VALID, WRONG_PASSWORD, NEED_APP_PASSWORD}

# Lower value = "better" answer. Used by merge() and by the engine when it has
# to pick between two verdicts it collected on the same account.
PRIORITY = {
    VALID: 0,
    NEED_APP_PASSWORD: 1,
    WRONG_PASSWORD: 2,
    RBL_BLOCKED: 3,
    RETRY_LATER: 4,
    SMTP_FAILED: 5,
    DNS_FAILED: 6,
    CONNECTION_FAILED: 7,
    UNKNOWN: 8,
    SKIPPED_COOLDOWN: 9,
}

LABELS = {
    VALID: "VALID",
    WRONG_PASSWORD: "WRONG_PASSWORD",
    NEED_APP_PASSWORD: "NEED_APP_PASSWORD",
    RETRY_LATER: "RETRY_LATER",
    RBL_BLOCKED: "RBL_BLOCKED",
    SMTP_FAILED: "SMTP_FAILED",
    DNS_FAILED: "DNS_FAILED",
    CONNECTION_FAILED: "CONNECTION_FAILED",
    UNKNOWN: "UNKNOWN",
    SKIPPED_COOLDOWN: "SKIPPED_COOLDOWN",
}

COLORS = {
    VALID: "#22c55e",
    WRONG_PASSWORD: "#ef4444",
    CONNECTION_FAILED: "#eab308",
    NEED_APP_PASSWORD: "#3b82f6",
    RETRY_LATER: "#ffffff",
    RBL_BLOCKED: "#facc15",
    SMTP_FAILED: "#a855f7",
    DNS_FAILED: "#f97316",
    UNKNOWN: "#94a3b8",
    SKIPPED_COOLDOWN: "#a78bfa",
}

# ---------------------------------------------------------------------------
# MATCH TABLES
# ---------------------------------------------------------------------------
_APP_PASSWORD = (
    "basic authentication is disabled",
    "basic auth is disabled",
    "basicauthenticationdisabled",
    "app password",
    "application specific password",
    "application-specific password",
    "app-specific password",
    "app specific password",
    "two-factor",
    "two factor",
    "2fa",
    "2-step",
    "2 step",
    "mfa",
    "multi-factor",
    "multi factor",
    "less secure app",
    "less secure apps",
    "lesssecureapp",
    "oauth",
    "oauth2",
    "token required",
    "an app password is required",
    "use an app password",
    "enable imap",
    "imap access is disabled",
    "imap is disabled",
    "pop access is disabled",
    "enable pop",
    "web login required",
    "via your web browser",
    "sign in with",
    "modern authentication",
    "authenticate with",
    "log in with your browser",
    "consent",
    "tenant",
    # Microsoft OAuth token refusals that mean "MFA is on"
    "aadsts50076",
    "aadsts50079",
    "aadsts50074",
    "strongauth",
)

_DNS = (
    "does not resolve",
    "failed to resolve",
    "name or service not known",
    "nodename nor servname",
    "getaddrinfo",
    "gaierror",
    "no address associated",
    "temporary failure in name resolution",
    "dns",
    "nxdomain",
    "servfail",
)

_RETRY = (
    "lookup failed",
    "user could not be routed",
    "could not route",
    "retry",
    "retry later",
    "try again",
    "temporarily unavailable",
    "temporary failure",
    "try again later",
    "service unavailable",
    "server busy",
    "too many",
    "rate limit",
    "rate-limit",
    "ratelimit",
    "throttle",
    "throttled",
    "over quota",
    "quota exceeded",
    "mailbox full",
    "system busy",
    "try later",
    "unavailable",
    "authentication services unavailable",
    "backend",
    "upstream",
    "downstream",
    "greylist",
    "greylisted",
    "unexpected extra arguments",
    "connection reset by peer",
)

_CONN = (
    "407",
    "proxy authentication",
    "proxy auth",
    "proxyconnect",
    "proxy connect",
    "proxy route",
    "bad proxy format",
    "proxy",
    "socks",
    "timed out",
    "timeout",
    "timedout",
    "connection refused",
    "connection reset",
    "connection aborted",
    "connection closed",
    "connection dropped",
    "connection lost",
    "connection failure",
    "connection negotiation failure",
    "negotiation failure",
    "socket error",
    "socket closed",
    "socket timeout",
    "eof",
    "broken pipe",
    "network is unreachable",
    "no route to host",
    "host is down",
    "reset by peer",
    "ssl",
    "tls",
    "wrong version number",
    "handshake",
    "certificate",
    "cert verify",
    "unexpected eof",
    "bad file descriptor",
    "not supported by server",
    "stls not supported",
    "starttls not supported",
    "tls not supported",
    "imap4rev1",
    "cannot connect",
    "unable to connect",
    "failed to connect",
    "connect failed",
)

# IP-reputation / greylist refusals.  Checked BEFORE _CONN and BEFORE _WRONG so
# a block is never reported as a password verdict or a bare connection failure.
_RBL = (
    "rbl restriction",
    "rbl",
    "abusix",
    "dnsbl",
    "spamhaus",
    "spam cop",
    "spamcop",
    "blacklist",
    "blacklisted",
    "blacklisted ip",
    "ip blocked",
    "ip is blocked",
    "blocked ip",
    "your ip",
)

_WRONG = (
    "authenticationfailed",
    "authentication failed",
    "authenticate error",
    "authenticate failed",
    "authentication error",
    "auth failed",
    "auth failure",
    "invalid credentials",
    "invalid credential",
    "invalid login",
    "invalid password",
    "invalid user",
    "invalid username",
    "invalid user name",
    "invalid account",
    "login incorrect",
    "login failed",
    "login failure",
    "login returned non-ok",
    "login non-ok",
    "login error",
    "password incorrect",
    "password invalid",
    "wrong password",
    "incorrect password",
    "realmless login not allowed",
    "realmless",
    "auth error",
    "[auth]",
    "authentication",
    "not authenticated",
    "bad credentials",
    "bad username",
    "bad password",
    "logon failure",
    "username and password not accepted",
    "user rejected",
    "password rejected",
    "invalid token",
    "expired token",
    "internal server error",
)

# Strong, unambiguous auth phrases checked before the CONN and RBL tables.
_WRONG_STRONG = (
    "realmless login not allowed",
    "authenticationfailed",
    "authentication failed",
    "invalid credentials",
    "invalid user name or password",
    "login incorrect",
    "wrong password",
    "authenticate error",
    "invalid login or password",
    # Microsoft OAuth token refusals that mean "wrong password"
    "aadsts50126",
    "aadsts50034",
    "invalid_grant",
)

# BARE / TERSE auth replies.  Some legacy Zimbra / Dovecot fronts answer a
# rejected LOGIN with the single token "LOGIN" (or "AUTH", "credentials").
# Matched against the WHOLE punctuation-stripped message.
_BARE_AUTH = (
    "login",
    "logon",
    "auth",
    "authenticate",
    "authentication",
    "sign in",
    "signin",
    "sign-in",
    "credentials",
    "invalid",
)

_PROXY_LEVEL = (
    "407",
    "proxy authentication required",
    "proxy auth",
    "proxyconnect",
    "proxy connect",
    "proxy route",
    "bad proxy format",
    "socks",
)


def _norm(text):
    return (text or "").strip().lower()


def _match(text, needles):
    return any(n in text for n in needles)


def _is_bare_auth(text):
    return text.strip().rstrip(".:!,;").strip() in _BARE_AUTH


# ---------------------------------------------------------------------------
# CLASSIFIER
# ---------------------------------------------------------------------------
def classify_error(raw, domain=""):
    """Map a raw server/socket error string to an engine status.

    Order: APP -> WRONG_STRONG -> BARE_AUTH -> RBL -> DNS -> RETRY -> CONN -> WRONG -> UNKNOWN
    """
    t = _norm(raw)
    if not t:
        return UNKNOWN

    if _match(t, _APP_PASSWORD):
        return NEED_APP_PASSWORD

    # Strong auth phrases win outright — they can otherwise be shadowed by the
    # generic "authentication" token or by a CONN token in the same message.
    if _match(t, _WRONG_STRONG):
        return WRONG_PASSWORD

    # A whole-message bare token ("LOGIN") is an auth rejection.
    if _is_bare_auth(t):
        return WRONG_PASSWORD

    if _match(t, _RBL):
        return RBL_BLOCKED
    if _match(t, _DNS):
        return DNS_FAILED
    if _match(t, _RETRY):
        return RETRY_LATER
    if _match(t, _CONN):
        return CONNECTION_FAILED
    if _match(t, _WRONG):
        return WRONG_PASSWORD
    return UNKNOWN


def ms_token_status(code):
    """Map a Microsoft AADSTS code to an engine status.

    Used by the XOAUTH2 path.  Returns None for codes that are not an account
    verdict (consent / app configuration), so the caller keeps its own verdict.
    """
    c = (code or "").upper()
    if c in ("AADSTS50126", "AADSTS50034"):
        return WRONG_PASSWORD
    if c in ("AADSTS50076", "AADSTS50079", "AADSTS50074"):
        return NEED_APP_PASSWORD
    return None


def is_retry_signal(raw):
    return _match(_norm(raw), _RETRY)


def is_proxy_level_error(raw):
    """True when the failure happened in the PROXY hop, not the mail server."""
    return _match(_norm(raw), _PROXY_LEVEL)


def is_app_password_signal(raw):
    return _match(_norm(raw), _APP_PASSWORD)


def is_dns_signal(raw):
    return _match(_norm(raw), _DNS)


def is_rbl_signal(raw):
    return _match(_norm(raw), _RBL)


def is_wrong_password_signal(raw):
    t = _norm(raw)
    return _is_bare_auth(t) or _match(t, _WRONG_STRONG) or _match(t, _WRONG)


# ---------------------------------------------------------------------------
# SMALL HELPERS
# ---------------------------------------------------------------------------
def merge(*statuses):
    cand = [s for s in statuses if s]
    if not cand:
        return UNKNOWN
    return sorted(cand, key=lambda s: PRIORITY.get(s, 99))[0]


def is_terminal(status):
    return status in TERMINAL


def is_failure(status):
    return status in (CONNECTION_FAILED, DNS_FAILED, SMTP_FAILED, UNKNOWN)


def display(status):
    return LABELS.get(status, status)


def color(status):
    return COLORS.get(status, "#cbd5e1")


def upper(status):
    return str(status or "").upper()
