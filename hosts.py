"""
hosts.py
========
One host table. Primary first, backup second, with SRV/autoconfig/MX discovery.

v13.18 changes
--------------
* FAMILY_PRIORITY + DEAD_IMAP_HOSTS.  merge_domain_guesses() used to place the
  domain's own generic names (imap.<d>, mail.<d>, apex <d>) BEFORE the curated
  provider endpoints.  For every family provider those generic names are dead,
  so the one host that actually serves IMAP was buried and the account window
  expired before reaching it.  Live trace for a @yahoo.com account:

      Host order -> IMAP ['mail.yahoo.com', 'email.yahoo.com', 'yahoo.com',
                          'imap.mail.yahoo.com']
      every phase timed out on the first three, window reached, and
      imap.mail.yahoo.com:993 was NEVER dialled in any pass.

  FAMILY_PRIORITY is now prepended, and DEAD_IMAP_HOSTS is demoted to the tail.
* MS_IMAP / YAHOO_IMAP / ATT_IMAP / FRONTIER_IMAP / COUNTRY hosts are all
  registered as family priority, so the real endpoint is always rung 1.
"""

import os
import re
import json
import time
import socket
import tempfile
import threading
import concurrent.futures

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
    "hotmail.fr", "hotmail.de", "hotmail.it", "hotmail.es",
    "outlook.fr", "outlook.de", "outlook.it", "outlook.es", "outlook.co.uk",
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
    # Latin-America / Spanish-language ISPs: 'correo.' and 'webmail.' are common
    "montevideo.com.uy": ["mail.montevideo.com.uy", "webmail.montevideo.com.uy"],
    "adinet.com.uy": ["mail.adinet.com.uy"],
    "antel.com.uy": ["mail.antel.com.uy"],
    "uy.com": ["mail.uy.com"],
    # offenders seen in the failure log
    "freenet.de": ["imap.freenet.de"],
    "netcourrier.com": ["imap.netcourrier.com"],
    "bbox.fr": ["imap.bbox.fr"],
    "tin.it": ["imaps.tin.it", "imap.tin.it"],
    "sfr.fr": ["imap.sfr.fr"],
    "nc-online.de": ["imap.nc-online.de"],
    "cogeco.ca": ["imap.cogeco.ca"],
    "sympatico.ca": ["imap.sympatico.ca"],
}

# ============================================================================
# v13.18 - FAMILY PRIORITY + DEAD ENDPOINT DEMOTION
# ============================================================================

# Hosts that resolve but have NO IMAP listener.  They used to occupy the front
# of the ladder and consume the entire account window.
DEAD_IMAP_HOSTS = {
    "mail.yahoo.com", "email.yahoo.com", "yahoo.com",
    "mail.hotmail.com", "hotmail.com", "imap.hotmail.com", "email.hotmail.com",
    "mail.live.com", "live.com", "outlook.com", "mail.outlook.com",
    "att.net", "sbcglobal.net", "bellsouth.net", "pacbell.net",
    "frontiernet.net", "myfrontiermail.com",
    "charter.net", "spectrum.net", "twc.com", "verizon.net",
    "roadrunner.com", "rr.com",
}

# domain -> hosts that MUST lead the ladder for that domain.
FAMILY_PRIORITY = {}

for _d in FRONTIER:
    FAMILY_PRIORITY[_d] = list(FRONTIER_IMAP)
for _d in ATT_FAMILY:
    FAMILY_PRIORITY[_d] = list(ATT_IMAP)
for _d in VERIZON:
    FAMILY_PRIORITY[_d] = list(VERIZON_IMAP)
for _d in CHARTER:
    FAMILY_PRIORITY[_d] = list(CHARTER_IMAP)
for _d in TWC:
    FAMILY_PRIORITY[_d] = list(TWC_IMAP)
for _d in YAHOO_DOMAINS:
    FAMILY_PRIORITY[_d] = list(YAHOO_IMAP)
for _d in MS_DOMAINS:
    FAMILY_PRIORITY[_d] = list(MS_IMAP)
for _d in GMAIL_DOMAINS:
    FAMILY_PRIORITY[_d] = list(GMAIL_IMAP)
