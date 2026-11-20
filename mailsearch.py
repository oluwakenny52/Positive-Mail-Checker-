"""mailsearch.py - keyword search over ONE already-verified mailbox.

PLAIN MODULE, like runstate.py: no @@BLOCK frame, no gate rows, nothing to
renumber. app.py block 109 imports it and passes in a connection that has
already been through verify_and_connect(), so every search rides the same
proxy-backed, post-auth verified session the Mailbox Reader uses and this module
never has to know how to log in, how to proxy, or how to pick a host.

WHAT IT DOES, and in this order, because it is the cheapest order:

  1. SELECT the folder READ-ONLY, so no \Seen flag is touched anywhere.
  2. SEARCH ALL and take the newest `scan_limit` ids. The window is bounded on
     purpose: a 40,000-message folder cannot be swept per keystroke.
  3. FETCH HEADERS ONLY in chunks and match the keywords against Subject + From.
  4. For each header match, fetch the body and keep the hit.
  5. Then a BODY pass over the newest `body_scan` ids that did not already hit,
     so a keyword that only appears in a body is still found - bounded, and
     reported as it goes.

Server-side SEARCH TEXT is deliberately not used: its quoting rules and its
notion of "text" differ between Dovecot, Exchange and Gmail, and a keyword with
a space in it breaks most of them. Headers-plus-body here behaves the same
everywhere.

Every function returns rather than raises. A search that dies half way still
returns the hits it already found, with the reason attached.

THE HIT CALLBACK
----------------
`on_hit(hit)` fires the moment a hit is COMPLETE - body read, counts worked out -
so a caller can store it as it lands instead of waiting for the whole pass. A
long scan over a big folder then shows progress per hit, and a scan that dies
half way has already handed over everything it found. It is optional and it is
called inside the same try as everything else, so a raising callback cannot take
the pass down.
"""

import os
import re
import time
from email import message_from_bytes as _mfb
from email.header import decode_header as _dh, make_header as _mh

MAX_SCAN = 200          # ids looked at per folder pass
MAX_BODY_SCAN = 120     # ids whose body is fetched on the body pass
MAX_HITS = 300          # hits kept per pass
BODY_CAP = 400000       # bytes of one message kept
BODY_SHOW = 200000      # characters of readable text kept per hit
_FETCH_CHUNK = 25
_MAX_KEYWORDS = 12


def _s(x):
    if isinstance(x, bytes):
        return x.decode("utf-8", errors="replace")
    return str(x or "")


def _unquote_folder(line):
    """`(\HasNoChildren) "/" "Sent Items"` -> `Sent Items`. Never raises."""
    m = re.search(r'"([^"]*)"\s*$', line or "")
    if m:
        return m.group(1)
    m = re.search(r'"[^"]*"\s+"?([^"]+)"?\s*$', line or "")
    return m.group(1).strip() if m else ""


def _keywords(words):
    """Free text -> a short, de-duplicated list. Commas, semicolons and newlines split."""
    out, seen = [], set()
    for w in re.split(r"[,\n;]+", words or ""):
        w = w.strip().strip('"').strip("'").strip()
        if not w or len(w) < 2:
            continue
        if w.lower() in seen:
            continue
        seen.add(w.lower())
        out.append(w)
    return out[:_MAX_KEYWORDS]


def list_folders(mail):
    """(folders, note). \\Noselect containers are dropped - they cannot be selected."""
    out = []
    try:
        typ, data = mail.list()
        if typ != "OK":
            return [], "the server would not list folders"
        for raw in (data or []):
            line = _s(raw).strip()
            if not line or "\\Noselect" in line:
                continue
            name = _unquote_folder(line)
            if name and name not in out:
                out.append(name)
        return out, ("" if out else "the server listed no selectable folder")
    except Exception as e:
        return [], f"{type(e).__name__}: {e}"


def _heads_from_bytes(payload):
    """Header block -> {subject, from, to, date}. Empty strings on any failure."""
    heads = {"subject": "", "from": "", "to": "", "date": ""}
    try:
        msg = _mfb(payload)
        for key in ("Subject", "From", "To", "Date"):
            value = msg.get(key) or ""
            if value:
                try:
                    value = str(_mh(_dh(value)))
                except Exception:
                    pass
            heads[key.lower()] = value.replace("\r", " ").replace("\n", " ").strip()
    except Exception:
        pass
    return heads


