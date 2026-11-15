import os
import json
import time
import logging
from datetime import datetime, timezone, timedelta
from typing import Tuple, Optional, Dict, Any, List

logger = logging.getLogger(__name__)
IST = timezone(timedelta(hours=5, minutes=30))

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(ROOT_DIR, "data")
CACHE_FILE = os.path.join(CACHE_DIR, "products_cache.json")
CACHE_TTL_SECONDS = 12 * 3600  # 12 hours TTL for products metadata

class DeltaCalculator:
    def __init__(self, api_client):
        self.client = api_client

    def get_target_expiry_date_str(self) -> str:
        """
        Delta options format: DDMMYY (e.g., 101126 for 10-Nov-2026).
        Delta daily options settle at 17:30:00 IST (12:00:00 UTC).
        After 17:30 IST, rolls over to the next day's expiry date.
        """
        now_ist = datetime.now(IST)
        if (now_ist.hour > 17) or (now_ist.hour == 17 and now_ist.minute >= 30):
            target_date = now_ist.date() + timedelta(days=1)
        else:
            target_date = now_ist.date()

        return target_date.strftime("%d%m%y")

    def _get_products(self) -> List[Dict[str, Any]]:
        """
        Fetches products metadata with a 12-hour local file cache to prevent
        re-downloading the ~5.6 MB payload on every entry run.
        Routes via request_public (0 KB proxy bandwidth, gzip compressed).
        """
        # 1. Check local cache validity
        if os.path.exists(CACHE_FILE):
            try:
                mtime = os.path.getmtime(CACHE_FILE)
                if (time.time() - mtime) < CACHE_TTL_SECONDS:
                    with open(CACHE_FILE, "r", encoding="utf-8") as f:
                        cached = json.load(f)
                    products = cached.get("result", [])
                    if products:
                        print(f"[CACHE] Loaded {len(products)} products from local cache ({CACHE_FILE}).")
                        return products
            except Exception as e:
                print(f"[CACHE WARN] Could not read products cache: {e}")

        # 2. Fetch fresh via direct internet (request_public, gzip enabled)
        print("[INFO] Fetching fresh /v2/products via public direct connection (0 KB proxy)...")
        resp = self.client.request_public("GET", "/v2/products")
        if resp and resp.get("success"):
            products = resp.get("result", [])
            try:
                os.makedirs(CACHE_DIR, exist_ok=True)
                with open(CACHE_FILE, "w", encoding="utf-8") as f:
                    json.dump(resp, f)
                print(f"[CACHE] Saved {len(products)} products to {CACHE_FILE} (TTL: 12h).")
            except Exception as e:
                print(f"[CACHE WARN] Could not write cache file: {e}")
            return products

        # 3. Fallback to existing stale cache if live request failed
        if os.path.exists(CACHE_FILE):
            try:
                with open(CACHE_FILE, "r", encoding="utf-8") as f:
                    cached = json.load(f)
                products = cached.get("result", [])
                if products:
                    print(f"[CACHE FALLBACK] Live fetch failed; falling back to stale cache ({len(products)} products).")
                    return products
            except Exception:
                pass

        print(f"[ERROR] Failed to fetch products: {resp}")
        return []

    def get_10_delta_strikes(self, symbol: str = "BTC", target_delta: float = 0.10, expiry_date_str: Optional[str] = None) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
        target_date_suffix = expiry_date_str or self.get_target_expiry_date_str()
        print(f"[INFO] Looking for Expiry Date Suffix: {target_date_suffix}")

        # 1. Tickers fetch karein via direct internet (request_public, 0 KB proxy bandwidth)
        tickers_resp = self.client.request_public("GET", "/v2/tickers")
        if not tickers_resp or not tickers_resp.get("success"):
            print(f"[ERROR] Failed to fetch tickers: {tickers_resp}")
            return None, None

        all_tickers = tickers_resp.get("result", [])

        # 2. Products details fetch karein (with 12h local caching)
        products_list = self._get_products()
        if not products_list:
            return None, None

        products_map = {p["id"]: p for p in products_list}

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

            # --- SAFETY BOUND: Enforce 0.07 <= abs(delta) <= 0.13 ---
            if not (0.07 <= abs_delta <= 0.13):
                continue

            quotes = ticker.get("quotes") or {}
            mark_price = float(ticker.get("mark_price") or 0.0)
            best_bid = float(quotes.get("best_bid") or 0.0)
            best_ask = float(quotes.get("best_ask") or 0.0)

            # --- SPREAD & LIQUIDITY SANITY CHECKS ---
            # 1. Enforce minimum $5.00 mark price threshold
            if mark_price < 5.0:
                continue

            # 2. Enforce minimum $5.00 best_bid threshold to prevent cheap junk fills (e.g. $0.50 USD)
            # In live production, strictly require BOTH mark_price >= 5.0 and best_bid >= 5.0.
            # On Testnet sandbox, if orderbooks have no synthetic bids (best_bid == 0.0), allow mark_price >= 5.0,
            # but reject any positive bid < 5.0.
            is_testnet = ("testnet" in getattr(self.client, "base_url", "").lower())
            if not is_testnet:
                if best_bid < 5.0:
                    continue
            else:
                if best_bid > 0 and best_bid < 5.0:
                    continue

            # 3. Filter out contracts where spread / mark_price > 0.40 (excessive slippage protection)
            if best_ask > 0 and best_bid > 0 and mark_price > 0:
                spread = best_ask - best_bid
                if (spread / mark_price) > 0.40:
                    continue

            # Extract contract tick_size for precise stop-loss rounding
            tick_size = float(prod.get("tick_size") or 0.1)

            candidate_info = {
                "id": prod_id,
                "symbol": symbol_name,
                "strike_price": float(prod.get("strike_price", 0.0)),
                "tick_size": tick_size,
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

        # Fallback to nearest active expiry if target date has no qualifying strikes (e.g., testnet or off-hours)
        if (not best_ce or not best_pe) and (expiry_date_str is None) and available_expiries:
            sorted_expiries = sorted(list(available_expiries))
            candidate_expiries = [e for e in sorted_expiries if e > target_date_suffix]
            for next_exp in candidate_expiries:
                print(f"[FALLBACK] Target {target_date_suffix} incomplete (CE={bool(best_ce)}, PE={bool(best_pe)}). Checking {next_exp}...")
                fb_ce, fb_pe = self.get_10_delta_strikes(symbol=symbol, target_delta=target_delta, expiry_date_str=next_exp)
                if fb_ce and fb_pe:
                    return fb_ce, fb_pe

        return best_ce, best_pe
