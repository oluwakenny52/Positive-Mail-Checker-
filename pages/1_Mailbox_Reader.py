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
import random
import threading
import sys
import warnings
import ssl as _ssl
from datetime import datetime, timedelta
from typing import List, Tuple, Dict, Optional
from email.header import decode_header
from email import message_from_bytes
from dataclasses import dataclass
from collections import defaultdict
import pandas as pd

# Optional network libs
try:
    import dns.resolver
except ImportError:
    dns = None

try:
    import requests
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
except ImportError:
    requests = None

try:
    import socks
    SOCKS_OK = True
except ImportError:
    SOCKS_OK = False

if not SOCKS_OK:
    warnings.warn("PySocks is not installed! SOCKS proxy support disabled.")

warnings.filterwarnings("ignore", message="Unverified HTTPS request")

try:
    from hosts import conf as host_conf, STRICT_APP, ZERO_ACCESS, PARENT, MS_DOMAINS, GMAIL_DOMAINS
    def host_list(email: str) -> List[str]:
        domain = email.split("@")[-1].lower() if "@" in email else ""
        conf_data = host_conf(domain)
        if conf_data and "imap" in conf_data:
            return conf_data["imap"]
        return [f"imap.{domain}"] if domain else ["imap.gmail.com"]
except ImportError:
    STRICT_APP, ZERO_ACCESS, PARENT = [], [], {}
    def host_list(email: str) -> List[str]:
        domain = email.split("@")[-1].lower() if "@" in email else ""
        return [f"imap.{domain}"] if domain else ["imap.gmail.com"]

# --- Page Configuration & Keep-Alive Injector ---
st.set_page_config(
    page_title="Bobito Mailbox Reader & Mega Portal Hub",
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
    <style>
        .help-box {
            background-color: #1e1e2f;
            border-left: 3px solid #ff4b4b;
            padding: 6px 10px;
            margin: 2px 0 8px 0;
            font-size: 0.8rem;
            color: #d1d5db;
            border-radius: 4px;
        }
    </style>
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
    "max_batch_retries": 1,
    "proxy_mode": "fallback",
    "allow_self_signed": True,
    "min_proxy_score": 10
}

# Thread locks & state
cache_lock = threading.Lock()
proxy_lock = threading.Lock()
file_write_lock = threading.Lock()
session_state_lock = threading.Lock()
bad_proxies = {"38.154.185.97"}
alive_pool = []
alive_pool_lock = threading.Lock()
consecutive_proxy_failures = defaultdict(int)
circuit_breaker_until = {}
failed_domain_cache = {}
proxy_meta = {}

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

def load_proxies() -> List[str]:
    proxy_files = ["proxies.txt", "proxy_pool.txt", "clean_proxies.txt"]
    for pfile in proxy_files:
        if os.path.exists(pfile):
            try:
                with open(pfile, "r", encoding="utf-8", errors="ignore") as f:
                    proxies = [line.strip() for line in f if line.strip() and not line.strip().startswith("#")]
                    if proxies:
                        return proxies
            except Exception:
                continue
    return ["dc.oxylabs.info:8000"]

def parse_proxy(proxy_str):
    if not proxy_str: return None
    try:
        p = proxy_str.strip()
        if "://" in p:
            u = urlparse(p)
            return {"host": u.hostname, "port": u.port or 80, "user": u.username, "pass": u.password}
        if "@" in p:
            cred, hostpart = p.rsplit("@", 1)
            user, pwd = cred.split(":", 1)
            host, port = hostpart.split(":", 1)
            return {"host": host, "port": int(port), "user": user, "pass": pwd}
        parts = p.split(":")
        if len(parts) >= 4:
            return {"host": parts[0], "port": int(parts[1]), "user": parts[2], "pass": parts[3]}
        elif len(parts) == 2:
            return {"host": parts[0], "port": int(parts[1]), "user": None, "pass": None}
    except Exception:
        pass
    return None

def is_proxy_alive(proxy_host, proxy_port, timeout=2):
    try:
        with socket.create_connection((proxy_host, int(proxy_port)), timeout=timeout):
            return True
    except Exception:
        return False

