# @@FILE pages/6_User_Guide.py blocks=17 version=v13.47
# @@BLOCK 000 FILE_HEADER deps=-
"""
pages/6_User_Guide.py - User Guide  (v13.47)
============================================
Everything the app can do, in one read-only page: every sidebar control, every
button, every verdict the engine can return, every other page, and what each one
is FOR - so a first-time user knows what a thing does before pressing it.

No mailbox connection. No proxy credit. No file writes. Pure reference.

WHY THE LAYOUT IS 17 BLOCKS AND 8 TABS
--------------------------------------
The 8-tab rewrite is the content; this frame is what makes it replaceable. The
merge of the two once produced duplicate ids 006-016, a "with _t1:" with no body,
and a stylesheet pasted into an f-string with single braces. All three are fixed
here and each has its own note below.

BUILD_TAG / CFG_VERSION mirror app.py block 008 exactly. verify_v1337.py derives
both from app.py's @@FILE header and fails if this page disagrees, so the parity
is a check now, not a comment.
"""

import os
import sys

import streamlit as st
# @@END 000 FILE_HEADER

# @@BLOCK 001 SYSPATH_AND_BUILD deps=000
THIS_DIR = os.path.dirname(os.path.abspath(__file__))
APP_DIR = os.path.dirname(THIS_DIR)
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

# Mirrors app.py block 008. Keep the two identical - verify_v1337.py enforces it.
BUILD_TAG = "v13.47"
CFG_VERSION = 1347
# @@END 001 SYSPATH_AND_BUILD

# @@BLOCK 002 PAGE_CONFIG deps=001
# set_page_config MUST be the first Streamlit call in the process.
st.set_page_config(
    page_title="User Guide - Mega Ultimate Mail Checker",
    page_icon="📖",
    layout="wide",
    initial_sidebar_state="collapsed",
)
# @@END 002 PAGE_CONFIG

# @@BLOCK 003 THEME_CSS deps=002
import json

_TH_DEFAULTS = {
    "bg": "#0b1020", "panel": "#141b30", "text": "#e6ebff",
    "accent": "#8b5cf6", "accent2": "#22d3ee", "g1": "#667eea", "g2": "#764ba2",
}


def _load_theme():
    """theme.json when it parses, else the defaults. Never raises."""
    base = dict(_TH_DEFAULTS)
    for cand in (os.path.join(APP_DIR, "theme.json"), "theme.json"):
        try:
            if not os.path.exists(cand):
                continue
            with open(cand, encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict):
                base.update({k: v for k, v in data.items()
                             if k in base and isinstance(v, str)})
            break
        except Exception:
            continue
    return base


_TH = _load_theme()

# A PLAIN string with __TOKEN__ placeholders, not an f-string. The stylesheet is
# full of braces, and doubling every one of them is exactly what the last paste
# got wrong - it shipped "f\"\"\" \"\"\"<style>" and then single braces, so the
# block raised "f-string: expecting '}'".
_CSS_TMPL = """
<style>
    .ug-hero {
        background: linear-gradient(135deg, __G1__ 0%, __G2__ 100%);
        padding: 22px 26px; border-radius: 14px; margin-bottom: 16px;
        border: 1px solid rgba(255,255,255,.12);
    }
    .ug-hero h1 { color: #fff !important; margin: 0; font-size: 1.65rem; font-weight: 800; }
    .ug-hero p { color: rgba(255,255,255,.93) !important; margin: 8px 0 0 0; font-size: .92rem; }
    .ug-card {
        background: __PANEL__; border: 1px solid rgba(255,255,255,.10);
        border-left: 4px solid __ACCENT__; border-radius: 12px;
        padding: 12px 16px; margin: 10px 0;
    }
    .ug-card h4 { margin: 0 0 6px 0; font-size: .95rem; }
    .ug-card p { margin: 0; font-size: .85rem; line-height: 1.45; opacity: .92; }
    .ug-h { margin: 26px 0 6px 0; font-size: 1.05rem; font-weight: 800;
            border-left: 4px solid __ACCENT2__; padding-left: 10px; }
    .ug-warn { border-left-color: #f59e0b !important; }
    .ug-bad { border-left-color: #ef4444 !important; }
    .ug-good { border-left-color: #22c55e !important; }
    .block-container, [data-testid="stMainBlockContainer"] {
        padding-top: 1.2rem !important; padding-bottom: 2rem !important;
        max-width: 900px !important;
    }
    @media (max-width: 820px) {
        .block-container, [data-testid="stMainBlockContainer"] {
            padding-top: 0.55rem !important;
            padding-left: 0.7rem !important; padding-right: 0.7rem !important;
        }
        .ug-hero { padding: 14px 16px !important; }
        .ug-hero h1 { font-size: 1.2rem !important; }
        .ug-card { padding: 10px 12px !important; }
        pre, code { font-size: .68rem !important; }
    }
</style>
"""

