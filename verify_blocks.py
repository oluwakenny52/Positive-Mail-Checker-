#!/usr/bin/env python3
"""verify_blocks.py - structural gate for the @@BLOCK layout (v13.40).

    python verify_blocks.py              # every file in BLOCKED_FILES
    python verify_blocks.py app.py ...   # just these

Exit 0 = all files well formed. Exit 1 = the exact fault, with line numbers.

WHAT THIS GATES
---------------
The big files are split into named, numbered, replaceable blocks:

    # @@FILE app.py blocks=111 version=v13.40
    # @@BLOCK 008 BUILD_IDENTITY deps=-
    ...
    # @@END 008 BUILD_IDENTITY

The rule is: to change behaviour you REPLACE A WHOLE BLOCK, never edit inside
one. That only stays safe if the frame is machine-checked - which is this file.

CHECKS
  1. exactly one @@FILE header, on the first code line
  2. block ids contiguous from 000, strictly ascending, no duplicates
  3. every @@BLOCK has a matching @@END with the same id AND name
  4. every dep exists and is EARLIER than the block that names it
  5. nothing but blanks/comments between an @@END and the next @@BLOCK
  6. no code outside any block
  7. the file still compiles, tokenizes and AST-parses
  8. the declared blocks=<n> matches the real count
  9. no non-ASCII outside a comment or a string (the paste landmine)
 10. prints the live block manifest for the file
"""
import ast
import io
import os
import re
import sys
import tokenize

BLOCKED_FILES = (
    "app.py",
    "status.py",
    "pages/2_Diagnostics.py",
    "pages/3_Mailbox_Reader.py",
    "pages/4_Downloads.py",
)

RE_FILE = re.compile(r"^#\s*@@FILE\s+(\S+)\s+blocks=(\d+)\s+version=(\S+)\s*$")
RE_BLOCK = re.compile(r"^#\s*@@BLOCK\s+(\d{3})\s+([A-Z0-9_]+)\s+deps=([\d,\-]+)\s*$")
RE_END = re.compile(r"^#\s*@@END\s+(\d{3})\s+([A-Z0-9_]+)\s*$")

PASS = []
FAIL = []


def read(path):
    with io.open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def _line_offsets(src):
    offs = [0]
    for ln in src.splitlines(keepends=True):
        offs.append(offs[-1] + len(ln))
    return offs


def code_view(src):
    """Source with every COMMENT and STRING blanked out, layout preserved."""
    chars = list(src)
    offs = _line_offsets(src)

    def pos(line, col):
        return offs[line - 1] + col

    try:
        toks = list(tokenize.generate_tokens(io.StringIO(src).readline))
    except Exception:
        return src
    for tok in toks:
        if tok.type not in (tokenize.COMMENT, tokenize.STRING):
            continue
        start, end = pos(*tok.start), pos(*tok.end)
        for i in range(start, min(end, len(chars))):
            if chars[i] != "\n":
                chars[i] = " "
    return "".join(chars)


