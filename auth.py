# @@FILE auth.py blocks=6 version=v13.48
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

Because Streamlit re-runs a page in the SAME process, a module imported before a
redeploy stays in sys.modules and keeps answering with the old shape. Callers
guard with importlib.reload() - see the note in block 004.

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
import threading

# One lock for every read-modify-write on passkey.json. _save() is atomic for the
# WRITE, but add_key() and the two forget_* calls read the list first, so two
# people creating a passkey at the same moment both built from the same snapshot
# and the second os.replace() dropped the first's key. Reentrant because
# forget_current() is called from inside require() while a caller may already
# hold it.
_key_lock = threading.RLock()


def _digest(phrase, salt):
    return hashlib.sha256((salt + "\x00" + phrase).encode("utf-8")).hexdigest()[:HASH_LEN]


def _norm(phrase):
    """Comparison form: trimmed, single-spaced, casefolded.

    v13.75: THIS IS THE "Wrong passphrase" FIX. The comparison was exact-only, so
    a phone keyboard that capitalises the first letter, or a paste that carries a
    trailing space, rejected a correct phrase. The exact hash is still tried
    FIRST, so case still distinguishes two keys that would otherwise collide; the
    normalised form is only a fallback.
    """
    return " ".join((phrase or "").split()).casefold()


def _load():
    try:
        with open(PASSKEY_FILE, encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict) and isinstance(data.get("keys"), list):
            # A hand-edited or half-written record used to crash compare_digest
            # (str vs None) and surface as a bare exception, not "wrong phrase".
            data["keys"] = [k for k in data["keys"]
                            if isinstance(k, dict) and isinstance(k.get("hash"), str)]
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


def add_key(phrase, label="", admin=False):
    """Create a passkey, persist it, return its hash.

    v13.75: THE FIRST KEY IS THE ADMIN, and every key now stores its phrase. The
    phrase is stored in clear beside the salted hash because there is no way to
    recover it from a hash, and the admin has to be able to read it back.
    passkey.json is therefore a keyring, not a secret: whoever holds the file
    holds every phrase.
    """
    phrase = (phrase or "").strip()
    with _key_lock:
        data = _load()
        salt = secrets.token_hex(SALT_BYTES)
        h = _digest(phrase, salt)
        data["keys"].append({"salt": salt, "hash": h,
                             "hash_n": _digest(_norm(phrase), salt),
                             "phrase": phrase[:120],
                             "label": (label or "").strip()[:40],
                             "admin": bool(admin) or not data["keys"],
                             "created": int(time.time())})
        _save(data)
    return h


def match_key_full(phrase):
    """The stored key `phrase` opens, or {}. Exact pass first, then normalised."""
    phrase = (phrase or "").strip()
    if not phrase:
        return {}
    with _key_lock:
        keys = [k for k in (_load().get("keys") or []) if isinstance(k, dict)]
    for k in reversed(keys):
        if secrets.compare_digest(_digest(phrase, k.get("salt", "")), k.get("hash", "")):
            return k
    n = _norm(phrase)
    for k in reversed(keys):
        if k.get("hash_n") and secrets.compare_digest(
                _digest(n, k.get("salt", "")), k["hash_n"]):
            return k
    return {}


def match_key(phrase):
    """Return the stored hash `phrase` opens, or ''."""
    return match_key_full(phrase).get("hash", "")


def forget_current(h):
    """Drop ONE key. Every other user keeps working. Empty list -> delete file."""
    if not h:
        return
    with _key_lock:
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
    with _key_lock:
        for p in (PASSKEY_FILE, PASSKEY_FILE + ".tmp"):
            try:
                if os.path.exists(p):
                    os.remove(p)
            except Exception:
                pass


def user_key_hash():
    import streamlit as st
    return str(st.session_state.get("user_key_hash", ""))


def _anon_id():
    """Identity for a session that has not unlocked yet.

    user_file() returned the BARE name when there was no hash, so every file
    written before require() - and every path built at import time before the
    key exists - landed unprefixed in the shared working directory.  Two users
    on one deployment therefore shared one results dir, one clean-valid list and
    one session cache, and each saw the other's runs.

    A per-session anonymous id is used until the passphrase arrives, so a path
    is never bare.  "anonlocal" covers the headless case (no Streamlit, e.g.
    --selftest), where there is no session to collide with.
    """
    try:
        import streamlit as st
        ss = st.session_state
    except Exception:
        return "anonlocal"
    h = ss.get("user_key_hash")
    if h:
        return h
    if not ss.get("_anon_hash"):
        ss["_anon_hash"] = "anon" + secrets.token_hex(8)
    return ss["_anon_hash"]


def user_file(name):
    """Per-user filename. NEVER bare - see _anon_id()."""
    h = _anon_id()
    return "%s_%s" % (h, name) if name else h


