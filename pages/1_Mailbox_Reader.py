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


# ============================================================
# PROTOCOL ENUM
# ============================================================
class Protocol(Enum):
    IMAP = "imap"
    POP3 = "pop3"
    UNKNOWN = "unknown"


# ============================================================
# UNIVERSAL FOLDER DISCOVERY ENGINE
# ============================================================
class UniversalMailboxEngine:
    """Universal mailbox folder discovery engine."""

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

            if any(x in entry.lower() for x in [r"\noselect", r"\nonexistent", r"\noinferiors"]):
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

    if any(k in combined for k in ["verify", "verification", "otp", "confirm", "code"]):
        flags.append("🔑 Verification Code / OTP")
    if any(k in combined for k in ["security alert", "unusual activity", "new sign-in"]):
        flags.append("🚨 Security Alert")
    if any(k in combined for k in ["password", "reset", "credentials"]):
        flags.append("🔐 Password Event")

    return flags


def extract_pins(text: str) -> List[str]:
    """Extract PINs/codes."""
    pattern = r"\b\d{4,8}\b"
    matches = re.findall(pattern, text)
    return list(dict.fromkeys(matches))[:10]


def extract_verification_urls(text: str) -> List[str]:
    """Extract verification links."""
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


# ============================================================
# STREAMLIT CONFIGURATION
# ============================================================
st.set_page_config(
    page_title="Mail Engine v7 Final",
    page_icon="📧",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.title("📧 Mail Engine v7 Final - Universal Mail Reader")
st.caption("Auto-detect • Folder discovery (UTF-7, any language) • Bot intelligence • PIN extraction • Valid account manager")


# ============================================================
# SESSION STATE
# ============================================================
if "engine_log" not in st.session_state:
    st.session_state.engine_log = []
if "engine_connected" not in st.session_state:
    st.session_state.engine_connected = False
if "engine_folders" not in st.session_state:
    st.session_state.engine_folders = ["INBOX"]
if "engine_page" not in st.session_state:
    st.session_state.engine_page = 0


def log_activity(msg: str):
    """Log activity."""
    st.session_state.engine_log.insert(0, msg)
    st.session_state.engine_log = st.session_state.engine_log[:50]


# ============================================================
# SIDEBAR: CONNECTION HUB
# ============================================================
st.sidebar.header("🔐 Mail Server Connection Hub")

valid_accounts = load_valid_accounts()

# Account selector
if valid_accounts:
    pick = st.sidebar.selectbox("📋 Select Valid Account", valid_accounts or ["(manual entry)"], key="sidebar_account_sel")
    if pick and ":" in pick:
        email_addr, password_val = pick.split(":", 1)
    else:
        email_addr = st.sidebar.text_input("Email Address", key="sidebar_email")
        password_val = st.sidebar.text_input("Password", type="password", key="sidebar_password")
else:
    email_addr = st.sidebar.text_input("Email Address", key="sidebar_email")
    password_val = st.sidebar.text_input("Password", type="password", key="sidebar_password")

protocol_sel = st.sidebar.selectbox("Protocol", ["IMAP", "POP3"], key="sidebar_protocol")
host_addr = st.sidebar.text_input("Mail Server Host", placeholder="imap.gmail.com", key="sidebar_host")
port_val = st.sidebar.number_input("Port (0 = auto)", min_value=0, max_value=65535, value=0, key="sidebar_port")

if st.sidebar.button("🚀 Connect & Discover Folders", type="primary", use_container_width=True):
    if not email_addr or not password_val or not host_addr:
        st.sidebar.error("❌ Email, password, and host required")
        log_activity("Connection attempt failed - missing credentials")
    else:
        with st.spinner("🔍 Discovering folders..."):
            try:
                port_use = port_val if port_val > 0 else None
                engine = UniversalMailboxEngine(
                    email=email_addr,
                    password=password_val,
                    host=host_addr,
                    protocol=protocol_sel,
                    port=port_use,
                )
                folders, msg, success = engine.discover_folders()

                if success:
                    st.session_state.engine_connected = True
                    st.session_state.engine_folders = folders
                    st.session_state.engine_email = email_addr
                    st.session_state.engine_password = password_val
                    st.session_state.engine_host = host_addr
                    st.session_state.engine_protocol = protocol_sel
                    st.session_state.engine_port = port_use or (993 if protocol_sel == "IMAP" else 995)

                    log_activity(f"✓ Connected to {host_addr} - {msg}")
                    st.sidebar.success(f"✅ {msg}\n\n**Folders:**\n" + "\n".join(folders[:20]))
                else:
                    log_activity(f"✗ Connection failed - {msg}")
                    st.sidebar.error(f"❌ {msg}")
            except Exception as e:
                log_activity(f"✗ Error: {str(e)[:40]}")
                st.sidebar.error(f"❌ {str(e)}")

# ============================================================
# SIDEBAR: STATUS
# ============================================================
st.sidebar.markdown("---")
if st.session_state.engine_connected:
    st.sidebar.success(f"✅ Connected | {len(st.session_state.engine_folders)} folder(s)")
else:
    st.sidebar.warning("⚠️ Not connected")

# ============================================================
# SIDEBAR: WEBMAIL PORTAL
# ============================================================
if st.session_state.engine_connected and st.session_state.engine_email:
    st.sidebar.markdown("---")
    st.sidebar.subheader("🌐 Webmail Portal & Credentials")
    portal = get_webmail_portal(st.session_state.engine_email)
    st.sidebar.markdown(f"[🌐 Open Webmail Portal]({portal})")
    
    cred_display = f"{st.session_state.engine_email}:{st.session_state.engine_password}"
    st.sidebar.text_input(
        "Copy Email:Password",
        value=cred_display,
        disabled=True,
        key="sidebar_cred_copy"
    )

# ============================================================
# SIDEBAR: VALID ACCOUNTS DOWNLOAD
# ============================================================
if valid_accounts:
    st.sidebar.markdown("---")
    st.sidebar.subheader("💾 Download Valid Accounts")
    
    valid_text = "\n".join(valid_accounts)
    
    col_dl, col_cnt = st.sidebar.columns([3, 1])
    with col_dl:
        st.download_button(
            label="📥 Download Valid Only",
            data=valid_text,
            file_name=f"valid_accounts_{len(valid_accounts)}.txt",
            mime="text/plain",
            use_container_width=True
        )
    with col_cnt:
        st.metric("Count", len(valid_accounts), label_visibility="collapsed")

# ============================================================
# SIDEBAR: ACTIVITY LOG
# ============================================================
st.sidebar.markdown("---")
st.sidebar.subheader("📜 Activity Log")
with st.sidebar.expander("View Log", expanded=False):
    for log_line in st.session_state.engine_log[:20]:
        st.text(log_line)

# ============================================================
# MAIN: FOLDER & SEARCH
# ============================================================
st.markdown("---")
st.subheader("📁 Browse Mailbox")

col1, col2, col3 = st.columns([2, 1, 1])
with col1:
    folder_sel = st.selectbox("📂 Folder", st.session_state.engine_folders, key="main_folder_sel")
with col2:
    per_page = st.slider("Per page", 5, 100, 20, key="main_per_page")
with col3:
    sort_sel = st.selectbox("Sort", ["Newest", "Oldest"], key="main_sort_sel")

col_search1, col_search2, col_search3 = st.columns([3, 1, 1])
with col_search1:
    search_query = st.text_input("🔍 Search", placeholder="keyword", key="main_search")
with col_search2:
    search_field = st.selectbox("Field", ["TEXT", "SUBJECT", "FROM"], key="main_search_field")
with col_search3:
    st.markdown("<br>", unsafe_allow_html=True)
    search_btn = st.button("🔍 Search", use_container_width=True)

col_load1, col_load2 = st.columns([1, 1])
with col_load1:
    load_btn = st.button("📥 Load Folder", type="primary", use_container_width=True)

# ============================================================
# MAIN: FETCH MESSAGES
# ============================================================
if load_btn or search_btn:
    if not st.session_state.engine_connected:
        st.error("❌ Please connect first")
    else:
        with st.spinner("📬 Fetching messages..."):
            try:
                if st.session_state.engine_protocol == "IMAP":
                    try:
                        mail = imaplib.IMAP4_SSL(
                            st.session_state.engine_host,
                            st.session_state.engine_port,
                            timeout=20
                        )
                    except:
                        mail = imaplib.IMAP4(st.session_state.engine_host, 143, timeout=20)

                    mail.login(st.session_state.engine_email, st.session_state.engine_password)
                    mail.select(f'"{folder_sel}"', readonly=True)

                    if search_btn and search_query.strip():
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
                                                "folder": folder_sel,
                                            })
                            except Exception:
                                pass

                        st.session_state.engine_messages = messages
                        log_activity(f"Loaded {len(messages)} messages from {folder_sel}")
                        st.success(f"✅ Loaded {len(messages)} messages")

                elif st.session_state.engine_protocol == "POP3":
                    pop_cli = poplib.POP3_SSL(
                        st.session_state.engine_host,
                        st.session_state.engine_port,
                        timeout=20
                    )
                    pop_cli.user(st.session_state.engine_email)
                    pop_cli.pass_(st.session_state.engine_password)

                    stat = pop_cli.stat()
                    msg_count = stat[0]
                    messages = []

                    for i in range(max(1, msg_count - per_page + 1), msg_count + 1):
                        try:
                            typ, msgdata, octets = pop_cli.retr(i)
                            raw_msg = b"\n".join(msgdata)
                            msg_obj = email.message_from_bytes(raw_msg)
                            messages.append({
                                "id": str(i),
                                "from": decode_mime_header(msg_obj.get("From", "")),
                                "subject": decode_mime_header(msg_obj.get("Subject", "")),
                                "date": msg_obj.get("Date", ""),
                                "folder": "INBOX",
                            })
                        except Exception:
                            pass

                    if "Oldest" in sort_sel:
                        messages = list(reversed(messages))

                    st.session_state.engine_messages = messages
                    log_activity(f"Loaded {len(messages)} messages (POP3)")
                    st.success(f"✅ Loaded {len(messages)} messages (POP3)")
                    pop_cli.quit()

            except Exception as e:
                log_activity(f"Error: {str(e)[:40]}")
                st.error(f"❌ Error: {str(e)}")