def _headers_of(mail, mid):
    """One message -> {subject, from, to, date}. Empty strings on any failure."""
    heads = {"subject": "", "from": "", "to": "", "date": ""}
    try:
        typ, data = mail.fetch(mid, "(BODY.PEEK[HEADER.FIELDS (SUBJECT FROM TO DATE)])")
        if typ != "OK":
            return heads
        for rp in (data or []):
            if isinstance(rp, tuple) and rp[1]:
                return _heads_from_bytes(rp[1])
    except Exception:
        pass
    return heads


def _fetch_headers(mail, ids):
    """Chunked header fetch -> {str(mid): heads}. One FETCH per _FETCH_CHUNK ids.

    THE CHUNKING WAS A LIE. _FETCH_CHUNK was declared and the loop then fetched
    one id at a time, so a 200-id window was 200 round trips per folder pass. A
    set is fetched in one command here; the server answers one tuple per message,
    prefixed with its id. Any id that comes back unparsed - a pedantic server, a
    partial answer - falls back to its own single fetch, so the optimisation can
    only ever cost a round trip, never a message.
    """
    out = {}
    ids = list(ids)
    for i in range(0, len(ids), _FETCH_CHUNK):
        part = ids[i:i + _FETCH_CHUNK]
        got = {}
        try:
            typ, data = mail.fetch(
                ",".join(_s(x) for x in part),
                "(BODY.PEEK[HEADER.FIELDS (SUBJECT FROM TO DATE)])")
            if typ == "OK":
                for rp in (data or []):
                    if not isinstance(rp, tuple) or not rp[1]:
                        continue
                    m = re.match(rb"(\d+)", rp[0] or b"")
                    if m:
                        got[_s(m.group(1))] = _heads_from_bytes(rp[1])
        except Exception:
            got = {}
        for mid in part:
            out[_s(mid)] = got.get(_s(mid)) or _headers_of(mail, mid)
    return out


def _raw_of(mail, mid):
    try:
        typ, data = mail.fetch(mid, "(BODY.PEEK[])")
        if typ == "OK" and data:
            for rp in (data or []):
                if isinstance(rp, tuple) and rp[1]:
                    return rp[1][:BODY_CAP]
    except Exception:
        pass
    try:
        typ, data = mail.fetch(mid, "(BODY.PEEK[TEXT])")
        if typ == "OK" and data:
            for rp in (data or []):
                if isinstance(rp, tuple) and rp[1]:
                    return rp[1][:BODY_CAP]
    except Exception:
        pass
    return b""


def _readable(raw):
    """Raw MIME -> readable text. Never raises, never returns bytes."""
    if not raw:
        return ""
    text, markup = "", ""
    try:
        msg = _mfb(raw)
        parts = list(msg.walk()) if msg.is_multipart() else [msg]
        for part in parts:
            if part.get_content_maintype() == "multipart":
                continue
            ctype = (part.get_content_type() or "").lower()
            try:
                payload = part.get_payload(decode=True) or b""
            except Exception:
                payload = b""
            if not payload:
                continue
            charset = part.get_content_charset() or "utf-8"
            try:
                decoded = payload.decode(charset, errors="replace")
            except Exception:
                decoded = payload.decode("utf-8", errors="replace")
            if ctype == "text/plain" and not text:
                text = decoded
            elif ctype == "text/html" and not markup:
                markup = decoded
    except Exception:
        text = raw.decode("utf-8", errors="replace")
    if not text and markup:
        import html as _html
        stripped = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", markup)
        stripped = re.sub(r"(?is)<br\s*/?>|</p>|</div>|</tr>|</li>", "\n", stripped)
        stripped = re.sub(r"(?s)<[^>]+>", " ", stripped)
        text = _html.unescape(stripped)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text[:BODY_SHOW]


def _counts(blob, keywords):
    """{keyword: occurrences in blob}. Zero entries are dropped."""
    low = (blob or "").lower()
    out = {}
    for k in keywords or []:
        n = low.count(str(k).lower())
        if n:
            out[str(k)] = n
    return out


