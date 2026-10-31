"""audit_log.py - per-user click & outcome ledger  (v13.48)

Records every press of a button or form submit with the page it came from, and
records the outcome the run then reports: OK / FAILED / WARN / ERROR / STOPPED,
or "no outcome reported" when the action finished silently.

Plain module, NOT frame-gated - like runstate.py.  Nothing here renders.

WHY WRAPPING INSTEAD OF AN audit_log.click() CALL IN EVERY BUTTON
-----------------------------------------------------------------
app.py alone has twenty-odd buttons and four pages have more.  Wrapping
st.button / st.form_submit_button / st.download_button once per process records
all of them - including any button added later - with no per-site edit and
nothing to forget.  The message surface (st.success / st.error / st.warning /
st.exception) is wrapped the same way, so the outcome is captured without a
single call being added inside an action body.

WHY A RERUN IS NOT AN OUTCOME
-----------------------------
Most actions here end in flash(...) + st.rerun(), and the flash is rendered on
the NEXT run.  st.rerun therefore keeps the entry OPEN for one more run so that
message can be attributed to it.  Anything still open after that is closed as
"no outcome reported" - an action that said nothing.

ISOLATION
---------
The file resolves through auth.user_file(), so it is <hash>_mail_results/
action_log.jsonl - one ledger per user, never shared.  Capped at MAX_LINES with
the oldest trimmed, so it cannot grow without bound.

A failure in here must never break a page: every public function swallows.
"""

import json
import os
import time
from datetime import datetime

MAX_LINES = 500
_ATTR = "_audit_wrapped"
_PEND = "_audit_pending"
_PAGE = "_audit_page"
# Passphrase boxes: typing in them is not an "action" worth a line.
_SKIP_KEYS = frozenset({"au_p1", "au_p2", "au_p3", "au_c1", "au_c2"})

_CLICKS = ("button", "form_submit_button", "download_button")
_MESSAGES = (("success", "OK"), ("error", "FAILED"), ("warning", "WARN"),
             ("info", "INFO"), ("exception", "ERROR"), ("stop", "STOPPED"))


def _path() -> str:
    try:
        import auth
        p = auth.user_file("mail_results/action_log.jsonl")
    except Exception:
        return ""
    try:
        os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
    except Exception:
        pass
    return p


def _append(rec: dict) -> None:
    p = _path()
    if not p:
        return
    try:
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        return
    _trim(p)