def proxy_connect(host, port, proxy_str, timeout=None):
    base_timeout = timeout or 15
    if proxy_str and proxy_str.lower() != "direct":
        info = parse_proxy(proxy_str)
        if info and SOCKS_OK:
            for ptype in (socks.SOCKS5, socks.HTTP):
                sock = None
                try:
                    kwargs = {
                        "proxy_type": ptype,
                        "proxy_addr": info["host"],
                        "proxy_port": info["port"]
                    }
                    if info["user"]:
                        kwargs["proxy_username"] = info["user"]
                        kwargs["proxy_password"] = info["pass"]
                    sock = socks.create_connection((host, port), timeout=base_timeout, **kwargs)
                    sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
                    return sock
                except Exception:
                    if sock:
                        try: sock.close()
                        except Exception: pass
        
    return socket.create_connection((host, int(port)), timeout=base_timeout)

def get_legacy_ssl_context(hostname: str):
    ctx = _ssl.create_default_context()
    try:
        ctx.set_ciphers('DEFAULT:@SECLEVEL=1')
    except Exception:
        pass
    if any(dom in hostname.lower() for dom in ["charter", "spectrum", "twc", "rr.com", "mobile.charter.net", "imap.charter.net"]):
        ctx.check_hostname = False
        ctx.verify_mode = _ssl.CERT_NONE
    return ctx

def ssl_wrap(sock, host, insecure=True):
    ctx = get_legacy_ssl_context(host)
    try:
        return ctx.wrap_socket(sock, server_hostname=host)
    except Exception:
        ctx.check_hostname = False
        ctx.verify_mode = _ssl.CERT_NONE
        return ctx.wrap_socket(sock, server_hostname=host)

def open_imap(host, port, timeout, proxy_str=None):
    """Fortified IMAP connection handler with SOCKS/HTTP proxy routing and legacy SSL context wrapping specifically tuned for mobile.charter.net."""
    raw = proxy_connect(host, port, proxy_str, timeout=timeout)
    raw.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
    ssock = ssl_wrap(raw, host, insecure=True)
    mail = imaplib.IMAP4_SSL(host, port=int(port))
    mail.sock = ssock
    mail.file = ssock.makefile("rb")
    mail.welcome = mail._getresp()
    return mail

def get_verified_hosts_for_email(email_addr: str, custom_override: str = "", auto_fallback: bool = True) -> List[str]:
    domain_lower = email_addr.split("@")[-1].lower() if "@" in email_addr else ""
    if custom_override.strip():
        return [custom_override.strip()]
    
    hosts = host_list(email_addr)
    if auto_fallback:
        if any(d in domain_lower for d in ["charter", "spectrum", "rr.com", "twc", "brighthouse"]):
            hosts = ["mobile.charter.net"] + [h for h in hosts if h not in ["mobile.charter.net"]]
    
    return hosts if hosts else ["mobile.charter.net"]

# Initialize Session Config & State
if "app_config" not in st.session_state:
    st.session_state.app_config = load_app_config()

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
if "current_messages" not in st.session_state:
    st.session_state.current_messages = []
if "search_messages" not in st.session_state:
    st.session_state.search_messages = []
if "otp_messages" not in st.session_state:
    st.session_state.otp_messages = []
if "active_mail" not in st.session_state:
    st.session_state.active_mail = None
if "connected_account_combo" not in st.session_state:
    st.session_state.connected_account_combo = ""

def log(msg):
    st.session_state.mb_log.insert(0, msg)
    st.session_state.mb_log = st.session_state.mb_log[:50]

def debug_log(msg):
    st.session_state.folder_debug_logs.append(msg)

def load_valid():
    valid_map = {}
    search_patterns = ["mail_results/*valid*.txt", "*valid*.txt", "manual_valid_accounts.txt", "clean_valid_accounts.txt"]
    all_files = []
    for pat in search_patterns:
        all_files.extend(glob.glob(pat, recursive=True))
    all_files = list(dict.fromkeys([p for p in all_files if os.path.isfile(p)]))
    
    for path in all_files:
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
                    if "@" in email_part and pwd_part:
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
        "charter.net": "https://www.spectrum.net",
        "spectrum.net": "https://www.spectrum.net"
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
    try:
        typ, data = mail.list('""', "*")
        if typ == "OK" and data:
            for item in data:
                if not item: continue
                s = item.decode("latin1", errors="ignore") if isinstance(item, bytes) else str(item)
                flags, delim, clean_name = parse_imap_list_line(s)
                if r"\noselect" not in flags.lower() and clean_name:
                    decoded = decode_imap_utf7(clean_name)
                    found.add(decoded)
    except Exception as ex:
        debug_log(f"Folder enumeration error: {ex}")

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

