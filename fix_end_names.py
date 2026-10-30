#!/usr/bin/env python3
"""fix_end_names.py - canonicalise every @@END marker to '# @@END NNN NAME'.

WHY THIS EXISTS
---------------
verify_blocks.py matches '# @@END NNN NAME'.  A bare '# @@END NNN' matches
nothing, so every such block reports TWO faults: 'opened while block NNN is
still open' plus 'has no @@END'.  On this repo that is 2 x 101 = 202 faults
across the five files that still carry bare markers.

WHAT IT TOUCHES
---------------
ONLY marker lines.  No code line is rewritten.  The id and the name are copied
from the matching @@BLOCK, so the frame stays byte-for-byte honest.

MODES
-----
    python fix_end_names.py                  dry run - show what WOULD change
    python fix_end_names.py --apply          rewrite the files
    python fix_end_names.py --check          dry run; exit 1 if changes pending
    python fix_end_names.py --selftest       prove the regexes on fixtures
    python fix_end_names.py --files app.py   only these files

EXIT CODES
----------
    0  clean (or dry run with nothing to do)
    1  malformed marker lines, or --check found pending changes
    2  internal error

WHY THE REGEXES LOOK LIKE THIS
------------------------------
* Markers MUST start at column 0.  The app.py header docstring shows an EXAMPLE
  marker indented by four spaces, so an indent-tolerant regex would match the
  example as well and invent a duplicate block id.
* deps= is OPTIONAL and may be empty or contain spaces.  The old version
  required a non-empty, space-free deps=, which is why it matched nothing and
  reported 'repaired 0'.

WHY THE REPAIR INSERTS BEFORE @@EOF
-----------------------------------
The last line of every block file is '# @@EOF'.  An unclosed FINAL block used to
get its '# @@END' appended BELOW that marker, so the file ended '# @@EOF' then
'# @@END 016 X'.  pages/5_Blocks.canon_end_names() already keeps @@EOF last; this
file now does the same, and the two implementations agree.
"""
import argparse
import io
import os
import re
import sys

# One source of truth: verify_blocks owns the gated file list.  Local copy only
# if the import fails (e.g. run from a directory without verify_blocks.py).
# It MUST mirror verify_blocks.BLOCKED_FILES exactly - it had drifted to nine
# entries, dropping auth.py, hosts.py and verify_blocks.py, which is precisely
# the case where nobody can check it.
try:
    from verify_blocks import BLOCKED_FILES as FILES
except Exception:
    FILES = ("app.py", "auth.py", "engine.py", "hosts.py", "ms_oauth.py",
             "status.py", "verify_blocks.py", "pages/2_Diagnostics.py",
             "pages/3_Mailbox_Reader.py", "pages/4_Downloads.py",
             "pages/5_Blocks.py", "pages/6_User_Guide.py")

RE_ANY_MARKER = re.compile(r"@@(?:BLOCK|END)\b")
RE_BLOCK = re.compile(r"^#\s*@@BLOCK\s+(\d{3})\s+([A-Za-z0-9_]+)"
                      r"\s*(?:deps\s*=\s*([0-9,\-\s]*))?\s*$")
RE_END = re.compile(r"^#\s*@@END\s+(\d{3})(?:\s+([A-Za-z0-9_]+))?\s*$")


def read(path):
    with io.open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def _is_marker_line(ln):
    """True only for a real `# @@BLOCK ...` / `# @@END ...` line at column 0.

    v13.42: the @@ token must be the FIRST thing after the '#'.  A prose comment
    that merely MENTIONS @@BLOCK (pages/5_Blocks.py block 010 has one) used to be
    read as a MALFORMED marker, which made --check exit 1.
    """
    if ln[:1] != "#":
        return False
    return RE_ANY_MARKER.match(ln[1:].strip()) is not None


def _analyse(lines):
    """id -> NAME, ids in file order, duplicate ids, malformed marker lines."""
    names, order, dupes, malformed = {}, [], [], []
    for i, ln in enumerate(lines, 1):
        if not _is_marker_line(ln):
            continue
        m = RE_BLOCK.match(ln)
        if m:
            bid = int(m.group(1))
            if bid in names:
                dupes.append((i, bid, ln))
            else:
                names[bid] = m.group(2)
                order.append(bid)
            continue
        if not RE_END.match(ln):
            malformed.append((i, ln))
    return names, order, dupes, malformed


