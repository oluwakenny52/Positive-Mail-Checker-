import streamlit as st
import imaplib
import email
from email.header import decode_header
import re
import os
import glob
import json
import time
import urllib.parse
import random
import string

# --- 1. CONFIGURATION & BRANDING ---

st.set_page_config(
    page_title="Bobito Mailbox Reader & Portal Hub",
    page_icon="📬",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for Mobile/Desktop responsiveness and UI polish
st.markdown("""
<style>
    /* Keep-alive visual indicator */
    .keepalive-status {
        font-size: 0.8rem;
        color: green;
        float: right;
    }
    
    /* Message Card Styling */
    .message-card {
        border: 1px solid #e0e0e0;
        border-radius: 8px;
        padding: 15px;
        margin-bottom: 10px;
        background-color: #fafafa;
    }
    
    /* PIN Badge */
    .pin-badge {
        display: inline-block;
        padding: 2px 8px;
        border-radius: 4px;
        background-color: #e3f2fd;
        color: #1565c0;
        font-weight: bold;
        font-family: monospace;
        margin-right: 5px;
    }

    /* Link Button */
    .link-btn {
        display: inline-block;
        padding: 4px 12px;
        border-radius: 4px;
        background-color: #e8f5e9;
        color: #2e7d32;
        text-decoration: none;
        font-size: 0.9rem;
        margin-top: 5px;
    }

    /* Sidebar Styling */
    .sidebar .stTextInput input {
        background-color: #ffffff;
    }
</style>
""", unsafe_allow_html=True)

# Keep-Alive Script for Mobile/Safari
st.markdown(
    """
    <script>
    function keepAlive() {
        const url = window.location.href;
        // Simple ping to prevent session drop on idle mobile devices
        fetch(url, { method: 'HEAD', cache: 'no-cache' }).catch(() => {});
        setTimeout(keepAlive, 60000); // Every 60 seconds
    }
    keepAlive();
    </script>
    """,
    unsafe_allow_html=True
)

# --- 2. HELPER FUNCTIONS & LOGIC ---

# Fallback host list if hosts.py is missing or empty
DEFAULT_HOSTS = ["imap.gmail.com", "outlook.office365.com", "imap-mail.outlook.com", "imap.aol.com"]

def get_hosts(email):
    try:
        from hosts import host_list
        return host_list(email)
    except ImportError:
        return DEFAULT_HOSTS[:2] # Fallback to Gmail/Outlook if file missing

# Webmail Domain Mapper
WEBMAIL_MAP = {
    "gmail.com": "https://mail.google.com",
    "yahoo.com": "https://mail.yahoo.com",
    "outlook.com": "https://outlook.live.com",
    "hotmail.com": "https://outlook.live.com",
    "icloud.com": "https://www.icloud.com/mail",
    "aol.com": "https://mail.aol.com"
}

def get_webmail_url(email):
    domain = email.split("@")[-1].lower() if "@" in email else ""
    return WEBMAIL_MAP.get(domain, None)

# Credential String Generator
def generate_credential_string(email, password):
    return f"{email}:{password}"

# --- 3. EMAIL PROCESSING ENGINES ---

def decode_mime_header(header_value):
    """Decodes RFC2047 encoded headers."""
    if not header_value:
        return ""
    try:
        decoded_parts = decode_header(header_value)
        decoded_str = []
        for part, charset in decoded_parts:
            if isinstance(part, bytes):
                decoded_str.append(part.decode(charset or 'utf-8', errors='ignore'))
            else:
                decoded_str.append(part)
        return "".join(decoded_str)
    except Exception:
        return str(header_value)

def extract_text_from_email(msg):
    """Extracts plain text body from email message object."""
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            content_disposition = str(part.get("Content-Disposition"))
            
            # Skip attachments
            if "attachment" in content_disposition:
                continue
            
            if content_type == "text/plain":
                charset = part.get_content_charset() or 'utf-8'
                try:
                    payload = part.get_payload(decode=True)
                    if payload:
                        body += payload.decode(charset, errors='ignore') + "\n"
                except Exception as e:
                    pass
    else:
        # Single part message
        content_type = msg.get_content_type()
        if content_type == "text/plain":
            charset = msg.get_content_charset() or 'utf-8'
            payload = msg.get_payload(decode=True)
            if payload:
                body = payload.decode(charset, errors='ignore')
    
    return body

def boilerplate_cleanup(text):
    """Removes common email clutter."""
    if not text:
        return ""
    
    # Remove Unsubscribe links (common patterns)
    text = re.sub(r'Unsubscribe.*?(\n|$)', '', text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r'View in browser.*?(\n|$)', '', text, flags=re.IGNORECASE | re.DOTALL)
    
    # Remove Footer/Confidentiality notices (simple heuristic)
    lines = text.split('\n')
    clean_lines = []
    skip_footer = False
    for i, line in enumerate(lines):
        if any(keyword in line.lower() for keyword in ["confidential", "disclaimer", "unsubscribe", "privacy policy"]):
            # Check if it's the last few lines or a large block
            pass 
        clean_lines.append(line)
    
    return "\n".join(clean_lines).strip()

def extract_pins_and_links(text):
    """Extracts 4-8 digit PINs and actionable URLs."""
    pins = []
    links = []
    
    # Extract PINs: 4 to 8 digits, often preceded by 'code', 'pin', 'otp'
    pin_pattern = r'(?:code|pin|otp|verification|digit)[\s:]*?(\d{4,8})'
    for match in re.finditer(pin_pattern, text, re.IGNORECASE):
        pins.append(match.group(1))
    
    # Fallback for standalone numbers if no context found (less accurate)
    if not pins:
        standalone_pins = re.findall(r'\b(\d{4,8})\b', text)
        pins = list(set(standalone_pins))[:5] # Limit to top 5

    # Extract URLs
    url_pattern = r'https?://[^\s<>"{}|\\^`\[\]]+'
    links = re.findall(url_pattern, text)
    
    return pins, links

def detect_bot_keywords(text):
    """Scans for bot/spam/crypto keywords."""
    keywords = [
        "otp", "verification", "code", "security alert", "password reset", 
        "crypto", "bitcoin", "promotional", "offer", "verify now", "click here"
    ]
    text_lower = text.lower()
    found = [kw for kw in keywords if kw in text_lower]
    return len(found) > 0, found

# --- 4. STATE MANAGEMENT & UI ---

if "mb_log" not in st.session_state:
    st.session_state.mb_log = []
if "mb_folders" not in st.session_state:
    st.session_state.mb_folders = ["INBOX"]
if "mb_host" not in st.session_state:
    st.session_state.mb_host = ""
if "current_email" not in st.session_state:
    st.session_state.current_email = ""
if "current_password" not in st.session_state:
    st.session_state.current_password = ""

def log(msg):
    timestamp = time.strftime("%H:%M:%S")
    entry = f"[{timestamp}] {msg}"
    st.session_state.mb_log.insert(0, entry)
    # Keep last 50 logs
    st.session_state.mb_log = st.session_state.mb_log[:50]

def load_valid_accounts():
    """Loads valid accounts from various text files."""
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
                    email_part, pwd_part = line.split(":", 1)
                    # Handle pipes in password if present
                    clean_pwd = pwd_part.split('|')[0].strip()
                    combo = f"{email_part.strip()}:{clean_pwd}"
                    if combo not in seen:
                        seen.add(combo)
                        rows.append(combo)
        except Exception:
            continue
    return rows

# --- 5. MAIN APP LOGIC ---

def main():
    st.title("📬 Bobito Mailbox Reader & Portal Hub")
    
    # Sidebar Configuration
    with st.sidebar:
        st.header("⚙️ Configuration Hub")
        
        valid_accounts = load_valid_accounts()
        pick = st.selectbox("Select Valid Account", valid_accounts if valid_accounts else ["none"])
        
        custom_email = st.text_input("Email Override", value=st.session_state.current_email)
        custom_pass = st.text_input("Password Override", type="password", value=st.session_state.current_password)
        override_host = st.text_input("IMAP Host Override")
        
        # Determine active credentials
        if custom_email.strip():
            email, password = custom_email.strip(), custom_pass.strip()
        elif ":" in pick and pick != "none":
            email, password = pick.split(":", 1)
        else:
            email, password = "", ""
            
        st.session_state.current_email = email
        st.session_state.current_password = password
        
        # Webmail Portal Display
        webmail_url = get_webmail_url(email)
        if webmail_url:
            st.success(f"Webmail Portal: {webmail_url}")
            st.markdown(f"[Open Webmail]({webmail_url})")
        
        st.markdown("---")
        st.caption("Credential String:")
        cred_str = generate_credential_string(email, password) if email else "No Account"
        st.code(cred_str, language="text")

    # Connect Button
    if st.sidebar.button("🔌 Connect & Discover Folders", type="primary"):
        if not email or not password:
            st.error("Please select an account or enter credentials.")
            return
        
        log(f"Connecting {email}...")
        
        hosts_to_try = [override_host] if override_host else get_hosts(email)
        connected = False
        
        with st.spinner("Crawling IMAP Namespace & Discovering Folders..."):
            for host in hosts_to_try:
                try:
                    mail = imaplib.IMAP4_SSL(host, 993, timeout=20)
                    mail.login(email, password)
                    
                    # Exhaustive Folder Discovery
                    folders = set()
                    # Standard LIST
                    typ, data = mail.list('""', "*")
                    if typ == 'OK':
                        for item in data:
                            if not item: continue
                            s = item.decode("utf-8", errors="ignore") if isinstance(item, bytes) else str(item)
                            # Extract folder name from LIST response (complex regex handles nested quotes)
                            quoted = re.findall(r'"((?:\\.|[^"\\])*)"', s)
                            name = quoted[-1] if quoted else s.split()[-1]
                            if name and name not in (".", "/"):
                                folders.add(name)
                    
                    # Add standard fallbacks if empty
                    if not folders:
                        folders.add("INBOX")
                        
                    st.session_state.mb_host = host
                    st.session_state.mb_folders = sorted(list(folders), key=lambda x: (0 if x.lower() == "inbox" else 1, x.lower()))
                    connected = True
                    log(f"Connected via {host}. Found {len(st.session_state.mb_folders)} folders.")
                    st.sidebar.success(f"Connected to {host}")
                    break
                    
                except Exception as e:
                    log(f"Failed {host}: {e}")
                    try: mail.logout()
                    except: pass
            else:
                if not connected:
                    st.error("Could not connect to any host.")
                    return

    # Main Interface Layout
    if st.session_state.mb_host:
        col1, col2 = st.columns([1, 3])
        
        with col1:
            st.subheader("📂 Folder Explorer")
            folder = st.selectbox("Select Folder", st.session_state.mb_folders)
            
            # Deep Search Controls
            st.markdown("**Deep Search Filters**")
            search_query = st.text_input("Keyword/Subject Search", placeholder="e.g., 'OTP' or 'Password'")
            search_scope = st.radio("Search Scope", ["SUBJECT", "BODY", "TEXT", "FROM"], horizontal=True)
            
            st.markdown("---")
            st.subheader("🤖 Bot Intelligence")
            if st.button("Scan for Bots/Spam"):
                log("Initiating Bot Scan...")
                scan_folder(folder, email, password, st.session_state.mb_host, search_scope)
                
            st.markdown("---")
            st.subheader("📤 Export Tools")
            if st.button("Download Valid Accounts"):
                # Re-load and download
                accounts = load_valid_accounts()
                csv_content = "\n".join(accounts)
                st.download_button(
                    label="Download .txt",
                    data=csv_content,
                    file_name="bobito_valid_accounts.txt",
                    mime="text/plain"
                )

        with col2:
            # Message Management Area
            if "folder_data" not in st.session_state or st.session_state.get("last_folder") != folder:
                # Refresh messages on folder change
                load_messages(folder, email, password, st.session_state.mb_host)
                st.session_state.last_folder = folder

            # Display Messages
            if "messages" in st.session_state:
                msgs = st.session_state.messages
                
                # Pagination Slider
                page_size = st.slider("Messages per page", 5, 50, 10)
                total_pages = (len(msgs) + page_size - 1) // page_size
                current_page = st.number_input("Page", min_value=1, max_value=total_pages if total_pages > 0 else 1, value=1)
                
                start_idx = (current_page - 1) * page_size
                end_idx = start_idx + page_size
                page_msgs = msgs[start_idx:end_idx]
                
                # Filter by Search Query if provided
                if search_query:
                    query_lower = search_query.lower()
                    filtered = []
                    for m in page_msgs:
                        if query_lower in m.get("subject", "").lower() or \
                           query_lower in m.get("body_clean", "").lower() or \
                           query_lower in m.get("from", "").lower():
                            filtered.append(m)
                    page_msgs = filtered

                st.write(f"Showing {len(page_msgs)} messages")
                
                for msg in page_msgs:
                    with st.expander(
                        f"{'📩' if not msg['seen'] else '📖'} **{msg['subject']}**", 
                        expanded=False
                    ):
                        # Header Info
                        c1, c2 = st.columns([3, 1])
                        with c1:
                            st.markdown(f"**From:** {msg['from']}")
                            st.caption(f"Date: {msg['date']} | ID: {msg['id']}")
                        
                        with c2:
                            # Actions
                            if not msg['seen']:
                                if st.button("Mark Read", key=f"read_{msg['id']}", help="Mark as seen"):
                                    mark_seen(msg['id'], email, password, st.session_state.mb_host)
                                    st.rerun()
                            
                            if st.button("Delete", key=f"del_{msg['id']}", help="Delete this message"):
                                delete_message(msg['id'], email, password, st.session_state.mb_host)
                                st.rerun()

                        # Bot Intelligence Panel
                        is_bot, bot_reasons = detect_bot_keywords(msg["body_clean"])
                        if is_bot:
                            st.warning(f"⚠️ **Bot Detected:** {', '.join(bot_reasons)}")
                        
                        # Extracted Data
                        pins, links = extract_pins_and_links(msg["body_clean"])
                        
                        if pins:
                            st.success("🔑 **Extracted PINs/Codes**")
                            for pin in pins:
                                st.markdown(f'<span class="pin-badge">{pin}</span>', unsafe_allow_html=True)
                        
                        if links:
                            st.info("🔗 **Actionable Links**")
                            for link in links[:3]: # Limit to 3 links
                                st.markdown(f'<a href="{link}" target="_blank" class="link-btn">Open Link</a>', unsafe_allow_html=True)

                        # Body View
                        st.markdown("---")
                        st.subheader("Cleaned Body")
                        st.text_area("", value=msg["body_clean"], height=200, key=f"body_{msg['id']}")
                        
                        # Raw Source Toggle
                        with st.expander("View RFC822 Source"):
                            st.code(msg.get("raw_source", "Source not cached"), language="text")

            else:
                st.info("Select a folder and click 'Load Messages' or connect first.")

    # Live Action Log (Sidebar Bottom)
    with st.sidebar.expander("📜 Live Action Log"):
        for line in reversed(st.session_state.mb_log):
            st.text(line)

# --- 6. IMAP OPERATIONS ---

def load_messages(folder, email, password, host):
    """Fetches messages and processes them."""
    try:
        mail = imaplib.IMAP4_SSL(host, 993, timeout=20)
        mail.login(email, password)
        mail.select(f'"{folder}"', readonly=False) # Readonly=False allows flags
        
        typ, data = mail.search(None, "ALL")
        ids = (data[0] or b"").split() if typ == 'OK' else []
        # Reverse to get Newest First by default
        ids = list(reversed(ids))
        
        st.session_state.messages = []
        
        for mid in ids:
            try:
                # Fetch header and body structure efficiently
                typ, msg_data = mail.fetch(mid, "(RFC822)")
                if typ == 'OK':
                    raw_email = msg_data[0][1]
                    msg = email.message_from_bytes(raw_email)
                    
                    subject = decode_mime_header(msg['Subject'])
                    frm = decode_mime_header(msg['From'])
                    date = msg.get('Date', '')
                    seen_flag = 'Seen' in msg.get_flags()
                    
                    body_text = extract_text_from_email(msg)
                    body_clean = boilerplate_cleanup(body_text)
                    
                    st.session_state.messages.append({
                        "id": mid.decode(),
                        "subject": subject,
                        "from": frm,
                        "date": date,
                        "seen": seen_flag,
                        "body_clean": body_clean,
                        "raw_source": raw_email.decode("utf-8", errors="ignore")[:500] + "...", # Cache partial source
                        "_msg_obj": msg # Keep object for operations
                    })
            except Exception as e:
                continue
                
        log(f"Loaded {len(st.session_state.messages)} messages in {folder}")
        
    except Exception as e:
        st.error(f"Error loading messages: {e}")
        log(str(e))

def mark_seen(msg_id, email, password, host):
    mail = imaplib.IMAP4_SSL(host, 993)
    mail.login(email, password)
    mail.store(msg_id, "+FLAGS", "\\Seen")
    mail.logout()
    log(f"Marked {msg_id} as Seen")

def delete_message(msg_id, email, password, host):
    mail = imaplib.IMAP4_SSL(host, 993)
    mail.login(email, password)
    mail.store(msg_id, "+FLAGS", "\\Deleted")
    mail.expunge()
    mail.logout()
    log(f"Deleted {msg_id}")

def scan_folder(folder, email, password, host, scope):
    """Scans current folder for bots and logs findings."""
    try:
        mail = imaplib.IMAP4_SSL(host, 993)
        mail.login(email, password)
        mail.select(f'"{folder}"')
        
        # Search based on scope
        search_cmd = f"ALL" # Simplified for demo, could be SUBJECT "bot" etc.
        typ, data = mail.search(None, search_cmd)
        ids = (data[0] or b"").split()
        
        bot_count = 0
        for mid in ids:
            typ, msg_data = mail.fetch(mid, "(BODY.PEEK[HEADER])")
            if typ == 'OK':
                raw_header = msg_data[0][1]
                msg = email.message_from_bytes(raw_header)
                subject = decode_mime_header(msg['Subject'])
                # Peek body for keywords (simplified)
                is_bot, reasons = detect_bot_keywords(subject + " " + str(msg))
                if is_bot:
                    bot_count += 1
                    log(f"Bot detected in {mid.decode()}: {reasons}")
        
        st.sidebar.success(f"Scan complete. Found {bot_count} potential bots.")
        mail.logout()
    except Exception as e:
        st.sidebar.error(f"Scan error: {e}")

if __name__ == "__main__":
    main()
