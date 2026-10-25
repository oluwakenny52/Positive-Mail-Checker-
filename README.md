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

## Gates - run all four before every commit

    python fix_end_names.py --check      # 0 = no bare @@END pending
    python verify_blocks.py              # 0 = frame intact
    python audit_frame.py                # must print RESULT: GREEN
    python verify_v1337.py               # must print FAILED 0
    python test_verdicts.py              # behavioural test

## In-browser

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

## Deploy

Streamlit secrets: `WEBSHARE_KEYS`, `OXYLABS_BASE` (see
`.streamlit/secrets.toml.example`). Runtime target is Python 3.14; the pins in
`requirements.txt` are the versions the deploy proved resolve.
