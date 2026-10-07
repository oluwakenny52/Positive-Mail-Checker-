"""Known IMAP/POP hosts. Do not invent imap.yahoo.com."""

YAHOO_IMAP = ["imap.mail.yahoo.com"]
YAHOO_POP = ["pop.mail.yahoo.com"]
MS_IMAP = ["outlook.office365.com", "imap-mail.outlook.com"]
MS_POP = ["outlook.office365.com"]
GMAIL_IMAP = ["imap.gmail.com"]
GMAIL_POP = ["pop.gmail.com"]
ATT_IMAP = ["imap.mail.att.net"]
ATT_POP = ["inbound.att.net"]

YAHOO_DOMAINS = {
    "yahoo.com", "ymail.com", "rocketmail.com", "yahoo.co.uk", "yahoo.fr",
    "yahoo.de", "yahoo.it", "yahoo.es", "yahoo.com.br", "frontier.com",
    "frontiernet.net", "sbcglobal.net", "att.net", "bellsouth.net",
    "pacbell.net", "swbell.net", "ameritech.net", "currently.com",
    "nvbell.net", "prodigy.net", "snet.net", "wans.net",
}
MS_DOMAINS = {
    "outlook.com", "hotmail.com", "live.com", "msn.com", "hotmail.co.uk",
    "outlook.com.br", "hotmail.com.br", "live.com.br",
}
GMAIL_DOMAINS = {"gmail.com", "googlemail.com"}
ATT_ONLY = {"att.net"}

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

DISPOSABLE_PARTS = (
    "tempmail", "temp-mail", "guerrillamail", "10minutemail", "mailinator",
    "yopmail", "trashmail", "throwaway", "fakeinbox", "sharklasers",
    "rerttymail", "discard.email", "maildrop", "getnada", "moakt",
)


def domain_of(email_addr):
    return (email_addr or "").split("@")[-1].lower().strip()


def bad_combo(email_addr):
    email = (email_addr or "").strip().lower()
    if email.count("@") != 1:
        return True
    local, domain = email.split("@", 1)
    if not local or not domain or "." not in domain:
        return True
    if "http" in local or "login.live" in local or " " in email:
        return True
    return False


def is_disposable(email_addr):
    domain = domain_of(email_addr)
    return any(part in domain for part in DISPOSABLE_PARTS)


def provider_hosts(email_addr):
    domain = domain_of(email_addr)
    if domain in YAHOO_DOMAINS or domain.endswith(".yahoo.com"):
        return YAHOO_IMAP, YAHOO_POP
    if domain in MS_DOMAINS or domain.endswith(".outlook.com") or domain.endswith(".hotmail.com"):
        return MS_IMAP, MS_POP
    if domain in GMAIL_DOMAINS:
        return GMAIL_IMAP, GMAIL_POP
    if domain in ATT_ONLY:
        return ATT_IMAP, ATT_POP
    known = COUNTRY.get(domain)
    if known:
        return [known], [known]
    return [f"mail.{domain}", f"imap.{domain}"], [f"mail.{domain}", f"pop.{domain}"]


def host_list(email_addr):
    imap_hosts, _ = provider_hosts(email_addr)
    return imap_hosts[:3]