_CSS = (_CSS_TMPL
        .replace("__G1__", _TH["g1"])
        .replace("__G2__", _TH["g2"])
        .replace("__PANEL__", _TH["panel"])
        .replace("__ACCENT__", _TH["accent"])
        .replace("__ACCENT2__", _TH["accent2"]))

st.markdown(_CSS, unsafe_allow_html=True)
# @@END 003 THEME_CSS

# @@BLOCK 004 AUTH deps=001
import auth

try:                                   # a module cached from before a redeploy
    auth.fit_panel                     # still has the pre-split, one-function shape
except AttributeError:
    import importlib
    auth = importlib.reload(auth)
from auth import user_file

# require() first, fit() second - the order every page uses. fit() is CSS-only
# and must land before the first widget. fit_panel() lands after the hero.
# Call each EXACTLY once: a second fit() raises
# StreamlitWidgetAlreadyInstantiatedError inside its own try/except.
auth.require(st, "Unlock User Guide")
auth.fit(st)
# @@END 004 AUTH

# @@BLOCK 005 HERO deps=004
st.markdown(
    f"""
<div class="ug-hero">
    <h1>📖 User Guide</h1>
    <p>Build {BUILD_TAG} · block edition. What every control does, what every
    button does, what every verdict means, and which page does what.
    Nothing here connects anywhere.</p>
</div>
""",
    unsafe_allow_html=True,
)

auth.fit_panel(st)          # the controls; collapsed until tapped
# @@END 005 HERO

# @@BLOCK 006 TABS deps=005
(_t1, _t2, _t3, _t4, _t5, _t6, _t7, _t8) = st.tabs([
    "🚀 Getting started", "🎛 Sidebar controls", "🔘 Every button",
    "🏷 What a verdict means", "📦 Downloads & buckets", "🧭 The other pages",
    "⚙ How the engine works", "🩺 Troubleshooting",
])
# @@END 006 TABS

# @@BLOCK 007 SECTION_HELPERS deps=006
# Both helpers live HERE, not inside a tab. A def inside "with _t1:" binds
# globally anyway, but the block named SECTION_HELPERS has to hold them or every
# later tab depends on block 010 having run first.
def ug_h(text: str):
    st.markdown(f'<div class="ug-h">{text}</div>', unsafe_allow_html=True)


def ug_card(title: str, body: str, tone: str = ""):
    cls = "ug-card" + (f" ug-{tone}" if tone else "")
    st.markdown(
        f'<div class="{cls}"><h4>{title}</h4><p>{body}</p></div>',
        unsafe_allow_html=True,
    )
# @@END 007 SECTION_HELPERS

