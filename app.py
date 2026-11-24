from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Tuple

import pandas as pd
import requests
import streamlit as st

from utils.indmoney import (
    INDmoneyClient,
    INDmoneyError,
    build_master,
    search_stocks,
)
from utils.strategy import run_scan
from utils.telegram import send_signal_messages

API_BASE = "https://api.indstocks.com"

st.set_page_config(
    page_title="Smart Option Scanner — INDmoney",
    page_icon="🚀",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    .main-title { font-size: 2.15rem; font-weight: 800; margin-bottom: 0; }
    .sub-title { color: #5f6368; font-size: 0.95rem; margin-top: 0; }
    </style>
    """,
    unsafe_allow_html=True,
)

def get_secret(key: str, default: str = "") -> str:
    try:
        return str(st.secrets.get(key, default))
    except Exception:
        return default

def init_state() -> None:
    defaults = {
        "connected": False, "client": None, "master": None,
        "scan_result": None, "scan_time": None, "connected_at": None,
        "search_box": "", "login_token_input": "",
        "tg_token": get_secret("TELEGRAM_BOT_TOKEN", ""),
        "tg_chat": get_secret("TELEGRAM_CHAT_ID", ""),
        "user_name": "INDmoney User",
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

def reset_connection() -> None:
    for k in ("client", "master", "scan_result", "scan_time", "connected_at"):
        st.session_state[k] = None
    st.session_state["connected"] = False
    st.session_state["user_name"] = "INDmoney User"

def clean_token(raw: str) -> str:
    token = (raw or "").strip()
    token = re.sub(r"^[Bb][Ee][Aa][Rr][Ee][Rr]\s+", "", token).strip()
    return token

def _extract_reliance_ltp(payload: Any) -> float:
    if not isinstance(payload, dict):
        return 0.0
    data = payload.get("data", payload)
    if not isinstance(data, dict):
        return 0.0
    for key in ("NSE_2885", "NSE:2885", "2885", "RELIANCE"):
        item = data.get(key)
        if isinstance(item, dict):
            for field in ("last_price", "ltp", "lastPrice"):
                try:
                    v = float(item.get(field))
                    if v > 0:
                        return v
                except (TypeError, ValueError):
                    pass
    return 0.0

def test_token_direct(token: str) -> Tuple[bool, str]:
    if not token:
        return False, "Token khali hai"

    variants = [("Bearer", f"Bearer {token}"), ("Raw", token)]
    last_error = ""

    for label, auth_value in variants:
        try:
            r = requests.get(
                f"{API_BASE}/market/quotes/full",
                params={"scrip-codes": "NSE_2885"},
                headers={"Authorization": auth_value, "Accept": "application/json"},
                timeout=15,
            )
        except requests.RequestException as exc:
            last_error = f"Connection issue: {exc}"
            continue

        if r.status_code == 200:
            try:
                ltp = _extract_reliance_ltp(r.json())
            except Exception:
                ltp = 0.0
            suffix = f" — RELIANCE LTP = ₹{ltp}" if ltp else ""
            return True, f"Token sahi hai ({label} auth){suffix}"

        api_msg = ""
        try:
            err = r.json()
            api_msg = (
                err.get("message") or err.get("error")
                or err.get("error_description") or ""
            )
        except Exception:
            api_msg = (r.text or "")[:300]

        last_error = f"HTTP {r.status_code}: {api_msg or 'unknown response'}"

    return False, f"Token fail — {last_error}"

def load_master(client: INDmoneyClient) -> Dict[str, Any]:
    equity = client.fetch_instruments("equity")
    fno = client.fetch_instruments("fno")
    index = client.fetch_instruments("index")
    return build_master(equity, fno, index)

def render_login() -> None:
    st.markdown('<p class="main-title">🔐 Smart Option Scanner</p>', unsafe_allow_html=True)
    st.markdown(
        '<p class="sub-title">INDmoney live data | Sirf signal, auto order nahi</p>',
        unsafe_allow_html=True,
    )

    st.info(
        "INDmoney access token **24 ghante** me expire hota hai. "
        "Naya token: [indstocks.com/app/api-trading/access-tokens]"
        "(https://indstocks.com/app/api-trading/access-tokens)"
    )

    st.text_input(
        "INDmoney API Secret Access Token — Yaha paste karo",
        type="password",
        key="login_token_input",
        placeholder="eyJhbGciOi... ya Bearer eyJhbGciOi...",
    )

    col1, col2 = st.columns(2)
    with col1:
        connect_clicked = st.button(
            "🚀 Connect & Start Scanner",
            type="primary", use_container_width=True, key="btn_connect",
        )
    with col2:
        test_clicked = st.button(
            "🔍 Token Test",
            use_container_width=True, key="btn_test",
        )

    raw_token = st.session_state.get("login_token_input", "")
    token = clean_token(raw_token)

    if test_clicked:
        if not token:
            st.error("Token daalo pehle.")
        else:
            with st.spinner("Token test ho raha hai..."):
                ok, message = test_token_direct(token)
            if ok:
                st.success(message)
            else:
                st.error(message)

    if connect_clicked:
        if not token:
            st.error("Token daalo pehle.")
            return

        with st.spinner("Token check ho raha hai..."):
            ok, message = test_token_direct(token)

        if not ok:
            st.error(message)
            return

        st.success(message)

        with st.spinner("Market master CSV load ho raha hai (5-10 sec)..."):
            client = INDmoneyClient(token=token, api_key="")
            try:
                master = load_master(client)
            except Exception as exc:
                st.error(f"Market data load fail: {exc}")
                return
                
            # API Token se User ka Naam nikalna (Fallback logic improved)
            user_name = "INDmoney User"
            try:
                profile = client.test_token()
                if isinstance(profile, dict):
                    # Check all possible keys for name
                    name_val = (
                        profile.get("name") 
                        or profile.get("full_name")
                        or profile.get("display_name") 
                        or profile.get("user_name") 
                        or profile.get("client_id") 
                    )
                    if name_val:
                        user_name = str(name_val)
            except Exception:
                pass

        st.session_state["client"] = client
        st.session_state["master"] = master
        st.session_state["connected"] = True
        st.session_state["connected_at"] = datetime.now()
        st.session_state["scan_result"] = None
        st.session_state["user_name"] = user_name
        st.rerun()

def run_scan_ui(client: INDmoneyClient, master: Dict[str, Any], capital: float) -> None:
    progress_bar = st.progress(0)
    status_box = st.empty()
    counter_box = st.empty()

    def progress_cb(pct: float, text: str) -> None:
        progress_bar.progress(min(max(int(pct), 0), 100))
        status_box.info(text)
        counter_box.markdown(f"### 🔄 {text}")

    try:
        result = run_scan(
            client=client, master=master, capital=capital, progress_cb=progress_cb,
        )
    except INDmoneyError as exc:
        progress_bar.empty(); status_box.empty(); counter_box.empty()
        st.error(f"Scan fail ho gaya: {exc}")
        return
    except Exception as exc:
        progress_bar.empty(); status_box.empty(); counter_box.empty()
        st.error(f"Scan fail: {exc}")
        return

    progress_bar.empty(); status_box.empty(); counter_box.empty()

    st.success(
        f"Scan complete — {result['scanned']} stocks dekhe, "
        f"{len(result['results'])} signal mile."
    )

    st.session_state["scan_result"] = result
    st.session_state["scan_time"] = datetime.now()

    if result["results"]:
        tg_token = st.session_state.get("tg_token", "").strip()
        tg_chat = st.session_state.get("tg_chat", "").strip()
        user_name = st.session_state.get("user_name", "INDmoney User")
        
        if tg_token and tg_chat:
            with st.spinner("Top 5 signals Telegram pe bheje ja rahe hain..."):
                ok, msg = send_signal_messages(tg_token, tg_chat, result["results"], user_name)
                if ok:
                    st.success("✅ Top 5 signals Telegram par bhej diye gaye!")
                else:
                    st.warning(f"⚠️ {msg}")

def _breakdown_line(row: Dict[str, Any]) -> str:
    bd = row.get("breakdown") or {}
    return (
        f"Trend {bd.get('trend', 0)}/30 + "
        f"VCP {bd.get('vcp', 0)}/20 + "
        f"ORB {bd.get('orb', 0)}/20 + "
        f"VWAP {bd.get('vwap', 0)}/15 + "
        f"OI {bd.get('oi', 0)}/15 = "
        f"**{row.get('score', 0)}/100**"
    )

def render_results() -> None:
    result = st.session_state.get("scan_result")
    if not result:
        st.info("👆 SCAN NOW dabao. Scanner Nifty 200 me se best option signals dhoondhega.")
        return

    st.caption(f"Scan time: {result.get('as_of', '')} | Market RS: {result.get('market_rs', 0)}")
    if result.get("market_closed"):
        st.warning("Market band hai — last session ka data use hua hai.")

    results = result.get("results", [])
    all_scored = result.get("all_scored", [])

    if results:
        st.subheader("✅ Qualified Signals (Score ≥ 70)")
        rows = []
        for s in results:
            rows.append({
                "Stock": s["stock_name"],
                "Strike Price": s["strike"],
                "Current Price": s.get("underlying_ltp", "-"),
                "Score / 100": s["score"],
                "Entry": s["entry"],
                "SL": s["stop_loss"],
                "Target 1": s["target1"],
                "Target 2": s["target2"],
                "Reason": s["reason"],
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

        if st.button("📤 Send Top 5 to Telegram again"):
            tg_token = st.session_state.get("tg_token", "").strip()
            tg_chat = st.session_state.get("tg_chat", "").strip()
            user_name = st.session_state.get("user_name", "INDmoney User")
            
            if not tg_token or not tg_chat:
                st.error("Pehle Streamlit Secrets me Telegram Token aur Chat ID set karo!")
            else:
                with st.spinner("Bhej rahe hain..."):
                    ok, msg = send_signal_messages(tg_token, tg_chat, results, user_name)
                    if ok:
                        st.success("Telegram par bhej diya gaya!")
                    else:
                        st.error(msg)

        st.divider()
        st.subheader("🃏 Signal Cards")
        for i, s in enumerate(results, 1):
            with st.container(border=True):
                cl, cr = st.columns([3, 1])
                with cl:
                    st.markdown(f"### {i}. {s['stock_name']} — {s['signal']}")
                    st.caption(f"{s['option_symbol']} | Expiry: {s['expiry']}")
                with cr:
                    st.metric("Score", f"{s['score']}/100")

                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Entry", f"₹{s['entry']:g}")
                c2.metric("Stop Loss", f"₹{s['stop_loss']:g}")
                c3.metric("Target 1", f"₹{s['target1']:g}")
                c4.metric("Target 2", f"₹{s['target2']:g}")

                st.write(
                    f"**Strike:** {s['strike']:g} | **Lot:** {s['lot_size']} | "
                    f"**Premium:** ₹{s['premium']:g} | **Total Cost:** ₹{s['total_cost']:,.0f}"
                )
                st.markdown(f"**Score breakdown:** `{_breakdown_line(s)}`")
    else:
        st.warning(
            f"⚠️ Top 5 Signals khali hai kyunki koi bhi stock Option Chain aur Capital filter pass nahi kar paya. "
            f"Neeche table me 'Status' check karo. Kuch stocks ka Score 70+ hai, par unka Total Cost, "
            f"ya Max Loss ₹{int(result.get('capital_used', 5000))} ke hisaab se fit nahi baith raha."
        )

    st.divider()
    st.subheader("📊 Sabhi Scored Stocks — Qualified + Rejected")

    if all_scored:
        scan_rows = []
        for r in all_scored:
            scan_rows.append({
                "Stock": r.get("stock_name", ""),
                "Score": r.get("score", 0),
                "Status": r.get("status", ""),
                "Reject Reason (Agar koi ho)": r.get("reason", ""),
            })
        st.dataframe(pd.DataFrame(scan_rows), use_container_width=True, hide_index=True)

def render_search(master: Dict[str, Any]) -> None:
    st.divider()
    st.subheader("🔍 Stock Search (master CSV se)")
    query = st.text_input(
        "Aadha naam likho — jaise REL, TECH, HDFC",
        key="search_box",
        placeholder="REL likhoge to RELIANCE aa jayega...",
    )
    if query:
        matches = search_stocks(master, query, limit=20)
        if matches.empty:
            st.info("Koi stock nahi mila. Naam thoda alag likho.")
        else:
            st.dataframe(
                matches.rename(columns={
                    "symbol": "Stock", "name": "Company",
                    "scrip_code": "Code", "security_id": "Security ID",
                }),
                use_container_width=True, hide_index=True,
            )

def render_main() -> None:
    client: Optional[INDmoneyClient] = st.session_state.get("client")
    master: Optional[Dict[str, Any]] = st.session_state.get("master")
    user_name = st.session_state.get("first_name & last_name", "INDmoney User")

    if client is None or master is None:
        st.session_state["connected"] = False
        st.rerun()
        return

    with st.sidebar:
        st.header("⚙️ Connection")
        st.write("**Status:** Connected")
        st.write(f"**User:** {user_name}")
        
        if st.button("🔄 Disconnect / Naya Token", use_container_width=True):
            reset_connection()
            st.rerun()
            
        st.divider()
        st.caption("⚠️ Educational scanner only. Trading me risk hai.")

    st.markdown('<p class="main-title">🚀 Smart Option Scanner</p>', unsafe_allow_html=True)
    st.markdown(
        '<p class="sub-title">INDmoney live data | Nifty 200 scan | Capital Filter</p>',
        unsafe_allow_html=True,
    )

    col1, col2 = st.columns([1, 2])
    with col1:
        capital = st.number_input(
            "Capital (₹)", min_value=1000, max_value=1000000,
            value=5000, step=1000, key="capital_input"
        )
    with col2:
        st.write("")
        st.write("")
        scan_clicked = st.button(
            "🚀 SCAN NOW", type="primary",
            use_container_width=True, key="scan_now",
        )

    st.caption("Scan me 30-90 sec lag sakte hain — INDmoney rate limit 5 req/sec.")

    if scan_clicked:
        st.session_state["scan_capital_used"] = capital
        run_scan_ui(client, master, float(capital))

    render_results()
    render_search(master)

def main() -> None:
    init_state()
    if not st.session_state.get("connected"):
        render_login()
    else:
        render_main()

if __name__ == "__main__":
    main()
