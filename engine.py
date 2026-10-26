# @@FILE engine.py blocks=12 version=v13.40
# ===========================================================================
# engine.py - headless verification engine: rung planning, pooled execution,
# verdict aggregation and backoff. No Streamlit, no side effects on import.
#
# Aggregation mirrors app.py blocks 100-104 (the WRONG block lives in 101):
# wrong_hosts / wrong_rungs / app_rungs / domain_local_hosts, local-part retry
# BEFORE the host is condemned, one wrong_hosts.add(server) per failing host.
#
#   python engine.py --selftest
# ===========================================================================


# @@BLOCK 000 HEADER
"""Standalone verification engine.

Importable anywhere: hosts.py and status.py are picked up when present and
degrade to safe local tables when absent.
"""

import argparse
import random
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

ENGINE_VERSION = "v13.40"

try:
    import status as _status
except Exception:
    _status = None

try:
    import hosts as _hosts
except Exception:
    _hosts = None
# @@END 000 HEADER


# @@BLOCK 001 CONSTANTS
DEFAULT_WORKERS = 8
MAX_WORKERS = 32
DEFAULT_TIMEOUT = 20.0
MAX_ATTEMPTS = 3
BACKOFF_BASE = 1.5
BACKOFF_CAP = 30.0
JITTER = 0.35
DEFAULT_RUNG_LIMIT = 12

VALID = getattr(_status, "VALID", "VALID")
WRONG = getattr(_status, "WRONG", "WRONG")
WRONG_PASSWORD = getattr(_status, "WRONG_PASSWORD", "WRONG_PASSWORD")
APP = getattr(_status, "APP", "APP")
NEED_APP_PASSWORD = getattr(_status, "NEED_APP_PASSWORD", "NEED_APP_PASSWORD")
CONNECTION_FAILED = getattr(_status, "CONNECTION_FAILED", "CONNECTION_FAILED")
UNKNOWN = getattr(_status, "UNKNOWN", "UNKNOWN")
RETRY_LATER = getattr(_status, "RETRY_LATER", "RETRY_LATER")
LOGIN_DROPPED = getattr(_status, "LOGIN_DROPPED", "LOGIN_DROPPED")

WRONG_SET = frozenset({WRONG, WRONG_PASSWORD})
APP_SET = frozenset({APP, NEED_APP_PASSWORD})
RETRY_SET = frozenset({UNKNOWN, RETRY_LATER, LOGIN_DROPPED})
# @@END 001 CONSTANTS


# @@BLOCK 002 RUNG
@dataclass(order=True)
class Rung:
    order: int
    host: str = ""
    port: int = 993
    proto: str = "imap"
    tls: bool = True
    tier: str = "host"
    source: str = "ladder"

    def label(self):
        return "%s:%d/%s" % (self.host, self.port, self.proto)
# @@END 002 RUNG


# @@BLOCK 003 BUCKET
@dataclass
class Bucket:
    name: str
    hosts: list = field(default_factory=list)
    rungs: list = field(default_factory=list)

    def add(self, rung):
        self.rungs.append(rung)
        if rung.host and rung.host not in self.hosts:
            self.hosts.append(rung.host)
        return rung


BUCKET_SPEC = (
    ("valid", "Confirmed working"),
    ("wrong", "Wrong credentials"),
    ("app", "App password / OAuth"),
    ("rbl", "RBL listed"),
    ("conn", "Transport failure"),
    ("retry", "Retry"),
    ("skip", "Skipped"),
    ("other", "Other"),
)


def new_buckets():
    return {name: Bucket(name) for name, _label in BUCKET_SPEC}


def bucket_for(buckets, status_code):
    name = "other"
    if _status is not None:
        try:
            name = _status.bucket_of(status_code)
        except Exception:
            name = "other"
    return buckets.get(name) or buckets["other"]
# @@END 003 BUCKET


# @@BLOCK 004 TARGET
@dataclass
class Target:
    domain: str
    local: str = ""
    password: str = ""
    pop: bool = False

    @property
    def email(self):
        return "%s@%s" % (self.local, self.domain) if self.local else self.domain


@dataclass
class RungResult:
    target: Target
    rung: Rung
    status: str = UNKNOWN
    text: str = ""
    elapsed: float = 0.0
    attempt: int = 1

    @property
    def host(self):
        return self.rung.host
