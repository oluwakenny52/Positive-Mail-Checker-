"""mailsort.py - sort a row set into ordered groups, ready to export.

PLAIN MODULE, like runstate.py and mailsearch.py: no @@BLOCK frame, no gate
rows, nothing to renumber. pages/4_Downloads.py imports it and hands it the rows
it has ALREADY parsed, so this file never touches the disk, never reads a source
and never knows what a result file is.

WHAT IT IS FOR
--------------
An export that is one flat file is useless once it is on a phone. Grouping is
the difference between "4000 lines" and "62 domains, largest first, take the one
you want". This turns a row set into N named groups with a stated order, and the
page gives each group its own button plus one archive of all of them.

A GROUP LABEL IS A FILE NAME, so safe_name() is the only thing allowed to build
one. A domain with a slash or a colon in it must not become a path.

Ordering is explicit and always applied - "A-Z" is the default, not "whatever
order the dict came out in" - so the same input produces the same archive twice.

COUNTRY AND REGION  (v13.86)
----------------------------
A ccTLD is a country by definition, but a bare `.com` says nothing about where
an account is - `alditra.com` is Indonesian and no TLD-only rule can know that.
So the lookup never guesses from a gTLD. It goes, in order:

    1. the owner's own map, which always wins and is taught from the page
    2. a seed map of free-mail providers and big brands
    3. a real ccTLD, two-label ones like co.uk included
    4. a generic TLD -> the Global / gTLD bucket
    5. anything else -> unknown

`.io` and `.tv` are technically the British Indian Ocean Territory and Tuvalu,
but nobody groups by that, so they sit in GENERIC_TLDS and land in the Global
bucket. The custom map is a per-user JSON file and is the only tier that grows.
"""

import io
import json
import os
import re
import zipfile

# Local rank, so ordering never depends on the page's table.
_RANK = {
    "VALID": 90, "WRONG_PASSWORD": 80, "NEED_APP_PASSWORD": 78, "RBL_BLOCKED": 70,
    "LOGIN_DROPPED": 60, "SMTP_FAILED": 50, "DNS_FAILED": 45,
    "PROXY_UNHEALTHY": 40, "CONNECTION_FAILED": 35, "RETRY_LATER": 30,
    "SKIPPED": 20, "UNKNOWN": 10, "MIXED": 5,
}

ORDERS = ["A-Z", "Z-A", "Largest group first", "Smallest group first",
          "Strongest status first"]

CAP_DEFAULT = 5000
MAX_GROUPS_RENDERED = 20


def _kw(detail):
    m = re.search(r"\bkw:([^|]*)", detail or "")
    if not m:
        return ""
    words = [w.strip() for w in m.group(1).split(",") if w.strip()]
    return ", ".join(words[:3]) or ""


def _folder(detail):
    m = re.search(r"\bfolder:([^|]*)", detail or "")
    return (m.group(1).strip() if m else "") or ""


def _band(pw):
    n = len(pw or "")
    if n <= 6:
        return "1-6 chars"
    if n <= 9:
        return "7-9 chars"
    if n <= 12:
        return "10-12 chars"
    return "13+ chars"


def _tld(domain):
    d = (domain or "").strip().lower()
    return d.rsplit(".", 1)[-1] if "." in d else "(none)"


def _first(local):
    s = (local or "").strip()
    return s[:1].lower() if s else "(blank)"


