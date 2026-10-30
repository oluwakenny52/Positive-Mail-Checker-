"""runstate.py - unfinished-run watchdog  (v13.47)
================================================
The run loop lives in app.py block 106. A Streamlit rerun (tab backgrounded,
WebSocket drop, phone lock, redeploy) tears the script down and the loop never
returns, so its own `finally` never runs and the run is never recorded.

tick() is called from app.py block 007 on EVERY page load. If a record is still
marked "running" and its heartbeat has gone quiet, tick() flips it to
"interrupted" - so a torn-down run is recorded on the NEXT load, with no
try/finally around the loop.

One record per user, in that user's own mail_results/ directory, so two users
cannot see each other's progress. The record holds COUNTS only; the remaining
ACCOUNT LINES stay in unfinished_live.json, which app.py already writes at every
100-check checkpoint and in its own finally. remaining() reads that file and
nothing else.

Selftest (gate 12):   python3 runstate.py --selftest
"""

import json
import os
import time
from datetime import datetime

STALE_SECONDS = 60.0
RUN_FILE = "unfinished_run.json"
UNFINISHED_FILE = "unfinished_live.json"


def _stamp():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _dir():
    ov = os.environ.get("BB_RUN_DIR")
    if ov:
        return ov
    try:
        import auth
        return auth.user_file("mail_results")
    except Exception:
        return "mail_results"


def _path():
    d = _dir()
    try:
        os.makedirs(d, exist_ok=True)
    except Exception:
        pass
    return os.path.join(d, RUN_FILE)


def _read():
    try:
        with open(_path(), encoding="utf-8") as f:
            rec = json.load(f)
        return rec if isinstance(rec, dict) else None
    except Exception:
        return None


def _write(rec):
    p = _path()
    rec["heartbeat"] = time.time()
    tmp = p + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(rec, f)
        os.replace(tmp, p)
    except Exception:
        return p
    return p


def begin(total):
    """Start a run record. Called once, when the queue is ready."""
    rec = {"state": "running", "total": int(total or 0), "checked": 0,
           "started_at": _stamp(), "reason": ""}
    return _write(rec)


def progress(checked, total):
    """Heartbeat plus counts. Called from the 100-account checkpoint."""
    rec = _read() or {"state": "running", "started_at": _stamp(), "reason": ""}
    rec["state"] = "running"
    rec["checked"] = int(checked or 0)
    rec["total"] = int(total or 0)
    return _write(rec)


def tick():
    """Watchdog. Returns the record path while a live run is still beating, or
    after marking a quiet one interrupted. Returns None when nothing is open."""
    rec = _read()
    if not rec or rec.get("state") != "running":
        return None
    if (time.time() - float(rec.get("heartbeat") or 0.0)) < STALE_SECONDS:
        return _path()
    rec["state"] = "interrupted"
    rec["reason"] = "Streamlit rerun / tab teardown (watchdog)"
    rec["interrupted_at"] = _stamp()
    return _write(rec)


def finish():
    """Clean completion - the record stops beating."""
    rec = _read()
    if not rec:
        return None
    rec["state"] = "finished"
    rec["reason"] = "Completed"
    rec["checked"] = rec.get("total", rec.get("checked", 0))
    rec["finished_at"] = _stamp()
    return _write(rec)


def _label(rec):
    s = rec.get("state")
    if s == "running":
        return "running now"
    if s == "interrupted":
        return "interrupted"
    return "completed"


def _saved_at():
    try:
        with open(os.path.join(_dir(), UNFINISHED_FILE), encoding="utf-8") as f:
            return (json.load(f) or {}).get("saved_at") or "?"
    except Exception:
        return "?"


def remaining():
    """The account lines still to check, straight from unfinished_live.json."""
    try:
        with open(os.path.join(_dir(), UNFINISHED_FILE), encoding="utf-8") as f:
            rec = json.load(f) or {}
        return [str(x) for x in (rec.get("remaining") or []) if str(x).strip()]
    except Exception:
        return []


def summary():
    """Lines for the Resume control. Empty when nothing is worth resuming."""
    out = []
    rec = _read()
    if rec and rec.get("state") in ("running", "interrupted"):
        line = ("%s | %s | %s/%s checked"
                % (rec.get("started_at", "?"), _label(rec),
                   rec.get("checked", 0), rec.get("total", 0)))
        if rec.get("reason"):
            line += " | " + str(rec["reason"])
        out.append(line)
    left = remaining()
    if left:
        out.append("%d account(s) still to check, saved %s" % (len(left), _saved_at()))
    return out


def load():
    return _read()


def drop():
    d = _dir()
    for name in (RUN_FILE, UNFINISHED_FILE):
        try:
            os.remove(os.path.join(d, name))
        except Exception:
            pass


def prune(max_age_days=7):
    """Delete a finished record older than max_age_days."""
    rec = _read()
    if not rec or rec.get("state") != "finished":
        return False
    if (time.time() - float(rec.get("heartbeat") or 0.0)) < max_age_days * 86400:
        return False
    drop()
    return True


def _selftest():
    import shutil
    import tempfile

    d = tempfile.mkdtemp(prefix="runstate_")
    os.environ["BB_RUN_DIR"] = d
    fails = []

    def check(name, cond):
        print("%s %s" % ("OK  " if cond else "FAIL", name))
        if not cond:
            fails.append(name)

    try:
        check("no record before begin", _read() is None)
        check("tick with no record is None", tick() is None)

        p = begin(120)
        check("begin writes a record", os.path.exists(p))
        rec = _read() or {}
        check("state is running", rec.get("state") == "running")
        check("total is stored", rec.get("total") == 120)

        check("tick keeps a beating run", tick() == p)

        progress(100, 120)
        rec = _read() or {}
        check("progress stores counts",
              rec.get("checked") == 100 and rec.get("total") == 120)

        rec["heartbeat"] = time.time() - (STALE_SECONDS + 5.0)
        _write(rec)
        tick()
        rec = _read() or {}
        check("a quiet run is interrupted", rec.get("state") == "interrupted")
        check("an interrupted run is not re-ticked", tick() is None)

        with open(os.path.join(d, UNFINISHED_FILE), "w", encoding="utf-8") as f:
            json.dump({"saved_at": "2026-01-01 00:00:00",
                       "remaining": ["a@b.c:1", "d@e.f:2"]}, f)
        check("remaining reads both lines", len(remaining()) == 2)
        check("summary reports the interruption",
              any("interrupted" in ln for ln in summary()))

        progress(120, 120)
        check("progress revives the record",
              (_read() or {}).get("state") == "running")
        finish()
        check("finish marks it finished",
              (_read() or {}).get("state") == "finished")
        check("a finished run is not listed as running",
              not any("running now" in ln for ln in summary()))

        drop()
        check("drop clears the record", _read() is None)
    finally:
        shutil.rmtree(d, ignore_errors=True)
        os.environ.pop("BB_RUN_DIR", None)

    print("SELFTEST: %s (%d failure(s))"
          % ("OK" if not fails else "FAILED", len(fails)))
    return 1 if fails else 0


if __name__ == "__main__":
    import sys
    if "--selftest" in sys.argv:
        raise SystemExit(_selftest())
    print("usage: python3 runstate.py --selftest")