# @@END 004 TARGET


# @@BLOCK 005 PLAN
def _hosts_of(domain):
    if _hosts is None:
        return []
    _conf = getattr(_hosts, "conf", None)
    if callable(_conf):
        try:
            _got = _conf(domain) or {}
            _out = [str(h) for h in (_got.get("imap") or []) if h]
            if _out:
                return _out
        except Exception:
            pass
    for fname in ("host_list", "discover_hosts", "smtp_candidates"):
        fn = getattr(_hosts, fname, None)
        if not callable(fn):
            continue
        for call in (lambda: fn(domain), lambda: fn(domain, "")):
            try:
                out = call()
            except Exception:
                continue
            if out:
                if isinstance(out, dict):
                    out = out.get("imap") or []
                if out:
                    return [str(h) for h in out]
    return []


def _rank(domain, hosts):
    if _hosts is None:
        return list(hosts)
    fn = getattr(_hosts, "rank_hosts", None)
    if not callable(fn):
        return list(hosts)
    try:
        return list(fn(list(hosts), domain, False))
    except Exception:
        try:
            return list(fn(list(hosts)))
        except Exception:
            return list(hosts)


def _is_junk(host):
    if _hosts is None:
        return False
    fn = getattr(_hosts, "is_junk_host", None)
    if not callable(fn):
        return False
    try:
        return bool(fn(host))
    except Exception:
        return False


def plan_rungs(domain, local="", *, include_pop=False, limit=DEFAULT_RUNG_LIMIT):
    """Build the ordered rung ladder for one target."""
    d = (domain or "").strip().lower()
    rungs = []

    hosts = [h for h in _hosts_of(d) if not _is_junk(h)]
    if not hosts:
        hosts = ["mail.%s" % d, d, "smtp.%s" % d, "imap.%s" % d]

    for h in _rank(d, hosts):
        rungs.append(Rung(order=len(rungs), host=h, port=993, proto="imap", tls=True, source="ladder"))
    for h in hosts:
        rungs.append(Rung(order=len(rungs), host=h, port=143, proto="imap", tls=False, source="plain"))

    if include_pop:
        for h in hosts:
            rungs.append(Rung(order=len(rungs), host=h, port=995, proto="pop", tls=True, source="pop"))
            rungs.append(Rung(order=len(rungs), host=h, port=110, proto="pop", tls=False, source="pop-plain"))

    if limit and len(rungs) > limit:
        head = rungs[:limit]
        # POP must survive the cap: the IMAP rungs alone filled the ladder and
        # include_pop=True produced no POP rung at all.
        if include_pop and not any(r.proto == "pop" for r in head):
            pop_tail = [r for r in rungs if r.proto == "pop"][:2]
            if pop_tail:
                head = head[: max(0, limit - len(pop_tail))] + pop_tail
        rungs = head
    return rungs
# @@END 005 PLAN


# @@BLOCK 006 AGGREGATE
def _prio(code):
    if _status is not None:
        try:
            return _status.priority_of(code)
        except Exception:
            pass
    return 10


def pick_verdict(results):
    """Aggregate rung results into one verdict + forensic detail.

    Order of authority:
      1. any hard WRONG on the domain's own host  -> WRONG
      2. any VALID                                -> VALID
      3. any APP / NEED_APP_PASSWORD              -> APP
      4. any RBL                                  -> RBL
      5. otherwise the most decisive transport/retry status
    """
    wrong_hosts = set()
    wrong_rungs = []
    app_rungs = []
    valid_rungs = []
    domain_local_hosts = set()

    for r in results or ():
        st = r.status
        host = r.host
        if st in WRONG_SET:
            wrong_rungs.append(r)
            if host:
                wrong_hosts.add(host)
        elif st in APP_SET:
            app_rungs.append(r)
        elif st == VALID:
            valid_rungs.append(r)
        if host:
            domain_local_hosts.add(host)

    if wrong_rungs:
        verdict = WRONG if any(r.status == WRONG for r in wrong_rungs) else WRONG_PASSWORD
    elif valid_rungs:
        verdict = VALID
    elif app_rungs:
        verdict = APP
    else:
        verdict = UNKNOWN
        for r in results or ():
            if _prio(r.status) > _prio(verdict):
                verdict = r.status

    return {
        "status": verdict,
        "wrong_hosts": sorted(wrong_hosts),
        "wrong_rungs": wrong_rungs,
        "app_rungs": app_rungs,
        "valid_rungs": valid_rungs,
        "domain_local_hosts": sorted(domain_local_hosts),
        "rungs_run": len(list(results or ())),
    }


