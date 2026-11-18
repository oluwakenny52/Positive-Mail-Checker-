# Resume note

Branch: fix-phase1
Updated: 2026-11-18 23:05
Verify: 6 needs a full eighteen-gate run before anything else

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
- WAVE 6: mailsearch.py (new, PLAIN MODULE - no frame, no gate rows, blocks stays 111); folder prompt with NOTHING selected (index=None + placeholder, Search refuses until a folder is picked); keyword hits into the kw_hits bucket; bodies to mail_results/kw_hits_<stamp>/ and into the ZIP under keyword_bodies/; wiring in 036, 079, 087, 105, 106, 107, 108, 109

## Next
- WAVE 7: mailsort.py + Mail Sorter panel on Export Studio

## Blocked
- nothing

## Files in play
- 6: mailsearch.py (new), app.py 036, 079, 087, 105, 106, 107, 108, 109
- 7: new mailsort.py, pages/4_Downloads.py

## Notes carried forward
- mailsearch.py is a PLAIN MODULE like runstate.py: verify_blocks.py, audit_frame.py and fix_end_names.py are untouched by WAVE 6, and blocks=111 in app.py stays 111.
- 098 READ_MAILBOX still hard-codes INBOX and is UNTOUCHED. mailsearch.py selects its own folder, so folder support did not have to go into the reader's fetch.
- kw_hits_results is NOT reset when a run starts (block 105) - it comes from the reader, not from a run. It IS emptied by "Delete my RESULT files".
- A keyword hit line is `email:password | kw:... | folder:...`, so _raw_of() re-runs it as a plain combo.
- 5d: 077 is untouched on purpose - 080 folds a completed fetch into the provider list.
- 5d: 079's keep list gets the two source names from 080, from the run AFTER 080 first executes.

## Waves
- 7 mailsort.py + Mail Sorter panel
- 8 sentinel.py
- 9 README, one build number, delete theme.json
- 10 breach page
- 11 block re-arrangement
- 12 gate scripts, CHANGELOG, config
