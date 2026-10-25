# @@FILE verify_blocks.py blocks=1 version=v13.40
#!/usr/bin/env python3
# @@BLOCK 000 VERIFIER deps=-
"""verify_blocks.py - block-integrity gate for the block-edition app.

Audits every file in BLOCKED_FILES for:
  * a valid `# @@FILE <name> blocks=<n> version=<v>` header, count matching
  * contiguous, zero-padded block ids starting at 000
  * every block closed by a *named* `# @@END <id> <NAME>` matching its block
  * no duplicate ids, no unmatched END
  * no non-ASCII characters outside strings/comments (f-string aware, so
    f-string bodies do NOT produce false positives)

A bare `# @@END` with no id costs 2 faults: one for the missing id and one for
the unnamed end. Exit status is 1 when any fault is found.

API used elsewhere:
  BLOCKED_FILES            list of audited paths
  audit_source(target, name=None) -> Report     (path, or source text + label)
  audit_all(paths=None)    -> {path: Report}
  block_ids(path)          -> [int, ...]
  totals(reports=None)     -> (files, blocks, faults)
  main(argv)               -> exit code
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
import tokenize

__version__ = "v13.40"

BLOCKED_FILES = [
    "app.py",
    "status.py",
    "pages/2_Diagnostics.py",
    "pages/3_Mailbox_Reader.py",
    "pages/4_Downloads.py",
    "pages/5_Blocks.py",
]

FILE_RX = re.compile(r"^#\s*@@FILE\s+(\S+)\s+blocks=(\d+)\s+version=(\S+)\s*$")
BLOCK_RX = re.compile(r"^#\s*@@BLOCK\s+(\d{3})\s+([A-Za-z0-9_]+)(?:\s+deps=(\S+))?\s*$")
END_RX = re.compile(r"^#\s*@@END(?:\s+(\d{3}))?(?:\s+([A-Za-z0-9_]+))?\s*$")
EOF_RX = re.compile(r"^#\s*@@EOF\b")

_ALLOWED_TOKENS = frozenset(
    {
        "STRING",
        "COMMENT",
        "FSTRING_START",
        "FSTRING_MIDDLE",
        "FSTRING_END",
        "NL",
        "NEWLINE",
        "INDENT",
        "DEDENT",
    }
)


class Report(dict):
    """dict that also allows attribute access, so both `r['faults']` and
    `r.faults` work for callers."""

    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    @property
    def ok(self):
        return not self.get("faults")


def _mask(lines, tok):
    sr, sc = tok.start
    er, ec = tok.end
    if sr == er:
        row = lines[sr - 1]
        lines[sr - 1] = row[:sc] + " " * max(0, ec - sc) + row[ec:]
        return
    for r in range(sr, er + 1):
        idx = r - 1
        if idx >= len(lines):
            break
        row = lines[idx]
        if r == sr:
            lines[idx] = row[:sc] + " " * max(0, len(row) - sc)
        elif r == er:
            lines[idx] = " " * ec + row[ec:]
        else:
            lines[idx] = " " * len(row)


def non_ascii_offenders(src):
    """Line numbers carrying non-ASCII outside strings/comments."""
    lines = src.splitlines()
    masked = list(lines)
    try:
        toks = list(tokenize.generate_tokens(io.StringIO(src).readline))
    except Exception:
        toks = []
    if not toks:
        return []
    for tok in toks:
        if tokenize.tok_name.get(tok.type) in _ALLOWED_TOKENS:
            try:
                _mask(masked, tok)
            except Exception:
                pass
    out = []
    for i, row in enumerate(masked, start=1):
        if any(ord(ch) > 127 for ch in row):
            out.append(i)
    return out


def _scan(path):
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def _finalise(rep):
    """Derive faults/fails/table from details+blocks. Called before EVERY return."""
    rep["faults"] = len(rep["details"])
    rep["fails"] = ["L%d %s: %s" % (d["line"], d["kind"], d["text"])
                    for d in rep["details"]]
    rep["table"] = [{"id": b[0], "name": b[1], "line": b[2]} for b in rep["blocks"]]
    return rep


def audit_source(target, name=None):
    """Audit one file, or a pasted block of source.

    target = a filesystem path, OR the full source text when `name` is given.
    Never raises; problems come back as faults.
    """
    is_text = name is not None
    path = name if is_text else target

    rep = Report(
        path=path,
        exists=False,
        declared=None,
        version=None,
        blocks=[],
        faults=0,
        details=[],
        fails=[],
        table=[],
    )

    if not is_text and not os.path.isfile(path):
        rep["details"].append({"line": 0, "kind": "missing_file", "text": "%s is MISSING" % path})
        return _finalise(rep)

    try:
        src = target if is_text else _scan(path)
    except Exception as exc:
        rep["exists"] = True
        rep["details"].append({"line": 0, "kind": "unreadable", "text": str(exc)})
        return _finalise(rep)

    rep["exists"] = True
    lines = src.splitlines()

    def fault(line, kind, text):
        rep["details"].append({"line": line, "kind": kind, "text": text})
        rep["faults"] += 1

    # header
    if lines:
        m = FILE_RX.match(lines[0].strip())
        if m:
            rep["declared"] = int(m.group(2))
            rep["version"] = m.group(3)
            if path.replace("\\", "/") != m.group(1).replace("\\", "/"):
                fault(1, "header_name", "header says '%s', file is '%s'" % (m.group(1), path))
        else:
            fault(1, "header", "first line is not a valid '# @@FILE name blocks=N version=V' header")

    blocks = {}       # id -> (line, name)
    ends = {}         # id -> (line, name)

    for i, raw in enumerate(lines, start=1):
        s = raw.rstrip()

        mb = BLOCK_RX.match(s)
        if mb:
            bid = int(mb.group(1))
            bname = mb.group(2)
            deps = mb.group(3)
            if deps is not None and deps != "-":
                for d in deps.split(","):
                    d = d.strip()
                    if d.isdigit() and int(d) >= bid:
                        fault(i, "bad_deps", "block %03d declares deps=%s (>= its own id)" % (bid, deps))
            if bid in blocks:
                fault(i, "duplicate_id", "block id %03d already opened at line %d" % (bid, blocks[bid][0]))
            else:
                blocks[bid] = (i, bname)
            continue

        me = END_RX.match(s)
        if me:
            gid, gname = me.group(1), me.group(2)
            if gid is None:
                fault(i, "bare_end", "bare '# @@END' with no block id")
                fault(i, "bare_end", "bare '# @@END' with no block name")
            else:
                bid = int(gid)
                if bid in ends:
                    fault(i, "duplicate_end", "END %03d already closed at line %d" % (bid, ends[bid][0]))
                ends[bid] = (i, gname or "")
            continue

    rep["blocks"] = [(bid, blocks[bid][1], blocks[bid][0]) for bid in sorted(blocks)]

    # every open block needs a matching named end
    for bid, bname, bline in rep["blocks"]:
        if bid not in ends:
            fault(bline, "unclosed", "block %03d %s has no matching '# @@END'" % (bid, bname))
            continue
        eline, ename = ends[bid]
        if not ename:
            fault(eline, "unnamed_end", "END %03d carries no block name" % bid)
        elif ename != bname:
            fault(eline, "end_name_mismatch", "END %03d name '%s' != block name '%s'" % (bid, ename, bname))

    for bid in sorted(ends):
        if not any(b[0] == bid for b in rep["blocks"]):
            fault(ends[bid][0], "orphan_end", "END %03d has no matching block" % bid)

    if rep["blocks"]:
        expected = list(range(len(rep["blocks"])))
        actual = sorted(b[0] for b in rep["blocks"])
        if actual != expected:
            missing = [i for i in expected if i not in actual]
            fault(0, "noncontiguous", "block ids are not 000..%03d (missing %s)" % (len(rep["blocks"]) - 1, missing or "none"))

    if rep["declared"] is not None and rep["declared"] != len(rep["blocks"]):
        fault(0, "count_mismatch", "header declares %d blocks, found %d" % (rep["declared"], len(rep["blocks"])))

    if rep["declared"] is not None and not any(EOF_RX.match(l.strip()) for l in lines):
        fault(len(lines), "eof_marker", "no '# @@EOF' marker")

    for lineno in non_ascii_offenders(src):
        fault(lineno, "non_ascii", "non-ASCII character outside a string or comment")

    return _finalise(rep)


audit_file = audit_source


def block_ids(path):
    if not os.path.isfile(path):
        return []
    ids = []
    for raw in _scan(path).splitlines():
        m = BLOCK_RX.match(raw.rstrip())
        if m:
            ids.append(int(m.group(1)))
    return ids


def audit_all(paths=None):
    targets = list(paths) if paths else list(BLOCKED_FILES)
    return {p: audit_source(p) for p in targets}


def totals(reports=None):
    reps = reports if reports is not None else audit_all()
    if isinstance(reps, dict):
        reps = list(reps.values())
    files = len(reps)
    blocks = sum(len(r.get("blocks") or []) for r in reps)
    faults = sum(len(r.get("fails") or []) for r in reps)
    return files, blocks, faults


audit = audit_source


def main(argv=None):
    ap = argparse.ArgumentParser(description="block-integrity gate")
    ap.add_argument("--json", action="store_true", help="emit JSON")
    ap.add_argument("--quiet", action="store_true", help="summary only")
    ap.add_argument("paths", nargs="*", help="override BLOCKED_FILES")
    args = ap.parse_args(argv)

    reports = audit_all(args.paths or None)
    files, blocks, faults = totals(reports)

    if args.json:
        print(json.dumps({"files": files, "blocks": blocks, "faults": faults,
                          "reports": reports}, indent=2, default=str))
    else:
        for path, rep in reports.items():
            if rep.get("faults"):
                status = "FAULT %d" % rep["faults"]
            elif not rep.get("exists"):
                status = "MISSING"
            else:
                status = "OK"
            print("%-34s blocks=%-4d %s" % (path, len(rep.get("blocks") or []), status))
            if not args.quiet:
                for d in rep.get("details", []):
                    print("    L%-5d %-20s %s" % (d["line"], d["kind"], d["text"]))
        print("-" * 62)
        print("files=%d blocks=%d faults=%d" % (files, blocks, faults))

    return 1 if faults else 0


if __name__ == "__main__":
    sys.exit(main())
# @@END 000 VERIFIER
# @@EOF
