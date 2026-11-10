"""mailview.py - safe mail body renderer

Plain module, NOT frame-gated - same status as runstate.py. Adds no block, moves
no TARGET_BLOCKS, renumbers nothing.

Renders a message as text or as real HTML. cid: inline images are resolved from
the message itself and embedded as data: URIs, so they display without a second
mailbox round trip and without a browser ever seeing a cid: it cannot resolve.

CHANGES IN THIS REVISION
------------------------
* VIEW IS CALLER-CONTROLLED. render()/render_auto() take view="HTML"|"Text". The
  per-message radio remains as a fallback but is skipped when the caller passes a
  mode, so one global switch can drive every message instead of the reader having
  to click HTML on each row.
* NO REFETCH PER RERUN. full_raw() results and the finished sanitised shell are
  both memoised. The old code re-fetched and re-sanitised a megabyte of markup on
  every rerun, which is what made the page stall. A cut message now costs ONE
  round trip for the whole session.
* CACHES ARE NAMESPACED. Every cache key carries `ns` (the reader passes the
  account address). They were keyed on folder + uid only, so two different
  accounts both holding "INBOX message 1" shared one entry and the second user
  could be served the first user's body.
* CAPS RAISED. _MAX_RAW 700 KB -> 8 MB, _MAX_MARKUP 400 KB -> 4 MB. Truncation is
  the exception now, and when it happens it says so.
* ATTACHMENTS CACHED. The part walk ran twice per render (paint + list).
* UNKNOWN KEYWORDS TOLERATED. render()/render_auto() swallow **kw. A page left in
  sys.modules from before a push can pass a keyword this module does not have; it
  used to be a TypeError that took the whole row down. The page reloads a stale
  mailview itself, so this is the reverse case only - an old page against a new
  module - and it is one line of insurance rather than a second code path.

__version__ STAYS "v13.55" ON PURPOSE. app.py block 109 captions a mismatch with
"update it to v13.55"; bumping the constant would print that caption on every
load. The changes above are file-level, not a version move.

Nothing here raises: every public function swallows and the caller falls back to
a text_area.
"""

import base64
import re

__version__ = "v13.55"

_MAX_PART = 4 * 1024 * 1024        # one inline image
_MAX_TOTAL = 16 * 1024 * 1024      # all inline images of one message
_MAX_RAW = 8 * 1024 * 1024         # one whole message
_MAX_MARKUP = 4 * 1024 * 1024      # what is actually handed to the widget
_TRUNC_HINT = 256000               # stored copy at/over this is probably cut

_RAW_CACHE = {}                    # (ns|key, uid) -> complete raw bytes
_SHELL_CACHE = {}                  # (ns|key, allow_remote, len) -> html
_ATT_CACHE = {}                    # ns|key -> [(name, mime, bytes)]
_CACHE_MAX = 24

_CID_RX = re.compile(r"cid:([^\"')\s>]+)", re.I)
# Paired tags: the closing tag exists, so the greedy-until-close removal works.
_DROP_PAIRED = ("script", "iframe", "object", "embed", "form")
# Void tags: no closing tag. `.*?</link>` never matches, so they need their own
# single-tag pattern. This was the hole.
_DROP_VOID = ("link", "meta", "base")
# Kept as one name in case anything reads it; the sanitiser uses the two above.
_DROP = _DROP_PAIRED + _DROP_VOID

_SHELL = (
    '<div style="all:initial;display:block;font-family:Arial,Helvetica,sans-serif;'
    'font-size:14px;line-height:1.45;color:#111;background:#fff;padding:12px;'
    'overflow-x:auto;word-break:break-word">%s</div>'
)


def _ns(ns, key):
    """Cache key carrying the account, so two users never share an entry."""
    return "%s|%s" % (ns or "", key or "")


def _memo(store, key, value):
    try:
        if key in store:
            store[key] = value
            return
        if len(store) >= _CACHE_MAX:
            for old in list(store)[: max(1, len(store) - _CACHE_MAX + 1)]:
                store.pop(old, None)
        store[key] = value
    except Exception:
        pass


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
            # check BEFORE adding, so the cap is not overshot by one part.
            if total + len(blob) > _MAX_TOTAL:
                break
            total += len(blob)
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
    # Paired tags - closing tag present.
    for tag in _DROP_PAIRED:
        markup = re.sub(r"(?is)<%s\b.*?</%s\s*>" % (tag, tag), "", markup)
    # Void tags - single tag, no closing form.
    for tag in _DROP_VOID:
        markup = re.sub(r"(?is)<%s\b[^>]*>" % tag, "", markup)
    markup = re.sub(r"(?is)<!--.*?-->", "", markup)
    markup = re.sub(r"(?is)<!doctype[^>]*>", "", markup)
    # quoted handler values first, then UNQUOTED ones (`onerror=alert(1)`).
    markup = re.sub(r"(?i)\son[a-z]+\s*=\s*(\"[^\"]*\"|'[^']*')", "", markup)
    markup = re.sub(r"(?i)\son[a-z]+\s*=\s*[^\"'\s>]+", "", markup)
    # a javascript: href executes in the widget's origin on click.
    markup = re.sub(r"(?i)href\s*=\s*([\"'])\s*javascript:[^\"']*\1", 'href="#"', markup)
    markup = re.sub(r"(?i)<a(\s|>)", r'<a target="_blank" rel="noopener noreferrer"\1', markup)
    markup = re.sub(r'(?i)(target="_blank"\s*){2,}', 'target="_blank" ', markup)
    if not allow_remote:
        markup = re.sub(r"(?is)<img\b[^>]*>",
                        lambda m: m.group(0) if "data:" in m.group(0) else "", markup)
        markup = re.sub(r"(?i)url\(\s*['\"]?https?://[^)]*\)", "none", markup)
    return markup


