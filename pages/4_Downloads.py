# @@BLOCK 000 FILE_HEADER deps=none
"""
pages/4_Downloads.py - Export Studio.

Pick a source (session buckets or the mail_results files on disk), pick the
fields, pick the format, style it, preview it, download it. Presets are saved
in session_state so a shape you like is one click away.
"""

from __future__ import annotations

import csv
import io
import json
import os
import re
import sys
import time
import zipfile
import importlib
import datetime as _dt
import html as _html

import streamlit as str_lit

PAGE_NAME = "Export Studio"
PAGE_VERSION = "v13.40"

FIELD_ALIASES = {
    "email": ("email", "user", "username", "login", "account", "mail", "address"),
    "password": ("password", "pass", "pwd", "secret", "app_password"),
    "status": ("status", "verdict", "result", "state"),
    "host": ("host", "imap_host", "server", "imap_server"),
    "port": ("port", "imap_port"),
    "protocol": ("protocol", "proto", "service"),
    "bucket": ("bucket", "group", "category"),
    "note": ("note", "reason", "detail", "message", "error"),
    "checked_at": ("checked_at", "timestamp", "ts", "time", "date"),
    "proxy": ("proxy", "node", "egress", "ip"),
}

FIELDS = tuple(FIELD_ALIASES.keys())

TEMPLATES = {
    "email:password": "{email}:{password}",
    "email|password": "{email}|{password}",
    "email,password": "{email},{password}",
    "email;password": "{email};{password}",
    "email<TAB>password": "{email}\t{password}",
    "email password": "{email} {password}",
    "email only": "{email}",
    "email:password:status": "{email}:{password}:{status}",
    "email|password|host": "{email}|{password}|{host}",
    "CSV (email,password,status,host)": "{email},{password},{status},{host}",
}

LINE_ENDINGS = {"LF (\\n)": "\n", "CRLF (\\r\\n)": "\r\n", "CR (\\r)": "\r"}
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


# @@BLOCK 002 SOURCE_PICKER deps=001
def _session_rows():
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
                item = dict(row)
                item.setdefault("bucket", bucket)
                out.append(item)
    return out


def _results_dir():
    for name in ("MAIL_RESULTS_DIR", "RESULTS_DIR", "MAIL_DIR"):
        val = _eng(name, None)
        if isinstance(val, str) and val:
            return val
    return "mail_results"


def _disk_rows():
    """Parse the newest mail_results/*.txt group. Format: bucket lines then
    'email:password' or 'email|password' rows, tab-separated when extra
    columns are present."""
    root = _results_dir()
    if not os.path.isdir(root):
        return []
    files = []
    for name in os.listdir(root):
        if not name.endswith(".txt"):
            continue
        path = os.path.join(root, name)
        try:
            files.append((os.path.getmtime(path), path, name))
        except OSError:
            continue
    if not files:
        return []
    files.sort(reverse=True)
    newest_stamp = None
    picked = []
    for mtime, path, name in files:
        stamp = name.split("_", 1)[0]
        if newest_stamp is None:
            newest_stamp = stamp
        if stamp == newest_stamp:
            picked.append((path, name))
    rows = []
    for path, name in picked:
        bucket = name.split("_", 1)[-1].replace(".txt", "") or "results"
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    line = line.rstrip("\n").rstrip("\r")
                    if not line or line.startswith("#"):
                        continue
                    parts = line.split("\t")
                    email, _, pw = parts[0].partition(":")
                    if not _:
                        email, _, pw = parts[0].partition("|")
                    row = {"email": email, "password": pw, "bucket": bucket}
                    if len(parts) > 1 and not row["password"]:
                        row["password"] = parts[1]
                    if len(parts) > 2:
                        row["status"] = parts[2]
                    rows.append(row)
        except OSError:
            continue
    return rows


