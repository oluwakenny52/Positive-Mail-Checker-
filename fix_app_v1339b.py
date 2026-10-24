#!/usr/bin/env python3
"""fix_app_v1339b.py - repairs what fix_app_v1339.py false-negatives.

fix_app_v1339.py skips FIX A because its APPLIED_MARK_A ("it was always going to
reject") is present in BOTH copies of the duplicated WRONG block, then dies on
its own post-check (wrong_hosts.add == 2, want 1).  This script keys off the
structure instead of a sentence: it takes the whole helper window and rewrites
it, so it cannot be fooled by a marker.

    python fix_app_v1339b.py
    python -m py_compile app.py && python verify_v1337.py
"""
import os
import sys
import time
import py_compile

TARGET = "app.py"
STAMP = time.strftime("%Y%m%d_%H%M%S")

START_A = ("        def _handle_app_or_wrong(st_val, proto, server, port, user, u_idx, "
           "px_used, seen_px,\n")
END_A = ("        # small mutable holder so _handle_app_or_wrong can read the current "
         "per-attempt timeout")

NEW_FN = '''        def _handle_app_or_wrong(st_val, proto, server, port, user, u_idx, px_used, seen_px,
                                 had_net, saw_retry):
            """Shared body for the APP / WRONG verdict handling.

            Returns (result_tuple_or_None, had_net, saw_retry, advance).
              * result is not None      -> RETURN it
              * advance is True         -> keep going (PROVISIONAL)
              * advance is "retry_user" -> retry this host as the LOCAL PART

            NOTE: px_used is a parameter, not a nonlocal - the helper is a sibling
            of sweep(), not nested inside it, so it cannot rebind sweep's locals.
            That is harmless because the only call it makes here is
            _rotate_to_fresh(..., keep_node=True), which returns the SAME node.
            """
            if st_val == APP:
                xres = try_ms_xoauth2(server, px_used, attempt_to_ref[0], err_text)
                if xres:
                    return xres, had_net, saw_retry, False
                if u_idx + 1 < len(users):
                    flags["saw_server"] = True
                    px_used, _ok = _rotate_to_fresh(px_used, seen_px, "local-part retry", keep_node=True)
                    trace_logs.append(f"{px_tag(px_used)} App-password signal as '{user}' -> retrying same host as local-part '{users[u_idx + 1]}'")
                    return None, had_net, saw_retry, "retry_user"
                app_hosts.add(server)
                _untried_local = [h for h in domain_local_hosts if h not in tried_hosts]
                _confirmed = (len(app_hosts) >= 2) or (not _untried_local)
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
                    f"({len(app_hosts)} host(s) agreed, {len(_untried_local)} local host(s) "
                    f"still untried) -> continuing")
                return None, had_net, saw_retry, True

            # ---- WRONG -------------------------------------------------------
            # v13.39: the local-part retry runs FIRST, exactly as it did before the
            # dedup - a legacy Zimbra/cPanel/Dovecot front answers
            # AUTHENTICATIONFAILED for 'user@domain' and accepts 'user'.  It must
            # also run BEFORE wrong_hosts.add(), because the host has not been
            # authoritatively tested until every username candidate is exhausted -
            # otherwise one host can satisfy the confirmation gate on a username
            # it was always going to reject.
            if u_idx + 1 < len(users):
                flags["saw_server"] = True
                px_used, _ok = _rotate_to_fresh(px_used, seen_px, "local-part retry", keep_node=True)
                trace_logs.append(f"{px_tag(px_used)} Rejected as '{user}' -> retrying same host as local-part '{users[u_idx + 1]}'")
                return None, had_net, saw_retry, "retry_user"

            wrong_hosts.add(server)
            _untried_local = [h for h in domain_local_hosts if h not in tried_hosts]
            _confirmed = (len(wrong_hosts) >= 2) or (not _untried_local)

            if (not confirm_wrong) or _confirmed:
                return (None, WRONG,
                        f"{px_tag(px_used)} {proto} {server} -> {st_val}" + _wrong_detail_note(domain, password),
                        px_used, trace_logs), had_net, saw_retry, False

            trace_logs.append(
                f"{px_tag(px_used)} WRONG on {server} -> PROVISIONAL "
                f"({len(wrong_hosts)} host(s) agreed, {len(_untried_local)} local host(s) "
                f"still untried) -> continuing the ladder")
            return None, had_net, saw_retry, True

'''

OLD_B = "elif u_idx + 1 < len(users) and st_val in (WRONG, UNKNOWN, LOGIN_DROPPED):"
NEW_B = "elif u_idx + 1 < len(users) and st_val in (UNKNOWN, LOGIN_DROPPED):"


