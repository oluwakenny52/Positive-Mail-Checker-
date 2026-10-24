# @@BLOCK 000 FILE_HEADER deps=none
"""
pages/3_Mailbox_Reader.py - read a mailbox for any account in any bucket.

FIX v13.40: _VALID_CACHE / _ZIP_CACHE / _B64_MEMO used to be MODULE GLOBALS,
so every rerun reset them and the whole ZIP was rebuilt on every click. They
now live in a single session_state holder. Raw bytes are no longer stored in
the session payload - only base64 strings - so the session stays small.
"""

from __future__ import annotations

import base64
import importlib
import io
import os
import sys
import time
import zipfile
import html as _html

import streamlit as str_lit

PAGE_NAME = "Mailbox Reader"
PAGE_VERSION = "v13.40"
READ_LIMIT_DEFAULT = 25
ZIP_MAX_ENTRIES = 400
# @@END 000


# @@BLOCK 001 ENGINE_ACCESS deps=000
@str_lit.cache_resource(show_spinner=False)
def _engine():
    mod = sys.modules.get("app")
    if mod is not None:
        return mod
    try:
        return importlib.import_module("app")
    except Exception as exc:  # noqa: BLE001
        return exc


def _ok():
    return not isinstance(_engine(), BaseException)


def _eng(name, default=None):
    if not _ok():
        return default
    return getattr(_engine(), name, default)
# @@END 001


# @@BLOCK 002 SESSION_CACHES deps=001
CACHE_KEY = "_mr_cache"


def _cache():
    """Single session_state-backed holder. Survives reruns and page switches."""
    ss = str_lit.session_state
    holder = ss.get(CACHE_KEY)
    if not isinstance(holder, dict):
        holder = {"valid": {}, "zip": {}, "b64": {}, "order": []}
        ss[CACHE_KEY] = holder
    holder.setdefault("valid", {})
    holder.setdefault("zip", {})
    holder.setdefault("b64", {})
    holder.setdefault("order", [])
    return holder


def _cache_get(kind, key):
    return _cache()[kind].get(key)


def _cache_put(kind, key, value):
    holder = _cache()
    holder[kind][key] = value
    holder["order"].append((kind, key, time.time()))
    if len(holder["order"]) > 500:
        _cache_trim()


def _cache_trim():
    holder = _cache()
    keep = holder["order"][-300:]
    holder["order"] = keep
    allowed = {}
    for kind, key, _ts in keep:
        allowed.setdefault(kind, set()).add(key)
    for kind in ("valid", "zip", "b64"):
        for key in list(holder[kind].keys()):
            if key not in allowed.get(kind, set()):
                holder[kind].pop(key, None)


def _clear_cache():
    str_lit.session_state[CACHE_KEY] = {"valid": {}, "zip": {}, "b64": {}, "order": []}
# @@END 002


# @@BLOCK 003 SMALL_HELPERS deps=002
def _rows():
    """(bucket, row) for every *_results list in session_state."""
    out = []
    try:
        items = list(str_lit.session_state.items())
    except Exception:
        return out
    for key, val in items:
        if not isinstance(key, str) or not key.endswith("_results"):
            continue
        if not isinstance(val, list):
            continue
        bucket = key[: -len("_results")]
        for row in val:
            if isinstance(row, dict):
                out.append((bucket, row))
    return out


def _row_key(bucket, row):
    email = row.get("email") or row.get("user") or row.get("username") or ""
    host = row.get("host") or row.get("imap_host") or row.get("server") or ""
    return "%s|%s|%s" % (bucket, email, host)


def _pick(row, *names, default=""):
    for n in names:
        v = row.get(n)
        if v not in (None, ""):
            return v
    return default


def _human(n):
    try:
        n = float(n)
    except Exception:
        return str(n)
    for unit in ("B", "KB", "MB"):
        if n < 1024:
            return "%.1f %s" % (n, unit)
        n /= 1024.0
    return "%.1f MB" % n


