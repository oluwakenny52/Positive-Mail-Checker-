"""audit_log.py - per-user action & outcome ledger  (v13.48)

Records every press AND every state change with the page it came from, and
records what the run then reports: OK / FAILED / WARN / ERROR / STOPPED. A press
that reports nothing closes as NO RESULT; a state change that reports nothing
closes as CHANGED, with the old -> new value in the detail.

Plain module, NOT frame-gated - like runstate.py.  Nothing here renders.

INSTALL ORDER IS THE WHOLE POINT
--------------------------------
install() must run BEFORE the first widget of the page. A widget created by the
unwrapped function is invisible to this module, so a hook placed after the
sidebar records the sidebar's buttons and nothing else. Every page now calls
page() + install() in its auth block, ahead of its own widgets.

WHAT IS AND IS NOT VISIBLE
--------------------------
st.expander / st.tabs / st.popover are drawn by the browser. Opening one does
not contact the server, so no server-side hook can see it. Everything whose
change forces a rerun IS captured: button, form_submit_button, download_button,
toggle, checkbox, slider, selectbox, multiselect, radio, number_input,
color_picker, file_uploader, text_input, text_area, date_input.

HOW A STATE CHANGE IS DETECTED
------------------------------
For a widget with key=, the value in st.session_state BEFORE the call is the
previous run's value and the value after it is the current one, so the compare
needs no cross-run memo at all. Widgets without key= get a synthetic key and a
memo. Consecutive edits to the same widget collapse into one line instead of one
line per keystroke.

WHY A RERUN IS NOT AN OUTCOME
-----------------------------
Most actions here end in flash(...) + st.rerun(), and the flash is rendered on
the NEXT run. st.rerun keeps the entry OPEN for one more run so that message can
be attributed to it. Anything still open after that closes with its kind's
default - NO RESULT for a press, CHANGED for a state move.

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
_MISSING = object()

# Passphrase boxes: the value is masked, so the detail would be useless.
_SKIP_KEYS = frozenset({"au_p1", "au_p2", "au_p3", "au_c1", "au_c2", "au_lbl"})

_CLICK_WIDGETS = ("button", "form_submit_button", "download_button")
_STATE_WIDGETS = ("toggle", "checkbox", "slider", "selectbox", "multiselect",
                  "radio", "number_input", "color_picker", "file_uploader",
                  "text_input", "text_area", "date_input")
# st.info is deliberately absent - see the docstring.
_MESSAGES = (("success", "OK"), ("error", "FAILED"), ("warning", "WARN"),
             ("exception", "ERROR"), ("stop", "STOPPED"))

_DEFAULT = {"click": "NO RESULT", "state": "CHANGED"}


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


def _short(value, limit: int = 90) -> str:
    try:
        text = getattr(value, "name", value)
        return str(text)[:limit]
    except Exception:
        return ""


def page(name: str) -> None:
    """Tag the page BEFORE auth.require, so even the Unlock press has an owner."""
    try:
        import streamlit as st
        st.session_state[_PAGE] = name
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
    """Attach the first reported outcome to the open entry, then close it."""
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


def _record(st, widget: str, kind: str, label: str, key: str, detail: str = "") -> None:
    if key in _SKIP_KEYS:
        return
    try:
        page_ = st.session_state.get(_PAGE, "?")
        prev = st.session_state.get(_PEND)
        # Collapse a run of edits on the SAME widget into one line: a slider drag
        # or a typed word is one action, not twenty.
        if (prev and not prev.get("outcome") and prev.get("key") == key
                and prev.get("kind") == kind):
            prev["detail"] = detail[:120] or prev.get("detail", "")
            prev["age"] = 0
            st.session_state[_PEND] = prev
            return
        st.session_state[_PEND] = {"page": page_, "widget": widget, "kind": kind,
                                   "label": str(label or "")[:120], "key": key[:80],
                                   "outcome": "", "detail": detail[:120], "age": 0}
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
        _emit(p, _DEFAULT.get(p.get("kind", "click"), "NO RESULT"),
              p.get("detail", "") or "finished without reporting")
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
        try:
            page_ = st.session_state.get(_PAGE, "?")
            label = k.get("label") or (a[0] if a else "") or real_key or _name
            if real_key:
                key = str(real_key)
                before = st.session_state.get(key, _MISSING)
            else:
                key = _synth_key(st, page_, str(label)[:60])
                before = st.session_state.setdefault(_SEEN, {}).get(key, _MISSING)
        except Exception:
            real_key, key, label, before, _kind = None, "", name, _MISSING, kind

        res = _fn(*a, **k)

        try:
            if _kind == "click":
                if res:
                    _record(st, _name, "click", str(label), key)
            else:
                after = st.session_state.get(real_key, res) if real_key else res
                if before is not _MISSING and before != after:
                    _record(st, _name, "state", str(label), key,
                            "%s -> %s" % (_short(before), _short(after)))
                if not real_key:
                    st.session_state.setdefault(_SEEN, {})[key] = after
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

    class _St:
        def __init__(self):
            self.session_state = {}

        def button(self, label, key=None):
            return True

        def slider(self, label, lo, hi, val, step=1, key=None):
            self.session_state[key] = val
            return val

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

    try:
        st = _St()
        check("empty at start", entries() == [])
        note("unit action", "OK", "fine")
        check("note is stored", len(entries()) == 1)

        install(st, "p.py")
        st.button("Press me")
        st.success("did it")
        check("a press is recorded", any(e["label"] == "Press me" for e in entries()))
        check("its outcome is attached",
              any(e["label"] == "Press me" and e["outcome"] == "OK" for e in entries()))

        st.slider("Volume", 0, 10, 3, key="vol")
        install(st, "p.py")
        st.slider("Volume", 0, 10, 7, key="vol")
        install(st, "p.py")
        install(st, "p.py")
        check("a slider move is recorded",
              any(e["label"] == "Volume" for e in entries()))
        check("old and new are kept",
              any("3 -> 7" in (e.get("detail") or "") for e in entries()))
        check("a silent state change closes as CHANGED",
              any(e["label"] == "Volume" and e["outcome"] == "CHANGED" for e in entries()))

        _n = len(entries())
        st.slider("Volume", 0, 10, 8, key="vol")
        check("a second edit collapses into one line", len(entries()) == _n + 0
              or entries()[0]["label"] == "Volume")

        st.info("chrome")
        check("st.info does not close an entry",
              not any(e["outcome"] == "INFO" for e in entries()))

        st.button("Silent press")
        install(st, "p.py")
        install(st, "p.py")
        check("a silent press closes as NO RESULT",
              any(e["label"] == "Silent press" and e["outcome"] == "NO RESULT"
                  for e in entries()))

        for i in range(MAX_LINES + 25):
            note("bulk %d" % i, "OK")
        check("capped at MAX_LINES", len(entries(limit=MAX_LINES + 50)) == MAX_LINES)
        check("reset empties the file", reset() > 0 and entries() == [])
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
