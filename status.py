"""
status.py
=========
Status taxonomy + error classification for the Positive Mail Checker engine.

This is the single source of truth. Every UI surface (Live Execution Stream
colours, per-status live dropdowns, "Select category to inspect contents",
"Engine Action Mode", Live Report Log & Analytics) reads from here so nothing
can drift out of sync with the engine.
"""

# --------------------------------------------------------------------------
# Statuses
# --------------------------------------------------------------------------
VALID = "VALID"
WRONG_PASSWORD = "WRONG_PASSWORD"
NEED_APP_PASSWORD = "NEED_APP_PASSWORD"
RETRY_LATER = "RETRY_LATER"
SMTP_FAILED = "SMTP_FAILED"
DNS_FAILED = "DNS_FAILED"
CONNECTION_FAILED = "CONNECTION_FAILED"
UNKNOWN = "UNKNOWN"
FAILED = "FAILED"
SKIP = "SKIP"

GOOD = [VALID]
RETRYABLE = [RETRY_LATER, SMTP_FAILED]

ALL = [
    VALID, WRONG_PASSWORD, NEED_APP_PASSWORD, RETRY_LATER, SMTP_FAILED,
    DNS_FAILED, CONNECTION_FAILED, UNKNOWN, FAILED, SKIP,
]

LABELS = {
    VALID: "✅ Valid",
    WRONG_PASSWORD: "❌ Wrong Password",
    NEED_APP_PASSWORD: "🔐 App Password / 2FA",
    RETRY_LATER: "🕓 RETRY_LATER",
    SMTP_FAILED: "📮 SMTP Failed",
    DNS_FAILED: "🛰 DNS Failed",
    CONNECTION_FAILED: "🔌 Connection Failed",
    UNKNOWN: "❔ Unknown",
    FAILED: "⚠️ Failed",
    SKIP: "⏭ Skipped",
}

# Live Execution Stream colour contract (exactly as specified)
COLORS = {
    VALID: "#22c55e",              # green
    WRONG_PASSWORD: "#ef4444",     # red
    CONNECTION_FAILED: "#eab308",  # yellow
    NEED_APP_PASSWORD: "#3b82f6",  # blue
    RETRY_LATER: "#ffffff",        # white
    SMTP_FAILED: "#a855f7",
    DNS_FAILED: "#f97316",
    UNKNOWN: "#94a3b8",
    FAILED: "#f43f5e",
    SKIP: "#64748b",
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
    FAILED: 8,
    SKIP: 9,
}


def merge(*statuses):
    """Return the highest-confidence status from a set of observations."""
    ranked = [s for s in statuses if s]
    if not ranked:
        return UNKNOWN
    return sorted(ranked, key=lambda s: PRIORITY.get(s, 99))[0]


# --------------------------------------------------------------------------
# Classification
# --------------------------------------------------------------------------
_APP_PASSWORD = (
    "application-specific password", "application specific password",
    "app-specific password", "app password", "basic authentication is disabled",
    "basic auth is disabled", "imap access is disabled", "web login required",
    "authentication is disabled", "log in with your web browser",
)

_DNS = (
    "fast-fail dns check failed", "does not resolve", "name or service not known",
    "nodename nor servname", "getaddrinfo failed", "no address associated",
    "temporary failure in name resolution", "dns",
)

_RETRY = (
    "lookup failed", "could not be routed", "user could not be routed",
    "could not route", "try again", "temporarily", "temporary", "server busy",
    "too many connections", "too many failed attempts", "too many login",
    "ip blacklisted", "blacklisted", "rate limit", "ratelimit", "greylist",
    "greylisted", "unavailable", "maintenance", "over quota", "exceeded",
    "internal server error", "system error", "please retry", "later",
    "resource temporarily unavailable", "connection limit",
)

_WRONG = (
    "[authenticationfailed]", "authentication failed", "authenticate error",
    "invalid credentials", "invalid login", "invalid password", "invalid user",
    "login incorrect", "login failed", "password incorrect", "wrong password",
    "realmless login not allowed", "auth error", "[auth]", "not authenticated",
    "bad credentials", "error",
)

_CONN = (
    "timed out", "timeout", "connection refused", "connection reset",
    "connection closed", "connection aborted", "socket error", "socket fail",
    "eof", "tls not supported", "ssl", "proxy connection failed",
    "proxy authentication required", "407", "network is unreachable",
    "broken pipe", "unexpected eof", "handshake", "no route to host",
    "imap4.error: socket error", "proxy and direct fallback",
)

_PROXY_LEVEL = (
    "407", "proxy authentication required", "error connecting to http proxy",
    "proxy connection failed", "proxy server",
)


def _norm(text):
    return (text or "").strip().lower()


def _match(text, needles):
    return any(n in text for n in needles)


def classify_error(raw):
    """Map a raw server/socket error string to an engine status."""
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
    """True when the failure is the *proxy's* fault, not the target's."""
    t = _norm(raw)
    return _match(t, _PROXY_LEVEL)


def is_app_password_signal(raw):
    return _match(_norm(raw), _APP_PASSWORD)


def display(status):
    return LABELS.get(status, status)


def color(status):
    return COLORS.get(status, "#cbd5e1")
