# @@FILE auth.py blocks=6 version=v13.47
# @@BLOCK 000 HEADER deps=-
"""auth.py - per-user passkey gate and display-fit controls.

Import-clean: stdlib only, no Streamlit at module level.

Every page calls, in this order:

    import auth
    auth.require(st)      # unlock or stop
    auth.fit(st)          # CSS ONLY - must be early, before the first widget

...and then, AFTER the page header:

    auth.fit_panel(st)    # the controls, where a display control belongs

fit() and fit_panel() are deliberately separate. The CSS has to land as early as
possible so the first paint is already scaled; the panel has to land after the
title or it pushes the header down. One function cannot do both.

v13.47: the deployed copy had drifted - the panel was back inside fit() and
fit_panel() did not exist at all, so every caller of fit_panel() died with
AttributeError and the Reset button still wrote the slider keys after the
sliders were built. fit() is CSS-only again and the reset travels through an
on_click handler, which Streamlit runs BEFORE the script body.

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


# @@BLOCK 003 FIT_CSS deps=002
FIT_FONT_DEFAULT = 16
FIT_SCALE_DEFAULT = 100
FIT_FONT_MIN, FIT_FONT_MAX = 12, 22
FIT_SCALE_MIN, FIT_SCALE_MAX = 80, 140
FIT_SCALE_FACTOR_BELOW = 3
FIT_FONT_PERCENT_ABOVE = 40
# A value at or above this is a percent where pixels were expected. It is not
# `percent_above` itself: 99px is an out-of-range PIXEL and must clamp to the
# maximum, while 100 is a PERCENT and must fall back to the default. Using
# percent_above as the threshold made 99 fall back and the clamp never ran.
FIT_PERCENT_THRESHOLD = 100


def _fit_from(value, default, lo, hi, cast, percent_above=None, factor_below=None):
    """Clamp one raw setting into [lo, hi] and cast it. Never raises.

    Order matters and is the whole point of this helper:

      1. unparseable -> `default`
      2. at or below `factor_below` -> a 0.8-1.6 factor, multiplied by 100
      3. at or above FIT_PERCENT_THRESHOLD -> a percent where pixels were
         expected, so `default`
      4. otherwise -> clamped into [lo, hi]

    Steps 3 and 4 are distinct. A value in (hi, 100) is an out-of-range pixel
    and clamps to hi; only a value that is genuinely a percent falls back.
    """
    try:
        n = float(value)
    except (TypeError, ValueError):
        return cast(default)
    if factor_below is not None and n <= factor_below:
        n *= 100.0
    if percent_above is not None:
        floor = max(float(FIT_PERCENT_THRESHOLD), float(percent_above) + 1.0)
        if n >= floor:
            n = float(default)
    return cast(max(lo, min(hi, round(n))))


def _fit_clamp_font(value):
    return _fit_from(value, FIT_FONT_DEFAULT, FIT_FONT_MIN, FIT_FONT_MAX,
                     int, FIT_FONT_PERCENT_ABOVE)


def _fit_clamp_scale(value):
    return _fit_from(value, FIT_SCALE_DEFAULT, FIT_SCALE_MIN, FIT_SCALE_MAX,
                     int, None, FIT_SCALE_FACTOR_BELOW)


def _fit_normalise(value):
    return _fit_clamp_scale(value)


def _fit_read(key, default, lo, hi, cast, percent_above=None, factor_below=None):
    """Clamped session value for `key`. Safe with no script run (headless)."""
    try:
        import streamlit as st
        raw = st.session_state.get(key, default)
    except Exception:
        raw = default
    return _fit_from(raw, default, lo, hi, cast, percent_above, factor_below)


def _fit_raw():
    import streamlit as st
    ss = st.session_state
    return ss.get("ui_font_size"), ss.get("ui_content_scale")


def _fit_values():
    font, scale = _fit_raw()
    f = _fit_clamp_font(font)
    s = _fit_clamp_scale(scale)
    return f, s, s / 100.0


def fit_css(font=None, scale=None):
    f = _fit_clamp_font(font)
    s = _fit_clamp_scale(scale)
    z = s / 100.0
    return (
        "<style>\n"
        "/* Display Fit. zoom sits on the main container only, never on stApp, */\n"
        "/* because stApp also holds the sidebar and would scale it twice.      */\n"
        '.block-container,\n[data-testid="stMainBlockContainer"] {\n'
        f"  zoom: {z:.4f} !important;\n"
        "  max-width: 100% !important;\n"
        "}\n"
        '[data-testid="stMarkdownContainer"] :is(p, li, td, th, h1, h2, h3, h4, h5, h6) {\n'
        f"  font-size: {f}px !important;\n"
        "}\n"
        '[data-testid="stMarkdownContainer"] [data-testid="stCaptionContainer"] p {\n'
        f"  font-size: {max(11, f - 3)}px !important;\n"
        "}\n"
        "</style>\n"
    )
# @@END 003 FIT_CSS


# @@BLOCK 004 FIT_UI deps=003
def _fit_seed():
    import streamlit as st
    ss = st.session_state
    if ss.get("_fit_seeded"):
        return
    if "ui_font_size" not in ss:
        ss["ui_font_size"] = FIT_FONT_DEFAULT
    if "ui_content_scale" not in ss:
        ss["ui_content_scale"] = FIT_SCALE_DEFAULT
    ss["_fit_seeded"] = True


def _fit_apply(html):
    import streamlit as st
    try:
        st.html(html)
        return "st.html"
    except Exception:
        pass
    try:
        st.markdown(html, unsafe_allow_html=True)
        return "st.markdown"
    except Exception:
        return "none"


def _on_reset_click():
    """on_click handler - runs BEFORE the script body, so raising the flag here
    is legal even though the sliders existed last run.

    The button used to write the two keys inside its own `if` branch, by which
    time the slider holding that key was already instantiated this run ->
    StreamlitWidgetAlreadyInstantiatedError, and st.rerun() was never reached.
    """
    import streamlit as st
    st.session_state["_fit_reset"] = True


def fit(scope=None):
    """Inject the Display Fit CSS. Call EARLY - before the first widget."""
    import streamlit as st
    ss = st.session_state
    if ss.pop("_fit_reset", False):
        ss["ui_font_size"] = FIT_FONT_DEFAULT
        ss["ui_content_scale"] = FIT_SCALE_DEFAULT
    _fit_seed()
    # Normalise BEFORE the widgets exist this run. An old factor (1.00) or an
    # old percent font (100) would otherwise sit outside the slider's range and
    # Streamlit would refuse to draw it.
    ss["ui_font_size"] = _fit_read("ui_font_size", FIT_FONT_DEFAULT,
                                   FIT_FONT_MIN, FIT_FONT_MAX, int,
                                   FIT_FONT_PERCENT_ABOVE)
    ss["ui_content_scale"] = _fit_read("ui_content_scale", FIT_SCALE_DEFAULT,
                                       FIT_SCALE_MIN, FIT_SCALE_MAX, int,
                                       None, FIT_SCALE_FACTOR_BELOW)

    font, scale, zoom = _fit_values()
    ss["_fit_injected_via"] = _fit_apply(fit_css(font, scale))


def fit_panel(scope=None):
    """The Display Fit controls. Call LATE - after the page header."""
    import streamlit as st
    ss = st.session_state
    _fit_seed()

    with st.expander("🔎 Display Fit", expanded=False):
        st.slider("Font size (px)", FIT_FONT_MIN, FIT_FONT_MAX, key="ui_font_size")
        st.slider("Content scale (%)", FIT_SCALE_MIN, FIT_SCALE_MAX, key="ui_content_scale")
        st.caption(
            f"Live: font {ss.get('ui_font_size')}px, scale {ss.get('ui_content_scale')}%. "
            "Scale zooms the page content only, never the sidebar."
        )
        st.button("Reset Display Fit", key="ui_fit_rst_btn", width="stretch",
                  on_click=_on_reset_click)

    font, scale, zoom = _fit_values()

    with st.expander("🔧 Display Fit debug", expanded=False):
        st.write(
            {
                "font": font,
                "scale": scale,
                "zoom": round(zoom, 4),
                "injected_via": ss.get("_fit_injected_via", "unknown"),
                "session_state": {
                    "ui_font_size": ss.get("ui_font_size"),
                    "ui_content_scale": ss.get("ui_content_scale"),
                },
            }
        )
        st.code(fit_css(font, scale), language="html")
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
    check("fit_css clamps high", lambda: "font-size: 22px" in fit_css(99, 9))
    check("fit_css clamps low", lambda: "font-size: 12px" in fit_css(1, 0))
    check("fit_css accepts a percent directly", lambda: "zoom: 1.30" in fit_css(16, 130))
    check("fit_css not empty", lambda: len(fit_css()) > 40)
    check("fit_css closes style", lambda: fit_css().rstrip().endswith("</style>"))
    check("fit_css is important", lambda: fit_css().count("!important") >= 2)
    check("_fit_read defaults headless",
          lambda: _fit_read("no_such_key", 7, 0, 10, int) == 7)

    # ---- a percent OR a factor must land in range, from either direction ----
    check("percent scale is untouched",
          lambda: _fit_from(100, FIT_SCALE_DEFAULT, FIT_SCALE_MIN, FIT_SCALE_MAX,
                            float, None, FIT_SCALE_FACTOR_BELOW) == 100)
    check("factor scale converts to a percent",
          lambda: _fit_from(1.25, FIT_SCALE_DEFAULT, FIT_SCALE_MIN, FIT_SCALE_MAX,
                            float, None, FIT_SCALE_FACTOR_BELOW) == 125)
    check("bare factor 1.0 converts",
          lambda: _fit_from(1.0, FIT_SCALE_DEFAULT, FIT_SCALE_MIN, FIT_SCALE_MAX,
                            float, None, FIT_SCALE_FACTOR_BELOW) == 100)
    check("percent font converts",
          lambda: _fit_from(100, FIT_FONT_DEFAULT, FIT_FONT_MIN, FIT_FONT_MAX, int, 40) == 16)
    check("px font is untouched",
          lambda: _fit_from(20, FIT_FONT_DEFAULT, FIT_FONT_MIN, FIT_FONT_MAX, int, 40) == 20)
    check("junk falls back",
          lambda: _fit_from("abc", FIT_SCALE_DEFAULT, FIT_SCALE_MIN, FIT_SCALE_MAX,
                            float, None, FIT_SCALE_FACTOR_BELOW) == FIT_SCALE_DEFAULT)
    check("above-range percent clamps high",
          lambda: _fit_from(250, FIT_SCALE_DEFAULT, FIT_SCALE_MIN, FIT_SCALE_MAX,
                            float, None, FIT_SCALE_FACTOR_BELOW) == FIT_SCALE_MAX)
    check("below-range percent clamps low",
          lambda: _fit_from(9, FIT_SCALE_DEFAULT, FIT_SCALE_MIN, FIT_SCALE_MAX,
                            float, None, FIT_SCALE_FACTOR_BELOW) == FIT_SCALE_MIN)
    # The distinction that was missing: 99px clamps, 100% falls back.
    check("out-of-range px clamps instead of falling back",
          lambda: _fit_from(99, FIT_FONT_DEFAULT, FIT_FONT_MIN, FIT_FONT_MAX, int, 40)
          == FIT_FONT_MAX)

    # ---- the constants must stay inside the ranges fit_css clamps to -------
    check("scale constants are percents",
          lambda: FIT_SCALE_MIN < FIT_SCALE_DEFAULT <= FIT_SCALE_MAX <= 200)
    check("font constants are px",
          lambda: FIT_FONT_MIN <= FIT_FONT_DEFAULT <= FIT_FONT_MAX <= 40)
    check("factor threshold sits below the scale range",
          lambda: FIT_SCALE_FACTOR_BELOW < FIT_SCALE_MIN)
    check("font percent threshold sits above the range",
          lambda: FIT_FONT_PERCENT_ABOVE > FIT_FONT_MAX)
    check("percent threshold is a real percent",
          lambda: FIT_PERCENT_THRESHOLD >= 100)

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
