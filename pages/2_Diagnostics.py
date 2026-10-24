# @@BLOCK 000 FILE_HEADER deps=none
"""
pages/2_Diagnostics.py - engine / proxy / DNS diagnostics surface.

Read-only: every control here reads, probes or clears a cache. Nothing here
mutates a bucket.

NOTE: this page deliberately does NOT call set_page_config(). Importing app.py
runs its own call and Streamlit permits only one per script run.
"""

from __future__ import annotations

import importlib
import json
import os
import socket
import sys
import time
import html as _html

import streamlit as str_lit

PAGE_NAME = "Diagnostics"
PAGE_VERSION = "v13.40"
DIAG_TTL = 30.0
# @@END 000


# @@BLOCK 001 ENGINE_ACCESS deps=000
@str_lit.cache_resource(show_spinner=False)
def _engine():
    """Import app.py once per server process. Returns the module or the
    exception object so the page can degrade instead of crashing."""
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


def _state():
    mod = _engine()
    if isinstance(mod, BaseException):
        return {}
    s = getattr(mod, "STATE", None)
    if isinstance(s, dict):
        return s
    fn = getattr(mod, "_engine_state", None)
    if callable(fn):
        try:
            got = fn()
            if isinstance(got, dict):
                return got
        except Exception:
            pass
    return {}
# @@END 001


# @@BLOCK 002 PROTOCOLS_FROM_APP deps=001
def _protocols_from_app():
    """FIX v13.40.

    The old page read `ui_protocols` / `protocols`, which are raw WIDGET
    VALUES: they can be empty or stale before the first run. app.py actually
    publishes the ACTIVE list as CFG['PROTOCOLS']. Read that, then fall back.
    """
    candidates = []
    cfg = _eng("CFG", None)
    if isinstance(cfg, dict):
        candidates.append(cfg)
    st = _eng("STATE", None)
    if isinstance(st, dict):
        candidates.append(st)
    for src in candidates:
        for key in ("PROTOCOLS", "protocols"):
            val = src.get(key)
            if val:
                return tuple(val)
    direct = _eng("PROTOCOLS", None)
    if direct:
        return tuple(direct)
    return ("IMAP",)


def _protocols_source():
    cfg = _eng("CFG", None)
    if isinstance(cfg, dict) and cfg.get("PROTOCOLS"):
        return "CFG['PROTOCOLS']"
    if _eng("PROTOCOLS", None):
        return "module PROTOCOLS"
    return "fallback (IMAP only)"
# @@END 002


# @@BLOCK 003 SMALL_HELPERS deps=001
def _bucket_rows():
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


def _count(bucket):
    return sum(1 for b, _r in _bucket_rows() if b == bucket)


def _kv_table(pairs, headers=("Key", "Value")):
    if not pairs:
        str_lit.caption("Nothing to show.")
        return
    head = "".join("<th style='text-align:left;padding:4px 10px;'>%s</th>" % _html.escape(h) for h in headers)
    body = "".join(
        "<tr><td style='padding:4px 10px;'>%s</td><td style='padding:4px 10px;'>%s</td></tr>"
        % (_html.escape(str(a)), _html.escape(str(b)))
        for a, b in pairs
    )
    str_lit.markdown(
        "<table style='width:100%%;border-collapse:collapse;font-size:13px;'>"
        "<thead><tr>%s</tr></thead><tbody>%s</tbody></table>" % (head, body),
        unsafe_allow_html=True,
    )


def _fmt_bytes(n):
    try:
        n = float(n)
    except Exception:
        return str(n)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return "%.1f %s" % (n, unit)
        n /= 1024.0
    return "%.1f GB" % n
# @@END 003


# @@BLOCK 004 CSS deps=000
def _css():
    str_lit.markdown(
        """
        <style>
        .dx-hero{background:linear-gradient(135deg,#0f172a,#1e293b);
                 border:1px solid #334155;border-radius:14px;
                 padding:16px 20px;margin-bottom:12px;}
        .dx-hero h1{margin:0;font-size:22px;color:#e2e8f0;}
        .dx-hero p{margin:4px 0 0;font-size:13px;color:#94a3b8;}
        .dx-card{background:#0f172a;border:1px solid #1e293b;border-radius:12px;
                 padding:12px 14px;margin-bottom:10px;}
        .dx-card h3{margin:0 0 6px;font-size:14px;color:#cbd5e1;}
        .dx-note{font-size:12px;color:#94a3b8;}
        </style>
        """,
        unsafe_allow_html=True,
    )
# @@END 004


# @@BLOCK 005 HERO deps=004
def _hero():
    if not _ok():
        str_lit.error("Engine import failed: %r" % (_engine(),))
        return
    _css()
    str_lit.markdown(
        "<div class='dx-hero'><h1>Diagnostics</h1>"
        "<p>Engine surface, proxy pool, DNS cache and the classifier self-test. "
        "Read-only.</p></div>",
        unsafe_allow_html=True,
    )
# @@END 005


# @@BLOCK 006 SUMMARY_METRICS deps=003
def _summary():
    st = _state()
    rows = _bucket_rows()
    cols = str_lit.columns(5)
    cols[0].metric("Accounts in session", len(rows))
    cols[1].metric("Valid", _count("valid"))
    cols[2].metric("Wrong", _count("wrong"))
    cols[3].metric("Blocked", _count("blocked"))
    cols[4].metric("State keys", len(st))
    str_lit.caption(
        "Protocols source: %s | protocols=%s"
        % (_protocols_source(), ", ".join(_protocols_from_app()))
    )
