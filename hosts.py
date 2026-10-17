"""One host table. Checker and reader both import this."""

YAHOO_IMAP = ["imap.mail.yahoo.com"]
YAHOO_POP = ["pop.mail.yahoo.com"]
MS_IMAP = ["outlook.office365.com", "imap-mail.outlook.com"]
MS_POP = ["outlook.office365.com"]
GMAIL_IMAP = ["imap.gmail.com"]
GMAIL_POP = ["pop.gmail.com"]
ATT_IMAP = ["imap.mail.att.net"]
ATT_POP = ["inbound.att.net"]
CHARTER_IMAP = ["mobile.charter.net", "imap.charter.net"]
CHARTER_POP = ["mobile.charter.net", "pop.charter.net"]
TWC_IMAP = ["mail.twc.com"]
TWC_POP = ["mail.twc.com"]

YAHOO_DOMAINS = {
    "yahoo.com", "ymail.com", "rocketmail.com", "yahoo.co.uk", "yahoo.fr",
    "yahoo.de", "yahoo.it", "yahoo.es", "yahoo.com.br", "frontier.com",
    "frontiernet.net", "sbcglobal.net", "att.net", "bellsouth.net",
    "pacbell.net", "swbell.net", "ameritech.net", "currently.com",
    "nvbell.net", "prodigy.net", "snet.net", "wans.net",
}
MS_DOMAINS = {
    "outlook.com", "hotmail.com", "live.com", "msn.com", "hotmail.co.uk",
    "outlook.com.br", "hotmail.com.br", "live.com.br", "windowslive.com",
}
GMAIL_DOMAINS = {"gmail.com", "googlemail.com"}
ATT_ONLY = {"att.net"}
CHARTER_DOMAINS = {
    "charter.net", "roadrunner.com", "rr.com", "cfl.rr.com", "tampabay.rr.com",
    "nyc.rr.com", "nycap.rr.com", "rochester.rr.com", "socal.rr.com", "ca.rr.com",
    "tx.rr.com", "satx.rr.com", "austin.rr.com", "oh.rr.com", "cinci.rr.com",
    "columbus.rr.com", "carolina.rr.com", "nc.rr.com", "sc.rr.com", "wi.rr.com",
    "mi.rr.com", "indy.rr.com", "kc.rr.com", "hawaii.rr.com",
}
TWC_DOMAINS = {"twc.com", "brighthouse.com", "adelphia.net"}
STRICT_APP = GMAIL_DOMAINS | {"outlook.com", "hotmail.com", "live.com", "windowslive.com"}
ZERO_ACCESS = {"proton.me", "protonmail.com", "pm.me", "tuta.io", "tutanota.com", "tutamail.com", "tuta.com"}
PARENT = {"memoad.jp": "biglobe.ne.jp"}

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
    "icloud.com": "imap.mail.me.com",
    "me.com": "imap.mail.me.com",
    "naver.com": "imap.naver.com",
    "qq.com": "imap.qq.com",
}

DISPOSABLE_PARTS = (
    "tempmail", "temp-mail", "guerrillamail", "10minutemail", "mailinator",
    "yopmail", "trashmail", "throwaway", "fakeinbox", "sharklasers",
    "rerttymail", "discard.email", "maildrop", "getnada", "moakt",
)


def domain_of(email_addr):
    return (email_addr or "").split("@")[-1].lower().strip()


def conf(domain):
    domain = (domain or "").lower().strip()
    if domain in ATT_ONLY:
        return {"imap": ATT_IMAP, "pop": ATT_POP, "pop3": ATT_POP}
    if domain in YAHOO_DOMAINS or domain.endswith(".yahoo.com"):
        return {"imap": YAHOO_IMAP, "pop": YAHOO_POP, "pop3": YAHOO_POP}
    if domain in MS_DOMAINS or domain.endswith(".outlook.com") or domain.endswith(".hotmail.com"):
        return {"imap": MS_IMAP, "pop": MS_POP, "pop3": MS_POP}
    if domain in GMAIL_DOMAINS:
        return {"imap": GMAIL_IMAP, "pop": GMAIL_POP, "pop3": GMAIL_POP}
    if domain in CHARTER_DOMAINS or domain.endswith(".rr.com"):
        return {"imap": CHARTER_IMAP, "pop": CHARTER_POP, "pop3": CHARTER_POP}
    if domain in TWC_DOMAINS:
        return {"imap": TWC_IMAP, "pop": TWC_POP, "pop3": TWC_POP}
    known = COUNTRY.get(domain)
    if known:
        return {"imap": [known], "pop": [known], "pop3": [known]}
    return None


def provider_hosts(email_addr):
    got = conf(domain_of(email_addr))
    if got:
        return got["imap"], got["pop"]
    domain = domain_of(email_addr)
    return [f"mail.{domain}", f"imap.{domain}"], [f"mail.{domain}", f"pop.{domain}"]


def host_list(email_addr):
    imap_hosts, _ = provider_hosts(email_addr)
    return imap_hosts[:3]


def is_disposable(email_addr):
    domain = domain_of(email_addr)
    return any(part in domain for part in DISPOSABLE_PARTS)
