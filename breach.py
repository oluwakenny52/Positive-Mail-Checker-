"""breach.py - breach exposure for one address, from FREE sources only.  v13.76

NO API KEY, and that shapes the whole design.

The per-account HIBP endpoint (/api/v3/breachedaccount) requires a paid key, so
it is never called. Three keyless sources replace it:

    catalogue  /api/v3/breaches - the whole breach list, ONE fetch, cached per
               user, then matched LOCALLY by domain. No per-address request at
               all for the common case.
    account    https://haveibeenpwned.com/account/<email> - scraped only when
               the local match is thin, because it is HTML and rate-limited.
    pastes     https://psbdmp.ws/api/search/<email> - paste dumps quoting the
               address.

THE VERDICT IS ABOUT FRESHNESS, NOT COUNT. "In 40 breaches from 2009" is noise;
"in a breach added three weeks ago" is the thing you act on. The bands are
derived from AddedDate, never from PwnCount.

Plain module, NOT frame-gated - like runstate.py, sentinel.py and mailsearch.py.
Nothing here imports Streamlit and nothing here renders.

ISOLATION
---------
The cache resolves through auth.user_file(), so it is one file per user. The
catalogue is identical for everybody but is still cached per user, because a
shared cache would need a lock and the fetch is cheap and rare.

EVERY public function swallows. A breach lookup must never be the reason a page
dies.
"""

import json
import os
import re
import time
from datetime import datetime

USER_AGENT = "PositiveMailChecker/1.0 (+https://github.com/oluwakenny52)"
HIBP_CATALOGUE = "https://haveibeenpwned.com/api/v3/breaches"
HIBP_ACCOUNT = "https://haveibeenpwned.com/account/%s"
PSBDMP_SEARCH = "https://psbdmp.ws/api/search/%s"

CACHE_NAME = "breach_cache.json"
CATALOGUE_TTL = 6 * 3600.0
ADDRESS_TTL = 6 * 3600.0
PASTE_TTL = 3600.0
# One HTML page every this many seconds, or HIBP throttles us.
ACCOUNT_MIN_INTERVAL = 2.0

NEW_DAYS = 90
RECENT_DAYS = 365

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_COUNT_RE = re.compile(r"(\d[\d,]*)\s+(?:data\s+)?breach", re.I)
_EMAIL = "_breach_last_call"


# --------------------------------------------------------------------------
# cache
# --------------------------------------------------------------------------
def _path() -> str:
    try:
        import auth
        p = auth.user_file(CACHE_NAME)
    except Exception:
        return ""
    try:
        os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
    except Exception:
        pass
    return p


def _load() -> dict:
    p = _path()
    if not p or not os.path.exists(p):
        return {}
    try:
        with open(p, encoding="utf-8", errors="ignore") as f:
            data = json.load(f)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _save(data: dict) -> None:
    p = _path()
    if not p:
        return
    tmp = p + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, separators=(",", ":"))
        os.replace(tmp, p)
    except Exception:
        pass


def _fresh(entry, ttl) -> bool:
    try:
        return bool(entry) and (time.time() - float(entry.get("ts") or 0)) < ttl
    except Exception:
        return False


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _norm(addr) -> str:
    return str(addr or "").strip().lower()


def domain_of(addr) -> str:
    a = _norm(addr)
    return a.split("@", 1)[1] if "@" in a else ""


def is_email(addr) -> bool:
    return bool(_EMAIL_RE.match(_norm(addr)))


def _throttle() -> None:
    """One account-page request every ACCOUNT_MIN_INTERVAL, process-wide.

    Module state is acceptable here: the limit belongs to the provider, not to a
    user, so two sessions sharing it is correct behaviour rather than a leak.
    """
    g = globals()
    last = g.get(_EMAIL, 0.0)
    wait = ACCOUNT_MIN_INTERVAL - (time.time() - last)
    if wait > 0:
        time.sleep(min(wait, ACCOUNT_MIN_INTERVAL))
    g[_EMAIL] = time.time()


def _get(url, accept="application/json", timeout=10):
    try:
        import requests
    except Exception:
        return None
    try:
        r = requests.get(url, timeout=timeout, verify=False,
                         headers={"User-Agent": USER_AGENT, "Accept": accept})
    except Exception:
        return None
    if r.status_code != 200:
        return None
    return r