# @@BLOCK 008 TAB_GETTING_STARTED deps=007
with _t1:
    ug_h("The 4 steps that actually run a check")

    st.markdown(
        """
1. **Add proxies** - sidebar, `📥 Fetch & Test All Proxies`. This pulls your
   Webshare / Oxylabs lines, opens a real CONNECT tunnel through each, and keeps
   only the ones that answered. The surviving nodes are written to `proxies.txt`
   and armed. The raw fetched pool is backed up to `proxies_all.txt`.
2. **Paste combos** - main page, `Accounts Input & Pre-Filtering`. Format is
   `email:password`, one per line. Paste or upload a `.txt`.
3. **Press Start** - `🔥 Start Live Checking Engine`. Leave *Engine Action Mode*
   on `Ready to Check` unless you are re-running a bucket.
4. **Take the results** - `📦 Download All Results (.zip)`, or open **Export
   Studio** in the nav for per-status files, CSV, JSON and a per-status split.
"""
    )

    ug_h("Before you press Start, know these three defaults")
    ug_card(
        "Confirm a WRONG verdict across hosts = ON",
        "One <code>AUTHENTICATIONFAILED</code> is treated as <i>provisional</i> - the "
        "ladder keeps dialling other hosts and rungs before accepting it. This is why a "
        "run is slower than a one-shot checker, and why it finds fewer false "
        "\"wrong password\" results.",
        "good",
    )
    ug_card(
        "Pick Protocols Mode = IMAP + POP3",
        "POP3 is the only genuinely independent path when a legacy IMAP front answers "
        "LOGIN with <code>* BYE</code> and hangs up.",
        "good",
    )
    ug_card(
        "Quarantine nodes that return 407 = ON",
        "A node that answers <code>407 Proxy Authentication Required</code> three times "
        "is pulled out of the pool for the run. A plain socket reset is <b>not</b> a 407 "
        "and does not quarantine.",
        "good",
    )

    ug_h("What costs proxy credit")
    st.markdown(
        """
| Action | Cost |
|---|---|
| `📥 Fetch & Test All Proxies` | 1 tunnel per line |
| `🔁 Re-probe pool now` / `Re-probe All` | 1 tunnel per node |
| A checking run | up to ~60 requests per account worst case |
| Diagnostics page, Block Inspector, **this page** | **zero** |

`Request budget` in the sidebar shows the live worst-case number per account.
"""
    )
    st.info("First run? Leave every sidebar setting on its default. They are "
            "pre-set for a mixed Gmail / O365 / Yahoo / legacy-ISP list.")
# @@END 008 TAB_GETTING_STARTED