def _rewrite(lines, names):
    """Return (new_lines, changed, bare, mismatched, inserted, orphan)."""
    out = []
    bare = mismatched = inserted = orphan = 0
    open_id = None
    for ln in lines:
        m = RE_BLOCK.match(ln)
        if m:
            if open_id is not None and names.get(open_id):
                out.append("# @@END %03d %s" % (open_id, names[open_id]))
                inserted += 1
                open_id = None
            out.append(ln)
            open_id = int(m.group(1))
            continue

        m = RE_END.match(ln)
        if m:
            bid = int(m.group(1))
            if bid == open_id:
                open_id = None
            name = names.get(bid)
            if not name:
                orphan += 1
                out.append(ln)
                continue
            want = "# @@END %03d %s" % (bid, name)
            if ln == want:
                out.append(ln)
                continue
            if not (m.group(2) or "").strip():
                bare += 1
            else:
                mismatched += 1
            out.append(want)
            continue

        out.append(ln)

    if open_id is not None and names.get(open_id):
        _end = "# @@END %03d %s" % (open_id, names[open_id])
        if out and out[-1].strip().startswith("# @@EOF"):
            out.insert(len(out) - 1, _end)
        else:
            out.append(_end)
        inserted += 1

    return out, (bare + mismatched), bare, mismatched, inserted, orphan


def process(path, apply_changes):
    if not os.path.exists(path):
        return {"path": path, "state": "absent"}
    lines = read(path).splitlines()
    names, order, dupes, malformed = _analyse(lines)
    out, changed, bare, mismatched, inserted, orphan = _rewrite(lines, names)
    ends = sum(1 for ln in lines if RE_END.match(ln))
    unclosed = len(names) - ends

    if changed or inserted:
        if apply_changes:
            with io.open(path, "w", encoding="utf-8", newline="\n") as fh:
                fh.write("\n".join(out) + "\n")

    return {"path": path, "state": "ok", "blocks": len(names), "ends": ends,
            "changed": changed, "bare": bare, "mismatched": mismatched,
            "inserted": inserted, "orphan": orphan, "unclosed": unclosed,
            "dupes": dupes, "malformed": malformed}


def _selftest():
    print("=" * 74)
    print("REGEX SELF-TEST")
    print("=" * 74)
    cases = [
        (RE_BLOCK, "# @@BLOCK 000 HEAD deps=-", True, "plain marker"),
        (RE_BLOCK, "# @@BLOCK 001 TAIL", True, "deps= omitted"),
        (RE_BLOCK, "# @@BLOCK 002 X deps=", True, "deps= empty"),
        (RE_BLOCK, "# @@BLOCK 003 X deps=1, 2", True, "deps= with spaces"),
        (RE_BLOCK, "# @@BLOCK 004 X deps=000-002", True, "deps= range"),
        (RE_BLOCK, "    # @@BLOCK 005 INDENTED deps=-", False, "indented -> NOT a marker"),
        (RE_BLOCK, "# @@BLOCK 006", False, "no name"),
        (RE_END, "# @@END 000", True, "bare @@END"),
        (RE_END, "# @@END 000 HEAD", True, "named @@END"),
        (RE_END, "# @@END", False, "no id"),
    ]
    bad = 0
    for rx, text, want, label in cases:
        got = rx.match(text) is not None
        ok = got == want
        bad += 0 if ok else 1
        print("  %-4s %-34s %s" % ("OK" if ok else "FAIL", label, repr(text)))

    fixture = ("# @@FILE demo.py blocks=2 version=v1\n"
               "# @@BLOCK 000 HEAD deps=-\n"
               "x = 1\n"
               "# @@END 000\n"
               "# @@BLOCK 001 TAIL deps=000\n"
               "y = 2\n")
    names, _o, dupes, malformed = _analyse(fixture.splitlines())
    out, changed, bare, mismatched, inserted, orphan = _rewrite(fixture.splitlines(),
                                                               names)
    want_lines = ["# @@FILE demo.py blocks=2 version=v1",
                  "# @@BLOCK 000 HEAD deps=-",
                  "x = 1",
                  "# @@END 000 HEAD",
                  "# @@BLOCK 001 TAIL deps=000",
                  "y = 2",
                  "# @@END 001 TAIL"]
    ok = (out == want_lines and bare == 1 and inserted == 1
          and not dupes and not malformed)
    bad += 0 if ok else 1
    print("  %-4s %s" % ("OK" if ok else "FAIL",
                         "fixture: bare repaired + missing @@END inserted"))

    # an unclosed FINAL block must get its @@END ABOVE the @@EOF marker
    eof_fixture = ("# @@FILE demo.py blocks=1 version=v1\n"
                   "# @@BLOCK 000 HEAD deps=-\n"
                   "x = 1\n"
                   "# @@EOF\n")
    names2, _o2, _d2, _m2 = _analyse(eof_fixture.splitlines())
    out2, _c2, _b2, _mm2, ins2, _or2 = _rewrite(eof_fixture.splitlines(), names2)
    want2 = ["# @@FILE demo.py blocks=1 version=v1",
             "# @@BLOCK 000 HEAD deps=-",
             "x = 1",
             "# @@END 000 HEAD",
             "# @@EOF"]
    ok2 = (out2 == want2 and ins2 == 1)
    bad += 0 if ok2 else 1
    print("  %-4s %s" % ("OK" if ok2 else "FAIL",
                         "fixture: inserted @@END stays ABOVE @@EOF"))
    print("")
    print("SELFTEST %s" % ("PASSED" if not bad else "FAILED (%d)" % bad))
    print("=" * 74)
    return 1 if bad else 0