def die(msg):
    print("ABORT: " + msg)
    sys.exit(1)


def main():
    if not os.path.exists(TARGET):
        die("app.py not found - run this from the repo root.")

    with open(TARGET, encoding="utf-8") as f:
        src = f.read()
    before_lines = src.count("\n")

    # ---------- sanity ----------
    for probe, want, why in (
        ("def _handle_app_or_wrong", 1, "helper"),
        ("def _check_account_core", 1, "core"),
        ("CONFIRM_WRONG_ACROSS_HOSTS", 4, "guard flag wiring"),
        ("domain_local_hosts = {h for h in", 1, "local-host set"),
    ):
        got = src.count(probe)
        if got < want:
            die(f"expected >= {want} x '{probe}' ({why}), found {got} - wrong file. Nothing written.")

    # ---------- FIX A: replace the whole helper window ----------
    if src.count(START_A) != 1:
        die(f"FIX A start anchor found {src.count(START_A)}x (want 1).")
    if src.count(END_A) != 1:
        die(f"FIX A end anchor found {src.count(END_A)}x (want 1).")
    i = src.index(START_A)
    j = src.index(END_A)
    if j <= i:
        die("FIX A end anchor sits BEFORE the start anchor.")

    window = src[i:j]
    n_wrong = window.count("wrong_hosts.add(server)")
    already = ("_dialable_local" not in window) and n_wrong == 1
    if already:
        print("FIX A: window already correct (1 WRONG block, no _dialable_local), skipped.")
    else:
        if n_wrong < 1:
            die("FIX A window does not contain wrong_hosts.add(server) - anchor drift.")
        if "def _handle_app_or_wrong" not in window:
            die("FIX A window does not start at the helper - anchor drift.")
        src = src[:i] + NEW_FN + src[j:]
        print(f"FIX A: helper rewritten ({len(window.splitlines())} -> "
              f"{len(NEW_FN.splitlines())} lines; had {n_wrong} WRONG block(s), "
              f"{window.count('_dialable_local')} x _dialable_local).")

    # ---------- FIX B: the shadowed branch handles only UNKNOWN / LOGIN_DROPPED ----------
    n_old, n_new = src.count(OLD_B), src.count(NEW_B)
    if n_old == 2 and n_new == 0:
        src = src.replace(OLD_B, NEW_B)
        print("FIX B: 2 call sites re-gated.")
    elif n_old == 0 and n_new == 2:
        print("FIX B: already applied, skipped.")
    else:
        die(f"FIX B anchor mismatch: old={n_old} new={n_new} (want 2/0 or 0/2).")

    # ---------- post-conditions ----------
    for probe, want in (
        ("_dialable_local", 0),
        ("wrong_hosts.add(server)", 1),
        ("app_hosts.add(server)", 1),
        ("if (not confirm_wrong) or _confirmed:", 2),
        ("retrying same host as local-part", 2),
        ("st_val in (WRONG, UNKNOWN, LOGIN_DROPPED)", 0),
        ("st_val in (UNKNOWN, LOGIN_DROPPED)", 2),
        ("ifapp_hosts", 0),
        ("def _handle_app_or_wrong", 1),
        ("def _check_account_core", 1),
    ):
        got = src.count(probe)
        if got != want:
            die(f"post-check failed: '{probe}' = {got}, want {want}. Nothing written.")

    fn_start = src.index("        def _handle_app_or_wrong(")
    fn_end = src.index(END_A, fn_start)
    body = src[fn_start:fn_end]
    if body.index("retrying same host as local-part") > body.index("wrong_hosts.add(server)"):
        die("ordering: the WRONG retry sits AFTER wrong_hosts.add().")

    # ---------- compile, then swap in ----------
    tmp = TARGET + ".tmp_v1339b"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(src)
    try:
        py_compile.compile(tmp, doraise=True)
    except py_compile.PyCompileError as e:
        os.remove(tmp)
        die(f"result does not compile:\n{e}")

    bak = f"app.py.bak.{STAMP}"
    with open(bak, "w", encoding="utf-8") as f:
        f.write(src[:0] + open(TARGET, encoding="utf-8").read())
    os.replace(tmp, TARGET)

    print(f"\nOK. app.py rewritten ({before_lines} -> {src.count(chr(10))} lines).")
    print(f"Backup: {bak}")
    print("Next: python -m py_compile app.py && python verify_v1337.py")


if __name__ == "__main__":
    main()
