#!/usr/bin/env python3
"""verify_v1337.py — regression harness for the v13.37 patch set (v13.40 revision).

Run from the repo root:   python verify_v1337.py
Exit code 0 = clean.

For every file the v13.37 work touched it checks:
  (a) the module compiles, tokenizes and AST-parses,
  (b) every v13.37 fix is textually PRESENT,
  (c) every buggy pattern the fix replaced is GONE from the CODE,
  (d) no pasted-prose line, no stray markdown fence, and no tokenizer landmine
      (em dash / curly quote / nbsp outside a string) survived the paste,
plus that no two files in pages/ share a page number.

WHY THIS REVISION EXISTS (v13.39b)
----------------------------------
  * THE P1 BLOCK DID NOT COMPILE.  It had been pasted without closing its
    has(...) call, so the whole harness was a SyntaxError and could never have
    run.  It is repaired, and the P0-v13.39 assertions are now real.
  * NEW STRUCTURAL CHECKS for the v13.39b regression: _handle_app_or_wrong
    referenced _dialable_local, a name defined NOWHERE, so every WRONG/APP
    verdict raised NameError inside an except handler and fell straight through
    to the outer handler - the ladder never advanced.  The helper must use
    domain_local_hosts and must contain exactly ONE WRONG block (the duplicate
    copy was dead code sitting after a return).
  * Four stale v13.38 markers corrected for v13.39 (header, CFG_VERSION,
    _GEO_FAIL, _STARTUP_SEEN - the last two are STATE-backed now).

WHY THE EARLIER REVISION EXISTED
--------------------------------
  * The PART 1/3 / PART 2/3 banner checks were removed — app.py has no banners.
  * "settled = False", "def _geo_throttle(", '"geo_fail": {}',
    '_GEO_FAIL = STATE["geo_fail"]' and "MAIL_SPOT_MIN_INTERVAL" do not exist in
    app.py; the real markers are checked instead.
  * gone() now runs against a view of the source with comments AND string
    literals blanked out, because app.py's changelog docstring and several
    comments deliberately name the symbols they removed.
  * NEW: stray-line + non-ASCII landmine checks for the paste that broke the
    build at app.py line 7330 ("invalid character '—' (U+2014)").
"""
import ast
import io
import os
import re
import sys
import tokenize

PASSES = []
FAILS = []


def read(path):
    with io.open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def _line_offsets(src):
    offs = [0]
    for ln in src.splitlines(keepends=True):
        offs.append(offs[-1] + len(ln))
    return offs


def code_view(src):
    """Source with every COMMENT and STRING token blanked out, layout preserved.

    Newlines inside multi-line strings are kept, so line numbers still line up
    with the real file.  This is the view gone() must use.
    """
    chars = list(src)
    offs = _line_offsets(src)

    def pos(line, col):
        return offs[line - 1] + col

    try:
        toks = list(tokenize.generate_tokens(io.StringIO(src).readline))
    except Exception:
        return src
    for tok in toks:
        if tokenize.tok_name.get(tok.type) not in (
                "COMMENT", "STRING", "FSTRING_START", "FSTRING_MIDDLE",
                "FSTRING_END", "TSTRING_START", "TSTRING_MIDDLE",
                "TSTRING_END"):
            continue
        start, end = pos(*tok.start), pos(*tok.end)
        for i in range(start, min(end, len(chars))):
            if chars[i] != "\n":
                chars[i] = " "
    return "".join(chars)


def has(src, needle, label):
    if needle in src:
        PASSES.append(label)
    else:
        FAILS.append("MISSING: " + label + "   -> " + repr(needle[:80]))


def gone(src, needle, label):
    if needle in src:
        FAILS.append("STILL PRESENT: " + label + "   -> " + repr(needle[:80]))
    else:
        PASSES.append(label)