def _regate():
    try:
        import verify_blocks as VB
    except Exception as exc:                                  # noqa: BLE001
        print("verify_blocks.py could not be imported: %r" % (exc,))
        return 0
    print("=" * 74)
    print("RE-GATE (verify_blocks.py)")
    print("=" * 74)
    total = 0
    for p in VB.BLOCKED_FILES:
        res = VB.audit(p)
        total += len(res["fails"])
        print("  %-32s %4d block(s)  %3d fault(s)"
              % (p, len(res["blocks"]), len(res["fails"])))
        for f in res["fails"][:12]:
            print("        - " + f)
        if len(res["fails"]) > 12:
            print("        ... and %d more" % (len(res["fails"]) - 12))
    print("")
    print("TOTAL FAULTS: %d" % total)
    print("=" * 74)
    return total


def main(argv=None):
    ap = argparse.ArgumentParser(description="canonicalise @@END marker names")
    ap.add_argument("--apply", action="store_true",
                    help="write the files (default is a dry run)")
    ap.add_argument("--check", action="store_true",
                    help="dry run; exit 1 if any file needs a change")
    ap.add_argument("--selftest", action="store_true",
                    help="prove the marker regexes on fixtures, then exit")
    ap.add_argument("--files", nargs="*", default=None,
                    help="only these files (default: every blocked file)")
    ap.add_argument("--no-gate", action="store_true",
                    help="skip the verify_blocks.py re-gate")
    args = ap.parse_args(argv)

    if args.selftest:
        return _selftest()

    targets = args.files or list(FILES)
    mode = "APPLY" if args.apply else ("CHECK" if args.check else "DRY RUN")

    print("=" * 74)
    print("@@END NAME REPAIR  [%s]" % mode)
    print("=" * 74)

    total_changed = total_inserted = 0
    problems, hard = [], 0
    for p in targets:
        r = process(p, args.apply)
        if r["state"] == "absent":
            print("  %-32s absent (skipped)" % p)
            continue
        total_changed += r["changed"]
        total_inserted += r["inserted"]
        print("  %-32s %3d block(s)  %3d @@END  rewrite %3d "
              "(bare %d, mismatched %d)  insert %d"
              % (p, r["blocks"], r["ends"], r["changed"], r["bare"],
                 r["mismatched"], r["inserted"]))
        if r["unclosed"] > 0:
            problems.append("%s: %d block(s) had NO @@END at all (inserted now)"
                            % (p, r["unclosed"]))
        if r["orphan"]:
            problems.append("%s: %d @@END with no matching @@BLOCK (left alone)"
                            % (p, r["orphan"]))
        for ln, bid, txt in r["dupes"]:
            problems.append("%s line %d: duplicate @@BLOCK id %03d: %r"
                            % (p, ln, bid, txt.strip()[:60]))
        for ln, txt in r["malformed"]:
            problems.append("%s line %d: MALFORMED marker: %r"
                            % (p, ln, txt.strip()[:60]))
            hard += 1

    print("")
    print("%d @@END line(s) rewritten, %d inserted" % (total_changed, total_inserted))
    for p in problems:
        print("  ! " + p)
    print("")

    if args.check and (total_changed or total_inserted):
        hard = max(hard, 1)
        print("--check: changes are PENDING (run with --apply)")
    elif not args.apply and (total_changed or total_inserted):
        print("DRY RUN - nothing written.  Re-run with --apply to write.")
    elif args.apply and not (total_changed or total_inserted):
        print("Already canonical - nothing to write.")
    print("")

    gate_faults = 0
    if not args.no_gate:
        gate_faults = _regate()
    return 1 if (hard or gate_faults) else 0


if __name__ == "__main__":
    sys.exit(main())