for _d, _h in COUNTRY.items():
    FAMILY_PRIORITY.setdefault(_d, list(_h))


def _family_priority(domain):
    """Hosts that must lead for this domain, including suffix families."""
    domain = (domain or "").lower().strip()
    if not domain:
        return []
    if domain in FAMILY_PRIORITY:
        return list(FAMILY_PRIORITY[domain])
    if domain.endswith(".rr.com"):
        return list(CHARTER_IMAP)
    if domain.endswith(".yahoo.com"):
        return list(YAHOO_IMAP)
    if domain.endswith(".outlook.com") or domain.endswith(".hotmail.com") or domain.endswith(".live.com"):
        return list(MS_IMAP)
    return []


def _order_provider_hosts(hosts, domain):
    """Family endpoints first, live endpoints next, known-dead endpoints last."""
    fam = _family_priority(domain)
    seen, alive, dead = set(), [], []
    for h in list(fam) + list(hosts or []):
        if not h or h in seen:
            continue
        seen.add(h)
        (dead if h in DEAD_IMAP_HOSTS else alive).append(h)
    return alive + dead


# Explicit SMTP endpoints for the providers whose SMTP host is NOT derived from
# their IMAP host. Checked before every guess.
SMTP_DIRECT = {
    "freenet.de": ["smtp.freenet.de", "mail.freenet.de"],
    "gmx.de": ["mail.gmx.net", "smtp.gmx.net"],
    "gmx.net": ["mail.gmx.net", "smtp.gmx.net"],
    "web.de": ["smtp.web.de", "mail.web.de"],
    "t-online.de": ["securesmtp.t-online.de"],
    "posteo.de": ["smtp.posteo.de"],
    "mailbox.org": ["smtp.mailbox.org"],
    "strato.de": ["smtp.strato.de"],
    "ionos.de": ["smtp.ionos.de"],
    "1und1.de": ["smtp.ionos.de"],
    "arcor.de": ["mail.arcor.de"],
    "netcourrier.com": ["smtp.netcourrier.com", "mail.netcourrier.com"],
    "bbox.fr": ["smtp.bbox.fr"],
    "sfr.fr": ["smtp.sfr.fr"],
    "orange.fr": ["smtp.orange.fr"],
    "free.fr": ["smtp.free.fr"],
    "laposte.net": ["smtp.laposte.net"],
    "tin.it": ["send.tin.it", "mail.tin.it"],
    "libero.it": ["smtp.libero.it"],
    "virgilio.it": ["smtp.virgilio.it"],
    "tiscali.it": ["smtp.tiscali.it"],
    "earthlink.net": ["smtpauth.earthlink.net", "mail.earthlink.net"],
    "comcast.net": ["smtp.comcast.net"],
    "cox.net": ["smtp.cox.net"],
    "optonline.net": ["mail.optonline.net"],
    "cogeco.ca": ["smtp.cogeco.ca"],
    "sympatico.ca": ["smtp.sympatico.ca"],
    "bluewin.ch": ["smtpauths.bluewin.ch"],
    "seznam.cz": ["smtp.seznam.cz"],
    "naver.com": ["smtp.naver.com"],
    "qq.com": ["smtp.qq.com"],
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
    "imap.aol.com",
]

UNIVERSAL_POP_FALLBACKS = [
    "pop.gmail.com",
    "outlook.office365.com",
    "pop.mail.yahoo.com",
    "pop.aol.com",
]

