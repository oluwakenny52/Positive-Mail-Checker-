"""mailview.py - safe mail body renderer  (v13.55)

Plain module, NOT frame-gated - same status as runstate.py. Adds no block, moves
no TARGET_BLOCKS, renumbers nothing.

Renders a message as text or as real HTML. cid: inline images are resolved from
the message itself and embedded as data: URIs, so they display without a second
mailbox round trip and without a browser ever seeing a cid: it cannot resolve.

v13.55: render() takes the FALLBACK TEXT. It used to seed the box with "" so the
text view was always blank; the text is now derived from the raw message and the
caller's fallback is only a last resort. The markup handed to the widget is also
capped, because a 2 MB HTML body re-sanitised on every rerun is what segfaulted
the container.

Nothing here raises: every public function swallows and the caller falls back to
a text_area.
"""

import base64
import re

_MAX_PART = 4 * 1024 * 1024        # one inline image
_MAX_TOTAL = 16 * 1024 * 1024      # all inline images of one message
_MAX_RAW = 700 * 1024              # one whole message
_MAX_MARKUP = 400 * 1024           # what is actually handed to the widget
_TRUNC_HINT = 256000               # stored copy at/over this is probably cut

_CID_RX = re.compile(r"cid:([^\"')\s>]+)", re.I)
_DROP = ("script", "iframe", "object", "embed", "form", "link", "meta", "base")

_SHELL = (
    '<div style="all:initial;display:block;font-family:Arial,Helvetica,sans-serif;'
    'font-size:14px;line-height:1.45;color:#111;background:#fff;padding:12px;'
    'overflow-x:auto;word-break:break-word">%s</div>'
)


def _charset(part):
    cs = (part.get_content_charset() or "utf-8").lower()
    try:
        "".encode(cs)
        return cs
    except Exception:
        return "utf-8"


def _bytes(part):
    try:
        return part.get_payload(decode=True) or b""
    except Exception:
        return b""


def _parse(raw):
    if not raw:
        return None
    try:
        from email import message_from_bytes
        return message_from_bytes(raw)
    except Exception:
        return None


def split_message(raw):
    """(plain_text, html_text). Never raises."""
    text, markup = "", ""
    msg = _parse(raw)
    if msg is None:
        return text, markup
    try:
        for part in (msg.walk() if msg.is_multipart() else [msg]):
            ctype = part.get_content_type()
            if ctype == "text/plain" and not text:
                text = _bytes(part).decode(_charset(part), "replace")
            elif ctype == "text/html" and not markup:
                markup = _bytes(part).decode(_charset(part), "replace")
    except Exception:
        pass
    return text, markup


def inline_images(raw):
    """cid -> data: URI, from image parts carrying a Content-ID."""
    out, total = {}, 0
    msg = _parse(raw)
    if msg is None:
        return out
    try:
        for part in msg.walk():
            cid = (part.get("Content-ID") or "").strip().strip("<>")
            ctype = part.get_content_type()
            if not cid or not ctype.startswith("image/"):
                continue
            blob = _bytes(part)
            if not blob or len(blob) > _MAX_PART:
                continue
            total += len(blob)
            if total > _MAX_TOTAL:
                break
            out[cid] = "data:%s;base64,%s" % (ctype, base64.b64encode(blob).decode("ascii"))
    except Exception:
        pass
    return out


def attachments(raw):
    """[(filename, mime, bytes)] for named parts under the per-part cap."""
    out = []
    msg = _parse(raw)
    if msg is None:
        return out
    try:
        for part in msg.walk():
            name = part.get_filename()
            if not name:
                continue
            blob = _bytes(part)
            if blob and len(blob) <= _MAX_PART:
                out.append((name, part.get_content_type(), blob))
    except Exception:
        pass
    return out


