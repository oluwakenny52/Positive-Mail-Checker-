"""One host table. Primary first, backup second, with SRV/autoconfig/MX discovery."""

import os
import re
import json
import time
import socket
import tempfile
import threading

try:
    import dns.resolver
    _DNS = True
except ImportError:
    _DNS = False

try:
    import requests
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    _REQ = True
except ImportError:
    _REQ = False


# ============================================================================
# STATIC PROVIDER TABLES
# ============================================================================

YAHOO_IMAP = ["imap.mail.yahoo.com"]
YAHOO_POP = ["pop.mail.yahoo.com"]
MS_IMAP = ["outlook.office365.com", "imap-mail.outlook.com"]
MS_POP = ["outlook.office365.com"]
GMAIL_IMAP = ["imap.gmail.com"]
GMAIL_POP = ["pop.gmail.com"]

YAHOO_DOMAINS = {
    "yahoo.com", "ymail.com", "rocketmail.com", "yahoo.co.uk", "yahoo.fr",
    "yahoo.de", "yahoo.it", "yahoo.es", "yahoo.com.br",
}
MS_DOMAINS = {
    "outlook.com", "hotmail.com", "live.com", "msn.com", "hotmail.co.uk",
    "outlook.com.br", "hotmail.com.br", "live.com.br", "windowslive.com",
}
GMAIL_DOMAINS = {"gmail.com", "googlemail.com"}
STRICT_APP = GMAIL_DOMAINS | {"outlook.com", "hotmail.com", "live.com", "windowslive.com"}
ZERO_ACCESS = {"proton.me", "protonmail.com", "pm.me", "tuta.io", "tutanota.com", "tutamail.com", "tuta.com"}
PARENT = {"memoad.jp": "biglobe.ne.jp"}

ATT_FAMILY = {
    "att.net", "sbcglobal.net", "bellsouth.net", "pacbell.net", "swbell.net",
    "ameritech.net", "currently.com", "prodigy.net", "snet.net", "flash.net",
    "nvbell.net", "wans.net",
}
ATT_IMAP = ["imap.mail.yahoo.com", "imap.mail.att.net"]
ATT_POP = ["pop.mail.yahoo.com", "inbound.att.net"]

FRONTIER = {"frontier.com", "frontiernet.net", "myfrontiermail.com", "citlink.net", "epix.net", "gte.net"}
FRONTIER_IMAP = ["imap.frontier.com", "mail.frontier.com", "imap.mail.yahoo.com"]
FRONTIER_POP = ["pop.frontier.com", "pop.mail.yahoo.com"]

CHARTER = {
    "charter.net", "roadrunner.com", "rr.com", "spectrum.net",
    "cfl.rr.com", "tampabay.rr.com", "nyc.rr.com", "nycap.rr.com", "rochester.rr.com",
    "socal.rr.com", "ca.rr.com", "tx.rr.com", "satx.rr.com", "austin.rr.com",
    "oh.rr.com", "cinci.rr.com", "columbus.rr.com", "carolina.rr.com", "nc.rr.com",
    "sc.rr.com", "wi.rr.com", "mi.rr.com", "indy.rr.com", "kc.rr.com", "hawaii.rr.com",
}
CHARTER_IMAP = ["mobile.charter.net", "imap.spectrum.net", "mail.twc.com"]
CHARTER_POP = ["mobile.charter.net", "mail.twc.com"]

TWC = {"twc.com", "brighthouse.com", "adelphia.net"}
TWC_IMAP = ["mail.twc.com", "mobile.charter.net"]
TWC_POP = ["mail.twc.com", "mobile.charter.net"]

VERIZON = {"verizon.net"}
VERIZON_IMAP = ["imap.aol.com", "imap.verizon.net"]
VERIZON_POP = ["pop.aol.com", "pop.verizon.net"]