def _source_picker():
    mode = str_lit.radio(
        "Source",
        options=("Session results", "Disk (mail_results)"),
        horizontal=True,
        key="dx_source",
    )
    rows = _session_rows() if mode.startswith("Session") else _disk_rows()
    if not rows:
        return mode, rows
    buckets = sorted({r.get("bucket", "?") for r in rows})
    chosen = str_lit.multiselect("Buckets", options=buckets, default=buckets, key="dx_buckets")
    rows = [r for r in rows if r.get("bucket") in chosen]
    return mode, rows
# @@END 002


# @@BLOCK 003 FIELD_PICKER deps=000
def _value(row, field):
    for name in FIELD_ALIASES.get(field, (field,)):
        val = row.get(name)
        if val not in (None, ""):
            return str(val)
    return ""


def _field_picker():
    chosen = str_lit.multiselect(
        "Fields to include",
        options=list(FIELDS),
        default=["email", "password", "status"],
        key="dx_fields",
    )
    if not chosen:
        chosen = ["email", "password"]
    missing = []
    for field in chosen:
        if field == "bucket":
            continue
        if not any(any(k in row for k in FIELD_ALIASES[field]) for row in str_lit.session_state.get("_dx_probe", [])):
            pass
    return chosen


def _row_dict(row, fields):
    out = {}
    for field in fields:
        out[field] = _value(row, field)
    return out
# @@END 003


# @@BLOCK 004 FORMAT_TEMPLATE deps=000
def _format_picker():
    mode = str_lit.radio(
        "Output",
        options=("Template lines", "CSV", "JSON", "ZIP bundle"),
        horizontal=True,
        key="dx_mode",
    )
    template = None
    if mode == "Template lines":
        preset = str_lit.selectbox("Template", options=list(TEMPLATES.keys()), key="dx_template")
        template = str_lit.text_input("Custom template", value=TEMPLATES[preset], key="dx_template_custom")
        str_lit.caption(
            "Placeholders: " + ", ".join("{%s}" % f for f in FIELDS)
        )
    return mode, template
# @@END 004


# @@BLOCK 005 OPTIONS deps=000
def _options():
    c1, c2, c3 = str_lit.columns(3)
    delim_label = c1.selectbox("Delimiter (CSV)", options=(",", ";", "|", "\\t", "space"), key="dx_delim")
    delim = {"\\t": "\t", "space": " "}.get(delim_label, delim_label)
    eol_label = c2.selectbox("Line ending", options=list(LINE_ENDINGS.keys()), key="dx_eol")
    eol = LINE_ENDINGS[eol_label]
    sort_by = c3.selectbox("Sort by", options=("none",) + FIELDS, key="dx_sort")
    c1, c2, c3, c4 = str_lit.columns(4)
    dedupe = c1.checkbox("Dedupe", value=True, key="dx_dedupe")
    only_valid = c2.checkbox("Only status=VALID", value=False, key="dx_only_valid")
    include_header = c3.checkbox("CSV header", value=False, key="dx_header")
    stamp = c4.checkbox("Timestamp in name", value=True, key="dx_stamp")
    c1, c2 = str_lit.columns(2)
    keep = c1.text_input("Regex include", value="", key="dx_keep")
    drop = c2.text_input("Regex exclude", value="", key="dx_drop")
    c1, c2 = str_lit.columns([2, 1])
    stem = c1.text_input("Filename stem", value="export", key="dx_stem")
    c2.caption("Placeholders: {date} {time} {count} {bucket}")
    return {
        "delim": delim,
        "eol": eol,
        "sort": sort_by,
        "dedupe": dedupe,
        "only_valid": only_valid,
        "header": include_header,
        "stamp": stamp,
        "keep": keep,
        "drop": drop,
        "stem": stem or "export",
    }
# @@END 005


# @@BLOCK 006 PRESETS deps=005
PRESET_KEY = "_dx_presets"


