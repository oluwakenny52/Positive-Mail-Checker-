import streamlit as st
import imaplib
import email
from email.header import decode_header
import os
import glob
import re
import base64
import quopri
from urllib.parse import unquote
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

# Initialize Action Log in Session State
if 'action_log' not in st.session_state:
    st.session_state['action_log'] = []

def log_action(msg):
    st.session_state['action_log'].insert(0, msg)
    if len(st.session_state['action_log']) > 25:
        st.session_state['action_log'].pop()

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

# --- Universal Folder Discovery Engine (Comprehensive mapping) ---
def discover_folders(mail):
    found = []
    seen = set()
    
    def add_folder(name):
        if not name:
            return
        name = name.strip().strip('"').strip("'")
        if not name or name in (".", "/", "\\", "NIL", "nil") or re.fullmatch(r"[\/.]+", name):
            return
        key = name.lower()
        if key in seen:
            return
        seen.add(key)
        found.append(name)

    # 1. Query standard LIST command
    try:
        typ, data = mail.list('""', '*')
        if typ == "OK" and data:
            for it in data:
                if not it:
                    continue
                s = it.decode("utf-8", errors="ignore") if isinstance(it, bytes) else str(it)
                quoted = re.findall(r'"((?:\\.|[^"\\])*)"', s)
                if quoted:
                    add_folder(quoted[-1].replace('\\"', '"'))
                else:
                    parts = s.split()
                    if parts:
                        add_folder(parts[-1])
    except Exception:
        pass

    # 2. Query LSUB (Subscribed folders)
    try:
        typ2, data2 = mail.lsub('""', '*')
        if typ2 == "OK" and data2:
            for it in data2:
                if not it:
                    continue
                s = it.decode("utf-8", errors="ignore") if isinstance(it, bytes) else str(it)
                quoted = re.findall(r'"((?:\\.|[^"\\])*)"', s)
                if quoted:
                    add_folder(quoted[-1].replace('\\"', '"'))
                else:
                    parts = s.split()
                    if parts:
                        add_folder(parts[-1])
    except Exception:
        pass

    # Fallback standard checks if server supports them directly
    for candidate in ["INBOX", "Sent", "Drafts", "Trash", "Junk", "Spam", "[Gmail]/Sent Mail", "[Gmail]/Trash", "[Gmail]/Spam"]:
        try:
            code, _ = mail.status(candidate, "(MESSAGES)")
            if code == "OK":
                add_folder(candidate)
        except Exception:
            pass

    names = found if found else ["INBOX"]
    # Sort nicely placing INBOX first
    names = sorted(names, key=lambda x: (0 if x.lower() == "inbox" else 1, x.lower()))
    return names

# --- Bot Filtering & Intelligence Engine ---
BOT_KEYWORDS = [
    "otp", "code", "pin", "verification", "verify", "authentication",
    "security", "alert", "suspicious", "login", "warning", "reset",
    "password", "recover", "confirm", "activation", "welcome", "crypto",
    "private video", "urgent"
]

def detect_bot_indicators(subject, body):
    text = f"{subject} {body}".lower()
    flags = []
    if any(k in text for k in ["otp", "code", "pin", "verification", "verify", "authentication"]):
        flags.append("🔑 OTP / Verification")
    if any(k in text for k in ["security", "alert", "suspicious", "login", "warning"]):
        flags.append("🚨 Security Alert")
    if any(k in text for k in ["reset", "password", "recover"]):
        flags.append("🔐 Password Reset")
    if any(k in text for k in ["confirm", "activation", "welcome"]):
        flags.append("✨ Activation / Action")
    if any(k in text for k in ["crypto", "private video", "urgent"]):
        flags.append("⚠ Bulk/Promotional Bot")
    return list(set(flags))

def is_bot_message(subject, body):
    text = f"{subject} {body}".lower()
    return any(k in text for k in BOT_KEYWORDS)

def extract_actionable_pins(body):
    pins = re.findall(r'\b(?<![\d-])(\d{4,8})(?![\d-])\b', body)
    return list(set(pins))

def extract_verification_links(body):
    urls = re.findall(r'(https?://[^\s<>"]+|www\.[^\s<>"]+)', body)
    clean_urls = []
    for u in urls:
        try:
            clean_urls.append(unquote(u))
        except Exception:
            clean_urls.append(u)
    return list(set(clean_urls))

def clean_boilerplate_text(body_text):
    clean_text = re.sub(r'<[^>]+>', '', body_text)
    lines = clean_text.split('\n')
    filtered_lines = []
    for line in lines:
        l_lower = line.lower()
        if any(term in l_lower for term in ["unsubscribe", "privacy policy", "all rights reserved", "sent from my", "confidentiality notice"]):
            continue
        filtered_lines.append(line)
    return "\n".join(filtered_lines).strip()