def _safe_name(name, fallback="file"):
    keep = []
    for ch in str(name or fallback):
        keep.append(ch if (ch.isalnum() or ch in "._-@") else "_")
    out = "".join(keep).strip("._") or fallback
    return out[:120]
# @@END 003


# @@BLOCK 004 CSS deps=000
def _css():
    str_lit.markdown(
        """
        <style>
        .mr-hero{background:linear-gradient(135deg,#0b1220,#111c33);
                 border:1px solid #1e293b;border-radius:14px;
                 padding:14px 18px;margin-bottom:12px;}
        .mr-hero h1{margin:0;font-size:21px;color:#e2e8f0;}
        .mr-hero p{margin:4px 0 0;font-size:12px;color:#94a3b8;}
        .mr-msg{border-left:3px solid #334155;padding:6px 10px;margin:4px 0;
                background:#0b1220;border-radius:0 8px 8px 0;}
        .mr-msg b{color:#e2e8f0;font-size:13px;}
        .mr-msg span{color:#94a3b8;font-size:11px;}
        .mr-body{white-space:pre-wrap;font-family:ui-monospace,monospace;
                 font-size:12px;background:#0b1220;border:1px solid #1e293b;
                 border-radius:10px;padding:10px;max-height:420px;overflow:auto;}
        </style>
        """,
        unsafe_allow_html=True,
    )
# @@END 004


# @@BLOCK 005 HERO deps=004
def _hero():
    _css()
    if not _ok():
        str_lit.error("Engine import failed: %r" % (_engine(),))
        return
    str_lit.markdown(
        "<div class='mr-hero'><h1>Mailbox Reader</h1>"
        "<p>Read, filter and export the mailbox of any account in any bucket. "
        "Cached in-session, so switching pages no longer rebuilds anything.</p></div>",
        unsafe_allow_html=True,
    )
# @@END 005


# @@BLOCK 006 SOURCE_PICKER deps=003
def _sources():
    rows = _rows()
    buckets = []
    for bucket, _row in rows:
        if bucket not in buckets:
            buckets.append(bucket)
    buckets.sort(key=lambda b: (b != "valid", b))
    if not buckets:
        return None, []
    label = str_lit.selectbox(
        "Bucket",
        options=buckets,
        format_func=lambda b: "%s (%d)" % (b, sum(1 for x, _ in rows if x == b)),
        key="mr_bucket",
    )
    picked = [(b, r) for b, r in rows if b == label]
    return label, picked
# @@END 006


# @@BLOCK 007 ACCOUNT_TABLE deps=003
def _account_table(picked):
    if not picked:
        return []
    c1, c2 = str_lit.columns([3, 1])
    needle = c1.text_input("Filter accounts", key="mr_filter").strip().lower()
    only_unread = c2.checkbox("Unread only", value=False, key="mr_unread")
    out = []
    for bucket, row in picked:
        email = str(_pick(row, "email", "user", "username", "login")).lower()
        if needle and needle not in email:
            continue
        if only_unread and row.get("read"):
            continue
        out.append((bucket, row))
    str_lit.caption("%d of %d account(s)" % (len(out), len(picked)))
    return out
# @@END 007


# @@BLOCK 008 SELECT_ACCOUNT deps=007
def _select_account(rows):
    if not rows:
        return None
    labels = []
    for bucket, row in rows:
        email = _pick(row, "email", "user", "username", "login", default="(no email)")
        status = _pick(row, "status", "verdict", default="?")
        labels.append("[%s] %s - %s" % (bucket, email, status))
    idx = str_lit.selectbox(
        "Account",
        options=list(range(len(labels))),
        format_func=lambda i: labels[i],
        key="mr_account",
    )
    return rows[idx][1]
# @@END 008