def _days_ago(stamp) -> int:
    """Days between an ISO date (or epoch) and now. -1 when unparseable."""
    if stamp in (None, ""):
        return -1
    try:
        if isinstance(stamp, (int, float)):
            ts = float(stamp)
        else:
            ts = datetime.fromisoformat(str(stamp).replace("Z", "+00:00")).timestamp()
        return max(0, int((time.time() - ts) / 86400.0))
    except Exception:
        return -1


def _band(days: int) -> str:
    if days < 0:
        return "unknown"
    if days <= NEW_DAYS:
        return "new"
    if days <= RECENT_DAYS:
        return "recent"
    return "old"


# --------------------------------------------------------------------------
# catalogue
# --------------------------------------------------------------------------
def catalogue(force: bool = False) -> list:
    """The whole breach catalogue, cached. [] on failure.

    One fetch serves every address: the local match is by domain, so a run over
    500 addresses makes ONE request, not 500.
    """
    cache = _load()
    entry = cache.get("catalogue")
    if not force and _fresh(entry, CATALOGUE_TTL):
        return entry.get("rows") or []

    r = _get(HIBP_CATALOGUE)
    if r is None:
        return (entry or {}).get("rows") or []
    try:
        rows = r.json() or []
    except Exception:
        return (entry or {}).get("rows") or []
    if not isinstance(rows, list):
        return (entry or {}).get("rows") or []

    keep = []
    for b in rows:
        if not isinstance(b, dict):
            continue
        dom = _norm(b.get("Domain"))
        if not dom:
            continue
        keep.append({
            "name": b.get("Name") or "",
            "title": b.get("Title") or b.get("Name") or "",
            "domain": dom,
            "breach_date": b.get("BreachDate") or "",
            "added": b.get("AddedDate") or "",
            "pwn": int(b.get("PwnCount") or 0),
            "classes": [str(c) for c in (b.get("DataClasses") or [])],
            "verified": bool(b.get("IsVerified")),
            "sensitive": bool(b.get("IsSensitive")),
            "description": re.sub(r"<[^>]+>", " ", str(b.get("Description") or ""))[:400],
        })
    cache["catalogue"] = {"ts": time.time(), "rows": keep}
    _save(cache)
    return keep


def _match(rows, domain) -> list:
    """Breaches whose Domain is the address's domain or a parent of it."""
    d = _norm(domain)
    if not d:
        return []
    out = []
    for b in rows:
        bd = b.get("domain") or ""
        if bd == d or d.endswith("." + bd) or bd.endswith("." + d):
            out.append(b)
    return out


# --------------------------------------------------------------------------
# account page
# --------------------------------------------------------------------------
def _account_count(addr) -> int:
    """The breach count on the account page, or -1 when unreadable.

    Defensive on purpose: the page is HTML and HIBP restyles it. A miss returns
    -1 so the caller keeps whatever the local match found rather than reporting
    a false zero.
    """
    _throttle()
    r = _get(HIBP_ACCOUNT % _norm(addr), accept="text/html")
    if r is None:
        return -1
    try:
        body = r.text or ""
    except Exception:
        return -1
    if "good news" in body.lower() and "pwned" in body.lower():
        return 0
    m = _COUNT_RE.search(body)
    if m:
        try:
            return int(m.group(1).replace(",", ""))
        except Exception:
            return -1
    return -1


# --------------------------------------------------------------------------
# pastes
# --------------------------------------------------------------------------
def pastes(addr, force: bool = False) -> list:
    """Paste hits quoting the address. [] on failure."""
    a = _norm(addr)
    cache = _load()
    entry = (cache.get("pastes") or {}).get(a)
    if not force and _fresh(entry, PASTE_TTL):
        return entry.get("rows") or []

    r = _get(PSBDMP_SEARCH % a)
    if r is None:
        return (entry or {}).get("rows") or []
    try:
        data = r.json() or {}
    except Exception:
        return (entry or {}).get("rows") or []
    rows = []
    for d in (data.get("data") or [])[:50]:
        if not isinstance(d, dict):
            continue
        rows.append({"id": str(d.get("id") or ""),
                     "time": d.get("time") or "",
                     "tags": d.get("tags") or "",
                     "days": _days_ago(d.get("time"))})
    cache.setdefault("pastes", {})[a] = {"ts": time.time(), "rows": rows}
    _save(cache)
    return rows


