# @@FILE pages/2_Diagnostics.py blocks=20 version=v13.40
# @@BLOCK 000 FILE_HEADER deps=-
"""
pages/2_Diagnostics.py — Mega Ultimate Mail Checker  (v13.40)
============================================================
Read-only inspection page. It answers three questions without spending a single
proxy credit or touching a mailbox:

  1. What EXACTLY will the engine dial for this domain?  (the real rung order,
     built with the same cap / apex / POP-selection logic app.py uses)
  2. Does the network actually answer?  (live TCP probes on 993/143/995/110)
  3. Is the resolution layer sane?  (family priority, dead-imap demotion,
     SRV / autoconfig / MX discovery sources, SMTP candidates, host cache)

Only real hosts.py functions are used:
    conf, discover_hosts, resolve_mx, resolve_srv, host_resolves, is_junk_host,
    host_tier, probe_live, smtp_candidates, cache_stats, clear_cache,
    refresh_domain, _family_priority, _family_priority_pop, DEAD_IMAP_HOSTS

v13.37 fixes on this page
-------------------------
* Renamed 1_Diagnostics.py -> 2_Diagnostics.py (it collided with
  1_Mailbox_Reader.py, so both rendered under the same page number).
* st.stop() inside `with tab_plan:` aborted the WHOLE script, so tabs 2-6
  (Live Port Probe, DNS, SMTP, Proxy Audit, Cache) never rendered at all for a
  zero-access domain, or whenever conf() raised.  Tab 1 is now skipped via a
  flag and every other tab still renders.
* _build_plan() claimed to mirror app.py and did not: it ignored the configured
  protocol set and always emitted both IMAP and POP rungs.  It now reads the
  engine's real protocol flags out of st.session_state["applied_cfg"].
* The POP warning was unconditional-ish.  Replaced with a real
  pop_only-vs-all_pop test.
"""

import os
import sys
import json
import time
import socket
from datetime import datetime

import streamlit as st
# @@END 000 FILE_HEADER


# @@BLOCK 001 PAGE_CONFIG deps=000
st.set_page_config(page_title="Diagnostics · Mail Checker", page_icon="🔍", layout="wide",
                   initial_sidebar_state="collapsed")
# @@END 001 PAGE_CONFIG


# @@BLOCK 002 SYSPATH deps=000
# --------------------------------------------------------------------------
# make the repo root importable (the page runs from pages/)
# --------------------------------------------------------------------------
THIS_DIR = os.path.dirname(os.path.abspath(__file__))
APP_DIR = os.path.dirname(THIS_DIR)
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)
# @@END 002 SYSPATH