# @@BLOCK 009 READ_MAILBOX deps=002
def _read(account, limit):
    key = "%s|%s|%s|%s" % (
        _pick(account, "email", "user", "username", "login"),
        _pick(account, "host", "imap_host", "server"),
        _pick(account, "port", default=""),
        limit,
    )
    cached = _cache_get("valid", key)
    if cached is not None:
        return cached

    fn = _eng("read_mailbox", None)
    if not callable(fn):
        result = {"messages": [], "error": "engine.read_mailbox() not found"}
        _cache_put("valid", key, result)
        return result

    for call in (
        lambda: fn(account, limit=limit),
        lambda: fn(account, limit),
        lambda: fn(account),
    ):
        try:
            got = call()
            if isinstance(got, dict):
                _cache_put("valid", key, got)
                return got
            if isinstance(got, list):
                result = {"messages": got}
                _cache_put("valid", key, result)
                return result
        except TypeError:
            continue
        except Exception as exc:  # noqa: BLE001
            result = {"messages": [], "error": repr(exc)}
            _cache_put("valid", key, result)
            return result

    result = {"messages": [], "error": "read_mailbox() signature mismatch"}
    _cache_put("valid", key, result)
    return result
# @@END 009


# @@BLOCK 010 MESSAGE_INDEX deps_009
def _messages(payload):
    msgs = payload.get("messages") if isinstance(payload, dict) else None
    if not isinstance(msgs, list):
        return []
    out = []
    for i, m in enumerate(msgs):
        if isinstance(m, dict):
            out.append(m)
        else:
            out.append({"index": i, "subject": str(m)})
    return out


def _msg_label(m, i):
    subject = _pick(m, "subject", "title", default="(no subject)")
    sender = _pick(m, "from", "sender", "from_addr", default="?")
    date = _pick(m, "date", "received", default="")
    return "%02d  %s  |  %s  |  %s" % (i + 1, date[:19], sender[:28], subject[:60])
# @@END 010


# @@BLOCK 011 SELECT_MESSAGE deps=010
def _select_message(msgs):
    if not msgs:
        return None, []
    needle = str_lit.text_input("Search messages", key="mr_msg_search").strip().lower()
    idxs = list(range(len(msgs)))
    if needle:
        idxs = [
            i
            for i in idxs
            if needle
            in (
                _pick(msgs[i], "subject", "title", default="")
                + " "
                + _pick(msgs[i], "from", "sender", default="")
                + " "
                + _pick(msgs[i], "body", "text", default="")
            ).lower()
        ]
    if not idxs:
        str_lit.info("No message matches the search.")
        return None, []
    pick = str_lit.selectbox(
        "Message",
        options=idxs,
        format_func=lambda i: _msg_label(msgs[i], i),
        key="mr_msg",
    )
    return pick, idxs
# @@END 011


# @@BLOCK 012 BODY_RENDER deps=011
def _render_message(m):
    if not isinstance(m, dict):
        str_lit.code(str(m), language="text")
        return
    head = [
        ("From", _pick(m, "from", "sender", "from_addr", default="?")),
        ("To", _pick(m, "to", "recipient", default="?")),
        ("Date", _pick(m, "date", "received", default="?")),
        ("Subject", _pick(m, "subject", "title", default="(no subject)")),
    ]
    for k, v in head:
        str_lit.markdown("**%s:** %s" % (k, _html.escape(str(v))))
    body = _pick(m, "body", "text", "html", "raw", default="")
    if not body:
        str_lit.caption("(empty body)")
        return
    str_lit.markdown("<div class='mr-body'>%s</div>" % _html.escape(str(body)[:20000]), unsafe_allow_html=True)
# @@END 012


# @@BLOCK 013 ATTACHMENT_INDEX deps=012
def _attachments(m):
    atts = m.get("attachments") if isinstance(m, dict) else None
    if not isinstance(atts, list):
        return []
    out = []
    for i, a in enumerate(atts):
        if isinstance(a, dict):
            out.append(
                {
                    "index": i,
                    "filename": _pick(a, "filename", "name", default="attachment_%d" % i),
                    "size": _pick(a, "size", "len", default=0),
                    "payload": a.get("payload") or a.get("data"),
                    "mime": _pick(a, "mime", "content_type", default="application/octet-stream"),
                }
            )
        else:
            out.append({"index": i, "filename": "attachment_%d" % i, "size": 0, "payload": a})
    return out


