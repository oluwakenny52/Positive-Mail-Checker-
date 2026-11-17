# Resume note

Branch: fix-phase1
Updated: 2026-11-16 16:40
Verify: all gates green; 5a needs the six pages loaded once with a locked session

## Done
- WAVE 0: secrets added in Cloud; GEMINI lines appended to secrets.toml.example; real keys never entered the repo
- WAVE 1: status.py 000, engine.py 000, app.py 063, 088, 090, 099
- WAVE 2: hosts.py 010, 014, 016 - dropped _is_junk_host alias, _is_plain_domain_guess, get_mx_host; 007 deps header restored to 004,005 with the forward ref in the comment
- WAVE 3: audit_log.py whole file - RLock, trim counter, full _FN_FOR, _close keeps every distinct message, replay suppression, click supersede, type-stable synth key, public drain(), selftest teardown
- WAVE 4: notify.py whole file - prune window max(dedupe, SYS_REPEAT_SECONDS), PRUNE_EVERY sweep, 16-digit monotonic id, .tmp cleanup, makedirs, throttle inside the lock, mark_seen id guard
- WAVE 5a: install() before require() on pages/1 005, pages/2 005, pages/3 001, pages/4 005, pages/5 004, pages/6 004, pages/7 005. app.py 007 already had it (FIX AU-5)
- Full read: every tracked file in the repo

## Next
- WAVE 5b: page defects 1, 2, 4, 5, 6, 7

## Blocked
- nothing

## Files in play
- pages/2, pages/3, pages/4, pages/6, pages/7 defect blocks (5b)

## Waves
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