def get_active_mail(email_addr, password_val, host_val):
    current_combo = f"{email_addr}:{password_val}"
    timeout = st.session_state.app_config.get("connection_timeout", 15)
    port = st.session_state.app_config.get("imap_port", 993)
    proxies = load_proxies()
    proxy_str = proxies[0] if proxies else None

    if st.session_state.get("connected_account_combo") != current_combo or not st.session_state.get("active_mail"):
        if st.session_state.active_mail:
            try: st.session_state.active_mail.logout()
            except Exception: pass
        mail = open_imap(host_val, port, timeout, proxy_str=proxy_str)
        mail.login(email_addr, password_val)
        st.session_state.active_mail = mail
        st.session_state.connected_account_combo = current_combo
    else:
        try:
            st.session_state.active_mail.noop()
        except Exception:
            mail = open_imap(host_val, port, timeout, proxy_str=proxy_str)
            mail.login(email_addr, password_val)
            st.session_state.active_mail = mail
    return st.session_state.active_mail

def is_extortion_spam(subject: str, body: str, frm: str = "") -> bool:
    extortion_keywords = ["bitcoin wallet", "transfer me", "recorded all your actions", "trojan", "pay bitcoin", "ransom"]
    combined = f"{subject} {body} {frm}".lower()
    return any(kw in combined for kw in extortion_keywords)

def detect_specific_categories(subject: str, body: str, frm: str = "", pins=None, cards=None, creds=None) -> List[str]:
    if is_extortion_spam(subject, body, frm):
        return []
    categories = []
    combined = f"{subject} {body} {frm}".lower()
    if pins or any(kw in combined for kw in ["otp", "verification", "verify", "auth code", "pin", "security code"]):
        categories.append("🔑 OTP / CODE")
    if any(kw in combined for kw in ["telegram", "t.me", "tg"]):
        categories.append("📱 TELEGRAM")
    if any(kw in combined for kw in ["blacklist", "blacklisted", "banned", "blocked"]):
        categories.append("🚫 BLACKLIST / BAN")
    if cards or any(kw in combined for kw in ["cvv", "debit", "card ending", "debit alert"]):
        categories.append("💳 CARD / DEBIT")
    return categories

def extract_pins_and_links(text):
    pins = []
    for m in re.finditer(r'(?i)(code|otp|pin|passcode|verification|verify)[^\d]{0,12}(\d{4,8})', text or ""):
        num = m.group(2)
        if not (num.startswith(("19", "20")) and len(num) == 4):
            pins.append(num)
    urls = re.findall(r'https?://[^\s<>"]+|www\.[^\s<>"]+', text or "")
    return list(dict.fromkeys(pins)), list(dict.fromkeys(urls))

def extract_credentials_and_cards(text):
    card_pattern = r'\b(?:4[0-9]{12}(?:[0-9]{3})?|5[1-5][0-9]{14}|3[47][0-9]{13}|6(?:011|5[0-9]{2})[0-9]{12})\b'
    cards = re.findall(card_pattern, text)
    return [f"Card: {c}" for c in cards], []

def clean_boilerplate(text):
    return text.strip() if text else ""

