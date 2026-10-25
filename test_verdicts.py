#!/usr/bin/env python3
"""test_verdicts.py - the behavioural test the repo was missing.

Every other harness is a SUBSTRING test, so the verdict-path bugs (a classifier
that emits WRONG_PASSWORD while the ladder compared against WRONG) passed green.
This one actually calls the code.

    python test_verdicts.py        # exit 0 = clean
"""
import io
import os
import sys

FAILS, PASSES = [], []


def ok(name):
    PASSES.append(name)


def bad(name, got, want):
    FAILS.append("%s -> got %r want %r" % (name, got, want))


# ---------------------------------------------------------------- status.py
import status as S

TABLE = (
    ("NO [AUTHENTICATIONFAILED] Invalid credentials", S.STATUS_WRONG_PASSWORD),
    ("550 5.1.1 User unknown", S.STATUS_WRONG),
    ("command: LOGIN => IMAP server terminating connection", S.STATUS_LOGIN_DROPPED),
    ("* BYE Connection is closed", S.STATUS_LOGIN_DROPPED),
    ("* BYE Auth process broken", S.STATUS_LOGIN_DROPPED),
    ("* BYE server dropping connection", S.STATUS_LOGIN_DROPPED),
    ("* BYE Too many simultaneous connections", S.STATUS_RETRY_LATER),
    ("* BYE Too many invalid IMAP commands", S.STATUS_RETRY_LATER),
    ("socket error: timed out", S.STATUS_CONNECTION_FAILED),
    ("connection reset by peer", S.STATUS_CONNECTION_FAILED),
    ("Socket error: 407: Proxy Authentication Required", S.STATUS_CONNECTION_FAILED),
    ("Name or service not known", S.STATUS_DNS_FAILED),
    ("upstream temporarily unavailable", S.STATUS_RETRY_LATER),
    ("Connection refused", S.STATUS_CONNECTION_FAILED),
    ("", S.STATUS_UNKNOWN),
)
for raw, want in TABLE:
    got = S.classify_error(raw)
    if got == want:
        ok("classify %r" % raw[:44])
    else:
        bad("classify %r" % raw[:44], got, want)

if S.worse_of(S.STATUS_VALID, S.STATUS_WRONG) == S.STATUS_WRONG:
    ok("worse_of is high-wins")
else:
    bad("worse_of", S.worse_of(S.STATUS_VALID, S.STATUS_WRONG), S.STATUS_WRONG)

# ------------------------------------------------------- app.py / engine.py
# Scan the CONCATENATION so these survive a Tier-2 split.
src = ""
for p in ("engine.py", "app.py"):
    if os.path.exists(p):
        src += io.open(p, encoding="utf-8").read() + "\n"

NEEDLES = (
    "def note_verdict(st_val, detail, host=\"\", force=False):",
    "if st_val not in (VALID, WRONG, APP, RBL, LOGIN_DROPPED, UNKNOWN):",
    "_VERDICT_RANK.get(st_val, 0) > _VERDICT_RANK.get(cur, 0)",
)
for n in NEEDLES:
    if n in src:
        ok("present: %s" % n)
    else:
        FAILS.append("MISSING: %s" % n)

if "ST_PRIORITY.get(st_val, 99) < ST_PRIORITY.get(cur, 99)" not in src:
    ok("note_verdict no longer uses the inverted <")
else:
    FAILS.append("note_verdict still compares priorities with <")

# ----------------------------------------------------------------- hosts.py
try:
    import hosts as H
    got = H.conf("windstream.net") or {}
    pop = [h for h in (got.get("pop") or []) if h]
    imap = set(got.get("imap") or [])
    if pop and pop[0] not in imap:
        ok("hosts.conf('windstream.net') leads POP with a real POP host")
    else:
        bad("windstream POP bucket", pop[:3], "a pop.* host, not an imap host")
except Exception as exc:
    FAILS.append("hosts.py: %r" % (exc,))

print("PASSED %d  FAILED %d" % (len(PASSES), len(FAILS)))
for f in FAILS:
    print("  - " + f)
sys.exit(1 if FAILS else 0)
