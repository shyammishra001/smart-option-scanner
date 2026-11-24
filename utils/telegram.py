from __future__ import annotations

from typing import Any, Dict, List, Tuple

import requests


def send_message(bot_token: str, chat_id: str, text: str, timeout: int = 10) -> Tuple[bool, str]:
    """Telegram pe ek message bhejta hai. Fail ho to exception nahi, False return karta hai."""
    if not bot_token or not chat_id:
        return False, "Telegram token ya chat ID nahi hai"

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

    try:
        response = requests.post(
            url,
            data={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=timeout,
        )
        if response.status_code == 200:
            payload = response.json()
            if payload.get("ok"):
                return True, ""
        return False, "Telegram nahi gaya, Token check karo"
    except Exception:
        return False, "Telegram nahi gaya, Token check karo"


def _format_signal(signal: Dict[str, Any]) -> str:
    return (
        f"🔥 <b>NEW SIGNAL - {signal.get('option_symbol', '')}</b>\n"
        f"Expiry: {signal.get('expiry', '')}\n"
        f"Entry: {signal.get('entry', 0):g} | "
        f"SL: {signal.get('stop_loss', 0):g} | "
        f"TGT1: {signal.get('target1', 0):g} | "
        f"TGT2: {signal.get('target2', 0):g}\n"
        f"Capital Need: ₹{signal.get('total_cost', 0):,.0f} | "
        f"Score: {signal.get('score', 0)}/100\n"
        f"Stock: {signal.get('stock_name', '')} ({signal.get('stock_code', '')})\n"
        f"Reason: {signal.get('reason', '')}"
    )


def send_signal_messages(
    bot_token: str,
    chat_id: str,
    signals: List[Dict[str, Any]],
) -> Tuple[bool, str]:
    """Top signals Telegram pe bhejta hai. Ek bhi fail ho to warning message."""
    if not signals:
        return True, ""

    if not bot_token or not chat_id:
        return False, "Telegram nahi gaya, Token check karo"

    all_ok = True

    for signal in signals:
        ok, _ = send_message(bot_token, chat_id, _format_signal(signal))
        if not ok:
            all_ok = False

    if all_ok:
        return True, ""

    return False, "Telegram nahi gaya, Token check karo"