def _presets():
    ss = str_lit.session_state
    store = ss.get(PRESET_KEY)
    if not isinstance(store, dict):
        store = {}
        ss[PRESET_KEY] = store
    c1, c2, c3 = str_lit.columns([2, 1, 1])
    name = c1.text_input("Preset name", value="", key="dx_preset_name")
    if c2.button("Save preset", key="dx_preset_save") and name:
        store[name] = {
            "fields": list(ss.get("dx_fields", [])),
            "template": ss.get("dx_template_custom", ""),
            "mode": ss.get("dx_mode", "Template lines"),
            "delim": ss.get("dx_delim", ","),
            "eol": ss.get("dx_eol", "LF (\\n)"),
            "stem": ss.get("dx_stem", "export"),
        }
        str_lit.toast("Preset '%s' saved." % name)
    if store:
        pick = c3.selectbox("Presets", options=["(none)"] + sorted(store), key="dx_preset_pick")
        if pick != "(none)":
            p = store[pick]
            ss["dx_fields"] = p.get("fields", [])
            ss["dx_template_custom"] = p.get("template", "")
            ss["dx_stem"] = p.get("stem", "export")
    return store
# @@END 006


# @@BLOCK 007 PREVIEW deps=003
def _apply_filters(rows, opts):
    out = rows
    if opts["only_valid"]:
        out = [r for r in out if _value(r, "status").upper() in ("VALID", "OK", "TRUE")]
    if opts["keep"]:
        try:
            rx = re.compile(opts["keep"])
            out = [r for r in out if rx.search(_value(r, "email") + " " + _value(r, "note"))]
        except re.error as exc:
            str_lit.warning("include regex: %s" % exc)
    if opts["drop"]:
        try:
            rx = re.compile(opts["drop"])
            out = [r for r in out if not rx.search(_value(r, "email") + " " + _value(r, "note"))]
        except re.error as exc:
            str_lit.warning("exclude regex: %s" % exc)
    if opts["sort"] != "none":
        out = sorted(out, key=lambda r: _value(r, opts["sort"]).lower())
    if opts["dedupe"]:
        seen = set()
        uniq = []
        for r in out:
            key = _value(r, "email").lower() + "\x00" + _value(r, "password")
            if key in seen:
                continue
            seen.add(key)
            uniq.append(r)
        out = uniq
    return out


def _render_lines(rows, fields, template):
    lines = []
    for row in rows:
        data = _row_dict(row, fields)
        try:
            lines.append(template.format(**{f: data.get(f, "") for f in FIELDS}))
        except Exception:
            lines.append(template)
    return lines


def _preview(rows, fields, mode, template, opts):
    if not rows:
        str_lit.info("Nothing to export after filters.")
        return []
    if mode == "Template lines":
        lines = _render_lines(rows, fields, template or "{email}:{password}")
    elif mode == "CSV":
        buf = io.StringIO()
        writer = csv.writer(buf, delimiter=opts["delim"], lineterminator=opts["eol"])
        if opts["header"]:
            writer.writerow(fields)
        for row in rows:
            writer.writerow([_value(row, f) for f in fields])
        lines = buf.getvalue().rstrip("\r\n").splitlines()
    elif mode == "JSON":
        payload = [_row_dict(r, fields) for r in rows]
        lines = json.dumps(payload, indent=2, ensure_ascii=False).splitlines()
    else:
        payload = [_row_dict(r, fields) for r in rows]
        lines = json.dumps(payload, indent=2, ensure_ascii=False).splitlines()
    str_lit.caption("%d row(s) ready." % len(rows))
    str_lit.code("\n".join(lines[:200]), language="text")
    return lines
# @@END 007


# @@BLOCK 008 BUILD_EXPORT deps_007
def _filename(opts, count, buckets):
    stem = opts["stem"]
    now = _dt.datetime.now()
    stem = stem.replace("{date}", now.strftime("%Y-%m-%d")).replace("{time}", now.strftime("%H-%M-%S"))
    stem = stem.replace("{count}", str(count)).replace("{bucket}", "-".join(sorted(buckets))[:40] or "all")
    if opts["stamp"]:
        stem = "%s_%s" % (stem, now.strftime("%Y-%m-%dT%H-%M"))
    return re.sub(r"[^A-Za-z0-9._-]+", "_", stem)[:120]