# @@BLOCK 003 THEME deps=002
# --------------------------------------------------------------------------
# theme — read-only mirror of theme.json so this page matches the app
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
                    base.update({k: v for k, v in data.items() if k in base and isinstance(v, str)})
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
    .stApp {{ background: {_TH['bg']}; color: {_TH['text']}; }}
    h1, h2, h3, h4 {{ color: {_TH['text']} !important; }}
    .dg-hero {{
        background: linear-gradient(135deg, {_TH['g1']} 0%, {_TH['g2']} 100%);
        padding: 18px 24px; border-radius: 14px; margin-bottom: 14px;
        border: 1px solid rgba(255,255,255,.12);
    }}
    .dg-hero h1 {{ color: #fff !important; margin: 0; font-size: 1.5rem; font-weight: 800; }}
    .dg-hero p {{ color: rgba(255,255,255,.92) !important; margin: 6px 0 0 0; font-size: .85rem; }}
    code, pre, [data-testid="stCodeBlock"] {{
        background: {_TH['bg']} !important; color: {_TH['accent2']} !important;
        border: 1px solid rgba(255,255,255,.10) !important; border-radius: 10px !important;
    }}
    [data-testid="stMetric"] {{
        background: {_TH['panel']}; border: 1px solid rgba(255,255,255,.10);
        border-left: 4px solid {_TH['accent']}; border-radius: 12px; padding: 12px 14px;
    }}
</style>
""",
    unsafe_allow_html=True,
)
# @@END 004 CSS


# @@BLOCK 005 HERO deps=004
st.markdown(
    '<div class="dg-hero"><h1>🔍 Diagnostics</h1>'
    '<p>Host plan · live port probe · DNS &amp; discovery · SMTP candidates · proxy audit · cache tools</p></div>',
    unsafe_allow_html=True,
)
# @@END 005 HERO


# @@BLOCK 006 IMPORT_HOSTS deps=002
# --------------------------------------------------------------------------
# hosts.py must import, or nothing here means anything
# --------------------------------------------------------------------------
try:
    import hosts as H
except Exception as _err:
    st.error(f"`hosts.py` could not be imported: {_err}")
    st.caption(f"Looked in: {APP_DIR}  ·  cwd: {os.getcwd()}")
    st.stop()

_HAVE = {
    "family_pop": hasattr(H, "_family_priority_pop"),
    "dead_imap": hasattr(H, "DEAD_IMAP_HOSTS"),
    "conf": hasattr(H, "conf"),
    "discover": hasattr(H, "discover_hosts"),
}

if not _HAVE["family_pop"]:
    st.warning(
        "This `hosts.py` has **no `_family_priority_pop()`** — the POP bucket is still being led by "
        "the IMAP family, so the POP rung will dial `<imap-host>:995`. Apply the v13.26 `hosts.py` patch."
    )
# @@END 006 IMPORT_HOSTS


# @@BLOCK 007 HELPERS_NET deps=006
# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------
def _resolve(host):
    try:
        return socket.gethostbyname(host)
    except Exception:
        return None


def _dedupe_by_ip(hosts, cap):
    """Same collapse app.py performs: one host per resolved IP, capped."""
    out, seen_ips = [], set()
    for h in hosts:
        if not h or h in out:
            continue
        ip = _resolve(h) or ("?" + h)
        if ip in seen_ips:
            continue
        seen_ips.add(ip)
        out.append(h)
        if len(out) >= cap:
            break
    if len(out) < cap:
        for h in hosts:
            if len(out) >= cap:
                break
            if h and h not in out:
                out.append(h)
    return out


def _port_probe(host, port, timeout=8.0):
    t0 = time.time()
    s = None
    try:
        s = socket.create_connection((host, int(port)), timeout=timeout)
        return True, int((time.time() - t0) * 1000), ""
    except Exception as e:
        return False, int((time.time() - t0) * 1000), f"{type(e).__name__}: {str(e)[:110]}"
    finally:
        if s:
            try:
                s.close()
            except Exception:
                pass
# @@END 007 HELPERS_NET


# @@BLOCK 008 HELPERS_PROXY deps=006
def _parse_proxy(line):
    p = (line or "").strip()
    if not p:
        return None
    try:
        if "://" in p:
            from urllib.parse import urlparse
            u = urlparse(p)
            return {"host": u.hostname, "port": u.port or 80, "user": u.username}
        if "@" in p:
            cred, hostpart = p.rsplit("@", 1)
            user = cred.split(":", 1)[0]
            host, port = hostpart.split(":", 1)
            return {"host": host, "port": int(port), "user": user}
        parts = p.split(":")
        if len(parts) == 4:
            return {"host": parts[0], "port": int(parts[1]), "user": parts[2]}
        if len(parts) == 2:
            return {"host": parts[0], "port": int(parts[1]), "user": None}
    except Exception:
        return None
    return None


def _detect_format(line):
    p = (line or "").strip()
    if not p:
        return "empty"
    if "://" in p:
        return "scheme:// (url form)"
    if "@" in p:
        return "user:pass@host:port"
    n = len(p.split(":"))
    if n == 4:
        return "host:port:user:pass"
    if n == 2:
        return "host:port (NO CREDS)"
    return f"UNRECOGNISED ({n} colon-parts)"
# @@END 008 HELPERS_PROXY


# @@BLOCK 009 PROTOCOLS_PLAN deps=007
# --------------------------------------------------------------------------
# v13.37: read the ENGINE's real protocol flags
# v13.40: build_cfg() publishes the key "PROTOCOLS" - "ui_protocols" is only
#         the widget key, so the old lookup always missed and the page fell
#         through to the IMAP+POP default, defeating this whole block.
#         Also split string values: iterating "IMAP,POP" yields characters.
# --------------------------------------------------------------------------
_WEB_ONLY = {
    "secure.windstream.net", "webmail.windstream.net",
    "secure.suddenlink.net", "webmail.suddenlink.net", "secure.optimum.net",
}


def _protocols_from_app():
    """app.py publishes its applied config into st.session_state["applied_cfg"].
    Reading that same key is what makes this page honest instead of decorative.
    Returns {imap, pop, smtp, sieve} — defaults match app.py's defaults."""
    flags = {"imap": True, "pop": True, "smtp": False, "sieve": False}
    cfg = {}
    try:
        cfg = st.session_state.get("applied_cfg") or {}
    except Exception:
        cfg = {}
    if not isinstance(cfg, dict):
        cfg = {}

    raw = cfg.get("PROTOCOLS") or cfg.get("protocols")
    if not raw:
        try:
            raw = st.session_state.get("ui_protocols")
        except Exception:
            raw = None
    if not raw:
        return flags

    if isinstance(raw, str):
        wanted = []
        buf = ""
        for ch in raw:
            if ch in ",/|; \t\r\n":
                if buf:
                    wanted.append(buf)
                    buf = ""
            else:
                buf += ch
        if buf:
            wanted.append(buf)
        wanted = [p.strip().upper() for p in wanted if p.strip()]
    else:
        wanted = [str(p).strip().upper() for p in raw if str(p).strip()]

    if not wanted:
        return flags

    flags["imap"] = any(p.startswith("IMAP") for p in wanted)
    flags["pop"] = any(p.startswith("POP") for p in wanted)
    flags["smtp"] = any(p.startswith("SMTP") for p in wanted)
    flags["sieve"] = any(p.startswith("SIEVE") for p in wanted)
    return flags


def _build_plan(domain, max_hosts, flags=None):
    """Replicate app.py's check_account_sync() rung construction EXACTLY.

    v13.37: the rung set is now gated on the engine's real protocol flags, so
    disabling IMAP in the sidebar is visible here.
    """
    if flags is None:
        flags = {"imap": True, "pop": True, "smtp": False, "sieve": False}

    got = H.conf(domain) or {}
    if got.get("type") == "zero_access":
        return got, [], [], [], [], "zero_access"

    all_imap = [h for h in (got.get("imap") or []) if h]
    all_pop = [h for h in (got.get("pop") or got.get("pop3") or []) if h]

    if not flags.get("imap"):
        all_imap = []
    if not flags.get("pop"):
        all_pop = []

    cap = max(2, min(4, int(max_hosts)))
    imap_hosts = _dedupe_by_ip(all_imap, cap)

    if domain and domain not in imap_hosts and len(imap_hosts) < 4 and _resolve(domain):
        imap_hosts = imap_hosts + [domain]
    if domain in imap_hosts:
        imap_hosts = [h for h in imap_hosts if h != domain] + [domain]

    _drop = {domain}
    if domain.endswith("windstream.net") or domain.endswith("kinetic.net"):
        _drop |= {"secure.windstream.net", "webmail.windstream.net"}
    _kept = [h for h in imap_hosts if h.lower() not in _drop]
    if _kept:
        imap_hosts = _kept
    _web = [h for h in imap_hosts if h.lower() in _WEB_ONLY]
    if _web and len(_web) < len(imap_hosts):
        imap_hosts = [h for h in imap_hosts if h.lower() not in _WEB_ONLY] + _web

    pop_only_pref = [h for h in all_pop if h not in imap_hosts]
    pop_hosts = (pop_only_pref or all_pop)[:1]

    imap_set = set(imap_hosts)
    pop_only = [h for h in pop_hosts if h not in imap_set]
    pop_dup = [h for h in pop_hosts if h in imap_set]

    primary = []
    if imap_hosts:
        primary.append(("IMAP", imap_hosts[0], 993, "ssl"))
    primary += [("POP", h, 995, "ssl") for h in pop_only]
    primary += [("IMAP", h, 993, "ssl") for h in imap_hosts[1:]]
    # v13.40a: app.py also dials SMTP submission and ManageSieve when those
    # protocols are selected, so the page was missing up to 4 rungs.
    if flags.get("smtp"):
        try:
            _smtp = [h for h in (H.smtp_candidates(domain) or []) if h][:1]
        except Exception:
            _smtp = []
        for _sh in _smtp:
            for _sp, _sm in ((587, "starttls"), (465, "ssl"), (25, "plain")):
                primary.append(("SMTP", _sh, _sp, _sm))
    if flags.get("sieve") and imap_hosts:
        primary.append(("SIEVE", imap_hosts[0], 4190, "starttls"))

    fallback = [("POP", h, 995, "ssl") for h in pop_dup]
    for h in imap_hosts:
        fallback.append(("IMAP", h, 143, "starttls"))
    for h in imap_hosts[:2]:
        fallback.append(("IMAP", h, 143, "plain"))
    for h in pop_hosts:
        fallback.append(("POP", h, 110, "starttls"))
        fallback.append(("POP", h, 110, "plain"))

    return got, all_imap, all_pop, primary, fallback, "ok"
# @@END 009 PROTOCOLS_PLAN


# @@BLOCK 010 SIDEBAR deps=009
# --------------------------------------------------------------------------
# sidebar controls
# --------------------------------------------------------------------------
with st.sidebar:
    st.markdown("### 🔍 Diagnostics controls")
    domain = st.text_input("Domain", value="windstream.net").strip().lower()
    max_hosts = st.slider("Max Hosts Per Domain (as in the app)", 1, 8, 3, 1)
    force = st.toggle("Force refresh discovery (bypass 24h host cache)", value=False)
    st.caption("Nothing here connects to a mailbox — only DNS and raw TCP.")
# @@END 010 SIDEBAR


# @@BLOCK 011 TABS_HEADER deps=010
if not domain:
    st.info("Enter a domain.")
    st.stop()

# --------------------------------------------------------------------------
tab_plan, tab_probe, tab_dns, tab_smtp, tab_proxy, tab_cache = st.tabs(
    ["🧭 Host Plan", "🔌 Live Port Probe", "🛰 DNS / Discovery", "📮 SMTP", "🌐 Proxy Audit", "🧰 Cache"]
)

_PROTO_FLAGS = _protocols_from_app()
st.caption("Engine protocol flags read from the applied config: "
           + ", ".join(k.upper() for k, v in _PROTO_FLAGS.items() if v))
# @@END 011 TABS_HEADER


# @@BLOCK 012 TAB_HOST_PLAN deps=011
# ==========================================================================
# 1. HOST PLAN
# ==========================================================================
with tab_plan:
    st.markdown(f"#### Exact rung order for `@{domain}`")

    if force:
        with st.spinner("Re-running discovery (SRV / autoconfig / autodiscover / MX)…"):
            try:
                H.refresh_domain(domain)
            except Exception as e:
                st.warning(f"discovery refresh failed: {e}")

    # v13.37: defaults first, so later tabs and the footer always have values
    got, all_imap, all_pop, primary, fallback, kind = {}, [], [], [], [], "ok"
    plan_error = ""
    # v13.40: fam/fam_pop belong up here too. They used to be bound only inside
    # the success branch, so on plan_error / zero_access the bundle button in
    # block 018 raised NameError: name 'fam' is not defined.
    fam = []
    fam_pop = []
    try:
        with st.spinner("Building host plan…"):
            got, all_imap, all_pop, primary, fallback, kind = _build_plan(
                domain, max_hosts, _PROTO_FLAGS)
    except Exception as e:
        plan_error = str(e)

    # v13.37: was st.stop() -> killed tabs 2-6 as well
    if plan_error:
        st.error(f"conf() failed: {plan_error}")
    elif kind == "zero_access":
        st.info("This provider is Zero-Access / bridge-only (no IMAP or POP endpoint).")
    else:
        if not got:
            st.warning("`hosts.conf()` returned nothing for this domain — the generic guesser found no route.")

        try:
            fam = H._family_priority(domain)
        except Exception:
            pass
        if _HAVE["family_pop"]:
            try:
                fam_pop = H._family_priority_pop(domain)
            except Exception:
                pass

        c1, c2, c3 = st.columns(3)
        c1.metric("IMAP candidates (raw)", len(all_imap))
        c2.metric("POP candidates (raw)", len(all_pop))
        c3.metric("Rungs that will be dialled", len(primary) + len(fallback))

        st.markdown("**Family priority (IMAP bucket)**")
        st.code(", ".join(fam) or "— none, generic guesser", language="text")
        st.markdown("**Family priority (POP bucket)**")
        st.code(", ".join(fam_pop) or "— none (POP bucket falls back to the IMAP family)", language="text")

        st.markdown("**Resulting ladder — this is literally what the engine dials**")
        st.code(
            f"Host order -> IMAP {[h for h in all_imap if h][:8]} | POP {all_pop[:4]}\n"
            f"primary_plan  ({len(primary)}): " + ", ".join(f"{p} {h}:{pt}" for p, h, pt, _m in primary) + "\n"
            f"fallback_plan ({len(fallback)}): " + ", ".join(f"{p} {h}:{pt}" for p, h, pt, _m in fallback),
            language="text",
        )

        if not fam_pop and all_pop:
            st.warning(
                "No POP family list is present, so the POP rung is dialling an IMAP hostname on 995 "
                f"(`{all_pop[0]}:995`). Expected after the fix: `pop.{domain.split('.')[-2] + '.' + domain.split('.')[-1]}`."
            )

        # v13.37: real test instead of an unconditional warning
        pop_only = bool(all_pop) and not bool(all_imap)
        all_pop_dup = bool(all_pop) and bool(all_imap)
        if pop_only:
            st.warning("POP-only provider: the ladder has NO IMAP rung. Enable IMAP in the sidebar or "
                       "this domain can never authenticate.")
        elif all_pop_dup:
            st.caption("IMAP and POP both exist — the engine dials IMAP first and only falls back to POP "
                       "when every IMAP rung fails.")

        st.markdown("**Per-host detail**")
        rows = []
        seen = []
        for h in list(dict.fromkeys(all_imap + all_pop)):
            if h in seen:
                continue
            seen.append(h)
            ip = _resolve(h)
            rows.append({
                "Host": h,
                "Resolves": "yes" if ip else "NO",
                "IP": ip or "—",
                "Dead-IMAP demoted": "yes" if (_HAVE["dead_imap"] and h in H.DEAD_IMAP_HOSTS) else "",
                "Tier": H.host_tier(h, domain) if hasattr(H, "host_tier") else "",
                "Looks like a router": "yes" if H.is_junk_host(h, domain) else "",
                "In primary plan": "yes" if any(h == r[1] for r in primary) else "",
            })
        if rows:
            st.dataframe(rows, use_container_width=True, hide_index=True)

        # shared-IP grouping — explains why two hostnames live or die together
        ipmap = {}
        for h in seen:
            ip = _resolve(h)
            if ip:
                ipmap.setdefault(ip, []).append(h)
        shared = {ip: hs for ip, hs in ipmap.items() if len(hs) > 1}
        if shared:
            st.markdown("**Hosts sharing an IP** (they succeed or fail together)")
            for ip, hs in shared.items():
                st.code(f"{ip}  <-  {', '.join(hs)}", language="text")
# @@END 012 TAB_HOST_PLAN


# @@BLOCK 013 TAB_PROBE deps=011
# ==========================================================================
# 2. LIVE PORT PROBE
# ==========================================================================
with tab_probe:
    st.markdown("#### Live TCP probe from this app host")
    st.caption("A TCP connect proves a listener exists. It does NOT prove a mailbox exists.")

    default_targets = []
    for _p, h, pt, _m in (primary or []):
        default_targets.append(f"{h}:{pt}")
    if not default_targets:
        default_targets = [f"imap.{domain}:993", f"pop.{domain}:995"]

    targets_text = st.text_area(
        "Targets (one host:port per line)", value="\n".join(dict.fromkeys(default_targets)), height=120
    )
    probe_to = st.slider("Timeout (s)", 2, 20, 8, 1)

    if st.button("▶ Probe all targets", type="primary"):
        pairs = []
        for line in targets_text.splitlines():
            line = line.strip()
            if not line or ":" not in line:
                continue
            h, p = line.rsplit(":", 1)
            if p.strip().isdigit():
                pairs.append((h.strip(), int(p.strip())))
        if not pairs:
            st.warning("No valid host:port targets.")
        else:
            results = []
            bar = st.progress(0.0)
            for i, (h, p) in enumerate(pairs, 1):
                ok, ms, err = _port_probe(h, p, timeout=probe_to)
                results.append({"Target": f"{h}:{p}", "TCP": "OK" if ok else "FAIL",
                                "ms": ms, "Error": err})
                bar.progress(i / len(pairs), text=f"{i}/{len(pairs)}")
            st.dataframe(results, use_container_width=True, hide_index=True)

            if all(r["TCP"] == "FAIL" for r in results):
                st.error(
                    "Every target refused. That is a **host or path** problem, not a password problem — "
                    "no proxy and no retry setting can change it."
                )
            elif any(r["TCP"] == "OK" for r in results):
                st.success("At least one listener answered — the ladder has something to talk to.")
# @@END 013 TAB_PROBE


# @@BLOCK 014 TAB_DNS deps=011
# ==========================================================================
# 3. DNS / DISCOVERY
# ==========================================================================
with tab_dns:
    st.markdown("#### Resolution layer")

    mx = []
    srv = []
    found = {}
    try:
        mx = H.resolve_mx(domain)
    except Exception as e:
        st.warning(f"MX lookup failed: {e}")
    try:
        srv = H.resolve_srv(f"_imaps._tcp.{domain}")
    except Exception as e:
        st.warning(f"SRV lookup failed: {e}")

    st.markdown("**MX records**")
    st.code("\n".join(mx) or "— none", language="text")
    st.markdown("**SRV `_imaps._tcp`**")
    st.code("\n".join(str(s) for s in srv) or "— none", language="text")

    if st.button("Run full discovery (SRV → autoconfig → autodiscover → MX → prefixes)"):
        with st.spinner("Discovering…"):
            try:
                found = H.discover_hosts(domain, force_refresh=True)
            except Exception as e:
                st.error(f"discover_hosts failed: {e}")
        if found:
            st.markdown(f"**Sources that produced data:** `{found.get('sources') or 'none'}`")
            st.markdown("**Discovered IMAP**")
            st.code("\n".join(found.get("imap") or []) or "— none", language="text")
            st.markdown("**Discovered POP**")
            st.code("\n".join(found.get("pop") or []) or "— none", language="text")

    st.divider()
    st.markdown("**Apex check**")
    apex_ip = _resolve(domain)
    st.code(f"{domain} -> {apex_ip or 'DOES NOT RESOLVE'}", language="text")
    st.caption(
        "The bare apex is appended as a last-resort rung only if it resolves. "
        "It is demoted to the very end because it has no IMAP listener on most providers."
    )
# @@END 014 TAB_DNS


# @@BLOCK 015 TAB_SMTP deps=011
# ==========================================================================
# 4. SMTP
# ==========================================================================
with tab_smtp:
    st.markdown("#### SMTP pre-check candidates")
    st.caption("Only used when `📮 Enable SMTP pre-check` is ON in the app sidebar. Ports tried: 587 → 465 → 25.")
    try:
        cands = H.smtp_candidates(domain) or []
    except Exception as e:
        cands = []
        st.warning(f"smtp_candidates failed: {e}")
    if not cands:
        st.info("No SMTP candidates (Zero-Access provider, or nothing derivable).")
    else:
        st.code("\n".join(cands), language="text")
        if st.button("Probe SMTP candidates"):
            out = []
            for h in cands:
                for port, tls in ((587, False), (465, True), (25, False)):
                    ok, ms, err = _port_probe(h, port, timeout=6)
                    out.append({"Host": h, "Port": port, "TLS": "implicit" if tls else "plain",
                                "TCP": "OK" if ok else "FAIL", "ms": ms, "Error": err})
            st.dataframe(out, use_container_width=True, hide_index=True)
# @@END 015 TAB_SMTP


# @@BLOCK 016 TAB_PROXY deps=011
# ==========================================================================
# 5. PROXY AUDIT
# ==========================================================================
with tab_proxy:
    st.markdown("#### proxies.txt audit (read-only)")
    st.caption("Nothing is probed here — use the app sidebar's 🔁 Re-probe for a real tunnel test.")

    pfile = None
    for cand in (os.path.join(APP_DIR, "proxies.txt"), "proxies.txt"):
        if os.path.exists(cand):
            pfile = cand
            break

    if not pfile:
        st.info("No proxies.txt found next to app.py.")
    else:
        try:
            with open(pfile, encoding="utf-8", errors="ignore") as f:
                raw = [l.rstrip("\n") for l in f]
        except Exception as e:
            st.error(f"Could not read {pfile}: {e}")
            raw = []

        lines = [l.strip() for l in raw if l.strip() and not l.startswith("#")]
        uniq = list(dict.fromkeys(lines))
        formats = {}
        unparsable = 0
        with_creds = 0
        for l in lines:
            formats[_detect_format(l)] = formats.get(_detect_format(l), 0) + 1
            if "@" in l:
                with_creds += 1
            if not _parse_proxy(l):
                unparsable += 1

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Lines", len(lines))
        c2.metric("Unique", len(uniq))
        c3.metric("With credentials", with_creds)
        c4.metric("Unparsable", unparsable)

        st.markdown("**Detected line formats**")
        st.code(json.dumps(formats, indent=2), language="json")

        if lines and with_creds == 0:
            st.warning("No line contains `@` → **no credentials at all**. A 407 is guaranteed if the proxy needs auth.")
        if unparsable:
            st.warning(f"{unparsable} line(s) do not parse into host:port — check for spaces or stray characters.")

        dupes = {}
        for l in lines:
            info = _parse_proxy(l)
            if info:
                k = f"{info['host']}:{info['port']}"
                dupes[k] = dupes.get(k, 0) + 1
        heavy = {k: v for k, v in dupes.items() if v > 1}
        if heavy:
            st.markdown("**Repeated endpoints** (dedupe collapses these)")
            st.code("\n".join(f"{k}  x{v}" for k, v in sorted(heavy.items(), key=lambda kv: -kv[1])[:30]),
                    language="text")

        with st.expander("First 10 raw lines"):
            st.code("\n".join(lines[:10]) or "— empty —", language="text")
# @@END 016 TAB_PROXY


# @@BLOCK 017 TAB_CACHE deps=011
# ==========================================================================
# 6. CACHE
# ==========================================================================
with tab_cache:
    st.markdown("#### Host cache tools")

    try:
        stats = H.cache_stats()
    except Exception as e:
        stats = {"error": str(e)}
    st.json(stats)

    c1, c2 = st.columns(2)
    with c1:
        if st.button("🧹 Clear hosts_cache.json", use_container_width=True):
            try:
                H.clear_cache()
                st.success("Cache cleared. Reload this page to rebuild it.")
            except Exception as e:
                st.error(f"clear_cache failed: {e}")
    with c2:
        if st.button("♻️ Refresh this domain", use_container_width=True):
            try:
                H.refresh_domain(domain)
                st.success(f"Discovery refreshed for {domain}.")
            except Exception as e:
                st.error(f"refresh_domain failed: {e}")

    st.caption(
        "Clear the cache after any hosts.py change, otherwise the old family entry keeps being served "
        "for up to 24h."
    )

    with st.expander("Cached entries (domain -> counts)"):
        try:
            with open(os.path.join(APP_DIR, "hosts_cache.json"), encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                st.code(
                    "\n".join(f"{k}: imap={len(v.get('imap') or [])} pop={len(v.get('pop') or [])} "
                              f"sources={v.get('sources')}" for k, v in list(data.items())[:60]),
                    language="text",
                )
        except Exception as e:
            st.caption(f"no readable cache: {e}")
# @@END 017 TAB_CACHE


# @@BLOCK 018 FOOTER_BUNDLE deps=012
# ==========================================================================
# footer bundle
# ==========================================================================
st.divider()
if st.button("📋 Build copy/paste bundle"):
    L = []
    L.append("=" * 70)
    L.append(f"DIAGNOSTICS BUNDLE — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    L.append("=" * 70)
    L.append(f"domain        : {domain}")
    L.append(f"max_hosts     : {max_hosts}")
    L.append(f"hosts.py      : {os.path.join(APP_DIR, 'hosts.py')}")
    L.append(f"family_pop    : {_HAVE['family_pop']}")
    L.append(f"proto_flags   : {_PROTO_FLAGS}")
    L.append(f"cwd           : {os.getcwd()}")
    L.append("")
    L.append("-- family (imap) --")
    L.append(", ".join(fam) or "none")
    L.append("-- family (pop) --")
    L.append(", ".join(fam_pop) or "none")
    L.append("")
    L.append("-- raw conf --")
    L.append(json.dumps(got, indent=2)[:4000])
    L.append("")
    L.append("-- rungs --")
    for p, h, pt, m in primary:
        L.append(f"PRIMARY  {p} {h}:{pt} {m}")
    for p, h, pt, m in fallback:
        L.append(f"FALLBACK {p} {h}:{pt} {m}")
    L.append("")
    L.append("-- resolution --")
    for h in list(dict.fromkeys(all_imap + all_pop)):
        L.append(f"{h} -> {_resolve(h) or 'UNRESOLVED'}")
    L.append("")
    L.append("-- live probe --")
    for p, h, pt, m in (primary or [])[:6]:
        ok, ms, err = _port_probe(h, pt, timeout=6)
        L.append(f"{h}:{pt} tcp={'OK' if ok else 'FAIL'} {ms}ms {err}")
    st.code("\n".join(L), language="text")
# @@END 018 FOOTER_BUNDLE


# @@BLOCK 019 TRAILING deps=018
# (reserved tail - keeps the file closed after the last block)
# @@END 019 TRAILING
# @@EOF
