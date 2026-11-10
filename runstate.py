"""runstate.py - unfinished-run watchdog  (v13.78)
================================================
The run loop lives in app.py block 106. A Streamlit rerun (tab backgrounded,
WebSocket drop, phone lock, redeploy) tears the script down and the loop never
returns, so its own `finally` never runs and the run is never recorded.

app.py block 007 detects that: run_active is PROCESS state, so it is still True
on the load after a teardown, while the loop that owned it is gone. That is the
proof, and it is immediate - no waiting for a stale heartbeat.

REASONS
-------
tick() used to be the only writer and it always wrote "Streamlit rerun / tab
teardown (watchdog)", so a user Stop and a dropped connection were both reported
as a rerun. Three writers now exist and the specific ones win:

    note(reason)       an in-progress cause, stamped on the live record
    interrupt(reason)  the teardown itself, stamped by block 007 on the next load
    tick()             the last-resort sweep for a record with no cause at all

interrupt() and tick() both mirror the reason into unfinished_live.json, because
that is where the results summary reads it from.

One record per user, in that user's own mail_results/ directory, so two users
cannot see each other's progress. The record holds COUNTS only; the remaining
ACCOUNT LINES stay in unfinished_live.json, which app.py writes on every
checkpoint and in its own finally. remaining() reads that file and nothing else.

_write() always stamps the heartbeat with "now" - every production caller
(begin, progress, note, tick, interrupt, finish) means exactly that. Only the
selftest needs to lie about the clock, so it rewrites the record by hand.

CHANGES IN THIS REVISION
------------------------
RS-1  NO ENVIRONMENT VARIABLE IS READ. The override was an env var, and block
      043 bridges EVERY Streamlit secret into os.environ - so a secret of that
      name would have put every user on one shared record. It is a module-level
      _DIR_OVERRIDE now, set by the selftest and by nothing else, so no secret
      can reach it.

RS-2  _atomic_json(). interrupt() rewrote unfinished_live.json with a plain
      truncating write, while app.py block 083 uses .tmp + os.replace for that
      same file and says why: the checkpoint may be mid-write. This was the one
      shape the app's own docstring warns about, and it is now atomic.

RS-3  tick() MIRRORS ITS REASON. The watchdog stamped a reason on the record and
      never copied it into unfinished_live.json, so a watchdog-detected stop
      left the summary reading a file with no reason in it.

RS-4  A WRITE LOCK. _write() used one fixed ".tmp" name for every writer on every
      thread, so two writers could share it and os.replace could move a
      half-written file. An RLock plus mkstemp() in the same directory now.

RS-5  prune() IS CALLED. It had no caller anywhere, so a finished record sat on
      disk for the life of the account. tick() ages it out; PRUNE_DAYS replaces
      the hard-coded 7.

_write() now returns None when the write did not land, so a caller can tell.

Selftest (gate 12):   python3 runstate.py --selftest
"""

import json
import os
import tempfile
import threading
import time
from datetime import datetime

STALE_SECONDS = 60.0
# How long a FINISHED record is kept before tick() ages it out.
PRUNE_DAYS = 7
RUN_FILE = "unfinished_run.json"
UNFINISHED_FILE = "unfinished_live.json"

# RS-1: process-wide directory override. NOT an env var - see the header.
# The selftest sets it; production leaves it None and resolves through auth.
_DIR_OVERRIDE = None

# RS-4: one lock for the whole write path. RLock so a future nested call is safe.
_LOCK = threading.RLock()


def _stamp():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _dir():
    """This user's mail_results/ directory. The override wins when set."""
    ov = _DIR_OVERRIDE
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


def _atomic_json(path, obj):
    """Write `obj` as JSON to `path` atomically. True on success, False otherwise.

    RS-2/RS-4: mkstemp() gives each writer its own temporary name in the
    destination directory, so two writers cannot share one and os.replace() can
    only ever move a complete file. Never raises.
    """
    d = os.path.dirname(os.path.abspath(path)) or "."
    try:
        os.makedirs(d, exist_ok=True)
    except Exception:
        pass
    tmp = None
    try:
        fd, tmp = tempfile.mkstemp(prefix=os.path.basename(path) + ".",
                                   suffix=".tmp", dir=d)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f)
            f.flush()
            try:
                os.fsync(f.fileno())
            except Exception:
                pass
        os.replace(tmp, path)
        return True
    except Exception:
        if tmp:
            try:
                os.remove(tmp)
            except Exception:
                pass
        return False