def full_raw(mail, uid, cap=_MAX_RAW, ns="", key=""):
    """Complete RFC822 bytes for ONE message. b'' on any failure.

    Memoised per (ns, key, uid). The reader used to call this on every rerun for
    every message at or over _TRUNC_HINT - one IMAP round trip per row per
    keystroke.
    """
    if mail is None or uid is None:
        return b""
    memo_key = (_ns(ns, key), str(uid))
    hit = _RAW_CACHE.get(memo_key)
    if hit:
        return hit
    try:
        typ, data = mail.fetch(uid, "(BODY.PEEK[])")
        if typ != "OK" or not data or not isinstance(data[0], tuple):
            return b""
        blob = (data[0][1] or b"")[:cap]
        if blob:
            _memo(_RAW_CACHE, memo_key, blob)
        return blob
    except Exception:
        return b""


def _seed(st, key, value):
    try:
        if key not in st.session_state:
            st.session_state[key] = value or ""
    except Exception:
        pass


def _mode(st, key):
    """Per-message fallback switch, used only when the caller passes no view."""
    try:
        return st.radio("View", ["Text", "HTML"], horizontal=True, key="mv_" + key)
    except Exception:
        return "Text"


def _cached_attachments(ns, key, raw):
    k = _ns(ns, key)
    if k in _ATT_CACHE:
        return _ATT_CACHE[k]
    items = attachments(raw)
    _memo(_ATT_CACHE, k, items)
    return items


def _paint(st, raw, key, markup, allow_remote, ns=""):
    """Render the HTML. True when something was drawn."""
    if not markup:
        return False
    shell_key = (_ns(ns, key), bool(allow_remote), len(raw))
    shell = _SHELL_CACHE.get(shell_key)
    if shell is None:
        cut = len(markup) > _MAX_MARKUP
        body = markup[:_MAX_MARKUP] if cut else markup
        shell = _SHELL % sanitize(body, inline_images(raw), allow_remote)
        if cut:
            shell += ("<p style='color:#666'>[... display cut at %d KB - the full "
                      "message is in View Raw RFC822]</p>" % (_MAX_MARKUP // 1024))
        _memo(_SHELL_CACHE, shell_key, shell)
    try:
        st.html(shell)
    except Exception:
        import streamlit.components.v1 as components
        components.html(shell, height=620, scrolling=True)
    _render_attachments(st, raw, key, ns)
    return True


def _text_area(st, raw, key, ns=""):
    """The text view, and its attachments."""
    try:
        st.text_area("Message Body", height=180, key=key)
    except Exception:
        pass
    _render_attachments(st, raw, key, ns)


def render(st, raw, key, fallback="", allow_remote=False, view=None, ns="", **kw):
    """Text/HTML render from an already-complete raw message.

    **kw absorbs a keyword this revision does not know, so a caller left over
    from before a push cannot take the row down with a TypeError.
    """
    text, markup = split_message(raw)
    _seed(st, key, text.strip() or fallback)
    mode = view or _mode(st, key)
    if mode == "HTML":
        try:
            if _paint(st, raw, key, markup, allow_remote, ns):
                return
        except Exception:
            pass
    _text_area(st, raw, key, ns)


def render_auto(st, msg, key, mail_getter, allow_remote=False, view=None, ns="", **kw):
    """Same, but completes a cut copy from the server (once) and prefers HTML.

    `mail_getter` is a zero-arg callable returning an open mailbox. It is only
    called for a message whose stored copy is cut, and the result is cached, so a
    rerun does not dial the server again. **kw as in render().
    """
    raw = msg.get("raw") or b""
    uid = msg.get("id")
    text, markup = split_message(raw)
    if len(raw) >= _TRUNC_HINT or "cid:" in markup:
        try:
            full = full_raw(mail_getter(), uid, ns=ns, key=key)
            if full and len(full) >= len(raw):
                raw = full
                text, markup = split_message(raw)
        except Exception:
            pass
    _seed(st, key, text.strip() or msg.get("body", ""))
    mode = view or _mode(st, key)
    if mode == "HTML":
        try:
            if _paint(st, raw, key, markup, allow_remote, ns):
                return
        except Exception:
            pass
    _text_area(st, raw, key, ns)


def _render_attachments(st, raw, key, ns=""):
    """Attachment list. Inline images get a preview, everything gets a download."""
    try:
        items = _cached_attachments(ns, key, raw)
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
