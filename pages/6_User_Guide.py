# @@FILE pages/6_User_Guide.py blocks=17 version=v13.47
# @@BLOCK 000 FILE_HEADER deps=-
"""
Mega Ultimate Mail Checker - User Guide (v13.47)
================================================
The reference page for the checker. Everything here describes what the
engine ACTUALLY does, in the order you will meet it.

READ THIS FIRST IF YOU ONLY READ ONE THING
------------------------------------------
A single AUTHENTICATIONFAILED is PROVISIONAL. The ladder keeps going -
POP3, the sibling hosts, 143/110, then DIRECT - until a SECOND host agrees
or nothing is left to dial. A lone imap.<domain> box is not authoritative:
it answers AUTHENTICATIONFAILED for mailboxes it has never heard of.

The five buckets that are NOT a verdict on the password:

    LOGIN_DROPPED   server answered, then hung up (* BYE) - untested
    PROXY_UNHEALTHY every attempt died in the 407 proxy hop - untested
    RETRY_LATER     rate limit / greylist / lookup failed - untested
    CONNECTION_FAILED  socket died before LOGIN - untested
    DNS_FAILED      no candidate host resolves - untested

Only VALID, WRONG_PASSWORD and NEED_APP_PASSWORD are answers about the
credential. Treat everything else as "try again differently".
"""
# @@END 000 FILE_HEADER

# @@BLOCK 001 IMPORTS deps=-
import streamlit as st
# @@END 001 IMPORTS

# @@BLOCK 002 PAGE_CONFIG deps=001
# set_page_config MUST be the first Streamlit call in the process.
st.set_page_config(
    page_title="User Guide - Mega Ultimate Mail Checker",
    page_icon="📖",
    layout="wide",
    initial_sidebar_state="collapsed",
)

import auth
from auth import user_file

# require() first, fit() second - the order every page uses.
auth.require(st)
auth.fit(st)
# @@END 002 PAGE_CONFIG

# @@BLOCK 003 BUILD_TAG deps=-
# Mirrors app.py block 008. Keep the two identical.
BUILD_TAG = "v13.47"
CFG_VERSION = 1347
# @@END 003 BUILD_TAG

# @@BLOCK 004 CSS deps=003
st.markdown(
    """
<style>
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
    }
    .ug-hero {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        padding: 22px 26px; border-radius: 14px; margin-bottom: 16px;
        border: 1px solid rgba(255,255,255,.12);
    }
    .ug-hero h1 { color: #fff !important; margin: 0; font-size: 1.65rem; font-weight: 800; }
    .ug-hero p { color: rgba(255,255,255,.93) !important; margin: 8px 0 0 0; font-size: .92rem; }
    .ug-card {
        background: rgba(255,255,255,.04); border: 1px solid rgba(255,255,255,.10);
        border-left: 4px solid #8b5cf6; border-radius: 12px;
        padding: 12px 16px; margin: 10px 0;
    }
    .ug-card h4 { margin: 0 0 6px 0; font-size: .95rem; }
    .ug-card p { margin: 0; font-size: .85rem; line-height: 1.45; opacity: .92; }
    .ug-h { margin: 26px 0 6px 0; font-size: 1.05rem; font-weight: 800;
            border-left: 4px solid #22d3ee; padding-left: 10px; }
    .ug-tag { display: inline-block; padding: 2px 9px; border-radius: 999px;
              font-size: .68rem; font-weight: 800; margin-right: 5px;
              background: rgba(139,92,246,.28); border: 1px solid rgba(139,92,246,.45); }
    .ug-warn { border-left-color: #f59e0b !important; }
    .ug-bad { border-left-color: #ef4444 !important; }
    .ug-good { border-left-color: #22c55e !important; }
</style>
""",
    unsafe_allow_html=True,
)
# @@END 004 CSS

# @@BLOCK 005 HERO deps=004
st.markdown(
    f"""
<div class="ug-hero">
    <h1>📖 User Guide</h1>
    <p>Build {BUILD_TAG} · block edition. What every bucket means, which protocols
    dial what, how the proxy hop fails, and what to do about it.</p>
</div>
""",
    unsafe_allow_html=True,
)
# @@END 005 HERO