def _trim(p: str) -> None:
    try:
        with open(p, encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
        if len(lines) <= MAX_LINES:
            return
        with open(p, "w", encoding="utf-8") as f:
            f.writelines(lines[-MAX_LINES:])
    except Exception:
        pass


def _stamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def entries(limit: int = 300) -> list:
    """Newest-first records. Never raises."""
    p = _path()
    if not p or not os.path.exists(p):
        return []
    out = []
    try:
        with open(p, encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                if isinstance(rec, dict):
                    out.append(rec)
    except Exception:
        return []
    return out[-limit:][::-1]


def reset() -> int:
    """Delete this user's ledger. Returns the number of lines removed."""
    p = _path()
    n = len(entries(limit=MAX_LINES))
    try:
        if p and os.path.exists(p):
            os.remove(p)
    except Exception:
        pass
    return n


def note(action: str, outcome: str, detail: str = "", page: str = "") -> None:
    """Record an action that is not a widget press (page loads, watchdogs)."""
    _append({"ts": _stamp(), "page": page or "?", "widget": "note",
             "label": str(action)[:120], "key": "",
             "outcome": outcome, "detail": str(detail)[:300]})


def _close(st, outcome: str, detail: str = "") -> None:
    """Attach the first reported outcome to the open entry, then close it."""
    try:
        p = st.session_state.get(_PEND)
    except Exception:
        return
    if not p or p.get("outcome"):
        return
    p["outcome"] = outcome
    p["detail"] = str(detail or "")[:300]
    try:
        st.session_state[_PEND] = p
    except Exception:
        pass
    _append({"ts": _stamp(), "page": p.get("page", "?"), "widget": p.get("widget", ""),
             "label": p.get("label", ""), "key": p.get("key", ""),
             "outcome": outcome, "detail": p.get("detail", "")})


def _record(st, widget: str, label: str, key) -> None:
    key = str(key or "")
    if key in _SKIP_KEYS:
        return
    try:
        page = st.session_state.get(_PAGE, "?")
    except Exception:
        page = "?"
    try:
        st.session_state[_PEND] = {"page": page, "widget": widget,
                                   "label": str(label or "")[:120], "key": key[:60],
                                   "outcome": "", "detail": "", "age": 0}
    except Exception:
        pass


def _close_stale(st) -> None:
    """Close an entry the previous run left open, or give it one more run."""
    try:
        p = st.session_state.get(_PEND)
    except Exception:
        return
    if not p:
        return
    if p.get("outcome"):
        try:
            st.session_state.pop(_PEND, None)
        except Exception:
            pass
        return
    if int(p.get("age", 0)) >= 1:
        _append({"ts": _stamp(), "page": p.get("page", "?"), "widget": p.get("widget", ""),
                 "label": p.get("label", ""), "key": p.get("key", ""),
                 "outcome": "NO RESULT", "detail": "action finished without reporting"})
        try:
            st.session_state.pop(_PEND, None)
        except Exception:
            pass
    else:
        p["age"] = int(p.get("age", 0)) + 1
        try:
            st.session_state[_PEND] = p
        except Exception:
            pass


def _wrap_clicks(st) -> None:
    for name in _CLICKS:
        fn = getattr(st, name, None)
        if fn is None or getattr(fn, _ATTR, False):
            continue

        def wrapper(*a, _fn=fn, _name=name, **k):
            res = _fn(*a, **k)
            try:
                if res:
                    label = k.get("label") or (a[0] if a else "") or k.get("key") or _name
                    _record(st, _name, label, k.get("key"))
            except Exception:
                pass
            return res

        setattr(wrapper, _ATTR, True)
        try:
            setattr(st, name, wrapper)
        except Exception:
            pass


def _wrap_messages(st) -> None:
    for name, outcome in _MESSAGES:
        fn = getattr(st, name, None)
        if fn is None or getattr(fn, _ATTR, False):
            continue

        def wrapper(*a, _fn=fn, _outcome=outcome, **k):
            try:
                _close(st, _outcome, a[0] if a else k.get("body", ""))
            except Exception:
                pass
            return _fn(*a, **k)

        setattr(wrapper, _ATTR, True)
        try:
            setattr(st, name, wrapper)
        except Exception:
            pass

    # A rerun keeps the entry OPEN for one more run (the flash it triggers is
    # rendered there).  Only st.stop closes immediately.
    fn = getattr(st, "rerun", None)
    if fn is not None and not getattr(fn, _ATTR, False):

        def wrapper(*a, _fn=fn, **k):
            try:
                p = st.session_state.get(_PEND)
                if p and not p.get("outcome"):
                    p["age"] = max(1, int(p.get("age", 0)))
                    st.session_state[_PEND] = p
            except Exception:
                pass
            return _fn(*a, **k)

        setattr(wrapper, _ATTR, True)
        try:
            st.rerun = wrapper
        except Exception:
            pass


def install(st, page: str) -> None:
    """Call once per page, right after auth.require(). Never raises."""
    try:
        try:
            st.session_state[_PAGE] = page
        except Exception:
            pass
        _close_stale(st)
        if not getattr(st, _ATTR, False):
            _wrap_clicks(st)
            _wrap_messages(st)
            try:
                setattr(st, _ATTR, True)
            except Exception:
                pass
    except Exception:
        pass


def selftest() -> int:
    import shutil
    import tempfile

    d = tempfile.mkdtemp(prefix="audit_")
    os.environ["BB_RUN_DIR"] = d
    bad = []

    class _A:
        @staticmethod
        def user_file(name):
            return os.path.join(d, name.replace("/", "_"))

    import sys
    sys.modules["auth"] = _A

    def check(name, cond):
        print("%s %s" % ("OK  " if cond else "FAIL", name))
        if not cond:
            bad.append(name)

    try:
        check("empty at start", entries() == [])
        note("unit action", "OK", "fine")
        check("note is stored", len(entries()) == 1)
        check("newest first", entries()[0]["label"] == "unit action")
        for i in range(MAX_LINES + 25):
            note("bulk %d" % i, "OK")
        check("capped at MAX_LINES", len(entries(limit=MAX_LINES + 50)) == MAX_LINES)
        check("trim keeps the newest", entries()[0]["label"] == "bulk %d" % (MAX_LINES + 24))
        removed = reset()
        check("reset empties the file", entries() == [] and removed > 0)
    finally:
        shutil.rmtree(d, ignore_errors=True)
        os.environ.pop("BB_RUN_DIR", None)
        sys.modules.pop("auth", None)

    print("SELFTEST: %s (%d failure(s))" % ("OK" if not bad else "FAILED", len(bad)))
    return 1 if bad else 0


if __name__ == "__main__":
    import sys
    if "--selftest" in sys.argv:
        raise SystemExit(selftest())
    print("usage: python3 audit_log.py --selftest")