# MX-host substring -> (imap_host, pop_host, smtp_host).  ORDER MATTERS: specific first.
# "aol" MUST come before "yahoo" (AOL MX = mx-aol.mail.gm0.yahoodns.net).
MX_PROVIDER_MAP = (
    (("google", "gsuite", "googlemail"), ("imap.gmail.com", "pop.gmail.com", "smtp.gmail.com")),
    (("outlook", "microsoft", "office365", "protection.outlook"), ("outlook.office365.com", "outlook.office365.com", "smtp.office365.com")),
    (("aol",), ("imap.aol.com", "pop.aol.com", "smtp.aol.com")),
    (("yahoodns", "yahoo"), ("imap.mail.yahoo.com", "pop.mail.yahoo.com", "smtp.mail.yahoo.com")),
    (("icloud", "apple", "me.com"), ("imap.mail.me.com", "pop.mail.me.com", "smtp.mail.me.com")),
    # --- the offenders: provider identity is NOT the same as the MX brand ---
    (("freenet",), ("imap.freenet.de", "pop.freenet.de", "smtp.freenet.de")),
    (("gmx", "1and1", "ionos", "schlund", "united-domains", "kasserver", "udag"), ("imap.gmx.net", "pop.gmx.net", "mail.gmx.net")),
    (("web.de",), ("imap.web.de", "pop3.web.de", "smtp.web.de")),
    (("t-online", "tonline", "tmo"), ("secureimap.t-online.de", "securepop.t-online.de", "securesmtp.t-online.de")),
    (("posteo",), ("imap.posteo.de", "pop.posteo.de", "smtp.posteo.de")),
    (("mailbox.org",), ("imap.mailbox.org", "pop3.mailbox.org", "smtp.mailbox.org")),
    (("strato",), ("imap.strato.de", "pop.strato.de", "smtp.strato.de")),
    (("zoho",), ("imap.zoho.com", "pop.zoho.com", "smtp.zoho.com")),
    (("yandex",), ("imap.yandex.com", "pop.yandex.com", "smtp.yandex.com")),
    (("mail.ru", "internet.ru", "bk.ru", "list.ru", "inbox.ru"), ("imap.mail.ru", "pop.mail.ru", "smtp.mail.ru")),
    (("ovh",), ("ssl0.ovh.net", "ssl0.ovh.net", "ssl0.ovh.net")),
    (("fastmail", "messagingengine"), ("imap.fastmail.com", "pop.fastmail.com", "smtp.fastmail.com")),
    (("hostinger",), ("imap.hostinger.com", "pop.hostinger.com", "smtp.hostinger.com")),
    (("gandi",), ("mail.gandi.net", "mail.gandi.net", "mail.gandi.net")),
    (("rackspace", "emailsrvr"), ("secure.emailsrvr.com", "secure.emailsrvr.com", "secure.emailsrvr.com")),
    (("secureserver", "godaddy"), ("imap.secureserver.net", "pop.secureserver.net", "smtpout.secureserver.net")),
    (("laposte",), ("imap.laposte.net", "pop.laposte.net", "smtp.laposte.net")),
    (("orange", "wanadoo"), ("imap.orange.fr", "pop.orange.fr", "smtp.orange.fr")),
    (("proxad",), ("imap.free.fr", "pop.free.fr", "smtp.free.fr")),
    (("bluewin", "swisscom"), ("imaps.bluewin.ch", "pop3s.bluewin.ch", "smtpauths.bluewin.ch")),
    (("interia",), ("poczta.interia.pl", "poczta.interia.pl", "poczta.interia.pl")),
    (("seznam",), ("imap.seznam.cz", "pop3.seznam.cz", "smtp.seznam.cz")),
    (("naver",), ("imap.naver.com", "pop.naver.com", "smtp.naver.com")),
    (("daum", "hanmail"), ("imap.daum.net", "pop.daum.net", "smtp.daum.net")),
    (("qq.com", "tencent"), ("imap.qq.com", "pop.qq.com", "smtp.qq.com")),
    (("163.com", "126.com", "netease"), ("imap.163.com", "pop.163.com", "smtp.163.com")),
    (("biglobe",), ("mail.biglobe.ne.jp", "mail.biglobe.ne.jp", "mail.biglobe.ne.jp")),
    (("nifty",), ("imap.nifty.com", "pop.nifty.com", "smtp.nifty.com")),
    (("so-net",), ("imap.so-net.ne.jp", "pop.so-net.ne.jp", "smtp.so-net.ne.jp")),
    # shared-hosting platforms -> mail.<domain>
    (("bluehost", "hostgator", "cpanel", "siteground", "namecheap", "dreamhost",
      "liquidweb", "inmotion", "greengeeks", "a2hosting", "hostpapa",
      "netsol", "network solutions", "webhostingpad", "stablehost", "hawkhost"), (None, None, None)),
)

# ============================================================================
# ROUTER / RELAY DETECTION + CANDIDATE RANKING
# ============================================================================

