"""One host table. Primary first, backup second, with MX resolution and universal fallbacks."""

import socket

YAHOO_IMAP = ["imap.mail.yahoo.com"]
YAHOO_POP = ["pop.mail.yahoo.com"]
MS_IMAP = ["outlook.office365.com", "imap-mail.outlook.com"]
MS_POP = ["outlook.office365.com"]
GMAIL_IMAP = ["imap.gmail.com"]
GMAIL_POP = ["pop.gmail.com"]

YAHOO_DOMAINS = {
    "yahoo.com", "ymail.com", "rocketmail.com", "yahoo.co.uk", "yahoo.fr",
    "yahoo.de", "yahoo.it", "yahoo.es", "yahoo.com.br",
}
MS_DOMAINS = {
    "outlook.com", "hotmail.com", "live.com", "msn.com", "hotmail.co.uk",
    "outlook.com.br", "hotmail.com.br", "live.com.br", "windowslive.com",
}
GMAIL_DOMAINS = {"gmail.com", "googlemail.com"}
STRICT_APP = GMAIL_DOMAINS | {"outlook.com", "hotmail.com", "live.com", "windowslive.com"}
ZERO_ACCESS = {"proton.me", "protonmail.com", "pm.me", "tuta.io", "tutanota.com", "tutamail.com", "tuta.com"}
PARENT = {"memoad.jp": "biglobe.ne.jp"}

ATT_FAMILY = {
    "att.net", "sbcglobal.net", "bellsouth.net", "pacbell.net", "swbell.net",
    "ameritech.net", "currently.com", "prodigy.net", "snet.net", "flash.net",
    "nvbell.net", "wans.net",
}
ATT_IMAP = ["imap.mail.yahoo.com", "imap.mail.att.net"]
ATT_POP = ["pop.mail.yahoo.com", "inbound.att.net"]

FRONTIER = {"frontier.com", "frontiernet.net", "myfrontiermail.com", "citlink.net", "epix.net", "gte.net"}
FRONTIER_IMAP = ["imap.frontier.com", "mail.frontier.com", "imap.mail.yahoo.com"]
FRONTIER_POP = ["pop.frontier.com", "pop.mail.yahoo.com"]

CHARTER = {
    "charter.net", "roadrunner.com", "rr.com", "spectrum.net",
    "cfl.rr.com", "tampabay.rr.com", "nyc.rr.com", "nycap.rr.com", "rochester.rr.com",
    "socal.rr.com", "ca.rr.com", "tx.rr.com", "satx.rr.com", "austin.rr.com",
    "oh.rr.com", "cinci.rr.com", "columbus.rr.com", "carolina.rr.com", "nc.rr.com",
    "sc.rr.com", "wi.rr.com", "mi.rr.com", "indy.rr.com", "kc.rr.com", "hawaii.rr.com",
}
CHARTER_IMAP = ["mobile.charter.net", "imap.spectrum.net", "mail.twc.com"]
CHARTER_POP = ["mobile.charter.net", "mail.twc.com"]

TWC = {"twc.com", "brighthouse.com", "adelphia.net"}
TWC_IMAP = ["mail.twc.com", "mobile.charter.net"]
TWC_POP = ["mail.twc.com", "mobile.charter.net"]

VERIZON = {"verizon.net"}
VERIZON_IMAP = ["imap.aol.com", "imap.verizon.net"]
VERIZON_POP = ["pop.aol.com", "pop.verizon.net"]

COUNTRY = {
    "bluewin.ch": ["imaps.bluewin.ch"],
    "interia.pl": ["poczta.interia.pl"],
    "wp.pl": ["imap.wp.pl"],
    "onet.pl": ["imap.onet.pl"],
    "o2.pl": ["poczta.o2.pl"],
    "libero.it": ["imapmail.libero.it"],
    "virgilio.it": ["in.virgilio.it"],
    "tiscali.it": ["imap.tiscali.it"],
    "free.fr": ["imap.free.fr"],
    "orange.fr": ["imap.orange.fr"],
    "web.de": ["imap.web.de"],
    "gmx.de": ["imap.gmx.net"],
    "gmx.net": ["imap.gmx.net"],
    "t-online.de": ["secureimap.t-online.de"],
    "comcast.net": ["imap.comcast.net"],
    "windstream.net": ["imap.windstream.net", "mail.windstream.net"],
    "suddenlink.net": ["imap.suddenlink.net", "mail.suddenlink.net"],
    "cox.net": ["imap.cox.net", "imap.mail.yahoo.com"],
    "optonline.net": ["mail.optimum.net"],
    "centurylink.net": ["mail.centurylink.net"],
    "embarqmail.com": ["mail.centurylink.net"],
    "centurytel.net": ["mail.centurylink.net"],
    "mediacombb.net": ["mail.mediacombb.net"],
    "mchsi.com": ["mail.mediacombb.net"],
    "earthlink.net": ["imap.earthlink.net"],
    "breezeline.net": ["mail.breezeline.net"],
    "astound.net": ["imap.wavecable.com"],
    "wavemail.com": ["imap.wavecable.com"],
    "armstrong.net": ["imap.armstrong.net"],
    "icloud.com": ["imap.mail.me.com"],
    "me.com": ["imap.mail.me.com"],
    "naver.com": ["imap.naver.com"],
    "qq.com": ["imap.qq.com"],
}