# @@BLOCK 006 SECTION_HELPERS deps=005
def ug_h(text: str):
    st.markdown(f'<div class="ug-h">{text}</div>', unsafe_allow_html=True)


def ug_card(title: str, body: str, tone: str = ""):
    cls = "ug-card" + (f" ug-{tone}" if tone else "")
    st.markdown(
        f'<div class="{cls}"><h4>{title}</h4><p>{body}</p></div>',
        unsafe_allow_html=True,
    )
# @@END 006 SECTION_HELPERS

# @@BLOCK 007 QUICKSTART deps=006
ug_h("1 · The short path")

st.markdown(
    "Five steps, in this order. Skipping one is the usual cause of a bad run."
)

ug_card(
    "1. Fetch &amp; Test All Proxies",
    "Sidebar → Proxy Management &amp; Health. Pulls your providers' nodes, tests each one "
    "against a real CONNECT tunnel and arms only the survivors. The button reports how "
    "many passed out of how many lines.",
    "good",
)
ug_card(
    "2. Read the Mail-Destination Spot Check",
    "After every probe cycle the app tunnels three random nodes to a real mail host and "
    "reports the result. If that line shows 407s with zero passes, the pool cannot reach "
    "mail ports even though it passes the web probe. Stop and fix that before you start.",
    "warn",
)
ug_card(
    "3. Paste your combos",
    "Accounts Input → Paste Combos, one <code>email:password</code> per line, or upload a "
    ".txt. The pre-filter buckets junk (typos, disposables, dead domains) before the "
    "engine ever dials.",
    "",
)
ug_card(
    "4. Apply Settings",
    "Sidebar → 💾 Apply Settings. The engine reads the APPLIED config, not the widgets. "
    "If you see the orange 'unapplied changes' warning, you have not applied yet.",
    "warn",
)
ug_card(
    "5. Start, then walk away",
    "🔥 Start Live Checking Engine. Do not touch the tab. Backgrounding it, or any "
    "sidebar click, triggers a Streamlit rerun and the run is saved as unfinished.",
    "bad",
)
# @@END 007 QUICKSTART

# @@BLOCK 008 WHAT_IT_DOES deps=006
ug_h("2 · What the engine actually does")

st.markdown(
    "For each account the engine resolves candidate hosts for the domain, then walks a "
    "ladder of protocol and port rungs. A rung is only ever one of three things: an "
    "answer, a provisional answer, or no answer at all."
)

ug_card(
    "Post-auth verification",
    "A login alone is not enough. After authentication the engine selects INBOX read-only "
    "and issues a NOOP. A node that intercepts the handshake but never had the mailbox "
    "fails here, which is why a 'valid' means the mailbox really opened.",
    "good",
)
ug_card(
    "Provisional WRONG, confirmed across hosts",
    "The first AUTHENTICATIONFAILED is held. The ladder continues until a second "
    "independent host agrees, a second rung of the same host agrees, or nothing is left "
    "to dial. Turn the sidebar guard off only when raw speed beats accuracy.",
    "",
)
ug_card(
    "Local-part username retry",
    "Legacy Zimbra / cPanel / Dovecot fronts want <code>user</code>, not "
    "<code>user@domain</code>. On an auth rejection the engine keeps the node and retries "
    "the same host with the local part before it will call the host tested.",
    "",
)
ug_card(
    "Fast-Mode cooldown",
    "In Fast Mode a domain that told us NOTHING is backed off. A domain that gave a real "
    "answer is never backed off, so a real verdict is never lost to the cooldown.",
    "",
)
# @@END 008 WHAT_IT_DOES

# @@BLOCK 009 BUCKETS deps=006
ug_h("3 · Every bucket, and whether it is an answer")

st.markdown("**Answers about the credential**")
ug_card("✅ VALID", "Authenticated and the mailbox opened. The only bucket worth "
                    "harvesting.", "good")
ug_card("❌ WRONG_PASSWORD", "Confirmed across hosts or rungs, or with nothing left to "
                             "dial. On Gmail/Yahoo the row also carries an app-password "
                             "note when the password does not look like one.", "bad")
ug_card("🔐 NEED_APP_PASSWORD", "The provider wants an app password or a token. Correct "
                                "password, wrong auth method - do not discard.", "warn")

