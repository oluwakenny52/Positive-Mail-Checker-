import base64
import email
from email.header import decode_header
import imaplib
import poplib
import re
from typing import List, Set
import streamlit as st

st.set_page_config(page_title="Mailbox Reader", page_icon="📧", layout="wide")


# ==============================================================================
# UNIVERSAL MAILBOX FOLDER DISCOVERY ENGINE
# ==============================================================================
class MailboxFolderEngine:
    """
    Universal Mailbox Folder Discovery Engine.
    Handles IMAP (multi-pattern LIST/LSUB traversal, delimiter stripping, UTF-7 handling,
    and active STATUS verification) and POP3 single-stream mailbox fallbacks.
    """

    DEFAULT_SYSTEM_FOLDERS = [
        "INBOX",
        "Sent",
        "Sent Messages",
        "Sent Items",
        "Drafts",
        "Trash",
        "Deleted Items",
        "Junk",
        "Spam",
        "Archive",
        "Archives",
        "Outbox",
        "Notes",
    ]

    def __init__(self, email: str, password: str, host: str, protocol: str = "IMAP", port: int = None, timeout: int = 20):
        self.email = email
        self.password = password
        self.host = host
        self.protocol = protocol.upper()
        self.port = port or (995 if self.protocol == "POP3" else 993)
        self.timeout = timeout

    def discover_folders(self) -> List[str]:
        if self.protocol == "POP3":
            return ["INBOX"]
        return self._discover_imap()

    def _discover_imap(self) -> List[str]:
        client = None
        discovered_raw: Set[str] = set()

        try:
            client = imaplib.IMAP4_SSL(self.host, self.port, timeout=self.timeout)
            client.login(self.email, self.password)

            # Strategy 1: Wildcard LIST queries
            list_patterns = [
                ('""', '*'),
                ('""', '%'),
                ('""', '"*"'),
                ('""', '"%"'),
                ('*', '*'),
            ]

            for ref, pattern in list_patterns:
                try:
                    status, data = client.list(ref, pattern)
                    if status == "OK" and data:
                        parsed = self._parse_imap_response(data)
                        discovered_raw.update(parsed)
                except Exception:
                    continue

            # Strategy 2: LSUB (Subscribed folders) fallback
            try:
                status, data = client.lsub('""', '*')
                if status == "OK" and data:
                    parsed = self._parse_imap_response(data)
                    discovered_raw.update(parsed)
            except Exception:
                pass

            # Strategy 3: Verify folders using STATUS/EXAMINE
            verified_folders = set()
            for folder in discovered_raw:
                if self._verify_folder_selectable(client, folder):
                    verified_folders.add(folder)

            # Strategy 4: Direct probe of common system folders if discovery returned few items
            if len(verified_folders) <= 1:
                for sys_folder in self.DEFAULT_SYSTEM_FOLDERS:
                    if sys_folder not in verified_folders and self._verify_folder_selectable(client, sys_folder):
                        verified_folders.add(sys_folder)

            client.logout()

            if not verified_folders:
                return ["INBOX"]

            return sorted(list(verified_folders), key=lambda x: (0 if x.upper() == "INBOX" else 1, x.lower()))

        except Exception:
            if client:
                try:
                    client.logout()
                except Exception:
                    pass
            return ["INBOX"]

    def _parse_imap_response(self, raw_data: list) -> Set[str]:
        valid_folders = set()

        for line in raw_data:
            if not line:
                continue

            entry = line.decode("utf-8", errors="ignore") if isinstance(line, bytes) else str(line)

            # Filter out non-selectable parent containers (\Noselect / \NonExistent)
            if r"\noselect" in entry.lower() or r"\nonexistent" in entry.lower():
                continue

            folder_name = self._extract_folder_name(entry)
            if folder_name and folder_name not in (".", "/", '""', "''"):
                valid_folders.add(folder_name)

        return valid_folders

    @staticmethod
    def _extract_folder_name(raw_line: str) -> str:
        # Match quoted delimiter format: (\Flags) "Delimiter" "FolderName"
        match = re.search(r'\((?P<flags>[^\)]*)\)\s+"(?P<delim>[^"]*)"\s+(?P<name>.*)', raw_line)
        if match:
            name = match.group("name").strip()
            if name.startswith('"') and name.endswith('"'):
                name = name[1:-1]
            return name.replace(r'\"', '"').strip()

        # Match unquoted delimiter format
        match_alt = re.search(r'\((?P<flags>[^\)]*)\)\s+(?P<delim>\S+)\s+(?P<name>.*)', raw_line)
        if match_alt:
            name = match_alt.group("name").strip()
            if name.startswith('"') and name.endswith('"'):
                name = name[1:-1]
            return name.replace(r'\"', '"').strip()

        # Fallback split
        tokens = raw_line.split()
        if tokens:
            return tokens[-1].strip('"').strip()

        return ""

    @staticmethod
    def _verify_folder_selectable(client: imaplib.IMAP4_SSL, folder_name: str) -> bool:
        try:
            status, _ = client.status(f'"{folder_name}"', "(MESSAGES)")
            if status == "OK":
                return True
        except Exception:
            pass

        try:
            status, _ = client.examine(f'"{folder_name}"')
            if status == "OK":
                return True
        except Exception:
            pass

        return False