def _make_hit(mail, mid, folder, heads, keywords, where, raw=None, counts=None):
    """One hit. `raw` is reused when the caller already has the body bytes.

    `counts` is {keyword: occurrences} for this message, so the bucket line can
    say HOW MANY mails a keyword produced rather than only that one did.
    """
    if raw is None:
        raw = _raw_of(mail, mid)
    return {"id": _s(mid), "folder": folder,
            "subject": heads.get("subject") or "(no subject)",
            "from": heads.get("from") or "(unknown sender)",
            "to": heads.get("to") or "",
            "date": heads.get("date") or "(no date)",
            "keywords": list(keywords), "counts": dict(counts or {}),
            "where": where, "body": _readable(raw)}


FIELD_LABELS = ("Subject", "From", "To", "Body")
FIELDS_DEFAULT = ("subject", "from", "to", "body")


def _blob(heads, fields):
    """The header text a hit is matched against, from the chosen fields only."""
    out = []
    if "subject" in fields:
        out.append(heads.get("subject") or "")
    if "from" in fields:
        out.append(heads.get("from") or "")
    if "to" in fields:
        out.append(heads.get("to") or "")
    return " ".join(out).lower()


def search(mail, folder, words, scan_limit=MAX_SCAN, body_scan=MAX_BODY_SCAN,
           hit_limit=MAX_HITS, on_progress=None, fields=None, folders=None,
           on_trace=None, on_hit=None):
    """(hits, note). Never raises.

    `fields` is any of subject / from / to / body - the header blob is built
    from the chosen header fields and the body pass only runs when "body" is
    chosen. `folders` is a list; each is selected READ-ONLY in turn and the
    single `folder` is used when it is empty.

    `on_trace(level, step, detail)` is called on EVERY path, including the
    zero-hit ones, so a pass that finds nothing is still readable afterwards
    instead of looking like a pass that never ran.

    `on_hit(hit)` is called as each hit is completed, so a caller can store it
    while the pass is still running. A raising callback is swallowed.
    """
    hits = []
    kws = _keywords(words)
    _t = on_trace or (lambda *a: None)

    def _tick(done, total, phase):
        if on_progress is None:
            return
        try:
            on_progress(done, total, phase)
        except Exception:
            pass

    def _keep(hit):
        """Append and hand over in one place, so on_hit can never be forgotten."""
        hits.append(hit)
        if on_hit is not None:
            try:
                on_hit(hit)
            except Exception:
                pass
        return len(hits)

    if not kws:
        _t("WARN", "search", "no keyword given")
        return hits, "no keyword given"

    _fields = [str(f).lower() for f in (fields or FIELDS_DEFAULT)]
    _fields = [f for f in _fields if f in FIELDS_DEFAULT] or list(FIELDS_DEFAULT)
    _want_body = "body" in _fields
    _folders = [str(f).strip() for f in (folders or []) if str(f).strip()]
    if not _folders and folder:
        _folders = [str(folder)]
    if not _folders:
        _t("WARN", "search", "no folder selected")
        return hits, "no folder selected"

    _t("INFO", "search", "words %r, fields %s, folders %s, window %s"
       % (kws, ",".join(_fields), ",".join(_folders), scan_limit))

    try:
        for _f_i, _fname in enumerate(_folders, 1):
            if len(hits) >= hit_limit:
                break
            quoted = '"%s"' % _fname.replace('"', "")
            typ, _ = mail.select(quoted, readonly=True)
            if typ != "OK":
                _t("WARN", "folder", "%s refused by the server" % _fname)
                continue
            typ, data = mail.search(None, "ALL")
            if typ != "OK":
                _t("WARN", "folder", "%s could not be searched" % _fname)
                continue
            ids = (data[0].split() if data and data[0] else [])
            if not ids:
                _t("INFO", "folder", "%s is empty" % _fname)
                continue

            try:
                _limit = max(1, int(scan_limit))
            except Exception:
                _limit = MAX_SCAN
            window = ids[-_limit:]
            total = len(window)
            seen = set()
            _t("INFO", "folder", "%s: %d message(s) in the window"
               % (_fname, total))

            for i in range(0, len(window), _FETCH_CHUNK):
                part = window[i:i + _FETCH_CHUNK]
                got = _fetch_headers(mail, part)
                for mid in part:
                    heads = got.get(_s(mid)) or {"subject": "", "from": "",
                                                 "to": "", "date": ""}
                    blob = _blob(heads, _fields)
                    hit_kw = [k for k in kws if k.lower() in blob]
                    if hit_kw:
                        seen.add(_s(mid))
                        _keep(_make_hit(mail, mid, _fname, heads, hit_kw,
                                        "header", counts=_counts(blob, hit_kw)))
                        if len(hits) >= hit_limit:
                            break
                _tick(min(total, i + len(part)), total, "headers")
                if len(hits) >= hit_limit:
                    break

            if _want_body and len(hits) < hit_limit:
                try:
                    body_scan = max(0, int(body_scan))
                except Exception:
                    body_scan = MAX_BODY_SCAN
                for n, mid in enumerate(reversed(window)):
                    if n >= body_scan:
                        break
                    if _s(mid) in seen:
                        continue
                    raw = _raw_of(mail, mid)
                    low = _readable(raw).lower()
                    if not low:
                        continue
                    hit_kw = [k for k in kws if k.lower() in low]
                    if hit_kw:
                        heads = _headers_of(mail, mid)
                        _keep(_make_hit(mail, mid, _fname, heads, hit_kw,
                                        "body", raw=raw,
                                        counts=_counts(low, hit_kw)))
                        if len(hits) >= hit_limit:
                            break
                    if n and n % 10 == 0:
                        _tick(total, total, "bodies")
            _t("INFO", "folder", "%s done: %d hit(s) so far, %d/%d folder(s)"
               % (_fname, len(hits), _f_i, len(_folders)))

        _tick(1, 1, "done")
        if not hits:
            _t("INFO", "search", "zero hits - the keywords are not in the scanned "
                                 "window of %s" % ",".join(_folders))
            return hits, "no keyword matched in the scanned window"
        _t("INFO", "search", "%d hit(s) total" % len(hits))
        return hits, ""
    except Exception as e:
        _t("ERR", "search", "%s: %s" % (type(e).__name__, e))
        return hits, f"{type(e).__name__}: {e}"


