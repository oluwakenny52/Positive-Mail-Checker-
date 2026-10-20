"""
status.py
=========
Status taxonomy + error classification for the Positive Mail Checker engine.

Exports BOTH naming conventions on purpose:
    app.py historically imported  VALID / WRONG / APP / FAILED / SKIP / UNKNOWN / RETRY
    newer UI code uses            VALID / WRONG_PASSWORD / NEED_APP_PASSWORD /
                                  CONNECTION_FAILED / RETRY_LATER / SMTP_FAILED / DNS_FAILED
Values are identical, so the two never drift.

`ALL` and `ALL_STATUSES` are BOTH exported. app.py imports `ALL_STATUSES as ST_ALL`.
Missing that alias used to throw the entire `from status import (...)` block in
app.py, which silently swapped the real classifier for a stub that returned
UNKNOWN for everything -- every auth error then logged "[Classified: unknown]".

Every UI surface (Live Execution Stream colours, live per-status dropdowns,
"Select category to inspect contents", "Engine Action Mode", Live Report Log &
Analytics) reads from here.
"""

# --------------------------------------------------------------------------
# Statuses  (values are the canonical lowercase wire strings)
# --------------------------------------------------------------------------
VALID = "valid"

WRONG_PASSWORD = "wrong_password"
WRONG = WRONG_PASSWORD

NEED_APP_PASSWORD = "need_app_password"
APP = NEED_APP_PASSWORD

RETRY_LATER = "retry_later"
RETRY = RETRY_LATER

SMTP_FAILED = "smtp_failed"
DNS_FAILED = "dns_failed"

CONNECTION_FAILED = "connection_failed"
FAILED = CONNECTION_FAILED

UNKNOWN = "unknown"

SKIPPED_COOLDOWN = "skipped_cooldown"
SKIP = SKIPPED_COOLDOWN

GOOD = [VALID]
RETRYABLE = [RETRY_LATER, SMTP_FAILED]

ALL = [
    VALID, WRONG_PASSWORD, NEED_APP_PASSWORD, RETRY_LATER, SMTP_FAILED,
    DNS_FAILED, CONNECTION_FAILED, UNKNOWN, SKIPPED_COOLDOWN,
]

# app.py does:  from status import (... ALL_STATUSES as ST_ALL ...)
ALL_STATUSES = ALL

LABELS = {
    VALID: "✅ Valid",
    WRONG_PASSWORD: "❌ Wrong Password",
    NEED_APP_PASSWORD: "🔐 App Password / 2FA",
    RETRY_LATER: "🕓 RETRY_LATER",
    SMTP_FAILED: "📮 SMTP Failed",
    DNS_FAILED: "🛰 DNS Failed",
    CONNECTION_FAILED: "🔌 Connection Failed",
    UNKNOWN: "❔ Unknown",
    SKIPPED_COOLDOWN: "⏭ Skipped",
}

# Live Execution Stream colour contract
COLORS = {
    VALID: "#22c55e",              # green
    WRONG_PASSWORD: "#ef4444",     # red
    CONNECTION_FAILED: "#eab308",  # yellow
    NEED_APP_PASSWORD: "#3b82f6",  # blue
    RETRY_LATER: "#ffffff",        # white
    SMTP_FAILED: "#a855f7",
    DNS_FAILED: "#f97316",
    UNKNOWN: "#94a3b8",
    SKIPPED_COOLDOWN: "#a78bfa",
}

# Lower rank wins when several probes disagree.
PRIORITY = {
    VALID: 0,
    NEED_APP_PASSWORD: 1,
    WRONG_PASSWORD: 2,
    RETRY_LATER: 3,
    SMTP_FAILED: 4,
    DNS_FAILED: 5,
    CONNECTION_FAILED: 6,
    UNKNOWN: 7,
    SKIPPED_COOLDOWN: 8,
}


def merge(*statuses):
    """Highest-confidence status from a set of observations."""
    ranked = [s for s in statuses if s]
    if not ranked:
        return UNKNOWN
    return sorted(ranked, key=lambda s: PRIORITY.get(s, 99))[0]


def is_terminal(status):
    return status in (VALID, WRONG_PASSWORD, NEED_APP_PASSWORD)


def is_failure(status):
    return status in (CONNECTION_FAILED, UNKNOWN, SMTP_FAILED, DNS_FAILED)


# --------------------------------------------------------------------------
# Classification tables
# --------------------------------------------------------------------------
_APP_PASSWORD = (
    "application-specific password", "application specific password",
    "app-specific password", "app specific password", "app password",
    "app-password", "apppassword",
    "basic authentication is disabled", "basic auth is disabled",
    "authentication is disabled", "authentication disabled",
    "imap access is disabled", "imap access disabled", "imap disabled",
    "web login required", "web login", "log in via your web browser",
    "login via web browser", "web browser", "webmail required",
    "logindisabled", "login disabled", "login-disabled", "login disabled",
    "two-factor", "two factor", "2fa", "mfa", "otp required",
    "enable imap", "enable less secure",
)