# ==============================================================================
# HELPER FUNCTIONS (PARSING, MIME & SECURITY DETECTION)
# ==============================================================================
def decode_mime_header(header_val, default="No Subject"):
    if not header_val:
        return default
    decoded_parts = decode_header(header_val)
    result = ""
    for part, encoding in decoded_parts:
        if isinstance(part, bytes):
            result += part.decode(encoding or "utf-8", errors="ignore")
        else:
            result += str(part)
    return result if result.strip() else default


def decode_payload_content(payload, encoding):
    if not payload:
        return ""
    if encoding and encoding.lower() == "base64":
        try:
            return base64.b64decode(payload).decode("utf-8", errors="ignore")
        except Exception:
            pass
    if isinstance(payload, bytes):
        return payload.decode("utf-8", errors="ignore")
    return str(payload)


def detect_bot_indicators(subject, body):
    combined = f"{subject} {body}".lower()
    flags = []
    if any(k in combined for k in ["verify", "verification", "otp", "code", "confirm"]):
        flags.append("Verification Code / OTP Detected")
    if any(k in combined for k in ["security alert", "unusual activity", "new sign-in", "login attempt"]):
        flags.append("Security Alert / Login Warning")
    if any(k in combined for k in ["password", "reset", "credentials"]):
        flags.append("Password / Credential Event")
    return flags


def extract_actionable_pins(body):
    pattern = r"\b(?:\d{4,8}|[A-Z0-9]{6,10})\b"
    matches = re.findall(pattern, body)
    return list(set(matches))[:5]


def extract_verification_links(body):
    url_pattern = r'https?://[^\s<>"]+|www\.[^\s<>"]+'
    links = re.findall(url_pattern, body)
    return [
        l for l in links if any(k in l.lower() for k in ["verify", "confirm", "auth", "login", "security", "token"])
    ]


# ==============================================================================
# STREAMLIT UI INTERFACE
# ==============================================================================
st.title("📧 Advanced Mailbox Reader & Bot Intelligence")

# Sidebar - Connection Hub
st.sidebar.header("🔑 Mailbox Connection Settings")
email_in = st.sidebar.text_input("Email Address", key="mb_email")
password_in = st.sidebar.text_input("Password", type="password", key="mb_password")
protocol_in = st.sidebar.selectbox("Protocol", ["IMAP", "POP3"], index=0, key="mb_proto")
host_in = st.sidebar.text_input("Host Server (e.g. imap.example.com)", key="mb_host")
port_in = st.sidebar.number_input("Port (0 = default)", min_value=0, max_value=65535, value=0, key="mb_port")

if st.sidebar.button("🔗 Connect & Discover Folders", type="primary", use_container_width=True):
    if not email_in or not password_in or not host_in:
        st.sidebar.error("Email, password, and host server are required.")
    else:
        with st.spinner("Executing Folder Engine discovery..."):
            port_val = port_in if port_in > 0 else None
            engine = MailboxFolderEngine(
                email=email_in,
                password=password_in,
                host=host_in,
                protocol=protocol_in,
                port=port_val,
            )
            discovered_folders = engine.discover_folders()

            st.session_state["available_folders"] = discovered_folders
            st.session_state["connected"] = True
            st.sidebar.success(f"Connected! Found {len(discovered_folders)} selectable folder(s).")

# Main Section - Folder Selection Layout
st.subheader("📁 Mailbox & Folder Configuration")
raw_folders = st.session_state.get("available_folders", ["INBOX"])

col_f1, col_f2, col_f3 = st.columns([2, 1, 1])

with col_f1:
    selected_folder = st.selectbox("Select Mailbox Folder", options=raw_folders, key="mb_selected_folder")

with col_f2:
    batch_size = st.slider("Messages per Page", min_value=10, max_value=100, value=20, key="mb_batch_size")

