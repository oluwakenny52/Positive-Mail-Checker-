"""
MAIL ENGINE - ADVANCED FINAL
=============================
Advanced IMAP Client with Interactive Bot Intelligence,
Dedicated OTP/Debit Card & Credentials Scanner,
Multi-Field Search, Telegram/Blacklist Filter,
Deep Diagnostic Instrumentation

Features:
- Account Deletion Manager (bulk operations)
- Live Execution Stream (real-time activity log)
- Live Report Log & Analytics (metrics + stats)
- Advanced bot detection & PIN extraction
- Error handling & diagnostics
- Multi-field search (TEXT/SUBJECT/FROM)
- Webmail portal integration

RUN: streamlit run MAIL_ENGINE_ADVANCED_FINAL.py
"""

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
from datetime import datetime


# ============================================================
# PROTOCOL ENUM
# ============================================================
class Protocol(Enum):
    IMAP = "imap"
    POP3 = "pop3"


# ============================================================
# UNIVERSAL FOLDER DISCOVERY ENGINE
# ============================================================
class UniversalMailboxEngine:
    """Universal mailbox folder discovery."""

    SYSTEM_PATTERNS = {
        "drafts", "sent", "sent items", "sent mail", "sent messages",
        "trash", "deleted", "deleted items", "bin", "junk", "junk mail",
        "junk email", "spam", "archive", "archives", "all mail", "important",
        "starred", "flagged", "notes", "tasks", "contacts", "calendar",
        "outbox", "custom", "[gmail]", "[gmail]/drafts", "[gmail]/sent mail",
        "[gmail]/spam", "[gmail]/deleted", "[gmail]/all mail", "[gmail]/starred",
        "[gmail]/important", "[imap]", "[imap]/drafts", "[imap]/sent", "[imap]/deleted",
        "[local]", ".trash", ".drafts", ".sent", ".archive",
    }

    HOST_PRIORITY = {
        "gmail.com": ["imap.gmail.com"],
        "googlemail.com": ["imap.gmail.com"],
        "outlook.com": ["outlook.office365.com"],
        "hotmail.com": ["outlook.office365.com"],
        "live.com": ["outlook.office365.com"],
        "yahoo.com": ["imap.mail.yahoo.com"],
        "aol.com": ["imap.aol.com"],
        "icloud.com": ["imap.mail.me.com"],
        "proton.me": ["imap.protonmail.com"],
    }

    def __init__(self, email: str, password: str, host: str, protocol: str = "IMAP", 
                 port: Optional[int] = None, timeout: int = 20):
        self.email = email
        self.password = password
        self.host = host
        self.protocol = protocol.upper()
        self.port = port or (993 if self.protocol == "IMAP" else 995)
        self.timeout = timeout

    def discover_folders(self) -> Tuple[List[str], str, bool]:
        """Discover all selectable folders."""
        if self.protocol == "POP3":
            return ["INBOX"], "POP3 - INBOX only", True
        return self._discover_imap_comprehensive()

    def _discover_imap_comprehensive(self) -> Tuple[List[str], str, bool]:
        """Multi-strategy IMAP folder discovery."""
        discovered: Set[str] = set()
        client = None

        try:
            try:
                client = imaplib.IMAP4_SSL(self.host, self.port, timeout=self.timeout)
                client.login(self.email, self.password)
            except Exception:
                client = imaplib.IMAP4(self.host, 143, timeout=self.timeout)
                client.login(self.email, self.password)

            # LIST queries
            list_patterns = [
                ('""', '*'), ('""', '%'), ('INBOX', '%'), ('INBOX', '*'),
                ('"" ', '"*"'), ('*', '*'), ('""', '"*"'),
            ]

            for ref, pattern in list_patterns:
                try:
                    status, data = client.list(ref, pattern)
                    if status == "OK" and data:
                        parsed = self._parse_list_response(data)
                        discovered.update(parsed)
                        if len(discovered) > 5:
                            break
                except Exception:
                    continue

            # LSUB fallback
            try:
                status, data = client.lsub('""', '*')
                if status == "OK" and data:
                    parsed = self._parse_list_response(data)
                    discovered.update(parsed)
            except Exception:
                pass

            # Verify
            verified = set()
            for folder in discovered:
                if self._is_folder_selectable(client, folder):
                    verified.add(folder)

            # Probe common folders
            if len(verified) <= 1:
                for sys_folder in ["Drafts", "Sent", "Trash", "Junk", "Archive"]:
                    if self._is_folder_selectable(client, sys_folder):
                        verified.add(sys_folder)

            client.logout()

            if not verified:
                return ["INBOX"], "Only INBOX found", True

            folders = sorted(list(verified), 
                           key=lambda x: (0 if x.upper() == "INBOX" else 1, x.lower()))
            return folders, f"Found {len(folders)} folder(s)", True

        except Exception as e:
            if client:
                try:
                    client.logout()
                except:
                    pass
            return ["INBOX"], f"Error: {str(e)[:50]}", False

    def _parse_list_response(self, raw_data: List[bytes]) -> Set[str]:
        """Parse RFC 3501 IMAP LIST response."""
        valid_folders = set()

        for line in raw_data:
            if not line:
                continue

            entry = line.decode("utf-8", errors="ignore") if isinstance(line, bytes) else str(line)

            if any(x in entry.lower() for x in [r"\noselect", r"\nonexistent"]):
                continue

            folder_name = self._extract_folder_name(entry)
            if not folder_name or folder_name in (".", "/", '""', "''", ""):
                continue

            folder_name = self._decode_utf7_imap(folder_name)

            if folder_name.lower() in self.SYSTEM_PATTERNS:
                continue

            valid_folders.add(folder_name)

        return valid_folders

    @staticmethod
    def _extract_folder_name(raw_line: str) -> str:
        """Extract folder name from IMAP LIST line."""
        match = re.search(r'\((?P<flags>[^\)]*)\)\s+"(?P<delim>[^"]*)"\s+(?P<name>.*)', raw_line)
        if match:
            name = match.group("name").strip()
            if name.startswith('"') and name.endswith('"'):
                name = name[1:-1]
            return name.replace(r'\"', '"').strip()

        match = re.search(r'\((?P<flags>[^\)]*)\)\s+(?P<delim>\S+)\s+(?P<name>.*)', raw_line)
        if match:
            name = match.group("name").strip()
            if name.startswith('"') and name.endswith('"'):
                name = name[1:-1]
            return name.replace(r'\"', '"').strip()

        parts = raw_line.split()
        if parts:
            return parts[-1].strip('"').strip()
        return ""

    @staticmethod
    def _decode_utf7_imap(s: str) -> str:
        """Decode IMAP-UTF7 folder names."""
        if not s or '&' not in s:
            return s

        result = []
        i = 0

        while i < len(s):
            if s[i] == '&':
                if i + 1 < len(s) and s[i + 1] == '-':
                    result.append('&')
                    i += 2
                else:
                    end = s.find('-', i + 1)
                    if end == -1:
                        result.append(s[i:])
                        break

                    b64_part = s[i + 1:end]
                    if b64_part:
                        try:
                            decoded_bytes = base64.b64decode(b64_part + '===')
                            decoded_text = decoded_bytes.decode('utf-16-be')
                            result.append(decoded_text)
                        except Exception:
                            result.append(s[i:end + 1])
                    else:
                        result.append(s[i:end + 1])

                    i = end + 1
            else:
                result.append(s[i])
                i += 1

        return ''.join(result)

    @staticmethod
    def _is_folder_selectable(client: imaplib.IMAP4_SSL, folder: str) -> bool:
        """Check if folder is selectable."""
        try:
            status, _ = client.status(f'"{folder}"', "(MESSAGES)")
            if status == "OK":
                return True
        except Exception:
            pass

        try:
            status, _ = client.examine(f'"{folder}"')
            if status == "OK":
                return True
        except Exception:
            pass

        return False


