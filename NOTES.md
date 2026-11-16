# Resume note

Branch: fix-phase1
Updated: 2026-11-16 15:55
Verify: all gates green; notify.py has no selftest, verify by loading the bell page

## Done
- WAVE 0: secrets added in Cloud; GEMINI lines appended to secrets.toml.example; real keys never entered the repo
- WAVE 1: status.py 000, engine.py 000, app.py 063, 088, 090, 099
- WAVE 2: hosts.py 010, 014, 016 - dropped _is_junk_host alias, _is_plain_domain_guess, get_mx_host; 007 deps header restored to 004,005 with the forward ref in the comment
- WAVE 3: audit_log.py whole file - RLock, trim counter, full _FN_FOR, _close keeps every distinct message, replay suppression, click supersede, type-stable synth key, public drain(), selftest teardown
- WAVE 4: notify.py whole file - prune window max(dedupe, SYS_REPEAT_SECONDS), PRUNE_EVERY sweep, 16-digit monotonic id, .tmp cleanup, makedirs, throttle inside the lock, mark_seen id guard
- Full read: app.py 111 blocks, hosts.py, audit_log.py, notify.py, mailview.py, all 7 pages, audit_frame.py, verify_blocks.py, tier2_split.py, .streamlit/config.toml

## Next
- WAVE 5a: install() before fit() on all 7 pages

## Blocked
- nothing

## Files in play
- pages/1_Notifications.py 005, pages/2..7 auth block (5a)

## Waves
- 5a install() before fit() on 7 pages
- 5b page defects 1,2,4,5,6,7
- 5c app.py 040,044,053,056,086,091,095,096,097,102-110 + Show-raw press
- 5d proxy source split (proxies_secret/custom, per-source toggles)
- 6 mailsearch.py + keyword hits
- 7 mailsort.py + Mail Sorter panel
- 8 sentinel.py
- 9 README, one build number, delete theme.json
- 10 breach page
- 11 block re-arrangement
- 12 gate scripts, CHANGELOG, config
