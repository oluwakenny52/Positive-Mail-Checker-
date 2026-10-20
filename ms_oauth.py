"""
ms_oauth.py
===========
Microsoft personal-account (hotmail / outlook / live / msn) IMAP access via
OAuth2 XOAUTH2.

Microsoft disabled Basic Authentication for personal accounts on 2024-09-16, so
`LOGIN user password` on outlook.office365.com:993 answers
"Basic authentication is disabled".  The only two ways in are:

  A) an app password (the user must generate it; basic auth then works), or
  B) OAuth2 / XOAUTH2 using the REAL account password.

This module implements (B) via the ROPC (Resource Owner Password Credentials)
grant against the /consumers/ tenant, using Mozilla Thunderbird's public client
id, which needs no secret and no redirect URI.

A successful token request only proves the PASSWORD is right.  It proves
nothing about the mailbox, so a VALID verdict is only allowed after the token
has been used to AUTHENTICATE and then SELECT / STATUS / NOOP a real session.

Error contract
--------------
  MsTokenTransport -> network / malformed response.  NOT an account verdict:
                      the caller must keep whatever verdict it already holds.
  MsTokenRejected  -> a real answer from Microsoft, carrying an AADSTS code:
                        AADSTS50126 / AADSTS50034            -> wrong_password
                        AADSTS50076 / 50079 / 50074          -> need_app_password
                        AADSTS65001 / 700016 / 500011        -> unknown
"""

import base64
import json
import threading
import time

try:
    import requests
except ImportError:
    requests = None


MS_TOKEN_URL = "https://login.microsoftonline.com/consumers/oauth2/v2.0/token"
MS_CLIENT_ID = "9e5f94bc-e8a4-4e73-b8be-63364c29d753"   # Mozilla Thunderbird public client
MS_SCOPE = (
    "https://outlook.office.com/IMAP.AccessAsUser.All "
    "https://outlook.office.com/POP.AccessAsUser.All "
    "offline_access"
)

# The only hosts that speak Microsoft consumer IMAP.
MS_IMAP_HOSTS = frozenset({
    "outlook.office365.com",
    "imap-mail.outlook.com",
    "imap.outlook.com",
})

# Domains whose mailboxes live on Microsoft's consumer platform.
MS_DOMAINS = frozenset({
    "outlook.com", "hotmail.com", "live.com", "msn.com",
    "windowslive.com", "passport.com",
    "hotmail.co.uk", "hotmail.fr", "hotmail.de", "hotmail.it", "hotmail.es",
    "outlook.co.uk", "outlook.fr", "outlook.de", "outlook.it", "outlook.es",
    "outlook.com.br", "hotmail.com.br", "live.com.br", "live.co.uk",
})

# Phrases meaning "this host wants modern auth".  Used to decide whether a
# Microsoft token request is worth making at all, so a Gmail account whose APP
# signal came from the shared phrase table never triggers a Microsoft call.
MS_APP_SIGNALS = (
    "basic authentication is disabled",
    "basic auth is disabled",
    "basicauthenticationdisabled",
    "modern authentication",
    "logindisabled",
)

_TOKEN_CACHE = {}
_TOKEN_LOCK = threading.Lock()
_TOKEN_SKEW = 30          # treat a token as expired this many seconds early


class MsTokenTransport(Exception):
    """Network / malformed-response problem.  Never overwrite a verdict."""


class MsTokenRejected(Exception):
    """Microsoft answered with a real account-level error."""

    def __init__(self, code, description):
        super().__init__(description or code)
        self.code = (code or "").upper()
        self.description = description or ""

    @property
    def verdict(self):
        if self.code in ("AADSTS50126", "AADSTS50034"):
            return "wrong_password"
        if self.code in ("AADSTS50076", "AADSTS50079", "AADSTS50074"):
            return "need_app_password"
        return "unknown"


def _cache_key(email, password):
    # MUST include the password.  Two combos can share an address with
    # different passwords; a token cached under the address alone would
    # validate the wrong password (a genuine false-VALID).
    return (email.strip().lower(), password)


def _jwt_claims(token):
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload))
    except Exception:
        return {}


def _classify_token_error(description):
    upper = (description or "").upper()
    for code in ("AADSTS50126", "AADSTS50076", "AADSTS50079", "AADSTS50074",
                 "AADSTS50034", "AADSTS65001", "AADSTS700016", "AADSTS500011"):
        if code in upper:
            return code
    if "INVALID_GRANT" in upper:
        return "AADSTS50126"
    return ""


def should_try_ms_xoauth2(host, error_text, domain=""):
    """True only when this really is a Microsoft modern-auth refusal."""
    h = (host or "").lower().strip()
    d = (domain or "").lower().strip()
    if h not in MS_IMAP_HOSTS and d not in MS_DOMAINS:
        return False
    if not error_text:
        return True
    low = error_text.lower()
    return any(sig in low for sig in MS_APP_SIGNALS)