def _write(rec):
    """Persist `rec` atomically. Returns the path, or None when it did not land."""
    rec["heartbeat"] = time.time()
    p = _path()
    with _LOCK:
        return p if _atomic_json(p, rec) else None


def _mirror_reason(reason):
    """Copy `reason` into unfinished_live.json ATOMICALLY. Never raises.

    RS-2/RS-3: shared by interrupt() and tick(), so the watchdog path cannot
    drift from the teardown path again. The live file's other keys (remaining,
    checked, total, saved_at) are preserved - this only stamps the reason.
    """
    uf = os.path.join(_dir(), UNFINISHED_FILE)
    if not os.path.exists(uf):
        return False
    with _LOCK:
        try:
            with open(uf, encoding="utf-8") as f:
                data = json.load(f) or {}
            if not isinstance(data, dict):
                data = {}
            data["reason"] = str(reason or "")[:200]
            return _atomic_json(uf, data)
        except Exception:
            return False


def begin(total):
    """Start a run record. Called once, when the queue is ready."""
    rec = {"state": "running", "total": int(total or 0), "checked": 0,
           "started_at": _stamp(), "reason": "", "cause": ""}
    return _write(rec)


def progress(checked, total, cause=None):
    """Heartbeat plus counts. Called from the checkpoint.

    `cause` is written when given, so the checkpoint is also where a live
    network problem gets recorded.
    """
    rec = _read() or {"state": "running", "started_at": _stamp(), "reason": "",
                      "cause": ""}
    rec["state"] = "running"
    rec["checked"] = int(checked or 0)
    rec["total"] = int(total or 0)
    if cause is not None:
        rec["cause"] = str(cause)[:200]
    return _write(rec)


def note(reason):
    """Stamp an in-progress cause on a running record."""
    rec = _read()
    if not rec or rec.get("state") != "running":
        return None
    rec["cause"] = str(reason or "")[:200]
    return _write(rec)


def cause():
    """The cause stamped on the live record, or ''."""
    rec = _read() or {}
    return str(rec.get("cause") or "")


def interrupt(reason):
    """Mark the live record interrupted, with the reason, and mirror the reason
    into unfinished_live.json so the results summary can name it."""
    rec = _read()
    if not rec or rec.get("state") != "running":
        return None
    rec["state"] = "interrupted"
    rec["reason"] = str(reason or "interrupted")[:200]
    rec["interrupted_at"] = _stamp()
    p = _write(rec)
    _mirror_reason(rec["reason"])
    return p


def tick():
    """Last-resort watchdog.

    Returns the record path while a live run is still beating, or after marking a
    quiet one interrupted. Returns None when nothing is open, and None for a
    finished record - which is also where an aged-out record is dropped.
    """
    rec = _read()
    if not rec:
        return None

    if rec.get("state") == "finished":
        # RS-5: THE AGEING POINT. tick() is the only call that already runs on
        # every load, after auth.require() and on the script thread - the only
        # place a per-user path resolves to the owner - and it returns early for
        # a non-running record, so ageing here is invisible to every caller.
        prune()
        return None

    if rec.get("state") != "running":
        return None

    if (time.time() - float(rec.get("heartbeat") or 0.0)) < STALE_SECONDS:
        return _path()

    rec["state"] = "interrupted"
    rec["reason"] = (rec.get("cause")
                     or "Streamlit rerun / tab teardown (watchdog)")
    rec["interrupted_at"] = _stamp()
    p = _write(rec)
    # RS-3: mirror it, or the summary reads a file with no reason in it.
    _mirror_reason(rec["reason"])
    return p


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


def prune(max_age_days=PRUNE_DAYS):
    """Delete a FINISHED record older than max_age_days. True when it went."""
    rec = _read()
    if not rec or rec.get("state") != "finished":
        return False
    try:
        age = time.time() - float(rec.get("heartbeat") or 0.0)
    except Exception:
        return False
    if age < float(max_age_days) * 86400:
        return False
    drop()
    return True


