"""Proxy pool picker.

all / us_only lock immediately.
country / mix show live country checkboxes, highest score first, then Done.
"""


def country_code(name: str) -> str:
    raw = (name or "").strip()
    up = raw.upper()
    known = {
        "UNITED STATES": "US",
        "USA": "US",
        "UNITED KINGDOM": "GB",
        "UK": "GB",
        "GERMANY": "DE",
        "FRANCE": "FR",
        "SPAIN": "ES",
        "ITALY": "IT",
        "JAPAN": "JP",
        "POLAND": "PL",
        "CANADA": "CA",
        "NETHERLANDS": "NL",
        "AUSTRALIA": "AU",
    }
    if up in known:
        return known[up]
    if len(up) == 2 and up.isalpha():
        return up
    return up[:16] or "UNKNOWN"


def countries_from_meta(proxy_meta: dict):
    buckets = {}
    for _proxy, meta in (proxy_meta or {}).items():
        if not isinstance(meta, dict):
            continue
        code = country_code(str(meta.get("country") or "Unknown"))
        try:
            score = int(meta.get("score") or 0)
        except Exception:
            score = 0
        row = buckets.setdefault(code, {"code": code, "count": 0, "best": 0, "score_sum": 0})
        row["count"] += 1
        row["score_sum"] += score
        row["best"] = max(row["best"], score)
    rows = list(buckets.values())
    for row in rows:
        row["avg"] = int(row["score_sum"] / max(1, row["count"]))
    rows.sort(key=lambda r: (-r["best"], -r["count"], r["code"]))
    return rows


def render_pool_picker(st, proxy_meta: dict):
    """Call from the sidebar. Returns pool_mode, country, mix_list."""
    if "pool_mode" not in st.session_state:
        st.session_state.pool_mode = "all"
    if "pool_locked" not in st.session_state:
        st.session_state.pool_locked = True
    if "picked_countries" not in st.session_state:
        st.session_state.picked_countries = ["US"]

    st.markdown("**Pool mode**")
    if st.session_state.pool_locked:
        st.success(f"Set: {st.session_state.pool_mode}")
        if st.session_state.pool_mode in ("country", "mix"):
            st.caption("Picked: " + ", ".join(st.session_state.picked_countries))
        if st.button("Change pool", key="pool_change"):
            st.session_state.pool_locked = False
            st.rerun()
    else:
        choice = st.radio(
            "Choose pool",
            ["all", "us_only", "country", "mix"],
            index=["all", "us_only", "country", "mix"].index(st.session_state.pool_mode),
            key="pool_radio",
        )
        if choice in ("all", "us_only"):
            st.session_state.pool_mode = choice
            st.session_state.pool_locked = True
            st.rerun()
        rows = countries_from_meta(proxy_meta)
        if not rows:
            st.warning("No country scores yet. Fetch proxies first. Using US.")
            rows = [{"code": "US", "count": 0, "best": 0, "avg": 0}]
        picked = []
        st.caption("Highest score first. Check the countries, then Done.")
        for row in rows:
            label = f"{row['code']}  score={row['best']}  n={row['count']}"
            if st.checkbox(label, value=row["code"] in st.session_state.picked_countries, key=f"cc_{choice}_{row['code']}"):
                picked.append(row["code"])
        if st.button("Done", key="pool_done"):
            if not picked:
                st.error("Pick at least one country")
            else:
                st.session_state.pool_mode = choice
                st.session_state.picked_countries = picked
                st.session_state.pool_locked = True
                st.rerun()

    mode = st.session_state.pool_mode
    picked = st.session_state.picked_countries or ["US"]
    country = picked[0]
    mix = ",".join(picked)
    return mode, country, mix
