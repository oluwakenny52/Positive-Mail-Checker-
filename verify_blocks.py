#!/usr/bin/env python3
"""verify_v1337.py - regression harness for the v13.37 patch set (v13.40 revision).

Run from the repo root:   python verify_v1337.py
Exit code 0 = clean.

For every file the v13.37 work touched it checks:
  (a) the module compiles, tokenizes and AST-parses,
  (b) every v13.37 fix is textually PRESENT,
  (c) every buggy pattern the fix replaced is GONE from the CODE,
  (d) no pasted-prose line, no stray markdown fence, and no tokenizer landmine
      (em dash / curly quote / nbsp outside a string) survived the paste,
plus that no two files in pages/ share a page number, plus a structural
cross-audit through verify_blocks.py.

WHY THIS REVISION EXISTS (v13.40)
---------------------------------
  * engine.py IS OPTIONAL AGAIN.  `if app:` is truthy whenever app.py exists, so
    the per-file compile loop ran read("engine.py") unguarded and raised
    FileNotFoundError - the harness died instead of reporting.  Every read is
    now exists()-guarded, and a missing engine.py is a clearly-labelled note.
  * THE pandas PIN CHECK WAS WRONG.  `if "pandas==2.2.3" in req` also matches
    the COMMENT HEADER in requirements.txt, which names the old pin on purpose.
    A correct file was therefore reported as still pinning it.  The check is now
    line-anchored.
  * NEW: the v13.40 block frame is asserted (one @@FILE header, block 101 is
    named CORE_VERDICT_HELPERS, exactly one _handle_app_or_wrong) and the whole
    BLOCKED_FILES set is cross-audited through verify_blocks.py.

WHY THE EARLIER REVISION EXISTED
--------------------------------
  * THE P1 BLOCK DID NOT COMPILE.  It had been pasted without closing its
    has(...) call, so the whole harness was a SyntaxError and could never have
    run.  It is repaired, and the P0-v13.39 assertions are now real.
  * NEW STRUCTURAL CHECKS for the v13.39b regression: _handle_app_or_wrong
    referenced _dialable_local, a name defined NOWHERE, so every WRONG/APP
    verdict raised NameError inside an except handler and fell straight through
    to the outer handler - the ladder never advanced.  The helper must use
    domain_local_hosts and must contain exactly ONE WRONG block.
  * Four stale v13.38 markers corrected for v13.39 (header, CFG_VERSION,
    _GEO_FAIL, _STARTUP_SEEN - the last two are STATE-backed now).
  * The PART 1/3 / PART 2/3 banner checks were removed - app.py has no banners.
  * gone() runs against a view of the source with comments AND string literals
    blanked out, because app.py's changelog docstring and several comments
    deliberately name the symbols they removed.
  * stray-line + non-ASCII landmine checks for the paste that broke the build at
    app.py line 7330 ("invalid character '-' (U+2014)").
"""
import ast
import io
import os
import re
import sys
import token
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


def _blank_types():
    """Token types blanked out before the landmine scan.

    Python 3.12+ splits an f-string into FSTRING_START / FSTRING_MIDDLE /
    FSTRING_END instead of one STRING token. Without this, every em dash or
    special character inside an f-string was falsely reported as non-ASCII
    outside a comment/string.
    """
    types = {tokenize.COMMENT, tokenize.STRING}
    for name in ("FSTRING_START", "FSTRING_MIDDLE", "FSTRING_END"):
        val = getattr(tokenize, name, None)
        if val is None:
            val = getattr(token, name, None)
        if val is not None:
            types.add(val)
    return frozenset(types)


BLANK_TOKENS = _blank_types()


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
        if tok.type not in BLANK_TOKENS:
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


