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
# Hex chars kept from the sha256 = 64 bits. Do NOT raise this casually:
# match_key re-derives with the CURRENT value, so every stored hash orphans.
HASH_LEN = 16
DEFAULT_FONT = 16
DEFAULT_SCALE = 100
MIN_LEN = 8
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
        if secrets.compare_digest(_digest(phrase, k.get("salt", "")), k.get("hash", "")):
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
            # Locked, so there is no session hash to "forget this one" with -
            # pick the key explicitly instead of reading user_key_hash (which is
            # always "" on this branch, making the old button a permanent no-op).
            pick = {}
            for k in (_load().get("keys") or []):
                lab = (k.get("label") or "").strip() or "unlabelled"
                pick["%s · %s" % (lab, str(k.get("hash", ""))[:8])] = k.get("hash", "")
            st.caption("Removes ONE key. Every other user on this deployment keeps theirs.")
            choice = st.selectbox("Which passkey", list(pick))
            if st.button("Forget selected passkey", key="au_forget_one"):
                forget_current(pick.get(choice, ""))
                st.session_state.pop("user_key_hash", None)
                st.rerun()
            st.caption("Or remove every key, for everyone.")
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


# @@BLOCK 003 FIT_CSS deps=001
FIT_FONT_KEY = "ui_font_size"
FIT_SCALE_KEY = "ui_content_scale"
FIT_FONT_DEFAULT = 16
FIT_SCALE_DEFAULT = 1.00
FIT_FONT_MIN, FIT_FONT_MAX = 12, 24
FIT_SCALE_MIN, FIT_SCALE_MAX = 0.75, 1.60


def _fit_read(key, default, lo, hi, cast=float):
    """One Display Fit setting, clamped. NEVER raises.

    v13.44: this was a bare st.session_state read inside fit_css, so the call
    raised whenever it ran outside a Streamlit script run - which is exactly
    what the CI selftest does - and raised ImportError wherever streamlit is
    not installed. The narrow except did not cover either, so fit_css died
    before emitting a byte and the gate went red.
    """
    try:
        import streamlit as st
        raw = st.session_state.get(key, default)
    except Exception:
        return default
    try:
        val = cast(raw)
    except (TypeError, ValueError):
        return default
    if val != val:                       # NaN
        return default
    return max(lo, min(hi, val))


def fit_css(font=None, scale=None) -> str:
    """CSS for the Display Fit sliders. Always returns a str.

    font / scale are optional overrides, so the values can be exercised with no
    Streamlit at all. No argument = read the live settings. The fallback is a
    harmless 16px / 1.00.

    The slider that writes ui_content_scale must use FIT_SCALE_MIN..FIT_SCALE_MAX
    (a 0.75-1.60 FACTOR). It used to be 80-140 percent, and every value above
    1.60 clamped, pinning the zoom at maximum.
    """
    if font is None:
        size = int(_fit_read(FIT_FONT_KEY, FIT_FONT_DEFAULT, FIT_FONT_MIN, FIT_FONT_MAX, int))
    else:
        size = max(FIT_FONT_MIN, min(FIT_FONT_MAX, int(font)))
    if scale is None:
        zoom = float(_fit_read(FIT_SCALE_KEY, FIT_SCALE_DEFAULT, FIT_SCALE_MIN, FIT_SCALE_MAX, float))
    else:
        zoom = max(FIT_SCALE_MIN, min(FIT_SCALE_MAX, float(scale)))

    return (
        "<style>"
        f"html, body, .stApp, .stApp p, .stApp li, .stApp label, .stApp input, "
        f".stApp textarea, .stApp select {{ font-size: {size}px !important; }}"
        f".stApp {{ zoom: {zoom:.2f}; }}"
        ".block-container, [data-testid=\"stMainBlockContainer\"] { max-width: 100% !important; }"
        "</style>"
    )
# @@END 003 FIT_CSS


