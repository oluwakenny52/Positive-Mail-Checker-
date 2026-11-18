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
"""

import re
import zipfile
import io

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


SORT_KEYS = {
    "Domain (after the @)": lambda r: (r.get("domain") or "(none)").lower(),
    "Status (the verdict)": lambda r: (r.get("status") or "UNKNOWN").upper(),
    "TLD": lambda r: _tld(r.get("domain")),
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
