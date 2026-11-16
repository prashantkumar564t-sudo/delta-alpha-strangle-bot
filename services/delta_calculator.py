from __future__ import annotations

import json
import logging
import os
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)
IST = timezone(timedelta(hours=5, minutes=30))

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(ROOT_DIR, "data")
CACHE_FILE = os.path.join(CACHE_DIR, "products_cache.json")
CACHE_TTL_SECONDS = 12 * 3600  # 12 hours TTL for products metadata


def parse_expiry_date(date_str: str) -> date | None:
    """Parses DDMMYY string into datetime.date object for calendar-aware comparisons."""
    try:
        return datetime.strptime(date_str, "%d%m%y").date()
    except (ValueError, TypeError):
        return None


class DeltaCalculator:
    def __init__(self, api_client):
        self.client = api_client

    def get_target_expiry_date_str(self) -> str:
        """
        Delta options format: DDMMYY (e.g., 161126 for 16-Nov-2026).
        Delta daily options settle at 17:30:00 IST (12:00:00 UTC).
        After 17:30 IST, rolls over to the next day's expiry date.
        """
        now_ist = datetime.now(IST)
        if (now_ist.hour > 17) or (now_ist.hour == 17 and now_ist.minute >= 30):
            target_date = now_ist.date() + timedelta(days=1)
        else:
            target_date = now_ist.date()

        return target_date.strftime("%d%m%y")

    def _get_products(self) -> list[dict[str, Any]]:
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
                    print(
                        f"[CACHE FALLBACK] Live fetch failed; falling back to stale cache ({len(products)} products)."
                    )
                    return products
            except Exception:
                pass

        print(f"[ERROR] Failed to fetch products: {resp}")
        return []

    def get_10_delta_strikes(
        self,
        symbol: str = "BTC",
        target_delta: float = 0.10,
        expiry_date_str: str | None = None,
        lot_size: int = 1,
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        """
        Selects optimal 10-Delta Call and Put strikes strictly for today's 0-DTE expiry.
        Enforces two-sided orderbook (bids AND asks required), spread <= 40%, and depth.
        """
        target_date_suffix = expiry_date_str or self.get_target_expiry_date_str()
        print(f"[INFO] Looking for 0-DTE Expiry Date Suffix: {target_date_suffix}")

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

        ce_candidates: list[dict[str, Any]] = []
        pe_candidates: list[dict[str, Any]] = []
        available_expiries: set[str] = set()

        for ticker in all_tickers:
            prod_id = ticker.get("product_id")
            prod = products_map.get(prod_id)

            if not prod:
                continue

            contract_type = prod.get("contract_type")
            if contract_type not in ("call_options", "put_options"):
                continue

            symbol_name = prod.get("symbol", "")
            if not symbol_name.startswith(("C-BTC-", "P-BTC-")):
                continue

            # Symbol ke aakhri 6 digit expiry date hote hain (DDMMYY)
            parts = symbol_name.split("-")
            if len(parts) >= 4:
                available_expiries.add(parts[-1])

            # Expiry date filter (Strictly target 0-DTE date suffix)
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
            bid_size = float(quotes.get("bid_size") or 0.0)

            # --- SPREAD & LIQUIDITY SANITY CHECKS ---
            # 1. Enforce two-sided orderbook (reject one-sided or empty books)
            if best_bid <= 0.0 or best_ask <= 0.0:
                continue

            # 2. Enforce minimum $5.00 mark price threshold
            if mark_price < 5.0:
                continue

            # 3. Require active buyers in live orderbook with minimum bid floor
            is_testnet = "testnet" in getattr(self.client, "base_url", "").lower()
            min_bid = 1.0 if is_testnet else 5.0
            if best_bid < min_bid:
                continue

            # 4. Filter out contracts where spread / mark_price > 0.40 (excessive slippage protection)
            spread = best_ask - best_bid
            if (spread / mark_price) > 0.40:
                continue

            # 5. Depth check: Ensure orderbook has sufficient buyers for requested lot size
            if bid_size < float(lot_size):
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
                "best_ask": best_ask,
                "bid_size": bid_size,
            }

            if contract_type == "call_options":
                ce_candidates.append(candidate_info)
            else:
                pe_candidates.append(candidate_info)

        if not ce_candidates and not pe_candidates:
            # Calendar-aware sorting for debug log
            valid_expiries = [e for e in available_expiries if parse_expiry_date(e) is not None]
            sorted_expiries = sorted(valid_expiries, key=lambda e: parse_expiry_date(e) or date.min)
            print(f"[DEBUG] Active Expiries found on Delta: {sorted_expiries}")

        # 3. Target delta (0.10) ke sabse kareeb wali strike select karein
        best_ce = min(ce_candidates, key=lambda x: x["delta_diff"]) if ce_candidates else None
        best_pe = min(pe_candidates, key=lambda x: x["delta_diff"]) if pe_candidates else None

        # 4. Strict 0-DTE Mandate: No forward expiry fallback
        if not best_ce or not best_pe:
            missing = []
            if not best_ce:
                missing.append("CE")
            if not best_pe:
                missing.append("PE")
            print(
                f"[0-DTE NOTICE] No qualifying 10-Delta strikes found for today's 0-DTE expiry "
                f"({target_date_suffix}). Missing: {', '.join(missing)}. "
                f"Strict 0-DTE mandate active — skipping session cleanly."
            )
            return None, None

        return best_ce, best_pe