# @@BLOCK 009 TAB_SIDEBAR deps=007
with _t2:
    st.markdown("Every sidebar control, what it does, and when to touch it.")

    ug_h("Engine")
    st.markdown(
        """
| Control | What it does |
|---|---|
| **Select Engine Mode** | `Normal` = balanced. `Fast` = fewer rungs, shorter deadline, 100 workers. `Deep` = 4 hosts/domain, 400 s deadline, strict. |
| **Workers Start** | Parallel accounts. Auto-scales when *Thread Auto-Scaling* is on and the list is large. |
| **Deadline (Seconds)** | Wall-clock budget **per account**, split between the proxy phase and the direct phase. |
| **Timeout** | Per-attempt socket timeout. |
| **Max Accounts** | Truncates the queue. `0` = unlimited. |
| **Blacklist CF** | Consecutive network failures before a node is circuit-broken for 30 s. |
"""
    )

    ug_h("Protocols")
    st.markdown(
        """
| Control | What it does |
|---|---|
| **Pick Protocols Mode** | Which protocols may be dialled. `IMAP` and `POP3` are real verdict sources. `SMTP` and `ManageSieve` are **CONFIRM-ONLY** - a failure never lowers a verdict. |
| **Enable STARTTLS + plaintext fallback** | Adds 143/110 rungs after implicit TLS fails. They get a shorter leash (8 s) because 143/110 are often firewalled from cloud egress. |
"""
    )

    ug_h("Rules")
    st.markdown(
        """
| Control | What it does |
|---|---|
| **Thread Auto-Scaling** | Lets the engine grow/shrink workers with list size. |
| **Max Hosts Per Domain** | How many discovered IMAP hosts to try. 143/110 and POP rungs are capped separately. |
| **Try local-part username on auth failure** | On an auth rejection, retries the **same** host as `user` instead of `user@domain`. Fires on `* BYE` too. Not applied to SMTP. |
| **Confirm a WRONG verdict across hosts** | The guard. ON = provisional WRONG until a second host or rung agrees. OFF = one-rung, faster, more false wrongs. |
| **Enable SMTP pre-check** | A reachability banner probe on 587/465/25 only - never authenticates. |
| **Custom Whitelist / Blacklist Domains** | Comma-separated domain filters applied before the ladder. |
"""
    )

    ug_h("Proxy / pool")
    st.markdown(
        """
| Control | What it does |
|---|---|
| **Min Proxy Score** | Drops nodes below this score. |
| **Proxy Pre-Check Timeout / Tunnel Probe Timeout** | TCP leg / total tunnel budget per node. |
| **Tunnel Probe Target** | Default `443 (HTTPS)` hits `api.ipify.org`, i.e. your provider's **websites** meter, not the email-servers meter. |
| **Strict tunnel probe** | ON = only nodes that pass the probe enter the pool, so `Alive: 0` means it. |
| **Probe: max targets per node / second scheme / idle probing / max nodes per cycle** | Request-frugality knobs. Defaults are the cheap ones. |
| **Spot-check the pool against a MAIL destination** | After each probe cycle, CONNECTs 3 nodes to your first queued mail host. Catches the "pool passes the web probe but 407s mail ports" case. |
| **Deduplicate proxy pool** | Collapses repeated `host:port` lines. |
| **Allow Blacklisted / Flagged Proxy IPs** | OFF = circuit-broken nodes leave the pool **and** the ladder. |
| **Quarantine nodes that return 407** | 3 strikes → out for the run. |
| **Pool picker** (`all` / `us_only` / `country` / `mix`) | Geo-filter the pool. `Change pool` unlocks it. |
"""
    )

    ug_h("Concurrency governors")
    st.markdown(
        """
| Control | What it does |
|---|---|
| **Per-Host Connection Cap** | Simultaneous connections to one mail hostname. 2 suits legacy ISP IMAP. |
| **Per-Proxy-IP Connection Cap** | Simultaneous tunnels through one proxy IP. |
| **Per-Proxy-SUBUSER Connection Cap** | **The single most important 407 control.** Providers meter per sub-user. |
| **Global Proxy Connection Cap** | Whole-run cap; the prober shares it. |
| **Direct-First** | Try the direct egress first. Auto-engages when >50 % of the pool is quarantined. |
| **Same-Host Retries on a SLOW answer** | READ-level slowness only. |
| **Max proxy rotations per rung** | Every rotation is another proxy request. |
| **Second pass over network-failed hosts** | Re-dials hosts that failed with a *network* error. |
| **Proxy Random Rotation** | Different random node per attempt, with a per-account avoid-set. |
| **Geo-Call Proxy** | Prefers a node matching the email's country. |
| **My own connection** | Diagnostic stamp on direct fallbacks. |
"""
    )

    ug_h("Switches")
    st.markdown(
        """
| Control | What it does |
|---|---|
| **Use Proxy** | OFF = fully direct. |
| **Retry CF (Direct Retry)** | One extra direct pass after a proxy network error. |
| **Allow Self-Signed** | **A real switch.** Ticked = accept unverified. Unticked = verify, and if that fails the handshake is retried unverified *unless* `TLS_STRICT`. |
| **Test Flight** | Probe every node before it enters the pool. Keep it ON. |
| **Skip Strict App-Only Providers** | Buckets Gmail/O365 away instead of checking them. |
| **Enable Debug Mode** | Verbose log cap (400 vs 120). |
| **Proxy Mode Engine** | `aggressive` proxy-only · `fallback` proxy then direct (default) · `sticky` one node per worker · `off` never proxy. With a provider-wide 407, `off` is the only mode that finishes. |
"""
    )

    ug_h("Buttons at the bottom of the sidebar")
    st.markdown(
        """
| Button | What it does |
|---|---|
| **💾 Apply Settings** | Commits the sidebar into the running config and rebuilds the concurrency gates. Nothing changes until you press it. |
| **♻️ Reset Defaults** | Restores every control to the universal default (protocols back to IMAP + POP3). |
| **🎨 Theme Studio** | Presets, colours, radius, glow, animated gradient, colourised logs, hero text. |
"""
    )