DISPOSABLE_PARTS = (
    "tempmail", "temp-mail", "guerrillamail", "10minutemail", "mailinator",
    "yopmail", "trashmail", "throwaway", "fakeinbox", "sharklasers",
    "rerttymail", "discard.email", "maildrop", "getnada", "moakt",
)

UNIVERSAL_IMAP_FALLBACKS = [
    "imap.gmail.com",
    "outlook.office365.com",
    "imap.mail.yahoo.com",
    "imap.aol.com"
]

UNIVERSAL_POP_FALLBACKS = [
    "pop.gmail.com",
    "outlook.office365.com",
    "pop.mail.yahoo.com",
    "pop.aol.com"
]


def domain_of(email_addr):
    return (email_addr or "").split("@")[-1].lower().strip()


def _pair(imap_hosts, pop_hosts):
    return {"imap": imap_hosts, "pop": pop_hosts, "pop3": pop_hosts}


def get_mx_host(domain):
    """Extract primary mail exchange host from DNS MX records if available."""
    try:
        import dns.resolver
        answers = dns.resolver.resolve(domain, 'MX')
        mx_records = sorted(answers, key=lambda x: x.preference)
        if mx_records:
            exchange = str(mx_records[0].exchange).rstrip('.')
            ex_lower = exchange.lower()
            if "google" in ex_lower or "gsuite" in ex_lower:
                return "imap.gmail.com"
            elif "outlook" in ex_lower or "protection.outlook.com" in ex_lower or "microsoft" in ex_lower:
                return "outlook.office365.com"
            elif "yahoo" in ex_lower or "yahoodns" in ex_lower:
                return "imap.mail.yahoo.com"
            elif "aol" in ex_lower:
                return "imap.aol.com"
            return exchange
    except Exception:
        pass
    return None


def conf(domain):
    domain = (domain or "").lower().strip()
    if domain in FRONTIER:
        return _pair(FRONTIER_IMAP, FRONTIER_POP)
    if domain in ATT_FAMILY:
        return _pair(ATT_IMAP, ATT_POP)
    if domain in VERIZON:
        return _pair(VERIZON_IMAP, VERIZON_POP)
    if domain in CHARTER or domain.endswith(".rr.com"):
        return _pair(CHARTER_IMAP, CHARTER_POP)
    if domain in TWC:
        return _pair(TWC_IMAP, TWC_POP)
    if domain in YAHOO_DOMAINS or domain.endswith(".yahoo.com"):
        return _pair(YAHOO_IMAP, YAHOO_POP)
    if domain in MS_DOMAINS or domain.endswith(".outlook.com") or domain.endswith(".hotmail.com"):
        return _pair(MS_IMAP, MS_POP)
    if domain in GMAIL_DOMAINS:
        return _pair(GMAIL_IMAP, GMAIL_POP)
    known = COUNTRY.get(domain)
    if known:
        return _pair(known, known)
    return None


def provider_hosts(email_addr):
    domain = domain_of(email_addr)
    got = conf(domain)
    if got:
        return got["imap"], got["pop"]
    
    mx_host = get_mx_host(domain)
    imap_candidates = []
    pop_candidates = []
    
    if mx_host and mx_host not in imap_candidates:
        imap_candidates.append(mx_host)
        pop_candidates.append(mx_host)
        
    imap_candidates.extend([f"mail.{domain}", f"imap.{domain}", f"secure.{domain}"])
    pop_candidates.extend([f"mail.{domain}", f"pop.{domain}"])
    
    for fb in UNIVERSAL_IMAP_FALLBACKS:
        if fb not in imap_candidates:
            imap_candidates.append(fb)
    for fb in UNIVERSAL_POP_FALLBACKS:
        if fb not in pop_candidates:
            pop_candidates.append(fb)
            
    return imap_candidates, pop_candidates


def host_list(email_addr):
    imap_hosts, _ = provider_hosts(email_addr)
    return imap_hosts[:6]


def is_disposable(email_addr):
    domain = domain_of(email_addr)
    return any(part in domain for part in DISPOSABLE_PARTS)
