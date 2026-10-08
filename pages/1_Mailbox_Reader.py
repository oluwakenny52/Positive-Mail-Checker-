import glob
import imaplib
import poplib
import os
import re
import base64
import socket
import asyncio
from email import message_from_bytes
from email.header import decode_header
from typing import List, Dict, Tuple, Optional
from enum import Enum
import streamlit as st

# ============================================================
# PROTOCOL ENUM
# ============================================================
class MailProtocol(Enum):
    IMAP = "imap"
    POP3 = "pop3"
    WEBMAIL = "webmail"
    UNKNOWN = "unknown"


# ============================================================
# UTF-7 IMAP DECODER (for folder names like &ZEcw4TD8MOswxzD8ML8-)
# ============================================================
def decode_utf7_imap(s: str) -> str:
    """Decode IMAP-UTF7 (modified UTF-7) folder names."""
    if not s:
        return s
    
    result = []
    i = 0
    
    while i < len(s):
        if s[i] == '&':
            if i + 1 < len(s) and s[i + 1] == '-':
                # &- is literal &
                result.append('&')
                i += 2
            else:
                # Find closing -
                end = s.find('-', i + 1)
                if end == -1:
                    result.append(s[i:])
                    break
                
                # Extract base64 part
                b64_part = s[i + 1:end]
                if b64_part:
                    try:
                        # Decode: base64 → UTF-16BE → decode
                        decoded_bytes = base64.b64decode(b64_part + '===')
                        decoded_text = decoded_bytes.decode('utf-16-be')
                        result.append(decoded_text)
                    except Exception:
                        result.append(s[i:end + 1])
                
                i = end + 1
        else:
            result.append(s[i])
            i += 1
    
    return ''.join(result)


# ============================================================
# PROTOCOL DETECTION ENGINE
# ============================================================
def detect_protocol(host: str, email: str, password: str) -> Tuple[MailProtocol, str]:
    """
    Detect which protocol the server supports.
    Returns: (protocol, description)
    """
    
    # Try IMAP (most common)
    try:
        mail = imaplib.IMAP4_SSL(host, 993, timeout=8)
        mail.login(email, password)
        mail.logout()
        return MailProtocol.IMAP, "IMAP (port 993)"
    except Exception:
        pass
    
    # Try IMAP unencrypted
    try:
        mail = imaplib.IMAP4(host, 143, timeout=8)
        mail.login(email, password)
        mail.logout()
        return MailProtocol.IMAP, "IMAP (port 143)"
    except Exception:
        pass
    
    # Try POP3 SSL
    try:
        mail = poplib.POP3_SSL(host, 995, timeout=8)
        mail.user(email)
        mail.pass_(password)
        mail.quit()
        return MailProtocol.POP3, "POP3 (port 995) - INBOX only"
    except Exception:
        pass
    
    # Try POP3 unencrypted
    try:
        mail = poplib.POP3(host, 110, timeout=8)
        mail.user(email)
        mail.pass_(password)
        mail.quit()
        return MailProtocol.POP3, "POP3 (port 110) - INBOX only"
    except Exception:
        pass
    
    # Try webmail detection
    try:
        import requests
        requests.packages.urllib3.disable_warnings()
        
        urls = [
            f"https://{host}/",
            f"https://{host}/mail/",
            f"https://{host}/webmail/",
            f"https://{host}/roundcube/",
            f"https://{host}/squirrelmail/",
        ]
        
        for url in urls:
            try:
                r = requests.get(url, timeout=5, verify=False)
                if r.status_code < 500:
                    return MailProtocol.WEBMAIL, f"Webmail Interface ({host})"
            except:
                pass
    except Exception:
        pass
    
    return MailProtocol.UNKNOWN, "Unknown/Not accessible"