# ---------------------------------------------------------------------------
# country / region
# ---------------------------------------------------------------------------
_TLD_COUNTRY = {
    "uk": "United Kingdom", "co.uk": "United Kingdom", "org.uk": "United Kingdom",
    "me.uk": "United Kingdom", "ltd.uk": "United Kingdom", "ac.uk": "United Kingdom",
    "de": "Germany", "fr": "France", "es": "Spain", "it": "Italy", "nl": "Netherlands",
    "be": "Belgium", "ch": "Switzerland", "at": "Austria", "se": "Sweden",
    "no": "Norway", "dk": "Denmark", "fi": "Finland", "ie": "Ireland",
    "pt": "Portugal", "pl": "Poland", "cz": "Czechia", "sk": "Slovakia",
    "hu": "Hungary", "ro": "Romania", "bg": "Bulgaria", "gr": "Greece",
    "hr": "Croatia", "si": "Slovenia", "rs": "Serbia", "ua": "Ukraine",
    "ru": "Russia", "by": "Belarus", "lt": "Lithuania", "lv": "Latvia",
    "ee": "Estonia", "is": "Iceland", "lu": "Luxembourg", "mt": "Malta",
    "cy": "Cyprus", "tr": "Turkey", "il": "Israel", "ae": "United Arab Emirates",
    "sa": "Saudi Arabia", "qa": "Qatar", "kw": "Kuwait", "bh": "Bahrain",
    "om": "Oman", "jo": "Jordan", "lb": "Lebanon", "eg": "Egypt", "ma": "Morocco",
    "dz": "Algeria", "tn": "Tunisia", "ly": "Libya", "ng": "Nigeria",
    "gh": "Ghana", "ke": "Kenya", "za": "South Africa", "tz": "Tanzania",
    "ug": "Uganda", "et": "Ethiopia", "sn": "Senegal", "ci": "Cote d'Ivoire",
    "cm": "Cameroon", "zw": "Zimbabwe", "zm": "Zambia", "mz": "Mozambique",
    "us": "United States", "ca": "Canada", "mx": "Mexico", "br": "Brazil",
    "ar": "Argentina", "cl": "Chile", "co": "Colombia", "pe": "Peru",
    "ve": "Venezuela", "ec": "Ecuador", "uy": "Uruguay", "py": "Paraguay",
    "bo": "Bolivia", "cr": "Costa Rica", "pa": "Panama", "gt": "Guatemala",
    "do": "Dominican Republic", "cu": "Cuba", "jm": "Jamaica",
    "tt": "Trinidad and Tobago", "au": "Australia", "com.au": "Australia",
    "nz": "New Zealand", "co.nz": "New Zealand", "fj": "Fiji", "pg": "Papua New Guinea",
    "cn": "China", "hk": "Hong Kong", "tw": "Taiwan", "jp": "Japan", "kr": "South Korea",
    "in": "India", "pk": "Pakistan", "bd": "Bangladesh", "lk": "Sri Lanka",
    "np": "Nepal", "th": "Thailand", "vn": "Vietnam", "my": "Malaysia",
    "sg": "Singapore", "id": "Indonesia", "ph": "Philippines", "kh": "Cambodia",
    "mm": "Myanmar", "kz": "Kazakhstan", "uz": "Uzbekistan", "az": "Azerbaijan",
    "ge": "Georgia", "am": "Armenia", "md": "Moldova", "al": "Albania",
    "ba": "Bosnia and Herzegovina", "mk": "North Macedonia", "me": "Montenegro",
}

