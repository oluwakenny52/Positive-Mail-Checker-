#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Bobito Mailbox Reader & Portal Hub
----------------------------------
A Streamlit IMAP client that:
• Discovers folders exhaustively
• Detects bot / OTP messages
• Extracts PINs and verification links
• Cleans message bodies
• Provides per‑message actions (mark read, delete, move, raw view)
• Logs all activity and exports the valid‑account list
"""

import glob
import imaplib
import os
import re
import time
from email import message_from_bytes
from email.header import decode_header

import streamlit as st

# ------------------------------------------------------------------
# 1️⃣ Configuration & Keep‑Alive injector
# ------------------------------------------------------------------
st.set_page_config(
    page_title="Bobito Mailbox Reader & Portal Hub",
    page_icon="📥",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Keep‑alive for mobile/Safari (prevents session drop)
st.markdown(
    """
    <script>
    setInterval(function(){
        fetch('/_stcore/health').then(res => {});
    }, 30000);
    </script>
    """,
    unsafe_allow_html=True,
)

# ------------------------------------------------------------------
# 2️⃣ Session state helpers
# ------------------------------------------------------------------
if "mb_log" not in st.session_state:
    st.session_state.mb_log = []
if "mb_folders" not in st.session_state:
    st.session_state.mb_folders = ["INBOX"]
if "mb_host" not in st.session_state:
    st.session_state.mb_host = ""
if "current_page" not in st.session_state:
    st.session_state.current_page = 0
if "current_messages" not in st.session_state:
    st.session_state.current_messages = []

def log(msg: str) -> None:
    """Insert a new log entry at the top of the list."""
    timestamp = time.strftime("%H:%M:%S")
    st.session_state.mb_log.insert(0, f"[{timestamp}] {msg}")
    st.session_state.mb_log = st.session_state.mb_log[:50]

# ------------------------------------------------------------------
# 3️⃣ Load “valid mail” list
# ------------------------------------------------------------------
def load_valid() -> list:
    """
    Load valid accounts from:
    1. mail_results/valid_*.txt
    2. clean_valid_accounts.txt
    3. valid_accounts.txt
    The file format must be email:password (password can contain a pipe; only the first part is used).
    """
    rows, seen = [], set()
    paths = sorted(glob.glob("mail_results/valid_*.txt"), reverse=True)
    paths += [p for p in ("clean_valid_accounts.txt", "valid_accounts.txt") if os.path.exists(p)]

    for path in paths:
        try:
            with open(path, encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line = line.strip()
                    if ":" not in line:
                        continue
                    email_addr, pwd = line.split(":", 1)
                    combo = f"{email_addr.strip()}:{pwd.split('|')[0].strip()}"
                    if combo not in seen:
                        seen.add(combo)
                        rows.append(combo)
        except Exception:
            continue
    return rows

# ------------------------------------------------------------------
# 4️⃣ Helper functions (IMAP, decoding, extraction, cleanup)
# ------------------------------------------------------------------
def decode_hdr(value: str) -> str:
    """Decode MIME‑encoded header values."""
    try:
        parts = decode_header(value or "")
        return "".join(
            part.decode(charset or "utf-8", errors="ignore")
            if isinstance(part, bytes)
            else part
            for part, charset in parts
        )
    except Exception:
        return str(value or "")

def get_webmail_portal(email: str) -> str:
    """Return the webmail portal URL for a given address."""
    if "@" not in email:
        return "https://mail.google.com"
    domain = email.split("@")[-1].lower()
    portals = {
        "gmail.com": "https://mail.google.com",
        "googlemail.com": "https://mail.google.com",
        "outlook.com": "https://outlook.live.com",
        "hotmail.com": "https://outlook.live.com",
        "live.com": "https://outlook.live.com",
        "yahoo.com": "https://mail.yahoo.com",
        "ymail.com": "https://mail.yahoo.com",
        "icloud.com": "https://www.icloud.com/mail",
        "me.com": "https://www.icloud.com/mail",
        "aol.com": "https://mail.aol.com",
        "zoho.com": "https://mail.zoho.com",
        "proton.me": "https://mail.proton.me",
        "protonmail.com": "https://mail.proton.me",
    }
    return portals.get(domain, f"https://www.{domain}")

def list_folders(mail: imaplib.IMAP4_SSL) -> list:
    """Return all folders discovered via LIST/LSUB + dictionary brute‑force."""
    found = set(["INBOX"])
    common_folders = [
        "INBOX", "Sent", "Sent Items", "Sent Messages", "Trash", "Deleted Items",
        "Junk", "Spam", "Junk E-mail", "Archive", "Archives", "Drafts",
        "Notes", "Important", "Starred", "All Mail", "Bin",
    ]
    for cf in common_folders:
        found.update({cf, cf.upper(), cf.lower()})

    try:
        typ, data = mail.list('""', "*")
        if typ == "OK" and data:
            for item in data:
                if not item:
                    continue
                s = item.decode("utf-8", errors="ignore") if isinstance(item, bytes) else str(item)
                quoted = re.findall(r'"((?:\\.|[^"\\])*)"', s)
                name = quoted[-1] if quoted else s.split()[-1]
                name = name.replace('\\"', '"').strip()
                if name and name not in (".", "/"):
                    found.add(name)
    except Exception:
        pass
    return sorted(list(found), key=lambda x: (0 if x.lower() == "inbox" else 1, x.lower()))

def extract_pins_and_links(text: str) -> tuple[list[str], list[str]]:
    """Return a tuple (pins, links) extracted from the body."""
    # PINs: 4‑8 digit numbers not adjacent to other digits
    pins = re.findall(r'\b(?<![#\d])\d{4,8}(?![#\d])\b', text)
    # URLs: http(s)://… or www.…
    urls = re.findall(r'https?://[^\s<>"]+|www\.[^\s<>"]+', text)
    # Filter out known noisy domains
    cleaned_urls = [u for u in urls if not any(x in u.lower() for x in ["w3.org", "schema.org", "apple.com/DTDs"])]
    return list(dict.fromkeys(pins)), list(dict.fromkeys(cleaned_urls))

def clean_boilerplate(text: str) -> str:
    """Strip common unsubscribe / privacy / confidentiality lines."""
    if not text:
        return ""
    patterns = [
        r"(?i)unsubscribe.*?(?:\n|$)",
        r"(?i)privacy policy.*?(?:\n|$)",
        r"(?i)confidentiality notice.*?(?:\n\n|$)",
        r"(?i)this email was sent by.*?(?:\n|$)",
    ]
    for pat in patterns:
        text = re.sub(pat, "", text)
    return text.strip()

# ------------------------------------------------------------------
# 5️⃣ Main UI – Sidebar
# ------------------------------------------------------------------
st.sidebar.header("⚙️ Account & Connection Hub")

# Load the list of valid accounts
valid_accounts = load_valid()

pick = st.sidebar.selectbox("Select Valid Account", valid_accounts or ["none"])
custom_email = st.sidebar.text_input("Email override")
custom_pass = st.sidebar.text_input("Password override", type="password")
override_host = st.sidebar.text_input("IMAP Host Override")

# Resolve the active credentials
if custom_email.strip():
    email_addr, pw = custom_email.strip(), custom_pass.strip()
elif ":" in pick and pick != "none":
    email_addr, pw = pick.split(":", 1)
else:
    email_addr, pw = "", ""

# Show webmail portal
if email_addr:
    portal_url = get_webmail_portal(email_addr)
    st.sidebar.markdown(f"**Webmail portal:** [Open]({portal_url})")
    st.sidebar.text_input(
        "Copy credentials (email:password)",
        value=f"{email_addr}:{pw}",
        key="cred_copy",
    )

# Connect & discover folders
if st.sidebar.button("🔌 Connect & Discover Folders", type="primary"):
    if not email_addr or not pw:
        st.error("Email and password are required.")
    else:
        hosts = [override_host.strip()] if override_host.strip() else get_hosts(email_addr)
        success, host_used, folders, err_msg = False, "", [], ""
        with st.spinner("Connecting…"):
            for host in hosts:
                try:
                    mail_obj = imaplib.IMAP4_SSL(host, 993, timeout=20)
                    mail_obj.login(email_addr, pw)
                    folders = list_folders(mail_obj)
                    mail_obj.logout()
                    host_used = host
                    success = True
                    break
                except Exception as exc:
                    err_msg = f"{host}: {exc}"
                    try:
                        mail_obj.logout()
                    except Exception:
                        pass
        if success:
            st.session_state.mb_host = host_used
            st.session_state.mb_folders = folders
            log(f"Connected to {host_used} – {len(folders)} folders found.")
            st.sidebar.success(f"Connected: {host_used} ({len(folders)} folders)")
        else:
            st.sidebar.error(f"Connection failed: {err_msg}")
            log(f"Connection failed: {err_msg}")

# ------------------------------------------------------------------
# 6️⃣ Sidebar – Activity log & export
# ------------------------------------------------------------------
st.sidebar.markdown("---")
st.sidebar.subheader("📜 Live Activity Log")
with st.sidebar.expander("Show log", expanded=False):
    for entry in st.session_state.mb_log:
        st.text(entry)

if valid_accounts:
    st.sidebar.markdown("---")
    st.sidebar.subheader("💾 Export Tools")
    export_text = "\n".join(valid_accounts)
    st.sidebar.download_button(
        label="Download Valid Accounts",
        data=export_text,
        file_name="valid_accounts_export.txt",
        mime="text/plain",
    )

# ------------------------------------------------------------------
# 7️⃣ Main panel – Folder explorer & message loader
# ------------------------------------------------------------------
col1, col2, col3 = st.columns([2, 1, 1])

with col1:
    folder = st.selectbox("Select Mail Folder", st.session_state.mb_folders)

with col2:
    page_size = st.slider("Page size", 5, 50, 15)

with col3:
    sort_order = st.selectbox("Sort Order", ["Newest First", "Oldest First"])

# Deep search panel
with st.expander("🔍 Deep Search & Filters", expanded=False):
    search_query = st.text_input("Search term or keyword")
    search_scope = st.selectbox("Search Scope", ["TEXT", "SUBJECT", "FROM", "BODY"])

# ------------------------------------------------------------------
# 8️⃣ Load & display messages
# ------------------------------------------------------------------
if st.button("Load & Search Messages", type="primary"):
    host = override_host.strip() or st.session_state.mb_host or (get_hosts(email_addr)[:1] or [""])[0]
    if not email_addr or not pw or not host:
        st.error("Connect first – you need a host, email and password.")
    else:
        mail = None
        try:
            with st.spinner(f"Fetching messages from {folder}…"):
                mail = imaplib.IMAP4_SSL(host, 993, timeout=20)
                mail.login(email_addr, pw)
                mail.select(f'"{folder}"', readonly=False)

                # Build the SEARCH query
                if search_query.strip():
                    if search_scope == "TEXT":
                        search_cmd = f'TEXT "{search_query.strip()}"'
                    elif search_scope == "SUBJECT":
                        search_cmd = f'SUBJECT "{search_query.strip()}"'
                    elif search_scope == "FROM":
                        search_cmd = f'FROM "{search_query.strip()}"'
                    else:  # BODY
                        search_cmd = f'BODY "{search_query.strip()}"'
                else:
                    search_cmd = "ALL"

                typ, data = mail.search(None, search_cmd)
                ids = (data[0] or b"").split() if typ == "OK" else []

                # Sort
                if sort_order == "Newest First":
                    ids = list(reversed(ids))
                ids = ids[:page_size]

                messages = []
                for mid in ids:
                    typ, msg_data = mail.fetch(mid, "(RFC822)")
                    if typ != "OK" or not msg_data or not isinstance(msg_data[0], tuple):
                        continue
                    raw_bytes = msg_data[0][1]
                    msg_obj = message_from_bytes(raw_bytes)

                    subject = decode_hdr(msg_obj.get("Subject", ""))
                    frm = decode_hdr(msg_obj.get("From", ""))
                    date_val = decode_hdr(msg_obj.get("Date", ""))
                    # Flags – check if seen
                    flags = msg_obj.get_flags() if hasattr(msg_obj, "get_flags") else []
                    is_read = "\\Seen" in flags

                    # Body extraction
                    body_text = ""
                    if msg_obj.is_multipart():
                        for part in msg_obj.walk():
                            if part.get_content_type() == "text/plain":
                                try:
                                    body_text = part.get_payload(decode=True).decode(
                                        part.get_content_charset() or "utf-8", errors="ignore"
                                    )
                                    break
                                except Exception:
                                    pass
                    else:
                        try:
                            body_text = msg_obj.get_payload(decode=True).decode(
                                msg_obj.get_content_charset() or "utf-8", errors="ignore"
                            )
                        except Exception:
                            pass

                    cleaned_body = clean_boilerplate(body_text)
                    pins, links = extract_pins_and_links(body_text)
                    is_bot = is_bot_message(subject, body_text)

                    messages.append(
                        {
                            "id": mid.decode(),
                            "from": frm,
                            "subject": subject,
                            "date": date_val,
                            "is_read": is_read,
                            "is_bot": is_bot,
                            "body": cleaned_body,
                            "pins": pins,
                            "links": links,
                            "raw": raw_bytes,
                        }
                    )

                st.session_state.current_messages = messages
                log(f"Loaded {len(messages)} messages from {folder}")
        except Exception as exc:
            st.error(str(exc))
            log(str(exc))
        finally:
            if mail:
                mail.logout()

# ------------------------------------------------------------------
# 9️⃣ Message actions & display
# ------------------------------------------------------------------
if st.session_state.current_messages:
    # Bot / spam preview + mass delete
    bot_msgs = [m for m in st.session_state.current_messages if m["is_bot"]]
    if bot_msgs:
        st.markdown("---")
        st.subheader(f"🤖 Bot & Security Intelligence Detected ({len(bot_msgs)} messages)")
        if st.button("🗑️ Mass Delete All Detected Bot/Spam Messages"):
            host = override_host.strip() or st.session_state.mb_host or (get_hosts(email_addr)[:1] or [""])[0]
            try:
                mail = imaplib.IMAP4_SSL(host, 993, timeout=20)
                mail.login(email_addr, pw)
                mail.select(f'"{folder}"', readonly=False)
                for bm in bot_msgs:
                    mail.store(bm["id"], "+FLAGS", "\\Deleted")
                mail.expunge()
                mail.logout()
                st.success(f"Deleted {len(bot_msgs)} bot messages!")
                log(f"Mass deleted {len(bot_msgs)} bot messages from {folder}")
                st.rerun()
            except Exception as exc:
                st.error(f"Error during mass delete: {exc}")

    st.markdown("---")
    st.subheader(f"✉️ Message Stream ({len(st.session_state.current_messages)} loaded)")
    for msg in st.session_state.current_messages:
        status_icon = "📖" if msg["is_read"] else "📩"
        bot_badge = " [🤖 BOT/OTP]" if msg["is_bot"] else ""
        with st.expander(f"{status_icon} [{msg['date']}] {msg['from']} – {msg['subject']}{bot_badge}"):
            st.write(f"**From:** {msg['from']}")
            st.write(f"**Subject:** {msg['subject']}")
            st.write(f"**Date:** {msg['date']}")

            if msg["pins"]:
                st.success(f"🔑 **Extracted PINs / Verification Codes:** {', '.join(msg['pins'])}")

            if msg["links"]:
                st.markdown("🔗 **Actionable Verification Links:**")
                for link in msg["links"]:
                    st.markdown(f"- [{link}]({link})", unsafe_allow_html=True)

            st.markdown("---")
            st.text_area("Cleaned Message Body", value=msg["body"], height=150, key=f"body_{msg['id']}")

            # Per‑message actions
            col1, col2, col3, col4 = st.columns(4)
            host = override_host.strip() or st.session_state.mb_host or (get_hosts(email_addr)[:1] or [""])[0]

            with col1:
                if not msg["is_read"]:
                    if st.button("Mark as Read", key=f"read_{msg['id']}"):
                        try:
                            m = imaplib.IMAP4_SSL(host, 993, timeout=20)
                            m.login(email_addr, pw)
                            m.select(f'"{folder}"', readonly=False)
                            m.store(msg["id"], "+FLAGS", "\\Seen")
                            m.logout()
                            st.success("Marked as read!")
                            st.rerun()
                        except Exception as exc:
                            st.error(str(exc))

            with col2:
                target_move = st.selectbox("Move to", st.session_state.mb_folders, key=f"mv_sel_{msg['id']}")
                if st.button("Move Message", key=f"mv_btn_{msg['id']}"):
                    try:
                        m = imaplib.IMAP4_SSL(host, 993, timeout=20)
                        m.login(email_addr, pw)
                        m.select(f'"{folder}"', readonly=False)
                        m.copy(msg["id"], f'"{target_move}"')
                        m.store(msg["id"], "+FLAGS", "\\Deleted")
                        m.expunge()
                        m.logout()
                        st.success(f"Moved to {target_move}!")
                        st.rerun()
                    except Exception as exc:
                        st.error(str(exc))

            with col3:
                if st.button("Delete Message", key=f"del_{msg['id']}"):
                    try:
                        m = imaplib.IMAP4_SSL(host, 993, timeout=20)
                        m.login(email_addr, pw)
                        m.select(f'"{folder}"', readonly=False)
                        m.store(msg["id"], "+FLAGS", "\\Deleted")
                        m.expunge()
                        m.logout()
                        st.success("Deleted message!")
                        st.rerun()
                    except Exception as exc:
                        st.error(str(exc))

            with col4:
                with st.popover("View Raw RFC822"):
                    st.code(msg["raw"].decode("utf-8", errors="ignore"))
else:
    st.info("No messages loaded yet – select a folder and click **Load & Search Messages**.")

# ------------------------------------------------------------------
# 10️⃣ Helper: get_hosts() – fallback if hosts.py missing
# ------------------------------------------------------------------
def get_hosts(email: str) -> list[str]:
    """
    Returns a list of IMAP hosts to try.
    If a `hosts.py` file is present it will use `host_list(email)` from that module.
    Otherwise it falls back to a short hard‑coded list.
    """
    try:
        from hosts import host_list
        return host_list(email)
    except Exception:
        return ["imap.gmail.com", "outlook.office365.com"]

# ------------------------------------------------------------------
# 11️⃣ Run the app
# ------------------------------------------------------------------
if __name__ == "__main__":
    st.experimental_set_query_params()  # Ensure a clean query string