def _build_text(rows, fields, mode, template, opts):
    if mode == "Template lines":
        body = opts["eol"].join(_render_lines(rows, fields, template or "{email}:{password}"))
        return body + opts["eol"] if body else ""
    if mode == "CSV":
        buf = io.StringIO()
        writer = csv.writer(buf, delimiter=opts["delim"], lineterminator=opts["eol"])
        if opts["header"]:
            writer.writerow(fields)
        for row in rows:
            writer.writerow([_value(row, f) for f in fields])
        return buf.getvalue()
    payload = [_row_dict(r, fields) for r in rows]
    return json.dumps(payload, indent=2, ensure_ascii=False) + opts["eol"]


def _build_zip(rows, fields, mode, template, opts):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        by_bucket = {}
        for row in rows:
            by_bucket.setdefault(row.get("bucket", "all"), []).append(row)
        for bucket, group in by_bucket.items():
            name = "%s_%s.txt" % (_filename(opts, len(group), [bucket]), bucket)
            body = _build_text(group, fields, mode if mode != "ZIP bundle" else "Template lines", template, opts)
            zf.writestr(re.sub(r"[^A-Za-z0-9._-]+", "_", name), body)
        payload = [_row_dict(r, fields) for r in rows]
        zf.writestr("all.json", json.dumps(payload, indent=2, ensure_ascii=False))
    return buf.getvalue()
# @@END 008


# @@BLOCK 009 STATS_ACTIONS deps=008
def _stats(rows):
    c1, c2, c3, c4 = str_lit.columns(4)
    c1.metric("Rows", len(rows))
    c2.metric("Unique emails", len({_value(r, "email").lower() for r in rows}))
    c3.metric("Buckets", len({r.get("bucket", "?") for r in rows}))
    c4.metric(
        "With password",
        sum(1 for r in rows if _value(r, "password")),
    )
# @@END 009


# @@BLOCK 010 FOOTER deps=005
def main():
    str_lit.markdown(
        "<div class='dx-hero'><h1>Export Studio</h1>"
        "<p>Choose what to download, how it is shaped, and how it is named.</p></div>",
        unsafe_allow_html=True,
    )
    if not _ok():
        str_lit.warning("Engine not importable - running on session_state only.")

    mode_src, rows = _source_picker()
    if not rows:
        str_lit.info("No rows found in %s." % mode_src)
        str_lit.caption("Export Studio %s" % PAGE_VERSION)
        return

    fields = _field_picker()
    mode, template = _format_picker()
    opts = _options()
    _presets()
    filtered = _apply_filters(rows, opts)
    _stats(filtered)
    _preview(filtered, fields, mode, template, opts)

    if not filtered:
        return

    base = _filename(opts, len(filtered), {r.get("bucket", "?") for r in filtered})
    c1, c2, c3 = str_lit.columns(3)

    if mode == "ZIP bundle":
        data = _build_zip(filtered, fields, mode, template, opts)
        c1.download_button(
            "Download ZIP",
            data=data,
            file_name="%s.zip" % base,
            mime="application/zip",
            key="dx_dl_zip",
        )
    else:
        body = _build_text(filtered, fields, mode, template, opts)
        ext = {"CSV": "csv", "JSON": "json"}.get(mode, "txt")
        mime = {"CSV": "text/csv", "JSON": "application/json"}.get(mode, "text/plain")
        c1.download_button(
            "Download %s" % ext.upper(),
            data=body.encode("utf-8"),
            file_name="%s.%s" % (base, ext),
            mime=mime,
            key="dx_dl_main",
        )

    if c2.button("Copy preview", key="dx_copy"):
        str_lit.session_state["dx_clip"] = _build_text(filtered, fields, "Template lines", template, opts)
    if str_lit.session_state.get("dx_clip"):
        c2.caption("copied to dx_clip")
    if c3.button("Clear caches", key="dx_clear"):
        for key in ("_mr_cache", "_dx_probe"):
            str_lit.session_state.pop(key, None)
        str_lit.toast("Caches cleared.")
    str_lit.caption("Export Studio %s" % PAGE_VERSION)


main()
# @@END 010