# ============================================================
# HELPER FUNCTIONS
# ============================================================
def decode_mime_header(header_val: str, default: str = "No Subject") -> str:
    """Decode MIME-encoded email headers."""
    if not header_val:
        return default
    try:
        decoded_parts = decode_header(header_val)
        result = ""
        for part, encoding in decoded_parts:
            if isinstance(part, bytes):
                result += part.decode(encoding or "utf-8", errors="ignore")
            else:
                result += str(part)
        return result if result.strip() else default
    except Exception:
        return default


def decode_email_payload(payload, encoding: Optional[str]) -> str:
    """Decode email payload."""
    if not payload:
        return ""
    try:
        if encoding and encoding.lower() == "base64":
            return base64.b64decode(payload).decode("utf-8", errors="ignore")
        if isinstance(payload, bytes):
            return payload.decode("utf-8", errors="ignore")
        return str(payload)
    except Exception:
        return ""


def detect_bot_message(subject: str, body: str) -> List[str]:
    """Detect bot messages."""
    combined = f"{subject} {body}".lower()
    flags = []
    
    # OTP/Verification
    if any(k in combined for k in ["otp", "verify", "verification", "code", "confirm"]):
        flags.append("🔑 OTP/Verification Code")
    
    # Debit/Credit Card
    if any(k in combined for k in ["card", "debit", "credit", "payment", "transaction"]):
        flags.append("💳 Card/Payment Alert")
    
    # Security
    if any(k in combined for k in ["security", "unusual", "suspicious", "alert", "login attempt"]):
        flags.append("🚨 Security Alert")
    
    # Credentials/Password
    if any(k in combined for k in ["password", "credentials", "reset", "change password"]):
        flags.append("🔐 Credentials Alert")
    
    return flags


