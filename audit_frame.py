#!/usr/bin/env python3
"""audit_frame.py - ground-truth frame audit for the fix-phase1 branch.

Independent of verify_blocks.py: re-derives every rule from the raw bytes.
Then separately proves the verifier's API against its three callers.

    python audit_frame.py
Exit 0 = frame clean AND verifier contract satisfied.
"""
from __future__ import annotations
import io, os, re, sys, tokenize

GATED = ["app.py", "engine.py", "status.py", "pages/2_Diagnostics.py",
         "pages/3_Mailbox_Reader.py", "pages/4_Downloads.py", "pages/5_Blocks.py"]
EXPECT_FILES, EXPECT_BLOCKS = 7, 225

FILE_RX  = re.compile(r"^#\s*@@FILE\s+(\S+)\s+blocks=(\d+)\s+version=(\S+)\s*$")
BLOCK_RX = re.compile(r"^#\s*@@BLOCK\s+(\d{3})\s+([A-Za-z0-9_]+)(?:\s+deps=(\S+))?\s*$")
END_RX   = re.compile(r"^#\s*@@END(?:\s+(\d{3}))?(?:\s+([A-Za-z0-9_]+))?\s*$")
EOF_RX   = re.compile(r"^#\s*@@EOF\b")
ALLOWED  = frozenset({"STRING", "COMMENT", "FSTRING_START", "FSTRING_MIDDLE",
                      "FSTRING_END", "NL", "NEWLINE", "INDENT", "DEDENT"})


def non_ascii(src):
    lines = src.splitlines()
    masked = list(lines)
    try:
        toks = list(tokenize.generate_tokens(io.StringIO(src).readline))
    except Exception:
        return []
    for t in toks:
        if tokenize.tok_name.get(t.type) not in ALLOWED:
            continue
        try:
            (sr, sc), (er, ec) = t.start, t.end
            if sr == er:
                r = masked[sr - 1]
                masked[sr - 1] = r[:sc] + " " * max(0, ec - sc) + r[ec:]
            else:
                for rr in range(sr, er + 1):
                    i = rr - 1
                    if i >= len(masked):
                        break
                    if rr == sr:
                        masked[i] = masked[i][:sc] + " " * max(0, len(masked[i]) - sc)
                    elif rr == er:
                        masked[i] = " " * ec + masked[i][ec:]
                    else:
                        masked[i] = " " * len(masked[i])
        except Exception:
            pass
    return [i for i, l in enumerate(masked, 1) if any(ord(c) > 127 for c in l)]


def scan(path):
    out = {"path": path, "faults": [], "blocks": 0, "named": 0, "bare": 0,
           "exists": os.path.isfile(path)}
    if not out["exists"]:
        out["faults"].append("missing file")
        return out
    src = io.open(path, encoding="utf-8").read()
    lines = src.splitlines()
    if not lines:
        out["faults"].append("empty file")
        return out
    declared = None
    m = FILE_RX.match(lines[0])
    if not m:
        out["faults"].append("L1 header: first line is not '# @@FILE name blocks=N version=V'")
    else:
        if m.group(1).replace("\\", "/") != path.replace("\\", "/"):
            out["faults"].append("L1 header_name: header %r vs path %r" % (m.group(1), path))
        declared = int(m.group(2))
    seen, ends = {}, {}
    for i, raw in enumerate(lines, 1):
        mb = BLOCK_RX.match(raw)                      # column-0 anchor
        if mb:
            bid, deps = int(mb.group(1)), mb.group(3)
            if bid in seen:
                out["faults"].append("L%d duplicate_id %03d" % (i, bid))
            else:
                seen[bid] = (i, mb.group(2))
            if deps and deps != "-":
                for d in deps.split(","):
                    d = d.strip()
                    if d.isdigit() and int(d) >= bid:
                        out["faults"].append("L%d bad_deps %03d deps=%s" % (i, bid, deps))
            continue
        me = END_RX.match(raw)
        if me:
            gid, gname = me.group(1), me.group(2)
            if gid is None:
                out["faults"].append("L%d bare_end (no id)" % i)
            else:
                bid = int(gid)
                if bid in ends:
                    out["faults"].append("L%d duplicate_end %03d" % (i, bid))
                ends[bid] = (i, gname)
            continue
    ids = sorted(seen)
    out["blocks"] = len(ids)
    if ids != list(range(len(ids))):
        out["faults"].append("noncontiguous block ids")
    if declared is not None and declared != len(ids):
        out["faults"].append("count_mismatch: header %d vs found %d" % (declared, len(ids)))
    for bid in ids:
        if bid not in ends:
            out["faults"].append("L%d unclosed %03d" % (seen[bid][0], bid))
            continue
        eline, ename = ends[bid]
        if not ename:
            out["bare"] += 1
            out["faults"].append("L%d unnamed_end %03d" % (eline, bid))
        elif ename != seen[bid][1]:
            out["faults"].append("L%d end_name_mismatch %03d" % (eline, bid))
        else:
            out["named"] += 1
    for bid in ends:
        if bid not in seen:
            out["faults"].append("L%d orphan_end %03d" % (ends[bid][0], bid))
    if not any(EOF_RX.match(l) for l in lines):
        out["faults"].append("eof_marker missing")
    for n in non_ascii(src):
        out["faults"].append("L%d non_ascii outside string/comment" % n)
    return out