def check_file(path):
    if not os.path.exists(path):
        PASS.append(path + " absent (skipped)")
        return
    src = read(path)
    lines = src.splitlines()

    hdr = None
    for ln in lines:
        if not ln.strip() or ln.startswith("#!"):
            continue
        hdr = RE_FILE.match(ln)
        break
    if not hdr:
        FAIL.append("%s: first code line is not "
                    "'# @@FILE <name> blocks=<n> version=<v>'" % path)
        return
    declared = int(hdr.group(2))
    PASS.append("%s: @@FILE header ok (declares %d block(s))" % (path, declared))

    blocks = []
    ends = {}
    depth = 0
    for i, ln in enumerate(lines, 1):
        m = RE_BLOCK.match(ln)
        if m:
            if depth:
                FAIL.append("%s line %d: @@BLOCK opened while block %03d is open"
                            % (path, i, blocks[-1][0]))
            depth = 1
            blocks.append((int(m.group(1)), m.group(2), m.group(3), i))
            continue
        m = RE_END.match(ln)
        if m:
            if not depth:
                FAIL.append("%s line %d: @@END with no open @@BLOCK" % (path, i))
                continue
            depth = 0
            ends[int(m.group(1))] = (m.group(2), i)
            continue

    if depth and blocks:
        FAIL.append("%s: block %03d %s is never closed"
                    % (path, blocks[-1][0], blocks[-1][1]))
    if not blocks:
        FAIL.append(path + ": no @@BLOCK lines found")
        return

    ids = [b[0] for b in blocks]
    if ids != sorted(ids):
        FAIL.append(path + ": block ids are not ascending")
    if len(set(ids)) != len(ids):
        FAIL.append("%s: duplicate block id(s) %s"
                    % (path, sorted({x for x in ids if ids.count(x) > 1})))
    if ids[0] != 0:
        FAIL.append(path + ": first block id is %03d, must be 000" % ids[0])
    for n in range(len(ids)):
        if ids[n] != n:
            FAIL.append("%s: ids not contiguous from 000 (first gap at %03d)" % (path, n))
            break

    for bid, name, deps, ln in blocks:
        e = ends.get(bid)
        if not e:
            FAIL.append("%s line %d: @@BLOCK %03d %s has no @@END" % (path, ln, bid, name))
            continue
        if e[0] != name:
            FAIL.append("%s line %d: @@END %03d name is %r, @@BLOCK says %r"
                        % (path, e[1], bid, e[0], name))
        if deps != "-":
            for d in [x for x in deps.split(",") if x]:
                di = int(d)
                if di >= bid:
                    FAIL.append("%s block %03d: dep %03d is not earlier" % (path, bid, di))
                elif di not in ids:
                    FAIL.append("%s block %03d: dep %03d does not exist" % (path, bid, di))
    PASS.append("%s: %d block(s), all closed, deps ordered" % (path, len(blocks)))

    end_of = {b: ends[b][1] for b in ends if b in ends}
    spans = sorted((ln, end_of[bid]) for bid, _n, _d, ln in blocks if bid in end_of)
    if spans:
        for i in range(1, spans[0][0]):
            t = lines[i - 1].strip()
            if t and not t.startswith("#"):
                FAIL.append("%s line %d: code above the first block: %r" % (path, i, t[:70]))
        for k in range(len(spans) - 1):
            for i in range(spans[k][1] + 1, spans[k + 1][0]):
                t = lines[i - 1].strip()
                if t and not t.startswith("#"):
                    FAIL.append("%s line %d: code BETWEEN blocks: %r" % (path, i, t[:70]))
        for i in range(spans[-1][1] + 1, len(lines) + 1):
            t = lines[i - 1].strip()
            if t and not t.startswith("#"):
                FAIL.append("%s line %d: code AFTER the last block: %r" % (path, i, t[:70]))

    try:
        compile(src, path, "exec")
        PASS.append(path + " compiles")
    except SyntaxError as e:
        FAIL.append("%s DOES NOT COMPILE: line %s: %s" % (path, e.lineno, e.msg))
    try:
        list(tokenize.generate_tokens(io.StringIO(src).readline))
        PASS.append(path + " tokenizes")
    except Exception as e:
        FAIL.append("%s tokenize failed: %s" % (path, e))
    try:
        ast.parse(src, filename=path)
        PASS.append(path + " AST parses")
    except SyntaxError as e:
        FAIL.append("%s AST parse failed: line %s: %s" % (path, e.lineno, e.msg))

    if declared != len(blocks):
        FAIL.append("%s: @@FILE declares blocks=%d but %d exist"
                    % (path, declared, len(blocks)))

    for i, ln in enumerate(code_view(src).splitlines(), 1):
        for ch in ln:
            if ord(ch) > 126:
                FAIL.append("%s line %d: non-ASCII %r outside any comment/string: %r"
                            % (path, i, ch, ln.strip()[:70]))
                break

    print("")
    print("  %-4s %-30s %6s  %s" % ("id", "block", "lines", "deps"))
    for bid, name, deps, ln in blocks:
        print("  %03d  %-30s %6d  %s" % (bid, name, end_of.get(bid, ln) - ln + 1, deps))


def main(argv):
    targets = argv[1:] or list(BLOCKED_FILES)
    for p in targets:
        print("=" * 74)
        print("CHECKING %s" % p)
        print("=" * 74)
        check_file(p)
    print("")
    print("=" * 74)
    print("PASSED %d   FAILED %d" % (len(PASS), len(FAIL)))
    for f in FAIL:
        print("  - " + f)
    print("=" * 74)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
