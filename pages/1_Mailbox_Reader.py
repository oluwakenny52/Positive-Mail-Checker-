import streamlit as st
import imaplib
import email
from email.header import decode_header
import os
import glob
import pandas as pd
import warnings

warnings.filterwarnings("ignore")

# Keep-Alive Injector Script
st.markdown(
    """
    <script>
    // Simple Streamlit Keep-Alive Poller
    setInterval(function() {
        fetch('/_stcore/health').then(function(res) {
            // Ping to maintain connection
        }).catch(function(err) {});
    }, 25000);
    </script>
    """,
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
        
        # Explicit Provider Configurations for custom and major hosts
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
        
        # Explicit Portal URL Configurations
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
        if domain in mapping:
            return mapping[domain]
        else:
            return f"https://mail.{domain}"
    except Exception:
        return "https://google.com"

# Main Page Interface
st.title("📥 Mailbox Reader & Webmail Portal Hub")
st.markdown("Connects to verified valid IMAP inboxes or launches direct Webmail portal access with smart credential helpers.")

valid_accs = load_valid_accounts()

st.sidebar.header("⚙ Reader & Portal Configuration")
selected_account = st.sidebar.selectbox("Select Valid Account", options=valid_accs if valid_accs else ["No valid accounts found"], key="mb_selected_account")

custom_email = st.sidebar.text_input("Or enter custom email", key="mb_custom_email")
custom_pass = st.sidebar.text_input("Or enter custom password", type="password", key="mb_custom_pass")

target_email = custom_email.strip() if custom_email.strip() else (selected_account.split(":")[0] if ":" in selected_account else "")
target_pass = custom_pass.strip() if custom_pass.strip() else (selected_account.split(":")[1] if ":" in selected_account else "")

# Sync session state with target inputs so other modules or background checks can reuse them
st.session_state['email'] = target_email
st.session_state['password'] = target_pass

server_host = st.sidebar.text_input("IMAP Server Host (Leave blank for auto-detect)", value="", key="mb_server_host")
search_keyword = st.sidebar.text_input("Keyword Filter (Optional)", value="", placeholder="e.g. Netflix, Reset, Code", key="mb_search_keyword")
max_msgs = st.sidebar.slider("Max Messages to Fetch", min_value=1, max_value=50, value=10, key="mb_max_msgs")

# Main Action Controls
connect_col, _ = st.columns([1, 1])
with connect_col:
    connect_pressed = st.button("📥 Connect & Read IMAP Inbox", type="primary", key="mb_connect_btn")

# Smart Webmail / Portal Quick Action Section
if target_email:
    portal_url = get_webmail_portal_url(target_email)
    st.markdown("---")
    st.subheader("🌐 Webmail & Portal Quick Access")
    col_w1, col_w2 = st.columns([2, 2])
    with col_w1:
        st.markdown(f"**Target Webmail URL:** `{portal_url}`")
        st.link_button("🔗 Open Webmail Portal in New Tab", portal_url, use_container_width=True)
    with col_w2:
        st.markdown(f"**Selected Combo:** `{target_email}:{target_pass}`")
        st.info("💡 Tip: Click the webmail button to open the login portal. You can copy your password directly from the details above.")
    st.markdown("---")

if connect_pressed:
    if not target_email or not target_pass:
        st.warning("⚠️️ Please select or enter a valid email and password.")
    else:
        host = server_host.strip() if server_host.strip() else guess_imap_server(target_email)
        st.session_state['imap_host'] = host
        
        st.info(f"Connecting to IMAP server **{host}:993** for **{target_email}**...")
        
        try:
            mail = imaplib.IMAP4_SSL(host, 993, timeout=10)
            mail.login(target_email, target_pass)
            mail.select("INBOX")
            
            if search_keyword.strip():
                status, response = mail.search(None, f'(SUBJECT "{search_keyword.strip()}")')
            else:
                status, response = mail.search(None, "ALL")
                
            if status != "OK":
                st.error("Failed to search mailbox messages.")
            else:
                msg_nums = response[0].split()
                if not msg_nums:
                    st.warning("No messages found matching criteria.")
                else:
                    latest_nums = msg_nums[-max_msgs:][::-1]
                    table_data = []
                    
                    for num in latest_nums:
                        st_fetch, msg_data = mail.fetch(num, "(RFC822)")
                        if st_fetch != "OK":
                            continue
                        for response_part in msg_data:
                            if isinstance(response_part, tuple):
                                msg = email.message_from_bytes(response_part[1])
                                
                                # Subject
                                sub_hdr = decode_header(msg.get("Subject", "No Subject"))[0]
                                subject = sub_hdr[0].decode(sub_hdr[1] or "utf-8", errors="ignore") if isinstance(sub_hdr[0], bytes) else str(sub_hdr[0])
                                
                                # Sender
                                from_hdr = decode_header(msg.get("From", "Unknown"))[0]
                                sender = from_hdr[0].decode(from_hdr[1] or "utf-8", errors="ignore") if isinstance(from_hdr[0], bytes) else str(from_hdr[0])
                                
                                date_str = msg.get("Date", "Unknown")
                                
                                body = ""
                                if msg.is_multipart():
                                    for part in msg.walk():
                                        if part.get_content_type() == "text/plain":
                                            payload = part.get_payload(decode=True)
                                            if payload:
                                                body = payload.decode("utf-8", errors="ignore")
                                                break
                                else:
                                    payload = msg.get_payload(decode=True)
                                    if payload:
                                        body = payload.decode("utf-8", errors="ignore")
                                        
                                table_data.append({
                                    "ID": num.decode(),
                                    "Date": date_str,
                                    "From": sender,
                                    "Subject": subject,
                                    "Snippet": body[:300].strip()
                                })
                                
                    mail.logout()
                    
                    if table_data:
                        st.success(f"Successfully retrieved {len(table_data)} messages!")
                        df = pd.DataFrame(table_data)
                        st.dataframe(df, use_container_width=True)
                        
                        # Expandable message view
                        for idx, row in df.iterrows():
                            with st.expander(f"✉ [{row['Date']}] {row['From']} - {row['Subject']}"):
                                st.markdown(f"**From:** {row['From']}")
                                st.markdown(f"**Subject:** {row['Subject']}")
                                st.markdown(f"**Date:** {row['Date']}")
                                st.markdown("---")
                                st.text(row['Snippet'])
                    else:
                        st.info("No readable messages extracted.")
                        
        except Exception as ex:
            st.error(f"Connection / Authentication Error: {ex}")