# @@BLOCK 004 FIT_UI deps=003
def fit(st) -> None:
    """Sidebar sliders + the CSS they drive. Call LATE in the page. Never raises.

    This is the ONLY definition of fit(). It used to be duplicated here and in
    003, so this copy shadowed the one that owned the reset handling.
    """
    try:
        if st.session_state.pop("_fit_reset", False):
            # Assigned BEFORE either widget exists. Assigning after them raises
            # StreamlitWidgetAlreadyInstantiatedError - the v13.35 reset lesson.
            st.session_state[FIT_FONT_KEY] = FIT_FONT_DEFAULT
            st.session_state[FIT_SCALE_KEY] = FIT_SCALE_DEFAULT

        if FIT_FONT_KEY not in st.session_state:
            st.session_state[FIT_FONT_KEY] = int(
                _fit_read(FIT_FONT_KEY, FIT_FONT_DEFAULT, FIT_FONT_MIN, FIT_FONT_MAX, int))
        if FIT_SCALE_KEY not in st.session_state:
            st.session_state[FIT_SCALE_KEY] = float(
                _fit_read(FIT_SCALE_KEY, FIT_SCALE_DEFAULT, FIT_SCALE_MIN, FIT_SCALE_MAX, float))

        with st.sidebar.expander("🔎 Display Fit", expanded=False):
            st.slider("Text size (px)", FIT_FONT_MIN, FIT_FONT_MAX, key=FIT_FONT_KEY)
            st.slider("Content scale", FIT_SCALE_MIN, FIT_SCALE_MAX, step=0.05,
                      format="%.2f", key=FIT_SCALE_KEY)
            if st.button("Reset Display Fit", key="fit_reset_btn", width="stretch"):
                st.session_state["_fit_reset"] = True
                st.rerun()
    except Exception:
        pass
    try:
        st.markdown(fit_css(), unsafe_allow_html=True)
    except Exception:
        pass
# @@END 004 FIT_UI


# @@BLOCK 005 SELFTEST deps=001,003
def _selftest() -> None:
    bad = []

    def check(name, fn):
        try:
            if fn() is False:
                bad.append(name)
        except Exception as exc:
            bad.append(f"{name} ({type(exc).__name__}: {exc})")

    # ---- Display Fit must work with no Streamlit and no script run ---------
    check("fit_css returns str", lambda: isinstance(fit_css(), str))
    check("fit_css has font-size", lambda: "font-size: 16px" in fit_css())
    check("fit_css has zoom", lambda: "zoom: 1.00" in fit_css())
    check("fit_css honours font override", lambda: "font-size: 20px" in fit_css(20, 1.25))
    check("fit_css honours scale override", lambda: "zoom: 1.25" in fit_css(20, 1.25))
    check("fit_css clamps high", lambda: "font-size: 24px" in fit_css(99, 9))
    check("fit_css clamps low", lambda: "font-size: 12px" in fit_css(1, 0))
    check("fit_css not empty", lambda: len(fit_css()) > 40)
    check("fit_css closes style", lambda: fit_css().rstrip().endswith("</style>"))
    check("_fit_read defaults headless",
          lambda: _fit_read("no_such_key", 7, 0, 10, int) == 7)

    # ---- the constants must stay inside the ranges fit_css clamps to -------
    check("scale constants are factors, not percents",
          lambda: FIT_SCALE_MIN < FIT_SCALE_DEFAULT <= FIT_SCALE_MAX <= 2.0)
    check("font constants are px, not percents",
          lambda: FIT_FONT_MIN <= FIT_FONT_DEFAULT <= FIT_FONT_MAX <= 40)

    # ---- passkey digest ----------------------------------------------------
    check("digest is stable", lambda: _digest("abc", "s") == _digest("abc", "s"))
    check("digest is salted", lambda: _digest("abc", "s") != _digest("abc", "t"))
    check("digest is hex of HASH_LEN",
          lambda: len(_digest("abc", "s")) == HASH_LEN
          and all(c in "0123456789abcdef" for c in _digest("abc", "s")))
    check("HASH_LEN is sane", lambda: 8 <= HASH_LEN <= 64)

    if bad:
        raise AssertionError("auth selftest failed: " + ", ".join(bad))


if __name__ == "__main__":
    _selftest()
    print("auth selftest OK")
# @@END 005 SELFTEST
# @@EOF
