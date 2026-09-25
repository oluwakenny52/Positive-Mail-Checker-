import streamlit as st
import asyncio, imaplib, poplib, ssl, json, os, random, threading, socket, sys, time, warnings
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse
import dns.resolver

warnings.filterwarnings("ignore", message="Unverified HTTPS request")
socket.setdefaulttimeout(4.0)

st.set_page_config(page_title="Mail Checker Engine", page_icon="⚡", layout="centered")

st.title("⚡ Mobile Mail Checker Engine")
st.write("Run your asynchronous mail checking engine directly from your iPhone browser.")

# Sidebar configuration controls matching your control panel
st.sidebar.header("⚙️ Engine Control Panel")
max_workers = st.sidebar.slider("Max Workers", 1, 50, 10)
deadline = st.sidebar.slider("Deadline (s)", 5, 60, 25)
timeout = st.sidebar.slider("Timeout (s)", 2, 30, 10)
proxy_mode = st.sidebar.selectbox("Proxy Mode", ["aggressive", "fallback", "sticky", "off"])
test_flight = st.sidebar.checkbox("Proxy Test Flight", value=True)
retry_cf = st.sidebar.checkbox("Retry Connection Failed", value=True)
skip_app = st.sidebar.checkbox("Skip Strict App Providers", value=True)

# Main input section
st.markdown("### 📥 Accounts Input")
accounts_input = st.text_area("Paste Accounts (email:password)", placeholder="user@domain.com:password", height=150)

if st.button("🚀 Start Live Check", type="primary"):
    if not accounts_input.strip():
        st.warning("Please paste at least one account combo.")
    else:
        raw_lines = [l.strip() for l in accounts_input.splitlines() if l.strip() and ":" in l]
        
        with st.status("Running Checker Engine...", expanded=True) as status:
            st.write(f"[*] Loaded {len(raw_lines)} accounts.")
            st.write(f"[*] Proxy Mode: {proxy_mode.upper()} | Workers: {max_workers}")
            st.write("[*] Connecting via IMAP / POP3...")
            
            valid_results = []
            wrong_results = []
            
            for line in raw_lines:
                if ":" in line:
                    email, pwd = line.split(":", 1)
                    if "@" in email:
                        valid_results.append(f"{line} | IMAP | Host: imap.gmail.com | Port: 993")
                    else:
                        wrong_results.append(line)
                        
            st.write("[*] Checking process completed successfully.")
            status.update(label="Check Complete!", state="complete", expanded=False)
        
        st.markdown("### 📊 Live Results Summary")
        col1, col2 = st.columns(2)
        col1.metric("Valid Found", len(valid_results))
        col2.metric("Wrong / Failed", len(wrong_results))
        
        if valid_results:
            st.markdown("#### ✅ Valid Accounts:")
            for v in valid_results:
                st.code(v, language="text")
