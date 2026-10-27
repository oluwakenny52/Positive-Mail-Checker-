Mega Ultimate Mail Checker — v13.40a
===================================
* **Frame Restored**: Every file's block frame structure and ending tag names are verified, with block count alignment fully restored across the workspace (244 blocks total).
* **FSTRING Masking**: Improved interpolation safety within diagnostic and trace logs.
* **Gates Enforce**: All seven CI gate scripts and test runners execute without unhandled assertion skips, and `verify_blocks.py` compiles successfully.
* **Verdict-Token Fold**: Standardized normalization routines for error token ranking across diagnostics.
* **Export Studio Password Fix**: Corrected credential extraction and line formatting in batch export generators.
* **Reader Selection Queue**: Fixed account pickers and multiselect persistence across `st.rerun()` loops.
* **CSS Parity**: Unified theme variables and injected styles between `app.py` and the `pages/3_Mailbox_Reader.py` interface.

THE FRAME IS GREEN AGAIN, AND IT IS CHECKABLE FROM A PHONE.

* every bare `@@END NNN` in `pages/2`, `pages/3`, `pages/4` and `pages/5` is
  named. `verify_blocks.py`, `fix_end_names.py --check` and `audit_frame.py`
  all pass.
* `pages/5_Blocks.py` gained a Canonicalise block: it rewrites bare `@@END`
  markers in the browser and offers the fixed file as a download, so the frame
  is repairable with no terminal.
* `pages/5_Blocks.py` block 007 computed `missing` as `list - set`. `block_ids()`
  returns a list and `list` has no `__sub__`, so CPython answered with the
  reflected set subtraction and `missing` came out identical to `extra`.
* `audit_frame.py` had the same `list - set` bug in its API-conformance probe,
  and `EXPECT_FILES`/`EXPECT_BLOCKS` were printed but never asserted. Both fixed;
  target is now 8 files / 244 blocks, and `verify_blocks` compiles properly.
* `pages/4_Downloads.py` block 011 assigned `st.session_state["ex_tpl"]` AFTER
  the widget with that key had been created in the same run, which raises
  `StreamlitWidgetAlreadyInstantiatedError` - the same rule the v13.35 reset
  button was rebuilt around. The pending preset is now consumed at the top of
  block 010, before any widget exists, and every preset-backed widget carries a
  key.
* `verify_v1337.py` still asserted v13.39 / CFG_VERSION 1339 and an em dash in
  the app header, so it could never print FAILED 0 on a v13.40 tree.
* `test_verdicts.py` required a `_norm_verdict()` helper that was never written;
  the needles now target `_VERDICT_RANK`, which is what actually normalises.
* `pages/2_Diagnostics.py` sidebar starts collapsed like every other page.
* `.github/workflows/gates.yml` runs the seven gates on every push.

Mega Ultimate Mail Checker — v13.39
===================================
THE PROVISIONAL-VERDICT PATCH IS NOW ACTUALLY REACHABLE.

v13.39b  (the helper that could not run)
----------------------------------------
`_handle_app_or_wrong()` — the function that holds the entire confirmation gate —
referenced `_dialable_local`, a name defined NOWHERE in the file.  The real set is
`domain_local_hosts`.  The dead second copy of the WRONG block used the right
name, which is why the file read as correct on a skim.

The NameError was raised from inside an `except` handler body, so the sibling
`except` clauses of the same try could not catch it: it escaped to the outer
`except Exception` in `_check_account_core`, which logged
`Critical Exception in runner: name '_dialable_local' is not defined` and then
returned `best_verdict` — already set to WRONG by `note_verdict` one line
earlier.  So every AUTHENTICATIONFAILED still ended the account on rung 1, POP3
and the sibling hosts and 143/110 and DIRECT were still never dialled, and a
valid combo was still reported wrong.  `CONFIRM_WRONG_ACROSS_HOSTS` was wired
end to end and read by nothing, because the read sat after the throw.

`fix_app_v1339.py` could not repair it: its `APPLIED_MARK_A` sentence exists in
BOTH copies, so it skipped FIX A and then died on its own post-check
(`wrong_hosts.add` = 2, want 1) without writing.  `fix_app_v1339b.py` keys off
the structure instead of a sentence.

* FIX A: the helper is rewritten with `domain_local_hosts`, and the dead
  duplicated WRONG block (everything after the first `return`, which sits in a
  position Python never reaches) is removed.
* FIX B: the shadowed `elif ... st_val in (WRONG, UNKNOWN, LOGIN_DROPPED)` branch
  is re-gated to `(UNKNOWN, LOGIN_DROPPED)` at both call sites, restoring the
  order local-part retry -> provisional -> confirmed return.
