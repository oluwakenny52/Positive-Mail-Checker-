# Resume note

Branch: fix-phase1
Updated: 2026-11-19 02:30
Verify: 9 needs a full eighteen-gate run before anything else

## Done
- WAVE 0: secrets added in Cloud; GEMINI lines appended to secrets.toml.example
- WAVE 1: status.py 000, engine.py 000, app.py 063, 088, 090, 099
- WAVE 2: hosts.py 010, 014, 016; 007 deps header back to 004,005
- WAVE 3: audit_log.py whole file
- WAVE 4: notify.py whole file
- WAVE 5a: install() before require() on pages/1 005, 2 005, 3 001, 4 005, 5 004, 6 004, 7 005
- WAVE 5b: pages/1 006, pages/4 006, pages/4 010, pages/7 011, pages/7 013, pages/2 016
- Full read: every tracked file in the repo
- WAVE 5c: app.py 040, 044, 053, 056, 080, 086, 091, 095, 096, 097, 102-110
- WAVE 5d: proxy source split; per-source switches; per-source Re-probe and Clear; Source column; permissive manual parser
- WAVE 6: mailsearch.py (new, PLAIN MODULE); folder prompt with NOTHING selected; kw_hits bucket; bodies to disk and ZIP
- WAVE 7: mailsort.py (new, PLAIN MODULE); Mail Sorter as a SIXTH TAB in pages/4 block 013
- WAVE 8: sentinel.py (new, PLAIN MODULE) - expect / satisfy / sweep, reporting to the bell as kind=watch; armed on fetch, restore, per-source re-probe, run start and ZIP build; satisfied by a real survivor, real bytes or a real result
- WAVE 9: README.md whole file (eighteen gates, real layout table, the one-build-number rule); app.py 000, 008, 031; pages/6 000; eleven file headers to v13.76; theme.json DELETED and gitignored

## Next
- WAVE 10: breach page - free /api/v3/breaches catalogue, account-page scrape, psbdmp.ws, freshness verdict

## Blocked
- nothing

## Files in play
- 10: pages/8_Breach.py (new), app.py nav + footer, pages/6 guide tab

## Notes carried forward
- ONE BUILD NUMBER: line 1 of app.py is the only typed number. Block 008 and pages/6 block 001 mirror it and verify_v1337.py proves all four. A bump is those three places, nothing else. File headers carry version= for drift NOTEs only.
- theme.json is runtime-only and gitignored. Absence is normal: block 031 seeds from default_theme(), whose hero comes from BUILD_TAG, and writes on first load. Never re-commit it - a committed seed is a second build number.
- sentinel.py, mailsearch.py, mailsort.py, mailview.py, audit_log.py and notify.py are PLAIN MODULES like runstate.py. No frame, no gate rows, no renumber: blocks=111 in app.py and blocks=16 in pages/4 are unchanged by waves 6, 7 and 8.
- kind="watch" needs no page edit - pages/1_Notifications.py builds its kind filter from whatever exists.
- The sweep runs at the top of block 105, which is module level and runs on every app load. It fires once per REPEAT window, so a rerun loop cannot flood the bell.
- The run expectation is satisfied from block 106's finally by looking at the BUCKETS, not at checked_count - a run that checks everything and buckets nothing is the case being watched for.
- Every sentinel call site is guarded, so the app is unchanged if sentinel.py is absent.
- The sorter caches its grouping on a signature that excludes the seconds-stamped fname.
- TAG_FILE_SAFE() lives in pages/4 block 013 - confirm two hits (the def and the use) before committing.
- kw_hits_results is not reset by a run; it IS emptied by "Delete my RESULT files".

## Waves
- 10 breach page
- 11 block re-arrangement
- 12 gate scripts, CHANGELOG, config
