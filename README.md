# Positive Mail Checker

Block-edition Streamlit mail checker. Every section of every big file is a
NAMED, NUMBERED, REPLACEABLE block.

## The frame contract

    # @@BLOCK 016 PROXY_407_CONTRACT deps=-
    ...
    # @@END 016 PROXY_407_CONTRACT

- Replace a WHOLE block - never edit inside one.
- Keep the id and the NAME byte-for-byte; keep ids ascending from 000.
- Nothing but blanks and comments between an `@@END` and the next `@@BLOCK`.
- Every `@@END` MUST carry its block name. A bare `# @@END 016` is a fault.
- The last line of every block file is `# @@EOF`.
- The frame size is deliberately NOT written down here. `verify_blocks.py` owns
`TARGET_FILES`/`TARGET_BLOCKS`, `audit_frame.py` imports them, and the Scan tab
prints target against found and warns on drift - so a stale number cannot hide
in a doc. A frame move is one edit, in `verify_blocks.py`.

## One build number

The build number is typed by hand in exactly ONE place: line 1 of `app.py`.

    # @@FILE app.py blocks=N version=v13.76

`app.py` block 008 mirrors it as `BUILD_TAG` and `CFG_VERSION`,
`pages/6_User_Guide.py` block 001 mirrors both again, and `verify_v1337.py`
parses line 1 and fails if either constant disagrees, if either is assigned
twice, or if the guide drifts. Every user-visible version string - hero title,
diag bundle, run export, footer, guide hero - reads `BUILD_TAG` and types
nothing.

A bump is therefore: line 1, block 008, `pages/6_User_Guide.py` block 001. A
number typed anywhere else is a bug. File headers carry `version=` so
`verify_v1337.py` can NOTE drift, but line 1 of `app.py` is the only authority.

`CFG_VERSION` is the config-migration counter and its digits must equal
`BUILD_TAG`'s. Bump it when a DEFAULT changes in a way users should inherit.

## Gates - all eighteen must be green before every commit

    python fix_end_names.py --check      # exit 0 = no bare @@END pending
    python verify_blocks.py              # exit 0 = frame intact
    python audit_frame.py                # must print RESULT: GREEN
    python verify_v1337.py               # must print FAILED 0
    python test_verdicts.py              # must print FAILED 0
    python engine.py --selftest          # exit 0 = headless engine sanity
    python status.py --selftest          # exit 0 = verdict alias sanity
    python auth.py --selftest            # exit 0 = gate + Display Fit sanity
    python -m compileall -q .            # exit 0 = everything compiles
    pip install -r requirements.txt      # exit 0 = pins still resolve
    python pages/5_Blocks.py --fix-check # exit 0 = the fixes are still in the code
    python runstate.py --selftest        # exit 0 = watchdog lifecycle sanity
    python test_resume_io.py             # exit 0 = resume IO expressions are real

Five more run as shell steps, because they are one-liners over the tree and a
Python script would be more moving parts than the check:

- `app.py`'s `blocks=N` header equals the number of `# @@BLOCK ` lines.
- the number of `# @@END ` lines equals the same N.
- the last line of `app.py` is `# @@EOF`.
- `read_timeout` appears nowhere in `app.py`.
- no `<<<<<<< ` conflict marker in any `.py`.

`.github/workflows/gates.yml` runs all eighteen on every push and writes a
PASS/FAIL table to the run summary, so the gates are checkable from a phone with
no terminal. The Summary step exits non-zero when a gate fails, so the run
itself goes red. The step names in the workflow are the authority if a command
above ever drifts from them.

`pages/5_Blocks.py` runs the same verifier in the browser and can canonicalise a
bare `@@END` for you (download the fixed file, upload it back). It also
validates a paste before you commit.

Always invoke `verify_blocks.py` as `python verify_blocks.py` - its `# @@FILE`
header is line 1, so it has no usable shebang.

## Passphrase and per-user isolation

`auth.py` gates every page. First visit: choose a passphrase (optionally
"Remember on this device", which writes a salted hash to `passkey.json`). Every
per-user file - results directory, clean-valid list, last account, session
cache, export presets, the results ZIP, the resume record, the proxy pool and
its two source lists, the proxy metadata, the domain cache, the probe key map,
the classifier's day budget, the theme and the applied settings - is prefixed
with the unlocked hash, so two people on one deployment stay separate. It is a
lock, not encryption.

"Remember on this device" is a convenience for a private phone. On a shared
deployment, "Forget this passkey" removes only the key you are signed in with;
"Forget all passkeys" deletes `passkey.json` and locks out everybody.
`passkey.json` is per-deployment and resets on redeploy.

**What is shared, and what that costs you.** Two files only: `passkey.json` (the
keyring) and `disposable_domains.txt` (a downloaded blocklist, identical for
everybody). Everything else is yours. The consequences, stated plainly, because
they are not free:

- `passkey.json` is the keyring itself, so `Forget all passkeys` is
  deployment-wide by definition.
