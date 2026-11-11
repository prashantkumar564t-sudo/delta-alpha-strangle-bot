import logging
from datetime import datetime, timezone, timedelta
from typing import Tuple, Optional, Dict, Any, List

logger = logging.getLogger(__name__)
IST = timezone(timedelta(hours=5, minutes=30))

class DeltaCalculator:
    def __init__(self, api_client):
        self.client = api_client

    def get_target_expiry_date_str(self) -> str:
        """
        Delta options format: DDMMYY (jaise 101126 kal ke liye, 091126 aaj ke liye)
        Delta par daily settlement 5:30 PM IST (12:00 UTC) par hota hai.
        5:30 PM ke baad agle din ki expiry target ki jaati hai.
        """
        now_ist = datetime.now(IST)
        
        # Agar 17:30 (5:30 PM) ya uske baad ka time hai, to kal ki expiry target karein
        if (now_ist.hour > 17) or (now_ist.hour == 17 and now_ist.minute >= 30):
            target_date = now_ist.date() + timedelta(days=1)
        else:
            target_date = now_ist.date()

        return target_date.strftime("%d%m%y")

    def get_10_delta_strikes(self, symbol: str = "BTC", target_delta: float = 0.10) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
        target_date_suffix = self.get_target_expiry_date_str()
        print(f"[INFO] Looking for Expiry Date Suffix: {target_date_suffix}")

        # 1. Tickers fetch karein (Greeks aur Mark Price ke liye)
        tickers_resp = self.client.request("GET", "/v2/tickers")
        if not tickers_resp or not tickers_resp.get("success"):
            print(f"[ERROR] Failed to fetch tickers: {tickers_resp}")
            return None, None

        all_tickers = tickers_resp.get("result", [])

        # 2. Products details fetch karein
        products_resp = self.client.request("GET", "/v2/products")
        if not products_resp or not products_resp.get("success"):
            print(f"[ERROR] Failed to fetch products: {products_resp}")
            return None, None

        products_map = {p["id"]: p for p in products_resp.get("result", [])}

        ce_candidates: List[Dict[str, Any]] = []
        pe_candidates: List[Dict[str, Any]] = []
        available_expiries = set()

        for ticker in all_tickers:
            prod_id = ticker.get("product_id")
            prod = products_map.get(prod_id)

            if not prod:
                continue

            contract_type = prod.get("contract_type")
            if contract_type not in ("call_options", "put_options"):
                continue

            symbol_name = prod.get("symbol", "")
            if not (symbol_name.startswith("C-BTC-") or symbol_name.startswith("P-BTC-")):
                continue

            # Symbol ke aakhri 6 digit expiry date hote hain (DDMMYY)
            parts = symbol_name.split("-")
            if len(parts) >= 4:
                available_expiries.add(parts[-1])

            # Expiry date filter
            if not symbol_name.endswith(target_date_suffix):
                continue

            greeks = ticker.get("greeks") or {}
            raw_delta = greeks.get("delta")
            if raw_delta is None:
                continue

            try:
                raw_delta = float(raw_delta)
            except (ValueError, TypeError):
                continue

            abs_delta = abs(raw_delta)
            quotes = ticker.get("quotes") or {}
            mark_price = float(ticker.get("mark_price") or 0.0)
            best_bid = float(quotes.get("best_bid") or 0.0)
            best_ask = float(quotes.get("best_ask") or 0.0)

            # --- SPREAD & LIQUIDITY SANITY CHECKS ---
            # 1. Filter out contracts where best_bid <= 0 (must have buyers in orderbook)
            if best_bid <= 0:
                continue

            # 2. Filter out contracts with mark_price < 5.0 (minimum premium threshold)
            if mark_price < 5.0:
                continue

            # 3. Filter out contracts where spread / mark_price > 0.40 (excessive slippage protection)
            if best_ask > 0 and mark_price > 0:
                spread = best_ask - best_bid
                if (spread / mark_price) > 0.40:
                    continue

            candidate_info = {
                "id": prod_id,
                "symbol": symbol_name,
                "strike_price": float(prod.get("strike_price", 0.0)),
                "delta": raw_delta,
                "abs_delta": abs_delta,
                "delta_diff": abs(abs_delta - target_delta),
                "mark_price": mark_price,
                "best_bid": best_bid,
                "best_ask": best_ask
            }

            if contract_type == "call_options":
                ce_candidates.append(candidate_info)
            else:
                pe_candidates.append(candidate_info)

        if not ce_candidates and not pe_candidates:
            print(f"[DEBUG] Active Expiries found on Delta: {sorted(list(available_expiries))}")

        # 3. Target delta (0.10) ke sabse kareeb wali strike select karein
        best_ce = min(ce_candidates, key=lambda x: x["delta_diff"]) if ce_candidates else None
        best_pe = min(pe_candidates, key=lambda x: x["delta_diff"]) if pe_candidates else None

        return best_ce, best_pe