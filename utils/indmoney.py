from __future__ import annotations

import io
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

import pandas as pd
import requests

BASE_URL = "https://api.indstocks.com"
IST = timezone(timedelta(hours=5, minutes=30))


class INDmoneyError(Exception):
    """User-friendly INDmoney API error."""


def normalize_symbol(value: Any) -> str:
    """Space, dot, hyphen hata kar symbol ko matchable banata hai."""
    if value is None:
        return ""
    text = str(value).upper().strip()
    text = re.sub(r"-(EQ|BE|BZ|BL|IL|MF|N1|N2|N3)$", "", text)
    text = re.sub(r"[^A-Z0-9]", "", text)
    return text


def chunks(items: List[Any], size: int) -> Iterable[List[Any]]:
    for i in range(0, len(items), size):
        yield items[i:i + size]


def _to_int(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


class INDmoneyClient:
    """
    INDmoney / INDstocks REST client.

    Auth: Authorization: <access_token>
    Base URL: https://api.indstocks.com
    Data APIs: 5 requests/sec — isliye internal throttle 0.22 sec.
    """

    def __init__(self, token: str, api_key: str = "", timeout: int = 25):
        self.token = str(token or "").strip()
        self.api_key = str(api_key or "").strip()
        self.timeout = timeout
        self._bearer = False
        self._lock = threading.Lock()
        self._last_request = 0.0

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _throttle(self) -> None:
        with self._lock:
            now = time.monotonic()
            wait = 0.22 - (now - self._last_request)
            if wait > 0:
                time.sleep(wait)
            self._last_request = time.monotonic()

    def _headers(self) -> Dict[str, str]:
    token = self.token.strip()
    # Double-Bearer bug fix: agar user ne "Bearer xyz" paste kiya to strip
    token = re.sub(r"^[Bb][Ee][Aa][Rr][Ee][Rr]\s+", "", token).strip()
    if self._bearer:
        token = f"Bearer {token}"
    headers = {"Accept": "application/json", "Authorization": token}
    if self.api_key:
        headers["X-API-KEY"] = self.api_key
    return headers

    def _get(self, path: str, params: Optional[Dict[str, Any]] = None,
         raw: bool = False, retries: int = 3) -> Any:
    last_error: Optional[Exception] = None

    for attempt in range(retries):
        self._throttle()
        try:
            response = requests.get(
                f"{BASE_URL}{path}", params=params,
                headers=self._headers(), timeout=self.timeout,
            )

            if response.status_code == 429:
                time.sleep(1.0 + attempt)
                continue

            # Asli API message nikalo
            api_msg = ""
            try:
                err_payload = response.json()
                api_msg = (
                    err_payload.get("message")
                    or err_payload.get("error")
                    or err_payload.get("error_description")
                    or ""
                )
            except Exception:
                api_msg = (response.text or "")[:300]

            if response.status_code in (401, 403):
                if not self._bearer:
                    self._bearer = True
                    continue
                raise INDmoneyError(
                    f"Token galat ya expire (HTTP {response.status_code})"
                    + (f": {api_msg}" if api_msg else "")
                )

            if response.status_code >= 400:
                raise INDmoneyError(
                    f"INDmoney request fail (HTTP {response.status_code})"
                    + (f": {api_msg}" if api_msg else "")
                )

            if raw:
                return response.text

            try:
                payload = response.json()
            except ValueError as exc:
                raise INDmoneyError("INDmoney se galat response aaya.") from exc

            if isinstance(payload, dict) and payload.get("success") is False:
                message = payload.get("message") or payload.get("error") or ""
                raise INDmoneyError(str(message) or "INDmoney ne request reject ki.")

            return payload

        except requests.RequestException as exc:
            last_error = exc
            time.sleep(0.5 * (attempt + 1))

    raise INDmoneyError("INDmoney se data nahi aaya. Internet check karo.") from last_error

    @staticmethod
    def _norm_code(code: Any) -> str:
        return str(code).upper().replace(":", "_").strip()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def test_token(self) -> Dict[str, Any]:
        """Token valid hai ya nahi — /user/profile se check."""
        payload = self._get("/user/profile")
        if isinstance(payload, dict):
            return payload.get("data", payload)
        return {}

    def fetch_instruments(self, source: str) -> pd.DataFrame:
        """source = equity / fno / index — CSV download."""
        text = self._get("/market/instruments", params={"source": source}, raw=True)

        if not text or text.lstrip().startswith("<"):
            raise INDmoneyError("Instruments CSV nahi mili.")

        try:
            df = pd.read_csv(io.StringIO(text), dtype=str, low_memory=False)
        except Exception as exc:
            raise INDmoneyError("Instruments CSV padhne me dikkat aayi.") from exc

        df.columns = [str(c).strip().upper().replace("\ufeff", "") for c in df.columns]
        return df

    def get_full_quotes(self, scrip_codes: List[str]) -> Dict[str, Dict[str, Any]]:
        """Live full quotes — max 1000 instruments ek request me."""
        codes = [self._norm_code(c) for c in scrip_codes if str(c).strip()]
        codes = list(dict.fromkeys(codes))
        result: Dict[str, Dict[str, Any]] = {}

        for batch in chunks(codes, 900):
            payload = self._get(
                "/market/quotes/full",
                params={"scrip-codes": ",".join(batch)},
            )
            data = payload.get("data", payload) if isinstance(payload, dict) else payload

            if isinstance(data, dict):
                for key, value in data.items():
                    result[self._norm_code(key)] = value

            elif isinstance(data, list):
                for item in data:
                    if not isinstance(item, dict):
                        continue
                    key = (
                        item.get("scrip_code")
                        or item.get("scrip-code")
                        or item.get("symbol")
                    )
                    if key:
                        result[self._norm_code(key)] = item

        return result

    def get_historical(
        self,
        scrip_codes: List[str],
        interval: str,
        start_ms: int,
        end_ms: int,
    ) -> Dict[str, pd.DataFrame]:
        """
        Historical candles — ek request me max 5 scrip.
        interval: 1day / 5minute / 15minute etc.
        """
        codes = [self._norm_code(c) for c in scrip_codes if str(c).strip()]
        if not codes:
            return {}
        if len(codes) > 5:
            raise ValueError("Ek request me max 5 scrip-codes allowed hain.")

        payload = self._get(
            f"/market/historical/{interval}",
            params={
                "scrip-codes": ",".join(codes),
                "start_time": int(start_ms),
                "end_time": int(end_ms),
            },
        )

        data = payload.get("data", {}) if isinstance(payload, dict) else {}
        result: Dict[str, pd.DataFrame] = {}

        if isinstance(data, dict):
            for key, value in data.items():
                candles = value.get("candles") if isinstance(value, dict) else value
                df = self._candles_to_df(candles)
                if not df.empty:
                    result[self._norm_code(key)] = df

        return result

    @staticmethod
    def _candles_to_df(candles: Any) -> pd.DataFrame:
        if not candles:
            return pd.DataFrame()

        df = pd.DataFrame(candles)
        df.columns = [str(c).lower().strip() for c in df.columns]

        rename = {
            "timestamp": "ts",
            "open": "o",
            "high": "h",
            "low": "l",
            "close": "c",
            "volume": "v",
        }
        df = df.rename(columns=rename)

        for col in ("ts", "o", "h", "l", "c", "v"):
            if col not in df.columns:
                return pd.DataFrame()

        for col in ("o", "h", "l", "c", "v"):
            df[col] = pd.to_numeric(df[col], errors="coerce")

        ts = pd.to_numeric(df["ts"], errors="coerce")
        if ts.dropna().empty:
            return pd.DataFrame()

        unit = "ms" if ts.max() > 1e12 else "s"
        df["ts"] = pd.to_datetime(ts, unit=unit, utc=True).dt.tz_convert("Asia/Kolkata")
        df = (
            df.dropna(subset=["ts", "c"])
            .sort_values("ts")
            .drop_duplicates("ts")
            .reset_index(drop=True)
        )
        return df[["ts", "o", "h", "l", "c", "v"]]

    def get_expiries(self, underlying: str) -> List[str]:
        """Nearest se latest tak expiry dates, ascending."""
        payload = self._get(
            "/market/instruments/expiries",
            params={"underlying": str(underlying).upper(), "segment": "DERIVATIVE"},
        )

        data = payload.get("data", []) if isinstance(payload, dict) else payload
        if isinstance(data, dict):
            data = data.get("expiries", [])

        dates: List[str] = []
        for item in data or []:
            if isinstance(item, str):
                dates.append(item[:10])
            elif isinstance(item, dict):
                value = item.get("expiry") or item.get("date")
                if value:
                    dates.append(str(value)[:10])

        return sorted(set(dates))

    def get_option_chain(
        self,
        underlying_scrip: Any,
        expiry: str,
        strike_count: int = 10,
    ) -> Dict[str, Any]:
        """
        Option chain — underlying-scrip me sirf SECURITY_ID (equity row).
        expiry YYYY-MM-DD.
        """
        payload = self._get(
            "/market/option-chain",
            params={
                "exchange": "NSE",
                "segment": "EQUITY",
                "underlying-scrip": str(underlying_scrip),
                "expiry": str(expiry)[:10],
                "strike_count": int(strike_count),
            },
        )

        data = payload.get("data", payload) if isinstance(payload, dict) else payload
        if not isinstance(data, dict):
            raise INDmoneyError("Option chain ka response samajh nahi aaya.")

        strikes = data.get("strikes") or {}

        # Kabhi kabhi API list bhejta hai — usko dict me convert karo.
        if isinstance(strikes, list):
            converted: Dict[str, Any] = {}
            for item in strikes:
                if not isinstance(item, dict):
                    continue
                strike = item.get("strike_price") or item.get("strike")
                if strike is None:
                    continue
                converted[str(strike)] = {
                    "ce": item.get("ce"),
                    "pe": item.get("pe"),
                }
            strikes = converted

        return {
            "underlying_ltp": data.get("underlying_ltp"),
            "expiry": data.get("expiry") or expiry,
            "strikes": strikes,
        }


# ----------------------------------------------------------------------
# Master CSV helpers
# ----------------------------------------------------------------------
def _clean_df(df: Optional[pd.DataFrame]) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.copy()
    out.columns = [str(c).strip().upper().replace("\ufeff", "") for c in out.columns]
    return out


def _lot_maps(fno: pd.DataFrame) -> Tuple[Dict[str, int], Dict[str, int]]:
    lot_by_id: Dict[str, int] = {}
    lot_by_symbol: Dict[str, int] = {}

    if fno is None or fno.empty:
        return lot_by_id, lot_by_symbol

    needed = {"SECURITY_ID", "TRADING_SYMBOL", "LOT_UNITS"}
    if not needed.issubset(set(fno.columns)):
        return lot_by_id, lot_by_symbol

    tmp = fno[["SECURITY_ID", "TRADING_SYMBOL", "LOT_UNITS"]].dropna()
    tmp["LOT_UNITS"] = pd.to_numeric(tmp["LOT_UNITS"], errors="coerce")
    tmp = tmp.dropna(subset=["LOT_UNITS"])

    for sid, lot in zip(tmp["SECURITY_ID"].astype(str), tmp["LOT_UNITS"].astype(int)):
        if sid.strip() and lot > 0:
            lot_by_id[sid.strip()] = lot

    for sym, lot in zip(tmp["TRADING_SYMBOL"].astype(str).str.upper(), tmp["LOT_UNITS"].astype(int)):
        if sym.strip() and lot > 0:
            lot_by_symbol[sym.strip()] = lot

    return lot_by_id, lot_by_symbol


def _build_search_df(equity: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "symbol", "name", "security_id", "scrip_code",
        "series", "aliases", "normalized", "aliases_text",
    ]
    if equity is None or equity.empty:
        return pd.DataFrame(columns=columns)

    rows = []
    seen = set()

    for _, row in equity.iterrows():
        exchange = str(row.get("EXCH", "")).strip().upper()
        if exchange and exchange != "NSE":
            continue

        security_id = str(row.get("SECURITY_ID", "")).strip()
        if not security_id or security_id in seen:
            continue

        series = str(row.get("SERIES", "")).strip().upper()
        if series and series not in ("EQ", "BE", "BZ"):
            continue

        trading_symbol = str(row.get("TRADING_SYMBOL", "")).strip()
        symbol_name = str(row.get("SYMBOL_NAME", "")).strip()
        custom_symbol = str(row.get("CUSTOM_SYMBOL", "")).strip()
        underlying_name = str(row.get("UNDERLYING_SCRIP_NAME", "")).strip()

        display = trading_symbol or symbol_name or custom_symbol
        display = re.sub(r"-(EQ|BE|BZ)$", "", display.upper()).strip()
        if not display:
            continue

        aliases = set()
        for value in (trading_symbol, symbol_name, custom_symbol, underlying_name, display):
            norm = normalize_symbol(value)
            if norm:
                aliases.add(norm)

        rows.append({
            "symbol": display,
            "name": symbol_name or display,
            "security_id": security_id,
            "scrip_code": f"NSE_{security_id}",
            "series": series,
            "aliases": sorted(aliases),
            "normalized": normalize_symbol(display),
            "aliases_text": " ".join(sorted(aliases)),
        })
        seen.add(security_id)

    return pd.DataFrame(rows, columns=columns)


def build_master(equity_df: pd.DataFrame, fno_df: pd.DataFrame,
                 index_df: Optional[pd.DataFrame] = None) -> Dict[str, Any]:
    equity = _clean_df(equity_df)
    fno = _clean_df(fno_df)
    index = _clean_df(index_df)

    lot_by_id, lot_by_symbol = _lot_maps(fno)
    search_df = _build_search_df(equity)

    alias_map: Dict[str, Dict[str, Any]] = {}
    for record in search_df.to_dict("records"):
        for alias in record.get("aliases", []):
            alias_map.setdefault(alias, record)

    return {
        "equity": equity,
        "fno": fno,
        "index": index,
        "lot_by_id": lot_by_id,
        "lot_by_symbol": lot_by_symbol,
        "search_df": search_df,
        "alias_map": alias_map,
    }


def resolve_universe(master: Dict[str, Any], symbols: List[str]) -> List[Dict[str, Any]]:
    alias_map = master.get("alias_map", {})
    result = []
    seen = set()

    for symbol in symbols:
        key = normalize_symbol(symbol)
        record = alias_map.get(key)
        if record and record.get("security_id") not in seen:
            result.append(dict(record))
            seen.add(record["security_id"])

    return result


def search_stocks(master: Dict[str, Any], query: str, limit: int = 20) -> pd.DataFrame:
    df = master.get("search_df")
    if df is None or df.empty:
        return pd.DataFrame()

    q = normalize_symbol(query)
    if not q:
        return pd.DataFrame()

    mask = (
        df["normalized"].str.contains(q, regex=False, na=False)
        | df["aliases_text"].str.contains(q, regex=False, na=False)
    )
    cols = ["symbol", "name", "scrip_code", "security_id"]
    return df.loc[mask, cols].head(limit).reset_index(drop=True)