# ============================================================
# IMAP HANDLER
# ============================================================
def get_imap_folders(host: str, email: str, password: str, port: int = 993) -> List[str]:
    """Get IMAP folder list with UTF-7 decoding."""
    
    folders = ["INBOX"]
    
    # System folders to hide
    system_patterns = {
        "drafts", "sent", "sent items", "sent mail", "sent messages",
        "trash", "deleted items", "deleted", "bin",
        "junk", "junk email", "junk mail", "spam",
        "archive", "all mail", "important",
        "[gmail]", "[imap]", "[local]",
        "notes", "tasks", "contacts", "calendar",
        ".trash", ".drafts", ".sent", ".archive",
        "starred", "custom", "flagged",
    }
    
    try:
        # Try SSL first
        try:
            mail = imaplib.IMAP4_SSL(host, port, timeout=15)
        except:
            # Fall back to unencrypted
            mail = imaplib.IMAP4(host, port, timeout=15)
        
        mail.login(email, password)
        
        typ, data = mail.list()
        
        if typ == "OK" and data:
            for item in data:
                if not item:
                    continue
                
                line = item.decode("utf-8", errors="ignore") if isinstance(item, bytes) else str(item)
                
                # Parse RFC 3501: (Attributes) "Delimiter" "Name"
                try:
                    # Simple extraction: get last quoted string
                    if '"' in line:
                        parts = line.split('"')
                        if len(parts) >= 2:
                            name_raw = parts[-2]
                            
                            # Decode UTF-7
                            name = decode_utf7_imap(name_raw)
                            
                            # Filter
                            if not name or name in ("", "/", "."):
                                continue
                            
                            if name.lower() in system_patterns:
                                continue
                            
                            if name.startswith(".") or name.startswith("["):
                                continue
                            
                            if "\\noselect" in line.lower() or "\\nonexistent" in line.lower():
                                continue
                            
                            if name not in folders:
                                folders.append(name)
                except Exception:
                    continue
        
        mail.logout()
    
    except Exception as e:
        pass
    
    # Sort: INBOX first, then alphabetical
    return sorted(folders, key=lambda x: (0 if x.upper() == "INBOX" else 1, x.lower()))


def get_imap_messages(host: str, email: str, password: str, folder: str, limit: int = 20, port: int = 993) -> List[Dict]:
    """Get messages from IMAP folder."""
    
    messages = []
    
    try:
        try:
            mail = imaplib.IMAP4_SSL(host, port, timeout=15)
        except:
            mail = imaplib.IMAP4(host, port, timeout=15)
        
        mail.login(email, password)
        mail.select(f'"{folder}"', readonly=True)
        
        typ, data = mail.search(None, "ALL")
        
        if typ == "OK":
            ids = (data[0] or b"").split()
            
            # Get last N messages
            ids = list(reversed(ids))
            ids = ids[:limit]
            
            for msg_id in ids:
                try:
                    typ, msgdata = mail.fetch(msg_id, "BODY.PEEK[HEADER]")
                    
                    if msgdata and isinstance(msgdata[0], tuple):
                        raw_header = msgdata[0][1]
                        
                        # Parse email
                        msg = message_from_bytes(raw_header)
                        
                        from_addr = decode_hdr(msg.get("From", ""))
                        subject = decode_hdr(msg.get("Subject", "(no subject)"))
                        date_str = decode_hdr(msg.get("Date", ""))
                        
                        messages.append({
                            "id": msg_id.decode(),
                            "from": from_addr,
                            "subject": subject,
                            "date": date_str,
                            "folder": folder,
                            "protocol": "IMAP"
                        })
                except Exception:
                    pass
        
        mail.logout()
    
    except Exception as e:
        pass
    
    return messages


# ============================================================
# POP3 HANDLER
# ============================================================
def get_pop3_folders(host: str, email: str, password: str) -> List[str]:
    """POP3 has no folder support - return INBOX only."""
    return ["INBOX"]