_DNS = (
    "fast-fail dns check failed", "does not resolve", "does not resolve locally",
    "host does not resolve", "no candidate host resolves", "no host resolves",
    "name or service not known", "nodename nor servname", "getaddrinfo failed",
    "no address associated", "temporary failure in name resolution", "gaierror",
)

_RETRY = (
    "lookup failed", "could not be routed", "user could not be routed",
    "could not route", "cannot route", "try again", "try again later",
    "temporarily", "temporary", "server busy", "server is busy",
    "system busy", "server not available", "service not available",
    "too many connections", "too many failed attempts", "too many login",
    "too many simultaneous", "too many", "ip blacklisted", "blacklisted",
    "rate limit", "ratelimit", "throttl", "greylist", "greylisted",
    "unavailable", "maintenance", "over quota", "quota exceeded",
    "exceeded", "internal server error", "system error", "please retry",
    "resource temporarily unavailable", "connection limit", "limit exceeded",
)

# NOTE: "[alert]" is deliberately NOT here. Gmail answers
#   "[ALERT] Invalid credentials (Failure)"  -> that is a WRONG password, and
#   "[ALERT] Please log in via your web browser" -> that is an APP password.
# Treating every [ALERT] as retryable mislabelled all of Gmail's auth failures.
_CONN = (
    "timed out", "timeout", "connection refused", "connection reset",
    "connection closed", "connection aborted", "connectionrefusederror",
    "socket error", "socket fail", "socket.timeout", "eof", "unexpected_eof",
    "unexpected eof", "tls not supported", "stls not supported", "ssl",
    "proxy connection failed", "proxy authentication required", "proxy auth",
    "proxyconnect", "proxy connect", "proxy route", "407",
    "network is unreachable", "unreachable", "broken pipe", "handshake",
    "no route to host", "bad file descriptor", "wrong version number",
    "certificate verify failed", "hostname mismatch", "certificate has expired",
    "self signed certificate", "self-signed certificate", "tlsv1",
    "proxy and direct fallback", "bad proxy format", "socks",
    "transport endpoint", "connection lost",
)

_WRONG = (
    "[authenticationfailed]", "authenticationfailed", "authentication failed",
    "authenticate error", "authenticate failed", "authentication error",
    "invalid credentials", "invalid login", "invalid password", "invalid user",
    "invalid username", "invalid user name", "login incorrect", "login failed",
    "login returned non-ok", "login non-ok", "password incorrect",
    "wrong password", "realmless login not allowed", "auth error", "[auth]",
    "not authenticated", "bad credentials", "bad username", "logon failure",
    "username and password not accepted", "user rejected", "password rejected",
    "invalid token", "expired token", "error",
)

_PROXY_LEVEL = (
    "407", "proxy authentication required", "proxy auth", "proxyconnect",
    "proxy connect", "proxy route", "bad proxy format", "socks",
)


def _norm(text):
    return (text or "").strip().lower()


def _match(text, needles):
    return any(n in text for n in needles)


def classify_error(raw, domain=""):
    """Map a raw server/socket error string to an engine status.

    Order matters: APP -> DNS -> RETRY -> CONN -> WRONG -> UNKNOWN.
    CONN is checked before WRONG so that 'Socket error: 407' is not read as
    an auth problem by the catch-all 'error' token.
    """
    t = _norm(raw)
    if not t:
        return UNKNOWN

    if _match(t, _APP_PASSWORD):
        return NEED_APP_PASSWORD
    if _match(t, _DNS):
        return DNS_FAILED
    if _match(t, _RETRY):
        return RETRY_LATER
    if _match(t, _CONN):
        return CONNECTION_FAILED
    if _match(t, _WRONG):
        return WRONG_PASSWORD
    return UNKNOWN


def is_retry_signal(raw):
    return _match(_norm(raw), _RETRY)


def is_proxy_level_error(raw):
    """True when the failure happened in the PROXY hop, not the mail server."""
    return _match(_norm(raw), _PROXY_LEVEL)


def is_app_password_signal(raw):
    return _match(_norm(raw), _APP_PASSWORD)


def is_dns_signal(raw):
    return _match(_norm(raw), _DNS)


def is_auth_signal(raw):
    return _match(_norm(raw), _WRONG)


def display(status):
    return LABELS.get(status, status)


def color(status):
    return COLORS.get(status, "#cbd5e1")


def upper(status):
    """Report-table spelling, e.g. 'retry_later' -> 'RETRY_LATER'."""
    return (status or "").upper()