def sanitize(markup, inline, allow_remote=False):
    """Embed cids, drop scripts and handlers, optionally kill remote assets."""
    markup = _CID_RX.sub(lambda m: inline.get(m.group(1), ""), markup or "")
    for tag in _DROP:
        markup = re.sub(r"(?is)<%s\b.*?</%s\s*>" % (tag, tag), "", markup)
    markup = re.sub(r"(?is)<!--.*?-->", "", markup)
    markup = re.sub(r"(?is)<!doctype[^>]*>", "", markup)
    markup = re.sub(r"(?i)\son[a-z]+\s*=\s*(\"[^\"]*\"|'[^']*')", "", markup)
    markup = re.sub(r"(?i)<a(\s|>)", r'<a target="_blank" rel="noopener noreferrer"\1', markup)
    markup = re.sub(r'(?i)(target="_blank"\s*){2,}', 'target="_blank" ', markup)
    if not allow_remote:
        markup = re.sub(r"(?is)<img\b[^>]*>",
                        lambda m: m.group(0) if "data:" in m.group(0) else "", markup)
        markup = re.sub(r"(?i)url\(\s*['\"]?https?://[^)]*\)", "none", markup)
    return markup


def full_raw(mail, uid, cap=_MAX_RAW):
    """Complete RFC822 bytes for ONE message. b'' on any failure."""
    if mail is None or uid is None:
        return b""
    try:
        typ, data = mail.fetch(uid, "(BODY.PEEK[])")
        if typ != "OK" or not data or not isinstance(data[0], tuple):
            return b""
        return (data[0][1] or b"")[:cap]
    except Exception:
        return b""


def _seed(st, key, value):
    try:
        if key not in st.session_state:
            st.session_state[key] = value or ""
    except Exception:
        pass


def _mode(st, key):
    try:
        return st.radio("View", ["Text", "HTML"], horizontal=True, key="mv_" + key)
    except Exception:
        return "Text"


def _paint(st, raw, key, markup, allow_remote):
    """Render the HTML. True when something was drawn."""
    if not markup:
        return False
    if len(markup) > _MAX_MARKUP:
        markup = markup[:_MAX_MARKUP] + "<p style='color:#666'>[... message truncated for display]</p>"
    shell = _SHELL % sanitize(markup, inline_images(raw), allow_remote)
    try:
        st.html(shell)
    except Exception:
        import streamlit.components.v1 as components
        components.html(shell, height=620, scrolling=True)
    _render_attachments(st, raw, key)
    return True


def _text_area(st, key):
    try:
        st.text_area("Message Body", height=180, key=key)
    except Exception:
        pass


def render(st, raw, key, fallback="", allow_remote=False):
    """Text/HTML switch from an already-complete raw message."""
    text, markup = split_message(raw)
    _seed(st, key, text.strip() or fallback)
    if _mode(st, key) == "HTML":
        try:
            if _paint(st, raw, key, markup, allow_remote):
                return
        except Exception:
            pass
    _text_area(st, key)


def render_auto(st, msg, key, mail_getter, allow_remote=False):
    """Same, but re-fetches when the stored copy is cut or carries cid: images.

    `mail_getter` is a zero-arg callable returning an open mailbox. It is only
    called for messages that actually need it, and a failure is swallowed.
    """
    raw = msg.get("raw") or b""
    text, markup = split_message(raw)
    if len(raw) >= _TRUNC_HINT or "cid:" in markup:
        try:
            full = full_raw(mail_getter(), msg.get("id"))
            if full:
                raw = full
                text, markup = split_message(raw)
        except Exception:
            pass
    _seed(st, key, text.strip() or msg.get("body", ""))
    if _mode(st, key) == "HTML":
        try:
            if _paint(st, raw, key, markup, allow_remote):
                return
        except Exception:
            pass
    _text_area(st, key)


def _render_attachments(st, raw, key):
    """Attachment list. Inline images get a preview, everything gets a download."""
    try:
        items = attachments(raw)
    except Exception:
        return
    if not items:
        return
    try:
        with st.expander("Attachments (%d)" % len(items), expanded=False):
            for i, (name, mime, blob) in enumerate(items):
                if mime.startswith("image/"):
                    try:
                        st.image(blob, caption=name)
                    except Exception:
                        pass
                st.download_button("%s (%s, %d bytes)" % (name, mime, len(blob)),
                                   data=blob, file_name=name, key="att_%s_%d" % (key, i))
    except Exception:
        pass