def decode_payload_content(part_payload, content_transfer_encoding):
    if not part_payload:
        return ""
    try:
        encoding_lower = (content_transfer_encoding or "").lower()
        if "base64" in encoding_lower:
            return base64.b64decode(part_payload).decode("utf-8", errors="ignore")
        elif "quoted-printable" in encoding_lower:
            return quopri.decodestring(part_payload).decode("utf-8", errors="ignore")
        else:
            if isinstance(part_payload, bytes):
                return part_payload.decode("utf-8", errors="ignore")
            return str(part_payload)
    except Exception:
        if isinstance(part_payload, bytes):
            return part_payload.decode("utf-8", errors="ignore")
        return str(part_payload)

# --- App Header & Config ---
st.title("📥 Bobito Mailbox Reader & Portal Hub")
st.markdown("High-performance IMAP inbox explorer equipped with automated folder discovery, bot intelligence, and advanced message management.")

valid_accs = load_valid_accounts()

# --- Sidebar Configuration Hub ---
st.sidebar.header("⚙ Reader & Portal Config")
selected_account = st.sidebar.selectbox("Select Valid Account", options=valid_accs if valid_accs else ["No valid accounts found"], key="mb_selected_account")

custom_email = st.sidebar.text_input("Or enter custom email", key="mb_custom_email")
custom_pass = st.sidebar.text_input("Or enter custom password", type="password", key="mb_custom_pass")

target_email = custom_email.strip() if custom_email.strip() else (selected_account.split(":")[0] if ":" in selected_account else "")
target_pass = custom_pass.strip() if custom_pass.strip() else (selected_account.split(":")[1] if ":" in selected_account else "")

st.session_state['email'] = target_email
st.session_state['password'] = target_pass

server_host = st.sidebar.text_input("IMAP Server Host (Blank for Auto)", value="", key="mb_server_host")

connect_pressed = st.button("📥 Connect & Discover Folders", type="primary", use_container_width=True, key="mb_connect_btn")

# --- Export Valid Accounts Option ---
if valid_accs:
    st.sidebar.markdown("---")
    st.sidebar.subheader("📥 Export Valid Combos")
    txt_data = "\n".join(valid_accs)
    st.sidebar.download_button(
        label="Download Valid Accounts (.txt)",
        data=txt_data,
        file_name="valid_accounts.txt",
        mime="text/plain",
        use_container_width=True
    )

# Webmail Portal & Copyable Combo Quick Access Hub Block
if target_email:
    portal_url = get_webmail_portal_url(target_email)
    st.sidebar.markdown("---")
    st.sidebar.subheader("🌐 Webmail Portal & Combo Hub")
    st.sidebar.markdown(f"**Target Webmail URL:**\n`{portal_url}`")
    st.sidebar.link_button("• Open Webmail Portal in New Tab", portal_url, use_container_width=True)
    
    combo_str = f"{target_email}:{target_pass}"
    st.sidebar.markdown("**Selected Combo (Copyable):**")
    st.sidebar.code(combo_str, language="")

# Action Log Sidebar Viewer
with st.sidebar.expander("📋 Live Action Log", expanded=False):
    if st.session_state['action_log']:
        for act in st.session_state['action_log']:
            st.text(act)
        if st.button("Clear Log"):
            st.session_state['action_log'] = []
            st.rerun()
    else:
        st.info("No actions logged yet.")

# --- Connection & Session Management ---
if connect_pressed:
    if not target_email or not target_pass:
        st.warning("⚠ Please provide a valid target email and password combo.")
    else:
        host = server_host.strip() if server_host.strip() else guess_imap_server(target_email)
        st.session_state['imap_host'] = host
        
        with st.spinner(f"Connecting to IMAP secure gateway **{host}:993**..."):
            try:
                mail = imaplib.IMAP4_SSL(host, 993, timeout=15)
                mail.login(target_email, target_pass)
                
                folders = discover_folders(mail)
                st.session_state['imap_mail'] = mail
                st.session_state['available_folders'] = folders
                log_action(f"Connected to {target_email} ({len(folders)} folders discovered)")
                st.success(f"Successfully connected and discovered {len(folders)} mail folders!")
            except Exception as ex:
                st.error(f"Connection error: {ex}")