def ms_access_token(email, password, timeout=10, force_refresh=False):
    """ROPC token for one account.  Cached on (email, password)."""
    if requests is None:
        raise MsTokenTransport("requests library unavailable")

    key = _cache_key(email, password)
    now = time.time()
    if not force_refresh:
        with _TOKEN_LOCK:
            hit = _TOKEN_CACHE.get(key)
        if hit and hit[1] > now + _TOKEN_SKEW:
            return hit[0]

    try:
        resp = requests.post(
            MS_TOKEN_URL,
            timeout=timeout,
            data={
                "client_id": MS_CLIENT_ID,
                "scope": MS_SCOPE,
                "grant_type": "password",
                "username": email.strip(),
                "password": password,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    except Exception as exc:
        raise MsTokenTransport(f"token endpoint unreachable: {exc}")

    if resp.status_code != 200:
        raise MsTokenTransport(f"token endpoint HTTP {resp.status_code}: {resp.text[:140]}")

    try:
        data = resp.json()
    except Exception:
        raise MsTokenTransport(f"token endpoint non-JSON body: {resp.text[:140]}")

    token = data.get("access_token")
    if not isinstance(token, str) or token.count(".") != 2 or not data.get("expires_in"):
        description = data.get("error_description") or data.get("error") or ""
        code = _classify_token_error(description)
        if code:
            raise MsTokenRejected(code, description)
        raise MsTokenTransport(f"malformed token response: {str(data)[:140]}")

    try:
        expires = int(data.get("expires_in", 3600))
    except Exception:
        expires = 3600
    with _TOKEN_LOCK:
        _TOKEN_CACHE[key] = (token, now + expires)
    return token


def clear_ms_token_cache():
    with _TOKEN_LOCK:
        _TOKEN_CACHE.clear()


def _xoauth2_string(email, token):
    return f"user={email.strip()}\x01auth=Bearer {token}\x01\x01".encode("utf-8")


def imap_xoauth2_open(email, password, server, proxy_class, port=993,
                      proxy_str=None, insecure=True, attempt_timeout=10):
    """Authenticate and return a LIVE open mailbox.

    Gates, in order:
      1. token transport + shape            (ms_access_token)
      2. server is really IMAP4rev1 and advertises XOAUTH2
      3. AUTHENTICATE XOAUTH2 returns OK
      4. SELECT INBOX returns OK with a parseable EXISTS count
      5. STATUS INBOX (MESSAGES UIDNEXT) returns OK
      6. NOOP returns OK

    Returns (open_mail, exists_count, claims).  Raises on any failure.
    The caller owns the connection and must log it out.
    """
    token = ms_access_token(email, password, timeout=attempt_timeout)
    claims = _jwt_claims(token)

    mail = proxy_class(server, port=port, timeout=attempt_timeout,
                       proxy_str=proxy_str, insecure=insecure)
    try:
        typ, caps = mail.capability()
        joined = b" ".join(caps or []).upper()
        if typ != "OK" or b"IMAP4REV1" not in joined:
            raise RuntimeError("XOAUTH2 gate 2: server is not IMAP4rev1")
        if b"XOAUTH2" not in joined:
            raise RuntimeError("XOAUTH2 gate 2: server does not advertise XOAUTH2")

        typ, data = mail.authenticate("XOAUTH2", lambda _c: _xoauth2_string(email, token))
        if typ != "OK":
            raise RuntimeError(f"XOAUTH2 gate 3: rejected ({data})")

        typ, data = mail.select("INBOX", readonly=True)
        if typ != "OK":
            raise RuntimeError(f"XOAUTH2 gate 4: SELECT INBOX failed ({data})")
        try:
            exists = int((data[0] or b"0"))
        except Exception:
            exists = 0

        typ, data = mail.status("INBOX", "(MESSAGES UIDNEXT)")
        if typ != "OK" or b"MESSAGES" not in b" ".join(data or []):
            raise RuntimeError("XOAUTH2 gate 5: STATUS INBOX failed")

        if mail.noop()[0] != "OK":
            raise RuntimeError("XOAUTH2 gate 6: NOOP failed")

        return mail, exists, claims
    except Exception:
        try:
            mail.logout()
        except Exception:
            pass
        raise


def imap_xoauth2_once(email, password, server, proxy_class, port=993,
                      proxy_str=None, insecure=True, attempt_timeout=10):
    """Same as imap_xoauth2_open but closes the connection.  Returns (exists, claims)."""
    mail, exists, claims = imap_xoauth2_open(
        email, password, server, proxy_class, port=port, proxy_str=proxy_str,
        insecure=insecure, attempt_timeout=attempt_timeout)
    try:
        mail.logout()
    except Exception:
        pass
    return exists, claims
