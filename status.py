VALID = "valid"
WRONG = "wrong_password"
APP = "need_app_password"
FAILED = "connection_failed"
SKIP = "skipped_cooldown"
UNKNOWN = "unknown"
RETRY = "retry_later"          # IP-blocked / rate-limited / proxy-broken — not the account's fault

ALL = {VALID, WRONG, APP, FAILED, SKIP, UNKNOWN, RETRY}
