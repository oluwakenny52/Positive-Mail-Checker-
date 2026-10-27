# @@FILE pages/4_Downloads.py blocks=16 version=v13.40
# @@BLOCK 000 FILE_HEADER deps=-
"""
pages/4_Downloads.py — Bobito Export Studio  (v13.40)
=====================================================
Pick WHAT to download, pick HOW it is written, preview it, take it.

Pure reader: no mailbox connection, no proxy credit. Sources are the result
files the checker already wrote, plus the live session buckets.
"""

import os
import re
import io
import csv
import json
import glob
import zipfile
from datetime import datetime

import streamlit as st
# @@END 000 FILE_HEADER


# @@BLOCK 001 PAGE_CONFIG deps=000
st.set_page_config(
    page_title="Export Studio · Downloads",
    page_icon="📦",
    layout="wide",
    initial_sidebar_state="collapsed",
)
# @@END 001 PAGE_CONFIG


# @@BLOCK 002 APP_PATHS deps=000
APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRESET_FILE = os.path.join(APP_DIR, "download_presets.json")
# @@END 002 APP_PATHS


# @@BLOCK 003 THEME deps=002
# --------------------------------------------------------------------------
# theme mirror
# --------------------------------------------------------------------------
def _load_theme():
    base = {"bg": "#0b1020", "panel": "#141b30", "text": "#e6ebff",
            "accent": "#8b5cf6", "accent2": "#22d3ee", "g1": "#667eea", "g2": "#764ba2"}
    for cand in (os.path.join(APP_DIR, "theme.json"), "theme.json"):
        try:
            if os.path.exists(cand):
                with open(cand, encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    base.update({k: v for k, v in data.items()
                                 if k in base and isinstance(v, str)})
                break
        except Exception:
            continue
    return base


_TH = _load_theme()
# @@END 003 THEME


# @@BLOCK 004 CSS deps=003
st.markdown(
    f"""
<style>
    .stApp, [data-testid="stAppViewContainer"] {{ background: {_TH['bg']}; color: {_TH['text']}; }}
    h1, h2, h3, h4 {{ color: {_TH['text']} !important; }}
    [data-testid="stSidebar"] {{ background: {_TH['panel']}; }}
    [data-testid="stSidebar"] p, [data-testid="stSidebar"] label,
    [data-testid="stSidebar"] span {{ color: {_TH['text']}; }}
    .ex-hero {{
        background: linear-gradient(135deg, {_TH['g1']} 0%, {_TH['g2']} 100%);
        padding: 18px 24px; border-radius: 14px; margin-bottom: 14px;
        border: 1px solid rgba(255,255,255,.12);
    }}
    .ex-hero h1 {{ color: #fff !important; margin: 0; font-size: 1.5rem; font-weight: 800; }}
    .ex-hero p {{ color: rgba(255,255,255,.92) !important; margin: 6px 0 0 0; font-size: .85rem; }}
    code, pre, [data-testid="stCodeBlock"] {{
        background: {_TH['bg']} !important; color: {_TH['accent2']} !important;
        border: 1px solid rgba(255,255,255,.10) !important; border-radius: 10px !important;
    }}
    [data-testid="stMetric"] {{
        background: {_TH['panel']}; border: 1px solid rgba(255,255,255,.10);
        border-left: 4px solid {_TH['accent']}; border-radius: 12px; padding: 10px 12px;
    }}
    .block-container {{ padding-top: 1.2rem !important; padding-bottom: 2rem !important; }}
    @media (max-width: 820px) {{
        .block-container {{ padding: .55rem .7rem 1.3rem .7rem !important; }}
        .ex-hero {{ padding: 12px 14px; }}
        .ex-hero h1 {{ font-size: 1.15rem; }}
        .ex-hero p {{ font-size: .74rem; }}
        [data-testid="stMetricValue"] {{ font-size: 1.05rem !important; }}
        [data-testid="stMetricLabel"] {{ font-size: .6rem !important; }}
        pre, code {{ font-size: .68rem !important; }}
    }}
</style>
""",
    unsafe_allow_html=True,
)
# @@END 004 CSS


# @@BLOCK 005 HERO deps=004
st.markdown(
    '<div class="ex-hero"><h1>📦 Export Studio</h1>'
    '<p>Choose what to download, choose the exact format, preview it, take it. '
    'No mailbox connection, no proxy credit spent.</p></div>',
    unsafe_allow_html=True,
)
# @@END 005 HERO


# @@BLOCK 006 SOURCE_TABLES deps=002
# --------------------------------------------------------------------------
# sources
# --------------------------------------------------------------------------
IGNORE = {
    "last_account.txt", "proxies.txt", "proxies_all.txt", "disposable_domains.txt",
    "clean_proxies.txt", "proxy_pool.txt", "download_presets.json",
}
IGNORE_TOKENS = ("resume", "unfinished", "remaining", "input", "proxies", "proxy", "config")


def _status_of(path):
    n = os.path.basename(path).lower()
    if "clean_valid" in n or "manual_valid" in n or "valid_accounts" in n:
        return "VALID"
    for tag, word in (("VALID", "valid"), ("WRONG_PASSWORD", "wrong"),
                      ("NEED_APP_PASSWORD", "need_app"), ("LOGIN_DROPPED", "login_dropped"),
                      ("CONNECTION_FAILED", "failed"), ("PROXY_UNHEALTHY", "proxy_unhealthy"),
                      ("RETRY_LATER", "retry_later"), ("RBL_BLOCKED", "rbl_blocked"),
                      ("SMTP_FAILED", "smtp_failed"), ("DNS_FAILED", "dns_failed"),
                      ("SKIPPED", "skipped"), ("UNKNOWN", "unclassified")):
        if word in n:
            return tag
    return "MIXED"


def _sources():
    out = {}
    for pat in ("mail_results/*.txt", "*.txt"):
        for p in glob.glob(os.path.join(APP_DIR, pat)):
            b = os.path.basename(p)
            if b in IGNORE or any(t in b.lower() for t in IGNORE_TOKENS):
                continue
            try:
                with open(p, encoding="utf-8", errors="ignore") as _fh:
                    n = sum(1 for l in _fh if l.strip() and not l.startswith("#"))
            except Exception:
                n = 0
            if n:
                out[f"{os.path.basename(os.path.dirname(p))}/{b}  ({n})"] = p
    return dict(sorted(out.items()))


SESSION_BUCKETS = [
    ("Session · valid_results", "valid_results", "VALID"),
    ("Session · wrong_results", "wrong_results", "WRONG_PASSWORD"),
    ("Session · need_app_results", "need_app_results", "NEED_APP_PASSWORD"),
    ("Session · login_drop_results", "login_drop_results", "LOGIN_DROPPED"),
    ("Session · conn_results", "conn_results", "CONNECTION_FAILED"),
    ("Session · proxy_results", "proxy_results", "PROXY_UNHEALTHY"),
    ("Session · retry_results", "retry_results", "RETRY_LATER"),
    ("Session · rbl_results", "rbl_results", "RBL_BLOCKED"),
    ("Session · skip_results", "skip_results", "SKIPPED"),
    ("Session · unknown_results", "unknown_results", "UNKNOWN"),
]


def _session_sources():
    out = {}
    for label, key, _tag in SESSION_BUCKETS:
        items = st.session_state.get(key) or []
        if items:
            out[f"{label}  ({len(items)})"] = key
    return out


FIELDS = ["email", "password", "domain", "local", "status", "host", "port",
          "detail", "time", "n", "source"]

FORMAT_PRESETS = {
    "email:password": "{email}:{password}",
    "email|password": "{email}|{password}",
    "email;password": "{email};{password}",
    "email,password (csv row)": "{email},{password}",
    "user:pass@host:port": "{email}:{password}@{host}:{port}",
    "host:port:user:pass": "{host}:{port}:{email}:{password}",
    "email:password:host:port": "{email}:{password}:{host}:{port}",
    "email only": "{email}",
    "email|password|status": "{email}|{password}|{status}",
    "full annotated": "{n} | {email}:{password} | {status} | {host}:{port} | {detail}",
    "CUSTOM": "",
}
# @@END 006 SOURCE_TABLES


# @@BLOCK 007 PARSERS deps=006
def _parse(line, source, status_hint):
    raw = line.rstrip("\n")
    if not raw.strip() or raw.startswith("#"):
        return None
    if " | " in raw:
        combo, _, rest = raw.partition(" | ")
    elif "|" in raw:
        # v13.42: anchor the cut to the FIRST colon, so a '|' before the colon
        # cannot eat the email and the split is deterministic.
        _colon = raw.find(":")
        _cut = raw.find("|", _colon + 1) if _colon != -1 else -1
        combo, rest = (raw[:_cut], raw[_cut + 1:]) if _cut != -1 else (raw, "")
    else:
        combo, rest = raw, ""
    combo = combo.strip().strip('"\'')
    if ":" not in combo:
        return None
    email, _, pw = combo.partition(":")
    email = email.strip()
    if "@" not in email:
        return None
    local, _, dom = email.partition("@")
    detail = rest.strip()
    host = port = ""
    m = re.search(r"([a-z0-9][a-z0-9.\-]*\.[a-z]{2,}):(\d{2,5})", detail, re.I)
    if m:
        host, port = m.group(1), m.group(2)
    st_tag = status_hint
    tm = re.search(r"\b([A-Z_]{4,})\b", detail)
    if status_hint == "MIXED" and tm:
        st_tag = tm.group(1)
    return {
        "email": email, "password": pw.strip(), "domain": dom.lower(),
        "local": local, "status": st_tag, "host": host, "port": port,
        "detail": detail, "time": "", "n": 0, "source": source,
        "line": raw,
    }


def _load(selection):
    rows = []
    srcs = _sources()
    sess = _session_sources()
    for label in selection:
        if label in sess:
            key = sess[label]
            tag = dict((l, t) for l, _k, t in SESSION_BUCKETS).get(label, "MIXED")
            for ln in st.session_state.get(key) or []:
                r = _parse(str(ln), label, tag)
                if r:
                    rows.append(r)
        elif label in srcs:
            p = srcs[label]
            tag = _status_of(p)
            try:
                with open(p, encoding="utf-8", errors="ignore") as fh:
                    for ln in fh:
                        r = _parse(ln, os.path.basename(p), tag)
                        if r:
                            rows.append(r)
            except Exception as ex:
                st.warning(f"{label}: {ex}")
    return rows
# @@END 007 PARSERS


# @@BLOCK 008 FORMATTERS deps=007
def _fmt(rows, template, delim, crlf, header, prefix, suffix,
         sort_key, dedupe, lower, regex_inc, regex_exc, host_filter):
    sel = rows
    if dedupe:
        seen, keep = set(), []
        for r in sel:
            if r["email"] in seen:
                continue
            seen.add(r["email"])
            keep.append(r)
        sel = keep
    if regex_inc:
        try:
            rx = re.compile(regex_inc)
            sel = [r for r in sel if rx.search(r["line"])]
        except re.error as e:
            st.warning(f"include regex: {e}")
    if regex_exc:
        try:
            rx = re.compile(regex_exc)
            sel = [r for r in sel if not rx.search(r["line"])]
        except re.error as e:
            st.warning(f"exclude regex: {e}")
    if host_filter.strip():
        want = {h.strip().lower() for h in host_filter.split(",") if h.strip()}
        sel = [r for r in sel if r["host"].lower() in want]

    if sort_key == "email":
        sel = sorted(sel, key=lambda r: r["email"])
    elif sort_key == "domain":
        sel = sorted(sel, key=lambda r: (r["domain"], r["email"]))
    elif sort_key == "status":
        sel = sorted(sel, key=lambda r: (r["status"], r["email"]))

    out = []
    for i, r in enumerate(sel, 1):
        r["n"] = i
        e = r["email"].lower() if lower else r["email"]
        d = dict(r)
        d["email"] = e
        try:
            line = template.format(**d)
        except KeyError as ke:
            line = r["line"]
            st.session_state["_fmt_bad"] = str(ke)
        if delim != " " and " " not in template:
            line = line.replace(" ", delim)
        out.append(line)

    text = ("\n" if not crlf else "\r\n").join(out)
    if header.strip():
        text = header + ("\n" if not crlf else "\r\n") + text
    if prefix.strip():
        text = prefix + ("\n" if not crlf else "\r\n") + text
    if suffix.strip():
        text = text + ("\n" if not crlf else "\r\n") + suffix
    return sel, text


def _csv_of(rows, sep):
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=sep, lineterminator="\n")
    w.writerow(["email", "password", "domain", "status", "host", "port", "detail"])
    for r in rows:
        w.writerow([r["email"], r["password"], r["domain"], r["status"],
                    r["host"], r["port"], r["detail"]])
    return buf.getvalue()