# @@END 006


# @@BLOCK 007 DIAG_TEXT deps=001
def _diag_text(force=False):
    st = _state()
    cache = st.get("diag_cache")
    now = time.time()
    if (
        not force
        and isinstance(cache, dict)
        and cache.get("text")
        and (now - float(cache.get("ts", 0.0))) < DIAG_TTL
    ):
        return cache["text"], float(cache.get("ts", 0.0)), True

    builder = _eng("build_diagnostics_text", None)
    if callable(builder):
        try:
            text = builder()
        except Exception as exc:  # noqa: BLE001
            text = "build_diagnostics_text() raised: %r" % (exc,)
    else:
        text = "build_diagnostics_text() not found on engine."

    try:
        st["diag_cache"] = {"text": text, "ts": now}
    except Exception:
        pass
    return text, now, False
# @@END 007


# @@BLOCK 008 DIAG_EXPANDER deps=007
def _diag_panel():
    c1, c2, c3 = str_lit.columns([1, 1, 3])
    force = c1.button("Rebuild", key="dx_rebuild")
    selftest = c2.button("Self-test", key="dx_selftest")
    text, ts, cached = _diag_text(force=force)
    c3.caption(
        "cached %.0fs ago (TTL %.0fs)" % (time.time() - ts, DIAG_TTL)
        if cached
        else "fresh"
    )
    with str_lit.expander("Engine diagnostics bundle", expanded=False):
        str_lit.code(text or "(empty)", language="text")

    if selftest:
        mod = sys.modules.get("status")
        if mod is None:
            try:
                mod = importlib.import_module("status")
            except Exception as exc:  # noqa: BLE001
                str_lit.error("status.py import failed: %r" % (exc,))
                return
        fn = getattr(mod, "selftest", None)
        if not callable(fn):
            str_lit.warning("status.selftest() missing.")
            return
        results = fn()
        bad = [r for r in results if not r[1]]
        if bad:
            for name, _okay, detail in bad:
                str_lit.error("%s -> %s" % (name, detail))
        else:
            str_lit.success("status.selftest(): %d/%d passed." % (len(results), len(results)))
# @@END 008


# @@BLOCK 009 PROXY_TABLE deps=003
def _proxy_table():
    st = _state()
    meta = st.get("proxy_meta")
    if not isinstance(meta, dict):
        meta = _eng("proxy_meta", None) or {}
    if not meta:
        str_lit.info("No proxy_meta in session yet - start a run first.")
        return
    pairs = []
    for node, info in sorted(meta.items()):
        if isinstance(info, dict):
            summary = ", ".join(
                "%s=%s" % (k, info.get(k))
                for k in ("status", "fails", "407s", "cooldown_until", "last_used")
                if k in info
            )
            pairs.append((node, summary or json.dumps(info, default=str)[:160]))
        else:
            pairs.append((node, info))
    str_lit.markdown("<div class='dx-card'><h3>Proxy nodes (%d)</h3></div>" % len(pairs), unsafe_allow_html=True)
    _kv_table(pairs, ("Node", "State"))
# @@END 009


# @@BLOCK 010 POOL_DNS_VIEW deps=003
def _pool_view():
    st = _state()
    alive = st.get("alive_pool") or _eng("alive_pool", None) or []
    dns = st.get("dns_cache") or _eng("dns_cache", None) or {}
    c1, c2 = str_lit.columns(2)
    with c1:
        str_lit.markdown("**Alive pool**")
        str_lit.caption("%d node(s) currently marked alive." % len(list(alive)))
        if alive:
            str_lit.code("\n".join(str(x) for x in list(alive)[:40]), language="text")
    with c2:
        str_lit.markdown("**DNS cache**")
        str_lit.caption("%d host(s) cached." % len(dns))
        if isinstance(dns, dict) and dns:
            _kv_table(list(dns.items())[:40], ("Host", "Resolved"))
# @@END 010


# @@BLOCK 011 SELF_TEST deps=002
def _connectivity():
    with str_lit.expander("Egress + DNS probe", expanded=False):
        host = str_lit.text_input("Host to probe", value="imap.gmail.com", key="dx_probe_host")
        port = str_lit.number_input("Port", value=993, min_value=1, max_value=65535, key="dx_probe_port")
        if str_lit.button("Probe", key="dx_probe_go"):
            t0 = time.time()
            try:
                ip = socket.gethostbyname(host)
                dns_ms = (time.time() - t0) * 1000.0
                str_lit.success("DNS %s -> %s (%.0f ms)" % (host, ip, dns_ms))
            except Exception as exc:  # noqa: BLE001
                str_lit.error("DNS failed for %s: %r" % (host, exc))
                return
            t1 = time.time()
            try:
                with socket.create_connection((host, int(port)), timeout=8):
                    str_lit.success("TCP %s:%d open (%.0f ms)" % (host, port, (time.time() - t1) * 1000.0))
            except Exception as exc:  # noqa: BLE001
                str_lit.warning("TCP %s:%d failed: %r" % (host, port, exc))
        str_lit.caption(
            "Egress IP hint: %s" % (_eng("EGRESS_IP", "unknown"))
        )
# @@END 011


# @@BLOCK 012 FOOTER deps=005
def main():
    _hero()
    if not _ok():
        return
    _summary()
    str_lit.divider()
    _diag_panel()
    str_lit.divider()
    _proxy_table()
    str_lit.divider()
    _pool_view()
    str_lit.divider()
    _connectivity()
    str_lit.caption("Diagnostics %s" % PAGE_VERSION)


main()
# @@END 012