# @@END 009 TAB_SIDEBAR

# @@BLOCK 010 TAB_BUTTONS deps=007
with _t3:
    st.markdown("Every button in the app, in the order you will meet it.")

    ug_h("Main page")
    st.markdown(
        """
| Button | What it does |
|---|---|
| **❓ (next to each switch)** | Toggles that switch's help text for 10 s. Free. |
| **🔥 Start Live Checking Engine** | Starts the run on the selected category. Clears the 407 quarantine first. |
| **📥 Fetch & Test All Proxies** | Fetches, validates, writes `proxies.txt`, arms the pool, geo-tags, and runs a mail-destination spot check. |
| **🔁 Re-probe pool now** | Clears probe stats and re-runs the tunnel probe. |
| **🧾 Show raw proxies.txt** | Prints the first 60 lines and whether credentials are present. |
| **↩️ Restore from proxies_all.txt** | Puts the full raw fetched pool back - the way back from a shrunk pool. |
| **➕ Add Custom Proxies → Save Custom Proxies** | Appends pasted lines to `proxies.txt` and de-duplicates. |
| **🔄 Refresh Dashboard / 🔁 Re-probe All** | Proxy Health dashboard refresh / full re-probe. |
| **🧹 Clean Dead / Low-Score** | Removes nodes with score < 5 or ≥ 10 fails from `proxy_meta.json`. |
| **♻️ Lift 407 Quarantine** | Clears the quarantine and all 407 strike counters. |
| **🔬 Deep Diagnostics → 🔁 Rebuild / 🧪 Direct self-test** | Rebuilds the bundle / runs a live classifier + tunnel + mail-destination self-test. |
| **⬇️ Download bundle** | The full diagnostic text, credentials included. |
| **🔄 Refresh Startup Screen / 🧹 Clear Startup Logs** | Startup ledger controls. |
| **📖 Read Inbox Messages** | Reads the selected valid account's last N headers, through a proxy. |
| **📦 Download All Results (.zip Package)** | The whole run as one archive. |
"""
    )

    ug_h("Export Studio (pages/4)")
    st.markdown(
        """
| Button | What it does |
|---|---|
| **⬇️ Download <name>** | The template-rendered text. |
| **⬇️ Download CSV / JSON / ZIP** | The same selection in another format. |
| **⬇️ <STATUS>.txt** | One file per status, inside the "Per-status split" tab. |
| **Save preset / Apply** | Stores and re-applies the whole format configuration. |
"""
    )

    ug_h("Block Inspector (pages/5)")
    st.markdown(
        """
| Button | What it does |
|---|---|
| **🔁 Re-scan now** | Re-audits the frame of every block file. |
| **✅ Validate paste** | Runs the same verifier on a pasted file before you commit it. |
| **🛠 Canonicalise** | Names every bare `@@END` from its `@@BLOCK`, then offers the fixed file to download. |
| **🧪 Run fix self-check** | Proves the behavioural fixes are still textually present. |
"""
    )

    ug_h("Diagnostics (pages/2) - all read-only")
    st.markdown(
        "**▶ Probe all targets**, **Run full discovery**, **Probe SMTP candidates**, "
        "**🧹 Clear hosts_cache.json**, **♻️ Refresh this domain**, "
        "**📋 Build copy/paste bundle**."
    )
# @@END 010 TAB_BUTTONS