def user_dir(name=""):
    """Per-user directory under data/, created on demand."""
    d = os.path.join("data", _anon_id())
    if name:
        d = os.path.join(d, name)
    try:
        os.makedirs(d, exist_ok=True)
    except Exception:
        pass
    return d
# @@END 001 KEYS


# @@BLOCK 002 GATE deps=001
def _flash(st, outcome, text):
    """Report a press through the ledger when it is present, else directly."""
    try:
        import audit_log
        if hasattr(audit_log, "flash"):
            audit_log.flash(st, outcome, text)
            return
    except Exception:
        pass
    try:
        {"OK": st.success, "WARN": st.warning,
         "FAILED": st.error}.get(outcome, st.info)(text)
    except Exception:
        pass


def _enter(st, key, why="Unlocked"):
    """Bind this session to `key` and mirror its admin bit."""
    st.session_state["user_key_hash"] = key.get("hash", "")
    st.session_state["is_admin"] = bool(key.get("admin"))
    _flash(st, "OK", why + ". Every file below is yours alone.")


def _key_rows():
    """(label, hash, created, phrase, admin) for every stored key, oldest first."""
    rows = []
    for k in (_load().get("keys") or []):
        if not isinstance(k, dict):
            continue
        rows.append((((k.get("label") or "").strip() or "unlabelled"),
                      str(k.get("hash", "")),
                      int(k.get("created") or 0),
                      str(k.get("phrase") or ""),
                      bool(k.get("admin"))))
    return rows


def _when(ts):
    try:
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts)) if ts else "?"
    except Exception:
        return "?"


def is_admin():
    """True when the UNLOCKED key carries the admin bit.

    v13.76 FIX ADMIN-1: the bit was only ever read from session_state and only
    ever written by _enter() on unlock - so it survived exactly the one session
    in which require() short-circuits and the panel could not be drawn. It is
    DERIVED from the stored record for the current hash now, so it survives a
    refresh, and a second unlock can never inherit it.
    """
    try:
        import streamlit as st
        cur = str(st.session_state.get("user_key_hash") or "")
    except Exception:
        return False
    if not cur:
        return False
    with _key_lock:
        for k in (_load().get("keys") or []):
            if isinstance(k, dict) and str(k.get("hash", "")) == cur:
                return bool(k.get("admin"))
    return False


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
            hit = match_key_full(phrase)
            if hit:
                st.session_state.pop("au_fails", None)
                _enter(st, hit)
                st.rerun()
            else:
                fails = int(st.session_state.get("au_fails", 0)) + 1
                st.session_state["au_fails"] = fails
                st.error("Wrong passphrase.")
                # v13.75: after a second miss, name the keys that exist. The
                # "wrong passphrase" box used to be a dead end - the user could
                # not tell a typo from having no key here at all, which is what a
                # passphrase created with "remember" unticked used to leave.
                if fails >= 2:
                    _labels = [r[0] for r in _key_rows()]
                    if _labels:
                        st.caption("Keys on this device: %s. Case and spacing are "
                                   "forgiven; a different word is not."
                                   % ", ".join("`%s`" % x for x in _labels))
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
                    h = add_key(p2, lbl)
                    st.session_state.pop("au_fails", None)
                    _enter(st, {"hash": h, "admin": False}, "Passkey created")
                    st.rerun()

        # v13.76 FIX ADMIN-1: the manager is NOT here any more. It lived below
        # this point, inside `if known:`, gated on session_state["is_admin"] -
        # and require() returns before any of it once the session is unlocked,
        # while is_admin is only set by the unlock that is followed by a rerun.
        # It is admin_panel() now and the caller draws it AFTER the gate.
        st.caption("Passkey management (including Forget) is on the page once you "
                   "are unlocked - the first passphrase created on a device is its "
                   "admin.")
        st.stop()

    st.caption("No passkey yet - create one. It is asked once per session. This one "
               "becomes the admin key.")
    with st.form("auth_create"):
        p1 = st.text_input("Choose a passphrase", type="password", key="au_c1")
        p2 = st.text_input("Repeat it", type="password", key="au_c2")
        go = st.form_submit_button("Create and enter", type="primary")
    if go:
        p1 = (p1 or "").strip()
        if len(p1) < MIN_LEN:
            st.error("Use at least %d characters." % MIN_LEN)
        elif p1 != p2:
            st.error("The two passphrases differ.")
        else:
            # v13.75: THIS ALWAYS PERSISTS NOW. With "Remember on this device"
            # unticked the old path hashed the phrase with a fresh random salt and
            # wrote nothing, so that passphrase could never match again - it worked
            # for the session and was "wrong" forever after.
            h = add_key(p1)
            _enter(st, {"hash": h, "admin": True}, "Passkey created as admin")
            st.rerun()
    st.stop()


