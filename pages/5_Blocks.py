# @@FILE pages/5_Blocks.py blocks=12 version=v13.47
# @@BLOCK 000 FILE_HEADER deps=-
"""
pages/5_Blocks.py - Block Inspector  (v13.47)
=============================================
Validates the @@BLOCK frame of every big file IN THE BROWSER, so you never
need a terminal, and lets you VALIDATE A PASTE before you commit it.

Uses verify_blocks.py from the repo root as the single source of truth.

Headless mode for CI (gate 11) - no Streamlit server and no streamlit import:

    python3 pages/5_Blocks.py --fix-check

v13.47: block 004 calls auth.fit_panel() in browser mode only. auth.fit() injects
the CSS, so without the panel call the Display Fit control was missing here. The
call stays inside the `if not _CLI_FIX_CHECK:` branch so `--fix-check` still runs
without importing Streamlit. The expander stays collapsed until it is tapped.

The reload guard is INSIDE that branch too. Left at module level, `--fix-check`
reached `auth.fit_panel` with `auth` never imported - a NameError, which
`except AttributeError` does not catch - so gate 11 died with a traceback. The
require/fit/fit_panel calls are also OUTSIDE the except: nested inside it, they
only ran when the module was stale, so a healthy module rendered the page with
no passkey gate and no Display Fit panel.

The guard itself is hasattr() + importlib.reload(), NOT a bare `auth.fit_panel`
expression inside a try. The bare form is magic-written by Streamlit, which
routes it through st.help -> ast.parse and can raise IndentationError on the
enclosing `try:` - and it dumps a help panel onto the page.
"""

import os
import sys
from datetime import datetime

_CLI_FIX_CHECK = "--fix-check" in sys.argv


class _BareNoop:
    """Absorbs any st.* call made outside a Streamlit runtime."""

    def __call__(self, *a, **k):
        if len(a) == 1 and not k and callable(a[0]):
            return a[0]                      # used as a bare decorator
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __getattr__(self, name):
        return _BareNoop()


class _BareSt:
    """Minimal st.* surface, so blocks 001-010 run unchanged under plain python3."""

    def __init__(self):
        # per-instance, not a class attribute: two _BareSt()s must not share state
        self.session_state = {}

    def __getattr__(self, name):
        return _BareNoop()

    def tabs(self, labels):
        return [_BareNoop() for _ in labels]

    def columns(self, spec):
        return [_BareNoop() for _ in range(spec)]

    def button(self, *a, **k):
        return False

    def selectbox(self, label, options, **k):
        return list(options)[0]

    def text_area(self, *a, **k):
        return ""

    def stop(self):
        raise SystemExit(2)


if _CLI_FIX_CHECK:
    st = _BareSt()          # bare mode: nothing here needs a real runtime
else:
    import streamlit as st
# @@END 000 FILE_HEADER


# @@BLOCK 001 PAGE_CONFIG deps=000
st.set_page_config(page_title="Blocks - Mail Checker", page_icon="🧱",
                   layout="wide", initial_sidebar_state="collapsed")
# @@END 001 PAGE_CONFIG


# @@BLOCK 002 IMPORT_VERIFY_BLOCKS deps=000
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

try:
    import verify_blocks as VB
except Exception as _e:
    if _CLI_FIX_CHECK:
        sys.stderr.write("FIX-CHECK: verify_blocks.py not importable from %s: %s\n"
                         % (ROOT, _e))
        raise SystemExit(2)
    st.error(f"verify_blocks.py could not be imported from {ROOT}: {_e}")
    st.caption("It must sit in the repo ROOT, next to app.py - not inside pages/.")
    st.stop()
# @@END 002 IMPORT_VERIFY_BLOCKS


# @@BLOCK 003 CSS deps=000
st.markdown(
    """
<style>
    .bl-hero {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        padding: 18px 24px; border-radius: 14px; margin-bottom: 14px;
        border: 1px solid rgba(255,255,255,.12);
    }
    .bl-hero h1 { color: #fff !important; margin: 0; font-size: 1.45rem; font-weight: 800; }
    .bl-hero p { color: rgba(255,255,255,.92) !important; margin: 6px 0 0 0; font-size: .84rem; }
    .block-container { padding-top: 1.2rem !important; padding-bottom: 2rem !important; }
    @media (max-width: 820px) {
        .block-container { padding: .55rem .7rem 1.3rem .7rem !important; }
        .bl-hero h1 { font-size: 1.1rem; }
        pre, code { font-size: .68rem !important; }
    }
</style>
""",
    unsafe_allow_html=True,
)
# @@END 003 CSS


