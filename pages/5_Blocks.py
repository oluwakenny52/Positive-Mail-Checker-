# @@FILE pages/5_Blocks.py blocks=9 version=v13.40
# @@BLOCK 000 FILE_HEADER deps=-
"""
pages/5_Blocks.py - Block Inspector  (v13.40)
=============================================
Validates the @@BLOCK frame of every big file IN THE BROWSER, so you never
need a terminal, and lets you VALIDATE A PASTE before you commit it.

Uses verify_blocks.py from the repo root as the single source of truth.
"""

import os
import sys
from datetime import datetime

import streamlit as st
# @@END 000


# @@BLOCK 001 PAGE_CONFIG deps=000
st.set_page_config(page_title="Blocks - Mail Checker", page_icon="🧱",
                   layout="wide", initial_sidebar_state="collapsed")
# @@END 001


# @@BLOCK 002 IMPORT_VERIFY_BLOCKS deps=000
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

try:
    import verify_blocks as VB
except Exception as _e:
    st.error(f"verify_blocks.py could not be imported from {ROOT}: {_e}")
    st.caption("It must sit in the repo ROOT, next to app.py - not inside pages/.")
    st.stop()
# @@END 002


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
# @@END 003


# @@BLOCK 004 HERO deps=003
st.markdown(
    '<div class="bl-hero"><h1>🧱 Block Inspector</h1>'
    '<p>Frame integrity for every block file, plus paste validation before you commit.</p></div>',
    unsafe_allow_html=True,
)
# @@END 004


# @@BLOCK 005 TABS deps=004
tab_scan, tab_paste, tab_how = st.tabs(["📋 Scan the repo", "🧪 Validate a paste", "📖 How to replace a block"])
# @@END 005


# @@BLOCK 006 TAB_SCAN deps=005
with tab_scan:
    if st.button("🔁 Re-scan now", type="primary"):
        st.rerun()

    results = VB.audit_all()
    total_blocks = sum(len(r["blocks"]) for r in results.values())
    total_fails = sum(len(r["fails"]) for r in results.values())

    c1, c2, c3 = st.columns(3)
    c1.metric("Files checked", len(results))
    c2.metric("Blocks found", total_blocks)
    c3.metric("Failures", total_fails)

    if total_fails == 0 and total_blocks:
        st.success("Frame is intact on every block file.")
    elif total_fails:
        st.error(f"{total_fails} structural fault(s) - details under each file below.")

    st.caption(f"Scanned at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    for path, res in results.items():
        label = f"{path}  -  {len(res['blocks'])} block(s), {len(res['fails'])} fault(s)"
        with st.expander(label, expanded=bool(res["fails"])):
            if not res["blocks"] and not res["fails"]:
                st.caption("File absent - skipped.")
                continue
            if res["fails"]:
                st.markdown("**Faults**")
                for f in res["fails"][:40]:
                    st.code(f, language="text")
                if len(res["fails"]) > 40:
                    st.caption(f"... and {len(res['fails']) - 40} more")
            if res["table"]:
                st.markdown("**Manifest**")
                st.dataframe(res["table"], use_container_width=True, hide_index=True)
# @@END 006


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
                st.error(f"{len(res['fails'])} fault(s) found:")
                for f in res["fails"][:40]:
                    st.code(f, language="text")
            if res["table"]:
                st.markdown("**Blocks found in the paste**")
                st.dataframe(res["table"], use_container_width=True, hide_index=True)

            if target in VB.BLOCKED_FILES and os.path.exists(os.path.join(ROOT, target)):
                disk = VB.block_ids(os.path.join(ROOT, target))
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
# @@END 007


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
# @@END 008