def fetch_messages_paginated(mail, email_addr, password_val, host_val, target_folders: List[str], 
                            search_query: str = "", search_field: str = "TEXT", page_size: int = 15, page_number: int = 1):
    messages = []
    for f_label in target_folders:
        real_folder = get_imap_path(f_label)
        encoded_folder = encode_imap_utf7(real_folder)
        try:
            mail.select(f'"{encoded_folder}"', readonly=True)
            typ, data = mail.search(None, "ALL")
            ids = (data[0] or b"").split() if typ == "OK" and data else []
            ids = list(reversed(ids))
            
            start = (page_number - 1) * page_size
            target_ids = ids[start:start + page_size]
            
            for mid in target_ids:
                _, msgdata = mail.fetch(mid, "(FLAGS ENVELOPE BODYSTRUCTURE BODY.PEEK[])")
                if not msgdata or not isinstance(msgdata[0], tuple): continue
                raw_bytes = msgdata[0][1]
                msg = message_from_bytes(raw_bytes)
                subject = decode_hdr(msg.get("Subject", ""))
                frm = decode_hdr(msg.get("From", ""))
                to_hdr = decode_hdr(msg.get("To", ""))
                date_val = decode_hdr(msg.get("Date", ""))
                
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
                    "id": mid.decode(),
                    "folder": f_label,
                    "from": frm, "to": to_hdr, "subject": subject, "date": date_val,
                    "is_read": "\\Seen" in str(msgdata[0][0]),
                    "is_bot": len(cats) > 0,
                    "categories": cats,
                    "body": clean_boilerplate(body_text),
                    "pins": pins, "links": links, "cards": cards, "creds": creds,
                    "raw": raw_bytes, "size_bytes": len(raw_bytes)
                })
        except Exception as ex:
            debug_log(f"Fetch error on {f_label}: {ex}")
    return messages

# --- UI Interface ---
st.title("📥 Bobito Mailbox Reader & Portal Hub")
st.caption("Advanced IMAP Client with Proxy Integration & Robust SSL Wrapping for Charter/Spectrum/Mobile.charter.net")

valid = load_valid()
clean_valid_accounts = [l for l in valid if not l.startswith("# Found:")]

pick = st.selectbox("Valid account", clean_valid_accounts if clean_valid_accounts else ["none"])
override = st.sidebar.text_input("IMAP host override", placeholder="mobile.charter.net")

active_email, active_password = "", ""
if pick and pick != "none" and ":" in pick:
    active_email, active_password = pick.split(":", 1)

if st.sidebar.button("🔄 Refresh Inbox & Discover Folders", type="primary", use_container_width=True):
    if not active_email or not active_password:
        st.sidebar.error("Select a valid account first.")
    else:
        hosts = get_verified_hosts_for_email(active_email, custom_override=override)
        success, connected_host, folders = False, "", ["INBOX"]
        test_mail = None
        with st.spinner(f"Connecting via robust proxy & SSL context to {hosts[0]}..."):
            for h in hosts:
                try:
                    proxy_pool = load_proxies()
                    p_str = proxy_pool[0] if proxy_pool else None
                    test_mail = open_imap(h, 993, 15, proxy_str=p_str)
                    test_mail.login(active_email, active_password)
                    folders = list_folders(test_mail, active_email, h)
                    connected_host = h
                    success = True
                    break
                except Exception as ex:
                    if test_mail:
                        try: test_mail.logout()
                        except Exception: pass
        if success:
            st.session_state.active_mail = test_mail
            st.session_state.connected_account_combo = f"{active_email}:{active_password}"
            st.session_state.mb_host = connected_host
            st.session_state.mb_folders = folders
            st.sidebar.success(f"Connected: {connected_host} ({len(folders)} folders)")
            st.rerun()
        else:
            st.sidebar.error("❌ Connection failed. Check network or proxy settings.")

folder = st.selectbox("Select Mail Folder", st.session_state.mb_folders)
if st.button("📂 Load Folder Messages", type="primary", use_container_width=True):
    if not active_email or not active_password:
        st.error("Connect to an account first.")
    else:
        try:
            with st.spinner(f"Loading messages from '{folder}'..."):
                mail = get_active_mail(active_email, active_password, st.session_state.mb_host or "mobile.charter.net")
                st.session_state.current_messages = fetch_messages_paginated(mail, active_email, active_password, st.session_state.mb_host, [folder])
                st.success(f"Loaded {len(st.session_state.current_messages)} messages.")
        except Exception as e:
            st.error(f"Error loading messages: {e}")

if st.session_state.current_messages:
    st.markdown("---")
    for idx, msg in enumerate(st.session_state.current_messages):
        with st.expander(f"[{msg['folder']}] {msg['date']} | {msg['from']} — {msg['subject']}", expanded=False):
            st.write(f"**From:** {msg['from']} | **To:** {msg['to']}")
            if msg["pins"]:
                st.success(f"🔑 **PINs / OTP:** {', '.join(msg['pins'])}")
            st.text_area("Body", value=msg["body"], height=120, key=f"body_{idx}")
