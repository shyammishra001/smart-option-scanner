from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from .indmoney import (
    INDmoneyClient,
    INDmoneyError,
    IST,
    chunks,
    resolve_universe,
)

NIFTY_200: List[str] = [
    "ADANIENT", "ADANIPORTS", "APOLLOHOSP", "ASIANPAINT", "AXISBANK",
    "BAJAJ-AUTO", "BAJFINANCE", "BAJAJFINSV", "BEL", "BHARTIARTL",
    "BPCL", "BRITANNIA", "CIPLA", "COALINDIA", "DRREDDY",
    "EICHERMOT", "ETERNAL", "GRASIM", "HCLTECH", "HDFCBANK",
    "HDFCLIFE", "HINDALCO", "HINDUNILVR", "ICICIBANK", "ITC",
    "INDIGO", "INFY", "JIOFIN", "JSWSTEEL", "KOTAKBANK",
    "LT", "M&M", "MARUTI", "MAXHEALTH", "NESTLEIND",
    "NTPC", "POWERGRID", "SBILIFE", "SBIN", "SHRIRAMFIN",
    "SUNPHARMA", "TATACONSUM", "TATAMOTORS", "TATASTEEL", "TCS",
    "TECHM", "TITAN", "TRENT", "ULTRACEMCO", "WIPRO",
    "ABB", "ACC", "ADANIENSOL", "ADANIGREEN", "ADANIPOWER",
    "AMBUJACEM", "ASTRAL", "AUROPHARMA", "BAJAJHLDNG", "BAJAJHFL",
    "BANKBARODA", "BATAINDIA", "BERGEPAINT", "BHARATFORG", "BHEL",
    "BIOCON", "BOSCHLTD", "BSOFT", "CANBK", "CGPOWER",
    "CHOLAFIN", "COLPAL", "CONCOR", "CROMPTON", "CUMMINSIND",
    "DABUR", "DEEPAKNTR", "DIVISLAB", "DIXON", "DLF",
    "DMART", "ESCORTS", "FEDERALBNK", "GAIL", "GMRINFRA",
    "GNFC", "GODREJCP", "GODREJPROP", "GUJGASLTD", "HAL",
    "HAVELLS", "HDFCAMC", "HEROMOTOCO", "HINDCOPPER", "HUDCO",
    "ICICIGI", "ICICIPRULI", "IDBI", "IDEA", "IEX",
    "INDHOTEL", "INDIAMART", "INDUSTOWER", "IOC", "IRCTC",
    "IRFC", "JINDALSTEL", "JSWENERGY", "JUBLFOOD", "KPITTECH",
    "LAURUSLABS", "LICHSGFIN", "LICI", "LODHA", "LTIM",
    "LUPIN", "MFSL", "MOTHERSON", "MPHASIS", "MRF",
    "NAUKRI", "NHPC", "NMDC", "OBEROIRLTY", "OFSS",
    "OIL", "PAGEIND", "PEL", "PETRONET", "PFC",
    "PIDILITIND", "PNB", "POLYCAB", "PVRINOX", "RAJESHEXPO",
    "RAMCOCEM", "RECLTD", "RELIANCE", "SAIL", "SBICARD",
    "SHREECEM", "SIEMENS", "SONACOMS", "SRF", "SUNTV",
    "SUPREMEIND", "SYNGENE", "TATACHEM", "TATACOMM", "TATAELXSI",
    "TATAPOWER", "TIINDIA", "TORNTPHARM", "TORNTPOWER", "TVSMOTOR",
    "UBL", "UNITDSPR", "UPL", "VBL", "VEDL",
    "VOLTAS", "YESBANK", "ZEEL", "ZYDUSLIFE",
    "AAVAS", "ABCAPITAL", "ABFRL", "AIAENG", "AJANTPHARM",
    "ALKEM", "APLAPOLLO", "ATUL", "AUBANK", "BALKRISIND",
    "BANKINDIA", "BAYERCROP", "BDL", "CAMS", "CDSL",
    "CESC", "CUB", "CYIENT", "DELHIVERY", "DEVYANI",
    "EMAMILTD", "ENDURANCE", "EXIDEIND", "FORTIS", "GLENMARK",
    "GODFRYPHLP", "GRINDWELL", "HAPPSTMNDS", "HATSUN", "HONAUT",
    "IDFCFIRSTB", "INDIGOPNTS", "INDIANB", "IPCALAB", "JBCHEPHARM",
    "JKCEMENT", "JSL", "JUBLPHARMA", "KANSAINER", "KAYNES",
    "KEI", "KFINTECH", "KIMS", "KPRMILL", "LATENTVIEW",
    "LINDEINDIA", "MANKIND", "MEDANTA", "METROBRAND", "MGL",
    "MUTHOOTFIN", "NAVINFLUOR", "NYKAA", "OLECTRA", "PAYTM",
    "PERSISTENT", "PIIND", "PNBHOUSING", "POLYMED", "PRESTIGE",
    "RADICO", "RAILTEL", "RAINBOW", "RATNAMANI", "RVNL",
    "SJVN", "SONATSOFTW", "STARHEALTH", "SUMICHEM", "TANLA",
    "TATATECH", "THERMAX", "TRIDENT", "TTKPRESTIG", "UNOMINDA",
    "UTIAMC", "VINATIORGA", "WELCORP", "WHIRLPOOL", "ZENSARTECH",
]


