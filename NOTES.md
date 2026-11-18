# Resume note

Branch: fix-phase1
Updated: 2026-11-19 01:40
Verify: 8 needs a full eighteen-gate run before anything else

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

## Next
- WAVE 9: README, one build number, delete theme.json

## Blocked
- nothing

## Files in play
- 8: sentinel.py (new), app.py 080, 105, 106, 107
- 9: README.md, theme.json, block 008

## Notes carried forward
- sentinel.py, mailsearch.py and mailsort.py are PLAIN MODULES like runstate.py. No frame, no gate rows, no renumber: blocks=111 in app.py and blocks=16 in pages/4 are unchanged by waves 6, 7 and 8.
- kind="watch" needs no page edit - pages/1_Notifications.py builds its kind filter from whatever exists.
- The sweep runs at the top of block 105, which is module level and runs on every app load. It fires once per REPEAT window, so a rerun loop cannot flood the bell.
- The run expectation is satisfied from block 106's finally by looking at the BUCKETS, not at checked_count - a run that checks everything and buckets nothing is the case being watched for.
- Every sentinel call site is guarded, so the app is unchanged if sentinel.py is absent.
- The sorter caches its grouping on a signature that excludes the seconds-stamped fname.
- TAG_FILE_SAFE() lives in pages/4 block 013 - confirm two hits (the def and the use) before committing.
- kw_hits_results is not reset by a run; it IS emptied by "Delete my RESULT files".

## Waves
- 9 README, one build number, delete theme.json
- 10 breach page
- 11 block re-arrangement
- 12 gate scripts, CHANGELOG, config