_REGION_OF = {
    "United Kingdom": "Europe", "Germany": "Europe", "France": "Europe",
    "Spain": "Europe", "Italy": "Europe", "Netherlands": "Europe",
    "Belgium": "Europe", "Switzerland": "Europe", "Austria": "Europe",
    "Sweden": "Europe", "Norway": "Europe", "Denmark": "Europe",
    "Finland": "Europe", "Ireland": "Europe", "Portugal": "Europe",
    "Poland": "Europe", "Czechia": "Europe", "Slovakia": "Europe",
    "Hungary": "Europe", "Romania": "Europe", "Bulgaria": "Europe",
    "Greece": "Europe", "Croatia": "Europe", "Slovenia": "Europe",
    "Serbia": "Europe", "Ukraine": "Europe", "Russia": "Europe",
    "Belarus": "Europe", "Lithuania": "Europe", "Latvia": "Europe",
    "Estonia": "Europe", "Iceland": "Europe", "Luxembourg": "Europe",
    "Malta": "Europe", "Cyprus": "Europe", "Moldova": "Europe",
    "Albania": "Europe", "Bosnia and Herzegovina": "Europe",
    "North Macedonia": "Europe", "Montenegro": "Europe",
    "Turkey": "Middle East", "Israel": "Middle East",
    "United Arab Emirates": "Middle East", "Saudi Arabia": "Middle East",
    "Qatar": "Middle East", "Kuwait": "Middle East", "Bahrain": "Middle East",
    "Oman": "Middle East", "Jordan": "Middle East", "Lebanon": "Middle East",
    "Egypt": "Africa", "Morocco": "Africa", "Algeria": "Africa",
    "Tunisia": "Africa", "Libya": "Africa", "Nigeria": "Africa",
    "Ghana": "Africa", "Kenya": "Africa", "South Africa": "Africa",
    "Tanzania": "Africa", "Uganda": "Africa", "Ethiopia": "Africa",
    "Senegal": "Africa", "Cote d'Ivoire": "Africa", "Cameroon": "Africa",
    "Zimbabwe": "Africa", "Zambia": "Africa", "Mozambique": "Africa",
    "United States": "North America", "Canada": "North America",
    "Mexico": "North America", "Costa Rica": "North America",
    "Panama": "North America", "Guatemala": "North America",
    "Dominican Republic": "North America", "Cuba": "North America",
    "Jamaica": "North America", "Trinidad and Tobago": "North America",
    "Brazil": "South America", "Argentina": "South America",
    "Chile": "South America", "Colombia": "South America",
    "Peru": "South America", "Venezuela": "South America",
    "Ecuador": "South America", "Uruguay": "South America",
    "Paraguay": "South America", "Bolivia": "South America",
    "Australia": "Oceania", "New Zealand": "Oceania", "Fiji": "Oceania",
    "Papua New Guinea": "Oceania",
    "China": "Asia", "Hong Kong": "Asia", "Taiwan": "Asia", "Japan": "Asia",
    "South Korea": "Asia", "India": "Asia", "Pakistan": "Asia",
    "Bangladesh": "Asia", "Sri Lanka": "Asia", "Nepal": "Asia",
    "Thailand": "Asia", "Vietnam": "Asia", "Malaysia": "Asia",
    "Singapore": "Asia", "Indonesia": "Asia", "Philippines": "Asia",
    "Cambodia": "Asia", "Myanmar": "Asia", "Kazakhstan": "Asia",
    "Uzbekistan": "Asia", "Azerbaijan": "Asia", "Georgia": "Asia",
    "Armenia": "Asia",
}

NO_COUNTRY = "(unknown country)"
NO_REGION = "(unknown region)"
COUNTRY_GENERIC = "Global / gTLD"
REGION_GENERIC = "Global"

# TLDs bought for meaning rather than for a country. `.io` is technically the
# British Indian Ocean Territory and `.tv` is Tuvalu, but nobody groups by that,
# so these land in the Global bucket instead of a country nobody recognises.
GENERIC_TLDS = frozenset({
    "com", "net", "org", "info", "biz", "edu", "gov", "mil", "int",
    "io", "co", "me", "tv", "ai", "cc", "ws", "to", "fm", "am", "nu", "sh",
    "ac", "la", "ly", "gg", "im", "vc", "bz", "gs", "ms", "tk", "cx",
    "app", "dev", "xyz", "online", "site", "shop", "store", "cloud", "email",
    "tech", "pro", "link", "live", "life", "world", "today", "digital",
    "agency", "media", "group", "network", "solutions", "services", "systems",
    "global", "one", "run", "page", "blog", "design", "studio", "works",
    "space", "website", "press", "finance", "capital", "fund", "ventures",
    "company", "host", "art", "cafe", "fun", "icu", "top", "vip", "wiki",
    "zone", "codes", "tools", "plus", "team", "work", "care", "click",
})

