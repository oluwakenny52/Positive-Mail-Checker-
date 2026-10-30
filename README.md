# Positive Mail Checker

Block-edition Streamlit mail checker. Every section of every big file is a
NAMED, NUMBERED, REPLACEABLE block.

## The frame contract

    # @@BLOCK 016 PROXY_407_CONTRACT deps=-
    ...
    # @@END 016 PROXY_407_CONTRACT

* Replace a WHOLE block - never edit inside one.
* Keep the id and the NAME byte-for-byte; keep ids ascending from 000.
* Nothing but blanks and comments between an `@@END` and the next `@@BLOCK`.
* Every `@@END` MUST carry its block name. A bare `# @@END 016` is a fault.
* The last line of every block file is `# @@EOF`.
* The frame size is deliberately NOT written down here. `verify_blocks.py` owns
  `TARGET_FILES`/`TARGET_BLOCKS`, `audit_frame.py` imports them, and the Scan tab
  prints target against found and warns on drift - so a stale number cannot hide
  in a doc. A frame move is one edit, in `verify_blocks.py`.

## Gates - all thirteen must be green before every commit

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

`.github/workflows/gates.yml` runs all thirteen on every push and writes a PASS/FAIL
table to the run summary, so the gates are checkable from a phone with no
terminal. The Summary step exits non-zero when a gate fails, so the run itself
goes red. The step names in the workflow are the authority if a command above
ever drifts from them.

`pages/5_Blocks.py` runs the same verifier in the browser and can canonicalise a
bare `@@END` for you (download the fixed file, upload it back). It also
validates a paste before you commit.

Always invoke `verify_blocks.py` as `python verify_blocks.py` - its `# @@FILE`
header is line 1, so it has no usable shebang.

## Passphrase and per-user isolation

`auth.py` gates every page. First visit: choose a passphrase (optionally
"Remember on this device", which writes a salted hash to `passkey.json`). Every
per-user file - results directory, clean-valid list, last account, session
cache, export presets, the results ZIP, the resume record - is prefixed with the
unlocked hash, so two people on one deployment stay separate. It is a lock, not
encryption.

"Remember on this device" is a convenience for a private phone. On a shared
deployment, "Forget this passkey" removes only the key you are signed in with;
"Forget all passkeys" deletes `passkey.json` and locks out everybody. `passkey.json`
is per-deployment and resets on redeploy; `theme.json` and `proxies.txt` stay
shared on purpose.

**What is shared, and what that costs you.** `proxies.txt`, `proxies_all.txt`,
`proxy_meta.json`, `domain_cache.json`, `theme.json`, `disposable_domains.txt`
and `passkey.json` are deployment infrastructure, not user data. The
consequences, stated plainly, because they are not free:

* **Fetch & Test All Proxies** rewrites `proxies.txt` for everyone, including a
  run someone else has in flight. The pool is re-read per attempt, so that run
  starts drawing from the new list.
* **Apply Settings** rebuilds the process-wide concurrency semaphores. If another
  run holds one, that run's later release lands on a replaced object.
* **Start** clears the 407 quarantine for the whole process, and rewrites the
  shared AUTO probe target.
* `STATE["cfg"]` is last-writer-wins, so a running check picks up the most
  recently applied settings for proxy mode, timeouts and pool mode.
* The background startup ledger is process-wide, so a second user's panel shows
  the first user's background-thread lines.

Everything that is *yours* is keyed to your unlocked hash: results, buckets,
resume records, presets, the ZIP, and both valid-account caches.

The identity is always DERIVED from `auth.user_file("")`, never from a second
source. That matters: `pages/7_Logs.py` used to probe with `auth._anon_id()`,
which is the pre-unlock placeholder, so its strict mode fired on every unlocked
session and reported a directory as possibly shared when it was demonstrably
yours.

Display Fit (font size / content scale) is in every page's sidebar via
`auth.fit(st)`. Call it **exactly once per page**: it writes the two widget keys
before creating the widgets, and a second call in the same run raises
`StreamlitWidgetAlreadyInstantiatedError` inside its own `try/except`.

Every page guards the import with `hasattr(auth, "fit_panel")` +
`importlib.reload(auth)`, never a bare `auth.fit_panel` expression inside a
`try:`. The bare form is intercepted by Streamlit's magic-write, which routes it
through `st.help` -> `ast.parse` and can raise `IndentationError` on the
enclosing `try:`; the reload is what makes a module cached from before a redeploy
safe.

## Layout

| File | Role |
| --- | --- |
| `app.py` | UI shell + run loop |
| `auth.py` | passphrase gate, per-user paths, Display Fit |
| `engine.py` | headless verification engine |
| `status.py` | canonical verdict taxonomy + classifier (13 blocks) |
| `hosts.py` | host discovery, family priority, ranking |
| `ms_oauth.py` | Microsoft XOAUTH2 (personal accounts) |
| `runstate.py` | unfinished-run watchdog (plain module, not frame-gated) |
| `pages/2_Diagnostics.py` | read-only rung/DNS/proxy inspection |
| `pages/3_Mailbox_Reader.py` | inbox reader, OTP/card scanner |
| `pages/4_Downloads.py` | export studio |
| `pages/5_Blocks.py` | frame inspector |
| `pages/6_User_Guide.py` | end-user manual: every control, button, verdict and page |
| `pages/7_Logs.py` | full log & operator trace (read-only) |

`tier2_split.py` is staged but NOT applied - `engine.py` is currently a separate
hand-written engine that `app.py` does not import.

## Deploy

Streamlit secrets: `WEBSHARE_KEYS`, `OXYLABS_BASE` (see
`.streamlit/secrets.toml.example`). Runtime target is Python 3.14; the pins in
`requirements.txt` are the versions the deploy proved resolve.