COUNTRY = {
    "bluewin.ch": ["imaps.bluewin.ch"],
    "interia.pl": ["poczta.interia.pl"],
    "wp.pl": ["imap.wp.pl"],
    "onet.pl": ["imap.onet.pl"],
    "o2.pl": ["poczta.o2.pl"],
    "libero.it": ["imapmail.libero.it"],
    "virgilio.it": ["in.virgilio.it"],
    "tiscali.it": ["imap.tiscali.it"],
    "free.fr": ["imap.free.fr"],
    "orange.fr": ["imap.orange.fr"],
    "web.de": ["imap.web.de"],
    "gmx.de": ["imap.gmx.net"],
    "gmx.net": ["imap.gmx.net"],
    "t-online.de": ["secureimap.t-online.de"],
    "comcast.net": ["imap.comcast.net"],
    "windstream.net": ["imap.windstream.net", "mail.windstream.net"],
    "suddenlink.net": ["imap.suddenlink.net", "mail.suddenlink.net"],
    "cox.net": ["imap.cox.net", "imap.mail.yahoo.com"],
    "optonline.net": ["mail.optimum.net"],
    "centurylink.net": ["mail.centurylink.net"],
    "embarqmail.com": ["mail.centurylink.net"],
    "centurytel.net": ["mail.centurylink.net"],
    "mediacombb.net": ["mail.mediacombb.net"],
    "mchsi.com": ["mail.mediacombb.net"],
    "earthlink.net": ["imap.earthlink.net"],
    "breezeline.net": ["mail.breezeline.net"],
    "astound.net": ["imap.wavecable.com"],
    "wavemail.com": ["imap.wavecable.com"],
    "armstrong.net": ["imap.armstrong.net"],
    "icloud.com": ["imap.mail.me.com"],
    "me.com": ["imap.mail.me.com"],
    "naver.com": ["imap.naver.com"],
    "qq.com": ["imap.qq.com"],
}

DISPOSABLE_PARTS = (
    "tempmail", "temp-mail", "guerrillamail", "10minutemail", "mailinator",
    "yopmail", "trashmail", "throwaway", "fakeinbox", "sharklasers",
    "rerttymail", "discard.email", "maildrop", "getnada", "moakt",
    "tempmailo", "1secmail", "dispostable", "mailnesia", "mohmal",
    "tempinbox", "mailcatch", "spamgourmet", "mytemp", "tmpmail",
    "emailondeck", "tempail", "grr.la", "pokemail", "spam4.me",
)

UNIVERSAL_IMAP_FALLBACKS = [
    "imap.gmail.com",
    "outlook.office365.com",
    "imap.mail.yahoo.com",
    "imap.aol.com"
]

UNIVERSAL_POP_FALLBACKS = [
    "pop.gmail.com",
    "outlook.office365.com",
    "pop.mail.yahoo.com",
    "pop.aol.com"
]

