# Resume note

Branch: fix-phase1
Updated: 2026-11-18 20:12 UTC
Verify: all eighteen gates GREEN at 20:09 on 4e5a9c4 (R1-R18 success, files=15 blocks=306 faults=0)

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
- WAVE 8: sentinel.py (new, PLAIN MODULE) - expect / satisfy / sweep, reporting to the bell as kind=watch
- WAVE 9: README.md whole file (eighteen gates, real layout table, one-build-number rule); app.py 000, 008, 031; pages/6 000; eleven file headers to v13.76; theme.json DELETED and gitignored
- WAVE 10: breach.py + pages/8_Breach.py (both new); registered in verify_blocks BLOCKED_FILES + targets 15/306, fix_end_names, verify_v1337 AUTH_CALLERS + page_numbers; all eighteen gates green
- WAVE 10c: app.py 110 fifth nav column; pages/6 013 breach rows; all eighteen green at 19:39
- WAVE 11a: verify_blocks.py 000 - the duplicated TARGET_FILES paragraph (one event, recorded twice, once as v13.77 which no file carries) collapsed to one with deltas only; audit_frame.py whole file - import-failure mirror 14/294 -> 15/306 with pages/8_Breach.py, which had been absent; green at 20:09

## Next
- WAVE 11b: fix_end_names.py docstring (the "2 x 101 = 202 faults across the five files" line); tier2_split.py version fallback v13.40 -> v13.76
- WAVE 11c: .streamlit/config.toml; CHANGELOG.md entry for v13.46-v13.76

## Blocked
- nothing

## Files in play
- fix_end_names.py (whole file), tier2_split.py (whole file)

## Notes carried forward
- ONE BUILD NUMBER: line 1 of app.py is the only typed number. Block 008 and pages/6 block 001 mirror it and verify_v1337.py proves all four.
- theme.json is runtime-only and gitignored. Never re-commit it.
- sentinel.py, mailsearch.py, mailsort.py, mailview.py, audit_log.py, notify.py, breach.py and runstate.py are PLAIN MODULES. No frame, no gate rows, no renumber.
- ADDING A PAGE is four edits: verify_blocks BLOCKED_FILES, TARGET_FILES, TARGET_BLOCKS, and verify_v1337 AUTH_CALLERS + page_numbers.
- Every block file ends with `# @@EOF`. A new page that omits it fails three gates at once.
- pages/6 block 003 and block 015 carry _FIX_CHECKS needles - prefer replacing 013/014 over touching them.
- kind="watch" needs no page edit - pages/1 builds its kind filter from whatever exists.
- The sweep runs at the top of block 105 and fires once per REPEAT window.
- Every sentinel call site is guarded, so the app is unchanged if sentinel.py is absent.
- kw_hits_results is not reset by a run; it IS emptied by "Delete my RESULT files".
- ANYTHING THAT MIRRORS A LIST MUST MOVE IN THE SAME COMMIT AS THE LIST. audit_frame's fallback had been 14/294 since before the breach page and only showed on the import-failure path; fix_end_names' fallback already had all fifteen. A mirror that disagrees with the thing it mirrors is worse than no mirror.
- WAVE 11 does NOT bump the build. Every number stays v13.76, so app.py line 1, block 008 and pages/6 001 are untouched.
- Block re-arrangement waits until the app has been used once, then gets discussed on its own scope and logic. Do not renumber anything before that.

## Waves
- 11 gate scripts, CHANGELOG, config
- 12 block re-arrangement (whole blocks only, renumber contiguously, re-point every deps= header that names a moved block)
