#!/usr/bin/env python3
"""repair_app_syntax.py - show the syntax error, repair the known paste damage.

    python repair_app_syntax.py

Exit 0 = app.py parses.  If it exits 1, paste the printed region back.
"""
import ast
import os
import re
import sys
import time

TARGET = "app.py"
STAMP = time.strftime("%Y%m%d_%H%M%S")


def show(src, lineno, span=8):
    lines = src.splitlines()
    lo, hi = max(1, lineno - span), min(len(lines), lineno + span)
    print("-" * 70)
    for i in range(lo, hi + 1):
        mark = ">>" if i == lineno else "  "
        print("%s %6d | %s" % (mark, i, lines[i - 1]))
    print("-" * 70)


def parse_error(src):
    try:
        ast.parse(src)
        return None
    except SyntaxError as e:
        return e


def repair_unmatched_brace(src):
    """A '}' with no '{' before it, inside report_entries.append(...).

    The append statement must be `append({ ... })`.  A lost '{' makes the final
    '}' unmatched.  Restore the '{', then drop any '}' that still has no opener.
    """
    done = []

    m = re.search(r"report_entries\.append\(\s*(?=\")", src)
    if m:
        src = src[:m.end()] + "{" + src[m.end():]
        done.append("restored the lost '{' in report_entries.append({")

    i = src.find("report_entries.append({")
    if i != -1:
        start = i + len("report_entries.append(")
        depth = 0
        j = start
        while j < len(src):
            c = src[j]
            if c in "([{":
                depth += 1
            elif c == "}":
                if depth == 0:
                    src = src[:j] + src[j + 1:]
                    done.append("removed a stray '}' at offset %d" % j)
                    continue
                depth -= 1
            elif c in ")]":
                if depth == 0:
                    break
                depth -= 1
            j += 1
    return src, done


def main():
    if not os.path.exists(TARGET):
        print("ABORT: app.py not found - run this from the repo root.")
        return 1

    with open(TARGET, encoding="utf-8") as f:
        src = f.read()

    err = parse_error(src)
    if err is None:
        print("app.py already parses. Nothing to repair.")
        return 0

    print("app.py does NOT parse.")
    print("line %s: %s" % (err.lineno, err.msg))
    show(src, err.lineno)

    if "unmatched '}'" not in err.msg:
        print("Not an unmatched-brace error - repair the region above by hand.")
        return 1

    fixed, done = repair_unmatched_brace(src)
    if not done:
        print("Brace repair found nothing to change.")
        return 1
    for d in done:
        print("  * " + d)

    err2 = parse_error(fixed)
    if err2 is not None:
        print("STILL broken at line %s: %s" % (err2.lineno, err2.msg))
        show(fixed, err2.lineno)
        print("Nothing written.")
        return 1

    i = fixed.find("report_entries.append({")
    print("\nRepaired statement:")
    print("-" * 70)
    print("\n".join(fixed[i - 80:i + 620].splitlines()))
    print("-" * 70)

    bak = "app.py.bak.%s" % STAMP
    with open(bak, "w", encoding="utf-8") as f:
        f.write(src)
    with open(TARGET, "w", encoding="utf-8") as f:
        f.write(fixed)

    print("\nOK. app.py parses. Backup: %s" % bak)
    return 0


if __name__ == "__main__":
    sys.exit(main())