def _selftest():
    import shutil
    import tempfile

    global _DIR_OVERRIDE

    d = tempfile.mkdtemp(prefix="runstate_")
    _DIR_OVERRIDE = d
    fails = []

    def check(name, cond):
        print("%s %s" % ("OK  " if cond else "FAIL", name))
        if not cond:
            fails.append(name)

    def backdate(seconds):
        """Age the stored heartbeat.

        _write() always stamps "now", so the record has to be rewritten by hand
        here - calling _write() after setting an old heartbeat just overwrites it
        and the staleness path never arms.
        """
        rec = _read() or {}
        rec["heartbeat"] = time.time() - float(seconds)
        with open(_path(), "w", encoding="utf-8") as f:
            json.dump(rec, f)

    def live_file(**kw):
        data = {"id": "live", "reason": "", "checked": 0, "total": 0,
                "remaining": [], "saved_at": "2026-01-01 00:00:00"}
        data.update(kw)
        with open(os.path.join(d, UNFINISHED_FILE), "w", encoding="utf-8") as f:
            json.dump(data, f)
        return data

    try:
        check("no record before begin", _read() is None)
        check("tick with no record is None", tick() is None)
        check("interrupt with no record is None", interrupt("x") is None)
        check("cause with no record is empty", cause() == "")

        p = begin(120)
        check("begin writes a record", bool(p) and os.path.exists(p))
        rec = _read() or {}
        check("begin marks it running", rec.get("state") == "running")
        check("begin stores the total", rec.get("total") == 120)

        progress(7, 120)
        check("progress stores the count", (_read() or {}).get("checked") == 7)
        note("network flapping")
        check("note stores the cause", cause() == "network flapping")

        check("tick while beating returns the path", tick() == _path())

        backdate(STALE_SECONDS + 5)
        tick()
        rec = _read() or {}
        check("a quiet record is marked interrupted", rec.get("state") == "interrupted")
        check("tick keeps the existing cause as the reason",
              rec.get("reason") == "network flapping")

        live_file(remaining=["a@x.com", "b@x.com"], checked=7, total=120)
        interrupt("UI interaction / rerun - the run loop was torn down")
        rec = _read() or {}
        check("interrupt marks it interrupted", rec.get("state") == "interrupted")
        check("interrupt stores the reason",
              rec.get("reason") == "UI interaction / rerun - the run loop was torn down")
        with open(os.path.join(d, UNFINISHED_FILE), encoding="utf-8") as f:
            uf = json.load(f) or {}
        check("interrupt mirrors the reason into unfinished_live.json",
              uf.get("reason") == rec.get("reason"))
        check("interrupt keeps the rest of the live file",
              uf.get("remaining") == ["a@x.com", "b@x.com"] and uf.get("checked") == 7)
        check("summary reports the interruption",
              any("interrupted" in ln for ln in summary()))

        # RS-3: the watchdog path must mirror too.
        live_file(reason="", remaining=["c@x.com"])
        begin(10)
        backdate(STALE_SECONDS + 5)
        tick()
        with open(os.path.join(d, UNFINISHED_FILE), encoding="utf-8") as f:
            uf = json.load(f) or {}
        check("tick mirrors its own reason", bool(uf.get("reason")))
        check("tick keeps the remaining lines", uf.get("remaining") == ["c@x.com"])

        # RS-5: ageing. A fresh finished record survives, a stale one does not.
        progress(10, 10)
        finish()
        check("finish marks it finished", (_read() or {}).get("state") == "finished")
        check("a finished run is not listed as running",
              not any("running now" in ln for ln in summary()))
        check("prune leaves a fresh finished record", prune() is False)
        tick()
        check("tick leaves a fresh finished record alone", _read() is not None)
        backdate((PRUNE_DAYS + 1) * 86400)
        tick()
        check("tick ages out a stale finished record", _read() is None)

        # RS-4: a write that cannot land reports None.
        blocker = os.path.join(d, "blocker")
        with open(blocker, "w", encoding="utf-8") as f:
            f.write("x")
        _DIR_OVERRIDE = os.path.join(blocker, "sub")
        check("a failed write returns None", begin(3) is None)
        _DIR_OVERRIDE = d

        begin(1)
        check("the record is readable again after the failure", _read() is not None)
        drop()
        check("drop clears the record", _read() is None)
    finally:
        shutil.rmtree(d, ignore_errors=True)
        _DIR_OVERRIDE = None

    print("SELFTEST: %s (%d failure(s))"
          % ("OK" if not fails else "FAILED", len(fails)))
    return 1 if fails else 0


if __name__ == "__main__":
    import sys
    if "--selftest" in sys.argv:
        raise SystemExit(_selftest())
    print("usage: python3 runstate.py --selftest")
