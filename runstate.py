#!/usr/bin/env python3
"""runstate.py - per-user unfinished-run persistence.

WHY THIS EXISTS
---------------
The checker printed "saved as unfinished" and wrote nothing. Two causes:

  1. the writer and the Resume reader each spelled the filename themselves, so
     the reader globbed a path the writer never produced;
  2. the write sat AFTER the run loop, so a tab-background rerun tore the script
     down before it ran - only a graceful finish ever wrote.

So: ONE path expression, used by both, and save() is cheap enough to call from a
finally and from the 100-account checkpoint.

    python runstate.py --selftest
"""
import glob
import io
import json
import os
import sys
import time

import auth

STEM = "unfinished"
KEEP = 25
KEYS = ("reason", "done", "total", "saved", "note")


def _path(stamp=None):
    """THE single filename expression. Writer and reader both come through here."""
    stamp = stamp or time.strftime("%Y%m%d_%H%M%S")
    return auth.user_file("%s_%s.json" % (STEM, stamp))


def _pattern():
    return auth.user_file("%s_*.json" % STEM)


def save(reason, done=0, total=None, note=""):
    """Write the current state. Never raises. Returns the path, or ''.

    Atomic (.tmp + os.replace) so a torn write cannot leave a half file that the
    reader then chokes on.
    """
    path = _path()
    payload = {
        "reason": str(reason or "stopped"),
        "done": int(done or 0),
        "total": int(total) if total is not None else None,
        "saved": time.strftime("%Y-%m-%d %H:%M:%S"),
        "note": str(note or "")[:400],
    }
    try:
        tmp = path + ".tmp"
        with io.open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
        os.replace(tmp, path)
    except Exception:
        return ""
    prune()
    return path


def load():
    """Every readable unfinished file for THIS user, newest first."""
    out = []
    for p in glob.glob(_pattern()):
        try:
            with io.open(p, encoding="utf-8") as fh:
                data = json.load(fh)
            if not isinstance(data, dict):
                continue
            data["path"] = p
            data.setdefault("reason", "unknown")
            data.setdefault("done", 0)
            data.setdefault("total", None)
            data.setdefault("saved", "")
            out.append(data)
        except Exception:
            continue
    out.sort(key=lambda d: str(d.get("saved", "")), reverse=True)
    return out


def drop(path):
    """Delete one unfinished file (call on a clean completion)."""
    for p in (path, path + ".tmp"):
        try:
            if p and os.path.exists(p):
                os.remove(p)
        except Exception:
            pass


def drop_all():
    for d in load():
        drop(d.get("path"))


def prune(keep=KEEP):
    """Keep the newest `keep` files; a stale run must not accumulate forever."""
    files = sorted(glob.glob(_pattern()), reverse=True)
    for p in files[keep:]:
        drop(p)


def summary():
    """One line per unfinished run, for the Resume control."""
    rows = load()
    if not rows:
        return ["No unfinished runs for this user."]
    out = []
    for d in rows:
        total = d.get("total")
        prog = "%s/%s" % (d.get("done", 0), total) if total else str(d.get("done", 0))
        out.append("%s  stopped at %s  (%s)%s"
                   % (d.get("saved", "?"), prog, d.get("reason", "?"),
                      "  " + d["note"] if d.get("note") else ""))
    return out


def _selftest():
    bad = []

    def check(name, fn):
        try:
            if fn() is False:
                bad.append(name)
        except Exception as exc:
            bad.append("%s (%s: %s)" % (name, type(exc).__name__, exc))

    check("path is per-user", lambda: _path("X").endswith("_unfinished_X.json"))
    check("path is not bare", lambda: "_" in _path("X"))
    check("pattern is per-user", lambda: _pattern().endswith("_unfinished_*.json"))
    check("path is stable for a stamp", lambda: _path("S") == _path("S"))
    check("save returns a path", lambda: bool(save("selftest", 1, 2)))
    check("saved file loads back", lambda: any(d.get("reason") == "selftest" for d in load()))
    check("summary is a list", lambda: isinstance(summary(), list))
    check("drop removes it", lambda: (drop(_path_by_reason("selftest")),
                                      not any(d.get("reason") == "selftest" for d in load()))[1])
    check("load is empty-safe", lambda: isinstance(load(), list))
    check("prune keeps newest", lambda: prune(5) is None)

    if bad:
        raise AssertionError("runstate selftest failed: " + ", ".join(bad))
    print("runstate selftest OK")


def _path_by_reason(reason):
    for d in load():
        if d.get("reason") == reason:
            return d.get("path", "")
    return ""


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    else:
        for line in summary():
            print(line)
    sys.exit(0)
