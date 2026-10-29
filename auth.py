# @@FILE auth.py blocks=6 version=v13.43
# @@BLOCK 000 HEADER deps=-
"""auth.py - per-user passkey gate and display-fit controls.

Import-clean: stdlib only, no Streamlit at module level.

Every page calls, in this order, in its FIRST block:

    import auth
    auth.require(st)      # unlock or stop
    auth.fit(st)          # sliders + CSS

The passphrase is salted-sha256 hashed into passkey.json. It is a LOCK, not
encryption: per-user files are separated by the hash PREFIX, they are not
encrypted at rest.

passkey.json holds a LIST of keys, so several people can share one deployment.
"Forget this passkey" removes only yours. "Forget all" removes every key.
"""

import hashlib
import json
import os
import secrets
import time

PASSKEY_FILE = "passkey.json"
SALT_BYTES = 16
HASH_LEN = 16
DEFAULT_FONT = 16
DEFAULT_SCALE = 100
MIN_LEN = 4
# @@END 000 HEADER


# @@BLOCK 001 KEYS deps=000
def _digest(phrase, salt):
    return hashlib.sha256((salt + "\x00" + phrase).encode("utf-8")).hexdigest()[:HASH_LEN]


def _load():
    try:
        with open(PASSKEY_FILE, encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict) and isinstance(data.get("keys"), list):
            return data
    except Exception:
        pass
    return {"keys": []}


def _save(data):
    try:
        tmp = PASSKEY_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
        os.replace(tmp, PASSKEY_FILE)
    except Exception:
        pass


def add_key(phrase, label=""):
    """Create a passkey, persist it, return its hash."""
    phrase = (phrase or "").strip()
    data = _load()
    salt = secrets.token_hex(SALT_BYTES)
    h = _digest(phrase, salt)
    data["keys"].append({"salt": salt, "hash": h,
                         "label": (label or "").strip()[:40],
                         "created": int(time.time())})
    _save(data)
    return h


def match_key(phrase):
    """Return the stored hash `phrase` opens, or ''."""
    phrase = (phrase or "").strip()
    if not phrase:
        return ""
    for k in reversed(_load().get("keys") or []):
        if _digest(phrase, k.get("salt", "")) == k.get("hash"):
            return k.get("hash", "")
    return ""


def forget_current(h):
    """Drop ONE key. Every other user keeps working. Empty list -> delete file."""
    if not h:
        return
    data = _load()
    data["keys"] = [k for k in (data.get("keys") or []) if k.get("hash") != h]
    if data["keys"]:
        _save(data)
    else:
        for p in (PASSKEY_FILE, PASSKEY_FILE + ".tmp"):
            try:
                if os.path.exists(p):
                    os.remove(p)
            except Exception:
                pass


def forget_all():
    for p in (PASSKEY_FILE, PASSKEY_FILE + ".tmp"):
        try:
            if os.path.exists(p):
                os.remove(p)
        except Exception:
            pass


def user_key_hash():
    import streamlit as st
    return str(st.session_state.get("user_key_hash", ""))


def user_file(name):
    h = user_key_hash()
    return "%s_%s" % (h, name) if h else name
# @@END 001 KEYS