# MX-host substring -> (imap_host, pop_host).  ORDER MATTERS: specific first.
# "aol" MUST come before "yahoo" (AOL MX = mx-aol.mail.gm0.yahoodns.net).
MX_PROVIDER_MAP = (
    (("google", "gsuite", "googlemail"), ("imap.gmail.com", "pop.gmail.com")),
    (("outlook", "microsoft", "office365", "protection.outlook"), ("outlook.office365.com", "outlook.office365.com")),
    (("aol",), ("imap.aol.com", "pop.aol.com")),
    (("yahoodns", "yahoo"), ("imap.mail.yahoo.com", "pop.mail.yahoo.com")),
    (("icloud", "apple", "me.com"), ("imap.mail.me.com", "pop.mail.me.com")),
    (("zoho",), ("imap.zoho.com", "pop.zoho.com")),
    (("yandex",), ("imap.yandex.com", "pop.yandex.com")),
    (("mail.ru", "internet.ru", "bk.ru", "list.ru", "inbox.ru"), ("imap.mail.ru", "pop.mail.ru")),
    (("gmx", "1and1", "ionos", "schlund", "united-domains"), ("imap.gmx.net", "pop.gmx.net")),
    (("t-online", "tonline", "tmo"), ("secureimap.t-online.de", "securepop.t-online.de")),
    (("ovh",), ("ssl0.ovh.net", "ssl0.ovh.net")),
    (("fastmail", "messagingengine"), ("imap.fastmail.com", "pop.fastmail.com")),
    (("hostinger",), ("imap.hostinger.com", "pop.hostinger.com")),
    (("gandi",), ("mail.gandi.net", "mail.gandi.net")),
    (("rackspace", "emailsrvr"), ("secure.emailsrvr.com", "secure.emailsrvr.com")),
    (("secureserver", "godaddy"), ("imap.secureserver.net", "pop.secureserver.net")),
    (("mailbox.org",), ("imap.mailbox.org", "pop3.mailbox.org")),
    (("posteo",), ("posteo.de", "posteo.de")),
    (("laposte",), ("imap.laposte.net", "pop.laposte.net")),
    (("orange", "wanadoo"), ("imap.orange.fr", "pop.orange.fr")),
    (("proxad",), ("imap.free.fr", "pop.free.fr")),
    (("bluewin", "swisscom"), ("imaps.bluewin.ch", "pop3s.bluewin.ch")),
    (("interia",), ("poczta.interia.pl", "poczta.interia.pl")),
    (("seznam",), ("imap.seznam.cz", "pop3.seznam.cz")),
    (("naver",), ("imap.naver.com", "pop.naver.com")),
    (("daum", "hanmail"), ("imap.daum.net", "pop.daum.net")),
    (("qq.com", "tencent"), ("imap.qq.com", "pop.qq.com")),
    (("163.com", "126.com", "netease"), ("imap.163.com", "pop.163.com")),
    (("biglobe",), ("mail.biglobe.ne.jp", "mail.biglobe.ne.jp")),
    (("nifty",), ("imap.nifty.com", "pop.nifty.com")),
    (("so-net",), ("imap.so-net.ne.jp", "pop.so-net.ne.jp")),
    # shared-hosting platforms -> mail.<domain>
    (("bluehost", "hostgator", "cpanel", "siteground", "namecheap", "dreamhost",
      "liquidweb", "inmotion", "greengeeks", "a2hosting", "hostpapa",
      "netsol", "network solutions", "webhostingpad", "stablehost", "hawkhost"), (None, None)),
)

# MX / mail-router hostnames that are almost never the user-facing IMAP endpoint.
# Used only to DEMOTE (never remove) so a live router host still beats a dead one.
_JUNK_HOST_MARKERS = (
    "mx", "mx1", "mx2", "mx3", "smtp", "inbound", "outbound", "spool",
    "filter", "relay", "gateway", "spam", "cluster", "edge", "aspmx",
    "mailrouter", "eur.olc", "olc.protection", "hs.", "lb.",
)


# ============================================================================
# CACHES
# ============================================================================

_CACHE_FILE = "hosts_cache.json"
_CACHE_TTL = 86400          # 24h - entry considered fresh
_CACHE_MAX_AGE = 7 * 86400  # 7d  - entry pruned entirely
_cache_lock = threading.RLock()   # RLock: _save_cache() may be called while held
_cache = None

_resolve_lock = threading.Lock()
_resolve_cache = {}


