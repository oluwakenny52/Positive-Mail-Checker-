# Resume note

Branch: fix-phase1
Updated: 2026-11-19 03:10
Verify: three frame gates RED on ONE fault - pages/8_Breach.py has no # @@EOF

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
- WAVE 10 part 1: breach.py (new, PLAIN MODULE, free sources, freshness bands, offline selftest 15 checks)
- WAVE 10 part 2: pages/8_Breach.py (new, 12 blocks); registered in verify_blocks BLOCKED_FILES + targets (15 / 306), fix_end_names, verify_v1337 AUTH_CALLERS + page_numbers

## Next
- pages/8_Breach.py: append `# @@EOF` as the LAST line, then all eighteen gates

## Blocked
- nothing

## Files in play
- pages/8_Breach.py (EOF marker), verify_blocks.py (stale comment + __version__)

## Notes carried forward
- ONE BUILD NUMBER: line 1 of app.py is the only typed number. Block 008 and pages/6 block 001 mirror it and verify_v1337.py proves all four.
- theme.json is runtime-only and gitignored. Never re-commit it.
- sentinel.py, mailsearch.py, mailsort.py, mailview.py, audit_log.py, notify.py and breach.py are PLAIN MODULES like runstate.py. No frame, no gate rows, no renumber.
- ADDING A PAGE is four edits, not one: verify_blocks BLOCKED_FILES, TARGET_FILES, TARGET_BLOCKS, and verify_v1337 AUTH_CALLERS + page_numbers. A file that is counted and not listed is never audited.
- Every block file ends with `# @@EOF`. A new page that omits it fails three gates at once.
- kind="watch" needs no page edit - pages/1 builds its kind filter from whatever exists.
- The sweep runs at the top of block 105 and fires once per REPEAT window.
- Every sentinel call site is guarded, so the app is unchanged if sentinel.py is absent.
- kw_hits_results is not reset by a run; it IS emptied by "Delete my RESULT files".

## Waves
- 10c app.py nav + footer, pages/6 guide tab, README layout rows
- 11 block re-arrangement
- 12 gate scripts, CHANGELOG, config
