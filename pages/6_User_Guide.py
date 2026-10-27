# @@FILE pages/6_User_Guide.py blocks=17 version=v13.40
# @@BLOCK 000 FILE_HEADER deps=-
"""
pages/6_User_Guide.py - User Guide  (v13.40)
============================================
Everything the app can do, in one read-only page: every sidebar control, every
button, every verdict the engine can return, every other page, and what each one
is FOR - so a first-time user knows what a thing does before pressing it.

No mailbox connection. No proxy credit. No file writes. Pure reference.
"""

import os
import sys
from datetime import datetime

import streamlit as st
# @@END 000 FILE_HEADER


# @@BLOCK 001 PAGE_CONFIG deps=000
st.set_page_config(page_title="User Guide - Mail Checker", page_icon="📖",
                   layout="wide", initial_sidebar_state="collapsed")
# @@END 001 PAGE_CONFIG


# @@BLOCK 002 SYSPATH_AND_BUILD deps=000
THIS_DIR = os.path.dirname(os.path.abspath(__file__))
APP_DIR = os.path.dirname(THIS_DIR)
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

# Keep in step with app.py block 008 (BUILD_TAG). Bump both together.
BUILD_TAG = "v13.40"
# @@END 002 SYSPATH_AND_BUILD


# @@BLOCK 003 THEME deps=002
import json


