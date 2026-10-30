#!/usr/bin/env python3
"""test_resume_io.py - gate 13: the Resume Unfinished path must actually work.

The bug this exists for: app.py block 083 called

    glob.glob(path, reverse=True)

`reverse` is a sorted() keyword, not a glob() one, so the call raised TypeError
and the bare `except Exception: pass` inside list_unfinished_runs() swallowed
it. The function returned [] on every call, so the Resume Unfinished counter
read 0 and the inspector said "No items" while the record sat on disk.

A substring gate cannot catch that - the broken text was right there and looked
right. This one CALLS the expression, then proves the source no longer uses the
broken form.

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

    # 3. list_unfinished_runs() must not use the broken form
    src = io.open("app.py", encoding="utf-8").read()
    body = between(src, "def list_unfinished_runs", "def unfinished_remaining_count")
    if not body:
        bad("app.py", "list_unfinished_runs() body not found")
    elif "reverse=True" in body:
        bad("app.py", "list_unfinished_runs() still passes reverse= to glob()")
    else:
        ok("list_unfinished_runs() no longer passes reverse= to glob()")

    # 4. the account-count helper must exist and read the watchdog record
    if "def unfinished_remaining_count(" in src:
        ok("unfinished_remaining_count() exists")
    else:
        bad("app.py", "unfinished_remaining_count() is missing")
    helper = between(src, "def unfinished_remaining_count", "def save_unfinished")
    if "runstate.remaining()" in helper:
        ok("unfinished_remaining_count() reads runstate.remaining()")
    else:
        bad("app.py", "unfinished_remaining_count() does not read runstate.remaining()")

    # 5. the metric must use the helper, not a file count
    if "unfinished_count = unfinished_remaining_count()" in src:
        ok("the Resume Unfinished metric counts accounts")
    else:
        bad("app.py", "the metric still counts files")

    # 6. save_unfinished must write atomically
    saver = between(src, "def save_unfinished", "def clear_unfinished")
    if "os.replace(tmp, path)" in saver:
        ok("save_unfinished() writes atomically")
    else:
        bad("app.py", "save_unfinished() still truncates in place")

    print("PASSED %d  FAILED %d" % (len(PASSES), len(FAILS)))
    for f in FAILS:
        print("  - " + f)
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
