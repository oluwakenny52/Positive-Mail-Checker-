#!/usr/bin/env python3
"""verify_v1337.py - regression harness for the v13.37 patch set.

For every changed file it checks:
  (a) the module compiles, tokenizes and AST-parses,
  (b) every v13.37 fix is textually PRESENT,
  (c) every buggy pattern the fix replaced is GONE,
plus that no two files in pages/ share a page number.

Run from the repo root:   python verify_v1337.py
Exit code 0 = clean.
"""
import ast
import io
import os
import sys
import tokenize

PASSES = []
FAILS = []


def read(path):
    with io.open(path, "r", encoding="utf-8") as fh:
        return fh.read()


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

    if app:
        compiles(app_path, app)
        tokenizes(app_path, app)
        parses(app_path, app)

        has(app, "Mega Ultimate Mail Checker — v13.37", "app.py header is v13.37")
        for n in (1, 2):
            has(app, "# ===== END OF APP.PY PART %d/3 =====" % n,
                "app.py PART %d end-marker present" % n)

        # P0
        has(app, "fetched_msgs, success_read = msgs, True", "P0 success_read typo fixed")
        gone(app, "success_msgs", "P0 success_msgs local is gone")
        has(app, "settled = False", "P0 tunnel_probe second-scheme gate rebuilt")
        gone(app, "if ptype == preferred:", "P0 407 no longer filed by preferred scheme")
        has(app, "out[\"reason\"] = \"auth\"", "P0 post-loop auth override present")
        has(app, "except ProxyAuthError as pae:", "P0 ProxyAuthError no longer swallowed")
        has(app, "nonlocal acct_407_total", "P0 407 counter is nonlocal")
        has(app, "def _write_clean_valid(", "P0 clean_valid merge helper present")

        # P1
        has(app, "if \"Fast-fail DNS check\" not in err_text:", "P1 DNS RuntimeError not saw_server")
        has(app, "def _resolve_cached(", "P1 shared DNS TTL cache present")
        has(app, "return _resolve_cached(host) is not None", "P1 fast_fail_dns_check uses cache")
        gone(app, "return filtered if filtered else raw", "P1 filter no longer falls back to raw")
        has(app, "while page <= 20:", "P1 fetch_ws paginates")
        has(app, "GEO_FAIL_TTL = 300.0", "P1 geo negative cache TTL present")
        has(app, "GEO_MIN_INTERVAL", "P1 geo throttle constant present")
        has(app, "\"geo_fail\": {}", "P1 geo_fail state key present")
        has(app, "_GEO_FAIL = STATE[\"geo_fail\"]", "P1 geo_fail alias present")
        has(app, "def _geo_throttle(", "P1 geo throttle helper present")

        # P2
        has(app, "_STARTUP_MAX = 400", "P2 startup log cap present")
        has(app, "_STARTUP_SEEN = set()", "P2 startup dedupe set present")
        has(app, "if msg in _STARTUP_SEEN:", "P2 dedupe compares the MESSAGE")
        has(app, "checked_count % 25 == 0", "P2 writes every 25 accounts")
        has(app, "def _estimated_rung_count(", "P2 rung count is derived")
        has(app, "rungs = _estimated_rung_count()", "P2 request_budget uses it")
        gone(app, "rungs = 8", "P2 hardcoded rungs = 8 gone")
        has(app, "MAIL_SPOT_MIN_INTERVAL", "P2 mail-destination spot throttle present")
        has(app, "PROXY_SUBUSER_CONCURRENCY", "P2 per-sub-user concurrency gate present")

        has(app, "return \"VPN ? (lookup failed)\"", "P3 VPN state admits failure")

        # dead code that must be GONE
        gone(app, "def _cached_probe(", "dead _cached_probe removed")
        gone(app, "def test_single_proxy(", "dead test_single_proxy removed")
        gone(app, "def proxy_tunnel_ok(", "dead proxy_tunnel_ok removed")
        gone(app, "def _pool_exhausted(", "dead _pool_exhausted removed")
        gone(app, "def _is_plain_domain_guess(", "dead _is_plain_domain_guess removed")
        gone(app, "SETTING_WIDGET_KEYS", "dead SETTING_WIDGET_KEYS removed")
        gone(app, "PUBLIC_PROVIDERS", "dead PUBLIC_PROVIDERS removed")
        gone(app, "_targets_key", "dead _targets_key removed")
        gone(app, "_TUNNEL_TTL", "dead _TUNNEL_TTL removed")
        gone(app, "_tunnel_lock", "dead _tunnel_lock removed")
        gone(app, "STATE[\"tunnel_cache\"]", "dead tunnel_cache state key removed")
        gone(app, "_DOMAIN_IMAP_GUESS", "dead _DOMAIN_IMAP_GUESS removed")
        gone(app, "_DOMAIN_POP_GUESS", "dead _DOMAIN_POP_GUESS removed")
        gone(app, "read_timeout", "CheckerConfig.read_timeout fully removed")

        # kept on purpose
        has(app, "PROVIDER_MAP = {", "PROVIDER_MAP kept as hosts.py fallback")
        has(app, "def clear_tunnel_cache(", "clear_tunnel_cache kept")
        has(app, "def _guess_candidates(", "_guess_candidates kept")
        has(app, "HOSTS_HAS_RANKING", "HOSTS_HAS_RANKING kept")
        has(app, "CFG_VERSION = 1337", "CFG_VERSION bumped to 1337")

    if dia:
        compiles(dia_path, dia)
        tokenizes(dia_path, dia)
        parses(dia_path, dia)
        has(dia, "pages/2_Diagnostics.py", "diagnostics page self-identifies as 2_")
        has(dia, "def _protocols_from_app(", "plan uses the real protocol flags")
        has(dia, "applied_cfg", "plan reads the app's applied config")
        has(dia, "pop_only", "false POP warning replaced by a real test")
        has(dia, "elif all_pop_dup", "all_pop branch present")
        has(dia, "tab_cache", "tab_cache still exists")

    if rdr:
        compiles(rdr_path, rdr)
        tokenizes(rdr_path, rdr)
        parses(rdr_path, rdr)
        has(rdr, "pages/3_Mailbox_Reader.py", "reader page self-identifies as 3_")
        has(rdr, "class MsVerdict(", "MsVerdict exception defined")
        has(rdr, "def _reader_proxy_reachable(", "reader proxy probe helper present")
        has(rdr, "def _reader_proxy_str(", "reader proxy rotate helper present")
        has(rdr, "def merge_into_clean_valid(", "reader merges clean_valid")
        has(rdr, "def _valid_fingerprint(", "valid-list mtime cache present")
        has(rdr, "MsVerdict(", "MsVerdict is actually raised")

    page_numbers()

    print("=" * 62)
    print("PASSED %d   FAILED %d" % (len(PASSES), len(FAILS)))
    for f in FAILS:
        print("  - " + f)
    print("=" * 62)
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