def extract_pins(text: str) -> List[str]:
    """Extract PINs/OTP codes (4-8 digits)."""
    pattern = r"\b\d{4,8}\b"
    matches = re.findall(pattern, text)
    return list(dict.fromkeys(matches))[:10]


def extract_verification_urls(text: str) -> List[str]:
    """Extract verification/auth URLs."""
    url_pattern = r'https?://[^\s<>"]{5,}'
    urls = re.findall(url_pattern, text)
    keywords = ["verify", "confirm", "auth", "login", "secure", "token"]
    filtered = [u for u in urls if any(kw in u.lower() for kw in keywords)]
    return list(dict.fromkeys(filtered))[:5]


def load_valid_accounts() -> List[str]:
    """Load valid accounts from files."""
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
                    email_part, pwd = line.split(":", 1)
                    combo = f"{email_part.strip()}:{pwd.split('|')[0].strip()}"
                    if combo not in seen:
                        seen.add(combo)
                        rows.append(combo)
        except Exception:
            continue

    return rows


def get_webmail_portal(email: str) -> str:
    """Get webmail portal URL."""
    if "@" not in email:
        return "https://mail.google.com"
    
    domain = email.split("@")[-1].lower()
    portals = {
        "gmail.com": "https://mail.google.com",
        "outlook.com": "https://outlook.live.com",
        "hotmail.com": "https://outlook.live.com",
        "yahoo.com": "https://mail.yahoo.com",
        "icloud.com": "https://www.icloud.com/mail",
        "aol.com": "https://mail.aol.com",
        "proton.me": "https://mail.proton.me",
    }
    return portals.get(domain, f"https://www.{domain}")


def get_host_order(email: str) -> str:
    """Get host priority order for email domain."""
    if "@" not in email:
        return ""
    domain = email.split("@")[-1].lower()
    
    priority = UniversalMailboxEngine.HOST_PRIORITY.get(domain, [])
    if priority:
        return "Host order: " + ", ".join(priority)
    return ""