def _attachment_table(atts):
    if not atts:
        return []
    rows = []
    for a in atts:
        rows.append(
            (a["index"], a["filename"], _human(a["size"]), a.get("mime", ""))
        )
    head = "<tr><th>#</th><th>Name</th><th>Size</th><th>Type</th></tr>"
    body = "".join(
        "<tr><td>%d</td><td>%s</td><td>%s</td><td>%s</td></tr>"
        % (i, _html.escape(str(n)), s, _html.escape(str(t)))
        for i, n, s, t in rows
    )
    str_lit.markdown(
        "<table style='width:100%%;font-size:12px;border-collapse:collapse;'>%s%s</table>"
        % (head, body),
        unsafe_allow_html=True,
    )
    return atts
# @@END 013


# @@BLOCK 014 ATTACHMENT_FETCH deps=013
def _fetch_attachment(account, message, att, as_bytes=False):
    if att.get("payload"):
        raw = att["payload"]
        if isinstance(raw, str):
            try:
                return base64.b64decode(raw)
            except Exception:
                return raw.encode("utf-8", "replace")
        if isinstance(raw, (bytes, bytearray)):
            return bytes(raw)
        return str(raw).encode("utf-8", "replace")

    fn = _eng("fetch_attachment", None)
    if not callable(fn):
        return b""
    for call in (
        lambda: fn(account, message, att.get("index", 0)),
        lambda: fn(account, message, att),
        lambda: fn(account, att),
    ):
        try:
            got = call()
            if isinstance(got, str):
                try:
                    return base64.b64decode(got)
                except Exception:
                    return got.encode("utf-8", "replace")
            if isinstance(got, (bytes, bytearray)):
                return bytes(got)
        except TypeError:
            continue
        except Exception:
            return b""
    return b""
# @@END 014


# @@BLOCK 015 B64_MEMO deps=002
def _b64_of(account, message, att, raw):
    """Memoised base64. Session payload stores the STRING, not the bytes."""
    key = "%s|%s|%s" % (
        _pick(account, "email", "user", "username", "login"),
        _pick(message, "uid", "id", "index", default=""),
        att.get("filename", "?"),
    )
    got = _cache_get("b64", key)
    if isinstance(got, str):
        return got
    try:
        enc = base64.b64encode(raw or b"").decode("ascii")
    except Exception:
        enc = ""
    _cache_put("b64", key, enc)
    return enc
# @@END 015


# @@BLOCK 016 ZIP_BUILD deps=015
def _zip_signature(entries):
    return "|".join(sorted("%s:%s" % (name, len(enc)) for name, enc in entries))


def _build_zip(entries):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        used = set()
        for name, enc in entries:
            safe = _safe_name(name)
            if safe in used:
                stem, dot, ext = safe.rpartition(".")
                n = 2
                while safe in used:
                    safe = "%s_%d%s%s" % (stem, n, dot, ext) if dot else "%s_%d" % (stem, n)
                    n += 1
            used.add(safe)
            try:
                zf.writestr(safe, base64.b64decode(enc))
            except Exception:
                zf.writestr(safe, b"")
    return buf.getvalue()
# @@END 016


# @@BLOCK 017 ZIP_CACHE deps=016
def _zip_for(account, atts, raws):
    entries = []
    for att, raw in zip(atts, raws):
        entries.append((att.get("filename", "attachment"), _b64_of(account, att, att, raw)))
    if not entries:
        return b""
    sig = _zip_signature(entries)
    cached = _cache_get("zip", sig)
    if isinstance(cached, (bytes, bytearray)) and cached:
        return bytes(cached)
    data = _build_zip(entries)
    _cache_put("zip", sig, data)
    return data