_ROUTER_LABEL_EXACT = re.compile(
    r"^(?:"
    r"mx|mx\d+|mta|mtas|mta\d+|smtp|smtps|smtpout|smtp-in|smtp-out|"
    r"inbound|outbound|relay|relay\d+|spool|filter|filters|cluster|clust\d+|"
    r"edge|edge\d+|gateway|gw|gw\d+|router|mailrouter|aspmx|aspmx\d*|"
    r"alt\d+|protection|hs|lb|"
    r"mx-aol|mx-aol\.mail|mx\.google|eur\.olc|olc\.protection"
    r")$"
)

_ROUTER_TOKENS = (
    "mta", "smtp", "relay", "inbound", "outbound", "spool",
    "filter", "cluster", "mailrouter", "olc.protection",
    "protection.outlook", "aspmx", "gateway",
)

_SERVICE_PREFIXES = (
    "imap", "imaps", "imap2", "mail", "mail2", "pop", "pop3", "pop3s",
    "webmail", "webmail2", "email", "correo", "zimbra", "zcs",
    "secure", "ssl", "outlook", "exchange", "owa",
)

_SKIP_LABELS_FOR_TOKENS = {"mail", "email", "webmail", "imap", "imaps", "pop", "pop3", "smtp", "correo"}


def is_junk_host(host, domain=None):
    """True when a hostname is almost certainly a mail ROUTER (MX/MTA) rather
    than an IMAP/POP service endpoint. Demotion only - never removal."""
    h = (host or "").lower().strip().strip(".")
    if not h:
        return True
    if domain and h == (domain or "").lower().strip():
        return True

    labels = h.split(".")
    if len(labels) < 2:
        return False

    for lab in labels[:-1]:
        if _ROUTER_LABEL_EXACT.match(lab):
            return True

    for lab in labels[:-1]:
        if lab in _SKIP_LABELS_FOR_TOKENS:
            continue
        if any(tok in lab for tok in _ROUTER_TOKENS):
            return True
        if re.search(r"(?:^|[-_])mx\d*(?:$|[-_])", lab):
            return True

    return False


_is_junk_host = is_junk_host


def host_tier(host, domain):
    """0 = most likely correct ... 4 = last resort. Ordering only."""
    h = (host or "").lower().strip().strip(".")
    d = (domain or "").lower().strip().strip(".")
    if not h:
        return 4
    if d and h == d:
        return 3                                     # bare domain is usually a router
    if d and h.endswith("." + d):
        if is_junk_host(h, d):
            return 3
        first = h[: -(len(d) + 1)].split(".")[0]     # left-most label under the domain
        if first in _SERVICE_PREFIXES:
            return 0                                 # imap.<d>, mail.<d>, webmail.<d>, correo.<d>
        return 1
    if is_junk_host(h, d):
        return 3
    return 2                                         # provider endpoint (ssl0.ovh.net, imap.gmail.com)


_probe_lock = threading.Lock()
_probe_cache = {}
_PROBE_TTL = 600


def _port_open(host, port, timeout=1.5):
    try:
        s = socket.create_connection((host, port), timeout=timeout)
        s.close()
        return True
    except Exception:
        return False


def probe_live(host, timeout=1.5):
    """Cheap TCP reachability check on 993 / 143 (cached 10 min)."""
    if not host:
        return False
    now = time.time()
    with _probe_lock:
        hit = _probe_cache.get(host)
        if hit and now - hit[0] < _PROBE_TTL:
            return hit[1]

    ok = _port_open(host, 993, timeout) or _port_open(host, 143, timeout)

    with _probe_lock:
        _probe_cache[host] = (now, ok)
    return ok


def rank_hosts(hosts, domain, probe=True):
    """Composite ranking.

    Order of precedence:
      1. DNS RESOLVES    - a name that does not resolve cannot possibly work.
      2. tier            - service endpoint before router before bare domain
      3. port answers    - 993/143 reachable
      4. discovery index - preserves SRV / autoconfig authority order
    """
    hosts = [h for h in (hosts or []) if h]
    if not hosts:
        return []

    indexed = list(enumerate(hosts))
    if not probe:
        indexed.sort(key=lambda t: (
            0 if host_resolves(t[1]) else 1,
            host_tier(t[1], domain),
            t[0],
        ))
        return [h for _i, h in indexed]

    tiers = {h: host_tier(h, domain) for h in set(hosts)}
    resolves = {h: host_resolves(h) for h in set(hosts)}

    to_probe = [h for h in dict.fromkeys(hosts) if tiers[h] <= 1 and resolves[h]][:6]
    live = {}
    if to_probe:
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=min(6, len(to_probe))) as ex:
                futs = {ex.submit(probe_live, h): h for h in to_probe}
                for fut in concurrent.futures.as_completed(futs, timeout=6):
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


