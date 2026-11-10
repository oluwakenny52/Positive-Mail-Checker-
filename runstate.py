"""runstate.py - unfinished-run watchdog  (v13.77)
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

interrupt() also rewrites the reason in unfinished_live.json, because that is
where the results summary reads it from.

One record per user, in that user's own mail_results/ directory, so two users
cannot see each other's progress. The record holds COUNTS only; the remaining
ACCOUNT LINES stay in unfinished_live.json, which app.py writes on every
checkpoint and in its own finally. remaining() reads that file and nothing else.

v13.77 FIX PRUNE-1: prune() HAD NO CALLER. It existed, it worked, and nothing in
app.py or in any page ever called it, so a FINISHED record sat in
unfinished_run.json for the life of the account. It is not a leak - summary()
filters to running/interrupted and clear_unfinished() takes the queue file on a
clean finish - but it is dead code with a stale file behind it. tick() ages the
record out now: it is the only call that already runs on every load, after
auth.require() (so the per-user path is resolved correctly), on the script
thread, and it returns early for a non-running record, which makes the ageing
invisible to every caller. drop() is therefore live again too.

v13.77 FIX PRUNE-2: THE TEST OVERRIDE COULD BE SHADOWED BY A SECRET. The
directory override was the environment variable BB_RUN_DIR, and app.py block
043 bridges EVERY Streamlit secret into os.environ under its own key - so a
secret named BB_RUN_DIR would have overridden the per-user directory for the
whole process and put every user on one record, silently. Nothing outside this
file referenced the name, so it is RUNSTATE_DIR_OVERRIDE now, which no secret
is going to collide with.

_write() also stopped lying: it returned the path even when the write had
failed, so no caller could ever tell. It returns None on failure.

_write() always stamps the heartbeat with "now" - every production caller
(begin, progress, note, tick, interrupt, finish) means exactly that. Only the
selftest needs to lie about the clock, so it rewrites the record by hand.

Selftest (gate 12):   python3 runstate.py --selftest
"""

import json
import os
import time
from datetime import datetime

STALE_SECONDS = 60.0
# How long a FINISHED record is kept before tick() ages it out.
PRUNE_DAYS = 7
RUN_FILE = "unfinished_run.json"
UNFINISHED_FILE = "unfinished_live.json"
# Process-wide directory override. Distinctive on purpose - see FIX PRUNE-2.
RUN_DIR_OVERRIDE = "RUNSTATE_DIR_OVERRIDE"


def _stamp():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _dir():
    ov = os.environ.get(RUN_DIR_OVERRIDE)
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
    """Persist `rec` atomically. Returns the path, or None when it did not land."""
    p = _path()
    rec["heartbeat"] = time.time()
    tmp = p + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(rec, f)
        os.replace(tmp, p)
    except Exception:
        return None
    return p


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
    """Stamp an in-progress cause without changing the state."""
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
    try:
        uf = os.path.join(_dir(), UNFINISHED_FILE)
        if os.path.exists(uf):
            with open(uf, encoding="utf-8") as f:
                data = json.load(f) or {}
            data["reason"] = rec["reason"]
            with open(uf, "w", encoding="utf-8") as f:
                json.dump(data, f)
    except Exception:
        pass
    return p


def tick():
    """Last-resort watchdog. Returns the record path while a live run is still
    beating, or after marking a quiet one interrupted. Returns None when nothing
    is open.

    v13.77 FIX PRUNE-1: a FINISHED record is also aged out here. See prune().
    """
    rec = _read()
    if not rec or rec.get("state") != "running":
        if rec and rec.get("state") == "finished":
            prune()
        return None
    if (time.time() - float(rec.get("heartbeat") or 0.0)) < STALE_SECONDS:
        return _path()
    rec["state"] = "interrupted"
    rec["reason"] = (rec.get("cause")
                     or "Streamlit rerun / tab teardown (watchdog)")
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


def prune(max_age_days=PRUNE_DAYS):
    """Delete a finished record older than max_age_days.

    v13.77 FIX PRUNE-1: this had no caller at all. tick() calls it now for a
    finished record, so a completed run is aged out instead of sitting on disk
    for the life of the account. It stays callable on its own and still refuses
    anything that is not FINISHED, so an interrupted run with a resumable queue
    is never taken.
    """
    rec = _read()
    if not rec or rec.get("state") != "finished":
        return False
    try:
        age = time.time() - float(rec.get("heartbeat") or 0.0)
    except Exception:
        return False
    if age < max_age_days * 86400:
        return False
    drop()
    return True