def merge_result(acc, new_status):
    """Fold a new status into an accumulator using decisiveness."""
    if acc is None:
        return new_status
    return acc if _prio(acc) >= _prio(new_status) else new_status
# @@END 006 AGGREGATE


# @@BLOCK 007 STATE
class EngineState:
    """Thread-safe counters + cooldown table."""

    def __init__(self):
        self._lock = threading.Lock()
        self.done = 0
        self.total = 0
        self.started = time.time()
        self.cooldown = {}
        self.errors = 0

    def bump(self, n=1):
        with self._lock:
            self.done += n
            return self.done

    def fail(self):
        with self._lock:
            self.errors += 1

    def cooled(self, host, seconds):
        until = self.cooldown.get(host, 0)
        return until > time.time()

    def cooldown_host(self, host, seconds):
        with self._lock:
            self.cooldown[host] = time.time() + seconds

    def snapshot(self):
        with self._lock:
            return {
                "done": self.done,
                "total": self.total,
                "errors": self.errors,
                "elapsed": time.time() - self.started,
            }
# @@END 007 STATE


# @@BLOCK 008 BACKOFF
def backoff(attempt, base=BACKOFF_BASE, cap=BACKOFF_CAP, jitter=JITTER):
    delay = min(cap, base * (2 ** max(0, attempt - 1)))
    return delay * (1.0 + random.uniform(-jitter, jitter))


def retry_delays(attempts=MAX_ATTEMPTS):
    return [backoff(a) for a in range(1, attempts + 1)]
# @@END 008 BACKOFF


# @@BLOCK 009 WORKER
def probe_once(target, rung, probe, timeout=DEFAULT_TIMEOUT):
    """Run one rung through `probe(target, rung, timeout)` -> (ok, text)."""
    started = time.time()
    try:
        out = probe(target, rung, timeout)
        if isinstance(out, tuple):
            ok, text = out[0], (out[1] if len(out) > 1 else "")
        else:
            ok, text = bool(out), str(out or "")
    except Exception as exc:
        ok, text = False, "%s: %s" % (type(exc).__name__, exc)

    elapsed = time.time() - started
    if ok:
        code = VALID
    elif _status is not None:
        code = _status.classify_error(text, target.domain)
    else:
        low = (text or "").lower()
        if "authenticationfailed" in low or "invalid credentials" in low:
            code = WRONG_PASSWORD
        elif "too many" in low or "temporar" in low:
            code = RETRY_LATER
        elif "refused" in low or "timed out" in low:
            code = CONNECTION_FAILED
        else:
            code = UNKNOWN

    return RungResult(target=target, rung=rung, status=code, text=text, elapsed=elapsed)


def run_rung(target, rung, probe, state=None, attempts=MAX_ATTEMPTS, sleep=True):
    """Run a rung with bounded retries on transient statuses."""
    last = None
    for attempt in range(1, attempts + 1):
        res = probe_once(target, rung, probe)
        res.attempt = attempt
        last = res
        if res.status not in RETRY_SET:
            break
        if attempt < attempts and sleep:
            time.sleep(backoff(attempt))
    if state is not None:
        if last is not None and last.status not in RETRY_SET:
            state.bump()
        else:
            state.fail()
    return last
# @@END 009 WORKER