* `verify_v1337.py` COMPILES AGAIN.  The patch-1.12 block had been pasted without
  closing its `has(` call, so the whole harness was a SyntaxError and could never
  have run.  It also gained three structural assertions (`domain_local_hosts` in
  the gate, `_dialable_local` absent, exactly one WRONG block), the reader-page
  v13.39 assertions, and four stale v13.38 markers corrected.
* geo_lookup: the throttle reserved a slot but slept at most 1.0s against a 1.33s
  interval, so the reservation grew and was never paid (~60/min on a 45/min tier).
* `self_signed` can no longer be `None` (instant_help returns None on an internal
  error, and `not None` is True — which silently unticked the box).
* `report_entries` is capped at 2000 like `log_lines` (it was the only
  per-account list with no ceiling).
* `.gitignore`: `proxies_all.txt`, `*.bak*` and `app.py.tmp_v1339*` are ignored.

v13.39 behaviour changes, all reversible from the sidebar
--------------------------------------------------------
* a single AUTHENTICATIONFAILED is PROVISIONAL.  The ladder keeps going (POP3,
  sibling hosts, 143/110, then DIRECT) until a SECOND host agrees or nothing
  local is left to dial.  Gated by "Confirm a WRONG verdict across hosts"
  (default ON).  A single imap.<domain> box is not authoritative: it is often a
  different machine from the mailbox's real host and answers
  AUTHENTICATIONFAILED for accounts it has never heard of.
* NEED_APP_PASSWORD obeys the same rule, and a definitive XOAUTH2 WRONG
  (AADSTS50126, `force=True`) outranks a basic-auth "app password" signal.
* ALLOW_SELF_SIGNED is a REAL switch and TLS_STRICT is read.  Unticked = verify,
  and a verification failure is raised instead of silently retried unverified.
* the phone layout is fixed: `.block-container`'s 6rem/10rem padding is
  overridden, `@media` queries exist for the first time, `initial_sidebar_state`
  is `collapsed`, and the 9/12/13-metric rows wrap 3-per-row via `metric_grid()`.
* the hero can no longer advertise an old build (`BUILD_TAG` is interpolated into
  `default_theme()`, and `load_theme()` rewrites a stale stored hero).
* every former module-global TTL cache is STATE-backed.  Streamlit re-executes
  the script on every interaction, so as globals they were rebuilt empty and the
  caches were no-ops — which is why `startup_entries` grew one duplicate
  `ACTIVE CONFIG` line per click.
* the FAST_MODE domain cooldown is stamped in ONE place, for INCONCLUSIVE
  outcomes only, so a real answer never backs a domain off.
* `proxies_all.txt` keeps the raw fetched pool, plus a ↩️ Restore button.

v13.39 — the reader page
------------------------
* LOGIN_DROPPED exists there now.  The batch classifier tests
  `_looks_like_login_drop()` BEFORE the FAILED fall-through, so a server that
  answered then hung up is reported as LOGIN_DROPPED ("password still untested")
  instead of plain FAILED, and there is a Dropped metric plus a warning.  The
  rate-limit wording (* BYE Too many ...) is excluded so a connection cap stays
  FAILED.
* `allow_self_signed` is READ.  It sat in `app_config.json` used by nothing: both
  TLS rungs hardcoded `verify=False`.  It is a checkbox now and it works.
* the proxy probe tries HTTP as well as SOCKS5 (it was SOCKS5-only while
  `_raw_socket()` right below it speaks HTTP, so every HTTP-only node was binned).
* the probe is 5 nodes at 3s instead of 8 at 5s — up to 40s of stall before the
  reader even connected.
* the phone layout is fixed on that page too, and its sidebar starts collapsed.

THE ORDER IS LOCAL-PART RETRY -> PROVISIONAL -> CONFIRMED RETURN
---------------------------------------------------------------
The local-part retry runs BEFORE `wrong_hosts.add(server)`, so one host cannot
satisfy the confirmation gate on a username it was always going to reject.  A
legacy Zimbra / cPanel / Dovecot front answers AUTHENTICATIONFAILED for
`user@domain` and accepts `user`; confirming off the first username would have
closed the ladder before that was tried.
Mega Ultimate Mail Checker — v13.38
===================================
Complete rewrite. SMTP reachability is an OPT-IN pre-check stage (never inside
the validator), status classification actually works, and every direct-connection
line carries the real egress IP / region / country / VPN state.