# ============================================================================
# CACHES  (atomic writes)
# ============================================================================

_CACHE_FILE = "hosts_cache.json"
_CACHE_TTL = 86400
_CACHE_MAX_AGE = 7 * 86400
_cache_lock = threading.RLock()
_cache = None

_resolve_lock = threading.Lock()
_resolve_cache = {}


def _atomic_write_json(path, obj, indent=2):
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
    return _save_cache()


def clear_cache():
    global _cache
    with _cache_lock:
        _cache = {}
    for p in (_CACHE_FILE, _CACHE_FILE + ".bak"):
        try:
            if os.path.exists(p):
                os.remove(p)
        except Exception:
            pass
    return True


def cache_stats():
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


# ============================================================================
# DNS HELPERS
# ============================================================================

def _dns_resolve(name, rdtype):
    if not _DNS:
        return []
    try:
        fn = getattr(dns.resolver, "resolve", None) or dns.resolver.query
        return list(fn(name, rdtype, lifetime=2))
    except Exception:
        try:
            return list(dns.resolver.query(name, rdtype))
        except Exception:
            return []


_mx_cache = {}
_mx_lock = threading.Lock()
_MX_TTL = 600


def resolve_mx(domain):
    domain = (domain or "").lower().strip()
    if not domain:
        return []
    now = time.time()
    with _mx_lock:
        hit = _mx_cache.get(domain)
    if hit and now - hit[0] < _MX_TTL:
        return list(hit[1])

    records = _dns_resolve(domain, "MX")
    out = []
    if records:
        try:
            records = sorted(records, key=lambda r: r.preference)
        except Exception:
            pass
        out = _dedupe([str(r.exchange).rstrip(".").lower() for r in records])

    with _mx_lock:
        _mx_cache[domain] = (now, out)
    return out


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
# DOMAIN-LOCAL + ALIAS-ROOT SERVICE-NAME MERGE
# ============================================================================

_LOCAL_PRIORITY_IMAP = ("imap.", "mail.", "email.", "")
_LOCAL_PRIORITY_POP = ("pop.", "pop3.", "")

_DOMAIN_IMAP_GUESS = (
    "imap.", "mail.", "", "imap3.", "imaps.", "imap2.",
    "webmail.", "mail2.", "imap4.", "correo.", "email.", "secure.", "zimbra.",
)
_DOMAIN_POP_GUESS = (
    "pop.", "pop3.", "", "pop3s.", "mail.", "pop2.", "pop4.", "mail2.",
)

_DOMAIN_ALIAS_ROOTS = {
    "xplornet.com": ("xplore.net",),
    "xplore.net":   ("xplornet.com",),
}


def _domain_roots(domain):
    """The domain itself followed by any known alias root (deduped)."""
    domain = (domain or "").lower().strip()
    roots = [domain] if domain else []
    for alt in _DOMAIN_ALIAS_ROOTS.get(domain, ()):
        if alt and alt not in roots:
            roots.append(alt)
    return roots


def _is_local_domain_host(host, domain):
    """True when host is the domain / an alias root, or sits under either."""
    h = (host or "").lower().strip()
    if not h:
        return False
    for root in _domain_roots(domain):
        if h == root or h.endswith("." + root):
            return True
    return False


def _guess_candidates(domain, prefixes):
    """Every '<prefix><root>' for the domain AND its alias roots that RESOLVES."""
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


def _is_plain_domain_guess(host, domain, prefixes):
    """True when host is just '<prefix><domain>' / the bare domain."""
    h = (host or "").lower().strip()
    d = (domain or "").lower().strip()
    if not h or not d:
        return False
    if h == d:
        return True
    return any(h == f"{p}{d}" for p in prefixes if p)