def _f(value: Any, default: float = np.nan) -> float:
    try:
        if value is None or value == "":
            return default
        num = float(value)
        return num if math.isfinite(num) else default
    except (TypeError, ValueError):
        return default


def _report(cb: Optional[Callable[[float, str], None]], pct: float, text: str) -> None:
    if cb is None:
        return
    try:
        cb(max(0.0, min(100.0, float(pct))), str(text))
    except Exception:
        pass


def _quote_ltp(quote: Any) -> float:
    if not isinstance(quote, dict):
        return np.nan

    for key in ("last_price", "ltp", "lastPrice", "close"):
        value = _f(quote.get(key))
        if value == value and value > 0:
            return value

    ohlc = quote.get("ohlc") or {}
    if isinstance(ohlc, dict):
        for key in ("close", "last_price"):
            value = _f(ohlc.get(key))
            if value == value and value > 0:
                return value

    return np.nan


def _quote_change_pct(quote: Any, fallback_price: float, prev_close: float) -> float:
    if isinstance(quote, dict):
        for key in ("change_percent", "changePct", "pct_change", "change_percentage"):
            value = _f(quote.get(key))
            if value == value:
                return float(value)
    if prev_close > 0:
        return (fallback_price / prev_close - 1) * 100
    return 0.0


def _rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi.fillna(50)


def _macd(series: pd.Series) -> Tuple[pd.Series, pd.Series]:
    ema12 = series.ewm(span=12, adjust=False).mean()
    ema26 = series.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    return macd_line, signal_line