def _atomic_write_json(path, obj, indent=2):
    """Write JSON via temp file + os.replace() so readers NEVER see a partial file.

    os.replace() is atomic on POSIX and Windows, so the destination is either the
    complete old file or the complete new file - never a truncated one.
    """
    directory = os.path.dirname(os.path.abspath(path)) or "."
    try:
        os.makedirs(directory, exist_ok=True)
    except Exception:
        pass

    payload = json.dumps(obj, indent=indent)
    fd, tmp_path = tempfile.mkstemp(
        prefix=os.path.basename(path) + ".", suffix=".tmp", dir=directory
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(payload)
            f.flush()
            try:
                os.fsync(f.fileno())
            except Exception:
                pass
        os.replace(tmp_path, path)
    except Exception:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass
        raise

    # fsync the directory so the rename itself survives a hard power loss (POSIX)
    try:
        dir_fd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except Exception:
        pass

    return payload


def _load_cache():
    """Load cache, healing a corrupt/truncated main file from the .bak copy."""
    global _cache
    if _cache is not None:
        return _cache

    for candidate in (_CACHE_FILE, _CACHE_FILE + ".bak"):
        if not os.path.exists(candidate):
            continue
        try:
            with open(candidate, encoding="utf-8") as f:
                parsed = json.load(f)
            if isinstance(parsed, dict):
                _cache = parsed
                if candidate.endswith(".bak"):
                    # main file was corrupt or partial - restore it atomically
                    try:
                        _atomic_write_json(_CACHE_FILE, parsed)
                    except Exception:
                        pass
                return _cache
        except Exception:
            continue

    _cache = {}
    return _cache


def _save_cache():
    """Atomically persist the cache, prune stale entries, keep one .bak copy."""
    try:
        now = time.time()
        with _cache_lock:
            data = _cache if _cache is not None else {}
            for k in [k for k, v in data.items()
                      if not isinstance(v, dict)
                      or (now - float(v.get("ts", 0))) >= _CACHE_MAX_AGE]:
                data.pop(k, None)
            snapshot = dict(data)

        payload = _atomic_write_json(_CACHE_FILE, snapshot)

        try:
            with open(_CACHE_FILE + ".bak", "w", encoding="utf-8") as f:
                f.write(payload)
        except Exception:
            pass

        return True
    except Exception:
        return False


def flush_cache():
    """Public: force an atomic cache write right now."""
    return _save_cache()


def clear_cache():
    """Public: drop the cache from memory and disk."""
    global _cache
    with _cache_lock:
        _cache = {}
    try:
        if os.path.exists(_CACHE_FILE):
            os.remove(_CACHE_FILE)
    except Exception:
        pass
    try:
        if os.path.exists(_CACHE_FILE + ".bak"):
            os.remove(_CACHE_FILE + ".bak")
    except Exception:
        pass
    return True


def cache_stats():
    """Public: quick health view of the on-disk cache."""
    stats = {"entries": 0, "file_bytes": 0, "path": _CACHE_FILE,
             "has_backup": os.path.exists(_CACHE_FILE + ".bak"), "healthy": True}
    try:
        with _cache_lock:
            stats["entries"] = len(_load_cache())
        if os.path.exists(_CACHE_FILE):
            stats["file_bytes"] = os.path.getsize(_CACHE_FILE)
    except Exception:
        stats["healthy"] = False
    return stats


def _dedupe(seq):
    out = []
    for x in seq:
        if x and x not in out:
            out.append(x)
    return out


def _is_junk_host(host):
    h = (host or "").lower()
    if not h:
        return True
    label = h.split(".")[0]
    return any(label.startswith(m) for m in _JUNK_HOST_MARKERS)


# ============================================================================
# DNS HELPERS
# ============================================================================

def _dns_resolve(name, rdtype):
    if not _DNS:
        return []
    try:
        fn = getattr(dns.resolver, "resolve", None) or dns.resolver.query
        return list(fn(name, rdtype, lifetime=3))
    except Exception:
        try:
            return list(dns.resolver.query(name, rdtype))
        except Exception:
            return []


def resolve_mx(domain):
    records = _dns_resolve(domain, "MX")
    if not records:
        return []
    try:
        records = sorted(records, key=lambda r: r.preference)
    except Exception:
        pass
    return _dedupe([str(r.exchange).rstrip(".").lower() for r in records])


def resolve_srv(name):
    records = _dns_resolve(name, "SRV")
    out = []
    for r in records:
        try:
            out.append((int(r.priority), int(r.weight), str(r.target).rstrip(".").lower()))
        except Exception:
            continue
    return sorted(out)


def host_resolves(host):
    """Cheap existence check so dead guesses don't burn attempts."""
    if not host:
        return False
    with _resolve_lock:
        cached = _resolve_cache.get(host)
        if cached is not None:
            return cached

    ok = False
    try:
        if _DNS:
            try:
                if _dns_resolve(host, "A"):
                    ok = True
            except Exception:
                pass
            if not ok:
                try:
                    if _dns_resolve(host, "AAAA"):
                        ok = True
                except Exception:
                    pass
        if not ok:
            try:
                socket.gethostbyname(host)
                ok = True
            except Exception:
                ok = False
    except Exception:
        ok = False

    with _resolve_lock:
        _resolve_cache[host] = ok
    return ok


# ============================================================================
# DISCOVERY: SRV / AUTOCONFIG / AUTODISCOVER / MX
# ============================================================================

def _thunderbird_autoconfig(domain):
    if not _REQ:
        return [], []
    imap, pop = [], []
    urls = [
        f"https://autoconfig.{domain}/mail/config-v1.1.xml",
        f"https://{domain}/.well-known/autoconfig/mail/config-v1.1.xml",
    ]
    for url in urls:
        try:
            r = requests.get(url, timeout=4, verify=False,
                             headers={"User-Agent": "Mozilla/5.0 MailChecker"})
            if r.status_code != 200 or "<clientConfig" not in r.text:
                continue
            for block in re.findall(r"<incomingServer[^>]*>(.*?)</incomingServer>", r.text, re.S | re.I):
                t = re.search(r"<type>\s*([^<]+?)\s*</type>", block, re.I)
                h = re.search(r"<hostname>\s*([^<]+?)\s*</hostname>", block, re.I)
                if not h:
                    continue
                host = h.group(1).strip().lower().rstrip(".")
                stype = (t.group(1).strip().upper() if t else "IMAP")
                if stype == "POP3":
                    pop.append(host)
                else:
                    imap.append(host)
            if imap or pop:
                break
        except Exception:
            continue
    return _dedupe(imap), _dedupe(pop)


_AUTODISCOVER_BODY = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<Autodiscover xmlns="http://schemas.microsoft.com/exchange/autodiscover/outlook/requestschema/2006">'
    '<Request><EMailAddress>{email}</EMailAddress>'
    '<AcceptableResponseSchema>'
    'http://schemas.microsoft.com/exchange/autodiscover/outlook/responseschema/2006a'
    '</AcceptableResponseSchema></Request></Autodiscover>'
)