# @@BLOCK 011 TAB_VERDICTS deps=007
with _t4:
    ug_h("What each verdict means")
    st.markdown(
        "**A verdict is about the password, not about the proxy.** Anything that died "
        "in the proxy hop never tested the password, and the engine says so."
    )

    st.markdown(
        """
| Verdict | Bucket file | Meaning | What to do |
|---|---|---|---|
| **VALID** | `valid_*.txt` | Post-auth verification passed: the mailbox opened and INBOX selected. | Keep it. |
| **WRONG** / `WRONG_PASSWORD` | `wrong_*.txt` | The server rejected the credentials. With the guard ON this was **confirmed** on a second host or rung first. | Discard, unless the domain needs an app password (the detail line says so). |
| **APP** / `NEED_APP_PASSWORD` | `need_app_*.txt` | The provider wants an app password / modern auth. Gmail, Yahoo and O365 land here. | Generate an app password and re-run the bucket. |
| **LOGIN_DROPPED** | `login_dropped_*.txt` | The server **answered**, accepted the LOGIN command, then closed the socket (`* BYE`). | **Not a wrong password.** Retry from a different IP or with an app password. |
| **RETRY** / `RETRY_LATER` | `retry_later_*.txt` | Rate limit, `too many simultaneous connections`, throttling. | Re-run later. |
| **RBL** / `RBL_BLOCKED` | `rbl_blocked_*.txt` | Your egress IP is on a blocklist, or the server names one. | Rotate node / change egress. |
| **CONNECTION_FAILED** / `FAILED` | `failed_*.txt` | Transport died: refused, reset, TLS failure, timeout. | Re-run; often a pool problem. |
| **PROXY_UNHEALTHY** | `proxy_unhealthy_*.txt` | Every attempt died with `407 Proxy Authentication Required`. **The mailbox was never reached.** | Set `Proxy Mode Engine = off`, or wait for the provider cap. |
| **DNS_FAILED** | `dns_failed_*.txt` | No candidate host resolved locally. | Usually a dead domain. |
| **SMTP_FAILED** | `smtp_failed_*.txt` | SMTP pre-check only: no 220 banner. | Optional - off by default. |
| **SKIP** / `SKIPPED_COOLDOWN` | `skipped_*.txt` | Bad format, disposable domain, or Fast-Mode domain cooldown. Counted as checked. | Usually nothing. |
| **UNKNOWN** | `unclassified_*.txt` | The server said something the classifier did not recognise. | Send the diagnostic bundle. |
"""
    )

    ug_h("Three that are easy to confuse")
    ug_card(
        "LOGIN_DROPPED is not WRONG",
        "The host spoke; the password is untested.",
        "warn",
    )
    ug_card(
        "PROXY_UNHEALTHY is not CONNECTION_FAILED",
        "The node rejected <i>you</i>, not the mailbox.",
        "warn",
    )
    ug_card(
        "APP is not WRONG",
        "The password may be perfectly correct - the auth method is wrong.",
        "warn",
    )

    st.markdown(
        "The detail line on every result names the protocol, host, port and the proxy "
        "tag, so you can always tell which of the three happened."
    )
# @@END 011 TAB_VERDICTS

# @@BLOCK 012 TAB_DOWNLOADS deps=007
with _t5:
    ug_h("Buckets, files and where to get them")
    st.markdown(
        "A run writes one file per bucket into `mail_results/`, stamped "
        "`YYYYMMDD_HHMMSS`, plus `clean_valid_accounts.txt` (merged, de-duplicated) "
        "and a `mail_results_<stamp>.zip`."
    )

    st.markdown(
        """
| Where | What you get |
|---|---|
| Main page, `📦 Download All Results` | Everything as one ZIP. |
| Main page, results summary expanders | One expander per bucket, in-app. |
| **Export Studio → Sources** | Pick **any combination** of session buckets and result files. |
| **Export Studio → Per-status split** | One download per status. |
| **Export Studio → CSV / JSON / ZIP** | The same selection in another shape. |
"""
    )

    ug_h("If Export Studio only offers valid accounts")
    st.markdown(
        "That is the `Sources` box in its sidebar. It is a **multi-select** - tap it and "
        "add `Session · wrong_results`, `Session · conn_results`, and so on, or pick the "
        "`mail_results/...` files directly. Nothing is filtered out."
    )

    ug_h("Presets")
    st.markdown(
        "Set the format once, type a name, `Save preset`. Next time, `Load preset` → "
        "`Apply`. Presets live in `download_presets.json` next to `app.py`, so on a "
        "cloud deploy they reset on redeploy."
    )
# @@END 012 TAB_DOWNLOADS