st.markdown("**Not answers - retry these**")
ug_card("🚪 LOGIN_DROPPED", "The server accepted LOGIN then closed the socket (* BYE) on "
                            "every attempt. Usually a rejected password or an "
                            "app-password wall. Retry from a different IP before "
                            "discarding.", "warn")
ug_card("🩹 PROXY_UNHEALTHY", "Every attempt died in the 407 proxy hop. The mailbox was "
                              "never reached, so the password is still untested.", "warn")
ug_card("🕓 RETRY_LATER", "Rate limit, greylist, lookup failed, service unavailable.", "warn")
ug_card("🔌 CONNECTION_FAILED", "Socket died before LOGIN was issued.", "warn")
ug_card("🛰 DNS_FAILED", "No candidate host resolves. Often a dead or parked domain.", "warn")
ug_card("🚫 RBL_BLOCKED", "The mail server flagged the egress IP. The password is "
                          "untested; the IP is the problem.", "warn")
ug_card("❓ UNCLASSIFIED", "Answered, but nothing matched a known signature.", "")
ug_card("⏭ SKIPPED", "Bad format, disposable, or Fast-Mode cooldown. Counted as checked, "
                     "never dialled.", "")
# @@END 009 BUCKETS

# @@BLOCK 010 PROTOCOLS deps=006
ug_h("4 · Protocols and ports")

st.markdown(
    "The picker in the sidebar decides which rungs the engine may dial. Default is "
    "**IMAP + POP3**, and that default is deliberate."
)

ug_card(
    "IMAP - 993 TLS, then 143 STARTTLS, then 143 plain",
    "The primary path. 993 first, always. The 143 rungs get a short leash because cloud "
    "egress often firewalls them.",
    "",
)
ug_card(
    "POP3 - 995 TLS, then 110 STLS, then 110 plain",
    "A completely independent code path: different port, different daemon, different "
    "reputation bucket. This is the only real fallback when a legacy IMAP front hangs up "
    "with * BYE.",
    "good",
)
ug_card(
    "SMTP - 587, 465, 25",
    "CONFIRM-ONLY. A 535 raises WRONG, but a soft error never lowers an existing verdict. "
    "Useful as corroboration, useless as a first opinion.",
    "",
)
ug_card(
    "ManageSieve - 4190",
    "CONFIRM-ONLY, same credentials. Occasionally open on boxes where IMAP is nailed "
    "shut.",
    "",
)
ug_card(
    "Zero-access providers",
    "Proton, Tuta and friends have no IMAP at all. They are bucketed NEED_APP_PASSWORD "
    "immediately rather than being dialled into a timeout.",
    "warn",
)
# @@END 010 PROTOCOLS

# @@BLOCK 011 PROXY_MODES deps=006
ug_h("5 · Proxy modes")

ug_card(
    "fallback (default)",
    "Proxy first, DIRECT second. The universal setting and the right one for almost "
    "everyone.",
    "good",
)
ug_card(
    "aggressive",
    "Proxy only. Faster, but a 407-flooded pool burns the whole account window. The 407 "
    "storm breaker still forces a DIRECT bypass mid-rung.",
    "",
)
ug_card(
    "sticky",
    "One node per worker thread for the life of the thread. Good when a provider meters "
    "per session.",
    "",
)
ug_card(
    "off",
    "Never touch a proxy. The only mode that can finish a run through a provider-wide "
    "email-server cap. Your own IP gets hammered instead.",
    "warn",
)
ug_card(
    "The 407 rule",
    "A 407 is the PROXY rejecting your credentials - usually a per-sub-user cap, not a "
    "dead node. A socket reset is a different event and is reported separately. Three 407 "
    "strikes quarantine a node; two inside one rung trip the storm breaker to DIRECT.",
    "bad",
)
# @@END 011 PROXY_MODES

# @@BLOCK 012 CONCURRENCY deps=006
ug_h("6 · Concurrency governors")

st.markdown(
    "Four gates, each holding a semaphore the engine must pass before a socket opens."
)

ug_card("Per-Proxy-SUBUSER cap (default 1)",
        "The single most important 407 control. Providers meter per sub-user, so this is "
        "the gate that keeps you under the cap.", "good")
