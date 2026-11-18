# Resume note

Branch: fix-phase1
Updated: 2026-11-18 21:40
Verify: 5c and 5d need a full eighteen-gate run before anything else

## Done
- WAVE 0: secrets added in Cloud; GEMINI lines appended to secrets.toml.example; real keys never entered the repo
- WAVE 1: status.py 000, engine.py 000, app.py 063, 088, 090, 099
- WAVE 2: hosts.py 010, 014, 016 dead symbols; 007 deps header back to 004,005
- WAVE 3: audit_log.py whole file - RLock, trim counter, _FN_FOR, _close keeps every distinct message, replay suppression, public drain()
- WAVE 4: notify.py whole file - prune window, PRUNE_EVERY, 16-digit id, .tmp cleanup, throttle in lock
- WAVE 5a: install() before require() on pages/1 005, 2 005, 3 001, 4 005, 5 004, 6 004, 7 005 (app.py 007 already had it)
- WAVE 5b: pages/1 006 tick-before-counts, pages/4 006 IGNORE tokens, pages/4 010 no stop, pages/7 011 index guard, pages/7 013 import io, pages/2 016 per-user proxies path
- Full read: every tracked file in the repo
- WAVE 5c: app.py 040 (proxy gate re-limited inside host_gate_lock), 044, 053, 056 (colorize_logs seeded), 080 (Show-raw press), 086, 091, 095, 096, 097, 102, 103, 104, 105, 106, 107, 108, 109, 110
- WAVE 5d: proxy source split - proxies_secret.txt / proxies_custom.txt / merged proxies.txt; per-user switches both ON by default; per-source Re-probe and Clear; Source column on all three dashboard tables; fetch and Restore write the provider list; permissive manual parser (labels, bullets, Sock5/socks5://, hyphenated user and pass kept, host:port:user:pass, user:pass@host:port, 4/3/2 part, masked octets kept and counted, junk dropped with a count)

## Next
- WAVE 6: mailsearch.py + keyword hits + kw_hits bucket + folder prompt with nothing selected + body to disk/bucket/ZIP

## Blocked
- nothing

## Files in play
- 5d: app.py 043, 052, 058, 080 (all committed)
- 6: new mailsearch.py, app.py keyword wiring

## Notes carried forward
- 077 is untouched on purpose: its fetch still writes the working file and 080 folds a completed fetch into the provider list immediately, so the split never depends on 077.
- 079's keep list gets the two source names from 080 - it applies from the run AFTER 080 first executes. Until then a "Delete my cache files" would drop the split, and the next load migrates the merged file back into the provider list.
- 043 defines PROXY_SRC_SECRET / PROXY_SRC_CUSTOM; the paths, merge and parser are 052; the buttons and the Source column are 080.

## Waves
- 6 mailsearch.py + keyword hits
- 7 mailsort.py + Mail Sorter panel
- 8 sentinel.py
- 9 README, one build number, delete theme.json
- 10 breach page
- 11 block re-arrangement
- 12 gate scripts, CHANGELOG, config
