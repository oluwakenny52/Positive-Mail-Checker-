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

## Gates - all seven must be green before every commit

    python fix_end_names.py --check      # exit 0 = no bare @@END pending
    python verify_blocks.py              # exit 0 = frame intact
    python audit_frame.py                # must print RESULT: GREEN
    python verify_v1337.py               # must print FAILED 0
    python test_verdicts.py              # must print FAILED 0
    python engine.py --selftest          # exit 0 = headless engine sanity
    python status.py --selftest          # exit 0 = status classifier sanity

`.github/workflows/gates.yml` runs all seven on every push and writes a PASS/FAIL
table to the run summary, so the gates are checkable from a phone with no
terminal. The Summary step exits non-zero when a gate fails, so the run itself goes red. 

`pages/5_Blocks.py` runs the same verifier in the browser and can
canonicalise a bare `@@END` for you (download the fixed file, upload it back).

Always invoke `verify_blocks.py` as `python verify_blocks.py` - its `# @@FILE`
header is line 1, so it has no usable shebang.

## In-browser
## Passphrase and per-user isolation

`auth.py` gates every page. First visit: choose a passphrase (optionally
"Remember on this device", which writes a salted hash to `passkey.json`). Every
per-user file - results directory, clean-valid list, last account, session
cache - is prefixed with the unlocked hash, so two people on one deployment stay
separate. It is a lock, not encryption.

Display Fit (font size / content scale) is in every page's sidebar via
`auth.fit(st)`.

`pages/5_Blocks.py` (Block Inspector) runs the same engine in the browser and
validates a paste before you commit.

## Layout

| File | Role |
|---|---|
| `app.py` | UI shell + run loop (111 blocks) |
| `engine.py` | headless verification engine (12 blocks) |
| `status.py` | canonical verdict taxonomy + classifier (13 blocks) |
| `hosts.py` | host discovery, family priority, ranking |
| `ms_oauth.py` | Microsoft XOAUTH2 (personal accounts) |
| `pages/2_Diagnostics.py` | read-only rung/DNS/proxy inspection |
| `pages/3_Mailbox_Reader.py` | inbox reader, OTP/card scanner |
| `pages/4_Downloads.py` | export studio |
| `pages/5_Blocks.py` | frame inspector |
| `pages/6_User_Guide.py` | end-user manual: every control, button, verdict and page |

tier2_split.py is staged but NOT applied — engine.py is currently a separate hand-written engine that app.py does not import.

## Deploy

Streamlit secrets: `WEBSHARE_KEYS`, `OXYLABS_BASE` (see
`.streamlit/secrets.toml.example`). Runtime target is Python 3.14; the pins in
`requirements.txt` are the versions the deploy proved resolve.