def get_pop3_messages(host: str, email: str, password: str, limit: int = 20) -> List[Dict]:
    """Get messages from POP3 (INBOX only)."""
    
    messages = []
    
    try:
        try:
            mail = poplib.POP3_SSL(host, 995, timeout=15)
        except:
            mail = poplib.POP3(host, 110, timeout=15)
        
        mail.user(email)
        mail.pass_(password)
        
        stat = mail.stat()
        count = stat[0]
        
        # Get last N messages
        start = max(1, count - limit + 1)
        
        for i in range(start, count + 1):
            try:
                typ, msgdata, octets = mail.retr(i)
                raw_msg = b'\n'.join(msgdata)
                
                msg = message_from_bytes(raw_msg)
                
                from_addr = decode_hdr(msg.get("From", ""))
                subject = decode_hdr(msg.get("Subject", "(no subject)"))
                date_str = decode_hdr(msg.get("Date", ""))
                
                messages.append({
                    "id": str(i),
                    "from": from_addr,
                    "subject": subject,
                    "date": date_str,
                    "folder": "INBOX",
                    "protocol": "POP3"
                })
            except Exception:
                pass
        
        mail.quit()
    
    except Exception as e:
        pass
    
    return messages


# ============================================================
# WEBMAIL BROWSER SCRAPER
# ============================================================
async def scrape_webmail_folders(host: str, email: str, password: str) -> List[str]:
    """Scrape folders from webmail interface using Playwright."""
    
    folders = ["INBOX"]
    
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return folders
    
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            
            # List of webmail URLs to try
            urls = [
                f"https://{host}/",
                f"https://{host}/mail/",
                f"https://{host}/webmail/",
                f"https://{host}/roundcube/",
                f"https://{host}/squirrelmail/",
                f"https://{host}/horde/",
                f"https://{host}/zimbra/",
                f"https://{host}/index.php",
            ]
            
            for url in urls:
                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=10000)
                    await page.wait_for_timeout(800)
                    
                    # Try to find and fill login form
                    try:
                        # Email field
                        email_field = await page.query_selector(
                            'input[type="email"], input[name*="user"], input[name*="login"], input[name*="email"]'
                        )
                        if email_field:
                            await email_field.fill(email)
                            await page.wait_for_timeout(200)
                        
                        # Password field
                        pass_field = await page.query_selector('input[type="password"]')
                        if pass_field:
                            await pass_field.fill(password)
                            await page.wait_for_timeout(200)
                        
                        # Submit button
                        submit = await page.query_selector(
                            'button[type="submit"], input[type="submit"], button:has-text("Login"), button:has-text("Sign in")'
                        )
                        if submit:
                            await submit.click()
                            await page.wait_for_timeout(2000)
                    except Exception:
                        pass
                    
                    # Wait for page to load
                    await page.wait_for_timeout(1000)
                    
                    # Scrape folders using multiple selectors
                    selectors = [
                        '[role="treeitem"]',
                        '[role="option"]',
                        'li[data-folder]',
                        'div[data-folder]',
                        '.folder',
                        '[aria-label*="folder"]',
                        '[data-test*="folder"]',
                        '.mail-folder',
                        'li.folder',
                        'a[data-folder]',
                    ]
                    
                    for selector in selectors:
                        try:
                            locs = page.locator(selector)
                            count = await locs.count()
                            
                            if count > 0:
                                for i in range(min(count, 100)):
                                    try:
                                        text = await locs.nth(i).inner_text()
                                        text = text.strip()
                                        
                                        if text and len(text) > 1:
                                            if text.lower() not in ("compose", "refresh", "settings", "add folder"):
                                                if not any(x in text.lower() for x in system_patterns):
                                                    if text not in folders:
                                                        folders.append(text)
                                    except:
                                        pass
                                
                                if len(folders) > 2:  # Found some folders
                                    break
                        except:
                            pass
                    
                    if len(folders) > 2:
                        break
                
                except Exception:
                    continue
            
            await browser.close()
    
    except Exception as e:
        pass
    
    return list(dict.fromkeys(folders))  # Remove duplicates, keep order