def _json_of(rows, lines=True):
    if lines:
        return "\n".join(json.dumps({k: r[k] for k in
                                     ("email", "password", "domain", "status", "host", "port", "detail")})
                         for r in rows)
    return json.dumps([{k: r[k] for k in
                        ("email", "password", "domain", "status", "host", "port", "detail")}
                       for r in rows], indent=2)
# @@END 008 FORMATTERS


# @@BLOCK 009 PRESETS_IO deps=002
def _presets():
    try:
        if os.path.exists(PRESET_FILE):
            with open(PRESET_FILE, encoding="utf-8") as f:
                return json.load(f) or {}
    except Exception:
        pass
    return {}


def _save_presets(d):
    try:
        with open(PRESET_FILE, "w", encoding="utf-8") as f:
            json.dump(d, f, indent=2)
    except Exception:
        pass
# @@END 009 PRESETS_IO


# @@BLOCK 010 SIDEBAR deps=006
# --------------------------------------------------------------------------
# sidebar — source + format
# --------------------------------------------------------------------------
srcs = _sources()
sess = _session_sources()

# v13.40: consume a pending preset HERE, before a single widget exists.
# SessionState.__setitem__ raises StreamlitWidgetAlreadyInstantiatedError if you
# write a widget key AFTER that widget was created in the same run - which is
# exactly what block 011 used to do, so Apply threw and the boxes never updated.
_pending_preset = st.session_state.pop("_ex_apply", None)
if _pending_preset:
    _pp = _presets().get(_pending_preset) or {}
    if _pp:
        st.session_state["ex_tpl"] = _pp.get("template", "{email}:{password}")
        st.session_state["ex_delim"] = _pp.get("delim", "none")
        st.session_state["ex_eol"] = _pp.get("eol", "LF (unix)")
        st.session_state["ex_header"] = _pp.get("header", "")
        st.session_state["ex_prefix"] = _pp.get("prefix", "")
        st.session_state["ex_suffix"] = _pp.get("suffix", "")
        st.session_state["ex_sort"] = _pp.get("sort", "none")
        st.session_state["ex_dedupe"] = bool(_pp.get("dedupe", True))
        st.session_state["ex_lower"] = bool(_pp.get("lower", True))
        st.session_state["ex_name"] = _pp.get("name_pat", "export_{status}_{count}_{stamp}")
        st.session_state["_ex_active"] = _pending_preset