# Known providers and brands, checked BEFORE the generic bucket. Without this a
# gmail.com row is "Global", which is true of the TLD and false of the account.
SEED_DOMAINS = {
    "gmail.com": "United States", "googlemail.com": "United States",
    "outlook.com": "United States", "hotmail.com": "United States",
    "live.com": "United States", "msn.com": "United States",
    "yahoo.com": "United States", "aol.com": "United States",
    "icloud.com": "United States", "me.com": "United States",
    "proton.me": "Switzerland", "protonmail.com": "Switzerland",
    "gmx.net": "Germany", "gmx.de": "Germany", "web.de": "Germany",
    "t-online.de": "Germany", "freenet.de": "Germany",
    "orange.fr": "France", "free.fr": "France", "laposte.net": "France",
    "libero.it": "Italy", "virgilio.it": "Italy",
    "mail.ru": "Russia", "yandex.ru": "Russia", "rambler.ru": "Russia",
    "qq.com": "China", "163.com": "China", "126.com": "China", "sina.com": "China",
    "naver.com": "South Korea", "daum.net": "South Korea",
    "seznam.cz": "Czechia", "wp.pl": "Poland", "o2.pl": "Poland",
    "interia.pl": "Poland", "onet.pl": "Poland",
    "abv.bg": "Bulgaria", "mail.bg": "Bulgaria",
    "ukr.net": "Ukraine", "i.ua": "Ukraine",
    "bigpond.com": "Australia", "optusnet.com.au": "Australia",
    "xtra.co.nz": "New Zealand",
    "shaw.ca": "Canada", "rogers.com": "Canada", "telus.net": "Canada",
    "uol.com.br": "Brazil", "bol.com.br": "Brazil", "terra.com.br": "Brazil",
    "yahoo.co.jp": "Japan", "docomo.ne.jp": "Japan", "ezweb.ne.jp": "Japan",
    "hanmail.net": "South Korea", "nate.com": "South Korea",
    "rediffmail.com": "India", "sify.com": "India",
    "btinternet.com": "United Kingdom", "sky.com": "United Kingdom",
    "virginmedia.com": "United Kingdom", "ntlworld.com": "United Kingdom",
    "talktalk.net": "United Kingdom",
}

CUSTOM_NAME = "domain_countries.json"
_CUSTOM = {"mtime": None, "map": {}}


def _custom_path() -> str:
    try:
        import auth
        return auth.user_file(CUSTOM_NAME)
    except Exception:
        return ""


def custom_map() -> dict:
    """The owner's domain -> country map, re-read when the file moves.

    Memoised on mtime, so a sort of 5000 rows is one stat and no re-read.
    """
    p = _custom_path()
    if not p:
        return dict(_CUSTOM["map"])
    try:
        mt = os.path.getmtime(p) if os.path.exists(p) else None
    except Exception:
        mt = None
    if _CUSTOM["mtime"] == mt and _CUSTOM["map"]:
        return dict(_CUSTOM["map"])
    out = {}
    try:
        if p and os.path.exists(p):
            with open(p, encoding="utf-8", errors="ignore") as fh:
                data = json.load(fh)
            if isinstance(data, dict):
                out = {str(k).strip().lower(): str(v).strip()
                       for k, v in data.items()
                       if str(k).strip() and str(v).strip()}
    except Exception:
        out = dict(_CUSTOM["map"])
    _CUSTOM["mtime"] = mt
    _CUSTOM["map"] = out
    return dict(out)


def custom_save(mapping) -> int:
    """Write the map back. Returns how many entries are stored."""
    p = _custom_path()
    clean = {str(k).strip().lower(): str(v).strip()
             for k, v in (mapping or {}).items()
             if str(k).strip() and str(v).strip()}
    if p:
        try:
            os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
            tmp = p + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(clean, fh, indent=2, sort_keys=True)
            os.replace(tmp, p)
        except Exception:
            pass
    _CUSTOM["mtime"] = None
    _CUSTOM["map"] = clean
    return len(clean)


def learn(domain, country) -> int:
    """Teach one domain, or clear it when `country` is empty. New map size."""
    d = (domain or "").strip().lower().lstrip("@")
    if d.startswith("www."):
        d = d[4:]
    cur = custom_map()
    if not d:
        return len(cur)
    if country:
        cur[d] = str(country).strip()
    else:
        cur.pop(d, None)
    return custom_save(cur)