def hit_line(hit):
    """One hit -> the bucket line. `email:password | ...`, so _raw_of() re-runs it.

    The combo comes first and alone before the first " | " on purpose: the
    re-run path cuts there, and every renderer shows only that much.
    """
    _kw = []
    _counts_ = hit.get("counts") or {}
    for _k in hit.get("keywords") or []:
        _n = int(_counts_.get(_k) or 0)
        _kw.append("%s(%d)" % (_k, _n) if _n else str(_k))
    return ("%s:%s | kw:%s | folder:%s | %s | %s"
            % (hit.get("email", ""), hit.get("password", ""), ",".join(_kw),
               hit.get("folder", ""), hit.get("where", ""),
               (hit.get("subject") or "")[:90]))


def save_bodies(directory, stamp, hits, max_files=MAX_HITS):
    """One .txt per hit plus an index, into `directory`. Returns (index, written).

    Bodies go to disk because session_state is the thing that gets a container
    killed. The bucket holds the combo; the file holds the message.
    """
    index, written = [], 0
    try:
        os.makedirs(directory, exist_ok=True)
    except Exception:
        return "", 0
    for n, hit in enumerate((hits or [])[:max_files], 1):
        slug = re.sub(r"[^A-Za-z0-9]+", "_", hit.get("email", "")).strip("_")[:40] or "acct"
        name = "%s_%03d_%s.txt" % (stamp, n, slug)
        body = ("Folder: %s\nFrom: %s\nDate: %s\nSubject: %s\nKeywords: %s\n"
                "Matched in: %s\n%s\n%s\n"
                % (hit.get("folder", ""), hit.get("from", ""), hit.get("date", ""),
                   hit.get("subject", ""), ", ".join(hit.get("keywords") or []),
                   hit.get("where", ""), "-" * 60, hit.get("body") or ""))
        try:
            with open(os.path.join(directory, name), "w", encoding="utf-8",
                      errors="replace") as f:
                f.write(body)
            written += 1
        except Exception:
            continue
        index.append("%s  |  %s  |  %s" % (name, ",".join(hit.get("keywords") or []),
                                          hit.get("where", "")))
    ipath = os.path.join(directory, "_index.txt")
    try:
        with open(ipath, "w", encoding="utf-8", errors="replace") as f:
            f.write("\n".join(index) + ("\n" if index else ""))
    except Exception:
        ipath = ""
    return ipath, written


def close(mail):
    """Log out, then hard-close if the logout failed. Never raises."""
    if mail is None:
        return
    try:
        mail.logout()
        return
    except Exception:
        pass
    try:
        mail.close()
    except Exception:
        pass