def _autodiscover(domain, email=None):
    if not _REQ:
        return [], []
    imap, pop = [], []
    body = _AUTODISCOVER_BODY.format(email=email or f"user@{domain}")
    urls = [
        f"https://autodiscover.{domain}/autodiscover/autodiscover.xml",
        f"https://{domain}/autodiscover/autodiscover.xml",
    ]
    for url in urls:
        try:
            r = requests.post(url, data=body, timeout=5, verify=False,
                              headers={"Content-Type": "text/xml; charset=utf-8",
                                       "User-Agent": "Mozilla/5.0 MailChecker"})
            if r.status_code != 200:
                continue
            for block in re.findall(r"<Protocol>(.*?)</Protocol>", r.text, re.S | re.I):
                t = re.search(r"<Type>\s*([^<]+?)\s*</Type>", block, re.I)
                s = re.search(r"<Server>\s*([^<]+?)\s*</Server>", block, re.I)
                if not (t and s):
                    continue
                stype = t.group(1).strip().upper()
                host = s.group(1).strip().lower().rstrip(".")
                if stype == "IMAP":
                    imap.append(host)
                elif stype == "POP3":
                    pop.append(host)
            if imap or pop:
                break
        except Exception:
            continue
    return _dedupe(imap), _dedupe(pop)


def _provider_from_mx(mx_host):
    m = (mx_host or "").lower()
    for keys, pair in MX_PROVIDER_MAP:
        if any(k in m for k in keys):
            return pair
    return None