def _tlds_of(domain) -> tuple:
    """(full domain, two-label tail, single tld). Any may be empty."""
    d = (domain or "").strip().lower().rstrip(".")
    if not d or "." not in d:
        return d, "", ""
    parts = d.split(".")
    two = ".".join(parts[-2:]) if len(parts) >= 2 else ""
    return d, two, parts[-1]


def country_of(domain) -> str:
    """Country for a domain, in this order - never a guess from a gTLD.

      1. the owner's own map, which always wins
      2. the seed map (free mail and big brands)
      3. a real ccTLD, including two-label ones like co.uk
      4. a generic TLD -> the Global bucket
      5. anything else -> unknown

    Never raises.
    """
    full, two, tld = _tlds_of(domain)
    if not full:
        return NO_COUNTRY
    cur = custom_map()
    if full in cur:
        return cur[full]
    if two and two in cur:
        return cur[two]
    if full in SEED_DOMAINS:
        return SEED_DOMAINS[full]
    if two and two in _TLD_COUNTRY:
        return _TLD_COUNTRY[two]
    if tld in GENERIC_TLDS:
        return COUNTRY_GENERIC
    if tld in _TLD_COUNTRY:
        return _TLD_COUNTRY[tld]
    return NO_COUNTRY


def region_of(domain) -> str:
    """Region for a domain. A Global-bucket country is its own region."""
    c = country_of(domain)
    if c == COUNTRY_GENERIC:
        return REGION_GENERIC
    if c == NO_COUNTRY:
        return NO_REGION
    return _REGION_OF.get(c, NO_REGION)


SORT_KEYS = {
    "Domain (after the @)": lambda r: (r.get("domain") or "(none)").lower(),
    "Status (the verdict)": lambda r: (r.get("status") or "UNKNOWN").upper(),
    "TLD": lambda r: _tld(r.get("domain")),
    "Country (from the domain TLD)": lambda r: country_of(r.get("domain")),
    "Region (from the domain TLD)": lambda r: region_of(r.get("domain")),
    "Mail host": lambda r: (r.get("host") or "(no host)").lower(),
    "Keyword (from a keyword hit)": lambda r: _kw(r.get("detail")) or "(no keyword)",
    "Folder (from a keyword hit)": lambda r: _folder(r.get("detail")) or "(no folder)",
    "Password length band": lambda r: _band(r.get("password")),
    "First letter of the local part": lambda r: _first(r.get("local")),
    "Source": lambda r: (r.get("source") or "(unknown)"),
    "None - one single group": lambda r: "(all rows)",
}

KEY_LABELS = list(SORT_KEYS.keys())


def describe(label):
    """One line saying what the chosen grouping actually produces."""
    return {
        "Domain (after the @)": "One group per recipient domain - the usual choice.",
        "Status (the verdict)": "One group per verdict, so a whole verdict can go alone.",
        "TLD": "One group per top-level domain, e.g. every .de in one file.",
        "Country (from the domain TLD)": "One group per country. Your own domain map "
                                         "is read first, then known providers, then "
                                         "the TLD. A bare .com that nothing places "
                                         "lands in Global / gTLD, not in unknown.",
        "Region (from the domain TLD)": "One group per continent - Europe, Asia, "
                                        "Africa, the Americas, Oceania, the Middle "
                                        "East - plus a Global bucket for gTLDs.",
        "Mail host": "One group per resolved mail server.",
        "Keyword (from a keyword hit)": "One group per keyword that matched - only "
                                        "meaningful on keyword-hit rows.",
        "Folder (from a keyword hit)": "One group per folder a hit came from.",
        "Password length band": "Bands by password length.",
        "First letter of the local part": "A-Z buckets on the part before the @.",
        "Source": "One group per source file or bucket the row came from.",
        "None - one single group": "No grouping at all - one file, sorted by email.",
    }.get(label, "")


def safe_name(label, limit=48):
    """A group label -> a file-name fragment that cannot escape the directory."""
    s = re.sub(r"[^A-Za-z0-9._-]+", "_", str(label or "")).strip("._-")
    return (s or "group")[:limit]