# ============================================================
# MAIN: DISPLAY MESSAGES
# ============================================================
if "engine_messages" in st.session_state and st.session_state.engine_messages:
    st.markdown("---")
    st.subheader(f"✉️ Messages ({len(st.session_state.engine_messages)})")

    for idx, msg in enumerate(st.session_state.engine_messages):
        from_short = msg["from"][:50] if msg["from"] else "Unknown"
        subj_short = msg["subject"][:70] if msg["subject"] else "(no subject)"
        date_short = msg["date"][:20] if msg["date"] else ""

        with st.expander(f"📧 [{date_short}] {from_short} — {subj_short}"):
            st.markdown(f"**From:** {msg['from']}")
            st.markdown(f"**Subject:** {msg['subject']}")
            st.markdown(f"**Date:** {msg['date']}")

            if st.button("📖 Read Full Message", key=f"read_{msg['id']}_{idx}"):
                full_body = ""

                if st.session_state.engine_protocol == "IMAP":
                    try:
                        mail = imaplib.IMAP4_SSL(
                            st.session_state.engine_host,
                            st.session_state.engine_port,
                            timeout=20
                        )
                    except:
                        mail = imaplib.IMAP4(st.session_state.engine_host, 143, timeout=20)

                    mail.login(st.session_state.engine_email, st.session_state.engine_password)
                    mail.select(f'"{msg["folder"]}"', readonly=True)

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

                    mail.logout()

                # Analysis
                bot_flags = detect_bot_message(msg["subject"], full_body)
                pins = extract_pins(full_body)
                urls = extract_verification_urls(full_body)

                if bot_flags:
                    st.warning("### 🤖 Bot Message Detected")
                    for flag in bot_flags:
                        st.write(f"• {flag}")

                if pins:
                    st.success(f"🔑 **Codes Found:** {', '.join(pins)}")

                if urls:
                    st.info("### 🔗 Verification Links")
                    for url in urls:
                        st.write(f"[{url[:60]}]({url})")

                st.text_area(
                    "Message Body",
                    value=full_body[:3000] if full_body else "(empty)",
                    height=250,
                    disabled=True,
                    key=f"body_{msg['id']}_{idx}"
                )

# ============================================================
# FOOTER
# ============================================================
st.markdown("---")
st.caption(
    "🔓 Complete Universal Mail Engine v7 • IMAP (UTF-7, any language) • POP3 • "
    "Global folder discovery • Bot detection • Valid account manager • "
    "Webmail portal mapper • Credentials manager • Activity log"
)