def discover_hosts(domain, email=None, use_cache=True, force_refresh=False):
    """Ordered candidate discovery: SRV -> autoconfig -> autodiscover -> MX -> prefixes.

    Returns {"imap": [...], "pop": [...], "sources": [...]}
    """
    domain = (domain or "").lower().strip()
    if not domain:
        return {"imap": [], "pop": [], "sources": []}

    if use_cache and not force_refresh:
        with _cache_lock:
            entry = _load_cache().get(domain)
        if entry and (time.time() - entry.get("ts", 0) < _CACHE_TTL):
            return {"imap": entry.get("imap", []), "pop": entry.get("pop", []),
                    "sources": entry.get("sources", ["cache"])}

    imap, pop, sources = [], [], []

    # 1. SRV (RFC 6186) - most authoritative when present
    for svc, bucket in (("_imaps._tcp.", imap), ("_imap._tcp.", imap),
                        ("_pop3s._tcp.", pop), ("_pop3._tcp.", pop)):
        for _prio, _weight, target in resolve_srv(f"{svc}{domain}"):
            if target and target not in bucket:
                bucket.append(target)
    if imap or pop:
        sources.append("srv")

    mx_records = resolve_mx(domain)

    # 2. Autoconfig / Autodiscover (only worth trying if the domain is alive)
    if _REQ and (mx_records or host_resolves(domain)):
        a_imap, a_pop = _thunderbird_autoconfig(domain)
        if a_imap or a_pop:
            imap.extend(a_imap)
            pop.extend(a_pop)
            sources.append("autoconfig")
        if not imap:
            d_imap, d_pop = _autodiscover(domain, email)
            if d_imap or d_pop:
                imap.extend(d_imap)
                pop.extend(d_pop)
                sources.append("autodiscover")

    # 3. MX-derived provider
    provider = None
    for m in mx_records:
        provider = _provider_from_mx(m)
        if provider:
            break
    if provider:
        p_imap, p_pop = provider
        if p_imap:
            imap.append(p_imap)
            pop.append(p_pop or p_imap)
        else:
            # shared-hosting platform -> mail.<domain>
            imap.append(f"mail.{domain}")
            pop.append(f"mail.{domain}")
        sources.append("mx-provider")

    # 4. MX-derived hostnames (guessed from the MX parent)
    for m in mx_records[:2]:
        if m and m not in imap:
            imap.append(m)
        parts = m.split(".")
        if len(parts) >= 2:
            parent = ".".join(parts[-2:])
            if parent != domain:
                for pfx in ("imap.", "mail."):
                    h = f"{pfx}{parent}"
                    if h not in imap:
                        imap.append(h)

    # 5. Common-name guesses on the domain itself
    for pfx in ("imap.", "mail.", "imaps.", "secure.", "webmail.", ""):
        h = f"{pfx}{domain}"
        if h not in imap:
            imap.append(h)
    for pfx in ("pop.", "pop3.", "mail.", ""):
        h = f"{pfx}{domain}"
        if h not in pop:
            pop.append(h)
    sources.append("prefix")

    # 6. Rank: LIVE hosts first, then non-junk before mail-router junk.
    #    Stable sort keeps discovery order inside each tier. Demote, never drop.
    imap = sorted(imap, key=lambda h: (not host_resolves(h), _is_junk_host(h)))
    pop = sorted(pop, key=lambda h: (not host_resolves(h), _is_junk_host(h)))

    # 7. Universal fallbacks last
    for fb in UNIVERSAL_IMAP_FALLBACKS:
        if fb not in imap:
            imap.append(fb)
    for fb in UNIVERSAL_POP_FALLBACKS:
        if fb not in pop:
            pop.append(fb)

    imap = _dedupe(imap)[:8]
    pop = _dedupe(pop)[:6]

    with _cache_lock:
        c = _load_cache()
        c[domain] = {"imap": imap, "pop": pop, "sources": sources, "ts": time.time()}
    # write OUTSIDE the lock so 30 workers don't serialise on disk I/O
    _save_cache()

    return {"imap": imap, "pop": pop, "sources": sources}