def group_rows(rows, label, order="A-Z", dedupe=True, cap=CAP_DEFAULT):
    """(groups, dropped). groups is [(label, rows)], already ordered and capped.

    `dropped` counts rows cut by `cap`, so the page can say so instead of
    silently shipping a truncated file.
    """
    fn = SORT_KEYS.get(label)
    if fn is None:
        fn = SORT_KEYS["None - one single group"]
    buckets = {}
    for r in rows or []:
        try:
            key = fn(r)
        except Exception:
            key = "(error)"
        key = str(key or "(none)")
        buckets.setdefault(key, []).append(r)

    groups = []
    dropped = 0
    for key in buckets:
        bucket = buckets[key]
        if dedupe:
            seen = set()
            keep = []
            for r in bucket:
                em = (r.get("email") or "").lower()
                if em and em in seen:
                    continue
                seen.add(em)
                keep.append(r)
            bucket = keep
        try:
            cap = max(1, int(cap))
        except Exception:
            cap = CAP_DEFAULT
        if len(bucket) > cap:
            dropped += len(bucket) - cap
            bucket = bucket[:cap]
        bucket.sort(key=lambda r: (r.get("email") or "").lower())
        groups.append((key, bucket))

    if order == "Z-A":
        groups.sort(key=lambda g: g[0].lower(), reverse=True)
    elif order == "Largest group first":
        groups.sort(key=lambda g: (-len(g[1]), g[0].lower()))
    elif order == "Smallest group first":
        groups.sort(key=lambda g: (len(g[1]), g[0].lower()))
    elif order == "Strongest status first":
        groups.sort(key=lambda g: (-max((_RANK.get((r.get("status") or "").upper(), 0)
                                         for r in g[1]), default=0), g[0].lower()))
    else:
        groups.sort(key=lambda g: g[0].lower())
    return groups, dropped


_PASTE_RX = re.compile(r"^([^@\s:|]+)@([^@\s:|]+\.[A-Za-z]{2,})(?::(.*))?$")


def paste_rows(text, source="pasted"):
    """Pasted lines -> rows in the same shape the page builds. Never raises.

    Accepts `email`, `email:pass`, `email | pass`, `email | pass | TAG` and
    `email:pass@host:port`. A line that is not an address is skipped, so a
    half-pasted column still yields everything in it that is usable.
    """
    out, seen = [], set()
    for raw in str(text or "").splitlines():
        s = raw.strip().lstrip("\ufeff")
        if not s or s.startswith("#"):
            continue
        if " | " in s:
            s = s.partition(" | ")[0]
        elif "|" in s:
            s = s.partition("|")[0]
        s = s.strip().strip("\"'")
        m = _PASTE_RX.match(s)
        if not m:
            continue
        local, dom, pw = m.group(1), m.group(2).lower(), (m.group(3) or "").strip()
        email = "%s@%s" % (local, dom)
        if email.lower() in seen:
            continue
        seen.add(email.lower())
        out.append({"email": email, "password": pw, "domain": dom, "local": local,
                    "status": "UNKNOWN", "host": "", "port": "",
                    "detail": "pasted", "time": "", "n": 0, "source": source,
                    "line": "%s:%s" % (email, pw)})
    return out


def group_text(rows):
    """One group -> its text. The row line is the source of truth."""
    return "\n".join(str(r.get("line") or "") for r in rows)


def zip_groups(groups, ext="txt", prefix="sorted"):
    """Every group as one archive entry. Returns bytes.

    Entry names carry the row count and are de-duplicated, so two groups that
    normalise to the same file name cannot overwrite each other in the archive.
    """
    buf = io.BytesIO()
    used = {}
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for label, rows in groups:
            if not rows:
                continue
            base = safe_name(label)
            if base in used:
                used[base] += 1
                base = "%s_%d" % (base, used[base])
            else:
                used[base] = 1
            z.writestr("%s/%s_%d.%s" % (prefix, base, len(rows), ext),
                       group_text(rows) + "\n")
    return buf.getvalue()


def totals(groups):
    """(group_count, row_count)."""
    return len(groups), sum(len(r) for _l, r in groups)