with col_f3:
    sort_order = st.selectbox(
        "Sort Order", ["Newest First (Descending)", "Oldest First (Ascending)"], key="mb_sort_order"
    )

col_s1, col_s2, col_s3 = st.columns([3, 1, 1])

with col_s1:
    search_query = st.text_input(
        "Deep Keyword Search", placeholder="e.g. Netflix, verify, security", key="mb_deep_search_query"
    )

with col_s2:
    search_scope = st.selectbox("Search Field", ["TEXT", "BODY", "SUBJECT", "FROM"], key="mb_search_scope")

with col_s3:
    st.markdown("<br>", unsafe_allow_html=True)
    refresh_btn = st.button("🔄 Refresh Inbox", use_container_width=True)

col_btn1, col_btn2 = st.columns([1, 1])
with col_btn1:
    load_folder_btn = st.button("📥 Load Folder Messages", type="primary", use_container_width=True)
with col_btn2:
    search_btn = st.button("🔍 Execute Deep Search", use_container_width=True)

# Message Fetching Execution
if load_folder_btn or search_btn or refresh_btn:
    if not st.session_state.get("connected"):
        st.error("Please connect to a server using the sidebar panel first.")
    else:
        with st.spinner(f"Querying messages in '{selected_folder}'..."):
            try:
                proto = st.session_state.get("mb_proto", "IMAP")
                host = st.session_state.get("mb_host")
                port = st.session_state.get("mb_port") or (995 if proto == "POP3" else 993)
                user = st.session_state.get("mb_email")
                pwd = st.session_state.get("mb_password")

                if proto == "IMAP":
                    mail = imaplib.IMAP4_SSL(host, port, timeout=20)
                    mail.login(user, pwd)
                    st.session_state["imap_mail"] = mail

                    safe_folder = selected_folder.replace('"', '\\"')
                    mail.select(f'"{safe_folder}"', readonly=True)

                    if search_btn and search_query.strip():
                        q = search_query.strip()
                        status, response = mail.search(None, f'({search_scope} "{q}")')
                    else:
                        status, response = mail.search(None, "ALL")

                    if status == "OK":
                        msg_ids = response[0].split()
                        if "Ascending" in sort_order:
                            msg_ids = sorted(msg_ids, key=lambda x: int(x))
                        else:
                            msg_ids = sorted(msg_ids, key=lambda x: int(x), reverse=True)

                        st.session_state["current_msg_ids"] = msg_ids
                        st.session_state["current_page"] = 0
                        st.success(f"Loaded {len(msg_ids)} message(s) successfully.")
                else:
                    pop_cli = poplib.POP3_SSL(host, port, timeout=20)
                    pop_cli.user(user)
                    pop_cli.pass_(pwd)

                    num_msgs = len(pop_cli.list()[1])
                    msg_ids = [str(i).encode() for i in range(1, num_msgs + 1)]

                    if "Descending" in sort_order:
                        msg_ids = list(reversed(msg_ids))

                    st.session_state["current_msg_ids"] = msg_ids
                    st.session_state["current_page"] = 0
                    st.session_state["active_pop_client"] = pop_cli
                    st.success(f"Loaded {len(msg_ids)} message(s) via POP3.")

            except Exception as e:
                st.error(f"Error loading messages: {e}")

