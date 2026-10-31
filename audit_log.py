"""audit_log.py - per-user action & outcome ledger  (v13.50)

Records every press AND every state change with the page it came from, and
records what the run then reports: OK / FAILED / WARN / ERROR / STOPPED. A press
that reports nothing closes as NO RESULT; a state change is written as CHANGED
with the old -> new value the moment it happens.

Plain module, NOT frame-gated - like runstate.py.  Nothing here renders.

INSTALL ORDER IS THE WHOLE POINT
--------------------------------
install() must run BEFORE the first widget of the page. A widget created by the
unwrapped function is invisible to this module, so a hook placed after the
sidebar records the sidebar's buttons and nothing else. Every page calls
page() + install() in its auth block, ahead of its own widgets.

WHY THE COMPARE BASE IS A MEMO AND NOT session_state  (v13.49)
--------------------------------------------------------------
v13.48 read the old value out of st.session_state BEFORE the widget call and
compared it to the value AFTER. In real Streamlit the client's widget update is
already committed to session_state before the script body runs, so `before` was
already the NEW value, `after` equalled it, and the comparison was always false:
no slider, toggle, checkbox, selectbox or multiselect change was ever recorded.
The selftest missed it because its fake widget wrote session_state itself, which
is the opposite of the real timing. The ledger proved it: on a page where a
button logged three lines, the two sliders next to it logged none.

The baseline is now _SEEN - a per-session memo written AFTER each widget call,
so it always holds the PREVIOUS run's value regardless of when Streamlit commits
state. A run of edits on one widget inside 1.5s rewrites the same ledger line
instead of appending one per keystroke.

WHAT IS AND IS NOT VISIBLE
--------------------------
st.expander / st.tabs / st.popover are drawn by the browser. Opening one does
not contact the server, so no server-side hook can see it. Everything whose
change forces a rerun IS captured: button, form_submit_button, download_button,
toggle, checkbox, slider, selectbox, multiselect, radio, number_input,
color_picker, file_uploader, text_input, text_area, date_input. Page visits are
written by page() itself, as a PAGE record.

WHY A RERUN IS NOT AN OUTCOME
-----------------------------
Most presses here end in flash(...) + st.rerun(), and the flash is rendered on
the NEXT run. st.rerun keeps the entry OPEN for one more run so that message can
be attributed to it. A press still open after that closes as NO RESULT. State
changes are not deferred at all - they have no flash to wait for.

FIX AU-2 (v13.50) - THE DEFER WAS OFF BY ONE AND NOTHING EVER CLOSED AS OK
-------------------------------------------------------------------------
The rerun wrapper used to stamp p["age"] = max(1, ...) while _close_stale()
closed at age >= 1. install() runs BEFORE the page body, so the entry was popped
as NO RESULT by install() on the very next load - before the flash could render -
and the flash then had nothing left to attach to. The whole ledger read NO RESULT
and never OK. The wrapper now stamps 0, so that load increments to 1 and KEEPS
the entry: the flash on the same load closes it as OK, and the load after closes
it as NO RESULT if no flash ever arrived. Two selftest cases now cover it.

st.info does NOT close an entry: it is page-render chrome ("Loaded Proxies..."),
not a response, and it was claiming unrelated clicks. Only success / error /
warning / exception / stop close one.

ISOLATION
---------
The file resolves through auth.user_file(), so it is <hash>_mail_results/
action_log.jsonl - one ledger per user, never shared. Capped at MAX_LINES.

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
_SEEN = "_audit_seen"
_USED = "_audit_used"
_LAST = "_audit_last"
_MISSING = object()
# A burst of edits on one widget inside this window is one ledger line.
BURST_SECONDS = 1.5

# Passphrase boxes: the value is masked, so the detail would be useless.
_SKIP_KEYS = frozenset({"au_p1", "au_p2", "au_p3", "au_c1", "au_c2", "au_lbl"})

_CLICK_WIDGETS = ("button", "form_submit_button", "download_button")
_STATE_WIDGETS = ("toggle", "checkbox", "slider", "selectbox", "multiselect",
                  "radio", "number_input", "color_picker", "file_uploader",
                  "text_input", "text_area", "date_input")
# st.info is deliberately absent - see the docstring.
_MESSAGES = (("success", "OK"), ("error", "FAILED"), ("warning", "WARN"),
             ("exception", "ERROR"), ("stop", "STOPPED"))


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


def _rewrite_last(rec: dict) -> None:
    """Replace the final line - used to fold a burst of edits into one record."""
    p = _path()
    if not p:
        return
    try:
        with open(p, encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
        if not lines:
            _append(rec)
            return
        lines[-1] = json.dumps(rec, ensure_ascii=False) + "\n"
        with open(p, "w", encoding="utf-8") as f:
            f.writelines(lines)
    except Exception:
        _append(rec)


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


def _short(value, limit: int = 90) -> str:
    try:
        text = getattr(value, "name", value)
        return str(text)[:limit]
    except Exception:
        return ""


def page(name: str) -> None:
    """Tag the page BEFORE auth.require, and log the visit when it changes.

    Every rerun re-enters page(), so only a genuine navigation writes a line.
    """
    try:
        import streamlit as st
        ss = st.session_state
        prev = ss.get(_PAGE)
        ss[_PAGE] = name
        if prev == name:
            return
        try:
            ss.setdefault(_SEEN, {}).clear()
        except Exception:
            pass
        ss[_LAST] = None
        _append({"ts": _stamp(), "page": name, "widget": "page", "label": name,
                 "key": "", "outcome": "PAGE", "detail": ""})
    except Exception:
        pass


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


def note(action: str, outcome: str, detail: str = "", page_: str = "") -> None:
    """Record something that is not a widget (page load, watchdog, engine)."""
    _append({"ts": _stamp(), "page": page_ or "?", "widget": "note",
             "label": str(action)[:120], "key": "",
             "outcome": outcome, "detail": str(detail)[:300]})


def _emit(p: dict, outcome: str, detail: str = "") -> None:
    _append({"ts": _stamp(), "page": p.get("page", "?"), "widget": p.get("widget", ""),
             "label": p.get("label", ""), "key": p.get("key", ""),
             "outcome": outcome, "detail": detail or p.get("detail", "")})


def _close(st, outcome: str, detail: str = "") -> None:
    """Attach the first reported outcome to the open press, then close it."""
    try:
        p = st.session_state.get(_PEND)
    except Exception:
        return
    if not p or p.get("outcome"):
        return
    p["outcome"] = outcome
    try:
        st.session_state[_PEND] = p
    except Exception:
        pass
    _emit(p, outcome, str(detail or "")[:300])


def _record_click(st, widget: str, label: str, key: str) -> None:
    if key in _SKIP_KEYS:
        return
    try:
        st.session_state[_PEND] = {"page": st.session_state.get(_PAGE, "?"),
                                   "widget": widget, "kind": "click",
                                   "label": str(label or "")[:120], "key": key[:80],
                                   "outcome": "", "detail": "", "age": 0}
    except Exception:
        pass


def _record_state(st, widget: str, label: str, key: str, old: str, new: str) -> None:
    """Write a state change NOW. Folds a burst on the same widget into one line."""
    if key in _SKIP_KEYS:
        return
    try:
        ss = st.session_state
        now = time.time()
        last = ss.get(_LAST) or {}
        burst = (last.get("key") == key
                 and (now - float(last.get("ts", 0.0))) < BURST_SECONDS)
        first = last.get("old", old) if burst else old
        rec = {"ts": _stamp(), "page": ss.get(_PAGE, "?"), "widget": widget,
               "label": str(label or "")[:120], "key": key[:80],
               "outcome": "CHANGED", "detail": "%s -> %s" % (first, new)}
        if burst:
            _rewrite_last(rec)
        else:
            _append(rec)
        ss[_LAST] = {"key": key, "ts": now, "old": first}
    except Exception:
        pass


def _close_stale(st) -> None:
    """Close a press the previous run left open, or give it one more run.

    The threshold is >= 1 and the rerun wrapper stamps 0, so a press that asked
    for a rerun gets exactly one load in which its flash can render. FIX AU-2.
    """
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
        _emit(p, "NO RESULT", p.get("detail", "") or "finished without reporting")
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


def _synth_key(st, page_: str, label: str) -> str:
    """Stable stand-in key for a widget declared without key=."""
    base = "@%s|%s" % (page_, label)
    try:
        used = st.session_state.setdefault(_USED, {})
        n = int(used.get(base, 0))
        used[base] = n + 1
    except Exception:
        return base
    return base if n == 0 else "%s#%d" % (base, n)


def _wrap_one(st, name: str, kind: str) -> None:
    fn = getattr(st, name, None)
    if fn is None or getattr(fn, _ATTR, False):
        return

    def wrapper(*a, _fn=fn, _name=name, _kind=kind, **k):
        real_key = k.get("key")
        seen = {}
        before = _MISSING
        try:
            page_ = st.session_state.get(_PAGE, "?")
            label = k.get("label") or (a[0] if a else "") or real_key or _name
            if real_key:
                key = str(real_key)
            else:
                key = _synth_key(st, page_, str(label)[:60])
            seen = st.session_state.setdefault(_SEEN, {})
            before = seen.get(key, _MISSING)
        except Exception:
            key, label = "", name

        res = _fn(*a, **k)

        try:
            if _kind == "click":
                if res:
                    _record_click(st, _name, str(label), key)
            else:
                # The memo - NOT session_state - is the baseline: Streamlit has
                # already committed the client's new value to session_state by the
                # time the script body runs, so comparing against it compares a
                # value to itself and never fires.
                if before is not _MISSING and before != res:
                    _record_state(st, _name, str(label), key,
                                  _short(before), _short(res))
                seen[key] = res
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

    fn = getattr(st, "rerun", None)
    if fn is not None and not getattr(fn, _ATTR, False):

        def wrapper(*a, _fn=fn, **k):
            try:
                p = st.session_state.get(_PEND)
                if p and not p.get("outcome"):
                    # FIX AU-2: 0, not max(1, ...). install() runs BEFORE the page
                    # body, so stamping 1 let _close_stale() pop the entry as
                    # NO RESULT on the very next load - before the flash could
                    # render - and nothing ever closed as OK. 0 makes that load
                    # increment to 1 and keep it: the flash closes it as OK on the
                    # same load, and only the load AFTER falls back to NO RESULT.
                    p["age"] = 0
                    st.session_state[_PEND] = p
            except Exception:
                pass
            return _fn(*a, **k)

        setattr(wrapper, _ATTR, True)
        try:
            st.rerun = wrapper
        except Exception:
            pass


def install(st, page_: str) -> None:
    """Call once per page, in the auth block, BEFORE the first widget."""
    try:
        try:
            st.session_state[_PAGE] = page_
            st.session_state[_USED] = {}
        except Exception:
            pass
        _close_stale(st)
        if not getattr(st, _ATTR, False):
            for _n in _CLICK_WIDGETS:
                _wrap_one(st, _n, "click")
            for _n in _STATE_WIDGETS:
                _wrap_one(st, _n, "state")
            _wrap_messages(st)
            try:
                setattr(st, _ATTR, True)
            except Exception:
                pass
    except Exception:
        pass


def selftest() -> int:
    import shutil
    import sys
    import tempfile
    import types

    d = tempfile.mkdtemp(prefix="audit_")
    os.environ["BB_RUN_DIR"] = d
    bad = []

    class _A:
        @staticmethod
        def user_file(name):
            return os.path.join(d, name.replace("/", "_"))

    sys.modules["auth"] = _A

    class _St:
        """Models REAL Streamlit: the client's widget value is already in
        session_state before the script body runs."""

        def __init__(self):
            self.session_state = {}

        def button(self, label, key=None):
            return True

        def slider(self, label, lo, hi, key=None):
            return self.session_state.get(key)

        def success(self, msg):
            return None

        def info(self, msg):
            return None

        def rerun(self):
            return None

    def check(name, cond):
        print("%s %s" % ("OK  " if cond else "FAIL", name))
        if not cond:
            bad.append(name)

    def drag(value, key="vol"):
        st.session_state[key] = value          # the client already committed it
        st.slider("Volume", 0, 10, key=key)    # the widget just returns it

    st = _St()
    # page() imports streamlit itself - give it the SAME session_state dict.
    saved_st = sys.modules.get("streamlit")
    stub = types.ModuleType("streamlit")
    stub.session_state = st.session_state
    sys.modules["streamlit"] = stub

    try:
        check("empty at start", entries() == [])
        note("unit action", "OK", "fine")
        check("note is stored", len(entries()) == 1)

        install(st, "p.py")
        st.button("Press me")
        st.success("did it")
        check("a press is recorded", any(e["label"] == "Press me" for e in entries()))
        check("its outcome is attached",
              any(e["label"] == "Press me" and e["outcome"] == "OK" for e in entries()))

        install(st, "p.py")
        drag(3)
        check("the baseline render is not a change",
              not any(e["label"] == "Volume" for e in entries()))

        # a real move: session_state ALREADY holds 7 when the run starts
        install(st, "p.py")
        drag(7)
        check("a slider move is recorded (the v13.48 regression)",
              any(e["label"] == "Volume" for e in entries()))
        check("old and new are kept",
              any("3 -> 7" in (e.get("detail") or "") for e in entries()))
        check("a state change closes as CHANGED",
              any(e["label"] == "Volume" and e["outcome"] == "CHANGED"
                  for e in entries()))

        _n = len(entries())
        install(st, "p.py")
        drag(8)
        check("a burst does not add a second line", len(entries()) == _n)
        check("the burst line still starts at the original value",
              any("3 -> 8" in (e.get("detail") or "") for e in entries()))

        _n = len(entries())
        install(st, "p.py")
        drag(8)
        check("an unchanged render is not a change", len(entries()) == _n)

        st.info("chrome")
        check("st.info does not close an entry",
              not any(e.get("outcome") == "INFO" for e in entries()))

        st.button("Silent press")
        install(st, "p.py")
        install(st, "p.py")
        check("a silent press closes as NO RESULT",
              any(e["label"] == "Silent press" and e["outcome"] == "NO RESULT"
                  for e in entries()))

        # FIX AU-2 regression pair. The press asks for a rerun, the rerun is what
        # carries the flash, and the flash is rendered by the load AFTER it.
        st.button("Rerun press")
        st.rerun()
        install(st, "p.py")
        check("a rerun keeps the entry open for its flash",
              not any(e["label"] == "Rerun press" and e["outcome"] == "NO RESULT"
                      for e in entries()))
        st.success("flashed")
        check("the flash closes it as OK",
              any(e["label"] == "Rerun press" and e["outcome"] == "OK"
                  for e in entries()))

        st.button("Rerun with no flash")
        st.rerun()
        install(st, "p.py")
        install(st, "p.py")
        check("a rerun with no flash still ends as NO RESULT",
              any(e["label"] == "Rerun with no flash" and e["outcome"] == "NO RESULT"
                  for e in entries()))

        page("q.py")
        check("a page visit is recorded",
              any(e.get("outcome") == "PAGE" and e.get("page") == "q.py"
                  for e in entries()))
        _n = len(entries())
        page("q.py")
        check("a rerun on the same page is not a second visit", len(entries()) == _n)

        for i in range(MAX_LINES + 25):
            note("bulk %d" % i, "OK")
        check("capped at MAX_LINES", len(entries(limit=MAX_LINES + 50)) == MAX_LINES)
        check("reset empties the file", reset() > 0 and entries() == [])
    finally:
        sys.modules.pop("streamlit", None)
        if saved_st is not None:
            sys.modules["streamlit"] = saved_st
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
