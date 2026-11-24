from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, Optional

import pandas as pd
import streamlit as st

from utils.indmoney import (
    INDmoneyClient,
    INDmoneyError,
    build_master,
    search_stocks,
)
from utils.strategy import run_scan
from utils.telegram import send_signal_messages


# ----------------------------------------------------------------------
# Page config
# ----------------------------------------------------------------------
st.set_page_config(
    page_title="Smart Option Scanner — INDmoney + Telegram",
    page_icon="🚀",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    .main-title { font-size: 2.15rem; font-weight: 800; margin-bottom: 0; }
    .sub-title { color: #5f6368; font-size: 0.95rem; margin-top: 0; }
    .small-note { color: #5f6368; font-size: 0.85rem; }
    </style>
    """,
    unsafe_allow_html=True,
)


# ----------------------------------------------------------------------
# Session state
# ----------------------------------------------------------------------
def init_state() -> None:
    defaults = {
        "connected": False,
        "client": None,
        "master": None,
        "scan_result": None,
        "scan_time": None,
        "connected_at": None,
        "profile_name": "",
        "api_key_default": "",
        "token_default": "",
        "tg_token": "",
        "tg_chat": "",
        "search_box": "",
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def secret(key: str, default: str = "") -> str:
    try:
        return str(st.secrets.get(key, default))
    except Exception:
        return default


def reset_connection() -> None:
    for key in (
        "connected", "client", "master", "scan_result", "scan_time",
        "connected_at", "profile_name",
    ):
        st.session_state[key] = None if key in ("client", "master", "scan_result", "scan_time", "connected_at") else False

    st.session_state["connected"] = False
    st.session_state["client"] = None
    st.session_state["master"] = None
    st.session_state["scan_result"] = None
    st.session_state["scan_time"] = None
    st.session_state["connected_at"] = None
    st.session_state["profile_name"] = ""


def load_master(client: INDmoneyClient) -> Dict[str, Any]:
    equity = client.fetch_instruments("equity")
    fno = client.fetch_instruments("fno")
    index = client.fetch_instruments("index")
    return build_master(equity, fno, index)


# ----------------------------------------------------------------------
# Login / Setup page
# ----------------------------------------------------------------------
def render_login() -> None:
    st.markdown('<p class="main-title">🔐 Smart Option Scanner</p>', unsafe_allow_html=True)
    st.markdown(
        '<p class="sub-title">INDmoney live data + Telegram alerts | Sirf signal, auto order nahi</p>',
        unsafe_allow_html=True,
    )

    st.info(
        "INDmoney access token sirf **24 hours** valid hota hai. "
        "INDstocks dashboard → API Trading → Access Tokens se naya token generate karo."
    )

    with st.form("login_form"):
        col1, col2 = st.columns(2)

        with col1:
            api_key = st.text_input(
                "1. INDmoney API Key (optional)",
                type="password",
                value=st.session_state.get("api_key_default") or secret("INDMONEY_API_KEY"),
                help="Client ID / API Key. Sirf token se bhi kaam chal jata hai.",
            )
            tg_token = st.text_input(
                "3. Telegram Bot Token",
                type="password",
                value=st.session_state.get("tg_token") or secret("TELEGRAM_BOT_TOKEN"),
                help="BotFather se mila token.",
            )

        with col2:
            token = st.text_input(
                "2. INDmoney API Secret / Access Token",
                type="password",
                value=st.session_state.get("token_default") or secret("INDMONEY_TOKEN"),
                help="Ye 24 ghante me expire hota hai. Har baar naya token paste karo.",
            )
            tg_chat = st.text_input(
                "4. Telegram Chat ID",
                value=st.session_state.get("tg_chat") or secret("TELEGRAM_CHAT_ID"),
                help="@userinfobot se apna chat ID le sakte ho.",
            )

        submitted = st.form_submit_button(
            "🚀 Connect & Start Scanner",
            type="primary",
            use_container_width=True,
        )

    if submitted:
        token = token.strip()
        api_key = api_key.strip()
        tg_token = tg_token.strip()
        tg_chat = tg_chat.strip()

        if not token:
            st.error("INDmoney Access Token daalna zaroori hai.")
            return

        with st.spinner("INDmoney token check ho raha hai..."):
            client = INDmoneyClient(token=token, api_key=api_key)
            try:
                profile = client.test_token()
            except Exception:
                st.error(
                    "Token galat ya expire ho gaya lagta hai. "
                    "INDstocks dashboard se naya token generate karke paste karo."
                )
                return

            profile_name = ""
            if isinstance(profile, dict):
                profile_name = (
                    profile.get("name")
                    or profile.get("display_name")
                    or profile.get("client_id")
                    or ""
                )

        with st.spinner("Market master CSV load ho raha hai... (ek baar 5-10 sec)"):
            try:
                master = load_master(client)
            except Exception:
                st.error("Market data load nahi hua. Internet check karke dobara try karo.")
                return

        st.session_state["client"] = client
        st.session_state["master"] = master
        st.session_state["connected"] = True
        st.session_state["connected_at"] = datetime.now()
        st.session_state["profile_name"] = str(profile_name)
        st.session_state["api_key_default"] = api_key
        st.session_state["token_default"] = token
        st.session_state["tg_token"] = tg_token
        st.session_state["tg_chat"] = tg_chat

        st.success("Connected! Scanner ready hai.")
        st.rerun()

    st.divider()
    st.caption(
        "⚠️ Ye sirf educational scanner hai. Trading me risk hai. "
        "Auto order place nahi hota — sirf signal milta hai. Apne risk pe trade karo."
    )


# ----------------------------------------------------------------------
# Scan UI
# ----------------------------------------------------------------------
def run_scan_ui(client: INDmoneyClient, master: Dict[str, Any], capital: float) -> None:
    progress_bar = st.progress(0)
    status_box = st.empty()

    def progress_cb(pct: float, text: str) -> None:
        progress_bar.progress(min(max(int(pct), 0), 100))
        status_box.info(text)

    try:
        result = run_scan(
            client=client,
            master=master,
            capital=capital,
            progress_cb=progress_cb,
        )
    except Exception:
        progress_bar.empty()
        status_box.empty()
        st.error("Scan fail ho gaya. Token ya internet check karo.")
        return

    progress_bar.empty()
    status_box.empty()

    st.success(
        f"Scan complete — {result['scanned']} stocks dekhe, "
        f"{len(result['results'])} signal mile."
    )

    st.session_state["scan_result"] = result
    st.session_state["scan_time"] = datetime.now()

    if result["results"]:
        ok, _ = send_signal_messages(
            st.session_state.get("tg_token", ""),
            st.session_state.get("tg_chat", ""),
            result["results"],
        )
        if not ok:
            st.warning("Telegram nahi gaya, Token check karo")
    else:
        st.info(
            "Aaj koi stock 70+ score ke saath 5000 capital me fit nahi hua. "
            "Fake breakout / low volume / high lot size ke wajah se reject hue."
        )


# ----------------------------------------------------------------------
# Results
# ----------------------------------------------------------------------
def render_results() -> None:
    result = st.session_state.get("scan_result")
    if not result:
        st.info("👆 SCAN NOW dabao. Scanner Nifty 200 stocks me se best option signals dhoondhega.")
        return

    st.caption(f"Scan time: {result.get('as_of', '')} | Market RS: {result.get('market_rs', 0)}")

    if result.get("market_closed"):
        st.warning("Market band hai — last trading session ka data use hua hai.")

    results = result.get("results", [])

    if not results:
        st.warning("Is scan me koi signal 70+ score ke saath 5000 capital me fit nahi hua.")
    else:
        # Table
        table_rows = []
        for signal in results:
            table_rows.append({
                "Score": signal["score"],
                "Stock": signal["stock_name"],
                "Code": signal["stock_code"],
                "Signal": signal["signal"],
                "Option": signal["option_symbol"],
                "Strike": signal["strike"],
                "Lot": signal["lot_size"],
                "Premium": signal["premium"],
                "Total Cost": signal["total_cost"],
                "Entry": signal["entry"],
                "SL": signal["stop_loss"],
                "T1": signal["target1"],
                "T2": signal["target2"],
                "Expiry": signal["expiry"],
                "Reason": signal["reason"],
            })

        st.subheader("📋 Top Signals")
        st.dataframe(
            pd.DataFrame(table_rows),
            use_container_width=True,
            hide_index=True,
        )

        st.download_button(
            label="⬇️ Signals CSV download",
            data=pd.DataFrame(table_rows).to_csv(index=False).encode("utf-8"),
            file_name="smart_option_signals.csv",
            mime="text/csv",
        )

        st.divider()

        # Cards
        st.subheader("🃏 Signal Cards")

        for index, signal in enumerate(results, 1):
            with st.container(border=True):
                top_left, top_right = st.columns([3, 1])

                with top_left:
                    st.markdown(
                        f"### {index}. {signal['stock_name']} — {signal['signal']}"
                    )
                    st.caption(
                        f"{signal['option_symbol']} | Expiry: {signal['expiry']} | "
                        f"Stock Code: {signal['stock_code']}"
                    )

                with top_right:
                    st.metric("Score", f"{signal['score']}/100")

                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Entry", f"₹{signal['entry']:g}")
                c2.metric("Stop Loss", f"₹{signal['stop_loss']:g}")
                c3.metric("Target 1", f"₹{signal['target1']:g}")
                c4.metric("Target 2", f"₹{signal['target2']:g}")

                st.write(
                    f"**Strike Price:** {signal['strike']:g} | "
                    f"**Lot Size:** {signal['lot_size']} | "
                    f"**Premium:** ₹{signal['premium']:g} | "
                    f"**Total Cost:** ₹{signal['total_cost']:,.0f}"
                )
                st.write(
                    f"**Underlying:** ₹{signal['underlying_ltp']:g} "
                    f"({signal['day_change_pct']:+.2f}%) | "
                    f"**RSI:** {signal['rsi']} | "
                    f"**PCR:** {signal['pcr']} | "
                    f"**Max Loss:** ₹{signal['max_loss']:,.0f}"
                )
                st.write(f"**Reason:** {signal['reason']}")

    # Skipped
    with st.expander("⛔ Reject / Skip hue stocks (reason ke saath)"):
        skipped = result.get("skipped", [])
        if skipped:
            st.dataframe(pd.DataFrame(skipped), use_container_width=True, hide_index=True)
        else:
            st.write("Koi skip nahi hua.")


# ----------------------------------------------------------------------
# Search
# ----------------------------------------------------------------------
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
            st.info("Koi stock nahi mila. Naam thoda alag likh ke dekho.")
        else:
            st.dataframe(
                matches.rename(columns={
                    "symbol": "Stock",
                    "name": "Company",
                    "scrip_code": "Code",
                    "security_id": "Security ID",
                }),
                use_container_width=True,
                hide_index=True,
            )


# ----------------------------------------------------------------------
# Main app
# ----------------------------------------------------------------------
def render_main() -> None:
    client: Optional[INDmoneyClient] = st.session_state.get("client")
    master: Optional[Dict[str, Any]] = st.session_state.get("master")

    if client is None or master is None:
        st.session_state["connected"] = False
        st.rerun()
        return

    # Sidebar
    with st.sidebar:
        st.header("⚙️ Connection")
        profile = st.session_state.get("profile_name") or "Connected"
        st.write(f"**Profile:** {profile}")

        connected_at = st.session_state.get("connected_at")
        if connected_at:
            st.write(f"**Connected:** {connected_at.strftime('%d-%b %H:%M')}")

        if connected_at and datetime.now() - connected_at > timedelta(hours=20):
            st.warning("Token 24 ghante me expire hota hai. Naya token generate karo.")

        if st.button("🔄 Disconnect / Naya Token", use_container_width=True):
            reset_connection()
            st.rerun()

        st.divider()
        st.caption(
            "⚠️ Educational scanner only. Trading me risk hai. "
            "Auto order nahi hota. Apne risk pe trade karo."
        )

    # Header
    st.markdown('<p class="main-title">🚀 Smart Option Scanner</p>', unsafe_allow_html=True)
    st.markdown(
        '<p class="sub-title">INDmoney live data | Nifty 200 scan | ₹5000 capital filter | Telegram alerts</p>',
        unsafe_allow_html=True,
    )

    col1, col2 = st.columns([1, 2])

    with col1:
        capital = st.number_input(
            "Capital (₹)",
            min_value=1000,
            max_value=100000,
            value=5000,
            step=500,
            help="Scanner sirf wahi option suggest karega jo is capital me fit ho.",
        )

    with col2:
        st.write("")
        st.write("")
        scan_clicked = st.button(
            "🚀 SCAN NOW",
            type="primary",
            use_container_width=True,
            key="scan_now",
        )

    st.caption(
        "Scan me 30-90 seconds lag sakte hain — INDmoney data API rate limit 5 requests/sec hai."
    )

    if scan_clicked:
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