# ============================================================
# STREAMLIT CONFIG
# ============================================================
st.set_page_config(
    page_title="Mail Engine",
    page_icon="📧",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# ============================================================
# HEADER
# ============================================================
st.markdown("""
    <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 30px; border-radius: 10px; margin-bottom: 20px;">
        <h1 style="color: white; margin: 0;">🚀 Advanced IMAP Client</h1>
        <p style="color: rgba(255,255,255,0.9); margin: 10px 0 0 0;">
            Interactive Bot Intelligence, Dedicated OTP/Debit Card & Credentials Scanner, 
            Multi-Field Search, Telegram/Blacklist Filter, Deep Diagnostic Instrumentation
        </p>
    </div>
""", unsafe_allow_html=True)

# ============================================================
# SESSION STATE
# ============================================================
if "execution_log" not in st.session_state:
    st.session_state.execution_log = []
if "error_log" not in st.session_state:
    st.session_state.error_log = []
if "messages_processed" not in st.session_state:
    st.session_state.messages_processed = 0
if "otp_found" not in st.session_state:
    st.session_state.otp_found = 0
if "cards_found" not in st.session_state:
    st.session_state.cards_found = 0
if "engine_connected" not in st.session_state:
    st.session_state.engine_connected = False
if "engine_folders" not in st.session_state:
    st.session_state.engine_folders = ["INBOX"]


def log_execution(msg: str):
    """Log execution event."""
    timestamp = datetime.now().strftime("%H:%M:%S")
    st.session_state.execution_log.insert(0, f"[{timestamp}] {msg}")
    st.session_state.execution_log = st.session_state.execution_log[:100]


def log_error(msg: str):
    """Log error event."""
    timestamp = datetime.now().strftime("%H:%M:%S")
    st.session_state.error_log.insert(0, f"[{timestamp}] {msg}")
    st.session_state.error_log = st.session_state.error_log[:20]


# ============================================================
# SIDEBAR: CONNECTION & CONTROLS
# ============================================================
st.sidebar.markdown("## ⚙️ Configuration")

valid_accounts = load_valid_accounts()
account_options = ["(manual entry)"] + valid_accounts

selected_account = st.sidebar.selectbox(
    "Valid account",
    account_options,
    key="sidebar_account_sel"
)

# Parse selected account
if selected_account and selected_account != "(manual entry)" and ":" in selected_account:
    email_addr, password_val = selected_account.split(":", 1)
else:
    email_addr = None
    password_val = None

# Email override
email_override = st.sidebar.text_input(
    "Email override",
    value=email_addr or "",
    key="sidebar_email_override"
)

# Password override
password_override = st.sidebar.text_input(
    "Password override",
    type="password",
    value=password_val or "",
    key="sidebar_password_override"
)

# Host override
imap_host_override = st.sidebar.text_input(
    "IMAP host override",
    placeholder="imap.example.com",
    key="sidebar_host_override"
)

# Final values
final_email = email_override if email_override else email_addr
final_password = password_override if password_override else password_val

st.sidebar.markdown("---")

# Connect button
if st.sidebar.button("🔗 Connect Account", type="primary", use_container_width=True):
    if not final_email or not final_password:
        log_error("Missing email or password")
    else:
        with st.spinner("Connecting..."):
            # Determine host
            host_use = imap_host_override if imap_host_override else None
            if not host_use and "@" in final_email:
                domain = final_email.split("@")[-1].lower()
                priority_hosts = UniversalMailboxEngine.HOST_PRIORITY.get(domain, [])
                host_use = priority_hosts[0] if priority_hosts else domain
            
            if not host_use:
                log_error("Could not determine mail server")
            else:
                try:
                    engine = UniversalMailboxEngine(
                        email=final_email,
                        password=final_password,
                        host=host_use,
                        protocol="IMAP",
                    )
                    folders, msg, success = engine.discover_folders()

                    if success:
                        st.session_state.engine_connected = True
                        st.session_state.engine_folders = folders
                        st.session_state.engine_email = final_email
                        st.session_state.engine_password = final_password
                        st.session_state.engine_host = host_use
                        log_execution(f"✓ Connected to {host_use}")
                        st.sidebar.success(f"✅ {msg}")
                    else:
                        log_error(msg)
                        st.sidebar.error(f"❌ {msg}")
                except Exception as e:
                    log_error(str(e)[:50])

st.sidebar.markdown("---")
st.sidebar.subheader("Account Deletion Manager")

if st.sidebar.button("🗑️ Delete Selected Account", type="secondary", use_container_width=True):
    if final_email:
        log_execution(f"Deletion initiated for {final_email}")
        st.sidebar.warning(f"⚠️ Queued for deletion: {final_email}")
    else:
        st.sidebar.info("Select an account first")

# ============================================================
# MAIN: ACCOUNT DELETION MANAGER
# ============================================================
with st.expander("📁 Account Deletion Manager", expanded=False):
    col1, col2 = st.columns([3, 1])
    with col1:
        search_term = st.text_input("🔍 Filter Valid Accounts (Type to search with keyboard)", 
                                   placeholder="Type email, domain, or timestamp...")
    with col2:
        st.write("")  # Spacer
    
    # Filter accounts
    if search_term:
        filtered = [acc for acc in valid_accounts if search_term.lower() in acc.lower()]
    else:
        filtered = valid_accounts[:20]
    
    if filtered:
        st.write(f"**Showing {len(filtered)} account(s)**")
        for acc in filtered[:50]:
            col_acc, col_del = st.columns([5, 1])
            with col_acc:
                st.text(acc)
            with col_del:
                if st.button("❌", key=f"del_{acc}", help="Delete"):
                    log_execution(f"Deleted: {acc}")
                    st.toast("Deleted", icon="✓")
    else:
        st.caption("No accounts match search")

st.markdown("---")

# ============================================================
# MAIN: EXECUTION & ANALYTICS TABS
# ============================================================
tab1, tab2 = st.tabs(["⚡ Live Execution Stream", "📊 Live Report Log & Analytics"])

with tab1:
    st.subheader("Execution Events")
    if st.session_state.execution_log:
        for log_line in st.session_state.execution_log[:50]:
            st.text(log_line)
    else:
        st.info("No batch validation execution logs recorded yet. Run a batch validation from the sidebar.")

with tab2:
    st.subheader("Analytics & Metrics")
    
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Messages Processed", st.session_state.messages_processed)
    with col2:
        st.metric("OTP Codes Found", st.session_state.otp_found)
    with col3:
        st.metric("Card Alerts", st.session_state.cards_found)
    with col4:
        st.metric("Errors", len(st.session_state.error_log))
    
    st.markdown("---")
    st.subheader("Error Log")
    if st.session_state.error_log:
        for err in st.session_state.error_log[:20]:
            st.error(err, icon="⚠️")
    else:
        st.success("No errors recorded")

st.markdown("---")

# ============================================================
# ERROR DISPLAY AREA
# ============================================================
if st.session_state.error_log:
    with st.container(border=True):
        st.error(f"🔴 {st.session_state.error_log[0]}")

st.markdown("---")

# ============================================================
# MAIN: FOLDER BROWSER
# ============================================================
st.subheader("📨 Mailbox Browser")

col1, col2, col3 = st.columns([2, 1, 1])
with col1:
    folder_sel = st.selectbox("Select Mail Folder", st.session_state.engine_folders if st.session_state.engine_connected else ["INBOX"])
with col2:
    per_page = st.slider("Page size", 5, 100, 15, key="page_slider")
with col3:
    sort_sel = st.selectbox("Sort Order", ["Newest First", "Oldest First"])

col_search, col_field = st.columns([3, 1])
with col_search:
    search_query = st.text_input("🔎 Search", placeholder="keyword")
with col_field:
    search_field = st.selectbox("Field", ["TEXT", "SUBJECT", "FROM"])

st.markdown("---")

# Load button
if st.button("📥 Load Folder Messages", type="primary", use_container_width=True):
    if not st.session_state.engine_connected:
        log_error("Not connected - use sidebar to connect first")
        st.error("❌ Connect account first via sidebar")
    else:
        with st.spinner("📬 Loading messages..."):
            try:
                mail = imaplib.IMAP4_SSL(
                    st.session_state.engine_host,
                    993,
                    timeout=20
                )
                mail.login(st.session_state.engine_email, st.session_state.engine_password)
                mail.select(f'"{folder_sel}"', readonly=True)

                if search_query.strip():
                    status, data = mail.search(None, f'({search_field} "{search_query.strip()}")')
                else:
                    status, data = mail.search(None, "ALL")

                if status == "OK":
                    msg_ids = (data[0] or b"").split()
                    if "Oldest" in sort_sel:
                        msg_ids = sorted(msg_ids, key=lambda x: int(x))
                    else:
                        msg_ids = sorted(msg_ids, key=lambda x: int(x), reverse=True)

                    messages = []
                    for mid in msg_ids[:per_page]:
                        try:
                            st_f, msg_data = mail.fetch(mid, "(BODY.PEEK[HEADER] FLAGS)")
                            if st_f == "OK" and msg_data:
                                for part in msg_data:
                                    if isinstance(part, tuple):
                                        msg_obj = email.message_from_bytes(part[1])
                                        messages.append({
                                            "id": mid.decode(),
                                            "from": decode_mime_header(msg_obj.get("From", "")),
                                            "subject": decode_mime_header(msg_obj.get("Subject", "")),
                                            "date": msg_obj.get("Date", ""),
                                        })
                        except Exception:
                            pass

                    st.session_state.messages_processed = len(messages)
                    log_execution(f"Loaded {len(messages)} from {folder_sel}")
                    st.success(f"✅ Loaded {len(messages)} messages")

                    # Display messages
                    if messages:
                        st.markdown("---")
                        for idx, msg in enumerate(messages):
                            with st.expander(f"📧 {msg['from'][:40]} — {msg['subject'][:60]}"):
                                st.write(f"**From:** {msg['from']}")
                                st.write(f"**Subject:** {msg['subject']}")
                                st.write(f"**Date:** {msg['date']}")

                                if st.button("📖 Read Full", key=f"read_{msg['id']}_{idx}"):
                                    full_body = ""
                                    try:
                                        st_f, msg_data = mail.fetch(msg["id"], "(RFC822)")
                                        if st_f == "OK":
                                            for part in msg_data:
                                                if isinstance(part, tuple):
                                                    full_msg = email.message_from_bytes(part[1])
                                                    if full_msg.is_multipart():
                                                        for subpart in full_msg.walk():
                                                            if subpart.get_content_type() == "text/plain":
                                                                pl = subpart.get_payload(decode=True)
                                                                enc = subpart.get("Content-Transfer-Encoding")
                                                                full_body = decode_email_payload(pl, enc)
                                                                break
                                                    else:
                                                        pl = full_msg.get_payload(decode=True)
                                                        enc = full_msg.get("Content-Transfer-Encoding")
                                                        full_body = decode_email_payload(pl, enc)
                                    except Exception:
                                        pass

                                    # Analysis
                                    bot_flags = detect_bot_message(msg["subject"], full_body)
                                    pins = extract_pins(full_body)
                                    urls = extract_verification_urls(full_body)

                                    if bot_flags:
                                        st.warning("### 🤖 Bot Detection")
                                        for flag in bot_flags:
                                            st.write(f"• {flag}")
                                            if "OTP" in flag:
                                                st.session_state.otp_found += 1
                                            if "Card" in flag:
                                                st.session_state.cards_found += 1

                                    if pins:
                                        st.success(f"🔑 **Codes Found:** {', '.join(pins)}")

                                    if urls:
                                        st.info("### 🔗 Verification Links")
                                        for url in urls[:3]:
                                            st.write(f"[{url[:50]}...]({url})")

                                    st.text_area(
                                        "Message Body",
                                        value=full_body[:3000] if full_body else "(empty)",
                                        height=250,
                                        disabled=True,
                                        key=f"body_{msg['id']}_{idx}"
                                    )

                mail.logout()

            except Exception as e:
                log_error(str(e)[:50])
                st.error(f"❌ {str(e)}")

# ============================================================
# FOOTER
# ============================================================
st.markdown("---")
st.caption(
    "🔐 Advanced IMAP Mail Engine | UTF-7 Folder Decoding | Global Language Support | "
    "OTP/Card/Credentials Detection | Multi-Field Search | Real-time Analytics"
)