# @@BLOCK 013 TAB_PAGES deps=007
with _t6:
    ug_h("The other pages")
    st.markdown(
        """
| Page | What it is | Costs |
|---|---|---|
| **Main** (`app.py`) | The checker: settings, input, run, results, in-app reader. | proxy credit |
| **`pages/2_Diagnostics.py`** | Read-only. Shows the **exact rung order** the engine will dial for a domain, live TCP probes on 993/143/995/110, MX/SRV discovery, SMTP candidates, a `proxies.txt` audit, and cache tools. | zero |
| **`pages/3_Mailbox_Reader.py`** | Bulk inbox reader: folders, OTP scanner, card/credential scanner, bot purge, per-message actions. | proxy credit |
| **`pages/4_Downloads.py`** | Export Studio. Text / CSV / JSON / ZIP / per-status split, with filters, sorting, dedupe and presets. | zero |
| **`pages/5_Blocks.py`** | Block Inspector. Frame audit, paste validation, `@@END` canonicaliser, fix self-check. | zero |
| **`pages/6_User_Guide.py`** | This page. | zero |
"""
    )
    st.markdown(
        "Start with **Diagnostics** for one domain if a run is behaving oddly - it tells "
        "you whether the host, the port or the path is the problem, before you spend a "
        "single proxy request."
    )
# @@END 013 TAB_PAGES

# @@BLOCK 014 TAB_HOW_IT_WORKS deps=007
with _t7:
    ug_h("The pipeline, in order")
    st.markdown(
        """
1. **Pre-filter.** Bad format, disposables, typos, already-valid, DNS failures
   and optional SMTP failures are bucketed **before** any network work.
2. **Host resolution.** `hosts.conf()` for known providers; otherwise SRV →
   autoconfig → autodiscover → MX → prefix guesses, ranked, junk-router labels
   demoted, duplicate IPs collapsed, apex appended last.
3. **Rung ladder.** IMAP:993 → POP3:995 for non-IMAP hosts → remaining IMAP
   hosts → SMTP 587/465/25 → ManageSieve 4190, then the 143/110 fallbacks. Each
   rung runs behind the per-host, per-IP and per-sub-user gates.
4. **Verdict handling.** `VALID` returns immediately. `WRONG`/`APP` first retry
   the same host as the local part, then go **provisional** until a second host
   or rung agrees. `LOGIN_DROPPED` keeps the ladder moving. `407` rotates the
   node, and two 407s in one rung trip the storm breaker into the direct phase.
5. **Direct phase.** Whatever the proxy phase did not settle is re-dialled from
   your own egress, with real geo/VPN stamps on the trace.
6. **Tail.** If nothing answered, the retained verdict is returned with an
   honest note; otherwise `PROXY_UNHEALTHY` / `DNS_FAILED` / `LOGIN_DROPPED` /
   `RETRY` / `FAILED` in that order of authority.
7. **Export.** Twelve bucket files, a merged valid file, and a ZIP.
"""
    )

    ug_h("What CONFIRM-ONLY means")
    st.markdown(
        "SMTP and ManageSieve can only ever *add* a verdict. If SMTP says 535, that is a "
        "real answer. If SMTP fails for any other reason, the verdict is untouched."
    )

    ug_h("Post-auth verification")
    ug_card(
        "A login alone is not enough",
        "After authentication the engine selects INBOX read-only and issues a NOOP. A "
        "node that intercepts the handshake but never had the mailbox fails here, which "
        "is why a 'valid' means the mailbox really opened.",
        "good",
    )
# @@END 014 TAB_HOW_IT_WORKS