# @@END 017


# @@BLOCK 018 DOWNLOAD_BAR deps_017
def _downloads(account, message, atts):
    if not atts:
        return
    c1, c2 = str_lit.columns([1, 1])
    idx = c1.selectbox(
        "Attachment",
        options=list(range(len(atts))),
        format_func=lambda i: "%s (%s)" % (atts[i]["filename"], _human(atts[i]["size"])),
        key="mr_att",
    )
    chosen = atts[idx]
    if c2.button("Fetch", key="mr_fetch"):
        str_lit.session_state["mr_last_att"] = idx

    raws = []
    for a in atts:
        raws.append(_fetch_attachment(account, message, a))

    payload = raws[idx] if idx < len(raws) else b""
    c1.download_button(
        "Download this",
        data=payload or b"",
        file_name=_safe_name(chosen["filename"]),
        mime=chosen.get("mime", "application/octet-stream"),
        key="mr_dl_one",
    )
    zip_bytes = _zip_for(account, atts, raws)
    c2.download_button(
        "Download all (.zip)",
        data=zip_bytes or b"",
        file_name="%s_attachments.zip" % _safe_name(_pick(account, "email", default="mailbox")),
        mime="application/zip",
        key="mr_dl_zip",
    )
# @@END 018


# @@BLOCK 019 SEARCH_FILTER deps_002
def _toolbar():
    c1, c2, c3 = str_lit.columns([1, 1, 2])
    limit = c1.number_input(
        "Messages", min_value=1, max_value=500, value=READ_LIMIT_DEFAULT, key="mr_limit"
    )
    if c2.button("Reload", key="mr_reload"):
        holder = _cache()
        holder["valid"] = {}
        holder["zip"] = {}
        holder["b64"] = {}
        holder["order"] = []
    c3.caption(
        "cached mailboxes: %d | cached zips: %d | cached parts: %d"
        % (
            len(_cache()["valid"]),
            len(_cache()["zip"]),
            len(_cache()["b64"]),
        )
    )
    return int(limit)
# @@END 019


# @@BLOCK 020 STATS_ACTIONS deps_003
def _stats(account, msgs):
    if not account:
        return
    c1, c2, c3, c4 = str_lit.columns(4)
    c1.metric("Messages", len(msgs))
    c2.metric("With attachments", sum(1 for m in msgs if m.get("attachments")))
    total = 0
    for m in msgs:
        for a in (m.get("attachments") or []):
            if isinstance(a, dict):
                try:
                    total += int(a.get("size") or 0)
                except Exception:
                    pass
    c3.metric("Attachment bytes", _human(total))
    c4.metric("Host", str(_pick(account, "host", "imap_host", "server", default="?"))[:18])
# @@END 020


# @@BLOCK 021 FOOTER deps=005
def main():
    _hero()
    if not _ok():
        return
    bucket, picked = _sources()
    if not picked:
        str_lit.info("No results in this session yet. Run the checker first.")
        str_lit.caption("Mailbox Reader %s" % PAGE_VERSION)
        return

    rows = _account_table(picked)
    account = _select_account(rows)
    if account is None:
        str_lit.warning("No account selected.")
        return

    limit = _toolbar()
    payload = _read(account, limit)
    if isinstance(payload, dict) and payload.get("error"):
        str_lit.warning(str(payload["error"]))
    msgs = _messages(payload)
    _stats(account, msgs)

    if not msgs:
        str_lit.info("Mailbox is empty or could not be read.")
        return

    pick, _idxs = _select_message(msgs)
    if pick is None:
        return
    message = msgs[pick]
    _render_message(message)
    atts = _attachment_table(_attachments(message))
    _downloads(account, message, atts)
    str_lit.caption("Mailbox Reader %s" % PAGE_VERSION)


main()
# @@END 021