# @@BLOCK 010 ENGINE
def run_engine(targets, probe, *, workers=DEFAULT_WORKERS, limit=DEFAULT_RUNG_LIMIT,
               include_pop=None, attempts=MAX_ATTEMPTS, progress=None, sleep=True):
    """Verify many targets concurrently.

    `probe(target, rung, timeout) -> (ok, text)` is supplied by the caller so
    the engine stays free of socket code. Returns
    {target.email: {"target": Target, "verdict": {...}, "results": [RungResult]}}.
    """
    targets = list(targets or ())
    workers = max(1, min(int(workers or DEFAULT_WORKERS), MAX_WORKERS))
    state = EngineState()
    state.total = len(targets)
    out = {}

    def work(target):
        pop = target.pop if include_pop is None else include_pop
        rungs = plan_rungs(target.domain, target.local, include_pop=pop, limit=limit)
        results = []
        for rung in rungs:
            if state.cooled(rung.host, 0):
                continue
            results.append(run_rung(target, rung, probe, state=state,
                                    attempts=attempts, sleep=sleep))
            if results[-1].status == VALID:
                break
            if results[-1].status in RETRY_SET:
                state.cooldown_host(rung.host, 30.0)
        return target, results

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(work, t): t for t in targets}
        for fut in as_completed(futures):
            target = futures[fut]
            try:
                _t, results = fut.result()
            except Exception as exc:
                out[target.email] = {"target": target, "verdict": {"status": UNKNOWN,
                                                                   "error": str(exc)},
                                     "results": []}
                continue
            out[target.email] = {"target": target, "verdict": pick_verdict(results),
                                 "results": results}
            if progress:
                try:
                    progress(state.snapshot())
                except Exception:
                    pass

    return out


def summarise(report):
    if _status is not None:
        try:
            return _status.tally([v["verdict"].get("status") for v in report.values()])
        except Exception:
            pass
    counts = {}
    for v in (report or {}).values():
        s = v.get("verdict", {}).get("status", UNKNOWN)
        counts[s] = counts.get(s, 0) + 1
    return counts
# @@END 010 ENGINE


# @@BLOCK 011 SELFTEST_MAIN
def _selftest():
    checks = []

    def add(name, ok):
        checks.append((name, bool(ok)))

    add("version", ENGINE_VERSION.startswith("v13."))
    add("plan_nonempty", len(plan_rungs("example.com", "bob")) > 0)
    add("plan_pop", any(r.proto == "pop" for r in plan_rungs("example.com", include_pop=True)))
    add("backoff_grows", backoff(3) > backoff(1))
    add("backoff_capped", all(backoff(a) <= BACKOFF_CAP * (1 + JITTER) for a in range(1, 12)))

    t = Target(domain="example.com", local="bob")
    good = RungResult(t, Rung(0, "mail.example.com"), status=VALID)
    bad = RungResult(t, Rung(1, "mail.example.com"), status=WRONG_PASSWORD)
    v = pick_verdict([good, bad])
    add("verdict_wrong", v["status"] == WRONG_PASSWORD)
    add("wrong_hosts", v["wrong_hosts"] == ["mail.example.com"])
    add("wrong_rungs", len(v["wrong_rungs"]) == 1)

    v2 = pick_verdict([RungResult(t, Rung(0, "a"), status=VALID)])
    add("verdict_valid", v2["status"] == VALID)

    v3 = pick_verdict([RungResult(t, Rung(0, "a"), status=UNKNOWN),
                       RungResult(t, Rung(1, "a"), status=CONNECTION_FAILED)])
    add("verdict_most_decisive", v3["status"] == CONNECTION_FAILED)

    st = EngineState()
    st.total = 1
    st.bump()
    add("state", st.snapshot()["done"] == 1)

    def fake_probe(target, rung, timeout):
        return (True, "") if rung.port == 993 else (False, "Connection refused")

    rep = run_engine([Target(domain="example.com", local="bob")], fake_probe,
                     workers=2, limit=3, sleep=False)
    add("engine_runs", len(rep) == 1)
    add("engine_valid", list(rep.values())[0]["verdict"]["status"] == VALID)

    if _status is not None:
        try:
            _status.alias_selftest()
            add("status_selftest", True)
        except Exception:
            add("status_selftest", False)

    bad_names = [n for n, ok in checks if not ok]
    if bad_names:
        raise AssertionError("engine selftest failed: " + ", ".join(bad_names))
    print("engine.py selftest: %d checks OK" % len(checks))
    return True


def main(argv=None):
    ap = argparse.ArgumentParser(description="verification engine")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--version", action="store_true")
    args = ap.parse_args(argv)
    if args.version:
        print(ENGINE_VERSION)
        return 0
    if args.selftest:
        _selftest()
        return 0
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
# @@END 011 SELFTEST_MAIN
# @@EOF
