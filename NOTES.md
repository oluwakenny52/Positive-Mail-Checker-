# Resume note

Branch: fix-phase1
Updated: 2026-11-19 00:20
Verify: 7 needs a full eighteen-gate run before anything else

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
- WAVE 5d: proxy source split - proxies_secret.txt / proxies_custom.txt / merged proxies.txt; per-source switches both ON; per-source Re-probe and Clear; Source column; permissive manual parser
- WAVE 6: mailsearch.py (new, PLAIN MODULE); folder prompt with NOTHING selected; keyword hits into kw_hits; bodies to disk and into the ZIP; wiring in 036, 079, 087, 105, 106, 107, 108, 109
- WAVE 7: mailsort.py (new, PLAIN MODULE); Mail Sorter as a SIXTH TAB in pages/4 block 013 - group by domain / status / TLD / host / keyword / folder / length band / first letter / source / none, explicit order, per-group cap, per-group button and one archive

## Next
- WAVE 8: sentinel.py with expect/satisfy/sweep, reporting to the bell as category=watch

## Blocked
- nothing

## Files in play
- 7: mailsort.py (new), pages/4_Downloads.py 013
- 8: new sentinel.py, app.py bell wiring

## Notes carried forward
- mailsearch.py and mailsort.py are PLAIN MODULES like runstate.py: no frame, no gate rows, no renumber. blocks=111 in app.py and blocks=16 in pages/4 are BOTH unchanged by waves 6 and 7.
- The sorter went in as a TAB, not a block, on purpose: a new block id in pages/4 would need a header count edit, a TRAILING renumber AND a TARGET_BLOCKS bump in verify_blocks.py, and audit_frame.py goes RED on any drift.
- TAG_FILE_SAFE() is defined in pages/4 block 013 for the per-status split buttons.
- The sorter caches its grouping on a signature and never puts the seconds-stamped fname in that signature.
- kw_hits_results is not reset by a run; it IS emptied by "Delete my RESULT files".
- 5d: 077 untouched - 080 folds a completed fetch into the provider list.

## Waves
- 8 sentinel.py
- 9 README, one build number, delete theme.json
- 10 breach page
- 11 block re-arrangement
- 12 gate scripts, CHANGELOG, config
