#!/usr/bin/env python3
"""test_resume_io.py - gate 13: the Resume Unfinished path must actually work.

The bug this exists for: app.py block 083 called

    glob.glob(path, reverse=True)

`reverse` is a sorted() keyword, not a glob() one, so the call raised TypeError
and the bare `except Exception: pass` inside list_unfinished_runs() swallowed
it. The function returned [] on every call, so the Resume Unfinished counter
read 0 and the inspector said "No items" while the record sat on disk.

A substring gate cannot catch that - the broken text was right there and looked
right. This one CALLS the expression, then proves the source no longer calls
glob() with reverse=.

WHY THE DOCSTRING IS STRIPPED: block 083's own docstring QUOTES the broken form
as a single bare line, so any scan of the raw body text sees it and reports a
false failure. Test 3 blanks the docstring first and scans only real code.

    python test_resume_io.py     # exit 0 = clean
"""
import glob
import io
import os
import sys
import tempfile

FAILS, PASSES = [], []


def ok(name):
    PASSES.append(name)


def bad(name, detail):
    FAILS.append("%s -> %s" % (name, detail))


def between(src, start, end):
    if start not in src:
        return ""
    return src.split(start, 1)[1].split(end, 1)[0]


def strip_docstring(body):
    """Drop a leading triple-quoted docstring, so quoted code is not scanned."""
    if body.count('"""') >= 2:
        return body.split('"""', 2)[2]
    return body


def main():
    d = tempfile.mkdtemp(prefix="resume_io_")
    with io.open(os.path.join(d, "unfinished_live.json"), "w", encoding="utf-8") as fh:
        fh.write('{"remaining": ["a@b.c:1", "d@e.f:2"]}')

    # 1. the expression block 083 must use
    try:
        hits = sorted(glob.glob(os.path.join(d, "unfinished_*.json")), reverse=True)
    except Exception as exc:
        bad("sorted(glob.glob(...))", repr(exc))
        hits = []
    if len(hits) == 1:
        ok("sorted(glob.glob(...)) finds the record")
    else:
        bad("sorted(glob.glob(...))", "found %d file(s), want 1" % len(hits))

    # 2. and prove the broken form really is broken
    try:
        glob.glob(os.path.join(d, "unfinished_*.json"), reverse=True)
        bad("glob.glob(..., reverse=True)", "did not raise - the fix may be moot")
    except TypeError:
        ok("glob.glob(..., reverse=True) still raises TypeError")

    # 3. list_unfinished_runs() must CALL sorted(glob.glob(...), reverse=True).
    src = io.open("app.py", encoding="utf-8").read()
    body = strip_docstring(between(src, "def list_unfinished_runs",
                                   "def unfinished_remaining_count"))
    if not body.strip():
        bad("app.py", "list_unfinished_runs() body not found")
    else:
        bad_lines = [l.strip() for l in body.splitlines()
                     if "glob.glob(" in l and "reverse=True" in l and "sorted(" not in l]
        good_call = ('sorted(glob.glob(os.path.join(_res, "unfinished_*.json")), '
                     'reverse=True)')
        if bad_lines:
            bad("app.py", "glob() is still CALLED with reverse=: %r" % bad_lines[0])
        elif good_call in body:
            ok("list_unfinished_runs() calls sorted(glob.glob(...), reverse=True)")
        else:
            bad("app.py", "the sorted(glob.glob(...), reverse=True) call is missing")

    # 4. the account-count helper must exist and read the watchdog record
    if "def unfinished_remaining_count(" in src:
        ok("unfinished_remaining_count() exists")
    else:
        bad("app.py", "unfinished_remaining_count() is missing")
    helper = strip_docstring(between(src, "def unfinished_remaining_count",
                                     "def save_unfinished"))
    if "return len(runstate.remaining())" in helper:
        ok("unfinished_remaining_count() reads runstate.remaining()")
    else:
        bad("app.py", "unfinished_remaining_count() does not read runstate.remaining()")

    # 5. the metric must use the helper, not a file count
    if "unfinished_count = unfinished_remaining_count()" in src:
        ok("the Resume Unfinished metric counts accounts")
    else:
        bad("app.py", "the metric still counts files")

    # 6. save_unfinished must write atomically
    saver = strip_docstring(between(src, "def save_unfinished", "def clear_unfinished"))
    if "os.replace(tmp, path)" in saver:
        ok("save_unfinished() writes atomically")
    else:
        bad("app.py", "save_unfinished() still truncates in place")

    # 7. the metric must be used where the tile is drawn
    if '("Resume Unfinished", unfinished_count)' in src:
        ok("the tile is wired to the account count")
    else:
        bad("app.py", "the Resume Unfinished tile is not wired to the count")

    print("PASSED %d  FAILED %d" % (len(PASSES), len(FAILS)))
    for f in FAILS:
        print("  - " + f)
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