# --------------------------------------------------------------------------
# the verdict
# --------------------------------------------------------------------------
def _verdict(breaches, paste_rows, count):
    """Freshness band -> verdict. Order of severity is NEW, RECENT, OLD, CLEAN."""
    bands = [_band(b.get("added_days", -1)) for b in breaches]
    fresh_paste = any((p.get("days", -1) >= 0 and p["days"] <= RECENT_DAYS)
                      for p in paste_rows)

    if "new" in bands:
        return "ACT", "in a breach added within %d days" % NEW_DAYS
    if fresh_paste:
        return "ACT", "quoted in a paste from the last year"
    if "recent" in bands:
        return "REVIEW", "in a breach added within a year"
    if breaches or paste_rows:
        return "HISTORIC", "only old breaches or pastes - rotate anyway"
    if count == 0:
        return "CLEAN", "not in the catalogue"
    if count < 0:
        return "UNKNOWN", "no readable answer"
    return "UNKNOWN", "count %d but no domain match" % count


def check(addr, force: bool = False) -> dict:
    """Full exposure report for ONE address. Never raises.

    Shape:
        {"email", "domain", "verdict", "reason", "count", "breaches",
         "pastes", "checked_at", "error"}
    """
    out = {"email": _norm(addr), "domain": "", "verdict": "UNKNOWN",
           "reason": "", "count": -1, "breaches": [], "pastes": [],
           "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "error": ""}
    try:
        if not is_email(addr):
            out["reason"] = "not an email address"
            return out
        out["domain"] = domain_of(addr)

        cache = _load()
        entry = (cache.get("address") or {}).get(out["email"])
        if not force and _fresh(entry, ADDRESS_TTL):
            return dict(entry.get("report") or out)

        rows = _match(catalogue(), out["domain"])
        for b in rows:
            b["added_days"] = _days_ago(b.get("added"))
            b["breach_days"] = _days_ago(b.get("breach_date"))
        rows.sort(key=lambda b: b.get("added_days", 10 ** 6))
        out["breaches"] = rows

        # The page is only worth a request when the local match is thin - the
        # catalogue is matched by DOMAIN, so a personal domain usually misses.
        count = -1
        if len(rows) < 1:
            count = _account_count(out["email"])
        out["count"] = count if count >= 0 else len(rows)

        try:
            out["pastes"] = pastes(out["email"], force=force)
        except Exception:
            out["pastes"] = []

        out["verdict"], out["reason"] = _verdict(rows, out["pastes"], count)

        cache.setdefault("address", {})[out["email"]] = {
            "ts": time.time(), "report": out}
        _save(cache)
        return out
    except Exception as e:
        out["error"] = "%s: %s" % (type(e).__name__, e)
        return out


def clear_cache() -> None:
    _save({})


def selftest() -> bool:
    """Offline: banding, matching and verdict precedence. No network."""
    checks = []

    def add(name, ok):
        checks.append((name, bool(ok)))

    add("new_band", _band(3) == "new")
    add("recent_band", _band(200) == "recent")
    add("old_band", _band(4000) == "old")
    add("unknown_band", _band(-1) == "unknown")

    rows = [{"domain": "example.com", "added_days": 3},
            {"domain": "mail.example.com", "added_days": 900}]
    add("match_parent", len(_match(rows, "example.com")) == 2)
    add("match_none", len(_match(rows, "elsewhere.org")) == 0)

    add("v_new", _verdict([{"added_days": 3}], [], 1)[0] == "ACT")
    add("v_recent", _verdict([{"added_days": 200}], [], 1)[0] == "REVIEW")
    add("v_old", _verdict([{"added_days": 4000}], [], 1)[0] == "HISTORIC")
    add("v_clean", _verdict([], [], 0)[0] == "CLEAN")
    add("v_unknown", _verdict([], [], -1)[0] == "UNKNOWN")
    add("v_paste", _verdict([], [{"days": 10}], 0)[0] == "ACT")

    add("is_email", is_email("a@b.com"))
    add("not_email", not is_email("nope"))
    add("domain_of", domain_of("A@B.com") == "b.com")

    bad = [n for n, ok in checks if not ok]
    if bad:
        raise AssertionError("breach selftest failed: " + ", ".join(bad))
    print("breach.py selftest: %d checks OK" % len(checks))
    return True


if __name__ == "__main__":
    import sys
    sys.exit(0 if selftest() else 1)