with st.sidebar:
    st.markdown("### 1. What to download")
    labels = list(sess.keys()) + list(srcs.keys())
    if not labels:
        st.info("No result files yet. Run the checker, or validate a batch in the Reader.")
        st.stop()
    picked = st.multiselect("Sources", labels, default=labels[:1])

    st.markdown("---")
    st.markdown("### 2. How to write it")
    fmt_name = st.selectbox("Format", list(FORMAT_PRESETS.keys()), index=0)
    default_tpl = FORMAT_PRESETS[fmt_name]
    template = st.text_input(
        "Template ({email} {password} {domain} {local} {status} {host} {port} {detail} {n})",
        value=default_tpl or "{email}:{password}",
        key="ex_tpl",
    )
    if fmt_name == "CUSTOM" and not template.strip():
        template = "{email}:{password}"

    delim = st.selectbox("Separator inside a line", ["none", "tab", "comma", "semicolon", "pipe"],
                         index=0, key="ex_delim",
                         help="'none' keeps the template exactly as written.")
    _delim_map = {"none": " ", "tab": "\t", "comma": ",", "semicolon": ";", "pipe": "|"}
    delim_ch = _delim_map[delim]

    eol = st.radio("Line ending", ["LF (unix)", "CRLF (windows)"], horizontal=True, key="ex_eol")
    crlf = eol.startswith("CRLF")

    header = st.text_input("Header line (optional)", value="", key="ex_header")
    prefix = st.text_input("Prefix line (optional)", value="", key="ex_prefix")
    suffix = st.text_input("Suffix line (optional)", value="", key="ex_suffix")

    st.markdown("---")
    st.markdown("### 3. Filter and order")
    sort_key = st.selectbox("Sort by", ["none", "email", "domain", "status"], index=0, key="ex_sort")
    dedupe = st.toggle("Dedupe by email (first wins)", value=True, key="ex_dedupe")
    lower = st.toggle("Lowercase email", value=True, key="ex_lower")
    regex_inc = st.text_input("Include regex", value="")
    regex_exc = st.text_input("Exclude regex", value="")
    host_filter = st.text_input("Only these hosts (comma)", value="")

    st.markdown("---")
    st.markdown("### 4. File name")
    name_pat = st.text_input("Name pattern",
                             value="export_{status}_{count}_{stamp}",
                             key="ex_name",
                             help="{status} {count} {stamp} {sources} are substituted.")

    st.markdown("---")
    st.markdown("### 5. Presets")
    _ps = _presets()
    pname = st.text_input("Preset name", value="")
    c1, c2 = st.columns(2)
    with c1:
        if st.button("Save preset", use_container_width=True) and pname.strip():
            _ps[pname.strip()] = {"template": template, "delim": delim, "eol": eol,
                                  "header": header, "prefix": prefix, "suffix": suffix,
                                  "sort": sort_key, "dedupe": dedupe, "lower": lower,
                                  "sources": picked, "name_pat": name_pat}
            _save_presets(_ps)
            st.success(f"Saved '{pname.strip()}'")
    with c2:
        if _ps:
            p_use = st.selectbox("Load preset", ["--"] + sorted(_ps.keys()))
            if p_use != "--" and st.button("Apply", use_container_width=True):
                st.session_state["_ex_apply"] = p_use
                st.rerun()