- `disposable_domains.txt` is rewritten by whichever session fetched it last. Two
  sessions fetching at once can race the write; the content is the same either
  way.

`proxies.txt`, the two proxy source lists, `proxies_all.txt`, `proxy_meta.json`,
`proxy_key_map.json`, `domain_cache.json`, `ai_usage.json`, `theme.json` and
`settings.json` are all per-user. So is every `ui_*` / `chk_*` value: they are
written to `settings.json` on Apply Settings and re-read before the sidebar is
built, so a refresh, a tab close or a redeploy restores the owner's own panel
instead of the factory defaults.

`theme.json` is NOT committed. It is a runtime file, created from
`default_theme()` on a user's first load, so a fresh clone can never ship a
stale hero title or a stale build number.

`STATE["cfg"]` is still a process value, and block 105 pins a per-task snapshot
over it for workers, so a running check does not start following another
session's settings mid-account.

Two more things are process-wide rather than per-user, and both belong to the
classifier: its per-run call counter and its text cache live in module memory,
so a probe one session spends is charged to whichever run is live. Its DAY
budget is the per-user file above, so the allowance itself cannot be eaten by
somebody else.

The identity is always DERIVED from `auth.user_file("")`, never from a second
source. That matters: `pages/7_Logs.py` used to probe with `auth._anon_id()`,
which is the pre-unlock placeholder, so its strict mode fired on every unlocked
session and reported a directory as possibly shared when it was demonstrably
yours.

Display Fit (font size / content scale) is in every page's sidebar via
`auth.fit(st)`. Call it **exactly once per page**: it writes the two widget keys
before creating the widgets, and a second call in the same run raises
`StreamlitWidgetAlreadyInstantiatedError` inside its own `try/except`.

Pages guard the import with `hasattr(auth, "fit_panel")` +
`importlib.reload(auth)`, never a bare `auth.fit_panel` expression inside a
`try:`. The bare form is intercepted by Streamlit's magic-write, which routes it
through `st.help` -> `ast.parse` and can raise `IndentationError` on the
enclosing `try:`; the reload is what makes a module cached from before a redeploy
safe. `pages/2_Diagnostics.py` was the last page without the guard and gained it
in block 005 at v13.81 - without it, a redeploy with that page already open died
on `AttributeError: module 'auth' has no attribute 'fit_panel'` before the hero
could render.

## Layout

| File | Role |
| --- | --- |
| `app.py` | UI shell + run loop |
| `auth.py` | passphrase gate, per-user paths, Display Fit |
| `engine.py` | headless verification engine |
| `status.py` | canonical verdict taxonomy + error classifier |
| `aiassist.py` | UNKNOWN-tail classifier of last resort (plain module) |
| `hosts.py` | host discovery, family priority, ranking |
| `ms_oauth.py` | Microsoft XOAUTH2 (personal accounts) |
| `audit_log.py` | per-user action & outcome ledger (plain module) |
| `notify.py` | per-user bounded notification ring (plain module) |
| `mailsearch.py` | keyword search over one verified mailbox (plain module) |
| `mailview.py` | safe mail body renderer (plain module) |
| `mailsort.py` | group / sort / zip a row set (plain module) |
| `runstate.py` | unfinished-run watchdog (plain module) |
| `sentinel.py` | expect / satisfy / sweep delivery watchdog (plain module) |
| `breach.py` | keyless breach lookup, freshness bands (plain module) |
| `pages/1_Notifications.py` | the bell: filterable notification history |
| `pages/2_Diagnostics.py` | rung / DNS / proxy inspection, plus a live AI-probe tab |
| `pages/3_Mailbox_Reader.py` | inbox reader, OTP/card scanner |
| `pages/4_Downloads.py` | export studio, Mail Sorter |
| `pages/5_Blocks.py` | frame inspector |
| `pages/6_User_Guide.py` | end-user manual: every control, button, verdict and page |
| `pages/7_Logs.py` | full log & operator trace (read-only) |
| `pages/8_Breach.py` | breach exposure for a list of addresses |

`tier2_split.py` is staged but NOT applied - `engine.py` is currently a separate
hand-written engine that `app.py` does not import.

`audit_frame.py`, `verify_blocks.py`, `verify_v1337.py`, `fix_end_names.py`,
`repair_app_syntax.py`, `test_verdicts.py` and `test_resume_io.py` are gates, not
runtime code. `NOTES.md` is the resume note and `CHANGELOG.md` is the history.

## Deploy

Streamlit secrets: `WEBSHARE_KEYS`, `OXYLABS_BASE`, and optionally
`GEMINI_ENABLED` (the string `true`), `GEMINI_API_KEY` and `GEMINI_MODEL` for the
unknown-tail classifier - see `.streamlit/secrets.toml.example`. Leave the
GEMINI lines out and the classifier stays off; nothing else changes. Runtime
target is Python 3.14; the pins in `requirements.txt` are the versions the
deploy proved resolve.