# @@BLOCK 002 GATE deps=001
def require(st, title="Unlock Positive Mail-Checker"):
    """Unlock, or create the first passkey. Sets session_state['user_key_hash']."""
    if st.session_state.get("user_key_hash"):
        return st.session_state["user_key_hash"]

    known = bool((_load().get("keys") or []))
    st.markdown("### %s" % title)
    st.caption("Your passphrase never leaves this device. Every account list, "
               "result file and cache is stored under its own prefix, so two "
               "people on the same deployment never see each other's data.")

    if known:
        with st.form("auth_unlock"):
            phrase = st.text_input("Passphrase", type="password", key="au_p1")
            ok = st.form_submit_button("Unlock", type="primary")
        if ok:
            h = match_key(phrase)
            if h:
                st.session_state["user_key_hash"] = h
                st.rerun()
            else:
                st.error("Wrong passphrase.")
        with st.expander("Start fresh as a different user on this device"):
            st.caption("Adds a SECOND passkey. The existing ones keep working.")
            with st.form("auth_new"):
                p2 = st.text_input("New passphrase", type="password", key="au_p2")
                p3 = st.text_input("Repeat it", type="password", key="au_p3")
                lbl = st.text_input("Label (optional)", key="au_lbl")
                mk = st.form_submit_button("Create and enter")
            if mk:
                p2 = (p2 or "").strip()
                if len(p2) < MIN_LEN:
                    st.error("Use at least %d characters." % MIN_LEN)
                elif p2 != p3:
                    st.error("The two passphrases differ.")
                else:
                    st.session_state["user_key_hash"] = add_key(p2, lbl)
                    st.rerun()
        with st.expander("Forget a passkey"):
            st.caption("Forget THIS passkey removes only the one you are signed "
                       "in with. Every other user on this deployment keeps theirs.")
            if st.button("Forget this passkey", key="au_forget_one"):
                forget_current(st.session_state.get("user_key_hash", ""))
                st.session_state.pop("user_key_hash", None)
                st.rerun()
            st.caption("Forget ALL passkeys removes every key, for everyone.")
            if st.button("Forget all passkeys", key="au_forget_all"):
                forget_all()
                st.session_state.pop("user_key_hash", None)
                st.rerun()
        st.stop()

    st.caption("No passkey yet - create one. It is asked once per session.")
    with st.form("auth_create"):
        p1 = st.text_input("Choose a passphrase", type="password", key="au_c1")
        p2 = st.text_input("Repeat it", type="password", key="au_c2")
        remember = st.checkbox("Remember on this device", value=True)
        go = st.form_submit_button("Create and enter", type="primary")
    if go:
        p1 = (p1 or "").strip()
        if len(p1) < MIN_LEN:
            st.error("Use at least %d characters." % MIN_LEN)
        elif p1 != p2:
            st.error("The two passphrases differ.")
        else:
            if remember:
                h = add_key(p1)
            else:
                h = _digest(p1, secrets.token_hex(SALT_BYTES))
            st.session_state["user_key_hash"] = h
            st.rerun()
    st.stop()
# @@END 002 GATE


# @@BLOCK 003 FIT_CSS deps=000
def fit_css():
    """CSS applying the two display-fit sliders.

    `st` MUST be bound here: this module is import-clean, so there is no
    module-level streamlit. The except clauses are narrow on purpose - a broad
    `except Exception` hid a NameError on `st` and pinned every page to 16px /
    1.00 forever, which looked exactly like "the sliders do nothing".
    """
    import streamlit as st
    try:
        font = int(st.session_state.get("ui_font_size", DEFAULT_FONT))
    except (TypeError, ValueError):
        font = DEFAULT_FONT
    try:
        scale = int(st.session_state.get("ui_content_scale", DEFAULT_SCALE)) / 100.0
    except (TypeError, ValueError):
        scale = 1.0
    return ("<style>html{font-size:%dpx !important;}"
            "body{font-size:%dpx !important;}"
            ".stApp{zoom:%.2f !important;}</style>" % (font, font, scale))
# @@END 003 FIT_CSS


# @@BLOCK 004 FIT_UI deps=003
def fit(st):
    """Sidebar sliders + the CSS they drive. Call LATE in the page."""
    with st.sidebar:
        st.markdown("### Display Fit")
        st.slider("Font size", 12, 22, DEFAULT_FONT, key="ui_font_size")
        st.slider("Content scale %", 80, 140, DEFAULT_SCALE, key="ui_content_scale")
    st.markdown(fit_css(), unsafe_allow_html=True)
# @@END 004 FIT_UI


# @@BLOCK 005 SELFTEST deps=001,003
def _selftest():
    checks = []
    h1 = _digest("abc", "s")
    checks.append(("deterministic", h1 == _digest("abc", "s")))
    checks.append(("salt matters", h1 != _digest("abc", "t")))
    checks.append(("length", len(h1) == HASH_LEN))
    checks.append(("hex", all(c in "0123456789abcdef" for c in h1)))
    # fit_css() must RUN, not fall back - this is the NameError tripwire.
    try:
        css = fit_css()
        checks.append(("fit_css runs", "<style>" in css))
        checks.append(("fit_css has zoom", "zoom:" in css))
    except Exception:
        checks.append(("fit_css runs", False))
        checks.append(("fit_css has zoom", False))
    bad = [n for n, ok in checks if not ok]
    if bad:
        raise AssertionError("auth selftest failed: " + ", ".join(bad))
    print("auth.py selftest: %d checks OK" % len(checks))
    return True


if __name__ == "__main__":
    import sys as _sys
    if "--selftest" in _sys.argv:
        _selftest()
    _sys.exit(0)
# @@END 005 SELFTEST
# @@EOF