# @@END 010 SIDEBAR


# @@BLOCK 011 PRESET_APPLY deps=010
# Block 010 already seeded every preset-backed widget key BEFORE those widgets
# were created - the only point where writing a widget key is legal.  So the
# values read out of the widgets above already carry the preset; this block just
# mirrors the preset into the locals block 012 consumes, and consumes the
# one-shot marker so a later rerun does not clobber your manual edits.
_p = _presets().get(st.session_state.pop("_ex_active", None) or "") or {}
if _p:
    template = _p.get("template", template)
    delim = _p.get("delim", delim)
    delim_ch = _delim_map[delim]
    crlf = str(_p.get("eol", eol)).startswith("CRLF")
    header = _p.get("header", header)
    prefix = _p.get("prefix", prefix)
    suffix = _p.get("suffix", suffix)
    sort_key = _p.get("sort", sort_key)
    dedupe = _p.get("dedupe", dedupe)
    lower = _p.get("lower", lower)
    name_pat = _p.get("name_pat", name_pat)
    picked = [s for s in _p.get("sources", picked) if s in labels] or picked
# @@END 011 PRESET_APPLY


# @@BLOCK 012 BUILD deps=011
# --------------------------------------------------------------------------
# build
# --------------------------------------------------------------------------
rows = _load(picked)
sel, text = _fmt(rows, template, delim_ch, crlf, header, prefix, suffix,
                 sort_key, dedupe, lower, regex_inc, regex_exc, host_filter)

stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
fname = (name_pat.replace("{stamp}", stamp)
         .replace("{count}", str(len(sel)))
         .replace("{status}", "mixed" if len(picked) != 1 else _status_of(picked[0]).lower())
         .replace("{sources}", str(len(picked))))
if "." not in os.path.basename(fname):
    fname += ".txt"

m1, m2, m3, m4 = st.columns(4)
m1.metric("Sources picked", len(picked))
m2.metric("Rows read", len(rows))
m3.metric("Rows exported", len(sel))
m4.metric("Bytes", f"{len(text.encode('utf-8')):,}")

if st.session_state.get("_fmt_bad"):
    st.warning(f"Unknown placeholder in the template: {st.session_state.pop('_fmt_bad')} "
               f"- valid ones are {', '.join('{'+f+'}' for f in FIELDS)}")

if not sel:
    st.info("Nothing matched. Widen the sources or clear a filter.")
    st.stop()

st.markdown("#### Preview (first 60 lines)")
st.code("\n".join(text.splitlines()[:60]) or "(empty)", language="text")

st.download_button(
    f"⬇️ Download {fname}",
    data=text.encode("utf-8"),
    file_name=fname,
    mime="text/plain",
    type="primary",
    use_container_width=True,
)
# @@END 012 BUILD


# @@BLOCK 013 TABS deps=012
tab_txt, tab_csv, tab_json, tab_zip, tab_break = st.tabs(
    ["Text / template", "CSV", "JSON", "ZIP (all formats)", "Per-status split"]
)