# --- Folder Selector & Advanced Search Hub ---
if 'imap_mail' in st.session_state:
    st.markdown("---")
    st.subheader("📁 Folder Explorer & Deep Search")
    
    col_f1, col_f2, col_f3 = st.columns([2, 1, 1])
    with col_f1:
        prev_folder = st.session_state.get('last_selected_folder', None)
        selected_folder = st.selectbox("Select Mailbox Folder", options=st.session_state.get('available_folders', ["INBOX"]), key="mb_selected_folder")
        
        if prev_folder != selected_folder:
            st.session_state['last_selected_folder'] = selected_folder
            if 'current_msg_ids' in st.session_state:
                del st.session_state['current_msg_ids']
            if 'flagged_bot_list' in st.session_state:
                del st.session_state['flagged_bot_list']
                
    with col_f2:
        batch_size = st.slider("Messages per Page", min_value=10, max_value=100, value=40, key="mb_batch_size")
    with col_f3:
        sort_order = st.selectbox(
            "Sort Order", 
            ["Newest First (Descending)", "Oldest First (Ascending)"], 
            key="mb_sort_order"
        )

    col_s1, col_s2, col_s3 = st.columns([3, 1, 1])
    with col_s1:
        search_query = st.text_input("Deep Keyword Search (Subject, Sender, or Body Text)", placeholder="e.g. Netflix, verify, security", key="mb_deep_search_query")
    with col_s2:
        search_scope = st.selectbox("Search Field", ["TEXT", "BODY", "SUBJECT", "FROM"], key="mb_search_scope")
    with col_s3:
        st.markdown("<br>", unsafe_allow_html=True)
        refresh_btn = st.button("🔄 Refresh Inbox", use_container_width=True)

    col_btn1, col_btn2 = st.columns([1, 1])
    with col_btn1:
        load_folder_btn = st.button("📂 Load Folder Messages", type="primary", use_container_width=True)
    with col_btn2:
        search_btn = st.button("🔎 Execute Deep Search", use_container_width=True)

    mail = st.session_state['imap_mail']
    safe_folder = selected_folder.replace('"', '\\"')

    if load_folder_btn or search_btn or refresh_btn:
        with st.spinner("Querying mailbox messages..."):
            try:
                mail.select(f'"{safe_folder}"', readonly=True)
                if search_btn and search_query.strip():
                    q = search_query.strip()
                    scope = search_scope
                    status, response = mail.search(None, f'({scope} "{q}")')
                else:
                    status, response = mail.search(None, "ALL")
                
                if status == "OK" and response and response[0]:
                    msg_ids = response[0].split()
                    if "Newest First" in sort_order:
                        msg_ids = msg_ids[::-1]
                    
                    st.session_state['current_msg_ids'] = msg_ids
                    st.session_state['current_page'] = 0
                    log_action(f"Loaded folder '{selected_folder}' ({len(msg_ids)} messages)")
                    st.success(f"Found {len(msg_ids)} messages matching criteria.")
                else:
                    st.session_state['current_msg_ids'] = []
                    st.warning("No messages found in folder.")
            except Exception as e:
                st.error(f"Error querying folder: {e}")

    # --- Bot Mail Preview & Safe Cleanup Utility Bar ---
    if 'current_msg_ids' in st.session_state and st.session_state['current_msg_ids']:
        st.markdown("---")
        st.markdown("### 🧹 Bot Mail Preview & Management")
        
        col_m1, col_m2 = st.columns([1, 1])
        with col_m1:
            preview_bots_btn = st.button("🔍 Scan & Preview Potential Bots", use_container_width=True, type="secondary")
        with col_m2:
            mass_clean_btn = st.button("🗑 Mass Delete Previewed Bots", use_container_width=True, type="primary")
            
        if preview_bots_btn:
            with st.spinner("Scanning headers for bot and spam messages..."):
                try:
                    mail.select(f'"{safe_folder}"', readonly=True)
                    flagged_bots = []
                    for num in st.session_state['current_msg_ids']:
                        num_str = num.decode('utf-8') if isinstance(num, bytes) else str(num)
                        st_fetch, msg_data = mail.fetch(num_str.encode(), "(BODY.PEEK[HEADER.FIELDS (SUBJECT FROM DATE)])")
                        if st_fetch == "OK":
                            sub, snd, dt = "", "", ""
                            for resp in msg_data:
                                if isinstance(resp, tuple):
                                    m = email.message_from_bytes(resp[1])
                                    sub = decode_mime_header(m.get("Subject", ""))
                                    snd = decode_mime_header(m.get("From", ""))
                                    dt = m.get("Date", "")
                            if is_bot_message(sub, snd):
                                flagged_bots.append({"id": num_str, "subject": sub, "sender": snd, "date": dt})
                    st.session_state['flagged_bot_list'] = flagged_bots
                    log_action(f"Scanned and found {len(flagged_bots)} potential bot messages.")
                    st.success(f"Scan complete! Found {len(flagged_bots)} bot/spam messages. Preview them below before deleting.")
                except Exception as ex:
                    st.error(f"Error scanning for bots: {ex}")

        if 'flagged_bot_list' in st.session_state and st.session_state['flagged_bot_list']:
            st.info(f"📋 **{len(st.session_state['flagged_bot_list'])} Bot Messages Flagged for Review:**")
            for b_item in st.session_state['flagged_bot_list']:
                with st.expander(f"🤖 [Msg #{b_item['id']}] {b_item['sender'][:30]} — {b_item['subject'][:40]}"):
                    st.markdown(f"**From:** `{b_item['sender']}`")
                    st.markdown(f"**Subject:** `{b_item['subject']}`")
                    st.markdown(f"**Date:** `{b_item['date']}`")
        elif 'flagged_bot_list' in st.session_state:
            st.info("No bot messages currently flagged in this view.")

        if mass_clean_btn:
            if 'flagged_bot_list' in st.session_state and st.session_state['flagged_bot_list']:
                with st.spinner("Deleting previewed bot messages..."):
                    try:
                        mail.select(f'"{safe_folder}"', readonly=False)
                        deleted_count = 0
                        for b_item in st.session_state['flagged_bot_list']:
                            num_str = b_item['id']
                            mail.store(num_str.encode(), '+FLAGS', '\\Deleted')
                            deleted_count += 1
                        mail.expunge()
                        log_action(f"Mass deleted {deleted_count} previewed bot messages from {selected_folder}")
                        st.session_state['flagged_bot_list'] = []
                        st.success(f"Successfully removed {deleted_count} bot messages! Click 'Refresh Inbox' to update view.")
                    except Exception as ex:
                        st.error(f"Error during mass bot cleanup: {ex}")
            else:
                st.warning("⚠ Please run 'Scan & Preview Potential Bots' first before deleting.")

    # Display Paginated Message Stream
    if 'current_msg_ids' in st.session_state and st.session_state['current_msg_ids']:
        msg_ids = st.session_state['current_msg_ids']
        total_msgs = len(msg_ids)
        current_page = st.session_state.get('current_page', 0)
        
        max_page = max(0, (total_msgs - 1) // batch_size)
        current_page = min(current_page, max_page)
        st.session_state['current_page'] = current_page
        
        start_idx = current_page * batch_size
        end_idx = min(start_idx + batch_size, total_msgs)
        page_ids = msg_ids[start_idx:end_idx]

        st.markdown(f"**Showing messages {start_idx + 1} to {end_idx} of {total_msgs}**")
        
        p_col1, p_col2, p_col3 = st.columns([1, 2, 1])
        with p_col1:
            if st.button("◀ Previous Page") and current_page > 0:
                st.session_state['current_page'] -= 1
                st.rerun()
        with p_col2:
            st.markdown(f"<p style='text-align: center;'>Page {current_page + 1} of {max_page + 1}</p>", unsafe_allow_html=True)
        with p_col3:
            if st.button("Next Page ▶") and current_page < max_page:
                st.session_state['current_page'] += 1
                st.rerun()

        st.markdown("---")
        
        for num in page_ids:
            try:
                num_str = num.decode('utf-8') if isinstance(num, bytes) else str(num)
                mail.select(f'"{safe_folder}"', readonly=True)
                st_fetch, msg_data = mail.fetch(num_str.encode(), "(BODY.PEEK[HEADER.FIELDS (SUBJECT FROM DATE)] FLAGS)")
                if st_fetch != "OK":
                    continue
                
                subject, sender, date_str = "No Subject", "Unknown", "Unknown"
                flags = ""
                for response_part in msg_data:
                    if isinstance(response_part, tuple):
                        msg = email.message_from_bytes(response_part[1])
                        subject = decode_mime_header(msg.get("Subject", "No Subject"))
                        sender = decode_mime_header(msg.get("From", "Unknown"))
                        date_str = msg.get("Date", "Unknown")
                    elif isinstance(response_part, bytes):
                        flags = response_part.decode("utf-8", errors="ignore")
                
                is_read = "\\Seen" in flags
                read_indicator = "📖" if is_read else "📩 **[UNREAD]**"
                
                with st.expander(f"{read_indicator} [{date_str}] {sender[:30]} — {subject[:40]}"):
                    st.markdown(f"**From:** `{sender}`")
                    st.markdown(f"**Subject:** `{subject}`")
                    st.markdown(f"**Date:** `{date_str}`")
                    st.markdown(f"**Server ID / Flags:** `Msg #{num_str}` | Flags: `{flags}`")
                    st.markdown("---")
                    
                    op_col1, op_col2, op_col3, op_col4 = st.columns(4)
                    with op_col1:
                        if st.button("👁 Mark Seen", key=f"seen_{selected_folder}_{num_str}"):
                            mail.select(f'"{safe_folder}"', readonly=False)
                            mail.store(num_str.encode(), '+FLAGS', '\\Seen')
                            log_action(f"Marked message #{num_str} as seen")
                            st.success("Marked as seen!")
                            st.rerun()
                    with op_col2:
                        if st.button("🗑 Delete", key=f"del_{selected_folder}_{num_str}"):
                            mail.select(f'"{safe_folder}"', readonly=False)
                            mail.store(num_str.encode(), '+FLAGS', '\\Deleted')
                            mail.expunge()
                            log_action(f"Deleted message #{num_str}")
                            st.success("Message deleted!")
                            st.rerun()
                    with op_col3:
                        target_move = st.selectbox("Move to Folder", options=[f for f in st.session_state.get('available_folders', ["INBOX"]) if f != selected_folder], key=f"move_sel_{selected_folder}_{num_str}")
                    with op_col4:
                        if st.button("🚀 Confirm Move", key=f"move_btn_{selected_folder}_{num_str}"):
                            try:
                                mail.select(f'"{safe_folder}"', readonly=False)
                                mail.copy(num_str.encode(), target_move)
                                mail.store(num_str.encode(), '+FLAGS', '\\Deleted')
                                mail.expunge()
                                log_action(f"Moved message #{num_str} to {target_move}")
                                st.success(f"Moved to {target_move} successfully!")
                                st.rerun()
                            except Exception as ex:
                                st.error(f"Move failed: {ex}")

                    st.markdown("---")
                    if st.button(f"📥 Fetch & Parse Payload #{num_str}", key=f"load_body_{selected_folder}_{num_str}", type="primary"):
                        with st.spinner("Extracting payload through Bot Intelligence & Decoder engine..."):
                            mail.select(f'"{safe_folder}"', readonly=True)
                            st_f, m_data = mail.fetch(num_str.encode(), "(RFC822)")
                            raw_body_text = "Could not parse body."
                            full_raw_rfc822 = ""
                            
                            if st_f == "OK":
                                for part in m_data:
                                    if isinstance(part, tuple):
                                        full_raw_rfc822 = part[1].decode("utf-8", errors="ignore")
                                        full_msg = email.message_from_bytes(part[1])
                                        if full_msg.is_multipart():
                                            for subpart in full_msg.walk():
                                                if subpart.get_content_type() == "text/plain":
                                                    payload = subpart.get_payload(decode=True)
                                                    encoding = subpart.get("Content-Transfer-Encoding")
                                                    if payload:
                                                        raw_body_text = decode_payload_content(payload, encoding)
                                                        break
                                        else:
                                            payload = full_msg.get_payload(decode=True)
                                            encoding = full_msg.get("Content-Transfer-Encoding")
                                            if payload:
                                                raw_body_text = decode_payload_content(payload, encoding)
                            
                            bot_flags = detect_bot_indicators(subject, raw_body_text)
                            extracted_pins = extract_actionable_pins(raw_body_text)
                            extracted_links = extract_verification_links(raw_body_text)
                            cleaned_content = clean_boilerplate_text(raw_body_text)
                            
                            if bot_flags:
                                st.markdown("### 🤖 Bot Intelligence Detected")
                                cols = st.columns(len(bot_flags))
                                for c_idx, flag in enumerate(bot_flags):
                                    with cols[c_idx]:
                                        st.warning(flag)
                            
                            if extracted_pins:
                                st.success(f"🔑 **Extracted Verification PIN(s):** `{'`, `'.join(extracted_pins)}`")
                            
                            if extracted_links:
                                st.markdown("##### 🔗 Actionable Verification Links")
                                for l_idx, link in enumerate(extracted_links[:3]):
                                    st.link_button(f"🚀 Open Link #{l_idx+1}", link, use_container_width=True)
                            
                            st.markdown("---")
                            st.markdown("##### 🧹 Cleaned Core Message Body")
                            st.text_area("Parsed Text", cleaned_content, height=220, key=f"body_area_{selected_folder}_{num_str}")
                            
                            with st.expander("🔍 Inspect Raw Source & Headers"):
                                st.text_area("Raw RFC822 Source", full_raw_rfc822[:5000], height=300, key=f"raw_source_{selected_folder}_{num_str}")
            except Exception as ex:
                st.error(f"Error loading message {num}: {ex}")
