import glob
import imaplib
import os
import re
from email.header import decode_header

import streamlit as st

from hosts import host_list

st.set_page_config(page_title="Mailbox", page_icon="M", layout="wide")

if "mb_log" not in st.session_state:
    st.session_state.mb_log = []
if "mb_folders" not in st.session_state:
    st.session_state.mb_folders = ["INBOX"]
if "mb_host" not in st.session_state:
    st.session_state.mb_host = ""


def log(msg):
    st.session_state.mb_log.insert(0, msg)
    st.session_state.mb_log = st.session_state.mb_log[:20]


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


def decode_hdr(value):
    try:
        out = []
        for part, enc in decode_header(value or ""):
            out.append(part.decode(enc or "utf-8", errors="ignore") if isinstance(part, bytes) else str(part))
        return "".join(out)
    except Exception:
        return str(value or "")


def list_folders(mail):
    found = set()
    try:
        typ, data = mail.list('""', "*")
        if typ == "OK" and data:
            for item in data:
                if not item:
                    continue
                s = item.decode("utf-8", errors="ignore") if isinstance(item, bytes) else str(item)
                quoted = re.findall(r'"((?:\\.|[^"\\])*)"', s)
                name = quoted[-1] if quoted else s.split()[-1]
                name = name.replace('\\"', '"').strip()
                if name and name not in (".", "/"):
                    found.add(name)
    except Exception:
        pass
    if not found:
        found.add("INBOX")
    return sorted(found, key=lambda x: (0 if x.lower() == "inbox" else 1, x.lower()))


def open_mail(email, password, host):
    mail = imaplib.IMAP4_SSL(host, 993, timeout=20)
    mail.login(email, password)
    return mail


def close_mail(mail):
    try:
        mail.logout()
    except Exception:
        try:
            mail.shutdown()
        except Exception:
            pass


def connect_first(email, password, override):
    hosts = [override] if override else host_list(email)
    last = "no host"
    for host in hosts:
        mail = None
        try:
            mail = open_mail(email, password, host)
            folders = list_folders(mail)
            close_mail(mail)
            return host, folders, None
        except Exception as e:
            last = f"{host}: {e}"
            if mail:
                close_mail(mail)
    return "", ["INBOX"], last


st.title("Mailbox")
st.caption("Reconnects on every click. Socket is not kept in session.")

valid = load_valid()
st.sidebar.header("Account")
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

st.sidebar.write("Host order: " + ", ".join(host_list(email)[:4]) if email else "-")

if st.sidebar.button("Load folders", type="primary"):
    if not email or not password:
        st.error("Need email and password")
    else:
        with st.spinner("Connecting..."):
            host, folders, err = connect_first(email, password, override.strip())
        if err:
            st.error(err)
            log(err)
        else:
            st.session_state.mb_host = host
            st.session_state.mb_folders = folders
            log(f"folders {len(folders)} via {host}")
            st.success(f"{host} · {len(folders)} folders")

folder = st.selectbox("Folder", st.session_state.mb_folders)
page_size = st.slider("Page size", 5, 40, 15)
if st.button("Load messages"):
    host = override.strip() or st.session_state.mb_host or (host_list(email)[:1] or [""])[0]
    if not email or not password or not host:
        st.error("Load folders first")
    else:
        mail = None
        try:
            with st.spinner(f"Reading {folder} on {host}"):
                mail = open_mail(email, password, host)
                mail.select(f'"{folder}"', readonly=True)
                typ, data = mail.search(None, "ALL")
                ids = (data[0] or b"").split() if typ == "OK" else []
                ids = list(reversed(ids))[:page_size]
                rows = []
                for mid in ids:
                    typ, msgdata = mail.fetch(mid, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])")
                    raw = msgdata[0][1] if msgdata and isinstance(msgdata[0], tuple) else b""
                    text = raw.decode("utf-8", errors="ignore")
                    sub = re.search(r"(?im)^Subject: (.*)$", text)
                    frm = re.search(r"(?im)^From: (.*)$", text)
                    rows.append({
                        "id": mid.decode(),
                        "from": decode_hdr(frm.group(1) if frm else ""),
                        "subject": decode_hdr(sub.group(1) if sub else ""),
                    })
            st.dataframe(rows, width="stretch")
            log(f"listed {len(rows)} in {folder}")
        except Exception as e:
            st.error(str(e))
            log(str(e))
        finally:
            if mail:
                close_mail(mail)

with st.expander("Log"):
    for line in st.session_state.mb_log:
        st.text(line)