with tab_txt:
    st.caption("Exactly what the download button produces. The copy icon is top-right.")
    st.code(text, language="text")

with tab_csv:
    sep_choice = st.radio("CSV separator", ["comma", "semicolon", "tab"], horizontal=True)
    _sep = {"comma": ",", "semicolon": ";", "tab": "\t"}[sep_choice]
    ctext = _csv_of(sel, _sep)
    st.download_button("⬇️ Download CSV", data=ctext.encode("utf-8"),
                       file_name=fname.rsplit(".", 1)[0] + ".csv",
                       mime="text/csv", use_container_width=True)
    st.code("\n".join(ctext.splitlines()[:30]), language="text")

with tab_json:
    jl = st.toggle("JSON Lines (one object per row)", value=True)
    jtext = _json_of(sel, lines=jl)
    st.download_button("⬇️ Download JSON", data=jtext.encode("utf-8"),
                       file_name=fname.rsplit(".", 1)[0] + (".jsonl" if jl else ".json"),
                       mime="application/json", use_container_width=True)
    st.code("\n".join(jtext.splitlines()[:30]), language="text")

with tab_zip:
    st.caption("One archive containing the template file, CSV, JSON and a per-status split.")
    if st.button("Build ZIP", type="primary"):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr(fname, text)
            z.writestr(fname.rsplit(".", 1)[0] + ".csv", _csv_of(sel, ","))
            z.writestr(fname.rsplit(".", 1)[0] + ".json", _json_of(sel, lines=False))
            by = {}
            for r in sel:
                by.setdefault(r["status"], []).append(r)
            for tag, group in by.items():
                z.writestr(f"{tag}_{len(group)}.txt",
                           "\n".join(g["line"] for g in group))
        st.download_button("⬇️ Download ZIP", data=buf.getvalue(),
                           file_name=fname.rsplit(".", 1)[0] + ".zip",
                           mime="application/zip", use_container_width=True)

with tab_break:
    by = {}
    for r in sel:
        by.setdefault(r["status"], []).append(r)
    for tag in sorted(by):
        with st.expander(f"{tag} — {len(by[tag])} row(s)"):
            body = "\n".join(r["line"] for r in by[tag])
            st.download_button(f"⬇️ {tag}.txt", data=body.encode("utf-8"),
                               file_name=f"{tag}_{len(by[tag])}.txt",
                               mime="text/plain", key=f"dl_{tag}")
            st.code(body, language="text")
# @@END 013 TABS


# @@BLOCK 014 FOOTER deps=013
st.markdown("---")
try:
    st.page_link("app.py", label="← Back to the Mail Checker")
except Exception:
    st.caption("The main checker lives at app.py")
# @@END 014 FOOTER


# @@BLOCK 015 TRAILING deps=014
# (reserved tail - keeps the file closed after the last block)
# @@END 015 TRAILING
# @@EOF