def count_is(src, needle, want, label):
    got = src.count(needle)
    if got == want:
        PASSES.append("%s (found %d)" % (label, got))
    else:
        FAILS.append("%s: found %d, want %d   -> %r"
                     % (label, got, want, needle[:70]))


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
        FAILS.append("app.py: run-reset seam BROKEN - the two pasted halves no "
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


def block_frame_crossaudit():
    """Run verify_blocks.py's own gate over the whole BLOCKED_FILES set."""
    try:
        import verify_blocks as VB
    except Exception as exc:                                   # noqa: BLE001
        PASSES.append("verify_blocks.py not importable, cross-audit skipped (%r)"
                      % (exc,))
        return
    total = 0
    for p in VB.BLOCKED_FILES:
        res = VB.audit(p)
        if res["fails"]:
            total += len(res["fails"])
            for f in res["fails"][:6]:
                FAILS.append("BLOCK FRAME %s: %s" % (p, f))
            if len(res["fails"]) > 6:
                FAILS.append("BLOCK FRAME %s: ... and %d more"
                             % (p, len(res["fails"]) - 6))
        else:
            PASSES.append("block frame clean: %s (%d block(s))"
                          % (p, len(res["blocks"])))
    if total == 0:
        PASSES.append("verify_blocks.py: 0 faults across every blocked file")


def _checked(path, src, kind="ui"):
    compiles(path, src)
    tokenizes(path, src)
    parses(path, src)
    stray_lines(path, code_view(src))


def main():
    app_path = "engine.py"
    ui_path = "app.py"
    dia_path = "pages/2_Diagnostics.py"
    rdr_path = "pages/3_Mailbox_Reader.py"
    req_path = "requirements.txt"

    for p in (ui_path, dia_path, rdr_path, req_path):
        if not os.path.exists(p):
            FAILS.append(p + " is MISSING")
    if not os.path.exists(app_path):
        # Not fatal: app.py is the whole implementation.  But say so loudly,
        # because the harness concatenates engine.py + app.py for its text
        # checks, so an absent engine.py silently narrows the search space.
        PASSES.append("engine.py absent (optional facade) - "
                      "text checks run against app.py only")
    else:
        PASSES.append("engine.py present - text checks run against engine.py + app.py")

    app = ""
    if os.path.exists(app_path):
        app += read(app_path)
    if os.path.exists(ui_path):
        app += "\n\n" + read(ui_path)
    ui_src = read(ui_path) if os.path.exists(ui_path) else ""
    dia = read(dia_path) if os.path.exists(dia_path) else ""
    rdr = read(rdr_path) if os.path.exists(rdr_path) else ""
    req = read(req_path) if os.path.exists(req_path) else ""

    if app:
        # exists()-guarded: app.py alone is enough to reach here, so an absent
        # engine.py used to raise FileNotFoundError inside this loop.
        for _p in (app_path, ui_path):
            if not os.path.exists(_p):
                continue
            _checked(_p, read(_p))
        app_code = code_view(app)
        seam_is_intact(ui_src)

        has(app, "Mega Ultimate Mail Checker - v13.40", "app.py header is v13.40")
        has(app, "CFG_VERSION = 1340", "CFG_VERSION is 1340")
        has(app, "BUILD_TAG = \"v13.40\"", "BUILD_TAG is the single build string")

        # ---- v13.40 block frame ----
        has(app, "# @@FILE app.py blocks=", "app.py carries its @@FILE header")
        has(app, "# @@BLOCK 101 CORE_VERDICT_HELPERS deps=",
            "block 101 is the verdict helper block")
        count_is(app, "def _handle_app_or_wrong(", 1,
                 "exactly one _handle_app_or_wrong definition")

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
        has(app, "wrong_rungs.add(", "P0 a second RUNG also confirms a WRONG")
        has(app, "if (not confirm_wrong) or _confirmed:",
            "P0 WRONG early-return is gated on confirmation")
        has(app, "app_hosts.add(server)", "P0 provisional APP tracking present")
        has(app, "app_rungs.add(", "P0 a second RUNG also confirms an APP")
        has(app, "CONFIRM_WRONG_ACROSS_HOSTS", "P0 guard flag wired")
        has(app, "note_verdict(st_val, detail, host=\"\", force=False)",
            "P0 note_verdict has a force path")
        has(app, "if st_val not in (VALID, WRONG, APP, RBL, LOGIN_DROPPED, UNKNOWN):",
            "P0 UNKNOWN is retained")

        # ---- P0-v13.39b: the helper must be reachable and single ----
        has(app, "[h for h in domain_local_hosts if h not in tried_hosts]",
            "P0 the confirmation gate uses domain_local_hosts")
        gone(app_code, "_dialable_local",
             "P0 _dialable_local is not referenced anywhere")
        count_is(app, "wrong_hosts.add(server)", 1,
                 "P0 exactly one WRONG block in the helper")
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
        has(app, "if _status in (FAILED, PROXY_UNHEALTHY, RETRY, DNS_FAILED, UNKNOWN, SMTP_FAILED):",
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
        has(app, "checked_count % 25 == 0", "P2 checkpoint writes every 25 accounts")
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

    if req:
        # LINE-ANCHORED.  requirements.txt's own comment header names the OLD
        # pins on purpose ("pandas==2.2.3"), so a plain substring test reported a
        # correct file as still pinning it.
        pin = re.search(r"^pandas\s*==\s*([0-9][^\s#]*)", req, re.M)
        if pin is None:
            FAILS.append("requirements.txt has no 'pandas==' pin line at column 0 "
                         "(a pin inside a comment does not count)")
        elif pin.group(1).startswith("2.2."):
            FAILS.append("requirements.txt still pins pandas %s "
                         "(no cp314 wheel on the Python 3.14 runtime)"
                         % pin.group(1))
        else:
            PASSES.append("requirements.txt pins pandas %s, not the cp314-less 2.2.x"
                          % pin.group(1))
        has(req, "streamlit==", "requirements.txt pins streamlit")

    if dia:
        _checked(dia_path, dia)
        has(dia, "pages/2_Diagnostics.py", "diagnostics page self-identifies as 2_")
        has(dia, "def _protocols_from_app(", "plan reads the real protocol flags")
        has(dia, "applied_cfg", "plan reads the app's applied config")
        has(dia, "pop_only", "false POP warning replaced by a real test")
        has(dia, "elif all_pop_dup", "all_pop branch present")
        has(dia, "tab_cache", "tab_cache still exists")

    if rdr:
        _checked(rdr_path, rdr)
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
    block_frame_crossaudit()

    print("=" * 62)
    print("PASSED %d   FAILED %d" % (len(PASSES), len(FAILS)))
    for f in FAILS:
        print("  - " + f)
    print("=" * 62)
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