# System folder patterns (for webmail)
system_patterns = {
    "drafts", "sent", "sent items", "sent mail",
    "trash", "deleted items", "junk", "junk email", "spam",
    "archive", "all mail", "[gmail]",
}


async def get_webmail_folders_async(host: str, email: str, password: str) -> List[str]:
    """Async wrapper for webmail folder scraping."""
    return await scrape_webmail_folders(host, email, password)


# ============================================================
# DECODE EMAIL HEADER
# ============================================================
def decode_hdr(value):
    try:
        out = []
        for part, enc in decode_header(value or ""):
            if isinstance(part, bytes):
                out.append(part.decode(enc or "utf-8", errors="ignore"))
            else:
                out.append(str(part))
        return "".join(out)
    except Exception:
        return str(value or "")


# ============================================================
# LOAD VALID ACCOUNTS FROM FILES
# ============================================================
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
                    
                    email, pwd = line.split(":", 1)
                    combo = f"{email.strip()}:{pwd.split('|')[0].strip()}"
                    
                    if combo not in seen:
                        seen.add(combo)
                        rows.append(combo)
        except Exception:
            continue
    
    return rows


# ============================================================
# STREAMLIT CONFIG
# ============================================================
st.set_page_config(
    page_title="Bobito Universal Mail Reader",
    page_icon="📬",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.title("📬 Bobito Universal Mail Reader v5")
st.caption("Reads ANY mail server (IMAP, POP3, Webmail, Custom). Auto-detects protocol and folders.")

# Session state
if "mb_log" not in st.session_state:
    st.session_state.mb_log = []
if "mb_folders" not in st.session_state:
    st.session_state.mb_folders = ["INBOX"]
if "mb_protocol" not in st.session_state:
    st.session_state.mb_protocol = MailProtocol.UNKNOWN
if "mb_host" not in st.session_state:
    st.session_state.mb_host = ""
if "mb_port" not in st.session_state:
    st.session_state.mb_port = 993

def log(msg):
    st.session_state.mb_log.insert(0, msg)
    st.session_state.mb_log = st.session_state.mb_log[:100]

valid_accounts = load_valid_accounts()

# ============================================================
# SIDEBAR
# ============================================================
st.sidebar.header("🔌 Universal Mail Connection")

# Account selection
pick = st.sidebar.selectbox("Select account", valid_accounts or ["(enter manually)"])

if pick and pick != "(enter manually)" and ":" in pick:
    email, password = pick.split(":", 1)
    custom_email = email
    custom_password = password
else:
    custom_email = st.sidebar.text_input("Email address")
    custom_password = st.sidebar.text_input("Password", type="password")

custom_host = st.sidebar.text_input("Mail server host (e.g., mail.example.com, imap.gmail.com)")

email = custom_email.strip() if custom_email else ""
password = custom_password.strip() if custom_password else ""
host = custom_host.strip() if custom_host else ""

# Connect button
if st.sidebar.button("🔗 Auto-Detect & Connect", type="primary", use_container_width=True):
    if not email or not password or not host:
        st.sidebar.error("❌ Please enter email, password, and mail server host")
    else:
        with st.spinner("🔍 Detecting protocol..."):
            protocol, protocol_name = detect_protocol(host, email, password)
            st.session_state.mb_protocol = protocol
            st.session_state.mb_host = host
            
            log(f"Detected: {protocol_name}")
            
            if protocol == MailProtocol.UNKNOWN:
                st.sidebar.error(f"❌ Could not connect to {host}")
            else:
                st.sidebar.success(f"✅ Connected via {protocol_name}")
                
                # Get folders based on protocol
                with st.spinner("📂 Discovering folders..."):
                    if protocol == MailProtocol.IMAP:
                        folders = get_imap_folders(host, email, password)
                    elif protocol == MailProtocol.POP3:
                        folders = get_pop3_folders(host, email, password)
                    elif protocol == MailProtocol.WEBMAIL:
                        # Use async browser scraper
                        try:
                            loop = asyncio.new_event_loop()
                            asyncio.set_event_loop(loop)
                            folders = loop.run_until_complete(scrape_webmail_folders(host, email, password))
                        except Exception as e:
                            folders = ["INBOX"]
                    else:
                        folders = ["INBOX"]
                    
                    st.session_state.mb_folders = folders
                    log(f"Found {len(folders)} folder(s)")
                    
                    st.sidebar.info(
                        f"📂 **{len(folders)} Folder(s) Found:**\n\n" + 
                        "\n".join(folders[:20]) + 
                        (f"\n... and {len(folders) - 20} more" if len(folders) > 20 else "")
                    )

# Activity log
st.sidebar.markdown("---")
st.sidebar.subheader("📜 Activity Log")
with st.sidebar.expander("View", expanded=False):
    for line in st.session_state.mb_log[:20]:
        st.text(line)

# Download valid accounts
if valid_accounts:
    st.sidebar.markdown("---")
    st.sidebar.subheader("💾 Export Valid Accounts")
    valid_text = "\n".join(valid_accounts)
    st.sidebar.download_button(
        label=f"📥 Download ({len(valid_accounts)} accounts)",
        data=valid_text,
        file_name=f"valid_accounts_{len(valid_accounts)}.txt",
        mime="text/plain",
        use_container_width=True
    )

# ============================================================
# MAIN UI
# ============================================================
st.markdown("---")

col1, col2, col3 = st.columns([2, 1, 1])

with col1:
    folder = st.selectbox("📁 Select Folder", st.session_state.mb_folders or ["INBOX"])

with col2:
    msg_limit = st.slider("Messages to load", 5, 100, 20)

with col3:
    sort_order = st.selectbox("Sort", ["Newest First", "Oldest First"])

# Load messages button
if st.button("📧 Load Messages", type="primary", use_container_width=True):
    if not email or not password or not st.session_state.mb_host:
        st.error("❌ Please connect first")
    else:
        protocol = st.session_state.mb_protocol
        host = st.session_state.mb_host
        
        messages = []
        
        with st.spinner(f"📬 Loading messages from {folder}..."):
            if protocol == MailProtocol.IMAP:
                messages = get_imap_messages(host, email, password, folder, msg_limit)
            
            elif protocol == MailProtocol.POP3:
                messages = get_pop3_messages(host, email, password, msg_limit)
            
            elif protocol == MailProtocol.WEBMAIL:
                st.info("ℹ Webmail detected - message reading requires additional browser automation. For now, please access via webmail directly or use IMAP if available.")
            
            if messages:
                st.success(f"✅ Loaded {len(messages)} messages from {folder}")
                log(f"Loaded {len(messages)} messages from {folder}")
                
                # Display messages
                st.markdown("---")
                st.subheader(f"✉ Messages from {folder}")
                
                for idx, msg in enumerate(messages):
                    from_addr = msg.get("from", "Unknown")[:50]
                    subject = msg.get("subject", "(no subject)")[:80]
                    date_str = msg.get("date", "")[:20]
                    
                    with st.expander(f"📧 {date_str} | {from_addr} - {subject}"):
                        col_from, col_date = st.columns([2, 1])
                        with col_from:
                            st.write(f"**From:** {msg['from']}")
                        with col_date:
                            st.write(f"**Date:** {msg['date']}")
                        
                        st.write(f"**Subject:** {msg['subject']}")
                        st.write(f"**Folder:** {msg['folder']}")
                        st.write(f"**Protocol:** {msg['protocol']}")
            
            else:
                st.info("No messages found or could not load messages")

# ============================================================
# FOOTER
# ============================================================
st.markdown("---")
st.caption(
    "🔓 Supports IMAP (all servers, UTF-7 folder names), POP3 (INBOX only), "
    "Webmail (Roundcube, Squirrelmail, Horde, Zimbra, cPanel, Plesk, Gmail, Outlook, Yahoo, Custom)"
)