def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    prev_close = df["c"].shift(1)
    tr = pd.concat(
        [
            df["h"] - df["l"],
            (df["h"] - prev_close).abs(),
            (df["l"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.rolling(period).mean()


def _vwap_value(today: pd.DataFrame) -> float:
    if today is None or today.empty:
        return np.nan

    typical = (today["h"] + today["l"] + today["c"]) / 3
    cum_volume = today["v"].cumsum()
    if cum_volume.iloc[-1] <= 0:
        return float(today["c"].iloc[-1])

    return float((typical * today["v"]).cumsum().iloc[-1] / cum_volume.iloc[-1])


def _vcp_score(daily: pd.DataFrame, direction: str) -> Tuple[int, List[str]]:
    if daily is None or len(daily) < 25:
        return 0, []

    recent = daily.tail(20).reset_index(drop=True)
    ranges: List[float] = []

    for i in range(4):
        part = recent.iloc[i * 5 : (i + 1) * 5]
        if len(part) < 2:
            continue
        mean_close = _f(part["c"].mean(), 0)
        if mean_close <= 0:
            continue
        ranges.append((part["h"].max() - part["l"].min()) / mean_close * 100)

    contraction = False
    if len(ranges) >= 3:
        contraction = (
            all(ranges[i] > ranges[i + 1] * 1.02 for i in range(len(ranges) - 1))
            and ranges[-1] < ranges[0] * 0.8
        )

    vol_dry = recent["v"].tail(5).mean() < recent["v"].mean() * 0.85
    vol_expansion = recent["v"].tail(3).max() > recent["v"].mean() * 1.5

    score = 0
    tags: List[str] = []

    if contraction:
        score += 8
        tags.append("VCP Contraction")
    if vol_dry:
        score += 6
        tags.append("Volume Dry-up")
    if vol_expansion:
        score += 6
        tags.append("Volume Expansion")

    return min(score, 20), tags


def _orb_score(intraday: pd.DataFrame, direction: str) -> Tuple[int, List[str], Dict[str, Any]]:
    if intraday is None or len(intraday) < 5:
        return 0, [], {}

    data = intraday.copy()
    data["date"] = data["ts"].dt.date
    last_date = data["date"].max()
    today = data[data["date"] == last_date].reset_index(drop=True)

    if len(today) < 5:
        return 0, [], {}

    opening = today.iloc[:3]
    orb_high = float(opening["h"].max())
    orb_low = float(opening["l"].min())
    last = today.iloc[-1]

    avg_volume = today["v"].iloc[3:-1].mean()
    if not math.isfinite(avg_volume) or avg_volume <= 0:
        avg_volume = today["v"].mean()

    volume_ratio = float(last["v"] / avg_volume) if avg_volume > 0 else 0.0

    if direction == "BULL":
        breakout = float(last["c"]) > orb_high * 1.0005
    else:
        breakout = float(last["c"]) < orb_low * 0.9995

    score = 0
    tags: List[str] = []

    if breakout:
        score += 12
        tags.append("ORB Breakout")
    if volume_ratio >= 1.5:
        score += 8
        tags.append(f"Volume {volume_ratio:.1f}x")

    return min(score, 20), tags, {
        "orb_high": orb_high,
        "orb_low": orb_low,
        "volume_ratio": round(volume_ratio, 2),
        "last_close": float(last["c"]),
        "breakout": breakout,
    }


def _tech_score(daily: Optional[pd.DataFrame], intraday: Optional[pd.DataFrame], quote: Any, market_rs: float) -> Optional[Dict[str, Any]]:
    if daily is None or intraday is None:
        return None
    if len(daily) < 60 or len(intraday) < 5:
        return None

    d = daily.sort_values("ts").reset_index(drop=True)
    i5 = intraday.sort_values("ts").reset_index(drop=True)

    price = _quote_ltp(quote)
    if not (price == price) or price <= 0:
        price = _f(d["c"].iloc[-1], 0)
    if price <= 0:
        return None

    ema20 = d["c"].ewm(span=20, adjust=False).mean()
    ema50 = d["c"].ewm(span=50, adjust=False).mean()
    ema200 = d["c"].ewm(span=200, adjust=False).mean()

    e20 = _f(ema20.iloc[-1], price)
    e50 = _f(ema50.iloc[-1], price)
    e200 = _f(ema200.iloc[-1], e50)

    previous_close = np.nan
    if isinstance(quote, dict):
        ohlc = quote.get("ohlc") or {}
        if isinstance(ohlc, dict):
            previous_close = _f(ohlc.get("close"))
    if not (previous_close == previous_close) or previous_close <= 0:
        previous_close = _f(d["c"].iloc[-2], price) if len(d) >= 2 else price

    day_change_pct = _quote_change_pct(quote, price, previous_close)

    if len(d) >= 21:
        base_20 = _f(d["c"].iloc[-21], price)
        rs_return = (price / base_20 - 1) * 100 if base_20 > 0 else 0.0
    else:
        rs_return = 0.0

    bull_trend = 0
    if price > e50: bull_trend += 8
    if e50 > e200: bull_trend += 7
    if len(ema50) >= 11 and ema50.iloc[-1] > ema50.iloc[-11]: bull_trend += 5
    if rs_return > market_rs: bull_trend += 10

    bear_trend = 0
    if price < e50: bear_trend += 8
    if e50 < e200: bear_trend += 7
    if len(ema50) >= 11 and ema50.iloc[-1] < ema50.iloc[-11]: bear_trend += 5
    if rs_return < market_rs: bear_trend += 10

    i5 = i5.copy()
    i5["date"] = i5["ts"].dt.date
    today = i5[i5["date"] == i5["date"].max()].reset_index(drop=True)
    momentum_df = today if len(today) >= 20 else i5

    rsi_value = _f(_rsi(momentum_df["c"]).iloc[-1], 50)
    macd_line, signal_line = _macd(momentum_df["c"])
    macd_value = _f(macd_line.iloc[-1], 0)
    signal_value = _f(signal_line.iloc[-1], 0)

    vwap = _vwap_value(today) if not today.empty else price
    if not (vwap == vwap): vwap = price

    bull_momentum = 0
    if price > vwap: bull_momentum += 5
    if 55 <= rsi_value <= 70: bull_momentum += 5
    if macd_value > signal_value: bull_momentum += 5

    bear_momentum = 0
    if price < vwap: bear_momentum += 5
    if 30 <= rsi_value <= 45: bear_momentum += 5
    if macd_value < signal_value: bear_momentum += 5

    if price > e50 and e50 > e200 and (bull_trend + bull_momentum) >= (bear_trend + bear_momentum):
        direction = "BULL"
    elif price < e50 and e50 < e200 and (bear_trend + bear_momentum) > (bull_trend + bull_momentum):
        direction = "BEAR"
    else:
        direction = "NEUTRAL"

    vcp_score, vcp_tags = _vcp_score(d, direction) if direction != "NEUTRAL" else (0, [])
    orb_score, orb_tags, orb_meta = _orb_score(i5, direction) if direction != "NEUTRAL" else (0, [], {})

    if direction == "BULL":
        tech_score = bull_trend + bull_momentum
    elif direction == "BEAR":
        tech_score = bear_trend + bear_momentum
    else:
        tech_score = max(bull_trend, bear_trend) + max(bull_momentum, bear_momentum)

    tech_score += vcp_score + orb_score
    tags = list(vcp_tags + orb_tags)

    fake_breakout = False
    if direction == "BULL" and orb_meta.get("orb_high") is not None:
        last_close = orb_meta.get("last_close", price)
        if last_close < vwap:
            recent_high = today["h"].tail(3).max() if len(today) >= 3 else last_close
            if recent_high > orb_meta["orb_high"]:
                fake_breakout = True

    if direction == "BEAR" and orb_meta.get("orb_low") is not None:
        last_close = orb_meta.get("last_close", price)
        if last_close > vwap:
            recent_low = today["l"].tail(3).min() if len(today) >= 3 else last_close
            if recent_low < orb_meta["orb_low"]:
                fake_breakout = True

    if fake_breakout:
        tech_score -= 30
        tags.append("Fake Breakout (-30)")

    tech_score = max(0, min(85, tech_score))

    atr_series = _atr(d, 14)
    atr_value = _f(atr_series.iloc[-1], 0)
    if atr_value <= 0:
        atr_value = price * 0.015

    return {
        "direction": direction,
        "tech_score": float(tech_score),
        "breakdown": {
            "trend": int(bull_trend if direction == "BULL" else bear_trend),
            "vcp": int(vcp_score),
            "orb": int(orb_score),
            "vwap": int(bull_momentum if direction == "BULL" else bear_momentum),
            "oi": 0,
        },
        "tags": tags,
        "price": float(price),
        "day_change_pct": float(day_change_pct),
        "rsi": float(rsi_value),
        "atr": float(atr_value),
        "ema20": float(e20),
        "ema50": float(e50),
        "ema200": float(e200),
        "rs_return": float(rs_return),
        "vwap": float(vwap),
        "orb_high": float(orb_meta.get("orb_high", 0) or 0),
        "orb_low": float(orb_meta.get("orb_low", 0) or 0),
        "fake_breakout": fake_breakout,
    }


def _get_leg(strikes: Dict[str, Any], strike: float, side: str) -> Optional[Dict[str, Any]]:
    for key, value in strikes.items():
        if not isinstance(value, dict): continue
        try:
            if abs(float(key) - float(strike)) < 1e-6:
                leg = value.get(side)
                return leg if isinstance(leg, dict) else None
        except (TypeError, ValueError):
            continue
    return None


def _lot_for_leg(leg: Dict[str, Any], lot_by_id: Dict[str, int], lot_by_symbol: Dict[str, int]) -> int:
    security_id = str(leg.get("security_id", "")).strip()
    if security_id and security_id in lot_by_id:
        return int(lot_by_id[security_id])

    trading_symbol = str(leg.get("trading_symbol", "")).strip().upper()
    if trading_symbol and trading_symbol in lot_by_symbol:
        return int(lot_by_symbol[trading_symbol])

    return 0


def _option_score(chain: Dict[str, Any], direction: str, day_change_pct: float, spot_fallback: float = 0.0) -> Tuple[int, List[str], Dict[str, Any]]:
    strikes = chain.get("strikes") or {}
    if not strikes: return 0, [], {}

    ce_oi_total = pe_oi_total = 0.0
    ce_oi_change = pe_oi_change = 0.0
    oi_by_strike: Dict[float, float] = {}

    for key, value in strikes.items():
        if not isinstance(value, dict): continue
        try: strike = float(key)
        except (TypeError, ValueError): continue

        ce = value.get("ce") or {}
        pe = value.get("pe") or {}

        ce_oi = _f(ce.get("oi"), 0)
        pe_oi = _f(pe.get("oi"), 0)
        ce_prev = _f(ce.get("previous_oi"), 0)
        pe_prev = _f(pe.get("previous_oi"), 0)

        ce_oi_total += ce_oi
        pe_oi_total += pe_oi
        ce_oi_change += ce_oi - ce_prev
        pe_oi_change += pe_oi - pe_prev
        oi_by_strike[strike] = ce_oi + pe_oi

    if not oi_by_strike: return 0, [], {}

    pcr = pe_oi_total / ce_oi_total if ce_oi_total > 0 else 0.0

    spot = _f(chain.get("underlying_ltp"), 0) or spot_fallback
    strike_list = sorted(oi_by_strike.keys())

    atm = None
    max_oi_strike = max(strike_list, key=lambda x: oi_by_strike[x])
    if spot > 0:
        atm = min(strike_list, key=lambda x: abs(x - spot))

    change = _f(day_change_pct, 0)
    score = 0
    tags: List[str] = []

    if direction == "BULL":
        if change > 0 and ce_oi_change > 0: score += 6; tags.append("Long Buildup")
    else:
        if change < 0 and pe_oi_change > 0: score += 6; tags.append("Short Buildup")

    if 0.8 <= pcr <= 1.2: score += 5; tags.append("PCR 0.8-1.2")
    elif 0.7 <= pcr <= 1.3: score += 3

    if atm is not None and max_oi_strike in strike_list:
        atm_index = strike_list.index(atm)
        max_index = strike_list.index(max_oi_strike)
        if abs(max_index - atm_index) <= 1: score += 4; tags.append("OI near ATM")

    return min(score, 15), tags, {
        "pcr": round(float(pcr), 2),
        "atm": atm,
        "max_oi_strike": max_oi_strike,
    }


def _pick_trade(chain: Dict[str, Any], lot_by_id: Dict[str, int], lot_by_symbol: Dict[str, int],
                direction: str, capital: float, atr: float, spot_fallback: float = 0.0) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    strikes = chain.get("strikes") or {}
    if not strikes: return None, "Option chain khali hai"

    try: strike_prices = sorted({float(k) for k in strikes.keys()})
    except (TypeError, ValueError): return None, "Strike data galat hai"

    spot = _f(chain.get("underlying_ltp"), 0) or _f(spot_fallback, 0)
    if spot <= 0: return None, "Underlying price nahi mila"

    atm = min(strike_prices, key=lambda x: abs(x - spot))
    atm_index = strike_prices.index(atm)

    side = "ce" if direction == "BULL" else "pe"
    option_type = "CE" if direction == "BULL" else "PE"

    # ATM ke aas paas ke 4 ITM aur 4 OTM check karega
    candidates = []
    for i in range(-4, 5):
        idx = atm_index + i
        if 0 <= idx < len(strike_prices):
            candidates.append(strike_prices[idx])

    # ATM sabse pehle check hoga (Distance based sorting)
    candidates.sort(key=lambda x: abs(x - spot))
    
    fail_reasons = []
    
    # MAX LOSS FIX: Capital ka 30%
    max_allowed_loss = capital * 0.30

    for strike in candidates:
        leg = _get_leg(strikes, strike, side)
        if not leg: continue

        premium = _f(leg.get("last_price"), 0)
        if premium <= 0:
            bid = _f(leg.get("top_bid_price"), 0)
            ask = _f(leg.get("top_ask_price"), 0)
            if bid > 0 and ask > 0: premium = (bid + ask) / 2

        if premium <= 0: continue

        lot = _lot_for_leg(leg, lot_by_id, lot_by_symbol)
        if not lot: continue

        total_cost = premium * lot
        if total_cost > capital: 
            fail_reasons.append(f"Strike {strike:g} Cost ₹{total_cost:,.0f} > Capital")
            continue

        greeks = leg.get("greeks") or {}
        delta = abs(_f(greeks.get("delta"), 0))
        if delta <= 0: delta = 0.5  # fallback

        # 🔴 DELTA FILTER: 0.30 se kam delta (deep OTM) allowed nahi hai
        if delta < 0.20:
            fail_reasons.append(f"Strike {strike:g} Delta ({delta:.2f}) < 0.30")
            continue

        premium_sl = premium * 0.65
        atr_value = _f(atr, 0)
        atr_sl = premium - (delta * atr_value) if atr_value > 0 else 0

        stop_loss = max(premium_sl, atr_sl)
        if stop_loss <= 0 or stop_loss >= premium * 0.98: stop_loss = premium_sl

        stop_loss = round(max(stop_loss, 0.05), 2)
        risk = premium - stop_loss
        if risk < 0.5: continue

        max_loss = risk * lot
        if max_loss > max_allowed_loss: 
            fail_reasons.append(f"Strike {strike:g} Max Loss ₹{max_loss:,.0f} > 30% Capital")
            continue

        target1 = round(premium + 1.5 * risk, 2)
        target2 = round(premium + 2.5 * risk, 2)

        reward_risk = (target2 - premium) / risk if risk > 0 else 0
        if reward_risk < 2.0: continue

        return {
            "strike": float(strike), "option_type": option_type, "side": side,
            "premium": round(float(premium), 2), "entry": round(float(premium), 2),
            "stop_loss": stop_loss, "target1": target1, "target2": target2,
            "risk": round(float(risk), 2), "reward_risk": round(float(reward_risk), 2),
            "lot_size": int(lot), "total_cost": round(float(total_cost), 2),
            "max_loss": round(float(max_loss), 2), "option_security_id": str(leg.get("security_id", "")),
            "delta": round(float(delta), 3), "expiry": chain.get("expiry", ""),
        }, None

    if fail_reasons:
        return None, fail_reasons[0]
    return None, f"Koi strike fit nahi hua"


def _fetch_histories(client: INDmoneyClient, codes: List[str], interval: str,
                     start: datetime, end: datetime, progress_cb: Optional[Callable[[float, str], None]],
                     base_pct: float, span_pct: float) -> Dict[str, pd.DataFrame]:
    out: Dict[str, pd.DataFrame] = {}
    total = len(codes)
    if total == 0: return out

    start_ms = int(start.timestamp() * 1000)
    end_ms = int(end.timestamp() * 1000)
    batches = list(chunks(codes, 5))

    for index, batch in enumerate(batches, 1):
        try:
            data = client.get_historical(batch, interval, start_ms, end_ms)
        except INDmoneyError:
            data = {}
            for code in batch:
                try: data.update(client.get_historical([code], interval, start_ms, end_ms))
                except INDmoneyError: continue

        for code in batch:
            df = data.get(code)
            if df is None or df.empty:
                df = data.get(code.replace("NSE_", ""))
                
            if df is not None and not df.empty: 
                out[code] = df

        pct = base_pct + span_pct * index / max(len(batches), 1)
        _report(progress_cb, pct, f"{interval} candles: {min(index * 5, total)}/{total}")

    return out


def run_scan(client: INDmoneyClient, master: Dict[str, Any], capital: float = 5000,
             progress_cb: Optional[Callable[[float, str], None]] = None) -> Dict[str, Any]:
    
    universe = resolve_universe(master, NIFTY_200)
    if not universe: raise RuntimeError("Master CSV me Nifty 200 stocks nahi mile.")

    total = len(universe)
    _report(progress_cb, 2, f"0 / {total} stocks — scan shuru...")

    codes = [stock["scrip_code"] for stock in universe]
    quotes = client.get_full_quotes(codes)
    _report(progress_cb, 8, "Live quotes aa gaye...")

    now = datetime.now(IST)
    daily = _fetch_histories(client, codes, "1day", now - timedelta(days=350), now, progress_cb, 10, 35)
    _report(progress_cb, 45, "Daily candles ready...")

    intraday = _fetch_histories(client, codes, "5minute", now - timedelta(days=6), now, progress_cb, 45, 25)
    _report(progress_cb, 70, "Intraday candles ready...")

    market_closed = False
    sample = next(iter(intraday.values()), None)
    if sample is not None and not sample.empty:
        market_closed = sample["ts"].iloc[-1].date() != now.date()

    returns: List[float] = []
    for stock in universe:
        d = daily.get(stock["scrip_code"])
        if d is not None and len(d) >= 21:
            base = _f(d["c"].iloc[-21], 0)
            if base > 0: returns.append((float(d["c"].iloc[-1]) / base - 1) * 100)
    market_rs = float(np.median(returns)) if returns else 0.0

    all_scored: List[Dict[str, Any]] = []
    technical: List[Dict[str, Any]] = []

    for idx, stock in enumerate(universe, 1):
        code = stock["scrip_code"]
        scored = _tech_score(daily.get(code), intraday.get(code), quotes.get(code, {}), market_rs)

        base = {
            "stock_name": stock["symbol"], "stock_full_name": stock["name"],
            "stock_code": code, "security_id": stock["security_id"],
            "breakdown": {"trend": 0, "vcp": 0, "orb": 0, "vwap": 0, "oi": 0},
        }

        if scored is None:
            all_scored.append({**base, "score": 0, "status": "❌ Data nahi", "reason": "Candles nahi mile"})
            continue

        bd = dict(scored.get("breakdown") or base["breakdown"])

        if scored["direction"] == "NEUTRAL":
            all_scored.append({**base, "breakdown": bd, "score": int(round(scored["tech_score"])),
                "status": "❌ NEUTRAL", "reason": "Trend clear nahi (50EMA / 200EMA mixed)"})
            continue

        if scored["tech_score"] < 45:
            why = []
            if bd["trend"] < 15: why.append("Trend fail")
            if bd["vcp"] < 8: why.append("VCP weak")
            if bd["orb"] < 8: why.append("ORB breakout nahi")
            if bd["vwap"] < 8: why.append("VWAP/momentum weak")
            if "Fake Breakout (-30)" in scored["tags"]: why.append("Fake breakout")
            all_scored.append({**base, "breakdown": bd, "score": int(round(scored["tech_score"])),
                "status": "❌ Low Score", "reason": ", ".join(why) or f"Score {int(round(scored['tech_score']))} < 45"})
            continue

        entry = {**stock, **scored, "breakdown": bd, "score": int(round(scored["tech_score"]))}
        technical.append(entry)
        all_scored.append({**base, "breakdown": bd, "score": int(round(scored["tech_score"])),
            "status": "⏳ Option chain pending", "reason": "", "_code": code})

        if idx % 5 == 0 or idx == total:
            _report(progress_cb, 70 + 5 * idx / total, f"{idx} / {total} stocks check ho gaye")

    technical.sort(key=lambda x: x["tech_score"], reverse=True)
    technical = technical[:15]

    _report(progress_cb, 75, f"{len(technical)} candidates ke option chain check ho rahe hain...")

    results: List[Dict[str, Any]] = []
    skipped: List[Dict[str, str]] = []

    for index, row in enumerate(technical, 1):
        code = row["scrip_code"]
        scored_ref = next((r for r in all_scored if r.get("_code") == code), None)

        try:
            expiries = client.get_expiries(row["symbol"])
            if not expiries:
                if scored_ref: scored_ref["status"] = "❌ Expiry missing"; scored_ref["reason"] = "Expiry list nahi mili"
                skipped.append({"stock": row["symbol"], "reason": "Expiry list nahi mili"})
                continue

            expiry = expiries[0]
            chain = client.get_option_chain(row["security_id"], expiry)

            option_score, option_tags, option_meta = _option_score(chain, row["direction"], row["day_change_pct"], row["price"])
            trade, reason = _pick_trade(chain, master["lot_by_id"], master["lot_by_symbol"], row["direction"], capital, row["atr"], row["price"])

            if scored_ref: scored_ref["breakdown"]["oi"] = int(option_score)
            final_score = int(round(row["tech_score"] + option_score))

            if not trade:
                if scored_ref:
                    scored_ref["score"] = final_score; scored_ref["status"] = "❌ Option Chain Fail"
                    scored_ref["reason"] = reason or "Capital / Premium fit nahi hua"
                skipped.append({"stock": row["symbol"], "reason": reason or "Capital fit nahi"})
                continue

            if final_score < 70:
                if scored_ref:
                    scored_ref["score"] = final_score; scored_ref["status"] = "❌ Score < 70"
                    scored_ref["reason"] = f"Score {final_score}/100 (70 chahiye)"
                skipped.append({"stock": row["symbol"], "reason": f"Score {final_score}/100 < 70"})
                continue

            tags = list(dict.fromkeys(row["tags"] + option_tags))
            reason_text = " + ".join(tags) if tags else "Technical + Option Chain"
            signal = "BULLISH CE" if row["direction"] == "BULL" else "BEARISH PE"

            result_row = {
                "stock_name": row["symbol"], "stock_full_name": row["name"], "stock_code": code,
                "security_id": row["security_id"], "signal": signal,
                "option_symbol": f"{row['symbol']} {trade['strike']:g} {trade['option_type']}",
                "expiry": expiry, "strike": trade["strike"], "lot_size": trade["lot_size"],
                "premium": trade["premium"], "total_cost": trade["total_cost"],
                "entry": trade["entry"], "stop_loss": trade["stop_loss"],
                "target1": trade["target1"], "target2": trade["target2"], "max_loss": trade["max_loss"],
                "score": final_score, "tech_score": round(row["tech_score"], 1), "option_score": option_score,
                "breakdown": dict(scored_ref["breakdown"]) if scored_ref else row["breakdown"],
                "reason": reason_text, "direction": row["direction"],
                "underlying_ltp": round(row["price"], 2), "day_change_pct": round(row["day_change_pct"], 2),
                "rsi": round(row["rsi"], 1), "pcr": option_meta.get("pcr"), "reward_risk": trade["reward_risk"],
            }
            results.append(result_row)

            if scored_ref:
                scored_ref.update({
                    "score": final_score, "status": "✅ Qualified", "reason": reason_text,
                    "entry": trade["entry"], "stop_loss": trade["stop_loss"],
                    "target1": trade["target1"], "target2": trade["target2"],
                })

        except INDmoneyError:
            if scored_ref: scored_ref["status"] = "❌ Option chain error"; scored_ref["reason"] = "Option chain data nahi mila"
            skipped.append({"stock": row["symbol"], "reason": "Option chain data nahi mila"})
        except Exception as exc:
            if scored_ref: scored_ref["status"] = "❌ Error"; scored_ref["reason"] = str(exc)[:80]
            skipped.append({"stock": row["symbol"], "reason": "Scan error"})

        _report(progress_cb, 75 + 20 * index / max(len(technical), 1), f"Option chain: {index}/{len(technical)}")

    for r in all_scored: r.pop("_code", None)

    results.sort(key=lambda x: x["score"], reverse=True)
    top_results = results[:5]

    _report(progress_cb, 100, "Scan complete")

    return {
        "results": top_results, "all_qualified": results, "all_scored": all_scored,
        "scanned": total, "technical_candidates": len(technical), "skipped": skipped,
        "market_rs": round(market_rs, 2), "as_of": now.strftime("%d-%b-%Y %H:%M IST"),
        "market_closed": market_closed, "capital_used": capital,
    }