# @@BLOCK 015 TAB_TROUBLESHOOT deps=007
with _t8:
    ug_h("Symptom → cause")
    st.markdown(
        """
| Symptom | What it usually is |
|---|---|
| `TypeError: Importing a module script failed.` in red | **Not a Python error.** Your browser is holding a stale JS chunk after a redeploy. Hard-refresh (`Ctrl`/`Cmd`+`Shift`+`R`). |
| `Alive: 0` after Fetch & Test | The pool genuinely failed the tunnel probe. Press it again, or lower `Min Proxy Score`. |
| Every account `PROXY_UNHEALTHY` | The pool passes the web probe but your provider is capping **email-server** destinations. Set `Proxy Mode Engine = off`, or wait for the cap to reset. |
| Lots of `LOGIN_DROPPED` | The mail server answered and hung up. Retry from a different IP, or use an app password. **Not** a wrong password. |
| Lots of `APP` | Normal for Gmail / Yahoo / O365. Generate app passwords. |
| `Every proxy was filtered out` | `Min Proxy Score`, pool mode or the circuit breaker emptied the pool. The raw list is **not** used as a silent fallback - by design. |
| Run feels slow | `Confirm a WRONG verdict across hosts` is ON (intended), and the live panels re-render 8×/second. Raise the mode to `Fast`, or narrow the protocol list. |
| Settings do not change | Nothing applies until **💾 Apply Settings**. |
| `⚠ You have UNAPPLIED settings changes` | Exactly that. Press Apply. |
| `407` shown as a proxy failure, not a password failure | Correct. The mailbox was never reached. |
"""
    )

    ug_h("Getting help")
    st.markdown(
        "Sidebar → `🔬 Deep Diagnostics` → `⬇️ Download bundle`. It contains the "
        "environment, the live config, the raw `proxies.txt` lines, the probe histogram, "
        "the quarantine state and the last 60 probe events. Proxy credentials are "
        "visible in it - rotate them if you paste it publicly."
    )
# @@END 015 TAB_TROUBLESHOOT

# @@BLOCK 016 GLOSSARY_FOOTER deps=007
st.divider()

ug_h("Glossary")
st.markdown(
    """
**Rung** - one `protocol host:port tls-mode` attempt in the ladder.
**Guard** - the cross-host WRONG confirmation.
**Confirm-only** - a protocol that can only add a verdict, never lower one.
**407** - the *proxy* rejected your credentials, not the mail server.
**Sub-user** - the username half of a proxy line; providers meter per sub-user,
which is what produces most 407s.
**Storm breaker** - two 407s inside one rung abandons the proxy phase and goes
direct.
**Quarantine** - a node pulled out for the run after three 407s.
**Spot check** - three nodes CONNECTed to a real mail host, so a web-only-healthy
pool is caught.
**Provisional** - a verdict held until a second host or rung agrees.
"""
)

ug_h("The block edition")
st.markdown(
    "Every section of every file is a numbered, named, replaceable block. The markers "
    "are part of the contract."
)
ug_card(
    "Replace a whole block, never edit inside one",
    "The <code># @@BLOCK NNN NAME deps=NNN</code> and <code># @@END NNN NAME</code> pair "
    "is byte-checked. Keep the id and the name identical and the ids ascending.",
    "good",
)
ug_card(
    "Verify after every paste",
    "Block Inspector → Scan the repo, then Run fix self-check. Expect faults=0, no "
    "drift banner, and All checks OK.",
    "good",
)
ug_card(
    "Build tag parity",
    "This page carries the same BUILD_TAG and CFG_VERSION as app.py block 008 on "
    "purpose. verify_v1337.py derives both from app.py's header and fails if they "
    "disagree, so a bug report can never name the wrong build.",
    "",
)

st.divider()
st.caption(
    f"Guide build {BUILD_TAG} · CFG {CFG_VERSION} · results directory: "
    f"`{user_file('mail_results')}`"
)

_nav1, _nav2 = st.columns(2)
with _nav1:
    try:
        st.page_link("app.py", label="🏠 Back to the Checker", width="stretch")
    except Exception:
        st.caption("The checker lives at app.py")
with _nav2:
    try:
        st.page_link("pages/2_Diagnostics.py", label="🔍 Diagnostics", width="stretch")
    except Exception:
        st.caption("Diagnostics lives at pages/2_Diagnostics.py")

st.caption(
    "Every section on this page is a replaceable @@BLOCK - run verify_blocks.py after "
    "every paste."
)
# @@END 016 GLOSSARY_FOOTER
# @@EOF