# @@BLOCK 004 HERO deps=000,003
st.markdown(
    '<div class="bl-hero"><h1>🧱 Block Inspector</h1>'
    '<p>Frame integrity for every block file, plus paste validation before you commit.</p></div>',
    unsafe_allow_html=True,
)

# auth is imported ONLY in browser mode.  Imported unconditionally it drags
# Streamlit in through auth.py and breaks block 000's promise that
# `--fix-check` needs no streamlit import at all.
#
# The whole guard lives inside that branch for the same reason: at module level
# `auth.fit_panel` is reached with `auth` never bound, and the resulting
# NameError is not an AttributeError, so --fix-check died here.
if not _CLI_FIX_CHECK:
    import importlib

    import auth

    # hasattr(), not a bare `auth.fit_panel` expression: the bare form is
    # magic-written by Streamlit (st.help -> ast.parse) and can raise
    # IndentationError on the enclosing `try:`.
    if not hasattr(auth, "fit_panel"):
        auth = importlib.reload(auth)

    auth.require(st, "Unlock Block Inspector")
    auth.fit(st)                        # CSS only, before the first widget
    auth.fit_panel(st)                  # the controls; collapsed until tapped

    # v13.48: click/outcome ledger. INSIDE the branch - audit_log needs the real
    # st (the _BareSt stand-in has no working session_state for the pending
    # entry), and the branch is what keeps --fix-check free of Streamlit.
    import audit_log

    audit_log.install(st, "pages/5_Blocks.py")
# @@END 004 HERO


# @@BLOCK 005 TABS deps=004
tab_scan, tab_paste, tab_how = st.tabs(["📋 Scan the repo", "🧪 Validate a paste", "📖 How to replace a block"])
# @@END 005 TABS