def _load_theme():
    base = {"bg": "#0b1020", "panel": "#141b30", "text": "#e6ebff",
            "accent": "#8b5cf6", "accent2": "#22d3ee", "g1": "#667eea", "g2": "#764ba2"}
    for cand in (os.path.join(APP_DIR, "theme.json"), "theme.json"):
        try:
            if os.path.exists(cand):
                with open(cand, encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    base.update({k: v for k, v in data.items()
                                 if k in base and isinstance(v, str)})
                break
        except Exception:
            continue
    return base


_TH = _load_theme()
# @@END 003 THEME


# @@BLOCK 004 CSS deps=003
st.markdown(
    f"""
<style>
    .ug-hero {{
        background: linear-gradient(135deg, {_TH['g1']} 0%, {_TH['g2']} 100%);
        padding: 18px 24px; border-radius: 14px; margin-bottom: 14px;
        border: 1px solid rgba(255,255,255,.12);
    }}
    .ug-hero h1 {{ color: #fff !important; margin: 0; font-size: 1.45rem; font-weight: 800; }}
    .ug-hero p {{ color: rgba(255,255,255,.92) !important; margin: 6px 0 0 0; font-size: .84rem; }}
    .ug-card {{
        background: {_TH['panel']}; border: 1px solid rgba(255,255,255,.10);
        border-left: 4px solid {_TH['accent']}; border-radius: 12px;
        padding: 10px 14px; margin: 8px 0;
    }}
    .ug-card h4 {{ margin: 0 0 4px 0; font-size: .92rem; }}
    .ug-card p {{ margin: 0; font-size: .8rem; opacity: .9; }}
    .block-container {{ padding-top: 1.2rem !important; padding-bottom: 2rem !important; }}
    @media (max-width: 820px) {{
        .block-container {{ padding: .55rem .7rem 1.3rem .7rem !important; }}
        .ug-hero h1 {{ font-size: 1.12rem; }}
        pre, code {{ font-size: .68rem !important; }}
    }}
</style>
""",
    unsafe_allow_html=True,
)
# @@END 004 CSS


# @@BLOCK 005 HERO deps=004
st.markdown(
    '<div class="ug-hero"><h1>📖 User Guide</h1>'
    '<p>What every control does, what every button does, what every verdict means, '
    'and which page does what. Nothing here connects anywhere.</p></div>',
    unsafe_allow_html=True,
)
# @@END 005 HERO


# @@BLOCK 006 TABS deps=005
(_t1, _t2, _t3, _t4, _t5, _t6, _t7, _t8) = st.tabs([
    "🚀 Getting started", "🎛 Sidebar controls", "🔘 Every button",
    "🏷 What a verdict means", "📦 Downloads & buckets", "🧭 The other pages",
    "⚙ How the engine works", "🩺 Troubleshooting",
])
# @@END 006 TABS


# @@BLOCK 007 TAB_GETTING_STARTED deps=006
with _t1:
    st.markdown(
        """
### The 4 steps that actually run a check

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

### Before you press Start, know these three defaults

* **Confirm a WRONG verdict across hosts = ON.** One
  `AUTHENTICATIONFAILED` is treated as *provisional* - the ladder keeps dialling
  other hosts and rungs before accepting it. This is why a run is slower than a
  one-shot checker, and why it finds fewer false "wrong password" results.
* **Pick Protocols Mode = IMAP + POP3.** POP3 is the only genuinely independent
  path when a legacy IMAP front answers LOGIN with `* BYE` and hangs up.
* **Quarantine nodes that return 407 = ON.** A node that answers
  `407 Proxy Authentication Required` three times is pulled out of the pool for
  the run. A plain socket reset is **not** a 407 and does not quarantine.

### What costs proxy credit

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
# @@END 007 TAB_GETTING_STARTED


# @@BLOCK 008 TAB_SIDEBAR deps=006
with _t2:
    st.markdown("Every sidebar control, what it does, and when to touch it.")
    st.markdown(
        """
#### Engine

| Control | What it does |
|---|---|
| **Select Engine Mode** | `Normal` = balanced. `Fast` = fewer rungs, shorter deadline, 100 workers. `Deep` = 4 hosts/domain, 400 s deadline, strict. |
| **Workers Start** | Parallel accounts. Auto-scales when *Thread Auto-Scaling* is on and the list is large. |
| **Deadline (Seconds)** | Wall-clock budget **per account**, split between the proxy phase and the direct phase. |
| **Timeout** | Per-attempt socket timeout. |
| **Max Accounts** | Truncates the queue. `0` = unlimited. |
| **Blacklist CF** | Consecutive network failures before a node is circuit-broken for 30 s. |

#### Protocols

| Control | What it does |
|---|---|
| **Pick Protocols Mode** | Which protocols may be dialled. `IMAP` and `POP3` are real verdict sources. `SMTP` and `ManageSieve` are **CONFIRM-ONLY** - a failure never lowers a verdict. |
| **Enable STARTTLS + plaintext fallback** | Adds 143/110 rungs after implicit TLS fails. They get a shorter leash (8 s) because 143/110 are often firewalled from cloud egress. |

#### Rules

| Control | What it does |
|---|---|
| **Thread Auto-Scaling** | Lets the engine grow/shrink workers with list size. |
| **Max Hosts Per Domain** | How many discovered IMAP hosts to try. 143/110 and POP rungs are capped separately. |
| **Try local-part username on auth failure** | On an auth rejection, retries the **same** host as `user` instead of `user@domain`. Fires on `* BYE` too. Not applied to SMTP. |
| **Confirm a WRONG verdict across hosts** | The guard. ON = provisional WRONG until a second host or rung agrees. OFF = one-rung, faster, more false wrongs. |
| **Enable SMTP pre-check** | A reachability banner probe on 587/465/25 only - never authenticates. |
| **Custom Whitelist / Blacklist Domains** | Comma-separated domain filters applied before the ladder. |

#### Proxy / pool

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

#### Concurrency governors

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

#### Switches

| Control | What it does |
|---|---|
| **Use Proxy** | OFF = fully direct. |
| **Retry CF (Direct Retry)** | One extra direct pass after a proxy network error. |
| **Allow Self-Signed** | **A real switch.** Ticked = accept unverified. Unticked = verify, and if that fails the handshake is retried unverified *unless* `TLS_STRICT`. |
| **Test Flight** | Probe every node before it enters the pool. Keep it ON. |
| **Skip Strict App-Only Providers** | Buckets Gmail/O365 away instead of checking them. |
| **Enable Debug Mode** | Verbose log cap (400 vs 120). |
| **Proxy Mode Engine** | `aggressive` proxy-only · `fallback` proxy then direct (default) · `sticky` one node per worker · `off` never proxy. With a provider-wide 407, `off` is the only mode that finishes. |

#### Buttons at the bottom of the sidebar

| Button | What it does |
|---|---|
| **💾 Apply Settings** | Commits the sidebar into the running config and rebuilds the concurrency gates. Nothing changes until you press it. |
| **♻️ Reset Defaults** | Restores every control to the universal default (protocols back to IMAP + POP3). |
| **🎨 Theme Studio** | Presets, colours, radius, glow, animated gradient, colourised logs, hero text. |
"""
    )
# @@END 008 TAB_SIDEBAR


# @@BLOCK 009 TAB_BUTTONS deps=006
with _t3:
    st.markdown("Every button in the app, in the order you will meet it.")
    st.markdown(
        """
#### Main page

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

#### Export Studio (`pages/4`)

| Button | What it does |
|---|---|
| **⬇️ Download <name>** | The template-rendered text. |
| **⬇️ Download CSV / JSON / ZIP** | The same selection in another format. |
| **⬇️ <STATUS>.txt** | One file per status, inside the "Per-status split" tab. |
| **Save preset / Apply** | Stores and re-applies the whole format configuration. |

#### Block Inspector (`pages/5`)

| Button | What it does |
|---|---|
| **🔁 Re-scan now** | Re-audits the frame of every block file. |
| **✅ Validate paste** | Runs the same verifier on a pasted file before you commit it. |
| **🛠 Canonicalise** | Names every bare `@@END` from its `@@BLOCK`, then offers the fixed file to download. |
| **🧪 Run fix self-check** | Proves the behavioural fixes are still textually present. |

#### Diagnostics (`pages/2`) - all read-only

**▶ Probe all targets**, **Run full discovery**, **Probe SMTP candidates**,
**🧹 Clear hosts_cache.json**, **♻️ Refresh this domain**, **📋 Build copy/paste bundle**.
"""
    )
# @@END 009 TAB_BUTTONS


# @@BLOCK 010 TAB_VERDICTS deps=006
with _t4:
    st.markdown(
        """
### What each verdict means

**A verdict is about the password, not about the proxy.** Anything that died in
the proxy hop never tested the password, and the engine says so.

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

### Three that are easy to confuse

* `LOGIN_DROPPED` **is not** `WRONG`. The host spoke; the password is untested.
* `PROXY_UNHEALTHY` **is not** `CONNECTION_FAILED`. The node rejected *you*.
* `APP` **is not** `WRONG`. The password may be perfectly correct.

The detail line on every result names the protocol, host, port and the proxy
tag, so you can always tell which of the three happened.
"""
    )
# @@END 010 TAB_VERDICTS


# @@BLOCK 011 TAB_DOWNLOADS deps=006
with _t5:
    st.markdown(
        """
### Buckets, files and where to get them

A run writes one file per bucket into `mail_results/`, stamped
`YYYYMMDD_HHMMSS`, plus `clean_valid_accounts.txt` (merged, de-duplicated) and a
`mail_results_<stamp>.zip`.

| Where | What you get |
|---|---|
| Main page, `📦 Download All Results` | Everything as one ZIP. |
| Main page, results summary expanders | One expander per bucket, in-app. |
| **Export Studio → Sources** | Pick **any combination** of session buckets and result files. |
| **Export Studio → Per-status split** | One download per status. |
| **Export Studio → CSV / JSON / ZIP** | The same selection in another shape. |

### If Export Studio only offers valid accounts

That is the `Sources` box in its sidebar. It is a **multi-select** - tap it and
add `Session · wrong_results`, `Session · conn_results`, and so on, or pick the
`mail_results/...` files directly. Nothing is filtered out.

### Presets

Set the format once, type a name, `Save preset`. Next time, `Load preset` →
`Apply`. Presets live in `download_presets.json` next to `app.py`, so on a cloud
deploy they reset on redeploy.
"""
    )
# @@END 011 TAB_DOWNLOADS


# @@BLOCK 012 TAB_PAGES deps=006
with _t6:
    st.markdown(
        """
### The other pages

| Page | What it is | Costs |
|---|---|---|
| **Main** (`app.py`) | The checker: settings, input, run, results, in-app reader. | proxy credit |
| **`pages/2_Diagnostics.py`** | Read-only. Shows the **exact rung order** the engine will dial for a domain, live TCP probes on 993/143/995/110, MX/SRV discovery, SMTP candidates, a `proxies.txt` audit, and cache tools. | zero |
| **`pages/3_Mailbox_Reader.py`** | Bulk inbox reader: folders, OTP scanner, card/credential scanner, bot purge, per-message actions. | proxy credit |
| **`pages/4_Downloads.py`** | Export Studio. Text / CSV / JSON / ZIP / per-status split, with filters, sorting, dedupe and presets. | zero |
| **`pages/5_Blocks.py`** | Block Inspector. Frame audit, paste validation, `@@END` canonicaliser, fix self-check. | zero |
| **`pages/6_User_Guide.py`** | This page. | zero |

Start with **Diagnostics** for one domain if a run is behaving oddly - it tells
you whether the host, the port or the path is the problem, before you spend a
single proxy request.
"""
    )
# @@END 012 TAB_PAGES


# @@BLOCK 013 TAB_HOW_IT_WORKS deps=006
with _t7:
    st.markdown(
        """
### The pipeline, in order

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

### What "CONFIRM-ONLY" means

SMTP and ManageSieve can only ever *add* a verdict. If SMTP says 535, that is a
real answer. If SMTP fails for any other reason, the verdict is untouched.
"""
    )
# @@END 013 TAB_HOW_IT_WORKS


# @@BLOCK 014 TAB_TROUBLESHOOT deps=006
with _t8:
    st.markdown(
        """
### Symptom → cause

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

### Getting help

Sidebar → `🔬 Deep Diagnostics` → `⬇️ Download bundle`. It contains the
environment, the live config, the raw `proxies.txt` lines, the probe histogram,
the quarantine state and the last 60 probe events. Proxy credentials are
visible in it - rotate them if you paste it publicly.
"""
    )
# @@END 014 TAB_TROUBLESHOOT


# @@BLOCK 015 GLOSSARY deps=014
st.divider()
st.markdown(
    f"""
### Glossary

**Rung** - one `protocol host:port tls-mode` attempt in the ladder.
**Guard** - the cross-host WRONG confirmation. **Confirm-only** - a protocol that
can only add a verdict, never lower one. **407** - the *proxy* rejected your
credentials, not the mail server. **Sub-user** - the username half of a proxy
line; providers meter per sub-user, which is what produces most 407s.
**Storm breaker** - two 407s inside one rung abandons the proxy phase and goes
direct. **Quarantine** - a node pulled out for the run after three 407s.
**Spot check** - three nodes CONNECTed to a real mail host, so a web-only-healthy
pool is caught. **Provisional** - a verdict held until a second host or rung
agrees. Confirm-only rungs never create a WRONG from a single host on their own, but a definitive SMTP/Sieve auth error does raise WRONG directly.

Build **{BUILD_TAG}** - a frame-audited block edition. Every section is a named,
numbered, replaceable `@@BLOCK`.
"""
)
# @@END 015 GLOSSARY


# @@BLOCK 016 TRAILING deps=015
# (reserved tail - keeps the file closed after the last block)
# @@END 016 TRAILING
# @@EOF