def compiles(path, src):
    try:
        compile(src, path, "exec")
        PASSES.append(path + " compiles")
    except SyntaxError as e:
        FAILS.append("%s DOES NOT COMPILE: line %s: %s" % (path, e.lineno, e.msg))
    except Exception as e:
        FAILS.append("%s compile failed: %s" % (path, e))


def tokenizes(path, src):
    try:
        list(tokenize.generate_tokens(io.StringIO(src).readline))
        PASSES.append(path + " tokenizes")
    except Exception as e:
        FAILS.append("%s tokenize failed: %s" % (path, e))


def parses(path, src):
    try:
        ast.parse(src, filename=path)
        PASSES.append(path + " AST parses")
    except SyntaxError as e:
        FAILS.append("%s AST parse failed: line %s: %s" % (path, e.lineno, e.msg))


# ---------------------------------------------------------------------------
# the paste that broke the build
# ---------------------------------------------------------------------------
PROSE_NEEDLES = (
    "Continuing the v13.37 app.py",
    "Paste this directly beneath it",
    "the two pieces concatenate with no seam",
)

LANDMINES = (
    ("\u2014", "em dash"),
    ("\u2013", "en dash"),
    ("\u2018", "left single quote"),
    ("\u2019", "right single quote"),
    ("\u201c", "left double quote"),
    ("\u201d", "right double quote"),
    ("\u00a0", "non-breaking space"),
)


def stray_lines(path, code_src):
    """code_src must be code_view(file): no comments, no strings."""
    lines = code_src.splitlines()

    fences = [i for i, l in enumerate(lines, 1) if l.strip().startswith("```")]
    if fences:
        for i in fences:
            FAILS.append("%s line %d is a stray markdown fence: %r"
                         % (path, i, lines[i - 1].strip()))
    else:
        PASSES.append(path + " has no stray markdown fence line")

    for needle in PROSE_NEEDLES:
        hits = [i for i, l in enumerate(lines, 1) if needle in l]
        if hits:
            for i in hits:
                FAILS.append("%s line %d is pasted English prose: %r"
                             % (path, i, lines[i - 1].strip()[:90]))
        else:
            PASSES.append("%s: prose marker gone (%r)" % (path, needle))

    for i, line in enumerate(lines, 1):
        for ch, name in LANDMINES:
            if ch in line:
                FAILS.append("%s line %d has a %s outside any string/comment "
                             "(the tokenizer rejects it): %r"
                             % (path, i, name, line.strip()[:90]))


def seam_is_intact(app):
    pat = (r"run_completion_status[^\n]*\n"
           r"(?:\s*(?:#[^\n]*)?\n)*"
           r"\s*start_dt = datetime\.now\(\)")
    if re.search(pat, app):
        PASSES.append("app.py: run-reset seam intact "
                      "(run_completion_status -> start_dt, nothing in between)")
    else:
        FAILS.append("app.py: run-reset seam BROKEN — the two pasted halves no "
                     "longer join around run_completion_status / start_dt")


def page_numbers():
    if not os.path.isdir("pages"):
        FAILS.append("no pages/ directory found")
        return
    seen = {}
    for name in sorted(os.listdir("pages")):
        if not name.endswith(".py"):
            continue
        num = name.split("_", 1)[0]
        if num.isdigit():
            seen.setdefault(num, []).append(name)
    for num in sorted(seen):
        names = seen[num]
        if len(names) > 1:
            FAILS.append("page number %s COLLIDES: %s" % (num, ", ".join(names)))
        else:
            PASSES.append("page number %s unique (%s)" % (num, names[0]))
    for expected in ("pages/2_Diagnostics.py", "pages/3_Mailbox_Reader.py"):
        if os.path.exists(expected):
            PASSES.append(expected + " exists")
        else:
            FAILS.append(expected + " is MISSING")
    for removed in ("pages/1_Diagnostics.py", "pages/1_Mailbox_Reader.py"):
        if os.path.exists(removed):
            FAILS.append(removed + " still exists (git rm it)")
        else:
            PASSES.append(removed + " removed")


