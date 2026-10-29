#!/usr/bin/env python3
"""verify_v1337.py - regression harness for the v13.37 patch set (v13.47 revision).

Run from the repo root:   python verify_v1337.py
Exit code 0 = clean.

For every file the v13.37 work touched it checks:
  (a) the module compiles, tokenizes and AST-parses,
  (b) every v13.37 fix is textually PRESENT,
  (c) every buggy pattern the fix replaced is GONE from the CODE,
  (d) no pasted-prose line, no stray markdown fence, and no tokenizer landmine
      (em dash / curly quote / nbsp outside a string) survived the paste,
plus that no two files in pages/ share a page number, that the build identity in
app.py, its @@FILE header and pages/6_User_Guide.py all agree, and that every
auth.<name> a page CALLS is actually defined in auth.py.

WHY THIS REVISION EXISTS (v13.47)
---------------------------------
  * BUILD IDENTITY IS DERIVED, NOT HARDCODED.  The harness used to assert the
    literals "CFG_VERSION = 1340" and 'BUILD_TAG = "v13.40"'.  app.py moved to
    1347 / v13.47 and the gate went red on every single bump until someone
    hand-edited the needle - a gate that has to be re-written to stay true is
    not a gate.  The version is now read out of app.py's own @@FILE header and
    the two constants must match it, so the header, the constants and the guide
    can only ever agree.  Each constant must also appear exactly once, which
    catches an override (a second assignment silently wins by rebinding).
  * pages/6_User_Guide.py is gated too: it mirrors block 008 by design and now
    cannot drift from it.
  * auth_api() compares every auth.<name> a page CALLS against the names auth.py
    actually defines.  The fit_panel AttributeError shipped because nothing ever
    compared the two: the callers were updated, the module was not, and every
    gate stayed green.  The match is anchored on the call paren so that the
    prose "auth.py" does not read as a call to a function named py.
  * A NOTE (not a failure) is printed for any block file whose own header
    version trails the app, so the drift stays visible without breaking CI.

WHY THE EARLIER REVISION EXISTED (v13.39b)
------------------------------------------
  * THE P1 BLOCK DID NOT COMPILE.  It had been pasted without closing its
    has(...) call, so the whole harness was a SyntaxError and could never have
    run.  It is repaired, and the P0-v13.39 assertions are now real.
  * NEW STRUCTURAL CHECKS for the v13.39b regression: _handle_app_or_wrong
    referenced _dialable_local, a name defined NOWHERE, so every WRONG/APP
    verdict raised NameError inside an except handler and fell straight through
    to the outer handler - the ladder never advanced.  The helper must use
    domain_local_hosts and must contain exactly ONE WRONG block (the duplicate
    copy was dead code sitting after a return).

WHY THE EARLIER REVISION EXISTED
--------------------------------
  * The PART 1/3 / PART 2/3 banner checks were removed - app.py has no banners.
  * "settled = False", "def _geo_throttle(", '"geo_fail": {}',
    '_GEO_FAIL = STATE["geo_fail"]' and "MAIL_SPOT_MIN_INTERVAL" do not exist in
    app.py; the real markers are checked instead.
  * gone() now runs against a view of the source with comments AND string
    literals blanked out, because app.py's changelog docstring and several
    comments deliberately name the symbols they removed.
  * stray-line + non-ASCII landmine checks for the paste that broke the build
    at app.py line 7330 ("invalid character '-' (U+2014)").
"""
import ast
import io
import os
import re
import sys
import tokenize

PASSES = []
FAILS = []
NOTES = []


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


def exactly(src_code, needle, want, label):
    """`needle` must appear `want` times in the CODE view (duplicate/override)."""
    n = src_code.count(needle)
    if n == want:
        PASSES.append(label)
    else:
        FAILS.append("%s: %r appears %d x, want %d" % (label, needle, n, want))


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

# name, blocks=N, version=vNN.NN  - the identity every block file carries
FILE_HDR = re.compile(
    r"^#\s*@@FILE\s+(\S+)\s+blocks=\d+\s+version=v(\d+)\.(\d+)\s*$", re.M)


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
        FAILS.append("app.py: run-reset seam BROKEN - the two pasted halves no "
                     "longer join around run_completion_status / start_dt")


def build_identity(app, app_code, gui, gui_code):
    """CFG_VERSION / BUILD_TAG derive from app.py's @@FILE header.

    The header is line 1 and the constants live in block 008.  All three must
    agree, each constant exactly once, and pages/6 block 001 must mirror them.
    """
    m = FILE_HDR.search(app)
    if not m or m.group(1) != "app.py":
        FAILS.append("app.py line 1 has no parseable "
                     "'# @@FILE app.py blocks=N version=vNN.NN' header")
        return
    major, minor = m.group(2), m.group(3)
    tag = "v%s.%s" % (major, minor)
    has(app, "CFG_VERSION = %s%s" % (major, minor),
        "CFG_VERSION matches the header version (%s%s)" % (major, minor))
    has(app, 'BUILD_TAG = "%s"' % tag,
        "BUILD_TAG is the single build string (%s)" % tag)
    exactly(app_code, "CFG_VERSION =", 1, "CFG_VERSION is assigned once")
    exactly(app_code, "BUILD_TAG =", 1, "BUILD_TAG is assigned once")

    if gui:
        has(gui, "CFG_VERSION = %s%s" % (major, minor),
            "pages/6_User_Guide.py CFG_VERSION mirrors app.py")
        has(gui, 'BUILD_TAG = "%s"' % tag,
            "pages/6_User_Guide.py BUILD_TAG mirrors app.py")
        exactly(gui_code, "CFG_VERSION =", 1,
                "pages/6_User_Guide.py assigns CFG_VERSION once")
        exactly(gui_code, "BUILD_TAG =", 1,
                "pages/6_User_Guide.py assigns BUILD_TAG once")