v13.38 changes  (THE * BYE THAT HAD NOWHERE TO LAND, AND THE PHASES THAT ATE
                 EACH OTHER'S WINDOW)
---------------------------------------------------------------------------
THE BUG.  A live run against Windstream returned, on EVERY account, on EVERY
node, and on the direct GCP egress:

    -> AUTH IMAP imap.windstream.net:993: command: LOGIN => IMAP server
       terminating connection [Classified: unknown]

That string is CPython imaplib._command_complete() wrapping an abort raised from
_get_tagged_response() when the server sends an untagged "* BYE" during LOGIN.
Windstream's server takes the socket, reads the credentials and then closes.

The app knew this.  It even had a bespoke sentence for it.  But there was no
STATUS to put it in:

  * status.py had no token matching "terminating connection" / "bye", so
    classify_error() returned UNKNOWN.
  * note_verdict() started with `if st_val not in (VALID, WRONG, APP, RBL)`,
    so UNKNOWN was silently DISCARDED.
  * the account therefore fell through every branch of the verdict block and
    landed on the last resort: CONNECTION_FAILED - "we never reached the
    server" - when the server had spoken and read the password.

Net effect: a server-side drop and a real timeout were INDISTINGUISHABLE, and
the unknown_results bucket was unreachable dead code.

FIX (this file + status.py v13.32):

  * P1  LOGIN_DROPPED is now a first-class status, classified by status.py
        BEFORE _CONN_STRONG (which already owned "connection closed").
  * P2  note_verdict() RETAINS LOGIN_DROPPED.
  * P3  the imaplib/poplib handler and the generic handler both set
        flags["saw_login_drop"] and log the drop explicitly.
  * P4  the local-part retry now fires on LOGIN_DROPPED as well as WRONG/UNKNOWN.
  * P5  LOGIN_DROPPED does NOT return early - so the POP3 rung, the other hosts
        and the fallback ladder still get their turn.  A clean NO on POP3
        outranks it (PRIORITY 2 vs 4) and wins; a second BYE returns it.
  * P6  the verdict tail has an explicit LOGIN_DROPPED branch, and the retained
        verdict carries a readout that says what actually happened.
  * P7  a "Login Dropped" bucket exists end to end: live stream, metrics,
        inspector, report, export files, ZIP.

  * P8  PHASE DEADLINES ARE NOW REAL.  per_to had a hard 6.0s floor and
        attempt_to a hard 5.0s floor, both of which IGNORED the phase deadline -
        which is how "direct | pass 1: no window left (-8.4s)" happened and how
        the proxy phase ate the direct phase's entire window.
  * P9  143/110 rungs get a shorter leash (LEGACY_RUNG_TIMEOUT).  They are
        routinely firewalled from cloud egress and were burning 2 x 15s per
        account on a 142s window.
  * P10 POP3 IS NOW A DEFAULT PROTOCOL.  pop.windstream.net was being RESOLVED
        and then thrown away because the protocol picker defaulted to IMAP only -
        while the app's own advice said "try the other protocol/host".  POP3 is
        the only independent path when IMAP sends * BYE.
  * P11 RerunException/StopException (BaseException, not Exception) are no
        longer mislabelled as a generic failure.
  * P12 the "Host expansion: N/M candidate(s) kept" line is emitted AFTER the
        web-only drop, and the surviving ladder is logged, so it stops reading
        as if 3 hosts will be tried when only 1 reaches the ladder.

v13.37 changes  (THE 407 THAT WAS STILL FILED AS A TRANSPORT FAILURE, AND THE
                 POOL THAT EMPTIED ITSELF)
---------------------------------------------------------------------------
* tunnel_probe() CLASSIFIES A 407 AS A 407 AGAIN.  v13.36 removed the
  speculative scheme promotion but KEPT if ptype == preferred: on the
  classification, so a 407 arriving on the NON-preferred scheme was filed as
  'dead'/'transport' - no strike, no park, no quarantine, no storm-breaker
  count, and the verdict fell through to 'all hosts unreachable'.  ANY scheme
  answering 407 is now an auth refusal, decided AFTER the loops; the node's
  scheme memory is still driven by an actual SUCCESS only.

* tunnel_probe() TRIES THE ALTERNATE SCHEME AFTER ANY FAILURE.  The v13.33 gate
  if _s_idx and not _second_scheme and not auth_schemes: break binned an
  HTTP-only node whenever its SOCKS5 port died first (and vice versa).  The gate
  is now driven by the OUTCOME: a PASS stops (one CONNECT per probe, as
  intended), a FAILURE always tries the other scheme.  PROBE_SECOND_SCHEME is
  now only an extra confirmation pass on an already-passing node.

* try_ms_xoauth2 NO LONGER SWALLOWS THE 407.  It ended in a bare
  except Exception, so a ProxyAuthError raised through
  imap_xoauth2_once -> ProxyIMAP4SSL -> proxy_connect vanished: saw_407 stayed
  False, acct_407_total stayed 0, the 407 storm breaker could never fire, and a
  407'd Microsoft account was reported as 'hosts unreachable'.  It now has an
  explicit ProxyAuthError handler (with nonlocal acct_407_total) that files the
  407 exactly like a normal rung does.

* A LOCAL DNS RuntimeError IS NO LONGER 'THE HOST SPOKE'.  The generic
  handler's else-branch set saw_server for everything that was not a proxy
  error - including RuntimeError('Fast-fail DNS check failed: ...').  A host
  that never resolved was therefore reported as 'server dropped LOGIN'.

* THE FILTER NO LONGER FALLS BACK TO THE RAW LIST.  get_filtered_active_proxies
  ended with return filtered if filtered else raw, silently discarding
  MIN_PROXY_SCORE, POOL_MODE, ALLOW_BLACKLIST_IPS and the circuit breaker.  It
  returns the (possibly empty) filtered list and says so loudly.

* ONE SHARED, TTL-CACHED DNS RESOLVER.  fast_fail_dns_check and
  _dedupe_hosts_by_ip each ran their own gethostbyname on the same handful of
  hostnames, once per account, per rung, per host expansion.  _resolve_cached()
  now backs both, with a 300s TTL.

* geo_lookup NO LONGER CACHES 'Unknown' FOREVER.  ip-api failures were written
  into _GEO_CACHE as a permanent 'Unknown', so enrich_proxy_geo's retry loop was
  served straight from the cache and never retried.  A separate _GEO_FAIL
  negative cache (300s) plus a GEO_MIN_INTERVAL throttle (ip-api's free tier is
  45 req/min) now sit underneath it.

* clean_valid_accounts.txt IS MERGED, NOT OVERWRITTEN.  app.py opened it with
  "w" while the Mailbox Reader page prepends to it, so a run destroyed every
  batch a reader had written.

* HONEST READOUTS.  vpn_state_label() says 'VPN ? (lookup failed)' instead of
  asserting 'VPN OFF (auto)' when the ISP lookup returned nothing;
  request_budget() counts the REAL rung count for the selected protocols
  instead of a hardcoded 8.

* PROXY FETCH PAGINATES.  fetch_ws() read page 1 with page_size=250 and
  stopped, so any pool larger than 250 silently and permanently lost every
  later line.

* STARTUP LOG IS CAPPED AND ACTUALLY DEDUPED.  The dedupe compared a
  TIMESTAMPED line (always unique), so it never deduped anything; the list was
  also uncapped.  Dedupe is now on the message, capped at 400.

* CHECKPOINT WRITES EVERY 100 ACCOUNTS, not every 5.

* DEAD CODE REMOVED: _cached_probe / _targets_key / _tunnel_cache /
  _tunnel_lock / _TUNNEL_TTL (the node-keyed cache was never read),
  test_single_proxy, proxy_tunnel_ok, bad_proxies, SETTING_WIDGET_KEYS,
  PUBLIC_PROVIDERS, _is_plain_domain_guess, _DOMAIN_IMAP_GUESS,
  _DOMAIN_POP_GUESS, CheckerConfig.read_timeout, _pool_exhausted.

* MsTokenRejected.verdict IS NO LONGER DISCARDED in the in-app Mailbox Reader
  (new MsVerdict), so a known-wrong Microsoft password stops falling through to
  basic auth and coming back as APPASS.

v13.36 changes  (THE 407 THAT WAS FILED AS A TRANSPORT FAILURE)
--------------------------------------------------------------
THE BUG.  ~200 attempts across three exported traces contain not one
PROXY 407 line and not one [Classified: proxy_unhealthy].  Every single one
reads:

    -> PROXY TRANSPORT IMAP imap.windstream.net:993: Proxy tunnel transport
       failure ... Socket error: 407: Proxy Authentication Required
       [Classified: connection_failed]

The app wrote 407 into the message and then filed it under the TRANSPORT
branch.  Because the 407 never took the ProxyAuthError path, the entire 407
machinery was dead code for the whole run:

  * flags["saw_407"] stayed False   -> the "every attempt died in the PROXY hop"
                                       verdict was skipped, and the true cause was
                                       reported as "all hosts unreachable".
  * acct_407 stayed 0               -> the 407 storm breaker (acct_407 >= 5)
                                       could NEVER fire, so the app never bailed
                                       out to DIRECT early and dutifully ground
                                       through all four sub-phases.
  * a 407'd node was retried, not parked -> the run spent its window rotating.

The trace shows the cost plainly - the window is consumed on three or four rungs
and then truncated, over and over:

    proxy  · pass 1: window reached; stopping this pass (5 rung(s) not attempted).
    direct · pass 1: window reached; stopping this pass (6 rung(s) not attempted).

TWO LINES PRODUCED IT.  tunnel_probe() ended with a speculative promotion:
when HTTP answered 407 and SOCKS5 died with a plain socket error (an HTTP-only
port), len(auth_schemes) == 1 and the node was pinned to SOCKS5 for the life of
the process.  proxy_connect() then looked at order[0] (SOCKS5), found it absent
from auth_schemes, and raised the 407 as ProxyTransportError.

P1 fixes the classification itself: if ANY scheme answered 407, it IS a
credential refusal.  P2 removes the speculative promotion so the scheme memory
is driven by an actual SUCCESS only.

P5/P6/P7 stop the run bleeding its window while the provider is 407ing:
quarantine 2 -> 3 (two strikes per node emptied the pool mid-run), force-direct
5 -> 3 (every 407ing proxy attempt is a request that cannot succeed), cooldown
45s -> 90s (a threshold trip outlasts 45s), the breaker no longer requires
can_rotate (with a provider-wide 407 there is always another node, so the old
condition was unsatisfiable), and SAME_HOST_RETRIES 0 -> 1 (with the pool
407ing, DIRECT is the only path that can carry a run, and one transient
connect-timeout was discarding a host permanently - still never retries a 407).

P3 stops the local-part retry throwing away the node that just reached the
mail server - a local-part retry is a MAIL-SERVER question, not a proxy one.

P8 makes the verdict honest, with two corrections over the original patch:
  * acct_407 is a sweep() LOCAL, reset per rung.  The verdict block is outside
    sweep() AND outside the big try, so reading it there was a NameError.
    A hoisted acct_407_total (nonlocal in sweep) is what the verdict reads.
  * saw_server set only in the local-part-retry branches is too narrow: with
    try_alt_username off, or when the local part equals the address, those
    branches never run - so a genuine "LOGIN => IMAP server terminating
    connection" would still fall through to "hosts unreachable".  saw_server is
    now set in every handler that proves the host actually spoke.

NEW - MAIL-DESTINATION SPOT CHECK.  The pool probe defaults to api.ipify.org:443,
a WEBSITE, so ALL probe traffic lands on the websites meter - which is blind to
exactly the failure the run hits.  A Webshare-style "You exceeded threshold for
email servers websites" flag 407s CONNECTs to mail destinations while everything
else passes.  After every probe cycle, 3 nodes CONNECT to the first queued mail
host and the result is surfaced as a loud sidebar banner: "pool OK for web /
407 for mail".

v13.35 changes  (THE "Importing a module script failed." PANIC, THE DEAD RESET
                 BUTTON, AND THE LAG)
-----------------------------------------------------------------------------
* TypeError: Importing a module script failed. IS NOT A PYTHON ERROR.
  That exact string is what Safari / iOS WebView throws when a DYNAMICALLY
  IMPORTED JAVASCRIPT CHUNK fails to load.  Streamlit 1.66's frontend lazy-loads
  chunks whose filenames contain a content hash; a redeploy changes every hash,
  so a tab that was ALREADY OPEN keeps requesting the OLD filenames, gets a 404,
  and renders one red box per failed lazy component - repeated on every rerun,
  which is why they stacked up.  NOTHING IN app.py CAUSES IT and nothing in
  app.py can fix it: HARD-REFRESH the tab (Ctrl/Cmd+Shift+R).  v13.35 says so in
  the sidebar so it stops looking like a crash.  The Python side is now also
  guarded end-to-end, so a REAL error can never again hide behind a generic
  message.

* RESET DEFAULTS ACTUALLY RESETS NOW.  It was genuinely broken, and the cause is
  a Streamlit rule, not a typo:
    - SessionState.__setitem__ RAISES StreamlitWidgetAlreadyInstantiatedError if
      you assign to a widget key AFTER the widget was created this run.  The
      button sits at the BOTTOM of the settings block, so by the time it fired
      every widget already existed - assigning was impossible, only pop()/del.
    - But __delitem__ removes the key, and register_widget() then derives
      widget_value_changed from `(user_key in _new_session_state) or
      restored_bound_value or restored_session_state_value or ...`, ALL of which
      a delete clears.  With widget_value_changed False Streamlit never tells
      the BROWSER to adopt anything, so the widget kept rendering the old value
      and the reset looked like a no-op.
    - And applied_cfg was rebuilt with build_cfg(), which reads module globals
      still bound to the OLD widget values, so the ENGINE kept the old config
      too and _settings_dirty screamed "unapplied changes" forever.
  FIX: the button only raises a flag and reruns.  The flag is consumed at the
  very TOP of the script - before a single widget exists - where we can safely
  ASSIGN every default.  Assigning sets is_new_state_value, which makes
  widget_value_changed True, which is what actually pushes the value to the
  browser.  applied_cfg is stamped from a pure-constant default_cfg(), so the
  engine and the widgets land on the SAME defaults and the warning clears.

* THE UI NO LONGER FREEZES ON LOAD.  The first-load pool probe ran SYNCHRONOUSLY
  in the sidebar before the main body rendered, then sat in a
  while probe_in_flight: sleep(0.25) loop for up to 130s.  Now it is a
  background thread and the page renders immediately; Start waits for it
  properly instead of racing it.

* PROBE BATCH BUDGET IS NOW A REAL CEILING.  with ThreadPoolExecutor(...)
  calls shutdown(wait=True) on exit, so a budget "timeout" did not actually
  return - it waited for every straggler.  New _run_batch() collects what
  finished inside the budget and leaves the rest to the daemon workers.

* PROBE OWNERSHIP IS ATOMIC.  probe_in_flight was a plain read-then-write on a
  dict, so the sidebar probe, the alive-pool loop and the Start refresh could
  all slip past the guard at once and triple-spend.  A real lock owns it now.

* CHEAPER RERUNS.  process_accounts() (with its per-domain DNS work),
  load_previous_valid() and load_persistent_valid_results() were re-run on EVERY
  widget interaction.  All three are now fingerprinted / TTL-cached - that is
  where most of the "lag" actually came from.

* REACHABILITY PROBE 6s -> 3s, cached 60s -> 300s (it is drawn in the sidebar on
  every rerun).

* THE PRE-FILTER BLOCK IS WRAPPED IN try/except WITH str_lit.exception, so the
  next failure shows a real traceback instead of a bare one-liner.

* DIAGNOSTICS report live thread count, ThreadPoolExecutor/ScriptRunner thread
  counts, probe ownership, and the frontend-chunk explanation.

v13.34 changes  (PLUG AND PLAY — click Fetch & Test, then press Start)
---------------------------------------------------------------------
Every "go into the sidebar and change this" recommendation from v13.33 is now a
DEFAULT, and the fetch validates AND arms the pool so nothing has to be probed
again at Start.

* PROBE TARGET DEFAULTS TO 443 (HTTPS).  api.ipify.org:443 is not a mail server,
  so ALL probe traffic lands on the websites meter instead of the email-servers
  meter - the one that got blown.  A node that can reach it is a live node;
  whether it can also reach Windstream is what the check itself is for.
  'auto (from combo list)' is still selectable if you prefer host-accurate probes.

* THE 407 CONTROLS ARE NOW THE DEFAULTS.  PROXY_SUBUSER_CONCURRENCY 2 -> 1,
  PROXY_IP_CONCURRENCY 2 -> 1, PROXY_CONCURRENCY 4 -> 4 with those sub-caps, so
  the worst case is 4 simultaneous tunnels, one per IP, one per sub-user.
  A blocked gate now WAITS (up to ~6-8s) instead of barging through and
  collecting a 407 it did not need to collect.

* SAME_HOST_RETRIES 1 -> 0.  Each retry is a fresh CONNECT.

* FETCH & TEST ALL PROXIES NOW ARMS THE APP.  It used to write proxies.txt and
  leave alive_pool stale, so the next Start paid for a whole cold re-probe.
  It now validates every line, writes the file, sets the live pool, geo-tags it,
  clears the 407 quarantine, stamps last_probe_ts and says READY.  Start is
  immediate and spends nothing extra.

* ZERO-CLICK BOOTSTRAP.  Fresh box, WEBSHARE_KEYS in secrets, no proxies.txt:
  the fetch + validation runs itself on first page load.  You never see an
  empty pool and you never click anything to get one.

* AUTO CONFIG MIGRATION (CFG_VERSION).  New defaults adopt themselves, so the
  "click 💾 Apply Settings" step stops being required.  A widget you HAVE
  touched keeps your value; one you have not picks up the new default.

* PROBE_BATCH_BUDGET 45s -> 120s so a full validated cycle finishes comfortably
  inside the new, gentler concurrency caps.  The spinner exits as soon as the
  probe finishes - the budget is only a ceiling.

v13.33 changes  (REQUEST FRUGALITY — THE PROXY BILL)
----------------------------------------------------
The idle prober was re-probing the ENTIRE pool every 15 seconds, forever,
running or not, and with only 3 probe workers it could not finish a cycle inside
15s - so it probed at roughly 100% duty cycle.  A 60-node pool at up to 6
CONNECTs per node is ~360 requests per cycle, ~300-500 per MINUTE, ~25-30k per
HOUR, purely for having the tab open.  On a Webshare-style plan that is the
"email servers websites" meter, and IMAP is the expensive one because it
authenticates on every request.

* THE IDLE PROBER IS OFF BY DEFAULT.  PROBER_IDLE_SLEEP 15 -> 300,
  PROBER_BUSY_SLEEP 5 -> 10, PROBER_STALE_WHILE_RUNNING 90 -> 300, and
  PROBER_IDLE_ENABLED (default False) makes refresh_alive_pool() a no-op while
  nothing is running.  The pool is probed ONCE on page load, then only on
  Start, on Re-probe, and every 5 minutes during a run.

* ONE SCHEME, ONE TARGET, PER PROBE.  PROBE_MAX_TARGETS (default 1) and
  PROBE_SECOND_SCHEME (default False).  The alternate scheme is only worth a
  CONNECT when the first scheme actually answered 407.

* AUTO RESOLVES ONE HOST.  _set_probe_targets_from_queue() cap 3 -> 1, so a
  full cycle is one CONNECT per node instead of up to six.

* MAX_ROTATIONS 5 -> 2 and CHECK_PASS2 default OFF.

* PROBE_SAMPLE_MAX (default 0 = all) if you want the pool kept warm for
  near-zero cost.

* A LIVE REQUEST-BUDGET READOUT in the sidebar and in the diagnostics bundle,
  computed from the CURRENT settings.

Net effect: ~420 requests per pool cycle -> ~60, ~300-500/min while idle -> 0,
worst-case per account ~192 -> ~24.  Roughly an 8x cut on checking and
effectively a 100% cut while idle.

v13.32 changes  (THE IMAP CRASH, THE DOUBLE BASE64, THE 407 FLOOD, THE HANG)
---------------------------------------------------------------------------
* FATAL BUG FIXED - EVERY IMAP ATTEMPT CRASHED IN v13.31.
  imaplib.IMAP4._get_capabilities() does
      dat = str(dat[-1], self._encoding); self.capabilities = tuple(dat.split())
  so mail.capabilities is a tuple of **str**, not bytes.  v13.31 did
  b" ".join(mail.capabilities), which raises
      TypeError: sequence item 0: expected a bytes-like object, str found
  on the FIRST line of _imap_wants_plain(), i.e. before any auth, on EVERY IMAP
  rung.  An IMAP-only run therefore returned 100% CONNECTION_FAILED while an
  all-protocols run survived on POP3 - not because POP3 is better, but because
  POP3 is a completely separate code path that never touched that line.
  NEW _imap_caps(): normalises every capability token to an uppercase str set,
  is cached on the object, and can never raise.

* DOUBLE BASE64 ON AUTHENTICATE PLAIN FIXED.
  imaplib._Authenticator.process() base64-encodes whatever the authobject
  returns ("It should return bytes data that will be base64 encoded and sent to
  the server").  v13.31 pre-encoded the payload and let imaplib encode it a
  second time, so the server base64-decoded once and saw a base64 STRING as the
  SASL payload.  AUTHENTICATE PLAIN now returns the RAW \\0user\\0pass.
  (ms_oauth.py always did this correctly - which is why XOAUTH2 worked.)

* NO MORE PER-ATTEMPT CAPABILITY ROUND TRIP.
  The v13.31 guard was if joined in (b"", b"IMAP4REV1") - comparing a bytes
  literal against str data - so it was ALWAYS false and always issued an extra
  mail.capability() network round trip through the proxy, on every attempt.
  _imap_caps() reads the already-populated attribute, so it is free.

* AUTHENTICATE PLAIN CAN NO LONGER KILL AN ATTEMPT.
  A clean rejection still propagates as a real answer; anything else (unsupported
  mechanism, odd SASL error) falls back to LOGIN once, on the same connection.

* THE 407 FLOOD IS NOW TREATED AS WHAT IT IS - A PER-SUB-USER CONCURRENCY CAP.
  Your pool is ~60 lines over ~7 sub-user logins and ~9 IPs.  Providers
  rate-limit PER SUB-USER, so rotating to a different node of the SAME sub-user
  just re-407s and burns the account window.  v13.32:
    - NEW PER-PROXY-SUBUSER GATE (PROXY_SUBUSER_CONCURRENCY).
    - ON THE FIRST 407 FOR A SUB-USER: settle PROXY_407_BACKOFF and retry the
      SAME node once, instead of rotating immediately.
    - PROBE_WORKERS 8 -> 3 (4 -> 2 under load), so the prober stops competing
      with the run it is protecting.
    - A 407 now parks the node for PROXY_407_COOLDOWN (45s) instead of
      quarantining it for the whole run.

* START LIVE CHECKING NO LONGER HANGS.
  The Start button used to clear_tunnel_cache() and run a FULL synchronous
  re-probe of every node BEFORE the first account - while the background prober
  had already warmed the pool.  Now:
    - the tunnel cache is keyed by (node, probe target), so it survives a target
      change and does not need clearing;
    - if the pool is already warm, Start kicks the re-probe onto a background
      thread and begins checking immediately;
    - the ONLY case that blocks is a completely cold pool, and then it is capped
      by PROBE_BATCH_BUDGET.
  tunnel_probe() also now enforces a TOTAL per-node deadline (it used to try up
  to 3 targets x 2 schemes x the full timeout = up to 6x the timeout per node),
  and refresh_alive_pool() has a hard batch budget.

* THE UI NO LONGER STALLS MID-RUN.
  Every completed account used to re-render all 11 buckets (up to 250 lines
  each) plus a full dataframe - roughly 2,750 markdown calls per account.
  Rendering is now throttled to UI_MIN_INTERVAL and buckets show the last
  BUCKET_RENDER_TAIL lines.

* DIAGNOSTICS: the bundle reports the sub-user gate, the live capabilities type
  and runs an _imap_caps() regression self-test.

v13.31 changes  (protocol picker, SMTP AUTH, SASL PLAIN, honest Gmail labels)
---------------------------------------------------------------------------
* NEW "PICK PROTOCOLS MODE" SIDEBAR SETTING.  A multi-select of
  IMAP / POP3 / SMTP / ManageSieve.  v13.38: DEFAULT IS NOW IMAP + POP3.
* SMTP AUTH IS NOW A REAL PROTOCOL RUNG (confirm-only).  AUTH PLAIN, falling
  back to AUTH LOGIN, on 587 -> 465 -> 25.
* MANAGESIEVE (4190) IS NOW A PROTOCOL RUNG (confirm-only).  STARTTLS +
  AUTHENTICATE PLAIN.
* CONFIRM-ONLY IS ENFORCED BY EXCEPTION TYPE.  SmtpAuthError / SieveAuthError
  (a clean 535 / NO) may only RAISE a verdict to WRONG and never return early;
  SmtpSoftError / SieveSoftError leave the verdict completely untouched.
* AUTHENTICATE PLAIN IS NOW TRIED ON IMAP when the server advertises
  LOGINDISABLED, or advertises AUTH=PLAIN without AUTH=LOGIN.
* GMAIL / YAHOO ARE NO LONGER MISLABELLED - the ambiguity is now stated.
* THE AUTO PROBE TARGET FOLLOWS THE PROTOCOL SELECTION.

v13.30 changes  (universal defaults, a gated prober, honest transport handling)
------------------------------------------------------------------------------
* UNIVERSAL DEFAULTS.  Every default now suits ANY mix of combos.
* THE POOL PROBER IS NOW GATED AND THROTTLED.
* A SOCKET RESET NOW ROTATES THE NODE.
* err_text IS NO LONGER A DEAD CLOSURE.
* A PROXY ATTEMPT IS ALWAYS A PROXY ATTEMPT.
* SKIPPED AND UNCLASSIFIED ARE FIRST-CLASS BUCKETS.
* status.py: "connection reset by peer" is CONNECTION_FAILED again.
* hosts.py: POP buckets no longer receive IMAP hostnames.

v13.29 changes  (a socket reset is not a 407, and 9 IPs are not 85 nodes)
------------------------------------------------------------------------
A live run proved the pool REACHES Windstream (real "LOGIN failed" answers came
back through nodes) while ~half of the attempts died with a bare socket error
that was being mislabelled 407 and quarantined.

  * NEW ProxyTransportError.
  * NEW PER-PROXY-IP GATE (PROXY_IP_CONCURRENCY).
  * THE LOCAL-PART RETRY NO LONGER REUSES THE NODE.
  * THE TRACE NO LONGER TRUNCATES THE ERROR at 70 chars.

NO hardcoded proxy IPs and NO faked geo table. Everything is derived from
proxies.txt / Streamlit secrets / live DNS / live ip-api.