# @@BLOCK 006 TAB_SCAN deps=005
with tab_scan:
    if st.button("🔁 Re-scan now", type="primary"):
        st.rerun()

    # CLI mode does not need the scan: block 011 prints only run_fix_check() rows
    # and everything here is a st.* noop under _BareSt.  Skipping it keeps the gate
    # off a full parse+compile of all twelve files it would then throw away.
    results = {} if _CLI_FIX_CHECK else VB.audit_all()
    total_blocks = sum(len(r["blocks"]) for r in results.values())
    total_fails = sum(len(r["fails"]) for r in results.values())

    # The frame size is READ, never quoted: verify_blocks.py owns the target and
    # audit_frame.py imports the same two names. A stale number cannot hide in a
    # doc or in this page.
    _tgt_files = getattr(VB, "TARGET_FILES", 0)
    _tgt_blocks = getattr(VB, "TARGET_BLOCKS", 0)

    c1, c2, c3 = st.columns(3)
    c1.metric("Files / target %d" % _tgt_files, len(results))
    c2.metric("Blocks / target %d" % _tgt_blocks, total_blocks)
    c3.metric("Failures", total_fails)

    if total_fails == 0 and total_blocks:
        st.success("Frame is intact on every block file.")
    elif total_fails:
        st.error(f"{total_fails} structural fault(s) - details under each file below.")

    if (len(results) != _tgt_files) or (total_blocks != _tgt_blocks):
        st.warning(
            "Frame size has DRIFTED: target %d file(s) / %d block(s), found %d / %d. "
            "If the move is real, edit TARGET_FILES/TARGET_BLOCKS in verify_blocks.py "
            "- that is the only place, and tier2_split.py prints the new line."
            % (_tgt_files, _tgt_blocks, len(results), total_blocks))

    st.caption(f"Scanned at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # v13.41: a phone cannot multi-select inside st.code(), so the fault list is
    # JOINED into one box per file (one copy icon) instead of one box per fault.
    # Nothing is truncated now - the old [:40] slice also hid the tail.
    def _file_report(path, res):
        L = [f"FILE={path}",
             f"exists={res.get('exists')} blocks={len(res['blocks'])} "
             f"faults={len(res['fails'])}"]
        if res["fails"]:
            L.append("-- faults --")
            L.extend(res["fails"])
        if res["table"]:
            L.append("-- blocks --")
            L.extend("%03d %s (line %d)" % (b["id"], b["name"], b["line"])
                     for b in res["table"])
        return "\n".join(L)

    _everything = "\n\n".join(_file_report(p, r) for p, r in results.items())

    with st.expander(f"📋 Copy the WHOLE scan ({total_fails} fault(s))",
                     expanded=bool(total_fails)):
        st.caption("Tap the copy icon at the top-right of the box, then paste it back.")
        st.code(_everything, language="text")
        st.download_button("⬇️ Download the scan as .txt",
                           data=_everything.encode("utf-8"),
                           file_name="blocks_scan_%s.txt"
                                     % datetime.now().strftime("%Y%m%d_%H%M%S"),
                           mime="text/plain",
                           width="stretch")

    for path, res in results.items():
        label = f"{path}  -  {len(res['blocks'])} block(s), {len(res['fails'])} fault(s)"
        with st.expander(label, expanded=bool(res["fails"])):
            if not res.get("exists"):
                st.caption("File absent - skipped.")
                continue
            st.code(_file_report(path, res), language="text")
            if res["table"]:
                st.markdown("**Manifest**")
                st.dataframe(res["table"], width="stretch", hide_index=True)
# @@END 006 TAB_SCAN


# @@BLOCK 007 TAB_PASTE deps=005
with tab_paste:
    st.caption(
        "Paste a WHOLE file here and check it before committing. This is the same "
        "engine the CLI runs, so if it is green here it is green there."
    )
    target = st.selectbox("Which file is this paste meant to be?",
                          list(VB.BLOCKED_FILES) + ["(something else)"])
    src = st.text_area("Paste the full file contents", height=260, key="bl_paste")

    if st.button("✅ Validate paste", type="primary"):
        if not src.strip():
            st.warning("Nothing pasted.")
        else:
            res = VB.audit_source(src, target)
            if res["ok"]:
                st.success(f"Frame OK - {len(res['blocks'])} block(s), ids contiguous, "
                           f"all closed, file compiles.")
            else:
                # v13.43: no [:40] slice - the count above already states the total,
                # so a slice only made the list and the number disagree.
                st.error(f"{len(res['fails'])} fault(s) found:")
                for f in res["fails"]:
                    st.code(f, language="text")
            if res["table"]:
                st.markdown("**Blocks found in the paste**")
                st.dataframe(res["table"], width="stretch", hide_index=True)

            if target in VB.BLOCKED_FILES and os.path.exists(os.path.join(ROOT, target)):
                # v13.40: block_ids() returns a LIST. `list - set` has no
                # list.__sub__, so CPython answers with the reflected set
                # subtraction and computes pasted - disk - i.e. `missing` came
                # out identical to `extra`. set() both sides.
                disk = set(VB.block_ids(os.path.join(ROOT, target)))
                pasted = {b[0] for b in res["blocks"]}
                missing = sorted(disk - pasted)
                extra = sorted(pasted - disk)
                if missing:
                    st.warning("Missing block id(s) that exist on disk: "
                               + ", ".join("%03d" % m for m in missing))
                if extra:
                    st.info("Extra block id(s) not on disk: "
                            + ", ".join("%03d" % x for x in extra))
                if not missing and not extra and res["ok"]:
                    st.success("Paste matches the on-disk block set exactly.")
# @@END 007 TAB_PASTE


# @@BLOCK 008 TAB_HOW deps=005
with tab_how:
    st.markdown(
        """
**Replacing a block - the only safe edit**

1. Open the file in the GitHub editor.
2. `Ctrl+F` and search `@@BLOCK 016 ` (include the space).
3. Search again for `@@END 016 `.
4. Select from the `# @@BLOCK 016` line **through** the `# @@END 016` line, inclusive.
5. Paste the replacement over the selection. Nothing outside those two lines changes.

**Rules**

* Never edit inside a block - replace the whole thing.
* Keep the id and the NAME byte-for-byte. `verify_blocks.py` matches on both.
* Blocks must stay in ascending id order, contiguous from `000`.
* Nothing but blanks and comments is allowed between an `@@END` and the next `@@BLOCK`.
* If a block's published names change, its dependent blocks must be replaced too -
  check the `deps=` line.

**Gate before every commit**
"""
    )
# @@END 008 TAB_HOW


# @@BLOCK 009 CANON_END deps=002
# In-browser stand-in for `python fix_end_names.py --apply`, so the frame can be
# repaired from a phone with no terminal.  Rewrites MARKER LINES ONLY.
def canon_end_names(src):
    """Return (fixed_text, changed_count).  Names every bare @@END from its @@BLOCK."""
    names, out, open_id, changed = {}, [], None, 0
    for ln in src.splitlines():
        mb = VB.BLOCK_RX.match(ln)
        if mb:
            if open_id is not None and names.get(open_id):
                _end = "# @@END %03d %s" % (open_id, names[open_id])
                if out and out[-1].strip().startswith("# @@EOF"):
                    out.insert(len(out) - 1, _end)
                else:
                    out.append(_end)
                changed += 1
            out.append(ln)
            open_id = int(mb.group(1))
            names[open_id] = mb.group(2)
            continue
        me = VB.END_RX.match(ln)
        if me and me.group(1):
            bid = int(me.group(1))
            if bid == open_id:
                open_id = None
            if names.get(bid):
                want = "# @@END %03d %s" % (bid, names[bid])
                if ln != want:
                    changed += 1
                out.append(want)
            else:
                out.append(ln)
            continue
        out.append(ln)
    if open_id is not None and names.get(open_id):
        _end = "# @@END %03d %s" % (open_id, names[open_id])
        if out and out[-1].strip().startswith("# @@EOF"):
            out.insert(len(out) - 1, _end)
        else:
            out.append(_end)
        changed += 1
    return "\n".join(out) + "\n", changed


st.divider()
with st.expander("🛠 Canonicalise @@END names (no terminal needed)", expanded=False):
    st.caption("Names every bare '# @@END NNN' from its matching '# @@BLOCK NNN NAME'. "
               "Download the result, then replace the file in GitHub with it.")
    _cn_file = st.selectbox("File to canonicalise", list(VB.BLOCKED_FILES), key="cn_file")
    if st.button("🛠 Canonicalise", type="primary", key="cn_go"):
        try:
            with open(os.path.join(ROOT, _cn_file), encoding="utf-8") as _cn_fh:
                _cn_src = _cn_fh.read()
            _cn_out, _cn_n = canon_end_names(_cn_src)
            _cn_res = VB.audit_source(_cn_out, _cn_file)
            if _cn_res["faults"]:
                st.session_state["cn_msg"] = (
                    f"WARNING: {_cn_res['faults']} fault(s) still present - check the Scan tab.")
            else:
                st.session_state["cn_msg"] = (
                    f"Frame OK. {_cn_n} marker line(s) rewritten, "
                    f"{len(_cn_res['blocks'])} block(s) intact.")
            st.session_state["cn_out"] = _cn_out
            st.session_state["cn_name"] = os.path.basename(_cn_file)
        except Exception as _cn_e:
            st.session_state["cn_msg"] = f"canonicalise failed: {_cn_e}"
            st.session_state["cn_out"] = ""
    if st.session_state.get("cn_msg"):
        if not st.session_state.get("cn_out"):
            st.error(st.session_state["cn_msg"])
        else:
            st.success(st.session_state["cn_msg"])
            st.download_button("⬇️ Download the fixed file",
                               data=st.session_state["cn_out"].encode("utf-8"),
                               file_name=st.session_state.get("cn_name", "fixed.py"),
                               mime="text/plain")
            st.code(st.session_state["cn_out"], language="python")
# @@END 009 CANON_END


# @@BLOCK 010 FIX_CHECK deps=002
# Behavioural companion to the frame scan. verify_blocks proves the @@BLOCK
# frame; it cannot see whether a FIX is still in the code. These are the exact
# strings the fix plan introduced, with the count each must appear at.
# NB: three needles below point at THIS file, so each also matches its own
# literal in this table - their want counts include that +1 self-reference.
# ("importlib.reload(auth)" is NOT one of them: it also appears in block 004,
# but its target is app.py, and the count is taken inside the target file.)
_FIX_CHECKS = (
    ("status.py", "_PROXY_BLOCKED", 2, "proxy-blocked classifies as CONNECTION_FAILED"),
    ("status.py", "best = None", 1, "worse_of no longer seeds with UNKNOWN"),
    ("status.py", "backend|upstream|downstream", 1, "_RETRY owns the transient words"),
    ("app.py", "{len(_untried_local)} local", 2, "_untried_local is reported"),
    ("app.py", "# A 407 is a proxy answer", 1, "a 407 breaks the username loop"),
    ("app.py", "[status.py 006, 007]", 1, "P0-3 ledger pointer"),
    ("pages/3_Mailbox_Reader.py", "login_drop_count += 1", 1, "drop not double counted"),
    ("pages/4_Downloads.py", "template.format(**d)", 1, "delimiter honours spaced templates"),
    ("pages/4_Downloads.py", '_cut = raw.find("|", _colon + 1)', 1, "no pipe truncation"),
    ("pages/5_Blocks.py", "out.insert(len(out) - 1, _end)", 3, "@@EOF stays last"),
    ("pages/5_Blocks.py", "def run_fix_check():", 2, "one implementation, button and CLI"),
    ("pages/5_Blocks.py", "if _CLI_FIX_CHECK:", 4, "CLI dispatch stays wired (000, 002, 011)"),
    ("engine.py", '_conf = getattr(_hosts, "conf", None)', 1, "engine reads hosts.conf"),
    ("engine.py", "state.cooldown_host(rung.host, 30.0)", 1, "cooldown table is armed"),
    ("engine.py", "def _local_to(domain, host):", 1, "pick_verdict checks locality"),
    ("fix_end_names.py", "(\\d{3})", 2, "marker id width matches verify_blocks (RE_BLOCK & RE_END)"),
    ("fix_end_names.py", "gate_faults", 3, "re-gate drives the exit code"),
    ("audit_frame.py", "TARGET_FILES as EXPECT_FILES", 1, "frame target is imported, not duplicated"),
    ("auth.py", "def require(", 1, "passkey gate exists"),
    ("auth.py", "def fit_css(", 1, "display fit exists"),
    ("app.py", "DNS_FAILED, SMTP_FAILED):", 2, "DNS/SMTP verdicts retained"),
    ("auth.py", "_fit_reset", 2, "Display Fit reset flag survives"),
    ("app.py", 'str_lit.session_state["_fit_reset"] = True', 1,
     "Reset Defaults reaches Display Fit"),
    ("pages/3_Mailbox_Reader.py", "auth.fit(st)", 1, "fit() called exactly once per page"),
    ("pages/4_Downloads.py", "from auth import user_file", 1,
     "Export Studio resolves user paths"),
    ("auth.py", "def fit_panel(", 1, "panel is its own function, not part of fit"),
    ("auth.py", "def fit(", 1, "fit() is CSS-only and defined once"),
    ("pages/3_Mailbox_Reader.py", "from auth import user_file", 1,
     "reader resolves per-user paths"),
    ("app.py", "importlib.reload(auth)", 1, "app survives a stale cached auth module"),
    ("auth.py", "def _anon_id(", 1, "pre-unlock identity is never a bare name"),
    ("auth.py", 'return "%s_%s" % (h, name) if name else h', 1, "user_file always prefixes"),
    ("pages/3_Mailbox_Reader.py", "_readable_text(th)", 1,
     "text colour is contrast-checked"),
    ("runstate.py", "def begin(", 1, "unfinished run lifecycle exists"),
    # ---- v13.48 resume / 407 / lag fixes ----
    ("app.py", "sorted(glob.glob(os.path.join(_res, \"unfinished_*.json\")), reverse=True)",
     1, "resume glob uses sorted(), not glob(reverse=)"),
    ("app.py", "def unfinished_remaining_count(", 1, "resume counts accounts, not files"),
    ("app.py", "unfinished_count = unfinished_remaining_count()", 1,
     "the Resume metric uses the helper"),
    ("app.py", "if _is_proxy_auth_fail(s):", 1, "raw 407 text is recognised, not normalised"),
    ("app.py", "executor.shutdown(wait=False)", 1, "a teardown does not drain the queue"),
    ("app.py", "_metric_phs", 2, "metric cells are built once, not per tick"),
    ("app.py", "for _ph, _ml, _mv in zip(_metric_phs, _metric_labels, _vals):", 1,
     "metric cells unpack label AND value, not a bare int"),
    # ---- v13.48 per-user isolation ----
    ("app.py", "own = str_lit.session_state.startup_entries", 1,
     "startup ledger dedupes per session, not per process"),
    ("pages/7_Logs.py", "_RES_IS_MINE", 4, "the log page proves whose directory it reads"),
    ("pages/7_Logs.py", "Strict: only my own directory", 1, "strict mode refuses a shared dir"),
)

# order matters in the verdict tail: a server answer must outrank retryable
_ORDER_CHECKS = (
    ("app.py", 'if flags.get("saw_login_drop"):',
     '    if retryable:\n        return None, RETRY', "LOGIN_DROPPED before retryable"),
)


def run_fix_check():
    """Run every fix check. Returns (rows, bad_count). No Streamlit calls, so the
    button and the CLI share one implementation."""
    _rows, _bad = [], 0
    for _f, _needle, _want, _why in _FIX_CHECKS:
        try:
            with open(os.path.join(ROOT, _f), encoding="utf-8") as _fh:
                _n = _fh.read().count(_needle)
        except Exception as _e:
            _rows.append("ERROR %-26s %r  (%s)" % (_f, _needle, _e))
            _bad += 1
            continue
        _ok = (_n == _want)
        _bad += 0 if _ok else 1
        _rows.append("%s %-26s got %d want %d  %s  [%s]"
                     % ("OK  " if _ok else "FAIL", _f, _n, _want, _needle, _why))
    for _f, _a, _b, _why in _ORDER_CHECKS:
        try:
            with open(os.path.join(ROOT, _f), encoding="utf-8") as _fh:
                _s = _fh.read()
            _ok = (_a in _s) and (_b in _s) and (_s.rindex(_a) < _s.index(_b))
        except Exception as _e:
            _rows.append("ERROR %-26s order check (%s)" % (_f, _e))
            _bad += 1
            continue
        _bad += 0 if _ok else 1
        _rows.append("%s %-26s order  [%s]"
                     % ("OK  " if _ok else "FAIL", _f, _why))
    return _rows, _bad


st.divider()
with st.expander("🧪 Fix self-check (are the behavioural fixes still in?)", expanded=False):
    st.caption("Textual, like the gates: it proves the fix is still THERE, not that it "
               "behaves. A FAIL means the fix was lost in an edit or a repair.")
    if st.button("🧪 Run fix self-check", type="primary", key="fx_go"):
        _rows, _bad = run_fix_check()
        st.session_state["fx_out"] = "\n".join(_rows)
        st.session_state["fx_bad"] = _bad
    if st.session_state.get("fx_out"):
        if st.session_state.get("fx_bad"):
            st.error("%d check(s) FAILED - a fix is missing." % st.session_state["fx_bad"])
        else:
            st.success("All checks OK.")
        st.code(st.session_state["fx_out"], language="text")
# @@END 010 FIX_CHECK


# @@BLOCK 011 CLI_FIX_CHECK deps=000,010
# Headless entry so CI can exercise the self-check with no Streamlit server:
#
#     python3 pages/5_Blocks.py --fix-check
#
# Calls the same run_fix_check() the button calls.
# Exit 0 = every check OK, 1 = at least one check FAILED, 2 = could not run.
if _CLI_FIX_CHECK:
    _rows, _bad = run_fix_check()
    print("FIX-CHECK  pages/5_Blocks.py  (%d check(s))" % len(_rows))
    for _r in _rows:
        print("  " + _r)
    if _bad:
        print("FIX-CHECK: %d check(s) FAILED" % _bad)
        raise SystemExit(1)
    print("FIX-CHECK: OK")
    raise SystemExit(0)
# @@END 011 CLI_FIX_CHECK
# @@EOF
