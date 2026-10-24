#!/usr/bin/env python3
"""fix_app_v1339c.py - the three P3 hygiene edits, anchor-asserted.

    python fix_app_v1339c.py
    python -m py_compile app.py
"""
import os
import sys
import time
import py_compile

TARGET = "app.py"
STAMP = time.strftime("%Y%m%d_%H%M%S")

# ---- 3a: geo throttle must PAY its reservation -----------------------------
A_OLD = ('        wait = GEO_MIN_INTERVAL - (now - _geo_last_call["ts"])\n'
         '        _geo_last_call["ts"] = max(now, _geo_last_call["ts"] + GEO_MIN_INTERVAL)\n'
         '    if wait > 0:\n'
         '        time.sleep(min(wait, 1.0))')
A_NEW = ('        # v13.39b: reserve the NEXT slot and actually sleep it.  Capping the\n'
         '        # sleep at 1.0s while the interval is 1.33s meant the stamp advanced\n'
         '        # 1.33s per call against 1.0s of wall clock - the reservation grew and\n'
         '        # was never paid, at ~60 req/min on a 45/min tier.\n'
         '        wait = max(0.0, _geo_last_call["ts"] + GEO_MIN_INTERVAL - now)\n'
         '        _geo_last_call["ts"] = now + wait\n'
         '    if wait > 0:\n'
         '        time.sleep(min(wait, 3.0))')

# ---- 3b: self_signed can never be None ------------------------------------
B_OLD = ('debug_mode = instant_help("debug_mode", "Stream verbose logs and error tracing '
         'directly into the UI interface.", "Enable Debug Mode", widget_type="checkbox", '
         'value=True)\n')
B_NEW = (B_OLD +
         '\n'
         '# v13.39b: instant_help() returns None when its internal try/except fires, and\n'
         '# `not None` is True - which silently flips ALLOW_SELF_SIGNED to False and turns\n'
         '# verification ON behind your back, in build_cfg()\'s "TLS_STRICT": not self_signed.\n'
         'self_signed = True if self_signed is None else self_signed\n')

# ---- 3c: report_entries needs a ceiling ------------------------------------
C_OLD = ('                                    "Under-The-Hood Background Trace": '
         'f"Result: {res.get(\'detail\',\'\')}\\nSteps Executed:\\n  \u21b3 {trace_text}",\n'
         '                                })\n')
C_NEW = (C_OLD +
         '                                # v13.39b: the only per-account list with no cap\n'
         '                                # (log_lines is capped at log_cap).\n'
         '                                if len(str_lit.session_state.report_entries) > 2000:\n'
         '                                    del str_lit.session_state.report_entries[:-2000]\n')

EDITS = (("3a geo throttle pays its reservation", A_OLD, A_NEW),
         ("3b self_signed can never be None", B_OLD, B_NEW),
         ("3c report_entries capped at 2000", C_OLD, C_NEW))


def die(msg):
    print("ABORT: " + msg)
    sys.exit(1)


def main():
    if not os.path.exists(TARGET):
        die("app.py not found - run this from the repo root.")
    with open(TARGET, encoding="utf-8") as f:
        src = f.read()

    applied, skipped = [], []
    for label, old, new in EDITS:
        if new.strip() and new.splitlines()[0] in src and src.count(old) == 0:
            skipped.append(label)
            continue
        n = src.count(old)
        if n != 1:
            die(f"{label}: anchor found {n}x (want 1). Nothing written.")
        line = src[:src.index(old)].count("\n") + 1
        src = src.replace(old, new, 1)
        applied.append((label, line))

    if not applied:
        print("Nothing to do - all three already applied.")
        return

    for label, line in applied:
        print(f"applied {label} at line {line}")

    # post-conditions
    for probe, want in (("time.sleep(min(wait, 3.0))", 1),
                        ("time.sleep(min(wait, 1.0))", 0),
                        ('GEO_MIN_INTERVAL - now)', 1),
                        ("self_signed = True if self_signed is None else self_signed", 1),
                        ("report_entries[:-2000]", 1)):
        got = src.count(probe)
        if got != want:
            die(f"post-check failed: {probe!r} = {got}, want {want}. Nothing written.")

    tmp = TARGET + ".tmp_v1339c"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(src)
    try:
        py_compile.compile(tmp, doraise=True)
    except py_compile.PyCompileError as e:
        os.remove(tmp)
        die(f"result does not compile:\n{e}")

    bak = f"app.py.bak.{STAMP}"
    with open(TARGET, encoding="utf-8") as f:
        original = f.read()
    with open(bak, "w", encoding="utf-8") as f:
        f.write(original)
    os.replace(tmp, TARGET)

    print(f"\nOK. Backup: {bak}")
    print("Next: python -m py_compile app.py")


if __name__ == "__main__":
    main()
