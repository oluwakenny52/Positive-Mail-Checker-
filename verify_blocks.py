#!/usr/bin/env python3
"""verify_blocks.py - structural gate for the @@BLOCK layout (v13.40).

TWO WAYS TO USE IT
------------------
    python verify_blocks.py                # CLI: every file in BLOCKED_FILES
    python verify_blocks.py app.py ...     # CLI: just these

    import verify_blocks as VB             # library - used by pages/5_Blocks.py
    res = VB.audit_source(src, "app.py")   # validate a PASTE before committing
    res = VB.audit("app.py")               # validate a file on disk
    res["fails"]                           # human-readable faults
    res["blocks"]                          # [(id, name, deps, start, end, lines)]

Exit 0 = clean. Exit 1 = the exact fault, with line numbers.

WHAT THIS GATES
---------------
The big files are split into named, numbered, replaceable blocks:

    # @@FILE app.py blocks=111 version=v13.40
    # @@BLOCK 016 PROXY_407_CONTRACT deps=-
    ...
    # @@END 016 PROXY_407_CONTRACT

Rule: to change behaviour you REPLACE A WHOLE BLOCK, never edit inside one.
That only stays safe if the frame is machine-checked - which is this file.

CHECKS
  1. exactly one @@FILE header, on the first code line
  2. block ids contiguous from 000, strictly ascending, no duplicates
  3. block NAMES are unique (replacement is by name as well as id)
  4. every @@BLOCK has a matching @@END with the same id AND name
  5. every dep exists and is EARLIER than the block that names it
  6. nothing but blanks/comments between an @@END and the next @@BLOCK
  7. no code outside any block
  8. the file still compiles, tokenizes and AST-parses
  9. the declared blocks=<n> matches the real count
 10. no non-ASCII outside a comment or a string (the paste landmine)
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
    "pages/5_Blocks.py",
)

RE_FILE = re.compile(r"^#\s*@@FILE\s+(\S+)\s+blocks=(\d+)\s+version=(\S+)\s*$")
RE_BLOCK = re.compile(r"^#\s*@@BLOCK\s+(\d{3})\s+([A-Z0-9_]+)\s+deps=([\d,\-]+)\s*$")
RE_END = re.compile(r"^#\s*@@END\s+(\d{3})\s+([A-Z0-9_]+)\s*$")

MAX_REPORT = 60


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


def audit_source(src, label="<paste>"):
    """Validate block structure. Returns a dict, never raises."""
    res = {"label": label, "ok": False, "blocks": [], "passes": [], "fails": [],
           "table": [], "file_name": None, "declared": None}
    lines = src.splitlines()
    ok, bad = res["passes"].append, res["fails"].append

    hdr = None
    for ln in lines:
        if not ln.strip() or ln.startswith("#!"):
            continue
        hdr = RE_FILE.match(ln)
        break
    if not hdr:
        bad("%s: the first code line is not "
            "'# @@FILE <name> blocks=<n> version=<v>'" % label)
        return res
    res["file_name"] = hdr.group(1)
    res["declared"] = int(hdr.group(2))
    ok("%s: @@FILE header ok (declares %d block(s))" % (label, res["declared"]))

    blocks, ends, depth = [], {}, 0
    for i, ln in enumerate(lines, 1):
        m = RE_BLOCK.match(ln)
        if m:
            if depth:
                bad("%s line %d: @@BLOCK opened while block %03d is still open"
                    % (label, i, blocks[-1][0]))
            depth = 1
            blocks.append((int(m.group(1)), m.group(2), m.group(3), i))
            continue
        m = RE_END.match(ln)
        if m:
            if not depth:
                bad("%s line %d: @@END with no open @@BLOCK" % (label, i))
                continue
            depth = 0
            ends[int(m.group(1))] = (m.group(2), i)

    if depth and blocks:
        bad("%s: block %03d %s is never closed" % (label, blocks[-1][0], blocks[-1][1]))
    if not blocks:
        bad("%s: no @@BLOCK lines found" % label)
        return res

    ids = [b[0] for b in blocks]
    names = [b[1] for b in blocks]
    if ids != sorted(ids):
        bad("%s: block ids are not ascending" % label)
    if len(set(ids)) != len(ids):
        bad("%s: duplicate block id(s) %s"
            % (label, sorted({x for x in ids if ids.count(x) > 1})))
    if len(set(names)) != len(names):
        bad("%s: duplicate block NAME(s) %s"
            % (label, sorted({x for x in names if names.count(x) > 1})))
    if ids[0] != 0:
        bad("%s: first block id is %03d, must be 000" % (label, ids[0]))
    for n in range(len(ids)):
        if ids[n] != n:
            bad("%s: ids are not contiguous from 000 (first gap at %03d)" % (label, n))
            break

    for bid, name, deps, ln in blocks:
        e = ends.get(bid)
        if not e:
            bad("%s line %d: @@BLOCK %03d %s has no @@END" % (label, ln, bid, name))
            continue
        if e[0] != name:
            bad("%s line %d: @@END %03d name is %r, @@BLOCK says %r"
                % (label, e[1], bid, e[0], name))
        if deps != "-":
            for d in [x for x in deps.split(",") if x]:
                di = int(d)
                if di >= bid:
                    bad("%s block %03d: dep %03d is not earlier" % (label, bid, di))
                elif di not in ids:
                    bad("%s block %03d: dep %03d does not exist" % (label, bid, di))

    res["blocks"] = [(bid, name, deps, ln, ends.get(bid, (name, ln))[1], 0)
                     for bid, name, deps, ln in blocks]
    ok("%s: %d block(s), all closed, deps ordered" % (label, len(blocks)))

    end_of = {b: ends[b][1] for b in ends}
    spans = sorted((ln, end_of[bid]) for bid, _n, _d, ln in blocks if bid in end_of)
    if spans:
        for i in range(1, spans[0][0]):
            t = lines[i - 1].strip()
            if t and not t.startswith("#"):
                bad("%s line %d: code ABOVE the first block: %r" % (label, i, t[:70]))
        for k in range(len(spans) - 1):
            for i in range(spans[k][1] + 1, spans[k + 1][0]):
                t = lines[i - 1].strip()
                if t and not t.startswith("#"):
                    bad("%s line %d: code BETWEEN blocks: %r" % (label, i, t[:70]))
        for i in range(spans[-1][1] + 1, len(lines) + 1):
            t = lines[i - 1].strip()
            if t and not t.startswith("#"):
                bad("%s line %d: code AFTER the last block: %r" % (label, i, t[:70]))

    try:
        compile(src, label, "exec")
        ok(label + " compiles")
    except SyntaxError as e:
        bad("%s DOES NOT COMPILE: line %s: %s" % (label, e.lineno, e.msg))
    except Exception as e:
        bad("%s compile failed: %s" % (label, e))
    try:
        list(tokenize.generate_tokens(io.StringIO(src).readline))
        ok(label + " tokenizes")
    except Exception as e:
        bad("%s tokenize failed: %s" % (label, e))
    try:
        ast.parse(src, filename=label)
        ok(label + " AST parses")
    except SyntaxError as e:
        bad("%s AST parse failed: line %s: %s" % (label, e.lineno, e.msg))

    if res["declared"] != len(blocks):
        bad("%s: @@FILE declares blocks=%d but %d exist"
            % (label, res["declared"], len(blocks)))

    for i, ln in enumerate(code_view(src).splitlines(), 1):
        for ch in ln:
            if ord(ch) > 126:
                bad("%s line %d: non-ASCII %r outside any comment/string: %r"
                    % (label, i, ch, ln.strip()[:70]))
                break

    res["table"] = [{"id": "%03d" % bid, "block": name, "lines": end_of.get(bid, ln) - ln + 1,
                     "deps": deps}
                    for bid, name, deps, ln, _e, _n in res["blocks"]]
    res["ok"] = not res["fails"]
    return res


def audit(path):
    if not os.path.exists(path):
        return {"label": path, "ok": True, "blocks": [], "passes": [path + " absent (skipped)"],
                "fails": [], "table": [], "file_name": None, "declared": None}
    return audit_source(read(path), path)


def audit_all(paths=None):
    return {p: audit(p) for p in (paths or BLOCKED_FILES)}


def block_ids(path):
    return {b[0] for b in audit(path)["blocks"]}


def _print_report(res):
    print("")
    print("  %-4s %-30s %6s  %s" % ("id", "block", "lines", "deps"))
    for row in res["table"]:
        print("  %-4s %-30s %6d  %s" % (row["id"], row["block"], row["lines"], row["deps"]))


def main(argv):
    targets = argv[1:] or list(BLOCKED_FILES)
    passes, fails = [], []
    for p in targets:
        print("=" * 74)
        print("CHECKING %s" % p)
        print("=" * 74)
        res = audit(p)
        passes.extend(res["passes"])
        fails.extend(res["fails"])
        if res["table"]:
            _print_report(res)
    print("")
    print("=" * 74)
    print("PASSED %d   FAILED %d" % (len(passes), len(fails)))
    for f in fails[:MAX_REPORT]:
        print("  - " + f)
    if len(fails) > MAX_REPORT:
        print("  ... and %d more" % (len(fails) - MAX_REPORT))
    print("=" * 74)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
