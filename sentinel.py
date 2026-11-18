"""sentinel.py - expect / satisfy / sweep: a per-user "did it actually deliver" watchdog.

PLAIN MODULE, like runstate.py, mailsearch.py and mailsort.py. No frame, no gate
rows, nothing to register.

THE SHAPE
---------
    sentinel.expect("fetch", "Fetch & Test produced no node")
    ...do the fetch...
    sentinel.satisfy("fetch")      # only when it really produced something

and once per page load, near the top of the script:

    sentinel.sweep()

sweep() raises one notification for every expectation whose window has passed
without being satisfied, as kind="watch", and marks it fired so it reports once
per REPEAT window instead of on every rerun.

WHY THE BELL AND NOT JUST A MESSAGE
-----------------------------------
A fetch, a re-probe and a run all report on the screen that was pressed - and
that screen is exactly what nobody is looking at when the tab is in a pocket.
"It produced nothing" is the one outcome worth a bell, and it is the one outcome
a screen message cannot deliver if there is no screen.

WHY IN MEMORY
-------------
An expectation lives for minutes, in one process, for one session. On disk, a
stale "fetch produced nothing" from yesterday would greet you today. It is a
process dict keyed by the caller's own scope, so two users cannot satisfy each
other's, and satisfied entries are reaped after REAP_SECONDS.

Every function swallows: a watchdog must never be the reason a page dies.
"""

import os
import threading
import time

KIND = "watch"
DEFAULT_REPEAT = 3600.0
REAP_SECONDS = 3600.0
MAX_ENTRIES = 60

_lock = threading.RLock()
_reg = {}


def _scope():
    try:
        import auth
        return os.path.basename(auth.user_file("")) or "anon"
    except Exception:
        return "anon"


def _key(name):
    return (_scope(), str(name or "")[:60])


def _reap(now):
    """Drop settled entries that are old enough to be forgotten."""
    try:
        for k in [k for k, v in _reg.items()
                  if v.get("ok") and (now - float(v.get("ok_ts") or now)) > REAP_SECONDS]:
            _reg.pop(k, None)
        if len(_reg) > MAX_ENTRIES:
            for k in sorted(_reg, key=lambda k: float(_reg[k].get("armed_ts") or 0))[:20]:
                _reg.pop(k, None)
    except Exception:
        pass


def expect(name, label, suggestion="", window=0.0, severity="warn",
           repeat=DEFAULT_REPEAT):
    """Arm (or re-arm) one expectation.

    `window` 0 means "fire on the very next sweep", which is the right value for
    an action that either delivers on the spot or does not deliver at all.
    """
    try:
        now = time.time()
        try:
            window = max(0.0, float(window))
        except Exception:
            window = 0.0
        sev = severity if severity in ("info", "warn", "critical") else "warn"
        with _lock:
            _reap(now)
            _reg[_key(name)] = {
                "name": str(name),
                "label": str(label or name),
                "suggestion": str(suggestion or ""),
                "due": now + window,
                "severity": sev,
                "repeat": max(60.0, float(repeat)),
                "armed_ts": now,
                "fired_ts": 0.0,
                "ok": False,
                "ok_ts": 0.0,
            }
    except Exception:
        pass


def satisfy(name, note=""):
    """Mark it delivered. Later sweeps stop reporting it."""
    try:
        with _lock:
            ent = _reg.get(_key(name))
            if ent is None:
                return False
            ent["ok"] = True
            ent["ok_ts"] = time.time()
            ent["note"] = str(note or "")
            return True
    except Exception:
        return False


def drop(name):
    try:
        with _lock:
            _reg.pop(_key(name), None)
    except Exception:
        pass


def state(name):
    """"waiting" | "satisfied" | "fired" | "unknown"."""
    try:
        with _lock:
            ent = _reg.get(_key(name))
        if ent is None:
            return "unknown"
        if ent.get("ok"):
            return "satisfied"
        if ent.get("fired_ts"):
            return "fired"
        return "waiting"
    except Exception:
        return "unknown"


def active():
    """This scope's unsettled entries, soonest due first."""
    try:
        now = time.time()
        with _lock:
            mine = [v for k, v in _reg.items() if k[0] == _scope() and not v.get("ok")]
        return sorted(mine, key=lambda v: float(v.get("due") or now))
    except Exception:
        return []


def sweep(now=None):
    """Fire everything due and unsettled. Returns the names fired.

    Idempotent: an entry fires once per `repeat` window, so a rerun loop cannot
    turn one dead fetch into fifty notifications.
    """
    fired = []
    try:
        import notify
    except Exception:
        return fired
    try:
        now = float(now if now is not None else time.time())
        with _lock:
            _reap(now)
            due = []
            for k, v in _reg.items():
                if k[0] != _scope() or v.get("ok"):
                    continue
                if now < float(v.get("due") or 0):
                    continue
                last = float(v.get("fired_ts") or 0.0)
                if last and (now - last) < float(v.get("repeat") or DEFAULT_REPEAT):
                    continue
                due.append((k, v))
            for k, v in due:
                v["fired_ts"] = now
                fired.append(v.get("name"))
    except Exception:
        return fired
    for k, v in due if 'due' in dir() else []:
        try:
            notify.add(v.get("severity") or "warn", KIND, v.get("label"),
                       v.get("suggestion") or "", key="watch:" + str(v.get("name")))
        except Exception:
            continue
    return fired


def clear():
    try:
        with _lock:
            for k in [k for k in _reg if k[0] == _scope()]:
                _reg.pop(k, None)
    except Exception:
        pass
