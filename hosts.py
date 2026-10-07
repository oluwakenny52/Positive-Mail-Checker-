"""IMAP host order: country map, then mail., imap., MX."""

COUNTRY = {
    "bluewin.ch": "imaps.bluewin.ch",
    "interia.pl": "poczta.interia.pl",
    "wp.pl": "imap.wp.pl",
    "onet.pl": "imap.onet.pl",
    "o2.pl": "poczta.o2.pl",
    "libero.it": "imapmail.libero.it",
    "virgilio.it": "in.virgilio.it",
    "tiscali.it": "imap.tiscali.it",
    "free.fr": "imap.free.fr",
    "orange.fr": "imap.orange.fr",
    "web.de": "imap.web.de",
    "gmx.de": "imap.gmx.net",
    "gmx.net": "imap.gmx.net",
    "t-online.de": "secureimap.t-online.de",
    "comcast.net": "imap.comcast.net",
    "windstream.net": "mail.windstream.net",
    "suddenlink.net": "mail.suddenlink.net",
}

BIG = {
    "gmail.com": "imap.gmail.com",
    "googlemail.com": "imap.gmail.com",
    "outlook.com": "outlook.office365.com",
    "hotmail.com": "outlook.office365.com",
    "live.com": "outlook.office365.com",
    "msn.com": "outlook.office365.com",
    "yahoo.com": "imap.mail.yahoo.com",
    "icloud.com": "imap.mail.me.com",
}


def mx_hosts(domain):
    try:
        import dns.resolver
    except Exception:
        return []
    try:
        ans = dns.resolver.resolve(domain, "MX")
        return [str(r.exchange).rstrip(".").lower() for r in sorted(ans, key=lambda x: x.preference)][:3]
    except Exception:
        return []


def host_list(email_addr):
    domain = (email_addr or "").split("@")[-1].lower().strip()
    seen, out = set(), []

    def add(h):
        h = (h or "").lower().strip(".")
        if h and h not in seen:
            seen.add(h)
            out.append(h)

    add(COUNTRY.get(domain))
    add(BIG.get(domain))
    add(f"mail.{domain}")
    add(f"imap.{domain}")
    add(f"imap.mail.{domain}")
    for mx in mx_hosts(domain):
        add(mx)
        if "outlook" in mx or "protection.outlook" in mx:
            add("outlook.office365.com")
        if "google" in mx or "gmail" in mx:
            add("imap.gmail.com")
    return out[:6]