ug_card("Per-Proxy-IP cap (default 1)", "Caps simultaneous tunnels through one IP.", "")
ug_card("Per-Host cap (default 2)",
        "Stops fifty workers slamming one IMAP box. 2 is right for legacy ISP IMAP.", "")
ug_card("Global proxy cap (default 4)", "Total simultaneous tunnels for the run. The "
                                        "prober shares it.", "")
ug_card("Raising them",
        "Raising a cap without raising the others just moves the queue. Raise the sub-user "
        "cap last, and only if the spot check is clean.", "warn")
# @@END 012 CONCURRENCY

# @@BLOCK 013 DISPLAY_FIT deps=006
ug_h("7 · Display Fit")

st.markdown(
    "The 🔎 Display Fit box sits directly under the header on the home page and starts "
    "closed, so it never eats the fold on a phone."
)

ug_card(
    "Font size and content scale",
    "Two sliders. Font size sets the base type size; content scale zooms the whole "
    "container. They are applied as CSS, so nothing re-renders when you drag.",
    "",
)
ug_card(
    "♻️ Reset Defaults restores them",
    "Font 16 and scale 100. Because the sliders already exist by the time a reset runs, "
    "the pair is restored through a one-shot flag that the next run consumes before the "
    "sliders are rebuilt - assigning the keys in place would raise a duplicate-key error.",
    "good",
)
ug_card(
    "If the box opens by itself",
    "A stale tab from before the redeploy. Hard-refresh before assuming a fault.",
    "warn",
)
# @@END 013 DISPLAY_FIT

# @@BLOCK 014 TROUBLESHOOTING deps=006
ug_h("8 · Troubleshooting")

ug_card(
    "Red: TypeError: Importing a module script failed",
    "Not a Python error and not this app. Safari/iOS WebView says that when a lazy-loaded "
    "JavaScript chunk 404s, and a redeploy changes every chunk hash. Hard-refresh "
    "(Ctrl/Cmd+Shift+R) with the tab open.",
    "warn",
)
ug_card(
    "Alive: 0 after Fetch &amp; Test",
    "No node passed the tunnel probe. Press it again; if it stays at zero, your provider "
    "is refusing CONNECT. Check the spot-check line and the probe histogram.",
    "bad",
)
ug_card(
    "Spot check 407s but the web probe passes",
    "The provider is capping email-server destinations specifically. Set Proxy Mode to off "
    "or wait for the cap to reset. Those passwords are still untested, not wrong.",
    "bad",
)
ug_card(
    "Every account lands in LOGIN_DROPPED",
    "A server-side hang-up, not a network fault. Confirm the protocol picker includes "
    "POP3, then retry from a different IP.",
    "warn",
)
ug_card(
    "Engine stops mid-run",
    "The reason is written to the unfinished file and shown in the summary. Use Resume "
    "Unfinished - nothing checked is re-dialled.",
    "",
)
ug_card(
    "Download the diagnostic bundle",
    "Deep Diagnostics → Download bundle. It carries the environment, pool state, per-node "
    "table and the raw proxy lines. Paste it back with any report.",
    "good",
)
# @@END 014 TROUBLESHOOTING

# @@BLOCK 015 BLOCK_EDITION deps=006
ug_h("9 · The block edition")

st.markdown(
    "Every section of every file is a numbered, named, replaceable block. The markers are "
    "part of the contract."
)

ug_card("Replace a whole block, never edit inside one",
        "The <code># @@BLOCK NNN NAME deps=NNN</code> and <code># @@END NNN NAME</code> "
        "pair is byte-checked. Keep the id and the name identical and the ids ascending.",
        "good")
ug_card("deps= lists what a block reads",
        "If you change a name a block publishes, every dependent block must be reissued "
        "with it.", "")
ug_card("Verify after every paste",
        "Block Inspector → Scan the repo, then Run fix self-check. Expect faults=0, no "
        "drift banner, and All checks OK.", "good")
ug_card("Build tag parity",
        "This page carries the same BUILD_TAG as app.py block 008 on purpose, so a bug "
        "report can never name the wrong build.", "")
# @@END 015 BLOCK_EDITION

# @@BLOCK 016 FOOTER deps=003,015
st.markdown("---")
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
# @@END 016 FOOTER
# @@EOF