def admin_panel(st):
    """The admin keyring: every passphrase, and both Forget buttons.

    Draw it AFTER the gate, from a page that has already called require() and
    fit(). Returns immediately for a non-admin, so a normal user sees nothing.

    v13.76 FIX ADMIN-1: reachable for the first time. The gate is is_admin(),
    which reads the stored record for the CURRENT hash - not a session flag that
    the next rerun outlives.

    v13.76 FIX ADMIN-2: THE CAPTION WAS WRONG. It promised that files reopen if a
    key is re-created with the same phrase. add_key() mints a fresh random salt
    every time, so the same phrase yields a DIFFERENT hash and therefore a
    different user_file() prefix - the old <hash>_* files stay on disk and the
    new key cannot see a single one. The caption says so now, and the Forget
    action reports the prefix it is about to orphan.
    """
    if not is_admin():
        return
    with st.expander("🔑 Manage passkeys (admin)", expanded=False):
        st.caption("Every key on this device, with its phrase in clear - passkey.json "
                   "is a keyring, not a secret, so whoever holds that file holds every "
                   "phrase. Removing a key removes that person's ACCESS. Their files "
                   "stay on disk but are ORPHANED: re-creating the same phrase mints a "
                   "new random salt, so it gets a different hash and a different file "
                   "prefix and cannot reach the old files.")
        rows = _key_rows()
        pick = {}
        for label, h, created, phrase, is_admin_ in rows:
            pick["%s%s · %s · %s" % (label, " (admin)" if is_admin_ else "",
                                     h[:8], _when(created))] = h
        st.dataframe(
            [{"Label": lb, "Admin": "yes" if ad else "",
              "Hash": h[:12], "Prefix": "%s_" % h, "Created": _when(cr),
              "Passphrase": ph or "(not stored - re-create this key)"}
             for lb, h, cr, ph, ad in rows],
            width="stretch", hide_index=True,
        )
        if pick:
            choice = st.selectbox("Which passkey", list(pick))
            if st.button("Forget selected passkey", key="au_forget_one"):
                gone = pick.get(choice, "")
                forget_current(gone)
                st.session_state.pop("user_key_hash", None)
                st.session_state.pop("is_admin", None)
                # v13.64: the forgotten key's per-user tables live in app.py's
                # process STATE and used to survive for the life of the process -
                # pool, quarantine, scores and its alive-pool thread. app.py block
                # 039 drops them; this is the only place that knows WHICH key.
                st.session_state["_forgotten_hash"] = gone
                _flash(st, "OK", "Passkey forgotten. Its files stay on disk under the "
                                 "prefix %s_ and are orphaned until a key with that "
                                 "exact hash exists again." % gone)
                st.rerun()
            st.caption("Or remove every key, for everyone.")
            if st.button("Forget all passkeys", key="au_forget_all"):
                # v13.51: user_key_hash is ALWAYS "" on this branch, so the old
                # read handed app.py block 039 an empty hash and it dropped no
                # tables at all. Keep the selected key instead.
                gone = pick.get(choice, "")
                forget_all()
                st.session_state["_forgotten_hash"] = gone
                st.session_state.pop("user_key_hash", None)
                st.session_state.pop("is_admin", None)
                _flash(st, "WARN", "Every passkey was removed. Nothing unlocks now "
                                   "until a new one is created - and the new key gets "
                                   "a new prefix, so every existing file is orphaned.")
                st.rerun()
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
# NOTE FOR CALLERS: Streamlit re-runs a page in the same process, so an `auth`
# module imported before a redeploy stays in sys.modules and keeps the OLD
# shape - which is how fit_panel() answered AttributeError for hours after it
# existed on disk. Every caller guards like this:

#     import auth
#     try:
#         auth.fit_panel
#     except AttributeError:
#         import importlib
#         auth = importlib.reload(auth)

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

    font, scale, _zoom = _fit_values()
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


# @@BLOCK 005 SELFTEST deps=001,003,004
def _selftest() -> None:
    bad = []

    def check(name, fn):
        try:
            if fn() is False:
                bad.append(name)
        except Exception as exc:
            bad.append(f"{name} ({type(exc).__name__}: {exc})")

    # ---- the API every caller binds to must exist -------------------------
    check("fit is callable", lambda: callable(fit))
    check("fit_panel is callable", lambda: callable(fit_panel))
    check("fit_panel is not fit", lambda: fit_panel is not fit)
    check("require is callable", lambda: callable(require))
    check("user_file is callable", lambda: callable(user_file))

    # ---- isolation: a path is never bare, even before unlock -------------
    check("anon id is non-empty headless", lambda: bool(_anon_id()))
    check("user_file prefixes headless", lambda: user_file("x.txt").endswith("_x.txt"))
    check("user_file('') is not empty", lambda: bool(user_file("")))
    check("user_file('') has no separator", lambda: "_" not in user_file(""))
    check("user_dir is under data/", lambda: user_dir().startswith("data/"))

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
