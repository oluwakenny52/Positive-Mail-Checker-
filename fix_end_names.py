#!/usr/bin/env python3
"""fix_end_names.py - give every bare @@END line its block NAME back.

verify_blocks.py matches '# @@END NNN NAME'.  A bare '# @@END NNN' matches
nothing, so every block reported 'opened while the previous is still open' plus
'has no @@END' - exactly 2 faults per block.

This rewrites ONLY those marker lines.  No code line is touched.
Run once from the repo root:   python fix_end_names.py
"""
import io
import os
import re
import sys

FILES = (
    "app.py",
    "engine.py",
    "status.py",
    "pages/2_Diagnostics.py",
    "pages/3_Mailbox_Reader.py",
    "pages/4_Downloads.py",
    "pages/5_Blocks.py",
)

RE_BLOCK = re.compile(r"^#\s*@@BLOCK\s+(\d{3})\s+([A-Z0-9_]+)\s+deps=([\d,\-]+)\s*$")
RE_END = re.compile(r"^#\s*@@END\s+(\d{3})(\s+[A-Z0-9_]+)?\s*$")


def fix(path):
    if not os.path.exists(path):
        return {"path": path, "state": "absent"}
    with io.open(path, encoding="utf-8") as fh:
        lines = fh.read().splitlines()

    names = {}
    for ln in lines:
        m = RE_BLOCK.match(ln)
        if m:
            names[int(m.group(1))] = m.group(2)

    n_blocks = len(names)
    n_ends = sum(1 for ln in lines if RE_END.match(ln))

    changed = bare = mismatched = 0
    out = []
    for ln in lines:
        m = RE_END.match(ln)
        if not m:
            out.append(ln)
            continue
        bid = int(m.group(1))
        name = names.get(bid)
        if name is None:
            out.append(ln)
            continue
        want = "# @@END %03d %s" % (bid, name)
        if ln == want:
            out.append(ln)
            continue
        if m.group(2) is None:
            bare += 1
        else:
            mismatched += 1
        changed += 1
        out.append(want)

    if changed:
        with io.open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("\n".join(out) + "\n")

    return {"path": path, "state": "ok", "blocks": n_blocks, "ends": n_ends,
            "changed": changed, "bare": bare, "mismatched": mismatched,
            "unclosed": n_blocks - n_ends}


def main():
    print("=" * 74)
    print("@@END NAME REPAIR")
    print("=" * 74)
    total = 0
    problems = []
    for p in FILES:
        r = fix(p)
        if r["state"] == "absent":
            print("  %-32s absent (skipped)" % p)
            continue
        total += r["changed"]
        print("  %-32s %3d block(s)  %3d @@END  repaired %3d (bare %d, mismatched %d)"
              % (p, r["blocks"], r["ends"], r["changed"], r["bare"], r["mismatched"]))
        if r["unclosed"]:
            problems.append("%s: %d block(s) have NO @@END at all"
                            % (p, r["unclosed"]))
    print("")
    print("%d @@END line(s) repaired" % total)
    for p in problems:
        print("  ! " + p)
    print("")

    try:
        import verify_blocks as VB
    except Exception as exc:                       # noqa: BLE001
        print("verify_blocks.py could not be imported: %r" % (exc,))
        return 0

    print("=" * 74)
    print("RE-GATE")
    print("=" * 74)
    fails = 0
    for p in VB.BLOCKED_FILES:
        res = VB.audit(p)
        fails += len(res["fails"])
        print("  %-32s %4d block(s)  %3d fault(s)"
              % (p, len(res["blocks"]), len(res["fails"])))
        for f in res["fails"][:12]:
            print("        - " + f)
        if len(res["fails"]) > 12:
            print("        ... and %d more" % (len(res["fails"]) - 12))
    print("")
    print("TOTAL FAULTS: %d" % fails)
    print("=" * 74)
    return 0


if __name__ == "__main__":
    sys.exit(main())