def merge_domain_guesses(servers, domain):
    """Insert the domain's own AND alias-root resolving service names.

    v13.18 ordering, per bucket:
        1. FAMILY_PRIORITY  - the curated endpoint for this provider
        2. local-priority   - imap./mail./email./apex for the domain and aliases
        3. other local
        4. FOREIGN          - provider endpoints, universal fallbacks, family hosts
        5. KNOWN-DEAD hosts - demoted to the very tail
    """
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

        local_priority = [h for h in _guess_candidates(domain, priority)
                          if h not in DEAD_IMAP_HOSTS]
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

        alive = [h for h in merged if h not in DEAD_IMAP_HOSTS]
        dead = [h for h in merged if h in DEAD_IMAP_HOSTS]
        out[key] = alive + dead
    return out


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
            r = requests.get(url, timeout=2.5, verify=False,
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
            r = requests.post(url, data=body, timeout=3, verify=False,
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


_IMAP_PREFIXES = ("imap.", "mail.", "webmail.", "imaps.", "correo.", "secure.", "zimbra.", "email.", "mail2.", "")
_POP_PREFIXES = ("pop.", "pop3.", "pop3s.", "mail.", "correo.", "")
_SMTP_PREFIXES = ("smtp.", "mail.", "smtp-mail.", "send.", "relay.", "")


def discover_hosts(domain, email=None, use_cache=True, force_refresh=False):
    """Ordered candidate discovery: SRV -> autoconfig -> autodiscover -> MX -> prefixes.

    Returns {"imap": [...], "pop": [...], "smtp": [...], "sources": [...]}
    """
    domain = (domain or "").lower().strip()
    if not domain:
        return {"imap": [], "pop": [], "smtp": [], "sources": []}

    if use_cache and not force_refresh:
        with _cache_lock:
            entry = _load_cache().get(domain)
        if entry and (time.time() - entry.get("ts", 0) < _CACHE_TTL):
            return {"imap": entry.get("imap", []), "pop": entry.get("pop", []),
                    "smtp": entry.get("smtp", []), "sources": entry.get("sources", ["cache"])}

    imap, pop, smtp, sources = [], [], [], []

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
        p_imap, p_pop, p_smtp = provider
        if p_imap:
            imap.append(p_imap)
            pop.append(p_pop or p_imap)
            smtp.append(p_smtp or f"mail.{domain}")
        else:
            imap.append(f"mail.{domain}")
            pop.append(f"mail.{domain}")
            smtp.append(f"mail.{domain}")
        sources.append("mx-provider")

    # 4. Well-known service names on the domain itself
    for pfx in _IMAP_PREFIXES:
        h = f"{pfx}{domain}"
        if h not in imap:
            imap.append(h)
    for pfx in _POP_PREFIXES:
        h = f"{pfx}{domain}"
        if h not in pop:
            pop.append(h)
    for pfx in _SMTP_PREFIXES:
        h = f"{pfx}{domain}"
        if h not in smtp:
            smtp.append(h)
    sources.append("prefix")

    # 5. MX-derived hostnames LAST (routers, usually not the endpoint)
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
                for pfx in ("smtp.", "mail."):
                    h = f"{pfx}{parent}"
                    if h not in smtp:
                        smtp.append(h)

    # 6. Universal fallbacks
    for fb in UNIVERSAL_IMAP_FALLBACKS:
        if fb not in imap:
            imap.append(fb)
    for fb in UNIVERSAL_POP_FALLBACKS:
        if fb not in pop:
            pop.append(fb)

    # 7. Family priority first, then rank: resolves -> tier -> port answers -> index
    imap = _order_provider_hosts(imap, domain)
    pop = _order_provider_hosts(pop, domain)
    imap = rank_hosts(_dedupe(imap), domain)[:8]
    pop = rank_hosts(_dedupe(pop), domain)[:6]
    smtp = rank_hosts(_dedupe(smtp), domain, probe=False)[:4]

    with _cache_lock:
        c = _load_cache()
        c[domain] = {"imap": imap, "pop": pop, "smtp": smtp, "sources": sources, "ts": time.time()}
    _save_cache()

    return {"imap": imap, "pop": pop, "smtp": smtp, "sources": sources}


# ============================================================================
# PUBLIC API
# ============================================================================

def domain_of(email_addr):
    return (email_addr or "").split("@")[-1].lower().strip()


def _pair(imap_hosts, pop_hosts, domain=None):
    if domain:
        imap_hosts = _order_provider_hosts(imap_hosts, domain)
        pop_hosts = _order_provider_hosts(pop_hosts, domain)
    return {"imap": imap_hosts, "pop": pop_hosts, "pop3": pop_hosts}


def get_mx_host(domain):
    mx_records = resolve_mx(domain)
    if not mx_records:
        return None
    exchange = mx_records[0]
    provider = _provider_from_mx(exchange)
    if provider and provider[0]:
        return provider[0]
    return exchange


def smtp_candidates(domain):
    """SMTP endpoints for the SMTP pre-check (never raises)."""
    domain = (domain or "").lower().strip()
    if not domain:
        return []
    if domain in ZERO_ACCESS:
        return []

    out = []

    for h in SMTP_DIRECT.get(domain, []):
        if h not in out:
            out.append(h)

    if not out:
        for m in resolve_mx(domain)[:2]:
            pair = _provider_from_mx(m)
            if pair and pair[2] and pair[2] not in out:
                out.append(pair[2])
                break

    known = COUNTRY.get(domain)
    if known:
        for h in known:
            cand = re.sub(r"^(imap|imaps|pop|pop3|secureimap|securepop)\.", "smtp.", h)
            if cand not in out:
                out.append(cand)

    for pfx in _SMTP_PREFIXES:
        h = f"{pfx}{domain}"
        if h not in out:
            out.append(h)

    ranked = rank_hosts(_dedupe(out), domain, probe=False)
    return ranked[:3] if ranked else _dedupe(out)[:3]


def _conf_curated(domain):
    """Curated / discovery answer WITHOUT the domain-local merge."""
    domain = (domain or "").lower().strip()
    if not domain:
        return None

    if domain in ZERO_ACCESS:
        return {"imap": [], "pop": [], "pop3": [], "type": "zero_access"}

    if domain in FRONTIER:
        return _pair(FRONTIER_IMAP, FRONTIER_POP, domain)
    if domain in ATT_FAMILY:
        return _pair(ATT_IMAP, ATT_POP, domain)
    if domain in VERIZON:
        return _pair(VERIZON_IMAP, VERIZON_POP, domain)
    if domain in CHARTER or domain.endswith(".rr.com"):
        return _pair(CHARTER_IMAP, CHARTER_POP, domain)
    if domain in TWC:
        return _pair(TWC_IMAP, TWC_POP, domain)
    if domain in YAHOO_DOMAINS or domain.endswith(".yahoo.com"):
        return _pair(YAHOO_IMAP, YAHOO_POP, domain)
    if domain in MS_DOMAINS or domain.endswith(".outlook.com") or domain.endswith(".hotmail.com"):
        return _pair(MS_IMAP, MS_POP, domain)
    if domain in GMAIL_DOMAINS:
        return _pair(GMAIL_IMAP, GMAIL_POP, domain)
    known = COUNTRY.get(domain)
    if known:
        return _pair(known, known, domain)

    found = discover_hosts(domain)
    if found["imap"] or found["pop"]:
        imap = found["imap"]
        pop = found["pop"] or found["imap"]
        return {"imap": imap, "pop": pop, "pop3": pop, "smtp": found.get("smtp", [])}

    return None


def conf(domain):
    """Full server config for a domain.

    Known providers are instant; everything else goes through cached discovery.
    EVERY curated answer is passed through merge_domain_guesses() so family
    priority, local priority and dead-endpoint demotion all apply.
    """
    domain = (domain or "").lower().strip()
    if not domain:
        return None

    got = _conf_curated(domain)
    if not got:
        return got
    if got.get("type") == "zero_access":
        return got
    return merge_domain_guesses(got, domain)


def provider_hosts(email_addr):
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
    return discover_hosts(domain, use_cache=True, force_refresh=True)


def is_disposable(email_addr):
    domain = domain_of(email_addr)
    return any(part in domain for part in DISPOSABLE_PARTS)