def _selftest():
    import shutil
    import tempfile

    d = tempfile.mkdtemp(prefix="runstate_")
    os.environ[RUN_DIR_OVERRIDE] = d
    fails = []

    def check(name, cond):
        print("%s %s" % ("OK  " if cond else "FAIL", name))
        if not cond:
            fails.append(name)

    def backdate(seconds):
        """Age the stored heartbeat.

        _write() always stamps "now", so the record has to be rewritten by hand
        here - calling _write() after setting an old heartbeat just overwrites
        it and the staleness path never arms.
        """
        rec = _read() or {}
        rec["heartbeat"] = time.time() - float(seconds)
        with open(_path(), "w", encoding="utf-8") as f:
            json.dump(rec, f)

    try:
        check("no record before begin", _read() is None)
        check("tick with no record is None", tick() is None)
        check("interrupt with no record is None", interrupt("x") is None)
        check("cause with no record is empty", cause() == "")

        p = begin(120)
        check("begin writes a record", os.path.exists(p))
        rec = _read() or {}
        check("state is running", rec.get("state") == "running")
        check("total is stored", rec.get("total") == 120)
        check("cause starts empty", rec.get("cause") == "")

        check("tick keeps a beating run", tick() == p)

        progress(100, 120, cause="8 consecutive transport failures")
        rec = _read() or {}
        check("progress stores counts",
              rec.get("checked") == 100 and rec.get("total") == 120)
        check("progress stores the cause",
              rec.get("cause") == "8 consecutive transport failures")
        check("cause() reads it back",
              cause() == "8 consecutive transport failures")

        note("Stopped by user (Stop button)")
        check("note overwrites the cause",
              cause() == "Stopped by user (Stop button)")

        backdate(STALE_SECONDS + 5.0)
        check("the backdated record is stale",
              (time.time() - float((_read() or {}).get("heartbeat", 0))) > STALE_SECONDS)
        tick()
        rec = _read() or {}
        check("a quiet run is interrupted", rec.get("state") == "interrupted")
        check("tick reuses the stamped cause",
              rec.get("reason") == "Stopped by user (Stop button)")
        check("an interrupted run is not re-ticked", tick() is None)
        check("interrupt on a non-running record is None", interrupt("late") is None)

        with open(os.path.join(d, UNFINISHED_FILE), "w", encoding="utf-8") as f:
            json.dump({"saved_at": "2026-01-01 00:00:00",
                       "remaining": ["a@b.c:1", "d@e.f:2"],
                       "reason": "In Progress (Running)"}, f)
        check("remaining reads both lines", len(remaining()) == 2)

        progress(120, 120)
        check("progress revives the record",
              (_read() or {}).get("state") == "running")
        check("progress keeps the cause when none is passed",
              cause() == "Stopped by user (Stop button)")

        interrupt("UI interaction / rerun - the run loop was torn down")
        rec = _read() or {}
        check("interrupt marks it interrupted", rec.get("state") == "interrupted")
        check("interrupt stores the reason",
              rec.get("reason") == "UI interaction / rerun - the run loop was torn down")
        with open(os.path.join(d, UNFINISHED_FILE), encoding="utf-8") as f:
            uf = json.load(f) or {}
        check("interrupt mirrors the reason into unfinished_live.json",
              uf.get("reason") == rec.get("reason"))
        check("summary reports the interruption",
              any("interrupted" in ln for ln in summary()))

        progress(120, 120)
        finish()
        check("finish marks it finished",
              (_read() or {}).get("state") == "finished")
        check("a finished run is not listed as running",
              not any("running now" in ln for ln in summary()))

        # v13.77 FIX PRUNE-1: the ageing path. It had no caller AND no test,
        # which is how it got orphaned. A fresh finished record must survive a
        # tick; an aged one must be taken by it; an interrupted one must not.
        tick()
        check("a fresh finished record survives a tick", _read() is not None)
        backdate(PRUNE_DAYS * 86400 + 60)
        tick()
        check("an aged finished record is pruned by tick", _read() is None)

        begin(5)
        backdate(PRUNE_DAYS * 86400 + 60)
        tick()
        check("an aged INTERRUPTED record is not pruned by the first tick",
              _read() is not None)
        check("the first tick marked it interrupted",
              (_read() or {}).get("state") == "interrupted")

        drop()
        check("drop clears the record", _read() is None)
    finally:
        shutil.rmtree(d, ignore_errors=True)
        os.environ.pop(RUN_DIR_OVERRIDE, None)

    print("SELFTEST: %s (%d failure(s))"
          % ("OK" if not fails else "FAILED", len(fails)))
    return 1 if fails else 0


if __name__ == "__main__":
    import sys
    if "--selftest" in sys.argv:
        raise SystemExit(_selftest())
    print("usage: python3 runstate.py --selftest")