# ============================================================================
# PUBLIC API
# ============================================================================

def domain_of(email_addr):
    return (email_addr or "").split("@")[-1].lower().strip()


def _pair(imap_hosts, pop_hosts):
    return {"imap": imap_hosts, "pop": pop_hosts, "pop3": pop_hosts}


def get_mx_host(domain):
    """Extract primary mail exchange host (or its known provider IMAP host)."""
    mx_records = resolve_mx(domain)
    if not mx_records:
        return None
    exchange = mx_records[0]
    provider = _provider_from_mx(exchange)
    if provider and provider[0]:
        return provider[0]
    return exchange


def conf(domain):
    """Full server config for a domain. Known providers are instant;
    everything else goes through cached discovery."""
    domain = (domain or "").lower().strip()
    if not domain:
        return None

    if domain in ZERO_ACCESS:
        return {"imap": [], "pop": [], "pop3": [], "type": "zero_access"}

    # --- Static, instant, no network ---
    if domain in FRONTIER:
        return _pair(FRONTIER_IMAP, FRONTIER_POP)
    if domain in ATT_FAMILY:
        return _pair(ATT_IMAP, ATT_POP)
    if domain in VERIZON:
        return _pair(VERIZON_IMAP, VERIZON_POP)
    if domain in CHARTER or domain.endswith(".rr.com"):
        return _pair(CHARTER_IMAP, CHARTER_POP)
    if domain in TWC:
        return _pair(TWC_IMAP, TWC_POP)
    if domain in YAHOO_DOMAINS or domain.endswith(".yahoo.com"):
        return _pair(YAHOO_IMAP, YAHOO_POP)
    if domain in MS_DOMAINS or domain.endswith(".outlook.com") or domain.endswith(".hotmail.com"):
        return _pair(MS_IMAP, MS_POP)
    if domain in GMAIL_DOMAINS:
        return _pair(GMAIL_IMAP, GMAIL_POP)
    known = COUNTRY.get(domain)
    if known:
        return _pair(known, known)

    # --- Discovered ---
    found = discover_hosts(domain)
    if found["imap"] or found["pop"]:
        imap = found["imap"]
        pop = found["pop"] or found["imap"]
        return {"imap": imap, "pop": pop, "pop3": pop, "sources": found["sources"]}

    return None


def provider_hosts(email_addr):
    """Returns (imap_candidates, pop_candidates)."""
    domain = domain_of(email_addr)
    got = conf(domain)
    if got:
        return got.get("imap", []), got.get("pop", [])

    found = discover_hosts(domain, email=email_addr)
    return found["imap"], found["pop"]


def host_list(email_addr):
    imap_hosts, _ = provider_hosts(email_addr)
    return imap_hosts[:8]


def ladder(email_addr, max_hosts=3, include_starttls=True):
    """Ordered attempt plan: [(proto, host, port, mode), ...]"""
    imap_hosts, pop_hosts = provider_hosts(email_addr)
    plan = []
    for h in imap_hosts[:max_hosts]:
        plan.append(("IMAP", h, 993, "ssl"))
    if include_starttls:
        for h in imap_hosts[:max_hosts]:
            plan.append(("IMAP", h, 143, "starttls"))
    for h in pop_hosts[:max_hosts]:
        plan.append(("POP", h, 995, "ssl"))
    if include_starttls:
        for h in pop_hosts[:max_hosts]:
            plan.append(("POP", h, 110, "starttls"))
    return plan


def refresh_domain(domain):
    """Force re-discovery, bypassing the cache."""
    return discover_hosts(domain, use_cache=True, force_refresh=True)


def is_disposable(email_addr):
    domain = domain_of(email_addr)
    return any(part in domain for part in DISPOSABLE_PARTS)