def api_conformance():
    """Prove verify_blocks.py satisfies its three callers. Returns [problems]."""
    bad = []
    try:
        import verify_blocks as VB
    except Exception as e:
        return ["verify_blocks import failed: %r" % (e,)]

    for name in ("audit", "audit_file", "block_ids", "audit_all", "totals", "BLOCKED_FILES"):
        if not hasattr(VB, name):
            bad.append("verify_blocks has no %r" % name)

    good = ("# @@FILE x.py blocks=1 version=v1\n"
            "# @@BLOCK 000 A deps=-\n# @@END 000 A\n# @@EOF\n")
    r = None
    try:
        r = VB.audit_source(good, "x.py")
    except TypeError as e:
        bad.append("audit_source(text, label) -> %s" % e)
    if r is not None:
        if not isinstance(r.get("blocks"), list):
            bad.append("Report['blocks'] is %s, want list" % type(r.get("blocks")).__name__)
        if not isinstance(r.get("fails"), list):
            bad.append("Report['fails'] missing or not a list")
        if "table" not in r:
            bad.append("Report has no 'table'")
        if r.get("ok") is not True:
            bad.append("Report.ok is not True for a clean paste")
        if not isinstance(r.get("faults"), int):
            bad.append("Report['faults'] is not an int")
        if r.get("faults") != len(r.get("fails") or []):
            bad.append("faults != len(fails) on a clean paste")

    try:
        r2 = VB.audit_source("/no/such/file_zzz_audit.py")
        if not isinstance(r2.get("blocks"), list):
            bad.append("missing-file Report['blocks'] is %s, want list"
                       % type(r2.get("blocks")).__name__)
        if not r2.get("fails"):
            bad.append("missing-file Report has empty 'fails'")
        if r2.get("faults") != len(r2.get("fails") or []):
            bad.append("missing-file faults != len(fails)")
    except Exception as e:
        bad.append("audit_source(missing path) -> %r" % (e,))

    # verbatim expressions from pages/5_Blocks.py
    try:
        res_all = VB.audit_all()
        sum(len(x["blocks"]) for x in res_all.values())
        sum(len(x["fails"]) for x in res_all.values())
        for x in res_all.values():
            _ = x["table"]; _ = bool(x["fails"]); _ = x["ok"]
            _ = {b[0] for b in x["blocks"]}
        _ = VB.block_ids("app.py") - {1}
    except Exception as e:
        bad.append("pages/5_Blocks.py expression -> %r" % (e,))

    try:
        VB.totals(res_all)
    except Exception as e:
        bad.append("totals() -> %r" % (e,))

    try:
        import fix_end_names as FE
        if not isinstance(FE._regate(), int):
            bad.append("fix_end_names._regate() did not return an int")
    except Exception as e:
        bad.append("fix_end_names._regate() -> %r" % (e,))

    t2 = "Tier 2"
    if os.path.exists(t2):
        t = io.open(t2, encoding="utf-8").read()
        if '"app.py (new)"' in t:
            bad.append("Tier 2: label still 'app.py (new)' -> header_name fault, writes nothing")
        if 'L.append("# @@EOF")' not in t:
            bad.append("Tier 2: emit() does not write @@EOF")
    return bad


def main():
    reps = [scan(p) for p in GATED] + [scan("verify_blocks.py")]
    faults = sum(len(r["faults"]) for r in reps)
    bare = sum(r["bare"] for r in reps)

    print("=" * 74)
    print("FRAME  (raw byte scan - independent of verify_blocks.py)")
    print("=" * 74)
    for r in reps:
        print("%-34s blocks=%-4d named=%-4d bare=%-4d faults=%d"
              % (r["path"], r["blocks"], r["named"], r["bare"], len(r["faults"])))
        for f in r["faults"][:25]:
            print("      " + f)
        if len(r["faults"]) > 25:
            print("      ... and %d more" % (len(r["faults"]) - 25))
    gated = reps[:-1]
    print("-" * 74)
    print("gated files=%d blocks=%d faults=%d bare_ends=%d"
          % (sum(1 for r in gated if r["exists"]),
             sum(r["blocks"] for r in gated), faults - len(reps[-1]["faults"]), bare))
    print("TARGET       files=%d blocks=%d faults=0 bare_ends=0"
          % (EXPECT_FILES, EXPECT_BLOCKS))
    print("verify_blocks.py itself: %d fault(s) (must be 0)"
          % len(reps[-1]["faults"]))

    print()
    print("=" * 74)
    print("VERIFIER CONTRACT  (against pages/5_Blocks.py, fix_end_names.py, Tier 2)")
    print("=" * 74)
    bad = api_conformance()
    if not bad:
        print("  OK - all three callers satisfied")
    for b in bad:
        print("  - " + b)

    print()
    print("=" * 74)
    print("WHAT IS LEFT")
    print("=" * 74)
    todo = []
    if bare:
        todo.append("STEP B: python fix_end_names.py --apply   (%d bare @@END lines)" % bare)
    missing_eof = [r["path"] for r in gated if any("eof_marker" in f for f in r["faults"])]
    if missing_eof:
        todo.append("STEP C: append '# @@EOF' as the LAST line of: " + ", ".join(missing_eof))
    for r in gated:
        for f in r["faults"]:
            if "bad_deps" in f or "duplicate" in f or "header_name" in f:
                todo.append("  %s: %s" % (r["path"], f))
    if not todo and not bad:
        print("  nothing - frame clean and contract satisfied")
    for t in todo:
        print("  " + t)

    ok = (faults == 0) and (not bad)
    print()
    print("RESULT: %s" % ("GREEN" if ok else "NOT GREEN"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
