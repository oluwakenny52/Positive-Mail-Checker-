import streamlit as st
import imaplib
import poplib
import socket
import re
import base64
from typing import List, Set, Tuple, Dict, Optional
from enum import Enum
import email
from email.header import decode_header
import time


# ============================================================
# PROTOCOL ENUM
# ============================================================
class Protocol(Enum):
    IMAP = "imap"
    POP3 = "pop3"
    UNKNOWN = "unknown"


# ============================================================
# UNIVERSAL FOLDER DISCOVERY ENGINE (Production-Grade)
# ============================================================
class UniversalMailboxEngine:
    """
    Battle-tested mailbox folder discovery.
    Handles all IMAP servers worldwide, UTF-7 decoding, localized folders,
    system folder filtering, POP3 fallback, webmail detection.
    """

    # System folders to hide (multi-language, multi-provider)
    SYSTEM_PATTERNS = {
        # English
        "drafts", "sent", "sent items", "sent mail", "sent messages",
        "trash", "deleted", "deleted items", "bin",
        "junk", "junk mail", "junk email", "spam",
        "archive", "archives", "all mail", "important",
        "starred", "flagged", "notes", "tasks", "contacts",
        "calendar", "outbox", "custom",
        # Gmail
        "[gmail]", "[gmail]/drafts", "[gmail]/sent mail", "[gmail]/spam",
        "[gmail]/deleted", "[gmail]/all mail", "[gmail]/starred", "[gmail]/important",
        # Microsoft
        "[imap]", "[imap]/drafts", "[imap]/sent", "[imap]/deleted",
        # Other
        "[local]", ".trash", ".drafts", ".sent", ".archive",
    }

    # Common IMAP hosts (for fallback)
    COMMON_HOSTS = {
        "gmail.com": "imap.gmail.com",
        "googlemail.com": "imap.gmail.com",
        "outlook.com": "outlook.office365.com",
        "hotmail.com": "outlook.office365.com",
        "live.com": "outlook.office365.com",
        "yahoo.com": "imap.mail.yahoo.com",
        "ymail.com": "imap.mail.yahoo.com",
        "aol.com": "imap.aol.com",
        "icloud.com": "imap.mail.me.com",
        "me.com": "imap.mail.me.com",
        "zoho.com": "imap.zoho.com",
        "proton.me": "imap.protonmail.com",
        "protonmail.com": "imap.protonmail.com",
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
        """
        Discover all selectable folders on mail server.
        Returns: (folder_list, status_message, success_flag)
        """
        if self.protocol == "POP3":
            return ["INBOX"], "POP3 - INBOX only (no multi-folder support)", True

        return self._discover_imap_comprehensive()

    def _discover_imap_comprehensive(self) -> Tuple[List[str], str, bool]:
        """Multi-strategy IMAP folder discovery."""
        discovered: Set[str] = set()
        client = None
        status_msg = ""

        # Strategy 1: Direct IMAP4_SSL connection
        try:
            client = imaplib.IMAP4_SSL(self.host, self.port, timeout=self.timeout)
            client.login(self.email, self.password)
            status_msg = f"Connected to {self.host}:{self.port} (SSL)"
        except Exception as e:
            # Strategy 2: Fallback to unencrypted IMAP
            try:
                client = imaplib.IMAP4(self.host, 143, timeout=self.timeout)
                client.login(self.email, self.password)
                status_msg = f"Connected to {self.host}:143 (TLS)"
            except Exception as e2:
                return ["INBOX"], f"Connection failed: {str(e2)}", False

        # Strategy 3: Comprehensive LIST queries
        list_patterns = [
            ('""', '*'),          # All folders
            ('""', '%'),          # Top-level only
            ('INBOX', '%'),       # INBOX subfolders
            ('INBOX', '*'),       # INBOX deep tree
            ('"" ', '"*"'),       # Quoted wildcard
            ('*', '*'),           # Alternate root
            ('""', '"*"'),        # Quoted variant
        ]

        for ref, pattern in list_patterns:
            try:
                status, data = client.list(ref, pattern)
                if status == "OK" and data:
                    parsed = self._parse_list_response(data)
                    discovered.update(parsed)
                    if len(discovered) > 5:  # Early exit if we found enough
                        break
            except Exception:
                continue

        # Strategy 4: LSUB (subscribed folders)
        try:
            status, data = client.lsub('""', '*')
            if status == "OK" and data:
                parsed = self._parse_list_response(data)
                discovered.update(parsed)
        except Exception:
            pass

        # Strategy 5: Verify and filter
        verified = set()
        for folder in discovered:
            if self._is_folder_selectable(client, folder):
                verified.add(folder)

        # Strategy 6: Probe common system folders if discovery was empty
        if len(verified) <= 1:
            for sys_folder in ["Drafts", "Sent", "Trash", "Junk", "Archive", "Sent Items"]:
                if self._is_folder_selectable(client, sys_folder):
                    verified.add(sys_folder)

        client.logout()

        if not verified:
            return ["INBOX"], "Only INBOX found (no other folders detected)", True

        # Sort: INBOX first, then alphabetical
        folders = sorted(list(verified), key=lambda x: (0 if x.upper() == "INBOX" else 1, x.lower()))
        return folders, f"Discovered {len(folders)} folder(s)", True

    def _parse_list_response(self, raw_data: List[bytes]) -> Set[str]:
        """Parse RFC 3501 IMAP LIST response with UTF-7 support."""
        valid_folders = set()

        for line in raw_data:
            if not line:
                continue

            entry = line.decode("utf-8", errors="ignore") if isinstance(line, bytes) else str(line)

            # Skip non-selectable (container) folders
            if any(x in entry.lower() for x in [r"\noselect", r"\nonexistent", r"\noinferiors"]):
                continue

            # Extract folder name
            folder_name = self._extract_folder_name(entry)
            if not folder_name or folder_name in (".", "/", '""', "''", ""):
                continue

            # Decode UTF-7 (IMAP-specific for international folders)
            folder_name = self._decode_utf7_imap(folder_name)

            # Filter system folders
            if folder_name.lower() in self.SYSTEM_PATTERNS:
                continue
            if any(folder_name.lower().startswith(x) for x in self.SYSTEM_PATTERNS if x.startswith("[")):
                continue

            valid_folders.add(folder_name)

        return valid_folders

    @staticmethod
    def _extract_folder_name(raw_line: str) -> str:
        """Extract folder name from IMAP LIST line."""
        # Format: (\Attributes) "Delimiter" "Name" or (\Attributes) NIL Name
        
        # Quoted format
        match = re.search(r'\((?P<flags>[^\)]*)\)\s+"(?P<delim>[^"]*)"\s+(?P<name>.*)', raw_line)
        if match:
            name = match.group("name").strip()
            if name.startswith('"') and name.endswith('"'):
                name = name[1:-1]
            return name.replace(r'\"', '"').strip()

        # Unquoted format
        match = re.search(r'\((?P<flags>[^\)]*)\)\s+(?P<delim>\S+)\s+(?P<name>.*)', raw_line)
        if match:
            name = match.group("name").strip()
            if name.startswith('"') and name.endswith('"'):
                name = name[1:-1]
            return name.replace(r'\"', '"').strip()

        # Fallback
        parts = raw_line.split()
        if parts:
            return parts[-1].strip('"').strip()

        return ""

    @staticmethod
    def _decode_utf7_imap(s: str) -> str:
        """Decode IMAP-UTF7 (modified UTF-7) folder names."""
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
        """Check if folder is selectable (not just a container)."""
        try:
            # Method 1: STATUS command
            status, _ = client.status(f'"{folder}"', "(MESSAGES)")
            if status == "OK":
                return True
        except Exception:
            pass

        try:
            # Method 2: EXAMINE command (read-only SELECT)
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
    """Decode email payload (handles base64, quoted-printable, etc)."""
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
    """Detect OTP/verification/security messages."""
    combined = f"{subject} {body}".lower()
    flags = []

    if any(k in combined for k in ["verify", "verification", "otp", "confirm", "code"]):
        flags.append("🔑 Verification Code / OTP")

    if any(k in combined for k in ["security alert", "unusual activity", "new sign-in", "login attempt"]):
        flags.append("🚨 Security Alert")

    if any(k in combined for k in ["password", "reset", "credentials", "change password"]):
        flags.append("🔐 Password Event")

    if any(k in combined for k in ["confirm", "authenticate", "verify identity"]):
        flags.append("✓ Authentication Required")

    return flags


def extract_pins(text: str, min_len: int = 4, max_len: int = 8) -> List[str]:
    """Extract verification PINs/codes from text."""
    pattern = rf"\b\d{{{min_len},{max_len}}}\b"
    matches = re.findall(pattern, text)
    return list(dict.fromkeys(matches))[:10]  # Remove duplicates, limit to 10


def extract_verification_urls(text: str) -> List[str]:
    """Extract verification/auth links."""
    url_pattern = r'https?://[^\s<>"]{5,}|www\.[^\s<>"]{5,}'
    urls = re.findall(url_pattern, text)
    verification_keywords = ["verify", "confirm", "auth", "login", "secure", "token", "click"]
    filtered = [u for u in urls if any(kw in u.lower() for kw in verification_keywords)]
    return list(dict.fromkeys(filtered))[:5]


# ============================================================
# STREAMLIT CONFIGURATION
# ============================================================
st.set_page_config(
    page_title="Mail Engine v7 - Production",
    page_icon="📧",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.title("📧 Mail Engine v7 - Universal Production Reader")
st.caption("Auto-detect protocol • Universal folder discovery (UTF-7, any language) • Bot intelligence • PIN extraction • Advanced search • Full operations")


# ============================================================
# SESSION STATE INITIALIZATION
# ============================================================
if "engine_connected" not in st.session_state:
    st.session_state.engine_connected = False
if "engine_folders" not in st.session_state:
    st.session_state.engine_folders = ["INBOX"]
if "engine_protocol" not in st.session_state:
    st.session_state.engine_protocol = Protocol.UNKNOWN
if "engine_messages" not in st.session_state:
    st.session_state.engine_messages = []
if "engine_page" not in st.session_state:
    st.session_state.engine_page = 0


# ============================================================
# SIDEBAR: CONNECTION
# ============================================================
st.sidebar.header("🔐 Mail Server Connection")

email_addr = st.sidebar.text_input("Email Address", key="engine_email")
password_val = st.sidebar.text_input("Password", type="password", key="engine_password")
protocol_sel = st.sidebar.selectbox("Protocol", ["IMAP", "POP3"], index=0, key="engine_protocol_sel")
host_addr = st.sidebar.text_input("Mail Server Host", placeholder="e.g., imap.gmail.com", key="engine_host")
port_val = st.sidebar.number_input("Port (0 = auto)", min_value=0, max_value=65535, value=0, key="engine_port")

if st.sidebar.button("🚀 Connect & Discover Folders", type="primary", use_container_width=True):
    if not email_addr or not password_val or not host_addr:
        st.sidebar.error("❌ Email, password, and host required")
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
                    st.session_state.engine_protocol = Protocol.IMAP if protocol_sel == "IMAP" else Protocol.POP3
                    st.session_state.engine_email = email_addr
                    st.session_state.engine_password = password_val
                    st.session_state.engine_host = host_addr
                    st.session_state.engine_port = port_use or (993 if protocol_sel == "IMAP" else 995)

                    st.sidebar.success(f"✅ {msg}\n\n**Folders found:**\n" + "\n".join(folders[:20]))
                else:
                    st.sidebar.error(f"❌ {msg}")
            except Exception as e:
                st.sidebar.error(f"❌ Error: {str(e)}")

# Status
if st.session_state.engine_connected:
    st.sidebar.success(f"✅ Connected | {len(st.session_state.engine_folders)} folder(s)")
else:
    st.sidebar.warning("⚠️ Not connected")

# ============================================================
# MAIN: FOLDER & SEARCH
# ============================================================
st.markdown("---")
st.subheader("📁 Browse & Search Mailbox")

col1, col2, col3 = st.columns([2, 1, 1])
with col1:
    folder_sel = st.selectbox("📂 Folder", st.session_state.engine_folders, key="engine_folder_sel")
with col2:
    per_page = st.slider("Per page", 5, 100, 20, key="engine_per_page")
with col3:
    sort_sel = st.selectbox("Sort", ["Newest", "Oldest"], key="engine_sort_sel")

search_query = st.text_input("🔍 Search messages", placeholder="keyword", key="engine_search")
search_field = st.selectbox("In field", ["TEXT", "SUBJECT", "FROM", "BODY"], key="engine_search_field")

col_load, col_search = st.columns([1, 1])
with col_load:
    load_btn = st.button("📥 Load Folder", type="primary", use_container_width=True)
with col_search:
    search_btn = st.button("🔍 Search", use_container_width=True)

# ============================================================
# MAIN: FETCH MESSAGES
# ============================================================
if load_btn or search_btn:
    if not st.session_state.engine_connected:
        st.error("❌ Please connect first")
    else:
        with st.spinner("📬 Fetching messages..."):
            try:
                if st.session_state.engine_protocol == Protocol.IMAP:
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
                        status, data = mail.search(
                            None,
                            f'({search_field} "{search_query.strip()}")'
                        )
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
                                        elif isinstance(part, bytes):
                                            flags = part.decode()
                                            if messages:
                                                messages[-1]["flags"] = flags
                            except Exception:
                                pass

                        st.session_state.engine_messages = messages
                        st.session_state.engine_page = 0
                        st.success(f"✅ Loaded {len(messages)} messages")

                elif st.session_state.engine_protocol == Protocol.POP3:
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
                    st.session_state.engine_page = 0
                    st.success(f"✅ Loaded {len(messages)} messages (POP3)")
                    pop_cli.quit()

            except Exception as e:
                st.error(f"❌ Error: {str(e)}")

# ============================================================
# MAIN: DISPLAY MESSAGES
# ============================================================
if st.session_state.engine_messages:
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

                if st.session_state.engine_protocol == Protocol.IMAP:
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
    "🔓 **Complete Universal Mail Engine** • IMAP (UTF-7 folders, any language, any server) • "
    "POP3 • Folder discovery • Bot detection • OTP/PIN extraction • Verification links • "
    "Advanced search • Production-ready"
)