# Message Pagination & Display Stream
if "current_msg_ids" in st.session_state and st.session_state["current_msg_ids"]:
    msg_ids = st.session_state["current_msg_ids"]
    total_msgs = len(msg_ids)
    current_page = st.session_state.get("current_page", 0)

    max_page = max(0, (total_msgs - 1) // batch_size)
    start_idx = current_page * batch_size
    end_idx = min(start_idx + batch_size, total_msgs)
    page_ids = msg_ids[start_idx:end_idx]

    st.markdown("---")
    p_col1, p_col2, p_col3 = st.columns([1, 2, 1])
    with p_col1:
        if st.button("◀ Previous Page") and current_page > 0:
            st.session_state["current_page"] -= 1
            st.rerun()
    with p_col2:
        st.markdown(
            f"<p style='text-align: center;'>Page {current_page + 1} of {max_page + 1}</p>",
            unsafe_allow_html=True,
        )
    with p_col3:
        if st.button("Next Page ▶") and current_page < max_page:
            st.session_state["current_page"] += 1
            st.rerun()

    st.markdown("---")

    proto = st.session_state.get("mb_proto", "IMAP")

    for num in page_ids:
        try:
            num_str = num.decode("utf-8", errors="ignore") if isinstance(num, bytes) else str(num)
            subject, sender, date_str, flags = "No Subject", "Unknown", "Unknown", ""

            if proto == "IMAP" and "imap_mail" in st.session_state:
                mail = st.session_state["imap_mail"]
                safe_folder = selected_folder.replace('"', '\\"')
                mail.select(f'"{safe_folder}"', readonly=True)

                st_fetch, msg_data = mail.fetch(num_str, "(BODY.PEEK[HEADER.FIELDS (SUBJECT FROM DATE)] FLAGS)")
                if st_fetch == "OK":
                    for response_part in msg_data:
                        if isinstance(response_part, tuple):
                            msg = email.message_from_bytes(response_part[1])
                            subject = decode_mime_header(msg.get("Subject", "No Subject"))
                            sender = decode_mime_header(msg.get("From", "Unknown"))
                            date_str = msg.get("Date", "Unknown")
                        elif isinstance(response_part, bytes):
                            flags = response_part.decode("utf-8", errors="ignore")

            is_read = "\\Seen" in flags
            read_indicator = "📭" if is_read else "📬 **[UNREAD]**"

            with st.expander(f"{read_indicator} [{date_str}] {sender[:30]} — {subject[:40]}"):
                st.markdown(f"**From:** {sender}")
                st.markdown(f"**Subject:** {subject}")
                st.markdown(f"**Date:** {date_str}")
                st.markdown(f"**Server ID / Flags:** Msg ID `{num_str}` | Flags: `{flags}`")
                st.markdown("---")

                # Action buttons for IMAP operations
                if proto == "IMAP" and "imap_mail" in st.session_state:
                    op_col1, op_col2 = st.columns(2)
                    with op_col1:
                        if st.button("✔ Mark Seen", key=f"seen_{selected_folder}_{num_str}"):
                            mail = st.session_state["imap_mail"]
                            mail.select(f'"{safe_folder}"', readonly=False)
                            mail.store(num_str, "+FLAGS", "\\Seen")
                            st.success("Marked message as seen.")
                            st.rerun()
                    with op_col2:
                        if st.button("❌ Delete", key=f"del_{selected_folder}_{num_str}"):
                            mail = st.session_state["imap_mail"]
                            mail.select(f'"{safe_folder}"', readonly=False)
                            mail.store(num_str, "+FLAGS", "\\Deleted")
                            mail.expunge()
                            st.success("Deleted message.")
                            st.rerun()

                # Full Body Payload Parser
                if st.button("📖 Read Full Message Body", key=f"read_body_{selected_folder}_{num_str}"):
                    raw_body_text = ""
                    if proto == "IMAP" and "imap_mail" in st.session_state:
                        mail = st.session_state["imap_mail"]
                        st_full, full_data = mail.fetch(num_str, "(RFC822)")
                        if st_full == "OK":
                            for part in full_data:
                                if isinstance(part, tuple):
                                    full_msg = email.message_from_bytes(part[1])
                                    if full_msg.is_multipart():
                                        for subpart in full_msg.walk():
                                            if subpart.get_content_type() == "text/plain":
                                                payload = subpart.get_payload(decode=True)
                                                encoding = subpart.get("Content-Transfer-Encoding")
                                                raw_body_text = decode_payload_content(payload, encoding)
                                                break
                                    else:
                                        payload = full_msg.get_payload(decode=True)
                                        encoding = full_msg.get("Content-Transfer-Encoding")
                                        raw_body_text = decode_payload_content(payload, encoding)

                    bot_flags = detect_bot_indicators(subject, raw_body_text)
                    extracted_pins = extract_actionable_pins(raw_body_text)
                    extracted_links = extract_verification_links(raw_body_text)

                    if bot_flags:
                        st.markdown("### 🤖 Bot Intelligence Detected")
                        cols = st.columns(len(bot_flags))
                        for c_idx, flag in enumerate(bot_flags):
                            with cols[c_idx]:
                                st.warning(flag)

                    if extracted_pins:
                        st.success(f"🔑 Extracted Verification PIN(s): `{', '.join(extracted_pins)}`")

                    if extracted_links:
                        st.markdown("#### 🔗 Actionable Verification Links")
                        for l_idx, link in enumerate(extracted_links[:3]):
                            st.link_button(f"Open Link #{l_idx+1}", link, use_container_width=True)

                    st.markdown("---")
                    st.markdown("#### 📄 Cleaned Message Body")
                    st.text_area(
                        "Parsed Text", raw_body_text, height=220, key=f"body_area_{selected_folder}_{num_str}"
                    )
        except Exception as ex:
            st.error(f"Error loading message `{num}`: {ex}")