AUTH_CALLERS = ("app.py", "pages/3_Mailbox_Reader.py", "pages/4_Downloads.py",
                "pages/5_Blocks.py", "pages/6_User_Guide.py")

# anchored on the call paren: bare `auth.py` in prose must not read as auth.py()
AUTH_CALL = re.compile(r"\bauth\.([A-Za-z_]\w*)\s*\(")

AUTH_REQUIRED = ("fit", "fit_panel", "require", "user_file")


def auth_api():
    """Every auth.<name> a page CALLS must exist in auth.py.

    The AttributeError for fit_panel shipped because nothing compared the two:
    the callers were updated, the module was not, and every gate was green.
    """
    if not os.path.exists("auth.py"):
        FAILS.append("auth.py is MISSING")
        return
    mod = read("auth.py")
    defined = set(re.findall(r"^def\s+([A-Za-z_]\w*)\s*\(", mod, re.M))
    for c in AUTH_CALLERS:
        if not os.path.exists(c):
            continue
        called = sorted(set(AUTH_CALL.findall(read(c))))
        if not called:
            NOTES.append("%s calls no auth.<name> - nothing to compare" % c)
        for name in called:
            if name in defined:
                PASSES.append("%s: auth.%s exists" % (c, name))
            else:
                FAILS.append("%s calls auth.%s, which auth.py does not define"
                             % (c, name))
    for need in AUTH_REQUIRED:
        if need in defined:
            PASSES.append("auth.py defines %s" % need)
        else:
            FAILS.append("auth.py does not define %s" % need)


def version_drift(paths):
    """NOTE (not a failure) for a gated file whose header version trails app.py."""
    app = read("app.py") if os.path.exists("app.py") else ""
    m = FILE_HDR.search(app)
    if not m:
        return
    want = (int(m.group(2)), int(m.group(3)))
    for p in paths:
        if not os.path.exists(p):
            continue
        pm = FILE_HDR.search(read(p))
        if not pm:
            NOTES.append("%s header has no version=vNN.NN" % p)
            continue
        got = (int(pm.group(2)), int(pm.group(3)))
        if got < want:
            NOTES.append("%s header is v%d.%d, app.py is v%d.%d - bump it with "
                         "the app or it will name a build that no longer exists"
                         % (p, got[0], got[1], want[0], want[1]))


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
    gui_path = "pages/6_User_Guide.py"
    req_path = "requirements.txt"

    for p in (app_path, dia_path, rdr_path, gui_path, req_path):
        if not os.path.exists(p):
            FAILS.append(p + " is MISSING")

    app = read(app_path) if os.path.exists(app_path) else ""
    dia = read(dia_path) if os.path.exists(dia_path) else ""
    rdr = read(rdr_path) if os.path.exists(rdr_path) else ""
    gui = read(gui_path) if os.path.exists(gui_path) else ""
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

        # ---- build identity: derived from the header, never hardcoded ----
        build_identity(app, app_code, gui, code_view(gui) if gui else "")

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

    if gui:
        compiles(gui_path, gui)
        tokenizes(gui_path, gui)
        parses(gui_path, gui)
        stray_lines(gui_path, code_view(gui))
        has(gui, "pages/6_User_Guide.py", "guide self-identifies as 6_")
        # exactly once each: a second fit() raises inside its own try/except and
        # a second fit_panel() draws the sliders twice.
        exactly(code_view(gui), "auth.fit(st)", 1, "guide calls auth.fit() exactly once")
        exactly(code_view(gui), "auth.fit_panel(st)", 1,
                "guide calls auth.fit_panel() exactly once")
        exactly(code_view(gui), "auth.require(", 1, "guide calls auth.require() exactly once")
        exactly(code_view(gui), "def ug_card(", 1, "ug_card() defined once")
        exactly(code_view(gui), "def ug_h(", 1, "ug_h() defined once")
        gone(code_view(gui), "import auth\nimport auth", "auth not imported twice")

    auth_api()
    page_numbers()
    version_drift(["engine.py", "status.py", "verify_blocks.py", "ms_oauth.py"])

    print("=" * 62)
    print("PASSED %d   FAILED %d" % (len(PASSES), len(FAILS)))
    for f in FAILS:
        print("  - " + f)
    for n in NOTES:
        print("  note: " + n)
    print("=" * 62)
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