def main():
    app_path = "app.py"
    dia_path = "pages/2_Diagnostics.py"
    rdr_path = "pages/3_Mailbox_Reader.py"
    req_path = "requirements.txt"

    for p in (app_path, dia_path, rdr_path, req_path):
        if not os.path.exists(p):
            FAILS.append(p + " is MISSING")

    app = read(app_path) if os.path.exists(app_path) else ""
    dia = read(dia_path) if os.path.exists(dia_path) else ""
    rdr = read(rdr_path) if os.path.exists(rdr_path) else ""
    req = read(req_path) if os.path.exists(req_path) else ""

    if app:
        compiles(app_path, app)
        tokenizes(app_path, app)
        parses(app_path, app)
        app_code = code_view(app)
        stray_lines(app_path, app_code)
        seam_is_intact(app)

        # NB: app.py uses an ASCII hyphen, not an em dash, so match the stem.
        has(app, "Mega Ultimate Mail Checker", "app.py header names the app")

        # ---- P0: 407 classification, swallowed XOAUTH2 407, clean_valid merge --
        has(app, 'out["reason"] = "auth"', "P0 post-loop auth override present")
        has(app, 'if _s_idx and out["ok"] and not _second_scheme:',
            "P0 tunnel_probe gate is outcome-driven (PASS stops, FAIL tries other scheme)")
        gone(app_code, "if ptype == preferred:",
             "P0 407 no longer filed by the preferred scheme")
        has(app, "except ProxyAuthError as pae:", "P0 ProxyAuthError no longer swallowed")
        has(app, "nonlocal acct_407_total", "P0 407 counter is nonlocal")
        has(app, "def _write_clean_valid(", "P0 clean_valid merge helper present")
        has(app, "fetched_msgs, success_read = msgs, True", "P0 success_read typo fixed")
        gone(app_code, "success_msgs", "P0 success_msgs local is gone")

        # ---- P1 ----
        has(app, 'if "Fast-fail DNS check" not in err_text:',
            "P1 local DNS RuntimeError no longer sets saw_server")

        # ---- P0-v13.39: a WRONG must be confirmed before it ends the ladder ----
        has(app, "wrong_hosts.add(server)", "P0 provisional WRONG tracking present")
        has(app, "if (not confirm_wrong) or _confirmed:",
            "P0 WRONG early-return is gated on confirmation")
        has(app, "app_hosts.add(server)", "P0 provisional APP tracking present")
        has(app, "CONFIRM_WRONG_ACROSS_HOSTS", "P0 guard flag wired")
        has(app, "note_verdict(st_val, detail, host=\"\", force=False)",
            "P0 note_verdict has a force path")
        has(app, "if st_val not in (VALID, WRONG, APP, RBL, LOGIN_DROPPED, UNKNOWN,",
            "P0 UNKNOWN is retained")

        # ---- P0-v13.39b: the helper must be reachable and single ----
        has(app, "[h for h in domain_local_hosts if h not in tried_hosts]",
            "P0 the confirmation gate uses domain_local_hosts")
        gone(app_code, "_dialable_local",
             "P0 _dialable_local is not referenced anywhere")
        _nw = app_code.count("wrong_hosts.add(server)")
        if _nw != 1:
            FAILS.append("P0 the WRONG block is duplicated inside "
                         "_handle_app_or_wrong (wrong_hosts.add appears %d x, want 1)" % _nw)
        else:
            PASSES.append("P0 exactly one WRONG block in the helper")
        gone(app_code, "st_val in (WRONG, UNKNOWN, LOGIN_DROPPED)",
             "P0 the shadowed WRONG/UNKNOWN branch is re-gated")

        # ---- P0-v13.39: TLS switch, STATE caches, mobile, hero guard ----
        has(app, "def tls_connect(host, port, proxy_str=None, insecure=None, timeout=None):",
            "P0 tls_connect resolves insecure from CFG")
        has(app, "TLS_STRICT is ON so NOT falling back", "P0 TLS_STRICT is honoured")
        has(app, '"TLS_STRICT": not self_signed', "P0 TLS_STRICT follows the checkbox")
        has(app, '_STARTUP_SEEN = STATE.setdefault("startup_seen", set())',
            "P0 startup dedupe set is STATE-backed")
        has(app, '_DNS_CACHE = STATE.setdefault("dns_cache", {})',
            "P0 DNS cache is STATE-backed")
        has(app, '_PERSISTENT_VALID_CACHE = STATE.setdefault("persistent_valid_cache"',
            "P0 valid cache is STATE-backed")
        has(app, '_geo_last_call = STATE.setdefault("geo_last_call"',
            "P0 geo throttle state is STATE-backed")
        has(app, "def metric_grid(pairs, per_row: int = 3):", "P0 metrics wrap per row")
        has(app, "initial_sidebar_state=\"collapsed\"", "P0 sidebar starts collapsed")
        has(app, "if BUILD_TAG not in str(base.get(\"hero_title\", \"\")):",
            "P0 load_theme cannot advertise an old build")
        has(app, "def _MOBILE_CSS", "P0 mobile stylesheet present")
        has(app, "if _status in (FAILED, CONNECTION_FAILED, PROXY_UNHEALTHY, RETRY, RETRY_LATER,",
            "P0 FAST_MODE cooldown only arms on inconclusive results")

        has(app, "def _resolve_cached(", "P1 shared DNS TTL cache present")
        has(app, "return _resolve_cached(host) is not None",
            "P1 fast_fail_dns_check uses the shared cache")
        gone(app_code, "return filtered if filtered else raw",
             "P1 filter no longer silently falls back to the raw list")
        has(app, "while page <= 20:", "P1 fetch_ws paginates")
        has(app, "GEO_FAIL_TTL = 300.0", "P1 geo negative-cache TTL present")
        has(app, "GEO_MIN_INTERVAL", "P1 geo throttle constant present")
        has(app, '_GEO_FAIL = STATE.setdefault("geo_fail", {})',
            "P1 geo negative cache is STATE-backed")
        has(app, "_geo_last_call", "P1 geo throttle state present")

        # ---- P2 ----
        has(app, "_STARTUP_MAX = 400", "P2 startup log cap present")
        has(app, "if msg in _STARTUP_SEEN:", "P2 dedupe compares the MESSAGE")
        has(app, "checked_count % 100 == 0", "P2 checkpoint writes every 100 accounts")
        has(app, "def _estimated_rung_count(", "P2 rung count is derived")
        has(app, "rungs = _estimated_rung_count()", "P2 request_budget uses it")
        gone(app_code, "rungs = 8", "P2 hardcoded rungs = 8 gone")
        has(app, "PROXY_SUBUSER_CONCURRENCY", "P2 per-sub-user concurrency gate present")
        has(app, "MAIL_SPOT_NODES", "P2 mail-destination spot check present")

        # ---- P3 ----
        has(app, 'return "VPN ? (lookup failed)"', "P3 VPN state admits a failed lookup")

        # ---- dead code that must be gone from the CODE (the docstring may name it)
        for dead in ("def _cached_probe(", "def test_single_proxy(",
                     "def proxy_tunnel_ok(", "def _pool_exhausted(",
                     "SETTING_WIDGET_KEYS", "PUBLIC_PROVIDERS", "_targets_key",
                     "_TUNNEL_TTL", "_tunnel_lock",
                     "_DOMAIN_IMAP_GUESS", "_DOMAIN_POP_GUESS",
                     "read_timeout", "_is_plain_domain_guess"):
            gone(app_code, dead, "dead code removed: " + dead)
        gone(app, 'STATE["tunnel_cache"]', "dead tunnel_cache state key removed")

        # ---- kept on purpose ----
        has(app, "PROVIDER_MAP = {", "PROVIDER_MAP kept as the hosts.py fallback")
        has(app, "def clear_tunnel_cache(", "clear_tunnel_cache kept")
        has(app, "def _guess_candidates(", "_guess_candidates kept")
        has(app, "HOSTS_HAS_RANKING", "HOSTS_HAS_RANKING kept")
        has(app, "CFG_VERSION = 1340", "CFG_VERSION is 1340")
        has(app, 'BUILD_TAG = "v13.40"', "BUILD_TAG is the single build string")

    if req:
        req_code = "\n".join(l.split("#", 1)[0] for l in req.splitlines())
        if "pandas==2.2.3" in req_code:
            FAILS.append("requirements.txt still pins pandas==2.2.3 on an active line "
                         "(no cp314 wheel on the Python 3.14 runtime)")
        else:
            PASSES.append("requirements.txt no longer pins the cp314-less pandas 2.2.3")
        has(req, "streamlit==", "requirements.txt pins streamlit")

    if dia:
        compiles(dia_path, dia)
        tokenizes(dia_path, dia)
        parses(dia_path, dia)
        stray_lines(dia_path, code_view(dia))
        has(dia, "pages/2_Diagnostics.py", "diagnostics page self-identifies as 2_")
        has(dia, "def _protocols_from_app(", "plan reads the real protocol flags")
        has(dia, "applied_cfg", "plan reads the app's applied config")
        has(dia, "pop_only", "false POP warning replaced by a real test")
        has(dia, "elif all_pop_dup", "all_pop branch present")
        has(dia, "tab_cache", "tab_cache still exists")

    if rdr:
        compiles(rdr_path, rdr)
        tokenizes(rdr_path, rdr)
        parses(rdr_path, rdr)
        stray_lines(rdr_path, code_view(rdr))
        has(rdr, "pages/3_Mailbox_Reader.py", "reader page self-identifies as 3_")
        has(rdr, "class MsVerdict(", "MsVerdict exception defined")
        has(rdr, "def _reader_proxy_reachable(", "reader proxy probe helper present")
        has(rdr, "def _reader_proxy_str(", "reader proxy rotate helper present")
        has(rdr, "def merge_into_clean_valid(", "reader merges clean_valid")
        has(rdr, "def _valid_fingerprint(", "valid-list mtime cache present")
        has(rdr, "MsVerdict(", "MsVerdict is actually raised")
        # ---- v13.39 reader fixes ----
        has(rdr, "def _looks_like_login_drop(", "reader knows about a * BYE drop")
        has(rdr, "elif _looks_like_login_drop(classify_src):",
            "reader reports LOGIN_DROPPED instead of FAILED")
        has(rdr, "status_type = \"LOGIN_DROPPED\"", "reader has a LOGIN_DROPPED status")
        has(rdr, "for _ptype in (socks.SOCKS5, socks.HTTP):",
            "reader proxy probe tries HTTP as well as SOCKS5")
        has(rdr, "def _cfg_verify()", "reader reads allow_self_signed")
        has(rdr, "verify=_verify", "reader implicit rung honours the switch")
        has(rdr, "_mail_tls_context(_verify)", "reader STARTTLS rung honours the switch")
        has(rdr, 'st.session_state.app_config["allow_self_signed"] = new_selfsigned',
            "reader saves the self-signed checkbox")
        has(rdr, "for item in pool[:5]:", "reader probes 5 nodes, not 8")
        has(rdr, "initial_sidebar_state=\"collapsed\"", "reader sidebar starts collapsed")
        has(rdr, "/* ---- v13.39 MOBILE FIT ---- */", "reader has the mobile stylesheet")

    page_numbers()

    print("=" * 62)
    print("PASSED %d   FAILED %d" % (len(PASSES), len(FAILS)))
    for f in FAILS:
        print("  - " + f)
    print("=" * 62)
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
